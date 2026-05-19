# -*- coding: utf-8 -*-
"""MCP 服务管理面板。"""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import messagebox, simpledialog

from modules.ui_components import (
    bind_adaptive_wrap,
    bind_responsive_two_pane,
    CardFrame,
    COLORS,
    create_home_shell_button,
    create_scrolled_text,
    FONTS,
    ResponsiveButtonBar,
    ScrollablePage,
    ToggleSwitch,
)


_TYPE_LABELS = {
    'builtin_ai_diagram': '内置 HTTP',
    'stdio': 'stdio',
    'http': 'HTTP',
    'sse': 'SSE',
}


def _format_time(ts):
    try:
        value = int(ts or 0)
    except Exception:
        value = 0
    if value <= 0:
        return '未启动'
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(value))


class MCPServicesPanel:
    def __init__(self, parent, config_mgr, service_manager, *, set_status, close_panel=None):
        self.config = config_mgr
        self.manager = service_manager
        self.set_status = set_status
        self.close_panel = close_panel
        self.frame = tk.Frame(parent, bg=COLORS['bg_main'])
        self.services = []
        self.selected_service_id = ''
        self.list_inner = None
        self.detail_inner = None
        self.title_label = None
        self.meta_label = None
        self.status_label = None
        self.url_text = None
        self.tools_text = None
        self.logs_text = None
        self.enabled_var = tk.BooleanVar(value=False)
        self.auto_start_var = tk.BooleanVar(value=False)
        self._rendering_detail = False
        self._build()
        self.refresh_all()

    def _build(self):
        header = tk.Frame(self.frame, bg=COLORS['bg_main'])
        header.pack(fill=tk.X, pady=(0, 14))
        tk.Label(
            header,
            text='MCP 服务',
            font=FONTS['title'],
            fg=COLORS['text_main'],
            bg=COLORS['bg_main'],
        ).pack(anchor='w')
        summary = tk.Label(
            header,
            text='管理应用内置和用户自定义 MCP 服务。已启用且开启自动启动的服务会在应用启动后自动运行。',
            font=FONTS['body'],
            fg=COLORS['text_sub'],
            bg=COLORS['bg_main'],
            anchor='w',
            justify='left',
        )
        summary.pack(fill=tk.X, pady=(8, 0))
        bind_adaptive_wrap(summary, header, padding=12, min_width=320)

        toolbar = ResponsiveButtonBar(self.frame, min_item_width=156, gap_x=8, gap_y=8, bg=COLORS['bg_main'])
        toolbar.pack(fill=tk.X, pady=(0, 14))
        for label, command, style in (
            ('新增 stdio 服务', lambda: self._edit_service(service_type='stdio'), 'primary'),
            ('新增 HTTP 服务', lambda: self._edit_service(service_type='http'), 'secondary'),
            ('新增 SSE 服务', lambda: self._edit_service(service_type='sse'), 'secondary'),
            ('刷新状态', self.refresh_all, 'secondary'),
        ):
            toolbar.add(create_home_shell_button(toolbar, label, command=command, style=style, padx=14, pady=7)[0])

        body = tk.Frame(self.frame, bg=COLORS['bg_main'])
        body.pack(fill=tk.BOTH, expand=True)
        left_card = CardFrame(body, title='服务列表')
        right_card = CardFrame(body, title='服务详情')
        self._build_left(left_card.inner)
        self._build_right(right_card.inner)
        bind_responsive_two_pane(body, left_card, right_card, breakpoint=1320, gap=12, left_minsize=380)

    def _build_left(self, parent):
        view = ScrollablePage(parent, bg=COLORS['card_bg'])
        view.pack(fill=tk.BOTH, expand=True)
        self.list_inner = view.inner

    def _build_right(self, parent):
        view = ScrollablePage(parent, bg=COLORS['card_bg'])
        view.pack(fill=tk.BOTH, expand=True)
        self.detail_inner = view.inner
        self.title_label = tk.Label(self.detail_inner, text='请选择左侧服务', font=FONTS['title'], fg=COLORS['text_main'], bg=COLORS['card_bg'], anchor='w')
        self.title_label.pack(fill=tk.X)
        self.meta_label = tk.Label(self.detail_inner, text='', font=FONTS['small'], fg=COLORS['text_sub'], bg=COLORS['card_bg'], anchor='w', justify='left')
        self.meta_label.pack(fill=tk.X, pady=(6, 0))
        bind_adaptive_wrap(self.meta_label, self.detail_inner, padding=12, min_width=320)
        self.status_label = tk.Label(self.detail_inner, text='未选择服务', font=FONTS['body_bold'], fg=COLORS['text_sub'], bg=COLORS['card_bg'], anchor='w')
        self.status_label.pack(fill=tk.X, pady=(14, 0))

        toggles = tk.Frame(self.detail_inner, bg=COLORS['card_bg'])
        toggles.pack(fill=tk.X, pady=(14, 0))
        self._build_toggle(toggles, '启用服务', self.enabled_var).pack(side=tk.LEFT, padx=(0, 18))
        self._build_toggle(toggles, '应用启动后自动运行', self.auto_start_var).pack(side=tk.LEFT)

        actions = ResponsiveButtonBar(self.detail_inner, min_item_width=130, gap_x=8, gap_y=8, bg=COLORS['card_bg'])
        actions.pack(fill=tk.X, pady=(16, 10))
        for label, command, style in (
            ('启动', self._start_selected, 'primary'),
            ('停止', self._stop_selected, 'secondary'),
            ('重启', self._restart_selected, 'secondary'),
            ('打开预览', self._open_preview_selected, 'secondary'),
            ('复制连接', self._copy_connection, 'secondary'),
            ('编辑', lambda: self._edit_service(service_id=self.selected_service_id), 'secondary'),
            ('删除', self._delete_selected, 'danger'),
        ):
            actions.add(create_home_shell_button(actions, label, command=command, style=style, padx=12, pady=7)[0])

        self.url_text = self._readonly_section('连接信息', height=4)
        self.tools_text = self._readonly_section('工具列表', height=8)
        self.logs_text = self._readonly_section('最近日志', height=8)

    def _build_toggle(self, parent, label, variable):
        group = tk.Frame(parent, bg=COLORS['card_bg'])
        ToggleSwitch(group, variable=variable, command=self._save_selected_toggles, bg=COLORS['card_bg']).pack(side=tk.LEFT)
        tk.Label(
            group,
            text=label,
            font=FONTS['small'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.LEFT, padx=(8, 0))
        return group

    def _readonly_section(self, title, height):
        tk.Label(self.detail_inner, text=title, font=FONTS['body_bold'], fg=COLORS['text_main'], bg=COLORS['card_bg']).pack(fill=tk.X, pady=(12, 6))
        box, text = create_scrolled_text(self.detail_inner, height=height)
        box.pack(fill=tk.X, pady=(0, 4))
        text.configure(state=tk.DISABLED, font=FONTS['small'])
        return text

    def refresh_all(self):
        self.services = self.manager.list_services() if self.manager else []
        if not self.selected_service_id and self.services:
            self.selected_service_id = self.services[0].get('id', '')
        ids = {item.get('id') for item in self.services}
        if self.selected_service_id not in ids:
            self.selected_service_id = self.services[0].get('id', '') if self.services else ''
        self._render_list()
        self._render_detail()

    def _render_list(self):
        for child in self.list_inner.winfo_children():
            child.destroy()
        if not self.services:
            tk.Label(self.list_inner, text='暂无 MCP 服务', font=FONTS['body'], fg=COLORS['text_sub'], bg=COLORS['card_bg']).pack(anchor='w', padx=10, pady=10)
            return
        for service in self.services:
            selected = service.get('id') == self.selected_service_id
            status = service.get('status') or {}
            card = tk.Frame(self.list_inner, bg=COLORS['accent_light'] if selected else COLORS['surface_alt'], highlightbackground=COLORS['card_border'], highlightthickness=1, cursor='hand2')
            card.pack(fill=tk.X, padx=6, pady=(0, 8))
            card.bind('<Button-1>', lambda _e, sid=service.get('id'): self._select(sid))
            tk.Label(card, text=service.get('name', service.get('id', '')), font=FONTS['body_bold'], fg=COLORS['text_main'], bg=card.cget('bg'), anchor='w').pack(fill=tk.X, padx=10, pady=(8, 2))
            state = '运行中' if status.get('running') else '未运行'
            line = f'{_TYPE_LABELS.get(service.get("type"), service.get("type"))} · {state}'
            if service.get('auto_start'):
                line += ' · 自动启动'
            tk.Label(card, text=line, font=FONTS['small'], fg=COLORS['text_sub'], bg=card.cget('bg'), anchor='w').pack(fill=tk.X, padx=10, pady=(0, 8))

    def _select(self, service_id):
        self.selected_service_id = service_id
        self._render_list()
        self._render_detail()

    def _selected_service(self):
        return next((item for item in self.services if item.get('id') == self.selected_service_id), None)

    def _render_detail(self):
        service = self._selected_service()
        self._rendering_detail = True
        try:
            self._render_detail_content(service)
        finally:
            self._rendering_detail = False

    def _render_detail_content(self, service):
        if not service:
            self.title_label.configure(text='请选择左侧服务')
            self.meta_label.configure(text='')
            self.status_label.configure(text='未选择服务', fg=COLORS['text_sub'])
            self.enabled_var.set(False)
            self.auto_start_var.set(False)
            self._set_text(self.url_text, '')
            self._set_text(self.tools_text, '')
            self._set_text(self.logs_text, '')
            return
        status = service.get('status') or {}
        self.title_label.configure(text=service.get('name') or service.get('id'))
        self.meta_label.configure(text=f'ID：{service.get("id")}    类型：{_TYPE_LABELS.get(service.get("type"), service.get("type"))}    创建时间：{_format_time(service.get("created_at"))}')
        self.status_label.configure(
            text=f'状态：{"运行中" if status.get("running") else "未运行"}    启动时间：{_format_time(status.get("started_at"))}',
            fg=COLORS['success'] if status.get('running') else COLORS['text_sub'],
        )
        self.enabled_var.set(bool(service.get('enabled')))
        self.auto_start_var.set(bool(service.get('auto_start')))
        self._set_text(self.url_text, self._connection_text(service, status))
        tools = status.get('tools') or []
        self._set_text(self.tools_text, '\n'.join(tools) if tools else '暂无工具列表。')
        logs = self.manager.get_logs(service.get('id')) if self.manager else []
        self._set_text(self.logs_text, '\n'.join(f'[{_format_time(item.get("time"))}] {item.get("level", "INFO")} {item.get("message", "")}' for item in logs) or '暂无日志。')

    def _connection_text(self, service, status):
        lines = [
            f'运行地址：{status.get("url") or service.get("url") or "未提供"}',
            f'预览地址：{status.get("preview_url") or "未提供"}',
        ]
        if service.get('type') == 'stdio':
            lines.append(f'启动命令：{service.get("command", "")} {" ".join(service.get("args", []))}'.strip())
        return '\n'.join(lines)

    def _set_text(self, widget, text):
        widget.configure(state=tk.NORMAL)
        widget.delete('1.0', tk.END)
        widget.insert('1.0', text or '')
        widget.configure(state=tk.DISABLED)

    def _save_selected_toggles(self):
        if self._rendering_detail:
            return
        service = self._selected_service()
        if not service:
            return
        service['enabled'] = bool(self.enabled_var.get())
        service['auto_start'] = bool(self.auto_start_var.get())
        self.manager.save_service(service.get('id'), service)
        self.set_status('MCP 服务配置已保存')
        self.refresh_all()

    def _start_selected(self):
        self._run_selected_action('启动', lambda sid: self.manager.start_service(sid))

    def _stop_selected(self):
        self._run_selected_action('停止', lambda sid: self.manager.stop_service(sid))

    def _restart_selected(self):
        self._run_selected_action('重启', lambda sid: self.manager.restart_service(sid))

    def _run_selected_action(self, label, action):
        service = self._selected_service()
        if not service:
            messagebox.showwarning('MCP 服务', '请先选择一个 MCP 服务。', parent=self.frame.winfo_toplevel())
            return
        try:
            action(service.get('id'))
            self.set_status(f'MCP 服务已{label}：{service.get("name")}')
        except Exception as exc:
            messagebox.showerror('MCP 服务', str(exc), parent=self.frame.winfo_toplevel())
        self.refresh_all()

    def _open_preview_selected(self):
        service = self._selected_service()
        if not service:
            return
        try:
            self.manager.open_preview(service.get('id'))
        except Exception as exc:
            messagebox.showwarning('MCP 服务', str(exc), parent=self.frame.winfo_toplevel())

    def _copy_connection(self):
        service = self._selected_service()
        if not service:
            return
        text = self._connection_text(service, service.get('status') or {})
        self.frame.clipboard_clear()
        self.frame.clipboard_append(text)
        self.frame.update_idletasks()
        self.set_status('MCP 服务连接信息已复制')

    def _edit_service(self, service_id='', service_type='stdio'):
        service = self.manager.get_service(service_id) if service_id else {'type': service_type, 'enabled': True, 'auto_start': False}
        if service.get('builtin'):
            messagebox.showinfo('MCP 服务', '内置服务只能修改启用和自动启动状态。', parent=self.frame.winfo_toplevel())
            return
        name = simpledialog.askstring('MCP 服务', '服务名称：', initialvalue=service.get('name', ''), parent=self.frame.winfo_toplevel())
        if not name:
            return
        service['name'] = name.strip()
        if not service.get('id'):
            service['id'] = f'mcp_{int(time.time() * 1000)}'
        service['type'] = service.get('type') or service_type
        if service['type'] == 'stdio':
            command = simpledialog.askstring('MCP 服务', '启动命令路径：', initialvalue=service.get('command', ''), parent=self.frame.winfo_toplevel())
            if command is None:
                return
            service['command'] = command.strip()
            args = simpledialog.askstring('MCP 服务', '启动参数（每行一个）：', initialvalue='\n'.join(service.get('args', [])), parent=self.frame.winfo_toplevel())
            service['args'] = [line.strip() for line in str(args or '').splitlines() if line.strip()]
            cwd = simpledialog.askstring('MCP 服务', '工作目录（可选）：', initialvalue=service.get('cwd', ''), parent=self.frame.winfo_toplevel())
            if cwd is None:
                return
            service['cwd'] = cwd.strip()
            env_text = simpledialog.askstring(
                'MCP 服务',
                '环境变量（每行 KEY=VALUE，可选）：',
                initialvalue='\n'.join(f'{key}={value}' for key, value in (service.get('env') or {}).items()),
                parent=self.frame.winfo_toplevel(),
            )
            if env_text is None:
                return
            env = {}
            for line in str(env_text or '').splitlines():
                key, sep, value = line.partition('=')
                key = key.strip()
                if sep and key:
                    env[key] = value.strip()
            service['env'] = env
        else:
            url = simpledialog.askstring('MCP 服务', '服务地址：', initialvalue=service.get('url', ''), parent=self.frame.winfo_toplevel())
            if url is None:
                return
            service['url'] = url.strip()
        self.manager.save_service(service.get('id'), service)
        self.set_status('MCP 服务已保存')
        self.selected_service_id = service.get('id')
        self.refresh_all()

    def _delete_selected(self):
        service = self._selected_service()
        if not service:
            return
        if service.get('builtin'):
            messagebox.showinfo('MCP 服务', '内置 MCP 服务不能删除。', parent=self.frame.winfo_toplevel())
            return
        if not messagebox.askyesno('MCP 服务', f'删除 MCP 服务「{service.get("name")}」？', parent=self.frame.winfo_toplevel()):
            return
        ok = self.manager.delete_service(service.get('id'))
        if not ok:
            messagebox.showwarning('MCP 服务', '服务删除失败。', parent=self.frame.winfo_toplevel())
        self.selected_service_id = ''
        self.refresh_all()
