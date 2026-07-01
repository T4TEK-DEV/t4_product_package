# -*- coding: utf-8 -*-
"""Dọn dữ liệu TỰ THAM CHIẾU cũ: linh kiện trùng chính Thành Phẩm của phiếu.

Trước v1.0.22 chưa có guard `_check_component_not_self_fg` → tồn tại các dòng
`t4.product.creation.line` có cùng serial/lot (hoặc cùng Mã Quản Lý) với Thành
Phẩm của phiếu ("vừa làm cha vừa làm con"). Xoá các dòng này để:
  - dữ liệu nhất quán (một serial không thể chứa chính nó),
  - không vướng constraint mới ở các thao tác sau,
  - `fg_component_line_ids` / committed-components của FG net lại đúng.

An toàn: phiếu ASSEMBLY confirm KHÔNG tạo stock.move/SVL (chỉ ghi nhận cấu
thành) nên xoá dòng không đụng valuation. Phiếu IDENTIFY đã tạo lot/quant cho
LINH KIỆN THẬT — dòng self-ref không thể tồn tại ở identify (bị
`_check_identify_lot_name_unique` chặn từ trước) nên không có quant nào bị
ảnh hưởng. `line.unlink()` override tự recompute assembly_status của quant.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Line = env['t4.product.creation.line']
    bad = Line.browse()
    for ln in Line.search([]):
        creation = ln.creation_id
        fg_lot = creation.lot_id
        fg_name = (fg_lot.name if fg_lot else '') or (creation.lot_name or '').strip()
        ln_name = (ln.lot_id.name if ln.lot_id else '') or (ln.lot_name or '').strip()
        same_lot = bool(fg_lot and ln.lot_id and ln.lot_id == fg_lot)
        same_name = bool(fg_name and ln_name and fg_name == ln_name)
        if same_lot or same_name:
            bad |= ln
            _logger.warning(
                "t4_product_package 1.0.22: xoá dòng tự-tham-chiếu id=%s "
                "(phiếu %s, state=%s, mã=%s) trùng FG %s",
                ln.id, creation.name, ln.state, ln_name or fg_name, fg_name,
            )
    if bad:
        bad.unlink()
        _logger.warning(
            "t4_product_package 1.0.22: đã xoá %s dòng linh kiện tự-tham-chiếu.",
            len(bad),
        )
