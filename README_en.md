<div align="center">

<img src="frontend/public/logo-long.png" alt="ClawAVC" width="280" />

# ClawAVC

[中文](./README.md) | **English**

**Claw Access-View Compliance**

*Perceive Access Behavior Intent · Validate Compliance*

> ClawAVC's mission is to catch 🫴 OpenClaw securely — you fly free, we've got your back.

[![Python](https://img.shields.io/badge/Python-3.14+-blue.svg)](https://python.org)
[![Vue](https://img.shields.io/badge/Vue-3.4+-42b883.svg)](https://vuejs.org)
[![TDesign](https://img.shields.io/badge/TDesign-Vue_Next-0052D9.svg)](https://tdesign.tencent.com)
[![License](https://img.shields.io/badge/License-Internal-orange.svg)]()

---

**Behavioral Compliance Audit & Visualization Platform for AI Agents**

Real-time Monitoring · Multi-dimensional Detection · Intent Comparison · Anomaly Alerting

*Let your Agent run wild — ClawAVC keeps the compliance books crystal clear* 🧮

</div>

---

## Table of Contents

- [Background](#background)
- [System Architecture](#system-architecture)
- [Core Capabilities](#core-capabilities)
- [Detection Engine](#detection-engine)
- [Quick Deployment](#quick-deployment)
- [Page Modules](#page-modules)
- [Permission System](#permission-system)
- [API Documentation](#api-documentation)
- [Tech Stack](#tech-stack)
- [Directory Structure](#directory-structure)
- [Development Guide](#development-guide)
- [Team](#team)

---

## Background

As AI Agents become widely deployed in production environments, they gain high-privilege capabilities such as tool invocation, file access, and command execution. Ensuring that an Agent's actual behavior aligns with user intent — preventing unauthorized access, parameter tampering, path traversal, and other security risks — has become a critical challenge.

**ClawAVC** was built to address this. The system name derives from three core concepts:

| Letter | Meaning | Responsibility |
|--------|---------|----------------|
| **A** | Access (Behavior) | Capture Agent's tool calls, file accesses, and command executions |
| **V** | View (Intent Perception) | Translate user natural language intent into standardized permission policies (IR) |
| **C** | Compliance (Validation) | Multi-dimensional comparison of behavior vs. intent, outputting compliance verdicts |

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        ClawAVC Platform                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────┐    HTTP POST     ┌──────────────────────────┐  │
│  │ Orchestrator │ ──────────────→ │     Backend (Flask)       │  │
│  │ (Agent Audit)│    /api/rounds   │                          │  │
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
│                                    │  ┌───────┐ ┌───────┐   │   │
│                                    │  │Monitor│ │Manage │...│   │
│                                    │  └───────┘ └───────┘   │   │
│                                    └─────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
User sends a request
    ↓
Agent performs tool calls (produces actions)
    ↓
IR Translator converts user intent into permission policies (produces IR)
    ↓
Judge Engine performs multi-dimensional comparison: action vs IR
    ↓
Orchestrator POSTs the complete round data to ClawAVC Backend
    ↓
Backend persists to SQLite + pushes via WebSocket to frontend
    ↓
Frontend renders audit cards in real-time
```

---

## Core Capabilities

### Real-time Auditing

Each Agent interaction round is pushed to the platform immediately upon completion, presenting compliance verdicts with zero delay. Bidirectional WebSocket communication ensures data freshness.

### Multi-dimensional Detection

Comprehensively evaluates Agent behavioral compliance across three dimensions: tool invocation, parameter matching, and resource access, with quantified composite scoring.

### Intent Perception

A two-stage IR translation pipeline powered by LLM transforms user natural language requests into structured `subject/objects` permission policies, precisely describing allowed tools, parameters, and resource scopes.

### Visual Auditing

Card-based design with grouped display of Access (behavior traces), View (intent policies), and Compliance (verdicts), supporting collapse/expand for clear overview.

---

## Detection Engine

### Three-Dimensional Consistency Model

| Dimension | Detection Target | Violation Example |
|-----------|-----------------|-------------------|
| **Tool Call Consistency** | Whether the Agent's called tools are within IR-allowed scope | IR allows `read`, Agent called `exec` |
| **Parameter Consistency** | Whether tool call parameter key-values match IR constraints | IR allows `path=/tmp/a.txt`, Agent passed `path=/etc/passwd` |
| **Resource Access Consistency** | Whether file paths and operation types are within allowed range | IR allows `read /tmp/**`, Agent executed `write /etc/cron.d/x` |

### Scoring Mechanism

```
overall_score = mean(score per dimension)    // only dimensions with events are counted
score = matched_count / total_count          // each dimension calculated independently
```

| Threshold | Verdict | Meaning |
|-----------|---------|---------|
| `> 0.5` | ✅ Compliant | Behavior is generally consistent with intent |
| `≤ 0.5` | ⚠️ Anomalous | Significant privilege escalation or deviation detected |

### Detection Pipeline (Integrated / Planned)

| Layer | Status | Description |
|-------|--------|-------------|
| User-space Intent-Behavior Consistency | ✅ Integrated | Rule-matching engine based on IR policies |
| Kernel-space Behavior-Intent Consistency | 🔄 In Progress | Deep detection based on syscall traces |
| Multi-dimensional Behavior Trace Analysis | 🔄 In Progress | Combined user-space + kernel-space LLM reasoning |

---

## Quick Deployment

### Prerequisites

- Python ≥ 3.11 (3.14+ recommended)
- Node.js ≥ 18
- [uv](https://github.com/astral-sh/uv) (Python package manager)

### Install Dependencies

```bash
cd /home/hx/jjq/clawAVC

# Backend
cd backend && uv sync && cd ..

# Frontend
cd frontend && npm install && cd ..
```

### Start Services

```bash
# Foreground (Ctrl+C to stop)
./start.sh

# Background (daemon mode)
./start.sh -d
```

### Stop Services

```bash
fuser -k 15100/tcp; fuser -k 15101/tcp
```

### Access

| Service | URL |
|---------|-----|
| Frontend | `http://<host>:15101` |
| Backend API | `http://<host>:15100` |

First-time access requires an entry passphrase (configured by privileged users).

---

## Built-in Monitoring

ClawAVC includes a lightweight monitoring engine that can perform audits independently without an external orchestrator.

### How It Works

```
             ┌──────────────────────────────┐
             │  watcher.py (background thread)│
             │                              │
  ~/.openclaw│──→ Detect ROUND_START/END     │
  (log files)│                              │
             │   ┌─────────────────────┐    │
  Gateway    │──→│ Parse query + actions│    │
  logs       │   └────────┬────────────┘    │
  (Portkey)  │            │                 │
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
                    │  SQLite DB  │──→ WebSocket ──→ Frontend
                    └─────────────┘
```

### Usage

1. Navigate to "Runtime Monitor → Monitor Config" page
2. Enter the **OpenClaw root folder** path (required)
3. Select **interaction data source**:
   - Default: "From OpenClaw logs" — no extra config needed, parses actions (including tool results) directly from agent session logs
   - Optional: "From Gateway" — requires additional Portkey gateway log path
4. Click "Start Security Monitor"
5. Switch to the "Runtime Logs" tab to view real-time data

> 💡 The monitor creates a card immediately when the Agent sends a message ("Detecting" state),
> then asynchronously requests IR translation, and finally completes the judge and updates the score when the round ends.
> The entire process is fully asynchronous and does not block Agent operation.
>
> 📦 Default mode parses directly from OpenClaw logs (zero extra dependencies). Also supports Portkey gateway for richer trajectory data.

---

## Attack Simulation

The Attack Simulation module reproduces typical Agent attack vectors in an isolated environment to validate the defensive capability of the ClawAVC detection engine. The page groups attack types into color blocks, with one attack configuration module under each type.

### Threat Scenarios

| Scenario | Severity | Target | Description |
|----------|----------|--------|-------------|
| **Runtime Tampering** | HIGH | Tool Dispatch layer | Tampers the Agent's runtime tool mapping — requesting tool A while actually executing tool B (attack config planned) |
| **Tool Injection** | CRITICAL | Tools Manifest registry | Injects a disguised malicious tool into the available tool list, luring the LLM to call it naturally |

### Tool Injection Attack Config

The "Tool Injection" scenario supports configurable attacks. Each item can be enabled/disabled independently; once enabled you fill in the attack content (the target file path or network is not validated for existence). Config is persisted to the `config` table with the `attack.inject.*` key prefix.

| Config key | Description | Example content |
|------------|-------------|-----------------|
| `tool_injection.network` | Fixed network access — forces the injected tool to connect to a given address when called | `http://malicious.example.com/collect` |
| `tool_injection.filepath` | Fixed file path access — forces the injected tool to read a given file when called | `/root/.ssh/id_rsa` |

Each config item is stored as two records in the `config` table: `attack.inject.<item>.enabled` (`true`/`false`) and `attack.inject.<item>.value` (attack content).

### Public Endpoint

External systems can query the enabled state and content of a specific tool config via `key` (the config key above):

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

> When `key` is omitted, all tool injection config is returned; an unknown key returns `404`. This endpoint is marked public and can be viewed and tested directly on the `/api-docs` page.

---

## Page Modules

| Route | Module | Description | Permission |
|-------|--------|-------------|------------|
| `/login` | Entry Auth | Enter passphrase to verify access | Public |
| `/` | Home | System intro, detection dimensions, anomaly threshold visualization | Entry passphrase |
| `/monitor` | Runtime Monitor | Monitor config + real-time audit card stream (filter/pagination/WebSocket push) | Entry passphrase |
| `/attack` | Attack Simulation | Preset malicious scenarios to validate detection capabilities (in beta) | Entry passphrase |
| `/database` | Database Operations | Visual table editor + SQL console + data export entry | Read: passphrase / Write: privileged |
| `/export` | Data Export | SQL filtering + multi-format export (CSV/Excel/TXT/JSON), accessed from Database Operations | Entry passphrase |
| `/settings` | Platform Settings | Session management, passphrase configuration | Privileged items require privilege key |

### Runtime Monitor Detail Structure

```
┌─ Access · Behavior Traces ──────────────────────┐
│  ├─ User-space behavior (tools/params/resources) │
│  └─ Kernel-space traces (in progress)            │
├─ View · Intent - IR Policy ─────────────────────┤
│  └─ subject/objects policy tree                  │
├─ Compliance · Verdict ──────────────────────────┤
│  ├─ User-space intent-behavior consistency       │
│  ├─ Kernel-space behavior-intent consistency     │
│  │   (in progress)                               │
│  └─ Multi-dimensional trace analysis             │
│      (in progress)                               │
└──────────────────────────────────────────────────┘
```

---

## Permission System

### Two-Layer Permission Model

```
┌─────────────────────────────────────────┐
│  Privileged Layer                        │
│  - Modify entry passphrase               │
│  - Database write operations             │
│    (INSERT/UPDATE/DELETE)                 │
│  - Access config table                   │
│  - 20-minute session TTL (configurable)  │
├─────────────────────────────────────────┤
│  Normal Layer                            │
│  - Access all pages                      │
│  - Query data (SELECT)                   │
│  - View real-time audit data             │
│  - Persistent session (sessionStorage)   │
└─────────────────────────────────────────┘
```

### Privilege Verification Flow

1. User clicks an area requiring privilege → `PrivilegeDialog` modal appears
2. Enter privilege key → Backend verifies → Generates `session_token`
3. Token stored in `sessionStorage`, no re-verification needed within 20 minutes
4. `PrivilegeStatus` component displays remaining countdown in real-time
5. Token automatically expires, re-verification required

> ⚠️ The privilege key cannot be modified via the UI — only through direct database operations.

---

## API Documentation

### Authentication

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/auth` | Verify entry passphrase |
| `POST` | `/api/admin/verify` | Verify privilege key, returns session_token |
| `GET` | `/api/admin/session` | Check privilege session validity |

### Data

| Method | Path | Description | Permission |
|--------|------|-------------|------------|
| `GET` | `/api/rounds?limit=20&offset=0&query=&round_id=&time_from=&time_to=` | Paginated + filtered query | Normal |
| `GET` | `/api/rounds/:id` | Single round details | Normal |
| `POST` | `/api/rounds` | Report round (event=start/end) | Internal |
| `GET` | `/api/stats` | Statistics overview | Normal |

### Monitoring

| Method | Path | Description | Permission |
|--------|------|-------------|------------|
| `GET` | `/api/monitor/config` | Get monitor configuration | Normal |
| `PUT` | `/api/monitor/config` | Save configuration | Normal |
| `GET` | `/api/monitor/status` | Monitor running status | Normal |
| `POST` | `/api/monitor/start` | Start monitoring | Normal |
| `POST` | `/api/monitor/stop` | Stop monitoring | Normal |

### Translator

| Method | Path | Description | Permission |
|--------|------|-------------|------------|
| `POST` | `/api/translator/translate` | IR translation (internal) | Internal |
| `POST` | `/api/translator/test` | Translation test (UI) | Normal |
| `GET/PUT` | `/api/translator/config` | LLM model configuration | Privileged |
| `GET/PUT` | `/api/translator/prompts` | Prompt management | Normal |
| `GET` | `/api/translator/registry` | Full policy registry | Normal |
| `GET/PUT` | `/api/translator/scene/<name>` | Scene CRUD | View: Normal / Modify: Privileged |

### Database

| Method | Path | Description | Permission |
|--------|------|-------------|------------|
| `GET` | `/api/db/tables` | List all tables | Normal |
| `POST` | `/api/db/query` | Execute SQL | SELECT: Normal / Write: Privileged |

### Configuration

| Method | Path | Description | Permission |
|--------|------|-------------|------------|
| `GET` | `/api/config` | Get public configuration | Normal |
| `PUT` | `/api/config` | Update configuration | Privileged |

### Attack Simulation

| Method | Path | Description | Permission |
|--------|------|-------------|------------|
| `GET` | `/api/attack/config` | Get tool injection attack config (internal page load) | Normal |
| `PUT` | `/api/attack/config` | Save tool injection attack config (incl. enabled state & content) | Normal |
| `GET` | `/api/attack/tool-config?key=tool_injection.network` | Public endpoint: query enabled state & content by config key | Public |

### WebSocket

| Event | Direction | Payload | Description |
|-------|-----------|---------|-------------|
| `new_round` | Server → Client | Round object | Real-time push for new rounds |
| `connect` | Client → Server | - | Establish connection |

---

## WebSocket Long Connection

ClawAVC provides a Socket.IO-based WebSocket push service, subscribed by message groups.

### Connection URL

```
ws://<host>:15100/wss/<namespace>
```

| Message Group | Namespace | Description |
|---------------|-----------|-------------|
| Runtime Messages | `/wss/monitor` | Real-time Agent behavior audit push |

### Unified Events

All messages are pushed via the `push` event, differentiated by the `push_type` field:

| push_type | Description | Trigger |
|-----------|-------------|---------|
| `round_start` | Round started | Agent begins a new interaction round |
| `round_ir_ready` | IR policy ready | Intent translation completed |
| `round_end` | Round ended | Complete verdict result |

### Integration Examples

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

## API Documentation System

ClawAVC features automated API documentation generation — **zero manual maintenance**.

### How It Works

```
Flask route definitions (@app.route)
        │
        ▼
generate_docs() auto-reflection scan
        │
        ├── ENDPOINT_REGISTRY (detailed metadata)
        ├── @api_doc() decorator (optional enhancement)
        └── Function docstring (fallback)
        │
        ▼
GET /api/docs        ← All endpoint docs
GET /api/docs/public ← Public-facing endpoints
```

### Public API Page

Visit `/api-docs` to view all public-facing API documentation, including:
- Collapsible category grouping
- Complete parameter tables (type, default value, description)
- Response JSON examples
- **Right-side API test panel**: Send requests directly to test endpoints

### Adding New API Docs

Add an entry to `ENDPOINT_REGISTRY` in `backend/api_docs.py` and docs take effect automatically:

```python
"POST /api/new-endpoint": {
    "summary": "Endpoint description",
    "category": "Category",
    "params": [{"name": "key", "type": "string", "desc": "Description"}],
    "response": {"ok": True},
    "public": True,  # Set True to expose publicly
}
```

---

## Tech Stack

### Backend

| Component | Version | Purpose |
|-----------|---------|---------|
| Python | 3.14+ | Runtime |
| Flask | 3.1+ | Web framework |
| Flask-SocketIO | 5.6+ | WebSocket support |
| Flask-CORS | 6.0+ | CORS handling |
| gevent | 26+ | Async worker |
| SQLite | 3.34+ | Persistent storage |
| uv | latest | Package manager |

### Frontend

| Component | Version | Purpose |
|-----------|---------|---------|
| Vue | 3.4+ | UI framework |
| Vite | 5.4+ | Build tool |
| TDesign Vue Next | 1.9+ | UI component library |
| vue-router | 4.x | Route management |
| socket.io-client | 4.7+ | WebSocket client |

### Design Specifications

| Property | Value | Purpose |
|----------|-------|---------|
| Primary Color | `#0052D9` | Tencent Blue, brand color |
| Anomaly Color | `#ED7B2F` | Orange, risk alerts |
| Normal Color | `#00a870` | Green, compliance pass |
| Background | `#f5f7fa` | Light gray base |
| Cards | White / border-radius 12-14px | Content containers |
| Font | PingFang SC / Microsoft YaHei | CJK-first typography |

---

## Directory Structure

```
clawAVC/
├── backend/
│   ├── app.py                 # Flask main app + SocketIO + all APIs
│   ├── db.py                  # SQLite data layer (rounds/config tables)
│   ├── auditor/
│   │   ├── translator/        # IR Translator (Level-1 scene classification + Level-2 policy generation)
│   │   │   ├── core.py
│   │   │   └── policy_registry/  # Policy registry (scenes.json + tools/*.json)
│   │   └── monitor/           # Built-in monitoring module
│   │       ├── watcher.py     # OpenClaw log watcher + gateway parser + scheduler
│   │       ├── ir_client.py   # Calls translation API for IR
│   │       └── judge.py       # User-space behavioral compliance judge engine
│   ├── pyproject.toml         # uv dependency declarations
│   ├── requirements.txt       # pip-compatible dependencies
│   └── .venv/                 # Python virtual environment (git ignored)
│
├── frontend/
│   ├── src/
│   │   ├── main.js            # Entry point
│   │   ├── App.vue            # Root component (sidebar + router-view)
│   │   ├── router/
│   │   │   └── index.js       # Route definitions + auth guard
│   │   ├── views/
│   │   │   ├── LoginPage.vue      # Entry authentication
│   │   │   ├── HomePage.vue       # Home page
│   │   │   ├── MonitorPage.vue    # Runtime Monitor (Tab container)
│   │   │   ├── monitor/
│   │   │   │   ├── ConfigTab.vue  # Monitor config (start/stop + data source paths)
│   │   │   │   └── LogsTab.vue   # Runtime logs (filter + pagination + card stream)
│   │   │   ├── PolicyPage.vue     # Policy Translation (Tab container)
│   │   │   ├── policy/
│   │   │   │   ├── TranslateTab.vue   # Translation & prompts
│   │   │   │   ├── ConfigTab.vue      # Model configuration
│   │   │   │   ├── RegistryTab.vue    # Policy registry management
│   │   │   │   ├── LogsTab.vue        # Translation logs
│   │   │   │   └── DefaultPolicyTab.vue # Default policy
│   │   │   ├── AttackPage.vue     # Attack Simulation
│   │   │   ├── DatabasePage.vue   # Database Operations
│   │   │   ├── ExportPage.vue     # Data Export
│   │   │   └── SettingsPage.vue   # Platform Settings
│   │   ├── components/
│   │   │   ├── PrivilegeDialog.vue    # Privilege verification modal (shared)
│   │   │   ├── PrivilegeStatus.vue    # Privilege status indicator (shared)
│   │   │   └── RowDetailDrawer.vue    # Row detail drawer (Database Operations)
│   │   └── utils/
│   │       └── socket.js          # WebSocket connection management
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
│
├── logs/                      # Runtime logs (git ignored)
├── .claude/CLAUDE.md          # Project development docs
├── .gitignore
├── start.sh                   # One-click startup script
└── README.md
```

---

## Development Guide

### Local Development

```bash
# Start Backend (hot reload)
cd backend
uv run python3 app.py

# Start Frontend (HMR)
cd frontend
npm run dev
```

The frontend dev server automatically proxies `/api` and `/socket.io` to the backend on port 15100.

### Adding a New Page

1. Create `XxxPage.vue` in `frontend/src/views/`
2. Add route in `frontend/src/router/index.js`
3. Add navigation item in `navItems` in `frontend/src/App.vue`
4. Build verification: `cd frontend && npx vite build`

### Adding a New API

1. Add Flask route in `backend/app.py`
2. If persistence is needed, add corresponding functions in `backend/db.py`
3. Privileged operations must check `_check_admin_session(token)`

### Database Migration

The SQLite database file is `backend/clawAVC.db`. Table schemas are defined in `init_db()` and `init_config_table()` in `db.py`. Adding new tables only requires adding `CREATE TABLE IF NOT EXISTS` statements without affecting existing data.

---

## Team

| Member | Role |
|--------|------|
| [@jjq0425](https://github.com/jjq0425) | Lead Developer |
| [@xiaoxuan668](https://github.com/xiaoxuan668) | Lead Developer |

Special thanks to Claude Code, Codex, Hy3, Mimo, Longcat, Doubao, Qwen, DeepSeek, and StepFun for their coding support (in no particular order).

---

<div align="center">

*Built with purpose. Secured by design.*

*ClawAVC: No matter how fast your Agent runs, we'll catch it* 🫴✨

*— Claw it, comply with it*

</div>
