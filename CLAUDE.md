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
- `component_ids` (One2many) — BOM linh kiện (mở cho mọi sản phẩm serial)
- `component_count`, `assembly_count` — computed statistics
- Smart buttons Linh Kiện / Lắp Ráp — ẩn khi `tracking != 'serial'`
- **Không có flag đánh dấu Thành Phẩm**: mọi sản phẩm `tracking='serial'`
  đều có thể:
    • đóng vai trò Thành Phẩm (khai BOM, chạy assembly wizard), HOẶC
    • là linh kiện của Thành Phẩm khác.
  Linh kiện có thể là sản phẩm bất kỳ tracking nào (serial / lot / none),
  chỉ Thành Phẩm mới bắt buộc `tracking='serial'` để tạo lot FG.

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

## Pattern: Quantity Consistency — "Paper-truth Single Source"

**Nguyên tắc cốt lõi**: Hệ thống quản lý "linh kiện đang nằm trong thành phẩm
nào" qua **một nguồn duy nhất** — `stock.lot.fg_component_line_ids` (chỉ tính
phiếu `state='done'`). Mọi check số lượng — bất kể là phiếu lắp ráp hay phiếu
kho (xuất / điều chuyển / nhập / scrap / inventory adjustment) — đều quy chiếu
cùng nguồn này. **Không phân biệt loại phiếu**: cùng invariant, nhiều enforcement
points, all consistent.

### Helper trung tâm — `stock.lot._t4_get_committed_components()`
Trả về dict `{(product_id, lot_id_or_0): net_qty}` — net = sum(used) − sum(returned)
qua các phiếu `t4.product.creation` done của FG này. Loại key có qty ≤ 0.

```python
# Search trực tiếp lines (KHÔNG dùng rec.line_ids vì có domain filter
# state='used' → bỏ sót returned)
all_lines = Line.search([
    ('creation_id.lot_id', '=', self.id),
    ('creation_id.type', 'in', ['assembly', 'identify']),
    ('creation_id.state', '=', 'done'),
])
```

### Pool free formula (universal)
```
free(product, location)
  = physical_qty
  − Σ committed_lock của các FG có quant > 0 ở location này
  − Σ soft_lock của các phiếu `t4.product.creation` draft/waiting khác
```
- `committed_lock`: dòng `used` của done phiếu, net với dòng `returned` của
  done phiếu sau (qua `_t4_get_committed_components`).
- `soft_lock`: chỉ filter `state='used'` — dòng `state='returned'` tự động
  leave pool ngay khi flip (paper-truth).

### Enforcement points (xuyên suốt — không phân biệt picking type)

| Tầng | Method | File | Bảo vệ |
|---|---|---|---|
| Phiếu lắp ráp confirm | `_t4_sti_check_qty_component_availability` | `t4_sti/.../product_creation_inherit.py` | Free pool tracking='none'/'lot' |
| Phiếu lắp ráp confirm | `_t4_check_returned_consistency` | `product_creation.py` | qty trả ≤ committed + new used (per phiếu) |
| Phiếu kho validate | `_t4_check_fg_lot_top_level` | `t4_sti/.../stock_picking.py` | Lot-tracked component không được move độc lập |
| Phiếu kho validate | `_t4_check_qty_components_committed` | `t4_sti/.../stock_picking.py` | Tracking='none' qty không vượt free tại src internal |
| Phiếu kho done | `_t4_expand_fg_component_lots` | `t4_sti/.../stock_picking.py` | BFS đệ quy: move FG → linh kiện con tự đi theo |
| Constraint backstop | `_check_lot_not_committed_to_other_fg` | `product_creation_line.py` | Lot không thuộc 2 FG done cùng lúc |
| Constraint backstop | `_check_lot_name_not_in_active_phieu` | `product_creation_line.py` | Lot không bị giành giữa 2 phiếu draft |

### Quy tắc loại phiếu
- **Outgoing** (xuất kho): src internal → 2 check fire ✓
- **Internal** (điều chuyển): src internal → 2 check fire ✓
- **Internal scrap**: src internal → 2 check fire ✓
- **Incoming** (nhập kho): src='supplier' (không internal) → check skip ✓
  (đúng nghiệp vụ: incoming chỉ tăng physical, không động committed)
- **FG move (mọi loại)**: `_t4_expand_fg_component_lots` BFS đệ quy auto-thêm
  move_line linh kiện con — không có ghost component sau khi FG xuất kho.

### Đệ quy (FG-A chứa FG-C, FG-C chứa SP-X)
- `_t4_get_committed_components` query theo `lot_id` của 1 FG → mỗi cấp có dict
  riêng. Lock formula gom mọi FG còn quant > 0 ở location → đệ quy free.
- `_t4_expand_fg_component_lots` BFS queue lot-tracked components → đệ quy mọi
  cấp lồng ghép.

### Rule cho dòng `returned` trên phiếu draft
- Tab Trả của phiếu draft **không vào committed_lock và không vào soft_lock**.
  Chỉ khi phiếu `done` thì `_t4_get_committed_components` trừ ra (paper-truth).
- Operator flip dòng từ used → returned ngay lập tức release khỏi soft_lock
  của phiếu khác (vì soft_lock filter `state='used'`).
- Validation `_t4_check_returned_consistency` chạy ở `action_confirm`, **không
  phải `@api.constrains`** — tránh fire sai timing khi user flip dòng draft.

### KHÔNG tạo lot FG trong action_confirm
Workflow: lắp ráp = lấy hàng có sẵn ở Lắp ráp. FG phải đã được nhập kho trước
(_check_lot_location enforce). `action_confirm` chỉ resolve `lot_name` →
`lot_id`; không tìm thấy → raise UserError. Không có nhánh tạo lot mới.

### Tests reference
`t4_sti/tests/test_assembly_locking.py` — 11 tests cover các invariant trên,
kể cả picking block ở location bất kỳ (không lock vào "Lắp ráp").
