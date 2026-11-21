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

# 路径类参数键名启发：命中其一即走 path 规则组
PATH_KEY_TOKENS = ["path", "file", "url", "dir", "script", "filename", "save",
                   "wrapper", "dest"]
# 内容类参数键名启发：键名含 content/body/message/text/code/command/transcript
CONTENT_KEY_TOKENS = ["content", "body", "message", "text", "code", "command",
                      "transcript"]

# 严重级合法值集合：配置写入前校验，防手误
_SEVERITIES = {"critical", "high", "medium", "low"}


def _rule_defaults(rule: Rule) -> Dict[str, Any]:
    """
    规则默认配置组装：enabled + 全部参数默认值 + 规则自身严重级。

    严重级取 rule.severity 而非参数通用默认：
    防止所有规则被统一覆盖成同一级别（P1 曾因此显示为 high）。

    Args:
        rule: 规则组件。

    Returns:
        默认配置 dict。
    """
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

    # 配置三形态兼容从这里分流：dict 完整覆盖 / str 仅严重级 / list 词表
    if isinstance(raw, dict):
        if "enabled" in raw:
            cfg["enabled"] = bool(raw["enabled"])
        for p in ([rule.param] if rule.param else []) + rule.extra_params:
            if p.name in raw and raw[p.name] is not None:
                cfg[p.name] = raw[p.name]
        if isinstance(raw.get("severity"), str) and raw["severity"] in _SEVERITIES:
            cfg["severity"] = raw["severity"]
    # 字符串形态视为严重级：旧配置一键降级场景
    elif isinstance(raw, str) and raw in _SEVERITIES:
        cfg["severity"] = raw
    # 列表形态视为词表：inject_markers / semantic_markers 的旧写法
    elif isinstance(raw, list):
        cfg["markers"] = raw

    # 旧字段兼容映射：inject_severity/semantic_severity/inject_enabled 等仍有效
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
    # semantic_requires_shebang 的旧字段独立兼容：bool 写法
    if rule.key == "semantic_markers" and "semantic_requires_shebang" in side_cfg:
        cfg["requires_shebang"] = bool(side_cfg["semantic_requires_shebang"])

    # _markers 是词表规则的运行态键：check 组件只认它
    cfg["_markers"] = cfg.get("markers") or []
    return cfg


# 默认配置与内置规则同步生成：改规则组件默认值即改出厂配置
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
# key_tokens 也写入默认配置：参数分派用词表可调
DEFAULT_PARAM_CONTENT_RULES["path"]["key_tokens"] = list(PATH_KEY_TOKENS)
DEFAULT_PARAM_CONTENT_RULES["content"]["key_tokens"] = list(CONTENT_KEY_TOKENS)


# 两个规则组对应前端两个配置卡片：path 组与 content 组
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
    # active_rules 缺省空 dict：目录接口在无配置时也返回默认值
    active_rules = active_rules if isinstance(active_rules, dict) else {}
    groups = []
    for g in GROUPS:
        side_cfg = active_rules.get(g.side) if isinstance(active_rules.get(g.side), dict) else {}
        rules = []
        for r in g.rules:
            # 目录含 active 段：前端同时拿到「默认值 + 当前生效值」便于对比展示
            cfg = _rule_cfg(side_cfg, r)
            d = r.to_dict()
            d["active"] = {"enabled": cfg["enabled"]}
            for p in d["params"]:
                d["active"][p["name"]] = cfg.get(p["name"])
            rules.append(d)
        groups.append({**g.to_dict(), "rules": rules})
    # cmd_classes 随目录下发：共现规则的类别下拉直接渲染
    return {"groups": groups, "severities": ["critical", "high", "medium", "low"],
            "cmd_classes": list(CMD_CLASSES.keys())}


# 段级 update 语义决定配置粒度：改一条规则只覆盖该键，其余默认保留
# 深拷贝防污染：默认配置字典不被用户配置就地修改（每次检测重新合并）
# 段级覆盖而不是深度合并：用户配置整段替换 path/content 后仍保留未覆盖键（key_tokens）
def _merge_rules(rules: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """深拷贝默认值 + 用户配置（段级覆盖，键级覆盖）。"""
    # 合并规则 = path 组 + content 组：检测主流程的唯一规则来源
    merged = {side: dict(sec) for side, sec in DEFAULT_PARAM_CONTENT_RULES.items()}
    if isinstance(rules, dict):
        for side in ("path", "content"):
            user_side = rules.get(side)
            if isinstance(user_side, dict):
                merged[side].update(user_side)
    return merged


# 展平时过滤非 Hit 元素：规则实现失误不会把杂质带进结果
def _iter_hits(hits) -> List[Hit]:
    """
    命中列表展平（规则可能返回单 Hit 或列表）。

    Args:
        hits: None / Hit / List[Hit]。

    Returns:
        Hit 列表。
    """
    if hits is None:
        return []
    if isinstance(hits, Hit):
        return [hits]
    # 返回 dict 列表（非 Hit）：落库与 JSON 序列化友好，Hit 仅组件内部使用
    return [h for h in hits if isinstance(h, Hit)]


# 本函数是 judge() 与平台前端的共用入口：同一命中口径双端一致
def check_param_content(action: Any, rules: Optional[Dict[str, Any]] = None) -> List[Dict[str, str]]:
    """执行参数内容检测，返回命中列表（同一 tool+param+rule 只报一次）。"""
    # 检测主入口：遍历 action 参数 → 按键名分派规则 → 汇总去重
    merged = _merge_rules(rules)
    path_cfg = merged.get("path") or {}
    content_cfg = merged.get("content") or {}
    # key_tokens 可被配置覆盖：参数分派启发词表可调（key_tokens 配置项）
    path_tokens = path_cfg.get("key_tokens") or PATH_KEY_TOKENS
    content_tokens = content_cfg.get("key_tokens") or CONTENT_KEY_TOKENS

    # 两轮 URL 解码：双重编码（%252e）在 decoded 中还原为真实序列
    # plan 预组装：规则配置只算一次，参数循环内纯判定（检测吞吐保障）
    path_plan = [(_rule_cfg(path_cfg, r), r) for r in PATH_RULES]
    content_plan = [(_rule_cfg(content_cfg, r), r) for r in CONTENT_RULES]
# 同一 工具+参数+规则 只报一次：去重键三要素

    results: List[Dict[str, str]] = []
    # 写类规则跳过非写工具：P7/P9 的 needs_write_tool 声明在此生效
    reported = set()

    # _emit 闭包持去重集：同键重复命中在源头吞掉，报告永不重复
    def _emit(hit: Hit):
        """
        单次命中转上报文本行（写入判定报告【参数内容检测】区块）。

        Args:
            hit: 单次命中。

        Returns:
            格式化文本行。
        """
        key = (hit.tool, hit.param, hit.rule)
        if key in reported:
            return
        reported.add(key)
        results.append(hit.as_dict())

    # action 单元素包装：单工具调用与列表统一处理
    action_list = action if isinstance(action, list) else [action]
    for item in action_list:
        if not isinstance(item, dict):
            continue
        # 工具名缺省 (unknown)：无 tool 字段的异常行为仍参与检测
        tool = str(item.get("tool", "")).strip() or "(unknown)"
        args = item.get("arguments")
        if not isinstance(args, dict):
            continue
        write_tool = is_write_tool(tool)
        # 仅字符串参数参与扫描：数值/结构化参数无路径语义
        for pname, pval in args.items():
            if not isinstance(pval, str) or not pval:
                continue
            plk = pname.lower()
            # 解码循环至多两轮且收敛即停：非编码参数零额外开销
            decoded = pval
            for _ in range(2):
                nxt = unquote(decoded)
                if nxt == decoded:
                    break
                decoded = nxt
            # ParamCtx 一次构造两组复用：path 与 content 共享上下文不重复解码
            ctx = ParamCtx(tool=tool, name=pname, raw=pval, lower=pval.lower(),
                           decoded=decoded, write_tool=write_tool)

            # 参数可同时命中两组（如 script_path）：path 与 content 判定互不排斥
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


# scanned 计数先于检测：无可扫描参数时连「正常」结论都不输出
def check_param_content_to_text(action: Any, rules: Optional[Dict[str, Any]] = None) -> str:
    """参数内容检测结论文本；无可扫描参数时返回空串。"""
    # 文本渲染入口：未启用规则时返回空串（区块不输出）
    scanned = 0
    action_list = action if isinstance(action, list) else [action]
    # 报告按工具分组：同工具多参数命中归并展示，逐条附 severity 与证据
    for item in action_list:
        if isinstance(item, dict) and isinstance(item.get("arguments"), dict):
            scanned += sum(1 for v in item["arguments"].values() if isinstance(v, str) and v)
    if scanned == 0:
        return ""

    # 正常路径也输出结论：审计可确认「已扫描且未发现」，与「未扫描」区分
    hits = check_param_content(action, rules)
    lines = ["", "【参数内容检测】已扫描参数值："]
    if not hits:
        lines.append("  - 检测结果: 正常，参数内容未发现路径逃逸或载荷特征。")
        return "\n".join(lines)

    # worst_severity 汇总：报告头给出最高严重级，便于快速分诊
    worst = worst_severity([h["severity"] for h in hits]) or "medium"
    lines.append(f"  - 检测结果: 异常，参数内容命中深度检查规则（最高严重级: {worst}）")
    for h in hits:
        lines.append(f"    * 工具 [{h['tool']}] 参数 [{h['param']}] "
                     f"命中 {h['rule']}({h['severity']}): {h['evidence']}")
    return "\n".join(lines)
