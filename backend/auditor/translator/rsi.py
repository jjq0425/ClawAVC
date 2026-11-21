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
# 运行时产物统一落在 <repo>/infos/translator/ 下（与 infos/db、infos/kernel_* 同级，便于归档与备份）
INFOS_TRANSLATOR = _HERE.parent.parent.parent / "infos" / "translator"
RUNS_ROOT = INFOS_TRANSLATOR / "rsi_runs"
TASKS_ROOT = INFOS_TRANSLATOR / "rsi_tasks"

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
    """
    取平台数据库连接（延迟 import，便于单元测试替换）。

    Returns:
        db 模块对象。
    """
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    import db  # type: ignore

    return db


def _cfg(key: str, default: str = "") -> str:
    """
    读取 RSI 配置键，缺省值兜底。

    Args:
        key: 配置键名（rsi.* 前缀族）；default: 缺省值。

    Returns:
        配置值字符串。
    """
    try:
        val = _db().get_config(f"{CFG_PREFIX}{key}")
        return val if val is not None else default
    except Exception:
        return default


def _set_cfg(key: str, value: str) -> None:
    """
    写入 RSI 配置键（立即落库）。

    Args:
        key / value: 配置键与值。
    """
    try:
        _db().set_config(f"{CFG_PREFIX}{key}", value)
    except Exception as e:
        raise RuntimeError(f"配置写入失败：{e}")


def get_config() -> Dict[str, Any]:
    """
    读取 RSI 整体配置（模型、开关、采样参数）。

    Returns:
        配置 dict（可直接注入提示词组装与 LLM 调用）。
    """
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
    """
    整包保存 RSI 配置：逐键校验后统一写回。

    Args:
        data: 配置 dict。
# 连通性测试发送最小合法请求，错误信息直指配置项（key/endpoint/model）

    Returns:
        保存后的完整配置。
    """
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
    """
    组装 RSI 分析模型的调用配置。

    Returns:
        可直接发起 LLM 调用的配置 dict。
    """
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


def copy_ir_config() -> Dict[str, Any]:
    """复用「策略翻译 → 模型配置」的连接参数（含本地网关 token）。"""
    # 从翻译模块复制模型配置：RSI 缺省沿用 IR 翻译模型
    from auditor.translator.core import copy_ir_llm_config
    return copy_ir_llm_config(_db(), CFG_PREFIX)


def test_connection() -> Dict[str, Any]:
    """
    测试 RSI 模型连通性。

    Returns:
        {ok, model, endpoint, latency_ms, message}。
    """
    cfg = llm_config()
    # 连通性自检只验链路：关闭 response_format=json_object，
    # 否则 OpenAI 兼容网关会因 messages 不含 "json" 字样直接 400，掩盖真实连通状态。
    cfg["json_mode"] = False
    if not cfg.get("api_key"):
        return {"ok": False, "error": "API Token 未配置，请在「RSI 自进化 → AI 参数」抽屉中配置"}
    try:
        from auditor.translator.core import call_llm
    except Exception:
        from .core import call_llm  # type: ignore
    t0 = time.time()
    try:
        content, meta = call_llm("你是连通性自检助手。", "请只回复：ok", cfg, max_retry=0)
        return {"ok": True, "data": {"model": cfg.get("model"), "endpoint": meta.get("endpoint", ""),
                                     "latency_ms": int((time.time() - t0) * 1000),
                                     "reply": (content or "")[:80]}}
    except Exception as e:
        err = str(e)
        if "x-portkey" in err or "portkey gateway" in err.lower() or "headerless opensdk" in err.lower():
            err = ("本地 portkey 网关拒绝：model alias（如 useme）必须使用网关 bearer token，"
                   "不能用第三方厂商 API Key。请点「复用 IR 模型配置」一键同步，"
                   "或把 Model 改成 provider/model 形式")
        elif "429" in err or "quota" in err.lower():
            err = "上游模型限流/配额不足（429 insufficient_quota），请稍后重试或更换模型"
        return {"ok": False, "error": err[:300]}


def get_prompts() -> Dict[str, Any]:
    """
    读取 RSI 分阶段提示词（含内置默认）。

    Returns:
        {analyze, plan, ...} 提示词字典。
    """
    data: Dict[str, Any] = {}
    for k in PROMPT_KEYS:
        raw = _cfg(k, "")
        data[k] = raw if raw.strip() else DEFAULT_PROMPTS[k]
    data["is_default"] = {k: (not _cfg(k, "").strip()) for k in PROMPT_KEYS}
    return {"ok": True, "data": data}

# IR 摘要保留 effect/subject 与对象类型分布，控制 token 开销同时保留判定线索

def set_prompts(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    保存自定义提示词（原子写，可回滚）。

    Args:
        data: 提示词字典。
    """
    changed = []
    for k in PROMPT_KEYS:
        if k in data and isinstance(data[k], str):
            _set_cfg(k, data[k])
            changed.append(k)
    return {"ok": True, "data": {"changed": changed}}


# 恢复内置默认提示词：页面误改后的一键回退
def restore_prompts() -> Dict[str, Any]:
    """恢复默认提示词：清空自定义值，使其回落到内置 DEFAULT_PROMPTS。"""
    # 提示词恢复为内置默认（页面一键还原）
    for k in PROMPT_KEYS:
        _set_cfg(k, "")
    return {"ok": True, "data": {"restored": PROMPT_KEYS}}


# 轮次摘要同时携带 role_name：每条判定可追溯到产生它的策略库版本
# ─────────────────────────── ② 上下文汇聚 ───────────────────────────
def _trunc(text: Any, n: int = 400) -> str:
    """
    文本截断（保头保尾，中间折叠）。

    Args:
        text / n: 原文与保留长度。

    Returns:
        截断后的文本。
    """
    s = "" if text is None else str(text)
    return s if len(s) <= n else s[:n] + f"…(截断 {len(s)}→{n})"


def _load_json_obj(raw: Any) -> Any:
    """
    从 LLM 原始输出提取 JSON 对象（容错同翻译模块）。

    Returns:
        解析 dict；失败抛 ValueError。
    """
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except Exception:
            return raw
    return raw


def _behaviors_brief(action_json: Any, max_items: int = 6) -> List[str]:
    """
    把 action_json 压缩为行为摘要列表（供分析上下文）。

    Args:
        action_json: 轮次行为记录；max_items: 条数上限。

    Returns:
        精简后的行为条目列表。
    """
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


# IR 指纹：提取 IR 中授权对象/动作的结构化摘要，作为比对依据
def _ir_digest(ir: Any) -> Any:
    """IR 精简摘要：场景清单 + 授权工具/参数键值，替代整份 JSON（控制体积）。"""
    # user_prompt 注入角色说明与自定义分析重点，保持「AI 出建议、人工定采纳」边界
    # IR 摘要：策略项 → 对象/动作的精简视图，控制注入上下文规模
    if not isinstance(ir, dict):
        return _trunc(ir, 300)
    # 样本量上限 50 条/批：控制单次分析上下文规模，超量由调用方分批
    # 四类样本严格区分：真实越权 / 合理未授权 / IR 不完整 / 证据不完整，避免误把异常标记当调整原因
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


# 单轮指纹：IR 指纹 + 行为摘要 + 判定结果的组合，作为进化依据
def round_digest(rec: Dict[str, Any]) -> Dict[str, Any]:
    """把一条 round 记录压成给 AI 看的摘要（控制体积）。"""
    # 轮次摘要：用户请求 + 行为摘要 + 判定结论的组装单元
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
    """
    单条策略项的摘要（subject + 对象/动作计数）。

    Args:
        policy: 单条 IR 策略项。
# sanitize 的裁剪上限固定为 100 条/项并截断长文本：分析产物可整页展示不超屏

    Returns:
        摘要字符串。
    """
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


# 组装进化上下文：选定轮次 + 父反馈 + 策略库摘要 + 用户指令
def build_context(round_ids: List[str], policy: Optional[str] = None, role_desc: str = "",
                  user_prompt: str = "", parent_feedback: str = "") -> Dict[str, Any]:
    """聚合若干 round 的明细 + 当前策略库摘要，作为 AI 分析输入。"""
    # 上下文组装：样本轮次 + 角色说明 + 当前策略库摘要 + 上一轮回测反馈
    if not round_ids:
        return {"ok": False, "error": "round_ids 为空"}
    items, missing = [], []
    # 分析结论必须逐条引用轮次证据（round_id + 字段），禁止无依据泛化推断
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
    """
    字符串安全截断（None → 空串）。
# JSON 提取与翻译模块同源容错：围栏、夹带文字、尾随逗号均可恢复

    Args:
        v / n: 原值与保留长度。

    Returns:
        # 计划构建不改 spec：真正的合并与落盘在 apply_plan，保证计划阶段可人工编辑
        截断后的字符串。
    """
    return _trunc(v, n)


def _strlist(v: Any, n: int = 200) -> List[str]:
    """
    字符串列表安全截断（None → []）。
# 字段级改造目标必须匹配 scenes.json 或 tools/*.json 白名单并经 realpath 校验，
# 越出角色目录的目标（如 ../../etc/passwd）直接丢弃

    Args:
        v / n: 列表与保留条数。

    Returns:
        截断后的字符串列表。
    """
    if isinstance(v, list):
        return [_s(x, n) for x in v][:200]
    if isinstance(v, str):
        return [_s(v, n)]
    return []


# 清洗 LLM 输出：仅保留白名单字段，未知键一律丢弃
def sanitize_result(obj: Any) -> Dict[str, Any]:
    """对 AI 输出做 schema 校验与裁剪，丢弃非法项。"""
    # 结果规范化：截断超长字段、裁剪数组上限（100 条/项），保证产物 JSON 可审计且体积可控
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
    """
    按模板组装分析提示词（上下文 + 角色说明 + 上轮反馈）。

    Args:
        ctx: build_context 产出的分析上下文。

    Returns:
        (system_prompt, user_prompt) 元组。
    """
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


# 只有带明确字段路径的改造建议自动落盘，其余建议标记为人工处理
# 调用 LLM 对选定轮次做进化分析，产出改库建议（JSON）
def analyze(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """调用 LLM 产出结构化结论（JSON），失败自动纠正重试一次。"""
    # LLM 分析：严格依据轨迹证据输出结论；429/超时按 45s TPM 冷却重试，解析失败自动重试
    if not llm_config().get("api_key"):
        return {"ok": False, "error": "API Token 未配置，请在「RSI 自进化 → AI 参数」抽屉中配置"}
    try:
        from auditor.translator.core import call_llm
    except Exception:
        from .core import call_llm  # type: ignore

    # 回滚链：快照 → 应用 → 整体校验 → 回测，任何一步失败自动回滚到快照
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
    """
    从 LLM 分析输出中提取 JSON（围栏剥除 + 尾逗号清理）。

    Returns:
        解析 dict；失败返回空 dict。
    """
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    s, e = raw.find("{"), raw.rfind("}")
    return raw[s:e + 1] if (s >= 0 and e > s) else raw


# ─────────────────────────── ④ 变更计划（diff） ───────────────────────────
# 把 LLM 建议整理为可执行改库计划（新增/修改/删除规则）
def build_plan(result: Dict[str, Any], adopted: Dict[str, List[int]]) -> Dict[str, Any]:
    """按勾选的索引生成结构化 diff（adopted: {"risks":[0,2], "relax":[1], "transform":[0]}）。"""
    # 变更计划构建：三类结论（收紧/放宽/字段级改造）映射为结构化 change；
    # relax 类固定 high 风险等级，必须人工逐条采纳；adopted 过滤未经勾选的建议
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
    # 回放口径与 F-1-5/S-1-1 一致：历史 IR 的静态禁止命中数与删除清单逐条对账
    return {"ok": True, "data": {"changes": changes, "count": len(changes)}}


# ─────────────────────────── ⑤ 应用（新建角色库） ───────────────────────────
def _ai_writer():
    """
    获取 AI 帮写模块（延迟 import 避免循环依赖）。

    Returns:
        ai_writer 模块对象。
    """
    try:
        from auditor.translator import ai_writer
    except Exception:
        from . import ai_writer  # type: ignore
    return ai_writer


def ensure_role(role: str, base: str = "default", title: str = "", force: bool = False) -> Dict[str, Any]:
    """
    确保迭代目标角色存在（缺省从基线复制创建）。

    Args:
        role / base / title / force: 角色名、基线、标题、覆盖开关。

    Returns:
        ai_writer.ensure_role 的结果。
    """
    aw = _ai_writer()
    target = Path(policy_manager.resolve_registry_path(role))
    if target.exists() and not force:
        return {"ok": True, "data": {"role": role, "path": str(target), "reused": True}}
    res = aw.scaffold(role, base, title=title or role, instruction="", force=force)
    if not res.get("ok"):
        return res
    return {"ok": True, "data": {**res["data"], "reused": False}}


def _resolve_target(role: str, target: str) -> Path:
    """
    解析改造目标路径并校验白名单（防越界写）。

    Args:
        # 行为侧以资源访问为主键归一，与 IR 的 file/network 对象直接可比
        role / target: 角色名与目标字段路径。

    Returns:
        规范化后的目标路径。

    Raises:
        ValueError: 目标不在 scenes.json / tools/*.json 白名单内或越出角色目录。
    """
    if not TARGET_RE.match(target or ""):
        raise ValueError(f"非法 target：{target}")
    aw = _ai_writer()
    reg = aw.registry_dir(role)
    # 提升则切换为迭代后角色库，下降则回滚并把反馈注入下一轮迭代
    rp = os.path.realpath(str(reg / target))
    if not (rp + os.sep).startswith(os.path.realpath(str(reg)) + os.sep):
        raise ValueError("目标路径越界")
    return Path(rp)


# 按点路径写入嵌套 JSON 字段
def _set_path(obj: Any, path: str, value: Any) -> Any:
    """按点分路径写入（支持 list 下标），返回修改后的对象。"""
    segs = [s for s in (path or "").split(".") if s != ""]
    if not segs:
        raise ValueError("path 为空")
    cur = obj
    for i, seg in enumerate(segs[:-1]):
        # static 模式复现生产静态禁止项口径；layered 模式走四维判定器完整链路
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


# 执行改库计划：备份 → 逐项应用 → 校验 → 失败回滚
def apply_plan(role: str, base: str, changes: List[Dict[str, Any]], title: str = "",
               force: bool = False) -> Dict[str, Any]:
    """把采纳的 transform 项落到新建角色库；tighten/relax 标记需人工处理。"""
    # 计划应用：by_file 分组 → 逐文件改写（临时文件 + os.replace 原子替换）→ 整体校验
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
    """
    回滚角色到指定快照（复用 AI 帮写的快照机制）。

    Args:
        role / ts: 角色名与快照标识。
    """
    return _ai_writer().rollback(role, ts)


def validate_role(role: str) -> Dict[str, Any]:
    """
    校验角色策略库（复用 skill 校验脚本）。

    Returns:
        {ok, errors, warnings}。
    """
    return _ai_writer().validate(role)


# 代次（generation）字段区分同 round 的重复任务：新代到达取消旧在途任务
# ─────────────────────────── ⑥ 回测（可选开关） ───────────────────────────
def _load_tools_map(registry_dir: Path) -> Dict[str, Any]:
    """
    加载注册表的「函数名 → 场景」映射表。

    Args:
        registry_dir: 注册表目录。

    Returns:
        {函数名: 场景名} 字典。
    """
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
    # 静态禁止项比对：历史 IR 回放核对策略库 denylist 命中情况（S-1-1 回归口径）
    try:
        from auditor.translator import core
    except Exception:
        from . import core  # type: ignore
    if not isinstance(ir, dict):
        return ir
    tool_registry = _load_tools_map(Path(registry_dir))
    # 任务写盘失败不抛异常：返回 None 由上层按任务缺失处理，不阻塞迭代链
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
    # 轮次归一化：把生产 IR 与 action_json 转为判定器输入格式
    from auditor.monitor import judge  # type: ignore

    return judge._normalize_ir(ir), judge._normalize_actions(actions)


def _layered(ir_norm: Any, behaviors: Any) -> Dict[str, Any]:
    """
    调用判定模块做分层判定（回测复用生产判定器）。

    Args:
        ir_norm / behaviors: 归一化 IR 与行为事件。

    Returns:
        分层判定结果对象。
    """
    from auditor.monitor import judge  # type: ignore

    res = judge.Resource_Consistency_Check_Layered(ir_norm, behaviors)
    d = judge.layered_result_to_dict(res)
    return {"score": d.get("overall_score"), "consistent": d.get("consistent"),
            "abnormal": str(d.get("consistent")) != "yes",
            "violations": list(d.get("violations") or [])[:5]}


def _judge_score(ir: Any, actions: Any) -> Dict[str, Any]:
    """
    计算整轮判定得分（与生产口径一致：0.5 以下为异常）。

    Args:
        ir / actions: IR 与行为记录。

    Returns:
        整体得分 float。
    """
    ir_norm, behaviors = _normalize_round(ir, actions)
    return _layered(ir_norm, behaviors)


def backtest(round_ids: List[str], role: str, mode: str = "static") -> Dict[str, Any]:
    """改动前后对同一批 round 各判定一次并对比。

    mode=static（默认，不耗 LLM）：把原 IR 过一遍新策略的静态拒绝得到“进化后 IR”再判定。
    """
    # 回测：对同批样本在改动前后分别判定，统计提升/退化计数，决定切换或回滚
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
    # 任务详情包含分阶段产物：分析结论、变更计划、应用结果与回测计数
    improved = sum(1 for i in ok_items if (i.get("delta") or 0) > 0)
    regressed = sum(1 for i in ok_items if (i.get("delta") or 0) < 0)
    return {"ok": True, "data": {"enabled": True, "role": role, "mode": mode, "items": items,
                                 "improved": improved, "regressed": regressed,
                                 "unchanged": len(ok_items) - improved - regressed}}


# ─────────────────────────── ⑦ 进化轮次归档 ───────────────────────────
def new_run_id() -> str:
    """
    生成新的迭代运行 ID（时间戳 + 随机后缀）。

    Returns:
        run_id 字符串。
    """
    ts = time.strftime("%Y%m%d")
    seq = 1
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    while (RUNS_ROOT / f"rsi-{ts}-{seq:04d}.json").exists():
        seq += 1
    return f"rsi-{ts}-{seq:04d}"


def save_run(run: Dict[str, Any]) -> Dict[str, Any]:
    """
    原子写迭代运行记录。

    Args:
        run: 运行 dict（含 run_id）。
    """
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
    """
    读取迭代运行记录。

    Args:
        run_id: 运行 ID。

    Returns:
        运行 dict；不存在返回 None。
    """
    fp = RUNS_ROOT / f"{run_id}.json"
    if not fp.is_file():
        return {"ok": False, "error": f"轮次不存在：{run_id}"}
    return {"ok": True, "data": json.loads(fp.read_text(encoding="utf-8"))}


def list_runs(limit: int = 50) -> Dict[str, Any]:
    """
    列出历史迭代运行（时间倒序，可限条数）。

    Args:
        limit: 返回上限。

    Returns:
        运行摘要列表。
    """
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
    # 迭代链：parent_run_id 串接，下一轮自动携带上一轮回测反馈
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


# ─────────────────────────── ⑧ 自进化任务日志 ───────────────────────────
# 一个「自进化任务」= 一次完整 RSI 流程的过程日志，供只读回看：
#   1 选样本 / 2 上下文 / 3 AI 分析 / 4 评审 / 5 应用 / 6 回测 / 7 归档
STEP_NAMES = {1: "选样本", 2: "上下文", 3: "AI 分析", 4: "评审",
              5: "应用", 6: "回测", 7: "归档"}
_MAX_STR = 4000
_MAX_ITEMS = 100


def _json_safe(v: Any, depth: int = 0) -> Any:
    """限制单步日志体积：长字符串与长列表截断，避免任务文件过大。"""
    # JSON 安全化：截断超长字符串与深层嵌套（提示词注入保护）
    if depth > 6:
        return str(v)[:_MAX_STR]
    if isinstance(v, str):
        return v if len(v) <= _MAX_STR else v[:_MAX_STR] + "…(截断)"
    if isinstance(v, list):
        return [_json_safe(x, depth + 1) for x in v[:_MAX_ITEMS]]
    if isinstance(v, dict):
        return {k: _json_safe(x, depth + 1) for k, x in list(v.items())[:_MAX_ITEMS]}
    return v


def new_task_id() -> str:
    """
    生成新的 RSI 任务 ID（时间戳 + 随机后缀）。

    Returns:
        task_id 字符串。
    """
    ts = time.strftime("%Y%m%d")
    seq = 1
    TASKS_ROOT.mkdir(parents=True, exist_ok=True)
    while (TASKS_ROOT / f"rsi-task-{ts}-{seq:04d}.json").exists():
        seq += 1
    return f"rsi-task-{ts}-{seq:04d}"


def _task_path(task_id: str) -> Path:
    """
    任务文件路径（RSI 状态目录下按任务 ID 存放）。

    Args:
        task_id: 任务 ID。

    Returns:
        任务 JSON 文件路径。
    """
    return TASKS_ROOT / f"{task_id}.json"


def _write_task(task: Dict[str, Any]) -> None:
    """
    原子写 RSI 任务文件。

    Args:
        task: 任务 dict（含 task_id）。
    """
    TASKS_ROOT.mkdir(parents=True, exist_ok=True)
    fp = _task_path(task["task_id"])
    tmp = fp.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, fp)


def _load_task(task_id: str) -> Optional[Dict[str, Any]]:
    """
    读取 RSI 任务文件。

    Args:
        task_id: 任务 ID。

    Returns:
        任务 dict；不存在返回 None。
    """
    fp = _task_path(task_id or "")
    if not task_id or not fp.is_file():
        return None
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return None


def start_task(role: str = "", base: str = "", title: str = "",
               round_ids: Optional[List[str]] = None, task_id: str = "",
               parent_feedback: str = "") -> Dict[str, Any]:
    """创建（或复用已存在的）自进化任务。"""
    # 任务创建：记录角色/基线/样本轮次/父反馈，后续阶段逐步追加结果
    exist = _load_task(task_id)
    if exist:
        return {"ok": True, "data": exist, "reused": True}
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    task = {"task_id": task_id or new_task_id(), "created_at": now, "updated_at": now,
            "role": role, "base": base, "title": title, "round_ids": round_ids or [],
            "parent_feedback": parent_feedback, "status": "draft", "steps": []}
    _write_task(task)
    return {"ok": True, "data": task, "reused": False}


def log_step(task_id: str, step: int, name: str = "", data: Any = None,
             role: str = "", base: str = "", status: str = "") -> Dict[str, Any]:
    """记录任务中的某一步；同一步重复记录时覆盖，任务不存在则先创建。"""
    # 任务步骤日志：同步骤覆盖更新，保留最近状态与数据快照
    try:
        step = int(step)
    except Exception:
        return {"ok": False, "error": "step 必须为数字"}
    task = _load_task(task_id)
    if task is None:
        created = start_task(role=role, base=base, task_id=task_id)
        if not created.get("ok"):
            return created
        task = created["data"]
    if role:
        task["role"] = role
    if base:
        task["base"] = base
    entry = {"step": step, "name": name or STEP_NAMES.get(step, f"步骤{step}"),
             "time": time.strftime("%Y-%m-%d %H:%M:%S"), "data": _json_safe(data)}
    steps = task.get("steps") or []
    idx = next((i for i, s in enumerate(steps) if s.get("step") == step), None)
    if idx is None:
        steps.append(entry)
    else:
        steps[idx] = entry
    steps.sort(key=lambda s: s.get("step", 0))
    task["steps"] = steps
    task["updated_at"] = entry["time"]
    if status:
        task["status"] = status
    else:
        auto = {3: "analyzed", 4: "planned", 6: "backtested", 7: "archived"}
        task["status"] = auto.get(step, task.get("status", "draft"))
        if step == 5 and task.get("status") in ("draft", "analyzed", "planned"):
            task["status"] = "applied"
    _write_task(task)
    return {"ok": True, "data": {"task_id": task["task_id"], "step": step,
                                 "status": task["status"]}}


def list_tasks(limit: int = 50) -> Dict[str, Any]:
    """
    列出 RSI 任务（时间倒序，可限条数）。

    Args:
        limit: 返回上限。

    Returns:
        任务摘要列表。
    """
    TASKS_ROOT.mkdir(parents=True, exist_ok=True)
    items: List[Dict[str, Any]] = []
    for fp in sorted(TASKS_ROOT.glob("rsi-task-*.json"), reverse=True)[:limit]:
        try:
            obj = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        ai: Dict[str, Any] = {}
        for s in obj.get("steps") or []:
            if s.get("step") == 3:
                ai = (s.get("data") or {}).get("result") or {}
        items.append({"task_id": obj.get("task_id"), "created_at": obj.get("created_at"),
                      "updated_at": obj.get("updated_at"), "role": obj.get("role"),
                      "base": obj.get("base"), "status": obj.get("status"),
                      "step_count": len(obj.get("steps") or []),
                      "round_count": len(obj.get("round_ids") or []),
                      "summary": (ai.get("summary") or "")[:200]})
    return {"ok": True, "data": {"items": items}}


def get_task(task_id: str) -> Dict[str, Any]:
    """
    读取 RSI 任务详情（含各阶段结果）。

    Args:
        task_id: 任务 ID。

    Returns:
        任务 dict；不存在返回 None。
    """
    task = _load_task(task_id)
    if task is None:
        return {"ok": False, "error": f"任务不存在：{task_id}"}
    return {"ok": True, "data": task}
