from odoo import api, fields, models

class PackingRequestLine(models.Model):
    _name = 'packing.request.line'
    _description = 'Chi Tiết Yêu Cầu Đóng Gói'

    request_id = fields.Many2one('packing.request', string='Yêu Cầu', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Sản Phẩm', required=True)
    product_uom_qty = fields.Float(string='Số Lượng Cần Đóng Gói', default=1.0)
    qty_packed = fields.Float(string='Đã Đóng Gói', default=0.0)
    product_uom = fields.Many2one('uom.uom', string='Đơn Vị', related='product_id.uom_id')
