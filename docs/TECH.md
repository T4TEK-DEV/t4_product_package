# t4_product_package — Technical Documentation

## Key Models
- Packing request wizard + lines
- BOM-like structure for product packaging

## Migration Notes (v18 → v19)
- `<tree>` → `<list>` in all views and view_mode
- Wizard line split to separate file for proper model registration
- Wizard views loaded BEFORE main views in manifest data order
