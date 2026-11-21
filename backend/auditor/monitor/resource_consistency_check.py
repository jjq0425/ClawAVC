# 文件定位：用户态行为合规判定器的首个独立实现（judge.py 的前身），
# 语义与新版一致——保留用于离线回放、历史比对与判定口径回归。
# 行为侧（BehaviorEvent）含轮次元信息与 outcome，是本文件较 judge.py 多出的
# 网关侧适配层（judge.py 已把该层收敛到 watcher/judge 协作中）。
# 历史独立版本说明：运行链路已由 judge.py 接管，本文件保留用于离线回放与比对
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence
# Action 别名为裸字符串：归一后的动作集合见 _normalize_action 的映射表
from urllib.parse import urlparse
# ResourceType 三值是判定分桶的全部类别：内核态细粒度由 resource_kind 表达

from shell_command_semantics import analyze_shell_command

# tool_trajectory 默认权重 0 的原因：早期数据中该维证据链弱、误报高，
# 实验确认置零不影响整体判定（历史结论，judge.py 已不设权重）
# 类型别名：动作（归一字符串）与资源三类型
Action = str
ResourceType = Literal["file", "tool", "network"]
# resource_kind 五分类：file/directory/network/process/unknown（内核态可观测的细粒度）
ResourceKind = Literal["file", "directory", "network", "process", "unknown"]

# 维度权重默认表：顺序维默认 0（该维证据链弱，实验后置零），其余等权 1.0
DEFAULT_ASPECT_WEIGHTS: Dict[str, float] = {
    # frozen=True 不可变：判定过程不修改 IR 对象（并发安全）
    "tool_call": 1.0,
    "tool_trajectory": 0.0,
    "parameter": 1.0,
    # identifier_match 四模式：auto/glob/regex/exact，缺省 auto
    "resource_access": 1.0,
}


# IRObject 五字段：类型/标识/动作/参数/SELinux 规则 + 匹配模式
@dataclass(frozen=True)
# IRObject：IR 资源对象（工具/文件/网络），identifier_match 支持精确/通配/正则三分派
class IRObject:
    """One resource object parsed from group-1 IR JSON."""

    type: ResourceType
    identifier: str
    actions: Sequence[Action]
    params: Optional[Dict[str, str]] = None
    selinux_rules: Sequence[str] = ()
    identifier_match: Literal["auto", "exact", "glob", "regex"] = "auto"

# effect 二值：allow/deny——deny 在策略库生成侧已优先（deny-wins）

@dataclass(frozen=True)
# IRPolicy：单条授权策略（subject + objects + effect）
class IRPolicy:
    # frozen 行为事件：一次构造全程不可变，避免判定中途被篡改
    """One allow/deny policy parsed from group-1 IR JSON."""

    subject: str
    objects: Sequence[IRObject]
    effect: Literal["allow", "deny"] = "allow"


@dataclass(frozen=True)
# BehaviorEvent：实际行为事件（类型/标识/动作/参数），四维比对的输入单元
# inference_status 三态贯穿判定：resolved 采信、partial 保守参与、unresolved 不采信
class BehaviorEvent:
    """Observed user-space behavior event."""
# source 供证据溯源：同一行为可标注其来源层（网关/内核/手工）

    # BehaviorEvent 主体三件套：类型/标识/动作（四维比对的直接输入）
    resource_type: ResourceType
    # round_id_source/timestamp_source 让「派生轮次」显式可辨：审计不被伪 round_id 误导
    identifier: str
    action: Action
    params: Optional[Dict[str, str]] = None
    # resource_kind 与 inference_status：推导细粒度与置信（unresolved 不参与判定）
    # pid/parent_pid 供与 proc_info 采集结果对齐（执行主体证据）
    resource_kind: ResourceKind = "file"
    inference_status: Literal["resolved", "partial", "unresolved"] = "resolved"
    inference_reason: Optional[str] = None
    # source 四态：manual（手写）/gateway（网关还原）/kernel（内核态）/trace
    # outcome 只做证据不做判定：失败的工具调用仍是行为（越权失败依旧违规）
    source: str = "manual"
    source_tool: Optional[str] = None
    tool_call_id: Optional[str] = None
    # 轮次元信息四字段：round_id 及其来源、时间戳及其来源（round 归属的完整证据）
    round_id: Optional[str] = None
    round_id_source: Optional[str] = None
    timestamp: Optional[str] = None
    timestamp_source: Optional[str] = None
    # 进程上下文：pid/parent_pid/container_id/sandbox_id（内核态对齐的预留字段）
    pid: Optional[int] = None
    parent_pid: Optional[int] = None
    container_id: Optional[str] = None
    sandbox_id: Optional[str] = None
    # outcome 四态：success/error/pending/unknown（工具结果语义，不参与判定只做证据）
    outcome: Literal["success", "error", "pending", "unknown"] = "unknown"
    # CheckResult：扁平判定输出（consistent/violations/matched_rules）
    outcome_detail: Optional[str] = None


@dataclass(frozen=True)
class CheckResult:
    """
    单维一致性检查结果（旧版扁平判定输出）。
# ScoredCheckResult：带得分判定输出（score = 命中/检查数）

    consistent: yes/no；violations: 违规明细；
    matched_rules: 命中对象附带的 SELinux 规则（证据链）。
    """
    consistent: Literal["yes", "no"]
    violations: List[str]
    matched_rules: List[str]


@dataclass(frozen=True)
class ScoredCheckResult:
    # AspectResult：单维度结果（S-2-1 约定：空维度不参与整体得分）
    """
    带评分的一致性检查结果。

    score = matched_count / total_count（四维得分的计算单元）。
    """
    consistent: Literal["yes", "no"]
    score: float
    matched_count: int
    total_count: int
    # LayeredCheckResult：四维分层输出（含 aspect_weights 实验权重）
    violations: List[str]
    matched_rules: List[str]
    behaviors: List[BehaviorEvent]


@dataclass(frozen=True)
class AspectResult:
    """
    单个判定维度（四维之一）的结果。

    无检查项的维度 total_count=0 且不参与整体得分。
    """
    consistent: Literal["yes", "no"]
    score: float
    matched_count: int
    total_count: int
    violations: List[str]


@dataclass(frozen=True)
class LayeredCheckResult:
    """
    四维分层判定结果（历史独立版本，运行链路不再引用）。

    与 judge.py 同构：工具调用 / 调用顺序 / 参数 / 资源访问
    四维 + overall_score（有效维度均值，保留 4 位小数）。
    保留本文件用于离线回放与历史记录比对。

    aspect_weights：可选的维度权重（实验用途），缺省等权。
    """
    consistent: Literal["yes", "no"]
    overall_score: float
    tool_call_consistency: AspectResult
    tool_trajectory_consistency: AspectResult
    parameter_consistency: AspectResult
    resource_access_consistency: AspectResult
    violations: List[str]
    matched_rules: List[str]
    behaviors: List[BehaviorEvent]


def _as_list(value: Any) -> List[Any]:
    """
    值归一为列表：None→[]，单值→单元素列表，列表原样。

    Returns:
        列表。
    """
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _normalize_action(action: Any) -> Action:
    """
    动作名归一化（大小写与别名统一）。

    覆盖三类来源：
        · 系统调用名（openat/unlinkat/execve → read/delete/execute）；
        · 语义近义词（access/summarize → read，patch → write）；
        · 网络方向词（fetch/http_get/download → connect）。

    Args:
        # _parse_open_flags：open(2) flags → 动作映射（内核态事件接入用）
        action: 原始动作名。

    Returns:
        归一后的动作名（未知动作原样返回）。
    """
    raw = str(action or "").strip().lower()
    aliases = {
        "open": "read",
        "openat": "read",
        "o_rdonly": "read",
        "read_file": "read",
        "summarize": "read",
        "write_file": "write",
        "patch": "write",
        "o_wronly": "write",
        "o_creat": "create",
        "rename": "write",
        "renameat": "write",
        "unlink": "delete",
        "unlinkat": "delete",
        "rmdir": "delete",
        "rm": "delete",
        "chmod": "setattr",
        "execve": "execute",
        "exec": "execute",
        "fetch": "connect",
        # _normalize_behavior_action：用户态事件与内核态事件（带 flags）的动作归一合流点
        # 网络方向词统一 connect：用户态无法区分 send/receive，方向语义留给内核态
        "request": "connect",
        "http_get": "connect",
        "http_post": "connect",
        "download": "connect",
        "upload": "connect",
    }
    # 未知动作原样返回：判定器对未知动作按字面比对（避免吞掉新动作形态）
    return aliases.get(raw, raw)


def _infer_resource_type(identifier: Any, fallback: Any = None) -> ResourceType:
    """
    按标识推导资源类型。

    显式 type 字段合法 → 直接采用；否则按标识形态推断：
    URL/域名 → network，绝对路径/文件名 → file，其余 → fallback。

    Returns:
        file / tool / network 之一。
    """
    # 显式 type 三值合法白名单：file/tool/network 之外的值不采信、按标识推断
    raw_type = str(fallback or "").strip().lower()
    if raw_type in {"file", "tool", "network"}:
        return raw_type  # type: ignore[return-value]

    ident = str(identifier or "").strip()
    parsed = urlparse(ident)
    # URL 判定五种协议 + 有 netloc 即 network：覆盖 http/https/ftp/ssh/git
    if parsed.scheme in {"http", "https", "ftp", "ssh", "git"} or parsed.netloc:
        return "network"
    # 以 / 或 . 开头视为文件：相对路径与绝对路径统一为 file
    if ident.startswith("/") or ident.startswith("."):
        return "file"
    # 兜底 tool：无法判定形态的标识按工具名处理（与判定器的 fail-safe 取向一致）
    return "tool"


def _parse_open_flags(raw_flags: Any) -> Optional[int]:
    """
    解析 open(2) flags 数值 → 读写动作映射。

    O_RDONLY/O_WRONLY/O_RDWR 及创建标志的组合判定，
    供内核态事件接入时的动作归一。

    Args:
        raw_flags: open(2) 的 flags 数值。

    Returns:
        动作集合（read/write/create）。
    """
    # flags 三形态入口：None→None、int→原值、字符串→解析（0x 十六进制或符号名）
    if raw_flags is None:
        return None
    # int 直通：内核态事件（Tracee）的 flags 常为数值
    if isinstance(raw_flags, int):
        return raw_flags

    text = str(raw_flags).strip()
    if not text:
        return None
    try:
        # 字符串数字解析：int(text, 0) 同时支持十进制与 0x 十六进制
        return int(text, 0)
    except ValueError:
        pass

    flag_value = 0
    matched = False
    # 符号名解析：'O_RDONLY|O_CREAT' 一类文本逐项查 os 模块常量并 OR 合并
    for name in re.split(r"[\s|,+]+", text.upper()):
        if not name:
            continue
        # getattr(os, name) 查常量：O_RDONLY/O_WRONLY/O_CREAT 等由 os 模块提供，跨平台无需硬编码
        value = getattr(os, name, None)
        if isinstance(value, int):
            flag_value |= value
            matched = True
    # 全部符号无法识别返回 None：调用方按无 flags 处理（动作归一降级）
    return flag_value if matched else None


def _normalize_behavior_action(
    action: Any,
    params: Optional[Dict[str, Any]] = None,
) -> Action:
    """
    行为动作归一（含 open flags 融合）。

    事件自带 action 时归一化；内核态事件（params 携带
    open flags）按 flags 推导并合并。

    Returns:
        归一后的动作列表。
    """
    raw = str(action or "").strip().lower()
    # 非 open/openat 动作直接走通用归一表
    if raw not in {"open", "openat"}:
        return _normalize_action(raw)

    # open/openat 专项：从 params 提取 flags 并映射 read/write/create（内核态口径）
    params = params or {}
    raw_flags = (
        params.get("flags")
        if "flags" in params
        else params.get("flag", params.get("open_flags"))
    )
    flags = _parse_open_flags(raw_flags)
    if flags is None:
        return "unknown"
    if flags & os.O_CREAT:
        return "create"

    access_mode = flags & os.O_ACCMODE
    if access_mode in {os.O_WRONLY, os.O_RDWR}:
        return "write"
    if flags & (os.O_APPEND | os.O_TRUNC):
        return "write"
    return "read"


def _glob_pattern_to_regex(pattern: str) -> str:
    """
    通配模式转正则：** 与 * 均映射 .*，其余转义。

    Returns:
        带锚点的正则字符串。
    """
    parts: List[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**", index):
            parts.append(".*")
            index += 2
        elif pattern[index] == "*":
            parts.append(r"[^/]*")
            index += 1
        else:
            parts.append(re.escape(pattern[index]))
            index += 1
    return "^" + "".join(parts) + "$"


def _is_regex_pattern(pattern: str, match_mode: str = "auto") -> bool:
    """
    判断标识是否为 re: 前缀的正则模式。

    Returns:
        True 表示按正则处理。
    """
    if match_mode == "regex":
        return True
    lowered = pattern.lower()
    return lowered.startswith(("regex:", "re:"))


def _strip_regex_prefix(pattern: str) -> str:
    """
    剥除 re: 前缀，取正则正文。

    Returns:
        正则表达式字符串。
    """
    lowered = pattern.lower()
    if lowered.startswith("regex:"):
        return pattern[len("regex:") :]
    if lowered.startswith("re:"):
        return pattern[len("re:") :]
    return pattern


def _match_identifier(actual: str, expected: str, match_mode: str = "auto") -> bool:
    """
    标识匹配三分派：精确 / 通配 / 正则。

    match_mode=exact 精确相等；re: 前缀走全匹配正则；
    含 * ? 走通配；auto 按 IR 声明自动选择。

    Returns:
        True 表示匹配。
    """
    actual = str(actual or "")
    expected = str(expected or "")
    if actual == expected:
        return True

    if match_mode == "exact":
        return False

    if _is_regex_pattern(expected, match_mode):
        pattern = _strip_regex_prefix(expected)
        try:
            return re.fullmatch(pattern, actual) is not None
        except re.error:
            return False

    if match_mode == "glob" or "*" in expected:
        return re.fullmatch(_glob_pattern_to_regex(expected), actual) is not None

    # Prefix-style path matching:
    # If expected ends with "/", treat it as an allowed directory prefix.
    expected_prefix = expected.rstrip("/")
    if expected.endswith("/") and expected_prefix:
        return actual == expected_prefix or actual.startswith(expected_prefix + "/")

    return False


def _glob_param_to_regex(pattern: str) -> str:
    """
    参数值通配模式转正则（** 与 * 均映射 .*，其余转义）。

    Returns:
        带锚点的正则字符串。
    """
    parts: List[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**", index):
            parts.append(".*")
            index += 2
        elif pattern[index] == "*":
            parts.append(".*")
            index += 1
        else:
            parts.append(re.escape(pattern[index]))
            index += 1
    return "^" + "".join(parts) + "$"


def _match_param_value(actual: str, expected: str) -> bool:
    """
    参数值匹配：精确 → 正则 → 通配三段降级。

    Returns:
        True 表示参数合规。
    """
    if actual == expected:
        return True

    if _is_regex_pattern(expected):
        pattern = _strip_regex_prefix(expected)
        try:
            return re.fullmatch(pattern, actual) is not None
        except re.error:
            return False

    if "*" in expected:
        return re.fullmatch(_glob_param_to_regex(expected), actual) is not None

    return False


def _action_allowed(resource_type: ResourceType, event_action: Action, allowed_actions: set[Action]) -> bool:
    """
    动作授权判定（含 fail-close 语义）。

    allowed_actions 为空：资源对象拒绝一切操作（R1 修复），
    工具对象按 invoke 白名单语义放行；
    network 的 connect 事件可被 send/receive 授权覆盖。

    Returns:
        True 表示动作被授权。
    """
    if not allowed_actions:
        return True
    if event_action in allowed_actions:
        return True
    # Some gateway/tool parsers only know that a network connection happened,
    # while the updated IR describes the intent direction as receive/send.
    if resource_type == "network" and event_action == "connect":
        return bool(allowed_actions & {"connect", "receive", "send"})
    return False


def _params_match(expected: Optional[Dict[str, str]], actual: Optional[Dict[str, str]]) -> bool:
    """
    工具参数整体匹配：IR 声明的每个参数都必须存在且值合规。

    IR 未声明参数约束时恒真（参数自由）。

    Returns:
        True 表示参数一致。
    """
    if not expected:
        return True
    actual = actual or {}
    for key, expected_value in expected.items():
        if key not in actual:
            return False
        actual_value = str(actual.get(key))
        expected_text = str(expected_value)
        if not _match_param_value(actual_value, expected_text):
            return False
    return True


def _parse_params(raw_params: Any) -> Optional[Dict[str, str]]:
    """
    参数三态解析：None / dict / [{name, identifier}] 数组。

    统一转为 {参数名: 约束值} 字典。

    Returns:
        归一后的参数字典或 None。
    """
    if not raw_params:
        return None
    if isinstance(raw_params, dict):
        return {str(key): str(value) for key, value in raw_params.items()}
    if isinstance(raw_params, list):
        parsed: Dict[str, str] = {}
        for item in raw_params:
            if isinstance(item, dict) and "name" in item:
                parsed[str(item["name"])] = str(item.get("identifier", item.get("value", "")))
        return parsed or None
    return None


def _parse_object(raw: Dict[str, Any]) -> IRObject:
    """
    单个 IR 对象解析（多键名兼容）。

    identifier 依次尝试 identifier/path/url/domain/host/name/resource；
    type 依次尝试 type/resource_type/kind，未给出时按标识推断。

    Returns:
        IRObject。

    Raises:
        ValueError: 缺少 identifier。
    """
    # type 三键名兼容：type/resource_type/kind 逐个尝试
    resource_type = raw.get("type") or raw.get("resource_type") or raw.get("kind")
    # identifier 九键名兼容：从结构化 IR 到扁平声明的全部历史形态
    # 多键名兼容的代价说明：解析层吸收全部历史形态，判定层只看统一结构
    identifier = (
        raw.get("identifier")
        or raw.get("path")
        or raw.get("url")
        or raw.get("uri")
        or raw.get("endpoint")
        or raw.get("domain")
        or raw.get("host")
        or raw.get("name")
        or raw.get("resource")
    )

    # 缺 identifier 直接拒绝：无法定位资源的对象没有判定意义
    if not identifier:
        raise ValueError(f"IR object missing identifier: {raw}")
    # 显式 type 合法时直接采用，否则按标识形态推断（路径→file、URL→network）
    resource_type = _infer_resource_type(identifier, resource_type)

    # 动作归一：单值/数组双形态统一为归一动作列表
    actions = raw.get("actions", raw.get("action", []))
    normalized_actions = [_normalize_action(a) for a in _as_list(actions)]

    # selinux_rules 透传：判定命中的对象携带其 SELinux 规则作为证据
    rules = raw.get("selinux_rules", raw.get("selinux_rule", []))
    return IRObject(
        type=resource_type,
        identifier=str(identifier),
        actions=normalized_actions,
        params=_parse_params(raw.get("params")),
        selinux_rules=[str(rule) for rule in _as_list(rules)],
        # identifier_match 缺省 auto：按对象声明自动选择匹配模式
        identifier_match=str(raw.get("identifier_match", raw.get("match", "auto"))).lower(),  # type: ignore[arg-type]
    )


# parse_ir_policies 三形态兼容入口：policies 数组 / 裸数组 / 单 policy 扁平体
def parse_ir_policies(raw_ir: Any) -> List[IRPolicy]:
    """
    Accepts the likely group-1 shapes:
      1. {"policies": [{"subject": ..., "objects": [...], "effect": "allow"}]}
      2. [{"subject": ..., "objects": [...], "effect": "allow"}]
      3. {"subject": ..., "resource": ..., "action": ...}
    # 对象内继承用浅拷贝 {**obj, ...}：不污染原始 raw（可重复解析）
    """

    # 形态一：标准 policies 数组（翻译模块当前产物）
    if isinstance(raw_ir, dict) and "policies" in raw_ir:
        raw_policies = raw_ir["policies"]
    # 形态二：裸策略数组（历史中间格式）
    elif isinstance(raw_ir, list):
        raw_policies = raw_ir
    # 形态三：单 policy 扁平体——资源字段提升为单对象策略（最早期格式）
    elif isinstance(raw_ir, dict):
        raw_policies = [
            {
                "subject": raw_ir.get("subject", "default_task"),
                "effect": raw_ir.get("effect", "allow"),
                "objects": [
                    {
                        "type": raw_ir.get("type", raw_ir.get("resource_type")),
                        "identifier": raw_ir.get("identifier", raw_ir.get("resource")),
                        "actions": raw_ir.get("actions", raw_ir.get("action")),
                        "params": raw_ir.get("params"),
                        "selinux_rules": raw_ir.get("selinux_rules", raw_ir.get("selinux_rule")),
                    }
                ],
            }
        ]
    else:
        # 其余类型直接拒绝：IR 必须是对象或数组
        raise ValueError("IR JSON must be an object or a list")

    policies: List[IRPolicy] = []
    for raw_policy in raw_policies:
        # objects 三键名兼容：objects/object/resources
        objects = raw_policy.get("objects", raw_policy.get("object", raw_policy.get("resources", [])))
        parsed_objects: List[IRObject] = []
        for obj in _as_list(objects):
            # 扁平体的动作继承：对象未声明 action 时继承 policy 级 action
            if "actions" not in obj and "action" not in obj and "action" in raw_policy:
                obj = {**obj, "action": raw_policy["action"]}
            # selinux_rules 同样支持 policy 级继承
            if "selinux_rules" not in obj and "selinux_rule" not in obj and "selinux_rules" in raw_policy:
                obj = {**obj, "selinux_rules": raw_policy["selinux_rules"]}
            parsed_objects.append(_parse_object(obj))

        policies.append(
            IRPolicy(
                # subject 缺省 default_task：无名策略仍可参与比对
                subject=str(raw_policy.get("subject", "default_task")),
                objects=parsed_objects,
                effect=raw_policy.get("effect", "allow"),
            )
        )
    return policies


def load_ir_policies(json_path: str | Path) -> List[IRPolicy]:
    """
    从 JSON 文件加载 IR 并解析为策略列表。

    Raises:
        FileNotFoundError: 文件缺失或为空。
    """
    path = Path(json_path)
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(f"{path} is empty or missing")
    return parse_ir_policies(json.loads(path.read_text(encoding="utf-8")))


# _evaluate_event：单事件授权评估（线性扫描版，与 judge 同语义、无哈希索引）
def _evaluate_event(
    event: BehaviorEvent,
    allow_policies: Sequence[IRPolicy],
) -> tuple[bool, List[str], List[str]]:
    # 返回三元组（是否匹配/违规明细/命中规则）：判定主循环的核心契约
    """
    单个行为事件的授权评估（线性扫描版，无哈希索引）。

    历史实现保留：判定语义与 judge._evaluate_event 一致，
    但未做 P-2-1 性能优化（10 倍规模下耗时较高）。

    Returns:
        (是否匹配, 违规明细, 命中规则) 三元组。
    """
    # unresolved 事件直接记违规但不匹配授权：语义不明即视为不可采信（宁严不滥）
    event_action = _normalize_behavior_action(event.action, event.params)
    # unknown 动作同样不可采信：避免推导缺口被误判为合规
    if event.inference_status == "unresolved" or event_action == "unknown":
        return (
            False,
            [
                f"resource semantics unresolved: {event.identifier}, "
                f"reason={event.inference_reason or 'insufficient action context'}"
            ],
            [],
        )
    # 线性双层循环：policy → object（历史版无哈希索引；judge.py 为性能优化版）
    matched_rules: List[str] = []

    # 类型不匹配跳过：file 对象只比 file 事件（对象池按类型自然分桶）
    for policy in allow_policies:
        for obj in policy.objects:
            if obj.type != event.resource_type:
                continue

            # 标识匹配三种模式按对象声明分派（auto/glob/regex/exact）
            if not _match_identifier(event.identifier, obj.identifier, obj.identifier_match):
                continue

            # 工具参数核对不匹配即违规返回：一条事件一个结论（参数违规优先报出）
            if event.resource_type == "tool" and not _params_match(obj.params, event.params):
                return (
                    False,
                    [
                        f"tool param mismatch: {event.identifier}, "
                        f"expected={obj.params}, actual={event.params}"
                    ],
                    [],
                )

            # 有 actions 才核对动作：空 actions 走 fail-close（在 _action_allowed 内处理）
            if obj.actions:
                allowed_actions = {_normalize_action(action) for action in obj.actions}
                if not _action_allowed(event.resource_type, event_action, allowed_actions):
                    return (
                        False,
                        [
                            f"action over-privilege: {event_action} on {event.identifier}, "
                            f"allowed={sorted(allowed_actions)}"
                        ],
                        [],
                    )

            # 全部通过则收集 SELinux 规则证据并返回命中
            matched_rules.extend(obj.selinux_rules)
            return True, [], matched_rules

    # 全部对象都不匹配：记「资源超出 IR 授权范围」违规（含类型与标识，可定位）
    return False, [f"resource out of IR allow scope: {event.resource_type}:{event.identifier}"], []


def _aspect_result(
    matched_count: int,
    total_count: int,
    violations: List[str],
) -> AspectResult:
    """
    组装单维度结果：得分 = 命中数 / 检查数（空维度得 1.0）。

    Returns:
        AspectResult。
    """
    # 得分计算：matched/total 四舍五入 4 位（与阈值 0.5 的比较口径一致）
    score = 1.0 if total_count == 0 else round(matched_count / total_count, 4)
    return AspectResult(
        # consistent 由违规明细驱动：有违规即 no，不受得分高低影响
        consistent="no" if violations else "yes",
        score=score,
        matched_count=matched_count,
        total_count=total_count,
        violations=violations,
    )


# 扁平判定（旧入口）：每个行为必须被任一 allow 策略覆盖
def Resource_Consistency_Check(
    ir_policies: Sequence[IRPolicy],
    behaviors: Sequence[BehaviorEvent],
) -> CheckResult:
    """
    Input:
      ir_policies: first-group IR parsed into IRPolicy.
      behaviors: observed user-space behavior events.

    Output:
      CheckResult.consistent is "yes" if every behavior is covered by an allow policy.
      Otherwise it is "no", with concrete violation reasons.
    """

    # 扁平判定的主循环：逐事件评估，违规收集、规则收集，无得分计算
    violations: List[str] = []
    matched_rules: List[str] = []
    # 只取 allow 策略（同 Layered/Scored 入口）：deny 在生成侧已收敛
    allow_policies = [policy for policy in ir_policies if policy.effect == "allow"]

    for event in behaviors:
        matched, event_violations, event_rules = _evaluate_event(event, allow_policies)
        if not matched:
            violations.extend(event_violations)
        matched_rules.extend(event_rules)

    # 扁平输出：consistent + violations + matched_rules 三字段（最早期 API 契约）
    return CheckResult(
        consistent="no" if violations else "yes",
        violations=violations,
        matched_rules=sorted(set(matched_rules)),
    )


def _normalize_params_dict(raw: Any) -> Optional[Dict[str, str]]:
    """
    网关参数归一：dict 转字符串字典，其余降级为 _raw 单键。

    Returns:
        {参数名: 值} 字典或 None。
    """
    # None→None：无参数声明的工具事件（参数维度恒真）
    if raw is None:
        return None
    if isinstance(raw, dict):
        # dict 参数全量字符串化：参数维度比对的统一形态
        return {str(k): str(v) for k, v in raw.items()}
    # 非 dict 降级 _raw：单字符串参数（如裸命令）也能进入参数比对
    return {"_raw": str(raw)}


def _gateway_content_to_text(content: Any) -> str:
    """
    消息内容文本化：字符串原样，多段列表逐段取 text 拼接。

    Returns:
        纯文本。
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    # 多段内容只取 text 块：image/tool_result 块不参与时间戳与结果判定
    if isinstance(content, list):
        out: List[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                out.append(str(item.get("text", "")))
        # 多段以换行拼接：保留分段结构便于按行解析
        return "\n".join(out)
    return str(content)


def _extract_messages(gateway_trace: Any) -> List[Dict[str, Any]]:
    """
    从网关轨迹提取消息序列（tool_calls / tool_result 兼容）。

    Returns:
        消息 dict 列表。
    """
    # 消息提取三形态：裸列表 / {messages} / {body.messages}——网关日志的三个历史层
    if isinstance(gateway_trace, list):
        return [msg for msg in gateway_trace if isinstance(msg, dict)]
    if isinstance(gateway_trace, dict):
        if isinstance(gateway_trace.get("messages"), list):
            return [msg for msg in gateway_trace["messages"] if isinstance(msg, dict)]
        body = gateway_trace.get("body")
        if isinstance(body, dict) and isinstance(body.get("messages"), list):
            return [msg for msg in body["messages"] if isinstance(msg, dict)]
    # 三形态全部不匹配直接抛错：轨迹结构错误应当暴露而非静默返回空
    raise ValueError("gateway_trace must be a messages list or an object containing body.messages")


def _extract_trace_metadata(gateway_trace: Any) -> Dict[str, Any]:
    """
    提取网关轨迹的轮次元信息（时间戳/round_id 等）。

    Returns:
        轮次元信息 dict。
    """
    if not isinstance(gateway_trace, dict):
        return {}

    # body 二级查找：新版网关把轮次字段嵌在 body 内
    body = gateway_trace.get("body")
    body = body if isinstance(body, dict) else {}
    # round_id/timestamp 双层查找：外层优先、body 兜底
    round_id = gateway_trace.get("round_id") or body.get("round_id")
    timestamp = gateway_trace.get("timestamp") or body.get("timestamp")
    # 元信息带 source 标记：审计可区分「哪来的 round_id」（显式/轨迹/派生）
    return {
        "round_id": round_id,
        "round_id_source": "trace_field" if round_id is not None else None,
        "timestamp": timestamp,
        "timestamp_source": "trace_field" if timestamp is not None else None,
        # 进程上下文四字段透传：内核态对齐（容器/沙箱标识）的预留证据
        "pid": gateway_trace.get("pid") or body.get("pid"),
        "parent_pid": gateway_trace.get("parent_pid") or body.get("parent_pid"),
        "container_id": gateway_trace.get("container_id") or body.get("container_id"),
        "sandbox_id": gateway_trace.get("sandbox_id") or body.get("sandbox_id"),
    }


def _timestamp_from_user_content(content: Any) -> Optional[str]:
    """
    从用户消息内容提取时间戳前缀。

    Returns:
        # 时间戳正则的兼容范围：[Wed 2026-07-01 10:30:45 GMT+8] 与分钟级变体均可解析
        (时间戳文本, 去前缀正文) 或 (None, 原文)。
    """
    # 文本化后正则抽取时间戳：兼容 [Tue 2026-06-30 01:04 GMT+8] 三种变体（秒可省）
    text = _gateway_content_to_text(content)
    match = re.search(
        r"\[[A-Za-z]{3}\s+"
        r"(?P<date>\d{4}-\d{2}-\d{2})\s+"
        r"(?P<time>\d{2}:\d{2})(?::(?P<second>\d{2}))?\s+"
        r"GMT(?P<offset>[+-]\d{1,2})\]",
        text,
    )
    if not match:
        return None

    # 偏移独立解析：GMT+8 → +08:00 时区，时间戳全链路可比
    offset_hours = int(match.group("offset"))
    tz = timezone(timedelta(hours=offset_hours))
    second = match.group("second") or "00"
    parsed = datetime.strptime(
        f"{match.group('date')} {match.group('time')}:{second}",
        "%Y-%m-%d %H:%M:%S",
    ).replace(tzinfo=tz)
    return parsed.isoformat()

# gateway_messages_to_behaviors：网关轨迹还原（本文件独有，含轮次元信息提取）

def _user_round_metadata(
    message: Dict[str, Any],
    trace_metadata: Dict[str, Any],
    round_index: int,
) -> Dict[str, Any]:
    """
    组装用户轮次的元信息（round 起点）。

    Returns:
        轮次元信息 dict。
    """
    # round_id 三来源优先级：消息显式字段 > 轨迹字段 > 序号派生（derived-round-0001）
    explicit_round_id = message.get("round_id")
    trace_round_id = trace_metadata.get("round_id")
    if explicit_round_id is not None:
        round_id = str(explicit_round_id)
        round_id_source = "message_field"
    elif trace_round_id is not None:
        round_id = str(trace_round_id)
        round_id_source = "trace_field"
    else:
        round_id = f"derived-round-{round_index:04d}"
        round_id_source = "derived_sequence"

    # 时间戳三来源优先级：显式字段 > 轨迹字段 > 正文前缀分钟级
    explicit_timestamp = message.get("timestamp")
    trace_timestamp = trace_metadata.get("timestamp")
    content_timestamp = _timestamp_from_user_content(message.get("content"))
    if explicit_timestamp is not None:
        timestamp = str(explicit_timestamp)
        timestamp_source = "message_field"
    elif trace_timestamp is not None:
        timestamp = str(trace_timestamp)
        timestamp_source = "trace_field"
    elif content_timestamp is not None:
        timestamp = content_timestamp
        timestamp_source = "message_content_minute"
    else:
        timestamp = None
        timestamp_source = None

    # 元信息合并 trace_metadata：后续全部行为事件继承（round 归属与时间锚点）
    return {
        **trace_metadata,
        "round_id": round_id,
        "round_id_source": round_id_source,
        "timestamp": timestamp,
        "timestamp_source": timestamp_source,
    }


def _assistant_event_metadata(
    message: Dict[str, Any],
    current_metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """
    组装 assistant 消息的元信息（工具调用起点）。

    Returns:
        更新后的元信息。
    """
    # assistant 元信息增量更新：仅覆盖出现的字段，其余沿用用户轮次的锚点
    metadata = dict(current_metadata)
    if message.get("round_id") is not None:
        metadata["round_id"] = str(message["round_id"])
        metadata["round_id_source"] = "message_field"
    if message.get("timestamp") is not None:
        metadata["timestamp"] = str(message["timestamp"])
        metadata["timestamp_source"] = "message_field"
    return metadata


def _tool_result_metadata(messages: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Optional[str]]]:
    """
    从 tool_result 消息提取结果元信息。

    Returns:
        更新后的元信息。
    """
    # 结果元信息按 tool_call_id 建索引：一次遍历产出，调用侧 O(1) 查询
    results: Dict[str, Dict[str, Optional[str]]] = {}

    for message in messages:
        if message.get("role") != "tool" or not message.get("tool_call_id"):
            continue

        tool_call_id = str(message["tool_call_id"])
        content = _gateway_content_to_text(message.get("content")).strip()
        outcome: Literal["success", "error", "pending", "unknown"] = "unknown"
        detail: Optional[str] = None

        # 结果判定四级：error/failed→error；pending/approval→pending；合法 dict→success；其余 unknown
        if content:
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                payload = None

            # 结构化结果优先：status/error 字段判定比文本匹配可靠
            if isinstance(payload, dict):
                status = str(payload.get("status", "")).lower()
                if status in {"error", "failed", "failure"} or payload.get("error"):
                    outcome = "error"
                    detail = str(payload.get("error") or payload.get("message") or status)
                elif status in {"pending", "approval_required"}:
                    outcome = "pending"
                    detail = str(payload.get("message") or status)
                else:
                    outcome = "success"
            # 纯文本结果兜底：非 JSON 结果按前缀分类
            elif content.lower().startswith("approval required"):
                outcome = "pending"
                detail = content.splitlines()[0]
            else:
                outcome = "success"

        results[tool_call_id] = {
            "outcome": outcome,
            "outcome_detail": detail,
        }

    return results


def _resolve_exec_path(raw_path: str, workdir: Optional[str]) -> str:
    """
    exec 相对路径解析：按工作目录拼绝对路径，~ 展开保持原样。

    Returns:
        解析后的路径。
    """
    if not raw_path:
        return str(Path(workdir or "."))
    path = Path(raw_path)
    if path.is_absolute():
        return str(path)
    if workdir:
        return str(Path(workdir) / path)
    return str(path)


def _looks_like_path(token: str) -> bool:
    """
    token 是否形似文件路径（绝对路径/常见扩展名启发）。

    Returns:
        True 视为路径。
    """
    if not token or token.startswith("-"):
        return False
    return (
        "/" in token
        or token in {".", ".."}
        or token.endswith(
            (
                ".md",
                ".txt",
                ".json",
                ".py",
                ".csv",
                ".pdf",
                ".doc",
                ".docx",
                ".xls",
                ".xlsx",
                ".yaml",
                ".yml",
                # Scored 入口（历史版）：单维结论与分层判定一致（F-2-5 ⑩ 兼容口径）
                ".xml",
                ".sh",
                ".c",
                ".cc",
                ".cpp",
                ".h",
            )
        )
    )


def _shell_complexity_reason(command: str, tokens: Sequence[str]) -> Optional[str]:
    """
    评估 shell 命令的复杂度并给出说明（管道/串联/嵌套）。

    复杂命令的置信状态降级依据。

    Returns:
        说明字符串或 None。
    """
    # 复杂度四线索：多行/管道串联/重定向/变量展开——每命中一条即降置信
    if "\n" in command:
        return "multi-line shell command"
    if any(token in {"|", "||", "&&", ";", "&"} for token in tokens):
        return "shell pipeline or command chaining"
    if any(token in {">", ">>", "<", "<<", "2>", "2>>"} for token in tokens):
        return "shell redirection"
    if re.search(r"`[^`]+`|\$\([^)]*\)|\$\{[^}]+\}|\$[A-Za-z_][A-Za-z0-9_]*", command):
        return "shell variable or command expansion"
    # 嵌套脚本线索：解释器 + -c 组合（sh -c / python -c 等）
    if tokens and tokens[0] in {"sh", "bash", "zsh", "python", "python3", "node"} and "-c" in tokens:
        return "nested script execution"
    # 不复杂返回 None：简单命令的置信保持 resolved，语义推导可直接采信
    return None


# _infer_exec_behaviors 是网关侧 exec 推导的入口：command → analyze_shell_command → 事件
def _infer_exec_behaviors(
    args: Dict[str, Any],
    *,
    source_tool: str,
    tool_call_id: Optional[str],
    trace_metadata: Dict[str, Any],
    outcome_metadata: Dict[str, Optional[str]],
) -> List[BehaviorEvent]:
    """
    从 exec 工具参数推导行为：命令文本 → 路径/网络资源访问。

    与 shell_command_semantics 的六类行为口径对齐。

    Returns:
        BehaviorEvent 列表。
    """
    # 空命令直接返回：exec 无 command 参数时不产出任何行为（避免伪事件）
    command = str(args.get("command", "")).strip()
    if not command:
        # Layered 入口（历史版）：与 judge.py 同构 + 可选维度权重
        return []

    # workdir 参与相对路径解析：与 judge 的 _resolve_exec_path 同口径
    workdir = str(args.get("workdir")) if args.get("workdir") else None
    # 复用 shell_command_semantics：六类行为推导单点收敛，两模块不重复实现
    analysis = analyze_shell_command(command, workdir=workdir)
    events: List[BehaviorEvent] = []
    for behavior in analysis.behaviors:
        # resource_kind 三分支映射：network→network、process→tool、其余（file/directory）→file
        if behavior.resource_kind == "network":
            resource_type: ResourceType = "network"
            resource_kind: ResourceKind = "network"
        elif behavior.resource_kind == "process":
            resource_type = "tool"
            resource_kind = "process"
        else:
            resource_type = "file"
            resource_kind = behavior.resource_kind

        # 行为事件组装：identifier/action/置信/reason/outcome 全量携带——一次调用多行为（多路径命令）
        events.append(
            BehaviorEvent(
                resource_type=resource_type,
                identifier=behavior.identifier,
                action=behavior.action,
                params=_normalize_params_dict(args),
                resource_kind=resource_kind,
                inference_status=behavior.inference_status,
                inference_reason=behavior.reason,
                source="gateway",
                source_tool=source_tool,
                tool_call_id=tool_call_id,
                outcome=outcome_metadata.get("outcome", "unknown"),  # type: ignore[arg-type]
                outcome_detail=outcome_metadata.get("outcome_detail"),
                # trace_metadata 展开继承：每个推导事件都带轮次锚点（round 归属不丢失）
                **trace_metadata,
            )
        )
    # 返回推导事件列表：并入 behaviors 后参与四维判定
    return events


# 网关轨迹 → 行为列表：含轮次元信息提取（本文件独有的网关侧适配层）
def gateway_messages_to_behaviors(gateway_trace: Any) -> List[BehaviorEvent]:
    """
    Convert gateway-side messages into BehaviorEvent records.
    Each assistant tool call produces a tool-level event. File and shell tools
    may additionally produce resource-level events inferred from arguments.
    """

    # 网关轨迹还原三步：提取消息 → 提取轨迹元信息 → 提取工具结果元信息
    messages = _extract_messages(gateway_trace)
    trace_metadata = _extract_trace_metadata(gateway_trace)
    tool_results = _tool_result_metadata(messages)
    behaviors: List[BehaviorEvent] = []
    current_metadata = dict(trace_metadata)
    round_index = 0

    # file_action_map：工具名 → 资源动作映射（read/read_file→read，edit/patch→write 等）
    file_action_map = {
        "read": "read",
        "read_file": "read",
        "open": "open",
        "openat": "openat",
        "write": "write",
        "write_file": "write",
        "edit": "write",
        "patch": "write",
        "apply_patch": "write",
        "delete": "delete",
        "rm": "delete",
        "unlink": "delete",
    }

    # 逐消息处理：user 消息开新轮（round_index 递增），assistant 消息展开工具调用
    for msg in messages:
        if msg.get("role") == "user":
            round_index += 1
            current_metadata = _user_round_metadata(
                msg,
                trace_metadata,
                round_index,
            )
            continue
        if msg.get("role") != "assistant":
            continue
        event_metadata = _assistant_event_metadata(msg, current_metadata)
        # tool_calls 逐项展开：每个调用至少产出一条 tool 级事件
        for tool_call in msg.get("tool_calls", []) or []:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function") or {}
            tool_name = str(function.get("name", "")).strip()
            if not tool_name:
                continue

            # arguments 三态解析：JSON 字符串→dict、dict 原样、非法文本→{_raw} 保留原文
            raw_args = function.get("arguments")
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError:
                    args = {"_raw": raw_args}
            elif isinstance(raw_args, dict):
                args = raw_args
            else:
                args = {}

            # 归一工具名只用于映射判定，事件 identifier 保留原始名（判定器对名匹配）
            normalized_tool = tool_name.lower()
            # 路径参数五键名启发：path/file/target
            path = args.get("path") or args.get("file") or args.get("target")
            # 网络参数六键名启发：url/uri/endpoint/domain/host/query
            network_identifier = (
                args.get("url")
                or args.get("uri")
                or args.get("endpoint")
                or args.get("domain")
                or args.get("host")
                or args.get("query")
            )
            # tool_call_id 关联结果元信息：outcome/error 语义附加到行为事件
            tool_call_id = str(tool_call.get("id")) if tool_call.get("id") else None
            outcome_metadata = tool_results.get(
                tool_call_id or "",
                {"outcome": "unknown", "outcome_detail": None},
            )

            # tool 级事件必产出：动作固定 invoke，参数归一为字符串字典
            behaviors.append(
                BehaviorEvent(
                    resource_type="tool",
                    identifier=tool_name,
                    action="invoke",
                    params=_normalize_params_dict(args),
                    source="gateway",
                    source_tool=tool_name,
                    tool_call_id=tool_call_id,
                    outcome=outcome_metadata.get("outcome", "unknown"),  # type: ignore[arg-type]
                    outcome_detail=outcome_metadata.get("outcome_detail"),
                    **event_metadata,
                )
            )

            # 文件类工具且有路径时附加资源级事件：动作按映射表推导
            if normalized_tool in file_action_map and path:
                # EISDIR 错误修正 resource_kind：错误详情反推目录语义
                resource_kind: Literal["file", "directory", "unknown"] = "file"
                if (
                    outcome_metadata.get("outcome") == "error"
                    and "EISDIR" in str(outcome_metadata.get("outcome_detail") or "")
                ):
                    resource_kind = "directory"

                # 动作归一（含 open flags 融合）：用户态动作名与内核态 flags 在此合流
                action = _normalize_behavior_action(
                    file_action_map[normalized_tool],
                    args,
                )
                # 不可识别动作标 unresolved 并留 reason：宁缺毋滥，判定器不消费不确定证据
                inference_status: Literal["resolved", "partial", "unresolved"] = (
                    "unresolved" if action == "unknown" else "resolved"
                )
                # 资源级事件携带完整上下文：params/kind/inference_status/outcome 一次成型
                behaviors.append(
                    BehaviorEvent(
                        resource_type="file",
                        identifier=str(path),
                        action=action,
                        params=_normalize_params_dict(args),
                        resource_kind=resource_kind,
                        inference_status=inference_status,
                        inference_reason=(
                            "open/openat flags missing or unsupported"
                            if inference_status == "unresolved"
                            else None
                        ),
                        source="gateway",
                        source_tool=tool_name,
                        tool_call_id=tool_call_id,
                        outcome=outcome_metadata.get("outcome", "unknown"),  # type: ignore[arg-type]
                        outcome_detail=outcome_metadata.get("outcome_detail"),
                        **event_metadata,
                    )
                )
                continue

            # 网络类工具集合：web_search/web_fetch/browser/playwright/curl/wget 均记 connect
            if normalized_tool in {"web_search", "web_fetch", "browser", "playwright", "curl", "wget"}:
                behaviors.append(
                    BehaviorEvent(
                        resource_type="network",
                        # 无显式目标时以工具名为标识：不漏报外联，置信降 partial
                        identifier=str(network_identifier or tool_name),
                        action="connect",
                        params=_normalize_params_dict(args),
                        resource_kind="network",
                        # 网络事件置信双态：有目标 resolved、无目标 partial（reason 记录差异依据）
                        inference_status="resolved" if network_identifier else "partial",
                        inference_reason=(
                            "network target from tool arguments"
                            if network_identifier
                            else "network-capable tool without explicit target"
                        ),
                        source="gateway",
                        source_tool=tool_name,
                        tool_call_id=tool_call_id,
                        outcome=outcome_metadata.get("outcome", "unknown"),  # type: ignore[arg-type]
                        outcome_detail=outcome_metadata.get("outcome_detail"),
                        **event_metadata,
                    )
                )
                continue

            # exec/bash/shell 走命令语义推导：复用 _infer_exec_behaviors 的六类口径
            if normalized_tool in {"exec", "bash", "shell"}:
                inferred_behaviors = _infer_exec_behaviors(
                    args,
                    source_tool=tool_name,
                    tool_call_id=tool_call_id,
                    trace_metadata=event_metadata,
                    outcome_metadata=outcome_metadata,
                )
                # 推导产物直接并入行为列表：exec 一次调用可能产出多个资源事件（多路径/多目标）
                if inferred_behaviors:
                    behaviors.extend(inferred_behaviors)

    # 返回全部行为事件：tool 级 + 资源级（文件/网络/exec 推导）混合列表
    return behaviors


# 评分判定（兼容入口）：结果与分层判定的单维结论一致
def Resource_Consistency_Check_Scored(
    ir_input: Sequence[IRPolicy] | str | Path | Dict[str, Any] | List[Any],
    behavior_input: Sequence[BehaviorEvent] | Dict[str, Any] | List[Any],
) -> ScoredCheckResult:
    """
    # Scored 入口的输入形态自适应与 Layered 相同：文件/对象/裸结构均可
    Baseline entrypoint for task-1:
    - input 1: IR JSON / parsed IR policies
    - input 2: BehaviorEvent list or gateway messages/body.messages
    - output : yes/no + score + violations
    """

    # IR 三形态入口：文件路径（load）→ IRPolicy 序列（直用）→ 裸结构（解析）
    if isinstance(ir_input, (str, Path)):
        ir_policies = load_ir_policies(ir_input)
    elif ir_input and isinstance(ir_input, Sequence) and isinstance(ir_input[0], IRPolicy):  # type: ignore[index]
        ir_policies = list(ir_input)  # type: ignore[arg-type]
    else:
        ir_policies = parse_ir_policies(ir_input)

    # 行为两形态入口：dict 走网关还原 → BehaviorEvent 序列直用 → 其余按网关轨迹还原
    if isinstance(behavior_input, dict):
        behaviors = gateway_messages_to_behaviors(behavior_input)
    elif behavior_input and isinstance(behavior_input, Sequence) and isinstance(behavior_input[0], BehaviorEvent):  # type: ignore[index]
        behaviors = list(behavior_input)  # type: ignore[arg-type]
    else:
        behaviors = gateway_messages_to_behaviors(behavior_input)

    # 只取 allow 策略：deny 语义在策略库生成侧已处理（deny-wins），判定侧无 deny 比对
    allow_policies = [policy for policy in ir_policies if policy.effect == "allow"]
    violations: List[str] = []
    matched_rules: List[str] = []
    matched_count = 0

    # 线性逐事件评估（无哈希索引）：历史版保持简单优先，judge.py 为性能优化版
    for event in behaviors:
        matched, event_violations, event_rules = _evaluate_event(event, allow_policies)
        if matched:
            matched_count += 1
        else:
            violations.extend(event_violations)
        matched_rules.extend(event_rules)

    total_count = len(behaviors)
    # 得分 = 命中数/检查数（四舍五入 4 位）：空行为集得 1.0（S-2-1 ② 约定）
    score = 1.0 if total_count == 0 else round(matched_count / total_count, 4)
    return ScoredCheckResult(
        consistent="no" if violations else "yes",
        score=score,
        matched_count=matched_count,
        total_count=total_count,
        violations=violations,
        # matched_rules 去重排序：证据链以稳定顺序输出
        matched_rules=sorted(set(matched_rules)),
        behaviors=behaviors,
    )


# 四维分层判定入口（历史版）：与 judge.py 同构，另支持维度权重实验
def Resource_Consistency_Check_Layered(
    ir_input: Sequence[IRPolicy] | str | Path | Dict[str, Any] | List[Any],
    behavior_input: Sequence[BehaviorEvent] | Dict[str, Any] | List[Any],
    # aspect_weights：四维加权实验入口，缺省 None 即等权（与 judge.py 行为一致）
    aspect_weights: Optional[Dict[str, float]] = None,
) -> LayeredCheckResult:
    """
    Layered consistency output for task-1:
    1. tool call consistency
    2. tool trajectory consistency
    3. parameter consistency
    4. resource access consistency
    5. overall consistency score
    """

    # Layered 的 IR/行为形态自适应与 Scored 一致：两个入口共享同一套适配规则
    if isinstance(ir_input, (str, Path)):
        ir_policies = load_ir_policies(ir_input)
    elif ir_input and isinstance(ir_input, Sequence) and isinstance(ir_input[0], IRPolicy):  # type: ignore[index]
        ir_policies = list(ir_input)  # type: ignore[arg-type]
    else:
        ir_policies = parse_ir_policies(ir_input)

    if isinstance(behavior_input, dict):
        # 行为还原在入口完成一次：四维判定循环内不再重复解析
        behaviors = gateway_messages_to_behaviors(behavior_input)
    elif behavior_input and isinstance(behavior_input, Sequence) and isinstance(behavior_input[0], BehaviorEvent):  # type: ignore[index]
        behaviors = list(behavior_input)  # type: ignore[arg-type]
    else:
        behaviors = gateway_messages_to_behaviors(behavior_input)

    # allow 策略展平为对象池：四维判定共用（工具白名单与资源对象都来源于此）
    allow_policies = [policy for policy in ir_policies if policy.effect == "allow"]
    all_objects = [obj for policy in allow_policies for obj in policy.objects]
    # 工具对象单独成池：维度一/三只对工具对象比对
    allowed_tool_objects = [obj for obj in all_objects if obj.type == "tool"]

    # 事件分组：tool 事件走白名单+参数两维，资源事件走覆盖判定维
    tool_events = [event for event in behaviors if event.resource_type == "tool"]
    resource_events = [event for event in behaviors if event.resource_type != "tool"]

    matched_rules: List[str] = []
    overall_violations: List[str] = []

    tool_call_matched = 0
    tool_call_violations: List[str] = []
    # 维度一 工具调用一致性：白名单内再看动作授权（invoke 语义，fail-close）
    for event in tool_events:
        matched = False
        event_violation = False
        for obj in allowed_tool_objects:
            if not _match_identifier(event.identifier, obj.identifier, obj.identifier_match):
                continue
            # 动作越权即记违规并停止该事件的匹配循环（一个事件一条结论）
            allowed_actions = {_normalize_action(action) for action in obj.actions}
            if not _action_allowed(
                event.resource_type,
                _normalize_behavior_action(event.action, event.params),
                allowed_actions,
            ):
                # 违规明细带 allowed 全集：审计可直接看出「该工具允许的动作是什么」
                tool_call_violations.append(
                        f"tool action over-privilege: {event.action} on {event.identifier}, allowed={sorted(allowed_actions)}"
                )
                matched = True
                event_violation = True
                break
            matched = True
            matched_rules.extend(obj.selinux_rules)
            break
        # matched 且未越权才计入命中：越权事件不得贡献正向得分
        if matched and not event_violation:
            tool_call_matched += 1
        # 白名单外工具记越权违规（S-1-1 的判定器侧视角）
        elif not matched:
            tool_call_violations.append(f"tool out of IR allow scope: {event.identifier}")

    parameter_matched = 0
    parameter_total = 0
    parameter_violations: List[str] = []
    # 维度三 参数一致性：仅对白名单内工具核参（白名单外由维度一报告）
    for event in tool_events:
        # first-match 语义：同名多对象时取声明序首个（与 judge 的索引语义一致）
        matched_obj = next(
            (
                obj
                for obj in allowed_tool_objects
                if _match_identifier(event.identifier, obj.identifier, obj.identifier_match)
            ),
            None,
        )
        if matched_obj is None:
            continue
        # 参数计数只统计进入核对的工具：白名单外工具不虚增维度三的分母
        parameter_total += 1
        if _params_match(matched_obj.params, event.params):
            parameter_matched += 1
        else:
            parameter_violations.append(
                f"tool param mismatch: {event.identifier}, expected={matched_obj.params}, actual={event.params}"
            )

    # 维度四 资源访问一致性：文件/网络事件的授权覆盖检查
    resource_matched = 0
    resource_violations: List[str] = []
    for event in resource_events:
        # 复用 _evaluate_event 的三段判定（标识匹配→参数→动作）
        matched, event_violations, event_rules = _evaluate_event(event, allow_policies)
        if matched:
            resource_matched += 1
            matched_rules.extend(event_rules)
        else:
            resource_violations.extend(event_violations)

    # 维度二 工具调用顺序一致性：期望序为可选集，实际序须是保序子序列
    expected_tool_order = [obj.identifier for obj in allowed_tool_objects]
    observed_tool_order = [event.identifier for event in tool_events]
    # 双指针推进：expected 指针只前进不回退——Agent 可少调用不可乱序
    order_idx = 0
    trajectory_matched = 0
    for observed in observed_tool_order:
        while order_idx < len(expected_tool_order) and expected_tool_order[order_idx] != observed:
            order_idx += 1
        if order_idx < len(expected_tool_order):
            trajectory_matched += 1
            order_idx += 1
    trajectory_violations: List[str] = []
    # 部分乱序即整维记一条违规（明细含两个序列的完整对照）
    if observed_tool_order and trajectory_matched != len(observed_tool_order):
        trajectory_violations.append(
            f"tool trajectory mismatch: expected_order={expected_tool_order}, observed_order={observed_tool_order}"
        )

    # 四维结果组装：每维 {consistent, score, matched, total, violations}
    tool_call_result = _aspect_result(tool_call_matched, len(tool_events), tool_call_violations)
    trajectory_result = _aspect_result(trajectory_matched, len(observed_tool_order), trajectory_violations)
    parameter_result = _aspect_result(parameter_matched, parameter_total, parameter_violations)
    resource_result = _aspect_result(resource_matched, len(resource_events), resource_violations)

    # 权重合并：默认等权表 + 调用方覆盖（实验用），零权重维度从违规汇总剔除
    weights = {**DEFAULT_ASPECT_WEIGHTS, **(aspect_weights or {})}
    active_violation_parts = [
        ("tool_call", tool_call_result),
        ("tool_trajectory", trajectory_result),
        ("parameter", parameter_result),
        ("resource_access", resource_result),
    ]
    # 违规汇总按权重过滤：被实验置零的维度不触发整体异常
    for name, result in active_violation_parts:
        if result.violations and weights.get(name, 0.0) > 0:
            overall_violations.extend(result.violations)

    weighted_parts = [
        ("tool_call", tool_call_result),
        ("tool_trajectory", trajectory_result),
        ("parameter", parameter_result),
        ("resource_access", resource_result),
    ]
    # 加权得分 = Σ(weight_i × score_i) / Σ(weight_i)：仅统计有检查项且权重>0 的维度
    weighted_scores = [
        weights[name] * result.score
        for name, result in weighted_parts
        if result.total_count > 0 and weights.get(name, 0.0) > 0
    ]
    weight_sum = sum(
        weights[name]
        for name, result in weighted_parts
        if result.total_count > 0 and weights.get(name, 0.0) > 0
    )
    # 全部维度为空（或权重和为 0）时得分 1.0：与 judge 的空轮次约定一致
    overall_score = 1.0 if weight_sum == 0 else round(sum(weighted_scores) / weight_sum, 4)

    # 组装返回：consistent 由违规汇总驱动（任一维度违规即异常）
    # 本入口为历史版本：与 judge.py 的判定语义一致，差异仅剩（1）无哈希索引（2）支持权重实验
    return LayeredCheckResult(
        consistent="no" if overall_violations else "yes",
        overall_score=overall_score,
        tool_call_consistency=tool_call_result,
        tool_trajectory_consistency=trajectory_result,
        parameter_consistency=parameter_result,
        resource_access_consistency=resource_result,
        violations=overall_violations,
        # matched_rules 排序去重：证据链稳定输出；behaviors 回带供上层复现
        matched_rules=sorted(set(matched_rules)),
        behaviors=behaviors,
    )


def layered_result_to_dict(result: LayeredCheckResult) -> Dict[str, Any]:
    """
    分层结果转 dict（JSON 序列化用）。

    Returns:
        嵌套 dict。
    """
    return asdict(result)


def demo_behaviors() -> Dict[str, List[BehaviorEvent]]:
    """
    内置演示行为样本（自测与示例用）。

    Returns:
        BehaviorEvent 列表。
    """
    return {
        "yes_case": [
            BehaviorEvent("file", "/workspace/report/ref.pdf", "read"),
            BehaviorEvent("file", "/workspace/report/draft.md", "write"),
        ],
        "no_case": [
            BehaviorEvent("file", "/workspace/report/ref.pdf", "write"),
            BehaviorEvent("file", "/etc/passwd", "read"),
        ],
    }


if __name__ == "__main__":
    ir = load_ir_policies("第一组json最终版.json")
    for case_name, behaviors in demo_behaviors().items():
        result = Resource_Consistency_Check(ir, behaviors)
        print(f"{case_name}: {result.consistent}")
        print(f"  violations: {result.violations}")
        print(f"  matched_rules: {result.matched_rules}")
