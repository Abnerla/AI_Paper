"""图表输出校验器 Skill。

after_response 在 AI 返回原始文本后做后处理：
  1. 剥掉 Markdown 代码围栏 (```json ... ```)
  2. 校验 JSON 可解析；不能解析则尝试容错截取（取首个 { 到最后一个 } 的子串）
  3. 对 ops 数组：剔除未知 op 与缺失关键字段的 op
  4. 对生成场景：保证 json_graph 至少有 nodes/edges/meta 三个键

returns 修复后的 response_text 与 metadata 标记。
"""

import json
import re


_VALID_OPS = {
    'add_node', 'update_node', 'remove_node',
    'add_edge', 'update_edge', 'remove_edge',
    'set_meta', 'add_group', 'set_caption',
}


def _strip_fences(text):
    if not text:
        return ''
    text = text.strip()
    # ```json ... ``` 或 ``` ... ```
    text = re.sub(r'^```(?:json|JSON)?\s*', '', text)
    text = re.sub(r'\s*```\s*$', '', text)
    return text.strip()


def _slice_first_json(text):
    if not text:
        return text
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1 or end <= start:
        return text
    return text[start:end + 1]


def _try_parse(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        try:
            return json.loads(_slice_first_json(text))
        except Exception:
            return None


def _validate_ops(ops):
    if not isinstance(ops, list):
        return [], 0
    cleaned = []
    dropped = 0
    for raw in ops:
        if not isinstance(raw, dict):
            dropped += 1
            continue
        op = str(raw.get('op', '') or '').strip()
        if op not in _VALID_OPS:
            dropped += 1
            continue
        if op in ('add_node',) and not isinstance(raw.get('node'), dict):
            dropped += 1
            continue
        if op in ('add_edge',):
            edge = raw.get('edge') or {}
            if not isinstance(edge, dict) or not edge.get('source') or not edge.get('target'):
                dropped += 1
                continue
        if op in ('update_node', 'remove_node', 'update_edge', 'remove_edge') and not raw.get('id'):
            dropped += 1
            continue
        cleaned.append(raw)
    return cleaned, dropped


class DiagramValidatorSkill:
    def before_request(self, ctx):
        return {}

    def after_response(self, ctx, text):
        usage = ctx.get('usage_context') if isinstance(ctx, dict) else {}
        scene_id = ''
        if isinstance(usage, dict):
            scene_id = str(usage.get('scene_id') or '')

        cleaned_text = _strip_fences(text or '')
        payload = _try_parse(cleaned_text)
        meta = {
            'skill': 'diagram-validator',
            'parsed': payload is not None,
            'scene_id': scene_id,
        }

        if payload is None:
            return {'response_text': cleaned_text, 'metadata': meta}

        if scene_id == 'paper_write.diagram_edit':
            ops = payload.get('ops') if isinstance(payload, dict) else payload
            cleaned_ops, dropped = _validate_ops(ops)
            payload = {'ops': cleaned_ops}
            meta['ops_count'] = len(cleaned_ops)
            meta['ops_dropped'] = dropped
        elif scene_id == 'paper_write.diagram_generate' and isinstance(payload, dict):
            graph = payload.get('json_graph') or {}
            if not isinstance(graph, dict):
                graph = {}
            graph.setdefault('nodes', [])
            graph.setdefault('edges', [])
            graph.setdefault('meta', {})
            payload['json_graph'] = graph
            meta['nodes_count'] = len(graph.get('nodes') or [])
            meta['edges_count'] = len(graph.get('edges') or [])

        return {
            'response_text': json.dumps(payload, ensure_ascii=False),
            'metadata': meta,
        }

    def run_action(self, action_id, inputs, host):
        return {'error': f'unknown action: {action_id}'}
