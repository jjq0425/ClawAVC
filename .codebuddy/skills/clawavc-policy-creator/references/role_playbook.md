# 角色适配 Playbook（权限说明 → spec）

> 供 skill 执行者对照使用：第 1 节是映射总表，第 2 节是四个开箱角色模板，
> 第 3 节解释关键语义，第 4 节给出面试问题清单，第 5 节是校验错误修复手册。

## 1. 权限说明 → spec 映射总表

### 1.1 文件场景

| 用户表达 | spec |
| --- | --- |
| "只能读 xx 目录" | `files.read_paths: ["<dir>/**"]` |
| "只读 / 绝不改动环境（禁止新建、修改、删除）" | `actions: {"file_ops": {"file": ["read"]}, "shell_exec": {"file": ["read"]}}`（→ 产物 `allowed_file_actions`＝动作层白名单；与 `write_paths: []` 并用＝路径层白名单，双保险） |
| "可以写 xx 目录" | `files.write_paths: ["<dir>/**"]` |
| "不能动系统文件 / 密钥" | `files.deny_paths: ["/etc/**", "/root/**", "~/.ssh/**", "~/.aws/**"]` |
| "只能改代码不能删" | `files.write_paths` 收窄 + 保持基线 denylist（删除类靠 deny-wins 与 judge 兜底） |
| "可以查询文件在哪" | 保留 `file_search` 场景（默认在），必要时收 `bash.workdir_allowlist` |

注意：`read_paths` 会替换**所有** path 类参数的 allowlist（读范围是最宽的安全边界）；
`write_paths` 仅作用于 `file_actions ∩ {create,write,edit,patch,delete}` 的函数。

### 1.2 网络场景

| 用户表达 | spec |
| --- | --- |
| "不能联网 / 断网" | `network.enabled: false` |
| "只能访问某些域名" | `network.allowed_domains: ["api.example.com"]` |
| "禁止访问内网元数据" | `network.deny_hosts: ["169.254.169.254", "metadata.google.internal", "localhost"]` |
| "要能搜索" | 不设 enabled=false；必要时 `scenes.disable` 里不要含 search |

`enabled=false` 的联动（脚本自动完成，无需手配）：移除 `search`/`browser` 场景；
`curl/wget/ping/nslookup/dig/host/traceroute/mtr/nc/socat` 等并入 Bash denylist；
`dynamic_ai_hint` 追加"禁止一切网络访问"。

### 1.3 Bash 场景（shell_exec）

| 用户表达 | spec |
| --- | --- |
| "不让使用 git" | `"no_git": true` |
| "只能跑只读命令" | `bash.allowed_commands: ["ls","cat","head","tail","grep","find","ps","df","free"]`（默认 mode=replace） |
| "可以跑 python" | `bash.allowed_commands` 里保留 `"python"`、`"python3"` |
| "不能 docker" | `bash.denied_commands: ["docker", "docker ps", "docker run", "docker exec"]` |
| "只能在 xx 目录干活" | `bash.workdir_allowlist: ["<dir>/**"]` |
| "运维，要能重启服务" | `base_policy: "ops"`（ops 库保留 systemctl/pm2/nginx 子场景） |

### 1.4 场景开关

| 用户表达 | spec |
| --- | --- |
| "不用邮件/IM/日历" | `scenes.disable: ["email", "im_chat", "calendar"]` |
| "不要浏览器" | `scenes.disable: ["browser"]` |

可禁用场景全集（15 个）：search、browser、email、calendar、im_chat、screen_lock、
shell_exec、terminal_session、process_control、runtime_exec、privilege_ops、media、
file_ops、office_doc、file_search。**shell_exec / file_ops 慎禁**（禁了几乎无法工作）。

## 2. 开箱角色模板

### 2.1 只读数据分析师（assets/spec_example_analyst.json）

```json
{
  "role_name": "analyst",
  "base_policy": "default",
  "title": "只读数据分析师",
  "files": {
    "read_paths": ["/workspace/**", "/data/**"],
    "write_paths": ["/workspace/outputs/**"],
    "deny_paths": ["/etc/**", "/root/**", "~/.ssh/**"]
  },
  "network": { "enabled": true, "allowed_domains": [], "deny_hosts": ["169.254.169.254"] },
  "bash": {
    "mode": "replace",
    "allowed_commands": ["ls", "cat", "head", "tail", "grep", "find", "wc", "stat", "diff", "python", "python3", "ps", "df"],
    "workdir_allowlist": ["/workspace/**", "/data/**"]
  },
  "scenes": { "disable": ["im_chat", "email", "calendar"] }
}
```

### 2.2 禁 git 开发者（assets/spec_example_no_git_dev.json）

```json
{
  "role_name": "dev-nogit",
  "base_policy": "default",
  "title": "禁用 git 的开发角色",
  "no_git": true,
  "bash": {
    "mode": "replace",
    "allowed_commands": ["ls", "cat", "head", "tail", "grep", "find", "wc", "diff", "make", "gcc", "python3", "node", "npm run", "npm test", "pytest", "jest"],
    "denied_commands": ["git", "docker"],
    "workdir_allowlist": ["/workspace/**"]
  }
}
```

### 2.3 网络隔离审阅者

```json
{
  "role_name": "reviewer-airgap",
  "base_policy": "default",
  "title": "断网审阅角色",
  "network": { "enabled": false },
  "files": { "read_paths": ["/workspace/**"], "deny_paths": ["/etc/**", "/root/**", "~/.ssh/**"] },
  "bash": { "mode": "replace", "allowed_commands": ["ls", "cat", "grep", "head", "tail", "wc", "diff"] }
}
```

### 2.4 轻量运维（ops 派生）

```json
{
  "role_name": "ops-lite",
  "base_policy": "ops",
  "title": "轻量运维（无用户管理/无防火墙）",
  "bash": {
    "denied_commands": ["passwd", "useradd", "usermod", "userdel", "iptables", "ufw", "firewall-cmd"],
    "workdir_allowlist": ["/workspace/**", "/etc/systemd/system/**", "/var/log/**"]
  },
  "scenes": { "disable": ["media", "im_chat", "calendar"] }
}
```

## 3. 关键语义（生成前必须理解）

1. **deny-wins**：`denied_commands` 并入 denylist 后，同串项自动移出 `allowed_values`。
   denylist 是**精确匹配**——`"git"` 只拦命令串恰为 `git` 的调用；拦"git 命令族"要枚举
   `git push/git commit/...`（`no_git` 已内置 14 项枚举），变体最终由判定层语义解析兜底。
2. **mode=replace 的拍平**：ops 基线的 `exec.command.static` 是 8 元素数组，替换前会按
   《shell_exec_策略调整说明.md》并集语义合并为单对象（消费端本就不区分子场景，语义等价）。
   想保留 ops 子场景结构只用交集收缩时选 `mode: "intersect"`。
3. **`cmd_executor__exec_command` 跟随 exec 的 denied/allowed**（同轮适配，保持两函数口径一致）。
4. **`no_git` 是惯例打包**：等价于 `functions_remove: [mcpguard_gitkit__*]` + git 命令族 deny + hint。
   用户只说"不让用 git"时优先用它，不要手散配。
5. **场景禁用 = 彻底关闭**：`scenes.disable` 会同时移除 scenes.json 键**并删除**对应
   `tools/<scene>.json`（避免孤儿工具文件触发校验 E4）；`functions_remove` 只做
   scenes.json 列表 + tools 定义**双清**（文件保留、场景保留）。

## 4. 信息不足时的最小权限缺省（直接采用并声明，不阻塞）

| 缺失信息 | 缺省假设 |
| --- | --- |
| base_policy | default |
| 角色（目录）名 | 由执行者按语义起英文短名（如 analyst / dev-nogit），向用户确认拼写 |
| 读范围 | `/workspace/**` + `/tmp/**`（基线口径） |
| 写范围 | `/workspace/outputs/**`（基线口径） |
| Bash 集合 | 基线 allowed_values 原样（mode 缺省不替换，只应用 denied） |
| 网络 | 不动（保持基线：http(s) allowlist + 元数据 denylist） |

## 5. 校验错误修复手册（validate_policy.py）

| 错误 | 原因 | 修复 |
| --- | --- | --- |
| E1 scenes.json 空/缺失 | 场景全被禁或复制失败 | 检查 `scenes.disable` 是否误禁全部场景 |
| E3 tools JSON 损坏 | 手工编辑引入语法错 | `python3 -m json.tool <file>` 定位 |
| E4 孤儿工具文件 | tools 文件的 scene 不在 scenes.json | 对应场景被 disable 时正常（文件保留）；要彻底删用 functions_remove |
| E6 allowed∩deny 冲突 | 手工加 deny 未同步移出 allowed | 重新走脚本生成（deny-wins 自动处理），勿手改产物 |
| E5(w) 函数缺口 | 基线历史遗留（default 的 file_ops 有 7 项） | 不判失败；向用户如实说明即可 |
| W1 advice 文档缺失 | warn_advice.md 未随基线复制 | 检查基线 tools/ 是否含 warn_advice.md |
| W2 default 缺失 | replace 后某 static 无 default | spec 里给 allowed_commands 非空列表，或复跑生成器 |

## 6. 交付前自检清单

- [ ] 角色目录含 README.md + policy_registry/{scenes.json, tools/}
- [ ] 基线 default/ops 无任何改动（`git status` 确认）
- [ ] 校验通过（0 errors；warnings 已向用户说明）
- [ ] 已给出切换命令/前端路径，且**未经用户确认未执行切换**
- [ ] 抽样 query 建议（2–3 条覆盖三类场景）已写入交付说明
