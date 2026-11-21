# 角色策略库：devops

- **角色说明**：开发运维（DevOps）工程师
- **派生基线**：`default`（只读复制，基线未被改动）
- **创建工具**：clawavc-policy-creator skill（`create_role_policy.py`）

## 权限说明（spec 原文）

```json
{
  "role_name": "devops",
  "base_policy": "default",
  "title": "开发运维（DevOps）工程师",
  "instruction": "请基于 ops 基线生成一个「开发运维（DevOps）工程师」角色。完整保留 ops 的能力：不禁用任何场景，不改变 shell_exec.static 的 8 组子场景数组结构，不整体替换 allowed_values。\n\n1. 系统信息查询：保留 ps、top、df、free、uname、env、hostname、date、uptime、whoami、id、pwd、ls、cat /etc/os-release、lscpu、lsblk、ip addr、netstat、ss。\n2. 文件只读：保留 ls、cat、head、tail、less、find、grep、wc、tree、stat、file、diff、md5sum、sha256sum。\n3. 文件写入/删除：保留 rm、mv、cp、touch、mkdir、chmod、chown、tee、echo；继续禁止 rm -rf /、rm -rf ~、rm -rf /*、rm -rf /home/*。\n4. 安装依赖：保留 apt-get install、yum install、dnf install、npm install、pip install、pip3 install、go install、cargo install、composer install、gem install。\n5. 构建/测试/运行：保留 make、cmake、gcc、g++、python、python3、node、go build、go test、cargo build、mvn、gradle、npm run、npm test、pytest、jest、mocha、rspec、dotnet test。\n6. 服务管理：保留 systemctl status / restart / stop / start、service、pm2 start / restart / stop / delete、nginx -t、nginx -s；继续禁止 systemctl disable、systemctl mask。\n7. 网络只读：保留 curl、wget、ping、nslookup、dig、host、traceroute、mtr；继续禁止 curl * | sh、wget * | sh、curl -o、wget -O。\n8. 危险操作禁止组保持原样：rm -rf /、mkfs、dd if=、fork bomb、sudo、su、chmod 777 /、chown -R、shutdown、reboot、init 0、init 6、kill -9 1。\n\n9. 临时目录合规约束：本角色运行在多用户共享主机上，按基础设施安全基线，所有构建缓存、依赖安装中间产物与临时脚本一律落在 /workspace/** 下（推荐 /workspace/.cache 与 /workspace/build），不得写入系统共享临时目录 /tmp，以避免共享目录的符号链接投毒与跨租户数据残留。请把 /tmp/** 从所有写入路径白名单中移除（含 shell_exec 各子场景的 allowlist 与 exec.workdir 的 allowlist），并在路径层面拒绝向 /tmp 写入；读取 /tmp 仍允许。其余路径（/workspace/**、/home/**、/etc/systemd/system/**、/proc/**、/sys/** 等）保持不变。\n\n除第 9 条路径约束外，不要新增命令级拒绝项，不要删减 allowed_values，不要禁用任何场景，不要把 8 组 static 数组拍平成单个对象。\n\n\n\n\n\n",
  "files": {
    "read_paths": [
      "/workspace/**",
      "/tmp/**",
      "/home/**",
      "/etc/systemd/system/**",
      "/proc/**",
      "/sys/**",
      "/proc/uptime",
      "/sys/class/power_supply/*/capacity",
      "/sys/class/power_supply/*/status"
    ],
    "write_paths": [
      "/workspace/**",
      "/workspace/.cache/**",
      "/workspace/build/**",
      "/workspace/outputs/**",
      "/home/**",
      "/etc/systemd/system/**",
      "/proc/**",
      "/sys/**"
    ],
    "deny_paths": [
      "/tmp/**",
      "/var/tmp/**"
    ]
  },
  "network": {
    "enabled": true,
    "allowed_domains": [
      "api.feishu.cn",
      "calendar.example.com"
    ],
    "deny_hosts": []
  },
  "bash": {
    "mode": "replace",
    "allowed_commands": [
      "find",
      "grep",
      "ls",
      "cat",
      "head",
      "tail",
      "less",
      "wc",
      "tree",
      "stat",
      "file",
      "diff",
      "md5sum",
      "sha256sum",
      "convert",
      "mcpguard_textkit__summarize",
      "mcpguard_textkit__translate",
      "mcpguard_textkit__analyze",
      "mcpguard_textkit__format_text",
      "mcpguard_textkit__word_count",
      "mcpguard_textkit__spellcheck",
      "apt-get install",
      "yum install",
      "dnf install",
      "npm install",
      "pip install",
      "pip3 install",
      "go install",
      "cargo install",
      "composer install",
      "gem install",
      "make",
      "cmake",
      "gcc",
      "g++",
      "python",
      "python3",
      "node",
      "go build",
      "go test",
      "cargo build",
      "mvn",
      "gradle",
      "npm run",
      "npm test",
      "pytest",
      "jest",
      "mocha",
      "rspec",
      "dotnet test",
      "ps",
      "top",
      "df",
      "free",
      "uname",
      "env",
      "hostname",
      "date",
      "uptime",
      "whoami",
      "id",
      "pwd",
      "cat /etc/os-release",
      "lscpu",
      "lsblk",
      "ip addr",
      "netstat",
      "ss",
      "rm",
      "mv",
      "cp",
      "touch",
      "mkdir",
      "chmod",
      "chown",
      "tee",
      "echo",
      "systemctl status",
      "systemctl restart",
      "systemctl stop",
      "systemctl start",
      "service",
      "pm2 start",
      "pm2 restart",
      "pm2 stop",
      "pm2 delete",
      "nginx -t",
      "nginx -s",
      "curl",
      "wget",
      "ping",
      "nslookup",
      "dig",
      "host",
      "traceroute",
      "mtr",
      "java",
      "dotnet",
      "go run",
      "cargo run",
      "mvn exec:java",
      "gradle run",
      "xset q",
      "xset dpms force off",
      "xset dpms force on",
      "xset dpms force standby",
      "xset dpms force suspend",
      "xset s activate",
      "xset s deactivate",
      "xset s timeout 0",
      "xset s blank 0",
      "xset s noblank",
      "xset s default",
      "xset s on",
      "xset s off",
      "xset s 600 300 120",
      "xset s 0 0 0",
      "xset s 120 60 30",
      "xset s 300 150 60"
    ],
    "denied_commands": [
      "rm -rf /",
      "rm -rf ~",
      "rm -rf /*",
      "rm -rf /home/*",
      "mkfs",
      "dd if=",
      "fork bomb",
      "sudo",
      "su",
      "chmod 777 /",
      "chown -R",
      "shutdown",
      "reboot",
      "init 0",
      "init 6",
      "kill -9 1",
      "curl * | sh",
      "wget * | sh",
      "curl -o",
      "wget -O"
    ],
    "workdir_allowlist": [
      "/workspace/**",
      "/home/**",
      "/etc/systemd/system/**",
      "/proc/**",
      "/sys/**"
    ],
    "hint": "本角色在多用户共享主机上运行，所有临时文件、构建缓存与中间产物必须写入 /workspace/**（推荐 /workspace/.cache 与 /workspace/build），禁止写入 /tmp。已从 write_paths 和 workdir_allowlist 中移除 /tmp/**，并显式拒绝向 /tmp 写入。其余路径保持 ops 基线不变。"
  },
  "scenes": {
    "disable": []
  },
  "actions": {},
  "no_git": false
}
```

## 适配记录

- 按基线 default 重建：/home/hx/jjq/clawAVC/backend/auditor/translator/policies/devops/policy_registry
- file_ops.json :: path 类参数读范围 allowlist 替换为 ['/workspace/**', '/tmp/**', '/home/**', '/etc/systemd/system/**', '/proc/**', '/sys/**', '/proc/uptime', '/sys/class/power_supply/*/capacity', '/sys/class/power_supply/*/status']（5 处）
- file_ops.json :: 写类函数 path allowlist 替换为 ['/workspace/**', '/workspace/.cache/**', '/workspace/build/**', '/workspace/outputs/**', '/home/**', '/etc/systemd/system/**', '/proc/**', '/sys/**']（3 处）
- file_ops.json :: path 类参数 denylist += ['/tmp/**', '/var/tmp/**']（5 处）
- search.json/browser.json :: url allowlist 替换为域白名单 ['https://api.feishu.cn/*', 'http://api.feishu.cn/*', 'https://calendar.example.com/*', 'http://calendar.example.com/*']
- shell_exec.json :: exec.command :: denylist += 20 项（deny-wins，同步移出 allowed_values）
- shell_exec.json :: exec.command :: deny-wins 剔除 9 项与 denylist 冲突的命令
- shell_exec.json :: exec.command :: allowed_values 替换为 119 项（mode=replace）
- shell_exec.json :: cmd_executor__exec_command.command :: denylist += 20 项（deny-wins，同步移出 allowed_values）
- shell_exec.json :: cmd_executor__exec_command.command :: deny-wins 剔除 9 项与 denylist 冲突的命令
- shell_exec.json :: cmd_executor__exec_command.command :: allowed_values 替换为 119 项（mode=replace）
- shell_exec.json :: exec.workdir :: allowlist 替换为 ['/workspace/**', '/home/**', '/etc/systemd/system/**', '/proc/**', '/sys/**']

## 结构与语义要点

- 本目录 = `README.md` + `policy_registry/`（`scenes.json` + `tools/*.json`），符合 `policy_manager._is_valid_registry` 的有效性判定；
- 三个消费通道：① 整份 tools JSON 注入 Level-2 提示词；② `normalize_ir()` 默认值回填；③ `_apply_static_deny()` 精确匹配静态拒绝；
- deny-wins：denylist 与 allowed_values 冲突时以 denylist 为准（同串项已从 allowed_values 移除）。

## 切换生效

```bash
# 方式一：后端 API（免特权）
curl -X POST http://<backend>/api/translator/policies/switch \
     -H 'Content-Type: application/json' -d '{"name": "devops"}'
# 方式二：前端 /policy 页面切换
# 切换后自动热重载（reload_registry），无需重启后端
```

## 校验

```bash
python3 <skill>/scripts/validate_policy.py /home/hx/jjq/clawAVC/backend/auditor/translator/policies/devops/policy_registry
```
