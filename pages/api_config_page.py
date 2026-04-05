# -*- coding: utf-8 -*-
"""
模型配置页面
"""

import json
import tkinter as tk
from tkinter import messagebox, ttk

from modules.task_runner import TaskRunner
from modules.ui_components import (
    COLORS,
    FONTS,
    LoadingOverlay,
    ModernButton,
    ModernEntry,
    ScrollablePage,
)
from pages.api_config_support import (
    FORM_KEY,
    PRESET_MAP,
    PRESET_OPTIONS,
    build_base_form_template,
    merge_with_preset_defaults,
)


class APIConfigPage:
    def __init__(
        self,
        parent,
        config_mgr,
        api_client,
        history_mgr,
        set_status,
        navigate_page=None,
        app_bridge=None,
        force_new=False,
    ):
        self.config = config_mgr
        self.api = api_client
        self.history = history_mgr
        self.set_status = set_status
        self.navigate_page = navigate_page
        self.app_bridge = app_bridge
        self._force_new = force_new

        self._on_save_callback = None
        self.frame = tk.Frame(parent, bg=COLORS['bg_main'])
        self.loading = LoadingOverlay(self.frame, config_mgr, text='正在测试模型连接...')

        self.task_runner = TaskRunner(self.frame, loading=self.loading, set_status=self.set_status)
        self._entries = {}
        self._content = None
        self._provider_grid_frame = None
        self._current_api_id = None
        self._current_provider_type = 'openai'
        self._current_config = {}

        self._initialize_current_form()
        self._build()

    def _initialize_current_form(self):
        if self._force_new:
            self._load_preset_draft('openai', reload=False)
            return

        active_api = self.config.active_api
        if active_api and self.config.get_api_config(active_api):
            self._load_saved_record(active_api, reload=False)
            return

        saved_apis = self.config.list_saved_apis()
        if saved_apis:
            self._load_saved_record(saved_apis[0][0], reload=False)
            return

        self._load_preset_draft('openai', reload=False)

    def _load_preset_draft(self, provider_type, reload=True):
        provider_type = provider_type if provider_type in PRESET_MAP else 'custom'
        self._current_api_id = None
        self._current_provider_type = provider_type
        self._current_config = merge_with_preset_defaults({}, provider_type)
        if reload:
            self._reload_panel()

    def _load_saved_record(self, api_id, reload=True):
        cfg = self.config.get_api_config(api_id)
        if not cfg:
            self._load_preset_draft('openai', reload=reload)
            return

        provider_type = (cfg.get('provider_type') or '').strip().lower()
        if provider_type not in PRESET_MAP:
            provider_type = 'custom'

        self._current_api_id = api_id
        self._current_provider_type = provider_type
        self._current_config = merge_with_preset_defaults(cfg, provider_type)
        if reload:
            self._reload_panel()

    def _build(self):
        header = tk.Frame(self.frame, bg=COLORS['bg_main'])
        header.pack(fill=tk.X, pady=(0, 12))
        hdr_left = tk.Frame(header, bg=COLORS['bg_main'])
        hdr_left.pack(fill=tk.X, expand=True)
        tk.Label(
            hdr_left,
            text='\u2699  模型配置中心',
            font=FONTS['subtitle'],
            fg=COLORS['primary'],
            bg=COLORS['bg_main'],
        ).pack(anchor='w')
        tk.Label(
            hdr_left,
            text='预设按钮只负责填充模板，填写服务商名称和密钥后再保存为一条记录。',
            font=FONTS['small'],
            fg=COLORS['text_muted'],
            bg=COLORS['bg_main'],
        ).pack(anchor='w', pady=(4, 0))

        self._scroll_page = ScrollablePage(self.frame, bg=COLORS['bg_main'])
        self._scroll_page.pack(fill=tk.BOTH, expand=True)
        self._content = self._scroll_page.inner
        self._build_api_panel(self._content)

    def _reload_panel(self):
        if not self._content:
            return

        new_frame = tk.Frame(self._content, bg=COLORS['bg_main'])
        self._entries = {}
        if hasattr(self, 'tip_label'):
            del self.tip_label

        self._build_api_panel(new_frame)
        for widget in self._content.winfo_children():
            if widget is not new_frame:
                widget.destroy()
        new_frame.pack(fill=tk.BOTH, expand=True)
        self._scroll_page.scroll_to_top()

    def _get_form_entries(self):
        return self._entries.setdefault(FORM_KEY, {})

    def _get_form_config(self):
        return dict(self._current_config or build_base_form_template(self._current_provider_type))

    def _select_api(self, target_id):
        """按 api_id 加载记录（仅用于「查看详情」跳转，进入编辑模式）"""
        if target_id in self.config.get_saved_apis():
            self._load_saved_record(target_id, reload=True)
            return
        self._load_preset_draft(target_id, reload=True)

    def _select_preset(self, preset_id):
        """点击预设模板按钮，始终创建新草稿（不进入编辑模式）"""
        self._load_preset_draft(preset_id, reload=True)

    def _build_api_panel(self, parent):
        self._entries[FORM_KEY] = {}

        grid_card = tk.Frame(
            parent,
            bg=COLORS['card_bg'],
            highlightbackground=COLORS['card_border'],
            highlightthickness=1,
        )
        grid_card.pack(fill=tk.X, pady=(0, 10))

        grid_title_row = tk.Frame(grid_card, bg=COLORS['card_bg'])
        grid_title_row.pack(fill=tk.X, padx=16, pady=(10, 6))
        tk.Label(
            grid_title_row,
            text='选择预设模板',
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.LEFT)
        tk.Label(
            grid_title_row,
            text='点击后只会创建当前表单草稿，不会立即新增记录',
            font=FONTS['small'],
            fg=COLORS['text_muted'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.RIGHT)

        self._provider_grid_frame = tk.Frame(grid_card, bg=COLORS['card_bg'])
        self._provider_grid_frame.pack(fill=tk.X, padx=16, pady=(0, 10))
        self._build_provider_grid(self._provider_grid_frame)

        self._build_basic_section(parent, FORM_KEY)
        self._build_collapsible_section(parent, '高级选项', lambda p: self._build_advanced_options(p, FORM_KEY))
        self._build_json_section(parent, FORM_KEY)
        self._build_test_section(parent, FORM_KEY)
        self._build_collapsible_section(parent, '参数需求', lambda p: self._build_params_section(p, FORM_KEY))
        self._build_billing_section(parent, FORM_KEY)

    def _build_provider_grid(self, parent):
        for widget in parent.winfo_children():
            widget.destroy()

        cols = 5
        for i, (preset_id, label, _defaults) in enumerate(PRESET_OPTIONS):
            is_selected = (preset_id == self._current_provider_type)
            btn_bg = COLORS['primary'] if is_selected else COLORS['surface_alt']
            btn_fg = '#ffffff' if is_selected else COLORS['text_main']
            btn = tk.Label(
                parent,
                text=label,
                font=FONTS['small'],
                bg=btn_bg,
                fg=btn_fg,
                relief=tk.FLAT,
                bd=0,
                padx=10,
                pady=5,
                cursor='hand2',
                highlightbackground=COLORS['primary'] if is_selected else COLORS['card_border'],
                highlightthickness=1,
            )
            btn.grid(row=i // cols, column=i % cols, padx=4, pady=3, sticky='ew')
            btn.bind('<Button-1>', lambda _event, aid=preset_id: self._select_preset(aid))

        for col in range(cols):
            parent.columnconfigure(col, weight=1)

    def _make_card(self, parent, title, right_widget_factory=None):
        shell = tk.Frame(parent, bg=COLORS['shadow'], bd=0, highlightthickness=0)
        shell.pack(fill=tk.X, pady=(0, 10))

        card = tk.Frame(
            shell,
            bg=COLORS['card_bg'],
            highlightbackground=COLORS['card_border'],
            highlightthickness=1,
            bd=0,
        )
        card.pack(fill=tk.X, padx=(0, 4), pady=(0, 4))

        title_row = tk.Frame(card, bg=COLORS['card_bg'])
        title_row.pack(fill=tk.X, padx=16, pady=(12, 0))
        tk.Label(
            title_row,
            text=title,
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.LEFT)

        if right_widget_factory:
            right_widget_factory(title_row)

        inner = tk.Frame(card, bg=COLORS['card_bg'])
        inner.pack(fill=tk.X, padx=16, pady=(10, 14))
        return card, inner

    def _build_collapsible_section(self, parent, title, build_fn, collapsed=True, right_widget_factory=None):
        shell = tk.Frame(parent, bg=COLORS['shadow'], bd=0, highlightthickness=0)
        shell.pack(fill=tk.X, pady=(0, 10))

        card = tk.Frame(
            shell,
            bg=COLORS['card_bg'],
            highlightbackground=COLORS['card_border'],
            highlightthickness=1,
            bd=0,
        )
        card.pack(fill=tk.X, padx=(0, 4), pady=(0, 4))

        is_open = tk.BooleanVar(value=not collapsed)

        header_row = tk.Frame(card, bg=COLORS['card_bg'], cursor='hand2')
        header_row.pack(fill=tk.X, padx=16, pady=(10, 10))

        arrow_lbl = tk.Label(
            header_row,
            text='\u25b6' if collapsed else '\u25bc',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            cursor='hand2',
        )
        arrow_lbl.pack(side=tk.LEFT, padx=(0, 8))

        tk.Label(
            header_row,
            text=title,
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
            cursor='hand2',
        ).pack(side=tk.LEFT)

        if right_widget_factory:
            right_widget_factory(header_row)

        body = tk.Frame(card, bg=COLORS['card_bg'])
        built = [False]

        def toggle(*_args):
            if not built[0]:
                build_fn(body)
                built[0] = True
            if is_open.get():
                body.pack_forget()
                arrow_lbl.configure(text='\u25b6')
                is_open.set(False)
            else:
                body.pack(fill=tk.X, padx=16, pady=(0, 12))
                arrow_lbl.configure(text='\u25bc')
                is_open.set(True)

        header_row.bind('<Button-1>', toggle)
        arrow_lbl.bind('<Button-1>', toggle)

        if not collapsed:
            build_fn(body)
            built[0] = True
            body.pack(fill=tk.X, padx=16, pady=(0, 12))

        return card

    def _entry_row(self, parent, label, key, form_key, placeholder='', show='', width=40, prefill=None):
        row = tk.Frame(parent, bg=COLORS['card_bg'])
        row.pack(fill=tk.X, pady=4)
        tk.Label(
            row,
            text=label,
            font=FONTS['body'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            width=16,
            anchor='e',
        ).pack(side=tk.LEFT, padx=(0, 10))

        cfg = self._get_form_config()
        entry = ModernEntry(row, placeholder=placeholder, show=show, width=width)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)

        saved = cfg.get(key, '')
        value = saved if saved else (prefill or '')
        if value:
            entry.delete(0, tk.END)
            entry.insert(0, value)
            entry.configure(fg=COLORS['text_main'])
            entry._placeholder_active = False

        self._entries[form_key][key] = entry
        return entry

    def _combo_row(self, parent, label, key, form_key, values, width=35):
        row = tk.Frame(parent, bg=COLORS['card_bg'])
        row.pack(fill=tk.X, pady=4)
        tk.Label(
            row,
            text=label,
            font=FONTS['body'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            width=16,
            anchor='e',
        ).pack(side=tk.LEFT, padx=(0, 10))

        cfg = self._get_form_config()
        var = tk.StringVar(value=cfg.get(key, values[0] if values else ''))
        combo = ttk.Combobox(
            row,
            textvariable=var,
            values=values,
            style='Modern.TCombobox',
            width=width,
            state='readonly',
        )
        combo.pack(side=tk.LEFT)
        self._entries[form_key][key] = var
        return combo, var

    def _build_basic_section(self, parent, form_key):
        _, inner = self._make_card(parent, '基础配置')
        cfg = self._get_form_config()
        preset = PRESET_MAP.get(self._current_provider_type, PRESET_MAP['custom'])
        preset_defaults = preset.get('defaults', {})

        info_row = tk.Frame(inner, bg=COLORS['card_bg'])
        info_row.pack(fill=tk.X, pady=(0, 8))
        tk.Label(
            info_row,
            text='预设模板',
            font=FONTS['body'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            width=16,
            anchor='e',
        ).pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(
            info_row,
            text=preset['label'],
            font=FONTS['body_bold'],
            fg=COLORS['primary'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.LEFT)

        mode_text = '当前正在编辑已保存记录' if self._current_api_id else '当前为未保存草稿，保存后才会新增一条记录'
        tk.Label(
            inner,
            text=mode_text,
            font=FONTS['small'],
            fg=COLORS['text_muted'],
            bg=COLORS['card_bg'],
            anchor='w',
        ).pack(anchor='w', padx=(116, 0), pady=(0, 8))

        self._entry_row(inner, '服务商名称', 'name', form_key, placeholder='请输入服务商名称', width=40)
        self._entry_row(inner, '备注', 'remark', form_key, placeholder='可选备注信息', width=40)
        self._entry_row(inner, '官网链接', 'website', form_key, placeholder=preset_defaults.get('website', 'https://...'), width=40)
        self._entry_row(inner, 'API Key', 'key', form_key, placeholder='请输入 API Key', show='*', width=40)
        self._entry_row(
            inner,
            '请求地址',
            'base_url',
            form_key,
            placeholder=preset_defaults.get('base_url', 'https://your-api-endpoint/v1'),
            width=40,
        )

        mv_row = tk.Frame(inner, bg=COLORS['card_bg'])
        mv_row.pack(fill=tk.X, pady=4)
        tk.Label(
            mv_row,
            text='模型版本',
            font=FONTS['body'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            width=16,
            anchor='e',
        ).pack(side=tk.LEFT, padx=(0, 10))

        model_init = cfg.get('model', '') or preset_defaults.get('model', '')
        model_var = tk.StringVar(value=model_init)
        self._entries[form_key]['model'] = model_var
        model_combo = ttk.Combobox(
            mv_row,
            textvariable=model_var,
            values=[model_init] if model_init else [],
            style='Modern.TCombobox',
            width=32,
        )
        model_combo.pack(side=tk.LEFT)
        model_sel_lbl = tk.Label(
            inner,
            text=f'已选择：{model_init}' if model_init else '已选择：（未选择）',
            font=FONTS['small'],
            fg=COLORS['text_muted'],
            bg=COLORS['card_bg'],
            anchor='w',
        )
        ModernButton(
            mv_row,
            '刷新',
            style='secondary',
            command=lambda: self._fetch_models(form_key, model_combo, model_sel_lbl),
            padx=8,
            pady=4,
        ).pack(side=tk.LEFT, padx=(6, 0))
        model_sel_lbl.pack(anchor='w', padx=(116, 0))
        model_var.trace_add(
            'write',
            lambda *_args: model_sel_lbl.configure(
                text=f'已选择：{model_var.get()}' if model_var.get() else '已选择：（未选择）'
            ),
        )

        btn_row = tk.Frame(inner, bg=COLORS['card_bg'])
        btn_row.pack(fill=tk.X, pady=(10, 0))
        ModernButton(btn_row, '\u21ba 重置当前表单', style='secondary', command=self._reset, padx=16, pady=8).pack(side=tk.LEFT)
        if self._current_api_id:
            ModernButton(btn_row, '\u2716 删除此记录', style='danger', command=self._delete_current, padx=16, pady=8).pack(side=tk.LEFT, padx=(8, 0))

        if not hasattr(self, 'tip_label'):
            self.tip_label = tk.Label(
                inner,
                text='',
                font=FONTS['small'],
                fg=COLORS['success'],
                bg=COLORS['card_bg'],
                anchor='w',
            )
            self.tip_label.pack(anchor='w', pady=(4, 0))

    def _build_advanced_options(self, parent, form_key):
        self._combo_row(parent, 'API 格式', 'api_format', form_key, ['OpenAI', 'Claude', 'Baidu', 'Custom'])
        self._entry_row(parent, '认证字段', 'auth_field', form_key, placeholder='Authorization', width=36)
        self._entry_row(parent, '模型映射', 'model_mapping', form_key, placeholder='源模型名:目标模型名', width=36)

    def _build_json_section(self, parent, form_key):
        _, inner = self._make_card(parent, '高级请求体 JSON')
        cfg = self._get_form_config()

        checks_frame = tk.Frame(inner, bg=COLORS['card_bg'])
        checks_frame.pack(fill=tk.X, pady=(0, 8))

        check_defs = [
            ('hide_ai_signature', '隐藏 AI 署名'),
            ('teammates_mode', 'teammates 模式'),
            ('enable_tool_search', '启用 tool search'),
            ('high_intensity_thinking', '高强度思考'),
        ]
        for key, label in check_defs:
            var = tk.BooleanVar(value=bool(cfg.get(key, False)))
            self._entries[form_key][key] = var
            cb = tk.Checkbutton(
                checks_frame,
                text=label,
                variable=var,
                font=FONTS['body'],
                fg=COLORS['text_main'],
                bg=COLORS['card_bg'],
                activebackground=COLORS['card_bg'],
                selectcolor=COLORS['card_bg'],
                bd=0,
                highlightthickness=0,
                cursor='hand2',
            )
            cb.pack(side=tk.LEFT, padx=(0, 18))

        json_label_row = tk.Frame(inner, bg=COLORS['card_bg'])
        json_label_row.pack(fill=tk.X)
        tk.Label(
            json_label_row,
            text='额外 JSON 参数',
            font=FONTS['body'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.LEFT)
        ModernButton(
            json_label_row,
            '格式化',
            style='secondary',
            command=lambda: self._format_json(form_key),
            padx=10,
            pady=4,
        ).pack(side=tk.RIGHT)

        txt_frame = tk.Frame(inner, bg=COLORS['card_bg'])
        txt_frame.pack(fill=tk.X, pady=(6, 0))
        txt = tk.Text(
            txt_frame,
            height=6,
            font=('Consolas', 10),
            bg=COLORS['surface_alt'],
            fg=COLORS['text_main'],
            insertbackground=COLORS['text_main'],
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=COLORS['card_border'],
            wrap=tk.NONE,
        )
        txt.pack(fill=tk.X)
        saved_json = cfg.get('extra_json', '')
        if saved_json:
            txt.insert('1.0', saved_json)
        self._entries[form_key]['extra_json'] = txt

    def _build_test_section(self, parent, form_key):
        cfg = self._get_form_config()
        use_separate = tk.BooleanVar(value=bool(cfg.get('use_separate_test', False)))
        self._entries[form_key]['use_separate_test'] = use_separate

        def make_toggle(title_row):
            tk.Checkbutton(
                title_row,
                text='使用单独配置',
                variable=use_separate,
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                activebackground=COLORS['card_bg'],
                selectcolor=COLORS['card_bg'],
                bd=0,
                highlightthickness=0,
                cursor='hand2',
            ).pack(side=tk.RIGHT)

        _, inner = self._make_card(parent, '模型测试配置', right_widget_factory=make_toggle)

        self._entry_row(inner, '测试模型', 'test_model', form_key, placeholder='留空沿用当前模型', width=40)
        self._entry_row(inner, '提示词', 'test_prompt', form_key, placeholder='Who are you?', width=40)
        self._entry_row(inner, '超时（秒）', 'test_timeout', form_key, placeholder='45', width=20)
        self._entry_row(inner, '降级阈值（毫秒）', 'test_degrade_ms', form_key, placeholder='6000', width=20)
        self._entry_row(inner, '最大重试次数', 'test_max_retries', form_key, placeholder='2', width=20)

        def refresh_state(*_args):
            state = 'normal' if use_separate.get() else 'disabled'
            for child in inner.winfo_children():
                try:
                    child.configure(state=state)
                except Exception:
                    pass

        use_separate.trace_add('write', refresh_state)
        refresh_state()

        test_btn_row = tk.Frame(inner, bg=COLORS['card_bg'])
        test_btn_row.pack(fill=tk.X, pady=(10, 0))
        ModernButton(test_btn_row, '\U0001f50d 测试连接', style='accent', command=self._test_connection, padx=16, pady=8).pack(side=tk.LEFT)

    def _build_params_section(self, parent, form_key):
        self._entry_row(parent, '温度', 'temperature', form_key, placeholder='0.7', width=20)
        self._entry_row(parent, '最大生成长度', 'max_tokens', form_key, placeholder='4096', width=20)
        self._entry_row(parent, '请求超时（秒）', 'timeout', form_key, placeholder='60', width=20)
        self._entry_row(parent, '核采样', 'top_p', form_key, placeholder='1.0', width=20)
        self._entry_row(parent, '存在惩罚', 'presence_penalty', form_key, placeholder='0.0', width=20)
        self._entry_row(parent, '频率惩罚', 'frequency_penalty', form_key, placeholder='0.0', width=20)

    def _build_billing_section(self, parent, form_key):
        cfg = self._get_form_config()
        use_separate = tk.BooleanVar(value=bool(cfg.get('use_separate_billing', False)))
        self._entries[form_key]['use_separate_billing'] = use_separate

        def make_toggle(title_row):
            tk.Checkbutton(
                title_row,
                text='使用单独配置',
                variable=use_separate,
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                activebackground=COLORS['card_bg'],
                selectcolor=COLORS['card_bg'],
                bd=0,
                highlightthickness=0,
                cursor='hand2',
            ).pack(side=tk.RIGHT)

        def build_body(inner):
            self._entry_row(inner, '成本倍率', 'billing_multiplier', form_key, placeholder='1.0（空=沿用全局）', width=30)
            self._combo_row(inner, '计费模式', 'billing_mode', form_key, ['', 'request_model', 'response_model'], width=28)

            def refresh_state(*_args):
                state = 'normal' if use_separate.get() else 'disabled'
                for child in inner.winfo_children():
                    try:
                        child.configure(state=state)
                    except Exception:
                        pass

            use_separate.trace_add('write', refresh_state)
            refresh_state()

        self._build_collapsible_section(parent, '计费配置', build_body, collapsed=True, right_widget_factory=make_toggle)

    def _format_json(self, form_key):
        txt = self._entries.get(form_key, {}).get('extra_json')
        if not txt:
            return
        raw = txt.get('1.0', tk.END).strip()
        if not raw:
            return
        try:
            parsed = json.loads(raw)
            pretty = json.dumps(parsed, ensure_ascii=False, indent=2)
            txt.delete('1.0', tk.END)
            txt.insert('1.0', pretty)
        except json.JSONDecodeError as exc:
            messagebox.showerror('JSON 格式错误', str(exc), parent=self.frame)

    def _collect_api_config(self, form_key):
        entries = self._entries.get(form_key, {})
        cfg = merge_with_preset_defaults(self._get_form_config(), self._current_provider_type)

        text_keys = [
            'name', 'remark', 'website', 'key', 'base_url',
            'auth_field', 'model_mapping',
            'test_model', 'test_prompt', 'test_timeout', 'test_degrade_ms', 'test_max_retries',
            'temperature', 'max_tokens', 'timeout', 'top_p', 'presence_penalty', 'frequency_penalty',
            'billing_multiplier',
        ]
        for key in text_keys:
            widget = entries.get(key)
            if widget is None:
                continue
            if isinstance(widget, ModernEntry):
                value = widget.get_value()
            else:
                value = widget.get()
            cfg[key] = value

        bool_keys = [
            'hide_ai_signature',
            'teammates_mode',
            'enable_tool_search',
            'high_intensity_thinking',
            'use_separate_test',
            'use_separate_billing',
        ]
        for key in bool_keys:
            var = entries.get(key)
            if var is not None:
                cfg[key] = bool(var.get())

        str_var_keys = ['api_format', 'billing_mode', 'model']
        for key in str_var_keys:
            var = entries.get(key)
            if var is not None:
                cfg[key] = var.get()

        txt_widget = entries.get('extra_json')
        if txt_widget is not None:
            cfg['extra_json'] = txt_widget.get('1.0', tk.END).strip()

        cfg['name'] = (cfg.get('name', '') or '').strip()
        cfg['provider_type'] = self._current_provider_type
        return cfg

    def _validate(self):
        entries = self._entries.get(FORM_KEY, {})
        required = [
            ('name', '服务商名称'),
            ('key', 'API Key'),
            ('base_url', '请求地址'),
        ]
        missing = []
        for field, label in required:
            widget = entries.get(field)
            if widget is None:
                continue
            value = widget.get_value() if isinstance(widget, ModernEntry) else widget.get()
            if not value.strip():
                missing.append((label, widget))
        return (len(missing) == 0), missing

    def _highlight_error(self, widget, error=True):
        color = COLORS.get('error', '#e53935') if error else COLORS.get('card_border', '#e0e0e0')
        try:
            widget.configure(highlightbackground=color, highlightthickness=1 if error else 0)
        except Exception:
            pass

    def _show_tip(self, text, color, duration_ms=0):
        if hasattr(self, 'tip_label') and self.tip_label.winfo_exists():
            self.tip_label.configure(text=text, fg=color)
            if duration_ms:
                self.frame.after(
                    duration_ms,
                    lambda: self.tip_label.configure(text='') if self.tip_label.winfo_exists() else None,
                )

    def _save_all(self):
        ok, missing = self._validate()
        if not ok:
            labels = '、'.join(label for label, _widget in missing)
            for _label, widget in missing:
                self._highlight_error(widget, True)
                widget.after(3000, lambda w=widget: self._highlight_error(w, False))
            self._show_tip(f'\u26a0 以下必填项未填写：{labels}', COLORS.get('error', '#e53935'), duration_ms=5000)
            return False

        cfg = self._collect_api_config(FORM_KEY)
        if self._force_new:
            exclude_id = None
        else:
            exclude_id = self._current_api_id
        duplicate_id = self.config.find_api_id_by_name(cfg.get('name', ''), exclude_api_id=exclude_id)
        if duplicate_id:
            name_entry = self._entries.get(FORM_KEY, {}).get('name')
            if name_entry is not None:
                self._highlight_error(name_entry, True)
                name_entry.after(3000, lambda w=name_entry: self._highlight_error(w, False))
            messagebox.showerror('保存失败', '服务商名称已存在，请更换名称后再保存。', parent=self.frame)
            self._show_tip('服务商名称已存在，请更换后再保存。', COLORS['error'], duration_ms=5000)
            return False

        if self._force_new:
            target_api_id = self.config.generate_api_id()
        else:
            target_api_id = self._current_api_id or self.config.generate_api_id()
        self.config.set_api_config(target_api_id, cfg)
        self.config.active_api = target_api_id
        if not self.config.save():
            messagebox.showerror('保存失败', '配置保存失败，请稍后重试。', parent=self.frame)
            self._show_tip('配置保存失败，请稍后重试。', COLORS['error'], duration_ms=5000)
            return False

        self._current_api_id = target_api_id
        self._current_provider_type = cfg.get('provider_type', 'custom')
        self._current_config = self.config.get_api_config(target_api_id)
        self._show_tip('\u2713 配置已保存', COLORS['success'], duration_ms=3000)
        if self._on_save_callback:
            self._on_save_callback()
        if self._force_new:
            self._load_preset_draft(cfg.get('provider_type', 'openai'), reload=True)
        else:
            self._reload_panel()
        return True

    def _fetch_models(self, form_key, combo, label):
        label.configure(text='正在获取模型列表...')
        cfg = self._collect_api_config(form_key)
        api_hint = self._current_api_id or self._current_provider_type

        def _done(models):
            combo['values'] = models
            current = combo.get()
            if not current and models:
                combo.set(models[0])
            label.configure(text=f'已选择：{combo.get()}' if combo.get() else '已选择：（未选择）')

        def _fail(exc):
            label.configure(text=f'获取失败：{exc}')

        self.task_runner.run(
            work=lambda: self.api.fetch_models(api_hint, cfg=cfg),
            on_success=_done,
            on_error=_fail,
        )

    def _test_connection(self):
        cfg = self._collect_api_config(FORM_KEY)
        use_separate = bool(self._entries.get(FORM_KEY, {}).get('use_separate_test', tk.BooleanVar()).get())
        if use_separate:
            model_override = cfg.get('test_model', '').strip() or None
            prompt = cfg.get('test_prompt', '').strip() or 'Who are you?'
            try:
                timeout = float(cfg.get('test_timeout', '') or 45)
            except Exception:
                timeout = 45
            try:
                degrade_ms = int(cfg.get('test_degrade_ms', '') or 6000)
            except Exception:
                degrade_ms = 6000
            try:
                max_retries = int(cfg.get('test_max_retries', '') or 2)
            except Exception:
                max_retries = 2
        else:
            model_override = None
            prompt = self.config.get_setting('global_test_prompt', 'Who are you?') or 'Who are you?'
            timeout = float(self.config.get_setting('global_test_timeout_sec', 45) or 45)
            degrade_ms = int(self.config.get_setting('global_test_degrade_ms', 6000) or 6000)
            max_retries = int(self.config.get_setting('global_test_max_retries', 2) or 2)

        self._show_tip('正在测试连接...', COLORS['text_sub'])
        api_hint = self._current_api_id or self._current_provider_type

        def _done(result):
            ok, msg = result
            self._show_tip(msg, COLORS['success'] if ok else COLORS['error'])

        self.task_runner.run(
            work=lambda: self.api.test_connection(
                api_hint,
                prompt=prompt,
                model_override=model_override,
                timeout=timeout,
                degrade_threshold_ms=degrade_ms,
                max_retries=max_retries,
                cfg=cfg,
            ),
            on_success=_done,
            loading_text='正在测试模型连接...',
        )

    def _delete_current(self):
        if not self._current_api_id:
            return
        cfg = self.config.get_api_config(self._current_api_id)
        name = (cfg.get('name', '') if cfg else '') or self._current_api_id
        if not messagebox.askyesno('删除记录', f'确定要删除「{name}」吗？此操作不可撤销。', parent=self.frame):
            return
        self.config.delete_api_config(self._current_api_id)
        self.config.save()
        self._current_api_id = None
        self._current_provider_type = 'openai'
        self._current_config = {}
        self._initialize_current_form()
        self._reload_panel()
        self._show_tip('\u2713 记录已删除', COLORS['success'], duration_ms=3000)
        if self._on_save_callback:
            self._on_save_callback()

    def _reset(self):
        if not messagebox.askyesno('重置配置', '确定要清空所有已保存模型记录并重置当前表单吗？此操作不可撤销。', parent=self.frame):
            return

        self.config.reset()
        for widget in self.frame.winfo_children():
            widget.destroy()

        self.loading = LoadingOverlay(self.frame, self.config, text='正在测试模型连接...')
        self.task_runner = TaskRunner(self.frame, loading=self.loading, set_status=self.set_status)
        self._entries = {}
        self._content = None
        self._provider_grid_frame = None
        self._current_api_id = None
        self._current_provider_type = 'openai'
        self._current_config = {}

        self._initialize_current_form()
        self._build()
        self._show_tip('已清空已保存记录，当前显示新的模板草稿。', COLORS['success'], duration_ms=4000)
