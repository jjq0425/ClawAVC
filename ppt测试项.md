# ClawAVC 用户态测试项（详细版）

> 依据 PPT 测试项整理，共 3 个模块、24 项；测试项集合与 PPT 完全一致，不增删。
> 「用户态行为抓取网关（Portkey）与主动拦截」部分暂时丢弃。
> 各项「测试内容 / 预期结果」已对照代码走查编写（被测代码位置逐项标注）。
> 修订时间：2026-09-16
>
> **证据声明**：本文为测试设计（静态代码走查 + 文档核对），未运行 pytest / 性能基准。文中目标值（如 <50ms、<20ms）为设计门槛，不是实测结论；执行时按实际记录填写，未执行的一律填"未测"。

---

# 一、IR 策略翻译与多角色策略库管理模块

> 被测代码：`backend/auditor/translator/core.py`（`_extract_json` L157、`level1_classify` L282、`_static_spec` L321、`normalize_ir` L329、`validate_ir` L409、`translate` L555、`load_scene_registry` L72 / `load_tool_registry` L78 / `reload_registry` L92）。注册表目录：`backend/auditor/translator/policies/<policy>/policy_registry`，默认回退 `_DEFAULT_REGISTRY_DIR`（L35）。LLM 全程以替身（mock `call_llm`）替代。

## 1.1 功能验证

### 【F-1-1】策略知识库加载与角色重载功能验证

验证两阶段（包括场景和详细策略）加载、热重载。

- **测试内容**：
  1. 准备完整策略库（`scenes.json` + `tools/*.json`，当前 15 场景 + 15 个 tool json），调用 `load_scene_registry()` / `load_tool_registry()`，记录模块级 `SCENE_REGISTRY` / `TOOL_REGISTRY`；
  2. 修改 `scenes.json`（新增 / 删除场景）后调用 `reload_registry()`，**不重启进程**，再次读取两注册表；
  3. 构造残缺库三种情形分别重载：`scenes.json` 缺失、`tools/` 目录为空、单个 tool json 内容非法；
  4. 构造缺少顶层 `scene` 字段的 tool json 放入 `tools/`；
  5. 未配置或配置路径无效时获取注册表目录。
- **预期结果**：
  1. 两阶段注册表正确加载：场景数量与 json 一致；tool 索引按各 json 顶层 `scene` 字段建立；
  2. `reload_registry()` 后模块级 `SCENE_REGISTRY` / `TOOL_REGISTRY` 刷新为新内容（热重载无需重启）；
  3. 三种残缺情形均降级为空集合而**不抛异常**（否则 `import core` 即崩）；`GET /api/translator/registry-health` 返回 `healthy=false` 与明确错误，接口不得 500；
  4. 无 `scene` 字段的文件被丢弃，不进入索引；
  5. 回退到 `_DEFAULT_REGISTRY_DIR`（`policies/default/policy_registry`）。

### 【F-1-2】Level-1 场景分类功能验证

能够正确根据 query 确定相关场景；正确处理选中 1 个 / 多个的复杂组合任务判定。

- **测试内容**：
  1. mock `call_llm`，输入单场景 query（如"帮我读取 /tmp/a.txt"），检查输出场景集合；
  2. 输入组合任务 query（如"读取日志文件并上传到远端服务器"，跨文件 + 网络多场景），检查多场景选中；
  3. mock LLM 分别返回：含注册表中不存在的场景名、空列表、非列表结构（字符串 / dict）；
  4. 检查 Level-1 提示词（`_scene_list_for_prompt` L274）与 Level-2 提示词拼装内容。
- **预期结果**：
  1. 输出 `(scenes, meta)`，单场景 query 场景判定正确；
  2. 选中 1 个 / 多个的组合任务判定均正确；
  3. 场景经注册表**白名单过滤**，未知场景被丢弃；空列表 / 非列表结构降级为空场景集且不抛异常；
  4. Level-1 提示词包含注册表全部场景名与描述；Level-2 提示词仅拼接被选中场景的函数定义。

### 【F-1-3】Level-2 IR 生成与归一化功能完备

四类非标准形态均被统一为 `{"policies":[{...}]}` 标准结构；连续两次归一化结果一致，幂等性成立。

- **测试内容**：
  1. 构造四类非标准形态样本：① 缺 `policies` 键；② `objects` 为单对象（非数组）；③ 字段别名为旧格式 `scene` / `functions`；④ 字段大小写不一致；
  2. 对同一非标准输入连续执行 `normalize_ir(normalize_ir(x))`（L329）；
  3. 构造 `identifier` 不在注册表中的短名（形如 `xxx__yyy`）样本；
  4. 构造 `constraint_spec.static` 为 list / 单个 dict / 非 list 三态样本（`_static_spec` L321）。
- **预期结果**：
  1. 四类非标准形态均被统一为 `{"policies":[{"subject","objects","effect"}]}` 标准结构；
  2. 连续两次归一化结果逐字段一致，幂等性成立；
  3. 短名按 `xxx__yyy` 后缀匹配正确补全为注册表标准 identifier；
  4. 三态均正确展开为参数约束列表，并按首个 `default` 回填参数。

### 【F-1-4】IR 校验规则验证

在给定一组 IR 中，能正确识别错误 / 正确的结构 IR。

- **测试内容**：在给定的一组 IR 样本中逐类构造违规：① `policies` 缺失 / 非数组；② `policies` 空数组；③ policy 缺 `subject` / `objects` / `effect`；④ `subject` 非已知场景；⑤ tool 对象 `identifier` 不在场景注册表（`*` 通配除外）；⑥ tool 对象 `params[].name` 不在函数定义的 params 中；⑦ file 对象缺 `identifier` 或 `actions`；⑧ `effect` 不为 `allow`。另备一份合法 IR。
- **预期结果**：
  1. 每类违规均被 `validate_ir()`（L409）逐项命中，错误信息指明具体 policy 与违规原因；
  2. 合法 IR 返回 `ok=True`、`errors=[]`；
  3. `ValidationReport` 可 JSON 序列化，供前端展示。

### 【F-1-5】两阶段翻译结果准确性

完整实现端到端测试，能够正确返回 IR 响应。

- **测试内容**：
  1. mock `call_llm` 为可控返回，执行完整 `translate(query)`（L555），检查返回结构；
  2. 检查 `on_level1_done` 回调触发时机与次数；
  3. 查询 `translation_log` 表，核对写入序列；
  4. 分别构造 Level-1 失败、Level-2 失败两种中断场景；
  5. 以 `is_ui_test=True` 调用一次并查库。
- **预期结果**：
  1. 返回 `{query, level1, level2, validation, meta}`，能够正确返回 IR 响应；
  2. Level-1 完成后 `on_level1_done` **立即触发一次**；
  3. DB 写入序列严格为 `insert_translation_log_pending` → `update_translation_log_level1` → 最终 upsert，各 1 次共 3 次；
  4. 阶段失败返回明确错误结构，且**不残留半成品 IR**；
  5. `is_ui_test=True` 记录被标记，不污染真实 round 数据。

## 1.2 性能验证

### 【P-1-1】策略注册表加载与热重载耗时

读取、加载场景、策略的平均时延开销。

- **测试内容**：当前规模（15 场景 + 15 工具定义）下，分别计时：① 单次 `load_scene_registry` + `load_tool_registry`；② `reload_registry()` 热重载。区分冷加载（首次读盘）与热加载（页缓存命中），各重复 ≥20 次记录均值 / P95。
- **预期结果**：平均时延开销目标 <50ms；热重载与首次加载同量级；冷、热两组数据分别记录。

### 【P-1-2】翻译链路处理耗时（LLM 环节所带来的时间开销）

- **测试内容**：mock LLM 为零延迟，单轮 `translate()` 内部分段计时：提示词拼装 → `_extract_json` → `normalize_ir` → `validate_ir` → DB 写入；再以真实（或加延迟 mock 的）LLM 各跑一组对照，记录分段耗时与 P95。
- **预期结果**：LLM 零延迟时单轮本地处理目标 <100ms，验证瓶颈仅在 LLM 环节；对照组给出 LLM 带来的时间开销占比。

## 1.3 安全性验证

### 【S-1-1】正确拦截处理静态策略

对静态策略已有的限制，若 IR 传入，能正确进行拦截和阻断（如不允许访问某命令，即便 IR 传入了允许该命令，最终输出结果应删除）。

- **测试内容**：
  1. 在静态策略（策略库中的静态限制）中禁止访问某命令 / 某路径；
  2. 构造一份 IR，其中显式**允许**该命令 / 路径，走完整翻译 → 判定链路；
  3. 对照组：静态策略允许、IR 也允许的项照常通过。
- **预期结果**：
  1. 静态策略已有的限制优先于 IR：即便 IR 传入了允许该命令，最终输出结果中该命令**被删除 / 阻断**；
  2. 静态策略允许项不受影响，正常放行。

## 1.4 可靠性验证

### 【R-1-1】LLM 输出解析鲁棒性

LLM 输出解析具备足够鲁棒性，同一 query 多次输出基本保持一致。

- **测试内容**：
  1. 对 `_extract_json()`（L157）喂七种形态：纯 JSON、``` 围栏、前后夹带解释文字、多个 JSON 块、单引号、尾随逗号、完全无 JSON；
  2. 对 `call_llm`（L106 起）模拟五类情形：200 正常、401 鉴权失败、超时、连接失败、响应缺 `choices`；
  3. 同一 query 让 LLM（或带随机扰动 mock）输出 10 次，比较 Level-1 / Level-2 结果。
- **预期结果**：
  1. 七种形态稳定提取；完全无 JSON 时返回 `{}` 不抛异常；
  2. 五类情形均返回明确错误而不抛未捕获异常；重试参数按实现固化：`max_retry=2`（共 3 次）、退避 `sleep(1.5**attempt)`，最终失败抛 `RuntimeError("LLM 调用失败（共 3 次）")`；
  3. 同一 query 多次输出基本保持一致（分类与 IR 结构稳定）。

### 【R-1-2】注册表缺失与非法内容降级不崩溃

注册表出现异常内容时能够判定异常，发出警告，方便调试使用。

- **测试内容**：构造三类残缺目录：`scenes.json` 缺失、`tools/` 为空、单个 tool json 非法；分别 `reload_registry()` 后访问 `GET /api/translator/registry` 与 `/api/translator/registry-health`。
- **预期结果**：
  1. 加载降级为空集合而非抛异常；
  2. 两个接口返回明确错误与 `healthy=false`，**不得 500**；警告信息足以定位是哪个文件异常（方便调试使用）。

---

# 二、用户态行为解析与信息分发模块

> 被测代码：`backend/auditor/monitor/watcher.py`（`POLL_INTERVAL=0.5` L50、`IDLE_END_SECONDS=5.0` L51、`FileTailer` L537、Portkey 日志解析 L636-649、`report_to_clawavc` L978、`sessionKey="agent:main:main"` L1476）、`backend/auditor/monitor/ir_client.py`、`backend/db.py`（`action_json_md5`）。

## 2.1 功能验证

### 【F-3-3】OpenClaw 会话日志解析功能

正确识别每一次 Round 交互的时间戳、session ID 等 Agent 任务字段内容。

- **测试内容**：
  1. 构造 `~/.openclaw/.../agents/main/sessions/<uuid>.jsonl` 样本：`user` 消息（含时间戳、`round_id`）、`assistant` 消息（`stopReason` 取 `toolUse` / `stop` / `end_turn` 三值）、`toolResult` 消息（携带 tool id）；
  2. 构造四组 ID 键名变体样本，验证归集；
  3. 构造非法 JSON 行、缺 `type` 行、缺 `message` 行；
  4. 从路径 `agents/main/sessions/<uuid>.jsonl` 推断 session key。
- **预期结果**：
  1. 正确识别每一次 Round 交互的时间戳、session ID 等 Agent 任务字段；
  2. `user` 的 `round_id`、`assistant` 的 `stopReason` 映射、`toolResult` 的 tool id 均正确；
  3. 非法 / 缺字段行返回 `None`，不抛异常；
  4. `session_key` 推断为 `agent:main:main`。

### 【F-3-4】Portkey 网关日志解析功能完备

能正确读取识别会话日志中的 tool、param 等参数信息。

- **测试内容**：
  1. 构造 `YYYY-MM-DD.jsonl` 网关日志：`requestOptions[0].finalUntransformedRequest.body.messages` 含 OpenAI `tool_calls` 与 Anthropic `tool_use` 两种风格，`body.tools` 提供工具定义；
  2. `arguments` 分别为 JSON 字符串 / 已是 dict / 非法 JSON 三态；
  3. 构造 `requestOptions` 为空数组 / 非数组 / 字段缺失的行（覆盖生产中 `sourceType=mcp` 的 404 记录即 `requestOptions: []`）；
  4. 构造仅有 `transformedRequest`（无 `finalUntransformedRequest`）的回退样本；
  5. 验证按 `YYYY-MM-DD.jsonl` 定位当天日志。
- **预期结果**：
  1. 能正确读取识别会话日志中的 tool、param 等参数信息（messages 与 tools 取自 `finalUntransformedRequest.body`）；
  2. `user_query` 取最后一条 `role=user` 的 content 并清理 Sender metadata；`last_llm_message` 取 `response.preview`；
  3. actions 双风格（OpenAI / Anthropic）均解析；`arguments` 三态兼容；
  4. `requestOptions` 空缺时降级不抛异常；
  5. 回退路径 `transformedRequest` 生效；当天日志文件正确定位。

### 【F-3-9】信息上报链路完整

各个模块信息上报接口能正确处理响应和约定的数据信息。

- **测试内容**：
  1. 以默认参数初始化 `MonitorOrchestrator`（`openclaw_log_root=~/.openclaw`、`POLL_INTERVAL=0.5`、`IDLE_END_SECONDS=5.0`），mock clawAVC 各上报端点；
  2. 跑完整一轮：round_start → turn（IR 先占位后回填）→ round_end，逐个核对上报体字段；
  3. 检查 `_query_and_ir_worker` 的占位与回填顺序；
  4. 空闲 ≥5.0s 触发 `check_idle_end` 强制结束。
- **预期结果**：
  1. 各模块信息上报接口能正确处理响应和约定的数据信息；
  2. `_on_round_start` 调用参数与缓存更新条件正确；
  3. **先上报 `ir_json="__loading__"` 占位再回填真实 IR**；
  4. round_end 上报体含 `time_end` / `user_query` / `last_llm_message` / `action_json` / `ir_json` / `judge_result` / `overall_score` / `is_abnormal`；
  5. `report_to_clawavc`（L978）为非阻塞 POST `/api/rounds`，不阻塞监控主流程。

## 2.2 性能验证

### 【P-3-2】OpenClaw 会话日志扫描吞吐

日志扫描与解析吞吐满足实时监控需求，分别给定短、中、长历史记录，记录解析时间。

- **测试内容**：构造 10 万行（约 85MB）OpenClaw 会话日志，`FileTailer`（`from_end=True`）扫描 + `parse_line` 全量解析；另分别给定短 / 中 / 长三档历史记录，各自记录解析时间；拆分"纯扫描"与"扫描+解析"分段计时。
- **预期结果**：扫描与解析吞吐 >2 万行/秒，满足实时监控需求（轮询间隔 0.5s 内可消化增量）；短 / 中 / 长三档解析时间分别成表。

### 【P-3-2】Portkey 网关日志扫描吞吐

日志扫描与解析吞吐满足实时监控需求，分别给定短、中、长历史记录，记录解析时间。

- **测试内容**：同上方法针对网关日志（`YYYY-MM-DD.jsonl`）执行；**须以生产量级样本（实测单文件最大约 58MB/天）单独记录一组**，不能只用合成小样本外推。
- **预期结果**：吞吐满足实时监控需求；短 / 中 / 长三档解析时间分别记录；生产量级样本组单独成表。

### 【P-3-3】信息上报接口 qps 测试

各模块信息上报数据量压力测试，观测平均能捕获的信息量级。

- **测试内容**：对 `/api/rounds` 等各模块信息上报接口施加阶梯压力（如 10/50/100 qps，持续 5 分钟），mock 上游返回 200 / 慢响应 / 5xx；统计上报成功率与平均能捕获的信息量级。
- **预期结果**：目标 qps 下无数据丢失（轮转与缓冲不丢行）、上报成功率达标；观测并记录平均能捕获的信息量级。

## 2.3 安全性验证

### 【S-3-1】采集是否防篡改

采集的数据通过 md5 哈希值能够被正确校验，且未篡改时 md5 值与存入数据库的 md5 一致。

- **测试内容**：
  1. 写入一个 round（`action_json` 非空），读取库中 `action_json_md5`，与本地对同串计算的 MD5 比对；
  2. 调用 `db.verify_action_json_integrity(round_id)`；
  3. 直接在 SQLite 中篡改该行 `action_json`（如把 `read` 改为 `write`）后再校验；
  4. 取一条 `action_json_md5` 为空的旧记录校验；
  5. 经 `update_round_end` / `update_round_field` 合法更新 `action_json` 后再校验。
- **预期结果**：
  1. **未篡改时 md5 值与存入数据库的 md5 一致**；
  2. `verify_action_json_integrity` 返回 `True`；篡改后返回 `False`（防篡改可检出）；
  3. 无 MD5 的旧记录返回 `None`（按"无可比对"处理，不误判为篡改）；
  4. 合法更新时 MD5 同步刷新，仍返回 `True`。

## 2.4 可靠性验证

### 【R-3-2】日志轮转、截断容错

当历史日志存在日志错误时，不影响解析。

- **测试内容**：
  1. 在历史日志中混入非法 JSON 行、被截断的半行；
  2. 模拟文件轮转（inode 变化，`FileTailer` 以 `(st_dev, st_ino)` 判定，L549）；
  3. 模拟文件截断（`st_size < pos`，L555）；
  4. 路径不存在 / 是目录 / 无权限。
- **预期结果**：
  1. 存在日志错误时不影响解析：非法行跳过、好行正常产出；
  2. 轮转后 offset 重置并重读全量，不漏读；
  3. 截断后 pos 回 0 重新读取；
  4. 异常路径被跳过，其他路径解析不受影响。

### 【R-3-4】采集与上报异常不阻塞监控主流程

- **测试内容**：
  1. 使 `collect_for_round` 抛异常；
  2. 使 `report_to_clawavc` 遇 HTTP 失败 / 超时 / 非 200；
  3. 使 `ir_client.translate` 返回 error（或目标不可达）；
  4. 使 `judge` 抛异常。
- **预期结果**：
  1. 异常被捕获，round_start 上报照常执行；
  2. 上报失败仅记录日志，主轮询循环（`POLL_INTERVAL=0.5`）持续运行；
  3. IR 翻译失败时**不上报脏 IR**（保留占位或明确降级）；
  4. 判定异常时上报体降级（字段置空 / 默认值），监控主流程不中断。

---

# 三、用户态行为合规判定模块

> 被测代码：`backend/auditor/monitor/judge.py`（`_normalize_action` L117、`_match_identifier` L201、`_action_allowed` L256、`overall_score` 计算 L852、`layered_result_to_text` L871、`_normalize_actions` L1064）、`shell_command_semantics.py`（`SHELL_OPERATORS` L32、`_split_segments` L144、`_redirection_behaviors` L159、`analyze_shell_command` L681）、`backend/db.py`（阈值判定 L253）。

## 3.1 功能验证

### 【F-2-5】判定序列化与数据上报正确

判定结果能够正确上报给主干系统。

- **测试内容**：
  1. 构造一份含异常行为的 action 集 + 合法 IR，执行分层判定；
  2. 对 `LayeredCheckResult` 分别调用 `layered_result_to_dict()`（asdict 序列化）与 `layered_result_to_text()`（L871）；
  3. 构造某维度 `total_count==0` 的结果，检查文本输出段落；
  4. 端到端跑一轮 round_end，检查判定结果上报主干系统的字段与 `is_abnormal` 标记（`db.insert_round` L253：`overall_score < 0.5 → is_abnormal=1`，分数取自文案 `整体得分: x`）。
- **预期结果**：
  1. dict 可 JSON 序列化无丢失；
  2. text 首行文案逐字符固定：`【判定结果】行为一致，整体得分: <s>` / `【判定结果】行为异常，整体得分: <s>`；
  3. `total_count==0` 的维度段落不输出（前端解析依赖）；
  4. 判定结果能够正确上报给主干系统；`overall_score < 0.5` 时 `is_abnormal=1`（注意：代码为严格小于，`==0.5` 记为正常，用例须固化该边界）。

### 【F-2-6】Shell 命令语义转义能力

Shell 命令语义分析能力完备，如绝对路径、相对路径的转换正确。

- **测试内容**：
  1. 六类行为逐类验证（`analyze_shell_command` L681）：读 `cat/head/tail/less/grep`；写 `tee/dd/cp/mv/install` 及源文件 read；删 `rm/rmdir/unlink/shred`；权限 `chmod/chown/setfacl`；网络 `curl/wget/nc/ssh/scp/git clone`；执行 `python x.py` / `./bin` / `node s.js`（并对脚本文件补 read）；
  2. 操作符分段：`SHELL_OPERATORS={"|","||","&&",";","&"}`（L32）全集，构造管道链与组合命令；
  3. 重定向：`<`（REDIRECT_READ）、`>`、`>>`、`1>`、`1>>`、`2>`、`2>>`；专门验证 `> /dev/null` 与 `2>&1`；
  4. 路径转换（`_resolve_exec_path`）：相对路径 + workdir、绝对路径、`~` 开头；
  5. 嵌套 `bash -c` 多层与包装命令。
- **预期结果**：
  1. 六类行为推导正确，产出对应资源能力事件；
  2. 五种操作符均正确分段，不漏段不串段；
  3. 重定向语义正确：`> /dev/null`、`2>&1` **不误判为文件写**；
  4. **绝对路径、相对路径的转换正确**（相对路径按 workdir 解析、`~` 正确展开）；
  5. 嵌套逐层解析且无无限递归。

## 3.2 性能验证

### 【P-2-1】单轮分层判定耗时

分层判定耗时低，不影响 round 上报时延。

- **测试内容**：典型规模（IR 5 策略 / 20 对象，行为事件 30 条）单轮分层判定，重复 ≥100 次记录均值 / P95 / max；注明归一化（`_normalize_actions`）是否纳入计时。
- **预期结果**：单轮目标 <20ms，**不影响 round 上报时延**；给出均值与 P95 数据及环境说明。

## 3.3 安全性验证

### 【S-2-1】三维分层判定结构与评分能力正确

三个维度的判定规则能正确识别异常。

- **测试内容**：
  1. 核对 `LayeredCheckResult`（judge.py L94-96）实际维度集合并按代码固化用例：**代码实现为四维** `tool_call_consistency` / `tool_trajectory_consistency` / `parameter_consistency` / `resource_access_consistency`（⚠ 与 PPT"三维"口径不一致，须对齐后统一）；
  2. 评分公式：`overall_score = round(mean(仅 total_count>0 的维度), 4)`（L852），四维全空时 `=1.0`；构造空维度、1/3 命中等样本核对得分；
  3. 对抗样本：替换工具 / 插入工具 / 参数越权 / 资源越权 / 网络外发 / 轨迹乱序，各验证能否判异常；
  4. 良性对照集（正常开发任务样本）跑误报。
- **预期结果**：
  1. 判定维度与代码实现一致（四维），判定规则能正确识别异常；
  2. 空维度得分 1.0、1/3 命中 0.3333、全空 overall=1.0，`consistent` 由 violations 决定并与 score 解耦；
  3. 六类对抗样本均被识别为异常（`overall_score < 0.5` 触发 `is_abnormal=1`）；
  4. 良性对照误报率单独统计报告（只报检出率不报误报率的结论不予采纳）。

## 3.4 可靠性验证

### 【R-2-1】空 actions 集合的 fail-open 放行语义

当 LLM 未进行任何工具调用时，能正常跳过处理。

- **测试内容**：
  1. LLM 未进行任何工具调用（`action_json="[]"`），执行完整判定链路；
  2. `judge(action, IR)` 的 action / IR 各四态组合：action ∈ {`None`, `[]`, 标量, 畸形 dict}，IR ∈ {`None`, `{}`, `"__loading__"`, 畸形 JSON}，共 4×4 组合；
  3. 针对代码事实做风险锚定：`_action_allowed`（L256-258）在 `allowed_actions` 为空集合时**直接返回 True**；端到端构造 IR object `actions=[]` + 实际 `delete` 事件验证判定结论。
- **预期结果**：
  1. 当 LLM 未进行任何工具调用时，能正常跳过处理，不抛异常；
  2. 16 种组合均返回合法文本，不抛未捕获异常；
  3. **已知风险须以用例固化**：空 `actions` 集合时放行一切（fail-open），`actions=[]` 的 IR 下 `delete` 被判合规——该语义作为风险上报（建议改 fail-close 或在 IR 校验阶段禁止空 `actions`），测试结论不得把该现状写成安全通过。
