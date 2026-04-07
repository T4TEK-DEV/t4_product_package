from odoo import api, fields, models, _
from odoo.exceptions import UserError

class PackingRequest(models.Model):
    _name = 'packing.request'
    _description = 'Phiếu Yêu Cầu Đóng Gói (Lắp Ráp Định Danh)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Mã Phiếu', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    picking_id = fields.Many2one('stock.picking', string='Phiếu Xuất Kho', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Đối Tác', related='picking_id.partner_id', store=True)
    
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('open', 'Đang thực hiện'),
        ('done', 'Hoàn thành'),
        ('cancel', 'Đã hủy'),
    ], string='Trạng Thái', default='draft', tracking=True)

    company_id = fields.Many2one('res.company', string='Công Ty', default=lambda self: self.env.company)
    request_line_ids = fields.One2many('packing.request.line', 'request_id', string='Chi Tiết Đóng Gói')
    
    packing_slip_count = fields.Integer(string='Số lượng kiện hàng', compute='_compute_packing_slip_count')

    def _compute_packing_slip_count(self):
        for rec in self:
            rec.packing_slip_count = 0 # TODO: Calculate from wizard or slips
            
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('packing.request') or _('New')
        return super().create(vals_list)

    def action_confirm(self):
        for rec in self:
            if not rec.request_line_ids:
                raise UserError(_("Vui lòng thêm sản phẩm cần đóng gói!"))
            if rec.picking_id:
                rec.picking_id.is_locked_by_packing = True
            rec.state = 'open'

    def action_done(self):
        self.ensure_one()
        self.state = 'done'
        if self.picking_id:
            self.picking_id.is_locked_by_packing = False
            self.picking_id._update_lines_from_packing(self)
        self._create_return_moves_for_excess_components()

    def _create_return_moves_for_excess_components(self):
        # TODO: Implement return logic
        pass

    def action_cancel(self):
        for rec in self:
            rec.state = 'cancel'
            if rec.picking_id:
                rec.picking_id.is_locked_by_packing = False

    def action_draft(self):
        for rec in self:
            rec.state = 'draft'
