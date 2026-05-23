# -*- coding: utf-8 -*-
"""Dòng linh kiện thuộc phiếu t4.product.creation.

Mỗi dòng = 1 lần sử dụng (state='used') hoặc 1 lần trả lại
(state='returned') của 1 linh kiện trong quá trình lắp ráp / định
danh thành phẩm. Lưu snapshot giá tại thời điểm tạo để truy vết kế
toán độc lập với lịch sử biến động giá sau này.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductCreationLine(models.Model):
    _name = 't4.product.creation.line'
    _description = 'Linh kiện - Phiếu Lắp Ráp/Định Danh'
    _order = 'sequence, id'

    # ------------------------------------------------------------------
    # Identity & relationships
    # ------------------------------------------------------------------
    sequence = fields.Integer(default=10)
    creation_id = fields.Many2one(
        't4.product.creation',
        string='Phiếu',
        required=True,
        ondelete='cascade',
        index=True,
    )
    state = fields.Selection(
        selection=[
            ('used', 'Sử Dụng'),
            ('returned', 'Trả'),
        ],
        string='Loại Dòng',
        required=True,
        default='used',
        index=True,
        help='Phân loại linh kiện: đã sử dụng để lắp ráp, hoặc bị trả lại/thay thế.',
    )
    # Related to make domain/invisible on view simpler
    wizard_type = fields.Selection(related='creation_id.type', store=False)
    parent_state = fields.Selection(related='creation_id.state', store=False)
    parent_cost_confirmed = fields.Boolean(
        related='creation_id.t4_cost_confirmed', store=False,
    )

    # ------------------------------------------------------------------
    # Product & lot
    # ------------------------------------------------------------------
    product_id = fields.Many2one(
        'product.product',
        string='Linh Kiện',
        required=True,
        domain="[('categ_tech_id.is_combo', '=', False)]" if False else "[]",
    )
    tracking = fields.Selection(related='product_id.tracking', store=False)
    lot_id = fields.Many2one(
        'stock.lot',
        string='Mã Quản Lý (ref)',
        domain="[('product_id', '=', product_id)]",
        ondelete='restrict',
    )
    lot_name = fields.Char(
        string='Mã Quản Lý',
        help='Tên lot/serial của linh kiện. Nhập hoặc quét trực tiếp — '
             'hệ thống tự tìm lot khớp tên (lọc theo product_id nếu đã chọn) '
             'và set lot_id + snapshot Brd/Mfr S/N.',
    )
    quantity = fields.Float(
        string='Số Lượng',
        default=1.0,
        required=True,
        digits='Product Unit of Measure',
    )
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='Đơn Vị',
        related='product_id.uom_id',
        readonly=True,
    )

    # ------------------------------------------------------------------
    # Price — auto-computed từ product/lot (stored cho perf)
    # ------------------------------------------------------------------
    # standard_price: lot-valuated (SN AVCO) → lot.standard_price (per-lot),
    # else product.standard_price. list_price: product.lst_price (template).
    # Stored để summary `total_standard_price` recompute đúng + tránh N+1
    # query khi list nhiều dòng. Tự cập nhật khi product/lot đổi giá.
    standard_price = fields.Float(
        string='Giá Mua',
        digits='Product Price',
        compute='_compute_standard_price',
        store=True,
        readonly=True,
        help='Giá mua linh kiện. Lot-valuated: per-lot từ stock.lot. '
             'Còn lại: từ product.standard_price.',
    )
    list_price = fields.Float(
        related='product_id.lst_price',
        store=True,
        string='Giá Kho',
        digits='Product Price',
        readonly=True,
        help='Giá kho (sale price) — related từ product.lst_price.',
    )

    @api.depends('product_id', 'product_id.standard_price',
                 'product_id.lot_valuated',
                 'lot_id', 'lot_id.standard_price')
    def _compute_standard_price(self):
        for line in self:
            product = line.product_id
            if not product:
                line.standard_price = 0.0
                continue
            if product.lot_valuated and line.lot_id and line.lot_id.standard_price:
                line.standard_price = line.lot_id.standard_price
            else:
                line.standard_price = product.standard_price or 0.0
    cost_currency_id = fields.Many2one(
        related='creation_id.cost_currency_id',
        readonly=True,
    )
    total_standard_price = fields.Monetary(
        string='Tổng Giá Mua',
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

    # ------------------------------------------------------------------
    # Brand / Manufacturer Serial Number — Char snapshot.
    # Assembly: onchange `_onchange_lot_name` copy từ lot_id khi resolve.
    # Identify: user nhập tay (lot chưa tồn tại tại thời điểm tạo line).
    # ------------------------------------------------------------------
    brand_part_id = fields.Char(
        string='Brd. S/N',
        help='Số sê-ri do nhãn hiệu hoặc nhà cung cấp phân bổ. '
             'Snapshot từ stock.lot khi assembly; user nhập tay khi identify.',
    )
    manufacturer_part_id = fields.Char(
        string='Mnf. S/N',
        help='Số sê-ri do nhà sản xuất phân bổ. Tương tự brand_part_id.',
    )

    # ------------------------------------------------------------------
    # Returned line specifics (chỉ dùng khi state='returned')
    # ------------------------------------------------------------------
    is_scrap = fields.Boolean(
        string='Hư Hỏng',
        default=False,
        help='Đánh dấu nếu linh kiện trả lại bị hư hỏng, hệ thống sẽ tự động chuyển vào kho phế phẩm.',
    )
    note = fields.Char(string='Ghi Chú')

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------
    @api.depends('quantity', 'standard_price', 'list_price')
    def _compute_totals(self):
        for line in self:
            line.total_standard_price = line.quantity * line.standard_price
            line.total_list_price = line.quantity * line.list_price

    # ------------------------------------------------------------------
    # Onchange — resolve lot_name → lot_id + snapshot Brd/Mfr S/N
    # ------------------------------------------------------------------
    @api.onchange('lot_name', 'product_id')
    def _onchange_lot_name(self):
        """Khi user gõ/quét lot_name, hành xử theo wizard_type.

        - assembly (lắp ráp): linh kiện ĐÃ được định danh trước đó —
          find existing lot, bind `lot_id`, fill `product_id` (nếu
          chưa có) và snapshot Brd/Mfr S/N.

        - identify (định danh LK TP): mã CHƯA tồn tại — đây là lần
          đầu định danh cho linh kiện. Mirror pattern
          `int_serial_assign` (Phiếu Định Danh Sản Phẩm): nếu mã đã
          tồn tại trong `stock.lot` (bất kỳ product nào) → trả
          warning + clear `lot_name`. KHÔNG auto-fill Brd/Mfr S/N
          (user nhập tay).
        """
        if not self.lot_name:
            return
        name = self.lot_name.strip()

        if self.wizard_type == 'identify':
            existing = self.env['stock.lot'].sudo().search(
                [('name', '=', name)], limit=1,
            )
            if existing:
                self.lot_name = False
                return {
                    'warning': {
                        'title': _('Mã đã được định danh'),
                        'message': _(
                            'Mã "%(tag)s" đã được định danh cho sản phẩm '
                            '"%(prod)s" trong hệ thống, không thể định danh lại.',
                            tag=name,
                            prod=existing.product_id.display_name
                                 or _('(không xác định)'),
                        ),
                    }
                }
            return

        domain = [('name', '=', name)]
        if self.product_id:
            domain.append(('product_id', '=', self.product_id.id))
        lot = self.env['stock.lot'].search(domain, limit=1)
        if not lot:
            return
        self.lot_id = lot
        if not self.product_id and lot.product_id:
            self.product_id = lot.product_id
        # Copy Brd/Mfr S/N từ lot làm snapshot — chỉ fill khi user chưa nhập
        # tay (assembly path; identify giữ giá trị user gõ).
        if not self.brand_part_id and lot.brand_part_id:
            self.brand_part_id = lot.brand_part_id
        if not self.manufacturer_part_id and lot.manufacturer_part_id:
            self.manufacturer_part_id = lot.manufacturer_part_id
        # standard_price / list_price tự compute từ product/lot — không cần
        # snapshot ở đây (xem `_compute_standard_price` + related list_price).

    @api.onchange('lot_id')
    def _onchange_lot_id_sync_name(self):
        """Sync lot_id → lot_name khi lot được set qua dropdown ẩn / RPC."""
        if self.lot_id and self.lot_id.name != self.lot_name:
            self.lot_name = self.lot_id.name

    # ------------------------------------------------------------------
    # Server-side guards — chốt chặn cho luồng định danh
    # ------------------------------------------------------------------
    @api.constrains('lot_name', 'state', 'creation_id')
    def _check_identify_lot_name_unique(self):
        """Phiếu Định Danh LK TP: lot_name của Linh Kiện Sử Dụng phải
        chưa tồn tại trong hệ thống và không được trùng giữa các dòng.

        Backup cho onchange (warning có thể bị bypass khi tạo qua RPC,
        import, hoặc paste batch). Chỉ áp dụng cho state='used' của
        phiếu type='identify'.
        """
        Lot = self.env['stock.lot'].sudo()
        for rec in self:
            if rec.creation_id.type != 'identify':
                continue
            if rec.state != 'used':
                continue
            if not rec.lot_name:
                continue
            name = rec.lot_name.strip()

            existing = Lot.search([('name', '=', name)], limit=1)
            if existing:
                raise ValidationError(_(
                    'Mã "%(tag)s" đã được định danh cho sản phẩm '
                    '"%(prod)s" trong hệ thống, không thể định danh lại.',
                    tag=name,
                    prod=existing.product_id.display_name
                         or _('(không xác định)'),
                ))

            siblings = rec.creation_id.line_ids.filtered(
                lambda l: l.id != rec.id
                          and l.state == 'used'
                          and l.lot_name
                          and l.lot_name.strip() == name
            )
            if siblings:
                raise ValidationError(_(
                    'Mã "%(tag)s" bị trùng giữa các dòng Linh Kiện Sử Dụng '
                    'trong cùng phiếu. Mỗi mã chỉ được định danh 1 lần.',
                    tag=name,
                ))

    @api.constrains('lot_name', 'creation_id')
    def _check_lot_name_not_in_active_phieu(self):
        """Chặn lot_name đang được dùng trong phiếu khác chưa hoàn thành.

        Cover cả line_ids (state='used') lẫn line_returned_ids
        (state='returned') của phiếu lắp ráp. Bỏ qua khi phiếu
        hiện tại đã done/cancel.
        """
        for line in self:
            if not line.lot_name or line.creation_id.state in ('done', 'cancel'):
                continue
            name = line.lot_name.strip()
            conflict = self.search([
                ('id', '!=', line.id),
                ('lot_name', '=', name),
                ('creation_id', '!=', line.creation_id.id),
                ('creation_id.state', 'in', ('draft', 'waiting')),
            ], limit=1)
            if not conflict:
                continue
            phieu = conflict.creation_id
            state_map = dict(
                self.env['t4.product.creation']._fields['state'].selection
            )
            state_label = state_map.get(phieu.state, phieu.state)
            tab = _('Linh Kiện Trả') if conflict.state == 'returned' \
                else _('Linh Kiện Sử Dụng')
            fg_label = phieu.lot_id.name or phieu.lot_name or _('chưa scan')
            raise ValidationError(_(
                'Thao tác không hợp lệ: Mã "%(name)s" đang được phiếu '
                '[%(phieu)s] (%(state)s) của FG "%(fg)s" chứa trong tab '
                '%(tab)s. Kiểm tra phiếu đó trước khi tiếp tục.',
                name=name,
                phieu=phieu.name or str(phieu.id),
                state=state_label,
                fg=fg_label,
                tab=tab,
            ))

    @api.constrains('lot_id', 'state', 'creation_id', 'product_id')
    def _check_lot_not_committed_to_other_fg(self):
        """Lot/serial của linh kiện đã thuộc FG khác (done) còn ở Lắp ráp
        thì không được sử dụng cho FG mới — phải trả từ FG cũ trước.

        Chỉ áp dụng cho dòng `used` của phiếu type='assembly' chưa done.
        Sử dụng `_t4_get_committed_components` để xét cả trường hợp lot
        đã được trả lại bằng phiếu khác (committed_qty = 0 → cho phép).
        """
        for line in self:
            if (line.creation_id.type != 'assembly'
                    or line.creation_id.state in ('done', 'cancel')
                    or line.state != 'used'
                    or not line.lot_id
                    or not line.product_id):
                continue
            self_fg_lot = line.creation_id.lot_id
            assembly_location = self.env['stock.location'].search([
                ('name', '=', 'Lắp ráp'),
                ('usage', '=', 'internal'),
            ], limit=1)
            if not assembly_location:
                continue
            # Tìm các FG khác có lot này trong committed (sau net trả)
            other_fg_quants = self.env['stock.quant'].sudo().search([
                ('location_id', '=', assembly_location.id),
                ('lot_id', '!=', False),
                ('quantity', '>', 0),
            ])
            other_fg_lots = other_fg_quants.lot_id - self_fg_lot
            key = (line.product_id.id, line.lot_id.id)
            for fg_lot in other_fg_lots:
                committed = fg_lot._t4_get_committed_components().get(key)
                if committed:
                    raise ValidationError(_(
                        'Linh kiện "%(comp)s" (lot %(lot)s) đang thuộc FG '
                        '"%(fg_prod)s" [%(fg_lot)s] còn ở kho Lắp ráp. '
                        'Phải trả lại từ FG đó trước khi dùng cho FG mới.',
                        comp=line.product_id.display_name,
                        lot=line.lot_id.name,
                        fg_prod=fg_lot.product_id.display_name,
                        fg_lot=fg_lot.name,
                    ))

