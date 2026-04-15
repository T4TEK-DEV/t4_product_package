# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class AssemblyRecord(models.Model):
    _name = 't4.assembly.record'
    _description = 'Phiếu Lắp Ráp Thành Phẩm'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Mã Phiếu',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )
    date = fields.Datetime(
        string='Ngày Lắp Ráp',
        default=fields.Datetime.now,
        required=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Thành Phẩm',
        required=True,
        index=True,
    )
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Template Thành Phẩm',
        related='product_id.product_tmpl_id',
        store=True,
    )
    lot_id = fields.Many2one(
        'stock.lot',
        string='Mã Serial/Lot Thành Phẩm',
        index=True,
        help='Serial/Lot của thành phẩm được tạo ra.',
    )
    packing_request_id = fields.Many2one(
        'packing.request',
        string='Phiếu Đóng Gói',
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Công Ty',
        default=lambda self: self.env.company,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Nháp'),
            ('done', 'Hoàn thành'),
            ('cancel', 'Đã hủy'),
        ],
        string='Trạng Thái',
        default='draft',
        tracking=True,
    )
    line_ids = fields.One2many(
        't4.assembly.record.line',
        'record_id',
        string='Chi Tiết Linh Kiện',
    )
    total_standard_price = fields.Float(
        string='Tổng Giá Vốn',
        compute='_compute_totals',
        store=True,
    )
    total_list_price = fields.Float(
        string='Tổng Giá Kho',
        compute='_compute_totals',
        store=True,
    )
    note = fields.Text(string='Ghi Chú')

    @api.depends('line_ids.total_standard_price', 'line_ids.total_list_price')
    def _compute_totals(self):
        for record in self:
            record.total_standard_price = sum(record.line_ids.mapped('total_standard_price'))
            record.total_list_price = sum(record.line_ids.mapped('total_list_price'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('t4.assembly.record') or _('New')
        return super().create(vals_list)

    def action_done(self):
        for record in self:
            record.state = 'done'

    def action_cancel(self):
        for record in self:
            record.state = 'cancel'
