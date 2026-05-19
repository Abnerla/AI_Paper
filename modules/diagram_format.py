# -*- coding: utf-8 -*-
"""
图表格式转换：内部 JSON ↔ Mermaid DSL ↔ mxGraph XML。

P1 阶段提供 Python 端的兜底实现，覆盖最常用的 flowchart 与基础图种。
更精确的解析在 P2/P3 阶段由 webview 内的 mermaid.parse() 与 drawio 自身
的 postMessage 提供。这里的目标是：
  1. AI 生成 mermaid 文本后 Python 能粗略解析出 nodes/edges 用于缩略图
  2. 用户从 mermaid 视图保存时能写回内部 JSON
  3. 内部 JSON 可生成结构正确的 mxGraph XML 供 drawio 加载
"""

from __future__ import annotations

import re
import uuid
from xml.etree import ElementTree as ET


SUPPORTED_BIDIRECTIONAL = {
    'flowchart', 'stateDiagram', 'classDiagram',
    'erDiagram', 'sequence', 'mindmap',
}

_MERMAID_HEADER_RE = re.compile(
    r'^\s*(flowchart|graph|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|erDiagram|mindmap|gantt|journey|pie|quadrantChart|timeline|C4Context)'
    r'(?:\s+(TB|BT|LR|RL|TD))?',
    re.IGNORECASE,
)

# flowchart 节点（按"长括号优先"顺序匹配）：
# id([text]) 体育场 / id[[text]] 子流程 / id[(text)] 圆柱 / id((text)) 圆 /
# id[/text/] 平行四边形 / id[\text\] / id{{text}} 六边形 / id{text} 菱形 /
# id(text) 圆角 / id[text] 矩形 / id>text] 标志
_FLOW_NODE_DECL_RE = re.compile(
    r'([A-Za-z_][A-Za-z0-9_\-]*)'
    r'(\(\[|\[\[|\[\(|\(\(|\[/|\[\\|\{\{|>|\(|\{|\[)'
    r'\s*"?(.*?)"?\s*'
    r'(\]\)|\]\]|\)\]|\)\)|/\]|\\\]|\}\}|\)|\}|\])'
)

# flowchart 边
_FLOW_EDGE_RE = re.compile(
    r'([A-Za-z_][A-Za-z0-9_\-]*)\s*'
    r'(?:\([\[\(]?[^\]\)\}]*[\]\)\}]?\)?|\[[\[\(]?[^\]\)\}]*[\]\)\}]?\]?|\{[\{]?[^\}]*\}?)?\s*'
    r'(--+>|--+|-\.-+>|-\.->|==+>|==+)'
    r'\s*(?:\|([^|]*?)\|)?'
    r'\s*([A-Za-z_][A-Za-z0-9_\-]*)'
)

# A -- 文本 --> B 形式
_FLOW_EDGE_INLINE_RE = re.compile(
    r'([A-Za-z_][A-Za-z0-9_\-]*)\s*'
    r'-{2,}\s*([^\n>-][^\n-]*?)\s*-{2,}>\s*'
    r'([A-Za-z_][A-Za-z0-9_\-]*)'
)

_SHAPE_BY_BRACKET = {
    '[': 'rect', '[[': 'rect',
    '(': 'rounded', '((': 'ellipse',
    '([': 'rounded',
    '[(': 'rounded',
    '{': 'diamond', '{{': 'hexagon',
    '>': 'flag',
    '[/': 'parallelogram', '[\\': 'parallelogram',
}


def detect_diagram_kind(text):
    if not text:
        return ''
    match = _MERMAID_HEADER_RE.search(text)
    if not match:
        return ''
    raw = match.group(1).lower()
    mapping = {
        'flowchart': 'flowchart',
        'graph': 'flowchart',
        'sequencediagram': 'sequence',
        'classdiagram': 'classDiagram',
        'statediagram': 'stateDiagram',
        'statediagram-v2': 'stateDiagram',
        'erdiagram': 'erDiagram',
        'mindmap': 'mindmap',
        'gantt': 'gantt',
        'journey': 'journey',
        'pie': 'pie',
        'quadrantchart': 'quadrant',
        'timeline': 'timeline',
        'c4context': 'c4',
    }
    return mapping.get(raw, raw)


def detect_layout(text):
    if not text:
        return 'TB'
    match = _MERMAID_HEADER_RE.search(text)
    if not match:
        return 'TB'
    direction = (match.group(2) or 'TB').upper()
    return 'TB' if direction == 'TD' else direction


def mermaid_to_json(text):
    """Python 端兜底解析。仅准确处理 flowchart；其它类型返回空 graph 但保留 meta。"""
    if not text:
        return {'nodes': [], 'edges': [], 'groups': [], 'meta': {}}

    diagram_kind = detect_diagram_kind(text)
    layout = detect_layout(text)
    meta = {'layout': layout}

    if diagram_kind != 'flowchart':
        return {'nodes': [], 'edges': [], 'groups': [], 'meta': meta}

    nodes = {}
    edges = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('%%'):
            continue
        if _MERMAID_HEADER_RE.match(stripped):
            continue

        for node_match in _FLOW_NODE_DECL_RE.finditer(stripped):
            node_id = node_match.group(1)
            open_bracket = node_match.group(2)
            label = (node_match.group(3) or node_id).strip()
            shape = _SHAPE_BY_BRACKET.get(open_bracket, 'rect')
            existing = nodes.get(node_id)
            if existing is None or (label and not existing.get('label')):
                nodes[node_id] = {
                    'id': node_id,
                    'label': label or node_id,
                    'shape': shape,
                }

        edge_match_inline = _FLOW_EDGE_INLINE_RE.search(stripped)
        if edge_match_inline:
            source = edge_match_inline.group(1)
            label = (edge_match_inline.group(2) or '').strip()
            target = edge_match_inline.group(3)
            _ensure_node(nodes, source)
            _ensure_node(nodes, target)
            edges.append({
                'id': f'e_{uuid.uuid4().hex[:8]}',
                'source': source, 'target': target,
                'label': label, 'arrow': 'classic', 'dashed': False,
            })
            continue

        # 链式边：A --> B --> C 中需把 cursor 推到 target 起点，让 target 作为下一条边的 source
        cursor = 0
        while cursor < len(stripped):
            sub = stripped[cursor:]
            edge_match = _FLOW_EDGE_RE.search(sub)
            if not edge_match:
                break
            source = edge_match.group(1)
            arrow = edge_match.group(2) or '-->'
            label = (edge_match.group(3) or '').strip()
            target = edge_match.group(4)
            _ensure_node(nodes, source)
            _ensure_node(nodes, target)
            edges.append({
                'id': f'e_{uuid.uuid4().hex[:8]}',
                'source': source, 'target': target,
                'label': label,
                'arrow': 'classic',
                'dashed': '.' in arrow,
            })
            cursor += edge_match.start(4)

    return {
        'nodes': list(nodes.values()),
        'edges': edges,
        'groups': [],
        'meta': meta,
    }


def _ensure_node(nodes, node_id):
    if node_id not in nodes:
        nodes[node_id] = {'id': node_id, 'label': node_id, 'shape': 'rect'}


_BRACKET_BY_SHAPE = {
    'rect': ('[', ']'),
    'rounded': ('(', ')'),
    'ellipse': ('((', '))'),
    'diamond': ('{', '}'),
    'hexagon': ('{{', '}}'),
    'flag': ('>', ']'),
    'parallelogram': ('[/', '/]'),
}


def json_to_mermaid(graph, *, diagram_kind='flowchart'):
    if not isinstance(graph, dict):
        return ''
    nodes = graph.get('nodes') or []
    edges = graph.get('edges') or []
    meta = graph.get('meta') or {}
    layout = (meta.get('layout') or 'TB').upper()

    if diagram_kind != 'flowchart':
        return ''

    lines = [f'flowchart {layout}']
    for node in nodes:
        node_id = node.get('id') or 'n'
        label = (node.get('label') or node_id).replace('"', '\\"')
        shape = node.get('shape') or 'rect'
        opener, closer = _BRACKET_BY_SHAPE.get(shape, ('[', ']'))
        lines.append(f'    {node_id}{opener}"{label}"{closer}')
    for edge in edges:
        source = edge.get('source')
        target = edge.get('target')
        if not source or not target:
            continue
        label = (edge.get('label') or '').replace('|', ' ')
        arrow = '-.->' if edge.get('dashed') else '-->'
        if label:
            lines.append(f'    {source} {arrow}|{label}| {target}')
        else:
            lines.append(f'    {source} {arrow} {target}')
    return '\n'.join(lines)


def _build_style_string(style, *, vertex=True):
    parts = []
    style = style or {}
    shape = style.get('shape')
    if shape:
        parts.append(f'shape={shape}')
    if 'fill' in style:
        parts.append(f'fillColor={style["fill"]}')
    if 'stroke' in style:
        parts.append(f'strokeColor={style["stroke"]}')
    if 'strokeWidth' in style:
        parts.append(f'strokeWidth={style["strokeWidth"]}')
    if style.get('rounded'):
        parts.append('rounded=1')
    if style.get('dashed'):
        parts.append('dashed=1')
    if 'fontSize' in style:
        parts.append(f'fontSize={style["fontSize"]}')
    if 'fontColor' in style:
        parts.append(f'fontColor={style["fontColor"]}')
    if vertex:
        parts.append('whiteSpace=wrap')
        parts.append('html=1')
    return ';'.join(parts)


def _shape_to_mxgraph_style(shape):
    mapping = {
        'rect': '',
        'rounded': 'rounded=1',
        'ellipse': 'ellipse',
        'diamond': 'rhombus',
        'hexagon': 'shape=hexagon',
        'flag': 'shape=offPageConnector',
        'parallelogram': 'shape=parallelogram',
    }
    return mapping.get(shape, '')


def json_to_mxgraph_xml(graph, *, page_width=1024, page_height=768):
    if not isinstance(graph, dict):
        graph = {}
    nodes = graph.get('nodes') or []
    edges = graph.get('edges') or []
    groups = graph.get('groups') or []

    root = ET.Element('mxGraphModel', {
        'dx': '1024', 'dy': '768', 'grid': '1', 'gridSize': '10',
        'guides': '1', 'tooltips': '1', 'connect': '1',
        'arrows': '1', 'fold': '1', 'page': '1',
        'pageScale': '1', 'pageWidth': str(page_width),
        'pageHeight': str(page_height), 'math': '0', 'shadow': '0',
    })
    inner_root = ET.SubElement(root, 'root')
    ET.SubElement(inner_root, 'mxCell', {'id': '0'})
    ET.SubElement(inner_root, 'mxCell', {'id': '1', 'parent': '0'})

    # 自动布局：未提供坐标的节点按网格摆放
    auto_x, auto_y = 80.0, 80.0
    for index, node in enumerate(nodes):
        node_id = node.get('id') or f'n_{index}'
        label = node.get('label') or node_id
        shape = node.get('shape') or 'rect'
        x = node.get('x', auto_x + (index % 4) * 180)
        y = node.get('y', auto_y + (index // 4) * 120)
        width = node.get('width', 120)
        height = node.get('height', 60)
        shape_style = _shape_to_mxgraph_style(shape)
        custom_style = _build_style_string(node.get('style'))
        style = ';'.join(part for part in (shape_style, custom_style) if part)
        cell = ET.SubElement(inner_root, 'mxCell', {
            'id': str(node_id),
            'value': str(label),
            'style': style,
            'vertex': '1',
            'parent': '1',
        })
        ET.SubElement(cell, 'mxGeometry', {
            'x': str(x), 'y': str(y),
            'width': str(width), 'height': str(height),
            'as': 'geometry',
        })

    for index, group in enumerate(groups):
        group_id = group.get('id') or f'g_{index}'
        label = group.get('label') or ''
        x = group.get('x', 40)
        y = group.get('y', 40)
        width = group.get('width', 320)
        height = group.get('height', 240)
        cell = ET.SubElement(inner_root, 'mxCell', {
            'id': str(group_id),
            'value': str(label),
            'style': 'rounded=0;whiteSpace=wrap;html=1;container=1;collapsible=0',
            'vertex': '1', 'parent': '1',
        })
        ET.SubElement(cell, 'mxGeometry', {
            'x': str(x), 'y': str(y),
            'width': str(width), 'height': str(height),
            'as': 'geometry',
        })

    for index, edge in enumerate(edges):
        edge_id = edge.get('id') or f'e_{index}'
        source = edge.get('source')
        target = edge.get('target')
        if not source or not target:
            continue
        label = edge.get('label') or ''
        custom_style = _build_style_string(edge.get('style'), vertex=False)
        style_parts = ['edgeStyle=orthogonalEdgeStyle', 'rounded=0', 'html=1']
        if edge.get('dashed'):
            style_parts.append('dashed=1')
        if custom_style:
            style_parts.append(custom_style)
        cell = ET.SubElement(inner_root, 'mxCell', {
            'id': str(edge_id),
            'value': str(label),
            'style': ';'.join(style_parts),
            'edge': '1', 'parent': '1',
            'source': str(source), 'target': str(target),
        })
        geometry = ET.SubElement(cell, 'mxGeometry', {
            'relative': '1', 'as': 'geometry',
        })
        waypoints = edge.get('waypoints') or []
        if waypoints:
            array = ET.SubElement(geometry, 'Array', {'as': 'points'})
            for point in waypoints:
                ET.SubElement(array, 'mxPoint', {
                    'x': str(point.get('x', 0)),
                    'y': str(point.get('y', 0)),
                })

    return ET.tostring(root, encoding='unicode')


def _parse_mxgraph_style(style_text):
    style = {}
    if not style_text:
        return style
    for part in str(style_text).split(';'):
        if not part:
            continue
        if '=' in part:
            key, value = part.split('=', 1)
            style[key.strip()] = value.strip()
        else:
            style[part.strip()] = '1'
    return style


def mxgraph_xml_to_json(xml_text):
    if not xml_text:
        return {'nodes': [], 'edges': [], 'groups': [], 'meta': {}}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {'nodes': [], 'edges': [], 'groups': [], 'meta': {}}

    nodes = []
    edges = []
    groups = []

    cells = root.iter('mxCell')
    for cell in cells:
        cell_id = cell.attrib.get('id')
        if not cell_id or cell_id in ('0', '1'):
            continue
        style = _parse_mxgraph_style(cell.attrib.get('style', ''))
        value = cell.attrib.get('value', '') or ''
        geometry = cell.find('mxGeometry')

        if cell.attrib.get('edge') == '1':
            edge = {
                'id': cell_id,
                'source': cell.attrib.get('source', ''),
                'target': cell.attrib.get('target', ''),
                'label': value,
                'arrow': 'classic',
                'dashed': style.get('dashed') == '1',
            }
            if geometry is not None:
                array = geometry.find('Array')
                if array is not None:
                    waypoints = []
                    for point in array.findall('mxPoint'):
                        try:
                            waypoints.append({
                                'x': float(point.attrib.get('x', 0)),
                                'y': float(point.attrib.get('y', 0)),
                            })
                        except (TypeError, ValueError):
                            continue
                    if waypoints:
                        edge['waypoints'] = waypoints
            edges.append(edge)
        elif cell.attrib.get('vertex') == '1':
            node = {
                'id': cell_id,
                'label': value,
                'shape': _shape_from_style(style),
            }
            if geometry is not None:
                for axis in ('x', 'y', 'width', 'height'):
                    raw = geometry.attrib.get(axis)
                    if raw is None:
                        continue
                    try:
                        node[axis] = float(raw)
                    except (TypeError, ValueError):
                        continue
            if style.get('container') == '1':
                groups.append({
                    'id': cell_id,
                    'label': value,
                    'children': [],
                    **{k: node[k] for k in ('x', 'y', 'width', 'height') if k in node},
                })
            else:
                nodes.append(node)

    # 容器子元素归属：parent 指向 group 时挂入 children
    parent_map = {cell.attrib.get('id'): cell.attrib.get('parent') for cell in root.iter('mxCell')}
    group_index = {group['id']: group for group in groups}
    for node in nodes:
        parent_id = parent_map.get(node['id'])
        if parent_id and parent_id in group_index:
            group_index[parent_id]['children'].append(node['id'])

    return {
        'nodes': nodes,
        'edges': edges,
        'groups': groups,
        'meta': {},
    }


def _shape_from_style(style):
    if style.get('shape') == 'hexagon':
        return 'hexagon'
    if style.get('shape') == 'parallelogram':
        return 'parallelogram'
    if style.get('ellipse') == '1' or style.get('shape') == 'ellipse':
        return 'ellipse'
    if style.get('rhombus') == '1' or style.get('shape') == 'rhombus':
        return 'diamond'
    if style.get('rounded') == '1':
        return 'rounded'
    return 'rect'
