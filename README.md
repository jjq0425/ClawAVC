<div align="center">

<img src="frontend/public/logo-long.png" alt="ClawAVC" width="280" />

# ClawAVC

**中文** | [English](./README_en.md)

**Claw Access-View Compliance**

*透视访问行为意图 · 校验合规性*

> ClawAVC 的使命就是稳稳地接住 🫴 OpenClaw —— 你放心飞，我帮你兜着。

[![Python](https://img.shields.io/badge/Python-3.14+-blue.svg)](https://python.org)
[![Vue](https://img.shields.io/badge/Vue-3.4+-42b883.svg)](https://vuejs.org)
[![TDesign](https://img.shields.io/badge/TDesign-Vue_Next-0052D9.svg)](https://tdesign.tencent.com)
[![License](https://img.shields.io/badge/License-Internal-orange.svg)]()

---

**面向 AI Agent 的行为合规审计可视化平台**

实时监控 · 多维检测 · 意图比对 · 异常预警

*Agent 你尽管浪，ClawAVC 帮你把合规的账算得明明白白* 🧮

</div>

---

## 目录

- [项目背景](#项目背景)
- [系统架构](#系统架构)
- [核心能力](#核心能力)
- [检测引擎](#检测引擎)
- [快速部署](#快速部署)
- [内置监控](#内置监控)
- [进程 & 安全上下文采集](#进程--安全上下文采集)
- [安全拦截](#安全拦截)
- [模拟攻击](#模拟攻击)
- [页面模块](#页面模块)
- [异常分析对话（小异）](#异常分析对话小异)
- [流量回放](#流量回放)
- [权限体系](#权限体系)
- [API 文档](#api-文档)
- [技术栈](#技术栈)
- [目录结构](#目录结构)
- [开发指南](#开发指南)
- [团队](#团队)

---

## 项目背景

随着 AI Agent 在生产环境中广泛应用，Agent 拥有了调用工具、访问文件、执行命令等高权限能力。如何确保 Agent 的实际行为与用户意图一致，不发生越权访问、参数篡改、路径逃逸等安全风险，成为亟需解决的问题。

**ClawAVC** 正是为此而生。系统名称取自三个核心概念：

| 字母 | 含义 | 职责 |
|------|------|------|
| **A** | Access（访问行为） | 捕获 Agent 的工具调用、文件访问、命令执行等行为轨迹 |
| **V** | View（意图透视） | 将用户自然语言意图翻译为标准化权限策略 (IR) |
| **C** | Compliance（合规校验） | 多维度比对行为与意图的一致性，输出合规判定 |

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        ClawAVC Platform                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────┐    HTTP POST     ┌──────────────────────────┐  │
│  │ Orchestrator │ ──────────────→ │     Backend (Flask)       │  │
│  │  (Agent审计)  │    /api/rounds   │                          │  │
│  └─────────────┘                  │  ┌──────┐  ┌──────────┐  │  │
│                                    │  │SQLite│  │SocketIO  │  │  │
│                                    │  └──┬───┘  └─────┬────┘  │  │
│                                    └─────┼────────────┼───────┘  │
│                                          │            │          │
│                                          │  WebSocket │          │
│                                          │            ▼          │
│                                    ┌─────┴──────────────────┐   │
│                                    │   Frontend (Vue3)       │   │
│                                    │                         │   │
│                                    │  ┌─────┐ ┌─────┐       │   │
│                                    │  │ 监控 │ │ 管理 │ ...   │   │
│                                    │  └─────┘ └─────┘       │   │
│                                    └─────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 数据流

```
用户发出请求
    ↓
Agent 执行工具调用（产生 action）
    ↓
IR 翻译器将用户意图转化为权限策略（产生 IR）
    ↓
Judge 引擎多维度比对 action vs IR
    ↓
Orchestrator 将完整 round 数据 POST 到 ClawAVC Backend
    ↓
Backend 持久化到 SQLite + WebSocket 推送到前端
    ↓
前端实时渲染审计卡片
```

---

## 核心能力

### 实时审计

每一轮 Agent 交互（round）完成后即刻推送至平台，零延迟呈现合规判定结果。基于 WebSocket 的双向通信确保数据实时性。

### 多维检测

从工具调用、参数匹配、资源访问三个维度全面评估 Agent 行为合规性，量化输出综合得分。

### 意图透视

基于 LLM 的两阶段 IR 翻译管线，将用户自然语言请求转化为结构化的 `subject/objects` 权限策略，精确描述允许的工具、参数与资源范围。

### 可视化审计

卡片式设计，分组展示 Access（行为轨迹）、View（意图策略）、Compliance（合规判定），支持折叠展开，一目了然。

### 异常分析对话（小异）

内置「小异」二阶段异常判断大模型，针对选中轮次的多维行为轨迹做交互式研判。采用「技能分析（Skill Analysis）」编排：通过流式 + tools 调用，一边解析模型输出一边实时执行取证工具并呈现，最终研判逐字流式返回，显著降低等待感。详见 [异常分析对话（小异）](#异常分析对话小异)。

### 进程 & 安全上下文回放

每一轮 ROUND_START 都会主动定位 OpenClaw 主进程，连同它启动的所有工具调用子进程一并采集 SELinux/AppArmor 标签、capabilities、namespaces、cgroup、loginuid、容器运行时等信息，作为 `pid_info` JSON 快照固化到本轮记录中。审计时可完整回放"谁在跑、跑在什么标签下、能做什么"。详见 [进程 & 安全上下文采集](#进程--安全上下文采集)。

### 安全拦截（portkey 网关集成）

ClawAVC 可与 portkey 网关联动，在 LLM 返回 tool_calls 时实时拦截 IR 白名单外的工具调用。支持死循环熔断保护和 IR 长轮询超时配置。详见 [安全拦截](#安全拦截)。

---

## 检测引擎

### 三维一致性检测模型

| 维度 | 检测内容 | 违规示例 |
|------|----------|----------|
| **工具调用一致性** | Agent 调用的工具是否在 IR 允许范围内 | IR 允许 `read`，Agent 调用了 `exec` |
| **参数一致性** | 工具调用参数键值是否与 IR 约束匹配 | IR 允许 `path=/tmp/a.txt`，Agent 传了 `path=/etc/passwd` |
| **资源访问一致性** | 文件路径和操作类型是否在允许范围内 | IR 允许 `read /tmp/**`，Agent 执行了 `write /etc/cron.d/x` |

### 评分机制

```
overall_score = mean(各维度 score)    // 仅计入有事件的维度
score = matched_count / total_count   // 每个维度独立计算
```

| 阈值 | 判定 | 含义 |
|------|------|------|
| `> 0.5` | ✅ 合规 | 行为与意图基本一致 |
| `≤ 0.5` | ⚠️ 异常 | 存在显著越权或偏离 |

### 检测管线（已集成 / 规划中）

| 层级 | 状态 | 说明 |
|------|------|------|
| 用户态意图行为一致性检测 | ✅ 已集成 | 基于 IR 策略的规则匹配引擎 |
| 内核态行为意图一致性检测 | 🔄 集成中 | 基于系统调用轨迹的深层检测 |
| 多维行为轨迹综合研判 | 🔄 集成中 | 用户态 + 内核态联合大模型研判 |

---

## 快速部署

### 前置要求

- Python ≥ 3.11（推荐 3.14）
- Node.js ≥ 18
- [uv](https://github.com/astral-sh/uv) (Python 包管理器)

### 安装依赖

```bash
cd /home/hx/jjq/clawAVC

# Backend
cd backend && uv sync && cd ..

# Frontend
cd frontend && npm install && cd ..
```

### 启动服务

```bash
# 前台运行（Ctrl+C 停止）
./start.sh

# 后台运行
./start.sh -d
```

### 停止服务

```bash
fuser -k 15100/tcp; fuser -k 15101/tcp
```

### 访问

| 服务 | 地址 |
|------|------|
| 前端页面 | `http://<host>:15101` |
| 后端 API | `http://<host>:15100` |

首次访问需输入入门口令（默认由特权用户配置）。

---

## 内置监控

ClawAVC 自带一个轻量监控引擎，无需外部 orchestrator 也能独立完成审计。

### 工作原理

```
             ┌──────────────────────────────┐
             │  watcher.py (后台线程)        │
             │                              │
  ~/.openclaw│──→ 检测 ROUND_START/END       │
  (日志文件)  │                              │
             │   ┌─────────────────────┐    │
  网关日志   │──→│ 解析 query + actions │    │
  (Portkey)  │   └────────┬────────────┘    │
             │            │                 │
             │     ┌──────▼──────┐          │
             │     │ ir_client   │──→ LLM   │
             │     └──────┬──────┘          │
             │            │                 │
             │     ┌──────▼──────┐          │
             │     │  judge.py   │          │
             │     └──────┬──────┘          │
             └────────────┼─────────────────┘
                          │
                   POST /api/rounds
                          │
                    ┌──────▼──────┐
                    │  SQLite DB  │──→ WebSocket ──→ 前端
                    └─────────────┘
```

### 使用方式

1. 进入「运行监控 → 监控配置」页
2. 填写 **OpenClaw 根文件夹** 路径（必填）
3. 选择 **交互数据来源**：
   - 默认「从 OpenClaw 日志获取」— 无需额外配置，直接从 agent session 日志解析 actions (含 tool result)
   - 可选「从网关获取」— 需额外填写 Portkey 网关日志路径
4. 点击「启动安全监控」
5. 切换到「运行日志」tab 查看实时数据

> 💡 监控会在 Agent 发出消息时立刻创建卡片（"检测中"状态），
> 然后异步请求 IR 翻译，最后在 round 结束时完成 judge 并更新分数。
> 整个过程完全异步，不阻塞 Agent 正常运行。
>
> 📦 默认从 OpenClaw 日志直接解析（零额外依赖），也支持从 Portkey 网关获取更丰富的 trajectory 数据。
>
> 🛡 每一轮 ROUND_START 都会**主动定位 OpenClaw 主进程**并枚举它派生的工具调用子进程，逐个抓 SELinux/AppArmor 标签、capabilities、namespaces、cgroup、loginuid 等，作为 `pid_info` JSON 快照固化到 `rounds.pid_info`。详见下一节「[进程 & 安全上下文采集](#进程--安全上下文采集)」。

---

## 进程 & 安全上下文采集

ClawAVC 内置了一个独立模块 [`backend/auditor/monitor/proc_info.py`](./backend/auditor/monitor/proc_info.py)（与 `watcher.py` 平级），在每次 ROUND_START 时**主动定位 OpenClaw 主进程**并采集它本身和它启动的工具调用子孙进程的完整安全上下文。结果作为 JSON 字符串写入 `rounds.pid_info` 字段，可在前端审计卡片上完整回放本轮的"谁在跑、跑在什么标签下"。

### 为什么不靠扫日志文件 fd

最直觉的做法是「谁打开了 session.jsonl 谁就是 OpenClaw」，但**绝大多数 logger 写一行就 flush + close fd**，watcher 拿到事件那一刻 fd 早已关闭，扫 `/proc/*/fd/` 是空的。所以 ClawAVC 改用**主动启发式定位**：基于 `cmdline`、`comm`、`cwd` 三路信号定位主进程，再从主进程反向遍历进程树枚举所有活着的工具子进程。

### 主进程定位策略

| 优先级 | 方法 | 说明 |
|:--:|------|------|
| 0 | `cached` | 上一轮的 `(pid, starttime_ticks)` 仍存活且 starttime 未变 → 直接复用，跳过整次 `/proc` 扫描 |
| 1 | `cmdline_match` | 扫所有进程的 `argv` 与 `comm`，按评分制选最佳候选（精确匹配 100，前缀匹配 95，路径组件匹配 60，等） |
| 2 | `cwd_boost` | 候选的 `cwd` 在 `openclaw_root` 目录下时 +20 加权（用于多个 OpenClaw 实例时消歧） |
| 3 | `fd_writer_fallback` | 兜底：扫 fd 表找 jsonl 写入者（多数 logger 行不通） |

**默认黑名单**（`comm_blacklist`）—— 这些进程**永远不算** OpenClaw，即使它们的 `cwd` 或参数里碰巧含 `openclaw`：
`bash / sh / zsh / fish / dash / ksh / csh / tmux / tmux: server / screen / sudo / su / systemd / init / login / sshd / agetty / ...`

**默认排除关键字**（`exclude_keywords`）：`clawavc / claw-avc / claw_avc` —— 防止 ClawAVC 自身被误识别为被监控对象。

### 每个进程采集到的字段

| 类别 | 字段 |
|------|------|
| **身份** | pid, ppid, tgid, comm, cmdline, argv, exe, cwd, root（chroot 检测） |
| **凭证** | uid 四元组（real/effective/saved/fs，自动解析用户名）、gid 四元组、附加组、**loginuid**（审计登录 uid）、**audit_session_id** |
| **资源** | state、threads、vm_rss/size/peak/swap_kb、num_fds、`/proc/<pid>/io` 全部计数器 |
| **能力（caps）** | CapInh / CapPrm / CapEff / CapBnd / CapAmb 全部按位**解码成 41 个 cap 名**（CAP_SYS_ADMIN…），同时保留原始 hex |
| **沙箱** | seccomp 模式（disabled / strict / filter）、no_new_privs、**全部 9~10 个 namespaces 的 inode**（mnt/pid/net/uts/ipc/cgroup/user/time/`pid_for_children`/`time_for_children`） |
| **MAC 标签** | `/proc/<pid>/attr/{current,exec,prev,fscreate,keycreate,sockcreate}` —— 同时覆盖 SELinux 与 AppArmor |
| **容器/cgroup** | cgroup 全文 + 自动识别 docker / kubernetes / cri-o / podman / containerd / lxc |
| **环境** | 白名单环境变量（PATH / USER / HOME / LANG / CONTAINER 等，规避秘密泄漏） |
| **启动时间** | clock_ticks → epoch → ISO（精确到秒） |
| **fd 采样** | num_fds + 前 20 个 fd 的目标路径 |

### 一次 ROUND_START 输出示例

```jsonc
{
  "openclaw_root": "/root/.openclaw",
  "jsonl_path": "/root/.openclaw/agents/main/sessions/<uuid>.jsonl",
  "captured_at": "2026-05-31T22:30:00+08:00",
  "discovery": {
    "method": "cmdline_match",       // 或 "cached" / "fd_writer_fallback"
    "candidates_count": 1,
    "selected_pid": 1017536,
    "selected_score": 95,
    "selected_reason": "score=95"
  },
  "main": {                          // 完整 collect_pid_info
    "pid": 1017536,
    "comm": "openclaw-gatewa",
    "cmdline": "openclaw-gateway",
    "exe": "/usr/bin/node",
    "uid": { "real": 0, "effective": 0, "real_name": "root", "effective_name": "root" },
    "capabilities": { "effective": ["CAP_CHOWN", "CAP_SYS_ADMIN", ... 41 项], ... },
    "seccomp": "disabled",
    "no_new_privs": false,
    "security_labels": {
      "current": "unconfined_u:unconfined_r:unconfined_t:s0-s0:c0.c1023",
      "prev":    "unconfined_u:unconfined_r:unconfined_t:s0-s0:c0.c1023"
    },
    "namespaces": { "mnt": "mnt:[4026531841]", "pid": "pid:[4026531836]", ... },
    "cgroups": [...], "container": null,
    "loginuid": 0, "audit_session_id": 23,
    "start_time": { "clock_ticks": 558931836, "iso": "2026-05-25T12:30:11+08:00" }
  },
  "ancestors": [ /* 4 层父链 (pid/comm/cmdline/exe/user/label) */ ],
  "descendants": [
    {
      "pid": 1660195, "depth": 1, "comm": "python3",
      "cmdline": "python3 /home/hx/.../tools/safe_file_reader/server.py",
      "user": "root",
      "security_labels": { "current": "unconfined_u:unconfined_r:unconfined_t:s0-s0:c0.c1023" }
    }
    /* ... 还有 10 个工具调用子进程 */
  ],

  // 顶层 shortcut：方便前端按工具 PID 直接列展、做异常对比
  "main_selinux_label":   "unconfined_u:unconfined_r:unconfined_t:s0-s0:c0.c1023",
  "main_exec_label":      null,
  "tool_subprocess_labels": [
    { "pid": 1660195, "comm": "python3",
      "cmdline": "...safe_file_reader/server.py",
      "label": "unconfined_u:..." }
    /* ... */
  ],

  "system": {
    "selinux":  { "mode": "permissive", "policyvers": "33", "mls": "1" },
    "apparmor": { "enabled": false },
    "kernel":   "Linux version 5.14.0-...",
    "hostname": "..."
    // 故意不包含 ClawAVC 后端自身的 SELinux label —— 我们只关心被监控目标
  },

  "collect_duration_ms": 43
}
```

### 性能

- 单次采集典型 **40–80 ms**（root + 标准服务器规模 `/proc`）
- `_main_pid_cache` 命中 (`method=cached`) 时只扫一棵进程树，不再扫整个 `/proc`
- 任何采集失败被 watcher 静默捕获，**不阻塞** round 上报；日志会落 `[monitor] pid_info note: ...`

### 独立调试

```bash
cd backend
uv run python3 auditor/monitor/proc_info.py \
    --openclaw-root /root/.openclaw \
    --hint openclaw \
    --ancestors 4 --descendants-depth 6 --descendants-max 64
```
直接打印 JSON 结果，可用于排查"为什么这台机器上 OpenClaw 没被定位到"。

### 安全约束

- **不**采集任意进程的环境变量原文（仅白名单），避免 token / API key 通过 `pid_info` 落到 DB
- **不**采集 ClawAVC 后端自身的 SELinux label —— 我们只关心被监控目标
- 所有读取均 best-effort：`FileNotFoundError` / `PermissionError` 都被静默吞掉，不影响整体快照

---

## 安全拦截

ClawAVC 支持与 portkey 网关深度集成，实现 Agent 工具调用的实时安全拦截。

### 拦截策略

| 功能 | 说明 |
|------|------|
| **拦截 IR 外工具** | 开启后，portkey 网关在收到上游 LLM 返回的 tool_calls 时，会同步等待本轮 IR 翻译完成，仅放行 IR 白名单内的工具；非白名单工具会被替换为系统提示，并将拦截事件上报至 ClawAVC |
| **死循环熔断** | 当同一 turn 内对同名同参 tool_call 累计调用达到阈值（默认 3 次）时，网关将跳过 retry，直接合成"loop break"拒绝文本流，强制 Agent 改用自然语言回答 |
| **IR 长轮询超时** | portkey 网关请求 `/api/translator/turn-ir` 时，clawAVC 会先等待 watcher 异步翻译完成；若超时则 fallback 调一次 translate 作为兜底，仍失败则放行 + 上报 ir_timeout 事件 |

### 拦截链路

```
Agent 请求经 portkey 网关转发至上游 LLM
    ↓
LLM 返回含 tool_calls/tool_use 时，网关同步请求 clawAVC 的 /api/translator/turn-ir
    ↓
clawAVC 按 turn_key 缓存翻译结果（同一 turn 复用），返回 allowed_tools 白名单
    ↓
网关重写非白名单工具调用为系统提示，并 POST 上报至 /api/intercept/events
    ↓
本页通过 SocketIO 实时刷新拦截事件
```

### 拦截事件

拦截事件存储在 `intercept_events` 表中，支持通过 `/api/intercept/events` 接口查询。事件类型包括：
- `ir_tool_block`：工具被 IR 白名单拦截
- `ir_loop_break`：死循环熔断触发
- `ir_timeout`：IR 长轮询超时

---

## 模拟攻击

模拟攻击模块用于在隔离环境中复现典型的 Agent 攻击向量，验证 ClawAVC 检测引擎的防御能力。页面按攻击类型用色块分组，每类下方对应一个攻击配置模块。

### 威胁场景

| 场景 | 等级 | 攻击目标 | 说明 |
|------|------|----------|------|
| **运行时篡改**（Runtime Tampering） | HIGH | Tool Dispatch 调度层 | 篡改 Agent 运行时的工具映射，请求工具 A 实际执行工具 B |
| **工具注入**（Tool Injection） | CRITICAL | Tools Manifest 工具注册表 | 向可用工具列表注入伪装的恶意工具，诱导 LLM 自然调用 |

### 工具注入攻击配置

「工具注入」场景支持下发攻击配置，每项可独立开启 / 关闭，开启后填写攻击内容（不校验目标文件路径或网络是否真实存在）。配置持久化到 `config` 表，键前缀 `attack.inject.*`。

| 配置 key | 说明 | 内容示例 |
|----------|------|----------|
| `tool_injection.network` | 固定网络外发 — 注入工具被调用时强制外连指定地址 | `http://malicious.example.com/collect` |
| `tool_injection.filepath` | 固定访问文件路径 — 注入工具被调用时强制读取指定文件 | `/root/.ssh/id_rsa` |
| `tool_injection.syscall` | 异常 syscall 序列 — 注入工具被调用时执行所选 `rule_id` 的 syscall 序列（规则集来自 `backend/static/rule_test_atk.json`） | `DT异常序列_003` |

### 运行时篡改攻击配置

「运行时篡改」场景同样支持可配置攻击，每项可独立开启 / 关闭。

| 配置 key | 说明 | 内容示例 |
|----------|------|----------|
| `runtime_tamper.replace` | 替换工具 — 将 Agent 请求的工具 A 替换为工具 B | `exec` |
| `runtime_tamper.insert` | 插入工具 — 在工具调用列表中插入额外工具 | `malicious_tool` |

每个配置项在 `config` 表中存为两条记录：`attack.inject.<item>.enabled`（`true`/`false`，是否开启）与 `attack.inject.<item>.value`（攻击内容）。

#### 异常 syscall 序列联动 (sys_probe)

`tool_injection.syscall` 不在前端直接输入字符串，而是通过独立组件 `frontend/src/components/RuleSelectDialog.vue` 弹窗选择：

- 弹窗加载 `GET /api/attack/rules`，后端读取 `backend/static/rule_test_atk.json`，返回每条规则的 `rule_id` / `sequence`（syscall 名拼接） / `note` / `score` / `source`
- 支持按 `rule_id` 或 syscall 名搜索，单选 radio 生效
- 外部 MCP 工具 [`agent_perm_audit/tools/sys_probe/server.py`](../agent_perm_audit/tools/sys_probe/server.py) 在被调用时会远程拉取本机 `GET /api/attack/tool-config?key=tool_injection.syscall` 取到当前选中的 `rule_id`，按 `rule_test_atk.json` 内对应规则真实执行该序列里的 syscall
- 当序列里包含网络 `connect` 时，sys_probe 走的是**应用层 HTTP GET** —— 真访问 `http://8.152.192.7:15100/api/webhook`（裸 TCP `connect()` 无法携带 URL 路径，必须走 HTTP 才能命中具体路由）
- rule_id 解析优先级：环境变量 `PERM_AUDIT_SYSCALL_SEQ` > `PERM_AUDIT_RULE_ID` > 远程拉取 ClawAVC > 默认 `DT异常序列_003`

### 攻击消息模拟

系统提供 `GET /api/attack/messages` 接口获取模拟攻击消息列表，以及 `DELETE /api/attack/messages` 接口清空消息，用于端到端测试攻击检测管线。

### Webhook 接口

系统提供 `ANY /api/webhook` 接口，用于接收外部系统（如 sys_probe 的 HTTP GET 回调）的 webhook 通知。该接口接受所有 HTTP 方法，便于测试系统集成。

### 对外接口

外部系统可通过 `key`（即上表的配置 key）查询某项工具配置的开启状态与具体内容：

```
GET /api/attack/tool-config?key=tool_injection.filepath
```

```json
{
  "ok": true,
  "data": {
    "key": "tool_injection.filepath",
    "enabled": true,
    "value": "/root/.ssh/id_rsa"
  }
}
```

> 不传 `key` 时返回全部工具注入配置；未知 key 返回 `404`。该接口已标记为对外公开，可在 `/api-docs` 页面查看并直接测试。

---

## 页面模块

| 路由 | 模块 | 说明 | 权限 |
|------|------|------|------|
| `/login` | 入口鉴权 | 输入入门口令验证访问权限 | 公开 |
| `/` | 首页 | 系统介绍、检测维度说明、异常阈值可视化 | 入门口令 |
| `/monitor` | 运行监控 | 监控配置 + 实时审计卡片流（筛选/分页/WebSocket实时推送） | 入门口令 |
| `/attack` | 模拟攻击 | 预设恶意场景验证检测能力（灰度中） | 入门口令 |
| `/policy` | 策略翻译 | IR 翻译器管理（翻译测试/模型配置/策略库/翻译日志/默认策略） | 入门口令 |
| `/security` | 安全拦截 | portkey 网关拦截策略配置 + 拦截事件实时展示 | 入门口令 |
| `/database` | 数据运维 | 可视化表编辑器 + SQL 控制台 + 数据导出入口 | 查询：入门口令 / 写操作：特权 |
| `/export` | 数据导出 | SQL 筛选 + 多格式导出（CSV/Excel/TXT/JSON/JSONL） | 入门口令 |
| `/replay` | 流量回放 | 选择历史 Round 以 WSS 推送方式回放，便于调试客户端或演示 | 入门口令 |
| `/api-docs` | 对外接口 | 所有对外公开 API 文档查看与测试 | 入门口令 |
| `/navigator` | 快捷导航 | 可配置的外部链接导航页，支持 JSON 配置 | 入门口令 |
| `/anomaly-chat` | 异常分析对话 | 选择某轮审计记录，由小异基于工具调用逐步取证研判 | 入门口令 |
| `/settings` | 平台管理 | 会话管理、入门口令配置、Round更新时间限制开关 | 特权配置项需特权密钥 |

### 流量回放

流量回放功能允许用户选择历史 Round 数据，通过 WSS 推送方式重新发送，便于调试客户端或进行演示。

**功能特点**：
- 选择历史 Round 进行回放
- 可配置回放速度（0.1x ~ 2x）
- 自动按原始时间间隔推送四个阶段：`round_start` → `round_ir_ready` → `round_end` → `round_kernel`
- 实时显示 WSS 收到的消息
- 回放日志记录推送进度

**使用方式**：
1. 进入「流量回放」页面
2. 在下方 Round 列表中选择一个历史 Round
3. 配置回放速度（默认 1x）
4. 确保 WSS 已连接到 `/wss/monitor`
5. 点击「开始回放」

**API 接口**：

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/monitor/send-test` | 发送模拟/回放消息到 WSS |

### 策略翻译详情

策略翻译页面包含以下 Tab：

| Tab | 说明 |
|-----|------|
| 翻译测试 | 输入用户 query 测试 IR 翻译结果，查看 Level-1 场景分类和 Level-2 策略生成 |
| 模型配置 | 配置翻译器使用的 LLM API 地址、API Key、模型名称、温度参数等 |
| 策略库 | 查看和编辑策略注册表（scenes.json + tools/*.json），支持场景和函数的增删改查 |
| 翻译日志 | 查看 IR 翻译历史记录，支持按类型和场景筛选 |
| 默认策略 | 配置默认兜底 IR 策略，当翻译失败或无法识别场景时生效 |
| 提示词管理 | 查看和编辑 Level-1/Level-2 翻译提示词模板，支持预览和重置 |

### 运行监控详情结构

```
┌─ Access · 行为轨迹 ─────────────────────────┐
│  ├─ 用户态行为（工具/参数/资源）              │
│  └─ 内核态轨迹（集成中）                      │
├─ View · 意图 - IR 策略 ─────────────────────┤
│  └─ subject/objects 策略树                    │
├─ Compliance · 合规判定 ──────────────────────┤
│  ├─ 用户态意图行为一致性检测                  │
│  ├─ 内核态行为意图一致性检测（集成中）         │
│  └─ 多维行为轨迹综合研判（集成中）            │
└──────────────────────────────────────────────┘
```

---

## 异常分析对话（小异）

「小异」是 ClawAVC 内置的二阶段异常判断大模型，用于对运行日志做自动研判与交互式异常分析对话。用户在异常分析对话页选择某轮审计记录后，小异读取该轮完整的多维行为轨迹审计数据，基于工具调用逐步取证，输出结构化的合规研判。

### 工作原理

小异采用「技能分析（Skill Analysis）」编排，核心特点是**流式 + 工具调用实时呈现**：

```
用户选定 round
    ↓
加载该轮完整多维行为轨迹审计数据（system + 数据）
    ↓
流式请求大模型（stream + tools）
    ↓   一边接收模型输出一边解析 tool_calls
    ├─ 解析出某个工具名 → 立即执行该工具 → 结果实时推送前端
    ├─ 解析出文本内容   → 逐字流式推送给前端（最终分析）
    └─ 流结束           → 组装完整 tool_calls，追加到消息历史供下一轮分析
    ↓
（如需多轮取证）重复上述步骤，直到模型不再调用工具，输出最终研判
```

> 取证工具的入参只需外部已知的 `round_id`，不依赖模型生成的 arguments，因此工具结果可随解析**实时逐个呈现**，不必等整轮大模型输出结束，显著降低等待感。

### 小异配置

小异相关配置项（键前缀 `monitor_conf.`）集中在「运行监控 → 异常分析对话」页右上角「设置」弹窗中可视化配置，也可通过 `PUT /api/monitor/config` 直接写入。各配置项如下：

| 配置 key | 说明 | 默认值 |
|----------|------|--------|
| `anomaly_llm_url_v2` | OpenAI 兼容地址（对话与技能分析共用）；未配置则不调用大模型 | 无 |
| `anomaly_llm_max_tokens` | 大模型单次最大生成 token 数 | `2048` |
| `anomaly_llm_base_prompt` | 分析指令（告诉小异如何分析数据），留空使用默认 | 无 |
| `anomaly_llm_system_prompt` | 系统人设（对所有对话生效），留空使用默认 | 无 |
| `anomaly_llm_skill_prompt` | **技能分析专属**系统提示词，定义工具使用策略、分析步骤与最终输出格式，仅对「技能分析」生效，留空使用默认 | 无 |
| `anomaly_llm_tool_compress` | 工具结果过长时的处理开关：`true` = 调用大模型压缩；`false` = 直接截断 | `false` |
| `anomaly_llm_tool_compress_max` | 触发压缩 / 截断的工具结果长度阈值（字符数） | `2000` |

> ⚠️ 上述 key 均在后端 `MONITOR_CONF_KEYS` 白名单内，经配置接口保存时会被严格校验；小异不单独维护模型字段，复用所指向服务的默认模型。

### 工具结果处理

当某取证工具返回内容超过 `anomaly_llm_tool_compress_max` 阈值时：
- **开关开启**（`tool_compress = true`）：调用大模型对该结果做摘要压缩后再交给小异继续分析；
- **开关关闭**（`tool_compress = false`）：直接截断到阈值长度，并标注「（结果过长，已截断）」。

### 设置弹窗

「小异设置」弹窗（宽 760px，内容超出可滚动）提供上述全部配置项的可视化编辑，分区为：
- **模型接入**：接口地址、最大 token；
- **提示词分层**：分析指令 / 系统人设 / 技能分析提示（三档互不干扰，按需覆盖默认）；
- **工具结果压缩**：开关 + 阈值输入。

清空对话（右上角「清空」按钮）会重置为系统默认问候语，使其不进入发送给大模型的上下文，确保新一轮分析不带历史残留。

---

## 流量回放

（见 [页面模块 → 流量回放](#流量回放)）

---

## 权限体系

### 双层权限模型

```
┌─────────────────────────────────────┐
│  特权层（Privileged）                │
│  - 修改入门口令                      │
│  - 数据库写操作（INSERT/UPDATE/DELETE）│
│  - config 表访问                     │
│  - 20 分钟会话有效期（可配置）        │
├─────────────────────────────────────┤
│  普通层（Normal）                    │
│  - 访问所有页面                      │
│  - 查询数据（SELECT）                │
│  - 查看实时审计数据                  │
│  - 持久会话（sessionStorage）        │
└─────────────────────────────────────┘
```

### 特权验证机制

1. 用户点击需特权操作的区域 → 触发 `PrivilegeDialog` 弹窗
2. 输入特权密钥 → 后端验证 → 生成 `session_token`
3. Token 存入 `sessionStorage`，20 分钟内免重复验证
4. `PrivilegeStatus` 组件实时展示剩余倒计时
5. 到期自动失效，需重新验证

> ⚠️ 特权密钥不可通过界面修改，仅可通过数据库直接操作。

---

## API 文档

### 鉴权

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/auth` | 验证入门口令 |
| `POST` | `/api/admin/verify` | 验证特权密钥，返回 session_token |
| `GET` | `/api/admin/session` | 检查特权会话有效性 |

### 数据

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| `GET` | `/api/rounds?limit=20&offset=0&query=&round_id=&time_from=&time_to=` | 分页+筛选查询 | 普通 |
| `GET` | `/api/rounds/query?round_id=xxx` | 查询单条 round 详情 | 对外公开 |
| `PUT` | `/api/rounds/update` | 更新 round 字段（仅支持部分字段，15分钟内） | 对外公开 |
| `POST` | `/api/rounds` | 上报 round (event=start/end) | 内部调用 |
| `GET` | `/api/stats` | 统计概览 | 普通 |
| `POST` | `/api/import` | 手动触发从 JSONL 文件导入历史 Round 数据 | 特权 |

### 监控

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| `GET` | `/api/monitor/config` | 获取监控配置 | 普通 |
| `PUT` | `/api/monitor/config` | 保存配置 | 普通 |
| `GET` | `/api/monitor/status` | 监控运行状态 | 普通 |
| `POST` | `/api/monitor/start` | 启动监控 | 普通 |
| `POST` | `/api/monitor/stop` | 停止监控 | 普通 |
| `POST` | `/api/monitor/send-test` | 发送模拟/回放消息到 WSS | 普通 |

### 翻译器

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| `POST` | `/api/translator/translate` | IR 翻译 (内部) | 内部 |
| `POST` | `/api/translator/test` | 翻译测试 (UI) | 普通 |
| `POST` | `/api/translator/level1` | 仅测试 Level-1 场景分类 | 普通 |
| `POST` | `/api/translator/level2` | 仅测试 Level-2 策略生成 | 普通 |
| `POST` | `/api/translator/turn-ir` | portkey 网关联动接口，长轮询返回 IR 白名单 | 内部 |
| `GET/PUT` | `/api/translator/config` | LLM 模型配置 | 特权 |
| `GET/PUT` | `/api/translator/prompts` | 提示词管理（查看/编辑/预览/重置） | 普通 |
| `GET` | `/api/translator/registry` | 策略库全量 | 普通 |
| `GET` | `/api/translator/registry-health` | 策略库健康状态检查 | 普通 |
| `GET/PUT` | `/api/translator/registry-path` | 策略库路径配置 | 特权 |
| `GET/PUT` | `/api/translator/scene/<name>` | 场景详情 CRUD | 查看普通/修改特权 |
| `GET/PUT` | `/api/translator/scene/<name>/desc` | 更新场景描述 | 特权 |
| `GET/PUT` | `/api/translator/scene/<name>/functions` | 更新场景函数定义 | 特权 |
| `GET/PUT` | `/api/translator/scene/<name>/function/<func>` | 更新场景单个函数定义 | 特权 |
| `GET/PUT` | `/api/translator/default-policy` | 默认兜底策略管理 | 特权 |
| `GET` | `/api/translator/logs` | 翻译日志查询 | 普通 |

### 安全拦截

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| `GET/PUT` | `/api/config/intercept_non_ir_tools` | 拦截 IR 外工具开关 | 特权 |
| `GET/PUT` | `/api/config/loop_breaker` | 死循环熔断配置 | 特权 |
| `GET/PUT` | `/api/config/turn_ir_wait_ms` | IR 长轮询超时配置 | 特权 |
| `POST` | `/api/intercept/events` | 上报拦截事件（portkey 网关调用） | 内部 |
| `GET` | `/api/intercept/events` | 查询拦截事件列表 | 普通 |
| `DELETE` | `/api/intercept/events` | 清空拦截事件 | 特权 |

### 数据库

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| `GET` | `/api/db/tables` | 列出所有表 | 普通 |
| `POST` | `/api/db/query` | 执行 SQL | SELECT 普通 / 写操作特权 |

### 配置

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| `GET` | `/api/config` | 获取公开配置 | 普通 |
| `PUT` | `/api/config` | 更新配置 | 特权 |
| `GET/PUT` | `/api/config/admin_ttl` | 特权会话有效期配置 | 特权 |
| `GET/PUT` | `/api/config/round_update_time_limit` | Round 更新时间限制开关 | 特权 |
| `GET/PUT` | `/api/config/navigator` | 快捷导航配置 | 普通/特权 |

### 模拟攻击

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| `GET` | `/api/attack/config` | 获取攻击配置（内部页面加载） | 普通 |
| `PUT` | `/api/attack/config` | 保存攻击配置（含开启状态与内容） | 普通 |
| `GET` | `/api/attack/rules` | 获取异常 syscall 规则列表 | 普通 |
| `GET` | `/api/attack/tool-config?key=tool_injection.network` | 对外接口：按配置 key 查询开启状态与内容 | 对外公开 |
| `GET/DELETE` | `/api/attack/messages` | 攻击消息模拟列表/清空 | 普通 |

### 流量回放

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| `POST` | `/api/monitor/send-test` | 发送模拟/回放消息到 /wss/monitor | 普通 |

### Webhook

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| `ANY` | `/api/webhook` | Webhook 接收接口（所有 HTTP 方法） | 公开 |

### WebSocket

| 事件 | 方向 | Payload | 说明 |
|------|------|---------|------|
| `new_round_info` | Server → Client | Round 对象 | 新 round 实时推送 |
| `intercept_event` | Server → Client | 拦截事件对象 | 拦截事件实时推送 |
| `push` | Server → Client | 统一推送事件 | 按 `push_type` 区分类型 |
| `connect` | Client → Server | - | 建立连接 |

---

## WebSocket 长连接

ClawAVC 提供基于 Socket.IO 的 WebSocket 推送服务，按消息组订阅。

### 连接地址

```
ws://<host>:15100/wss/<namespace>
```

| 消息组 | Namespace | 说明 |
|--------|-----------|------|
| 运行消息组 | `/wss/monitor` | Agent 行为审计实时推送 |
| 默认命名空间 | `/` | 平台内部推送（新 round、拦截事件等） |

### 统一事件

所有消息通过 `push` 事件推送，`push_type` 字段区分类型：

| push_type | 说明 | 触发时机 |
|-----------|------|----------|
| `round_start` | Round 开始 | Agent 开始新一轮交互 |
| `round_ir_ready` | IR 策略就绪 | 意图翻译完成 |
| `round_end` | Round 结束 | 完整判定结果 |
| `round_kernel` | 内核态信息推送 | 内核态信息上报后推送 |
| `intercept_event` | 拦截事件 | portkey 网关上报工具拦截 |

### 接入示例

```javascript
// JavaScript (socket.io-client)
const socket = io("ws://host:15100/wss/monitor", { path: "/wss", transports: ["websocket"] })
socket.on("push", (data) => console.log(data.push_type, data.round_id))
```

```python
# Python (python-socketio)
import socketio
sio = socketio.Client()

@sio.on("push", namespace="/wss/monitor")
def on_push(data):
    print(data["push_type"], data["round_id"])

sio.connect("ws://host:15100", socketio_path="/wss", namespaces=["/wss/monitor"])
sio.wait()
```

---

## API 文档系统

ClawAVC 内置自动化 API 文档生成，**零手动维护**。

### 工作原理

```
Flask 路由定义 (@app.route)
        │
        ▼
generate_docs() 自动反射扫描
        │
        ├── ENDPOINT_REGISTRY (详细元数据)
        ├── @api_doc() 装饰器 (可选增强)
        └── 函数 docstring (兜底)
        │
        ▼
GET /api/docs       ← 全部接口文档
GET /api/docs/public ← 对外公开接口
```

### 对外接口页面

访问 `/api-docs` 页面可查看所有对外公开的接口文档，包含：
- 按分类折叠展示
- 完整参数表格（类型、默认值、说明）
- 返回示例 JSON
- **右侧 API 测试面板**：可直接发送请求测试接口

### 内核态信息上报

系统支持内核态信息的上报和推送，包括系统调用序列、LSM hook检查结果和资源事实信息。

**新增字段**（rounds 表）：
- `kernel_syscall_seq`: 内核态系统调用序列文件路径 (JSONL格式)
- `kernel_lsm_hook_result`: 内核态LSM hook检查结果文件路径 (JSONL格式)
- `kernel_resource_facts`: 内核资源事实内容
- `judge_result_kernel`: 内核态判断结果 Markdown 文件路径
- `syscall_judge`: 系统调用判断结果 Markdown 文件路径

**API 接口**：

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/rounds/kernel` | 内核态信息上报（支持15分钟时间限制） |
| `POST` | `/api/rounds/detection/kernel` | 内核态判断结果上报（支持15分钟时间限制） |
| `POST` | `/api/rounds/detection/syscall` | 系统调用判断结果上报（支持15分钟时间限制） |

**WebSocket 推送**：

新增 `push_type: "round_kernel"` 阶段，在 round_end 之后推送内核态信息：
```json
{
  "push_type": "round_kernel",
  "round_id": "xxx",
  "kernel_syscall_seq": "/path/to/syscall_seq.jsonl",
  "kernel_lsm_hook_result": "/path/to/lsm_hook_result.jsonl",
  "kernel_resource_facts": "资源事实内容...",
  "push_time": "2026-06-05 16:52:00.123+0800"
}
```

**推送时序**：
- `round_start` → `round_ir_ready` → `round_end` → `round_kernel`
- round_start 必须最先推送
- 其他阶段为异步处理，推送顺序可能不固定
- 前端应根据 `push_type` 进行状态更新

**流量回放**：
- 回放时自动包含 `round_kernel` 阶段（如果存在内核态数据）
- 进度条分段显示：round_start(33%) → round_ir_ready(66%) → round_end(80%) → round_kernel(100%)

### IR 翻译器高级功能

#### 两阶段翻译管线

IR 翻译器采用两阶段 LLM 管线：
1. **Level-1 场景分类**：将用户 query 分类为最小必要场景集合（如 `file_ops`、`shell_exec`、`search`）
2. **Level-2 策略生成**：基于选中场景的函数定义，生成结构化 `subject/objects` 权限策略

#### 分阶段数据库更新

翻译结果采用**分阶段写入** `translation_log` 表，确保前端能实时看到翻译进度：

```
round_start 触发
    ↓
_on_round_start() 被调用
    ↓
1. 立即插入 pending 记录到 translation_log（level1/level2 为空）
    ↓
2. 启动 _query_and_ir_worker 线程（异步）
    ↓
_query_and_ir_worker 中：
  1. 等待 user_query 出现（从 gateway 或 session 文件）
  2. 找到 user_query 后，调用 ir_translate（同步）
     ↓
     ir_translate 内部：
     1. 立即插入 pending 记录到 translation_log
     2. 执行 Level1 → 完成后更新 translation_log 的 level1_json
     3. 执行 Level2 → 完成后更新 translation_log 的 level2_json 和 validation
  3. 结果存到 self._round_ir_results
    ↓
round_end 触发
    ↓
_on_round_end() 被调用
    ↓
从 self._round_ir_results 获取 ir_result
```

**特点**：
- 翻译开始时立即创建数据库记录（前端可见"翻译中"状态）
- Level1 完成后立即更新，前端可看到场景分类结果
- Level2 完成后更新最终 IR 策略
- 即使两个阶段都很快，数据库也会有 3 次更新，前端不会漏掉任何进度

#### 策略验证

翻译结果会自动经过 `validate_ir()` 函数验证，检查：
- policies 数组存在且非空
- subject 是否为已知场景
- tool 对象的 identifier 是否在注册表中
- params 参数名是否合法
- file 对象是否有 identifier 和 actions

#### 策略库热重载

支持通过 API 重新加载策略库（`GET /api/translator/registry-health` 检查健康状态，`PUT /api/translator/registry-path` 配置自定义路径），无需重启服务。

#### 默认策略

当 IR 翻译失败或无法识别场景时，系统可使用默认兜底策略（`GET/PUT /api/translator/default-policy`）。默认策略经过 normalize 和 validate 后存储。

### 新增接口文档

在 `backend/api_docs.py` 的 `ENDPOINT_REGISTRY` 中添加一条记录即可，文档自动生效：

```python
"POST /api/new-endpoint": {
    "summary": "接口描述",
    "category": "分类",
    "params": [{"name": "key", "type": "string", "desc": "说明"}],
    "response": {"ok": True},
    "public": True,  # 设为 True 即对外展示
}
```

---

## 技术栈

### Backend

| 组件 | 版本 | 用途 |
|------|------|------|
| Python | 3.14+ | 运行时 |
| Flask | 3.1+ | Web 框架 |
| Flask-SocketIO | 5.6+ | WebSocket 支持 |
| Flask-CORS | 6.0+ | 跨域处理 |
| gevent | 26+ | 异步 Worker |
| SQLite | 3.34+ | 持久化存储 |
| uv | latest | 包管理 |
| requests | latest | LLM API 调用 |

### Frontend

| 组件 | 版本 | 用途 |
|------|------|------|
| Vue | 3.4+ | UI 框架 |
| Vite | 5.4+ | 构建工具 |
| TDesign Vue Next | 1.9+ | UI 组件库 |
| vue-router | 4.x | 路由管理 |
| socket.io-client | 4.7+ | WebSocket 客户端 |

### 设计规范

| 属性 | 值 | 用途 |
|------|------|------|
| 主色 | `#0052D9` | 腾讯蓝，品牌色 |
| 异常色 | `#ED7B2F` | 橙色，风险告警 |
| 正常色 | `#00a870` | 绿色，合规通过 |
| 背景 | `#f5f7fa` | 浅灰底色 |
| 卡片 | 白底 / 圆角 12-14px | 内容容器 |
| 字体 | PingFang SC / Microsoft YaHei | 中文优先 |

---

## 目录结构

```
clawAVC/
├── backend/
│   ├── app.py                 # Flask 主应用 + SocketIO + 全部 API
│   ├── db.py                  # SQLite 数据层（rounds/config/translation_logs/intercept_events 表）
│   ├── api_docs.py            # 自动化 API 文档生成
│   ├── auditor/
│   │   ├── translator/        # IR 翻译器 (Level-1 场景分类 + Level-2 策略生成)
│   │   │   ├── core.py        # 翻译核心（LLM 调用/提示词/验证/归一化）
│   │   │   └── policy_registry/  # 策略注册表 (scenes.json + tools/*.json)
│   │   └── monitor/           # 内置监控模块
│   │       ├── watcher.py     # OpenClaw日志监听 + 网关解析 + 调度
│   │       ├── ir_client.py   # 调用翻译接口获取 IR
│   │       ├── judge.py       # 用户态行为合规判定引擎
│   │       └── proc_info.py   # OpenClaw 主进程定位 + 工具子进程 SELinux/caps/ns 采集
│   ├── pyproject.toml         # uv 依赖声明
│   ├── requirements.txt       # pip 兼容依赖
│   └── .venv/                 # Python 虚拟环境（git ignored）
│
├── frontend/
│   ├── src/
│   │   ├── main.js            # 入口
│   │   ├── App.vue            # 根组件（侧边栏 + router-view）
│   │   ├── router/
│   │   │   └── index.js       # 路由定义 + auth guard
│   │   ├── views/
│   │   │   ├── LoginPage.vue      # 入口鉴权
│   │   │   ├── HomePage.vue       # 首页
│   │   │   ├── MonitorPage.vue    # 运行监控 (Tab容器)
│   │   │   ├── monitor/
│   │   │   │   ├── ConfigTab.vue  # 监控配置 (启停 + 数据源路径)
│   │   │   │   └── LogsTab.vue   # 运行日志 (筛选 + 分页 + 卡片流)
│   │   │   ├── PolicyPage.vue     # 策略翻译 (Tab容器)
│   │   │   ├── policy/
│   │   │   │   ├── TranslateTab.vue   # 翻译与提示词
│   │   │   │   ├── ConfigTab.vue      # 模型配置
│   │   │   │   ├── RegistryTab.vue    # 策略库管理
│   │   │   │   ├── LogsTab.vue        # 翻译日志
│   │   │   │   ├── DefaultPolicyTab.vue # 默认策略
│   │   │   │   └── PromptsTab.vue     # 提示词管理
│   │   │   ├── AttackPage.vue     # 模拟攻击
│   │   │   ├── AnomalyChatPage.vue # 异常分析对话（小异）
│   │   │   ├── SecurityPage.vue   # 安全拦截
│   │   │   ├── DatabasePage.vue   # 数据运维
│   │   │   ├── ExportPage.vue     # 数据导出
│   │   │   ├── ReplayPage.vue     # 流量回放
│   │   │   ├── ApiDocsPage.vue    # 对外接口
│   │   │   ├── NavigatorPage.vue  # 快捷导航
│   │   │   ├── SettingsPage.vue   # 平台管理
│   │   │   └── components/
│   │   │       ├── PrivilegeDialog.vue    # 特权验证弹窗（通用）
│   │   │       ├── PrivilegeStatus.vue    # 特权状态指示器（通用）
│   │   │       ├── RowDetailDrawer.vue    # 行详情抽屉（数据运维）
│   │   │       └── RuleSelectDialog.vue   # 规则选择弹窗（模拟攻击）
│   │   └── utils/
│   │       └── socket.js          # WebSocket 连接管理
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
│
├── logs/                      # 运行日志（git ignored）
├── infos/                     # 运行时数据（数据库/内核信息文件）
├── .claude/CLAUDE.md          # 项目开发文档
├── .gitignore
├── start.sh                   # 一键启动脚本
└── README.md
```

---

## 开发指南

### 本地开发

```bash
# 启动 Backend（热重载）
cd backend
uv run python3 app.py

# 启动 Frontend（HMR）
cd frontend
npm run dev
```

前端开发服务器自动代理 `/api` 和 `/socket.io` 到后端 15100 端口。

### 新增页面

1. 在 `frontend/src/views/` 创建 `XxxPage.vue`
2. 在 `frontend/src/router/index.js` 添加路由
3. 在 `frontend/src/App.vue` 的 `navItems` 添加导航项
4. 构建验证：`cd frontend && npx vite build`

### 新增 API

1. 在 `backend/app.py` 添加 Flask route
2. 需要持久化则在 `backend/db.py` 添加相应函数
3. 特权操作需检查 `_check_admin_session(token)`
4. 在 `backend/api_docs.py` 的 `ENDPOINT_REGISTRY` 添加文档元数据

### 数据库迁移

SQLite 数据库文件为 `infos/db/clawAVC.db`，表结构在 `backend/db.py` 的 `init_db()` 和 `init_config_table()` 中定义。新增表只需添加 `CREATE TABLE IF NOT EXISTS` 语句，不影响已有数据。

支持的数据库表：
- `rounds`：审计轮次数据
- `config`：平台配置项
- `translation_logs`：IR 翻译历史日志
- `intercept_events`：安全拦截事件记录

---

## 团队

| 成员 | 职责 |
|------|------|
| [@jjq0425](https://github.com/jjq0425) | 主研 |
| [@xiaoxuan668](https://github.com/xiaoxuan668) | 主研 |


也一并感谢 claude code、codex、Hy3、mimo、longcat、doubao、qwen、deepseek、 stepfun 的coding支持 （排名不分先后）


---

<div align="center">

*Built with purpose. Secured by design.*

*ClawAVC: 你的 Agent 跑得再快，我也接得住* 🫴✨

*——「爪」到擒来，合规无忧*

</div>
