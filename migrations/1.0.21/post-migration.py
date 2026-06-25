# -*- coding: utf-8 -*-
"""Gỡ cron "Dọn dẹp phiếu Lắp Ráp/Định Danh nháp rỗng".

Phiếu Định Danh tạo tự động (sinh từ phiếu điều chuyển đi định danh) bắt đầu
ở trạng thái Nháp RỖNG — kỹ thuật chưa quét — và là việc cần làm. Cron dọn
nháp rỗng > 24h sẽ XÓA mất các phiếu này. Gỡ cron để giữ task.

Record cron đã bỏ khỏi data/ir_cron_cleanup.xml; migration này xóa bản ghi
ir.cron còn tồn trên DB đã cài (idempotent).
"""

from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cron = env.ref(
        't4_product_package.ir_cron_t4_cleanup_empty_product_creation',
        raise_if_not_found=False,
    )
    if cron:
        cron.unlink()
