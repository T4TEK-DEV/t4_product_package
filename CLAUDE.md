# t4_product_package

## Overview
Module quản lý lắp ráp định danh / đóng gói trong kho STI. Cho phép xuất linh kiện sang khu vực lắp ráp, tạo phiếu đóng gói, và quản lý BOM.

## Dependencies
- base, stock, product

## Conventions
- Odoo 19: version "1.0", `<list>` not `<tree>`
- Vietnamese labels
- Wizard dùng form riêng, import wizard_line TRƯỚC wizard trong `__init__.py`
