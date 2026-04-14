# t4_product_package — Agent Guide

## Overview
Module quản lý quy trình lắp ráp thành phẩm (FG) và đóng gói trong kho STI.
Cho phép xuất linh kiện sang khu vực lắp ráp, quét mã barcode, và tạo thành phẩm mới.

## Dependencies
- stock, sale_stock, mail

## Models

### t4.product.component (BOM đơn giản)
Định nghĩa linh kiện cho thành phẩm — thay thế Odoo MRP BOM cho quy trình nhẹ.
- `parent_product_id` → product.template (thành phẩm)
- `product_id` → product.product (linh kiện)
- `quantity` (Float) — số lượng linh kiện per 1 FG
- Constraint: linh kiện không được trùng thành phẩm
- Thành phẩm có thể thay đổi linh kiện liên tục (không lock)

### t4.assembly.record (Phiếu Lắp Ráp)
Ghi nhận mỗi lần lắp ráp — thay thế `stock.card.line` v18.
- `product_id` → product.product (thành phẩm tạo ra)
- `lot_id` → stock.lot (serial/lot của FG)
- `packing_request_id` → packing.request (link phiếu đóng gói)
- `line_ids` → t4.assembly.record.line (snapshot linh kiện)
- `total_standard_price`, `total_list_price` (computed tổng giá)
- States: draft → done / cancel
- Sequence: AR/%(year)s/00001

### t4.assembly.record.line (Snapshot Linh Kiện)
Ghi nhận chính xác linh kiện nào đã dùng, giá tại thời điểm lắp ráp.
- `product_id`, `lot_id` — linh kiện + serial
- `quantity` — số lượng sử dụng
- `standard_price`, `list_price` — snapshot giá tại thời điểm lắp ráp
- `total_standard_price`, `total_list_price` — computed (qty * price)

### packing.request (Phiếu Đóng Gói)
Quy trình lắp ráp từ stock.picking.
- States: draft → open → done / cancel
- `request_line_ids` → packing.request.line (linh kiện cần đóng gói)
- `assembly_record_ids` → t4.assembly.record (link phiếu lắp ráp)
- Lock picking khi đang xử lý (is_locked_by_packing)

### packing.slip.wizard (Wizard Quét Barcode)
Wizard quét mã lắp ráp thành phẩm.
- `fg_product_id` — chọn sản phẩm thành phẩm đích
- `barcode_input` — quét barcode/serial
- `line_ids` — linh kiện đã quét (với price snapshot)
- **Scan logic**: tìm lot → barcode → default_code
- **Finish**: tạo t4.assembly.record + stock.lot cho FG, update qty_packed

### product.template (extend)
- `is_combo` (Boolean) — đánh dấu thành phẩm
- `component_ids` (One2many) — BOM linh kiện
- `component_count`, `assembly_count` — computed statistics
- Smart buttons: Linh Kiện, Lắp Ráp

### stock.picking (extend)
- `is_locked_by_packing` — lock khi đang đóng gói
- `packing_request_ids` — link phiếu đóng gói
- `action_create_packing_request()` — tạo phiếu từ picking

## Workflow

```
stock.picking (Xuất kho linh kiện)
  └─ "Mang Lắp Ráp Thành Phẩm" → packing.request (draft)
       └─ "Xác nhận" → open (lock picking)
            └─ "Tạo Thành Phẩm (Mã Vạch)" → packing.slip.wizard
                 ├─ Chọn FG product
                 ├─ Quét barcode linh kiện (lặp)
                 └─ "Hoàn thành" → t4.assembly.record (done)
                      ├─ Tạo stock.lot cho FG
                      └─ Snapshot giá linh kiện
       └─ "Hoàn thành yêu cầu" → done (unlock picking)
```

## Migration from v18

| v18 Custom | v19 | Ghi chú |
|---|---|---|
| `stock.card.line` | `t4.assembly.record` + `stock.lot` | Dùng product.product thay vì model custom |
| `stock.card.line.component` | `t4.assembly.record.line` | Snapshot giá tại lắp ráp |
| `product.template.fg.container` | Computed từ assembly records | Không cần model riêng |
| `product.creation.wizard` | `packing.slip.wizard` | Tái sử dụng wizard có sẵn |
| Implicit BOM (qua wizard) | `t4.product.component` | Explicit BOM trên product |

## Conventions
- Odoo 19: version "1.0", `<list>` not `<tree>`
- Vietnamese labels
- application: False (sub-module)
- Import order: comodel TRƯỚC parent model trong `__init__.py`
