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
        # t4_sti yêu cầu technical_categ_id + default_code; tracking='none'
        # phải dùng AVCO (không SN AVCO).
        TechCateg = cls.env['product.category.technical']
        tc_fg = TechCateg.create({'name': 'Component FG'})
        tc_screen = TechCateg.create({'name': 'Component Screen'})
        tc_kb = TechCateg.create({'name': 'Component Keyboard'})
        tc_bat = TechCateg.create({'name': 'Component Battery'})
        avco_categ = cls.env.ref(
            't4_cost_tracking.product_category_account_avco')
        # Thành phẩm
        cls.fg_template = cls.env['product.template'].create({
            'name': 'Laptop Assembled',
            'default_code': 'T4_COMP_FG',
            'technical_categ_id': tc_fg.id,
            'is_storable': True,
            'tracking': 'serial',
        })
        # Linh kiện
        cls.comp_screen = cls.env['product.product'].create({
            'name': 'Màn hình LCD',
            'default_code': 'T4_COMP_SCREEN',
            'technical_categ_id': tc_screen.id,
            'is_storable': True,
            'tracking': 'serial',
        })
        cls.comp_keyboard = cls.env['product.product'].create({
            'name': 'Bàn phím',
            'default_code': 'T4_COMP_KB',
            'technical_categ_id': tc_kb.id,
            'categ_id': avco_categ.id,
            'is_storable': True,
            'tracking': 'none',
        })
        cls.comp_battery = cls.env['product.product'].create({
            'name': 'Pin',
            'default_code': 'T4_COMP_BAT',
            'technical_categ_id': tc_bat.id,
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
        tc_empty = self.env['product.category.technical'].create(
            {'name': 'Component Empty FG'})
        tmpl = self.env['product.template'].create({
            'name': 'Empty FG',
            'default_code': 'T4_COMP_EMPTY',
            'technical_categ_id': tc_empty.id,
            'tracking': 'serial',
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
