# -*- coding: utf-8 -*-
"""Mở rộng `stock.lot` để truy vết Linh Kiện Đã Lắp.

FG luôn `tracking='serial'` (1 lot = 1 đơn vị) nên đặt source-of-truth
tại `stock.lot` thay vì `stock.quant`. Module phụ thuộc (vd. `t4_sti`)
chỉ cần `related='lot_id.fg_component_line_ids'` trên `stock.quant`.
"""
from odoo import api, fields, models


class StockLot(models.Model):
    _inherit = 'stock.lot'

    fg_component_line_ids = fields.Many2many(
        't4.product.creation.line',
        compute='_compute_fg_component_line_ids',
        string='Linh Kiện Đã Lắp',
        help='Danh sách linh kiện đã được sử dụng để lắp ráp thành phẩm '
             'này (qua phiếu t4.product.creation type=assembly state=done).',
    )

    @api.depends()
    def _compute_fg_component_line_ids(self):
        """Tổng hợp linh kiện đã lắp/định danh cho FG này.

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
