# -*- coding: utf-8 -*-
"""
图表 AI 生成入口。

- generate_from_prompt: 从自然语言生成新图表 block（含 mermaid + json_graph + 占位缩略图）
- patch_from_ai: 让 AI 输出增量 ops 用于二次编辑（P4 阶段使用）
- apply_patch: 把 ops 应用到 graph，纯 Python 便于测试

P1 阶段仅启用 generate_from_prompt；patch_from_ai/apply_patch 已就绪
等 P4 接入 webview AI 对话区。
"""

from __future__ import annotations

import copy
import json
import re
import uuid
from typing import Iterable

from modules.diagram_blocks import (
    DIAGRAM_FORMAT_MERMAID,
    DIAGRAM_KIND_DEFAULT,
    new_diagram_block,
    sanitize_diagram_block,
)
from modules.diagram_format import detect_diagram_kind, mermaid_to_json
from modules.diagram_thumbnail import render_placeholder_b64


GENERATE_SYSTEM = (
    '你是图表生成专家。根据用户描述输出严格 JSON：\n'
    '{"diagram_kind": "...", "caption": "...", "mermaid": "...", "json_graph": {"nodes": [...], "edges": [...], "meta": {"layout": "TB"}}}\n'
    '约束：\n'
    '1. mermaid 字段必须是合法的 Mermaid v10+ 语法，可独立渲染\n'
    '2. json_graph.nodes 中每个节点都要有唯一 id（短英文+数字）和 label\n'
    '3. 所有 edges 的 source/target 必须出现在 nodes 列表中\n'
    '4. 形状取值仅限：rect / rounded / ellipse / diamond / hexagon / parallelogram\n'
    '5. 禁止输出任何额外文字、Markdown 围栏或解释，只输出 JSON 对象'
)

PATCH_SYSTEM = (
    '你是图表编辑助手。根据用户的修改指令，对当前图返回最小增量 ops。\n'
    '严格输出 {"ops": [...]} 形式的 JSON 对象。\n'
    '允许的 op 类型：\n'
    '  add_node / update_node / remove_node / add_edge / update_edge / remove_edge\n'
    '  set_meta / add_group / set_caption\n'
    '约束：\n'
    '1. 保留所有未被指令明确提及的节点与边\n'
    '2. 新增节点必须给唯一 id（建议 n_<时间戳后缀>）\n'
    '3. 新增边的 source / target 必须存在\n'
    '4. 不要修改 caption 除非用户明确要求\n'
    '5. 仅输出 JSON 对象，不要解释'
)

VALID_OPS = {
    'add_node', 'update_node', 'remove_node',
    'add_edge', 'update_edge', 'remove_edge',
    'set_meta', 'add_group', 'set_caption',
}


def _build_generate_prompt(instruction, diagram_kind=''):
    pieces = [f'用户描述：{instruction}']
    if diagram_kind:
        pieces.append(f'期望图表类型：{diagram_kind}')
    pieces.append('请按 system 规定的 JSON 结构输出。')
    return '\n\n'.join(pieces)


def _build_patch_prompt(instruction, current_json):
    summary = _summarize_graph(current_json)
    return (
        f'当前图概要：\n{summary}\n\n'
        f'修改指令：{instruction}\n\n'
        '请输出最小增量 ops。'
    )


def _summarize_graph(graph):
    if not isinstance(graph, dict):
        return '（空图）'
    nodes = graph.get('nodes') or []
    edges = graph.get('edges') or []
    lines = [f'节点 {len(nodes)} 个，边 {len(edges)} 条']
    for node in nodes[:30]:
        lines.append(f'- 节点 {node.get("id")}: {node.get("label", "")}（{node.get("shape", "rect")}）')
    for edge in edges[:30]:
        label = edge.get('label') or ''
        suffix = f' [{label}]' if label else ''
        lines.append(f'- 边 {edge.get("source")} -> {edge.get("target")}{suffix}')
    return '\n'.join(lines)


def generate_from_prompt(api_client, instruction, *,
                         diagram_kind='',
                         caption='',
                         scene_id='paper_write.diagram_generate'):
    """调用 AI 生成图表 block。"""
    if not instruction or not str(instruction).strip():
        raise ValueError('需要提供描述以生成图表。')

    payload = api_client.call_json_sync(
        prompt=_build_generate_prompt(instruction, diagram_kind),
        system=GENERATE_SYSTEM,
        usage_context={
            'page_id': 'paper_write',
            'scene_id': scene_id,
            'action': 'diagram.generate',
        },
        schema_name='diagram.v1',
    )
    if not isinstance(payload, dict):
        raise ValueError('AI 返回格式不符合 diagram.v1 规范。')

    ai_kind = payload.get('diagram_kind') or diagram_kind or detect_diagram_kind(payload.get('mermaid', '')) or DIAGRAM_KIND_DEFAULT
    mermaid_text = str(payload.get('mermaid', '') or '').strip()
    json_graph = payload.get('json_graph') or {}
    if not json_graph and mermaid_text:
        json_graph = mermaid_to_json(mermaid_text)

    block = new_diagram_block(
        diagram_kind=ai_kind,
        authoring_format=DIAGRAM_FORMAT_MERMAID,
        mermaid=mermaid_text,
        json_graph=json_graph,
        caption=caption or payload.get('caption', ''),
    )
    block = sanitize_diagram_block(block)
    if block is None:
        raise ValueError('AI 返回的图表内容无效（缺少 mermaid 与节点）。')

    thumb_b64, thumb_path = render_placeholder_b64(
        block.get('json_graph') or {},
        caption=block.get('caption') or '',
    )
    if thumb_b64:
        block['thumbnail_b64'] = thumb_b64
    if thumb_path:
        block['thumbnail_path'] = thumb_path
    return block


def patch_from_ai(api_client, instruction, current_json, *,
                  scene_id='paper_write.diagram_edit'):
    """让 AI 输出 ops 列表用于增量改图。"""
    payload = api_client.call_json_sync(
        prompt=_build_patch_prompt(instruction, current_json),
        system=PATCH_SYSTEM,
        usage_context={
            'page_id': 'paper_write',
            'scene_id': scene_id,
            'action': 'diagram.patch',
        },
        schema_name='diagram.patch.v1',
    )
    if isinstance(payload, dict):
        ops = payload.get('ops')
    else:
        ops = payload
    return _validate_ops(ops or [])


def _validate_ops(ops: Iterable):
    cleaned = []
    if not isinstance(ops, list):
        return cleaned
    for raw in ops:
        if not isinstance(raw, dict):
            continue
        op_name = str(raw.get('op', '')).strip()
        if op_name not in VALID_OPS:
            continue
        cleaned.append(raw)
    return cleaned


def apply_patch(graph, ops):
    """把 ops 应用到 json_graph，返回新 graph（不修改入参）。"""
    new_graph = copy.deepcopy(graph) if isinstance(graph, dict) else {
        'nodes': [], 'edges': [], 'groups': [], 'meta': {}
    }
    new_graph.setdefault('nodes', [])
    new_graph.setdefault('edges', [])
    new_graph.setdefault('groups', [])
    new_graph.setdefault('meta', {})
    caption_buffer = {'caption': None}

    nodes = new_graph['nodes']
    edges = new_graph['edges']
    groups = new_graph['groups']

    node_index = {node['id']: node for node in nodes if isinstance(node, dict) and node.get('id')}
    edge_index = {edge['id']: edge for edge in edges if isinstance(edge, dict) and edge.get('id')}

    for op in ops or []:
        kind = op.get('op')
        if kind == 'add_node':
            node = op.get('node') or {}
            if not node.get('id'):
                node['id'] = f'n_{uuid.uuid4().hex[:8]}'
            if node['id'] not in node_index:
                nodes.append(node)
                node_index[node['id']] = node
        elif kind == 'update_node':
            node_id = op.get('id')
            patch = op.get('patch') or {}
            target = node_index.get(node_id)
            if target:
                for key, value in patch.items():
                    target[key] = value
        elif kind == 'remove_node':
            node_id = op.get('id')
            if node_id and node_id in node_index:
                nodes[:] = [n for n in nodes if n.get('id') != node_id]
                node_index.pop(node_id, None)
                # 级联删除连接到该节点的边
                edges[:] = [e for e in edges if e.get('source') != node_id and e.get('target') != node_id]
                edge_index = {e['id']: e for e in edges if isinstance(e, dict) and e.get('id')}
        elif kind == 'add_edge':
            edge = op.get('edge') or {}
            if not edge.get('id'):
                edge['id'] = f'e_{uuid.uuid4().hex[:8]}'
            if edge.get('source') in node_index and edge.get('target') in node_index:
                edges.append(edge)
                edge_index[edge['id']] = edge
        elif kind == 'update_edge':
            edge_id = op.get('id')
            patch = op.get('patch') or {}
            target = edge_index.get(edge_id)
            if target:
                for key, value in patch.items():
                    target[key] = value
        elif kind == 'remove_edge':
            edge_id = op.get('id')
            if edge_id in edge_index:
                edges[:] = [e for e in edges if e.get('id') != edge_id]
                edge_index.pop(edge_id, None)
        elif kind == 'set_meta':
            meta = op.get('meta') or {}
            if isinstance(meta, dict):
                new_graph['meta'].update(meta)
        elif kind == 'add_group':
            group = op.get('group') or {}
            if not group.get('id'):
                group['id'] = f'g_{uuid.uuid4().hex[:8]}'
            groups.append(group)
        elif kind == 'set_caption':
            caption_buffer['caption'] = op.get('caption', '')

    return new_graph, caption_buffer['caption']
