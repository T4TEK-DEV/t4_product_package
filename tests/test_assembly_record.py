# -*- coding: utf-8 -*-
"""Tests cho t4.assembly.record + t4.assembly.record.line — nghiệp vụ lắp ráp."""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 't4_product_package')
class TestAssemblyRecord(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.AssemblyRecord = cls.env['t4.assembly.record']
        cls.fg_product = cls.env['product.product'].create({
            'name': 'Laptop FG',
            'is_storable': True,
            'tracking': 'serial',
            'is_combo': True,
        })
        cls.comp_a = cls.env['product.product'].create({
            'name': 'Comp A',
            'is_storable': True,
            'standard_price': 100.0,
            'list_price': 150.0,
        })
        cls.comp_b = cls.env['product.product'].create({
            'name': 'Comp B',
            'is_storable': True,
            'standard_price': 200.0,
            'list_price': 300.0,
        })

    # ── Create + Sequence ─────────────────────────────────────────

    def test_create_with_sequence(self):
        record = self.AssemblyRecord.create({
            'product_id': self.fg_product.id,
        })
        self.assertNotEqual(record.name, 'New')
        self.assertTrue(record.name.startswith('AR/'))

    def test_create_default_draft(self):
        record = self.AssemblyRecord.create({
            'product_id': self.fg_product.id,
        })
        self.assertEqual(record.state, 'draft')

    # ── Lines + Price Snapshot ────────────────────────────────────

    def test_line_price_snapshot(self):
        record = self.AssemblyRecord.create({
            'product_id': self.fg_product.id,
            'line_ids': [(0, 0, {
                'product_id': self.comp_a.id,
                'quantity': 2,
                'standard_price': 100.0,
                'list_price': 150.0,
            })],
        })
        line = record.line_ids[0]
        self.assertEqual(line.total_standard_price, 200.0)
        self.assertEqual(line.total_list_price, 300.0)

    def test_total_computed_from_lines(self):
        record = self.AssemblyRecord.create({
            'product_id': self.fg_product.id,
            'line_ids': [
                (0, 0, {
                    'product_id': self.comp_a.id,
                    'quantity': 1,
                    'standard_price': 100.0,
                    'list_price': 150.0,
                }),
                (0, 0, {
                    'product_id': self.comp_b.id,
                    'quantity': 1,
                    'standard_price': 200.0,
                    'list_price': 300.0,
                }),
            ],
        })
        self.assertEqual(record.total_standard_price, 300.0)
        self.assertEqual(record.total_list_price, 450.0)

    def test_line_zero_quantity(self):
        """Quantity 0 → tổng = 0."""
        record = self.AssemblyRecord.create({
            'product_id': self.fg_product.id,
            'line_ids': [(0, 0, {
                'product_id': self.comp_a.id,
                'quantity': 0,
                'standard_price': 100.0,
                'list_price': 150.0,
            })],
        })
        self.assertEqual(record.total_standard_price, 0)

    # ── State Transitions ─────────────────────────────────────────

    def test_action_done(self):
        record = self.AssemblyRecord.create({
            'product_id': self.fg_product.id,
        })
        record.action_done()
        self.assertEqual(record.state, 'done')

    def test_action_cancel(self):
        record = self.AssemblyRecord.create({
            'product_id': self.fg_product.id,
        })
        record.action_cancel()
        self.assertEqual(record.state, 'cancel')

    # ── Assembly Count on Product ─────────────────────────────────

    def test_assembly_count_on_product_template(self):
        tmpl = self.fg_product.product_tmpl_id
        self.AssemblyRecord.create({
            'product_id': self.fg_product.id,
            'state': 'done',
        })
        self.AssemblyRecord.create({
            'product_id': self.fg_product.id,
            'state': 'done',
        })
        self.AssemblyRecord.create({
            'product_id': self.fg_product.id,
            'state': 'cancel',  # Không tính
        })
        tmpl.invalidate_recordset(['assembly_count'])
        self.assertEqual(tmpl.assembly_count, 2)

    # ── Lot Assignment ────────────────────────────────────────────

    def test_lot_assignment(self):
        lot = self.env['stock.lot'].create({
            'product_id': self.fg_product.id,
            'company_id': self.env.company.id,
        })
        record = self.AssemblyRecord.create({
            'product_id': self.fg_product.id,
            'lot_id': lot.id,
        })
        self.assertEqual(record.lot_id, lot)

    # ── Packing Request Link ──────────────────────────────────────

    def test_packing_request_assembly_count(self):
        request = self.env['packing.request'].create({})
        self.AssemblyRecord.create({
            'product_id': self.fg_product.id,
            'packing_request_id': request.id,
        })
        self.assertEqual(request.assembly_count, 1)

    # ── Multiple assemblies for same product (thay đổi LK liên tục) ──

    def test_different_components_per_assembly(self):
        """Mỗi lần lắp ráp có snapshot linh kiện khác nhau."""
        record1 = self.AssemblyRecord.create({
            'product_id': self.fg_product.id,
            'line_ids': [(0, 0, {
                'product_id': self.comp_a.id,
                'quantity': 1,
                'standard_price': 100.0,
                'list_price': 150.0,
            })],
            'state': 'done',
        })
        record2 = self.AssemblyRecord.create({
            'product_id': self.fg_product.id,
            'line_ids': [
                (0, 0, {
                    'product_id': self.comp_a.id,
                    'quantity': 1,
                    'standard_price': 110.0,  # Giá thay đổi
                    'list_price': 160.0,
                }),
                (0, 0, {
                    'product_id': self.comp_b.id,  # Thêm LK mới
                    'quantity': 2,
                    'standard_price': 200.0,
                    'list_price': 300.0,
                }),
            ],
            'state': 'done',
        })
        # Record 1: chỉ comp_a (100)
        self.assertEqual(record1.total_standard_price, 100.0)
        # Record 2: comp_a (110) + comp_b*2 (400) = 510
        self.assertEqual(record2.total_standard_price, 510.0)
