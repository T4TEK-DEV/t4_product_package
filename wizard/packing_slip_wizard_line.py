from odoo import fields, models


class PackingSlipWizardLine(models.TransientModel):
    _name = 'packing.slip.wizard.line'
    _description = 'Chi tiết mã vạch đã quét'

    wizard_id = fields.Many2one('packing.slip.wizard', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Sản phẩm')
    lot_id = fields.Many2one('stock.lot', string='Mã/Serial')
    qty = fields.Float(string='Số lượng', default=1.0)
