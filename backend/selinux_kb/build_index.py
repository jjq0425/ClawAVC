#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建 SELinux 知识库索引（SQLite，单文件、可跨机器拷贝）。

用法::

    # 环境自检（不写文件）
    python3 build_index.py --check

    # 构建索引
    python3 build_index.py --corpus /path/to/SELinux --out /path/to/selinux_kb.db

    # 构建后跑一遍抽样检索，确认索引可用
    python3 build_index.py --corpus ... --out ... --sample

设计约束（面向 2GB 内存的 Linux 服务器）：
  * 只依赖标准库，不安装任何第三方包
  * 兼容 Python 3.8+；SQLite 缺 FTS5 时自动降级为 LIKE 检索
  * 产物为单个 .db 文件（DELETE journal + VACUUM），可直接 scp 到目标机器
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from . import parsers as P
except ImportError:  # 直接以脚本方式运行
    import parsers as P

TOOL_VERSION = "1.0.0"

# wiki 中与策略推理相关的页面；发布流水账/会议记录等噪声页不收录
WIKI_INCLUDE = [
    "Tools.creole",
    "Fix-Policy-Problems.md",
    "Policy-Store-Migration.md",
    "Userspace-Packages.md",
    "High-Level-Language-Infrastructure.md",
    "Home.md",
    "Other-Resources.md",
]

REFPOLICY_POLICY_FILES = [
    "policy/constraints",
    "policy/users",
    "policy/mls",
    "policy/mcs",
    "policy/context_defaults",
    "policy/policy_capabilities",
    "policy/global_booleans",
    "policy/global_tunables",
    "policy/flask/security_classes",
    "policy/flask/initial_sids",
]


# ────────────────────────────── 环境自检 ──────────────────────────────


def fts5_available() -> bool:
    try:
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE VIRTUAL TABLE _probe USING fts5(x)")
            return True
        finally:
            conn.close()
    except Exception:
        return False


def check_env(corpus: Optional[str]) -> int:
    print("Python   : %s" % sys.version.split()[0])
    print("SQLite   : %s" % sqlite3.sqlite_version)
    ok_fts5 = fts5_available()
    print("FTS5     : %s" % ("可用" if ok_fts5 else "不可用（将降级为 LIKE 检索）"))

    if sys.version_info < (3, 8):
        print("错误     : 需要 Python 3.8 及以上")
        return 2
    if corpus:
        found = detect_sources(corpus)
        if not found:
            print("错误     : 在 %s 下未找到 refpolicy/ 或 selinux-notebook/ 或 selinux.wiki/" % corpus)
            return 2
        for name, path in sorted(found.items()):
            print("语料     : %-18s %s" % (name, path))
    print("结论     : %s" % ("环境可用" if ok_fts5 else "环境可用（无 FTS5，检索质量略降）"))
    return 0


def detect_sources(corpus: str) -> Dict[str, str]:
    """在 corpus 目录下探测三类语料的实际位置。"""
    found: Dict[str, str] = {}
    candidates = {
        "refpolicy": ["refpolicy", "."],
        "notebook": ["selinux-notebook", "notebook"],
        "wiki": ["selinux.wiki", "wiki"],
    }
    for name, names in candidates.items():
        for sub in names:
            base = os.path.join(corpus, sub) if sub != "." else corpus
            if name == "refpolicy" and os.path.isdir(os.path.join(base, "policy", "modules")):
                found[name] = base
                break
            if name == "notebook" and os.path.isdir(os.path.join(base, "src")):
                found[name] = base
                break
            if name == "wiki" and os.path.isfile(os.path.join(base, "Tools.creole")):
                found[name] = base
                break
    return found


def _dedupe(records: List[Dict], keys) -> List[Dict]:
    """按给定字段组合去重，保持原有顺序。"""
    seen = set()
    out: List[Dict] = []
    for rec in records:
        k = tuple(rec.get(x) for x in keys)
        if k in seen:
            continue
        seen.add(k)
        out.append(rec)
    return out


# ────────────────────────────── 语料遍历 ──────────────────────────────


def collect_refpolicy(root: str, log) -> Tuple[List[Dict], List[Dict], List[Dict], List[Dict]]:
    chunks: List[Dict] = []
    symbols: List[Dict] = []
    rules: List[Dict] = []
    fctxs: List[Dict] = []
    unbalanced: List[str] = []

    modules_root = os.path.join(root, "policy", "modules")
    for path in P.walk_files(modules_root, (".te", ".if", ".fc"), skip_dirs=(".git",)):
        rel = P.rel_path(path, root)
        module = os.path.splitext(os.path.basename(path))[0]
        try:
            if path.endswith(".te"):
                c, s, r, balanced = P.parse_te(path, rel, module)
                if not balanced:
                    unbalanced.append(rel)
            elif path.endswith(".if"):
                c, s, r = P.parse_if(path, rel, module)
            else:
                c, f = P.parse_fc(path, rel, module)
                fctxs.extend(f)
                chunks.extend(c)
                continue
        except Exception as exc:  # 单个文件失败不影响整体构建
            log("  跳过 %s：%s" % (rel, exc))
            continue
        chunks.extend(c)
        symbols.extend(s)
        rules.extend(r)

    support_root = os.path.join(root, "policy", "support")
    for path in P.walk_files(support_root, (".spt",), skip_dirs=(".git",)):
        rel = P.rel_path(path, root)
        try:
            c, s = P.parse_spt(path, rel)
        except Exception as exc:
            log("  跳过 %s：%s" % (rel, exc))
            continue
        chunks.extend(c)
        symbols.extend(s)

    av_path = os.path.join(root, "policy", "flask", "access_vectors")
    if os.path.isfile(av_path):
        rel = P.rel_path(av_path, root)
        c, s = P.parse_access_vectors(av_path, rel)
        chunks.extend(c)
        symbols.extend(s)

    for name in REFPOLICY_POLICY_FILES:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        rel = P.rel_path(path, root)
        text = P.read_text(path).strip()
        if not text:
            continue
        title = "refpolicy %s" % name
        for piece, off in P.split_long(text, 1):
            chunks.append(P._chunk("policy_config", "refpolicy", rel, off, title, piece, None))

    for path in P.walk_files(os.path.join(root, "doc"), (".md",), skip_dirs=(".git",)):
        rel = P.rel_path(path, root)
        chunks.extend(P.parse_markdown(path, rel, "refpolicy", kind="doc",
                                       prefix="refpolicy 文档"))

    for path in P.walk_files(os.path.join(root, "man"), (".8",), skip_dirs=(".git",)):
        rel = P.rel_path(path, root)
        chunks.extend(P.parse_man(path, rel))

    if unbalanced:
        log("  注意：%d 个 .te 文件的 m4 条件块括号不平衡，其规则不标注启用条件"
            % len(unbalanced))
        log("        例如：%s" % ", ".join(unbalanced[:3]))

    return chunks, symbols, rules, fctxs


def collect_notebook(root: str, log) -> Tuple[List[Dict], List[Dict]]:
    chunks: List[Dict] = []
    symbols: List[Dict] = []
    src = os.path.join(root, "src")
    for path in P.walk_files(src, (".md",), skip_dirs=(".git", "images", "notebook-examples")):
        rel = P.rel_path(path, root)
        base = os.path.basename(path)
        if base == "terminology.md":
            c, s = P.parse_terminology(path, rel, "notebook")
            chunks.extend(c)
            symbols.extend(s)
        chunks.extend(P.parse_markdown(path, rel, "notebook", kind="doc",
                                       prefix="SELinux Notebook"))
    return chunks, symbols


def collect_wiki(root: str, log) -> List[Dict]:
    chunks: List[Dict] = []
    for name in WIKI_INCLUDE:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        if name.endswith(".creole"):
            chunks.extend(P.parse_creole(path, P.rel_path(path, root)))
        else:
            chunks.extend(P.parse_markdown(path, P.rel_path(path, root), "wiki", kind="wiki"))
    return chunks


# ────────────────────────────── 写库 ──────────────────────────────

SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE chunks(
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    module TEXT,
    source TEXT NOT NULL,
    path TEXT NOT NULL,
    line INTEGER,
    title TEXT,
    text TEXT NOT NULL
);
CREATE INDEX idx_chunks_module ON chunks(module);
CREATE INDEX idx_chunks_kind ON chunks(kind);
CREATE INDEX idx_chunks_path ON chunks(path);

CREATE TABLE symbols(
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT,
    module TEXT,
    source TEXT,
    path TEXT,
    line INTEGER,
    summary TEXT
);
CREATE INDEX idx_symbols_name ON symbols(name);
CREATE INDEX idx_symbols_name_nocase ON symbols(name COLLATE NOCASE);
CREATE INDEX idx_symbols_kind ON symbols(kind);

CREATE TABLE access_rules(
    id INTEGER PRIMARY KEY,
    rule_type TEXT,
    src TEXT,
    tgt TEXT,
    tclass TEXT,
    perms TEXT,
    cond TEXT,
    module TEXT,
    source TEXT,
    path TEXT,
    line INTEGER
);
CREATE INDEX idx_rules_src ON access_rules(src);
CREATE INDEX idx_rules_tgt ON access_rules(tgt);
CREATE INDEX idx_rules_st ON access_rules(src, tgt);

CREATE TABLE file_contexts(
    id INTEGER PRIMARY KEY,
    pattern TEXT,
    ftype TEXT,
    context_type TEXT,
    module TEXT,
    source TEXT,
    path TEXT,
    line INTEGER
);
CREATE INDEX idx_fctx_type ON file_contexts(context_type);
CREATE INDEX idx_fctx_pattern ON file_contexts(pattern);
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    title, text, content='chunks', content_rowid='id',
    tokenize='porter unicode61'
);
"""


def build(corpus: str, out_path: str, log) -> Dict[str, int]:
    sources = detect_sources(corpus)
    if not sources:
        raise SystemExit("在 %s 下未找到任何语料目录" % corpus)

    log("语料目录：")
    for name, path in sorted(sources.items()):
        log("  %-10s %s" % (name, path))

    all_chunks: List[Dict] = []
    all_symbols: List[Dict] = []
    all_rules: List[Dict] = []
    all_fctxs: List[Dict] = []

    if "refpolicy" in sources:
        log("解析 refpolicy ...")
        c, s, r, f = collect_refpolicy(sources["refpolicy"], log)
        all_chunks += c
        all_symbols += s
        all_rules += r
        all_fctxs += f
        log("  chunks=%d symbols=%d rules=%d file_contexts=%d" % (len(c), len(s), len(r), len(f)))

    if "notebook" in sources:
        log("解析 selinux-notebook ...")
        c, s = collect_notebook(sources["notebook"], log)
        all_chunks += c
        all_symbols += s
        log("  chunks=%d symbols=%d" % (len(c), len(s)))

    if "wiki" in sources:
        log("解析 selinux.wiki ...")
        c = collect_wiki(sources["wiki"], log)
        all_chunks += c
        log("  chunks=%d" % len(c))

    # 去重：同一 (文件, 行号, 标题) 的片段只保留一份，避免接口/模板被重复扫描
    all_chunks = _dedupe(all_chunks, ("path", "line", "kind", "title"))
    all_symbols = _dedupe(all_symbols, ("name", "path", "line", "kind"))
    all_rules = _dedupe(all_rules, ("path", "line", "rule_type", "src", "tgt", "tclass"))
    all_fctxs = _dedupe(all_fctxs, ("path", "line", "pattern"))

    use_fts = fts5_available()
    tmp_path = out_path + ".tmp"
    for stale in (tmp_path, tmp_path + "-journal"):
        if os.path.exists(stale):
            os.remove(stale)

    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    conn = sqlite3.connect(tmp_path)
    try:
        conn.executescript(SCHEMA)
        if use_fts:
            conn.executescript(FTS_SCHEMA)

        conn.executemany(
            "INSERT INTO chunks(kind,module,source,path,line,title,text) VALUES(?,?,?,?,?,?,?)",
            [(c["kind"], c["module"], c["source"], c["path"], c["line"], c["title"], c["text"])
             for c in all_chunks],
        )
        conn.executemany(
            "INSERT INTO symbols(name,kind,module,source,path,line,summary) VALUES(?,?,?,?,?,?,?)",
            [(s["name"], s["kind"], s["module"], s["source"], s["path"], s["line"], s["summary"])
             for s in all_symbols],
        )
        conn.executemany(
            "INSERT INTO access_rules(rule_type,src,tgt,tclass,perms,cond,module,source,path,line)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            [(r["rule_type"], r["src"], r["tgt"], r["tclass"], r["perms"], r["cond"],
              r["module"], r["source"], r["path"], r["line"]) for r in all_rules],
        )
        conn.executemany(
            "INSERT INTO file_contexts(pattern,ftype,context_type,module,source,path,line)"
            " VALUES(?,?,?,?,?,?,?)",
            [(f["pattern"], f["ftype"], f["context_type"], f["module"], f["source"],
              f["path"], f["line"]) for f in all_fctxs],
        )

        if use_fts:
            conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")

        meta = {
            "tool_version": TOOL_VERSION,
            "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "built_on": "%s %s" % (sys.platform, sys.version.split()[0]),
            "sqlite_version": sqlite3.sqlite_version,
            "fts5": "1" if use_fts else "0",
            "corpus": corpus,
            "chunks": str(len(all_chunks)),
            "symbols": str(len(all_symbols)),
            "access_rules": str(len(all_rules)),
            "file_contexts": str(len(all_fctxs)),
        }
        for k, v in sorted(meta.items()):
            conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (k, v))

        conn.commit()
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("VACUUM")
        conn.execute("PRAGMA optimize")
        conn.commit()
    finally:
        conn.close()

    if os.path.exists(out_path):
        os.remove(out_path)
    os.replace(tmp_path, out_path)

    return {
        "chunks": len(all_chunks),
        "symbols": len(all_symbols),
        "access_rules": len(all_rules),
        "file_contexts": len(all_fctxs),
        "fts5": 1 if use_fts else 0,
    }


# ────────────────────────────── 抽样验证 ──────────────────────────────

SAMPLE_QUERIES = [
    ("httpd_t var_log_t write", "rule"),
    ("apache_read_user_content", "symbol"),
    ("/etc/httpd", "file_context"),
    ("httpd_can_network_connect", "symbol"),
    ("AVC denied 如何排查", "all"),
    ("type_transition", "all"),
]


def run_samples(db_path: str, log) -> None:
    try:
        from . import search as S
    except ImportError:
        import search as S
    log("")
    log("抽样检索：")
    for query, kind in SAMPLE_QUERIES:
        log("-" * 68)
        log("查询: %s   (kind=%s)" % (query, kind))
        try:
            out = S.search(query, kind=kind, k=3, db_path=db_path)
        except Exception as exc:
            log("  检索失败：%s" % exc)
            continue
        log(out)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="构建 SELinux 知识库索引")
    ap.add_argument("--corpus", default=os.environ.get("SELINUX_CORPUS", ""),
                    help="语料根目录（含 refpolicy/ selinux-notebook/ selinux.wiki/）")
    ap.add_argument("--out", default=os.environ.get("SELINUX_KB_PATH", ""),
                    help="输出索引文件路径")
    ap.add_argument("--check", action="store_true", help="只做环境自检")
    ap.add_argument("--sample", action="store_true", help="构建后跑抽样检索")
    ap.add_argument("--selftest", action="store_true",
                    help="对已存在的索引（--out）跑抽样检索，用于目标机器验证")
    args = ap.parse_args(argv)

    def log(msg: str) -> None:
        print(msg, flush=True)

    if args.check:
        return check_env(args.corpus or None)

    if args.selftest:
        if not args.out or not os.path.isfile(args.out):
            log("错误：--selftest 需要用 --out 指向已存在的索引文件")
            return 2
        run_samples(args.out, log)
        return 0

    if not args.corpus:
        log("错误：请用 --corpus 指定语料根目录（或设置 SELINUX_CORPUS）")
        return 2
    if not args.out:
        log("错误：请用 --out 指定输出路径（或设置 SELINUX_KB_PATH）")
        return 2
    if not os.path.isdir(args.corpus):
        log("错误：语料目录不存在：%s" % args.corpus)
        return 2

    t0 = time.time()
    stats = build(args.corpus, args.out, log)
    size_mb = os.path.getsize(args.out) / 1024.0 / 1024.0
    log("")
    log("构建完成：%s" % args.out)
    log("  chunks=%d  symbols=%d  access_rules=%d  file_contexts=%d"
        % (stats["chunks"], stats["symbols"], stats["access_rules"], stats["file_contexts"]))
    log("  文件大小=%.1f MB  FTS5=%s  耗时=%.1fs"
        % (size_mb, "是" if stats["fts5"] else "否（LIKE 降级）", time.time() - t0))

    if args.sample:
        run_samples(args.out, log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
