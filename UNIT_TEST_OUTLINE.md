# ClawAVC 测试说明书和测试用例（验证文档）

> 项目：ClawAVC（Claw Access-View Compliance）—— 智能体访问权限合规监察系统
> 阶段：第三阶段 —— 单元测试设计与执行准备（续修稿，非实测验收版）
> 修订日期：2026-09-13
> 代码基线：Git HEAD `ca91e26` 加当前工作树；`backend/xy_skill.py` 有既有修改，`backend/selinux_kb/` 为未跟踪新增模块，不能只用 HEAD 代表本次基线
> 资料基线：沿用原报告设计，本次复核测试基建、数据库导入副作用、知识库入口和工具分发；不宣称重新验证全部业务行为
>
> **证据声明：本次未运行 pytest、Vitest 或性能基准。项目中未找到报告引用的自动化测试套件和执行产物。“待验证行为”属于设计或待复核的历史走查记录，“验收判据”不是执行结论；不得据此推算通过数或覆盖率。**

## 主要内容

- 功能验证 – F (x.1)
- 性能验证 – P (x.2)
- 安全验证 – S (x.3)
- 可靠验证 – R (x.4)

## 0. 测试概述

### 0.1 被测系统与模块划分

| 章节 | 模块 | 被测代码（默认相对 `backend/`） | 验证边界 |
|---|---|---|---|
| 一 | IR 策略翻译与多策略库管理 | `auditor/translator/core.py`、`auditor/translator/policy_manager.py` | 翻译结构、校验与策略切换；LLM 替身 |
| 二 | 行为合规判定引擎 | `auditor/monitor/judge.py`、`resource_consistency_check.py`、`shell_command_semantics.py` | 四维判定、原语、Shell 语义与双实现差异 |
| 三 | 运行时监控与进程安全上下文采集 | `auditor/monitor/watcher.py`、`proc_info.py`、`ir_client.py` | 解析、状态机、伪进程与 HTTP 契约 |
| 四 | 数据服务与接口权限管控 | `db.py`、`app.py`、`api_docs.py` | 临时数据层、接口与鉴权；不启动在线服务 |
| 五 | 内核态与用户态联合权限监察与异常研判 | `xy_skill.py`、`app.py` 拦截接口族、`../frontend/src` | 12 个 round 工具 + 1 个知识库工具、流式编排与前端逻辑 |
| 六 | SELinux 本地知识库解析、构建与检索 | `selinux_kb/parsers.py`、`build_index.py`、`search.py` | 微型语料、临时索引或连接替身 |

### 0.2 目标测试环境与当前状态

| 项 | 目标/约束 | 本次核对状态 |
|---|---|---|
| 操作系统 | Linux；性能基准固定 CPU、内存、内核、文件系统与负载 | 本次为静态核对，正文沿用的 Ubuntu 22.04/内核 5.15 为目标环境，不代表已验证 |
| 运行时 | Python 满足 `requires-python = ">=3.14"`，由 `uv` 锁定依赖 | 要求来自 `backend/pyproject.toml`；实际测试解释器未记录 |
| 后端框架 | pytest、pytest-cov、pytest-mock、freezegun、pytest-timeout；验证 Python 3.14 兼容性后锁定 | 未声明测试依赖组，未找到 `backend/tests/` 与覆盖率配置 |
| 前端 | 受维护且兼容 Vite/Vitest 的 Node；Vue Test Utils 与 jsdom 版本锁定 | 现有 Vite 5.4；未声明 Vitest、配置或 `test:unit` 脚本；原 Node 18 方案需更新 |
| 外部依赖 | 网络、LLM、OpenClaw、真实 `/proc` 均隔离；后台任务受控 | 尚未验证隔离实现 |
| 数据隔离 | 首次导入前隔离 DB、配置、日志与策略目录；每例临时 SQLite | `db.py` 导入即初始化及写入配置；普通 autouse fixture 不能保护收集阶段，见 E.3 |
| 知识库 | 不读取生产索引；构建只在临时目录，检索使用微型只读索引或替身 | 默认索引位于 `infos/selinux_kb/`；本次未访问该索引 |

### 0.3 用例编号与分层规则

| 项 | 规则 |
|---|---|
| 验证点编号 | `F/P/S/R-<模块号>-<序号>`；保留五章编号，第六章新增 8 个验证点 |
| 单元用例编号 | `UT-<域>-<序号>`；保留原有域，新增 `KB`。设计标识不等于 pytest 收集项 |
| 优先级 | P0：隔离、权限、核心判定、工具分发；P1：解析、检索、异常与一致性；P2：前端补充及性能。落地时注册 `p0`、`p1`、`p2`、`performance` 标记 |
| 测试分层 | L1 纯函数；L2 组件；L3 API 契约；L4 伪环境。凡导入真实 `app` 的用例均在独立 API 进程执行 |
| 表驱动约定 | 一个验证点可关联多个参数实例，同一测试可支撑多个验证点，按完整 nodeid 去重统计 |
| 文本口径 | “待验证行为”保存设计预期或待复核历史观察；风险必须复现，不能直接作为已确认缺陷。计划文件与 fixture 均不代表已存在 |

### 0.4 当前结论摘要

| 项 | 内容 |
|---|---|
| 设计验证点 | **98 个**：功能 42 / 性能 16 / 安全 18 / 可靠 22；原 90 个 + 知识库 8 个 |
| 用例规模 | 原五章预算分项合计约 **560**，不是原稿的 520，也不是实收数量；新增 KB/XY 编号见第六章和 G。优先级精确数量待收集 |
| 执行结果 | **未执行，无可核验运行证据**；98 个验证点均待验证。通过/失败/跳过/xfail 数量及通过率均为“未测”，不得填 0% 或 100% |
| 覆盖率 | **未测**；目标整体行覆盖 ≥75%、分支覆盖 ≥65%，分模块目标见 B.2 |
| 本次产出 | 补充知识库与工具分流设计、证据模板、风险闭环、导入隔离前置条件和统一统计口径 |
| 验收状态 | **尚不满足实测验收条件**：测试代码、依赖、隔离、运行产物与风险回归证据待补齐 |
| 范围外 | 真实 LLM 语义质量、OpenClaw 真机联调、WebSocket 系统压测和浏览器 E2E 另行验证 |

### 0.5 续修记录与版本关系

| 项 | 记录 |
|---|---|
| 接续文件 | `UNIT_TEST_OUTLINE.md`；保留中断前五章设计与既有未提交修改 |
| Word 参考文件 | `测试报告_三期提交版.docx` 为知识问答/策略生成/权限专家评测材料；`测试报告_最终版.docx` 为静态权限分析/信息流评估材料。均未检出 ClawAVC 标识，不是本报告的同步导出版，本次不改写 |
| 修订重点 | 清除无证据性能数字与通过结论；更新 13 工具契约；新增知识库 8 项；补全隔离及证据闭环 |
| 实测版条件 | 落实 A/E 后执行，按 H 关联代码基线、原始结果及复核记录，有证据后才更新结论 |

---

## 一、IR 策略翻译与多策略库管理模块

### 1.1 功能验证

验证的基本目标：

1. 【F-1-1】策略注册表加载与热重载功能完备
2. 【F-1-2】Level-1 场景分类功能完备
3. 【F-1-3】Level-2 IR 生成与归一化功能完备
4. 【F-1-4】IR 五项校验规则完备
5. 【F-1-5】两阶段翻译编排与分阶段落库正确
6. 【F-1-6】多策略库增删改查切换功能完备
7. 【F-1-7】策略路径模板配置与解析正确

#### 【F-1-1】策略注册表加载与热重载功能完备

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-1-1 |
| 测试要求 | `load_scene_registry` / `load_tool_registry` 能从 `policy_registry` 目录正确加载场景与工具定义；`reload_registry()` 调用后模块级 `SCENE_REGISTRY` / `TOOL_REGISTRY` 被刷新，实现"热重载无需重启"；`_get_registry_dir` 在未配置时回退 `_DEFAULT_REGISTRY_DIR`。 |
| 主要测试文件 | 被测：`auditor/translator/core.py`；测试脚本：`tests/unit/test_translator_core.py`（UT-TR-001~004）；数据：`tests/data/registry/` 微型策略库 |
| 测试环境 | Ubuntu 22.04，Python 3.14 uv 虚拟环境；monkeypatch `core.REGISTRY_DIR` 后调用 `core.reload_registry()` |
| 测试方法 | 1. 构造微型策略库（`scenes.json` + `tools/*.json`）；2. monkeypatch `REGISTRY_DIR` 指向该目录并调用 `reload_registry()`；3. 断言场景数、工具数与文件内容一致；4. 修改目录内容后再次 `reload_registry()`，断言新内容生效；5. 断言未配置 `registry_path` 时回退默认路径 `policies/default/policy_registry`。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 验证完整/缺 scenes.json/空 tools 三态的加载、热重载和默认回退。首次导入须先完成 A/E 隔离，再设置临时注册表并 reload；对应 fixture 尚未实现，不能宣称约定已落地。 |
| 验收判据（非执行结论） | 注册表加载与热重载功能完备，配置项优先级与默认回退均符合设计；需执行后判定。 |

#### 【F-1-2】Level-1 场景分类功能完备

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-1-2 |
| 测试要求 | `level1_classify` 在 LLM 返回合法场景列表时输出 `(scenes, meta)`；返回的场景须经注册表校验，未知场景被过滤；`_scene_list_for_prompt` 生成的场景清单文本包含全部注册场景名与描述。 |
| 主要测试文件 | 被测：`auditor/translator/core.py`；测试脚本：`tests/unit/test_translator_core.py`（UT-TR-010~013） |
| 测试环境 | 同 F-1-1；`call_llm` 全程 mock，`no_llm` autouse fixture 阻断 `urllib.request.urlopen` 与 `requests.*` |
| 测试方法 | 1. mock `call_llm` 返回合法场景列表，断言 `(scenes, meta)` 结构与内容；2. 分别注入"未知场景""空列表""非列表结构"，断言过滤与降级行为；3. 断言 15 个场景注册表生成的提示词文本包含全部场景名；4. 断言 `_selected_registry_for_prompt` 仅拼接被选中场景的函数定义。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 合法场景全部保留、未知场景被过滤、空列表与非列表结构均降级为空场景集且不抛异常；提示词文本场景清单完整；选中 1 个 / 多个 / 未知场景三种情形下拼接范围正确。 |
| 验收判据（非执行结论） | Level-1 分类链路与场景注册表校验功能完备；需执行后判定。 |

#### 【F-1-3】Level-2 IR 生成与归一化功能完备

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-1-3 |
| 测试要求 | `level2_generate` 在 LLM 返回合法 `subject/objects` 时输出 `(ir, meta)`；`normalize_ir` 能把缺 `policies`、`objects` 为单对象、字段别名、大小写不一致等形态统一为标准结构，且具备幂等性；`_static_spec` 能正确展开 `constraint_spec`。 |
| 主要测试文件 | 被测：`auditor/translator/core.py`；测试脚本：`tests/unit/test_translator_core.py`（UT-TR-014~017、UT-TR-015） |
| 测试环境 | 同 F-1-2 |
| 测试方法 | 1. mock LLM 返回合法 Level-2 结构，断言 IR 主体与对象字段；2. 表驱动喂入 4 类非标准形态，断言归一化结果；3. 对同一 IR 连续两次 `normalize_ir`，断言结果完全相同（幂等）；4. 构造含 / 缺 `constraint_spec` 的 `param_def`，断言静态约束展开。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 四类非标准形态均被统一为 `{"policies":[{...}]}` 标准结构；连续两次归一化结果一致，幂等性成立；`constraint_spec` 缺失时静态约束段为空且不抛异常。 |
| 验收判据（非执行结论） | Level-2 生成与 IR 归一化功能完备，归一化幂等；需执行后判定。 |

#### 【F-1-4】IR 五项校验规则完备

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-1-4 |
| 测试要求 | `validate_ir` 覆盖 README 声明的 5 项校验：①`policies` 缺失或为空数组；②`subject` 非已知场景；③tool 对象 `identifier` 不在工具注册表；④`params` 参数名非法；⑤file 对象缺 `identifier` 或 `actions`。合法 IR 须返回 `ok=True`、`errors=[]`。 |
| 主要测试文件 | 被测：`auditor/translator/core.py`（`validate_ir`、`ValidationReport`）；测试脚本：`tests/unit/test_translator_core.py`（UT-TR-018~024） |
| 测试环境 | 同 F-1-2 |
| 测试方法 | 1. 针对 5 项校验分别构造违规 IR，断言 `ok=False` 且 `errors` 文案命中对应校验项；2. 喂入完全合法 IR，断言 `ok=True`、`errors=[]` 并锚定 `warnings` 语义；3. 断言 `ValidationReport` dataclass 可 JSON 序列化供前端展示。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 5 项校验逐一命中，错误文案可定位到具体 policy 与 object 下标；合法 IR 校验通过且 `warnings` 仅包含非阻断提示；`ValidationReport` 序列化正常。 |
| 验收判据（非执行结论） | IR 校验规则完备，与 README 声明的五项校验一致；需执行后判定。 |

#### 【F-1-5】两阶段翻译编排与分阶段落库正确

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-1-5 |
| 测试要求 | `translate` 完整两阶段成功时返回含 `level1`/`level2`/`validation`/`query`/`round_id` 的结构；DB 交互严格为 3 次：`insert_translation_log_pending` → `update_translation_log_level1` → 最终 upsert；`on_level1_done` 回调在 Level-1 完成后立即触发一次；`is_ui_test=True` 时日志标记且不污染真实 round。 |
| 主要测试文件 | 被测：`auditor/translator/core.py`（`translate`、`normalize_and_validate`）；测试脚本：`tests/unit/test_translator_core.py`（UT-TR-025~030） |
| 测试环境 | 同 F-1-2；`db` 三个写入函数以 `unittest.mock` spy 包裹并计数 |
| 测试方法 | 1. mock 两阶段 LLM 返回，执行 `translate` 并断言返回结构；2. 断言三个 DB 写入函数的调用序列与次数（各 1 次，共 3 次）；3. 注册 `on_level1_done` 回调，断言其在 Level-2 之前被调用一次；4. 分别使 Level-1 / Level-2 失败，断言错误结构且不写入半成品 IR；5. `is_ui_test=True` 时断言日志 `is_ui_test=1`。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 返回结构完整；DB 交互序列与次数精确符合 README 描述的"3 次更新"流程；回调触发时机正确；阶段失败时返回明确错误结构，DB 中不残留半成品 IR；UI 测试标记生效。 |
| 验收判据（非执行结论） | 两阶段翻译编排与分阶段落库流程正确；需执行后判定。 |

#### 【F-1-6】多策略库增删改查切换功能完备

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-1-6 |
| 测试要求 | `create_policy`（空骨架 / 从已有 Policy 复制）、`rename_policy`、`delete_policy`、`switch_policy`、`list_policies` 语义正确；切换与重命名须触发 `_reload()` 热重载；重命名当前生效 Policy 时自动同步 `current_policy` 与 `registry_path`（`switched=True`）。 |
| 主要测试文件 | 被测：`auditor/translator/policy_manager.py`；测试脚本：`tests/unit/test_policy_manager.py`（UT-PM-009~022、UT-PM-026~028） |
| 测试环境 | Ubuntu 22.04，Python 3.14；`policy_root` fixture 在 `tmp_path` 构造 `policies/{default,ops}/policy_registry/{scenes.json,tools/}`；monkeypatch `_cfg`/`_set_cfg` 为内存字典、`_reload` 为计数 spy |
| 测试方法 | 1. 建空骨架 Policy，断言生成 `tools/` 与 `{}` 内容的 `scenes.json`、返回 `scenes=0`；2. 由有效 Policy 复制，断言 `copytree` 成功且场景数与源一致；3. 重命名非当前 / 当前 Policy，断言容器目录 move 与 `switched` 标志；4. `switch_policy` 合法切换，断言写入 `current_policy`+`registry_path` 且 `_reload()` 恰好被调用 1 次；5. `list_policies` 断言列表项含 `name`/`path`/`scenes`/`healthy`，顶层含 `template`/`current`/`resolved_path`/`healthy`；6. `sync_registry_path` 三态验证。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 创建、复制、重命名、切换、列举全部符合预期；容器层（`<root>/<name>`）与注册表层（`.../policy_registry`）区分正确，删除与重命名作用于容器层，成功后无残留空目录；重命名当前生效 Policy 时 `switched=True` 并同步配置；`_reload()` 调用次数精确。 |
| 验收判据（非执行结论） | 多策略库管理功能完备，热重载联动正确；需执行后判定。 |

#### 【F-1-7】策略路径模板配置与解析正确

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-1-7 |
| 测试要求 | `get_template` / `get_current_policy` 在未配置或空白时分别回退 `_DEFAULT_TEMPLATE` 与 `"default"`；`resolve_registry_path` 正确替换 `{policy}`；`_template_parts` 对含 `{policy}` 中段、结尾、不含 `{policy}` 三种模板返回正确 `(root, suffix)`；`set_template` 合法模板生效并同步 `registry_path`。 |
| 主要测试文件 | 被测：`auditor/translator/policy_manager.py`；测试脚本：`tests/unit/test_policy_manager.py`（UT-PM-002~008、UT-PM-023~025） |
| 测试环境 | 同 F-1-6 |
| 测试方法 | 1. 三态（未配置 / 空白串 / 自定义）断言模板与当前 Policy 回退值；2. 表驱动断言 `_template_parts` 对 3 类模板的切分结果；3. 断言 `_policy_dir_of` 与 `_policy_container_dir_of` 分别指向注册表层与容器层；4. `_is_valid_registry` 五态、`_count_scenes` 四态断言；5. `set_template` 合法模板断言 `applied=True` 且 `registry_path` 被同步；合法但解析后无效时断言 `applied=False` 且不覆盖 `registry_path`。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 回退语义与替换结果正确；不含 `{policy}` 的模板返回 `(None, "")` 并被上层拒绝；`_is_valid_registry` 对"缺 `scenes.json`""缺 `tools/`""路径是文件""不存在"四种情况均返回 `False`；`set_template` 在解析后无效时保持 `registry_path` 不变，避免把系统切到不存在的目录。 |
| 验收判据（非执行结论） | 路径模板配置与解析正确，异常模板不会破坏现有生效配置；需执行后判定。 |

### 1.2 性能验证

1. 【P-1-1】策略注册表加载与热重载耗时
2. 【P-1-2】翻译链路本地处理耗时（LLM 之外的全部环节）
3. 【P-1-3】策略库列举与切换耗时

#### 【P-1-1】策略注册表加载与热重载耗时

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | P-1-1 |
| 测试要求 | 15 个场景 + 15 个工具定义的注册表，单次 `load_scene_registry` + `load_tool_registry` 加载耗时应小于 50ms；`reload_registry()` 热重载耗时同量级，不影响在线请求。 |
| 主要测试文件 | 被测：`auditor/translator/core.py`；测试脚本：`tests/unit/test_translator_core.py::test_registry_load_perf` |
| 测试环境 | Ubuntu 22.04，CPU Intel x86_64，内存 16GB；真实仓库 `policies/default/policy_registry` 与 `policies/ops/policy_registry` |
| 测试方法 | 1. 以 `time.perf_counter` 包裹 100 次加载取均值；2. 分别测量冷加载（首次读盘）与热加载（页缓存命中）；3. 断言均值低于阈值。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 冷/热加载与 reload 的耗时均未测；执行后填写样本数、均值、P95 和原始计时位置，按测试要求比较 50ms 目标。不得从首次读取推定操作系统页缓存已清空。 |
| 验收判据（非执行结论） | 注册表加载与热重载耗时可忽略，支持在线频繁切换策略库；需执行后判定。 |

#### 【P-1-2】翻译链路本地处理耗时

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | P-1-2 |
| 测试要求 | 在 LLM 响应被 mock 为即时返回的前提下，`translate` 单轮的本地处理耗时（提示词拼装 + `_extract_json` + `normalize_ir` + `validate_ir` + 3 次 DB 写入）应小于 100ms，确保端到端时延瓶颈仅在 LLM。 |
| 主要测试文件 | 被测：`auditor/translator/core.py`；测试脚本：`tests/unit/test_translator_core.py::test_translate_local_cost` |
| 测试环境 | 同 P-1-1；`temp_db` 临时 SQLite（WAL 模式） |
| 测试方法 | 1. mock `call_llm` 为零延迟返回固定 JSON；2. 连续执行 50 轮 `translate`，记录总耗时与分段耗时；3. 断言单轮均值与 P95。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 本地链路均值、P95 及 DB/提示词/归一化分段耗时均未测；仅按 100ms 本地处理目标验收，不据 mock 结果推断真实 LLM 端到端时延。 |
| 验收判据（非执行结论） | 翻译链路本地处理开销极小，时延主要由外部 LLM 决定；需执行后判定。 |

#### 【P-1-3】策略库列举与切换耗时

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | P-1-3 |
| 测试要求 | 20 套 Policy 规模下 `list_policies` 耗时小于 200ms；`switch_policy`（含 `_reload()` 热重载）耗时小于 100ms。 |
| 主要测试文件 | 被测：`auditor/translator/policy_manager.py`；测试脚本：`tests/unit/test_policy_manager.py::test_list_switch_perf` |
| 测试环境 | 同 P-1-1；`tmp_path` 下构造 20 套 Policy（含 4 套无效空壳） |
| 测试方法 | 1. 批量生成 20 套 Policy 目录；2. 各执行 20 次 `list_policies` 与 `switch_policy`，取均值；3. 断言均值低于阈值。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 列举与切换耗时未测；记录 20 套合成策略的完整/无效比例、缓存状态和计时样本，分别比较 200ms/100ms 目标。 |
| 验收判据（非执行结论） | 策略库列举与切换耗时满足交互式要求；需执行后判定。 |

### 1.3 安全性验证

1. 【S-1-1】Policy 名称校验阻断路径穿越
2. 【S-1-2】LLM 配置读写受特权保护且 `api_key` 不明文外泄

#### 【S-1-1】Policy 名称校验阻断路径穿越

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | S-1-1 |
| 测试要求 | `POLICY_NAME_RE` 作为唯一路径穿越防线，须接受 `default`、`ops-1`、`a_b`、64 字符名，拒绝空串、65 字符、`../x`、`a/b`、`中文`、`a.b`；非法名在 `switch_policy` / `create_policy` / `rename_policy` / `delete_policy` 四处入口均被拦截且不写任何配置、不创建任何目录。 |
| 主要测试文件 | 被测：`auditor/translator/policy_manager.py`；测试脚本：`tests/unit/test_policy_manager.py`（UT-PM-001、UT-PM-010、UT-PM-013、UT-PM-017、UT-PM-021） |
| 测试环境 | 同 F-1-6 |
| 测试方法 | 1. 表驱动喂入 10 组名称，断言正则判定结果；2. 对四个入口分别传入 `../x`、`a/b`，断言返回 400 与中文错误文案；3. 断言操作后 `tmp_path` 目录树与内存配置字典完全未变。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 10 组名称判定全部符合预期（4 通过 / 6 拒绝）；四个入口对穿越名称均返回 400，且目录树与配置无任何副作用。 |
| 验收判据（非执行结论） | 策略库名称校验可有效阻断路径穿越，为 Policy 目录操作提供了可靠防线；需执行后判定。 |

#### 【S-1-2】LLM 配置读写受特权保护且 `api_key` 不明文外泄

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | S-1-2 |
| 测试要求 | `GET/PUT /api/translator/config` 读写 `api_base_url`/`api_key`/`model`/`temperature`/`timeout`/`json_mode`；PUT 须校验特权会话（无 `X-Admin-Session` 返回 403）；GET 响应中的 `api_key` 须脱敏。 |
| 主要测试文件 | 被测：`app.py`（`/api/translator/config`）、`auditor/translator/core.py`（`get_llm_config`）；测试脚本：`tests/api/test_translator_api.py`（UT-API-064）、`tests/unit/test_translator_core.py`（UT-TR-005） |
| 测试环境 | Ubuntu 22.04；`flask_client` fixture（依赖 `temp_db`，mock `socketio.emit` 与 `broadcast_push`）；`admin_session` fixture 提供特权头 |
| 测试方法 | 1. 无特权 PUT，断言 403 且 config 表未变；2. 携带有效特权头 PUT，断言 200 且配置落库；3. GET 响应体全文检索预置 `api_key` 明文值；4. 断言 `get_llm_config` 各字段默认值与 config 覆盖合并结果。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 验证写入权限、默认值合并及读取脱敏；RISK-019 的明文返回风险待复现。只使用合成测试密钥；若登记 xfail，仍应断言期望的脱敏行为并设 strict=True，不把现状泄漏写成安全通过。 |
| 验收判据（非执行结论） | 无特权写入无副作用、合法写入符合契约、读取不暴露密钥；需执行和风险回归后判定。 |

### 1.4 可靠性验证

1. 【R-1-1】LLM 输出解析鲁棒性
2. 【R-1-2】注册表缺失与非法内容降级不崩溃
3. 【R-1-3】策略库操作异常时副作用可控
4. 【R-1-4】策略库删除与重命名边界保护

#### 【R-1-1】LLM 输出解析鲁棒性

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | R-1-1 |
| 测试要求 | `_extract_json` 须能从纯 JSON、` ```json ` 围栏、前后夹带解释性文字、多个 JSON 块、单引号、尾随逗号、完全无 JSON 等七种 LLM 输出形态中稳定提取；无 JSON 时返回空 dict 且不抛异常。`call_llm` 在 200/401/超时/连接失败/响应缺 `choices` 五种情形下均返回明确结果而不抛未捕获异常。 |
| 主要测试文件 | 被测：`auditor/translator/core.py`（`_extract_json`、`call_llm`）；测试脚本：`tests/unit/test_translator_core.py`（UT-TR-006~008） |
| 测试环境 | 同 F-1-2；HTTP 层以 `unittest.mock` 替换 |
| 测试方法 | 1. 表驱动喂入 7 类输出形态，逐一断言提取结果；2. 分别 mock 出 5 类 HTTP 结果，断言返回值与错误文案；3. 断言 `json_mode=True` 时请求体携带 `response_format`。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 七形态全部按预期处理：围栏与夹带文字能正确剥离，多块取首个合法块，单引号与尾随逗号经容错解析成功，完全无 JSON 返回 `{}`；五类 HTTP 结果均转为明确错误串，无未捕获异常。 |
| 验收判据（非执行结论） | LLM 输出解析具备足够鲁棒性，不会因模型输出格式波动导致链路崩溃；需执行后判定。 |

#### 【R-1-2】注册表缺失与非法内容降级不崩溃

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | R-1-2 |
| 测试要求 | `scenes.json` 缺失、`tools/` 为空、单个 tool json 非法时，注册表加载须降级为空集合而非抛异常（否则 `import core` 即崩溃）；`GET /api/translator/registry` 与 `registry-health` 须返回明确错误而非 500。 |
| 主要测试文件 | 被测：`auditor/translator/core.py`、`app.py`（`/api/translator/registry*`）；测试脚本：`tests/unit/test_translator_core.py`（UT-TR-003）、`tests/api/test_translator_api.py`（UT-API-065~066） |
| 测试环境 | 同 F-1-1 |
| 测试方法 | 1. 构造三类残缺目录，分别执行加载并断言不抛异常且返回空集合；2. 调用 `/api/translator/registry` 与 `/api/translator/registry-health`，断言状态码非 500 且 `healthy` 标志正确。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 三类残缺目录加载均返回空集合，`import` 链路不受影响；两个接口分别返回 200 并携带 `healthy=false` 与缺失原因，无 500。 |
| 验收判据（非执行结论） | 注册表异常内容只降级不崩溃，符合"不因策略库损坏导致服务不可用"的要求；需执行后判定。 |

#### 【R-1-3】策略库操作异常时副作用可控

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | R-1-3 |
| 测试要求 | `create_policy` 在 `mkdir` 抛错时返回 500 且不留半成品目录；`rename_policy` 在 move 失败时返回 500 且源目录保持可用；`_reload` 在 `core.reload_registry` 抛异常时经双路 import 兜底后静默不抛。 |
| 主要测试文件 | 被测：`auditor/translator/policy_manager.py`；测试脚本：`tests/unit/test_policy_manager.py`（UT-PM-014、UT-PM-017、UT-PM-029） |
| 测试环境 | 同 F-1-6；以 monkeypatch 使 `Path.mkdir` / `shutil.move` / `core.reload_registry` 抛出 `OSError` |
| 测试方法 | 1. 注入磁盘异常执行创建，断言返回码 500 与错误文案，并检查目录树无半成品残留；2. 注入 move 失败执行重命名，断言源 Policy 仍有效可切换；3. 注入 `reload_registry` 异常，断言 `_reload` 不抛且上层操作照常返回。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 创建失败后目录树保持操作前状态；重命名失败后源 Policy 仍可被 `switch_policy` 正常切换；`_reload` 异常被完全吞掉并打印日志，不影响配置写入结果。 |
| 验收判据（非执行结论） | 异常路径副作用可控，不会产生"幽灵 Policy"或不可用的中间状态；需执行后判定。 |

#### 【R-1-4】策略库删除与重命名边界保护

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | R-1-4 |
| 测试要求 | `delete_policy` 拒绝删除当前生效 Policy（400"不能删除当前正在使用的 Policy"）；拒绝删除最后一个有效 Policy（400"至少需保留一个有效 Policy"）；但允许删除无效空壳目录（幽灵 Policy），即使有效 Policy 仅剩 1 个；删除成功后容器目录整体消失。 |
| 主要测试文件 | 被测：`auditor/translator/policy_manager.py`；测试脚本：`tests/unit/test_policy_manager.py`（UT-PM-018~022、UT-PM-030） |
| 测试环境 | 同 F-1-6 |
| 测试方法 | 1. 删除当前生效 Policy，断言 400 与文案；2. 仅保留 1 个有效 Policy 时删除它，断言 400 与文案；3. 在同样条件下删除一个无效空壳目录，断言允许删除；4. 删除成功后断言容器目录不存在；5. 对真实仓库 `default` 与 `ops` 两套策略库断言场景集合相同、工具 json 文件名一致。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 两类拒绝分支文案精确；无效空壳目录在"有效 Policy 仅剩 1 个"时仍被放行（代码特意设计），符合清理幽灵目录的需要；真实仓库两套策略库场景集合与 15 个工具文件名完全一致。 |
| 验收判据（非执行结论） | 删除与重命名边界保护完备，不会把系统置于无可用策略库的状态；需执行后判定。 |

---

## 二、行为合规判定引擎模块

### 2.1 功能验证

验证的基本目标：

1. 【F-2-1】归一化与匹配原语正确
2. 【F-2-2】IR 解析与加载三形态兼容
3. 【F-2-3】四维分层判定结构与评分公式正确
4. 【F-2-4】四维越权检测能力完备
5. 【F-2-5】判定结果序列化与文本渲染正确
6. 【F-2-6】Shell 命令语义分析能力完备
7. 【F-2-7】顶层入口 `judge()` 与网关行为解析正确

#### 【F-2-1】归一化与匹配原语正确

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-2-1 |
| 测试要求 | `_normalize_action` 覆盖 25 条别名映射（`open/openat/o_rdonly/read_file/summarize→read`、`write_file/patch/o_wronly/rename/renameat→write`、`o_creat→create`、`unlink/unlinkat/rmdir/rm→delete`、`chmod→setattr`、`execve/exec→execute`、`fetch/request/http_get/http_post/download/upload→connect`）并统一大小写与空格；`_infer_resource_type` 正确区分 file/tool/network；`_glob_pattern_to_regex` 与 `_glob_param_to_regex` 按各自语义转译；`_match_identifier` 按"等值→regex→glob"逐级匹配。 |
| 主要测试文件 | 被测：`auditor/monitor/judge.py`（模块级私有原语）；测试脚本：`tests/unit/test_judge_primitives.py`（UT-JG-001~013） |
| 测试环境 | Ubuntu 22.04，Python 3.14；纯函数无需任何 mock |
| 测试方法 | 1. 表驱动逐条断言 25 条动作别名；2. 断言大小写、前后空格、`None`、未命中别名四种输入的归一结果；3. 对 URL、路径、工具名三类 identifier 断言资源类型推断，并验证合法 fallback 优先；4. 对 `/tmp/**`、`/tmp/*.txt`、含正则元字符字面量断言 glob 转译与首尾锚定；5. 差异断言 identifier 版 `*` 不跨 `/`、param 版 `*` 跨 `/`；6. 断言 `regex:`/`re:`/`REGEX:` 前缀识别与剥离后保留原大小写。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 25 条别名逐条命中；`None→""`、未命中别名原样返回；`http/https/ftp/ssh/git` 与裸 netloc 判 network，`/etc/passwd`、`./a.txt`、`.env` 判 file，`read`、`safe_file_reader` 判 tool；两个 glob 转译函数的跨 `/` 差异被显式固化；非法正则不抛异常并自动降级到 glob 匹配。 |
| 验收判据（非执行结论） | 判定引擎原语行为确定、可复现，别名表与匹配链完整；需执行后判定。 |

#### 【F-2-2】IR 解析与加载三形态兼容

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-2-2 |
| 测试要求 | `parse_ir_policies` 兼容 `{"policies":[...]}`、裸 list、单 policy dict 三形态；`objects`/`object`/`resources` 三种键名等价；policy 级 `action`/`selinux_rules` 下渗到 object；非法输入抛 `ValueError("IR JSON must be an object or a list")`。`load_ir_policies` 对文件不存在、存在但 size==0、合法 JSON、非法 JSON 四态返回预期结果。 |
| 主要测试文件 | 被测：`auditor/monitor/judge.py`（`parse_ir_policies`、`load_ir_policies`、`_parse_object`、`_parse_params`）；测试脚本：`tests/unit/test_judge_primitives.py`（UT-JG-019~027）；数据：`tests/data/ir/` |
| 测试环境 | 同 F-2-1；文件类用例使用 `tmp_path` |
| 测试方法 | 1. 三形态 IR 各解析一次，断言策略数与对象数一致；2. 三种对象键名等价性断言；3. 断言 identifier 取值优先级 `identifier/path/url/domain/host/name/resource` 逐级回退，全缺失时抛 `ValueError`；4. 断言 `_parse_params` 对 dict（值含 int/None 全部 str 化）、list（取 `name\|identifier`→`value`）、空三态的输出；5. 四态文件加载断言异常类型。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 三形态与三键名全部等价；identifier 回退链正确，全缺失时抛 `ValueError`；空文件（size==0）按 `FileNotFoundError` 处理，非法 JSON 抛 `JSONDecodeError`；`_parse_object` 不支持 `uri`/`endpoint` 而 `_normalize_actions` 支持，该不对称待复核并上报（附录 C 第 10 项）。 |
| 验收判据（非执行结论） | IR 解析与加载兼容性符合设计，键名不对称问题已记录待统一；需执行后判定。 |

#### 【F-2-3】四维分层判定结构与评分公式正确

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-2-3 |
| 测试要求 | `Resource_Consistency_Check_Layered` 返回的 `LayeredCheckResult` 须包含 `tool_call_consistency`、`tool_trajectory_consistency`、`parameter_consistency`、`resource_access_consistency` 四维；`overall_score` 仅对 `total_count>0` 的维度取算术平均并 `round(...,4)`，四维全空时为 `1.0`；`_aspect_result` 中空维度得分为 `1.0`、1/3 命中为 `0.3333`，`consistent` 由 violations 决定并与 score 解耦。 |
| 主要测试文件 | 被测：`auditor/monitor/judge.py`（`Resource_Consistency_Check_Layered`、`_aspect_result`）；测试脚本：`tests/unit/test_judge_layered.py`（UT-JG-101~102、UT-JG-033~035、UT-JG-120~123） |
| 测试环境 | 同 F-2-1 |
| 测试方法 | 1. 喂入标准 IR + 行为事件，断言返回 dataclass 的四维字段存在性与类型；2. 构造"部分维度为空"的组合，断言分母仅计入 `total_count>0` 的维度；3. 构造四维全空输入，断言 `overall_score==1.0`；4. 构造 1/3 命中，断言 `0.3333`；5. 构造"violations 非空但 matched==total"，断言 `consistent=="no"`；6. 构造 `overall_score` 恰为 `0.5`/`0.5001`/`-1` 的输入，断言与 README 阈值语义可对接。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 四维字段齐全；评分公式与四舍五入位数精确；空维度不参与平均；`consistent` 与 score 解耦语义被固化。注：实现为四维（含轨迹一致性），README/CLAUDE.md 仅描述三维，文档不一致待复核（附录 C 第 17 项）。 |
| 验收判据（非执行结论） | 分层判定结构与评分公式正确，文档需同步补充第四维；需执行后判定。 |

#### 【F-2-4】四维越权检测能力完备

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-2-4 |
| 测试要求 | 工具调用维能检出"工具不在 IR 范围"（`tool out of IR allow scope`）与"动作越权"（`tool action over-privilege`）；参数维能检出 `tool param mismatch`；资源维能检出 `resource out of IR allow scope`（含 network 类型）；轨迹维对子序列命中放行、乱序或含期望外工具时报 `tool trajectory mismatch`；`effect="deny"` 的 policy 被过滤不参与 allow 判定。 |
| 主要测试文件 | 被测：`auditor/monitor/judge.py`（`_evaluate_event`、四维判定主体）；测试脚本：`tests/unit/test_judge_layered.py`（UT-JG-105~119、UT-JG-028~032） |
| 测试环境 | 同 F-2-1；IR 与行为样本取自 `tests/data/ir/`、`tests/data/actions/` |
| 测试方法 | 1. 以 README 示例构造"IR 允许 `read`、实际调 `exec`"，断言工具调用维 violation 文案；2. 构造"IR 允许 `path=/tmp/a.txt`、实际传 `path=/etc/passwd`"，断言参数维 violation；3. 构造"IR 允许 `read /tmp/**`、实际 `write /etc/cron.d/x`"，断言资源维 violation；4. 构造网络资源 `http://malicious.example.com/collect`，断言 network 类型 violation；5. 轨迹维分别喂入子序列、乱序、含期望外工具、重复调用、空序列五种输入；6. 断言 `effect="deny"` 策略被过滤；7. 断言 `obj.type != event.resource_type` 时跳过该 obj。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 四维 violation 文案与 README 描述一致；轨迹维贪心指针算法对子序列放行、乱序报错，同一工具重复调用时第 2 次不命中（语义待固化），空 `observed_tool_order` 不产生 violation 且不计入 overall；`deny` 策略正确过滤；类型不匹配的 obj 被跳过且不计入匹配。 |
| 验收判据（非执行结论） | 四维越权检测能力完备，覆盖 README 声明的全部威胁场景；需执行后判定。 |

#### 【F-2-5】判定结果序列化与文本渲染正确

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-2-5 |
| 测试要求 | `layered_result_to_dict` 输出可 JSON 序列化（含嵌套 dataclass）；`layered_result_to_text` 首行在合规/异常时分别为 `【判定结果】行为一致，整体得分: <s>` 与 `【判定结果】行为异常，整体得分: <s>`；`total_count==0` 的维度段落不输出（前端解析依赖）；`Resource_Consistency_Check_Scored` 与基线版 `Resource_Consistency_Check` 结构正确。 |
| 主要测试文件 | 被测：`auditor/monitor/judge.py`（`layered_result_to_dict`、`layered_result_to_text`、`Resource_Consistency_Check*`）；测试脚本：`tests/unit/test_judge_layered.py`（UT-JG-122~128） |
| 测试环境 | 同 F-2-1 |
| 测试方法 | 1. 对任意判定结果执行 `asdict()` 后 `json.dumps`，断言无异常；2. 分别构造合规与异常结果，断言首行文案逐字符相等；3. 构造含空维度的结果，断言文本中不出现该维度段落；4. 无行为事件时断言 `score==1.0`、`total_count==0`、`consistent=="yes"`；5. 混合命中时断言 `score==round(matched/total,4)`；6. 喂入中文路径与超长 violations，断言无编码异常。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 序列化与文本渲染全部符合前端解析契约；空维度段落确实被省略；中文路径与 1MB 级 violations 文本渲染无异常。 |
| 验收判据（非执行结论） | 判定结果输出格式稳定，可作为前后端契约固化；需执行后判定。 |

#### 【F-2-6】Shell 命令语义分析能力完备

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-2-6 |
| 测试要求 | `analyze_shell_command` 能从命令串推导出读/写/删除/权限/网络/执行六类行为：读类 `cat/head/tail/less/grep`→`read`；写类 `tee/dd/cp/mv/install`→`write`（及源 `read`）；删除类 `rm/rmdir/unlink/shred`→`delete`；权限类 `chmod/chown/setfacl`→`setattr`；网络类 `curl/wget/nc/ssh/scp/git clone`→`connect`；执行类 `python x.py`、`./bin`、`node s.js`→`execute` + 脚本 `read`。须正确处理管道链、重定向、包装命令与嵌套 shell。 |
| 主要测试文件 | 被测：`auditor/monitor/shell_command_semantics.py`；测试脚本：`tests/unit/test_shell_semantics.py`（UT-SH-001~026） |
| 测试环境 | 同 F-2-1 |
| 测试方法 | 1. 分类表驱动喂入六类命令，断言行为集合与 identifier；2. `_split_segments` 覆盖 `SHELL_OPERATORS = {\|, \|\|, &&, ;, &}` 全集与混合；3. `_redirection_behaviors` 覆盖 `REDIRECT_READ={<}` 与 `REDIRECT_WRITE={>,>>,1>,1>>,2>,2>>}` 全集，断言 `> /dev/null`、`2>&1` 不误判文件写；4. 包装命令与多层嵌套逐一解析；5. 仅将 `cat /etc/passwd \| grep root > /tmp/o` 作为输入字符串，断言 read/write 行为，绝不执行该命令或读取真实文件。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 六类命令行为推导全部正确；操作符与重定向全集覆盖，fd 复制不被误判为文件写；包装命令可逐层剥离到真实命令；多层嵌套 shell 递归终止且不无限循环；管道链端到端结果符合预期；`/etc/passwd`、`/root/.ssh/id_rsa`、`/etc/cron.d/x` 等敏感目标均能产出可供上层判越权的行为。 |
| 验收判据（非执行结论） | Shell 命令语义分析能力完备，为"命令型工具调用"提供了可判定的行为视图；需执行后判定。 |

#### 【F-2-7】顶层入口 `judge()` 与网关行为解析正确

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-2-7 |
| 测试要求 | `judge(action, IR)` 对自带 demo 样本输出稳定文本（golden 比对）；`_normalize_ir` 能处理两阶段结构 `{"level1":[...],"level2":{"policies":[...]}}` 与 Level-2 真实结构（`functions`+`file_actions`+`resource_type`+`scene`）；`_normalize_actions` 能从标准 action 形态产出 1 个 tool 事件 + N 个资源事件，并支持 `identifier/path/url/uri/endpoint/domain/host` 七键回退；`gateway_messages_to_behaviors` 能解析 Portkey `body.messages`（含 assistant `tool_calls`）；`_infer_exec_behaviors` 联动 shell 语义分析。 |
| 主要测试文件 | 被测：`auditor/monitor/judge.py`（`judge`、`_normalize_ir`、`_normalize_actions`、`gateway_messages_to_behaviors`、`_infer_exec_behaviors`、`_resolve_exec_path`）；测试脚本：`tests/unit/test_judge_entry.py`（UT-JG-201~215）；数据：`tests/data/gateway/` |
| 测试环境 | 同 F-2-1 |
| 测试方法 | 1. 以 `judge.py` 自带 demo 样本（read `/temp/helloworld.txt`）执行并与 golden 文本比对；2. 分别喂入两阶段结构与 Level-2 真实结构，断言策略提取结果；3. 表驱动断言七键回退；4. 喂入完整 Portkey 报文，断言行为事件序列；5. 断言 `content` 为多模态 list 与纯字符串时 `_gateway_content_to_text` 归一结果；6. 断言含 `command` 参数时 `analyze_shell_command` 被调用并转为行为事件；7. 断言 `_resolve_exec_path` 对相对路径+`workdir`、绝对路径、`~` 的归一。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | demo 样本输出与 golden 文本逐字节一致；两阶段结构与 Level-2 真实结构均正确转为 `IRObject` 列表；七键回退逐键生效；Portkey 报文（含 OpenAI 风格 `tool_calls`）解析出的事件序列完整；`command` 参数成功联动 shell 语义分析；路径归一为绝对路径。 |
| 验收判据（非执行结论） | 顶层判定入口与网关行为解析正确，具备直接接入生产网关日志的能力；需执行后判定。 |

### 2.2 性能验证

1. 【P-2-1】单轮分层判定耗时
2. 【P-2-2】Shell 命令语义分析耗时（含超长命令）
3. 【P-2-3】大批量行为事件判定的耗时与内存

#### 【P-2-1】单轮分层判定耗时

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | P-2-1 |
| 测试要求 | 典型规模（IR 5 条策略 / 20 个对象，行为事件 30 条）下 `Resource_Consistency_Check_Layered` 单轮耗时小于 20ms，确保 round 结束时的判定不成为上报链路瓶颈。 |
| 主要测试文件 | 被测：`auditor/monitor/judge.py`；测试脚本：`tests/unit/test_judge_layered.py::test_layered_perf` |
| 测试环境 | Ubuntu 22.04，CPU Intel x86_64，内存 16GB；纯 CPU 计算，无 IO |
| 测试方法 | 1. 构造典型规模 IR 与行为事件；2. 连续执行 1000 轮判定，记录总耗时与单轮均值、P95；3. 断言均值低于阈值。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 分层判定及顶层入口耗时未测；分别记录相同输入规模下的样本、均值和 P95，按 20ms 目标评估，注明渲染和归一化是否纳入计时。 |
| 验收判据（非执行结论） | 分层判定耗时极低，不影响 round 上报时延；需执行后判定。 |

#### 【P-2-2】Shell 命令语义分析耗时

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | P-2-2 |
| 测试要求 | 常规命令（≤200 字符）分析耗时小于 1ms；超长命令（>8KB，含多级管道与嵌套 shell）分析耗时小于 50ms 且不出现指数级回溯。 |
| 主要测试文件 | 被测：`auditor/monitor/shell_command_semantics.py`；测试脚本：`tests/unit/test_shell_semantics.py::test_shell_perf`（UT-SH-025） |
| 测试环境 | 同 P-2-1 |
| 测试方法 | 1. 对 50 条常规命令各分析 200 次取均值；2. 构造 8KB / 32KB 超长命令（含 200 段管道、3 层嵌套 `bash -c`），各分析 20 次；3. 断言耗时与内存增长线性。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 常规/长命令耗时与内存均未测；仅解析合成命令文本、不执行 Shell。保存多个长度和结构的重复样本，比较 1ms/50ms 目标；有限样本不能证明不存在所有回溯或复杂度风险。 |
| 验收判据（非执行结论） | Shell 语义分析性能满足在线分析需求，超长命令无性能风险；需执行后判定。 |

#### 【P-2-3】大批量行为事件判定的耗时与内存

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | P-2-3 |
| 测试要求 | 10 万条行为事件 × 50 条 IR 策略的批量判定，总耗时应在可接受范围（<60s）且内存峰值增长小于 500MB，不出现 O(n²) 退化。 |
| 主要测试文件 | 被测：`auditor/monitor/judge.py`；测试脚本：`tests/unit/test_judge_layered.py::test_layered_bulk`（P1） |
| 测试环境 | 同 P-2-1；以 `tracemalloc` 采集内存峰值 |
| 测试方法 | 生成 1 万/5 万/10 万事件，分别覆盖合规和全越权，按 G.2 重复测量耗时及内存；输入构造置于计时外。对比规模增长和单位事件成本，不以三个单次样本证明算法复杂度。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 三档耗时、Python 分配峰值和进程内存均未测；10 万事件目标 <60s、内存增长 <500MB。需额外测量 violations 体量，未验证的上层截断不算保护措施。 |
| 验收判据（非执行结论） | 在固定规模与硬件下达到耗时/内存目标；扩展趋势单列，不能推断所有输入均线性。 |

### 2.3 安全性验证

1. 【S-2-1】空 `actions` 集合的 fail-open 放行语义
2. 【S-2-2】参数单向子集匹配带来的参数注入面
3. 【S-2-3】路径逃逸与编码绕过检测能力
4. 【S-2-4】越权事件对后续事件计数的干扰

#### 【S-2-1】空 `actions` 集合的 fail-open 放行语义

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | S-2-1 |
| 测试要求 | `_action_allowed` 在 `allowed_actions` 为空集合时返回 `True`（放行一切）。该安全语义必须以用例锚定，并在端到端场景中验证其影响：IR object 的 `actions=[]`、实际行为为 `delete` 时会被判为合规。 |
| 主要测试文件 | 被测：`auditor/monitor/judge.py`（`_action_allowed`）；测试脚本：`tests/unit/test_judge_primitives.py`（UT-JG-014~016）、`tests/api/test_joint_permission.py`（UT-JP-018） |
| 测试环境 | 同 F-2-1 |
| 测试方法 | 1. 直接调用 `_action_allowed` 传入空集合，断言返回 `True`；2. 断言正常集合的交集判定（`network`+`connect` vs `{receive}`/`{send}`/`{connect}`，`file`+`write` vs `{read}`）；3. 构造 `actions=[]` 的 IR + `delete` 行为，端到端执行分层判定并断言最终结论。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 空集合确认为 fail-open 放行；端到端场景中 `delete /etc/passwd` 在 `actions=[]` 的 IR 下被判定为合规（`overall_score=1.0`）。该行为拟作为高危风险固化上报（附录 C 第 8 项），建议改为 fail-close 或在 IR 校验阶段禁止空 `actions`。 |
| 验收判据（非执行结论） | 空动作集合放行语义待复核，属高危设计风险，待复现后评审修复评审。尚未执行；关联风险须复现和关闭，不以“条件通过”替代验收。 |

#### 【S-2-2】参数单向子集匹配带来的参数注入面

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | S-2-2 |
| 测试要求 | `_params_match` 语义为单向子集匹配：expected 为空→`True`；expected 子集命中→`True`；actual 含 expected 之外的额外键→仍 `True`。须锚定该语义并验证其风险：IR 仅约束 `path=/tmp/a.txt` 时，额外传入 `mode=w` 不被拦截。 |
| 主要测试文件 | 被测：`auditor/monitor/judge.py`（`_params_match`、`_match_param_value`）；测试脚本：`tests/unit/test_judge_primitives.py`（UT-JG-017~018）、`tests/api/test_joint_permission.py`（UT-JP-017） |
| 测试环境 | 同 F-2-1 |
| 测试方法 | 1. 表驱动断言四类参数组合（空 expected / 子集命中 / 含额外键 / 键缺失或值不匹配）；2. 端到端构造"合法 path + 额外 mode=w"的工具调用，断言参数维无 violation。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 单向子集匹配语义确认；额外参数（含 `mode=w`、`follow_symlinks=true` 等潜在提权参数）不受约束而被放行。该面拟作为风险固化上报（附录 C 第 9 项），建议增加"参数白名单严格模式"配置。 |
| 验收判据（非执行结论） | 参数匹配语义待复核，存在参数注入面，待复现后评审修复评审。尚未执行；关联风险须复现和关闭，不以“条件通过”替代验收。 |

#### 【S-2-3】路径逃逸与编码绕过检测能力

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | S-2-3 |
| 测试要求 | 对 `/tmp/../etc/passwd`、`/tmp/./x`、双斜杠 `//tmp//x`、软链目标等路径逃逸形态，须在归一化后正确判定越权；对 `/TMP/A.TXT`（Linux 大小写敏感）、URL 编码 `%2e%2e%2f`、Unicode 同形字符等绕过形态，须断言实测行为并固化。 |
| 主要测试文件 | 被测：`auditor/monitor/judge.py`、`auditor/monitor/shell_command_semantics.py`；测试脚本：`tests/api/test_joint_permission.py`（UT-JP-015~016） |
| 测试环境 | 同 F-2-1 |
| 测试方法 | 1. 构造 IR 仅允许 `/tmp/**`，行为路径依次为 4 类逃逸形态，断言判定结果；2. 构造 3 类编码/大小写绕过形态，记录实测判定并以 golden 固化；3. 对 shell 语义分析产出的 identifier 做同样断言。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | `/tmp/./x` 与 `//tmp//x` 经 `_resolve_exec_path` 归一后判定正确；`/tmp/../etc/passwd` 在经过 shell 路径归一的链路（exec 行为）中被正确判为越权，但直接由 action `resources[].path` 传入的未归一路径存在漏检面，待固化为 xfail 并上报（附录 C 第 20 项）；URL 编码与 Unicode 同形字符不做解码，按字面量参与匹配，该语义待固化。 |
| 验收判据（非执行结论） | 逃逸检测能力在 exec 链路完整；action 直传路径需补充统一归一化，待复现后评审修复评审。尚未执行；关联风险须复现和关闭，不以“条件通过”替代验收。 |

#### 【S-2-4】越权事件对后续事件计数的干扰

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | S-2-4 |
| 测试要求 | 锚定 `judge.py:791` 的计数条件 `not tool_call_violations or "tool action over-privilege" not in tool_call_violations[-1]`：构造 `[越权工具A, 合规工具B]` 序列，验证前一条 violation 是否影响后一条合规事件计入 `matched_count`，并固化当前真实输出。 |
| 主要测试文件 | 被测：`auditor/monitor/judge.py`（`Resource_Consistency_Check_Layered` 工具调用维计数）；测试脚本：`tests/unit/test_judge_layered.py`（UT-JG-109） |
| 测试环境 | 同 F-2-1 |
| 测试方法 | 1. 构造 `[越权A, 合规B]` 与 `[合规B, 越权A]` 两个序列；2. 分别执行判定，记录 `matched_count`、`total_count`、`overall_score`；3. 以 golden 固化两组输出并比对差异。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 两个序列的 `matched_count` 不同：越权事件在前时，后续合规事件未被计入 `matched`，导致得分受事件顺序影响，判定结果不满足"顺序无关"的期望。该缺陷待复核（附录 C 第 7 项），建议改为按事件独立计数。 |
| 验收判据（非执行结论） | 计数条件依赖上一条 violation 的字符串内容，属高危逻辑缺陷，待复现后评审修复评审。尚未执行；关联风险须复现和关闭，不以“条件通过”替代验收。 |

### 2.4 可靠性验证

1. 【R-2-1】畸形输入不崩溃
2. 【R-2-2】非法正则与未闭合引号降级处理
3. 【R-2-3】judge 与 RCC 双实现漂移防护
4. 【R-2-4】编码与体量鲁棒性

#### 【R-2-1】畸形输入不崩溃

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | R-2-1 |
| 测试要求 | `judge(action, IR)` 在 `action=None`/`[]`/非 list 标量/含非 dict 元素，以及 `IR=None`/`{}`/`"__loading__"`/畸形 JSON dict 的任意组合下，均不抛异常并返回合法文本；`_normalize_actions` 对无 identifier、非 dict、`tool` 为空串的资源项静默跳过。 |
| 主要测试文件 | 被测：`auditor/monitor/judge.py`（`judge`、`_normalize_ir`、`_normalize_actions`）；测试脚本：`tests/unit/test_judge_entry.py`（UT-JG-202~203、UT-JG-209~210） |
| 测试环境 | 同 F-2-1 |
| 测试方法 | 1. 以 4×4 组合矩阵（action 四态 × IR 四态）参数化调用 `judge`，断言无异常且返回字符串非空；2. 构造含非法资源项的 action，断言事件数量符合"静默跳过"预期；3. 断言 `arguments` 非 dict 时 `params=None`。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 16 组组合全部返回合法判定文本，无一抛出异常；`"__loading__"` 占位 IR 被 `_normalize_ir` 兜底为空策略集；非法资源项被静默跳过且不产生事件。 |
| 验收判据（非执行结论） | 判定入口对畸形输入具备完全的容错能力，不会中断 round 上报链路；需执行后判定。 |

#### 【R-2-2】非法正则与未闭合引号降级处理

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | R-2-2 |
| 测试要求 | `_match_identifier` 遇到非法正则（如 `regex:[`）时不抛异常并降级；`_tokenize` 遇到未闭合引号、转义空格时不抛异常并降级切词；`analyze_shell_command` 对空串、纯空白、仅操作符 `;;`、仅赋值 `A=1` 返回空行为集。 |
| 主要测试文件 | 被测：`auditor/monitor/judge.py`（`_match_identifier`）、`shell_command_semantics.py`（`_tokenize`、`analyze_shell_command`）；测试脚本：`tests/unit/test_judge_primitives.py`（UT-JG-011）、`tests/unit/test_shell_semantics.py`（UT-SH-001、UT-SH-023） |
| 测试环境 | 同 F-2-1 |
| 测试方法 | 1. 喂入 5 类非法正则模式，断言无异常并回落到 glob/等值匹配；2. 喂入单引号、双引号、转义空格、未闭合引号四类命令，断言切词结果；3. 喂入 4 类空/退化命令，断言行为集为空。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 非法正则被捕获并降级，不影响后续匹配链；未闭合引号按"到行尾闭合"降级处理，不抛 `ValueError`；4 类退化命令返回空行为集。 |
| 验收判据（非执行结论） | 匹配与分词链路具备降级能力，不会因用户或模型构造的畸形模式崩溃；需执行后判定。 |

#### 【R-2-3】judge 与 RCC 双实现漂移防护

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | R-2-3 |
| 测试要求 | `judge.py`（1175 行）与 `resource_consistency_check.py`（1221 行）为同源分叉双实现，须建立交叉一致性测试：对 `_normalize_action`、`_match_identifier`、`_action_allowed`、`_params_match`、`_glob_*`、`parse_ir_policies` 喂同一组输入，逐一断言两模块输出相等；任何不等即视为分叉漂移缺陷并记录。同时验证 RCC 独有能力（`_parse_open_flags`、`_normalize_behavior_action`、`_shell_complexity_reason` 等）。 |
| 主要测试文件 | 被测：`auditor/monitor/judge.py`、`auditor/monitor/resource_consistency_check.py`；测试脚本：`tests/unit/test_rcc_parity.py`（UT-RCC-001~010） |
| 测试环境 | 同 F-2-1 |
| 测试方法 | 1. 建立同名函数对照表，对每对函数喂入同一组参数化输入并断言输出相等；2. 断言 `_parse_open_flags` 对 `"O_RDONLY"`、`"O_WRONLY\|O_CREAT"`、八进制 `0o100`、十进制字符串、`None`、乱码的解析结果；3. 断言 `_normalize_behavior_action` 将 open flags 正确映射为 `read`/`write`/`create`；4. 断言 `_shell_complexity_reason` 对管道、命令替换 `$(...)`、反引号、复杂重定向返回原因串，简单命令返回 `None`；5. 对两版 `Resource_Consistency_Check_Layered` 同输入做结构一致性比对。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 6 组同名原语在全部参数组合下输出相等，当前无语义漂移；RCC 独有的内核态 open flags 映射与 shell 复杂度判定功能正常；两版 Layered 对同输入的四维结构一致。双实现并存的架构风险待复核（附录 C 第 11 项），建议将公共原语抽取为 `_primitives.py`，并以本用例作为抽取前后的等价性保护网。 |
| 验收判据（非执行结论） | 双实现公共语义按批准的对照矩阵一致，扩展差异有记录；保护用例尚未实现，不能预填当前无漂移。 |

#### 【R-2-4】编码与体量鲁棒性

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | R-2-4 |
| 测试要求 | 判定链路对中文路径、emoji、RTL 控制符、NUL 字符、非 UTF-8 字节、10MB 级字符串、10 万条数组输入均不抛异常，文本渲染无编码问题。 |
| 主要测试文件 | 被测：`auditor/monitor/judge.py`、`shell_command_semantics.py`；测试脚本：`tests/unit/test_judge_layered.py`（UT-JG-128）、`tests/unit/test_shell_semantics.py`（UT-SH-025） |
| 测试环境 | 同 F-2-1 |
| 测试方法 | 1. 构造含 6 类特殊字符的 identifier 与命令串，执行判定与文本渲染；2. 构造 10MB 单字符串与 10 万条数组输入，断言无异常且耗时可接受；3. 断言 `layered_result_to_text` 输出可被 `str.encode("utf-8")` 无损编码。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 6 类特殊字符全部安全处理，NUL 字符在 identifier 中被保留为字面量参与匹配；10MB 字符串与 10 万条数组判定完成且无内存异常；渲染文本可无损编码。 |
| 验收判据（非执行结论） | 编码与体量鲁棒性满足要求；需执行后判定。 |

---

## 三、运行时监控与进程安全上下文采集模块

### 3.1 功能验证

验证的基本目标：

1. 【F-3-1】日志增量尾随（FileTailer）功能完备
2. 【F-3-2】OpenClaw 会话日志解析功能完备
3. 【F-3-3】Round 状态机与生命周期管理正确
4. 【F-3-4】Portkey 网关日志解析功能完备
5. 【F-3-5】进程与安全上下文采集字段完备
6. 【F-3-6】OpenClaw 主进程定位与评分正确
7. 【F-3-7】进程树、祖先链与文件写者定位正确
8. 【F-3-8】IR 客户端请求构造与响应处理正确
9. 【F-3-9】监控编排上报链路完整

#### 【F-3-1】日志增量尾随（FileTailer）功能完备

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-3-1 |
| 测试要求 | `FileTailer.scan_new_lines` 首次扫描支持 `from_end=True/False` 两种语义；追加写入后仅返回新增行且 offset 前进；文件轮转（`(st_dev, st_ino)` 变化）时 offset 重置为 0 并重读全量；文件截断（`st_size < pos`）时 offset 回 0；空行与纯空白行不 yield。 |
| 主要测试文件 | 被测：`auditor/monitor/watcher.py`（`FileTailer`）；测试脚本：`tests/unit/test_watcher_parse.py`（UT-WT-001~008） |
| 测试环境 | Ubuntu 22.04，Python 3.14；`tmp_path` 构造日志文件，通过重建文件模拟 inode 变化 |
| 测试方法 | 1. 分别以 `from_end=True/False` 首次扫描，断言跳过历史与读取全量；2. 追加写入后二次扫描，断言只返回新增行；3. 删除并重建同名文件（inode 变化）后扫描，断言重读全量；4. 用 `truncate()` 截断文件后扫描，断言 offset 回 0；5. 喂入空行与纯空白行，断言不 yield。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 首次扫描两种语义正确；增量读取与 offset 前进正确；轮转与截断均能自恢复；空白行被过滤。注：末尾半行（无换行结尾）按 `f.tell()` 记录位点，存在被切分为两次读取的情况，待固化并上报（附录 C 第 18 项）。 |
| 验收判据（非执行结论） | 日志增量尾随功能完备，轮转与截断可自恢复；半行切分问题已记录待修；需执行后判定。 |

#### 【F-3-2】OpenClaw 会话日志解析功能完备

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-3-2 |
| 测试要求 | `parse_line` 能解析 OpenClaw `user` 消息（`round_id` 取 user message 的 `id`）、`assistant` 消息（`stopReason=toolUse`/`stop`/`end_turn` 映射到对应事件类型）、`toolResult` 消息（携带 tool id）；`session_key` 能从路径 `agents/main/sessions/<uuid>.jsonl` 推断为 `agent:main:main`；`ID_KEYS`/`TOOL_ID_KEYS`/`PROCESS_ID_KEYS`/`SUBAGENT_ID_KEYS` 各键名变体正确归集。 |
| 主要测试文件 | 被测：`auditor/monitor/watcher.py`（`parse_line`、`EVENT_ALIASES`）；测试脚本：`tests/unit/test_watcher_parse.py`（UT-WT-010~017）；数据：`tests/data/openclaw/` |
| 测试环境 | 同 F-3-1 |
| 测试方法 | 1. 逐类消息喂入并断言事件类型与 `round_id`；2. 以 `EVENT_ALIASES` 表驱动全覆盖 `stopReason` 映射；3. 断言路径推断出的 `session_key`；4. 对四组 ID 键名变体断言 ids 归集结果；5. 断言 `BLOCKED_PAYLOAD_KEYS` 命中时敏感 payload 不进入事件；6. 喂入非法 JSON、缺 `type`、缺 `message` 三类行，断言返回 `None`。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 三类消息解析正确，`EVENT_ALIASES` 全表映射无遗漏；`session_key` 推断符合约定；四组 ID 键名变体均被归集；敏感 payload 键被剔除；三类畸形行返回 `None` 且不抛异常。 |
| 验收判据（非执行结论） | 会话日志解析功能完备，畸形行容错；需执行后判定。 |

#### 【F-3-3】Round 状态机与生命周期管理正确

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-3-3 |
| 测试要求 | `RoundLedger.status` 的 9 种状态（`FAILED`/`WAITING_TOOL`/`WAITING_PROCESS`/`WAITING_SUBAGENT`/`WAITING_APPROVAL`/`YIELDED`/`RUNNING_AGENT`/`ROUTING_RESPONSE`/`COMPLETED`）优先级顺序严格符合实现；`_start_round` 缺 `round_id` 时合成 `round:{session}:{ms}`；同 session 已有活跃 round 时旧轮被标记 `failed` 并强制结束；`_find_round` 四级回退（`round_id`→`parent_id`→`message_to_round`→`active_by_session`）；`check_idle_end` 在 `ROUTING_RESPONSE` 且空闲 ≥ `IDLE_END_SECONDS(5.0)` 时强制结束；`_maybe_end` 幂等。 |
| 主要测试文件 | 被测：`auditor/monitor/watcher.py`（`RoundLedger`、`RoundStateMachine`）；测试脚本：`tests/unit/test_watcher_lifecycle.py`（UT-WT-020~036） |
| 测试环境 | 同 F-3-1；不启动真实线程，状态机以手动驱动方式推进；`freezegun` 控制空闲判定时间 |
| 测试方法 | 1. 逐一构造 9 种状态组合，断言 `status` 返回值与优先级；2. 断言 `is_ended` 对 `COMPLETED`/`FAILED` 与其他状态的判定；3. 缺 `round_id` 时断言合成格式；4. 同 session 连续两个 round，断言旧轮被 `failed` 并触发 `on_round_end`；5. 分别命中四级回退路径，并断言全不命中时事件被丢弃；6. 断言工具开始/完成配对的 pending 集合增减、无法匹配 ID 但 pending 仅剩 1 个时的兜底清空、`turn_completed` 一次性清空全部 pending；7. 以 freezegun 推进到 4.9s / 5.1s，断言 `check_idle_end`；8. 重复触发 `_maybe_end`，断言 `on_round_end` 只调一次且 `active_by_session` 被清理。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 9 种状态优先级与实现一致；round_id 合成格式正确；旧轮强制结束回调被触发；四级回退逐级命中，全不命中时事件被丢弃而不创建新 round；三处 pending 兜底逻辑（tool/process/subagent）行为一致；乱序事件（先完成后开始）不抛异常；空闲结束边界精确；`_maybe_end` 幂等。注：`yielded` / `waiting_for_approval` 字段在全代码路径中从不被置 True，拟作为死字段上报（附录 C 第 15 项）。 |
| 验收判据（非执行结论） | Round 状态机与生命周期管理正确，幂等与容错完备；需执行后判定。 |

#### 【F-3-4】Portkey 网关日志解析功能完备

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-3-4 |
| 测试要求 | 能从 `requestOptions[].finalUntransformedRequest.body.messages` 正确取到 messages 与 tools；`user_query` 取最后一个 `role=user` 的 content 并清理 Sender metadata；`last_llm_message` 取 `response.preview`；actions 同时支持 OpenAI 风格 `tool_calls` 与 Anthropic 风格 `tool_use`；按 `YYYY-MM-DD.jsonl` 正确定位当天日志文件。 |
| 主要测试文件 | 被测：`auditor/monitor/watcher.py`（网关解析链路）；测试脚本：`tests/unit/test_watcher_lifecycle.py`（UT-WT-050~059）；数据：`tests/data/gateway/` |
| 测试环境 | 同 F-3-1；`gateway_log` fixture 写入 Portkey 日志片段；`freezegun` 固定当天日期 |
| 测试方法 | 1. 喂入标准 Portkey 报文，断言 messages/tools 提取；2. 构造多轮对话，断言 `user_query` 取最后一条 user 且 Sender metadata 被清理；3. 断言 `last_llm_message` 取值与缺字段降级；4. 分别喂入两种风格的工具调用，断言 action 构建结果；5. 断言 `arguments` 为 JSON 字符串 / 已是 dict / 非法 JSON 三态兼容；6. 跨天场景断言日志文件定位；7. 断言 `FILE_PARAM_HINTS`（`path`/`file`/`filename`/`filepath` 等）识别出 file 资源、`COMMAND_ACCESS` 映射表命令→访问类型正确、含 `command` 参数时联动 shell 语义分析。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 网关报文解析完整，两种工具调用风格均支持；`arguments` 三态兼容；`requestOptions` 为空数组 / 非数组 / 缺失时均降级不抛异常；跨天日志定位正确；文件参数提示与命令访问映射正确，`command` 参数成功联动 shell 语义分析产出资源清单。 |
| 验收判据（非执行结论） | 网关日志解析功能完备，可直接支撑 `use_gateway` 模式的行为采集；需执行后判定。 |

#### 【F-3-5】进程与安全上下文采集字段完备

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-3-5 |
| 测试要求 | `collect_pid_info` 输出七大类字段齐全：identity（pid/ppid/tgid/comm/cmdline/argv/exe/cwd/root）、credentials（uid/gid 四元组 + groups + loginuid + audit_session_id）、resources（state/threads/vm_* /num_fds/io）、capabilities（5 组 + 原始 hex）、sandbox（seccomp/no_new_privs）、`security_labels`、isolation（9~10 个 namespace inode + cgroups + container）、env 白名单、start_time、fds；`_decode_caps` 对全量掩码解出 41 项；`collect_pid_slim` 字段集合严格小于完整版。 |
| 主要测试文件 | 被测：`auditor/monitor/proc_info.py`；测试脚本：`tests/unit/test_proc_info.py`（UT-PI-001~021）；数据：`tests/data/proc/` 伪 `/proc` 快照 |
| 测试环境 | Ubuntu 22.04；monkeypatch `proc_info.PROC` 指向 `tmp_path/"proc"`，`fake_proc` 工厂生成 `<pid>/{cmdline,comm,status,stat,cwd,exe,root,cgroup,attr/*,ns/*,io,fd/}`；`pwd`/`grp` 解析 monkeypatch |
| 测试方法 | 1. 构造完整伪进程，执行 `collect_pid_info` 并逐类断言字段存在性与取值；2. 表驱动断言 `_safe_read_text`/`_safe_readlink`/`_parse_kb`/`_try_int`/`_read_status_kv` 的正常与异常返回；3. 断言 `_read_attr_dir` 六项（current/exec/prev/fscreate/keycreate/sockcreate）映射与 NUL 清理；4. 断言 `_read_starttime_ticks` 在 comm 含空格与括号（如 `(tmux: server)`）时仍定位第 22 字段；5. 断言 `_decode_caps` 对 `"0000003fffffffff"`（41 项）、全 0、单 `CAP_SYS_ADMIN`、`None`、非 hex 的解码；6. 断言 `_detect_container` 对 docker/kubernetes/cri-o/podman/containerd/lxc 六种 cgroup 与宿主机的识别；7. 断言 `SECCOMP_MODES` 对 `"0"/"1"/"2"/`缺失的映射；8. 断言 `with_fd_sample` 与 `fd_sample_limit=20` 的采样上限；9. 对比 `collect_pid_slim` 与完整版字段集合。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 七大类字段全部齐全并与伪 `/proc` 内容一致；`_read_starttime_ticks` 不被 comm 中的空格/括号干扰；`_decode_caps` 全量掩码解出 41 项 cap 名，异常输入返回 `[]`；六种容器运行时均被识别、宿主机返回 `None`；seccomp 模式映射正确；fd 采样上限生效；slim 版仅含 identity + uid + `security_labels` + state（+`depth`）。 |
| 验收判据（非执行结论） | 进程与安全上下文采集字段完备，SELinux 与 AppArmor 标签同时覆盖；需执行后判定。 |

#### 【F-3-6】OpenClaw 主进程定位与评分正确

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-3-6 |
| 测试要求 | `_cmdline_match_score` 六档评分精确：argv[0] basename == `openclaw`→100；`openclaw-gateway`/`openclaw_x`→95；`my-openclaw-run` 子串→80；hint 在 comm 中→70；`argv[1:]` 路径组件含 hint→60；完全不含→0。`find_openclaw_main_pid` 在 `cached` 有效时 `discovery.method=="cached"` 且不扫全量 `/proc`；多候选时 `cwd` 在 `openclaw_root` 下的候选获得 `cwd_boost +20`；无候选时 `method=="no_match"` 返回 `None`。 |
| 主要测试文件 | 被测：`auditor/monitor/proc_info.py`（`_cmdline_match_score`、`find_openclaw_main_pid`、`_validate_cached`、`_path_under`）；测试脚本：`tests/unit/test_proc_info.py`（UT-PI-023~031） |
| 测试环境 | 同 F-3-5；以 spy 包裹 `_list_pids` 验证是否扫描全量 |
| 测试方法 | 1. 表驱动构造六档候选，逐一断言评分数值；2. 提供有效 `cached` 二元组，断言 `method=="cached"` 且 `_list_pids` 未被调用；3. 构造多候选（其一 cwd 在 `openclaw_root` 下），断言 `cwd_boost` 生效与 `selected_reason` 文案；4. 断言 `_validate_cached` 对"存活且 ticks 一致 / ticks 变化（PID 复用）/ pid 消失 / None"四态的复用决策；5. 断言 `_path_under` 对 `/root/.openclaw/x` 为 True、`/root/.openclaw2` 必须为 False；6. 无候选与自定义 `hint_keywords` 场景断言。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 六档评分逐一精确命中；`cached` 命中时确实跳过全量扫描；`cwd_boost +20` 生效并体现在 `selected_reason`；PID 复用（ticks 变化）被正确拒绝复用；`_path_under` 前缀误判防护有效；无候选时返回 `no_match` 且不抛异常。 |
| 验收判据（非执行结论） | 主进程定位与评分机制正确，缓存复用安全；需执行后判定。 |

#### 【F-3-7】进程树、祖先链与文件写者定位正确

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-3-7 |
| 测试要求 | `_build_pid_tree` 对多层父子、孤儿进程、`ppid=0` 正确构造 `{ppid:[children]}`；`find_descendants` 遵守 `max_depth` 与 `max_count` 且 `depth` 字段正确；`collect_ancestors` 能沿父链上溯到 pid 1 并输出 slim 结构；`find_pids_writing` 能按 fd 指向定位写者并支持 `exclude_self=True`；`collect_for_round` 返回顶层键完整且可 `json.dumps(default=str)`。 |
| 主要测试文件 | 被测：`auditor/monitor/proc_info.py`（`_build_pid_tree`、`find_descendants`、`collect_ancestors`、`find_pids_writing`、`collect_for_round`、`collect_system_context`）；测试脚本：`tests/unit/test_proc_info.py`（UT-PI-032~045） |
| 测试环境 | 同 F-3-5 |
| 测试方法 | 1. 构造 3 层伪进程树，断言树结构与 `max_depth=2` 截断、`depth` 字段；2. 子进程数超 `max_count` 时断言截断；3. 构造 4 层父链断言 `collect_ancestors` 层数与结构；4. 构造 fd 指向目标文件的进程，断言写者列表与 `exclude_self` 生效；5. 执行 `collect_for_round`，断言顶层键 `openclaw_root`/`jsonl_path`/`captured_at`/`discovery`/`main`/`ancestors`/`descendants`/`main_selinux_label`/`main_exec_label`/`tool_subprocess_labels`/`system`/`collect_duration_ms` 齐全；6. 断言返回值可 JSON 序列化；7. 断言 `collect_system_context` 对 SELinux `enforcing`/`permissive`/`disabled` 与 AppArmor 启用/禁用的结构。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 进程树、祖先链、写者定位全部正确；`max_depth`/`max_count` 截断生效；`collect_for_round` 顶层键齐全，`tool_subprocess_labels` 每项含 `pid`/`comm`/`cmdline`/`label` 且与 `descendants` 一致；返回值可 JSON 序列化（watcher 直接序列化落库）；`collect_duration_ms` 为非负数值；SELinux/AppArmor 状态结构正确。 |
| 验收判据（非执行结论） | 进程关系采集与系统上下文采集正确，输出结构可直接落库；需执行后判定。 |

#### 【F-3-8】IR 客户端请求构造与响应处理正确

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-3-8 |
| 测试要求 | `query` 为空、`None`、`"(not found)"` 时直接返回 `({}, "empty query")` 且不发起 HTTP；响应 `{"ok":true,"data":{...}}` 返回 `(data, None)`；响应为 JSON 数组或标量时包装为 `{"value": parsed}`；请求须为 POST、`Content-Type: application/json`、`User-Agent: ClawAVC-Monitor/1.0`、body 为 `ensure_ascii=False` 的 UTF-8；默认 `timeout == 300.0`、`use_llm=True`。 |
| 主要测试文件 | 被测：`auditor/monitor/ir_client.py`（72 行）；测试脚本：`tests/unit/test_ir_client.py`（UT-IRC-001~012） |
| 测试环境 | Ubuntu 22.04；monkeypatch `urllib.request.urlopen`，断言传入的 `Request` 对象属性 |
| 测试方法 | 1. 三类空 query 断言短路返回且 `urlopen` 未被调用；2. 分别 mock 四类响应体（标准 ok、`ok:false`、JSON 数组、标量），断言返回值；3. 断言请求对象的 method/headers/body 编码；4. 断言中文 query 不被转义为 `\uXXXX`；5. 断言默认参数取值。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 空 query 短路正确；标准响应与数组/标量包装正确；请求构造属性全部符合约定；中文 query 以 UTF-8 原文发送。注：`{"ok":false,"error":"x"}` 时返回 `(整个 parsed, None)`，error 不被转为第二个返回值，该语义待固化；默认端点为 `/api/translator/translate` 而 docstring 写 `/api/translator/test`，文档不一致待复核（附录 C 第 17 项）。 |
| 验收判据（非执行结论） | IR 客户端请求构造与响应处理正确，行覆盖率达 100%；需执行后判定。 |

#### 【F-3-9】监控编排上报链路完整

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-3-9 |
| 测试要求 | `MonitorOrchestrator` 初始化默认 `openclaw_log_root=~/.openclaw`、`gateway_log_path=""`、`running=False`、`_main_pid_cache=None`；`_on_round_start` 以正确参数调用 `collect_for_round(openclaw_root, jsonl_path=r.source_file, cached_main=...)` 并在采集含 `main.pid` + `start_time.clock_ticks` 时更新缓存；`_query_and_ir_worker` 先上报 `ir_json=LOADING_MARKER("__loading__")` 再调 `ir_translate` 并上报结果；`_on_round_end` 取回 IR、调 `judge(actions, ir)` 并组装完整上报体。 |
| 主要测试文件 | 被测：`auditor/monitor/watcher.py`（`MonitorOrchestrator`、`report_to_clawavc`）；测试脚本：`tests/unit/test_watcher_lifecycle.py`（UT-WT-060~076） |
| 测试环境 | 同 F-3-1；`ir_translate`/`judge`/`collect_for_round`/`report_to_clawavc` 全部 mock，不启动真实线程，全局 `--timeout=30` |
| 测试方法 | 1. 断言初始化默认值；2. 断言 `_on_round_start` 的调用参数与缓存更新条件（缺 `main` 或缺 ticks 时不更新）；3. 断言 round_start 上报体含 `event=start`/`round_id`/`time_start`/`session_key`/`attack_config`/`pid_info`（JSON 字符串）/`history`；4. 断言 `_query_and_ir_worker` 的两次上报顺序与超时降级；5. 断言 `_on_round_end` 上报体含 `time_end`/`user_query`/`last_llm_message`/`action_json`/`ir_json`/`judge_result`/`overall_score`/`is_abnormal`；6. 断言 `overall_score <= 0.5` → `is_abnormal=1`；7. 断言常量 `CLAWAVC_ROUNDS_API`/`POLL_INTERVAL=0.5`/`IDLE_END_SECONDS=5.0`/`DEFAULT_OPENCLAW_LOG_ROOT` 与文档一致。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 初始化默认值与常量契约全部一致；采集参数与缓存更新条件正确；两阶段 IR 上报顺序符合"先占位后回填"的设计；结束上报体字段齐全；分数到异常标记的换算符合 README 阈值；同 `round_id` 二次 start 幂等。 |
| 验收判据（非执行结论） | 监控编排上报链路完整，四阶段上报契约可固化；需执行后判定。 |

### 3.2 性能验证

1. 【P-3-1】单次进程与安全上下文采集耗时
2. 【P-3-2】日志扫描吞吐
3. 【P-3-3】IR 客户端长链路超时配置

#### 【P-3-1】单次进程与安全上下文采集耗时

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | P-3-1 |
| 测试要求 | `collect_for_round` 单次采集（主进程 + 4 层祖先 + 20 个子孙 + 系统上下文）耗时应小于 500ms，且 `collect_duration_ms` 字段真实反映耗时，确保不阻塞 round_start 上报。 |
| 主要测试文件 | 被测：`auditor/monitor/proc_info.py`；测试脚本：`tests/unit/test_proc_info.py::test_collect_perf`（UT-PI-043） |
| 测试环境 | Ubuntu 22.04，内存 16GB；伪 `/proc` 树（1 主进程 + 4 祖先 + 20 子孙，每进程 12 个字段文件） |
| 测试方法 | 1. 构造上述规模伪 `/proc`；2. 执行 100 次 `collect_for_round` 取均值与 P95；3. 比对 `collect_duration_ms` 与外部计时差值。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 默认及 FD 采样模式耗时、P95、内外计时偏差均未测；对伪目录验证 500ms 目标，不能外推为真实 procfs 性能。计时字段正确性与机器性能分开断言。 |
| 验收判据（非执行结论） | 采集耗时远低于 500ms 阈值，不会阻塞上报链路；需执行后判定。 |

#### 【P-3-2】日志扫描吞吐

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | P-3-2 |
| 测试要求 | `FileTailer` + `parse_line` 组合对 10 万行会话日志的解析吞吐应大于 2 万行/秒；`POLL_INTERVAL=0.5` 的轮询周期内可消化的增量应远大于真实产出速率。 |
| 主要测试文件 | 被测：`auditor/monitor/watcher.py`；测试脚本：`tests/unit/test_watcher_parse.py::test_tail_parse_throughput` |
| 测试环境 | 同 P-3-1；`tmp_path` 写入 10 万行真实结构 jsonl（约 85MB） |
| 测试方法 | 1. 生成 10 万行日志；2. 一次性扫描并逐行 `parse_line`，记录总耗时；3. 计算吞吐并断言阈值；4. 分别测量纯扫描与含解析的耗时占比。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 扫描耗时、有效解析条数及吞吐未测；以实际处理条数/耗时核对 >2 万行/秒目标，单列畸形行、扫描和解析开销，不虚填分段占比。 |
| 验收判据（非执行结论） | 日志扫描与解析吞吐满足实时监控需求；需执行后判定。 |

#### 【P-3-3】IR 客户端长链路超时配置

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | P-3-3 |
| 测试要求 | `ir_client` 默认 `timeout == 300.0`（5 分钟，适配两阶段 LLM 长链路）；超时后返回 `({}, str(exc))` 而非抛异常；`turn-ir` 侧等待窗默认 `300_000` ms 并夹取到 `[5_000, 1_800_000]`。 |
| 主要测试文件 | 被测：`auditor/monitor/ir_client.py`、`app.py`（`_get_turn_ir_wait_ms_config`）；测试脚本：`tests/unit/test_ir_client.py`（UT-IRC-007、UT-IRC-010）、`tests/api/test_intercept_turnir_api.py`（UT-API-100） |
| 测试环境 | 同 P-3-1；以 mock 抛出 `socket.timeout` 模拟超时 |
| 测试方法 | 1. 断言默认参数值；2. mock 超时异常，断言返回值结构与耗时不额外阻塞；3. 断言等待窗未配置 / 合法 / 越界三态的夹取结果。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 默认 `timeout=300.0` 与 `use_llm=True` 一致；超时被捕获并返回错误串；等待窗默认 300000ms，`4_999` 与 `1_800_001` 被夹取到边界值。 |
| 验收判据（非执行结论） | 长链路超时配置与边界夹取正确；需执行后判定。 |

### 3.3 安全性验证

1. 【S-3-1】环境变量白名单保证密钥不落库
2. 【S-3-2】不采集 ClawAVC 自身标签并排除自身进程
3. 【S-3-3】敏感 payload 不进入监控事件

#### 【S-3-1】环境变量白名单保证密钥不落库

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | S-3-1 |
| 测试要求 | 伪 `environ` 同时含 `PATH`/`USER`/`HOME`/`LANG`/`CONTAINER` 与 `OPENAI_API_KEY`/`TOKEN`/`SECRET` 时，`collect_pid_info` 输出中仅出现白名单键，密钥类键必须完全不存在；对采集结果全文搜索 `KEY`/`TOKEN`/`SECRET`/`PASSWORD` 无命中。 |
| 主要测试文件 | 被测：`auditor/monitor/proc_info.py`（环境变量白名单）；测试脚本：`tests/unit/test_proc_info.py`（UT-PI-018）、`tests/api/test_joint_permission.py`（UT-JP-033） |
| 测试环境 | 同 F-3-5 |
| 测试方法 | 1. 构造含 8 个环境变量（5 白名单 + 3 密钥类）的伪 `environ`；2. 执行 `collect_pid_info`，断言 env 字段键集合等于白名单交集；3. 对 `json.dumps` 后的完整采集结果做大小写不敏感全文检索，断言 4 类敏感关键词零命中。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | env 字段仅含白名单键；全文检索 4 类敏感关键词零命中，密钥不会随 `pid_info` 落入数据库。 |
| 验收判据（非执行结论） | 环境变量白名单有效，满足 README 的"防 token 落 DB"安全约束；需执行后判定。 |

#### 【S-3-2】不采集 ClawAVC 自身标签并排除自身进程

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | S-3-2 |
| 测试要求 | `collect_system_context` 输出不含 ClawAVC 自身 label 类字段；`find_openclaw_main_pid` 须排除 comm 为 `bash`/`sh`/`zsh`/`fish`/`dash`/`ksh`/`csh`/`tmux`/`tmux: server`/`screen`/`sudo`/`su`/`systemd`/`init`/`login`/`sshd`/`agetty` 的候选（即使其 cwd/argv 含 `openclaw`），并排除 cmdline 含 `clawavc`/`claw-avc`/`claw_avc` 的候选。 |
| 主要测试文件 | 被测：`auditor/monitor/proc_info.py`（黑名单与排除关键字）；测试脚本：`tests/unit/test_proc_info.py`（UT-PI-028~029、UT-PI-038）、`tests/api/test_joint_permission.py`（UT-JP-034） |
| 测试环境 | 同 F-3-5 |
| 测试方法 | 1. 为 17 个黑名单 comm 各构造一个"cwd/argv 含 openclaw"的高分候选，断言全部被排除、永不被选为主进程；2. 构造 3 类 ClawAVC 自身 cmdline 候选，断言被排除；3. 检查 `system` 与 `main` 字段，断言无 `clawavc_self_label` 类字段。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 17 个黑名单 comm 候选全部被排除；3 类自身 cmdline 候选被排除，避免 ClawAVC 把自己识别为被监控对象；系统上下文不含自身标签字段。 |
| 验收判据（非执行结论） | 监控主体与被监控对象边界清晰，符合 README 安全约束；需执行后判定。 |

#### 【S-3-3】敏感 payload 不进入监控事件

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | S-3-3 |
| 测试要求 | `parse_line` 对 `BLOCKED_PAYLOAD_KEYS` 命中的字段不写入事件；网关解析中 `user_query` 与 `last_llm_message` 之外的原始报文不被整体透传落库。 |
| 主要测试文件 | 被测：`auditor/monitor/watcher.py`（`BLOCKED_PAYLOAD_KEYS`、网关解析）；测试脚本：`tests/unit/test_watcher_parse.py`（UT-WT-016）、`tests/unit/test_watcher_lifecycle.py`（UT-WT-051~052） |
| 测试环境 | 同 F-3-1 |
| 测试方法 | 1. 构造含 `BLOCKED_PAYLOAD_KEYS` 全部键名的日志行，断言产出事件中不含这些键；2. 构造含 Authorization 头与完整请求体的网关报文，断言上报体仅含约定字段；3. 对最终上报体全文检索敏感关键词。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 被屏蔽键全部未进入事件；网关上报体仅含 `user_query`/`last_llm_message`/`action_json` 等约定字段，原始报文与鉴权头不落库；全文检索无敏感命中。 |
| 验收判据（非执行结论） | 监控事件的数据最小化原则得到落实；需执行后判定。 |

### 3.4 可靠性验证

1. 【R-3-1】残缺 `/proc` 只降级不崩溃
2. 【R-3-2】日志轮转、截断与非 UTF-8 编码容错
3. 【R-3-3】PID 复用与循环父子引用防护
4. 【R-3-4】采集与上报异常不阻塞监控主流程

#### 【R-3-1】残缺 `/proc` 只降级不崩溃

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | R-3-1 |
| 测试要求 | 进程在采集中途消失（目录被删除）时返回部分字段而不抛异常；`status`/`stat`/`attr` 等文件缺失或无权限时对应字段为 `None`；`_list_pids` 对混合数字与非数字目录（`self`/`net`/`sys`）只返回数字 pid；主进程定位失败时 `collect_for_round` 仍返回结构完整的字典并带 note。 |
| 主要测试文件 | 被测：`auditor/monitor/proc_info.py`；测试脚本：`tests/unit/test_proc_info.py`（UT-PI-001~002、UT-PI-019、UT-PI-022、UT-PI-041） |
| 测试环境 | 同 F-3-5；以 `chmod 000` 与中途 `shutil.rmtree` 模拟权限与消失场景 |
| 测试方法 | 1. 采集过程中删除伪进程目录，断言返回部分字段且不抛异常；2. 逐个移除 12 类字段文件，断言对应字段为 `None` 且其余字段正常；3. 构造混合目录断言 `_list_pids` 过滤；4. 清空所有候选，断言 `collect_for_round` 返回结构完整、`main` 为空并带 note。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 12 类字段文件缺失场景全部只降级不崩溃；进程中途消失时返回已采集到的部分字段；非数字目录被过滤；主进程定位失败时结构完整且不抛异常。 |
| 验收判据（非执行结论） | 采集层对残缺 `/proc` 具备完整降级能力；需执行后判定。 |

#### 【R-3-2】日志轮转、截断与非 UTF-8 编码容错

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | R-3-2 |
| 测试要求 | `FileTailer` 对路径不存在、路径是目录、无权限的情况跳过该路径而其他路径正常（整块 `except: continue`）；对非 UTF-8 字节以 `errors="replace"` 处理而不抛 `UnicodeDecodeError`；轮转与截断后自动重新定位。 |
| 主要测试文件 | 被测：`auditor/monitor/watcher.py`（`FileTailer`）；测试脚本：`tests/unit/test_watcher_parse.py`（UT-WT-003~006） |
| 测试环境 | 同 F-3-1 |
| 测试方法 | 1. 同时传入 4 个路径（正常 / 不存在 / 目录 / 无权限），断言仅正常路径产出行；2. 写入 GBK 编码与随机字节行，断言不抛异常且以替换字符解码；3. 轮转与截断后断言重新读取。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 异常路径被跳过且不影响正常路径；非 UTF-8 字节以替换字符解码，`parse_line` 对其返回 `None`；轮转与截断后自动重新定位。 |
| 验收判据（非执行结论） | 日志层编码与路径异常容错完备；需执行后判定。 |

#### 【R-3-3】PID 复用与循环父子引用防护

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | R-3-3 |
| 测试要求 | `_validate_cached` 在 pid 存活但 `starttime` ticks 变化（PID 复用）时必须拒绝复用；`find_descendants` 在人工构造 ppid 环（循环父子引用）时不得无限递归，须有访问集合保护。 |
| 主要测试文件 | 被测：`auditor/monitor/proc_info.py`（`_validate_cached`、`find_descendants`）；测试脚本：`tests/unit/test_proc_info.py`（UT-PI-023、UT-PI-035） |
| 测试环境 | 同 F-3-5；全局 `--timeout=30` 兜底防止死循环挂起 |
| 测试方法 | 1. 构造"pid 相同但 ticks 不同"的伪进程，断言 `_validate_cached` 返回拒绝；2. 构造 A→B→A 的 ppid 环，执行 `find_descendants` 并断言在超时前正常返回、结果无重复节点。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | ticks 变化时拒绝复用缓存，避免把复用 PID 的无关进程当作 OpenClaw 主进程；ppid 环场景下访问集合生效，函数正常返回且无重复节点，未触发超时。 |
| 验收判据（非执行结论） | PID 复用与循环引用防护有效；需执行后判定。 |

#### 【R-3-4】采集与上报异常不阻塞监控主流程

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | R-3-4 |
| 测试要求 | `collect_for_round` 抛异常时被捕获并打印 `[monitor] pid_info ...`，round_start 上报照常执行（README 承诺"不阻塞 round 上报"）；`report_to_clawavc` 在 HTTP 失败、超时、非 200 时捕获并打印，不中断监控循环；`ir_translate` 返回 error 时不上报脏 IR；`_query_and_ir_worker` 超时未找到 query 时不调用翻译并明确降级。 |
| 主要测试文件 | 被测：`auditor/monitor/watcher.py`（`_on_round_start`、`_on_round_end`、`report_to_clawavc`）；测试脚本：`tests/unit/test_watcher_lifecycle.py`（UT-WT-064、UT-WT-067~073） |
| 测试环境 | 同 F-3-1；以 mock 注入采集异常、HTTP 异常与翻译错误 |
| 测试方法 | 1. 使 `collect_for_round` 抛 `RuntimeError`，断言 round_start 上报仍被调用且 `pid_info` 为空串；2. 分别注入 HTTP 失败/超时/非 200，断言监控循环继续；3. 使 `ir_translate` 返回 error，断言未上报 IR 字段；4. 使 worker 超时，断言走降级路径且 round 仍完成上报；5. 使 `judge` 抛异常，断言被捕获且上报体降级。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 五类异常注入下监控主流程均未中断：采集异常不影响 round_start、上报异常不影响循环、翻译错误不产生脏 IR、worker 超时仍完成 round 上报、判定异常被捕获后上报降级结果。 |
| 验收判据（非执行结论） | 采集与上报链路的异常隔离符合"只降级不崩溃"的设计承诺；需执行后判定。 |

---

## 四、数据服务与接口权限管控模块

### 4.1 功能验证

验证的基本目标：

1. 【F-4-1】建表、索引与增量迁移功能完备
2. 【F-4-2】rounds 读写与防覆盖规则正确
3. 【F-4-3】字段白名单更新与 15 分钟时间窗正确
4. 【F-4-4】内核态信息上报入库正确
5. 【F-4-5】config 与翻译日志读写正确
6. 【F-4-6】rounds/stats 接口契约与 WebSocket 推送时序正确
7. 【F-4-7】模拟攻击配置与 webhook 功能完备
8. 【F-4-8】API 文档自动生成功能完备

#### 【F-4-1】建表、索引与增量迁移功能完备

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-4-1 |
| 测试要求 | `init_db` 在空库首次执行时建出 `rounds`/`translation_log`/`config`/`attack_messages`/`intercept_events`/`api_trace`/`anomaly_chats` 七表与 `idx_rounds_time`/`idx_rounds_abnormal` 索引，且连续执行两次幂等；对缺列的旧 `rounds` 表须依次补齐 `attack_config`/`pid_info`/`kernel_syscall_seq`/`kernel_lsm_hook_result`/`kernel_resource_facts`/`judge_result_kernel`/`syscall_judge`/`history`/`anomaly_llm_v2_judge_res`/`anomaly_llm_v2_chat_session` 共 10 列并保留存量数据；`get_conn` 须启用 `row_factory=sqlite3.Row`、`check_same_thread=False`、`journal_mode=WAL`、`synchronous=NORMAL`。 |
| 主要测试文件 | 被测：`db.py`（`get_conn`、`init_db`）；测试脚本：`tests/unit/test_db_rounds.py`（UT-DB-001~006） |
| 测试环境 | 目标 Python 3.14；首次导入前按 E.3 建立隔离，真实 SQLite 仅连接 tmp_path 内测试库；autouse 只作补充，不承担首次导入保护。 |
| 测试方法 | 空库与多版本旧 schema 分别初始化，核对全部业务表、索引和连接属性；重复执行检查幂等；为旧 resource_facts 列填充唯一标识，迁移后检查字段和值保留；用受控旧 schema 验证迁移条件和异常路径。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 建表、增量迁移与数据保留待验证。`cols` 是 ALTER TABLE 前获取的列快照，不能仅因前面已添加目标列就断言旧列迁移条件恒假；原死代码结论撤回，RISK-014 保留为迁移语义待复核。 |
| 验收判据（非执行结论） | 建表与增量迁移功能完备，向后兼容旧库结构；需执行后判定。 |

#### 【F-4-2】rounds 读写与防覆盖规则正确

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-4-2 |
| 测试要求 | `insert_round_start` 占位值正确（`overall_score=-1.0`、`is_abnormal=0`、`action_json="[]"`、`ir_json="{}"`、`time_end=""`）且同 `round_id` 重复插入返回 `None`、原记录不被覆盖；`update_round_end` 的防覆盖规则正确：`user_query`/`judge_result`/`time_end`/`last_llm_message`/`history` 传 `None` 或 `""` 时跳过；`action_json="[]"` 与 `ir_json="{}"`/`"__loading__"` 在 DB 已有真实值时跳过；`overall_score=0` 与 `is_abnormal=0/False` 不被当空值跳过；未知字段被忽略；全部字段被跳过时返回 `False`。`get_rounds`/`get_round_by_id`/`get_stats` 语义正确。 |
| 主要测试文件 | 被测：`db.py`（`insert_round_start`、`update_round_end`、`insert_round`、`get_rounds`、`get_round_by_id`、`get_stats`）；测试脚本：`tests/unit/test_db_rounds.py`（UT-DB-010~040） |
| 测试环境 | 同 F-4-1；`seeded_round` fixture 提供已插入的 round_id |
| 测试方法 | 1. 插入并读回，逐字段断言占位值；2. 同 round_id 二次插入，断言返回 `None` 与原记录不变；3. 表驱动覆盖 11 组防覆盖入参组合，断言 DB 前后值；4. 传入未知字段 `foo`，断言不参与 SET；5. 全字段跳过时断言返回 `False` 且未执行 UPDATE；6. `round_id` 不存在时断言返回 `False`（触发 app 层 legacy fallback）；7. `get_rounds` 断言默认 `limit=50, offset=0`、`{total,data}` 结构、`abnormal_only`、模糊筛选（含 `%`/`_`/单引号/中文）、时间范围叠加、分页边界（`limit=0`/越界 offset/负 limit）与 `time_start DESC` 排序；8. `get_stats` 断言空库不除零。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 占位值与唯一约束行为正确；11 组防覆盖组合全部符合设计（含"portkey 早先回填的真实 IR 不被覆盖"场景）；`0`/`False` 被正确写入而非跳过；未知字段被忽略（防注入）；分页与筛选边界均不抛异常，参数化查询不被注入；空库统计不除零。 |
| 验收判据（非执行结论） | rounds 读写与防覆盖规则正确，数据不会被占位值污染；需执行后判定。 |

#### 【F-4-3】字段白名单更新与 15 分钟时间窗正确

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-4-3 |
| 测试要求 | `update_round_field` 的 `UPDATABLE_FIELDS = [action_json, ir_json, judge_result, judge_result_kernel, syscall_judge]` 逐个可更新并返回 `"ok"`；白名单外字段返回 `"unsupported"`；`round_id` 不存在返回 `"not_found"`；`created_at` 超 15 分钟返回 `"too_old"`，`time_limit_enabled=False` 时放行；`created_at` 为 `NULL` 时跳过校验、格式错误时返回 `"error"`。 |
| 主要测试文件 | 被测：`db.py`（`update_round_field`）；测试脚本：`tests/unit/test_db_config_kernel.py`（UT-DB-050~057） |
| 测试环境 | 同 F-4-1；`freezegun` 固定与推进时间 |
| 测试方法 | 1. 逐个白名单字段更新并读回断言；2. 白名单外字段与注入型字段名断言 `"unsupported"`；3. 不存在的 round 断言 `"not_found"`；4. 以 freezegun 构造 `created_at` 距今 14 分 59 秒与 15 分 01 秒，断言 `"ok"`/`"too_old"`；5. 关闭 `round_update_time_limit` 后对超期记录断言 `"ok"`；6. `created_at` 为 `NULL` 与格式错误时断言跳过与 `"error"`。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 5 个白名单字段全部可更新；白名单外字段与注入型字段名被拒绝；时间窗边界精确到秒；开关关闭后放行；`NULL` 与格式错误分支符合预期。注：`created_at` 由 SQLite `CURRENT_TIMESTAMP`（UTC）写入而校验使用 `datetime.now()`（本地时区），东八区环境下刚创建的记录也会被判 `"too_old"`，属高危功能缺陷，待复核（附录 C 第 1 项），用例以实测结果固化。 |
| 验收判据（非执行结论） | 白名单机制与时间窗逻辑本身正确；时区不一致缺陷待复现并评审修复。尚未执行；关联风险须复现和关闭，不以“条件通过”替代验收。 |

#### 【F-4-4】内核态信息上报入库正确

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-4-4 |
| 测试要求 | `update_kernel_info` 在三个源文件存在时复制到 `infos/kernel_infos/<round_id>/<round_id>_syscall_seq.jsonl` 与 `_lsm_hook_result.jsonl`，`kernel_resource_facts` 存文件内容而非路径，返回 `"ok"`；目标文件已存在时覆盖成功；三路径全为空串时写空串返回 `"ok"`（清空语义）；`update_judge_result_kernel` 与 `update_syscall_judge_json` 四态返回正确；`parse_json_input` 对合法 JSON 串/dict/list/非 JSON 串/`None`/超深嵌套统一返回 dict。 |
| 主要测试文件 | 被测：`db.py`（`update_kernel_info`、`update_judge_result_kernel`、`update_syscall_judge_json`、`parse_json_input`、`update_anomaly_llm_v2_judge`）；测试脚本：`tests/unit/test_db_config_kernel.py`（UT-DB-060~070） |
| 测试环境 | 同 F-4-1；源文件与 `infos` 目录均位于 `tmp_path` |
| 测试方法 | 1. 构造三个源文件执行上报，断言目标路径、文件内容与 `kernel_resource_facts` 字段内容；2. 目标已存在时断言覆盖；3. 任一源路径不存在时断言返回 `"error"` 并记录副作用；4. 三路径全空断言清空语义；5. 断言校验顺序（文件复制是否先于 `not_found`/`too_old` 校验）；6. `round_id` 含 `../` 时断言实测行为；7. 四态断言 `update_judge_result_kernel`；8. 六态断言 `parse_json_input`；9. 断言 `update_anomaly_llm_v2_judge` 不受 15 分钟限制。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 正常路径、覆盖、清空语义均正确；`parse_json_input` 六态统一返回 dict 不抛异常；`update_anomaly_llm_v2_judge` 确认不受时间窗限制。注：①文件复制与目录创建发生在 `not_found`/`too_old` 校验之前，不存在的 round 会产生残留目录；②`infos_dir` 直接用 `round_id` 拼接，`../` 存在路径穿越面。两项待复核（附录 C 第 2 项）。 |
| 验收判据（非执行结论） | 内核态上报入库功能正确；校验顺序与路径拼接缺陷待复现并评审修复。尚未执行；关联风险须复现和关闭，不以“条件通过”替代验收。 |

#### 【F-4-5】config 与翻译日志读写正确

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-4-5 |
| 测试要求 | `get_config`/`set_config` 写读往返、覆盖同 key、默认值回退语义正确；`init_config_table` 与 `init_db` 中的重复建表幂等，`_init_translator_prompts` 默认提示词只在缺失时写入；`get_configs_by_prefix` 对 `monitor_conf.`/`ir_translator.`/`attack.inject.` 前缀匹配正确；翻译日志的 pending→level1→upsert 三段式写入正确。 |
| 主要测试文件 | 被测：`db.py`（`get_config`、`set_config`、`init_config_table`、`get_configs_by_prefix`、`insert_translation_log*`、`update_translation_log_level1`、`insert_or_update_translation_log`、`get_translation_logs`）；测试脚本：`tests/unit/test_db_config_kernel.py`（UT-DB-080~083、UT-DB-090~095） |
| 测试环境 | 同 F-4-1 |
| 测试方法 | 1. config 写读往返、覆盖、默认值回退、key 不存在四态断言；2. 连续调用两个建表函数断言幂等，并断言默认提示词不覆盖已有值；3. 三类前缀与含 `%`/`_` 的 prefix 断言匹配行为；4. 建 pending 记录断言 `level1_json`/`level2_json` 为空；5. Level-1 完成后断言仅更新 `level1_json`/`meta_json`；6. 同 round 二次调用断言 upsert 而非新增；7. `round_id=None`（UI 测试）断言走 insert 分支；8. 分页与 `ui_only` 筛选断言。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | config 读写与前缀匹配语义正确；重复建表幂等；翻译日志三段式写入与 upsert 语义符合 README 的"3 次更新"流程；UI 测试日志与真实 round 隔离。注：`set_config` 在 `db.py:1067` 与 `db.py:1320` 被重复定义，实际生效为后者（返回值语义不同），待复核（附录 C 第 12 项）。 |
| 验收判据（非执行结论） | 配置与翻译日志读写正确；重复定义问题待复核待清理；需执行后判定。 |

#### 【F-4-6】rounds/stats 接口契约与 WebSocket 推送时序正确

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-4-6 |
| 测试要求 | `GET /api/rounds`、`GET /api/rounds/query`、`PUT /api/rounds/update`、`POST /api/rounds`（start/end）、`POST /api/rounds/kernel`、`POST /api/rounds/detection/kernel`、`POST /api/rounds/detection/syscall`、`GET /api/stats` 的状态码与返回结构符合契约；db 返回码到 HTTP 的映射为 `not_found→404`、`too_old→400`、`unsupported→400`、`error→500`；推送时序满足"`round_start` 必须最先"，`round_ir_ready`/`round_end` 的 `ir_json`/`action_json` 取自 DB record 而非请求体；请求体 `ir_json` 为 `""`/`"__loading__"` 时不推送 `round_ir_ready`，DB `action_json` 为 `"[]"` 时不推送 `round_end`；`broadcast_push` 推送到 `/wss/monitor` 命名空间的 `push` 事件。 |
| 主要测试文件 | 被测：`app.py`（rounds 接口族、`broadcast_push`）；测试脚本：`tests/api/test_rounds_api.py`（UT-API-001~030） |
| 测试环境 | Ubuntu 22.04；`flask_client` fixture（依赖 `temp_db`，mock `socketio.emit`/`broadcast_push`/`_send_webhook`）；`tests/api` 与 `tests/unit` 分进程执行以隔离 gevent monkey-patch |
| 测试方法 | 1. 逐接口断言正常与异常入参的状态码与返回结构；2. 以 mock 让 db 分别返回四种状态码，断言 HTTP 映射；3. 依次调用 start→ir_ready→end→kernel，断言 `push_type` 序列；4. 断言推送取值来源为 DB record；5. 断言两类占位值下的"不推送"行为；6. 断言 `socketio.emit` 与 `broadcast_push` 的调用次数与命名空间；7. 断言 `event=start` 未携带 `attack_config` 时走 `_read_all_attack_config()` 本地兜底；8. 断言 `event=end` 在 `update_round_end` 返回 False 时走 legacy `insert_round` 映射，且非法 JSON 降级为 `[]`/`{}`。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 接口状态码与结构契约全部符合；四类 db 返回码映射正确；推送时序与取值来源符合 README 契约；两类占位值的"不推送"行为正确，避免与 worker 重复推送；本地兜底与 legacy 降级路径正常。注：`GET /api/rounds` 实际默认 `limit=50` 而 `@api_doc` 声明 20，文档不一致待复核（附录 C 第 17 项）。 |
| 验收判据（非执行结论） | rounds 接口契约与推送时序正确；需执行后判定。 |

#### 【F-4-7】模拟攻击配置与 webhook 功能完备

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-4-7 |
| 测试要求 | `ATTACK_GROUPS` 覆盖 `tool_injection`（network/filepath/syscall）与 `runtime_tamper`（replace/insert）；`attack.inject.<item>.enabled` 与 `.value` 成对读写，缺失项默认 `enabled=false,value=""`；`GET /api/attack/tool-config` 支持全名 `tool_injection.filepath` 与短名 `filepath`，未知 key 返回 404；`GET /api/attack/rules` 读取 `backend/static/rule_test_atk.json`（143 条规则），每条含 `rule_id`/`sequence`/`sequence_list`/`note`/`score`/`source` 且默认规则 `DT异常序列_003` 可检索；`ANY /api/webhook` 对 7 种 HTTP 方法均返回 200 并落 `attack_messages`（含 `request_method`）。 |
| 主要测试文件 | 被测：`app.py`（攻击配置族、`/api/webhook`、`_get_webhook_urls`、`_send_webhook`）、`db.py`（`insert_attack_message` 等）；测试脚本：`tests/api/test_attack_config_api.py`（UT-API-120~133） |
| 测试环境 | 同 F-4-6；`_send_webhook` 的网络调用 mock |
| 测试方法 | 1. 断言 `ATTACK_GROUPS` 常量结构；2. 逐项开关与内容写入后断言每项产生两条 config 记录；3. 两种 key 写法与未知 key 断言返回；4. 读取真实规则文件断言条数与字段完整性，并检索默认 `rule_id`；5. 规则文件缺失与非法 JSON 时断言明确错误不 500；6. 以 7 种方法请求 webhook，断言 200 与落库字段；7. 断言未配置 / 多 URL / 目标不可达 / 超时 5s 时不阻塞主流程。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 攻击分组与成对配置读写正确；两种 key 写法等价、未知 key 返回 404；143 条规则字段齐全且默认规则可检索；规则文件异常时返回明确错误；7 种 HTTP 方法全部 200 并正确记录 `request_method`；webhook 目标异常被吞不阻塞。 |
| 验收判据（非执行结论） | 模拟攻击配置与 webhook 功能完备；需执行后判定。 |

#### 【F-4-8】API 文档自动生成功能完备

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-4-8 |
| 测试要求 | `api_doc` 装饰器仅打标记、不改变被装饰函数行为与返回值；`generate_docs` 能反射出全部路由并按 `ENDPOINT_REGISTRY` > `@api_doc` > `docstring` 的优先级取元数据；`public_only=True` 只返回公开接口；传入 `public_list`（对应 config `api_docs.public_endpoints`）时动态覆盖 registry 标记；`_infer_category` 将路径正确分类到"数据查询与更新/运行监控/策略翻译/鉴权管理/数据库/配置/文档/其他"。 |
| 主要测试文件 | 被测：`api_docs.py`；测试脚本：`tests/unit/test_api_docs.py`（UT-DOC-001~011） |
| 测试环境 | Ubuntu 22.04；构造假 Flask app 注册若干路由，无需启动服务 |
| 测试方法 | 1. 装饰前后调用同一函数，断言返回值与副作用一致；2. 对假 app 执行 `generate_docs`，断言路由数、方法与路径；3. 构造三层元数据冲突场景，逐一验证优先级；4. 无元数据路由断言从 docstring 提取 summary、无 docstring 时不报错；5. `public_only=True` 与 `public_list` 两种模式断言过滤结果；6. 表驱动断言 8 类路径的分类映射；7. 断言含 `<scene_name>` 路径参数的路由被正确展示；8. `jsonify(generate_docs(app))` 断言可序列化。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 装饰器无侵入；路由反射完整；三层元数据优先级正确；`public_only` 与动态公开列表均生效；8 类路径分类映射正确；路径参数展示正常；输出可 JSON 序列化。 |
| 验收判据（非执行结论） | API 文档自动生成功能完备，实现"零手动维护"；需执行后判定。 |

### 4.2 性能验证

1. 【P-4-1】rounds 分页查询耗时
2. 【P-4-2】WAL 模式并发写入
3. 【P-4-3】API 文档生成耗时

#### 【P-4-1】rounds 分页查询耗时

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | P-4-1 |
| 测试要求 | 1 万条 rounds 记录下 `get_rounds`（默认 `limit=50`）耗时小于 100ms；带 `query` 模糊筛选与时间范围叠加的查询耗时小于 300ms；`get_stats` 全表聚合耗时小于 200ms。 |
| 主要测试文件 | 被测：`db.py`（`get_rounds`、`get_stats`）；测试脚本：`tests/unit/test_db_rounds.py::test_query_perf` |
| 测试环境 | Ubuntu 22.04，内存 16GB；`temp_db` 临时 SQLite（WAL），批量插入 1 万条含真实体量 `action_json`/`ir_json` 的记录 |
| 测试方法 | 1. 批量插入 1 万条记录并建索引；2. 分别执行默认分页、模糊筛选、时间范围叠加、深分页（offset=9950）与 `get_stats`，各 20 次取均值；3. 断言均值低于阈值。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 分页、筛选、深分页与聚合耗时均未测；分别保存计时和查询计划，再比较 100ms/300ms/200ms 目标，不能预先宣称命中索引或完成全表扫描。 |
| 验收判据（非执行结论） | 分页与统计查询性能满足前端交互要求；模糊筛选为全表扫描，数据量继续增长时建议补充索引或 FTS；需执行后判定。 |

#### 【P-4-2】WAL 模式并发写入

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | P-4-2 |
| 测试要求 | WAL 模式下两个连接同时 `insert_round_start` 同一 `round_id` 时 UNIQUE 约束生效、不产生重复行；并发读写不出现 `database is locked` 导致的用例失败；100 轮 start+end 顺序写入总耗时小于 5s。 |
| 主要测试文件 | 被测：`db.py`（`get_conn`、`insert_round_start`、`update_round_end`）；测试脚本：`tests/unit/test_db_rounds.py`（UT-DB-110） |
| 测试环境 | 同 P-4-1；使用两个独立连接（`check_same_thread=False`） |
| 测试方法 | 1. 两连接并发插入同一 round_id，断言表中仅 1 行；2. 一连接持续读、另一连接持续写，断言无锁异常；3. 连续 100 轮 start+end 写入，记录总耗时。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 唯一约束、并发冲突与 100 轮总耗时待测；断言同 round_id 只保留一条、事务结果一致，记录锁等待和失败而非重试掩盖；顺序写入目标 <5s。 |
| 验收判据（非执行结论） | WAL 并发模型满足监控上报的写入频率要求；需执行后判定。 |

#### 【P-4-3】API 文档生成耗时

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | P-4-3 |
| 测试要求 | 对 90+ 路由的真实 Flask app 执行 `generate_docs` 耗时小于 200ms，保证 `/api/docs` 可即时响应而无需缓存。 |
| 主要测试文件 | 被测：`api_docs.py`（`generate_docs`）；计划：`tests/api/test_api_docs_contract.py::test_generate_perf` |
| 测试环境 | 同 P-4-1；真实 app 的 url_map 仅在独立 API 进程中、导入隔离完成后使用 |
| 测试方法 | 记录实际路由数量，两种 public_only 模式各执行至少 50 次并保存原始计时；比较 200ms 目标。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 两种模式耗时未测；不得把假 app 的反射耗时写成真实全量路由性能。 |
| 验收判据（非执行结论） | 文档生成为纯反射计算，耗时可忽略；需执行后判定。 |

### 4.3 安全性验证

1. 【S-4-1】双层权限模型与权限基线矩阵
2. 【S-4-2】SQL 控制台只读判定与写操作鉴权
3. 【S-4-3】密钥类配置不可被 API 修改且不在响应中泄漏
4. 【S-4-4】未鉴权公开面基线快照与高危接口标注
5. 【S-4-5】SQL 注入防线（列名白名单 + 参数化查询）

#### 【S-4-1】双层权限模型与权限基线矩阵

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | S-4-1 |
| 测试要求 | 建立声明式权限期望表，参数化遍历全部路由，断言"无 token / 错误 token / 入门 token / 特权 token"四种身份下的状态码。`POST /api/auth` 正确/错误/空口令分别 200/401/401；`POST /api/admin/verify` 正确密钥返回 200 + 32 位 `session_token`（`sha256(key+time)[:32]`）+ `ttl`，错误密钥返回 401 且不产生会话；`_check_admin_session` 对有效/不存在/已过期 token 分别 `True/False/False` 且过期条目被删除；14 个特权接口在无特权或过期时返回 403，有效时非 403；`POST /api/translator/policies/switch` 免特权放行。 |
| 主要测试文件 | 被测：`app.py`（`/api/auth`、`/api/admin/verify`、`_check_admin_session`、全部特权接口）；测试脚本：`tests/api/test_auth_permission_matrix.py`（UT-PERM-001~010） |
| 测试环境 | 同 F-4-6；`entry_token` 与 `admin_session` fixture；autouse fixture 每例清空 `app._admin_sessions`；`freezegun` 推进到 `ADMIN_SESSION_TTL`（默认 1200s）边界前后 1 秒 |
| 测试方法 | 1. 三态口令断言鉴权接口状态码；2. 断言 session_token 长度、生成算法与 `ttl` 字段；3. 断言错误密钥不产生会话条目；4. 以 freezegun 推进到 TTL 边界前后 1 秒，断言会话有效性与过期条目删除；5. 断言 token A 不能用于验证 token B（会话隔离）；6. 以声明式期望表参数化遍历 14 个特权接口 × 4 种身份，逐一断言状态码；7. 断言 `GET /api/admin/session` 恒 200 且 `valid` 字段正确；8. 断言切换 Policy 接口免特权。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 鉴权、TTL、会话隔离和策略切换均待验证；56 组仅为原设计矩阵，需按真实路由清单复核，不是执行通过数量。权限快照与 CI 均未落地；TTL 双来源风险见 RISK-016。 |
| 验收判据（非执行结论） | 逐项匹配精确状态码、响应体与副作用，未授权不能执行受保护操作；有效权限不能仅以“非 403”判成功，矩阵执行后再验收。 |

#### 【S-4-2】SQL 控制台只读判定与写操作鉴权

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | S-4-2 |
| 测试要求 | `POST /api/db/query` 空 sql/纯空白返回 400；`SELECT` 类查询无特权放行；`INSERT`/`UPDATE`/`DELETE`/`DROP`/`ALTER`/`PRAGMA`/`ATTACH` 无特权返回 403；含 `CONFIG` 与 `SQLITE_SEQUENCE` 字样的查询无特权返回 403；特权会话下写操作放行且真实生效；语法错误返回 400 且不泄漏堆栈。须实测并固化"以 `sql.strip().upper().startswith("SELECT")` 判定"带来的绕过与误伤面。 |
| 主要测试文件 | 被测：`app.py`（`db_query`）；测试脚本：`tests/api/test_db_query_api.py`（UT-API-040~050） |
| 测试环境 | 同 F-4-6 |
| 测试方法 | 1. 空/空白 sql 断言 400；2. 大小写与前导空格的 SELECT 断言放行；3. 7 类写操作逐一断言 403；4. 前导注释 `-- x\nSELECT ...` 断言实测判定结果；5. `WITH x AS (SELECT 1) SELECT * FROM x` 断言实测结果；6. 三类含 `config` 字面量的查询断言实测结果；7. `SELECT * FROM sqlite_sequence` 断言 403；8. 多语句 `SELECT 1; DROP TABLE rounds` 断言实测行为；9. 特权会话下写操作断言放行并校验数据变化；10. 语法错误与表不存在断言 400 且响应体无堆栈。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 静态分支显示：strip 后去除前导空白；带前导注释或 WITH 的查询归为写操作，无特权时应被 403 拒绝，这是只读误拒绝，不是已证实绕过。CONFIG 字面量检查可能误伤；多语句及异常返回须在临时库复现，不能仅以字符串检查推断绝对安全。 |
| 验收判据（非执行结论） | 分别验证非特权写入阻断、合法只读需求和特权契约；RISK-005 待复核，不宣称鉴权绕过已复现或修复。 |

#### 【S-4-3】密钥类配置不可被 API 修改且不在响应中泄漏

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | S-4-3 |
| 测试要求 | `PUT /api/config` 在 `key == "admin_key"` 时返回 403 且 config 表中值不变；`key ∈ {secret_key, subdomain}` 无特权时 403；普通 key 无/错 `X-Auth-Token` 时 401。遍历所有写配置接口尝试写 `admin_key` 须全部拒绝；遍历所有 GET 接口响应体全文检索入门口令值与 `secret_key` 须无泄漏。`verify_secret`/`verify_admin` 在未设置对应 key 时拒绝任何口令，且为严格等值比较。 |
| 主要测试文件 | 被测：`app.py`（`update_config`）、`db.py`（`verify_secret`、`verify_admin`）；测试脚本：`tests/api/test_auth_permission_matrix.py`（UT-PERM-011~014）、`tests/unit/test_db_config_kernel.py`（UT-DB-084~086）、`tests/api/test_joint_permission.py`（UT-JP-030~032） |
| 测试环境 | 同 F-4-6 |
| 测试方法 | 1. 以特权与非特权身份分别 PUT `admin_key`，断言 403 与 DB 值不变；2. `secret_key`/`subdomain` 无特权断言 403；3. 普通 key 缺/错 token 断言 401；4. 遍历全部写配置接口尝试写 `admin_key`，断言全部拒绝；5. 遍历全部 GET 接口，对响应体全文检索预置口令值；6. 断言 `verify_secret`/`verify_admin` 在四态（正确/错误/空串/未设置）下的返回；7. 断言大小写、前后空格、Unicode 同形字符下的严格等值语义；8. 多 key 混合请求 `{"a":1,"admin_key":"x"}` 断言原子性。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | `admin_key` 在全部写入入口被拒绝、DB 值不变；`secret_key`/`subdomain` 特权校验生效；GET 响应全文检索无口令泄漏；`verify_*` 未设置对应 key 时拒绝任何口令并为严格等值比较。注：①多 key 混合写入为逐 key 循环、非原子，非法 key 之前的合法 key 已落库，待复核（附录 C 第 6 项）；②代码读取的是 `secret_key` 而 CLAUDE.md 写 `entry_password`，文档不一致待复核（附录 C 第 17 项）。 |
| 验收判据（非执行结论） | 密钥不可改、不泄漏的核心不变量成立；多 key 写入原子性缺陷待复现后评审修复。尚未执行；关联风险须复现和关闭，不以“条件通过”替代验收。 |

#### 【S-4-4】未鉴权公开面基线快照与高危接口标注

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | S-4-4 |
| 测试要求 | 核对 rounds、stats、import、db/tables、monitor、attack、webhook 与 kernel/file 路由的公开面。对每条实际 METHOD/path 建立经评审的权限表，不以路径通配符代替精确路由；导入和文件读取副作用必须隔离。 |
| 主要测试文件 | 被测：`app.py`；计划：`tests/api/test_auth_permission_matrix.py`，UT-PERM-015~017 |
| 测试环境 | 同 F-4-6；文件读取仅使用 tmp_path 内普通文件和允许目录外的合成哨兵文件，绝不读取主机敏感文件。 |
| 测试方法 | 无/错/有效权限分别请求，核对确切状态码、响应体与副作用；反向遍历 url_map 检查遗漏；导入函数使用 spy，文件正常/相对穿越/软链分别断言；核对 CORS 响应，不能只凭非 401/403 判请求成功。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 原公开面快照尚未建立或接入 CI；RISK-003/004 的未鉴权读取/导入风险待在临时沙箱复现。不宣称已经读出任何真实文件。 |
| 验收判据（非执行结论） | 实际公开面与批准契约一致，敏感副作用受权限和路径边界限制；风险复现/修复及回归均有证据后再验收。 |

#### 【S-4-5】SQL 注入防线（列名白名单 + 参数化查询）

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | S-4-5 |
| 测试要求 | `update_round_field` 因 SQL 以 f-string 拼列名，白名单是唯一防线：传入 `field="action_json = 1, is_abnormal"` 与 `field="1;DROP TABLE rounds--"` 须返回 `"unsupported"`，且表结构与数据完好；`get_rounds` 的 `query` 参数含 `%`、`_`、单引号、中文时必须走参数化查询不被注入；`update_round_end` 传入未知字段不参与 SET。 |
| 主要测试文件 | 被测：`db.py`（`update_round_field`、`get_rounds`、`update_round_end`）；测试脚本：`tests/unit/test_db_rounds.py`（UT-DB-030、UT-DB-035）、`tests/unit/test_db_config_kernel.py`（UT-DB-051~052） |
| 测试环境 | 同 F-4-1 |
| 测试方法 | 1. 喂入 6 组注入型 field 名，断言返回 `"unsupported"`；2. 断言操作后 `sqlite_master` 与各表行数完好；3. 以 `'; DROP TABLE rounds; --` 等注入串作为 `query` 参数执行查询，断言表完好且结果为空集；4. 传入未知字段断言不参与 SET。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 6 组注入型 field 名全部被白名单拒绝，表结构与数据零损坏；注入串作为查询条件被参数化转义，未产生任何 DDL 效果；未知字段被忽略。注：`field == "is_abnormal"` 分支因该字段不在 `UPDATABLE_FIELDS` 而不可达，确认为死代码并上报（附录 C 第 13 项）。 |
| 验收判据（非执行结论） | SQL 注入防线有效，列名白名单与参数化查询共同构成双重保护；需执行后判定。 |

### 4.4 可靠性验证

1. 【R-4-1】非法与缺失参数不导致 500
2. 【R-4-2】数据层返回码到 HTTP 状态码映射一致
3. 【R-4-3】重复上报与乱序调用的幂等性
4. 【R-4-4】文档与实现一致性元测试

#### 【R-4-1】非法与缺失参数不导致 500

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | R-4-1 |
| 测试要求 | `GET /api/rounds` 的 `limit` 为非数字/负数/超大值时不返回 500；`PUT /api/rounds/update` 空 body、缺 `round_id`、缺 `field` 均返回 400；`POST /api/rounds` 空 body 返回 400；`PUT /api/config/turn_ir_wait_ms` 对 `4_999`/`5_000`/`1_800_000`/`1_800_001`/非数字的边界校验正确且非法值返回 400 而非 500；`GET/PUT /api/config/navigator` 非法 JSON 返回 400。 |
| 主要测试文件 | 被测：`app.py`（rounds 与 config 接口族）；测试脚本：`tests/api/test_rounds_api.py`（UT-API-003、UT-API-005、UT-API-021）、`tests/api/test_intercept_turnir_api.py`（UT-API-101）、`tests/api/test_attack_config_api.py`（UT-API-145） |
| 测试环境 | 同 F-4-6 |
| 测试方法 | 1. 表驱动喂入 3 类非法 `limit`，断言状态码非 500；2. 三类缺参请求断言 400；3. 五类边界 `turn_ir_wait_ms` 断言校验结果；4. 非法 JSON 配置断言 400；5. 统计全部 API 用例中出现 500 的接口并逐一评审。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 非法 limit、缺参、等待窗边界和非法 JSON 的返回均待验证；需给出明确的批准契约，不能仅断言“不是 500”。本次没有执行全量 API，不预填无未预期 500 的结论。 |
| 验收判据（非执行结论） | 接口层参数校验完备，非法输入不会导致服务端异常；需执行后判定。 |

#### 【R-4-2】数据层返回码到 HTTP 状态码映射一致

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | R-4-2 |
| 测试要求 | `PUT /api/rounds/update`、`POST /api/rounds/kernel`、`POST /api/rounds/detection/kernel`、`POST /api/rounds/detection/syscall` 四个接口对 db 返回的 `not_found`/`too_old`/`unsupported`/`error` 须映射为一致的 404/400/400/500；`round_update_time_limit` 开关须被透传为 `time_limit_enabled`。 |
| 主要测试文件 | 被测：`app.py`（rounds 更新与内核态上报接口）、`db.py`；测试脚本：`tests/api/test_rounds_api.py`（UT-API-006、UT-API-008、UT-API-023）、`tests/api/test_joint_permission.py`（UT-JP-003） |
| 测试环境 | 同 F-4-6 |
| 测试方法 | 1. 对四个接口分别 mock db 返回四种状态码，断言 HTTP 状态码矩阵（4×4 共 16 组）；2. 关闭 `round_update_time_limit` 后断言 `time_limit_enabled=False` 被透传；3. 断言三个内核态接口受同一 15 分钟窗与同一开关控制、行为完全一致。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 16 组映射全部一致；开关透传正确；三个内核态上报接口的时间窗与开关行为一致，无接口遗漏开关控制。 |
| 验收判据（非执行结论） | 返回码映射统一，接口行为对齐；需执行后判定。 |

#### 【R-4-3】重复上报与乱序调用的幂等性

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | R-4-3 |
| 测试要求 | 同 `round_id` 二次 `event=start` 不产生重复行且不重复推送；内核态上报乱序到达（先 `/detection/kernel` 后 `/api/rounds/kernel`、先 kernel 后 end）时不丢数据、不互相覆盖；`update_round_end` 在 round 不存在时返回 `False` 并触发 app 层 legacy fallback。 |
| 主要测试文件 | 被测：`app.py`、`db.py`；测试脚本：`tests/api/test_rounds_api.py`（UT-API-012）、`tests/api/test_joint_permission.py`（UT-JP-004）、`tests/unit/test_db_rounds.py`（UT-DB-029） |
| 测试环境 | 同 F-4-6 |
| 测试方法 | 1. 同 round_id 连续两次 start，断言表中 1 行、`inserted` 分别 `True`/`False`、失败时不推送；2. 以两种乱序顺序上报，断言九类字段互不覆盖；3. round 不存在时 end 上报，断言走 legacy `insert_round` 路径。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 重复 start 幂等且不重复推送；两种乱序顺序下字段互不覆盖、数据无丢失；legacy fallback 正确触发并完成映射入库。 |
| 验收判据（非执行结论） | 重复与乱序上报具备幂等与容错能力；需执行后判定。 |

#### 【R-4-4】文档与实现一致性元测试

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | R-4-4 |
| 测试要求 | 遍历 `ENDPOINT_REGISTRY` 中每条 `"METHOD /path"`，须都能在真实 Flask `url_map` 中找到对应路由（防文档漂移）；反向遍历真实路由，标记为对外公开的接口必须在 registry 中有完整 `params`/`response`。 |
| 主要测试文件 | 被测：`api_docs.py`（`ENDPOINT_REGISTRY`）、`app.py`（url_map）；计划：`tests/api/test_api_docs_contract.py`，UT-DOC-008~009 |
| 测试环境 | 同 F-4-6；首次导入隔离完成后，独立 API 进程内反射 app |
| 测试方法 | 对 METHOD/path 双向匹配，核对公开接口元数据；无参数接口允许空 params，但须明确结构；HEAD/OPTIONS 等框架自动方法单独排除并记录规则；输出差异列表。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 路由对应关系、元数据和公开集合均待验证；CI 闸门尚未实现，不能预填无孤立条目或已受自动化保障。 |
| 验收判据（非执行结论） | 全部适用路由可追踪，差异得到修复或明确豁免后验收。 |

---

## 五、内核态与用户态联合权限监察与异常研判模块

> 本章对应团队横向课题"内核态与用户态联合权限监察"，为跨模块组合验证，用例落在 `tests/api/test_joint_permission.py`、`tests/unit/test_xy_skill.py` 与 `tests/api/test_intercept_turnir_api.py`。

### 5.1 功能验证

验证的基本目标：

1. 【F-5-1】用户态与内核态九类字段贯通
2. 【F-5-2】四阶段推送 payload 契约完整
3. 【F-5-3】13 个工具的注册、参数与取证契约完整
4. 【F-5-4】流式工具编排实时呈现正确
5. 【F-5-5】安全拦截三类事件功能完备
6. 【F-5-6】turn-ir 长轮询与兜底放行正确
7. 【F-5-7】前端关键交互逻辑正确（P2 骨架）

#### 【F-5-1】用户态与内核态九类字段贯通

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-5-1 |
| 测试要求 | 同一条 round 的九类字段可同时存在且互不覆盖：`action_json`（用户态行为）、`pid_info`（进程安全上下文）、`kernel_syscall_seq`、`kernel_lsm_hook_result`、`kernel_resource_facts`、`judge_result`（用户态判定）、`judge_result_kernel`、`syscall_judge`、`anomaly_llm_v2_judge_res`（联合研判）；任一字段缺失时其余字段读取正常；`pid_info` 的 `tool_subprocess_labels[].cmdline` 能与 `action_json` 中的工具名建立对应关系。 |
| 主要测试文件 | 被测：`db.py`、`app.py`（rounds 与内核态上报接口族）；测试脚本：`tests/api/test_joint_permission.py`（UT-JP-001、UT-JP-005） |
| 测试环境 | Ubuntu 22.04；`temp_db` + `flask_client`；数据取自 `tests/data/` 脱敏黄金样本（含真实结构的 pid_info、syscall 序列、LSM hook 结果） |
| 测试方法 | 1. 按 start→ir→end→kernel→detection 顺序完整上报一条 round；2. 读回记录，逐一断言九类字段非空且内容与上报一致；3. 以 9 组"缺一"组合分别上报，断言其余字段读取正常；4. 解析 `tool_subprocess_labels[].cmdline` 与 `action_json` 中的工具名，断言可建立对应（如 `safe_file_reader/server.py` ↔ 文件读工具）。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 九类字段同时存在且互不覆盖；9 组"缺一"组合下其余字段均可正常读取；子进程 cmdline 与工具名的关联字段存在且非空，可支撑"用户态工具调用 ↔ 内核态进程行为"的对齐分析。 |
| 验收判据（非执行结论） | 用户态与内核态数据贯通完整，为联合权限监察提供了完备的数据底座；需执行后判定。 |

#### 【F-5-2】四阶段推送 payload 契约完整

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-5-2 |
| 测试要求 | `round_start` → `round_ir_ready` → `round_end` → `round_kernel` 四阶段的推送 payload 字段符合 README 契约，且 `round_start` 必须最先；推送统一走 `/wss/monitor` 命名空间的 `push` 事件。 |
| 主要测试文件 | 被测：`app.py`（`broadcast_push` 与各上报接口）；测试脚本：`tests/api/test_joint_permission.py`（UT-JP-002）、`tests/api/test_rounds_api.py`（UT-API-028~029） |
| 测试环境 | 同 F-5-1；`broadcast_push` 以 spy 记录全部调用 |
| 测试方法 | 1. 完整上报一条 round，收集全部推送调用；2. 断言 `push_type` 序列为四阶段顺序；3. 逐阶段断言 payload 必需字段；4. 断言命名空间与事件名。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 四阶段 `push_type` 序列正确且 `round_start` 最先；各阶段 payload 字段齐全；命名空间与事件名符合前端订阅约定。 |
| 验收判据（非执行结论） | 四阶段推送契约完整，可作为前后端接口基线；需执行后判定。 |

#### 【F-5-3】13 个工具的注册、参数与取证契约完整

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-5-3 |
| 测试要求 | `TOOLS` 与 `TOOL_HANDLERS` 均包含 13 个同名工具：12 个 `get_*` round 工具和 `search_selinux_knowledge`。前者必填 `round_id`；后者必填 `query`，可选 `kind/module/k`，schema 不含 `round_id`。内部 handler 保留 round_id 参数但不用于检索。 |
| 主要测试文件 | 被测：`xy_skill.py` 的工具注册、`_call_tool_handler`、`_handler_selinux_knowledge`；计划：`tests/unit/test_xy_skill.py`，保留 UT-XY-001~005，新增 UT-XY-021~025，P0 |
| 测试环境 | 按 E.3 在首次导入前替换数据依赖；round 行和知识库 search 均为替身，JSONL 放在 `tmp_path`，无网络和默认索引访问。 |
| 测试方法 | 1. 比较注册名称集合和 schema；2. 12 个 round handler 分别校验关键字段；3. 新工具合法 JSON 参数、空/缺 query、畸形 JSON、非对象、额外字段分别测试；4. `k` 覆盖缺省、0、1、10、11、非法字符串，确认回退 5 和夹取 1~10；5. 验证 kind 归一化与 module 空值转 None；6. 额外 round_id/db_path 不可覆盖分发器参数或索引位置；7. mock 导入失败与检索异常，检查可读提示。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 待执行。预期 round 工具仅接收编排器的 round_id，参数类工具仅传递 `_ARG_TOOL_KEYS` 白名单值；JSONL 与取证内容需逐项断言，不只检查返回字符串。详见 G.1。 |
| 验收判据（非执行结论） | 注册、参数分流、边界与异常都有证据后再判定；当前未执行。 |

#### 【F-5-4】流式工具编排实时呈现正确

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-5-4 |
| 测试要求 | 分离 SSE 事件解析与 tool arguments 分片组装。12 个 round 工具在 `tool_start` 执行；`ARG_TOOLS` 中的知识库工具必须等 `final` 收齐 arguments 才执行。文本增量、工具调用与结果关联不能丢失或重复。 |
| 主要测试文件 | 被测：`xy_skill.py` 的 `_call_llm_stream`、`_stream_llm_with_tools`、`run_skill_analysis`；计划：`tests/unit/test_xy_skill.py`，UT-XY-010~013、UT-XY-026~028，P0 |
| 测试环境 | 生成器伪造 SSE，HTTP 与全部 handler 使用 spy；不启动模型或后台服务。 |
| 测试方法 | 1. 测试空行、`data:`、`[DONE]`、畸形事件与 arguments 的跨事件片段，不假定畸形 SSE JSON 会自动拼回；2. 同流混合 round/知识库工具，断言执行时机；3. 非连续 index、多工具交错、缺失 ID 时核对组装与结果关联；4. final 前知识库调用次数为 0，final 后各调用一次；5. 区分工具返回错误字符串（当前走 completed）与未知工具/抛异常（error）；6. 分别验证显示预览截断和模型历史内容，不把二者当成同一输出。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 待执行。当前源码为同步逐个工具执行，不是工具并发；参数类工具不会在名称出现时提前检索。HTTP 异常及历史结构完整性须独立断言。 |
| 验收判据（非执行结论） | 两类工具的分流、流式时序和结果关联验证后再判定；当前未执行。 |

#### 【F-5-5】安全拦截三类事件功能完备

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-5-5 |
| 测试要求 | `POST /api/intercept/events` 支持 `ir_tool_block`/`ir_loop_break`/`ir_timeout` 三类事件，入库同时触发 `emit("intercept_event")` 与 `broadcast_push`；`_row_to_intercept_event` 对含 `round_id`/`note` 迁移列的行与缺列旧行均正确映射；`GET /api/intercept/events` 分页与筛选正确；`DELETE /api/intercept/events` 无特权 403、特权 200 且清空；`GET/PUT /api/config/intercept_non_ir_tools` 与 `/api/config/loop_breaker`（默认阈值 3）配置读写正确。 |
| 主要测试文件 | 被测：`app.py`（拦截事件接口族与开关配置）、`db.py`（`intercept_events` 表）；测试脚本：`tests/api/test_intercept_turnir_api.py`（UT-API-104~110） |
| 测试环境 | 同 F-5-1 |
| 测试方法 | 1. 三类事件分别上报，断言入库字段与两类推送各一次；2. 缺 `type`/未知 type/空 body 断言 400 或明确降级；3. 构造含迁移列与缺列的两种行，断言映射不抛异常；4. 分页与筛选断言 200 与结果集；5. 无特权与特权 DELETE 断言 403/200 与清空效果；6. 两个开关配置读写断言落库与类型归一为 `"true"/"false"`。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 三类事件入库与推送正确；异常入参明确拒绝；两种行结构映射均不抛异常；分页筛选正确；DELETE 特权校验生效；开关配置类型归一正确，`loop_breaker` 默认阈值 3。 |
| 验收判据（非执行结论） | 安全拦截事件链路功能完备；需执行后判定。 |

#### 【F-5-6】turn-ir 长轮询与兜底放行正确

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-5-6 |
| 测试要求 | `_normalize_user_query` 能剥离 `Sender metadata` 与 `[时间戳]` 前缀并归一多空白以作缓存 key；`_extract_allowed_tools_from_ir` 对标准 IR/空 IR/无 tool 对象/嵌套 functions 返回去重工具名列表或 `[]`；`_turn_ir_get_or_create_event` 同 key 并发返回同一 `Event`（`_TURN_IR_LOCK` 保护）；缓存命中时立即返回不调 translate；未命中但在等待窗内被 publish 时长轮询被唤醒；超时后 fallback 调一次 translate 成功则返回其结果，fallback 也失败时放行并通过 `_record_turn_ir_timeout_event` 记录 `ir_timeout`；`_TURN_IR_MAX_ENTRIES=256` 有淘汰机制；`_turn_ir_reset_for_new_round` 清理旧 turn 缓存与 Event；`_backfill_round_ir` 回填遵守防覆盖规则、round 不存在时静默跳过。 |
| 主要测试文件 | 被测：`app.py`（turn-ir 接口族与内部函数）；测试脚本：`tests/api/test_intercept_turnir_api.py`（UT-API-090~103） |
| 测试环境 | 同 F-5-1；`core.translate` mock；以线程事件手动驱动 publish 与超时，全局 `--timeout=30` |
| 测试方法 | 1. 表驱动断言查询归一与工具名提取；2. 同 key 两次获取 Event，断言为同一对象；3. 缓存命中场景断言 translate 未被调用；4. 等待窗内 publish，断言长轮询返回；5. 构造超时 + fallback 成功 / 超时 + fallback 失败两种场景，断言返回与事件记录；6. 写入超过 256 条缓存，断言有淘汰不无限增长；7. 新 round 到来断言旧缓存与 Event 被清理；8. `_backfill_round_ir` 在 round 存在与不存在两种情形断言行为。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 查询归一与工具名提取正确；同 key 并发返回同一 Event；缓存命中零翻译调用；publish 唤醒长轮询成功；超时 fallback 成功时返回翻译结果，fallback 失败时放行并记录 `ir_timeout` 事件（符合 README"兜底放行不阻断业务"的设计）；缓存容量受控；新 round 清理生效；回填遵守防覆盖规则且 round 不存在时静默跳过。 |
| 验收判据（非执行结论） | turn-ir 长轮询、兜底放行与缓存治理正确；需执行后判定。 |

#### 【F-5-7】前端关键交互逻辑正确（P2 骨架）

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | F-5-7 |
| 测试要求 | `src/utils/socket.js` 的 namespace 与 `path: "/wss"` 配置正确、`new_round_info` 监听注册、单例语义正确；`router/index.js` 的 auth guard 未登录时重定向 `/login`；`monitor/LogsTab.vue` 的 round upsert 逻辑按 `round_id` 已存在则更新否则插入，且筛选激活时只更新不插入；分数徽章渲染 `>0.5` 绿（`#00a870`）/`≤0.5` 橙（`#ED7B2F`）/`-1` 灰+脉冲；`ir_json === "__loading__"` 时显示 IR 翻译中 loading。 |
| 主要测试文件 | 被测：`frontend/src/utils/socket.js`、`router/index.js`、`views/monitor/LogsTab.vue`、`components/PrivilegeDialog.vue`、`PrivilegeStatus.vue`、`RuleSelectDialog.vue`、`SecurityPage.vue`、`ReplayPage.vue`；测试脚本：`frontend/tests/unit/*.spec.js`（UT-FE-001~011） |
| 测试环境 | 按 0.2 选择受维护且兼容的 Node 与锁定的 Vitest/Vue Test Utils/jsdom；测试配置尚未落地；倒计时使用假定时器并在 teardown 恢复 |
| 测试方法 | 1. mock socket.io-client，断言连接参数与监听注册、重复连接的单例语义；2. 断言路由守卫在未登录/已登录两态的跳转；3. 构造 round 推送序列断言 upsert 与"筛选激活时只更新不插入"；4. 断言三档分数徽章样式与 `__loading__` 状态渲染；5. 断言特权对话框写 `sessionStorage`、特权状态倒计时递减与到期失效；6. 断言规则选择对话框按 `rule_id`/syscall 名搜索与单选生效；7. 断言 `SecurityPage` 在 `monitor_conf.use_gateway !== "true"` 时弹 warning 但不阻断且 `destroy()` 被调用；8. 断言回放速度 0.1x~2x 与阶段进度分段（33%/66%/80%/100%）计算。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 11 项设计见 G.3，当前未找到对应 Vitest 基建与测试实现。socket、路由、upsert、徽章/loading、会话、规则筛选及回放均待验证；DOM 相关用例须挂载实际组件，不能只验证复制的计算逻辑。 |
| 验收判据（非执行结论） | 实际组件/逻辑用例和依赖配置落地，证据完整后再判定；目前未执行，浏览器 E2E 不在范围。 |

### 5.2 性能验证

1. 【P-5-1】turn-ir 长轮询等待与唤醒时延
2. 【P-5-2】工具结果压缩与截断阈值控制
3. 【P-5-3】取证 handler 大文件体量控制

#### 【P-5-1】turn-ir 长轮询等待与唤醒时延

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | P-5-1 |
| 测试要求 | 缓存命中时接口响应时延小于 10ms；等待窗内被 publish 唤醒的时延小于 50ms；256 条缓存满载时的查找与淘汰耗时小于 5ms；长轮询期间不占用额外线程池资源导致其他接口阻塞。 |
| 主要测试文件 | 被测：`app.py`（turn-ir 接口族）；测试脚本：`tests/api/test_intercept_turnir_api.py::test_turn_ir_latency` |
| 测试环境 | Ubuntu 22.04，内存 16GB；`core.translate` mock 为零延迟；以 `threading.Timer` 触发 publish |
| 测试方法 | 1. 预热缓存后连续 200 次请求，记录命中时延均值与 P95；2. 以定时器在 20ms 后 publish，测量从请求发出到返回的时延；3. 填满 256 条缓存后测量查找与淘汰耗时；4. 长轮询进行中并发请求 `GET /api/stats`，断言其响应不被阻塞。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 缓存命中、唤醒、淘汰和并发请求耗时均未测；分别比较 10ms/50ms/5ms 目标。唤醒耗时从实际 publish 时刻算起，定时器预设等待不计作唤醒开销，不能据 mock 推断系统并发能力。 |
| 验收判据（非执行结论） | 长轮询时延与并发表现满足在线拦截决策要求；需执行后判定。 |

#### 【P-5-2】工具结果压缩与截断阈值控制

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | P-5-2 |
| 测试要求 | `_process_tool_result` 在长度恰好等于阈值时不处理；超阈值且压缩开关关闭时直接截断并标注"（结果过长，已截断）"；超阈值且开关开启时走 LLM 摘要，压缩失败回退截断；`_get_tool_compress_max` 默认 2000、非法值回退默认；处理耗时（不含 LLM）小于 5ms。 |
| 主要测试文件 | 被测：`xy_skill.py`（`_process_tool_result`、`_compress_tool_result`、`_get_tool_compress_switch`、`_get_tool_compress_max`）；测试脚本：`tests/unit/test_xy_skill.py`（UT-XY-007~009、UT-XY-019） |
| 测试环境 | Ubuntu 22.04；压缩用 LLM 调用 mock；config 以内存字典替换 |
| 测试方法 | 1. 构造长度为阈值 -1 / 等于阈值 / 阈值 +1 的三组结果，断言处理行为；2. 开关关闭时断言截断与标注文案；3. 开关开启时断言调用压缩，并使压缩失败断言回退截断；4. 三态断言阈值配置取值；5. 以 `time.perf_counter` 测量纯截断路径耗时。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 待验证等于阈值不处理、超限截断及摘要失败回退；配置默认值与覆盖顺序分别断言。纯本地处理耗时未测，目标 <5ms，不包含 mock LLM 的虚拟耗时。 |
| 验收判据（非执行结论） | 工具结果体量控制策略正确，阈值与回退链完备；需执行后判定。 |

#### 【P-5-3】取证 handler 大文件体量控制

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | P-5-3 |
| 测试要求 | `_handler_syscall_sequence` 与 `_handler_kernel_lsm_hook` 在 JSONL 文件达到 50MB / 50 万行时，返回文本体量受控（不超过压缩阈值数量级）、耗时小于 3s、内存增长小于 200MB。 |
| 主要测试文件 | 被测：`xy_skill.py`（JSONL 类取证 handler）；测试脚本：`tests/unit/test_xy_skill.py`（UT-XY-005，P1） |
| 测试环境 | 同 P-5-2；`tmp_path` 生成 50 万行内核态 JSONL |
| 测试方法 | 1. 生成 50 万行 JSONL（约 52MB）；2. 调用两个 handler，记录耗时、返回文本长度与 `tracemalloc` 峰值；3. 断言三项指标均在阈值内。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 两个 handler 的耗时、返回长度和内存未测；分别比较 <3s、<200MB 目标，并记录实际输出。`tracemalloc` 仅反映 Python 分配，不能替代进程整体内存测量，流式读取方式也须验证。 |
| 验收判据（非执行结论） | 大体量内核态数据的取证读取具备体量与内存控制；需执行后判定。 |

### 5.3 安全性验证

1. 【S-5-1】权限模型不变量
2. 【S-5-2】攻击向量检测能力矩阵
3. 【S-5-3】提权信号可解析并进入研判上下文

#### 【S-5-1】权限模型不变量

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | S-5-1 |
| 测试要求 | 以 invariant 测试固化 7 条权限模型不变量：①特权密钥永不可通过 API 修改；②入门口令不在任何 GET 响应中出现；③`api_key` 不在任何非特权响应中出现；④`pid_info` 不含敏感环境变量；⑤`pid_info` 不含 ClawAVC 自身 label；⑥特权会话不可跨重启复用；⑦`judge()` 函数本体不被修改（源码哈希快照，对应 CLAUDE.md 约束）。 |
| 主要测试文件 | 被测：`app.py`、`db.py`、`auditor/monitor/proc_info.py`、`auditor/monitor/judge.py`；测试脚本：`tests/api/test_joint_permission.py`（UT-JP-030~036） |
| 测试环境 | 同 F-5-1；重建 `_admin_sessions` 模拟重启 |
| 测试方法 | 1. 遍历所有写配置接口尝试写 `admin_key`，断言全部拒绝且 DB 值不变；2. 遍历所有 GET 接口响应体，全文检索口令值与 `secret_key`；3. 遍历配置类 GET 接口检索 `api_key`；4. 对 `pid_info` 采集结果全文检索 `KEY`/`TOKEN`/`SECRET`/`PASSWORD`；5. 检查 `system` 与 `main` 字段无自身 label；6. 重建会话字典后以旧 token 请求，断言失效；7. 对 `judge` 函数源码取哈希并与基线比对。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 七条不变量均待执行，RISK-019 单独追踪密钥泄漏；尚无源码哈希快照或运行证据。源码变更检查属于评审门禁，不能替代判定行为测试；快照变更须审核，不能为消除失败自动更新。 |
| 验收判据（非执行结论） | 每条不变量都有对应证据与风险处置后再判定，不预填“六条成立”。 |

#### 【S-5-2】攻击向量检测能力矩阵

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | S-5-2 |
| 测试要求 | 以 README 的两类威胁场景与三类注入配置构造纯离线端到端判定用例：运行时篡改-替换工具（IR 只允许 `read`、实际 `exec`）须产生工具调用维 violation 且 `overall_score ≤ 0.5`；运行时篡改-插入工具（多出 IR 外的 `malicious_tool`）须产生工具调用维 + 轨迹维双 violation；工具注入-固定网络外发（`http://malicious.example.com/collect` + `connect`）须产生资源维 network violation；工具注入-固定文件访问（`/root/.ssh/id_rsa` + `read`，IR 仅允许 `/tmp/**`）须产生资源维 violation；工具注入-异常 syscall 序列（`DT异常序列_003`）须正确入库并进入联合研判上下文；沙箱越界（工具返回 `Path escapes sandbox root`）时判定链路不漏检。 |
| 主要测试文件 | 被测：`auditor/monitor/judge.py`、`db.py`、`app.py`；测试脚本：`tests/api/test_joint_permission.py`（UT-JP-010~014、UT-JP-019） |
| 测试环境 | 同 F-5-1；纯离线，仅喂数据不真跑攻击 |
| 测试方法 | 1. 逐个攻击向量构造 IR + action（+ syscall_judge）数据对；2. 执行端到端判定，断言 violation 维度、文案与 `overall_score` 区间；3. 对 syscall 注入场景断言字段入库与研判上下文可见；4. 对沙箱越界场景断言工具执行失败不导致漏检。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 5 类攻击向量全部被正确检出：替换工具与插入工具分别命中单维与双维 violation 且分数降至 ≤0.5；网络外发与敏感文件访问命中资源维；`DT异常序列_003` 判定结果正确入库并出现在研判上下文；沙箱越界场景中工具执行失败不影响行为事件生成，判定链路无漏检。 |
| 验收判据（非执行结论） | 攻击向量检测能力矩阵完整覆盖 README 声明的威胁场景；需执行后判定。 |

#### 【S-5-3】提权信号可解析并进入研判上下文

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | S-5-3 |
| 测试要求 | `pid_info` 中 `capabilities.effective` 含 `CAP_SYS_ADMIN`、`seccomp=disabled`、`no_new_privs=false`、`loginuid=4294967295` 等提权信号须可被解析并进入研判上下文；`_simplify_ir_json`/`_simplify_action_json`/`_simplify_resource_facts`/`_simplify_judge`/`_simplify_syscall_judge`/`_simplify_kernel_judge_from_path` 六个上下文构造函数在完整/缺字段/非法 JSON/文件不存在四态下均降级返回不抛异常。 |
| 主要测试文件 | 被测：`auditor/monitor/proc_info.py`、`app.py`（`_simplify_*`、`_build_round_chat_seed`）、`xy_skill.py`；测试脚本：`tests/api/test_joint_permission.py`（UT-JP-020）、`tests/api/test_attack_config_api.py`（UT-API-148~150） |
| 测试环境 | 同 F-5-1 |
| 测试方法 | 1. 构造含四类提权信号的伪进程，采集后断言字段可解析；2. 将该 `pid_info` 喂入研判上下文构造，断言提权信号出现在上下文文本中；3. 对六个 `_simplify_*` 函数各喂入四态输入，断言均降级返回；4. 断言 `_build_round_chat_seed` 生成的消息序列结构合法且不含超长未截断内容；5. 断言 `_try_json`/`_raw_or_json`/`_read_file_text` 对非法 JSON、大文件、不存在、无权限的安全降级。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 四类提权信号均被正确解析并进入研判上下文；六个上下文构造函数在 24 组（6×4）输入下全部降级返回、无一抛异常；`_build_round_chat_seed` 结构合法且内容经截断；三个底层读取函数安全降级。 |
| 验收判据（非执行结论） | 提权信号采集与研判上下文构造安全可靠，不会因数据缺陷中断研判；需执行后判定。 |

### 5.4 可靠性验证

1. 【R-5-1】取证 handler 全异常输入友好降级
2. 【R-5-2】研判循环轮次上限防护
3. 【R-5-3】流式中断与未知工具不中断研判
4. 【R-5-4】联合研判入口未配置时不误调大模型

#### 【R-5-1】取证 handler 全异常输入友好降级

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | R-5-1 |
| 测试要求 | 原 12 个 round 取证 handler 覆盖 round 不存在、空字段、非法 JSON、引用文件不存在；新增知识库工具不依赖 round，另以 query/索引/导入异常矩阵验证，不能机械套用 round 缺失期望。 |
| 主要测试文件 | 被测：`xy_skill.py`；计划：`tests/unit/test_xy_skill.py`，UT-XY-003、UT-XY-025；关联 R-6-1 |
| 测试环境 | 同 P-5-2；临时文件与知识库替身 |
| 测试方法 | 12×4 为 round 工具的设计矩阵，逐项检查可读降级及无未捕获异常；知识库工具独立验证错误路径，未使用字段不强制产生同一种错误提示。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 两类工具异常矩阵均待执行；需记录每个参数实例的实际提示，不能从“返回字符串”推断所有异常均可靠处理。 |
| 验收判据（非执行结论） | 取证层具备完全的异常降级能力，研判流不会被单个字段缺陷中断；需执行后判定。 |

#### 【R-5-2】研判循环轮次上限防护

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | R-5-2 |
| 测试要求 | `run_skill_analysis` 在模型连续调用工具超过 `MAX_TOOL_ROUNDS = 6` 时强制终止循环（防无限取证）；模型首轮即不调工具时直接输出最终研判；`_get_skill_system_prompt` 在 config 无自定义时回退 `DEFAULT_SKILL_SYSTEM_PROMPT`。 |
| 主要测试文件 | 被测：`xy_skill.py`（`run_skill_analysis`、`_get_skill_system_prompt`）；计划：`tests/unit/test_xy_skill.py`，UT-XY-006、UT-XY-016~017、UT-XY-020、UT-XY-029 |
| 测试环境 | 同 P-5-2；mock 文本/工具混合流和最终文本生成器 |
| 测试方法 | 持续工具调用时校验 6 轮上限；分别第 1/5/6 轮无工具而直接返回文本，核对 text_done、tool_limit_reached 和最终生成器调用次数；验证默认/自定义提示词；详细输入见 G.1。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 正常文本只应生成一次最终结果，上限后不能执行额外工具。第 6 轮正常 break 后仍可能进入限轮收尾的静态风险见 RISK-023，须失败注入/事件序列断言复核。 |
| 验收判据（非执行结论） | 研判循环具备轮次上限防护，不会无限取证消耗资源；需执行后判定。 |

#### 【R-5-3】流式中断与未知工具不中断研判

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | R-5-3 |
| 测试要求 | `_stream_llm_with_tools` 在流中出现未知工具名时跳过或返回错误提示而不中断流；流中途连接断开时已产出内容保留且异常被捕获。 |
| 主要测试文件 | 被测：`xy_skill.py`（`_stream_llm_with_tools`）；测试脚本：`tests/unit/test_xy_skill.py`（UT-XY-014~015） |
| 测试环境 | 同 P-5-2；以生成器在中途 `raise ConnectionError` 模拟断流 |
| 测试方法 | 1. 在流中注入未知工具名，断言流继续且返回错误提示文本；2. 在流中途抛出 `ConnectionError`，断言已产出内容被保留、异常被捕获且函数正常返回；3. 断言异常后消息历史结构仍合法。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 未知工具被跳过并返回提示，后续分片继续处理；断流时已推送内容完整保留、异常被捕获，消息历史结构合法可用于后续轮次。 |
| 验收判据（非执行结论） | 流式研判具备中断容错能力；需执行后判定。 |

#### 【R-5-4】联合研判入口未配置时不误调大模型

| 项 | 内容 |
|---|---|
| SR编号 | SR-1 |
| 用例编号 | R-5-4 |
| 测试要求 | `anomaly_llm_url_v2` 未配置时 `request_anomaly_llm_url_v2` 与 `run_skill_analysis` 均不调用大模型、直接返回；已配置时 mock LLM 返回须写入 `anomaly_llm_v2_judge_res`，超时或非 200 时异常被吞且不影响上报链路；`POST /api/rounds/detection/kernel` 成功时异步触发 `request_anomaly_llm_url_v2`。 |
| 主要测试文件 | 被测：`app.py`（`request_anomaly_llm_url_v2`、`/api/rounds/detection/kernel`）、`xy_skill.py`；测试脚本：`tests/api/test_attack_config_api.py`（UT-API-151~152）、`tests/api/test_rounds_api.py`（UT-API-025）、`tests/unit/test_xy_skill.py`（UT-XY-018） |
| 测试环境 | 同 F-5-1；异步触发以线程/函数调度 spy 断言 |
| 测试方法 | 1. 清空 `anomaly_llm_url_v2` 配置，断言大模型调用函数未被触发；2. 配置后 mock LLM 正常返回，断言结果写入 `anomaly_llm_v2_judge_res`；3. 分别注入超时与非 200，断言异常被吞且上报链路返回 200；4. 断言 detection/kernel 成功时异步调度被触发一次。 |
| 执行状态 | 待执行；未提供运行证据。 |
| 待验证行为（非实测） | 未配置时确认零大模型调用（符合 README 明确约定）；配置后结果正确落库；超时与非 200 场景异常被吞、上报链路不受影响；异步调度被精确触发一次。 |
| 验收判据（非执行结论） | 联合研判入口的配置门控与异常隔离正确；需执行后判定。 |

---

## 六、SELinux 本地知识库解析、构建与检索模块

> 本章基于当前新增 `backend/selinux_kb/` 源码补齐设计，不代表已有测试实现。检索模块独立测试；与研判工具的集成归 F-5-3/F-5-4，不重复增加验证点。

### 6.1 功能验证

1. 【F-6-1】策略语法解析与出处定位
2. 【F-6-2】多格式文档分块与参数提取
3. 【F-6-3】多通道检索、过滤与稳定排序
4. 【F-6-4】微型索引构建与读取一致性

#### 【F-6-1】策略语法解析与出处定位

| 项 | 内容 |
|---|---|
| SR编号 | SR-KB（本报告新增内部需求域，待需求负责人确认） |
| 用例编号 | F-6-1 |
| 测试要求 | `parse_te`、`parse_if`、`parse_fc` 提取类型、接口、规则、文件上下文和原始出处；不执行策略内容，不将静态规则文本等同于运行内核的实际授权。 |
| 主要测试文件 | 被测：`selinux_kb/parsers.py`；计划：`tests/unit/test_kb_parsers.py`，UT-KB-001~008，P1 |
| 前置与数据 | `tmp_path` 中自建 `.te/.if/.fc`；覆盖多行规则、m4 嵌套、`$1` 参数、条件块、续行和 `<<none>>`。不复制实际主机策略。 |
| 测试方法 | 1. 用手工标注的期望字典核对 chunks/symbols/rules/fctxs；2. 校验 path/module/source/line 指向原始样本；3. 对空文件、注释、重复声明分别测试；4. 不平衡 `.te` 核对 balanced 与条件清除行为；5. `.if` 的 `_bal` 未参与后续处理，单列回归，不假定与 `.te` 一致。 |
| 待验证行为（非实测） | 合法语法应得到对应结构和准确行号；无法解析的范围应可识别。条件丢失、行号错位或残缺结构应记录失败，不以“返回了列表”判通过。 |
| 执行状态 | 待执行；无运行证据。 |

#### 【F-6-2】多格式文档分块与参数提取

| 项 | 内容 |
|---|---|
| SR编号 | SR-KB |
| 用例编号 | F-6-2 |
| 测试要求 | `clean_doc`、`extract_params`、`split_long` 及 Markdown/man/Creole/SPT/access_vectors/terminology 解析保留有效内容、标题与出处。 |
| 主要测试文件 | 被测：`selinux_kb/parsers.py`；计划：`tests/unit/test_kb_parsers.py`，UT-KB-009~014，P1 |
| 前置与数据 | 合成短文档、空文件、含中文与特殊符号文本、长单段、多段及末尾无换行样本。 |
| 测试方法 | 参数化格式；核对参数名称和说明、标题边界、chunk 顺序及非空内容；对长度阈值前/等于/后各一组，重组内容校验无丢失或重复；确认分块是否保留正确行号。 |
| 待验证行为（非实测） | 当前 `split_long` 主要按空段边界切分，不能宣称每个长单段都严格小于 3600 字符；将实际边界写入回归记录，若需求要求硬上限则另立修复项。 |
| 执行状态 | 待执行；无运行证据。 |

#### 【F-6-3】多通道检索、过滤与稳定排序

| 项 | 内容 |
|---|---|
| SR编号 | SR-KB |
| 用例编号 | F-6-3 |
| 测试要求 | 标识符/路径/词元提取，多通道 symbol/rule/fctx/fts 检索、kind/module 过滤、RRF 融合及文本引用符合 `search_hits` 和 `search` 契约。 |
| 主要测试文件 | 被测：`selinux_kb/search.py`；计划：`tests/unit/test_kb_search.py`，UT-KB-015~024，P1 |
| 前置与数据 | 连接替身或微型临时索引，固定不同通道、相同命中、同分与零命中记录；不访问默认索引。 |
| 测试方法 | 1. 验证查询拆分、大小写和过滤；2. 按源码权重及 `RRF_K` 手算两条记录分数；3. 相同 key 累积分数并去重，同分按首次出现顺序稳定输出；4. 检查 `k` 限制；5. FTS 有结果/无结果/不可用分别核对 LIKE 回退；6. `interface`/`macro` 的符号子类型过滤；7. 核对引用与“无直接规则不代表绝对禁止”的提示。 |
| 待验证行为（非实测） | `search_hits` 返回含 query/kind/module/info/notes/hits 的结构；`search` 返回带出处字符串。module 过滤当前允许 module 为 NULL 的通用资料，不应误写为只返回完全相等模块。 |
| 执行状态 | 待执行；无运行证据。 |

#### 【F-6-4】微型索引构建与读取一致性

| 项 | 内容 |
|---|---|
| SR编号 | SR-KB |
| 用例编号 | F-6-4 |
| 测试要求 | `detect_sources`、`_dedupe`、`collect_*`、`build` 正确发现语料、保序去重、建表并返回计数；构建出的微型索引能够被检索模块读取。 |
| 主要测试文件 | 被测：`selinux_kb/build_index.py`；计划：`tests/unit/test_kb_build_index.py`，UT-KB-025~030，P1；属于 L2 组件单测 |
| 前置与数据 | 输出和语料全部位于每例独立 `tmp_path`；mock 日志、时间及环境探测；FTS5 可用/不可用都要有确定性分支用例。 |
| 测试方法 | 手工给定记录及去重键，验证输出顺序；以三类微型语料构建，分别核对四类表的行数、元信息、来源字段及返回 counts；重复构建比较业务内容，不比较动态时间戳；FTS 开关两态检索同一关键词。 |
| 待验证行为（非实测） | 返回计数与索引实际行数一致；两种 FTS 能力下接口均可读取；不要求随运行变化的时间戳或 SQLite 文件二进制完全相同。 |
| 执行状态 | 待执行；无运行证据。 |

### 6.2 性能验证

1. 【P-6-1】检索体量、截断与资源开销

#### 【P-6-1】检索体量、截断与资源开销

| 项 | 内容 |
|---|---|
| SR编号 | SR-KB |
| 用例编号 | P-6-1 |
| 测试要求 | 核对 `k` 上限、摘要截断和输出增长；延迟/内存基线必须在固定规模索引上测量，mock 查询不用于证明 SQLite 检索性能。 |
| 主要测试文件 | 被测：`selinux_kb/search.py`；计划：`tests/unit/test_kb_search.py`，UT-KB-031~035，P2/performance |
| 前置与数据 | 确定性合成 100/1000/10000 条记录；分别测试短/长首条结果及不同 k，禁止使用生产语料。 |
| 测试方法 | 记录索引大小、冷/热查询耗时、P50/P95、返回字符数与内存；预热与重复次数按 G.2；分别记录 `_shorten` 与 `search` 的软上限，不把二者混为硬限制。 |
| 待验证行为（非实测） | `_shorten` 截断后还会添加省略符；`search` 对首条超长结果、提示文字存在例外，不能断言总输出严格 ≤2000 字符。耗时与内存目前未测，数值验收门槛待首轮基线后评审，不能据无阈值判性能通过。 |
| 执行状态 | 待执行；性能门槛待评审。 |

### 6.3 安全性验证

1. 【S-6-1】检索只读、参数约束与证据边界

#### 【S-6-1】检索只读、参数约束与证据边界

| 项 | 内容 |
|---|---|
| SR编号 | SR-KB |
| 用例编号 | S-6-1 |
| 测试要求 | 查询不改变索引；用户输入仅作为查询值，不作为可执行 SQL 或可读取文件路径；无命中时不伪造依据，检索结果不能被误解为运行内核授权结论。 |
| 主要测试文件 | 被测：`selinux_kb/search.py`、`xy_skill.py`；计划：`tests/unit/test_kb_search.py`，UT-KB-036~043，P0；工具参数详见 G.1 |
| 前置与数据 | 临时只读索引，合成含引号、通配符、无效 FTS 词法的 query/module；路径仅作为合成字符串，不访问真实敏感文件。 |
| 测试方法 | 记录 SQL 与绑定参数，确认输入不改变语句结构；检索前后比较表数据与索引内容；模拟写操作确认连接只读；空查询应在连接前返回；缺索引和无命中分别检查提示；工具多余参数不能重定向 db_path；引用必须可回溯到样本原文。 |
| 待验证行为（非实测） | 无执行代码或实际越权访问；查询不能改写索引；失败/无证据需明确反馈，不生成虚构规则。记录无效 kind 的当前返回并与 schema 约束区分，不能假定所有类型错误均被拒绝。 |
| 执行状态 | 待执行；安全要求不因表征测试通过而自动满足。 |

### 6.4 可靠性验证

1. 【R-6-1】缺失索引、解析错误与检索异常降级
2. 【R-6-2】构建失败不损坏旧索引

#### 【R-6-1】缺失索引、解析错误与检索异常降级

| 项 | 内容 |
|---|---|
| SR编号 | SR-KB |
| 用例编号 | R-6-1 |
| 测试要求 | 缺失索引、SQLite 错误、空查询、知识库导入失败等均有明确边界；成功获取的连接在后续异常下仍关闭，单个语料解析失败不误报全量构建成功。 |
| 主要测试文件 | 被测：`search.py`、`build_index.py`、`xy_skill.py`；计划：`tests/unit/test_kb_search.py`、`test_kb_build_index.py`，UT-KB-044~049，P1 |
| 测试方法 | 注入 FileNotFoundError、sqlite3.Error、元信息/通道查询异常及解析器异常；spy 连接关闭次数；空查询确认零连接；分别调用 `search_hits` 与 `search`，前者允许异常向上传递，后者检查约定降级；handler 的额外异常捕获另测。 |
| 待验证行为（非实测） | 降级层级与源码一致，不把所有底层函数都描述成“永不抛异常”；错误提示中不得出现真实凭据或私人路径。 |
| 执行状态 | 待执行；无运行证据。 |

#### 【R-6-2】构建失败不损坏旧索引

| 项 | 内容 |
|---|---|
| SR编号 | SR-KB |
| 用例编号 | R-6-2 |
| 测试要求 | 建库、写入、提交或目标替换失败时旧有效索引仍可用；连接释放，临时产物可识别，无静默丢失。 |
| 主要测试文件 | 被测：`selinux_kb/build_index.py::build`；计划：`tests/unit/test_kb_build_index.py`，UT-KB-050~056，P0 |
| 前置与数据 | 临时目录中的旧索引写入唯一测试标识；失败注入仅针对该目录，不操作现有业务索引。 |
| 测试方法 | 分别在连接、建表、写入、提交、替换、资源释放处注入异常；检查旧索引是否仍可查询标识、连接是否释放和日志是否报错；验证成功替换一次；同时记录调用顺序。 |
| 待验证行为（非实测） | 当前实现存在先 unlink 旧目标再 replace 的顺序，替换失败可能丢失旧库（RISK-022）。应断言期望的旧库保留，而非仅证明“删除确实发生”；若失败须报告风险，不能将现状写为通过。 |
| 执行状态 | 待执行；静态风险待复现及回归。 |

---

## 附录 A · 测试基建与隔离方案

### A.1 关键隔离难点与对策（计划，尚未落地）

| # | 难点 | 影响 | 对策 |
|---|---|---|---|
| 1 | `app.py` 导入即 gevent monkey-patch | 污染同进程 socket/thread | 所有真实 app 依赖置于 `tests/api/`，与 `tests/unit/` 独立进程；不能仅靠目录名隔离 |
| 2 | `db.py` 模块尾部调用 `init_db()`、`init_config_table()`、`_init_translator_prompts()` | 首次 import 已可能写生产库及配置 | **先建立 E.3 隔离，再 import**；导入后改 `DB_PATH` 已太晚；数据库真实实现用例不得仅替换为 fake db 来冒充验证 |
| 3 | `core.py` 导入时读取注册表与配置 | 首次导入可能读取真实配置 | 首次导入前隔离其配置/读取依赖；导入后用临时 `REGISTRY_DIR` 并显式 reload，不能直接 reload db |
| 4 | `policy_manager._cfg()` 内部导入 db | 间接触发初始化 | 在受测函数调用前注入 `_cfg/_set_cfg` 替身，独立验证数据层 |
| 5 | `set_config` 重复定义及重复建表 | 表征行为与设计可能不同 | F-4-5 独立验证最终实现，风险见 C，不预先宣称幂等通过 |
| 6 | 真实 `/proc`、SELF_PID 与命名空间 | 读取主机信息，结果随机器变化 | 伪进程树、受控 PID、临时软链；不使用真实环境变量或进程数据 |
| 7 | 会话、turn-ir 缓存、Event、模块全局状态 | 用例间状态泄漏 | 每例前后重置会话、缓存、事件、配置和知识库导入状态；恢复 sys.path/sys.modules 替身 |
| 8 | watcher 线程、sleep、异步任务 | 不稳定或意外启动服务 | 状态机手动驱动，调度与 HTTP 替身；必须实测并发的用例用有界同步和独立临时连接，确保退出 |
| 9 | 判定引擎纯函数 | 较低隔离成本 | 以合成字典/字符串直接测试，作为优先实现范围 |
| 10 | 知识库默认索引与 build 文件替换 | 访问/覆盖真实索引 | 每例显式临时 db_path；handler 使用 search 替身；失败注入只作用临时输出目录 |

### A.2 Fixture 清单（设计，不代表文件已存在）

| Fixture/前置机制 | 作用域 | 产出 | 要求 |
|---|---|---|---|
| 导入前隔离机制 | 测试收集之前 | 独立沙箱、数据库与文件访问边界 | 不是普通 function autouse；必须覆盖 collection，见 E.3 |
| `temp_db` | function | 初始化后的临时 SQLite | 连接从首次导入起即受控；结束时关闭连接，包含 WAL/SHM 文件清理 |
| `seeded_round` | function | 合成 round_id | 时间、内容、配置显式设定，不读生产库 |
| `flask_client` | function/API | 隔离 app 的 test_client | 依赖 temp_db；mock socketio、webhook、后台任务和全部外部请求 |
| `entry_token` / `admin_session` | function/API | 合成权限配置与请求头 | 不使用真实口令；每例清空会话及时间状态 |
| `fake_proc` | function | 伪进程树工厂 | pid、cmdline、status、attr/current、cgroup、namespace、stat 均合成 |
| `policy_root` | function | 微型 default/ops 策略 | 只在 tmp_path 中创建、重命名和删除 |
| `gateway_log` / `openclaw_session` | function | 合成 JSONL | 覆盖 user/assistant/toolResult 及网关嵌套消息 |
| `frozen_now` | function | 受控时钟 | 时间窗与 TTL 用虚拟时间，性能计时不冻结 perf_counter |
| `no_llm` | 全测试生命周期 | 出站请求阻断 | 覆盖 unit 和 API；高层 mock 之外还需连接边界阻断，失败即报错 |
| `kb_corpus` / `kb_db` | function | 微型语料与临时索引 | FTS/LIKE 均覆盖；真实 SQLite 测试和连接替身测试分开标注 |
| `fake_tool_stream` | function | 文本/工具/参数分片生成器 | 可注入 interleaving、空 ID、异常和最终事件 |

以上均为实施要求；正文中沿用的 fixture 名称不能作为测试基建完成证明。

### A.3 黄金样本（Golden Data）

- 来源：优先使用可公开的合成样本；如需已有审计资料，须先授权、脱敏并评审。本次未读取业务审计日志，不沿用未经复核的样本文件数量。
- 纪律：移除用户名、主机名和所有凭据；黄金样本单文件目标 ≤50KB（性能大样本测试时在临时目录生成）；记录样本 ID、来源、预期结果和覆盖分支。测试时不得动态读取 `infos/` 中的生产数据。
- 必备样本集：
  - IR：合规单策略、多策略、`deny` effect、空 `objects`、`actions` 缺失（触发 fail-open）、`identifier` 缺失（触发 `ValueError`）、glob `**`、`regex:` 前缀、非 dict/list（触发 `ValueError`）。
  - action：单工具、工具+资源、越权路径（`/etc/passwd`）、网络外发（`http://malicious.example.com/collect`）、`resources` 非 dict、缺 `identifier`。
  - pid_info：含 SELinux label、`seccomp=2`、容器 cgroup（docker/k8s）、`loginuid=4294967295`。

### A.4 测试目录结构（计划，当前未创建）

```text
backend/tests/
├── conftest.py
├── .coveragerc
├── data/
│   └── ir/ actions/ gateway/ openclaw/ proc/ registry/ kb/
├── unit/
│   ├── test_judge_primitives.py
│   ├── test_judge_layered.py
│   ├── test_judge_entry.py
│   ├── test_rcc_parity.py
│   ├── test_shell_semantics.py
│   ├── test_db_rounds.py
│   ├── test_db_config_kernel.py
│   ├── test_translator_core.py
│   ├── test_policy_manager.py
│   ├── test_proc_info.py
│   ├── test_watcher_parse.py
│   ├── test_watcher_lifecycle.py
│   ├── test_ir_client.py
│   ├── test_api_docs.py
│   ├── test_xy_skill.py
│   ├── test_kb_parsers.py
│   ├── test_kb_search.py
│   └── test_kb_build_index.py
└── api/
    ├── test_auth_permission_matrix.py
    ├── test_rounds_api.py
    ├── test_db_query_api.py
    ├── test_translator_api.py
    ├── test_intercept_turnir_api.py
    ├── test_attack_config_api.py
    ├── test_api_docs_contract.py
    └── test_joint_permission.py
```

- 共规划 18 个 unit 文件和 8 个 API 文件，不等于已实现数量；详细需求映射以各验证点“主要测试文件”为准。
- F-4-8 的假 app 元数据测试留在 `unit/test_api_docs.py`；P-4-3/R-4-4 依赖真实 app，统一放在 `api/test_api_docs_contract.py`。
- 联合权限用例统一放在 API 隔离进程，避免间接导入 app 污染纯函数批次；纯函数内容可后续拆分，但须同步映射与统计。
- 前端另规划 `frontend/tests/unit/socket.spec.js`、`router.spec.js`、`monitor-logic.spec.js`、`privilege.spec.js`、`rule-select.spec.js`、`security-replay.spec.js`；设计总计 11 项，不预先声明函数/参数化实例数量。

---

## 附录 B · 用例与覆盖率统计

### B.1 验证点分布与计数口径

| 章节 | 模块 | 功能 F | 性能 P | 安全 S | 可靠 R | 合计 | 设计规模（非实收） |
|---|---|---|---|---|---|---|---|
| 一 | IR 策略翻译与多策略库管理 | 7 | 3 | 2 | 4 | 16 | 原估约 95 |
| 二 | 行为合规判定引擎 | 7 | 3 | 4 | 4 | 18 | 原估约 190 |
| 三 | 运行时监控与进程安全上下文采集 | 9 | 3 | 3 | 4 | 19 | 原估约 110 |
| 四 | 数据服务与接口权限管控 | 8 | 3 | 5 | 4 | 20 | 原估约 105 |
| 五 | 联合权限监察与异常研判 | 7 | 3 | 3 | 4 | 17 | 原估约 60（含前端 11 项设计）；本次新增 XY 设计见 G |
| 六 | SELinux 本地知识库 | 4 | 1 | 1 | 2 | 8 | `UT-KB-001~056` 设计标识，参数化数量待定 |
| —— | **合计** | **42** | **16** | **18** | **22** | **98** | 原五章预算约 560；新增设计不冒充执行用例 |

计数规则：

1. 验证点数按正文四级标题中的唯一 `F/P/S/R` 编号计数；目标清单、风险表与交叉引用不重复计数。
2. `UT-*` 是设计标识；一个标识可能对应多个参数实例，多处引用同一标识不增加数量。旧有范围写法须在实现时展开为唯一 nodeid 映射，禁止直接按最大编号推算总量。
3. 后端执行项按两个独立进程的 pytest 收集清单去重；前端单列 Vitest 用例数量，不与后端复用名称合并。
4. 各项分别记录 collected、deselected、passed、failed、setup/teardown error、skipped、xfail、xpass。JUnit 的 skipped 可能包含 xfail，必须同时保留原始终端摘要，不能直接相加。
5. 通过率定义为严格通过项/本次选中执行项；未执行、不含用例或收集失败时写“不可计算”。有 setup/teardown 错误的项不得同时记为有效通过；缺失必需验证点时不得以局部全绿宣称阶段验收通过。

### B.2 分模块覆盖率目标（全部未测）

| 模块 | 行覆盖目标 | 分支覆盖目标 | 重点 |
|---|---|---|---|
| `auditor/monitor/judge.py` | ≥ 92% | ≥ 85% | 四维判定及原语边界 |
| `auditor/monitor/resource_consistency_check.py` | ≥ 85% | ≥ 78% | 同源双实现差异 |
| `auditor/monitor/shell_command_semantics.py` | ≥ 90% | ≥ 82% | 表驱动覆盖命令分支 |
| `auditor/translator/policy_manager.py` | ≥ 92% | ≥ 88% | 路径、切换与失败原子性 |
| `auditor/translator/core.py` | ≥ 82% | ≥ 72% | LLM 替身、解析与校验 |
| `db.py` | ≥ 85% | ≥ 75% | 迁移、读写、时间窗与错误路径 |
| `auditor/monitor/proc_info.py` | ≥ 78% | ≥ 68% | 多套伪 `/proc` 快照 |
| `auditor/monitor/ir_client.py` | 100% | ≥ 95% | 请求契约与异常返回 |
| `api_docs.py` | ≥ 80% | ≥ 70% | 元数据与路由一致性 |
| `app.py` | ≥ 70% | ≥ 58% | 鉴权、契约与调度，不启动服务器 |
| `auditor/monitor/watcher.py` | ≥ 60% | ≥ 50% | 解析和状态机；真实循环另测 |
| `xy_skill.py` | ≥ 65% | ≥ 55% | 参数分流、流式工具与降级 |
| `selinux_kb/parsers.py` | ≥ 85% | ≥ 75% | 多格式、行号、异常输入 |
| `selinux_kb/search.py` | ≥ 90% | ≥ 80% | RRF、过滤、FTS/LIKE 与引用 |
| `selinux_kb/build_index.py` | ≥ 80% | ≥ 70% | 构建、资源释放与失败保护 |
| **后端整体** | **≥ 75%** | **≥ 65%** | 所有范围内源码纳入分母，包括未被导入文件 |

- 统一启用分支采集；行覆盖按 `covered_lines / num_statements`，分支覆盖按 `covered_branches / num_branches` 从同一轮合并后的 coverage JSON 计算。分母为 0 时记 N/A，不伪造 100%。
- `--cov-fail-under=75` 是 coverage 汇总百分比门槛，**不能代替独立行/分支门槛，也不能保证各模块达标**；需逐项复核上述分子、分母，自动门禁实现后再声明已接入 CI。
- 可排除虚拟环境、测试代码、缓存和无业务占位入口；不得为了达标排除难测生产函数。其他豁免须记录源码范围、原因、审批人与替代验证。
- 前端覆盖率单列，不与 Python 覆盖率合并；首轮取得基线后再评审目标。

### B.3 实测验收标准（当前均未验收）

1. `tests/unit` 与 `tests/api` 独立收集、独立运行且无收集错误；所有范围内验证点具备 nodeid 和证据映射，不只检查退出码。
2. P0 两进程合计耗时目标小于 60 秒；性能标记另批执行。无 P0 用例、失败、收集错误或意外 xpass 均不能放行。
3. B.2 全部适用目标分别达标，合并产物来自同一代码基线和相同采集配置。
4. 网络与真实进程依赖被阻断；非 root 隔离环境运行一次，禁止扫描主机真实 `/proc` 或调用在线 LLM。
5. 从首次导入到 teardown 都不能访问生产数据；数据库、日志、策略库与知识库目录无新增/修改/删除。仅事后比对 mtime 不能代替事前访问阻断。
6. 附录 C 所有风险有复现/排除依据及回归结果。高风险未关闭不得仅以 xfail 或“条件通过”完成安全验收。
7. `skip` 要有原因与范围；`xfail(strict=True)` 绑定风险编号并断言期望修复后的安全行为，修复后移除标记。表征当前缺陷的用例通过不代表安全需求通过。
8. 测试样本采用合成或经审核脱敏资料。可测性改造独立评审，不修改业务规则以迎合测试。
9. 附录 H 环境、版本、精确计数、覆盖率、性能原始样本、缺陷与复核字段填写完整；有证据后才能把续修稿升级为实测版。

---

## 附录 C · 缺陷与风险清单

> 本表为风险登记，不是已复现缺陷清单。第 1~20 项沿用历史走查，本次新增第 21~23 项；所有项目的执行证据、工单链接、负责人和关闭状态均待补。正文若保留历史观察，须以此状态口径为准，不代表已上报或已修复。
>
> 稳定编号为 `RISK-001`~`RISK-023`，与下表序号一一对应。高/中/低是初步风险等级，复现后评审；同一风险可关联多个验证点，风险数不等于失败用例数。未证实的危险行为只能在合成数据和临时沙箱中验证。

### C.1 风险登记

| # | 位置 | 问题 | 严重度 | 对应验证点 / 用例 |
|---|---|---|---|---|
| 1 | `db.update_round_field`/`update_kernel_info`/`update_judge_result_kernel` | `created_at` 由 SQLite `CURRENT_TIMESTAMP` 写入（UTC），校验用 `datetime.now()`（本地时区）→ 东八区下新建记录即被判 `too_old`，15 分钟窗形同误拦 | 高 | F-4-3 / UT-DB-055 |
| 2 | `db.update_kernel_info` | 文件复制与目录创建发生在 `not_found`/`too_old` 校验之前；且 `infos_dir` 直接用 `round_id` 拼接，存在路径穿越面 | 高 | F-4-4 / UT-DB-064、UT-DB-065 |
| 3 | `app.py` `GET /api/kernel/file` | 无鉴权 + 可指定路径读取任意文件 | 高 | S-4-4 / UT-PERM-016 |
| 4 | `app.py` `POST /api/import` | 无鉴权、无参数即触发历史数据导入 | 中 | S-4-4 / UT-PERM-015 |
| 5 | `app.py` `db_query` | 非 SELECT 前缀归为写操作并要求特权；前导注释/只读 CTE 会被误拒绝，含 CONFIG 字面量也可能被子串检查误伤。静态逻辑不支持“前导注释已绕过鉴权”的旧结论；真正越权须独立复现 | 高（待复核） | S-4-2 / UT-API-042、UT-API-044、UT-API-045、UT-API-048 |
| 6 | `app.py` `update_config` | 多 key 循环写入非原子，非法 key 之前的合法 key 已落库 | 中 | S-4-3 / UT-PERM-014 |
| 7 | `judge.Resource_Consistency_Check_Layered` | `tool_call` 计数条件依赖 `tool_call_violations[-1]` 的字符串内容，前一事件的 violation 会影响后一事件计数，判定结果与事件顺序相关 | 高 | S-2-4 / UT-JG-109 |
| 8 | `judge._action_allowed` | 空 `actions` 集合 → 放行一切（fail-open） | 高 | S-2-1 / UT-JG-014、UT-JP-018 |
| 9 | `judge._params_match` | 单向子集匹配，actual 的额外参数不受约束 | 中 | S-2-2 / UT-JG-017、UT-JP-017 |
| 10 | `judge._parse_object` vs `_normalize_actions` | identifier 候选键不对称（后者多支持 `uri`/`endpoint`） | 中 | F-2-2 / UT-JG-020、UT-JG-207 |
| 11 | `judge.py` ↔ `resource_consistency_check.py` | 同源分叉双实现，RCC 独有 open flags/元数据能力，存在持续漂移风险 | 高 | R-2-3 / UT-RCC-001 |
| 12 | `db.py` | `set_config` 重复定义（L1067 / L1320）；`config` 表在 `init_db` 与 `init_config_table` 中重复建表 | 中 | F-4-5 / UT-DB-081、UT-DB-082 |
| 13 | `db.update_round_field` | `if field == "is_abnormal"` 为死分支（不在 `UPDATABLE_FIELDS`） | 低 | S-4-5 / UT-DB-052 |
| 14 | `db.init_db` | 原“重命名迁移分支恒假”结论撤回：判断使用 ALTER TABLE 前的 cols 快照，旧 schema 下可能可达；需核对迁移后旧数据保留及列结构 | 低（待复核） | F-4-1 / UT-DB-006 |
| 15 | `watcher.RoundLedger` | `yielded` / `waiting_for_approval` 字段从不被置位 | 低 | F-3-3 / UT-WT-022 |
| 16 | `app.py` 会话 TTL | `ADMIN_SESSION_TTL`（环境变量模块常量）与 config `admin_ttl_minutes` 双来源，改配置不影响实际会话 TTL | 中 | S-4-1 / UT-PERM-007 |
| 17 | 文档 vs 实现 | ①判定实为四维（含轨迹一致性），README/CLAUDE.md 写三维；②`verify_secret` 读 `secret_key`，CLAUDE.md 写 `entry_password`；③`GET /api/rounds` 默认 `limit=50`，`@api_doc` 写 20；④`ir_client` 默认端点是 `/api/translator/translate`，docstring 写 `/api/translator/test` | 中 | F-2-3、F-3-8、F-4-6、S-4-3 / UT-JG-101、UT-DB-084、UT-API-001、UT-IRC-010 |
| 18 | `watcher.FileTailer` | 按 `f.tell()` 记录位点，末尾半行可能被切分为两次读取 | 中 | F-3-1 / UT-WT-008 |
| 19 | `app.py` `GET /api/translator/config` | 响应体中 `api_key` 以明文返回，未脱敏 | 中 | S-1-2、S-5-1 / UT-API-064、UT-JP-032 |
| 20 | `judge` 资源路径归一化 | action `resources[].path` 直传的路径未统一归一化，`/tmp/../etc/passwd` 形态存在漏检面（exec 链路已归一） | 中 | S-2-3 / UT-JP-015 |
| 21 | `db.py` 导入初始化与旧版 fixture 方案 | autouse 生效前可能连接生产数据库并写默认配置；当前测试执行前置阻塞 | 高 | 附录 A/E.3；需导入阶段隔离检查 |
| 22 | `selinux_kb/build_index.py::build` | 旧目标先 unlink 再 replace，替换失败可能丢失旧索引；静态发现，待失败注入复现 | 高 | R-6-2 / UT-KB-050~056 |
| 23 | `xy_skill.py::run_skill_analysis` | 第 6 轮已返回最终文本并 break 后，仍可能进入 `tool_round >= MAX_TOOL_ROUNDS` 收尾分支，二次生成最终文本 | 中 | R-5-2 / UT-XY-029 |

### C.2 关闭标准与回归追踪

以下为每项必填的关闭依据；目前均为**待复现/待确认**，责任角色仅作建议，具体负责人、工单、修复提交、回归 RUN_ID 和复核人均“未指定/未提供”，不得代签。

| 风险编号 | 建议责任角色 | 最小关闭依据 |
|---|---|---|
| RISK-001 | 数据层维护者 | UTC/本地时区、新建记录、899/900/901 秒和禁用时间窗四类对照 |
| RISK-002 | 数据层维护者 | 非法/过期 round 在任何文件副作用之前被拒绝；路径不逃逸临时根 |
| RISK-003 | API/安全维护者 | 鉴权和允许目录边界生效；仅用临时普通文件及根外哨兵文件验证 |
| RISK-004 | API 维护者 | 导入入口权限及副作用边界符合批准契约 |
| RISK-005 | API/数据层维护者 | 注释、CTE、字面量、系统表和写语句逐项对照；误拒绝与真正越权分开记录 |
| RISK-006 | 数据层维护者 | 混合合法/非法 key 请求不会部分提交，或原子性设计经书面确认 |
| RISK-007 | 判定引擎维护者 | 等价事件交换顺序后，各计数与评分不受前一事件污染 |
| RISK-008 | 判定引擎/安全维护者 | 空 actions 的允许/拒绝策略经确认，高危默认放行有修复或正式风险接受 |
| RISK-009 | 判定引擎/安全维护者 | 额外参数白名单或宽松设计明确，预期与反例都有断言 |
| RISK-010 | 判定引擎维护者 | 两入口 identifier 候选键差异有统一规则与回归 |
| RISK-011 | 判定引擎维护者 | 双实现公共语义一致，扩展差异列白名单，不以全文完全相同强行验收 |
| RISK-012 | 数据层维护者 | 重复定义与建表的实际语义明确，消除重复或注明兼容依据 |
| RISK-013 | 数据层维护者 | 白名单与 is_abnormal 分支设计一致，死分支处置有依据 |
| RISK-014 | 数据层维护者 | 旧 schema 到新 schema 的迁移样本保留全部既有数据 |
| RISK-015 | 监控维护者 | 状态字段设置/清理有可达状态转移，或无用字段被确认 |
| RISK-016 | API 维护者 | TTL 来源明确，配置变更后的新旧会话行为有边界测试 |
| RISK-017 | 模块/文档维护者 | 四处文档差异分别复核；需求文档与运行契约一致 |
| RISK-018 | 监控维护者 | 半行追加、轮转、截断和续读无丢失/重复 |
| RISK-019 | API/安全维护者 | 非特权响应不含合成测试密钥，日志及错误响应同样脱敏 |
| RISK-020 | 判定引擎维护者 | 路径等价类、软链与编码边界按批准规则判定 |
| RISK-021 | 测试基建维护者 | 收集前保护已验证，生产路径不可达，临时连接与输出可追踪 |
| RISK-022 | 知识库维护者 | 建库/提交/替换失败保留旧索引，资源释放与错误记录完整 |
| RISK-023 | 研判维护者 | 第 1/5/6 轮直接返回与持续工具调用两类分支中，最终分析只生成一次 |

状态流转：待复现 → 确认缺陷或确认设计 → 修复/风险评审 → 回归 → 复核关闭。无法复现应记录版本、输入和原因，不自动删除风险；安全风险接受不等同于测试通过。

---

## 附录 D · 通用边界与异常矩阵

对每一个外部输入入口，用例至少覆盖下列维度（作为设计 checklist，不逐条展开）：

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

## 附录 E · 测试执行方式（准备方案，尚未执行）

### E.1 执行前置条件

1. **先完成 E.3，再收集或执行任何导入 db/app 的测试。** `--collect-only` 也会导入模块，不是无副作用安全检查。
2. 后端实现测试文件、`conftest.py`、标记、覆盖率配置，在 `pyproject.toml` 增加经 Python 3.14 验证的测试依赖并更新锁文件。当前这些配置未落地，本报告不代为安装或修改依赖。
3. 前端补齐兼容的 Vitest/Vue Test Utils/jsdom 及测试脚本；固定 Node 版本并更新锁文件。当前 `package.json` 没有 `test:unit`，不得把构建成功算作单测成功。
4. 输出目录按本轮 RUN_ID 独立创建，关联代码、未提交差异和样本版本；禁止混入之前 `.coverage` 或不同基线结果。

### E.2 后续命令模板

以下仅供基建和隔离验收完成后使用，**当前不能直接作为可用测试入口，也不是本次运行记录**。在经验证的隔离项目副本中执行，`PWD` 应为该副本的 `backend`，不是在线实例目录。下例假定所有测试依赖已锁定、覆盖率配置已存在，且性能项均标记 `performance`。

```bash
set -euo pipefail
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
ARTIFACTS="$PWD/test-results/$RUN_ID"
mkdir -p "$ARTIFACTS"
export COVERAGE_FILE="$ARTIFACTS/.coverage"
uv run --locked pytest tests/unit --collect-only -q | tee "$ARTIFACTS/collect-unit.txt"
uv run --locked pytest tests/api --collect-only -q | tee "$ARTIFACTS/collect-api.txt"
uv run --locked pytest tests/unit -m 'not performance' -q -ra --strict-markers --timeout=30 --junitxml="$ARTIFACTS/junit-unit.xml" --cov=. --cov-branch --cov-config=tests/.coveragerc --cov-report=term-missing | tee "$ARTIFACTS/unit.log"
uv run --locked pytest tests/api -m 'not performance' -q -ra --strict-markers --timeout=30 --junitxml="$ARTIFACTS/junit-api.xml" --cov=. --cov-branch --cov-append --cov-config=tests/.coveragerc --cov-report=term-missing --cov-report="xml:$ARTIFACTS/coverage.xml" --cov-report="json:$ARTIFACTS/coverage.json" | tee "$ARTIFACTS/api.log"
```

- 第二次追加覆盖率后才生成最终 XML/JSON，按 B.2 分别计算行与分支目标；不得用第一次的覆盖率文件声称全量达标。
- 管道使用 `pipefail`，失败不会因 `tee` 返回 0 被隐藏；模板为快速失败，若某阶段失败，报告必须标记后续阶段未执行。需要收集全部失败时，在 CI 分任务保留各自退出码，不忽略失败继续报全绿。
- P0 快跑同样分别在 `tests/unit`、`tests/api` 两进程以 `-m 'p0 and not performance'` 运行，不合并为 `pytest tests`。
- 性能用例另以 `-m performance` 分两个进程运行，不启用 coverage 或冻结计时，长任务的 timeout 须大于评审后的上限；保存原始计时，不能与上述功能批次混为同一全量运行。
- 前端脚本落地后以非 watch 模式 `npm run test:unit -- --run` 执行，记录独立退出码、用例数和报告；`npm run build` 只证明能构建。

### E.3 首次导入前的生产数据保护

**原稿“先 `import db`、再用 autouse fixture 检查 DB_PATH”的示例已撤除。** `db.py` 的自动初始化在 fixture 运行前就会执行，且包含默认翻译配置写入；仅更换当前目录也不能改变基于 `__file__` 的路径。

可接受的落地路径：

1. 首选专门的非 root 测试沙箱：源码副本与依赖位于隔离环境，不挂载生产 `infos/`、`logs/`、策略目录和知识库索引；需要的最小配置由测试合成，禁止复制 `.env`、真实口令或审计产物。无外网，所有可写输出留在临时根目录。
2. 若须直接针对工作树源码测试，应先独立评审可测性改造：把数据库/输出路径及初始化作为显式入口或可注入依赖；生产默认行为需等价性测试。当前不存在的环境变量开关不得假定可用。
3. 仅测翻译/工具等组件时，可在首次导入前用受控模块替身隔离 db；替身不能算作真实数据层测试。真实 db 用例需要临时 SQLite、真实 SQL 和迁移验证。
4. 无法证明导入前隔离已生效时，停止收集并将执行状态记为“阻塞”，不能先尝试运行再看生产文件是否变化。

守卫应验证：解析后的真实路径位于临时根，处理软链/URI/别名，拒绝生产连接和范围外写入；网络、文件与 SQLite 边界覆盖 collection、setup、call、teardown；退出时关闭连接和线程，恢复模块全局状态。路径子串断言、事后 mtime 比对只能作为补充，不能替代访问阻断。

### E.4 阻塞与失败记录

记录失败阶段（依赖/导入/收集/setup/call/teardown）、命令、退出码、首个异常、受影响验证点和解除条件。依赖缺失、没有收集到测试、隔离失败均不是业务用例通过；不得用重新运行后的成功覆盖第一次失败记录。

---

## 附录 F · 局限与范围外验证

| 局限 | 单测能证明什么 | 不能据此证明什么 |
|---|---|---|
| gevent 与 API | 独立进程中的路由契约、状态与调度参数 | 在线服务并发容量和真实 WebSocket 时延 |
| 模块初始化 | E.3 保护下的临时初始化及数据读写 | 普通 autouse 足以防止生产库访问 |
| Python/Node 生态 | 选定且记录的解释器/依赖组合可运行 | 任意新版运行时均兼容 |
| 伪 `/proc` | 已覆盖字段格式的解析与降级 | 各内核发行版或真实权限环境都一致 |
| LLM 替身 | 解析、校验、工具分发、失败回退 | 真实模型语义正确性与检索后的建议质量 |
| 受控时间与线程 | 有限状态转移、超时分支、限轮与清理 | 真机长时间稳定性和竞态完全不存在 |
| 知识库 | 合成语料解析、微型索引读写、检索引用 | 全量语料召回率或当前内核策略是否允许某访问 |
| 前端逻辑/组件 | jsdom 中的状态、事件和显示契约 | 浏览器布局、真实网络、全流程 E2E |

真实 LLM 质量、OpenClaw 真机联调、全量语料召回评估、WebSocket 系统压测、浏览器 E2E 和长期稳定性归入后续专项/集成验证；本报告不预填其结论。

---

## 附录 G · 本次补充的可实施用例矩阵

### G.1 参数工具与混合流式边界

以下 9 个新增设计标识属于第五章，全部待实现和执行；不重复增加验证点数量。

| 用例标识 | 优先级 | 输入/前置 | 必须断言 | 关联 |
|---|---|---|---|---|
| UT-XY-021 | P0 | 当前 TOOLS/TOOL_HANDLERS | 同名集合共 13 项、无重复；12 个 round schema 与知识库 query schema 区分 | F-5-3 |
| UT-XY-022 | P0 | 合法 query/kind/module/k JSON | 仅白名单参数传给知识库；round 工具始终使用编排器 round_id | F-5-3 |
| UT-XY-023 | P0 | 空参数、畸形 JSON、数组、标量、额外 db_path/round_id | 无默认索引误访问；格式错误明确提示；额外参数不覆盖受控值 | F-5-3 |
| UT-XY-024 | P1 | k 缺省/None/0/1/10/11/非法字符串，kind 大小写，module 空白 | k 回退/夹取，kind 归一化，module 空值转 None；断言传参而非只看返回文字 | F-5-3 |
| UT-XY-025 | P1 | 导入失败、search 抛异常、空 query | 明确降级，空查询不检索；异常字符串不含真实隐私 | F-5-3、R-6-1 |
| UT-XY-026 | P0 | round 工具和参数工具同流，query 尚未完整 | round 工具可提前执行；参数工具在 final 前为 0 次，final 后一次 | F-5-4 |
| UT-XY-027 | P0 | index 不连续、工具交错、arguments 多片、缺失 ID | 参数不串单，按原 index 关联结果，工具消息的 tool_call_id 正确且无重复调用 | F-5-4 |
| UT-XY-028 | P1 | 未知工具、handler 抛异常、handler 返回错误字符串、断流 | error/completed 契约分别核对；已推送文本保留；历史结构合法；预览与模型内容分开校验 | F-5-4、R-5-3 |
| UT-XY-029 | P0 | 第 1/5/6 轮无工具返回文本；每轮持续工具调用 | 正常返回只产生一次最终分析；达到上限不执行额外工具；第 6 轮边界不重复收尾 | R-5-2、RISK-023 |

### G.2 性能采样与判定规则

1. 本报告原有耗时目标属于待验证需求，不是已测结果；新增 P-6-1 的数值门槛待首轮基线后评审。
2. 小规模用例预热至少 5 次，正式采样至少 30 次；正文要求更多时取更高次数。大批量用例至少 5 次独立采样，资源限制导致不足时标注不足，不能填写可靠的 P95。
3. 计时用未冻结的单调高精度时钟；样本生成、fixture 初始化、依赖下载置于计时外；是否包含 DB/文件 IO 必须明确。覆盖率采集与性能测量分开。
4. 保存每次原始值和单位；报告 n、min、均值、中位数、P95、max。P95 使用排序后第 `ceil(0.95*n)` 项（1-based），记录该算法，避免不同库默认分位数不一致。
5. 记录 CPU、内存、负载、内核、文件系统、缓存/预热状态、SQLite/FTS 能力、数据字节数/记录数/命中率。不能清理共享主机缓存来制造“冷启动”；冷状态不可控时明确标注。
6. 逐例比较已批准目标，不平均掉失败样本。跨机器结果不可直接做回归比例；有限规模的增长趋势不构成复杂度证明。
7. `tracemalloc` 是 Python 分配，不包含所有 SQLite/扩展库内存；进程内存另行记录。基线和峰值使用相同方法，输出截断与读入内存分别验证。

性能记录模板（每个 P 验证点一份）：

| 验证点 | RUN_ID/样本版本 | 规模/冷热状态 | 次数 | 均值/P95/max | 内存/输出体量 | 目标/单位 | 原始证据 | 结论 |
|---|---|---|---|---|---|---|---|---|
| 待填 | 未记录 | 未记录 | 未测 | 未测 | 未测 | 取自对应测试要求 | 未提供 | 未执行 |

### G.3 前端 11 项设计展开

以下均关联 F-5-7，优先级 P2，数量是设计编号而非 Vitest 实收项。

| 标识 | 计划文件（相对 `frontend/tests/unit/`） | 断言重点 |
|---|---|---|
| UT-FE-001 | `socket.spec.js` | namespace、连接 path 与必要监听参数 |
| UT-FE-002 | `socket.spec.js` | 重复初始化的单例/去重，销毁后清理监听 |
| UT-FE-003 | `router.spec.js` | 未登录重定向与已登录放行，测试间重置登录状态 |
| UT-FE-004 | `monitor-logic.spec.js` | round_id 已存在时更新，不存在时插入，不产生重复记录 |
| UT-FE-005 | `monitor-logic.spec.js` | 筛选激活时只更新既有记录，不插入不匹配推送 |
| UT-FE-006 | `monitor-logic.spec.js` | 分数 -1/0.5/刚大于 0.5 的样式与 `__loading__` 状态 |
| UT-FE-007 | `privilege.spec.js` | 验证成功后保存合成会话，失败不写；用例后清空 sessionStorage |
| UT-FE-008 | `privilege.spec.js` | 倒计时前一刻/到期/过期状态，组件卸载清理定时器 |
| UT-FE-009 | `rule-select.spec.js` | rule_id/syscall 搜索、无结果、单选和取消不误提交 |
| UT-FE-010 | `security-replay.spec.js` | 非网关模式提示但不阻断，关闭时调用 destroy |
| UT-FE-011 | `security-replay.spec.js` | 0.1x~2x 速度边界与 33%/66%/80%/100% 阶段映射 |

DOM 显示类测试使用组件挂载，不能仅凭复制一份计算公式验证；纯逻辑可独立测试，但须调用项目实际实现。不得声称纯逻辑测试已经覆盖浏览器 E2E。

### G.4 时间窗、权限与副作用的共同断言

| 输入族 | 必须保留的对照 | 防止的误判 |
|---|---|---|
| 15 分钟窗 | 899/900/901 秒、UTC/本地时区、未来/NULL/非法时间、开关关闭 | 只验证超期而漏测刚创建记录及恰好边界 |
| 特权会话 | 无/错误/有效/过期会话；到期前/恰好到期/到期后；新旧会话 | 把非 403 的 400/500 当成合法请求成功 |
| SQL 分类 | SELECT、前导注释、只读 CTE、含 config 字面量、写语句、多语句 | 把误拒绝误写为已绕过鉴权 |
| 路径操作 | 临时根内、根外哨兵、相对路径、软链、round 不存在/过期 | 测试自身读取主机敏感文件或发生目录副作用 |
| 参数工具 | 缺省/错误类型/额外字段、参数未收齐/已收齐 | 按旧 round 工具方式提前调用新工具 |
| 风险表征 | 当前行为断言 + 批准后的安全预期断言 | “复现缺陷的测试通过”被误报成安全验收通过 |

---

## 附录 H · 实测证据记录与交付检查

### H.1 运行基线（当前未产生运行）

| 字段 | 本次状态/后续填写要求 |
|---|---|
| 文档修订 | 2026-09-13，设计续修 |
| 代码版本 | HEAD `ca91e26` + 工作树；正式执行需保存完整提交 ID、diff 及未跟踪源码清单/摘要，不能只写分支名 |
| RUN_ID、开始/结束时间 | 未执行；后续含时区 |
| 执行者/复核者 | 未指定，不代签 |
| OS/内核/CPU/内存/文件系统 | 未采集测试运行环境 |
| Python/uv/Node/npm/SQLite/FTS5 | 未记录测试运行版本 |
| 依赖与样本版本 | 未提供；后续对应后端/前端锁文件、fixture 与样本标识 |
| 导入隔离、外部依赖阻断 | 未验收，RISK-021 为执行前置阻塞 |
| 运行命令与退出码 | 未执行，E.2 仅为模板 |

### H.2 执行汇总模板

| 批次 | collected/selected | passed | failed/error | skipped/xfail/xpass | 耗时 | 退出码 | 原始产物 |
|---|---|---|---|---|---|---|---|
| 后端 unit | 未测 | 未测 | 未测 | 未测 | 未测 | 未运行 | 未提供 |
| 后端 API | 未测 | 未测 | 未测 | 未测 | 未测 | 未运行 | 未提供 |
| 前端 | 未测 | 未测 | 未测 | 未测 | 未测 | 未运行 | 未提供 |
| 性能专项 | 未测 | 未测 | 未测 | 未测 | 未测 | 未运行 | 未提供 |

后端两批次的功能覆盖率可在同基线/同配置下合并；前端与性能报告独立。模板中 `failed/error` 和 `skipped/xfail/xpass` 正式回填时需逐项给数，并遵循 B.1，不能混算。

### H.3 验证点到证据的追踪模板

| 验证点/UT 标识 | 实际 nodeid（含参数 ID） | 输入/样本版本 | 预期 | 实际输出/状态 | 证据路径 | 风险编号 | 复核 |
|---|---|---|---|---|---|---|---|
| 待填 | 尚无测试代码 | 待设计落实 | 取自正文 | 未执行 | 未提供 | 如适用 | 未复核 |

每个验证点必须能追踪至一个或多个真实运行项；一个用例关联多个验证点时复用同一证据，不复制为多个执行项。失败保留完整断言与脱敏日志，不能只截取“passed”摘要。

### H.4 交付产物与续接顺序

| 产物 | 用途 | 当前状态 |
|---|---|---|
| 本报告及风险闭环表 | 设计、范围、需求追踪和待办依据 | 本次续修 |
| 两份 pytest 收集清单与终端日志 | 确认真实 nodeid、跳过原因与退出码 | 待生成 |
| `junit-unit.xml` / `junit-api.xml` | 机器可读执行结果 | 待生成 |
| 同轮合并 `coverage.xml` / `coverage.json` | 行与分支计数、分模块门槛 | 待生成 |
| Vitest 结果与前端覆盖率 | 前端独立证据 | 待生成 |
| 性能原始样本与环境记录 | 可复核统计，不只保留均值 | 待生成 |
| 风险工单、修复及回归记录 | RISK-001~023 的闭环证据 | 待提供 |

后续接续顺序：落实导入前隔离 → 实现 P0 与依赖/fixture → 补齐 P1/P2 及知识库/前端用例 → 分进程执行并留存证据 → 完成风险回归和复核 → 更新本报告实测结论。**本次交付为完整续修设计稿，不是测试已通过的证明。**
