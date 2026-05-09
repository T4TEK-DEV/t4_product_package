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

    # ------------------------------------------------------------------
    # Cost confirmation (chỉ áp dụng cho type='identify')
    # Mirror pattern in_purchase trong t4_sti.stock_picking: 2 bước
    # — Purchase/Manager xác nhận giá trước, sau đó action_confirm tạo
    # stock.lot + stock.quant cho linh kiện mới.
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
    # Lines (split theo line_type qua domain trong One2many)
    # ------------------------------------------------------------------
    line_ids = fields.One2many(
        't4.product.creation.line',
        'creation_id',
        string='Linh Kiện Sử Dụng',
        domain=[('line_type', '=', 'used')],
        context={'default_line_type': 'used'},
    )
    line_returned_ids = fields.One2many(
        't4.product.creation.line',
        'creation_id',
        string='Linh Kiện Trả',
        domain=[('line_type', '=', 'returned')],
        context={'default_line_type': 'returned'},
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
    @api.constrains('line_ids', 'type')
    def _check_identify_single_used_line(self):
        for rec in self:
            if rec.type == 'identify' and len(rec.line_ids) > 1:
                raise ValidationError(_(
                    'Phiếu Định Danh chỉ cho phép 1 dòng Linh Kiện Sử Dụng.'
                ))

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
          - Không khớp → giữ lot_name; lot_id sẽ được tạo (assembly) hoặc
            báo lỗi (identify) tại action_confirm.
        """
        if not self.lot_name:
            return
        lot = self.env['stock.lot'].search([
            ('name', '=', self.lot_name.strip()),
        ], limit=1)
        if not lot:
            return
        self.lot_id = lot
        if lot.product_id:
            self.product_id = lot.product_id

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
    def action_confirm(self):
        """Xác nhận phiếu — chuyển state=done.

        Với type='assembly': tự tạo lot mới cho FG nếu chưa có và FG
        là tracking='serial'. Đồng bộ qty_packed lên packing_request_id
        nếu liên kết.

        Sign-wizard intercept (mirror stock.picking.button_validate):
            - Đọc flag `is_required_print_assembly|identify` từ context
              (do `t4_sti.ir_http.session_info` inject vào user_context).
            - Nếu type tương ứng require print: enforce `is_have_printed`
              và mở wizard upload ảnh nếu chưa có attachment.
            - Wizard re-call method này với `t4_bypass_sign_wizard=True`.
        """
        ctx = self.env.context
        bypass_wizard = ctx.get('t4_bypass_sign_wizard')
        for rec in self:
            if rec.state == 'done':
                continue
            if not rec.line_ids:
                raise UserError(_(
                    'Phiếu phải có ít nhất 1 dòng linh kiện trước khi xác nhận.'
                ))

            # Sign-wizard intercept — chỉ chạy cho phiếu thật sự require print.
            if not bypass_wizard:
                requires_sign = (
                    (rec.type == 'assembly' and ctx.get('is_required_print_assembly'))
                    or (rec.type == 'identify' and ctx.get('is_required_print_identify'))
                )
                if requires_sign:
                    if not rec.is_have_printed:
                        raise UserError(_(
                            'Vui lòng in phiếu trước khi xác nhận.'
                        ))
                    if not rec.image_tracking_attachment_id:
                        return {
                            'type': 'ir.actions.act_window',
                            'name': _('Upload Hình Ảnh Xác Minh'),
                            'res_model': 't4.product.creation.sign.wizard',
                            'view_mode': 'form',
                            'target': 'new',
                            'context': {'default_creation_id': rec.id},
                        }

            # Resolve lot_name → lot_id (find existing or create for assembly).
            if rec.lot_name and not rec.lot_id:
                lot = self.env['stock.lot'].search([
                    ('name', '=', rec.lot_name.strip()),
                    ('product_id', '=', rec.product_id.id),
                ], limit=1)
                if lot:
                    rec.lot_id = lot
                elif rec.type == 'assembly' and rec.product_id.tracking == 'serial':
                    rec.lot_id = self.env['stock.lot'].create({
                        'name': rec.lot_name.strip(),
                        'product_id': rec.product_id.id,
                        'company_id': rec.company_id.id,
                    })
                else:
                    raise UserError(_(
                        'Không tìm thấy Mã Quản Lý "%(name)s" cho thành phẩm '
                        '"%(product)s". Vui lòng kiểm tra lại.',
                        name=rec.lot_name,
                        product=rec.product_id.display_name,
                    ))

            if rec.type == 'assembly' and not rec.lot_id and rec.product_id.tracking == 'serial':
                rec.lot_id = self.env['stock.lot'].create({
                    'product_id': rec.product_id.id,
                    'company_id': rec.company_id.id,
                })
                if not rec.lot_name:
                    rec.lot_name = rec.lot_id.name

            if rec.type == 'identify' and not rec.lot_id:
                raise UserError(_(
                    'Phiếu định danh phải có Mã Quản Lý TP trước khi '
                    'xác nhận.'
                ))

            # Identify-only gates: cost-confirm bắt buộc + tạo stock.lot
            # + stock.quant cho linh kiện mới định danh.
            if rec.type == 'identify':
                if not rec.t4_cost_confirmed:
                    raise UserError(_(
                        'Vui lòng xác nhận giá mua trước khi xác nhận phiếu '
                        '(yêu cầu quyền Thu Mua / Quản Lý).'
                    ))
                # Re-validate: nếu user thêm dòng mới sau cost-confirm,
                # standard_price có thể = 0 → buộc đặt về Nháp & xác nhận
                # giá lại.
                zero_price = rec.line_ids.filtered(
                    lambda l: not l.standard_price or l.standard_price <= 0
                )
                if zero_price:
                    names = ', '.join(
                        zero_price.mapped('product_id.display_name')[:5]
                    )
                    raise UserError(_(
                        'Có dòng linh kiện chưa có giá mua: %(names)s. '
                        'Vui lòng đặt phiếu về Nháp và xác nhận lại giá.',
                        names=names,
                    ))
                rec._t4_create_component_lots()

            if rec.packing_request_id:
                rec._sync_packing_request_qty_packed()

            rec.state = 'done'

    def action_confirm_cost(self):
        """Xác nhận giá mua cho phiếu Định Danh LK TP.

        Mirror pattern in_purchase (`stock.picking._t4_check_demand_not_zero`
        + `_t4_confirm_cost`):
            - Chỉ áp dụng cho phiếu type='identify' state='draft'.
            - Validate mọi dòng:
              + product_id đã set
              + quantity > 0
              + lot_name có khi tracking == 'serial'
              + standard_price > 0
              + brand/manufacturer S/N nếu config require (đọc context,
                fallback singleton t4.sti.config).
            - Set 3 field cost_confirm + post message vào chatter.
            - Lock UI: x2many `line_ids` readonly khi t4_cost_confirmed
              (xem view).

        Quyền hiển thị/gọi: thực thi qua group purchase/accounting/manager
        (declared trên button XML).
        """
        self.ensure_one()
        if self.type != 'identify':
            raise UserError(_(
                'Chỉ phiếu Định Danh LK TP mới cần xác nhận giá mua.'
            ))
        if self.state != 'draft':
            raise UserError(_(
                'Chỉ phiếu ở trạng thái Nháp mới có thể xác nhận giá.'
            ))
        if self.t4_cost_confirmed:
            raise UserError(_('Giá đã được xác nhận trước đó.'))
        if not self.line_ids:
            raise UserError(_(
                'Phiếu chưa có dòng Linh Kiện Sử Dụng để xác nhận giá.'
            ))

        # Đọc flag config từ context (t4_sti.ir_http.session_info inject);
        # fallback singleton nếu thiếu (case CLI / migration / cron).
        ctx = self.env.context
        is_have_brand = ctx.get('is_have_brand')
        is_have_mfr = ctx.get('is_have_manufacturer')
        if is_have_brand is None or is_have_mfr is None:
            cfg = self.env['t4.sti.config'].sudo()._get_default()
            if is_have_brand is None:
                is_have_brand = bool(cfg and cfg.is_have_brand)
            if is_have_mfr is None:
                is_have_mfr = bool(cfg and cfg.is_have_manufacturer)

        # Validate: missing product_id (chống dòng rỗng do paste/import)
        no_product = self.line_ids.filtered(lambda l: not l.product_id)
        if no_product:
            raise UserError(_(
                'Có dòng Linh Kiện Sử Dụng chưa chọn sản phẩm — '
                'vui lòng kiểm tra lại.'
            ))

        # Validate: quantity > 0 (mirror _t4_check_demand_not_zero)
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

        # Validate: lot_name bắt buộc cho serial
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

        # Validate: Brd/Mfr S/N theo config (chỉ check serial — qty/no
        # tracking không cần Brd/Mfr).
        if is_have_brand or is_have_mfr:
            missing_part = self.line_ids.filtered(
                lambda l: l.product_id.tracking == 'serial'
                          and (
                              (is_have_brand and not l.brand_part_id and not l.manufacturer_part_id)
                              or (is_have_mfr and not l.manufacturer_part_id and not l.brand_part_id)
                          )
            )
            if missing_part:
                names = ', '.join(
                    missing_part.mapped('product_id.display_name')[:5]
                )
                raise UserError(_(
                    'Linh kiện serial phải có ít nhất 1 trong Brd. S/N hoặc '
                    'Mnf. S/N. Dòng còn thiếu: %(names)s',
                    names=names,
                ))

        self.write({
            't4_cost_confirmed': True,
            't4_cost_confirm_user_id': self.env.user.id,
            't4_cost_confirm_date': fields.Datetime.now(),
        })
        self.message_post(body=_(
            'Đã xác nhận giá mua bởi %(user)s. Tổng giá: %(total)s. '
            'Các dòng linh kiện đã được khoá.',
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

        fg_quant = self.lot_id.quant_ids.filtered(
            lambda q: q.location_id.usage == 'internal'
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
            quants_to_apply._apply_inventory()

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
            rec.state = 'cancel'

    def action_draft(self):
        """Đặt về Nháp — reset cost_confirmed để cho phép xác nhận giá lại.

        Không reset lại các stock.lot / stock.quant đã tạo (state=done →
        cancel → draft path không xảy ra theo design vì state=done không
        có nút cancel; chỉ cancel → draft). Nếu sau này mở rộng cho phép
        revert state=done → cần thêm rollback logic.
        """
        for rec in self:
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
