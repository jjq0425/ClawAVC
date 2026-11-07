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
    import sys
    sys.path.insert(0, str(_HERE.parent.parent))
    import db
    return db


def _cfg(key: str, default: str = "") -> str:
    try:
        val = _db().get_config(f"{CFG_PREFIX}{key}")
        return val if val is not None else default
    except Exception:
        return default


def _set_cfg(key: str, value: str) -> None:
    _db().set_config(f"{CFG_PREFIX}{key}", value)


def get_ai_config() -> Dict[str, Any]:
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
    temp = _cfg("temperature", CFG_DEFAULTS["temperature"])
    timeout = _cfg("timeout", CFG_DEFAULTS["timeout"])
    return {"api_base_url": _cfg("api_base_url", CFG_DEFAULTS["api_base_url"]),
            "api_key": _cfg("api_key", ""),
            "model": _cfg("model", CFG_DEFAULTS["model"]),
            "temperature": float(temp) if str(temp).strip() else 0.0,
            "timeout": int(timeout) if str(timeout).strip() else 120,
            "json_mode": _cfg("json_mode", CFG_DEFAULTS["json_mode"]) in ("1", ""),
            "max_tokens": (_cfg("max_tokens", "") or "").strip()}


def default_config() -> Dict[str, Any]:
    return {"meta": {"version": 1, "updated": time.strftime("%Y-%m-%d %H:%M:%S"), "source": "builtin"},
            "sensitive_groups": json.loads(json.dumps(DEFAULT_GROUPS))}


def load_config() -> Dict[str, Any]:
    if not CONFIG_FILE.is_file():
        return default_config()
    try:
        obj = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return default_config()
    if not isinstance(obj, dict) or not isinstance(obj.get("sensitive_groups"), list):
        return default_config()
    obj.setdefault("meta", {"version": 1, "updated": "", "source": "builtin"})
    return obj


def validate_config(data: Dict[str, Any]) -> Dict[str, Any]:
    """校验敏感文件配置；返回 {ok, errors, warnings}。E 级阻断，W 级提示。"""
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
        gid = str(g.get("id", "")).strip()
        if not ID_RE.match(gid):
            errors.append(f"第 {i + 1} 个分组 id 不合法（小写字母/数字/下划线，2-49 字符）：{gid}")
        elif gid in seen:
            errors.append(f"分组 id 重复：{gid}")
        seen.add(gid)
        if g.get("severity") not in SEVERITIES:
            errors.append(f"分组 {gid} 的 severity 必须是 critical/high")
        if g.get("match") not in MATCHES:
            errors.append(f"分组 {gid} 的 match 必须是 any/write_only")
        if not str(g.get("reason", "")).strip() or not str(g.get("basis", "")).strip():
            errors.append(f"分组 {gid} 缺少必填的 reason / basis（威胁语义与公开依据）")
        globs = g.get("globs") or []
        prefixes = g.get("prefixes") or []
        if not globs and not prefixes:
            errors.append(f"分组 {gid} 至少需要一条 prefixes 或 globs")
        for pat in list(globs) + list(prefixes):
            if not isinstance(pat, str) or not pat.strip():
                errors.append(f"分组 {gid} 存在空的路径模式")
                continue
            # 红线：按扩展名收 .pem / .crt 会误判公开 CA 证书包
            if pat.endswith("*.pem") or pat.endswith("*.crt"):
                errors.append(f"分组 {gid} 的规则 {pat} 命中红线：不要按扩展名收 *.pem / *.crt（公开 CA 证书包会误判为私钥材料）")
            if pat.endswith("/") and g.get("match") == "any":
                warnings.append(f"分组 {gid} 的规则 {pat} 为目录前缀且 match=any，连带命中面较大，建议收窄为精确 glob")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def save_config(data: Dict[str, Any]) -> Dict[str, Any]:
    v = validate_config(data)
    if not v["ok"]:
        return {"ok": False, "error": "配置校验未通过", "errors": v["errors"], "warnings": v["warnings"]}
    INFOS_TRANSLATOR.mkdir(parents=True, exist_ok=True)
    meta = dict(data.get("meta") or {})
    try:
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


def test_connection() -> Dict[str, Any]:
    """独立 AI 参数连通性自检。任何失败都返回结构化错误，绝不抛异常（避免 500 HTML）。"""
    cfg = llm_config()
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
        if "429" in err or "quota" in err.lower():
            err = "上游模型限流/配额不足（429 insufficient_quota），请稍后重试或更换模型"
        return {"ok": False, "error": err[:300]}
