# -*- coding: utf-8 -*-
from odoo import fields, models


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    t4_creation_id = fields.Many2one(
        't4.product.creation',
        related='move_id.t4_creation_id',
        string='Phiếu Định Danh',
        store=True,
        index=True,
    )
