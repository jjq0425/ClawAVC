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
- [页面模块](#页面模块)
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

---

## 页面模块

| 路由 | 模块 | 说明 | 权限 |
|------|------|------|------|
| `/login` | 入口鉴权 | 输入入门口令验证访问权限 | 公开 |
| `/` | 首页 | 系统介绍、检测维度说明、异常阈值可视化 | 入门口令 |
| `/monitor` | 运行监控 | 监控配置 + 实时审计卡片流（筛选/分页/WebSocket实时推送） | 入门口令 |
| `/attack` | 模拟攻击 | 预设恶意场景验证检测能力（灰度中） | 入门口令 |
| `/database` | 数据运维 | 可视化表编辑器 + SQL 控制台 + 数据导出入口 | 查询：入门口令 / 写操作：特权 |
| `/export` | 数据导出 | SQL 筛选 + 多格式导出（CSV/Excel/TXT/JSON），从数据运维页跳转进入 | 入门口令 |
| `/settings` | 平台管理 | 会话管理、入门口令配置 | 特权配置项需特权密钥 |

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
| `GET` | `/api/rounds/:id` | 单条 round 详情 | 普通 |
| `POST` | `/api/rounds` | 上报 round (event=start/end) | 内部调用 |
| `GET` | `/api/stats` | 统计概览 | 普通 |

### 监控

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| `GET` | `/api/monitor/config` | 获取监控配置 | 普通 |
| `PUT` | `/api/monitor/config` | 保存配置 | 普通 |
| `GET` | `/api/monitor/status` | 监控运行状态 | 普通 |
| `POST` | `/api/monitor/start` | 启动监控 | 普通 |
| `POST` | `/api/monitor/stop` | 停止监控 | 普通 |

### 翻译器

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| `POST` | `/api/translator/translate` | IR 翻译 (内部) | 内部 |
| `POST` | `/api/translator/test` | 翻译测试 (UI) | 普通 |
| `GET/PUT` | `/api/translator/config` | LLM 模型配置 | 特权 |
| `GET/PUT` | `/api/translator/prompts` | 提示词管理 | 普通 |
| `GET` | `/api/translator/registry` | 策略库全量 | 普通 |
| `GET/PUT` | `/api/translator/scene/<name>` | 场景 CRUD | 查看普通/修改特权 |

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

### WebSocket

| 事件 | 方向 | Payload | 说明 |
|------|------|---------|------|
| `new_round` | Server → Client | Round 对象 | 新 round 实时推送 |
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

### 统一事件

所有消息通过 `push` 事件推送，`push_type` 字段区分类型：

| push_type | 说明 | 触发时机 |
|-----------|------|----------|
| `round_start` | Round 开始 | Agent 开始新一轮交互 |
| `round_ir_ready` | IR 策略就绪 | 意图翻译完成 |
| `round_end` | Round 结束 | 完整判定结果 |

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
│   ├── db.py                  # SQLite 数据层（rounds/config 表）
│   ├── auditor/
│   │   ├── translator/        # IR 翻译器 (Level-1 场景分类 + Level-2 策略生成)
│   │   │   ├── core.py
│   │   │   └── policy_registry/  # 策略注册表 (scenes.json + tools/*.json)
│   │   └── monitor/           # 内置监控模块
│   │       ├── watcher.py     # OpenClaw日志监听 + 网关解析 + 调度
│   │       ├── ir_client.py   # 调用翻译接口获取 IR
│   │       └── judge.py       # 用户态行为合规判定引擎
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
│   │   │   │   └── DefaultPolicyTab.vue # 默认策略
│   │   │   ├── AttackPage.vue     # 模拟攻击
│   │   │   ├── DatabasePage.vue   # 数据运维
│   │   │   ├── ExportPage.vue     # 数据导出
│   │   │   └── SettingsPage.vue   # 平台管理
│   │   ├── components/
│   │   │   ├── PrivilegeDialog.vue    # 特权验证弹窗（通用）
│   │   │   ├── PrivilegeStatus.vue    # 特权状态指示器（通用）
│   │   │   └── RowDetailDrawer.vue    # 行详情抽屉（数据运维）
│   │   └── utils/
│   │       └── socket.js          # WebSocket 连接管理
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
│
├── logs/                      # 运行日志（git ignored）
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

### 数据库迁移

SQLite 数据库文件为 `backend/clawAVC.db`，表结构在 `db.py` 的 `init_db()` 和 `init_config_table()` 中定义。新增表只需添加 `CREATE TABLE IF NOT EXISTS` 语句，不影响已有数据。

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
