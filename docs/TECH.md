# t4_product_package — Technical Notes

> Tài liệu tính năng đầy đủ: [FEATURES.md](./FEATURES.md)

## Migration Notes (v18 → v19)

- `<tree>` → `<list>` trong tất cả view và `view_mode`
- `wizard_line` tách ra file riêng để đăng ký model trước parent (Odoo 19 strict validation)
- Wizard views load TRƯỚC main views trong `__manifest__.py data`
- `move_ids_without_package` → `move_ids` (field bị xoá trong Odoo 19)
- `stock.move.name` → `stock.move.reference` (field bị đổi tên)
- `category_id` → `privilege_id` trên `res.groups` (Odoo 19 breaking change)
