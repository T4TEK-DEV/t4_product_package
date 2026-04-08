from odoo import fields, models, _
from odoo.exceptions import UserError


class PackingSlipWizard(models.TransientModel):
    _name = 'packing.slip.wizard'
    _description = 'Wizard Quét Mã Đóng Gói'

    request_id = fields.Many2one('packing.request', string='Phiếu Đóng Gói', required=True)
    barcode_input = fields.Char(string='Quét Mã Vạch')
    line_ids = fields.One2many('packing.slip.wizard.line', 'wizard_id', string='Linh Kiện Đã Quét')

    def action_scan_barcode(self):
        if not self.barcode_input:
            return

        # TODO: Xử lý tìm kiếm sản phẩm/lot dựa vào self.barcode_input

        self.barcode_input = False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'packing.slip.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_finish_pack(self):
        if not self.line_ids:
            raise UserError(_('Vui lòng quét ít nhất 1 linh kiện để đóng gói!'))

        # TODO: Logic tạo ra mã Thành Phẩm / Kiện hàng mới
        pass
