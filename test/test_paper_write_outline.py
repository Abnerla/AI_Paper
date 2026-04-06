import unittest

from pages.paper_write_page import PaperWritePage


class DummyEntry:
    def __init__(self, value=''):
        self.value = value

    def get(self):
        return self.value

    def delete(self, _start, _end=None):
        self.value = ''

    def insert(self, _index, value):
        self.value = str(value)


class DummyText:
    def __init__(self, value=''):
        self.value = value

    def get(self, _start='1.0', _end=None):
        return self.value

    def delete(self, _start, _end=None):
        self.value = ''

    def insert(self, _index, value):
        self.value = str(value)


class DummyVar:
    def __init__(self, value=''):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class DummyFrame:
    def after_idle(self, func):
        if callable(func):
            func()


def build_page(structure=None, reference_style='GB/T 7714'):
    page = PaperWritePage.__new__(PaperWritePage)
    structure = structure or {'sections': {}, 'order': [], 'levels': {}, 'parents': {}}
    page._sections = dict(structure.get('sections', {}))
    page._section_order = list(structure.get('order', []))
    page._section_levels = dict(structure.get('levels', {}))
    page._section_parent = dict(structure.get('parents', {}))
    page._section_children = {}
    page._section_formats = {title: [] for title in page._section_order}
    page._collapsed_sections = set()
    page._editor_section_source = ''
    page._outline_selected = DummyVar('')
    page.outline_text = DummyText('')
    page.section_entry = DummyEntry('')
    page.topic_entry = DummyEntry('论文标题')
    page.edit_text = DummyText('')
    page.frame = DummyFrame()
    page.ref_var = DummyVar(reference_style)
    page._refresh_outline_list = lambda: None
    page._select_section = lambda title, touch_context=False: page._outline_selected.set(title)
    page._touch_context_revision = lambda: None
    page._update_stats = lambda: None
    page._capture_selection_snapshot = lambda: None
    page._schedule_workspace_state_save = lambda *args, **kwargs: None
    page._store_current_editor_content = lambda: None
    page._set_editor_content = lambda text, _formats=None: page.edit_text.insert('1.0', text)
    page._serialize_editor_format_spans = lambda: []
    page._rebuild_section_children()
    return page


def build_restore_test_page():
    structure = {
        'sections': {'# 引言': '引言正文'},
        'order': ['# 引言'],
        'levels': {'# 引言': 1},
        'parents': {'# 引言': ''},
    }
    page = build_page(structure)
    page.style_var = DummyVar('学术论文')
    page.subject_entry = DummyEntry('')
    page.wcount_var = DummyVar('1000')
    page._editor_bg_indicator_color = PaperWritePage.DEFAULT_BG_SWATCH_COLOR
    page._outline_level_fonts = {'stale_cache': object()}
    page._level_font_styles = {k: dict(v) for k, v in PaperWritePage.LEVEL_STYLE_DEFAULTS.items()}
    page._current_cn_font = None
    page._current_en_font = None
    page._current_size_pt = 12
    page._context_revision = 0
    page._update_background_color_button = lambda: None
    page._set_editor_content = lambda text, _formats=None, reset_undo=False: page.edit_text.insert('1.0', text)

    apply_calls = []

    def apply_level_font_to_editor():
        style = page._level_font_styles.get('body', PaperWritePage.LEVEL_STYLE_DEFAULTS['body'])
        page._current_cn_font = style.get('font', '宋体')
        page._current_en_font = style.get('font_en', 'Times New Roman')
        page._current_size_pt = int(style.get('size_pt', 12))
        apply_calls.append((page._current_cn_font, page._current_en_font, page._current_size_pt))

    page._apply_level_font_to_editor = apply_level_font_to_editor
    page._apply_level_font_calls = apply_calls
    return page


def build_restore_state(level_font_styles):
    return {
        'topic': '测试标题',
        'style': '学术论文',
        'subject': '测试方向',
        'reference_style': 'GB/T 7714',
        'outline_text': '# 引言',
        'sections': {'# 引言': '引言正文'},
        'section_formats': {'# 引言': []},
        'section_order': ['# 引言'],
        'section_levels': {'# 引言': 1},
        'section_parent': {'# 引言': ''},
        'collapsed_sections': [],
        'selected_section': '',
        'current_section': '# 引言',
        'editor_section_source': '# 引言',
        'target_word_count': '1000',
        'editor_text': '引言正文',
        'editor_toolbar_bg_color': PaperWritePage.DEFAULT_BG_SWATCH_COLOR,
        'snapshots': [],
        'selection_snapshot': {},
        'context_revision': 3,
        'level_font_styles': level_font_styles,
    }


class PaperWriteOutlineParsingTests(unittest.TestCase):
    def test_parse_outline_heading_levels(self):
        cases = [
            ('**第2章 历史知识的形式化建模**', ('第2章 历史知识的形式化建模', 1)),
            ('第2章 历史知识的形式化建模', ('第2章 历史知识的形式化建模', 1)),
            ('1 研究背景', ('1 研究背景', 1)),
            ('1.1 研究现状', ('1.1 研究现状', 2)),
            ('1.1.1 技术瓶颈', ('1.1.1 技术瓶颈', 3)),
            ('一、研究设计', ('一、 研究设计', 1)),
            ('（一）研究方法', ('（一） 研究方法', 2)),
            ('（1）实施路径', ('（1） 实施路径', 3)),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(PaperWritePage._parse_outline_heading(text), expected)

    def test_normalize_outline_structure_merges_keywords_and_promotes_reference(self):
        outline_text = '\n'.join([
            '摘要',
            '中文摘要正文',
            '关键词',
            '关键词甲；关键词乙',
            'Abstract',
            'English abstract body',
            'Keywords',
            'keyword a; keyword b',
            '1.1 研究背景',
            '前置误编号正文',
            '1.1.1 技术瓶颈',
            '前置误编号子节正文',
            '第一章 方法设计',
            '章节正文',
            '参考文献',
            '[1] 文献A',
        ])

        normalized = PaperWritePage._normalize_outline_structure(
            PaperWritePage._build_outline_structure(outline_text)
        )

        self.assertEqual(
            normalized['order'],
            [
                '# 中文摘要',
                '# 英文摘要',
                '# 引言',
                '## 研究背景',
                '### 技术瓶颈',
                '第一章 方法设计',
                '# 参考文献',
            ],
        )
        self.assertEqual(
            normalized['sections']['# 中文摘要'],
            '中文摘要正文\n\n关键词：关键词甲；关键词乙',
        )
        self.assertEqual(
            normalized['sections']['# 英文摘要'],
            'English abstract body\n\nKeywords: keyword a; keyword b',
        )
        self.assertEqual(normalized['sections']['# 参考文献'], '[1] 文献A')
        self.assertEqual(normalized['parents']['## 研究背景'], '# 引言')
        self.assertEqual(normalized['parents']['### 技术瓶颈'], '## 研究背景')

    def test_normalize_outline_structure_preserves_xulun_name(self):
        outline_text = '\n'.join([
            '中文摘要',
            '中文摘要正文',
            '绪论',
            '绪论正文',
            '第一章 研究设计',
            '章节正文',
        ])

        normalized = PaperWritePage._normalize_outline_structure(
            PaperWritePage._build_outline_structure(outline_text)
        )

        self.assertEqual(
            normalized['order'][:5],
            ['# 中文摘要', '# 英文摘要', '# 绪论', '第一章 研究设计', '# 参考文献'],
        )
        self.assertEqual(normalized['sections']['# 英文摘要'], '')
        self.assertEqual(normalized['sections']['# 绪论'], '绪论正文')

    def test_write_abstract_to_section_merges_keywords_into_chinese_abstract(self):
        page = build_page(PaperWritePage._build_default_front_matter_structure())
        page._sections['# 英文摘要'] = 'Existing English Abstract'

        abstract_title = page._write_abstract_to_section('【摘要】中文摘要内容\n\n【关键词】词1；词2')

        self.assertEqual(abstract_title, '# 中文摘要')
        self.assertEqual(page._sections['# 中文摘要'], '中文摘要内容\n\n关键词：词1；词2')
        self.assertEqual(page._sections['# 英文摘要'], 'Existing English Abstract')
        self.assertNotIn('## 中文关键词', page._sections)
        self.assertNotIn('## 英文关键词', page._sections)

    def test_collect_full_text_for_abstract_excludes_abstracts_and_references(self):
        structure = {
            'sections': {
                '# 中文摘要': '中文摘要内容\n\n关键词：词1；词2',
                '# 英文摘要': 'English abstract content\n\nKeywords: keyword1; keyword2',
                '# 引言': '引言正文',
                '第一章 研究设计': '章节正文',
                '# 参考文献': '[1] 文献A',
            },
            'order': ['# 中文摘要', '# 英文摘要', '# 引言', '第一章 研究设计', '# 参考文献'],
            'levels': {
                '# 中文摘要': 1,
                '# 英文摘要': 1,
                '# 引言': 1,
                '第一章 研究设计': 1,
                '# 参考文献': 1,
            },
            'parents': {
                '# 中文摘要': '',
                '# 英文摘要': '',
                '# 引言': '',
                '第一章 研究设计': '',
                '# 参考文献': '',
            },
        }
        page = build_page(structure)

        full_text = page._collect_full_text_for_abstract()

        self.assertIn('# 论文标题', full_text)
        self.assertIn('# 引言\n引言正文', full_text)
        self.assertIn('第一章 研究设计\n章节正文', full_text)
        self.assertNotIn('中文摘要内容', full_text)
        self.assertNotIn('English abstract content', full_text)
        self.assertNotIn('[1] 文献A', full_text)

    def test_strip_reference_heading_supports_variants(self):
        page = build_page()
        cases = [
            ('参考文献\n[1] 文献甲', '[1] 文献甲'),
            ('【参考文献】\n[1] 文献甲', '[1] 文献甲'),
            ('# 参考文献\n[1] 文献甲', '[1] 文献甲'),
            ('## 参考文献\n[1] 文献甲', '[1] 文献甲'),
            ('**参考文献**\n[1] 文献甲', '[1] 文献甲'),
            ('**参考文献**（严格遵循GB/T 7714-2015格式）\n[1] 文献甲', '[1] 文献甲'),
            ('参考文献：\n[1] 文献甲', '[1] 文献甲'),
            ('References\n[1] Source A', '[1] Source A'),
            ('---\n\n**参考文献**（严格遵循GB/T 7714-2015格式）\n[1] 文献甲', '[1] 文献甲'),
        ]
        for raw_text, expected in cases:
            with self.subTest(raw_text=raw_text):
                self.assertEqual(page._strip_reference_heading(raw_text), expected)

    def test_extract_references_from_section_result_strips_separator_and_heading(self):
        page = build_page()

        clean_result, references_text = page._extract_references_from_section_result(
            '章节正文第一段。\n\n---\n\n**参考文献**（严格遵循GB/T 7714-2015格式）\n[1] 文献甲\n[2] 文献乙'
        )

        self.assertEqual(clean_result, '章节正文第一段。')
        self.assertEqual(references_text, '[1] 文献甲\n[2] 文献乙')

    def test_reference_block_is_not_written_back_to_current_section_body(self):
        structure = {
            'sections': {
                '第一章 研究背景': '已有正文',
                '# 参考文献': '[1] 旧文献',
            },
            'order': ['第一章 研究背景', '# 参考文献'],
            'levels': {'第一章 研究背景': 1, '# 参考文献': 1},
            'parents': {'第一章 研究背景': '', '# 参考文献': ''},
        }
        page = build_page(structure)

        clean_result, references_text = page._extract_references_from_section_result(
            '新增正文见[1][2]。\n\n---\n**参考文献**（严格遵循GB/T 7714-2015格式）\n[1] 新文献\n[2] 旧文献'
        )
        merged, _merged_formats, reference_title = page._sync_document_references_after_section_write(
            '第一章 研究背景',
            page._sections['第一章 研究背景'],
            clean_result,
            references_text,
        )

        self.assertEqual(reference_title, '# 参考文献')
        self.assertEqual(merged, '已有正文\n\n新增正文见[1][2]。')
        self.assertEqual(page._sections['第一章 研究背景'], '已有正文\n\n新增正文见[1][2]。')
        self.assertNotIn('参考文献', page._sections['第一章 研究背景'])
        self.assertNotIn('[1] 新文献', page._sections['第一章 研究背景'])
        self.assertEqual(page._sections['# 参考文献'], '[1] 新文献\n[2] 旧文献')

    def test_extract_references_from_section_result_supports_trailing_numbered_entries_without_heading(self):
        page = build_page()

        clean_result, references_text = page._extract_references_from_section_result(
            '章节正文见[1][2]。\n\n[1] 文献甲\n[2] 文献乙'
        )

        self.assertEqual(clean_result, '章节正文见[1][2]。')
        self.assertEqual(references_text, '[1] 文献甲\n[2] 文献乙')

    def test_merge_section_text_preserves_spaces(self):
        self.assertEqual(
            PaperWritePage._merge_section_text('  首段保留前导空格', '次段保留结尾空格  '),
            '  首段保留前导空格\n\n次段保留结尾空格  ',
        )
        self.assertEqual(
            PaperWritePage._normalize_outline_section_body('  段首空格\n正文中  保留空格\n    \n结尾空格  '),
            '  段首空格\n正文中  保留空格\n    \n结尾空格  ',
        )

    def test_sync_document_references_after_section_write_reorders_global_numbers(self):
        structure = {
            'sections': {
                '# 引言': '引言正文',
                '第一章 理论分析': '已有分析',
                '第二章 实验结果': '实验结果见[1,2]，连续引用[1-2]。',
                '# 参考文献': '[1] 旧文献甲\n[2] 旧文献乙',
            },
            'order': ['# 引言', '第一章 理论分析', '第二章 实验结果', '# 参考文献'],
            'levels': {
                '# 引言': 1,
                '第一章 理论分析': 1,
                '第二章 实验结果': 1,
                '# 参考文献': 1,
            },
            'parents': {
                '# 引言': '',
                '第一章 理论分析': '',
                '第二章 实验结果': '',
                '# 参考文献': '',
            },
        }
        page = build_page(structure)

        merged, merged_formats, reference_title = page._sync_document_references_after_section_write(
            '第一章 理论分析',
            page._sections['第一章 理论分析'],
            '新增引用[1,2]，连续引用[1-2]。',
            '[1] 新文献丙\n[2] 旧文献甲',
        )

        self.assertEqual(reference_title, '# 参考文献')
        self.assertEqual(merged_formats, [])
        self.assertEqual(merged, '已有分析\n\n新增引用[1-2]，连续引用[1-2]。')
        self.assertEqual(page._sections['第一章 理论分析'], merged)
        self.assertEqual(page._sections['第二章 实验结果'], '实验结果见[2-3]，连续引用[2-3]。')
        self.assertEqual(
            page._sections['# 参考文献'],
            '[1] 新文献丙\n[2] 旧文献甲\n[3] 旧文献乙',
        )

    def test_write_references_to_section_rebuilds_reference_body_only(self):
        structure = {
            'sections': {
                '# 引言': '引言引用[1]。',
                '# 参考文献': '[1] 文献甲',
            },
            'order': ['# 引言', '# 参考文献'],
            'levels': {'# 引言': 1, '# 参考文献': 1},
            'parents': {'# 引言': '', '# 参考文献': ''},
        }
        page = build_page(structure)

        reference_title = page._write_references_to_section('[2] 文献乙\n[1] 文献甲')

        self.assertEqual(reference_title, '# 参考文献')
        self.assertEqual(page._sections['# 引言'], '引言引用[1]。')
        self.assertEqual(page._sections['# 参考文献'], '[1] 文献甲\n[2] 文献乙')


class PaperWriteFontRestoreTests(unittest.TestCase):
    def test_restore_workspace_state_applies_saved_fonts_before_first_outline_refresh(self):
        page = build_restore_test_page()
        refresh_snapshots = []

        def refresh_outline_list():
            refresh_snapshots.append(
                {
                    'h1_font': page._level_font_styles['h1']['font'],
                    'body_font': page._level_font_styles['body']['font'],
                    'cache': dict(page._outline_level_fonts),
                }
            )

        page._refresh_outline_list = refresh_outline_list
        state = build_restore_state(
            {
                'h1': {'font': '仿宋', 'font_en': 'Arial', 'size_name': '三号', 'size_pt': 16},
                'body': {'font': '楷体', 'font_en': 'Calibri', 'size_name': '小四', 'size_pt': 12},
            }
        )

        page.restore_workspace_state(state)

        self.assertEqual(len(refresh_snapshots), 1)
        self.assertEqual(refresh_snapshots[0]['h1_font'], '仿宋')
        self.assertEqual(refresh_snapshots[0]['body_font'], '楷体')
        self.assertEqual(refresh_snapshots[0]['cache'], {})
        self.assertEqual(page._current_cn_font, '楷体')
        self.assertEqual(page._current_en_font, 'Calibri')
        self.assertEqual(page._current_size_pt, 12)

    def test_restore_workspace_state_rebuilds_body_font_from_saved_style(self):
        page = build_restore_test_page()
        page._refresh_outline_list = lambda: None
        state = build_restore_state(
            {
                'body': {'font': '仿宋', 'font_en': 'Arial', 'size_name': '四号', 'size_pt': 14},
            }
        )

        page.restore_workspace_state(state)

        self.assertEqual(page._current_cn_font, '仿宋')
        self.assertEqual(page._current_en_font, 'Arial')
        self.assertEqual(page._current_size_pt, 14)
        self.assertEqual(page._apply_level_font_calls[-1], ('仿宋', 'Arial', 14))

    def test_restore_workspace_state_fills_missing_font_fields_with_defaults(self):
        page = build_restore_test_page()
        page._refresh_outline_list = lambda: None
        state = build_restore_state({'body': {'font': '仿宋'}})

        page.restore_workspace_state(state)

        body_defaults = PaperWritePage.LEVEL_STYLE_DEFAULTS['body']
        h1_defaults = PaperWritePage.LEVEL_STYLE_DEFAULTS['h1']
        self.assertEqual(page._level_font_styles['body']['font'], '仿宋')
        self.assertEqual(page._level_font_styles['body']['font_en'], body_defaults['font_en'])
        self.assertEqual(page._level_font_styles['body']['size_name'], body_defaults['size_name'])
        self.assertEqual(page._level_font_styles['body']['size_pt'], body_defaults['size_pt'])
        self.assertEqual(page._level_font_styles['h1'], h1_defaults)


if __name__ == '__main__':
    unittest.main()
