# -*- coding: utf-8 -*-
"""Phiếu Lắp Ráp / Định Danh Sản Phẩm — model thống nhất.

Port từ v18 `product.creation.wizard` (extra-addons_18/STI-backend/STIs).
1 model duy nhất phục vụ 2 nghiệp vụ phân biệt qua field `type`:

  type='assembly':
      Lắp ráp thành phẩm mới (FG) từ N linh kiện. Tạo lot/serial mới
      cho FG, ghi nhận snapshot giá linh kiện tại thời điểm lắp.

  type='identify':
      Định danh linh kiện thành phẩm — gắn lot/serial cho từng linh
      kiện đã có nhưng chưa được định danh trên 1 thành phẩm sẵn có.

Cả 2 type dùng chung view list/form (form ẩn/hiện section theo type).
"""
import logging
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class ProductCreation(models.Model):
    _name = 't4.product.creation'
    _description = 'Phiếu Lắp Ráp / Định Danh Sản Phẩm'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'
    _rec_name = 'name'

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    name = fields.Char(
        string='Mã Phiếu',
        default=lambda self: _('New'),
        copy=False,
        readonly=True,
        index=True,
    )
    type = fields.Selection(
        selection=[
            ('assembly', 'Lắp Ráp'),
            ('identify', 'Định Danh'),
        ],
        string='Loại Phiếu',
        required=True,
        default='assembly',
        tracking=True,
        copy=False,
        index=True,
        help='Chọn mục đích của phiếu: lắp ráp thành phẩm mới hoặc định danh lại linh kiện cho thành phẩm đã có sẵn.',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Nháp'),
            ('waiting', 'Chờ Nhập Giá'),
            ('done', 'Hoàn Thành'),
            ('cancel', 'Đã Huỷ'),
        ],
        string='Trạng Thái',
        default='draft',
        tracking=True,
        copy=False,
    )

    # ------------------------------------------------------------------
    # Header — Thành phẩm + lot output
    # ------------------------------------------------------------------
    product_id = fields.Many2one(
        'product.product',
        string='Thành Phẩm',
        required=True,
        tracking=True,
        domain="[('tracking', '=', 'serial')]",
        index=True,
    )
    product_name = fields.Char(
        string='Tên Thành Phẩm',
        related='product_id.name',
        readonly=True,
    )
    product_tmpl_id = fields.Many2one(
        related='product_id.product_tmpl_id',
        store=True,
        readonly=True,
    )
    lot_id = fields.Many2one(
        'stock.lot',
        string='Lot Thành Phẩm',
        copy=False,
        tracking=True,
        domain="[('product_id', '=', product_id)]",
        help='Lot/Serial gắn cho thành phẩm. Với type=assembly sẽ tự '
             'tạo khi xác nhận; với type=identify user chọn lot có sẵn.',
    )
    lot_name = fields.Char(
        string='Mã Quản Lý TP',
        copy=False,
        tracking=True,
        help='Tên lot/serial của thành phẩm. Nhập hoặc quét trực tiếp — '
             'hệ thống tự tìm lot có sẵn (type=identify) hoặc tạo lot mới '
             'khi xác nhận (type=assembly).',
    )
    brand_part_id = fields.Char(
        string='Brd. S/N',
        related='lot_id.brand_part_id',
        readonly=True,
        store=False,
        help='S/N do Nhãn hiệu cấp cho lot thành phẩm.',
    )
    manufacturer_part_id = fields.Char(
        string='Mfr. S/N',
        related='lot_id.manufacturer_part_id',
        readonly=True,
        store=False,
        help='S/N do Nhà Sản Xuất cấp cho lot thành phẩm.',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Công Ty',
        default=lambda self: self.env.company,
        required=True,
    )
    has_lines = fields.Boolean(
        string='Có Linh Kiện?',
        compute='_compute_has_lines',
    )

    @api.depends('line_ids')
    def _compute_has_lines(self):
        for rec in self:
            rec.has_lines = bool(rec.line_ids)

    # ------------------------------------------------------------------
    # Cost confirmation (chỉ áp dụng cho type='identify')
    # Luồng mới: Operator nhập thông tin → "Hoàn Thành" (state=waiting) →
    # Thu Mua / Quản Lý nhập giá → "Xác Nhận Giá" (tạo lots/quants/SVL →
    # state=done).
    # Các field t4_cost_confirm_* giữ lại cho audit trail.
    # ------------------------------------------------------------------
    t4_cost_confirmed = fields.Boolean(
        string='Đã Xác Nhận Giá Mua',
        copy=False,
        tracking=True,
        help='Đánh dấu đã xác nhận giá mua linh kiện. Bắt buộc cho '
             'phiếu Định Danh LK TP trước khi xác nhận chính thức.',
    )
    t4_cost_confirm_user_id = fields.Many2one(
        'res.users',
        string='Người Xác Nhận Giá',
        copy=False,
        readonly=True,
    )
    t4_cost_confirm_date = fields.Datetime(
        string='Ngày Xác Nhận Giá',
        copy=False,
        readonly=True,
    )

    # ------------------------------------------------------------------
    # Linkage
    # ------------------------------------------------------------------
    packing_request_id = fields.Many2one(
        'packing.request',
        string='Phiếu Yêu Cầu Lắp Ráp',
        ondelete='set null',
        index=True,
        help='Liên kết tới phiếu yêu cầu lắp ráp (nếu có) để tự động '
             'cập nhật qty_packed khi xác nhận.',
    )

    # ------------------------------------------------------------------
    # Lines (split theo state qua domain trong One2many)
    # ------------------------------------------------------------------
    line_ids = fields.One2many(
        't4.product.creation.line',
        'creation_id',
        string='Linh Kiện Sử Dụng',
        domain=[('state', '=', 'used')],
        context={'default_state': 'used'},
    )
    line_returned_ids = fields.One2many(
        't4.product.creation.line',
        'creation_id',
        string='Linh Kiện Trả',
        domain=[('state', '=', 'returned')],
        context={'default_state': 'returned'},
        help='Chỉ dùng khi type=assembly để ghi nhận linh kiện trả lại '
             '(thay thế / hư hỏng).',
    )

    # ------------------------------------------------------------------
    # Notes & verification
    # ------------------------------------------------------------------
    note = fields.Text(string='Ghi Chú')
    # Pattern: lưu qua `ir.attachment` thay vì Binary auto-attachment
    # (giống `print_attachment_id` ở stock.picking trong t4_sti). Lợi ích:
    #   - Download URL gọn `/web/content/<id>?download=true`
    #   - Attachment xuất hiện ở chatter, có ACL riêng, dễ truy vết
    #   - Cleanup tự động khi xoá record (qua res_model/res_id)
    image_tracking_attachment_id = fields.Many2one(
        'ir.attachment',
        string='Hình Ảnh Xác Minh - Attachment',
        copy=False,
        ondelete='set null',
    )
    image_tracking = fields.Binary(
        string='Hình Ảnh Xác Minh',
        compute='_compute_image_tracking',
        inverse='_inverse_image_tracking',
        help='Hình chụp xác minh phiếu đã hoàn thành (chữ ký, vật chứng).',
    )
    image_tracking_filename = fields.Char(
        string='Tên File',
        compute='_compute_image_tracking',
        inverse='_inverse_image_tracking',
    )
    is_have_printed = fields.Boolean(
        string='Đã In',
        copy=False,
        help='Đánh dấu phiếu đã được in (set khi action_print được gọi).',
    )

    # ------------------------------------------------------------------
    # Computed totals & currency
    # ------------------------------------------------------------------
    cost_currency_id = fields.Many2one(
        'res.currency',
        string='Tiền Tệ',
        compute='_compute_cost_currency',
        store=False,
    )
    total_standard_price = fields.Monetary(
        string='Giá Mua (BOM)',
        currency_field='cost_currency_id',
        compute='_compute_totals',
        store=True,
        help='Tổng giá vốn của toàn bộ linh kiện trong BOM (snapshot).',
    )
    total_list_price = fields.Monetary(
        string='Tổng Giá Kho',
        currency_field='cost_currency_id',
        compute='_compute_totals',
        store=True,
    )
    purchase_price = fields.Monetary(
        string='Giá Mua',
        currency_field='cost_currency_id',
        compute='_compute_purchase_price',
        store=False,
        help='Giá vốn (standard_price) của thành phẩm tại thời điểm hiển thị.',
    )

    @api.depends('company_id')
    def _compute_cost_currency(self):
        for rec in self:
            rec.cost_currency_id = rec.company_id.currency_id

    @api.depends('line_ids.total_standard_price', 'line_ids.total_list_price')
    def _compute_totals(self):
        for rec in self:
            rec.total_standard_price = sum(
                rec.line_ids.mapped('total_standard_price')
            )
            rec.total_list_price = sum(
                rec.line_ids.mapped('total_list_price')
            )

    @api.depends('product_id.standard_price')
    def _compute_purchase_price(self):
        for rec in self:
            rec.purchase_price = rec.product_id.standard_price or 0.0

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains('lot_id', 'lot_name', 'type')
    def _check_lot_location(self):
        for rec in self:
            if not rec.type or rec.state in ('done', 'cancel'):
                continue
            if rec.type == 'identify':
                if rec.lot_name and not rec.lot_id:
                    raise ValidationError(_(
                        'Không tìm thấy sản phẩm với Mã Quản Lý TP "%s" trong kho.'
                    ) % rec.lot_name)
                if rec.lot_id:
                    restricted_quant = self.env['stock.quant'].search([
                        ('lot_id', '=', rec.lot_id.id),
                        ('location_id.is_usage_restricted', '=', True),
                        ('quantity', '>', 0),
                    ], limit=1)
                    if restricted_quant:
                        raise ValidationError(_(
                            'Sản phẩm "%s" đang nằm ở vị trí bị hạn chế sử dụng (%s).'
                        ) % (rec.lot_id.name, restricted_quant.location_id.display_name))
            elif rec.type == 'assembly' and rec.lot_id:
                quant = self.env['stock.quant'].search([
                    ('lot_id', '=', rec.lot_id.id),
                    ('location_id.name', '=', 'Lắp ráp'),
                    ('location_id.usage', '=', 'internal'),
                    ('quantity', '>', 0),
                ], limit=1)
                if not quant:
                    raise ValidationError(_(
                        'Sản phẩm "%s" không nằm ở kho Lắp Ráp. '
                        'Chỉ được lắp ráp thành phẩm đang có mặt tại kho Lắp Ráp.'
                    ) % rec.lot_id.name)

    # ------------------------------------------------------------------
    # Onchange — auto-resolve lot_name → lot_id + product_id khi user
    # nhập/quét tên lot
    # ------------------------------------------------------------------
    @api.onchange('lot_name')
    def _onchange_lot_name(self):
        """Khi user gõ/quét lot_name, tự tìm lot và bind toàn bộ header.

        Tìm theo `name` toàn cục (lot.name unique do t4_sti enforce):
          - Có lot khớp:
              * set lot_id (Brd/Mfr S/N tự load qua related field)
              * set product_id từ lot.product_id để user khỏi chọn lại
                thành phẩm — RFID là source-of-truth.
              * Nếu type='identify': kiểm tra thêm vị trí — cảnh báo nếu
                lot đang nằm ở location có is_usage_restricted=True.
          - Không khớp → giữ lot_name; lot_id sẽ được tạo (assembly) hoặc
            báo lỗi (identify) tại action_confirm.
        """
        if not self.lot_name:
            return
        lot = self.env['stock.lot'].search([
            ('name', '=', self.lot_name.strip()),
        ], limit=1)
        if not lot:
            if self.type in ('identify', 'assembly'):
                self.lot_id = False
                self.product_id = False
                return {
                    'warning': {
                        'title': _('Cảnh báo'),
                        'message': _('Không tìm thấy sản phẩm với Mã Quản Lý TP "%s" trong kho.') % self.lot_name,
                    }
                }
            return
        self.lot_id = lot
        if lot.product_id:
            self.product_id = lot.product_id
        if self.type == 'identify':
            restricted_quant = self.env['stock.quant'].search([
                ('lot_id', '=', lot.id),
                ('location_id.is_usage_restricted', '=', True),
                ('quantity', '>', 0),
            ], limit=1)
            if restricted_quant:
                return {
                    'warning': {
                        'title': _('Vị trí bị hạn chế'),
                        'message': _(
                            'Sản phẩm "%s" đang nằm ở vị trí bị hạn chế sử dụng (%s).'
                        ) % (lot.name, restricted_quant.location_id.display_name),
                    }
                }
        # Note: Validation kho Lắp Ráp cho type='assembly' đã được xử lý
        # ở @api.constrains _check_lot_location khi save — không duplicate
        # ở onchange để tránh popup hiện 2 lần.

    @api.onchange('lot_id')
    def _onchange_lot_id(self):
        """Sync ngược lot_id → lot_name khi user pick lot từ dropdown ẩn."""
        if self.lot_id and self.lot_id.name != self.lot_name:
            self.lot_name = self.lot_id.name

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                seq = self.env['ir.sequence'].next_by_code(
                    't4.product.creation'
                ) or _('New')
                vals['name'] = seq
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Workflow actions
    # ------------------------------------------------------------------
    def action_complete(self):
        """Hoàn thành nhập liệu — chuyển phiếu Định Danh sang Chờ Nhập Giá.

        Người vận hành hoàn tất nhập thông tin linh kiện (mã serial,
        Brd/Mfr S/N, số lượng). Phiếu bị khoá nhập liệu, chuyển sang
        state='waiting' để Thu Mua / Quản Lý nhập đơn giá rồi xác nhận.

        Không validate standard_price — phần đó do Thu Mua làm ở
        action_confirm_cost.
        """
        self.ensure_one()
        if self.type != 'identify':
            raise UserError(_('Chỉ phiếu Định Danh LK TP mới dùng nút này.'))
        if self.state != 'draft':
            raise UserError(_('Chỉ phiếu ở trạng thái Nháp mới có thể hoàn thành.'))
        if not self.line_ids:
            raise UserError(_(
                'Phiếu phải có ít nhất 1 dòng linh kiện trước khi hoàn thành.'
            ))
        if not self.lot_name and not self.lot_id:
            raise UserError(_('Vui lòng nhập Mã Quản Lý TP trước khi hoàn thành.'))

        no_product = self.line_ids.filtered(lambda l: not l.product_id)
        if no_product:
            raise UserError(_('Có dòng Linh Kiện Sử Dụng chưa chọn sản phẩm.'))

        zero_qty = self.line_ids.filtered(
            lambda l: not l.quantity or l.quantity <= 0
        )
        if zero_qty:
            names = ', '.join(zero_qty.mapped('product_id.display_name')[:5])
            raise UserError(_(
                'Vui lòng nhập Số Lượng (> 0) cho tất cả linh kiện. '
                'Dòng còn thiếu: %(names)s',
                names=names,
            ))

        no_lot = self.line_ids.filtered(
            lambda l: l.product_id.tracking == 'serial' and not l.lot_name
        )
        if no_lot:
            names = ', '.join(no_lot.mapped('product_id.display_name')[:5])
            raise UserError(_(
                'Linh kiện tracking serial phải có Mã Quản Lý. '
                'Dòng còn thiếu: %(names)s',
                names=names,
            ))

        # Kiểm tra brand_part_id / manufacturer_part_id không trùng hệ thống
        # và không trùng nhau trong cùng phiếu — phải chạy ở đây thay vì để
        # DB ném lỗi tại action_confirm_cost khi đã sang trạng thái waiting.
        Lot = self.env['stock.lot'].sudo()
        brd_seen, mfr_seen = {}, {}
        for line in self.line_ids:
            if not line.lot_name:
                continue
            pid = line.product_id.id

            if line.brand_part_id:
                key = (pid, line.brand_part_id)
                if key in brd_seen:
                    raise UserError(_(
                        'S/N Nhãn Hiệu "%(sn)s" của sản phẩm "%(prod)s" '
                        'xuất hiện nhiều hơn 1 lần trong cùng phiếu.',
                        sn=line.brand_part_id,
                        prod=line.product_id.display_name,
                    ))
                brd_seen[key] = True
                dup = Lot.search(
                    [('product_id', '=', pid), ('brand_part_id', '=', line.brand_part_id)],
                    limit=1,
                )
                if dup:
                    raise UserError(_(
                        'S/N Nhãn Hiệu "%(sn)s" của linh kiện "%(prod)s" '
                        'đã tồn tại trong hệ thống (Lot: %(lot)s). '
                        'Không thể định danh trùng.',
                        sn=line.brand_part_id,
                        prod=line.product_id.display_name,
                        lot=dup.name,
                    ))

            if line.manufacturer_part_id:
                key = (pid, line.manufacturer_part_id)
                if key in mfr_seen:
                    raise UserError(_(
                        'S/N Nhà Sản Xuất "%(sn)s" của sản phẩm "%(prod)s" '
                        'xuất hiện nhiều hơn 1 lần trong cùng phiếu.',
                        sn=line.manufacturer_part_id,
                        prod=line.product_id.display_name,
                    ))
                mfr_seen[key] = True
                dup = Lot.search(
                    [('product_id', '=', pid), ('manufacturer_part_id', '=', line.manufacturer_part_id)],
                    limit=1,
                )
                if dup:
                    raise UserError(_(
                        'S/N Nhà Sản Xuất "%(sn)s" của linh kiện "%(prod)s" '
                        'đã tồn tại trong hệ thống (Lot: %(lot)s). '
                        'Không thể định danh trùng.',
                        sn=line.manufacturer_part_id,
                        prod=line.product_id.display_name,
                        lot=dup.name,
                    ))

        self.state = 'waiting'
        self.message_post(body=_(
            'Hoàn thành nhập liệu bởi %(user)s. '
            'Đang chờ Thu Mua / Quản Lý nhập đơn giá và xác nhận.',
            user=self.env.user.name,
        ))

    def action_confirm(self):
        """Xác nhận phiếu — chỉ dùng cho type='assembly'.

        Với type='identify': dùng action_complete() → action_confirm_cost().

        Sign-wizard intercept (mirror stock.picking.button_validate):
            - Đọc flag `is_required_print_assembly` từ context.
            - Nếu require print: enforce `is_have_printed` và mở wizard
              upload ảnh nếu chưa có attachment.
            - Wizard re-call method này với `t4_bypass_sign_wizard=True`.
        """
        ctx = self.env.context
        bypass_wizard = ctx.get('t4_bypass_sign_wizard')
        for rec in self:
            if rec.state == 'done':
                continue
            if rec.type == 'identify':
                raise UserError(_(
                    'Phiếu Định Danh LK TP: dùng nút "Hoàn Thành" rồi '
                    '"Xác Nhận Giá" thay vì Xác Nhận trực tiếp.'
                ))
            if not rec.line_ids and not rec.line_returned_ids:
                raise UserError(_(
                    'Phiếu phải có ít nhất 1 dòng linh kiện trước khi xác nhận.'
                ))

            if not bypass_wizard and ctx.get('is_required_print_assembly'):
                if not rec.is_have_printed:
                    raise UserError(_('Vui lòng in phiếu trước khi xác nhận.'))
                if not rec.image_tracking_attachment_id:
                    return {
                        'type': 'ir.actions.act_window',
                        'name': _('Upload Hình Ảnh Xác Minh'),
                        'res_model': 't4.product.creation.sign.wizard',
                        'view_mode': 'form',
                        'target': 'new',
                        'context': {'default_creation_id': rec.id},
                    }

            # FG đã phải tồn tại tại kho Lắp ráp với quant > 0 trước khi
            # lắp ráp — _check_lot_location enforce điều này. Không tạo
            # lot mới ở đây: nghiệp vụ "lắp ráp = lấy hàng có sẵn".
            if rec.lot_name and not rec.lot_id:
                lot = self.env['stock.lot'].search([
                    ('name', '=', rec.lot_name.strip()),
                    ('product_id', '=', rec.product_id.id),
                ], limit=1)
                if not lot:
                    raise UserError(_(
                        'Không tìm thấy Mã Quản Lý "%(name)s" cho thành phẩm '
                        '"%(product)s". Lắp ráp chỉ được thực hiện trên thành '
                        'phẩm đã tồn tại tại kho Lắp ráp.',
                        name=rec.lot_name,
                        product=rec.product_id.display_name,
                    ))
                rec.lot_id = lot
            if not rec.lot_id:
                raise UserError(_(
                    'Phiếu Lắp Ráp phải có Mã Quản Lý TP hợp lệ — thành phẩm '
                    'chưa được nhập kho Lắp ráp thì chưa lắp ráp được.'
                ))

            rec._t4_check_returned_consistency()

            if rec.packing_request_id:
                rec._sync_packing_request_qty_packed()

            rec.state = 'done'

    def _t4_check_returned_consistency(self):
        """Validate net qty (committed + used − returned) ≥ 0 per (product, lot).

        Chạy ngay trước khi confirm. Cho phép returned bằng tổng:
            committed_qty (đã có trong FG từ phiếu done trước)
          + used_in_this_phieu (đã thêm vào tab Sử Dụng cùng phiếu)

        Tránh per-line constraint vì khi user flip dòng từ used→returned
        ở draft (UX phổ biến), constraint sẽ fire sai timing — chỉ kiểm
        tra cuối ở confirm là đủ và ít noise hơn.
        """
        self.ensure_one()
        if self.type != 'assembly' or not self.lot_id:
            return
        committed = self.lot_id._t4_get_committed_components()
        # Gom theo (product_id, lot_id) cho mọi dòng của phiếu này
        per_key_used = {}
        per_key_returned = {}
        for ln in self.line_ids:  # state='used'
            if not ln.product_id or not ln.quantity:
                continue
            key = (ln.product_id.id, ln.lot_id.id or 0)
            per_key_used[key] = per_key_used.get(key, 0.0) + ln.quantity
        for ln in self.line_returned_ids:  # state='returned'
            if not ln.product_id or not ln.quantity:
                continue
            key = (ln.product_id.id, ln.lot_id.id or 0)
            per_key_returned[key] = per_key_returned.get(key, 0.0) + ln.quantity

        errors = []
        for key, ret_qty in per_key_returned.items():
            committed_qty = committed.get(key, 0.0)
            used_qty = per_key_used.get(key, 0.0)
            allowance = committed_qty + used_qty
            if ret_qty > allowance:
                product = self.env['product.product'].browse(key[0])
                lot = self.env['stock.lot'].browse(key[1]) if key[1] else None
                label = product.display_name
                if lot:
                    label = '%s [lot %s]' % (label, lot.name)
                errors.append(_(
                    'Trả %(req)g của "%(comp)s" cho FG "%(fg)s" — vượt '
                    'mức cho phép %(max)g (đã có trong FG: %(committed)g, '
                    'mới thêm trong phiếu này: %(new)g).',
                    req=ret_qty,
                    comp=label,
                    fg=self.lot_id.name,
                    max=allowance,
                    committed=committed_qty,
                    new=used_qty,
                ))
        if errors:
            raise UserError('\n'.join(errors))

    def action_confirm_cost(self):
        """Xác nhận giá và nhập kho — chỉ cho phiếu Định Danh ở Chờ Nhập Giá.

        Thu Mua / Quản Lý nhập đơn giá cho từng dòng linh kiện, sau đó
        xác nhận. Một bước duy nhất thực hiện toàn bộ:
          1. Validate giá > 0 cho mọi dòng.
          2. Resolve lot_name → lot_id cho header TP.
          3. Tạo stock.lot cho linh kiện (serial/lot tracked).
          4. Tạo stock.quant + _apply_inventory() → SVL + journal entries.
          5. Chuyển state = done.

        Quyền: group_purchase hoặc group_manager (khai báo trên button XML).
        """
        self.ensure_one()
        if self.type != 'identify':
            raise UserError(_('Chỉ phiếu Định Danh LK TP mới cần xác nhận giá.'))
        if self.state != 'waiting':
            raise UserError(_(
                'Phiếu phải ở trạng thái "Chờ Nhập Giá" trước khi xác nhận giá.'
            ))
        if not self.line_ids:
            raise UserError(_('Phiếu chưa có dòng Linh Kiện Sử Dụng để xác nhận giá.'))

        # Validate: standard_price > 0
        zero_price = self.line_ids.filtered(
            lambda l: not l.standard_price or l.standard_price <= 0
        )
        if zero_price:
            names = ', '.join(zero_price.mapped('product_id.display_name')[:5])
            raise UserError(_(
                'Vui lòng nhập đơn giá mua (> 0) cho tất cả linh kiện. '
                'Dòng còn thiếu: %(names)s',
                names=names,
            ))

        # Sign-wizard intercept
        ctx = self.env.context
        bypass_wizard = ctx.get('t4_bypass_sign_wizard')
        if not bypass_wizard and ctx.get('is_required_print_identify'):
            if not self.is_have_printed:
                raise UserError(_('Vui lòng in phiếu trước khi xác nhận.'))
            if not self.image_tracking_attachment_id:
                return {
                    'type': 'ir.actions.act_window',
                    'name': _('Upload Hình Ảnh Xác Minh'),
                    'res_model': 't4.product.creation.sign.wizard',
                    'view_mode': 'form',
                    'target': 'new',
                    'context': {'default_creation_id': self.id},
                }

        # Resolve lot_name → lot_id cho TP header (phải tồn tại sẵn)
        if self.lot_name and not self.lot_id:
            lot = self.env['stock.lot'].search([
                ('name', '=', self.lot_name.strip()),
                ('product_id', '=', self.product_id.id),
            ], limit=1)
            if lot:
                self.lot_id = lot
            else:
                raise UserError(_(
                    'Không tìm thấy Mã Quản Lý "%(name)s" cho thành phẩm '
                    '"%(product)s". Vui lòng kiểm tra lại.',
                    name=self.lot_name,
                    product=self.product_id.display_name,
                ))
        if not self.lot_id:
            raise UserError(_('Phiếu định danh phải có Mã Quản Lý TP trước khi xác nhận.'))

        # Lưu audit trail
        self.write({
            't4_cost_confirmed': True,
            't4_cost_confirm_user_id': self.env.user.id,
            't4_cost_confirm_date': fields.Datetime.now(),
        })

        # Tạo stock.lot + stock.quant + SVL
        self._t4_create_component_lots()

        if self.packing_request_id:
            self._sync_packing_request_qty_packed()

        self.state = 'done'
        self.message_post(body=_(
            'Đã xác nhận giá và nhập kho bởi %(user)s. Tổng giá: %(total)s.',
            user=self.env.user.name,
            total=self.total_standard_price,
        ))

    def _t4_create_component_lots(self):
        """Tạo stock.lot + stock.quant + svl cho linh kiện identify.

        Mirror pattern accounting của in_purchase (`_t4_apply_cost`):

        Pass 1 — Lot + standard_price:
            - Tạo stock.lot (Brd/Mfr soft guard).
            - Group standard_price theo cost giống `_t4_apply_cost`:
              + product `lot_valuated=True` & tracking != 'none' →
                set `lot.standard_price` (svl per-lot).
              + Ngược lại → set `product.standard_price`.
              Batch theo cost-bucket để giảm ORM writes + invalidate.

        Pass 2 — Quant + Inventory Adjustment:
            - Tạo stock.quant với `inventory_quantity = line.quantity`
              tại location của FG (lấy quant internal đầu tiên của
              header lot_id).
            - Gọi `_apply_inventory()` → Odoo tự tạo stock.move (từ
              location_inventory → fg_location), `_action_done()` →
              tạo stock_valuation_layer + journal entries (giống
              Inventory Adjustment).

        Sau cùng invalidate cache `fg_component_line_ids` của FG lot.
        """
        self.ensure_one()
        if self.type != 'identify':
            return

        Lot = self.env['stock.lot']
        Quant = self.env['stock.quant']
        Product = self.env['product.product']
        has_brand = 'brand_part_id' in Lot._fields
        has_mfr = 'manufacturer_part_id' in Lot._fields

        # Ưu tiên quant có quantity > 0 ở vị trí không bị restricted (Kho Tạm
        # có thể còn remnant qty=0 với ID thấp → [:1] sẽ pick sai nếu không lọc).
        fg_quant = self.lot_id.quant_ids.filtered(
            lambda q: q.location_id.usage == 'internal'
            and not q.location_id.is_usage_restricted
            and q.quantity > 0
        )[:1]
        if not fg_quant:
            # Fallback: bất kỳ internal quant nào (trường hợp location không
            # đánh is_usage_restricted nhưng vẫn là nội bộ hợp lệ)
            fg_quant = self.lot_id.quant_ids.filtered(
                lambda q: q.location_id.usage == 'internal' and q.quantity > 0
            )[:1]
        if not fg_quant:
            raise UserError(_(
                'Thành phẩm "%(prod)s" (lot %(lot)s) chưa có vị trí kho '
                'nội bộ — không thể nhập linh kiện vào kho.',
                prod=self.product_id.display_name,
                lot=self.lot_id.name,
            ))
        fg_location = fg_quant.location_id

        # ----------------------------------------------------------
        # Pass 1: tạo lot (chỉ cho tracked) + collect cost-buckets
        # cho batch write. Tracking='none' không tạo lot — chỉ tạo
        # quant không lot ở Pass 2.
        # ----------------------------------------------------------
        cost_to_lots = defaultdict(lambda: Lot)
        cost_to_products = defaultdict(lambda: Product)
        line_lot_pairs = []  # [(line, new_lot or empty recordset)]

        for line in self.line_ids:
            if not line.product_id:
                continue
            if not line.quantity or line.quantity <= 0:
                continue
            if line.lot_id:
                # Idempotent: line đã được xử lý (vd. retry sau lỗi)
                continue

            tracking = line.product_id.tracking
            new_lot = Lot  # empty default cho tracking='none'

            if tracking != 'none':
                # Tracked product (serial / lot) → cần lot_name + tạo
                # stock.lot record. Validation đã đảm bảo lot_name có
                # tại action_confirm_cost (cho serial) — tracking='lot'
                # tạm bỏ qua nếu lot_name rỗng (view chưa hỗ trợ).
                if not line.lot_name:
                    continue
                lot_vals = {
                    'name': line.lot_name.strip(),
                    'product_id': line.product_id.id,
                    'company_id': self.company_id.id,
                }
                if has_brand and line.brand_part_id:
                    lot_vals['brand_part_id'] = line.brand_part_id
                if has_mfr and line.manufacturer_part_id:
                    lot_vals['manufacturer_part_id'] = line.manufacturer_part_id

                new_lot = Lot.create(lot_vals)
                line.lot_id = new_lot

            line_lot_pairs.append((line, new_lot))

            # Cost bucket: lot_valuated CHỈ áp dụng cho product có
            # tracking != 'none' (Odoo enforce). Tracking='none' luôn
            # rớt xuống product.standard_price (mirror in_purchase
            # `_t4_apply_cost` fallback).
            cost = line.standard_price or 0.0
            if cost > 0:
                product = line.product_id
                if new_lot and product.lot_valuated and tracking != 'none':
                    cost_to_lots[cost] |= new_lot
                else:
                    cost_to_products[cost] |= product

        # Batch-write standard_price TRƯỚC khi tạo quant + apply
        # inventory: svl đọc lot/product.standard_price khi move
        # _action_done → giá phải có sẵn.
        for cost, lots in cost_to_lots.items():
            lots.standard_price = cost
        for cost, products in cost_to_products.items():
            products.standard_price = cost

        # ----------------------------------------------------------
        # Pass 2: tạo quant với inventory_quantity → _apply_inventory.
        # Tracking='none' tạo quant không lot_id (Odoo cho phép); svl
        # sẽ dùng product.standard_price đã set ở Pass 1.
        # ----------------------------------------------------------
        quants_to_apply = Quant
        for line, new_lot in line_lot_pairs:
            quant_vals = {
                'product_id': line.product_id.id,
                'location_id': fg_location.id,
                'inventory_quantity': line.quantity,
                'inventory_quantity_set': True,
            }
            if new_lot:
                quant_vals['lot_id'] = new_lot.id
            new_quant = Quant.with_context(inventory_mode=True).create(quant_vals)
            quants_to_apply |= new_quant

        if quants_to_apply:
            # _apply_inventory: tạo stock.move (location_inventory →
            # fg_location) + _action_done → svl + journal entries.
            # Inject `t4_creation_id` qua context → stock.quant._get_inventory_move_values
            # đọc và set lên stock.move → stock.move.line related → navigate
            # từ "Lịch Sử Định Danh" về phiếu này.
            quants_to_apply.with_context(t4_creation_id=self.id)._apply_inventory()

        # Invalidate FG lot's fg_component_line_ids để form refresh.
        self.lot_id.invalidate_recordset(['fg_component_line_ids'])

    def _sync_packing_request_qty_packed(self):
        """Cập nhật qty_packed trên packing.request.line theo line_ids."""
        self.ensure_one()
        for line in self.line_ids:
            req_line = self.packing_request_id.request_line_ids.filtered(
                lambda rl: rl.product_id.id == line.product_id.id,
            )
            if req_line:
                req_line[0].qty_packed += line.quantity

    def action_cancel(self):
        for rec in self:
            if rec.state in ('draft', 'waiting'):
                rec.state = 'cancel'

    def action_draft(self):
        """Đặt về Nháp — cho phép từ cancel hoặc waiting (identify).

        waiting → draft: mở khoá để operator chỉnh sửa lại linh kiện.
        cancel → draft: khởi động lại phiếu từ đầu.
        Không rollback stock.lot / stock.quant (path done không có cancel).
        """
        for rec in self:
            if rec.state not in ('cancel', 'waiting'):
                continue
            rec.write({
                'state': 'draft',
                't4_cost_confirmed': False,
                't4_cost_confirm_user_id': False,
                't4_cost_confirm_date': False,
            })

    def action_print(self):
        """In phiếu lắp ráp / định danh.

        Port v18: 2 report riêng cho 2 type. Set is_have_printed=True
        để tracking ai đã in.
        """
        self.ensure_one()
        if not self.line_ids and not self.line_returned_ids:
            raise UserError(_(
                'Chưa có dòng linh kiện nào để in.'
            ))
        self.is_have_printed = True
        report_xml_id = (
            't4_product_package.action_report_t4_product_creation_assembly'
            if self.type == 'assembly'
            else 't4_product_package.action_report_t4_product_creation_identify'
        )
        return self.env.ref(report_xml_id).report_action(self)

    @api.depends('image_tracking_attachment_id',
                 'image_tracking_attachment_id.datas',
                 'image_tracking_attachment_id.name')
    def _compute_image_tracking(self):
        for rec in self:
            att = rec.image_tracking_attachment_id
            rec.image_tracking = att.datas if att else False
            rec.image_tracking_filename = att.name if att else False

    def _inverse_image_tracking(self):
        """Tạo / cập nhật / xoá `ir.attachment` khi user upload qua widget=image.

        - Có data + chưa có attachment  → tạo mới (gắn res_model/res_id để
          attachment được cleanup tự động khi record bị xoá).
        - Có data + đã có attachment    → ghi đè datas; chỉ ghi đè name nếu
          user thực sự cung cấp filename mới (tránh trường hợp clear filename
          xong inverse fall back về 'image_tracking' và đè tên gốc).
        - Không có data + có attachment → xoá attachment, FK tự null qua
          ondelete='set null'.
        """
        Attachment = self.env['ir.attachment']
        for rec in self:
            data = rec.image_tracking
            name = rec.image_tracking_filename
            att = rec.image_tracking_attachment_id
            if data:
                if att:
                    vals = {'datas': data}
                    if name:
                        vals['name'] = name
                    att.write(vals)
                else:
                    new_att = Attachment.create({
                        'name': name or 'image_tracking',
                        'datas': data,
                        'res_model': 't4.product.creation',
                        'res_id': rec.id,
                        'type': 'binary',
                    })
                    rec.image_tracking_attachment_id = new_att
            elif att:
                att.unlink()

    def action_download_image_tracking(self):
        """Trả về URL tải về attachment hình ảnh xác minh.

        Dùng route chuẩn `/web/content/<id>?download=true` của Odoo (giống
        `action_download_verification_image` ở stock.picking). Target `self`
        để trình duyệt xử lý header `Content-Disposition: attachment` và lưu
        file vào Downloads thay vì điều hướng tab hiện tại sang trang trắng.
        """
        self.ensure_one()
        if not self.image_tracking_attachment_id:
            raise UserError(_("Phiếu chưa có hình ảnh xác minh."))
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/%s?download=true" % self.image_tracking_attachment_id.id,
            "target": "self",
        }

    @api.model
    def _cron_cleanup_empty_drafts(self):
        """Dọn dẹp các phiếu nháp rỗng do auto-save của Odoo tạo ra."""
        limit_date = fields.Datetime.subtract(fields.Datetime.now(), hours=24)
        domain = [
            ('state', '=', 'draft'),
            ('line_ids', '=', False),
            ('create_date', '<', limit_date)
        ]
        empty_drafts = self.search(domain)
        if empty_drafts:
            empty_drafts.unlink()

