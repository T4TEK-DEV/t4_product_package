# -*- coding: utf-8 -*-
"""Seed dữ liệu mẫu cho t4_product_package.

Chạy qua odoo-bin shell:

    cd D:/workspaces/odoo_19_base
    python odoo-bin shell -c D:/workspaces/projects/odoo19/t4_sti/odoo.conf -d t4_sti --no-http \
        < D:/workspaces/projects/odoo19/t4_sti/addons/t4_product_package/scripts/seed_sample_data.py

Tạo:
- 5 linh kiện (3 không tracking + 2 serial-tracked với lot tồn kho).
- 2 thành phẩm (FG_A, FG_B) — tracking=serial, có BOM đầy đủ.
- 2 phiếu lắp ráp t4.product.creation (type=assembly, state=done) — mỗi
  phiếu tạo 1 serial cho FG, snapshot giá linh kiện, có lot trên line để
  stock.quant.fg_component_line_ids hiển thị.
- 1 thành phẩm super (FG_SUPER) — tracking=serial, BOM = [FG_A, FG_B].

Idempotent: chạy lại không tạo trùng (so default_code / SEED marker).
"""
import logging

_logger = logging.getLogger("t4_product_package.seed")

# ============================================================
# Config
# ============================================================
SEED_TAG = "[SEED:t4_product_package]"

COMPONENTS = [
    # (default_code, name, tracking, standard_price, list_price, init_lots)
    ("LK-RES-01", "Điện trở 10K", "none", 500, 800, []),
    ("LK-CAP-01", "Tụ điện 100uF", "none", 1200, 2000, []),
    ("LK-CAS-01", "Vỏ nhựa ABS", "none", 8000, 15000, []),
    ("LK-MCU-01", "MCU STM32F103", "serial", 95000, 150000,
     ["MCU-001", "MCU-002", "MCU-003"]),
    ("LK-PCB-01", "Bo mạch PCB v2", "serial", 45000, 75000,
     ["PCB-001", "PCB-002", "PCB-003"]),
]

# (default_code, name, BOM lines [(component_default_code, qty)])
FG_PRODUCTS = [
    ("TP-DEV-A", "Smart Device A", 850000, 1500000, [
        ("LK-RES-01", 10),
        ("LK-CAP-01", 5),
        ("LK-MCU-01", 1),
        ("LK-PCB-01", 1),
        ("LK-CAS-01", 1),
    ]),
    ("TP-DEV-B", "Smart Device B", 720000, 1300000, [
        ("LK-RES-01", 8),
        ("LK-CAP-01", 3),
        ("LK-MCU-01", 1),
        ("LK-PCB-01", 1),
        ("LK-CAS-01", 1),
    ]),
]

# Thành phẩm super: BOM dùng 2 FG ở trên làm linh kiện
FG_SUPER = (
    "TP-COMBO-AB", "Combo Smart Device AB", 1700000, 3000000,
    [("TP-DEV-A", 1), ("TP-DEV-B", 1)],
)

# Phiếu lắp ráp: (fg_default_code, [(component_default_code, qty, lot_name_or_None)])
ASSEMBLIES = [
    ("TP-DEV-A", [
        ("LK-RES-01", 10, None),
        ("LK-CAP-01", 5, None),
        ("LK-MCU-01", 1, "MCU-001"),
        ("LK-PCB-01", 1, "PCB-001"),
        ("LK-CAS-01", 1, None),
    ]),
    ("TP-DEV-B", [
        ("LK-RES-01", 8, None),
        ("LK-CAP-01", 3, None),
        ("LK-MCU-01", 1, "MCU-002"),
        ("LK-PCB-01", 1, "PCB-002"),
        ("LK-CAS-01", 1, None),
    ]),
]


# ============================================================
# Helpers
# ============================================================
def get_or_create_product(env, default_code, name, tracking, std_price, lst_price):
    """Get product.product by default_code or create new one."""
    product = env["product.product"].search(
        [("default_code", "=", default_code)], limit=1,
    )
    if product:
        print(f"  - Product exist: {default_code} ({product.name})")
        return product
    tmpl = env["product.template"].create({
        "name": name,
        "default_code": default_code,
        "type": "consu",
        "is_storable": True,
        "tracking": tracking,
        "standard_price": std_price,
        "list_price": lst_price,
        "uom_id": env.ref("uom.product_uom_unit").id,
    })
    product = tmpl.product_variant_id
    print(f"  + Product created: {default_code} ({name}) tracking={tracking}")
    return product


def get_or_create_lot(env, product, lot_name):
    """Get/create stock.lot for product+name."""
    lot = env["stock.lot"].search([
        ("product_id", "=", product.id),
        ("name", "=", lot_name),
    ], limit=1)
    if lot:
        return lot
    lot = env["stock.lot"].create({
        "name": lot_name,
        "product_id": product.id,
        "company_id": env.company.id,
    })
    print(f"    + Lot created: {lot_name} ({product.default_code})")
    return lot


def stock_in(env, product, location, qty, lot=None):
    """Đẩy tồn kho vào location bằng inventory adjustment."""
    Quant = env["stock.quant"]
    domain = [
        ("product_id", "=", product.id),
        ("location_id", "=", location.id),
    ]
    if lot:
        domain.append(("lot_id", "=", lot.id))
    quant = Quant.search(domain, limit=1)
    if quant and quant.quantity >= qty:
        return quant
    vals = {
        "product_id": product.id,
        "location_id": location.id,
        "inventory_quantity": qty,
    }
    if lot:
        vals["lot_id"] = lot.id
    if not quant:
        quant = Quant.with_context(inventory_mode=True).create(vals)
    else:
        quant.with_context(inventory_mode=True).inventory_quantity = qty
    quant.with_context(inventory_mode=True).action_apply_inventory()
    print(f"    + Stock in: {product.default_code} qty={qty}"
          f"{f' lot={lot.name}' if lot else ''}")
    return quant


def get_or_create_bom_line(env, parent_tmpl, component_product, qty):
    """Tạo dòng BOM nếu chưa có."""
    Comp = env["t4.product.component"]
    line = Comp.search([
        ("parent_product_id", "=", parent_tmpl.id),
        ("product_id", "=", component_product.id),
    ], limit=1)
    if line:
        if line.quantity != qty:
            line.quantity = qty
        return line
    line = Comp.create({
        "parent_product_id": parent_tmpl.id,
        "product_id": component_product.id,
        "quantity": qty,
    })
    print(f"    + BOM line: {parent_tmpl.default_code} <- "
          f"{component_product.default_code} x{qty}")
    return line


def assembly_already_seeded(env, fg_product):
    """Kiểm tra đã có phiếu seed cho FG này chưa (so SEED_TAG trong note)."""
    Creation = env["t4.product.creation"]
    return Creation.search_count([
        ("product_id", "=", fg_product.id),
        ("type", "=", "assembly"),
        ("note", "like", SEED_TAG),
        ("state", "=", "done"),
    ], limit=1) > 0


# ============================================================
# Main
# ============================================================
def seed(env):
    print("=" * 60)
    print("SEED t4_product_package sample data")
    print("=" * 60)

    warehouse = env["stock.warehouse"].search(
        [("company_id", "=", env.company.id)], limit=1,
    )
    stock_loc = warehouse.lot_stock_id
    print(f"Warehouse: {warehouse.name}, Stock location: {stock_loc.complete_name}")

    # 1. Components ----------------------------------------------------
    print("\n[1] Components")
    comp_by_code = {}
    for code, name, tracking, std, lst, lot_names in COMPONENTS:
        product = get_or_create_product(env, code, name, tracking, std, lst)
        comp_by_code[code] = product
        # Stock in: tracked → tạo lot; untracked → đẩy số lượng lớn.
        if tracking == "serial":
            for lot_name in lot_names:
                lot = get_or_create_lot(env, product, lot_name)
                stock_in(env, product, stock_loc, 1.0, lot=lot)
        else:
            stock_in(env, product, stock_loc, 100.0)

    # 2. FG products + BOM --------------------------------------------
    print("\n[2] FG products + BOM")
    fg_by_code = {}
    for code, name, std, lst, bom in FG_PRODUCTS:
        fg = get_or_create_product(env, code, name, "serial", std, lst)
        fg_by_code[code] = fg
        for comp_code, qty in bom:
            get_or_create_bom_line(env, fg.product_tmpl_id,
                                   comp_by_code[comp_code], qty)

    # 3. Assembly records (t4.product.creation, type=assembly) ---------
    print("\n[3] Assembly records")
    Creation = env["t4.product.creation"]
    for fg_code, lines_spec in ASSEMBLIES:
        fg = fg_by_code[fg_code]
        if assembly_already_seeded(env, fg):
            print(f"  - Assembly exist for {fg_code} (skip)")
            continue
        line_vals = []
        for comp_code, qty, lot_name in lines_spec:
            comp = comp_by_code[comp_code]
            vals = {
                "state": "used",
                "product_id": comp.id,
                "quantity": qty,
                "standard_price": comp.standard_price,
                "list_price": comp.lst_price,
            }
            if lot_name:
                lot = env["stock.lot"].search([
                    ("name", "=", lot_name),
                    ("product_id", "=", comp.id),
                ], limit=1)
                if lot:
                    vals["lot_id"] = lot.id
            line_vals.append((0, 0, vals))

        rec = Creation.create({
            "type": "assembly",
            "product_id": fg.id,
            "company_id": env.company.id,
            "note": f"{SEED_TAG} Phiếu lắp ráp mẫu {fg_code}",
            "line_ids": line_vals,
        })
        rec.action_confirm()  # state=done + auto-create lot for FG
        # Nhập kho FG (đặt 1 serial vào internal stock).
        stock_in(env, fg, stock_loc, 1.0, lot=rec.lot_id)
        print(f"  + Assembly created: {rec.name} → FG {fg_code} "
              f"lot={rec.lot_id.name} (lines={len(rec.line_ids)})")

    # 4. FG_SUPER với BOM = 2 FG vừa tạo -------------------------------
    print("\n[4] FG super")
    super_code, super_name, super_std, super_lst, super_bom = FG_SUPER
    fg_super = get_or_create_product(env, super_code, super_name,
                                     "serial", super_std, super_lst)
    for comp_code, qty in super_bom:
        get_or_create_bom_line(env, fg_super.product_tmpl_id,
                               fg_by_code[comp_code], qty)

    # 5. Phiếu lắp ráp combo: dùng lot của 2 FG vừa tạo làm linh kiện ----
    print("\n[5] Combo assembly (FG-of-FG)")
    if assembly_already_seeded(env, fg_super):
        print(f"  - Combo assembly exist for {super_code} (skip)")
    else:
        combo_lines = []
        for comp_code, qty in super_bom:
            comp_fg = fg_by_code[comp_code]
            # Lấy phiếu lắp đã done gần nhất của FG con → lot output làm linh kiện.
            prev = env["t4.product.creation"].search([
                ("product_id", "=", comp_fg.id),
                ("type", "=", "assembly"),
                ("state", "=", "done"),
            ], order="id desc", limit=1)
            if not prev or not prev.lot_id:
                print(f"  ! Khong tim thay lot cho {comp_code} (skip combo)")
                combo_lines = []
                break
            combo_lines.append((0, 0, {
                "state": "used",
                "product_id": comp_fg.id,
                "lot_id": prev.lot_id.id,
                "quantity": qty,
                "standard_price": comp_fg.standard_price,
                "list_price": comp_fg.lst_price,
            }))
        if combo_lines:
            rec = env["t4.product.creation"].create({
                "type": "assembly",
                "product_id": fg_super.id,
                "company_id": env.company.id,
                "note": f"{SEED_TAG} Combo assembly {super_code}",
                "line_ids": combo_lines,
            })
            rec.action_confirm()
            stock_in(env, fg_super, stock_loc, 1.0, lot=rec.lot_id)
            print(f"  + Combo assembly: {rec.name} → {super_code} "
                  f"lot={rec.lot_id.name} (lines={len(rec.line_ids)})")

    # 6. Force recompute assembly_status (store=True compute không tự
    # trigger ngay khi chuỗi create-then-confirm chạy trong cùng cursor).
    print("\n[6] Recompute stock.quant.assembly_status")
    seed_codes = ([c[0] for c in COMPONENTS] + [f[0] for f in FG_PRODUCTS]
                  + [FG_SUPER[0]])
    quants = env["stock.quant"].search([
        ("product_id.default_code", "in", seed_codes),
    ])
    quants.invalidate_recordset(["assembly_status"])
    for q in quants:
        q._compute_assembly_status()
    env.flush_all()
    print(f"  Recomputed {len(quants)} quants")

    print("\n" + "=" * 60)
    print("DONE — committing transaction")
    print("=" * 60)


# Khi chạy qua `odoo-bin shell`, biến `env` được expose tự động.
try:
    seed(env)  # noqa: F821 — env injected by odoo shell
    env.cr.commit()  # noqa: F821
    print("✓ Committed.")
except Exception as exc:
    print(f"✗ ERROR: {exc!r}")
    env.cr.rollback()  # noqa: F821
    raise
