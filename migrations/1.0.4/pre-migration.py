# -*- coding: utf-8 -*-
"""Pre-migration v1.0.4: đổi tên cột line_type → state trên t4_product_creation_line.

`line_type` là tên cũ (v1.0.3), không rõ nghĩa. Đổi sang `state` để nhất
quán với convention Odoo (Selection phân loại trạng thái dùng 'state').

Phải chạy TRƯỚC khi ORM load model mới (tên field Python đã là `state`)
để Odoo không tạo cột `state` mới trong khi `line_type` vẫn còn dữ liệu.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    # Kiểm tra cột cũ còn tồn tại không (idempotent)
    cr.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 't4_product_creation_line'
          AND column_name = 'line_type'
    """)
    if not cr.fetchone():
        _logger.info('t4_product_package 1.0.4: column line_type already renamed, skip')
        return
    cr.execute(
        'ALTER TABLE t4_product_creation_line RENAME COLUMN line_type TO state'
    )
    _logger.info('t4_product_package 1.0.4: renamed column line_type → state on t4_product_creation_line')
