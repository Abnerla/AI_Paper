"""图表领域专家 Skill：在 AI 生成或修改图表时注入符号规范与布局建议。"""


_KIND_GUIDELINES = {
    'flowchart': (
        '【流程图规范】\n'
        '1. 起止节点使用椭圆形 ( ([\"开始\"]) / ([\"结束\"]) )；\n'
        '2. 判断节点使用菱形 { ... }，并在分支边上标注「是」「否」或具体条件；\n'
        '3. 处理节点使用矩形 [ ... ]；输入输出可使用平行四边形 [/ ... /]；\n'
        '4. 子流程使用双层矩形 [[ ... ]]；数据存储使用圆柱 [( ... )]；\n'
        '5. 长流程优先使用 LR 布局，短流程使用 TB；\n'
        '6. 避免交叉边，必要时引入中间节点或调整顺序。'
    ),
    'sequence': (
        '【时序图规范】\n'
        '1. 参与者使用 participant 显式声明，命名简短规范；\n'
        '2. 同步消息使用 ->>，异步消息使用 -)，返回使用 -->>；\n'
        '3. 关键阶段使用 Note over 注释；可选分支使用 alt/else，循环使用 loop；\n'
        '4. 避免 8 个以上参与者，必要时拆分多张图。'
    ),
    'classDiagram': (
        '【类图规范】\n'
        '1. 字段与方法使用 + / - / # 标注可见性；\n'
        '2. 关系使用 <|-- 继承、*-- 组合、o-- 聚合、--> 关联、..> 依赖；\n'
        '3. 抽象类用 <<abstract>>，接口用 <<interface>>；\n'
        '4. 字段类型与方法签名完整给出。'
    ),
    'stateDiagram': (
        '【状态图规范】\n'
        '1. 起始状态使用 [*]，终止状态使用 [*]；\n'
        '2. 转移条件写在边上：state_a --> state_b : 触发条件；\n'
        '3. 复合状态用 state X { ... } 嵌套；\n'
        '4. 并行区域用 -- 分隔。'
    ),
    'erDiagram': (
        '【ER 图规范】\n'
        '1. 实体名使用大写，属性写在实体内并标注主外键（PK/FK）；\n'
        '2. 关系基数使用 ||--o{ / }o--o{ / ||--|| 等显式标注；\n'
        '3. 关系动词描述放在 :"...." 中。'
    ),
    'mindmap': (
        '【思维导图规范】\n'
        '1. 中心主题位于根节点，分支按维度展开；\n'
        '2. 同一层级保持表达粒度一致；\n'
        '3. 叶节点保持名词或短语，避免长句。'
    ),
}

_GENERIC_GUIDE = (
    '【通用约束】\n'
    '1. 节点 id 使用短英文+数字，禁止与 mermaid 关键字冲突；\n'
    '2. 节点 label 使用引号包裹，可包含中英文与空格，禁止包含未转义的引号；\n'
    '3. json_graph.nodes 必须与 mermaid 保持节点 id 一致；\n'
    '4. 输出严格 JSON，不带任何解释、Markdown 围栏或额外文字。'
)


class FlowchartExpertSkill:
    def before_request(self, ctx):
        usage = ctx.get('usage_context') if isinstance(ctx, dict) else {}
        usage = usage if isinstance(usage, dict) else {}
        scene_id = str(usage.get('scene_id') or ctx.get('scene_id') or '')
        diagram_kind = str(usage.get('diagram_kind') or ctx.get('diagram_kind') or '').strip()

        guide = _KIND_GUIDELINES.get(diagram_kind, '')
        if not guide and scene_id == 'paper_write.diagram_edit':
            guide = (
                '【增量改图规范】\n'
                '1. 严格保留所有未在指令中提及的节点与边；\n'
                '2. 新增节点必须给出唯一 id，且边的 source/target 必须存在；\n'
                '3. 不要重命名已有节点 id（仅可改 label）；\n'
                '4. 输出 {"ops": [...]} 形式的 JSON，不要解释。'
            )
        elif not guide:
            guide = (
                '【通用图表规范】请按所选 diagram_kind 的标准符号语法输出，'
                '保持节点命名简洁，避免交叉边。'
            )

        return {
            'system_append': f'{guide}\n\n{_GENERIC_GUIDE}',
            'prompt_append': '',
            'metadata': {
                'skill': 'flowchart-expert',
                'diagram_kind': diagram_kind,
            },
        }

    def after_response(self, ctx, text):
        return {}

    def run_action(self, action_id, inputs, host):
        return {'error': f'unknown action: {action_id}'}
