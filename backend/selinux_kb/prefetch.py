# -*- coding: utf-8 -*-
"""回答前自动检索 SELinux 知识（确定性预取）。

动机：7B 级模型不一定会主动调用检索工具。为了确保「回答前一定参考了 SELinux 知识」，
由后端在发起模型请求之前主动检索一次，把结果直接拼进上下文——
即使模型从不调用 search_selinux_knowledge，也能拿到可引用的依据。

两个入口共用同一套逻辑：
  * 技能分析（xy_skill.run_skill_analysis）  → block_for_round(row)
  * 普通对话（app.monitor_anomaly_llm_chat） → block_for_text(用户问题)

开关（config 表，缺省视为开启）：
  monitor_conf.selinux_kb_enable      总开关
  monitor_conf.selinux_kb_prefetch    是否启用自动预取
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

try:
    from . import search as kb_search
except ImportError:  # 以顶层模块方式导入
    try:
        import search as kb_search
    except ImportError:  # pragma: no cover - 索引模块缺失时降级为不可用
        kb_search = None

# 强制附加到技能分析系统提示词末尾的约束（用户自定义提示词时依然生效）
DIRECTIVE = (
    "【SELinux 依据要求】\n"
    "分析中凡涉及 SELinux 标签、类型、布尔值或策略建议，"
    "必须以「SELinux 知识参考」段落或 search_selinux_knowledge 工具返回的内容为依据；"
    "禁止凭记忆编造类型名、布尔名、接口名或 allow 规则。"
    "信息不足时应先调用 search_selinux_knowledge 检索，仍查不到就明确说明无法确认。"
)

_SELINUX_KW_RE = re.compile(
    r"selinux|avc|dontaudit|audit2allow|audit2why|restorecon|semanage|setsebool|getsebool|"
    r"sepolicy|sesearch|seinfo|checkmodule|semodule|chcon|setfiles|enforcing|permissive|"
    r"unconfined|type enforcement|security context|policy module|"
    r"安全上下文|标签|策略|拒绝|提权|强制访问|域转换|类型强制|布尔值",
    re.I,
)
_LABEL_RE = re.compile(r"\b[a-z_]+_u:[a-z_]+_r:[a-z_]+_t\b")
_TYPE_RE = re.compile(r"\b[a-z][a-z0-9_]*_(?:t|exec_t|type|attr)\b")
_PATH_RE = re.compile(r"(?<![\w.])/(?:[A-Za-z0-9._*\-]+/?){1,12}")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.\-]{3,}")

# 语料是英文的，中文提问直接检索命中率很低，先把高频中文术语映射成英文
_ZH_EN = {
    "安全上下文": "security context",
    "上下文": "security context",
    "标签": "label",
    "策略": "policy",
    "拒绝": "denied avc",
    "提权": "privilege escalation",
    "强制访问": "mandatory access control",
    "域转换": "domain transition",
    "类型强制": "type enforcement",
    "布尔值": "boolean",
    "布尔": "boolean",
    "规则": "rule",
    "文件上下文": "file context",
    "接口": "interface",
    "排错": "troubleshooting",
    "排查": "troubleshooting",
}

# 这些词过于宽泛，单独作为检索词价值不大
_LOW_VALUE_WORDS = {"selinux", "avc", "policy", "rule", "type", "label", "allow"}

_MAX_QUERY_TERMS = 12
_CACHE: Dict[str, str] = {}
_CACHE_LIMIT = 64


def _cfg(key: str, default: str = "") -> str:
    """惰性读取 config 表；db 不可用时返回默认值（不抛错）。"""
    try:
        import db
        return (db.get_config(key) or default)
    except Exception:
        return default


def _enabled() -> bool:
    return _cfg("monitor_conf.selinux_kb_enable", "true").strip().lower() != "false"


def _prefetch_enabled() -> bool:
    return _cfg("monitor_conf.selinux_kb_prefetch", "true").strip().lower() != "false"


# ────────────────────────────── 线索抽取 ──────────────────────────────


def _uniq(items: List[str], limit: int) -> List[str]:
    out: List[str] = []
    for it in items:
        if it and it not in out:
            out.append(it)
        if len(out) >= limit:
            break
    return out


def looks_selinux_related(text: str) -> bool:
    """判断一段文本是否值得触发 SELinux 知识预取。"""
    if not text:
        return False
    if _SELINUX_KW_RE.search(text):
        return True
    if _LABEL_RE.search(text) or _TYPE_RE.search(text):
        return True
    return False


def query_from_text(text: str) -> str:
    """把用户问题转成检索关键词：标签/类型 > 路径 > 术语映射 > 英文技术词。"""
    text = text or ""
    types = _LABEL_RE.findall(text) + _TYPE_RE.findall(text)
    paths = _PATH_RE.findall(text)
    mapped = [en for zh, en in _ZH_EN.items() if zh in text]
    words = [w for w in _WORD_RE.findall(text) if w.lower() not in _LOW_VALUE_WORDS]
    terms = _uniq(types + paths + mapped + words, _MAX_QUERY_TERMS)
    return " ".join(terms)


def _extract_types_from_json(raw: str) -> List[str]:
    """从 pid_info 之类的 JSON 文本里抽取 SELinux 类型（含 u:r:t 完整标签）。"""
    if not raw:
        return []
    found: List[str] = []
    for label in _LABEL_RE.findall(raw):
        parts = label.split(":")
        if len(parts) >= 3:
            found.append(parts[2])
    found += _TYPE_RE.findall(raw)
    found = _uniq(found, 8)
    # unconfined_t 这类通用域信息量极低：只要还有别的类型就不要它
    specific = [t for t in found if not t.startswith("unconfined")]
    if specific:
        return specific[:4]
    return found[:2]


def _clues_from_round(row: Dict[str, Any]):
    """从 Round 数据里分别抽取 (类型, 路径, 其他关键词)。"""
    row = row or {}
    types = _extract_types_from_json(str(row.get("pid_info") or ""))
    paths = _uniq(
        _PATH_RE.findall(str(row.get("action_json") or ""))
        + _PATH_RE.findall(str(row.get("ir_json") or "")),
        4,
    )
    user_query = str(row.get("user_query") or "")
    extras = query_from_text(user_query).split()
    return types, paths, extras


def query_from_round(row: Dict[str, Any]) -> str:
    """把 Round 线索拼成单条查询（用于日志排查与降级路径）。"""
    types, paths, extras = _clues_from_round(row)
    return " ".join(_uniq(types + paths + extras, _MAX_QUERY_TERMS))


# ────────────────────────────── 渲染与入口 ──────────────────────────────


def _render(kb_text: str) -> str:
    return (
        "【SELinux 知识参考 · 后端已自动检索】\n"
        + kb_text
        + "\n\n说明：以上是依据库检索结果，可直接在结论中引用（含 文件:行号）。"
        "若不足以支撑判断，请调用 search_selinux_knowledge 工具补充检索；"
        "不得编造未出现的类型名、布尔名或规则。"
    )


def _search_cached(query: str, k: int, kind: str = "all") -> Optional[str]:
    if kb_search is None or not query.strip():
        return None
    key = "%s|%s|%s" % (kind, k, query)
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    try:
        text = kb_search.search(query, kind=kind, k=k)
    except Exception:
        return None
    if len(_CACHE) >= _CACHE_LIMIT:
        _CACHE.clear()
    _CACHE[key] = text
    return text


def block_for_text(text: str, k: int = 4) -> str:
    """普通对话入口：问题与 SELinux 相关时返回知识参考段落，否则返回空串。"""
    if not _enabled() or not _prefetch_enabled():
        return ""
    if not looks_selinux_related(text):
        return ""
    query = query_from_text(text)
    if not query:
        return ""
    kb_text = _search_cached(query, k, "all")
    return _render(kb_text) if kb_text else ""


def block_for_round(row: Dict[str, Any], k: int = 5) -> str:
    """技能分析入口：从 Round 数据提取线索并返回知识参考段落。

    分两路检索：路径 → 文件上下文（判断访问目标是否该打这个标签），
    类型 → 规则/符号（判断该域是否有相应权限）。拼成一段注入，控制总长度。
    """
    if not _enabled() or not _prefetch_enabled():
        return ""
    types, paths, extras = _clues_from_round(row)

    sections: List[str] = []
    if paths:
        text = _search_cached(" ".join(paths[:4]), 3, "file_context")
        if text:
            sections.append(text)
    if types:
        text = _search_cached(" ".join(types[:3]), min(k, 4), "all")
        if text:
            sections.append(text)
    elif extras:
        text = _search_cached(" ".join(extras[:6]), min(k, 4), "all")
        if text:
            sections.append(text)

    if not sections:
        return ""
    return _render("\n\n".join(sections))


def extend_skill_prompt(base_prompt: str) -> str:
    """给技能分析的系统提示词追加 SELinux 约束（无论是否用户自定义）。"""
    base = (base_prompt or "").rstrip()
    if DIRECTIVE in base:
        return base
    return (base + "\n\n" + DIRECTIVE).strip()
