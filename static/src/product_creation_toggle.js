/** @odoo-module **/

// Toggle LIVE used↔returned cho phiếu LẮP RÁP (t4.product.creation, type=assembly).
//
// Quy tắc (user chốt): 1 serial (lot_name) chỉ tồn tại 1 dòng trong phiếu.
//   - Quét serial CHƯA có            → vào "Linh kiện SỬ DỤNG" (line_ids).
//   - Quét LẠI serial đang ở SỬ DỤNG → chuyển sang "TRẢ" (line_returned_ids), xóa dòng cũ.
//   - Quét LẠI serial đang ở TRẢ     → chuyển ngược lại SỬ DỤNG.
//
// Cơ chế: patch FormRenderer (chỉ kích hoạt cho model t4.product.creation),
// chạy reconcile sau mỗi patch (onPatched). Idempotent: chỉ hành động khi có
// serial TRÙNG (xuất hiện ≥2 lần do quét lại); sau khi gộp về 1 dòng thì không
// còn trùng → ổn định, không lặp vô hạn. Có cờ `_t4Reconciling` chặn re-entry.
//
// Xác định dòng MỚI vs CŨ: dòng vừa quét chưa lưu (không có resId); dòng cũ đã
// lưu (có resId). Phiếu hoàn toàn chưa lưu (cả 2 đều chưa resId) → coi dòng
// CUỐI theo thứ tự là dòng mới (scan append ở bottom).
//
// LƯU Ý: file này cần test trên màn hình thật (luồng quét không chạy headless).
// Bật log chi tiết: window.__t4ToggleDbg = true.

import { patch } from "@web/core/utils/patch";
import { onPatched } from "@odoo/owl";
import { FormRenderer } from "@web/views/form/form_renderer";

const TARGET_MODEL = "t4.product.creation";

function _dbg(...args) {
    if (window.__t4ToggleDbg) {
        // eslint-disable-next-line no-console
        console.log("[t4-toggle]", ...args);
    }
}

function _norm(v) {
    return typeof v === "string" ? v.trim() : v;
}

// Lấy giá trị m2o để gán sang dòng khác: cần {id, display_name} cho virtual record.
function _m2o(val) {
    if (val && typeof val === "object" && val.id) {
        return { id: val.id, display_name: val.display_name || "" };
    }
    return false;
}

patch(FormRenderer.prototype, {
    setup() {
        super.setup();
        this._t4Reconciling = false;
        onPatched(() => {
            const root = this.env.model && this.env.model.root;
            if (!root || root.resModel !== TARGET_MODEL) {
                return;
            }
            this._t4ReconcileToggle().catch((e) =>
                console.error("[t4-toggle] reconcile error:", e)
            );
        });
    },

    async _t4ReconcileToggle() {
        if (this._t4Reconciling) {
            return;
        }
        const root = this.env.model.root;
        if (!root || root.resModel !== TARGET_MODEL) {
            return;
        }
        if (root.data.type !== "assembly") {
            return; // identify nhập tay → không toggle
        }
        const used = root.data.line_ids;
        const ret = root.data.line_returned_ids;
        if (!used || !ret || !Array.isArray(used.records) || !Array.isArray(ret.records)) {
            return;
        }

        // Gom occurrences theo serial qua cả 2 bảng.
        const occ = new Map();
        const collect = (list, state) => {
            for (const rec of list.records) {
                const s = _norm(rec.data.lot_name);
                if (!s) {
                    continue;
                }
                if (!occ.has(s)) {
                    occ.set(s, []);
                }
                occ.get(s).push({ rec, list, state });
            }
        };
        collect(used, "used");
        collect(ret, "returned");

        // Tìm 1 serial TRÙNG (≥2) để xử lý mỗi lần (re-render rồi xử lý tiếp).
        let dup = null;
        for (const [serial, items] of occ) {
            if (items.length >= 2) {
                dup = { serial, items };
                break;
            }
        }
        if (!dup) {
            return;
        }

        this._t4Reconciling = true;
        try {
            const items = dup.items;
            // Dòng MỚI = không có resId (vừa quét, chưa lưu); fallback dòng cuối.
            const newItem =
                items.find((i) => !i.rec.resId) || items[items.length - 1];
            const priorItems = items.filter((i) => i !== newItem);
            const priorState = priorItems[0].state; // trạng thái TRƯỚC khi quét lại
            const targetState = priorState === "used" ? "returned" : "used";
            const targetList = targetState === "used" ? used : ret;

            // Snapshot dữ liệu để dựng lại 1 dòng ở bảng đích.
            const src = newItem.rec;
            const payload = {
                lot_name: src.data.lot_name,
                product_id: _m2o(src.data.product_id),
                lot_id: _m2o(src.data.lot_id),
                quantity: src.data.quantity || 1,
                brand_part_id: src.data.brand_part_id || false,
                manufacturer_part_id: src.data.manufacturer_part_id || false,
            };
            _dbg("toggle serial", dup.serial, "prior", priorState, "->", targetState, payload);

            // Xóa MỌI occurrence của serial này (cả mới lẫn cũ).
            for (const it of items) {
                if (typeof it.list.delete === "function") {
                    await it.list.delete(it.rec);
                }
            }
            // Thêm đúng 1 dòng vào bảng đích (state lấy từ default_state của list).
            const nr = await targetList.addNewRecord({ position: "bottom", mode: "edit" });
            await nr.update(payload);
            _dbg("toggle done -> state", targetState);
        } finally {
            this._t4Reconciling = false;
        }
    },
});
