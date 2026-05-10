# -*- coding: utf-8 -*-
"""Pre-migration v1.0.4: đổi tên cột line_type → state trên t4_product_creation_line.

`line_type` là tên cũ (v1.0.3), không rõ nghĩa. Đổi sang `state` để nhất
quán với convention Odoo (Selection phân loại trạng thái dùng 'state').

Phải chạy TRƯỚC khi ORM load model mới (tên field Python đã là `state`)
để Odoo không tạo cột `state` mới trong khi `line_type` vẫn còn dữ liệu.

Robust với 4 trạng thái DB có thể gặp khi upgrade:
  1. Chỉ có line_type → ALTER RENAME (case happy path)
  2. Chỉ có state → đã migrate trước đó, skip
  3. Có cả 2 → upgrade trước đó tạo state rỗng/NULL, copy data và drop line_type
  4. Không có cột nào → bảng mới tạo, để Odoo tự xử lý
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 't4_product_creation_line'
          AND column_name IN ('line_type', 'state')
    """)
    columns = {row[0] for row in cr.fetchall()}
    has_line_type = 'line_type' in columns
    has_state = 'state' in columns

    if has_line_type and not has_state:
        cr.execute(
            'ALTER TABLE t4_product_creation_line RENAME COLUMN line_type TO state'
        )
        _logger.info(
            't4_product_package 1.0.4: renamed line_type → state on t4_product_creation_line'
        )
    elif has_line_type and has_state:
        # Trường hợp Odoo đã tạo state rỗng/NULL trong lần upgrade trước,
        # giờ phải copy data từ line_type sang state rồi drop line_type.
        cr.execute("""
            UPDATE t4_product_creation_line
            SET state = line_type
            WHERE state IS NULL OR state = ''
        """)
        rowcount = cr.rowcount
        cr.execute('ALTER TABLE t4_product_creation_line DROP COLUMN line_type')
        _logger.info(
            't4_product_package 1.0.4: copied line_type → state on %d rows '
            'and dropped line_type',
            rowcount,
        )
    else:
        _logger.info(
            't4_product_package 1.0.4: column already migrated (state only) '
            'or table not yet created, skip'
        )
