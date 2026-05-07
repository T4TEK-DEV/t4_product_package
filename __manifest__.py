{
    'name': 'T4 Product Package',
    'version': '1.0',
    'summary': 'Quản lý lắp ráp định danh / đóng gói trong kho STI',
    'description': """
        Module quản lý quy trình đóng gói định danh, cho phép xuất linh kiện sang khu vực lắp ráp,
        quét mã định danh và ghép vào một Mã Thành phẩm/Kiện hàng mới.
        Quản lý BOM đơn giản (danh sách linh kiện) và lịch sử lắp ráp.
    """,
    'category': 'Inventory/Warehouse',
    'author': 'T4TEK-DEV',
    'license': 'LGPL-3',
    'depends': ['stock', 'sale_stock', 'mail', 't4_sti_brand_manufacturer'],
    'data': [
        # 1. Security
        'security/ir.model.access.csv',
        # 2. Data (sequences)
        'data/sequence_data.xml',
        # 3. Reports (load TRƯỚC views vì action_print dùng env.ref report)
        'reports/product_creation_report.xml',
        # 4. Views
        'views/product_component_views.xml',
        'views/product_creation_views.xml',
        'views/product_template_views.xml',
        'views/packing_request_views.xml',
        'views/stock_picking_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': True,
}
