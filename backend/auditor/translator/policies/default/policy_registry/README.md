README — Policy Registry Tools Schema

目的
- 说明 `policy_registry/tools` 目录下工具定义的统一 JSON 模式。
- 说明哪些字段用于工具执行，哪些字段仅用于生成用户意图参数的辅助信息（并已从工具定义中移除）。

位置
- 工具定义在 `policy_registry/tools/*.json`。

函数对象（function）模式
每个工具文件的顶层字段：
- `scene`: 场景名（string）
- `resource_type`: 资源类型（tool, external, file）
- `functions`: 一个对象，键为函数名，值为函数描述对象

每个函数描述对象包含：
- `type`: 字符串，通常为 `function`。
- `params`: 对象，描述参数集合。每个参数是一个对象，包含 `required`、`desc` 和 `constraint_spec` 等。
- 可选字段（运行时/安全相关）：`risk`（例如："high"）。

注意：为避免混淆，以下字段已从工具定义中移除——这些字段应该只在意图生成或参数结构化环节使用（例如单独的意图生成层），而不应存在于具备执行语义的工具定义中：
- `min_params`
- `app_component`
- `notes`

示例（工具文件片段）
{
  "scene": "browser",
  "resource_type": "tool",
  "functions": {
    "browser": {
      "type": "function",
      "params": {
        "url": { "required": false, "desc": "访问 URL", "constraint_spec": { /* ... */ } },
        "action": { "required": true, "desc": "浏览器动作", "constraint_spec": { /* ... */ } }
      }
    }
  }
}

为什么要移除 `min_params` / `app_component` / `notes`：
- 这些字段更适合放在意图解析或 UI 层，用来帮助模型生成用户意图和构造最小参数；将其留在执行定义中会混淆执行语义与生成语义。
- 执行层应保持简洁，只声明可执行函数与其参数和约束。

如果你仍然需要一份“意图生成”元数据表（包含 `min_params`、`app_component`、`notes` 示例），我可以另外生成 `policy_registry/TOOLS_INTENT_METADATA.json`。