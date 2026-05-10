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
