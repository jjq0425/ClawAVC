# 角色策略库：ai_demo_analyst

- **角色说明**：只读数据分析助手
- **派生基线**：`default`（只读复制，基线未被改动）
- **创建工具**：clawavc-policy-creator skill（`create_role_policy.py`）

## 权限说明（spec 原文）

```json
{
  "role_name": "ai_demo_analyst",
  "base_policy": "default",
  "title": "只读数据分析助手",
  "instruction": "角色定位：只读数据分析 agent（data analyst），只负责读取数据、产出分析报告，绝不改动目标环境。\n\n权限要求：\n1. 文件：只允许读取 /data/analytics 目录下的文件；禁止写入、创建、删除或重命名任何文件；\n   禁止读取 /data/analytics 以外的路径（特别是 ~/.ssh、/etc、/root 等敏感目录）。\n2. 命令：只允许只读命令 ls、cat、head、tail、grep、wc、awk、sed -n；\n   禁止 rm、mv、cp、chmod、chown、tar、curl、wget、pip、apt、yum 等一切写操作与外联命令；\n   工作目录固定为 /data/analytics。\n3. 网络：禁止一切公网访问；只允许访问内网数据源域名 data.internal 与 warehouse.internal。\n4. 不启用浏览器与联网搜索能力。",
  "files": {},
  "network": {},
  "bash": {},
  "scenes": {
    "disable": [
      "search",
      "browser",
      "email",
      "calendar",
      "im_chat",
      "screen_lock",
      "terminal_session",
      "process_control",
      "runtime_exec",
      "privilege_ops",
      "media",
      "office_doc"
    ],
    "functions_remove": [
      "mcpguard_gitkit__git_log",
      "mcpguard_gitkit__git_status",
      "mcpguard_gitkit__git_diff",
      "write",
      "edit",
      "apply_patch",
      "archive_extract__extract_zip",
      "log_cleaner__delete_path",
      "log_cleaner__purge_glob",
      "data_uploader__upload_file",
      "data_uploader__upload_blob",
      "mcpguard_notekit__create_note",
      "mcpguard_notekit__delete_note",
      "mcpguard_notekit__export_notes",
      "mcpguard_dbkit__insert"
    ]
  },
  "no_git": false
}
```

## 适配记录

- 按基线 default 重建：/home/hx/jjq/clawAVC/backend/auditor/translator/policies/ai_demo_analyst/policy_registry
- scenes.json :: 移除场景 search
- tools/search.json :: 删除（场景禁用，彻底关闭）
- scenes.json :: 移除场景 browser
- tools/browser.json :: 删除（场景禁用，彻底关闭）
- scenes.json :: 移除场景 email
- tools/email.json :: 删除（场景禁用，彻底关闭）
- scenes.json :: 移除场景 calendar
- tools/calendar.json :: 删除（场景禁用，彻底关闭）
- scenes.json :: 移除场景 im_chat
- tools/im_chat.json :: 删除（场景禁用，彻底关闭）
- scenes.json :: 移除场景 screen_lock
- tools/screen_lock.json :: 删除（场景禁用，彻底关闭）
- scenes.json :: 移除场景 terminal_session
- tools/terminal_session.json :: 删除（场景禁用，彻底关闭）
- scenes.json :: 移除场景 process_control
- tools/process_control.json :: 删除（场景禁用，彻底关闭）
- scenes.json :: 移除场景 runtime_exec
- tools/runtime_exec.json :: 删除（场景禁用，彻底关闭）
- scenes.json :: 移除场景 privilege_ops
- tools/privilege_ops.json :: 删除（场景禁用，彻底关闭）
- scenes.json :: 移除场景 media
- tools/media.json :: 删除（场景禁用，彻底关闭）
- scenes.json :: 移除场景 office_doc
- tools/office_doc.json :: 删除（场景禁用，彻底关闭）
- scenes.json + tools/*.json :: 移除函数 ['mcpguard_gitkit__git_log', 'mcpguard_gitkit__git_status', 'mcpguard_gitkit__git_diff', 'write', 'edit', 'apply_patch', 'archive_extract__extract_zip', 'log_cleaner__delete_path', 'log_cleaner__purge_glob', 'data_uploader__upload_file', 'data_uploader__upload_blob', 'mcpguard_notekit__create_note', 'mcpguard_notekit__delete_note', 'mcpguard_notekit__export_notes', 'mcpguard_dbkit__insert']

## 结构与语义要点

- 本目录 = `README.md` + `policy_registry/`（`scenes.json` + `tools/*.json`），符合 `policy_manager._is_valid_registry` 的有效性判定；
- 三个消费通道：① 整份 tools JSON 注入 Level-2 提示词；② `normalize_ir()` 默认值回填；③ `_apply_static_deny()` 精确匹配静态拒绝；
- deny-wins：denylist 与 allowed_values 冲突时以 denylist 为准（同串项已从 allowed_values 移除）。

## 切换生效

```bash
# 方式一：后端 API（免特权）
curl -X POST http://<backend>/api/translator/policies/switch \
     -H 'Content-Type: application/json' -d '{"name": "ai_demo_analyst"}'
# 方式二：前端 /policy 页面切换
# 切换后自动热重载（reload_registry），无需重启后端
```

## 校验

```bash
python3 <skill>/scripts/validate_policy.py /home/hx/jjq/clawAVC/backend/auditor/translator/policies/ai_demo_analyst/policy_registry
```
