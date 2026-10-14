# openclaw_agent —— OpenClaw 进程/工具的 SELinux 域与标签策略

## 1. 目标

| 目标 | 实现 |
| --- | --- |
| openclaw 相关进程/二进制统一为 `agent_t` 域 | `openclaw_agent.te`（域声明 + 域切换规则 + systemd `SELinuxContext=system_u:system_r:agent_t:s0`） |
| `/home/hx/jjq/agent_perm_audit/tools` 下全部 MCP 工具 + openclaw 自带基础工具统一为 `agent_tool_t` | `openclaw_agent.fc` + `semanage fcontext`（`file_contexts.local`） |
| 文件访问与工具调用完整留痕 | permissive + `auditallow`（即使允许也记 granted）+ auditd 规则（`/etc/audit/rules.d/openclaw_agent.rules`） |
| 权限与系统默认一致（高权限，不阻断业务） | `unconfined_domain(agent_t)` + 对 `file_type`/`exec_type`/`domain` 的等价授权 |
| 保持日志模式 | `permissive agent_t;`（模块内声明）+ `semanage permissive -a agent_t` |

## 2. 文件清单

```
selinux/
├── openclaw_agent.te       类型强制规则（域、类型、切换、审计、permissive）
├── openclaw_agent.fc       文件上下文（agent_exec_t / agent_tool_t / agent_conf_t / agent_log_t）
├── openclaw_agent.if       对外接口（domtrans / exec_tools / manage_conf）
├── openclaw_agent.pp       编译产物
├── Makefile                构建（基于 /usr/share/selinux/devel）
├── install.sh              一键安装：编译→载入→permissive→打标签→审计规则→systemd 上下文→验证
├── verify.sh               验证：模式/模块/标签/审计捕获/域切换
├── run_as_agent.sh         以 agent_t 运行 shebang 脚本（runcon 包装）
├── audit/openclaw_agent.rules   auditd 规则（工具目录 watch + execve 规则）
└── systemd/openclaw-agent-context.conf   systemd drop-in（SELinuxContext=agent_t）
```

## 3. 标签映射

| 路径 | 类型 | 说明 |
| --- | --- | --- |
| `/usr/bin/openclaw`、`/usr/lib/node_modules/openclaw/**`、`/usr/local/bin/openclaw-tool-e2e`、`/usr/local/libexec/openclaw-round-id-listener.py`、`run-openclaw-tracee-collector-service`、`openclaw-selinux/*` | `agent_exec_t` | 执行即进入 `agent_t` |
| `/home/hx/jjq/agent_perm_audit/tools/**` | `agent_tool_t` | MCP 工具（22 个 server.py 等） |
| `/root/.openclaw/skills/**` | `agent_tool_t` | openclaw 自带基础工具/技能载体 |
| `/root/.openclaw`、`exec-approvals.json` | `agent_conf_t` | 配置 |
| `/var/lib/openclaw-kernel-collector/**` | `agent_log_t` | 采集产物 |

## 4. 安装与验证

```bash
cd /home/hx/jjq/clawAVC/selinux
bash install.sh     # 编译→载入→permissive→打标签→审计规则→systemd 上下文
bash verify.sh      # 17+ 项检查
```

常用核查：

```bash
getenforce                                   # 必须 Permissive
semodule -l | grep openclaw_agent
semanage permissive -l | grep agent_t
ls -Z /home/hx/jjq/agent_perm_audit/tools    # agent_tool_t
ausearch -m AVC -ts recent | grep agent_t    # AVC 审计
ausearch -k agent_tool_access -ts recent     # auditd 工具访问
```

## 5. 重要限制与说明

1. **域切换已实测可用（含 shebang 脚本）**：早期版本因缺少 `role unconfined_r types agent_t;` 导致从管理员会话启动无法切域；补齐后实测直接执行 `/usr/bin/openclaw --help`
   （`#!/usr/bin/env node` 脚本）进程即为 `unconfined_u:unconfined_r:agent_t`，并产生 22 条自身访问的 AVC 记录（见 `verify.sh` 第⑥项与 README 第 7 节）。
   仍需注意：只有**标签为 `agent_exec_t` 的入口**才会切域；systemd 服务与 `./run_as_agent.sh` 作为显式兜底手段保留。
2. **`/home` 下路径需登记 `file_contexts.local`**：`file_contexts.homedirs` 的 `/home/[^/]+/.+`（user_home_t）会覆盖模块内规则，`install.sh` 中已用 `semanage fcontext` 登记并用 `setfiles` 落标签。
3. **已有进程需重启**才进入 `agent_t`；当前仍在运行的 openclaw 进程保持原域（unconfined_service_t / unconfined_t）。
4. **日志量**：permissive 下所有未显式允许的访问均产生 AVC 记录（完整捕捉），审计日志增长较快，建议配合 logrotate 或按 key 过滤。
5. **高权限模式（当前配置）**：`agent_t` 通过 `unconfined_domain(agent_t)` 与对 `file_type`/`exec_type`/`domain` 的显式授权，
   获得与系统默认（unconfined）等同的权限——实测读 `/etc/shadow`、列 `/root`、写 `/var/log`、启动 MCP 工具均与未受限时一致，新增 denied 为 0。
   因此**留痕不再依赖「拒绝」**，而由 `auditallow`（granted 记录）+ auditd 规则 + permissive 三者保证。
6. **禁止直接切 enforcing**：当前为审计/兼容场景的高权限配置，切到 enforcing 前必须收敛为最小权限（按 AVC 反推 allow 集），否则等同关闭 SELinux 保护。

## 7. 真实 openclaw 执行的审计证据（实测）

命令（普通 shell，未强制上下文）：

```bash
sh -c 'echo $$ > /tmp/p_nat; exec /usr/bin/openclaw --help'   # pid=3689046
```

进程域：`unconfined_u:unconfined_r:agent_t:s0-s0:c0.c1023`（自然切换，非 runcon 强制）

```
type=EXECVE msg=audit(...): argc=4 a0="/usr/bin/env" a1="node" a2="/usr/bin/openclaw" a3="--help"
type=AVC ... : avc: granted { write }   for pid=3689046 comm=openclaw name=openclaw
              scontext=unconfined_u:unconfined_r:agent_t  tcontext=...user_tmp_t  tclass=dir
type=AVC ... : avc: granted { setattr } for pid=3689046 comm=openclaw name=openclaw.sqlite
              scontext=...agent_t  tcontext=...admin_home_t  tclass=file
type=AVC ... : avc: granted { setattr } for pid=3689046 comm=openclaw name=openclaw.sqlite-shm
type=AVC ... : avc: granted { setattr } for pid=3689046 comm=openclaw name=openclaw.sqlite-wal
type=AVC ... : avc: granted { write }   for pid=3689046 comm=openclaw path=/root/.openclaw/state/openclaw.sqlite
```

该次 `--help` 共产生 50 条 AVC（其中 22 条为 openclaw 自身访问：状态库读写、临时目录写入；
其余为继承的标准输出 fd 写入 IDE 日志，属真实但非业务访问）。

一键复现：

```bash
ausearch -m AVC -p <openclaw_pid> -i | grep -v codebuddy
```

## 8. 真实「让 openclaw 写文件」的审计证据（实测）

命令（普通 shell，未强制上下文）：

```bash
mkdir -p /tmp/agent_t_backup
sh -c 'echo $$ > /tmp/p_bk; exec /usr/bin/openclaw backup create --only-config \
       --output /tmp/agent_t_backup --json --verify'
```

结果：openclaw 真的写出了文件

```
/tmp/agent_t_backup/2026-10-12T22-56-17.212+08-00-openclaw-backup.tar.gz   3269 字节  verified=true
进程链：pid 3689844 (comm=openclaw) → 子进程 pid 3689852 (comm=openclaw-backup / libuv-worker)
两者 scontext 均为 unconfined_u:unconfined_r:agent_t:s0-s0:c0.c1023
```

对应的 AVC（`ausearch -m AVC -p 3689852 -i`）：

```
avc: granted { create }   comm=libuv-worker name=2026-10-12T22-56-17...tar.gz.<uuid>.tmp  scontext=...agent_t  tcontext=...user_tmp_t
avc: granted { write }    comm=libuv-worker path=/tmp/agent_t_backup/2026-10-12T22-56-17...tar.gz.<uuid>.tmp   scontext=...agent_t
avc: granted { add_name } comm=libuv-worker name=2026-10-12T22-56-17...tar.gz.<uuid>.tmp  scontext=...agent_t
avc: granted { link }     comm=libuv-worker name=2026-10-12T22-56-17...tar.gz.<uuid>.tmp  scontext=...agent_t
avc: granted { write }    comm=libuv-worker name=agent_t_backup  scontext=...agent_t  tcontext=...user_tmp_t  tclass=dir
avc: granted { setattr }  comm=openclaw-backup name=openclaw.sqlite / -shm / -wal      scontext=...agent_t
avc: granted { write }    comm=openclaw-backup path=/root/.openclaw/state/openclaw.sqlite  scontext=...agent_t
```

统计：主进程 12 条 + 子进程 59 条 = 71 条 AVC，59/59 全部为 `agent_t`。

**覆盖边界（重要）**：当前 `auditallow` 只覆盖写类操作（write/append/create/link/unlink/rename/setattr）
与 `agent_tool_t` 的读/执行；高权限模式下**普通文件的读操作不再产生 AVC**（不再被 deny，也未纳入 auditallow）。
如需读也留痕，可在 `openclaw_agent.te` 中把 `auditallow agent_t file_type:file { ... }` 补上 `read open getattr`
（会显著增加日志量）。

## 9. `agent_tool_t` 客体是否真的出现（实测）

结论：**会出现**，前提有两个——① 主体进程在 `agent_t` 域；② 该进程真的去读/执行 `tools/` 下的工具文件。

真实 MCP 工具调用（`safe_file_reader`，走完整 JSON-RPC initialize 握手）：

```bash
printf '%s\n%s\n' \
 '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{...}}' \
 '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
 | ./run_as_agent.sh sh -c 'echo $$ >/tmp/p_tool; exec python3 \
     /home/hx/jjq/agent_perm_audit/tools/safe_file_reader/server.py'
# 工具真实响应：{"jsonrpc":"2.0","id":1,"result":{...,"serverInfo":{"name":"safe_file_reader",...}}}
# pid=3691487
```

```
type=AVC ... : avc: granted { search }   comm=python3 name=safe_file_reader
               scontext=system_u:system_r:agent_t:s0  tcontext=system_u:object_r:agent_tool_t:s0  tclass=dir
type=AVC ... : avc: granted { getattr }  comm=python3 path=/home/hx/.../tools/safe_file_reader/server.py
               scontext=...agent_t  tcontext=...agent_tool_t  tclass=file
type=AVC ... : avc: granted { read open } comm=python3 path=/home/hx/.../tools/safe_file_reader/server.py
               scontext=...agent_t  tcontext=...agent_tool_t  tclass=file
```

统计：该进程 120 条 `tcontext=agent_tool_t`，120/120 主体均为 `agent_t`。

**为什么 openclaw CLI 自身跑不出 agent_tool_t**：`openclaw --help` / `backup create` 不加载 MCP 工具；
MCP 工具由**网关进程**加载执行，而网关（pid 443026）当前仍是 `unconfined_t`，主体不是 `agent_t`，因此不会产生
`agent_t → agent_tool_t` 记录。要让真实链路产出该记录，需把网关以 `agent_t` 运行（systemd drop-in 或 `run_as_agent.sh`）。
