# -*- coding: utf-8 -*-
"""Mở rộng `stock.lot` để truy vết Linh Kiện Đã Lắp.

FG luôn `tracking='serial'` (1 lot = 1 đơn vị) nên đặt source-of-truth
tại `stock.lot` thay vì `stock.quant`. Module phụ thuộc (vd. `t4_sti`)
chỉ cần `related='lot_id.fg_component_line_ids'` trên `stock.quant`.

`fg_component_line_ids` chỉ liệt kê dòng `used` của các phiếu done — phục
vụ auto-populate UI và báo cáo. Đối với pool free / locking, dùng helper
`_t4_get_committed_components()` (net used − returned, support cả
tracking-by-qty lẫn tracking-by-lot).
"""
from collections import defaultdict

from odoo import api, fields, models


class StockLot(models.Model):
    _inherit = 'stock.lot'

    fg_component_line_ids = fields.Many2many(
        't4.product.creation.line',
        compute='_compute_fg_component_line_ids',
        string='Linh Kiện Đã Lắp',
        help='Danh sách dòng linh kiện đã `used` của các phiếu done. '
             'Lưu ý: KHÔNG net với dòng `returned` — dùng cho UI/báo cáo. '
             'Pool free dùng `_t4_get_committed_components()` để có net qty.',
    )
    fg_all_component_line_ids = fields.Many2many(
        't4.product.creation.line',
        'stock_lot_fg_all_component_line_rel',
        'lot_id',
        'line_id',
        compute='_compute_fg_all_component_line_ids',
        string='Linh Kiện Đã Lắp (Đệ Quy)',
        help='Như `fg_component_line_ids` nhưng đệ quy xuống mọi cấp sub-FG. '
             'Mỗi line giữ nguyên `creation_id` của phiếu lắp cấp đó nên group '
             'theo `creation_id` sẽ tách thành nhiều nhóm theo từng cấp. '
             'UI-only — KHÔNG dùng cho business logic (locking, pool free, '
             'BFS picking…); các logic đó phải dùng `fg_component_line_ids` '
             'direct + `_t4_get_committed_components()`.',
    )

    @api.depends()
    def _compute_fg_component_line_ids(self):
        """Tổng hợp linh kiện đã lắp/định danh cho FG này (UI-only).

        Bao gồm cả:
            - type='assembly' done (lần đầu lắp ráp tạo FG)
            - type='identify' done (lần định danh thêm linh kiện cho FG có sẵn)

        Pattern batch: 1 search duy nhất cho toàn bộ recordset thay vì N
        queries trong vòng lặp — quan trọng khi field được đọc cho nhiều
        lot cùng lúc (vd. related trên stock.quant list).

        Caller sau khi xác nhận phiếu identify nên gọi:
            `lot.invalidate_recordset(['fg_component_line_ids'])`
        để form đang mở refresh ngay (xem `_t4_create_component_lots`).
        """
        lot_ids = [lid for lid in self.ids if lid]
        if not lot_ids:
            self.fg_component_line_ids = False
            return

        records = self.env['t4.product.creation'].sudo().search([
            ('lot_id', 'in', lot_ids),
            ('type', 'in', ['assembly', 'identify']),
            ('state', '=', 'done'),
        ])

        # Group lines by FG lot_id — 1 pass qua records
        Line = self.env['t4.product.creation.line']
        lot_map = {}
        for rec in records:
            used = rec.line_ids.filtered(lambda l: l.state == 'used')
            lid = rec.lot_id.id
            if lid not in lot_map:
                lot_map[lid] = Line
            lot_map[lid] |= used

        for lot in self:
            lot.fg_component_line_ids = lot_map.get(lot.id, Line)

    @api.depends()
    def _compute_fg_all_component_line_ids(self):
        """Đệ quy xuống mọi cấp sub-FG, gom tất cả dòng linh kiện đã `used`.

        BFS theo level: mỗi vòng query batch `t4.product.creation` cho toàn
        bộ frontier (lot_id IN frontier) thay vì N queries — depth × 1 query
        thay vì depth × N queries.

        Cycle guard: dùng `visited` set theo từng root lot. Một lot xuất hiện
        ở 2 nhánh khác nhau của cùng root vẫn chỉ duyệt 1 lần — đủ vì dòng
        line là cùng (line được thêm vào kết quả khi gặp lần đầu).

        Caller sau khi xác nhận phiếu identify/assembly nên gọi:
            `lot.invalidate_recordset(['fg_all_component_line_ids'])`
        cùng với `fg_component_line_ids`.
        """
        Line = self.env['t4.product.creation.line']
        if not any(self.ids):
            self.fg_all_component_line_ids = False
            return

        # Pre-fetch field descriptor for `t4_tree_depth` so we can prime the
        # ORM cache directly. Lý do: context `t4_fg_root_lot_id` ko propagate
        # khi Odoo read m2m → compute `t4_tree_depth` không có root để tính.
        # Workaround: tại đây ta đã biết root + depth_map → set thẳng vào cache
        # cho từng line, adapter đọc field thấy giá trị ngay, bỏ qua compute.
        depth_field = Line._fields.get('t4_tree_depth')
        for lot in self:
            if not lot.id:
                lot.fg_all_component_line_ids = Line
                continue
            collected, depth_map = lot._t4_walk_fg_tree()
            lot.fg_all_component_line_ids = collected
            if depth_field is not None:
                for line in collected:
                    depth = depth_map.get(line.creation_id.id, 0)
                    self.env.cache.set(line, depth_field, depth)

    def _t4_walk_fg_tree(self):
        """BFS đệ quy từ FG lot này, gom dòng linh kiện + map depth.

        :returns: (collected_lines, depth_map) trong đó:
            - `collected_lines`: recordset `t4.product.creation.line` mọi cấp.
            - `depth_map`: dict `{creation_id: depth}` — depth của creation
              = depth của FG mà creation đó tạo ra. Root lot có depth 0; các
              creation tạo FG ở depth N thì tạo line cho components ở
              "subtree" của FG đó, mà line.creation_id depth = N.

              Ý nghĩa cho UI: depth của 1 LINE = depth(line.creation_id) — tức
              là cấp của FG cha (FG mà line này là component). Group theo
              `creation_id` → mọi line trong group cùng depth.

        Cycle guard: visited set theo lot_id.
        """
        self.ensure_one()
        Line = self.env['t4.product.creation.line']
        if not self.id:
            return Line, {}
        Creation = self.env['t4.product.creation'].sudo()
        collected = Line
        depth_map = {}
        visited = {self.id}
        frontier = {self.id}
        depth = 0
        while frontier:
            records = Creation.search([
                ('lot_id', 'in', list(frontier)),
                ('type', 'in', ['assembly', 'identify']),
                ('state', '=', 'done'),
            ])
            next_frontier = set()
            for rec in records:
                depth_map[rec.id] = depth
                used = rec.line_ids.filtered(lambda l: l.state == 'used')
                collected |= used
                for line in used:
                    sub_lot_id = line.lot_id.id
                    if sub_lot_id and sub_lot_id not in visited:
                        visited.add(sub_lot_id)
                        next_frontier.add(sub_lot_id)
            frontier = next_frontier
            depth += 1
        return collected, depth_map

    # ------------------------------------------------------------------
    # Helper: net committed qty của 1 FG cho từng (product, lot) component
    # ------------------------------------------------------------------
    def _t4_get_committed_components(self):
        """Trả về dict net qty của linh kiện đã commit cho FG này.

        :returns: dict {(product_id, lot_id_or_0): net_qty} — net qty
            được tính = sum(used) − sum(returned) qua các phiếu done.
            Chỉ trả về key có net_qty > 0.

        Lưu ý: phải search trực tiếp `t4.product.creation.line` thay vì
        `rec.line_ids`/`rec.line_returned_ids` — 2 field này có domain
        filter `state in ('used', 'returned')` nên đọc từ creation chỉ
        thấy 1 chiều.

        Match key:
          - Tracking != 'none' (lot/serial): key = (product, lot_id).
            Dòng returned phải khớp lot_id để biết "đang trả linh kiện
            nào". Tracking lot có thể partial: returned 2/3 → key giữ
            qty=1.
          - Tracking == 'none': key = (product, 0). Cộng/trừ qty.
        """
        self.ensure_one()
        Line = self.env['t4.product.creation.line'].sudo()
        all_lines = Line.search([
            ('creation_id.lot_id', '=', self.id),
            ('creation_id.type', 'in', ['assembly', 'identify']),
            ('creation_id.state', '=', 'done'),
        ])
        net = defaultdict(float)
        for ln in all_lines:
            if not ln.product_id or not ln.quantity:
                continue
            key = (ln.product_id.id, ln.lot_id.id or 0)
            if ln.state == 'used':
                net[key] += ln.quantity
            elif ln.state == 'returned':
                net[key] -= ln.quantity
        # Loại key có qty <= 0 (đã trả hết hoặc trả vượt — vượt hiển thị
        # cảnh báo nghiệp vụ ở chỗ khác)
        return {k: q for k, q in net.items() if q > 0}
