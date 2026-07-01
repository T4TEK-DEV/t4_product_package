# -*- coding: utf-8 -*-
"""Backfill dòng "Linh Kiện Trả" cũ bị rỗng Mã Quản Lý / Brd / Mfr S/N.

Trước v1.0.23, `_t4_auto_return_dropped_components` tạo dòng returned CHỈ set
`lot_id` (không set `lot_name`/`brand_part_id`/`manufacturer_part_id`). Cột
"Mã Quản Lý"/"Brd. S/N"/"Mfr. S/N" bind các char passenger này (KHÔNG bind
lot_id) → hiển thị rỗng. Backfill từ `stock.lot` cho các dòng cũ.

Fill-when-empty: KHÔNG đè giá trị đã có (nhập tay). Chỉ dòng state='returned'
có lot_id nhưng thiếu ít nhất 1 trong 3 char.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Line = env['t4.product.creation.line']
    lines = Line.search([
        ('state', '=', 'returned'),
        ('lot_id', '!=', False),
    ])
    count = 0
    for ln in lines:
        lot = ln.lot_id
        patch = {}
        if not ln.lot_name and lot.name:
            patch['lot_name'] = lot.name
        if not ln.brand_part_id and lot.brand_part_id:
            patch['brand_part_id'] = lot.brand_part_id
        if not ln.manufacturer_part_id and lot.manufacturer_part_id:
            patch['manufacturer_part_id'] = lot.manufacturer_part_id
        if patch:
            ln.with_context(t4_skip_bm_snapshot=True).write(patch)
            count += 1
    if count:
        _logger.warning(
            "t4_product_package 1.0.23: backfill %s dòng Linh Kiện Trả "
            "(lot_name/Brd/Mfr từ lot).", count,
        )
