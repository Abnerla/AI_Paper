# 技能开发与提交说明

本文档用于规范纸研社技能仓库的提交格式，避免发现技能页面出现空名称、空介绍、无法安装或场景绑定失效等问题。

## 目录结构

每个技能在仓库中应同时提供源码目录和发布包：

```text
Management/
  skills_src/
    your-skill-id/
      skill.json
      entry.py
      ...
  skills/
    your-skill-id.zip
  skills_index.json
```

源码目录用于维护和审查，ZIP 文件用于用户在发现技能页面安装。ZIP 包内必须包含一个技能根目录，根目录内必须有 `skill.json` 和入口模块。

## skill.json 必填字段

`skill.json` 是技能包的唯一清单文件。以下字段必须填写，且不能为空：

```json
{
  "id": "your-skill-id",
  "name": "技能显示名称",
  "version": "v1.0.0",
  "description": "一句话说明技能解决什么问题，建议 20 到 120 个中文字符。",
  "min_app_version": "v1.4.0",
  "entry": {
    "module": "entry",
    "class": "YourSkillClass"
  },
  "actions": [
    {
      "id": "run",
      "label": "执行技能",
      "description": "说明这个动作的用途。",
      "input_schema": {
        "fields": []
      }
    }
  ],
  "scene_bindings": [
    "paper_write.section"
  ],
  "global_hook": false
}
```

字段要求：

- `id`：只允许小写字母、数字、点、下划线和中划线，长度不超过 64，例如 `literature-searcher`。
- `name`：发现技能页面显示的名称，必须是可读中文或英文，不要留空。
- `description`：发现技能页面显示的介绍，必须描述实际能力，不要写“暂无”“测试”等占位文本。
- `version`：使用 `v主版本.次版本.修订号` 格式，例如 `v1.0.0`。
- `min_app_version`：最低支持的纸研社版本。
- `entry.module`：入口 Python 文件名，不带 `.py` 后缀。
- `entry.class`：入口类名。
- `actions`：管理中心手动执行技能时使用的动作定义。
- `scene_bindings`：技能可绑定的场景，必须使用程序支持的场景 ID。
- `global_hook`：`false` 表示只在声明场景中生效，`true` 表示全局钩子。

## 技能索引字段

`Management/skills_index.json` 中每个条目至少应包含以下字段：

```json
{
  "id": "your-skill-id",
  "name": "技能显示名称",
  "version": "v1.0.0",
  "description": "一句话说明技能解决什么问题。",
  "min_app_version": "v1.4.0",
  "download_url": "https://raw.githubusercontent.com/Abnerla/AI_paper/main/Management/skills/your-skill-id.zip",
  "publisher": "PaperLab",
  "homepage": "https://github.com/Abnerla/AI_paper",
  "global_hook": false,
  "scene_bindings": [
    "paper_write.section"
  ]
}
```

索引中的 `id` 必须与 ZIP 包内 `skill.json` 的 `id` 一致。`name` 和 `description` 必须填写；客户端会做兜底处理，但仓库提交不应依赖兜底。

兼容字段：第三方仓库可以用 `title`、`display_name` 或 `label` 作为名称字段，也可以用 `summary`、`intro`、`readme` 或 `details` 作为介绍字段。官方仓库仍统一使用 `name` 和 `description`。

## 入口类约定

入口类至少实现需要使用的方法。常见形式如下：

```python
class YourSkillClass:
    def __init__(self, host=None, manifest=None):
        self.host = host
        self.manifest = manifest or {}

    def run_action(self, action_id, payload):
        return {
            "text": "处理结果"
        }
```

如需参与 AI 请求前后处理，可以实现运行时约定的方法；不要在模块导入阶段执行网络请求、文件删除、后台进程启动等副作用操作。

## 文件限制

技能包允许包含 `.py`、`.json`、`.md`、`.txt`、`.csv`、`.html`、`.css`、图片等静态文件。

禁止包含以下内容：

- 可执行文件，例如 `.exe`、`.dll`、`.bat`、`.cmd`、`.ps1`、`.sh`。
- 依赖管理文件，例如 `requirements.txt`、`pyproject.toml`、`setup.py`。
- 编译缓存，例如 `__pycache__`、`.pyc`、`.pyo`。
- 符号链接或包含 `..` 的路径。

## 提交前检查

提交前至少完成以下检查：

```powershell
py -m py_compile Management\skills_src\your-skill-id\entry.py
```

并人工确认：

- `skill.json` 的 `id`、`name`、`description` 不为空。
- `skills_index.json` 中对应条目的 `id`、`name`、`description` 不为空。
- `download_url` 能直接下载 ZIP 文件。
- ZIP 包内只包含一个技能根目录，且根目录内存在 `skill.json`。
- ZIP 包内的 `skill.json` 与 `skills_index.json` 的版本一致。
- `scene_bindings` 都是程序支持的场景 ID。

## 常见问题

- 发现技能页面名称为空：索引条目缺少 `name`，或安装记录覆盖了仓库元数据。提交时必须填写 `name`。
- 发现技能页面显示“暂无描述”：索引条目或 `skill.json` 缺少 `description`。
- 安装按钮不可用：索引条目缺少 `download_url`，或 URL 不是可直接下载的 ZIP 文件。
- 安装后无法执行：`entry.module` 或 `entry.class` 与实际文件、类名不一致。
- 场景绑定不显示：`scene_bindings` 使用了程序不支持的场景 ID。
