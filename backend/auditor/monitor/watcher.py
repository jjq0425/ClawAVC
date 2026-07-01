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
  - Reports result to /api/rounds (WebSocket push to frontend)

Usage (standalone):
  python3 -m auditor.monitor.watcher

Or import and call start_monitor() from the backend.
"""

from __future__ import annotations

import dataclasses
import glob
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


# ═══════════════════════════════════════════════════════════════════════════════
# OpenClaw Log Parser (from openclaw_agent_round_watcher_v2)
# ═══════════════════════════════════════════════════════════════════════════════

BLOCKED_PAYLOAD_KEYS = {
    "content", "messages", "prompt", "input", "output",
    "body", "text", "markdown", "transcript", "conversation", "chat", "delta",
}

SESSION_KEYS = [
    "sessionKey", "session_key", "sourceSessionKey",
    "source_session_key", "sessionId", "session_id",
    "conversationId", "conversation_id",
]

ROUND_KEYS = [
    "round_id", "roundId", "turn_id", "turnId",
    "run_id", "runId", "inbound_message_id", "inboundMessageId",
    "message_id", "messageId",
]

ID_KEYS = [
    "id", "parentId", "parent_id", "sessionKey", "session_key",
    "sourceSessionKey", "sessionId", "session_id",
    "turnId", "turn_id", "roundId", "round_id",
    "runId", "run_id", "requestId", "request_id",
    "messageId", "message_id", "toolCallId", "tool_call_id",
    "toolName", "tool_name", "processId", "process_id",
    "subagentId", "subagent_id", "target",
    "sourceChannel", "sourceTool", "agentId", "agent_id",
    "responseId", "response_id",
]

TOOL_ID_KEYS = ["tool_call_id", "toolCallId", "call_id", "callId", "id"]
PROCESS_ID_KEYS = ["process_id", "processId", "sessionProcessId", "pid", "id"]
SUBAGENT_ID_KEYS = ["subagent_id", "subagentId", "sessionKey", "session_key", "target", "id"]

EVENT_ALIASES = {
    "user_inbound": {
        "inbound.message.received", "user.message.received",
        "message.received", "requester.message.received",
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
    "llm_started": {
        "llm.request.started", "llm.started", "model.request.started",
    },
    "llm_completed": {
        "llm.stream.completed", "llm.completed", "model.response.completed",
    },
    "tool_started": {"tool.call.started", "tool.started", "function.call.started"},
    "tool_completed": {"tool.call.completed", "tool.completed", "tool.result"},
    "process_started": {"process.started", "exec.started"},
    "process_completed": {"process.exited", "process.completed", "exec.completed"},
    "subagent_started": {"subagent.started", "sessions_spawn.started"},
    "subagent_completed": {"subagent.completed", "subagent.failed", "sessions_spawn.completed"},
    "response_routed": {"response.routed", "message.routed", "reply.sent", "message.sent"},
}

TEXT_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("user_inbound", re.compile(r"\b(inbound|user|requester|chat)\b.*\bmessage\b.*\b(received|incoming)\b", re.I)),
    ("turn_started", re.compile(r"\b(agent[._-]?)?turn[._ -]?start(ed)?\b|\brun[._ -]?start(ed)?\b", re.I)),
    ("turn_completed", re.compile(r"\b(agent[._-]?)?turn[._ -]?complete(d)?\b|\brun[._ -]?complete(d)?\b", re.I)),
    ("turn_failed", re.compile(r"\b(agent[._-]?)?turn[._ -]?fail(ed)?\b|\bfatal\b", re.I)),
    ("llm_started", re.compile(r"\bllm\b.*\b(request|start|started)\b", re.I)),
    ("llm_completed", re.compile(r"\bllm\b.*\b(complete|completed|done)\b|\bfinish_reason\b", re.I)),
    ("tool_started", re.compile(r"\btool\b.*\b(start|started|call)\b", re.I)),
    ("tool_completed", re.compile(r"\btool\b.*\b(complete|completed|result|done)\b", re.I)),
    ("response_routed", re.compile(r"\b(response|reply|message)\b.*\b(route|routed|sent|delivered)\b", re.I)),
]


@dataclasses.dataclass
class ParsedEvent:
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
        return self.status() in {"COMPLETED", "FAILED"}


# ═══════════════════════════════════════════════════════════════════════════════
# OpenClaw Event Parsing
# ═══════════════════════════════════════════════════════════════════════════════

def sanitize_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: sanitize_json(v) for k, v in obj.items() if k not in BLOCKED_PAYLOAD_KEYS}
    if isinstance(obj, list):
        return [sanitize_json(x) for x in obj]
    return obj


def flatten_dict(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
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


def get_scalar(d: Dict[str, Any], key: str) -> str:
    v = d.get(key)
    if v is None or isinstance(v, (dict, list)):
        return ""
    return str(v)


def collect_ids(clean: Dict[str, Any], flat: Dict[str, Any]) -> Dict[str, str]:
    ids: Dict[str, str] = {}
    for k in ID_KEYS:
        v = get_scalar(clean, k)
        if v:
            ids[k] = v
    for fk, v in flat.items():
        if isinstance(v, (dict, list)) or v is None:
            continue
        leaf = fk.split(".")[-1]
        if leaf in ID_KEYS:
            sv = str(v)
            if len(sv) <= 500:
                ids.setdefault(leaf, sv)
    # Alias paths
    alias_paths = {
        "details.sessionKey": "sessionKey",
        "details.runId": "run_id",
        "message.details.sessionKey": "sessionKey",
        "message.details.runId": "run_id",
        "message.provenance.sourceSessionKey": "sourceSessionKey",
        "message.toolCallId": "toolCallId",
        "message.toolName": "toolName",
    }
    for path, alias in alias_paths.items():
        if path in flat and flat[path] is not None:
            sv = str(flat[path])
            if len(sv) <= 500:
                ids.setdefault(alias, sv)
    return ids


def first_id(ids: Dict[str, str], keys: Iterable[str]) -> str:
    for k in keys:
        if ids.get(k):
            return ids[k]
    return ""


def classify_event(clean: Dict[str, Any], flat: Dict[str, Any]) -> Tuple[str, str]:
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
        if stop_reason in {"stop", "end_turn", "complete", "completed"}:
            return "turn_completed", f"assistant stopReason={stop_reason}"
        return "response_routed", f"assistant stopReason={stop_reason}"
    if top_type == "message" and msg_role == "toolResult":
        return "tool_completed", f"toolResult.{tool_name or 'unknown'}"

    event_name = get_scalar(clean, "event") or get_scalar(clean, "type") or get_scalar(clean, "name")
    event_lower = event_name.lower()
    for kind, aliases in EVENT_ALIASES.items():
        if event_lower in {a.lower() for a in aliases}:
            return kind, event_name

    # Fallback: text pattern matching
    haystack = " ".join(f"{k}={v}" for k, v in flat.items() if not isinstance(v, (dict, list)) and v is not None and len(str(v)) <= 120)
    for kind, pat in TEXT_PATTERNS:
        if pat.search(haystack):
            return kind, event_name

    return "unknown", event_name


def extract_ids_from_path(source_file: str) -> Dict[str, str]:
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
    try:
        obj = json.loads(line)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None

    clean = sanitize_json(obj)
    if not isinstance(clean, dict):
        return None
    flat = flatten_dict(clean)
    ids = collect_ids(clean, flat)
    ids.update({k: v for k, v in extract_ids_from_path(source_file).items() if not ids.get(k)})
    kind, event_name = classify_event(clean, flat)
    if kind == "unknown":
        return None

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
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Round State Machine
# ═══════════════════════════════════════════════════════════════════════════════

class RoundStateMachine:
    def __init__(self, on_round_start=None, on_round_end=None):
        self.rounds: Dict[str, RoundLedger] = {}
        self.active_by_session: Dict[str, str] = {}
        self.message_to_round: Dict[str, str] = {}
        self.on_round_start = on_round_start
        self.on_round_end = on_round_end

    def apply(self, ev: ParsedEvent) -> None:
        if ev.kind in {"user_inbound", "turn_started"}:
            r = self._start_round(ev)
            self._apply_event(r, ev)
            self._maybe_end(r)
            return

        r = self._find_round(ev)
        if r is None:
            return
        self._apply_event(r, ev)
        self._maybe_end(r)

    def check_idle_end(self, idle_seconds: float = IDLE_END_SECONDS) -> None:
        now = time.time()
        for r in list(self.rounds.values()):
            if r.end_printed:
                continue
            if r.status() == "ROUTING_RESPONSE" and now - r.last_event_at >= idle_seconds:
                r.response_routed = True
                self._maybe_end(r)

    def _start_round(self, ev: ParsedEvent) -> RoundLedger:
        session_key = ev.session_key or "unknown"
        round_id = ev.round_id or f"round:{session_key}:{int(ev.ts * 1000)}"

        # Close old round in same session
        old_id = self.active_by_session.get(session_key)
        if old_id and old_id != round_id:
            old = self.rounds.get(old_id)
            if old and not old.end_printed and session_key != "unknown":
                old.failed = True
                self._maybe_end(old)

        r = self.rounds.get(round_id)
        if r is None:
            r = RoundLedger(round_id=round_id, session_key=session_key)
            r.source_file = ev.source_file or ""
            self.rounds[round_id] = r
        elif not r.source_file and ev.source_file:
            # Backfill if a later event from the same file is the first we saw with a path.
            r.source_file = ev.source_file

        if session_key != "unknown":
            self.active_by_session[session_key] = round_id

        if ev.kind == "user_inbound":
            r.user_inbound_seen = True
        if ev.kind == "turn_started":
            r.turn_started_seen = True

        self._merge_ids(r, ev)
        if not r.start_printed:
            r.start_printed = True
            if self.on_round_start:
                self.on_round_start(r)
        return r

    def _find_round(self, ev: ParsedEvent) -> Optional[RoundLedger]:
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
                if c and c in r.pending_tools:
                    r.pending_tools.discard(c)
                    removed = True
            if not removed and len(r.pending_tools) == 1:
                r.pending_tools.clear()
        elif ev.kind == "process_started":
            r.pending_processes.add(ev.entity_id or f"proc:{int(ev.ts * 1000)}")
        elif ev.kind == "process_completed":
            if ev.entity_id and ev.entity_id in r.pending_processes:
                r.pending_processes.discard(ev.entity_id)
            elif len(r.pending_processes) == 1:
                r.pending_processes.clear()
        elif ev.kind == "subagent_started":
            r.pending_subagents.add(ev.entity_id or f"sub:{int(ev.ts * 1000)}")
        elif ev.kind == "subagent_completed":
            candidates = [ev.entity_id, ev.parent_id, ev.ids.get("subagentId")]
            removed = False
            for c in candidates:
                if c and c in r.pending_subagents:
                    r.pending_subagents.discard(c)
                    removed = True
            if not removed and len(r.pending_subagents) == 1:
                r.pending_subagents.clear()
        elif ev.kind == "response_routed":
            r.response_routed = True
        elif ev.kind == "turn_completed":
            r.llm_completed = True
            r.response_routed = True
            r.pending_tools.clear()
            r.pending_processes.clear()
            r.pending_subagents.clear()
        elif ev.kind == "turn_failed":
            r.failed = True

    def _maybe_end(self, r: RoundLedger) -> None:
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
        for k, v in ev.ids.items():
            if v:
                r.ids[k] = v
        if ev.session_key and ev.session_key != "unknown":
            r.session_key = ev.session_key


# ═══════════════════════════════════════════════════════════════════════════════
# File Tailer
# ═══════════════════════════════════════════════════════════════════════════════

class FileTailer:
    def __init__(self, paths: List[Path], from_end: bool = True):
        self.paths = paths
        self.from_end = from_end
        self.positions: Dict[Path, int] = {}
        self.inodes: Dict[Path, Tuple[int, int]] = {}

    def scan_new_lines(self) -> Iterable[Tuple[Path, str]]:
        for path in self.paths:
            if not path.exists() or not path.is_file():
                continue
            try:
                st = path.stat()
                inode = (st.st_dev, st.st_ino)
                prev_inode = self.inodes.get(path)
                if prev_inode != inode:
                    self.inodes[path] = inode
                    self.positions[path] = st.st_size if self.from_end else 0
                pos = self.positions.get(path, st.st_size if self.from_end else 0)
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
    patterns = ["**/*.log", "**/*.jsonl", "**/*.ndjson"]
    files: List[Path] = []
    for pat in patterns:
        for p in glob.glob(str(log_root / pat), recursive=True):
            path = Path(p)
            if path.is_file():
                files.append(path)
    files = sorted(set(files), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return files[:max_files]


# ═══════════════════════════════════════════════════════════════════════════════
# Gateway Log Parsing (from openclaw_orchestrator.py)
# ═══════════════════════════════════════════════════════════════════════════════

def parse_timestr_to_dt(timestr: str) -> Optional[datetime]:
    if not timestr or not isinstance(timestr, str):
        return None
    ts = timestr.strip()
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
    for key in ("time", "createdAt", "created_at", "timestamp", "date"):
        if key in obj:
            dt = parse_timestr_to_dt(str(obj[key]))
            if dt:
                return dt
    return None


def to_epoch(dt: Optional[datetime], ref_dt: Optional[datetime] = None) -> Optional[float]:
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


def _get_portkey_messages(obj: dict) -> Optional[List[dict]]:
    """Extract messages array from Portkey gateway log structure.
    
    Portkey log format:
      {time, sourceType, method, endpoint, status, duration, requestOptions, response}
      requestOptions[0].finalUntransformedRequest.body.messages = [...]
    """
    # Try Portkey structure first
    ro = obj.get("requestOptions")
    if isinstance(ro, list) and ro:
        ro0 = ro[0] if isinstance(ro[0], dict) else {}
        fur = ro0.get("finalUntransformedRequest")
        if isinstance(fur, dict):
            body = fur.get("body")
            if isinstance(body, dict) and isinstance(body.get("messages"), list):
                return body["messages"]
        # Fallback: requestOptions[0].transformedRequest
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
        for k in path_keys:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                cur = None
                break
        if isinstance(cur, list):
            return cur

    # Deep search
    def deep_find(o):
        if isinstance(o, dict):
            msgs = o.get("messages")
            if isinstance(msgs, list) and any(isinstance(m, dict) and "role" in m for m in msgs):
                return msgs
            for v in o.values():
                r = deep_find(v)
                if r:
                    return r
        return None
    return deep_find(obj)


def _get_portkey_response(obj: dict) -> Optional[dict]:
    """Extract the LLM response from Portkey gateway log."""
    ro = obj.get("requestOptions")
    if isinstance(ro, list) and ro:
        ro0 = ro[0] if isinstance(ro[0], dict) else {}
        orig = ro0.get("originalResponse")
        if isinstance(orig, dict) and orig.get("choices"):
            return orig
        resp = ro0.get("response")
        if isinstance(resp, dict):
            return resp
    resp = obj.get("response")
    if isinstance(resp, dict):
        return resp
    return None


def _clean_sender_metadata(text: str) -> str:
    """Remove OpenClaw Sender (untrusted metadata) wrapper from user text."""
    import re as _re
    cleaned = _re.sub(
        r"Sender\s*\(untrusted metadata\):\s*```json\s*\{[^}]*\}\s*```\s*",
        "", text, flags=_re.DOTALL
    )
    return cleaned.strip()


def _extract_text_from_content(content) -> Optional[str]:
    """Extract plain text from OpenAI-style message content."""
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
    return _get_portkey_messages(obj)



FILE_PARAM_HINTS = {
    "path", "file", "filepath", "file_path", "filename", "dir",
    "directory", "target", "source", "src", "dst", "dest",
}

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
    if not isinstance(value, str) or not value.strip():
        return False
    v = value.strip().strip("'\"")
    if re.search(r"\s", v):
        return False
    return v.startswith("/") or v.startswith("./") or v.startswith("../") or v.startswith("~/") or "/" in v or bool(re.search(r"\.[A-Za-z0-9_+-]{1,12}$", v))


def resources_from_command(command: str) -> List[dict]:
    resources = []
    seen = set()
    if not command.strip():
        return resources
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
def build_actions_from_trajectory(trajectory: List[dict]) -> List[dict]:
    """Parse tool calls from trajectory messages into action records."""
    actions = []
    tool_results: Dict[str, dict] = {}
    for msg in trajectory:
        if isinstance(msg, dict) and msg.get("role") == "tool":
            tcid = msg.get("tool_call_id")
            if tcid:
                tool_results[tcid] = msg

    for msg in trajectory:
        if not isinstance(msg, dict):
            continue
        tool_calls = msg.get("tool_calls")
        if not isinstance(tool_calls, list):
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
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    return now.strftime("%Y-%m-%d %H:%M:%S.") + f"{now.microsecond // 1000:03d}+0800"


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
        try:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
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
                f"{len(data.get('ir_json','') or '')} err={e}",
                flush=True,
            )
    threading.Thread(target=_do_post, daemon=True).start()


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


def truncate_text(text: str, max_len: int = 2000) -> str:
    """Truncate text with [Truncated] marker if too long."""
    if not text or len(text) <= max_len:
        return text
    return text[:max_len] + " [Truncated]"


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
                        elif isinstance(c, dict) and c.get("type") == "text" and c.get("text"):
                            last_assistant_text = c.get("text", "")
                    
                    if tool_calls_in_msg and msg_id:
                        pending_tool_calls[msg_id] = tool_calls_in_msg
                        current_assistant_id = msg_id
                    
                    if stop_reason in ("stop", "end_turn", "complete"):
                        break
                
                # toolResult - attach result to matching action
                if role == "toolResult" and parent_id and isinstance(content, list):
                    result_text = ""
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            result_text += c.get("text", "")
                    
                    # Find the action(s) from the parent assistant message
                    if parent_id in pending_tool_calls:
                        parent_actions = pending_tool_calls[parent_id]
                        # Attach result to first action without result
                        for pa in parent_actions:
                            if "result" not in pa:
                                pa["result"] = result_text[:2000]
                                break
    except Exception:
        pass
    
    result["actions"] = actions
    result["last_llm_msg"] = last_assistant_text
    return result

class MonitorOrchestrator:
    """Main monitor process that coordinates watcher + gateway + IR + judge."""

    LOADING_MARKER = "__loading__"

    def __init__(self, openclaw_log_root: str = DEFAULT_OPENCLAW_LOG_ROOT, gateway_log_path: str = ""):
        self.openclaw_log_root = Path(openclaw_log_root).expanduser()
        self.gateway_log_path = Path(gateway_log_path) if gateway_log_path else None
        self.running = False
        self._round_start_times: Dict[str, float] = {}
        self._round_ir_results: Dict[str, Dict] = {}
        self._round_queries: Dict[str, str] = {}
        self._round_workers: Dict[str, threading.Thread] = {}
        self._round_histories: Dict[str, List[Dict[str, str]]] = {}  # 存储每个 round 的 history
        self._round_actions: Dict[str, List[Dict]] = {}  # 存储每个 round 的 actions
        # Cache the OpenClaw main process across rounds: (pid, starttime_ticks).
        # If the cached PID still exists with the same starttime at the next
        # round_start, proc_info.collect_for_round skips its full /proc scan.
        self._main_pid_cache = None
        
        # 存储 tool_started 的信息，用于在 tool_completed 时关联
        # key: toolCallId, value: {toolName, paramsPreview, ...}
        self._pending_tool_traces: Dict[str, Dict[str, Any]] = {}

        self.sm = RoundStateMachine(
            on_round_start=self._on_round_start,
            on_round_end=self._on_round_end,
        )

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
        config = get_config_from_db()
        gw_path = config.get("gateway_log_path", "")
        if gw_path:
            self.gateway_log_path = Path(gw_path)
        if self.gateway_log_path and self.gateway_log_path.exists():
            return self.gateway_log_path if self.gateway_log_path.is_dir() else self.gateway_log_path.parent
        return None

    def _should_use_gateway(self) -> bool:
        """Check config: whether to use gateway logs for action data."""
        config = get_config_from_db()
        return config.get("use_gateway", "false").lower() == "true"


    def _on_round_start(self, r: RoundLedger) -> None:
        self._round_start_times[r.round_id] = r.started_at
        print(f"[monitor] ROUND_STARTED round_id={r.round_id} session={r.session_key} time={format_bj_time()}", flush=True)

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
            "round_id": r.round_id,
            "time_start": format_bj_time(),
            "session_key": session_key,
            "session_id": session_id,
            "attack_config": attack_config,
            "pid_info": pid_info,
            "history": json.dumps(history, ensure_ascii=False) if history else "",
        })

        t = threading.Thread(target=self._query_and_ir_worker, args=(r.round_id, r.started_at), daemon=True)
        self._round_workers[r.round_id] = t
        t.start()

    def _query_and_ir_worker(self, round_id: str, start_time: float) -> None:
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
            history = self._round_histories.get(round_id, [])

        report_to_clawavc({"event": "end", "round_id": round_id, "time_end": "", "user_query": user_query, "history": json.dumps(history, ensure_ascii=False) if history else "", "action_json": "[]", "ir_json": self.LOADING_MARKER})

        try:
            ir_result, ir_error = ir_translate(query=user_query, round_id=round_id, use_llm=True)
            if ir_error:
                print(f"[monitor] IR error for {round_id}: {ir_error}", flush=True)
            self._round_ir_results[round_id] = ir_result or {}
        except Exception as e:
            print(f"[monitor] IR exception for {round_id}: {e}", flush=True)
            self._round_ir_results[round_id] = {}

        ir_data = self._round_ir_results.get(round_id, {})
        
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
        
        # 调用 judge：检查 actions 和 ir_data 是否都有值
        # Judge 结果只更新数据库，不广播
        actions = self._round_actions.get(round_id, [])
        if actions and ir_data:
            try:
                judge_result = judge(actions, ir_data)
                import re as _re
                score_match = _re.search(r"整体得分:\s*([0-9.]+)", judge_result)
                judge_score = float(score_match.group(1)) if score_match else -1.0
                
                # 只更新数据库，不广播
                from auditor.monitor.watcher import format_bj_time as _fmt_time
                payload = {
                    "event": "end",
                    "round_id": round_id,
                    "time_end": _fmt_time(),
                    "judge_result": judge_result,
                    "overall_score": judge_score,
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
        elif not actions:
            print(f"[monitor] No actions for {round_id}, skipping judge in worker", flush=True)
        elif not ir_data:
            print(f"[monitor] No IR data for {round_id}, skipping judge in worker", flush=True)
        
        print(f"[monitor] IR ready for {round_id}", flush=True)

        # 发布到 clawAVC turn-ir long-poll 缓存：唤醒所有正在 wait 的 portkey 长轮询线程。
        # 此处必须用与 portkey/clawAVC 同款 normalize 规则做 cache key，
        # 由 _turn_ir_publish_translation 内部 _normalize_user_query 完成。
        try:
            from app import _turn_ir_publish_translation  # type: ignore
            _turn_ir_publish_translation(user_query, ir_data or {})
        except Exception as e:
            print(f"[monitor] turn-ir publish failed for {round_id}: {e}", flush=True)

    def _on_round_end(self, r: RoundLedger) -> None:
        print(f"[monitor] ROUND_ENDED round_id={r.round_id} session={r.session_key} time={format_bj_time()}", flush=True)

        start_time = self._round_start_times.pop(r.round_id, r.started_at)
        start_dt = datetime.fromtimestamp(start_time, tz=ZoneInfo("Asia/Shanghai"))

        # 注意：不再等待 _query_and_ir_worker 线程
        # round_end 和 round_ir_ready 是独立的，不应该互相阻塞
        # worker 线程会自己完成翻译并更新数据库
        _ = self._round_workers.pop(r.round_id, None)  # 只是清理，不等待

        user_query = self._round_queries.pop(r.round_id, None)
        ir_result = self._round_ir_results.pop(r.round_id, None)
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
                # Extract from OpenClaw session log
                oc_data = extract_from_openclaw_session(self.openclaw_log_root, r.round_id, start_time)
                if not user_query:
                    user_query = oc_data.get("user_query")
                actions = oc_data.get("actions", [])
                last_llm_msg = oc_data.get("last_llm_msg")

        # round_end 不再等待翻译完成，直接使用已有的 ir_result（可能为 None）
        # 翻译是异步进行的，round_end 只负责发送最终的 judge 结果
        # 如果 ir_result 为 None，说明翻译还没完成，使用空结果
        if ir_result is None:
            ir_result = {}
            print(f"[monitor] IR not ready for {r.round_id}, using empty result", flush=True)

        # 存储 actions 供后续使用
        self._round_actions[r.round_id] = actions

        judge_result = ""
        judge_score = -1.0
        
        session_key = r.session_key if r.session_key != "unknown" else ""
        session_id = r.ids.get("session_id") or r.ids.get("sessionId") or ""

        # 检测到 agent turn 结束，立即发送 round_end
        # round_end 只需要 action_json，其他字段保持原值
        # 不包含 overall_score，因为 round_end 推送只与 action 有关
        out = {
            "event": "end",
            "round_id": r.round_id,
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

        # 延迟 500ms 后调用 judge，等待 IR 翻译完成
        # Judge 结果只更新数据库，不广播
        def delayed_judge():
            try:
                # 等待 500ms，让 IR 翻译完成
                time.sleep(0.5)
                
                # 获取最新的 actions 和 ir_data
                current_actions = self._round_actions.get(r.round_id, [])
                current_ir_data = self._round_ir_results.get(r.round_id, {})
                
                print(f"[monitor] Delayed judge check for {r.round_id}: actions_count={len(current_actions)} ir_data_count={len(current_ir_data)}", flush=True)
                
                if current_actions and current_ir_data:
                    try:
                        judge_result = judge(current_actions, current_ir_data)
                        import re as _re
                        score_match = _re.search(r"整体得分:\s*([0-9.]+)", judge_result)
                        judge_score = float(score_match.group(1)) if score_match else -1.0
                        
                        # 只更新数据库，不广播
                        from auditor.monitor.watcher import format_bj_time as _fmt_time
                        payload = {
                            "event": "end",
                            "round_id": r.round_id,
                            "time_end": _fmt_time(),
                            "judge_result": judge_result,
                            "overall_score": judge_score,
                        }
                        import json as _json
                        req = urllib.request.Request(
                            CLAWAVC_ROUNDS_API,
                            data=_json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        urllib.request.urlopen(req, timeout=5)
                        print(f"[monitor] Judge result updated (end) for {r.round_id}: score={judge_score}", flush=True)
                    except Exception as e:
                        print(f"[monitor] Judge error for {r.round_id}: {e}", flush=True)
                elif not current_actions:
                    print(f"[monitor] No actions for {r.round_id}, skipping judge", flush=True)
                elif not current_ir_data:
                    print(f"[monitor] No IR data for {r.round_id}, skipping judge", flush=True)
            except Exception as e:
                print(f"[monitor] Delayed judge error for {r.round_id}: {e}", flush=True)
        
        # 启动延迟 judge 线程
        judge_thread = threading.Thread(target=delayed_judge, daemon=True)
        judge_thread.start()
        print(f"[monitor] Started delayed judge thread for {r.round_id}", flush=True)
    def run(self) -> None:
        """Main blocking loop."""
        self.running = True
        print(f"[monitor] Starting monitor...", flush=True)
        print(f"[monitor] OpenClaw logs: {self.openclaw_log_root}", flush=True)
        print(f"[monitor] Gateway logs: {self.gateway_log_path or '(from config)'}", flush=True)

        # Discover openclaw log files
        files = discover_log_files(self.openclaw_log_root)
        if not files:
            print(f"[monitor] WARNING: No log files found in {self.openclaw_log_root}", flush=True)

        tailer = FileTailer(files, from_end=True)
        last_rescan = time.time()

        def _stop(signum, frame):
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

            self.sm.check_idle_end()

            # Periodically rescan for new files
            now = time.time()
            if now - last_rescan >= 30:
                tailer.paths = discover_log_files(self.openclaw_log_root)
                last_rescan = now

            time.sleep(POLL_INTERVAL)

        print("[monitor] Stopped.", flush=True)


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
