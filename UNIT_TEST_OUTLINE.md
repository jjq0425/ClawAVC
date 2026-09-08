# ClawAVC 单元测试大纲

> 项目：ClawAVC（Claw Access-View Compliance）
> 阶段：第三阶段 —— clawAVC 模块单元测试落地
> 范围：`/home/hx/jjq/clawAVC/backend`（主体） + `frontend`（附属）
> 基线：README.md / .claude/CLAUDE.md + 代码实测（backend 共 13208 行 Python，16 个 .py 文件）

---

## 0. 结论摘要

| 项 | 内容 |
|---|---|
| 被测代码规模 | backend 13208 行 / 16 文件；核心可测面集中在 `judge.py`、`resource_consistency_check.py`、`shell_command_semantics.py`、`db.py`、`app.py`、`proc_info.py`、`watcher.py`、`policy_manager.py` |
| 现状 | **仓库内零测试代码**（无 `tests/`、无 pytest 依赖、`pyproject.toml` 无 dev 依赖组） |
| 用例总量（规划） | 约 **520** 条，其中 P0 约 210 条、P1 约 200 条、P2 约 110 条 |
| 首要攻坚点 | 纯函数密集的**合规判定引擎**（judge / RCC / shell 语义）—— 零外部依赖、收益最高，作为 P0 起点 |
| 最大技术障碍 | `app.py` 顶部 `gevent monkey.patch_all()`；`db.DB_PATH` / `core.SCENE_REGISTRY` 为**模块级常量**（import 时固化）；`proc_info` 直读 `/proc` |
| 覆盖率目标 | 判定引擎 ≥ 90%；数据层 ≥ 85%；API 层 ≥ 70%；采集/监控层 ≥ 60%；整体 ≥ 75% |

---

## 1. 测试目标与分层

### 1.1 质量目标

1. **判定正确性**：三维（实为四维）一致性检测与评分公式在任意 IR × action 组合下结果确定、可复现。
2. **权限不可绕过**：双层权限模型（入门口令 / 特权会话）在每一个受保护接口上均不可旁路；建立**权限基线快照**防止新增接口误开放。
3. **数据不被污染**：`update_round_end` 的防覆盖规则、15 分钟时间窗、字段白名单在边界条件下行为一致。
4. **采集鲁棒性**：`proc_info` / `watcher` 在残缺 `/proc`、日志轮转、乱序事件、编码错误下**只降级不崩溃**（README 承诺「不阻塞 round 上报」）。
5. **回归防护**：`judge.py` 与 `resource_consistency_check.py` 为同源分叉双实现，需交叉一致性测试防止二者继续漂移。

### 1.2 分层策略

| 层 | 目标 | 手段 | 占比 |
|---|---|---|---|
| L1 纯函数单测 | 判定引擎、路径/命令解析、归一化、caps 解码、评分 | 无 mock，表驱动参数化 | ~55% |
| L2 组件单测 | `db.py`（临时 SQLite）、`policy_manager`（临时目录）、`api_docs`（假 Flask app） | 文件系统 fixture + monkeypatch | ~25% |
| L3 接口契约测试 | `app.py` 路由（Flask `test_client`），mock 掉 db/LLM/monitor | `unittest.mock` + fixture | ~15% |
| L4 伪环境测试 | `proc_info`（伪造 `/proc` 树）、`watcher`（伪造 jsonl/网关日志） | `tmp_path` 构造 + 常量 monkeypatch | ~5% |

**明确不在本阶段范围**：真实 LLM 调用、真实 OpenClaw 进程、端到端 WebSocket 联调、前端 E2E（归入集成测试阶段）。

---

## 2. 工具链与工程约定

### 2.1 依赖（需新增到 `backend/pyproject.toml`）

```toml
[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-cov>=6.0",
    "pytest-mock>=3.14",
    "freezegun>=1.5",        # 15 分钟时间窗 / 会话 TTL / starttime 测试
    "pytest-timeout>=2.3",   # watcher 线程类用例兜底
]
```

> 约束：`requires-python = ">=3.14"`，测试代码可使用 `match`、`X | None` 等新语法；判定引擎已使用 `set[Action]`、`str | Path`，测试须同版本运行。

### 2.2 目录结构

```
backend/
└── tests/
    ├── conftest.py                  # 全局 fixture（DB、app、伪 /proc）
    ├── data/                        # 冻结的黄金样本（脱敏）
    │   ├── ir/                      # IR JSON 样本（合规/越权/畸形）
    │   ├── actions/                 # action_json 样本
    │   ├── gateway/                 # Portkey 网关日志片段
    │   ├── openclaw/                # session .jsonl 片段
    │   └── proc/                    # 伪 /proc 快照（含 SELinux label、caps）
    ├── unit/
    │   ├── test_judge_primitives.py         # TS-05A
    │   ├── test_judge_layered.py            # TS-05B
    │   ├── test_judge_entry.py              # TS-05C
    │   ├── test_rcc_parity.py               # TS-06
    │   ├── test_shell_semantics.py          # TS-07
    │   ├── test_db_rounds.py                # TS-01A
    │   ├── test_db_config_kernel.py         # TS-01B
    │   ├── test_translator_core.py          # TS-03
    │   ├── test_policy_manager.py           # TS-04
    │   ├── test_proc_info.py                # TS-08
    │   ├── test_watcher_parse.py            # TS-09A
    │   ├── test_watcher_lifecycle.py        # TS-09B
    │   ├── test_ir_client.py                # TS-10
    │   ├── test_api_docs.py                 # TS-11
    │   └── test_xy_skill.py                 # TS-12
    └── api/
        ├── test_auth_permission_matrix.py   # TS-02A（权限基线）
        ├── test_rounds_api.py               # TS-02B
        ├── test_db_query_api.py             # TS-02C
        ├── test_translator_api.py           # TS-02D
        ├── test_intercept_turnir_api.py     # TS-02E
        └── test_attack_config_api.py        # TS-02F
```

### 2.3 命名与用例 ID 规范

- 文件：`test_<模块>_<切面>.py`；函数：`test_<被测函数>_<场景>_<预期>`。
- 用例 ID：`UT-<域>-<序号>`，域取 `JG`(judge) / `RCC` / `SH`(shell) / `DB` / `API` / `PERM` / `TR`(translator) / `PM`(policy) / `PI`(proc_info) / `WT`(watcher) / `IRC` / `DOC` / `XY`。
- 每条用例必须显式标注 `@pytest.mark.p0|p1|p2`，CI 可按 `-m p0` 做门禁快跑。
- 表驱动优先：同一分支族用 `@pytest.mark.parametrize` 收敛，避免用例爆炸。

### 2.4 运行命令

```bash
cd /home/hx/jjq/clawAVC/backend

# 全量 + 覆盖率
uv run pytest tests -q --cov=. --cov-report=term-missing \
  --cov-config=tests/.coveragerc

# 门禁快跑（提交前）
uv run pytest tests -m p0 -q

# 单模块
uv run pytest tests/unit/test_judge_layered.py -v
```

`tests/.coveragerc` 需 `omit = .venv/*, tests/*, main.py, */__pycache__/*`。

---

## 3. 测试基建（conftest.py）

### 3.1 关键隔离难点与对策

| # | 难点（代码实证） | 影响 | 对策 |
|---|---|---|---|
| 1 | `app.py` 顶部执行 gevent monkey-patch | 一旦 `import app`，整个 pytest 进程的 socket/thread 被打补丁，可能干扰其他用例 | API 层测试独立目录 `tests/api/`，CI 分两次调用 pytest（`tests/unit` 与 `tests/api` 分进程）；必要时用 `pytest-forked` |
| 2 | `db.DB_PATH` 为模块级常量（`db.py:9`） | 直接 import 会连生产库 `infos/db/clawAVC.db` | `monkeypatch.setattr(db, "DB_PATH", tmp_path/"t.db")` 后调用 `db.init_db()`；**严禁**任何用例触达真实 DB_PATH |
| 3 | `core.py` import 时即执行 `REGISTRY_DIR/SCENE_REGISTRY/TOOL_REGISTRY = load_*()`（`core.py:48,88,89`） | 策略库内容在 import 时固化，改配置无效 | 先 monkeypatch `core.REGISTRY_DIR`，再调 `core.reload_registry()`；或直接 monkeypatch 两个 REGISTRY 字典 |
| 4 | `policy_manager._cfg()` 内部 `sys.path.insert` + `import db`（`policy_manager.py:47-65`） | 隐式依赖 backend 在 sys.path，且读真实 config 表 | monkeypatch `db.get_config` / `db.set_config` 为内存字典；或 monkeypatch `policy_manager._cfg/_set_cfg` |
| 5 | `db.set_config` **被定义两次**（`db.py:1067` 与 `db.py:1320`） | 后者覆盖前者，行为需锚定 | 专门用例断言最终生效实现的语义（见 UT-DB-041） |
| 6 | `proc_info.PROC = Path("/proc")`、`SELF_PID`（`proc_info.py:68-69`） | 依赖真实内核 | monkeypatch `proc_info.PROC = tmp_path/"proc"`，用 fixture 生成伪进程目录树 |
| 7 | `_admin_sessions` 为 app.py 模块级内存字典 | 用例间会话泄漏 | 每个 API 用例 `autouse` fixture 清空 `app._admin_sessions` |
| 8 | `watcher` 大量使用 `threading` + `time.sleep` | 用例慢且不稳定 | 只测纯逻辑类（`RoundStateMachine`/`FileTailer`/解析函数），`MonitorOrchestrator` 用注入回调 + 手动驱动，不起真实线程；全局 `--timeout=30` |
| 9 | `judge`/`RCC` 依赖 `time`/`os` 极少 | —— | 可直接测，无需 mock（P0 起点） |

### 3.2 Fixture 清单

| Fixture | 作用域 | 产出 | 说明 |
|---|---|---|---|
| `temp_db` | function | 已 `init_db()` + `init_config_table()` 的临时 SQLite | 同时 patch `db.DB_PATH`，yield 后删除文件 |
| `seeded_round` | function | 插入一条 `insert_round_start` 的 round_id | 供 update 类用例复用 |
| `flask_client` | function | `app.app.test_client()` | 依赖 `temp_db`，并 mock `socketio.emit` 与 `broadcast_push` |
| `entry_token` | function | 写入 `secret_key=test-pass`，返回 header dict | 注意：`verify_secret` 读的是 **`secret_key`**（`db.py:1337`），而 CLAUDE.md 写的是 `entry_password` |
| `admin_session` | function | 写入 `admin_key`，调 `/api/admin/verify` 取 `session_token` | 返回 `{"X-Admin-Session": token}` |
| `fake_proc` | function | 伪 `/proc` 树构造器（工厂 fixture） | 参数：pid、cmdline、comm、status(含 CapEff/Uid/Gid/Seccomp/NoNewPrivs)、attr/current、cgroup、ns 软链、stat(starttime) |
| `policy_root` | function | 临时 `policies/{default,ops}/policy_registry/{scenes.json,tools/}` | 配合 patch 后的 `get_template()` |
| `gateway_log` | function | 写入 `YYYY-MM-DD.jsonl` 的 Portkey 片段 | 覆盖 `requestOptions[].finalUntransformedRequest.body.messages` |
| `openclaw_session` | function | 写入 `agents/main/sessions/<uuid>.jsonl` | 覆盖 user / assistant / toolResult 消息 |
| `frozen_now` | function | freezegun 时间锚点 | 15 分钟窗、TTL、starttime→ISO |
| `no_llm` | autouse(unit) | 阻断 `urllib.request.urlopen` 与 `requests.*` | 防止任何用例意外外呼 LLM |

### 3.3 黄金样本（Golden Data）

- 来源：`infos/` 下已有 552 个 `.jsonl` + 256 个 `.md` 真实审计产物，可**脱敏裁剪**后固化到 `tests/data/`。
- 纪律：样本必须（a）去除主机名/路径中的用户信息、token；（b）单文件 ≤ 50 KB；（c) 冻结不可随代码改动而改；（d）每个样本配 `README` 一行说明其覆盖的分支。
- 必备样本集：
  - IR：合规单策略、多策略、`deny` effect、空 `objects`、`actions` 缺失（触发 fail-open）、`identifier` 缺失（触发 `ValueError`）、glob `**`、`regex:` 前缀、非 dict/list（触发 `ValueError`）。
  - action：单工具、工具+资源、越权路径（`/etc/passwd`）、网络外发（`http://malicious.example.com/collect`）、`resources` 非 dict、缺 `identifier`。
  - pid_info：含 SELinux label、`seccomp=2`、容器 cgroup（docker/k8s）、`loginuid=4294967295`。

---

## 4. 模块测试套件

> 优先级：**P0** = 阶段三必须交付；**P1** = 阶段三内补齐；**P2** = 可延后。
> 下文用例表为**大纲级**，每行通常对应 1 个参数化测试函数（含 2~8 个参数组）。
> 套件排列顺序**按落地优先级**而非编号顺序：TS-05/06/07（判定引擎，零依赖先行）→ TS-01/02（数据与接口）→ TS-03/04（翻译与策略库）→ TS-08/09/10/11（采集与监控）→ TS-12/13。

### TS-05 判定引擎原语 —— `auditor/monitor/judge.py`（P0，最高优先级）

**被测对象**：模块级私有原语 + dataclass 解析。全部为纯函数，零外部依赖。
**隔离**：无需 mock。

#### TS-05A 归一化与匹配原语

| 用例 ID | 被测 | 场景 | 预期 | 优先级 |
|---|---|---|---|---|
| UT-JG-001 | `_as_list` | `None` / `list` / 标量 | `[]` / 原样 / `[x]` | P0 |
| UT-JG-002 | `_normalize_action` | 25 条别名表全覆盖（`open/openat/o_rdonly/read_file/summarize→read`；`write_file/patch/o_wronly/rename/renameat→write`；`o_creat→create`；`unlink/unlinkat/rmdir/rm→delete`；`chmod→setattr`；`execve/exec→execute`；`fetch/request/http_get/http_post/download/upload→connect`） | 逐条映射正确 | P0 |
| UT-JG-003 | `_normalize_action` | 大小写 / 前后空格 / `None` / 未命中别名 | 统一小写去空格；`None→""`；未命中原样返回 | P0 |
| UT-JG-004 | `_infer_resource_type` | fallback 合法（file/tool/network）优先 | 直接采用 fallback，不做推断 | P0 |
| UT-JG-005 | `_infer_resource_type` | `http://` `https://` `ftp://` `ssh://` `git://`、裸 netloc | `network` | P0 |
| UT-JG-006 | `_infer_resource_type` | `/etc/passwd`、`./a.txt`、`.env` | `file` | P0 |
| UT-JG-007 | `_infer_resource_type` | `read`、`safe_file_reader` | `tool` | P0 |
| UT-JG-008 | `_glob_pattern_to_regex` | `/tmp/**`、`/tmp/*.txt`、含正则元字符的字面量（`a+b.txt`） | `**→.*`、`*→[^/]*`、其余 `re.escape`；首尾锚定 | P0 |
| UT-JG-009 | `_glob_pattern_to_regex` vs `_glob_param_to_regex` | 同一模式 `/a/*/b` | **差异断言**：identifier 版 `*` 不跨 `/`，param 版 `*` 跨 `/` | P0 |
| UT-JG-010 | `_is_regex_pattern` / `_strip_regex_prefix` | `regex:^/tmp/.*$`、`re:...`、`REGEX:...`（大写）、`match_mode="regex"` | 前缀识别与剥离正确，剥离后**保留原大小写** | P0 |
| UT-JG-011 | `_match_identifier` | 完全相等 / glob 命中 / glob 不命中 / regex 命中 / 非法正则 | 匹配链 等值→regex→glob 逐级；非法正则不抛异常 | P0 |
| UT-JG-012 | `_match_identifier` | `match_mode="exact"` 时 glob 不生效 | 仅等值 | P1 |
| UT-JG-013 | `_match_param_value` | 等值 / `regex:` / glob（跨 `/`）/ 不匹配 | 按序命中 | P0 |
| UT-JG-014 | **`_action_allowed`** | `allowed_actions` 为**空集合** | **返回 True（fail-open 放行一切）** —— 安全语义必须锚定并在评审中确认是否符合设计 | **P0** |
| UT-JG-015 | `_action_allowed` | `network` + `connect` vs `{receive}` / `{send}` / `{connect}` | 交集非空即放行 | P0 |
| UT-JG-016 | `_action_allowed` | `file` + `write` vs `{read}` | False | P0 |
| UT-JG-017 | **`_params_match`** | expected 为空 → True；expected 子集命中 → True；**actual 含 expected 之外的额外键 → 仍 True** | **单向子集匹配语义**（潜在参数注入面），必须锚定 | **P0** |
| UT-JG-018 | `_params_match` | expected 键在 actual 中缺失 / 值不匹配 | False | P0 |
| UT-JG-019 | `_parse_params` | dict（值含 int/None → 全部 str 化）/ list（取 `name`\|`identifier` → `value`）/ 空 | dict / dict / `None` | P0 |
| UT-JG-020 | `_parse_object` | identifier 取值优先级 `identifier/path/url/domain/host/name/resource` | 逐字段回退正确；**注意不支持 `uri`/`endpoint`**（与 `_normalize_actions` 不一致，需记录） | P0 |
| UT-JG-021 | `_parse_object` | 全部候选键缺失 | 抛 `ValueError` | P0 |
| UT-JG-022 | `_parse_object` | `identifier_match` 取 `identifier_match` 或 `match`，大写输入 | `.lower()` 后生效 | P1 |
| UT-JG-023 | `parse_ir_policies` | `{"policies":[...]}` / 裸 list / 单 policy dict | 三形态均解析成功 | P0 |
| UT-JG-024 | `parse_ir_policies` | `objects` / `object` / `resources` 三种键名 | 等价 | P0 |
| UT-JG-025 | `parse_ir_policies` | policy 级 `action` / `selinux_rules` 下渗到 object | object 继承 | P1 |
| UT-JG-026 | `parse_ir_policies` | 传入字符串 / int / None | 抛 `ValueError("IR JSON must be an object or a list")` | P0 |
| UT-JG-027 | `load_ir_policies` | 文件不存在 / **文件存在但 size==0** / 合法 JSON / 非法 JSON | `FileNotFoundError` / `FileNotFoundError` / 正常 / `JSONDecodeError` | P0 |
| UT-JG-028 | `_evaluate_event` | `obj.type != event.resource_type` | 跳过该 obj，不算匹配 | P0 |
| UT-JG-029 | `_evaluate_event` | tool 事件 + 参数不匹配 | 立即返回 `(False, ["tool param mismatch: ..."], [])`，**不再尝试后续 policy** | P0 |
| UT-JG-030 | `_evaluate_event` | 动作越权 | 返回 `action over-privilege: <action> on <id>, allowed=[...]` 文案 | P0 |
| UT-JG-031 | `_evaluate_event` | 完全无命中 | `resource out of IR allow scope: <type>:<id>` | P0 |
| UT-JG-032 | `_evaluate_event` | 命中且带 `selinux_rules` | 返回 `matched_rules` 透传 | P1 |
| UT-JG-033 | `_aspect_result` | `total_count == 0` | `score == 1.0`（空维度视为满分） | P0 |
| UT-JG-034 | `_aspect_result` | 1/3 命中 | `score == 0.3333`（round 到 4 位） | P0 |
| UT-JG-035 | `_aspect_result` | `violations` 非空但 matched==total | `consistent == "no"`（consistent 由 violations 决定，**与 score 解耦**） | P0 |

#### TS-05B 分层判定与评分 —— `Resource_Consistency_Check_Layered`

| 用例 ID | 场景 | 预期 | 优先级 |
|---|---|---|---|
| UT-JG-101 | **四维结构断言** | 返回 `LayeredCheckResult` 含 `tool_call_consistency`、`tool_trajectory_consistency`、`parameter_consistency`、`resource_access_consistency` —— **实现为 4 维，README/CLAUDE.md 只描述 3 维，文档需同步** | **P0** |
| UT-JG-102 | `overall_score` 公式 | 仅对 `total_count > 0` 的维度取算术平均，`round(...,4)`；四维全空 → `1.0` | P0 |
| UT-JG-103 | 输入形态兼容 | `ir_input` 为 `str` / `Path` / `dict` / `list` / `Sequence[IRPolicy]` 五形态等价 | P0 |
| UT-JG-104 | 输入形态兼容 | `behavior_input` 为 `dict`（网关 trace）/ `Sequence[BehaviorEvent]` / `list`（messages） | P0 |
| UT-JG-105 | `effect="deny"` 的 policy | 被过滤，不参与 allow 判定 | P0 |
| UT-JG-106 | 工具调用一致性 | 工具在 IR 白名单内 + 动作允许 | `tool_call.matched_count` 递增，无 violation | P0 |
| UT-JG-107 | 工具调用一致性 | 工具**不在** IR 范围（README 例：IR 允许 `read`，实际调 `exec`） | `tool out of IR allow scope: exec` | P0 |
| UT-JG-108 | 工具动作越权 | 命中 identifier 但动作不允许 | `tool action over-privilege: ...` | P0 |
| UT-JG-109 | **越权后续事件计数缺陷探测** | 构造 `[越权工具A, 合规工具B]` 序列 | 锚定 `judge.py:791` 条件 `not tool_call_violations or "tool action over-privilege" not in tool_call_violations[-1]` 的实际行为：**前一条 violation 会影响后一条合规事件是否被计入 matched**，用例必须固化当前真实输出并标注为待评审风险 | **P0** |
| UT-JG-110 | 参数一致性 | 仅统计「identifier 命中的 tool 事件」，未命中的**不计入 `parameter_total`** | 分母语义锚定 | P0 |
| UT-JG-111 | 参数一致性 | README 例：IR 允许 `path=/tmp/a.txt`，实际传 `path=/etc/passwd` | `tool param mismatch: ...` | P0 |
| UT-JG-112 | 参数一致性 | `matched_obj` 取 `next(...)` 即**第一个命中**的 obj | 多 obj 命中时只比对首个（语义锚定） | P1 |
| UT-JG-113 | 资源访问一致性 | README 例：IR 允许 `read /tmp/**`，实际 `write /etc/cron.d/x` | 资源维 violation | P0 |
| UT-JG-114 | 资源访问一致性 | 网络资源 `http://malicious.example.com/collect` 不在 IR | `resource out of IR allow scope: network:...` | P0 |
| UT-JG-115 | 轨迹一致性 | 观测顺序是期望顺序的**子序列**（贪心指针算法） | 全部命中，无 violation | P0 |
| UT-JG-116 | 轨迹一致性 | 观测顺序乱序 / 含期望列表外的工具 | `tool trajectory mismatch: expected_order=[...], observed_order=[...]` | P0 |
| UT-JG-117 | 轨迹一致性 | 同一工具重复调用（期望列表只出现 1 次） | 指针单向前进导致第 2 次不命中 —— 语义锚定 | P0 |
| UT-JG-118 | 轨迹一致性 | `observed_tool_order` 为空 | 不产生 violation，`total_count==0`，不计入 overall | P0 |
| UT-JG-119 | `matched_rules` | 多 obj 命中重复规则 | `sorted(set(...))` 去重排序 | P1 |
| UT-JG-120 | `consistent` 判定 | 任一维度产生 violation | 顶层 `consistent == "no"` | P0 |
| UT-JG-121 | 阈值语义（README 评分表） | `overall_score` 恰为 `0.5` / `0.5001` / `-1` | 与 README「>0.5 合规、≤0.5 异常、-1 检测中」映射一致（阈值判定在调用方，用例覆盖临界值构造能力） | P0 |
| UT-JG-122 | `Resource_Consistency_Check_Scored` | 无行为事件 | `score == 1.0`、`total_count == 0`、`consistent == "yes"` | P0 |
| UT-JG-123 | `Resource_Consistency_Check_Scored` | 混合命中 | `score == round(matched/total, 4)` | P0 |
| UT-JG-124 | `Resource_Consistency_Check` | 基线版返回 `CheckResult` | 结构与 violations 正确 | P1 |
| UT-JG-125 | `layered_result_to_dict` | 任意结果 | `asdict()` 可 JSON 序列化（含嵌套 dataclass） | P1 |
| UT-JG-126 | `layered_result_to_text` | 合规 / 异常 | 首行分别为 `【判定结果】行为一致，整体得分: <s>` / `【判定结果】行为异常，整体得分: <s>` | P0 |
| UT-JG-127 | `layered_result_to_text` | `total_count == 0` 的维度 | 该维度段落**不输出**（前端解析依赖，需锚定） | P0 |
| UT-JG-128 | `layered_result_to_text` | 含中文路径 / 超长 violations | 不抛异常，无编码问题 | P1 |

#### TS-05C 顶层入口与网关解析

| 用例 ID | 被测 | 场景 | 预期 | 优先级 |
|---|---|---|---|---|
| UT-JG-201 | `judge(action, IR)` | 使用 `judge.py:1141` 自带 demo 样本（read `/temp/helloworld.txt`） | 输出文本稳定（golden 文本比对） | P0 |
| UT-JG-202 | `judge` | `action=None` / `[]` / 非 list 标量 / 含非 dict 元素 | 不抛异常，返回合法文本 | P0 |
| UT-JG-203 | `judge` | `IR=None` / `{}` / `"__loading__"` / 畸形 JSON dict | 不抛异常（`_normalize_ir` 兜底） | P0 |
| UT-JG-204 | `_normalize_ir` | `{"level1":[...],"level2":{"policies":[...]}}` 两阶段结构 | 正确提取 level2 策略 | P0 |
| UT-JG-205 | `_normalize_ir` | `functions` + `file_actions` + `resource_type` + `scene` 的 Level-2 真实结构 | 转为 IRObject 列表 | P0 |
| UT-JG-206 | `_normalize_actions` | `{"tool","arguments","resources","result"}` 标准形态 | 产出 1 个 tool 事件（`action="invoke"`）+ N 个资源事件 | P0 |
| UT-JG-207 | `_normalize_actions` | `resources[].identifier/path/url/uri/endpoint/domain/host` 七键回退 | 逐键生效（**比 `_parse_object` 多支持 `uri`/`endpoint`，不对称需记录**） | P0 |
| UT-JG-208 | `_normalize_actions` | `access` / `action` 缺失 | 默认 `"read"` | P0 |
| UT-JG-209 | `_normalize_actions` | `resources` 项无 identifier / 非 dict / `tool` 为空串 | 静默跳过，不产生事件 | P0 |
| UT-JG-210 | `_normalize_actions` | `arguments` 非 dict | `params=None` | P1 |
| UT-JG-211 | `gateway_messages_to_behaviors` | 完整 Portkey `body.messages`（含 assistant `tool_calls`） | 正确产出行为事件序列 | P0 |
| UT-JG-212 | `gateway_messages_to_behaviors` | `content` 为 list（多模态块）/ 纯字符串 | `_gateway_content_to_text` 归一 | P1 |
| UT-JG-213 | `_infer_exec_behaviors` | `command` 参数触发 shell 语义分析联动 | 调用 `analyze_shell_command` 并转为行为事件 | P0 |
| UT-JG-214 | `_resolve_exec_path` | 相对路径 + `workdir` / 绝对路径 / `~` | 归一为绝对路径 | P0 |
| UT-JG-215 | `_looks_like_path` / `_looks_like_network_identifier` / `_normalize_network_identifier` | 边界串（`-`、`--flag`、`a=b`、`1.2.3.4:80`、`example.com`） | 分类正确 | P0 |

---

### TS-06 分叉实现一致性 —— `auditor/monitor/resource_consistency_check.py`（P0/P1）

**关键事实**：`resource_consistency_check.py`（1221 行）与 `judge.py`（1175 行）是**同源分叉的两份实现**，共有大量同名函数；RCC 侧额外具备 `_parse_open_flags`、`_normalize_behavior_action`、`_extract_trace_metadata`、`_timestamp_from_user_content`、`_user_round_metadata`、`_assistant_event_metadata`、`_tool_result_metadata`、`_shell_complexity_reason`、`demo_behaviors`。

| 用例 ID | 场景 | 预期 | 优先级 |
|---|---|---|---|
| UT-RCC-001 | **双实现同名函数交叉一致性**（表驱动：对 `_normalize_action`、`_match_identifier`、`_action_allowed`、`_params_match`、`_glob_*`、`parse_ir_policies` 喂同一组输入） | 逐一断言两模块输出相等；**任何不等即视为分叉漂移缺陷并记录** | **P0** |
| UT-RCC-002 | `_parse_open_flags` | `"O_RDONLY"`、`"O_WRONLY\|O_CREAT"`、八进制 `0o100`、十进制字符串、`None`、乱码 | 解析为 int 或 `None` | P0 |
| UT-RCC-003 | `_normalize_behavior_action` | open flags → `read`/`write`/`create` 的映射 | 内核态 syscall 语义正确落到用户态动作 | P0 |
| UT-RCC-004 | `_shell_complexity_reason` | 含管道 / 命令替换 `$(...)` / 反引号 / 复杂重定向 | 返回不可静态判定的原因串；简单命令返回 `None` | P0 |
| UT-RCC-005 | `_timestamp_from_user_content` | 带 `[YYYY-MM-DD HH:MM:SS]` 前缀 / 无时间戳 | 提取或 `None` | P1 |
| UT-RCC-006 | `_user_round_metadata` / `_assistant_event_metadata` / `_tool_result_metadata` | 完整网关 trace | 元数据（round/时间/tool_call_id 映射）正确 | P1 |
| UT-RCC-007 | `_extract_trace_metadata` | 缺字段 / 空 trace | 返回空 dict，不抛异常 | P1 |
| UT-RCC-008 | `Resource_Consistency_Check_Layered`（RCC 版） | 与 judge 版同输入 | 输出结构一致性对比 | P0 |
| UT-RCC-009 | `demo_behaviors()` | 直接调用 | 返回可用于自检的行为样本，且能喂入 Layered 不报错 | P2 |
| UT-RCC-010 | `layered_result_to_dict`（RCC 版） | —— | 可序列化 | P2 |

> **架构建议（随测试一并提出）**：将两份实现的公共原语抽取为 `_primitives.py`，用 UT-RCC-001 作为抽取前后的等价性保护网。

---

### TS-07 Shell 命令语义 —— `auditor/monitor/shell_command_semantics.py`（P0）

**被测对象**：`analyze_shell_command(command, workdir=None) -> ShellAnalysis`，及 `_tokenize`、`_split_segments`、`_redirection_behaviors`、`_strip_redirections`、`_option_values`、`_path_args`、`_network_args`、`_skip_wrappers`、`_nested_shell_command`、`_analyze_segment`、`_status_for_identifier`、`_merge_status`。

| 用例 ID | 被测 | 场景 | 预期 | 优先级 |
|---|---|---|---|---|
| UT-SH-001 | `_tokenize` | 单引号 / 双引号 / 转义空格 / 未闭合引号 | 正确切词；未闭合不抛异常（降级） | P0 |
| UT-SH-002 | `_command_name` | `/usr/bin/cat`、`cat`、`./run.sh` | 取 basename | P0 |
| UT-SH-003 | `_is_assignment` | `FOO=bar`、`FOO=`、`=bar`、`a==b` | 赋值前缀识别正确 | P0 |
| UT-SH-004 | `_looks_like_path` | `/etc/passwd`、`./a`、`../b`、`~/c`、`a/b`、`-l`、`--flag`、`80` | 分类正确 | P0 |
| UT-SH-005 | `_looks_like_network_identifier` / `_is_remote_path` | `http://x`、`user@host:/p`、`host:port`、`git@github.com:o/r.git` | 网络/远端识别正确 | P0 |
| UT-SH-006 | `_resolve_path` | 相对路径 + workdir / 无 workdir / `~` 展开 | 绝对化正确；无 workdir 时的降级语义锚定 | P0 |
| UT-SH-007 | `_split_segments` | `SHELL_OPERATORS = {\|, \|\|, &&, ;, &}` 全覆盖 + 混合 | 正确切分为多段 | P0 |
| UT-SH-008 | `_redirection_behaviors` | `REDIRECT_READ={<}`、`REDIRECT_WRITE={>,>>,1>,1>>,2>,2>>}` 全覆盖 | 产出对应 read/write 行为 | P0 |
| UT-SH-009 | `_redirection_behaviors` | `> /dev/null`、`2>&1`（fd 复制而非文件） | 不误判为文件写 | P0 |
| UT-SH-010 | `_strip_redirections` | 重定向 token 与目标一并剔除 | 剩余 token 干净 | P0 |
| UT-SH-011 | `_skip_wrappers` | `sudo`、`env A=1`、`nohup`、`timeout 5`、`nice -n 10` 组合前缀 | 剥离到真实命令 | P0 |
| UT-SH-012 | `_nested_shell_command` | `bash -c "cat /etc/passwd"`、`sh -lc '...'` | 提取内层命令串并递归分析 | P0 |
| UT-SH-013 | `_nested_shell_command` | 多层嵌套 `bash -c "bash -c '...'"` | 递归终止，不无限循环 | P0 |
| UT-SH-014 | `_option_values` / `_path_args` / `_network_args` | `curl -o out.txt http://x`、`tar -f a.tar` | 选项值与位置参数分别归类 | P0 |
| UT-SH-015 | `_analyze_segment` | 读类命令 `cat/head/tail/less/grep` | 产出 `read` 行为 | P0 |
| UT-SH-016 | `_analyze_segment` | 写类命令 `tee/dd/cp/mv/install` | 产出 `write`（及 `read` 源） | P0 |
| UT-SH-017 | `_analyze_segment` | 删除类 `rm/rmdir/unlink/shred` | 产出 `delete` | P0 |
| UT-SH-018 | `_analyze_segment` | 权限类 `chmod/chown/setfacl` | 产出 `setattr` | P0 |
| UT-SH-019 | `_analyze_segment` | 网络类 `curl/wget/nc/ssh/scp/git clone` | 产出 `connect` + 网络 identifier | P0 |
| UT-SH-020 | `_analyze_segment` | 执行类 `python x.py`、`./bin`、`node s.js` | 产出 `execute` + 脚本文件 `read` | P0 |
| UT-SH-021 | `_analyze_segment` | **敏感目标**：`/etc/passwd`、`/root/.ssh/id_rsa`、`/etc/cron.d/x`（README 攻击样例） | 行为可被上层判定为越权 | P0 |
| UT-SH-022 | `_status_for_identifier` / `_merge_status` | 含通配符 / 变量 `$VAR` / 命令替换的路径 | 状态降级为不确定（`InferenceStatus`），并在 `ShellAnalysis` 上聚合 | P0 |
| UT-SH-023 | `analyze_shell_command` | 空串 / 纯空白 / 仅操作符 `;;` / 仅赋值 `A=1` | 返回空行为集，不抛异常 | P0 |
| UT-SH-024 | `analyze_shell_command` | 管道链 `cat /etc/passwd \| grep root > /tmp/o` | 同时产出 read(/etc/passwd) + write(/tmp/o) | P0 |
| UT-SH-025 | `analyze_shell_command` | 超长命令（>8KB）/ 含中文路径 / 含 emoji | 不抛异常，性能可接受 | P1 |
| UT-SH-026 | `ShellBehavior` / `ShellAnalysis` dataclass | 字段完整性 | 可序列化，供上层构造 `BehaviorEvent` | P1 |

### TS-01 数据层 —— `db.py`（P0）

**依赖隔离**：`temp_db` fixture（patch `DB_PATH` → tmp）；文件复制类函数用 `tmp_path` 造源文件；时间窗用 `freezegun`。

#### TS-01A 建表 / 迁移 / rounds 读写

| 用例 ID | 被测 | 场景 | 预期 | 优先级 |
|---|---|---|---|---|
| UT-DB-001 | `get_conn` | 连接属性 | `row_factory == sqlite3.Row`、`check_same_thread=False`、`journal_mode=WAL`、`synchronous=NORMAL` 生效 | P0 |
| UT-DB-002 | `init_db` | 空库首次执行 | 建出 `rounds`/`translation_log`/`config`/`attack_messages`/`intercept_events`/`api_trace`/`anomaly_chats` 七表 | P0 |
| UT-DB-003 | `init_db` | 幂等性：连续执行 2 次 | 不报错、无重复表、已有数据不丢 | P0 |
| UT-DB-004 | `init_db` | 索引 | `idx_rounds_time`、`idx_rounds_abnormal` 存在 | P1 |
| UT-DB-005 | `init_db` | **增量迁移**：手工建一张缺列的旧 `rounds` 表后执行 | 依次补齐 `attack_config`/`pid_info`/`kernel_syscall_seq`/`kernel_lsm_hook_result`/`kernel_resource_facts`/`judge_result_kernel`/`syscall_judge`/`history`/`anomaly_llm_v2_judge_res`/`anomaly_llm_v2_chat_session` 共 10 列，**存量数据保留** | P0 |
| UT-DB-006 | `init_db` | `resource_facts` → `kernel_resource_facts` 重命名迁移分支（建表→DROP→RENAME） | 数据迁移成功；失败时仅打印不抛异常。**注意该分支条件为 `"resource_facts" in cols and "kernel_resource_facts" not in cols`，而前置逻辑已先补齐 `kernel_resource_facts`，条件恒假 —— 需用例确认为死代码并上报** | P0 |
| UT-DB-010 | `insert_round_start` | 正常插入 | 返回 `lastrowid`；占位值断言 `overall_score == -1.0`、`is_abnormal == 0`、`action_json == "[]"`、`ir_json == "{}"`、`time_end == ""` | P0 |
| UT-DB-011 | `insert_round_start` | 同 `round_id` 重复插入（`INSERT OR IGNORE` + UNIQUE） | 第二次返回 `None`（`rowcount == 0`），原记录不被覆盖 | P0 |
| UT-DB-012 | `insert_round_start` | `attack_config` / `pid_info` / `history` 传入超大 JSON 字符串 | 原样固化，可完整读回 | P0 |
| UT-DB-013 | `insert_round_start` | `round_id=""` | 行为锚定（当前不校验空 ID） | P1 |
| UT-DB-020 | `update_round_end` | 全字段有值 | 全部落库，返回 `True` | P0 |
| UT-DB-021 | `update_round_end` | **防覆盖**：`user_query`/`judge_result`/`time_end`/`last_llm_message`/`history` 传 `None` 或 `""` | 跳过该字段，DB 原值保留 | P0 |
| UT-DB-022 | `update_round_end` | `is_abnormal` 传 `0`/`False`/`""`/`None` | 前三者写入（`None` 才跳过）；`""` → 写 0。**布尔化语义锚定** | P0 |
| UT-DB-023 | `update_round_end` | `overall_score` 传 `0`/`0.0`/`-1` | 写入（`0` 不被当空值跳过） | P0 |
| UT-DB-024 | `update_round_end` | **`action_json` 占位保护**：入参 `"[]"` 且 DB 已有真实 actions | 跳过，保留 DB 真实值 | P0 |
| UT-DB-025 | `update_round_end` | 入参 `"[]"` 且 DB 也是 `"[]"` | 允许写入 | P0 |
| UT-DB-026 | `update_round_end` | **`ir_json` 占位保护**：入参 `"{}"` 或 `"__loading__"` 且 DB 已有真实 IR | 跳过（对应 README「portkey 早先回填的真实 IR 不被覆盖」） | P0 |
| UT-DB-027 | `update_round_end` | 入参真实 IR 且 DB 为 `"__loading__"` | 正常覆盖 | P0 |
| UT-DB-028 | `update_round_end` | **所有字段均被跳过** | 返回 `False`（不执行 UPDATE），打印 `no fields to update` | P0 |
| UT-DB-029 | `update_round_end` | `round_id` 不存在 | `affected == 0` → 返回 `False`（触发 app 层 legacy fallback） | P0 |
| UT-DB-030 | `update_round_end` | 传入未知字段（如 `foo`） | 被忽略，不参与 SET（防注入） | P0 |
| UT-DB-031 | `insert_round` | legacy 形态 `{round, sessionKey, sessionID, action, IR, abnormal_judge}` | 正确映射入库并计算 `is_abnormal`/`overall_score` | P0 |
| UT-DB-032 | `insert_round` | `action`/`IR` 为 dict/list 对象 | JSON 序列化落库 | P0 |
| UT-DB-033 | `get_rounds` | 默认参数 | `limit=50, offset=0`，返回 `{total, data}` 结构 | P0 |
| UT-DB-034 | `get_rounds` | `abnormal_only=True` | 仅返回 `is_abnormal=1` | P0 |
| UT-DB-035 | `get_rounds` | `query` 模糊筛选（含 `%`、`_`、单引号、中文） | 参数化查询不被注入，`%`/`_` 行为锚定 | P0 |
| UT-DB-036 | `get_rounds` | `round_id` 精确 + `time_from`/`time_to` 组合 | 条件正确叠加 | P0 |
| UT-DB-037 | `get_rounds` | 分页边界：`limit=0`、`offset` 超出总数、`limit` 为负 | 不抛异常，`total` 与 `data` 语义一致 | P0 |
| UT-DB-038 | `get_rounds` | 排序 | 按 `time_start DESC` | P1 |
| UT-DB-039 | `get_round_by_id` | 存在 / 不存在 | `dict` / `None` | P0 |
| UT-DB-040 | `get_stats` | 空库 / 混合库 | `total`/`abnormal`/`normal`/`avg_score` 正确；空库不除零 | P0 |

#### TS-01B 字段更新 / 时间窗 / 内核态 / config / 翻译日志

| 用例 ID | 被测 | 场景 | 预期 | 优先级 |
|---|---|---|---|---|
| UT-DB-050 | `update_round_field` | **字段白名单**：`UPDATABLE_FIELDS = [action_json, ir_json, judge_result, judge_result_kernel, syscall_judge]` 逐个 | 全部返回 `"ok"` 并落库 | P0 |
| UT-DB-051 | `update_round_field` | **SQL 注入探测**：`field="action_json = 1, is_abnormal"`、`field="1;DROP TABLE rounds--"` | 返回 `"unsupported"`，表结构与数据完好（白名单是唯一防线，因 SQL 用 f-string 拼列名） | **P0** |
| UT-DB-052 | `update_round_field` | `field="is_abnormal"` | 返回 `"unsupported"`（不在白名单）→ 证明函数内 `if field == "is_abnormal"` 分支为**死代码**，上报清理 | P0 |
| UT-DB-053 | `update_round_field` | `round_id` 不存在 | `"not_found"` | P0 |
| UT-DB-054 | `update_round_field` | `created_at` 距今 14 分 59 秒 / 15 分 01 秒（freezegun） | `"ok"` / `"too_old"` | P0 |
| UT-DB-055 | `update_round_field` | **时区一致性缺陷探测**：`created_at` 由 SQLite `CURRENT_TIMESTAMP`（UTC）写入，而校验用 `datetime.now()`（本地时区，东八区 +8h） | 断言实测结果并上报：在东八区环境下**刚创建的记录也会被判 `too_old`**，属高危功能缺陷（建议改用 `datetime.utcnow()` 或存带时区时间） | **P0** |
| UT-DB-056 | `update_round_field` | `time_limit_enabled=False` + 超期记录 | `"ok"`（对应 `round_update_time_limit` 开关） | P0 |
| UT-DB-057 | `update_round_field` | `created_at` 为 `NULL` / 非 `%Y-%m-%d %H:%M:%S` 格式 | `NULL` 跳过校验；格式错触发 `ValueError` → 被捕获返回 `"error"` | P0 |
| UT-DB-060 | `update_kernel_info` | 三个源文件均存在 | 复制到 `infos/kernel_infos/<round_id>/<round_id>_syscall_seq.jsonl` 与 `_lsm_hook_result.jsonl`；`kernel_resource_facts` 存**文件内容**而非路径；返回 `"ok"` | P0 |
| UT-DB-061 | `update_kernel_info` | 目标文件已存在 | 覆盖成功（并打印 Overwriting） | P0 |
| UT-DB-062 | `update_kernel_info` | 任一源路径不存在（非空但无文件） | 返回 `"error"`，**且此时目录已被创建、其他文件可能已复制** —— 部分副作用语义锚定 | P0 |
| UT-DB-063 | `update_kernel_info` | 三路径全为空串 | 三字段写空串，返回 `"ok"`（清空语义） | P0 |
| UT-DB-064 | `update_kernel_info` | 校验顺序 | **文件复制发生在 `not_found` / `too_old` 校验之前** → 不存在的 round 也会产生残留目录，上报为副作用缺陷 | P0 |
| UT-DB-065 | `update_kernel_info` | `round_id` 含 `../` 等路径穿越字符 | 断言实测（当前 `infos_dir` 直接用 round_id 拼接，**存在穿越风险**）并上报 | **P0** |
| UT-DB-066 | `update_kernel_info` | 时间窗 15 分钟 / 开关关闭 | 同 UT-DB-054/056 | P0 |
| UT-DB-067 | `update_judge_result_kernel` | 正常 / 不存在 / 超期 / 开关关闭 | `"ok"`/`"not_found"`/`"too_old"`/`"ok"` | P0 |
| UT-DB-068 | `update_syscall_judge_json` | dict / list / 字符串 / `None` 输入 | 经 `parse_json_input` 归一后落库 | P0 |
| UT-DB-069 | `parse_json_input` | 合法 JSON 串 / dict / list / 非 JSON 串 / `None` / 嵌套超深 | 统一返回 dict，不抛异常 | P0 |
| UT-DB-070 | `update_anomaly_llm_v2_judge` | 正常 / round 不存在 | `"ok"` / `"not_found"`；**且明确不受 15 分钟限制**（与其它 update 语义不同，需锚定） | P0 |
| UT-DB-080 | `get_config` / `set_config` | 写读往返、覆盖同 key、默认值回退、key 不存在 | 语义正确 | P0 |
| UT-DB-081 | **`set_config` 重复定义**（`db.py:1067` 与 `db.py:1320`） | 调用 `db.set_config` | 断言实际生效的是后定义版本，并对比两版语义差异（返回值 `bool` vs `None`），上报去重 | **P0** |
| UT-DB-082 | `init_config_table` | 与 `init_db` 中重复的 `CREATE TABLE config` | 幂等无冲突；`_init_translator_prompts` 默认提示词只在缺失时写入 | P0 |
| UT-DB-083 | `get_configs_by_prefix` | `monitor_conf.` / `ir_translator.` / `attack.inject.` 前缀；含 `%`/`_` 的 prefix | LIKE 前缀匹配正确；特殊字符行为锚定 | P0 |
| UT-DB-084 | `verify_secret` | 正确口令 / 错误 / 空串 / **config 中未设置 `secret_key`** | `True`/`False`/`False`/`False`（未设置时任何口令均拒绝）；**同时记录：代码读 `secret_key`，CLAUDE.md 写 `entry_password`，文档需修正** | **P0** |
| UT-DB-085 | `verify_admin` | 正确 / 错误 / 空串 / 未设置 `admin_key` | 同上语义 | P0 |
| UT-DB-086 | `verify_secret` / `verify_admin` | 大小写、前后空格、Unicode 同形字符 | 严格等值比较（不做 strip / 归一） | P1 |
| UT-DB-090 | `insert_translation_log` | 正常写入 | 返回 rowid，字段齐全 | P1 |
| UT-DB-091 | `insert_translation_log_pending` | 建 pending 记录 | `level1_json`/`level2_json` 为空（对应前端「翻译中」状态） | P0 |
| UT-DB-092 | `update_translation_log_level1` | Level-1 完成后更新 | 仅更新 `level1_json`/`meta_json`，不动 level2 | P0 |
| UT-DB-093 | `insert_or_update_translation_log` | 同 round 二次调用 | upsert 语义：更新而非新增（README「3 次更新」流程） | P0 |
| UT-DB-094 | `insert_or_update_translation_log` | `round_id=None`（UI 测试场景 `is_ui_test=True`） | 走 insert 分支 | P1 |
| UT-DB-095 | `get_translation_logs` | 分页 + `ui_only=True/False` | 筛选与排序正确 | P1 |
| UT-DB-100 | `insert_attack_message` / `get_attack_messages` / `clear_attack_messages` | 增查清三连 + `request_method` 迁移列 | 语义正确，`clear` 返回删除条数 | P1 |
| UT-DB-101 | `insert_api_trace` / `get_api_trace` / `clear_api_trace` | 含 `path` 筛选 | 语义正确 | P2 |
| UT-DB-102 | `create_anomaly_chat` / `upsert_anomaly_chat` / `get_anomaly_chat` / `list_anomaly_chats` / `delete_anomaly_chat` | 会话 CRUD 全链路 | messages 列表 JSON 往返无损；删除不存在返回 `False` | P1 |
| UT-DB-103 | `set_round_anomaly_chat_session` | 绑定/重绑/round 不存在 | `"ok"`/`"ok"`/`"not_found"` | P1 |
| UT-DB-104 | `import_from_jsonl` | 合法 JSONL / 含空行 / 含畸形行 / 文件不存在 | 逐行容错，畸形行跳过不中断 | P1 |
| UT-DB-110 | 并发写入 | 两个连接同时 `insert_round_start` 同一 round_id | UNIQUE 约束生效，不产生重复行（WAL 模式下） | P1 |

---

### TS-02 API 与权限层 —— `app.py`（P0）

**依赖隔离**：`flask_client` fixture；`db` 走 `temp_db` 真库（更贴近契约）或按需 mock；`socketio.emit`/`broadcast_push`/`_send_webhook` 全部 mock；`core.translate`、`xy_skill.*`、`watcher.*` 全部 mock；`autouse` 清空 `_admin_sessions`。

#### TS-02A 权限基线矩阵（最高优先级，横向课题核心）

**做法**：建立一张**声明式权限期望表**，参数化遍历全部路由，逐一断言「无 token / 错误 token / 入门 token / 特权 token」四种身份下的状态码。该测试同时充当**新增接口误开放的回归闸门**。

| 用例 ID | 场景 | 预期 | 优先级 |
|---|---|---|---|
| UT-PERM-001 | `POST /api/auth` 正确 / 错误 / 空口令 | 200 / 401 / 401 | P0 |
| UT-PERM-002 | `POST /api/admin/verify` 正确密钥 | 200 + 32 位 `session_token`（`sha256(key+time)[:32]`）+ `ttl` | P0 |
| UT-PERM-003 | `POST /api/admin/verify` 错误密钥 | 401，且**不产生**会话（`_admin_sessions` 无新增） | P0 |
| UT-PERM-004 | `_check_admin_session` | 有效 token / 不存在 token / **已过期 token** | `True` / `False` / `False` **且过期条目被删除** | P0 |
| UT-PERM-005 | `_check_admin_session` | freezegun 推进到 `ADMIN_SESSION_TTL`（默认 1200s）边界前后 1 秒 | 边界语义精确 | P0 |
| UT-PERM-006 | 会话隔离 | token A 不能用于验证 token B | 独立 | P0 |
| UT-PERM-007 | **TTL 双来源不一致** | `ADMIN_SESSION_TTL` 环境变量 vs `PUT /api/config/admin_ttl` 写入的 `admin_ttl_minutes` | 断言：修改 config 后**不影响**已生成会话的实际 TTL（会话仍用模块常量）→ 上报设计不一致 | **P0** |
| UT-PERM-008 | `GET /api/admin/session` | 有效 / 无效 / 缺 header | 恒 200，`valid` 分别 `True/False/False` | P0 |
| UT-PERM-009 | **特权接口全量遍历**（`/api/translator/config` PUT、`/api/translator/scene/*/desc\|functions\|function/*` PUT、`/api/translator/registry-path` PUT、`/api/translator/policies/create` POST、`/rename` PUT、`/api/translator/policies/<name>` DELETE、`/api/translator/policy-path-template` PUT、`/api/translator/default-policy` PUT、`/api/config/admin_ttl` PUT、`/api/config/intercept_non_ir_tools` PUT、`/api/config/loop_breaker` PUT、`/api/config/turn_ir_wait_ms` PUT、`/api/intercept/events` DELETE、`/api/docs/public` PUT） | 无 `X-Admin-Session` 或过期 → **403**；有效 → 非 403 | **P0** |
| UT-PERM-010 | `POST /api/translator/policies/switch` | **无特权也应放行**（README 明确「切换免特权」） | 非 403 | P0 |
| UT-PERM-011 | `PUT /api/config` | `key == "admin_key"` | **403**，且 config 表中 `admin_key` 未被修改 | P0 |
| UT-PERM-012 | `PUT /api/config` | `key ∈ {secret_key, subdomain}` 无特权 | 403 | P0 |
| UT-PERM-013 | `PUT /api/config` | 普通 key + 无/错 `X-Auth-Token` | 401 | P0 |
| UT-PERM-014 | `PUT /api/config` | **多 key 混合**：`{"a":1, "admin_key":"x"}`（合法 key 在前） | 断言原子性：当前实现**逐 key 循环写入**，前面的 key 可能已落库才返回 403 → 上报为非原子缺陷 | **P0** |
| UT-PERM-015 | **公开面基线快照** | 断言以下接口**当前无鉴权**：`GET /api/rounds`、`GET /api/rounds/query`、`PUT /api/rounds/update`、`POST /api/rounds*`、`GET /api/stats`、**`POST /api/import`**、`GET /api/db/tables`、`GET|PUT /api/monitor/config`、`POST /api/monitor/start|stop`、`POST /api/monitor/send-test`、`GET /api/attack/*`、`PUT /api/attack/config`、`ANY /api/webhook`、`GET /api/kernel/file` | 固化为快照，任一变化触发用例失败以强制评审；同时**将 `POST /api/import`（无参数直接导入 JSONL）与 `GET /api/kernel/file`（读任意路径）标注为高危未鉴权面** | **P0** |
| UT-PERM-016 | `GET /api/kernel/file` | `path` 指向 `/etc/passwd`、`../../` 穿越 | 断言实测是否存在任意文件读取，作为安全用例上报 | **P0** |
| UT-PERM-017 | CORS | `/api/*` 响应头 `Access-Control-Allow-Origin: *` | 与 `app.py:32` 配置一致（记录为对外暴露风险） | P1 |

#### TS-02B rounds 接口契约

| 用例 ID | 接口 | 场景 | 预期 | 优先级 |
|---|---|---|---|---|
| UT-API-001 | `GET /api/rounds` | 默认参数 | 200；**`limit` 默认 50，而 `@api_doc` 声明 20 → 文档与实现不一致，上报** | P0 |
| UT-API-002 | `GET /api/rounds` | `abnormal=true`（仅字符串 `"true"` 生效）、`abnormal=True`/`1` | 大小写敏感语义锚定 | P0 |
| UT-API-003 | `GET /api/rounds` | `limit` 非数字 / 负数 / 超大 | 断言不 500（或记录 500 为缺陷） | P0 |
| UT-API-004 | `GET /api/rounds/query` | `round_id` 缺失 / 不存在 / 存在 | 400 / 404 / 200 | P0 |
| UT-API-005 | `PUT /api/rounds/update` | 空 body / 缺 `round_id` / 缺 `field` | 400 ×3 | P0 |
| UT-API-006 | `PUT /api/rounds/update` | db 返回 `not_found`/`too_old`/`unsupported`/`error` | 404 / 400 / 400 / 500 | P0 |
| UT-API-007 | `PUT /api/rounds/update` | 成功 | 200 且 `socketio.emit("new_round_info", ...)` 被调用一次 | P0 |
| UT-API-008 | `PUT /api/rounds/update` | `round_update_time_limit` 开关 = false | 透传 `time_limit_enabled=False` 给 db | P0 |
| UT-API-010 | `POST /api/rounds` (`event=start`) | `attack_config` 未携带 | 走 `_read_all_attack_config()` 本地兜底并序列化落库 | P0 |
| UT-API-011 | `POST /api/rounds` (`event=start`) | 携带 `pid_info` / `history` | 原样透传；缺省为 `""` | P0 |
| UT-API-012 | `POST /api/rounds` (`event=start`) | 插入成功 / 重复 round_id 插入失败 | `inserted` 分别 `True`/`False`；失败时**不推送** WebSocket | P0 |
| UT-API-013 | `POST /api/rounds` (`event=start`) | 成功推送 | `emit("new_round_info")` + `broadcast_push({"push_type":"round_start",...})` 各一次 | P0 |
| UT-API-014 | `POST /api/rounds` (`event=end`) | `update_round_end` 成功 | 200，不走 legacy insert | P0 |
| UT-API-015 | `POST /api/rounds` (`event=end`) | `update_round_end` 返回 False | 走 legacy `insert_round` 映射（`round`/`sessionKey`/`action`/`IR`/`abnormal_judge`） | P0 |
| UT-API-016 | `POST /api/rounds` (`event=end`) | `action_json`/`ir_json` 为**非法 JSON 字符串** | legacy 降级为 `[]` / `{}`，不抛异常 | P0 |
| UT-API-017 | `POST /api/rounds` (`event=end`) | legacy 兼容：body 用 `round` 而非 `round_id` | 正确识别 | P0 |
| UT-API-018 | `POST /api/rounds` (`event=end`) | 推送取值来源 | `round_ir_ready`/`round_end` 的 `ir_json`/`action_json` **取自 DB record 而非请求体** | P0 |
| UT-API-019 | `POST /api/rounds` (`event=end`) | 请求体 `ir_json` 为 `""` 或 `"__loading__"` | **不推送** `round_ir_ready`（避免与 worker 重复推送） | P0 |
| UT-API-020 | `POST /api/rounds` (`event=end`) | DB `action_json` 为 `"[]"` | **不推送** `round_end` | P0 |
| UT-API-021 | `POST /api/rounds` | 空 body | 400 | P0 |
| UT-API-022 | `POST /api/rounds/kernel` | 正常 / 缺 round_id / 空 body | 200 / 400 / 400；成功时推送 `round_kernel` + `new_round_info` | P0 |
| UT-API-023 | `POST /api/rounds/kernel` | db 返回 `not_found`/`too_old`/`error` | 404 / 400 / 500 | P0 |
| UT-API-024 | `POST /api/rounds/detection/kernel` | 缺 `judge_result_kernel_md_path` | 400 | P0 |
| UT-API-025 | `POST /api/rounds/detection/kernel` | 成功 | 200，且**异步触发** `request_anomaly_llm_url_v2`（断言线程/函数被调度，需 mock） | P0 |
| UT-API-026 | `POST /api/rounds/detection/syscall` | `syscall_judge` 缺失（`None`） | 400 | P0 |
| UT-API-027 | `POST /api/rounds/detection/syscall` | `syscall_judge` 为 `{}` / `[]` / `""` | **均通过校验**（仅判 `is None`）→ 语义锚定并评估是否为缺陷 | P0 |
| UT-API-028 | 推送时序 | 依次调用 start → ir_ready → end → kernel | `push_type` 序列符合 README「round_start 必须最先」 | P0 |
| UT-API-029 | `broadcast_push` | namespace | 推送到 `/wss/monitor`，事件名 `push` | P0 |
| UT-API-030 | `GET /api/stats` | 空库 | 200，字段齐全不报错 | P1 |

#### TS-02C SQL 控制台鉴权 —— `POST /api/db/query`（安全关键）

| 用例 ID | 场景 | 预期 | 优先级 |
|---|---|---|---|
| UT-API-040 | 空 sql / 纯空白 | 400 | P0 |
| UT-API-041 | `SELECT ...` 无特权 | 200（放行） | P0 |
| UT-API-042 | `select ...` 小写、前导空格/换行/注释 `-- x\nSELECT` | **判定基于 `sql.strip().upper().startswith("SELECT")`** → 前导注释/空行的绕过可能性必须实测并上报 | **P0** |
| UT-API-043 | `INSERT`/`UPDATE`/`DELETE`/`DROP`/`ALTER`/`PRAGMA`/`ATTACH` 无特权 | 403 ×7 | P0 |
| UT-API-044 | `WITH x AS (SELECT 1) SELECT * FROM x` 无特权 | 断言实测：**不以 SELECT 开头 → 被判写操作 403**（合法只读查询误拦），上报可用性缺陷 | P0 |
| UT-API-045 | 含 `CONFIG` 字样：`SELECT * FROM config`、`SELECT 'config'`、`SELECT * FROM rounds WHERE user_query LIKE '%config%'` | 无特权全部 403（**子串匹配会误伤字面量**，上报） | P0 |
| UT-API-046 | `SELECT * FROM sqlite_sequence` 无特权 | 403 | P0 |
| UT-API-047 | 特权会话 + 写操作 | 放行并真实生效 | P0 |
| UT-API-048 | 多语句 `SELECT 1; DROP TABLE rounds` | 断言实测行为（sqlite3 `execute` 单语句限制）并固化 | **P0** |
| UT-API-049 | SQL 语法错误 / 表不存在 | 400 + 错误信息，不泄漏堆栈 | P0 |
| UT-API-050 | `GET /api/db/tables` | 返回全表 + COUNT | 200；确认为无鉴权面 | P1 |

#### TS-02D 翻译器与策略库接口

| 用例 ID | 接口 | 场景 | 预期 | 优先级 |
|---|---|---|---|---|
| UT-API-060 | `POST /api/translator/test` | mock `core.translate` | 200，`is_ui_test=True` 被透传，写入 UI 测试日志 | P0 |
| UT-API-061 | `POST /api/translator/translate` | 内部接口，mock translate | 200；`round_id` 透传；异常时返回错误结构而非 500 | P0 |
| UT-API-062 | `POST /api/translator/level1` / `level2` | 分阶段单测接口 | 分别只调 `level1_classify` / `level2_generate` | P1 |
| UT-API-063 | `POST /api/translator/level2` | 缺 `scenes` 参数 | 400 或明确错误 | P1 |
| UT-API-064 | `GET/PUT /api/translator/config` | 读写 LLM 配置（`api_base_url`/`api_key`/`model`/`temperature`/`timeout`/`json_mode`） | 特权校验 + 落 config 表；**断言响应中 `api_key` 是否脱敏**（若明文返回则上报） | **P0** |
| UT-API-065 | `GET /api/translator/registry` | 正常 / 策略库目录缺失 | 200 全量 / 明确错误不 500 | P0 |
| UT-API-066 | `GET /api/translator/registry-health` | 健康 / `scenes.json` 缺失 / `tools/` 缺失 | `healthy` 标志正确 | P0 |
| UT-API-067 | `GET/PUT /api/translator/registry-path` | 路径不以 `policy_registry` 结尾 / 不存在 / 合法 | 400 / 400 / 200 | P0 |
| UT-API-068 | `GET /api/translator/scene/<name>` | 存在 / 不存在 / name 含 `../` | 200 / 404 / 拒绝穿越 | P0 |
| UT-API-069 | `PUT /api/translator/scene/<name>/desc` | 特权 + 正常 | 落盘 `scenes.json` 且不破坏其他场景 | P0 |
| UT-API-070 | `PUT /api/translator/scene/<name>/functions` | 增 / 删 / 非法 JSON 结构 | 正确写入 / 400 | P0 |
| UT-API-071 | `PUT /api/translator/scene/<name>/function/<func>` | 修改单函数定义（含 `params`/`constraint_spec`） | 精确更新 | P0 |
| UT-API-072 | `GET /api/translator/policies` | —— | 返回 `template`/`current`/`resolved_path`/`healthy`/`policies[]` | P0 |
| UT-API-073 | `POST /api/translator/policies/switch` | 合法 / 非法名 / 目录无效 | 200 / 400 / 400，并触发热重载 | P0 |
| UT-API-074 | `POST /api/translator/policies/create` | 空骨架 / `from` 复制 / 已存在 | 200 / 200 / 400 | P0 |
| UT-API-075 | `PUT /api/translator/policies/rename` | 重命名当前生效 Policy | 自动同步切换（`switched=True`） | P0 |
| UT-API-076 | `DELETE /api/translator/policies/<name>` | 删当前生效 / 删最后一个有效 / 正常 | 400 / 400 / 200 | P0 |
| UT-API-077 | `PUT /api/translator/policy-path-template` | 缺 `{policy}` / 不以 `policy_registry` 结尾 / 父目录不存在 / 合法 | 400 ×3 / 200 | P0 |
| UT-API-078 | `GET/PUT /api/translator/prompts` | 读写 Level-1/Level-2 提示词 | 落 config 表 | P1 |
| UT-API-079 | `POST /api/translator/prompts/preview` | 渲染预览 | 返回填充后的完整提示词 | P1 |
| UT-API-080 | `POST /api/translator/prompts/reset` | 重置 | 恢复默认模板 | P1 |
| UT-API-081 | `GET/PUT /api/translator/default-policy` | 写入后经 normalize + validate 存储；写入非法 IR | 200 / 400 | P0 |
| UT-API-082 | `GET /api/translator/logs` | 分页 + 类型/场景筛选 | 200 | P1 |

#### TS-02E 安全拦截与 turn-ir 长轮询（README 核心能力）

| 用例 ID | 被测 | 场景 | 预期 | 优先级 |
|---|---|---|---|---|
| UT-API-090 | `_normalize_user_query` | 含 `Sender metadata` / `[时间戳]` 前缀 / 多空白 | `_SENDER_META_RE` 与 `_TS_PREFIX_RE` 正确剥离，归一后可作缓存 key | P0 |
| UT-API-091 | `_extract_allowed_tools_from_ir` | 标准 IR / 空 IR / 无 tool 对象 / 嵌套 functions | 返回去重工具名列表 / `[]` | P0 |
| UT-API-092 | `_turn_ir_get_or_create_event` | 同 key 并发两次 | 返回同一 `Event` 对象（`_TURN_IR_LOCK` 保护） | P0 |
| UT-API-093 | `_turn_ir_publish_translation` | 发布后等待者被唤醒 | Event set，缓存写入 | P0 |
| UT-API-094 | turn-ir 缓存容量 | 写入超过 `_TURN_IR_MAX_ENTRIES = 256` | 有淘汰机制，不无限增长 | P0 |
| UT-API-095 | `_turn_ir_reset_for_new_round` | 新 round 到来 | 旧 turn 缓存与 Event 被清理 | P0 |
| UT-API-096 | `POST /api/translator/turn-ir` | 缓存命中 | 立即返回 `allowed_tools`，不调 translate | P0 |
| UT-API-097 | `POST /api/translator/turn-ir` | 缓存未命中但在等待窗内被 publish | 长轮询被唤醒后返回 | P0 |
| UT-API-098 | `POST /api/translator/turn-ir` | **超时** → fallback 调一次 translate 成功 | 返回该结果（README 兜底逻辑） | P0 |
| UT-API-099 | `POST /api/translator/turn-ir` | 超时 + fallback 也失败 | **放行**（返回允许）并通过 `_record_turn_ir_timeout_event` 记录 `ir_timeout` 事件 | P0 |
| UT-API-100 | `_get_turn_ir_wait_ms_config` | 未配置 / 合法 / 越界 | 默认 `300_000`；夹取到 `[5_000, 1_800_000]` | P0 |
| UT-API-101 | `PUT /api/config/turn_ir_wait_ms` | `4_999` / `5_000` / `1_800_000` / `1_800_001` / 非数字 | 边界校验正确，非法 400（不得 500） | P0 |
| UT-API-102 | `_backfill_round_ir` | turn-ir 翻译结果回填到已存在的 round | 更新 `ir_json` 且遵守防覆盖规则 | P0 |
| UT-API-103 | `_backfill_round_ir` | round 尚不存在 | 静默跳过，不抛异常 | P0 |
| UT-API-104 | `GET/PUT /api/config/intercept_non_ir_tools` | 开关读写（特权） | 落 config 表；类型归一为 `"true"/"false"` | P0 |
| UT-API-105 | `GET/PUT /api/config/loop_breaker` | 阈值默认 3 / 非法值 / 关闭 | 校验与落库正确 | P0 |
| UT-API-106 | `POST /api/intercept/events` | 三类事件 `ir_tool_block` / `ir_loop_break` / `ir_timeout` | 入库 + `emit("intercept_event")` + `broadcast_push` | P0 |
| UT-API-107 | `POST /api/intercept/events` | 缺 `type` / 未知 type / 空 body | 400 或明确降级（锚定实测） | P0 |
| UT-API-108 | `_row_to_intercept_event` | 含 `round_id`/`note` 迁移列的行 / 列缺失的旧行 | 字段映射正确，缺列不抛异常 | P0 |
| UT-API-109 | `GET /api/intercept/events` | 分页 + 筛选 | 200 | P1 |
| UT-API-110 | `DELETE /api/intercept/events` | 无特权 / 特权 | 403 / 200 且清空 | P0 |

#### TS-02F 模拟攻击配置与 webhook

| 用例 ID | 被测 | 场景 | 预期 | 优先级 |
|---|---|---|---|---|
| UT-API-120 | `ATTACK_GROUPS` 常量 | 分组定义 | 覆盖 `tool_injection`（network/filepath/syscall）与 `runtime_tamper`（replace/insert） | P0 |
| UT-API-121 | `_read_attack_group` / `_read_all_attack_config` / `_read_attack_inject_config` | config 表中 `attack.inject.<item>.enabled` + `.value` 成对读取 | 结构为 `{"tool_injection": {...}}`；缺失项默认 `enabled=false, value=""` | P0 |
| UT-API-122 | `PUT /api/attack/config` | 逐项开关 + 内容写入 | 每项写两条 config 记录 | P0 |
| UT-API-123 | `PUT /api/attack/config` | 未知 item / `enabled` 非布尔 | 忽略或明确 400（锚定实测） | P0 |
| UT-API-124 | `GET /api/attack/tool-config` | 不传 `key` | 返回全部工具注入配置 | P0 |
| UT-API-125 | `GET /api/attack/tool-config` | `key=tool_injection.filepath` 与短名 `filepath` | 两种写法等价，返回 `{key, enabled, value}` | P0 |
| UT-API-126 | `GET /api/attack/tool-config` | 未知 key | **404**（README 明确约定） | P0 |
| UT-API-127 | `GET /api/attack/rules` | 读取 `backend/static/rule_test_atk.json`（143 条规则） | 每条含 `rule_id`/`sequence`/`sequence_list`/`note`/`score`/`source` | P0 |
| UT-API-128 | `GET /api/attack/rules` | 规则文件缺失 / 内容非法 JSON | 明确错误不 500 | P0 |
| UT-API-129 | `GET /api/attack/rules` | 默认 `rule_id` `DT异常序列_003` 存在性 | 可被检索到（sys_probe 默认值契约） | P0 |
| UT-API-130 | `ANY /api/webhook` | 7 种 HTTP 方法（GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS） | 全部 200 并落 `attack_messages`（含 `request_method`） | P0 |
| UT-API-131 | `GET/DELETE /api/attack/messages` | 列表 + 清空 | 200 | P1 |
| UT-API-132 | `_get_webhook_urls` / `_send_webhook` | 未配置 / 多 URL / 目标不可达 / 超时 5s | 不阻塞主流程，异常被吞（需 mock 网络） | P0 |
| UT-API-133 | `GET/PUT /api/config/webhook` | 读写 webhook 配置 | 语义正确 | P1 |
| UT-API-140 | `GET/PUT /api/monitor/config` | **`MONITOR_CONF_KEYS` 白名单**共 11 项（`gateway_log_path`/`openclaw_root`/`use_gateway`/`tool_trace_enabled`/`anomaly_llm_url_v2`/`anomaly_llm_base_prompt`/`anomaly_llm_system_prompt`/`anomaly_llm_max_tokens`/`anomaly_llm_skill_prompt`/`anomaly_llm_tool_compress`/`anomaly_llm_tool_compress_max`） | 白名单内可写；**白名单外的 key 被拒绝**（README 承诺「严格校验」） | **P0** |
| UT-API-141 | `GET /api/monitor/config` | 路径有效性检测 | 返回 `path_status`；不存在路径标记无效 | P0 |
| UT-API-142 | `POST /api/monitor/start` | 未配 `openclaw_root` / 已在运行 / 正常（mock orchestrator） | 明确错误 / 幂等 / 200 | P0 |
| UT-API-143 | `POST /api/monitor/stop` / `GET /api/monitor/status` | 未启动时 stop、状态查询 | 不抛异常，状态字段正确 | P0 |
| UT-API-144 | `POST /api/monitor/send-test` | 回放推送 | 自动补 `is_mock: true` 与当前 `push_time`，推送到 `/wss/monitor` | P0 |
| UT-API-145 | `GET/PUT /api/config/navigator` | JSON 配置读写 / 非法 JSON | 200 / 400 | P1 |
| UT-API-146 | `GET/PUT /api/config/round_update_time_limit` | 开关读写 | 落库并被 rounds 更新接口读取 | P0 |
| UT-API-147 | 异常分析对话接口族（`/api/monitor/anomaly-chats` CRUD、`/anomaly-chat-from-round`、`/anomaly-round-seed`、`/anomaly-llm-chat`、`/anomaly-llm-skill`、`/anomaly-llm-test-v2`） | mock LLM | 会话增删改查、seed 构造、清空重置为默认问候语 | P1 |
| UT-API-148 | `_simplify_ir_json` / `_simplify_action_json` / `_simplify_resource_facts` / `_simplify_judge` / `_simplify_syscall_judge` / `_simplify_kernel_judge_from_path` | 完整 / 缺字段 / 非法 JSON / 文件不存在 | 均降级返回，不抛异常（喂给小异的上下文构造不能崩） | P0 |
| UT-API-149 | `_try_json` / `_raw_or_json` / `_read_file_text` | 非法 JSON / 大文件 / 不存在 / 无权限 | 安全降级 | P0 |
| UT-API-150 | `_build_round_chat_seed` | 完整 round 行 | 生成的消息序列结构合法，且不含超长未截断内容 | P1 |
| UT-API-151 | `request_anomaly_llm_url_v2` | `anomaly_llm_url_v2` 未配置 | **不调用大模型**，直接返回（README 明确） | P0 |
| UT-API-152 | `request_anomaly_llm_url_v2` | mock LLM 返回 / 超时 / 非 200 | 结果写 `anomaly_llm_v2_judge_res`；异常被吞不影响上报链路 | P0 |

---

### TS-03 IR 翻译核心 —— `auditor/translator/core.py`（P0）

**依赖隔离**：`no_llm` autouse 阻断网络；`call_llm` 直接 mock；`REGISTRY_DIR` + `reload_registry()` 指向 `tests/data` 微型策略库。

| 用例 ID | 被测 | 场景 | 预期 | 优先级 |
|---|---|---|---|---|
| UT-TR-001 | `_get_config` | key 存在 / 缺失 / DB 异常 | 值 / 默认 / 默认（不抛） | P0 |
| UT-TR-002 | `_get_registry_dir` | 配置了 `registry_path` / 未配置 | 配置值 / `_DEFAULT_REGISTRY_DIR`（`policies/default/policy_registry`） | P0 |
| UT-TR-003 | `load_scene_registry` / `load_tool_registry` | 正常 / `scenes.json` 缺失 / `tools/` 空 / 单个 tool json 非法 | 正常加载；缺失与非法**降级为空而不抛**（否则 import 即崩） | P0 |
| UT-TR-004 | `reload_registry` | 切换 `REGISTRY_DIR` 后调用 | 模块级 `SCENE_REGISTRY`/`TOOL_REGISTRY` 被刷新（README「热重载无需重启」） | P0 |
| UT-TR-005 | `get_llm_config` | 全部字段默认值 + config 覆盖 | `api_base_url`/`api_key`/`model`/`temperature`/`timeout`/`json_mode` 正确合并 | P0 |
| UT-TR-006 | `call_llm` | mock HTTP 200 正常 / 401 / 超时 / 连接失败 / 响应缺 `choices` | 分别返回内容或明确错误，**不抛未捕获异常** | P0 |
| UT-TR-007 | `call_llm` | `json_mode=True` | 请求体带 `response_format` | P1 |
| UT-TR-008 | **`_extract_json`** | 纯 JSON / ```json 围栏 / 前后有解释性文字 / 多个 JSON 块 / 单引号 / 尾随逗号 / 完全无 JSON | 逐形态断言提取结果；无 JSON 时返回空 dict 不抛异常（LLM 输出鲁棒性关键） | **P0** |
| UT-TR-009 | `_get_prompt` | config 有自定义 / 为空 → 默认 | 正确回退 | P0 |
| UT-TR-010 | `_scene_list_for_prompt` | 15 个场景注册表 | 生成的场景清单文本包含全部场景名与描述 | P0 |
| UT-TR-011 | `level1_classify` | mock LLM 返回合法场景列表 | `(scenes, meta)`；场景经注册表校验过滤未知项 | P0 |
| UT-TR-012 | `level1_classify` | LLM 返回未知场景 / 空列表 / 非列表结构 | 过滤 / 空 / 降级，不抛异常 | P0 |
| UT-TR-013 | `_selected_registry_for_prompt` | 选中 1/多/未知场景 | 仅拼接选中场景的函数定义 | P0 |
| UT-TR-014 | `level2_generate` | mock LLM 返回合法 `subject/objects` | `(ir, meta)` | P0 |
| UT-TR-015 | `_static_spec` | `param_def` 含 `constraint_spec` / 缺失 | 静态约束展开正确 | P1 |
| UT-TR-016 | `normalize_ir` | 缺 `policies` / `objects` 为单对象 / 字段别名 / 大小写 | 统一为标准结构 | P0 |
| UT-TR-017 | `normalize_ir` | 幂等性：连续两次 normalize | 结果相同 | P0 |
| UT-TR-018 | **`validate_ir`** | `policies` 缺失 / 为空数组 | `ok=False` + 明确 error（README 校验项 1） | P0 |
| UT-TR-019 | `validate_ir` | `subject` 不是已知场景 | error（校验项 2） | P0 |
| UT-TR-020 | `validate_ir` | tool 对象 `identifier` 不在注册表 | error（校验项 3） | P0 |
| UT-TR-021 | `validate_ir` | `params` 参数名非法 | error（校验项 4） | P0 |
| UT-TR-022 | `validate_ir` | file 对象缺 `identifier` 或 `actions` | error（校验项 5） | P0 |
| UT-TR-023 | `validate_ir` | 完全合法 IR | `ok=True`、`errors=[]`；`warnings` 语义锚定 | P0 |
| UT-TR-024 | `ValidationReport` | dataclass 字段与序列化 | 可 JSON 化供前端展示 | P1 |
| UT-TR-025 | `translate` | 完整两阶段成功 | 返回含 `level1`/`level2`/`validation`/`query`/`round_id` 的结构 | P0 |
| UT-TR-026 | `translate` | **分阶段 DB 写入**（README 关键流程） | 断言调用序列：`insert_translation_log_pending` → `update_translation_log_level1` → 最终 upsert，**共 3 次 DB 交互** | **P0** |
| UT-TR-027 | `translate` | `on_level1_done` 回调 | Level-1 完成后立即被调用一次 | P0 |
| UT-TR-028 | `translate` | Level-1 失败 / Level-2 失败 | 明确错误结构；不写入半成品 IR；必要时回退默认策略 | P0 |
| UT-TR-029 | `translate` | `is_ui_test=True` | 日志标记 `is_ui_test=1`，不污染真实 round | P0 |
| UT-TR-030 | `normalize_and_validate` | 合法 / 非法 IR | 组合调用结果正确（默认策略保存路径复用） | P0 |
| UT-TR-031 | `translate` | 空 query / 超长 query / 中文+emoji | 不抛异常 | P1 |

---

### TS-04 多策略库管理 —— `auditor/translator/policy_manager.py`（P0）

**依赖隔离**：monkeypatch `_cfg`/`_set_cfg` 为内存字典；`policy_root` fixture 造真实目录；monkeypatch `_reload` 为计数 spy。

| 用例 ID | 被测 | 场景 | 预期 | 优先级 |
|---|---|---|---|---|
| UT-PM-001 | `POLICY_NAME_RE` | `default`、`ops-1`、`a_b`、64 字符 / 65 字符、空串、`../x`、`a/b`、`中文`、`a.b` | 前 4 通过；后 6 拒绝（**路径穿越防线**） | **P0** |
| UT-PM-002 | `get_template` | 未配置 / 配置为空白串 / 自定义 | 回退 `_DEFAULT_TEMPLATE`；自定义生效 | P0 |
| UT-PM-003 | `get_current_policy` | 未配置 / 空白 / 自定义 | 回退 `"default"` | P0 |
| UT-PM-004 | `resolve_registry_path` | 传入 policy / 不传（用当前） / 传空白 | `{policy}` 正确替换；空白回退 default | P0 |
| UT-PM-005 | `_template_parts` | 含 `{policy}` 中段 / 结尾 / **不含 `{policy}`** | `(root, suffix)` / `(root, "")` / `(None, "")` | P0 |
| UT-PM-006 | `_policy_dir_of` / `_policy_container_dir_of` | 标准模板 | 分别指向 `<root>/<name>/policy_registry` 与 `<root>/<name>`（删除/重命名必须作用于容器层） | P0 |
| UT-PM-007 | `_is_valid_registry` | 齐全 / 缺 `scenes.json` / 缺 `tools/` / 路径是文件 / 不存在 | `True` / `False` ×4 | P0 |
| UT-PM-008 | `_count_scenes` | 合法 dict / 非 dict（list） / 非法 JSON / 文件缺失 | N / 0 / 0 / 0 | P0 |
| UT-PM-009 | `switch_policy` | 合法且有效 | `(200, ok)`，写 `current_policy` + `registry_path`，**`_reload()` 被调用一次** | P0 |
| UT-PM-010 | `switch_policy` | 非法名 / 目录无效 | 400 + 中文错误文案，**不写任何配置** | P0 |
| UT-PM-011 | `create_policy` | 空骨架 | 建 `tools/` + 空 `scenes.json`（`{}`），返回 `scenes=0` | P0 |
| UT-PM-012 | `create_policy` | `src` 复制自有效 Policy | `copytree` 成功，场景数与源一致 | P0 |
| UT-PM-013 | `create_policy` | 目标已存在 / 源名非法 / 源无效 | 400 ×3 | P0 |
| UT-PM-014 | `create_policy` | 磁盘异常（mock `mkdir` 抛错） | 500 + 错误文案，不留半成品（副作用锚定） | P0 |
| UT-PM-015 | `rename_policy` | 正常重命名非当前 Policy | 容器目录被 move，`switched=False` | P0 |
| UT-PM-016 | `rename_policy` | 重命名**当前生效** Policy | 自动同步 `current_policy` 与 `registry_path`，`switched=True`（README 承诺） | P0 |
| UT-PM-017 | `rename_policy` | 新名非法 / 源无效 / 目标已存在 / move 失败 | 400/400/400/500 | P0 |
| UT-PM-018 | `delete_policy` | 删除当前生效 Policy | 400「不能删除当前正在使用的 Policy」 | P0 |
| UT-PM-019 | `delete_policy` | 仅剩 1 个有效 Policy 时删它 | 400「至少需保留一个有效 Policy」 | P0 |
| UT-PM-020 | `delete_policy` | 删除**无效空壳目录**（幽灵 Policy），即使有效 Policy 只剩 1 个 | **允许删除**（代码特意放行） | P0 |
| UT-PM-021 | `delete_policy` | 名不合法 / 目录不存在 / rmtree 失败 | 400/400/500 | P0 |
| UT-PM-022 | `delete_policy` | 成功后 | 容器目录整体消失（无残留空目录） | P0 |
| UT-PM-023 | `set_template` | 空 / 缺 `{policy}` / 不以 `policy_registry` 结尾 / 父目录不存在 | 400 ×4，错误文案逐一断言 | P0 |
| UT-PM-024 | `set_template` | 合法且解析后有效 | 写模板 + 同步 `registry_path` + 热重载，`applied=True` | P0 |
| UT-PM-025 | `set_template` | 合法但解析后无效（当前 Policy 目录不存在） | `applied=False`，**不覆盖** `registry_path` | P0 |
| UT-PM-026 | `list_policies` | 多 Policy（含有效/无效混合） | 列表含 `name`/`path`/`scenes`/`healthy`；顶层含 `template`/`current`/`resolved_path`/`healthy` | P0 |
| UT-PM-027 | `list_policies` | root 不存在 / root 下有普通文件 | `policies=[]` / 文件被跳过 | P0 |
| UT-PM-028 | `sync_registry_path` | 已一致 / 不一致 / 无效路径 | `False` / `True`+写入+重载 / `False` | P0 |
| UT-PM-029 | `_reload` | `core.reload_registry` 抛异常 | 双路 import 兜底，最终静默不抛 | P0 |
| UT-PM-030 | 真实策略库一致性 | 实际仓库中 `default` 与 `ops` 两套 | 两套 `scenes.json` 的**场景集合相同**（README 承诺「各套场景集合相同」），15 个工具 json 文件名一致 | P0 |

### TS-08 进程与安全上下文采集 —— `auditor/monitor/proc_info.py`（P0）

**依赖隔离**：monkeypatch `proc_info.PROC` 指向 `tmp_path/"proc"`；用 `fake_proc` 工厂生成 `<pid>/{cmdline,comm,status,stat,cwd,exe,root,cgroup,attr/*,ns/*,io,fd/}`；`pwd`/`grp` 解析用 monkeypatch。

| 用例 ID | 被测 | 场景 | 预期 | 优先级 |
|---|---|---|---|---|
| UT-PI-001 | `_safe_read_text` | 正常 / `FileNotFoundError` / `PermissionError` / 超 `max_bytes=65536` | 内容 / `None` / `None` / 截断（best-effort 契约） | P0 |
| UT-PI-002 | `_safe_readlink` | 正常软链 / 不存在 / 无权限 | 目标 / `None` / `None` | P0 |
| UT-PI-003 | `_parse_kb` | `"1234 kB"` / `"0 kB"` / `None` / 乱码 | `1234` / `0` / `None` / `None` | P0 |
| UT-PI-004 | `_try_int` | `"12"` / `" 12 "` / `"a"` / `None` | `12`/`12`/`None`/`None` | P0 |
| UT-PI-005 | `_read_status_kv` | 完整 status / 空文件 / 缺文件 | dict / `{}` / `{}` | P0 |
| UT-PI-006 | `_read_attr_dir` | `attr/{current,exec,prev,fscreate,keycreate,sockcreate}` 六项齐全 / 部分缺失 / 值带 `\x00` | 六键映射，缺失为 `None`，NUL 被清理（SELinux 与 AppArmor 同时覆盖） | P0 |
| UT-PI-007 | `_read_starttime_ticks` | 标准 `stat` 行（**comm 含空格与括号**，如 `(tmux: server)`） | 正确定位第 22 字段，不被 comm 中的空格/括号干扰 | **P0** |
| UT-PI-008 | `_starttime_dict` | 合法 ticks | 返回 `{clock_ticks, epoch, iso}`，ISO 精确到秒（freezegun 固定 boot time） | P0 |
| UT-PI-009 | `_read_cmdline` | NUL 分隔多参数 / 空 cmdline（内核线程） / 尾随 NUL | `(argv, cmdline)`；空时 `([], None)` | P0 |
| UT-PI-010 | `_read_comm` | 正常 / 15 字符截断名（如 `openclaw-gatewa`） | 原样返回（README 示例值） | P0 |
| UT-PI-011 | **`_decode_caps`** | `"0000003fffffffff"`（全量）/ `"0000000000000000"` / `"0000000000200000"`（单 `CAP_SYS_ADMIN`）/ `None` / 非 hex | 解码为 cap 名列表，**全量应为 41 项**；空/异常返回 `[]` | **P0** |
| UT-PI-012 | `_detect_container` | docker / kubernetes / cri-o / podman / containerd / lxc 六种 cgroup 文本 + 宿主机 | 逐一识别；宿主机返回 `None` | P0 |
| UT-PI-013 | `_detect_container` | `root_link` 指向非 `/`（chroot） | 识别逻辑锚定 | P1 |
| UT-PI-014 | `_uid_to_name` / `_gid_to_name` | 存在 / 不存在（`KeyError`） | 名称 / `None` | P0 |
| UT-PI-015 | `_parse_id_quartet` | `"0\t0\t0\t0"` 四元组 / 三元组 / `None` | 解析为 real/effective/saved/fs + 名称；异常返回 `None` | P0 |
| UT-PI-016 | **`collect_pid_info`** | 完整伪进程 | 断言七大类字段齐全：identity（pid/ppid/tgid/comm/cmdline/argv/exe/cwd/root）、credentials（uid/gid 四元组 + groups + **loginuid** + **audit_session_id**）、resources（state/threads/vm_*/num_fds/io）、capabilities（5 组 + 原始 hex）、sandbox（seccomp/no_new_privs）、`security_labels`、isolation（**9~10 个 namespace inode** + cgroups + container）、env 白名单、start_time、fds | **P0** |
| UT-PI-017 | `collect_pid_info` | `SECCOMP_MODES` 映射 `"0"/"1"/"2"/缺失` | `disabled`/`strict`/`filter`/`None` | P0 |
| UT-PI-018 | **`collect_pid_info` 环境变量白名单** | 伪 `environ` 含 `PATH`/`USER`/`HOME`/`LANG`/`CONTAINER` + `OPENAI_API_KEY`/`TOKEN`/`SECRET` | **仅白名单键出现，密钥类键必须不存在**（README 安全约束：防 token 落 DB） | **P0** |
| UT-PI-019 | `collect_pid_info` | 进程在采集中途消失（目录删除） | 返回部分字段，不抛异常 | P0 |
| UT-PI-020 | `collect_pid_info` | `with_fd_sample=True/False`、`fd_sample_limit=20` | fd 采样最多 20 条；关闭时不含 fd 列表 | P0 |
| UT-PI-021 | `collect_pid_slim` | 同一伪进程 | **仅含** identity + uid + `security_labels` + state（+ `depth`）；字段集合严格小于完整版 | P0 |
| UT-PI-022 | `_list_pids` | 混合数字目录与非数字目录（`self`/`net`/`sys`） | 只返回数字 pid | P0 |
| UT-PI-023 | **`_validate_cached`** | `(pid, ticks)` 存活且 ticks 一致 / pid 存活但 **ticks 变化（PID 复用）** / pid 已消失 / `None` | 复用 / **拒绝复用** / 拒绝 / 拒绝 | **P0** |
| UT-PI-024 | **`_path_under`** | `/root/.openclaw/x` under `/root/.openclaw` → True；**`/root/.openclaw2` under `/root/.openclaw` → 必须 False**；`None`；相对路径；软链 | 前缀误判防护 | **P0** |
| UT-PI-025 | **`_cmdline_match_score`** | argv[0] basename == `openclaw` → **100**；`openclaw-gateway` / `openclaw_x` → **95**；`my-openclaw-run` 子串 → **80**；hint 在 comm 中 → **70**；`argv[1:]` 路径组件含 hint（`/opt/openclaw/main.js`）→ **60**；完全不含 → **0** | 六档评分逐一精确断言（README 评分表） | **P0** |
| UT-PI-026 | `find_openclaw_main_pid` | 有 `cached` 且有效 | `discovery.method == "cached"`，**不扫全量 `/proc`**（可用 spy 断言 `_list_pids` 未被调用） | P0 |
| UT-PI-027 | `find_openclaw_main_pid` | 多候选，其一 `cwd` 在 `openclaw_root` 下 | `cwd_boost` **+20** 生效，选中该候选，`selected_reason` 体现 | P0 |
| UT-PI-028 | **`find_openclaw_main_pid` 黑名单** | 候选 comm 为 `bash`/`sh`/`zsh`/`fish`/`dash`/`ksh`/`csh`/`tmux`/`tmux: server`/`screen`/`sudo`/`su`/`systemd`/`init`/`login`/`sshd`/`agetty`，且 cwd/argv 含 `openclaw` | **全部被排除**，永不被选为主进程 | **P0** |
| UT-PI-029 | **`find_openclaw_main_pid` 排除关键字** | 候选 cmdline 含 `clawavc` / `claw-avc` / `claw_avc` | 被排除（防 ClawAVC 自身被误识别为被监控对象） | **P0** |
| UT-PI-030 | `find_openclaw_main_pid` | 无任何候选 | `method == "no_match"`，返回 `None`，不抛异常 | P0 |
| UT-PI-031 | `find_openclaw_main_pid` | 自定义 `hint_keywords` / 多 hint | 取最高分候选 | P0 |
| UT-PI-032 | `_build_pid_tree` | 多层父子 / 孤儿进程 / ppid=0 | 正确构造 `{ppid: [children]}` | P0 |
| UT-PI-033 | `find_descendants` | 3 层子树，`max_depth=2` | 只返回 2 层，`depth` 字段正确 | P0 |
| UT-PI-034 | `find_descendants` | 子进程数超 `max_count` | 截断到上限 | P0 |
| UT-PI-035 | `find_descendants` | **循环父子引用**（人工构造 ppid 环） | 不无限递归（有访问集合保护） | **P0** |
| UT-PI-036 | `collect_ancestors` | 4 层父链 / 到达 pid 1 / `max_depth=0` | 层数正确，slim 结构 | P0 |
| UT-PI-037 | `find_pids_writing` | fd 指向目标文件 / 无人打开 / `exclude_self=True` | 命中列表 / `[]` / 排除自身 PID | P0 |
| UT-PI-038 | `collect_system_context` | SELinux `enforcing`/`permissive`/`disabled`；AppArmor 启用/禁用；kernel/hostname | 结构正确；**断言不含 ClawAVC 自身 label**（README 安全约束） | **P0** |
| UT-PI-039 | **`collect_for_round`** | 完整流程 | 返回顶层键：`openclaw_root`/`jsonl_path`/`captured_at`/`discovery`/`main`/`ancestors`/`descendants`/`main_selinux_label`/`main_exec_label`/`tool_subprocess_labels`/`system`/`collect_duration_ms` | **P0** |
| UT-PI-040 | `collect_for_round` | `tool_subprocess_labels` shortcut | 每项含 `pid`/`comm`/`cmdline`/`label`，与 `descendants` 一致 | P0 |
| UT-PI-041 | `collect_for_round` | 主进程定位失败 | 仍返回结构完整的字典（`main` 为空/None），带 note，**不抛异常** | P0 |
| UT-PI-042 | `collect_for_round` | 返回值可 `json.dumps(default=str)` | 无不可序列化对象（watcher 直接序列化落库） | P0 |
| UT-PI-043 | `collect_for_round` | `collect_duration_ms` | 为非负数值 | P1 |
| UT-PI-044 | `collect_for_round` | `fd_writer_fallback` 分支 | 命中时输出 `fallback_writers` 字段 | P1 |
| UT-PI-045 | `collect_for_session` | `jsonl_path` 入口 | 结构正确 | P2 |

---

### TS-09 内置监控 —— `auditor/monitor/watcher.py`（P0/P1）

**依赖隔离**：只测纯逻辑与可注入部分；`ir_translate`/`judge`/`collect_for_round`/`report_to_clawavc` 全部 mock；**不启动真实线程**（`MonitorOrchestrator` 用回调手动驱动）；全局 `--timeout`。

#### TS-09A 日志解析与状态机

| 用例 ID | 被测 | 场景 | 预期 | 优先级 |
|---|---|---|---|---|
| UT-WT-001 | `FileTailer.scan_new_lines` | 首次 `from_end=True` / `from_end=False` | 分别跳过历史与读取全量 | P0 |
| UT-WT-002 | `FileTailer` | 追加写入后二次扫描 | 只返回新增行，offset 前进 | P0 |
| UT-WT-003 | `FileTailer` | **文件被轮转**（inode 变化，`(st_dev, st_ino)`） | offset 重置为 0，重新读全量 | P0 |
| UT-WT-004 | `FileTailer` | **文件被截断**（`st_size < pos`） | offset 回 0 | P0 |
| UT-WT-005 | `FileTailer` | 路径不存在 / 是目录 / 无权限 | 跳过该路径，其他路径正常（整块 `except: continue`） | P0 |
| UT-WT-006 | `FileTailer` | 非 UTF-8 字节（`errors="replace"`） | 不抛 `UnicodeDecodeError` | P0 |
| UT-WT-007 | `FileTailer` | 空行 / 仅空白行 | 不 yield | P0 |
| UT-WT-008 | `FileTailer` | **半行写入**（无换行结尾）后补齐 | 语义锚定（当前按 `tell()` 记录，半行可能被切分）→ 若确认为缺陷则上报 | **P0** |
| UT-WT-010 | `parse_line` | OpenClaw `user` 消息 | 产出 `user_inbound` 类事件，`round_id` 取 user message 的 `id` 字段 | P0 |
| UT-WT-011 | `parse_line` | `assistant` + `stopReason=toolUse` / `stop` / `end_turn` | 事件类型正确映射（`EVENT_ALIASES` 表驱动全覆盖） | P0 |
| UT-WT-012 | `parse_line` | `toolResult` 消息 | 产出工具完成事件，携带 tool id | P0 |
| UT-WT-013 | `parse_line` | 非法 JSON 行 / 缺 `type` / 缺 `message` | 返回 `None`，不抛异常 | P0 |
| UT-WT-014 | `parse_line` | `session_key` 从路径推断 | `agents/main/sessions/<uuid>.jsonl` → `agent:main:main` | P0 |
| UT-WT-015 | `parse_line` | `ID_KEYS`/`TOOL_ID_KEYS`/`PROCESS_ID_KEYS`/`SUBAGENT_ID_KEYS` 各键名变体 | ids 正确归集 | P0 |
| UT-WT-016 | `parse_line` | `BLOCKED_PAYLOAD_KEYS` 命中 | 敏感 payload 不进入事件（防泄漏） | P0 |
| UT-WT-017 | `parse_line` | `TEXT_PATTERNS` 正则族 | 文本型事件识别正确 | P1 |
| UT-WT-020 | `RoundLedger.status` | 逐一构造 8 种状态：`FAILED`/`WAITING_TOOL`/`WAITING_PROCESS`/`WAITING_SUBAGENT`/`WAITING_APPROVAL`/`YIELDED`/`RUNNING_AGENT`/`ROUTING_RESPONSE`/`COMPLETED` | **优先级顺序**严格符合实现 | P0 |
| UT-WT-021 | `RoundLedger.is_ended` | `COMPLETED`/`FAILED` vs 其他 | `True`/`False` | P0 |
| UT-WT-022 | `RoundLedger` | `yielded` / `waiting_for_approval` 字段 | 断言全代码路径中**从不被置 True** → 死字段，上报清理 | P1 |
| UT-WT-023 | `RoundStateMachine._start_round` | `round_id` 缺失 | 合成 `round:{session}:{ms}` 格式 | P0 |
| UT-WT-024 | `RoundStateMachine._start_round` | 同 session 已有活跃 round 时来新 round | **旧轮被标记 `failed` 并强制结束**，回调 `on_round_end` 被触发 | P0 |
| UT-WT-025 | `RoundStateMachine._start_round` | `on_round_start` 回调 | 仅在首次触发一次（`start_printed` 幂等） | P0 |
| UT-WT-026 | `RoundStateMachine._start_round` | `source_file` 回填 | 记录首条事件来源文件（供 `proc_info` 的 `jsonl_path`） | P0 |
| UT-WT-027 | **`RoundStateMachine._find_round`** | 四级回退：`round_id` → `parent_id` → `message_to_round` → `active_by_session` | 逐级命中；全不命中 → 事件**被丢弃**（不创建新 round） | P0 |
| UT-WT-028 | `RoundStateMachine.apply` | `user_inbound`/`turn_started` 走 start，其他走 find | 分流正确 | P0 |
| UT-WT-029 | `RoundStateMachine._apply_event` | 工具开始/完成配对，pending 集合增减 | 集合状态正确 | P0 |
| UT-WT-030 | `_apply_event` | 工具完成事件**无法匹配 ID**但 pending **仅剩 1 个** | 兜底清空该项（3 处相同兜底逻辑：tool/process/subagent） | P0 |
| UT-WT-031 | `_apply_event` | `turn_completed` | **一次性清空全部 pending** | P0 |
| UT-WT-032 | `_apply_event` | 乱序事件（先完成后开始） | 不抛异常，状态可解释 | P0 |
| UT-WT-033 | `_merge_ids` | 空 ids 不覆盖；`session_key != "unknown"` 时覆盖 | 合并语义正确 | P0 |
| UT-WT-034 | `RoundStateMachine.check_idle_end` | `ROUTING_RESPONSE` 且 `now - last_event_at >= IDLE_END_SECONDS(5.0)` | 强制 `response_routed=True` 并结束 | P0 |
| UT-WT-035 | `check_idle_end` | 未到 5 秒 / 状态非 ROUTING_RESPONSE | 不结束 | P0 |
| UT-WT-036 | `_maybe_end` | 重复触发 | 幂等（`end_printed`），`on_round_end` 只调一次，`active_by_session` 被清理 | P0 |

#### TS-09B 编排生命周期与网关解析

| 用例 ID | 被测 | 场景 | 预期 | 优先级 |
|---|---|---|---|---|
| UT-WT-050 | 网关日志解析 | 标准 Portkey 结构 `requestOptions[].finalUntransformedRequest.body.messages` | 正确取到 messages / tools | P0 |
| UT-WT-051 | 网关解析 | `user_query` 提取 = **最后一个 `role=user`** 的 content，且清理 Sender metadata | 文案与 README 一致 | P0 |
| UT-WT-052 | 网关解析 | `last_llm_message` 取 `response.preview` | 正确；缺字段时降级为空 | P0 |
| UT-WT-053 | 网关解析 | actions 来自 assistant 的 `tool_calls`（OpenAI 风格）与 `tool_use`（Anthropic 风格） | 两种风格均支持 | P0 |
| UT-WT-054 | 网关解析 | `requestOptions` 为空数组 / 非数组 / 缺失 | 降级不抛异常 | P0 |
| UT-WT-055 | 网关解析 | `arguments` 为 JSON 字符串 / 已是 dict / 非法 JSON | 三态兼容 | P0 |
| UT-WT-056 | 网关日志文件名 | `YYYY-MM-DD.jsonl` 选取当天文件 / 跨天 | 正确定位（freezegun） | P0 |
| UT-WT-057 | action 构建 | `FILE_PARAM_HINTS`（`path`/`file`/`filename`/`filepath` 等）识别资源 | 从工具参数推断出 file 资源 | P0 |
| UT-WT-058 | action 构建 | `COMMAND_ACCESS` 映射表 | 命令 → 访问类型（read/write/execute）正确 | P0 |
| UT-WT-059 | action 构建 | 工具参数含 `command` | 联动 shell 语义分析产出资源清单 | P0 |
| UT-WT-060 | `MonitorOrchestrator.__init__` | 默认 `openclaw_log_root=~/.openclaw`、`gateway_log_path=""` | 状态字典初始化为空，`running=False`，`_main_pid_cache=None` | P0 |
| UT-WT-061 | `_on_round_start` | 调用链 | `collect_for_round(openclaw_root, jsonl_path=r.source_file, cached_main=...)` 参数正确 | P0 |
| UT-WT-062 | `_on_round_start` | 采集成功且含 `main.pid` + `start_time.clock_ticks` | `_main_pid_cache` 被更新为二元组 | P0 |
| UT-WT-063 | `_on_round_start` | 采集缺 `main` 或缺 ticks | 缓存**不更新**（避免污染） | P0 |
| UT-WT-064 | **`_on_round_start`** | `collect_for_round` 抛异常 | 异常被捕获并打印 `[monitor] pid_info ...`，**round_start 上报照常执行**（README 承诺不阻塞） | **P0** |
| UT-WT-065 | `_on_round_start` | 上报体 | 含 `event=start`/`round_id`/`time_start`/`session_key`/`attack_config`/`pid_info`（JSON 字符串）/`history` | P0 |
| UT-WT-066 | `_query_and_ir_worker` | 轮询到 `user_query` | 先上报 `ir_json = LOADING_MARKER("__loading__")`，再调 `ir_translate` 并上报结果 | P0 |
| UT-WT-067 | `_query_and_ir_worker` | 轮询超时未找到 query | 不调用翻译，明确降级 | P0 |
| UT-WT-068 | `_query_and_ir_worker` | `ir_translate` 返回 error | 不上报脏 IR，记录错误 | P0 |
| UT-WT-069 | `_on_round_end` | 等待 worker 完成后再取 IR | 从 `_round_ir_results` 拿到结果 | P0 |
| UT-WT-070 | `_on_round_end` | worker 未完成即超时 | 走降级路径（IR 为空仍完成上报） | P0 |
| UT-WT-071 | `_on_round_end` | 调 `judge(actions, ir)` | 结果文本与分数写入上报体；`judge` 抛异常时被捕获 | P0 |
| UT-WT-072 | `_on_round_end` | 上报体完整性 | 含 `time_end`/`user_query`/`last_llm_message`/`action_json`/`ir_json`/`judge_result`/`overall_score`/`is_abnormal` | P0 |
| UT-WT-073 | `report_to_clawavc` | HTTP 失败 / 超时 / 非 200 | 捕获并打印，不中断监控循环 | P0 |
| UT-WT-074 | 常量契约 | `CLAWAVC_ROUNDS_API`、`POLL_INTERVAL=0.5`、`IDLE_END_SECONDS=5.0`、`DEFAULT_OPENCLAW_LOG_ROOT` | 与文档一致 | P1 |
| UT-WT-075 | 重复 round | 同 `round_id` 二次 start | 幂等（DB `INSERT OR IGNORE` 兜底 + 状态机幂等） | P0 |
| UT-WT-076 | 分数与异常标记 | `overall_score` 与 `is_abnormal` 的换算 | `<= 0.5` → `is_abnormal=1`（README 阈值） | P0 |

---

### TS-10 IR 客户端 —— `auditor/monitor/ir_client.py`（P0）

**依赖隔离**：monkeypatch `urllib.request.urlopen`。

| 用例 ID | 场景 | 预期 | 优先级 |
|---|---|---|---|
| UT-IRC-001 | `query=""` / `query=None` / `query="(not found)"` | 直接返回 `({}, "empty query")`，**不发起 HTTP** | P0 |
| UT-IRC-002 | 响应 `{"ok":true,"data":{...}}` | 返回 `(data, None)` | P0 |
| UT-IRC-003 | 响应 `{"ok":false,"error":"x"}` | 返回 `(整个 parsed, None)` —— **error 不被转成第二个返回值**，语义锚定（调用方需自行判断） | **P0** |
| UT-IRC-004 | 响应为 JSON 数组 / 标量 | 包装为 `{"value": parsed}` | P0 |
| UT-IRC-005 | `HTTPError` 401/500（含 body） | `({}, "HTTP <code>: <body 前 200 字符>")` | P0 |
| UT-IRC-006 | `HTTPError` 无 `fp` | 不抛异常，错误串中 body 为空 | P0 |
| UT-IRC-007 | `URLError` / socket timeout / 连接拒绝 | `({}, str(exc))` | P0 |
| UT-IRC-008 | 响应体为非法 JSON | `({}, <JSONDecodeError 文案>)` | P0 |
| UT-IRC-009 | 请求构造 | method=POST、`Content-Type: application/json`、`User-Agent: ClawAVC-Monitor/1.0`、body 为 `ensure_ascii=False` 的 UTF-8 | 断言请求对象属性 | P0 |
| UT-IRC-010 | 默认参数 | `timeout == 300.0`（5 分钟，适配长链路 LLM）、`base_url == TRANSLATOR_URL`、`use_llm=True` | 与 CLAUDE.md 一致 | P0 |
| UT-IRC-011 | 中文 query | 不被转义为 `\uXXXX`，服务端可读 | P0 |
| UT-IRC-012 | 响应含非 UTF-8 字节 | `errors="replace"` 不抛异常 | P1 |

---

### TS-11 API 文档自动化 —— `api_docs.py`（P1）

| 用例 ID | 被测 | 场景 | 预期 | 优先级 |
|---|---|---|---|---|
| UT-DOC-001 | `api_doc` 装饰器 | 装饰后调用被装饰函数 | **仅打标记，不改变函数行为与返回值** | P0 |
| UT-DOC-002 | `generate_docs` | 假 Flask app + 若干路由 | 反射出全部路由，方法/路径正确 | P0 |
| UT-DOC-003 | `generate_docs` | **元数据优先级** `ENDPOINT_REGISTRY` > `@api_doc` > `docstring` | 三层逐一验证 | P0 |
| UT-DOC-004 | `generate_docs` | 路由无任何元数据 | 从 docstring 提取 summary；无 docstring 时不报错 | P0 |
| UT-DOC-005 | `generate_docs` | `public_only=True` | 只返回 `public: True` 的接口 | P0 |
| UT-DOC-006 | `generate_docs` | 传入 `public_list`（对应 config `api_docs.public_endpoints`） | 动态公开列表覆盖 registry 标记 | P0 |
| UT-DOC-007 | `_infer_category` | `/api/rounds*` / `/api/monitor/*` / `/api/translator/*` / `/api/admin|auth*` / `/api/db/*` / `/api/config*` / `/api/docs*` / 其他 | 分类映射到「数据查询与更新/运行监控/策略翻译/鉴权管理/数据库/配置/文档/其他」 | P0 |
| UT-DOC-008 | `ENDPOINT_REGISTRY` **一致性校验（元测试）** | 遍历 registry 中每个 `"METHOD /path"` | **每条都能在真实 Flask url_map 中找到对应路由**（防文档漂移） | **P0** |
| UT-DOC-009 | 反向一致性 | 遍历真实路由 | 标记为对外公开的接口必须在 registry 中有完整 `params`/`response`（README 承诺零手动维护 + 完整参数表） | P1 |
| UT-DOC-010 | `generate_docs` | 含 `<scene_name>` 等路径参数的路由 | 参数被正确展示 | P1 |
| UT-DOC-011 | 输出可序列化 | `jsonify(generate_docs(app))` | 无异常 | P1 |

---

### TS-12 异常分析技能编排 —— `xy_skill.py`（P1）

**依赖隔离**：mock LLM（含**流式**响应，用生成器伪造 SSE 分片）；`db.get_round_by_id` 用 fixture 行。

| 用例 ID | 被测 | 场景 | 预期 | 优先级 |
|---|---|---|---|---|
| UT-XY-001 | `TOOLS` 常量 | 工具声明 | 每个工具 schema 合法（name/description/parameters），**入参仅需外部已知的 `round_id`**（README 设计要点） | P0 |
| UT-XY-002 | `_handler_round_info` 等 **12 个取证 handler**（`round_info`/`user_query`/`ir_policy`/`action_json`/`judge_result`/`kernel_resource_facts`/`kernel_judge`/`syscall_judge`/`pid_info`/`previous_llm_analysis`/`syscall_sequence`/`kernel_lsm_hook`） | round 存在且字段完整 | 各自返回可读文本 | P0 |
| UT-XY-003 | 同上 12 个 handler | **round 不存在 / 字段为空串 / 字段为非法 JSON / 引用的文件路径不存在** | 全部返回**友好提示文本而非抛异常**（任一崩溃都会中断研判流） | **P0** |
| UT-XY-004 | `_handler_pid_info` | 完整 pid_info JSON | 提取主进程 label 与工具子进程标签摘要 | P0 |
| UT-XY-005 | `_handler_syscall_sequence` / `_handler_kernel_lsm_hook` | JSONL 文件正常 / 超大 / 含畸形行 | 逐行容错 + 体量控制 | P0 |
| UT-XY-006 | `_get_skill_system_prompt` | config 有自定义 `anomaly_llm_skill_prompt` / 为空 | 自定义 / `DEFAULT_SKILL_SYSTEM_PROMPT` | P0 |
| UT-XY-007 | `_get_tool_compress_switch` / `_get_tool_compress_max` | 未配置 / `"true"`/`"false"` / 非法数字 | 默认 `False` / `2000`；非法值回退默认 | P0 |
| UT-XY-008 | `_process_tool_result` | 长度 **恰好等于**阈值 / 超阈值且开关关闭 | 不处理 / **直接截断并标注「（结果过长，已截断）」** | P0 |
| UT-XY-009 | `_process_tool_result` | 超阈值且开关开启 | 调 `_compress_tool_result` 走 LLM 摘要；**压缩失败时回退截断** | P0 |
| UT-XY-010 | `_call_llm_with_tools` | 正常 / 非 200 / 超时 / 响应缺 `choices` | 结果或明确错误，不抛未捕获异常 | P0 |
| UT-XY-011 | `_call_llm_stream` | 分片 SSE（含 `[DONE]`、空行、`data:` 前缀、半个 JSON 分片） | 正确增量解析 | P0 |
| UT-XY-012 | **`_stream_llm_with_tools`** | 流中先出现 tool_call 名、后出现 arguments 分片 | **一解析出工具名即执行该工具并推送结果**（README 核心：实时呈现，不等整轮结束） | **P0** |
| UT-XY-013 | `_stream_llm_with_tools` | 流中同时含文本与 tool_calls | 文本逐字推送；流结束后组装完整 tool_calls 追加到消息历史 | P0 |
| UT-XY-014 | `_stream_llm_with_tools` | 未知工具名 | 跳过或返回错误提示，不中断流 | P0 |
| UT-XY-015 | `_stream_llm_with_tools` | 流中途连接断开 | 已产出内容保留，异常被捕获 | P0 |
| UT-XY-016 | `run_skill_analysis` | 模型连续调用工具超过 `MAX_TOOL_ROUNDS = 6` | **强制终止循环**（防无限取证） | **P0** |
| UT-XY-017 | `run_skill_analysis` | 模型首轮即不调工具 | 直接输出最终研判 | P0 |
| UT-XY-018 | `run_skill_analysis` | `anomaly_llm_url_v2` 未配置 | 明确不调用大模型 | P0 |
| UT-XY-019 | `DEFAULT_MAX_TOKENS = 4096` 与 config `anomaly_llm_max_tokens` | 默认 / 覆盖 / 非法值 | 取值正确 | P1 |
| UT-XY-020 | `_COMPRESS_SYSTEM_PROMPT` / `DEFAULT_SKILL_SYSTEM_PROMPT` | 常量存在且非空 | 契约 | P2 |

---

### TS-13 前端单元测试（P2，本阶段仅奠基）

**工具链**：`vitest` + `@vue/test-utils` + `jsdom`（`frontend/` 已有 Vite 5.4）。

| 用例 ID | 被测 | 场景 | 预期 | 优先级 |
|---|---|---|---|---|
| UT-FE-001 | `src/utils/socket.js` | 连接参数 | namespace 与 `path: "/wss"` 正确；`new_round_info` 监听注册 | P2 |
| UT-FE-002 | `socket.js` | 断线重连 / 重复连接 | 单例语义 | P2 |
| UT-FE-003 | `router/index.js` | auth guard | 未登录访问受保护路由 → 重定向 `/login`；已登录放行 | P2 |
| UT-FE-004 | `monitor/LogsTab.vue` | round upsert 逻辑 | 按 `round_id` 已存在则更新、否则插入；**筛选激活时只更新不插入**（CLAUDE.md 明确） | P2 |
| UT-FE-005 | `LogsTab.vue` | 分数徽章渲染 | `>0.5` 绿（`#00a870`）/ `≤0.5` 橙（`#ED7B2F`）/ `-1` 灰+脉冲 | P2 |
| UT-FE-006 | `LogsTab.vue` | `ir_json === "__loading__"` | 显示 IR 翻译中 loading | P2 |
| UT-FE-007 | `components/PrivilegeDialog.vue` | 验证成功写 `sessionStorage` / 失败提示 | 行为正确 | P2 |
| UT-FE-008 | `components/PrivilegeStatus.vue` | 倒计时递减、到期失效 | 定时器行为（假定时器） | P2 |
| UT-FE-009 | `components/RuleSelectDialog.vue` | 按 `rule_id` / syscall 名搜索、单选生效 | 过滤与选中值正确 | P2 |
| UT-FE-010 | `SecurityPage.vue` | 开启拦截前校验 `monitor_conf.use_gateway !== "true"` | 弹 warning **提示但不阻断**；`destroy()` 被调用 | P2 |
| UT-FE-011 | `ReplayPage.vue` | 回放速度 0.1x~2x 与阶段进度分段（33%/66%/80%/100%） | 计算正确 | P2 |

## 5. 横向专项：内核态与用户态联合权限监察（TS-14，P0）

> 本专项对应团队横向课题，跨模块组合验证，用例落在 `tests/unit/test_joint_permission.py`。

### 5.1 用户态 → 内核态数据贯通

| 用例 ID | 场景 | 预期 | 优先级 |
|---|---|---|---|
| UT-JP-001 | 一条 round 的完整字段贯通：`action_json`(用户态) + `pid_info`(进程安全上下文) + `kernel_syscall_seq` + `kernel_lsm_hook_result` + `kernel_resource_facts` + `judge_result`(用户态判定) + `judge_result_kernel` + `syscall_judge` + `anomaly_llm_v2_judge_res`(联合研判) | 九类字段可同时存在且互不覆盖；任一缺失时其余读取正常 | P0 |
| UT-JP-002 | 推送阶段完整性 | `round_start` → `round_ir_ready` → `round_end` → `round_kernel` 四阶段 payload 字段符合 README 契约 | P0 |
| UT-JP-003 | 内核态三个上报接口的**时间窗一致性** | `/api/rounds/kernel`、`/detection/kernel`、`/detection/syscall` 均受同一 15 分钟窗与 `round_update_time_limit` 开关控制，行为完全一致 | P0 |
| UT-JP-004 | 内核态上报**乱序到达** | 先 `/detection/kernel` 后 `/api/rounds/kernel`；先 kernel 后 end | 均不丢数据、不互相覆盖 | P0 |
| UT-JP-005 | `pid_info` 与 `action_json` 的关联可用性 | `tool_subprocess_labels[].cmdline` 能与 action 中的工具名建立对应（如 `safe_file_reader/server.py` ↔ 文件读工具） | 关联字段存在且非空 | P0 |

### 5.2 权限越权检测能力矩阵（判定引擎 × 攻击场景）

以 README 的两类威胁场景与三类注入配置构造**端到端判定用例**（纯离线，只喂数据不真跑攻击）：

| 用例 ID | 攻击向量 | 构造 | 预期判定 | 优先级 |
|---|---|---|---|---|
| UT-JP-010 | 运行时篡改 - 替换工具（`runtime_tamper.replace`） | IR 只允许 `read`，action 中实际为 `exec` | 工具调用维 violation，`overall_score` 下降至 ≤0.5 | P0 |
| UT-JP-011 | 运行时篡改 - 插入工具（`runtime_tamper.insert`） | action 中多出 IR 外的 `malicious_tool` | 工具调用维 + 轨迹维双 violation | P0 |
| UT-JP-012 | 工具注入 - 固定网络外发（`tool_injection.network`） | 资源事件 `http://malicious.example.com/collect` + `connect` | 资源访问维 violation（network 类型） | P0 |
| UT-JP-013 | 工具注入 - 固定文件访问（`tool_injection.filepath`） | 资源事件 `/root/.ssh/id_rsa` + `read`，IR 仅允许 `/tmp/**` | 资源访问维 violation | P0 |
| UT-JP-014 | 工具注入 - 异常 syscall 序列（`tool_injection.syscall`） | `syscall_judge` 注入 `DT异常序列_003` 判定结果 | 字段正确入库并进入联合研判上下文 | P0 |
| UT-JP-015 | 路径逃逸 | action 路径 `/tmp/../etc/passwd`、`/tmp/./x`、双斜杠 `//tmp//x`、软链目标 | 归一化后正确判定越权（**若未归一化即为漏检缺陷，必须上报**） | **P0** |
| UT-JP-016 | 大小写与编码绕过 | `/TMP/A.TXT`（Linux 大小写敏感）、URL 编码 `%2e%2e%2f`、Unicode 同形字符 | 断言实测行为并固化 | **P0** |
| UT-JP-017 | 参数篡改 | IR 允许 `path=/tmp/a.txt`，action 传 `path=/tmp/a.txt` + 额外 `mode=w` | 因 `_params_match` 为单向子集匹配 → **额外参数被放行**，作为已知风险固化 | **P0** |
| UT-JP-018 | 空 actions 的 IR（fail-open） | IR object 的 `actions=[]`，action 为 `delete` | 因 `_action_allowed` 空集放行 → **判定为合规**，作为已知风险固化 | **P0** |
| UT-JP-019 | 沙箱越界（judge.py demo 场景） | 工具返回 `Path escapes sandbox root` 错误 | 判定链路不因工具执行失败而漏检 | P0 |
| UT-JP-020 | 提权信号 | `pid_info` 中 `capabilities.effective` 含 `CAP_SYS_ADMIN`、`seccomp=disabled`、`no_new_privs=false`、`loginuid` 异常 | 字段可被解析并进入研判上下文 | P0 |

### 5.3 权限模型不变量（Invariant 测试）

| 用例 ID | 不变量 | 验证方式 | 优先级 |
|---|---|---|---|
| UT-JP-030 | **特权密钥永不可通过 API 修改** | 遍历所有写配置接口，尝试写 `admin_key` | 全部拒绝，DB 中值不变 | P0 |
| UT-JP-031 | **入门口令不在任何 GET 响应中出现** | 遍历所有 GET 接口响应体，全文搜索口令值与 `secret_key` | 无泄漏 | P0 |
| UT-JP-032 | **`api_key` 不在任何非特权响应中出现** | 遍历配置类 GET 接口 | 无泄漏或已脱敏 | P0 |
| UT-JP-033 | **`pid_info` 不含敏感环境变量** | 对采集结果全文搜索 `KEY`/`TOKEN`/`SECRET`/`PASSWORD` | 无命中（README 安全约束） | P0 |
| UT-JP-034 | **`pid_info` 不含 ClawAVC 自身 label** | 检查 `system` 与 `main` 字段 | 无 `clawavc_self_label` 类字段 | P0 |
| UT-JP-035 | **特权会话不可跨重启复用** | 重新 import/重建 `_admin_sessions` | 旧 token 失效 | P0 |
| UT-JP-036 | **CLAUDE.md 约束**：不修改 `judge()` 函数本身 | 元测试：对 `judge.py` 中 `judge` 函数源码做哈希快照 | 变更即失败，强制评审 | P1 |

---

## 6. 通用边界与异常矩阵

对**每一个**外部输入入口，至少覆盖下列维度（作为用例设计 checklist，不逐条展开）：

| 维度 | 具体取值 |
|---|---|
| 空值族 | `None`、`""`、`" "`、`[]`、`{}`、`0`、`False` |
| 类型错位 | 期望 dict 给 list / 期望 str 给 int / 期望 list 给标量 |
| JSON 畸形 | 截断 JSON、单引号、尾随逗号、超深嵌套（>50 层）、NaN/Infinity |
| 编码 | 非 UTF-8 字节、BOM、NUL 字符、中文、emoji、RTL 控制符 |
| 体量 | 空文件、1 字节、10 MB 字符串、10 万条数组（性能与内存） |
| 路径 | 相对路径、`..` 穿越、软链、不存在、无权限、目录当文件、超长路径（>4096） |
| 时间 | 边界前后 1 秒、时区差、`NULL`、格式错误、未来时间 |
| 并发 | 同 key 并发写、同 round 并发 start/end |
| 网络（mock） | 200/4xx/5xx、超时、连接拒绝、响应体截断、非 JSON |

---

## 7. 测试须锚定并上报的可疑缺陷清单

> 单元测试的价值之一是**固化现状并暴露风险**。下列问题在代码走查中已定位，测试用例必须覆盖；若确认为缺陷则在阶段三同步提修复单。

| # | 位置 | 问题 | 严重度 | 对应用例 |
|---|---|---|---|---|
| 1 | `db.update_round_field` / `update_kernel_info` / `update_judge_result_kernel` | `created_at` 由 SQLite `CURRENT_TIMESTAMP` 写入（**UTC**），校验用 `datetime.now()`（**本地时区**）→ 东八区下新建记录即被判 `too_old`，15 分钟窗形同关闭/误拦 | **高** | UT-DB-055 |
| 2 | `db.update_kernel_info` | 文件复制与目录创建发生在 `not_found`/`too_old` 校验**之前**；且 `infos_dir` 直接用 `round_id` 拼接，存在路径穿越面 | **高** | UT-DB-064、UT-DB-065 |
| 3 | `app.py` `GET /api/kernel/file` | 无鉴权 + 可指定路径读取文件 | **高** | UT-PERM-016 |
| 4 | `app.py` `POST /api/import` | 无鉴权、无参数即触发历史数据导入 | 中 | UT-PERM-015 |
| 5 | `app.py` `db_query` | 写操作判定仅 `startswith("SELECT")`；`CONFIG`/`SQLITE_SEQUENCE` 用子串匹配 → 既可能被前导注释绕过，也会误伤合法 `WITH ... SELECT` 与含 config 字面量的查询 | **高** | UT-API-042、044、045、048 |
| 6 | `app.py` `update_config` | 多 key 循环写入非原子，非法 key 前的合法 key 已落库 | 中 | UT-PERM-014 |
| 7 | `judge.Resource_Consistency_Check_Layered` | `tool_call` 计数条件依赖 `tool_call_violations[-1]` 的**字符串内容**，前一事件的 violation 会影响后一事件计数 | **高** | UT-JG-109 |
| 8 | `judge._action_allowed` | 空 `actions` 集合 → 放行一切（fail-open） | **高** | UT-JG-014、UT-JP-018 |
| 9 | `judge._params_match` | 单向子集匹配，actual 的额外参数不受约束 | 中 | UT-JG-017、UT-JP-017 |
| 10 | `judge._parse_object` vs `_normalize_actions` | identifier 候选键不对称（后者多支持 `uri`/`endpoint`） | 中 | UT-JG-020、UT-JG-207 |
| 11 | `judge.py` ↔ `resource_consistency_check.py` | 同源分叉双实现，原语已出现差异（RCC 独有 open flags/元数据能力），存在持续漂移风险 | **高** | UT-RCC-001 |
| 12 | `db.py` | `set_config` 重复定义（L1067 / L1320）；`config` 表在 `init_db` 与 `init_config_table` 中重复建表 | 中 | UT-DB-081、UT-DB-082 |
| 13 | `db.update_round_field` | `if field == "is_abnormal"` 为死分支（不在 `UPDATABLE_FIELDS`） | 低 | UT-DB-052 |
| 14 | `db.init_db` | `resource_facts` 重命名迁移分支条件恒假（死代码） | 低 | UT-DB-006 |
| 15 | `watcher.RoundLedger` | `yielded` / `waiting_for_approval` 字段从不被置位 | 低 | UT-WT-022 |
| 16 | `app.py` 会话 TTL | `ADMIN_SESSION_TTL`（环境变量，模块常量）与 config `admin_ttl_minutes` 双来源，改配置不影响实际会话 TTL | 中 | UT-PERM-007 |
| 17 | 文档 vs 实现 | ① 判定实为**四维**（含轨迹一致性），README/CLAUDE.md 写三维；② `verify_secret` 读 `secret_key`，CLAUDE.md 写 `entry_password`；③ `GET /api/rounds` 默认 `limit=50`，`@api_doc` 写 20；④ `ir_client` 默认端点是 `/api/translator/translate`，docstring 写 `/api/translator/test` | 中 | UT-JG-101、UT-DB-084、UT-API-001、UT-IRC-010 |
| 18 | `watcher.FileTailer` | 按 `f.tell()` 记录位点，末尾半行可能被切分为两次读取 | 中 | UT-WT-008 |

---

## 8. 覆盖率目标与验收标准

### 8.1 分模块覆盖率门槛

| 模块 | 行覆盖 | 分支覆盖 | 说明 |
|---|---|---|---|
| `auditor/monitor/judge.py` | ≥ 92% | ≥ 85% | 纯函数，无理由不达标 |
| `auditor/monitor/resource_consistency_check.py` | ≥ 85% | ≥ 78% | 分叉实现，与 judge 共测 |
| `auditor/monitor/shell_command_semantics.py` | ≥ 90% | ≥ 82% | `_analyze_segment` 命令分支多，需表驱动 |
| `auditor/translator/policy_manager.py` | ≥ 92% | ≥ 88% | 逻辑短、分支密，易达标 |
| `auditor/translator/core.py` | ≥ 82% | ≥ 72% | LLM 调用路径全 mock |
| `db.py` | ≥ 85% | ≥ 75% | 排除 `import_from_jsonl` 深路径 |
| `auditor/monitor/proc_info.py` | ≥ 78% | ≥ 68% | 伪 `/proc` 无法覆盖全部内核字段变体 |
| `auditor/monitor/ir_client.py` | 100% | ≥ 95% | 仅 72 行，必须打满 |
| `api_docs.py` | ≥ 80% | ≥ 70% | registry 为数据，主要测 generate |
| `app.py` | ≥ 70% | ≥ 58% | 3263 行、90+ 路由；anomaly LLM 相关路径可放宽 |
| `auditor/monitor/watcher.py` | ≥ 60% | ≥ 50% | 线程与主循环不做单测 |
| `xy_skill.py` | ≥ 65% | ≥ 55% | 流式解析为重点 |
| **整体** | **≥ 75%** | **≥ 65%** | CI 门槛 |

### 8.2 验收标准（Definition of Done）

1. `uv run pytest tests -q` 全绿，**零 skip 无理由**（skip 必须带 `reason` 且列入豁免清单）。
2. `uv run pytest tests -m p0` 在 **60 秒内**跑完（作为 pre-commit 门禁）。
3. 覆盖率达到 8.1 门槛，`--cov-fail-under=75` 生效。
4. 用例**不依赖真实环境**：断网、无 `/proc` 权限、生产 DB 不存在时仍全绿（CI 中以非 root 用户验证一次）。
5. 用例**无副作用**：执行前后 `infos/db/clawAVC.db`、`infos/kernel_infos/`、`logs/`、`auditor/translator/policies/` 的 mtime 与内容不变（加一条 autouse 守卫 fixture 断言）。
6. 第 7 节 18 项可疑缺陷**全部有对应用例覆盖**，且每项已形成「确认为缺陷 / 确认为设计」的书面结论。
7. 新增测试代码不修改任何生产代码逻辑；如需可测性改造（如把模块级常量改为惰性读取），单独提 PR 并附等价性测试。
8. `tests/data/` 中样本已脱敏（评审通过），无真实主机名、路径中的用户名、token、API key。

---

## 9. 落地排期（阶段三内）

| 里程碑 | 内容 | 交付物 | 依赖 |
|---|---|---|---|
| **M1 · 基建 + 判定引擎** | 测试骨架、`conftest.py`、黄金样本；TS-05 / TS-06 / TS-07 全部 P0 | 约 190 条用例，判定引擎覆盖率达标 | 无（零外部依赖，可立即开工） |
| **M2 · 数据层 + 策略库** | TS-01 / TS-04 全部 P0，TS-03 P0 | 约 130 条用例；同步产出缺陷 #1/#2/#12 结论 | M1 的 fixture 基建 |
| **M3 · 接口与权限** | TS-02A~F 的 P0，TS-14 横向专项 | 约 140 条用例；**权限基线快照**成为 CI 强制门禁 | M2 的 `temp_db` |
| **M4 · 采集与监控** | TS-08 / TS-09 / TS-10 / TS-11 的 P0 | 约 110 条用例；伪 `/proc` fixture 可复用 | M1 |
| **M5 · 补齐与收口** | 全部 P1；覆盖率补洞；CI 接入；缺陷结论归档 | 覆盖率报告 + 缺陷清单 + 前端 vitest 骨架（P2 只搭不填） | M1~M4 |

**并行建议**：M1 与 M4 无依赖关系，可双线并行；M3 的权限基线表可在 M1 期间先以声明式数据形式落地评审。

---

## 10. 风险与不可测项

| 风险 | 说明 | 缓解 |
|---|---|---|
| gevent monkey-patch 污染 | `import app` 即全局打补丁，可能使 `tests/unit` 行为异常 | `tests/unit` 与 `tests/api` **分进程执行**（CI 两条命令）；必要时引入 `pytest-forked` |
| 模块级副作用 | `core.py` import 时读策略库、`db.DB_PATH` 固化、`app.py` 建 socketio | 统一在 `conftest` 中提供「先 patch 后 reload」的标准姿势，禁止用例各自发明 |
| Python 3.14 生态 | 部分测试库对 3.14 支持较新 | 先以 `pytest` + 标准库 `unittest.mock` 为主，`freezegun` 若不兼容则改用手写 `time` monkeypatch |
| `/proc` 语义差异 | 不同内核版本字段格式不同（cap 掩码宽度、ns 数量 9 vs 10） | 伪 `/proc` 参数化多套快照；真机验证归入集成测试 |
| LLM 行为不确定 | Level-1/Level-2 输出不稳定 | 单测**只测 `_extract_json` / normalize / validate 的解析与校验能力**，绝不断言 LLM 语义质量 |
| 时间与线程 | watcher 的 join/poll 易导致 flaky | 不测真实线程；`pytest-timeout` 兜底；状态机手动驱动 |
| 生产数据误伤 | 测试若连上 `infos/db/clawAVC.db` 将污染真实审计数据 | autouse 守卫 fixture：断言 `db.DB_PATH` 不等于生产路径，否则**直接 fail** |
| 前端测试缺失 | `frontend/` 无测试基建，56358 个文件（含依赖） | 本阶段仅搭 vitest 骨架 + 4 个纯逻辑用例，组件测试延后 |

---

## 附录 A · 快速开始

```bash
cd /home/hx/jjq/clawAVC/backend

# 1. 安装测试依赖
uv add --dev pytest pytest-cov pytest-mock freezegun pytest-timeout

# 2. 建目录
mkdir -p tests/{unit,api,data/{ir,actions,gateway,openclaw,proc}}
touch tests/__init__.py tests/conftest.py

# 3. 跑第一条（判定引擎，零依赖）
uv run pytest tests/unit/test_judge_primitives.py -v

# 4. CI 两段式执行（避免 gevent 污染）
uv run pytest tests/unit -q --cov=. --cov-report=xml:cov-unit.xml
uv run pytest tests/api  -q --cov=. --cov-append --cov-report=term-missing --cov-fail-under=75
```

## 附录 B · `conftest.py` 守卫 fixture（必须存在）

```python
import pytest, db

PROD_DB = "infos/db/clawAVC.db"

@pytest.fixture(autouse=True)
def _guard_production_db():
    """任何用例触达生产库即失败。"""
    assert PROD_DB not in str(db.DB_PATH), f"测试指向了生产数据库: {db.DB_PATH}"
    yield
```

---

*本大纲基于 README.md、.claude/CLAUDE.md 与 backend 全量代码走查产出；用例编号与优先级可直接作为任务拆分依据。*

