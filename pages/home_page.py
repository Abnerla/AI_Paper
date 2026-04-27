# -*- coding: utf-8 -*-
"""
纸研社首页
"""

import json
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk

from modules.config import resolve_model_display_name
from pages.home_support import (
    active_model_ready,
    build_dashboard_view_model,
    get_active_model_label,
)
from modules.usage_stats import (
    USAGE_PERIOD_OPTIONS,
    default_query_time_range_strings,
    format_currency,
    format_token_count,
)
from modules.ui_components import (
    apply_adaptive_window_geometry,
    ask_datetime_string,
    bind_adaptive_wrap,
    CardFrame,
    COLORS,
    create_scrolled_text,
    create_home_shell_button,
    FONTS,
    ModernButton,
    ResponsiveButtonBar,
    refresh_home_shell_button,
    THEMES,
    ToolIconButton,
    load_image,
)
from modules.task_runner import TaskRunner
from pages.api_config_support import (
    merge_with_preset_defaults,
    resolve_connection_test_settings,
)

DASHBOARD_TITLE_FONT_SIZE = 20
DASHBOARD_SECTION_TITLE_FONT_SIZE = 16


class HomePage:
    def __init__(
        self,
        parent,
        config_mgr,
        api_client,
        history_mgr,
        set_status,
        navigate_page=None,
        app_bridge=None,
    ):
        self.config = config_mgr
        self.api = api_client
        self.history = history_mgr
        self.set_status = set_status
        self.navigate_page = navigate_page
        self.app_bridge = app_bridge
        self.frame = tk.Frame(parent, bg=COLORS['bg_main'])

        self.logo_image = None
        self.dashboard_view_model = {}

        self.hero_panel = None
        self.hero_canvas = None
        self.hero_visual = None
        self.hero_text = None
        self.hero_progress = None
        self.hero_visual_window = None
        self.hero_text_window = None
        self.hero_progress_window = None
        self.hero_top_bar = None

        self.hero_title_item = None
        self.hero_subtitle_item = None
        self.hero_identity_item = None
        self.hero_tip_item = None
        self.hero_action_shells = []
        self.hero_action_windows = []
        self.hero_tag_shells = []
        self.hero_tag_windows = []
        self.hero_button_shells = []
        self.dashboard_shell_buttons = []
        self.hero_completion_label = None
        self.hero_completion_hint = None

        self.dashboard_panel = None
        self.dashboard_columns = None
        self.dashboard_usage_row = None
        self.left_column = None
        self.right_column = None

        self.board_subtitle_label = None
        self.task_text_label = None
        self.status_value_labels = {}
        self.status_continue_button_shell = None
        self.status_continue_button = None
        self.system_status_empty_label = None
        self.system_status_list = None
        self.system_status_card = None
        self.usage_card = None
        self.usage_period_key = 'all'
        self.usage_period_buttons = {}
        self.usage_summary_labels = {}
        self.usage_summary_row = None
        self.usage_summary_cards = []
        self.usage_page_label_to_id = {}
        self.usage_status_label_to_value = {}
        self.usage_chart_canvas = None
        self.usage_chart_caption_label = None
        self.usage_notebook = None
        self.usage_log_page_var = None
        self.usage_log_status_var = None
        self.usage_log_provider_var = None
        self.usage_log_model_var = None
        self.usage_log_start_var = None
        self.usage_log_end_var = None
        self.usage_log_tree = None
        self.usage_log_row_map = {}
        self.usage_provider_tree = None
        self.usage_model_tree = None
        self.pricing_panel_body = None
        self.pricing_expanded = False
        self.pricing_toggle_button = None
        self.pricing_rule_tree = None
        self.pricing_provider_var = None
        self.pricing_model_var = None
        self.pricing_input_price_var = None
        self.pricing_output_price_var = None
        self.pricing_cache_create_var = None
        self.pricing_cache_hit_var = None
        self.pricing_enabled_var = None
        self.pricing_edit_key = None
        self._usage_layout_after_id = None
        self._hero_relayout_job = None
        self._dashboard_relayout_job = None
        self._usage_chart_redraw_job = None
        self._usage_summary_cards_ready = False
        self.usage_task_runner = TaskRunner(self.frame, set_status=self.set_status)
        self.model_test_task_runner = TaskRunner(self.frame, set_status=self.set_status)
        self._usage_refresh_token = 0
        self._usage_trend_cache = None
        self._hero_last_width = None
        self._dashboard_layout_mode = None
        self._usage_chart_last_signature = None

        self._build()

    def _build(self):
        self._build_hero()
        self._build_dashboard()
        self.frame.after_idle(lambda: self._schedule_hero_relayout(delay_ms=0))
        self.frame.after_idle(lambda: self._schedule_dashboard_relayout(delay_ms=0))
        self.refresh_dashboard()

    def _cancel_scheduled_job(self, attr_name):
        job_id = getattr(self, attr_name, None)
        if job_id is None:
            return
        try:
            self.frame.after_cancel(job_id)
        except tk.TclError:
            pass
        setattr(self, attr_name, None)

    def _schedule_scheduled_job(self, attr_name, callback, delay_ms=24):
        if getattr(self, attr_name, None) is not None:
            return
        try:
            job_id = self.frame.after(delay_ms, callback)
        except tk.TclError:
            job_id = None
        setattr(self, attr_name, job_id)

    def _schedule_hero_relayout(self, _event=None, delay_ms=24):
        self._schedule_scheduled_job('_hero_relayout_job', self._run_hero_relayout, delay_ms)

    def _run_hero_relayout(self):
        self._hero_relayout_job = None
        self._relayout_hero()

    def _schedule_dashboard_relayout(self, _event=None, delay_ms=24):
        self._schedule_scheduled_job('_dashboard_relayout_job', self._run_dashboard_relayout, delay_ms)

    def _run_dashboard_relayout(self):
        self._dashboard_relayout_job = None
        self._relayout_dashboard()

    def _schedule_usage_chart_redraw(self, _event=None, delay_ms=32):
        self._schedule_scheduled_job('_usage_chart_redraw_job', self._run_usage_chart_redraw, delay_ms)

    def _run_usage_chart_redraw(self):
        self._usage_chart_redraw_job = None
        self._draw_usage_chart()

    def _make_hero_shell_button(self, parent, text, style, command, padx, pady, font, min_width, border_color=None):
        shell, button = create_home_shell_button(
            parent,
            text,
            command=command,
            style=style,
            padx=padx,
            pady=pady,
            font=font,
            border_color=border_color,
        )
        # 记录 min_width，延迟到窗口可见后由 _fix_hero_button_sizes 统一固定尺寸
        shell._min_width = min_width
        self.hero_button_shells.append((shell, button))
        return shell

    def _create_dashboard_shell_button(self, parent, text, *, command, style='secondary', padx=12, pady=8, font=None, border_color=None, **button_kwargs):
        shell, button = create_home_shell_button(
            parent,
            text,
            command=command,
            style=style,
            padx=padx,
            pady=pady,
            font=font or FONTS['body_bold'],
            border_color=border_color,
            **button_kwargs,
        )
        self.dashboard_shell_buttons.append((shell, button))
        return shell, button

    def _fix_hero_button_sizes(self):
        """在窗口可见、布局稳定后统一固定 hero 按钮的最小尺寸。"""
        for shell, _button in self.hero_button_shells:
            try:
                if shell.winfo_exists() and not shell.pack_info().get('fill'):
                    pass
            except tk.TclError:
                continue
            try:
                req_w = shell.winfo_reqwidth()
                req_h = shell.winfo_reqheight()
                min_w = getattr(shell, '_min_width', 0)
                if req_w > 0 and req_h > 0:
                    shell.configure(width=max(req_w, min_w), height=req_h)
                    shell.pack_propagate(False)
            except tk.TclError:
                pass

    def _refresh_primary_action_button_styles(self):
        for shell, button in self.hero_button_shells:
            refresh_home_shell_button(shell, button)

        for shell, button in self.dashboard_shell_buttons:
            refresh_home_shell_button(shell, button)

    def _build_hero(self):
        self.hero_panel = tk.Frame(self.frame, bg=COLORS['shadow'])
        self.hero_panel.pack(fill=tk.X, pady=(2, 18))

        self.hero_canvas = tk.Canvas(
            self.hero_panel,
            bg=COLORS['hero_stripe_a'],
            bd=0,
            highlightbackground=COLORS['card_border'],
            highlightthickness=3,
            height=300,
        )
        self.hero_canvas.pack(fill=tk.X, expand=True, padx=(0, 8), pady=(0, 8))
        self.hero_top_bar = self.hero_canvas.create_rectangle(0, 0, 1, 14, fill=COLORS['accent'], outline=COLORS['accent'])

        self.hero_visual = CardFrame(self.hero_canvas, padding=12)
        self.hero_visual.configure(width=208, height=208)
        self.hero_visual.pack_propagate(False)

        try:
            self.logo_image = load_image('logo.png', max_size=(148, 148))
            hero_logo = tk.Label(self.hero_visual.inner, image=self.logo_image, bg=COLORS['card_bg'])
        except Exception:
            hero_logo = tk.Label(
                self.hero_visual.inner,
                text='纸研社',
                font=FONTS['subtitle'],
                fg=COLORS['text_main'],
                bg=COLORS['card_bg'],
            )
        hero_logo.pack(expand=True)

        self.hero_corner = tk.Frame(self.hero_visual.body, bg=COLORS['accent'], width=10, height=10)
        self.hero_corner.place(relx=1.0, x=-12, y=12, anchor='ne')

        self.hero_text = tk.Canvas(
            self.hero_canvas,
            bg=COLORS['hero_stripe_a'],
            bd=0,
            highlightthickness=0,
            width=1200,
            height=360,
        )

        hero_title_font = (FONTS['hero'][0], 28, 'bold')
        self.hero_title_item = self.hero_text.create_text(
            0,
            0,
            anchor='nw',
            text='纸研社',
            font=hero_title_font,
            fill=COLORS['text_main'],
        )
        self.hero_subtitle_item = self.hero_text.create_text(
            0,
            0,
            anchor='nw',
            text='本地优先的智能论文工坊，把 AI 接入、写作、润色、对比和导出整合成一套工作台。',
            font=(FONTS['body'][0], 12),
            fill=COLORS['text_sub'],
            width=760,
        )
        self.hero_identity_item = self.hero_text.create_text(
            0,
            0,
            anchor='nw',
            text=get_active_model_label(self.config),
            font=(FONTS['body_bold'][0], 12, 'bold'),
            fill=COLORS['text_sub'],
        )
        self.hero_tip_item = self.hero_text.create_text(
            0,
            0,
            anchor='nw',
            text='今日建议：先完成模型配置，再导入论文开始写作。',
            font=FONTS['small'],
            fill=COLORS['text_sub'],
            width=700,
        )

        self.hero_actions_host = tk.Frame(self.hero_text, bg=COLORS['hero_stripe_a'], bd=0, highlightthickness=0)
        self.hero_actions_bar = ResponsiveButtonBar(
            self.hero_actions_host,
            min_item_width=148,
            gap_x=10,
            gap_y=8,
            bg=COLORS['hero_stripe_a'],
        )
        self.hero_actions_bar.pack(fill=tk.X)
        self.hero_actions_bar.add(
            self._make_hero_shell_button(
                self.hero_actions_bar,
                '开始使用',
                'primary_fixed',
                self._start_using,
                padx=18,
                pady=6,
                font=FONTS['body_bold'],
                min_width=176,
                border_color=THEMES['light']['card_border'],
            )
        )
        self.hero_actions_bar.add(
            self._make_hero_shell_button(
                self.hero_actions_bar,
                '系统公告',
                'secondary',
                lambda: self._trigger_action('show_announcement'),
                padx=18,
                pady=6,
                font=FONTS['body_bold'],
                min_width=176,
            )
        )

        self.hero_tags_host = tk.Frame(self.hero_text, bg=COLORS['hero_stripe_a'], bd=0, highlightthickness=0)
        self.hero_tags_bar = ResponsiveButtonBar(
            self.hero_tags_host,
            min_item_width=108,
            gap_x=6,
            gap_y=6,
            bg=COLORS['hero_stripe_a'],
        )
        self.hero_tags_bar.pack(fill=tk.X)
        hero_tag_specs = (
            ('使用教程', lambda: self._trigger_action('show_tutorial'), FONTS['tiny']),
            ('模型列表', lambda: self._show_model_list(), FONTS['tiny']),
            ('模型配置', lambda: self._trigger_action('show_api_config'), FONTS['tiny']),
            ('模型路由', lambda: self._trigger_action('show_model_routing'), FONTS['tiny']),
            ('提示词', lambda: self._trigger_action('show_prompt_manager'), FONTS['tiny']),
        )
        for label, command, font in hero_tag_specs:
            self.hero_tags_bar.add(
                self._make_hero_shell_button(
                    self.hero_tags_bar,
                    label,
                    'nav',
                    command,
                    padx=12,
                    pady=5,
                    font=font,
                    min_width=144,
                )
            )

        self.hero_action_shells = [
            self._make_hero_shell_button(
                self.hero_text,
                '开始使用',
                'primary_fixed',
                self._start_using,
                padx=18,
                pady=6,
                font=FONTS['body_bold'],
                min_width=176,
                border_color=THEMES['light']['card_border'],
            ),
            self._make_hero_shell_button(
                self.hero_text,
                '系统公告',
                'secondary',
                lambda: self._trigger_action('show_announcement'),
                padx=18,
                pady=6,
                font=FONTS['body_bold'],
                min_width=176,
            ),
        ]

        self.hero_tag_shells = []
        for label, command, font in hero_tag_specs:
            self.hero_tag_shells.append(
                self._make_hero_shell_button(
                    self.hero_text,
                    label,
                    'nav',
                    command,
                    padx=12,
                    pady=5,
                    font=font,
                    min_width=144,
                )
            )

        self.hero_progress = CardFrame(self.hero_canvas, padding=14)
        self.hero_progress.configure(width=338, height=286)
        self.hero_progress.pack_propagate(False)

        self.progress_top_line = tk.Frame(self.hero_progress.inner, bg=COLORS['primary'], height=4)
        self.progress_top_line.pack(fill=tk.X, pady=(0, 6))

        tk.Label(
            self.hero_progress.inner,
            text='最近历史记录',
            font=(FONTS['body_bold'][0], 11, 'bold'),
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            anchor='e',
        ).pack(anchor='e')

        self.hero_completion_label = tk.Label(
            self.hero_progress.inner,
            text='#0000',
            font=(FONTS['hero'][0], 26, 'bold'),
            fg=COLORS['primary'],
            bg=COLORS['card_bg'],
        )
        self.hero_completion_label.pack(anchor='e', pady=(8, 6))

        self.hero_completion_hint = tk.Label(
            self.hero_progress.inner,
            text='导出前记得核验引用与数据',
            font=FONTS['tiny'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            justify='right',
            anchor='e',
        )
        self.hero_completion_hint.pack(anchor='e', pady=(0, 4))
        bind_adaptive_wrap(self.hero_completion_hint, self.hero_progress.inner, padding=12, min_width=200, max_width=260)

        self.hero_actions_window = self.hero_text.create_window(0, 0, window=self.hero_actions_host, anchor='nw')
        self.hero_tags_window = self.hero_text.create_window(0, 0, window=self.hero_tags_host, anchor='nw')
        self.hero_action_windows = [
            self.hero_text.create_window(0, 0, window=shell, anchor='nw')
            for shell in self.hero_action_shells
        ]
        self.hero_tag_windows = [
            self.hero_text.create_window(0, 0, window=shell, anchor='nw')
            for shell in self.hero_tag_shells
        ]
        self.hero_visual_window = self.hero_canvas.create_window(0, 0, window=self.hero_visual, anchor='nw')
        self.hero_text_window = self.hero_canvas.create_window(0, 0, window=self.hero_text, anchor='nw')
        self.hero_progress_window = self.hero_canvas.create_window(0, 0, window=self.hero_progress, anchor='nw')
        self.hero_canvas.bind('<Configure>', self._schedule_hero_relayout, add='+')

    def _build_dashboard(self):
        self.dashboard_panel = CardFrame(self.frame, padding=16)
        self.dashboard_panel.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        board_header = tk.Frame(self.dashboard_panel.inner, bg=COLORS['card_bg'])
        board_header.pack(fill=tk.X, pady=(0, 14))

        board_title_row = tk.Frame(board_header, bg=COLORS['card_bg'])
        board_title_row.pack(fill=tk.X)

        tk.Label(
            board_title_row,
            text='主控台',
            font=(FONTS['title'][0], DASHBOARD_TITLE_FONT_SIZE, 'bold'),
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.LEFT, anchor='n')

        self.board_subtitle_label = tk.Label(
            board_title_row,
            text='先连通模型，再把写作、润色、检测和导出串起来。',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            justify='left',
            anchor='w',
        )
        self.board_subtitle_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(16, 0), pady=(10, 0))
        bind_adaptive_wrap(self.board_subtitle_label, board_title_row, padding=260, min_width=220)

        self.dashboard_columns = tk.Frame(self.dashboard_panel.inner, bg=COLORS['card_bg'])
        self.dashboard_columns.pack(fill=tk.X)

        self.left_column = tk.Frame(self.dashboard_columns, bg=COLORS['card_bg'])
        self.right_column = tk.Frame(self.dashboard_columns, bg=COLORS['card_bg'])
        self.dashboard_usage_row = tk.Frame(self.dashboard_panel.inner, bg=COLORS['card_bg'])
        self.dashboard_usage_row.pack(fill=tk.BOTH, expand=True, pady=(16, 0))

        self._build_status_card()
        self._build_tasks_card()
        self._build_quick_card()
        self._build_notice_card()

        self._relayout_dashboard(force=True)
        self.dashboard_columns.bind('<Configure>', self._schedule_dashboard_relayout, add='+')

    def _build_status_card(self):
        self.status_card = CardFrame(self.left_column, padding=22)
        self.status_card.pack(fill=tk.X, pady=(0, 16))
        self.status_card.inner.grid_columnconfigure(0, weight=1)

        tk.Label(
            self.status_card.inner,
            text='我的状态',
            font=(FONTS['title'][0], DASHBOARD_SECTION_TITLE_FONT_SIZE, 'bold'),
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).grid(row=0, column=0, sticky='w')

        content_shell = tk.Frame(self.status_card.inner, bg=COLORS['card_bg'])
        content_shell.grid(row=1, column=0, sticky='ew', pady=(12, 0))

        fields_shell = tk.Frame(content_shell, bg=COLORS['card_bg'])
        fields_shell.pack(fill=tk.X)

        field_specs = (
            ('当前文稿主题', 'paper_topic'),
            ('当前阶段', 'stage'),
            ('活跃模型', 'active_model'),
            ('当前字数', 'word_count'),
            ('最近一次处理时间', 'latest_time'),
            ('待处理风险数', 'pending_risks'),
        )
        for index, (title, key) in enumerate(field_specs):
            row = index // 2
            column = index % 2
            fields_shell.grid_columnconfigure(column, weight=1)
            item = tk.Frame(
                fields_shell,
                bg=COLORS['surface_alt'],
                highlightbackground=COLORS['card_border'],
                highlightthickness=1,
                padx=14,
                pady=12,
            )
            item.grid(row=row, column=column, sticky='nsew', padx=(0, 10 if column == 0 else 0), pady=(0, 10))
            title_shell = tk.Frame(item, bg=COLORS['surface_alt'])
            title_shell.pack(fill=tk.X, anchor='nw')
            tk.Label(
                title_shell,
                text=title,
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=COLORS['surface_alt'],
                justify='left',
                anchor='w',
            ).pack(fill=tk.X, anchor='nw')

            value_shell = tk.Frame(item, bg=COLORS['surface_alt'])
            value_shell.pack(fill=tk.BOTH, expand=True, anchor='nw', pady=(10, 0))
            value_label = tk.Label(
                value_shell,
                text='--',
                font=FONTS['body_bold'],
                fg=COLORS['text_main'],
                bg=COLORS['surface_alt'],
                justify='left',
                anchor='nw',
            )
            value_label.pack(fill=tk.X, anchor='nw')
            bind_adaptive_wrap(value_label, value_shell, padding=0, min_width=180)
            self.status_value_labels[key] = value_label

        button_host = tk.Frame(content_shell, bg=COLORS['card_bg'])
        button_host.pack(fill=tk.X, pady=(8, 0))

        self.status_continue_button_shell, self.status_continue_button = self._create_dashboard_shell_button(
            button_host,
            '继续当前任务',
            style='primary_fixed',
            command=self._continue_current_task,
            padx=20,
            pady=10,
            font=FONTS['body_bold'],
            border_color=THEMES['light']['card_border'],
        )
        self.status_continue_button_shell.pack(anchor='w')

    def _build_tasks_card(self):
        self.tasks_card = CardFrame(self.right_column, padding=22)
        self.tasks_card.pack(fill=tk.X, pady=(0, 16))

        tk.Label(
            self.tasks_card.inner,
            text='今日主线任务',
            font=(FONTS['title'][0], DASHBOARD_SECTION_TITLE_FONT_SIZE, 'bold'),
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(anchor='w')

        self.task_text_label = tk.Label(
            self.tasks_card.inner,
            text=(
                '1. 先配置自己的模型 Key、端点和模型名称\n'
                '2. 导入论文文档或新建空白草稿开始写作\n'
                '3. 生成大纲、优化表达，并补齐摘要或结论\n'
                '4. 检查格式、差异和重复风险后再导出成文档'
            ),
            font=FONTS['body'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            justify='left',
            anchor='w',
        )
        self.task_text_label.pack(fill=tk.X, anchor='w', pady=(14, 0))
        bind_adaptive_wrap(self.task_text_label, self.tasks_card.inner, padding=26, min_width=320)

    def _build_notice_card(self):
        self.notice_card = CardFrame(self.dashboard_usage_row, padding=22)
        self.notice_card.pack(fill=tk.BOTH, expand=True)

        self._build_usage_card()

    def _build_quick_card(self):
        self.quick_card = CardFrame(self.right_column, padding=22)
        self.quick_card.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            self.quick_card.inner,
            text='系统状态',
            font=(FONTS['title'][0], DASHBOARD_SECTION_TITLE_FONT_SIZE, 'bold'),
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(anchor='w')

        self.system_status_empty_label = tk.Label(
            self.quick_card.inner,
            text='系统运行正常',
            font=FONTS['body_bold'],
            fg=COLORS['success'],
            bg=COLORS['card_bg'],
            justify='left',
            anchor='w',
        )
        self.system_status_empty_label.pack(fill=tk.X, anchor='w', pady=(12, 0))

        self.system_status_list = tk.Frame(self.quick_card.inner, bg=COLORS['card_bg'])
        self.system_status_list.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

    def _build_usage_card(self):
        header = tk.Frame(self.notice_card.inner, bg=COLORS['card_bg'])
        header.pack(fill=tk.X)

        title_row = tk.Frame(header, bg=COLORS['card_bg'])
        title_row.pack(fill=tk.X)
        title_row.grid_columnconfigure(1, weight=1)
        tk.Label(
            title_row,
            text='使用统计',
            font=(FONTS['title'][0], DASHBOARD_SECTION_TITLE_FONT_SIZE, 'bold'),
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).grid(row=0, column=0, sticky='w')

        period_shell = tk.Frame(title_row, bg=COLORS['card_bg'])
        period_shell.grid(row=0, column=2, sticky='e')
        for key, label in USAGE_PERIOD_OPTIONS:
            shell, button = self._create_dashboard_shell_button(
                period_shell,
                label,
                style='secondary',
                command=lambda current=key: self._set_usage_period(current),
                padx=12,
                pady=6,
                font=FONTS['body_bold'],
            )
            shell.pack(side=tk.LEFT, padx=(8, 0))
            self.usage_period_buttons[key] = button

        self.usage_summary_row = tk.Frame(self.notice_card.inner, bg=COLORS['card_bg'])
        self.usage_summary_row.pack(fill=tk.X, pady=(18, 18))

        trend_card = CardFrame(self.notice_card.inner, padding=16)
        trend_card.pack(fill=tk.X, pady=(0, 18))
        trend_header = tk.Frame(trend_card.inner, bg=COLORS['card_bg'])
        trend_header.pack(fill=tk.X)
        tk.Label(
            trend_header,
            text='使用趋势',
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(side=tk.LEFT)
        self.usage_chart_caption_label = tk.Label(
            trend_header,
            text='过去 24 小时（按小时）',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
        )
        self.usage_chart_caption_label.pack(side=tk.RIGHT)

        self.usage_chart_canvas = tk.Canvas(
            trend_card.inner,
            bg=COLORS['card_bg'],
            bd=0,
            highlightbackground=COLORS['card_border'],
            highlightthickness=1,
            height=640,
        )
        self.usage_chart_canvas.pack(fill=tk.X, pady=(12, 0))
        self.usage_chart_canvas.bind('<Configure>', self._schedule_usage_chart_redraw, add='+')

        self.usage_notebook = ttk.Notebook(self.notice_card.inner, style='Card.TNotebook')
        self.usage_notebook.pack(fill=tk.BOTH, expand=True)

        request_tab = tk.Frame(self.usage_notebook, bg=COLORS['card_bg'])
        provider_tab = tk.Frame(self.usage_notebook, bg=COLORS['card_bg'])
        model_tab = tk.Frame(self.usage_notebook, bg=COLORS['card_bg'])
        self.usage_notebook.add(request_tab, text='请求日志')
        self.usage_notebook.add(provider_tab, text='供应商统计')
        self.usage_notebook.add(model_tab, text='模型统计')

        self._build_usage_request_log_tab(request_tab)
        self._build_usage_provider_tab(provider_tab)
        self._build_usage_model_tab(model_tab)
        self._build_usage_pricing_panel()
        self._refresh_usage_period_styles()

    def _build_usage_request_log_tab(self, parent):
        filter_card = CardFrame(parent, padding=14)
        filter_card.pack(fill=tk.X, pady=(12, 12))

        self.usage_page_label_to_id = {'全部应用': ''}
        for page_id, label in (
            ('paper_write', '论文写作'),
            ('polish', '学术润色'),
            ('ai_reduce', '降AI检测'),
            ('plagiarism', '降查重率'),
            ('correction', '智能纠错'),
        ):
            self.usage_page_label_to_id[label] = page_id
        self.usage_status_label_to_value = {
            '全部状态': '',
            '成功': 'success',
            '失败': 'error',
        }

        start_text, end_text = default_query_time_range_strings()
        self.usage_log_page_var = tk.StringVar(value='全部应用')
        self.usage_log_status_var = tk.StringVar(value='全部状态')
        self.usage_log_provider_var = tk.StringVar(value='')
        self.usage_log_model_var = tk.StringVar(value='')
        self.usage_log_start_var = tk.StringVar(value=start_text)
        self.usage_log_end_var = tk.StringVar(value=end_text)

        fields_row = tk.Frame(filter_card.inner, bg=COLORS['card_bg'])
        fields_row.pack(fill=tk.X, pady=(0, 8))
        for index in range(4):
            fields_row.grid_columnconfigure(index, weight=1)

        tk.Label(fields_row, text='应用页面', font=FONTS['small'], fg=COLORS['text_sub'], bg=COLORS['card_bg']).grid(row=0, column=0, sticky='w')
        ttk.Combobox(fields_row, textvariable=self.usage_log_page_var, values=list(self.usage_page_label_to_id.keys()), state='readonly', style='Modern.TCombobox').grid(row=1, column=0, sticky='ew', padx=(0, 10), pady=(6, 0), ipady=4)
        tk.Label(fields_row, text='请求状态', font=FONTS['small'], fg=COLORS['text_sub'], bg=COLORS['card_bg']).grid(row=0, column=1, sticky='w')
        ttk.Combobox(fields_row, textvariable=self.usage_log_status_var, values=list(self.usage_status_label_to_value.keys()), state='readonly', style='Modern.TCombobox').grid(row=1, column=1, sticky='ew', padx=(0, 10), pady=(6, 0), ipady=4)
        tk.Label(fields_row, text='搜索供应商', font=FONTS['small'], fg=COLORS['text_sub'], bg=COLORS['card_bg']).grid(row=0, column=2, sticky='w')
        provider_entry_shell, _provider_entry = self._create_usage_entry_field(fields_row, self.usage_log_provider_var)
        provider_entry_shell.grid(row=1, column=2, sticky='ew', padx=(0, 10), pady=(6, 0))
        tk.Label(fields_row, text='搜索模型', font=FONTS['small'], fg=COLORS['text_sub'], bg=COLORS['card_bg']).grid(row=0, column=3, sticky='w')
        model_entry_shell, _model_entry = self._create_usage_entry_field(fields_row, self.usage_log_model_var)
        model_entry_shell.grid(row=1, column=3, sticky='ew', pady=(6, 0))

        time_row_host = tk.Frame(filter_card.inner, bg=COLORS['card_bg'])
        time_row_host.pack(fill=tk.X, pady=(20, 10))

        time_row = tk.Frame(time_row_host, bg=COLORS['card_bg'])
        time_row.pack(fill=tk.X, pady=(2, 2))

        action_row = tk.Frame(time_row, bg=COLORS['card_bg'])
        action_row.pack(side=tk.RIGHT, anchor='e')

        time_fields_row = tk.Frame(time_row, bg=COLORS['card_bg'])
        time_fields_row.pack(side=tk.LEFT, anchor='w')

        start_label = ttk.Label(
            time_fields_row,
            text='开始时间',
            anchor='w',
        )
        start_field = self._create_usage_datetime_entry(
            time_fields_row,
            self.usage_log_start_var,
            '选择开始时间',
        )
        start_pick_button = ttk.Button(
            time_fields_row,
            text='选择',
            command=lambda: self._pick_usage_log_datetime(self.usage_log_start_var, '选择开始时间'),
            width=6,
        )

        end_label = ttk.Label(
            time_fields_row,
            text='结束时间',
            anchor='w',
        )
        end_field = self._create_usage_datetime_entry(
            time_fields_row,
            self.usage_log_end_var,
            '选择结束时间',
        )
        end_pick_button = ttk.Button(
            time_fields_row,
            text='选择',
            command=lambda: self._pick_usage_log_datetime(self.usage_log_end_var, '选择结束时间'),
            width=6,
        )

        clear_button = ttk.Button(
            action_row,
            text='清空日志',
            command=self._clear_usage_logs,
            width=10,
        )
        refresh_button = ttk.Button(
            action_row,
            text='刷新',
            command=self._refresh_usage_panel,
            width=6,
        )
        query_button = ttk.Button(
            action_row,
            text='查询',
            command=self._query_usage_logs,
            width=6,
        )
        time_controls = (
            (start_label, 0, (0, 12), 'w'),
            (start_field, 1, (0, 8), 'w'),
            (start_pick_button, 2, (0, 18), 'w'),
            (end_label, 3, (0, 12), 'w'),
            (end_field, 4, (0, 8), 'w'),
            (end_pick_button, 5, (0, 18), 'w'),
        )
        for widget, column_index, padx, sticky in time_controls:
            widget.grid(row=0, column=column_index, padx=padx, pady=(0, 2), sticky=sticky)
        clear_button.pack(side=tk.LEFT)
        refresh_button.pack(side=tk.LEFT, padx=(8, 0))
        query_button.pack(side=tk.LEFT, padx=(8, 0))
        time_row.after_idle(
            lambda row=time_row,
            fields=fields_row,
            card=filter_card.inner,
            parent_tab=parent: self._debug_usage_log_time_row_layout(row, fields, card, parent_tab)
        )

        table_card = CardFrame(parent, padding=12)
        table_card.pack(fill=tk.BOTH, expand=True)
        columns = (
            ('time', '时间', 150),
            ('provider', '供应商', 120),
            ('billed_model', '计费模型', 160),
            ('input_tokens', '输入', 80),
            ('output_tokens', '输出', 80),
            ('cache_hit_tokens', '缓存命中', 90),
            ('cache_create_tokens', '缓存创建', 90),
            ('billing_multiplier', '倍率', 60),
            ('total_cost', '总成本', 80),
            ('elapsed', '用时/首字', 90),
            ('status', '状态', 70),
        )
        self.usage_log_tree = self._create_usage_tree(table_card.inner, columns, height=10)
        self.usage_log_tree.bind('<ButtonRelease-1>', self._open_request_log_detail_from_click, add='+')
        self.usage_log_tree.bind('<Return>', self._open_selected_request_log_detail, add='+')

    def _build_usage_provider_tab(self, parent):
        card = CardFrame(parent, padding=12)
        card.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        columns = (
            ('provider', '供应商', 120),
            ('request_count', '请求数', 80),
            ('success_count', '成功', 80),
            ('error_count', '失败', 80),
            ('input_tokens', '输入', 90),
            ('output_tokens', '输出', 90),
            ('cache_hit_tokens', '缓存命中', 90),
            ('cache_create_tokens', '缓存创建', 90),
            ('total_cost', '总成本', 90),
            ('avg_duration_ms', '平均耗时', 90),
        )
        self.usage_provider_tree = self._create_usage_tree(card.inner, columns, height=12)

    def _build_usage_model_tab(self, parent):
        card = CardFrame(parent, padding=12)
        card.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        columns = (
            ('provider', '供应商', 120),
            ('model', '模型', 160),
            ('request_count', '请求数', 80),
            ('success_count', '成功', 80),
            ('error_count', '失败', 80),
            ('input_tokens', '输入', 90),
            ('output_tokens', '输出', 90),
            ('cache_hit_tokens', '缓存命中', 90),
            ('cache_create_tokens', '缓存创建', 90),
            ('total_cost', '总成本', 90),
            ('avg_duration_ms', '平均耗时', 90),
        )
        self.usage_model_tree = self._create_usage_tree(card.inner, columns, height=12)

    def _pick_usage_log_datetime(self, variable, title):
        value = ask_datetime_string(
            self.frame,
            title=title,
            initial_value=variable.get(),
        )
        if value:
            variable.set(value)

    def _create_usage_entry_field(self, parent, variable, *, readonly=False):
        shell = tk.Frame(parent, bg=COLORS['input_border'], bd=0, highlightthickness=0)
        body = tk.Frame(shell, bg=COLORS['input_bg'], bd=0, highlightthickness=0)
        body.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        entry_kwargs = {
            'textvariable': variable,
            'font': FONTS['body'],
            'fg': COLORS['text_main'],
            'relief': tk.FLAT,
            'bd': 0,
            'highlightthickness': 0,
            'insertbackground': COLORS['text_main'],
        }
        if readonly:
            entry_kwargs['state'] = 'readonly'
            entry_kwargs['readonlybackground'] = COLORS['input_bg']
        else:
            entry_kwargs['bg'] = COLORS['input_bg']

        entry = tk.Entry(body, **entry_kwargs)
        entry.pack(fill=tk.X, expand=True, padx=10, pady=6, ipady=2)
        return shell, entry

    def _create_usage_datetime_field(self, parent, variable, title, *, shell_width=None):
        shell_width = shell_width or self._get_usage_datetime_field_width()
        shell_height = 42
        shell = tk.Frame(parent, bg=COLORS['input_border'], bd=0, highlightthickness=0)
        shell.configure(width=shell_width, height=shell_height)
        shell._usage_fixed_width = shell_width
        shell._usage_fixed_height = shell_height
        shell.pack_propagate(False)
        shell.grid_propagate(False)
        body = tk.Frame(shell, bg=COLORS['input_bg'], bd=0, highlightthickness=0)
        body.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        def _open_picker(_event=None):
            self._pick_usage_log_datetime(variable, title)
            return 'break'

        value_entry = tk.Entry(
            body,
            textvariable=variable,
            font=FONTS['body'],
            fg=COLORS['text_main'],
            bg=COLORS['input_bg'],
            relief=tk.FLAT,
            bd=0,
            highlightthickness=0,
            justify='left',
            readonlybackground=COLORS['input_bg'],
            state='readonly',
            cursor='hand2',
        )
        value_entry.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)
        value_entry.bind('<Button-1>', _open_picker)
        body.bind('<Button-1>', _open_picker)
        return shell

    def _create_usage_datetime_entry(self, parent, variable, title):
        entry = ttk.Entry(
            parent,
            textvariable=variable,
            state='readonly',
            width=18,
            font=FONTS['body'],
        )
        entry.bind(
            '<Button-1>',
            lambda _event, current_var=variable, current_title=title: (
                self._pick_usage_log_datetime(current_var, current_title),
                'break'
            )[-1],
            add='+',
        )
        return entry

    def _create_usage_inline_button(self, parent, text, command, *, tone='secondary', font=None):
        font_spec = font or FONTS['small']
        font_obj = tkfont.Font(font=font_spec)
        shell_height = 42
        shell_width = max(font_obj.measure(text) + 28, 72)
        palette = {
            'secondary': {
                'border': COLORS['card_border'],
                'bg': COLORS['surface_alt'],
                'hover': COLORS['accent_light'],
                'fg': COLORS['text_main'],
            },
            'warning': {
                'border': COLORS['warning'],
                'bg': COLORS['warning'],
                'hover': COLORS['warning'],
                'fg': COLORS['text_main'],
            },
        }.get(tone, {
            'border': COLORS['card_border'],
            'bg': COLORS['surface_alt'],
            'hover': COLORS['accent_light'],
            'fg': COLORS['text_main'],
        })

        shell = tk.Frame(
            parent,
            bg=palette['border'],
            bd=0,
            highlightthickness=0,
            width=shell_width,
            height=shell_height,
        )
        shell._usage_fixed_width = shell_width
        shell._usage_fixed_height = shell_height
        shell.pack_propagate(False)
        label = tk.Label(
            shell,
            text=text,
            font=font_spec,
            fg=palette['fg'],
            bg=palette['bg'],
            bd=0,
            highlightthickness=0,
            cursor='hand2',
            anchor='center',
            justify='center',
        )

        def _set_bg(bg):
            try:
                label.configure(bg=bg)
            except tk.TclError:
                return

        def _invoke(_event=None):
            command()
            return 'break'

        for widget in (shell, label):
            widget.bind('<Enter>', lambda _event, bg=palette['hover']: _set_bg(bg), add='+')
            widget.bind('<Leave>', lambda _event, bg=palette['bg']: _set_bg(bg), add='+')
            widget.bind('<Button-1>', _invoke, add='+')

        self._layout_usage_inline_button(shell, label)
        shell.bind(
            '<Configure>',
            lambda _event, current_shell=shell, current_label=label: self._layout_usage_inline_button(
                current_shell,
                current_label,
            ),
            add='+',
        )
        return shell

    def _get_usage_datetime_field_width(self):
        display_font = tkfont.Font(font=FONTS['body'])
        text_width = display_font.measure('2026-12-31 23:59')
        return max(260, text_width + 32)

    def _get_usage_time_label_width(self, text):
        label_font = tkfont.Font(font=FONTS['small'])
        return max(label_font.measure(text) + 12, 72)

    def _debug_usage_log_time_row_layout(self, time_row, fields_row, card_inner, parent_tab, attempt=0):
        try:
            if (
                not time_row.winfo_ismapped()
                and attempt < 12
            ):
                time_row.after(
                    120,
                    lambda row=time_row,
                    fields=fields_row,
                    card=card_inner,
                    tab=parent_tab,
                    next_attempt=attempt + 1: self._debug_usage_log_time_row_layout(
                        row, fields, card, tab, next_attempt
                    ),
                )
                return
            targets = (
                ('parent_tab', parent_tab),
                ('card_inner', card_inner),
                ('fields_row', fields_row),
                ('time_row', time_row),
            )
            print(f'=== usage log time row debug begin attempt={attempt} ===')
            for name, widget in targets:
                print(
                    f'{name}: mapped={widget.winfo_ismapped()} '
                    f'manager={widget.winfo_manager()} '
                    f'x={widget.winfo_x()} y={widget.winfo_y()} '
                    f'w={widget.winfo_width()} h={widget.winfo_height()} '
                    f'req_w={widget.winfo_reqwidth()} req_h={widget.winfo_reqheight()}'
                )
            for index, child in enumerate(time_row.winfo_children()):
                print(
                    f'time_row.child[{index}]: class={child.winfo_class()} '
                    f'manager={child.winfo_manager()} '
                    f'x={child.winfo_x()} y={child.winfo_y()} '
                    f'w={child.winfo_width()} h={child.winfo_height()} '
                    f'req_w={child.winfo_reqwidth()} req_h={child.winfo_reqheight()}'
                )
                for inner_index, inner in enumerate(child.winfo_children()):
                    text = ''
                    try:
                        text = inner.cget('text')
                    except tk.TclError:
                        text = ''
                    print(
                        f'  child[{index}].inner[{inner_index}]: class={inner.winfo_class()} '
                        f'text={text!r} manager={inner.winfo_manager()} '
                        f'x={inner.winfo_x()} y={inner.winfo_y()} '
                        f'w={inner.winfo_width()} h={inner.winfo_height()} '
                        f'req_w={inner.winfo_reqwidth()} req_h={inner.winfo_reqheight()}'
                    )
            print('=== usage log time row debug end ===')
        except tk.TclError:
            return

    def _create_usage_tree(self, parent, columns, height=8):
        shell = tk.Frame(parent, bg=COLORS['card_bg'])
        shell.pack(fill=tk.BOTH, expand=True)
        tree = ttk.Treeview(shell, columns=[column[0] for column in columns], show='headings', height=height, selectmode='browse')
        y_scroll = ttk.Scrollbar(shell, orient=tk.VERTICAL, command=tree.yview, style='Thin.Vertical.TScrollbar')
        x_scroll = ttk.Scrollbar(shell, orient=tk.HORIZONTAL, command=tree.xview, style='Thin.Horizontal.TScrollbar')
        tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        for key, title, width in columns:
            tree.heading(key, text=title)
            tree.column(key, width=width, minwidth=width, anchor='center', stretch=True)

        tree.grid(row=0, column=0, sticky='nsew')
        y_scroll.grid(row=0, column=1, sticky='ns')
        x_scroll.grid(row=1, column=0, sticky='ew')
        shell.grid_rowconfigure(0, weight=1)
        shell.grid_columnconfigure(0, weight=1)
        return tree

    def _relayout_usage_summary(self, _event=None):
        if not self.usage_summary_row:
            return
        cards = list(self.usage_summary_cards or [])
        if not cards:
            return
        for card in cards:
            card.grid_forget()
        columns = len(cards)
        for index in range(columns):
            self.usage_summary_row.grid_columnconfigure(index, weight=1, minsize=0, uniform='usage_summary')
            self.usage_summary_row.grid_rowconfigure(index, weight=0)
        self.usage_summary_row.grid_rowconfigure(0, weight=1)
        for index, card in enumerate(cards):
            padx = (0, 12 if index < columns - 1 else 0)
            card.grid(row=0, column=index, sticky='nsew', padx=padx, pady=0)

    def _build_usage_summary_cards(self):
        if not self.usage_summary_row:
            return
        for child in self.usage_summary_row.winfo_children():
            child.destroy()

        self._usage_summary_cards_ready = True
        self.usage_summary_cards = []
        self.usage_summary_labels = {}
        summary_specs = (
            ('total_requests', '请求数', ''),
            ('total_cost', '总成本', ''),
            ('total_tokens', '总 Token 数', '输入 Token：0\n输出 Token：0'),
            ('cache_tokens', '缓存 Token', '缓存创建：0\n缓存命中：0'),
        )
        for key, title, detail_text in summary_specs:
            card = CardFrame(self.usage_summary_row, padding=14)
            title_shell = tk.Frame(card.inner, bg=COLORS['card_bg'])
            title_shell.pack(fill=tk.X, anchor='n')
            title_label = tk.Label(
                title_shell,
                text=title,
                font=FONTS['body_bold'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                justify='left',
                anchor='w',
            )
            title_label.pack(fill=tk.X, anchor='w')
            bind_adaptive_wrap(title_label, title_shell, padding=8, min_width=120)

            value_shell = tk.Frame(card.inner, bg=COLORS['card_bg'])
            value_shell.pack(fill=tk.X, anchor='n', pady=(12, 10))
            value_label = tk.Label(
                value_shell,
                text='0',
                font=(FONTS['hero'][0], 20, 'bold'),
                fg=COLORS['text_main'],
                bg=COLORS['card_bg'],
                justify='left',
                anchor='w',
            )
            value_label.pack(fill=tk.X, anchor='nw')
            self.usage_summary_labels[key] = {'value': value_label}

            detail_shell = tk.Frame(card.inner, bg=COLORS['card_bg'])
            detail_shell.pack(fill=tk.X, anchor='n')
            detail_label = tk.Label(
                detail_shell,
                text=detail_text,
                font=FONTS['small'],
                fg=COLORS['text_sub'],
                bg=COLORS['card_bg'],
                justify='left',
                anchor='nw',
            )
            detail_label.pack(fill=tk.X, anchor='nw')
            bind_adaptive_wrap(detail_label, detail_shell, padding=8, min_width=120)
            self.usage_summary_labels[key]['detail'] = detail_label
            self.usage_summary_cards.append(card)

    def _ensure_usage_summary_cards(self, force_rebuild=False):
        if not self.usage_summary_row:
            return False
        if force_rebuild or not self._usage_summary_cards_ready or not self.usage_summary_cards:
            self._build_usage_summary_cards()
            self._relayout_usage_summary()
            return True
        return False

    def _schedule_usage_layout_stabilize(self, delay_ms=0):
        if self._usage_layout_after_id is not None:
            try:
                self.frame.after_cancel(self._usage_layout_after_id)
            except tk.TclError:
                pass
            self._usage_layout_after_id = None
        try:
            self._usage_layout_after_id = self.frame.after(delay_ms, self._stabilize_usage_layout)
        except tk.TclError:
            self._usage_layout_after_id = None

    def _stabilize_usage_layout(self):
        self._usage_layout_after_id = None
        try:
            if not self.frame.winfo_exists():
                return
            self.frame.update_idletasks()
        except tk.TclError:
            return
        if self.frame.winfo_viewable():
            self._ensure_usage_summary_cards()
        self._relayout_usage_summary()
        self._refresh_usage_panel()

    def _build_usage_pricing_panel(self):
        shell = CardFrame(self.notice_card.inner, padding=14)
        shell.pack(fill=tk.X, pady=(18, 0))

        header = tk.Frame(shell.inner, bg=COLORS['card_bg'])
        header.pack(fill=tk.X)
        header.grid_columnconfigure(0, weight=1)
        title_shell = tk.Frame(header, bg=COLORS['card_bg'])
        title_shell.grid(row=0, column=0, sticky='ew')
        tk.Label(
            title_shell,
            text='成本定价',
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
        ).pack(anchor='w')
        tk.Label(
            title_shell,
            text='按供应商 + 模型精确匹配，价格单位为每百万 Token。',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
        ).pack(anchor='w', pady=(6, 0))

        pricing_toggle_shell, self.pricing_toggle_button = self._create_dashboard_shell_button(
            header,
            '展开',
            style='secondary',
            command=self._toggle_pricing_panel,
            padx=14,
            pady=8,
            font=FONTS['body_bold'],
        )
        pricing_toggle_shell.grid(row=0, column=1, sticky='ne', padx=(12, 0))

        self.pricing_panel_body = tk.Frame(shell.inner, bg=COLORS['card_bg'])

        table_shell = CardFrame(self.pricing_panel_body, padding=10)
        table_shell.pack(fill=tk.X, pady=(14, 12))
        columns = (
            ('provider', '供应商', 120),
            ('model', '模型', 180),
            ('input_price', '输入单价', 90),
            ('output_price', '输出单价', 90),
            ('cache_create_price', '缓存创建', 90),
            ('cache_hit_price', '缓存命中', 90),
            ('enabled', '启用', 70),
        )
        self.pricing_rule_tree = self._create_usage_tree(table_shell.inner, columns, height=6)
        self.pricing_rule_tree.bind('<<TreeviewSelect>>', self._load_selected_pricing_rule)

        form = tk.Frame(self.pricing_panel_body, bg=COLORS['card_bg'])
        form.pack(fill=tk.X)
        for index in range(4):
            form.grid_columnconfigure(index, weight=1)

        self.pricing_provider_var = tk.StringVar(value='')
        self.pricing_model_var = tk.StringVar(value='')
        self.pricing_input_price_var = tk.StringVar(value='0')
        self.pricing_output_price_var = tk.StringVar(value='0')
        self.pricing_cache_create_var = tk.StringVar(value='0')
        self.pricing_cache_hit_var = tk.StringVar(value='0')
        self.pricing_enabled_var = tk.BooleanVar(value=True)

        def _entry(parent, variable):
            shell, _entry_widget = self._create_usage_entry_field(parent, variable)
            return shell

        tk.Label(form, text='供应商', font=FONTS['small'], fg=COLORS['text_sub'], bg=COLORS['card_bg']).grid(row=0, column=0, sticky='w')
        _entry(form, self.pricing_provider_var).grid(row=1, column=0, sticky='ew', padx=(0, 10), pady=(6, 10))
        tk.Label(form, text='模型', font=FONTS['small'], fg=COLORS['text_sub'], bg=COLORS['card_bg']).grid(row=0, column=1, sticky='w')
        _entry(form, self.pricing_model_var).grid(row=1, column=1, sticky='ew', padx=(0, 10), pady=(6, 10))
        tk.Label(form, text='输入单价', font=FONTS['small'], fg=COLORS['text_sub'], bg=COLORS['card_bg']).grid(row=0, column=2, sticky='w')
        _entry(form, self.pricing_input_price_var).grid(row=1, column=2, sticky='ew', padx=(0, 10), pady=(6, 10))
        tk.Label(form, text='输出单价', font=FONTS['small'], fg=COLORS['text_sub'], bg=COLORS['card_bg']).grid(row=0, column=3, sticky='w')
        _entry(form, self.pricing_output_price_var).grid(row=1, column=3, sticky='ew', pady=(6, 10))

        tk.Label(form, text='缓存创建', font=FONTS['small'], fg=COLORS['text_sub'], bg=COLORS['card_bg']).grid(row=2, column=0, sticky='w')
        _entry(form, self.pricing_cache_create_var).grid(row=3, column=0, sticky='ew', padx=(0, 10), pady=(6, 0))
        tk.Label(form, text='缓存命中', font=FONTS['small'], fg=COLORS['text_sub'], bg=COLORS['card_bg']).grid(row=2, column=1, sticky='w')
        _entry(form, self.pricing_cache_hit_var).grid(row=3, column=1, sticky='ew', padx=(0, 10), pady=(6, 0))

        enabled_shell = tk.Frame(form, bg=COLORS['card_bg'])
        enabled_shell.grid(row=3, column=2, sticky='w', pady=(6, 0))
        tk.Checkbutton(
            enabled_shell,
            text='启用规则',
            variable=self.pricing_enabled_var,
            font=FONTS['body'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
            activebackground=COLORS['card_bg'],
            selectcolor=COLORS['card_bg'],
        ).pack(anchor='w')

        action_shell = tk.Frame(form, bg=COLORS['card_bg'])
        action_shell.grid(row=3, column=3, sticky='e', pady=(6, 0))
        clear_shell, _clear_button = self._create_dashboard_shell_button(
            action_shell,
            '清空',
            style='secondary',
            command=self._clear_pricing_rule_form,
            padx=12,
            pady=8,
            font=FONTS['body_bold'],
        )
        clear_shell.pack(side=tk.RIGHT)
        delete_shell, _delete_button = self._create_dashboard_shell_button(
            action_shell,
            '删除',
            style='secondary',
            command=self._delete_pricing_rule,
            padx=12,
            pady=8,
            font=FONTS['body_bold'],
        )
        delete_shell.pack(side=tk.RIGHT, padx=(0, 8))
        save_shell, _save_button = self._create_dashboard_shell_button(
            action_shell,
            '保存',
            style='primary_fixed',
            command=self._save_pricing_rule,
            padx=12,
            pady=8,
            font=FONTS['body_bold'],
            border_color=THEMES['light']['card_border'],
        )
        save_shell.pack(side=tk.RIGHT, padx=(0, 8))

    def _set_usage_period(self, key):
        self.usage_period_key = key
        self._refresh_usage_period_styles()
        self._refresh_usage_panel()

    def _refresh_usage_period_styles(self):
        for key, button in self.usage_period_buttons.items():
            if key == self.usage_period_key:
                button.set_style('primary')
            else:
                button.set_style('secondary')

    def _get_usage_store(self):
        return getattr(self.api, 'usage_store', None)

    def _draw_usage_chart(self, trend=None):
        if not self.usage_chart_canvas:
            return
        trend = dict(trend or self._usage_trend_cache or {})
        if not trend:
            return
        canvas = self.usage_chart_canvas
        width = max(canvas.winfo_width(), 640)
        height = max(canvas.winfo_height(), 300)
        labels = tuple(trend.get('labels', []))
        series = trend.get('series', {})
        render_signature = (
            width,
            height,
            trend.get('caption', ''),
            labels,
            COLORS['card_bg'],
            COLORS['card_border'],
            COLORS['divider'],
            COLORS['text_sub'],
            tuple(series.get('cost', [])),
            tuple(series.get('cache_create', [])),
            tuple(series.get('cache_hit', [])),
            tuple(series.get('input', [])),
            tuple(series.get('output', [])),
        )
        if render_signature == self._usage_chart_last_signature:
            return
        self._usage_chart_last_signature = render_signature

        canvas.delete('all')
        left = 48
        right = width - 56
        top = 18

        token_max = max(int(trend.get('token_max', 0) or 0), 1)
        cost_max = max(float(trend.get('cost_max', 0.0) or 0.0), 1.0)
        colors = {
            'cost': '#FF4D6D',
            'cache_create': '#FF7A00',
            'cache_hit': '#9B5CFF',
            'input': '#2E61F2',
            'output': '#2F9E44',
        }
        legend_specs = (
            ('cost', '成本'),
            ('cache_create', '缓存创建'),
            ('cache_hit', '缓存命中'),
            ('input', '输入'),
            ('output', '输出'),
        )
        legend_font = tkfont.Font(font=FONTS['small'])
        axis_font = tkfont.Font(font=FONTS['tiny'])
        legend_line_width = 14
        legend_text_gap = 8
        legend_gap_x = 18
        legend_gap_y = 8
        legend_available_width = max(right - left, 240)
        legend_rows = [[]]
        current_row_width = 0
        for key, label in legend_specs:
            item_width = legend_line_width + legend_text_gap + legend_font.measure(label) + 12
            required_width = item_width if not legend_rows[-1] else item_width + legend_gap_x
            if legend_rows[-1] and current_row_width + required_width > legend_available_width:
                legend_rows.append([])
                current_row_width = 0
                required_width = item_width
            legend_rows[-1].append((key, label, item_width))
            current_row_width += required_width
        legend_line_height = max(legend_font.metrics('linespace'), 16)
        axis_label_height = max(axis_font.metrics('linespace'), 12)
        legend_height = len(legend_rows) * legend_line_height + max(len(legend_rows) - 1, 0) * legend_gap_y
        bottom = height - (legend_height + axis_label_height + 80)
        bottom = max(bottom, top + 80)

        canvas.create_rectangle(left, top, right, bottom, outline=COLORS['card_border'], width=1)
        for index in range(5):
            y = top + (bottom - top) * index / 4
            canvas.create_line(left, y, right, y, fill=COLORS['divider'], dash=(3, 4))
            token_value = int(token_max * (4 - index) / 4)
            cost_value = cost_max * (4 - index) / 4
            canvas.create_text(left - 8, y, text=format_token_count(token_value), anchor='e', fill=COLORS['text_sub'], font=FONTS['tiny'])
            canvas.create_text(right + 8, y, text=f'${cost_value:.0f}' if cost_max >= 1 else f'${cost_value:.2f}', anchor='w', fill=COLORS['text_sub'], font=FONTS['tiny'])

        point_count = max(len(labels), 1)
        x_step = (right - left) / max(point_count - 1, 1)
        x_positions = [left + index * x_step for index in range(point_count)]
        max_label_count = max(int((right - left) / 96), 2)
        label_step = max((len(labels) + max_label_count - 1) // max_label_count, 1)
        for index, label in enumerate(labels):
            if index % label_step != 0 and index != len(labels) - 1:
                continue
            label_text = label
            if self.usage_period_key == '24h' and ' ' in label:
                label_text = label.split(' ')[-1]
            canvas.create_text(
                x_positions[index],
                bottom + 16,
                text=label_text,
                anchor='n',
                fill=COLORS['text_sub'],
                font=FONTS['tiny'],
            )

        def _draw_line(values, maximum, color):
            if not values:
                return
            points = []
            max_value = max(float(maximum or 1), 1.0)
            for index, value in enumerate(values):
                ratio = min(max(float(value or 0) / max_value, 0.0), 1.0)
                x = x_positions[index]
                y = bottom - (bottom - top) * ratio
                points.extend((x, y))
            if len(points) >= 4:
                canvas.create_line(*points, fill=color, width=2)
            elif len(points) == 2:
                canvas.create_oval(points[0] - 2, points[1] - 2, points[0] + 2, points[1] + 2, fill=color, outline=color)

        _draw_line(series.get('cost', []), cost_max, colors['cost'])
        _draw_line(series.get('cache_create', []), token_max, colors['cache_create'])
        _draw_line(series.get('cache_hit', []), token_max, colors['cache_hit'])
        _draw_line(series.get('input', []), token_max, colors['input'])
        _draw_line(series.get('output', []), token_max, colors['output'])

        legend_y = bottom + axis_label_height + 60
        for row in legend_rows:
            row_width = 0
            for index, (_key, _label, item_width) in enumerate(row):
                row_width += item_width
                if index < len(row) - 1:
                    row_width += legend_gap_x
            legend_x = left + max((legend_available_width - row_width) / 2, 0)
            for key, label, item_width in row:
                color = colors[key]
                canvas.create_line(legend_x, legend_y, legend_x + legend_line_width, legend_y, fill=color, width=2)
                canvas.create_text(
                    legend_x + legend_line_width + legend_text_gap,
                    legend_y,
                    text=label,
                    anchor='w',
                    fill=color,
                    font=FONTS['small'],
                )
                legend_x += item_width + legend_gap_x
            legend_y += legend_line_height + legend_gap_y

        if self.usage_chart_caption_label is not None:
            self.usage_chart_caption_label.configure(text=trend.get('caption', ''))

    def _refresh_usage_panel(self):
        store = self._get_usage_store()
        if store is None:
            return
        if not self.usage_summary_cards:
            if not self.frame.winfo_viewable():
                return
            self._ensure_usage_summary_cards()

        snapshot = self._build_usage_query_snapshot()
        self._usage_refresh_token += 1
        refresh_token = self._usage_refresh_token

        self.usage_task_runner.run(
            work=lambda: self._collect_usage_panel_data(store, snapshot),
            on_success=lambda payload, token=refresh_token: self._apply_usage_panel_data(payload, token),
            on_error=lambda exc, token=refresh_token: self._handle_usage_refresh_error(exc, token),
        )

    def _build_usage_query_snapshot(self):
        return {
            'period_key': self.usage_period_key,
            'page_id': self.usage_page_label_to_id.get(self.usage_log_page_var.get(), ''),
            'status': self.usage_status_label_to_value.get(self.usage_log_status_var.get(), ''),
            'provider_keyword': self.usage_log_provider_var.get(),
            'model_keyword': self.usage_log_model_var.get(),
            'start_text': self.usage_log_start_var.get(),
            'end_text': self.usage_log_end_var.get(),
        }

    def _query_usage_logs(self, _event=None):
        self._refresh_usage_panel()
        return 'break'

    @staticmethod
    def _collect_usage_panel_data(store, snapshot):
        period_key = snapshot['period_key']
        return {
            'summary': store.summarize(period_key),
            'trend': store.build_trends(period_key),
            'request_rows': store.query_events(
                period_key,
                page_id=snapshot['page_id'],
                status=snapshot['status'],
                provider_keyword=snapshot['provider_keyword'],
                model_keyword=snapshot['model_keyword'],
                start_text=snapshot['start_text'],
                end_text=snapshot['end_text'],
            ),
            'provider_rows': store.provider_stats(period_key),
            'model_rows': store.model_stats(period_key),
        }

    def _apply_usage_panel_data(self, payload, refresh_token):
        if refresh_token != self._usage_refresh_token:
            return
        summary = dict(payload.get('summary') or {})
        trend = dict(payload.get('trend') or {})
        request_rows = list(payload.get('request_rows') or [])
        provider_rows = list(payload.get('provider_rows') or [])
        model_rows = list(payload.get('model_rows') or [])

        self.usage_summary_labels['total_requests']['value'].configure(text=str(summary['total_requests']))
        self.usage_summary_labels['total_cost']['value'].configure(text=format_currency(summary['total_cost']))
        self.usage_summary_labels['total_tokens']['value'].configure(text=format_token_count(summary['total_tokens']))
        self.usage_summary_labels['total_tokens']['detail'].configure(
            text=(
                f'输入 Token：{format_token_count(summary["input_tokens"])}\n'
                f'输出 Token：{format_token_count(summary["output_tokens"])}'
            )
        )
        cache_total = summary['cache_create_tokens'] + summary['cache_hit_tokens']
        self.usage_summary_labels['cache_tokens']['value'].configure(text=format_token_count(cache_total))
        self.usage_summary_labels['cache_tokens']['detail'].configure(
            text=(
                f'缓存创建：{format_token_count(summary["cache_create_tokens"])}\n'
                f'缓存命中：{format_token_count(summary["cache_hit_tokens"])}'
            )
        )

        self._usage_trend_cache = trend
        self._draw_usage_chart(trend)
        self._refresh_request_logs(rows=request_rows)
        self._refresh_provider_stats(rows=provider_rows)
        self._refresh_model_stats(rows=model_rows)
        self._refresh_pricing_rules()

    def _handle_usage_refresh_error(self, exc, refresh_token):
        if refresh_token != self._usage_refresh_token:
            return
        self.set_status(f'用量统计刷新失败：{exc}', COLORS['warning'])

    def _refresh_request_logs(self, rows=None):
        if not self.usage_log_tree:
            return
        rows = list(rows or [])
        tree = self.usage_log_tree
        self.usage_log_row_map = {}
        tree.delete(*tree.get_children())
        for item in rows:
            item_id = tree.insert(
                '',
                'end',
                values=(
                    item.get('timestamp', ''),
                    item.get('provider', ''),
                    item.get('billed_model', ''),
                    format_token_count(item.get('input_tokens', 0)),
                    format_token_count(item.get('output_tokens', 0)),
                    format_token_count(item.get('cache_hit_tokens', 0)),
                    format_token_count(item.get('cache_create_tokens', 0)),
                    f'{float(item.get("billing_multiplier", 1.0) or 1.0):.2f}',
                    format_currency(item.get('total_cost', 0.0)),
                    f'{int(item.get("duration_ms", 0) or 0)}ms / --',
                    '成功' if item.get('status') == 'success' else '失败',
                ),
            )
            self.usage_log_row_map[item_id] = dict(item)
        self._scroll_usage_log_to_latest()

    def _scroll_usage_log_to_latest(self):
        tree = self.usage_log_tree
        if not tree:
            return
        try:
            children = tree.get_children()
            tree.yview_moveto(0)
            if children:
                tree.see(children[0])
        except tk.TclError:
            return

    def _open_request_log_detail_from_click(self, event=None):
        if not self.usage_log_tree or event is None:
            return
        item_id = self.usage_log_tree.identify_row(event.y)
        if not item_id:
            return
        self.usage_log_tree.selection_set(item_id)
        self.usage_log_tree.focus(item_id)
        self._show_request_log_detail(item_id)

    def _open_selected_request_log_detail(self, _event=None):
        if not self.usage_log_tree:
            return
        selection = self.usage_log_tree.selection()
        if not selection:
            return
        self._show_request_log_detail(selection[0])

    @staticmethod
    def _format_request_log_value(value):
        if value in (None, '', [], {}):
            return ''
        if isinstance(value, (list, tuple)):
            return ', '.join(str(item) for item in value if str(item).strip())
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        return str(value)

    def _build_request_log_section_text(self, section, ordered_fields):
        payload = dict(section or {})
        if not payload:
            return '无'
        lines = []
        used_keys = set()
        multiline_keys = {
            'headers_text',
            'body_text',
            'prompt_text',
            'system_text',
            'text_preview',
            'body_preview',
            'message',
            'transport_message',
        }
        for key, label in ordered_fields:
            value = self._format_request_log_value(payload.get(key))
            if not value:
                continue
            used_keys.add(key)
            if key in multiline_keys or '\n' in value:
                lines.append(f'{label}:\n{value}')
            else:
                lines.append(f'{label}: {value}')
        for key in sorted(payload.keys()):
            if key in used_keys:
                continue
            value = self._format_request_log_value(payload.get(key))
            if not value:
                continue
            label = str(key).replace('_', ' ')
            if '\n' in value:
                lines.append(f'{label}:\n{value}')
            else:
                lines.append(f'{label}: {value}')
        return '\n\n'.join(lines) if lines else '无'

    def _build_request_log_overview_text(self, row):
        item = dict(row or {})
        detail = dict(item.get('request_detail') or {})
        summary = dict(detail.get('summary') or {})
        page_label = item.get('page_label', '') or summary.get('page_id', '') or '未分类'
        status_text = '成功' if item.get('status') == 'success' else '失败'
        lines = [
            f'请求 ID: {summary.get("request_id", "") or item.get("request_id", "") or "-"}',
            f'时间: {item.get("timestamp", "") or "-"}',
            f'状态: {status_text}',
            f'应用页面: {page_label}',
            f'场景 ID: {summary.get("scene_id", "") or item.get("scene_id", "") or "-"}',
            f'动作: {summary.get("action", "") or item.get("action", "") or "-"}',
            f'API ID: {summary.get("api_id", "") or item.get("api_id", "") or "-"}',
            f'供应商: {item.get("provider", "") or summary.get("provider", "") or "-"}',
            f'请求模型: {item.get("request_model", "") or summary.get("request_model", "") or "-"}',
            f'返回模型: {item.get("response_model", "") or summary.get("response_model", "") or "-"}',
            f'计费模型: {item.get("billed_model", "") or "-"}',
            f'耗时: {int(item.get("duration_ms", 0) or 0)} ms',
            f'输入 Token: {format_token_count(item.get("input_tokens", 0))}',
            f'输出 Token: {format_token_count(item.get("output_tokens", 0))}',
            f'缓存命中: {format_token_count(item.get("cache_hit_tokens", 0))}',
            f'缓存创建: {format_token_count(item.get("cache_create_tokens", 0))}',
            f'成本倍率: {float(item.get("billing_multiplier", 1.0) or 1.0):.2f}',
            f'总成本: {format_currency(item.get("total_cost", 0.0))}',
        ]
        error_message = str(item.get('error_message', '') or '').strip()
        if error_message:
            lines.append('')
            lines.append(f'错误摘要:\n{error_message}')
        return '\n'.join(lines)

    def _append_request_log_text_tab(self, notebook, title, text):
        tab = tk.Frame(notebook, bg=COLORS['card_bg'])
        notebook.add(tab, text=title)
        shell, content = create_scrolled_text(
            tab,
            height=24,
            show_scrollbar=True,
            bg=COLORS['input_bg'],
            fg=COLORS['text_main'],
            wrap=tk.WORD,
        )
        shell.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        content.insert('1.0', text or '无')
        content.configure(state='disabled')

    def _show_request_log_detail(self, item_id):
        row = dict(self.usage_log_row_map.get(item_id) or {})
        if not row:
            return
        detail = dict(row.get('request_detail') or {})
        request_text = self._build_request_log_section_text(
            detail.get('request', {}),
            (
                ('method', '请求方法'),
                ('url', '请求地址'),
                ('timeout_sec', '超时秒数'),
                ('auth_field', '鉴权字段'),
                ('request_model', '请求模型'),
                ('model_mapping_hit', '命中模型映射'),
                ('use_bearer', '使用 Bearer'),
                ('compatibility_rules', '兼容规则'),
                ('extra_json_keys', '额外 JSON 字段'),
                ('ignored_extra_json_keys', '忽略的额外 JSON 字段'),
                ('removed_extra_json_keys', '移除的额外 JSON 字段'),
                ('extra_header_keys', '额外请求头'),
                ('ignored_extra_header_keys', '忽略的额外请求头'),
                ('headers_text', '请求头'),
                ('body_text', '请求体'),
                ('prompt_text', '测试提示词'),
                ('system_text', '系统提示词'),
            ),
        )
        response_text = self._build_request_log_section_text(
            detail.get('response', {}),
            (
                ('status_code', '状态码'),
                ('response_model', '返回模型'),
                ('text_source', '文本来源'),
                ('content_kind', '内容类型'),
                ('has_choices', '包含候选项'),
                ('has_output_text', '包含输出文本'),
                ('response_keys', '响应字段'),
                ('block_reason', '阻断原因'),
                ('finish_reasons', '结束原因'),
                ('text_preview', '文本预览'),
                ('body_preview', '响应体预览'),
                ('body_text', '响应体'),
            ),
        )
        error_section = dict(detail.get('error') or {})
        if row.get('error_message') and not error_section.get('message'):
            error_section['message'] = row.get('error_message')
        error_text = self._build_request_log_section_text(
            error_section,
            (
                ('message', '错误信息'),
                ('transport_message', '传输层信息'),
            ),
        )

        win = tk.Toplevel(self.frame)
        win.title('请求详情')
        win.configure(bg=COLORS['bg_main'])
        win.transient(self.frame.winfo_toplevel())
        win.grab_set()
        apply_adaptive_window_geometry(win, '1280x960')

        header = tk.Frame(win, bg=COLORS['bg_main'])
        header.pack(fill=tk.X, padx=18, pady=(16, 8))
        tk.Label(
            header,
            text='请求详情',
            font=FONTS['subtitle'],
            fg=COLORS['primary'],
            bg=COLORS['bg_main'],
        ).pack(side=tk.LEFT)
        ModernButton(
            header,
            '关闭',
            style='secondary',
            command=win.destroy,
            padx=12,
            pady=6,
        ).pack(side=tk.RIGHT)

        overview_card = CardFrame(win, padding=14)
        overview_card.pack(fill=tk.X, padx=18, pady=(0, 12))
        overview_shell, overview_text = create_scrolled_text(
            overview_card.inner,
            height=10,
            show_scrollbar=True,
            bg=COLORS['card_bg'],
            fg=COLORS['text_main'],
            wrap=tk.WORD,
        )
        overview_shell.pack(fill=tk.X, anchor='w')
        overview_text.insert('1.0', self._build_request_log_overview_text(row))
        overview_text.configure(state='disabled')

        notebook = ttk.Notebook(win, style='Card.TNotebook')
        notebook.pack(fill=tk.BOTH, expand=True, padx=18, pady=(0, 18))
        self._append_request_log_text_tab(notebook, '概览', self._build_request_log_overview_text(row))
        self._append_request_log_text_tab(notebook, '请求', request_text)
        self._append_request_log_text_tab(notebook, '响应', response_text)
        self._append_request_log_text_tab(notebook, '错误', error_text)

    def _refresh_provider_stats(self, rows=None):
        if not self.usage_provider_tree:
            return
        rows = list(rows or [])
        tree = self.usage_provider_tree
        tree.delete(*tree.get_children())
        for item in rows:
            tree.insert(
                '',
                'end',
                values=(
                    item.get('provider', ''),
                    item.get('request_count', 0),
                    item.get('success_count', 0),
                    item.get('error_count', 0),
                    format_token_count(item.get('input_tokens', 0)),
                    format_token_count(item.get('output_tokens', 0)),
                    format_token_count(item.get('cache_hit_tokens', 0)),
                    format_token_count(item.get('cache_create_tokens', 0)),
                    format_currency(item.get('total_cost', 0.0)),
                    f'{int(item.get("avg_duration_ms", 0) or 0)}ms',
                ),
            )

    def _refresh_model_stats(self, rows=None):
        if not self.usage_model_tree:
            return
        rows = list(rows or [])
        tree = self.usage_model_tree
        tree.delete(*tree.get_children())
        for item in rows:
            tree.insert(
                '',
                'end',
                values=(
                    item.get('provider', ''),
                    item.get('model', ''),
                    item.get('request_count', 0),
                    item.get('success_count', 0),
                    item.get('error_count', 0),
                    format_token_count(item.get('input_tokens', 0)),
                    format_token_count(item.get('output_tokens', 0)),
                    format_token_count(item.get('cache_hit_tokens', 0)),
                    format_token_count(item.get('cache_create_tokens', 0)),
                    format_currency(item.get('total_cost', 0.0)),
                    f'{int(item.get("avg_duration_ms", 0) or 0)}ms',
                ),
            )

    def _toggle_pricing_panel(self):
        self.pricing_expanded = not self.pricing_expanded
        if self.pricing_expanded:
            self.pricing_panel_body.pack(fill=tk.X, pady=(12, 0))
            self.pricing_toggle_button.configure(text='收起')
        else:
            self.pricing_panel_body.pack_forget()
            self.pricing_toggle_button.configure(text='展开')

    def _refresh_pricing_rules(self):
        if not self.pricing_rule_tree:
            return
        tree = self.pricing_rule_tree
        tree.delete(*tree.get_children())
        for rule in self.config.get_usage_pricing_rules():
            item_id = f'{rule["provider"]}::{rule["model"]}'
            tree.insert('', 'end', iid=item_id, values=(rule['provider'], rule['model'], rule['input_price'], rule['output_price'], rule['cache_create_price'], rule['cache_hit_price'], '是' if rule.get('enabled', True) else '否'))

    def _load_selected_pricing_rule(self, _event=None):
        if not self.pricing_rule_tree:
            return
        selected = self.pricing_rule_tree.selection()
        if not selected:
            return
        provider, model = selected[0].split('::', 1)
        for rule in self.config.get_usage_pricing_rules():
            if rule['provider'] == provider and rule['model'] == model:
                self.pricing_provider_var.set(rule['provider'])
                self.pricing_model_var.set(rule['model'])
                self.pricing_input_price_var.set(str(rule['input_price']))
                self.pricing_output_price_var.set(str(rule['output_price']))
                self.pricing_cache_create_var.set(str(rule['cache_create_price']))
                self.pricing_cache_hit_var.set(str(rule['cache_hit_price']))
                self.pricing_enabled_var.set(bool(rule.get('enabled', True)))
                self.pricing_edit_key = (rule['provider'].lower(), rule['model'].lower())
                break

    def _clear_pricing_rule_form(self):
        self.pricing_provider_var.set('')
        self.pricing_model_var.set('')
        self.pricing_input_price_var.set('0')
        self.pricing_output_price_var.set('0')
        self.pricing_cache_create_var.set('0')
        self.pricing_cache_hit_var.set('0')
        self.pricing_enabled_var.set(True)
        self.pricing_edit_key = None
        if self.pricing_rule_tree:
            self.pricing_rule_tree.selection_remove(self.pricing_rule_tree.selection())

    @staticmethod
    def _parse_price_value(text):
        value = str(text or '').strip()
        try:
            parsed = float(value or 0)
        except Exception:
            return None
        return parsed if parsed >= 0 else None

    def _save_pricing_rule(self):
        provider = str(self.pricing_provider_var.get() or '').strip()
        model = str(self.pricing_model_var.get() or '').strip()
        input_price = self._parse_price_value(self.pricing_input_price_var.get())
        output_price = self._parse_price_value(self.pricing_output_price_var.get())
        cache_create_price = self._parse_price_value(self.pricing_cache_create_var.get())
        cache_hit_price = self._parse_price_value(self.pricing_cache_hit_var.get())
        if not provider or not model:
            messagebox.showwarning('提示', '请先填写供应商和模型名称。', parent=self.frame)
            return
        if None in {input_price, output_price, cache_create_price, cache_hit_price}:
            messagebox.showwarning('提示', '价格必须是大于等于 0 的数字。', parent=self.frame)
            return

        rules = self.config.get_usage_pricing_rules()
        updated = []
        replaced = False
        current_key = self.pricing_edit_key
        new_key = (provider.lower(), model.lower())
        for rule in rules:
            rule_key = (rule['provider'].lower(), rule['model'].lower())
            if current_key and rule_key == current_key:
                updated.append({'provider': provider, 'model': model, 'input_price': input_price, 'output_price': output_price, 'cache_create_price': cache_create_price, 'cache_hit_price': cache_hit_price, 'enabled': bool(self.pricing_enabled_var.get())})
                replaced = True
            elif rule_key != new_key:
                updated.append(rule)
        if not replaced:
            updated.append({'provider': provider, 'model': model, 'input_price': input_price, 'output_price': output_price, 'cache_create_price': cache_create_price, 'cache_hit_price': cache_hit_price, 'enabled': bool(self.pricing_enabled_var.get())})
        self.config.set_usage_pricing_rules(updated)
        self.config.save()
        self._refresh_pricing_rules()
        self._clear_pricing_rule_form()

    def _delete_pricing_rule(self):
        if not self.pricing_edit_key:
            return
        rules = [rule for rule in self.config.get_usage_pricing_rules() if (rule['provider'].lower(), rule['model'].lower()) != self.pricing_edit_key]
        self.config.set_usage_pricing_rules(rules)
        self.config.save()
        self._refresh_pricing_rules()
        self._clear_pricing_rule_form()

    def _reset_usage_log_filters(self):
        self.usage_log_page_var.set('全部应用')
        self.usage_log_status_var.set('全部状态')
        self.usage_log_provider_var.set('')
        self.usage_log_model_var.set('')
        start_text, end_text = default_query_time_range_strings()
        self.usage_log_start_var.set(start_text)
        self.usage_log_end_var.set(end_text)
        self._refresh_usage_panel()

    def _clear_usage_logs(self):
        store = self._get_usage_store()
        if store is None:
            return
        if not messagebox.askyesno(
            '清空请求日志',
            '确定要清空全部请求日志吗？此操作不可撤销。',
            parent=self.frame.winfo_toplevel(),
        ):
            return

        removed_count = int(store.clear_events() or 0)
        self._refresh_usage_panel()
        self.set_status(f'已清空 {removed_count} 条请求日志', COLORS['success'])

    def _execute_system_status_action(self, item):
        action_kind = item.get('action_kind', '')
        action_value = item.get('action_value', '')
        if action_kind == 'bridge':
            self._trigger_action(action_value)
        elif action_kind == 'navigate':
            self._navigate(action_value)

    def _render_system_status_items(self, items):
        for child in self.system_status_list.winfo_children():
            child.destroy()

        if not items:
            self.system_status_empty_label.configure(text='系统运行正常', fg=COLORS['success'])
            self.system_status_empty_label.pack(fill=tk.X, anchor='w', pady=(12, 0))
            return

        self.system_status_empty_label.pack_forget()
        tone_map = {'error': COLORS['error'], 'warning': COLORS['warning'], 'success': COLORS['success']}
        for item in items:
            row = tk.Frame(self.system_status_list, bg=COLORS['surface_alt'], highlightbackground=COLORS['card_border'], highlightthickness=1, padx=12, pady=12)
            row.pack(fill=tk.X, pady=(0, 10))
            head = tk.Frame(row, bg=COLORS['surface_alt'])
            head.pack(fill=tk.X)
            tk.Label(head, text=item.get('title', ''), font=FONTS['body_bold'], fg=tone_map.get(item.get('level', 'success'), COLORS['text_main']), bg=COLORS['surface_alt']).pack(side=tk.LEFT, anchor='w')
            action_name = str(item.get('action_name', '') or '').strip()
            if action_name:
                action_shell, _action_button = self._create_dashboard_shell_button(
                    head,
                    action_name,
                    style='secondary',
                    command=lambda current=item: self._execute_system_status_action(current),
                    padx=12,
                    pady=6,
                    font=FONTS['small'],
                )
                action_shell.pack(side=tk.RIGHT)
            detail = tk.Label(row, text=item.get('detail', ''), font=FONTS['small'], fg=COLORS['text_sub'], bg=COLORS['surface_alt'], justify='left', anchor='w')
            detail.pack(fill=tk.X, anchor='w', pady=(8, 0))
            bind_adaptive_wrap(detail, row, padding=22, min_width=220)

    def _continue_current_task(self):
        status_card = self.dashboard_view_model.get('status_card', {})
        target = str(status_card.get('continue_target', '') or '').strip()
        if target == 'api_config':
            self._trigger_action('show_api_config')
        elif target:
            self._navigate(target)

    def _draw_hero_background(self, width, height):
        self.hero_canvas.delete('stripe')
        step = 28
        for x in range(-height, width, step):
            self.hero_canvas.create_line(
                x, 18, x + height, height,
                fill=COLORS['hero_stripe_b'],
                width=14,
                tags='stripe',
            )
        self.hero_canvas.tag_lower('stripe')
        self.hero_canvas.coords(self.hero_top_bar, 0, 0, width, 14)

    def _draw_hero_text_background(self, width, height):
        self.hero_text.delete('text_stripe')
        step = 28
        for x in range(-height, width, step):
            self.hero_text.create_line(
                x, 0, x + height, height,
                fill=COLORS['hero_stripe_b'],
                width=14,
                tags='text_stripe',
            )
        self.hero_text.tag_lower('text_stripe')

    def _layout_hero_button_group(self, windows, shells, available_width, gap_x, gap_y, origin_x=0, origin_y=0):
        available_width = int(max(available_width, 1))
        x = 0
        y = 0
        row_height = 0

        for window_id, shell in zip(windows, shells):
            shell_width = shell.winfo_reqwidth()
            shell_height = shell.winfo_reqheight()

            if x and x + shell_width > available_width:
                x = 0
                y += row_height + gap_y
                row_height = 0

            self.hero_text.itemconfigure(window_id, width=shell_width, height=shell_height, state='normal')
            self.hero_text.coords(window_id, origin_x + x, origin_y + y)
            x += shell_width + gap_x
            row_height = max(row_height, shell_height)

        return y + row_height if shells else 0

    def _relayout_hero_text(self, text_width):
        text_width = int(max(text_width, 1))
        subtitle_width = min(max(text_width - 8, 620), 928)
        tip_width = min(max(text_width - 8, 560), 840)

        self.hero_text.configure(width=text_width)
        self.hero_text.itemconfigure(
            self.hero_title_item,
            text='纸研社',
            font=(FONTS['hero'][0], 28, 'bold'),
            fill=COLORS['text_main'],
        )
        self.hero_text.itemconfigure(
            self.hero_subtitle_item,
            text='本地优先的智能论文工坊，把 AI 接入、写作、润色、对比和导出整合成一套工作台。',
            font=(FONTS['body'][0], 12),
            fill=COLORS['text_sub'],
            width=subtitle_width,
        )
        self.hero_text.itemconfigure(
            self.hero_identity_item,
            text=get_active_model_label(self.config) if active_model_ready(self.config) else '未配置',
            font=(FONTS['body_bold'][0], 12, 'bold'),
            fill=COLORS['text_sub'],
        )
        self.hero_text.itemconfigure(
            self.hero_tip_item,
            font=FONTS['small'],
            fill=COLORS['text_sub'],
            width=tip_width,
        )

        y = 0
        self.hero_text.coords(self.hero_title_item, 0, y)
        title_box = self.hero_text.bbox(self.hero_title_item)
        y = title_box[3] + 8

        self.hero_text.coords(self.hero_subtitle_item, 0, y)
        subtitle_box = self.hero_text.bbox(self.hero_subtitle_item)
        y = subtitle_box[3] + 8

        self.hero_text.coords(self.hero_identity_item, 0, y)
        identity_box = self.hero_text.bbox(self.hero_identity_item)
        y = identity_box[3] + 8

        self.hero_text.coords(self.hero_tip_item, 0, y)
        tip_box = self.hero_text.bbox(self.hero_tip_item)
        y = tip_box[3] + 12

        self.hero_text.itemconfigure(self.hero_actions_window, state='hidden')
        self.hero_text.itemconfigure(self.hero_tags_window, state='hidden')

        actions_height = self._layout_hero_button_group(
            self.hero_action_windows,
            self.hero_action_shells,
            text_width,
            gap_x=12,
            gap_y=10,
            origin_y=y,
        )
        y += actions_height
        if actions_height:
            y += 10

        tags_height = self._layout_hero_button_group(
            self.hero_tag_windows,
            self.hero_tag_shells,
            text_width,
            gap_x=10,
            gap_y=10,
            origin_y=y,
        )
        y += tags_height

        self.hero_text.configure(height=y)
        self._draw_hero_text_background(text_width, y)
        return y

    def _relayout_hero(self, _event=None, *, force=False):
        if not self.hero_canvas:
            return

        width = max(self.hero_canvas.winfo_width(), 1)
        if not force and width == self._hero_last_width:
            return
        self._hero_last_width = width
        pad = 22
        top = 22
        gap = 18
        visual_width = 208
        visual_height = 208
        progress_width = 338
        progress_height = 286
        progress_right_pad = 76

        self.hero_visual.configure(width=visual_width, height=visual_height)

        if width < 1260:
            text_width = min(max(width - pad * 2, 560), 900)
            progress_card_width = min(max(width - pad * 2, 338), 420)
            self.hero_progress.configure(width=progress_card_width, height=progress_height)

            self.hero_canvas.itemconfigure(self.hero_visual_window, width=visual_width, height=visual_height)
            self.hero_canvas.coords(self.hero_visual_window, pad, top)

            text_height = self._relayout_hero_text(text_width)
            self.hero_canvas.itemconfigure(self.hero_text_window, width=text_width, height=text_height)
            self.hero_canvas.coords(self.hero_text_window, pad, top + visual_height + 14)

            progress_y = top + visual_height + 14 + text_height + 14
            self.hero_completion_hint.configure(wraplength=max(progress_card_width - 54, 200))
            self.hero_canvas.itemconfigure(self.hero_progress_window, width=progress_card_width, height=progress_height)
            self.hero_canvas.coords(self.hero_progress_window, pad, progress_y)
            canvas_height = progress_y + progress_height + 24
        else:
            progress_x = width - progress_right_pad - progress_width
            text_x = pad + visual_width + gap
            text_width = min(max(progress_x - text_x - gap, 760), 936)

            self.hero_progress.configure(width=progress_width, height=progress_height)
            self.hero_canvas.itemconfigure(self.hero_visual_window, width=visual_width, height=visual_height)
            self.hero_canvas.coords(self.hero_visual_window, pad, top + 26)

            text_height = self._relayout_hero_text(text_width)
            self.hero_canvas.itemconfigure(self.hero_text_window, width=text_width, height=text_height)
            self.hero_canvas.coords(self.hero_text_window, text_x, top)

            self.hero_completion_hint.configure(wraplength=max(progress_width - 54, 220))
            subtitle_box = self.hero_text.bbox(self.hero_subtitle_item)
            progress_top = top + (subtitle_box[1] if subtitle_box else 96)
            self.hero_canvas.itemconfigure(self.hero_progress_window, width=progress_width, height=progress_height)
            self.hero_canvas.coords(self.hero_progress_window, progress_x, progress_top)
            canvas_height = max(
                top + 26 + visual_height,
                top + text_height,
                progress_top + progress_height,
            ) + 24

        self.hero_canvas.configure(height=canvas_height)
        self._draw_hero_background(width, canvas_height)

    def _relayout_dashboard(self, _event=None, *, force=False):
        width = max(self.dashboard_columns.winfo_width(), 1)
        mode = 'stacked' if width < 1280 else 'split'
        if not force and mode == self._dashboard_layout_mode:
            return
        self._dashboard_layout_mode = mode

        self.left_column.pack_forget()
        self.right_column.pack_forget()

        if mode == 'stacked':
            self.left_column.pack(fill=tk.BOTH, expand=True)
            self.right_column.pack(fill=tk.BOTH, expand=True, pady=(16, 0))
        else:
            self.left_column.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 16))
            self.right_column.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _trigger_action(self, action_name):
        if not self.app_bridge:
            return
        callback = getattr(self.app_bridge, action_name, None)
        if callable(callback):
            callback()

    def _navigate(self, page_id):
        if callable(self.navigate_page) and page_id:
            self.navigate_page(page_id)

    def _show_model_list(self):
        """弹出模型列表弹窗"""
        import subprocess
        win = tk.Toplevel(self.frame)
        win.title('模型列表')
        win.configure(bg=COLORS['bg_main'])
        win.resizable(False, False)
        win.transient(self.frame.winfo_toplevel())
        apply_adaptive_window_geometry(win, '1600x1200')
        win.grab_set()

        # 标题
        hdr = tk.Frame(win, bg=COLORS['bg_main'])
        hdr.pack(fill=tk.X, padx=20, pady=(16, 8))
        tk.Label(hdr, text='模型列表', font=FONTS['subtitle'], fg=COLORS['primary'],
                 bg=COLORS['bg_main']).pack(side=tk.LEFT)

        def _goto_add_new():
            win.destroy()
            if self.app_bridge:
                self.app_bridge.show_api_config(return_to_model_list=True)

        action_icon_images = {}
        action_button_size = 48
        select_button_height = 48
        select_button_width = 116
        toast_state = {'window': None}

        def _get_action_icon(filename, max_size=(26, 26)):
            image = action_icon_images.get(filename)
            if image is not None:
                return image
            try:
                image = load_image(f'png/{filename}', max_size=max_size)
            except Exception:
                image = None
            action_icon_images[filename] = image
            return image

        def _close_test_toast():
            toast = toast_state.get('window')
            if toast and toast.winfo_exists():
                toast.destroy()
            toast_state['window'] = None

        def _show_test_toast(message, ok):
            if not win.winfo_exists():
                return

            _close_test_toast()
            toast = tk.Toplevel(win)
            toast.overrideredirect(True)
            toast.configure(bg=COLORS['shadow'])
            try:
                toast.attributes('-topmost', True)
            except tk.TclError:
                pass

            border_color = COLORS['success'] if ok else COLORS['error']
            title_text = '模型测试成功' if ok else '模型测试失败'
            shell = tk.Frame(toast, bg=COLORS['shadow'])
            shell.pack()
            card = tk.Frame(
                shell,
                bg=COLORS['card_bg'],
                highlightbackground=border_color,
                highlightthickness=2,
            )
            card.pack(padx=(0, 4), pady=(0, 4))
            tk.Label(
                card,
                text=title_text,
                font=FONTS['body_bold'],
                fg=border_color,
                bg=COLORS['card_bg'],
            ).pack(anchor='w', padx=16, pady=(12, 6))
            tk.Label(
                card,
                text=str(message or '').strip() or '模型测试未返回结果。',
                font=FONTS['small'],
                fg=COLORS['text_main'],
                bg=COLORS['card_bg'],
                justify='left',
                wraplength=560,
            ).pack(anchor='w', padx=16, pady=(0, 12))

            toast.update_idletasks()
            win.update_idletasks()
            x = win.winfo_rootx() + max((win.winfo_width() - toast.winfo_reqwidth()) // 2, 0)
            y = win.winfo_rooty() + 72
            toast.geometry(f'+{x}+{y}')
            toast.after(5000, _close_test_toast)
            toast.bind('<Button-1>', lambda _event: _close_test_toast())
            for child in card.winfo_children():
                child.bind('<Button-1>', lambda _event: _close_test_toast())
            toast_state['window'] = toast

        ModernButton(hdr, '⚙ 前往配置', style='secondary',
                     command=_goto_add_new,
                     padx=10, pady=6).pack(side=tk.RIGHT, padx=(0, 8))

        # 滚动区
        container = tk.Frame(win, bg=COLORS['bg_main'])
        container.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 16))

        canvas = tk.Canvas(container, bg=COLORS['bg_main'], bd=0,
                           highlightthickness=0)
        scrollbar = tk.Scrollbar(container, orient='vertical', command=canvas.yview)
        inner = tk.Frame(canvas, bg=COLORS['bg_main'])

        inner.bind('<Configure>',
                   lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=inner, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.bind('<Configure>',
                    lambda e: canvas.itemconfig(canvas.find_all()[0], width=e.width))
        canvas.pack(fill=tk.BOTH, expand=True)

        def _on_mousewheel(event):
            if event.num == 4:
                canvas.yview_scroll(-1, 'units')
            elif event.num == 5:
                canvas.yview_scroll(1, 'units')
            else:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')

        def _bind_wheel(e=None):
            win.bind_all('<MouseWheel>', _on_mousewheel)
            win.bind_all('<Button-4>', _on_mousewheel)
            win.bind_all('<Button-5>', _on_mousewheel)

        def _unbind_wheel(e=None):
            win.unbind_all('<MouseWheel>')
            win.unbind_all('<Button-4>')
            win.unbind_all('<Button-5>')

        canvas.bind('<Enter>', _bind_wheel)
        canvas.bind('<Leave>', _unbind_wheel)
        inner.bind('<Enter>', _bind_wheel)
        win.bind('<Destroy>', lambda e: _unbind_wheel())

        # 拖拽状态
        drag_state = {'widget': None, 'api_id': None, 'start_y': 0, 'ghost': None}

        def _on_drag_start(event, api_id, card_frame):
            drag_state['api_id'] = api_id
            drag_state['widget'] = card_frame
            drag_state['start_y'] = event.y_root

        def _on_drag_motion(event, api_id):
            if drag_state['api_id'] != api_id:
                return
            y_root = event.y_root
            cards = [w for w in inner.winfo_children() if isinstance(w, tk.Frame)]
            target_idx = None
            for i, c in enumerate(cards):
                cy = c.winfo_rooty()
                ch = c.winfo_height()
                if cy <= y_root <= cy + ch:
                    target_idx = i
                    break
            if target_idx is None:
                if cards and y_root < cards[0].winfo_rooty():
                    target_idx = 0
                elif cards:
                    target_idx = len(cards) - 1
            drag_state['target_idx'] = target_idx

        def _on_drag_end(event, api_id):
            if drag_state['api_id'] != api_id:
                return
            target_idx = drag_state.get('target_idx')
            if target_idx is None:
                drag_state['api_id'] = None
                return
            ordered = [aid for aid, _ in self.config.list_saved_apis()]
            if api_id in ordered:
                ordered.remove(api_id)
                ordered.insert(target_idx, api_id)
                self.config.reorder_apis(ordered)
                self.config.save()
                _populate()
            drag_state['api_id'] = None

        def _create_action_icon(parent, *, icon, tooltip, fg, command, active_bg, active_fg=None, image_name=None):
            shell = tk.Frame(
                parent,
                bg=COLORS['shadow'],
                width=action_button_size,
                height=action_button_size,
            )
            shell.pack_propagate(False)
            button = ToolIconButton(
                shell,
                text=icon,
                tooltip=tooltip,
                command=command,
                font=FONTS['small'],
                width=4,
                padx=0,
                pady=0,
                highlightthickness=2,
                takefocus=0,
            )
            button.configure(
                fg=fg,
                activebackground=active_bg,
                activeforeground=active_fg or COLORS['text_main'],
            )
            if image_name:
                image = _get_action_icon(image_name)
                if image is not None:
                    button.configure(image=image, text='')
                    button.image = image
            button.pack(fill=tk.BOTH, expand=True, padx=(2, 4), pady=(2, 4))
            return shell, button

        def _test_model(api_id, raw_cfg, button):
            effective_cfg = merge_with_preset_defaults(raw_cfg, raw_cfg.get('provider_type') or api_id)
            settings = resolve_connection_test_settings(self.config, effective_cfg)

            try:
                if button.winfo_exists():
                    button.configure(state=tk.DISABLED, cursor='arrow')
            except tk.TclError:
                pass

            def _finish(ok, message):
                try:
                    if button.winfo_exists():
                        button.configure(state=tk.NORMAL, cursor='hand2')
                except tk.TclError:
                    pass
                _show_test_toast(message, ok)

            self.model_test_task_runner.run(
                work=lambda: self.api.test_connection(
                    api_id,
                    prompt=settings['prompt'],
                    model_override=settings['model_override'],
                    timeout=settings['timeout'],
                    degrade_threshold_ms=settings['degrade_ms'],
                    max_retries=settings['max_retries'],
                    cfg=effective_cfg,
                    usage_context={
                        'page_id': 'home',
                        'scene_id': 'model_list',
                        'action': 'test_connection',
                    },
                ),
                on_success=lambda result: _finish(result[0], result[1]),
                on_error=lambda exc: _finish(False, str(exc)),
                status_text='正在测试模型连接...',
            )

        def _activate_model(api_id, display_name):
            if not self.config.get_api_config(api_id):
                messagebox.showerror('切换失败', '目标模型配置不存在，请刷新后重试。', parent=win)
                return
            self.config.active_api = api_id
            if not self.config.save():
                messagebox.showerror('切换失败', '当前模型保存失败，请稍后重试。', parent=win)
                return
            self.refresh_dashboard()
            self.set_status(f'已切换当前模型：{display_name}')
            _populate()

        def _populate():
            for w in inner.winfo_children():
                w.destroy()
            any_shown = False
            active_id = self.config.active_api
            for api_id, cfg in self.config.list_saved_apis():
                name = cfg.get('name', '').strip() or api_id
                model_id = str(cfg.get('model', '') or '').strip()
                model_display = resolve_model_display_name(cfg)
                switch_label = f'{name} / {model_display}' if model_display else name
                any_shown = True
                is_active = (api_id == active_id)
                card_bg = COLORS.get('primary_light', COLORS['surface_alt']) if is_active else COLORS['card_bg']
                border_color = COLORS['primary'] if is_active else COLORS['card_border']
                card = tk.Frame(inner, bg=card_bg,
                                highlightbackground=border_color,
                                highlightthickness=2 if is_active else 1)
                card.pack(fill=tk.X, pady=(0, 8))

                # 拖拽手柄 + 内容的水平容器
                row = tk.Frame(card, bg=card_bg)
                row.pack(fill=tk.X, padx=14, pady=10)

                # 左侧拖拽手柄
                handle = tk.Label(row, text='⠿', font=FONTS['body_bold'],
                                  fg=COLORS['text_muted'], bg=card_bg,
                                  cursor='fleur')
                handle.pack(side=tk.LEFT, padx=(0, 10))
                handle.bind('<ButtonPress-1>', lambda e, aid=api_id, cf=card: _on_drag_start(e, aid, cf))
                handle.bind('<B1-Motion>', lambda e, aid=api_id: _on_drag_motion(e, aid))
                handle.bind('<ButtonRelease-1>', lambda e, aid=api_id: _on_drag_end(e, aid))

                # 信息区（可点击手柄拖拽，也允许整个 body 拖拽）
                body = tk.Frame(row, bg=card_bg)
                body.pack(side=tk.LEFT, fill=tk.X, expand=True)

                name_row = tk.Frame(body, bg=card_bg)
                name_row.pack(fill=tk.X)
                tk.Label(name_row, text=name, font=FONTS['body_bold'],
                         fg=COLORS['primary'] if is_active else COLORS['text_main'],
                         bg=card_bg).pack(side=tk.LEFT)
                if model_display:
                    tk.Label(name_row, text=f'  {model_display}', font=FONTS['small'],
                             fg=COLORS['text_muted'], bg=card_bg).pack(side=tk.LEFT)
                if model_id and model_id != model_display:
                    tk.Label(body, text=f'模型 ID：{model_id}', font=FONTS['small'],
                             fg=COLORS['text_muted'], bg=card_bg).pack(anchor='w', pady=(2, 0))

                website = cfg.get('website', '').strip()
                if website:
                    link = tk.Label(body, text=website, font=FONTS['small'],
                                    fg=COLORS['info'], bg=card_bg,
                                    cursor='hand2')
                    link.pack(anchor='w')
                    link.bind('<Button-1>', lambda e, url=website: subprocess.Popen(
                        ['cmd', '/c', 'start', '', url], shell=False))

                remark = cfg.get('remark', '').strip()
                if remark:
                    tk.Label(body, text=remark, font=FONTS['small'],
                             fg=COLORS['text_muted'], bg=card_bg,
                             wraplength=460, justify='left').pack(anchor='w', pady=(2, 0))

                # 右侧按钮区（垂直居中）
                btn_col = tk.Frame(row, bg=card_bg, width=320, height=select_button_height)
                btn_col.pack(side=tk.RIGHT, padx=(12, 0), anchor='center')
                btn_col.pack_propagate(False)
                btn_col.grid_columnconfigure(0, minsize=120)
                btn_col.grid_columnconfigure(1, minsize=60)
                btn_col.grid_columnconfigure(2, minsize=60)
                btn_col.grid_columnconfigure(3, minsize=60)
                btn_col.grid_rowconfigure(0, minsize=select_button_height)

                select_shell, select_button = create_home_shell_button(
                    btn_col,
                    '当前使用' if is_active else '启用',
                    command=(lambda: None) if is_active else (lambda aid=api_id, model_name=switch_label: _activate_model(aid, model_name)),
                    style='primary' if is_active else 'secondary',
                    padx=8,
                    pady=4,
                    font=FONTS['small'],
                    border_color=COLORS['primary'] if is_active else COLORS['card_border'],
                )
                select_shell.configure(width=select_button_width, height=select_button_height)
                select_shell.pack_propagate(False)
                if is_active:
                    select_button.configure(
                        state=tk.DISABLED,
                        cursor='arrow',
                        disabledforeground=COLORS['text_main'],
                    )
                select_shell.grid(row=0, column=0, padx=(0, 6), sticky='e')

                test_shell, test_button = _create_action_icon(
                    btn_col,
                    icon='测',
                    tooltip='模型测试',
                    fg=COLORS['primary'],
                    command=lambda: None,
                    active_bg=COLORS['accent_light'],
                    image_name='Model_test.png',
                )
                test_button.configure(command=lambda aid=api_id, saved_cfg=dict(cfg), btn=test_button: _test_model(aid, saved_cfg, btn))
                test_shell.grid(row=0, column=1, padx=(0, 6), sticky='e')

                detail_shell, _detail_button = _create_action_icon(
                    btn_col,
                    icon='✎',
                    tooltip='查看详情',
                    fg=COLORS['primary'],
                    command=lambda aid=api_id: _open_detail(aid),
                    active_bg=COLORS['primary_light'],
                    image_name='Edit.png',
                )
                detail_shell.grid(row=0, column=2, padx=(0, 6), sticky='e')

                _name = name

                def _delete(aid=api_id, n=_name, active=is_active):
                    if active:
                        confirm_message = (
                            f'确定要删除当前模型「{n}」的配置吗？此操作不可撤销。\n'
                            '删除后会自动切换到下一条可用模型；若无剩余模型则清空当前模型。'
                        )
                    else:
                        confirm_message = f'确定要删除「{n}」的配置吗？此操作不可撤销。'
                    if not messagebox.askyesno('删除模型', confirm_message, parent=win):
                        return

                    backup_cfg = self.config.get_api_config(aid)
                    previous_active_api = self.config.active_api
                    self.config.delete_api_config(aid)
                    if not self.config.save():
                        if backup_cfg:
                            self.config.set_api_config(aid, backup_cfg)
                        self.config.active_api = previous_active_api
                        messagebox.showerror('删除失败', '模型配置保存失败，请稍后重试。', parent=win)
                        return

                    self.refresh_dashboard()
                    _populate()

                del_shell, _del_button = _create_action_icon(
                    btn_col,
                    icon='⌦',
                    tooltip='删除',
                    fg=COLORS['error'],
                    command=_delete,
                    active_bg=COLORS['error'],
                    active_fg='#FFFFFF',
                    image_name='Delete.png',
                )
                del_shell.grid(row=0, column=3, sticky='e')

            if not any_shown:
                tk.Label(inner, text='暂无已配置的模型，请前往「模型配置」页面添加。',
                         font=FONTS['body'], fg=COLORS['text_muted'],
                         bg=COLORS['bg_main'], wraplength=480).pack(pady=40)

        def _open_detail(api_id):
            win.destroy()
            if self.app_bridge:
                self.app_bridge.show_api_config(return_to_model_list=True)
                self.frame.after(150, lambda aid=api_id: self.app_bridge.switch_api_provider_direct(aid))

        _populate()
        self._model_list_refresh = _populate
        win.after_idle(win.focus_force)
        win.bind('<Destroy>', lambda _event: _close_test_toast(), add='+')
        win.protocol('WM_DELETE_WINDOW', lambda: [setattr(self, '_model_list_refresh', None), win.destroy()])

    def _start_using(self):
        if active_model_ready(self.config):
            self._navigate('paper_write')
            self.set_status('已进入论文写作页面')
        else:
            self._trigger_action('show_api_config')
            self.set_status('请先完成模型配置，再开始写作', COLORS['warning'])

    def refresh_dashboard(self):
        show_home_stats = self.config.get_setting('show_home_stats', True)
        view_model = build_dashboard_view_model(
            show_home_stats,
            self.config,
            self.history,
            'all',
        )
        self.dashboard_view_model = view_model

        self.hero_text.itemconfigure(self.hero_tip_item, text=view_model['tip_text'])
        self.hero_completion_label.configure(text=f'#{view_model["total"]:04d}')
        self.hero_completion_hint.configure(text=view_model['completion_hint'])
        self.board_subtitle_label.configure(text=view_model['board_text'])
        self.task_text_label.configure(text=view_model['task_text'])

        field_keys = (
            'paper_topic',
            'stage',
            'active_model',
            'word_count',
            'latest_time',
            'pending_risks',
        )
        for key, (_title, value) in zip(field_keys, view_model['status_card']['fields']):
            label = self.status_value_labels.get(key)
            if label is not None:
                label.configure(text=str(value))

        self._render_system_status_items(view_model.get('system_status_items', []))
        self._refresh_usage_panel()

        self._relayout_hero(force=True)
        self._relayout_dashboard(force=True)

    def on_show(self):
        self._refresh_primary_action_button_styles()
        self._relayout_hero(force=True)
        self._relayout_dashboard(force=True)
        self.refresh_dashboard()
        try:
            is_viewable = bool(self.frame.winfo_viewable())
        except tk.TclError:
            is_viewable = False
        if is_viewable:
            self._ensure_usage_summary_cards()
            self._schedule_usage_layout_stabilize(80)
