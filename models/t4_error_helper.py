# -*- coding: utf-8 -*-
"""T4 Error Helper — raise duplicate errors with "Open record" action button.

Dùng RedirectWarning (Odoo native) thay cho ValidationError ở những chỗ phát
hiện trùng record để dialog mặc định của Odoo tự thêm nút action mở record
bị trùng. KHÔNG cần custom UI — Odoo web client xử lý sẵn.

Cách dùng:
    self.env['t4.error.helper']._raise_duplicate(
        message=_('Mã Tham Chiếu "%s" đã được sử dụng...', code),
        model='product.template',
        res_id=duplicate.id,
        button_label=_('Mở sản phẩm bị trùng'),
        view_xml_id='t4_sti.view_t4_product_template_form',
    )

`view_xml_id` cố định form view nào sẽ được mở. Không truyền → Odoo tự pick
form default theo priority (implicit, dễ vỡ khi module khác bump priority).

Đặt ở t4_product_package vì t4_sti depend t4_product_package — cả 2 module
đều access được. Module-level function thay vì AbstractModel cũng OK nhưng
AbstractModel idiomatic hơn với Odoo (truy cập qua self.env).
"""
import logging

from odoo import _, api, models
from odoo.exceptions import RedirectWarning

_logger = logging.getLogger(__name__)


class T4ErrorHelper(models.AbstractModel):
    _name = 't4.error.helper'
    _description = 'T4 Error Helper — duplicate redirect raising'

    @api.model
    def _raise_duplicate(self, message, model, res_id, button_label=None, view_xml_id=None):
        """Raise RedirectWarning với button mở record bị trùng.

        Dialog Odoo render: title "Lỗi xác nhận" + body=message + 2 nút:
        [button_label] [Đóng]. Click button_label → mở form record bị trùng.

        :param str message: nội dung lỗi (đã dịch qua _())
        :param str model: tên model của record bị trùng (vd 'product.template')
        :param int res_id: id của record bị trùng
        :param str button_label: nhãn nút action (default 'Mở bản ghi bị trùng')
        :param str view_xml_id: xml_id form view cần mở (vd
            't4_sti.view_t4_product_template_form'). Không truyền → Odoo tự
            resolve form default theo priority.
        :raises RedirectWarning: luôn raise — không return
        """
        view_id = False
        if view_xml_id:
            view = self.env.ref(view_xml_id, raise_if_not_found=False)
            if view:
                view_id = view.id
            else:
                # View bị xoá / module chưa cài: log warning rồi fallback form
                # default thay vì crash trong context đang raise lỗi khác.
                _logger.warning(
                    'T4ErrorHelper: view_xml_id %r không tồn tại — fallback form default',
                    view_xml_id,
                )
        action = {
            'type': 'ir.actions.act_window',
            'res_model': model,
            'res_id': res_id,
            'views': [(view_id, 'form')],
            'target': 'current',
        }
        raise RedirectWarning(
            message,
            action,
            button_label or _('Mở bản ghi bị trùng'),
        )
