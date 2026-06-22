# -*- coding: utf-8 -*-
from odoo import fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

    t4_creation_id = fields.Many2one(
        't4.product.creation',
        string='Phiếu Định Danh',
        ondelete='set null',
        index=True,
        copy=False,
        help='Liên kết về phiếu t4.product.creation (type identify/assembly) '
             'đã tạo ra move này qua _apply_inventory. Cho phép navigate từ '
             'move.line về phiếu gốc khi không qua stock.picking.',
    )
