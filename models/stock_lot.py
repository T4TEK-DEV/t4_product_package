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
        help='Danh sách dòng linh kiện hiện đang gắn trong FG (net qty). '
             'Đã trừ các dòng `returned` của mọi phiếu done cùng FG theo '
             'key (product, lot). Mục dùng cho UI/báo cáo — pool free / '
             'locking vẫn dùng `_t4_get_committed_components()`.',
    )
    fg_all_component_line_ids = fields.Many2many(
        't4.product.creation.line',
        'stock_lot_fg_all_component_line_rel',
        'lot_id',
        'line_id',
        compute='_compute_fg_all_component_line_ids',
        string='Linh Kiện Đã Lắp',
        help='Như `fg_component_line_ids` nhưng đệ quy xuống mọi cấp sub-FG. '
             'Mỗi line giữ nguyên `creation_id` của phiếu lắp cấp đó nên group '
             'theo `creation_id` sẽ tách thành nhiều nhóm theo từng cấp. '
             'UI-only — KHÔNG dùng cho business logic (locking, pool free, '
             'BFS picking…); các logic đó phải dùng `fg_component_line_ids` '
             'direct + `_t4_get_committed_components()`.',
    )
    fg_component_summary_ids = fields.Many2many(
        't4.product.creation.summary',
        compute='_compute_fg_component_summary_ids',
        string='Cấu Thành',
        help='Aggregate của `fg_all_component_line_ids` theo product. '
             'Gom các dòng cùng product_id thành 1 dòng với '
             'SUM(quantity). View "Cấu Thành" group theo categ_tech_id '
             'của product. UI-only — đọc từ SQL view '
             '`t4.product.creation.summary`.',
    )

    @api.depends()
    def _compute_fg_component_line_ids(self):
        """Tổng hợp linh kiện hiện đang gắn trong FG (net used − returned).

        Bao gồm:
            - type='assembly' done (lần đầu lắp ráp tạo FG)
            - type='identify' done (lần định danh thêm linh kiện cho FG có sẵn)

        Logic net: với mỗi key (product_id, lot_id_or_0), tổng hợp returned
        từ MỌI phiếu done cùng FG → trừ vào used. Used line bị cancel khi
        returned_remaining ≥ used.quantity (consume 1:1 cho serial).

        Pattern batch: 1 search duy nhất cho toàn bộ recordset thay vì N
        queries trong vòng lặp — quan trọng khi field được đọc cho nhiều
        lot cùng lúc (vd. related trên stock.quant list).

        Caller sau khi xác nhận/trả/hủy phiếu nên gọi:
            `lot.invalidate_recordset(['fg_component_line_ids'])`
        để form đang mở refresh ngay (xem `_t4_create_component_lots` và
        `action_confirm`).
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

        # Group lines by FG lot_id — net used vs returned per (product, lot)
        Line = self.env['t4.product.creation.line']
        lot_map = {}
        for lid in lot_ids:
            recs = records.filtered(lambda r: r.lot_id.id == lid)
            if not recs:
                lot_map[lid] = Line
                continue
            lot_map[lid] = self._t4_net_used_vs_returned(recs)

        for lot in self:
            lot.fg_component_line_ids = lot_map.get(lot.id, Line)

    @api.model
    def _t4_net_used_vs_returned(self, creation_records):
        """Filter used lines: trừ returned + dedupe theo (product, lot_id).

        :param creation_records: recordset t4.product.creation (mọi phiếu
            done của cùng 1 FG lot).
        :returns: recordset t4.product.creation.line — used lines còn lại
            sau khi (1) trừ returned theo key, (2) dedupe — mỗi lot chỉ
            xuất hiện 1 lần trên dòng phiếu mới nhất.

        Pass 1 — Net used vs returned per key (product_id, lot_id_or_0):
          - Cộng dồn returned_qty.
          - Duyệt used theo (create_date, id) tăng dần — line cũ bị cancel
            trước. Tracking='serial': mỗi line qty=1, exact 1:1 cancel.
            Tracking='lot'/'none': cancel theo bucket qty từ used cũ nhất.

        Pass 2 — Dedupe theo (product, lot_id) khi lot_id > 0:
          - Cùng 1 lot vật lý không thể "used" trong nhiều phiếu cùng lúc.
            Khi data có duplicate (vd: identify lại sau quy trình bất
            thường), chỉ giữ line ở phiếu mới nhất (create_date max).
          - lot_id = 0 (tracking='none'): KHÔNG dedupe — mỗi lần thêm là
            1 sự kiện riêng, hợp lệ xuất hiện nhiều line.

        Approximation Pass 1: nếu used.qty > returned_remaining > 0
        (partial trả trên lot/none), line vẫn giữ qty gốc.
        """
        Line = self.env['t4.product.creation.line']

        # Aggregate returned across all phiếu
        returned_remaining = defaultdict(float)
        for rec in creation_records:
            for r_line in rec.line_returned_ids:
                if not r_line.product_id or not r_line.quantity:
                    continue
                key = (r_line.product_id.id, r_line.lot_id.id or 0)
                returned_remaining[key] += r_line.quantity

        # Pass 1 — Cancel used by returned (cũ trước).
        all_used = creation_records.line_ids.sorted(
            key=lambda l: (l.create_date or l.id, l.id)
        )
        kept_pass1 = Line
        for u in all_used:
            if not u.product_id or not u.quantity:
                continue
            key = (u.product_id.id, u.lot_id.id or 0)
            if returned_remaining[key] >= u.quantity:
                returned_remaining[key] -= u.quantity
                continue
            kept_pass1 |= u
            returned_remaining[key] = 0

        # Pass 2 — Dedupe theo (product, lot_id) khi lot_id > 0: keep latest.
        # Duyệt theo create_date DESC → line gặp đầu tiên (mới nhất) keep,
        # các line sau cùng key bị skip.
        seen_keys = set()
        kept = Line
        for u in kept_pass1.sorted(
            key=lambda l: (l.create_date or l.id, l.id), reverse=True,
        ):
            lot_id = u.lot_id.id or 0
            if lot_id:
                key = (u.product_id.id, lot_id)
                if key in seen_keys:
                    continue  # đã có line mới hơn cùng lot → skip
                seen_keys.add(key)
            kept |= u
        return kept

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

        # Pre-fetch field descriptors for `t4_tree_depth` + `t4_tree_sort_path`
        # so we can prime the ORM cache directly. Lý do: context
        # `t4_fg_root_lot_id` ko propagate khi Odoo read m2m → compute không
        # có root để tính. Workaround: ta đã biết root + depth_map + sort_paths
        # tại đây → set thẳng vào cache cho từng line, adapter đọc field thấy
        # giá trị ngay, bỏ qua compute.
        depth_field = Line._fields.get('t4_tree_depth')
        sort_field = Line._fields.get('t4_tree_sort_path')
        for lot in self:
            if not lot.id:
                lot.fg_all_component_line_ids = Line
                continue
            collected, depth_map, sort_paths = lot._t4_walk_fg_tree()
            lot.fg_all_component_line_ids = collected
            for line in collected:
                if depth_field is not None:
                    depth = depth_map.get(line.creation_id.id, 0)
                    self.env.cache.set(line, depth_field, depth)
                if sort_field is not None:
                    self.env.cache.set(
                        line, sort_field, sort_paths.get(line.id, '')
                    )

    @api.depends('fg_all_component_line_ids')
    def _compute_fg_component_summary_ids(self):
        """Gom `fg_all_component_line_ids` theo product → records summary.

        Aggregation thực hiện ở Python (không SQL view) vì M2M cha
        `fg_all_component_line_ids` là computed-only — Odoo không tạo
        rel table physical. Mỗi lần compute:
          1. Xoá summary cũ của lot (TransientModel records).
          2. Iterate fg_all_component_line_ids, group theo product_id,
             tích luỹ SUM(quantity).
          3. Batch-create records mới.

        Auto-vacuum của TransientModel sẽ dọn records không còn trỏ tới
        lot nào sau ~4h (theo `_transient_max_hours`).
        """
        Summary = self.env['t4.product.creation.summary'].sudo()
        for lot in self:
            if not lot.id:
                lot.fg_component_summary_ids = Summary
                continue
            # Xoá summary cũ — tránh duplicate khi recompute.
            Summary.search([('lot_id', '=', lot.id)]).unlink()
            # Aggregate theo product.
            agg = {}
            for line in lot.fg_all_component_line_ids:
                pid = line.product_id.id
                if not pid:
                    continue
                if pid not in agg:
                    agg[pid] = {
                        'lot_id': lot.id,
                        'product_id': pid,
                        'product_uom_id': line.product_uom_id.id or False,
                        'quantity': 0.0,
                    }
                agg[pid]['quantity'] += line.quantity or 0.0
            if agg:
                lot.fg_component_summary_ids = Summary.create(
                    list(agg.values())
                )
            else:
                lot.fg_component_summary_ids = Summary

    def _t4_walk_fg_tree(self):
        """BFS đệ quy từ FG lot này, gom dòng linh kiện + map depth + sort path.

        :returns: (collected_lines, depth_map, sort_paths) trong đó:
            - `collected_lines`: recordset `t4.product.creation.line` mọi cấp.
            - `depth_map`: dict `{creation_id: depth}` — depth của creation
              = depth của FG mà creation đó tạo ra. Root lot có depth 0; các
              creation tạo FG ở depth N thì tạo line cho components ở
              "subtree" của FG đó, mà line.creation_id depth = N.
            - `sort_paths`: dict `{line_id: zero-padded index string}` — index
              theo DFS traversal. Adapter dùng để sort records sao cho child
              subtree xuất hiện ngay sau dòng cha (interleaved order).

        Cycle guard: visited set theo lot_id.
        """
        self.ensure_one()
        Line = self.env['t4.product.creation.line']
        if not self.id:
            return Line, {}, {}
        Creation = self.env['t4.product.creation'].sudo()
        collected = Line
        depth_map = {}
        # Per-creation ordered lines + edge map line→child_creation, built
        # during BFS. We then DFS-traverse to derive interleaved sort.
        creation_lines = {}            # {creation_id: [line, ...] sorted by sequence}
        line_to_child_creation = {}    # {line.id: child_creation_id}
        visited = {self.id}
        # `frontier_source` tracks which line in the previous level introduced
        # each lot into the current frontier. Used to link line → child creation
        # when we resolve the creation that builds that lot in the next iteration.
        frontier_source = {self.id: None}
        frontier = {self.id}
        depth = 0
        root_creations = []            # creations at depth 0 (lot_id = self)
        while frontier:
            records = Creation.search([
                ('lot_id', 'in', list(frontier)),
                ('type', 'in', ['assembly', 'identify']),
                ('state', '=', 'done'),
            ])
            next_frontier = set()
            next_frontier_source = {}
            # Net used vs returned per FG lot (gom mọi phiếu của cùng lot trước
            # khi cancel) — đảm bảo returned ở phiếu B cancel used ở phiếu A
            # khi cùng FG. Group records by lot_id (frontier) → recs_of_lot.
            recs_by_lot = defaultdict(lambda: Creation)
            for rec in records:
                recs_by_lot[rec.lot_id.id] |= rec
            netted_lines_by_creation = {}  # {creation_id: recordset kept lines}
            for lot_id_in_frontier, recs in recs_by_lot.items():
                kept_for_lot = self._t4_net_used_vs_returned(recs)
                # Split kept lines back to per-creation dict
                for rec in recs:
                    kept_in_rec = kept_for_lot.filtered(
                        lambda l: l.creation_id.id == rec.id
                    )
                    netted_lines_by_creation[rec.id] = kept_in_rec

            for rec in records:
                depth_map[rec.id] = depth
                used = netted_lines_by_creation.get(rec.id, Line)
                used_sorted = used.sorted(key=lambda l: (l.sequence, l.id))
                collected |= used
                creation_lines[rec.id] = list(used_sorted)
                # Link parent line → this creation (if rec.lot_id was introduced
                # by a specific line in the previous level).
                source_line_id = frontier_source.get(rec.lot_id.id)
                if source_line_id is not None:
                    line_to_child_creation[source_line_id] = rec.id
                elif depth == 0:
                    root_creations.append(rec.id)
                for line in used_sorted:
                    sub_lot_id = line.lot_id.id
                    if sub_lot_id and sub_lot_id not in visited:
                        visited.add(sub_lot_id)
                        next_frontier.add(sub_lot_id)
                        next_frontier_source[sub_lot_id] = line.id
            frontier = next_frontier
            frontier_source = next_frontier_source
            depth += 1
        # DFS traversal — assign incremental sort index in interleaved order:
        # for each creation, walk its lines; if a line introduces a child
        # creation, recurse into that child before continuing.
        sort_paths = {}
        counter = [0]

        def _dfs(creation_id):
            for line in creation_lines.get(creation_id, []):
                sort_paths[line.id] = f"{counter[0]:08d}"
                counter[0] += 1
                child = line_to_child_creation.get(line.id)
                if child is not None:
                    _dfs(child)

        for cid in root_creations:
            _dfs(cid)
        return collected, depth_map, sort_paths

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

    def _t4_committing_fg_lot(self):
        """FG lot đang giữ `self` (lot linh kiện) với NET used − returned > 0.

        Dùng cho các check "không được di chuyển linh kiện độc lập". Khác với
        search thô `state='used'`: helper này NET qua mọi phiếu done (cả
        assembly LẪN identify) của cùng FG — nên khi linh kiện đã được TRẢ
        (tab "Linh Kiện Trả" / phiếu cùng FG) thì net = 0 → KHÔNG còn bị giữ,
        dù dòng `used` gốc (kể cả của phiếu Định Danh LKTP, vốn không có luồng
        trả riêng) vẫn tồn tại trong DB.

        :returns: tuple (fg_lot, creation) của vi phạm đầu tiên còn net > 0;
            (stock.lot rỗng, t4.product.creation rỗng) nếu linh kiện đã tự do.
        """
        self.ensure_one()
        empty_lot = self.env['stock.lot']
        empty_creation = self.env['t4.product.creation']
        if not self.id or not self.product_id:
            return empty_lot, empty_creation
        Line = self.env['t4.product.creation.line'].sudo()
        used_lines = Line.search([
            ('lot_id', '=', self.id),
            ('state', '=', 'used'),
            ('creation_id.type', 'in', ['assembly', 'identify']),
            ('creation_id.state', '=', 'done'),
        ])
        key = (self.product_id.id, self.id)
        seen_fg = set()
        for creation in used_lines.mapped('creation_id'):
            fg_lot = creation.lot_id
            if not fg_lot or fg_lot.id in seen_fg:
                continue
            seen_fg.add(fg_lot.id)
            if fg_lot._t4_get_committed_components().get(key, 0.0) > 0:
                return fg_lot, creation
        return empty_lot, empty_creation
