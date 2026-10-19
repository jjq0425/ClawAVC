---
name: clawavc-policy-creator
description: ClawAVC 角色策略库生成器。当用户给出角色权限说明（例如"新建一个不许使用 git 的开发角色""建一个只能读 /data、不能联网的只读分析角色"），需要基于 backend/auditor/translator/policies 下的现有策略库（default/ops）创建新角色文件夹并适配文件/网络/Bash 三类场景权限、生成 ClawAVC 兼容的新策略库（policy_registry）时使用。覆盖权限说明解析、spec 构造、策略生成、结构校验与切换生效全流程。
---

# ClawAVC 角色策略库生成器（Policy Role Creator）

## 概述

将用户的自然语言权限说明转化为一个**新的 ClawAVC 角色策略库**：

```
backend/auditor/translator/policies/
├── default/policy_registry/     ← 基线（只读，绝不修改）
├── ops/policy_registry/         ← 基线（只读，绝不修改）
└── <new_role>/                  ← 本 skill 的产物
    ├── README.md                （角色说明 + 适配记录 + 切换方式）
    └── policy_registry/
        ├── scenes.json          （场景清单，按 spec 增删）
        └── tools/*.json         （工具约束，按 spec 适配）
```

适配范围与《Agent权限策略调研报告》三类核心场景一一对应：
**文件**（读写/删改/查询范围）、**网络请求**（域白/黑名单、禁网）、**Bash**（`shell_exec` 场景的 `allowed_values`/`denylist`/`workdir`，每个角色权限不同）。

## 硬约束（必须遵守）

1. **绝不修改既有策略库**（`default/`、`ops/` 及任何已存在角色）：基线只读复制；对既有角色的调整请求应拒绝并提示新建派生角色。
2. 角色名必须匹配 `^[A-Za-z0-9_-]{1,64}$`（与 `policy_manager.POLICY_NAME_RE` 一致），且不得为 `default`/`ops`。
3. 产物必须含 `policy_registry/scenes.json` + `policy_registry/tools/` 才有效。
4. 遵循仓库既有裁决：**deny-wins**——新增拒绝项并入 `denylist` 并从 `allowed_values` 移除同串项。
5. `constraint_spec.static` 有 dict / list 两种形态（`core.py::_static_spec` 双兼容）；仅当整体替换 `allowed_values` 且 static 为多元素数组时才按《shell_exec_策略调整说明.md》的并集语义拍平。
6. **场景级动作白名单**：`tools/<scene>.json` 顶层支持两个可选字段，用于限制该场景的**文件 / 网络访问动作**：

   | 字段 | 作用对象 | 取值 | 语义 |
   | --- | --- | --- | --- |
   | `allowed_file_actions` | IR 中 `type="file"` 对象的 `actions` | 数组，元素取自 `read` / `write` / `delete` / `create` | **非空**＝白名单，IR 只能从中选择（必须为其子集）；**缺省 / null / 空数组**＝不限制，都放行 |
   | `allowed_network_actions` | IR 中 `type="network"` 对象的 `actions` | 数组，元素取自 `send` / `receive` | 同上 |

   这两个字段由 `LEVEL2_SYS` 的硬约束保证生效——**用户的请求意图不能凌驾于该白名单之上**
   （例如只读场景要求"创建文件"，IR 不得输出 `create` / `write`，宁可整体省略该 file 对象）。
   生成只读 / 受限角色时应显式填写；生成通用角色时留空即可（保持"都放行"）。

## 工作流（五步，按序执行）

### 第 1 步：解析权限说明 → spec

从用户描述中抽取五类信息，落成 spec JSON（schema 见 `references/policy_schema.md`，常见映射见 `references/role_playbook.md`）：

```json
{
  "role_name": "analyst",
  "base_policy": "default",
  "title": "只读数据分析师",
  "files":     { "read_paths": [...], "write_paths": [...], "deny_paths": [...] },
  "network":   { "enabled": true, "allowed_domains": [...], "deny_hosts": [...] },
  "bash":      { "mode": "replace", "allowed_commands": [...], "denied_commands": [...],
                 "workdir_allowlist": [...], "hint": "..." },
  "scenes":    { "disable": ["im_chat", "email"] },
  "actions":   { "file_ops":   { "file": ["read"], "network": [] },
                 "shell_exec": { "file": ["read"] } },
  "no_git":    false
}
```

`actions` 为**可选**字段（场景级动作白名单，缺省 = 不限制）：键是场景名，值支持 `file` / `network`
两个数组，分别对应产物 `tools/<scene>.json` 顶层的 `allowed_file_actions` / `allowed_network_actions`；
数组元素分别取自 `read`/`write`/`delete`/`create` 与 `send`/`receive`。
只读角色应写 `"file": ["read"]`；通用角色留空或省略该字段。

映射要点（详表在 `references/role_playbook.md`）：

| 用户说 | spec 落点 |
| --- | --- |
| "不让使用 git" | `"no_git": true`（自动：移除 `mcpguard_gitkit__*` 函数 + git 命令族入 denylist + AI hint 禁 git） |
| "只能读 /data 下的文件" | `files.read_paths: ["/data/**"]` |
| "只读 / 只能读不能写（绝不改动环境）" | `actions: {"file_ops": {"file": ["read"]}, "shell_exec": {"file": ["read"]}}`（→ 产物 `allowed_file_actions`；与 `write_paths: []` 并用：路径层 + 动作层双保险） |
| "只能写输出目录" | `files.write_paths: ["/workspace/outputs/**"]` |
| "不能访问网络" | `network.enabled: false`（自动：移除 search/browser 场景 + curl/wget 等入 Bash denylist） |
| "只能访问 api.example.com" | `network.allowed_domains: ["api.example.com"]`（url allowlist → `https://api.example.com/*`） |
| "只能跑只读查询命令" | `bash.allowed_commands: ["ls","cat","grep","ps","df"]`（默认 mode=replace） |
| "运维类，可以重启服务" | `base_policy: "ops"`（保留 systemctl 等服务管理命令） |

信息不足时**直接按最小权限假设落 spec 并向用户声明假设**，不阻塞流程。

### 第 2 步：选择基线

- 普通办公/开发/分析类角色 → `base_policy: "default"`（权限收敛、含 risk_guidance/warn_advice 平替机制）；
- 运维/系统管理类角色 → `base_policy: "ops"`（保留服务管理、文件写入删除等子场景）；
- 拿不准 → default（更安全一侧）。

### 第 3 步：生成

```bash
python3 scripts/create_role_policy.py --spec /tmp/<role>_spec.json
```

可选参数：`--policies-root DIR`（默认自动探测）、`--dry-run`（只看适配计划）、`--force`（覆盖重建同名角色）。
脚本保证基线只读；产物落盘后自动执行第 4 步校验并输出变更清单（changes）。
本步**支持** spec 的 `actions` 字段：键为场景名、值为 `{"file": [...], "network": [...]}`，
落盘为 `tools/<scene>.json` 顶层的 `allowed_file_actions` / `allowed_network_actions`；缺省则不写该键（＝不限制）。

### 第 4 步：校验

```bash
python3 scripts/validate_policy.py <policies_root>/<role>/policy_registry
```

校验 scenes↔tools 一致性、deny-wins（`allowed_values ∩ denylist = ∅`）、advice_docs 引用等；E 级错误必须修复（常见修复见 `references/role_playbook.md` 第 5 节），W 级（基线历史遗留缺口）如实向用户说明即可。

### 第 5 步：生效（需用户确认后才执行）

生成不等于切换。向用户给出切换方式并确认：

```bash
# API（免特权）
curl -X POST http://<backend>/api/translator/policies/switch \
     -H 'Content-Type: application/json' -d '{"name": "<role>"}'
# 或前端 /policy 页面切换；切换即热重载（reload_registry），无需重启后端
```

随后建议抽 2–3 条典型 query 走 `/api/translator/*` 验证 IR 生成的权限边界符合预期。

## 边界与失败处理

- 角色已存在 → 默认拒绝；用户确认覆盖时才加 `--force`；
- 用户要求修改 default/ops → 拒绝，说明本 skill 只做"新建派生角色"，避免污染基线；
- spec 缺 `role_name` / 名字不合法 / 基线不存在 → 脚本直接报错退出，按报错修正；
- 校验失败 → 按 `errors` 逐条修复 spec 重跑（产物可 `--force` 重建）；
- 用户权限说明超出三类场景（如要求时限控制） → 如实说明当前策略库 schema 不支持，不要造字段。

## 资源索引

| 资源 | 用途 |
| --- | --- |
| `scripts/create_role_policy.py` | 生成器（spec → 新角色策略库 + README + 自动校验） |
| `scripts/validate_policy.py` | 独立校验器（E1–E6 / W1–W2，见脚本 docstring） |
| `references/policy_schema.md` | spec 完整 schema 与 policy_registry 字段语义、三个消费通道 |
| `references/role_playbook.md` | 权限说明→spec 映射表、四个角色模板、修复手册 |
| `assets/spec_example_analyst.json` | 可直接复制的只读分析师 spec 示例 |
| `assets/spec_example_no_git_dev.json` | 禁 git 开发者 spec 示例 |
