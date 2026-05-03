# -*- coding: utf-8 -*-
"""Tests cho packing.slip.wizard — scan barcode + finish pack + edge cases."""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 't4_product_package')
class TestPackingWizard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Wizard = cls.env['packing.slip.wizard']
        # Thành phẩm
        cls.fg_product = cls.env['product.product'].create({
            'name': 'FG Product Test',
            'is_storable': True,
            'tracking': 'serial',
        })
        # Linh kiện
        cls.comp_product = cls.env['product.product'].create({
            'name': 'Component Test',
            'is_storable': True,
            'tracking': 'serial',
            'barcode': 'COMP001',
            'default_code': 'CMP-001',
            'standard_price': 50.0,
            'list_price': 80.0,
        })
        cls.comp_no_barcode = cls.env['product.product'].create({
            'name': 'No Barcode Component',
            'is_storable': True,
            'standard_price': 30.0,
            'list_price': 45.0,
        })
        # Lot cho linh kiện
        cls.lot_comp = cls.env['stock.lot'].create({
            'name': 'LOT-COMP-001',
            'product_id': cls.comp_product.id,
            'company_id': cls.env.company.id,
        })
        # Packing request
        cls.request = cls.env['packing.request'].create({})

    def _create_wizard(self, **kwargs):
        vals = {'request_id': self.request.id}
        vals.update(kwargs)
        return self.Wizard.create(vals)

    # ── Scan Barcode — Tìm theo lot ──────────────────────────────

    def test_scan_find_by_lot_name(self):
        wizard = self._create_wizard(barcode_input='LOT-COMP-001')
        wizard.action_scan_barcode()
        self.assertEqual(len(wizard.line_ids), 1)
        self.assertEqual(wizard.line_ids[0].product_id, self.comp_product)
        self.assertEqual(wizard.line_ids[0].lot_id, self.lot_comp)
        self.assertFalse(wizard.barcode_input)

    # ── Scan Barcode — Tìm theo product barcode ──────────────────

    def test_scan_find_by_product_barcode(self):
        wizard = self._create_wizard(barcode_input='COMP001')
        wizard.action_scan_barcode()
        self.assertEqual(len(wizard.line_ids), 1)
        self.assertEqual(wizard.line_ids[0].product_id, self.comp_product)

    # ── Scan Barcode — Tìm theo default_code ─────────────────────

    def test_scan_find_by_default_code(self):
        wizard = self._create_wizard(barcode_input='CMP-001')
        wizard.action_scan_barcode()
        self.assertEqual(len(wizard.line_ids), 1)
        self.assertEqual(wizard.line_ids[0].product_id, self.comp_product)

    # ── Scan Barcode — Không tìm thấy ────────────────────────────

    def test_scan_not_found_raises_error(self):
        wizard = self._create_wizard(barcode_input='NONEXISTENT')
        with self.assertRaises(UserError):
            wizard.action_scan_barcode()

    # ── Scan Barcode — Empty input ────────────────────────────────

    def test_scan_empty_barcode(self):
        wizard = self._create_wizard(barcode_input='')
        result = wizard.action_scan_barcode()
        self.assertIsNone(result)

    def test_scan_none_barcode(self):
        wizard = self._create_wizard()
        result = wizard.action_scan_barcode()
        self.assertIsNone(result)

    # ── Scan Barcode — Price snapshot ─────────────────────────────

    def test_scan_captures_price_snapshot(self):
        wizard = self._create_wizard(barcode_input='COMP001')
        wizard.action_scan_barcode()
        line = wizard.line_ids[0]
        self.assertEqual(line.standard_price, 50.0)
        self.assertEqual(line.list_price, 80.0)

    # ── Scan nhiều linh kiện ──────────────────────────────────────

    def test_scan_multiple_components(self):
        wizard = self._create_wizard(barcode_input='LOT-COMP-001')
        wizard.action_scan_barcode()
        wizard.write({'barcode_input': 'COMP001'})
        wizard.action_scan_barcode()
        self.assertEqual(len(wizard.line_ids), 2)

    # ── Finish Pack — Validations ─────────────────────────────────

    def test_finish_no_lines_raises_error(self):
        wizard = self._create_wizard(fg_product_id=self.fg_product.id)
        with self.assertRaises(UserError):
            wizard.action_finish_pack()

    def test_finish_no_fg_product_raises_error(self):
        wizard = self._create_wizard(barcode_input='COMP001')
        wizard.action_scan_barcode()
        with self.assertRaises(UserError):
            wizard.action_finish_pack()

    # ── Finish Pack — Success ─────────────────────────────────────

    def test_finish_creates_assembly_record(self):
        wizard = self._create_wizard(
            fg_product_id=self.fg_product.id,
            barcode_input='COMP001',
        )
        wizard.action_scan_barcode()
        wizard.action_finish_pack()

        assembly = self.env['t4.assembly.record'].search([
            ('packing_request_id', '=', self.request.id),
        ], limit=1)
        self.assertTrue(assembly)
        self.assertEqual(assembly.product_id, self.fg_product)
        self.assertEqual(assembly.state, 'done')

    def test_finish_creates_fg_lot(self):
        """Thành phẩm tracking=serial → tạo lot mới."""
        wizard = self._create_wizard(
            fg_product_id=self.fg_product.id,
            barcode_input='COMP001',
        )
        wizard.action_scan_barcode()
        wizard.action_finish_pack()

        assembly = self.env['t4.assembly.record'].search([
            ('packing_request_id', '=', self.request.id),
        ], limit=1)
        self.assertTrue(assembly.lot_id)
        self.assertEqual(assembly.lot_id.product_id, self.fg_product)

    def test_finish_assembly_line_snapshot(self):
        wizard = self._create_wizard(
            fg_product_id=self.fg_product.id,
            barcode_input='LOT-COMP-001',
        )
        wizard.action_scan_barcode()
        wizard.action_finish_pack()

        assembly = self.env['t4.assembly.record'].search([
            ('packing_request_id', '=', self.request.id),
        ], limit=1)
        self.assertEqual(len(assembly.line_ids), 1)
        line = assembly.line_ids[0]
        self.assertEqual(line.product_id, self.comp_product)
        self.assertEqual(line.lot_id, self.lot_comp)
        self.assertEqual(line.standard_price, 50.0)
        self.assertEqual(line.list_price, 80.0)

    # ── Finish Pack — qty_packed update ───────────────────────────

    def test_finish_updates_qty_packed(self):
        self.request.write({
            'request_line_ids': [(0, 0, {
                'product_id': self.comp_product.id,
                'product_uom_qty': 5,
            })],
        })
        wizard = self._create_wizard(
            fg_product_id=self.fg_product.id,
            barcode_input='COMP001',
        )
        wizard.action_scan_barcode()
        wizard.action_finish_pack()

        req_line = self.request.request_line_ids[0]
        self.assertEqual(req_line.qty_packed, 1.0)

    # ── Packing Request Workflow ──────────────────────────────────

    def test_packing_request_full_workflow(self):
        """Nghiệp vụ đầy đủ: confirm → wizard → finish → done."""
        self.request.write({
            'request_line_ids': [(0, 0, {
                'product_id': self.comp_product.id,
                'product_uom_qty': 1,
            })],
        })
        # Confirm
        self.request.action_confirm()
        self.assertEqual(self.request.state, 'open')

        # Wizard → scan → finish
        wizard = self._create_wizard(
            fg_product_id=self.fg_product.id,
            barcode_input='LOT-COMP-001',
        )
        wizard.action_scan_barcode()
        wizard.action_finish_pack()

        # Done
        self.request.action_done()
        self.assertEqual(self.request.state, 'done')
        self.assertEqual(self.request.assembly_count, 1)
