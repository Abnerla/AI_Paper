# -*- coding: utf-8 -*-
"""
同行评审模拟器 — 多视角学术论文评审技能
模拟主编、方法论、领域专家、跨学科、魔鬼代言人五个视角。
"""


class PeerReviewSimulatorSkill:
    """模拟多视角同行评审。"""

    def before_request(self, ctx):
        return {
            'system_append': (
                '你是一名学术期刊评审专家，能够从多个视角模拟完整的同行评审过程。\n\n'
                '评审视角：\n'
                '1. 主编视角：期刊适配性、原创性、整体质量、读者价值\n'
                '2. 方法论视角：研究设计、抽样策略、数据分析、可重复性\n'
                '3. 领域视角：文献覆盖、理论框架、学术论证、领域贡献\n'
                '4. 跨学科视角：跨学科连接、实践应用、更广泛影响\n'
                '5. 魔鬼代言人：核心论点挑战、逻辑谬误检测、最强反论证\n\n'
                '评审原则：\n'
                '- 客观公正，基于学术标准\n'
                '- 具体明确，指出具体问题和位置\n'
                '- 建设性意见，提供改进方向\n'
                '- 区分严重问题和次要问题'
            ),
            'prompt_append': (
                '请从多个视角对论文进行评审，输出结构化的审稿意见。'
            ),
            'metadata': {
                'skill': 'peer-review-simulator',
                'scope': ctx.get('scope', ''),
            },
        }

    def after_response(self, ctx, text):
        return {}

    def run_action(self, action_id, inputs, host):
        action_map = {
            'full_review': self._run_full_review,
            'quick_assessment': self._run_quick_assessment,
            'methodology_check': self._run_methodology_check,
        }

        handler = action_map.get(action_id)
        if not handler:
            return {'error': f'unknown action: {action_id}'}

        return handler(inputs, host)

    def _run_full_review(self, inputs, host):
        paper_content = inputs.get('paper_content', '').strip()
        paper_type = inputs.get('paper_type', 'auto')
        target_journal = inputs.get('target_journal', '').strip()

        if not paper_content:
            return {'error': '请提供论文内容。'}

        paper_type_map = {
            'empirical': '实证研究',
            'review': '综述论文',
            'theoretical': '理论研究',
            'case_study': '案例研究',
            'methodological': '方法论研究',
        }

        prompt = f"""## 任务
模拟完整的同行评审过程，从5个不同视角对论文进行评审。

## 论文内容
{paper_content[:8000]}{'...(内容已截断)' if len(paper_content) > 8000 else ''}

## 论文类型
{paper_type_map.get(paper_type, '请自动识别') if paper_type != 'auto' else '请自动识别'}

## 目标期刊
{target_journal if target_journal else '未指定'}

## 评审要求

### Phase 0: 论文识别
- 识别论文的主要学科和研究范式
- 判断论文类型和成熟度
- 为5个评审人配置具体身份

### Phase 1: 五视角并行评审

#### 视角1：主编评审
- 期刊适配性：论文是否适合目标期刊？
- 原创性：研究问题和方法是否有新意？
- 重要性：对领域有何贡献？
- 可读性：写作质量如何？
- **总体判断**：接收/小修/大修/拒稿

#### 视角2：方法论评审
- 研究设计是否严谨？
- 抽样策略是否合适？
- 数据收集方法是否可靠？
- 分析方法是否恰当？
- 是否可重复？
- **方法论评分**：1-5分

#### 视角3：领域专家评审
- 文献综述是否全面？
- 理论框架是否合适？
- 学术论证是否准确？
- 对领域的增量贡献是什么？
- 缺少哪些关键文献？
- **领域贡献评分**：1-5分

#### 视角4：跨学科视角
- 与其他学科的连接点
- 实践应用价值
- 更广泛的社会或伦理影响
- **跨学科价值评分**：1-5分

#### 视角5：魔鬼代言人
- 核心论点的最强反论证
- 逻辑谬误检测
- 确认偏误检测
- 过度概括检测
- 替代解释分析
- **论证强度评分**：1-5分

### Phase 2: 编辑综合决策

综合5个视角的评审意见：
- 共识点（5人一致同意的问题）
- 分歧点（不同意见的仲裁）
- 编辑决定信
- 修改路线图（按优先级排序）

## 输出格式

### 1. 评审人配置
为5个评审人配置具体身份和专长

### 2. 五份独立评审报告
每份报告包含：
- 总体评价
- 主要优点（2-3条）
- 主要问题（按严重程度排序）
- 具体修改建议
- 评分（1-5分）

### 3. 编辑决定信
- 决定：接收/小修/大修/拒稿
- 理由概述
- 必须修改的问题
- 建议修改的问题

### 4. 修改路线图
按优先级排序的修改清单：
- P0（必须修改）：影响论文有效性的核心问题
- P1（强烈建议）：影响论文质量的重要问题
- P2（建议修改）：提升论文质量的次要问题
"""

        result = host.call_llm(
            prompt,
            system='你是一名资深的学术期刊编辑，能够从多个视角模拟完整的同行评审过程。请提供专业、客观、建设性的评审意见。',
        )

        return {
            'action_id': 'full_review',
            'paper_type': paper_type,
            'target_journal': target_journal,
            'result': result,
        }

    def _run_quick_assessment(self, inputs, host):
        paper_content = inputs.get('paper_content', '').strip()

        if not paper_content:
            return {'error': '请提供论文内容。'}

        prompt = f"""## 任务
快速评估论文的核心质量维度（15分钟内完成）。

## 论文内容
{paper_content[:6000]}{'...(内容已截断)' if len(paper_content) > 6000 else ''}

## 评估维度

### 1. 原创性（1-5分）
- 研究问题是否新颖？
- 方法是否有创新？
- 结论是否有新发现？

### 2. 方法论严谨性（1-5分）
- 研究设计是否合理？
- 数据分析是否恰当？
- 是否可重复？

### 3. 论证质量（1-5分）
- 逻辑是否清晰？
- 证据是否充分？
- 结论是否合理？

### 4. 写作质量（1-5分）
- 结构是否清晰？
- 表达是否准确？
- 引用是否规范？

### 5. 贡献度（1-5分）
- 理论贡献
- 实践贡献
- 方法论贡献

## 输出要求
- 每个维度给出评分和简要理由
- 总体评估：优点、缺点、改进建议
- 快速判断：是否值得深入评审？
"""

        result = host.call_llm(
            prompt,
            system='你是一名学术论文质量评估专家，请快速、准确地评估论文的核心质量维度。',
        )

        return {
            'action_id': 'quick_assessment',
            'result': result,
        }

    def _run_methodology_check(self, inputs, host):
        methodology_section = inputs.get('methodology_section', '').strip()
        results_section = inputs.get('results_section', '').strip()

        if not methodology_section:
            return {'error': '请提供方法论部分。'}

        prompt = f"""## 任务
专注于研究设计、数据分析和可重复性的方法论审查。

## 方法论部分
{methodology_section}

## 结果部分
{results_section if results_section else '未提供'}

## 审查维度

### 1. 研究设计
- 研究范式是否合适？（实证/解释/探索）
- 研究设计类型（实验/调查/案例/混合）
- 是否有对照组？
- 变量定义是否清晰？

### 2. 抽样策略
- 目标总体是否明确？
- 抽样方法是否合适？
- 样本量是否足够？
- 是否存在选择偏误？

### 3. 数据收集
- 数据收集方法是否可靠？
- 测量工具是否有效？
- 数据收集过程是否标准化？
- 是否有缺失数据？如何处理？

### 4. 数据分析
- 分析方法是否与研究问题匹配？
- 统计方法是否恰当？
- 效应量是否报告？
- 置信区间是否提供？
- 假设检验是否正确？

### 5. 可重复性
- 研究过程是否详细描述？
- 是否提供数据和代码？
- 是否有预注册？
- 是否报告了所有分析（包括失败的）？

### 6. 伦理合规
- 是否获得伦理审查批准？
- 是否保护参与者隐私？
- 是否有利益冲突声明？
- 是否有知情同意？

## 输出格式

### 方法论评分
- 研究设计：X/5
- 抽样策略：X/5
- 数据收集：X/5
- 数据分析：X/5
- 可重复性：X/5
- 伦理合规：X/5
- **总分：X/30**

### 主要优点
列出方法论的2-3个优点

### 主要问题
按严重程度排序：
- 严重问题（必须修改）
- 重要问题（强烈建议修改）
- 次要问题（建议修改）

### 改进建议
针对每个问题提供具体的改进建议
"""

        result = host.call_llm(
            prompt,
            system='你是一名研究方法论专家，专注于研究设计、数据分析和可重复性审查。请提供专业、详细的审查意见。',
        )

        return {
            'action_id': 'methodology_check',
            'result': result,
        }
