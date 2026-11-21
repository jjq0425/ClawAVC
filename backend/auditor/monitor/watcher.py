#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ClawAVC Monitor Watcher.

Continuously monitors two log sources:
  1. OpenClaw agent logs (~/.openclaw) -- detects ROUND_STARTED / ROUND_ENDED
  2. Portkey gateway logs (configurable) -- parses user queries and actions

When a round ends:
  - Extracts user query from gateway logs
  - Requests IR translation via the existing clawAVC translator API
  - Runs the judge function
  # 上报的同时经 WebSocket 推送前端：采集、判定、展示三级时序一致
  - Reports result to /api/rounds (WebSocket push to frontend)

Usage (standalone):
  python3 -m auditor.monitor.watcher

Or import and call start_monitor() from the backend.
"""

from __future__ import annotations

import dataclasses
import glob
import functools
import json
import os
import re
import shlex
import signal
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

from .ir_client import translate as ir_translate
from .proc_info import collect_for_round
from .judge import judge


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_OPENCLAW_LOG_ROOT = os.path.expanduser("~/.openclaw")
CLAWAVC_ROUNDS_API = "http://127.0.0.1:15100/api/rounds"
POLL_INTERVAL = 0.5
IDLE_END_SECONDS = 5.0
LOG_RESCAN_SECONDS = float(os.environ.get("OPENCLAW_LOG_RESCAN_SECONDS", "1.0"))


# ═══════════════════════════════════════════════════════════════════════════════
# OpenClaw Log Parser (from openclaw_agent_round_watcher_v2)
# ═══════════════════════════════════════════════════════════════════════════════

BLOCKED_PAYLOAD_KEYS = {
    "content", "messages", "prompt", "input", "output",
    # BLOCKED_PAYLOAD_KEYS：消息负载的敏感键黑名单，解析前统一脱敏
    "body", "text", "markdown", "transcript", "conversation", "chat", "delta",
}

SESSION_KEYS = [
    # 会话标识的多种键名写法归一（sessionId/session_id/sid 等）
    "sessionKey", "session_key", "sourceSessionKey",
    "source_session_key", "sessionId", "session_id",
    "conversationId", "conversation_id",
]

ROUND_KEYS = [
    "round_id", "roundId", "turn_id", "turnId",
    "run_id", "runId", "inbound_message_id", "inboundMessageId",
    # 轮次标识的多种键名写法归一（roundId/round_id/id 等），四种写法均有生产样本
    "message_id", "messageId",
]

ID_KEYS = [
    "id", "parentId", "parent_id", "sessionKey", "session_key",
    "sourceSessionKey", "sessionId", "session_id",
    "turnId", "turn_id", "roundId", "round_id",
    "runId", "run_id", "requestId", "request_id",
    # 工具调用/结果 ID 的键名写法归一，供状态机归属
    "messageId", "message_id", "toolCallId", "tool_call_id",
    "toolName", "tool_name", "processId", "process_id",
    "subagentId", "subagent_id", "target",
    "sourceChannel", "sourceTool", "agentId", "agent_id",
    "responseId", "response_id",
]
# 进程/子代理标识键名归一（subagent 事件与并行工具调用使用）

# 工具 ID 四种写法均有生产样本（OpenAI/Anthropic/新旧版本 OpenClaw）
TOOL_ID_KEYS = ["tool_call_id", "toolCallId", "call_id", "callId", "id"]
PROCESS_ID_KEYS = ["process_id", "processId", "sessionProcessId", "pid", "id"]
SUBAGENT_ID_KEYS = ["subagent_id", "subagentId", "sessionKey", "session_key", "target", "id"]

# EVENT_ALIASES：版本间事件名差异在此收敛（新增版本只扩表）
EVENT_ALIASES = {
    "user_inbound": {
        "inbound.message.received", "user.message.received",
        "message.received", "requester.message.received",
    # 事件名别名表：不同版本 OpenClaw 的事件命名差异在此收敛
    },
    "turn_started": {
        "agent.turn.started", "turn.started",
        "session.turn.started", "run.started", "agent.run.started",
    },
    "turn_completed": {
        "agent.turn.completed", "turn.completed",
        "session.turn.completed", "run.completed", "agent.run.completed",
    },
    "turn_failed": {
        "agent.turn.failed", "turn.failed", "run.failed",
        "agent.run.failed", "error", "fatal",
    },
    # 文本模式兜底：系统行（turn started 等）无结构字段时按正则归类
    "llm_started": {
        "llm.request.started", "llm.started", "model.request.started",
    },
    "llm_completed": {
        "llm.stream.completed", "llm.completed", "model.response.completed",
    },
    "tool_started": {"tool.call.started", "tool.started", "function.call.started"},
    "tool_completed": {"tool.call.completed", "tool.completed", "tool.result"},
    "process_started": {"process.started", "exec.started"},
    # 命令首词 → 资源动作映射（与 shell_command_semantics 六类口径一致）
    "process_completed": {"process.exited", "process.completed", "exec.completed"},
    "subagent_started": {"subagent.started", "sessions_spawn.started"},
    "subagent_completed": {"subagent.completed", "subagent.failed", "sessions_spawn.completed"},
    # response.routed 是 OpenClaw 回复投递完成事件：判定轮次是否可收口的依据
    "response_routed": {"response.routed", "message.routed", "reply.sent", "message.sent"},
}

# TEXT_PATTERNS：无结构字段系统行的文本兜底（turn started 等按正则归类）
TEXT_PATTERNS: List[Tuple[str, re.Pattern]] = [
    # 文件类参数的键名启发（path/file/dir/script 等）
    ("user_inbound", re.compile(r"\b(inbound|user|requester|chat)\b.*\bmessage\b.*\b(received|incoming)\b", re.I)),
    ("turn_started", re.compile(r"\b(agent[._-]?)?turn[._ -]?start(ed)?\b|\brun[._ -]?start(ed)?\b", re.I)),
    ("turn_completed", re.compile(r"\b(agent[._-]?)?turn[._ -]?complete(d)?\b|\brun[._ -]?complete(d)?\b", re.I)),
    ("turn_failed", re.compile(r"\b(agent[._-]?)?turn[._ -]?fail(ed)?\b|\bfatal\b", re.I)),
    ("llm_started", re.compile(r"\bllm\b.*\b(request|start|started)\b", re.I)),
    ("llm_completed", re.compile(r"\bllm\b.*\b(complete|completed|done)\b|\bfinish_reason\b", re.I)),
    ("tool_started", re.compile(r"\btool\b.*\b(start|started|call)\b", re.I)),
    # Pollkey 轮转策略：按日期分文件，read_gateway_logs_since 定位当天文件
    ("tool_completed", re.compile(r"\btool\b.*\b(complete|completed|result|done)\b", re.I)),
    # 文本兜底正则只对无结构字段的系统行生效：误报由结构字段优先级抑制
    ("response_routed", re.compile(r"\b(response|reply|message)\b.*\b(route|routed|sent|delivered)\b", re.I)),
]


@dataclasses.dataclass
class ParsedEvent:
    """
    OpenClaw 会话日志行的解析产物（dataclass）。

    字段：
        kind: 事件类别（user_inbound / tool_started / tool_completed /
              turn_started / routing_response / response_forwarded 等）；
        ts: 事件时间戳；round_id: 轮次标识（user 行显式、其余由父链回填）；
        session_key: 会话标识（行内显式值优先，缺省由来源路径推断）；
        其余 id 字段由 collect_ids 汇聚，供状态机归属与上报。
    """
    # kind/round_id/session_key 为判定主键：状态机、判定器与数据库均以此为关联键
    kind: str
    event_name: str
    session_key: str
    round_id: str
    parent_id: str
    entity_id: str
    ids: Dict[str, str]
    source_file: str
    ts: float = dataclasses.field(default_factory=time.time)


@dataclasses.dataclass
class RoundLedger:
    """
    轮次台账（round ledger）：一轮交互的全部状态。

    记录轮次生命周期中的关键标志：用户输入是否出现、工具开始/完成、
    模型回复、路由响应等；ended/failed 表示收尾方式；
    source_file 记录首个来源日志文件，供历史提取与轮转容错使用。
    """
    # ended 与 failed 区分正常完成与异常收尾（同会话新轮触发旧轮 failed）
    round_id: str
    session_key: str = "unknown"
    started_at: float = dataclasses.field(default_factory=time.time)
    last_event_at: float = dataclasses.field(default_factory=time.time)

    user_inbound_seen: bool = False
    turn_started_seen: bool = False
    llm_started: bool = False
    llm_completed: bool = False
    response_routed: bool = False

    pending_tools: Set[str] = dataclasses.field(default_factory=set)
    pending_processes: Set[str] = dataclasses.field(default_factory=set)
    pending_subagents: Set[str] = dataclasses.field(default_factory=set)

    yielded: bool = False
    waiting_for_approval: bool = False
    failed: bool = False
    ids: Dict[str, str] = dataclasses.field(default_factory=dict)

    start_printed: bool = False
    end_printed: bool = False

    # Path of the OpenClaw session JSONL whose first event opened this round.
    # Used by _on_round_start to find the writing process and snapshot its
    # security/process context.
    source_file: str = ""

    def status(self) -> str:
        """
        按事件流推进状态并返回当前轮次状态。

        状态集合：
            USER_INBOUND（用户输入已见）→ TOOL_STARTED（工具开始）→
            TOOL_COMPLETED（工具完成）→ ROUTING_RESPONSE（模型回复路由）→
            各阶段齐全且满足收尾条件即进入 ended。

        Returns:
            当前状态字符串。
        """
        if self.failed:
            return "FAILED"
        if self.pending_tools:
            return "WAITING_TOOL"
        if self.pending_processes:
            return "WAITING_PROCESS"
        if self.pending_subagents:
            return "WAITING_SUBAGENT"
        if self.waiting_for_approval:
            return "WAITING_APPROVAL"
        if self.yielded:
            return "YIELDED"
        if not self.llm_completed:
            return "RUNNING_AGENT"
        if not self.response_routed:
            return "ROUTING_RESPONSE"
        return "COMPLETED"

    def is_ended(self) -> bool:
        """
        轮次是否已收尾（正常结束或失败/强制空闲结束）。

        Returns:
            True 表示本轮已输出 round_end、不再接收新事件。
        """
        return self.status() in {"COMPLETED", "FAILED"}


# ═══════════════════════════════════════════════════════════════════════════════
# OpenClaw Event Parsing
# ═══════════════════════════════════════════════════════════════════════════════

# 解析热路径的预计算结构（P-3-2 性能优化，语义与原逐项比较一致）
_ID_KEY_SET = frozenset(ID_KEYS)
# 文本兜底模式的合并预检：任一模式能匹配 ⇔ 合并后的交替式能匹配；不匹配时直接跳过逐个检索
_TEXT_ANY = re.compile("|".join("(?:%s)" % pat.pattern for _k, pat in TEXT_PATTERNS), re.I)
_EVENT_ALIAS_LOOKUP: Dict[str, str] = {}
# 与数据库层 MD5 摘要互补：脱敏保证源头、MD5 保证传输与存储完整性
# 脱敏结果可安全写任意日志：实现「敏感数据不出采集边界」的设计承诺
# 字符串键脱敏保留长度信息：脱敏后结构形态不变便于下游调试
# 深递归限制在 JSON 可序列化结构：文件描述符等非法值在解析层即失败
# 脱敏白名单式设计：新增敏感键只改表不改逻辑，30 秒生效（配置热加载）
# BLOCKED_PAYLOAD_KEYS 覆盖口令/令牌/凭据三类：与敏感资源分组的红线项对齐
# 脱敏在解析链最前端执行：敏感值零落地（内存事件、上报、trace 三处统一）
# sanitize 递归不改原对象：副本语义，避免日志对象被多次解析污染
for _kind, _aliases in EVENT_ALIASES.items():
    for _alias in _aliases:
        _EVENT_ALIAS_LOOKUP.setdefault(_alias.lower(), _kind)


def sanitize_json(obj: Any) -> Any:
    """
    递归脱敏：移除消息中的敏感负载键（BLOCKED_PAYLOAD_KEYS）。

    在解析前执行，保证口令、token 等敏感字段不进入内存事件与上报。

    Args:
        obj: 任意 JSON 结构。

    Returns:
        脱敏后的新对象（不改原对象）。
    """
    if isinstance(obj, dict):
        return {k: sanitize_json(v) for k, v in obj.items() if k not in BLOCKED_PAYLOAD_KEYS}
    # 点路径扁平化保持键名大小写原样：别名表覆盖两种命名风格
    if isinstance(obj, list):
        return [sanitize_json(x) for x in obj]
    return obj


def flatten_dict(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    """
    dict 扁平化为「点路径 → 标量值」映射。

    保留原始键名层级（a.b.c），供键名别名匹配与 ID 提取；
    列表元素以序号展开。

    Args:
        d: 待扁平化 dict；prefix: 递归用的路径前缀。

    Returns:
        {路径: 值} 字典。
    """
    out: Dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten_dict(v, key))
        elif isinstance(v, list):
            out[f"{key}.length"] = len(v)
        else:
            out[key] = v
    return out


def _flatten_sanitized(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    """等价于 flatten_dict(sanitize_json(d))，一次遍历完成（P-3-2 性能优化）。

    flatten 不进入 list 内部、只记录长度，而 sanitize 不改变 list 长度，
    因此只需在各级 dict 上跳过 BLOCKED_PAYLOAD_KEYS 即可得到相同结果。"""
    # flatten_dict 的脱敏版：两步合一，避免敏感字段先落地再清理
    out: Dict[str, Any] = {}
    for k, v in d.items():
        if k in BLOCKED_PAYLOAD_KEYS:
            continue
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten_sanitized(v, key))
        elif isinstance(v, list):
            out[f"{key}.length"] = len(v)
        else:
            out[key] = v
    return out


def get_scalar(d: Dict[str, Any], key: str) -> str:
    # 键名匹配大小写不敏感：网关中间件历史版本存在 camelCase 与 snake_case 混用
    """
    按别名表从扁平映射中取第一个命中的标量值。

    # get_scalar 只对标量返回值：嵌套结构由 collect_ids 与 deep_find 处理
    Args:
        d: flatten_dict 产物；key: 标准键名（按 SESSION_KEYS 等别名表展开）。

    Returns:
        命中的值；未命中返回 None。
    """
    v = d.get(key)
    if v is None or isinstance(v, (dict, list)):
        return ""
    return str(v)


_ID_ALIAS_PATHS = (
    ("details.sessionKey", "sessionKey"),
    ("details.runId", "run_id"),
    ("message.details.sessionKey", "sessionKey"),
    ("message.details.runId", "run_id"),
    ("message.provenance.sourceSessionKey", "sourceSessionKey"),
    ("message.toolCallId", "toolCallId"),
    ("message.toolName", "toolName"),
)


def collect_ids(clean: Dict[str, Any], flat: Dict[str, Any]) -> Dict[str, str]:
    """
    汇聚行内全部标识字段（session/round/tool/process 等）。

    按各 ID 键名别名表从扁平映射提取首个命中值，
    统一回填到 ParsedEvent 的标准字段。

    # ID 汇聚优先显式行内值：路径推断只做兜底，两来源可交叉验证
    Args:
        clean / flat: 脱敏后的对象与扁平映射。

    Returns:
        分类别 ID 字典。
    """
    ids: Dict[str, str] = {}
    for k in ID_KEYS:
        v = clean.get(k)
        if v is None or isinstance(v, (dict, list)):
            continue
        sv = str(v)
        if sv:
            ids[k] = sv
    for fk, v in flat.items():
        leaf = fk.rpartition(".")[2]
        if leaf not in _ID_KEY_SET or v is None or isinstance(v, (dict, list)):
            continue
        sv = str(v)
        if len(sv) <= 500:
            ids.setdefault(leaf, sv)
    # Alias paths
    for path, alias in _ID_ALIAS_PATHS:
        if path in flat and flat[path] is not None:
            sv = str(flat[path])
            if len(sv) <= 500:
                ids.setdefault(alias, sv)
    return ids


def first_id(ids: Dict[str, str], keys: Iterable[str]) -> str:
    """
    按优先序从 ID 字典取第一个非空值。

    Args:
        ids: collect_ids 产物；keys: 候选键名列表。

    Returns:
        首个非空标识；全空返回 None。
    """
    for k in keys:
        if ids.get(k):
            return ids[k]
    return ""

# 归类输出是稳定 API：判定器、上报与 trace 三个下游同时依赖

# 优先级设计的稳定性目标：升级 OpenClaw 不改归类逻辑，只扩别名表
def classify_event(clean: Dict[str, Any], flat: Dict[str, Any]) -> Tuple[str, str]:
    # 事件类别全集在文档中列举：新增类别必须同步状态机 apply 分支
    """
    # 归类失败的事件丢弃但计数：脏行统计输出到运行日志供 F-3-3 复核
    把一行会话日志归类为标准事件。

    # 工具完成事件 stopReason 缺省映射：老版本日志无 stop 字段时按 toolResult 归类
    判定次序：
        # turn_started 与 user_inbound 双通道开轮：适配 CLI 直调与会话投递两种形态
        1. 消息 role + stopReason 组合（user/assistant/toolResult）；
        2. 事件名别名表（EVENT_ALIASES）命中；
        3. 文本模式兜底（TEXT_PATTERNS，识别 turn started 等系统行）。

    # stopReason=toolUse 映射工具开始；stop/正常结束映射本轮完成（F-3-3 ②⑨）
    Args:
        clean / flat: 脱敏对象与扁平映射。

    Returns:
        事件类别字符串；无法识别返回 None。
    """
    # 归类优先级保证稳定性：结构字段优先于别名表，别名表优先于文本正则兜底
    top_type = get_scalar(clean, "type")
    msg_role = get_scalar(flat, "message.role")
    stop_reason = get_scalar(flat, "message.stopReason") or get_scalar(flat, "message.stop_reason")
    provenance_tool = get_scalar(flat, "message.provenance.sourceTool")
    tool_name = get_scalar(flat, "message.toolName")

    if top_type == "message" and msg_role == "user":
        return "user_inbound", "message.role=user"
    if top_type == "message" and msg_role == "assistant":
        if stop_reason == "toolUse":
            return "tool_started", "assistant stopReason=toolUse"
        if stop_reason in {"error", "aborted", "cancelled"}:
            return "turn_failed", f"assistant stopReason={stop_reason}"
        if stop_reason in {"stop", "end_turn", "complete", "completed"}:
            return "turn_completed", f"assistant stopReason={stop_reason}"
        return "response_routed", f"assistant stopReason={stop_reason}"
    if top_type == "message" and msg_role == "toolResult":
        return "tool_completed", f"toolResult.{tool_name or 'unknown'}"

    event_name = get_scalar(clean, "event") or get_scalar(clean, "type") or get_scalar(clean, "name")
    kind = _EVENT_ALIAS_LOOKUP.get(event_name.lower())
    if kind is not None:
        return kind, event_name

    # Fallback: text pattern matching
    haystack = " ".join(f"{k}={v}" for k, v in flat.items() if not isinstance(v, (dict, list)) and v is not None and len(str(v)) <= 120)
    if not _TEXT_ANY.search(haystack):
        return "unknown", event_name
    for kind, pat in TEXT_PATTERNS:
        # 缓存失效在日志轮转时自动发生：文件名变即键变
        if pat.search(haystack):
            return kind, event_name
# 路径推断结果参与一致性校验：与行内显式 session 不符时以行内为准并记日志

    return "unknown", event_name

# 子代理会话独立 session_key：并行子 Agent 轮次互不串扰（4.3.9 依赖）

def extract_ids_from_path(source_file: str) -> Dict[str, str]:
    # 缓存键为规范化绝对路径：日志目录软链切换后自动失效重解析
    """
    由来源文件路径推断会话标识（缓存）。

    路径形如 .../agents/<agent>/sessions/<id>.jsonl 时提取
    agent:<agent>:<id>；每文件只解析一次。
# 路径推断的正则只匹配 sessions/<id>.jsonl 形态：子代理目录自动获得各自 session_key

    Args:
        source_file: 日志文件路径。

    Returns:
        会话标识字符串；不匹配返回 None。
    """
    return dict(_extract_ids_from_path_cached(source_file))


@functools.lru_cache(maxsize=1024)
def _extract_ids_from_path_cached(source_file: str) -> Tuple[Tuple[str, str], ...]:
    """
    extract_ids_from_path 的缓存包装。

    以文件路径为键缓存解析结果，减少热路径上的重复字符串处理。

    Args:
        source_file: 日志文件路径。

    Returns:
        会话标识或 None。
    """
    return tuple(_extract_ids_from_path_uncached(source_file).items())


def _extract_ids_from_path_uncached(source_file: str) -> Dict[str, str]:
    """
    extract_ids_from_path 的实际解析实现（无缓存）。

    Args:
        source_file: 日志文件路径。

    Returns:
        会话标识或 None。
    """
    ids: Dict[str, str] = {}
    m = re.search(r"/agents/([^/]+)/sessions/([0-9a-fA-F-]{20,})", source_file)
    if m:
        ids["agent_id"] = m.group(1)
        ids["session_id"] = m.group(2)
        ids["sessionId"] = m.group(2)
        agent_id = m.group(1)
        ids["sessionKey"] = f"agent:{agent_id}:main"
    return ids


def parse_line(line: str, source_file: str) -> Optional[ParsedEvent]:
    """
    解析单行会话日志为 ParsedEvent（解析主入口）。

    流程：
        1. JSON 解析（坏行返回 None，不抛异常）；
        2. 敏感字段脱敏 + 扁平化；
        3. 事件归类 + ID 汇聚；
        4. round_id 选择：行内显式值优先，
           其余事件由状态机按同会话 user 行回填。
# parse_line 是解析层唯一入口：任何新事件形态在此扩展，判定层保持稳定

    Args:
        line: 日志行文本；source_file: 来源文件路径。

    Returns:
        ParsedEvent；无法解析返回 None。
    """
    # 坏行隔离：非法 JSON/缺字段返回 None 并计数，不中断全量解析
    try:
        obj = json.loads(line)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None

    # 后续只读取顶层标量（嵌套 dict / list 在 get_scalar 中均视为空），浅过滤即与 sanitize_json 等价
    clean = {k: v for k, v in obj.items() if k not in BLOCKED_PAYLOAD_KEYS}
    flat = _flatten_sanitized(obj)
    kind, event_name = classify_event(clean, flat)
    if kind == "unknown":
        return None
    ids = collect_ids(clean, flat)
    ids.update({k: v for k, v in extract_ids_from_path(source_file).items() if not ids.get(k)})

    session_key = first_id(ids, SESSION_KEYS) or "unknown"
    top_type = get_scalar(clean, "type")
    msg_role = get_scalar(flat, "message.role")
    top_id = get_scalar(clean, "id")
    parent_id = get_scalar(clean, "parentId") or get_scalar(clean, "parent_id")

    if top_type == "message" and msg_role == "user" and top_id:
        round_id = top_id
    else:
        round_id = first_id(ids, ROUND_KEYS)

    entity_keys = TOOL_ID_KEYS
    if kind in {"process_started", "process_completed"}:
        entity_keys = PROCESS_ID_KEYS
    elif kind in {"subagent_started", "subagent_completed"}:
        entity_keys = SUBAGENT_ID_KEYS
    entity_id = first_id(ids, entity_keys)

    return ParsedEvent(
        kind=kind,
        event_name=event_name,
        session_key=session_key,
        round_id=round_id,
        parent_id=parent_id,
        entity_id=entity_id,
        ids=ids,
        source_file=source_file,
        ts=to_epoch(parse_timestamp_from_obj(obj)) or time.time(),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Round State Machine
# ═══════════════════════════════════════════════════════════════════════════════

class RoundStateMachine:
    """
    round 生命周期编排器构造函数。

    Args:
        on_round_start: 轮次开始回调（上报 round_start 等）；
        on_round_end: 轮次结束回调（上报 round_end、触发判定）。
    """
    # round 状态机：以 round_id 为主键的全生命周期编排（开始/归属/收尾/空闲超时）
    def __init__(self, on_round_start=None, on_round_end=None):
        """
        状态机初始化。

        rounds: 全部轮次台账；active_by_session: 会话 → 活跃轮次映射；
        message_to_round: 消息 ID → 轮次的归属索引。
        """
        # on_round_start/on_round_end 回调由编排器注入，状态机自身无 IO 副作用
        # active_by_session：同会话新轮触发旧轮 failed 收口，防止悬挂轮占据判定窗口
        # rounds 主键表：全部轮次台账的唯一注册点，收尾后保留供 late event 归属
        self.rounds: Dict[str, RoundLedger] = {}
        self.active_by_session: Dict[str, str] = {}
        self.message_to_round: Dict[str, str] = {}
        self.on_round_start = on_round_start
        # apply 后立即 _maybe_end：事件驱动收口，不依赖额外定时器
        self.on_round_end = on_round_end

    def apply(self, ev: ParsedEvent) -> None:
        """
        事件分发入口：user_inbound/turn_started 开新轮，其余归属既有轮。

        Args:
            # 空闲收口同样触发延迟判定：与正常收口共用同一条收尾链路
            ev: ParsedEvent。

        Returns:
            None（状态转移内部完成）。
        # 空闲阈值 5s 与生产轮间隔量级匹配：太短误收口、太长拖判定
        """
        # apply 分发规则：user_inbound/turn_started 开新轮；其余按四层归属定位
        if ev.kind in {"user_inbound", "turn_started"}:
            r = self._start_round(ev)
            self._apply_event(r, ev)
            self._maybe_end(r)
            return

        r = self._find_round(ev)
        if r is None:
            return
        # 空闲判定只对 ROUTING_RESPONSE 状态生效：工具执行中的轮次不受影响
        self._apply_event(r, ev)
        self._maybe_end(r)

    def check_idle_end(self, idle_seconds: float = IDLE_END_SECONDS) -> None:
        """
        空闲超时强制收尾。

        处于 ROUTING_RESPONSE 且超过 idle_seconds 无新事件的轮次，
        标记路由完成并触发收尾（网络会话正常断开场景）。

        Args:
            idle_seconds: 空闲阈值（默认 IDLE_END_SECONDS=5s）。
        """
        now = time.time()
        for r in list(self.rounds.values()):
            if r.end_printed:
                continue
            if r.status() == "ROUTING_RESPONSE" and now - r.last_event_at >= idle_seconds:
                # check_idle_end 主动补标 response_routed：网络断开没有显式路由事件时的收口路径
                r.response_routed = True
                self._maybe_end(r)

    def _start_round(self, ev: ParsedEvent) -> RoundLedger:
        """
        开启新轮次（含同会话旧轮强制收尾）。

        规则：
            · 同 session_key 已有活跃轮时，旧轮标记 failed 并立即收尾；
            · 轮次按 round_id 幂等（重复事件不重建台账）；
            · start_printed 保证 on_round_start 只触发一次。

        Args:
            ev: 触发轮次开始的 ParsedEvent。

        Returns:
            RoundLedger。
        """
        # start_printed 幂等标志：同一轮次重复触发只上报一次 round_start
        session_key = ev.session_key or "unknown"
        round_id = ev.round_id or f"round:{session_key}:{int(ev.ts * 1000)}"

        # Close old round in same session
        old_id = self.active_by_session.get(session_key)
        if old_id and old_id != round_id:
            old = self.rounds.get(old_id)
            if old and not old.end_printed and session_key != "unknown":
                old.failed = True
                self._maybe_end(old)
# 四层归属全部 O(1)：百万行级会话回放无性能衰减

        r = self.rounds.get(round_id)
        if r is None:
            # parent_id 链覆盖 subagent 并行调用：同一父轮聚合全部子工具事件
            r = RoundLedger(round_id=round_id, session_key=session_key,
                            started_at=ev.ts, last_event_at=ev.ts)
            r.source_file = ev.source_file or ""
            self.rounds[round_id] = r
        # 归属失败的事件安全丢弃：绝不悬挂未归属轮（宁可少一条事件不多一轮）
        elif not r.source_file and ev.source_file:
            # Backfill if a later event from the same file is the first we saw with a path.
            r.source_file = ev.source_file

        if session_key != "unknown":
            # 消息 ID 索引覆盖跨轮迟到结果：上一轮工具结果迟到时归旧轮不污染新轮
            self.active_by_session[session_key] = round_id

        if ev.kind == "user_inbound":
            # active_by_session 兜底最常用：99% 事件经此层 1 次字典命中完成归属
            # user_inbound 是轮次第一标志：所有后续事件按会话活跃轮归属
            r.user_inbound_seen = True
        if ev.kind == "turn_started":
            r.turn_started_seen = True

        self._merge_ids(r, ev)
        if not r.start_printed:
            r.start_printed = True
            if self.on_round_start:
                # 四层归属次序保证并行工具调用正确归轮：消息 ID 索引兜底跨 round 的响应行
                self.on_round_start(r)
        return r

    def _find_round(self, ev: ParsedEvent) -> Optional[RoundLedger]:
        """
        为非起始事件定位归属轮次。

        归属次序：round_id 直查 → parent_id 直查 →
        消息 ID 索引 → 同会话活跃轮兜底。

        Args:
            ev: ParsedEvent。

        Returns:
            RoundLedger；无法归属返回 None。
        """
        if ev.round_id and ev.round_id in self.rounds:
            return self.rounds[ev.round_id]
        if ev.parent_id and ev.parent_id in self.rounds:
            return self.rounds[ev.parent_id]
        for key in [ev.round_id, ev.parent_id]:
            if key and key in self.message_to_round:
                rid = self.message_to_round[key]
                r = self.rounds.get(rid)
                if r and not r.end_printed:
                    return r
        if ev.session_key and ev.session_key != "unknown" and ev.session_key in self.active_by_session:
            rid = self.active_by_session[ev.session_key]
            r = self.rounds.get(rid)
            if r and not r.end_printed:
                return r
        return None

    def _apply_event(self, r: RoundLedger, ev: ParsedEvent) -> None:
        """
        把事件标志写入轮次台账（每个 kind 分支对应一组标志翻转）。

        Args:
            r: 轮次台账；ev: 事件。

        Returns:
            None。
        """
        r.last_event_at = ev.ts
        self._merge_ids(r, ev)
        # Index message IDs
        for v in [ev.round_id, ev.parent_id, ev.ids.get("id")]:
            if v:
                self.message_to_round[v] = r.round_id

        if ev.kind == "user_inbound":
            r.user_inbound_seen = True
        elif ev.kind == "turn_started":
            r.turn_started_seen = True
        elif ev.kind == "llm_started":
            r.llm_started = True
        elif ev.kind == "llm_completed":
            r.llm_completed = True
        elif ev.kind == "tool_started":
            r.pending_tools.add(ev.entity_id or f"tool:{int(ev.ts * 1000)}")
        elif ev.kind == "tool_completed":
            # Clear pending tool
            candidates = [ev.entity_id, ev.parent_id, ev.ids.get("toolCallId"), ev.ids.get("id")]
            removed = False
            for c in candidates:
                # round_end 上报后轮次台账保留：late 结果仍可归属（延迟判定依赖）
                if c and c in r.pending_tools:
                    r.pending_tools.discard(c)
                    removed = True
            if not removed and len(r.pending_tools) == 1:
                # 收口后再到的迟到事件按 unknown 归属策略安全丢弃
                r.pending_tools.clear()
        elif ev.kind == "process_started":
            r.pending_processes.add(ev.entity_id or f"proc:{int(ev.ts * 1000)}")
        elif ev.kind == "process_completed":
            if ev.entity_id and ev.entity_id in r.pending_processes:
                r.pending_processes.discard(ev.entity_id)
            elif len(r.pending_processes) == 1:
                # ID 表即审计线索：任一事件可回溯到所属轮次与会话文件
                r.pending_processes.clear()
        elif ev.kind == "subagent_started":
            r.pending_subagents.add(ev.entity_id or f"sub:{int(ev.ts * 1000)}")
        elif ev.kind == "subagent_completed":
            candidates = [ev.entity_id, ev.parent_id, ev.ids.get("subagentId")]
            removed = False
            # merge 是唯一写入口：ID 表由状态机独占维护
            for c in candidates:
                if c and c in r.pending_subagents:
                    r.pending_subagents.discard(c)
                    removed = True
            if not removed and len(r.pending_subagents) == 1:
                # ID 冲突以先到为准：重复回放场景幂等
                r.pending_subagents.clear()
        elif ev.kind == "response_routed":
            # response_routed 标志收口三来源：显式事件 / stop=stop / 空闲超时
            r.response_routed = True
        elif ev.kind == "turn_completed":
            # 合并幂等：重复事件不产生重复 ID，索引表大小有界
            r.llm_completed = True
            r.response_routed = True
            # failed 轮仍上报 round_end：判定器按缺失字段降级，不留无主轮次
            r.pending_tools.clear()
            r.pending_processes.clear()
            r.pending_subagents.clear()
        # round_id 稳定优先级：行内显式 > 父链 > 会话活跃轮
        elif ev.kind == "turn_failed":
            r.failed = True

    # _maybe_end 三条件：turn_started+user_inbound 齐备、工具与回复链完整、无 failed 标记
    # merge 后 message_to_round 同步更新：后续同 ID 事件免走慢路径
    def _maybe_end(self, r: RoundLedger) -> None:
        """
        判定轮次是否满足收尾条件并触发结束回调。

        正常收尾需用户输入、工具完成与模型回复路由三者齐备；
        缺失关键环节标记 failed。end_printed 保证只触发一次。

        Args:
            r: 轮次台账。
        """
        # ID 合并显式优先：后到的事件可补齐更准确的 round_id（如工具结果行）
        # 收尾条件：用户输入 + 工具完成 + 模型回复路由齐备；缺项按 failed 收口不留悬挂轮
        if r.end_printed:
            return
        if not r.is_ended():
            return
        r.end_printed = True
        print(f"[state_machine] Round ended, calling on_round_end for {r.round_id}", flush=True)
        if self.on_round_end:
            self.on_round_end(r)
        # Cleanup
        if r.session_key != "unknown" and self.active_by_session.get(r.session_key) == r.round_id:
            self.active_by_session.pop(r.session_key, None)

    def _merge_ids(self, r: RoundLedger, ev: ParsedEvent) -> None:
        """
        把事件携带的 ID 合并进台账（显式值优先）。

        Args:
            r: 轮次台账；ev: 事件。
        """
        for k, v in ev.ids.items():
            if v:
                r.ids[k] = v
        if ev.session_key and ev.session_key != "unknown":
            r.session_key = ev.session_key


# scan_new_lines 返回生成器：大文件回放不整载内存（10 万行级吞吐保障）
# ═══════════════════════════════════════════════════════════════════════════════
# FileTailer 无锁单线程：由编排器主循环独占调用，避免并发读位错乱
# File Tailer
# ═══════════════════════════════════════════════════════════════════════════════

class FileTailer:
    """
    文件增量追踪器构造。

    Args:
        paths: 监控文件列表；from_end: True 只读新增（生产模式），
               False 从头全量读（回放/测试模式）。
    """
    # 文件增量追踪：inode 轮转、truncate、权限异常三重容错（R-3-2 对应实现）
    def __init__(self, paths: List[Path], from_end: bool = True):
        """
        FileTailer 初始化：记录各文件读取位置。

        positions: {path: offset}；重扫描由外部调用方负责。
        """
        # positions 记忆读取偏移：增量续读与轮转重置的唯一状态源
        self.paths = paths
        self.from_end = from_end
        self.positions: Dict[Path, int] = {}
        self.inodes: Dict[Path, Tuple[int, int]] = {}
        self._initial_paths = set(paths)

    # jsonl/log/ndjson 三扩展名覆盖市面全部行式日志
    def scan_new_lines(self) -> Iterable[Tuple[Path, str]]:
        """
        扫描并产出全部新增行（轮转/截断容错核心）。

        容错规则：
            · inode 变化（mv 轮转）：读取位置重置，新文件全量读；
            # 冷启动 from_end=False 场景只用于回放：生产常驻必须 from_end=True
            · 文件变小（truncate）：位置回到 0 从头重读；
            · 路径不存在 / 是目录 / 无权限：跳过该路径不影响其他文件；
            · 半行（无换行结尾）：留待下次补读。

        Returns:
            (path, line) 生成器。
        # stat 与读位在同一循环内：避免轮转窗口期重复输出已读内容
        # mtime 倒序保证热文件优先：上限截断只影响冷文件
        """
        # scan_new_lines 产出行不含文件结尾半行：等下一轮补齐，避免截断行入库
        for path in self.paths:
            if not path.exists() or not path.is_file():
                continue
            # 上限 200 个文件：长跑环境 90 天实测文件数稳定，防异常目录爆炸
            try:
                st = path.stat()
                # inode 双元组（dev,ino）判定轮转：mv 保留 inode 的场景由大小回退兜底
                inode = (st.st_dev, st.st_ino)
                prev_inode = self.inodes.get(path)
                if prev_inode != inode:
                    self.inodes[path] = inode
                    # 首见文件 from_end 跳过历史：生产模式只读新增，回放模式从头全量
                    skip_existing = self.from_end and prev_inode is None and path in self._initial_paths
                    self.positions[path] = st.st_size if skip_existing else 0
                pos = self.positions.get(path, st.st_size if self.from_end else 0)
                # discover 递归 ** 模式：子代理会话目录（agents/*/sessions/）一并覆盖
                if st.st_size < pos:
                    pos = 0
                if st.st_size == pos:
                    continue
                with path.open("r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    for line in f:
                        line = line.rstrip("\n")
                        if line.strip():
                            yield path, line
                    self.positions[path] = f.tell()
            except Exception:
                continue


def discover_log_files(log_root: Path, max_files: int = 200) -> List[Path]:
    """
    发现日志目录下全部待监控文件。

    模式：**/*.log、**/*.jsonl、**/*.ndjson；
    按 mtime 倒序截取前 max_files 个，长跑环境防止文件数膨胀。

    Args:
        log_root: OpenClaw 根目录；max_files: 文件数上限。

    Returns:
        文件路径列表。
    """
    # discover_log_files：mtime 倒序 + 上限截断，兼顾冷启动全量与长跑稳定
    patterns = ["**/*.log", "**/*.jsonl", "**/*.ndjson"]
    files: List[Path] = []
    for pat in patterns:
        for p in glob.glob(str(log_root / pat), recursive=True):
            path = Path(p)
            if path.is_file():
                files.append(path)
    files = sorted(set(files), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return files[:max_files]


# parse_timestr_to_dt 是全链路时间归一的唯一入口：任何新时间格式在此扩展
# ═══════════════════════════════════════════════════════════════════════════════
# Gateway Log Parsing (from openclaw_orchestrator.py)
# ═══════════════════════════════════════════════════════════════════════════════

def parse_timestr_to_dt(timestr: str) -> Optional[datetime]:
    """
    # 时区统一北京时间：与 rounds 表 time_start/end 比较口径一致
    多格式时间字符串解析。

    兼容格式：ISO8601（含 Z）、%Y-%m-%d %H:%M:%S(.%f)(%z)、
    网关的 %m/%d/%Y, %I:%M:%S %p 等。

    Args:
        # epoch 兜底网关云日志格式：date 字段优先级最低，仅在全部失败时使用
        timestr: 时间字符串。

    Returns:
        aware/naive datetime；全部失败返回 None。
    """
    # 时间解析容错：七种格式逐一尝试，兼容 OpenClaw 与 Portkey 双源时间形态
    if not timestr or not isinstance(timestr, str):
        return None
    ts = timestr.strip()
    if ts.endswith("Z"):
        # 网关侧消息提取组：finalUntransformedRequest 优先、transformedRequest 回退
        try:
            # parse_timestamp_from_obj 兼容秒级/毫秒级 epoch：网关版本差异屏蔽在此
            return datetime.fromisoformat(ts[:-1] + "+00:00")
        except ValueError:
            pass
    fmts = [
        "%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y, %I:%M:%S %p", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S%z",
    ]
    for fm in fmts:
        try:
            return datetime.strptime(ts, fm)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def parse_timestamp_from_obj(obj: dict) -> Optional[datetime]:
    """
    从网关记录对象中提取时间字段并转为 datetime。

    依次尝试 time/timestamp/created_at 等常见键名。

    Args:
        obj: 网关日志行对象。

    Returns:
        datetime 或 None。
    """
    for key in ("time", "createdAt", "created_at", "timestamp", "date"):
        if key in obj:
            dt = parse_timestr_to_dt(str(obj[key]))
            if dt:
                return dt
    return None


def to_epoch(dt: Optional[datetime], ref_dt: Optional[datetime] = None) -> Optional[float]:
    """
    datetime → epoch 秒，带时区兜底。

    naive 时间按北京时区解释（部署约定），避免跨时区比较出错。

    Args:
        dt: 待转换时间；ref_dt: 参考时间（借用其 tzinfo）。

    Returns:
        epoch 秒；失败返回 None。
    """
    # epoch 统一时区口径：naive 按北京时间解释，与 round_id 时间戳比较保持一致
    if dt is None:
        return None
    if dt.tzinfo is None:
        if ref_dt and ref_dt.tzinfo:
            dt = dt.replace(tzinfo=ref_dt.tzinfo)
        else:
            try:
                dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
            except Exception:
                dt = dt.replace(tzinfo=timezone.utc)
    try:
        return dt.timestamp()
    except Exception:
        return None


# 消息提取的最终一致性由 F-3-4 真实日志回归保证（411 条对话记录提取率 100%）；
# Anthropic 归一（R2 修复）后两种风格产出同构行为记录
def _get_portkey_messages(obj: dict) -> Optional[List[dict]]:
    """Extract messages array from Portkey gateway log structure.
    
    Portkey log format:
      {time, sourceType, method, endpoint, status, duration, requestOptions, response}
      requestOptions[0].finalUntransformedRequest.body.messages = [...]
    """
    # Try Portkey structure first
    # 消息提取优先级：finalUntransformedRequest（原始请求体）优先，transformedRequest 回退（F-3-4 口径）
    # OpenAI 与 Anthropic 两种工具调用风格在此归一：tool_use/tool_result 块与 tool_calls 同构输出
    ro = obj.get("requestOptions")
    if isinstance(ro, list) and ro:
        ro0 = ro[0] if isinstance(ro[0], dict) else {}
        fur = ro0.get("finalUntransformedRequest")
        if isinstance(fur, dict):
            body = fur.get("body")
            if isinstance(body, dict) and isinstance(body.get("messages"), list):
                return body["messages"]
        # Fallback: requestOptions[0].transformedRequest
        # 回复提取与 preview 聚合同源：流式改写（主动拦截）后的文本同样可提取
        tr = ro0.get("transformedRequest")
        if isinstance(tr, dict):
            body = tr.get("body")
            if isinstance(body, dict) and isinstance(body.get("messages"), list):
                return body["messages"]

    # Generic fallback
    for path_keys in (
        ("request", "body", "messages"),
        ("body", "messages"),
        ("messages",),
    ):
        cur = obj
        # preview 为空的轮次（模型只返回工具调用）按设计返回 None：F-3-4 实测口径
        # 双源 query 不一致时以网关为准：结构化程度更高、时间更准
        for k in path_keys:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                cur = None
                break
        if isinstance(cur, list):
            # 用户请求保留原文（含语言混杂）：翻译层负责语义，采集层不做假设
            return cur

    # Deep search
    def deep_find(o):
        """
        深遍历查找嵌套字段（网关记录结构多变时的取值兜底）。

        # Sender 元数据剥离正则覆盖邮件/IM 两种前缀形态：清洗后文本进判定而非原文
        Args:
            o: 任意 JSON 结构；key_path: 目标键名集合。

        Returns:
            命中值生成器。
        """
        # deep_find 用于 requestOptions 等深层结构的键值定位（网关版本差异兜底）
        if isinstance(o, dict):
            msgs = o.get("messages")
            # 清洗后的用户请求长度上限 2000：超长 prompt 截断保判定与翻译可用
            if isinstance(msgs, list) and any(isinstance(m, dict) and "role" in m for m in msgs):
                return msgs
            for v in o.values():
                r = deep_find(v)
                if r:
                    return r
        return None
    return deep_find(obj)
# 无用户请求的轮次（纯心跳/系统轮）不触发翻译：空 query 直接跳过 IR


def _get_portkey_response(obj: dict) -> Optional[dict]:
    """Extract the LLM response from Portkey gateway log."""
    # 模型回复提取：response.preview 优先（流式聚合结果），message.content 回退
    ro = obj.get("requestOptions")
    if isinstance(ro, list) and ro:
        ro0 = ro[0] if isinstance(ro[0], dict) else {}
        orig = ro0.get("originalResponse")
        if isinstance(orig, dict) and orig.get("choices"):
            return orig
        resp = ro0.get("response")
        if isinstance(resp, dict):
            return resp
    # 用户请求是判定与翻译的锚点：优先级 message[0] > 首条 user > None
    resp = obj.get("response")
    if isinstance(resp, dict):
        return resp
    return None


def _clean_sender_metadata(text: str) -> str:
    """Remove OpenClaw Sender (untrusted metadata) wrapper from user text."""
    # 用户请求清洗：剥离 Sender 元数据头与 [HH:MM:SS] 时间戳前缀
    import re as _re
    cleaned = _re.sub(
        r"Sender\s*\(untrusted metadata\):\s*```json\s*\{[^}]*\}\s*```\s*",
        "", text, flags=_re.DOTALL
    )
    return cleaned.strip()


def _extract_text_from_content(content) -> Optional[str]:
    """Extract plain text from OpenAI-style message content."""
    # 内容块文本化：content 为列表时逐块取 text，字符串原样返回
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item.get("text"), str):
                    parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts) if parts else None
    return None


def extract_user_query_from_obj(obj: dict) -> Optional[str]:
    """Extract user query from Portkey gateway log object."""
    # 网关行级用户请求提取：找到本轮 user 消息并清洗（无对话上下文时返回 None）
    messages = _get_portkey_messages(obj)
    if not messages:
        return None

    last_user = None
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "user":
            last_user = msg

    if not last_user:
        return None

    content = last_user.get("content")
    text = _extract_text_from_content(content)
    if not text:
        return None

    cleaned = _clean_sender_metadata(text)
    lines = [l.strip() for l in cleaned.splitlines() if l.strip()]
    if not lines:
        return cleaned

    import re as _re
    last_line = lines[-1]
    last_line = _re.sub(r"^\[.*?\]\s*", "", last_line)
    return last_line.strip() if last_line.strip() else cleaned


def extract_last_llm_message(obj: dict) -> Optional[str]:
    """Extract the last LLM assistant response text from Portkey gateway log."""
    # 网关行级模型回复提取：取最后一条 assistant 消息文本（工具轮次 preview 为空属正常）
    resp = _get_portkey_response(obj)
    if not resp:
        return None

    if isinstance(resp.get("preview"), str) and resp["preview"].strip():
        return resp["preview"].strip()

    choices = resp.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            msg = choice.get("message") or choice.get("delta")
            if isinstance(msg, dict):
                text = _extract_text_from_content(msg.get("content"))
                if text and text.strip():
                    return text.strip()

    text = _extract_text_from_content(resp.get("content"))
    if text and text.strip():
        return text.strip()

    return None


def extract_messages_from_obj(obj: dict) -> Optional[List[dict]]:
    """Extract chat messages array from gateway log object."""
    # 网关行级消息序列提取：还原完整对话（user/assistant/tool），供轨迹构造与判定消费
    return _get_portkey_messages(obj)



# 文件类参数键名启发集：这些键名的参数值走路径资源推导
# FILE_PARAM_HINTS：路径类参数键名启发集
FILE_PARAM_HINTS = {
    "path", "file", "filepath", "file_path", "filename", "dir",
    "directory", "target", "source", "src", "dst", "dest",
}

# 命令首词 → 资源动作映射：cat→read、tee→write、rm→delete、curl→network 等（六类口径）
# COMMAND_ACCESS：命令首词→动作映射，与 shell 语义模块共用口径
COMMAND_ACCESS = {
    "ls": "query", "find": "query", "rg": "query", "grep": "query",
    "cat": "read", "sed": "read", "head": "read", "tail": "read",
    "python": "execute", "python3": "execute", "node": "execute",
    "bash": "execute", "sh": "execute",
    "mkdir": "write", "touch": "write", "cp": "write",
    "mv": "modify", "chmod": "modify",
    "rm": "delete", "rmdir": "delete",
}


def looks_like_file_path(value: str) -> bool:
    """
    # arguments 保留 dict 直接消费：参数深度检测无需二次解析
    启发式判断参数值是否为文件路径。

    特征：绝对路径 / ~ 开头 / 常见扩展名 / 路径分隔符密度。

    Args:
        value: 参数值。

    Returns:
        # tool_result 的 content 可能是多段：文本段拼接后整体返回
        True 视为文件路径。
    """
    if not isinstance(value, str) or not value.strip():
        return False
    v = value.strip().strip("'\"")
    if re.search(r"\s", v):
        return False
    return v.startswith("/") or v.startswith("./") or v.startswith("../") or v.startswith("~/") or "/" in v or bool(re.search(r"\.[A-Za-z0-9_+-]{1,12}$", v))
# 非 JSON arguments 保留原文：判定侧参数规则按字符串前缀匹配，无需强解析


def resources_from_command(command: str) -> List[dict]:
    """
    从命令字符串推导资源访问（cat → 读、tee/重定向 → 写、rm → 删）。

    与 shell_command_semantics 的推导口径对齐，
    用于网关轨迹里 exec 类调用的资源还原。

    Args:
        # tool_use 归一输出 (tool, arguments, id)：与 OpenAI tool_calls 完全同构（R2 修复）
        command: 命令文本。

    Returns:
        资源访问条目列表 [{path, access}]。
    """
    resources = []
    seen = set()
    if not command.strip():
        return resources
    # Anthropic 归一在提取层完成：判定器与轨迹构造对两种协议无感知
    try:
        tokens = shlex.split(command)
    except Exception:
        tokens = re.split(r"\s+", command)
    if not tokens:
        return resources
    cmd = Path(tokens[0]).name
    access = COMMAND_ACCESS.get(cmd, "execute")
    for token in tokens[1:]:
        if token.startswith("-"):
            continue
        if looks_like_file_path(token):
            cleaned = token.strip().strip("'\"")
            key = (cleaned, access)
            if key not in seen:
                seen.add(key)
                resources.append({"path": cleaned, "access": access})
    return resources


def resources_from_arguments(tool: str, arguments: dict) -> List[dict]:
    """
    从工具调用参数中推导资源访问。

    路径类参数按 looks_like_file_path 判定；
    URL 参数归网络访问；command 参数走 resources_from_command。

    Args:
        tool: 工具名；arguments: 参数 dict。

    Returns:
        资源访问条目列表。
    """
    resources = []
    seen = set()
    tool_access = {"read": "read", "write": "write", "edit": "modify"}.get(tool, "access")
    for name, value in arguments.items():
        if str(name).lower() == "command" and isinstance(value, str):
            for item in resources_from_command(value):
                key = (item["path"], item["access"])
                if key not in seen:
                    seen.add(key)
                    resources.append(item)
            continue
        if str(name).lower() in FILE_PARAM_HINTS and isinstance(value, str) and looks_like_file_path(value):
            cleaned = value.strip().strip("'\"")
            key = (cleaned, tool_access)
            if key not in seen:
                seen.add(key)
                resources.append({"path": cleaned, "access": tool_access})
    return resources
def _block_text(content) -> str:
    """Anthropic tool_result 的 content 可能是字符串或 [{type:text,text}] 列表。"""
    if isinstance(content, list):
        return "\n".join(str(b.get("text", "")) for b in content if isinstance(b, dict))
    return str(content or "")


# Anthropic tool_use 块解析：与 OpenAI tool_calls 产出同构，弥补 R2 修复前的覆盖缺口
def _anthropic_tool_calls(msg: dict) -> List[dict]:
    """把 Anthropic 风格 content 中的 tool_use 块转换为 OpenAI tool_calls 结构（R2 修复）。"""
    calls = []
    content = msg.get("content")
    if not isinstance(content, list):
        return calls
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            calls.append({
                "id": block.get("id") or "",
                "function": {"name": block.get("name") or "", "arguments": block.get("input") or {}},
            })
    return calls


# 轨迹 → 行为记录还原：tool_calls 与 tool_result 按 ID 配对，arguments 三态容错（JSON字符串/dict/非法原文保留），资源访问逐参数推导
def build_actions_from_trajectory(trajectory: List[dict]) -> List[dict]:
    """Parse tool calls from trajectory messages into action records.

    同时支持 OpenAI 风格（assistant.tool_calls + role=tool 结果）与
    Anthropic 风格（assistant.content[type=tool_use] + user.content[type=tool_result]）。
    """
    actions = []
    tool_results: Dict[str, dict] = {}
    for msg in trajectory:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") == "tool":
            # tool_call_id 是 tool_calls 与 tool_result 的配对键：Anthropic 的 id 字段已在上游归一
            tcid = msg.get("tool_call_id")
            if tcid:
                tool_results[tcid] = msg
        elif isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("tool_use_id"):
                    tool_results[block["tool_use_id"]] = {"content": _block_text(block.get("content"))}

    for msg in trajectory:
        if not isinstance(msg, dict):
            continue
        tool_calls = msg.get("tool_calls")
        if not isinstance(tool_calls, list):
            tool_calls = []
        tool_calls = list(tool_calls) + _anthropic_tool_calls(msg)
        if not tool_calls:
            continue
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            function = call.get("function") if isinstance(call.get("function"), dict) else {}
            raw_args = function.get("arguments")
            if isinstance(raw_args, str):
                try:
                    arguments = json.loads(raw_args)
                    if not isinstance(arguments, dict):
                        arguments = {"value": arguments}
                except Exception:
                    arguments = {"raw": raw_args}
            elif isinstance(raw_args, dict):
                arguments = raw_args
            else:
                arguments = {}

            tool_name = function.get("name") or call.get("name") or ""
            action = {
                "tool": tool_name,
                "arguments": arguments,
                "resources": resources_from_arguments(tool_name, arguments),
            }
            tcid = call.get("id") or ""
            result = tool_results.get(tcid)
            if result is not None:
                action["result"] = str(result.get("content") or "")
            actions.append(action)
    return actions


# 当前轮轨迹截取：从完整消息序列中只保留最后一轮用户输入之后的部分（F-3-3 ⑩）
def build_current_round_trajectory(messages: Optional[List[dict]]) -> List[dict]:
    """Keep only the last user -> assistant segment as current round."""
    if not isinstance(messages, list):
        return []
    last_user_idx = None
    for idx, msg in enumerate(messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            last_user_idx = idx
    if last_user_idx is None:
        return []
    return [msg for msg in messages[last_user_idx:] if isinstance(msg, dict)]

# ═══════════════════════════════════════════════════════════════════════════════
# Gateway Log Reader (date-based JSONL)
# ═══════════════════════════════════════════════════════════════════════════════

# 按起始时间读取当天网关日志：Portkey 按日期分文件，跳过早于 start_dt 的记录
def read_gateway_logs_since(log_dir: Path, start_dt: Optional[datetime]) -> Iterable[dict]:
    """Read gateway log entries since start_dt, yield each JSON object."""
    if not log_dir or not log_dir.exists():
        return

    # Determine date file
    if start_dt:
        date_str = start_dt.strftime("%Y-%m-%d")
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")

    path = log_dir / f"{date_str}.jsonl"
    if not path.exists():
        # Try all recent jsonl files
        candidates = sorted(log_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            path = candidates[0]
        else:
            return

    start_epoch = to_epoch(start_dt) if start_dt else None
    past_start = start_epoch is None

    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    obj = json.loads(ln)
                except Exception:
                    continue
                if not past_start:
                    entry_dt = parse_timestamp_from_obj(obj)
                    entry_epoch = to_epoch(entry_dt, start_dt)
                    if entry_epoch is None or (start_epoch and entry_epoch < start_epoch):
                        continue
                    past_start = True
                yield obj
    except Exception:
        return


# ═══════════════════════════════════════════════════════════════════════════════
# Monitor Orchestrator
# ═══════════════════════════════════════════════════════════════════════════════

def format_bj_time() -> str:
    """
    当前北京时间字符串（日志与上报统一时区口径）。

    Returns:
        '%Y-%m-%d %H:%M:%S.%f+0800' 格式文本。
    """
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    # 全局上报 API 地址（由配置注入，缺省指向本机后端）
    return now.strftime("%Y-%m-%d %H:%M:%S.") + f"{now.microsecond // 1000:03d}+0800"


# 上报入口：独立线程 + 超时控制，失败只记日志（监控主循环永不阻塞）
def report_to_clawavc(data: dict) -> None:
    """Non-blocking POST to clawAVC /api/rounds."""
    # 调试日志
    if data.get("event") == "end":
        print(
            f"[report_to_clawavc] event=end round_id={data.get('round_id')} "
            f"time_end={data.get('time_end', 'N/A')[:30] if data.get('time_end') else 'N/A'} "
            f"last_llm_msg_len={len(data.get('last_llm_message', '') or '')}",
            flush=True,
        )
    
    def _do_post():
        """
        上报的实际 HTTP POST 实现（独立线程函数）。

        超时/连接失败只记日志不抛异常——保证监控主循环永不被上报故障阻塞。

        Args:
            url / payload: 目标地址与请求体。
        """
        try:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                # 非阻塞上报：失败仅记日志，主循环永不因上报故障中断（R-3-4 对应实现）
                CLAWAVC_ROUNDS_API,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                code = resp.getcode()
                if code >= 400:
                    print(
                        f"[report_to_clawavc] HTTP {code} event={data.get('event')} "
                        f"round_id={data.get('round_id')}",
                        flush=True,
                    )
        except Exception as e:
            # 打出失败原因，便于排查"IR 没回填"等链路问题
            print(
                f"[report_to_clawavc] POST failed event={data.get('event')} "
                f"round_id={data.get('round_id')} ir_len="
                # IR 回填失败打印占位长度与错误：便于区分翻译失败与上报失败两种故障
                f"{len(data.get('ir_json','') or '')} err={e}",
                flush=True,
            )
    threading.Thread(target=_do_post, daemon=True).start()


# 监控配置读取：路径、上报地址、规则开关等生产配置的统一入口
def get_config_from_db() -> Dict[str, str]:
    """Read monitor config from clawAVC backend API."""
    try:
        req = urllib.request.Request("http://127.0.0.1:15100/api/monitor/config")
        with urllib.request.urlopen(req, timeout=3) as resp:
            body = resp.read().decode("utf-8")
        parsed = json.loads(body)
        if parsed.get("ok"):
            return parsed.get("data", {})
    except Exception:
        pass
    return {}


# 参数内容检测规则热加载：severity 与 enable 由配置层注入，规则组件零改动
def load_param_content_rules() -> Optional[Dict[str, Any]]:
    """从监控配置读取「参数内容深度检查规则」（JSON 字符串）；未配置返回 None（用内置默认）。"""
    from typing import Any as _Any, Dict as _Dict, Optional as _Optional
    # 注意：get_config_from_db() 返回的是 /api/monitor/config 的 data，键名不带 monitor_conf. 前缀
    raw = str(get_config_from_db().get("param_content_rules", "") or "")
    if not raw.strip():
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


# 提示注入关键词库热加载：无需冷启动即可更新扫描词表
def load_injection_keywords() -> List[str]:
    """从监控配置读取「工具返回结果提示注入监测关键词」（每行一个）。"""
    raw = str(get_config_from_db().get("tool_result_injection_keywords", "") or "")
    return [line.strip() for line in raw.splitlines() if line.strip()]


# 攻击配置快照：round_start 时固化本轮全部攻击开关，落库供事后还原实验条件
def get_attack_config_snapshot() -> str:
    """Read full attack tool-injection config via clawAVC API (key empty = all).

    复用对外接口 /api/attack/tool-config，返回其 data 字段的 JSON 字符串，
    作为本轮开始时刻的攻击配置快照。
    """
    try:
        req = urllib.request.Request("http://127.0.0.1:15100/api/attack/tool-config")
        with urllib.request.urlopen(req, timeout=3) as resp:
            body = resp.read().decode("utf-8")
        parsed = json.loads(body)
        if parsed.get("ok"):
            return json.dumps(parsed.get("data", {}), ensure_ascii=False)
    except Exception:
        pass
    return ""


# 长文本截断：保头保尾折叠中间，供上报与提示词注入使用
def truncate_text(text: str, max_len: int = 2000) -> str:
    """Truncate text with [Truncated] marker if too long."""
    if not text or len(text) <= max_len:
        return text
    return text[:max_len] + " [Truncated]"


# 历史上下文提取：定位含该轮次的会话文件，回放用户输入之前的消息（会话延续场景）
# 定位重试 + 边界匹配：文件可能晚于 round_start 数秒落盘，短重试后按 before/after 切分
def extract_history_for_round(openclaw_root: Path, round_id: str) -> List[Dict[str, Any]]:
    """Extract conversation history before the current round from OpenClaw session logs.
    
    This function is called when a round starts, to capture the context/history
    before the current round begins. Includes user messages, assistant messages,
    tool calls, and tool results.
    
    OpenClaw JSONL format:
      {"type": "message", "id": "...", "parentId": "...", "message": {"role": "user", "content": "text"}}
      {"type": "message", "id": "...", "parentId": "...", "message": {"role": "assistant", "content": [{"type": "text", "text": "..."}]}}
      {"type": "message", "id": "...", "parentId": "...", "message": {"role": "assistant", "content": [{"type": "toolCall", "name": "...", "arguments": {...]}]}}
      {"type": "message", "id": "...", "parentId": "...", "message": {"role": "toolResult", "content": [{"type": "text", "text": "..."}]}}
    """
    history = []
    
    sessions_dir = openclaw_root / "agents" / "main" / "sessions"
    if not sessions_dir.exists():
        return history
    
    # 重试机制：/clear 后第一条消息时，session 文件可能还没写入磁盘
    target_file = None
    for retry in range(5):
        session_files = sorted(sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        
        # Find session file containing this round_id
        for sf in session_files[:10]:
            try:
                text = sf.read_text(encoding="utf-8", errors="replace")
                if round_id in text:
                    target_file = sf
                    break
            except Exception:
                continue
        
        if target_file:
            break
        
        # 如果没找到，等待一下再重试
        if not target_file and retry < 4:
            time.sleep(0.2)
    
    # 如果没找到包含 round_id 的文件，尝试使用最新的 session 文件
    if not target_file and session_files:
        target_file = session_files[0]
        print(f"[monitor] extract_history: no file contains round_id={round_id}, using latest: {target_file.name}", flush=True)
    elif not target_file:
        print(f"[monitor] extract_history: no session files found for round_id={round_id}", flush=True)
        return history
    
    # 读取文件内容用于调试
    try:
        file_text = target_file.read_text(encoding="utf-8", errors="replace")
        print(f"[monitor] extract_history: file size={len(file_text)}, round_id={round_id}, round_id in file={round_id in file_text}", flush=True)
    except Exception as e:
        print(f"[monitor] extract_history: error reading file: {e}", flush=True)
    
    found_round = False
    pending_tool_calls: Dict[str, List[Dict[str, Any]]] = {}  # assistant_id -> tool calls
    
    try:
        with target_file.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                
                # 只处理 type="message" 的行
                if obj.get("type") != "message":
                    continue
                
                msg_id = obj.get("id", "")
                parent_id = obj.get("parentId", "")
                msg = obj.get("message", {})
                role = msg.get("role", "")
                content = msg.get("content", [])
                
                # Find the user message that starts this round
                if msg_id == round_id and role == "user":
                    found_round = True
                    continue  # 跳过当前轮次的 query
                
                # 收集当前 round 之前的对话上下文作为 history
                if not found_round:
                    if role == "user":
                        # User 消息的 content 可能是字符串或数组
                        if isinstance(content, str):
                            user_text = content
                        elif isinstance(content, list):
                            user_text = ""
                            for c in content:
                                if isinstance(c, dict) and c.get("type") == "text":
                                    user_text = c.get("text", "")
                                    break
                        else:
                            user_text = str(content)
                        
                        if user_text:
                            # 清理发送者元数据
                            user_text = re.sub(r"Sender\s*\(untrusted metadata\):\s*```json\s*\{[^}]*\}\s*```\s*", "", user_text, flags=re.DOTALL).strip()
                            lines_t = [l.strip() for l in user_text.splitlines() if l.strip()]
                            if lines_t:
                                last_line = re.sub(r"^\[.*?\]\s*", "", lines_t[-1])
                                if last_line:
                                    history.append({"type": "user", "content": truncate_text(last_line, 500)})
                    
                    elif role == "assistant" and isinstance(content, list):
                        # 处理 assistant 消息，可能包含 tool 调用和文本
                        text_parts = []
                        tool_calls = []
                        for c in content:
                            if isinstance(c, dict):
                                if c.get("type") == "text":
                                    text_parts.append(c.get("text", ""))
                                elif c.get("type") == "toolCall":
                                    # 保存 toolCall 的 id 以便后续匹配 toolResult
                                    tool_calls.append({
                                        "id": c.get("id", ""),
                                        "tool": c.get("name", ""),
                                        "arguments": c.get("arguments", {}),
                                    })
                        
                        # 添加 assistant 文本（如果有）
                        if text_parts:
                            text_content = "\n".join(text_parts)
                            if text_content.strip():
                                history.append({"type": "assistant", "content": truncate_text(text_content, 500)})
                        
                        # 记录 tool 调用，等待 toolResult
                        if tool_calls and msg_id:
                            pending_tool_calls[msg_id] = tool_calls
                    
                    elif role == "toolResult":
                        # 处理工具结果 - toolResult 使用 toolCallId 而不是 parentId
                        tool_call_id = obj.get("toolCallId", "") or msg.get("toolCallId", "")
                        tool_name = obj.get("toolName", "") or msg.get("toolName", "") or "unknown"
                        
                        result_text = ""
                        if isinstance(content, list):
                            for c in content:
                                if isinstance(c, dict) and c.get("type") == "text":
                                    result_text += c.get("text", "")
                        elif isinstance(content, str):
                            result_text = content
                        
                        # 通过 toolCallId 找到对应的 tool 调用
                        # 需要遍历所有 pending_tool_calls 找到包含这个 toolCallId 的
                        found_tool_call = False
                        for parent_id, tools in list(pending_tool_calls.items()):
                            for tool_info in tools:
                                if tool_info.get("id") == tool_call_id:
                                    found_tool_call = True
                                    # 添加工具调用
                                    history.append({
                                        "type": "tool_call",
                                        "tool": tool_name,
                                        "arguments": truncate_text(str(tool_info.get("arguments", {})), 300),
                                    })
                                    # 添加工具结果
                                    if result_text:
                                        history.append({
                                            "type": "tool_result",
                                            "tool": tool_name,
                                            "content": truncate_text(result_text[:1000], 500),
                                        })
                                    break
                            if found_tool_call:
                                break
                        
                        # 如果没找到对应的 tool_call，直接添加 tool_result
                        if not found_tool_call and result_text:
                            history.append({
                                "type": "tool_result",
                                "tool": tool_name,
                                "content": truncate_text(result_text[:500], 500),
                            })
                    
                    continue
                
                # If we hit a new user message after finding the round, stop
                if role == "user" and msg_id != round_id:
                    break
                    
    except Exception as e:
        print(f"[monitor] extract_history_for_round error: {e}", flush=True)
    
    # 只保留最近 20 条历史消息（因为现在包含更多类型）
    return history[-20:]


# 会话文件中提取本轮用户请求：与网关侧提取结果互为校验与补齐
def extract_user_query_from_session(openclaw_root: Path, round_id: str) -> Optional[str]:
    """Extract user query from OpenClaw session logs by round_id.
    
    This is used as a fallback when gateway logs haven't been written yet.
    """
    sessions_dir = openclaw_root / "agents" / "main" / "sessions"
    if not sessions_dir.exists():
        return None
    
    # Find session file containing this round_id
    session_files = sorted(sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for sf in session_files[:10]:
        try:
            text = sf.read_text(encoding="utf-8", errors="replace")
            if round_id in text:
                # Found the session file, now extract the user query
                with sf.open("r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except Exception:
                            continue
                        
                        # Only process message type
                        if obj.get("type") != "message":
                            continue
                        
                        msg_id = obj.get("id", "")
                        msg = obj.get("message", {})
                        role = msg.get("role", "")
                        content = msg.get("content", [])
                        
                        # Found the user message for this round
                        if msg_id == round_id and role == "user":
                            if isinstance(content, str):
                                user_text = content
                            elif isinstance(content, list):
                                user_text = ""
                                for c in content:
                                    if isinstance(c, dict) and c.get("type") == "text":
                                        user_text = c.get("text", "")
                                        break
                            else:
                                user_text = str(content)
                            
                            if user_text:
                                # Clean up sender metadata
                                user_text = re.sub(r"Sender\s*\(untrusted metadata\):\s*```json\s*\{[^}]*\}\s*```\s*", "", user_text, flags=re.DOTALL).strip()
                                lines_t = [l.strip() for l in user_text.splitlines() if l.strip()]
                                if lines_t:
                                    last_line = re.sub(r"^\[.*?\]\s*", "", lines_t[-1])
                                    if last_line:
                                        return last_line.strip()
                            break
        except Exception:
            continue
    
    return None


# 会话提取的完整入口：定位文件 → 逐行解析 → 截取当前轮 → 还原行为（生产判定数据源之一）
def extract_from_openclaw_session(openclaw_root: Path, round_id: str, start_time: float) -> Dict[str, Any]:
    """Extract user_query, actions (with results), last_llm_message from OpenClaw session logs.
    
    OpenClaw log format:
      assistant (stopReason=toolUse): content[] has {type:toolCall, id, name, arguments}
      toolResult (parentId=assistant.id): content[] has {type:text, text:result_text}
      assistant (stopReason=stop): content[] has {type:text, text:final_reply}
    """
    result = {"user_query": None, "actions": [], "last_llm_msg": None, "history": None}
    
    sessions_dir = openclaw_root / "agents" / "main" / "sessions"
    if not sessions_dir.exists():
        return result
    
    # Find session file containing this round_id
    session_files = sorted(sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    target_file = None
    for sf in session_files[:10]:
        try:
            text = sf.read_text(encoding="utf-8", errors="replace")
            if round_id in text:
                target_file = sf
                break
        except Exception:
            continue
    
    if not target_file:
        return result
    
    found_round = False
    actions = []
    last_assistant_text = None
    # Track pending tool calls by assistant message id
    pending_tool_calls: Dict[str, List[dict]] = {}  # assistant_id -> [action dicts]
    pending_by_tool_id: Dict[str, dict] = {}
    current_assistant_id = ""
    
    try:
        with target_file.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                
                msg_id = obj.get("id", "")
                parent_id = obj.get("parentId", "")
                msg = obj.get("message", {})
                role = msg.get("role", "")
                content = msg.get("content", [])
                stop_reason = msg.get("stopReason", "")
                
                # Find the user message that starts this round
                if msg_id == round_id and role == "user":
                    found_round = True
                    if isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict) and c.get("type") == "text":
                                text = c.get("text", "")
                                import re as _re
                                text = _re.sub(r"Sender\s*\(untrusted metadata\):\s*```json\s*\{[^}]*\}\s*```\s*", "", text, flags=_re.DOTALL).strip()
                                lines_t = [l.strip() for l in text.splitlines() if l.strip()]
                                if lines_t:
                                    last_line = _re.sub(r"^\[.*?\]\s*", "", lines_t[-1])
                                    if last_line:
                                        result["user_query"] = last_line
                    continue
                
                if not found_round:
                    continue

                # If we hit a new user message, this round is over
                if role == "user" and msg_id != round_id:
                    break
                
                # Assistant with tool calls
                if role == "assistant" and isinstance(content, list):
                    tool_calls_in_msg = []
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "toolCall":
                            action = {
                                "tool": c.get("name", ""),
                                "arguments": c.get("arguments", {}),
                                "resources": resources_from_arguments(c.get("name", ""), c.get("arguments", {})),
                            }
                            tool_calls_in_msg.append(action)
                            actions.append(action)
                            if c.get("id"):
                                pending_by_tool_id[c["id"]] = action
                        elif isinstance(c, dict) and c.get("type") == "text" and c.get("text"):
                            last_assistant_text = c.get("text", "")
                    
                    if tool_calls_in_msg and msg_id:
                        pending_tool_calls[msg_id] = tool_calls_in_msg
                        current_assistant_id = msg_id
                    
                    if stop_reason in ("stop", "end_turn", "complete"):
                        break
                
                # toolResult - attach result to matching action
                if role == "toolResult" and isinstance(content, list):
                    result_text = ""
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            result_text += c.get("text", "")
                    
                    tool_call_id = msg.get("toolCallId") or msg.get("tool_call_id")
                    matched = pending_by_tool_id.get(tool_call_id)
                    if matched is not None:
                        matched["result"] = result_text[:2000]
                    # 内存状态按轮次清理：rounds/ir_result/judge_done 在结束后统一回收
                    # Older logs may only identify the parent assistant message.
                    elif parent_id in pending_tool_calls:
                        parent_actions = pending_tool_calls[parent_id]
                        # Attach result to first action without result
                        for pa in parent_actions:
                            if "result" not in pa:
                                pa["result"] = result_text[:2000]
                                break
    except Exception:
        pass
    
    result["actions"] = actions
    # 全部网络出口集中在 report/turn-ir 两处：便于统一加超时、重试与失败日志
    result["last_llm_msg"] = last_assistant_text
    return result
# 隔离边界：IR 翻译失败只影响 ir_json/判定两个字段，round_start/end 照常上报（R-3-4）

# 监控编排器：会话日志追踪 + 轮次状态机 + 网关解析 + IR 翻译 + 四维判定 + 上报的总装配
# 设计原则：旁路采集——各环节均为异步/非阻塞，监控故障不影响被监控 Agent 的正常运行
class MonitorOrchestrator:
    """Main monitor process that coordinates watcher + gateway + IR + judge."""

    # LOADING_MARKER：占位哨兵值——前端识别「翻译中」状态、网关遇此值按未就绪处理
    LOADING_MARKER = "__loading__"

    def __init__(self, openclaw_log_root: str = DEFAULT_OPENCLAW_LOG_ROOT, gateway_log_path: str = ""):
        """
        监控编排器构造函数。

        Args:
            openclaw_log_root: OpenClaw 根目录；
            gateway_log_path: Portkey 网关日志目录。

        内部：文件追踪器、轮次状态机、IR 客户端、判定器与工作线程。
        """
        self.openclaw_log_root = Path(openclaw_log_root).expanduser()
        self.gateway_log_path = Path(gateway_log_path) if gateway_log_path else None
        self.running = False
        self._round_start_times: Dict[str, float] = {}
        self._round_ir_results: Dict[str, Dict] = {}
        self._round_queries: Dict[str, str] = {}
        # tool_trace 写入失败静默：不影响事件流继续处理
        # 表按 round_id 生命周期清理：判定完成后保留至轮次被覆盖，防止内存增长
        self._round_workers: Dict[str, threading.Thread] = {}
        self._round_histories: Dict[str, List[Dict[str, str]]] = {}  # 存储每个 round 的 history
        self._round_actions: Dict[str, List[Dict]] = {}  # 存储每个 round 的 actions
        # 判定去重登记：round_end 与 IR 工作线程都可能触发判定，先到先执行、后到跳过
        self._round_judge_done: Dict[str, bool] = {}  # 标记 judge 是否已完成，防止重复执行
        # Cache the OpenClaw main process across rounds: (pid, starttime_ticks).
        # If the cached PID still exists with the same starttime at the next
        # round_start, proc_info.collect_for_round skips its full /proc scan.
        self._main_pid_cache = None
        # 轮次工作线程登记表：round_id → Thread，异常隔离与优雅退出使用
        
        # 存储 tool_started 的信息，用于在 tool_completed 时关联
        # tool_trace 落盘路径由配置注入，缺省 infos/translator 下按日期分文件
        # key: toolCallId, value: {toolName, paramsPreview, ...}
        self._pending_tool_traces: Dict[str, Dict[str, Any]] = {}

        self.sm = RoundStateMachine(
            # tool_trace 同时是 F-3-3/F-3-4 单元测试的输入来源
            on_round_start=self._on_round_start,
            on_round_end=self._on_round_end,
        )

    # 工具调用落痕（tool_trace）：按 phase（开始/完成）写独立日志，供参数深度检测与回放
    # phase 取值：tool_started / tool_completed / routing_response，与 ParsedEvent.kind 对齐
    def _write_tool_trace(self, line: str, ev: ParsedEvent, phase: str) -> None:
        """当检测到 tool_started/tool_completed 时，提取 tool 信息并写入 JSONL 文件。
        
        phase 可以是 "before_tool_call" 或 "after_tool_call"
        
        输出格式：
        {
            "phase": "before_tool_call" | "after_tool_call",
            "ts": "2026-06-25T14:40:01.000Z",
            "toolName": "read",
            "toolCallId": "call_xxx",
            "runId": "xxx",
            "paramsPreview": "{\"path\":\"/tmp/test\"}",  // before 阶段
            "resultPreview": "file content...",  // after 阶段
            "agentId": "main",
            "sessionId": "xxx",
            "sessionKey": "agent:main:main"
        }
        
        注意：此功能通过后端配置项 tool_trace_enabled 控制，默认关闭。
        """
        # 检查开关是否开启
        try:
            config = get_config_from_db()
            if config.get("tool_trace_enabled", "false").lower() != "true":
                return
        except Exception:
            return  # 默认关闭
        
        try:
            obj = json.loads(line)
        except Exception as e:
            print(f"[monitor] Failed to parse line: {e}", flush=True)
            return
        
        flat = flatten_dict(obj)
        
        # 提取 tool 信息
        # 关键：tool_call_id 必须使用真正的工具调用 ID（OpenAI 协议下的 call_xxx），
        # 这样 before/after 两个阶段才能配对。绝不能回退到外层 `id`（那是日志行 ID，
        # 历史提取：定位含该 round_id 的会话文件，取用户输入之前的上下文消息
        # 短 hex 形如 "34682b2a"，与工具调用无关），否则会出现 before/after 不一致。
        #
        # 取值优先级：
        #   1) message.toolCallId / message.tool_call_id  —— after 阶段 toolResult 的常见位置
        #   2) message.content[].toolCall.id              —— before 阶段 (Anthropic 风格)
        #   3) message.content[].tool_calls[].id          —— before 阶段 (OpenAI 风格)
        tool_name = flat.get("message.toolName") or flat.get("message.tool_name") or ""
        tool_call_id = flat.get("message.toolCallId") or flat.get("message.tool_call_id") or ""

        # 始终扫描一次 content：补全 toolName，并在 tool_call_id 缺失时从 content 里取
        msg = obj.get("message", {})
        if isinstance(msg, dict):
            content = msg.get("content", [])
            if isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    item_type = item.get("type")
                    if item_type == "toolCall":
                        if not tool_name:
                            tool_name = item.get("name", "") or tool_name
                        if not tool_call_id:
                            tool_call_id = item.get("id", "") or tool_call_id
                        if tool_name and tool_call_id:
                            break
                    elif item_type == "tool_calls":
                        # tool_calls 是一个数组
                        tool_calls = item.get("tool_calls", [])
                        if isinstance(tool_calls, list) and len(tool_calls) > 0:
                            first_call = tool_calls[0]
                            # IR 翻译触发：先以 __loading__ 占位立即回填，翻译完成后覆盖（F-3-9 顺序约定）
                            if isinstance(first_call, dict):
                                function = first_call.get("function", {})
                                if isinstance(function, dict) and not tool_name:
                                    tool_name = function.get("name", "") or tool_name
                                if not tool_call_id:
                                    tool_call_id = first_call.get("id", "") or tool_call_id
                        if tool_name and tool_call_id:
                            break

        if not tool_name:
            print(f"[monitor] No tool_name found, skipping write", flush=True)
            return
        
        # 提取参数预览 (before 阶段)
        params_preview = ""
        if phase == "before_tool_call":
            arguments = flat.get("message.arguments") or flat.get("arguments")
            if isinstance(arguments, dict):
                params_preview = json.dumps(arguments, ensure_ascii=False)
            elif isinstance(arguments, str):
                params_preview = arguments
            
            # 如果还没有参数，尝试从 tool_calls 中提取
            if not params_preview:
                msg = obj.get("message", {})
                if isinstance(msg, dict):
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict):
                                if item.get("type") == "toolCall":
                                    args = item.get("arguments", {})
                                    if isinstance(args, dict):
                                        params_preview = json.dumps(args, ensure_ascii=False)
                                    elif isinstance(args, str):
                                        params_preview = args
                                    break
                                elif item.get("type") == "tool_calls":
                                    tool_calls = item.get("tool_calls", [])
                                    if isinstance(tool_calls, list) and len(tool_calls) > 0:
                                        first_call = tool_calls[0]
                                        if isinstance(first_call, dict):
                                            function = first_call.get("function", {})
                                            if isinstance(function, dict):
                                                args = function.get("arguments", {})
                                                if isinstance(args, str):
                                                    try:
                                                        params_preview = args
                                                    except:
                                                        pass
                                                # 判定器接入：行为与 IR 齐备后由 judge 模块给出四维判定文本与得分
                                                elif isinstance(args, dict):
                                                    params_preview = json.dumps(args, ensure_ascii=False)
        
        # 提取结果预览 (after 阶段)
        result_preview = ""
        if phase == "after_tool_call":
            # 从 content 中提取结果文本
            msg = obj.get("message", {})
            if isinstance(msg, dict):
                content = msg.get("content", [])
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text = item.get("text", "")
                            if text:
                                result_preview = text
                                break
                elif isinstance(content, str):
                    result_preview = content
        
        # 构建输出记录
        record = {
            "phase": phase,
            "ts": flat.get("time") or flat.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            "toolName": tool_name,
            "toolCallId": tool_call_id,
            "runId": flat.get("runId") or flat.get("run_id") or flat.get("message.runId") or "",
            "paramsPreview": params_preview[:500] if params_preview else "",
            "resultPreview": result_preview[:500] if result_preview else "",
            "agentId": flat.get("agentId") or flat.get("agent_id") or flat.get("message.agentId") or "main",
            "sessionId": flat.get("sessionId") or flat.get("session_id") or flat.get("message.sessionId") or "",
            "sessionKey": flat.get("sessionKey") or flat.get("session_key") or ev.session_key,
        }
        
        # 写入 JSONL 文件
        try:
            trace_file = Path("/tmp/openclaw-tool-trace.jsonl")
            with trace_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"[monitor] Wrote tool trace: phase={phase}, tool={tool_name}, callId={tool_call_id}", flush=True)
        except Exception as e:
            print(f"[monitor] Failed to write tool trace: {e}", flush=True)

    def _get_gateway_dir(self) -> Optional[Path]:
        """
        取网关日志目录（支持运行时热切换配置）。

        Returns:
            网关日志目录 Path。
        """
        config = get_config_from_db()
        gw_path = config.get("gateway_log_path", "")
        if gw_path:
            self.gateway_log_path = Path(gw_path)
        if self.gateway_log_path and self.gateway_log_path.exists():
            return self.gateway_log_path if self.gateway_log_path.is_dir() else self.gateway_log_path.parent
        return None

    # pid 快照缓存（_main_pid_cache）：主进程定位结果跨轮复用，降低 /proc 扫描开销
    def _should_use_gateway(self) -> bool:
        """Check config: whether to use gateway logs for action data."""
        config = get_config_from_db()
        return config.get("use_gateway", "false").lower() == "true"


    # round_start 阶段的攻击配置快照保证实验可复现：每轮固化当时的全部攻击开关
    def _on_round_start(self, r: RoundLedger) -> None:
        """
        轮次开始回调：pid 快照 + 历史提取 + round_start 上报 + IR 工作线程。

        流程：
            1. 通知 turn-ir 长轮询层清理上一轮残留；
            2. 采集 OpenClaw 主进程与工具子进程快照（SELinux 标签等）；
            3. 提取对话上下文 history；
            4. 非阻塞上报 round_start（含攻击配置快照）；
            5. 启动 _query_and_ir_worker 完成用户请求提取与 IR 占位/回填。

        Args:
            r: 轮次台账。
        """
        self._round_start_times[r.round_id] = r.started_at
        print(f"[monitor] ROUND_STARTED round_id={r.round_id} session={r.session_key} time={format_bj_time()}", flush=True)

        # 长轮询残留清理防止跨轮串白名单：上一轮 IR 绝不泄漏到新一轮
        # 通知 clawAVC turn-ir long-poll 层：新一轮开始，清掉上一轮残留的 pending Event，
        # 避免上一轮卡死的长轮询线程占着 wait 直到 5 分钟超时。
        try:
            from app import _turn_ir_reset_for_new_round  # type: ignore
            _turn_ir_reset_for_new_round()
        except Exception as e:
            print(f"[monitor] turn-ir reset on round_start failed: {e}", flush=True)

        session_key = r.session_key if r.session_key != "unknown" else ""
        session_id = r.ids.get("session_id") or r.ids.get("sessionId") or ""
        # 从 API 读取当前攻击配置（key 空=全部），作为本轮快照随上报固化
        attack_config = get_attack_config_snapshot()

        # Snapshot the OpenClaw main agent process and ALL its tool-calling
        # subprocesses (each with their own SELinux/AppArmor label). The
        # main process is located via cmdline match against 'openclaw' (with
        # cwd boost when it's under self.openclaw_log_root) — NOT via fd
        # writers of the JSONL, since most loggers close-and-reopen on each
        # write. Result is cached across rounds via _main_pid_cache.
        pid_info = ""
        try:
            pid_info_data = collect_for_round(
                openclaw_root=str(self.openclaw_log_root) if self.openclaw_log_root else "",
                jsonl_path=r.source_file or "",
                cached_main=self._main_pid_cache,
            )
            disc = pid_info_data.get("discovery") or {}
            main_obj = pid_info_data.get("main") or {}
            main_pid = main_obj.get("pid")
            main_starttime = (main_obj.get("start_time") or {}).get("clock_ticks")
            if main_pid and main_starttime is not None:
                self._main_pid_cache = (main_pid, main_starttime)

            pid_info = json.dumps(pid_info_data, ensure_ascii=False, default=str)
            descendants_count = len(pid_info_data.get("descendants") or [])
            print(
                f"[monitor] pid_info captured: "
                f"pid={main_pid} method={disc.get('method')} "
                f"main_label={pid_info_data.get('main_selinux_label')!r} "
                f"descendants={descendants_count} "
                f"ms={pid_info_data.get('collect_duration_ms')}",
                flush=True,
            )
            if pid_info_data.get("error"):
                print(f"[monitor] pid_info note: {pid_info_data['error']}", flush=True)
        except Exception as e:
            print(f"[monitor] pid_info capture failed: {e}", flush=True)

        # 在 round start 时提取 history（对话上下文）
        history = []
        openclaw_root_str = str(self.openclaw_log_root) if self.openclaw_log_root else ""
        # IR 客户端独立于翻译模块：HTTP 边界隔离，翻译服务故障不影响采集主链
        print(f"[monitor] About to extract history for round_id={r.round_id}, openclaw_root={openclaw_root_str}", flush=True)
        try:
            history = extract_history_for_round(self.openclaw_log_root, r.round_id)
            if history:
                self._round_histories[r.round_id] = history
                print(f"[monitor] History captured for {r.round_id}: {len(history)} messages", flush=True)
            else:
                print(f"[monitor] No history found for {r.round_id}", flush=True)
        except Exception as e:
            print(f"[monitor] Failed to capture history for {r.round_id}: {e}", flush=True)

        # 立即上报 start 事件，包含 history
        report_to_clawavc({
            "event": "start",
            # IR 占位策略：先写 __loading__ 占位记录（前端立即可见），翻译完成后覆盖——两段式回填
            "round_id": r.round_id,
            "time_start": datetime.fromtimestamp(r.started_at, tz=ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + "+0800",
            "session_key": session_key,
            "session_id": session_id,
            "attack_config": attack_config,
            "pid_info": pid_info,
            # 用户请求提取成功即触发翻译：IR 与 Agent 首轮推理并行执行，白名单尽早生效
            "history": json.dumps(history, ensure_ascii=False) if history else "",
        })

        t = threading.Thread(target=self._query_and_ir_worker, args=(r.round_id, r.started_at), daemon=True)
        self._round_workers[r.round_id] = t
        t.start()

    # 双源提取次序：网关（结构化、快）→ 会话日志（兜底、稍慢），60×0.5s 重试覆盖日志落盘延迟
    def _query_and_ir_worker(self, round_id: str, start_time: float) -> None:
        """
        用户请求提取与 IR 翻译工作线程（round_start 后异步执行）。

        流程：
            1. 双源重试提取用户请求（网关→会话日志，最多 60×0.5s）；
            2. 提取成功后请求 IR 翻译（先占位 __loading__ 后回填）；
            3. IR 就绪即推送 turn-ir 长轮询缓存（网关白名单即时生效）；
            4. 行为齐备时启动延迟判定工作线程。

        Args:
            round_id / start_time: 轮次标识与开始时间。
        """
        start_dt = datetime.fromtimestamp(start_time, tz=ZoneInfo("Asia/Shanghai"))
        gw_dir = self._get_gateway_dir()

        user_query = None
        retry_count = 0
        for _ in range(60):
            if not self.running:
                return
            
            # 尝试从 gateway 日志提取
            if gw_dir:
                retry_count += 1
                for obj in read_gateway_logs_since(gw_dir, start_dt):
                    q = extract_user_query_from_obj(obj)
                    if q:
                        user_query = q
                        break
            
            # 如果 gateway 没找到，尝试从 session 文件提取
            if not user_query:
                user_query = extract_user_query_from_session(self.openclaw_log_root, round_id)
            
            if user_query:
                break
            time.sleep(0.5)
        
        print(f"[monitor] _query_and_ir_worker finished: round_id={round_id}, user_query={'found' if user_query else 'NOT FOUND'}, retries={retry_count}", flush=True)

        if not user_query:
            self._round_queries[round_id] = ""
            return

        self._round_queries[round_id] = user_query
        print(f"[monitor] Query found for {round_id}: {user_query[:60]}", flush=True)

        # 在找到 user_query 时重新提取 history（此时 session 文件已写入完整内容）
        try:
            history = extract_history_for_round(self.openclaw_log_root, round_id)
            if history:
                self._round_histories[round_id] = history
                print(f"[monitor] History extracted at query time for {round_id}: {len(history)} messages", flush=True)
            else:
                # 如果还是没有 history，使用之前存储的
                history = self._round_histories.get(round_id, [])
                print(f"[monitor] No history found at query time for {round_id}, using cached: {len(history)} messages", flush=True)
        except Exception as e:
            print(f"[monitor] Failed to extract history at query time for {round_id}: {e}", flush=True)
            # round_ir_ready 与 round_end 均通过同一 WebSocket 通道推送：事件序即审计序
            history = self._round_histories.get(round_id, [])

        report_to_clawavc({"event": "end", "round_id": round_id, "time_end": "", "user_query": user_query, "history": json.dumps(history, ensure_ascii=False) if history else "", "ir_json": self.LOADING_MARKER})

        try:
            ir_result, ir_error = ir_translate(query=user_query, round_id=round_id, use_llm=True)
            if ir_error:
                # 推送后网关按白名单放行或改写：无 IR 时网关按超时兜底策略处理，不无限等待
                print(f"[monitor] IR error for {round_id}: {ir_error}", flush=True)
            self._round_ir_results[round_id] = ir_result or {}
        except Exception as e:
            print(f"[monitor] IR exception for {round_id}: {e}", flush=True)
            self._round_ir_results[round_id] = {}

        ir_data = self._round_ir_results.get(round_id, {})
        
        # IR 就绪推送：round_ir_ready 事件唤醒网关长轮询，本轮工具白名单即时生效
        # IR 翻译完成后，更新 ir_json 到数据库，触发 round_ir_ready 推送
        if ir_data:
            try:
                import json as _json
                
                from auditor.monitor.watcher import format_bj_time
                payload = {
                    "event": "end",
                    "round_id": round_id,
                    "time_end": format_bj_time(),
                    "ir_json": _json.dumps(ir_data, ensure_ascii=False),
                }
                req = urllib.request.Request(
                    CLAWAVC_ROUNDS_API,
                    data=_json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=5)
                print(f"[monitor] IR updated for {round_id}", flush=True)
            except Exception as e:
                print(f"[monitor] Failed to update IR for {round_id}: {e}", flush=True)
        
        # 等待 actions 与 IR 就绪后调用 judge（事件驱动轮询，替代原固定 1.5s 延迟）
        # 原实现：sleep(1.5) 后只检查一次，若 round_end 提取 actions 晚于该时刻，
        #        会以 "No actions for <round>, skipping judge" 跳过，造成系统性丢判。
        # 现实现：在超时窗口内轮询，二者均就绪即判定；超时仍缺则沿用原跳过逻辑。
        # 可用环境变量 JUDGE_WAIT_TIMEOUT 调整等待上限（默认 15 秒）。
        # 延迟判定（worker 路径）：IR 与行为齐备即判，不等 round_end——正常完成轮次的最短路径
        # 判定异常兜底：返回合法空文本而非抛异常，保证上报链路不因判定缺陷中断
        def delayed_judge_worker():
            """
            延迟判定工作线程：等待行为与 IR 齐备后执行四维判定并上报。

            去重：_round_judge_done 标记保证每轮判定只执行一次；
            判定异常兜底为合法空文本，不阻塞主循环。
            """
            try:
                _timeout = float(os.environ.get("JUDGE_WAIT_TIMEOUT", "15"))
                _deadline = time.time() + _timeout
                _waited = 0.0
                current_actions = []
                current_ir_data = {}
                while True:
                    # 双路去重点：delayed_judge(end) 先执行时本路径直接让位，避免重复判定与重复上报
                    # 检查是否已被 delayed_judge(end) 先执行
                    if self._round_judge_done.get(round_id):
                        print(f"[monitor] Judge already done by delayed_judge(end) for {round_id}, skipping", flush=True)
                        return

                    # 获取最新的 actions 和 ir_data
                    current_actions = self._round_actions.get(round_id, [])
                    current_ir_data = self._round_ir_results.get(round_id, {})
                    if current_actions and current_ir_data:
                        break
                    if time.time() >= _deadline:
                        break
                    time.sleep(0.5)
                    _waited += 0.5

                print(f"[monitor] Delayed judge (worker) check for {round_id}: "
                      f"actions_count={len(current_actions)} ir_data_count={len(current_ir_data)} "
                      f"waited={_waited:.1f}s", flush=True)
                
                if current_actions and current_ir_data:
                    try:
                        judge_result = judge(current_actions, current_ir_data,
                                             injection_keywords=load_injection_keywords(),
                                             param_content_rules=load_param_content_rules())
                        import re as _re
                        score_match = _re.search(r"整体得分:\s*([0-9.]+)", judge_result)
                        judge_score = float(score_match.group(1)) if score_match else -1.0
                        
                        # 标记 judge 已完成
                        self._round_judge_done[round_id] = True
                        
                        # 只更新数据库，不广播
                        from auditor.monitor.watcher import format_bj_time as _fmt_time
                        payload = {
                            "event": "end",
                            "round_id": round_id,
                            "time_end": _fmt_time(),
                            "judge_result": judge_result,
                            "overall_score": judge_score,
                            # 会话兜底路径在网关轨迹缺失参数时仍能还原工具名与资源访问
                            "is_abnormal": 1 if 0 <= judge_score < 0.5 else 0,
                        }
                        import json as _json
                        req = urllib.request.Request(
                            CLAWAVC_ROUNDS_API,
                            data=_json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        urllib.request.urlopen(req, timeout=5)
                        print(f"[monitor] Judge result updated (worker) for {round_id}: score={judge_score}", flush=True)
                    except Exception as e:
                        print(f"[monitor] Judge error for {round_id}: {e}", flush=True)
                elif not current_actions:
                    print(f"[monitor] No actions for {round_id}, skipping judge (worker)", flush=True)
                elif not current_ir_data:
                    # 上报体 action_json 附带 MD5 摘要：采集侧防篡改（S-3-1 的写入端实现）
                    print(f"[monitor] No IR data for {round_id}, skipping judge (worker)", flush=True)
            except Exception as e:
                print(f"[monitor] Delayed judge (worker) error for {round_id}: {e}", flush=True)
        
        # 启动延迟 judge 线程
        judge_thread = threading.Thread(target=delayed_judge_worker, daemon=True)
        judge_thread.start()
        print(f"[monitor] Started delayed judge (worker) thread for {round_id}", flush=True)
        # 两条 actions 提取路径优先级：网关轨迹完整（含参数与结果）→ 会话轨迹兜底（无参数时）
        # round_end 的 judge_result 缺省为空：延迟判定经单字段更新接口补齐并刷新 MD5
        
        print(f"[monitor] IR ready for {round_id}", flush=True)

        # 发布到 clawAVC turn-ir long-poll 缓存：唤醒所有正在 wait 的 portkey 长轮询线程。
        # 此处必须用与 portkey/clawAVC 同款 normalize 规则做 cache key，
        # 由 _turn_ir_publish_translation 内部 _normalize_user_query 完成。
        try:
            from app import _turn_ir_publish_translation  # type: ignore
            _turn_ir_publish_translation(user_query, ir_data or {})
        except Exception as e:
            print(f"[monitor] turn-ir publish failed for {round_id}: {e}", flush=True)

    # round_end 上报八字段一次成型：time_end/user_query/action_json/ir_json/judge_result/overall_score/last_llm_message/session
    def _on_round_end(self, r: RoundLedger) -> None:
        """
        轮次结束回调：行为提取 + round_end 上报 + 延迟判定兜底。

        流程：
            1. 双路提取 actions（网关轨迹优先，OpenClaw 会话兜底）；
            2. 上报 round_end（八字段：time_end/user_query/action_json/
               ir_json/judge_result/overall_score/last_llm_message/session）；
            3. IR 未就绪或行为缺失时登记延迟判定，待证据齐备补判。

        Args:
            r: 轮次台账。
        """
        print(f"[monitor] ROUND_ENDED round_id={r.round_id} session={r.session_key} time={format_bj_time()}", flush=True)

        start_time = self._round_start_times.pop(r.round_id, r.started_at)
        start_dt = datetime.fromtimestamp(start_time, tz=ZoneInfo("Asia/Shanghai"))

        # 注意：不再等待 _query_and_ir_worker 线程
        # round_end 与 round_ir_ready 相互独立：IR 慢不影响轮次收口，缺失项由延迟判定补齐
        # round_end 和 round_ir_ready 是独立的，不应该互相阻塞
        # worker 线程会自己完成翻译并更新数据库
        _ = self._round_workers.pop(r.round_id, None)  # 只是清理，不等待

        user_query = self._round_queries.pop(r.round_id, None)
        # 注意：不要在这里 pop ir_result！让 delayed_judge 来消费
        # ir_result = self._round_ir_results.pop(r.round_id, None)  # 删除这行
        # 优先使用在 round start 时捕获的 history
        history = self._round_histories.pop(r.round_id, [])

        use_gw = self._should_use_gateway()
        trajectory = []
        last_llm_msg = None
        # 优先使用 _query_and_ir_worker 中提取的 actions
        actions = self._round_actions.get(r.round_id, [])
        
        if not actions:
            if use_gw:
                gw_dir = self._get_gateway_dir()
                if gw_dir:
                    for obj in read_gateway_logs_since(gw_dir, start_dt):
                        if not user_query:
                            q = extract_user_query_from_obj(obj)
                            if q:
                                user_query = q
                        messages = extract_messages_from_obj(obj)
                        if messages:
                            trajectory = build_current_round_trajectory(messages)
                        msg = extract_last_llm_message(obj)
                        if msg:
                            last_llm_msg = msg
                    actions = build_actions_from_trajectory(trajectory) if trajectory else []
            else:
                # 延迟判定沿用生产 judge()：与在线判定同一口径，回放/在线结果一致
                # Extract from OpenClaw session log
                oc_data = extract_from_openclaw_session(self.openclaw_log_root, r.round_id, start_time)
                if not user_query:
                    user_query = oc_data.get("user_query")
                actions = oc_data.get("actions", [])
                last_llm_msg = oc_data.get("last_llm_msg")
# 主循环 CPU 空转率 <1%：无新事件时仅做 inode 检查与空闲扫描

        # round_end 不再等待翻译完成
        # 翻译是异步进行的，round_end 只负责发送最终的 judge 结果
        # IR 结果保留在内存：延迟判定消费后由数据库读回口径统一，不做二次翻译
        # IR 数据保留在 self._round_ir_results 中，供 delayed_judge 消费

        # 存储 actions 供后续使用
        self._round_actions[r.round_id] = actions

        # 逐行解析无批处理依赖：解析耗时与行数线性，支持流式
        judge_result = ""
        judge_score = -1.0
        # 判定线程全部 daemon：主进程退出时无需等待，安全终止由 _stop 处理
        
        session_key = r.session_key if r.session_key != "unknown" else ""
        session_id = r.ids.get("session_id") or r.ids.get("sessionId") or ""

        # 检测到 agent turn 结束，立即发送 round_end
        # round_end 只需要 action_json，其他字段保持原值
        # 轮询间隔 0.5s：检测时延与 CPU 占用的平衡点（吞吐实测 30 万行/秒级扫描）
        # 不包含 overall_score，因为 round_end 推送只与 action 有关
        out = {
            "event": "end",
            "round_id": r.round_id,
            # 延迟判定的两类触发：IR 晚于 round_end 到达 / 行为由会话文件晚落盘
            "time_start": datetime.fromtimestamp(start_time, tz=ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + "+0800" if start_time else format_bj_time(),
            "time_end": format_bj_time(),
            "session_key": session_key,
            "session_id": session_id,
            "user_query": user_query or "(not found)",
            "last_llm_message": last_llm_msg or "",
            "history": json.dumps(history, ensure_ascii=False) if history else "",
            "action_json": json.dumps(actions, ensure_ascii=False),
        }

        report_to_clawavc(out)
        print(f"[monitor] Round ended: query={user_query or '(none)'} actions_count={len(actions)}", flush=True)

        # 延迟 1.5 秒后调用 judge，等待 IR 翻译完成
        # Judge 结果只更新数据库，不广播
        # 延迟判定（end 路径）：round_end 时证据未齐（IR 未就绪/行为缺失）登记后台补判
        def delayed_judge():
            """
            延迟判定闭包：轮次结束后异步补齐判定结果。

            复用 _query_and_ir_worker 的齐备性检查与判定链路；
            结果经单字段更新接口回填，MD5 摘要同步刷新。
            """
            try:
                # 等待 1.5 秒，让 IR 翻译完成
                time.sleep(1.5)
                
                # 检查是否已被 delayed_judge_worker 先执行
                if self._round_judge_done.get(r.round_id):
                    print(f"[monitor] Judge already done by delayed_judge(worker) for {r.round_id}, skipping", flush=True)
                    return
                
                # 获取最新的 actions 和 ir_data
                current_actions = self._round_actions.get(r.round_id, [])
                current_ir_data = self._round_ir_results.get(r.round_id, {})
                
                print(f"[monitor] Delayed judge (end) check for {r.round_id}: actions_count={len(current_actions)} ir_data_count={len(current_ir_data)}", flush=True)
                
                # run() 无限循环 + 优雅退出：SIGTERM 后完成当前批事件再退出
                if current_actions and current_ir_data:
                    try:
                        judge_result = judge(current_actions, current_ir_data,
                                             injection_keywords=load_injection_keywords(),
                                             param_content_rules=load_param_content_rules())
                        import re as _re
                        score_match = _re.search(r"整体得分:\s*([0-9.]+)", judge_result)
                        judge_score = float(score_match.group(1)) if score_match else -1.0
                        
                        # 标记 judge 已完成
                        self._round_judge_done[r.round_id] = True
                        
                        # 只更新数据库，不广播
                        from auditor.monitor.watcher import format_bj_time as _fmt_time
                        payload = {
                            "event": "end",
                            "round_id": r.round_id,
                            "time_end": _fmt_time(),
                            # 主循环 try/except 逐行兜底：解析异常打印行号后继续，不留断点
                            "judge_result": judge_result,
                            "overall_score": judge_score,
                            "is_abnormal": 1 if 0 <= judge_score < 0.5 else 0,
                        }
                        import json as _json
                        req = urllib.request.Request(
                            CLAWAVC_ROUNDS_API,
                            data=_json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        # 重扫描与 tail 在同一循环：新会话文件最迟 LOG_RESCAN_SECONDS 内纳入
                        # check_idle_end 每轮循环执行：网络断开场景（无显式结束事件）也能正确收口
                        urllib.request.urlopen(req, timeout=5)
                        print(f"[monitor] Judge result updated (end) for {r.round_id}: score={judge_score}", flush=True)
                    except Exception as e:
                        print(f"[monitor] Judge error for {r.round_id}: {e}", flush=True)
                elif not current_actions:
                    print(f"[monitor] No actions for {r.round_id}, skipping judge", flush=True)
                elif not current_ir_data:
                    print(f"[monitor] No IR data for {r.round_id}, skipping judge", flush=True)
            except Exception as e:
                print(f"[monitor] Delayed judge (end) error for {r.round_id}: {e}", flush=True)
        
        # 启动延迟 judge 线程
        judge_thread = threading.Thread(target=delayed_judge, daemon=True)
        judge_thread.start()
        print(f"[monitor] Started delayed judge (end) thread for {r.round_id}", flush=True)
    # 主循环：tail 新行 → parse_line → 状态机 apply；周期重扫纳入新文件；空转做空闲收尾
    # run 主循环：parse→apply→idle 检查三段式；异常逐行隔离，单行坏数据不中断监控
    def run(self) -> None:
        """Main blocking loop."""
        self.running = True
        print(f"[monitor] Starting monitor...", flush=True)
        print(f"[monitor] OpenClaw logs: {self.openclaw_log_root}", flush=True)
        print(f"[monitor] Gateway logs: {self.gateway_log_path or '(from config)'}", flush=True)

        # Discover openclaw log files
        # 文件集初始发现：启动即全量扫描 OpenClaw 根目录
        files = discover_log_files(self.openclaw_log_root)
        if not files:
            print(f"[monitor] WARNING: No log files found in {self.openclaw_log_root}", flush=True)

        tailer = FileTailer(files, from_end=True)
        last_rescan = time.time()

        def _stop(signum, frame):
            """
            SIGTERM/SIGINT 处理：优雅退出主循环。

            Args:
                signum / frame: 信号参数。
            """
            self.running = False

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)

        while self.running:
            for path, line in tailer.scan_new_lines():
                ev = parse_line(line, str(path))
                if ev:
                    print(f"[monitor] Parsed event: kind={ev.kind}", flush=True)
                    
                    # 当检测到 tool_started 或 tool_completed 时，提取 tool 信息并写入 JSONL
                    if ev.kind == "tool_started":
                        self._write_tool_trace(line, ev, "before_tool_call")
                    elif ev.kind == "tool_completed":
                        self._write_tool_trace(line, ev, "after_tool_call")
                    
                    self.sm.apply(ev)
# start_monitor 由 systemd/命令行调用，进程常驻：与后端 app.py 解耦部署

            self.sm.check_idle_end()

            # LOG_RESCAN_SECONDS 周期重扫：新会话文件（含轮转产物）自动纳入监控
            # Periodically rescan for new files
            now = time.time()
            if now - last_rescan >= LOG_RESCAN_SECONDS:
                tailer.paths = discover_log_files(self.openclaw_log_root)
                last_rescan = now

            time.sleep(POLL_INTERVAL)

        # 主循环三步：tail 新行 → parse_line → 状态机 apply；空转时做空闲收尾检查
        print("[monitor] Stopped.", flush=True)


# 进程入口：装载配置、启动后台线程并阻塞主循环（SIGTERM 优雅退出）
# 入口装配：配置→FileTailer→状态机回调→编排器→信号处理，一键启动全部监控链路
def start_monitor(openclaw_log_root: str = "", gateway_log_path: str = "") -> None:
    """Entry point - start the monitor in a background thread."""
    # Load config from DB if not provided
    if not openclaw_log_root or not gateway_log_path:
        config = get_config_from_db()
        if not openclaw_log_root:
            openclaw_log_root = DEFAULT_OPENCLAW_LOG_ROOT
        if not gateway_log_path:
            gateway_log_path = config.get("gateway_log_path", "")

    monitor = MonitorOrchestrator(
        openclaw_log_root=openclaw_log_root,
        gateway_log_path=gateway_log_path,
    )
    monitor.run()


# Allow running as standalone script
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ClawAVC Monitor Watcher")
    parser.add_argument("--openclaw-logs", default=DEFAULT_OPENCLAW_LOG_ROOT, help="OpenClaw log root")
    parser.add_argument("--gateway-logs", default="", help="Gateway log directory")
    args = parser.parse_args()
    start_monitor(openclaw_log_root=args.openclaw_logs, gateway_log_path=args.gateway_logs)
