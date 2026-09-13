# -*- coding: utf-8 -*-
"""SELinux 知识库检索。

对上层只暴露一个函数::

    search(query, kind="all", module=None, k=5, db_path=None) -> str

返回值是给大模型直接阅读的紧凑文本（含出处引用），不是 JSON。

检索策略：符号精确匹配 + allow 规则匹配 + 文件上下文匹配 + 全文 BM25，
四路结果用 RRF（Reciprocal Rank Fusion）融合后取前 k 条。

设计约束（2GB 内存 Linux 服务器）：
  * 只依赖标准库；每次调用新建只读连接并立即关闭，不持有长连接
  * SQLite 缓存限制在 16MB，mmap 仅用于加速读取
  * 缺 FTS5 时自动降级为 LIKE 逐词检索，功能不中断
"""

from __future__ import annotations

import os
import re
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

MAX_K = 10
MAX_SNIPPET = 320
MAX_TOTAL_CHARS = 2000
RRF_K = 60

# 各检索通道权重：精确的规则/符号命中优先于全文相似度
WEIGHTS = {"rule": 1.25, "symbol": 1.10, "fctx": 1.05, "fts": 1.0}

_TYPE_ID_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*_(?:t|u|r|type|attr|bool)\b")
_IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]+\b")
_PATH_RE = re.compile(r"(?<![\w.])/(?:[A-Za-z0-9._*\-]+/?){1,12}")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_/.\-]{2,}")

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
    "all", "any", "not", "you", "can", "how", "what", "why", "does", "did",
}


# ────────────────────────────── 路径与连接 ──────────────────────────────


def default_db_path() -> str:
    """默认索引位置：clawAVC/infos/selinux_kb/selinux_kb.db（可用环境变量覆盖）。"""
    env = os.environ.get("SELINUX_KB_PATH")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", "infos", "selinux_kb", "selinux_kb.db"))


def _connect(db_path: str) -> sqlite3.Connection:
    if not os.path.isfile(db_path):
        raise FileNotFoundError(db_path)
    uri = "file:%s?mode=ro" % quote(os.path.abspath(db_path))
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=1")
    conn.execute("PRAGMA cache_size=-16000")     # 页缓存上限约 16MB
    conn.execute("PRAGMA mmap_size=268435456")   # 仅建立映射，按需换页
    return conn


def kb_info(db_path: Optional[str] = None) -> Dict[str, str]:
    """读取索引元信息（构建时间、语料规模、是否含 FTS5）。"""
    path = db_path or default_db_path()
    conn = _connect(path)
    try:
        rows = conn.execute("SELECT key, value FROM meta").fetchall()
        info = {r["key"]: r["value"] for r in rows}
        info["db_path"] = path
        info["db_size_mb"] = "%.1f" % (os.path.getsize(path) / 1024.0 / 1024.0)
        return info
    finally:
        conn.close()


def _has_fts(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunks_fts'"
    ).fetchone()
    return row is not None


# ────────────────────────────── 查询解析 ──────────────────────────────


def extract_identifiers(query: str) -> Tuple[List[str], List[str]]:
    """从查询里抽取 (类型类标识符, 任意带下划线标识符)，保序去重。"""
    types: List[str] = []
    idents: List[str] = []
    for m in _TYPE_ID_RE.finditer(query):
        w = m.group(0)
        if w not in types:
            types.append(w)
    for m in _IDENT_RE.finditer(query):
        w = m.group(0)
        if w not in idents:
            idents.append(w)
    return types, idents


def extract_paths(query: str) -> List[str]:
    out: List[str] = []
    for m in _PATH_RE.finditer(query):
        p = m.group(0).rstrip(",.?;:")
        if len(p) >= 3 and p not in out:
            out.append(p)
    return out


def query_tokens(query: str) -> List[str]:
    toks: List[str] = []
    for m in _TOKEN_RE.finditer(query):
        t = m.group(0).strip("-.")
        if len(t) < 2 or t.lower() in _STOPWORDS:
            continue
        if t not in toks:
            toks.append(t)
    return toks


def _fts_match_expr(tokens: Sequence[str]) -> str:
    """把词元安全地拼成 FTS5 MATCH 表达式（逐个加引号，OR 连接）。"""
    parts = []
    for t in tokens[:12]:
        parts.append('"%s"' % t.replace('"', '""'))
    return " OR ".join(parts)


# ────────────────────────────── 分路检索 ──────────────────────────────


def _search_symbols(conn: sqlite3.Connection, idents: List[str],
                    module: Optional[str], limit: int) -> List[Dict[str, Any]]:
    if not idents:
        return []
    hits: List[Dict[str, Any]] = []
    seen = set()
    for ident in idents[:6]:
        sql = ("SELECT id,name,kind,module,source,path,line,summary FROM symbols "
               "WHERE (name = ? COLLATE NOCASE OR name LIKE ?) ")
        params: List[Any] = [ident, ident + "%"]
        if module:
            sql += "AND (module = ? OR module IS NULL) "
            params.append(module)
        sql += "ORDER BY (name = ? COLLATE NOCASE) DESC, LENGTH(name) ASC LIMIT ?"
        params += [ident, limit]
        for r in conn.execute(sql, params):
            key = ("symbol", r["id"])
            if key in seen:
                continue
            seen.add(key)
            hits.append(dict(r))
    return hits


def _search_rules(conn: sqlite3.Connection, idents: List[str],
                  module: Optional[str], limit: int) -> List[Dict[str, Any]]:
    """检索 allow 类规则。命中 "src 与 tgt 同时出现" 的记录会标记 paired=True。"""
    if not idents:
        return []
    hits: List[Dict[str, Any]] = []
    seen = set()
    idents = idents[:6]
    base = ("SELECT id,rule_type,src,tgt,tclass,perms,cond,module,source,path,line "
            "FROM access_rules WHERE ")
    mod_clause = " AND (module = ? OR module IS NULL)" if module else ""

    def _run(sql: str, params: List[Any], paired: bool) -> None:
        for r in conn.execute(sql, params):
            key = ("rule", r["id"])
            if key in seen:
                continue
            seen.add(key)
            rec = dict(r)
            rec["paired"] = paired
            hits.append(rec)

    # 1) 同时出现两个标识符 → 双向查 (src,tgt)
    if len(idents) >= 2:
        for a in idents[:4]:
            for b in idents[:4]:
                if a == b:
                    continue
                params = [a, b] + ([module] if module else []) + [limit]
                _run(base + "src = ? AND tgt = ?" + mod_clause + " LIMIT ?", params, True)
    # 2) 单标识符 → 查它作为主体的规则
    for a in idents[:4]:
        params = [a] + ([module] if module else []) + [limit]
        _run(base + "src = ?" + mod_clause + " LIMIT ?", params, False)
    return hits


def _search_file_contexts(conn: sqlite3.Connection, paths: List[str], idents: List[str],
                          module: Optional[str], limit: int) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    seen = set()
    base = ("SELECT id,pattern,ftype,context_type,module,source,path,line "
            "FROM file_contexts WHERE ")
    mod_clause = " AND (module = ? OR module IS NULL)" if module else ""

    for p in paths[:3]:
        params = ["%" + p + "%"] + ([module] if module else []) + [limit]
        for r in conn.execute(base + "pattern LIKE ?" + mod_clause + " LIMIT ?", params):
            key = ("fctx", r["id"])
            if key in seen:
                continue
            seen.add(key)
            hits.append(dict(r))

    for ident in idents[:4]:
        params = [ident] + ([module] if module else []) + [limit]
        for r in conn.execute(base + "context_type = ?" + mod_clause + " LIMIT ?", params):
            key = ("fctx", r["id"])
            if key in seen:
                continue
            seen.add(key)
            hits.append(dict(r))
    return hits


def _search_fts(conn: sqlite3.Connection, tokens: List[str], module: Optional[str],
                kind_filter: Optional[Sequence[str]], limit: int) -> List[Dict[str, Any]]:
    if not tokens or not _has_fts(conn):
        return []
    where = "chunks_fts MATCH ?"
    params: List[Any] = [_fts_match_expr(tokens)]
    if module:
        where += " AND (c.module = ? OR c.module IS NULL)"
        params.append(module)
    if kind_filter:
        where += " AND c.kind IN (%s)" % ",".join("?" * len(kind_filter))
        params += list(kind_filter)
    params.append(limit)
    sql = ("SELECT c.id,c.kind,c.module,c.source,c.path,c.line,c.title,c.text,"
           "       bm25(chunks_fts) AS score "
           "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
           "WHERE " + where + " ORDER BY score LIMIT ?")
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error:
        return []
    return [dict(r) for r in rows]


def _search_like(conn: sqlite3.Connection, tokens: List[str], module: Optional[str],
                 kind_filter: Optional[Sequence[str]], limit: int) -> List[Dict[str, Any]]:
    """无 FTS5 时的降级检索：先逐词 LIKE 粗筛，再按命中词数重排。"""
    if not tokens:
        return []
    clause = "(title LIKE ? OR text LIKE ?)"
    if module:
        clause += " AND (module = ? OR module IS NULL)"
    if kind_filter:
        clause += " AND kind IN (%s)" % ",".join("?" * len(kind_filter))
    sql = "SELECT id,kind,module,source,path,line,title,text FROM chunks WHERE " + clause + " LIMIT ?"

    candidates: Dict[int, Dict[str, Any]] = {}
    for tok in tokens[:4]:
        pat = "%" + tok + "%"
        params: List[Any] = [pat, pat]
        if module:
            params.append(module)
        if kind_filter:
            params += list(kind_filter)
        params.append(limit * 4)          # 多取候选，便于后面按相关度重排
        for r in conn.execute(sql, params):
            candidates.setdefault(r["id"], dict(r))

    if not candidates:
        return []

    lowered = [t.lower() for t in tokens]
    scored: List[Tuple[int, int, Dict[str, Any]]] = []
    for cid, rec in candidates.items():
        hay = ((rec.get("title") or "") + "\n" + (rec.get("text") or "")).lower()
        title = (rec.get("title") or "").lower()
        score = 0
        for tok in lowered:
            if tok in hay:
                score += 1
            if tok in title:
                score += 2               # 标题命中权重更高
        scored.append((score, -len(hay), rec))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return [rec for _s, _l, rec in scored[:limit]]


# ────────────────────────────── 融合与渲染 ──────────────────────────────


def _key_of(channel: str, hit: Dict[str, Any]) -> Tuple[str, Any]:
    if channel == "symbol":
        return ("symbol", hit["id"])
    if channel == "rule":
        return ("rule", hit["id"])
    if channel == "fctx":
        return ("fctx", hit["id"])
    return ("chunk", hit["id"])


def _fuse(channels: Dict[str, List[Dict[str, Any]]], k: int) -> List[Tuple[float, str, Dict[str, Any]]]:
    """RRF 融合，返回 [(score, key, 记录)]，按分数降序。"""
    scores: Dict[Tuple[str, Any], float] = {}
    store: Dict[Tuple[str, Any], Dict[str, Any]] = {}
    first_seen: Dict[Tuple[str, Any], int] = {}

    for channel, hits in channels.items():
        weight = WEIGHTS.get(channel, 1.0)
        for rank, hit in enumerate(hits):
            key = _key_of(channel, hit)
            scores[key] = scores.get(key, 0.0) + weight / (RRF_K + rank + 1)
            if key not in store:
                rec = dict(hit)
                rec["channel"] = channel
                store[key] = rec
                first_seen[key] = len(first_seen)

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], first_seen.get(kv[0], 0)))
    return [(score, "%s:%s" % (key[0], key[1]), store[key]) for key, score in ranked[:k]]


def _shorten(text: Optional[str], limit: int = MAX_SNIPPET) -> str:
    if not text:
        return ""
    text = re.sub(r"\s*\n\s*", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + " …"


def _cite(hit: Dict[str, Any]) -> str:
    path = hit.get("path") or "?"
    line = hit.get("line")
    return "%s:%s" % (path, line) if line else str(path)


def _render(hit: Dict[str, Any]) -> str:
    channel = hit.get("channel")
    if channel == "rule":
        lines = [
            "规则 [%s] %s" % (hit.get("rule_type") or "rule", _cite(hit)),
            "  %s %s %s:%s %s;" % (hit.get("rule_type") or "allow", hit.get("src"),
                                   hit.get("tgt"), hit.get("tclass"), hit.get("perms")),
        ]
        if hit.get("cond"):
            lines.append("  启用条件: %s" % hit["cond"])
        if hit.get("module"):
            lines.append("  模块: %s" % hit["module"])
        return "\n".join(lines)

    if channel == "symbol":
        lines = ["符号 [%s] %s — %s" % (hit.get("kind") or "symbol",
                                        hit.get("name"), _cite(hit))]
        if hit.get("summary"):
            lines.append("  说明: %s" % _shorten(hit["summary"], 240))
        if hit.get("module"):
            lines.append("  模块: %s" % hit["module"])
        return "\n".join(lines)

    if channel == "fctx":
        ftype = ("  类型: %s" % hit["ftype"]) if hit.get("ftype") else ""
        return "\n".join([
            "文件上下文 %s" % _cite(hit),
            "  %s -> %s%s" % (hit.get("pattern"), hit.get("context_type") or "<<none>>", ftype),
        ])

    label = "策略源码" if hit.get("source") == "refpolicy" else "知识文档"
    return "\n".join([
        "%s [%s] %s" % (label, hit.get("source") or "?", _cite(hit)),
        "  标题: %s" % (hit.get("title") or hit.get("kind") or "片段"),
        "  %s" % _shorten(hit.get("text")),
    ])


# kind 参数 -> 允许的 chunk.kind（None 表示不限）
KIND_MAP: Dict[str, Optional[Tuple[str, ...]]] = {
    "doc": ("doc", "wiki", "man", "glossary", "policy_config"),
    "interface": ("interface", "template"),
    "macro": ("macro",),
    "file_context": ("file_context",),
    "rule": ("te_section", "interface", "template"),
}


def search_hits(query: str, kind: str = "all", module: Optional[str] = None,
                k: int = 5, db_path: Optional[str] = None) -> Dict[str, Any]:
    """执行检索并返回结构化结果，供测试与上层复用。"""
    path = db_path or default_db_path()
    try:
        k = int(k)
    except (TypeError, ValueError):
        k = 5
    k = max(1, min(k, MAX_K))
    kind = (kind or "all").strip().lower() or "all"
    module = (module or "").strip() or None

    types, idents = extract_identifiers(query or "")
    paths = extract_paths(query or "")
    tokens = query_tokens(query or "")

    conn = _connect(path)
    try:
        info = {r["key"]: r["value"] for r in conn.execute("SELECT key,value FROM meta")}
        channels: Dict[str, List[Dict[str, Any]]] = {}
        if kind in ("all", "symbol", "interface", "macro"):
            channels["symbol"] = _search_symbols(conn, idents or tokens, module, k * 2)
        if kind in ("all", "rule"):
            channels["rule"] = _search_rules(conn, idents or types, module, k * 2)
        if kind in ("all", "file_context"):
            channels["fctx"] = _search_file_contexts(conn, paths, idents or types, module, k * 2)
        if kind in ("all", "doc", "interface", "macro", "rule"):
            kf = KIND_MAP.get(kind)
            fts_hits = _search_fts(conn, tokens, module, kf, k * 3)
            channels["fts"] = fts_hits or _search_like(conn, tokens, module, kf, k * 3)
    finally:
        conn.close()

    if kind == "interface":
        channels["symbol"] = [h for h in channels.get("symbol", [])
                              if h.get("kind") in ("interface", "template")]
    elif kind == "macro":
        channels["symbol"] = [h for h in channels.get("symbol", [])
                              if h.get("kind") in ("macro", "permission_set")]

    # 显式的"查无直接规则"提示：比返回一堆不相关的规则更有价值
    notes: List[str] = []
    if kind in ("all", "rule") and len(idents) >= 2:
        rule_hits = channels.get("rule") or []
        if not any(h.get("paired") for h in rule_hits):
            notes.append(
                "未在策略源码中找到 %s → %s 的直接 allow 规则。"
                "这不等于绝对不允许：策略常通过接口宏间接授权。"
                "可改用 kind=rule 并只查 %s，或检索相关接口/布尔值后再下结论。"
                % (idents[0], idents[1], idents[0])
            )

    return {"query": query, "kind": kind, "module": module,
            "info": info, "notes": notes, "hits": _fuse(channels, k)}


def search(query: str, kind: str = "all", module: Optional[str] = None,
           k: int = 5, db_path: Optional[str] = None) -> str:
    """检索知识库，返回可直接放进提示词的文本（含出处引用）。"""
    if not (query or "").strip():
        return ("【SELinux 知识库】查询为空。请提供要查证的类型名、布尔值、路径或概念关键词。")

    try:
        result = search_hits(query, kind=kind, module=module, k=k, db_path=db_path)
    except FileNotFoundError:
        return ("【SELinux 知识库】索引文件不存在，无法检索。"
                "请先在部署机器上运行 build_index.py 生成索引。")
    except sqlite3.Error as exc:
        return "【SELinux 知识库】检索出错：%s" % exc

    hits = result["hits"]
    info = result["info"]
    scope = "kind=%s" % result["kind"]
    if result["module"]:
        scope += "，module=%s" % result["module"]

    if not hits:
        return ("【SELinux 知识库】未找到与 %r 匹配的记录（%s）。\n"
                "说明：知识库中没有相关证据。不要凭记忆编造类型名或规则，"
                "请换关键词重试，或直接说明无法确认。"
                % (result["query"], scope))

    parts = [
        "【SELinux 知识库】查询 %r（%s）命中 %d 条；索引构建于 %s。"
        % (result["query"], scope, len(hits), info.get("built_at", "未知")),
        "以下为检索到的原始依据；引用类型名/规则时必须与这里一致，不要编造未出现的标识符。",
    ]
    for note in result.get("notes") or []:
        parts.append("注意：" + note)
    parts.append("")
    total = len(parts[0]) + len(parts[1])
    for i, (_score, _key, hit) in enumerate(hits, 1):
        block = "%d. %s" % (i, _render(hit))
        if total + len(block) > MAX_TOTAL_CHARS and i > 1:
            parts.append("…（结果过长已截断；可缩小关键词或指定 module 再查）")
            break
        parts.append(block)
        parts.append("")
        total += len(block) + 1
    return "\n".join(parts).strip()
