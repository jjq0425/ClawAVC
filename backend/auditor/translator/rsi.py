# -*- coding: utf-8 -*-
"""RSI（自进化）：基于历史 round 数据与用户反馈，迭代优化角色策略库。

设计要点：
  1. AI 只产出「结构化结论」（越权风险 / 应放宽 / 策略改造方向），
     落盘一律复用既有 skill（clawavc-policy-creator）与 ai_writer 编排层；
  2. 产物只落在新建角色库 policies/<role>/，基线 default/ops 只读；
  3. 进化作用域：仅策略库内容（scenes.json / tools/*.json / 引导文档），不改翻译提示词；
  4. 一次进化 = 一条 evolution run（含 parent_run_id），形成可追溯的迭代链。
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent                 # backend/auditor/translator
BACKEND_DIR = _HERE.parent.parent                       # backend/
RUNS_ROOT = _HERE / ".rsi_runs"

CFG_PREFIX = "rsi."
CFG_KEYS = ["api_base_url", "model", "temperature", "timeout", "json_mode", "max_tokens"]
CFG_DEFAULTS = {
    "api_base_url": "https://api.longcat.chat/openai",
    "model": "LongCat-2.0-Preview",
    "temperature": "0",
    "timeout": "120",
    "json_mode": "1",
    "max_tokens": "",
}
PROMPT_KEYS = ["prompt_analyze", "prompt_relax", "prompt_transform"]

try:
    from auditor.translator import policy_manager  # type: ignore
except Exception:  # pragma: no cover
    from . import policy_manager  # type: ignore


DEFAULT_PROMPT_ANALYZE = """你是 ClawAVC 的策略自进化分析引擎（RSI）。

输入包含两部分：
  ① 若干历史 Round 的真实数据（用户 query、翻译得到的 IR、实际行为 action、判定结果与得分）；
  ② 当前策略库摘要（场景清单、各工具函数的允许值/拒绝清单/路径白名单、引导文档要点）、角色说明与用户提示词。

任务：
  1. risks     —— 越权风险：实际行为或 IR 授权超出角色应有的最小权限，需要收紧；
  2. relax     —— 应放宽：被策略误拦、阻碍角色正常工作的合理行为，需要放宽；
  3. transform —— 策略改造方向：明确到目标文件与字段（现值 → 建议值）。

只输出一个 JSON 对象，禁止 Markdown 代码块与解释文字：
{
  "risks":     [{"round_id":"","scene":"","tool":"","param":"","behavior":"","violation":"","severity":"high|medium|low","action":""}],
  "relax":     [{"round_id":"","scene":"","tool":"","blocked_behavior":"","reason":"","action":""}],
  "transform": [{"target":"scenes.json|tools/<scene>.json","path":"","current":"","proposed":"","reason":"","risk_level":"high|medium|low"}],
  "summary": "",
  "assumptions": ""
}

规则：
  - 只依据给定数据判断；缺失信息写入 assumptions，不要臆造 round；
  - 收紧优先于放宽（deny-wins）；无法判断时不产出该项；
  - transform.path 用点分路径，如 functions.exec.params.command.constraint_spec.static.denylist。
"""

DEFAULT_PROMPT_RELAX = """【放宽判定准则】
- 仅当行为属于角色职责范围内、且被拦截 solely 因为策略过紧时，才建议放宽；
- 放宽必须附带替代性收紧（限定路径/域名/命令范围），不得无条件放开；
- 涉及删除、提权、数据外发、网络访问的行为默认不放宽。
"""

DEFAULT_PROMPT_TRANSFORM = """【改造建议准则】
- target 只取 scenes.json 或 tools/<scene>.json；path 用点分路径定位到具体字段；
- proposed 必须是可直接写入的合法值（字符串或字符串数组），不允许写代码或表达式；
- 新增拒绝项并入 denylist，并从 allowed_values 移除同串项（deny-wins）；
- risk_level：high=影响面大需人工复核，medium=建议采纳，low=可选优化。
"""

DEFAULT_PROMPTS = {
    "prompt_analyze": DEFAULT_PROMPT_ANALYZE,
    "prompt_relax": DEFAULT_PROMPT_RELAX,
    "prompt_transform": DEFAULT_PROMPT_TRANSFORM,
}


# ──────────────────────────────── 配置读写 ────────────────────────────────
def _db():
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    import db  # type: ignore

    return db


def _cfg(key: str, default: str = "") -> str:
    try:
        val = _db().get_config(f"{CFG_PREFIX}{key}")
        return val if val is not None else default
    except Exception:
        return default


def _set_cfg(key: str, value: str) -> None:
    try:
        _db().set_config(f"{CFG_PREFIX}{key}", value)
    except Exception as e:
        raise RuntimeError(f"配置写入失败：{e}")


def get_config() -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    for k in CFG_KEYS:
        raw = _cfg(k, "")
        data[k] = raw if raw != "" else CFG_DEFAULTS.get(k, "")
    key = _cfg("api_key", "")
    data["api_key"] = ""
    data["has_api_key"] = bool(key)
    data["api_key_masked"] = (key[:4] + "****" + key[-4:]) if len(key) > 8 else ("****" if key else "")
    return {"ok": True, "data": data}


def set_config(data: Dict[str, Any]) -> Dict[str, Any]:
    changed: List[str] = []
    for k in CFG_KEYS:
        if k in data and data[k] is not None:
            _set_cfg(k, str(data[k]))
            changed.append(k)
    if data.get("api_key"):
        _set_cfg("api_key", str(data["api_key"]))
        changed.append("api_key")
    return {"ok": True, "data": {"changed": changed}}


def llm_config() -> Dict[str, Any]:
    temp_str = _cfg("temperature", CFG_DEFAULTS["temperature"])
    timeout_str = _cfg("timeout", CFG_DEFAULTS["timeout"])
    return {
        "api_base_url": _cfg("api_base_url", CFG_DEFAULTS["api_base_url"]),
        "api_key": _cfg("api_key", ""),
        "model": _cfg("model", CFG_DEFAULTS["model"]),
        "temperature": float(temp_str) if str(temp_str).strip() else 0.0,
        "timeout": int(timeout_str) if str(timeout_str).strip() else 120,
        "json_mode": _cfg("json_mode", CFG_DEFAULTS["json_mode"]) in ("1", ""),
        "max_tokens": (_cfg("max_tokens", "") or "").strip(),
    }


def test_connection() -> Dict[str, Any]:
    cfg = llm_config()
    if not cfg.get("api_key"):
        return {"ok": False, "error": "API Token 未配置，请在「RSI 自进化 → AI 参数」抽屉中配置"}
    try:
        from auditor.translator.core import call_llm
    except Exception:
        from .core import call_llm  # type: ignore
    t0 = time.time()
    content, meta = call_llm("你是连通性自检助手。", "请只回复：ok", cfg, max_retry=0)
    return {"ok": True, "data": {"model": cfg.get("model"), "endpoint": meta.get("endpoint", ""),
                                 "latency_ms": int((time.time() - t0) * 1000),
                                 "reply": (content or "")[:80]}}


def get_prompts() -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    for k in PROMPT_KEYS:
        raw = _cfg(k, "")
        data[k] = raw if raw.strip() else DEFAULT_PROMPTS[k]
    data["is_default"] = {k: (not _cfg(k, "").strip()) for k in PROMPT_KEYS}
    return {"ok": True, "data": data}


def set_prompts(data: Dict[str, Any]) -> Dict[str, Any]:
    changed = []
    for k in PROMPT_KEYS:
        if k in data and isinstance(data[k], str):
            _set_cfg(k, data[k])
            changed.append(k)
    return {"ok": True, "data": {"changed": changed}}


def restore_prompts() -> Dict[str, Any]:
    """恢复默认提示词：清空自定义值，使其回落到内置 DEFAULT_PROMPTS。"""
    for k in PROMPT_KEYS:
        _set_cfg(k, "")
    return {"ok": True, "data": {"restored": PROMPT_KEYS}}


# ─────────────────────────── ② 上下文汇聚 ───────────────────────────
def _trunc(text: Any, n: int = 400) -> str:
    s = "" if text is None else str(text)
    return s if len(s) <= n else s[:n] + f"…(截断 {len(s)}→{n})"


def _load_json_obj(raw: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except Exception:
            return raw
    return raw


def _behaviors_brief(action_json: Any, max_items: int = 6) -> List[str]:
    obj = _load_json_obj(action_json)
    items = obj if isinstance(obj, list) else (obj.get("behaviors") if isinstance(obj, dict) else [])
    out: List[str] = []
    if not isinstance(items, list):
        return out
    for it in items[:max_items]:
        if not isinstance(it, dict):
            out.append(_trunc(it, 60))
            continue
        tool = str(it.get("tool", "")).strip()
        args = it.get("arguments")
        arg_s = json.dumps(args, ensure_ascii=False) if isinstance(args, (dict, list)) else str(args or "")
        res_list = it.get("resources") or []
        res_s = ",".join(str(r.get("path", r)) for r in res_list if isinstance(r, dict))[:60]
        out.append(f"{tool}({_trunc(arg_s, 80)}) -> {_trunc(res_s, 60)}"[:150])
    return out


def _ir_digest(ir: Any) -> Any:
    """IR 精简摘要：场景清单 + 授权工具/参数键值，替代整份 JSON（控制体积）。"""
    if not isinstance(ir, dict):
        return _trunc(ir, 300)
    l2 = ir.get("level2") or {}
    scenes = l2.get("level1") or ir.get("level1") or []
    pols: List[Dict[str, Any]] = []
    for p in (l2.get("policies") or [])[:10]:
        if not isinstance(p, dict):
            continue
        objs: List[Dict[str, Any]] = []
        for o in (p.get("objects") or [])[:20]:
            if not isinstance(o, dict):
                continue
            ent: Dict[str, Any] = {"id": o.get("identifier"), "actions": o.get("actions")}
            ps = o.get("params")
            if ps:
                ent["params"] = [f"{x.get('name')}={_trunc(x.get('identifier'), 60)}"
                                 for x in ps[:6] if isinstance(x, dict)]
            objs.append(ent)
        pols.append({"subject": p.get("subject"), "objects": objs})
    return {"scenes": scenes, "policies": pols}


def round_digest(rec: Dict[str, Any]) -> Dict[str, Any]:
    """把一条 round 记录压成给 AI 看的摘要（控制体积）。"""
    ir = _load_json_obj(rec.get("ir_json"))
    return {
        "round_id": rec.get("round_id", ""),
        "time_start": rec.get("time_start", ""),
        "user_query": _trunc(rec.get("user_query"), 300),
        "overall_score": rec.get("overall_score"),
        "is_abnormal": rec.get("is_abnormal"),
        "judge_result": _trunc(rec.get("judge_result"), 400),
        "ir_brief": _ir_digest(ir),
        "behaviors": _behaviors_brief(rec.get("action_json"), max_items=6),
    }


def _policy_summary(policy: Optional[str] = None) -> Dict[str, Any]:
    reg = Path(policy_manager.resolve_registry_path(policy))
    scenes_obj: Dict[str, Any] = {}
    sp = reg / "scenes.json"
    if sp.is_file():
        try:
            scenes_obj = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:
            scenes_obj = {}
    tools: Dict[str, Any] = {}
    tdir = reg / "tools"
    if tdir.is_dir():
        for tf in sorted(tdir.glob("*.json")):
            try:
                obj = json.loads(tf.read_text(encoding="utf-8"))
            except Exception:
                continue
            fns = obj.get("functions") or {}
            brief: Dict[str, Any] = {}
            for fname, fdef in list(fns.items())[:10]:
                params = fdef.get("params") or {}
                pbrief: Dict[str, Any] = {}
                for pname, pdef in list(params.items())[:4]:
                    cs = (pdef or {}).get("constraint_spec") or {}
                    st = cs.get("static")
                    blocks = st if isinstance(st, list) else ([st] if isinstance(st, dict) else [])
                    allow_v, allow_l, deny = [], [], []
                    for b in blocks:
                        if not isinstance(b, dict):
                            continue
                        allow_v += [str(x) for x in (b.get("allowed_values") or [])]
                        allow_l += [str(x) for x in (b.get("allowlist") or [])]
                        deny += [str(x) for x in (b.get("denylist") or [])]
                    pbrief[pname] = {"allowed_values": allow_v[:12], "allowlist": allow_l[:10], "denylist": deny[:15]}
                brief[fname] = {"risk": fdef.get("risk", ""), "params": pbrief}
            tools[tf.name] = {"scene": obj.get("scene", ""), "functions": brief}
    advice: List[Dict[str, Any]] = []
    ap = reg / "advice_docs.json"
    if ap.is_file():
        try:
            aobj = json.loads(ap.read_text(encoding="utf-8"))
            advice = (aobj.get("advice_docs") if isinstance(aobj, dict) else aobj) or []
        except Exception:
            advice = []
    return {"policy": policy or policy_manager.get_current_policy(), "registry": str(reg),
            "scenes": list(scenes_obj.keys()), "tools": tools,
            "advice_docs": [_trunc(a, 120) for a in advice[:5]]}


def build_context(round_ids: List[str], policy: Optional[str] = None, role_desc: str = "",
                  user_prompt: str = "", parent_feedback: str = "") -> Dict[str, Any]:
    """聚合若干 round 的明细 + 当前策略库摘要，作为 AI 分析输入。"""
    if not round_ids:
        return {"ok": False, "error": "round_ids 为空"}
    items, missing = [], []
    for rid in round_ids[:50]:
        rid = (rid or "").strip()
        if not rid:
            continue
        try:
            rec = _db().get_round_by_id(rid)
        except Exception:
            rec = None
        if not rec:
            missing.append(rid)
            continue
        items.append(round_digest(rec))
    if not items:
        return {"ok": False, "error": f"未找到任何有效 round：{missing[:5]}"}
    return {"ok": True, "data": {"items": items, "missing": missing,
                                 "policy_summary": _policy_summary(policy),
                                 "role_desc": role_desc, "user_prompt": user_prompt,
                                 "parent_feedback": parent_feedback}}


# ─────────────────────────── ③ AI 综合分析 ───────────────────────────
SEVERITIES = ("high", "medium", "low")
TARGET_RE = re.compile(r"^(scenes\.json|tools/[A-Za-z0-9_-]+\.json)$")


def _s(v: Any, n: int = 400) -> str:
    return _trunc(v, n)


def _strlist(v: Any, n: int = 200) -> List[str]:
    if isinstance(v, list):
        return [_s(x, n) for x in v][:200]
    if isinstance(v, str):
        return [_s(v, n)]
    return []


def sanitize_result(obj: Any) -> Dict[str, Any]:
    """对 AI 输出做 schema 校验与裁剪，丢弃非法项。"""
    if not isinstance(obj, dict):
        raise ValueError("AI 输出不是 JSON 对象")
    out: Dict[str, Any] = {"risks": [], "relax": [], "transform": [], "summary": "", "assumptions": ""}

    for it in (obj.get("risks") or [])[:100]:
        if not isinstance(it, dict):
            continue
        out["risks"].append({
            "round_id": _s(it.get("round_id"), 64), "scene": _s(it.get("scene"), 64),
            "tool": _s(it.get("tool"), 64), "param": _s(it.get("param"), 64),
            "behavior": _s(it.get("behavior"), 300), "violation": _s(it.get("violation"), 300),
            "severity": _s(it.get("severity"), 16).lower() if _s(it.get("severity"), 16).lower() in SEVERITIES else "medium",
            "action": _s(it.get("action"), 300),
        })
    for it in (obj.get("relax") or [])[:100]:
        if not isinstance(it, dict):
            continue
        out["relax"].append({
            "round_id": _s(it.get("round_id"), 64), "scene": _s(it.get("scene"), 64),
            "tool": _s(it.get("tool"), 64), "blocked_behavior": _s(it.get("blocked_behavior"), 300),
            "reason": _s(it.get("reason"), 300), "action": _s(it.get("action"), 300),
        })
    for it in (obj.get("transform") or [])[:100]:
        if not isinstance(it, dict):
            continue
        target = _s(it.get("target"), 120)
        if not TARGET_RE.match(target):
            continue
        proposed = it.get("proposed")
        if isinstance(proposed, (list, dict)):
            proposed_v: Any = _strlist(proposed) if isinstance(proposed, list) else _s(proposed, 400)
        else:
            proposed_v = _s(proposed, 400)
        out["transform"].append({
            "target": target, "path": _s(it.get("path"), 300),
            "current": _s(it.get("current"), 400), "proposed": proposed_v,
            "reason": _s(it.get("reason"), 400),
            "risk_level": _s(it.get("risk_level"), 16).lower() if _s(it.get("risk_level"), 16).lower() in SEVERITIES else "medium",
        })
    out["summary"] = _s(obj.get("summary"), 2000)
    out["assumptions"] = _s(obj.get("assumptions"), 2000)
    return out


def _build_prompt(ctx: Dict[str, Any]) -> str:
    prompts = {k: (_cfg(k, "") or DEFAULT_PROMPTS[k]) for k in PROMPT_KEYS}
    body = {
        "role_desc": ctx.get("role_desc", ""),
        "user_prompt": ctx.get("user_prompt", ""),
        "parent_feedback": ctx.get("parent_feedback", ""),
        "policy_summary": ctx.get("policy_summary", {}),
        "rounds": ctx.get("items", []),
    }
    return (f"{prompts['prompt_analyze']}\n\n{prompts['prompt_relax']}\n\n{prompts['prompt_transform']}\n\n"
            "===== 待分析数据（JSON）=====\n" + json.dumps(body, ensure_ascii=False, indent=1)[:20000])


def analyze(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """调用 LLM 产出结构化结论（JSON），失败自动纠正重试一次。"""
    if not llm_config().get("api_key"):
        return {"ok": False, "error": "API Token 未配置，请在「RSI 自进化 → AI 参数」抽屉中配置"}
    try:
        from auditor.translator.core import call_llm
    except Exception:
        from .core import call_llm  # type: ignore

    system = "你是 ClawAVC 策略自进化分析引擎，只输出严格 JSON。"
    user = _build_prompt(ctx)
    cfg = llm_config()
    try:
        content, meta = call_llm(system, user, cfg, max_retry=1)
        result = sanitize_result(json.loads(_json_extract(content)))
        return {"ok": True, "data": {"result": result, "meta": meta}}
    except Exception as first:
        try:
            # TPM 限流保护：首次大调用后冷却再重试，避免同一窗口内叠加触发 429
            time.sleep(45)
            fix = user + "\n\n【纠正】上一次输出无法解析为合法 JSON，请仅输出 JSON 对象本身。"
            content2, meta2 = call_llm(system, fix, cfg, max_retry=0)
            result = sanitize_result(json.loads(_json_extract(content2)))
            meta2["repaired"] = True
            return {"ok": True, "data": {"result": result, "meta": meta2}}
        except Exception as second:
            return {"ok": False, "error": f"AI 分析失败：{first} / 重试失败：{second}"}


def _json_extract(text: str) -> str:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    s, e = raw.find("{"), raw.rfind("}")
    return raw[s:e + 1] if (s >= 0 and e > s) else raw


# ─────────────────────────── ④ 变更计划（diff） ───────────────────────────
def build_plan(result: Dict[str, Any], adopted: Dict[str, List[int]]) -> Dict[str, Any]:
    """按勾选的索引生成结构化 diff（adopted: {"risks":[0,2], "relax":[1], "transform":[0]}）。"""
    changes: List[Dict[str, Any]] = []
    for idx in sorted(set(adopted.get("risks") or [])):
        it = (result.get("risks") or [])[idx: idx + 1]
        if not it:
            continue
        r = it[0]
        changes.append({"kind": "tighten", "origin": "risks", "index": idx,
                        "target": f"tools/{r['scene']}.json" if r.get("scene") else "",
                        "path": "", "current": r.get("behavior", ""),
                        "proposed": r.get("action", ""), "reason": r.get("violation", ""),
                        "risk_level": r.get("severity", "medium"), "round_id": r.get("round_id", "")})
    for idx in sorted(set(adopted.get("relax") or [])):
        it = (result.get("relax") or [])[idx: idx + 1]
        if not it:
            continue
        r = it[0]
        changes.append({"kind": "relax", "origin": "relax", "index": idx,
                        "target": f"tools/{r['scene']}.json" if r.get("scene") else "",
                        "path": "", "current": r.get("blocked_behavior", ""),
                        "proposed": r.get("action", ""), "reason": r.get("reason", ""),
                        "risk_level": "high", "round_id": r.get("round_id", "")})
    for idx in sorted(set(adopted.get("transform") or [])):
        it = (result.get("transform") or [])[idx: idx + 1]
        if not it:
            continue
        t = it[0]
        changes.append({"kind": "transform", "origin": "transform", "index": idx,
                        "target": t.get("target", ""), "path": t.get("path", ""),
                        "current": t.get("current", ""), "proposed": t.get("proposed", ""),
                        "reason": t.get("reason", ""), "risk_level": t.get("risk_level", "medium"),
                        "round_id": ""})
    return {"ok": True, "data": {"changes": changes, "count": len(changes)}}


# ─────────────────────────── ⑤ 应用（新建角色库） ───────────────────────────
def _ai_writer():
    try:
        from auditor.translator import ai_writer
    except Exception:
        from . import ai_writer  # type: ignore
    return ai_writer


def ensure_role(role: str, base: str = "default", title: str = "", force: bool = False) -> Dict[str, Any]:
    aw = _ai_writer()
    target = Path(policy_manager.resolve_registry_path(role))
    if target.exists() and not force:
        return {"ok": True, "data": {"role": role, "path": str(target), "reused": True}}
    res = aw.scaffold(role, base, title=title or role, instruction="", force=force)
    if not res.get("ok"):
        return res
    return {"ok": True, "data": {**res["data"], "reused": False}}


def _resolve_target(role: str, target: str) -> Path:
    if not TARGET_RE.match(target or ""):
        raise ValueError(f"非法 target：{target}")
    aw = _ai_writer()
    reg = aw.registry_dir(role)
    rp = os.path.realpath(str(reg / target))
    if not (rp + os.sep).startswith(os.path.realpath(str(reg)) + os.sep):
        raise ValueError("目标路径越界")
    return Path(rp)


def _set_path(obj: Any, path: str, value: Any) -> Any:
    """按点分路径写入（支持 list 下标），返回修改后的对象。"""
    segs = [s for s in (path or "").split(".") if s != ""]
    if not segs:
        raise ValueError("path 为空")
    cur = obj
    for i, seg in enumerate(segs[:-1]):
        nxt = cur[int(seg)] if (isinstance(cur, list) and seg.lstrip("-").isdigit()) else cur.setdefault(seg, {})
        if isinstance(nxt, dict) or isinstance(nxt, list):
            cur = nxt
        else:  # 叶子被当成容器，覆盖为 dict 继续
            nxt = {}
            if isinstance(cur, list):
                cur[int(seg)] = nxt
            else:
                cur[seg] = nxt
            cur = nxt
    last = segs[-1]
    if isinstance(cur, list) and last.lstrip("-").isdigit():
        cur[int(last)] = value
    else:
        cur[last] = value
    return obj


def apply_plan(role: str, base: str, changes: List[Dict[str, Any]], title: str = "",
               force: bool = False) -> Dict[str, Any]:
    """把采纳的 transform 项落到新建角色库；tighten/relax 标记需人工处理。"""
    if not role:
        return {"ok": False, "error": "缺少角色名"}
    ensured = ensure_role(role, base, title=title, force=force)
    if not ensured.get("ok"):
        return ensured
    aw = _ai_writer()
    snap = aw.snapshot(role, "rsi-before-apply")
    applied, manual, errors = [], [], []
    by_file: Dict[str, List[Dict[str, Any]]] = {}
    for ch in changes or []:
        if ch.get("kind") != "transform":
            manual.append({"kind": ch.get("kind"), "reason": ch.get("reason", ""),
                           "proposed": ch.get("proposed", "")})
            continue
        if not ch.get("path"):
            manual.append({"kind": "transform", "reason": "缺少 path，需人工定位", **ch})
            continue
        by_file.setdefault(ch["target"], []).append(ch)

    for target, items in by_file.items():
        try:
            fp = _resolve_target(role, target)
            if not fp.is_file():
                errors.append(f"{target} 不存在")
                continue
            obj = json.loads(fp.read_text(encoding="utf-8"))
            for ch in items:
                obj = _set_path(obj, ch["path"], ch.get("proposed"))
                applied.append({"target": target, "path": ch["path"], "proposed": ch.get("proposed"),
                                "reason": ch.get("reason", ""), "risk_level": ch.get("risk_level", "medium")})
            tmp = fp.with_suffix(fp.suffix + ".tmp")
            tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, fp)
        except Exception as e:
            errors.append(f"{target}: {e}")

    aw.policy_manager._reload()
    validation = aw.validate(role).get("data", {})
    return {"ok": True, "data": {"role": role, "base": base, "path": str(aw.registry_dir(role)),
                                 "snapshot": snap.get("data", {}).get("ts", ""), "applied": applied,
                                 "manual": manual, "errors": errors, "validation": validation}}


def rollback(role: str, ts: str = "") -> Dict[str, Any]:
    return _ai_writer().rollback(role, ts)


def validate_role(role: str) -> Dict[str, Any]:
    return _ai_writer().validate(role)


# ─────────────────────────── ⑥ 回测（可选开关） ───────────────────────────
def _load_tools_map(registry_dir: Path) -> Dict[str, Any]:
    tools: Dict[str, Any] = {}
    tdir = Path(registry_dir) / "tools"
    if not tdir.is_dir():
        return tools
    for tf in sorted(tdir.glob("*.json")):
        try:
            obj = json.loads(tf.read_text(encoding="utf-8"))
        except Exception:
            continue
        scene = obj.get("scene")
        if scene:
            tools[scene] = obj
    return tools


def static_deny_with(ir: Dict[str, Any], registry_dir: Path) -> Dict[str, Any]:
    """按指定策略库（而非当前生效库）执行静态拒绝，语义与 core._apply_static_deny 一致。

    用于回测：把 round 的原始 IR 过一遍“进化后策略”的 denylist，得到进化后 IR。
    """
    try:
        from auditor.translator import core
    except Exception:
        from . import core  # type: ignore
    if not isinstance(ir, dict):
        return ir
    tool_registry = _load_tools_map(Path(registry_dir))
    kept: List[Dict[str, Any]] = []
    for policy in ir.get("policies", []) or []:
        if not isinstance(policy, dict):
            continue
        subj = policy.get("subject")
        fn_defs = tool_registry.get(subj, {}).get("functions", {}) if subj else {}
        new_objs: List[Dict[str, Any]] = []
        for obj in policy.get("objects") or []:
            blocked = False
            if isinstance(obj, dict) and obj.get("type") == "tool":
                fn_def = fn_defs.get(obj.get("identifier")) or {}
                params_def = fn_def.get("params") or {}
                for p in obj.get("params") or []:
                    if not isinstance(p, dict):
                        continue
                    pval = str(p.get("identifier", ""))
                    if not pval:
                        continue
                    for st in core._static_spec(params_def.get(p.get("name"), {}) or {}):
                        denylist = [str(x) for x in (st.get("denylist") or [])]
                        if core._param_denied(p.get("name"), pval, denylist) is not None:
                            blocked = True
                            break
                    if blocked:
                        break
            if not blocked:
                new_objs.append(obj)
        if new_objs:
            policy["objects"] = new_objs
            kept.append(policy)
    ir["policies"] = kept
    return ir


def _normalize_round(ir: Any, actions: Any) -> tuple:
    """把库内原始 ir_json / action_json 转成判定所需结构（复用 judge 规范化入口）。"""
    from auditor.monitor import judge  # type: ignore

    return judge._normalize_ir(ir), judge._normalize_actions(actions)


def _layered(ir_norm: Any, behaviors: Any) -> Dict[str, Any]:
    from auditor.monitor import judge  # type: ignore

    res = judge.Resource_Consistency_Check_Layered(ir_norm, behaviors)
    d = judge.layered_result_to_dict(res)
    return {"score": d.get("overall_score"), "consistent": d.get("consistent"),
            "abnormal": str(d.get("consistent")) != "yes",
            "violations": list(d.get("violations") or [])[:5]}


def _judge_score(ir: Any, actions: Any) -> Dict[str, Any]:
    ir_norm, behaviors = _normalize_round(ir, actions)
    return _layered(ir_norm, behaviors)


def backtest(round_ids: List[str], role: str, mode: str = "static") -> Dict[str, Any]:
    """改动前后对同一批 round 各判定一次并对比。

    mode=static（默认，不耗 LLM）：把原 IR 过一遍新策略的静态拒绝得到“进化后 IR”再判定。
    """
    reg_dir = Path(policy_manager.resolve_registry_path(role))
    if not reg_dir.is_dir():
        return {"ok": False, "error": f"角色策略库不存在：{role}"}
    items: List[Dict[str, Any]] = []
    for rid in (round_ids or [])[:50]:
        rid = (rid or "").strip()
        if not rid:
            continue
        rec = _db().get_round_by_id(rid)
        if not rec:
            items.append({"round_id": rid, "error": "round 不存在"})
            continue
        try:
            ir = _load_json_obj(rec.get("ir_json"))
            actions = _load_json_obj(rec.get("action_json"))
            ir_norm, behaviors = _normalize_round(ir, actions)
            before = _layered(ir_norm, behaviors)
            ir_after = static_deny_with(json.loads(json.dumps(ir_norm)), reg_dir)
            after = _layered(ir_after, behaviors)
            b_s, a_s = before.get("score"), after.get("score")
            items.append({"round_id": rid, "before_score": b_s, "after_score": a_s,
                          "before_abnormal": before.get("abnormal"), "after_abnormal": after.get("abnormal"),
                          "delta": (round(a_s - b_s, 4) if isinstance(a_s, (int, float)) and isinstance(b_s, (int, float)) else None),
                          "stored_score": rec.get("overall_score"), "mode": mode,
                          "after_violations": after.get("violations", [])})
        except Exception as e:
            items.append({"round_id": rid, "error": str(e)})
    ok_items = [i for i in items if not i.get("error")]
    improved = sum(1 for i in ok_items if (i.get("delta") or 0) > 0)
    regressed = sum(1 for i in ok_items if (i.get("delta") or 0) < 0)
    return {"ok": True, "data": {"enabled": True, "role": role, "mode": mode, "items": items,
                                 "improved": improved, "regressed": regressed,
                                 "unchanged": len(ok_items) - improved - regressed}}


# ─────────────────────────── ⑦ 进化轮次归档 ───────────────────────────
def new_run_id() -> str:
    ts = time.strftime("%Y%m%d")
    seq = 1
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    while (RUNS_ROOT / f"rsi-{ts}-{seq:04d}.json").exists():
        seq += 1
    return f"rsi-{ts}-{seq:04d}"


def save_run(run: Dict[str, Any]) -> Dict[str, Any]:
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    rid = run.get("run_id") or new_run_id()
    run["run_id"] = rid
    run.setdefault("created_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    run.setdefault("parent_run_id", "")
    fp = RUNS_ROOT / f"{rid}.json"
    tmp = fp.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, fp)
    return {"ok": True, "data": {"run_id": rid, "path": str(fp)}}


def get_run(run_id: str) -> Dict[str, Any]:
    fp = RUNS_ROOT / f"{run_id}.json"
    if not fp.is_file():
        return {"ok": False, "error": f"轮次不存在：{run_id}"}
    return {"ok": True, "data": json.loads(fp.read_text(encoding="utf-8"))}


def list_runs(limit: int = 50) -> Dict[str, Any]:
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    items: List[Dict[str, Any]] = []
    for fp in sorted(RUNS_ROOT.glob("rsi-*.json"), reverse=True)[:limit]:
        try:
            obj = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        items.append({"run_id": obj.get("run_id"), "created_at": obj.get("created_at"),
                      "role": obj.get("role"), "base": obj.get("base"), "status": obj.get("status"),
                      "parent_run_id": obj.get("parent_run_id", ""),
                      "round_count": len(obj.get("round_ids") or []),
                      "adopted_count": len(obj.get("adopted") or []),
                      "backtest": obj.get("backtest", {}).get("enabled", False),
                      "summary": (obj.get("ai_result", {}) or {}).get("summary", "")[:200]})
    return {"ok": True, "data": {"items": items}}


def next_run(parent_run_id: str) -> Dict[str, Any]:
    """基于上一轮发起新一轮：继承上下文与回测反馈，返回可编辑的新轮次骨架。"""
    pr = get_run(parent_run_id)
    if not pr.get("ok"):
        return pr
    p = pr["data"]
    bt = p.get("backtest") or {}
    feedback = ""
    if bt.get("enabled"):
        feedback = (f"上一轮 {parent_run_id} 回测：提升 {bt.get('improved', 0)} 条、"
                    f"下降 {bt.get('regressed', 0)} 条；角色 {p.get('role', '')}。")
    skeleton = {"run_id": new_run_id(), "parent_run_id": parent_run_id,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "role": p.get("role", ""), "base": p.get("base", "default"),
                "round_ids": p.get("round_ids", []), "role_desc": p.get("role_desc", ""),
                "user_prompt": p.get("user_prompt", ""), "parent_feedback": feedback,
                "status": "draft"}
    return {"ok": True, "data": skeleton}
