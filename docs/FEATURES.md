# t4_product_package — Tài Liệu Tính Năng

> Module `t4_product_package` | Odoo 19 Community | T4TEK-DEV
>
> Quản lý quy trình **Lắp Ráp Thành Phẩm** và **Định Danh Linh Kiện Thành Phẩm** trong kho STI.
> Xem kiến trúc tổng thể tại [`t4_sti/docs/ARCHITECTURE.md`](../../t4_sti/docs/ARCHITECTURE.md),
> master index tại [`t4_sti/docs/INDEX.md`](../../t4_sti/docs/INDEX.md).

---

## 1. Tổng quan & Dependencies

**Depends:** `stock`, `sale_stock`, `mail`, `t4_sti_brand_manufacturer`

**Models chính:**

| Model | Mô tả |
|-------|-------|
| `t4.product.creation` | Phiếu Lắp Ráp / Định Danh LK TP (2 workflow qua field `type`) |
| `t4.product.creation.line` | Dòng linh kiện (sử dụng hoặc trả) |
| `t4.product.component` | BOM linh kiện đơn giản của thành phẩm |
| `packing.request` | Phiếu yêu cầu lắp ráp từ phiếu xuất kho |
| `packing.request.line` | Chi tiết sản phẩm cần lắp ráp |
| `t4.assembly.record` | Biên bản lắp ráp (snapshot giá) |
| `t4.assembly.record.line` | Dòng snapshot linh kiện trong biên bản |

**Extend:**

| Model | Tính năng thêm |
|-------|---------------|
| `product.template` | BOM linh kiện (`component_ids`), thống kê lắp ráp |
| `stock.picking` | Lock phiếu khi đang lắp ráp (`is_locked_by_packing`) |
| `stock.lot` | Truy vết linh kiện đã định danh (`fg_component_line_ids`) |

---

## 2. Model `t4.product.creation` — Phiếu Lắp Ráp / Định Danh LK TP

Model thống nhất cho 2 nghiệp vụ phân biệt qua field `type`:

| `type` | Tên hiển thị | Mô tả |
|--------|-------------|-------|
| `assembly` | Phiếu Lắp Ráp | Tạo thành phẩm mới từ N linh kiện; tạo `stock.lot` mới cho FG |
| `identify` | Phiếu Định Danh LK TP | Gắn lot/serial cho linh kiện của thành phẩm đã có sẵn; tạo `stock.quant` + SVL |

### 2.1 State machine

#### Assembly (`type='assembly'`)

```
draft
  ├─ [In]         → is_have_printed = True
  ├─ [Xác Nhận]   → resolve lot_name → lot_id (tạo mới nếu chưa có)
  │                  → state = done
  └─ [Huỷ]        → state = cancel

cancel
  └─ [Đặt về Nháp] → state = draft

done (kết thúc — không cancel)
```

#### Identify (`type='identify'`)

```
┌─────────────────────────────────────────────────────────────────┐
│                    Phiếu Định Danh LK TP                        │
│                                                                  │
│  Operator                         Purchase / Manager            │
│     │                                    │                      │
│     ├─ Nhập: thành phẩm (lot_name),      │                      │
│     │  linh kiện, Mã QLC, Brd/Mfr S/N   │                      │
│     │  (state = draft)                   │                      │
│     │                                    │                      │
│     ├─ [Hoàn Thành]                      │                      │
│     │   validate: lot_name, lines ≥ 1,   │                      │
│     │   qty > 0, lot_name cho serial     │                      │
│     │   → state = waiting               │                      │
│     │   → toàn bộ trường khoá readonly  │                      │
│     │                                    │                      │
│     │                         ┌──────────┤                      │
│     │                         │ Nhập đơn giá (standard_price)   │
│     │                         │ cho từng dòng linh kiện         │
│     │                         │                                 │
│     │                         ├─ [Xác Nhận]                    │
│     │                         │   validate: giá > 0            │
│     │                         │   → resolve lot_name → lot_id  │
│     │                         │   → _t4_create_component_lots()│
│     │                         │     • tạo stock.lot (serial)   │
│     │                         │     • set standard_price       │
│     │                         │     • tạo stock.quant          │
│     │                         │     • _apply_inventory() → SVL │
│     │                         │   → state = done              │
│     │                         └──────────┘                     │
│     │                                    │                      │
│     ├─ [Huỷ] (draft hoặc waiting)        │                      │
│     │   → state = cancel               │                      │
│     │                                    │                      │
│     ├─ [Đặt về Nháp] (cancel/waiting)    │                      │
│     │   → state = draft                 │                      │
│     │   → xoá audit trail cost_confirm  │                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Trạng thái:**

| State | Label | Mô tả |
|-------|-------|-------|
| `draft` | Nháp | Operator nhập liệu; mọi trường có thể sửa |
| `waiting` | Chờ Nhập Giá | Linh kiện đã khoá; Thu Mua nhập đơn giá |
| `done` | Hoàn Thành | Đã nhập kho; không sửa được |
| `cancel` | Đã Huỷ | Đã huỷ; có thể đặt về Nháp |

### 2.2 Fields header

| Field | Kiểu | Mô tả |
|-------|------|-------|
| `name` | Char | Mã phiếu tự động: `PC/%(year)s/00001` |
| `type` | Selection | `assembly` / `identify` |
| `state` | Selection | `draft` / `waiting` / `done` / `cancel` |
| `product_id` | M2o → product.product | Thành phẩm (domain: `tracking='serial'`) |
| `lot_name` | Char | Mã Quản Lý TP — scan hoặc nhập tay |
| `lot_id` | M2o → stock.lot | Tự resolve từ `lot_name` |
| `brand_part_id` | Char (related) | Brd. S/N của lot thành phẩm |
| `manufacturer_part_id` | Char (related) | Mfr. S/N của lot thành phẩm |
| `packing_request_id` | M2o → packing.request | Link yêu cầu lắp ráp (nếu có) |
| `company_id` | M2o → res.company | Công ty |

**Fields cost audit trail (identify):**

| Field | Kiểu | Mô tả |
|-------|------|-------|
| `t4_cost_confirmed` | Boolean | Đã xác nhận giá (audit trail) |
| `t4_cost_confirm_user_id` | M2o → res.users | Người xác nhận giá |
| `t4_cost_confirm_date` | Datetime | Thời điểm xác nhận giá |

**Fields tổng hợp (computed):**

| Field | Mô tả |
|-------|-------|
| `total_standard_price` | Tổng giá vốn (sum `line_ids.total_standard_price`) |
| `total_list_price` | Tổng giá kho (sum `line_ids.total_list_price`) |
| `purchase_price` | Giá vốn hiện tại của thành phẩm (`product_id.standard_price`) |

### 2.3 Phân quyền nút & trường

#### Nút action

| Nút | Type | State hiển thị | Group yêu cầu |
|-----|------|---------------|---------------|
| In | `action_print` | any | base.group_user |
| **Hoàn Thành** | `action_complete` | draft (identify) | base.group_user |
| **Xác Nhận** | `action_confirm_cost` | waiting (identify) | group_purchase / group_manager |
| Xác Nhận | `action_confirm` | draft (assembly) | base.group_user |
| Huỷ | `action_cancel` | draft, waiting | base.group_user |
| Đặt về Nháp | `action_draft` | cancel, waiting | base.group_user |

#### Trường trong bảng linh kiện (identify)

| Trường | Draft | Waiting | Done |
|--------|-------|---------|------|
| Sản phẩm, Số lượng | ✏️ Operator | 🔒 Locked | 🔒 Locked |
| Mã Quản Lý, Brd/Mfr S/N | ✏️ Operator | 🔒 Locked | 🔒 Locked |
| Đơn Giá Mua | 🔒 Locked | ✏️ Purchase / Manager | 🔒 Locked |
| Add / Delete dòng | ✅ Cho phép | ❌ Khoá | ❌ Khoá |

> `Đơn Giá Mua` và `Thành Tiền` ẩn hoàn toàn với user không thuộc
> `group_purchase` hoặc `group_manager` (thuộc tính `groups=` trên field XML).

### 2.4 Workflow action — mô tả chi tiết

#### `action_complete()` — Operator hoàn thành nhập liệu

- Chỉ `type='identify'`, `state='draft'`
- Validate:
  - Có ≥ 1 dòng linh kiện
  - `lot_name` hoặc `lot_id` header đã có
  - Tất cả dòng: `product_id` đã chọn, `quantity > 0`
  - Linh kiện `tracking='serial'` phải có `lot_name`
- Kết quả: `state = 'waiting'`, post chatter

#### `action_confirm_cost()` — Purchase xác nhận giá và nhập kho

- Chỉ `type='identify'`, `state='waiting'`
- Group: `t4_sti.group_purchase` hoặc `t4_sti.group_manager`
- Validate:
  - `standard_price > 0` cho mọi dòng
  - `lot_name` header hợp lệ (phải tồn tại sẵn trong `stock.lot`)
- Sign-wizard intercept nếu config `is_required_print_identify = True`
- Thực thi `_t4_create_component_lots()`:
  - **Pass 1:** Tạo `stock.lot` cho linh kiện serial/lot + batch write `standard_price`
  - **Pass 2:** Tạo `stock.quant` → `_apply_inventory()` → `stock.move` → SVL + journal entries
- Lưu audit: `t4_cost_confirmed = True`, `t4_cost_confirm_user_id`, `t4_cost_confirm_date`
- Kết quả: `state = 'done'`, post chatter

#### `action_confirm()` — Xác nhận phiếu Lắp Ráp (assembly only)

- Chỉ `type='assembly'`
- Resolve `lot_name` → `lot_id` (tạo mới `stock.lot` nếu FG `tracking='serial'`)
- Sign-wizard intercept nếu config `is_required_print_assembly = True`
- Kết quả: `state = 'done'`

#### `action_draft()` — Đặt về Nháp

- Từ `state='cancel'` hoặc `state='waiting'` (identify)
- Reset: `state = 'draft'`, xoá `t4_cost_confirmed + user + date`
- Không rollback `stock.lot` / `stock.quant` đã tạo (path `done` không có cancel)

### 2.5 Kế toán — `_t4_create_component_lots()`

**Tìm vị trí kho FG:**
Tìm `stock.quant` của `lot_id` header tại `location.usage='internal'` → lấy `fg_location`.

**Pass 1 — Lot + Giá:**
```
for line in line_ids:
    if tracking != 'none':
        Tạo stock.lot(name=lot_name, product_id, brand_part_id, manufacturer_part_id)
    if product.lot_valuated and tracking != 'none':
        lot.standard_price = line.standard_price      # per-lot SVL (SN AVCO)
    else:
        product.standard_price = line.standard_price  # AVCO / Standard / FIFO
```

**Pass 2 — Quant + Inventory Adjustment:**
```
for line in line_ids:
    Tạo stock.quant(product_id, location_id=fg_location, inventory_quantity=qty, lot_id)

quants._apply_inventory()
  → stock.move (location_inventory → fg_location)
  → _action_done()
  → stock_valuation_layer (SVL)
  → account.move (journal entries)
```

> Pattern giống **Inventory Adjustment** chuẩn Odoo — `t4_cost_tracking`
> tự động log `t4.cost.history` qua hook `stock.move._action_done()`.

---

## 3. Model `t4.product.creation.line` — Dòng Linh Kiện

| Field | Kiểu | Mô tả |
|-------|------|-------|
| `creation_id` | M2o → t4.product.creation | Phiếu cha |
| `line_type` | Selection | `used` (sử dụng) / `returned` (trả) |
| `product_id` | M2o → product.product | Linh kiện |
| `lot_name` | Char | Mã serial của linh kiện (scan hoặc nhập) |
| `lot_id` | M2o → stock.lot | Tự resolve từ `lot_name` (assembly) hoặc tạo mới (identify) |
| `quantity` | Float | Số lượng |
| `brand_part_id` | Char | Brd. S/N snapshot |
| `manufacturer_part_id` | Char | Mfr. S/N snapshot |
| `standard_price` | Float | Giá vốn tại thời điểm định danh (snapshot) |
| `list_price` | Float | Giá kho tại thời điểm lắp ráp (snapshot) |
| `total_standard_price` | Monetary (computed) | `quantity × standard_price` |
| `total_list_price` | Monetary (computed) | `quantity × list_price` |

**Related (cho view logic):**

| Field | Nguồn | Dùng để |
|-------|-------|---------|
| `wizard_type` | `creation_id.type` | Phân biệt behavior onchange |
| `parent_state` | `creation_id.state` | Readonly condition trong list |
| `tracking` | `product_id.tracking` | Ẩn/hiện `lot_name` |

**Constraint:**
- `_check_identify_single_used_line`: Phiếu `identify` chỉ được có **1** dòng `line_type='used'`
- `_check_identify_lot_name_unique`: `lot_name` của dòng `used` trong phiếu `identify` phải chưa tồn tại trong `stock.lot` (backup cho onchange warning)

---

## 4. Model `t4.product.component` — BOM Linh Kiện Đơn Giản

Thay thế Odoo MRP BOM cho quy trình nhẹ STI.

| Field | Kiểu | Mô tả |
|-------|------|-------|
| `parent_product_id` | M2o → product.template | Thành phẩm (FG) |
| `product_id` | M2o → product.product | Linh kiện (required) |
| `quantity` | Float | Số lượng linh kiện per 1 FG (default: 1.0) |
| `sequence` | Integer | Thứ tự (default: 10) |
| `note` | Char | Ghi chú |

**Constraints:**
- `_check_qty_positive`: quantity > 0
- `_check_no_self_reference`: linh kiện ≠ thành phẩm

---

## 5. Model `packing.request` — Phiếu Yêu Cầu Lắp Ráp

Luồng từ phiếu xuất kho sang khu vực lắp ráp.

### 5.1 State machine

```
draft
  ├─ [Xác Nhận]          → validate: có dòng ≥ 1
  │                          lock picking (is_locked_by_packing = True)
  │                          → state = open
  └─ [Huỷ]               → state = cancel

open
  ├─ [Hoàn Thành YC]     → unlock picking → state = done
  ├─ [Đặt về Nháp]       → state = draft
  └─ [Huỷ]               → unlock picking → state = cancel

cancel
  └─ [Đặt về Nháp]       → state = draft (unlock picking)

done (kết thúc)
```

### 5.2 Fields

| Field | Kiểu | Mô tả |
|-------|------|-------|
| `name` | Char | Mã: `PKG/%(year)s/00001` |
| `picking_id` | M2o → stock.picking | Phiếu xuất kho nguồn |
| `partner_id` | M2o (related) | Khách hàng từ picking |
| `state` | Selection | draft / open / done / cancel |
| `request_line_ids` | O2m → packing.request.line | Chi tiết SP cần lắp |
| `assembly_record_ids` | O2m → t4.product.creation | Phiếu lắp ráp liên kết |
| `assembly_count` | Integer (computed) | Số phiếu lắp ráp |

### 5.3 Tích hợp `stock.picking`

- `picking.action_create_packing_request()`: Tạo `packing.request` từ `move_ids`
- `picking.is_locked_by_packing`: Lock validate khi có packing request đang open
- Khi confirm packing: `is_locked_by_packing = True`
- Khi done/cancel packing: `is_locked_by_packing = False`

---

## 6. `t4.assembly.record` — Biên Bản Lắp Ráp

Log snapshot giá linh kiện tại thời điểm lắp (audit trail độc lập với biến động giá).

| Field | Kiểu | Mô tả |
|-------|------|-------|
| `name` | Char | Mã: `AR/%(year)s/00001` |
| `product_id` | M2o → product.product | Thành phẩm tạo ra |
| `lot_id` | M2o → stock.lot | Serial FG |
| `packing_request_id` | M2o → packing.request | Link phiếu đóng gói |
| `state` | Selection | draft / done / cancel |
| `line_ids` | O2m → t4.assembly.record.line | Snapshot linh kiện |
| `total_standard_price` | Float (computed) | Tổng giá vốn |
| `total_list_price` | Float (computed) | Tổng giá kho |

---

## 7. Sign Wizard — Upload Ảnh Xác Minh

**Model:** `t4.product.creation.sign.wizard` (TransientModel)

Intercept trước khi xác nhận nếu config bắt buộc in phiếu:

| Config flag | Áp dụng cho |
|-------------|-------------|
| `is_required_print_assembly` | `type='assembly'` tại `action_confirm()` |
| `is_required_print_identify` | `type='identify'` tại `action_confirm_cost()` |

**Luồng intercept:**
1. Method xác nhận kiểm tra `is_have_printed` — nếu chưa in → raise UserError
2. Nếu đã in nhưng chưa có `image_tracking_attachment_id` → mở wizard
3. Wizard: user upload ảnh phiếu đã ký → tạo `ir.attachment`
4. Re-call method phù hợp với `context t4_bypass_sign_wizard=True`:
   - `assembly` → `action_confirm()`
   - `identify` → `action_confirm_cost()`

---

## 8. HID Integration (RFID / Barcode)

Các action `Lắp Ráp` và `Định Danh LK TP` đều có context:

```python
{
    't4_auto_input_enabled': True,
    't4_passive_buttons': [{
        'id': 'rfid_reader',
        'title': 'Quét',
        'icon': 'fa-rss',
        'position': 'status_bar',
        'url': 'ws://localhost:9001',
        'toggle': False,
        'timeout': 2000,
    }],
}
```

**Sequential auto-input trong bảng linh kiện (identify):**

| `data-auto-input-order` | Field |
|------------------------|-------|
| `0` | `lot_name` (header TP) |
| `1` | `lot_name` (dòng linh kiện) |
| `2` | `brand_part_id` |
| `3` | `manufacturer_part_id` |

> Scan tuần tự: quét serial TP → chuyển focus sang serial linh kiện → Brd S/N → Mfr S/N.

---

## 9. Security

### 9.1 Model access rights

| Model | Group | Read | Write | Create | Unlink |
|-------|-------|------|-------|--------|--------|
| `t4.product.creation` | base.group_user | ✓ | ✓ | ✓ | ✗ |
| `t4.product.creation` | base.group_system | ✓ | ✓ | ✓ | ✓ |
| `t4.product.creation.line` | base.group_user | ✓ | ✓ | ✓ | ✗ |
| `t4.product.creation.line` | base.group_system | ✓ | ✓ | ✓ | ✓ |
| `packing.request` | base.group_user | ✓ | ✓ | ✓ | ✗ |
| `packing.request.line` | base.group_user | ✓ | ✓ | ✓ | ✓ |
| `t4.product.component` | base.group_user | ✓ | ✓ | ✓ | ✗ |
| `t4.product.component` | base.group_system | ✓ | ✓ | ✓ | ✓ |

### 9.2 Field-level visibility

| Field / Vùng | Group |
|-------------|-------|
| `standard_price`, `list_price`, `total_standard_price` (dòng) | group_purchase / group_manager |
| `total_standard_price`, `purchase_price` (header) | group_purchase / group_manager |
| Nút **Xác Nhận** (identify, state=waiting) | group_purchase / group_manager |
| `company_id` | base.group_multi_company |

> Groups kế thừa từ `t4_sti`: xem `t4_sti/security/t4_sti_groups.xml`.
> `group_manager` implies `group_purchase` — Manager có đủ quyền xác nhận giá.

---

## 10. Menu Structure

```
T4 STI
├── Thao Tác
│   ├── Kỹ Thuật
│   │   ├── Lắp Ráp              → action_t4_product_creation_assembly_new (form)
│   │   └── Định Danh LK TP      → action_t4_product_creation_identify_new (form)
│   └── ...
└── Quản Lý
    ├── Phiếu Lắp Ráp            → action_t4_product_creation_assembly_history (list)
    ├── Phiếu Định Danh LK TP    → action_t4_product_creation_identify_history (list)
    └── Phiếu Yêu Cầu Lắp Ráp  → action_packing_request (list)
```

> Action **Lắp Ráp** và **Định Danh LK TP** mở thẳng form mới (`view_mode=form`, `create=1`).
> Action **lịch sử** mở list (`create=0`), dùng domain `[('type', '=', ...)]` để lọc.

---

## 11. Sequences

| Mã phiếu | Format | Model |
|----------|--------|-------|
| `PC/2026/00001` | `PC/%(year)s/00001` | `t4.product.creation` |
| `PKG/2026/00001` | `PKG/%(year)s/00001` | `packing.request` |
| `AR/2026/00001` | `AR/%(year)s/00001` | `t4.assembly.record` |

---

## 12. Conventions module này

| Điểm | Giá trị |
|------|---------|
| Version manifest | `"1.0"` (KHÔNG `"19.0.x.x.x"`) |
| application | `False` (sub-module của `t4_sti`) |
| View tag | `<list>` (Odoo 19), KHÔNG `<tree>` |
| Model prefix | `t4.product.*`, `packing.*` |
| `__init__.py` | Import comodel (`line`) TRƯỚC parent model |
| `action_confirm_cost` | Là full confirm cho identify (validate + lots + quants + SVL + done) |

---

## Xem thêm

- [`TECH.md`](./TECH.md) — Migration notes v18 → v19
- [`CLAUDE.md`](../CLAUDE.md) — Agent guide
- [`t4_sti/docs/FEATURES.md`](../../t4_sti/docs/FEATURES.md) — Features t4_sti (module gốc)
- [`t4_sti/docs/INDEX.md`](../../t4_sti/docs/INDEX.md) — Master index
