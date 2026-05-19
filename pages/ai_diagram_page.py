# -*- coding: utf-8 -*-
"""
独立 AI 图表页面。

该页面只负责桌面端交互、历史快照和写回论文正文；图表生成与修改由
modules.diagram_ai.DiagramAIService 统一执行，draw.io 可视化编辑由本地
pywebview 资源承接。
"""

from __future__ import annotations

import copy
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

try:
    from PIL import Image, ImageTk
except ImportError:  # pragma: no cover - 运行环境缺少 Pillow 时降级为文本预览
    Image = None
    ImageTk = None

from modules.app_metadata import MODULE_AI_DIAGRAM
from modules.diagram_ai import DiagramAIService, diagram_block_from_xml
from modules.diagram_blocks import diagram_placeholder_text, sanitize_diagram_block
from modules.diagram_export import DiagramExportError, export_diagram_file, safe_diagram_filename
from modules.diagram_format import json_to_mxgraph_xml, mxgraph_xml_to_json
from modules.diagram_thumbnail import load_image_from_block, render_placeholder_b64, render_placeholder_png
from modules.diagram_tools import DiagramToolError, analyze_mxgraph_xml, validate_mxgraph_xml
from modules.diagram_session_store import (
    delete_diagram_session,
    list_diagram_sessions,
    save_diagram_session,
)
from modules.task_runner import TaskRunner
from modules.ui_components import (
    COLORS,
    FONTS,
    CardFrame,
    LoadingOverlay,
    bind_responsive_two_pane,
    create_home_shell_button,
)
from modules.workspace_state import WorkspaceStateMixin
from modules.diagram_vlm import validate_diagram_visual
from pages.home_support import ensure_model_configured


class AIDiagramPage(WorkspaceStateMixin):
    PAGE_STATE_ID = 'ai_diagram'
    PREVIEW_W = 620
    PREVIEW_H = 380

    def __init__(self, parent, config_mgr, api_client, history_mgr, set_status,
                 navigate_page=None, app_bridge=None):
        self.config = config_mgr
        self.api = api_client
        self.history = history_mgr
        self.set_status = set_status
        self.navigate_page = navigate_page
        self.app_bridge = app_bridge
        self.ai_service = DiagramAIService(api_client)

        self.frame = tk.Frame(parent, bg=COLORS['bg_main'])
        self.loading = LoadingOverlay(self.frame, config_mgr, text='正在生成图表...')
        self.task_runner = TaskRunner(self.frame, loading=self.loading, set_status=self.set_status)

        self.session_title_var = tk.StringVar(value='')
        self.section_hint_var = tk.StringVar(value='')
        self.use_knowledge_var = tk.BooleanVar(value=False)
        self.knowledge_status_var = tk.StringVar(value='')
        self.minimal_style_var = tk.BooleanVar(value=False)
        self.auto_vlm_var = tk.BooleanVar(value=False)
        self.custom_system_prompt_var = tk.StringVar(value='')

        self.current_block = None
        self.pending_xml = ''
        self.messages = []
        self.selected_knowledge_context = {}
        self._preview_photo = None
        self.send_button = None
        self.stop_button = None
        self.generation_status_label = None
        self._active_task_id = None
        self._mcp_server = None
        self._caption_sync_job = None
        self._busy = False

        self._init_workspace_state_support()
        self._build()
        self.restore_saved_workspace_state()
        self._bind_workspace_state_watchers()
        self._refresh_all()
        self._enable_workspace_state_autosave()

    def _build(self):
        self._build_session_bar()

        body = tk.Frame(self.frame, bg=COLORS['bg_main'])
        body.pack(fill=tk.BOTH, expand=True)

        left_card = CardFrame(body, title='AI 对话')
        right_card = CardFrame(body, title='图表画布')
        self._build_chat_title_actions(left_card.title_frame)
        self._build_chat_panel(left_card.inner)
        self._build_canvas_title_actions(right_card.title_frame)
        self._build_canvas_panel(right_card.inner)

        bind_responsive_two_pane(
            body,
            left_card,
            right_card,
            breakpoint=1180,
            gap=8,
            left_minsize=380,
            left_weight=3,
            right_weight=7,
            uniform_group='ai_diagram_body',
        )

    def _build_session_bar(self):
        card = CardFrame(self.frame)
        card.pack(fill=tk.X, pady=(0, 10))
        inner = card.inner

        layout = tk.Frame(inner, bg=COLORS['card_bg'])
        layout.pack(fill=tk.X)
        layout.grid_columnconfigure(0, weight=1)
        layout.grid_columnconfigure(1, weight=0)

        info_area = tk.Frame(layout, bg=COLORS['card_bg'])
        info_area.grid(row=0, column=0, sticky='w')
        tk.Label(
            info_area,
            text='图表信息与操作',
            font=FONTS['heading'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(anchor='w')

        row = tk.Frame(info_area, bg=COLORS['card_bg'])
        row.pack(fill=tk.X, pady=(18, 0))
        self._build_labeled_entry(row, '图注', self.session_title_var, width=28)
        self._build_labeled_entry(row, '插入章节', self.section_hint_var, width=32, readonly=True)

        actions = tk.Frame(layout, bg=COLORS['card_bg'])
        actions.grid(row=0, column=1, sticky='e', padx=(24, 0))
        tools_row = tk.Frame(actions, bg=COLORS['card_bg'])
        tools_row.pack(anchor='e')
        self._add_button(tools_row, '知识库管理', self._open_knowledge_base_manager, padx=10, pady=4)
        self._add_button(tools_row, '图表偏好', self._show_diagram_preferences, padx=10, pady=4)
        self._add_button(tools_row, '保存快照', self._save_manual_snapshot, padx=10, pady=4)

    def _build_labeled_entry(self, parent, label, variable, width=20, readonly=False):
        group = tk.Frame(parent, bg=COLORS['card_bg'])
        group.pack(side=tk.LEFT, padx=(0, 12))
        tk.Label(
            group,
            text=label,
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
        ).pack(anchor='w')
        entry = tk.Entry(
            group,
            textvariable=variable,
            width=width,
            font=FONTS['body'],
            bg=COLORS['input_bg'],
            fg=COLORS['text_main'],
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=COLORS['input_border'],
        )
        if readonly:
            entry.configure(state='readonly', readonlybackground=COLORS['input_bg'])
        entry.pack(fill=tk.X, pady=(4, 0), ipady=3)
        return entry

    def _show_diagram_preferences(self):
        top = self._create_manager_window('图表偏好', width=640, height=460)
        container = tk.Frame(top, bg=COLORS['card_bg'])
        container.pack(fill=tk.BOTH, expand=True, padx=14, pady=14)

        minimal = tk.BooleanVar(value=bool(self.minimal_style_var.get()))
        auto_vlm = tk.BooleanVar(value=bool(self.auto_vlm_var.get()))

        for text, variable in (
            ('简约图表风格', minimal),
            ('生成后自动视觉校验并按建议重试', auto_vlm),
        ):
            box = tk.Checkbutton(
                container,
                text=text,
                variable=variable,
                font=FONTS['body'],
                fg=COLORS['text_main'],
                bg=COLORS['card_bg'],
                activebackground=COLORS['card_bg'],
                selectcolor=COLORS['card_bg'],
                relief=tk.FLAT,
                highlightthickness=0,
            )
            box.pack(anchor='w', pady=(0, 8))

        tk.Label(
            container,
            text='自定义系统提示',
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(anchor='w', pady=(8, 4))
        prompt_frame = tk.Frame(container, bg=COLORS['card_bg'], highlightthickness=1, highlightbackground=COLORS['input_border'])
        prompt_frame.pack(fill=tk.BOTH, expand=True)
        prompt_text = tk.Text(
            prompt_frame,
            height=8,
            wrap=tk.WORD,
            font=FONTS['body'],
            bg=COLORS['input_bg'],
            fg=COLORS['text_main'],
            relief=tk.FLAT,
        )
        prompt_text.pack(fill=tk.BOTH, expand=True)
        prompt_text.insert('1.0', self.custom_system_prompt_var.get())

        def save():
            self.minimal_style_var.set(bool(minimal.get()))
            self.auto_vlm_var.set(bool(auto_vlm.get()))
            self.custom_system_prompt_var.set(prompt_text.get('1.0', tk.END).strip()[:5000])
            self._schedule_workspace_state_save()
            top.destroy()
            self.set_status('AI 图表偏好已保存')

        self._build_manager_actions(top, [('保存', save), ('关闭', top.destroy)])

    def _build_chat_title_actions(self, parent):
        if parent is None:
            return
        action_row = tk.Frame(parent, bg=COLORS['card_bg'])
        action_row.grid(row=0, column=1, sticky='e')
        self.send_button = self._add_button(
            action_row,
            '发送',
            self._send_instruction,
            style='primary',
            padx=10,
            pady=4,
        )
        self.stop_button = self._add_button(
            action_row,
            '停止',
            self._stop_generation,
            padx=10,
            pady=4,
        )
        try:
            self.stop_button.configure(state=tk.DISABLED)
        except Exception:
            pass
        self._add_button(action_row, '清空消息', self._clear_messages, padx=10, pady=4)

    def _build_canvas_title_actions(self, parent):
        if parent is None:
            return
        action_row = tk.Frame(parent, bg=COLORS['card_bg'])
        action_row.grid(row=0, column=1, sticky='e')
        self._add_button(action_row, '打开图表编辑器', self._open_editor, style='primary', padx=10, pady=4)
        self._add_button(action_row, '插入正文', self._insert_to_paper_write, padx=10, pady=4)
        self._add_button(action_row, '校验图表', self._run_combined_validation, padx=10, pady=4)
        self._add_button(action_row, '恢复上一版', self._restore_previous_version, padx=10, pady=4)

    def _build_canvas_panel(self, parent):
        preview_shell = tk.Frame(
            parent,
            bg=COLORS['card_bg'],
            highlightbackground=COLORS['card_border'],
            highlightthickness=1,
        )
        preview_shell.pack(fill=tk.BOTH, expand=True)

        self.preview_canvas = tk.Canvas(
            preview_shell,
            width=self.PREVIEW_W,
            height=self.PREVIEW_H,
            bg='#FAFAFA',
            highlightthickness=0,
        )
        self.preview_canvas.pack(fill=tk.BOTH, expand=True)
        self.preview_canvas.bind('<Configure>', lambda _e: self._refresh_preview())

        self.diagram_meta_label = tk.Label(
            parent,
            text='',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            anchor='w',
            justify=tk.LEFT,
        )
        self.diagram_meta_label.pack(fill=tk.X, pady=(8, 0))

        xml_header = tk.Frame(parent, bg=COLORS['card_bg'])
        xml_header.pack(fill=tk.X, pady=(6, 4))
        tk.Label(
            xml_header,
            text='当前 XML 上下文',
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.LEFT)
        self.xml_status_label = tk.Label(
            xml_header,
            text='',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
        )
        self.xml_status_label.pack(side=tk.RIGHT)

        xml_frame = tk.Frame(
            parent,
            bg=COLORS['card_bg'],
            highlightbackground=COLORS['input_border'],
            highlightthickness=1,
        )
        xml_frame.pack(fill=tk.BOTH, expand=True)
        xml_scroll = tk.Scrollbar(xml_frame, orient=tk.VERTICAL)
        xml_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.xml_text = tk.Text(
            xml_frame,
            height=9,
            wrap=tk.NONE,
            font=('Consolas', 10),
            bg=COLORS['input_bg'],
            fg=COLORS['text_main'],
            relief=tk.FLAT,
            yscrollcommand=xml_scroll.set,
        )
        self.xml_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        xml_scroll.config(command=self.xml_text.yview)
        self.xml_text.configure(state=tk.DISABLED)

        validation_header = tk.Frame(parent, bg=COLORS['card_bg'])
        validation_header.pack(fill=tk.X, pady=(8, 4))
        tk.Label(
            validation_header,
            text='结构校验报告',
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.LEFT)
        self.validation_status_label = tk.Label(
            validation_header,
            text='',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
        )
        self.validation_status_label.pack(side=tk.RIGHT)

        validation_frame = tk.Frame(
            parent,
            bg=COLORS['card_bg'],
            highlightbackground=COLORS['input_border'],
            highlightthickness=1,
        )
        validation_frame.pack(fill=tk.BOTH, expand=False)
        validation_scroll = tk.Scrollbar(validation_frame, orient=tk.VERTICAL)
        validation_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.validation_text = tk.Text(
            validation_frame,
            height=6,
            wrap=tk.WORD,
            font=FONTS['small'],
            bg=COLORS['input_bg'],
            fg=COLORS['text_main'],
            relief=tk.FLAT,
            yscrollcommand=validation_scroll.set,
        )
        self.validation_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        validation_scroll.config(command=self.validation_text.yview)
        self.validation_text.configure(state=tk.DISABLED)

        visual_header = tk.Frame(parent, bg=COLORS['card_bg'])
        visual_header.pack(fill=tk.X, pady=(8, 4))
        tk.Label(
            visual_header,
            text='视觉校验报告',
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.LEFT)
        self.visual_validation_status_label = tk.Label(
            visual_header,
            text='未运行',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
        )
        self.visual_validation_status_label.pack(side=tk.RIGHT)

        visual_frame = tk.Frame(
            parent,
            bg=COLORS['card_bg'],
            highlightbackground=COLORS['input_border'],
            highlightthickness=1,
        )
        visual_frame.pack(fill=tk.BOTH, expand=False)
        visual_scroll = tk.Scrollbar(visual_frame, orient=tk.VERTICAL)
        visual_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.visual_validation_text = tk.Text(
            visual_frame,
            height=5,
            wrap=tk.WORD,
            font=FONTS['small'],
            bg=COLORS['input_bg'],
            fg=COLORS['text_main'],
            relief=tk.FLAT,
            yscrollcommand=visual_scroll.set,
        )
        self.visual_validation_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        visual_scroll.config(command=self.visual_validation_text.yview)
        self.visual_validation_text.configure(state=tk.DISABLED)

    def _build_chat_panel(self, parent):
        input_header = tk.Frame(parent, bg=COLORS['card_bg'])
        input_header.pack(fill=tk.X, pady=(0, 4))
        tk.Label(
            input_header,
            text='自然语言指令',
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.LEFT)
        tk.Label(
            input_header,
            text='Ctrl+Enter 发送',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.RIGHT)

        input_frame = tk.Frame(
            parent,
            bg=COLORS['card_bg'],
            highlightbackground=COLORS['input_border'],
            highlightthickness=1,
        )
        input_frame.pack(fill=tk.X)
        self.input_text = tk.Text(
            input_frame,
            height=5,
            wrap=tk.WORD,
            font=FONTS['body'],
            bg=COLORS['input_bg'],
            fg=COLORS['text_main'],
            relief=tk.FLAT,
            undo=True,
        )
        self.input_text.pack(fill=tk.BOTH, expand=True)
        self.input_text.bind('<Control-Return>', lambda _e: self._send_instruction())
        self.input_text.bind('<KeyRelease>', self._schedule_workspace_state_save)

        self.generation_status_label = tk.Label(
            parent,
            text='生成状态：空闲',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            anchor='w',
        )
        self.generation_status_label.pack(fill=tk.X, pady=(4, 0))

        self._build_conversation_panel(parent)

    def _build_conversation_panel(self, parent):
        messages_header = tk.Frame(parent, bg=COLORS['card_bg'])
        messages_header.pack(fill=tk.X, pady=(12, 4))
        tk.Label(
            messages_header,
            text='AI 对话记录',
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.LEFT)
        action_row = tk.Frame(messages_header, bg=COLORS['card_bg'])
        action_row.pack(side=tk.RIGHT)
        self._add_button(action_row, '复制', self._copy_messages, padx=10, pady=4)
        self._add_button(action_row, '保存', self._save_current_session, padx=10, pady=4)
        self._add_button(action_row, '新建', self._new_session, padx=10, pady=4)
        self._add_button(action_row, '管理会话', self._show_session_manager, padx=10, pady=4)

        messages_frame = tk.Frame(
            parent,
            bg=COLORS['card_bg'],
            highlightbackground=COLORS['input_border'],
            highlightthickness=1,
        )
        messages_frame.pack(fill=tk.BOTH, expand=True)
        msg_scroll = tk.Scrollbar(messages_frame, orient=tk.VERTICAL)
        msg_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.messages_text = tk.Text(
            messages_frame,
            wrap=tk.WORD,
            font=FONTS['body'],
            bg=COLORS['input_bg'],
            fg=COLORS['text_main'],
            relief=tk.FLAT,
            yscrollcommand=msg_scroll.set,
        )
        self.messages_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        msg_scroll.config(command=self.messages_text.yview)
        self.messages_text.configure(state=tk.DISABLED)

    def _add_button(self, parent, text, command, style='secondary', padx=14, pady=6):
        shell, button = create_home_shell_button(
            parent,
            text,
            command=command,
            style=style,
            padx=padx,
            pady=pady,
            font=FONTS['small'],
        )
        shell.pack(side=tk.LEFT, padx=(0, 8), pady=(0, 4))
        return button

    def _clear_input_text(self):
        if hasattr(self, 'input_text'):
            self._set_input_text('')

    def _current_input_text(self):
        if not hasattr(self, 'input_text'):
            return ''
        try:
            return self.input_text.get('1.0', tk.END).strip()
        except tk.TclError:
            return ''

    def _set_input_text(self, text, *, schedule=True):
        if not hasattr(self, 'input_text'):
            return
        try:
            self.input_text.delete('1.0', tk.END)
            if text:
                self.input_text.insert('1.0', str(text))
        except tk.TclError:
            return
        if schedule:
            self._schedule_workspace_state_save()

    def _current_caption(self):
        caption = self.session_title_var.get().strip()
        if caption == '未命名图表会话':
            return ''
        return caption

    def _current_block_with_caption(self):
        if not isinstance(self.current_block, dict):
            return None
        block = copy.deepcopy(self.current_block)
        caption = self._current_caption()
        if caption and str(block.get('caption') or '').strip() != caption:
            block['caption'] = caption
            block.pop('thumbnail_b64', None)
            block.pop('thumbnail_path', None)
            thumb_b64, thumb_path = render_placeholder_b64(
                block.get('json_graph') or {},
                caption=caption,
            )
            if thumb_b64:
                block['thumbnail_b64'] = thumb_b64
            if thumb_path:
                block['thumbnail_path'] = thumb_path
        elif caption:
            block['caption'] = caption
        return sanitize_diagram_block(block) or block

    def _sync_current_block_caption(self):
        block = self._current_block_with_caption()
        if not isinstance(block, dict):
            return
        if block != self.current_block:
            self.current_block = block
            self._refresh_preview()

    def _current_paper_section_title(self):
        if not self.app_bridge or not hasattr(self.app_bridge, 'pull_paper_write_context'):
            return ''
        try:
            context = self.app_bridge.pull_paper_write_context() or {}
        except Exception:
            return ''
        selected = str(context.get('selected_section') or '').strip()
        current = str(context.get('current_section') or '').strip()
        return selected or current

    def _sync_section_hint_from_paper_write(self):
        section = self._current_paper_section_title()
        if section:
            self.section_hint_var.set(section)
        return section

    def on_show(self):
        self._sync_section_hint_from_paper_write()

    def _on_caption_changed(self, *_args):
        self._schedule_workspace_state_save()
        if not isinstance(self.current_block, dict):
            return
        if self._caption_sync_job is not None:
            try:
                self.frame.after_cancel(self._caption_sync_job)
            except Exception:
                pass
        self._caption_sync_job = self.frame.after(300, self._run_caption_sync)

    def _run_caption_sync(self):
        self._caption_sync_job = None
        self._sync_current_block_caption()

    def _bind_workspace_state_watchers(self):
        self.session_title_var.trace_add('write', self._on_caption_changed)
        self.section_hint_var.trace_add('write', lambda *_args: self._schedule_workspace_state_save())
        self.use_knowledge_var.trace_add('write', lambda *_args: self._schedule_workspace_state_save())
        self.minimal_style_var.trace_add('write', lambda *_args: self._schedule_workspace_state_save())
        self.auto_vlm_var.trace_add('write', lambda *_args: self._schedule_workspace_state_save())
        self.custom_system_prompt_var.trace_add('write', lambda *_args: self._schedule_workspace_state_save())

    def export_workspace_state(self):
        current_block = self._current_block_with_caption()
        return {
            'session_title': self.session_title_var.get().strip(),
            'caption': self._current_caption(),
            'section_hint': self.section_hint_var.get().strip(),
            'use_knowledge_context': bool(self.use_knowledge_var.get()),
            'minimal_style': bool(self.minimal_style_var.get()),
            'auto_vlm_validation': bool(self.auto_vlm_var.get()),
            'custom_system_prompt': self.custom_system_prompt_var.get().strip(),
            'input_draft': self._current_input_text(),
            'current_block': current_block,
            'pending_xml': self.pending_xml,
            'messages': copy.deepcopy(self.messages[-100:]),
        }

    def restore_workspace_state(self, state):
        if not isinstance(state, dict):
            return
        caption = str(state.get('caption') or state.get('session_title') or '').strip()
        if caption == '未命名图表会话':
            caption = ''
        self.session_title_var.set(caption)
        self.section_hint_var.set(str(state.get('section_hint') or ''))
        self.use_knowledge_var.set(bool(state.get('use_knowledge_context', False)))
        self.minimal_style_var.set(bool(state.get('minimal_style', False)))
        self.auto_vlm_var.set(bool(state.get('auto_vlm_validation', False)))
        self.custom_system_prompt_var.set(str(state.get('custom_system_prompt') or '')[:5000])
        block = state.get('current_block')
        self.current_block = sanitize_diagram_block(block) if isinstance(block, dict) else None
        self.pending_xml = str(state.get('pending_xml') or '')
        raw_messages = state.get('messages', [])
        self.messages = [item for item in raw_messages if isinstance(item, dict)][-100:] if isinstance(raw_messages, list) else []
        self.selected_knowledge_context = {}
        if hasattr(self, 'input_text'):
            self._set_input_text(str(state.get('input_draft') or ''), schedule=False)
        self._refresh_all()

    def _refresh_all(self):
        self._refresh_preview()
        self._refresh_xml_view()
        self._refresh_messages()
        self._refresh_knowledge_status()
        self._refresh_visual_validation_empty()
        self._set_generation_status('生成状态：空闲')

    def _current_xml(self):
        block = self.current_block if isinstance(self.current_block, dict) else {}
        xml = str(block.get('mxgraph_xml') or '').strip()
        if xml:
            return xml
        graph = block.get('json_graph')
        if isinstance(graph, dict) and (graph.get('nodes') or graph.get('edges') or graph.get('groups')):
            return json_to_mxgraph_xml(graph)
        return ''

    def _preview_canvas_size(self):
        width = self.PREVIEW_W
        height = self.PREVIEW_H
        try:
            actual_w = int(self.preview_canvas.winfo_width())
            actual_h = int(self.preview_canvas.winfo_height())
            if actual_w > 1:
                width = actual_w
            if actual_h > 1:
                height = actual_h
        except Exception:
            pass
        return max(120, width), max(90, height)

    def _refresh_preview(self):
        if not hasattr(self, 'diagram_meta_label'):
            return
        self.preview_canvas.delete('all')
        canvas_w, canvas_h = self._preview_canvas_size()
        block = self.current_block
        if not isinstance(block, dict):
            self._preview_photo = None
            self.preview_canvas.create_text(
                canvas_w / 2,
                canvas_h / 2,
                text='当前没有图表',
                font=FONTS['body_bold'],
                fill=COLORS['text_sub'],
            )
            self.diagram_meta_label.configure(text='未生成图表')
            return

        image = load_image_from_block(block)
        if image is None and Image is not None:
            image = render_placeholder_png(
                block.get('json_graph') or {},
                caption=block.get('caption') or '',
                size=(canvas_w, canvas_h),
            )

        if image is not None and ImageTk is not None:
            preview = image.copy()
            try:
                resampling = Image.Resampling.LANCZOS
            except AttributeError:  # Pillow < 9
                resampling = Image.LANCZOS
            preview.thumbnail((max(80, canvas_w - 24), max(60, canvas_h - 24)), resampling)
            self._preview_photo = ImageTk.PhotoImage(preview)
            self.preview_canvas.create_image(
                canvas_w / 2,
                canvas_h / 2,
                image=self._preview_photo,
            )
        else:
            self._preview_photo = None
            self.preview_canvas.create_text(
                canvas_w / 2,
                canvas_h / 2,
                text=diagram_placeholder_text(block),
                font=FONTS['body_bold'],
                fill=COLORS['text_sub'],
                width=max(120, canvas_w - 40),
            )

        graph = block.get('json_graph') or {}
        nodes = len(graph.get('nodes') or []) if isinstance(graph, dict) else 0
        edges = len(graph.get('edges') or []) if isinstance(graph, dict) else 0
        fmt = block.get('authoring_format') or 'drawio'
        caption = block.get('caption') or '未命名图表'
        self.diagram_meta_label.configure(
            text=f'{caption}    格式：{fmt}    节点：{nodes}    连线：{edges}'
        )

    def _refresh_xml_view(self):
        xml = self._current_xml()
        status = '无 XML'
        text = '当前没有 draw.io XML。'
        if xml:
            try:
                stats = validate_mxgraph_xml(xml)
                status = f'单元 {stats.get("cell_count", 0)} / 节点 {stats.get("vertex_count", 0)} / 连线 {stats.get("edge_count", 0)}'
            except DiagramToolError as exc:
                status = 'XML 校验失败'
                text = f'{exc}\n\n{xml[:12000]}'
            else:
                pending = f'\n\n待续写片段：\n{self.pending_xml[-2000:]}' if self.pending_xml else ''
                text = f'{xml[:12000]}{pending}'
                if len(xml) > 12000:
                    text += '\n\n……XML 已截断显示。'
        elif self.pending_xml:
            status = '存在待续写片段'
            text = self.pending_xml[-12000:]

        self.xml_status_label.configure(text=status)
        self._set_text(self.xml_text, text)
        self._refresh_validation_view(xml)

    def _refresh_validation_view(self, xml=None):
        if not hasattr(self, 'validation_text'):
            return
        xml = self._current_xml() if xml is None else str(xml or '').strip()
        if not xml:
            self.validation_status_label.configure(text='无报告')
            self._set_text(self.validation_text, '当前没有可校验的 draw.io XML。')
            return
        report = analyze_mxgraph_xml(xml)
        stats = report.get('stats') or {}
        issues = report.get('issues') or []
        if report.get('ok'):
            self.validation_status_label.configure(text='通过')
        else:
            self.validation_status_label.configure(text='存在错误')
        lines = [
            f'单元：{stats.get("cell_count", 0)}',
            f'节点：{stats.get("vertex_count", 0)}',
            f'连线：{stats.get("edge_count", 0)}',
            f'缺少几何信息：{stats.get("missing_geometry_count", 0)}',
            f'孤立节点：{stats.get("isolated_vertex_count", 0)}',
        ]
        if issues:
            lines.append('')
            lines.append('问题：')
            for item in issues:
                label = '错误' if item.get('severity') == 'error' else '警告'
                lines.append(f'- [{label}] {item.get("message", "")}')
        else:
            lines.append('')
            lines.append('未发现结构问题。')
        self._set_text(self.validation_text, '\n'.join(lines))

    def _show_validation_message(self):
        self._run_combined_validation()

    def _run_combined_validation(self):
        if self._busy:
            self.set_status('当前已有图表任务在执行', COLORS['warning'])
            return

        self._refresh_validation_view()
        xml = self._current_xml()
        if not xml:
            self._refresh_visual_validation_empty()
            messagebox.showinfo('图表校验', '当前没有可校验的 draw.io XML。', parent=self.frame)
            return

        report = analyze_mxgraph_xml(xml)
        issues = report.get('issues') or []
        structure_summary = '结构校验通过' if not issues else f'结构校验发现 {len(issues)} 个问题'

        block = self._current_block_with_caption()
        if not isinstance(block, dict):
            self.visual_validation_status_label.configure(text='无图表')
            self._set_text(self.visual_validation_text, '当前没有可执行视觉校验的图表。')
            self.set_status(f'{structure_summary}；视觉校验未执行', COLORS['warning'])
            return

        if not ensure_model_configured(self.config, self.frame, self.app_bridge):
            self.visual_validation_status_label.configure(text='未执行')
            self._set_text(self.visual_validation_text, '模型配置未完成，视觉校验未执行。')
            self.set_status(f'{structure_summary}；视觉校验未执行', COLORS['warning'])
            return

        self._start_visual_validation(block, status_prefix=structure_summary)

    def _refresh_visual_validation_empty(self):
        if not hasattr(self, 'visual_validation_text'):
            return
        if isinstance(self.current_block, dict):
            self.visual_validation_status_label.configure(text='未运行')
            self._set_text(self.visual_validation_text, '点击“校验图表”后，会使用支持图片输入的模型检查当前图表预览。')
        else:
            self.visual_validation_status_label.configure(text='无图表')
            self._set_text(self.visual_validation_text, '当前没有可校验的图表。')

    def _run_visual_validation(self):
        if self._busy:
            self.set_status('当前已有图表任务在执行', COLORS['warning'])
            return
        block = self._current_block_with_caption()
        if not isinstance(block, dict):
            messagebox.showinfo('视觉校验', '当前没有可校验的图表。', parent=self.frame)
            return
        if not ensure_model_configured(self.config, self.frame, self.app_bridge):
            return
        self._start_visual_validation(block)

    def _start_visual_validation(self, block, status_prefix=''):
        self._set_busy(True)
        self.visual_validation_status_label.configure(text='校验中')
        self._set_text(self.visual_validation_text, '正在生成图表预览并请求视觉模型校验...')

        def work():
            return validate_diagram_visual(self.api, block).as_dict()

        def on_success(result):
            self._set_busy(False)
            self._active_task_id = None
            self._show_visual_validation_result(result)
            visual_status = self._visual_validation_status_text(result)
            full_status = f'{status_prefix}；{visual_status}' if status_prefix else visual_status
            color = COLORS['error'] if result.get('error') else COLORS['warning'] if result.get('skipped') or not result.get('ok') else None
            self.set_status(full_status, color)

        def on_error(exc):
            self._set_busy(False)
            self._active_task_id = None
            result = {
                'ok': False,
                'summary': '视觉校验失败。',
                'issues': [],
                'suggestions': [],
                'skipped': False,
                'error': str(exc),
            }
            self._show_visual_validation_result(result)
            full_status = f'{status_prefix}；视觉校验失败：{exc}' if status_prefix else f'视觉校验失败：{exc}'
            self.set_status(full_status, COLORS['error'])

        self._active_task_id = self.task_runner.run(
            work=work,
            on_success=on_success,
            on_error=on_error,
            loading_text='正在校验图表视觉效果...',
            status_text='正在校验图表视觉效果...',
            status_color=COLORS['warning'],
        )

    def _refresh_knowledge_status(self):
        if not hasattr(self, 'knowledge_status_var'):
            return
        if not self.use_knowledge_var.get():
            self.knowledge_status_var.set('')
            return
        context = self.selected_knowledge_context if isinstance(self.selected_knowledge_context, dict) else {}
        docs = context.get('documents') or []
        if context.get('context_text'):
            self.knowledge_status_var.set(f'已选择 {len(docs)} 份知识库资料')
            return
        self.knowledge_status_var.set('')

    def _refresh_messages(self):
        if not self.messages:
            self._set_text(self.messages_text, '暂无对话。')
            return

        lines = []
        role_labels = {
            'user': '用户',
            'assistant': 'AI',
            'tool': '工具',
            'system': '系统',
        }
        for item in self.messages[-100:]:
            role = role_labels.get(item.get('role'), str(item.get('role') or '消息'))
            ts = str(item.get('time') or '').strip()
            header = f'[{ts}] {role}' if ts else role
            lines.append(header)
            content = str(item.get('content') or '').strip()
            if content:
                lines.append(content)
            tool_name = str(item.get('tool_name') or '').strip()
            if tool_name:
                lines.append(f'工具：{tool_name}')
            tool_output = str(item.get('tool_output') or '').strip()
            if tool_output:
                lines.append(f'结果：{tool_output[:2000]}')
            error = str(item.get('error') or '').strip()
            if error:
                lines.append(f'错误：{error}')
            lines.append('')
        self._set_text(self.messages_text, '\n'.join(lines).strip())
        try:
            self.messages_text.see(tk.END)
        except tk.TclError:
            pass

    def _set_text(self, widget, text):
        try:
            widget.configure(state=tk.NORMAL)
            widget.delete('1.0', tk.END)
            widget.insert('1.0', text or '')
            widget.configure(state=tk.DISABLED)
        except tk.TclError:
            pass

    def _set_generation_status(self, text, color=None):
        if self.generation_status_label is None:
            return
        try:
            self.generation_status_label.configure(
                text=str(text or '生成状态：空闲'),
                fg=color or COLORS['text_sub'],
            )
        except tk.TclError:
            pass

    def _append_message(self, role, content, *, tool_name='', tool_output='', error='', extra=None):
        record = {
            'id': f'msg_{int(time.time() * 1000)}_{len(self.messages)}',
            'role': role,
            'content': str(content or '').strip(),
            'tool_name': str(tool_name or '').strip(),
            'tool_output': str(tool_output or '').strip(),
            'error': str(error or '').strip(),
            'time': time.strftime('%H:%M:%S'),
        }
        if isinstance(extra, dict):
            record.update(copy.deepcopy(extra))
        self.messages.append(record)
        self.messages = self.messages[-100:]
        self._refresh_messages()
        self._schedule_workspace_state_save()

    def _send_instruction(self):
        instruction = self._current_input_text()
        self._start_instruction(instruction, clear_input=True, append_user=True, operation='AI 图表对话')

    def _start_instruction(self, instruction, *, clear_input=True, append_user=True, operation='AI 图表对话'):
        if self._busy:
            return
        instruction = str(instruction or '').strip()
        if not instruction:
            messagebox.showinfo('AI 图表', '请输入图表生成或修改指令。', parent=self.frame)
            return
        if not ensure_model_configured(self.config, self.frame, self.app_bridge):
            return
        knowledge_context = self._resolve_knowledge_context_for_generation()
        if knowledge_context is None:
            return
        if not knowledge_context:
            knowledge_context = None
        self._refresh_knowledge_status()
        self._schedule_workspace_state_save()

        self._sync_section_hint_from_paper_write()
        self._sync_current_block_caption()
        before_state = self.export_workspace_state()
        minimal_style = bool(self.minimal_style_var.get())
        auto_vlm = bool(self.auto_vlm_var.get())
        custom_system_prompt = self.custom_system_prompt_var.get()
        current_block_snapshot = copy.deepcopy(self.current_block)
        pending_xml_snapshot = self.pending_xml
        self._set_busy(True)
        if append_user:
            self._append_message(
                'user',
                self._build_user_message_content(instruction),
                extra={
                    'instruction': instruction,
                    'diagram_snapshot': before_state,
                },
            )
        if clear_input:
            self._set_input_text('')

        events = []

        def emit(event):
            if isinstance(event, dict):
                events.append(copy.deepcopy(event))
                try:
                    self.frame.after(0, lambda payload=copy.deepcopy(event): self._handle_generation_event(payload))
                except Exception:
                    pass

        def work():
            return self._run_generation_pipeline(
                instruction,
                knowledge_context=knowledge_context,
                current_block=current_block_snapshot,
                pending_xml=pending_xml_snapshot,
                minimal_style=minimal_style,
                auto_vlm=auto_vlm,
                custom_system_prompt=custom_system_prompt,
                event_callback=emit,
            )

        def on_success(payload):
            self._set_busy(False)
            self._active_task_id = None
            result = payload.get('result') if isinstance(payload, dict) else payload
            validation = payload.get('validation') if isinstance(payload, dict) else None
            self.pending_xml = result.pending_xml or ''
            if result.block:
                self._set_current_block(result.block)
            if isinstance(validation, dict):
                self._show_visual_validation_result(validation)
            self._append_message(
                'assistant',
                result.message,
                tool_name=result.tool_name,
                tool_output=result.tool_output,
                error=result.error,
            )
            if result.error:
                self.set_status(f'AI 图表操作失败：{result.error}', COLORS['error'])
                self._set_generation_status('生成状态：失败', COLORS['error'])
            else:
                self.set_status('AI 图表操作已完成')
                self._set_generation_status('生成状态：完成')
            self._save_history_snapshot(operation, input_text=instruction, output_text=result.message)

        def on_error(exc):
            self._set_busy(False)
            self._active_task_id = None
            self._append_message('assistant', 'AI 图表请求失败。', error=str(exc))
            self.set_status(f'AI 图表请求失败：{exc}', COLORS['error'])
            self._set_generation_status('生成状态：失败', COLORS['error'])

        self._active_task_id = self.task_runner.run(
            work=work,
            on_success=on_success,
            on_error=on_error,
            loading_text='正在生成图表...',
            status_text='正在生成图表...',
            status_color=COLORS['warning'],
        )

    def _resolve_knowledge_context_for_generation(self):
        if self.use_knowledge_var.get():
            context = self.selected_knowledge_context if isinstance(self.selected_knowledge_context, dict) else {}
            if context.get('context_text'):
                return copy.deepcopy(context)
            knowledge_context = self._choose_knowledge_context()
            if knowledge_context is None:
                return None
            if knowledge_context and knowledge_context.get('context_text'):
                self.selected_knowledge_context = copy.deepcopy(knowledge_context)
                return knowledge_context
            self.use_knowledge_var.set(False)
            self.selected_knowledge_context = {}
        return {}

    def _run_generation_pipeline(
        self,
        instruction,
        *,
        knowledge_context,
        current_block,
        pending_xml,
        minimal_style,
        auto_vlm,
        custom_system_prompt,
        event_callback,
    ):
        result = self.ai_service.run_instruction(
            instruction,
            current_block=current_block,
            pending_xml=pending_xml,
            knowledge_context=knowledge_context,
            minimal_style=minimal_style,
            custom_system_message=custom_system_prompt,
            event_callback=event_callback,
        )
        validation = None
        if result.block and not result.error and auto_vlm:
            result, validation = self._auto_validate_and_improve(
                instruction,
                result,
                knowledge_context=knowledge_context,
                minimal_style=minimal_style,
                custom_system_prompt=custom_system_prompt,
                event_callback=event_callback,
            )
        return {'result': result, 'validation': validation}

    def _auto_validate_and_improve(
        self,
        instruction,
        result,
        *,
        knowledge_context,
        minimal_style,
        custom_system_prompt,
        event_callback,
        max_attempts=3,
    ):
        current_result = result
        last_validation = None
        for attempt in range(1, max_attempts + 1):
            event_callback({
                'type': 'visual_validation',
                'message': f'正在执行自动视觉校验 {attempt}/{max_attempts}。',
                'data': {'attempt': attempt, 'max_attempts': max_attempts},
            })
            validation = validate_diagram_visual(self.api, current_result.block).as_dict()
            last_validation = validation
            if validation.get('skipped') or validation.get('ok'):
                return current_result, last_validation

            feedback = self._format_visual_feedback(validation, attempt, max_attempts)
            if attempt >= max_attempts:
                return current_result, last_validation

            event_callback({
                'type': 'visual_retry',
                'message': f'视觉校验发现问题，正在按建议自动优化 {attempt}/{max_attempts}。',
                'data': {'attempt': attempt, 'max_attempts': max_attempts},
            })
            improve_instruction = (
                f'{instruction}\n\n请只根据自动视觉校验建议优化当前图表布局、标签和连线，'
                f'保持原有语义和节点数量尽量稳定。'
            )
            improved = self.ai_service.run_instruction(
                improve_instruction,
                current_block=current_result.block,
                pending_xml='',
                knowledge_context=knowledge_context,
                minimal_style=minimal_style,
                custom_system_message=custom_system_prompt,
                tool_feedback=feedback,
                event_callback=event_callback,
            )
            if improved.error:
                return improved, last_validation
            if improved.block:
                current_result = improved
        return current_result, last_validation

    def _format_visual_feedback(self, validation, attempt, max_attempts):
        issues = validation.get('issues') or []
        suggestions = validation.get('suggestions') or []
        lines = [
            f'自动视觉校验未通过，需改进后重新返回工具 JSON。',
            f'校验次数：{attempt}/{max_attempts}',
            f'结论：{validation.get("summary") or "存在视觉问题"}',
        ]
        if issues:
            lines.append('问题：')
            for item in issues[:10]:
                lines.append(f'- {item.get("message", "")}')
        if suggestions:
            lines.append('建议：')
            for item in suggestions[:10]:
                lines.append(f'- {item}')
        return '\n'.join(lines)

    def _handle_generation_event(self, event):
        if not isinstance(event, dict):
            return
        event_type = str(event.get('type') or '')
        message = str(event.get('message') or '').strip()
        if message:
            self._set_generation_status(f'生成状态：{message}', COLORS['warning'])
        if event_type in {'tool_call', 'continuation', 'retry', 'shape_library', 'visual_retry'} and message:
            role = 'tool' if event_type in {'tool_call', 'shape_library'} else 'system'
            tool_name = str((event.get('data') or {}).get('tool') or '')
            self._append_message(role, message, tool_name=tool_name)

    def _show_visual_validation_result(self, result):
        if not isinstance(result, dict) or not hasattr(self, 'visual_validation_text'):
            return
        status = '失败' if result.get('error') else '已跳过' if result.get('skipped') else '通过' if result.get('ok') else '存在问题'
        self.visual_validation_status_label.configure(text=status)
        lines = [result.get('summary') or '视觉校验完成。']
        error = str(result.get('error') or '').strip()
        if error:
            lines.extend(['', f'错误：{error}'])
        issues = result.get('issues') or []
        if issues:
            lines.append('')
            lines.append('问题：')
            for item in issues:
                severity = str(item.get('severity') or 'warning')
                label = {'error': '错误', 'warning': '警告', 'info': '信息'}.get(severity, severity)
                lines.append(f'- [{label}] {item.get("message", "")}')
        suggestions = result.get('suggestions') or []
        if suggestions:
            lines.append('')
            lines.append('建议：')
            for item in suggestions:
                lines.append(f'- {item}')
        self._set_text(self.visual_validation_text, '\n'.join(lines))

    @staticmethod
    def _visual_validation_status_text(result):
        if not isinstance(result, dict):
            return '视觉校验失败'
        error = str(result.get('error') or '').strip()
        if error:
            return f'视觉校验失败：{error}'
        if result.get('skipped'):
            return result.get('summary') or '视觉校验已跳过'
        if result.get('ok'):
            return '视觉校验通过'
        return result.get('summary') or '视觉校验发现问题'

    def _build_user_message_content(self, instruction):
        return instruction

    def _open_knowledge_base_manager(self):
        if self.app_bridge and hasattr(self.app_bridge, 'show_knowledge_base'):
            try:
                self.app_bridge.show_knowledge_base()
                return
            except Exception as exc:
                messagebox.showerror('知识库', f'打开知识库管理失败：{exc}', parent=self.frame)
                return
        self.set_status('知识库管理不可用', COLORS['warning'])

    def _choose_knowledge_context(self):
        if not self.app_bridge or not hasattr(self.app_bridge, 'choose_knowledge_context'):
            return {}
        try:
            return self.app_bridge.choose_knowledge_context(
                'ai_diagram.chat',
                page_id='ai_diagram',
                action_label='AI 图表',
            )
        except Exception as exc:
            messagebox.showerror('知识库', f'选择知识库资料失败：{exc}', parent=self.frame)
            return None

    def _copy_messages(self):
        text = self._compose_messages_text()
        if not text:
            self.set_status('当前没有可复制的对话记录', COLORS['warning'])
            return
        try:
            self.frame.clipboard_clear()
            self.frame.clipboard_append(text)
        except tk.TclError as exc:
            messagebox.showerror('复制记录', str(exc), parent=self.frame)
            return
        self.set_status('AI 图表对话记录已复制')

    def _compose_messages_text(self):
        if not self.messages:
            return ''
        lines = []
        for item in self.messages[-100:]:
            role = str(item.get('role') or 'message')
            content = str(item.get('content') or '').strip()
            tool_name = str(item.get('tool_name') or '').strip()
            tool_output = str(item.get('tool_output') or '').strip()
            error = str(item.get('error') or '').strip()
            lines.append(f'[{role}]')
            if content:
                lines.append(content)
            if tool_name:
                lines.append(f'工具：{tool_name}')
            if tool_output:
                lines.append(f'结果：{tool_output}')
            if error:
                lines.append(f'错误：{error}')
            lines.append('')
        return '\n'.join(lines).strip()

    def _save_current_session(self):
        state = self.export_workspace_state()
        if not state.get('current_block') and not state.get('messages'):
            self.set_status('当前没有可保存的图表会话', COLORS['warning'])
            return
        title = self._current_caption() or simpledialog.askstring('保存会话', '会话名称：', parent=self.frame)
        if title is None:
            return
        record = save_diagram_session(self.config, state, title=title or '未命名图表会话')
        self.set_status(f'AI 图表会话已保存：{record.get("title", "")}')

    def _show_session_manager(self):
        top = self._create_manager_window('AI 图表会话', width=760, height=480)
        search_var = tk.StringVar(value='')
        records = []

        search_entry, listbox = self._build_manager_list(top, search_var)

        def refresh():
            nonlocal records
            records = list_diagram_sessions(self.config, query=search_var.get())
            listbox.delete(0, tk.END)
            for record in records:
                time_text = self._format_record_time(record.get('updated_at'))
                listbox.insert(tk.END, f'{record.get("title", "未命名图表会话")}    {time_text}    {record.get("summary", "")}')

        def selected_record():
            selection = listbox.curselection()
            if not selection:
                return None
            index = int(selection[0])
            return records[index] if 0 <= index < len(records) else None

        def restore_session():
            record = selected_record()
            if not record:
                return
            self.restore_workspace_state(record.get('state') or {})
            top.destroy()
            self.set_status(f'已恢复 AI 图表会话：{record.get("title", "")}')

        def delete_session():
            record = selected_record()
            if not record:
                return
            if not messagebox.askyesno('删除会话', f'确定删除「{record.get("title", "")}」？', parent=top):
                return
            delete_diagram_session(self.config, record.get('id'))
            refresh()

        self._build_manager_actions(top, [('恢复', restore_session), ('删除', delete_session), ('关闭', top.destroy)])
        search_var.trace_add('write', lambda *_a: refresh())
        search_entry.focus_set()
        refresh()

    def _start_mcp_service(self):
        if self.app_bridge and hasattr(self.app_bridge, 'show_mcp_services'):
            self.app_bridge.show_mcp_services()
            return
        if self._mcp_server is not None:
            url = f'http://{self._mcp_server.host}:{self._mcp_server.port}'
            self.set_status(f'MCP 图表服务已在运行：{url}')
            self._open_mcp_preview_url(url)
            return

        def on_update(_session_id, xml):
            def apply_update():
                if not xml:
                    return
                try:
                    block = diagram_block_from_xml(xml, previous_block=self.current_block, caption=self._current_caption())
                except Exception:
                    return
                if self._set_current_block(block):
                    self._append_message('system', 'MCP 工具已更新当前图表。')
            try:
                self.frame.after(0, apply_update)
            except Exception:
                pass

        try:
            from modules.diagram_mcp import DiagramMCPHTTPServer, DiagramMCPService
            service = DiagramMCPService(on_update=on_update)
            initial_xml = self._current_xml()
            service.start_session(initial_xml, notify=False)
            self._mcp_server = DiagramMCPHTTPServer(service=service, host='127.0.0.1', port=0)
            info = self._mcp_server.start()
        except Exception as exc:
            self._mcp_server = None
            messagebox.showerror('MCP 图表服务', str(exc), parent=self.frame)
            return
        self.set_status(f'MCP 图表服务已启动：{info.get("url")}')
        preview_url = ''
        try:
            preview_url = service._preview_url(service.current_session_id)
        except Exception:
            preview_url = ''
        self._append_message(
            'system',
            (
                f'MCP 图表服务已启动：{info.get("url")}，POST / 调用 '
                f'start_session/create_new_diagram/edit_diagram/get_diagram/export_diagram。'
                f'\n本地预览：{preview_url or info.get("url")}'
            ),
        )
        self._open_mcp_preview_url(preview_url or info.get('url'))

    def _open_mcp_preview_url(self, url):
        target = str(url or '').strip()
        if not target:
            return
        try:
            import webbrowser
            webbrowser.open(target)
        except Exception:
            pass

    def apply_mcp_diagram_xml(self, xml):
        xml = str(xml or '').strip()
        if not xml:
            return False
        try:
            block = diagram_block_from_xml(xml, previous_block=self.current_block, caption=self._current_caption())
        except Exception:
            return False
        if self._set_current_block(block):
            self._append_message('system', 'MCP 工具已更新当前图表。')
            self.set_status('MCP 工具已更新当前图表')
            return True
        return False

    def _create_manager_window(self, title, *, width=720, height=460):
        top = tk.Toplevel(self.frame.winfo_toplevel())
        top.title(title)
        top.configure(bg=COLORS['card_bg'])
        top.transient(self.frame.winfo_toplevel())
        top.geometry(f'{width}x{height}')
        top.minsize(520, 360)
        return top

    def _build_manager_list(self, top, search_var):
        header = tk.Frame(top, bg=COLORS['card_bg'])
        header.pack(fill=tk.X, padx=12, pady=(12, 8))
        tk.Label(header, text='搜索', font=FONTS['small'], fg=COLORS['text_sub'], bg=COLORS['card_bg']).pack(side=tk.LEFT)
        search_entry = tk.Entry(
            header,
            textvariable=search_var,
            font=FONTS['body'],
            bg=COLORS['input_bg'],
            fg=COLORS['text_main'],
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=COLORS['input_border'],
        )
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0), ipady=3)

        frame = tk.Frame(top, bg=COLORS['card_bg'], highlightthickness=1, highlightbackground=COLORS['input_border'])
        frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))
        scrollbar = tk.Scrollbar(frame, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox = tk.Listbox(
            frame,
            font=FONTS['body'],
            bg=COLORS['input_bg'],
            fg=COLORS['text_main'],
            relief=tk.FLAT,
            activestyle='dotbox',
            yscrollcommand=scrollbar.set,
        )
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=listbox.yview)
        return search_entry, listbox

    def _build_manager_actions(self, top, actions):
        footer = tk.Frame(top, bg=COLORS['card_bg'])
        footer.pack(fill=tk.X, padx=12, pady=(0, 12))
        for label, command in reversed(actions):
            button = tk.Button(
                footer,
                text=label,
                command=command,
                font=FONTS['small'],
                bg=COLORS['input_bg'],
                fg=COLORS['text_main'],
                relief=tk.FLAT,
                padx=14,
                pady=5,
                cursor='hand2',
            )
            button.pack(side=tk.RIGHT, padx=(8, 0))

    @staticmethod
    def _format_record_time(timestamp):
        try:
            value = int(timestamp or 0)
        except (TypeError, ValueError):
            value = 0
        if value <= 0:
            return ''
        return time.strftime('%Y-%m-%d %H:%M', time.localtime(value))

    def _set_busy(self, busy):
        self._busy = bool(busy)
        if busy:
            self._set_generation_status('生成状态：任务执行中', COLORS['warning'])
        try:
            if self.send_button is not None:
                self.send_button.configure(state=tk.DISABLED if busy else tk.NORMAL)
            if self.stop_button is not None:
                self.stop_button.configure(state=tk.NORMAL if busy else tk.DISABLED)
        except Exception:
            pass

    def _stop_generation(self):
        if not self._busy or not self._active_task_id:
            self.set_status('当前没有正在执行的图表任务', COLORS['warning'])
            return
        cancelled = self.task_runner.cancel(self._active_task_id)
        self._active_task_id = None
        self._set_busy(False)
        if cancelled:
            self._append_message('system', '已请求停止当前图表生成。')
            self.set_status('已请求停止当前图表生成')
            self._set_generation_status('生成状态：已请求停止', COLORS['warning'])
        else:
            self.set_status('当前图表任务无法停止', COLORS['warning'])

    def _set_current_block(self, block):
        sanitized = sanitize_diagram_block(block)
        if not sanitized:
            return False
        caption = self._current_caption()
        if caption:
            caption_changed = str(sanitized.get('caption') or '').strip() != caption
            sanitized['caption'] = caption
            if caption_changed:
                sanitized.pop('thumbnail_b64', None)
                sanitized.pop('thumbnail_path', None)
        elif self.session_title_var.get().strip() in {'', '未命名图表会话'}:
            caption = sanitized.get('caption') or sanitized.get('diagram_id') or ''
            if caption:
                self.session_title_var.set(str(caption)[:80])
        if not sanitized.get('thumbnail_b64') and not sanitized.get('thumbnail_path'):
            thumb_b64, thumb_path = render_placeholder_b64(
                sanitized.get('json_graph') or {},
                caption=sanitized.get('caption') or '',
            )
            if thumb_b64:
                sanitized['thumbnail_b64'] = thumb_b64
            if thumb_path:
                sanitized['thumbnail_path'] = thumb_path
        self.current_block = sanitized
        self._refresh_preview()
        self._refresh_xml_view()
        self._schedule_workspace_state_save()
        return True

    def _open_editor(self):
        self._sync_current_block_caption()
        if not isinstance(self.current_block, dict):
            messagebox.showinfo('AI 图表', '请先生成图表后再打开编辑器。', parent=self.frame)
            return

        try:
            from pages.diagram_editor_dialog import open_diagram_editor
        except Exception as exc:
            messagebox.showerror('AI 图表', f'图表编辑器加载失败：{exc}', parent=self.frame)
            return

        def on_save(new_block):
            if self._set_current_block(self._merge_editor_history(new_block)):
                self._append_message('system', '图表已通过编辑器更新。')
                self._save_history_snapshot('编辑图表', output_text=diagram_placeholder_text(self.current_block))
                self.set_status('图表已更新')

        open_diagram_editor(
            self.frame,
            self.current_block,
            on_save=on_save,
            api_client=self.api,
            task_runner=self.task_runner,
            prefer_webview=True,
        )

    def _merge_editor_history(self, new_block):
        if not isinstance(new_block, dict) or not isinstance(self.current_block, dict):
            return new_block
        old_xml = str(self.current_block.get('mxgraph_xml') or '').strip()
        new_xml = str(new_block.get('mxgraph_xml') or '').strip()
        if not old_xml or old_xml == new_xml:
            return new_block
        merged = copy.deepcopy(new_block)
        history = list(merged.get('history') or self.current_block.get('history') or [])
        if not history or str(history[-1].get('mxgraph_xml') or '').strip() != old_xml:
            snapshot = {
                'mxgraph_xml': old_xml,
                'updated_at': self.current_block.get('updated_at', 0),
                'caption': self.current_block.get('caption', ''),
            }
            if self.current_block.get('thumbnail_b64'):
                snapshot['thumbnail_b64'] = self.current_block.get('thumbnail_b64')
            if self.current_block.get('thumbnail_path'):
                snapshot['thumbnail_path'] = self.current_block.get('thumbnail_path')
            history.append(snapshot)
        merged['history'] = history
        return merged

    def _insert_to_paper_write(self):
        self._sync_section_hint_from_paper_write()
        self._sync_current_block_caption()
        if not isinstance(self.current_block, dict):
            messagebox.showinfo('AI 图表', '当前没有可插入的图表。', parent=self.frame)
            return
        if not self.app_bridge or not hasattr(self.app_bridge, 'apply_diagram_to_paper_write'):
            messagebox.showwarning('AI 图表', '论文写作页桥接不可用。', parent=self.frame)
            return
        outcome = self.app_bridge.apply_diagram_to_paper_write(
            copy.deepcopy(self.current_block),
            section_hint=self.section_hint_var.get().strip(),
        )
        if outcome and outcome.get('ok'):
            section = outcome.get('section') or self.section_hint_var.get().strip()
            self.set_status(f'图表已插入论文正文：{section}')
            self._append_message('system', f'图表已插入论文正文：{section}')
            self._save_history_snapshot('插入论文正文', output_text=diagram_placeholder_text(self.current_block))
        else:
            message = (outcome or {}).get('message') or '图表插入失败。'
            self.set_status(message, COLORS['error'])
            messagebox.showwarning('AI 图表', message, parent=self.frame)

    def _save_manual_snapshot(self):
        self._sync_current_block_caption()
        if not isinstance(self.current_block, dict):
            self.set_status('当前没有可保存的图表快照', COLORS['warning'])
            return
        record_id = self._save_history_snapshot('保存图表快照', output_text=self._current_summary_text())
        if record_id:
            self.set_status(f'图表快照已保存：#{record_id}')
        else:
            self.set_status('当前没有可保存的图表快照', COLORS['warning'])

    def _save_history_snapshot(self, operation, input_text='', output_text=''):
        if self.history is None or not hasattr(self.history, 'add'):
            return None
        if not isinstance(self.current_block, dict) and not self.messages:
            return None
        self._sync_current_block_caption()
        state = self.capture_workspace_state_snapshot(save_to_disk=True)
        title = self._current_caption() or 'AI 图表'
        try:
            record_id = self.history.add(
                operation=operation,
                input_text=input_text or title,
                output_text=output_text or self._current_summary_text(),
                module=MODULE_AI_DIAGRAM,
                extra={
                    'session_title': title,
                    'diagram_id': (self.current_block or {}).get('diagram_id', '') if isinstance(self.current_block, dict) else '',
                },
                page_state_id=self.PAGE_STATE_ID,
                workspace_state=state,
            )
        except Exception:
            return None
        return record_id

    def _current_summary_text(self):
        block = self._current_block_with_caption()
        if not isinstance(block, dict):
            return '暂无图表'
        caption = block.get('caption') or block.get('diagram_id') or '图表'
        xml = self._current_xml()
        if not xml:
            return diagram_placeholder_text(block)
        try:
            stats = validate_mxgraph_xml(xml)
        except DiagramToolError:
            return f'{caption}\nXML 校验失败'
        return (
            f'{caption}\n'
            f'单元：{stats.get("cell_count", 0)}，节点：{stats.get("vertex_count", 0)}，连线：{stats.get("edge_count", 0)}'
        )

    def _restore_previous_version(self):
        block = self.current_block if isinstance(self.current_block, dict) else None
        history = list((block or {}).get('history') or [])
        if not history:
            messagebox.showinfo('AI 图表', '当前图表没有上一版快照。', parent=self.frame)
            return
        snapshot = history.pop()
        xml = str(snapshot.get('mxgraph_xml') or '').strip()
        if not xml:
            messagebox.showwarning('AI 图表', '上一版快照缺少 mxGraph XML。', parent=self.frame)
            return
        restored = dict(block)
        restored['mxgraph_xml'] = xml
        restored['json_graph'] = mxgraph_xml_to_json(xml)
        restored['history'] = history
        restored['updated_at'] = int(time.time())
        restored.pop('thumbnail_b64', None)
        restored.pop('thumbnail_path', None)
        if self._set_current_block(restored):
            self._append_message('system', '图表已恢复上一版。')
            self._save_history_snapshot('恢复上一版', output_text=self._current_summary_text())
            self.set_status('图表已恢复上一版')

    def _show_version_history(self):
        block = self.current_block if isinstance(self.current_block, dict) else None
        history = list((block or {}).get('history') or [])
        if not block or not history:
            messagebox.showinfo('版本历史', '当前图表没有可恢复的历史版本。', parent=self.frame)
            return
        top = self._create_manager_window('图表版本历史', width=760, height=480)
        search_var = tk.StringVar(value='')
        records = []
        search_entry, listbox = self._build_manager_list(top, search_var)

        def version_label(snapshot, version_no):
            xml = str(snapshot.get('mxgraph_xml') or '').strip()
            time_text = self._format_record_time(snapshot.get('updated_at'))
            caption = str(snapshot.get('caption') or block.get('caption') or '图表版本').strip()
            try:
                stats = validate_mxgraph_xml(xml)
                stat_text = f'节点 {stats.get("vertex_count", 0)} / 连线 {stats.get("edge_count", 0)}'
            except Exception:
                stat_text = 'XML 校验失败'
            return f'版本 {version_no}    {caption}    {time_text}    {stat_text}'

        def refresh():
            nonlocal records
            needle = search_var.get().strip().lower()
            records = []
            listbox.delete(0, tk.END)
            for offset, snapshot in enumerate(reversed(history), start=1):
                version_no = len(history) - offset + 1
                label = version_label(snapshot, version_no)
                if needle and needle not in label.lower():
                    continue
                records.append((version_no - 1, snapshot))
                listbox.insert(tk.END, label)

        def selected():
            selection = listbox.curselection()
            if not selection:
                return None
            index = int(selection[0])
            return records[index] if 0 <= index < len(records) else None

        def restore_selected():
            selected_item = selected()
            if not selected_item:
                return
            hist_index, snapshot = selected_item
            xml = str(snapshot.get('mxgraph_xml') or '').strip()
            if not xml:
                messagebox.showwarning('版本历史', '所选版本缺少 mxGraph XML。', parent=top)
                return
            restored = dict(block)
            restored['mxgraph_xml'] = xml
            restored['json_graph'] = mxgraph_xml_to_json(xml)
            restored['history'] = history[:hist_index]
            restored['updated_at'] = int(time.time())
            if snapshot.get('thumbnail_b64'):
                restored['thumbnail_b64'] = snapshot.get('thumbnail_b64')
            else:
                restored.pop('thumbnail_b64', None)
            if snapshot.get('thumbnail_path'):
                restored['thumbnail_path'] = snapshot.get('thumbnail_path')
            else:
                restored.pop('thumbnail_path', None)
            if self._set_current_block(restored):
                top.destroy()
                self._append_message('system', f'图表已恢复到历史版本 {hist_index + 1}。')
                self._save_history_snapshot('恢复历史版本', output_text=self._current_summary_text())
                self.set_status(f'图表已恢复到历史版本 {hist_index + 1}')

        self._build_manager_actions(top, [('恢复', restore_selected), ('关闭', top.destroy)])
        search_var.trace_add('write', lambda *_a: refresh())
        search_entry.focus_set()
        refresh()

    def _export_drawio(self):
        xml = self._current_xml()
        if not xml:
            messagebox.showinfo('AI 图表', '当前没有可导出的 draw.io XML。', parent=self.frame)
            return
        try:
            validate_mxgraph_xml(xml)
        except DiagramToolError as exc:
            if not messagebox.askyesno(
                '导出 .drawio',
                f'XML 校验失败：\n{exc}\n\n是否仍然导出？',
                parent=self.frame,
            ):
                return

        title = self.session_title_var.get().strip() or 'diagram'
        filename = safe_diagram_filename(title)
        path = filedialog.asksaveasfilename(
            parent=self.frame,
            title='导出图表',
            defaultextension='.drawio',
            initialfile=f'{filename}.drawio',
            filetypes=[
                ('draw.io 文件', '*.drawio'),
                ('XML 文件', '*.xml'),
                ('PNG 预览', '*.png'),
                ('SVG 预览', '*.svg'),
                ('draw.io SVG', '*.drawio.svg'),
                ('所有文件', '*.*'),
            ],
        )
        if not path:
            return
        try:
            result = export_diagram_file(
                path,
                xml,
                block=self._current_block_with_caption(),
                native_exporter=self._export_via_webview,
            )
        except (OSError, DiagramExportError) as exc:
            messagebox.showerror('导出图表', str(exc), parent=self.frame)
            return
        self.set_status(f'{result.get("note", "图表已导出")}：{path}')

    def _export_via_webview(self, export_format):
        block = self._current_block_with_caption()
        if not isinstance(block, dict):
            return None
        try:
            from modules.diagram_webview import export_diagram_in_webview
            return export_diagram_in_webview(block, export_format)
        except Exception:
            return None

    def _new_session(self):
        if self.current_block or self.messages:
            if not messagebox.askyesno('新建会话', '当前会话尚未清空，是否新建空白会话？', parent=self.frame):
                return
        self.session_title_var.set('')
        self.section_hint_var.set('')
        self._sync_section_hint_from_paper_write()
        self.current_block = None
        self.pending_xml = ''
        self.messages = []
        self.use_knowledge_var.set(False)
        self.selected_knowledge_context = {}
        self._set_input_text('', schedule=False)
        self._refresh_preview()
        self._refresh_xml_view()
        self._refresh_messages()
        self._refresh_knowledge_status()
        self._schedule_workspace_state_save()
        self.set_status('已新建 AI 图表会话')

    def _clear_messages(self):
        self.messages = []
        self._refresh_messages()
        self._schedule_workspace_state_save()
