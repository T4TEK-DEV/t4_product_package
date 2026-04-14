# -*- coding: utf-8 -*-
"""Tests cho t4.product.component (BOM đơn giản) + product.template extend."""
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 't4_product_package')
class TestProductComponent(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Component = cls.env['t4.product.component']
        # Thành phẩm
        cls.fg_template = cls.env['product.template'].create({
            'name': 'Laptop Assembled',
            'is_combo': True,
            'is_storable': True,
        })
        # Linh kiện
        cls.comp_screen = cls.env['product.product'].create({
            'name': 'Màn hình LCD',
            'is_storable': True,
            'tracking': 'serial',
        })
        cls.comp_keyboard = cls.env['product.product'].create({
            'name': 'Bàn phím',
            'is_storable': True,
            'tracking': 'none',
        })
        cls.comp_battery = cls.env['product.product'].create({
            'name': 'Pin',
            'is_storable': True,
            'tracking': 'lot',
        })

    # ── CRUD ──────────────────────────────────────────────────────

    def test_create_component_line(self):
        line = self.Component.create({
            'parent_product_id': self.fg_template.id,
            'product_id': self.comp_screen.id,
            'quantity': 1.0,
        })
        self.assertTrue(line.id)
        self.assertEqual(line.product_tmpl_id, self.comp_screen.product_tmpl_id)

    def test_create_multiple_components(self):
        """Thành phẩm có nhiều linh kiện."""
        self.Component.create([
            {'parent_product_id': self.fg_template.id, 'product_id': self.comp_screen.id, 'quantity': 1},
            {'parent_product_id': self.fg_template.id, 'product_id': self.comp_keyboard.id, 'quantity': 1},
            {'parent_product_id': self.fg_template.id, 'product_id': self.comp_battery.id, 'quantity': 2},
        ])
        self.assertEqual(self.fg_template.component_count, 3)

    def test_component_with_note(self):
        line = self.Component.create({
            'parent_product_id': self.fg_template.id,
            'product_id': self.comp_screen.id,
            'quantity': 1,
            'note': 'Dùng loại 15.6 inch',
        })
        self.assertEqual(line.note, 'Dùng loại 15.6 inch')

    # ── Constraints ───────────────────────────────────────────────

    def test_quantity_must_be_positive(self):
        with self.assertRaises(Exception):
            self.Component.create({
                'parent_product_id': self.fg_template.id,
                'product_id': self.comp_screen.id,
                'quantity': 0,
            })

    def test_negative_quantity_rejected(self):
        with self.assertRaises(Exception):
            self.Component.create({
                'parent_product_id': self.fg_template.id,
                'product_id': self.comp_screen.id,
                'quantity': -1,
            })

    def test_self_reference_rejected(self):
        """Linh kiện không được trùng với thành phẩm."""
        fg_variant = self.fg_template.product_variant_ids[0]
        with self.assertRaises(ValidationError):
            self.Component.create({
                'parent_product_id': self.fg_template.id,
                'product_id': fg_variant.id,
                'quantity': 1,
            })

    # ── Cascade / Restrict ────────────────────────────────────────

    def test_delete_parent_cascades_components(self):
        self.Component.create({
            'parent_product_id': self.fg_template.id,
            'product_id': self.comp_screen.id,
            'quantity': 1,
        })
        comp_count_before = self.Component.search_count([
            ('parent_product_id', '=', self.fg_template.id),
        ])
        self.assertEqual(comp_count_before, 1)
        self.fg_template.unlink()
        comp_count_after = self.Component.search_count([
            ('parent_product_id', '=', self.fg_template.id),
        ])
        self.assertEqual(comp_count_after, 0)

    # ── component_count computed ──────────────────────────────────

    def test_component_count_empty(self):
        tmpl = self.env['product.template'].create({
            'name': 'Empty FG',
            'is_combo': True,
        })
        self.assertEqual(tmpl.component_count, 0)

    def test_component_count_after_add_remove(self):
        line = self.Component.create({
            'parent_product_id': self.fg_template.id,
            'product_id': self.comp_screen.id,
            'quantity': 1,
        })
        self.assertEqual(self.fg_template.component_count, 1)
        line.unlink()
        self.fg_template.invalidate_recordset(['component_count'])
        self.assertEqual(self.fg_template.component_count, 0)

    # ── Thay đổi linh kiện liên tục ──────────────────────────────

    def test_change_components_freely(self):
        """Thành phẩm có thể thay đổi linh kiện bất kỳ lúc nào."""
        line = self.Component.create({
            'parent_product_id': self.fg_template.id,
            'product_id': self.comp_screen.id,
            'quantity': 1,
        })
        # Đổi linh kiện
        line.write({'product_id': self.comp_keyboard.id, 'quantity': 2})
        self.assertEqual(line.product_id, self.comp_keyboard)
        self.assertEqual(line.quantity, 2)

    def test_update_quantity(self):
        line = self.Component.create({
            'parent_product_id': self.fg_template.id,
            'product_id': self.comp_battery.id,
            'quantity': 1,
        })
        line.write({'quantity': 5})
        self.assertEqual(line.quantity, 5)
