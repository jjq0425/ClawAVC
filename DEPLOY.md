# ClawAVC 部署与配置指南

> 面向 AI Agent 的行为合规审计可视化平台 —— **Claw Access-View Compliance**
> 透视访问行为意图 · 校验合规性

本文档在 README 基础上，给出**可直接照做的启动与配置步骤**，涵盖环境准备、依赖安装、服务启动、关键配置项、监控接入与排错。

> 📌 **关于服务器 IP**：本文档统一以 **`8.152.192.7`** 代指实际部署服务器的 IP 地址（前端页面、后端 API、小异模型接入地址等均以此表示）。实际部署时，请将文档（及代码）中出现的 **`8.152.192.7` 全局替换为你的真实服务器 IP**。本地校验命令中的 `127.0.0.1` 表示「在服务器本机执行」，无需替换。

---

## 1. 系统要求

| 组件 | 版本要求 | 说明 |
|------|----------|------|
| Python | ≥ 3.11（推荐 3.14+） | 后端运行时（注意 `pyproject.toml` 声明 `requires-python = ">=3.14"`） |
| Node.js | ≥ 18 | 前端构建/开发服务器 |
| [uv](https://github.com/astral-sh/uv) | latest | Python 包管理器（推荐，替代 pip） |
| 操作系统 | Linux（推荐） | 进程/安全上下文采集依赖 `/proc`，建议在被监控 Agent 同机部署 |
| 被监控目标 | OpenClaw Agent | 标准部署路径 `~/.openclaw` |

> ⚠️ 若使用 `uv`，无需手动建虚拟环境，`uv sync` 会自动创建 `.venv`。
> 仅用 pip 时请自行 `python3 -m venv .venv && source .venv/bin/activate`。

---

## 2. 目录与端口速览

```
clawAVC/
├── backend/      # Flask 后端（端口 15100）
├── frontend/     # Vue3 前端（开发/预览端口 15101）
├── logs/         # 运行日志（backend.log / frontend.log）
├── infos/        # 运行时数据（SQLite 库 infos/db/clawAVC.db）
└── start.sh      # 一键启动脚本
```

| 服务 | 默认地址 | 说明 |
|------|----------|------|
| 前端页面 | `http://8.152.192.7:15101` | 浏览器访问入口 |
| 后端 API | `http://8.152.192.7:15100` | Flask + SocketIO（WebSocket 路径 `/wss`） |

前端开发服务器（`vite`）已自动将 `/api` 与 `/wss` 反向代理到后端 `15100`，因此**前端与后端必须部署在同一台机器**（或保证 15100 对前端可达）。

---

## 3. 安装依赖

```bash
cd /home/hx/jjq/clawAVC

# ── 后端（uv） ──
cd backend && uv sync && cd ..

# ── 前端 ──
cd frontend && npm install && cd ..
```

依赖清单：
- 后端（`pyproject.toml`）：`flask`、`flask-cors`、`flask-socketio`、`gevent`、`requests`
- 前端（`package.json`）：`vue`、`vite`、`tdesign-vue-next`、`vue-router`、`socket.io-client`

---

## 4. 启动服务

### 4.1 一键启动（推荐）

```bash
# 前台运行（Ctrl+C 停止），默认 dev 模式（vite 开发服务器）
./start.sh

# 后台守护进程模式
./start.sh -d
```

`start.sh` 行为说明：
- 先 `fuser -k 15100/tcp; fuser -k 15101/tcp` 清理旧进程
- 后台模式用 `nohup ... &` 拉起后端与前端的 vite 开发服务器
- 日志写入 `logs/backend.log` 与 `logs/frontend.log`

### 4.2 手动启动（便于调试）

```bash
# 终端 1：后端
cd backend && uv run python3 app.py

# 终端 2：前端（热重载）
cd frontend && npm run dev
```

### 4.3 生产静态构建 + 预览模式

```bash
# 构建静态产物
cd frontend && npx vite build && cd ..

# 用 start.sh 的非 dev 模式（vite preview 服务 dist/）
./start.sh -d --no-dev    # 如脚本支持；否则：
cd frontend && npx vite preview --host 0.0.0.0 --port 15101
```

> 注：当前 `start.sh` 默认 `DEV_MODE=true`。若要纯静态托管，可自行用 `npx vite preview` 或把 `dist/` 交给 Nginx 等反代（需将 `/api`、`/wss` 反代到 15100）。

### 4.4 停止服务

```bash
fuser -k 15100/tcp; fuser -k 15101/tcp
```

---

## 5. 首次访问与鉴权

1. 浏览器打开 `http://8.152.192.7:15101` → 跳转到 `/login`
2. 输入**入门口令**（默认 `secret_key = abc`）
3. 进入平台后，按需访问「运行监控 / 策略翻译 / 安全拦截 / 数据运维」等模块

### 权限模型

| 层级 | 能力 | 凭证 |
|------|------|------|
| 普通层 | 访问所有页面、查询数据、查看实时审计 | 入门口令（`secret_key`） |
| 特权层 | 修改配置、数据库写操作、特权接口（20 分钟有效） | 特权密钥（`admin_key`） |

- 默认 `admin_key = admin`（**不可通过界面修改**，只能改数据库 `config` 表）
- 涉及特权操作时前端弹出 `PrivilegeDialog`，输入 `admin_key` 后获得 20 分钟 `session_token`

> 🔐 **生产环境务必改掉默认口令**：直接改 `infos/db/clawAVC.db` 中 `config` 表的 `secret_key` 与 `admin_key` 值（或后续在「平台管理」页通过特权会话修改 `secret_key`）。

---

## 6. 关键配置项

所有配置最终落在 SQLite `config` 表（`infos/db/clawAVC.db`），多数可通过 UI 或 API 修改。建议通过UI修改。

### 6.1 环境变量（启动前可选）

无特殊环境变量。

### 6.2 IR 翻译器（LLM 模型）配置

监控引擎依赖 IR 翻译将用户意图转为权限策略。配置键前缀 `ir_translator.`：

| 配置键 | 默认值 | 说明 |
|--------|--------|------|
| `ir_translator.api_base_url` | `https://api.longcat.chat/openai` | OpenAI 兼容接口地址 |
| `ir_translator.api_key` | 空 | **必须配置**，否则 IR 翻译报错 |
| `ir_translator.model` | `LongCat-2.0-Preview` | 模型名 |
| `ir_translator.temperature` | `0.0` | 温度 |
| `ir_translator.timeout` | `60` | 请求超时（秒） |

**配置方式（任选其一）：**
- 页面：「策略翻译 → 模型配置」填写并保存（普通访问即可）
- API：`PUT /api/translator/config`（需特权校验）
- 数据库：直接 `UPDATE config SET value='...' WHERE key='ir_translator.api_key'`

> 未配 `api_key` 时，运行日志会出现 `API Key 未配置，请在「策略翻译 → 模型配置」中设置`。

### 6.3 内置监控配置

监控配置键：

| 配置键 | 默认值 | 说明 |
|--------|--------|------|
| `monitor_conf.openclaw_root` | `~/.openclaw` | OpenClaw 根目录（必填） |
| `monitor_conf.use_gateway` | `false` | 是否从 Portkey 网关日志取行为数据 |
| `monitor_conf.gateway_log_path` | 空 | 网关日志路径（use_gateway=true 时必填） |

**配置方式：**
- 页面：「运行监控 → 监控配置」填写 OpenClaw 根目录，选择数据源，点「启动安全监控」
- 接口：`PUT /api/monitor/config` 保存，`POST /api/monitor/start` 启动

### 6.4 小异（二阶段异常判断大模型）配置

「小异」是平台内置的**二阶段异常判断大模型**：既用于「运行监控 → 运行日志」里每轮行为轨迹的自动异常研判（上报后延迟约 5s 在后台触发，结果写入 `rounds.anomaly_llm_v2_judge_res`），也用于「异常分析 · 小异」独立对话页面。配置键前缀 `monitor_conf.`：

| 配置键 | 默认值 | 说明 |
|--------|--------|------|
| `monitor_conf.anomaly_llm_url_v2` | 空 | OpenAI 兼容 `chat/completions` 地址（如 `http://8.152.192.7:8000/v1/chat/completions`）。对话与二阶段异常判断**共用同一地址**；**未配置则不发起任何调用** |
| `monitor_conf.anomaly_llm_max_tokens` | `2048` | 单次输出最大 token 数（前端限制 256–32768） |
| `monitor_conf.anomaly_llm_base_prompt` | 内置默认 | 发起 Round 异常分析时附在多维审计数据之前的指令，可自定义分析视角与输出要求；留空用默认 |
| `monitor_conf.anomaly_llm_system_prompt` | 内置默认 | 小异的人设与回答规范（系统提示词），作用于所有对话与异常分析；留空用默认 |

**配置方式（任选其一）：**
- 页面：「异常分析 · 小异 → 小异设置」填写请求地址、最大 token、分析指令、系统提示后保存（普通访问即可）
- 接口：通过监控配置 `PUT /api/monitor/config` 批量保存以上键（需特权）
- 数据库：直接 `UPDATE config SET value='...' WHERE key='monitor_conf.anomaly_llm_url_v2'`

> ⚠️ 未配置 `anomaly_llm_url_v2` 时，「问问小异」与运行日志的二阶段研判均不可用，相关接口返回 `<未配置>` 提示；这**不影响**一阶段 `judge` 的综合得分与是否异常判定（见 6.2 / Q2）。
>
> 与 6.2 的 IR 翻译器不同，小异**只需配置 URL 即可**（无独立 api_key 配置项），鉴权依赖所指向模型服务自身。

---

## 7. 启用内置监控（核心使用流程）

ClawAVC 自带轻量监控引擎，可独立于外部 orchestrator 完成审计。

### 步骤

1. 进入「运行监控 → 监控配置」
2. 填写 **OpenClaw 根文件夹** 路径（默认 `~/.openclaw`，必填）
3. 选择**交互数据来源**：
   - 默认「从 OpenClaw 日志获取」—— 零额外依赖，直接从 agent session 日志解析 actions
   - 「从网关获取」—— 额外填写 Portkey 网关日志路径
4. 点击「启动安全监控」
5. 切换到「运行日志」tab，查看实时卡片流

### 数据流

```
~/.openclaw 日志 ──→ watcher 检测 ROUND_START/END
        │
        ├─ proc_info：定位 OpenClaw 主进程 + 子进程安全上下文 → pid_info
        ├─ ir_client：调用 LLM 翻译用户意图 → IR 策略
        └─ judge：比对 action vs IR → 综合得分 + 是否异常
                │
                └─ POST /api/rounds → SQLite + WebSocket → 前端实时卡片
```


---

## 8. 安全拦截（portkey 网关，可选）

若需实时拦截 IR 白名单外工具调用，配置以下项（需特权）：

| 配置键 | 说明 |
|--------|------|
| `intercept_non_ir_tools` | 拦截 IR 外工具开关 |
| `loop_breaker` | 死循环熔断配置 |
| `turn_ir_wait_ms` | IR 长轮询超时（毫秒） |

网关侧需将工具调用转发到 ClawAVC 的 `/api/translator/turn-ir` 获取 `allowed_tools` 白名单，并把拦截事件上报到 `/api/intercept/events`。拦截事件在「安全拦截」页面实时展示。

---

## 9. 验证部署

```bash
# 1. 后端健康（应返回 JSON）
curl http://127.0.0.1:15100/api/stats

# 2. 前端页面可访问
curl -sI http://127.0.0.1:15101 | head -1

# 3. 查看后端日志
tail -f logs/backend.log

# 4. 查看前端日志（后台模式）
tail -f logs/frontend.log
```

正常启动应看到：
- 后端日志首行 `[clawAVC] Starting backend on http://0.0.0.0:15100`
- `[monitor] Starting monitor...` 及 `[monitor] OpenClaw logs: ...`
- 前端日志出现 `VITE ready` / `Local: http://0.0.0.0:15101`

---

## 10. 常见问题排查

### Q1：启动报 `ModuleNotFoundError: No module named 'shell_command_semantics'`
`backend/auditor/monitor/judge.py` 必须使用**相对导入**：
```python
from .shell_command_semantics import analyze_shell_command
```
（已修复。若仍报错，确认 `shell_command_semantics.py` 与 `judge.py` 同目录 `backend/auditor/monitor/`）

### Q2：监控启动了但「运行日志」不显示分数 / 不显示是否异常
- 确认 IR 翻译器已配 `api_key`（否则 judge 拿不到 IR，日志出现 `No IR data ... skipping judge`）
- judge 在 round 结束后**异步**执行（延迟约 1.5s 等待 IR），稍候刷新
- 分数来自后端 `overall_score` 字段，经 WebSocket `new_round_info` 推送，确认前端与后端 15100 连通

### Q3：前端页面空白 / 接口 401
- 入门口令错误或未登录（`secret_key` 默认 `abc`）
- 反向代理未转发 `/api` 与 `/wss`（同机部署可避免）

### Q4：IR 翻译失败
- 检查 `ir_translator.api_base_url` / `api_key` / `model` 是否正确
- 查看后端日志 `ir_translate` 相关报错

### Q5：特权操作 403
- 输入正确的 `admin_key`（默认 `admin`）
- 会话 20 分钟过期后需重新验证

---

## 11. 生产部署建议

1. **改默认口令**：上线前修改 `secret_key` 与 `admin_key`
2. **反向代理**：用 Nginx/Caddy 统一暴露 15101，并将 `/api`、`/wss` 反代到 15100（支持 HTTPS/WSS）
3. **静态托管**：`npx vite build` 后用 `vite preview` 或 Nginx 托管 `dist/`，减轻开发服务器开销
4. **进程守护**：用 `systemd` / `supervisor` 管理 `start.sh -d` 进程，或分别守护后端与前端的守护进程
5. **数据库备份**：定期备份 `infos/db/clawAVC.db`
6. **同机部署**：监控引擎需读取 `/proc` 定位 OpenClaw 进程，建议与被监控 Agent 同机

### systemd 示例（后端）

```ini
# /etc/systemd/system/clawavc-backend.service
[Unit]
Description=ClawAVC Backend
After=network.target

[Service]
WorkingDirectory=/home/hx/jjq/clawAVC/backend
ExecStart=/home/hx/jjq/clawAVC/backend/.venv/bin/python3 app.py
Restart=always
Environment=ADMIN_SESSION_TTL=1200

[Install]
WantedBy=multi-user.target
```

---

## 12. 目录结构与关键文件

```
backend/
├── app.py                      # Flask 主应用 + SocketIO + 全部 API（端口 15100）
├── db.py                       # SQLite 数据层（rounds/config/translation_logs/intercept_events）
├── api_docs.py                 # 自动化 API 文档
└── auditor/
    ├── translator/
    │   ├── core.py             # IR 翻译核心（LLM / 提示词 / 验证 / 归一化）
    │   └── policy_registry/    # 策略注册表 scenes.json + tools/*.json
    └── monitor/
        ├── watcher.py          # OpenClaw 日志监听 + 调度
        ├── ir_client.py        # 调用翻译接口获取 IR
        ├── judge.py            # 用户态行为合规判定引擎
        ├── proc_info.py        # 进程/安全上下文采集
        ├── shell_command_semantics.py  # shell 命令语义分析
        └── resource_consistency_check.py  # 资源一致性检查

frontend/
├── src/views/monitor/          # 运行监控（ConfigTab 配置 / LogsTab 运行日志）
├── src/utils/socket.js         # WebSocket 连接
└── vite.config.js              # 端口 15101 + 代理到 15100
```

---

## 13. 常用接口速查

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/auth` | 验证入门口令 |
| `POST` | `/api/admin/verify` | 验证特权密钥 |
| `GET` | `/api/rounds` | 分页+筛选查询 round |
| `GET` | `/api/stats` | 统计概览 |
| `GET` | `/api/monitor/config` | 获取监控配置 |
| `PUT` | `/api/monitor/config` | 保存监控配置 |
| `POST` | `/api/monitor/start` | 启动监控 |
| `POST` | `/api/monitor/stop` | 停止监控 |
| `GET/PUT` | `/api/translator/config` | LLM 模型配置（特权） |
| `POST` | `/api/translator/test` | 翻译测试 |
| `GET` | `/api/translator/registry` | 策略库全量 |
| `GET` | `/api/docs` | 全部接口文档 |
| `ANY` | `/api/webhook` | Webhook 接收（公开） |

完整 API 见平台内 `/api-docs` 页面或 README「API 文档」章节。

---

*部署完成后，你的 Agent 跑得再快，ClawAVC 也接得住 🫴*
