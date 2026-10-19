# -*- coding: utf-8 -*-
"""AI 帮写（ai_writer）—— 角色策略库生成编排层。

设计要点：
  1. AI 只产出「权限意图 spec」，落盘/适配/校验一律复用 skill
     `.codebuddy/skills/clawavc-policy-creator` 的既有实现，避免格式漂移；
  2. 产物只落在新建角色目录 `policies/<role>/`，绝不修改基线（default/ops）；
  3. 配置独立存储（db key 前缀 `ai_writer.`），与翻译模块自身模型互不影响；
  4. 写盘前快照，支持按阶段回滚。
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent                       # backend/auditor/translator
BACKEND_DIR = _HERE.parent.parent                             # backend/
REPO_ROOT = BACKEND_DIR.parent                                # 仓库根
POLICIES_ROOT = _HERE / "policies"
SKILL_DIR = REPO_ROOT / ".codebuddy" / "skills" / "clawavc-policy-creator"
SKILL_MD = SKILL_DIR / "SKILL.md"
SKILL_SCRIPTS = SKILL_DIR / "scripts"
SKILL_BACKUPS = SKILL_DIR / "backups"
SNAPSHOT_ROOT = _HERE / ".ai_writer_snapshots"
STATE_ROOT = _HERE / ".ai_writer_state"

CFG_PREFIX = "ai_writer."
ROLE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
RESERVED_ROLES = {"default", "ops"}


class AiWriterError(ValueError):
    """AI 帮写参数/流程类错误：接口层据此返回 400 + 可读提示，而不是 500。

    继承 ValueError，保持既有 except ValueError 逻辑兼容。
    """


CFG_KEYS = ["api_base_url", "model", "temperature", "timeout", "json_mode"]
CFG_DEFAULTS = {
    "api_base_url": "https://api.longcat.chat/openai",
    "model": "LongCat-2.0-Preview",
    "temperature": "0",
    "timeout": "120",
    "json_mode": "1",
}

try:  # 优先按运行包路径导入，失败则回退相对导入
    from auditor.translator import policy_manager  # type: ignore
except Exception:  # pragma: no cover
    from . import policy_manager  # type: ignore


# ────────────────────────────── 配置读写 ──────────────────────────────
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
    """读取 AI 帮写配置。API Token 不回显，只返回是否已配置与掩码。"""
    data: Dict[str, Any] = {}
    for k in CFG_KEYS:
        raw = _cfg(k, "")
        data[k] = raw if raw != "" else CFG_DEFAULTS.get(k, "")
    key = _cfg("api_key", "")
    data["api_key"] = ""
    data["has_api_key"] = bool(key)
    data["api_key_masked"] = (key[:4] + "****" + key[-4:]) if len(key) > 8 else ("****" if key else "")
    data["skill_doc_path"] = str(SKILL_MD)
    data["skill_doc_exists"] = SKILL_MD.is_file()
    return {"ok": True, "data": data}


def set_config(data: Dict[str, Any]) -> Dict[str, Any]:
    """更新配置；api_key 空值不覆盖（避免误清空）。"""
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
    """供 core.call_llm 使用的配置字典（类型与 core.get_llm_config 保持一致）。"""
    temp_str = _cfg("temperature", CFG_DEFAULTS["temperature"])
    timeout_str = _cfg("timeout", CFG_DEFAULTS["timeout"])
    return {
        "api_base_url": _cfg("api_base_url", CFG_DEFAULTS["api_base_url"]),
        "api_key": _cfg("api_key", ""),
        "model": _cfg("model", CFG_DEFAULTS["model"]),
        "temperature": float(temp_str) if str(temp_str).strip() else 0.0,
        "timeout": int(timeout_str) if str(timeout_str).strip() else 120,
        "json_mode": _cfg("json_mode", CFG_DEFAULTS["json_mode"]) in ("1", ""),
    }


# ──────────────────────────── SKILL.md 读写 ────────────────────────────
def read_skill_doc() -> Dict[str, Any]:
    if not SKILL_MD.is_file():
        return {"ok": False, "error": f"SKILL.md 不存在：{SKILL_MD}"}
    txt = SKILL_MD.read_text(encoding="utf-8")
    return {
        "ok": True,
        "data": {
            "path": str(SKILL_MD),
            "content": txt,
            "size": len(txt),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(SKILL_MD.stat().st_mtime)),
            "backups": _list_skill_backups(),
        },
    }


def _list_skill_backups() -> List[Dict[str, Any]]:
    if not SKILL_BACKUPS.is_dir():
        return []
    items = []
    for p in sorted(SKILL_BACKUPS.glob("SKILL.md.bak-*"), reverse=True)[:10]:
        items.append({
            "name": p.name,
            "size": p.stat().st_size,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime)),
        })
    return items


def write_skill_doc(content: str) -> Dict[str, Any]:
    """写入 SKILL.md，写前自动备份（.bak-<时间戳>），原子替换。"""
    if not isinstance(content, str) or not content.strip():
        return {"ok": False, "error": "内容为空，拒绝写入"}
    if not SKILL_MD.is_file():
        return {"ok": False, "error": f"SKILL.md 不存在：{SKILL_MD}"}
    try:
        SKILL_BACKUPS.mkdir(parents=True, exist_ok=True)
        bak = SKILL_BACKUPS / f"SKILL.md.bak-{time.strftime('%Y%m%d%H%M%S')}"
        shutil.copy2(SKILL_MD, bak)
        tmp = SKILL_MD.with_suffix(SKILL_MD.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, SKILL_MD)
        return {"ok": True, "data": {"backup": bak.name, "size": len(content), "path": str(SKILL_MD)}}
    except Exception as e:
        return {"ok": False, "error": f"写入失败：{e}"}


def restore_skill_doc(backup: str = "") -> Dict[str, Any]:
    """恢复 SKILL.md：优先 git HEAD 版本，失败则用指定/最新备份。"""
    try:
        rel = SKILL_MD.relative_to(REPO_ROOT)
        out = subprocess.run(["git", "-C", str(REPO_ROOT), "show", f"HEAD:{rel.as_posix()}"],
                             capture_output=True, text=True, timeout=20)
        if out.returncode == 0 and out.stdout.strip():
            return {"ok": True, "data": {"source": "git HEAD", **{k: v for k, v in write_skill_doc(out.stdout).get("data", {}).items()}}}
    except Exception:
        pass

    if backup:
        src = SKILL_BACKUPS / backup
        if not src.is_file():
            return {"ok": False, "error": f"备份不存在：{backup}"}
    else:
        cands = sorted(SKILL_BACKUPS.glob("SKILL.md.bak-*"), reverse=True)
        if not cands:
            return {"ok": False, "error": "无可用的备份，且 git 版本不可用"}
        src = cands[0]
    try:
        return {"ok": True, "data": {"source": src.name,
                                     **write_skill_doc(src.read_text(encoding="utf-8")).get("data", {})}}
    except Exception as e:
        return {"ok": False, "error": f"恢复失败：{e}"}


# ─────────────────────────── skill 脚本复用 ───────────────────────────
def _load_module(mod_name: str, path: Path):
    if not path.is_file():
        raise RuntimeError(f"skill 脚本缺失：{path}")
    spec = importlib.util.spec_from_file_location(mod_name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 skill 脚本：{path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _skill_create():
    return _load_module("clawavc_create_role_policy", SKILL_SCRIPTS / "create_role_policy.py")


def _skill_validate():
    return _load_module("clawavc_validate_policy", SKILL_SCRIPTS / "validate_policy.py")


# ───────────────────────────── 路径与快照 ─────────────────────────────
def _check_role(role: str) -> None:
    if not ROLE_RE.match(role or ""):
        raise AiWriterError("角色名只能包含字母、数字、下划线和中划线（1-64 字符）")
    if role in RESERVED_ROLES:
        raise AiWriterError(f"保留名不可作为产物角色：{role}")


def registry_dir(role: str) -> Path:
    _check_role(role)
    p = Path(policy_manager.resolve_registry_path(role))
    _assert_in_policies(p)
    return p


def _assert_in_policies(p: Path) -> None:
    root = os.path.realpath(str(POLICIES_ROOT))
    rp = os.path.realpath(str(p))
    if not (rp + os.sep).startswith(root + os.sep):
        raise ValueError(f"路径越界（不在 policies 目录内）：{p}")


def container_dir(role: str) -> Path:
    reg = registry_dir(role)
    parent = reg.parent
    _assert_in_policies(parent)
    return parent


def snapshot(role: str, label: str = "") -> Dict[str, Any]:
    reg = registry_dir(role)
    if not reg.is_dir():
        return {"ok": False, "error": f"策略库不存在：{reg}"}
    base = SNAPSHOT_ROOT / role
    base.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d%H%M%S")
    dest = base / ts
    seq = 1
    while dest.exists():  # 同一秒内的连续操作也要保证快照名唯一
        seq += 1
        dest = base / f"{ts}-{seq}"
    ts = dest.name
    shutil.copytree(reg, dest)
    (base / f"{ts}.meta.json").write_text(
        json.dumps({"ts": ts, "role": role, "label": label,
                    "at": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return {"ok": True, "data": {"ts": ts, "path": str(dest), "label": label}}


def list_snapshots(role: str) -> Dict[str, Any]:
    base = SNAPSHOT_ROOT / role if ROLE_RE.match(role or "") else None
    items: List[Dict[str, Any]] = []
    if base and base.is_dir():
        for meta in sorted(base.glob("*.meta.json"), reverse=True)[:20]:
            try:
                items.append(json.loads(meta.read_text(encoding="utf-8")))
            except Exception:
                continue
    return {"ok": True, "data": {"items": items}}


def rollback(role: str, ts: str = "") -> Dict[str, Any]:
    reg = registry_dir(role)
    base = SNAPSHOT_ROOT / role
    if not base.is_dir():
        return {"ok": False, "error": "无可用快照"}
    cands = sorted([p for p in base.iterdir() if p.is_dir()], reverse=True)
    if ts:
        cands = [base / ts] if (base / ts).is_dir() else []
    if not cands:
        return {"ok": False, "error": f"快照不存在：{ts or '(最新)'}"}
    src = cands[0]
    if reg.is_dir():
        shutil.rmtree(reg)
    shutil.copytree(src, reg)
    policy_manager._reload()
    return {"ok": True, "data": {"restored_from": src.name, "path": str(reg)}}


# ────────────────────────────── 状态 spec ──────────────────────────────
def _state_dir(role: str) -> Path:
    _check_role(role)
    return STATE_ROOT / role


def load_spec(role: str) -> Dict[str, Any]:
    p = _state_dir(role) / "spec.json"
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"role_name": role, "base_policy": "default", "title": "", "instruction": "",
            "files": {}, "network": {}, "bash": {}, "scenes": {}, "no_git": False}


def save_spec(role: str, spec: Dict[str, Any]) -> None:
    d = _state_dir(role)
    d.mkdir(parents=True, exist_ok=True)
    (d / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_patch(spec: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    for key in ("files", "network", "bash", "scenes"):
        src = patch.get(key)
        if isinstance(src, dict) and src:
            dst = spec.setdefault(key, {})
            for k, v in src.items():
                if isinstance(v, list) and isinstance(dst.get(k), list):
                    dst[k] = list(dict.fromkeys(list(dst[k]) + list(v)))
                else:
                    dst[k] = v
    # 场景级动作白名单（两级结构）：{"<scene>": {"file": [...], "network": [...]}}
    acts = patch.get("actions")
    if isinstance(acts, dict) and acts:
        dst = spec.setdefault("actions", {})
        for scene, node in acts.items():
            if not isinstance(node, dict):
                continue
            dnode = dst.setdefault(scene, {})
            for k, v in node.items():
                if isinstance(v, list):
                    base_vals = list(dnode.get(k) or [])
                    dnode[k] = list(dict.fromkeys(base_vals + list(v))) if base_vals else list(v)
                else:
                    dnode[k] = v
    if "no_git" in patch:
        spec["no_git"] = bool(patch["no_git"])
    return spec


# ─────────────────────────── 阶段 A：建目录结构 ───────────────────────────
def list_base_scenes(base: str = "default") -> Dict[str, Any]:
    p = Path(policy_manager.resolve_registry_path(base))
    _assert_in_policies(p)
    f = p / "scenes.json"
    if not f.is_file():
        return {"ok": False, "error": f"基线 scenes.json 不存在：{f}"}
    obj = json.loads(f.read_text(encoding="utf-8"))
    scenes = []
    for name, meta in (obj or {}).items():
        if isinstance(meta, dict):
            scenes.append({"name": name, "desc": meta.get("desc", ""), "functions": meta.get("functions", [])})
        else:
            scenes.append({"name": name, "desc": "", "functions": []})
    return {"ok": True, "data": {"base": base, "scenes": scenes}}


def scaffold(role: str, base: str = "default", title: str = "", instruction: str = "",
             force: bool = False) -> Dict[str, Any]:
    _check_role(role)
    if base not in ("default", "ops") and not ROLE_RE.match(base or ""):
        return {"ok": False, "error": "基线名不合法"}
    target = Path(policy_manager.resolve_registry_path(role))
    _assert_in_policies(target)
    if target.exists():
        if not force:
            return {"ok": False, "error": f"角色目录已存在：{target.name}（如需重建请勾选强制覆盖）"}
        shutil.rmtree(target)
    res, _code = policy_manager.create_policy(role, src=base)
    if not res.get("ok"):
        return res
    spec = {"role_name": role, "base_policy": base, "title": title or role,
            "instruction": instruction, "files": {}, "network": {}, "bash": {},
            "scenes": {}, "no_git": False}
    save_spec(role, spec)
    snap = snapshot(role, "scaffold")
    tools = sorted(p.name for p in (target / "tools").glob("*.json")) if (target / "tools").is_dir() else []
    base_scenes = list_base_scenes(base).get("data", {}).get("scenes", [])
    return {"ok": True, "data": {"role": role, "base": base, "path": str(target), "tools": tools,
                                 "tool_count": len(tools), "scenes": [s["name"] for s in base_scenes],
                                 "snapshot": snap.get("data", {}).get("ts", "")}}


# ───────────────────── 落盘：复用 skill 适配函数 ─────────────────────
def apply_spec(role: str, spec: Dict[str, Any], reset: bool = True) -> Dict[str, Any]:
    """把完整 spec 应用到角色策略库；reset=True 时先按基线重建（保证结果可复现）。"""
    reg = registry_dir(role)
    base = spec.get("base_policy") or "default"
    base_reg = Path(policy_manager.resolve_registry_path(base))
    _assert_in_policies(base_reg)
    if not reg.is_dir():
        return {"ok": False, "error": f"角色策略库不存在，请先执行阶段 A：{reg}"}
    m = _skill_create()
    log: List[str] = []
    if reset:
        shutil.rmtree(reg)
        shutil.copytree(base_reg, reg)
        log.append(f"按基线 {base} 重建：{reg}")
    scenes = m.load_json(reg / "scenes.json")
    tools_dir = reg / "tools"
    m.apply_scenes_spec(scenes, tools_dir, spec.get("scenes") or {}, log)
    m.apply_files_spec(tools_dir, spec.get("files") or {}, log)
    m.apply_network_spec(tools_dir, scenes, spec.get("network") or {}, log)
    m.apply_bash_spec(tools_dir, spec.get("bash") or {}, log)
    # 场景级动作白名单（文件 / 网络访问动作；缺省 = 不限制）
    m.apply_actions_spec(tools_dir, spec.get("actions") or {}, log)
    if spec.get("no_git"):
        m.apply_scenes_spec(scenes, tools_dir, {"functions_remove": m.GIT_FUNCTIONS}, log)
        m.apply_bash_spec(tools_dir, {"denied_commands": [
            "git", "git push", "git pull", "git clone", "git commit", "git add", "git log",
            "git status", "git diff", "git checkout", "git reset", "git merge", "git rebase", "git stash"],
            "hint": "不得使用任何 git 命令（版本控制操作不在本角色授权范围内）。"}, log)
    m.save_json(reg / "scenes.json", scenes)
    try:
        m.build_readme(spec, container_dir(role), base_reg, log)
    except Exception as e:
        log.append(f"README 生成失败（不影响策略）：{e}")
    policy_manager._reload()
    save_spec(role, spec)
    return {"ok": True, "data": {"role": role, "path": str(reg), "changes": log}}


def validate(role: str) -> Dict[str, Any]:
    reg = registry_dir(role)
    if not reg.is_dir():
        return {"ok": False, "error": f"角色策略库不存在：{reg}"}
    report = _skill_validate().validate_registry(reg)
    return {"ok": True, "data": {"role": role, **report}}


# ────────────────────────────── LLM 交互 ──────────────────────────────
def _skill_prompt_base() -> str:
    """SKILL.md 正文作为系统提示词基座（可在 AI 参数抽屉中编辑）。"""
    try:
        return SKILL_MD.read_text(encoding="utf-8") if SKILL_MD.is_file() else ""
    except Exception:
        return ""


def _extract_json(text: str) -> Any:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start:end + 1]
    return json.loads(raw)


def _llm_json(system: str, user: str, cfg: Dict[str, Any]) -> Tuple[Any, Dict[str, Any]]:
    """调用 LLM 并解析 JSON；解析失败时自动纠正重试一次。"""
    if not cfg.get("api_key"):
        raise RuntimeError("API Token 未配置，请在「AI 帮写 → AI 参数」抽屉中配置")
    try:
        from auditor.translator.core import call_llm
    except Exception:
        from .core import call_llm  # type: ignore

    content, meta = call_llm(system, user, cfg, max_retry=1)
    try:
        return _extract_json(content), meta
    except Exception as e:
        fix = (f"{user}\n\n【纠正】上一次输出无法解析为 JSON（{e}）。"
               "请只输出一个 JSON 对象，不要包含解释、注释或 Markdown 代码块。")
        content2, meta2 = call_llm(system, fix, cfg, max_retry=1)
        meta2["repaired"] = True
        return _extract_json(content2), meta2


def test_connection() -> Dict[str, Any]:
    cfg = llm_config()
    if not cfg.get("api_key"):
        return {"ok": False, "error": "API Token 未配置，请在「AI 帮写 → AI 参数」抽屉中配置"}
    try:
        from auditor.translator.core import call_llm
    except Exception:
        from .core import call_llm  # type: ignore
    t0 = time.time()
    content, meta = call_llm("你是连通性自检助手。", "请只回复：ok", cfg, max_retry=0)
    return {"ok": True, "data": {"model": cfg.get("model"), "endpoint": meta.get("endpoint", ""),
                                 "latency_ms": int((time.time() - t0) * 1000),
                                 "reply": (content or "")[:80]}}


# ──────────────────────── 阶段 B：AI 生成场景清单 ────────────────────────
SCENE_KEYS_HINT = {
    "file_ops": "files（读写/禁止路径）",
    "shell_exec": "bash（命令白/黑名单、workdir）+ 可选 network",
    "terminal_session": "bash",
    "runtime_exec": "bash + 可选 network",
    "search": "network（允许域名）",
    "browser": "network（允许域名）",
}

SCENE_SYSTEM = """你是 ClawAVC 角色策略库的场景规划器。必须严格遵守下列 skill 规范（硬约束：基线只读、deny-wins、角色名规则）：

----- SKILL.md 开始 -----
{skill}
----- SKILL.md 结束 -----

任务：根据用户给出的角色权限说明，从【基线场景清单】中决定哪些场景需要禁用。

输出要求（只输出 JSON，禁止 Markdown 代码块与解释文字）：
{{
  "disable": ["<基线中存在的场景名>"],
  "keep": ["<保留的场景名，可选>"],
  "functions_remove": ["<需整体移除的工具函数名，可选>"],
  "reason": {{"<场景名>": "<一句话理由>"}},
  "summary": "<整体说明>"
}}

规则：
1. disable 与 keep 中的名字必须来自给定的基线场景清单，严禁臆造新场景名；
2. 无法判断时保持保守（不禁用），并在 reason 中说明假设；
3. functions_remove 仅用于明确要整体剔除的工具函数（如 no_git 场景填 GIT 系列函数）。
"""

SCENE_USER = """【基线】{base}
【基线场景清单】
{scenes}

【角色名】{role}
【角色说明】{title}
【用户权限说明】
{instruction}

【补充提示】{hint}

请输出上述 JSON。"""


def generate_scenes(role: str, base: str, instruction: str, hint: str = "", title: str = "") -> Dict[str, Any]:
    base_res = list_base_scenes(base)
    if not base_res.get("ok"):
        return base_res
    scenes = base_res["data"]["scenes"]
    system = SCENE_SYSTEM.format(skill=_skill_prompt_base()[:12000])
    user = SCENE_USER.format(base=base, scenes=json.dumps(scenes, ensure_ascii=False, indent=1),
                             role=role, title=title or role, instruction=instruction or "（未填写，按最小权限假设）",
                             hint=hint or "（无）")
    obj, meta = _llm_json(system, user, llm_config())
    if not isinstance(obj, dict):
        return {"ok": False, "error": "AI 输出不是 JSON 对象"}
    names = {s["name"] for s in scenes}
    disable = [x for x in (obj.get("disable") or []) if isinstance(x, str) and x in names]
    keep = [x for x in (obj.get("keep") or []) if isinstance(x, str) and x in names and x not in disable]
    reason = {k: v for k, v in (obj.get("reason") or {}).items() if isinstance(k, str)}
    funcs = [x for x in (obj.get("functions_remove") or []) if isinstance(x, str)]

    spec = load_spec(role)
    spec["scenes"] = {"disable": disable}
    if funcs:
        spec["scenes"]["functions_remove"] = funcs
    if title:
        spec["title"] = title
    if instruction:
        spec["instruction"] = instruction
    save_spec(role, spec)
    return {"ok": True, "data": {"role": role, "base": base, "disable": disable, "keep": keep,
                                 "functions_remove": funcs, "reason": reason,
                                 "summary": obj.get("summary", ""), "meta": meta,
                                 "all_scenes": [s["name"] for s in scenes], "spec": spec}}


# ────────────────────── 阶段 C：AI 填充场景具体内容 ──────────────────────
CONTENT_SYSTEM = """你是 ClawAVC 角色策略库的权限定义器。必须严格遵守下列 skill 规范（硬约束：基线只读、deny-wins、最小权限）：

----- SKILL.md 开始 -----
{skill}
----- SKILL.md 结束 -----

任务：为指定场景给出该角色的权限约束（spec 片段）。

输出要求（只输出 JSON，禁止 Markdown 代码块与解释文字）：
{{
  "scene": "<场景名>",
  "files": {{"read_paths": ["..."], "write_paths": ["..."], "deny_paths": ["..."]}},
  "network": {{"enabled": true, "allowed_domains": ["api.example.com"], "deny_hosts": []}},
  "bash": {{"mode": "replace", "allowed_commands": ["ls"], "denied_commands": ["rm"],
            "workdir_allowlist": ["/workspace/**"], "hint": "..."}},
  "no_git": false,
  "summary": "<一句话说明本场景做了什么约束>"
}}

规则：
1. 只输出与【本场景】相关的键，其余键省略（例如 file_ops 只给 files；search/browser 只给 network）；
2. 路径用 glob 形式（如 /data/**）；域名只写主机名，不要带协议与路径；
3. 遵循 deny-wins：被禁止的命令/路径不要同时出现在允许列表；
4. 无把握时按最小权限收紧，并在 hint / summary 中声明假设。
"""

CONTENT_USER = """【角色名】{role}
【角色说明】{title}
【用户权限说明】
{instruction}

【当前场景】{scene}
【场景描述】{desc}
【本场景相关工具函数】{functions}
【本场景建议使用的键】{keys}

【已有约束（避免冲突）】
{current}

【用户对本场景的补充提示】{hint}

请输出上述 JSON。"""


def generate_scene(role: str, scene: str, instruction: str = "", hint: str = "",
                   title: str = "", base: str = "default") -> Dict[str, Any]:
    base_res = list_base_scenes(base)
    if not base_res.get("ok"):
        return base_res
    meta_scene = next((s for s in base_res["data"]["scenes"] if s["name"] == scene), None)
    if meta_scene is None:
        return {"ok": False, "error": f"场景中不存在于基线 {base}：{scene}"}
    spec = load_spec(role)
    system = CONTENT_SYSTEM.format(skill=_skill_prompt_base()[:12000])
    user = CONTENT_USER.format(
        role=role, title=title or spec.get("title") or role, instruction=instruction or spec.get("instruction") or "（未填写）",
        scene=scene, desc=meta_scene.get("desc", ""), functions=json.dumps(meta_scene.get("functions", []), ensure_ascii=False),
        keys=SCENE_KEYS_HINT.get(scene, "可省略（保持基线默认）"),
        current=json.dumps({k: spec.get(k) for k in ("files", "network", "bash")}, ensure_ascii=False),
        hint=hint or "（无）")
    obj, meta = _llm_json(system, user, llm_config())
    if not isinstance(obj, dict):
        return {"ok": False, "error": "AI 输出不是 JSON 对象"}

    patch: Dict[str, Any] = {"scene": scene}
    for key in ("files", "network", "bash"):
        v = obj.get(key)
        if isinstance(v, dict) and v:
            patch[key] = _sanitize_spec_block(key, v)
    if "no_git" in obj:
        patch["no_git"] = bool(obj["no_git"])
    patch["summary"] = str(obj.get("summary", ""))[:500]
    return {"ok": True, "data": {"role": role, "scene": scene, "patch": patch, "meta": meta}}


def _sanitize_spec_block(key: str, block: Dict[str, Any]) -> Dict[str, Any]:
    """裁剪非法值，保证落盘 spec 结构整洁（deny-wins 由 skill 保证）。"""
    out: Dict[str, Any] = {}
    list_keys = {"files": ("read_paths", "write_paths", "deny_paths"),
                 "network": ("allowed_domains", "deny_hosts"),
                 "bash": ("allowed_commands", "denied_commands", "workdir_allowlist")}
    for k, v in block.items():
        if k in list_keys.get(key, ()):
            if isinstance(v, list):
                out[k] = [str(x).strip() for x in v if str(x).strip()][:200]
        elif k == "enabled":
            out[k] = bool(v)
        elif k == "mode":
            out[k] = str(v) if str(v) in ("replace", "merge", "append") else "replace"
        elif k == "hint":
            out[k] = str(v)[:500]
    return out


def apply_patch(role: str, patch: Dict[str, Any], reset: bool = True) -> Dict[str, Any]:
    """合并单场景补丁 → 按基线重建 → 落盘 → 校验，返回变更与校验结果。"""
    spec = merge_patch(load_spec(role), patch)
    applied = apply_spec(role, spec, reset=reset)
    if not applied.get("ok"):
        return applied
    snap = snapshot(role, f"scene:{patch.get('scene', '')}")
    vr = validate(role)
    return {"ok": True, "data": {"role": role, "spec": spec, "changes": applied["data"]["changes"],
                                 "snapshot": snap.get("data", {}).get("ts", ""),
                                 "validation": vr.get("data", {})}}


# ───────────────── 按场景补丁存储（保证重生成幂等） ─────────────────
def load_patches(role: str) -> Dict[str, Any]:
    p = _state_dir(role) / "patches.json"
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_patch(role: str, scene: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    """按场景保存补丁（同名场景覆盖，重生成不会累积）。"""
    d = _state_dir(role)
    d.mkdir(parents=True, exist_ok=True)
    store = load_patches(role)
    store[scene] = {k: v for k, v in patch.items() if k != "scene"}
    (d / "patches.json").write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    return store


def delete_patch(role: str, scene: str) -> Dict[str, Any]:
    store = load_patches(role)
    store.pop(scene, None)
    p = _state_dir(role) / "patches.json"
    p.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    return store


def build_spec(role: str) -> Dict[str, Any]:
    """基线 spec + 全部场景补丁 → 完整 spec（顺序稳定，结果可复现）。"""
    base_spec = load_spec(role)
    spec = {"role_name": base_spec.get("role_name", role),
            "base_policy": base_spec.get("base_policy", "default"),
            "title": base_spec.get("title", role),
            "instruction": base_spec.get("instruction", ""),
            "files": {}, "network": {}, "bash": {}, "scenes": dict(base_spec.get("scenes") or {}),
            "actions": dict(base_spec.get("actions") or {}),
            "no_git": bool(base_spec.get("no_git"))}
    for scene in sorted(load_patches(role).keys()):
        merge_patch(spec, load_patches(role)[scene])
    return spec


def apply_patches(role: str, reset: bool = True) -> Dict[str, Any]:
    """应用当前全部场景补丁（阶段 C 的「全部应用 / 重生成后应用」）。"""
    spec = build_spec(role)
    applied = apply_spec(role, spec, reset=reset)
    if not applied.get("ok"):
        return applied
    snap = snapshot(role, "apply-patches")
    vr = validate(role)
    return {"ok": True, "data": {"role": role, "spec": spec, "changes": applied["data"]["changes"],
                                 "snapshot": snap.get("data", {}).get("ts", ""),
                                 "validation": vr.get("data", {})}}


def get_state(role: str) -> Dict[str, Any]:
    return {"ok": True, "data": {"role": role, "spec": build_spec(role),
                                 "base_spec": load_spec(role), "patches": load_patches(role)}}
