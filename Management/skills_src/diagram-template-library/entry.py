"""图表模板库 Skill。

模板存放在 templates/<diagram_kind>/*.json，每个模板包含 mermaid 与 json_graph。
SkillManager.collect_skill_templates 会自动扫描该目录。
"""


class DiagramTemplateLibrarySkill:
    def before_request(self, ctx):
        return {}

    def after_response(self, ctx, text):
        return {}

    def run_action(self, action_id, inputs, host):
        if action_id != 'list_templates':
            return {'error': f'unknown action: {action_id}'}
        diagram_kind = (inputs or {}).get('diagram_kind', '') or ''
        templates = host.list_diagram_templates(diagram_kind)
        return {
            'action_id': action_id,
            'diagram_kind': diagram_kind,
            'count': len(templates),
            'templates': [
                {
                    'id': item.get('id'),
                    'name': item.get('name'),
                    'description': item.get('description'),
                    'diagram_kind': item.get('diagram_kind'),
                }
                for item in templates
            ],
        }
