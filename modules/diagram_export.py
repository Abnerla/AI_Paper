# -*- coding: utf-8 -*-
"""AI 图表导出工具。"""

from __future__ import annotations

import base64
import io
import os
import re
import urllib.parse
from xml.sax.saxutils import escape

from modules.diagram_thumbnail import load_image_from_block, render_placeholder_png


class DiagramExportError(ValueError):
    """图表导出失败。"""


def safe_diagram_filename(title):
    text = re.sub(r'[\\/:*?"<>|\s]+', '_', str(title or '').strip())
    return text.strip('_')[:60] or 'diagram'


def detect_export_format(path):
    lower = str(path or '').lower()
    if lower.endswith('.drawio.svg'):
        return 'drawio.svg'
    ext = os.path.splitext(lower)[1]
    if ext == '.drawio':
        return 'drawio'
    if ext == '.xml':
        return 'xml'
    if ext == '.svg':
        return 'svg'
    if ext == '.png':
        return 'png'
    return ''


def export_diagram_file(path, xml_text, *, block=None, native_exporter=None):
    fmt = detect_export_format(path)
    if not fmt:
        raise DiagramExportError('不支持的导出格式。')

    if fmt in {'drawio', 'xml'}:
        with open(path, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(str(xml_text or ''))
        return {'format': fmt, 'path': path, 'note': '已导出 draw.io XML。'}

    if fmt in {'png', 'svg', 'drawio.svg'} and callable(native_exporter):
        native = native_exporter(fmt)
        if isinstance(native, dict) and native.get('data'):
            _write_native_export(path, native.get('data'), fmt)
            return {'format': fmt, 'path': path, 'note': f'已导出 draw.io 原生 {fmt.upper()}。'}

    if fmt == 'png':
        png_bytes = render_preview_png_bytes(block)
        with open(path, 'wb') as handle:
            handle.write(png_bytes)
        return {'format': fmt, 'path': path, 'note': '已导出当前图表预览 PNG。'}

    if fmt in {'svg', 'drawio.svg'}:
        svg = render_preview_svg(block, xml_text=str(xml_text or ''), include_drawio_metadata=(fmt == 'drawio.svg'))
        with open(path, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(svg)
        note = '已导出当前图表预览 SVG。'
        if fmt == 'drawio.svg':
            note = '已导出带 draw.io XML 元数据的预览 SVG。'
        return {'format': fmt, 'path': path, 'note': note}

    raise DiagramExportError('不支持的导出格式。')


def _write_native_export(path, data, fmt):
    text = str(data or '').strip()
    if not text:
        raise DiagramExportError('draw.io 原生导出结果为空。')
    if fmt == 'png':
        if text.startswith('data:'):
            payload = text.split(',', 1)[1] if ',' in text else ''
            raw = base64.b64decode(payload)
        else:
            raw = base64.b64decode(text)
        with open(path, 'wb') as handle:
            handle.write(raw)
        return

    if text.startswith('data:'):
        header, payload = text.split(',', 1) if ',' in text else ('', '')
        if ';base64' in header:
            text = base64.b64decode(payload).decode('utf-8', errors='replace')
        else:
            text = urllib.parse.unquote(payload)
    with open(path, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(text)


def render_preview_png_bytes(block, *, size=(1200, 720)):
    image = load_image_from_block(block or {})
    if image is None:
        graph = (block or {}).get('json_graph') if isinstance(block, dict) else {}
        image = render_placeholder_png(graph or {}, caption=(block or {}).get('caption', ''), size=size)
    if image is None:
        raise DiagramExportError('当前环境缺少 PNG 预览渲染能力。')
    buffer = io.BytesIO()
    image.save(buffer, format='PNG', optimize=True)
    return buffer.getvalue()


def render_preview_svg(block, *, xml_text='', include_drawio_metadata=False, size=(1200, 720)):
    png_bytes = render_preview_png_bytes(block, size=size)
    encoded = base64.b64encode(png_bytes).decode('ascii')
    width, height = size
    caption = escape(str((block or {}).get('caption') or 'AI 图表'))
    desc = '由当前图表预览生成，非 draw.io 原生渲染。'
    metadata = ''
    if include_drawio_metadata and xml_text:
        metadata = f'\n  <metadata><mxfile>{escape(xml_text)}</mxfile></metadata>'
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{caption}">\n'
        f'  <title>{caption}</title>\n'
        f'  <desc>{escape(desc)}</desc>{metadata}\n'
        f'  <image width="{width}" height="{height}" href="data:image/png;base64,{encoded}" />\n'
        f'</svg>\n'
    )
