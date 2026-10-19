"""工具函数模块：工具结果精简渲染（编排层）。

原先这些函数定义在 app.py 模块级，现集中到此处，由 app.py 与 xy_skill.py
共同导入，避免两处各维护一份实现。全部为纯函数，不访问数据库、不执行命令。
"""

import json
import re
from pathlib import Path


def _try_json(raw):
    """尝试解析 JSON；已是 dict/list 直接返回，否则按字符串解析。返回 (obj, ok)。"""
    if isinstance(raw, (dict, list)):
        return raw, True
    if not isinstance(raw, str) or not raw.strip():
        return None, False
    try:
        return json.loads(raw), True
    except Exception:
        return None, False


def _raw_or_json(raw):
    """解析失败时回退为原样字符串（灾备）。"""
    obj, ok = _try_json(raw)
    if ok:
        return obj
    return raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)


def _read_file_text(path):
    """安全读取文件文本，失败返回 None。"""
    try:
        p = Path(path)
        if not p.exists() or not p.is_file():
            return None
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def _simplify_ir_json(raw):
    """精简 IR 权限声明：保留 主体/客体(类型+标识+动作+参数)。解析失败原样返回。"""
    obj, ok = _try_json(raw)
    if not ok or not isinstance(obj, dict):
        return raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    try:
        level2 = obj.get("level2") or obj
        policies = level2.get("policies") if isinstance(level2, dict) else None
        if not policies:
            return json.dumps(obj, ensure_ascii=False)
        lines = []
        for p in policies:
            subject = p.get("subject", "（未知主体）")
            effect = p.get("effect", "")
            objs = p.get("objects", []) or []
            items = []
            for o in objs:
                typ = o.get("type", "")
                ident = o.get("identifier", "")
                acts = ",".join(o.get("actions", []) or [])
                params = ",".join(
                    f"{pp.get('name')}={pp.get('identifier')}"
                    for pp in (o.get("params") or [])
                    if isinstance(pp, dict)
                )
                parts = [typ, ident, f"actions=[{acts}]"]
                if params:
                    parts.append(f"params=[{params}]")
                items.append(" / ".join(parts))
            lines.append(f"- 主体 {subject}（effect={effect}）: " + ("; ".join(items) if items else "（无对象）"))
        return "\n".join(lines)
    except Exception:
        return raw if isinstance(raw, str) else json.dumps(obj, ensure_ascii=False)


def _simplify_action_json(raw):
    """精简用户态工具调用：保留 工具名/参数/资源。解析失败原样返回。"""
    obj, ok = _try_json(raw)
    if not ok:
        return raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    if isinstance(obj, dict):
        obj = obj.get("actions") or obj.get("tool_calls") or [obj]
    if not isinstance(obj, list):
        obj = [obj]
    try:
        lines = []
        for act in obj:
            if not isinstance(act, dict):
                continue
            tool = act.get("tool") or act.get("tool_name") or "（未知工具）"
            args = act.get("arguments") or act.get("args") or {}
            arg_str = ", ".join(f"{k}={v}" for k, v in args.items()) if isinstance(args, dict) else str(args)
            res = act.get("resources") or []
            res_str = ""
            if res:
                res_items = []
                for r in res:
                    if isinstance(r, dict):
                        res_items.append(f"{r.get('type', '')}:{r.get('path', r.get('identifier', ''))}({r.get('access', '')})")
                    else:
                        res_items.append(str(r))
                res_str = " | 资源: " + ", ".join(res_items)
            lines.append(f"- 工具 {tool}；参数: {arg_str}{res_str}")
        return "\n".join(lines) if lines else "（无行为记录）"
    except Exception:
        return raw if isinstance(raw, str) else json.dumps(obj, ensure_ascii=False)


def _simplify_resource_facts(raw):
    """精简内核态资源事实：保留 文件访问(路径/动作/读取字节) 与 网络访问(目标/动作)。"""
    obj, ok = _try_json(raw)
    if not ok or not isinstance(obj, dict):
        return raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    try:
        tool_calls = obj.get("tool_calls") or []
        lines = []
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            facts = tc.get("resource_facts") or []
            for f in facts:
                if not isinstance(f, dict):
                    continue
                typ = f.get("type", "")
                if typ == "file_access":
                    path = f.get("path", "")
                    actions = ",".join(f.get("actions", []) or [])
                    ro = f.get("read_returned_bytes")
                    line = f"  文件 {path} 动作=[{actions}]"
                    if ro:
                        line += f" 读取字节={ro}"
                    lines.append(line)
                elif typ == "network_access":
                    target = f.get("network_target") or f.get("remote_ip", "")
                    actions = ",".join(f.get("actions", []) or [])
                    lines.append(f"  网络 {target} 动作=[{actions}] connect={f.get('connect_count', '')}")
                else:
                    lines.append(f"  {typ}: {json.dumps(f, ensure_ascii=False)}")
        if not lines:
            return json.dumps(obj, ensure_ascii=False)
        header = f"工具调用数: {obj.get('tool_call_count', '')}"
        return header + "\n" + "\n".join(lines)
    except Exception:
        return raw if isinstance(raw, str) else json.dumps(obj, ensure_ascii=False)


def _simplify_judge(obj):
    """通用精简：内核态 LSM Hook 判断 / 系统调用分析结果。保留 verdict/risk/summary/
    tool_analysis/syscall_analysis/alerts，并兜底保留其它顶层字段。失败返回 None。"""
    if not isinstance(obj, dict):
        return None
    try:
        out = {}
        out["round_id"] = obj.get("round_id", "")
        det = obj.get("detector")
        out["detector"] = det.get("name", "") if isinstance(det, dict) else det
        out["verdict"] = obj.get("verdict", "")
        out["risk_score"] = obj.get("risk_score", "")
        out["summary"] = obj.get("summary", "")
        ta = obj.get("tool_analysis") or {}
        if isinstance(ta, dict):
            out["tool_analysis"] = {
                "expected_tool": ta.get("expected_tool"),
                "actual_tool": ta.get("actual_tool"),
                "authorized": ta.get("authorized"),
                "arguments": ta.get("arguments"),
            }
        sa = obj.get("syscall_analysis") or {}
        if isinstance(sa, dict):
            out["syscall_analysis"] = {
                k: sa.get(k)
                for k in ("processed_event_count", "tool_call_count", "unattributed_event_count",
                          "tool_alert_count", "syscall_alert_count", "alert_count")
                if k in sa
            }
        alerts = obj.get("alerts") or []
        if isinstance(alerts, list):
            # 去重聚合：相同 类型/规则/级别/信息/资源 的告警合并，只记录命中次数与 pid 列表
            grouped = {}
            order = []
            for a in alerts:
                if not isinstance(a, dict):
                    continue
                res = a.get("resource")
                if isinstance(res, dict):
                    res = res.get("path") or res.get("type")
                key = (a.get("alert_type"), a.get("rule_id"), a.get("severity"),
                       a.get("message"), res)
                if key not in grouped:
                    grouped[key] = {
                        "alert_type": a.get("alert_type"),
                        "rule_id": a.get("rule_id"),
                        "severity": a.get("severity"),
                        "message": a.get("message"),
                        "resource": res,
                        "count": 0,
                        "pids": [],
                    }
                    order.append(key)
                g = grouped[key]
                g["count"] += 1
                pid = a.get("pid")
                if pid is not None and pid not in g["pids"]:
                    g["pids"].append(pid)
            simple_alerts = []
            for key in order:
                g = grouped[key]
                # count==1 时省略聚合字段，保持简洁
                if g["count"] == 1:
                    g.pop("count", None)
                    g["pid"] = g.pop("pids")[0] if g["pids"] else None
                    if g.get("pid") is None:
                        g.pop("pid", None)
                    else:
                        g.pop("pids", None)
                simple_alerts.append({k: v for k, v in g.items() if v not in (None, [], "")})
            if simple_alerts:
                out["alerts"] = simple_alerts
        # 兜底：保留未显式处理的顶层字段，但跳过已知冗余字段与空值，避免臃肿
        handled = {"round_id", "detector", "verdict", "risk_score", "summary",
                   "tool_analysis", "syscall_analysis", "alerts"}
        # tool_analyses 与 tool_analysis 重复；error/None 等空值无信息量
        redundant = {"tool_analyses"}
        for k, v in obj.items():
            if k in handled or k in redundant:
                continue
            if v in (None, "", [], {}):
                continue
            out[k] = v
        return json.dumps(out, ensure_ascii=False, indent=2)
    except Exception:
        return None


def _simplify_syscall_judge(raw):
    """精简 syscall_judge（JSON 内容）。解析失败原样返回。"""
    obj, ok = _try_json(raw)
    if not ok:
        return raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    simplified = _simplify_judge(obj)
    return simplified if simplified else (raw if isinstance(raw, str) else json.dumps(obj, ensure_ascii=False))


def _simplify_kernel_judge_from_path(path):
    """读取 judge_result_kernel（markdown 文件路径）内容并精简；
    解析失败时按顺序回退：尝试提取 ```json 代码块 → 原样文件内容 → 仅返回路径。"""
    if not path or not str(path).strip():
        return ""
    text = _read_file_text(path)
    if text is None:
        return f"（无法读取 LSM Hook 结果文件：{path}）"
    obj, ok = _try_json(text)
    if not ok:
        m = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
        if m:
            obj, ok = _try_json(m.group(1))
    if ok:
        simplified = _simplify_judge(obj)
        return simplified if simplified else text
    # 灾备：原样返回文件内容
    return text


def _simplify_local_policy(raw):
    """精简本地 SELinux 策略数据，保留关键信息供 LLM 阅读。"""
    obj, ok = _try_json(raw)
    if not ok or not isinstance(obj, dict):
        return raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    try:
        out = {
            "source": obj.get("source", ""),
            "policy_path": obj.get("policy_path", ""),
        }
        types = obj.get("types", [])
        if types:
            if isinstance(types[0], dict):
                type_names = [t.get("name", "") for t in types if t.get("kind") == "type"]
                out["type_count"] = len(types)
                out["type_declarations"] = type_names[:50]
            else:
                out["type_count"] = len(types)
        booleans = obj.get("booleans", [])
        if booleans:
            out["boolean_count"] = len(booleans)
            out["booleans"] = [
                {"name": b.get("name", ""), "default": b.get("default", "")}
                for b in booleans[:30]
            ] if isinstance(booleans[0], dict) else booleans[:30]
        rules = obj.get("allow_rules", [])
        if rules:
            # 只给条数不给样本：十几万条规则里摘 20 条，会让 LLM 把
            # 「样本里没有」误读成「策略里没有」，进而编造出不存在的策略缺口
            out["rule_count"] = len(rules)
        if obj.get("allow_rules_note"):
            out["allow_rules_note"] = obj["allow_rules_note"]
        interfaces = obj.get("interfaces", [])
        if interfaces:
            out["interface_count"] = len(interfaces)
        fctxs = obj.get("file_contexts", [])
        if fctxs:
            out["file_context_count"] = len(fctxs)
        errors = obj.get("errors", [])
        if errors:
            out["errors"] = errors[:5]
        return json.dumps(out, ensure_ascii=False, indent=2)
    except Exception:
        return raw if isinstance(raw, str) else json.dumps(obj, ensure_ascii=False)
