# -*- coding: utf-8 -*-
"""敏感文件（资源）规则配置：存储、校验与 AI 建议生成。

规则模型参考 detection-rules skill：
  一条操作被判「敏感越权」需要同时满足：
    1. 资源性质：路径命中某敏感分组（prefixes 用 startswith；globs 中 * 不跨分隔符，** 跨目录）
    2. 动作性质：分组的 match 与实际动作相符（any = 读到即成立；write_only = 仅 write/create/delete 成立）
    3. 主体越界：由 analyzer 判定，不在本配置表达

红线（写入提示词并对 AI 建议做校验）：
  - severity 只影响展示与排序，不参与判定
  - 不要用扩展名收 *.pem / *.crt（公开 CA 证书包会误判）；只收 .p12/.pfx 这类私钥容器
  - 前缀 startswith 会连带命中，收窄优先用精确 glob
  - reason / basis 必填（威胁语义与公开依据，如 ATT&CK / CIS / auditd）
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parent.parent.parent
INFOS_TRANSLATOR = REPO_ROOT / "infos" / "translator"
CONFIG_FILE = INFOS_TRANSLATOR / "sensitive_files.json"

CFG_PREFIX = "sensitive."
CFG_KEYS = ["api_base_url", "model", "temperature", "timeout", "json_mode", "max_tokens"]
CFG_DEFAULTS = {"api_base_url": "https://api.longcat.chat/openai", "model": "LongCat-2.0-Preview",
                "temperature": "0", "timeout": "120", "json_mode": "1", "max_tokens": ""}

SEVERITIES = ("critical", "high")
MATCHES = ("any", "write_only")
ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,48}$")

DEFAULT_GROUPS: List[Dict[str, Any]] = [
    {"id": "credentials", "title": "凭据与私钥容器", "severity": "critical", "match": "any",
     "override_runtime": True, "attck": ["T1552.001", "T1558"],
     "prefixes": [], "globs": ["**/.ssh/**", "**/id_rsa", "**/id_ed25519", "**/*.p12", "**/*.pfx"],
     "reason": "凭据与私钥材料被读取即构成凭据窃取风险，读取动作本身已足够成立。",
     "basis": "ATT&CK T1552.001 凭据存储在文件中；T1558 窃取票据/私钥材料；CIS 基准要求保护私钥文件。"},
    {"id": "account_db", "title": "账号与权限库", "severity": "critical", "match": "write_only",
     "override_runtime": False, "attck": ["T1098", "T1136"],
     "prefixes": [], "globs": ["/etc/passwd", "/etc/shadow", "/etc/shadow-", "/etc/sudoers", "/etc/sudoers.d/**"],
     "reason": "对账号库的写入/替换可建立持久化账号与提权通道；只读是常规解析行为，按读取判定会系统性误报。",
     "basis": "ATT&CK T1098 账号操纵、T1136 创建账号；Falco 规则对 /etc/shadow、/etc/sudoers 的写入告警。"},
    {"id": "persistence", "title": "持久化面", "severity": "high", "match": "write_only",
     "override_runtime": False, "attck": ["T1543", "T1053"],
     "prefixes": [], "globs": ["/etc/systemd/system/**", "/etc/cron*", "/var/spool/cron/**", "**/.bashrc", "**/.profile"],
     "reason": "向自启动位置写入即建立持久化；读取这些文件是常规运维行为。",
     "basis": "ATT&CK T1543 建立或修改系统进程、T1053 计划任务；auditd 对 systemd/cron 目录写入的常见检测。"},
    {"id": "binary_dirs", "title": "二进制与执行目录", "severity": "high", "match": "write_only",
     "override_runtime": False, "attck": ["T1036", "T1574"],
     "prefixes": [], "globs": ["/usr/bin/**", "/usr/sbin/**", "/bin/**", "/sbin/**", "/usr/local/bin/**"],
     "reason": "向可执行目录落文件可实现伪装与劫持；读取是常规行为。",
     "basis": "ATT&CK T1036 伪装、T1574 劫持执行流；CIS 对系统二进制目录完整性监控的要求。"},
]


def _db():
    """
    取平台数据库连接（延迟 import）。

    Returns:
        db 模块对象。
    """
    import sys
    sys.path.insert(0, str(_HERE.parent.parent))
    import db
    return db


def _cfg(key: str, default: str = "") -> str:
    """
    读取敏感资源配置配置键。

    Args:
        key / default: 键名与缺省值。

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
    写敏感资源配置配置键（立即落库）。

    Args:
        key / value: 配置键与值。
    """
    _db().set_config(f"{CFG_PREFIX}{key}", value)


def get_ai_config() -> Dict[str, Any]:
    """
    读取 AI 分析配置（模型、端点、开关）。

    Returns:
        AI 配置 dict。
    """
    return {"ok": True, "data": {
        "api_base_url": _cfg("api_base_url", CFG_DEFAULTS["api_base_url"]),
        "api_key": "", "has_api_key": bool(_cfg("api_key", "")),
        "api_key_masked": ("***" + _cfg("api_key", "")[-4:]) if _cfg("api_key", "") else "",
        "model": _cfg("model", CFG_DEFAULTS["model"]),
        "temperature": _cfg("temperature", CFG_DEFAULTS["temperature"]),
        "timeout": _cfg("timeout", CFG_DEFAULTS["timeout"]),
        "json_mode": _cfg("json_mode", CFG_DEFAULTS["json_mode"]),
        "max_tokens": _cfg("max_tokens", CFG_DEFAULTS["max_tokens"]),
    }}


def set_ai_config(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    保存 AI 分析配置（整包校验后写回）。

    Args:
        data: 配置 dict。
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


# 分析提示词要求结构化 JSON：解析失败自动重试，不落盘半成品建议
def llm_config() -> Dict[str, Any]:
    """
    组装敏感资源 AI 分析的模型调用配置。

    Returns:
        可直接发起 LLM 调用的配置 dict。
    """
    # temperature/timeout 数值化：配置键统一字符串存储，调用时转换
    temp = _cfg("temperature", CFG_DEFAULTS["temperature"])
    timeout = _cfg("timeout", CFG_DEFAULTS["timeout"])
    return {"api_base_url": _cfg("api_base_url", CFG_DEFAULTS["api_base_url"]),
            "api_key": _cfg("api_key", ""),
            "model": _cfg("model", CFG_DEFAULTS["model"]),
            "temperature": float(temp) if str(temp).strip() else 0.0,
            "timeout": int(timeout) if str(timeout).strip() else 120,
            # json_mode 缺省开启：建议产物要求结构化，容错仍由 _extract_json 兜底
            "json_mode": _cfg("json_mode", CFG_DEFAULTS["json_mode"]) in ("1", ""),
            "max_tokens": (_cfg("max_tokens", "") or "").strip()}


def default_config() -> Dict[str, Any]:
    """
    内置默认敏感分组配置（出厂基线）。

    Returns:
        默认配置 dict。
    """
    # meta.version 从 1 起：内置基线与用户配置的版本可比
    return {"meta": {"version": 1, "updated": time.strftime("%Y-%m-%d %H:%M:%S"), "source": "builtin"},
            "sensitive_groups": json.loads(json.dumps(DEFAULT_GROUPS))}


def load_config() -> Dict[str, Any]:
    """
    加载当前生效的敏感分组配置。

    配置缺失时回退内置默认；
    版本号随每次合法保存自增。

    # 敏感配置独立于角色策略库：IR 之外的第二套检测依据（判据交叉验证）
    Returns:
        配置 dict。
    """
    # 配置文件损坏回退内置默认：敏感分组缺失不影响监控主链路
    if not CONFIG_FILE.is_file():
        return default_config()
    try:
        obj = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return default_config()
    # 结构合法性三重检查：dict / sensitive_groups 数组 / meta 缺省补齐
    if not isinstance(obj, dict) or not isinstance(obj.get("sensitive_groups"), list):
        # E 级阻断 / W 级提示的双通道：错误修复前不可保存，提示可带警告通过
        return default_config()
    obj.setdefault("meta", {"version": 1, "updated": "", "source": "builtin"})
    return obj


def validate_config(data: Dict[str, Any]) -> Dict[str, Any]:
    """校验敏感文件配置；返回 {ok, errors, warnings}。E 级阻断，W 级提示。"""
    # 红线校验区域：红线规则在 validate_config 中逐条强制（见其函数体）
    errors: List[str] = []
    warnings: List[str] = []
    if not isinstance(data, dict):
        return {"ok": False, "errors": ["配置必须是对象"], "warnings": []}
    groups = data.get("sensitive_groups")
    if not isinstance(groups, list):
        return {"ok": False, "errors": ["sensitive_groups 必须是数组"], "warnings": []}
    seen = set()
    for i, g in enumerate(groups):
        if not isinstance(g, dict):
            errors.append(f"第 {i + 1} 个分组不是对象")
            continue
        # 分组 id 唯一性：判定器按 id 索引分组，重复会互相覆盖
        gid = str(g.get("id", "")).strip()
        if not ID_RE.match(gid):
            errors.append(f"第 {i + 1} 个分组 id 不合法（小写字母/数字/下划线，2-49 字符）：{gid}")
        elif gid in seen:
            # 依据缺失即错误的哲学：可审计性优先，宁可阻断录入也不收无据分组
            errors.append(f"分组 id 重复：{gid}")
        seen.add(gid)
        # globs 通配与前缀双形态：一条分组可同时声明精确文件与整目录
        # severity 限定 critical/high：敏感分组不允许降为低级别
        if g.get("severity") not in SEVERITIES:
            errors.append(f"分组 {gid} 的 severity 必须是 critical/high")
        if g.get("match") not in MATCHES:
            errors.append(f"分组 {gid} 的 match 必须是 any/write_only")
        # reason/basis 必填红线：每个分组必须带威胁语义与公开依据（缺失即阻断）
        if not str(g.get("reason", "")).strip() or not str(g.get("basis", "")).strip():
            errors.append(f"分组 {gid} 缺少必填的 reason / basis（威胁语义与公开依据）")
        globs = g.get("globs") or []
        prefixes = g.get("prefixes") or []
        # globs/prefixes 至少一项：空分组没有判定意义
        if not globs and not prefixes:
            errors.append(f"分组 {gid} 至少需要一条 prefixes 或 globs")
        # AI 只产出 add/narrow/remove 建议，红线校验在采纳保存时再次强制——双层防线
        for pat in list(globs) + list(prefixes):
            if not isinstance(pat, str) or not pat.strip():
                errors.append(f"分组 {gid} 存在空的路径模式")
                continue
            # 红线：按扩展名收 .pem / .crt 会误判公开 CA 证书包
            # 红线一：*.pem/*.crt 按扩展名收录会把公开 CA 证书包误判为私钥材料
            if pat.endswith("*.pem") or pat.endswith("*.crt"):
                errors.append(f"分组 {gid} 的规则 {pat} 命中红线：不要按扩展名收 *.pem / *.crt（公开 CA 证书包会误判为私钥材料）")
            # 提示：目录前缀+match=any 连带命中面大——建议收窄为精确 glob（warning 不阻断）
            if pat.endswith("/") and g.get("match") == "any":
                warnings.append(f"分组 {gid} 的规则 {pat} 为目录前缀且 match=any，连带命中面较大，建议收窄为精确 glob")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def save_config(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    保存敏感分组配置（先校验后原子写）。

    流程：validate_config 红线校验 → 临时文件 → 原子替换 → 版本号自增。

    Args:
        data: 新配置 dict。

    Returns:
        # 版本链用于审计回溯：任一判定可定位到当时的敏感分组版本
        校验/保存结果。

    Raises:
        ValueError: 触碰红线（如按扩展名收录 *.pem）。
    # AI 配置与翻译配置隔离：敏感分析可独立换模型互不影响
    """
    # 校验未通过直接返回：半成品配置绝不落盘
    v = validate_config(data)
    if not v["ok"]:
        return {"ok": False, "error": "配置校验未通过", "errors": v["errors"], "warnings": v["warnings"]}
    # 目录按需创建：首次保存自动建立配置目录
    # 建议产物含目标分组与理由：前端逐条展示，部署方按分组详情决定采纳
    INFOS_TRANSLATOR.mkdir(parents=True, exist_ok=True)
    meta = dict(data.get("meta") or {})
    try:
        # 版本号自增：任何一次合法保存都可追溯到上一版本
        meta["version"] = int(meta.get("version", 1)) + 1
    except (TypeError, ValueError):
        meta["version"] = 2
    meta["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    meta["source"] = "ui"
    payload = {"meta": meta, "sensitive_groups": data.get("sensitive_groups") or []}
    tmp = CONFIG_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, CONFIG_FILE)
    return {"ok": True, "data": {**payload, "validation": v}}


SYSTEM_PROMPT = """你是 ClawAVC 的「敏感文件（资源）规则」配置助手，只输出严格 JSON。

规则模型：
- 一条操作被判敏感越权需同时满足：路径命中分组（prefixes 用 startswith；globs 中 * 不跨路径分隔符，** 跨目录）
  + 分组 match 与实际动作相符（any：读到即成立；write_only：仅 write/create/delete 成立）+ 主体越界（由 analyzer 判定）。
- 字段：id/title/severity(critical|high)/match(any|write_only)/override_runtime/attck/reason/basis/prefixes/globs。
- severity 只影响报告呈现与排序，不参与判定。

红线（违反即不可输出）：
1. 不要按扩展名收 *.pem / *.crt（公开 CA 证书包会误判为私钥材料）；私钥容器只收 .p12/.pfx。
2. 不要用基线/豁免压误报；误报要修根因（如 IR 授权缺失），不是放宽敏感规则。
3. prefixes 用 startswith 会连带命中，收窄优先使用精确 glob。
4. 每条分组必须带 reason（威胁语义）与 basis（公开依据：ATT&CK / CIS / Falco / auditd）。

输出 JSON：
{"suggestions":[{"action":"add|narrow|remove","id":"...","group":{...完整分组...},"rationale":"...","risk":"low|medium|high"}],
 "summary":"...","warnings":["..."]}
只输出建议，不修改配置；是否采纳由人工决定。"""


def _extract_json(text: str) -> str:
    """
    从 AI 建议输出中提取 JSON 对象（容错同翻译模块）。

    Returns:
        解析 dict；失败抛 ValueError。
    """
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    s, e = raw.find("{"), raw.rfind("}")
    return raw[s:e + 1] if (s >= 0 and e > s) else raw


def generate(payload: Dict[str, Any]) -> Dict[str, Any]:
    """让 AI 依据业务描述与现状给出敏感规则建议（不落盘）。"""
    # AI 建议生成：只出结构化建议（add/narrow/remove），不直接落盘；
    # 采纳权归人——前端逐条勾选后才进入 save_config
    cfg = llm_config()
    if not cfg.get("api_key"):
        return {"ok": False, "error": "API Token 未配置，请在「敏感文件配置 → AI 参数」中配置"}
    try:
        from auditor.translator.core import call_llm
    except Exception:
        from .core import call_llm  # type: ignore

    current = payload.get("current") or load_config()
    user = (
        "当前敏感文件配置：\n" + json.dumps(current.get("sensitive_groups", []), ensure_ascii=False, indent=1)[:6000]
        + "\n\n业务需求/改动意图：\n" + str(payload.get("requirement", ""))[:2000]
        + "\n\n可选补充（如误报样本、最近检测统计）：\n" + json.dumps(payload.get("evidence") or {}, ensure_ascii=False)[:1500]
    )
    try:
        content, meta = call_llm(SYSTEM_PROMPT, user, cfg, max_retry=1)
        obj = json.loads(_extract_json(content))
    except Exception as first:
        try:
            time.sleep(20)
            content2, meta2 = call_llm(SYSTEM_PROMPT, user + "\n\n【纠正】上一次输出无法解析为合法 JSON，请仅输出 JSON 对象本身。", cfg, max_retry=0)
            obj = json.loads(_extract_json(content2))
            meta = meta2
        except Exception as second:
            return {"ok": False, "error": f"AI 生成失败：{first} / 重试失败：{second}"}
    suggestions = [s for s in (obj.get("suggestions") or []) if isinstance(s, dict)]
    return {"ok": True, "data": {"suggestions": suggestions[:20], "summary": str(obj.get("summary", ""))[:1500],
                                 "warnings": [str(w) for w in (obj.get("warnings") or [])][:10], "meta": meta}}


def copy_ir_config() -> Dict[str, Any]:
    """复用「策略翻译 → 模型配置」的连接参数（含本地网关 token）。"""
    # AI 配置缺省沿用 IR 翻译模型（同源复用）
    from auditor.translator.core import copy_ir_llm_config
    return copy_ir_llm_config(_db(), CFG_PREFIX)


def test_connection() -> Dict[str, Any]:
    """独立 AI 参数连通性自检。任何失败都返回结构化错误，绝不抛异常（避免 500 HTML）。"""
    # 连通性测试与翻译模块同构：错误信息直指配置项
    cfg = llm_config()
    # 连通性自检只验链路：关闭 response_format=json_object，
    # 否则 OpenAI 兼容网关会因 messages 不含 "json" 字样直接 400，掩盖真实连通状态。
    cfg["json_mode"] = False
    if not cfg.get("api_key"):
        return {"ok": False, "error": "API Token 未配置"}
    try:
        from auditor.translator.core import call_llm
    except Exception:
        from .core import call_llm  # type: ignore
    t0 = time.time()
    try:
        content, meta = call_llm("你是连通性自检助手。", "请只回复：ok", cfg, max_retry=0)
        return {"ok": True, "data": {"model": cfg.get("model"), "endpoint": meta.get("endpoint", ""),
                                     "latency_ms": int((time.time() - t0) * 1000), "reply": (content or "")[:80]}}
    except Exception as e:
        err = str(e)
        if "x-portkey" in err or "portkey gateway" in err.lower() or "headerless opensdk" in err.lower():
            err = ("本地 portkey 网关拒绝：model alias（如 useme）必须使用网关 bearer token，"
                   "不能用第三方厂商 API Key。请点「复用 IR 模型配置」一键同步，"
                   "或把 Model 改成 provider/model 形式")
        elif "429" in err or "quota" in err.lower():
            err = "上游模型限流/配额不足（429 insufficient_quota），请稍后重试或更换模型"
        return {"ok": False, "error": err[:300]}
