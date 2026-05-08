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
        Creation = self.env['t4.product.creation'].sudo()
        for lot in self:
            if not lot.id:
                lot.fg_component_line_ids = False
                continue
            records = Creation.search([
                ('lot_id', '=', lot.id),
                ('type', '=', 'assembly'),
                ('state', '=', 'done'),
            ])
            lot.fg_component_line_ids = records.mapped('line_ids').filtered(
                lambda l: l.line_type == 'used'
            )
