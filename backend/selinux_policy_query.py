# -*- coding: utf-8 -*-
"""本机 SELinux 策略定向查询（全程只读）。

对上层暴露五个查询 + 一个组合探针::

    posture()                                   当前 SELinux 运行状态
    path_type(path)                             路径的实际标签与默认标签
    type_info(name)                             类型/属性是否存在、展开成哪些类型
    allow_search(src, tgt, tclass, perms)       按四元组反查已存在的 allow 规则
    port_type(port, proto)                      端口对应的 SELinux 类型
    probe_access(src, resource, tclass, perms)  组合上面几个：这次访问是否已被放行

为什么是"定向查询"而不是"整份策略"：
本机策略的 allow 规则量级在十万条，任何截断投喂都会让模型因为"看不到规则"
而把已放行的访问误判成缺口。这里只提供按 src/tgt/class/perm 反查的能力。

安全约束：
  * 只执行查询类命令（getenforce/sestatus/matchpathcon/seinfo/sesearch/semanage port -l）；
    本模块不存在 setenforce、semodule、restorecon、semanage -a/-d 等写操作路径
  * 全部 subprocess 数组参数 + shell=False + 固定 env + 超时；不接受调用方传入可执行路径
  * 策略文件路径由模块自行探测，不接受外部指定，避免路径穿越
  * 工具缺失时返回结构化 ``{"available": False, "missing": ...}``，
    让上层能区分"没有这条规则"和"我查不到"——后者绝不能被当成缺口证据
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import sqlite3
import subprocess
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ──────────────────────────── 常量 ────────────────────────────

FIXED_PATH = "/usr/sbin:/usr/bin:/sbin:/bin:/usr/local/sbin:/usr/local/bin"
DEFAULT_TIMEOUT = 15
MAX_RULES = 60
MAX_TYPES = 40
MAX_PATH_LEN = 4096

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LABEL_RE = re.compile(r"^([^:]*):([^:]*):([^:]*):(.*)$")

# 已知对象类白名单：拒绝把任意字符串塞进 sesearch 参数位
_VALID_CLASSES = {
    "file", "dir", "lnk_file", "sock_file", "chr_file", "blk_file", "fifo_file",
    "process", "capability", "capability2", "tcp_socket", "udp_socket",
    "rawip_socket", "unix_stream_socket", "unix_dgram_socket", "netlink_route_socket",
    "packet_socket", "node", "port", "filesystem", "key", "dbus", "system",
}

_TOOL_HINTS = {
    "getenforce": "policycoreutils（dnf install policycoreutils）",
    "sestatus": "policycoreutils（dnf install policycoreutils）",
    "matchpathcon": "policycoreutils（dnf install policycoreutils）",
    "seinfo": "setools-console（dnf install setools-console）",
    "sesearch": "setools-console（dnf install setools-console）",
    "semanage": "policycoreutils-python-utils（dnf install policycoreutils-python-utils）",
}

_ENV = {
    "PATH": FIXED_PATH,
    "LANG": "C",
    "LC_ALL": "C",
    "HOME": "/",
}

_CACHE: Dict[str, Any] = {}


def reset_cache() -> None:
    """清空缓存（测试与策略热更新后使用）。"""
    _CACHE.clear()


# ──────────────────────────── 底层执行 ────────────────────────────


def _which(name: str) -> Optional[str]:
    if name not in _CACHE:
        _CACHE["which:" + name] = shutil.which(name, path=FIXED_PATH)
    return _CACHE["which:" + name]


def _run(argv: Sequence[str], timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """执行只读查询命令。返回 rc/out/err，不抛异常。"""
    try:
        proc = subprocess.run(
            list(argv),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            env=_ENV,
            cwd="/",
            shell=False,
        )
    except FileNotFoundError:
        return {"rc": -1, "out": "", "err": "command not found"}
    except subprocess.TimeoutExpired:
        return {"rc": -2, "out": "", "err": "timeout after %ds" % timeout}
    except OSError as exc:
        return {"rc": -3, "out": "", "err": str(exc)}
    return {
        "rc": proc.returncode,
        "out": proc.stdout.decode("utf-8", "replace"),
        "err": proc.stderr.decode("utf-8", "replace"),
    }


def _unavailable(tool: str, detail: str = "") -> Dict[str, Any]:
    return {
        "available": False,
        "missing": tool,
        "hint": _TOOL_HINTS.get(tool, tool),
        "detail": detail,
        "note": "查询不可用 ≠ 规则不存在。此结果不能作为“策略缺口”的证据。",
    }


def _is_valid_ident(name: str) -> bool:
    return bool(_IDENT_RE.match(str(name or "")))


def _policy_file() -> Optional[str]:
    """探测内核已加载策略文件路径；不接受外部传入。"""
    if "policy_file" in _CACHE:
        return _CACHE["policy_file"]
    found: Optional[str] = None
    if os.path.isfile("/sys/fs/selinux/policy"):
        found = "/sys/fs/selinux/policy"
    else:
        candidates = []
        for pattern in ("/etc/selinux/*/policy/policy.*",):
            candidates.extend(glob.glob(pattern))
        # 取版本号最大的那个
        def _ver(p: str) -> Tuple[int, str]:
            tail = os.path.basename(p)
            digits = "".join(ch for ch in tail if ch.isdigit())
            return (int(digits) if digits else 0, p)

        if candidates:
            found = max(candidates, key=_ver)
    _CACHE["policy_file"] = found
    return found


# ──────────────────────────── 知识库兜底 ────────────────────────────


def _kb() -> Optional[Any]:
    """延迟导入 selinux_kb.search，用于 setools 缺失时的源码级兜底。"""
    if "kb" in _CACHE:
        return _CACHE["kb"]
    kb = None
    try:
        from selinux_kb import search as kb_search  # noqa: F401

        if os.path.isfile(kb_search.default_db_path()):
            kb = kb_search
    except Exception:
        kb = None
    _CACHE["kb"] = kb
    return kb


def _kb_query(sql: str, params: Sequence[Any], limit: int = 200) -> List[sqlite3.Row]:
    kb = _kb()
    if kb is None:
        return []
    try:
        conn = kb._connect(kb.default_db_path())
    except Exception:
        return []
    try:
        return conn.execute(sql, tuple(params) + (limit,)).fetchall()
    except Exception:
        return []
    finally:
        conn.close()


# ──────────────────────────── posture ────────────────────────────


def _parse_sestatus(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        if key:
            out[key] = value.strip()
    return out


def posture(refresh: bool = False) -> Dict[str, Any]:
    """当前 SELinux 运行状态：模式、策略名、policyvers、MLS。"""
    if not refresh and "posture" in _CACHE:
        return _CACHE["posture"]

    missing: List[str] = []
    info: Dict[str, str] = {}

    ge = _run(["getenforce"], timeout=5)
    if ge["rc"] == 0 and ge["out"].strip():
        info["runtime_mode"] = ge["out"].strip()
    else:
        missing.append("getenforce")
        if os.path.isfile("/sys/fs/selinux/enforce"):
            try:
                with open("/sys/fs/selinux/enforce", "r") as fh:
                    info["runtime_mode"] = "Enforcing" if fh.read().strip() == "1" else "Permissive"
            except OSError:
                pass

    st = _run(["sestatus"], timeout=5)
    if st["rc"] == 0 and st["out"].strip():
        info.update(_parse_sestatus(st["out"]))
    else:
        missing.append("sestatus")
        if os.path.isfile("/sys/fs/selinux/policyvers"):
            try:
                with open("/sys/fs/selinux/policyvers", "r") as fh:
                    info["policy_version"] = fh.read().strip()
            except OSError:
                pass

    selinux_status = info.get("selinux status", "").lower()
    enabled = selinux_status in ("enabled",) or bool(info.get("runtime_mode"))
    mode = (info.get("current mode") or info.get("runtime_mode") or "").lower()
    if not mode:
        mode = "disabled" if selinux_status == "disabled" else "unknown"
    if mode == "unknown" and info.get("mode from config file"):
        mode = info["mode from config file"].lower()

    result: Dict[str, Any] = {
        "available": bool(enabled or info),
        "enabled": enabled,
        "mode": mode,
        "config_mode": (info.get("mode from config file") or "").lower(),
        "policy_name": info.get("loaded policy name") or info.get("policy from config file") or "",
        "policyvers": info.get("policy version") or "",
        "mls_enabled": info.get("policy mls status", "").lower() in ("enabled",),
        "policy_file": _policy_file() or "",
        "tool_missing": missing,
        "notes": [],
    }

    src_type_note = (
        "permissive 模式下内核记录但不拦截，因此不会产生 AVC 拒绝；"
        "此时无法用拒绝日志验证规则是否缺失。本模块不会建议修改 enforce 状态。"
    )
    if mode == "permissive":
        result["notes"].append(src_type_note)
    if not result["available"]:
        result["notes"].append("无法确定本机 SELinux 状态，所有策略判断都应标记为 unknown。")

    _CACHE["posture"] = result
    return result


# ──────────────────────────── path_type ────────────────────────────


def _split_label(label: str) -> Optional[Dict[str, str]]:
    m = _LABEL_RE.match(label.strip())
    if not m:
        return None
    return {"user": m.group(1), "role": m.group(2), "type": m.group(3), "level": m.group(4)}


def _check_path(path: str) -> Optional[str]:
    """路径入参校验，返回 None 表示合法，否则返回错误说明。"""
    if not path or not isinstance(path, str):
        return "path 不能为空"
    if "\x00" in path:
        return "path 含非法字符"
    if not path.startswith("/"):
        return "path 必须是绝对路径"
    if len(path) > MAX_PATH_LEN:
        return "path 过长"
    return None


_REGEX_META = re.compile(r"[()\[\]{}.*+?|^$\\]")

# refpolicy 在 .fc 里用 m4 宏写路径，知识库保留的是未展开形式，匹配前先还原
_FC_MACROS = (("HOME_ROOT", "/root"), ("HOME_DIR", "/home/[^/]+"), ("USER", "[^/]+"))
_FC_JUNK = re.compile(r"ifdef|`|%|define|HOME_ROOT$|HOME_DIR$|USER$")

# 泛型/兜底类型：它们覆盖面极大，对一个具体客体（尤其敏感客体）几乎没有约束意义。
# 当默认类型解析成这些值时，往往不是"该路径本就该用泛型类型"，而是本机知识库不全、
# 更专门的那条 .fc 规则没被收进来（例如 /etc/shadow 在 refpolicy 里应是 shadow_t，
# 但知识库只命中了 /etc/.* → etc_t）。据此发"改标签"建议会把客体改宽而不是收窄，
# 因此这类解析一律判为不可信，禁止作为 RELABEL_OBJECT 的目标类型来源。
GENERIC_FC_TYPES = frozenset({
    "default_t", "unlabeled_t", "file_t", "etc_t", "etc_runtime_t", "var_t",
    "var_lib_t", "tmp_t", "usr_t", "bin_t", "sbin_t", "lib_t", "root_t",
    "home_root_t", "user_home_t", "user_home_dir_t", "device_t", "sysfs_t", "proc_t",
})

# 只命中这类"整棵目录树"兜底模式时，解析结果同样不可信
_GENERIC_FC_PATTERNS = frozenset({"/.*", ".*", "/etc/.*", "/var/.*", "/usr/.*"})


def _fc_resolution_trust(path: str, expected: Dict[str, Any], source: str) -> Dict[str, Any]:
    """判定"默认类型"解析结果能否作为改标签建议的可信目标。

    返回 {trust: high|low, is_generic: bool, reason: str}。

    trust=high 只有一个来源：目标机上的 matchpathcon（反映已加载策略的真实 .fc）。
    知识库（refpolicy 源码）解析一律 low —— 它可能与目标机实际策略不一致，
    必须提示人工用 matchpathcon 复核后才能落地。
    """
    etype = str((expected or {}).get("expected_type") or "")
    pattern = str((expected or {}).get("pattern") or "")
    if not etype:
        return {"trust": "low", "is_generic": False,
                "reason": "默认类型未解析，无法确定改标签目标"}
    is_generic = etype in GENERIC_FC_TYPES or pattern in _GENERIC_FC_PATTERNS
    if is_generic:
        return {"trust": "low", "is_generic": True,
                "reason": ("默认类型解析成泛型/兜底类型 %s（模式 %s）。敏感或专门客体应有"
                           "专门类型，这通常是本机 file_contexts 知识库不全所致；据此改标签"
                           "可能把客体改宽而非收窄，需在目标机上用 matchpathcon %s 复核"
                           % (etype, pattern or "-", path))}
    if source != "matchpathcon":
        return {"trust": "low", "is_generic": False,
                "reason": ("默认类型 %s 来自 %s 而非目标机 matchpathcon，可能与目标机已加载"
                           "策略不一致，落地前须用 matchpathcon 复核" % (etype, source))}
    return {"trust": "high", "is_generic": False, "reason": ""}


def _literal_prefix_len(pattern: str) -> int:
    """模式里第一个正则元字符之前的字面量长度。

    matchpathcon 的选择依据是最长字面前缀，而不是模式串长度：
    ``/var/spool/cron``(字面 15) 必须胜过 ``/var/spool(/.*)?``(字面 10)，
    否则 /var/spool/cron 会被错误解析成 var_spool_t 而不是 cron_spool_t。
    """
    m = _REGEX_META.search(pattern)
    return m.start() if m else len(pattern)


def _kb_file_contexts() -> List[Tuple[int, Any, Dict[str, Any]]]:
    """refpolicy file_contexts 规则表，按字面前缀长度降序，进程内缓存。"""
    key = "kb_file_contexts"
    if key in _CACHE:
        return _CACHE[key]
    rows = _kb_query(
        "SELECT pattern, ftype, context_type, module, source, path, line FROM file_contexts "
        "WHERE pattern IS NOT NULL AND pattern != '' LIMIT ?",
        (),
        limit=20000,
    )
    entries: List[Tuple[int, Any, Dict[str, Any]]] = []
    for row in rows:
        raw = str(row["pattern"] or "")
        context_type = str(row["context_type"] or "")
        # 没有类型的行（解析残缺）与 m4 条件片段都不能用于匹配
        if not context_type or _FC_JUNK.search(raw):
            continue
        pattern = raw
        for macro, replacement in _FC_MACROS:
            pattern = pattern.replace(macro, replacement)
        try:
            regex: Any = re.compile(pattern)
        except re.error:
            continue
        entries.append((
            _literal_prefix_len(pattern),
            regex,
            {
                "pattern": pattern,
                "raw_pattern": raw,
                "ftype": str(row["ftype"] or ""),
                "expected_type": context_type,
                "module": str(row["module"] or ""),
                "origin": "%s:%s" % (row["path"], row["line"]),
            },
        ))
    entries.sort(key=lambda item: (item[0], len(item[2]["pattern"])), reverse=True)
    _CACHE[key] = entries
    return entries


def _kb_file_context(path: str) -> Optional[Dict[str, Any]]:
    """在 refpolicy file_contexts 里找与 matchpathcon 同规则的最长字面前缀匹配。"""
    for _, regex, info in _kb_file_contexts():
        try:
            matched = regex.match(path)
        except Exception:
            continue
        if matched and matched.end() == len(path):
            return info
    return None


def path_type(path: str) -> Dict[str, Any]:
    """路径的实际标签（getxattr）与默认标签（matchpathcon）。

    对不存在的路径同样可用——返回的是"若在此创建，会被打上什么标签"。
    """
    err = _check_path(path)
    if err:
        return {"available": False, "path": path, "error": err}

    exists = os.path.exists(path)
    actual: Optional[Dict[str, str]] = None
    actual_err = ""
    getxattr = getattr(os, "getxattr", None)
    if exists and getxattr is not None:
        try:
            raw = getxattr(path, "security.selinux")
            actual = _split_label(raw.decode("utf-8", "replace").rstrip("\x00"))
        except (OSError, AttributeError, ValueError) as exc:
            actual_err = str(exc)
            ls = _run(["ls", "-dZ", "--", path], timeout=5)
            if ls["rc"] == 0:
                for token in ls["out"].split():
                    if token.count(":") >= 3:
                        actual = _split_label(token)
                        break

    expected: Optional[Dict[str, Any]] = None
    source = "none"
    missing: List[str] = []

    if _which("matchpathcon"):
        mp = _run(["matchpathcon", "--", path], timeout=10)
        out = mp["out"].strip()
        if mp["rc"] == 0 and out:
            tokens = out.split()
            label = tokens[-1] if len(tokens) >= 2 else ""
            split = _split_label(label)
            if split:
                expected = {"expected_type": split["type"], "label": label}
                source = "matchpathcon"
        elif mp["rc"] != 0:
            missing.append("matchpathcon")
    else:
        missing.append("matchpathcon")

    if expected is None:
        kb_hit = _kb_file_context(path)
        if kb_hit:
            expected = kb_hit
            source = "kb_file_contexts(refpolicy 源码)"

    result: Dict[str, Any] = {
        "available": expected is not None or actual is not None,
        "path": path,
        "exists": exists,
        "actual_label": actual,
        "actual_label_error": actual_err,
        "expected_type": (expected or {}).get("expected_type", ""),
        "expected_source": source,
        "tool_missing": missing,
    }
    if expected and "pattern" in expected:
        result["kb_pattern"] = expected["pattern"]
        result["kb_ftype"] = expected.get("ftype", "")
        result["kb_module"] = expected.get("module", "")
        result["kb_origin"] = expected.get("origin", "")
        if expected["pattern"] in ("/.*", ".*") or expected["expected_type"] == "default_t":
            result["confidence"] = "low"
            result["kb_note"] = (
                "仅命中兜底模式 /.*（default_t）。可能是该路径确实没有专门标签，"
                "也可能是本机知识库不全（例如 /root/.ssh 在 refpolicy 里由 HOME_ROOT 宏描述）。"
                "不能仅凭这个结果写 allow 规则，需在目标机上用 matchpathcon 复核。"
            )
    # 改标签建议的可信度门槛：只有 matchpathcon 解析出的专门类型才算 high，
    # 泛型/兜底类型或纯知识库解析一律 low，RELABEL_OBJECT 据此决定是否弃权
    trust = _fc_resolution_trust(path, expected or {}, source)
    result["expected_trust"] = trust["trust"]
    result["expected_is_generic"] = trust["is_generic"]
    if trust["reason"]:
        result["expected_trust_reason"] = trust["reason"]
        if result.get("confidence") != "low" and trust["trust"] == "low":
            result["confidence"] = "low"
    if expected is None and missing:
        result.update(_unavailable("matchpathcon", "无法确定 %s 的默认标签" % path))
    if actual and expected and actual.get("type") != expected.get("expected_type"):
        result["label_mismatch"] = True
        if trust["trust"] == "high" and not trust["is_generic"]:
            result["mismatch_note"] = (
                "实际标签 %s 与默认标签 %s 不一致，且默认标签来自 matchpathcon（可信）。"
                "这是标签收敛候选：可判 RELABEL_OBJECT，把客体从 %s 重打回默认类型 %s。"
                % (actual.get("type"), expected.get("expected_type"),
                   actual.get("type"), expected.get("expected_type"))
            )
        else:
            result["mismatch_note"] = (
                "实际标签 %s 与默认标签 %s 不一致，但默认标签解析不可信（%s）。"
                "不得据此产出改标签建议，应判 NO_CHANGE(LABEL_MISMATCH)，"
                "并提示在目标机上用 matchpathcon 复核。"
                % (actual.get("type"), expected.get("expected_type"),
                   trust["reason"] or "解析置信度低")
            )
    return result


# ──────────────────────────── type_info ────────────────────────────


def _seinfo(flag: str, name: str, expand: bool = False) -> Optional[List[str]]:
    """执行 seinfo 查询。命令不可用返回 None，可用时返回解析出的名字列表。"""
    if not _which("seinfo"):
        return None
    argv = ["seinfo", flag, name]
    if expand:
        argv.append("-x")
    res = _run(argv, timeout=DEFAULT_TIMEOUT)
    if res["rc"] != 0:
        return []
    return [tok for tok in res["out"].split() if _IDENT_RE.match(tok)]


def type_info(name: str) -> Dict[str, Any]:
    """类型或属性是否存在、是类型还是属性、（属性）展开成哪些类型。

    区分两个层次：
      in_loaded_policy  本机已加载策略里确实有这个名字（规则能通过 require 引用）
      in_refpolicy      refpolicy 源码词汇表里有，但本机可能没编译进策略

    存在性判定是防幻觉的关键：LLM 写出的类型名两边都查不到，
    几乎可以确定是编造的，必须拒绝该建议；只在源码里有、本机没加载，
    同样不能写进 .te（require 块会编译失败）。
    """
    if not _is_valid_ident(name):
        return {"available": False, "name": name, "error": "非法的类型/属性名"}

    host_types = _seinfo("-t", name)
    host_attrs = _seinfo("-a", name)
    seinfo_ok = host_types is not None or host_attrs is not None

    kind = "unknown"
    expanded: List[str] = []
    in_loaded = None
    if seinfo_ok:
        if host_attrs:
            kind, in_loaded = "attribute", True
            expanded = [m for m in (_seinfo("-a", name, expand=True) or []) if m != name]
        elif host_types:
            kind, in_loaded = "type", True
        else:
            kind, in_loaded = "none", False

    kb_rows = _kb_query(
        "SELECT kind, module, source, path, line FROM symbols "
        "WHERE name = ? AND kind IN ('type','attribute') ORDER BY module LIMIT ?",
        (name,),
        limit=10,
    )
    kb_kinds = sorted({str(r["kind"]) for r in kb_rows})
    kb_modules = sorted({str(r["module"]) for r in kb_rows if r["module"]})
    in_refpolicy = bool(kb_kinds)

    if kind in ("none", "unknown") and in_refpolicy:
        kind = kb_kinds[0]

    result: Dict[str, Any] = {
        "available": seinfo_ok or in_refpolicy,
        "name": name,
        "kind": kind,
        "in_loaded_policy": in_loaded,
        "in_refpolicy": in_refpolicy,
        "seinfo_available": seinfo_ok,
        "expanded_count": len(expanded),
        "expanded_types": expanded[:MAX_TYPES],
        "kb_modules": kb_modules[:10],
    }
    if not seinfo_ok:
        result["tool_missing"] = ["seinfo"]
        result["hint"] = _TOOL_HINTS["seinfo"]

    if in_loaded is False and in_refpolicy:
        result["verdict_note"] = (
            "%s 存在于 refpolicy 源码（模块 %s），但本机已加载策略中没有它。"
            "写进 .te 的 require 块会导致编译失败，应拒绝该建议或标注为 unknown。"
            % (name, ", ".join(kb_modules[:3]) or "?")
        )
    elif in_loaded is False:
        result["verdict_note"] = (
            "%s 在本机策略与 refpolicy 词汇表中均不存在，"
            "若出现在建议规则里应判定为幻觉类型名并拒绝。" % name
        )
    elif in_loaded is None and in_refpolicy:
        result["verdict_note"] = (
            "本机缺少 seinfo，无法确认 %s 是否已加载到当前策略；"
            "只能确认 refpolicy 源码里存在（模块 %s）。此结果不足以支撑 allow 规则建议。"
            % (name, ", ".join(kb_modules[:3]) or "?")
        )
    elif in_loaded is None:
        result["verdict_note"] = (
            "无法确认 %s 是否存在：本机缺少 seinfo，refpolicy 词汇表里也没有这个名字。"
            "高度可疑（可能是幻觉类型名），不得用于任何建议规则。" % name
        )
    return result


# ──────────────────────────── allow_search ────────────────────────────


_RULE_KINDS = (
    "allow", "auditallow", "dontaudit", "neverallow",
    "type_transition", "type_change", "type_member", "range_transition",
)
# 只有这几类规则有权限集；transition 类的第三项是默认类型，不是 perm
_ACCESS_KINDS = frozenset({"allow", "auditallow", "dontaudit", "neverallow"})

# 尾部条件写法因 setools 版本而异：`( cond )` / `[ bool ]:True`。
# 统一收进 rest，避免因为条件格式不认识而把整条规则丢掉
_RULE_RE = re.compile(
    r"^(?P<kind>%s)\s+"
    r"(?P<src>\S+)\s+(?P<tgt>\S+)\s*:\s*(?P<tclass>\S+)\s*"
    r"(?P<body>\{\s*[^}]*\s*\}|[A-Za-z_][A-Za-z0-9_]*)?\s*;\s*(?P<rest>.*)$"
    % "|".join(_RULE_KINDS)
)
_LEADING_COND_RE = re.compile(r"^\(\s*(?P<cond>[^)]*?)\s*\)\s*")


def _parse_sesearch_line(line: str) -> Optional[Dict[str, Any]]:
    """解析一条 sesearch 输出；无法解析时返回 None（调用方必须统计这些行）。"""
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    cond = ""
    lead = _LEADING_COND_RE.match(text)
    if lead:
        cond = lead.group("cond")
        text = text[lead.end():]
    m = _RULE_RE.match(text)
    if not m:
        return None

    body = (m.group("body") or "").strip()
    if body.startswith("{"):
        perms = [p for p in body.strip("{}").split() if p]
    elif body:
        perms = [body]
    else:
        perms = []

    kind = m.group("kind")
    rule: Dict[str, Any] = {
        "rule_type": kind,
        "src": m.group("src"),
        "tgt": m.group("tgt"),
        "tclass": m.group("tclass"),
    }
    if kind in _ACCESS_KINDS:
        rule["perms"] = perms
    elif perms:
        # type_transition / type_member / type_change 的 body 是默认类型而不是权限，
        # 留一个空 perms 会被读成「这条规则不授予任何权限」，因此干脆不给这个键
        rule["default"] = perms[0]

    tail = (m.group("rest") or "").strip()
    cond = " ".join(part for part in (cond, tail) if part).strip()
    if cond:
        rule["cond"] = cond
    return rule


def _kb_allow_search(src: str, tgt: str, tclass: str, perms: List[str]) -> List[Dict[str, Any]]:
    """refpolicy 源码里的 allow 规则兜底。

    注意两点局限，调用方必须在结论里保留它们：
      1. 权限是宏（read_file_perms）而非展开值，无法直接比对具体 perm
      2. 模板规则带 $1 占位，未实例化，不代表本机策略真有这条
    """
    clauses = ["rule_type = 'allow'"]
    params: List[Any] = []
    if src:
        clauses.append("src = ?")
        params.append(src)
    if tgt:
        clauses.append("tgt = ?")
        params.append(tgt)
    if tclass:
        clauses.append("tclass = ?")
        params.append(tclass)
    rows = _kb_query(
        "SELECT rule_type, src, tgt, tclass, perms, cond, module, path, line FROM access_rules "
        "WHERE %s ORDER BY module, path, line LIMIT ?" % " AND ".join(clauses),
        params,
        limit=300,
    )
    out: List[Dict[str, Any]] = []
    for row in rows:
        rule_perms = [p for p in str(row["perms"] or "").split() if p]
        # 宏形式的权限无法与具体 perm 比对，只有源码里写死字面量时才做权限过滤
        literal = [p for p in rule_perms if not p.endswith("_perms")]
        if perms and literal and not any(p in literal for p in perms):
            continue
        out.append({
            "rule_type": "allow",
            "src": str(row["src"] or ""),
            "tgt": str(row["tgt"] or ""),
            "tclass": str(row["tclass"] or ""),
            "perms": rule_perms,
            "cond": str(row["cond"] or ""),
            "module": str(row["module"] or ""),
            "origin": "%s:%s" % (row["path"], row["line"]),
            "macro_perms": bool(rule_perms) and not literal,
        })
    return out


def allow_search(src: str = "", tgt: str = "", tclass: str = "",
                 perms: Optional[List[str]] = None, limit: int = MAX_RULES) -> Dict[str, Any]:
    """按四元组反查已存在的 allow 规则。

    至少要给出 src/tgt/tclass 中的一项，否则会退化为全表扫描——这里直接拒绝。
    """
    perms = [str(p) for p in (perms or []) if str(p).strip()]
    src = str(src or "").strip()
    tgt = str(tgt or "").strip()
    tclass = str(tclass or "").strip()

    if not (src or tgt or tclass):
        return {"available": False, "error": "至少需要提供 src / tgt / tclass 中的一项"}
    for name in (src, tgt):
        if name and name != "self" and not _is_valid_ident(name):
            return {"available": False, "error": "非法的类型名：%s" % name}
    if tclass and tclass not in _VALID_CLASSES:
        return {
            "available": False,
            "error": "未知对象类 %s（不在支持列表内）" % tclass,
            "valid_classes": sorted(_VALID_CLASSES),
        }
    for perm in perms:
        if not _IDENT_RE.match(perm):
            return {"available": False, "error": "非法权限名：%s" % perm}

    query = {"src": src, "tgt": tgt, "tclass": tclass, "perms": perms}
    detail = ""

    if _which("sesearch"):
        argv = ["sesearch", "--allow"]
        if src:
            argv += ["-s", src]
        if tgt:
            argv += ["-t", tgt]
        if tclass:
            argv += ["-c", tclass]
        if perms:
            argv += ["-p", ",".join(perms)]
        policy = _policy_file()
        if policy:
            argv.append(policy)
        res = _run(argv, timeout=30)
        if res["rc"] == 0:
            rules: List[Dict[str, Any]] = []
            unparsed: List[str] = []
            for line in res["out"].splitlines():
                text = line.strip()
                if not text or text.startswith("#"):
                    continue
                rule = _parse_sesearch_line(text)
                if rule:
                    rules.append(rule)
                else:
                    unparsed.append(text)
            # 一条都没解析出来时必须报"不可用"，否则会被误读成"策略里没有这条规则"
            if unparsed and not rules:
                return {
                    "available": False, "query": query, "matched_count": 0, "rules": [],
                    "error": "sesearch 输出无法解析（样本：%s）" % unparsed[0][:120],
                    "note": "解析失败 ≠ 没有规则，不能据此判定策略缺口。",
                }
            return {
                "available": True,
                "query": query,
                "source": "sesearch(本机已加载策略)",
                "policy_file": policy or "",
                "matched_count": len(rules),
                "rules": rules[:limit],
                "truncated": len(rules) > limit,
                "unparsed_count": len(unparsed),
                "unparsed_sample": unparsed[0][:120] if unparsed else "",
            }
        detail = (res["err"] or res["out"] or "rc=%s" % res["rc"]).strip()[:200]

    kb_rules = _kb_allow_search(src, tgt, tclass, perms)
    if kb_rules:
        return {
            "available": True,
            "query": query,
            "source": "kb_access_rules(refpolicy 源码)",
            "matched_count": len(kb_rules),
            "rules": kb_rules[:limit],
            "truncated": len(kb_rules) > limit,
            "caveat": (
                "结果来自 refpolicy 源码而非本机已加载策略：权限多为宏（read_file_perms）、"
                "模板规则带 $1 未实例化。只能作为写法参考，不能证明本机策略是否放行。"
            ),
            "sesearch_error": detail,
        }

    result: Dict[str, Any] = {"available": False, "query": query, "matched_count": 0, "rules": []}
    if _which("sesearch"):
        result["error"] = "sesearch 执行失败：%s" % (detail or "未知错误")
    else:
        result.update(_unavailable("sesearch", "本机没有 sesearch，且 refpolicy 知识库无匹配"))
    result["note"] = (
        "查询不可用 ≠ 规则不存在。不能据此判定策略缺口；"
        "请在装有 setools-console 的目标机上重新查询，否则只能标注为 unknown。"
    )
    return result


# ──────────────────────────── port_type ────────────────────────────


def _parse_port_spec(spec: str) -> Optional[Tuple[int, int]]:
    """解析 "80" 或 "10001-10010" 为 (lo, hi)。"""
    text = spec.strip()
    if not text:
        return None
    if "-" in text:
        low, _, high = text.partition("-")
        try:
            lo, hi = int(low), int(high)
        except ValueError:
            return None
        return (lo, hi) if 0 < lo <= hi < 65536 else None
    if text.isdigit():
        value = int(text)
        return (value, value) if 0 < value < 65536 else None
    return None


def _semanage_port_table() -> Optional[List[Tuple[str, str, List[Tuple[int, int]]]]]:
    """解析 `semanage port -l`，返回 [(type, proto, [(lo, hi), ...]), ...]。

    不展开端口区间：1024-65535 这类范围展开会瞬间产生几万个键。
    """
    if "port_table" in _CACHE:
        return _CACHE["port_table"]
    table: Optional[List[Tuple[str, str, List[Tuple[int, int]]]]] = None
    if _which("semanage"):
        res = _run(["semanage", "port", "-l"], timeout=DEFAULT_TIMEOUT)
        if res["rc"] == 0 and res["out"].strip():
            table = []
            for line in res["out"].splitlines():
                parts = line.split()
                if len(parts) < 3 or parts[1] not in ("tcp", "udp"):
                    continue
                ranges = [r for r in (_parse_port_spec(t) for t in ",".join(parts[2:]).split(",")) if r]
                if ranges:
                    table.append((parts[0], parts[1], ranges))
    _CACHE["port_table"] = table
    return table


def port_type(port: Any, proto: str = "tcp") -> Dict[str, Any]:
    """端口对应的 SELinux 端口类型（如 443/tcp -> https_port_t）。"""
    try:
        port_num = int(port)
    except (TypeError, ValueError):
        return {"available": False, "port": port, "error": "port 必须是整数"}
    if not 0 < port_num < 65536:
        return {"available": False, "port": port, "error": "port 超出范围"}
    proto = str(proto or "tcp").strip().lower()
    if proto not in ("tcp", "udp"):
        return {"available": False, "port": port, "error": "proto 只能是 tcp 或 udp"}

    table = _semanage_port_table()
    if table is None:
        result: Dict[str, Any] = {"available": False, "port": port_num, "proto": proto,
                                  "port_type": "", "matches": []}
        result.update(_unavailable("semanage", "无法列出端口标签"))
        return result

    matches = [
        "%s/%s" % (name, p)
        for name, p, ranges in table
        if p == proto and any(lo <= port_num <= hi for lo, hi in ranges)
    ]
    type_name = matches[0].rsplit("/", 1)[0] if matches else ""

    return {
        "available": True,
        "port": port_num,
        "proto": proto,
        "port_type": type_name,
        "matches": matches[:MAX_TYPES],
        "note": "" if type_name else (
            "该端口没有显式标签，通常落在未保留端口范围内，需要人工确认后才能写进规则"
        ),
    }


# ──────────────────────────── probe_access ────────────────────────────


_UNCONFINED_HINTS = ("unconfined", "spc_t", "kernel_t")


def probe_access(src: str, resource: str, tclass: str,
                 perms: Optional[List[str]] = None, port: Any = None) -> Dict[str, Any]:
    """组合探针：解析客体类型后反查 allow 规则，给出"是否已放行"的结论。

    verdict 取值：
      allowed         已存在无条件规则且覆盖全部权限
      conditional     已存在规则但受布尔开关控制，只在开关打开时生效
      partial         已存在规则但权限不全（此时才可能需要 MODIFY_ALLOW）
      no_rule         查得到策略但没有任何匹配规则（可能需要 ADD_ALLOW）
      unknown         工具缺失、客体类型无法解析或权限是宏（不得据此建议任何规则）
    """
    perms = [str(p) for p in (perms or []) if str(p).strip()]
    tclass = str(tclass or "").strip()
    base: Dict[str, Any] = {
        "src": src, "resource": resource, "tclass": tclass, "perms": perms,
        "available": False, "verdict": "unknown",
    }
    if not _is_valid_ident(src):
        return dict(base, error="非法的源类型名：%s" % src)
    if not resource:
        return dict(base, error="resource 不能为空")
    if tclass not in _VALID_CLASSES:
        return dict(base, error="未知对象类 %s" % (tclass or "(空)"),
                    valid_classes=sorted(_VALID_CLASSES))

    notes: List[str] = []
    if any(h in src for h in _UNCONFINED_HINTS):
        notes.append(
            "源类型 %s 属于不受限域（unconfined/spc/kernel 一类）：内核不对其做强制，"
            "为它编写 allow 规则没有实际约束效果。正确处理是判定 NO_CHANGE，"
            "并在说明中指出应当迁移到受限域（超出本模块范围）。" % src
        )

    tgt_type = ""
    target_confidence = "high"
    target_info: Dict[str, Any] = {}
    if tclass in ("tcp_socket", "udp_socket", "rawip_socket", "node", "port"):
        if port is None:
            parsed = re.search(r":(\d+)$", str(resource))
            port = parsed.group(1) if parsed else None
        if port is None:
            target_confidence = "none"
            notes.append("无法从 %s 解析端口号，客体类型未知" % resource)
        else:
            target_info = port_type(port, "udp" if tclass == "udp_socket" else "tcp")
            tgt_type = str(target_info.get("port_type") or "")
            if not tgt_type:
                target_confidence = "none"
    else:
        target_info = path_type(str(resource))
        actual = target_info.get("actual_label")
        if isinstance(actual, dict) and actual.get("type"):
            # 文件已存在时以实际标签为准，matchpathcon 只反映默认规则
            tgt_type = str(actual["type"])
        else:
            tgt_type = str(target_info.get("expected_type") or "")
        if not tgt_type:
            target_confidence = "none"
        elif target_info.get("confidence") == "low":
            target_confidence = "low"
            notes.append(target_info.get("kb_note") or "客体类型置信度低，不足以支撑 allow 规则")

    if not tgt_type:
        return dict(base, target_resolution=target_info, target_confidence="none",
                    notes=notes + ["客体类型无法解析，不能据此判断策略是否缺失"])

    search = allow_search(src=src, tgt=tgt_type, tclass=tclass, perms=perms or None)
    if not search.get("available"):
        return dict(base, resolved_target_type=tgt_type, target_resolution=target_info,
                    target_confidence=target_confidence, query=search,
                    notes=notes + [search.get("note") or search.get("error") or "策略查询不可用"])

    # sesearch 会按 -c 过滤，但知识库兜底不会；这里再按对象类过滤一次，
    # 否则别的对象类的规则会污染"是否已放行"的判断
    rules = [r for r in search.get("rules", []) if not tclass or r.get("tclass") == tclass]
    covered: List[str] = []
    for rule in rules:
        for perm in rule.get("perms", []):
            if perm in perms and perm not in covered:
                covered.append(perm)
    missing = [p for p in perms if p not in covered]
    # 宏权限（read_file_perms）无法逐 perm 比对；此时宁可报 unknown 也不能报缺口
    macro_rules = [r for r in rules if any(str(p).endswith("_perms") for p in r.get("perms", []))]
    covering = [r for r in rules if not perms or any(p in perms for p in r.get("perms", []))]
    all_conditional = bool(covering) and all(r.get("cond") for r in covering)

    if not perms:
        verdict = "allowed" if rules else "no_rule"
    elif not missing:
        verdict = "conditional" if all_conditional else "allowed"
    elif covered:
        verdict = "unknown" if macro_rules else "partial"
    elif macro_rules:
        verdict = "unknown"
    else:
        verdict = "no_rule"
    if missing:
        notes.append("未覆盖权限：%s" % ", ".join(missing))
    if macro_rules and missing:
        notes.append(
            "命中的规则使用宏权限（如 read_file_perms），无法逐权限比对，"
            "因此不能判定为缺口——结论只能是 unknown。需在有 setools 的机器上用 sesearch 复核。"
        )
    if verdict == "conditional":
        notes.append(
            "命中的规则受布尔开关控制（%s），只在开关打开时才生效。"
            "本模块不建议修改 boolean，只把它写进诊断说明。"
            % "; ".join(sorted({r["cond"] for r in covering if r.get("cond")}))[:120]
        )

    if search.get("source", "").startswith("kb_"):
        notes.append(
            "结果来自 refpolicy 源码知识库而非本机已加载策略，"
            "仅可作为写法参考，不能证明本机策略是否放行。"
        )

    return {
        "available": True,
        "verdict": verdict,
        "src": src,
        "resource": resource,
        "tclass": tclass,
        "perms": perms,
        "covered_perms": covered,
        "missing_perms": missing,
        "resolved_target_type": tgt_type,
        "target_confidence": target_confidence,
        "target_resolution": {
            "expected_type": target_info.get("expected_type", ""),
            "expected_source": target_info.get("expected_source", ""),
            "actual_label": target_info.get("actual_label"),
            "label_mismatch": bool(target_info.get("label_mismatch")),
            "expected_trust": target_info.get("expected_trust", ""),
            "expected_is_generic": bool(target_info.get("expected_is_generic")),
            "expected_trust_reason": target_info.get("expected_trust_reason", ""),
        },
        "matched_count": search.get("matched_count", 0),
        "rules": rules[:20],
        "source": search.get("source", ""),
        "notes": notes,
    }


# ──────────────────────────── 文本渲染 ────────────────────────────


def _fmt_rules(rules: List[Dict[str, Any]]) -> List[str]:
    lines = []
    for rule in rules:
        text = "%s %s %s:%s { %s };" % (
            rule.get("rule_type", "allow"), rule.get("src", ""), rule.get("tgt", ""),
            rule.get("tclass", ""), " ".join(rule.get("perms", []) or []),
        )
        if rule.get("cond"):
            text += "  # 条件：%s" % rule["cond"]
        if rule.get("default"):
            text = "%s %s %s:%s %s;" % (
                rule.get("rule_type"), rule.get("src"), rule.get("tgt"),
                rule.get("tclass"), rule["default"])
        if rule.get("origin"):
            text += "  [%s:%s]" % (rule["module"], rule["origin"])
        lines.append("  " + text)
    return lines


def _unavailable_line(result: Dict[str, Any], prefix: str = "") -> str:
    lines = ["%s不可用" % prefix]
    if result.get("error"):
        lines[0] += "：%s" % result["error"]
    elif result.get("missing"):
        lines[0] += "：缺少 %s（%s）" % (result["missing"], result.get("hint", ""))
    for key in ("note", "detail", "sesearch_error"):
        if result.get(key):
            lines.append("  %s" % result[key])
    for note in result.get("notes", []):
        lines.append("  注意：%s" % note)
    return "\n".join(lines)


def _indent(text: str, pad: str = "  ") -> str:
    return "\n".join(pad + line if line.strip() else line for line in text.splitlines())


def _render_posture(r: Dict[str, Any]) -> str:
    if not r.get("available"):
        return _unavailable_line(r, "SELinux 状态查询")
    lines = [
        "SELinux 状态：enabled=%s mode=%s config_mode=%s policy=%s policyvers=%s mls=%s"
        % (r.get("enabled"), r.get("mode"), r.get("config_mode") or "-",
           r.get("policy_name") or "-", r.get("policyvers") or "-", r.get("mls_enabled")),
    ]
    if r.get("policy_file"):
        lines.append("  已加载策略文件：%s" % r["policy_file"])
    if r.get("tool_missing"):
        lines.append("  缺失命令：%s" % ", ".join(r["tool_missing"]))
    lines.extend("  注意：" + n for n in r.get("notes", []))
    return "\n".join(lines)


def _render_path_type(r: Dict[str, Any]) -> str:
    if r.get("error") or not r.get("available"):
        return _unavailable_line(r, "路径标签查询 %s " % r.get("path", ""))
    lines = ["路径 %s（存在=%s）" % (r.get("path"), r.get("exists"))]
    actual = r.get("actual_label") or {}
    if actual:
        lines.append("  实际标签：%s:%s:%s:%s" % (
            actual.get("user"), actual.get("role"), actual.get("type"), actual.get("level")))
    if r.get("actual_label_error"):
        lines.append("  实际标签读取失败：%s" % r["actual_label_error"])
    if r.get("expected_type"):
        lines.append("  默认类型：%s（来源 %s，可信度 %s%s）" % (
            r["expected_type"], r.get("expected_source"),
            r.get("expected_trust", "?"),
            "，泛型/兜底" if r.get("expected_is_generic") else ""))
        if r.get("kb_pattern"):
            lines.append("  匹配 file_contexts 模式：%s [%s:%s]" % (
                r["kb_pattern"], r.get("kb_module", ""), r.get("kb_origin", "")))
    else:
        lines.append("  默认类型：未知（无 matchpathcon，知识库也未命中）")
    if r.get("expected_trust_reason"):
        lines.append("  改标签可信度：" + r["expected_trust_reason"])
    if r.get("kb_note"):
        lines.append("  低置信度：" + r["kb_note"])
    if r.get("mismatch_note"):
        lines.append("  " + r["mismatch_note"])
    return "\n".join(lines)


def _render_type_info(r: Dict[str, Any]) -> str:
    if r.get("error"):
        return _unavailable_line(r, "类型查询 %s " % r.get("name", ""))
    lines = ["%s：kind=%s 已加载到本机策略=%s refpolicy词汇表=%s seinfo可用=%s" % (
        r.get("name"), r.get("kind"), r.get("in_loaded_policy"),
        r.get("in_refpolicy"), r.get("seinfo_available"))]
    if r.get("expanded_count"):
        shown = r.get("expanded_types", [])
        suffix = " …共 %d 个" % r["expanded_count"] if r["expanded_count"] > len(shown) else ""
        lines.append("  展开：%s%s" % (", ".join(shown), suffix))
    if r.get("kb_modules"):
        lines.append("  refpolicy 模块：%s" % ", ".join(r["kb_modules"]))
    if r.get("hint"):
        lines.append("  缺失命令安装：%s" % r["hint"])
    if r.get("verdict_note"):
        lines.append("  " + r["verdict_note"])
    return "\n".join(lines)


def _render_allow_search(r: Dict[str, Any]) -> str:
    if r.get("error") or not r.get("available"):
        return _unavailable_line(r, "allow 规则查询")
    q = r.get("query", {})
    lines = ["allow 规则查询 src=%s tgt=%s class=%s perms=%s → 命中 %d 条（来源 %s）" % (
        q.get("src") or "-", q.get("tgt") or "-", q.get("tclass") or "-",
        ",".join(q.get("perms") or []) or "-", r.get("matched_count", 0), r.get("source", "-"))]
    if not r.get("matched_count"):
        lines.append("  本机已加载策略中没有匹配规则")
    lines.extend(_fmt_rules(r.get("rules", [])))
    if r.get("truncated"):
        lines.append("  （结果已截断，仅显示前 %d 条）" % MAX_RULES)
    if r.get("unparsed_count"):
        lines.append("  （另有 %d 行无法解析，样本：%s）" % (r["unparsed_count"], r.get("unparsed_sample", "")))
    if r.get("caveat"):
        lines.append("  注意：%s" % r["caveat"])
    return "\n".join(lines)


def _render_port_type(r: Dict[str, Any]) -> str:
    if r.get("error") or not r.get("available"):
        return _unavailable_line(r, "端口类型查询 %s/%s " % (r.get("port"), r.get("proto")))
    lines = ["端口 %s/%s → %s" % (
        r.get("port"), r.get("proto"), r.get("port_type") or "(无显式标签)")]
    if r.get("note"):
        lines.append("  " + r["note"])
    return "\n".join(lines)


def _render_probe_access(r: Dict[str, Any]) -> str:
    lines = ["访问探测 %s → %s（%s）：verdict=%s" % (
        r.get("src", ""), r.get("resource", ""), r.get("tclass", ""),
        r.get("verdict") or "unknown")]
    if not r.get("available"):
        lines.append(_indent(_unavailable_line(r)))
        if r.get("resolved_target_type"):
            lines.append("  客体类型：%s" % r["resolved_target_type"])
        return "\n".join(lines)
    lines.append("  客体类型：%s" % (r.get("resolved_target_type") or "未解析"))
    if r.get("target_confidence") and r["target_confidence"] != "high":
        lines.append("  客体类型置信度：%s" % r["target_confidence"])
    if r.get("perms"):
        lines.append("  需要权限：%s" % ", ".join(r["perms"]))
        if r.get("covered_perms"):
            lines.append("  已覆盖：%s" % ", ".join(r["covered_perms"]))
        if r.get("missing_perms"):
            lines.append("  未覆盖：%s" % ", ".join(r["missing_perms"]))
    lines.append("  命中规则 %d 条（来源 %s）" % (r.get("matched_count", 0), r.get("source", "-")))
    lines.extend(_fmt_rules(r.get("rules", [])[:10]))
    lines.extend("  注意：" + n for n in r.get("notes", []))
    return "\n".join(lines)


_RENDERERS = {
    "posture": _render_posture,
    "path_type": _render_path_type,
    "type_info": _render_type_info,
    "allow_search": _render_allow_search,
    "port_type": _render_port_type,
    "probe_access": _render_probe_access,
}


def render(name: str, result: Dict[str, Any]) -> str:
    """把查询结果渲染成给 LLM 阅读的紧凑文本；不可用时也要说清"为什么查不到"。"""
    if not isinstance(result, dict):
        return str(result)
    renderer = _RENDERERS.get(name)
    if renderer is None:
        return str(result)
    return renderer(result)
