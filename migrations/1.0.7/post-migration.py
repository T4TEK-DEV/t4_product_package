# -*- coding: utf-8 -*-
"""Post-migration v1.0.7: backfill standard_price + list_price computed/related.

v1.0.7 chuyển `t4.product.creation.line.standard_price` (Float thường) →
computed stored, và `list_price` → related stored từ `product.lst_price`.
Logic snapshot ở `_onchange_lot_name` được bỏ.

Trên upgrade, related store=True KHÔNG tự backfill row cũ (Odoo chỉ tạo
cột mới, không SELECT lại data). Computed cũng cần explicit recompute
cho row cũ vì @api.depends() được analyze tại field definition.

Script này force write tường minh:
  - standard_price: lot_valuated → lot.standard_price; else product.standard_price
  - list_price: product.lst_price
Chỉ touch line đang có giá ≠ giá đáng có (idempotent — chạy lại = no-op).
"""
import logging
from odoo import SUPERUSER_ID
from odoo.api import Environment

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = Environment(cr, SUPERUSER_ID, {})
    Line = env['t4.product.creation.line']
    lines = Line.search([])
    if not lines:
        return

    fixed_std = 0
    fixed_list = 0
    for line in lines:
        if not line.product_id:
            continue
        product = line.product_id

        # standard_price (computed)
        if product.lot_valuated and line.lot_id and line.lot_id.standard_price:
            new_std = line.lot_id.standard_price
        else:
            new_std = product.standard_price or 0.0
        if line.standard_price != new_std:
            line.standard_price = new_std
            fixed_std += 1

        # list_price (related — không auto-fill cho row cũ, ghi tay)
        new_list = product.lst_price or 0.0
        if line.list_price != new_list:
            line.list_price = new_list
            fixed_list += 1

    _logger.info(
        't4_product_package 1.0.7: backfilled standard_price=%d, list_price=%d lines',
        fixed_std, fixed_list,
    )
