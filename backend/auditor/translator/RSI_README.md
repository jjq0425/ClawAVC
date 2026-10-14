# RSI 自进化（策略翻译模块）

基于历史 round 数据与用户反馈，迭代优化**角色策略库**的可持续闭环。

## 1. 自进化流程（一次进化 = 一条 evolution run）

```
① 选样本     检索并多选 round_id（时间/异常/关键字/round_id 过滤），填写角色说明与用户提示词
② 汇聚上下文  每个 round 的 user_query / IR / 行为 action / 判定结果 / 得分
              ＋ 当前策略库摘要（scenes 清单、tools 的 allowed_values/allowlist/denylist、引导文档）
              ＋ 可选：上一轮的回测反馈（parent_feedback）
③ AI 分析     SSE 流式输出结构化结论：risks（越权） / relax（放宽） / transform（改造）
              schema 校验 + 非法裁剪 + 解析失败自动纠正重试 1 次，温度默认 0
④ 人工评审    三类结论分栏，逐条勾选/编辑/丢弃 → 生成结构化变更计划（diff）
⑤ 安全应用    产物落新建角色库 policies/<role>/（基线只读）
              落盘前快照、支持回滚，应用后重新校验（E 级阻断 / W 级提示）
⑥ 回测+归档    可选开关：同一批 round 改动前后各判定一次并对比
              轮次记录落盘（含 parent_run_id），可查看、可对比、可基于上一轮发起下一轮
```

闭环关键：`parent_run_id` 串起迭代链，下一轮自动带上上一轮「提升/下降」的回测反馈，
形成 **数据 → 分析 → 改造 → 回测 → 反馈** 的可持续循环。

## 2. 字段契约

### 进化轮次（`.rsi_runs/rsi-YYYYMMDD-NNNN.json`）

```json
{
  "run_id": "rsi-20261014-0001", "parent_run_id": "",
  "created_at": "2026-10-14 10:00:00", "role": "analyst_evolved", "base": "default",
  "round_ids": ["c0b5183f"], "role_desc": "只读数据分析师",
  "user_prompt": "重点收紧文件写入", "parent_feedback": "",
  "ai_result": { "risks": [], "relax": [], "transform": [], "summary": "", "assumptions": "" },
  "adopted": [], "applied": {}, "backtest": { "enabled": true, "improved": 0, "regressed": 0 },
  "status": "applied"
}
```

### AI 结论（schema 校验后裁剪）

```json
{
  "risks":     [{"round_id","scene","tool","param","behavior","violation","severity","action"}],
  "relax":     [{"round_id","scene","tool","blocked_behavior","reason","action"}],
  "transform": [{"target","path","current","proposed","reason","risk_level"}],
  "summary": "", "assumptions": ""
}
```

- `severity / risk_level` 仅取 `high|medium|low`，非法值归一为 `medium`；
- `target` 仅允许 `scenes.json` 或 `tools/<scene>.json`，越界项直接丢弃；
- `transform.path` 用点分路径，如 `functions.exec.params.command.constraint_spec.static.denylist`。

### 变更计划条目

`{kind: tighten|relax|transform, target, path, current, proposed, reason, risk_level, round_id}`

- `transform` 且带 `path` → 可直接落盘；
- `tighten / relax` 缺少字段级路径 → 标记为 **需人工处理**（返回 `manual` 列表，不自动改写）。

## 3. 回测策略（分层）

| 模式 | 做法 | 成本 | 说明 |
|------|------|------|------|
| `static`（默认） | 把 round 的原始 `ir_json` 用 judge 规范化后，过一遍**进化后策略库**的 denylist（`rsi.static_deny_with`），再用 `Resource_Consistency_Check_Layered` 判定 | 不耗 LLM | 语义与 `core._apply_static_deny` 一致（已用单测对齐），但可作用于任意策略库目录 |
| `translate`（可选，未默认开启） | 用新策略库重新翻译生成 IR 再判定 | 每 round 1 次 LLM | 高保真，需在开启前评估调用量与耗时 |

回测输出：`before_score / after_score / delta / before_abnormal / after_abnormal / after_violations`，
并汇总 `improved / regressed / unchanged`。

> 实测样例：某 round 原判定 1.0（一致），进化后因命令命中 denylist → 0.0（不一致），delta = -1.0，
> violations 给出 `tool out of IR allow scope: exec`，即回测能真实反映策略收紧的影响。

## 4. 接口清单

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/PUT | `/api/translator/rsi/config` | 独立模型配置（Token 不回显、空值不覆盖、PUT 需特权） |
| POST | `/api/translator/rsi/test` | 连通性自检 |
| GET/PUT | `/api/translator/rsi/prompts` | 三类分析 Prompt 模板（分析/放宽/改造） |
| POST | `/api/translator/rsi/prompts/restore` | 恢复内置默认模板 |
| POST | `/api/translator/rsi/context` | 汇聚 round 明细 + 策略库摘要 |
| POST | `/api/translator/rsi/analyze` | SSE：stage / text / done / error |
| POST | `/api/translator/rsi/plan` | 按勾选生成变更计划 |
| POST | `/api/translator/rsi/apply` | 落新建角色库（快照 + 校验） |
| POST | `/api/translator/rsi/rollback` | 回滚到上一快照 |
| POST | `/api/translator/rsi/validate` | 结构校验（E/W 分级） |
| POST | `/api/translator/rsi/backtest` | 可选回测对比 |
| GET/POST | `/api/translator/rsi/runs` | 轮次历史 / 归档 |
| GET | `/api/translator/rsi/runs/<id>` | 轮次详情 |
| POST | `/api/translator/rsi/runs/<id>/next` | 基于上一轮发起新一轮 |

## 5. 约束与限制

1. **进化作用域**：仅策略库内容（`scenes.json` / `tools/*.json` / 引导文档），**不修改**翻译提示词（Level-1/Level-2、`registry_prompt_format`）。
2. **基线只读**：`default` / `ops` 不会被修改；产物一律落在 `policies/<role>/`。
3. **写入白名单**：目标只能是 `scenes.json` 或 `tools/<name>.json`，且 realpath 必须位于该角色策略库内；写盘用 tmp + `os.replace` 原子替换。
4. **deny-wins**：新增拒绝项应并入 `denylist` 并从 `allowed_values` 移除同串项（由 AI 建议保证，落盘不做自动反向清理）。
5. **已有进程/策略不受影响**：新角色库需确认后手动切换生效（`POST /api/translator/policies/switch`）。
6. **tighten/relax 需人工**：这两类结论没有字段级路径，返回 `manual` 列表由人工在策略库中落实（可在 UI 里转成 transform 项后再应用）。
7. **未配置 Token 时**：analyze 通过 SSE 返回明确 error 事件（"API Token 未配置…"），不会静默失败。

## 6. 验证与回滚

```bash
# 单元与回归
cd test && python3 run_tests.py        # 含 test_module9_rsi（17 条），当前 169/169 全绿

# 快速自检
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from auditor.translator import rsi
print(rsi.get_config()["ok"], rsi.get_prompts()["ok"], rsi.list_runs()["ok"])
PY
```

回滚：每轮应用在写盘前自动快照 `.ai_writer_snapshots/<role>/<ts>`，
`POST /api/translator/rsi/rollback {"role": ...}` 即可恢复；也可在前端「应用」步骤点回滚。
