from odoo import api, fields, models, _
from odoo.exceptions import UserError

class PackingSlipWizardLine(models.TransientModel):
    _name = 'packing.slip.wizard.line'
    _description = 'Chi tiết mã vạch đã quét'

    wizard_id = fields.Many2one('packing.slip.wizard')
    product_id = fields.Many2one('product.product', string='Sản phẩm')
    lot_id = fields.Many2one('stock.lot', string='Mã/Serial')
    qty = fields.Float(string='Số lượng', default=1.0)


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
        # Giả lập chưa tìm thấy:
        # raise UserError(f"Không tìm thấy mã vạch {self.barcode_input}")
        
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
            raise UserError(_("Vui lòng quét ít nhất 1 linh kiện để đóng gói!"))
        
        # Logic tạo ra mã Thành Phẩm / Kiện hàng mới (Sử dụng STIs Product Creation hoặc độc lập)
        pass
