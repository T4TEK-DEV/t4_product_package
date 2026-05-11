# -*- coding: utf-8 -*-
from odoo import models


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    def _get_inventory_move_values(self, qty, location_id, location_dest_id, package_id=False, package_dest_id=False):
        """Inject t4_creation_id từ context xuống stock.move vals.

        `t4.product.creation._t4_create_quants_and_apply_inventory` set
        context `t4_creation_id` trước khi call `_apply_inventory()` →
        Odoo tạo move qua method này → ta thêm FK link về phiếu identify.
        """
        res = super()._get_inventory_move_values(
            qty, location_id, location_dest_id, package_id, package_dest_id,
        )
        creation_id = self.env.context.get('t4_creation_id')
        if creation_id:
            res['t4_creation_id'] = creation_id
        return res
