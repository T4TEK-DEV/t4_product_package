# -*- coding: utf-8 -*-
"""Nối nhóm quyền ẩn/hiện menu vào đúng menu và đúng Client Scope.

Không khai được bằng XML: menu là bản ghi `menu_sync.poc_menu_*` do Stuflow
đồng bộ (xmlid đó không tồn tại trên mọi môi trường — `ref` vào nó sẽ làm
CHẾT lúc cài ở nơi chưa có Stuflow), còn Client Scope thì không có xmlid nào.

🔴 CHỈ THÊM, KHÔNG XOÁ. Scope đang gắn trên menu được giữ nguyên: điều kiện
menu là OR, nên người đang giữ scope không mất gì, và lần Stuflow đồng bộ
menu kế tiếp cũng không đạp lên.

Tìm menu qua ACTION của chính module (xmlid mình sở hữu) chứ không qua id
menu — id menu lệch giữa các môi trường.
"""
import logging

from odoo import SUPERUSER_ID, api
from odoo.fields import Command

_logger = logging.getLogger(__name__)

ACTION = 't4_product_package.action_t4_product_creation_identify_new'
GROUP = 't4_product_package.group_identify_component'
SCOPE = 'STI - Định danh LK trong TP'


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})

    group = env.ref(GROUP, raise_if_not_found=False)
    action = env.ref(ACTION, raise_if_not_found=False)
    if not group or not action:
        _logger.warning('t4_product_package: chua co group/action, bo qua noi day.')
        return

    menus = env['ir.ui.menu'].sudo().search(
        [('action', '=', 'ir.actions.act_window,%s' % action.id)])
    da_noi = 0
    for menu in menus:
        if group not in menu.group_ids:
            menu.group_ids = [Command.link(group.id)]
            da_noi += 1
    if not menus:
        _logger.info('t4_product_package: khong co menu nao tro toi action nay.')

    # Client Scope trùng tên nhưng khác tầng thì bỏ qua — chỉ nhận đúng nhóm
    # nằm dưới privilege "Client Scope" của Stuflow.
    scope = env['res.groups'].sudo().search(
        [('name', '=', SCOPE), ('privilege_id.name', '=', 'Client Scope')],
        limit=1)
    if scope and group not in scope.implied_ids:
        scope.implied_ids = [Command.link(group.id)]
        _logger.info('t4_product_package: da gan quyen nen vao scope "%s".', SCOPE)
    elif not scope:
        _logger.info('t4_product_package: khong tim thay Client Scope "%s".', SCOPE)

    _logger.info('t4_product_package: da noi nhom quyen vao %s menu.', da_noi)
