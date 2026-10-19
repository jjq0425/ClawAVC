# -*- coding: utf-8 -*-
"""越权资源访问证据提取。

从 Round 的内核态 LSM Hook 事件流、kernel_resource_facts、ir_json、pid_info 中
提取「Agent 实际访问了哪些资源」，并按 (资源, 对象类, 权限集, 资源角色) 聚合去重，
作为 SELinux 策略建议的唯一证据源。

权限集一律从事件本身的语义推导（open flags / mprotect prot / socket 族与类型），
不做任何按路径猜测类型的行为——目标类型由 selinux_policy_query 实时解析。
"""

from __future__ import annotations

import json
import os
import re
from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Optional, Tuple

# 单轮最多读取的事件数，防止异常大的采集文件拖垮分析
MAX_EVENTS_PER_ROUND = 200000
# 每条聚合证据最多保留的 event_id 数
MAX_EVENT_IDS_PER_ACCESS = 5
# 输出给 LLM 的聚合证据条数上限
MAX_ACCESSES_FOR_LLM = 120

# hook_name → (对象类, 该类下由 hook 语义直接确定的权限)
# 权限为 None 表示需要从 args 进一步推导
_HOOK_CLASS_PERMS: Dict[str, Tuple[str, Optional[List[str]]]] = {
    "file_open": ("file", None),
    "file_permission": ("file", None),
    "file_mprotect": ("file", None),
    "inode_unlink": ("file", ["unlink"]),
    "inode_create": ("file", ["create"]),
    "inode_rename": ("file", ["rename"]),
    "inode_setattr": ("file", ["setattr"]),
    "inode_getattr": ("file", ["getattr"]),
    "bprm_check": ("file", ["execute"]),
    "socket_create": (None, ["create"]),
    "socket_bind": (None, ["bind"]),
    "socket_connect": (None, None),
    "socket_accept": (None, ["accept"]),
    "socket_sendmsg": (None, ["write"]),
    "socket_recvmsg": (None, ["read"]),
    "socket_setsockopt": (None, ["setopt"]),
    "socket_getsockopt": (None, ["getopt"]),
    "socket_shutdown": (None, ["shutdown"]),
}

# 敏感资源角色：这类访问属于越权，禁止为其生成 allow 规则
SENSITIVE_ROLES = {"privacy_resource"}

# resource_role 缺失时的兜底（例如证据只来自 kernel_resource_facts，或 LSM 文件不可读）。
# 误判为 sensitive 的后果只是判 NO_CHANGE，漏判的后果是把凭据读取写成 allow 规则，
# 因此这里宁严勿松。
SENSITIVE_PATH_RES = (
    re.compile(r"^/(?:root|home/[^/]+)/\.ssh(?:/|$)"),
    re.compile(r"^/(?:root|home/[^/]+)/\.(?:gnupg|aws|kube|docker|netrc|bash_history|python_history)(?:/|$)"),
    re.compile(r"^/(?:root|home/[^/]+)/\.[^/]*(?:token|secret|credential|api_?key|private_?key)[^/]*$"),
    re.compile(r"^/etc/(?:passwd|shadow|gshadow|group|sudoers|sudoers\.d)(?:/|$)"),
    re.compile(r"^/etc/(?:ssh|pam\.d|krb5\.keytab)(?:/|$)"),
    re.compile(r"\.(?:key|p12|pfx)$"),
    re.compile(r"(?:^|/)id_(?:rsa|dsa|ecdsa|ed25519)$"),
    re.compile(r"^/run/systemd/userdb(?:/|$)"),
)

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ─── 基础读取 ─────────────────────────────────────────────────────


def _iter_jsonl(path: str, limit: int = MAX_EVENTS_PER_ROUND) -> Iterable[Dict[str, Any]]:
    """逐行读取 JSONL，容忍坏行与超大文件。"""
    if not path or not os.path.isfile(path):
        return
    count = 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if count >= limit:
                    return
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    count += 1
                    yield obj
    except OSError:
        return


def _read_json_field(raw: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        obj = json.loads(raw)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


# ─── 权限推导 ─────────────────────────────────────────────────────


def _perms_from_open_flags(flags: Any) -> List[str]:
    """从 open(2) flags 推导 file 类权限。无法识别时只给 open/getattr。"""
    perms = ["open", "getattr"]
    text = str(flags or "").upper()
    if not text:
        return sorted(set(perms))
    accmode = None
    for token in re.split(r"[|\s,]+", text):
        if token in ("O_RDONLY", "O_WRONLY", "O_RDWR"):
            accmode = token
        elif token == "O_CREAT":
            perms.append("create")
        elif token == "O_TRUNC":
            perms.append("write")
        elif token == "O_APPEND":
            perms.append("append")
    if accmode in ("O_WRONLY", "O_RDWR"):
        perms.append("write")
    if accmode in ("O_RDONLY", "O_RDWR") or accmode is None:
        perms.append("read")
    return sorted(set(perms))


def _perms_from_mprotect(args: Dict[str, Any]) -> List[str]:
    """从 mprotect 的 prot 推导权限；PROT_EXEC 映射为 execmod（高危，需人审）。"""
    prot = str((args or {}).get("prot") or "").upper()
    if "PROT_EXEC" in prot:
        return ["execmod"]
    if "PROT_WRITE" in prot:
        return ["write"]
    return ["read"]


def _sock_class(args: Dict[str, Any]) -> str:
    """按 socket 类型与地址族确定对象类。"""
    stype = str((args or {}).get("type") or "").upper()
    family = str((args or {}).get("sa_family") or "").upper()
    if "AF_UNIX" in family:
        return "unix_stream_socket" if "STREAM" in stype else "unix_dgram_socket"
    if "DGRAM" in stype:
        return "udp_socket"
    return "tcp_socket"


def _network_perms(hook_name: str, args: Dict[str, Any]) -> List[str]:
    """网络类 hook 的权限推导。"""
    if hook_name == "socket_connect":
        family = str((args or {}).get("sa_family") or "").upper()
        # AF_UNIX 的 connect 走 connectto，INET 的 connect 走 name_connect
        return ["connectto"] if "AF_UNIX" in family else ["name_connect"]
    _, perms = _HOOK_CLASS_PERMS.get(hook_name, (None, None))
    return list(perms or [])


def _file_tclass_and_perms(path: str, perms: List[str]) -> Tuple[str, List[str]]:
    """区分 file / dir 对象类：SELinux 对目录的权限集与文件不通用
    （打开目录要 dir:search，删除目录是 rmdir 而不是 unlink），
    一律记成 file 会产出在目标机上无效的 allow 规则。

    按分析机上的实际条目判断；路径在本地不存在时回落为 file ——
    与查询链路「分析机即目标机」的既有假设一致。
    """
    try:
        is_dir = os.path.isdir(path)
    except OSError:
        is_dir = False
    if not is_dir:
        return "file", perms
    adjusted = set(perms)
    if {"read", "open"} & adjusted:
        adjusted.add("search")
    if "unlink" in adjusted:
        adjusted.discard("unlink")
        adjusted.add("rmdir")
    return "dir", sorted(adjusted)


# ─── 单事件 → 访问记录 ────────────────────────────────────────────


def _access_from_lsm_event(ev: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """把一条 LSM Hook 事件归一化为访问记录；无法定位资源时返回 None。"""
    hook = str(ev.get("hook_name") or "").strip()
    if not hook:
        return None
    args = ev.get("args") if isinstance(ev.get("args"), dict) else {}

    if hook.startswith("socket_") or args.get("sa_family") or args.get("sun_path"):
        tclass = _sock_class(args)
        sun_path = args.get("sun_path")
        target = str(ev.get("network_target") or "")
        if not target and sun_path:
            target = str(sun_path)
        if not target:
            target = str(ev.get("remote_ip") or "")
        if not target:
            return None
        perms = _network_perms(hook, args)
        if hook == "socket_create":
            perms = ["create"]
        rec = {
            "kind": "network",
            "resource": target,
            "hooks": [hook],
            "tclass": tclass,
            "perms": perms,
            "sock_type": args.get("type") or "",
            "port": _parse_port(args, target),
            "sun_path": sun_path or "",
        }
    else:
        path = ev.get("path") or args.get("pathname") or args.get("syscall_pathname")
        if not path:
            return None
        path = str(path)
        entry = _HOOK_CLASS_PERMS.get(hook)
        if entry is None:
            return None
        _, fixed = entry
        if hook == "file_open":
            perms = _perms_from_open_flags(args.get("flags"))
        elif hook == "file_mprotect":
            perms = _perms_from_mprotect(args)
        elif hook == "file_permission":
            perms = _perms_from_open_flags(args.get("flags") or args.get("mask"))
        else:
            perms = list(fixed or [])
        tclass, perms = _file_tclass_and_perms(path, perms)
        rec = {
            "kind": "file",
            "resource": path,
            "hooks": [hook],
            "tclass": tclass,
            "perms": perms,
            "sock_type": "",
            "port": None,
            "sun_path": "",
        }

    rec.update({
        "resource_role": str(ev.get("resource_role") or ""),
        "category": str(ev.get("category") or ""),
        "event_ids": [str(ev["event_id"])] if ev.get("event_id") else [],
        "tool_names": [str(ev["tool_name"])] if ev.get("tool_name") else [],
        "count": 1,
    })
    return rec


def _parse_port(args: Dict[str, Any], target: str) -> Optional[int]:
    raw = args.get("sin_port") or args.get("sin6_port")
    if raw is None and ":" in target:
        raw = target.rsplit(":", 1)[-1]
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _access_from_resource_fact(fact: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """kernel_resource_facts 里的资源事实，作为 LSM 事件缺失时的兜底证据源。"""
    ftype = fact.get("type")
    actions = [str(a) for a in (fact.get("actions") or []) if a]
    if ftype == "file_access":
        path = fact.get("path")
        if not path:
            return None
        perms = sorted({p for a in actions for p in _action_perms(a)}) or ["getattr"]
        tclass, perms = _file_tclass_and_perms(str(path), perms)
        return {
            "kind": "file", "resource": str(path), "hooks": [], "tclass": tclass,
            "perms": perms, "sock_type": "", "port": None, "sun_path": "",
            "resource_role": "", "category": str(fact.get("category") or ""),
            "event_ids": [str(e) for e in (fact.get("evidence_event_ids") or [])][:MAX_EVENT_IDS_PER_ACCESS],
            "tool_names": [],
            "count": int(fact.get("open_count") or fact.get("read_count") or 1),
        }
    if ftype == "network_access":
        target = fact.get("network_target") or fact.get("remote_ip")
        if not target:
            return None
        perms = sorted({p for a in actions for p in _network_action_perms(a)}) or ["name_connect"]
        return {
            "kind": "network", "resource": str(target), "hooks": [],
            "tclass": "tcp_socket", "perms": perms, "sock_type": "",
            "port": _parse_port({}, str(target)), "sun_path": "",
            "resource_role": "", "category": "",
            "event_ids": [str(e) for e in (fact.get("evidence_event_ids") or [])][:MAX_EVENT_IDS_PER_ACCESS],
            "tool_names": [],
            "count": int(fact.get("connect_count") or 1),
        }
    return None


_ACTION_PERM_MAP = {
    "read": "read", "write": "write", "open": "open", "create": "create",
    "append": "append", "execute": "execute", "getattr": "getattr",
    "setattr": "setattr", "rename": "rename", "unlink": "unlink", "link": "link",
}
_NETWORK_ACTION_PERM_MAP = {
    "connect": "name_connect", "bind": "name_bind", "accept": "accept",
    "send": "write", "receive": "read", "listen": "listen", "create": "create",
}


def _action_perms(action: str) -> List[str]:
    perm = _ACTION_PERM_MAP.get(str(action).lower())
    return [perm] if perm else []


def _network_action_perms(action: str) -> List[str]:
    perm = _NETWORK_ACTION_PERM_MAP.get(str(action).lower())
    return [perm] if perm else []


# ─── 聚合 ─────────────────────────────────────────────────────────


def _agg_key(rec: Dict[str, Any]) -> Tuple:
    return (rec["kind"], rec["resource"], rec["tclass"],
            tuple(sorted(rec["perms"])), rec.get("resource_role") or "")


def aggregate(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按 (资源, 对象类, 权限集, 资源角色) 聚合，保留计数、hook 集合与样本 event_id。"""
    buckets: "OrderedDict[Tuple, Dict[str, Any]]" = OrderedDict()
    for rec in records:
        key = _agg_key(rec)
        slot = buckets.get(key)
        if slot is None:
            slot = dict(rec)
            slot["hooks"] = list(rec["hooks"])
            slot["event_ids"] = list(rec["event_ids"])[:MAX_EVENT_IDS_PER_ACCESS]
            slot["tool_names"] = list(rec["tool_names"])
            slot["count"] = int(rec.get("count") or 1)
            buckets[key] = slot
            continue
        slot["count"] += int(rec.get("count") or 1)
        for hook in rec["hooks"]:
            if hook and hook not in slot["hooks"]:
                slot["hooks"].append(hook)
        for tool in rec["tool_names"]:
            if tool and tool not in slot["tool_names"]:
                slot["tool_names"].append(tool)
        for eid in rec["event_ids"]:
            if eid and eid not in slot["event_ids"] and len(slot["event_ids"]) < MAX_EVENT_IDS_PER_ACCESS:
                slot["event_ids"].append(eid)
        if not slot.get("category") and rec.get("category"):
            slot["category"] = rec["category"]

    out = list(buckets.values())
    # 敏感资源排前面，其余按访问次数降序，保证截断时优先保留高价值证据
    out.sort(key=lambda r: (0 if r.get("resource_role") in SENSITIVE_ROLES else 1, -r["count"]))
    for idx, rec in enumerate(out, 1):
        rec["access_id"] = "acc_%04d" % idx
    return out


# ─── Round 级上下文 ───────────────────────────────────────────────


def source_type_from_pid_info(raw: Any) -> str:
    """从 pid_info 提取主体 SELinux 类型（user:role:type:level 的第三段）。"""
    obj = _read_json_field(raw)
    if not obj:
        return ""
    label = str(obj.get("main_selinux_label") or "")
    parts = label.split(":")
    if len(parts) >= 3:
        return parts[2]
    return parts[-1] if parts else ""


def posture_from_pid_info(raw: Any) -> Dict[str, Any]:
    """采集时刻目标机的 SELinux 姿态（permissive/enforcing 直接影响结论表述）。"""
    obj = _read_json_field(raw) or {}
    se = ((obj.get("system") or {}).get("selinux")) or {}
    return {
        "mode": str(se.get("mode") or ""),
        "policyvers": str(se.get("policyvers") or ""),
        "mls": str(se.get("mls") or ""),
        "hostname": str((obj.get("system") or {}).get("hostname") or ""),
        "kernel": str((obj.get("system") or {}).get("kernel") or ""),
        "main_selinux_label": str(obj.get("main_selinux_label") or ""),
        "apparmor_enabled": bool((obj.get("system") or {}).get("apparmor", {}).get("enabled")),
    }


def declared_from_ir(raw: Any) -> Dict[str, List[str]]:
    """从 ir_json 提取用户态声明的允许集（文件路径 / 工具 / 网络目标）。"""
    declared: Dict[str, List[str]] = {"files": [], "tools": [], "networks": []}
    obj = _read_json_field(raw)
    if not obj:
        return declared
    level2 = obj.get("level2") if isinstance(obj.get("level2"), dict) else obj
    for policy in (level2 or {}).get("policies") or []:
        if not isinstance(policy, dict):
            continue
        if str(policy.get("effect") or "allow").lower() != "allow":
            continue
        for obj_item in policy.get("objects") or []:
            if not isinstance(obj_item, dict):
                continue
            ident = str(obj_item.get("identifier") or "")
            if not ident:
                continue
            otype = str(obj_item.get("type") or "").lower()
            bucket = "tools" if otype == "tool" else ("networks" if otype in ("network", "ip", "domain") else "files")
            if ident not in declared[bucket]:
                declared[bucket].append(ident)
    return declared


def _sensitive_by_path(resource: str) -> bool:
    """按路径兜底判定隐私资源。

    resource_role 只有 LSM 事件才带；LSM 文件不可读或证据只来自 kernel_resource_facts 时，
    敏感标记会整个丢失，凭据读取就会被当成普通越权候选。这里补一道兜底。
    """
    return any(rx.search(resource) for rx in SENSITIVE_PATH_RES)


def classify(rec: Dict[str, Any], declared: Dict[str, List[str]]) -> str:
    """判定一条访问相对声明允许集的状态。

    sensitive   — 命中敏感资源角色或敏感路径，禁止生成 allow
    declared    — ir_json 已声明，属预期访问
    runtime     — 采集器自身运行时资源
    undeclared  — 未在 ir_json 声明，属越权候选
    """
    role = rec.get("resource_role") or ""
    if role in SENSITIVE_ROLES:
        return "sensitive"
    if rec.get("kind") == "file" and _sensitive_by_path(str(rec.get("resource") or "")):
        return "sensitive"
    if role == "openclaw_runtime":
        return "runtime"
    if role == "declared_resource":
        return "declared"
    resource = rec.get("resource") or ""
    bucket = declared.get("files" if rec.get("kind") == "file" else "networks") or []
    if resource in bucket or any(resource.startswith(p.rstrip("/") + "/") for p in bucket if p.startswith("/")):
        return "declared"
    return "undeclared"


# ─── 主入口 ───────────────────────────────────────────────────────


def collect(row: Dict[str, Any], max_accesses: int = MAX_ACCESSES_FOR_LLM) -> Dict[str, Any]:
    """从一条 rounds 记录构建越权资源访问证据包。

    返回结构直接作为 get_overprivilege_evidence 工具的输出，字段均已限界。
    """
    declared = declared_from_ir(row.get("ir_json"))
    posture = posture_from_pid_info(row.get("pid_info"))
    source_type = source_type_from_pid_info(row.get("pid_info"))

    records: List[Dict[str, Any]] = []
    sources: Dict[str, Any] = {"lsm_hook_events": 0, "resource_facts": 0, "lsm_hook_path": "", "readable": False}

    lsm_path = str(row.get("kernel_lsm_hook_result") or "")
    sources["lsm_hook_path"] = lsm_path
    if lsm_path and os.path.isfile(lsm_path):
        sources["readable"] = True
        for ev in _iter_jsonl(lsm_path):
            rec = _access_from_lsm_event(ev)
            if rec is not None:
                records.append(rec)
                sources["lsm_hook_events"] += 1

    facts = _read_json_field(row.get("kernel_resource_facts"))
    if facts:
        for tool_call in facts.get("tool_calls") or []:
            if not isinstance(tool_call, dict):
                continue
            tool_name = str(tool_call.get("tool_name") or "")
            for fact in tool_call.get("resource_facts") or []:
                if not isinstance(fact, dict):
                    continue
                rec = _access_from_resource_fact(fact)
                if rec is None:
                    continue
                # LSM 事件已覆盖的路径不再重复计入，避免同一访问被两个来源放大
                if sources["lsm_hook_events"] and any(
                    r["resource"] == rec["resource"] and r["kind"] == rec["kind"] for r in records
                ):
                    continue
                if tool_name:
                    rec["tool_names"] = [tool_name]
                records.append(rec)
                sources["resource_facts"] += 1

    accesses = aggregate(records)
    for rec in accesses:
        rec["declaration"] = classify(rec, declared)
    # aggregate 只能按 resource_role 排序，路径兜底判出的 sensitive 要重排到前面，
    # 否则截断时最先丢掉的恰好是最该让 LLM 看见的证据
    accesses.sort(key=lambda r: (0 if r["declaration"] == "sensitive" else 1, -r["count"]))
    for idx, rec in enumerate(accesses, 1):
        rec["access_id"] = "acc_%04d" % idx

    total = len(accesses)
    trimmed = accesses[:max_accesses]
    by_declaration: Dict[str, int] = {}
    for rec in accesses:
        by_declaration[rec["declaration"]] = by_declaration.get(rec["declaration"], 0) + 1

    return {
        "round_id": row.get("round_id"),
        "source_type": source_type,
        "selinux_posture": posture,
        "declared_allow_set": declared,
        "summary": {
            "access_count": total,
            "returned_count": len(trimmed),
            "truncated": total > len(trimmed),
            "by_declaration": by_declaration,
            "by_resource_role": _count_by(accesses, "resource_role"),
            "by_tclass": _count_by(accesses, "tclass"),
            "sensitive_resources": [
                {"access_id": r["access_id"], "resource": r["resource"], "tclass": r["tclass"],
                 "perms": r["perms"], "category": r.get("category") or "", "count": r["count"]}
                for r in accesses if r["declaration"] == "sensitive"
            ][:40],
        },
        "sources": sources,
        "accesses": trimmed,
    }


def _count_by(records: List[Dict[str, Any]], field: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for rec in records:
        key = str(rec.get(field) or "(empty)")
        out[key] = out.get(key, 0) + 1
    return out


def index_by_id(evidence: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """access_id → 访问记录，供 emit_policy_proposal 校验引用有效性。"""
    return {rec["access_id"]: rec for rec in evidence.get("accesses", [])}


def perms_for(evidence: Dict[str, Any], access_ids: Iterable[str]) -> Dict[str, set]:
    """按 (source_type, tclass) 汇总被引证据实际观察到的权限集，用于最小化校验。"""
    idx = index_by_id(evidence)
    out: Dict[str, set] = {}
    src = evidence.get("source_type") or ""
    for aid in access_ids:
        rec = idx.get(aid)
        if not rec:
            continue
        key = "%s|%s" % (src, rec.get("tclass") or "")
        out.setdefault(key, set()).update(rec.get("perms") or [])
    return out


def is_valid_identifier(name: str) -> bool:
    return bool(_IDENT_RE.match(str(name or "")))
