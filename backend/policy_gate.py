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

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple

DECISIONS = ("ADD_ALLOW", "MODIFY_ALLOW", "NO_CHANGE")

# NO_CHANGE 的理由码：布尔开关、标签错配、permissive 模式等属于检测能力，
# 只写进说明，不产出规则
REASON_CODES = {
    "MISSING_RULE": "策略里确实没有对应 allow 规则",
    "INSUFFICIENT_PERMS": "已有规则但权限不全",
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

# 与 NO_CHANGE 自洽的理由码；MISSING_RULE / INSUFFICIENT_PERMS 必须伴随规则产出
_NO_CHANGE_REASONS = frozenset(REASON_CODES) - {"MISSING_RULE", "INSUFFICIENT_PERMS"}
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

MAX_RULES = 20
MAX_PERMS_PER_RULE = 24
MAX_NOTES = 30
MAX_REASON_LEN = 400
MAX_SUMMARY_LEN = 2000

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

    rules = _norm_rules(proposal.get("rules"), violations)
    if len(rules) > MAX_RULES:
        violations.append(_violation(
            "TOO_MANY_RULES", "规则数 %d 超过上限 %d，只保留前 %d 条"
            % (len(rules), MAX_RULES, MAX_RULES)))
        rules = rules[:MAX_RULES]

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


def _check_decision_consistency(p: Dict[str, Any], violations: List[Violation]) -> None:
    """三态决策与规则/理由是否自洽。"""
    if p["decision"] == "NO_CHANGE":
        if p["rules"]:
            violations.append(_violation(
                "DECISION_RULE_MISMATCH",
                "decision=NO_CHANGE 却给出了 %d 条规则；要么改判为 ADD_ALLOW/MODIFY_ALLOW，"
                "要么清空 rules" % len(p["rules"])))
    elif not p["rules"]:
        violations.append(_violation(
            "DECISION_RULE_MISMATCH",
            "decision=%s 但 rules 为空；没有规则可产出时必须判 NO_CHANGE" % p["decision"]))
    elif p["decision"] == "MODIFY_ALLOW":
        # MODIFY_ALLOW 意味着已有规则但权限不全，必须说明改哪一条
        if not any("已有" in n or "修改" in n or "missing" in n.lower() for n in p["notes"]):
            violations.append(_violation(
                "DECISION_RULE_MISMATCH",
                "decision=MODIFY_ALLOW 需要在 notes 里说明现有规则缺哪些权限",
                level="warn"))

    if p["decision"] == "NO_CHANGE" and p["reason_code"] in ("MISSING_RULE", "INSUFFICIENT_PERMS"):
        violations.append(_violation(
            "DECISION_RULE_MISMATCH",
            "reason_code=%s 与 decision=NO_CHANGE 矛盾" % p["reason_code"]))
    if p["decision"] in ("ADD_ALLOW", "MODIFY_ALLOW") and p["reason_code"] in (
            "ALREADY_ALLOWED", "SOURCE_UNCONFINED", "OVERPRIVILEGE_ONLY", "LABEL_MISMATCH",
            "BOOLEAN_GATED", "PERMISSIVE_MODE", "EVIDENCE_INSUFFICIENT", "NOT_POLICY_ISSUE"):
        violations.append(_violation(
            "DECISION_RULE_MISMATCH",
            "reason_code=%s（%s）不能作为产出 allow 规则的依据"
            % (p["reason_code"], REASON_CODES[p["reason_code"]])))


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
                         violations: List[Violation]) -> None:
    """引用的 access_id 必须真实存在于证据包中。"""
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
                "每条规则必须引用至少一个 access_id 作为依据", rule=dict(rule)))
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


def _check_blacklist(p: Dict[str, Any], violations: List[Violation]) -> None:
    """静态黑名单：高危权限、过宽客体、禁止的对象类、模块名。"""
    if p["rules"] and not MODULE_NAME_RE.match(p["module_name"]):
        violations.append(_violation(
            "MODULE_NAME_INVALID",
            "module_name 必须匹配 ^[a-z][a-z0-9_]{2,30}$，收到 %r" % p["module_name"]))

    for rule in p["rules"]:
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

        if rule["tclass"] in FORBIDDEN_CLASSES:
            violations.append(_violation(
                "FORBIDDEN_CLASS",
                "对象类 %s 不在本模块范围内（只处理资源访问类对象，"
                "capability/process 一类内核特权不产出规则）" % rule["tclass"],
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
        if p["decision"] != "NO_CHANGE":
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
             sensitive_types: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """校验 LLM 提交的策略建议。

    probes: access_id -> selinux_policy_query.probe_access 的结果
    type_facts: 类型名 -> selinux_policy_query.type_info 的结果
    sensitive_types: 敏感访问的 access_id -> 解析出的客体类型，
    用于对「同类型间接放行」给出 warn（工具层负责解析，见 xy_skill）
    两者都由工具层在执行过程中记录，缺失会让对应校验判为"未验证"而拒绝输出。
    """
    probes = probes or {}
    type_facts = type_facts or {}
    violations: List[Violation] = []

    if not isinstance(proposal, dict):
        return _result({"decision": "NO_CHANGE", "reason_code": "EVIDENCE_INSUFFICIENT",
                        "summary": "", "module_name": "", "rules": [], "notes": [],
                        "evidence_refs": [], "must_not_allow": [],
                        "target_policy_version": "", "confidence": "low"},
                       [_violation("SCHEMA_INVALID", "提案必须是 JSON 对象")], evidence)

    p = _check_shape(proposal, violations)
    _check_decision_consistency(p, violations)
    _check_evidence_refs(p, evidence, violations)
    _check_safety_valve(p, evidence, probes, violations, sensitive_types=sensitive_types)
    _check_source_type(p, evidence, violations)

    if p["rules"] and not _blocks(violations):
        _check_blacklist(p, violations)
        _check_types_resolved(p, type_facts, violations)
        _check_target_confidence(p, probes, violations)
        _check_minimality(p, evidence, probes, violations)

    te_text = ""
    te_sha256 = ""
    compile_result: Dict[str, Any] = {"attempted": False, "ok": False, "skipped": True,
                                      "detail": "没有规则需要编译"}
    if p["rules"] and not _blocks(violations):
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

    return _result(p, violations, evidence, te_text, te_sha256, compile_result)


def _result(p: Dict[str, Any], violations: List[Violation], evidence: Dict[str, Any],
            te_text: str = "", te_sha256: str = "",
            compile_result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    blocks = _blocks(violations)
    warns = _warns(violations)
    ok = not blocks

    compile_result = dict(compile_result or {"attempted": False, "ok": False,
                                             "skipped": True, "detail": "没有规则需要编译"})
    if not ok:
        # 校验未通过时不输出规则文本，编译结果也不再有意义
        te_text = ""
        te_sha256 = ""
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
    lines.append(
        "修正原则：授予的权限不得超出证据里实际观察到的权限；"
        "越权访问（隐私资源、未申报的高危访问）绝不能产出 allow 规则，只能判 NO_CHANGE；"
        "类型名必须是查询确认存在于本机已加载策略的具体类型，不能是属性或兜底类型。"
    )
    return "\n".join(lines)


def _rule_text(rule: Dict[str, Any]) -> str:
    if not isinstance(rule, dict):
        return str(rule)[:160]
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

    if result["decision"] == "NO_CHANGE" or not result.get("rules"):
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
