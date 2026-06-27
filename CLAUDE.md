# t4_product_package — Agent Guide (v1.0.18)

## Overview

Module quản lý quy trình lắp ráp / đóng gói định danh trong kho STI.
Nghiệp vụ cốt lõi: xuất linh kiện ra khu vực lắp ráp → quét mã barcode → ghép
linh kiện vào một Thành Phẩm (FG) mới hoặc định danh linh kiện cho FG có sẵn.

Có **hai loại phiếu** phân biệt qua field `type` trên `t4.product.creation`:
- `type='assembly'` — Lắp ráp FG mới: FG đã nhập kho Lắp ráp trước, operator quét
  linh kiện vào phiếu, xác nhận → ghi nhận snapshot giá.
- `type='identify'` — Định danh linh kiện TP: linh kiện chưa có serial trong hệ
  thống, operator nhập thông tin → Thu Mua nhập giá → xác nhận giá → tạo
  `stock.lot` + `stock.quant` qua `_apply_inventory()`.

Cả 2 type dùng **chung** model `t4.product.creation`, chung view, ẩn/hiện section
theo `type`.

---

## Dependencies & Circular Avoidance Pattern

```python
'depends': ['stock', 'sale_stock', 'mail', 't4_sti_brand_manufacturer'],
'auto_install': True,
```

**KHÔNG depend `t4_sti`** — `t4_sti` phụ thuộc ngược lại module này (chain sẽ
circular). Thay vào đó:
- `action_confirm` / `action_confirm_cost` đọc flags từ
  `self.env.context` thay vì query:
  - `is_required_print_assembly` → enforce in + ảnh trước khi xác nhận phiếu Assembly.
  - `is_required_print_identify` → enforce in + ảnh trước khi xác nhận giá phiếu
    Định Danh.
- `t4_sti.ir_http` inject flags vào `user_context` khi user login.
- Nếu `t4_sti` không cài: `ctx.get()` trả `None` → wizard không kích hoạt →
  **graceful degradation** tự động.

**Auto-install**: module tự cài khi đủ 3 module: `stock`, `sale_stock`,
`t4_sti_brand_manufacturer`.

---

## Data Load Order (`__manifest__.py`)

```
security/ir.model.access.csv
data/sequence_data.xml          # sequences
data/ir_cron_cleanup.xml        # cron dọn nháp rỗng
reports/product_creation_report.xml   # load trước views (action_print dùng env.ref)
wizard/product_creation_sign_wizard_views.xml  # load trước views (action_confirm mở wizard)
views/product_component_views.xml
views/product_creation_views.xml
views/product_template_views.xml
views/packing_request_views.xml
views/stock_picking_views.xml
views/stock_move_line_views.xml
```

---

## Models

### `t4.product.creation` — Phiếu Lắp Ráp / Định Danh

File: `models/product_creation.py`

**Fields chính:**
- `name` (Char, readonly) — mã phiếu, sequence code `t4.product.creation`, prefix `PC/%(year)s/`
- `type` (Selection) — `'assembly'` | `'identify'`, required, index
- `state` (Selection) — `'draft'` → `'waiting'` (chỉ identify) → `'done'` | `'cancel'`
- `product_id` → `product.product`, domain `tracking='serial'`
- `lot_id` → `stock.lot` của FG (resolve từ `lot_name` khi confirm)
- `lot_name` (Char) — tên lot quét/nhập; onchange tự tìm `lot_id`
- `brand_part_id`, `manufacturer_part_id` — related từ `lot_id` (Brd/Mfr S/N)
- `line_ids` — One2many `t4.product.creation.line`, domain `state='used'`
- `line_returned_ids` — One2many `t4.product.creation.line`, domain `state='returned'`
- `packing_request_id` → `packing.request` (link để sync `qty_packed`)
- `image_tracking_attachment_id` → `ir.attachment` (ảnh xác minh — Many2one explicit, không dùng `res_field` magic)
- `image_tracking` (Binary, compute/inverse qua attachment)
- `is_have_printed` (Boolean) — đánh dấu đã in
- `t4_cost_confirmed`, `t4_cost_confirm_user_id`, `t4_cost_confirm_date` — audit trail xác nhận giá (chỉ identify)
- `total_standard_price`, `total_list_price` (Monetary, stored computed)
- `purchase_price` (Monetary, compute, không store) — Giá Mua của **thành phẩm
  (FG header)**. SN-AVCO (`product.lot_valuated`) → `lot_id.standard_price`
  (giá vốn serial cụ thể); còn lại → `product_id.standard_price` (trung bình).
  Mirror logic line `_t4_snapshot_standard_price` (v1.0.17 — trước đây luôn lấy
  `product_id.standard_price` → sai giá khi FG là SN-AVCO).

**Workflow actions:**

| Action | Điều kiện | Kết quả |
|---|---|---|
| `action_complete()` | type=identify, state=draft | state → waiting; lock nhập liệu |
| `action_confirm()` | type=assembly, state=draft | resolve lot_name → lot_id; state → done |
| `action_confirm_cost()` | type=identify, state=waiting | tạo lot/quant/SVL; state → done |
| `action_cancel()` | state in draft/waiting | state → cancel |
| `action_draft()` | state in cancel/waiting | state → draft (reset cost audit) |
| `action_print()` | bất kỳ | in báo cáo; set is_have_printed=True |
| `_cron_cleanup_empty_drafts()` | cron hàng ngày | xoá phiếu nháp rỗng > 24 giờ |

**Sign-wizard intercept** (cả `action_confirm` lẫn `action_confirm_cost`):
1. Kiểm tra context flag (`is_required_print_assembly` / `is_required_print_identify`).
2. Enforce `is_have_printed=True`.
3. Nếu chưa có `image_tracking_attachment_id` → trả về action mở
   `t4.product.creation.sign.wizard` (popup).
4. Wizard upload ảnh xong re-call method với `t4_bypass_sign_wizard=True`.

**Constraints:**
- `_check_lot_location`: identify — lot không ở location `is_usage_restricted`; assembly
  — lot phải có quant > 0 tại location tên "Lắp ráp" (internal).
- `_t4_check_returned_consistency()`: chạy trong `action_confirm` (KHÔNG phải
  `@api.constrains`) — returned ≤ committed + used trong cùng phiếu per (product, lot).

**Lưu ý assembly — KHÔNG tạo lot FG:**
`action_confirm` chỉ resolve `lot_name` → `lot_id` bằng cách tìm lot đã tồn tại.
FG phải được nhập kho Lắp ráp trước (constraint enforce). Không có nhánh tạo lot mới.

**Auto-return khi re-assembly (A2 — `_t4_auto_return_dropped_components`):**
Mô hình "phiếu lắp ráp mới nhất CÓ dòng used = danh sách linh kiện hiện tại của
FG". Khi `action_confirm` (assembly có ≥1 dòng used), tự tạo dòng "Linh Kiện Trả"
để TRIỆT TIÊU toàn bộ đóng góp của các phiếu done TRƯỚC (`_t4_get_committed_components`),
phần linh kiện GIỮ LẠI được dòng used phiếu này cộng lại → **sau confirm, cấu thành
FG == danh sách Sử Dụng của phiếu này**. Cả 2 cách gỡ (xóa dòng used / thêm dòng
Trả tay) hội tụ về net model — KHÔNG sửa logic cấu thành.
- Trả **full baseline cho MỌI key** vì `_t4_get_committed_components` CỘNG DỒN
  used qua các phiếu (KHÔNG dedupe; dedupe chỉ ở field hiển thị
  `fg_component_line_ids`). Vd serial S2 giữ lại: net = used_cũ(1)+used_mới(1)−trả(1)=1.
- CHỈ chạy khi phiếu có `line_ids` (re-assembly). Phiếu CHỈ-trả (line_ids rỗng) là
  điều chỉnh incremental → bỏ qua (không coi là "redefine = rỗng").
- KHÔNG di chuyển tồn kho (assembly confirm không tạo move) — linh kiện free tại
  'Lắp ráp' (B3); `is_scrap=False`. Free chỉ sau khi confirm thành công (compute
  chỉ tính phiếu done). Idempotent (trừ phần đã trả sẵn). Tests:
  `t4_sti/tests/test_assembly_locking.py::test_reassembly_*`.

**Identify — `_t4_create_component_lots()`:**
- Pass 1: tạo `stock.lot` cho linh kiện tracked; gom cost-bucket; batch-write
  `standard_price` trước khi tạo quant (chỉ cho `cost_method='standard'` —
  tránh blast AVCO/FIFO history).
- Pass 2: tạo `stock.quant` với `inventory_quantity = current_qty + line.quantity`
  (TARGET absolute, không phải delta); `_apply_inventory()` tạo SVL + journal entries.
- Inject `t4_creation_id` qua context → `stock.quant._get_inventory_move_values`
  gắn FK lên `stock.move` → navigate từ move.line về phiếu gốc.

---

### `t4.product.creation.line` — Dòng Linh Kiện

File: `models/product_creation_line.py`

- `creation_id` → `t4.product.creation`, ondelete=cascade, index
- `state` (Selection) — `'used'` | `'returned'`, index
- `product_id` → `product.product`, required
- `lot_id` → `stock.lot`, domain theo product_id
- `lot_name` (Char) — onchange: assembly tìm lot có sẵn + fill Brd/Mfr; identify
  check lot chưa tồn tại (warning nếu đã có)
- `quantity` (Float, default 1.0)
- `standard_price` (Float, **snapshot thường** — KHÔNG compute) — prefill từ
  lot/product qua `_onchange_prefill_standard_price` + `create()`; identify chỉ
  prefill khi trống để GIỮ giá Thu Mua nhập tay. Trước v1.0.9 là computed-stored
  → bị recompute về 0 khi `action_confirm_cost` set lot_id/product price (bug
  "nhập giá → xác nhận xong quay về 0"). Helper: `_t4_snapshot_standard_price()`
- `list_price` (Float, related stored từ `product.lst_price`)
- `total_standard_price`, `total_list_price` (Monetary, computed stored)
- `brand_part_id`, `manufacturer_part_id` (Char snapshot)
- `is_scrap` (Boolean) — line returned: đánh dấu hư hỏng → kho phế phẩm
- `note` (Char)

**Constraints (backstop):**
- `_check_identify_lot_name_unique`: phiếu identify — lot_name chưa tồn tại hệ
  thống và không trùng trong phiếu (backup cho onchange, guard RPC/import).
- `_check_lot_name_not_in_active_phieu`: lot_name không bị giữ bởi phiếu draft/waiting
  khác (soft-lock chống race condition giữa 2 phiếu cùng lúc).
- `_check_lot_not_committed_to_other_fg`: assembly — lot đang committed cho FG
  done khác còn ở kho Lắp ráp → phải trả từ FG cũ trước.

---

### `t4.product.component` — BOM Linh Kiện (Định Mức)

File: `models/product_component.py`

BOM đơn giản, thay thế Odoo MRP BOM.

- `parent_product_id` → `product.template`, ondelete=cascade, index
- `product_id` → `product.product`, ondelete=restrict
- `quantity` (Float, default 1.0) — số lượng per 1 FG
- `note` (Char)
- Constraint: quantity > 0; linh kiện ≠ thành phẩm (self-reference).
- Thành phẩm **có thể thay đổi linh kiện bất kỳ lúc nào** — BOM không lock.

---

### `packing.request` — Phiếu Yêu Cầu Đóng Gói

File: `models/packing_request.py`

- `name` (Char, readonly) — sequence code `packing.request`, prefix `PKG/%(year)s/`
- `picking_id` → `stock.picking`
- `state` (Selection) — `'draft'` → `'open'` → `'done'` | `'cancel'`
- `request_line_ids` → `packing.request.line`
- `assembly_record_ids` → `t4.product.creation` (domain type=assembly) — **CHÚ Ý:**
  field này link sang `t4.product.creation`, KHÔNG phải `t4.assembly.record`
- `assembly_count` (computed)
- `action_confirm()`: set `picking_id.is_locked_by_packing=True`; state → open
- `action_done()`: set `is_locked_by_packing=False`; state → done
- `action_cancel()`: giải lock picking; state → cancel

### `packing.request.line`

File: `models/packing_request_line.py`

- `request_id` → `packing.request`, cascade
- `product_id` → `product.product`
- `product_uom_qty` (Float)
- `qty_packed` (Float) — cập nhật bởi `_sync_packing_request_qty_packed()` khi phiếu assembly done

---

### `t4.assembly.record` — Phiếu Lắp Ráp (Legacy / Đóng Gói Nhanh)

File: `models/assembly_record.py`

Model **riêng biệt** — sử dụng bởi `packing.slip.wizard` trong luồng đóng gói
nhanh từ `packing.request`. **Không phải** `t4.product.creation`.

- `name` — sequence code `t4.assembly.record`, prefix `AR/%(year)s/`
- `product_id` → `product.product`
- `lot_id` → `stock.lot`
- `packing_request_id` → `packing.request`
- `line_ids` → `t4.assembly.record.line`
- `state` — `'draft'` → `'done'` | `'cancel'`
- `total_standard_price`, `total_list_price` (computed)
- Actions: `action_done()`, `action_cancel()`

### `t4.assembly.record.line`

File: `models/assembly_record_line.py`

- `record_id` → `t4.assembly.record`, cascade
- `product_id`, `lot_id`, `quantity`, `standard_price`, `list_price`
- `total_standard_price`, `total_list_price` (computed)

---

### `stock.lot` (extend)

File: `models/stock_lot.py`

**`fg_component_line_ids`** (Many2many `t4.product.creation.line`, computed):
- Liệt kê dòng `used` hiện còn gắn trong FG — đã net used − returned qua mọi
  phiếu `t4.product.creation` done của FG lot này.
- **Single Source of Truth** cho UI/báo cáo "Linh Kiện Đã Lắp".
- Dedupe: cùng lot_id chỉ giữ line ở phiếu mới nhất.
- Batch pattern: 1 search cho toàn recordset (tránh N queries).

**`fg_all_component_line_ids`** (Many2many, computed):
- Đệ quy BFS xuống mọi cấp sub-FG — UI only, KHÔNG dùng cho business logic.
- Mỗi line giữ `creation_id` của phiếu cấp đó → group theo creation = tách
  thành nhóm theo từng cấp.

**`_t4_get_committed_components()`**:
- Trả `dict {(product_id, lot_id_or_0): net_qty}` — net used − returned qua mọi
  phiếu done của FG này.
- Chỉ trả key có `net_qty > 0`.
- Search trực tiếp `t4.product.creation.line` (KHÔNG dùng `rec.line_ids` vì
  domain filter bỏ sót `state='returned'`).

**`_t4_net_used_vs_returned(creation_records)`**:
- Helper nội bộ cho cả `_compute_fg_component_line_ids` lẫn BFS.
- Pass 1: cancel used theo returned (cũ trước) per (product, lot).
- Pass 2: dedupe theo (product, lot_id) — giữ line mới nhất khi lot_id > 0.

Caller sau khi confirm/cancel phiếu phải gọi:
```python
lot.invalidate_recordset(['fg_component_line_ids', 'fg_all_component_line_ids'])
```

**`_t4_descendant_lot_ids()`** (v1.0.18): BFS xuống mọi cấp sub-FG (cycle guard)
→ set id lot linh kiện đang gắn trong FG này. Dựa `fg_component_line_ids`.

**`t4_partition_scanned(lot_names)`** (`@api.model`, v1.0.18; **không có `_`** vì
gọi qua RPC): bộ lọc quét
"giữ thành phẩm — bỏ linh kiện con". Trả `{keep, dropped, fg_products}`. Một mã
bị bỏ ⟺ lot của nó là linh kiện (đệ quy) của một lot KHÁC **cùng batch** quét;
mã quét lẻ (cha không trong batch) được giữ. Dùng bởi bộ lọc quét RFID/batch ở
`t4_sti` (picking move.line — `form_passive_handler` qua cờ
`filter_fg_components_via_rpc`; form Lắp/Định danh — `rfid_scan_handler`). Quét
server đọc trúng cả linh kiện bên trong → chỉ ghi nhận server, không báo lỗi
(BFS `_t4_expand_fg_component_lots` tự kéo linh kiện theo khi chuyển/định danh).

---

### `product.template` (extend)

File: `models/product_template_inherit.py`

- `component_ids` → One2many `t4.product.component`
- `component_count` (computed)
- `assembly_record_ids` → One2many `t4.product.creation` (domain type=assembly)
- `assembly_count` (computed, chỉ đếm done)
- `find_fg_by_component` (Char, search-only) — tìm template là TP chứa LK theo tên/barcode
- `action_view_components()`, `action_view_assembly_records()`

**Không có flag "Thành Phẩm"**: bất kỳ sản phẩm `tracking='serial'` nào cũng
có thể làm FG (khai BOM + lắp ráp) hoặc là linh kiện của FG khác. Linh kiện
chấp nhận mọi tracking (serial / lot / none).

---

### `stock.picking` (extend)

File: `models/stock_picking_inherit.py`

- `is_locked_by_packing` (Boolean) — lock khi `packing.request` đang open
- `packing_request_ids` → One2many `packing.request`
- `action_create_packing_request()` — tạo phiếu đóng gói từ move_ids của picking
  (chỉ khi state in confirmed/assigned)

---

### `stock.move` / `stock.move.line` (extend)

Files: `models/stock_move.py`, `models/stock_move_line.py`

- `stock.move.t4_creation_id` → `t4.product.creation` (ondelete=set null, index)
- `stock.move.line.t4_creation_id` — related stored từ `move_id.t4_creation_id`

Inject qua: `_t4_create_component_lots` set context `t4_creation_id` trước
`_apply_inventory()` → `stock.quant._get_inventory_move_values` (override trong
`models/stock_quant.py`) đọc context và gắn FK lên move.

---

### `t4.error.helper` (AbstractModel)

File: `models/t4_error_helper.py`

Dùng `RedirectWarning` (thay `ValidationError`) để dialog thêm nút "Mở bản ghi
bị trùng". Pattern dùng khi phát hiện duplicate serial (brand_part_id,
manufacturer_part_id). Đặt ở module này vì cả `t4_product_package` lẫn `t4_sti`
đều access được.

---

## Workflow Chính

### Luồng Đóng Gói (packing.request → packing.slip.wizard → t4.assembly.record)

```
stock.picking (confirmed/assigned)
  → action_create_packing_request()
  → packing.request (draft)
       → action_confirm() → open (lock picking)
            → packing.slip.wizard
                 ├─ Chọn fg_product_id (tracking=serial)
                 ├─ Quét barcode → action_scan_barcode()
                 │    Tìm: lot.name → product.barcode → product.default_code
                 └─ action_finish_pack()
                      ├─ Tạo stock.lot cho FG (nếu tracking=serial)
                      ├─ Tạo t4.assembly.record (state=done) + lines snapshot giá
                      └─ Cập nhật packing.request.line.qty_packed
       → action_done() → unlock picking
```

### Luồng Lắp Ráp Định Danh (t4.product.creation type=assembly)

```
t4.product.creation (type=assembly, draft)
  ├─ Nhập lot_name (FG đã có ở kho Lắp ráp) → onchange bind lot_id
  ├─ Thêm line_ids (linh kiện used) + line_returned_ids (nếu có trả)
  └─ action_confirm()
       ├─ [Context check] is_required_print_assembly → enforce in + sign wizard
       ├─ Resolve lot_name → lot_id (raise UserError nếu không tìm thấy)
       ├─ _t4_check_returned_consistency()
       ├─ _sync_packing_request_qty_packed() (nếu có packing_request_id)
       └─ state = done; invalidate lot fg_component_line_ids
```

### Luồng Định Danh Linh Kiện (t4.product.creation type=identify)

```
t4.product.creation (type=identify, draft)
  ├─ Nhập lot_name FG (lot đã tồn tại) → bind lot_id
  ├─ Thêm line_ids (linh kiện chưa có serial — nhập lot_name mới)
  └─ action_complete() → state = waiting
       → Thu Mua nhập standard_price cho từng dòng
       └─ action_confirm_cost()
            ├─ [Context check] is_required_print_identify → enforce in + sign wizard
            ├─ _t4_create_component_lots()
            │    ├─ Pass 1: tạo stock.lot + batch-write standard_price
            │    └─ Pass 2: tạo quant (target = current + qty) → _apply_inventory()
            └─ state = done; invalidate lot fg_component_line_ids
```

---

## Wizards

### `t4.product.creation.sign.wizard`

File: `wizard/product_creation_sign_wizard.py`

- `creation_id` → `t4.product.creation`
- `attachment_data` (Binary, required) — ảnh phiếu đã ký
- `action_upload_and_confirm()`:
  1. Tạo `ir.attachment`; gắn vào `creation_id.image_tracking_attachment_id`.
  2. Re-call đúng method theo `creation.type`:
     - `assembly` → `creation.action_confirm(t4_bypass_sign_wizard=True)`
     - `identify` → `creation.action_confirm_cost(t4_bypass_sign_wizard=True)`

### `packing.slip.wizard` + `packing.slip.wizard.line`

Files: `wizard/packing_slip_wizard.py`, `wizard/packing_slip_wizard_line.py`

- `request_id` → `packing.request`
- `fg_product_id` → `product.product` (tracking=serial)
- `barcode_input` (Char) — quét liên tục
- `line_ids` → `packing.slip.wizard.line`
- `action_scan_barcode()`: tìm theo lot.name → product.barcode → product.default_code
- `action_finish_pack()`: tạo `t4.assembly.record` + lot FG + update qty_packed

---

## Reports

File: `reports/product_creation_report.xml`

Hai action report riêng theo type:
- `action_report_t4_product_creation_assembly` — in phiếu Lắp Ráp
- `action_report_t4_product_creation_identify` — in phiếu Định Danh

`action_print()` chọn đúng report_xml_id theo `self.type`.

---

## Sequences & Cron

**Sequences** (`data/sequence_data.xml`, noupdate=1):

| Code | Prefix | Padding |
|---|---|---|
| `t4.product.creation` | `PC/%(year)s/` | 5 |
| `packing.request` | `PKG/%(year)s/` | 5 |
| `t4.assembly.record` | (dùng `ir.sequence.next_by_code('t4.assembly.record')`, prefix khai trong code) | — |

**Cron** (`data/ir_cron_cleanup.xml`, noupdate=1):
- `ir_cron_t4_cleanup_empty_product_creation` — hàng ngày, gọi
  `t4.product.creation._cron_cleanup_empty_drafts()` — xoá phiếu nháp rỗng > 24h.

---

## Quantity Consistency Invariant

**Single Source of Truth**: `stock.lot.fg_component_line_ids` + helper
`_t4_get_committed_components()` — chỉ tính phiếu `state='done'`.

```
free(product, location)
  = physical_qty
  − Σ committed_lock (FG quant > 0 ở location; net via _t4_get_committed_components)
  − Σ soft_lock (phiếu draft/waiting khác, chỉ dòng state='used')
```

**Enforcement points** (ở `t4_sti` — module này chỉ cung cấp data layer):

| Tầng | Method | Bảo vệ |
|---|---|---|
| assembly action_confirm | `_t4_check_returned_consistency` (local) | returned ≤ committed + new used |
| assembly line constraint | `_check_lot_not_committed_to_other_fg` (local) | lot không thuộc 2 FG done |
| line constraint | `_check_lot_name_not_in_active_phieu` (local) | soft-lock anti-race |
| picking validate | `_t4_check_fg_lot_top_level` (t4_sti) | lot tracked không move độc lập |
| picking validate | `_t4_check_qty_components_committed` (t4_sti) | tracking none không vượt free |
| picking done | `_t4_expand_fg_component_lots` (t4_sti) | BFS: FG move → component tự đi theo |

Chi tiết đầy đủ về pool free / BFS / đệ quy FG lồng ghép: xem
`addons/t4_sti/CLAUDE.md` section "Quantity Consistency" và
`t4_sti/tests/test_assembly_locking.py` (11 tests).

**Rule dòng returned trên phiếu draft**: không vào committed_lock / soft_lock.
Chỉ khi phiếu done thì `_t4_get_committed_components` mới trừ. `_t4_check_returned_consistency`
chạy tại `action_confirm` (không phải `@api.constrains` — tránh fire sai timing).

---

## Security (`security/ir.model.access.csv`)

| Model | User | Admin |
|---|---|---|
| `packing.request` | R/W/C | — |
| `packing.request.line` | R/W/C/D | — |
| `t4.product.component` | R/W/C | R/W/C/D (group_system) |
| `t4.product.creation` | R/W/C | R/W/C/D (group_system) |
| `t4.product.creation.line` | R/W/C | R/W/C/D (group_system) |
| `t4.product.creation.sign.wizard` | R/W/C/D | — |

---

## Migrations

| Version | File | Nội dung |
|---|---|---|
| 1.0.1 | `post-migration.py` | Migrate `image_tracking` Binary → `image_tracking_attachment_id` Many2one; restore tên file gốc; clear `res_field` magic |
| 1.0.4 | `pre-migration.py` | Đổi tên cột `line_type` → `state` trên `t4_product_creation_line` (robust với 4 trạng thái DB) |
| 1.0.7 | `post-migration.py` | Backfill `standard_price` (computed) + `list_price` (related stored) cho row cũ sau khi field đổi loại |
| 1.0.8 | `post-migration.py` | Compensate bug `_apply_inventory`: `inventory_quantity` phải là target tuyệt đối = current + delta, không phải chỉ delta |

---

## Tests

```
tests/
  test_product_component.py   # t4.product.component — CRUD, constraints, cascade
  test_assembly_record.py     # t4.assembly.record — create/sequence/lines/state/count
  test_packing_wizard.py      # packing.slip.wizard — scan barcode (3 path), finish_pack, qty_packed
```

Tag: `@tagged('post_install', '-at_install', 't4_product_package')`

**Lưu ý**: `test_assembly_record.py` tạo `t4.assembly.record` (model đóng gói
nhanh), không phải `t4.product.creation`. Tests cho invariant locking
(t4.product.creation) nằm tại `t4_sti/tests/test_assembly_locking.py`.

---

## Caveats / Rules

1. **KHÔNG nhầm `t4.assembly.record` với `t4.product.creation`**: đây là 2 model
   khác nhau. `t4.assembly.record` là model đơn giản của luồng đóng gói nhanh.
   `t4.product.creation` là model chính quản lý lắp ráp / định danh với đầy đủ
   state machine, locking, cost flow.

2. **`fg_component_line_ids` chỉ liệt kê dòng `used` của phiếu `done`** — dùng
   cho UI/báo cáo. Cho pool free / locking phải dùng
   `_t4_get_committed_components()` (net used − returned).

3. **`packing.request.assembly_record_ids` trỏ về `t4.product.creation`** (không
   phải `t4.assembly.record`) qua field `packing_request_id` trên
   `t4.product.creation`.

4. **Identify — inventory_quantity là target tuyệt đối**: khi gọi
   `_apply_inventory()`, `inventory_quantity = current_qty + line.quantity`
   (tính delta để tránh trừ nhầm stock hiện có). Bug v1.0.7- đã fix ở v1.0.8.

5. **Import order trong `__init__.py`**: `product_creation_line` (comodel) trước
   `product_creation` (parent), `packing_request_line` trước `packing_request`.

6. **Views dùng `<list>` không dùng `<tree>`** (Odoo 19). `view_mode` cũng dùng
   `list,form` không phải `tree,form`.
