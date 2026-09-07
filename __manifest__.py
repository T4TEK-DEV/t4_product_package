{
    'name': 'T4 Product Package',
    # (2026-07-16): thêm field search_keyword (Tìm tổng hợp) trên
    # t4.product.creation — search mặc định quét số phiếu/mã lot/SP (+ mã
    # YC/người thực hiện nếu t4_sti cài); mirror stock.quant.search_keyword.
    # 1.0.25 (2026-07-23): widget="image"→"binary" ở sign-wizard + field
    # preview image_tracking (bỏ giới hạn ảnh, không vỡ preview PDF/DOC).
    # 1.0.26 (2026-07-24): t4.product.creation.note "Ghi Chú" Text→Html (đồng
    # bộ với stock.picking.note "Diễn giải" = fields.Html) + form field
    # widget="html". Nút "Tạo Phiếu Lắp Ráp" (t4_sti) copy picking.note qua
    # context default_note → trước đây Text hiện raw tag <p>. Cột DB vẫn text →
    # KHÔNG migration. Report dùng t-field="doc.note" tự render Html đúng.
    'version': '1.0.26',
    'summary': 'Quản lý lắp ráp định danh / đóng gói trong kho STI',
    'description': """
        Module quản lý quy trình đóng gói định danh, cho phép xuất linh kiện sang khu vực lắp ráp,
        quét mã định danh và ghép vào một Mã Thành phẩm/Kiện hàng mới.
        Quản lý BOM đơn giản (danh sách linh kiện) và lịch sử lắp ráp.
    """,
    'category': 'Inventory/Warehouse',
    'author': 'T4TEK-DEV',
    'license': 'LGPL-3',
    # KHÔNG depend trực tiếp `t4_sti` — vì `t4_sti` depends ngược về module
    # này (chain: t4_product_package → t4_sti → t4_product_package = circular).
    # Wizard intercept đọc flag `is_required_print_assembly|identify` từ
    # `self.env.context` — `t4_sti.ir_http.session_info` inject flags vào
    # user_context khi user login. Nếu `t4_sti` không cài: ctx.get() trả None
    # → wizard không kích hoạt → graceful degradation.
    # t4_sti_technical_category: BẮT BUỘC — product_creation_summary.categ_tech_id
    # related tới product_tmpl_id.technical_categ_id + M2o 'product.category.technical'
    # (tham chiếu TĨNH; thiếu dep này install partial sẽ fail KeyError khi
    # auto_install kéo module vào graph mà không có technical_category).
    'depends': ['stock', 'sale_stock', 'mail', 't4_sti_brand_manufacturer',
                't4_sti_technical_category'],
    'data': [
        # 1. Security
        'security/ir.model.access.csv',
        # 2. Data (sequences)
        'data/sequence_data.xml',
        'data/ir_cron_cleanup.xml',
        # 3. Reports (load TRƯỚC views vì action_print dùng env.ref report)
        'reports/product_creation_report.xml',
        # 4. Wizard (load TRƯỚC views vì action_confirm trả về action tham chiếu wizard)
        'wizard/product_creation_sign_wizard_views.xml',
        # 5. Views
        'views/product_component_views.xml',
        'views/product_creation_views.xml',
        'views/product_template_views.xml',
        'views/packing_request_views.xml',
        'views/stock_picking_views.xml',
        'views/stock_move_line_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            # Toggle LIVE used↔returned khi quét lại serial (form lắp ráp).
            't4_product_package/static/src/product_creation_toggle.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': True,
}
