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

from odoo import _, api, fields, models
from odoo.exceptions import UserError

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
    )
    lot_id = fields.Many2one(
        'stock.lot',
        string='Mã Quản Lý Thành Phẩm',
        copy=False,
        tracking=True,
        domain="[('product_id', '=', product_id)]",
        help='Lot/Serial gắn cho thành phẩm. Với type=assembly sẽ tự '
             'tạo khi xác nhận; với type=identify user chọn lot có sẵn.',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Công Ty',
        default=lambda self: self.env.company,
        required=True,
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
    # Scan input (header-level barcode/scan)
    # ------------------------------------------------------------------
    barcode_input = fields.Char(
        string='Quét Mã Vạch',
        copy=False,
        help='Nhập / scan mã linh kiện. Click nút "Quét" để xử lý — '
             'hệ thống tự tìm lot → product → tạo dòng tương ứng.',
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
    image_tracking = fields.Binary(
        string='Hình Ảnh Xác Minh',
        help='Hình chụp xác minh phiếu đã hoàn thành (chữ ký, vật chứng).',
    )
    image_tracking_filename = fields.Char(string='Tên File')
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
        string='Tổng Giá Vốn',
        currency_field='cost_currency_id',
        compute='_compute_totals',
        store=True,
    )
    total_list_price = fields.Monetary(
        string='Tổng Giá Kho',
        currency_field='cost_currency_id',
        compute='_compute_totals',
        store=True,
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
    # Scan logic — port từ packing.slip.wizard.action_scan_barcode
    # ------------------------------------------------------------------
    def action_scan_barcode(self):
        """Xử lý barcode_input — thêm dòng linh kiện tương ứng."""
        self.ensure_one()
        if not self.barcode_input:
            return False
        barcode = self.barcode_input.strip()
        if not barcode:
            self.barcode_input = False
            return False

        # Ưu tiên 1: tìm lot/serial có sẵn (định danh đã tồn tại)
        lot = self.env['stock.lot'].search(
            [('name', '=', barcode)], limit=1,
        )
        if lot:
            self._add_line_from_lot(lot)
            self.barcode_input = False
            return True

        # Ưu tiên 2: tìm product theo barcode
        product = self.env['product.product'].search(
            [('barcode', '=', barcode)], limit=1,
        )
        if not product:
            # Ưu tiên 3: default_code (mã sản phẩm nội bộ)
            product = self.env['product.product'].search(
                [('default_code', '=', barcode)], limit=1,
            )
        if product:
            self._add_line_from_product(product)
            self.barcode_input = False
            return True

        raise UserError(_(
            'Không tìm thấy lot/serial hoặc sản phẩm tương ứng với mã: %s',
            barcode,
        ))

    def _add_line_from_lot(self, lot):
        """Thêm dòng từ stock.lot — auto-fill product + snapshot price."""
        self.line_ids = [(0, 0, {
            'line_type': 'used',
            'product_id': lot.product_id.id,
            'lot_id': lot.id,
            'quantity': 1.0,
            'standard_price': lot.product_id.standard_price,
            'list_price': lot.product_id.lst_price,
        })]

    def _add_line_from_product(self, product):
        """Thêm dòng từ product (chưa có lot — tracking='none' hoặc lot mới)."""
        self.line_ids = [(0, 0, {
            'line_type': 'used',
            'product_id': product.id,
            'quantity': 1.0,
            'standard_price': product.standard_price,
            'list_price': product.lst_price,
        })]

    # ------------------------------------------------------------------
    # Workflow actions
    # ------------------------------------------------------------------
    def action_confirm(self):
        """Xác nhận phiếu — chuyển state=done.

        Với type='assembly': tự tạo lot mới cho FG nếu chưa có và FG
        là tracking='serial'. Đồng bộ qty_packed lên packing_request_id
        nếu liên kết.
        """
        for rec in self:
            if rec.state == 'done':
                continue
            if not rec.line_ids:
                raise UserError(_(
                    'Phiếu phải có ít nhất 1 dòng linh kiện trước khi xác nhận.'
                ))

            if rec.type == 'assembly' and not rec.lot_id and rec.product_id.tracking == 'serial':
                rec.lot_id = self.env['stock.lot'].create({
                    'product_id': rec.product_id.id,
                    'company_id': rec.company_id.id,
                })

            if rec.type == 'identify' and not rec.lot_id:
                raise UserError(_(
                    'Phiếu định danh phải có Mã Quản Lý Thành Phẩm trước khi '
                    'xác nhận.'
                ))

            if rec.packing_request_id:
                rec._sync_packing_request_qty_packed()

            rec.state = 'done'

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
        for rec in self:
            rec.state = 'draft'

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
