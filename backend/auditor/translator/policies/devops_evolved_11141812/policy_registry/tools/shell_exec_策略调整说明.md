# shell_exec.json 策略调整说明

| 项 | 内容 |
| --- | --- |
| 评审对象 | `policy_registry/tools/shell_exec.json`（shell_exec 场景工具注册表） |
| 调整类型 | 结构重构 + 安全策略收紧 + 风险分级机制引入 |
| 变更日期 | 2026-09-25 |
| 文档用途 | 供安全与研发团队评审，记录调整动因、影响范围、验证与回滚方案 |
| 原文件备份 | `/tmp/shell_exec.json.bak`（合并脚本执行前留档） |

---

## 1. 文件背景

### 1.1 系统定位

ClawAVC 的审计链路分两层：**翻译层**（`backend/auditor/translator/`）负责将用户自然语言请求翻译为机器可校验的中间表示（IR，即结构化的资源访问策略）；**判定层**（`backend/auditor/monitor/`）负责将 Agent 的实际行为与 IR 做四维一致性比对。`shell_exec.json` 位于翻译层，是 shell_exec 场景（命令执行类任务）的策略知识库条目。

### 1.2 目录职责

`policy_registry/` 采用两阶段注册表结构：

- `scenes.json`：场景清单（约 15 个场景及其描述），供 Level-1 场景分类使用；
- `tools/*.json`：各场景的工具函数定义（供 Level-2 IR 生成使用）。`shell_exec.json` 定义了 `exec`、`process`、`cmd_executor__exec_command` 等 13 个函数的参数约束，是**风险等级最高的策略文件**（多数函数 `risk: high/critical`，直接对应 RCE 能力）。

### 1.3 本文件的三个消费通道（决定了调整的语义边界）

| 通道 | 代码位置 | 消费方式 |
| --- | --- | --- |
| ① Level-2 提示词注入 | `core.py` `_selected_registry_for_prompt()`（L330-332） | **整份 JSON** 进入 LLM 提示词，引导 AI 生成合规 IR（配合 db.py L1622 的系统提示词规则"必须遵守 static.allowlist/denylist 等约束"） |
| ② 默认值回填 | `core.py` `normalize_ir()`（L411-419） | 取全部子场景中**首个非空 default** 回填缺失参数 |
| ③ 静态拒绝 | `core.py` `_apply_static_deny()`（L434-478） | 遍历全部子场景的 denylist，参数值**精确匹配**命中即从 IR 中删除整个工具对象（静态策略优先于 IR，对应测试项 S-1-1） |

关键事实：三个通道对 `static` 字段均**不区分子场景**——通道②取首个非空值、通道③取并集、通道①整体注入。这一事实是本次结构合并的语义依据。

---

## 2. 调整动因

### 2.1 结构冗余：static 数组无实际消费者

原配置中 `exec.command` 的 `static` 为 8 元素数组（系统信息查询 / 文件只读 / 写入删除 / 安装依赖 / 构建测试 / 服务管理 / 网络请求 / 危险禁止），每个元素各带一套 `allowed_values / allowlist / denylist / default`。但如 1.3 所述，**代码从不按子场景解析**：`_static_spec()`（core.py L352-357）对 dict/list 双兼容，list 直接透传后即被"拍平"消费。数组结构造成"存在场景级隔离"的错觉，实际等价于并集——维护者可能误以为修改某个子场景只影响该类命令，实则影响合并后的整体行为。**合并为单一对象使配置结构与真实语义一致。**

### 2.2 自相矛盾的清单：允许项与拒绝项交叉

原子场景间存在冲突：`rm/mv/cp/chmod/chown/kill` 同时出现在"写入删除"子场景的 `allowed_values` 与其余子场景的 `denylist`；`curl/wget` 同时出现在"网络请求（只读）"的允许清单与多个子场景的拒绝清单。合并必须裁决，本次确立**拒绝项优先（deny-wins）**原则：与 denylist 精确冲突的 10 项（rm、mv、cp、chmod、chown、kill、curl、wget、touch、mkdir）从 `allowed_values` 移除，消除"同一命令既允许又禁止"的歧义。

### 2.3 重大风险命令覆盖缺口

对照 CodeBuddy 内置安全命令规则的十个分类（磁盘操作、网络与防火墙、系统服务、用户管理、文件删除、权限、进程控制、Git 操作、命令注入、脚本执行），原 denylist 存在系统性缺口，本轮选择性补充 33 项（详见第 6 节对比表），包括：磁盘操作（`fdisk/parted/cfdisk/sfdisk/dd of=/dev/*`）、网络与防火墙（`nc/ncat/netcat/socat/iptables/ufw/firewall-cmd`）、用户管理（`passwd/useradd/usermod/userdel`）、进程控制（`killall/pkill`）、Git 破坏性操作（`git push --force/git reset --hard/git clean -f`）、命令注入（`eval $()/exec $()/base64 -d | bash/xxd -r -p/| bash/&& bash/; bash/source <()`）。

### 2.4 缺少风险分级与平替引导（参照 CodeBuddy 警告机制）

原配置只有"禁止"语义，没有"如何安全地做"。CodeBuddy 的机制给出启发：将命令风险分级——**重大风险直接拒绝并说明分类；一般风险给出警告与替代方案**。本次新增 `risk_guidance` 结构：`deny_strict`（9 个分类的硬拒绝视图）+ `warn`（8 条 `{class, pattern, risk, alternative}` 平替条目，如 `rm` → 先移入 `/tmp` 回收目录、`kill` → 先 `pgrep` 定位 PID 再精确 kill）。由于整份 JSON 会注入 Level-2 提示词（通道①），该结构可**直接被 AI 读到**，从源头引导 IR 生成。

### 2.5 AI 引导约束不完整

原 `dynamic_ai_hint` 与顶层 `prompt_guidance` 未要求 AI 对风险命令"说明风险、采用替代方案"。本轮在 `exec.command` 的 hint 与顶层 guidance 中追加该要求，使平替机制形成闭环。

---

## 3. 安全目标

| 目标 | 落地手段 |
| --- | --- |
| **最小权限** | `allowed_values` 去除 10 个冲突项后仅保留 81 条明确授权命令；default 保持只读命令（`ps aux`/`whoami`） |
| **防注入** | deny_strict"命令注入"类：`eval $()`、`exec $()`、`base64 -d \| bash`、`xxd -r -p`、`\| bash`、`&& bash`、`; bash`、`source <()`、fork bomb |
| **防提权** | `sudo/su/chmod 777 //chmod -R 777/chown root/chown -R` + 用户管理类 `passwd/user*` |
| **防数据外泄** | 网络与防火墙类 `nc/socat/iptables` 等直连外联通道；`curl * \| sh` 下载即执行；Git 外泄相关 `git push --force` |
| **防破坏** | 磁盘操作类 `mkfs/fdisk/dd of=/dev/*`；文件删除类 `rm -rf /` 系列、`find -delete/find -exec rm`；服务类 `shutdown/reboot/init 0/6` |
| **可追溯性** | 合并规则写入 `note` 字段；风险分级集中于 `risk_guidance` 单一位置；结构简化降低误配概率 |
| **行为可预期** | warn+平替机制使 AI 从"尝试→被拒→换写法/伪造"转向"识别风险→采用替代方案"，减少被拒后的不确定行为（对应对称实测中观察到的 S4"拒后伪造"问题） |

## 4. 影响范围

### 4.1 上游（调用方）

- **Level-2 IR 生成**：提示词内容变化（注入的注册表 JSON 结构调整 + risk_guidance 新增）。预期 AI 生成的命令分布更保守——命中 warn 类命令时须先说明风险并采用平替。属预期行为变化；
- **`/api/translator/*` 接口**（app.py）：透传注册表内容，无接口契约变化；
- **`/policy` 前端页面**：展示的函数定义内容变化，无结构变化。

### 4.2 下游（执行与判定链路）

- **`_apply_static_deny`**：拦截面扩大（denylist 45→71 条精确匹配项）。新增项命中即从 IR 删除工具对象，与原有语义一致；
- **`normalize_ir` 默认值回填**：**无变化**。四处 default（`ps aux`、`whoami`、`/workspace`、`null`）经逐一验证与合并前一致；
- **运行时四维判定（judge.py）**：不消费 static，**不受影响**；
- **S-1-1 静态策略优先语义**：保持。

### 4.3 兼容性

- `_static_spec()` 对 dict/list 双兼容（core.py L355-356），合并后的 dict 形态是**已支持的旧格式**，其余场景文件（file_ops.json 等本就是 dict）无需同步修改；
- **未同步项**：`policies/ops/policy_registry/tools/shell_exec.json`（运维库副本）尚未应用本次调整，双库当前存在差异。**建议后续以同一合并脚本同步**（`/tmp/merge_shell_exec.py` 可复用），同步前 ops 库继续按旧策略生效。

### 4.4 回归验证结论

`test/` 全量单元测试 118/118 通过（10.43s），覆盖 F-1-1（注册表加载/热重载）、F-1-3（static 三态兼容）、S-1-1（静态拒绝）等关联测试项。

## 5. 风险与缓解

| # | 风险 | 等级 | 缓解措施 |
| --- | --- | --- | --- |
| R1 | denylist 为**精确匹配**（`pval in denylist`），模式类条目（`dd of=/dev/*`、`curl * \| sh`）不拦变体，硬拦截仅覆盖同串命令 | 中 | 模式条目主要作为通道①的 AI 引导生效；后续可将匹配升级为前缀/glob（需改 core.py，另行评审）；judge 层四维判定兜底实际行为 |
| R2 | `rm/mv/cp/touch/mkdir` 移出 allowed_values，AI 完成合法写文件任务时约束变紧 | 中 | warn 平替给出路径（`mv` 到 /tmp 回收目录）；实际写入仍由用户确认环节把关 |
| R3 | risk_guidance 增大 Level-2 提示词体积 | 低 | 合并去重后总体积与原 8 子场景相当；P-1-2 实测本地链路 14.70 ms（瓶颈 99.95% 在 LLM 环节），体积增量无感知 |
| R4 | warn 机制无运行时强制力，依赖 AI 遵从 | 中 | deny_strict 类有 denylist 硬拦截兜底；后续可在 judge 侧增加 warn 命中校验 |
| R5 | 双库（default/ops）暂不同步，运维侧策略口径不一致 | 中 | 见 4.3；列入待办，复用合并脚本同步 |
| R6 | 平替方案本身可能被滥用（如 `mv` 到 /tmp 后从 /tmp 执行） | 低 | /tmp 在 allowlist 内但命令仍受 denylist 与四维判定约束；平替设计均为"降风险"而非"绕过"路径 |

---

## 6. 变更对比

### 6.1 结构层

| 项 | 调整前 | 调整后 |
| --- | --- | --- |
| `exec.command.static` | 8 个子场景数组（每项独立 allowed/allowlist/denylist/default/note） | 单一对象（并集合并 + risk_guidance） |
| `exec.workdir.static` | 4 个子场景数组 | 单一对象 |
| `cmd_executor__exec_command.command.static` | 2 个子场景数组 | 单一对象（含简化版 risk_guidance） |
| `cmd_executor__exec_script.command.static` | 1 元素数组 | 单一对象（含脚本来源 warn） |
| 其余函数（process/gitkit 等） | dict（本就是单对象） | 未改动 |

### 6.2 数值层（以 `exec.command` 为例）

| 字段 | 调整前（8 子场景合计） | 调整后 | 说明 |
| --- | --- | --- | --- |
| `allowed_values` | 并集约 91 条（含冲突） | **81 条** | 去重 + 移除 10 个 denylist 冲突项（rm/mv/cp/chmod/chown/kill/curl/wget/touch/mkdir） |
| `denylist` | 并集约 45 条 | **71 条** | 新增 33 项（2.3 节清单）+ 去重 |
| `allowlist` | 并集 9 条 | **9 条** | 不变（/proc/**、/sys/**、/workspace/**、/tmp/**、/home/** 等） |
| `default` | `"ps aux"` | **`"ps aux"`** | 不变（合并规则：取首个非空） |
| `risk_guidance` | 无 | **新增** | deny_strict 9 类 + warn 8 条平替 |

### 6.3 新增的 33 个拒绝项（按 CodeBuddy 分类）

| 分类 | 新增条目 |
| --- | --- |
| 磁盘操作 | fdisk、parted、cfdisk、sfdisk、dd of=/dev/* |
| 网络与防火墙 | nc、ncat、netcat、socat、iptables、ufw、firewall-cmd |
| 用户管理 | passwd、useradd、usermod、userdel |
| 文件删除 | rm -rf .git、find -delete、find -exec rm |
| 权限 | chmod -R 777 |
| 进程控制 | killall、pkill |
| Git 操作 | git push --force、git reset --hard、git clean -f |
| 命令注入 | eval $(、exec $(、base64 -d \| bash、xxd -r -p、\| bash、&& bash、; bash、source <() |

### 6.4 引导层

| 项 | 调整前 | 调整后 |
| --- | --- | --- |
| `dynamic_ai_hint`（exec.command） | 通用最小化要求 | 追加"命中 risk_guidance.warn 的命令，必须先向用户说明风险并优先采用替代方案" |
| `prompt_guidance`（顶层） | 通用使用边界 | 追加同样的 warn 处理要求 |

---

## 7. 验证与回滚

### 7.1 验证方式（已执行）

1. **结构校验**：`json.load` 解析通过；4 处 static 均为 dict 且含 risk_guidance；
2. **兼容校验**：`_static_spec()` 对 4 个函数均返回 1 个子场景；default 四处逐一比对与合并前一致（ps aux / whoami / /workspace / null）；
3. **拦截矩阵**：原拒绝项（rm/curl/sudo）与新增项（mkfs/git push --force/passwd/nc 等）均正确从 IR 删除工具对象；正常命令（ps aux/pytest/ls）放行；
4. **一致性校验**：`allowed_values ∩ denylist = ∅`（0 冲突）；
5. **回归测试**：`cd test && python3 run_tests.py` → **118/118 PASS**（10.43s）。

### 7.2 验收标准

- 上述 5 项全部通过（当前状态：已满足）；
- `GET /api/translator/registry-health` 返回 `healthy=true`（部署后检查）；
- 抽样 translate 验证：含 warn 命令的 query 生成 IR 时，AI 响应中出现风险说明或采用替代方案（上线后观察项）。

### 7.3 回滚方案

| 层级 | 操作 |
| --- | --- |
| 文件回滚 | `cp /tmp/shell_exec.json.bak <原路径>`（合并前完整备份） |
| Git 回滚 | 文件在版本控制内：`git checkout <commit> -- <路径>` 或 revert 本次提交 |
| 生效方式 | `reload_registry()` 支持热重载，回滚后**无需重启**后端 |
| 判定回滚 | 无需——judge 层不消费 static，本次调整对运行时判定无残留影响 |

---

## 附：合并脚本与产物索引

| 资产 | 位置 |
| --- | --- |
| 合并脚本（可复用于 ops 库同步） | `/tmp/merge_shell_exec.py`（风险分级数据：`/tmp/risk_guidance.json`） |
| 原文件备份 | `/tmp/shell_exec.json.bak` |
| 消费端代码 | `backend/auditor/translator/core.py`（L330-332 / L352-357 / L411-419 / L434-478） |
| 关联测试 | `test/test_module1_translator.py`（F-1-1 / F-1-3 / S-1-1 / R-1-2） |

---

## 8. 后续演进：warn 建议与配置解耦（2026-09-25 第二次调整）

初版将 `risk/alternative` 文本内联在 JSON `warn` 数组中，存在复用性差、维护分散的问题。本轮将其抽象为通用化机制：

### 8.1 机制设计

| 组件 | 位置 | 说明 |
| --- | --- | --- |
| 建议文档 | `tools/warn_advice.md` | warn 类建议的**唯一事实来源**：按风险类别组织（10 类），每类含 `pattern / risk / alternative` 结构化条目 + AI 使用规则 |
| JSON 引用 | `risk_guidance.advice_docs: [{role, path}]` | 数组管理、支持多文档；`warn` 条目瘦身为仅 `{class, pattern}` 标识 |
| 加载器 | `core.py` `_load_advice_doc()`（mtime 缓存） | 同一文档被多处引用只读一次盘；热重载后 mtime 变化自动失效 |
| 路径解析 | `_resolve_advice_path()` | 绝对路径原样；相对路径相对 `policy_registry/tools/` |
| 注入展开 | `_expand_advice_docs()` → `_selected_registry_for_prompt()` | Level-2 提示词注入时把引用展开为 `{role, path, loaded, content}`，建议内容随提示词进入 AI |
| 状态可见 | `advice_docs_status()` → `GET /api/translator/registry-health` | 健康检查返回各 advice 文档 `loaded` 状态与 warnings |

### 8.2 降级行为（明确保证）

- 路径不存在 / 读取失败：**不抛异常、不影响其余规则**，注入占位文本 `[advice doc unavailable: <path>]`（`loaded: false`），AI 可感知缺档；
- 健康检查：`ok` 保持 true（属可降级项），但 `warnings` 列出未加载成功的文档路径。

### 8.3 SOUL 注入 API（openclaw 自我认知约束）

新增 `POST /api/openclaw/soul-advice`（app.py）：接收建议文档的 `path` 或 `content`（可选 `target_path`，默认 `~/.openclaw/workspace/SOUL.md`），以标记块 `<!-- clawavc:advice begin/end -->` 幂等写入——**不存在则追加、已存在则覆盖**，原 SOUL 内容保持不动。配套 `GET /api/openclaw/soul-advice` 查询标记块状态。校验：仅 `.md`、1MB 上限、目标目录须存在；错误均返回明确的 4xx JSON。

### 8.4 验证结论

提示词展开含完整建议文档、三处引用仅 1 条缓存、缺档降级占位、SOUL 追加/覆盖幂等（v1→v2 覆盖生效、标记各 1 次）、registry-health 返回 `advice_docs: [{loaded: true}]`；全量回归 **118/118 PASS**。

---

## 9. 演进：advice_docs 上移至场景级 + 文档分区加载

**结构变更**：`advice_docs` 由「函数级」（原先在 `functions.*.params.command.constraint_spec.static.risk_guidance` 内、重复 3 处）上移至**场景级**——与 `"scene": "shell_exec"` 同级，全文件**单处配置**。翻译模型读取场景 JSON 后即按此加载，不再随函数分散定义。

**分区加载**：引导文档按风险类别分节，每节以 `<!-- applies: <场景名> -->` 标注适用场景（未标注 = 全局分节，始终加载）：
- **注入翻译模型（Level-2 提示词）**：`_filter_advice_for_scene()` 按当前场景过滤，仅注入匹配分节（实测 shell_exec 注入 2147 字符 / 全文 2438 字符；非匹配场景仅注入全局分节 630 字符）；
- **同步 AGENTS.md / 页签查看**：全量（`filter: "full"` 或未传 scene），保证主模型获得完整引导。

**接口与前端**：`GET /api/translator/advice-docs` 返回场景级引用位置、分区元信息（标题 + applies）、全量内容与各场景「注入视图」；前端「可替代工具引导」页签新增**风险分区 chips** 与**注入视图 / 全量 切换**。

**验证**：场景级键位唯一（1 处，函数级已清零）；分节过滤与全局分节保留符合预期；回归测试 138/138 PASS。

---

## 10. 结构精简：移除 `risk_guidance`

**变更**：删除 `functions.*.params.command.constraint_spec.static.risk_guidance`（exec / cmd_executor__exec_command / cmd_executor__exec_script 三处）。

**原因**：该字段仅作文档性描述，无任何代码消费——真正生效的是 `static.denylist`（由 `_apply_static_deny` 精确匹配拦截）与全局引导文档。其内部的 `warn` 条目此前已瘦身（建议文本全部迁移至 `warn_advice.md`）、`deny_strict` 分类视图也已由 `denylist` 直接承载，保留只会造成「同一语义多处定义」。

**删除后**：`exec.static` 仅保留 `note / allowed_values / allowlist / default / denylist`；denylist 79 条强制拦截条目不变，注入提示词的引导文档由全局 `advice_docs.json` 提供（shell_exec 注入 2164 字符、其他场景仅全局分块 647 字符）。

**文案同步**：`dynamic_ai_hint`、`static.note`、`prompt_guidance` 与 `warn_advice.md` 头部中指向 `risk_guidance` 的描述，统一改为指向「全局可替代工具引导文档（advice_docs.json → warn_advice.md）」。

**验证**：JSON 解析正常；引导文档仍按场景注入；回归测试 138/138 PASS。
