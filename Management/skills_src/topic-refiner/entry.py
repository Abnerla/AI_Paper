# -*- coding: utf-8 -*-
"""
论文主题确定器 — 苏格拉底式追问技能
通过连续追问帮助用户从模糊想法收敛到明确的研究主题。
"""


class TopicRefinerSkill:
    """通过苏格拉底式追问确定论文主题。"""

    def before_request(self, ctx):
        return {
            'system_append': (
                '你是一名资深的学术导师，擅长通过苏格拉底式追问帮助学生确定论文主题。\n'
                '你的追问策略：\n'
                '1. 先理解用户的兴趣领域和动机\n'
                '2. 通过缩小范围的问题（时间、地域、人群、具体现象）收敛主题\n'
                '3. 检验主题的可行性（数据可得性、研究方法、时间限制）\n'
                '4. 确认主题的新颖性（与现有研究的区别）\n'
                '5. 最终输出一个明确、可研究、有边界的论文主题\n\n'
                '每次只问 1-2 个问题，不要一次性问太多。'
                '当主题足够清晰时，输出结构化的主题确认书。'
            ),
            'prompt_append': (
                '请通过追问帮助用户确定论文主题。如果用户已经提供了足够信息，'
                '直接输出主题确认书，包括：研究主题、研究问题、研究范围、预期贡献。'
            ),
            'metadata': {
                'skill': 'topic-refiner',
                'scope': ctx.get('scope', ''),
            },
        }

    def after_response(self, ctx, text):
        return {}

    def run_action(self, action_id, inputs, host):
        if action_id != 'refine_topic':
            return {'error': f'unknown action: {action_id}'}

        initial_idea = inputs.get('initial_idea', '').strip()
        discipline = inputs.get('discipline', 'auto')
        paper_type = inputs.get('paper_type', 'auto')

        if not initial_idea:
            return {'error': '请先描述你的初步想法。'}

        discipline_map = {
            'education': '教育学',
            'management': '管理学',
            'psychology': '心理学',
            'sociology': '社会学',
            'computer_science': '计算机科学',
            'economics': '经济学',
            'law': '法学',
            'literature': '文学',
            'other': '其他',
        }

        paper_type_map = {
            'journal': '期刊论文',
            'conference': '会议论文',
            'thesis': '学位论文（硕士/博士）',
            'course': '课程论文',
        }

        prompt_parts = [
            '## 任务',
            '通过苏格拉底式追问帮助用户确定论文主题。',
            '',
            '## 用户的初步想法',
            f'{initial_idea}',
            '',
        ]

        if discipline != 'auto':
            prompt_parts.append(f'## 学科领域\n{discipline_map.get(discipline, discipline)}')
            prompt_parts.append('')

        if paper_type != 'auto':
            prompt_parts.append(f'## 论文类型\n{paper_type_map.get(paper_type, paper_type)}')
            prompt_parts.append('')

        prompt_parts.extend([
            '## 追问策略',
            '请按以下顺序追问（每次只问 1-2 个问题）：',
            '',
            '**第一轮：理解动机**',
            '- 你为什么对这个方向感兴趣？',
            '- 你希望通过这篇论文解决什么问题？',
            '',
            '**第二轮：缩小范围**',
            '- 时间范围（近5年？某个特定时期？）',
            '- 地域范围（国内？某个地区？全球？）',
            '- 研究对象（特定人群？特定行业？特定技术？）',
            '- 具体现象（哪个具体方面？）',
            '',
            '**第三轮：检验可行性**',
            '- 你能获取到相关数据吗？',
            '- 你熟悉这个领域的研究方法吗？',
            '- 你的时间和资源限制是什么？',
            '',
            '**第四轮：确认新颖性**',
            '- 你了解这个方向的现有研究吗？',
            '- 你的研究与现有研究有什么不同？',
            '- 你的预期贡献是什么？',
            '',
            '**最终输出：主题确认书**',
            '当信息足够时，输出以下结构：',
            '',
            '```',
            '## 论文主题确认书',
            '',
            '**研究主题：** [一句话概括]',
            '',
            '**研究问题：**',
            '1. [主要研究问题]',
            '2. [次要研究问题（如有）]',
            '',
            '**研究范围：**',
            '- 时间：',
            '- 地域：',
            '- 对象：',
            '- 边界：',
            '',
            '**预期贡献：**',
            '- 理论贡献：',
            '- 实践贡献：',
            '',
            '**可行性评估：**',
            '- 数据来源：',
            '- 研究方法：',
            '- 时间预估：',
            '```',
            '',
            '## 注意事项',
            '- 每次只问 1-2 个问题，不要一次性问太多',
            '- 根据用户的回答动态调整追问方向',
            '- 如果用户的想法太宽泛，帮助他们找到切入点',
            '- 如果用户的想法太狭窄，帮助他们找到更大的意义',
            '- 使用中文交流',
        ])

        prompt = '\n'.join(prompt_parts)

        result = host.call_llm(
            prompt,
            system='你是一名资深的学术导师，擅长通过苏格拉底式追问帮助学生确定论文主题。你的目标是帮助用户从模糊的想法收敛到一个明确、可研究、有边界的论文主题。',
        )

        return {
            'action_id': action_id,
            'initial_idea': initial_idea,
            'discipline': discipline,
            'paper_type': paper_type,
            'result': result,
        }
