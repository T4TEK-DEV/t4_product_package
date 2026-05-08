# -*- coding: utf-8 -*-
"""Dòng linh kiện thuộc phiếu t4.product.creation.

Mỗi dòng = 1 lần sử dụng (line_type='used') hoặc 1 lần trả lại
(line_type='returned') của 1 linh kiện trong quá trình lắp ráp / định
danh thành phẩm. Lưu snapshot giá tại thời điểm tạo để truy vết kế
toán độc lập với lịch sử biến động giá sau này.
"""
from odoo import api, fields, models


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
    line_type = fields.Selection(
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
    # Snapshot price (giá vốn / giá kho tại thời điểm tạo phiếu)
    # ------------------------------------------------------------------
    standard_price = fields.Float(
        string='Giá Vốn',
        digits='Product Price',
        help='Lưu trữ giá vốn của linh kiện tại thời điểm tạo phiếu.',
    )
    list_price = fields.Float(
        string='Giá Kho',
        digits='Product Price',
        help='Lưu trữ giá kho của linh kiện tại thời điểm tạo phiếu.',
    )
    cost_currency_id = fields.Many2one(
        related='creation_id.cost_currency_id',
        readonly=True,
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

    # ------------------------------------------------------------------
    # Scan inputs (port từ v18: barcode_input + card_code)
    # ------------------------------------------------------------------
    barcode_input = fields.Char(
        string='Barcode',
        help='Mã vạch do người dùng nhập hoặc từ máy quét.',
    )
    card_code = fields.Char(
        string='Mã Thẻ',
        help='Mã thẻ RFID được gắn cho dòng thông tin này.',
    )

    # ------------------------------------------------------------------
    # Brand / Manufacturer Serial Number (port từ v18 supplier_part_id_temp /
    # manufacturer_part_id_temp). Là Char snapshot — đồng bộ semantic với
    # stock.lot.brand_part_id / manufacturer_part_id của module
    # t4_sti_brand_manufacturer (cũng là Char). Khi xác nhận phiếu có thể
    # propagate xuống stock.lot tương ứng (TODO).
    # ------------------------------------------------------------------
    brand_part_id = fields.Char(
        string='Brd. S/N',
        help='Số sê-ri do nhãn hiệu hoặc nhà cung cấp phân bổ.',
    )
    manufacturer_part_id = fields.Char(
        string='Mnf. S/N',
        help='Số sê-ri do nhà sản xuất phân bổ.',
    )

    # ------------------------------------------------------------------
    # Returned line specifics (chỉ dùng khi line_type='returned')
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
        """Khi user gõ/quét lot_name, tìm stock.lot và bind lot_id, S/N.

        - Filter theo product_id nếu đã chọn (lot trùng tên với product
          khác sẽ không match).
        - Không khớp → giữ lot_name; không xoá dữ liệu hiện có.
        - Khớp → set lot_id, fill product_id (nếu chưa có), snapshot
          brand/manufacturer S/N (chỉ khi line chưa có giá trị, tránh
          đè entry thủ công).
        """
        if not self.lot_name:
            return
        domain = [('name', '=', self.lot_name.strip())]
        if self.product_id:
            domain.append(('product_id', '=', self.product_id.id))
        lot = self.env['stock.lot'].search(domain, limit=1)
        if not lot:
            return
        self.lot_id = lot
        if not self.product_id and lot.product_id:
            self.product_id = lot.product_id
        if not self.brand_part_id and lot.brand_part_id:
            self.brand_part_id = lot.brand_part_id
        if not self.manufacturer_part_id and lot.manufacturer_part_id:
            self.manufacturer_part_id = lot.manufacturer_part_id

    @api.onchange('lot_id')
    def _onchange_lot_id_sync_name(self):
        """Sync lot_id → lot_name khi lot được set qua dropdown ẩn / RPC."""
        if self.lot_id and self.lot_id.name != self.lot_name:
            self.lot_name = self.lot_id.name
