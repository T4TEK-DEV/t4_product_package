# -*- coding: utf-8 -*-
"""Wizard upload ảnh phiếu lắp ráp/định danh đã ký trước khi xác nhận.

Mirror `t4.sti.picking.sign.wizard` (t4_sti) — pattern thống nhất:
    1. User bấm "Xác Nhận" trên `t4.product.creation`.
    2. `action_confirm` kiểm tra config `t4.sti.config`:
        - type='assembly' + is_required_print_assembly → required
        - type='identify' + is_required_print_identify → required
    3. Nếu required: enforce `is_have_printed=True` và mở wizard này nếu
       chưa có `image_tracking_attachment_id`.
    4. Wizard tạo `ir.attachment`, gắn FK, re-call `action_confirm` với
       context `t4_bypass_sign_wizard=True` để bỏ qua intercept.
"""
from odoo import _, fields, models
from odoo.exceptions import UserError


class T4ProductCreationSignWizard(models.TransientModel):
    _name = 't4.product.creation.sign.wizard'
    _description = 'Wizard upload ảnh phiếu lắp ráp/định danh đã ký trước khi xác nhận'

    creation_id = fields.Many2one(
        't4.product.creation',
        string='Phiếu',
        required=True,
        ondelete='cascade',
    )
    creation_name = fields.Char(related='creation_id.name', readonly=True)
    attachment_data = fields.Binary(
        string='Ảnh Phiếu Đã Ký',
        required=True,
        help='Chụp ảnh phiếu đã in và ký tên, sau đó tải hình ảnh lên đây.',
    )
    attachment_name = fields.Char(string='Tên File')

    def action_upload_and_confirm(self):
        self.ensure_one()
        if not self.attachment_data:
            raise UserError(_('Vui lòng upload ảnh phiếu đã ký.'))
        attachment = self.env['ir.attachment'].create({
            'name': self.attachment_name or 'signed_%s.png' % (
                self.creation_id.name or 'creation'
            ),
            'datas': self.attachment_data,
            'res_model': 't4.product.creation',
            'res_id': self.creation_id.id,
            'type': 'binary',
        })
        self.creation_id.image_tracking_attachment_id = attachment.id
        return self.creation_id.with_context(
            t4_bypass_sign_wizard=True
        ).action_confirm()
