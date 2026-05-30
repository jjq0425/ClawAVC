#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Abnormal user-state judging entrypoint.

This file provides a stable `judge(action, IR)` function boundary for the
orchestrator. The implementation adapts the current round's action list and
translated IR into the layered resource consistency checker.

This is a self-contained module that integrates the resource_consistency_check
logic directly, removing the external module dependency.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import asdict, dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence

# ---------------------------------------------------------------------------
# Core data types
# ---------------------------------------------------------------------------

Action = str


@dataclass(frozen=True)
class IRObject:
    """One resource object parsed from group-1 IR JSON."""

    type: Literal["file", "tool"]
    identifier: str
    actions: Sequence[Action]
    params: Optional[Dict[str, str]] = None
    selinux_rules: Sequence[str] = ()


@dataclass(frozen=True)
class IRPolicy:
    """One allow/deny policy parsed from group-1 IR JSON."""

    subject: str
    objects: Sequence[IRObject]
    effect: Literal["allow", "deny"] = "allow"


@dataclass(frozen=True)
class BehaviorEvent:
    """Observed user-space behavior event."""

    resource_type: Literal["file", "tool"]
    identifier: str
    action: Action
    params: Optional[Dict[str, str]] = None


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


# ---------------------------------------------------------------------------
# Internal helpers for resource consistency check
# ---------------------------------------------------------------------------


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
        "access": "read",
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
    }
    return aliases.get(raw, raw)


def _match_identifier(actual: str, expected: str) -> bool:
    return actual == expected or fnmatch(actual, expected)


def _params_match(expected: Optional[Dict[str, str]], actual: Optional[Dict[str, str]]) -> bool:
    if not expected:
        return True
    actual = actual or {}
    return all(str(actual.get(k)) == str(v) for k, v in expected.items())


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
    identifier = raw.get("identifier") or raw.get("path") or raw.get("name") or raw.get("resource")

    if not resource_type:
        resource_type = "file" if str(identifier or "").startswith("/") else "tool"
    if not identifier:
        raise ValueError(f"IR object missing identifier: {raw}")

    actions = raw.get("actions", raw.get("action", []))
    normalized_actions = [_normalize_action(a) for a in _as_list(actions)]

    rules = raw.get("selinux_rules", raw.get("selinux_rule", []))
    return IRObject(
        type=resource_type,
        identifier=str(identifier),
        actions=normalized_actions,
        params=_parse_params(raw.get("params")),
        selinux_rules=[str(rule) for rule in _as_list(rules)],
    )


# ---------------------------------------------------------------------------
# IR policy parsing
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Event evaluation
# ---------------------------------------------------------------------------


def _evaluate_event(
    event: BehaviorEvent,
    allow_policies: Sequence[IRPolicy],
) -> tuple[bool, List[str], List[str]]:
    event_action = _normalize_action(event.action)
    matched_rules: List[str] = []

    for policy in allow_policies:
        for obj in policy.objects:
            if obj.type != event.resource_type:
                continue

            if not _match_identifier(event.identifier, obj.identifier):
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
                if event_action not in allowed_actions:
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


# ---------------------------------------------------------------------------
# Consistency check functions
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Gateway message to behavior conversion
# ---------------------------------------------------------------------------


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
    return "/" in token or token in {".", ".."} or token.endswith((".md", ".txt", ".json", ".py", ".csv"))


def _infer_exec_behaviors(args: Dict[str, Any]) -> List[BehaviorEvent]:
    command = str(args.get("command", "")).strip()
    if not command:
        return []

    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    if not tokens:
        return []

    cmd = tokens[0]
    workdir = str(args.get("workdir")) if args.get("workdir") else None
    path_tokens = [token for token in tokens[1:] if _looks_like_path(token)]

    def as_file_event(path_token: str, action: str) -> BehaviorEvent:
        return BehaviorEvent(
            resource_type="file",
            identifier=_resolve_exec_path(path_token, workdir),
            action=action,
            params=_normalize_params_dict(args),
        )

    if cmd in {"ls", "find", "pwd", "tree", "du", "stat"}:
        target = path_tokens[0] if path_tokens else (workdir or ".")
        return [as_file_event(target, "read")]

    if cmd in {"cat", "head", "tail", "grep", "sed", "awk"}:
        file_tokens = [token for token in path_tokens if token not in {".", ".."}]
        return [as_file_event(token, "read") for token in file_tokens] or [as_file_event(workdir or ".", "read")]

    if cmd in {"rm", "unlink", "rmdir"}:
        return [as_file_event(token, "delete") for token in path_tokens]

    if cmd in {"touch", "mkdir", "mktemp"}:
        targets = path_tokens or [workdir or "."]
        return [as_file_event(token, "create") for token in targets]

    if cmd in {"chmod", "chown"}:
        return [as_file_event(token, "setattr") for token in path_tokens]

    if cmd == "cp" and len(path_tokens) >= 2:
        src, dst = path_tokens[0], path_tokens[1]
        return [as_file_event(src, "read"), as_file_event(dst, "write")]

    if cmd == "mv" and len(path_tokens) >= 2:
        src, dst = path_tokens[0], path_tokens[1]
        return [as_file_event(src, "write"), as_file_event(dst, "write")]

    return []


def gateway_messages_to_behaviors(gateway_trace: Any) -> List[BehaviorEvent]:
    """
    Convert gateway-side messages into BehaviorEvent records.
    Current baseline only consumes assistant tool_calls and ignores tool ids.
    """

    messages = _extract_messages(gateway_trace)
    behaviors: List[BehaviorEvent] = []

    file_action_map = {
        "read": "read",
        "read_file": "read",
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
        if msg.get("role") != "assistant":
            continue
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

            if normalized_tool in file_action_map and path:
                behaviors.append(
                    BehaviorEvent(
                        resource_type="file",
                        identifier=str(path),
                        action=file_action_map[normalized_tool],
                        params=_normalize_params_dict(args),
                    )
                )
                continue

            if normalized_tool in {"exec", "bash", "shell"}:
                inferred_behaviors = _infer_exec_behaviors(args)
                if inferred_behaviors:
                    behaviors.extend(inferred_behaviors)
                    continue

            action = "execute" if normalized_tool in {"exec", "bash", "shell"} else "invoke"
            behaviors.append(
                BehaviorEvent(
                    resource_type="tool",
                    identifier=tool_name,
                    action=action,
                    params=_normalize_params_dict(args),
                )
            )

    return behaviors


# ---------------------------------------------------------------------------
# Scored & Layered check functions
# ---------------------------------------------------------------------------


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
    allowed_file_objects = [obj for obj in all_objects if obj.type == "file"]

    tool_events = [event for event in behaviors if event.resource_type == "tool"]
    file_events = [event for event in behaviors if event.resource_type == "file"]

    matched_rules: List[str] = []
    overall_violations: List[str] = []

    tool_call_matched = 0
    tool_call_violations: List[str] = []
    for event in tool_events:
        matched = False
        for obj in allowed_tool_objects:
            if not _match_identifier(event.identifier, obj.identifier):
                continue
            allowed_actions = {_normalize_action(action) for action in obj.actions}
            if allowed_actions and _normalize_action(event.action) not in allowed_actions:
                tool_call_violations.append(
                    f"tool action over-privilege: {event.action} on {event.identifier}, allowed={sorted(allowed_actions)}"
                )
                matched = True
                break
            matched = True
            matched_rules.extend(obj.selinux_rules)
            break
        if matched and (not tool_call_violations or "tool action over-privilege" not in tool_call_violations[-1]):
            tool_call_matched += 1
        elif not matched:
            tool_call_violations.append(f"tool out of IR allow scope: {event.identifier}")

    parameter_matched = 0
    parameter_total = 0
    parameter_violations: List[str] = []
    for event in tool_events:
        matched_obj = next((obj for obj in allowed_tool_objects if _match_identifier(event.identifier, obj.identifier)), None)
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
    for event in file_events:
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
    resource_result = _aspect_result(resource_matched, len(file_events), resource_violations)

    overall_violations.extend(tool_call_result.violations)
    overall_violations.extend(trajectory_result.violations)
    overall_violations.extend(parameter_result.violations)
    overall_violations.extend(resource_result.violations)

    active_scores = [
        result.score
        for result in [tool_call_result, trajectory_result, parameter_result, resource_result]
        if result.total_count > 0
    ]
    overall_score = 1.0 if not active_scores else round(sum(active_scores) / len(active_scores), 4)

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


def layered_result_to_text(result: LayeredCheckResult) -> str:
    """
    Convert LayeredCheckResult into a human-readable text summary.
    """
    lines: List[str] = []

    # Overall verdict
    if result.consistent == "yes":
        lines.append(f"【判定结果】行为一致，整体得分: {result.overall_score}")
    else:
        lines.append(f"【判定结果】行为异常，整体得分: {result.overall_score}")

    # Tool call consistency
    tc = result.tool_call_consistency
    if tc.total_count > 0:
        if tc.consistent == "yes":
            lines.append(f"  - 工具调用一致性: 通过 ({tc.matched_count}/{tc.total_count})")
        else:
            lines.append(f"  - 工具调用一致性: 异常 ({tc.matched_count}/{tc.total_count})")
            for v in tc.violations:
                if "out of IR allow scope" in v:
                    tool_name = v.split(":")[-1].strip()
                    lines.append(f"    * 调用了未授权的工具: {tool_name}")
                elif "action over-privilege" in v:
                    lines.append(f"    * 工具操作越权: {v}")
                else:
                    lines.append(f"    * {v}")

    # Tool trajectory consistency
    tt = result.tool_trajectory_consistency
    if tt.total_count > 0:
        if tt.consistent == "yes":
            lines.append(f"  - 工具调用顺序一致性: 通过 ({tt.matched_count}/{tt.total_count})")
        else:
            lines.append(f"  - 工具调用顺序一致性: 异常 ({tt.matched_count}/{tt.total_count})")
            for v in tt.violations:
                if "trajectory mismatch" in v:
                    lines.append(f"    * 调用顺序与预期不符")
                else:
                    lines.append(f"    * {v}")

    # Parameter consistency
    pc = result.parameter_consistency
    if pc.total_count > 0:
        if pc.consistent == "yes":
            lines.append(f"  - 参数一致性: 通过 ({pc.matched_count}/{pc.total_count})")
        else:
            lines.append(f"  - 参数一致性: 异常 ({pc.matched_count}/{pc.total_count})")
            for v in pc.violations:
                if "param mismatch" in v:
                    lines.append(f"    * 参数不匹配: {v}")
                else:
                    lines.append(f"    * {v}")

    # Resource access consistency
    ra = result.resource_access_consistency
    if ra.total_count > 0:
        if ra.consistent == "yes":
            lines.append(f"  - 资源访问一致性: 通过 ({ra.matched_count}/{ra.total_count})")
        else:
            lines.append(f"  - 资源访问一致性: 异常 ({ra.matched_count}/{ra.total_count})")
            for v in ra.violations:
                if "out of IR allow scope" in v:
                    lines.append(f"    * 访问了未授权的资源: {v}")
                elif "action over-privilege" in v:
                    lines.append(f"    * 资源操作越权: {v}")
                else:
                    lines.append(f"    * {v}")

    # Behavior summary
    if result.behaviors:
        lines.append("  - 行为记录:")
        for b in result.behaviors:
            if b.resource_type == "tool":
                param_str = ""
                if b.params:
                    param_str = ", ".join(f"{k}={v}" for k, v in b.params.items())
                lines.append(f"    * 调用工具 [{b.identifier}]({param_str})")
            else:
                lines.append(f"    * 访问文件 [{b.identifier}] 操作={b.action}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Judge function (orchestrator entrypoint)
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Support both dict-style and attribute-style access."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _normalize_ir(ir: Any) -> Dict[str, Any]:
    """
    Convert the translated IR into the policy shape expected by the consistency module.
    Supports both:
    - New format: level2.policies already in subject/objects format
    - Old format: level2.policies in scene/resource_type/functions format
    """

    level1 = _get(ir, "level1", []) or []
    level2 = _get(ir, "level2", {}) or {}
    raw_policies = _get(level2, "policies", []) or []

    normalized_policies: List[Dict[str, Any]] = []
    for raw_policy in raw_policies:
        effect = _get(raw_policy, "effect", "allow")

        # --- New format: already has subject/objects ---
        if "subject" in (raw_policy if isinstance(raw_policy, dict) else {}) and "objects" in (raw_policy if isinstance(raw_policy, dict) else {}):
            normalized_policies.append({
                "subject": raw_policy["subject"],
                "effect": effect,
                "objects": raw_policy["objects"],
            })
            continue

        # --- Old format: scene/resource_type/functions -> convert ---
        resource_type = _get(raw_policy, "resource_type", "file")
        scene = _get(raw_policy, "scene", level1[0] if level1 else "default_task")
        functions = _get(raw_policy, "functions", []) or []

        objects: List[Dict[str, Any]] = []
        for fn in functions:
            fn_name = _get(fn, "name", "")
            fn_type = _get(fn, "type", "function")
            params = _get(fn, "params", {}) or {}

            # Tool-level intent object.
            objects.append(
                {
                    "type": "tool",
                    "identifier": fn_name,
                    "actions": ["invoke"],
                    "params": params or None,
                }
            )

            # File-level intent object, if path-like resource exists.
            if resource_type == "file" and isinstance(params, dict) and params.get("path"):
                objects.append(
                    {
                        "type": "file",
                        "identifier": params["path"],
                        "actions": _get(fn, "file_actions", ["read"]),
                        "params": None,
                    }
                )
            elif resource_type != "file":
                objects.append(
                    {
                        "type": resource_type,
                        "identifier": fn_name if fn_type == "function" else str(params),
                        "actions": _get(fn, "actions", ["invoke"]),
                        "params": params or None,
                    }
                )

        normalized_policies.append(
            {
                "subject": scene,
                "effect": effect,
                "objects": objects,
            }
        )

    return {"policies": normalized_policies}


def _normalize_actions(action: Any) -> List[BehaviorEvent]:
    """
    Convert orchestrator action records into BehaviorEvent.

    Expected action item shape:
    {
      "tool": "read",
      "arguments": {"path": "..."},
      "resources": [{"path": "...", "access": "read"}],
      "result": "..."
    }
    """

    action_list = action if isinstance(action, list) else [action]
    behaviors: List[BehaviorEvent] = []

    for item in action_list:
        if not isinstance(item, dict):
            continue

        tool = str(item.get("tool", "")).strip()
        arguments = item.get("arguments") or {}
        resources = item.get("resources") or []

        if tool:
            behaviors.append(
                BehaviorEvent(
                    resource_type="tool",
                    identifier=tool,
                    action="invoke",
                    params={str(k): str(v) for k, v in arguments.items()} if isinstance(arguments, dict) else None,
                )
            )

        for resource in resources:
            if not isinstance(resource, dict):
                continue
            path = resource.get("path") or resource.get("identifier")
            access = resource.get("access") or resource.get("action") or "read"
            if not path:
                continue
            behaviors.append(
                BehaviorEvent(
                    resource_type="file",
                    identifier=str(path),
                    action=str(access),
                    params=None,
                )
            )

    return behaviors


def judge(action: Any, IR: Any) -> str:
    """Return textual abnormal-state judgement for one completed round."""
    normalized_ir = _normalize_ir(IR)
    behaviors = _normalize_actions(action)
    result = Resource_Consistency_Check_Layered(normalized_ir, behaviors)
    return layered_result_to_text(result)


# ---------------------------------------------------------------------------
# Demo / self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sample_action = [
        {
            "tool": "read",
            "arguments": {"path": "/temp/helloworld.txt"},
            "resources": [{"path": "/temp/helloworld.txt", "access": "read"}],
            "result": '{\n  "status": "error",\n  "tool": "read",\n  "error": "Path escapes sandbox root (~/.openclaw/workspace): /temp/helloworld.txt"\n}',
        }
    ]

    sample_ir = {
        "level1": ["file_ops"],
        "level2": {
            "policies": [
                {
                    "effect": "allow",
                    "functions": [
                        {
                            "file_actions": ["read"],
                            "name": "read",
                            "params": {"path": "/temp/helloworld.txt"},
                            "type": "function",
                        }
                    ],
                    "resource_type": "file",
                    "scene": "file_ops",
                }
            ],
            "query": "read一下/temp/helloworld.txt，看看有什么，记得调用read工具",
            "round_id": "129b8a51",
            "validation": {"errors": [], "ok": True, "warnings": []},
        },
    }

    print(judge(sample_action, sample_ir))
