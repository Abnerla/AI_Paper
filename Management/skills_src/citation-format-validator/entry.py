# -*- coding: utf-8 -*-
"""
引用格式验证器 — 学术引用规范检查技能
验证引用格式、转换格式、检查完整性。
"""


class CitationFormatValidatorSkill:
    """验证学术引用格式。"""

    def before_request(self, ctx):
        return {
            'system_append': (
                '你是一名学术引用格式专家，精通各种引用格式规范。\n\n'
                '支持的引用格式：\n'
                '- APA 7th：美国心理学会第7版\n'
                '- GB/T 7714：中国国家标准\n'
                '- MLA 9th：现代语言协会第9版\n'
                '- IEEE：电气电子工程师学会\n'
                '- Vancouver：温哥华格式（医学）\n'
                '- Chicago：芝加哥格式\n\n'
                '检查要点：\n'
                '1. 文内引用格式是否正确\n'
                '2. 参考文献列表格式是否规范\n'
                '3. 文内引用与参考文献是否匹配\n'
                '4. 引用信息是否完整（作者、年份、标题、来源等）\n'
                '5. 标点符号、斜体、大小写是否正确'
            ),
            'prompt_append': (
                '请严格按照引用格式规范进行检查，指出具体问题并提供修正示例。'
            ),
            'metadata': {
                'skill': 'citation-format-validator',
                'scope': ctx.get('scope', ''),
            },
        }

    def after_response(self, ctx, text):
        return {}

    def run_action(self, action_id, inputs, host):
        action_map = {
            'validate_citations': self._run_validate_citations,
            'convert_format': self._run_convert_format,
            'check_completeness': self._run_check_completeness,
        }

        handler = action_map.get(action_id)
        if not handler:
            return {'error': f'unknown action: {action_id}'}

        return handler(inputs, host)

    def _run_validate_citations(self, inputs, host):
        paper_text = inputs.get('paper_text', '').strip()
        reference_list = inputs.get('reference_list', '').strip()
        citation_format = inputs.get('citation_format', 'auto')

        if not paper_text:
            return {'error': '请提供论文正文。'}
        if not reference_list:
            return {'error': '请提供参考文献列表。'}

        format_map = {
            'apa7': 'APA 7th',
            'gbt7714': 'GB/T 7714',
            'mla9': 'MLA 9th',
            'ieee': 'IEEE',
            'vancouver': 'Vancouver',
            'chicago': 'Chicago',
        }

        prompt = f"""## 任务
验证论文的引用格式是否符合规范。

## 论文正文（包含文内引用）
{paper_text[:6000]}{'...(内容已截断)' if len(paper_text) > 6000 else ''}

## 参考文献列表
{reference_list[:4000]}{'...(内容已截断)' if len(reference_list) > 4000 else ''}

## 引用格式
{format_map.get(citation_format, '请自动识别') if citation_format != 'auto' else '请自动识别'}

## 检查要求

### 1. 文内引用检查
- 引用格式是否正确？
- 引用位置是否合适？
- 多篇引用的排列顺序是否正确？
- 直接引用是否标注页码？

### 2. 参考文献列表检查
- 每条文献的格式是否符合规范？
- 作者姓名格式是否正确？
- 年份位置是否正确？
- 标题格式（斜体、引号等）是否正确？
- 来源信息是否完整？
- 标点符号是否正确？
- 排序是否正确（字母顺序/引用顺序）？

### 3. 引用完整性
- 文内引用的文献是否都在参考文献列表中？
- 参考文献列表中的文献是否都被引用？
- 是否有遗漏或多余的文献？

### 4. 具体问题清单
列出所有发现的问题，按类型分类：
- 格式错误
- 信息缺失
- 不一致问题
- 排序问题

### 5. 修正建议
针对每个问题提供具体的修正建议和正确格式示例。

## 输出格式

### 引用格式识别
识别出使用的引用格式（或指出格式不一致）

### 检查结果摘要
- 文内引用：X个正确，X个有问题
- 参考文献：X条正确，X条有问题
- 引用完整性：X%匹配

### 问题清单
按类型分组列出所有问题

### 修正示例
提供修正后的正确格式示例
"""

        result = host.call_llm(
            prompt,
            system='你是一名学术引用格式专家，精通各种引用格式规范。请严格按照规范检查引用格式。',
        )

        return {
            'action_id': 'validate_citations',
            'citation_format': citation_format,
            'result': result,
        }

    def _run_convert_format(self, inputs, host):
        references = inputs.get('references', '').strip()
        source_format = inputs.get('source_format', 'auto')
        target_format = inputs.get('target_format', 'apa7')

        if not references:
            return {'error': '请提供需要转换的参考文献。'}

        format_map = {
            'apa7': 'APA 7th',
            'gbt7714': 'GB/T 7714',
            'mla9': 'MLA 9th',
            'ieee': 'IEEE',
            'vancouver': 'Vancouver',
            'chicago': 'Chicago',
        }

        prompt = f"""## 任务
将参考文献从一种格式转换为另一种格式。

## 参考文献
{references[:5000]}{'...(内容已截断)' if len(references) > 5000 else ''}

## 当前格式
{format_map.get(source_format, '请自动识别') if source_format != 'auto' else '请自动识别'}

## 目标格式
{format_map.get(target_format, target_format)}

## 转换要求

### 1. 格式识别
- 识别当前参考文献的格式
- 确认是否为同一格式

### 2. 逐条转换
对每条参考文献：
- 提取所有信息（作者、年份、标题、来源等）
- 按目标格式重新排列
- 调整标点符号、斜体、大小写等

### 3. 排序调整
根据目标格式的排序要求：
- APA：按作者姓氏字母顺序
- GB/T 7714：按引用顺序
- MLA：按作者姓氏字母顺序
- IEEE：按引用顺序
- Vancouver：按引用顺序
- Chicago：按作者姓氏字母顺序或引用顺序

### 4. 质量检查
- 检查转换后的格式是否正确
- 确保信息没有丢失
- 验证标点符号和格式细节

## 输出格式

### 转换结果
列出每条参考文献的转换结果

### 转换说明
说明主要的格式变化

### 注意事项
提醒用户需要人工核实的项目
"""

        result = host.call_llm(
            prompt,
            system='你是一名学术引用格式转换专家，精通各种引用格式之间的转换。',
        )

        return {
            'action_id': 'convert_format',
            'source_format': source_format,
            'target_format': target_format,
            'result': result,
        }

    def _run_check_completeness(self, inputs, host):
        paper_text = inputs.get('paper_text', '').strip()
        reference_list = inputs.get('reference_list', '').strip()

        if not paper_text:
            return {'error': '请提供论文正文。'}
        if not reference_list:
            return {'error': '请提供参考文献列表。'}

        prompt = f"""## 任务
检查文内引用与参考文献列表的匹配情况。

## 论文正文
{paper_text[:6000]}{'...(内容已截断)' if len(paper_text) > 6000 else ''}

## 参考文献列表
{reference_list[:4000]}{'...(内容已截断)' if len(reference_list) > 4000 else ''}

## 检查要求

### 1. 提取文内引用
从正文中提取所有文内引用，包括：
- 作者-年份引用（如：Smith, 2020）
- 数字引用（如：[1]、[2-5]）
- 脚注引用（如有）

### 2. 提取参考文献
从参考文献列表中提取所有文献标识（作者+年份或编号）

### 3. 匹配检查

#### 文内引用 → 参考文献
- 文内引用的每篇文献是否都在参考文献列表中？
- 列出未找到的引用

#### 参考文献 → 文内引用
- 参考文献列表中的每篇文献是否都被引用？
- 列出未被引用的文献

### 4. 一致性检查
- 作者姓名拼写是否一致？
- 年份是否一致？
- 文献标识是否一致？

## 输出格式

### 匹配统计
- 文内引用总数：X
- 参考文献总数：X
- 成功匹配：X
- 未匹配引用：X
- 未使用文献：X

### 未匹配的文内引用
列出文内引用但参考文献列表中没有的文献

### 未使用的参考文献
列出参考文献列表中但正文未引用的文献

### 一致性问题
列出作者姓名、年份等不一致的问题

### 修正建议
如何解决这些匹配问题
"""

        result = host.call_llm(
            prompt,
            system='你是一名学术引用完整性检查专家，擅长发现文内引用与参考文献列表之间的匹配问题。',
        )

        return {
            'action_id': 'check_completeness',
            'result': result,
        }
