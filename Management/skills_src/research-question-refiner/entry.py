# -*- coding: utf-8 -*-
"""
研究问题提炼器 — FINER标准技能
使用FINER标准将模糊主题提炼为精确的研究问题。
"""


class ResearchQuestionRefinerSkill:
    """使用FINER标准提炼研究问题。"""

    def before_request(self, ctx):
        return {
            'system_append': (
                '你是一名研究方法论专家，擅长使用FINER标准帮助研究者提炼研究问题。\n\n'
                'FINER标准：\n'
                '- Feasible（可行）：研究者有能力完成，有足够的时间、资源、资金、数据可得性\n'
                '- Interesting（有趣）：能引起研究者和学术界的兴趣\n'
                '- Novel（新颖）：提供新知识、新视角、新方法，与现有研究有区别\n'
                '- Ethical（伦理）：符合研究伦理，不伤害研究对象\n'
                '- Relevant（相关）：对学科发展或实践应用有贡献\n\n'
                '好的研究问题应该：\n'
                '1. 清晰明确，不含糊\n'
                '2. 可以通过研究方法回答\n'
                '3. 有适当的范围（不太宽泛也不太狭窄）\n'
                '4. 有理论或实践意义'
            ),
            'prompt_append': (
                '请帮助用户提炼研究问题。使用FINER标准评估，并提供具体的改进建议。'
            ),
            'metadata': {
                'skill': 'research-question-refiner',
                'scope': ctx.get('scope', ''),
            },
        }

    def after_response(self, ctx, text):
        return {}

    def run_action(self, action_id, inputs, host):
        action_map = {
            'refine_question': self._run_refine_question,
            'evaluate_question': self._run_evaluate_question,
        }

        handler = action_map.get(action_id)
        if not handler:
            return {'error': f'unknown action: {action_id}'}

        return handler(inputs, host)

    def _run_refine_question(self, inputs, host):
        topic = inputs.get('topic', '').strip()
        existing_questions = inputs.get('existing_questions', '').strip()
        discipline = inputs.get('discipline', 'auto')

        if not topic:
            return {'error': '请先描述你的研究主题。'}

        discipline_map = {
            'social_science': '社会科学',
            'natural_science': '自然科学',
            'humanities': '人文学科',
            'engineering': '工程技术',
            'medical': '医学健康',
            'other': '其他',
        }

        prompt = f"""## 任务
使用FINER标准将研究主题提炼为精确的研究问题。

## 研究主题
{topic}

## 已有研究问题
{existing_questions if existing_questions else '暂无'}

## 学科领域
{discipline_map.get(discipline, '请根据主题自动识别') if discipline != 'auto' else '请根据主题自动识别'}

## 输出要求

### 1. 主题分析
分析研究主题的核心概念、研究范围和潜在方向。

### 2. FINER评估
对主题进行FINER标准评估：
- **Feasible（可行性）**：需要什么资源？数据可得性如何？
- **Interesting（趣味性）**：学术界和实践界会感兴趣吗？
- **Novel（新颖性）**：与现有研究有何不同？
- **Ethical（伦理性）**：是否存在伦理风险？
- **Relevant（相关性）**：对学科或实践有何贡献？

### 3. 研究问题建议
基于分析，提供3-5个备选研究问题：
- 主要研究问题（RQ1）
- 次要研究问题（RQ2-RQn）
- 每个问题都用FINER标准简要评估

### 4. 问题优化建议
- 如何使问题更清晰？
- 如何调整问题范围？
- 如何增强问题的新颖性？

### 5. 推荐方案
推荐最佳的研究问题组合，并说明理由。
"""

        result = host.call_llm(
            prompt,
            system='你是一名研究方法论专家，擅长使用FINER标准帮助研究者提炼高质量的研究问题。',
        )

        return {
            'action_id': 'refine_question',
            'topic': topic,
            'discipline': discipline,
            'result': result,
        }

    def _run_evaluate_question(self, inputs, host):
        question = inputs.get('question', '').strip()
        context = inputs.get('context', '').strip()

        if not question:
            return {'error': '请提供需要评估的研究问题。'}

        prompt = f"""## 任务
评估以下研究问题的质量，并提供改进建议。

## 研究问题
{question}

## 研究背景
{context if context else '未提供'}

## 评估维度

### 1. 问题质量评估
使用以下标准评估研究问题：

**清晰度**
- 问题表述是否清晰明确？
- 核心概念是否定义清楚？
- 是否存在歧义？

**可研究性**
- 问题是否可以通过研究方法回答？
- 是否需要量化或质化数据？
- 数据可得性如何？

**范围适当性**
- 问题范围是否合适？
- 是否太宽泛（需要缩小）？
- 是否太狭窄（需要扩展）？

**FINER标准**
- Feasible（可行）：研究者是否有能力完成？
- Interesting（有趣）：是否能引起学术兴趣？
- Novel（新颖）：与现有研究有何不同？
- Ethical（伦理）：是否符合研究伦理？
- Relevant（相关）：对学科或实践有何贡献？

### 2. 问题分类
判断研究问题的类型：
- 描述性问题（是什么？）
- 解释性问题（为什么？）
- 探索性问题（如何？）
- 预测性问题（会怎样？）
- 规范性问题（应该怎样？）

### 3. 改进建议
针对每个评估维度，提供具体的改进建议：
- 如何提高问题的清晰度？
- 如何调整问题范围？
- 如何增强可研究性？
- 如何提升新颖性？

### 4. 优化版本
提供1-2个优化后的研究问题版本，供用户参考。
"""

        result = host.call_llm(
            prompt,
            system='你是一名研究方法论专家，擅长评估和优化研究问题。请提供客观、具体的评估和改进建议。',
        )

        return {
            'action_id': 'evaluate_question',
            'question': question,
            'context': context,
            'result': result,
        }
