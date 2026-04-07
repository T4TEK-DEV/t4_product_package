{
    'name': 'T4 Packing System',
    'version': '18.0.1.0.0',
    'summary': 'Quản lý lắp ráp định danh / đóng gói trong kho STI',
    'description': """
        Module quản lý quy trình đóng gói định danh, cho phép xuất linh kiện sang khu vực lắp ráp, 
        quét mã định danh và ghép vào một Mã Thành phẩm/Kiện hàng mới.
    """,
    'category': 'Inventory/Packing',
    'author': 'STI Team',
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
