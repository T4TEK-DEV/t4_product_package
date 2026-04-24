# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class PackingSlipWizard(models.TransientModel):
    _name = 'packing.slip.wizard'
    _description = 'Wizard Quét Mã Đóng Gói'

    request_id = fields.Many2one('packing.request', string='Phiếu Đóng Gói', required=True)
    fg_product_id = fields.Many2one(
        'product.product',
        string='Thành Phẩm',
        domain="[('tracking', '=', 'serial')]",
        help='Sản phẩm thành phẩm (serial) sẽ được tạo ra từ linh kiện đã quét. '
             'Mọi sản phẩm serial đều có thể đóng vai trò Thành Phẩm.',
    )
    barcode_input = fields.Char(string='Quét Mã Vạch')
    line_ids = fields.One2many('packing.slip.wizard.line', 'wizard_id', string='Linh Kiện Đã Quét')

    def action_scan_barcode(self):
        """Tìm product/lot từ barcode, thêm vào line_ids."""
        if not self.barcode_input:
            return
        barcode = self.barcode_input.strip()

        # Tìm theo lot/serial name trước
        lot = self.env['stock.lot'].search([
            ('name', '=', barcode),
        ], limit=1)
        if lot:
            self.line_ids = [(0, 0, {
                'product_id': lot.product_id.id,
                'lot_id': lot.id,
                'qty': 1.0,
                'standard_price': lot.product_id.standard_price,
                'list_price': lot.product_id.lst_price,
            })]
            self.barcode_input = False
            return self._reopen()

        # Tìm theo product barcode
        product = self.env['product.product'].search([
            ('barcode', '=', barcode),
        ], limit=1)
        if product:
            self.line_ids = [(0, 0, {
                'product_id': product.id,
                'qty': 1.0,
                'standard_price': product.standard_price,
                'list_price': product.lst_price,
            })]
            self.barcode_input = False
            return self._reopen()

        # Tìm theo default_code
        product = self.env['product.product'].search([
            ('default_code', '=', barcode),
        ], limit=1)
        if product:
            self.line_ids = [(0, 0, {
                'product_id': product.id,
                'qty': 1.0,
                'standard_price': product.standard_price,
                'list_price': product.lst_price,
            })]
            self.barcode_input = False
            return self._reopen()

        raise UserError(_('Không tìm thấy sản phẩm hoặc serial cho mã: %s') % barcode)

    def action_finish_pack(self):
        """Tạo assembly record từ linh kiện đã quét."""
        if not self.line_ids:
            raise UserError(_('Vui lòng quét ít nhất 1 linh kiện để đóng gói!'))
        if not self.fg_product_id:
            raise UserError(_('Vui lòng chọn sản phẩm thành phẩm!'))

        # Tạo lot/serial mới cho thành phẩm nếu tracking=serial
        lot = False
        if self.fg_product_id.tracking == 'serial':
            lot = self.env['stock.lot'].create({
                'product_id': self.fg_product_id.id,
                'company_id': self.request_id.company_id.id,
            })

        # Tạo assembly record
        record_lines = []
        for line in self.line_ids:
            record_lines.append((0, 0, {
                'product_id': line.product_id.id,
                'lot_id': line.lot_id.id if line.lot_id else False,
                'quantity': line.qty,
                'standard_price': line.standard_price,
                'list_price': line.list_price,
            }))

        assembly = self.env['t4.assembly.record'].create({
            'product_id': self.fg_product_id.id,
            'lot_id': lot.id if lot else False,
            'packing_request_id': self.request_id.id,
            'line_ids': record_lines,
            'state': 'done',
        })

        # Cập nhật qty_packed trên request lines
        for line in self.line_ids:
            req_line = self.request_id.request_line_ids.filtered(
                lambda rl: rl.product_id.id == line.product_id.id
            )
            if req_line:
                req_line[0].qty_packed += line.qty

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Lắp ráp thành công'),
                'message': _('Đã tạo thành phẩm %s') % assembly.name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'packing.slip.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

