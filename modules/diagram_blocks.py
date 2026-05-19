# -*- coding: utf-8 -*-
"""
图表块（diagram block）数据模型与序列化工具。

与 table_blocks.py 同风格：提供 new_diagram_block / sanitize_diagram_block
两个对外入口，约束 block 字段并处理缩略图大小限制。
"""

from __future__ import annotations

import copy
import re
import time
import uuid


DIAGRAM_FORMAT_MERMAID = 'mermaid'
DIAGRAM_FORMAT_DRAWIO = 'drawio'
DIAGRAM_AUTHORING_FORMATS = {DIAGRAM_FORMAT_MERMAID, DIAGRAM_FORMAT_DRAWIO}

DIAGRAM_KIND_DEFAULT = 'flowchart'
DIAGRAM_KIND_ALIASES = {
    '': DIAGRAM_KIND_DEFAULT,
    'graph': 'flowchart',
    'flow': 'flowchart',
    'flowchart': 'flowchart',
    'sequence': 'sequence',
    'sequencediagram': 'sequence',
    'class': 'classDiagram',
    'classdiagram': 'classDiagram',
    'state': 'stateDiagram',
    'statediagram': 'stateDiagram',
    'er': 'erDiagram',
    'erdiagram': 'erDiagram',
    'mindmap': 'mindmap',
    'gantt': 'gantt',
    'journey': 'journey',
    'pie': 'pie',
    'quadrant': 'quadrant',
    'timeline': 'timeline',
    'c4': 'c4',
    'freeform': 'freeform',
}

# 缩略图 base64 内嵌上限，超出后写文件由调用方处理
THUMBNAIL_MAX_INLINE_BYTES = 200 * 1024
HISTORY_MAX_LEN = 10
DISPLAY_SIZE_DEFAULT = {'w': 520, 'h': 300}
DISPLAY_SIZE_MIN_W = 260
DISPLAY_SIZE_MIN_H = 180
DISPLAY_SIZE_MAX_W = 1400
DISPLAY_SIZE_MAX_H = 1000

# 节点/边样式键白名单，防止把任意 CSS/HTML 注入到 mxGraph 字符串里
_STYLE_ALLOWED_KEYS = {
    'fill', 'stroke', 'strokeWidth', 'strokeDasharray',
    'fontSize', 'fontFamily', 'fontColor', 'fontWeight', 'fontStyle',
    'rounded', 'shape', 'arrow', 'arrowStart', 'arrowEnd',
    'opacity', 'shadow', 'dashed', 'verticalAlign', 'align',
    'whiteSpace', 'html',
}

_ID_SAFE_RE = re.compile(r'[^A-Za-z0-9_\-]+')


def _normalize_text(value):
    return str(value or '').replace('\r\n', '\n').replace('\r', '\n')


def _normalize_caption(value):
    text = _normalize_text(value).strip()
    return re.sub(r'\s+', ' ', text)[:240]


def _normalize_kind(value):
    raw = str(value or '').strip()
    key = raw.lower()
    if key in DIAGRAM_KIND_ALIASES:
        return DIAGRAM_KIND_ALIASES[key]
    return raw or DIAGRAM_KIND_DEFAULT


def _normalize_authoring_format(value):
    text = str(value or '').strip().lower()
    if text in DIAGRAM_AUTHORING_FORMATS:
        return text
    return DIAGRAM_FORMAT_MERMAID


def _safe_id(value, fallback_prefix='n'):
    raw = str(value or '').strip()
    if not raw:
        return f'{fallback_prefix}_{uuid.uuid4().hex[:8]}'
    cleaned = _ID_SAFE_RE.sub('_', raw).strip('_')
    if not cleaned:
        return f'{fallback_prefix}_{uuid.uuid4().hex[:8]}'
    return cleaned[:64]


def _filter_style(style):
    if not isinstance(style, dict):
        return {}
    cleaned = {}
    for key, value in style.items():
        key_str = str(key or '').strip()
        if key_str not in _STYLE_ALLOWED_KEYS:
            continue
        if isinstance(value, bool):
            cleaned[key_str] = bool(value)
        elif isinstance(value, (int, float)):
            cleaned[key_str] = value
        else:
            text = str(value or '').strip()
            if text:
                cleaned[key_str] = text[:80]
    return cleaned


def _normalize_number(value, default=None):
    if value is None or value == '':
        return default
    try:
        num = float(value)
    except (TypeError, ValueError):
        return default
    if num != num or num in (float('inf'), float('-inf')):
        return default
    return num


def _normalize_node(node, used_ids):
    if not isinstance(node, dict):
        return None
    raw_id = node.get('id', '')
    node_id = _safe_id(raw_id, fallback_prefix='n')
    while node_id in used_ids:
        node_id = f'n_{uuid.uuid4().hex[:8]}'
    used_ids.add(node_id)
    label = _normalize_text(node.get('label', '')).strip()[:240]
    shape = str(node.get('shape', '') or '').strip().lower()[:32]
    cleaned = {
        'id': node_id,
        'label': label,
        'shape': shape or 'rect',
    }
    for key in ('x', 'y', 'width', 'height'):
        num = _normalize_number(node.get(key))
        if num is not None:
            cleaned[key] = num
    cleaned['style'] = _filter_style(node.get('style'))
    metadata = node.get('metadata')
    if isinstance(metadata, dict):
        meta_clean = {}
        for k, v in metadata.items():
            key_str = str(k or '').strip()[:40]
            if not key_str:
                continue
            meta_clean[key_str] = _normalize_text(v)[:200]
        if meta_clean:
            cleaned['metadata'] = meta_clean
    return cleaned


def _normalize_edge(edge, node_ids, used_ids):
    if not isinstance(edge, dict):
        return None
    source = _safe_id(edge.get('source', ''), fallback_prefix='n')
    target = _safe_id(edge.get('target', ''), fallback_prefix='n')
    if source not in node_ids or target not in node_ids:
        return None
    edge_id = _safe_id(edge.get('id', ''), fallback_prefix='e')
    while edge_id in used_ids:
        edge_id = f'e_{uuid.uuid4().hex[:8]}'
    used_ids.add(edge_id)
    cleaned = {
        'id': edge_id,
        'source': source,
        'target': target,
        'label': _normalize_text(edge.get('label', '')).strip()[:200],
        'arrow': str(edge.get('arrow', '') or '').strip().lower()[:32] or 'classic',
        'dashed': bool(edge.get('dashed', False)),
        'style': _filter_style(edge.get('style')),
    }
    waypoints = edge.get('waypoints')
    if isinstance(waypoints, list):
        cleaned_points = []
        for point in waypoints[:32]:
            if not isinstance(point, dict):
                continue
            x = _normalize_number(point.get('x'))
            y = _normalize_number(point.get('y'))
            if x is None or y is None:
                continue
            cleaned_points.append({'x': x, 'y': y})
        if cleaned_points:
            cleaned['waypoints'] = cleaned_points
    return cleaned


def _normalize_group(group, node_ids, used_ids):
    if not isinstance(group, dict):
        return None
    raw_id = group.get('id', '')
    group_id = _safe_id(raw_id, fallback_prefix='g')
    while group_id in used_ids:
        group_id = f'g_{uuid.uuid4().hex[:8]}'
    used_ids.add(group_id)
    children_raw = group.get('children')
    children = []
    if isinstance(children_raw, list):
        for child in children_raw:
            child_id = _safe_id(child, fallback_prefix='n')
            if child_id in node_ids:
                children.append(child_id)
    cleaned = {
        'id': group_id,
        'label': _normalize_text(group.get('label', '')).strip()[:200],
        'children': children,
    }
    for key in ('x', 'y', 'width', 'height'):
        num = _normalize_number(group.get(key))
        if num is not None:
            cleaned[key] = num
    return cleaned


def _normalize_meta(meta):
    if not isinstance(meta, dict):
        return {}
    cleaned = {}
    layout = str(meta.get('layout', '') or '').strip().upper()
    if layout in ('TB', 'BT', 'LR', 'RL', 'TD'):
        cleaned['layout'] = 'TB' if layout == 'TD' else layout
    theme = str(meta.get('theme', '') or '').strip().lower()
    if theme in ('default', 'dark', 'forest', 'neutral', 'base'):
        cleaned['theme'] = theme
    page_size = meta.get('page_size')
    if isinstance(page_size, dict):
        w = _normalize_number(page_size.get('width'))
        h = _normalize_number(page_size.get('height'))
        if w and h:
            cleaned['page_size'] = {'width': w, 'height': h}
    return cleaned


def _normalize_json_graph(graph):
    if not isinstance(graph, dict):
        return {'nodes': [], 'edges': [], 'groups': [], 'meta': {}}
    used_ids = set()
    nodes = []
    raw_nodes = graph.get('nodes')
    if isinstance(raw_nodes, list):
        for node in raw_nodes:
            normalized = _normalize_node(node, used_ids)
            if normalized:
                nodes.append(normalized)
    node_ids = {node['id'] for node in nodes}

    edges = []
    raw_edges = graph.get('edges')
    if isinstance(raw_edges, list):
        for edge in raw_edges:
            normalized = _normalize_edge(edge, node_ids, used_ids)
            if normalized:
                edges.append(normalized)

    groups = []
    raw_groups = graph.get('groups')
    if isinstance(raw_groups, list):
        for group in raw_groups:
            normalized = _normalize_group(group, node_ids, used_ids)
            if normalized:
                groups.append(normalized)

    return {
        'nodes': nodes,
        'edges': edges,
        'groups': groups,
        'meta': _normalize_meta(graph.get('meta')),
    }


def _normalize_thumbnail_b64(value):
    if not value:
        return ''
    text = str(value).strip()
    if not text:
        return ''
    # 仅接受 data:image/... 或纯 base64；超长截断为空，让上层另外写盘
    if len(text) > THUMBNAIL_MAX_INLINE_BYTES:
        return ''
    return text


def _normalize_thumbnail_path(value):
    text = _normalize_text(value).strip()
    return text[:512]


def _normalize_thumbnail_size(value):
    if not isinstance(value, dict):
        return {'w': 480, 'h': 300}
    w = _normalize_number(value.get('w'), default=480)
    h = _normalize_number(value.get('h'), default=300)
    return {'w': max(64, int(w or 480)), 'h': max(48, int(h or 300))}


def _normalize_display_size(value):
    if not isinstance(value, dict):
        return dict(DISPLAY_SIZE_DEFAULT)
    w = _normalize_number(value.get('w', value.get('width')), default=DISPLAY_SIZE_DEFAULT['w'])
    h = _normalize_number(value.get('h', value.get('height')), default=DISPLAY_SIZE_DEFAULT['h'])
    width = max(DISPLAY_SIZE_MIN_W, min(DISPLAY_SIZE_MAX_W, int(w or DISPLAY_SIZE_DEFAULT['w'])))
    height = max(DISPLAY_SIZE_MIN_H, min(DISPLAY_SIZE_MAX_H, int(h or DISPLAY_SIZE_DEFAULT['h'])))
    return {'w': width, 'h': height}


def _normalize_history(history):
    if not isinstance(history, list):
        return []
    cleaned = []
    for item in history[-HISTORY_MAX_LEN:]:
        if not isinstance(item, dict):
            continue
        snapshot = {
            'mxgraph_xml': str(item.get('mxgraph_xml', '') or '')[:200000],
            'updated_at': int(_normalize_number(item.get('updated_at'), default=0) or 0),
        }
        cleaned.append(snapshot)
    return cleaned


def new_diagram_block(
    *,
    diagram_id=None,
    diagram_kind=DIAGRAM_KIND_DEFAULT,
    authoring_format=DIAGRAM_FORMAT_MERMAID,
    mermaid='',
    json_graph=None,
    mxgraph_xml='',
    caption='',
    thumbnail_b64='',
    thumbnail_path='',
    thumbnail_size=None,
    display_size=None,
    preview_only=False,
    history=None,
):
    block = {
        'type': 'diagram',
        'diagram_id': str(diagram_id or uuid.uuid4().hex),
        'caption': _normalize_caption(caption),
        'diagram_kind': _normalize_kind(diagram_kind),
        'authoring_format': _normalize_authoring_format(authoring_format),
        'mermaid': _normalize_text(mermaid).strip(),
        'json_graph': _normalize_json_graph(json_graph or {}),
        'mxgraph_xml': str(mxgraph_xml or '')[:500000],
        'thumbnail_b64': _normalize_thumbnail_b64(thumbnail_b64),
        'thumbnail_path': _normalize_thumbnail_path(thumbnail_path),
        'thumbnail_size': _normalize_thumbnail_size(thumbnail_size),
        'display_size': _normalize_display_size(display_size),
        'preview_only': bool(preview_only),
        'history': _normalize_history(history or []),
        'updated_at': int(time.time()),
    }
    return block


def sanitize_diagram_block(block):
    """对外入口：清洗一个 diagram block，缺失字段补默认值，非法字段丢弃。"""
    if not isinstance(block, dict):
        return None
    sanitized = new_diagram_block(
        diagram_id=block.get('diagram_id', ''),
        diagram_kind=block.get('diagram_kind', DIAGRAM_KIND_DEFAULT),
        authoring_format=block.get('authoring_format', DIAGRAM_FORMAT_MERMAID),
        mermaid=block.get('mermaid', ''),
        json_graph=block.get('json_graph', {}),
        mxgraph_xml=block.get('mxgraph_xml', ''),
        caption=block.get('caption', ''),
        thumbnail_b64=block.get('thumbnail_b64', ''),
        thumbnail_path=block.get('thumbnail_path', ''),
        thumbnail_size=block.get('thumbnail_size'),
        display_size=block.get('display_size'),
        preview_only=block.get('preview_only', False),
        history=block.get('history', []),
    )
    has_mermaid = bool(sanitized['mermaid'])
    graph = sanitized['json_graph']
    has_graph = bool(graph.get('nodes')) or bool(sanitized['mxgraph_xml'])
    if not has_mermaid and not has_graph:
        return None
    if 'updated_at' in block:
        try:
            sanitized['updated_at'] = int(block['updated_at'])
        except (TypeError, ValueError):
            pass
    return sanitized


def diagram_placeholder_text(block):
    """diagram block 在纯文本/Markdown 占位输出。"""
    if not isinstance(block, dict):
        return '[图表]'
    caption = _normalize_caption(block.get('caption', ''))
    diagram_id = str(block.get('diagram_id', '') or '').strip()
    label = caption or diagram_id or '图表'
    return f'[图表: {label}]'


def deep_copy_diagram_block(block):
    return copy.deepcopy(block) if isinstance(block, dict) else block
