# -*- coding: utf-8 -*-
"""
论证结构检查器 — 学术论证分析技能
检查论点-论据链条、逻辑漏洞、过度概括等问题。
"""


class ArgumentStructureCheckerSkill:
    """检查学术论证结构。"""

    def before_request(self, ctx):
        return {
            'system_append': (
                '你是一名学术论证分析专家，擅长识别和分析学术写作中的论证结构。\n\n'
                '常见论证问题：\n'
                '1. 论点-论据断裂：论据不能有效支持论点\n'
                '2. 逻辑谬误：滑坡谬误、稻草人谬误、循环论证等\n'
                '3. 过度概括：从有限样本推出普遍结论\n'
                '4. 因果误判：将相关性当作因果性\n'
                '5. 选择性证据：只引用支持自己观点的证据\n'
                '6. 诉诸权威：仅因为某权威说了就认为正确\n\n'
                '好的论证应该：\n'
                '- 论点清晰明确\n'
                '- 论据真实可靠\n'
                '- 推理逻辑严密\n'
                '- 考虑反面论证\n'
                '- 结论适当谨慎'
            ),
            'prompt_append': (
                '请分析论证结构，识别问题并提供改进建议。'
            ),
            'metadata': {
                'skill': 'argument-structure-checker',
                'scope': ctx.get('scope', ''),
            },
        }

    def after_response(self, ctx, text):
        return {}

    def run_action(self, action_id, inputs, host):
        action_map = {
            'check_argument': self._run_check_argument,
            'strengthen_argument': self._run_strengthen_argument,
        }

        handler = action_map.get(action_id)
        if not handler:
            return {'error': f'unknown action: {action_id}'}

        return handler(inputs, host)

    def _run_check_argument(self, inputs, host):
        text = inputs.get('text', '').strip()
        check_focus = inputs.get('check_focus', 'all')

        if not text:
            return {'error': '请提供需要检查的论证内容。'}

        focus_map = {
            'all': '全面检查',
            'claim_evidence': '论点-论据链条',
            'logical_fallacies': '逻辑漏洞',
            'overgeneralization': '过度概括',
            'causal_reasoning': '因果推理',
        }

        prompt = f"""## 任务
检查以下学术论证的结构，识别问题并提供改进建议。

## 论证内容
{text}

## 检查重点
{focus_map.get(check_focus, '全面检查')}

## 分析维度

### 1. 论点识别
- 核心论点是什么？
- 次要论点有哪些？
- 论点是否清晰明确？

### 2. 论据分析
- 使用了哪些论据？
- 论据来源是否可靠？
- 论据是否充分？
- 论据与论点是否相关？

### 3. 推理链条
- 从论据到论点的推理是否逻辑严密？
- 是否存在推理跳跃？
- 是否有隐含假设？
- 假设是否合理？

### 4. 常见问题检测
请检查是否存在以下问题：

**逻辑谬误**
- 滑坡谬误（不合理推导连锁反应）
- 稻草人谬误（曲解对方观点后攻击）
- 循环论证（用结论证明前提）
- 诉诸权威（仅因权威说了就认为正确）
- 诉诸情感（用情感替代理性论证）
- 虚假二分（非此即彼的错误选择）

**论证缺陷**
- 过度概括（从有限样本推出普遍结论）
- 因果误判（将相关性当作因果性）
- 选择性证据（只引用支持性证据）
- 忽略反面论证（不考虑反对意见）
- 论据不足（证据不充分就下结论）

### 5. 论证强度评估
- 论点-论据相关性：X/5
- 论据充分性：X/5
- 推理逻辑性：X/5
- 反面论证考虑：X/5
- **总体论证强度：X/5**

## 输出格式

### 识别出的问题
按严重程度排序：
- **严重**：影响论证有效性的核心问题
- **重要**：削弱论证说服力的问题
- **次要**：可以改进的问题

### 改进建议
针对每个问题提供具体的改进建议

### 优化示例
提供1-2个优化后的论证版本
"""

        result = host.call_llm(
            prompt,
            system='你是一名学术论证分析专家，擅长识别论证结构问题并提供改进建议。',
        )

        return {
            'action_id': 'check_argument',
            'check_focus': check_focus,
            'result': result,
        }

    def _run_strengthen_argument(self, inputs, host):
        claim = inputs.get('claim', '').strip()
        evidence = inputs.get('evidence', '').strip()
        target_audience = inputs.get('target_audience', 'academic')

        if not claim:
            return {'error': '请提供核心论点。'}
        if not evidence:
            return {'error': '请提供现有论据。'}

        audience_map = {
            'academic': '学术同行',
            'reviewer': '期刊审稿人',
            'interdisciplinary': '跨学科读者',
            'general': '一般读者',
        }

        prompt = f"""## 任务
针对以下论点和论据，提供论证强化建议。

## 核心论点
{claim}

## 现有论据
{evidence}

## 目标读者
{audience_map.get(target_audience, '学术同行')}

## 分析要求

### 1. 现状评估
- 当前论证的优势
- 当前论证的薄弱环节
- 论点-论据的匹配度

### 2. 强化策略

#### 2.1 补充论据
- 需要补充哪些类型的论据？
- 推荐的论据来源（数据、文献、案例等）
- 如何增强论据的说服力？

#### 2.2 加强推理
- 如何使推理链条更严密？
- 需要补充哪些中间推理步骤？
- 如何处理隐含假设？

#### 2.3 考虑反面论证
- 可能的反对意见有哪些？
- 如何回应这些反对意见？
- 如何将反面论证转化为论证的优势？

#### 2.4 修辞技巧
- 如何使论证更有说服力？
- 适合目标读者的表达方式
- 如何平衡严谨性和可读性？

### 3. 强化后的论证
提供一个强化后的完整论证版本，包含：
- 明确的论点陈述
- 充分的论据支持
- 严密的推理链条
- 对反面论证的回应
- 适当的结论

### 4. 注意事项
- 避免过度强化导致的过度概括
- 保持学术严谨性
- 注意论据的真实性和可靠性
"""

        result = host.call_llm(
            prompt,
            system='你是一名学术论证专家，擅长帮助研究者强化论证结构，提高论文说服力。',
        )

        return {
            'action_id': 'strengthen_argument',
            'claim': claim,
            'evidence': evidence,
            'target_audience': target_audience,
            'result': result,
        }
