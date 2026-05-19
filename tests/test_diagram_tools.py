# -*- coding: utf-8 -*-

from modules.diagram_blocks import new_diagram_block
from modules.diagram_mcp import DiagramMCPService
from modules.diagram_tools import (
    analyze_mxgraph_xml,
    apply_diagram_operations,
    is_mxcell_xml_complete,
    validate_mxgraph_xml,
    wrap_mx_cells,
)
from modules.table_blocks import blocks_to_plain_text, sanitize_blocks


def _sample_cells():
    return """
    <mxCell id="a" value="开始" vertex="1" parent="1">
      <mxGeometry x="80" y="80" width="120" height="60" as="geometry" />
    </mxCell>
    <mxCell id="b" value="结束" vertex="1" parent="1">
      <mxGeometry x="260" y="80" width="120" height="60" as="geometry" />
    </mxCell>
    <mxCell id="e1" value="" edge="1" parent="1" source="a" target="b">
      <mxGeometry relative="1" as="geometry" />
    </mxCell>
    """


def test_wrap_mx_cells_builds_valid_model():
    xml = wrap_mx_cells(_sample_cells())

    assert xml.startswith('<mxGraphModel')
    stats = validate_mxgraph_xml(xml)
    assert stats['cell_count'] == 5
    assert stats['vertex_count'] == 2
    assert stats['edge_count'] == 1


def test_apply_diagram_operations_add_update_delete_cascade():
    xml = wrap_mx_cells(_sample_cells())
    added_cell = """
    <mxCell id="c" value="输出" vertex="1" parent="1">
      <mxGeometry x="440" y="80" width="120" height="60" as="geometry" />
    </mxCell>
    """
    updated_cell = """
    <mxCell id="b" value="完成" vertex="1" parent="1">
      <mxGeometry x="260" y="80" width="120" height="60" as="geometry" />
    </mxCell>
    """

    updated, errors = apply_diagram_operations(
        xml,
        [
            {'operation': 'add', 'cell_id': 'c', 'new_xml': added_cell},
            {'operation': 'update', 'cell_id': 'b', 'new_xml': updated_cell},
            {'operation': 'delete', 'cell_id': 'a'},
        ],
    )

    assert errors == []
    assert 'id="c"' in updated
    assert 'value="完成"' in updated
    assert 'id="a"' not in updated
    assert 'id="e1"' not in updated
    validate_mxgraph_xml(updated)


def test_mcp_edit_reuses_diagram_operation_validation():
    service = DiagramMCPService()
    session = service.start_session(wrap_mx_cells(_sample_cells()))

    result = service.edit_diagram(
        session['session_id'],
        [{'operation': 'delete', 'cell_id': 'a'}],
    )

    assert result['ok'] is True
    assert 'id="a"' not in result['xml']
    assert 'id="e1"' not in result['xml']
    validate_mxgraph_xml(result['xml'])


def test_is_mxcell_xml_complete_detects_partial_fragment():
    assert is_mxcell_xml_complete('<mxCell id="a" parent="1" />')
    assert not is_mxcell_xml_complete('<mxCell id="a"')


def test_analyze_mxgraph_xml_reports_structure_warnings():
    xml = wrap_mx_cells("""
    <mxCell id="a" value="孤立" vertex="1" parent="1" />
    <mxCell id="b" value="结束" vertex="1" parent="1">
      <mxGeometry x="260" y="80" width="120" height="60" as="geometry" />
    </mxCell>
    <mxCell id="e1" value="" edge="1" parent="1" source="b" target="b">
      <mxGeometry relative="1" as="geometry" />
    </mxCell>
    """)

    report = analyze_mxgraph_xml(xml)

    assert report['ok'] is True
    assert report['stats']['vertex_count'] == 2
    assert report['stats']['missing_geometry_count'] == 1
    assert any(item['code'] == 'missing_geometry' for item in report['issues'])
    assert any(item['code'] == 'isolated_vertex' for item in report['issues'])


def test_sanitize_blocks_accepts_diagram_blocks():
    xml = wrap_mx_cells(_sample_cells())
    block = new_diagram_block(
        authoring_format='drawio',
        mxgraph_xml=xml,
        json_graph={'nodes': [{'id': 'a', 'label': '开始'}], 'edges': [], 'groups': [], 'meta': {}},
        caption='流程图',
        display_size={'w': 760, 'h': 420},
    )

    sanitized = sanitize_blocks([block])

    assert len(sanitized) == 1
    assert sanitized[0]['type'] == 'diagram'
    assert sanitized[0]['display_size'] == {'w': 760, 'h': 420}
    assert '[图表: 流程图]' in blocks_to_plain_text(sanitized)
