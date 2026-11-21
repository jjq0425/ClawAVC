# 角色策略库：ops_v2

- **角色说明**：运维角色 v2（与 ops 对齐）
- **派生基线**：`ops`（只读复制，基线未被改动）
- **创建工具**：clawavc-policy-creator skill（`create_role_policy.py`）

## 权限说明（spec 原文）

```json
{
  "role_name": "ops_v2",
  "base_policy": "ops",
  "title": "运维角色 v2（与 ops 对齐）",
  "instruction": "与基线 ops 完全一致：保留全部场景、全部 shell 子场景约束与运维能力；不禁用任何场景，不增删任何命令白/黑名单，不修改文件路径与网络规则。",
  "files": {},
  "network": {},
  "bash": {},
  "scenes": {},
  "actions": {},
  "no_git": false
}
```

## 适配记录

- 按基线 ops 重建：/home/hx/jjq/clawAVC/backend/auditor/translator/policies/ops_v2/policy_registry

## 结构与语义要点

- 本目录 = `README.md` + `policy_registry/`（`scenes.json` + `tools/*.json`），符合 `policy_manager._is_valid_registry` 的有效性判定；
- 三个消费通道：① 整份 tools JSON 注入 Level-2 提示词；② `normalize_ir()` 默认值回填；③ `_apply_static_deny()` 精确匹配静态拒绝；
- deny-wins：denylist 与 allowed_values 冲突时以 denylist 为准（同串项已从 allowed_values 移除）。

## 切换生效

```bash
# 方式一：后端 API（免特权）
curl -X POST http://<backend>/api/translator/policies/switch \
     -H 'Content-Type: application/json' -d '{"name": "ops_v2"}'
# 方式二：前端 /policy 页面切换
# 切换后自动热重载（reload_registry），无需重启后端
```

## 校验

```bash
python3 <skill>/scripts/validate_policy.py /home/hx/jjq/clawAVC/backend/auditor/translator/policies/ops_v2/policy_registry
```
