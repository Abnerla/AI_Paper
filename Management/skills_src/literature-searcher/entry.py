# -*- coding: utf-8 -*-
"""
文献检索器 — 系统化文献检索与验证技能
生成检索策略、推荐数据库、验证文献真实性。
"""


class LiteratureSearcherSkill:
    """系统化文献检索与验证。"""

    def before_request(self, ctx):
        return {
            'system_append': (
                '你是一名专业的学术图书馆员和文献检索专家。\n'
                '你的职责：\n'
                '1. 根据研究主题生成系统化的检索策略\n'
                '2. 推荐合适的学术数据库和检索词\n'
                '3. 验证文献的真实性（避免AI幻觉生成的虚假文献）\n'
                '4. 评估文献来源的可信度和质量\n\n'
                '重要提醒：\n'
                '- 绝不编造或猜测文献信息\n'
                '- 如果无法确认文献真实性，明确告知用户\n'
                '- 始终建议用户在正规数据库（知网、Web of Science、Google Scholar等）核实\n'
                '- 标注文献的证据等级和可信度'
            ),
            'prompt_append': (
                '请基于用户的查询提供专业的文献检索建议。'
                '确保所有推荐的文献来源真实可查，避免虚假引用。'
            ),
            'metadata': {
                'skill': 'literature-searcher',
                'scope': ctx.get('scope', ''),
            },
        }

    def after_response(self, ctx, text):
        return {}

    def run_action(self, action_id, inputs, host):
        action_map = {
            'search_strategy': self._run_search_strategy,
            'verify_reference': self._run_verify_reference,
            'evaluate_source': self._run_evaluate_source,
        }

        handler = action_map.get(action_id)
        if not handler:
            return {'error': f'unknown action: {action_id}'}

        return handler(inputs, host)

    def _run_search_strategy(self, inputs, host):
        topic = inputs.get('topic', '').strip()
        discipline = inputs.get('discipline', 'auto')
        time_range = inputs.get('time_range', '5years')

        if not topic:
            return {'error': '请先描述你的研究主题。'}

        discipline_map = {
            'education': '教育学',
            'management': '管理学',
            'psychology': '心理学',
            'sociology': '社会学',
            'computer_science': '计算机科学',
            'economics': '经济学',
            'law': '法学',
            'medicine': '医学',
            'science_engineering': '理工科',
            'other': '其他',
        }

        time_range_map = {
            '5years': '近5年（2021-2026）',
            '10years': '近10年（2016-2026）',
            'any': '不限时间',
        }

        prompt = f"""## 任务
为以下研究主题生成系统化的文献检索策略。

## 研究主题
{topic}

## 学科领域
{discipline_map.get(discipline, '待识别') if discipline != 'auto' else '请根据主题自动识别'}

## 时间范围
{time_range_map.get(time_range, time_range)}

## 输出要求

### 1. 推荐数据库
根据学科领域推荐最适合的学术数据库（中英文各推荐2-3个）：
- 中文：知网(CNKI)、万方、维普等
- 英文：Web of Science、Scopus、PubMed、Google Scholar、IEEE Xplore等

### 2. 检索策略
提供3-5组检索词组合，使用布尔运算符(AND/OR/NOT)：
- 核心概念词
- 同义词/近义词
- 上下位词
- 英文对照词

### 3. 筛选标准
建议的文献筛选标准：
- 纳入标准
- 排除标准
- 优先级排序

### 4. 检索流程
建议的检索步骤和流程图

### 5. 注意事项
- 提醒用户核实文献真实性
- 建议使用文献管理工具（如Zotero、EndNote）
- 提醒关注高被引论文和综述文章
"""

        result = host.call_llm(
            prompt,
            system='你是一名专业的学术图书馆员，精通各学科的文献检索策略。请提供系统化、可操作的检索方案。',
        )

        return {
            'action_id': 'search_strategy',
            'topic': topic,
            'discipline': discipline,
            'time_range': time_range,
            'result': result,
        }

    def _run_verify_reference(self, inputs, host):
        reference = inputs.get('reference', '').strip()

        if not reference:
            return {'error': '请提供需要验证的文献信息。'}

        prompt = f"""## 任务
验证以下文献的真实性，并评估其可信度。

## 文献信息
{reference}

## 验证步骤

### 1. 文献真实性检查
请分析以下信息：
- 文献标题是否完整、规范？
- 作者姓名是否合理？
- 期刊/会议名称是否真实存在？
- 发表年份是否合理？
- 卷号、期号、页码格式是否正确？
- DOI是否存在且格式正确？

### 2. 可信度评估
如果文献可能真实存在，请评估：
- **来源可信度**：是否为正规学术期刊/会议？
- **期刊质量**：是否为核心期刊（SCI/SSCI/CSSCI/北大核心）？
- **掠夺性期刊风险**：是否有可能是掠夺性期刊？
- **证据等级**：该文献在证据等级中的位置

### 3. 核实建议
提供具体的核实步骤：
- 在哪些数据库可以查到这篇文献？
- 如何验证DOI的真实性？
- 如何确认期刊的影响因子和分区？

### 4. 风险提示
- 如果无法确认真实性，明确告知用户
- 提醒用户AI可能生成虚假文献
- 建议使用正规渠道核实

## 重要原则
- 绝不编造或猜测文献信息
- 如果无法确认，直接说明"无法确认此文献的真实性"
- 始终建议用户在正规数据库核实
"""

        result = host.call_llm(
            prompt,
            system='你是一名学术文献审核专家，擅长识别虚假文献和掠夺性期刊。请客观、谨慎地评估文献的真实性。',
        )

        return {
            'action_id': 'verify_reference',
            'reference': reference,
            'result': result,
        }

    def _run_evaluate_source(self, inputs, host):
        journal_name = inputs.get('journal_name', '').strip()
        context = inputs.get('context', '').strip()

        if not journal_name:
            return {'error': '请提供期刊名称。'}

        prompt = f"""## 任务
评估以下学术期刊的质量和可信度。

## 期刊名称
{journal_name}

## 使用场景
{context if context else '学术论文引用'}

## 评估维度

### 1. 基本信息
- 期刊全称和缩写
- ISSN号
- 出版商
- 创刊年份
- 出版频率

### 2. 学术影响力
- 是否被SCI/SSCI/EI收录？
- 影响因子（最近几年）
- JCR分区（Q1/Q2/Q3/Q4）
- 中文期刊：是否为CSSCI/北大核心/CSCD？

### 3. 可信度评估
- 是否为正规学术期刊？
- 是否有掠夺性期刊的特征？
  - 审稿周期过短（<2周）
  - 邮件邀请投稿
  - 版面费过高
  - 编委会信息不透明
  - 收录在Beall's List中

### 4. 引用建议
- 是否推荐在学术论文中引用该期刊的文章？
- 引用时需要注意什么？
- 如何在参考文献中标注期刊级别？

## 输出格式
请用表格形式展示评估结果，便于用户快速了解期刊质量。
"""

        result = host.call_llm(
            prompt,
            system='你是一名学术期刊评估专家，熟悉各学科的核心期刊和数据库收录情况。请提供客观、准确的期刊评估。',
        )

        return {
            'action_id': 'evaluate_source',
            'journal_name': journal_name,
            'context': context,
            'result': result,
        }
