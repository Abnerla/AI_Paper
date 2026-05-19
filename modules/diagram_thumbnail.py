# -*- coding: utf-8 -*-
"""
图表缩略图生成。

P1 阶段使用 PIL 直接绘制节点/边的占位预览，无需 webview 截图。
后续阶段（P2/P3）可由 webview 渲染 mermaid SVG 后回传 base64 替换。
"""

from __future__ import annotations

import base64
import io
import math
import os
import uuid
from typing import Optional

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None
    ImageDraw = None
    ImageFont = None

from modules.diagram_blocks import THUMBNAIL_MAX_INLINE_BYTES
from modules.runtime_paths import resolve_data_path


_DEFAULT_THUMB_SIZE = (480, 300)
_NODE_COLORS = {
    'rect': ('#E3F2FD', '#1565C0'),
    'rounded': ('#E8F5E9', '#2E7D32'),
    'ellipse': ('#FFF3E0', '#EF6C00'),
    'diamond': ('#F3E5F5', '#6A1B9A'),
    'hexagon': ('#FFF8E1', '#F9A825'),
    'parallelogram': ('#E0F7FA', '#00838F'),
    'flag': ('#FCE4EC', '#AD1457'),
}


def render_placeholder_png(graph, *, caption='', size=_DEFAULT_THUMB_SIZE):
    """根据 json_graph 绘一张占位 PNG，返回 PIL Image 对象。"""
    if Image is None:
        return None

    width, height = size
    image = Image.new('RGB', (width, height), '#FAFAFA')
    draw = ImageDraw.Draw(image)

    nodes = (graph or {}).get('nodes') or []
    edges = (graph or {}).get('edges') or []
    layout_direction = ((graph or {}).get('meta') or {}).get('layout', 'TB').upper()

    if not nodes:
        _draw_empty_placeholder(draw, width, height, caption)
        return image

    positions = _layout_nodes(nodes, layout_direction, width, height)
    font = _load_font(13)
    small_font = _load_font(11)

    # 先画边
    for edge in edges:
        source_pos = positions.get(edge.get('source'))
        target_pos = positions.get(edge.get('target'))
        if not source_pos or not target_pos:
            continue
        sx, sy, sw, sh = source_pos
        tx, ty, tw, th = target_pos
        sx_center, sy_center = sx + sw / 2, sy + sh / 2
        tx_center, ty_center = tx + tw / 2, ty + th / 2
        line_color = '#90A4AE'
        dashed = bool(edge.get('dashed'))
        _draw_arrow(draw, sx_center, sy_center, tx_center, ty_center, line_color, dashed=dashed)
        label = (edge.get('label') or '').strip()
        if label:
            mid_x = (sx_center + tx_center) / 2
            mid_y = (sy_center + ty_center) / 2
            _draw_label(draw, mid_x, mid_y, label[:20], small_font, '#37474F', '#ECEFF1')

    # 再画节点
    for node in nodes:
        node_id = node.get('id')
        rect = positions.get(node_id)
        if not rect:
            continue
        x, y, w, h = rect
        shape = node.get('shape') or 'rect'
        fill, stroke = _NODE_COLORS.get(shape, _NODE_COLORS['rect'])
        _draw_shape(draw, shape, x, y, w, h, fill, stroke)
        label = (node.get('label') or node_id or '')[:12]
        _draw_centered_text(draw, x + w / 2, y + h / 2, label, font, '#212121')

    if caption:
        _draw_caption_overlay(draw, caption, width, height, small_font)

    return image


def render_placeholder_b64(graph, *, caption='', size=_DEFAULT_THUMB_SIZE):
    """生成占位 PNG 的 base64 (data: 前缀)。超过阈值返回 ('', '<外部路径>')。"""
    if Image is None:
        return '', ''

    image = render_placeholder_png(graph, caption=caption, size=size)
    if image is None:
        return '', ''
    buffer = io.BytesIO()
    image.save(buffer, format='PNG', optimize=True)
    raw = buffer.getvalue()
    encoded = base64.b64encode(raw).decode('ascii')
    data_uri = f'data:image/png;base64,{encoded}'
    if len(data_uri) > THUMBNAIL_MAX_INLINE_BYTES:
        external_path = _persist_thumbnail_to_disk(raw)
        return '', external_path
    return data_uri, ''


def _persist_thumbnail_to_disk(png_bytes):
    cache_dir = resolve_data_path('diagram_cache')
    os.makedirs(cache_dir, exist_ok=True)
    filename = f'{uuid.uuid4().hex}.png'
    full_path = os.path.join(cache_dir, filename)
    try:
        with open(full_path, 'wb') as handle:
            handle.write(png_bytes)
    except OSError:
        return ''
    return os.path.join('diagram_cache', filename)


def load_image_from_block(block):
    """从 block 的 thumbnail 字段还原 PIL Image。"""
    if Image is None or not isinstance(block, dict):
        return None
    b64 = block.get('thumbnail_b64')
    if b64:
        text = b64
        if text.startswith('data:'):
            _, _, text = text.partition(',')
        try:
            raw = base64.b64decode(text)
            return Image.open(io.BytesIO(raw)).convert('RGB')
        except (ValueError, OSError):
            pass
    path = block.get('thumbnail_path')
    if path:
        full_path = resolve_data_path(path)
        if os.path.exists(full_path):
            try:
                return Image.open(full_path).convert('RGB')
            except OSError:
                pass
    return None


def _layout_nodes(nodes, direction, canvas_width, canvas_height):
    """非常简化的网格布局：TB/BT 列优先；LR/RL 行优先。"""
    count = len(nodes)
    if count == 0:
        return {}

    margin = 24
    box_width = 96
    box_height = 40

    if direction in ('LR', 'RL'):
        cols = min(count, max(1, (canvas_width - margin * 2) // (box_width + 30)))
        rows = math.ceil(count / cols)
    else:
        rows = min(count, max(1, (canvas_height - margin * 2) // (box_height + 30)))
        cols = math.ceil(count / rows)

    available_w = canvas_width - margin * 2
    available_h = canvas_height - margin * 2
    spacing_x = (available_w - cols * box_width) / max(1, cols + 1)
    spacing_y = (available_h - rows * box_height) / max(1, rows + 1)

    positions = {}
    for index, node in enumerate(nodes):
        if direction in ('LR', 'RL'):
            row = index // cols
            col = index % cols
            if direction == 'RL':
                col = cols - 1 - col
        else:
            row = index % rows
            col = index // rows
        x = margin + spacing_x + col * (box_width + spacing_x)
        y = margin + spacing_y + row * (box_height + spacing_y)
        positions[node.get('id') or f'n{index}'] = (x, y, box_width, box_height)
    return positions


def _draw_shape(draw, shape, x, y, w, h, fill, stroke):
    if shape == 'ellipse':
        draw.ellipse([x, y, x + w, y + h], fill=fill, outline=stroke, width=2)
    elif shape == 'diamond':
        cx, cy = x + w / 2, y + h / 2
        draw.polygon([
            (cx, y), (x + w, cy), (cx, y + h), (x, cy)
        ], fill=fill, outline=stroke)
    elif shape == 'hexagon':
        offset = h / 4
        draw.polygon([
            (x + offset, y), (x + w - offset, y), (x + w, y + h / 2),
            (x + w - offset, y + h), (x + offset, y + h), (x, y + h / 2),
        ], fill=fill, outline=stroke)
    elif shape == 'parallelogram':
        offset = h / 3
        draw.polygon([
            (x + offset, y), (x + w, y),
            (x + w - offset, y + h), (x, y + h),
        ], fill=fill, outline=stroke)
    elif shape == 'rounded':
        draw.rounded_rectangle([x, y, x + w, y + h], radius=8, fill=fill, outline=stroke, width=2)
    else:
        draw.rectangle([x, y, x + w, y + h], fill=fill, outline=stroke, width=2)


def _draw_arrow(draw, x1, y1, x2, y2, color, *, dashed=False):
    if dashed:
        _draw_dashed_line(draw, x1, y1, x2, y2, color)
    else:
        draw.line([(x1, y1), (x2, y2)], fill=color, width=2)
    angle = math.atan2(y2 - y1, x2 - x1)
    arrow_len = 8
    ax1 = x2 - arrow_len * math.cos(angle - math.pi / 7)
    ay1 = y2 - arrow_len * math.sin(angle - math.pi / 7)
    ax2 = x2 - arrow_len * math.cos(angle + math.pi / 7)
    ay2 = y2 - arrow_len * math.sin(angle + math.pi / 7)
    draw.polygon([(x2, y2), (ax1, ay1), (ax2, ay2)], fill=color)


def _draw_dashed_line(draw, x1, y1, x2, y2, color):
    dx, dy = x2 - x1, y2 - y1
    distance = math.hypot(dx, dy) or 1
    dash, gap = 6, 4
    cursor = 0
    while cursor < distance:
        start_ratio = cursor / distance
        end_ratio = min(1.0, (cursor + dash) / distance)
        sx = x1 + dx * start_ratio
        sy = y1 + dy * start_ratio
        ex = x1 + dx * end_ratio
        ey = y1 + dy * end_ratio
        draw.line([(sx, sy), (ex, ey)], fill=color, width=2)
        cursor += dash + gap


def _draw_label(draw, x, y, text, font, color, bg):
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0] + 8
    height = bbox[3] - bbox[1] + 4
    draw.rectangle(
        [x - width / 2, y - height / 2, x + width / 2, y + height / 2],
        fill=bg, outline=None,
    )
    draw.text((x - (bbox[2] - bbox[0]) / 2, y - (bbox[3] - bbox[1]) / 2 - bbox[1]), text, font=font, fill=color)


def _draw_centered_text(draw, x, y, text, font, color):
    if not text:
        return
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    draw.text((x - text_w / 2, y - text_h / 2 - bbox[1]), text, font=font, fill=color)


def _draw_caption_overlay(draw, caption, width, height, font):
    text = (caption or '').strip()
    if not text:
        return
    text = text[:36]
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    pad = 6
    box = (8, height - text_h - pad * 2 - 8,
           text_w + pad * 2 + 8, height - 8)
    draw.rectangle(box, fill='#263238')
    draw.text((box[0] + pad, box[1] + pad - bbox[1]), text, font=font, fill='#ECEFF1')


def _draw_empty_placeholder(draw, width, height, caption):
    text = '图表预览'
    if caption:
        text = caption[:24]
    font = _load_font(16)
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.rectangle([20, 20, width - 20, height - 20], outline='#B0BEC5', width=2)
    draw.text(
        ((width - (bbox[2] - bbox[0])) / 2,
         (height - (bbox[3] - bbox[1])) / 2 - bbox[1]),
        text, font=font, fill='#455A64',
    )


_FONT_CACHE = {}


def _load_font(size):
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    font = None
    candidates = [
        'C:/Windows/Fonts/msyh.ttc',
        'C:/Windows/Fonts/msyh.ttf',
        '/System/Library/Fonts/PingFang.ttc',
        '/System/Library/Fonts/Helvetica.ttc',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, size)
                break
            except OSError:
                continue
    if font is None:
        try:
            font = ImageFont.load_default()
        except OSError:
            font = None
    _FONT_CACHE[size] = font
    return font
