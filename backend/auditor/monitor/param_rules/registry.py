# -*- coding: utf-8 -*-
"""参数内容检测规则注册表。

职责：
1. 汇总规则组件（path_rules / content_rules），提供给前端渲染配置表单的目录；
2. 把用户配置与内置默认值合并成每条规则的实际生效配置（含启用开关、严重级、阈值、词表）；
3. 执行检测主流程（遍历参数 → 分派给对应规则组件 → 汇总去重）。

配置兼容三种写法（旧格式仍有效）：
- 字符串：该规则的严重级，如 "traversal_escape": "critical"
- 列表：词表类规则（inject_markers / semantic_markers）
- 对象：{"severity": "high", "enabled": false, "min_token": 40, ...}
"""
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

from .base import Hit, ParamCtx, Rule, RuleGroup, worst_severity
from .content_rules import CONTENT_RULES, CMD_CLASSES
from .path_rules import PATH_RULES, is_write_tool

PATH_KEY_TOKENS = ["path", "file", "url", "dir", "script", "filename", "save",
                   "wrapper", "dest"]
CONTENT_KEY_TOKENS = ["content", "body", "message", "text", "code", "command",
                      "transcript"]

_SEVERITIES = {"critical", "high", "medium", "low"}


def _rule_defaults(rule: Rule) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {"enabled": rule.default_enabled}
    for p in ([rule.param] if rule.param else []) + rule.extra_params:
        cfg[p.name] = p.default
    # 规则自身的默认严重级优先于 severity 参数的通用默认值，
    # 否则各规则会被统一覆盖成同一个级别（曾导致 P1 默认显示为 high）。
    cfg["severity"] = rule.severity
    return cfg


def _rule_cfg(side_cfg: Dict[str, Any], rule: Rule) -> Dict[str, Any]:
    """把用户配置归一成该规则的生效配置。"""
    cfg = _rule_defaults(rule)
    raw = side_cfg.get(rule.key)

    if isinstance(raw, dict):
        if "enabled" in raw:
            cfg["enabled"] = bool(raw["enabled"])
        for p in ([rule.param] if rule.param else []) + rule.extra_params:
            if p.name in raw and raw[p.name] is not None:
                cfg[p.name] = raw[p.name]
        if isinstance(raw.get("severity"), str) and raw["severity"] in _SEVERITIES:
            cfg["severity"] = raw["severity"]
    elif isinstance(raw, str) and raw in _SEVERITIES:
        cfg["severity"] = raw
    elif isinstance(raw, list):
        cfg["markers"] = raw

    # 旧字段兼容：inject_severity / semantic_severity / semantic_requires_shebang
    if not isinstance(raw, dict):
        legacy_sev_key = {"inject_markers": "inject_severity",
                          "semantic_markers": "semantic_severity"}.get(rule.key)
        if legacy_sev_key and isinstance(side_cfg.get(legacy_sev_key), str) \
                and side_cfg[legacy_sev_key] in _SEVERITIES:
            cfg["severity"] = side_cfg[legacy_sev_key]
        legacy_en_key = {"inject_markers": "inject_enabled",
                         "semantic_markers": "semantic_enabled"}.get(rule.key)
        if legacy_en_key and legacy_en_key in side_cfg:
            cfg["enabled"] = bool(side_cfg[legacy_en_key])
    if rule.key == "semantic_markers" and "semantic_requires_shebang" in side_cfg:
        cfg["requires_shebang"] = bool(side_cfg["semantic_requires_shebang"])

    cfg["_markers"] = cfg.get("markers") or []
    return cfg


DEFAULT_PARAM_CONTENT_RULES: Dict[str, Any] = {
    "path": {r.key: r.severity for r in PATH_RULES},
    "content": {
        "encoded_blob": {"min_token": 40, "severity": "high", "escalate": "critical"},
        "cmd_co_occurrence": {"classes": 2, "severity": "critical", "severity_single": "medium"},
        "inject_markers": ["[SYSTEM NOTICE]", "[SYSTEM INSTRUCT]", "<INFORMATION>",
                           "ignore all previous", "忽略以上", "忽略之前", "remember-rule"],
        "inject_severity": "critical",
        "semantic_markers": ["persistent_service", "hidden_persist", "backdoor",
                             "reverse_shell", "exfiltrate", "V_PERSISTENT"],
        "semantic_requires_shebang": True,
        "semantic_severity": "high",
        "obfuscation": "high",
    },
}
DEFAULT_PARAM_CONTENT_RULES["path"]["key_tokens"] = list(PATH_KEY_TOKENS)
DEFAULT_PARAM_CONTENT_RULES["content"]["key_tokens"] = list(CONTENT_KEY_TOKENS)


GROUPS = [
    RuleGroup("path", "路径类参数规则（path）",
              "针对路径/目标类参数（键名含 path/file/url/dir/script 等）：逃逸、特殊路径、写类落盘等",
              PATH_RULES),
    RuleGroup("content", "内容类参数规则（content）",
              "针对内容类参数（键名含 content/body/message/text/code/command 等）：注入标记、编码载荷、命令特征等",
              CONTENT_RULES),
]


def catalog(active_rules: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """返回前端渲染配置表单所需的规则目录（含默认值与当前生效值）。"""
    active_rules = active_rules if isinstance(active_rules, dict) else {}
    groups = []
    for g in GROUPS:
        side_cfg = active_rules.get(g.side) if isinstance(active_rules.get(g.side), dict) else {}
        rules = []
        for r in g.rules:
            cfg = _rule_cfg(side_cfg, r)
            d = r.to_dict()
            d["active"] = {"enabled": cfg["enabled"]}
            for p in d["params"]:
                d["active"][p["name"]] = cfg.get(p["name"])
            rules.append(d)
        groups.append({**g.to_dict(), "rules": rules})
    return {"groups": groups, "severities": ["critical", "high", "medium", "low"],
            "cmd_classes": list(CMD_CLASSES.keys())}


def _merge_rules(rules: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """深拷贝默认值 + 用户配置（段级覆盖，键级覆盖）。"""
    merged = {side: dict(sec) for side, sec in DEFAULT_PARAM_CONTENT_RULES.items()}
    if isinstance(rules, dict):
        for side in ("path", "content"):
            user_side = rules.get(side)
            if isinstance(user_side, dict):
                merged[side].update(user_side)
    return merged


def _iter_hits(hits) -> List[Hit]:
    if hits is None:
        return []
    if isinstance(hits, Hit):
        return [hits]
    return [h for h in hits if isinstance(h, Hit)]


def check_param_content(action: Any, rules: Optional[Dict[str, Any]] = None) -> List[Dict[str, str]]:
    """执行参数内容检测，返回命中列表（同一 tool+param+rule 只报一次）。"""
    merged = _merge_rules(rules)
    path_cfg = merged.get("path") or {}
    content_cfg = merged.get("content") or {}
    path_tokens = path_cfg.get("key_tokens") or PATH_KEY_TOKENS
    content_tokens = content_cfg.get("key_tokens") or CONTENT_KEY_TOKENS

    path_plan = [(_rule_cfg(path_cfg, r), r) for r in PATH_RULES]
    content_plan = [(_rule_cfg(content_cfg, r), r) for r in CONTENT_RULES]

    results: List[Dict[str, str]] = []
    reported = set()

    def _emit(hit: Hit):
        key = (hit.tool, hit.param, hit.rule)
        if key in reported:
            return
        reported.add(key)
        results.append(hit.as_dict())

    action_list = action if isinstance(action, list) else [action]
    for item in action_list:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool", "")).strip() or "(unknown)"
        args = item.get("arguments")
        if not isinstance(args, dict):
            continue
        write_tool = is_write_tool(tool)
        for pname, pval in args.items():
            if not isinstance(pval, str) or not pval:
                continue
            plk = pname.lower()
            decoded = pval
            for _ in range(2):
                nxt = unquote(decoded)
                if nxt == decoded:
                    break
                decoded = nxt
            ctx = ParamCtx(tool=tool, name=pname, raw=pval, lower=pval.lower(),
                           decoded=decoded, write_tool=write_tool)

            if any(t in plk for t in path_tokens):
                for cfg, rule in path_plan:
                    if not cfg["enabled"]:
                        continue
                    if rule.needs_write_tool and not write_tool:
                        continue
                    for h in _iter_hits(rule.check(ctx, cfg)):
                        _emit(h)

            if any(t in plk for t in content_tokens):
                for cfg, rule in content_plan:
                    if not cfg["enabled"]:
                        continue
                    for h in _iter_hits(rule.check(ctx, cfg)):
                        _emit(h)

    return results


def check_param_content_to_text(action: Any, rules: Optional[Dict[str, Any]] = None) -> str:
    """参数内容检测结论文本；无可扫描参数时返回空串。"""
    scanned = 0
    action_list = action if isinstance(action, list) else [action]
    for item in action_list:
        if isinstance(item, dict) and isinstance(item.get("arguments"), dict):
            scanned += sum(1 for v in item["arguments"].values() if isinstance(v, str) and v)
    if scanned == 0:
        return ""

    hits = check_param_content(action, rules)
    lines = ["", "【参数内容检测】已扫描参数值："]
    if not hits:
        lines.append("  - 检测结果: 正常，参数内容未发现路径逃逸或载荷特征。")
        return "\n".join(lines)

    worst = worst_severity([h["severity"] for h in hits]) or "medium"
    lines.append(f"  - 检测结果: 异常，参数内容命中深度检查规则（最高严重级: {worst}）")
    for h in hits:
        lines.append(f"    * 工具 [{h['tool']}] 参数 [{h['param']}] "
                     f"命中 {h['rule']}({h['severity']}): {h['evidence']}")
    return "\n".join(lines)
