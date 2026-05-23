# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AssemblyRecordLine(models.Model):
    _name = 't4.assembly.record.line'
    _description = 'Chi Tiết Linh Kiện Lắp Ráp'

    record_id = fields.Many2one(
        't4.assembly.record',
        string='Phiếu Lắp Ráp',
        required=True,
        ondelete='cascade',
    )
    product_id = fields.Many2one(
        'product.product',
        string='Linh Kiện',
        required=True,
    )
    lot_id = fields.Many2one(
        'stock.lot',
        string='Mã Serial/Lot',
        help='Mã sê-ri hoặc số lô của linh kiện sử dụng.',
    )
    quantity = fields.Float(
        string='Số Lượng',
        default=1.0,
        required=True,
    )
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='Đơn Vị',
        related='product_id.uom_id',
    )
    # --- Snapshot giá tại thời điểm lắp ráp ---
    standard_price = fields.Float(
        string='Giá Mua (Snapshot)',
        help='Giá mua linh kiện tại thời điểm lắp ráp.',
    )
    list_price = fields.Float(
        string='Giá Kho (Snapshot)',
        help='Giá kho linh kiện tại thời điểm lắp ráp.',
    )
    total_standard_price = fields.Float(
        string='Tổng Giá Mua',
        compute='_compute_totals',
        store=True,
    )
    total_list_price = fields.Float(
        string='Tổng Giá Kho',
        compute='_compute_totals',
        store=True,
    )
    note = fields.Char(string='Ghi Chú')

    @api.depends('quantity', 'standard_price', 'list_price')
    def _compute_totals(self):
        for line in self:
            line.total_standard_price = line.quantity * line.standard_price
            line.total_list_price = line.quantity * line.list_price
