"""Deterministic typography. Only Pillow and the Python standard library are used."""
from __future__ import annotations

import math
from pathlib import Path
import struct

from PIL import Image, ImageDraw, ImageFont


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


def render(base: Path, layout: dict, output: Path, resolve_font) -> dict:
    """Draw exact strings, without truncation, wrapping, shrinking or AI rewriting."""
    with Image.open(base) as opened:
        canvas = opened.convert('RGB')
    width, height = canvas.size
    if layout['canvas'] != [width, height]:
        raise ValueError('Layout canvas must match the generated image exactly')
    protected = [rectangle(box, width, height) for box in layout.get('protected_regions', [])]
    draw = ImageDraw.Draw(canvas)
    boxes, reports, cmaps = [], [], {}
    for item in layout['text_blocks']:
        text = item['text']
        if not isinstance(text, str) or not text.strip():
            raise ValueError('Text block must contain approved nonempty text')
        box = rectangle(item['box'], width, height)
        if any(overlaps(box, other) for other in boxes + protected):
            raise ValueError('Text box overlaps another block or a protected product region')
        font_path = resolve_font(item['font'])
        if font_path not in cmaps:
            cmaps[font_path] = font_codepoints(font_path)
        missing = sorted({ch for ch in text if ch not in '\n\r\t' and ord(ch) not in cmaps[font_path]})
        if missing:
            raise ValueError('Font is missing characters: ' + ''.join(missing))
        size = item['size']
        if type(size) is not int or size <= 0:
            raise ValueError('Font size must be a positive integer')
        font = ImageFont.truetype(str(font_path), size)
        spacing = number(item.get('spacing', 4))
        if spacing < 0:
            raise ValueError('Line spacing must not be negative')
        align = item.get('align', 'left')
        if align not in ('left', 'center', 'right'):
            raise ValueError('Unsupported alignment')
        bounds = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing, align=align)
        ink_w, ink_h = bounds[2] - bounds[0], bounds[3] - bounds[1]
        x, y, w, h = box
        if ink_w > w or ink_h > h:
            raise ValueError('Approved text does not fit; revise the layout, never truncate it')
        x += {'left': 0, 'center': (w - ink_w) / 2, 'right': w - ink_w}[align]
        if item.get('background'):
            draw.rectangle((box[0], box[1], box[0] + w - 1, box[1] + h - 1), fill=item['background'])
        draw.multiline_text((x - bounds[0], y - bounds[1]), text, font=font,
                            fill=item['color'], spacing=spacing, align=align)
        boxes.append(box)
        reports.append({'text': text, 'font': item['font'], 'box': list(box), 'fits': True})
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        canvas.save(stream, format='PNG')
    return {'status': 'rendered_pending_visual_review', 'text_rewritten': False,
            'glyph_coverage_checked': True, 'blocks': reports, 'canvas': [width, height]}
