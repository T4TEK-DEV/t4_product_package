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
        help='Giá mua của thành phẩm tại thời điểm hiển thị. SN-AVCO '
             '(lot_valuated) → giá vốn per-lot của serial cụ thể; còn lại '
             '→ product.standard_price (trung bình).',
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

    @api.depends('product_id.standard_price', 'product_id.lot_valuated',
                 'lot_id.standard_price')
    def _compute_purchase_price(self):
        """Giá mua TP: SN-AVCO (lot_valuated) → giá vốn per-lot của serial
        cụ thể (lot.standard_price); còn lại → product.standard_price
        (trung bình). Mirror `t4.product.creation.line._t4_snapshot_standard_price`.
        """
        for rec in self:
            product = rec.product_id
            if (product and product.lot_valuated
                    and rec.lot_id and rec.lot_id.standard_price):
                rec.purchase_price = rec.lot_id.standard_price
            else:
                rec.purchase_price = (product.standard_price or 0.0) if product else 0.0

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

    @api.constrains('lot_id', 'lot_name', 'type', 'state')
    def _check_identify_fg_unique(self):
        """Phiếu Định Danh LK TP: mỗi Thành Phẩm chỉ được định danh 1 lần.

        Chặn tạo / lưu phiếu Định Danh mới cho một FG (Mã Quản Lý TP) đã
        có phiếu Định Danh khác — dù phiếu đó đã hoàn thành (done) hay
        đang dở (draft / waiting). Phiếu đã huỷ (cancel) KHÔNG tính →
        muốn định danh lại phải huỷ phiếu cũ trước.

        Backstop cho onchange (warning có thể bị bypass qua RPC / import /
        paste batch). Chỉ kiểm tra phiếu type='identify' chưa done/cancel:
        phiếu done là đối tượng được so trùng, không tự xét chính nó.
        So trùng FG theo lot_id (ưu tiên) hoặc lot_name (bắt cả phiếu nháp
        chưa resolve được lot_id).
        """
        for rec in self:
            if rec.type != 'identify' or rec.state in ('done', 'cancel'):
                continue
            fg_name = (rec.lot_id.name if rec.lot_id
                       else rec.lot_name and rec.lot_name.strip())
            if not fg_name:
                continue
            conflict = self.sudo().search([
                ('id', '!=', rec.id),
                ('type', '=', 'identify'),
                ('state', '!=', 'cancel'),
                '|', ('lot_id.name', '=', fg_name), ('lot_name', '=', fg_name),
            ], limit=1)
            if not conflict:
                continue
            state_label = dict(
                self._fields['state'].selection
            ).get(conflict.state, conflict.state)
            raise ValidationError(_(
                'Thành phẩm "%(fg)s" đã có phiếu Định Danh [%(phieu)s] '
                '(%(state)s). Mỗi thành phẩm chỉ được định danh một lần. '
                'Hãy kiểm tra — hoặc huỷ phiếu đó — trước khi tạo phiếu mới.',
                fg=fg_name,
                phieu=conflict.name or str(conflict.id),
                state=state_label,
            ))

    @api.constrains('lot_id', 'lot_name', 'line_ids', 'line_returned_ids')
    def _check_component_not_self_fg(self):
        """Chặn TỰ THAM CHIẾU: linh kiện KHÔNG được trùng chính Thành Phẩm
        (FG) của phiếu — cùng serial/lot hoặc cùng Mã Quản Lý.

        Một serial không thể vừa là thành phẩm vừa là linh kiện của chính
        nó ("vừa làm cha vừa làm con"). Áp dụng cả assembly lẫn identify,
        mọi dòng (Sử Dụng lẫn Trả). So khớp theo:
          - lot_id (ưu tiên): dòng.lot_id == FG.lot_id, HOẶC
          - Mã Quản Lý: lot_name/lot_id.name của dòng trùng của FG (bắt cả
            trường hợp chưa resolve được lot_id — RPC/import/paste).

        Backstop cho các luồng KHÔNG qua onchange. Chỉ so cùng serial (KHÔNG
        chặn cùng product khác serial — đó là phạm vi ràng buộc BOM
        `t4.product.component`).
        """
        for rec in self:
            if rec.state == 'cancel':
                continue
            fg_lot = rec.lot_id
            fg_name = (fg_lot.name if fg_lot else False) or (
                rec.lot_name and rec.lot_name.strip())
            if not fg_lot and not fg_name:
                continue
            for line in (rec.line_ids | rec.line_returned_ids):
                line_name = (line.lot_id.name if line.lot_id else False) or (
                    line.lot_name and line.lot_name.strip())
                same_lot = bool(fg_lot and line.lot_id and line.lot_id == fg_lot)
                same_name = bool(fg_name and line_name and fg_name == line_name)
                if same_lot or same_name:
                    raise ValidationError(_(
                        'Linh kiện "%(comp)s" (Mã Quản Lý "%(code)s") trùng '
                        'chính Thành Phẩm của phiếu — một sản phẩm không thể '
                        'vừa là thành phẩm vừa là linh kiện của chính nó.',
                        comp=line.product_id.display_name or _('(chưa chọn)'),
                        code=line_name or fg_name or '',
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
            # Cảnh báo sớm: FG này đã có phiếu Định Danh khác (done hoặc
            # đang dở). Backstop cứng nằm ở _check_identify_fg_unique.
            existing_phieu = self.env['t4.product.creation'].sudo().search([
                ('id', '!=', self._origin.id),
                ('type', '=', 'identify'),
                ('state', '!=', 'cancel'),
                ('lot_id', '=', lot.id),
            ], limit=1)
            if existing_phieu:
                state_label = dict(
                    self._fields['state'].selection
                ).get(existing_phieu.state, existing_phieu.state)
                self.lot_id = False
                self.lot_name = False
                self.product_id = False
                return {
                    'warning': {
                        'title': _('Thành phẩm đã được định danh'),
                        'message': _(
                            'Thành phẩm "%(fg)s" đã có phiếu Định Danh '
                            '[%(phieu)s] (%(state)s). Mỗi thành phẩm chỉ '
                            'được định danh một lần.',
                            fg=lot.name,
                            phieu=existing_phieu.name or str(existing_phieu.id),
                            state=state_label,
                        ),
                    }
                }
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

    def unlink(self):
        """Chặn xoá phiếu đã hoàn thành / xác nhận.

        - Lắp Ráp (assembly): khi đã Xác Nhận → state='done' → không xoá.
        - Định Danh (identify): có thêm bước "Hoàn Thành" → state='waiting'
          (Chờ Nhập Giá); từ bước này trở đi (kể cả 'done') không được xoá.

        Phiếu 'draft' (đang nhập) và 'cancel' (đã huỷ) vẫn xoá được — cron
        dọn nháp rỗng và việc dọn phiếu huỷ vẫn hoạt động bình thường. Muốn
        xoá phiếu đang 'waiting' phải Huỷ (action_cancel) trước.
        """
        blocked = self.filtered(lambda r: r.state in ('waiting', 'done'))
        if blocked:
            names = ', '.join(blocked.mapped('name')[:5])
            raise UserError(_(
                'Không thể xoá phiếu đã hoàn thành: %(names)s.',
                names=names,
            ))
        return super().unlink()

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
                    self.env['t4.error.helper']._raise_duplicate(
                        message=_(
                            'S/N Nhãn Hiệu "%(sn)s" của linh kiện "%(prod)s" '
                            'đã tồn tại trong hệ thống (Lot: %(lot)s). '
                            'Không thể định danh trùng.',
                            sn=line.brand_part_id,
                            prod=line.product_id.display_name,
                            lot=dup.name,
                        ),
                        model='stock.lot',
                        res_id=dup.id,
                        button_label=_('Mở lot/serial bị trùng'),
                    )

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
                    self.env['t4.error.helper']._raise_duplicate(
                        message=_(
                            'S/N Nhà Sản Xuất "%(sn)s" của linh kiện "%(prod)s" '
                            'đã tồn tại trong hệ thống (Lot: %(lot)s). '
                            'Không thể định danh trùng.',
                            sn=line.manufacturer_part_id,
                            prod=line.product_id.display_name,
                            lot=dup.name,
                        ),
                        model='stock.lot',
                        res_id=dup.id,
                        button_label=_('Mở lot/serial bị trùng'),
                    )

        # Sign-wizard intercept — CHUYỂN TỪ action_confirm_cost sang đây
        # (v1.0.23): KỸ THUẬT bấm "Hoàn Thành" phải IN phiếu + úp ảnh xác minh
        # nếu cấu hình `is_required_print_identify` bật. Kế toán "Xác Nhận Giá"
        # sau đó KHÔNG qua form úp ảnh nữa. Wizard re-call action_complete với
        # `t4_bypass_sign_wizard=True`.
        ctx = self.env.context
        if not ctx.get('t4_bypass_sign_wizard') and ctx.get('is_required_print_identify'):
            if not self.is_have_printed:
                raise UserError(_('Vui lòng in phiếu trước khi hoàn thành.'))
            if not self.image_tracking_attachment_id:
                return {
                    'type': 'ir.actions.act_window',
                    'name': _('Upload Hình Ảnh Xác Minh'),
                    'res_model': 't4.product.creation.sign.wizard',
                    'view_mode': 'form',
                    'target': 'new',
                    'context': {'default_creation_id': self.id},
                }

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

            rec._t4_auto_return_dropped_components()
            rec._t4_check_returned_consistency()

            if rec.packing_request_id:
                rec._sync_packing_request_qty_packed()

            rec.state = 'done'

            # Invalidate FG lot's cache để UI "Linh Kiện Đã Lắp" net lại
            # ngay sau khi confirm (returned line đã có trong line_returned_ids
            # → recompute sẽ trừ used tương ứng). Mirror identify flow ở
            # `_t4_create_component_lots`.
            if rec.lot_id:
                rec.lot_id.invalidate_recordset([
                    'fg_component_line_ids',
                    'fg_all_component_line_ids',
                ])

    def _t4_auto_return_dropped_components(self):
        """A2 — "phiếu lắp ráp mới nhất là danh sách hiện tại của FG".

        Khi xác nhận phiếu lắp ráp, linh kiện thuộc cấu thành CŨ (phiếu done
        trước — `_t4_get_committed_components`, nay đã DEDUPE) mà phiếu này
        KHÔNG còn dùng (đã xóa) hoặc giảm số lượng → tự tạo dòng "Linh Kiện
        Trả" để gỡ/giảm chúng. Cả 2 cách gỡ (xóa dòng used / thêm dòng Trả
        tay) hội tụ về cùng cơ chế.

        Bất biến: **sau confirm, cấu thành FG == danh sách "Sử Dụng" của phiếu
        này**.

        **v1.0.23 — TRẢ ĐÚNG DELTA (không còn trả full baseline):** vì
        `_t4_get_committed_components` đã bỏ cộng dồn + dedupe theo (product,
        lot), baseline = cấu thành thực (mỗi mã 1 lần). Lượng trả mỗi key =
        `baseline − used(phiếu này) − đã_trả_sẵn`. Linh kiện GIỮ LẠI (có trong
        "Sử Dụng" mới) → to_return = 0 → KHÔNG trả. Linh kiện BỊ BỎ → trả đúng
        phần chênh. → "xóa 1 dòng serial ⇒ trả đúng 1 dòng" (trước đây ra 2 vì
        đếm đôi qua phiếu định danh + lắp ráp).

        Điền `lot_name` + Brd/Mfr S/N từ lot cho dòng trả (cột "Mã Quản Lý"
        bind `lot_name` char passenger, không phải `lot_id`) → không còn rỗng.

        KHÔNG di chuyển tồn kho (assembly confirm không tạo move) → linh kiện
        free tại 'Lắp ráp'. `is_scrap=False`. Idempotent (trừ phần đã trả sẵn).
        """
        self.ensure_one()
        if self.type != 'assembly' or not self.lot_id:
            return
        # CHỈ áp dụng cho phiếu RE-ASSEMBLY (có dòng "Sử Dụng" = danh sách
        # đầy đủ mới). Phiếu CHỈ-TRẢ (line_ids rỗng, chỉ có line_returned_ids)
        # là ĐIỀU CHỈNH incremental — returns của nó net trừ trực tiếp, KHÔNG
        # được coi là "redefine danh sách = rỗng" (sẽ trả nhầm toàn bộ FG).
        if not self.line_ids:
            return
        baseline = self.lot_id._t4_get_committed_components()
        if not baseline:
            return
        used = defaultdict(float)
        for ln in self.line_ids:
            if ln.product_id and ln.quantity:
                used[(ln.product_id.id, ln.lot_id.id or 0)] += ln.quantity
        already = defaultdict(float)
        for ln in self.line_returned_ids:
            if ln.product_id and ln.quantity:
                already[(ln.product_id.id, ln.lot_id.id or 0)] += ln.quantity
        Lot = self.env['stock.lot']
        new_lines = []
        for key, base_qty in baseline.items():
            pid, lid = key
            if lid:
                # Serial/lot (deduped): trả ĐÚNG DELTA — cấu thành cũ − dùng lại
                # ở phiếu này − đã trả sẵn. Giữ lại (used khớp) → to_return = 0
                # → "xóa 1 mã serial ⇒ trả đúng 1 dòng".
                to_return = base_qty - used.get(key, 0.0) - already.get(key, 0.0)
            else:
                # Non-serial (tracking='none', lot_id=0): committed CỘNG DỒN qua
                # các phiếu (không dedupe) → phải trả TOÀN BỘ baseline cũ để triệt
                # tiêu; phần giữ lại được cộng lại qua dòng used của chính phiếu
                # này. Vd cũ 5, phiếu này dùng 3: trả 5 → net = 5+3−5 = 3.
                to_return = base_qty - already.get(key, 0.0)
            if to_return > 0:
                vals = {
                    'state': 'returned',
                    'product_id': pid,
                    'lot_id': lid or False,
                    'quantity': to_return,
                    'is_scrap': False,
                }
                # Điền char passenger từ lot (cột "Mã Quản Lý"/Brd/Mfr bind
                # các field char này, không bind lot_id) → dòng trả không rỗng.
                if lid:
                    lot = Lot.browse(lid)
                    vals['lot_name'] = lot.name
                    vals['brand_part_id'] = lot.brand_part_id or False
                    vals['manufacturer_part_id'] = lot.manufacturer_part_id or False
                new_lines.append((0, 0, vals))
        if new_lines:
            self.line_returned_ids = new_lines

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

        # Sign-wizard (IN + úp ảnh) đã CHUYỂN sang nút "Hoàn Thành"
        # (action_complete, v1.0.23). Kế toán "Xác Nhận Giá" bấm thẳng, KHÔNG
        # qua form úp ảnh nữa.

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
        #
        # CRITICAL: cho AVCO/FIFO products (cost_method != 'standard'),
        # KHÔNG ghi đè product.standard_price. Việc ghi sẽ trigger
        # `_change_standard_price` của stock_account → tạo "Price update"
        # SVL blast AVCO avg về giá user nhập, phá lịch sử pool. Odoo
        # tự recompute avg từ pool sau mỗi incoming move. User's
        # line.standard_price chỉ informational trên line (không inject
        # vào pool valuation). Standard-Manual products dùng user cost
        # làm standard_price cố định — vẫn ghi như cũ.
        for cost, lots in cost_to_lots.items():
            lots.standard_price = cost
        for cost, products in cost_to_products.items():
            standard_products = products.filtered(
                lambda p: p.cost_method == 'standard'
            )
            if standard_products:
                standard_products.standard_price = cost

        # ----------------------------------------------------------
        # Pass 2: tạo quant với inventory_quantity → _apply_inventory.
        # Tracking='none' tạo quant không lot_id (Odoo cho phép); svl
        # sẽ dùng product.standard_price đã set ở Pass 1.
        #
        # CRITICAL: `inventory_quantity` là TARGET ABSOLUTE qty — Odoo
        # tính delta = inventory_quantity − current_qty rồi tạo move.
        # Nếu quant đã tồn tại (vd: tracking='none' merge theo product+
        # location, hoặc lot tái sử dụng) và current_qty=100, set
        # inventory_quantity=3 → delta=-97 → stock giảm 97 thay vì +3.
        # → Phải tính target = (current_qty + line.quantity).
        # ----------------------------------------------------------
        quants_to_apply = Quant
        for line, new_lot in line_lot_pairs:
            # Tìm quant tồn tại (merge target của Odoo) để compute target
            # qty đúng. Match: cùng product + location + lot (hoặc no-lot).
            existing_domain = [
                ('product_id', '=', line.product_id.id),
                ('location_id', '=', fg_location.id),
            ]
            if new_lot:
                existing_domain.append(('lot_id', '=', new_lot.id))
            else:
                existing_domain.append(('lot_id', '=', False))
            existing = Quant.search(existing_domain, limit=1)
            target_qty = (existing.quantity if existing else 0.0) + line.quantity

            quant_vals = {
                'product_id': line.product_id.id,
                'location_id': fg_location.id,
                'inventory_quantity': target_qty,
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
        # Đồng thời invalidate biến thể đệ quy (UI tab "Linh Kiện Đã Lắp"
        # của stock.quant dùng `fg_all_component_line_ids`). Chỉ invalidate
        # cho lot hiện tại — nếu sub-FG được identify mới, parent FG sẽ
        # cần re-open form để thấy update (chấp nhận được vì UI-only).
        self.lot_id.invalidate_recordset([
            'fg_component_line_ids',
            'fg_all_component_line_ids',
        ])

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

