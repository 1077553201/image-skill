"""Typography preflight and diagnostic overlays; no model calls are made."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import typography


FONT = next((path for path in [Path('C:/Windows/Fonts/msyh.ttc'),
                              Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]
             if path.is_file()), None)


class TypographyTests(unittest.TestCase):
    def setUp(self):
        if FONT is None:
            self.skipTest('No test font installed')
        configured = os.environ.get('DETAIL_SKILL_TEST_ROOT')
        temp_root = (Path(configured) if configured else
                     Path(__file__).resolve().parents[3] / 'reports' / 'detail_page_validation' / 'tmp')
        temp_root = temp_root.resolve()
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='typography-test-', dir=temp_root)
        self.root = Path(self.temp.name).resolve()
        def cleanup():
            if self.root.parent != temp_root or not self.root.name.startswith('typography-test-'):
                raise ValueError('Refusing cleanup outside the isolated test workspace')
            self.temp.cleanup()
        self.addCleanup(cleanup)
        self.base = self.root / 'base.png'
        Image.new('RGB', (400, 240), 'white').save(self.base)
        self.layout = {'canvas': [400, 240], 'protected_regions': [[0, 120, 400, 120]],
                       'text_blocks': [{'text': 'Approved text', 'font': 'approved-font',
                                        'size': 24, 'color': '#102030', 'box': [20, 20, 360, 80]}]}

    def resolve_font(self, name):
        self.assertEqual(name, 'approved-font')
        return FONT

    def check(self, layout=None):
        return typography.preflight(layout if layout is not None else self.layout, self.resolve_font)

    def test_preflight_without_image_preserves_approved_data(self):
        before = copy.deepcopy(self.layout)
        self.base.unlink()
        report = self.check()
        self.assertEqual(report['status'], 'layout_preflight_passed')
        self.assertEqual(report['blocks'][0]['text'], 'Approved text')
        self.assertEqual(report['blocks'][0]['size'], 24)
        self.assertTrue(report['glyph_coverage_checked'])
        self.assertFalse(report['text_rewritten'])
        self.assertFalse(report['font_size_changed'])
        self.assertFalse(report['actual_product_detected'])
        self.assertEqual(report['safe_margin'], 0)
        self.assertEqual(self.layout, before)
        json.dumps(report)

    def test_canvas_requires_positive_integer_dimensions(self):
        for size in [None, [], [400], [400, 240, 1], [0, 240], [-1, 240],
                     [True, 240], [400.0, 240], ['400', 240]]:
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, 'positive integer'):
                self.check({**self.layout, 'canvas': size})

    def test_product_region_or_explicit_no_product_reason_is_required(self):
        for regions in [None, []]:
            layout = copy.deepcopy(self.layout)
            if regions is None:
                layout.pop('protected_regions')
            else:
                layout['protected_regions'] = regions
            with self.subTest(regions=regions), self.assertRaisesRegex(ValueError, 'no_product_reason'):
                self.check(layout)
        layout = {**self.layout, 'protected_regions': [],
                  'no_product_reason': 'This page has only an approved infographic; no product is pictured.'}
        report = self.check(layout)
        self.assertEqual(report['protected_regions'], [])
        self.assertEqual(report['no_product_reason'], layout['no_product_reason'])

    def test_no_product_reason_cannot_be_empty_or_nontext(self):
        for reason in ['', '  ', 123, False]:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, 'reason'):
                self.check({**self.layout, 'protected_regions': [], 'no_product_reason': reason})

    def test_rectangles_must_be_finite_and_within_canvas(self):
        for box in [[20, 20, 400, 80], [-1, 0, 10, 10], [20, 20, 0, 10],
                    [20, float('nan'), 30, 10], [0, 0, True, 10], [0, 0, 30]]:
            layout = copy.deepcopy(self.layout)
            layout['text_blocks'][0]['box'] = box
            with self.subTest(box=box), self.assertRaises(ValueError):
                self.check(layout)

    def test_text_cannot_overlap_product_or_another_text_box(self):
        layout = copy.deepcopy(self.layout)
        layout['text_blocks'][0]['box'] = [20, 130, 360, 80]
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            self.check(layout)
        layout = copy.deepcopy(self.layout)
        layout['text_blocks'].append({**layout['text_blocks'][0], 'text': 'Second block'})
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            self.check(layout)

    def test_overflow_is_rejected_before_an_image_exists(self):
        layout = copy.deepcopy(self.layout)
        layout['text_blocks'][0]['box'] = [20, 20, 12, 12]
        self.base.unlink()
        with self.assertRaisesRegex(ValueError, 'never truncate'):
            self.check(layout)

    def test_font_missing_glyph_is_rejected_in_preflight(self):
        layout = copy.deepcopy(self.layout)
        layout['text_blocks'][0]['text'] = '\U0010ffff'
        with self.assertRaisesRegex(ValueError, 'missing characters'):
            self.check(layout)

    def test_invalid_text_font_and_font_size_are_rejected(self):
        for change in [{'text': ''}, {'text': '  '}, {'text': None}, {'font': ''},
                       {'size': 0}, {'size': 24.0}, {'size': True}]:
            layout = copy.deepcopy(self.layout)
            layout['text_blocks'][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.check(layout)

    def test_colors_are_validated_before_generation(self):
        for field in ['color', 'background']:
            for value in ['not-a-color', '#12345', [0, 0, 256], [True, 0, 0], [0, 0], '#ffffff00']:
                layout = copy.deepcopy(self.layout)
                layout['text_blocks'][0][field] = value
                with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, 'color|RGB'):
                    self.check(layout)
        layout = copy.deepcopy(self.layout)
        layout['text_blocks'][0].update(color=[10, 20, 30], background='white')
        report = self.check(layout)
        self.assertEqual(report['blocks'][0]['color'], [10, 20, 30])
        self.assertEqual(report['blocks'][0]['background'], [255, 255, 255])

    def test_alignment_and_line_spacing_are_validated(self):
        for change in [{'align': 'justify'}, {'spacing': -1}, {'spacing': float('inf')},
                       {'spacing': True}, {'spacing': '4'}]:
            layout = copy.deepcopy(self.layout)
            layout['text_blocks'][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.check(layout)
        for align in ['left', 'center', 'right']:
            layout = copy.deepcopy(self.layout)
            layout['text_blocks'][0].update(text='First\nSecond', align=align, spacing=7)
            self.assertEqual(self.check(layout)['blocks'][0]['align'], align)

    def test_safe_margin_applies_to_text_not_intentional_product_bleed(self):
        self.check({**self.layout, 'safe_margin': 10})
        for margin in [-1, 21, 120, True, float('inf')]:
            with self.subTest(margin=margin), self.assertRaises(ValueError):
                self.check({**self.layout, 'safe_margin': margin})

    def test_render_reuses_preflight_and_keeps_source_unchanged(self):
        original = self.base.read_bytes()
        output = self.root / 'render.png'
        report = typography.render(self.base, self.layout, output, self.resolve_font)
        self.assertEqual(report['status'], 'rendered_pending_visual_review')
        self.assertEqual(report['blocks'][0]['text'], 'Approved text')
        self.assertEqual(self.base.read_bytes(), original)
        with Image.open(output) as image:
            self.assertEqual(image.size, (400, 240))
            self.assertEqual(image.getpixel((200, 180)), (255, 255, 255))
        with self.assertRaises(FileExistsError):
            typography.render(self.base, self.layout, output, self.resolve_font)
        invalid = copy.deepcopy(self.layout)
        invalid['text_blocks'][0]['box'] = [20, 20, 10, 10]
        with self.assertRaisesRegex(ValueError, 'never truncate'):
            typography.render(self.base, invalid, self.root / 'invalid.png', self.resolve_font)
        self.assertFalse((self.root / 'invalid.png').exists())

    def test_overlay_draws_declared_boxes_without_altering_source(self):
        original = self.base.read_bytes()
        output = self.root / 'inspection.png'
        report = typography.inspection_overlay(self.base, {**self.layout, 'safe_margin': 10},
                                               output, self.resolve_font)
        self.assertEqual(report['status'], 'inspection_overlay_pending_visual_review')
        self.assertTrue(report['overlay_only'])
        self.assertFalse(report['actual_product_detected'])
        self.assertEqual(self.base.read_bytes(), original)
        with Image.open(output) as image:
            self.assertEqual(image.size, (400, 240))
            self.assertEqual(image.getpixel((10, 10)), (184, 121, 0))
            self.assertEqual(image.getpixel((20, 20)), (18, 101, 214))
            self.assertEqual(image.getpixel((0, 120)), (209, 34, 34))
            self.assertEqual(image.getpixel((200, 180)), (255, 255, 255))

    def test_overlay_output_cannot_overwrite_any_existing_image(self):
        original = self.base.read_bytes()
        with self.assertRaises(FileExistsError):
            typography.inspection_overlay(self.base, self.layout, self.base, self.resolve_font)
        self.assertEqual(self.base.read_bytes(), original)
        output = self.root / 'existing.png'
        output.write_bytes(b'existing output')
        with self.assertRaises(FileExistsError):
            typography.inspection_overlay(self.base, self.layout, output, self.resolve_font)
        self.assertEqual(output.read_bytes(), b'existing output')

    def test_render_and_overlay_require_actual_image_dimensions(self):
        wrong = self.root / 'wrong.png'
        Image.new('RGB', (401, 240), 'white').save(wrong)
        for operation in [typography.render, typography.inspection_overlay]:
            output = self.root / (operation.__name__ + '-wrong.png')
            with self.subTest(operation=operation.__name__), self.assertRaisesRegex(ValueError, 'match'):
                operation(wrong, self.layout, output, self.resolve_font)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
