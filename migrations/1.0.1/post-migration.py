# -*- coding: utf-8 -*-
"""Migrate `image_tracking` từ Binary auto-attachment sang explicit Many2one.

Trước 1.0.1:
    fields.Binary(string='Hình Ảnh Xác Minh')
    → Odoo lưu data ở `ir_attachment` với `res_model='t4.product.creation'`,
      `res_field='image_tracking'`, `res_id=<rec_id>`. Field tự đọc qua res_field.

Từ 1.0.1:
    image_tracking_attachment_id = fields.Many2one('ir.attachment', ...)
    image_tracking = compute/inverse từ attachment.datas

Migration: với mỗi attachment cũ (`res_field='image_tracking'`):
  1. Restore tên file gốc: `att.name` của auto-attachment là synthesized
     (`t4.product.creation_<id>_image_tracking`), trong khi tên thật user
     upload nằm ở column cũ `t4_product_creation.image_tracking_filename`
     (vẫn còn trong DB vì Odoo không tự drop column khi field chuyển sang
     compute). Copy lại để nút "Tải Hình Về" trả ra đúng tên gốc.
  2. Set `t4_product_creation.image_tracking_attachment_id = att.id`
  3. Clear `att.res_field` để Odoo không còn auto-quản lý qua res_field magic
     (giữ res_model/res_id để cleanup khi xoá record vẫn hoạt động).
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # 1. Khôi phục tên file gốc trên attachment trước khi cắt res_field
    cr.execute("""
        UPDATE ir_attachment a
        SET name = pc.image_tracking_filename
        FROM t4_product_creation pc
        WHERE a.res_model = 't4.product.creation'
          AND a.res_field = 'image_tracking'
          AND a.res_id = pc.id
          AND pc.image_tracking_filename IS NOT NULL
          AND pc.image_tracking_filename <> ''
    """)
    renamed = cr.rowcount

    # 2. Link attachment cũ vào FK mới
    cr.execute("""
        UPDATE t4_product_creation pc
        SET image_tracking_attachment_id = a.id
        FROM ir_attachment a
        WHERE a.res_model = 't4.product.creation'
          AND a.res_field = 'image_tracking'
          AND a.res_id = pc.id
          AND pc.image_tracking_attachment_id IS NULL
    """)
    linked = cr.rowcount

    # 3. Bỏ res_field magic, giữ res_model/res_id cho cleanup khi xoá record
    cr.execute("""
        UPDATE ir_attachment
        SET res_field = NULL
        WHERE res_model = 't4.product.creation'
          AND res_field = 'image_tracking'
    """)
    cleared = cr.rowcount

    _logger.info(
        "t4_product_package 1.0.1: renamed %s attachments to original "
        "filename, linked %s into FK, cleared res_field on %s rows",
        renamed, linked, cleared,
    )
