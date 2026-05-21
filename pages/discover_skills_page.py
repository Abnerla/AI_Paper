# -*- coding: utf-8 -*-
"""
发现技能弹窗面板 — 支持仓库搜索筛选、网格化卡片、安装/详情、仓库管理。
"""

from __future__ import annotations

import threading
import time as _time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from modules.skills_runtime import SkillExecutionError, SkillValidationError
from modules.ui_components import (
    bind_adaptive_wrap,
    bind_ellipsis_tooltip,
    bind_combobox_dropdown_mousewheel,
    CardFrame,
    COLORS,
    create_home_shell_button,
    FONTS,
    ModernButton,
    ScrollablePage,
    set_ellipsized_label_text,
    SkillCardGrid,
    show_tooltip,
    ToggleSwitch,
)


class DiscoverSkillsPanel:
    SKILL_CARD_WIDTH = 340
    SKILL_CARD_HEIGHT = 400
    SKILL_CARD_DESC_HEIGHT = 132
    SKILL_CARD_DESC_LINES = 4
    SKILL_CARD_DESC_CHARS = 72

    def __init__(self, parent, config_mgr, skill_manager, remote_content_manager,
                 *, set_status, close_panel=None, on_skill_installed=None,
                 on_open_repo_manage=None):
        self.config = config_mgr
        self.skill_manager = skill_manager
        self.remote_content = remote_content_manager
        self.set_status = set_status
        self.close_panel = close_panel
        self.on_skill_installed = on_skill_installed
        self.on_open_repo_manage = on_open_repo_manage
        self.frame = tk.Frame(parent, bg=COLORS['bg_main'])

        self._current_source = 'registry'
        self._registry_payload = self.skill_manager.load_registry_cache()
        self._all_skills = []
        self._filtered_skills = []
        self._search_var = tk.StringVar(value='')
        self._source_filter_var = tk.StringVar(value='全部来源')
        self._status_filter_var = tk.StringVar(value='全部')
        self._search_debounce_job = None
        self._source_buttons = {}
        self._source_filter_combo = None
        self._toolbar_row2 = None
        self._grid_area = None
        self._card_grid = None
        self._count_label = None
        self._search_entry = None
        self._search_placeholder_on = True

        self._build()
        self._load_source_data('registry')

    # ------------------------------------------------------------------ UI 构建
    def _build(self):
        # 顶部栏
        toolbar = tk.Frame(self.frame, bg=COLORS['bg_main'])
        toolbar.pack(fill=tk.X, pady=(0, 10))
        self._build_toolbar(toolbar)

        # 内容区
        self._grid_area = ScrollablePage(self.frame, bg=COLORS['bg_main'])
        self._grid_area.pack(fill=tk.BOTH, expand=True)

        self._card_grid = SkillCardGrid(
            self._grid_area.inner,
            card_width=self.SKILL_CARD_WIDTH,
            card_height=self.SKILL_CARD_HEIGHT,
            gap_x=14,
            gap_y=14,
            max_columns=4,
            bg=COLORS['bg_main'],
        )
        self._card_grid.pack(fill=tk.BOTH, expand=True)

    def _build_toolbar(self, parent):
        # 第一行：仓库入口 | 搜索框 | 刷新
        row1 = tk.Frame(parent, bg=COLORS['bg_main'])
        row1.pack(fill=tk.X, pady=(0, 8))

        # 仓库入口
        source_frame = tk.Frame(row1, bg=COLORS['bg_main'])
        source_frame.pack(side=tk.LEFT)

        for source_key, source_label in [('registry', '仓库')]:
            btn = ModernButton(
                source_frame,
                source_label,
                style='primary' if source_key == self._current_source else 'ghost',
                command=lambda k=source_key: self._switch_source(k),
                padx=16,
                pady=4,
            )
            btn.pack(side=tk.LEFT, padx=(0, 4))
            self._source_buttons[source_key] = btn

        # 搜索框
        search_frame = tk.Frame(row1, bg=COLORS['bg_main'])
        search_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(12, 12))

        self._search_entry = tk.Entry(
            search_frame,
            textvariable=self._search_var,
            font=FONTS['body'],
            bg=COLORS['input_bg'],
            fg=COLORS['text_muted'],
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=COLORS['input_border'],
            insertbackground=COLORS['text_main'],
        )
        self._search_entry.pack(fill=tk.X, ipady=5)
        self._search_entry.insert(0, self._SEARCH_PLACEHOLDER)
        self._search_entry.bind('<FocusIn>', self._on_search_focus_in)
        self._search_entry.bind('<FocusOut>', self._on_search_focus_out)
        self._search_entry.bind('<KeyRelease>', self._on_search_changed)

        # 刷新按钮
        refresh_shell, _ = create_home_shell_button(
            row1,
            '刷新',
            command=self._refresh,
            style='ghost',
            padx=10,
            pady=4,
        )
        refresh_shell.pack(side=tk.RIGHT)

        # 第二行：来源筛选 | 安装状态筛选 | 仓库管理 | 计数
        self._toolbar_row2 = tk.Frame(parent, bg=COLORS['bg_main'])
        self._toolbar_row2.pack(fill=tk.X, pady=(0, 4))

        # 来源筛选（仅仓库模式下有意义）
        filter_source_frame = tk.Frame(self._toolbar_row2, bg=COLORS['bg_main'])
        filter_source_frame.pack(side=tk.LEFT)
        tk.Label(
            filter_source_frame,
            text='来源:',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['bg_main'],
        ).pack(side=tk.LEFT, padx=(0, 4))
        self._source_filter_combo = ttk.Combobox(
            filter_source_frame,
            textvariable=self._source_filter_var,
            values=['全部来源'],
            state='readonly',
            style='Modern.TCombobox',
            width=14,
        )
        self._source_filter_combo.pack(side=tk.LEFT, ipady=3)
        bind_combobox_dropdown_mousewheel(self._source_filter_combo)
        self._source_filter_combo.bind('<<ComboboxSelected>>', lambda e: self._apply_filters())

        # 安装状态筛选
        filter_status_frame = tk.Frame(self._toolbar_row2, bg=COLORS['bg_main'])
        filter_status_frame.pack(side=tk.LEFT, padx=(16, 0))
        tk.Label(
            filter_status_frame,
            text='状态:',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['bg_main'],
        ).pack(side=tk.LEFT, padx=(0, 4))
        status_combo = ttk.Combobox(
            filter_status_frame,
            textvariable=self._status_filter_var,
            values=['全部', '已安装', '未安装'],
            state='readonly',
            style='Modern.TCombobox',
            width=10,
        )
        status_combo.pack(side=tk.LEFT, ipady=3)
        bind_combobox_dropdown_mousewheel(status_combo)
        status_combo.bind('<<ComboboxSelected>>', lambda e: self._apply_filters())

        # 仓库管理按钮
        repo_manage_shell, _ = create_home_shell_button(
            self._toolbar_row2,
            '仓库管理',
            command=self._open_repo_manage,
            style='secondary',
            padx=10,
            pady=4,
        )
        repo_manage_shell.pack(side=tk.LEFT, padx=(20, 0))

        # 计数标签
        self._count_label = tk.Label(
            self._toolbar_row2,
            text='',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['bg_main'],
            anchor='e',
        )
        self._count_label.pack(side=tk.RIGHT)

    # ------------------------------------------------------------------ 仓库管理（关闭当前弹窗，打开仓库管理弹窗）
    def _open_repo_manage(self):
        if callable(self.on_open_repo_manage):
            self.on_open_repo_manage()

    # ------------------------------------------------------------------ 搜索占位符
    _SEARCH_PLACEHOLDER = '搜索技能名称/描述...'

    def _is_placeholder_active(self):
        return getattr(self, '_search_placeholder_on', True)

    def _on_search_focus_in(self, _event=None):
        entry = _event.widget
        if self._search_placeholder_on:
            self._search_placeholder_on = False
            entry.delete(0, tk.END)
            entry.configure(fg=COLORS['text_main'])

    def _on_search_focus_out(self, _event=None):
        entry = _event.widget
        if not entry.get().strip():
            self._search_placeholder_on = True
            entry.delete(0, tk.END)
            entry.insert(0, self._SEARCH_PLACEHOLDER)
            entry.configure(fg=COLORS['text_muted'])

    def _on_search_changed(self, _event=None):
        if self._search_debounce_job:
            try:
                self.frame.after_cancel(self._search_debounce_job)
            except Exception:
                pass
        self._search_debounce_job = self.frame.after(300, self._debounced_apply_filters)

    def _debounced_apply_filters(self):
        self._search_debounce_job = None
        self._apply_filters()

    # ------------------------------------------------------------------ 数据源切换
    def _switch_source(self, source_key):
        if source_key == self._current_source:
            return
        # 取消待执行的防抖搜索
        if self._search_debounce_job:
            try:
                self.frame.after_cancel(self._search_debounce_job)
            except Exception:
                pass
            self._search_debounce_job = None
        self._current_source = source_key
        for key, btn in self._source_buttons.items():
            btn.set_style('primary' if key == source_key else 'ghost')
        self._source_filter_combo.configure(state='readonly')
        # 重置搜索（正确清空，避免占位符冲突）
        # 如果搜索框仍有焦点，先移除焦点，防止占位符与用户输入冲突
        if self._search_entry is not None:
            try:
                focus_widget = self.frame.winfo_toplevel().focus_get()
                if focus_widget is self._search_entry:
                    self.frame.focus_set()
            except Exception:
                pass
        self._search_placeholder_on = True
        self._search_entry.delete(0, tk.END)
        self._search_entry.insert(0, self._SEARCH_PLACEHOLDER)
        self._search_entry.configure(fg=COLORS['text_muted'])
        self._status_filter_var.set('全部')
        self._load_source_data(source_key)

    # ------------------------------------------------------------------ 数据加载
    def _load_source_data(self, source_type):
        self.set_status('正在加载技能列表...', COLORS['warning'])
        self._load_registry_data()

    def _load_registry_data(self):
        repos = self.config.get_skills_repositories()
        enabled_repos = [r for r in repos if r.get('enabled', True)]

        # 更新来源筛选选项
        repo_names = ['全部来源'] + [r.get('name', r.get('id', '')) for r in enabled_repos]
        self._source_filter_combo.configure(values=repo_names)

        if not enabled_repos:
            self._all_skills = []
            self._apply_filters()
            self.set_status('没有已启用的仓库', COLORS['warning'])
            return

        # 先加载本地缓存（用于远程拉取失败时的回退）
        self._registry_payload = self.skill_manager.load_registry_cache()

        # 直接远程拉取，避免缓存渲染后再刷新导致的闪烁
        self._fetch_all_repos(enabled_repos)

    def _fetch_all_repos(self, repos):
        remaining = len(repos)
        merged_skills = []  # 每项为 (repo_name, skill_data)

        def on_repo_loaded(data, repo_name='官方仓库'):
            nonlocal remaining
            remaining -= 1
            try:
                sanitized = self.skill_manager.sanitize_registry_payload(data)
                for skill in sanitized.get('skills', []):
                    merged_skills.append((repo_name, skill))
            except Exception:
                pass
            if remaining <= 0:
                if self._current_source == 'registry':
                    self._on_all_repos_fetched(merged_skills)

        def on_repo_error(exc, repo_name=''):
            nonlocal remaining
            remaining -= 1
            if remaining <= 0:
                if self._current_source == 'registry':
                    self._on_all_repos_fetched(merged_skills)

        for repo in repos:
            url = str(repo.get('url', '') or '').strip()
            repo_name = str(repo.get('name', repo.get('id', '')) or '').strip() or '未命名仓库'
            if not url:
                remaining -= 1
                continue
            if repo.get('id') == 'official':
                self.remote_content.fetch('skills_index',
                    on_success=lambda data, rn=repo_name: on_repo_loaded(data, repo_name=rn),
                    on_error=lambda exc, rn=repo_name: on_repo_error(exc, repo_name=rn),
                    force=True)
            else:
                self.remote_content.fetch_custom(url,
                    on_success=lambda data, rn=repo_name: on_repo_loaded(data, repo_name=rn),
                    on_error=lambda exc, rn=repo_name: on_repo_error(exc, repo_name=rn),
                    force=True)

        if remaining <= 0:
            self._on_all_repos_fetched(merged_skills)

    def _on_all_repos_fetched(self, repo_skills):
        all_skills = []
        seen_ids = set()

        # 构建 repo_name → skill 的映射，为每个 skill 标注来源仓库名
        repo_skill_map = {}
        registry_map = {}
        for repo_name, raw in repo_skills:
            skill_id = str(raw.get('id', '') or '').strip()
            if skill_id:
                repo_skill_map[skill_id] = repo_name
                registry_map[skill_id] = raw

        if registry_map:
            merged_payload = {
                'id': 'merged-registry',
                'updated_at': '',
                'skills': list(registry_map.values()),
            }
        else:
            merged_payload = self._registry_payload

        installed = self.skill_manager.list_installed_skills(merged_payload)
        installed_map = {s.get('id'): s for s in installed}

        # 如果远程拉取有数据，使用远程数据
        if repo_skills:
            for item in self.skill_manager.list_registry_skills(merged_payload):
                skill_id = item.get('id', '')
                merged = self.skill_manager.build_skill_view(
                    installed_map.get(skill_id, {}),
                    registry_entry=registry_map.get(skill_id) or item.get('registry_entry') or item,
                )
                if skill_id not in installed_map:
                    merged['is_installed'] = False
                merged['repo_name'] = repo_skill_map.get(skill_id, '官方仓库')
                if skill_id not in seen_ids:
                    seen_ids.add(skill_id)
                    all_skills.append(merged)
            for repo_name, raw in repo_skills:
                skill_id = str(raw.get('id', '') or '').strip()
                if skill_id and skill_id not in seen_ids:
                    seen_ids.add(skill_id)
                    view = self.skill_manager.build_skill_view(
                        installed_map.get(skill_id, {}),
                        registry_entry=raw,
                    )
                    view['repo_name'] = repo_name
                    all_skills.append(view)
        else:
            # 远程拉取全部失败，回退到本地缓存
            for item in self.skill_manager.list_registry_skills(self._registry_payload):
                skill_id = item.get('id', '')
                entry = self.skill_manager.build_skill_view(
                    installed_map.get(skill_id, {}),
                    registry_entry=item.get('registry_entry') or item,
                )
                if skill_id not in installed_map:
                    entry['is_installed'] = False
                entry.setdefault('repo_name', '官方仓库')
                all_skills.append(entry)
                seen_ids.add(skill_id)

        for item in installed:
            if item.get('id') not in seen_ids:
                entry = dict(item)
                entry.setdefault('repo_name', '本地')
                all_skills.append(entry)

        self._all_skills = all_skills
        self._apply_filters()
        if repo_skills:
            self.set_status(f'技能索引已刷新，共 {len(self._all_skills)} 个技能', COLORS['success'])
        else:
            self.set_status(f'使用缓存索引，共 {len(self._all_skills)} 个技能', COLORS['text_sub'])

    # ------------------------------------------------------------------ 筛选
    def _apply_filters(self):
        query = ''
        if not self._is_placeholder_active():
            query = str(self._search_var.get() or '').strip().lower()
        source_filter = str(self._source_filter_var.get() or '')
        status_filter = str(self._status_filter_var.get() or '')

        filtered = []
        for view in self._all_skills:
            # 搜索条件
            if query:
                searchable = ' '.join([
                    str(view.get('name', '') or ''),
                    str(view.get('description', '') or ''),
                    str(view.get('id', '') or ''),
                    str(view.get('publisher', '') or ''),
                ]).lower()
                if query not in searchable:
                    continue
            # 安装状态筛选
            if status_filter == '已安装' and not view.get('is_installed'):
                continue
            if status_filter == '未安装' and view.get('is_installed'):
                continue
            # 来源筛选
            if source_filter and source_filter != '全部来源':
                repo_name = view.get('repo_name', '')
                if repo_name != source_filter:
                    continue
            filtered.append(view)

        self._filtered_skills = filtered
        self._render_skill_grid()
        self._update_count_label()

    def _update_count_label(self):
        total = len(self._all_skills)
        shown = len(self._filtered_skills)
        if shown == total:
            self._count_label.configure(text=f'共 {total} 个技能')
        else:
            self._count_label.configure(text=f'显示 {shown} / {total} 个技能')

    # ------------------------------------------------------------------ 网格渲染
    def _render_skill_grid(self):
        if not self._card_grid:
            return
        self._card_grid.clear_cards()

        if not self._filtered_skills:
            # 区分不同空状态
            if not self._all_skills:
                empty_text = '仓库中没有技能，请添加仓库或检查网络连接。'
            elif self._all_skills and not self._filtered_skills:
                empty_text = '没有找到匹配的技能。'
            else:
                empty_text = '暂无技能。'
            tk.Label(
                self._card_grid,
                text=empty_text,
                font=FONTS['body'],
                fg=COLORS['text_sub'],
                bg=COLORS['bg_main'],
                anchor='center',
                justify='center',
            ).grid(row=0, column=0, sticky='ew')
            self._card_grid.grid_columnconfigure(0, weight=1)
            return

        for view in self._filtered_skills:
            card = self._render_skill_card(view)
            self._card_grid.add_card(card)

        self._refresh_grid_layout()

    def _refresh_grid_layout(self):
        if not self._grid_area:
            return

        def apply_layout():
            try:
                self._grid_area.inner.update_idletasks()
                self._grid_area._apply_layout_refresh()
            except tk.TclError:
                pass

        apply_layout()
        try:
            self.frame.after_idle(apply_layout)
        except tk.TclError:
            pass

    @staticmethod
    def _first_view_text(view, keys, default=''):
        if not isinstance(view, dict):
            return default
        sources = [view]
        for nested_key in ('manifest', 'registry_entry'):
            nested = view.get(nested_key)
            if isinstance(nested, dict):
                sources.append(nested)
        for source in sources:
            for key in keys:
                value = str(source.get(key, '') or '').strip()
                if value:
                    return value
        return default

    @classmethod
    def _skill_display_name(cls, view):
        skill_id = str((view or {}).get('id', '') or '').strip()
        return cls._first_view_text(
            view,
            ('name', 'title', 'display_name', 'label'),
            skill_id or '未命名技能',
        )

    @classmethod
    def _skill_display_description(cls, view):
        return cls._first_view_text(
            view,
            ('description', 'summary', 'intro', 'readme', 'details'),
            '该技能暂未提供介绍，请查看技能详情或仓库文档。',
        )

    @staticmethod
    def _truncate_card_text(text, limit):
        value = ' '.join(str(text or '').split())
        if len(value) <= limit:
            return value, False
        return value[:max(0, limit - 3)].rstrip() + '...', True

    def _render_skill_card(self, view):
        is_installed = bool(view.get('is_installed', False))
        has_update = bool(view.get('has_update', False))
        card = CardFrame(self._card_grid, padding=14)
        card.configure(width=self.SKILL_CARD_WIDTH, height=self.SKILL_CARD_HEIGHT)
        card.grid_propagate(False)
        card.pack_propagate(False)
        try:
            card.body.configure(width=self.SKILL_CARD_WIDTH - 6, height=self.SKILL_CARD_HEIGHT - 6)
            card.body.pack_propagate(False)
            card.inner.configure(width=self.SKILL_CARD_WIDTH - 34, height=self.SKILL_CARD_HEIGHT - 34)
            card.inner.pack_propagate(False)
            card.inner.grid_propagate(False)
        except tk.TclError:
            pass

        card.inner.grid_columnconfigure(0, weight=1)
        card.inner.grid_rowconfigure(3, weight=1, minsize=self.SKILL_CARD_DESC_HEIGHT)

        # 头部行：名称 + 状态标签
        header = tk.Frame(card.inner, bg=COLORS['card_bg'])
        header.grid(row=0, column=0, sticky='ew')
        header.grid_columnconfigure(0, weight=1)
        skill_name = self._skill_display_name(view)
        name_label = tk.Label(
            header,
            text='',
            font=FONTS['body_bold'],
            fg=COLORS['text_main'],
            bg=COLORS['card_bg'],
            anchor='w',
            width=1,
        )
        name_label.grid(row=0, column=0, sticky='ew')
        bind_ellipsis_tooltip(name_label, padding=8, wraplength=360)
        set_ellipsized_label_text(name_label, skill_name)

        tag_text = ''
        tag_fg = COLORS['primary']
        if is_installed and has_update:
            tag_text = '可更新'
            tag_fg = COLORS['warning']
        elif is_installed:
            tag_text = '已安装'
            tag_fg = COLORS['success']
        if tag_text:
            tk.Label(
                header,
                text=tag_text,
                font=FONTS['small'],
                fg=tag_fg,
                bg=COLORS['card_bg'],
                anchor='e',
            ).grid(row=0, column=1, sticky='e', padx=(8, 0))

        source_label = str(view.get('source_label', '') or view.get('source_type', '') or 'registry').strip()
        publisher = str(view.get('publisher', '') or '').strip()

        meta_row = tk.Frame(card.inner, bg=COLORS['card_bg'])
        meta_row.grid(row=1, column=0, sticky='ew', pady=(8, 0))
        meta_row.grid_columnconfigure(0, weight=1)

        author_label = tk.Label(
            meta_row,
            text='',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            anchor='w',
            width=1,
        )
        author_label.grid(row=0, column=0, sticky='ew')
        bind_ellipsis_tooltip(author_label, padding=6, wraplength=360)
        set_ellipsized_label_text(author_label, f'作者: {publisher or "未知"}')

        source_meta_label = tk.Label(
            card.inner,
            text='',
            font=FONTS['small'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            anchor='w',
            width=1,
        )
        source_meta_label.grid(row=2, column=0, sticky='ew', pady=(4, 0))
        bind_ellipsis_tooltip(source_meta_label, padding=8, wraplength=380)
        set_ellipsized_label_text(source_meta_label, f'来源: {source_label}')

        # 描述行
        desc = self._skill_display_description(view)
        desc_text, desc_truncated = self._truncate_card_text(desc, self.SKILL_CARD_DESC_CHARS)
        desc_frame = tk.Frame(card.inner, bg=COLORS['card_bg'], height=self.SKILL_CARD_DESC_HEIGHT)
        desc_frame.grid(row=3, column=0, sticky='nsew', pady=(10, 0))
        desc_frame.pack_propagate(False)
        desc_label = tk.Label(
            desc_frame,
            text=desc_text,
            font=FONTS['body'],
            fg=COLORS['text_sub'],
            bg=COLORS['card_bg'],
            anchor='nw',
            justify='left',
            wraplength=max(160, self.SKILL_CARD_WIDTH - 54),
            height=self.SKILL_CARD_DESC_LINES,
        )
        desc_label.pack(fill=tk.X, anchor='nw')
        if desc_truncated:
            show_tooltip(desc_label, desc, wraplength=420)

        # 操作行
        action_row = tk.Frame(card.inner, bg=COLORS['card_bg'])
        action_row.grid(row=4, column=0, sticky='ew', pady=(12, 0))

        if is_installed and not has_update:
            installed_btn = ModernButton(
                action_row,
                '已安装',
                style='ghost',
                padx=16,
                pady=5,
                state='disabled',
            )
            installed_btn.pack(side=tk.LEFT)
        else:
            install_label = '更新' if has_update else '安装'
            install_style = 'primary'
            install_btn = ModernButton(
                action_row,
                install_label,
                style=install_style,
                padx=16,
                pady=5,
                command=lambda v=view: self._install_skill(v),
            )
            install_btn.pack(side=tk.LEFT)

        detail_btn = ModernButton(
            action_row,
            '详情',
            style='ghost',
            padx=16,
            pady=5,
            command=lambda v=view: self._show_skill_detail(v),
        )
        detail_btn.pack(side=tk.RIGHT)

        return card

    # ------------------------------------------------------------------ 安装技能
    def _install_skill(self, view):
        skill_id = view.get('id', '')
        skill_name = self._skill_display_name(view)
        is_installed = bool(view.get('is_installed', False))
        is_update = is_installed and view.get('has_update', False)
        registry_entry = view.get('registry_entry') or {}

        download_url = str(registry_entry.get('download_url', '') or '').strip()
        if not download_url:
            messagebox.showinfo('发现技能', f'技能「{skill_name}」没有可用的下载地址。', parent=self.frame.winfo_toplevel())
            return

        action_label = '下载并更新' if is_update else '安装'
        if is_installed:
            if not messagebox.askyesno(
                '覆盖确认',
                f'技能「{skill_name}」已安装。\n当前版本：{view.get("version", "未知")}\n'
                f'导入版本：{registry_entry.get("version", "未知")}\n\n'
                f'继续{action_label}吗？',
                parent=self.frame.winfo_toplevel(),
            ):
                return
        else:
            if not messagebox.askyesno(
                '安装确认',
                f'确定安装技能「{skill_name}」吗？',
                parent=self.frame.winfo_toplevel(),
            ):
                return

        self._run_background(
            lambda: self.skill_manager.download_registry_skill_zip(registry_entry),
            success_message='技能安装完成' if not is_update else '技能更新完成',
            on_success=lambda result: self._on_skill_installed(result, view),
            on_error=self._handle_skill_error,
        )

    def _on_skill_installed(self, result, original_view):
        skill_id = (result or {}).get('id', '') or original_view.get('id', '')
        for item in self._all_skills:
            if item.get('id') == skill_id:
                item['is_installed'] = True
                item['has_update'] = False
                if result:
                    item.update({k: v for k, v in result.items() if k != 'id'})
                break
        self._apply_filters()
        if callable(self.on_skill_installed):
            try:
                self.on_skill_installed()
            except Exception:
                pass

    # ------------------------------------------------------------------ 技能详情
    def _show_skill_detail(self, view):
        """打开技能详情页面（跳转到GitHub上的SKILL.md）"""
        skill_id = view.get('id', '')
        if not skill_id:
            messagebox.showinfo('技能详情', '无法获取技能ID', parent=self.frame.winfo_toplevel())
            return

        # 构建GitHub上SKILL.md的URL
        github_base_url = 'https://github.com/Abnerla/AI_paper/blob/main/Management/skills_src'
        skill_md_url = f'{github_base_url}/{skill_id}/SKILL.md'

        # 直接在浏览器中打开
        try:
            webbrowser.open(skill_md_url)
        except Exception as e:
            messagebox.showerror('打开失败', f'无法打开技能详情页面: {e}', parent=self.frame.winfo_toplevel())

    # ------------------------------------------------------------------ 刷新
    def _refresh(self):
        self._load_source_data(self._current_source)

    # ------------------------------------------------------------------ 后台任务
    def _run_background(self, work, *, success_message='', on_success=None, on_error=None):
        self.set_status('处理中，请稍候...', COLORS['warning'])

        def runner():
            error = None
            result = None
            try:
                result = work()
            except Exception as exc:
                error = exc

            def finalize():
                try:
                    if not self.frame.winfo_exists():
                        return
                except Exception:
                    return
                if error is not None:
                    self.set_status('操作失败', COLORS['error'])
                    if callable(on_error):
                        on_error(error)
                    else:
                        messagebox.showerror('发现技能', str(error), parent=self.frame.winfo_toplevel())
                    return
                if success_message:
                    self.set_status(success_message, COLORS['success'])
                if callable(on_success):
                    on_success(result)

            self.frame.after(0, finalize)

        threading.Thread(target=runner, name='DiscoverSkillsAction', daemon=True).start()

    def _handle_skill_error(self, error):
        messagebox.showerror('发现技能', str(error), parent=self.frame.winfo_toplevel())
        if isinstance(error, (SkillValidationError, SkillExecutionError)):
            self.set_status(str(error), COLORS['error'])
        else:
            self.set_status('技能操作失败', COLORS['error'])


# ======================================================================
# 仓库管理弹窗面板（独立于发现技能弹窗，关闭后自动重新打开发现技能弹窗）
# ======================================================================

class RepoManagePanel:
    def __init__(self, parent, config_mgr, skill_manager, remote_content_manager, *, set_status, close_panel=None):
        self.config = config_mgr
        self.skill_manager = skill_manager
        self.remote_content = remote_content_manager
        self.set_status = set_status
        self.close_panel = close_panel
        self.frame = tk.Frame(parent, bg=COLORS['bg_main'])

        self._build()

    def _build(self):
        scroll = ScrollablePage(self.frame, bg=COLORS['bg_main'])
        scroll.pack(fill=tk.BOTH, expand=True)
        inner = scroll.inner
        self._scroll = scroll

        # 添加仓库卡片
        add_card = CardFrame(inner, title='添加仓库', padding=16)
        add_card.pack(fill=tk.X, pady=(0, 14))

        name_frame = tk.Frame(add_card.inner, bg=COLORS['card_bg'])
        name_frame.pack(fill=tk.X, pady=(0, 8))
        tk.Label(name_frame, text='仓库名称:', font=FONTS['body'], fg=COLORS['text_main'],
                 bg=COLORS['card_bg']).pack(side=tk.LEFT)
        name_var = tk.StringVar()
        name_entry = tk.Entry(name_frame, textvariable=name_var, font=FONTS['body'],
                              bg=COLORS['input_bg'], fg=COLORS['text_main'], relief=tk.FLAT,
                              highlightthickness=1, highlightbackground=COLORS['input_border'],
                              insertbackground=COLORS['text_main'])
        name_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0), ipady=4)

        url_frame = tk.Frame(add_card.inner, bg=COLORS['card_bg'])
        url_frame.pack(fill=tk.X, pady=(0, 8))
        tk.Label(url_frame, text='索引 URL:', font=FONTS['body'], fg=COLORS['text_main'],
                 bg=COLORS['card_bg']).pack(side=tk.LEFT)
        url_var = tk.StringVar()
        url_entry = tk.Entry(url_frame, textvariable=url_var, font=FONTS['body'],
                             bg=COLORS['input_bg'], fg=COLORS['text_main'], relief=tk.FLAT,
                             highlightthickness=1, highlightbackground=COLORS['input_border'],
                             insertbackground=COLORS['text_main'])
        url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0), ipady=4)

        add_btn_row = tk.Frame(add_card.inner, bg=COLORS['card_bg'])
        add_btn_row.pack(fill=tk.X, pady=(4, 0))

        def do_add():
            name = str(name_var.get() or '').strip()
            url = str(url_var.get() or '').strip()
            if not url:
                messagebox.showwarning('添加仓库', '请输入索引 URL。', parent=self.frame.winfo_toplevel())
                return
            if not name:
                name = url.split('/')[-1] or '自定义仓库'
            self.set_status('正在验证仓库...', COLORS['warning'])

            def on_validated(data):
                try:
                    self.skill_manager.sanitize_registry_payload(data)
                    self.config.add_skills_repository({
                        'id': '',
                        'name': name,
                        'url': url,
                        'type': 'generic_json',
                        'added_at': int(_time.time()),
                        'enabled': True,
                    })
                    self.config.save()
                    self.set_status('仓库添加成功', COLORS['success'])
                    self._refresh_repo_list()
                except Exception as exc:
                    messagebox.showerror('添加仓库', f'索引格式不兼容: {exc}', parent=self.frame.winfo_toplevel())

            def on_validate_error(exc):
                messagebox.showerror('添加仓库', f'无法访问该 URL: {exc}', parent=self.frame.winfo_toplevel())

            self.remote_content.fetch_custom(url, on_success=on_validated, on_error=on_validate_error, force=True)

        ModernButton(add_btn_row, '添加仓库', style='primary', padx=14, pady=5, command=do_add).pack(side=tk.LEFT)

        # 已添加仓库列表卡片
        self._list_card_placeholder = tk.Frame(inner, bg=COLORS['bg_main'])
        self._list_card_placeholder.pack(fill=tk.BOTH, expand=True)
        self._refresh_repo_list()

        # 确保首次布局刷新（延迟稍长，等窗口完成渲染）
        def _force_refresh():
            try:
                self.frame.update_idletasks()
                self._scroll._apply_layout_refresh()
            except tk.TclError:
                pass
        try:
            self.frame.after(50, _force_refresh)
        except tk.TclError:
            pass

    def _refresh_repo_list(self):
        for child in self._list_card_placeholder.winfo_children():
            child.destroy()

        repos = self.config.get_skills_repositories()
        list_card = CardFrame(self._list_card_placeholder, title=f'已添加仓库 ({len(repos)})', padding=16)
        list_card.pack(fill=tk.BOTH, expand=True)

        if not repos:
            tk.Label(list_card.inner, text='暂无已添加的仓库。', font=FONTS['body'], fg=COLORS['text_sub'],
                     bg=COLORS['card_bg'], anchor='w').pack(fill=tk.X)
        else:
            for repo in repos:
                self._render_repo_item(list_card.inner, repo)

        # 刷新滚动区域布局
        def _force_refresh():
            try:
                self.frame.update_idletasks()
                self._scroll._apply_layout_refresh()
            except tk.TclError:
                pass
        try:
            self.frame.after(50, _force_refresh)
        except tk.TclError:
            pass

    def _render_repo_item(self, parent, repo):
        repo_id = repo.get('id', '')
        is_official = repo_id == 'official'
        enabled = repo.get('enabled', True)

        item_frame = tk.Frame(parent, bg=COLORS['surface_alt'], highlightbackground=COLORS['divider'],
                              highlightthickness=1, bd=0)
        item_frame.pack(fill=tk.X, pady=(0, 8))

        header = tk.Frame(item_frame, bg=COLORS['surface_alt'])
        header.pack(fill=tk.X, padx=14, pady=(10, 0))

        name_text = repo.get('name', repo_id)
        if is_official:
            name_text += '  (官方)'
        tk.Label(header, text=name_text, font=FONTS['body_bold'], fg=COLORS['text_main'],
                 bg=COLORS['surface_alt'], anchor='w').pack(side=tk.LEFT)

        enabled_var = tk.BooleanVar(value=enabled)

        def on_toggle(rid=repo_id, var=enabled_var):
            self.config.update_skills_repository(rid, {'enabled': var.get()})
            self.config.save()

        enable_label = tk.Label(
            header,
            text='启用',
            font=FONTS['small'],
            fg=COLORS['text_main'],
            bg=COLORS['surface_alt'],
        )
        enable_label.pack(side=tk.RIGHT, padx=(0, 4))
        ToggleSwitch(
            header,
            variable=enabled_var,
            command=on_toggle,
            bg=COLORS['surface_alt'],
        ).pack(side=tk.RIGHT)

        url_text = repo.get('url', '')
        tk.Label(item_frame, text=url_text, font=FONTS['small'], fg=COLORS['text_sub'],
                 bg=COLORS['surface_alt'], anchor='w').pack(fill=tk.X, padx=14, pady=(4, 6))

        if not is_official:
            del_row = tk.Frame(item_frame, bg=COLORS['surface_alt'])
            del_row.pack(fill=tk.X, padx=14, pady=(0, 10))

            def do_delete(rid=repo_id, rname=repo.get('name', repo_id)):
                if not messagebox.askyesno('删除仓库', f'确定删除仓库「{rname}」吗？',
                                           parent=self.frame.winfo_toplevel()):
                    return
                self.config.remove_skills_repository(rid)
                self.config.save()
                self._refresh_repo_list()

            ModernButton(del_row, '删除', style='danger', padx=10, pady=3, command=do_delete).pack(side=tk.RIGHT)
