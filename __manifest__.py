{
    'name': 'T4 Product Package',
    'version': '1.0',
    'summary': 'Quản lý lắp ráp định danh / đóng gói trong kho STI',
    'description': """
        Module quản lý quy trình đóng gói định danh, cho phép xuất linh kiện sang khu vực lắp ráp,
        quét mã định danh và ghép vào một Mã Thành phẩm/Kiện hàng mới.
    """,
    'category': 'Inventory/Warehouse',
    'author': 'T4TEK-DEV',
    'depends': ['stock', 'sale_stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/packing_request_views.xml',
        'views/stock_picking_views.xml',
        'wizard/packing_slip_wizard_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
