# -*- coding: utf-8 -*-
from odoo import api, fields, models


class T4ProductCreationSummary(models.TransientModel):
    """Aggregate của `fg_all_component_line_ids` theo `(lot, product)`.

    Mỗi record = 1 sản phẩm linh kiện đã lắp vào 1 lot FG (đệ quy mọi
    cấp sub-FG), với `quantity = SUM(line.quantity)` cộng dồn từ mọi
    line cùng product. Phục vụ tab "Cấu Thành" trên form stock.quant —
    gom các dòng cùng product thành 1 dòng + group theo `categ_tech_id`.

    Là `TransientModel` vì:
      - Records build trên-demand mỗi khi `stock.lot.fg_component_summary_ids`
        được compute, qua aggregation từ `fg_all_component_line_ids`.
      - Tự auto-vacuum (`_transient_max_hours`) để không phình bảng.
      - Không cần SQL VIEW — rel table M2M `stock_lot_fg_all_component_line_rel`
        không tồn tại physical vì M2M cha là computed-only.
    """

    _name = "t4.product.creation.summary"
    _description = "FG Component Summary (Cấu Thành)"
    _order = "categ_tech_id, product_id"
    _transient_max_hours = 4

    lot_id = fields.Many2one(
        "stock.lot",
        string="Lot FG",
        index=True,
        ondelete="cascade",
    )
    product_id = fields.Many2one(
        "product.product",
        string="Sản Phẩm",
    )
    product_uom_id = fields.Many2one(
        "uom.uom",
        string="Đơn Vị",
    )
    quantity = fields.Float(
        string="Tổng Số Lượng",
        help="Tổng quantity của tất cả lines cùng product_id, gom đệ quy "
             "mọi cấp sub-FG dưới lot này.",
    )

    # ------------------------------------------------------------------
    # Related / computed display fields
    # ------------------------------------------------------------------
    categ_tech_id = fields.Many2one(
        "product.category.technical",
        related="product_id.product_tmpl_id.technical_categ_id",
        string="Danh Mục Kỹ Thuật",
        store=False,
        readonly=True,
    )
    cost_currency_id = fields.Many2one(
        related="product_id.cost_currency_id",
        readonly=True,
    )
    # `product.product.standard_price` là Float — không phải Monetary —
    # nên expose lại Float ở đây. View dùng `widget="monetary"` +
    # `currency_field='cost_currency_id'` để format đúng tiền tệ.
    standard_price = fields.Float(
        related="product_id.standard_price",
        string="Giá Mua",
        readonly=True,
    )
    list_price = fields.Float(
        related="product_id.product_tmpl_id.list_price",
        string="Giá Kho",
        readonly=True,
    )
    total_standard_price = fields.Monetary(
        compute="_compute_totals",
        currency_field="cost_currency_id",
        string="Tổng Giá Mua",
    )
    total_list_price = fields.Monetary(
        compute="_compute_totals",
        currency_field="cost_currency_id",
        string="Tổng Giá Kho",
    )

    @api.depends("quantity", "standard_price", "list_price")
    def _compute_totals(self):
        for rec in self:
            rec.total_standard_price = rec.quantity * rec.standard_price
            rec.total_list_price = rec.quantity * rec.list_price
