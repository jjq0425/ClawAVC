#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SELinux 知识库检索自检：覆盖索引、解析、四条召回通道、融合排序、
输出引用、负例防幻觉、无 FTS5 降级、性能内存、预取集成、端到端工具调用。

用法::

    cd backend/selinux_kb
    python3 test_retrieval.py                      # 全流程自检
    python3 test_retrieval.py --corpus /path/to/SELinux   # 指定语料，启用源码比对
    python3 test_retrieval.py --json out.json      # 结果另存 JSON
    python3 test_retrieval.py --perf-queries 200   # 加大性能压测样本

仅依赖标准库，可在目标 Linux 服务器上直接运行（缺语料时自动跳过源码比对项）。
退出码 0 = 全部通过，1 = 有失败项。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
for p in (BACKEND, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from selinux_kb import search as S  # noqa: E402
from selinux_kb import prefetch as P  # noqa: E402

RESULTS: List[Dict[str, Any]] = []
_CURRENT_GROUP = ""


# ────────────────────────────── 结果记录 ──────────────────────────────


def group(title: str) -> None:
    global _CURRENT_GROUP
    _CURRENT_GROUP = title
    print("\n" + "─" * 72)
    print(title)
    print("─" * 72)


def ok(name: str, detail: str = "") -> None:
    RESULTS.append({"group": _CURRENT_GROUP, "name": name, "ok": True, "detail": detail})
    print("  ✓ %s%s" % (name, ("  — " + detail) if detail else ""))


def bad(name: str, detail: str = "") -> None:
    RESULTS.append({"group": _CURRENT_GROUP, "name": name, "ok": False, "detail": detail})
    print("  ✗ %s%s" % (name, ("  — " + detail) if detail else ""))


def expect(name: str, cond: bool, detail: str = "") -> bool:
    (ok if cond else bad)(name, detail)
    return bool(cond)


def skip(name: str, why: str) -> None:
    RESULTS.append({"group": _CURRENT_GROUP, "name": name, "ok": True,
                    "detail": "跳过：" + why, "skipped": True})
    print("  – %s  （跳过：%s）" % (name, why))


# ────────────────────────────── 工具 ──────────────────────────────


def default_corpus(db_path: str) -> Optional[str]:
    """索引所在位置往上三级通常是语料根目录（clawAVC/infos/selinux_kb → SELinux/）。"""
    guess = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(db_path)),
                                          "..", "..", ".."))
    if os.path.isdir(os.path.join(guess, "refpolicy")):
        return guess
    return None


def find_line(corpus: str, relpath: str, pattern: str) -> Optional[int]:
    """在语料文件里定位首行匹配 pattern 的行号（1-based），用于比对解析结果。"""
    path = os.path.join(corpus, relpath)
    if not os.path.isfile(path):
        return None
    rx = re.compile(pattern)
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh, 1):
            if rx.search(line):
                return i
    return None


def query(db: str, sql: str, params: Tuple = ()) -> List[sqlite3.Row]:
    conn = S._connect(db)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


# ────────────────────────────── 1. 索引完整性 ──────────────────────────────


def check_index(db: str) -> Optional[Dict[str, str]]:
    group("1/12  索引完整性")
    if not expect("索引文件存在", os.path.isfile(db), db):
        return None
    size_mb = os.path.getsize(db) / 1048576.0
    ok("文件大小", "%.1f MB" % size_mb)

    conn = S._connect(db)
    info: Dict[str, str] = {}
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        expect("PRAGMA integrity_check = ok", bool(row) and row[0] == "ok",
               str(row[0]) if row else "")

        info = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
        for key in ("built_at", "chunks", "symbols", "access_rules", "file_contexts", "fts5"):
            expect("meta.%s 已写入" % key, bool(info.get(key)), str(info.get(key, "")))

        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','index')")}
        for name in ("chunks", "symbols", "access_rules", "file_contexts", "chunks_fts"):
            expect("表 %s 存在" % name, name in names)
        for name in ("idx_symbols_name", "idx_rules_st", "idx_fctx_type", "idx_chunks_module"):
            expect("索引 %s 存在" % name, name in names)

        counts = {t: conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
                  for t in ("chunks", "symbols", "access_rules", "file_contexts")}
        expect("四张表均有数据", all(v > 0 for v in counts.values()),
               " ".join("%s=%d" % kv for kv in counts.items()))

        fts_n = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
        expect("FTS5 与 chunks 行数一致", fts_n == counts["chunks"],
               "fts=%d chunks=%d" % (fts_n, counts["chunks"]))

        # 符号名唯一性（同名字符串允许出现在不同位置，但不该多到离谱）
        dup = conn.execute(
            "SELECT name, COUNT(*) n FROM symbols GROUP BY name, path, line "
            "HAVING n > 1 LIMIT 3").fetchall()
        expect("同一位置无重复符号", not dup, str([r["name"] for r in dup]))

        # 规则表核心字段完整
        nulls = conn.execute(
            "SELECT COUNT(*) FROM access_rules WHERE src IS NULL OR tgt IS NULL").fetchone()[0]
        expect("规则 src/tgt 无空值", nulls == 0, "空值 %d 条" % nulls)
    finally:
        conn.close()
    return info


# ────────────────────────────── 2. 解析正确性 ──────────────────────────────


def check_ground_truth(db: str, corpus: Optional[str]) -> None:
    group("2/12  解析正确性（与源码逐行比对）")
    if not corpus:
        skip("源码比对", "未找到语料目录，用 --corpus 指定后启用")
        return

    cases = [
        ("符号", "apache_read_user_content", "interface",
         "refpolicy/policy/modules/services/apache.if",
         r"^interface\(`apache_read_user_content'"),
        ("符号", "httpd_can_network_connect", "tunable",
         "refpolicy/policy/modules/services/apache.te",
         r"gen_tunable\(httpd_can_network_connect"),
        ("符号", "httpd_t", "type",
         "refpolicy/policy/modules/services/apache.te",
         r"^\s*type httpd_t\b"),
        ("符号", "httpd_log_t", "type",
         "refpolicy/policy/modules/services/apache.te",
         r"^\s*type httpd_log_t\b"),
    ]
    for label, name, kind, relpath, pattern in cases:
        want = find_line(corpus, relpath, pattern)
        got = query(db, "SELECT line, path, kind FROM symbols WHERE name = ? "
                        "AND path LIKE ? ORDER BY line LIMIT 1", (name, "%" + os.path.basename(relpath)))
        if want is None:
            skip("%s %s" % (label, name), "源码中未定位到该声明")
            continue
        if not got:
            bad("%s %s 已入库" % (label, name), "库中查无此符号")
            continue
        row = got[0]
        expect("%s %s 行号一致（源码 %d / 库 %d）" % (label, name, want, row["line"]),
               row["line"] == want, row["path"])
        expect("%s %s 类型正确" % (label, name), row["kind"] == kind,
               "kind=%s" % row["kind"])

    # 文件上下文：源码里的路径模式必须能反查到
    fc_cases = [
        ("refpolicy/policy/modules/services/apache.fc", r"^/etc/httpd/logs\b", "httpd_log_t"),
        ("refpolicy/policy/modules/services/apache.fc", r"^/var/www\(/\.\*\)\?", "httpd_sys_content_t"),
    ]
    for relpath, pattern, ctype in fc_cases:
        line = find_line(corpus, relpath, pattern)
        if line is None:
            skip("文件上下文 %s" % ctype, "源码中未定位到该模式")
            continue
        got = query(db, "SELECT line, context_type FROM file_contexts WHERE context_type = ? "
                        "AND path LIKE ? ORDER BY ABS(line - ?) LIMIT 1", (ctype, "%" + relpath.split("/")[-1], line))
        if not got:
            bad("文件上下文 %s 已入库" % ctype, "库中查无该类型")
            continue
        expect("文件上下文 %s 行号贴近源码（源码 %d / 库 %d）" % (ctype, line, got[0]["line"]),
               abs(got[0]["line"] - line) <= 2, relpath)

    # 访问规则：库里任取 20 条 allow，逐条回到源码确认该行确实是这条规则
    rules = query(db, "SELECT src, tgt, path, line FROM access_rules "
                      "WHERE rule_type='allow' AND path LIKE '%/services/%' "
                      "ORDER BY id LIMIT 20")
    if not rules:
        bad("规则回查源码", "库中没有 services/ 下的 allow 规则")
    else:
        mismatched = []
        for r in rules:
            path = os.path.join(corpus, "refpolicy", r["path"])
            if not os.path.isfile(path):
                mismatched.append("%s 不存在" % r["path"])
                continue
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
            if not (0 < r["line"] <= len(lines)):
                mismatched.append("%s:%d 越界" % (r["path"], r["line"]))
                continue
            text = lines[r["line"] - 1]
            if r["src"] not in text or r["tgt"] not in text:
                mismatched.append("%s:%d 内容不符" % (r["path"], r["line"]))
        expect("随机 20 条 allow 规则可回查源码", not mismatched,
               "全部一致" if not mismatched else "; ".join(mismatched[:3]))


# ────────────────────────────── 3. 查询解析 ──────────────────────────────


def check_query_parsing() -> None:
    group("3/12  查询解析")
    types, idents = S.extract_identifiers("httpd_t 能不能写 var_log_t")
    expect("类型标识符抽取", types == ["httpd_t", "var_log_t"], str(types))

    _, idents2 = S.extract_identifiers("allow httpd_t httpd_sys_script_t:process transition;")
    expect("规则语句中抽取两个类型", idents2[:2] == ["httpd_t", "httpd_sys_script_t"], str(idents2))

    paths = S.extract_paths("看看 /var/log/secure 和 /etc/shadow，顺带 /etc/httpd/conf")
    expect("路径抽取", paths == ["/var/log/secure", "/etc/shadow", "/etc/httpd/conf"], str(paths))

    toks = S.query_tokens("how to fix the AVC denied problem httpd_t")
    expect("停用词被过滤", "the" not in toks and "how" not in toks, str(toks))
    lowered = [t.lower() for t in toks]
    expect("技术词保留", "httpd_t" in lowered and "avc" in lowered, str(toks))

    expr = S._fts_match_expr(['httpd_t', 'a"b', 'x(y)'])
    expect("FTS 表达式安全转义", expr.count('"') >= 6 and '""' in expr, expr)


# ────────────────────────────── 4. 四条召回通道 ──────────────────────────────


def check_channels(db: str) -> None:
    group("4/12  四条召回通道")

    # ① 符号通道
    hits = S.search_hits("apache_read_user_content", kind="symbol", k=3, db_path=db)["hits"]
    kinds = [h[2].get("kind") for h in hits]
    expect("符号通道：接口精确命中", bool(hits) and hits[0][2].get("name") == "apache_read_user_content",
           str(kinds[:3]))

    hits = S.search_hits("httpd_can_network_connect", kind="symbol", k=3, db_path=db)["hits"]
    expect("符号通道：布尔值命中", any(h[2].get("name") == "httpd_can_network_connect" for h in hits))

    # ② 规则通道（成对 src/tgt）
    res = S.search_hits("httpd_t httpd_sys_script_t", kind="rule", k=5, db_path=db)
    paired = [h for h in res["hits"] if h[2].get("channel") == "rule" and h[2].get("paired")]
    expect("规则通道：双向成对命中", len(paired) >= 2,
           "命中 %d 条（含双向）" % len(paired))
    both_dir = {h[2]["src"] for h in paired} == {"httpd_t", "httpd_sys_script_t"}
    expect("规则通道：src/tgt 双向都覆盖", both_dir, str({h[2]["src"] for h in paired}))

    # ③ 文件上下文通道
    hits = S.search_hits("/etc/httpd/logs", kind="file_context", k=3, db_path=db)["hits"]
    types = [h[2].get("context_type") for h in hits]
    expect("文件上下文通道：路径命中", "httpd_log_t" in types, str(types))

    hits = S.search_hits("httpd_log_t", kind="file_context", k=3, db_path=db)["hits"]
    expect("文件上下文通道：按类型反查", bool(hits) and hits[0][2].get("context_type") == "httpd_log_t")

    # ④ 全文通道
    hits = S.search_hits("type_transition", kind="doc", k=3, db_path=db)["hits"]
    paths = [h[2].get("path", "") for h in hits]
    expect("全文通道：命中 Notebook 章节", any("type_statements.md" in p for p in paths),
           str(paths[:3]))

    hits = S.search_hits("audit2allow", kind="doc", k=3, db_path=db)["hits"]
    expect("全文通道：命中 wiki 排错指南",
           any("Fix-Policy-Problems" in h[2].get("path", "") for h in hits),
           str([h[2].get("path") for h in hits][:3]))

    # 宏 / 权限集
    hits = S.search_hits("read_files_pattern", kind="macro", k=3, db_path=db)["hits"]
    expect("宏通道：命中权限宏", any(h[2].get("name") == "read_files_pattern" for h in hits))


# ────────────────────────────── 5. 融合与过滤 ──────────────────────────────


def check_fusion(db: str) -> None:
    group("5/12  RRF 融合与过滤")
    res = S.search_hits("httpd_t /var/log/secure", k=8, db_path=db)
    scores = [h[0] for h in res["hits"]]
    expect("得分单调不增", all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1)),
           str([round(s, 5) for s in scores[:4]]))
    keys = [h[1] for h in res["hits"]]
    expect("结果无重复", len(keys) == len(set(keys)), "%d 条" % len(keys))

    res = S.search_hits("httpd_t", kind="all", module="apache", k=5, db_path=db)
    mods = {h[2].get("module") for h in res["hits"]}
    expect("module 过滤生效", mods <= {"apache", None}, str(mods))

    res = S.search_hits("httpd_t", kind="rule", module="container", k=5, db_path=db)
    mods = {h[2].get("module") for h in res["hits"]}
    expect("module 过滤跨模块不串味", "apache" not in mods, str(mods))

    res = S.search_hits("httpd_t", kind="symbol", k=5, db_path=db)
    chans = {h[2].get("channel") for h in res["hits"]}
    expect("kind=symbol 只走符号通道", chans <= {"symbol"}, str(chans))

    res = S.search_hits("/etc/httpd/logs", kind="file_context", k=5, db_path=db)
    chans = {h[2].get("channel") for h in res["hits"]}
    expect("kind=file_context 只走上下文通道且非空", chans == {"fctx"}, str(chans))


# ────────────────────────────── 6. 输出与引用 ──────────────────────────────


def check_output(db: str) -> None:
    group("6/12  输出格式与出处引用")
    text = S.search("httpd_t httpd_sys_script_t", kind="rule", k=3, db_path=db)
    expect("输出含查询回显", "httpd_t httpd_sys_script_t" in text)
    expect("输出含反幻觉提示", "不要编造" in text, "")
    expect("输出长度受控", len(text) <= S.MAX_TOTAL_CHARS + 400, "%d 字符" % len(text))

    cites = re.findall(r"([A-Za-z0-9_./\-]+\.(?:te|if|fc|md|creole|s|8)):(\d+)", text)
    expect("输出带 文件:行号 出处", len(cites) >= 2, str(cites[:3]))

    conn = S._connect(db)
    try:
        bad_cites = []
        for path, line in cites:
            row = conn.execute(
                "SELECT 1 FROM access_rules WHERE path=? AND line=? "
                "UNION ALL SELECT 1 FROM symbols WHERE path=? AND line=? "
                "UNION ALL SELECT 1 FROM chunks WHERE path=? AND line=? LIMIT 1",
                (path, int(line), path, int(line), path, int(line))).fetchone()
            if not row:
                bad_cites.append("%s:%s" % (path, line))
        expect("每条出处都能在库中定位", not bad_cites,
               "全部可定位" if not bad_cites else str(bad_cites[:3]))
    finally:
        conn.close()

    text = S.search("httpd_t", kind="rule", k=2, db_path=db)
    expect("规则输出含启用条件或模块信息", ("启用条件" in text) or ("模块" in text))


# ────────────────────────────── 7. 负例与防幻觉 ──────────────────────────────


def check_negative(db: str) -> None:
    group("7/12  负例与防幻觉")
    text = S.search("svirt_sandbox_domain", k=3, db_path=db)
    expect("语料中不存在的符号 → 明确未找到", "未找到" in text, text.split("\n")[0][:70])
    expect("未找到时给出禁止编造提示", "不要凭记忆编造" in text or "无法确认" in text)

    text = S.search("httpd_t var_log_t", kind="rule", k=3, db_path=db)
    expect("无直接规则时显式声明", "未在策略源码中找到" in text)
    expect("并说明可能由接口宏间接授权", "接口宏" in text)

    text = S.search("   ", k=3, db_path=db)
    expect("空查询被拦截", "查询为空" in text)

    bogus = os.path.join(tempfile.gettempdir(), "no_such_kb_%d.db" % os.getpid())
    text = S.search("httpd_t", k=1, db_path=bogus)
    expect("索引缺失时给出可操作提示", "索引文件不存在" in text, text[:60])


# ────────────────────────────── 8. 健壮性 ──────────────────────────────


def check_robustness(db: str) -> None:
    group("8/12  健壮性（异常输入不崩）")
    weird = [
        'httpd_t" OR "1', "((httpd_t))", "*", '""', "'", "!@#$%^&*()",
        "httpd_t AND var_log_t", "NEAR(httpd t)", "a" * 5000, "中文" * 300,
        "allow httpd_t var_log_t:file { read write };",
        "../../etc/passwd", "'; DROP TABLE chunks; --", "%", "_",
    ]
    failures = []
    for q in weird:
        try:
            out = S.search(q, k=3, db_path=db)
            if not isinstance(out, str) or not out:
                failures.append(repr(q[:20]) + " 返回空")
        except Exception as exc:
            failures.append("%r → %s: %s" % (q[:20], type(exc).__name__, exc))
    expect("15 组异常输入均安全返回", not failures, "; ".join(failures[:3]))

    kinds = ["all", "rule", "symbol", "interface", "file_context", "doc", "macro", "bogus", ""]
    failures = []
    for k in kinds:
        try:
            S.search("httpd_t", kind=k, k=2, db_path=db)
        except Exception as exc:
            failures.append("%s → %s" % (k, exc))
    expect("全部 kind 取值可用", not failures, str(failures[:3]))

    failures = []
    for k in (-5, 0, 999, "x", None, 3.7):
        try:
            S.search("httpd_t", k=k, db_path=db)
        except Exception as exc:
            failures.append("%r → %s" % (k, exc))
    expect("k 非法值自动兜底", not failures, str(failures[:3]))

    # DROP TABLE 注入后索引仍然完好
    n = query(db, "SELECT COUNT(*) FROM chunks")[0][0]
    expect("注入串未破坏索引", n > 0, "chunks=%d" % n)


# ────────────────────────────── 9. 无 FTS5 降级 ──────────────────────────────


def check_fallback(db: str) -> None:
    group("9/12  无 FTS5 时的降级路径")
    tmpdir = tempfile.mkdtemp(prefix="kb_nofs_")
    tmp = os.path.join(tmpdir, "kb.db")
    try:
        shutil.copy(db, tmp)
        conn = sqlite3.connect(tmp)
        conn.execute("DROP TABLE chunks_fts")
        conn.execute("UPDATE meta SET value='0' WHERE key='fts5'")
        conn.commit()
        conn.close()

        expect("降级库确实没有 FTS5", not S._has_fts(S._connect(tmp)))
        out = S.search("type_transition", kind="doc", k=3, db_path=tmp)
        expect("降级后仍能检索", "未找到" not in out and "命中" in out, out.split("\n")[0][:70])
        hits = S.search_hits("httpd_t var_log_t", kind="rule", k=3, db_path=tmp)["hits"]
        expect("降级后规则通道不受影响", len(hits) >= 1, "%d 条" % len(hits))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ────────────────────────────── 10. 性能与内存 ──────────────────────────────


def check_performance(db: str, n: int) -> None:
    group("10/12  性能与内存")
    queries = [
        "httpd_t var_log_t", "apache_read_user_content", "/etc/httpd/logs",
        "httpd_can_network_connect", "type_transition 的用法", "audit2allow 怎么用",
        "svirt_t", "container_t 能不能写 /etc", "neverallow 规则", "AVC denied 排查",
    ]
    for _ in range(2):                       # 预热
        for q in queries:
            S.search(q, k=5, db_path=db)

    lat: List[float] = []
    for i in range(n):
        q = queries[i % len(queries)]
        t0 = time.perf_counter()
        S.search(q, k=5, db_path=db)
        lat.append((time.perf_counter() - t0) * 1000.0)
    lat.sort()
    p50 = lat[len(lat) // 2]
    p95 = lat[int(len(lat) * 0.95) - 1] if len(lat) > 1 else lat[0]
    ok("检索延迟", "n=%d  p50=%.1fms  p95=%.1fms  max=%.1fms" % (n, p50, p95, lat[-1]))
    expect("p95 低于 300ms", p95 < 300.0, "%.1fms" % p95)

    try:
        import resource
        raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss = raw / 1048576.0 if sys.platform == "darwin" else raw / 1024.0
        expect("进程峰值 RSS 低于 300MB", rss < 300.0, "%.1f MB" % rss)
    except Exception:
        skip("内存占用", "当前平台不支持 resource.getrusage")

    # 冷启动：新建连接的开销
    t0 = time.perf_counter()
    S.search_hits("httpd_t", k=3, db_path=db)
    ok("单次调用（含建连）", "%.1fms" % ((time.perf_counter() - t0) * 1000))


# ────────────────────────────── 11. 预取集成 ──────────────────────────────


def check_prefetch(db: str) -> None:
    group("11/12  回答前自动预取")
    row = {
        "user_query": "读取 /var/log/secure 的内容",
        "pid_info": json.dumps({"main_selinux_label": "system_u:system_r:httpd_t:s0"}),
        "action_json": json.dumps([{"tool": "read_file", "args": {"path": "/var/log/secure"}}]),
    }
    block = P.block_for_round(row)
    expect("技能分析预取有输出", len(block) > 200, "%d 字符" % len(block))
    expect("预取含文件上下文依据", "-> var_log_t" in block or "var_log_t" in block)
    expect("预取含反幻觉约束", "不得编造" in block)

    expect("普通对话：SELinux 问题注入", bool(P.block_for_text("httpd_t 能写 /var/log 吗")))
    expect("普通对话：中文问题可命中", bool(P.block_for_text("什么是 SELinux 安全上下文")))
    expect("普通对话：无关问题不注入", P.block_for_text("你好，帮我写首诗") == "")

    types, paths, _extras = P._clues_from_round(row)
    expect("unconfined_t 噪声被剔除", "unconfined_t" not in types, str(types))
    expect("访问路径被提取", "/var/log/secure" in paths, str(paths))

    base = P.extend_skill_prompt("自定义提示词")
    expect("自定义提示词也会追加约束", "SELinux 依据要求" in base)
    expect("约束追加幂等", P.extend_skill_prompt(base).count("SELinux 依据要求") == 1)


# ────────────────────────────── 12. 端到端工具调用 ──────────────────────────────


def _stub_modules() -> None:
    """为导入 xy_skill 准备轻量桩件（不触碰真实数据库与 Flask）。"""
    import types
    if "db" not in sys.modules:
        dbm = types.ModuleType("db")
        dbm.get_round_by_id = lambda rid: None
        dbm.get_config = lambda key, default=None: default
        sys.modules["db"] = dbm
    if "app" not in sys.modules:
        app = types.ModuleType("app")
        for fn in ("_simplify_ir_json", "_simplify_action_json", "_simplify_resource_facts",
                   "_simplify_syscall_judge", "_simplify_kernel_judge_from_path",
                   "_read_file_text", "_try_json"):
            setattr(app, fn, lambda *a, **k: "")
        sys.modules["app"] = app
    if "requests" not in sys.modules:
        try:
            import requests  # noqa: F401
        except ImportError:
            sys.modules["requests"] = types.ModuleType("requests")


def check_end_to_end() -> None:
    group("12/12  端到端：小异工具调用")
    try:
        _stub_modules()
        import xy_skill as X
    except Exception as exc:
        skip("导入 xy_skill", "%s: %s" % (type(exc).__name__, exc))
        return

    names = [t["function"]["name"] for t in X.TOOLS]
    expect("工具已注册到小异", "search_selinux_knowledge" in names, "共 %d 个工具" % len(names))
    expect("工具位于靠前位置", names.index("search_selinux_knowledge") <= 1, "位置 %d" % (names.index("search_selinux_knowledge") + 1))
    expect("工具计入参数类分发", "search_selinux_knowledge" in X.ARG_TOOLS)

    out = X._call_tool_handler("search_selinux_knowledge", "r1",
                               '{"query": "httpd_can_network_connect", "kind": "symbol", "k": 2}')
    expect("工具可返回带出处的依据", "httpd_can_network_connect" in out and "apache.te" in out,
           out.split("\n")[0][:70])

    out = X._call_tool_handler("search_selinux_knowledge", "r1", "{}")
    expect("空参数给出明确提示", "不能为空" in out)
    out = X._call_tool_handler("search_selinux_knowledge", "r1", "not-json")
    expect("非法 JSON 给出明确提示", "不是合法 JSON" in out)

    prompt = X._get_skill_system_prompt()
    expect("系统提示词含 SELinux 依据约束", "SELinux 依据要求" in prompt)


# ────────────────────────────── 主流程 ──────────────────────────────


def run_all(db: str, corpus: Optional[str], perf_queries: int) -> int:
    print("=" * 72)
    print("SELinux 知识库检索自检")
    print("=" * 72)
    print("索引 : %s" % db)
    print("语料 : %s" % (corpus or "(未指定，跳过源码比对)"))
    print("Python %s / SQLite %s / FTS5 %s"
          % (sys.version.split()[0], sqlite3.sqlite_version,
             "可用" if S._has_fts(S._connect(db)) else "不可用" if os.path.isfile(db) else "未知"))

    t0 = time.time()
    if check_index(db) is None:
        return 1
    check_ground_truth(db, corpus)
    check_query_parsing()
    check_channels(db)
    check_fusion(db)
    check_output(db)
    check_negative(db)
    check_robustness(db)
    check_fallback(db)
    check_performance(db, perf_queries)
    check_prefetch(db)
    check_end_to_end()

    failed = [r for r in RESULTS if not r["ok"]]
    skipped = [r for r in RESULTS if r.get("skipped")]
    print("\n" + "=" * 72)
    print("结果：%d 项通过 / %d 项失败 / %d 项跳过，耗时 %.1fs"
          % (len(RESULTS) - len(failed) - len(skipped), len(failed), len(skipped), time.time() - t0))
    if failed:
        for r in failed:
            print("  ✗ [%s] %s  %s" % (r["group"], r["name"], r["detail"]))
    print("=" * 72)
    return 1 if failed else 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="SELinux 知识库检索自检")
    ap.add_argument("--db", default=os.environ.get("SELINUX_KB_PATH") or S.default_db_path())
    ap.add_argument("--corpus", default=os.environ.get("SELINUX_CORPUS", ""))
    ap.add_argument("--json", default="", help="把结果另存为 JSON")
    ap.add_argument("--perf-queries", type=int, default=100)
    args = ap.parse_args(argv)

    corpus = args.corpus or default_corpus(args.db)
    code = run_all(args.db, corpus, max(10, args.perf_queries))

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"db": args.db, "corpus": corpus, "exit_code": code,
                       "results": RESULTS}, fh, ensure_ascii=False, indent=2)
        print("结果已写入 %s" % args.json)
    return code


if __name__ == "__main__":
    sys.exit(main())
