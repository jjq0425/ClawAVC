from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence
from urllib.parse import urlparse

from shell_command_semantics import analyze_shell_command

Action = str
ResourceType = Literal["file", "tool", "network"]
ResourceKind = Literal["file", "directory", "network", "process", "unknown"]

DEFAULT_ASPECT_WEIGHTS: Dict[str, float] = {
    "tool_call": 1.0,
    "tool_trajectory": 0.0,
    "parameter": 1.0,
    "resource_access": 1.0,
}


@dataclass(frozen=True)
class IRObject:
    """One resource object parsed from group-1 IR JSON."""

    type: ResourceType
    identifier: str
    actions: Sequence[Action]
    params: Optional[Dict[str, str]] = None
    selinux_rules: Sequence[str] = ()
    identifier_match: Literal["auto", "exact", "glob", "regex"] = "auto"


@dataclass(frozen=True)
class IRPolicy:
    """One allow/deny policy parsed from group-1 IR JSON."""

    subject: str
    objects: Sequence[IRObject]
    effect: Literal["allow", "deny"] = "allow"


@dataclass(frozen=True)
class BehaviorEvent:
    """Observed user-space behavior event."""

    resource_type: ResourceType
    identifier: str
    action: Action
    params: Optional[Dict[str, str]] = None
    resource_kind: ResourceKind = "file"
    inference_status: Literal["resolved", "partial", "unresolved"] = "resolved"
    inference_reason: Optional[str] = None
    source: str = "manual"
    source_tool: Optional[str] = None
    tool_call_id: Optional[str] = None
    round_id: Optional[str] = None
    round_id_source: Optional[str] = None
    timestamp: Optional[str] = None
    timestamp_source: Optional[str] = None
    pid: Optional[int] = None
    parent_pid: Optional[int] = None
    container_id: Optional[str] = None
    sandbox_id: Optional[str] = None
    outcome: Literal["success", "error", "pending", "unknown"] = "unknown"
    outcome_detail: Optional[str] = None


@dataclass(frozen=True)
class CheckResult:
    consistent: Literal["yes", "no"]
    violations: List[str]
    matched_rules: List[str]


@dataclass(frozen=True)
class ScoredCheckResult:
    consistent: Literal["yes", "no"]
    score: float
    matched_count: int
    total_count: int
    violations: List[str]
    matched_rules: List[str]
    behaviors: List[BehaviorEvent]


@dataclass(frozen=True)
class AspectResult:
    consistent: Literal["yes", "no"]
    score: float
    matched_count: int
    total_count: int
    violations: List[str]


@dataclass(frozen=True)
class LayeredCheckResult:
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
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _normalize_action(action: Any) -> Action:
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
        "request": "connect",
        "http_get": "connect",
        "http_post": "connect",
        "download": "connect",
        "upload": "connect",
    }
    return aliases.get(raw, raw)


def _infer_resource_type(identifier: Any, fallback: Any = None) -> ResourceType:
    raw_type = str(fallback or "").strip().lower()
    if raw_type in {"file", "tool", "network"}:
        return raw_type  # type: ignore[return-value]

    ident = str(identifier or "").strip()
    parsed = urlparse(ident)
    if parsed.scheme in {"http", "https", "ftp", "ssh", "git"} or parsed.netloc:
        return "network"
    if ident.startswith("/") or ident.startswith("."):
        return "file"
    return "tool"


def _parse_open_flags(raw_flags: Any) -> Optional[int]:
    if raw_flags is None:
        return None
    if isinstance(raw_flags, int):
        return raw_flags

    text = str(raw_flags).strip()
    if not text:
        return None
    try:
        return int(text, 0)
    except ValueError:
        pass

    flag_value = 0
    matched = False
    for name in re.split(r"[\s|,+]+", text.upper()):
        if not name:
            continue
        value = getattr(os, name, None)
        if isinstance(value, int):
            flag_value |= value
            matched = True
    return flag_value if matched else None


def _normalize_behavior_action(
    action: Any,
    params: Optional[Dict[str, Any]] = None,
) -> Action:
    raw = str(action or "").strip().lower()
    if raw not in {"open", "openat"}:
        return _normalize_action(raw)

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
    if match_mode == "regex":
        return True
    lowered = pattern.lower()
    return lowered.startswith(("regex:", "re:"))


def _strip_regex_prefix(pattern: str) -> str:
    lowered = pattern.lower()
    if lowered.startswith("regex:"):
        return pattern[len("regex:") :]
    if lowered.startswith("re:"):
        return pattern[len("re:") :]
    return pattern


def _match_identifier(actual: str, expected: str, match_mode: str = "auto") -> bool:
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
    resource_type = raw.get("type") or raw.get("resource_type") or raw.get("kind")
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

    if not identifier:
        raise ValueError(f"IR object missing identifier: {raw}")
    resource_type = _infer_resource_type(identifier, resource_type)

    actions = raw.get("actions", raw.get("action", []))
    normalized_actions = [_normalize_action(a) for a in _as_list(actions)]

    rules = raw.get("selinux_rules", raw.get("selinux_rule", []))
    return IRObject(
        type=resource_type,
        identifier=str(identifier),
        actions=normalized_actions,
        params=_parse_params(raw.get("params")),
        selinux_rules=[str(rule) for rule in _as_list(rules)],
        identifier_match=str(raw.get("identifier_match", raw.get("match", "auto"))).lower(),  # type: ignore[arg-type]
    )


def parse_ir_policies(raw_ir: Any) -> List[IRPolicy]:
    """
    Accepts the likely group-1 shapes:
      1. {"policies": [{"subject": ..., "objects": [...], "effect": "allow"}]}
      2. [{"subject": ..., "objects": [...], "effect": "allow"}]
      3. {"subject": ..., "resource": ..., "action": ...}
    """

    if isinstance(raw_ir, dict) and "policies" in raw_ir:
        raw_policies = raw_ir["policies"]
    elif isinstance(raw_ir, list):
        raw_policies = raw_ir
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
        raise ValueError("IR JSON must be an object or a list")

    policies: List[IRPolicy] = []
    for raw_policy in raw_policies:
        objects = raw_policy.get("objects", raw_policy.get("object", raw_policy.get("resources", [])))
        parsed_objects: List[IRObject] = []
        for obj in _as_list(objects):
            if "actions" not in obj and "action" not in obj and "action" in raw_policy:
                obj = {**obj, "action": raw_policy["action"]}
            if "selinux_rules" not in obj and "selinux_rule" not in obj and "selinux_rules" in raw_policy:
                obj = {**obj, "selinux_rules": raw_policy["selinux_rules"]}
            parsed_objects.append(_parse_object(obj))

        policies.append(
            IRPolicy(
                subject=str(raw_policy.get("subject", "default_task")),
                objects=parsed_objects,
                effect=raw_policy.get("effect", "allow"),
            )
        )
    return policies


def load_ir_policies(json_path: str | Path) -> List[IRPolicy]:
    path = Path(json_path)
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(f"{path} is empty or missing")
    return parse_ir_policies(json.loads(path.read_text(encoding="utf-8")))


def _evaluate_event(
    event: BehaviorEvent,
    allow_policies: Sequence[IRPolicy],
) -> tuple[bool, List[str], List[str]]:
    event_action = _normalize_behavior_action(event.action, event.params)
    if event.inference_status == "unresolved" or event_action == "unknown":
        return (
            False,
            [
                f"resource semantics unresolved: {event.identifier}, "
                f"reason={event.inference_reason or 'insufficient action context'}"
            ],
            [],
        )
    matched_rules: List[str] = []

    for policy in allow_policies:
        for obj in policy.objects:
            if obj.type != event.resource_type:
                continue

            if not _match_identifier(event.identifier, obj.identifier, obj.identifier_match):
                continue

            if event.resource_type == "tool" and not _params_match(obj.params, event.params):
                return (
                    False,
                    [
                        f"tool param mismatch: {event.identifier}, "
                        f"expected={obj.params}, actual={event.params}"
                    ],
                    [],
                )

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

            matched_rules.extend(obj.selinux_rules)
            return True, [], matched_rules

    return False, [f"resource out of IR allow scope: {event.resource_type}:{event.identifier}"], []


def _aspect_result(
    matched_count: int,
    total_count: int,
    violations: List[str],
) -> AspectResult:
    score = 1.0 if total_count == 0 else round(matched_count / total_count, 4)
    return AspectResult(
        consistent="no" if violations else "yes",
        score=score,
        matched_count=matched_count,
        total_count=total_count,
        violations=violations,
    )


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

    violations: List[str] = []
    matched_rules: List[str] = []
    allow_policies = [policy for policy in ir_policies if policy.effect == "allow"]

    for event in behaviors:
        matched, event_violations, event_rules = _evaluate_event(event, allow_policies)
        if not matched:
            violations.extend(event_violations)
        matched_rules.extend(event_rules)

    return CheckResult(
        consistent="no" if violations else "yes",
        violations=violations,
        matched_rules=sorted(set(matched_rules)),
    )


def _normalize_params_dict(raw: Any) -> Optional[Dict[str, str]]:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    return {"_raw": str(raw)}


def _gateway_content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: List[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                out.append(str(item.get("text", "")))
        return "\n".join(out)
    return str(content)


def _extract_messages(gateway_trace: Any) -> List[Dict[str, Any]]:
    if isinstance(gateway_trace, list):
        return [msg for msg in gateway_trace if isinstance(msg, dict)]
    if isinstance(gateway_trace, dict):
        if isinstance(gateway_trace.get("messages"), list):
            return [msg for msg in gateway_trace["messages"] if isinstance(msg, dict)]
        body = gateway_trace.get("body")
        if isinstance(body, dict) and isinstance(body.get("messages"), list):
            return [msg for msg in body["messages"] if isinstance(msg, dict)]
    raise ValueError("gateway_trace must be a messages list or an object containing body.messages")


def _extract_trace_metadata(gateway_trace: Any) -> Dict[str, Any]:
    if not isinstance(gateway_trace, dict):
        return {}

    body = gateway_trace.get("body")
    body = body if isinstance(body, dict) else {}
    round_id = gateway_trace.get("round_id") or body.get("round_id")
    timestamp = gateway_trace.get("timestamp") or body.get("timestamp")
    return {
        "round_id": round_id,
        "round_id_source": "trace_field" if round_id is not None else None,
        "timestamp": timestamp,
        "timestamp_source": "trace_field" if timestamp is not None else None,
        "pid": gateway_trace.get("pid") or body.get("pid"),
        "parent_pid": gateway_trace.get("parent_pid") or body.get("parent_pid"),
        "container_id": gateway_trace.get("container_id") or body.get("container_id"),
        "sandbox_id": gateway_trace.get("sandbox_id") or body.get("sandbox_id"),
    }


def _timestamp_from_user_content(content: Any) -> Optional[str]:
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

    offset_hours = int(match.group("offset"))
    tz = timezone(timedelta(hours=offset_hours))
    second = match.group("second") or "00"
    parsed = datetime.strptime(
        f"{match.group('date')} {match.group('time')}:{second}",
        "%Y-%m-%d %H:%M:%S",
    ).replace(tzinfo=tz)
    return parsed.isoformat()


def _user_round_metadata(
    message: Dict[str, Any],
    trace_metadata: Dict[str, Any],
    round_index: int,
) -> Dict[str, Any]:
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
    metadata = dict(current_metadata)
    if message.get("round_id") is not None:
        metadata["round_id"] = str(message["round_id"])
        metadata["round_id_source"] = "message_field"
    if message.get("timestamp") is not None:
        metadata["timestamp"] = str(message["timestamp"])
        metadata["timestamp_source"] = "message_field"
    return metadata


def _tool_result_metadata(messages: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Optional[str]]]:
    results: Dict[str, Dict[str, Optional[str]]] = {}

    for message in messages:
        if message.get("role") != "tool" or not message.get("tool_call_id"):
            continue

        tool_call_id = str(message["tool_call_id"])
        content = _gateway_content_to_text(message.get("content")).strip()
        outcome: Literal["success", "error", "pending", "unknown"] = "unknown"
        detail: Optional[str] = None

        if content:
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                payload = None

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
    if not raw_path:
        return str(Path(workdir or "."))
    path = Path(raw_path)
    if path.is_absolute():
        return str(path)
    if workdir:
        return str(Path(workdir) / path)
    return str(path)


def _looks_like_path(token: str) -> bool:
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
    if "\n" in command:
        return "multi-line shell command"
    if any(token in {"|", "||", "&&", ";", "&"} for token in tokens):
        return "shell pipeline or command chaining"
    if any(token in {">", ">>", "<", "<<", "2>", "2>>"} for token in tokens):
        return "shell redirection"
    if re.search(r"`[^`]+`|\$\([^)]*\)|\$\{[^}]+\}|\$[A-Za-z_][A-Za-z0-9_]*", command):
        return "shell variable or command expansion"
    if tokens and tokens[0] in {"sh", "bash", "zsh", "python", "python3", "node"} and "-c" in tokens:
        return "nested script execution"
    return None


def _infer_exec_behaviors(
    args: Dict[str, Any],
    *,
    source_tool: str,
    tool_call_id: Optional[str],
    trace_metadata: Dict[str, Any],
    outcome_metadata: Dict[str, Optional[str]],
) -> List[BehaviorEvent]:
    command = str(args.get("command", "")).strip()
    if not command:
        return []

    workdir = str(args.get("workdir")) if args.get("workdir") else None
    analysis = analyze_shell_command(command, workdir=workdir)
    events: List[BehaviorEvent] = []
    for behavior in analysis.behaviors:
        if behavior.resource_kind == "network":
            resource_type: ResourceType = "network"
            resource_kind: ResourceKind = "network"
        elif behavior.resource_kind == "process":
            resource_type = "tool"
            resource_kind = "process"
        else:
            resource_type = "file"
            resource_kind = behavior.resource_kind

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
                **trace_metadata,
            )
        )
    return events


def gateway_messages_to_behaviors(gateway_trace: Any) -> List[BehaviorEvent]:
    """
    Convert gateway-side messages into BehaviorEvent records.
    Each assistant tool call produces a tool-level event. File and shell tools
    may additionally produce resource-level events inferred from arguments.
    """

    messages = _extract_messages(gateway_trace)
    trace_metadata = _extract_trace_metadata(gateway_trace)
    tool_results = _tool_result_metadata(messages)
    behaviors: List[BehaviorEvent] = []
    current_metadata = dict(trace_metadata)
    round_index = 0

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
        for tool_call in msg.get("tool_calls", []) or []:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function") or {}
            tool_name = str(function.get("name", "")).strip()
            if not tool_name:
                continue

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

            normalized_tool = tool_name.lower()
            path = args.get("path") or args.get("file") or args.get("target")
            network_identifier = (
                args.get("url")
                or args.get("uri")
                or args.get("endpoint")
                or args.get("domain")
                or args.get("host")
                or args.get("query")
            )
            tool_call_id = str(tool_call.get("id")) if tool_call.get("id") else None
            outcome_metadata = tool_results.get(
                tool_call_id or "",
                {"outcome": "unknown", "outcome_detail": None},
            )

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

            if normalized_tool in file_action_map and path:
                resource_kind: Literal["file", "directory", "unknown"] = "file"
                if (
                    outcome_metadata.get("outcome") == "error"
                    and "EISDIR" in str(outcome_metadata.get("outcome_detail") or "")
                ):
                    resource_kind = "directory"

                action = _normalize_behavior_action(
                    file_action_map[normalized_tool],
                    args,
                )
                inference_status: Literal["resolved", "partial", "unresolved"] = (
                    "unresolved" if action == "unknown" else "resolved"
                )
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

            if normalized_tool in {"web_search", "web_fetch", "browser", "playwright", "curl", "wget"}:
                behaviors.append(
                    BehaviorEvent(
                        resource_type="network",
                        identifier=str(network_identifier or tool_name),
                        action="connect",
                        params=_normalize_params_dict(args),
                        resource_kind="network",
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

            if normalized_tool in {"exec", "bash", "shell"}:
                inferred_behaviors = _infer_exec_behaviors(
                    args,
                    source_tool=tool_name,
                    tool_call_id=tool_call_id,
                    trace_metadata=event_metadata,
                    outcome_metadata=outcome_metadata,
                )
                if inferred_behaviors:
                    behaviors.extend(inferred_behaviors)

    return behaviors


def Resource_Consistency_Check_Scored(
    ir_input: Sequence[IRPolicy] | str | Path | Dict[str, Any] | List[Any],
    behavior_input: Sequence[BehaviorEvent] | Dict[str, Any] | List[Any],
) -> ScoredCheckResult:
    """
    Baseline entrypoint for task-1:
    - input 1: IR JSON / parsed IR policies
    - input 2: BehaviorEvent list or gateway messages/body.messages
    - output : yes/no + score + violations
    """

    if isinstance(ir_input, (str, Path)):
        ir_policies = load_ir_policies(ir_input)
    elif ir_input and isinstance(ir_input, Sequence) and isinstance(ir_input[0], IRPolicy):  # type: ignore[index]
        ir_policies = list(ir_input)  # type: ignore[arg-type]
    else:
        ir_policies = parse_ir_policies(ir_input)

    if isinstance(behavior_input, dict):
        behaviors = gateway_messages_to_behaviors(behavior_input)
    elif behavior_input and isinstance(behavior_input, Sequence) and isinstance(behavior_input[0], BehaviorEvent):  # type: ignore[index]
        behaviors = list(behavior_input)  # type: ignore[arg-type]
    else:
        behaviors = gateway_messages_to_behaviors(behavior_input)

    allow_policies = [policy for policy in ir_policies if policy.effect == "allow"]
    violations: List[str] = []
    matched_rules: List[str] = []
    matched_count = 0

    for event in behaviors:
        matched, event_violations, event_rules = _evaluate_event(event, allow_policies)
        if matched:
            matched_count += 1
        else:
            violations.extend(event_violations)
        matched_rules.extend(event_rules)

    total_count = len(behaviors)
    score = 1.0 if total_count == 0 else round(matched_count / total_count, 4)
    return ScoredCheckResult(
        consistent="no" if violations else "yes",
        score=score,
        matched_count=matched_count,
        total_count=total_count,
        violations=violations,
        matched_rules=sorted(set(matched_rules)),
        behaviors=behaviors,
    )


def Resource_Consistency_Check_Layered(
    ir_input: Sequence[IRPolicy] | str | Path | Dict[str, Any] | List[Any],
    behavior_input: Sequence[BehaviorEvent] | Dict[str, Any] | List[Any],
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

    if isinstance(ir_input, (str, Path)):
        ir_policies = load_ir_policies(ir_input)
    elif ir_input and isinstance(ir_input, Sequence) and isinstance(ir_input[0], IRPolicy):  # type: ignore[index]
        ir_policies = list(ir_input)  # type: ignore[arg-type]
    else:
        ir_policies = parse_ir_policies(ir_input)

    if isinstance(behavior_input, dict):
        behaviors = gateway_messages_to_behaviors(behavior_input)
    elif behavior_input and isinstance(behavior_input, Sequence) and isinstance(behavior_input[0], BehaviorEvent):  # type: ignore[index]
        behaviors = list(behavior_input)  # type: ignore[arg-type]
    else:
        behaviors = gateway_messages_to_behaviors(behavior_input)

    allow_policies = [policy for policy in ir_policies if policy.effect == "allow"]
    all_objects = [obj for policy in allow_policies for obj in policy.objects]
    allowed_tool_objects = [obj for obj in all_objects if obj.type == "tool"]

    tool_events = [event for event in behaviors if event.resource_type == "tool"]
    resource_events = [event for event in behaviors if event.resource_type != "tool"]

    matched_rules: List[str] = []
    overall_violations: List[str] = []

    tool_call_matched = 0
    tool_call_violations: List[str] = []
    for event in tool_events:
        matched = False
        event_violation = False
        for obj in allowed_tool_objects:
            if not _match_identifier(event.identifier, obj.identifier, obj.identifier_match):
                continue
            allowed_actions = {_normalize_action(action) for action in obj.actions}
            if not _action_allowed(
                event.resource_type,
                _normalize_behavior_action(event.action, event.params),
                allowed_actions,
            ):
                tool_call_violations.append(
                        f"tool action over-privilege: {event.action} on {event.identifier}, allowed={sorted(allowed_actions)}"
                )
                matched = True
                event_violation = True
                break
            matched = True
            matched_rules.extend(obj.selinux_rules)
            break
        if matched and not event_violation:
            tool_call_matched += 1
        elif not matched:
            tool_call_violations.append(f"tool out of IR allow scope: {event.identifier}")

    parameter_matched = 0
    parameter_total = 0
    parameter_violations: List[str] = []
    for event in tool_events:
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
        parameter_total += 1
        if _params_match(matched_obj.params, event.params):
            parameter_matched += 1
        else:
            parameter_violations.append(
                f"tool param mismatch: {event.identifier}, expected={matched_obj.params}, actual={event.params}"
            )

    resource_matched = 0
    resource_violations: List[str] = []
    for event in resource_events:
        matched, event_violations, event_rules = _evaluate_event(event, allow_policies)
        if matched:
            resource_matched += 1
            matched_rules.extend(event_rules)
        else:
            resource_violations.extend(event_violations)

    expected_tool_order = [obj.identifier for obj in allowed_tool_objects]
    observed_tool_order = [event.identifier for event in tool_events]
    order_idx = 0
    trajectory_matched = 0
    for observed in observed_tool_order:
        while order_idx < len(expected_tool_order) and expected_tool_order[order_idx] != observed:
            order_idx += 1
        if order_idx < len(expected_tool_order):
            trajectory_matched += 1
            order_idx += 1
    trajectory_violations: List[str] = []
    if observed_tool_order and trajectory_matched != len(observed_tool_order):
        trajectory_violations.append(
            f"tool trajectory mismatch: expected_order={expected_tool_order}, observed_order={observed_tool_order}"
        )

    tool_call_result = _aspect_result(tool_call_matched, len(tool_events), tool_call_violations)
    trajectory_result = _aspect_result(trajectory_matched, len(observed_tool_order), trajectory_violations)
    parameter_result = _aspect_result(parameter_matched, parameter_total, parameter_violations)
    resource_result = _aspect_result(resource_matched, len(resource_events), resource_violations)

    weights = {**DEFAULT_ASPECT_WEIGHTS, **(aspect_weights or {})}
    active_violation_parts = [
        ("tool_call", tool_call_result),
        ("tool_trajectory", trajectory_result),
        ("parameter", parameter_result),
        ("resource_access", resource_result),
    ]
    for name, result in active_violation_parts:
        if result.violations and weights.get(name, 0.0) > 0:
            overall_violations.extend(result.violations)

    weighted_parts = [
        ("tool_call", tool_call_result),
        ("tool_trajectory", trajectory_result),
        ("parameter", parameter_result),
        ("resource_access", resource_result),
    ]
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
    overall_score = 1.0 if weight_sum == 0 else round(sum(weighted_scores) / weight_sum, 4)

    return LayeredCheckResult(
        consistent="no" if overall_violations else "yes",
        overall_score=overall_score,
        tool_call_consistency=tool_call_result,
        tool_trajectory_consistency=trajectory_result,
        parameter_consistency=parameter_result,
        resource_access_consistency=resource_result,
        violations=overall_violations,
        matched_rules=sorted(set(matched_rules)),
        behaviors=behaviors,
    )


def layered_result_to_dict(result: LayeredCheckResult) -> Dict[str, Any]:
    return asdict(result)


def demo_behaviors() -> Dict[str, List[BehaviorEvent]]:
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
