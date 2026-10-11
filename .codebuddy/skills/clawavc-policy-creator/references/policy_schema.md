# ClawAVC 策略库 Schema 参考

> 适用范围：`backend/auditor/translator/policies/<role>/policy_registry/` 下的策略文件，
> 以及本 skill 的权限说明 spec（`create_role_policy.py --spec`）。

## 1. 策略库目录语义

```
policies/<role>/
├── README.md            # 角色说明（本 skill 产物）
└── policy_registry/
    ├── scenes.json      # 场景清单（Level-1 场景分类依据）
    └── tools/<scene>.json   # 各场景工具定义（Level-2 IR 生成依据）
```

有效性判定（`policy_manager._is_valid_registry`）：`policy_registry/` 下必须同时存在
`scenes.json` 与 `tools/` 目录。角色名（目录名）必须匹配 `^[A-Za-z0-9_-]{1,64}$`。

### 1.1 scenes.json

```json
{
  "<scene>": {
    "desc": "场景描述（供 Level-1 场景分类）",
    "functions": ["<函数名>", "server__tool"]
  }
}
```

- 场景被禁用 = scenes.json 键移除 + 对应 `tools/<scene>.json` 删除（生成产物的彻底关闭语义）；
- 函数从 `functions` 列表移除 + 从 `tools/*.json` 定义删除 = 彻底禁用该工具。

### 1.2 tools/<scene>.json

顶层字段：`scene`（场景名，必须与文件名一致且存在于 scenes.json）、
`functions`（对象：函数名 → 函数定义）、`prompt_guidance`（该场景工具的使用边界，注入提示词）。

每个函数定义：

```json
{
  "type": "function",
  "risk": "high | critical | ...",
  "desc": "功能描述",
  "file_actions": ["read", "create", "write", "edit", "delete"],
  "params": {
    "<参数名>": {
      "required": true,
      "desc": "参数说明",
      "constraint_spec": {
        "mode": "static | dynamic_ai | static_or_dynamic_ai",
        "static": { ... } 或 [ { ... }, ... ],
        "dynamic_ai_hint": "AI 生成参数值的引导"
      }
    }
  }
}
```

`static` 两种形态（`core.py::_static_spec` 双兼容）：

- **dict**（default 库 shell_exec 现行形态，多子场景合并后）
- **list[dict]**（ops 库 shell_exec 形态，按子场景组织的数组；消费端不区分子场景——
  提示词整体注入、default 取首个非空、denylist 取并集）

`static` 内部字段：

| 字段 | 语义 | 匹配方式 |
| --- | --- | --- |
| `allowed_values` | 命令/动作枚举 | 引导 AI 生成 + 一致性参照 |
| `allowlist` | 路径/URL 通配（`/workspace/**`、`https://*`） | 提示词引导 + judge 层 |
| `denylist` | 精确拒绝串 | **精确匹配**（`pval in denylist`，命中即删整个工具对象） |
| `default` | 参数缺失时回填 | `normalize_ir()` 取首个非空 |
| `risk_guidance` | `deny_strict`（分类硬拒绝）+ `warn`（`{class, pattern}`）+ `advice_docs: [{role, path}]` | 注入提示词 |
| `note` | 变更/合并说明 | 仅文档 |

## 2. 三个消费通道（改策略必须同时考虑）

| 通道 | 代码位置 | 行为 |
| --- | --- | --- |
| ① 提示词注入 | `core.py::_selected_registry_for_prompt()` | 整份 JSON（含 risk_guidance、advice_docs 展开内容）进入 LLM 提示词 |
| ② 默认值回填 | `core.py::normalize_ir()` L411-419 | 全部子场景中首个非空 default 回填缺失参数 |
| ③ 静态拒绝 | `core.py::_apply_static_deny()` L434-478 | 遍历全部子场景 denylist，**精确匹配**命中即从 IR 删除工具对象 |

关键推论：
- **denylist 是精确匹配**——模式条目（`dd of=/dev/*`、`curl * | sh`）只作为通道①的 AI 引导，
  不拦变体；变体拦截依赖判定层 shell 语义解析 + 四维一致性；
- **deny-wins**——`allowed_values` 与 `denylist` 同串冲突时以 denylist 为准；
- **advice_docs 降级**——路径不存在不抛异常，注入占位提示，不影响其余规则。

## 3. 权限说明 spec（create_role_policy.py 输入）

```jsonc
{
  // 必填
  "role_name": "analyst",              // ^[A-Za-z0-9_-]{1,64}$，不得为 default/ops
  // 可选（默认 default）
  "base_policy": "default",             // 派生基线（只读复制）
  "title": "只读数据分析师",             // README 用
  "description": "……",

  // 文件场景 → file_ops.json
  "files": {
    "read_paths":  ["/workspace/**", "/data/**"],  // 替换所有 path 类参数 allowlist（读范围）
    "write_paths": ["/workspace/outputs/**"],      // 仅写类函数（file_actions ∩ {create,write,edit,patch,delete}）
    "deny_paths":  ["/etc/**", "/root/**", "~/.ssh/**"]  // 并集进所有 path 类参数 denylist
  },

  // 网络场景 → scenes.json + search.json/browser.json + shell_exec.json 联动
  "network": {
    "enabled": false,                   // false：移除 search/browser 场景 + curl/wget/ping 等入 Bash denylist
    "allowed_domains": ["api.example.com"],  // url allowlist → https(s)://<domain>/*
    "deny_hosts": ["169.254.169.254", "evil.com"]  // url denylist += http(s)://<host>*
  },

  // Bash 场景 → shell_exec.json 的 exec / cmd_executor__exec_command
  "bash": {
    "mode": "replace",                  // replace：整体替换 allowed_values（多元素 static 先按并集语义拍平）
                                       // intersect：与现值取交集收缩
    "allowed_commands": ["ls", "cat", "grep", "python3"],
    "denied_commands": ["git", "docker"],   // deny-wins：并入 denylist 且移出 allowed_values
    "workdir_allowlist": ["/workspace/**", "/data/**"],
    "hint": "本角色仅允许数据分析相关命令。",   // 追加到 dynamic_ai_hint
    "prompt_guidance": "……"                  // 追加到 shell_exec.json 顶层 prompt_guidance
  },

  // 场景增删
  "scenes": {
    "disable": ["im_chat", "email"]     // 从 scenes.json 移除
  },

  // 惯例开关：禁 git（等价于 functions_remove + git 命令族 deny + hint）
  "no_git": true
}
```

### 3.1 字段 → 落盘位置对照

| spec 字段 | 落盘 | 动作 |
| --- | --- | --- |
| `files.read_paths` | `file_ops.json` 全部 path 类参数 | allowlist 替换 |
| `files.write_paths` | `file_ops.json` 写类函数 path 参数 | allowlist 替换 |
| `files.deny_paths` | `file_ops.json` 全部 path 类参数 | denylist 并集 |
| `network.enabled=false` | `scenes.json`（移 search/browser）+ `shell_exec.json`（网络命令 deny） | 场景移除 + deny-wins |
| `network.allowed_domains` | `search.json` / `browser.json` 的 url 参数 | allowlist 替换为域 glob |
| `network.deny_hosts` | 同上 | denylist 并集 |
| `bash.*` | `shell_exec.json` | 见 §3 注释 |
| `scenes.disable` | `scenes.json` | 键移除 |
| `no_git` | `scenes.json` + `tools/*.json` + `shell_exec.json` | 函数双清 + 命令族 deny + hint |

### 3.2 生成产物

- `policies/<role>/README.md`：spec 原文、字段级适配记录（changes）、切换方式、校验命令；
- 校验报告内嵌在生成器 stdout 的 `validation` 字段（E 级错误即退出码 1）。

## 4. 切换生效（后端 API）

| 操作 | API | 权限 |
| --- | --- | --- |
| 列出全部策略库 | `GET /api/translator/policies` | 无 |
| 切换当前策略库 | `POST /api/translator/policies/switch` `{"name": "<role>"}` | 免特权 |
| 新建（复制基线） | `POST /api/translator/policies/create` `{"name": "...", "from": "..."}` | 特权（X-Admin-Session） |
| 重命名 / 删除 / 模板 | `PUT /api/translator/policies/rename`、`DELETE /api/translator/policies/<name>`、`PUT /api/translator/policy-path-template` | 特权 |

切换后 `reload_registry()` 热重载，无需重启后端。健康检查：`GET /api/translator/registry-health`。
