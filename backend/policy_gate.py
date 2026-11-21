# -*- coding: utf-8 -*-
"""策略建议后置校验（确定性 gate）与 .te 渲染。

规则文本由 LLM 撰写，本模块负责在它落地之前做机器可检的把关：

    validate(proposal, evidence, probes) -> dict

校验分三级：
  block  必须拒绝输出，理由会回灌给 LLM 让它修正
  warn   允许输出，但会写进最终报告的风险说明
  info   仅记录

最硬的一条是安全阀 OVERPRIVILEGE_GRANTED：
如果某条越权访问（隐私资源、未申报的高危访问）正是应当被拦下的证据，
那么任何试图放行它的规则都必须被拒绝——这正是本模块区别于裸 audit2allow 的地方。

设计约束：
  * 全程只读目标机。这里只会调用 checkmodule 做**本地沙箱编译校验**，
    绝不执行 semodule -i / semodule -r / setenforce / restorecon
  * 类型存在性无法验证时（本机缺 seinfo，或客体类型只来自源码知识库），
    宁可拒绝输出也不输出未经验证的规则
"""

from __future__ import annotations

import copy
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple

import policy_library as plib
from selinux_policy_query import GENERIC_FC_TYPES

DECISIONS = ("ADD_ALLOW", "MODIFY_ALLOW", "DELETE_ALLOW", "RELABEL_OBJECT", "NO_CHANGE")

# NO_CHANGE 的理由码：布尔开关、标签错配、permissive 模式等属于检测能力，
# 只写进说明，不产出规则
REASON_CODES = {
    "MISSING_RULE": "策略里确实没有对应 allow 规则",
    "INSUFFICIENT_PERMS": "已有规则但权限不全",
    "EXCESSIVE_PERMISSION": "已有规则权限超出任务需要，应删减或收窄",
    "RULE_NOT_NEEDED": "整条 allow 规则不在任务范围内，应删除",
    "OBJECT_MISLABELED": "客体标签错配且已被放行，应收敛到默认类型（改标签，不动 allow 规则）",
    "ALREADY_ALLOWED": "策略已放行，无需改动",
    "SOURCE_UNCONFINED": "源域不受 SELinux 强制，allow 规则无实际意义",
    "OVERPRIVILEGE_ONLY": "全部证据都是越权访问，不应放行",
    "LABEL_MISMATCH": "属于文件标签问题，不是 allow 规则问题",
    "BOOLEAN_GATED": "由布尔开关控制，不属于 allow 规则改动",
    "PERMISSIVE_MODE": "目标机为 permissive，无法验证规则是否缺失",
    "EVIDENCE_INSUFFICIENT": "证据不足以判定",
    "NOT_POLICY_ISSUE": "不属于 SELinux 策略问题",
}

MODULE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,30}$")

# 这些理由码必须伴随一次实际改动，不能配 NO_CHANGE
_CHANGE_REASONS = frozenset({
    "MISSING_RULE", "INSUFFICIENT_PERMS", "EXCESSIVE_PERMISSION",
    "RULE_NOT_NEEDED", "OBJECT_MISLABELED",
})
_NO_CHANGE_REASONS = frozenset(REASON_CODES) - _CHANGE_REASONS
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

MAX_RULES = 20
MAX_EDITS = 40
MAX_PERMS_PER_RULE = 24
MAX_NOTES = 30
MAX_REASON_LEN = 400
MAX_SUMMARY_LEN = 2000
MAX_RELABEL = 20

# 高危权限：授予它们等于给出提权/绕过路径，任何情况下都不产出
FORBIDDEN_PERMS = frozenset({
    "execmod", "entrypoint", "execute_no_trans", "transition", "dyntransition",
    "setenforce", "setbool", "setsecparam", "load_policy", "setcheckreqprot",
    "relabelfrom", "relabelto", "ptrace", "setexec", "setfscreate",
    "setcurrent", "mounton", "audit_write", "audit_control", "sysadmin",
})

# 过宽的客体：给属性或兜底类型授权等于给一大片类型授权
FORBIDDEN_TARGETS = frozenset({
    "domain", "file_type", "fs_type", "object_type", "default_t", "unlabeled_t",
    "device_t", "nodev", "self",
})

# 只允许产出 allow；其余规则类型（含 dontaudit 抑制）不在本模块范围内
FORBIDDEN_RULE_TYPES = frozenset({
    "dontaudit", "auditallow", "neverallow", "type_transition", "type_change",
    "type_member", "role_transition", "range_transition", "permissive",
})

# 本模块只处理资源访问类对象，不产出内核特权类规则
FORBIDDEN_CLASSES = frozenset({"capability", "capability2", "process", "kernel_service"})

_UNCONFINED_HINTS = ("unconfined", "spc_t", "kernel_t")


def _is_unconfined(name: Any) -> bool:
    """是否是不受限域：内核对它不做强制，为它写 allow 规则没有约束效果。"""
    text = str(name or "")
    return any(h in text for h in _UNCONFINED_HINTS)


# ──────────────────────────── 违规记录 ────────────────────────────


def _violation(code: str, message: str, level: str = "block",
               rule: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """一条校验结果：code / level / message / rule。"""
    item: Dict[str, Any] = {"code": code, "level": level, "message": message}
    if rule is not None:
        item["rule"] = rule
    return item


Violation = Dict[str, Any]


def _blocks(violations: List[Violation]) -> List[Violation]:
    return [v for v in violations if v["level"] == "block"]


def _warns(violations: List[Violation]) -> List[Violation]:
    return [v for v in violations if v["level"] == "warn"]


def _blocked_reason(blocks: Sequence[Violation], evidence: Dict[str, Any]) -> str:
    """从阻断原因反推一个自洽的 NO_CHANGE 理由码；推不出来返回空串。

    被拒绝的建议会连理由码一起落库，理由码必须说明「为什么被拦」：
    一律回落成 EVIDENCE_INSUFFICIENT 会让「试图放行越权访问」在库里看不出区别。
    """
    codes = {v["code"] for v in blocks}
    if "OVERPRIVILEGE_GRANTED" in codes:
        return "OVERPRIVILEGE_ONLY"
    # 改标签建议被拦下时，回落到"标签问题只写诊断"，而不是笼统的证据不足
    if any(c.startswith("RELABEL_") for c in codes):
        return "LABEL_MISMATCH"
    if codes & {"EDIT_RULE_NOT_FOUND", "EDIT_APPLY_FAILED", "EDIT_NO_EFFECT"}:
        return "EVIDENCE_INSUFFICIENT"
    if _is_unconfined(evidence.get("source_type")):
        return "SOURCE_UNCONFINED"
    return ""


# ──────────────────────────── 提案结构校验 ────────────────────────────


def _norm_rules(raw: Any, violations: List[Violation]) -> List[Dict[str, Any]]:
    """规则归一化：只接受 allow，同 (src,tgt,class) 合并权限并排序。"""
    if raw is None:
        return []
    if not isinstance(raw, list):
        violations.append(_violation("SCHEMA_INVALID", "rules 必须是数组"))
        return []
    merged: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for index, item in enumerate(raw):
        if isinstance(item, str):
            # 兼容参考目录风格的 add_rules: ["allow agent_t x_t:file { read };"]
            parsed, err = plib.parse_rule_text(item)
            if parsed is None:
                violations.append(_violation(
                    "SCHEMA_INVALID", "rules[%d] %s" % (index, err)))
                continue
            item = {
                "src": parsed.src, "tgt": parsed.tgt, "tclass": parsed.tclass,
                "perms": list(parsed.perms), "evidence": [], "reason": "",
            }
        if not isinstance(item, dict):
            violations.append(_violation(
                "SCHEMA_INVALID", "rules[%d] 不是对象" % index, rule={"raw": str(item)[:120]}))
            continue
        rule_type = str(item.get("rule_type") or item.get("type") or "allow").strip().lower()
        if rule_type != "allow":
            violations.append(_violation(
                "NON_ALLOW_RULE",
                "规则类型 %s 不在本模块范围内，只允许输出 allow 规则" % rule_type,
                rule=dict(item)))
            continue

        src = str(item.get("src") or "").strip()
        tgt = str(item.get("tgt") or item.get("target") or "").strip()
        tclass = str(item.get("tclass") or item.get("class") or "").strip()
        perms_raw = item.get("perms") or item.get("permissions") or []
        if isinstance(perms_raw, str):
            perms_raw = re.split(r"[\s,]+", perms_raw)
        perms = sorted({str(p).strip() for p in perms_raw if str(p).strip()})

        for field, value in (("src", src), ("tgt", tgt), ("tclass", tclass)):
            if not value:
                violations.append(_violation(
                    "SCHEMA_INVALID", "rules[%d] 缺少 %s" % (index, field), rule=dict(item)))
        if not IDENT_RE.match(src) or not IDENT_RE.match(tgt) or not IDENT_RE.match(tclass):
            violations.append(_violation(
                "SCHEMA_INVALID",
                "rules[%d] 的 src/tgt/tclass 必须是合法标识符（收到 src=%r tgt=%r class=%r）"
                % (index, src, tgt, tclass),
                rule=dict(item)))
            continue
        if not perms:
            violations.append(_violation(
                "SCHEMA_INVALID", "rules[%d] 的 perms 不能为空" % index, rule=dict(item)))
            continue

        refs = item.get("evidence") or item.get("evidence_refs") or []
        if isinstance(refs, str):
            refs = [refs]
        refs = [str(r).strip() for r in refs if str(r).strip()]

        key = (src, tgt, tclass)
        slot = merged.get(key)
        if slot is None:
            merged[key] = {
                "rule_type": "allow", "src": src, "tgt": tgt, "tclass": tclass,
                "perms": perms, "evidence": refs,
                "reason": str(item.get("reason") or "").strip()[:MAX_REASON_LEN],
            }
        else:
            slot["perms"] = sorted(set(slot["perms"]) | set(perms))
            for ref in refs:
                if ref not in slot["evidence"]:
                    slot["evidence"].append(ref)
    return list(merged.values())


# relabel 项绝不允许携带这些字段：它们是把"改标签"当成夹带放行的信号
_RELABEL_SMUGGLE_KEYS = ("perms", "permissions", "src", "source", "tgt", "target",
                         "rule_type", "allow")


def _norm_relabel(raw: Any, violations: List[Violation]) -> List[Dict[str, Any]]:
    """改标签项归一化。

    结构上只接受 {access_id, path, current_type, expected_type, reason} —— 没有
    perms/src/tgt，因此无法借"改标签"之名夹带 allow 授权。任何这类字段一律阻断。
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        violations.append(_violation("SCHEMA_INVALID", "relabel 必须是数组"))
        return []
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for index, item in enumerate(raw[:MAX_RELABEL + 5]):
        if not isinstance(item, dict):
            violations.append(_violation(
                "SCHEMA_INVALID", "relabel[%d] 不是对象" % index, rule={"raw": str(item)[:120]}))
            continue
        smuggled = [k for k in _RELABEL_SMUGGLE_KEYS if item.get(k) not in (None, "", [])]
        if smuggled:
            violations.append(_violation(
                "RELABEL_SMUGGLES_ALLOW",
                "relabel[%d] 携带了 %s 字段；改标签建议不得包含任何授权信息，"
                "需要放行请另判 ADD_ALLOW/MODIFY_ALLOW" % (index, ", ".join(smuggled)),
                rule=dict(item)))
            continue
        access_id = str(item.get("access_id") or "").strip()
        path = str(item.get("path") or "").strip()
        current_type = str(item.get("current_type") or "").strip()
        expected_type = str(item.get("expected_type") or "").strip()
        if not access_id or not path:
            violations.append(_violation(
                "SCHEMA_INVALID", "relabel[%d] 缺少 access_id 或 path" % index, rule=dict(item)))
            continue
        if not path.startswith("/"):
            violations.append(_violation(
                "SCHEMA_INVALID", "relabel[%d] 的 path 必须是绝对路径，收到 %r" % (index, path),
                rule=dict(item)))
            continue
        for field, value in (("current_type", current_type), ("expected_type", expected_type)):
            if not IDENT_RE.match(value or ""):
                violations.append(_violation(
                    "SCHEMA_INVALID",
                    "relabel[%d] 的 %s 必须是合法类型标识符，收到 %r" % (index, field, value),
                    rule=dict(item)))
        key = (access_id, path)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "access_id": access_id, "path": path[:300],
            "current_type": current_type, "expected_type": expected_type,
            "reason": str(item.get("reason") or "").strip()[:MAX_REASON_LEN],
        })
    if len(raw) > MAX_RELABEL:
        violations.append(_violation(
            "TOO_MANY_RULES", "relabel 项 %d 超过上限 %d，只保留前 %d 条"
            % (len(raw), MAX_RELABEL, MAX_RELABEL)))
    return out[:MAX_RELABEL]


def _norm_edits(raw: Any, violations: List[Violation]) -> List[Dict[str, Any]]:
    """归一化对已有 allow 规则的增/删/改。

    每项 {old_rule, new_rule}：old_rule 必须逐字来自指定策略库源码；
    new_rule 为空表示删除整条规则，否则表示用新规则替换该行。
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        violations.append(_violation("SCHEMA_INVALID", "edits 必须是数组"))
        return []
    out: List[Dict[str, Any]] = []
    for index, item in enumerate(raw[:MAX_EDITS + 5]):
        if not isinstance(item, dict):
            violations.append(_violation(
                "SCHEMA_INVALID", "edits[%d] 不是对象" % index,
                rule={"raw": str(item)[:120]}))
            continue
        old_text = str(item.get("old_rule") or "").strip()
        new_text = str(item.get("new_rule") or "").strip()
        if not old_text:
            violations.append(_violation(
                "SCHEMA_INVALID", "edits[%d] 缺少 old_rule" % index))
            continue
        old_rule, err = plib.parse_rule_text(old_text)
        if old_rule is None:
            violations.append(_violation(
                "SCHEMA_INVALID", "edits[%d] 的 old_rule %s" % (index, err),
                rule={"old_rule": old_text[:160]}))
            continue
        new_rule = None
        if new_text:
            new_rule, err = plib.parse_rule_text(new_text)
            if new_rule is None:
                violations.append(_violation(
                    "SCHEMA_INVALID", "edits[%d] 的 new_rule %s" % (index, err),
                    rule={"new_rule": new_text[:160]}))
                continue
        refs = item.get("evidence") or item.get("evidence_refs") or []
        if isinstance(refs, str):
            refs = [refs]
        out.append({
            "old_rule": old_text[:500],
            "old_norm": plib.normalize_rule_text(old_text),
            "old_parsed": _rule_struct(old_rule),
            "new_rule": new_text[:500],
            "new_parsed": _rule_struct(new_rule) if new_rule else None,
            "is_delete": new_rule is None,
            "evidence": [str(r).strip() for r in refs if str(r).strip()],
            "reason": str(item.get("reason") or "").strip()[:MAX_REASON_LEN],
        })
    if len(raw) > MAX_EDITS:
        violations.append(_violation(
            "TOO_MANY_RULES", "edits 项 %d 超过上限 %d，只保留前 %d 条"
            % (len(raw), MAX_EDITS, MAX_EDITS)))
    return out[:MAX_EDITS]


def _rule_struct(rule: Any) -> Dict[str, Any]:
    return {
        "src": rule.src, "tgt": rule.tgt, "tclass": rule.tclass,
        "perms": list(rule.perms),
    }


def _edits_as_rule_dicts(p: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把 edits 中「新增的权限」视图转成规则字典，供黑名单检查复用。

    只检查 new_perm - old_perm / 新客体，不会因为「保留了既有高危权限」
    而阻断一次收窄编辑。
    """
    out: List[Dict[str, Any]] = []
    for edit in p["edits"]:
        old = edit["old_parsed"] or {}
        new = edit["new_parsed"]
        if not new:
            continue
        old_perms = set(old.get("perms") or [])
        added_perms = sorted(set(new["perms"]) - old_perms)
        same_target = (old.get("tgt") == new["tgt"] and
                       old.get("tclass") == new["tclass"] and
                       old.get("src") == new["src"])
        if same_target and not added_perms:
            continue
        out.append({
            "src": new["src"], "tgt": new["tgt"], "tclass": new["tclass"],
            "perms": added_perms if same_target else list(new["perms"]),
            "evidence": [], "reason": edit.get("reason") or "",
            "edit": True,
        })
    return out


def _check_shape(proposal: Dict[str, Any], violations: List[Violation]) -> Dict[str, Any]:
    """校验提案的字段与取值范围，返回归一化后的提案。"""
    decision = str(proposal.get("decision") or "").strip().upper()
    if decision not in DECISIONS:
        violations.append(_violation(
            "SCHEMA_INVALID",
            "decision 必须是 %s 之一，收到 %r" % ("/".join(DECISIONS), proposal.get("decision"))))
        decision = "NO_CHANGE"

    reason_code = str(proposal.get("reason_code") or "").strip().upper()
    if reason_code not in REASON_CODES:
        violations.append(_violation(
            "SCHEMA_INVALID",
            "reason_code 必须是 %s 之一，收到 %r" % ("/".join(sorted(REASON_CODES)), proposal.get("reason_code"))))
        reason_code = "EVIDENCE_INSUFFICIENT"

    summary = str(proposal.get("summary") or "").strip()
    if not summary:
        violations.append(_violation("SCHEMA_INVALID", "summary 不能为空"))
    summary = summary[:MAX_SUMMARY_LEN]

    module_name = str(proposal.get("module_name") or "").strip()
    notes = proposal.get("notes") or []
    if isinstance(notes, str):
        notes = [notes]
    notes = [str(n).strip()[:MAX_REASON_LEN] for n in notes if str(n).strip()][:MAX_NOTES]

    refs = proposal.get("evidence_refs") or []
    if isinstance(refs, str):
        refs = [refs]

    combined_rules: List[Any] = []
    for key in ("rules", "add_rules"):
        value = proposal.get(key)
        if value is None:
            continue
        if not isinstance(value, list):
            violations.append(_violation("SCHEMA_INVALID", "%s 必须是数组" % key))
            continue
        combined_rules.extend(value)
    rules = _norm_rules(combined_rules, violations)
    if len(rules) > MAX_RULES:
        violations.append(_violation(
            "TOO_MANY_RULES", "规则数 %d 超过上限 %d，只保留前 %d 条"
            % (len(rules), MAX_RULES, MAX_RULES)))
        rules = rules[:MAX_RULES]

    edits = _norm_edits(proposal.get("edits"), violations)
    relabel = _norm_relabel(proposal.get("relabel"), violations)

    confidence = str(proposal.get("confidence") or "medium").strip().lower()
    if confidence not in ("high", "medium", "low"):
        confidence = "medium"

    return {
        "decision": decision,
        "reason_code": reason_code,
        "summary": summary,
        "module_name": module_name,
        "target_policy_version": str(proposal.get("target_policy_version") or "").strip(),
        "rules": rules,
        "edits": edits,
        "relabel": relabel,
        "notes": notes,
        "evidence_refs": [str(r).strip() for r in refs if str(r).strip()],
        "must_not_allow": _norm_must_not_allow(proposal.get("must_not_allow"), violations),
        "confidence": confidence,
    }


def _norm_must_not_allow(raw: Any, violations: List[Violation]) -> List[Dict[str, str]]:
    """LLM 自己声明的"绝不应放行"集合，用于与安全阀交叉验证。"""
    if raw is None:
        return []
    if not isinstance(raw, list):
        violations.append(_violation("SCHEMA_INVALID", "must_not_allow 必须是数组"))
        return []
    out = []
    for item in raw[:MAX_RULES]:
        if not isinstance(item, dict):
            continue
        out.append({
            "access_id": str(item.get("access_id") or "").strip(),
            "resource": str(item.get("resource") or "").strip()[:200],
            "reason": str(item.get("reason") or "").strip()[:MAX_REASON_LEN],
        })
    return out


def _check_decision_consistency(p: Dict[str, Any], violations: List[Violation],
                                library: bool = False) -> None:
    """决策与规则/增删改项/改标签项/理由是否自洽。

    两种模式的自洽要求不同，不能混用：实时模式只能产出 .te 模块（新增/补权），
    MODIFY_ALLOW 用 rules 提交、靠 notes 说明缺权；库模式能逐字编辑场景 .te，
    因此强制要求 edits 并支持 DELETE_ALLOW。用库模式的标准去卡实时提案会全部误判。
    """
    decision = p["decision"]
    has_rules = bool(p["rules"])
    has_edits = bool(p["edits"])
    has_replacements = any(not e["is_delete"] for e in p["edits"])

    if decision == "RELABEL_OBJECT":
        # 改标签与 allow 规则互斥：混在一起就无法判断到底在授权还是在收敛
        if has_rules or has_edits:
            violations.append(_violation(
                "DECISION_RULE_MISMATCH",
                "decision=RELABEL_OBJECT 不能同时给出 allow 规则或增删改项；"
                "改标签是收敛权限，与放行互斥，请拆成两次独立判断"))
        if not p["relabel"]:
            violations.append(_violation(
                "DECISION_RULE_MISMATCH",
                "decision=RELABEL_OBJECT 但 relabel 为空；没有改标签项时必须判 NO_CHANGE"))
    elif p["relabel"]:
        violations.append(_violation(
            "DECISION_RULE_MISMATCH",
            "decision=%s 却给出了 relabel 项；改标签建议必须判 RELABEL_OBJECT" % decision))
    elif decision == "NO_CHANGE":
        if has_rules or has_edits:
            violations.append(_violation(
                "DECISION_RULE_MISMATCH",
                "decision=NO_CHANGE 却给出了规则/增删改项；"
                "要么改判为 ADD_ALLOW/MODIFY_ALLOW/DELETE_ALLOW，要么全部清空"))
    elif library:
        if decision == "ADD_ALLOW":
            if not has_rules:
                violations.append(_violation(
                    "DECISION_RULE_MISMATCH",
                    "decision=ADD_ALLOW 但 rules/add_rules 为空；新增规则必须给出完整 allow 规则"))
            if has_edits:
                violations.append(_violation(
                    "DECISION_RULE_MISMATCH",
                    "decision=ADD_ALLOW 只用于新增规则；修改已有规则请用 MODIFY_ALLOW，"
                    "删除已有规则请用 DELETE_ALLOW"))
        elif decision == "DELETE_ALLOW":
            if not has_edits:
                violations.append(_violation(
                    "DECISION_RULE_MISMATCH",
                    "decision=DELETE_ALLOW 但 edits 为空；请用 edits 给出要删除的 old_rule"))
            if has_rules:
                violations.append(_violation(
                    "DECISION_RULE_MISMATCH",
                    "decision=DELETE_ALLOW 不能同时新增规则；需要同时增删请用 MODIFY_ALLOW"))
            if has_replacements:
                violations.append(_violation(
                    "DECISION_RULE_MISMATCH",
                    "decision=DELETE_ALLOW 的 edits 必须全部是删除（new_rule 为空）；"
                    "要保留但收窄某条规则请用 MODIFY_ALLOW"))
        elif decision == "MODIFY_ALLOW":
            if not has_edits:
                violations.append(_violation(
                    "DECISION_RULE_MISMATCH",
                    "decision=MODIFY_ALLOW 但 edits 为空；请用 edits 给出 old_rule 与 new_rule"))
            if not has_replacements:
                violations.append(_violation(
                    "DECISION_RULE_MISMATCH",
                    "decision=MODIFY_ALLOW 的 edits 至少要有一条 new_rule 非空；"
                    "只删规则请用 DELETE_ALLOW"))
    else:
        if not has_rules:
            violations.append(_violation(
                "DECISION_RULE_MISMATCH",
                "decision=%s 但 rules 为空；没有规则可产出时必须判 NO_CHANGE" % decision))
        elif decision == "MODIFY_ALLOW":
            # MODIFY_ALLOW 意味着已有规则但权限不全，必须说明改哪一条
            if not any("已有" in n or "修改" in n or "missing" in n.lower() for n in p["notes"]):
                violations.append(_violation(
                    "DECISION_RULE_MISMATCH",
                    "decision=MODIFY_ALLOW 需要在 notes 里说明现有规则缺哪些权限",
                    level="warn"))

    reason_code = p["reason_code"]
    if decision == "RELABEL_OBJECT" and reason_code != "OBJECT_MISLABELED":
        violations.append(_violation(
            "DECISION_RULE_MISMATCH",
            "decision=RELABEL_OBJECT 的 reason_code 必须是 OBJECT_MISLABELED，收到 %s" % reason_code))
    if reason_code == "OBJECT_MISLABELED" and decision != "RELABEL_OBJECT":
        violations.append(_violation(
            "DECISION_RULE_MISMATCH",
            "reason_code=OBJECT_MISLABELED 只能配 decision=RELABEL_OBJECT"))
    if decision == "NO_CHANGE" and reason_code in _CHANGE_REASONS:
        violations.append(_violation(
            "DECISION_RULE_MISMATCH",
            "reason_code=%s 与 decision=NO_CHANGE 矛盾" % reason_code))
    if library:
        if decision == "ADD_ALLOW" and reason_code != "MISSING_RULE":
            violations.append(_violation(
                "DECISION_RULE_MISMATCH",
                "decision=ADD_ALLOW 的 reason_code 应为 MISSING_RULE，收到 %s" % reason_code))
        if decision == "DELETE_ALLOW" and reason_code not in ("EXCESSIVE_PERMISSION", "RULE_NOT_NEEDED"):
            violations.append(_violation(
                "DECISION_RULE_MISMATCH",
                "decision=DELETE_ALLOW 的 reason_code 应为 EXCESSIVE_PERMISSION 或 RULE_NOT_NEEDED，"
                "收到 %s" % reason_code))
        if decision == "MODIFY_ALLOW" and reason_code not in ("INSUFFICIENT_PERMS", "EXCESSIVE_PERMISSION"):
            violations.append(_violation(
                "DECISION_RULE_MISMATCH",
                "decision=MODIFY_ALLOW 的 reason_code 应为 INSUFFICIENT_PERMS（补权）或 "
                "EXCESSIVE_PERMISSION（收窄），收到 %s" % reason_code))
        if decision in ("ADD_ALLOW", "MODIFY_ALLOW", "DELETE_ALLOW") and reason_code in _NO_CHANGE_REASONS:
            violations.append(_violation(
                "DECISION_RULE_MISMATCH",
                "reason_code=%s（%s）不能作为改动 allow 规则的依据"
                % (reason_code, REASON_CODES.get(reason_code, reason_code))))
    elif decision in ("ADD_ALLOW", "MODIFY_ALLOW") and reason_code in (
            "ALREADY_ALLOWED", "SOURCE_UNCONFINED", "OVERPRIVILEGE_ONLY", "LABEL_MISMATCH",
            "BOOLEAN_GATED", "PERMISSIVE_MODE", "EVIDENCE_INSUFFICIENT", "NOT_POLICY_ISSUE"):
        violations.append(_violation(
            "DECISION_RULE_MISMATCH",
            "reason_code=%s（%s）不能作为产出 allow 规则的依据"
            % (reason_code, REASON_CODES[reason_code])))


# ──────────────────────────── 安全阀与最小化 ────────────────────────────


def _is_sensitive_record(rec: Dict[str, Any]) -> bool:
    return rec.get("declaration") == "sensitive" or rec.get("resource_role") == "privacy_resource"


def _sensitive_accesses(evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
    """证据包里所有越权/隐私资源访问（含被截断未返回的那部分摘要）。"""
    out = []
    for rec in evidence.get("accesses", []) or []:
        if _is_sensitive_record(rec):
            out.append(rec)
    seen = {r.get("access_id") for r in out}
    for rec in (evidence.get("summary", {}) or {}).get("sensitive_resources", []) or []:
        if rec.get("access_id") not in seen:
            out.append(rec)
    return out


def _rule_grants(rule: Dict[str, Any], access: Dict[str, Any],
                 target_type: str = "") -> bool:
    """规则是否实际放行了这条越权访问。"""
    if rule["tclass"] != str(access.get("tclass") or ""):
        return False
    if target_type and rule["tgt"] != target_type:
        return False
    return bool(set(rule["perms"]) & set(access.get("perms") or []))


def _check_safety_valve(p: Dict[str, Any], evidence: Dict[str, Any],
                        probes: Dict[str, Dict[str, Any]],
                        violations: List[Violation],
                        sensitive_types: Optional[Dict[str, str]] = None) -> None:
    """越权证据绝不能变成放行理由。"""
    sensitive = _sensitive_accesses(evidence)
    if not sensitive:
        return

    # access_id -> 已解析出的客体类型；没有探测结果的越权访问只能靠引用关系拦
    resolved_types: Dict[str, str] = {}
    for acc in sensitive:
        aid = str(acc.get("access_id") or "")
        resolved = str((probes.get(aid) or {}).get("resolved_target_type") or "")
        if resolved:
            resolved_types[aid] = resolved

    for rule in p["rules"]:
        cited = set(rule.get("evidence") or [])
        hit = ""
        for acc in sensitive:
            aid = str(acc.get("access_id") or "")
            if aid in cited:
                hit = "规则直接引用了越权证据 %s（%s）" % (aid, acc.get("resource", ""))
                break
            ttype = resolved_types.get(aid, "")
            if ttype and _rule_grants(rule, acc, ttype):
                hit = "规则放行了越权证据 %s（%s，客体类型 %s）" % (
                    aid, acc.get("resource", ""), ttype)
                break
        if hit:
            violations.append(_violation(
                "OVERPRIVILEGE_GRANTED",
                "%s；绝不能为越权访问产出 allow 规则，应判 NO_CHANGE，"
                "并在 notes 里说明这是需要收敛的权限" % hit,
                rule=dict(rule)))

    # 提案自己声明的禁止放行集合，与实际规则交叉验证
    for entry in p["must_not_allow"]:
        aid = str(entry.get("access_id") or "")
        probe = probes.get(aid) or {}
        ttype = resolved_types.get(aid) or str(probe.get("resolved_target_type") or "")
        if not ttype:
            continue
        for rule in p["rules"]:
            if rule["tgt"] == ttype and rule["tclass"] == str(probe.get("tclass") or ""):
                violations.append(_violation(
                    "OVERPRIVILEGE_GRANTED",
                    "提案自己声明 %s 不应放行，却产出了针对其客体类型 %s 的规则" % (aid, ttype),
                    rule=dict(rule)))

    # 同类型间接放行：SELinux 的类型粒度区分不了同标签下的不同路径，
    # 规则客体若与某敏感访问的解析类型相同，放行良性访问的同时也会放行敏感资源。
    # 上面两道拦截都抓不到这种写法（引用的是良性 access_id、敏感访问也没被探测过），
    # 无法确定性判定违规，但要作为 warn 写进报告强制人工复核。
    stypes = sensitive_types or {}
    if stypes:
        for rule in p["rules"]:
            if rule["tclass"] not in ("file", "dir"):
                continue
            cited = set(rule.get("evidence") or [])
            overlap = sorted(aid for aid, t in stypes.items()
                             if t == rule["tgt"] and aid not in cited)
            if overlap:
                violations.append(_violation(
                    "SENSITIVE_TYPE_OVERLAP",
                    "客体类型 %s 与敏感访问 %s 的解析类型相同；同类型下的敏感路径会被本规则"
                    "一并放行（SELinux 无法区分），请人工复核是否可接受"
                    % (rule["tgt"], ", ".join(overlap[:5])),
                    level="warn", rule=dict(rule)))


def _check_evidence_refs(p: Dict[str, Any], evidence: Dict[str, Any],
                         violations: List[Violation],
                         require_rule_evidence: bool = True) -> None:
    """引用的 access_id 必须真实存在于证据包中。

    指定策略库模式下允许用完整 allow 字符串提交新增规则（参考目录风格），
    此时不强制每条规则带 access_id，但一旦引用就必须真实存在。
    """
    valid = {str(r.get("access_id")) for r in evidence.get("accesses", []) or []}
    for ref in p["evidence_refs"]:
        if ref not in valid:
            violations.append(_violation(
                "EVIDENCE_REF_UNKNOWN", "evidence_refs 里的 %s 不在证据包中（可能是编造的）" % ref))
    for rule in p["rules"]:
        refs = rule.get("evidence") or []
        if not refs:
            violations.append(_violation(
                "RULE_WITHOUT_EVIDENCE",
                "每条规则必须引用至少一个 access_id 作为依据",
                level="block" if require_rule_evidence else "warn",
                rule=dict(rule)))
        for ref in refs:
            if ref not in valid:
                violations.append(_violation(
                    "EVIDENCE_REF_UNKNOWN",
                    "规则引用的 %s 不在证据包中（可能是编造的）" % ref, rule=dict(rule)))


def _check_minimality(p: Dict[str, Any], evidence: Dict[str, Any],
                      probes: Dict[str, Dict[str, Any]],
                      violations: List[Violation]) -> None:
    """授予的权限不得超出证据里实际观察到的权限；客体类型必须来自证据解析结果。"""
    observed: Dict[str, set] = {}
    src_type = str(evidence.get("source_type") or "")
    for rec in evidence.get("accesses", []) or []:
        if _is_sensitive_record(rec):
            # 敏感访问是要收敛的对象：它贡献的权限不得抬高同类客体的可授予上限，
            # 否则 LLM 引用良性证据也能把敏感访问观察到的权限带进规则
            continue
        key = "%s|%s" % (src_type, rec.get("tclass") or "")
        observed.setdefault(key, set()).update(rec.get("perms") or [])

    by_id = {str(r.get("access_id")): r for r in evidence.get("accesses", []) or []}

    for rule in p["rules"]:
        key = "%s|%s" % (rule["src"], rule["tclass"])
        allowed_perms = observed.get(key, set())
        extra = [perm for perm in rule["perms"] if perm not in allowed_perms]
        if extra:
            violations.append(_violation(
                "PERM_NOT_OBSERVED",
                "权限 %s 没有在证据中出现（该源类型对 %s 类只观察到 %s）；"
                "不得授予未观察到的权限"
                % (", ".join(extra), rule["tclass"], ", ".join(sorted(allowed_perms)) or "无"),
                rule=dict(rule)))

        # 客体类型必须能追溯到被引用证据的解析结果
        cited_types = set()
        for ref in rule.get("evidence") or []:
            acc = by_id.get(ref)
            if acc is None:
                continue
            if str(acc.get("tclass") or "") != rule["tclass"]:
                violations.append(_violation(
                    "CLASS_NOT_OBSERVED",
                    "证据 %s 的对象类是 %s，与规则的 %s 不一致"
                    % (ref, acc.get("tclass"), rule["tclass"]),
                    rule=dict(rule)))
            probe = probes.get(ref) or {}
            resolved = str(probe.get("resolved_target_type") or "")
            if resolved:
                cited_types.add(resolved)
        if cited_types and rule["tgt"] not in cited_types:
            violations.append(_violation(
                "TGT_NOT_EVIDENCED",
                "客体类型 %s 无法从被引用的证据解析得到（证据解析出的是 %s）"
                % (rule["tgt"], ", ".join(sorted(cited_types))),
                rule=dict(rule)))
        if not cited_types:
            violations.append(_violation(
                "TGT_NOT_EVIDENCED",
                "客体类型 %s 没有对应的探测结果，无法验证它确实是被访问资源的标签" % rule["tgt"],
                rule=dict(rule)))


# ──────────────────────────── 黑名单 ────────────────────────────


def _check_blacklist(p: Dict[str, Any], violations: List[Violation],
                     rules: Optional[Sequence[Dict[str, Any]]] = None,
                     library: bool = False) -> None:
    """静态黑名单：高危权限、过宽客体、禁止的对象类、模块名。"""
    rules = p["rules"] if rules is None else list(rules)
    if rules and not library and not MODULE_NAME_RE.match(p["module_name"]):
        violations.append(_violation(
            "MODULE_NAME_INVALID",
            "module_name 必须匹配 ^[a-z][a-z0-9_]{2,30}$，收到 %r" % p["module_name"]))

    forbidden_classes = _LIBRARY_FORBIDDEN_CLASSES if library else FORBIDDEN_CLASSES
    for rule in rules:
        bad_perms = [x for x in rule["perms"] if x in FORBIDDEN_PERMS]
        if bad_perms:
            violations.append(_violation(
                "FORBIDDEN_PERM",
                "权限 %s 属于高危权限（可绕过域转换或直接改动策略），本模块不产出"
                % ", ".join(bad_perms), rule=dict(rule)))
        if len(rule["perms"]) > MAX_PERMS_PER_RULE:
            violations.append(_violation(
                "FORBIDDEN_PERM",
                "单条规则权限数 %d 超过上限 %d，说明授权过宽"
                % (len(rule["perms"]), MAX_PERMS_PER_RULE), rule=dict(rule)))

        if rule["tclass"] in forbidden_classes:
            detail = ("capability 一类内核特权不产出规则" if library else
                      "只处理资源访问类对象，capability/process 一类内核特权不产出规则")
            violations.append(_violation(
                "FORBIDDEN_CLASS",
                "对象类 %s 不在本模块范围内（%s）" % (rule["tclass"], detail),
                rule=dict(rule)))

        if rule["tgt"] in FORBIDDEN_TARGETS or rule["tgt"].endswith("_attribute"):
            violations.append(_violation(
                "FORBIDDEN_TARGET_ATTR",
                "客体 %s 过宽（属性或兜底类型），等于一次性放行一大片类型" % rule["tgt"],
                rule=dict(rule)))
        if _is_unconfined(rule["tgt"]):
            violations.append(_violation(
                "FORBIDDEN_TARGET_ATTR",
                "客体 %s 属于不受限域，向它授权没有意义" % rule["tgt"], rule=dict(rule)))


def _check_source_type(p: Dict[str, Any], evidence: Dict[str, Any],
                       violations: List[Violation]) -> None:
    """源类型必须是证据里真实观察到的域，且不能是不受限域。"""
    src_type = str(evidence.get("source_type") or "")
    if not src_type:
        if p["rules"]:
            violations.append(_violation(
                "SRC_NOT_EVIDENCED", "证据包里没有源类型信息，不能产出任何规则"))
        return

    for rule in p["rules"]:
        if rule["src"] != src_type:
            violations.append(_violation(
                "SRC_NOT_EVIDENCED",
                "规则源类型 %s 与证据里的实际域 %s 不一致；本模块不为未观察到的域编写规则"
                % (rule["src"], src_type), rule=dict(rule)))

    if _is_unconfined(src_type):
        # 改标签针对的是客体标签，与源域是否受限无关，因此 RELABEL_OBJECT 不受此限
        if p["decision"] not in ("NO_CHANGE", "RELABEL_OBJECT"):
            violations.append(_violation(
                "SRC_NOT_EVIDENCED",
                "源类型 %s 不受 SELinux 强制，为它编写 allow 规则没有实际约束效果；"
                "必须判 NO_CHANGE（reason_code=SOURCE_UNCONFINED），"
                "并把'应迁移到受限域'写进 notes（域创建超出本模块范围）" % src_type))


def _check_types_resolved(p: Dict[str, Any], type_facts: Dict[str, Dict[str, Any]],
                          violations: List[Violation]) -> None:
    """类型必须确实存在于本机已加载策略，否则 require 块会编译失败。"""
    for rule in p["rules"]:
        for name in (rule["src"], rule["tgt"]):
            fact = type_facts.get(name)
            if fact is None:
                violations.append(_violation(
                    "TYPE_UNVERIFIED",
                    "类型 %s 没有做过存在性查询，请先调用 query_selinux_policy(type_info=%s)"
                    % (name, name), rule=dict(rule)))
                continue
            if fact.get("in_loaded_policy") is False:
                violations.append(_violation(
                    "TYPE_NOT_IN_LOADED_POLICY",
                    "类型 %s 不在本机已加载策略中（%s），写进 .te 会导致 require 失败"
                    % (name, fact.get("verdict_note") or ""), rule=dict(rule)))
            elif fact.get("in_loaded_policy") is None:
                violations.append(_violation(
                    "TYPE_UNVERIFIED",
                    "本机缺少 seinfo，无法确认类型 %s 是否已加载；"
                    "不输出未经验证的规则" % name, rule=dict(rule)))
            if fact.get("kind") == "attribute":
                violations.append(_violation(
                    "FORBIDDEN_TARGET_ATTR",
                    "%s 是属性而不是具体类型，向属性授权过于宽泛" % name, rule=dict(rule)))


def _check_target_confidence(p: Dict[str, Any], probes: Dict[str, Dict[str, Any]],
                             violations: List[Violation]) -> None:
    """客体类型若只来自兜底模式或源码知识库，就不能作为规则客体。"""
    for rule in p["rules"]:
        for ref in rule.get("evidence") or []:
            probe = probes.get(ref) or {}
            confidence = str(probe.get("target_confidence") or "")
            if confidence == "low":
                violations.append(_violation(
                    "TGT_NOT_EVIDENCED",
                    "证据 %s 的客体类型只命中兜底模式（default_t），"
                    "无法确认 %s 就是真实标签，需在目标机上用 matchpathcon 复核"
                    % (ref, rule["tgt"]), rule=dict(rule)))
            elif confidence == "none" or (probe and probe.get("verdict") == "unknown"
                                          and not probe.get("resolved_target_type")):
                violations.append(_violation(
                    "TGT_NOT_EVIDENCED",
                    "证据 %s 的客体类型未能解析，不能据此产出规则" % ref, rule=dict(rule)))


# ──────────────────────────── 改标签收敛校验 ────────────────────────────

# 只有这些 verdict 说明客体当前确实被放行，才存在"权限过多"可供收敛
_RELABEL_OVERPRIV_VERDICTS = ("allowed", "conditional", "partial")


def _check_relabel(p: Dict[str, Any], evidence: Dict[str, Any],
                   probes: Dict[str, Dict[str, Any]],
                   violations: List[Violation]) -> None:
    """改标签建议的确定性把关。

    镜像安全阀：加 allow 时是"越权证据绝不能变成放行"，改标签时是
    "绝不能因为一轮没看清，就把客体改到一个错误或更宽的类型上"。因此每一项都要：
      1. 引用真实存在、且已 probe_access 过的访问；
      2. 该访问当前确实被放行（否则没有过度权限可收敛）；
      3. 实际标签 ≠ 默认标签（label_mismatch），且 current_type 就是观测到的实际类型；
      4. expected_type 必须等于确定性解析出的默认类型，不得由模型自造；
      5. 默认类型的解析必须可信 —— 泛型/兜底类型或未解析一律弃权（回落 LABEL_MISMATCH）。
    可信但仅来自源码知识库（非目标机 matchpathcon）时，允许输出但强制低置信度 + warn。
    """
    if not p["relabel"]:
        return
    valid = {str(r.get("access_id")) for r in evidence.get("accesses", []) or []}
    for item in p["relabel"]:
        aid = item["access_id"]
        if aid not in valid:
            violations.append(_violation(
                "RELABEL_UNKNOWN_ACCESS",
                "relabel 引用的 %s 不在证据包中（可能是编造的）" % aid, rule=dict(item)))
            continue
        probe = probes.get(aid)
        if not probe:
            violations.append(_violation(
                "RELABEL_UNPROBED",
                "改标签前必须先对 %s 调用 query_selinux_policy(probe_access, access_id=%s)，"
                "取得实际标签与默认类型" % (aid, aid), rule=dict(item)))
            continue
        tr = probe.get("target_resolution") or {}
        verdict = str(probe.get("verdict") or "")
        if verdict not in _RELABEL_OVERPRIV_VERDICTS:
            violations.append(_violation(
                "RELABEL_NOT_OVERPRIV",
                "证据 %s 的探测结论是 %s，当前访问并未被策略放行，没有需要收敛的过度权限；"
                "改标签只用于'已被放行但客体标签过宽'的情形" % (aid, verdict or "unknown"),
                rule=dict(item)))
            continue
        if not tr.get("label_mismatch"):
            violations.append(_violation(
                "RELABEL_NO_MISMATCH",
                "证据 %s 的实际标签与默认标签一致，不存在标签错配，无需改标签" % aid,
                rule=dict(item)))
            continue
        actual = tr.get("actual_label") or {}
        actual_type = str(actual.get("type") or "")
        if not actual_type:
            violations.append(_violation(
                "RELABEL_NO_ACTUAL",
                "证据 %s 读不到客体的实际标签类型（客体可能不存在或无 getxattr 权限），"
                "无法确定从哪个类型改起" % aid, rule=dict(item)))
            continue
        if item["current_type"] != actual_type:
            violations.append(_violation(
                "RELABEL_CURRENT_MISMATCH",
                "relabel 声称当前类型是 %s，但探测到的实际标签类型是 %s；以观测事实为准"
                % (item["current_type"], actual_type), rule=dict(item)))
            continue
        expected_type = str(tr.get("expected_type") or "")
        if item["expected_type"] != expected_type:
            violations.append(_violation(
                "RELABEL_TARGET_UNVERIFIED",
                "改标签目标类型必须等于确定性解析出的默认类型 %s，收到 %s；不得自造类型名"
                % (expected_type or "(未解析)", item["expected_type"]), rule=dict(item)))
            continue
        if not expected_type or tr.get("expected_is_generic") or \
                str(tr.get("expected_trust") or "") not in ("high", "low"):
            p["confidence"] = "low"
            violations.append(_violation(
                "RELABEL_UNTRUSTED",
                "证据 %s 的默认类型解析不可信（%s）；不得据此改标签，"
                "应判 NO_CHANGE(LABEL_MISMATCH) 并提示人工用 matchpathcon 复核"
                % (aid, tr.get("expected_trust_reason") or "泛型/兜底类型或未解析"),
                rule=dict(item)))
            continue
        if expected_type == actual_type:
            violations.append(_violation(
                "RELABEL_NO_MISMATCH",
                "证据 %s 的默认类型与实际类型相同（%s），改标签没有意义" % (aid, expected_type),
                rule=dict(item)))
            continue
        if str(tr.get("expected_trust") or "") == "low":
            # 可信度足够发出建议，但目标类型只来自源码知识库：强制低置信度并要求人工复核
            p["confidence"] = "low"
            violations.append(_violation(
                "RELABEL_KB_UNVERIFIED",
                "证据 %s 的默认类型 %s 来自 refpolicy 源码知识库而非目标机 matchpathcon，"
                "落地前必须在目标机上用 matchpathcon %s 复核确认"
                % (aid, expected_type, item["path"]), level="warn", rule=dict(item)))


# ──────────────────────────── 指定策略库模式 ────────────────────────────

# 库模式下仍不产出的对象类：其余类只要场景 .te 里出现过就可以做规则
_LIBRARY_FORBIDDEN_CLASSES = frozenset({"capability", "capability2", "kernel_service"})


def _library_rule_dicts(p: Dict[str, Any]) -> List[Dict[str, Any]]:
    """新增规则 + edit 的 new_rule 视图，供主体/黑名单/安全阀复用。"""
    out: List[Dict[str, Any]] = [dict(r) for r in p["rules"]]
    for edit in p["edits"]:
        new = edit["new_parsed"]
        if not new:
            continue
        out.append({
            "src": new["src"], "tgt": new["tgt"], "tclass": new["tclass"],
            "perms": list(new["perms"]),
            "evidence": list(edit.get("evidence") or []),
            "reason": edit.get("reason") or "",
            "edit": True,
        })
    return out


def _edit_delta(edit: Dict[str, Any]) -> Dict[str, Any]:
    """一次 edit 相对源码规则的权限增减与客体迁移。"""
    old = edit["old_parsed"] or {}
    new = edit["new_parsed"]
    old_perms = set(old.get("perms") or [])
    new_perms = set(new.get("perms") or []) if new else set()
    moved = bool(new) and (
        new["src"] != old.get("src") or new["tgt"] != old.get("tgt")
        or new["tclass"] != old.get("tclass"))
    return {
        "old_perms": old_perms,
        "new_perms": new_perms,
        "added": sorted(new_perms - old_perms),
        "removed": sorted(old_perms - new_perms),
        "moved": moved,
    }


def _check_library_subject_rules(rules: Sequence[Dict[str, Any]],
                                 scene: Any, violations: List[Violation]) -> None:
    """库模式下的源域与类型存在性：主体固定为场景 subject，类型必须已声明。"""
    for rule in rules:
        if rule["src"] != scene.subject:
            violations.append(_violation(
                "SRC_NOT_EVIDENCED",
                "指定策略库的主体固定为 %s，规则源类型 %s 不匹配"
                % (scene.subject, rule["src"]), rule=dict(rule)))
        tgt = scene.subject if rule["tgt"] == "self" else rule["tgt"]
        if tgt not in scene.types:
            violations.append(_violation(
                "TYPE_NOT_IN_LIBRARY",
                "类型 %s 未在场景 %s 的 .te 中声明；本模块不允许新增类型声明"
                % (tgt, scene.name), rule=dict(rule)))


def _check_library_edits(p: Dict[str, Any], scene: Any,
                         violations: List[Violation]) -> None:
    """old_rule 必须逐字存在于场景源码；新规则的源域/类型必须合法。"""
    if not p["edits"]:
        return
    known = {plib.normalize_rule_text(r.raw or r.text) for r in scene.rules}
    for edit in p["edits"]:
        old = edit["old_parsed"] or {}
        if edit["old_norm"] not in known:
            violations.append(_violation(
                "EDIT_RULE_NOT_FOUND",
                "edits 的 old_rule 不在场景 %s 的源码中（必须逐字来自 .te）：%s"
                % (scene.name, edit["old_rule"]), rule={"old_rule": edit["old_rule"]}))
            continue
        if old.get("src") != scene.subject:
            violations.append(_violation(
                "EDIT_FOREIGN_SUBJECT",
                "只能修改主体 %s 自己的规则，old_rule 的源类型是 %s"
                % (scene.subject, old.get("src")), rule={"old_rule": edit["old_rule"]}))
            continue
        if not edit["is_delete"]:
            _check_library_subject_rules([{
                "src": edit["new_parsed"]["src"], "tgt": edit["new_parsed"]["tgt"],
                "tclass": edit["new_parsed"]["tclass"], "perms": edit["new_parsed"]["perms"],
            }], scene, violations)


def _check_library_sensitive(p: Dict[str, Any], scene: Any,
                             violations: List[Violation]) -> None:
    """敏感目标只允许收窄/删除，任何新增或扩大放行都必须拒绝。"""
    sensitive = set(scene.sensitive_targets or ())

    for rule in p["rules"]:
        tgt = scene.subject if rule["tgt"] == "self" else rule["tgt"]
        if tgt in sensitive:
            violations.append(_violation(
                "OVERPRIVILEGE_GRANTED",
                "场景把 %s 标记为敏感目标，绝不能新增放行它的规则" % tgt,
                rule=dict(rule)))

    for edit in p["edits"]:
        delta = _edit_delta(edit)
        if not delta["moved"] and not delta["added"]:
            continue
        new = edit["new_parsed"] or {}
        tgt = scene.subject if new.get("tgt") == "self" else str(new.get("tgt") or "")
        if tgt in sensitive:
            violations.append(_violation(
                "OVERPRIVILEGE_GRANTED",
                "该编辑向敏感目标 %s 新增/扩大了放行（新增权限 %s），必须拒绝"
                % (tgt, ", ".join(delta["added"]) or "迁移了客体"),
                rule={"old_rule": edit["old_rule"], "new_rule": edit["new_rule"]}))


def _library_valve_rules(p: Dict[str, Any]) -> List[Dict[str, Any]]:
    """送进安全阀的规则：新增规则与真正扩大放行的编辑。

    纯收窄/删除的 edit 不放进来——它保留的权限本来就由源码规则持有，
    再拿它对敏感证据做交集会误伤合法的权限收敛。
    """
    out: List[Dict[str, Any]] = [dict(r) for r in p["rules"]]
    for edit in p["edits"]:
        delta = _edit_delta(edit)
        new = edit["new_parsed"]
        if not new or (not delta["moved"] and not delta["added"]):
            continue
        out.append({
            "src": new["src"], "tgt": new["tgt"], "tclass": new["tclass"],
            "perms": list(new["perms"]),
            "evidence": list(edit.get("evidence") or []),
            "reason": edit.get("reason") or "",
            "edit": True,
        })
    return out


def _check_library_effects(p: Dict[str, Any], scene: Any, applied: Dict[str, Any],
                           violations: List[Violation]) -> None:
    """编辑必须真实改变生效权限：被删掉的权限若仍由别的规则授予，就是空操作。"""
    updated = applied.get("scene")
    if updated is None:
        return

    for edit in p["edits"]:
        delta = _edit_delta(edit)
        if not delta["added"] and not delta["removed"] and not delta["moved"]:
            violations.append(_violation(
                "EDIT_NO_EFFECT",
                "该 edit 的 new_rule 与 old_rule 生效结果完全一致，没有产生任何权限变化；"
                "无需提交这条编辑", rule={"old_rule": edit["old_rule"],
                                          "new_rule": edit["new_rule"]}))
            continue
        old = edit["old_parsed"] or {}
        old_tgt = scene.subject if old.get("tgt") == "self" else str(old.get("tgt") or "")
        tclass = str(old.get("tclass") or "")
        # 删除或换客体时，旧客体失去这条规则的全部权限；收窄时只失去被删的权限
        vacated = delta["old_perms"] if (edit["is_delete"] or delta["moved"]) \
            else (delta["old_perms"] - delta["new_perms"])
        if not vacated:
            continue
        # 排除本次 edit 自己写出的新规则后，旧客体上还剩下哪些权限
        new_norm = plib.normalize_rule_text(edit["new_rule"]) if edit["new_parsed"] else ""
        skipped_self = False
        still_other: set = set()
        for rule in updated.matching_rules(old.get("src") or scene.subject, old_tgt, tclass):
            if new_norm and not skipped_self and \
                    plib.normalize_rule_text(rule.raw or rule.text) == new_norm:
                skipped_self = True
                continue
            still_other |= set(rule.perms)
        leaked = sorted(vacated & still_other)
        if leaked:
            violations.append(_violation(
                "EDIT_NO_EFFECT",
                "编辑移除的权限 %s 仍由场景中的其他 allow 规则授予，收窄/删除不会真正生效；"
                "请一并处理授予这些权限的规则" % ", ".join(leaked),
                rule={"old_rule": edit["old_rule"], "new_rule": edit["new_rule"]}))

    for change in applied.get("changes") or []:
        if change.get("kind") == "noop_add":
            violations.append(_violation(
                "EDIT_NO_EFFECT",
                "新增的规则 %s 已存在于场景源码中，重复提交不会改变策略"
                % change.get("new_rule", ""), rule={"new_rule": change.get("new_rule", "")}))


def _library_required_perms(scene: Any) -> Dict[Tuple[str, str], set]:
    """任务正向测试要求的权限：新增权限即使未被观测到，只要任务要求也算有据。"""
    out: Dict[Tuple[str, str], set] = {}
    for test in scene.tests:
        if not isinstance(test, dict) or not test.get("expected", True):
            continue
        target = str(test.get("target") or test.get("target_type") or "")
        tclass = str(test.get("class") or test.get("tclass") or "")
        perms = {str(p) for p in (test.get("permissions") or test.get("perms") or []) if str(p)}
        if target and tclass:
            out.setdefault((target, tclass), set()).update(perms)
    return out


def _library_observed_perms(evidence: Dict[str, Any], probes: Dict[str, Dict[str, Any]],
                            subject: str) -> Tuple[Dict[Tuple[str, str, str], set],
                                                   Dict[Tuple[str, str], set]]:
    """证据里实际观察到的权限，按 (源域, 客体类型, 类) 与 (源域, 类) 两级索引。"""
    by_target: Dict[Tuple[str, str, str], set] = {}
    by_class: Dict[Tuple[str, str], set] = {}
    for rec in evidence.get("accesses") or []:
        if _is_sensitive_record(rec):
            continue
        tclass = str(rec.get("tclass") or "")
        perms = {str(p) for p in (rec.get("perms") or []) if str(p)}
        by_class.setdefault((subject, tclass), set()).update(perms)
        probe = probes.get(str(rec.get("access_id") or "")) or {}
        tgt = str(probe.get("resolved_target_type") or "")
        if tgt:
            by_target.setdefault((subject, tgt, tclass), set()).update(perms)
    return by_target, by_class


def _check_library_minimality(p: Dict[str, Any], scene: Any, evidence: Dict[str, Any],
                              probes: Dict[str, Dict[str, Any]],
                              violations: List[Violation]) -> None:
    """新增的权限必须有据：证据里观察到，或任务是明确要求。"""
    required = _library_required_perms(scene)
    by_target, by_class = _library_observed_perms(evidence, probes, scene.subject)

    def _allowed_for(tgt: str, tclass: str, perm: str) -> bool:
        if perm in required.get((tgt, tclass), set()):
            return True
        key = (scene.subject, tgt, tclass)
        if key in by_target:
            return perm in by_target[key]
        return perm in by_class.get((scene.subject, tclass), set())

    added_rules = []
    for rule in p["rules"]:
        added_rules.append((dict(rule), list(rule.get("perms") or [])))
    for edit in p["edits"]:
        new = edit["new_parsed"]
        if not new:
            continue
        added_rules.append((
            {"src": new["src"], "tgt": new["tgt"], "tclass": new["tclass"],
             "perms": list(new["perms"]), "evidence": edit.get("evidence") or []},
            _edit_delta(edit)["added"]))

    for rule, perms in added_rules:
        tgt = scene.subject if rule["tgt"] == "self" else rule["tgt"]
        extra = [perm for perm in perms if not _allowed_for(tgt, rule["tclass"], perm)]
        if extra:
            violations.append(_violation(
                "PERM_NOT_OBSERVED",
                "权限 %s 既未在证据中观察到，也不是任务正向测试要求的权限；"
                "不得授予无据权限（客体 %s:%s）"
                % (", ".join(extra), tgt, rule["tclass"]), rule=dict(rule)))


def _check_library_tasks(p: Dict[str, Any], before: Dict[str, Any],
                         after: Dict[str, Any], violations: List[Violation]) -> None:
    """编辑结果必须不破坏任务、且不得新放行任务禁止的访问。"""
    reg = plib.task_regressions(before, after)
    for check in reg["broken"]:
        violations.append(_violation(
            "TASK_REQUIREMENT_BROKEN",
            "编辑后破坏了任务必需的访问「%s」（%s:%s 需要 %s）"
            % (check["name"], check["target"], check["class"],
               ", ".join(check["permissions"]))))
    for check in reg["newly_granted"]:
        violations.append(_violation(
            "TASK_FORBIDDEN_GRANTED",
            "编辑后放行了任务明确禁止的访问「%s」（%s:%s %s）"
            % (check["name"], check["target"], check["class"],
               ", ".join(check["permissions"]))))
    for check in reg["remaining"]:
        if check["expected"]:
            violations.append(_violation(
                "TASK_INCOMPLETE",
                "任务必需的访问「%s」仍未放行（缺 %s），当前建议只修复了一部分问题"
                % (check["name"], ", ".join(check["missing_permissions"])), level="warn"))
        else:
            violations.append(_violation(
                "TASK_STILL_OVERPRIVILEGED",
                "任务禁止的访问「%s」仍被放行，当前建议没有完全收敛权限" % check["name"],
                level="warn"))


def _label_test_paths(scene: Any) -> Dict[str, Dict[str, Any]]:
    """场景里声明过的标签类任务测试：path -> test。"""
    out: Dict[str, Dict[str, Any]] = {}
    for test in scene.tests or []:
        if not isinstance(test, dict):
            continue
        if str(test.get("kind") or "").strip() != "label":
            continue
        path = str(test.get("path") or "").strip()
        if path:
            out[path] = test
    return out


def _check_library_relabel(p: Dict[str, Any], scene: Any, evidence: Dict[str, Any],
                           violations: List[Violation]) -> None:
    """库模式改标签建议的确定性把关（标签夹具）。

    库模式没有目标机 matchpathcon，因此把"实际标签"限制为场景元数据显式声明的
    夹具事实，默认类型只从 .fc 解析。每一项都必须：
      1. 引用真实证据，且证据的资源就是该路径；
      2. 场景为该路径声明了实际标签，且确实与 .fc 默认类型不同；
      3. current_type 等于声明的实际标签，expected_type 等于 .fc 解析结果；
      4. 目标类型是场景 .te 里已声明的具体类型，不得是泛型/兜底类型；
      5. 该访问当前确实被放行（否则没有过度权限可收敛）；
      6. 不得把敏感客体改成非敏感类型（那是放宽，不是收敛）；
      7. 场景必须为该路径声明了标签任务测试，否则无从验证改动效果。
    """
    if not p["relabel"]:
        return
    accesses = {str(r.get("access_id") or ""): r
                for r in evidence.get("accesses", []) or []}
    label_tests = _label_test_paths(scene)
    sensitive = set(scene.sensitive_targets or ())

    for item in p["relabel"]:
        aid = item["access_id"]
        acc = accesses.get(aid)
        if acc is None:
            violations.append(_violation(
                "RELABEL_UNKNOWN_ACCESS",
                "relabel 引用的 %s 不在证据包中（可能是编造的）" % aid, rule=dict(item)))
            continue
        path = item["path"]
        if str(acc.get("resource") or "").strip() != path:
            violations.append(_violation(
                "RELABEL_PATH_MISMATCH",
                "relabel 的 path %s 与证据 %s 的资源 %s 不一致；改标签必须针对被放行的那个客体"
                % (path, aid, acc.get("resource") or ""), rule=dict(item)))
            continue

        actual_type = str(scene.actual_labels.get(path) or "").strip()
        if not actual_type:
            violations.append(_violation(
                "RELABEL_NO_ACTUAL",
                "场景 %s 没有为 %s 声明实际标签；库模式只接受场景元数据里的标签夹具，"
                "不得凭空推断实际标签" % (scene.name, path), rule=dict(item)))
            continue
        resolved = plib.resolve_type(scene, path)
        expected_type = str((resolved or {}).get("type") or "")
        if not expected_type:
            violations.append(_violation(
                "RELABEL_TARGET_UNVERIFIED",
                "路径 %s 未在场景 .fc 中命中，无法确定默认类型，不得改标签" % path,
                rule=dict(item)))
            continue
        if actual_type == expected_type:
            violations.append(_violation(
                "RELABEL_NO_MISMATCH",
                "客体 %s 的实际标签与 .fc 默认类型一致（%s），不存在标签错配" % (path, actual_type),
                rule=dict(item)))
            continue
        if item["current_type"] != actual_type:
            violations.append(_violation(
                "RELABEL_CURRENT_MISMATCH",
                "relabel 声称当前类型是 %s，但场景声明的实际标签是 %s；以声明的夹具事实为准"
                % (item["current_type"], actual_type), rule=dict(item)))
            continue
        if item["expected_type"] != expected_type:
            violations.append(_violation(
                "RELABEL_TARGET_UNVERIFIED",
                "改标签目标类型必须等于场景 .fc 解析出的默认类型 %s，收到 %s；不得自造类型名"
                % (expected_type, item["expected_type"]), rule=dict(item)))
            continue
        if expected_type in GENERIC_FC_TYPES:
            violations.append(_violation(
                "RELABEL_UNTRUSTED",
                "默认类型 %s 是泛型/兜底类型，不能作为改标签目标；"
                "应判 NO_CHANGE(LABEL_MISMATCH) 并提示人工复核" % expected_type,
                rule=dict(item)))
            continue
        if expected_type not in scene.types:
            violations.append(_violation(
                "RELABEL_TARGET_UNVERIFIED",
                "默认类型 %s 未在场景 %s 的 .te 中声明；本模块不允许新增类型声明，"
                "不得把客体改到未声明的类型" % (expected_type, scene.name), rule=dict(item)))
            continue

        if actual_type in sensitive and expected_type not in sensitive:
            violations.append(_violation(
                "RELABEL_DECLASSIFIES_SENSITIVE",
                "客体 %s 当前标签 %s 是场景标记的敏感类型，改到非敏感类型 %s 会扩大可访问范围；"
                "改标签只能收敛权限，不能放宽敏感客体" % (path, actual_type, expected_type),
                rule=dict(item)))
            continue

        tclass = str(acc.get("tclass") or "")
        perms = [str(x) for x in (acc.get("perms") or []) if str(x)]
        actual_perms = scene.effective_perms(scene.subject, actual_type, tclass)
        expected_perms = scene.effective_perms(scene.subject, expected_type, tclass)
        widened = sorted(expected_perms - actual_perms)
        if widened:
            violations.append(_violation(
                "RELABEL_WIDENS_ACCESS",
                "改标签后源域 %s 对 %s 会新增权限 %s（%s -> %s）；"
                "改标签只能收敛权限，不能扩大可访问范围"
                % (scene.subject, path, ", ".join(widened), actual_type, expected_type),
                rule=dict(item)))
            continue

        probe = plib.probe_access(scene, path, tclass, perms)
        if str(probe.get("verdict") or "") not in _RELABEL_OVERPRIV_VERDICTS:
            violations.append(_violation(
                "RELABEL_NOT_OVERPRIV",
                "证据 %s 在场景当前策略下未被放行（verdict=%s），没有需要收敛的过度权限；"
                "改标签只用于'已被放行但客体标签过宽'的情形"
                % (aid, probe.get("verdict") or "unknown"), rule=dict(item)))
            continue
        if path not in label_tests:
            violations.append(_violation(
                "RELABEL_NO_LABEL_TEST",
                "场景 %s 没有为 %s 声明标签任务测试，无法验证改标签效果；"
                "请先补齐测试再给出建议" % (scene.name, path), rule=dict(item)))


def _apply_library_relabel(p: Dict[str, Any], scene: Any, evidence: Dict[str, Any],
                           ctx: Dict[str, Any], violations: List[Violation]) -> None:
    """校验并应用改标签；只有全部通过才更新场景实际标签。"""
    before = plib.evaluate_tests(scene)
    ctx["task_before"] = before
    _check_evidence_refs(p, evidence, violations, require_rule_evidence=False)
    _check_library_relabel(p, scene, evidence, violations)
    if _blocks(violations):
        return

    applied = plib.apply_relabel(scene, p["relabel"])
    updated = applied["scene"]
    ctx["changes"] = applied["changes"]
    ctx["updated_source"] = scene.source
    after = plib.evaluate_tests(updated)
    ctx["task_after"] = after
    if not _blocks(violations):
        _check_library_tasks(p, before, after, violations)


def _validate_library(p: Dict[str, Any], scene: Any, evidence: Dict[str, Any],
                      probes: Dict[str, Dict[str, Any]],
                      sensitive_types: Optional[Dict[str, str]],
                      violations: List[Violation]) -> Dict[str, Any]:
    """指定策略库模式下的完整校验，返回应用编辑后的场景与任务评估。"""
    ctx: Dict[str, Any] = {
        "scene_name": scene.name,
        "scene_title": scene.title,
        "subject": scene.subject,
        "updated_source": "",
        "diff": "",
        "changes": [],
        "task_before": None,
        "task_after": None,
        "apply_errors": [],
    }

    if p["relabel"]:
        if scene.actual_labels:
            _apply_library_relabel(p, scene, evidence, ctx, violations)
        else:
            violations.append(_violation(
                "RELABEL_UNSUPPORTED_IN_LIBRARY",
                "场景 %s 没有声明客体实际标签夹具，无法判断标签是否错配；"
                "该场景只做 allow 规则的增/删/改" % scene.name))
        return ctx

    _check_evidence_refs(p, evidence, violations, require_rule_evidence=False)
    _check_library_edits(p, scene, violations)

    before = plib.evaluate_tests(scene)
    ctx["task_before"] = before

    combined = _library_rule_dicts(p)
    if combined:
        _check_blacklist(p, violations, rules=combined, library=True)
    _check_library_subject_rules([r for r in combined if not r.get("edit")], scene, violations)
    _check_library_sensitive(p, scene, violations)

    valve_rules = _library_valve_rules(p)
    valve_target = dict(p)
    valve_target["rules"] = valve_rules
    _check_safety_valve(valve_target, evidence, probes, violations,
                        sensitive_types=sensitive_types)

    # old_rule 定位失败等结构性错误已足以拒绝，不必再应用一遍
    if _blocks(violations):
        return ctx

    applied = plib.apply_edits(scene, p["edits"], p["rules"])
    ctx["diff"] = applied.get("diff", "")
    ctx["changes"] = applied.get("changes", [])
    ctx["apply_errors"] = list(applied.get("errors") or [])
    for err in ctx["apply_errors"]:
        violations.append(_violation(
            "EDIT_APPLY_FAILED", "无法把建议应用到场景源码：%s" % err))

    if applied.get("errors"):
        return ctx

    updated = applied["scene"]
    after = plib.evaluate_tests(updated)
    ctx["task_after"] = after
    ctx["updated_source"] = applied.get("source", "")

    if not _blocks(violations):
        _check_library_effects(p, scene, applied, violations)
        _check_library_minimality(p, scene, evidence, probes, violations)
        _check_library_tasks(p, before, after, violations)
    return ctx


# ──────────────────────────── .te 渲染与沙箱编译 ────────────────────────────


def _require_block(rules: Sequence[Dict[str, Any]]) -> List[str]:
    types: List[str] = []
    for rule in rules:
        for name in (rule["src"], rule["tgt"]):
            if name not in types:
                types.append(name)
    classes: Dict[str, List[str]] = {}
    for rule in rules:
        slot = classes.setdefault(rule["tclass"], [])
        for perm in rule["perms"]:
            if perm not in slot:
                slot.append(perm)

    lines = ["require {"]
    for name in sorted(types):
        lines.append("\ttype %s;" % name)
    for tclass in sorted(classes):
        perms = sorted(classes[tclass])
        if len(perms) == 1:
            lines.append("\tclass %s %s;" % (tclass, perms[0]))
        else:
            lines.append("\tclass %s { %s };" % (tclass, " ".join(perms)))
    lines.append("}")
    return lines


def render_te(module_name: str, rules: Sequence[Dict[str, Any]],
              comments: Optional[Dict[str, str]] = None) -> str:
    """把校验通过的规则渲染成可用 checkmodule 编译的 .te 文本。

    头部用 ``module <name> 1.0;`` 而不是 refpolicy 的 ``policy_module()`` 宏：
    后者需要 /usr/share/selinux/devel 的 Makefile 与 m4 展开，
    而本模块只做沙箱编译校验，checkmodule 直接吃 module 形式。
    """
    comments = comments or {}
    # 渲染顺序不跟随 LLM 的书写顺序：同一组规则必须逐字节渲染出同一份 .te，
    # 否则 te_sha256 无法作为建议的稳定身份
    rules = sorted(rules, key=lambda r: (r["src"], r["tgt"], r["tclass"], list(r["perms"])))
    lines = ["module %s 1.0;" % module_name, ""]
    lines.extend(_require_block(rules))
    lines.append("")
    for rule in rules:
        comment = comments.get("%s|%s|%s" % (rule["src"], rule["tgt"], rule["tclass"]))
        if comment:
            lines.append("# %s" % comment)
        lines.append("allow %s %s:%s { %s };" % (
            rule["src"], rule["tgt"], rule["tclass"], " ".join(rule["perms"])))
        if rule.get("evidence"):
            lines.append("# 依据证据：%s" % ", ".join(rule["evidence"]))
    return "\n".join(lines) + "\n"


def render_relabel(relabel: Sequence[Dict[str, Any]], confidence: str = "low") -> str:
    """把校验通过的改标签项渲染成人工可执行的说明文本。

    本模块只渲染文本，绝不执行 semanage / restorecon。渲染顺序与输入无关，
    保证同一组改标签项逐字节稳定，便于审计比对。
    """
    items = sorted(relabel, key=lambda r: (r["path"], r["current_type"], r["expected_type"]))
    if confidence == "high":
        trust_note = "目标机 matchpathcon 已解析出具体默认类型，仍需人工确认其他域的依赖"
    else:
        trust_note = "低置信度：默认类型未经目标机 matchpathcon 确认，落地前必须复核"
    lines = ["# 客体标签收敛建议（%s；本模块不会自动应用）" % trust_note,
             "# 目的：把被过度放行的客体从过宽的实际标签改回默认类型，从而收窄可访问它的域"]
    for item in items:
        path = item["path"]
        cur = item["current_type"]
        exp = item["expected_type"]
        lines.append("")
        lines.append("# 客体 %s：%s → %s（依据证据 %s）" % (path, cur, exp, item["access_id"]))
        if item.get("reason"):
            lines.append("# 理由：%s" % item["reason"])
        lines.append("# 第一步先复核默认类型是否确为 %s：" % exp)
        lines.append("matchpathcon %s" % path)
        lines.append("# 若上面已显示 %s，说明 file_contexts 规则已存在，只需重打标签：" % exp)
        lines.append("restorecon -v %s" % path)
        lines.append("# 否则先补/改 file_contexts 规则，再重打标签：")
        lines.append("semanage fcontext -a -t %s %s   # 已存在同路径规则时改用 -m" % (exp, path))
        lines.append("restorecon -v %s" % path)
        lines.append("# 风险：本模块无法枚举其他域对 %s 在 %s 下的合法依赖，"
                     "改标签可能影响它们，务必人工确认后再执行" % (path, cur))
    return "\n".join(lines) + "\n"


def _compile_check(module_name: str, te_text: str) -> Dict[str, Any]:
    """在临时目录里用 checkmodule 做沙箱编译校验。

    只生成 .mod/.pp 到临时目录并立即删除；绝不执行 semodule 安装。
    """
    checkmodule = shutil.which("checkmodule")
    if not checkmodule:
        return {"attempted": False, "ok": False, "skipped": True,
                "detail": "本机没有 checkmodule（dnf install checkpolicy），未做编译校验"}
    workdir = tempfile.mkdtemp(prefix="clawavc_gate_")
    try:
        te_path = os.path.join(workdir, "%s.te" % module_name)
        mod_path = os.path.join(workdir, "%s.mod" % module_name)
        with open(te_path, "w", encoding="utf-8") as fh:
            fh.write(te_text)
        proc = subprocess.run(
            [checkmodule, "-M", "-m", "-o", mod_path, te_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
            cwd=workdir, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C"},
            shell=False,
        )
        err = proc.stderr.decode("utf-8", "replace").strip()
        return {
            "attempted": True,
            "ok": proc.returncode == 0,
            "detail": err[:800],
            "returncode": proc.returncode,
        }
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"attempted": True, "ok": False, "detail": "编译校验异常：%s" % exc}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ──────────────────────────── 主入口 ────────────────────────────


def validate(proposal: Dict[str, Any], evidence: Dict[str, Any],
             probes: Optional[Dict[str, Dict[str, Any]]] = None,
             type_facts: Optional[Dict[str, Dict[str, Any]]] = None,
             compile_check: bool = True,
             sensitive_types: Optional[Dict[str, str]] = None,
             library: Optional[Any] = None) -> Dict[str, Any]:
    """校验 LLM 提交的策略建议。

    probes: access_id -> probe_access 的结果
    type_facts: 类型名 -> type_info 的结果
    sensitive_types: 敏感访问的 access_id -> 解析出的客体类型，
    用于对「同类型间接放行」给出 warn（工具层负责解析，见 xy_skill）
    library: 指定策略库模式下的当前 Scene（policy_library.Scene）。传入后按场景
    .te 做增/删/改与任务测试评估，不再依赖目标机 SELinux 工具。
    """
    probes = probes or {}
    type_facts = type_facts or {}
    violations: List[Violation] = []

    if not isinstance(proposal, dict):
        return _result({"decision": "NO_CHANGE", "reason_code": "EVIDENCE_INSUFFICIENT",
                        "summary": "", "module_name": "", "rules": [], "edits": [],
                        "relabel": [], "notes": [], "evidence_refs": [], "must_not_allow": [],
                        "target_policy_version": "", "confidence": "low"},
                       [_violation("SCHEMA_INVALID", "提案必须是 JSON 对象")], evidence)

    p = _check_shape(proposal, violations)
    _check_decision_consistency(p, violations, library=library is not None)

    library_ctx: Optional[Dict[str, Any]] = None
    if library is not None:
        library_ctx = _validate_library(p, library, evidence, probes,
                                        sensitive_types, violations)
    else:
        _check_evidence_refs(p, evidence, violations)
        _check_safety_valve(p, evidence, probes, violations, sensitive_types=sensitive_types)
        _check_source_type(p, evidence, violations)

        if p["rules"] and not _blocks(violations):
            _check_blacklist(p, violations)
            _check_types_resolved(p, type_facts, violations)
            _check_target_confidence(p, probes, violations)
            _check_minimality(p, evidence, probes, violations)

        # 改标签与 allow 规则互斥，各自独立校验；有阻断时都不渲染
        if p["relabel"] and not _blocks(violations):
            _check_relabel(p, evidence, probes, violations)

    te_text = ""
    te_sha256 = ""
    relabel_text = ""
    relabel_sha256 = ""
    compile_result: Dict[str, Any] = {"attempted": False, "ok": False, "skipped": True,
                                      "detail": "没有规则需要编译"}
    if library is not None:
        compile_result = {"attempted": False, "ok": False, "skipped": True,
                          "detail": "指定策略库模式不做沙箱编译，按场景任务测试评估"}
        if p["relabel"] and not _blocks(violations):
            # 库模式的默认类型来自 .fc 而非目标机 matchpathcon，渲染文本按低置信度提示复核
            relabel_text = render_relabel(p["relabel"], confidence="low")
            relabel_sha256 = hashlib.sha256(relabel_text.encode("utf-8")).hexdigest()
    elif p["rules"] and not _blocks(violations):
        comments = {}
        for rule in p["rules"]:
            if rule.get("reason"):
                comments["%s|%s|%s" % (rule["src"], rule["tgt"], rule["tclass"])] = rule["reason"]
        te_text = render_te(p["module_name"], p["rules"], comments)
        te_sha256 = hashlib.sha256(te_text.encode("utf-8")).hexdigest()
        if compile_check:
            compile_result = _compile_check(p["module_name"], te_text)
            if compile_result.get("attempted") and not compile_result.get("ok"):
                violations.append(_violation(
                    "COMPILE_FAILED",
                    "沙箱 checkmodule 编译失败：%s" % (compile_result.get("detail") or "未知错误")))
        else:
            compile_result = {"attempted": False, "ok": False, "skipped": True,
                              "detail": "调用方要求跳过编译校验"}
    elif p["relabel"] and not _blocks(violations):
        # 改标签不产生 .te，无模块可编译；渲染人工执行说明并留一份稳定哈希供审计
        relabel_text = render_relabel(p["relabel"], confidence=p["confidence"])
        relabel_sha256 = hashlib.sha256(relabel_text.encode("utf-8")).hexdigest()
        compile_result = {"attempted": False, "ok": False, "skipped": True,
                          "detail": "改标签建议不涉及 .te 编译"}

    return _result(p, violations, evidence, te_text, te_sha256, compile_result,
                   relabel_text, relabel_sha256, library=library_ctx)


def _result(p: Dict[str, Any], violations: List[Violation], evidence: Dict[str, Any],
            te_text: str = "", te_sha256: str = "",
            compile_result: Optional[Dict[str, Any]] = None,
            relabel_text: str = "", relabel_sha256: str = "",
            library: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    blocks = _blocks(violations)
    warns = _warns(violations)
    ok = not blocks

    compile_result = dict(compile_result or {"attempted": False, "ok": False,
                                             "skipped": True, "detail": "没有规则需要编译"})
    if not ok:
        # 校验未通过时不输出规则/改标签文本，编译结果也不再有意义
        te_text = ""
        te_sha256 = ""
        relabel_text = ""
        relabel_sha256 = ""
        compile_result = {"attempted": False, "ok": False, "skipped": True,
                          "detail": "存在阻断性校验失败，建议未输出"}

    decision = p["decision"] if ok else "NO_CHANGE"
    reason_code = p["reason_code"]
    if not ok:
        # 被拦下的建议一律回落到 NO_CHANGE，理由码也必须自洽且能说明被拦的原因
        derived = _blocked_reason(blocks, evidence)
        if derived or reason_code not in _NO_CHANGE_REASONS:
            reason_code = derived or "EVIDENCE_INSUFFICIENT"

    out: Dict[str, Any] = {
        "ok": ok,
        "decision": decision,
        "reason_code": reason_code,
        "summary": p["summary"],
        "module_name": p["module_name"] if ok and p["rules"] else "",
        "target_policy_version": p.get("target_policy_version", ""),
        "rules": p["rules"] if ok else [],
        "edits": p["edits"] if ok and decision in ("MODIFY_ALLOW", "DELETE_ALLOW") else [],
        "relabel": p["relabel"] if ok and decision == "RELABEL_OBJECT" else [],
        "relabel_text": relabel_text,
        "relabel_sha256": relabel_sha256,
        "te": te_text,
        "te_sha256": te_sha256,
        "notes": p["notes"],
        "evidence_refs": p["evidence_refs"],
        "must_not_allow": p["must_not_allow"],
        "confidence": p["confidence"],
        "violations": [dict(v) for v in violations],
        "block_codes": sorted({v["code"] for v in blocks}),
        "warnings": sorted({v["code"] for v in warns}),
        "compile": compile_result,
        "source_type": evidence.get("source_type", ""),
        "selinux_posture": evidence.get("selinux_posture", {}),
    }
    if library is not None:
        out["library"] = {
            "scene": library.get("scene_name", ""),
            "scene_title": library.get("scene_title", ""),
            "subject": library.get("subject", ""),
            "updated_source": library.get("updated_source", "") if ok else "",
            "diff": library.get("diff", "") if ok else "",
            "changes": library.get("changes", []) if ok else [],
            "task_before": library.get("task_before"),
            "task_after": library.get("task_after"),
            "apply_errors": library.get("apply_errors", []),
        }
        if ok and library.get("scene_name"):
            out["module_name"] = library["scene_name"]
    if blocks:
        out["blocked_note"] = (
            "建议未通过确定性校验，已拒绝输出规则文本。原因：%s"
            % "; ".join(sorted({v["code"] for v in blocks}))
        )
    return out


# ──────────────────────────── 文本输出 ────────────────────────────


def feedback(result: Dict[str, Any]) -> str:
    """把阻断原因整理成回灌给 LLM 的修正指令。"""
    violations = result.get("violations") or []
    blocks = [v for v in violations if v.get("level") == "block"]
    if not blocks:
        return ""
    lines = ["你的策略建议未通过确定性校验，必须修正后重新提交："]
    for index, v in enumerate(blocks, 1):
        lines.append("%d. [%s] %s" % (index, v["code"], v["message"]))
        rule = v.get("rule")
        if rule:
            lines.append("   涉及规则：%s" % _rule_text(rule))
    lines.append("")
    if result.get("library"):
        lines.append(
            "修正原则（指定策略库模式）：old_rule 必须逐字来自场景 .te；"
            "删除整条规则用 edits.new_rule 留空，收窄/补权用 old_rule→new_rule；"
            "新增规则用 rules/add_rules。不得新增类型声明，source 固定为场景主体。"
        )
        lines.append(
            "权限必须有据：只能授予证据里观察到的权限，或场景任务正向测试明确要求的权限；"
            "敏感目标只允许删除或收窄，绝不能新增/扩大放行；"
            "编辑不得破坏任务必需的访问，也不得新放行任务禁止的访问。"
        )
        if any(str(v.get("code", "")).startswith("TASK_") for v in blocks):
            lines.append(
                "任务修正原则：编辑后必须保留任务需要的权限，并去掉任务禁止的权限；"
                "若一次改动无法同时满足，请把所有需要调整的规则都写进同一次提案的 edits 中。"
            )
    else:
        lines.append(
            "修正原则：授予的权限不得超出证据里实际观察到的权限；"
            "越权访问（隐私资源、未申报的高危访问）绝不能产出 allow 规则，只能判 NO_CHANGE；"
            "类型名必须是查询确认存在于本机已加载策略的具体类型，不能是属性或兜底类型。"
        )
    if any(str(v.get("code", "")).startswith("RELABEL_") for v in blocks):
        lines.append(
            "改标签修正原则：relabel 项只能引用已 probe_access 过、当前被放行、"
            "且实际标签≠默认标签的访问；expected_type 必须等于探测解析出的默认类型，"
            "不得自造；默认类型解析为泛型/兜底或不可信时必须弃权，改判 NO_CHANGE(LABEL_MISMATCH)。"
        )
    return "\n".join(lines)


def _rule_text(rule: Dict[str, Any]) -> str:
    if not isinstance(rule, dict):
        return str(rule)[:160]
    if rule.get("old_rule") or rule.get("new_rule"):
        old = str(rule.get("old_rule") or "") or "（新增）"
        new = str(rule.get("new_rule") or "") or "（删除）"
        return "%s  ->  %s" % (old, new)
    if not rule.get("tclass"):
        return str(rule)[:160]
    return "allow %s %s:%s { %s };" % (
        rule.get("src", "?"), rule.get("tgt", "?"), rule.get("tclass", "?"),
        " ".join(rule.get("perms") or []))


def render_report(result: Dict[str, Any]) -> str:
    """给最终报告用的建议正文。"""
    lines = ["策略建议：%s（%s）" % (result["decision"], result["reason_code"])]
    if result.get("blocked_note"):
        # 被拒绝的提案，理由行是 LLM 原始说法，必须紧跟拒绝结论，否则会被当成通过的理由读
        lines.append("  警告：%s" % result["blocked_note"])
        for v in result.get("violations", []):
            if v.get("level") == "block":
                lines.append("    - [%s] %s" % (v["code"], v["message"]))
    lines.append("  理由：%s" % (result.get("summary") or "（无）"))
    if result.get("source_type"):
        lines.append("  源域：%s" % result["source_type"])
    posture = result.get("selinux_posture") or {}
    if posture:
        lines.append("  目标机状态：mode=%s policyvers=%s" % (
            posture.get("mode", "?"), posture.get("policyvers", "?")))

    if result.get("library"):
        return _render_library_report(result, lines)

    if result["decision"] == "NO_CHANGE" or not result.get("rules"):
        if result["decision"] == "RELABEL_OBJECT" and result.get("relabel"):
            lines.append("  置信度：%s" % (result.get("confidence") or "-"))
            lines.append("  改标签项 sha256：%s" % (result.get("relabel_sha256") or "")[:16])
            for note in result.get("notes", []):
                lines.append("  说明：%s" % note)
            for v in result.get("violations", []):
                if v.get("level") == "warn":
                    lines.append("  警告：[%s] %s" % (v["code"], v["message"]))
            lines.append("")
            lines.append("  改标签建议（需人工在目标机复核后执行 semanage/restorecon，本模块不会自动应用）：")
            lines.append("  " + "\n  ".join(result.get("relabel_text", "").rstrip().splitlines()))
            return "\n".join(lines)
        for note in result.get("notes", []):
            lines.append("  说明：%s" % note)
        for v in result.get("violations", []):
            if v.get("level") == "warn":
                lines.append("  警告：[%s] %s" % (v["code"], v["message"]))
        return "\n".join(lines)

    lines.append("  模块名：%s  policyvers：%s  sha256：%s" % (
        result.get("module_name", ""), result.get("target_policy_version", ""),
        (result.get("te_sha256") or "")[:16]))
    compile_info = result.get("compile") or {}
    if compile_info.get("attempted"):
        lines.append("  沙箱编译校验：%s%s" % (
            "通过" if compile_info.get("ok") else "失败",
            "（%s）" % compile_info["detail"][:120] if compile_info.get("detail") else ""))
    elif compile_info.get("skipped"):
        lines.append("  沙箱编译校验：未执行（%s）" % compile_info.get("detail", ""))
    for note in result.get("notes", []):
        lines.append("  说明：%s" % note)
    for v in result.get("violations", []):
        if v.get("level") == "warn":
            lines.append("  警告：[%s] %s" % (v["code"], v["message"]))
    lines.append("")
    lines.append("  .te 内容（需人工在目标机上执行 checkmodule/semodule_package/semodule -i，本模块不会自动应用）：")
    lines.append("  " + "\n  ".join(result.get("te", "").rstrip().splitlines()))
    return "\n".join(lines)


def _task_line(task: Optional[Dict[str, Any]]) -> str:
    if not task:
        return "-"
    return "%s/%s%s" % (task.get("passed", 0), task.get("total", 0),
                        "（全部符合）" if task.get("fully_correct") else "")


def _render_library_report(result: Dict[str, Any], lines: List[str]) -> str:
    """指定策略库模式下的报告：改动清单、任务前后对比、编辑后的 .te。"""
    lib = result.get("library") or {}
    lines.append("  策略场景：%s（主体 %s）" % (lib.get("scene", ""), lib.get("subject", "")))
    for note in result.get("notes", []):
        lines.append("  说明：%s" % note)
    for v in result.get("violations", []):
        if v.get("level") == "warn":
            lines.append("  警告：[%s] %s" % (v["code"], v["message"]))

    if not result.get("ok"):
        lines.append("  任务测试（改动前）：%s" % _task_line(lib.get("task_before")))
        return "\n".join(lines)

    changes = lib.get("changes") or []
    if changes:
        lines.append("  改动清单：")
        for change in changes:
            if change.get("kind") == "relabel":
                lines.append("    - 改标签：%s：%s -> %s" % (
                    change.get("path", ""), change.get("old_label") or "（未声明）",
                    change.get("new_label", "")))
                continue
            kind = {"delete": "删除", "modify": "修改", "add": "新增",
                    "noop_add": "无变化"}.get(change.get("kind"), change.get("kind"))
            lines.append("    - %s：%s" % (kind, change.get("new_rule") or change.get("old_rule")))
            if change.get("kind") == "modify":
                lines.append("      原规则：%s" % change.get("old_rule"))
    lines.append("  任务测试：改动前 %s -> 改动后 %s" % (
        _task_line(lib.get("task_before")), _task_line(lib.get("task_after"))))
    if result.get("decision") == "RELABEL_OBJECT" and result.get("relabel"):
        lines.append("")
        lines.append("  改标签建议（需人工在目标机复核后执行 semanage/restorecon，本模块不会自动应用）：")
        lines.append("  " + "\n  ".join(result.get("relabel_text", "").rstrip().splitlines()))
        return "\n".join(lines)
    lines.append("")
    lines.append("  变更 diff：")
    diff = lib.get("diff") or ""
    lines.append("  " + "\n  ".join(diff.rstrip().splitlines()) if diff else "  （无差异）")
    lines.append("")
    lines.append("  修改后的 .te（需人工在目标机复核后编译安装，本模块不会自动应用）：")
    lines.append("  " + "\n  ".join((lib.get("updated_source") or "").rstrip().splitlines()))
    return "\n".join(lines)
