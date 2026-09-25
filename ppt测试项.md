# ClawAVC 用户态测试项（标准测试用例规格）

> **格式依据**：`测试报告_最终版.docx` —— 每个用例一张 **8 行 2 列**表，字段固定为
> `SR编号 / 用例编号 / 测试要求 / 主要测试文件 / 测试环境 / 测试方法 / 测试结果 / 结论`，
> 运行截图贴在「测试结果」单元格内，判据与实测值写在「结论」单元格内。
>
> **测试项集合**：与 PPT 完全一致，共 3 模块、24 项（23 个唯一编号，`P-3-2` 对应两个标题）。
> 「用户态行为抓取网关（Portkey）与主动拦截」部分暂时丢弃。
>
> **测试方法分两类**：
> - 【A】**自动化**：`python3 test/run_tests.py` 已覆盖（本轮 118 条用例）；
> - 【B】**真实环境 / 网页验证**：需人工执行；其中**真实 LLM 端到端类（F-1-2 / F-1-5 / P-1-2 / R-1-1）已于 2026-09-23 补测完成**（`scripts/real_llm_e2e.py`），其余网页 / 真实环境类本轮仍未覆盖，是可靠性补测的重点。
>
> **证据声明（2026-09-23 修订）**：本文为测试设计 + 自动化实测引用。文中目标值（<50 ms、<20 ms、>2 万行/秒等）为设计门槛；
> 【A】的实测值取自 `test/results/summary.json`、`run.log`、`perf.log`；真实 LLM 类【B】的实测值取自 `test/results/real_llm.json`（首轮）与 `test/results/real_llm_e2e.json`（大样本轮），见测试报告 5.6 / 5.7；其余【B】尚未执行，一律填「待执行」。
> 修订时间：2026-09-23

---

## 0. 结果可信度说明（先读这一节）

本轮 118 条用例全部通过（100.0%），但该结论**只在「替身 + 合成样本」条件下成立**，不等于真实生产环境通过：

| 维度 | 本轮实际 | 是否被真实覆盖 | 对结论的影响 |
| --- | --- | --- | --- |
| 大模型 LLM | 全程 `mock call_llm`（零延迟、返回可控文本） | **已补充（三轮 + 横评）**（2026-09-20 / 09-23）：`scripts/real_llm_check.py` 首轮 + `scripts/real_llm_e2e.py` 大样本轮，模型 `deepseek-v4-flash`；**多模型横评（2026-09-21，模块 4～7）**：同一套真实链路用例横评 4 平台（sensenova / OpenRouter 免费档 / 云知声 MaaS / vLLM 自部署），26 条用例 | **D1 已补齐**：首轮端到端 27 049.12 ms、LLM 占 99.95%、本地 12.89 ms（n=3）；**大样本轮（5.7，按【B】口径）**：同一 query × 20 次端到端（成功 13 次，LLM 占 99.99%、本地 12.02 ms）+ level1 10+10 次（一致率 100%、未注册场景 0）+ 51 条回放（提取成功率 90.2%）；**横评（5.8）**：`u2-flash` 与自部署 `Qwen2.5-7B` 管线用例 7/7 全通过（模型可替换性成立，vLLM 管线 L1+L2 仅 3.4 s、快 14.8×），OpenRouter 免费档持续 429（3/7，R7 跨供应商证据）。**风险 R7 强化**（429 / 超时失败率 35%）、**新增 R8**（有效 IR 产出率仅 30.8%）（测试报告 5.6 / 5.7 / 5.8） |
| 本地后端接口 | `/api/rounds` 由**本地捕获服务**（`test/helpers.py` 的 `_CaptureServer`）承接 | **已补充**（2026-09-24 批次二/三）：对运行中的真实后端（`127.0.0.1:15100`）执行 registry / db/query / intercept 等 9 项接口断言；P-3-3 压测直打真实 `/api/rounds` | `F-3-9`、`P-3-3` 已获真实后端证据（5.9 / 5.10） |
| 数据库 | 临时库 `/tmp/clawavc_ut_*.db`（跑完即删） | **已补充**（2026-09-24 批次二）：对生产库 `infos/db/clawAVC.db` 只读统计（rounds 504 条 / translation_log / intercept 事件）+ S-3-1 篡改测试（备份→改→校验→恢复） | `S-3-1` 防篡改在真实库验证通过；`F-2-5` 落库分布暴露 R9（169 条阈值违反，见 5.9） |
| OpenClaw 会话日志 | 构造样本（`helpers.openclaw_*_line`） | **已补充**（2026-09-24 批次一）：真实日志 `/root/.openclaw/agents/main/sessions/*.jsonl`（9 文件 55 行）全量解析 + trajectory 1568 条命令取 120 条语义分析 + 真实文件轮转/截断 | `F-3-3` 0 脏行、`F-2-6` 一致率 90.3%（R3 复现）、`R-3-2` 通过、`P-3-2` 三档表（D3）——见 5.9 |
| Portkey 网关日志 | 合成样本（2 万行） | **否**（无生产量级样本，约 58 MB/天） | `F-3-4`、`P-3-2(Portkey)` 的生产结论不成立（D2） |
| 前端网页 | 完全未覆盖 | **否** | 判定展示、策略库热重载、拦截事件、防篡改核对等**端到端可见行为均未验证** |
| 版本锚点 | 未记录 commit id 与主机环境 | — | 结果不可绑定到确切代码版本（D5） |

**判定**：
1. **代码级（算法、解析、归一化、判定、容错、纯计算性能）结论可靠且可复现** —— 输入受控、断言明确、脚本可重跑；
2. **系统级结论大部分建立**：**真实 LLM 端到端（F-1-2 / F-1-5 / P-1-2 / R-1-1 的【B】）已于 2026-09-23 补测完成**（见测试报告 5.7）——「瓶颈仅在 LLM 环节」判据成立（LLM 占 99.99%）、Level-1 场景分类稳定（一致率 100%）、`_extract_json` 提取成功率 90.2%；**多模型横评（模块 4～7）确认翻译链路不绑定特定供应商**（测试报告 5.8）；**真实环境 / 真实后端 / 真实日志的 17 项【B】已于 2026-09-24 执行**（测试报告 5.9）——F-3-3 / R-3-2 / S-3-1 / R-1-2 / F-1-3 / F-1-4 / P-1-1 / S-2-1① / S-1-1 通过，F-2-5 暴露 **R9（`is_abnormal` 主链路漏报 33.5%）**、F-2-6 复现 R3（`2>&1` 误写）；仍待补：网页端可视化截图类、Portkey 真实日志（D2）；**P-3-3 阶梯压测已于 2026-09-24 完成（三档成功率 100.0%，D4 闭环，见测试报告 5.10）**；真实 LLM 侧 R7 / R8 / R9 须修复后才能给出对外发布结论；
3. `R-2-1` 的 fail-open 属设计层风险，与测试是否真实无关，须按 P0 修复。

---

## 1. 测试环境（通用定义，各表「测试环境」栏引用）

| 环境 | 组成 | 启动 / 访问方式 |
| --- | --- | --- |
| **E1 自动化环境** | Python 3.9.25、`unittest`（verbosity=2）、单机容器；`mock call_llm`；写库指向临时库 `/tmp/clawavc_ut_*.db`；本地捕获服务承接 `/api/rounds` | `cd test && python3 run_tests.py`（全量 118 条，约 10 s）；单模块 `python3 -m unittest test_module1_translator -v`；产物落 `test/results/` |
| **E2 真实后端** | 后端 Flask+SocketIO，端口 `15100`；接口：`/api/rounds`、`/api/translator/*`、`/api/db/query`、`/api/monitor/*`、`/api/intercept/events` | `bash start.sh` 或 `python3 backend/app.py`；健康检查 `curl http://127.0.0.1:15100/api/config` |
| **E3 真实前端（网页）** | Vue3 + Vite，端口 `15101`；页面：`/policy` 策略库、`/api-docs` 接口调试、`/monitor` 监控、`/replay` 回放、`/database` 数据查询、`/security` 拦截、`/anomaly-chat` 异常对话 | `cd frontend && npm run dev` → 浏览器打开 `http://<host>:15101` |
| **E4 真实 OpenClaw** | 真实会话日志 `/root/.openclaw/agents/main/sessions/<uuid>.jsonl`（含 `.trajectory.jsonl`） | 用真实文件作为 `FileTailer` 输入复跑解析；或在网页观察真实会话产生的 round |
| **E5 真实 LLM** | 初始设计值：`api_base_url=https://api.longcat.chat/openai`、`model=LongCat-2.0-Preview`；**实际执行（2026-09-20 / 09-23 两轮）使用当时生产配置**：`api_base_url=https://token.sensenova.cn/v1/chat/completions`、`model=deepseek-v4-flash`、`temperature=0.0`、`timeout=60`、`json_mode=0`；`api_key` 在 `/api/translator/config` 或 `/settings` 页面配置 | 配置有效 key 后，`/api/translator/translate` 走真实模型（以生产配置库 `ir_translator.*` 实际值为准）；未配置时 `call_llm` 直接返回错误，相关用例只能以 mock 运行 |

---

## 2. 需要人工在网页 / 真实环境执行的测试清单（汇总）

| 用例编号 | 入口 | 关键动作 | 预期 |
| --- | --- | --- | --- |
| F-1-1 | `/policy` + `/api-docs` | 查看场景数与函数定义；修改 `scenes.json` 后请求 `GET /api/translator/registry-path`、`/api/translator/registry-health` | 场景/函数与 json 一致；路径正确；健康态为 true；改坏文件后返回 `healthy=false` 且**不 500** |
| F-1-5 | ~~`/api-docs` → `POST /api/translator/translate`~~ **脚本部分已完成（`scripts/real_llm_e2e.py` 组A，2026-09-23）**；② translation_log 核对已完成（批次二，2026-09-24）；网页截图部分待执行 | 输入一句自然语言 query（如"读取 /tmp/a.txt 并上传到远端"） | **脚本实测**：13/20 轮返回 `{query, level1, level2, validation, meta}` 结构完整；IR 有效产出率 30.8%（R8）；translation_log 最近 8 条 round_id / is_ui_test / has_l1 / has_l2 / has_val 齐备（`real_api_check.json` → `F-1-5【B】②`） |
| P-1-2 | ~~`/api-docs`（真实 LLM）~~ **已完成（`scripts/real_llm_e2e.py`，2026-09-23）** | 同一 query 连续请求 ≥20 次，记录端到端耗时 | **已达成**：n=13 成功轮，LLM 占 99.99%、本地 12.02 ms 与 mock 组同量级（D1 补齐，见测试报告 5.7） |
| S-1-1 | `/security`（拦截策略 / 外工具拦截 / 拦截事件） | 开启拦截，触发一条静态策略禁止的命令 | 即使 IR 允许，该命令被删除；`/api/intercept/events` 出现对应拦截事件 |
| F-3-3 | E4 真实日志 + `/database` | 用真实 session jsonl 复跑解析；在 `/database` 查 round 记录 | 时间戳 / session ID / `round_id` 正确；页面 round 与日志一致 |
| F-3-4 | 真实 `YYYY-MM-DD.jsonl` | 用真实网关日志复跑解析，检查 actions | OpenAI / Anthropic 双风格均解析（当前 Anthropic 缺失，R2） |
| F-3-9 | `/monitor` + `/replay` | 真实跑一轮会话，观察 round_start → round_end | 先占位 `ir_json="__loading__"` 再回填；页面可见完整字段 |
| P-3-3 | ~~`/api-docs` 或压测脚本~~ **已完成（`scripts/p33_load_test.py`，2026-09-24）** | 对真实 `/api/rounds` 做 10/50/100 qps 阶梯、持续 5 分钟 | **已达成**：三档成功率均 100.0%（48000 条落库零差异）；mock 200 / 慢响应 / 5xx 三分支覆盖（D4 闭环，见测试报告 5.10） |
| S-3-1 | `/database`（`/api/db/query`） | 查 `action_json_md5`；手工改 `action_json` 后再校验 | 未篡改一致；篡改检出；无 MD5 旧记录按「无可比对」处理 |
| F-2-5 / S-2-1 | `/replay`（含 `overall_score`、`is_abnormal`）、`/anomaly-chat` | 回放一个含越权行为的 round | 判定文本首行格式固定；`overall_score<0.5` 时 `is_abnormal=1`；页面展示与库一致 |
| R-2-1 | `/replay` | 构造 `actions=[]` 的 IR + 实际 `delete` 事件 | 当前**放行**（fail-open，R1）；修复后应判异常 |

> 注：**F-1-2 与 R-1-1 的【B】（真实 LLM 类，入口 E5）已于 2026-09-23 执行完毕**，不列入上表——F-1-2 组B 10+10 次（一致率 100%、未注册场景 0）、R-1-1 共 51 条真实输出回放（提取成功率 90.2%），实测见测试报告 5.7；P-1-2 / F-1-5 的脚本可自动化部分亦同步完成（表中已标注）。

---

# 一、IR 策略翻译与多角色策略库管理模块（SR-1）

### 【F-1-1】策略知识库加载与角色重载功能验证

| 字段 | 内容 |
| --- | --- |
| SR编号 | SR-1 |
| 用例编号 | F-1-1 |
| 测试要求 | 两阶段注册表正确加载：场景数量与 `scenes.json` 一致，tool 索引按各 json 顶层 `scene` 字段建立；`reload_registry()` 热重载后模块级注册表刷新（无需重启）；三类残缺（`scenes.json` 缺失、`tools/` 为空、单个 tool json 非法）均**降级为空集合而不抛异常**；无 `scene` 字段的文件被丢弃；未配置路径时回退 `_DEFAULT_REGISTRY_DIR`；`GET /api/translator/registry-health` 返回 `healthy=false` 且不得 500 |
| 主要测试文件 | 被测：`backend/auditor/translator/core.py`（`load_scene_registry` L72 / `load_tool_registry` L78 / `reload_registry` L92 / `_get_registry_dir` L35）<br>测试：`test/test_module1_translator.py`（7 条用例） |
| 测试环境 | E1 自动化环境；补充：E2 真实后端 + E3 前端 `/policy`、`/api-docs` |
| 测试方法 | 【A】`python3 -m unittest test_module1_translator -v -k F_1_1`；受控策略库 15 场景 + 15 tool json<br>【B】网页：① 打开 `/policy` 核对场景数与函数定义；② 在 `/api-docs` 发 `GET /api/translator/registry-path`、`/api/translator/registry-health`，截图记录；③ 备份后删除 `scenes.json`（或写入非法 json），重启/重载并再次请求 health，确认返回 `healthy=false`、HTTP 非 500；④ 恢复文件后确认恢复 `healthy=true` |
| 测试结果 | 【A】本轮 7 条用例全 PASS（见 `test/results/run.log`、`summary.json`；逐条输出见 `figures/fig_21_terminal_F_1_1.png`）——执行后在此粘贴运行截图<br>【B】**接口部分已执行（2026-09-24，批次二 `scripts/real_api_check.py`）**：② `GET /api/translator/registry-path`、`/api/translator/registry-health` 均正常（19 scenes / 27 tools）；③ 残缺分支（scenes.json / tools 目录缺失）→ health `ok=false` + 明确 error（非 500）→ ④ 恢复后 `ok=true`（详见 R-1-2【B】）；`/policy` 网页截图仍待人工 |
| 结论 | 【A】通过：加载、热重载、残缺降级、无 `scene` 丢弃、默认目录回退 5 项判据全部成立；其中 `test_F_1_1_missing_scenes_degrade` 为 2026-09-17 批次失败项，本轮已转为 PASS【B】接口部分通过（2026-09-24）：②③④ 三个接口判据全部成立（见测试报告 5.9）；`/policy` 页面可视化仍待人工 |

### 【F-1-2】Level-1 场景分类功能验证

| 字段 | 内容 |
| --- | --- |
| SR编号 | SR-1 |
| 用例编号 | F-1-2 |
| 测试要求 | 输出 `(scenes, meta)`；单场景 query 判定正确；组合任务（跨文件 + 网络多场景）可同时选中多个场景；未知场景经注册表**白名单过滤**被丢弃；LLM 返回空列表 / 非列表 / 无 JSON / 单引号 / 尾随逗号时降级为空场景集且不抛异常；Level-1 提示词含全部场景名与描述，Level-2 提示词仅拼被选中场景的函数定义 |
| 主要测试文件 | 被测：`backend/auditor/translator/core.py`（`level1_classify` L282、`_scene_list_for_prompt` L274）<br>测试：`test/test_module1_translator.py`（5 条） |
| 测试环境 | E1（LLM 为 mock，返回值可控）；补充：E2 + E5 真实 LLM |
| 测试方法 | 【A】`python3 -m unittest test_module1_translator -v -k F_1_2`<br>【B】真实 LLM：在 `/api-docs` 用 `POST /api/translator/level1` 分别提交单场景 query（"帮我读取 /tmp/a.txt"）与组合 query（"读取日志并上传到远端服务器"），各重复 10 次，记录场景集合稳定性与是否出现未注册场景 |
| 测试结果 | 【A】5 条全 PASS（`figures/fig_22_terminal_F_1_2.png`）<br>【B】**已执行（2026-09-23，`scripts/real_llm_e2e.py` 组B，与 `/api/translator/level1` 同一实现链路）**：单场景 10/10 成功且全部返回 `["file_ops"]`；组合 9/10 成功（1 次上游 429）且成功轮全部返回 `["file_ops"]`；**场景集合一致率均 100%、未注册场景 0 次**（`test/results/real_llm_e2e.json` → `group_b`） |
| 结论 | 【A】通过：单场景 / 多场景 / 白名单过滤 / 五类异常降级全部成立<br>【B】**通过（2026-09-23）**：两 query 场景集合稳定率均 100%，原始输出 scenes 100% 落在注册表白名单内；组合 query 模型仅判 `file_ops`（偏保守但稳定），建议在 Level-1 提示词补充「上传 / 发送类动作须选对应 scene」示例（见测试报告 5.7 组B） |

### 【F-1-3】Level-2 IR 生成与归一化功能完备

| 字段 | 内容 |
| --- | --- |
| SR编号 | SR-1 |
| 用例编号 | F-1-3 |
| 测试要求 | 四类非标准形态（缺 `policies` 键、`objects` 为单对象、旧格式 `scene`/`functions` 别名、`constraint_spec.static` 三态）均统一为 `{"policies":[{"subject","objects","effect"}]}`；连续两次 `normalize_ir` 结果逐字段一致（**幂等**）；短名按 `xxx__yyy` 后缀匹配补全为注册表标准 identifier |
| 主要测试文件 | 被测：`backend/auditor/translator/core.py`（`normalize_ir` L329、`_static_spec` L321）<br>测试：`test/test_module1_translator.py`（6 条） |
| 测试环境 | E1 |
| 测试方法 | 【A】`python3 -m unittest test_module1_translator -v -k F_1_3`；重点看 `test_F_1_3_idempotent` 与 `test_F_1_3_static_spec_three_states`<br>【B】网页：`/api-docs` → `POST /api/translator/level2`，传入一份非标准 IR，查看返回是否已归一为标准结构并可按 `static default` 回填参数 |
| 测试结果 | 【A】6 条全 PASS（`figures/fig_23_terminal_F_1_3.png`）<br>【真实 LLM 补充】真实模型输出经 `normalize_ir` 归一后通过 `validate_ir`（首轮 3/3、大样本轮 4 个非空 IR 轮全部通过，见测试报告 5.6 / 5.7）<br>【B】**已执行（2026-09-24，批次二 `scripts/real_api_check.py`）**：接口核查确认 `/api/translator/level2` 为 LLM 生成端点（归一在 translate 链路内部执行，无独立归一化端点）；代码层四类非标准形态（缺 policies / objects 单对象 / 旧格式 scene-functions / static 三态）归一全部产出标准结构（`real_api_check.json` → `F-1-3【B】`） |
| 结论 | 【A】通过：归一 + 幂等 + 三态展开成立，累计耗时仅 0.86 ms（纯内存变换）；真实模型输出归一链路获两轮真实证据【B】通过（2026-09-24）：非标准 IR 归一在真实接口链路与代码层均验证成立（见测试报告 5.9） |

### 【F-1-4】IR 校验规则验证

| 字段 | 内容 |
| --- | --- |
| SR编号 | SR-1 |
| 用例编号 | F-1-4 |
| 测试要求 | 8 类违规结构逐类被 `validate_ir()` 命中并指明 policy 与原因；合法 IR 返回 `ok=True`、`errors=[]`；`ValidationReport` 可 JSON 序列化（前端展示前提）；未知 `subject` 与未注册 tool 计为 **error**（非 warning） |
| 主要测试文件 | 被测：`backend/auditor/translator/core.py`（`validate_ir` L409）<br>测试：`test/test_module1_translator.py`（3 条） |
| 测试环境 | E1；补充：E3 `/policy` 页面（校验结果展示） |
| 测试方法 | 【A】`python3 -m unittest test_module1_translator -v -k F_1_4`<br>【B】在 `/api-docs` 提交一份含未知 subject 的 IR 走 `POST /api/translator/translate`，在 `/policy` 页面查看校验报告是否可见、是否标为 error |
| 测试结果 | 【A】3 条全 PASS（`figures/fig_24_terminal_F_1_4.png`）<br>【B】**已执行（2026-09-24，批次二 `scripts/real_api_check.py`）**：接口核查（校验报告随 translate 返回，无独立校验端点；`/policy` 页面展示部分待人工）+ 代码层验证：未知 subject 与未注册 tool 两类违规均进入 `errors` 且 `ok=false`（`real_api_check.json` → `F-1-4【B】`） |
| 结论 | 【A】通过：8 类违规命中、合法 IR 通过、报告可序列化；未知 subject / 未注册 tool 已由 warnings 升级为 errors，与本文口径一致【B】通过（2026-09-24，代码层）：违规计为 error 的语义验证成立（见测试报告 5.9）；`/policy` 页面可视化仍待人工 |

### 【F-1-5】两阶段翻译结果准确性

| 字段 | 内容 |
| --- | --- |
| SR编号 | SR-1 |
| 用例编号 | F-1-5 |
| 测试要求 | 完整 `translate(query)` 返回 `{query, level1, level2, validation, meta}`；Level-1 完成后 `on_level1_done` **立即触发一次**；DB 写入序列严格为 `pending → level1 → upsert` 共 3 次；Level-1 / Level-2 失败为两个不同中断点且**不残留半成品 IR**；`is_ui_test=True` 记录被标记，不污染真实 round |
| 主要测试文件 | 被测：`backend/auditor/translator/core.py`（`translate` L555）<br>测试：`test/test_module1_translator.py`（4 条） |
| 测试环境 | E1（mock LLM + 临时库）；补充：E2 + E3 `/api-docs`、`/policy` |
| 测试方法 | 【A】`python3 -m unittest test_module1_translator -v -k F_1_5`<br>【B】网页：① `/api-docs` → `POST /api/translator/translate` 提交真实 query，截图返回 JSON；② 在 `/database` 用 `SELECT * FROM translation_log ORDER BY id DESC LIMIT 5` 核对写入序列；③ 断开网络或填错 `api_key` 重发，确认返回明确错误且库内无半成品 IR<br>**【B】执行状态**：①③已由 5.7 组A（2026-09-23）+ 模块4/6/7（2026-09-21）脚本覆盖（结构完整率、失败无残留）；②已由批次二（2026-09-24，`scripts/real_api_check.py`）以等价 SQL 核对——最近 8 条 translation_log 的 round_id / is_ui_test / has_l1 / has_l2 / has_val 全部齐备；网页人工截图仍待执行 |
| 测试结果 | 【A】4 条全 PASS（`figures/fig_25_terminal_F_1_5.png`）<br>【B】**已执行（①③：2026-09-23 `scripts/real_llm_e2e.py` 组A；②：2026-09-24 批次二 `real_api_check.py`）**：① 同一真实 query × 20 次端到端——结构完整返回 13/20（失败 7 次均为上游 429 / 读超时）；成功轮五键齐备、临时库无半成品 IR，`validation.ok` 9/13，**IR 含非空 policies 仅 4/13（30.8%）**（5 次空响应 + 4 次空 `policies`/`objects`）（`real_llm_e2e.json` → `group_a`）；② 真实库 translation_log 最近 8 条字段齐备（`real_api_check.json` → `F-1-5【B】②`）；③ 模块4/6/7 真实模型失败路径均返回明确 RuntimeError 且无残留 |
| 结论 | 【A】通过：结构完整、回调一次、写入序列正确、两类失败均无残留<br>【B】**部分通过（2026-09-23）**：返回结构与「失败不残留半成品 IR」在真实链路成立；但暴露 R7（上游 429 / 超时，35% 轮次整轮失败）与 **R8（真实模型 Level-2 有效 IR 产出率仅 30.8%**，`json_mode=0` 下 `deepseek-v4-flash` 偶发空响应 / 空对象），**须修复 R8 后复测方可给出对外结论**（见测试报告 5.7） |

### 【P-1-1】策略注册表加载与热重载耗时

| 字段 | 内容 |
| --- | --- |
| SR编号 | SR-1 |
| 用例编号 | P-1-1 |
| 测试要求 | 当前规模（15 场景 + 15 工具定义）下平均时延 **< 50 ms**；热重载与首次加载**同量级**；冷加载（首次读盘）与热加载（页缓存命中）**分别记录**，各重复 ≥20 次记录均值 / P95 |
| 主要测试文件 | 被测：`backend/auditor/translator/core.py`（`load_*_registry` / `reload_registry`）<br>测试：`test/test_module1_translator.py`（2 条）；实测值落 `test/results/perf.log` L3-4 |
| 测试环境 | E1（单机容器，Python 3.9.25） |
| 测试方法 | 【A】`python3 -m unittest test_module1_translator -v -k P_1_1`，查看 `perf.log` 第 3、4 行<br>【B】真实环境复测：在部署机上用同样脚本跑 20 次冷 / 热加载，确认页缓存与磁盘 IO 差异 |
| 测试结果 | 【A】`reload_registry` 均值 **1.99 ms** / P95 2.13 ms；冷加载 2.08 ms、热重载 2.23 ms（各 20 次）——见 `figures/fig_26_terminal_P_1_1.png`<br>【B】**已执行（2026-09-24，批次一 `scripts/real_env_check.py`）**：部署机 20 次冷/热加载（含 drop_caches）——冷 mean **25.62 ms** / P95 31.22 / max 37.93，热 mean **4.30 ms** / P95 5.73 / max 5.82（`real_env_check.json` → `P-1-1【B】`） |
| 结论 | 【A】通过：均值为 50 ms 门槛的 1/25；冷 2.08 ms 与热 2.23 ms 相差 7%，满足「同量级」判据【B】待填写 |

### 【P-1-2】翻译链路处理耗时（LLM 环节所带来的时间开销）

| 字段 | 内容 |
| --- | --- |
| SR编号 | SR-1 |
| 用例编号 | P-1-2 |
| 测试要求 | LLM 零延迟时单轮本地处理 **< 100 ms**，并验证瓶颈**仅在 LLM 环节**；给出分段耗时（提示词拼装 → `_extract_json` → `normalize_ir` → `validate_ir` → DB 写入）与 P95；**再以真实（或加延迟 mock 的）LLM 跑一组对照**，给出 LLM 带来的时间开销占比 |
| 主要测试文件 | 被测：`backend/auditor/translator/core.py`（`translate` L555、`_extract_json` L157）<br>测试：`test/test_module1_translator.py`（2 条）；`test/results/perf.log` L5-6 |
| 测试环境 | E1（本轮仅零延迟 mock 组）；**补测必须** E5 真实 LLM |
| 测试方法 | 【A】`python3 -m unittest test_module1_translator -v -k P_1_2`<br>【B】真实 LLM 对照组（**已执行两轮**：首轮 `python3 scripts/real_llm_check.py` → `test/results/real_llm.json`；大样本轮 `python3 scripts/real_llm_e2e.py 45 a` → `test/results/real_llm_e2e.json`）：① 配置有效 `api_key`；② 对真实 query 跑端到端 `translate()`，分别记录端到端耗时与 LLM 耗时；③ 与 mock 组 14.70 ms 对照，得出 LLM 环节占比 |
| 测试结果 | 【A】本地链路均值 **14.70 ms**；分段 `extract_json` 0.014 ms / `normalize` 0.011 ms / `validate` 0.004 ms（合计 0.029 ms）——见 `figures/fig_27_terminal_P_1_2.png`<br>【B】**已执行（两轮）**：首轮（2026-09-20）端到端 **27 049.12 ms**、LLM 占 **99.95%**、本地 12.89 ms（n=3）；**大样本轮（2026-09-23，同一 query × 20 次）**：端到端 wall mean **101 227.23 ms** / P95 182 438.12（n=13 成功轮），LLM mean 101 215.21 ms，**LLM 占 99.99%**，本地链路 **12.02 ms** / P95 12.43 / min 9.94 / max 20.54——见测试报告 5.6 / 5.7 |
| 结论 | 【A】本地处理 14.70 ms < 100 ms 门槛成立；三段解析合计仅占 0.2%，说明耗时主体在提示词拼装与 DB 写入<br>【B】**「瓶颈仅在 LLM 环节」判据成立**（由 n=3 的初步成立升级）：mock 14.70 ms / 真实首轮 12.89 ms / 真实大样本 12.02 ms **三组独立样本本地链路同量级**，LLM 占比 99.95%→99.99%；真实端到端 45～186 s 全部由 LLM 调用与上游限流重试构成。须随结论引用：成功轮有效 IR 产出率仅 30.8%（R8，不影响本项耗时结论）（见测试报告 5.7） |

### 【S-1-1】正确拦截处理静态策略

| 字段 | 内容 |
| --- | --- |
| SR编号 | SR-1 |
| 用例编号 | S-1-1 |
| 测试要求 | 静态策略已有的限制**优先于 IR**：在静态策略中禁止某命令 / 路径，即便 IR 显式**允许**该命令，最终输出结果中该命令也应被**删除 / 阻断**；静态策略允许项不受影响，正常放行 |
| 主要测试文件 | 被测：`backend/auditor/translator/core.py`（`_static_spec` L321、`translate` L555 的 denylist 拦截）<br>测试：`test/test_module1_translator.py`（2 条） |
| 测试环境 | E1；补充：E2 + E3 `/security`（拦截策略 / 外工具拦截 / 拦截事件）与 `/api/intercept/events` |
| 测试方法 | 【A】`python3 -m unittest test_module1_translator -v -k S_1_1`<br>【B】网页：① 打开 `/security`，开启拦截开关并按提示刷新；② 触发/构造一条被静态策略禁止的命令（如 `rm -rf /`）的调用；③ 在 `/api/intercept/events` 或页面事件列表确认出现拦截事件，且被禁命令未出现在最终输出；④ 对照组：静态策略允许的命令正常放行 |
| 测试结果 | 【A】2 条全 PASS（`figures/fig_28_terminal_S_1_1.png`）<br>【真实 LLM 补充】模块4/6/7 的 S-1-1 用例在 3 个真实模型上全部 PASS：真实 LLM 即使生成 `rm -rf /`，最终 IR 也不含被禁命令（见测试报告 5.8）<br>【B】**已执行（2026-09-24，批次二）**：`GET /api/intercept/events` 返回 **24 条真实拦截事件**（`ir_tool_block` 18 + `ir_timeout` 6，`real_api_check.json` → `S-1-1【B】`）；`/security` 网页截图仍待人工 |
| 结论 | 【A】通过：IR 允许的被禁命令在最终输出中被删除，静态约束已注入 Level-2 提示词【B】待填写<br>**注意**：本项仅 2 条用例，是全表覆盖最薄的安全项之一，建议扩充 |

### 【R-1-1】LLM 输出解析鲁棒性

| 字段 | 内容 |
| --- | --- |
| SR编号 | SR-1 |
| 用例编号 | R-1-1 |
| 测试要求 | 对 `_extract_json()` 喂七种形态（纯 JSON、``` 围栏、前后夹带解释文字、多 JSON 块、单引号、尾随逗号、完全无 JSON）均能稳定提取，完全无 JSON 时返回 `{}` 不抛异常；`call_llm` 五类情形（200 / 401 / 超时 / 连接失败 / 缺 `choices`）均返回明确错误而不抛未捕获异常；重试按 `max_retry=2`（共 3 次）+ `sleep(1.5**attempt)` 退避；同一 query 多次输出结构基本一致 |
| 主要测试文件 | 被测：`backend/auditor/translator/core.py`（`_extract_json` L157、`call_llm` L106 起）<br>测试：`test/test_module1_translator.py`（9 条） |
| 测试环境 | E1（mock）；**补测** E5 真实 LLM（真实模型的围栏/夹带文字形态更常见） |
| 测试方法 | 【A】`python3 -m unittest test_module1_translator -v -k R_1_1`<br>【B】真实 LLM：连续 10 次提交同一 query，保存每次原始响应文本，用 `_extract_json` 回放解析，统计提取成功率与结构一致性 |
| 测试结果 | 【A】9 条全 PASS（`figures/fig_29_terminal_R_1_1.png`）；重试参数与退避已固化<br>【B】**已执行（两轮）**：首轮（2026-09-20）8 条（纯 JSON 7 + 夹带文字 1），提取成功率 87.5%；**大样本轮（2026-09-23）51 条全量回放**——纯 JSON 46 + 空响应 5，`_extract_json` 提取成功率 **90.2%**，同一 query 的 level1 输出结构一致率 **100%**（`test/results/real_llm_e2e.json` → `r_1_1_replay`） |
| 结论 | 【A】通过（**存在提取边界**）：`test_supp_R_1_1_text_plus_trailing_comma_boundary` 固化「夹带文字 + 尾随逗号」组合形态**当前无法提取**（风险 R4，上层已兜底为空结果不崩溃）<br>【B】**通过（附条件）**：51 条真实输出提取成功率 90.2%、结构一致率 100%；首轮复现的 R4「夹带文字」形态大样本轮未再出现，本轮 5 条失败全部为上游**空响应**（429 重试轮次后 `content=""`，R7/R8 关联，`level2_generate` 已兜底为空 IR 不抛异常）——解析侧容错已达标，剩余失败均来自上游输出质量（见测试报告 5.7） |

### 【R-1-2】注册表缺失与非法内容降级不崩溃

| 字段 | 内容 |
| --- | --- |
| SR编号 | SR-1 |
| 用例编号 | R-1-2 |
| 测试要求 | 三类残缺目录（`scenes.json` 缺失、`tools/` 为空、单个 tool json 非法）加载后**降级为空集合而非抛异常**；`GET /api/translator/registry`、`/api/translator/registry-health` 返回明确错误与 `healthy=false`，**接口不得 500**；警告信息足以定位是哪个文件异常 |
| 主要测试文件 | 被测：`backend/auditor/translator/core.py`（加载层降级）、`backend/app.py`（`/api/translator/registry*` L868/885）<br>测试：`test/test_module1_translator.py`（6 条） |
| 测试环境 | E1 + E2（健康检查接口需真实后端） |
| 测试方法 | 【A】`python3 -m unittest test_module1_translator -v -k R_1_2`<br>【B】网页/接口：① 备份策略库；② 依次删除 `scenes.json`、清空 `tools/`、写入非法 json；③ 每次在 `/api-docs` 请求 `GET /api/translator/registry-health`，记录响应码与 body；④ 恢复文件 |
| 测试结果 | 【A】6 条全 PASS（`figures/fig_30_terminal_R_1_2.png`），其中 2 条为 2026-09-17 批次失败项，本轮转为 PASS<br>【B】**已执行（2026-09-24，批次二 `scripts/real_api_check.py`）**：真实后端上 scenes.json 缺失、tools 目录缺失两个分支——`registry-health` 均 HTTP 200 + `ok=false` + 明确 error 文案（不 500），恢复后 `ok=true`；第三分支（单 tool json 非法）由 load 层降级覆盖、接口不感知，已在 E1 验证（`real_api_check.json` → `R-1-2【B】`） |
| 结论 | 【A】通过：三类残缺均不崩溃，三个健康检查分支均返回明确错误而非 500【B】**通过（2026-09-24）**：残缺注册表两分支在真实后端返回明确错误且可恢复（见测试报告 5.9）<br>**注**：R-1-2 累计耗时 989.0 ms 中 983.79 ms 来自单条 HTTP 健康检查用例的接口往返，非降级逻辑开销 |

---

# 二、用户态行为解析与信息分发模块（SR-2）

### 【F-3-3】OpenClaw 会话日志解析功能

| 字段 | 内容 |
| --- | --- |
| SR编号 | SR-2 |
| 用例编号 | F-3-3 |
| 测试要求 | 正确识别每一次 Round 交互的时间戳、session ID、`round_id`；`stopReason` 三值映射（`toolUse→tool_started`、`end_turn`/`stop→turn_completed`）；`toolResult` 的 tool id 正确；四组 ID 键名变体可归集；非法 JSON 行 / 缺 `type` / 缺 `message` 行返回 `None` 不抛异常；由路径 `agents/main/sessions/<uuid>.jsonl` 推断 `session_key = agent:main:main`（行内显式 `sessionKey` 优先） |
| 主要测试文件 | 被测：`backend/auditor/monitor/watcher.py`（`FileTailer` L537、`parse_line`、L1476）<br>测试：`test/test_module2_parsing.py`（9 条） |
| 测试环境 | E1（构造样本）；**补测** E4 真实日志 `/root/.openclaw/agents/main/sessions/*.jsonl` + E3 `/database` |
| 测试方法 | 【A】`python3 -m unittest test_module2_parsing -v -k F_3_3`<br>【B】真实日志：① 取一个真实 session（含 `.trajectory.jsonl`）；② 用 `FileTailer(from_end=True)` + `parse_line` 全量解析，统计成功解析率、脏行比例、字段缺失情况；③ 在 `/database` 页面核对由此产生的 round 记录与日志一致 |
| 测试结果 | 【A】9 条全 PASS（`figures/fig_31_terminal_F_3_3.png`）<br>【B】**已执行（2026-09-24，批次一 `scripts/real_env_check.py`）**：真实会话日志全量解析——9 个文件、55 行：**脏行 0（0.0%）**、round 事件 31 条（56.4%）、事件字段 0 缺失（非 user 行的 round_id 缺失按设计走 parent 链归属，由状态机补齐）（`real_env_check.json` → `F-3-3【B】`） |
| 结论 | 【A】通过：Round 字段、stopReason 映射、ID 变体归集、三类异常行全部成立【B】**通过（2026-09-24）**：真实日志解析 0 脏行、0 字段缺失；受部署机真实日志规模所限（55 行），大规模脏行比例结论仍建议积累后复测（见测试报告 5.9） |

### 【F-3-4】Portkey 网关日志解析功能完备

| 字段 | 内容 |
| --- | --- |
| SR编号 | SR-2 |
| 用例编号 | F-3-4 |
| 测试要求 | messages 与 tools 取自 `requestOptions[0].finalUntransformedRequest.body`；`user_query` 取最后一条 `role=user` 的 content 并清理 Sender metadata 与 `[时间戳]` 前缀，`last_llm_message` 优先 `response.preview`；actions **双风格（OpenAI `tool_calls` / Anthropic `tool_use`）均解析**；`arguments` 三态兼容；`requestOptions` 为空数组 / 非数组 / 字段缺失时降级不抛异常；可回退 `transformedRequest`；按 `YYYY-MM-DD.jsonl` 定位当天日志 |
| 主要测试文件 | 被测：`backend/auditor/monitor/watcher.py`（L636-649、`build_actions_from_trajectory`）<br>测试：`test/test_module2_parsing.py`（9 条） |
| 测试环境 | E1（合成样本）；**补测** 真实 `YYYY-MM-DD.jsonl` 网关日志（路径按部署实际填写） |
| 测试方法 | 【A】`python3 -m unittest test_module2_parsing -v -k F_3_4`<br>【B】真实网关日志：① 取一天的真实 `YYYY-MM-DD.jsonl`；② 复跑解析，检查 `sourceType=mcp` 的 404 记录（`requestOptions: []`）是否降级正常；③ 统计 OpenAI / Anthropic 两种风格占比，确认 Anthropic 风格是否被解析 |
| 测试结果 | 【A】9 条全 PASS（`figures/fig_32_terminal_F_3_4.png`）<br>【B】**部分已执行（2026-09-24，批次一）**：部署机未发现 Portkey 网关日志（`/root/.portkey*` 等路径不存在，**数据缺失 D2 维持**）；已用真实 OpenClaw `*.trajectory.jsonl`（含 1 568 条 shell 命令记录）做命令提取与解析验证（服务于 F-2-6，见测试报告 5.9） |
| 结论 | 【A】通过（**存在能力缺口**）：`test_supp_F_3_4_anthropic_tool_use` 固化 **Anthropic `tool_use` 风格当前未被解析**（风险 R2，P1 修复）【B】**维持待执行（D2）**：需先接入真实 Portkey 网关日志（约 58 MB/天量级）方可复跑；OpenClaw trajectory 侧已有真实文件解析证据 |

### 【F-3-9】信息上报链路完整

| 字段 | 内容 |
| --- | --- |
| SR编号 | SR-2 |
| 用例编号 | F-3-9 |
| 测试要求 | 以默认参数初始化 `MonitorOrchestrator`（`openclaw_log_root=~/.openclaw`、`POLL_INTERVAL=0.5`、`IDLE_END_SECONDS=5.0`）跑完整一轮：round_start → turn（IR 先占位后回填）→ round_end；**先上报 `ir_json="__loading__"` 占位再回填真实 IR**；round_end 上报体含 `time_end` / `user_query` / `last_llm_message` / `action_json` / `ir_json` / `judge_result` / `overall_score` / `is_abnormal`；`report_to_clawavc`（L978）为非阻塞 POST `/api/rounds`，不阻塞监控主流程；空闲 ≥5.0 s 触发 `check_idle_end` 强制结束 |
| 主要测试文件 | 被测：`backend/auditor/monitor/watcher.py`（`report_to_clawavc` L978、`_query_and_ir_worker`、`check_idle_end`）、`backend/auditor/monitor/ir_client.py`<br>测试：`test/test_module2_parsing.py`（4 条） |
| 测试环境 | E1（上报由本地捕获服务承接）；**补测** E2 真实后端 + E3 `/monitor`、`/replay`、`/database` |
| 测试方法 | 【A】`python3 -m unittest test_module2_parsing -v -k F_3_9`<br>【B】网页：① 启动真实后端与前端，打开 `/monitor`；② 真实发起一轮 Agent 会话；③ 观察 round_start 出现、`ir_json` 先为 `__loading__` 后被回填；④ 会话结束（或空闲 ≥5 s）后在 `/replay`、`/database` 核对 round_end 八项字段是否齐备 |
| 测试结果 | 【A】4 条全 PASS（`figures/fig_33_terminal_F_3_9.png`），上报字段经本地捕获服务逐字段核对<br>【B】**部分已执行（2026-09-24，批次二）**：真实库 rounds 表 round_end 八字段齐备性统计——502 条 round_end 中 `time_end / user_query / action_json / overall_score / is_abnormal` 100% 齐备，`ir_json` 482（96.0%）、`last_llm_message` 455（90.6%）、**`judge_result` 335（66.7%，缺失与 R7/R8 的 LLM 失败轮关联）**（`real_api_check.json` → `F-3-9【B】部分`）；`/monitor`、`/replay` 网页观察仍待人工 |
| 结论 | 【A】通过：占位回填顺序、完整流转、回调各一次、空闲超时强制结束均成立【B】部分通过（2026-09-24，数据侧）：落库字段齐备性已验证（judge_result 缺失 1/3 属 R7/R8 派生现象而非上报缺陷）；网页流转观察仍待人工（见测试报告 5.9） |

### 【P-3-2】OpenClaw 会话日志扫描吞吐

| 字段 | 内容 |
| --- | --- |
| SR编号 | SR-2 |
| 用例编号 | P-3-2（OpenClaw） |
| 测试要求 | 构造 10 万行（约 85 MB）会话日志，`FileTailer(from_end=True)` 扫描 + `parse_line` 全量解析；扫描与解析吞吐 **> 2 万行/秒**（轮询间隔 0.5 s 内可消化增量）；**短 / 中 / 长三档历史记录解析时间分别成表**；拆分「纯扫描」与「扫描+解析」分段计时 |
| 主要测试文件 | 被测：`backend/auditor/monitor/watcher.py`（`FileTailer` L537、`parse_line`）<br>测试：`test/test_module2_parsing.py`（3 条，与下项共享）；`test/results/perf.log` L7-9 |
| 测试环境 | E1（10 万行合成样本）；**补测** E4 真实日志（真实行宽 / 脏行比例不同） |
| 测试方法 | 【A】`python3 -m unittest test_module2_parsing -v -k P_3_2`，读 `perf.log` 第 7～9 行<br>【B】按统一档位重测：短（1 万行）/ 中（10 万行）/ 长（真实单日全量）三档各跑 3 次，分别记录纯扫描与扫描+解析耗时并成表（补 D3） |
| 测试结果 | 【A】10 万行 / 2.45 s → **40 831 行/秒**；补充拆分：纯扫描 1 101 156 行/秒、扫描+解析 42 298 行/秒（5 万行）——见 `figures/fig_34_terminal_P_3_2.png`<br>【B】**已执行（2026-09-24，批次一 `scripts/real_env_check.py`，真实行形态）**：短（1 万行）scan **31.6～32.6 万行/s**、scan+parse **1.37～1.42 万行/s**；中（10 万行）同量级；长=真实全量 55 行；每档 3 次（`real_env_check.json` → `P-3-2【B】` 三档表） |
| 结论 | 【A】通过：40 831 行/秒为门槛 2.04×；纯扫描与扫描+解析相差 26 倍，**瓶颈在 `parse_line` 而非文件 I/O**<br>【B】**D3 三档表已补**（真实行形态）：真实行更长更复杂，scan+parse 1.42 万行/s 低于合成组 4.08 万行/s 且低于 2 万行/s 门槛；受真实日志池仅 55 行所限（行样本重复采样），数字供参考，**建议积累更大规模真实日志后复测**（见测试报告 5.9） |

### 【P-3-2】Portkey 网关日志扫描吞吐

| 字段 | 内容 |
| --- | --- |
| SR编号 | SR-2 |
| 用例编号 | P-3-2（Portkey） |
| 测试要求 | 同上方法针对网关日志（`YYYY-MM-DD.jsonl`）执行；吞吐满足实时监控需求；短 / 中 / 长三档分别记录；**须以生产量级样本（实测单文件最大约 58 MB/天）单独记录一组，不能只用合成小样本外推** |
| 主要测试文件 | 被测：`backend/auditor/monitor/watcher.py`<br>测试：`test/test_module2_parsing.py`；`test/results/perf.log` L8 |
| 测试环境 | E1（2 万行合成样本）；**补测必须**生产量级真实单文件（约 58 MB/天） |
| 测试方法 | 【A】`python3 -m unittest test_module2_parsing -v -k P_3_2`<br>【B】取真实单日 `YYYY-MM-DD.jsonl`（约 58 MB），单独跑一组并记录：文件行数、字节数、纯扫描耗时、扫描+解析耗时、行/秒；同时补短 / 中 / 长三档 |
| 测试结果 | 【A】2 万行 / 0.28 s → **71 354 行/秒**（**合成样本**）<br>【B】**待执行（数据缺失 D2）** |
| 结论 | 【A】合成样本下吞吐达标（3.57×）<br>【B】**生产量级结论本轮不成立，必须补测后才能对外给出** |

### 【P-3-3】信息上报接口 qps 测试

| 字段 | 内容 |
| --- | --- |
| SR编号 | SR-2 |
| 用例编号 | P-3-3 |
| 测试要求 | 对各模块信息上报接口施加**阶梯压力（10/50/100 qps，持续 5 分钟）**；mock 上游返回 200 / 慢响应 / 5xx；统计**上报成功率**与平均能捕获的信息量级；目标 qps 下无数据丢失（轮转与缓冲不丢行） |
| 主要测试文件 | 被测：`backend/auditor/monitor/watcher.py`（`report_to_clawavc` L978）、`backend/app.py`（`POST /api/rounds` L320）<br>测试：`test/test_module2_parsing.py`（1 条）；`test/results/perf.log` L10 |
| 测试环境 | E1（本地捕获服务，200 次短时突发）；**补测必须** E2 真实后端 `/api/rounds` |
| 测试方法 | 【A】`python3 -m unittest test_module2_parsing -v -k P_3_3`<br>【B】按本文口径重做：① 用压测脚本/工具对 `http://127.0.0.1:15100/api/rounds` 依次施加 10 / 50 / 100 qps，每档持续 5 分钟；② mock 上游 200 / 慢响应 / 5xx 三种返回各跑一轮；③ 统计成功数与成功率，并在 `/database` 核对落库条数是否一致（补 D4） |
| 测试结果 | 【A】200 次上报全部到达，0.38 s 完成，**qps = 525**（短时突发口径）——见 `figures/fig_35_terminal_P_3_3.png`<br>【B】**已执行（2026-09-24，批次三 `scripts/p33_load_test.py` + `p33_fix_5xx.py`，真实后端）**：10 / 50 / 100 qps × 300 s 三档——成功率均 **100.0%**（3000 / 15000 / 30000 条），48 000 条压测写入与 HTTP 成功数逐条一致（带 `p33-load-` 前缀，结束即清理）；mock 上游三分支：200 正常 300/300、慢响应（6 s > timeout 5 s）全部失败但**异常被捕获不中断**、5xx 300 次全部失败但**客户端不中断**（`p33_load_test.json`） |
| 结论 | 【A】数字上为 100 qps 门槛的 5.25 倍，但**口径是「200 次短时突发」，与「阶梯 + 持续 5 分钟」不可比**；图中未出现慢响应与 5xx 分支<br>【B】**通过（2026-09-24，D4 闭环）**：真实后端阶梯压测 100 qps × 300 s 成功率 100.0%、落库零差异；慢响应 / 5xx 下上报客户端失败被捕获、主流程不中断（R-3-4 语义获真实证据）。注：100 qps 档实际用时 626 s，单压测机调度已近极限，更高压力需分布式施压（见测试报告 5.10） |

### 【S-3-1】采集是否防篡改

| 字段 | 内容 |
| --- | --- |
| SR编号 | SR-2 |
| 用例编号 | S-3-1 |
| 测试要求 | 未篡改时库内 `action_json_md5` 与本地对同串计算的 MD5 **一致**；`verify_action_json_integrity(round_id)` 返回 `True`；直接篡改 `action_json` 后返回 `False`（可检出）；`action_json_md5` 为空的旧记录返回 `None`（按「无可比对」处理，**不误判为篡改**）；经 `update_round_end` / `update_round_field` 合法更新后 MD5 同步刷新且仍返回 `True` |
| 主要测试文件 | 被测：`backend/db.py`（`action_json_md5`、`verify_action_json_integrity`、`update_round_*`）<br>测试：`test/test_module2_parsing.py`（5 条） |
| 测试环境 | E1（临时 SQLite）；**补测** E2 + E3 `/database`（`/api/db/query`） |
| 测试方法 | 【A】`python3 -m unittest test_module2_parsing -v -k S_3_1`<br>【B】网页：① 在 `/database` 用 `SELECT id, action_json, action_json_md5 FROM rounds ORDER BY id DESC LIMIT 5` 取一条真实记录；② 用外部工具对同一 `action_json` 计算 MD5 并与库内值比对；③ 用 `/api/db/query` 把 `read` 改为 `write` 后再校验，确认检出篡改；④ 取一条无 MD5 的历史记录，确认不误判 |
| 测试结果 | 【A】5 条全 PASS（`figures/fig_36_terminal_S_3_1.png`），四条判据成立且两条合法更新路径均同步刷新 MD5<br>【B】**已执行（2026-09-24，批次二 `scripts/real_api_check.py`）**：经 `/api/db/query` 取最新 5 条真实记录——库内 MD5 与本地重算 **5/5 一致**（legacy 无 MD5 行 0 条）；**篡改检出链**：admin 改 `read`→`write` 后 `verify_action_json_integrity` 返回 `False` → 恢复原值后返回 `True` 且逐字节还原（`real_api_check.json` → `S-3-1【B】`） |
| 结论 | 【A】通过：正反向证据链完整【B】**通过（2026-09-24）**：真实库 MD5 一致性与篡改检出 / 恢复链全部成立（见测试报告 5.9） |

### 【R-3-2】日志轮转、截断容错

| 字段 | 内容 |
| --- | --- |
| SR编号 | SR-2 |
| 用例编号 | R-3-2 |
| 测试要求 | 历史日志混入非法 JSON 行、被截断半行时**不影响解析**（非法行跳过、好行正常产出）；模拟轮转（inode 变化，以 `(st_dev, st_ino)` 判定 L549）后 offset 重置并重读全量**不漏读**；模拟截断（`st_size < pos` L555）后 pos 回 0 重读；路径不存在 / 是目录 / 无权限时被跳过，其他路径解析不受影响 |
| 主要测试文件 | 被测：`backend/auditor/monitor/watcher.py`（`FileTailer` L537-560）<br>测试：`test/test_module2_parsing.py`（5 条） |
| 测试环境 | E1；补充：E4 真实日志目录下做真实轮转（拷贝 + 重命名触发 inode 变化） |
| 测试方法 | 【A】`python3 -m unittest test_module2_parsing -v -k R_3_2`<br>【B】真实环境：① 监控一个真实 session 文件；② 用 `logrotate` 或 `mv` + 新建同名文件触发轮转；③ 观察监控是否重读且不漏 round；④ 用 `truncate` 截断文件，确认 pos 回 0 重读 |
| 测试结果 | 【A】5 条全 PASS（`figures/fig_37_terminal_R_3_2.png`），含无权限路径（模拟 `PermissionError`）不导致整体崩溃<br>【B】**已执行（2026-09-24，批次一 `scripts/real_env_check.py`）**：以最大真实会话文件副本为监控对象——首读 18 行全量 → `mv` + 新建同名触发轮转（inode 变化）后新文件 9 行**全读不漏** → 截断至 4 行后 pos 回 0 **全读不漏**，零丢失零重复（`real_env_check.json` → `R-3-2【B】`） |
| 结论 | 【A】通过：四类容错全部成立，累计耗时仅 4.50 ms【B】**通过（2026-09-24）**：真实文件轮转 / 截断容错在部署机上验证成立（见测试报告 5.9） |

### 【R-3-4】采集与上报异常不阻塞监控主流程

| 字段 | 内容 |
| --- | --- |
| SR编号 | SR-2 |
| 用例编号 | R-3-4 |
| 测试要求 | `collect_for_round` 抛异常时异常被捕获、round_start 上报照常执行；`report_to_clawavc` 遇 HTTP 失败 / 超时 / 非 200 时**仅记录日志**，主轮询循环（0.5 s）持续运行；IR 翻译失败 / 超时返回 `({}, err)`，**不上报脏 IR**；`judge` 抛异常时上报体降级且主流程不中断 |
| 主要测试文件 | 被测：`backend/auditor/monitor/watcher.py`、`backend/auditor/monitor/ir_client.py`、`backend/auditor/monitor/judge.py`<br>测试：`test/test_module2_parsing.py`（5 条） |
| 测试环境 | E1；补充：E2（停掉后端制造不可达）+ E3 `/monitor` |
| 测试方法 | 【A】`python3 -m unittest test_module2_parsing -v -k R_3_4`<br>【B】网页：① 打开 `/monitor` 保持监控；② 停止后端（或把上报地址指向不可达端口）；③ 观察前端是否仍持续刷新、页面不报错；④ 重启后端后确认后续 round 正常上报（无永久阻断） |
| 测试结果 | 【A】5 条全 PASS（`figures/fig_38_terminal_R_3_4.png`），含连续失败后主流程未被永久阻断<br>【B】**已执行（2026-09-24，批次三 `scripts/p33_load_test.py` mock 分支，数据侧）**：mock 上游慢响应（6 s > 客户端 timeout 5 s）——10 次请求全部超时失败但**异常全被捕获、循环不中断**；mock 5xx——300 次全部失败（`ok=false`）且**无未捕获异常、客户端不中断**（`p33_load_test.json` → `mock`）；`/monitor` 页面截图仍待人工 |
| 结论 | 【A】通过：四类异常隔离与降级全部成立【B】**通过（2026-09-24，数据侧）**：上报失败不阻断监控主流程的判据在真实上报客户端 + mock 上游下验证成立（见测试报告 5.10） |

---

# 三、用户态行为合规判定模块（SR-3）

### 【F-2-5】判定序列化与数据上报正确

| 字段 | 内容 |
| --- | --- |
| SR编号 | SR-3 |
| 用例编号 | F-2-5 |
| 测试要求 | `layered_result_to_dict()` 可 JSON 序列化无丢失；`layered_result_to_text()` 首行文案**逐字符固定**为「【判定结果】行为一致，整体得分: x」/「【判定结果】行为异常，整体得分: x」；某维度 `total_count==0` 时该段落**不输出**（前端解析依赖）；判定结果正确上报主干系统，`overall_score < 0.5` 时 `is_abnormal=1`（**严格小于**，`==0.5` 记为正常） |
| 主要测试文件 | 被测：`backend/auditor/monitor/judge.py`（`layered_result_to_text` L871、`overall_score` L852）、`backend/db.py`（阈值判定 L253）<br>测试：`test/test_module3_judge.py`（4 条） |
| 测试环境 | E1（临时库）；补充：E2 + E3 `/replay`、`/database`、`/anomaly-chat` |
| 测试方法 | 【A】`python3 -m unittest test_module3_judge -v -k F_2_5`<br>【B】网页：① 在 `/replay` 打开一个真实 round，核对判定文本首行与得分展示；② 在 `/database` 查 `SELECT overall_score, is_abnormal FROM rounds ...`，验证 `<0.5` 与 `==0.5` 两种取值的落库结果；③ 在 `/anomaly-chat` 确认异常 round 出现在异常列表中 |
| 测试结果 | 【A】4 条全 PASS（`figures/fig_39_terminal_F_2_5.png`），含 0.5 严格小于边界固化<br>【B】**已执行（2026-09-24，批次二 `scripts/real_api_check.py`，数据侧）**：`/database` 等价 SQL 对生产库 504 条 round 全量统计——**169 条（33.5%）违反阈值语义**：137 条 `<0.5` 却 `is_abnormal=0`（**漏报**）、32 条 `=0.5` 却 `=1`（误标）（`real_api_check.json` → `F-2-5【B】②`）；`/replay`、`/anomaly-chat` 网页部分仍待人工 |
| 结论 | 【A】通过：序列化、文案固定、空维度段落省略、阈值边界全部成立【B】**不通过（2026-09-24，数据侧）→ 新增风险 R9**：根因是 watcher judge worker 异步上报体不含 `is_abnormal`、`db.update_round_end` 对缺失字段跳过更新（沿用建轮默认 0）——E1 仅覆盖两字段齐备路径，属测试盲区暴露的设计缺陷；修复建议见测试报告 7.2 R9 |

### 【F-2-6】Shell 命令语义转义能力

| 字段 | 内容 |
| --- | --- |
| SR编号 | SR-3 |
| 用例编号 | F-2-6 |
| 测试要求 | 六类行为逐类推导正确（读 `cat/head/tail/less/grep`；写 `tee/dd/cp/mv/install` 及源文件 read；删 `rm/rmdir/unlink/shred`；权限 `chmod/chown/setfacl`；网络 `curl/wget/nc/ssh/scp/git clone`；执行 `python x.py` / `./bin` / `node s.js` 并补脚本 read）；五种操作符 `{"|","||","&&",";","&"}` 均正确分段；重定向语义正确且 `> /dev/null`、`2>&1` **不误判为文件写**；相对路径按 workdir 解析、绝对路径正确、`~` 正确展开；嵌套 `bash -c` 逐层解析且无无限递归 |
| 主要测试文件 | 被测：`backend/auditor/monitor/shell_command_semantics.py`（`SHELL_OPERATORS` L32、`_split_segments` L144、`_redirection_behaviors` L159、`analyze_shell_command` L681）<br>测试：`test/test_module3_judge.py`（15 条，全表用例最多） |
| 测试环境 | E1；补充：E5 真实 LLM 产生的真实命令（真实命令形态更复杂） |
| 测试方法 | 【A】`python3 -m unittest test_module3_judge -v -k F_2_6`<br>【B】从真实 OpenClaw 会话中提取真实执行的 shell 命令样本（≥50 条，含管道、重定向、嵌套 `bash -c`），逐条跑 `analyze_shell_command` 并与人工标注的行为类别比对，统计一致率 |
| 测试结果 | 【A】15 条全 PASS（`figures/fig_40_terminal_F_2_6.png`），累计仅 7.71 ms（均值 0.51 ms）<br>【B】**已执行（2026-09-24，批次一 `scripts/real_env_check.py`）**：真实 trajectory 提取 **120 条**去重 shell 命令逐条 `analyze_shell_command`——状态 resolved 74 / partial 46；31 条可规则化比对命令一致率 **90.3%**（28/31，mismatch 为复合命令的分段语义）；**`2>&1` 被误判为文件写 22 条**（R3 真实复现）（`real_env_check.json` → `F-2-6【B】`） |
| 结论 | 【A】通过（**存在两处缺口**）：① `tee` 写类命令当前不支持（风险 R3）；② `~` 保持原样未展开，与本文「`~` 正确展开」口径不一致【B】**部分通过（2026-09-24）**：真实命令语义一致率 90.3%；但 `2>&1` 误判为文件写在真实命令中高频出现（22/120），且暴露 E1 断言盲区（`test_F_2_6_2gt1_no_false_write` 的成员列表断言恰好放过实现生成的 `'&'`）——R3 升级为「中偏高」，修复建议见测试报告 7.2 R3 |

### 【P-2-1】单轮分层判定耗时

| 字段 | 内容 |
| --- | --- |
| SR编号 | SR-3 |
| 用例编号 | P-2-1 |
| 测试要求 | 典型规模（IR 5 策略 / 20 对象、行为事件 30 条）单轮分层判定重复 ≥100 次，记录均值 / P95 / max；单轮目标 **< 20 ms**，**不影响 round 上报时延**；须注明归一化（`_normalize_actions`）是否纳入计时 |
| 主要测试文件 | 被测：`backend/auditor/monitor/judge.py`（`_normalize_actions` L1064）<br>测试：`test/test_module3_judge.py`（2 条）；`test/results/perf.log` L11-12 |
| 测试环境 | E1（单机容器，Python 3.9.25） |
| 测试方法 | 【A】`python3 -m unittest test_module3_judge -v -k P_2_1`<br>【B】在生产规模数据（对象 / 事件量级放大一个数量级）下复测，确认仍远低于 20 ms |
| 测试结果 | 【A】`layered_judge` 均值 **0.52 ms** / P95 0.80 ms（不含归一化）；补充组 Mean 0.69 ms / P95 0.82 ms / Max 0.88 ms；含归一化的完整 `judge()` 为 0.15 ms——见 `figures/fig_41_terminal_P_2_1.png`<br>【B】**已执行（2026-09-24，批次一 `scripts/real_env_check.py`）**：生产规模 10×（50 策略 / 200 对象 / 300 事件）× 100 次——mean **21.17 ms** / P95 22.14 / min 20.57 / max 25.73（`real_env_check.json` → `P-2-1【B】`） |
| 结论 | 【A】通过：均值为 20 ms 门槛的 1/38，Max 0.88 ms 亦远低于门槛，可判定**不影响 round 上报时延**；两条记录已分别标注是否含归一化【B】**边界（2026-09-24）**：10× 规模 mean 21.17 ms **微超 20 ms 门槛（超 5.9%）**，P95 22.14 ms；基准规模余量 38.5×。属规模外推的边界现象，不影响 round 级秒量级时延结论，但建议在优化判定器索引（如对象查找哈希化）后复测 |

### 【S-2-1】分层判定结构与评分能力正确

| 字段 | 内容 |
| --- | --- |
| SR编号 | SR-3 |
| 用例编号 | S-2-1 |
| 测试要求 | 判定维度与代码实现一致（**四维**：`tool_call_consistency` / `tool_trajectory_consistency` / `parameter_consistency` / `resource_access_consistency`）；评分公式 `overall_score = round(mean(仅 total_count>0 的维度), 4)`，四维全空时 `=1.0`；空维度得分 1.0、1/3 命中 0.3333；六类对抗样本（替换工具 / 插入工具 / 参数越权 / 资源越权 / 轨迹乱序 / 网络外发）**均被识别为异常**；良性对照集误报率**单独统计报告**（只报检出率不报误报率的结论不予采纳） |
| 主要测试文件 | 被测：`backend/auditor/monitor/judge.py`（`LayeredCheckResult` L94-96、`overall_score` L852、`_action_allowed` L256）<br>测试：`test/test_module3_judge.py`（7 条）；`test/results/perf.log` L13 |
| 测试环境 | E1；**补测**真实良性样本集（≥30 个正常开发任务） |
| 测试方法 | 【A】`python3 -m unittest test_module3_judge -v -k S_2_1`<br>【B】① 扩充良性对照集至 ≥30 个真实正常开发任务样本，重跑误报率；② 在 `/replay` 抽查 5 个真实 round 的判定结果与人工判断比对 |
| 测试结果 | 【A】7 条全 PASS（`figures/fig_42_terminal_S_2_1.png`）；六类对抗样本全部识别；良性对照 `benign_samples=3, false_positives=0, fpr=0.00`<br>【B】① **已执行（2026-09-24，批次一）**：30 个良性对照样本（工具调用 / 文件读写 / 网络收发三类组合的正常开发任务行为）——**FPR = 0**（30/30 判合规，`real_env_check.json` → `S-2-1【B】①`）；② `/replay` 真实 round 人工比对仍待执行 |
| 结论 | 【A】通过（**两项需处理**）：① 代码实现为**四维**，与本文标题「三维」口径不一致（风险 R5，建议以代码为准修订本文）；② 3 个样本的误报率不具统计效力【B】① **通过（2026-09-24）**：R6 误报率判据初步成立（30 样本 FPR=0，满足「误报率单独统计报告」要求）；② 待人工（见测试报告 5.9） |

### 【R-2-1】空 actions 集合的 fail-open 放行语义

| 字段 | 内容 |
| --- | --- |
| SR编号 | SR-3 |
| 用例编号 | R-2-1 |
| 测试要求 | LLM 未进行任何工具调用（`action_json="[]"`）时能正常跳过处理，不抛异常；`judge(action, IR)` 的 action / IR 各四态共 **4×4 = 16 种组合**均返回合法文本且不抛未捕获异常；**已知风险须以用例固化**：空 `actions` 集合时放行一切（fail-open），`actions=[]` 的 IR 下 `delete` 被判合规 —— 该语义**作为风险上报**（建议改 fail-close 或在 IR 校验阶段禁止空 `actions`），**测试结论不得把该现状写成安全通过** |
| 主要测试文件 | 被测：`backend/auditor/monitor/judge.py`（`_action_allowed` L256-258）<br>测试：`test/test_module3_judge.py`（3 条） |
| 测试环境 | E1；补充：E3 `/replay`（端到端可见） |
| 测试方法 | 【A】`python3 -m unittest test_module3_judge -v -k R_2_1`<br>【B】构造 IR object `actions=[]` + 实际 `delete` 事件的真实 round，在 `/replay` 查看判定结论；修复后应判为异常 |
| 测试结果 | 【A】3 条全 PASS（`figures/fig_43_terminal_R_2_1.png`）；`test_R_2_1_fail_open_semantics` 说明文字为「【代码事实锚定】空 actions 集合返回 True（fail-open）」<br>【B】**已执行（2026-09-24，批次一 `scripts/real_env_check.py`，代码直测）**：`actions=[]` IR + 实际 `delete` / `rm` 事件——判定器 verdict=`yes`（**放行，fail-open 复现**）；对照组 `actions=[read]` + 同一 `delete` 事件——verdict=`no`（正确判越权）（`real_env_check.json` → `R-2-1【B】`）；`/replay` 网页部分仍待人工 |
| 结论 | **本项通过 ≠ 安全达标**：用例通过恰恰说明 fail-open 风险**确认存在**。按本文明确要求，本报告将其列为 **P0 级风险 R1**，不计入安全通过结论；修复后须补充「`actions=[]` + 实际 `delete` 事件应判异常」的反向用例<br>【B】**fail-open 已在真实判定器上复现**（2026-09-24）：空 actions 放行、非空对照正确拦截——风险确认，修复优先级维持 P0（见测试报告 5.9） |

---

## 3. 附：本轮自动化结果索引与补测优先级

| 项 | 内容 |
| --- | --- |
| 自动化执行 | `cd test && python3 run_tests.py` → 118 条用例，PASS 118 / FAIL 0 / SKIP 0，通过率 100.0%，整轮 9.99 s |
| 结果产物 | `test/results/summary.json`（用例级）、`run.log`（unittest 原文）、`perf.log`（13 行性能实测）、`测试报告.md`（118 条明细）、`screenshot_0*.png`；**真实 LLM 两轮**：`real_llm.json` / `real_llm.log`（首轮 2026-09-20）、`real_llm_e2e.json` / `real_llm_e2e.log`（大样本轮 2026-09-23）；**多模型横评**：`online/or/uni/vllm_summary.json` 等（模块4～7，2026-09-21）；**真实环境/接口/压测**：`real_env_check.json/.log`、`real_api_check.json/.log`（2026-09-24 批次一/二）、`p33_load_test.json/.log`（批次三压测） |
| 统计图复现 | `python3 scripts/render_all.py`（48 张图，输出到 `figures/`；真实 LLM 验证图 `fig_47` / `fig_48` 分别由 `scripts/real_llm_check.py`、`scripts/real_llm_e2e.py` 的产物生成，需先跑对应脚本） |
| 完整报告 | `测试报告.md` v1.3（含第 7 章 **9 项风险 R1-R9**、5 项数据缺失 D1-D5，其中 **D1 已补齐**；真实 LLM 端到端见 5.6 / 5.7、多模型横评见 5.8、真实环境/接口见 5.9、压测见 5.10） |
| **补测优先级** | P0：R1 fail-open 改 fail-close；**R9 修复 `is_abnormal` 主链路漏报**（`update_round_end` 按阈值推导或 watcher 上报体补字段，修复后全库复扫 + 历史回填）→ 对应 R-2-1、F-2-5<br>P1：**R8 开启 `json_mode=1` / Level-2 空输出定向重试 / 换模型，目标有效 IR 产出率 ≥80% 后按 5.7 组A 口径复测**（5.8 已验证 vLLM / u2-flash 可作候选，vLLM 管线快 14.8×）；D2 Portkey 真实日志；R2 Anthropic 解析；**R3 修复 `2>&1` 误判为文件写 + 收紧 E1 断言**；R7 配额退避与告警 → 对应 F-1-5 / P-1-2、P-3-2、F-3-4、F-2-6<br>P2：R5 维度口径统一；R4 提取容错；扩充 `S-1-1` 等薄弱项<br>P3：D5 记录 commit id 与主机环境；每轮执行前清空 `test/results/`<br>**已闭环**：~~D1 真实 LLM 对照组（P-1-2）~~（5.6 + 5.7 n=13）；~~F-1-2 / F-1-5 / P-1-2 / R-1-1 的【B】类~~（2026-09-23）；~~多模型可替换性~~（5.8 模块4～7）；~~D3 三档吞吐表~~（5.9 批次一）；~~D4 P-3-3 阶梯压测~~（5.10 批次三：10/50/100 qps × 300 s 成功率 100.0% + mock 三分支）；~~R6 良性误报率①~~（30 样本 FPR=0，②③仍待）；~~F-1-1② / F-1-3 / F-1-4 / F-1-5② / R-1-2 / S-3-1 / R-3-2 / F-2-5② / F-2-6 / F-3-3 / F-3-9 / P-1-1 / P-2-1 / S-1-1 的【B】接口/数据侧~~（2026-09-24 批次一/二；网页可视化部分除外） |
