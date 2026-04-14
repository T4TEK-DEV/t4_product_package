# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductComponent(models.Model):
    _name = 't4.product.component'
    _description = 'Linh Kiện Thành Phẩm (BOM)'
    _order = 'sequence, id'

    sequence = fields.Integer(string='Thứ Tự', default=10)
    parent_product_id = fields.Many2one(
        'product.template',
        string='Thành Phẩm',
        required=True,
        ondelete='cascade',
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Linh Kiện',
        required=True,
        ondelete='restrict',
    )
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Template LK',
        related='product_id.product_tmpl_id',
        store=True,
    )
    quantity = fields.Float(
        string='Số Lượng',
        required=True,
        default=1.0,
    )
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='Đơn Vị',
        related='product_id.uom_id',
    )
    note = fields.Char(string='Ghi Chú')

    _sql_constraints = [
        ('qty_positive', 'CHECK(quantity > 0)', 'Số lượng phải lớn hơn 0.'),
    ]

    @api.constrains('parent_product_id', 'product_id')
    def _check_no_self_reference(self):
        for line in self:
            if line.parent_product_id.id == line.product_tmpl_id.id:
                raise ValidationError(
                    _('Linh kiện không được trùng với thành phẩm chính.')
                )
