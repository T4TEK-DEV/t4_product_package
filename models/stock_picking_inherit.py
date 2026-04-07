from odoo import fields, models, _
from odoo.exceptions import UserError

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    is_locked_by_packing = fields.Boolean(string='Đóng gói khóa phiếu', default=False, copy=False)
    packing_request_ids = fields.One2many('packing.request', 'picking_id', string='Phiếu Đóng Gói')

    def action_create_packing_request(self):
        self.ensure_one()
        if self.state not in ['confirmed', 'assigned']:
            raise UserError(_("Chỉ có thể mang đi đóng gói khi kiện hàng ở trạng thái Chờ hoặc Sẵn sàng!"))
        
        lines = []
        for move in self.move_ids_without_package:
            lines.append((0, 0, {
                'product_id': move.product_id.id,
                'product_uom_qty': move.product_uom_qty
            }))
            
        request = self.env['packing.request'].create({
            'picking_id': self.id,
            'request_line_ids': lines
        })
        
        return {
            'name': _('Yêu Cầu Đóng Gói'),
            'type': 'ir.actions.act_window',
            'res_model': 'packing.request',
            'res_id': request.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _update_lines_from_packing(self, packing_request):
        # Logic cập nhật thành phẩm / kiện hàng vào chứng từ
        pass
