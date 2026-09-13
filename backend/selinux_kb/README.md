# SELinux 知识库（小异的 SELinux 依据库）

把 `refpolicy/`、`selinux-notebook/`、`selinux.wiki/` 三份语料解析成一个 SQLite 索引，
供「小异」在给出 SELinux 策略建议前检索核对，避免凭记忆编造类型名、布尔名和规则。

## 组成

| 文件 | 作用 |
|---|---|
| `parsers.py` | 语料解析：`.te/.if/.fc/.spt`、flask 类定义、Markdown、man 页 |
| `build_index.py` | 索引构建 CLI（含环境自检与抽样验证） |
| `search.py` | 检索 API：`search(query, kind, module, k, db_path) -> str` |
| `../../infos/selinux_kb/selinux_kb.db` | 构建产物（单文件，已被 `.gitignore` 的 `*.db` 忽略） |

依赖：**仅 Python 标准库**，无第三方包。要求 Python ≥ 3.8；
SQLite 带 FTS5 时用 BM25 排序，不带时自动降级为 `LIKE` 逐词检索。

## 在本地构建

```bash
cd backend/selinux_kb

# 1) 环境自检（Python / SQLite / FTS5 / 语料是否找得到）
python3 build_index.py --check --corpus /path/to/SELinux

# 2) 构建索引
python3 build_index.py --corpus /path/to/SELinux --out ../../infos/selinux_kb/selinux_kb.db

# 3) 构建完顺带跑抽样检索
python3 build_index.py --corpus /path/to/SELinux --out ../../infos/selinux_kb/selinux_kb.db --sample
```

`--corpus` 指向同时包含 `refpolicy/`、`selinux-notebook/`、`selinux.wiki/` 的目录；
缺失的子目录会被跳过（只放 `refpolicy/` 也能构建）。
也可用环境变量 `SELINUX_CORPUS` / `SELINUX_KB_PATH` 代替命令行参数。

## 部署到目标 Linux 服务器

两种方式任选：

```bash
# 方式 A：只拷贝构建产物（推荐，无需搬运语料）
scp infos/selinux_kb/selinux_kb.db  user@server:/path/to/clawAVC/infos/selinux_kb/

# 方式 B：把语料一起带过去，在目标机构建（约 1 秒，内存占用 < 200MB）
scp -r refpolicy selinux-notebook selinux.wiki user@server:/path/to/corpus/
ssh user@server 'cd /path/to/clawAVC/backend/selinux_kb && \
  python3 build_index.py --corpus /path/to/corpus --out ../../infos/selinux_kb/selinux_kb.db'
```

目标机器上验证：

```bash
python3 build_index.py --check
python3 build_index.py --selftest --out ../../infos/selinux_kb/selinux_kb.db
```

索引路径可用环境变量覆盖：`export SELINUX_KB_PATH=/data/selinux_kb.db`。

## 检索用法

```python
from selinux_kb import search

search("httpd_t var_log_t write", kind="rule", k=5)      # 查 allow 规则
search("apache_read_user_content", kind="interface")      # 查接口语义
search("/etc/httpd", kind="file_context")                 # 查路径上下文
search("httpd_can_network_connect", kind="symbol")        # 查布尔值
search("AVC denied 排查", kind="doc")                      # 查文档
```

`kind` 取值：`all`（默认）/ `rule` / `symbol` / `interface` / `file_context` / `doc` / `macro`。
`module` 可限定策略模块（如 `apache`）缩小范围。

返回的是给大模型直接阅读的紧凑文本，每条都带 `文件:行号` 出处；
当查询的源/目标类型之间不存在直接 `allow` 规则时会显式提示，
避免模型把「没查到」误说成「一定不允许」。

## 实测数据（本机 macOS / Python 3.13 / SQLite 3.50）

| 指标 | 数值 |
|---|---|
| 语料规模 | refpolicy 438 个模块 + Notebook 71 章 + wiki 7 页 |
| 索引内容 | 10857 chunks / 16685 symbols / 9618 rules / 2403 file_contexts |
| 索引文件 | 16.2 MB（单文件，DELETE journal，已 VACUUM） |
| 构建耗时 | ≈ 1 秒 |
| 单次检索 | 平均 3 ms，进程峰值 RSS 22 MB |

在 2GB 内存的服务器上，检索侧常驻开销可忽略（SQLite 页缓存上限 16MB，
每次调用新建只读连接并在结束时关闭）。

## 与「小异」的接入点

`backend/xy_skill.py` 中的 `search_selinux_knowledge` 工具：

- 工具定义在 `TOOLS`，处理函数 `_handler_selinux_knowledge`，注册在 `TOOL_HANDLERS`
- 该工具属于 `ARG_TOOLS`：入参在流式响应中分片到达，因此推迟到本轮
  `final` 事件（参数接收完整）后才执行；其余 12 个只依赖 `round_id`
  的工具保持原有的「拿到函数名即执行」行为
- 索引缺失或模块导入失败时返回提示文本，不会让技能分析中断

## 已知限制

- 语料是 upstream refpolicy，与发行版实际策略的类型命名可能存在差异；
  建议后续把目标机器的真实策略（`sesearch -A`、`semanage fcontext -l`、
  `getsebool -a`）也导入为独立来源，答案中注明依据来源。
- 模板体内的规则用 `$1` 等占位符表示（如 `allow httpd_t httpd_$1_content_t:file map`），
  这是策略源码的原始写法，不是解析错误。
- `rule` 表记录的是源码中显式写出的规则；通过接口宏间接授予的权限不在其中，
  检索结果会附带提示说明这一点。
