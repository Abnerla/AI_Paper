# -*- coding: utf-8 -*-
"""AI 图表会话与用户提示模板存储。"""

from __future__ import annotations

import copy
import time
import uuid

from modules.diagram_context import sanitize_reference_items


SESSIONS_KEY = 'ai_diagram_sessions'
TEMPLATES_KEY = 'ai_diagram_prompt_templates'
MAX_SESSIONS = 50
MAX_TEMPLATES = 80


def list_diagram_sessions(config_mgr, query=''):
    records = _clean_sessions(_get_setting(config_mgr, SESSIONS_KEY, []))
    needle = str(query or '').strip().lower()
    if needle:
        records = [
            record for record in records
            if needle in record.get('title', '').lower()
            or needle in record.get('summary', '').lower()
        ]
    return records


def save_diagram_session(config_mgr, state, *, title='', session_id=''):
    records = _clean_sessions(_get_setting(config_mgr, SESSIONS_KEY, []))
    now_ts = int(time.time())
    target_id = str(session_id or '').strip() or f'diagram_session_{uuid.uuid4().hex[:12]}'
    session_title = str(title or '').strip() or str((state or {}).get('caption') or '').strip() or '未命名图表会话'
    summary = _state_summary(state)
    next_record = {
        'id': target_id,
        'title': session_title[:120],
        'summary': summary[:300],
        'updated_at': now_ts,
        'state': _clean_state(state),
    }
    records = [record for record in records if record.get('id') != target_id]
    records.insert(0, next_record)
    records = records[:MAX_SESSIONS]
    _set_setting(config_mgr, SESSIONS_KEY, records)
    return copy.deepcopy(next_record)


def get_diagram_session(config_mgr, session_id):
    target = str(session_id or '').strip()
    for record in list_diagram_sessions(config_mgr):
        if record.get('id') == target:
            return copy.deepcopy(record)
    return None


def delete_diagram_session(config_mgr, session_id):
    target = str(session_id or '').strip()
    records = [record for record in list_diagram_sessions(config_mgr) if record.get('id') != target]
    _set_setting(config_mgr, SESSIONS_KEY, records)
    return records


def list_prompt_templates(config_mgr, query=''):
    records = _clean_templates(_get_setting(config_mgr, TEMPLATES_KEY, []))
    needle = str(query or '').strip().lower()
    if needle:
        records = [
            record for record in records
            if needle in record.get('name', '').lower()
            or needle in record.get('content', '').lower()
        ]
    return records


def save_prompt_template(config_mgr, content, *, name='', template_id=''):
    text = str(content or '').strip()
    if not text:
        raise ValueError('提示模板内容不能为空。')
    records = _clean_templates(_get_setting(config_mgr, TEMPLATES_KEY, []))
    now_ts = int(time.time())
    target_id = str(template_id or '').strip() or f'diagram_template_{uuid.uuid4().hex[:12]}'
    template_name = str(name or '').strip() or text.splitlines()[0][:40] or '未命名模板'
    next_record = {
        'id': target_id,
        'name': template_name[:80],
        'content': text[:12000],
        'pinned': False,
        'run_count': 0,
        'last_used_at': 0,
        'updated_at': now_ts,
    }
    records = [record for record in records if record.get('id') != target_id]
    records.insert(0, next_record)
    records = records[:MAX_TEMPLATES]
    _set_setting(config_mgr, TEMPLATES_KEY, records)
    return copy.deepcopy(next_record)


def update_prompt_template(config_mgr, template_id, updates):
    target = str(template_id or '').strip()
    records = _clean_templates(_get_setting(config_mgr, TEMPLATES_KEY, []))
    changed = None
    now_ts = int(time.time())
    for index, record in enumerate(records):
        if record.get('id') != target:
            continue
        next_record = dict(record)
        if 'name' in updates:
            name = str(updates.get('name') or '').strip()
            if name:
                next_record['name'] = name[:80]
        if 'content' in updates:
            content = str(updates.get('content') or '').strip()
            if content:
                next_record['content'] = content[:12000]
        if 'pinned' in updates:
            next_record['pinned'] = bool(updates.get('pinned'))
        if updates.get('touch', True):
            next_record['updated_at'] = now_ts
        records[index] = next_record
        changed = next_record
        break
    if changed is None:
        return None
    _set_setting(config_mgr, TEMPLATES_KEY, records)
    return copy.deepcopy(changed)


def duplicate_prompt_template(config_mgr, template_id, *, suffix=' 副本'):
    target = str(template_id or '').strip()
    for record in list_prompt_templates(config_mgr):
        if record.get('id') != target:
            continue
        return save_prompt_template(
            config_mgr,
            record.get('content', ''),
            name=f'{record.get("name", "未命名模板")}{suffix}',
        )
    return None


def toggle_prompt_template_pinned(config_mgr, template_id):
    target = str(template_id or '').strip()
    for record in list_prompt_templates(config_mgr):
        if record.get('id') == target:
            return update_prompt_template(
                config_mgr,
                target,
                {'pinned': not bool(record.get('pinned')), 'touch': False},
            )
    return None


def increment_prompt_template_run_count(config_mgr, template_id):
    target = str(template_id or '').strip()
    records = _clean_templates(_get_setting(config_mgr, TEMPLATES_KEY, []))
    now_ts = int(time.time())
    changed = None
    for index, record in enumerate(records):
        if record.get('id') != target:
            continue
        next_record = dict(record)
        next_record['run_count'] = _safe_int(next_record.get('run_count')) + 1
        next_record['last_used_at'] = now_ts
        records[index] = next_record
        changed = next_record
        break
    if changed is None:
        return None
    _set_setting(config_mgr, TEMPLATES_KEY, records)
    return copy.deepcopy(changed)


def export_prompt_templates(config_mgr):
    return {
        'type': 'ai_diagram_prompt_templates',
        'version': 1,
        'templates': list_prompt_templates(config_mgr),
    }


def import_prompt_templates(config_mgr, payload):
    if isinstance(payload, list):
        templates = payload
    elif isinstance(payload, dict):
        templates = payload.get('templates') if isinstance(payload.get('templates'), list) else []
    else:
        templates = []
    imported = []
    existing = list_prompt_templates(config_mgr)
    existing_keys = {
        (record.get('name', '').strip().lower(), record.get('content', '').strip())
        for record in existing
    }
    for item in templates:
        if not isinstance(item, dict):
            continue
        content = str(item.get('content') or item.get('prompt') or '').strip()
        if not content:
            continue
        name = str(item.get('name') or item.get('title') or '').strip() or content.splitlines()[0][:40]
        key = (name.lower(), content)
        if key in existing_keys:
            continue
        record = save_prompt_template(config_mgr, content, name=name)
        if item.get('pinned'):
            record = update_prompt_template(config_mgr, record['id'], {'pinned': True, 'touch': False}) or record
        imported.append(record)
        existing_keys.add(key)
    return imported


def delete_prompt_template(config_mgr, template_id):
    target = str(template_id or '').strip()
    records = [record for record in list_prompt_templates(config_mgr) if record.get('id') != target]
    _set_setting(config_mgr, TEMPLATES_KEY, records)
    return records


def _clean_sessions(records):
    cleaned = []
    for record in list(records or []):
        if not isinstance(record, dict):
            continue
        state = _clean_state(record.get('state') or {})
        if not state:
            continue
        cleaned.append({
            'id': str(record.get('id') or '').strip() or f'diagram_session_{uuid.uuid4().hex[:12]}',
            'title': str(record.get('title') or '').strip()[:120] or '未命名图表会话',
            'summary': str(record.get('summary') or '').strip()[:300],
            'updated_at': _safe_int(record.get('updated_at')),
            'state': state,
        })
    cleaned.sort(key=lambda item: item.get('updated_at', 0), reverse=True)
    return cleaned[:MAX_SESSIONS]


def _clean_templates(records):
    cleaned = []
    for record in list(records or []):
        if not isinstance(record, dict):
            continue
        content = str(record.get('content') or '').strip()
        if not content:
            continue
        cleaned.append({
            'id': str(record.get('id') or '').strip() or f'diagram_template_{uuid.uuid4().hex[:12]}',
            'name': str(record.get('name') or '').strip()[:80] or '未命名模板',
            'content': content[:12000],
            'pinned': bool(record.get('pinned', False)),
            'run_count': _safe_int(record.get('run_count')),
            'last_used_at': _safe_int(record.get('last_used_at')),
            'updated_at': _safe_int(record.get('updated_at')),
        })
    cleaned.sort(key=lambda item: (not bool(item.get('pinned')), -item.get('updated_at', 0), item.get('name', '')))
    return cleaned[:MAX_TEMPLATES]


def _clean_state(state):
    if not isinstance(state, dict):
        return {}
    cleaned = copy.deepcopy(state)
    messages = cleaned.get('messages')
    if isinstance(messages, list):
        cleaned['messages'] = [item for item in messages if isinstance(item, dict)][-100:]
    references = cleaned.get('references')
    if isinstance(references, list):
        cleaned['references'] = sanitize_reference_items(references)
    return cleaned


def _state_summary(state):
    block = (state or {}).get('current_block') if isinstance(state, dict) else {}
    if isinstance(block, dict):
        graph = block.get('json_graph') or {}
        nodes = len(graph.get('nodes') or []) if isinstance(graph, dict) else 0
        edges = len(graph.get('edges') or []) if isinstance(graph, dict) else 0
        caption = block.get('caption') or block.get('diagram_id') or '图表'
        return f'{caption}，节点 {nodes}，连线 {edges}'
    messages = (state or {}).get('messages') if isinstance(state, dict) else []
    return f'对话消息 {len(messages or [])} 条'


def _get_setting(config_mgr, key, default):
    if config_mgr and hasattr(config_mgr, 'get_setting'):
        return config_mgr.get_setting(key, default)
    return default


def _set_setting(config_mgr, key, value):
    if not config_mgr or not hasattr(config_mgr, 'set_setting'):
        return
    config_mgr.set_setting(key, value)
    if hasattr(config_mgr, 'save'):
        config_mgr.save()


def _safe_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
