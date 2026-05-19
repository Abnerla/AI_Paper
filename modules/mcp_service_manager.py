# -*- coding: utf-8 -*-
"""MCP 服务配置与运行管理。"""

from __future__ import annotations

import copy
import subprocess
import time
import webbrowser


class MCPServiceError(RuntimeError):
    """MCP 服务操作失败。"""


class MCPServiceManager:
    BUILTIN_AI_DIAGRAM_ID = 'ai_diagram_builtin'

    def __init__(self, config_mgr, *, log_callback=None, app_bridge=None):
        self.config = config_mgr
        self.log_callback = log_callback
        self.app_bridge = app_bridge
        self._runtimes = {}
        self._logs = {}

    def list_services(self):
        records = self.config.get_mcp_service_records() if self.config else {}
        result = []
        for service_id, record in sorted(records.items(), key=lambda item: (not item[1].get('builtin'), item[1].get('name', ''))):
            item = copy.deepcopy(record)
            item['status'] = self.get_service_status(service_id)
            result.append(item)
        return result

    def get_service(self, service_id):
        if not self.config:
            return {}
        return self.config.get_mcp_service_record(service_id)

    def save_service(self, service_id, record):
        if not self.config:
            return
        payload = dict(record or {})
        payload['id'] = str(service_id or payload.get('id') or '').strip()
        if not payload['id']:
            payload['id'] = f'mcp_{int(time.time() * 1000)}'
        self.config.set_mcp_service_record(payload['id'], payload)
        self.config.save()

    def delete_service(self, service_id):
        if not self.config:
            return False
        record = self.config.get_mcp_service_record(service_id)
        if record and record.get('builtin'):
            return False
        self.stop_service(service_id)
        ok = self.config.delete_mcp_service_record(service_id)
        self.config.save()
        return ok

    def start_auto_services(self):
        started = []
        for service in self.list_services():
            if service.get('enabled') and service.get('auto_start'):
                try:
                    status = self.start_service(service.get('id'))
                    started.append({'id': service.get('id'), 'ok': True, 'status': status})
                except Exception as exc:
                    self._append_log(service.get('id'), f'自动启动失败：{exc}', level='ERROR')
                    started.append({'id': service.get('id'), 'ok': False, 'error': str(exc)})
        return started

    def start_service(self, service_id):
        record = self.get_service(service_id)
        if not record:
            raise MCPServiceError('MCP 服务不存在。')
        if not record.get('enabled', True):
            raise MCPServiceError('MCP 服务未启用。')
        service_type = record.get('type')
        if service_type == 'builtin_ai_diagram':
            return self._start_builtin_ai_diagram(record)
        if service_type == 'stdio':
            return self._start_stdio_service(record)
        if service_type in {'http', 'sse'}:
            return self._register_remote_service(record)
        raise MCPServiceError(f'不支持的 MCP 服务类型：{service_type}')

    def stop_service(self, service_id):
        runtime = self._runtimes.pop(str(service_id or '').strip(), None)
        if not runtime:
            return self.get_service_status(service_id)
        server = runtime.get('server')
        process = runtime.get('process')
        if server is not None:
            try:
                server.stop()
            except Exception as exc:
                self._append_log(service_id, f'停止服务失败：{exc}', level='WARN')
        if process is not None:
            try:
                process.terminate()
            except Exception:
                pass
        self._append_log(service_id, '服务已停止')
        return self.get_service_status(service_id)

    def restart_service(self, service_id):
        self.stop_service(service_id)
        return self.start_service(service_id)

    def stop_all(self):
        for service_id in list(self._runtimes.keys()):
            self.stop_service(service_id)

    def get_service_status(self, service_id):
        service_id = str(service_id or '').strip()
        runtime = self._runtimes.get(service_id)
        if runtime:
            status = {
                'running': True,
                'state': 'running',
                'url': runtime.get('url', ''),
                'preview_url': runtime.get('preview_url', ''),
                'tools': list(runtime.get('tools') or []),
                'started_at': runtime.get('started_at', 0),
                'message': runtime.get('message', ''),
            }
            process = runtime.get('process')
            if process is not None and process.poll() is not None:
                status.update({'running': False, 'state': 'stopped', 'message': '进程已退出'})
            return status
        record = self.get_service(service_id)
        if record and record.get('type') in {'http', 'sse'} and record.get('url'):
            return {
                'running': False,
                'state': 'configured',
                'url': record.get('url', ''),
                'preview_url': record.get('url', ''),
                'tools': [],
                'started_at': 0,
                'message': '已配置外部 MCP 地址',
            }
        return {'running': False, 'state': 'stopped', 'url': '', 'preview_url': '', 'tools': [], 'started_at': 0, 'message': '未运行'}

    def get_logs(self, service_id):
        return list(self._logs.get(str(service_id or '').strip(), [])[-80:])

    def open_preview(self, service_id):
        status = self.get_service_status(service_id)
        url = status.get('preview_url') or status.get('url')
        if not url:
            raise MCPServiceError('当前服务没有可打开的地址。')
        webbrowser.open(url)
        return url

    def _start_builtin_ai_diagram(self, record):
        service_id = record.get('id')
        existing = self._runtimes.get(service_id)
        if existing:
            return self.get_service_status(service_id)

        from modules.diagram_mcp import DiagramMCPHTTPServer, DiagramMCPService, MCP_TOOL_NAMES

        def on_update(_session_id, xml):
            bridge = self.app_bridge
            if bridge and hasattr(bridge, 'apply_mcp_diagram_update'):
                try:
                    bridge.apply_mcp_diagram_update(xml)
                except Exception as exc:
                    self._append_log(service_id, f'同步图表到页面失败：{exc}', level='WARN')

        service = DiagramMCPService(on_update=on_update)
        service.start_session(notify=False)
        server = DiagramMCPHTTPServer(service=service, host='127.0.0.1', port=0)
        info = server.start()
        preview_url = ''
        try:
            preview_url = service._preview_url(service.current_session_id)
        except Exception:
            preview_url = info.get('url', '')
        self._runtimes[service_id] = {
            'server': server,
            'service': service,
            'url': info.get('url', ''),
            'preview_url': preview_url or info.get('url', ''),
            'tools': list(MCP_TOOL_NAMES),
            'started_at': int(time.time()),
            'message': 'AI 图表 MCP 已启动',
        }
        self._append_log(service_id, f'服务已启动：{info.get("url")}')
        return self.get_service_status(service_id)

    def _start_stdio_service(self, record):
        service_id = record.get('id')
        existing = self._runtimes.get(service_id)
        if existing:
            return self.get_service_status(service_id)
        command = str(record.get('command') or '').strip()
        if not command:
            raise MCPServiceError('stdio MCP 服务缺少启动命令。')
        args = list(record.get('args') or [])
        env = None
        if isinstance(record.get('env'), dict) and record.get('env'):
            import os
            env = os.environ.copy()
            env.update({str(k): str(v) for k, v in record.get('env').items()})
        process = subprocess.Popen(
            [command, *args],
            cwd=str(record.get('cwd') or '') or None,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        self._runtimes[service_id] = {
            'process': process,
            'url': '',
            'preview_url': '',
            'tools': [],
            'started_at': int(time.time()),
            'message': 'stdio MCP 进程已启动',
        }
        self._append_log(service_id, f'stdio 服务已启动：{command}')
        return self.get_service_status(service_id)

    def _register_remote_service(self, record):
        service_id = record.get('id')
        existing = self._runtimes.get(service_id)
        if existing:
            return self.get_service_status(service_id)
        url = str(record.get('url') or '').strip()
        if not url:
            raise MCPServiceError('HTTP/SSE MCP 服务缺少地址。')
        self._runtimes[service_id] = {
            'url': url,
            'preview_url': url,
            'tools': [],
            'started_at': int(time.time()),
            'message': '外部 MCP 服务已登记',
        }
        self._append_log(service_id, f'外部服务已登记：{url}')
        return self.get_service_status(service_id)

    def _append_log(self, service_id, message, *, level='INFO'):
        service_id = str(service_id or '').strip()
        entry = {
            'time': int(time.time()),
            'level': level,
            'message': str(message or ''),
        }
        self._logs.setdefault(service_id, []).append(entry)
        if len(self._logs[service_id]) > 200:
            self._logs[service_id] = self._logs[service_id][-200:]
        if callable(self.log_callback):
            try:
                self.log_callback(f'[mcp_service] {service_id} {message}', level=level)
            except Exception:
                pass
