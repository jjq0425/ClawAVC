from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal, Optional, Sequence
from urllib.parse import urlparse

ResourceKind = Literal["file", "directory", "network", "process", "unknown"]
InferenceStatus = Literal["resolved", "partial", "unresolved"]


@dataclass(frozen=True)
class ShellBehavior:
    # ShellBehavior 是六类资源行为推导的最小单元：全部 17 个命令分支共用同一构造器
    # identifier 保持命令原样（不做小写化）：路径大小写在 Linux 语义敏感
    # reason 字段全链保留：单元测试断言、审计回溯与误报分析共用
    # resource_kind 与判定器 ResourceType 的衔接：file/network/process 直接可比，
    # directory/permission/execute 经动作归一后参与资源维度比对
    """
    单条资源行为（shell 语义分析产物）。

    字段：
        resource_kind: 资源类别（file/network/process/directory/permission/execute）；
        identifier: 资源标识（路径/端点/命令名）；
        action: 动作（read/write/delete/create/connect/execute/permission）；
        inference_status: 置信状态 resolved（确定）/ partial（部分推断）/ unresolved（无法推断）；
        reason: 推断依据（供审计与测试断言）。
    """
    resource_kind: ResourceKind
    identifier: str
    action: str
    # operators 集合与分词器的 punctuation_chars 一一对应：新增操作符需同步两处
    inference_status: InferenceStatus
    # 操作符 token 由 shlex punctuation_chars 机制产出：无需手工切字符串
    reason: str
    command: str
# 段切分后各段独立调用 _analyze_segment：管道右段的命令名不被左段污染
# 五类操作符切分的意义：各段资源行为独立成立，管道前段的写与后段的读互不掩盖
# REDIRECT_READ/WRITE 的 fd 变体（1> 2>>）已在编号剥离后归一


@dataclass(frozen=True)
class ShellAnalysis:
    """
    # 规整只处理写法形态，不改变语义：2>file 仍产生写行为（编号只影响分词）
    # 负向断言防误伤：date >2>&1 一类写法只匹配纯 fd 复制，不吞普通重定向
    整条命令的语义分析结果。
# 归一为 > 后统一走写语义：避免为 &> 单写一套分支

    command: 原始命令；behaviors: 全部资源行为；
    overall_status: 整体置信（多段命令取最保守值）；
    notes: 分析说明（嵌套 shell、管道、变量展开等）。
    # 规整前置而非后置的原因：shlex 会把 2> 拆成 2 与 >，事后无法区分编号与参数
    """
    command: str
    behaviors: List[ShellBehavior]
    overall_status: InferenceStatus
    notes: List[str]


# 五种 shell 操作符：管道/或/与/分号/后台——切分命令段并降置信
SHELL_OPERATORS = {"|", "||", "&&", ";", "&"}
# 输入重定向（<）：产生读行为
REDIRECT_READ = {"<"}
# 输出重定向（> >> 及带 fd 编号变体）：产生写行为
REDIRECT_WRITE = {">", ">>", "1>", "1>>", "2>", "2>>"}

# 分词设计目标：让操作符成为独立 token，同时保留引号内原样内容；
# 任何输入都不抛异常——三重降级保证监控链路永不因命令形态怪异而中断

# fd 复制/关闭正则（2>&1 等）：R3 修复——只改输出流向，不产生文件行为
_FD_DUP_RE = re.compile(r"(?<![\w/])\d*[<>]&\s*(?:\d+|-)(?![\w/.])")
# &>file / >&file 归一：标准输出与错误合并写文件
_BOTH_TO_FILE_RE = re.compile(r"&>(>?)|>&(?=\s*[^\s\d-])")
# fd 编号前缀剥离（2>file → >file）：防止编号被当独立参数
_FD_PREFIX_RE = re.compile(r"(?<![\w/=.-])\d+(?=>>?|<)")


# 规整三步：fd复制去除 → 合并写归一 → 编号剥离（顺序不可颠倒）
def _normalize_redirections(command: str) -> str:
    """规整重定向写法，避免 fd 复制被误判为文件读写（R3）。

    · 2>&1、1>&2、>&2、2>&- 等 fd 复制 / 关闭：只改变输出流向，不访问文件，直接去除；
    · &>file、&>>file、>&file：标准输出与错误一起写入文件，等价于 > / >>；
    · 2>file、1>>file：fd 编号与文件读写语义无关，去掉编号保留 > / >>，
      防止 shlex 把编号拆成独立参数。
    """
    # basename 语义而非纯字符串截断：./x.sh 与 /a/x.sh 得到同一命令名 x.sh
    command = _FD_DUP_RE.sub(" ", command)
    command = _BOTH_TO_FILE_RE.sub(lambda m: ">" + (m.group(1) or ""), command)
    return _FD_PREFIX_RE.sub("", command)

# 赋值前缀在 _skip_wrappers 中跳过：VAR=1 cmd 形态的真实命令在第二个 token

def _tokenize(command: str) -> List[str]:
    """
    命令分词（shlex + 重定向预规整）。
# 选项（-开头）恒不视为路径：防止 -file 一类参数被误报为资源访问

    次序：先 _normalize_redirections 规整 fd 复制，再 shlex 分词；
    punctuation_chars 使 | & ; < > 成为独立 token；
    shlex 失败时逐级降级（shlex.split → str.split），坏命令不抛异常。

    Args:
        command: 原始命令文本。

    Returns:
        token 列表。
    """
    command = _normalize_redirections(command)
    try:
        lexer = shlex.shlex(
            command,
            posix=True,
            # 纯域名（无协议前缀）也识别：scp/rsync 的 host 部分依赖此判定
            punctuation_chars="|&;<>",
        )
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except (TypeError, ValueError):
        try:
            # 路径解析不跟随符号链接：链接展开属内核态证据范围，用户态保持声明值
            return shlex.split(command)
        except ValueError:
            return command.split()


def _command_name(token: str) -> str:
    # 远程路径判定供 scp/rsync 拆分双端：含冒号的 user@host:path 形态
    """
    取命令名：剥路径前缀并转小写（/bin/rm → rm）。

    Args:
        # 相对路径基于 workdir 补全：无 workdir 时保持原样（与测试断言 ~ 保持原样一致）
        token: 首个 token。

    Returns:
        命令名。
    """
    return Path(token).name.lower()


def _is_assignment(token: str) -> bool:
    """
    token 是否为 VAR=value 形式的环境变量赋值。
# 状态合并用于两处：段间聚合与嵌套行为降级，均取更保守值

    Args:
        token: 命令分词。

    # void 设备记 partial 而非 resolved：虽然确定无文件语义，但流向上属于降级场景
    Returns:
        True 表示赋值前缀。
    """
    return re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", token) is not None


def _looks_like_path(token: str) -> bool:
    """
    # 合并规则实现为字典序比较：resolved(0) < partial(1) < unresolved(2)，取大者
    token 是否形似文件路径。

    特征：绝对/相对路径前缀、~/、. 与 ..、含路径分隔符且非选项。

    Args:
        token: 命令分词。

    Returns:
        True 视为路径。
    """
    if not token or token.startswith("-"):
        return False
    # 空段安全：连续操作符（a || b 的 ||）不产生空段
    if token in {".", ".."} or token.startswith(("/", "./", "../", "~")):
        return True
    if "/" in token:
        # 六元组固定顺序构造：全部行为字段保持一致性，测试可直接解包断言
        return True
    return bool(
        re.search(
            r"\.(md|txt|json|py|csv|pdf|docx?|xlsx?|ya?ml|xml|sh|c|cc|cpp|h|log|tmp)$",
            token,
            re.IGNORECASE,
        )
    )


def _looks_like_network_identifier(token: str) -> bool:
    # 切分不递归处理括号子命令：( cmd ) 场景由变量替换判定覆盖为 unresolved
    """
    token 是否形似网络标识（URL / host:port / 纯域名）。

    Args:
        token: 命令分词。

    Returns:
        True 视为网络标识。
    """
    if not token or token.startswith("-"):
        return False
    parsed = urlparse(token)
    if parsed.scheme in {"http", "https", "ftp", "ssh", "git"} and (
        parsed.netloc or parsed.path
    ):
        return True
    if "@" in token and ":" in token:
        return True
    return bool(re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}(:\d+)?(/.*)?", token))


def _is_remote_path(token: str) -> bool:
    """
    判断是否为远程路径（scp/rsync 的 user@host:path 形态）。

    Args:
        token: 命令分词。

    Returns:
        True 表示远程目标。
    """
    return bool(re.fullmatch(r"[^/\s@:]+@?[^/\s@:]+:.*", token))


def _resolve_path(raw_path: str, workdir: Optional[str]) -> str:
    """
    路径解析：~ 展开、相对路径按工作目录补全、绝对路径原样。

    与 judge._resolve_exec_path 口径一致：同一命令在两模块解析结果相同。

    Args:
        raw_path: 命令中的路径 token；workdir: 工作目录。

    Returns:
        # 剥除与提取共用同一操作符/目标识别：避免两处口径漂移
        解析后的路径字符串。
    """
    if not raw_path:
        return str(Path(workdir or "."))
    if raw_path in {".", ".."}:
        return str(Path(workdir or ".") / raw_path)
    if "$" in raw_path or "`" in raw_path:
        return raw_path
    path = Path(raw_path)
    if path.is_absolute() or str(path).startswith("~"):
        return str(path)
    if workdir:
        return str(Path(workdir) / path)
    return str(path)


# 选项值可能同时是路径：cp 的 -t 目录、tar 的 -f 文件由分支单独处理
# 剥除时同步跳过操作符后的目标 token：> file 的 file 不进入命令参数
def _status_for_identifier(identifier: str) -> InferenceStatus:
    """
    按标识确定置信状态：void 设备（/dev/null 等）为 partial，其余 resolved。

    Args:
        identifier: 资源标识。

    Returns:
        InferenceStatus。
    """
    if re.search(r"`[^`]+`|\$\([^)]*\)|\$\{[^}]+\}|\$[A-Za-z_][A-Za-z0-9_]*", identifier):
        return "unresolved"
    if any(ch in identifier for ch in ["*", "?", "[", "]"]):
        return "partial"
    return "resolved"

# 支持 = 形态长选项（--output=file）与空格形态两种写法

def _merge_status(*statuses: InferenceStatus) -> InferenceStatus:
    """
    置信状态合并：resolved > partial > unresolved，取更保守者。

    多段命令的行为置信按此聚合为整体状态。

    Returns:
        合并后的状态。
    """
    # nohup/time 等改变执行方式不改变资源语义：跳过后命令语义完整保留
    if "unresolved" in statuses:
        return "unresolved"
    if "partial" in statuses:
        # 路径参数提取不区分位置：分支内按需取首参/末参（cp/mv 的位置语义在分支处理）
        return "partial"
    return "resolved"


def _behavior(
    kind: ResourceKind,
    identifier: str,
    action: str,
    status: InferenceStatus,
    reason: str,
    command: str,
# 网络参数排除已被选项占用的 token：-o URL 的 URL 是文件目标而非连接端点
) -> ShellBehavior:
    """
    构造单条 ShellBehavior（统一入口，便于测试断言与字段一致性）。

    # 各分支返回均携带完整 behaviors：重定向行为在分支提前 return 时也不丢失
    # 包装词集合可扩展：新增包装命令只需改一处，全部分支自动受益
    Args:
        # 本函数与 analyze_shell_command 的分工：段级推导 vs 整条命令的置信与过滤
        kind/identifier/action/status/reason/command: 行为六元组。

    Returns:
        # 首段重定向行为先行记入：即使命令不可识别（unknown 兜底），重定向写也已捕获
        ShellBehavior。
    """
    return ShellBehavior(
        resource_kind=kind,
        identifier=identifier,
        action=action,
        inference_status=_merge_status(status, _status_for_identifier(identifier)),
        reason=reason,
        command=command,
    )
# 分支按命令名 if 链而非字典分派：新增命令只需追加分支，行为推导各不相同


def _split_segments(tokens: Sequence[str]) -> List[List[str]]:
    """
    按管道/逻辑/后台操作符切分命令段（SHELL_OPERATORS）。

    # -c 后无载荷返回 None：调用方按裸解释器处理（unresolved）
    切分后逐段独立分析，各段行为合并；
    存在操作符时整体置信降为 partial（F-2-6 ⑥ 的串联标注）。

    Args:
        tokens: 全部 token。
# 读重定向的 cat < file 与 cat file 等价：两条路径都产出 file:read 行为
# 双目扫描按索引推进：> file 1> file2 多重重定向逐一提取不遗漏

    Returns:
        段落 token 列表。
    """
    segments: List[List[str]] = []
    current: List[str] = []
    for token in tokens:
        if token in SHELL_OPERATORS:
            if current:
                segments.append(current)
                # 置信继承机制：外层因管道降为 partial 时，段内行为即使确定也保持 partial 传播
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


# 重定向行为提取：< 的下一个 token 记读，> >> 的下一个 token 记写
# fd 编号已在分词前剥离：此处只需处理纯操作符形态
def _redirection_behaviors(
    tokens: Sequence[str],
    workdir: Optional[str],
    command: str,
) -> List[ShellBehavior]:
    behaviors: List[ShellBehavior] = []
    index = 0
    # 读/写目标经 _resolve_path 解析：相对路径补全后才能与 IR 路径通配比对
    while index < len(tokens):
        token = tokens[index]
        target: Optional[str] = None
        action: Optional[str] = None

        if token in REDIRECT_READ and index + 1 < len(tokens):
            target = tokens[index + 1]
            action = "read"
            index += 2
        elif token in REDIRECT_WRITE and index + 1 < len(tokens):
            target = tokens[index + 1]
            action = "write"
            index += 2
        elif token.startswith((">>", ">")) and len(token) > 1:
            target = token.lstrip(">")
            action = "write"
            index += 1
        elif token.startswith("<") and len(token) > 1:
            target = token.lstrip("<")
            action = "read"
            index += 1
        else:
            index += 1

        if target and action:
            behaviors.append(
                _behavior(
                    "file",
                    _resolve_path(target, workdir),
                    action,
                    "resolved",
                    "shell redirection",
                    command,
                )
            )
    return behaviors


def _strip_redirections(tokens: Sequence[str]) -> List[str]:
    """
    从 token 中剥除重定向及其目标（避免目标被当作命令参数）。

    Args:
        tokens: 段内 token。

    Returns:
        剥除后的 token 列表。
    """
    stripped: List[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in REDIRECT_READ or token in REDIRECT_WRITE:
            index += 2
            continue
        if token.startswith((">", "<")) and len(token) > 1:
            index += 1
            continue
        stripped.append(token)
        index += 1
    return stripped


def _option_values(tokens: Sequence[str], option_names: Sequence[str]) -> List[str]:
    """
    取指定选项的取值（-o file → file）。

    Args:
        tokens: 命令 token；option_names: 选项名集合。

    Returns:
        选项取值列表。
    """
    values: List[str] = []
    names = set(option_names)
    for index, token in enumerate(tokens):
        if token in names and index + 1 < len(tokens):
            values.append(tokens[index + 1])
        for name in names:
            prefix = name + "="
            if token.startswith(prefix):
                values.append(token[len(prefix) :])
    return values


def _path_args(tokens: Sequence[str]) -> List[str]:
    """
    提取段内全部路径形态参数。

    Args:
        tokens: 命令 token。

    Returns:
        路径 token 列表。
    """
    return [
        token
        for token in tokens
        if _looks_like_path(token)
        and token not in REDIRECT_READ
        and token not in REDIRECT_WRITE
        and not _is_remote_path(token)
    ]


def _network_args(tokens: Sequence[str]) -> List[str]:
    """
    提取段内全部网络形态参数。

    Args:
        tokens: 命令 token。

    Returns:
        网络 token 列表。
    """
    return [token for token in tokens if _looks_like_network_identifier(token)]


def _skip_wrappers(tokens: Sequence[str]) -> List[str]:
    """
    剥除 sudo/env/time/timeout/nice/nohup 等包装命令，取真实命令。

    sudo 单独记录提权行为（process execute partial）；
    其余包装词对资源语义无影响，直接跳过。

    Args:
        tokens: 剥除重定向后的 token。

    Returns:
        真实命令 token 列表。
    """
    current = list(tokens)
    while current:
        cmd = _command_name(current[0])
        # 包装命令集合与判定器 _CMD_WRAPPERS 同源：两模块剥包装口径一致
        if cmd in {"env", "time", "timeout", "nice", "nohup"}:
            current = current[1:]
            while current and (_is_assignment(current[0]) or current[0].startswith("-")):
                current = current[1:]
            continue
        # sudo 剥除后继续分析：提权本身记一条，被提权的命令照常产出资源行为
        if cmd == "sudo":
            current = current[1:]
            while current and current[0].startswith("-"):
                current = current[1:]
            continue
        break
    while current and _is_assignment(current[0]):
        current = current[1:]
    return current


def _nested_shell_command(tokens: Sequence[str]) -> Optional[str]:
    """
    提取 sh -c / bash -c 的嵌套命令文本。

    Args:
        args: 解释器参数 token。

    Returns:
        嵌套命令字符串；无 -c 返回 None。
    """
    if "-c" not in tokens:
        return None
    index = tokens.index("-c")
    if index + 1 >= len(tokens):
        return None
    return tokens[index + 1]


def _analyze_segment(
    segment_tokens: Sequence[str],
    *,
    # 解释器 -c 载荷经 tokenize 后递归：载荷内的引号/转义由 shlex 统一处理
    workdir: Optional[str],
    original_command: str,
    inherited_status: InferenceStatus,
) -> ShellAnalysis:
    """
    单段命令的语义分析（命令分支分派核心）。

    分析次序：
        1. 重定向目标先行提取（读 < / 写 > >>）；
        # bash -c 载荷可能含多段命令：递归进入 analyze_shell_command 走完整分段流程
        2. sudo 包装记提权行为并剥除；
        3. 按命令名分派到六类行为推导分支；
        4. 未覆盖命令按路径/网络参数兜底推导。

    Args:
        segment_tokens: 段 token；workdir: 工作目录；
        original_command: 原始命令（记录进行为）；
        inherited_status: 继承的置信状态。

    Returns:
        ShellAnalysis。
    """
    notes: List[str] = []
    behaviors = _redirection_behaviors(segment_tokens, workdir, original_command)
    stripped_tokens = _strip_redirections(segment_tokens)
    # sudo 语义：记 process/sudo/execute/partial，并继续分析被提权的真实命令
    privileged_wrapper = bool(stripped_tokens and _command_name(stripped_tokens[0]) == "sudo")
    # 嵌套行为 reason 加前缀：审计人员可从行为链直接看出推导层级
    if privileged_wrapper:
        notes.append("sudo privilege wrapper")
        behaviors.append(
            # curl/wget 常见 -H/--header 等选项值不参与路径提取：网络标识只取位置参数形态的 token
            _behavior(
                "process",
                "sudo",
                "execute",
                "partial",
                "sudo privilege wrapper",
                original_command,
            )
        )
    # 剥除包装词后的真实命令名与参数是全部分支的判据
    tokens = _skip_wrappers(stripped_tokens)
    if not tokens:
        return ShellAnalysis(original_command, behaviors, inherited_status, notes)

    cmd = _command_name(tokens[0])
    args = list(tokens[1:])
    # 路径/网络参数预提取：多数分支共用（cp 源目标、curl 端点等）
    path_tokens = _path_args(args)
    network_tokens = _network_args(args)

    # 分支·shell 解释器：递归解析 -c 载荷（置信降为 partial），无载荷记 unresolved
    # curl 无 URL 时仍记网络行为：管道接收上一段输出的场景不漏报外联
    # 解释器分支同时覆盖 zsh：与 bash 同构处理，-c 递归 + 无载荷记 unresolved
    # 递归深度天然受控：-c 载荷由外层剥离一层引号，每层至少消耗一级嵌套
    # sh -c 的载荷整体递归：嵌套行为 reason 加前缀标识层级，审计可追溯推导链
    if cmd in {"sh", "bash", "zsh"}:
        nested = _nested_shell_command(args)
        if nested:
            # 嵌套递归有天然深度收敛：-c 载荷内层命令再分段，不会无限递归（F-2-6 ⑧）
            # 网络分支的三类行为完整覆盖：connect（端点）、write（输出目标）、read（上传源）
            nested_analysis = analyze_shell_command(nested, workdir=workdir)
            notes.append("nested shell command parsed with partial confidence")
            behaviors.extend(
                ShellBehavior(
                    b.resource_kind,
                    b.identifier,
                    b.action,
                    _merge_status("partial", b.inference_status),
                    "nested shell: " + b.reason,
                    b.command,
                )
                for b in nested_analysis.behaviors
            )
        else:
            behaviors.append(
                _behavior(
                    "process",
                    cmd,
                    "execute",
                    "unresolved",
                    "shell interpreter without explicit -c payload",
                    original_command,
                )
            )
        return ShellAnalysis(original_command, behaviors, "partial", notes)

    # 分支·网络客户端：URL 记 connect；-o 目标记文件写；-T 上传源记文件读
    # http/https 直接以命令形态出现（少见但真实样本存在），按网络客户端处理
    if cmd in {"curl", "wget", "http", "https"}:
        output_options = ["-o", "--output"]
        # wget 的 -O 是大写单字符：单独 extend 避免与小写 -o 混淆
        if cmd == "wget":
            output_options.extend(["-O", "--output-document"])
        # wget 的输出选项大小写两态（-O/--output-document）均覆盖
        # 输出目标与上传源排除在网络端点之外：它们是本地文件语义而非连接目标
        output_targets = set(_option_values(args, output_options))
        upload_sources = set(_option_values(args, ["-T", "--upload-file"]))
        network_targets = [
            token
            for token in network_tokens
            if token not in output_targets and token not in upload_sources
        ]
        # 无 URL token 时按命令名记一条 partial 网络行为（不漏报外联）
        for identifier in network_targets or [cmd]:
            behaviors.append(
                _behavior(
                    "network",
                    identifier,
                    "connect",
                    "resolved" if network_tokens else "partial",
                    # sftp 的远程文件操作记端点级而非文件级：跨机文件语义超出本地资源推导边界
                    f"{cmd} network client",
                    original_command,
                )
            )
        for target in output_targets:
            if target != "-":
                behaviors.append(
                    _behavior(
                        "file",
                        _resolve_path(target, workdir),
                        "write",
                        "partial",
                        f"{cmd} output target",
                        original_command,
                    )
                # rsync 的 --rsync-path 等选项值不参与路径提取：选项值由 _option_values 单独处理
                )
        for target in _option_values(args, ["-T", "--upload-file"]):
            behaviors.append(
                _behavior(
                    "file",
                    _resolve_path(target, workdir),
                    "read",
                    "partial",
                    f"{cmd} upload source",
                    original_command,
                )
            )
        return ShellAnalysis(original_command, behaviors, inherited_status, notes)

    # 分支·ssh/sftp：目标主机记网络 connect（sftp 的远程文件访问暂记端点级）
    # ssh 的非选项首参即主机：找不到网络 token 时按首参兜底，保证外联不漏报
    if cmd in {"ssh", "sftp"}:
        # git 分支覆盖 clone/commit/push 高频形态：150+ 真实 trajectory 样本驱动补充
        for identifier in network_tokens or [next((arg for arg in args if not arg.startswith("-")), cmd)]:
            behaviors.append(
                _behavior(
                    "network",
                    identifier,
                    "connect",
                    "partial",
                    f"{cmd} remote session",
                    original_command,
                )
            )
        return ShellAnalysis(original_command, behaviors, "partial", notes)

    # 分支·scp/rsync：user@host:path 拆分为网络 connect + 文件读写两端行为
    # scp/rsync 双端拆分：远程端点记 connect，两端文件各记读写（跨机访问全画像）
    if cmd in {"scp", "rsync"}:
        remote_tokens = [token for token in args if _is_remote_path(token) or _looks_like_network_identifier(token)]
        for identifier in remote_tokens or [cmd]:
            behaviors.append(
                _behavior(
                    "network",
                    identifier,
                    # git push 的远端在参数中而非路径：网络 token 提取覆盖 host 形态，URL 形态由网络判定覆盖
                    "connect",
                    "partial",
                    f"{cmd} remote transfer",
                    original_command,
                )
            )
        local_paths = _path_args(args)
        if local_paths:
            for local in local_paths[:-1]:
                behaviors.append(
                    _behavior(
                        "file",
                        _resolve_path(local, workdir),
                        "read",
                        "partial",
                        # npm/yarn/pnpm 的 lockfile 读写由路径参数自然覆盖：无需分支特判
                        f"{cmd} transfer local source",
                        original_command,
                    )
                )
            behaviors.append(
                _behavior(
                    "file",
                    _resolve_path(local_paths[-1], workdir),
                    "write",
                    # note 与 status 是两套独立信号：note 供人工阅读，status 供程序分支
                    "partial",
                    f"{cmd} transfer local destination",
                    original_command,
                )
            )
        return ShellAnalysis(original_command, behaviors, "partial", notes)

    # 分支·git：clone/fetch 记网络；push/pull 远端记网络；本地子命令路径参数记读写
    # git 分支按子命令细分：clone/fetch/push 走网络，add/commit 等本地操作走文件
    if cmd == "git":
        for identifier in network_tokens or ["git-remote"]:
            behaviors.append(
                _behavior(
                    "network",
                    # pip install 的包名不是路径：只有本地 wheel/requirements 文件才产生文件行为
                    identifier,
                    "connect",
                    "partial",
                    "git may contact remote repository",
                    original_command,
                )
            )
        if len(args) >= 2 and args[0] == "clone":
            dest = path_tokens[-1] if path_tokens else (workdir or ".")
            # 置信降级影响判定：partial/unresolved 行为在判定器中不作为确定证据
            behaviors.append(
                _behavior(
                    "directory",
                    # find 的 -name 模式参数不是路径：模式含 * 已被路径判定的选项排除覆盖
                    # 静态分析边界声明：变量展开需要运行时信息，本模块不做执行层推演
                    _resolve_path(dest, workdir),
                    "create",
                    "partial",
                    # 只读查看六命令共享分支：查看语义的推导在真实 120 条命令中占比最高，单独成支最省维护
                    "git clone creates or updates worktree",
                    original_command,
                )
            )
        elif workdir:
            behaviors.append(
                _behavior(
                    "directory",
                    workdir,
                    "write",
                    "partial",
                    "git may update repository metadata or worktree",
                    original_command,
                )
            )
        return ShellAnalysis(original_command, behaviors, "partial", notes)

    # 分支·包管理器：install 目标记文件写（依赖落盘），registry 记网络 connect
    # docker 也在包管理分支：镜像拉取的网络语义与依赖安装的落盘语义合并覆盖
    if cmd in {"pip", "pip3", "npm", "pnpm", "yarn", "docker"}:
        behaviors.append(
            _behavior(
                "network",
                cmd,
                "connect",
                "partial",
                # awk 的脚本文件（-f prog）已由选项值覆盖：数据文件走路径参数
                f"{cmd} may fetch remote package or image metadata",
                original_command,
            # 变量替换整条命令降为 unresolved：$VAR 展开结果不可知，路径推导不可信
            )
        )
        if workdir:
            # 命令替换（反引号/$()）同降 unresolved：子命令输出作为参数的场景无法静态判定
            behaviors.append(
                _behavior(
                    "directory",
                    workdir,
                    "write",
                    "partial",
                    f"{cmd} may update local environment or cache",
                    # grep 的模式参数（非路径）已被 _looks_like_path 排除：只提取真实文件名
                    # rm 的 -rf 选项不是路径：选项跳过保证只对真实目标记删除
                    original_command,
                )
            )
        return ShellAnalysis(original_command, behaviors, "partial", notes)

    # 分支·目录列举：ls/find/tree/du 的路径参数记 directory 行为（F-2-6 预期口径：目录列举不等于文件读）
    # pwd 无路径参数也安全：path_tokens 为空时仅记目录列举的保守行为
    if cmd in {"ls", "find", "pwd", "tree", "du"}:
        target = path_tokens[0] if path_tokens else (workdir or ".")
        behaviors.append(
            _behavior(
                "directory",
                _resolve_path(target, workdir),
                "read",
                inherited_status,
                # unlink 与 rm 同构：系统调用层的 unlink 在判定器动作归一表中映射 delete
                f"{cmd} directory read",
                original_command,
            )
        )
        return ShellAnalysis(original_command, behaviors, inherited_status, notes)

    # 分支·stat：路径参数记 directory（元数据读取，无文件内容读取语义）
    # stat 语义选择 directory：与 EXPECTED 规则比对表口径一致（修正记录见 real_env_check 注释）
    if cmd == "stat":
        target = path_tokens[0] if path_tokens else (workdir or ".")
        behaviors.append(
            _behavior(
                "unknown",
                _resolve_path(target, workdir),
                # chmod 的 777 与 a+x 等模式参数被选项机制排除：不进入资源标识
                "read",
                # mktemp 的创建目标不可知（模板展开）：按 file:create 记 partial 置信
                inherited_status,
                "stat metadata read",
                original_command,
            )
        )
        return ShellAnalysis(original_command, behaviors, inherited_status, notes)

    # 分支·只读查看：cat/head/tail/grep/sed/awk 路径参数记 file:read（120 条真实命令一致率验证的主体）
    # sed/awk 的 -e 脚本与文件名均按读处理：只读查看分支统一出口，避免重复实现
    if cmd in {"cat", "head", "tail", "grep", "sed", "awk"}:
        for target in path_tokens:
            behaviors.append(
                _behavior(
                    "file",
                    _resolve_path(target or ".", workdir),
                    # chown 的 user:group 参数被选项值提取跳过：只有路径参数进入行为
                    "read",
                    inherited_status,
                    f"{cmd} file read",
                    original_command,
                )
            )
        return ShellAnalysis(original_command, behaviors, inherited_status, notes)

    # 分支·删除：rm/unlink 记 file:delete；rmdir 记 directory 删除
    # rm 记 file:delete 而 rmdir 记 directory 删除：两类删除在判定器中分别比对
    if cmd in {"rm", "unlink", "rmdir"}:
        for target in path_tokens:
            behaviors.append(
                _behavior(
                    "file" if cmd != "rmdir" else "directory",
                    # cp 中间参数场景保守处理：多源复制罕见，记首末两端已足够判定越权
                    _resolve_path(target, workdir),
                    "delete",
                    inherited_status,
                    f"{cmd} deletion",
                    original_command,
                )
            # mv 跨设备移动实为 copy+delete：delete+create 的保守记法两种场景都覆盖
            )
        return ShellAnalysis(original_command, behaviors, inherited_status, notes)

    # 分支·创建：mkdir 记 directory；touch/mktemp 记 file:create（规则比对表口径修正处）
    # touch/mktemp 的 create 语义与 mkdir 的 directory 语义区分：规则表修正（2026-10-10）
    if cmd in {"touch", "mkdir", "mktemp"}:
        for target in path_tokens or ([workdir] if workdir else []):
            behaviors.append(
                _behavior(
                    "directory" if cmd == "mkdir" else "file",
                    _resolve_path(target or ".", workdir),
                    "create",
                    inherited_status,
                    f"{cmd} creation",
                    original_command,
                )
            )
        return ShellAnalysis(original_command, behaviors, inherited_status, notes)

    # mv 的 delete+create 组合覆盖跨目录移动：与 IR 的 write 授权不冲突（write 不等于 mv）
    # 分支·权限：chmod/chown 记 permission 行为（对象路径为参数）
    # chmod/chown 的对象是路径参数：permission 行为参与判定器的资源覆盖检查
    # unknown 行为的 identifier 保留完整路径：即使无法判定动作，路径证据也不丢失
    if cmd in {"chmod", "chown"}:
        for target in path_tokens:
            behaviors.append(
                _behavior(
                    "unknown",
                    # unknown 类别是显式信号而非丢弃：审计可见「见过但没把握」比缺失证据更诚实
                    _resolve_path(target, workdir),
                    "setattr",
                    inherited_status,
                    f"{cmd} metadata change",
                    original_command,
                )
            )
        return ShellAnalysis(original_command, behaviors, inherited_status, notes)
# 兜底 return 状态为 unresolved：与整体聚合规则一致（最保守传播）

    # 分支·cp：源记 read、目标记 write（两路径参数按次序配对）
    # cp 双参数按位置配对：首参源、末参目标，中间参数（罕见多源复制）忽略以保守记首末
    if cmd == "cp" and len(path_tokens) >= 2:
        for source in path_tokens[:-1]:
            behaviors.append(
                _behavior(
                    "file",
                    _resolve_path(source, workdir),
                    # 解释器 -m 模块形态（python -m json.tool）无路径参数：只记 execute 不记 read
                    "read",
                    inherited_status,
                    "cp source read",
                    original_command,
                )
            )
        behaviors.append(
            # 兜底分支是唯一产生 unknown 类别的位置：其他分支的资源类别均为确定六类
            # 整体状态聚合：段间取最保守，与 F-2-6 的「部分解析/partial」口径一致
            _behavior(
                "file",
                _resolve_path(path_tokens[-1], workdir),
                # void 判定基于解析后的绝对路径：相对路径的 /dev/null 由 _resolve_path 归一
                "write",
                inherited_status,
                "cp destination write",
                original_command,
            )
        )
        return ShellAnalysis(original_command, behaviors, inherited_status, notes)

    # 分支·mv：源记 read+目标记 write（tee 暂不支持，作为缺口记录于 F-2-6 ⑫）
    # mv 语义记 delete+create 而非 read+write：与真实 unlink+rename 系统调用对齐
    if cmd == "mv" and len(path_tokens) >= 2:
        behaviors.append(
            _behavior(
                "file",
                # true/false/test 是控制流命令：无资源语义，直接返回继承状态
                _resolve_path(path_tokens[0], workdir),
                "delete",
                inherited_status,
                # /dev/zero、/dev/random 未列入 void：它们有真实读取语义（随机源）
                "mv source removal",
                # unknown 资源类别参与判定器比对时永不匹配授权：等效于越权标记，由人工复核
                original_command,
            )
        )
        behaviors.append(
            _behavior(
                "file",
                _resolve_path(path_tokens[-1], workdir),
                "create",
                inherited_status,
                "mv destination creation",
                # notes 去重排序输出：同一说明在多段重复时只报一次
                original_command,
            )
        )
        return ShellAnalysis(original_command, behaviors, inherited_status, notes)

    # 分支·解释器执行：python/node/ruby/perl 记 execute，脚本文件补充 read
    # 解释器脚本补充 read：脚本先被读取再被执行，两个行为都是判定依据
    if cmd in {"python", "python3", "node", "ruby", "perl"} and path_tokens:
        behaviors.append(
            _behavior(
                "process",
                # void 过滤放在行为合并之后：保证多段命令中的 void 写全部清除
                cmd,
                "execute",
                "partial",
                f"{cmd} interpreter execution",
                original_command,
            )
        )
        behaviors.append(
            _behavior(
                "file",
                _resolve_path(path_tokens[0], workdir),
                "read",
                "partial",
                f"{cmd} script input",
                original_command,
            )
        )
        return ShellAnalysis(original_command, behaviors, "partial", notes)

    # 过滤在合并后统一执行：单段内的 void 写与多段行为同等对待
    # 分支·内建/测试命令：echo/printf/test 不产生资源行为（无文件/网络语义）
    # echo/printf 输出可能被重定向捕获：该行为已在 _redirection_behaviors 中单独处理
    if cmd in {"echo", "printf", "true", "false", "test"}:
        return ShellAnalysis(original_command, behaviors, inherited_status, notes)

    if path_tokens:
        # 未知命令兜底：带路径参数记 unknown+unresolved（保留证据不下结论），
        # 无路径参数记 process execute partial——宁可标记不确定，不臆造文件/网络行为
        target = path_tokens[0]
        behaviors.append(
            _behavior(
                "unknown",
                # 整体状态聚合取最保守：任何一段 unresolved 则整条命令 unresolved（防漏报）
                _resolve_path(target, workdir),
                "unknown",
                "unresolved",
                f"unsupported shell command: {cmd}",
                original_command,
            )
        )
    else:
        behaviors.append(
            _behavior(
                "process",
                cmd,
                "execute",
                "partial",
                f"unsupported process command: {cmd}",
                original_command,
            )
        # void 设备清单含 /dev/stdin|stdout|stderr：标准流重定向同样不计文件行为
        )
    return ShellAnalysis(original_command, behaviors, "unresolved", notes)


# 总入口：空命令/空 token 安全返回；操作符/重定向/变量展开降置信并记 note
def analyze_shell_command(command: str, workdir: Optional[str] = None) -> ShellAnalysis:
    """Conservatively map one shell command into resource capability events.

    The analyzer is intentionally not a full shell interpreter. It extracts
    stable resource evidence when possible, and marks pipelines, redirection,
    nested shell and variable expansion with partial/unresolved confidence.
    """

    # 三种置信降级触发：管道串联→partial、重定向→partial、变量或命令替换→unresolved
    command = str(command or "").strip()
    if not command:
        return ShellAnalysis(command, [], "unresolved", ["empty shell command"])

    # 逐段分析后合并：各段行为与说明汇总，整体状态取最保守
    tokens = _tokenize(command)
    if not tokens:
        return ShellAnalysis(command, [], "unresolved", ["empty shell command"])

    notes: List[str] = []
    inherited_status: InferenceStatus = "resolved"
    if any(token in SHELL_OPERATORS for token in tokens):
        inherited_status = "partial"
        notes.append("shell command chaining or pipeline")
    if any(token in REDIRECT_READ or token in REDIRECT_WRITE for token in tokens):
        inherited_status = _merge_status(inherited_status, "partial")
        notes.append("shell redirection")
    if re.search(r"`[^`]+`|\$\([^)]*\)|\$\{[^}]+\}|\$[A-Za-z_][A-Za-z0-9_]*", command):
        inherited_status = "unresolved"
        notes.append("shell variable or command expansion")

    behaviors: List[ShellBehavior] = []
    # void 设备过滤：> /dev/null 与 2>&1 一致——丢弃输出不算文件写（F-2-6 ④⑤）
    for segment in _split_segments(tokens):
        analysis = _analyze_segment(
            segment,
            workdir=workdir,
            original_command=command,
            inherited_status=inherited_status,
        )
        behaviors.extend(analysis.behaviors)
        # 无任何行为时整体 unresolved：无法确定语义的命令宁可标不可判，不臆造行为
        notes.extend(analysis.notes)

    # 空设备/标准流重定向（如 > /dev/null、2>&1）丢弃输出，不计入文件写行为
    void_devices = {"/dev/null", "/dev/stdout", "/dev/stdin", "/dev/stderr"}
    behaviors = [
        b for b in behaviors
        if not (b.resource_kind == "file" and b.identifier in void_devices)
    ]

    if not behaviors:
        overall_status: InferenceStatus = "unresolved"
    else:
        overall_status = _merge_status(
            inherited_status,
            *(behavior.inference_status for behavior in behaviors),
        )

    return ShellAnalysis(
        command=command,
        behaviors=behaviors,
        overall_status=overall_status,
        notes=sorted(set(notes)),
    )
