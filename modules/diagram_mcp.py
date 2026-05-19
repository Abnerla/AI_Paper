# -*- coding: utf-8 -*-
"""本地 AI 图表 MCP 兼容工具服务。"""

from __future__ import annotations

import base64
import html
import json
import mimetypes
import os
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from modules.diagram_export import export_diagram_file
from modules.diagram_tools import apply_diagram_operations, validate_mxgraph_xml, wrap_mx_cells
from modules.runtime_paths import resolve_resource_path


DEFAULT_EMPTY_DIAGRAM = (
    '<mxGraphModel dx="1024" dy="768" grid="1" gridSize="10" guides="1" tooltips="1" '
    'connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1024" '
    'pageHeight="768" math="0" shadow="0"><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
    '</root></mxGraphModel>'
)

MCP_PROTOCOL_VERSION = '2024-11-05'
MCP_SERVER_INFO = {'name': 'ai-paper-diagram-mcp', 'version': '0.1.0'}
MCP_WORKFLOW_PROMPT = """# Draw.io 图表工作流

1. 调用 start_session 创建会话；HTTP 模式下会返回本地预览地址 preview_url。
2. 新建图表时调用 create_new_diagram，并传入完整 mxGraphModel XML 或 mxCell 片段。
3. 修改已有图表前先调用 get_diagram 获取当前 XML，再调用 edit_diagram 执行 add/update/delete 操作。
4. 调用 export_diagram 导出 drawio、xml、png、svg 或 drawio.svg。
5. 调用 restore_history 可恢复 get_diagram 返回的历史版本索引。
6. add/update 操作的 new_xml 必须是完整 mxCell，delete 会级联删除关联边和子节点。"""

MAX_HTTP_BODY_BYTES = 10 * 1024 * 1024
MCP_SYNC_TIMEOUT_SECONDS = 2.5
MCP_EXPORT_TIMEOUT_SECONDS = 8.0


class DiagramMCPService:
    """提供 start_session/create_new_diagram/edit_diagram/get_diagram/export_diagram 工具。"""

    def __init__(self, *, on_update=None):
        self.sessions = {}
        self.current_session_id = ''
        self.on_update = on_update
        self.preview_base_url = ''
        self._lock = threading.RLock()

    def start_session(self, xml='', *, notify=True):
        session_id = f'mcp-{uuid.uuid4().hex[:12]}'
        diagram_xml = _normalize_diagram_xml(xml or DEFAULT_EMPTY_DIAGRAM)
        now = int(time.time())
        with self._lock:
            self.sessions[session_id] = {
                'id': session_id,
                'xml': diagram_xml,
                'history': [],
                'version': 1,
                'created_at': now,
                'updated_at': now,
                'browser_ready': False,
                'sync_requested': 0,
                'export_format': '',
                'export_data': '',
                'native_exports': {},
            }
            self.current_session_id = session_id
        if notify:
            self._notify_update(session_id)
        payload = {'session_id': session_id, 'xml': diagram_xml}
        preview_url = self._preview_url(session_id)
        if preview_url:
            payload['preview_url'] = preview_url
        return payload

    def create_new_diagram(self, session_id, xml):
        session_id = self._session_key(session_id)
        self._refresh_browser_state(session_id)
        diagram_xml = _normalize_diagram_xml(xml)
        with self._lock:
            session = self.sessions[session_id]
            current_xml = session.get('xml', '')
            if current_xml and current_xml != diagram_xml:
                session['history'].append(
                    _history_entry(current_xml, session.get('updated_at', 0), thumbnail=_session_svg(session))
                )
            self._set_session_xml_locked(session, diagram_xml)
        self._notify_update(session_id)
        return {'session_id': session_id, 'xml': diagram_xml, 'stats': validate_mxgraph_xml(diagram_xml)}

    def edit_diagram(self, session_id, operations):
        session_id = self._session_key(session_id)
        self._refresh_browser_state(session_id)
        with self._lock:
            session = self.sessions[session_id]
            current_xml = session.get('xml') or DEFAULT_EMPTY_DIAGRAM
        next_xml, errors = apply_diagram_operations(current_xml, operations or [])
        if errors:
            return {'session_id': session_id, 'ok': False, 'errors': errors, 'xml': current_xml}
        with self._lock:
            session = self.sessions[session_id]
            session['history'].append(
                _history_entry(current_xml, session.get('updated_at', 0), thumbnail=_session_svg(session))
            )
            self._set_session_xml_locked(session, next_xml)
        self._notify_update(session_id)
        return {'session_id': session_id, 'ok': True, 'xml': next_xml, 'stats': validate_mxgraph_xml(next_xml)}

    def get_diagram(self, session_id):
        session_id = self._session_key(session_id)
        with self._lock:
            session = self.sessions[session_id]
            xml = session.get('xml') or DEFAULT_EMPTY_DIAGRAM
            history = _safe_history(session.get('history') or [])
            history_count = len(session.get('history') or [])
            version = int(session.get('version') or 0)
        return {
            'session_id': session_id,
            'xml': xml,
            'stats': validate_mxgraph_xml(xml),
            'history_count': history_count,
            'history': history,
            'version': version,
            'preview_url': self._preview_url(session_id),
        }

    def sync_diagram(self, session_id, xml, thumbnail='', exports=None):
        session_id = self._session_key(session_id)
        diagram_xml = _normalize_diagram_xml(xml)
        version = 0
        with self._lock:
            session = self.sessions[session_id]
            current_xml = session.get('xml') or DEFAULT_EMPTY_DIAGRAM
            if current_xml != diagram_xml:
                session['history'].append(
                    _history_entry(current_xml, session.get('updated_at', 0), thumbnail=thumbnail or _session_svg(session))
                )
                self._set_session_xml_locked(session, diagram_xml)
            else:
                session['updated_at'] = int(time.time())
            self._store_native_exports_locked(session, exports)
            if thumbnail:
                session.setdefault('native_exports', {})['svg'] = thumbnail
            session['browser_ready'] = True
            session['sync_requested'] = 0
            version = int(session.get('version') or 0)
        self._notify_update(session_id)
        return {
            'session_id': session_id,
            'ok': True,
            'xml': diagram_xml,
            'version': version,
            'stats': validate_mxgraph_xml(diagram_xml),
        }

    def restore_history(self, session_id, index):
        session_id = self._session_key(session_id)
        with self._lock:
            session = self.sessions[session_id]
            history = list(session.get('history') or [])
        try:
            idx = int(index)
        except (TypeError, ValueError):
            raise ValueError('历史版本索引无效。')
        if idx < 0 or idx >= len(history):
            raise ValueError('历史版本不存在。')
        restored = str(history[idx].get('xml') or '').strip()
        if not restored:
            raise ValueError('历史版本缺少 XML。')
        validate_mxgraph_xml(restored)
        with self._lock:
            session = self.sessions[session_id]
            current_xml = session.get('xml') or DEFAULT_EMPTY_DIAGRAM
            session['history'] = history[:idx]
            session['history'].append(
                _history_entry(current_xml, session.get('updated_at', 0), thumbnail=_session_svg(session))
            )
            self._set_session_xml_locked(session, restored)
        self._notify_update(session_id)
        return {'session_id': session_id, 'ok': True, 'xml': restored, 'stats': validate_mxgraph_xml(restored)}

    def export_diagram(self, session_id, export_format='drawio', path=''):
        session_id = self._session_key(session_id)
        fmt = _normalize_export_format(export_format)
        if fmt in {'png', 'svg', 'drawio.svg'}:
            self._request_browser_export(session_id, fmt)
        suffix = '.drawio.svg' if fmt == 'drawio.svg' else f'.{fmt}'
        output_path = str(path or '').strip()
        remove_after = False
        if not output_path:
            handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            output_path = handle.name
            handle.close()
            remove_after = True
        with self._lock:
            session = self.sessions[session_id]
            xml = session.get('xml') or DEFAULT_EMPTY_DIAGRAM
            native_exports = dict(session.get('native_exports') if isinstance(session.get('native_exports'), dict) else {})

        def native_exporter(native_fmt):
            data = native_exports.get(native_fmt)
            return {'data': data} if data else None

        result = export_diagram_file(output_path, xml, block=_block_for_xml(xml), native_exporter=native_exporter)
        payload = {'session_id': session_id, 'format': fmt, 'path': output_path, 'note': result.get('note', '')}
        if remove_after:
            if fmt == 'png':
                with open(output_path, 'rb') as handle:
                    data = handle.read()
            else:
                with open(output_path, 'r', encoding='utf-8') as handle:
                    data = handle.read()
            if isinstance(data, bytes):
                payload['data_base64'] = base64.b64encode(data).decode('ascii')
            else:
                payload['data'] = data
            try:
                os.remove(output_path)
            except OSError:
                pass
            payload.pop('path', None)
        return payload

    def dispatch(self, tool, arguments):
        args = arguments if isinstance(arguments, dict) else {}
        name = str(tool or '').strip()
        if name == 'start_session':
            return self.start_session(args.get('xml', ''))
        if name == 'create_new_diagram':
            return self.create_new_diagram(args.get('session_id'), args.get('xml', ''))
        if name == 'edit_diagram':
            return self.edit_diagram(args.get('session_id'), args.get('operations') or [])
        if name == 'get_diagram':
            return self.get_diagram(args.get('session_id'))
        if name == 'export_diagram':
            return self.export_diagram(args.get('session_id'), args.get('format', 'drawio'), args.get('path', ''))
        if name == 'restore_history':
            return self.restore_history(args.get('session_id'), args.get('index'))
        raise ValueError(f'未知 MCP 图表工具：{name}')

    def get_browser_state(self, session_id):
        session_id = self._session_key(session_id)
        with self._lock:
            session = self.sessions[session_id]
            session['browser_ready'] = True
            return {
                'session_id': session_id,
                'xml': session.get('xml') or DEFAULT_EMPTY_DIAGRAM,
                'version': int(session.get('version') or 0),
                'syncRequested': bool(session.get('sync_requested')),
                'exportFormat': str(session.get('export_format') or ''),
            }

    def store_browser_export(self, session_id, export_data, export_format=''):
        session_id = self._session_key(session_id)
        data = str(export_data or '').strip()
        if not data:
            raise ValueError('浏览器导出结果为空。')
        with self._lock:
            session = self.sessions[session_id]
            fmt = _normalize_export_format(export_format or session.get('export_format') or 'svg')
            session['export_data'] = data
            session['export_format'] = ''
            session.setdefault('native_exports', {})[fmt] = data
            if fmt == 'svg':
                session.setdefault('native_exports', {})['drawio.svg'] = data
            session['browser_ready'] = True
        return {'session_id': session_id, 'ok': True, 'format': fmt}

    def update_history_thumbnail(self, session_id, thumbnail):
        session_id = self._session_key(session_id)
        svg = str(thumbnail or '').strip()
        if not svg:
            return {'session_id': session_id, 'ok': False, 'updated': False}
        with self._lock:
            session = self.sessions[session_id]
            history = session.get('history') or []
            if history:
                history[-1]['thumbnail'] = svg[:200000]
            session.setdefault('native_exports', {})['svg'] = svg
            session['browser_ready'] = True
        return {'session_id': session_id, 'ok': True, 'updated': bool(history)}

    def _session(self, session_id):
        return self.sessions[self._session_key(session_id)]

    def _session_key(self, session_id):
        key = str(session_id or '').strip() or self.current_session_id
        if not key or key not in self.sessions:
            raise ValueError('MCP 图表会话不存在，请先调用 start_session。')
        return key

    def _notify_update(self, session_id):
        if callable(self.on_update):
            try:
                self.on_update(session_id, self.sessions[session_id].get('xml', ''))
            except Exception:
                pass

    def _preview_url(self, session_id):
        base = str(self.preview_base_url or '').strip().rstrip('/')
        if not base:
            return ''
        return f'{base}/?session_id={urllib.parse.quote(str(session_id))}'

    def _set_session_xml_locked(self, session, xml):
        session['xml'] = xml
        session['updated_at'] = int(time.time())
        session['version'] = int(session.get('version') or 0) + 1
        session['sync_requested'] = 0
        session['export_format'] = ''
        session['export_data'] = ''

    def _store_native_exports_locked(self, session, exports):
        if not isinstance(exports, dict):
            return
        native = dict(session.get('native_exports') if isinstance(session.get('native_exports'), dict) else {})
        for key, value in exports.items():
            fmt = str(key or '').strip()
            if fmt not in {'png', 'svg', 'drawio.svg'}:
                continue
            data = str(value or '').strip()
            if data:
                native[fmt] = data
        session['native_exports'] = native

    def _refresh_browser_state(self, session_id, timeout=MCP_SYNC_TIMEOUT_SECONDS):
        with self._lock:
            session = self.sessions.get(session_id)
            if not session or not session.get('browser_ready'):
                return False
            session['sync_requested'] = int(time.time() * 1000)
        deadline = time.time() + float(timeout or 0)
        while time.time() < deadline:
            with self._lock:
                session = self.sessions.get(session_id)
                if not session or not session.get('sync_requested'):
                    return True
            time.sleep(0.05)
        with self._lock:
            session = self.sessions.get(session_id)
            if session:
                session['sync_requested'] = 0
        return False

    def _request_browser_export(self, session_id, export_format, timeout=MCP_EXPORT_TIMEOUT_SECONDS):
        fmt = _normalize_export_format(export_format)
        with self._lock:
            session = self.sessions.get(session_id)
            if not session or not session.get('browser_ready'):
                return None
            exports = session.get('native_exports') if isinstance(session.get('native_exports'), dict) else {}
            if str(exports.get(fmt) or '').strip():
                return {'data': str(exports.get(fmt) or '')}
            session['export_format'] = fmt
            session['export_data'] = ''
        deadline = time.time() + float(timeout or 0)
        while time.time() < deadline:
            with self._lock:
                session = self.sessions.get(session_id)
                if not session:
                    return None
                data = str(session.get('export_data') or '').strip()
                if data:
                    session['export_data'] = ''
                    return {'data': data}
            time.sleep(0.05)
        with self._lock:
            session = self.sessions.get(session_id)
            if session:
                session['export_format'] = ''
        return None


class DiagramMCPHTTPServer:
    """监听 127.0.0.1 的本地 JSON 工具服务。"""

    def __init__(self, service=None, *, host='127.0.0.1', port=0):
        self.service = service or DiagramMCPService()
        self.host = host
        self.port = int(port or 0)
        self.httpd = None
        self.thread = None

    def start(self):
        service = self.service

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                try:
                    length = int(self.headers.get('Content-Length') or 0)
                    if length > MAX_HTTP_BODY_BYTES:
                        self._send_json({'ok': False, 'error': 'payload too large'}, status=413)
                        return
                    payload = json.loads(self.rfile.read(length).decode('utf-8') or '{}')
                    parsed = urllib.parse.urlsplit(self.path)
                    path = parsed.path.rstrip('/') or '/'
                    if path == '/sync':
                        result = service.sync_diagram(
                            payload.get('session_id'),
                            payload.get('xml', ''),
                            thumbnail=payload.get('thumbnail', ''),
                            exports=payload.get('exports') if isinstance(payload.get('exports'), dict) else None,
                        )
                    elif path == '/restore':
                        result = service.restore_history(payload.get('session_id'), payload.get('index'))
                    elif path == '/api/state':
                        result = _handle_api_state_post(service, payload)
                    elif path == '/api/restore':
                        result = service.restore_history(payload.get('sessionId') or payload.get('session_id'), payload.get('index'))
                    elif path == '/api/history-svg':
                        result = service.update_history_thumbnail(payload.get('sessionId') or payload.get('session_id'), payload.get('svg', ''))
                    else:
                        result = service.dispatch(payload.get('tool'), payload.get('arguments') or {})
                    self._send_json({'ok': True, 'result': result})
                except Exception as exc:
                    self._send_json({'ok': False, 'error': str(exc)}, status=400)

            def do_GET(self):  # noqa: N802
                parsed = urllib.parse.urlsplit(self.path)
                path = parsed.path.rstrip('/') or '/'
                if path == '/health':
                    self._send_json({'ok': True, 'tools': MCP_TOOL_NAMES})
                elif path == '/state':
                    query = urllib.parse.parse_qs(parsed.query)
                    session_id = (query.get('session_id') or [''])[0]
                    self._send_json({'ok': True, 'result': service.get_diagram(session_id)})
                elif path == '/api/state':
                    query = urllib.parse.parse_qs(parsed.query)
                    session_id = (query.get('sessionId') or query.get('session_id') or [''])[0]
                    self._send_json(service.get_browser_state(session_id))
                elif path == '/api/history':
                    query = urllib.parse.parse_qs(parsed.query)
                    session_id = (query.get('sessionId') or query.get('session_id') or [''])[0]
                    state = service.get_diagram(session_id)
                    self._send_json({
                        'entries': [
                            {'index': item.get('index'), 'svg': item.get('thumbnail', '')}
                            for item in state.get('history', [])
                        ],
                        'count': state.get('history_count', 0),
                    })
                elif path == '/':
                    self._send_html(_preview_html())
                elif path == '/drawio' or path.startswith('/drawio/'):
                    asset = _read_drawio_asset(path)
                    if asset:
                        data, mime_type = asset
                        self._send_bytes(data, mime_type)
                    else:
                        self._send_json({'ok': False, 'error': 'not found'}, status=404)
                else:
                    self._send_json({'ok': False, 'error': 'not found'}, status=404)

            def log_message(self, _format, *args):
                return

            def _send_json(self, payload, status=200):
                data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _send_bytes(self, data, mime_type, status=200):
                body = data if isinstance(data, bytes) else bytes(data or b'')
                self.send_response(status)
                self.send_header('Content-Type', mime_type or 'application/octet-stream')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_html(self, text, status=200):
                data = str(text or '').encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.host, self.port = self.httpd.server_address
        service.preview_base_url = f'http://{self.host}:{self.port}'
        self.thread = threading.Thread(target=self.httpd.serve_forever, name='diagram-mcp-http', daemon=True)
        self.thread.start()
        return {'host': self.host, 'port': self.port, 'url': f'http://{self.host}:{self.port}'}

    def stop(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None


def run_stdio(service=None, *, stdin=None, stdout=None):
    """运行最小 JSONL MCP 兼容 stdio 服务。

    输入每行 JSON：{"tool": "...", "arguments": {...}}
    输出每行 JSON：{"ok": true, "result": {...}}
    """
    service = service or DiagramMCPService()
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
            result = service.dispatch(payload.get('tool'), payload.get('arguments') or {})
            response = {'ok': True, 'result': result}
        except Exception as exc:
            response = {'ok': False, 'error': str(exc)}
        stdout.write(json.dumps(response, ensure_ascii=False) + '\n')
        stdout.flush()


def run_mcp_stdio(service=None, *, stdin=None, stdout=None):
    """运行最小 MCP JSON-RPC stdio 服务。"""
    service = service or DiagramMCPService()
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        text = line.strip()
        if not text:
            continue
        try:
            request = json.loads(text)
            if not isinstance(request, dict):
                raise ValueError('MCP 请求必须是 JSON 对象。')
            response = _handle_jsonrpc_request(service, request)
        except Exception as exc:
            response = _jsonrpc_error(None, -32700, str(exc))
        if response is None:
            continue
        stdout.write(json.dumps(response, ensure_ascii=False) + '\n')
        stdout.flush()


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if '--http' in args:
        port = 0
        if '--port' in args:
            try:
                port = int(args[args.index('--port') + 1])
            except Exception:
                port = 0
        server = DiagramMCPHTTPServer(port=port)
        info = server.start()
        sys.stdout.write(json.dumps({'ok': True, 'url': info['url']}, ensure_ascii=False) + '\n')
        sys.stdout.flush()
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            server.stop()
            return 0
    if '--jsonl' in args:
        run_stdio()
    else:
        run_mcp_stdio()
    return 0


def maybe_run_from_argv(argv=None):
    args = list(sys.argv if argv is None else argv)
    if len(args) >= 2 and args[1] == '--diagram-mcp':
        raise SystemExit(main(args[2:]))
    return False


MCP_TOOL_NAMES = [
    'start_session',
    'create_new_diagram',
    'edit_diagram',
    'get_diagram',
    'export_diagram',
    'restore_history',
]


def _handle_jsonrpc_request(service, request):
    request_id = request.get('id')
    method = str(request.get('method') or '').strip()
    params = request.get('params') if isinstance(request.get('params'), dict) else {}
    if request_id is None and method.endswith('/initialized'):
        return None
    try:
        if method == 'initialize':
            return _jsonrpc_result(request_id, {
                'protocolVersion': MCP_PROTOCOL_VERSION,
                'capabilities': {'tools': {}, 'prompts': {}},
                'serverInfo': MCP_SERVER_INFO,
            })
        if method == 'tools/list':
            return _jsonrpc_result(request_id, {'tools': _mcp_tool_definitions()})
        if method == 'tools/call':
            tool_name = str(params.get('name') or '').strip()
            arguments = params.get('arguments') if isinstance(params.get('arguments'), dict) else {}
            result = service.dispatch(tool_name, arguments)
            return _jsonrpc_result(request_id, _mcp_tool_result(result))
        if method == 'prompts/list':
            return _jsonrpc_result(request_id, {
                'prompts': [{
                    'name': 'diagram-workflow',
                    'description': '创建和编辑 draw.io 图表的本地工作流说明。',
                    'arguments': [],
                }]
            })
        if method == 'prompts/get':
            prompt_name = str(params.get('name') or '').strip()
            if prompt_name != 'diagram-workflow':
                raise ValueError(f'未知 MCP 提示词：{prompt_name}')
            return _jsonrpc_result(request_id, {
                'description': '创建和编辑 draw.io 图表的本地工作流说明。',
                'messages': [{
                    'role': 'user',
                    'content': {'type': 'text', 'text': MCP_WORKFLOW_PROMPT},
                }],
            })
        return _jsonrpc_error(request_id, -32601, f'未知 MCP 方法：{method}')
    except Exception as exc:
        return _jsonrpc_error(request_id, -32000, str(exc))


def _jsonrpc_result(request_id, result):
    return {'jsonrpc': '2.0', 'id': request_id, 'result': result}


def _jsonrpc_error(request_id, code, message):
    return {
        'jsonrpc': '2.0',
        'id': request_id,
        'error': {'code': int(code), 'message': str(message)},
    }


def _mcp_tool_result(result):
    text = json.dumps(result, ensure_ascii=False, indent=2)
    return {
        'content': [{'type': 'text', 'text': text}],
        'structuredContent': result if isinstance(result, dict) else {'result': result},
        'isError': False,
    }


def _mcp_tool_definitions():
    return [
        {
            'name': 'start_session',
            'description': '创建本地图表会话。可选传入 xml 作为初始图表。',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'xml': {'type': 'string', 'description': '可选初始 mxGraphModel XML 或 mxCell 片段。'},
                },
                'additionalProperties': False,
            },
        },
        {
            'name': 'create_new_diagram',
            'description': '用完整 XML 替换当前会话图表。用于新建或重构图表。',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'session_id': {'type': 'string', 'description': '图表会话 ID；省略时使用最近会话。'},
                    'xml': {'type': 'string', 'description': '完整 mxGraphModel XML 或 mxCell 片段。'},
                },
                'required': ['xml'],
                'additionalProperties': False,
            },
        },
        {
            'name': 'edit_diagram',
            'description': '按 cell_id 执行 add/update/delete 操作，复用当前 XML 校验与删除级联。',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'session_id': {'type': 'string', 'description': '图表会话 ID；省略时使用最近会话。'},
                    'operations': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'operation': {'type': 'string', 'enum': ['add', 'update', 'delete']},
                                'cell_id': {'type': 'string'},
                                'new_xml': {'type': 'string'},
                            },
                            'required': ['operation', 'cell_id'],
                            'additionalProperties': True,
                        },
                    },
                },
                'required': ['operations'],
                'additionalProperties': False,
            },
        },
        {
            'name': 'get_diagram',
            'description': '获取当前会话图表 XML、结构统计和历史数量。',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'session_id': {'type': 'string', 'description': '图表会话 ID；省略时使用最近会话。'},
                },
                'additionalProperties': False,
            },
        },
        {
            'name': 'export_diagram',
            'description': '导出当前会话图表。支持 drawio、xml、png、svg、drawio.svg。',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'session_id': {'type': 'string', 'description': '图表会话 ID；省略时使用最近会话。'},
                    'format': {'type': 'string', 'enum': ['drawio', 'xml', 'png', 'svg', 'drawio.svg']},
                    'path': {'type': 'string', 'description': '可选输出路径；省略时返回导出数据。'},
                },
                'additionalProperties': False,
            },
        },
        {
            'name': 'restore_history',
            'description': '从当前 MCP 会话历史中恢复指定版本。',
            'inputSchema': {
                'type': 'object',
                'properties': {
                    'session_id': {'type': 'string', 'description': '图表会话 ID；省略时使用最近会话。'},
                    'index': {'type': 'integer', 'description': 'get_diagram 返回的历史版本索引。'},
                },
                'required': ['index'],
                'additionalProperties': False,
            },
        },
    ]


def _handle_api_state_post(service, payload):
    session_id = payload.get('sessionId') or payload.get('session_id')
    if payload.get('exportData') is not None:
        return service.store_browser_export(session_id, payload.get('exportData'), payload.get('exportFormat', ''))
    exports = {}
    svg = str(payload.get('svg') or '').strip()
    if svg:
        exports['svg'] = svg
    return service.sync_diagram(session_id, payload.get('xml', ''), thumbnail=svg, exports=exports)


def _drawio_assets_available():
    try:
        index_path = resolve_resource_path('Management', 'web_assets', 'drawio', 'index.html')
        bootstrap_path = resolve_resource_path('Management', 'web_assets', 'drawio', 'js', 'bootstrap.js')
        return os.path.exists(index_path) and os.path.exists(bootstrap_path)
    except Exception:
        return False


def _read_drawio_asset(path):
    try:
        rel = urllib.parse.unquote(str(path or ''))
        if rel == '/drawio':
            rel = '/drawio/index.html'
        if not rel.startswith('/drawio/'):
            return None
        rel = rel[len('/drawio/'):].replace('\\', '/').lstrip('/')
        if not rel:
            rel = 'index.html'
        parts = [part for part in rel.split('/') if part and part not in {'.', '..'}]
        if len(parts) != len([part for part in rel.split('/') if part]):
            return None
        base = os.path.abspath(resolve_resource_path('Management', 'web_assets', 'drawio'))
        target = os.path.abspath(os.path.join(base, *parts))
        if target != base and not target.startswith(base + os.sep):
            return None
        if not os.path.isfile(target):
            return None
        with open(target, 'rb') as handle:
            data = handle.read()
        mime_type = mimetypes.guess_type(target)[0] or 'application/octet-stream'
        if target.endswith('.js'):
            mime_type = 'application/javascript; charset=utf-8'
        elif target.endswith('.css'):
            mime_type = 'text/css; charset=utf-8'
        elif target.endswith('.html'):
            mime_type = 'text/html; charset=utf-8'
        return data, mime_type
    except Exception:
        return None


def _normalize_diagram_xml(xml):
    text = str(xml or '').strip()
    if not text:
        return DEFAULT_EMPTY_DIAGRAM
    if text.startswith('<mxCell'):
        text = wrap_mx_cells(text)
    validate_mxgraph_xml(text)
    return text


def _normalize_export_format(export_format):
    fmt = str(export_format or 'drawio').strip().lower()
    if fmt in {'drawio', 'xml', 'png', 'svg', 'drawio.svg'}:
        return fmt
    if fmt == 'drawiosvg':
        return 'drawio.svg'
    if fmt == 'xmlsvg':
        return 'drawio.svg'
    raise ValueError(f'不支持的导出格式：{export_format}')


def _history_entry(xml, updated_at=0, *, thumbnail=''):
    return {
        'xml': str(xml or ''),
        'updated_at': int(updated_at or time.time()),
        'thumbnail': str(thumbnail or '')[:200000],
    }


def _session_svg(session):
    exports = session.get('native_exports') if isinstance(session.get('native_exports'), dict) else {}
    return str(exports.get('svg') or exports.get('drawio.svg') or '')[:200000]


def _safe_history(history):
    cleaned = []
    for index, item in enumerate(list(history or [])):
        if not isinstance(item, dict):
            continue
        xml = str(item.get('xml') or '')
        if not xml:
            continue
        cleaned.append({
            'index': index,
            'updated_at': int(item.get('updated_at') or 0),
            'thumbnail': str(item.get('thumbnail') or '')[:200000],
            'xml_preview': xml[:1200],
        })
    return cleaned


def _block_for_xml(xml):
    return {
        'caption': 'MCP 图表',
        'mxgraph_xml': xml,
        'json_graph': {'nodes': [], 'edges': [], 'groups': [], 'meta': {}},
    }


def _preview_html():
    if _drawio_assets_available():
        return _drawio_preview_html()
    return _xml_preview_html()


def _drawio_preview_html():
    title = html.escape(MCP_SERVER_INFO['name'])
    drawio_src = '/drawio/index.html?embed=1&proto=json&spin=1&libraries=1&noSaveBtn=1&noExitBtn=1&saveAndExit=0&offline=1&local=1&stealth=1&lang=zh'
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>__TITLE__</title>
  <style>
    * { box-sizing: border-box; }
    html, body { width:100%; height:100%; margin:0; overflow:hidden; font-family:"Microsoft YaHei", Arial, sans-serif; color:#1f2937; background:#f6f7fb; }
    .app { width:100%; height:100%; display:flex; flex-direction:column; }
    header { height:48px; display:flex; align-items:center; justify-content:space-between; gap:12px; padding:0 14px; background:#fff; border-bottom:1px solid #d9dee8; }
    .brand { display:flex; align-items:center; gap:10px; min-width:0; }
    .title { font-weight:600; white-space:nowrap; }
    .session { font:12px Consolas, monospace; color:#64748b; overflow:hidden; text-overflow:ellipsis; max-width:220px; }
    .actions { display:flex; align-items:center; gap:8px; }
    button { border:1px solid #c5ccd8; background:#fff; color:#1f2937; border-radius:6px; padding:6px 10px; cursor:pointer; }
    button.primary { background:#2563eb; color:#fff; border-color:#2563eb; }
    button:disabled { color:#9ca3af; background:#eef2f7; cursor:not-allowed; }
    #status { min-width:140px; text-align:right; font-size:12px; color:#64748b; }
    #drawio { flex:1; width:100%; border:0; background:#fff; }
    .modal { display:none; position:fixed; inset:0; background:rgba(15,23,42,.35); z-index:20; align-items:center; justify-content:center; }
    .modal.open { display:flex; }
    .dialog { width:min(720px, 92vw); max-height:76vh; display:flex; flex-direction:column; background:#fff; border-radius:8px; border:1px solid #d9dee8; box-shadow:0 18px 45px rgba(15,23,42,.22); }
    .dialog header { height:auto; padding:12px 14px; }
    .dialog main { padding:14px; overflow:auto; }
    .dialog footer { display:flex; justify-content:flex-end; gap:8px; padding:12px 14px; border-top:1px solid #e5e7eb; }
    .history-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(150px, 1fr)); gap:10px; }
    .history-item { border:1px solid #d9dee8; border-radius:6px; padding:8px; cursor:pointer; background:#f8fafc; }
    .history-item.selected { border-color:#2563eb; box-shadow:0 0 0 2px rgba(37,99,235,.16); background:#fff; }
    .thumb { aspect-ratio:4/3; display:flex; align-items:center; justify-content:center; background:#fff; border:1px solid #e5e7eb; border-radius:4px; overflow:hidden; margin-bottom:6px; color:#64748b; }
    .thumb img { max-width:100%; max-height:100%; object-fit:contain; }
    .label { font-size:12px; color:#64748b; }
    .field { display:grid; gap:6px; margin-bottom:12px; }
    .field label { font-size:13px; color:#475569; }
    input, select { border:1px solid #cbd5e1; border-radius:6px; padding:8px 10px; font:14px "Microsoft YaHei", Arial, sans-serif; }
  </style>
</head>
<body>
  <div class="app">
    <header>
      <div class="brand">
        <span class="title">本地 MCP draw.io 预览</span>
        <span id="session" class="session"></span>
      </div>
      <div class="actions">
        <button id="historyBtn">历史版本</button>
        <button id="saveBtn" class="primary">导出</button>
        <span id="status"></span>
      </div>
    </header>
    <iframe id="drawio" src="__DRAWIO_SRC__"></iframe>
  </div>
  <div id="historyModal" class="modal">
    <div class="dialog">
      <header><strong>历史版本</strong></header>
      <main>
        <div id="historyGrid" class="history-grid"></div>
        <div id="historyEmpty" class="label" style="display:none;">暂无历史版本</div>
      </main>
      <footer>
        <button id="historyCancel">关闭</button>
        <button id="historyRestore" class="primary" disabled>恢复</button>
      </footer>
    </div>
  </div>
  <div id="saveModal" class="modal">
    <div class="dialog">
      <header><strong>导出图表</strong></header>
      <main>
        <div class="field">
          <label for="saveFormat">格式</label>
          <select id="saveFormat">
            <option value="drawio">draw.io XML (.drawio)</option>
            <option value="png">PNG 图像 (.png)</option>
            <option value="svg">SVG 图像 (.svg)</option>
            <option value="drawio.svg">draw.io SVG (.drawio.svg)</option>
          </select>
        </div>
        <div class="field">
          <label for="saveName">文件名</label>
          <input id="saveName" value="diagram" />
        </div>
      </main>
      <footer>
        <button id="saveCancel">关闭</button>
        <button id="saveConfirm" class="primary">导出</button>
      </footer>
    </div>
  </div>
  <script>
    const params = new URLSearchParams(location.search);
    const sessionId = params.get('session_id') || params.get('mcp') || '';
    const iframe = document.getElementById('drawio');
    const statusBox = document.getElementById('status');
    document.getElementById('session').textContent = sessionId || '未创建会话';
    let currentVersion = 0;
    let isReady = false;
    let pendingXml = '';
    let lastXml = '';
    let pendingSvgExport = '';
    let pendingSyncExport = false;
    let pendingMcpExport = '';
    let pendingDownload = null;

    function setStatus(text) { statusBox.textContent = text || ''; }
    function postDrawio(payload) {
      if (!iframe.contentWindow) return;
      iframe.contentWindow.postMessage(JSON.stringify(payload), '*');
    }
    function normalizeDataUrl(data, mime) {
      const text = String(data || '');
      if (text.startsWith('data:')) return text;
      return 'data:' + mime + ';base64,' + btoa(unescape(encodeURIComponent(text)));
    }
    function emptyMxgraph() {
      return '<mxGraphModel dx="1024" dy="768" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1024" pageHeight="768" math="0" shadow="0"><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel>';
    }
    function sanitizeXml(xml) {
      const text = String(xml || '').trim();
      if (!text) return emptyMxgraph();
      try {
        const doc = new DOMParser().parseFromString(text, 'text/xml');
        if (doc.querySelector('parsererror')) return emptyMxgraph();
        const model = doc.documentElement && doc.documentElement.tagName === 'mxGraphModel'
          ? doc.documentElement
          : doc.querySelector('mxGraphModel');
        return model ? new XMLSerializer().serializeToString(model) : text;
      } catch (_) {
        return emptyMxgraph();
      }
    }
    function loadDiagram(xml, capturePreview) {
      const safeXml = sanitizeXml(xml);
      if (!isReady) { pendingXml = safeXml; return; }
      lastXml = safeXml;
      postDrawio({ action: 'load', xml: safeXml, autosave: 1 });
      if (capturePreview) {
        setTimeout(() => {
          pendingSvgExport = safeXml;
          postDrawio({ action: 'export', format: 'svg' });
        }, 500);
      }
    }
    async function pushState(xml, svg) {
      if (!sessionId) return;
      try {
        const resp = await fetch('/api/state', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sessionId, xml, svg: svg || '' })
        });
        const payload = await resp.json();
        if (payload.ok) {
          const result = payload.result || {};
          currentVersion = result.version || currentVersion;
          lastXml = xml;
        }
      } catch (_) {}
    }
    async function poll() {
      if (!sessionId) return;
      try {
        const resp = await fetch('/api/state?sessionId=' + encodeURIComponent(sessionId));
        if (!resp.ok) return;
        const state = await resp.json();
        if (state.syncRequested && isReady && !pendingSyncExport) {
          pendingSyncExport = true;
          postDrawio({ action: 'export', format: 'xml' });
        }
        if (state.version > currentVersion && state.xml) {
          currentVersion = state.version;
          loadDiagram(state.xml, true);
        }
        if (state.exportFormat && isReady && !pendingMcpExport) {
          pendingMcpExport = state.exportFormat;
          const format = state.exportFormat === 'drawio.svg' ? 'xmlsvg' : state.exportFormat;
          const payload = format === 'png'
            ? { action: 'export', format: 'png', scale: 2 }
            : { action: 'export', format };
          postDrawio(payload);
          setTimeout(() => { pendingMcpExport = ''; }, 8000);
        }
      } catch (_) {}
    }
    window.addEventListener('message', (event) => {
      if (event.origin !== location.origin) return;
      let msg = event.data;
      if (typeof msg === 'string') {
        try { msg = JSON.parse(msg); } catch (_) { return; }
      }
      if (!msg || typeof msg !== 'object') return;
      if (msg.event === 'init') {
        isReady = true;
        setStatus('draw.io 已就绪');
        if (pendingXml) { loadDiagram(pendingXml, false); pendingXml = ''; }
        poll();
      } else if ((msg.event === 'autosave' || msg.event === 'save') && msg.xml && msg.xml !== lastXml) {
        pendingSvgExport = msg.xml;
        postDrawio({ action: 'export', format: 'svg' });
        setTimeout(() => {
          if (pendingSvgExport === msg.xml) {
            pushState(msg.xml, '');
            pendingSvgExport = '';
          }
        }, 2000);
      } else if (msg.event === 'export' && msg.data) {
        const data = String(msg.data || '');
        if (pendingMcpExport) {
          const exportFormat = pendingMcpExport;
          pendingMcpExport = '';
          fetch('/api/state', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sessionId, exportData: data, exportFormat })
          }).catch(() => {});
          return;
        }
        if (pendingDownload) {
          const item = pendingDownload;
          pendingDownload = null;
          downloadData(item.filename, data, item.mime);
          return;
        }
        if (pendingSyncExport && !data.startsWith('data:') && !data.startsWith('<svg')) {
          pendingSyncExport = false;
          pushState(data, '');
          return;
        }
        if (pendingSvgExport) {
          const xml = pendingSvgExport;
          pendingSvgExport = '';
          pushState(xml, normalizeDataUrl(data, 'image/svg+xml'));
        }
      }
    });
    function downloadData(filename, data, mime) {
      let href = String(data || '');
      if (!href.startsWith('data:')) href = normalizeDataUrl(href, mime);
      const a = document.createElement('a');
      a.href = href;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    }
    setInterval(poll, 2000);
    poll();

    const historyModal = document.getElementById('historyModal');
    const historyGrid = document.getElementById('historyGrid');
    const historyEmpty = document.getElementById('historyEmpty');
    const historyRestore = document.getElementById('historyRestore');
    let historyData = [];
    let selectedHistory = null;
    document.getElementById('historyBtn').onclick = async () => {
      selectedHistory = null;
      historyRestore.disabled = true;
      try {
        const resp = await fetch('/api/history?sessionId=' + encodeURIComponent(sessionId));
        const payload = await resp.json();
        historyData = payload.entries || [];
      } catch (_) {
        historyData = [];
      }
      renderHistory();
      historyModal.classList.add('open');
    };
    document.getElementById('historyCancel').onclick = () => historyModal.classList.remove('open');
    function renderHistory() {
      historyGrid.innerHTML = '';
      historyEmpty.style.display = historyData.length ? 'none' : 'block';
      for (const item of historyData) {
        const el = document.createElement('div');
        el.className = 'history-item';
        el.dataset.index = item.index;
        const thumb = item.svg ? '<img src="' + item.svg + '">' : '#' + item.index;
        el.innerHTML = '<div class="thumb">' + thumb + '</div><div class="label">版本 ' + item.index + '</div>';
        el.onclick = () => {
          selectedHistory = item.index;
          historyRestore.disabled = false;
          historyGrid.querySelectorAll('.history-item').forEach((node) => {
            node.classList.toggle('selected', Number(node.dataset.index) === selectedHistory);
          });
        };
        historyGrid.appendChild(el);
      }
    }
    historyRestore.onclick = async () => {
      if (selectedHistory === null) return;
      await fetch('/api/restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sessionId, index: selectedHistory })
      });
      historyModal.classList.remove('open');
      await poll();
    };

    const saveModal = document.getElementById('saveModal');
    const saveFormat = document.getElementById('saveFormat');
    const saveName = document.getElementById('saveName');
    document.getElementById('saveBtn').onclick = () => saveModal.classList.add('open');
    document.getElementById('saveCancel').onclick = () => saveModal.classList.remove('open');
    document.getElementById('saveConfirm').onclick = () => {
      const format = saveFormat.value;
      const ext = format === 'drawio.svg' ? '.drawio.svg' : (format === 'drawio' ? '.drawio' : '.' + format);
      const filename = (saveName.value.trim() || 'diagram') + ext;
      if (format === 'drawio') {
        const blob = new Blob([lastXml || emptyMxgraph()], { type: 'application/xml' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(url), 2000);
      } else {
        const drawioFormat = format === 'drawio.svg' ? 'xmlsvg' : format;
        pendingDownload = { filename, mime: format === 'png' ? 'image/png' : 'image/svg+xml' };
        postDrawio({ action: 'export', format: drawioFormat, scale: format === 'png' ? 2 : undefined });
      }
      saveModal.classList.remove('open');
    };
  </script>
</body>
</html>""".replace('__TITLE__', title).replace('__DRAWIO_SRC__', drawio_src)


def _xml_preview_html():
    title = html.escape(MCP_SERVER_INFO['name'])
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>{title}</title>
  <style>
    body {{ margin:0; font-family: "Microsoft YaHei", Arial, sans-serif; background:#f6f7fb; color:#1f2937; }}
    header {{ padding:12px 16px; background:#ffffff; border-bottom:1px solid #d9dee8; display:flex; gap:10px; align-items:center; }}
    main {{ display:grid; grid-template-columns: 1fr 360px; gap:12px; padding:12px; }}
    textarea {{ width:100%; min-height:58vh; box-sizing:border-box; border:1px solid #ccd3df; border-radius:6px; padding:10px; font-family:Consolas, monospace; font-size:12px; }}
    button {{ border:1px solid #c5ccd8; background:#ffffff; color:#1f2937; border-radius:6px; padding:6px 10px; cursor:pointer; }}
    button.primary {{ background:#2563eb; color:#ffffff; border-color:#2563eb; }}
    .panel {{ background:#ffffff; border:1px solid #d9dee8; border-radius:8px; padding:12px; }}
    .meta {{ font-size:12px; color:#64748b; margin:6px 0 12px; }}
    .history button {{ display:block; width:100%; margin:0 0 6px; text-align:left; }}
    pre {{ white-space:pre-wrap; word-break:break-all; background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:8px; max-height:180px; overflow:auto; }}
  </style>
</head>
<body>
  <header>
    <strong>本地 MCP 图表预览</strong>
    <button class="primary" onclick="syncXml()">同步当前 XML</button>
    <button onclick="loadState()">刷新</button>
    <span id="status" class="meta"></span>
  </header>
  <main>
    <section class="panel">
      <div class="meta">该页面用于本地 MCP 会话预览和手动 XML 同步。真实 draw.io 编辑仍使用桌面软件内置编辑器。</div>
      <textarea id="xml"></textarea>
    </section>
    <aside class="panel">
      <h3>结构统计</h3>
      <pre id="stats"></pre>
      <h3>历史版本</h3>
      <div id="history" class="history"></div>
    </aside>
  </main>
  <script>
    const params = new URLSearchParams(location.search);
    const sessionId = params.get('session_id') || '';
    const xmlBox = document.getElementById('xml');
    const statusBox = document.getElementById('status');
    const statsBox = document.getElementById('stats');
    const historyBox = document.getElementById('history');
    function setStatus(text) {{ statusBox.textContent = text || ''; }}
    async function loadState() {{
      const resp = await fetch('/state?session_id=' + encodeURIComponent(sessionId));
      const payload = await resp.json();
      if (!payload.ok) {{ setStatus(payload.error || '读取失败'); return; }}
      const data = payload.result || {{}};
      xmlBox.value = data.xml || '';
      statsBox.textContent = JSON.stringify(data.stats || {{}}, null, 2);
      historyBox.innerHTML = '';
      (data.history || []).slice().reverse().forEach((item) => {{
        const btn = document.createElement('button');
        btn.textContent = '版本 ' + item.index + '    ' + new Date((item.updated_at || 0) * 1000).toLocaleString();
        btn.onclick = () => restoreHistory(item.index);
        historyBox.appendChild(btn);
      }});
      setStatus('已刷新 ' + new Date().toLocaleTimeString());
    }}
    async function syncXml() {{
      const exports = {{ svg: renderSvg(), 'drawio.svg': renderDrawioSvg() }};
      const resp = await fetch('/sync', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ session_id: sessionId, xml: xmlBox.value, exports }})
      }});
      const payload = await resp.json();
      setStatus(payload.ok ? '已同步' : (payload.error || '同步失败'));
      if (payload.ok) loadState();
    }}
    function renderSvg() {{
      const escaped = xmlBox.value
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
      return '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="720" viewBox="0 0 1200 720"><title>MCP 图表 XML 预览</title><desc>由本地 MCP 预览页生成，非 draw.io 原生渲染。</desc><foreignObject width="1200" height="720"><pre xmlns="http://www.w3.org/1999/xhtml" style="font:12px Consolas;white-space:pre-wrap;margin:16px;">' + escaped + '</pre></foreignObject></svg>';
    }}
    function renderDrawioSvg() {{
      return renderSvg().replace('</svg>', '<metadata><mxfile>' + xmlBox.value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</mxfile></metadata></svg>');
    }}
    async function restoreHistory(index) {{
      const resp = await fetch('/restore', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ session_id: sessionId, index }})
      }});
      const payload = await resp.json();
      setStatus(payload.ok ? '已恢复历史版本' : (payload.error || '恢复失败'));
      if (payload.ok) loadState();
    }}
    loadState();
    setInterval(loadState, 2000);
  </script>
</body>
</html>"""


if __name__ == '__main__':
    raise SystemExit(main())
