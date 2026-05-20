# -*- coding: utf-8 -*-
"""
研究方法设计器 — 研究方法论蓝图设计技能
设计研究范式、方法选择、数据策略、分析框架。
"""


class MethodologyDesignerSkill:
    """设计研究方法论蓝图。"""

    def before_request(self, ctx):
        return {
            'system_append': (
                '你是一名研究方法论专家，擅长为各种研究问题设计合适的研究方法。\n\n'
                '研究方法论的核心要素：\n'
                '1. 研究范式：实证主义、解释主义、实用主义、批判主义\n'
                '2. 研究方法：定量、定性、混合方法\n'
                '3. 研究设计：实验、调查、案例研究、扎根理论、民族志等\n'
                '4. 数据策略：数据来源、抽样方法、数据收集工具\n'
                '5. 分析框架：统计分析、内容分析、主题分析、话语分析等\n'
                '6. 效度标准：内部效度、外部效度、信度、可重复性\n\n'
                '设计原则：\n'
                '- 方法必须与研究问题匹配\n'
                '- 考虑实际可行性\n'
                '- 注重研究伦理\n'
                '- 确保可重复性'
            ),
            'prompt_append': (
                '请根据研究问题设计合适的研究方法论，确保方法与问题匹配且可行。'
            ),
            'metadata': {
                'skill': 'methodology-designer',
                'scope': ctx.get('scope', ''),
            },
        }

    def after_response(self, ctx, text):
        return {}

    def run_action(self, action_id, inputs, host):
        action_map = {
            'design_methodology': self._run_design_methodology,
            'evaluate_methodology': self._run_evaluate_methodology,
        }

        handler = action_map.get(action_id)
        if not handler:
            return {'error': f'unknown action: {action_id}'}

        return handler(inputs, host)

    def _run_design_methodology(self, inputs, host):
        research_question = inputs.get('research_question', '').strip()
        discipline = inputs.get('discipline', 'auto')
        constraints = inputs.get('constraints', '').strip()

        if not research_question:
            return {'error': '请提供研究问题。'}

        discipline_map = {
            'social_science': '社会科学',
            'natural_science': '自然科学',
            'humanities': '人文学科',
            'engineering': '工程技术',
            'medical': '医学健康',
            'education': '教育学',
            'management': '管理学',
            'other': '其他',
        }

        prompt = f"""## 任务
根据研究问题设计完整的研究方法论蓝图。

## 研究问题
{research_question}

## 学科领域
{discipline_map.get(discipline, '请根据研究问题自动识别') if discipline != 'auto' else '请根据研究问题自动识别'}

## 研究条件限制
{constraints if constraints else '未特别说明'}

## 设计要求

### 1. 研究范式选择
- 推荐的研究范式（实证主义/解释主义/实用主义/批判主义）
- 选择理由
- 与研究问题的匹配度

### 2. 研究方法选择
- 推荐的方法类型（定量/定性/混合方法）
- 选择理由
- 优势和局限性

### 3. 研究设计
- 推荐的研究设计类型
  - 定量：实验、准实验、调查、相关研究等
  - 定性：案例研究、扎根理论、民族志、现象学等
  - 混合：解释性顺序、探索性顺序、嵌入式等
- 设计细节

### 4. 数据策略

#### 4.1 数据来源
- 一手数据 vs 二手数据
- 数据来源渠道

#### 4.2 抽样方法
- 目标总体定义
- 抽样策略（概率/非概率抽样）
- 样本量确定
- 抽样框架

#### 4.3 数据收集工具
- 问卷设计（如适用）
- 访谈提纲（如适用）
- 观察记录表（如适用）
- 实验方案（如适用）

### 5. 分析框架

#### 5.1 定量分析
- 描述性统计
- 推断统计方法
- 效应量
- 软件工具

#### 5.2 定性分析
- 编码策略
- 主题分析/内容分析
- 信度检验
- 软件工具

### 6. 效度与信度

#### 6.1 效度
- 内部效度保障措施
- 外部效度保障措施
- 构念效度保障措施

#### 6.2 信度
- 测量信度
- 评分者信度
- 可重复性保障

### 7. 研究伦理
- 伦理审查要求
- 知情同意
- 隐私保护
- 数据安全

### 8. 时间规划
- 各阶段时间分配
- 里程碑节点
- 风险预案

## 输出格式

### 方法论蓝图
以结构化的方式呈现完整的研究方法论设计

### 可行性评估
评估该方法论设计的可行性

### 替代方案
提供1-2个备选方法论方案

### 注意事项
实施该方法论需要注意的关键问题
"""

        result = host.call_llm(
            prompt,
            system='你是一名研究方法论设计专家，擅长为各种研究问题设计合适、可行的研究方法。',
        )

        return {
            'action_id': 'design_methodology',
            'research_question': research_question,
            'discipline': discipline,
            'result': result,
        }

    def _run_evaluate_methodology(self, inputs, host):
        methodology = inputs.get('methodology', '').strip()
        research_question = inputs.get('research_question', '').strip()

        if not methodology:
            return {'error': '请提供研究方法描述。'}
        if not research_question:
            return {'error': '请提供研究问题。'}

        prompt = f"""## 任务
评估现有研究方法设计的合理性和可行性。

## 研究问题
{research_question}

## 研究方法描述
{methodology}

## 评估维度

### 1. 方法-问题匹配度
- 研究方法是否与研究问题匹配？
- 研究范式是否合适？
- 研究设计是否能回答研究问题？

### 2. 方法论严谨性
- 研究设计是否严谨？
- 数据收集方法是否可靠？
- 分析方法是否恰当？

### 3. 可行性评估
- 时间可行性
- 资源可行性
- 数据可得性
- 技术可行性

### 4. 效度评估
- 内部效度：因果关系推断是否合理？
- 外部效度：结果能否推广？
- 构念效度：测量是否有效？

### 5. 信度评估
- 测量工具是否可靠？
- 研究过程是否可重复？
- 是否有信度保障措施？

### 6. 伦理性评估
- 是否符合研究伦理？
- 是否有伦理审查？
- 如何保护参与者？

### 7. 创新性评估
- 方法是否有创新？
- 与现有研究方法有何不同？

## 输出格式

### 评估摘要
- 方法论评分：X/5
- 主要优点：X条
- 主要问题：X条
- 改进建议：X条

### 详细评估
按维度逐项评估

### 问题清单
按严重程度排序的问题列表

### 改进建议
针对每个问题的具体改进建议

### 替代方案
如果当前方法论有严重问题，提供替代方案
"""

        result = host.call_llm(
            prompt,
            system='你是一名研究方法论评估专家，擅长评估研究方法设计的合理性、可行性和严谨性。',
        )

        return {
            'action_id': 'evaluate_methodology',
            'research_question': research_question,
            'result': result,
        }
