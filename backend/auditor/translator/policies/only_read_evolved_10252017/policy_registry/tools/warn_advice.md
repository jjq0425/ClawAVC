# 最小权限操作指导（warn 类命令风险与替代方案）

> **适用角色**：shell_exec（命令执行类任务：exec / cmd_executor__* 等全部函数）
> **引用方式**：由策略库根目录的全局注册表 `advice_docs.json` 按路径声明（`{role, path, inject}`），系统在注入 Level-2 提示词时自动加载本文内容；
> 相对路径相对 `policy_registry/tools/` 目录解析，绝对路径原样生效。
> **维护说明**：本文是 warn 类建议的唯一事实来源（Single Source of Truth），多处配置共享引用，修改即全局生效。
> **分区规则**：正文按风险类别分节，每节以 `<!-- applies: <场景名> -->` 标注适用场景——
> 翻译模型注入提示词时**仅加载与当前场景匹配的分节**（未标注者为全局通用分节，始终加载）；
> 同步至 AGENTS.md 时**全量同步**整份文档。

## 使用规则（AI 必须遵守）

1. 拟生成的命令命中本文任一 `pattern` 时，**必须先向用户说明对应 `risk`**；
2. 优先采用 `alternative` 平替方案执行，不得直接执行原命令；
3. 平替方案无法满足任务需求时，须获得用户明确确认后才可执行原命令；
4. `denylist`（硬拒绝）不在本文讨论范围——被拒命令禁止生成，无平替通道。

---

## 文件删除

<!-- applies: shell_exec -->

- **pattern**：`rm`
- **risk**：不可恢复删除，误删工作区或系统文件无法回滚。
- **alternative（最小权限建议）**：先 `mv <目标> /tmp/trash_<时间戳>/` 移入回收目录，任务确认无误后再统一清理。

## 权限

<!-- applies: shell_exec -->

- **pattern**：`chmod / chown`
- **risk**：权限误配可能导致服务异常或被提权利用。
- **alternative**：仅对明确列出的单个文件做最小化授权；禁止 `-R` 递归与 `777`；先 `ls -l` 确认现状再修改。

## 进程控制

<!-- applies: shell_exec -->

- **pattern**：`kill / killall / pkill`
- **risk**：按名称匹配易误杀无关进程。
- **alternative**：先 `ps aux | grep <名称>` 或 `pgrep -f <名称>` 精确定位 PID，再 `kill <单个pid>`；禁止 kill init/systemd。

## 系统服务

<!-- applies: shell_exec -->

- **pattern**：`systemctl restart / stop / start`
- **risk**：直接影响在线服务可用性。
- **alternative**：先 `systemctl status` 确认影响面；配置变更先做 `nginx -t` 等校验，再请求用户确认执行。

## 网络请求

<!-- applies: shell_exec -->

- **pattern**：`curl / wget`
- **risk**：外联不可信地址或下载即执行（RCE）。
- **alternative**：仅做只读 GET 查询；需要获取文件时先下载到 `/tmp` 并检查内容，禁止任何 `管道 | sh` 直接执行。

## 安装依赖

<!-- applies: shell_exec -->

- **pattern**：`apt / yum / npm / pip install`
- **risk**：引入不可信或未锁版本的依赖。
- **alternative**：优先按项目内已锁定的依赖清单安装固定版本；避免全局安装、避免卸载系统包。

## Git 操作

<!-- applies: shell_exec -->

- **pattern**：`git reset --hard / git clean -f / git push --force`
- **risk**：不可逆丢失本地改动或覆盖远程历史。
- **alternative**：先 `git stash` 或新建备份分支保存现场；撤销提交优先用 `git revert`。

## 文件写入

<!-- applies: shell_exec -->

- **pattern**：`tee / echo > /etc/*` 等系统配置写入
- **risk**：直接覆盖系统配置可能导致系统异常。
- **alternative**：先写入 `/workspace` 下的副本，经用户确认后再手动同步到目标位置。

## 文件读取

<!-- applies: shell_exec -->

- **pattern**：`cat /etc/*` 等敏感路径
- **risk**：读取密钥、token、SSH 配置等系统敏感文件。
- **alternative**：仅读取任务明确需要的项目文件与 `/etc/os-release`、`/proc/version` 等环境信息文件。

## 脚本执行

<!-- applies: shell_exec -->

- **pattern**：来源不明 / 网络下载的脚本
- **risk**：脚本内容不可信，可能包含破坏性或外泄逻辑。
- **alternative**：先 `cat` 输出脚本内容供用户确认，再执行；网络下载的脚本禁止直接执行。
