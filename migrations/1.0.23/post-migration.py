# -*- coding: utf-8 -*-
"""Backfill dòng "Linh Kiện Trả" cũ bị rỗng Mã Quản Lý / Brd / Mfr S/N.

Trước v1.0.23, `_t4_auto_return_dropped_components` tạo dòng returned CHỈ set
`lot_id` (không set `lot_name`/`brand_part_id`/`manufacturer_part_id`). Cột
"Mã Quản Lý"/"Brd. S/N"/"Mfr. S/N" bind các char passenger này → rỗng.

Dùng **SQL trực tiếp** (KHÔNG qua ORM) để backfill: tránh trigger các
`@api.constrains` của `t4.product.creation.line` / `stock.move.line` trên DỮ
LIỆU CŨ chưa hợp lệ (vd dòng serial thiếu S/N) — migration backfill không được
hard-fail vì legacy data. Fill-when-empty (chỉ điền field còn rỗng).
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        UPDATE t4_product_creation_line cl
        SET lot_name = CASE WHEN COALESCE(cl.lot_name, '') = ''
                            THEN sl.name ELSE cl.lot_name END,
            brand_part_id = CASE WHEN COALESCE(cl.brand_part_id, '') = ''
                                 THEN sl.brand_part_id ELSE cl.brand_part_id END,
            manufacturer_part_id = CASE WHEN COALESCE(cl.manufacturer_part_id, '') = ''
                                        THEN sl.manufacturer_part_id
                                        ELSE cl.manufacturer_part_id END
        FROM stock_lot sl
        WHERE cl.lot_id = sl.id
          AND cl.state = 'returned'
          AND (COALESCE(cl.lot_name, '') = ''
               OR COALESCE(cl.brand_part_id, '') = ''
               OR COALESCE(cl.manufacturer_part_id, '') = '')
    """)
    if cr.rowcount:
        _logger.warning(
            "t4_product_package 1.0.23: backfill %s dòng Linh Kiện Trả "
            "(lot_name/Brd/Mfr từ lot, SQL).", cr.rowcount,
        )
