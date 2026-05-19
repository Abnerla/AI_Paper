# -*- coding: utf-8 -*-
"""
图表编辑窗子进程入口（P3.A）。

由 main.py 在检测到命令行参数 `--diagram-webview <input.json>` 时调度。
读取输入 JSON 中的 block + 能力清单，启动 pywebview 加载 host.html，
通过 JS Bridge 接收前端保存事件，把新 block 写入 out_path 后退出。
"""

from __future__ import annotations

import json
import os
import sys
import traceback


def _read_payload(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as handle:
        return json.load(handle)


def _resolve_host_uri() -> str:
    from modules.runtime_paths import resolve_resource_path
    abs_path = os.path.abspath(resolve_resource_path('Management', 'web_assets', 'host.html'))
    return 'file:///' + abs_path.replace('\\', '/')


class _Bridge:
    """暴露给前端的 JS API。pywebview 自动把公共方法暴露为 window.pywebview.api.*。"""

    def __init__(self, payload: dict):
        self._block = payload.get('block') or {}
        self._capabilities = payload.get('capabilities') or {}
        self._out_path = payload.get('out_path') or ''
        self._mode = payload.get('mode') or 'edit'
        self._export_format = payload.get('export_format') or ''
        self._saved = False

    # ---- 前端调用 ----
    def load_diagram(self) -> dict:
        return {
            'block': self._block,
            'capabilities': self._capabilities,
            'mode': self._mode,
            'export_format': self._export_format,
        }

    def save_diagram(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            return {'ok': False, 'error': 'invalid payload'}
        old_xml = str(self._block.get('mxgraph_xml') or '').strip()
        merged = dict(self._block)
        merged.update(payload)

        new_xml = str(merged.get('mxgraph_xml') or '').strip()
        if old_xml and new_xml and old_xml != new_xml:
            history = list(merged.get('history') or self._block.get('history') or [])
            if not history or str(history[-1].get('mxgraph_xml') or '').strip() != old_xml:
                history.append({
                    'mxgraph_xml': old_xml,
                    'updated_at': self._block.get('updated_at', 0),
                })
            merged['history'] = history

        if merged.get('authoring_format') == 'drawio' and new_xml:
            try:
                from modules.diagram_format import mxgraph_xml_to_json
                from modules.diagram_tools import validate_mxgraph_xml
                validate_mxgraph_xml(new_xml)
                merged['json_graph'] = mxgraph_xml_to_json(merged['mxgraph_xml'])
            except Exception as exc:
                return {'ok': False, 'error': str(exc)}
        try:
            from modules.diagram_blocks import sanitize_diagram_block
            from modules.diagram_thumbnail import render_placeholder_b64
            sanitized = sanitize_diagram_block(merged) or merged
            if not sanitized.get('thumbnail_b64') and not sanitized.get('thumbnail_path'):
                thumb_b64, thumb_path = render_placeholder_b64(
                    sanitized.get('json_graph') or {},
                    caption=sanitized.get('caption') or '',
                )
                if thumb_b64:
                    sanitized['thumbnail_b64'] = thumb_b64
                if thumb_path:
                    sanitized['thumbnail_path'] = thumb_path
            merged = sanitized
        except Exception:
            pass
        try:
            with open(self._out_path, 'w', encoding='utf-8') as handle:
                json.dump(merged, handle, ensure_ascii=False)
        except OSError as exc:
            return {'ok': False, 'error': str(exc)}
        self._saved = True
        return {'ok': True}

    def save_export(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            return {'ok': False, 'error': 'invalid payload'}
        export_payload = {
            'format': str(payload.get('format') or self._export_format or '').strip(),
            'data': str(payload.get('data') or '').strip(),
            'mime_type': str(payload.get('mime_type') or '').strip(),
        }
        if not export_payload['data']:
            return {'ok': False, 'error': 'empty export data'}
        try:
            with open(self._out_path, 'w', encoding='utf-8') as handle:
                json.dump(export_payload, handle, ensure_ascii=False)
        except OSError as exc:
            return {'ok': False, 'error': str(exc)}
        self._saved = True
        return {'ok': True}

    def mermaid_to_mxgraph(self, text: str) -> dict:
        """供前端切换到 drawio 视图时把当前 mermaid 文本转 mxgraph XML。"""
        try:
            from modules.diagram_format import mermaid_to_json, json_to_mxgraph_xml
            graph = mermaid_to_json(text or '')
            xml = json_to_mxgraph_xml(graph)
            return {'ok': True, 'xml': xml}
        except Exception as exc:
            return {'ok': False, 'error': str(exc)}

    def close_window(self) -> dict:
        try:
            import webview
            for win in list(webview.windows):
                win.destroy()
        except Exception:
            pass
        return {'ok': True}


def run(input_path: str) -> int:
    try:
        payload = _read_payload(input_path)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f'[diagram-webview] cannot read input: {exc}\n')
        return 2

    try:
        import webview
    except ImportError:
        sys.stderr.write('[diagram-webview] pywebview not installed\n')
        return 3

    bridge = _Bridge(payload)
    title = '编辑图表'
    block = payload.get('block') or {}
    if isinstance(block, dict):
        cap = block.get('caption') or block.get('diagram_id') or ''
        if cap:
            title = f'编辑图表 - {cap}'

    try:
        host_uri = _resolve_host_uri()
    except Exception as exc:
        sys.stderr.write(f'[diagram-webview] resolve host.html failed: {exc}\n')
        return 4

    webview.create_window(
        title=title,
        url=host_uri,
        js_api=bridge,
        width=1280, height=820,
        resizable=True,
    )
    try:
        webview.start(debug=False)
    except Exception:
        sys.stderr.write('[diagram-webview] webview start failed:\n')
        traceback.print_exc(file=sys.stderr)
        return 5

    return 0 if bridge._saved else 1


def maybe_run_from_argv(argv=None) -> bool:
    args = list(sys.argv if argv is None else argv)
    from modules.diagram_webview import WEBVIEW_WORKER_FLAG
    if len(args) < 3 or args[1] != WEBVIEW_WORKER_FLAG:
        return False
    raise SystemExit(run(args[2]))


if __name__ == '__main__':
    if len(sys.argv) >= 2:
        raise SystemExit(run(sys.argv[1]))
    sys.exit(0)
