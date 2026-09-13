# -*- coding: utf-8 -*-
"""SELinux 语料解析器。

把三类语料解析成结构化记录，供索引与检索使用：
  1. refpolicy —— .te / .if / .fc / .spt / policy 配置文件 / doc / man
  2. selinux-notebook —— 章节 Markdown（含术语表）
  3. selinux.wiki —— 工具清单、排错指南等

仅依赖标准库，兼容 Python 3.8+，macOS 与 Linux 行为一致。
所有 path 字段统一使用相对路径 + "/" 分隔符，便于跨机器搬运索引。

记录结构：
  chunk  = {kind, module, source, path, line, title, text}
  symbol = {name, kind, module, source, path, line, summary}
  rule   = {rule_type, src, tgt, tclass, perms, cond, module, source, path, line}
  fctx   = {pattern, ftype, context_type, module, source, path, line}
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

MAX_CHUNK_CHARS = 3600


# ────────────────────────────── 基础工具 ──────────────────────────────


def read_text(path: str) -> str:
    """读取文本文件，编码异常时用替换字符兜底，绝不抛错。"""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def rel_path(path: str, root: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


_TAG_RE = re.compile(r"</?(?:summary|desc|p|param|name|function)\b[^>]*>", re.I)
_PARAM_RE = re.compile(r'<param\s+name="([^"]+)"\s*>(.*?)</param>', re.S | re.I)
_INNER_SUMMARY_RE = re.compile(r"<summary>(.*?)</summary>", re.S | re.I)
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,63}")


def clean_doc(lines: List[str]) -> str:
    """把 ## 文档注释清理成单行纯文本（去掉 XML 标签）。"""
    parts = []
    for raw in lines:
        s = raw.strip()
        if s.startswith("#"):
            s = s.lstrip("#").strip()
        if s:
            parts.append(s)
    text = _TAG_RE.sub(" ", " ".join(parts))
    return re.sub(r"\s+", " ", text).strip()


def raw_doc_lines_before(lines: List[str], idx: int) -> List[str]:
    """返回紧邻第 idx 行之前连续的 ## 注释行（保持原顺序）。

    refpolicy 里常用一个单独的 "#" 行把文档块与声明隔开，例如::

        ## <summary>Read user httpd content.</summary>
        #
        interface(`apache_read_user_content',`

    因此这里最多跳过 2 个空行或孤立 "#" 分隔行。
    """
    i = idx - 1
    skipped = 0
    while i >= 0 and skipped < 2 and lines[i].strip() in ("", "#"):
        i -= 1
        skipped += 1
    buf: List[str] = []
    while i >= 0 and lines[i].strip().startswith("##"):
        buf.append(lines[i])
        i -= 1
    buf.reverse()
    return buf


def doc_before(lines: List[str], idx: int) -> str:
    return clean_doc(raw_doc_lines_before(lines, idx))


def extract_params(doc_lines: List[str]) -> List[Tuple[str, str]]:
    """从 ## 注释里抽取 <param name="x"><summary>..</summary></param>。"""
    # 先去掉每行开头的 ## 标记，否则参数说明里会残留 "##"
    text = "\n".join(re.sub(r"^\s*##[ \t]?", "", ln) for ln in doc_lines)
    out: List[Tuple[str, str]] = []
    for m in _PARAM_RE.finditer(text):
        inner = m.group(2)
        sm = _INNER_SUMMARY_RE.search(inner)
        desc = clean_doc([sm.group(1)]) if sm else clean_doc([inner])
        out.append((m.group(1).strip(), desc))
    return out


def symbol_hints(text: str, limit: int = 60) -> List[str]:
    """抽取文本里出现的带下划线的标识符，用于辅助展示（不参与 FTS 打分）。"""
    seen: List[str] = []
    have = set()
    for m in _WORD_RE.finditer(text):
        w = m.group(0)
        if "_" not in w or w in have:
            continue
        have.add(w)
        seen.append(w)
        if len(seen) >= limit:
            break
    return seen


def split_long(text: str, start_line: int, max_chars: int = MAX_CHUNK_CHARS) -> List[Tuple[str, int]]:
    """按空行分段，把过长文本切成多块。返回 [(文本, 起始行号)]。"""
    if len(text) <= max_chars:
        return [(text, start_line)]
    pieces: List[Tuple[str, int]] = []
    buf: List[str] = []
    size = 0
    cur_off = start_line
    for para in text.split("\n\n"):
        plen = len(para) + 2
        if buf and size + plen > max_chars:
            joined = "\n\n".join(buf)
            pieces.append((joined, cur_off))
            cur_off += joined.count("\n") + 2
            buf = []
            size = 0
        buf.append(para)
        size += plen
    if buf:
        pieces.append(("\n\n".join(buf), cur_off))
    return pieces


def _chunk(kind: str, source: str, path: str, line: int, title: str,
           text: str, module: Optional[str] = None) -> Dict[str, Any]:
    return {
        "kind": kind,
        "module": module,
        "source": source,
        "path": path,
        "line": line,
        "title": title,
        "text": text,
        "symbols": " ".join(symbol_hints(text)),
    }


# ───────────────────────────── refpolicy: .te ─────────────────────────────

# refpolicy 段头形如：
#   ########################################
#   #
#   # Declarations
#   #
SECTION_HDR_RE = re.compile(
    r"^#{4,}[ \t]*\n#[ \t]*\n#[ \t]*(?P<name>[^\n]+?)[ \t]*\n#[ \t]*$",
    re.MULTILINE,
)

# m4 块起始：行尾以反引号开启（tunable_policy(`x',` / gen_require(` / interface(`x',`）
BLOCK_OPEN_RE = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*\(.*`\s*$")
BLOCK_CLOSE_RE = re.compile(r"^\s*'\s*\)")
COND_RE = re.compile(
    r"^\s*(tunable_policy|optional_policy|booleanif|ifdef|ifndef)\s*\(\s*`?([^`',)]*)"
)

# 标识符里允许 $ 与数字：模板中会出现 httpd_$1_script_t 这类名字，
# 若字符集不含 $，allow_httpd_$1_script_anon_write 会被截断成 allow_httpd_
DECL_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("type", re.compile(r"^\s*type\s+([A-Za-z0-9_$]+)")),
    ("attribute", re.compile(r"^\s*(?:attribute|typeattribute)\s+([A-Za-z0-9_$]+)")),
    ("tunable", re.compile(r"^\s*gen_tunable\(\s*`?([A-Za-z0-9_$]+)")),
    ("bool", re.compile(r"^\s*gen_bool\(\s*`?([A-Za-z0-9_$]+)")),
    ("tunable", re.compile(r"^\s*tunable\s+([A-Za-z0-9_$]+)\s+(?:true|false)")),
    ("bool", re.compile(r"^\s*bool\s+([A-Za-z0-9_$]+)\s+(?:true|false)")),
    ("class", re.compile(r"^\s*class\s+([A-Za-z0-9_$]+)")),
    ("role", re.compile(r"^\s*role\s+([A-Za-z0-9_$]+)")),
]

RULE_KINDS = (
    "allow", "dontaudit", "auditallow", "neverallow",
    "type_transition", "type_change", "type_member",
    "role_transition", "range_transition",
    "allowxperm", "auditallowxperm", "dontauditxperm",
)
RULE_START_RE = re.compile(r"^\s*(" + "|".join(RULE_KINDS) + r")\s+(.*)$")
RULE_BODY_RE = re.compile(r"^(\S+)\s+(\S+?)\s*:\s*(\S+)\s+(.+)$")


def _norm_perms(raw: str) -> str:
    raw = raw.strip().rstrip(";").strip()
    if raw.startswith("{"):
        raw = raw.strip("{}").strip()
    return re.sub(r"\s+", " ", raw)


def make_rule(rule_type: str, body: str, module: Optional[str], source: str,
              path: str, line: int, cond: Optional[str]) -> Optional[Dict[str, Any]]:
    """把一条规则语句解析成结构化记录；无法解析时返回 None。"""
    body = body.strip().rstrip(";").strip()
    m = RULE_BODY_RE.match(body)
    if not m:
        return None
    src, tgt, tclass, perms = m.group(1), m.group(2), m.group(3), m.group(4)
    return {
        "rule_type": rule_type,
        "src": src,
        "tgt": tgt,
        "tclass": tclass,
        "perms": _norm_perms(perms),
        "cond": cond or None,
        "module": module,
        "source": source,
        "path": path,
        "line": line,
    }


def te_sections(text: str) -> List[Tuple[str, int, int]]:
    """按 refpolicy 的 ###### 段头切分，返回 [(段名, 起始行, 结束行)]（1-based，含头不含尾）。"""
    total_lines = text.count("\n") + (0 if text.endswith("\n") else 1)
    marks: List[Tuple[str, int, int]] = []
    for m in SECTION_HDR_RE.finditer(text):
        start = text.count("\n", 0, m.start()) + 1
        end = text.count("\n", 0, m.end()) + 1
        marks.append((m.group("name").strip(), start, end))
    if not marks:
        return [("", 1, total_lines + 1)]
    out: List[Tuple[str, int, int]] = []
    if marks[0][1] > 1:
        out.append(("", 1, marks[0][1]))
    for i, (name, _s, end) in enumerate(marks):
        nxt = marks[i + 1][1] if i + 1 < len(marks) else total_lines + 1
        body_start = end + 1 if end + 1 <= nxt else end
        out.append((name, body_start, nxt))
    return out


def find_block_end(lines: List[str], decl_line: int) -> int:
    """给定 m4 块起始行（1-based），返回块结束行（1-based，含）。

    需要按嵌套深度匹配，否则 interface()/define() 里第一个 gen_require() 的
    结束行 ' 就会被误判成整个块的结束。
    """
    decl = lines[decl_line - 1].rstrip()
    if decl.endswith("')"):          # 单行块，如 define(`x', `{ a b }')
        return decl_line
    depth = 1
    for idx in range(decl_line, len(lines)):     # 0-based，指向起始行的下一行
        s = lines[idx].strip()
        if not s:
            continue
        if BLOCK_CLOSE_RE.match(s):
            depth -= 1
            if depth == 0:
                return idx + 1
        elif BLOCK_OPEN_RE.match(s):
            depth += 1
    return len(lines)


def _scan_statements(lines: List[str], start_idx: int, end_idx: int,
                     module: Optional[str], source: str, path: str,
                     base_line: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], bool]:
    """在 lines[start_idx:end_idx] 内扫描符号声明与规则。

    base_line 为 start_idx 对应的真实行号（1-based）。
    返回 (symbols, rules, balanced)：balanced=False 表示条件块括号不平衡，
    此时该片段内的规则不标注 cond，避免给出错误的启用条件。
    """
    symbols: List[Dict[str, Any]] = []
    rules: List[Dict[str, Any]] = []
    stack: List[Optional[str]] = []
    pending: Optional[Tuple[str, str, int]] = None

    for offset, raw in enumerate(lines[start_idx:end_idx]):
        lineno = base_line + offset
        stripped = raw.strip()

        if not stripped or stripped.startswith("#"):
            continue

        if BLOCK_CLOSE_RE.match(stripped):
            if stack:
                stack.pop()
            continue

        if pending is not None:
            pkind, pbody, pline = pending
            pbody = pbody + " " + stripped
            if stripped.endswith(";"):
                rec = make_rule(pkind, pbody, module, source, path, pline,
                                None if not stack else stack[-1])
                if rec:
                    rules.append(rec)
                pending = None
            else:
                pending = (pkind, pbody, pline)
            continue

        if BLOCK_OPEN_RE.match(raw):
            cm = COND_RE.match(raw)
            stack.append(cm.group(2).strip() if cm else None)
            continue

        declared = False
        for kind, pat in DECL_PATTERNS:
            dm = pat.match(raw)
            if dm:
                symbols.append({
                    "name": dm.group(1),
                    "kind": kind,
                    "module": module,
                    "source": source,
                    "path": path,
                    "line": lineno,
                    "summary": doc_before(lines, start_idx + offset),
                })
                declared = True
                break
        if declared:
            continue

        rm = RULE_START_RE.match(raw)
        if rm:
            rkind, rbody = rm.group(1), rm.group(2)
            if stripped.endswith(";"):
                rec = make_rule(rkind, rbody, module, source, path, lineno,
                                None if not stack else stack[-1])
                if rec:
                    rules.append(rec)
            else:
                pending = (rkind, rbody, lineno)
            continue

    balanced = not stack and pending is None
    return symbols, rules, balanced


def parse_te(path: str, relpath: str, module: str,
             source: str = "refpolicy") -> Tuple[List[Dict], List[Dict], List[Dict], bool]:
    """解析一个 .te 文件。返回 (chunks, symbols, rules, balanced)。"""
    text = read_text(path)
    lines = text.splitlines()
    chunks: List[Dict] = []

    for sec_name, start, end in te_sections(text):
        body = "\n".join(lines[start - 1:end - 1]).strip("\n")
        if not body.strip():
            continue
        title = "%s: %s" % (module, sec_name) if sec_name else ("%s (声明)" % module)
        for piece, off in split_long(body, start):
            chunks.append(_chunk("te_section", source, relpath, off, title, piece, module))

    symbols, rules, balanced = _scan_statements(
        lines, 0, len(lines), module, source, relpath, 1)

    if not balanced:
        # 兜底策略：条件块解析不可靠时，丢弃 cond，只保留"存在该规则"这一确凿事实
        for r in rules:
            r["cond"] = None

    return chunks, symbols, rules, balanced


# ───────────────────────────── refpolicy: .if ─────────────────────────────

IF_OPEN_RE = re.compile(r"^\s*(interface|template)\(\s*`([A-Za-z0-9_]+)'", re.M)


def parse_if(path: str, relpath: str, module: str,
             source: str = "refpolicy") -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """解析 .if 文件：每个 interface()/template() 一块。"""
    text = read_text(path)
    lines = text.splitlines()
    chunks: List[Dict] = []
    symbols: List[Dict] = []
    rules: List[Dict] = []

    file_summary = ""
    for i, raw in enumerate(lines[:5]):
        if "<summary>" in raw:
            file_summary = doc_before(lines, i + 1)
            break

    matches = list(IF_OPEN_RE.finditer(text))
    for m in matches:
        kind = m.group(1)
        name = m.group(2)
        start = text.count("\n", 0, m.start()) + 1          # 1-based
        end = find_block_end(lines, start)

        idx0 = start - 1
        doc_lines = raw_doc_lines_before(lines, idx0)
        summary = clean_doc(doc_lines)
        params = extract_params(doc_lines)
        body = "\n".join(lines[idx0:end])

        header = summary or (file_summary or ("%s 的 %s" % (module, kind)))
        if params:
            header += "  参数: " + "; ".join("%s=%s" % (n, d) for n, d in params)

        chunk_text = header + "\n" + body
        for piece, off in split_long(chunk_text, start):
            chunks.append(_chunk(kind, source, relpath, off, name, piece, module))

        symbols.append({
            "name": name,
            "kind": kind,
            "module": module,
            "source": source,
            "path": relpath,
            "line": start,
            "summary": summary or file_summary,
        })

        sub_symbols, sub_rules, _bal = _scan_statements(
            lines, idx0, end, module, source, relpath, start)
        symbols.extend([s for s in sub_symbols if s["name"] != name])
        rules.extend(sub_rules)

    return chunks, symbols, rules


# ───────────────────────────── refpolicy: .fc ─────────────────────────────

FC_RE = re.compile(r"^(?P<pat>[^#\s]\S*)(?:\s+(?P<ftype>-[bcdflps]*))?\s+(?P<ctx>\S+)\s*$")
CTX_ROLE_RE = re.compile(r"(?:object_r|system_r):([A-Za-z0-9_]+)")


def _context_type(ctx: str) -> Optional[str]:
    if ctx.startswith("<<"):
        return None
    m = CTX_ROLE_RE.search(ctx)
    if m:
        return m.group(1)
    for part in ctx.split(":"):
        if part.endswith("_t") or part.endswith("_type"):
            return part
    return None


def parse_fc(path: str, relpath: str, module: str,
             source: str = "refpolicy") -> Tuple[List[Dict], List[Dict]]:
    """解析 .fc 文件：路径模式 → 安全上下文类型。"""
    lines = read_text(path).splitlines()
    fctxs: List[Dict] = []
    by_type: Dict[str, List[str]] = {}
    pending = ""

    for i, raw in enumerate(lines, 1):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.endswith("\\"):
            pending += line[:-1]
            continue
        line = pending + line
        pending = ""
        m = FC_RE.match(line)
        if not m:
            continue
        ctype = _context_type(m.group("ctx"))
        fctxs.append({
            "pattern": m.group("pat"),
            "ftype": m.group("ftype") or "",
            "context_type": ctype,
            "module": module,
            "source": source,
            "path": relpath,
            "line": i,
        })
        by_type.setdefault(ctype or "<<none>>", []).append(
            "%s\t%s" % (m.group("pat"), line.split(None, 1)[-1].strip()))

    chunks: List[Dict] = []
    for ctype, rows in by_type.items():
        text = "%s 的文件上下文（%s）：\n%s" % (module, ctype, "\n".join(sorted(rows)))
        for piece, off in split_long(text, 1):
            chunks.append(_chunk("file_context", source, relpath, off,
                                 "%s → %s" % (module, ctype), piece, module))
    return chunks, fctxs


# ─────────────────────── refpolicy: .spt 支持宏 ───────────────────────

SPT_DEF_RE = re.compile(r"^\s*(?:define|interface|template)\(\s*`([A-Za-z0-9_]+)'", re.M)


def parse_spt(path: str, relpath: str, source: str = "refpolicy") -> Tuple[List[Dict], List[Dict]]:
    """解析 policy/support/*.spt：define(`name',`...`') 形式的宏与权限集合。"""
    text = read_text(path)
    lines = text.splitlines()
    chunks: List[Dict] = []
    symbols: List[Dict] = []

    for m in SPT_DEF_RE.finditer(text):
        name = m.group(1)
        start = text.count("\n", 0, m.start()) + 1
        end = find_block_end(lines, start)

        # 宏上方的普通 # 注释即其文档
        doc_lines: List[str] = []
        i = start - 2
        while i >= 0:
            s = lines[i].strip()
            if s.startswith("#") and not s.startswith("#!"):
                doc_lines.append(s.lstrip("#").strip())
                i -= 1
                continue
            if not s:
                i -= 1
                continue
            break
        doc_lines.reverse()
        summary = re.sub(r"\s+", " ", " ".join(doc_lines)).strip()

        body = "\n".join(lines[start - 1:end])
        chunk_text = (summary + "\n" if summary else "") + body
        for piece, off in split_long(chunk_text, start):
            chunks.append(_chunk("macro", source, relpath, off, name, piece, None))

        kind = "permission_set" if name.endswith("_perms") or name.endswith("_set") else "macro"
        symbols.append({
            "name": name,
            "kind": kind,
            "module": None,
            "source": source,
            "path": relpath,
            "line": start,
            "summary": summary,
        })

    return chunks, symbols


# ─────────────────── refpolicy: flask 类与权限定义 ───────────────────

AV_BLOCK_RE = re.compile(
    r"^(common|class)\s+([A-Za-z0-9_]+)\s*\n(?:inherits\s+([A-Za-z0-9_]+)\s*\n)?\{(.*?)\n\}",
    re.M | re.S,
)


def parse_access_vectors(path: str, relpath: str,
                         source: str = "refpolicy") -> Tuple[List[Dict], List[Dict]]:
    """解析 policy/flask/access_vectors：对象类 → 权限集合。"""
    text = read_text(path)
    chunks: List[Dict] = []
    symbols: List[Dict] = []

    for m in AV_BLOCK_RE.finditer(text):
        btype, name, parent, body = m.group(1), m.group(2), m.group(3), m.group(4)
        perms = [p.strip() for p in re.split(r"[\s]+", body) if p.strip()]
        kind = "common_class" if btype == "common" else "object_class"
        summary = "对象类 %s 的权限（共 %d 个）" % (name, len(perms))
        if parent:
            summary += "，继承自 %s" % parent
        summary += ": " + ", ".join(perms)
        start = text.count("\n", 0, m.start()) + 1
        chunks.append(_chunk(kind, source, relpath, start, "class %s" % name, summary, None))
        symbols.append({
            "name": name,
            "kind": kind,
            "module": None,
            "source": source,
            "path": relpath,
            "line": start,
            "summary": summary,
        })
    return chunks, symbols


# ─────────────────────── 通用：Markdown / man / creole ───────────────────────

MD_HEAD_RE = re.compile(r"^(#{1,3})[ \t]+(.+?)[ \t]*$", re.M)
ROFF_SH_RE = re.compile(r"^\.SH[ \t]+(.*)$", re.M)
ROFF_MACRO_RE = re.compile(r"^\.[A-Za-z]{1,2}([ \t].*)?$")
CREOLE_HEAD_RE = re.compile(r"^(={1,3})[ \t]*(.+?)[ \t]*=*[ \t]*$", re.M)


def parse_markdown(path: str, relpath: str, source: str, kind: str = "doc",
                   prefix: str = "") -> List[Dict]:
    """按 1~3 级标题切分 Markdown。"""
    text = read_text(path)
    lines = text.splitlines()
    heads = [(text.count("\n", 0, m.start()) + 1, len(m.group(1)), m.group(2).strip())
             for m in MD_HEAD_RE.finditer(text)]
    if not heads:
        body = text.strip()
        return [_chunk(kind, source, relpath, 1, prefix or relpath, body)] if body else []

    chunks: List[Dict] = []
    h1 = ""
    for i, (line_no, level, title) in enumerate(heads):
        if level == 1:
            h1 = title
        end = heads[i + 1][0] if i + 1 < len(heads) else len(lines) + 1
        body = "\n".join(lines[line_no - 1:end - 1]).strip()
        if not body:
            continue
        if prefix:
            full_title = "%s / %s" % (prefix, title)
        elif level > 1 and h1:
            full_title = "%s / %s" % (h1, title)
        else:
            full_title = title
        for piece, off in split_long(body, line_no):
            chunks.append(_chunk(kind, source, relpath, off, full_title, piece, None))
    return chunks


def parse_man(path: str, relpath: str, source: str = "refpolicy") -> List[Dict]:
    """解析 roff man 页面，按 .SH 分节。"""
    text = read_text(path)
    lines = text.splitlines()
    heads = [(text.count("\n", 0, m.start()) + 1, m.group(1).strip().strip('"'))
             for m in ROFF_SH_RE.finditer(text)]
    if not heads:
        heads = [(1, relpath)]

    chunks: List[Dict] = []
    for i, (line_no, title) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else len(lines) + 1
        buf = []
        for raw in lines[line_no - 1:end - 1]:
            if ROFF_MACRO_RE.match(raw):
                continue
            s = raw.strip()
            if s:
                buf.append(s)
        body = "\n".join(buf)
        if not body:
            continue
        for piece, off in split_long(body, line_no):
            chunks.append(_chunk("man", source, relpath, off,
                                 "%s / %s" % (relpath, title), piece, None))
    return chunks


def parse_creole(path: str, relpath: str, source: str = "wiki") -> List[Dict]:
    """解析 creole 文本，按 = 标题分节。"""
    text = read_text(path)
    lines = text.splitlines()
    heads = [(text.count("\n", 0, m.start()) + 1, m.group(2).strip())
             for m in CREOLE_HEAD_RE.finditer(text) if m.group(2).strip()]
    if not heads:
        heads = [(1, relpath)]

    chunks: List[Dict] = []
    for i, (line_no, title) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else len(lines) + 1
        body = "\n".join(lines[line_no - 1:end - 1]).strip()
        if not body:
            continue
        for piece, off in split_long(body, line_no):
            chunks.append(_chunk("wiki", source, relpath, off, title, piece, None))
    return chunks


# ───────────────────────────── 术语表 ─────────────────────────────

TERM_RE = re.compile(r"^\*\*(?P<name>[^*\n]{1,80})\*\*[ \t]*$", re.M)


def parse_terminology(path: str, relpath: str, source: str) -> Tuple[List[Dict], List[Dict]]:
    """解析 notebook 的 terminology.md：**缩写** 换行 定义。"""
    text = read_text(path)
    lines = text.splitlines()
    chunks: List[Dict] = []
    symbols: List[Dict] = []

    for m in TERM_RE.finditer(text):
        name = m.group("name").strip()
        line_no = text.count("\n", 0, m.start()) + 1
        idx = line_no
        buf: List[str] = []
        while idx < len(lines):
            s = lines[idx].strip()
            if not s:
                if buf:
                    break
                idx += 1
                continue
            if TERM_RE.match(lines[idx]):
                break
            buf.append(s)
            idx += 1
        desc = re.sub(r"\s+", " ", " ".join(buf)).strip()
        if not desc:
            continue
        symbols.append({
            "name": name,
            "kind": "term",
            "module": None,
            "source": source,
            "path": relpath,
            "line": line_no,
            "summary": desc,
        })
        chunks.append(_chunk("glossary", source, relpath, line_no,
                             "术语 %s" % name, "%s: %s" % (name, desc), None))
    return chunks, symbols


# ─────────────────────────── 通用目录遍历 ───────────────────────────


def walk_files(root: str, suffixes: Tuple[str, ...],
               skip_dirs: Tuple[str, ...] = (".git", "node_modules", "images")) -> List[str]:
    out: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for fn in filenames:
            if fn.startswith("."):
                continue
            if suffixes and not fn.endswith(suffixes):
                continue
            out.append(os.path.join(dirpath, fn))
    return sorted(out)
