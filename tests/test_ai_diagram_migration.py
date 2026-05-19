# -*- coding: utf-8 -*-

import inspect
import io
import json

import pytest

from modules.diagram_context import (
    DiagramReferenceError,
    MAX_IMAGE_ATTACHMENT_BYTES,
    build_image_attachments,
    format_reference_context,
    read_reference_file,
    sanitize_reference_items,
    validate_reference_url,
)
from modules.diagram_ai import DiagramAIService
from modules.diagram_mcp import DiagramMCPService, run_mcp_stdio, run_stdio, _preview_html
from modules.diagram_export import render_preview_svg, safe_diagram_filename
from modules.diagram_session_store import (
    duplicate_prompt_template,
    delete_diagram_session,
    delete_prompt_template,
    export_prompt_templates,
    import_prompt_templates,
    increment_prompt_template_run_count,
    list_diagram_sessions,
    list_prompt_templates,
    save_diagram_session,
    save_prompt_template,
    toggle_prompt_template_pinned,
)
from modules.diagram_vlm import validate_diagram_visual
from modules.diagram_tools import wrap_mx_cells
from modules.knowledge_base import KnowledgeBaseError, KnowledgeBaseStore
from modules.mcp_service_manager import MCPServiceManager
from modules.prompt_center import PromptCenter
from pages.ai_diagram_page import AIDiagramPage
from pages.home_page import HomePage
from pages.history_page import HistoryPage


class _FakeConfig:
    def __init__(self):
        self.settings = {}
        self.saved = 0

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)

    def set_setting(self, key, value):
        self.settings[key] = value

    def save(self):
        self.saved += 1


class _Var:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def test_prompt_center_registers_ai_diagram_chat_scene():
    center = PromptCenter(None)

    scene = center.get_scene_def('ai_diagram.chat')
    rendered = center.render_scene(
        'ai_diagram.chat',
        {
            'instruction': '生成流程图',
            'current_xml': '(空图)',
            'previous_xml': '',
            'pending_xml': '',
            'knowledge_context': '',
            'attachment_context': '',
            'tool_feedback': '',
        },
    )

    assert scene['page_id'] == 'ai_diagram'
    assert '"tool"' in rendered['prompt']
    assert '生成流程图' in rendered['prompt']


def test_reference_file_and_url_guard(tmp_path):
    note = tmp_path / 'note.md'
    note.write_text('流程：输入 -> 处理 -> 输出', encoding='utf-8')

    item = read_reference_file(str(note))

    assert item['kind'] == 'md'
    assert '输入' in format_reference_context([item])
    with pytest.raises(DiagramReferenceError):
        validate_reference_url('http://127.0.0.1/private')
    with pytest.raises(DiagramReferenceError):
        validate_reference_url('https://localhost/private')


def test_image_reference_builds_multimodal_attachment(tmp_path):
    image_path = tmp_path / 'diagram.png'
    image_path.write_bytes(b'\x89PNG\r\n\x1a\nfake')

    item = read_reference_file(str(image_path))
    attachments = build_image_attachments([item])

    assert item['kind'] == 'image'
    assert item['mime_type'] == 'image/png'
    assert attachments[0]['mime_type'] == 'image/png'
    assert attachments[0]['data']


def test_reference_limits_match_localized_upload_rules(tmp_path):
    items = [{'title': f'资料{i}', 'source': str(tmp_path / f'{i}.txt'), 'kind': 'txt', 'content': 'x'} for i in range(8)]
    assert len(sanitize_reference_items(items)) == 5

    image_path = tmp_path / 'large.png'
    image_path.write_bytes(b'0' * (MAX_IMAGE_ATTACHMENT_BYTES + 1))
    with pytest.raises(DiagramReferenceError):
        read_reference_file(str(image_path))


def test_ai_diagram_page_does_not_persist_temporary_references():
    page = object.__new__(AIDiagramPage)
    page.session_title_var = _Var('diagram')
    page.section_hint_var = _Var('section')
    page.use_knowledge_var = _Var(True)
    page.minimal_style_var = _Var(False)
    page.auto_vlm_var = _Var(False)
    page.custom_system_prompt_var = _Var('')
    page.pending_xml = ''
    page.messages = []
    page.selected_knowledge_context = {'context_text': 'knowledge'}
    page._current_block_with_caption = lambda: None
    page._current_caption = lambda: 'diagram'
    page._current_input_text = lambda: 'draft'

    state = AIDiagramPage.export_workspace_state(page)

    assert 'references' not in state
    assert AIDiagramPage._build_user_message_content(page, 'generate') == 'generate'


def test_ai_diagram_restore_ignores_legacy_references():
    page = object.__new__(AIDiagramPage)
    page.session_title_var = _Var('')
    page.section_hint_var = _Var('')
    page.use_knowledge_var = _Var(False)
    page.minimal_style_var = _Var(False)
    page.auto_vlm_var = _Var(False)
    page.custom_system_prompt_var = _Var('')
    page.selected_knowledge_context = {'context_text': 'old'}
    page._set_input_text = lambda *_args, **_kwargs: None
    page._refresh_all = lambda: None

    AIDiagramPage.restore_workspace_state(page, {
        'caption': 'diagram',
        'use_knowledge_context': True,
        'references': [{'title': 'legacy', 'content': 'text'}],
        'messages': [],
    })

    assert page.use_knowledge_var.get() is True
    assert page.selected_knowledge_context == {}


def test_ai_diagram_chat_toolbar_is_consolidated():
    chat_source = inspect.getsource(AIDiagramPage._build_chat_panel)
    conversation_source = inspect.getsource(AIDiagramPage._build_conversation_panel)
    session_actions_source = inspect.getsource(AIDiagramPage._build_session_bar)
    chat_actions_source = inspect.getsource(AIDiagramPage._build_chat_title_actions)
    canvas_actions_source = inspect.getsource(AIDiagramPage._build_canvas_title_actions)

    for text in ('提示模板', '保存模板', '消息操作', '复制记录'):
        assert text not in chat_source
    assert '编辑重发' in chat_source
    assert '重新生成' in chat_source
    assert '清空输入' not in chat_actions_source
    assert '清空消息' in chat_actions_source
    assert '清空消息' not in session_actions_source
    assert session_actions_source.index('知识库管理') < session_actions_source.index('图表偏好') < session_actions_source.index('保存快照')
    for text in ('新建对话', '保存会话', '会话管理'):
        assert text not in session_actions_source
    assert conversation_source.index('复制') < conversation_source.index('保存') < conversation_source.index('新建') < conversation_source.index('管理会话')
    for text in ('复制记录', '新建对话', '保存会话', '会话管理'):
        assert text not in conversation_source
    assert '查询图形库' not in session_actions_source
    assert not hasattr(AIDiagramPage, '_query_shape_library')
    assert 'tools_row' in session_actions_source
    assert '知识库管理' in session_actions_source
    assert '使用知识库上下文' not in session_actions_source
    assert 'Checkbutton' not in session_actions_source
    assert '恢复上一版' not in session_actions_source
    assert '校验图表' in canvas_actions_source
    assert '恢复上一版' in canvas_actions_source
    assert canvas_actions_source.index('校验图表') < canvas_actions_source.index('恢复上一版')
    for text in ('视觉校验', '版本历史', '导出图表'):
        assert text not in canvas_actions_source
    assert not hasattr(AIDiagramPage, '_show_message_manager')
    assert not hasattr(AIDiagramPage, '_show_prompt_template_manager')
    assert not hasattr(AIDiagramPage, '_save_current_prompt_template')


def test_history_page_detects_ai_diagram_export_options():
    page = object.__new__(HistoryPage)

    bundle = {
        'selected': {'module': 'AI图表'},
        'display': {
            'page_state_id': 'ai_diagram',
            'workspace_state': {
                'current_block': {
                    'caption': '流程图',
                    'mxgraph_xml': '<mxGraphModel><root /></mxGraphModel>',
                    'json_graph': {'nodes': [], 'edges': []},
                }
            },
        },
    }

    assert HistoryPage._bundle_has_diagram_block(page, bundle) is True
    assert [item[1] for item in HistoryPage.DIAGRAM_EXPORT_OPTIONS] == [
        'drawio',
        'xml',
        'png',
        'svg',
        'drawio.svg',
    ]


def test_history_page_exports_ai_diagram_with_shared_exporter(tmp_path, monkeypatch):
    page = object.__new__(HistoryPage)
    page.frame = None
    page.set_status = lambda text, *_args: setattr(page, 'status_text', text)
    page._get_paper_title = lambda _record: '流程图'

    display = {
        'time': '2026-05-19 18:00:00',
        'workspace_state': {
            'current_block': {
                'caption': '流程图',
                'mxgraph_xml': '<mxGraphModel><root /></mxGraphModel>',
                'json_graph': {'nodes': [], 'edges': []},
            }
        },
    }
    target = tmp_path / 'diagram.drawio'
    calls = []

    monkeypatch.setattr('pages.history_page.filedialog.asksaveasfilename', lambda **_kwargs: str(target))
    monkeypatch.setattr('pages.history_page.messagebox.showinfo', lambda *_args, **_kwargs: None)
    monkeypatch.setattr('pages.history_page.messagebox.showwarning', lambda *_args, **_kwargs: None)
    monkeypatch.setattr('pages.history_page.messagebox.showerror', lambda *_args, **_kwargs: None)

    def _fake_export(path, xml_text, *, block=None, native_exporter=None):
        calls.append((path, xml_text, block, native_exporter))
        return {'note': '已导出 draw.io XML。', 'path': path}

    monkeypatch.setattr('pages.history_page.export_diagram_file', _fake_export)

    HistoryPage._export_selected_diagram(page, display, 'drawio')

    assert calls == [(str(target), '<mxGraphModel><root /></mxGraphModel>', display['workspace_state']['current_block'], None)]
    assert '已导出 draw.io XML。' in page.status_text


def test_home_exposes_mcp_services_entry_and_ai_diagram_removes_start_button():
    home_source = inspect.getsource(HomePage._build_hero)
    session_source = inspect.getsource(AIDiagramPage._build_session_bar)

    assert "'提示词'" in home_source
    assert "'MCP 服务'" in home_source
    assert home_source.index("'提示词'") < home_source.index("'MCP 服务'")
    assert '启动 MCP' not in session_source


def test_mcp_center_default_ai_diagram_config():
    from modules.config import ConfigManager

    config = object.__new__(ConfigManager)
    center = ConfigManager._sanitize_mcp_center(config, {})

    assert 'ai_diagram_builtin' in center['services']
    service = center['services']['ai_diagram_builtin']
    assert service['type'] == 'builtin_ai_diagram'
    assert service['enabled'] is True
    assert service['auto_start'] is True


def test_mcp_service_manager_builtin_start_is_idempotent():
    class _Config:
        def __init__(self):
            from modules.config import ConfigManager
            self._helper = object.__new__(ConfigManager)
            self._helper._safe_int_val = lambda value, default=0: int(value or default or 0)
            self.records = self._helper._sanitize_mcp_center({})['services']

        def get_mcp_service_records(self):
            return self.records

        def get_mcp_service_record(self, service_id):
            return self.records.get(service_id, {})

    manager = MCPServiceManager(_Config())
    first = manager.start_service('ai_diagram_builtin')
    second = manager.start_service('ai_diagram_builtin')
    manager.stop_all()

    assert first['running'] is True
    assert second['url'] == first['url']


def test_knowledge_base_imports_local_text_types_and_url(tmp_path, monkeypatch):
    store = KnowledgeBaseStore(tmp_path)
    project = store.create_project('diagram refs')
    store.set_active_project(project['id'])

    for suffix in ('.markdown', '.json', '.csv', '.xml'):
        path = tmp_path / f'doc{suffix}'
        path.write_text('local context', encoding='utf-8')
        document = store.import_document(project['id'], str(path), bound_scene_ids=['ai_diagram.chat'])
        assert document['char_count'] == len('local context')

    def _fake_read_reference_url(url, resolver=None):
        return {'title': 'example.com', 'source': url, 'content': 'url context'}

    monkeypatch.setattr('modules.knowledge_base.read_reference_url', _fake_read_reference_url)
    url_doc = store.import_url(project['id'], 'https://example.com/ref', bound_scene_ids=['ai_diagram.chat'])
    context = store.build_context(
        project['id'],
        [url_doc['id']],
        'ai_diagram.chat',
        total_char_limit=1000,
        per_document_char_limit=1000,
    )

    assert url_doc['source_type'] == 'url'
    assert 'url context' in context['context_text']
    assert store.delete_project_documents(project['id']) == 5
    assert store.list_documents(project['id']) == []


def test_knowledge_base_url_import_blocks_local_addresses(tmp_path):
    store = KnowledgeBaseStore(tmp_path)
    project = store.create_project('diagram refs')

    with pytest.raises(KnowledgeBaseError):
        store.import_url(project['id'], 'http://127.0.0.1/private')


def test_diagram_ai_auto_continues_partial_display():
    class _Api:
        def __init__(self):
            self.calls = 0
            self.systems = []

        def call_json_sync(self, **kwargs):
            self.calls += 1
            self.systems.append(kwargs.get('system', ''))
            if self.calls == 1:
                return {
                    'message': '开始生成。',
                    'tool': 'display_diagram',
                    'xml': '<mxCell id="a" value="开始" vertex="1" parent="1">',
                }
            return {
                'message': '续写完成。',
                'tool': 'append_diagram',
                'xml': '<mxGeometry x="80" y="80" width="120" height="60" as="geometry" /></mxCell>',
            }

    events = []
    service = DiagramAIService(_Api())
    result = service.run_instruction('生成流程图', minimal_style=True, custom_system_message='使用中文标签', event_callback=events.append)

    assert result.block
    assert result.pending_xml == ''
    assert 'id="a"' in result.block['mxgraph_xml']
    assert any(event.get('type') == 'continuation' for event in events)
    assert '简约' in service.api_client.systems[0]
    assert '使用中文标签' in service.api_client.systems[0]


def test_visual_validation_skips_without_multimodal_support():
    class _TextOnlyApi:
        def supports_multimodal_attachments(self, **_kwargs):
            return False

        def call_json_sync(self, **_kwargs):
            raise AssertionError('不应调用文本模型')

    result = validate_diagram_visual(_TextOnlyApi(), {'json_graph': {'nodes': [], 'edges': []}})

    assert result.skipped is True
    assert '不支持图片输入' in result.summary


def test_preview_svg_export_is_explicit_fallback():
    pytest.importorskip('PIL')
    xml = wrap_mx_cells("""
    <mxCell id="a" value="开始" vertex="1" parent="1">
      <mxGeometry x="80" y="80" width="120" height="60" as="geometry" />
    </mxCell>
    """)
    block = {
        'caption': '流程图',
        'json_graph': {
            'nodes': [{'id': 'a', 'label': '开始'}],
            'edges': [],
            'groups': [],
            'meta': {},
        },
    }

    svg = render_preview_svg(block, xml_text=xml, include_drawio_metadata=True)

    assert safe_diagram_filename('A/B 图表') == 'A_B_图表'
    assert '非 draw.io 原生渲染' in svg
    assert '<metadata><mxfile>' in svg


def test_diagram_session_and_template_store_roundtrip():
    config = _FakeConfig()
    state = {
        'caption': '流程图',
        'messages': [{'role': 'user', 'content': '生成流程图'}],
        'references': [{'title': '资料', 'content': '文本'}],
    }

    session = save_diagram_session(config, state, title='流程图会话')
    template = save_prompt_template(config, '生成一个三阶段流程图', name='三阶段流程')
    toggle_prompt_template_pinned(config, template['id'])
    increment_prompt_template_run_count(config, template['id'])
    duplicate = duplicate_prompt_template(config, template['id'])

    assert list_diagram_sessions(config, query='流程图')[0]['id'] == session['id']
    templates = list_prompt_templates(config, query='三阶段')
    assert templates[0]['id'] == template['id']
    assert templates[0]['pinned'] is True
    assert templates[0]['run_count'] == 1
    exported = export_prompt_templates(config)
    delete_prompt_template(config, duplicate['id'])
    imported = import_prompt_templates(config, exported)
    assert imported == []
    delete_diagram_session(config, session['id'])
    delete_prompt_template(config, template['id'])
    assert list_diagram_sessions(config) == []
    assert list_prompt_templates(config) == []
    assert config.saved >= 4


def test_diagram_mcp_service_edit_and_export():
    updates = []
    service = DiagramMCPService(on_update=lambda session_id, xml: updates.append((session_id, xml)))
    session = service.start_session(notify=False)
    assert updates == []

    service = DiagramMCPService()
    session = service.start_session()
    xml = wrap_mx_cells("""
    <mxCell id="a" value="开始" vertex="1" parent="1">
      <mxGeometry x="80" y="80" width="120" height="60" as="geometry" />
    </mxCell>
    """)

    created = service.create_new_diagram(session['session_id'], xml)
    edited = service.edit_diagram(
        session['session_id'],
        [{
            'operation': 'update',
            'cell_id': 'a',
            'new_xml': '<mxCell id="a" value="完成" vertex="1" parent="1"><mxGeometry x="80" y="80" width="120" height="60" as="geometry" /></mxCell>',
        }],
    )
    exported = service.export_diagram(session['session_id'], 'drawio')

    assert created['stats']['vertex_count'] == 1
    assert edited['ok'] is True
    assert 'value="完成"' in service.get_diagram(session['session_id'])['xml']
    assert '<mxGraphModel' in exported['data']


def test_diagram_mcp_history_preview_and_restore():
    service = DiagramMCPService()
    service.preview_base_url = 'http://127.0.0.1:6002'
    session = service.start_session()
    session_id = session['session_id']
    first_xml = wrap_mx_cells("""
    <mxCell id="a" value="v1" vertex="1" parent="1">
      <mxGeometry x="80" y="80" width="120" height="60" as="geometry" />
    </mxCell>
    """)
    second_xml = wrap_mx_cells("""
    <mxCell id="a" value="v2" vertex="1" parent="1">
      <mxGeometry x="80" y="80" width="120" height="60" as="geometry" />
    </mxCell>
    """)

    assert session['preview_url'].startswith('http://127.0.0.1:6002/')
    service.create_new_diagram(session_id, first_xml)
    service.sync_diagram(session_id, second_xml, exports={'svg': '<svg>native</svg>'})
    state = service.get_diagram(session_id)
    restored = service.restore_history(session_id, 1)
    exported = service.export_diagram(session_id, 'svg')

    assert state['history_count'] >= 2
    assert 'v1' in restored['xml']
    assert exported.get('data') or exported.get('data_base64')


def test_diagram_mcp_browser_state_and_native_export():
    service = DiagramMCPService()
    session = service.start_session()
    session_id = session['session_id']

    state = service.get_browser_state(session_id)
    service.store_browser_export(session_id, '<svg>browser-native</svg>', 'svg')
    exported = service.export_diagram(session_id, 'svg')
    html = _preview_html()

    assert state['version'] >= 1
    assert 'browser-native' in exported['data']
    assert '本地 MCP' in html
    assert 'draw.io' in html


def test_diagram_mcp_stdio_protocol_tools():
    requests = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}},
        {
            'jsonrpc': '2.0',
            'id': 3,
            'method': 'tools/call',
            'params': {'name': 'start_session', 'arguments': {}},
        },
        {
            'jsonrpc': '2.0',
            'id': 4,
            'method': 'tools/call',
            'params': {'name': 'get_diagram', 'arguments': {}},
        },
        {'jsonrpc': '2.0', 'id': 5, 'method': 'prompts/get', 'params': {'name': 'diagram-workflow'}},
    ]
    stdin = io.StringIO('\n'.join(json.dumps(item, ensure_ascii=False) for item in requests) + '\n')
    stdout = io.StringIO()

    run_mcp_stdio(DiagramMCPService(), stdin=stdin, stdout=stdout)

    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert responses[0]['result']['serverInfo']['name'] == 'ai-paper-diagram-mcp'
    assert any(item['name'] == 'edit_diagram' for item in responses[1]['result']['tools'])
    start_payload = json.loads(responses[2]['result']['content'][0]['text'])
    assert start_payload['session_id'].startswith('mcp-')
    get_payload = json.loads(responses[3]['result']['content'][0]['text'])
    assert '<mxGraphModel' in get_payload['xml']
    assert 'edit_diagram' in responses[4]['result']['messages'][0]['content']['text']


def test_diagram_mcp_jsonl_compatibility():
    stdin = io.StringIO(json.dumps({'tool': 'start_session', 'arguments': {}}, ensure_ascii=False) + '\n')
    stdout = io.StringIO()

    run_stdio(DiagramMCPService(), stdin=stdin, stdout=stdout)

    payload = json.loads(stdout.getvalue())
    assert payload['ok'] is True
    assert payload['result']['session_id'].startswith('mcp-')
