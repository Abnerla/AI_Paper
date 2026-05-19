# -*- coding: utf-8 -*-
"""AI 图表视觉校验。"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass

from modules.diagram_export import render_preview_png_bytes


DIAGRAM_VLM_SYSTEM = """
你是图表视觉校验助手。请根据输入图片检查图表可读性、布局、连线、标签和重叠问题。
只返回 JSON 对象，不输出 Markdown。

返回格式：
{
  "ok": true,
  "summary": "简短中文结论",
  "issues": [
    {"severity": "error|warning|info", "message": "具体问题"}
  ],
  "suggestions": ["可执行修改建议"]
}
"""

DIAGRAM_VLM_PROMPT = """
请校验当前图表截图。
重点检查：
1. 文字是否清晰可读。
2. 节点、标签、连接线是否明显重叠。
3. 连线方向和布局是否容易理解。
4. 是否存在缺失标签、无意义空白、内容超出画布。
5. 是否适合作为论文或技术文档插图。
"""


@dataclass
class DiagramVisualValidationResult:
    ok: bool
    summary: str
    issues: list[dict]
    suggestions: list[str]
    skipped: bool = False
    error: str = ''

    def as_dict(self) -> dict:
        return {
            'ok': bool(self.ok),
            'summary': self.summary,
            'issues': list(self.issues or []),
            'suggestions': list(self.suggestions or []),
            'skipped': bool(self.skipped),
            'error': self.error,
        }


def validate_diagram_visual(api_client, block: dict | None, *, request_timeout=90) -> DiagramVisualValidationResult:
    """使用当前模型配置对图表预览图做视觉校验。"""
    if api_client is None or not hasattr(api_client, 'call_json_sync'):
        return DiagramVisualValidationResult(False, '当前模型调用链路不可用。', [], [], skipped=True)
    if hasattr(api_client, 'supports_multimodal_attachments'):
        try:
            if not api_client.supports_multimodal_attachments(
                usage_context={'page_id': 'ai_diagram', 'scene_id': 'ai_diagram.visual_validation'}
            ):
                return DiagramVisualValidationResult(False, '当前模型不支持图片输入，已跳过视觉校验。', [], [], skipped=True)
        except Exception as exc:
            return DiagramVisualValidationResult(False, f'无法确认模型视觉能力：{exc}', [], [], skipped=True)

    try:
        png_bytes = render_preview_png_bytes(block or {})
    except Exception as exc:
        return DiagramVisualValidationResult(False, f'无法生成视觉校验图片：{exc}', [], [], skipped=True)

    attachment = {
        'type': 'image',
        'title': '当前图表预览',
        'mime_type': 'image/png',
        'data': base64.b64encode(png_bytes).decode('ascii'),
        'size_bytes': len(png_bytes),
    }
    try:
        kwargs = {
            'prompt': DIAGRAM_VLM_PROMPT,
            'system': DIAGRAM_VLM_SYSTEM,
            'request_timeout': request_timeout,
            'usage_context': {
                'page_id': 'ai_diagram',
                'scene_id': 'ai_diagram.visual_validation',
                'action': 'diagram.visual_validation',
            },
            'schema_name': 'diagram.visual_validation.v1',
            'multimodal_attachments': [attachment],
        }
        try:
            payload = api_client.call_json_sync(**kwargs)
        except TypeError:
            return DiagramVisualValidationResult(False, '当前 APIClient 不支持图片输入，已跳过视觉校验。', [], [], skipped=True)
    except Exception as exc:
        return DiagramVisualValidationResult(False, '视觉校验失败。', [], [], error=str(exc))

    if not isinstance(payload, dict):
        try:
            payload = json.loads(str(payload or '{}'))
        except Exception:
            payload = {}

    issues = payload.get('issues') if isinstance(payload.get('issues'), list) else []
    suggestions = payload.get('suggestions') if isinstance(payload.get('suggestions'), list) else []
    return DiagramVisualValidationResult(
        ok=bool(payload.get('ok', not issues)),
        summary=str(payload.get('summary') or '').strip() or ('视觉校验通过。' if not issues else '视觉校验发现问题。'),
        issues=[item for item in issues if isinstance(item, dict)],
        suggestions=[str(item).strip() for item in suggestions if str(item).strip()],
    )
