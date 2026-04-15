# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_combo = fields.Boolean(
        string='Thành Phẩm',
        default=False,
        help='Sản phẩm này là thành phẩm (FG) — có quy trình lắp ráp.',
    )
    component_ids = fields.One2many(
        't4.product.component',
        'parent_product_id',
        string='Danh Sách Linh Kiện',
    )
    component_count = fields.Integer(
        string='Số Linh Kiện',
        compute='_compute_component_count',
    )
    assembly_record_ids = fields.One2many(
        't4.assembly.record',
        'product_tmpl_id',
        string='Lịch Sử Lắp Ráp',
    )
    assembly_count = fields.Integer(
        string='Số Lần Lắp Ráp',
        compute='_compute_assembly_count',
    )

    def _compute_component_count(self):
        for record in self:
            record.component_count = len(record.component_ids)

    def _compute_assembly_count(self):
        data = self.env['t4.assembly.record'].read_group(
            [('product_tmpl_id', 'in', self.ids), ('state', '=', 'done')],
            ['product_tmpl_id'], ['product_tmpl_id'],
        )
        mapped = {d['product_tmpl_id'][0]: d['product_tmpl_id_count'] for d in data}
        for record in self:
            record.assembly_count = mapped.get(record.id, 0)

    def action_view_components(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Linh Kiện',
            'res_model': 't4.product.component',
            'view_mode': 'list,form',
            'domain': [('parent_product_id', '=', self.id)],
            'context': {'default_parent_product_id': self.id},
        }

    def action_view_assembly_records(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Lịch Sử Lắp Ráp',
            'res_model': 't4.assembly.record',
            'view_mode': 'list,form',
            'domain': [('product_tmpl_id', '=', self.id)],
        }
