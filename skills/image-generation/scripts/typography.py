"""Deterministic typography. Only Pillow and the Python standard library are used."""
from __future__ import annotations

import math
from pathlib import Path
import struct

from PIL import Image, ImageColor, ImageDraw, ImageFont


def font_codepoints(path: Path) -> set[int]:
    """Read Unicode cmaps (4/12) from a TTF, OTF or the first face of a TTC."""
    data = path.read_bytes()
    u16 = lambda pos: struct.unpack_from('>H', data, pos)[0]
    u32 = lambda pos: struct.unpack_from('>I', data, pos)[0]
    start = u32(12) if data[:4] == b'ttcf' else 0
    tables = {data[pos:pos + 4]: u32(pos + 8)
              for pos in range(start + 12, start + 12 + 16 * u16(start + 4), 16)}
    cmap = tables[b'cmap']
    covered = set()
    for rec in range(cmap + 4, cmap + 4 + 8 * u16(cmap + 2), 8):
        platform, encoding = u16(rec), u16(rec + 2)
        if platform != 0 and (platform != 3 or encoding not in (1, 10)):
            continue
        pos = cmap + u32(rec + 4)
        form = u16(pos)
        if form == 12:
            for group in range(pos + 16, pos + 16 + 12 * u32(pos + 12), 12):
                first, last, glyph = u32(group), u32(group + 4), u32(group + 8)
                if last > 0x10ffff:
                    raise ValueError('Invalid font Unicode range')
                covered.update(range(first + (glyph == 0), last + 1))
        elif form == 4:
            count = u16(pos + 6) // 2
            ends = pos + 14
            starts, deltas, offsets = ends + 2 * count + 2, ends + 4 * count + 2, ends + 6 * count + 2
            for index in range(count):
                first, last = u16(starts + 2 * index), u16(ends + 2 * index)
                delta, offset = u16(deltas + 2 * index), u16(offsets + 2 * index)
                for char in range(first, min(last + 1, 0xffff)):
                    glyph = u16(offsets + 2 * index + offset + 2 * (char - first)) if offset else char
                    if glyph and ((glyph + delta) & 0xffff):
                        covered.add(char)
    if not covered:
        raise ValueError('Font has no supported Unicode cmap')
    return covered


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('Layout coordinates must be finite numbers')
    return value


def rectangle(value, width, height):
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError('Expected [x, y, width, height]')
    x, y, w, h = map(number, value)
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
        raise ValueError('Rectangle exceeds canvas')
    return x, y, w, h


def overlaps(a, b):
    x, y, w, h = a
    xx, yy, ww, hh = b
    return x < xx + ww and xx < x + w and y < yy + hh and yy < y + h


def color(value):
    """Validate an opaque RGB color before generation or drawing starts."""
    if isinstance(value, str):
        try:
            rgb = ImageColor.getrgb(value)
        except (ValueError, TypeError) as error:
            raise ValueError('Invalid typography color') from error
    elif isinstance(value, (list, tuple)):
        rgb = value
    else:
        raise ValueError('Typography color must be a color string or RGB triplet')
    if len(rgb) != 3 or any(type(part) is not int or not 0 <= part <= 255 for part in rgb):
        raise ValueError('Typography color must be opaque RGB with values from 0 to 255')
    return list(rgb)


def preflight(layout: dict, resolve_font) -> dict:
    """Check exact approved text and declared coordinates, without an image.

    This checks layout data, not the position or identity of an actual product.
    A later overlay and visual review must compare these coordinates to the image.
    Safe margins apply to text boxes; product regions may intentionally bleed.
    """
    if not isinstance(layout, dict):
        raise ValueError('Layout must be an object')
    size = layout.get('canvas')
    if (not isinstance(size, list) or len(size) != 2
            or any(type(value) is not int or value <= 0 for value in size)):
        raise ValueError('Canvas must contain two positive integer dimensions')
    width, height = size
    margin = number(layout.get('safe_margin', 0))
    if margin < 0 or 2 * margin >= min(width, height):
        raise ValueError('Safe margin must leave a positive usable canvas')
    regions = layout.get('protected_regions', [])
    if not isinstance(regions, list):
        raise ValueError('Protected regions must be a list of rectangles')
    reason = layout.get('no_product_reason')
    if reason is not None and (not isinstance(reason, str) or not reason.strip()):
        raise ValueError('No-product reason must be nonempty text')
    if not regions and reason is None:
        raise ValueError('Declare protected product regions or an explicit no_product_reason')
    protected = [rectangle(box, width, height) for box in regions]
    items = layout.get('text_blocks')
    if not isinstance(items, list):
        raise ValueError('Text blocks must be a list')
    draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    boxes, reports, cmaps = [], [], {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('Text block must be an object')
        text = item.get('text')
        if not isinstance(text, str) or not text.strip():
            raise ValueError('Text block must contain approved nonempty text')
        box = rectangle(item.get('box'), width, height)
        x, y, w, h = box
        if x < margin or y < margin or x + w > width - margin or y + h > height - margin:
            raise ValueError('Text box exceeds the declared safe margin')
        if any(overlaps(box, other) for other in boxes + protected):
            raise ValueError('Text box overlaps another block or a protected product region')
        if not isinstance(item.get('font'), str) or not item['font'].strip():
            raise ValueError('Text block must identify its approved font')
        font_path = Path(resolve_font(item['font']))
        if font_path not in cmaps:
            cmaps[font_path] = font_codepoints(font_path)
        missing = sorted({ch for ch in text if ch not in '\n\r\t' and ord(ch) not in cmaps[font_path]})
        if missing:
            raise ValueError('Font is missing characters: ' + ''.join(missing))
        size = item.get('size')
        if type(size) is not int or size <= 0:
            raise ValueError('Font size must be a positive integer')
        font = ImageFont.truetype(str(font_path), size)
        spacing = number(item.get('spacing', 4))
        if spacing < 0:
            raise ValueError('Line spacing must not be negative')
        align = item.get('align', 'left')
        if align not in ('left', 'center', 'right'):
            raise ValueError('Unsupported alignment')
        foreground = color(item.get('color'))
        background = color(item['background']) if 'background' in item else None
        bounds = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing, align=align)
        ink_w, ink_h = bounds[2] - bounds[0], bounds[3] - bounds[1]
        if ink_w > w or ink_h > h:
            raise ValueError('Approved text does not fit; revise the layout, never truncate it')
        boxes.append(box)
        reports.append({'text': text, 'font': item['font'], 'size': size,
                        'box': list(box), 'ink_bounds': list(bounds), 'fits': True,
                        'align': align, 'spacing': spacing, 'color': foreground,
                        'background': background})
    return {'status': 'layout_preflight_passed', 'text_rewritten': False,
            'font_size_changed': False, 'glyph_coverage_checked': True,
            'actual_product_detected': False, 'canvas': [width, height],
            'safe_margin': margin, 'protected_regions': [list(box) for box in protected],
            'no_product_reason': reason, 'blocks': reports}


def _base_canvas(base: Path, report: dict):
    with Image.open(base) as opened:
        if list(opened.size) != report['canvas']:
            raise ValueError('Layout canvas must match the generated image exactly')
        return opened.convert('RGB')


def _save_new(canvas, output: Path):
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        canvas.save(stream, format='PNG')


def render(base: Path, layout: dict, output: Path, resolve_font) -> dict:
    """Draw exact strings, without truncation, wrapping, shrinking or AI rewriting."""
    report = preflight(layout, resolve_font)
    canvas = _base_canvas(base, report)
    draw = ImageDraw.Draw(canvas)
    for item in report['blocks']:
        x, y, w, h = item['box']
        bounds = item['ink_bounds']
        ink_w = bounds[2] - bounds[0]
        text_x = x + {'left': 0, 'center': (w - ink_w) / 2, 'right': w - ink_w}[item['align']]
        if item['background'] is not None:
            draw.rectangle((x, y, x + w - 1, y + h - 1), fill=tuple(item['background']))
        font = ImageFont.truetype(str(resolve_font(item['font'])), item['size'])
        draw.multiline_text((text_x - bounds[0], y - bounds[1]), item['text'], font=font,
                            fill=tuple(item['color']), spacing=item['spacing'], align=item['align'])
    _save_new(canvas, output)
    return {**report, 'status': 'rendered_pending_visual_review'}


def inspection_overlay(base: Path, layout: dict, output: Path, resolve_font) -> dict:
    """Draw declared regions over a copy, for an agent to inspect visually.

    T1, T2... are text boxes; P1, P2... are product protection boxes. The gold
    rectangle is the safe text area. No image segmentation or detection occurs.
    """
    report = preflight(layout, resolve_font)
    canvas = _base_canvas(base, report)
    draw = ImageDraw.Draw(canvas)
    width, height = canvas.size
    margin = report['safe_margin']
    draw.rectangle((margin, margin, width - margin - 1, height - margin - 1),
                   outline='#b87900', width=2)
    label_font = ImageFont.load_default()
    for prefix, boxes, stroke in (
            ('P', report['protected_regions'], '#d12222'),
            ('T', [block['box'] for block in report['blocks']], '#1265d6')):
        for index, (x, y, w, h) in enumerate(boxes, 1):
            draw.rectangle((x, y, x + w - 1, y + h - 1), outline=stroke, width=2)
            label = prefix + str(index)
            bounds = draw.textbbox((x + 2, y + 2), label, font=label_font)
            draw.rectangle(bounds, fill='white')
            draw.text((x + 2, y + 2), label, fill=stroke, font=label_font)
    _save_new(canvas, output)
    return {**report, 'status': 'inspection_overlay_pending_visual_review',
            'output': str(output), 'overlay_only': True,
            'legend': {'T': 'declared text box', 'P': 'declared product protection box',
                       'gold': 'safe text area'}}
