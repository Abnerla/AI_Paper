# -*- coding: utf-8 -*-
"""
AI 图表服务。

模型只返回结构化工具动作，Python 负责执行工具并更新图表块。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

from modules.diagram_blocks import (
    DIAGRAM_FORMAT_DRAWIO,
    DIAGRAM_KIND_DEFAULT,
    new_diagram_block,
    sanitize_diagram_block,
)
from modules.diagram_format import mxgraph_xml_to_json
from modules.diagram_thumbnail import render_placeholder_b64
from modules.diagram_tools import (
    DiagramToolError,
    apply_diagram_operations,
    get_shape_library,
    is_mxcell_xml_complete,
    validate_mxgraph_xml,
    wrap_mx_cells,
)
from modules.prompt_center import PromptCenter, PromptCenterError


DIAGRAM_CHAT_SYSTEM = """
你是 draw.io 图表助手。用户会用自然语言要求创建或修改图表。
你必须只返回 JSON 对象，不输出 Markdown。

返回格式：
{
  "message": "给用户看的简短中文说明",
  "tool": "display_diagram | edit_diagram | append_diagram | get_shape_library | none",
  "xml": "display_diagram 或 append_diagram 使用的 mxCell XML 片段",
  "operations": [
    {"operation": "add|update|delete", "cell_id": "单元ID", "new_xml": "完整 mxCell XML"}
  ],
  "library": "图形库名称"
}

规则：
1. 新建图或大幅重构时使用 display_diagram，只输出裸 mxCell 元素，不包含 mxGraphModel、root、mxfile、id=0、id=1。
2. 小范围修改当前图时使用 edit_diagram，按 cell_id 增删改。
3. display_diagram 输出过长时，后续使用 append_diagram 继续输出裸 mxCell 片段。
4. 涉及 AWS、Azure、GCP、Kubernetes、BPMN、网络等图形库时先使用 get_shape_library。
5. 所有 mxCell 必须有唯一 id、parent 和 mxGeometry；边必须引用已存在的 source/target。
6. 需要避免重叠，图形坐标优先控制在 x=0..900、y=0..700 范围内。
"""


@dataclass
class DiagramAIResult:
    block: dict | None
    message: str
    tool_name: str
    tool_output: str
    error: str = ''
    pending_xml: str = ''

    def as_dict(self) -> dict:
        return {
            'block': copy.deepcopy(self.block) if self.block else None,
            'message': self.message,
            'tool_name': self.tool_name,
            'tool_output': self.tool_output,
            'error': self.error,
            'pending_xml': self.pending_xml,
        }


class DiagramAIService:
    """自然语言图表服务。"""

    def __init__(self, api_client):
        self.api_client = api_client
        self.prompt_center = PromptCenter(getattr(api_client, 'config', None))

    def run_instruction(
        self,
        instruction: str,
        *,
        current_block: dict | None = None,
        pending_xml: str = '',
        knowledge_context: dict | None = None,
        attachment_context: str = '',
        multimodal_attachments: list[dict] | None = None,
        minimal_style: bool = False,
        custom_system_message: str = '',
        tool_feedback: str = '',
        event_callback=None,
        max_continuations: int = 2,
        max_tool_retries: int = 2,
    ) -> DiagramAIResult:
        instruction = str(instruction or '').strip()
        if not instruction:
            raise ValueError('请输入图表指令。')

        block = sanitize_diagram_block(current_block or {}) if isinstance(current_block, dict) else None
        current_xml = _block_xml(block)
        previous_xml = ''
        if block and isinstance(block.get('history'), list) and block['history']:
            previous_xml = str(block['history'][-1].get('mxgraph_xml') or '')

        next_pending = str(pending_xml or '')
        feedback = str(tool_feedback or '')
        continuations = 0
        retries = 0
        library_queries = 0

        while True:
            _emit_event(event_callback, 'request', '正在请求模型生成图表工具动作。')
            payload = self._request_tool(
                instruction,
                current_xml=current_xml,
                previous_xml=previous_xml,
                pending_xml=next_pending,
                knowledge_context=knowledge_context,
                attachment_context=attachment_context,
                tool_feedback=feedback,
                multimodal_attachments=multimodal_attachments,
                minimal_style=minimal_style,
                custom_system_message=custom_system_message,
            )
            tool_name = str(payload.get('tool') or 'none').strip()
            _emit_event(event_callback, 'tool_call', f'模型选择工具：{tool_name}', {'tool': tool_name})

            if tool_name == 'get_shape_library' and library_queries < 2:
                library_queries += 1
                library = str(payload.get('library') or '').strip()
                _emit_event(event_callback, 'shape_library', f'正在读取图形库：{library}', {'library': library})
                library_text = get_shape_library(library)
                feedback = _join_feedback(feedback, f'图形库 {library} 资料：\n{library_text[:12000]}')
                continue

            result = self._execute_payload(payload, block=block, current_xml=current_xml, pending_xml=next_pending)
            _emit_event(
                event_callback,
                'tool_result',
                result.error or result.tool_output or result.message,
                {'tool': result.tool_name, 'error': result.error, 'pending': bool(result.pending_xml)},
            )

            if result.error and retries < max_tool_retries:
                retries += 1
                feedback = _join_feedback(feedback, _repair_feedback(result, current_xml, retries, max_tool_retries))
                _emit_event(
                    event_callback,
                    'retry',
                    f'工具结果需要修正，正在第 {retries} 次重试。',
                    {'attempt': retries, 'max_attempts': max_tool_retries, 'error': result.error},
                )
                continue

            if result.pending_xml and result.tool_name in {'display_diagram', 'append_diagram'} and continuations < max_continuations:
                continuations += 1
                next_pending = result.pending_xml
                feedback = _join_feedback(
                    feedback,
                    (
                        f'上一轮图表 XML 片段尚未完整，继续使用 append_diagram 输出剩余 mxCell。'
                        f'\n续写次数：{continuations}/{max_continuations}'
                        f'\n当前片段结尾：\n{next_pending[-1200:]}'
                    ),
                )
                _emit_event(
                    event_callback,
                    'continuation',
                    f'检测到图表片段未完整，正在第 {continuations} 次续写。',
                    {'attempt': continuations, 'max_attempts': max_continuations},
                )
                continue

            return result

    def _request_tool(
        self,
        instruction: str,
        *,
        current_xml: str,
        previous_xml: str = '',
        pending_xml: str = '',
        knowledge_context: dict | None = None,
        attachment_context: str = '',
        tool_feedback: str = '',
        multimodal_attachments: list[dict] | None = None,
        minimal_style: bool = False,
        custom_system_message: str = '',
    ) -> dict:
        system, prompt = self._render_chat_prompt(
            instruction,
            current_xml=current_xml,
            previous_xml=previous_xml,
            pending_xml=pending_xml,
            knowledge_context=knowledge_context,
            attachment_context=attachment_context,
            tool_feedback=tool_feedback,
            minimal_style=minimal_style,
            custom_system_message=custom_system_message,
        )

        kwargs = {
            'prompt': prompt,
            'system': system,
            'usage_context': {
                'page_id': 'ai_diagram',
                'scene_id': 'ai_diagram.chat',
                'action': 'diagram.chat',
            },
            'schema_name': 'diagram.chat_tool.v1',
        }
        if multimodal_attachments:
            kwargs['multimodal_attachments'] = multimodal_attachments
        try:
            payload = self.api_client.call_json_sync(**kwargs)
        except TypeError:
            kwargs.pop('multimodal_attachments', None)
            payload = self.api_client.call_json_sync(**kwargs)
        if not isinstance(payload, dict):
            raise ValueError('AI 返回格式不是 JSON 对象。')
        return payload

    def _render_chat_prompt(
        self,
        instruction: str,
        *,
        current_xml: str,
        previous_xml: str = '',
        pending_xml: str = '',
        knowledge_context: dict | None = None,
        attachment_context: str = '',
        tool_feedback: str = '',
        minimal_style: bool = False,
        custom_system_message: str = '',
    ) -> tuple[str, str]:
        values = {
            'instruction': instruction,
            'current_xml': current_xml or '(空图)',
            'previous_xml': (previous_xml or '')[:50000],
            'pending_xml': (pending_xml or '')[-1200:],
            'knowledge_context': _knowledge_text(knowledge_context),
            'attachment_context': str(attachment_context or '')[:24000],
            'tool_feedback': str(tool_feedback or ''),
        }
        try:
            rendered = self.prompt_center.render_scene('ai_diagram.chat', values)
        except (PromptCenterError, KeyError, ValueError):
            system = DIAGRAM_CHAT_SYSTEM
            prompt = _fallback_prompt(values)
            return _augment_system_prompt(system, minimal_style=minimal_style, custom_system_message=custom_system_message), prompt
        system = rendered.get('system') or DIAGRAM_CHAT_SYSTEM
        prompt = rendered.get('prompt') or _fallback_prompt(values)
        return _augment_system_prompt(system, minimal_style=minimal_style, custom_system_message=custom_system_message), prompt

    def _execute_payload(
        self,
        payload: dict,
        *,
        block: dict | None,
        current_xml: str,
        pending_xml: str,
    ) -> DiagramAIResult:
        tool_name = str(payload.get('tool') or 'none').strip()
        message = str(payload.get('message') or '').strip()

        try:
            if tool_name == 'display_diagram':
                fragment = str(payload.get('xml') or '')
                if not is_mxcell_xml_complete(fragment):
                    return DiagramAIResult(
                        block,
                        message or '图表片段尚未完整，正在继续生成。',
                        tool_name,
                        'display_diagram 已缓存片段',
                        pending_xml=fragment,
                    )
                xml = wrap_mx_cells(fragment)
                next_block = diagram_block_from_xml(xml, previous_block=block, caption=_caption_from_payload(payload, block))
                return DiagramAIResult(next_block, message or '已生成图表。', tool_name, 'display_diagram 执行成功')

            if tool_name == 'edit_diagram':
                if not current_xml:
                    raise DiagramToolError('当前没有可编辑的 draw.io XML。')
                edited_xml, errors = apply_diagram_operations(current_xml, payload.get('operations') or [])
                if errors:
                    error_text = '\n'.join(f'{item.get("cell_id", "")}: {item.get("message", "")}' for item in errors)
                    raise DiagramToolError(error_text)
                next_block = diagram_block_from_xml(edited_xml, previous_block=block, caption=_caption_from_payload(payload, block))
                return DiagramAIResult(next_block, message or '已修改图表。', tool_name, 'edit_diagram 执行成功')

            if tool_name == 'append_diagram':
                fragment = str(payload.get('xml') or '')
                combined = f'{pending_xml}{fragment}'
                if not is_mxcell_xml_complete(combined):
                    return DiagramAIResult(
                        block,
                        message or '图表片段尚未完整，等待继续生成。',
                        tool_name,
                        'append_diagram 已缓存片段',
                        pending_xml=combined,
                    )
                xml = wrap_mx_cells(combined)
                next_block = diagram_block_from_xml(xml, previous_block=block, caption=_caption_from_payload(payload, block))
                return DiagramAIResult(next_block, message or '已完成图表续写。', tool_name, 'append_diagram 执行成功')

            if tool_name == 'none':
                return DiagramAIResult(block, message or '未执行图表操作。', tool_name, 'none')

            raise DiagramToolError(f'未知工具：{tool_name}')
        except Exception as exc:
            return DiagramAIResult(
                block,
                message or '图表操作失败。',
                tool_name,
                '',
                error=str(exc),
                pending_xml=pending_xml,
            )


def diagram_block_from_xml(xml_text: str, *, previous_block: dict | None = None, caption: str = '') -> dict:
    validate_mxgraph_xml(xml_text)
    graph = mxgraph_xml_to_json(xml_text)
    history = []
    if previous_block and previous_block.get('mxgraph_xml'):
        history = list(previous_block.get('history') or [])
        snapshot = {
            'mxgraph_xml': previous_block.get('mxgraph_xml', ''),
            'updated_at': previous_block.get('updated_at', 0),
            'caption': previous_block.get('caption', ''),
        }
        if previous_block.get('thumbnail_b64'):
            snapshot['thumbnail_b64'] = previous_block.get('thumbnail_b64')
        if previous_block.get('thumbnail_path'):
            snapshot['thumbnail_path'] = previous_block.get('thumbnail_path')
        history.append(snapshot)

    block = new_diagram_block(
        diagram_id=(previous_block or {}).get('diagram_id'),
        diagram_kind=(previous_block or {}).get('diagram_kind', DIAGRAM_KIND_DEFAULT),
        authoring_format=DIAGRAM_FORMAT_DRAWIO,
        mermaid=(previous_block or {}).get('mermaid', ''),
        json_graph=graph,
        mxgraph_xml=xml_text,
        caption=caption or (previous_block or {}).get('caption', ''),
        display_size=(previous_block or {}).get('display_size'),
        history=history,
    )
    thumb_b64, thumb_path = render_placeholder_b64(
        block.get('json_graph') or {},
        caption=block.get('caption') or '',
    )
    if thumb_b64:
        block['thumbnail_b64'] = thumb_b64
    if thumb_path:
        block['thumbnail_path'] = thumb_path
    return sanitize_diagram_block(block) or block


def _block_xml(block: dict | None) -> str:
    if not block:
        return ''
    return str(block.get('mxgraph_xml') or '').strip()


def _caption_from_payload(payload: dict, block: dict | None) -> str:
    caption = str(payload.get('caption') or '').strip()
    if caption:
        return caption
    return str((block or {}).get('caption') or '').strip()


def _knowledge_text(knowledge_context: dict | None) -> str:
    if not isinstance(knowledge_context, dict):
        return ''
    context_text = str(
        knowledge_context.get('context_text')
        or knowledge_context.get('content')
        or knowledge_context.get('text')
        or ''
    ).strip()
    return context_text[:12000]


def _fallback_prompt(values: dict) -> str:
    pieces = [
        f'用户指令：\n{values.get("instruction", "")}',
        f'当前图表 XML：\n{values.get("current_xml", "")}',
    ]
    if values.get('previous_xml'):
        pieces.append(f'上一版图表 XML：\n{values["previous_xml"]}')
    if values.get('pending_xml'):
        pieces.append(f'待续写的 mxCell 片段结尾：\n{values["pending_xml"]}')
    if values.get('knowledge_context'):
        pieces.append(f'可用知识库资料：\n{values["knowledge_context"]}')
    if values.get('attachment_context'):
        pieces.append(f'附件资料：\n{values["attachment_context"]}')
    if values.get('tool_feedback'):
        pieces.append(str(values['tool_feedback']))
    return '\n\n'.join(pieces)


def _augment_system_prompt(system: str, *, minimal_style: bool = False, custom_system_message: str = '') -> str:
    parts = [str(system or DIAGRAM_CHAT_SYSTEM).strip()]
    if minimal_style:
        parts.append(
            '图表风格要求：使用简约、克制、文档友好的样式。优先使用白底、细边框、少量强调色，'
            '避免装饰性渐变、复杂阴影和过度饱和配色。'
        )
    custom = str(custom_system_message or '').strip()
    if custom:
        parts.append(f'自定义系统提示：\n{custom[:5000]}')
    return '\n\n'.join(part for part in parts if part)


def _join_feedback(*items: str) -> str:
    parts = [str(item or '').strip() for item in items if str(item or '').strip()]
    return '\n\n'.join(parts)[-24000:]


def _repair_feedback(result: DiagramAIResult, current_xml: str, attempt: int, max_attempts: int) -> str:
    return (
        f'上一次工具执行失败，需要修正后重新返回工具 JSON。'
        f'\n重试次数：{attempt}/{max_attempts}'
        f'\n失败工具：{result.tool_name or "unknown"}'
        f'\n错误信息：{result.error}'
        f'\n当前图表 XML：\n{str(current_xml or "")[:12000]}'
    )


def _emit_event(callback, event_type: str, message: str, data: dict | None = None) -> None:
    if not callable(callback):
        return
    try:
        callback({
            'type': str(event_type or ''),
            'message': str(message or ''),
            'data': copy.deepcopy(data or {}),
        })
    except Exception:
        pass
