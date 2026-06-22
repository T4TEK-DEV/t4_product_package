# -*- coding: utf-8 -*-
"""Post-migration v1.0.8: compensate adjustment bug ở phiếu Định Danh LK TP.

Bug v1.0.7-: `_t4_create_component_lots` tạo stock.quant với
`inventory_quantity = line.quantity` (TARGET ABSOLUTE). Khi quant đã
tồn tại tại fg_location (vd: tracking='none' merge theo product+location,
hoặc lot tái sử dụng) với qty=N, set inventory_quantity=Q → Odoo tính
delta = Q − N → tạo move giảm/tăng sai hướng.

Ví dụ user case:
  - SS0012.cpu.SSSSSS tồn 100 tại HQG/Kho
  - PC/2026/00035 định danh thêm 3 đơn vị
  - Bug: inventory_quantity=3 → delta=-97 → kho còn 3 (đúng phải 103)

Fix code: `product_creation.py:_t4_create_component_lots` đã tính
target_qty = current + line.quantity từ v1.0.8.

Migration này compensate dữ liệu cũ: với mỗi phiếu identify done, so
sánh sum signed delta của move (linked qua t4_creation_id) với
+line.quantity. Nếu lệch → tạo move bù.

Idempotent: chạy lại nếu sum khớp thì skip.
"""
import logging
from collections import defaultdict
from odoo import SUPERUSER_ID
from odoo.api import Environment

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = Environment(cr, SUPERUSER_ID, {})
    Creation = env['t4.product.creation']
    Move = env['stock.move']
    Quant = env['stock.quant']

    phieus = Creation.search([
        ('type', '=', 'identify'),
        ('state', '=', 'done'),
    ])
    if not phieus:
        _logger.info('t4_product_package 1.0.8: không có phiếu identify done')
        return

    total_compensated = 0
    total_lines_checked = 0

    for phieu in phieus:
        # Aggregate expected delta per (product_id, lot_id_or_0)
        expected = defaultdict(float)
        for line in phieu.line_ids:  # state='used'
            if not line.product_id or not line.quantity:
                continue
            key = (line.product_id.id, line.lot_id.id or 0)
            expected[key] += line.quantity
            total_lines_checked += 1

        if not expected:
            continue

        # Aggregate actual signed delta từ moves linked với phiếu này
        moves = Move.search([
            ('t4_creation_id', '=', phieu.id),
            ('state', '=', 'done'),
        ])
        actual = defaultdict(float)
        for mv in moves:
            for ml in mv.move_line_ids:
                key = (ml.product_id.id, ml.lot_id.id or 0)
                # Direction: + nếu vào fg_location (location_dest_id internal),
                # − nếu ra (location_id internal → loss).
                # Tin cậy location.usage: 'internal' = kho thực; 'inventory'
                # = loss/adjust.
                if ml.location_dest_id.usage == 'internal' \
                        and ml.location_id.usage != 'internal':
                    actual[key] += ml.quantity
                elif ml.location_id.usage == 'internal' \
                        and ml.location_dest_id.usage != 'internal':
                    actual[key] -= ml.quantity
                # internal → internal (transfer): không tính ở đây

        # So sánh, tạo compensating adjustment
        for key, exp_qty in expected.items():
            act_qty = actual.get(key, 0.0)
            diff = exp_qty - act_qty
            if abs(diff) < 0.0001:
                continue  # đã đúng

            product_id, lot_id_int = key
            # Tìm fg_location: ưu tiên internal location có qty > 0.
            # KHÔNG dùng `is_usage_restricted` (field của t4_sti) vì migration
            # này chạy trong load t4_product_package — t4_sti chưa load xong,
            # field chưa visible. Fallback hợp lý: location có qty cao nhất.
            fg_quant = phieu.lot_id.quant_ids.filtered(
                lambda q: q.location_id.usage == 'internal'
                and q.quantity > 0
            ).sorted(key=lambda q: q.quantity, reverse=True)[:1]
            if not fg_quant:
                _logger.warning(
                    't4_product_package 1.0.8: phiếu %s không tìm thấy '
                    'fg_location, skip compensate (product %s lot %s diff %s)',
                    phieu.name, product_id, lot_id_int, diff,
                )
                continue
            fg_location = fg_quant.location_id

            # Tìm quant hiện tại
            qdomain = [
                ('product_id', '=', product_id),
                ('location_id', '=', fg_location.id),
            ]
            if lot_id_int:
                qdomain.append(('lot_id', '=', lot_id_int))
            else:
                qdomain.append(('lot_id', '=', False))
            current = Quant.search(qdomain, limit=1)
            current_qty = current.quantity if current else 0.0
            target_qty = current_qty + diff

            quant_vals = {
                'product_id': product_id,
                'location_id': fg_location.id,
                'inventory_quantity': target_qty,
                'inventory_quantity_set': True,
            }
            if lot_id_int:
                quant_vals['lot_id'] = lot_id_int
            new_quant = Quant.with_context(inventory_mode=True).create(quant_vals)
            new_quant.with_context(t4_creation_id=phieu.id)._apply_inventory()
            total_compensated += 1
            _logger.info(
                't4_product_package 1.0.8: phiếu %s compensate '
                'product=%s lot=%s diff=%+.2f (current=%.2f → target=%.2f)',
                phieu.name, product_id, lot_id_int, diff,
                current_qty, target_qty,
            )

    _logger.info(
        't4_product_package 1.0.8: kiểm %d line, compensate %d adjustment',
        total_lines_checked, total_compensated,
    )
