# -*- coding: utf-8 -*-
"""
draw.io XML 工具层。

该模块承接原图表前端中的核心工具协议：
display_diagram / edit_diagram / append_diagram / get_shape_library。
Python 页面只处理结构化结果，不直接运行 Next.js 服务。
"""

from __future__ import annotations

import os
import re
from copy import deepcopy
from xml.etree import ElementTree as ET

from modules.runtime_paths import resolve_resource_path


ROOT_CELL_IDS = {'0', '1'}
AVAILABLE_SHAPE_LIBRARIES = (
    'aws4', 'azure2', 'gcp2', 'alibaba_cloud', 'openstack', 'salesforce',
    'cisco19', 'network', 'kubernetes', 'vvd', 'rack',
    'bpmn', 'lean_mapping', 'flowchart', 'basic', 'arrows2', 'infographic',
    'sitemap', 'android', 'material_design', 'citrix', 'sap', 'mscae',
    'atlassian', 'fluidpower', 'electrical', 'pid', 'cabinets', 'floorplan',
    'webicons',
)


class DiagramToolError(ValueError):
    """图表工具执行失败。"""


def is_mxcell_xml_complete(xml_fragment: str) -> bool:
    """判断裸 mxCell 片段是否完整，供 append_diagram 续写判定使用。"""
    text = str(xml_fragment or '').strip()
    if not text:
        return False
    try:
        ET.fromstring(f'<root>{text}</root>')
        return True
    except ET.ParseError:
        return False


def wrap_mx_cells(mx_cells_xml: str, *, page_width: int = 1024, page_height: int = 768) -> str:
    """把模型输出的裸 mxCell 片段包装成 draw.io 可加载的 mxGraphModel。"""
    text = str(mx_cells_xml or '').strip()
    if not text:
        raise DiagramToolError('图表 XML 为空。')
    if text.startswith('<mxGraphModel') or text.startswith('<mxfile'):
        validate_mxgraph_xml(text)
        return text
    if not is_mxcell_xml_complete(text):
        raise DiagramToolError('mxCell XML 片段不完整。')

    model = ET.Element('mxGraphModel', {
        'dx': '1024',
        'dy': '768',
        'grid': '1',
        'gridSize': '10',
        'guides': '1',
        'tooltips': '1',
        'connect': '1',
        'arrows': '1',
        'fold': '1',
        'page': '1',
        'pageScale': '1',
        'pageWidth': str(page_width),
        'pageHeight': str(page_height),
        'math': '0',
        'shadow': '0',
    })
    root = ET.SubElement(model, 'root')
    ET.SubElement(root, 'mxCell', {'id': '0'})
    ET.SubElement(root, 'mxCell', {'id': '1', 'parent': '0'})

    fragment_root = ET.fromstring(f'<root>{text}</root>')
    for cell in list(fragment_root):
        if cell.tag != 'mxCell':
            raise DiagramToolError('display_diagram 只能接收 mxCell 元素。')
        cell_id = cell.attrib.get('id')
        if cell_id in ROOT_CELL_IDS:
            raise DiagramToolError('模型输出不能包含根单元 id=0 或 id=1。')
        root.append(deepcopy(cell))

    xml_text = ET.tostring(model, encoding='unicode')
    validate_mxgraph_xml(xml_text)
    return xml_text


def validate_mxgraph_xml(xml_text: str) -> dict:
    """校验 mxGraphModel/mxfile 基础结构，返回统计信息。"""
    model = _parse_model(xml_text)
    root = _find_graph_root(model)
    cells = list(root.findall('mxCell'))
    ids = []
    id_set = set()
    errors = []
    vertices = 0
    edges = 0

    for cell in cells:
        cell_id = cell.attrib.get('id')
        if not cell_id:
            errors.append('存在缺少 id 的 mxCell。')
            continue
        if cell_id in id_set:
            errors.append(f'存在重复 id：{cell_id}。')
        ids.append(cell_id)
        id_set.add(cell_id)

    if '0' not in id_set or '1' not in id_set:
        errors.append('缺少 draw.io 根单元 id=0 或 id=1。')

    for cell in cells:
        cell_id = cell.attrib.get('id', '')
        if cell_id in ROOT_CELL_IDS:
            continue
        parent = cell.attrib.get('parent')
        if parent and parent not in id_set:
            errors.append(f'id={cell_id} 的 parent 不存在：{parent}。')
        if cell.attrib.get('edge') == '1':
            edges += 1
            source = cell.attrib.get('source')
            target = cell.attrib.get('target')
            if source and source not in id_set:
                errors.append(f'id={cell_id} 的 source 不存在：{source}。')
            if target and target not in id_set:
                errors.append(f'id={cell_id} 的 target 不存在：{target}。')
        elif cell.attrib.get('vertex') == '1':
            vertices += 1

    if errors:
        raise DiagramToolError('\n'.join(errors))
    return {'cell_count': len(ids), 'vertex_count': vertices, 'edge_count': edges}


def analyze_mxgraph_xml(xml_text: str) -> dict:
    """生成用于界面展示的 draw.io 结构校验报告。"""
    try:
        model = _parse_model(xml_text)
        root = _find_graph_root(model)
    except DiagramToolError as exc:
        return {
            'ok': False,
            'stats': {'cell_count': 0, 'vertex_count': 0, 'edge_count': 0},
            'issues': [{'severity': 'error', 'code': 'parse_error', 'message': str(exc)}],
        }

    cells = list(root.findall('mxCell'))
    ids = []
    id_set = set()
    duplicate_ids = set()
    issues = []
    vertices = []
    edges = []
    missing_geometry = []
    refs = set()

    for cell in cells:
        cell_id = cell.attrib.get('id')
        if not cell_id:
            issues.append({'severity': 'error', 'code': 'missing_id', 'message': '存在缺少 id 的 mxCell。'})
            continue
        if cell_id in id_set:
            duplicate_ids.add(cell_id)
        ids.append(cell_id)
        id_set.add(cell_id)

    for cell_id in sorted(duplicate_ids):
        issues.append({'severity': 'error', 'code': 'duplicate_id', 'message': f'存在重复 id：{cell_id}。'})

    if '0' not in id_set or '1' not in id_set:
        issues.append({'severity': 'error', 'code': 'missing_root', 'message': '缺少 draw.io 根单元 id=0 或 id=1。'})

    for cell in cells:
        cell_id = cell.attrib.get('id', '')
        if not cell_id or cell_id in ROOT_CELL_IDS:
            continue

        parent = cell.attrib.get('parent')
        if parent and parent not in id_set:
            issues.append({'severity': 'error', 'code': 'missing_parent', 'message': f'id={cell_id} 的 parent 不存在：{parent}。'})

        is_edge = cell.attrib.get('edge') == '1'
        is_vertex = cell.attrib.get('vertex') == '1'
        if is_edge:
            edges.append(cell)
            source = cell.attrib.get('source')
            target = cell.attrib.get('target')
            if source:
                refs.add(source)
                if source not in id_set:
                    issues.append({'severity': 'error', 'code': 'missing_source', 'message': f'id={cell_id} 的 source 不存在：{source}。'})
            if target:
                refs.add(target)
                if target not in id_set:
                    issues.append({'severity': 'error', 'code': 'missing_target', 'message': f'id={cell_id} 的 target 不存在：{target}。'})
        elif is_vertex:
            vertices.append(cell)

        if (is_edge or is_vertex) and cell.find('mxGeometry') is None:
            missing_geometry.append(cell_id)

    if missing_geometry:
        preview = '、'.join(missing_geometry[:6])
        suffix = '等' if len(missing_geometry) > 6 else ''
        issues.append({
            'severity': 'warning',
            'code': 'missing_geometry',
            'message': f'{len(missing_geometry)} 个图形单元缺少 mxGeometry：{preview}{suffix}。',
        })

    isolated = [
        cell.attrib.get('id', '')
        for cell in vertices
        if cell.attrib.get('id', '') and cell.attrib.get('id') not in refs
    ]
    if isolated and edges:
        preview = '、'.join(isolated[:6])
        suffix = '等' if len(isolated) > 6 else ''
        issues.append({
            'severity': 'warning',
            'code': 'isolated_vertex',
            'message': f'{len(isolated)} 个节点未被连线引用：{preview}{suffix}。',
        })

    return {
        'ok': not any(item.get('severity') == 'error' for item in issues),
        'stats': {
            'cell_count': len(ids),
            'vertex_count': len(vertices),
            'edge_count': len(edges),
            'missing_geometry_count': len(missing_geometry),
            'isolated_vertex_count': len(isolated),
        },
        'issues': issues,
    }


def apply_diagram_operations(xml_text: str, operations: list[dict]) -> tuple[str, list[dict]]:
    """按 cell_id 对 draw.io XML 执行 add/update/delete 操作。"""
    model = _parse_model(xml_text)
    root = _find_graph_root(model)
    errors = []

    for op in operations or []:
        if not isinstance(op, dict):
            continue
        operation = str(op.get('operation') or '').strip().lower()
        cell_id = str(op.get('cell_id') or '').strip()
        if operation not in {'add', 'update', 'delete'}:
            errors.append({'type': operation or 'unknown', 'cell_id': cell_id, 'message': '未知操作类型'})
            continue
        if not cell_id:
            errors.append({'type': operation, 'cell_id': '', 'message': '缺少 cell_id'})
            continue
        if cell_id in ROOT_CELL_IDS:
            errors.append({'type': operation, 'cell_id': cell_id, 'message': '不能修改 draw.io 根单元'})
            continue

        cell_index = _cell_index(root)
        if operation == 'delete':
            if cell_id not in cell_index:
                errors.append({'type': operation, 'cell_id': cell_id, 'message': '目标单元不存在'})
                continue
            _delete_cell_cascade(root, cell_id)
            continue

        new_xml = str(op.get('new_xml') or '').strip()
        try:
            new_cell = _parse_single_mxcell(new_xml)
        except DiagramToolError as exc:
            errors.append({'type': operation, 'cell_id': cell_id, 'message': str(exc)})
            continue
        if new_cell.attrib.get('id') != cell_id:
            errors.append({'type': operation, 'cell_id': cell_id, 'message': 'new_xml 中的 id 与 cell_id 不一致'})
            continue

        if operation == 'add':
            if cell_id in cell_index:
                errors.append({'type': operation, 'cell_id': cell_id, 'message': '新增单元 id 已存在'})
                continue
            root.append(new_cell)
            continue

        if cell_id not in cell_index:
            errors.append({'type': operation, 'cell_id': cell_id, 'message': '更新目标不存在'})
            continue
        _replace_cell(root, cell_id, new_cell)

    result = ET.tostring(model, encoding='unicode')
    if not errors:
        try:
            validate_mxgraph_xml(result)
        except DiagramToolError as exc:
            errors.append({'type': 'validate', 'cell_id': '', 'message': str(exc)})
    return result, errors


def get_shape_library(library: str) -> str:
    """读取 draw.io 图形库说明。优先使用打包资源，其次使用导入的 Next 项目文档。"""
    sanitized = re.sub(r'[^a-z0-9_-]', '', str(library or '').lower())
    if not sanitized or sanitized != str(library or '').lower():
        raise DiagramToolError('图形库名称只能包含字母、数字、下划线和连字符。')

    candidates = [
        resolve_resource_path('Management', 'shape_libraries', f'{sanitized}.md'),
    ]
    for path in candidates:
        if not os.path.exists(path):
            continue
        with open(path, 'r', encoding='utf-8') as handle:
            return handle.read()

    available = ', '.join(AVAILABLE_SHAPE_LIBRARIES)
    raise DiagramToolError(f'未找到图形库：{library}。可用图形库：{available}')


def _parse_model(xml_text: str) -> ET.Element:
    text = str(xml_text or '').strip()
    if not text:
        raise DiagramToolError('图表 XML 为空。')
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise DiagramToolError(f'XML 解析失败：{exc}') from exc
    if root.tag == 'mxfile':
        diagram = root.find('diagram')
        if diagram is not None and diagram.text and diagram.text.strip().startswith('<mxGraphModel'):
            return _parse_model(diagram.text)
        model = root.find('.//mxGraphModel')
        if model is not None:
            return model
        raise DiagramToolError('mxfile 中未找到可直接解析的 mxGraphModel。')
    if root.tag != 'mxGraphModel':
        raise DiagramToolError('根元素必须是 mxGraphModel 或 mxfile。')
    return root


def _find_graph_root(model: ET.Element) -> ET.Element:
    root = model.find('root')
    if root is None:
        raise DiagramToolError('mxGraphModel 缺少 root 节点。')
    return root


def _cell_index(root: ET.Element) -> dict[str, ET.Element]:
    return {
        str(cell.attrib.get('id') or ''): cell
        for cell in root.findall('mxCell')
        if cell.attrib.get('id')
    }


def _parse_single_mxcell(xml_text: str) -> ET.Element:
    try:
        cell = ET.fromstring(str(xml_text or '').strip())
    except ET.ParseError as exc:
        raise DiagramToolError(f'new_xml 不是合法 mxCell：{exc}') from exc
    if cell.tag != 'mxCell':
        raise DiagramToolError('new_xml 必须是单个 mxCell 元素。')
    if not cell.attrib.get('id'):
        raise DiagramToolError('new_xml 缺少 id。')
    return cell


def _replace_cell(root: ET.Element, cell_id: str, new_cell: ET.Element) -> None:
    children = list(root)
    for index, child in enumerate(children):
        if child.tag == 'mxCell' and child.attrib.get('id') == cell_id:
            root.remove(child)
            root.insert(index, new_cell)
            return


def _delete_cell_cascade(root: ET.Element, cell_id: str) -> None:
    deleted = {cell_id}
    changed = True
    while changed:
        changed = False
        for cell in list(root.findall('mxCell')):
            cid = cell.attrib.get('id')
            if cid in deleted:
                continue
            if (
                cell.attrib.get('parent') in deleted
                or cell.attrib.get('source') in deleted
                or cell.attrib.get('target') in deleted
            ):
                deleted.add(cid)
                changed = True

    for cell in list(root.findall('mxCell')):
        if cell.attrib.get('id') in deleted:
            root.remove(cell)
