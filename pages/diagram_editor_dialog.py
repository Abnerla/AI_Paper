# -*- coding: utf-8 -*-
"""
图表编辑弹窗。

优先使用 pywebview 承接本地 draw.io / Mermaid 编辑；环境不满足时降级为
Tk Mermaid 文本编辑器。对外接口（open_diagram_editor）保持稳定。
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None

from modules.diagram_blocks import (
    DIAGRAM_KIND_DEFAULT,
    new_diagram_block,
    sanitize_diagram_block,
)
from modules.diagram_format import (
    detect_diagram_kind, detect_layout, json_to_mermaid, mermaid_to_json,
)
from modules.diagram_generator import apply_patch, patch_from_ai
from modules.diagram_thumbnail import render_placeholder_b64, render_placeholder_png
from modules.ui_components import COLORS, FONTS, THEMES


DIAGRAM_KIND_OPTIONS = [
    ('flowchart', '流程图 flowchart'),
    ('sequence', '时序图 sequence'),
    ('classDiagram', '类图 classDiagram'),
    ('stateDiagram', '状态图 stateDiagram'),
    ('erDiagram', 'ER 图 erDiagram'),
    ('mindmap', '思维导图 mindmap'),
    ('gantt', '甘特图 gantt'),
    ('journey', '用户旅程 journey'),
    ('pie', '饼图 pie'),
    ('quadrant', '象限图 quadrant'),
    ('timeline', '时间线 timeline'),
    ('c4', 'C4 架构图 c4'),
    ('freeform', '自由形式 freeform'),
]


def open_diagram_editor(parent_frame, block, *, on_save,
                        api_client=None, task_runner=None, skills_runtime=None,
                        prefer_webview=True):
    """打开图表编辑弹窗（阻塞调用）。on_save 收到合并后的新 block。

    传入 api_client / task_runner 后右侧出现 AI 对话区，支持自然语言增量改图。
    传入 skills_runtime 后顶部出现"插入模板"下拉，聚合所有启用 Skill 提供的图表模板。
    prefer_webview=True 且 webview 环境就绪时，优先开 pywebview 子进程编辑窗；
    否则降级到 Tk 文本编辑器。
    """
    if not isinstance(block, dict):
        return

    if prefer_webview:
        try:
            from modules.diagram_webview import (
                is_webview_supported,
                open_diagram_in_webview,
            )
            if is_webview_supported():
                result = open_diagram_in_webview(block)
                if isinstance(result, dict):
                    try:
                        on_save(result)
                    except Exception:
                        pass
                return
        except Exception:
            # 子进程方式异常则降级到 Tk dialog
            pass

    dialog = _DiagramEditorDialog(parent_frame, block, on_save,
                                  api_client=api_client, task_runner=task_runner,
                                  skills_runtime=skills_runtime)
    dialog.show()


class _DiagramEditorDialog:
    PREVIEW_W = 520
    PREVIEW_H = 360

    def __init__(self, parent_frame, block, on_save, *,
                 api_client=None, task_runner=None, skills_runtime=None):
        self._parent_frame = parent_frame
        self._block = dict(block)
        self._on_save = on_save
        self._api_client = api_client
        self._task_runner = task_runner
        self._skills_runtime = skills_runtime
        self._dirty = False
        self._refresh_after_id = None
        self._photo = None
        self._top = None
        self._ai_busy = False
        self._templates_cache = None

    def show(self):
        top = tk.Toplevel(self._parent_frame.winfo_toplevel())
        self._top = top
        top.title(f"编辑图表 - {self._block.get('caption') or self._block.get('diagram_id', '')}")
        top.configure(bg=COLORS.get('card_bg', '#FFFFFF'))
        top.transient(self._parent_frame.winfo_toplevel())
        top.grab_set()
        top.protocol('WM_DELETE_WINDOW', self._handle_close)
        top.bind('<Escape>', lambda _e: self._handle_close())

        self._build_header(top)
        body = tk.Frame(top, bg=COLORS.get('card_bg', '#FFFFFF'))
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))
        body.grid_columnconfigure(0, weight=1, uniform='diag_body')
        body.grid_columnconfigure(1, weight=1, uniform='diag_body')
        body.grid_rowconfigure(0, weight=3)
        if self._ai_available():
            body.grid_rowconfigure(1, weight=2)

        self._build_text_panel(body)
        self._build_preview_panel(body)
        if self._ai_available():
            self._build_ai_panel(body)
        self._build_footer(top)

        self._render_preview()
        top.update_idletasks()
        top.minsize(880, 540)
        try:
            top.wait_window()
        except tk.TclError:
            pass

    def _build_header(self, top):
        header = tk.Frame(top, bg=COLORS.get('card_bg', '#FFFFFF'))
        header.pack(fill=tk.X, padx=12, pady=(12, 8))

        tk.Label(
            header, text='标题', font=FONTS['small'],
            fg=COLORS.get('text_sub', '#666'),
            bg=COLORS.get('card_bg', '#FFFFFF'),
        ).pack(side=tk.LEFT)

        self._caption_var = tk.StringVar(value=self._block.get('caption', ''))
        caption_entry = tk.Entry(
            header, textvariable=self._caption_var,
            font=FONTS['body'],
            bg=COLORS.get('input_bg', '#FFF'),
            fg=COLORS.get('text_main', '#222'),
            relief=tk.FLAT, highlightthickness=1,
            highlightbackground=COLORS.get('input_border', '#CCC'),
        )
        caption_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 16), ipady=3)
        caption_entry.bind('<KeyRelease>', lambda _e: self._mark_dirty())

        tk.Label(
            header, text='类型', font=FONTS['small'],
            fg=COLORS.get('text_sub', '#666'),
            bg=COLORS.get('card_bg', '#FFFFFF'),
        ).pack(side=tk.LEFT)

        current_kind = self._block.get('diagram_kind') or DIAGRAM_KIND_DEFAULT
        kind_labels = [label for _key, label in DIAGRAM_KIND_OPTIONS]
        kind_map = {label: key for key, label in DIAGRAM_KIND_OPTIONS}
        current_label = next(
            (label for key, label in DIAGRAM_KIND_OPTIONS if key == current_kind),
            DIAGRAM_KIND_OPTIONS[0][1],
        )
        self._kind_var = tk.StringVar(value=current_label)
        self._kind_map = kind_map
        kind_menu = tk.OptionMenu(header, self._kind_var, *kind_labels)
        kind_menu.configure(
            font=FONTS['small'],
            bg=COLORS.get('input_bg', '#FFF'),
            fg=COLORS.get('text_main', '#222'),
            activebackground=COLORS.get('input_bg', '#FFF'),
            relief=tk.FLAT, highlightthickness=1,
            highlightbackground=COLORS.get('input_border', '#CCC'),
        )
        kind_menu.pack(side=tk.LEFT, padx=(6, 0))
        self._kind_var.trace_add('write', lambda *_a: self._on_kind_changed())

        if self._skills_runtime is not None:
            tpl_btn = tk.Button(
                header, text='插入模板',
                command=self._show_template_menu,
                font=FONTS['small'],
                bg=COLORS.get('input_bg', '#FFF'),
                fg=COLORS.get('text_main', '#222'),
                activebackground=COLORS.get('input_bg', '#FFF'),
                relief=tk.FLAT, padx=10, pady=2, cursor='hand2',
                highlightthickness=1,
                highlightbackground=COLORS.get('input_border', '#CCC'),
            )
            tpl_btn.pack(side=tk.LEFT, padx=(8, 0))
            self._template_button = tpl_btn

    def _show_template_menu(self):
        kind = self._current_kind()
        try:
            templates = self._skills_runtime.collect_diagram_templates(diagram_kind=kind)
        except Exception as exc:
            messagebox.showerror('模板', f'加载模板失败：{exc}', parent=self._top)
            return
        if not templates:
            try:
                templates = self._skills_runtime.collect_diagram_templates(diagram_kind='')
            except Exception:
                templates = []
        if not templates:
            messagebox.showinfo(
                '模板',
                '暂无匹配的模板。请先到「发现技能」安装并启用「图表模板库」或第三方图表 Skill。',
                parent=self._top,
            )
            return

        menu = tk.Menu(self._top, tearoff=False)
        for template in templates:
            label_text = template.get('name') or template.get('id') or '未命名模板'
            kind_tag = template.get('diagram_kind') or ''
            display = f'{label_text}    [{kind_tag}]' if kind_tag else label_text
            menu.add_command(label=display, command=lambda t=template: self._apply_template(t))
        try:
            x = self._template_button.winfo_rootx()
            y = self._template_button.winfo_rooty() + self._template_button.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _apply_template(self, template):
        if not isinstance(template, dict):
            return
        mermaid_text = template.get('mermaid') or ''
        caption = template.get('caption') or template.get('name') or ''
        new_kind = template.get('diagram_kind') or self._current_kind()

        if self._dirty and self._text.get('1.0', 'end-1c').strip():
            answer = messagebox.askokcancel(
                '插入模板',
                '当前内容尚未保存，模板会覆盖现有 Mermaid 源代码。是否继续？',
                parent=self._top,
            )
            if not answer:
                return

        self._text.delete('1.0', tk.END)
        if mermaid_text:
            self._text.insert('1.0', mermaid_text)
        if caption:
            self._caption_var.set(caption)
        new_label = next(
            (label for key, label in DIAGRAM_KIND_OPTIONS if key == new_kind),
            None,
        )
        if new_label:
            self._kind_var.set(new_label)
        self._mark_dirty()
        self._render_preview()

    def _build_text_panel(self, body):
        panel = tk.Frame(body, bg=COLORS.get('card_bg', '#FFFFFF'))
        panel.grid(row=0, column=0, sticky='nsew', padx=(0, 6))

        tk.Label(
            panel, text='Mermaid 源代码',
            font=FONTS.get('body_bold', FONTS['body']),
            fg=COLORS.get('text_main', '#222'),
            bg=COLORS.get('card_bg', '#FFFFFF'),
        ).pack(anchor='w')

        text_frame = tk.Frame(
            panel,
            bg=COLORS.get('card_bg', '#FFFFFF'),
            highlightthickness=1,
            highlightbackground=COLORS.get('input_border', '#CCC'),
        )
        text_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        mono_font = tkfont.Font(family='Consolas', size=11)
        scrollbar = tk.Scrollbar(text_frame, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._text = tk.Text(
            text_frame,
            font=mono_font,
            bg=COLORS.get('input_bg', '#FFF'),
            fg=COLORS.get('text_main', '#222'),
            relief=tk.FLAT,
            wrap=tk.NONE,
            undo=True,
            yscrollcommand=scrollbar.set,
        )
        self._text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self._text.yview)

        self._text.insert('1.0', self._block.get('mermaid', '') or '')
        self._text.bind('<KeyRelease>', self._on_text_changed)

        hint = tk.Label(
            panel,
            text='示例: flowchart TB\n    A["开始"] --> B["处理"] --> C["结束"]',
            font=FONTS['small'],
            fg=COLORS.get('text_sub', '#666'),
            bg=COLORS.get('card_bg', '#FFFFFF'),
            justify=tk.LEFT,
        )
        hint.pack(anchor='w', pady=(4, 0))

    def _build_preview_panel(self, body):
        panel = tk.Frame(body, bg=COLORS.get('card_bg', '#FFFFFF'))
        panel.grid(row=0, column=1, sticky='nsew', padx=(6, 0))

        tk.Label(
            panel, text='预览（节点级示意图）',
            font=FONTS.get('body_bold', FONTS['body']),
            fg=COLORS.get('text_main', '#222'),
            bg=COLORS.get('card_bg', '#FFFFFF'),
        ).pack(anchor='w')

        canvas_frame = tk.Frame(
            panel,
            bg=COLORS.get('card_bg', '#FFFFFF'),
            highlightthickness=1,
            highlightbackground=COLORS.get('input_border', '#CCC'),
        )
        canvas_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        self._canvas = tk.Canvas(
            canvas_frame,
            width=self.PREVIEW_W,
            height=self.PREVIEW_H,
            bg='#FAFAFA',
            highlightthickness=0,
        )
        self._canvas.pack(fill=tk.BOTH, expand=True)

        self._status_label = tk.Label(
            panel,
            text='准备预览',
            font=FONTS['small'],
            fg=COLORS.get('text_sub', '#666'),
            bg=COLORS.get('card_bg', '#FFFFFF'),
            anchor='w',
        )
        self._status_label.pack(fill=tk.X, pady=(4, 0))

    def _ai_available(self):
        return self._api_client is not None and self._task_runner is not None

    def _build_ai_panel(self, body):
        panel = tk.Frame(body, bg=COLORS.get('card_bg', '#FFFFFF'))
        panel.grid(row=1, column=0, columnspan=2, sticky='nsew', pady=(8, 0))

        header = tk.Frame(panel, bg=COLORS.get('card_bg', '#FFFFFF'))
        header.pack(fill=tk.X)
        tk.Label(
            header, text='AI 对话改图',
            font=FONTS.get('body_bold', FONTS['body']),
            fg=COLORS.get('text_main', '#222'),
            bg=COLORS.get('card_bg', '#FFFFFF'),
        ).pack(side=tk.LEFT)
        self._ai_status_label = tk.Label(
            header, text='输入指令后回车或点「应用」让 AI 增量修改当前图。',
            font=FONTS['small'],
            fg=COLORS.get('text_sub', '#666'),
            bg=COLORS.get('card_bg', '#FFFFFF'),
        )
        self._ai_status_label.pack(side=tk.LEFT, padx=(8, 0))

        body_frame = tk.Frame(panel, bg=COLORS.get('card_bg', '#FFFFFF'))
        body_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        body_frame.grid_columnconfigure(0, weight=1)
        body_frame.grid_columnconfigure(1, weight=0)
        body_frame.grid_rowconfigure(0, weight=1)

        instr_frame = tk.Frame(
            body_frame,
            bg=COLORS.get('card_bg', '#FFFFFF'),
            highlightthickness=1,
            highlightbackground=COLORS.get('input_border', '#CCC'),
        )
        instr_frame.grid(row=0, column=0, sticky='nsew')

        self._ai_instruction = tk.Text(
            instr_frame,
            height=4, wrap=tk.WORD,
            font=FONTS['body'],
            bg=COLORS.get('input_bg', '#FFF'),
            fg=COLORS.get('text_main', '#222'),
            relief=tk.FLAT, undo=True,
        )
        self._ai_instruction.pack(fill=tk.BOTH, expand=True)
        self._ai_instruction.bind('<Control-Return>', lambda _e: self._handle_ai_apply())

        button_col = tk.Frame(body_frame, bg=COLORS.get('card_bg', '#FFFFFF'))
        button_col.grid(row=0, column=1, sticky='ns', padx=(8, 0))
        self._ai_apply_btn = tk.Button(
            button_col, text='应用 (Ctrl+Enter)',
            command=self._handle_ai_apply,
            font=FONTS.get('body_bold', FONTS['body']),
            bg=COLORS.get('primary', '#1976D2'), fg='#FFFFFF',
            activebackground=COLORS.get('primary', '#1976D2'),
            relief=tk.FLAT, padx=14, pady=6, cursor='hand2',
        )
        self._ai_apply_btn.pack(fill=tk.X)
        tk.Button(
            button_col, text='清空',
            command=lambda: self._ai_instruction.delete('1.0', tk.END),
            font=FONTS['small'],
            bg=COLORS.get('card_bg', '#FFFFFF'),
            fg=COLORS.get('text_sub', '#666'),
            relief=tk.FLAT, padx=12, pady=4, cursor='hand2',
        ).pack(fill=tk.X, pady=(6, 0))

        hint = tk.Label(
            panel,
            text='示例：把"处理"换成"AI 推理"；在结束前加一个"输出报告"节点；把流向改成 LR。',
            font=FONTS['small'],
            fg=COLORS.get('text_sub', '#666'),
            bg=COLORS.get('card_bg', '#FFFFFF'),
            justify=tk.LEFT,
            anchor='w',
        )
        hint.pack(fill=tk.X, pady=(4, 0))

    def _build_footer(self, top):
        footer = tk.Frame(top, bg=COLORS.get('card_bg', '#FFFFFF'))
        footer.pack(fill=tk.X, padx=12, pady=(4, 12))

        tk.Button(
            footer, text='保存', command=self._handle_save,
            font=FONTS.get('body_bold', FONTS['body']),
            bg=COLORS.get('primary', '#1976D2'), fg='#FFFFFF',
            activebackground=COLORS.get('primary', '#1976D2'),
            relief=tk.FLAT, padx=18, pady=6, cursor='hand2',
        ).pack(side=tk.RIGHT)
        tk.Button(
            footer, text='取消', command=self._handle_close,
            font=FONTS['small'],
            bg=COLORS.get('card_bg', '#FFFFFF'),
            fg=COLORS.get('text_sub', '#666'),
            relief=tk.FLAT, padx=14, pady=6, cursor='hand2',
        ).pack(side=tk.RIGHT, padx=(0, 8))

        tk.Label(
            footer,
            text='提示：当前环境不可用时会降级为 Mermaid 源码编辑；draw.io 编辑结果会在保存后回写。',
            font=FONTS['small'],
            fg=COLORS.get('text_sub', '#666'),
            bg=COLORS.get('card_bg', '#FFFFFF'),
        ).pack(side=tk.LEFT)

    def _mark_dirty(self):
        self._dirty = True

    def _on_text_changed(self, _event=None):
        self._mark_dirty()
        self._schedule_refresh()

    def _on_kind_changed(self):
        self._mark_dirty()
        self._schedule_refresh()

    def _schedule_refresh(self):
        if self._refresh_after_id is not None:
            try:
                self._top.after_cancel(self._refresh_after_id)
            except Exception:
                pass
        self._refresh_after_id = self._top.after(250, self._render_preview)

    def _current_kind(self):
        label = self._kind_var.get()
        return self._kind_map.get(label, DIAGRAM_KIND_DEFAULT)

    def _render_preview(self):
        self._refresh_after_id = None
        if Image is None:
            self._status_label.config(text='缺少 Pillow，无法预览')
            return
        mermaid_text = self._text.get('1.0', 'end-1c').strip()
        kind = self._current_kind()
        if not mermaid_text:
            self._photo = None
            self._canvas.delete('all')
            self._canvas.create_text(
                self.PREVIEW_W / 2, self.PREVIEW_H / 2,
                text='请输入 Mermaid 源代码',
                font=FONTS['small'], fill='#9E9E9E',
            )
            self._status_label.config(text='空内容')
            return

        graph = mermaid_to_json(mermaid_text)
        node_count = len(graph.get('nodes') or [])
        edge_count = len(graph.get('edges') or [])

        image = render_placeholder_png(
            graph,
            caption=self._caption_var.get().strip(),
            size=(self.PREVIEW_W, self.PREVIEW_H),
        )
        self._canvas.delete('all')
        if image is None:
            self._canvas.create_text(
                self.PREVIEW_W / 2, self.PREVIEW_H / 2,
                text='预览失败', font=FONTS['small'], fill='#C62828',
            )
            self._status_label.config(text='渲染失败')
            return

        self._photo = ImageTk.PhotoImage(image)
        self._canvas.create_image(self.PREVIEW_W / 2, self.PREVIEW_H / 2, image=self._photo)
        detected = detect_diagram_kind(mermaid_text) or kind
        if detected != kind and detected:
            self._status_label.config(
                text=f'识别为 {detected}（与所选类型不一致，将以源码内容为准），节点 {node_count}/边 {edge_count}'
            )
        else:
            self._status_label.config(text=f'节点 {node_count}，边 {edge_count}')

    def _handle_close(self):
        if self._dirty:
            answer = messagebox.askokcancel(
                '未保存', '当前修改尚未保存，确定要关闭吗？',
                parent=self._top,
            )
            if not answer:
                return
        try:
            self._top.destroy()
        except Exception:
            pass

    def _handle_save(self):
        mermaid_text = self._text.get('1.0', 'end-1c').strip()
        caption = self._caption_var.get().strip()
        kind = self._current_kind()
        if not mermaid_text:
            messagebox.showwarning('提示', '请输入 Mermaid 源代码', parent=self._top)
            return

        graph = mermaid_to_json(mermaid_text)
        meta = graph.setdefault('meta', {})
        if 'layout' not in meta:
            meta['layout'] = detect_layout(mermaid_text)
        if not graph.get('nodes') and kind in ('flowchart',):
            answer = messagebox.askokcancel(
                '解析提示',
                '当前 Mermaid 源代码无法被本地解析为节点列表，缩略图将退化为占位提示。\n是否仍要保存？',
                parent=self._top,
            )
            if not answer:
                return

        new_block = new_diagram_block(
            diagram_id=self._block.get('diagram_id'),
            diagram_kind=kind,
            authoring_format='mermaid',
            mermaid=mermaid_text,
            json_graph=graph,
            caption=caption,
            display_size=self._block.get('display_size'),
            history=self._block.get('history') or [],
        )
        new_block = sanitize_diagram_block(new_block) or new_block

        thumb_b64, thumb_path = render_placeholder_b64(
            new_block.get('json_graph') or {}, caption=caption,
        )
        if thumb_b64:
            new_block['thumbnail_b64'] = thumb_b64
        if thumb_path:
            new_block['thumbnail_path'] = thumb_path

        try:
            self._on_save(new_block)
        except Exception as exc:
            messagebox.showerror('保存失败', str(exc), parent=self._top)
            return
        self._dirty = False
        try:
            self._top.destroy()
        except Exception:
            pass

    def _handle_ai_apply(self):
        if not self._ai_available():
            return
        if self._ai_busy:
            return
        instruction = self._ai_instruction.get('1.0', 'end-1c').strip()
        if not instruction:
            messagebox.showinfo('提示', '请输入修改指令', parent=self._top)
            return

        mermaid_text = self._text.get('1.0', 'end-1c').strip()
        current_graph = mermaid_to_json(mermaid_text) if mermaid_text else {
            'nodes': [], 'edges': [], 'groups': [], 'meta': {}
        }
        if not current_graph.get('nodes'):
            answer = messagebox.askokcancel(
                'AI 改图',
                '当前 Mermaid 源代码未能解析出节点，AI 将在空图上构造。继续？',
                parent=self._top,
            )
            if not answer:
                return

        api_client = self._api_client
        kind = self._current_kind()
        self._set_ai_busy(True, '正在请求 AI...')

        def work():
            ops = patch_from_ai(api_client, instruction, current_graph)
            new_graph, new_caption = apply_patch(current_graph, ops)
            new_graph.setdefault('meta', {})
            if 'layout' not in new_graph['meta']:
                new_graph['meta']['layout'] = current_graph.get('meta', {}).get('layout', 'TB')
            return {
                'ops': ops,
                'graph': new_graph,
                'caption': new_caption,
            }

        def on_success(result):
            self._set_ai_busy(False, '')
            ops = result.get('ops') or []
            new_graph = result.get('graph') or {}
            new_caption = result.get('caption')
            if not ops:
                self._ai_status_label.config(text='AI 返回为空，未做改动。')
                return
            new_mermaid = json_to_mermaid(new_graph, diagram_kind=kind) or mermaid_text
            self._text.delete('1.0', tk.END)
            self._text.insert('1.0', new_mermaid)
            if new_caption is not None:
                self._caption_var.set(new_caption)
            self._mark_dirty()
            self._render_preview()
            self._ai_status_label.config(text=f'已应用 {len(ops)} 个修改，可继续保存。')

        def on_error(exc):
            self._set_ai_busy(False, f'AI 调用失败：{exc}')

        self._task_runner.run(
            work=work,
            on_success=on_success,
            on_error=on_error,
            loading_text='AI 正在改图...',
            status_text=None,
        )

    def _set_ai_busy(self, busy, status_text):
        self._ai_busy = busy
        try:
            if busy:
                self._ai_apply_btn.config(state=tk.DISABLED, text='请稍候...')
            else:
                self._ai_apply_btn.config(state=tk.NORMAL, text='应用 (Ctrl+Enter)')
        except Exception:
            pass
        if status_text is not None:
            try:
                self._ai_status_label.config(text=status_text)
            except Exception:
                pass
