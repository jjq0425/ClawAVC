# ClawAVC - Claw Access-View Compliance

## 项目定位
透视访问行为意图并校验其合规性的 AI Agent 行为审计可视化系统。
监控 OpenClaw Agent 的实际行为，将用户意图翻译为结构化 IR 策略，多维度比对合规性。

## 服务端口
- Backend: `15100` (Flask + gevent + SocketIO)
- Frontend: `15101` (Vite preview)
- 启动: `cd /home/hx/jjq/clawAVC && bash start.sh -d`

## 模块划分

### Backend (`/backend`)

#### app.py — Flask 主应用
所有 API 路由集中在此文件。gevent monkey-patch 在文件顶部。

**Rounds API:**
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/rounds?limit=20&offset=0&query=&round_id=&time_from=&time_to=` | 分页+筛选查询 |
| `GET` | `/api/rounds/query?round_id=xxx` | 查询单条 round 详情 |
| `PUT` | `/api/rounds/update` | 更新 round 字段（仅支持部分字段，15分钟内） |
| `POST` | `/api/rounds` | 上报 round (支持 event=start 和 event=end) |
| `GET` | `/api/stats` | 统计概览 |

**Monitor API:**
| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| `GET` | `/api/monitor/config` | 获取监控配置 | 公开 |
| `PUT` | `/api/monitor/config` | 保存配置 (key/value) | 公开 |
| `GET` | `/api/monitor/status` | 监控运行状态 | 公开 |
| `POST` | `/api/monitor/start` | 启动监控 (需先配路径) | 公开 |
| `POST` | `/api/monitor/stop` | 停止监控 | 公开 |

**Translator API:**
| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| `POST` | `/api/translator/translate` | 内部翻译接口 (monitor调用) | 内部 |
| `POST` | `/api/translator/test` | UI测试翻译 (is_ui_test=True) | 公开 |
| `GET/PUT` | `/api/translator/config` | LLM模型配置 | 特权 |
| `GET/PUT` | `/api/translator/prompts` | Level-1/Level-2 提示词 | 公开 |
| `GET` | `/api/translator/registry` | 策略库全量数据 | 公开 |
| `GET` | `/api/translator/scene/<name>` | 场景详情 | 公开 |
| `PUT` | `/api/translator/scene/<name>/desc` | 修改场景描述 | 特权 |
| `PUT` | `/api/translator/scene/<name>/functions` | 增删场景函数 | 特权 |
| `PUT` | `/api/translator/scene/<name>/function/<func>` | 修改函数定义 | 特权 |
| `GET/PUT` | `/api/translator/registry-path` | 策略库路径配置 | 特权 |
| `GET` | `/api/translator/registry-health` | 策略库健康检查 | 公开 |
| `GET` | `/api/translator/logs` | 翻译日志 | 公开 |
| `GET/PUT` | `/api/translator/default-policy` | 默认策略 | 公开 |

**其他 API:**
| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| `POST` | `/api/auth` | 入门口令验证 | 公开 |
| `POST` | `/api/admin/verify` | 特权密钥验证 | 公开 |
| `GET` | `/api/admin/session` | 检查特权会话 | 需token |
| `GET` | `/api/db/tables` | 列出表 | 公开 |
| `POST` | `/api/db/query` | SQL执行 | 写操作需特权 |

**Attack API (模拟攻击):**
| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| `GET` | `/api/attack/config` | 获取工具注入配置 (内部页面加载) | 公开 |
| `PUT` | `/api/attack/config` | 保存工具注入配置 (含开启状态) | 公开 |
| `GET` | `/api/attack/tool-config?key=tool_injection.<item>` | 对外接口: 按配置 key 查询开启状态与内容 | 对外公开 |

- 支持的注入项在代码中配置 (`ATTACK_INJECT_ITEMS`)，具体项及对应配置 key 可前往数据运维页面查看 config 表
- 每项在 config 表存为 `attack.inject.<item>.enabled` + `attack.inject.<item>.value`
- `tool-config` 接口 key 支持 `tool_injection.xxx` 或 `xxx`；不传 key 返回全部；未知 key 返回 404
- 该接口在 `api_docs.py` 的 ENDPOINT_REGISTRY 中标记 `public: True`

**Traffic Replay API (流量回放):**
| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| `POST` | `/api/monitor/send-test` | 发送模拟/回放消息到 /wss/monitor | 公开 |

- 后端自动设置 `is_mock: true` 和当前时间作为 `push_time`
- 前端可配置回放速度（0.1x ~ 2x）和选择推送阶段

#### db.py — SQLite 数据层

**表结构:**
- `rounds` — round_id, time_start, time_end, session_key, session_id, user_query, last_llm_message, action_json, ir_json, judge_result, is_abnormal, overall_score, attack_config, **pid_info**
- `config` — key (TEXT PRIMARY KEY), value (TEXT)
- `translation_log` — 翻译日志

> `pid_info` 是 `TEXT`，存 watcher 在 ROUND_START 时采集的 OpenClaw 主进程 + 子孙工具进程的 JSON 快照（PID/cmdline/exe/SELinux 标签/capabilities/namespaces/cgroup/ancestors 等）。详见 [`auditor/monitor/proc_info.py`](#proc_infopy--进程--安全上下文采集) 一节。`init_db()` 自带 `ALTER TABLE rounds ADD COLUMN pid_info TEXT DEFAULT ''` 迁移，存量库无需手动改。

**关键函数:**
- `insert_round_start(round_id, time_start, session_key, session_id, attack_config="", pid_info="")` — ROUND_START 时插入占位记录(score=-1)，attack_config / pid_info 一并固化
- `update_round_end(round_id, data)` — ROUND_END 时更新完整数据
- `insert_round(data)` — 兼容旧 orchestrator 的直接上报
- `get_rounds(limit, offset, query, round_id, time_from, time_to)` — 返回 {total, data}

#### auditor/translator/ — IR 翻译器

- `core.py` — 核心翻译逻辑
  - `translate(query, config, is_ui_test)` — 两阶段 LLM 管线
  - Level-1: 场景分类 (从 scenes.json 匹配)
  - Level-2: 生成 subject/objects 格式的权限策略
  - 含 normalize_ir() + validate_ir() 后处理
  - 动态从 DB 读取配置 (api_base_url, api_key, model, prompts)
- `policy_registry/` — 策略注册表
  - `scenes.json` — 15个场景定义 (desc + functions列表)
  - `tools/*.json` — 各场景工具函数的详细定义 (params, constraint_spec)
  - `tool_function_map.json` — ToolName → functions 映射

#### auditor/monitor/ — 内置监控模块

四个文件分工:
1. **watcher.py** — 核心协调器 (~1370行)
   - `RoundStateMachine` — 从 OpenClaw 日志检测 round 开始/结束
   - `RoundLedger.source_file` — 记录本轮第一条事件来自哪个 JSONL 文件，供 `_on_round_start` 用作 `proc_info.collect_for_round` 的 `jsonl_path` 入参
   - `FileTailer` — 尾随读取 .jsonl 日志文件
   - `MonitorOrchestrator` — 主循环, 协调 watcher + gateway + IR + judge
     - 持有 `_main_pid_cache: Optional[Tuple[int, int]]` —— `(pid, starttime_ticks)` 二元组，跨 round 复用 OpenClaw 主进程定位结果
   - Gateway 日志解析: 适配 Portkey 的 requestOptions 嵌套结构
   - ROUND_START → 调 `proc_info.collect_for_round` 抓 pid_info → 后台线程轮询 query → 请求 IR
   - ROUND_END → 等 IR → 解析 actions → judge → 上报

2. **ir_client.py** — HTTP 客户端
   - 调用 `POST /api/translator/translate`
   - 返回 (ir_dict, error_or_None)

3. **judge.py** — 完整搬运自 abnormal_judge_userState.py
   - `judge(action, IR)` → 文本判定结果
   - 三维检测: 工具调用一致性 + 参数一致性 + 资源访问一致性
   - LayeredCheckResult → layered_result_to_text()

4. **proc_info.py** — 进程 & 安全上下文采集（纯 stdlib，读 `/proc`）
   - `collect_for_round(openclaw_root, jsonl_path, hint_keywords, exclude_keywords, cached_main, ...)` — 顶层入口
   - `find_openclaw_main_pid(...)` — cmdline + cwd 启发式定位 OpenClaw 主进程（**不依赖 jsonl fd**）
   - `find_descendants(root_pid, max_depth, max_count)` — 反向遍历进程树枚举工具调用子孙进程，每个带 SELinux current label
   - `collect_pid_info(pid)` / `collect_pid_slim(pid)` — 完整 / 精简版单 PID 采集
   - `collect_ancestors(pid, max_depth)` — 父链
   - `collect_system_context()` — SELinux 模式 / AppArmor / kernel / hostname
   - `find_pids_writing(file_path)` — fd-writer 兜底（多数 logger close-and-reopen 时不可用）

**Monitor 工作流:**
```
OpenClaw 日志变化 → FileTailer 读取 → parse_line(line, source_file) → RoundStateMachine
  ├─ user_inbound/turn_started → _on_round_start
  │   ├─ proc_info.collect_for_round(openclaw_root, jsonl_path=r.source_file,
  │   │                              cached_main=self._main_pid_cache)
  │   │   → {discovery, main, ancestors, descendants, main_selinux_label,
  │   │      tool_subprocess_labels[], system, collect_duration_ms}
  │   │   → 更新 self._main_pid_cache = (main_pid, starttime_ticks)
  │   ├─ report_to_clawavc(event=start, attack_config=..., pid_info=<json>)
  │   │                                  → DB 插入 + WebSocket 推送
  │   └─ 启动 _query_and_ir_worker 线程
  │       ├─ 轮询网关日志找 user_query (max 30s)
  │       ├─ 找到 → report(ir_json="__loading__") → 前端显示转圈
  │       └─ 调用 /api/translator/translate → report(ir_json=结果)
  └─ turn_completed/response_routed → _on_round_end
      ├─ worker.join(65s) 等 IR 完成
      ├─ 从网关日志解析 trajectory → build_actions
      ├─ 提取 last_llm_message
      ├─ judge(actions, ir) → score + 文本
      └─ report_to_clawavc(event=end, 完整数据) → DB 更新 + WebSocket
```

### Frontend (`/frontend`)

#### 页面路由

| 路由 | Tab | 文件 | 说明 |
|------|-----|------|------|
| `/monitor` | 监控配置 | `monitor/ConfigTab.vue` | 启停控制 + 数据源路径配置 |
| `/monitor` | 运行日志 | `monitor/LogsTab.vue` | 筛选 + 分页 + 实时卡片流 |
| `/policy` | 翻译与提示词 | `policy/TranslateTab.vue` | 左栏提示词 + 右栏测试 |
| `/policy` | 模型配置 | `policy/ConfigTab.vue` | LLM 参数 (需特权) |
| `/policy` | 策略库 | `policy/RegistryTab.vue` | 场景概览 → 场景详情 |
| `/policy` | 翻译日志 | `policy/LogsTab.vue` | 日志列表 + 筛选 + 详情抽屉 |
| `/policy` | 默认策略 | `policy/DefaultPolicyTab.vue` | JSON 编辑器 |
| `/attack` | — | `AttackPage.vue` | 模拟攻击场景 (色块分组) + 工具注入攻击配置 (固定访问网络/文件路径，独立开关，保存到 config 表) |
| `/database` | — | `DatabasePage.vue` | 可视化表编辑器 + SQL 控制台，顶部有"数据导出"跳转按钮 |
| `/export` | — | `ExportPage.vue` | 选表 → SQL 筛选 → 预览 → 多格式导出 (CSV/Excel/TXT/JSON)，从数据运维页进入 |
| `/replay` | — | `ReplayPage.vue` | 流量回放：选择历史 Round 以 WSS 推送方式回放，支持配置回放速度 |

#### 运行日志卡片结构
```
[Score Badge] [Query + round_id + time_start → time_end] [合规/异常/检测中]
  └─ 展开:
     ├─ Access · 行为轨迹
     │   ├─ 用户态行为 (工具卡片: 工具名 + 参数 + 资源)
     │   └─ 内核态轨迹 (集成中)
     ├─ View · 意图 - IR 策略
     │   └─ 按 policy 分块 (subject → objects 列表)
     └─ Compliance · 合规判定
         ├─ 用户态意图行为一致性检测 (judge_result 多行文本)
         ├─ 内核态行为意图一致性检测 (集成中)
         └─ 多维行为轨迹综合研判 (集成中)
```

#### 监控配置页
- 暗色安全主题控制面板 (盾牌图标 + 脉冲动画)
- 启动前需填写两个路径:
  - 网关日志路径 → 存入 `monitor_conf.gateway_log_path`
  - OpenClaw 根文件夹 → 存入 `monitor_conf.openclaw_root`
- 路径保存后自动检测有效性

#### WebSocket 事件
- `new_round_info` — 前端通过 round_id 做 upsert (已有则更新, 否则插入)
- 筛选激活时只更新已有记录, 不插入新记录

### 数据库配置键 (config 表)

| Key 前缀 | 说明 |
|----------|------|
| `monitor_conf.*` | 监控配置 (openclaw_root, use_gateway, gateway_log_path) |
| `ir_translator.*` | 翻译器配置 (api_base_url, api_key, model, prompt_level1, prompt_level2, registry_path, default_policy, temperature, timeout, json_mode) |
| `attack.inject.*` | 模拟攻击-工具注入配置 (`<item>.enabled` + `<item>.value`，item=network/filepath) |
| `admin_key` | 特权密钥 (admin, 不可 UI 修改) |
| `entry_password` | 入门口令 |
| `admin_ttl_minutes` | 特权会话有效期 (默认20分钟) |



## API 文档系统

### 自动化机制
- `backend/api_docs.py` 中维护 `ENDPOINT_REGISTRY` 字典
- `generate_docs(app)` 自动反射 Flask 路由并合并 registry 元数据
- 未注册的路由自动从函数 docstring 提取 summary
- 新增路由无需手动维护文档，自动出现在 `/api/docs`

### @api_doc 装饰器（可选增强）
```python
@app.route("/api/foo", methods=["GET"])
@api_doc(summary="描述", category="分类", params=[...], response={...}, public=True)
def get_foo():
    ...
```
装饰器仅做增强标记，不影响逻辑。优先级：ENDPOINT_REGISTRY > @api_doc > docstring。

### ENDPOINT_REGISTRY 格式
在 `backend/api_docs.py` 中添加条目即可：
```python
ENDPOINT_REGISTRY = {
    "GET /api/xxx": {
        "summary": "简要描述",
        "description": "详细描述",
        "category": "分类名",  # 数据查询与更新/运行监控/策略翻译/鉴权管理/数据库/配置/文档/其他
        "params": [
            {"name": "参数名", "type": "类型", "default": "默认值", "desc": "说明"},
        ],
        "response": {"ok": True, "data": {}},  # 返回示例
        "public": True,  # 是否对外展示
    },
}
```

### 对外展示配置
- 在 registry 中标记 `"public": True` 的接口会出现在对外文档页
- 也可通过 `PUT /api/docs/public` 动态配置（存入 config 表 `api_docs.public_endpoints`）
- 前端「对外接口」页面 (`/api-docs`) 只展示 public 接口

### 文档 API
| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/docs` | 全部接口文档（内部） |
| `GET` | `/api/docs/public` | 对外公开接口文档 |
| `PUT` | `/api/docs/public` | 配置公开列表（需特权） |


## WebSocket 长连接 (WSS)

### 架构
- Socket.IO path: `/wss`（替代默认的 `/socket.io`）
- 消息组通过 namespace 区分
- 统一事件名 `push`，通过 `push_type` 字段区分消息类型

### 连接方式
```
ws://<host>:15100/wss/<namespace>
```

### 消息组

| Namespace | 名称 | 事件 | 说明 |
|-----------|------|------|------|
| `/wss/monitor` | 运行消息组 | `push` | Agent 行为审计实时推送 |

### 运行消息组 push_type

| push_type | 触发时机 | 关键字段 |
|-----------|----------|----------|
| `round_start` | Round 开始 | round_id, time_start, session_key, push_time |
| `round_ir_ready` | IR 策略翻译完成 | round_id, ir_json, push_time |
| `round_end` | Round 结束（含判定） | round_id, time_start, time_end, action_json, ir_json, overall_score, judge_result, push_time |

> 手动推送和回放的消息会自动设置 `is_mock: true`，客户端可根据此字段区分真实数据和测试数据。

### 客户端接入

**JavaScript:**
```javascript
import { io } from "socket.io-client"

const socket = io("ws://host:15100/wss/monitor", {
  path: "/wss",
  transports: ["websocket"]
})

socket.on("push", (data) => {
  console.log(data.push_type, data.round_id)
})
```

**Python:**
```python
import socketio

sio = socketio.Client()

@sio.on("push", namespace="/wss/monitor")
def on_push(data):
    print(data["push_type"], data["round_id"])

sio.connect("ws://host:15100", socketio_path="/wss", namespaces=["/wss/monitor"], transports=["websocket"])
sio.wait()
```

### 后端 emit 方式
```python
socketio.emit("push", {"push_type": "round_start", "round_id": "...", ...}, namespace="/wss/monitor")
```

### 前端内部 WebSocket（运行日志页）
`frontend/src/utils/socket.js` 连接默认 namespace（无 namespace），监听 `new_round_info` 事件做实时卡片更新。与对外 WSS 接口（/wss/monitor）是不同的 namespace。

## 网关日志格式 (Portkey)

路径: 由 `monitor_conf.gateway_log_path` 配置指向的目录, 文件名为 `YYYY-MM-DD.jsonl`

```json
{
  "time": "5/30/2026, 9:20:17 PM",
  "requestOptions": [{
    "finalUntransformedRequest": {
      "body": { "messages": [...], "tools": [...] }
    },
    "response": { "preview": "LLM回复文本..." },
    "createdAt": "2026-05-30T13:20:11.544Z"
  }]
}
```

提取逻辑:
- user_query: messages 中最后一个 role=user 的 content, 清理 Sender metadata
- last_llm_message: response.preview
- actions: messages 中 assistant 的 tool_calls

## OpenClaw 日志格式

路径: `<openclaw_root>/agents/main/sessions/<uuid>.jsonl`

```json
{"type":"message","id":"177e52b1","parentId":"32923cdd","message":{"role":"user|assistant|toolResult","stopReason":"toolUse|stop|end_turn",...}}
```

round_id = user message 的 `id` 字段
session_key = 从路径推断 `agent:main:main`

## proc_info.py — 进程 & 安全上下文采集

ROUND_START 时由 watcher 调用，**主动定位 OpenClaw 主进程**并枚举它所有活着的工具调用子孙进程，每个带 SELinux/AppArmor 标签 + capabilities + namespaces 等。结果作为 `pid_info` 字段（JSON 字符串）随 start 事件落到 `rounds.pid_info`。

### 设计动机
- OpenClaw 多数 logger 写一行就 flush + close fd，**不能**靠扫 `/proc/*/fd/*` 找写入者
- 真正想要的是**被监控对象**（OpenClaw 主进程）和它启动的工具子进程的安全上下文，**不是** ClawAVC 后端自己的 label

### 主进程定位策略（按优先级）
| Step | 方法 | 说明 |
|------|------|------|
| 0 | `cached` | 上一轮的 `(pid, starttime_ticks)` 仍存活且 starttime 未变 → 直接复用，跳过整次 `/proc` 扫 |
| 1 | `cmdline_match` | 扫 `/proc/*/cmdline` + `/proc/*/comm`，按评分制选最佳候选 |
| 2 | `cwd_boost` | 候选的 cwd 在 `openclaw_root` 之下时 +20 加权 |
| 3 | `fd_writer_fallback` | 兜底：扫 fd 表找 jsonl 写入者（多数 logger 行不通） |

**评分规则**（`_cmdline_match_score`）：
- 100 — `argv[0]` basename **完全等于** hint（如 `openclaw`）
- 95 — `argv[0]` basename 以 `<hint>-` / `<hint>_` 开头（如 `openclaw-gateway`）
- 80 — hint 是 `argv[0]` basename 子串
- 70 — hint 是 `comm` 子串
- 60 — `argv[1:]` 中存在含斜杠的路径，且某个**路径组件**含 hint（如 `/opt/openclaw/main.js`）
- 0  — 不命中

**可配置**：
- `hint_keywords`（默认 `("openclaw",)`）
- `exclude_keywords`（默认 `("clawavc","claw-avc","claw_avc")`）—— 阻止 ClawAVC 自身被误命中
- `comm_blacklist`（默认含 `bash/sh/zsh/fish/dash/ksh/tmux/tmux: server/screen/sudo/su/systemd/init/login/sshd/...`）—— 这些进程**永远不算** OpenClaw，即使它们的 cwd 或 argv 含 'openclaw'

### 单 PID 采集字段（`collect_pid_info`）
| 类别 | 字段 |
|------|------|
| identity | pid, ppid, tgid, comm, cmdline, argv, exe, cwd, root |
| credentials | uid 四元组 (real/eff/saved/fs) + 用户名, gid 四元组 + 组名, groups, **loginuid**, **audit_session_id** |
| resources | state, threads, vm_rss/size/peak/swap_kb, num_fds, `/proc/<pid>/io` |
| capabilities | CapInh / CapPrm / CapEff / CapBnd / CapAmb 全部按位**解码成 41 个 cap 名**（CAP_SYS_ADMIN…）+ 原始 hex |
| sandbox | seccomp 模式 (disabled/strict/filter), no_new_privs |
| **MAC 标签** | `/proc/<pid>/attr/{current,exec,prev,fscreate,keycreate,sockcreate}` —— 同时覆盖 SELinux 与 AppArmor |
| isolation | namespaces (mnt/pid/net/uts/ipc/cgroup/user/time + `_for_children`，每个 ns inode), cgroups 全文, container 自动检测 (docker/k8s/cri-o/podman/containerd/lxc) |
| env | 白名单（PATH/USER/HOME/LANG/CONTAINER 等），避免泄漏密钥 |
| start_time | clock_ticks → epoch → ISO |
| fds | num_fds + 前 20 个 fd 的目标路径采样 |

精简版 `collect_pid_slim(pid)` 只保留 identity + uid + `security_labels` + state，用于 descendants 列表（避免每个工具子进程都拉完整版）。

### 顶层数据结构（`collect_for_round` 返回）
```jsonc
{
  "openclaw_root": "...",
  "jsonl_path": "...",
  "captured_at": "2026-05-31T22:30:00+08:00",
  "discovery": {
    "method": "cached" | "cmdline_match" | "fd_writer_fallback" | "no_match",
    "candidates_count": 1,
    "selected_pid": 1017536,
    "selected_score": 95,
    "selected_reason": "score=95"      // 或 "cwd_boost"
  },
  "main": { /* 完整 collect_pid_info */ },
  "ancestors": [ /* 4 层父链 (slim) */ ],
  "descendants": [
    { "pid": 1660195, "depth": 1, "comm": "python3",
      "cmdline": "python3 /home/.../safe_file_reader/server.py",
      "exe": "/usr/bin/python3", "user": "root",
      "security_labels": { "current": "unconfined_u:..." } }
    /* ... */
  ],
  "main_selinux_label": "unconfined_u:unconfined_r:unconfined_t:s0-s0:c0.c1023",
  "main_exec_label": null,                                 // 主进程下次 exec 时的目标 label
  "tool_subprocess_labels": [
    { "pid": 1660195, "comm": "python3",
      "cmdline": "...", "label": "unconfined_u:..." }
    /* … 顶层 shortcut，方便前端按工具 PID 直接列展 */
  ],
  "fallback_writers": [ /* 仅在 method=fd_writer_fallback 时有 */ ],
  "system": {
    "selinux": { "mode": "permissive|enforcing|disabled", "policyvers": "33", "mls": "1" },
    "apparmor": { "enabled": false },
    "kernel": "Linux version 5.14.0-...",
    "hostname": "..."
    // 注意：故意不包含 clawavc 后端自身的 label —— 我们只关心被监控目标
  },
  "collect_duration_ms": 43
}
```

### Watcher 集成
```python
# auditor/monitor/watcher.py
from .proc_info import collect_for_round

class MonitorOrchestrator:
    def __init__(self, ...):
        self._main_pid_cache = None  # (pid, starttime_ticks)

    def _on_round_start(self, r: RoundLedger):
        ...
        pid_info_data = collect_for_round(
            openclaw_root=str(self.openclaw_log_root),
            jsonl_path=r.source_file or "",
            cached_main=self._main_pid_cache,
        )
        main = pid_info_data.get("main") or {}
        if main.get("pid") and (main.get("start_time") or {}).get("clock_ticks"):
            self._main_pid_cache = (main["pid"], main["start_time"]["clock_ticks"])
        report_to_clawavc({"event": "start", ..., "pid_info": json.dumps(pid_info_data, default=str)})
```

`POST /api/rounds`（event=start）的 body 接受 `pid_info` 字符串字段，`db.insert_round_start` 直接写到 `rounds.pid_info`。

### 性能与可靠性
- 单次采集典型 40–80 ms（root 权限 + 标准服务器规模 /proc）
- 任何采集失败被 watcher 捕获并落 `[monitor] pid_info capture failed: ...` / `[monitor] pid_info note: ...`，**不阻塞** round_start 上报
- 默认排除 watcher 自身 PID，避免临时 fd 干扰
- `_main_pid_cache` 命中时 discovery method = `cached`，整个采集只需要扫**一棵进程树**而非整个 `/proc`

### 独立调试
```bash
cd /home/hx/jjq/clawAVC/backend
uv run python3 auditor/monitor/proc_info.py --openclaw-root /root/.openclaw \
  --hint openclaw --ancestors 4 --descendants-depth 6 --descendants-max 64
```
直接打印 JSON 结果，可用于排查"为什么这台机器上 OpenClaw 没被定位到"。

### 安全约束
- **不**采集任意进程的环境变量原文（只白名单），避免 token / API key 通过 `pid_info` 落到 DB
- **不**采集 ClawAVC 后端自身的 SELinux label（即旧 `clawavc_self_label` 已删除）
- 所有读取均 best-effort：FileNotFoundError / PermissionError 都被静默吞掉，不影响整体快照

## 评分机制

- `overall_score > 0.5` → 合规 (绿色)
- `overall_score <= 0.5` → 异常 (橙色)
- `overall_score == -1` → 检测中 (灰色, 脉冲动画)
- `ir_json == "__loading__"` → IR 翻译中 (显示 loading)

## 权限体系

| 层级 | 验证方式 | 有效期 | 能力 |
|------|----------|--------|------|
| 入门 | 口令 (可配置) | 持久 (localStorage) | 所有页面访问 + 查询 |
| 特权 | 密钥 admin (不可改) | 20分钟 (sessionStorage) | 配置修改 + DB 写操作 |

## 安全约束

- 特权密钥 `admin` 不可通过 UI 修改
- 入门口令不可在前端代码中明文暴露
- 不修改原始 `/home/hx/jjq/auditor/` 下的文件
- 不修改 `judge()` 函数本身 (helpers 可改)

## 构建验证

```bash
cd /home/hx/jjq/clawAVC/backend && uv run python3 -c 'import app; print("OK")'
cd /home/hx/jjq/clawAVC/backend && uv run python3 -c 'from auditor.monitor.proc_info import collect_for_round; import json; print(json.dumps(collect_for_round(openclaw_root="/root/.openclaw"), default=str)[:300])'
cd /home/hx/jjq/clawAVC/frontend && npx vite build
```
