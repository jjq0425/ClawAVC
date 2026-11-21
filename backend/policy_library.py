# -*- coding: utf-8 -*-
"""指定策略库：解析、评估与编辑场景 .te 源码。

为什么需要它
------------
目标机的已加载 SELinux 策略在很多环境里拿不到（容器、离线评审、只拿到采集
Round 的机器）。这时策略建议改为围绕一份**可审查的场景策略库**进行：库里每个
场景是一份 refpolicy 风格 .te 源码 + .fc 路径映射 + 任务要求。模型读源码、回答
访问探测、提交 allow 规则的增/删/改，全部在本地确定性完成，不依赖 seinfo /
sesearch / checkmodule。

核心语义（与 real SELinux 保持一致的部分）
------------------------------------------
* 授权关系是 allow 规则的**并集**：同一 (src, tgt, class) 的多条规则叠加，
  只改一条、删一条可能仍然被另一条授予。apply_edits 之后会重新解析并评估，
  用来发现这种「改了等于没改」的情况。
* 类型属性（attribute / typeattributeset）会展开后再判断来源与客体。
* .fc 按最长字面前缀匹配，和 matchpathcon 的选择规则一致。

安全约束
--------
本模块只读文件、只在内存里重写源码字符串；不写回磁盘、不执行 semanage /
restorecon / checkmodule。所有改动都作为文本交给人工复核。
"""

from __future__ import annotations

import copy
import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CLASS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CONTEXT_RE = re.compile(r"gen_context\(\s*([^)]+)\)")
_REGEX_META = re.compile(r"[()\[\]{}.*+?|^$\\]")


# ═══════════════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════════════


@dataclass
class Rule:
    line: int
    raw: str
    src: str
    tgt: str
    tclass: str
    perms: Tuple[str, ...]

    @property
    def text(self) -> str:
        return render_rule(self.src, self.tgt, self.tclass, self.perms)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "line": self.line,
            "raw": self.raw.strip(),
            "text": self.text,
            "src": self.src,
            "tgt": self.tgt,
            "tclass": self.tclass,
            "perms": list(self.perms),
        }


@dataclass
class FileContext:
    pattern: str
    regex: "re.Pattern[str]"
    type: str
    prefix_len: int
    raw: str

    def as_dict(self) -> Dict[str, Any]:
        return {"pattern": self.pattern, "type": self.type}


@dataclass
class ParsedPolicy:
    rules: List[Rule] = field(default_factory=list)
    types: Dict[str, str] = field(default_factory=dict)          # name -> "type"
    attributes: Dict[str, List[str]] = field(default_factory=dict)  # attr -> members
    errors: List[str] = field(default_factory=list)


@dataclass
class Scene:
    name: str
    title: str
    task: str
    subject: str
    source: str
    rules: List[Rule]
    types: Dict[str, str]
    attributes: Dict[str, List[str]]
    file_contexts: List[FileContext]
    tests: List[Dict[str, Any]]
    sensitive_targets: List[str] = field(default_factory=list)
    actual_labels: Dict[str, str] = field(default_factory=dict)
    policy_path: str = ""
    fc_path: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    # ── 基础查询 ──────────────────────────────────────────────
    def is_attribute(self, name: str) -> bool:
        return name in self.attributes

    def members_of(self, name: str, _seen: Optional[set] = None) -> set:
        if name not in self.attributes:
            return {name}
        seen = set(_seen or ())
        if name in seen:
            return set()
        seen.add(name)
        out = {name}
        for member in self.attributes.get(name, []):
            out |= self.members_of(member, seen)
        return out

    def rule_sources(self, rule: Rule) -> set:
        return self.members_of(rule.src)

    def rule_targets(self, rule: Rule) -> set:
        if rule.tgt == "self":
            return self.members_of(rule.src)
        return self.members_of(rule.tgt)

    def effective_perms(self, subject: str, target_type: str, tclass: str) -> set:
        perms: set = set()
        for rule in self.rules:
            if rule.tclass != tclass:
                continue
            if subject not in self.rule_sources(rule):
                continue
            if target_type not in self.rule_targets(rule):
                continue
            perms |= set(rule.perms)
        return perms

    def matching_rules(self, subject: str, target_type: str, tclass: str) -> List[Rule]:
        out: List[Rule] = []
        for rule in self.rules:
            if rule.tclass != tclass:
                continue
            if subject not in self.rule_sources(rule):
                continue
            if target_type not in self.rule_targets(rule):
                continue
            out.append(rule)
        return out

    # ── 对外快照 ──────────────────────────────────────────────
    def as_dict(self, include_source: bool = True) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "name": self.name,
            "title": self.title,
            "task": self.task,
            "subject": self.subject,
            "types": sorted(self.types),
            "attributes": {k: sorted(v) for k, v in sorted(self.attributes.items())},
            "file_contexts": [fc.as_dict() for fc in self.file_contexts],
            "tests": self.tests,
            "sensitive_targets": sorted(self.sensitive_targets),
            "actual_labels": dict(sorted(self.actual_labels.items())),
            "rules": [r.as_dict() for r in self.rules],
            "audit": self.policy_audit(),
            "errors": self.errors,
        }
        if include_source:
            out["source"] = self.source
        return out

    def policy_audit(self) -> List[Dict[str, Any]]:
        """按任务测试核查当前策略，只返回不一致项（与参考的 policy_audit 同义）。"""
        result = evaluate_tests(self, self.tests)
        audit: List[Dict[str, Any]] = []
        for check in result["checks"]:
            if check["passed"]:
                continue
            if check.get("kind") == "label":
                audit.append({
                    "operation": check["name"],
                    "target_type": check["target"],
                    "class": check["class"],
                    "permissions": [],
                    "path": check.get("path", ""),
                    "current": check["actual"],
                    "required": check["expected"],
                    "missing_permissions": [],
                })
                continue
            expected = bool(check["expected"])
            entry = {
                "operation": check["name"],
                "target_type": check["target"],
                "class": check["class"],
                "permissions": list(check["permissions"]),
                "current": "允许" if check["actual"] else (
                    "部分缺失" if check["covered_permissions"] else "缺少授权"),
                "required": "允许" if expected else "禁止",
                "missing_permissions": check["missing_permissions"],
            }
            if not expected and check["actual"]:
                entry["current"] = "已允许（应收敛）"
                entry["excess_permissions"] = check["covered_permissions"]
            audit.append(entry)
        return audit

    def summary(self) -> Dict[str, Any]:
        result = evaluate_tests(self, self.tests)
        return {
            "scene": self.name,
            "subject": self.subject,
            "rule_count": len(self.rules),
            "tests_passed": result["passed"],
            "tests_total": result["total"],
            "fully_correct": result["fully_correct"],
        }


@dataclass
class Library:
    root: Path
    scenes: Dict[str, Scene]
    default_scene: str = ""
    errors: List[str] = field(default_factory=list)

    def names(self) -> List[str]:
        return sorted(self.scenes)

    def get(self, name: str) -> Optional[Scene]:
        if not name:
            name = self.default_scene
        return self.scenes.get(name or "")

    def list_public(self) -> List[Dict[str, Any]]:
        out = []
        for name in self.names():
            scene = self.scenes[name]
            out.append({
                "name": scene.name,
                "title": scene.title,
                "task": scene.task,
                "subject": scene.subject,
                "test_count": len(scene.tests),
                "rule_count": len(scene.rules),
                "is_default": scene.name == self.default_scene,
            })
        return out


# ═══════════════════════════════════════════════════════════════════
# 解析
# ═══════════════════════════════════════════════════════════════════


def _strip_comment(line: str) -> str:
    idx = line.find("#")
    return line[:idx] if idx >= 0 else line


def normalize_rule_text(text: str) -> str:
    """把一条 allow 规则归一化成可比较的 token 串（容忍空白与标点差异）。"""
    cleaned = _strip_comment(str(text or "")).strip()
    tokens = re.findall(r"\{|\}|:|;|[^\s{}:;]+", cleaned)
    return " ".join(tokens)


def parse_rule_text(text: str, line: int = 0, raw: str = "") -> Tuple[Optional[Rule], str]:
    """解析单行 allow 规则；失败返回 (None, 错误说明)。"""
    cleaned = _strip_comment(str(text or "")).strip()
    m = re.match(
        r"^allow\s+([A-Za-z_][A-Za-z0-9_]*)\s+"
        r"([A-Za-z_][A-Za-z0-9_]*|self)\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\s+"
        r"(?:\{\s*([^}]*)\s*\}|([A-Za-z_][A-Za-z0-9_]*))\s*;$",
        cleaned,
    )
    if not m:
        return None, "不是合法的单行 allow 规则：%r" % cleaned[:160]
    src, tgt, tclass = m.group(1), m.group(2), m.group(3)
    raw_perms = m.group(4) if m.group(4) is not None else m.group(5)
    perms = sorted({p for p in re.split(r"[\s,]+", str(raw_perms or "")) if p})
    if not perms:
        return None, "allow 规则的权限集为空：%r" % cleaned[:160]
    bad = [p for p in perms if not IDENT_RE.match(p)]
    if bad:
        return None, "非法权限名：%s" % ", ".join(bad)
    return Rule(line=line, raw=raw or cleaned, src=src, tgt=tgt,
                tclass=tclass, perms=tuple(perms)), ""


def render_rule(src: str, tgt: str, tclass: str, perms: Iterable[str]) -> str:
    ordered = sorted({str(p).strip() for p in perms if str(p).strip()})
    return "allow %s %s:%s { %s };" % (src, tgt, tclass, " ".join(ordered))


def parse_policy(source: str) -> ParsedPolicy:
    """解析 .te 源码里的类型声明、属性与 allow 规则。"""
    parsed = ParsedPolicy()
    for lineno, line in enumerate(str(source or "").splitlines(), 1):
        cleaned = _strip_comment(line).strip()
        if not cleaned:
            continue

        if cleaned.startswith("allow "):
            rule, err = parse_rule_text(cleaned, line=lineno, raw=line)
            if rule is None:
                parsed.errors.append("第 %d 行：%s" % (lineno, err))
            else:
                parsed.rules.append(rule)
            continue

        m = re.match(r"^attribute\s+([A-Za-z_][A-Za-z0-9_]*)\s*;$", cleaned)
        if m:
            parsed.attributes.setdefault(m.group(1), [])
            continue

        m = re.match(r"^type\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:,\s*([^;]+))?;$", cleaned)
        if m:
            parsed.types.setdefault(m.group(1), "type")
            for attr in re.split(r"[\s,]+", m.group(2) or ""):
                if attr and IDENT_RE.match(attr):
                    parsed.attributes.setdefault(attr, []).append(m.group(1))
            continue

        m = re.match(r"^typeattribute\s+([A-Za-z_][A-Za-z0-9_]*)\s+"
                     r"([A-Za-z_][A-Za-z0-9_]*)\s*;$", cleaned)
        if m:
            parsed.attributes.setdefault(m.group(2), []).append(m.group(1))
            continue

        m = re.match(r"^typeattributeset\s+([A-Za-z_][A-Za-z0-9_]*)\s*"
                     r"(?:\((.*?)\)|\{(.*?)\}|([A-Za-z_][A-Za-z0-9_]*))\s*;$", cleaned)
        if m:
            attr = m.group(1)
            body = m.group(2) if m.group(2) is not None else (
                m.group(3) if m.group(3) is not None else m.group(4))
            members = re.split(r"[\s,]+", body or "")
            slot = parsed.attributes.setdefault(attr, [])
            for member in members:
                if member and IDENT_RE.match(member) and member not in slot:
                    slot.append(member)
            continue

    for attr, members in parsed.attributes.items():
        parsed.attributes[attr] = sorted(set(members))
    return parsed


def parse_file_contexts(text: str) -> List[FileContext]:
    """解析 .fc 文件，返回按最长字面前缀排序的匹配表。"""
    entries: List[FileContext] = []
    for line in str(text or "").splitlines():
        cleaned = _strip_comment(line).strip()
        if not cleaned:
            continue
        tokens = cleaned.split()
        if not tokens:
            continue
        pattern = tokens[0]
        if pattern.startswith("<<"):
            continue
        m = _CONTEXT_RE.search(cleaned)
        context = m.group(1) if m else tokens[-1]
        parts = [p.strip() for p in context.split(",")[0].split(":")]
        type_name = parts[2] if len(parts) >= 3 else ""
        if not type_name or type_name.startswith("<<") or not IDENT_RE.match(type_name):
            continue
        try:
            regex = re.compile(pattern)
        except re.error:
            continue
        meta = _REGEX_META.search(pattern)
        prefix_len = meta.start() if meta else len(pattern)
        entries.append(FileContext(pattern=pattern, regex=regex, type=type_name,
                                   prefix_len=prefix_len, raw=cleaned))
    entries.sort(key=lambda e: (e.prefix_len, len(e.pattern)), reverse=True)
    return entries


def resolve_type(scene: Scene, resource: str) -> Optional[Dict[str, Any]]:
    """按场景 .fc 把资源路径解析成 SELinux 类型（最长字面前缀优先）。"""
    path = str(resource or "")
    if not path.startswith("/"):
        return None
    for fc in scene.file_contexts:
        try:
            m = fc.regex.match(path)
        except Exception:
            continue
        if m and m.end() == len(path):
            return {
                "type": fc.type,
                "pattern": fc.pattern,
                "source": "policy_library.fc",
                "raw": fc.raw,
            }
    return None


def guess_subject(parsed: ParsedPolicy) -> str:
    """没有显式 subject 时，从规则来源里猜一个最常用的域。"""
    counts: Dict[str, int] = {}
    for rule in parsed.rules:
        counts[rule.src] = counts.get(rule.src, 0) + 1
    if not counts:
        return ""
    return sorted(counts, key=lambda name: (-counts[name], name))[0]


def scene_from_source(scene: Scene, source: str) -> Scene:
    """以既有场景的元信息为底，用新源码重建一个 Scene。"""
    parsed = parse_policy(source)
    updated = copy.copy(scene)
    updated.source = source
    updated.rules = parsed.rules
    updated.types = parsed.types
    updated.attributes = parsed.attributes
    updated.errors = list(parsed.errors)
    return updated


# ═══════════════════════════════════════════════════════════════════
# 加载场景库
# ═══════════════════════════════════════════════════════════════════


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _task_from_readme(path: Path) -> str:
    text = _read_text(path)
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return ""


def load_scene(root: Path, meta: Dict[str, Any]) -> Scene:
    name = str(meta.get("name") or "").strip()
    if not name:
        raise ValueError("场景缺少 name")
    policy_name = str(meta.get("policy") or (name + ".te")).strip()
    fc_name = str(meta.get("file_contexts") or (name + ".fc")).strip()
    policy_path = (root / policy_name).resolve()
    fc_path = (root / fc_name).resolve()

    source = _read_text(policy_path)
    parsed = parse_policy(source)
    subject = str(meta.get("subject") or "").strip() or guess_subject(parsed)
    task = str(meta.get("task") or "").strip()
    if not task:
        task = _task_from_readme(policy_path.with_name("README.md"))

    file_contexts = parse_file_contexts(_read_text(fc_path)) if fc_path.is_file() else []
    errors = list(parsed.errors)
    if not policy_path.is_file():
        errors.insert(0, "策略文件不存在：%s" % policy_path)
    if not fc_path.is_file():
        errors.append("文件上下文不存在：%s（路径→类型解析将不可用）" % fc_path)

    return Scene(
        name=name,
        title=str(meta.get("title") or name),
        task=task,
        subject=subject,
        source=source,
        rules=parsed.rules,
        types=parsed.types,
        attributes=parsed.attributes,
        file_contexts=file_contexts,
        tests=[t for t in (meta.get("tests") or []) if isinstance(t, dict)],
        sensitive_targets=[str(t) for t in (meta.get("sensitive_targets") or [])],
        actual_labels={str(k): str(v) for k, v in (meta.get("actual_labels") or {}).items()
                       if isinstance(k, str) and isinstance(v, str)},
        policy_path=str(policy_path),
        fc_path=str(fc_path),
        metadata=dict(meta),
        errors=errors,
    )


def load_library(library_dir: str) -> Library:
    """加载一个场景库目录。

    目录结构（最小）::

        library.json           # {"default": "...", "scenes": [ {...}, ... ]}
        <scene>.te
        <scene>.fc

    library.json 也可直接是一个场景数组。缺少 library.json 时按 ``*.te`` 发现场景。
    """
    root = Path(str(library_dir or "")).expanduser().resolve()
    library = Library(root=root, scenes={})
    if not root.is_dir():
        library.errors.append("策略库目录不存在：%s" % root)
        return library

    manifest = root / "library.json"
    metas: List[Dict[str, Any]] = []
    if manifest.is_file():
        try:
            raw = json.loads(_read_text(manifest) or "{}")
        except ValueError as exc:
            library.errors.append("library.json 解析失败：%s" % exc)
            raw = {}
        if isinstance(raw, list):
            metas = [m for m in raw if isinstance(m, dict)]
        elif isinstance(raw, dict):
            metas = [m for m in (raw.get("scenes") or []) if isinstance(m, dict)]
            library.default_scene = str(raw.get("default") or "").strip()
    if not metas:
        metas = [{"name": p.stem, "policy": p.name} for p in sorted(root.glob("*.te"))]
    if not metas:
        library.errors.append("策略库里没有 .te 场景：%s" % root)
        return library

    for meta in metas:
        try:
            scene = load_scene(root, meta)
        except Exception as exc:
            library.errors.append("场景加载失败（%s）：%s" % (meta.get("name") or "?", exc))
            continue
        if scene.name in library.scenes:
            library.errors.append("场景名重复：%s" % scene.name)
            continue
        library.scenes[scene.name] = scene

    if not library.default_scene or library.default_scene not in library.scenes:
        if len(library.scenes) == 1:
            library.default_scene = next(iter(library.scenes))
        else:
            library.default_scene = sorted(library.scenes)[0] if library.scenes else ""
    return library


# ═══════════════════════════════════════════════════════════════════
# 查询（与 selinux_policy_query 的返回形状保持一致）
# ═══════════════════════════════════════════════════════════════════


def probe_access(scene: Scene, resource: str, tclass: str,
                 perms: Optional[Sequence[str]] = None,
                 src: str = "") -> Dict[str, Any]:
    src = str(src or scene.subject or "").strip()
    resource = str(resource or "").strip()
    tclass = str(tclass or "").strip()
    wanted = sorted({str(p) for p in (perms or []) if str(p)})

    base: Dict[str, Any] = {
        "available": True, "verdict": "unknown", "src": src,
        "resource": resource, "tclass": tclass, "perms": wanted,
        "source": "policy_library(%s)" % scene.name,
    }
    if not IDENT_RE.match(src):
        return dict(base, error="场景主体名非法：%s" % src,
                    notes=["场景 subject 为空或非法，无法评估"])
    if not resource:
        return dict(base, error="resource 不能为空")

    resolved = resolve_type(scene, resource)
    if not resolved:
        return dict(base, verdict="unknown", resolved_target_type="",
                    target_confidence="none",
                    target_resolution={
                        "expected_type": "", "expected_source": "policy_library.fc",
                        "actual_label": None, "label_mismatch": False,
                        "expected_trust": "low", "expected_is_generic": False,
                        "expected_trust_reason": "路径未命中场景 .fc，无法解析客体类型",
                    },
                    matched_count=0, rules=[],
                    notes=["资源 %s 未在场景 .fc 中声明，无法解析类型；"
                           "不得据此产出规则" % resource])

    expected_type = str(resolved["type"])
    # 场景可以声明客体的实际标签；没有声明时按 .fc 默认类型处理。
    # 授权判断跟随实际标签（SELinux 只看实际类型），标签检查另看 expected_type。
    actual_type = str(scene.actual_labels.get(resource) or expected_type)
    label_mismatch = actual_type != expected_type
    tgt_type = actual_type
    covered = scene.effective_perms(src, tgt_type, tclass)
    covered_perms = [p for p in wanted if p in covered]
    missing = [p for p in wanted if p not in covered]
    matched = scene.matching_rules(src, tgt_type, tclass)

    if not wanted:
        verdict = "allowed" if matched else "no_rule"
    elif not missing:
        verdict = "allowed"
    elif covered_perms:
        verdict = "partial"
    else:
        verdict = "no_rule"

    notes: List[str] = []
    if missing:
        notes.append("未覆盖权限：%s" % ", ".join(missing))
    if verdict == "no_rule":
        notes.append("场景策略里没有该访问的 allow 规则；若任务确需该访问，需新增规则")
    if tgt_type in scene.sensitive_targets:
        notes.append("客体类型 %s 在场景中被标记为敏感目标：已有规则应删除或收窄，"
                     "绝不能新增/扩大放行" % tgt_type)
    if label_mismatch:
        notes.append("客体 %s 的实际标签是 %s，但 .fc 声明的默认类型是 %s；"
                     "应按默认类型纠正标签" % (resource, actual_type, expected_type))

    return {
        "available": True,
        "verdict": verdict,
        "src": src,
        "resource": resource,
        "tclass": tclass,
        "perms": wanted,
        "covered_perms": covered_perms,
        "missing_perms": missing,
        "resolved_target_type": tgt_type,
        "target_confidence": "high",
        "target_resolution": {
            "expected_type": expected_type,
            "expected_source": "policy_library.fc(%s)" % resolved["pattern"],
            "actual_label": {"user": "system_u", "role": "object_r",
                             "type": actual_type, "level": "s0"},
            "label_mismatch": label_mismatch,
            "expected_trust": "high",
            "expected_is_generic": False,
            "expected_trust_reason": "",
        },
        "matched_count": len(matched),
        "rules": [r.as_dict() for r in matched[:20]],
        "source": "policy_library(%s)" % scene.name,
        "notes": notes,
    }


def type_info(scene: Scene, name: str) -> Dict[str, Any]:
    name = str(name or "").strip()
    if not IDENT_RE.match(name):
        return {"available": False, "name": name, "error": "非法的类型/属性名"}
    if name in scene.attributes:
        expanded = sorted(scene.members_of(name) - {name})
        return {
            "available": True, "name": name, "kind": "attribute",
            "in_library": True, "in_loaded_policy": None,
            "expanded_count": len(expanded), "expanded_types": expanded[:40],
            "verdict_note": "这是属性而不是具体类型，不能直接作为规则客体",
        }
    if name in scene.types:
        return {"available": True, "name": name, "kind": "type",
                "in_library": True, "in_loaded_policy": None,
                "expanded_count": 0, "expanded_types": [],
                "verdict_note": "类型已在本场景 .te 中声明"}
    used = any(r.src == name or r.tgt == name for r in scene.rules)
    return {
        "available": True, "name": name, "kind": "unknown",
        "in_library": False, "in_loaded_policy": None,
        "expanded_count": 0, "expanded_types": [],
        "verdict_note": (
            "类型未在场景 .te 中声明；本模块不允许新增类型声明，"
            "因此不能把它写进规则（曾被规则引用=%s）" % used
        ),
    }


def allow_search(scene: Scene, src: str = "", tgt: str = "",
                 tclass: str = "", perms: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    src = str(src or "").strip()
    tgt = str(tgt or "").strip()
    tclass = str(tclass or "").strip()
    wanted = {str(p) for p in (perms or []) if str(p)}
    if not (src or tgt or tclass):
        return {"available": False, "error": "至少需要提供 src / tgt / tclass 中的一项"}

    rules: List[Rule] = []
    for rule in scene.rules:
        if src and src not in scene.rule_sources(rule):
            continue
        if tgt:
            targets = scene.rule_targets(rule) if rule.tgt == "self" else scene.members_of(rule.tgt)
            if tgt not in targets:
                continue
        if tclass and rule.tclass != tclass:
            continue
        if wanted and not (wanted & set(rule.perms)):
            continue
        rules.append(rule)

    return {
        "available": True,
        "query": {"src": src, "tgt": tgt, "tclass": tclass, "perms": sorted(wanted)},
        "source": "policy_library(%s)" % scene.name,
        "matched_count": len(rules),
        "rules": [r.as_dict() for r in rules[:60]],
        "truncated": len(rules) > 60,
    }


# ═══════════════════════════════════════════════════════════════════
# 编辑
# ═══════════════════════════════════════════════════════════════════


def _rule_line_index(scene: Scene) -> Dict[str, List[int]]:
    index: Dict[str, List[int]] = {}
    for rule in scene.rules:
        index.setdefault(normalize_rule_text(rule.raw or rule.text), []).append(rule.line)
    return index


def apply_edits(scene: Scene, edits: Sequence[Dict[str, Any]],
                add_rules: Sequence[Any]) -> Dict[str, Any]:
    """在场景源码上应用 edits/add_rules，返回新源码与规范化后的改动。

    edits 每项：{"old_rule": "源码中原样的一条 allow", "new_rule": "新规则或空串"}
        空串 new_rule 表示删除整条规则。
    add_rules：完整 allow 规则字符串（或结构化的 src/tgt/tclass/perms 对象）。

    本函数只做文本替换与语法解析，不做策略合规判断；合规判断在 policy_gate。
    """
    lines = scene.source.splitlines()
    original_lines = list(lines)
    by_norm = _rule_line_index(scene)
    used_lines: set = set()
    errors: List[str] = []
    changes: List[Dict[str, Any]] = []

    for index, item in enumerate(edits or []):
        if not isinstance(item, dict):
            errors.append("edits[%d] 不是对象" % index)
            continue
        old_text = str(item.get("old_rule") or "").strip()
        new_text = str(item.get("new_rule") or "").strip()
        if not old_text:
            errors.append("edits[%d] 缺少 old_rule" % index)
            continue

        old_rule, err = parse_rule_text(old_text)
        if old_rule is None:
            errors.append("edits[%d] 的 old_rule %s" % (index, err))
            continue
        norm = normalize_rule_text(old_text)
        candidates = [ln for ln in by_norm.get(norm, []) if ln not in used_lines]
        if not candidates:
            errors.append(
                "edits[%d] 的 old_rule 不在场景源码中（或已被前面的 edit 用过）：%s"
                % (index, old_text[:160]))
            continue
        line_no = candidates[0]
        used_lines.add(line_no)

        if not new_text:
            old_raw = lines[line_no - 1]
            lines[line_no - 1] = None  # type: ignore[assignment]
            changes.append({
                "kind": "delete", "line": line_no,
                "old_rule": old_raw.strip(), "new_rule": "",
                "reason": str(item.get("reason") or "")[:400],
            })
            continue

        new_rule, err = parse_rule_text(new_text)
        if new_rule is None:
            errors.append("edits[%d] 的 new_rule %s" % (index, err))
            continue
        old_raw = lines[line_no - 1]
        indent = re.match(r"^(\s*)", old_raw).group(1)
        rendered = render_rule(new_rule.src, new_rule.tgt, new_rule.tclass, new_rule.perms)
        lines[line_no - 1] = indent + rendered
        changes.append({
            "kind": "modify", "line": line_no,
            "old_rule": old_raw.strip(), "new_rule": rendered,
            "reason": str(item.get("reason") or "")[:400],
        })

    kept = [line for line in lines if line is not None]
    appended: List[str] = []
    # 同一次调用内新增的规则也要参与查重，否则 add_rules 里重复提交会产出两条一样的 allow
    existing = {normalize_rule_text(line) for line in kept if line.strip().startswith("allow ")}
    for index, raw in enumerate(add_rules or []):
        if isinstance(raw, dict):
            try:
                text = render_rule(str(raw.get("src") or ""), str(raw.get("tgt") or ""),
                                   str(raw.get("tclass") or raw.get("class") or ""),
                                   raw.get("perms") or raw.get("permissions") or [])
            except Exception as exc:
                errors.append("add_rules[%d] 结构不合法：%s" % (index, exc))
                continue
        else:
            text = str(raw or "").strip()
        rule, err = parse_rule_text(text)
        if rule is None:
            errors.append("add_rules[%d] %s" % (index, err))
            continue
        rendered = render_rule(rule.src, rule.tgt, rule.tclass, rule.perms)
        if normalize_rule_text(rendered) in existing:
            changes.append({"kind": "noop_add", "line": 0, "old_rule": "",
                            "new_rule": rendered,
                            "reason": "该规则在源码中已存在（同一条 allow）"})
            continue
        existing.add(normalize_rule_text(rendered))
        appended.append(rendered)
        changes.append({"kind": "add", "line": 0, "old_rule": "",
                        "new_rule": rendered,
                        "reason": ""})

    if appended:
        if kept and kept[-1].strip():
            kept.append("")
        kept.extend(appended)

    new_source = "\n".join(kept)
    if new_source and not new_source.endswith("\n"):
        new_source += "\n"
    updated = scene_from_source(scene, new_source)
    if errors:
        # 有语法/定位错误时仍然返回 candidate_source 供排查，但调用方必须看 errors
        pass
    return {
        "ok": not errors,
        "errors": errors,
        "source": new_source,
        "scene": updated,
        "changes": changes,
        "diff": unified_diff(scene.source, new_source, scene.name),
        "original_source": "\n".join(original_lines) + ("\n" if original_lines else ""),
    }


def apply_relabel(scene: Scene, items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """在场景副本上应用客体改标签，返回更新后的场景与改动列表。

    只改内存中的 actual_labels，不触碰 .te/.fc 文件，也不执行任何标签命令。
    """
    updated = copy.copy(scene)
    updated.actual_labels = dict(scene.actual_labels)
    changes: List[Dict[str, Any]] = []
    for item in items or []:
        path = str(item.get("path") or "").strip()
        expected = str(item.get("expected_type") or "").strip()
        if not path or not expected:
            continue
        old = updated.actual_labels.get(path, "")
        updated.actual_labels[path] = expected
        changes.append({
            "kind": "relabel",
            "path": path,
            "old_label": old,
            "new_label": expected,
            "reason": str(item.get("reason") or "")[:400],
        })
    return {"scene": updated, "changes": changes}


def unified_diff(old: str, new: str, name: str = "scene") -> str:
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile="a/%s.te" % name, tofile="b/%s.te" % name, n=2,
    ))


# ═══════════════════════════════════════════════════════════════════
# 任务测试评估
# ═══════════════════════════════════════════════════════════════════


def evaluate_tests(scene: Scene, tests: Optional[Sequence[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """按任务测试评估当前策略。

    与参考实现的语义一致：一个测试的 permissions 全部被授予才算 actual=True，
    再与 expected（True=应允许，False=应禁止）比较。
    """
    checks: List[Dict[str, Any]] = []
    subject = scene.subject
    for test in (tests if tests is not None else scene.tests):
        if not isinstance(test, dict):
            continue
        kind = str(test.get("kind") or "").strip()
        if kind == "label":
            path = str(test.get("path") or "").strip()
            expected_label = str(test.get("expected_type") or test.get("expected") or "").strip()
            actual_label = str(scene.actual_labels.get(path) or "").strip()
            if not actual_label:
                resolved = resolve_type(scene, path)
                actual_label = str((resolved or {}).get("type") or "")
            checks.append({
                "name": str(test.get("name") or test.get("operation") or "标签检查"),
                "kind": "label",
                "path": path,
                "target": expected_label,
                "class": str(test.get("class") or "file"),
                "permissions": [],
                "expected": expected_label,
                "actual": actual_label,
                "covered_permissions": [],
                "missing_permissions": [],
                "passed": bool(expected_label) and actual_label == expected_label,
            })
            continue
        target = str(test.get("target") or test.get("target_type") or "").strip()
        tclass = str(test.get("class") or test.get("tclass") or "").strip()
        wanted = [str(p) for p in (test.get("permissions") or test.get("perms") or []) if str(p)]
        expected = bool(test.get("expected", True))
        covered = scene.effective_perms(subject, target, tclass) if target and tclass else set()
        covered_perms = [p for p in wanted if p in covered]
        missing = [p for p in wanted if p not in covered]
        actual = not missing
        checks.append({
            "name": str(test.get("name") or test.get("operation") or "%s:%s" % (target, tclass)),
            "target": target,
            "class": tclass,
            "permissions": wanted,
            "expected": expected,
            "actual": actual,
            "covered_permissions": covered_perms,
            "missing_permissions": missing,
            "passed": actual == expected,
        })
    passed = sum(1 for c in checks if c["passed"])
    return {
        "scene": scene.name,
        "subject": subject,
        "checks": checks,
        "passed": passed,
        "total": len(checks),
        "fully_correct": bool(checks) and passed == len(checks),
    }


def task_regressions(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    """对比编辑前后的任务结果，区分「新破坏」「新放行」「仍未修复」。"""
    before_map = {c["name"]: c for c in before.get("checks", [])}
    broken: List[Dict[str, Any]] = []
    newly_granted: List[Dict[str, Any]] = []
    remaining: List[Dict[str, Any]] = []
    for check in after.get("checks", []):
        prev = before_map.get(check["name"])
        if check["passed"]:
            continue
        if check["expected"] and prev and prev["actual"] and not check["actual"]:
            broken.append(check)
        elif (not check["expected"]) and prev and not prev["actual"] and check["actual"]:
            newly_granted.append(check)
        else:
            remaining.append(check)
    return {
        "broken": broken,
        "newly_granted": newly_granted,
        "remaining": remaining,
    }


def rules_text(rules: Sequence[Rule]) -> List[str]:
    return [r.text for r in rules]
