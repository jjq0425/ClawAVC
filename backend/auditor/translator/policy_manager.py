"""
多 Policy 策略库管理
====================

把原本「单一策略库」升级为可跨多套 Policy：

    目录约定（父目录各含 policy_registry）:
        <backend>/auditor/translator/policies/
            ├── default/policy_registry/   (scenes.json + tools/)
            └── strict/policy_registry/

    路径模板（动态占位符 {policy}）:
        <backend>/auditor/translator/policies/{policy}/policy_registry

解析出的真实路径仍写入既有配置键 ``ir_translator.registry_path``，
因此 core.py 与 registry-health 的既有逻辑与校验完全复用，零破坏。

配置键（SQLite config 表，前缀 ir_translator.）:
    registry_path_template  路径模板，必须含 {policy}、必须以 policy_registry 结尾
    current_policy          当前生效的 Policy 名
    registry_path           解析后的真实路径（既有语义，保持单一事实来源）
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ─── 常量 ────────────────────────────────────────────────────────
_TRANSLATOR_DIR = Path(__file__).resolve().parent
_DEFAULT_TEMPLATE = str(_TRANSLATOR_DIR / "policies" / "{policy}" / "policy_registry")
_DEFAULT_POLICY = "default"

# Policy 名：仅允许字母/数字/下划线/中划线，杜绝路径穿越
POLICY_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

CFG_TEMPLATE = "registry_path_template"
CFG_CURRENT = "current_policy"
CFG_PATH = "registry_path"


# ─── 配置读写 ────────────────────────────────────────────────────
def _cfg(key: str, default: str = "") -> str:
    try:
        import sys
        sys.path.insert(0, str(_TRANSLATOR_DIR.parent.parent))  # backend/
        import db

        val = db.get_config(f"ir_translator.{key}")
        return val if val is not None else default
    except Exception:
        return default


def _set_cfg(key: str, value: str) -> None:
    import sys

    sys.path.insert(0, str(_TRANSLATOR_DIR.parent.parent))  # backend/
    import db

    db.set_config(f"ir_translator.{key}", value)


def get_template() -> str:
    """当前路径模板（含 {policy} 占位符），未配置则用默认。"""
    tpl = (_cfg(CFG_TEMPLATE, "") or "").strip()
    return tpl or _DEFAULT_TEMPLATE


def get_current_policy() -> str:
    """当前生效的 Policy 名。"""
    name = (_cfg(CFG_CURRENT, "") or "").strip()
    return name or _DEFAULT_POLICY


# ─── 路径解析 ────────────────────────────────────────────────────
def resolve_registry_path(policy: Optional[str] = None) -> str:
    """用给定（或当前）Policy 名替换模板中的 {policy} 占位符，返回真实路径。"""
    name = (policy or get_current_policy()).strip() or _DEFAULT_POLICY
    return get_template().replace("{policy}", name)


def _template_parts(tpl: str) -> Tuple[Optional[Path], str]:
    """把模板拆成 (父目录, {policy} 之后的相对后缀)。"""
    if "{policy}" not in tpl:
        return None, ""
    root, _, suffix = tpl.partition("{policy}")
    return Path(root.rstrip("/\\")), suffix.strip("/\\")


def _policy_dir_of(name: str) -> Path:
    """某个 Policy 名对应的策略库目录。"""
    root, suffix = _template_parts(get_template())
    if root is None:
        return Path(resolve_registry_path(name))
    return root / name / suffix if suffix else root / name


def _policy_container_dir_of(name: str) -> Path:
    """Policy 的容器目录（<root>/<name>），其内才是 policy_registry。

    删除/重命名必须作用于这一层，否则会残留空的 <name> 目录（幽灵 Policy）。
    """
    root, _ = _template_parts(get_template())
    if root is None:
        return Path(resolve_registry_path(name)).parent
    return root / name


def _is_valid_registry(path) -> bool:
    """策略库目录有效性：含 scenes.json 与 tools/。"""
    p = Path(path)
    return p.is_dir() and (p / "scenes.json").is_file() and (p / "tools").is_dir()


def _count_scenes(path) -> int:
    try:
        with open(Path(path) / "scenes.json", "r", encoding="utf-8") as f:
            obj = json.load(f)
        return len(obj) if isinstance(obj, dict) else 0
    except Exception:
        return 0


def _reload() -> None:
    """热重载策略库，使切换立即生效。"""
    try:
        from auditor.translator.core import reload_registry

        reload_registry()
        return
    except Exception:
        pass
    try:
        from .core import reload_registry  # type: ignore

        reload_registry()
    except Exception:
        pass


# ─── 列出 ────────────────────────────────────────────────────────
def list_policies() -> Dict[str, Any]:
    """列出全部 Policy（名/路径/场景数/健康）及当前 Policy、模板、解析路径。"""
    tpl = get_template()
    root, _ = _template_parts(tpl)
    policies: List[Dict[str, Any]] = []

    if root is not None and root.is_dir():
        for d in sorted(root.iterdir()):
            if not d.is_dir():
                continue
            base = _policy_dir_of(d.name)
            healthy = _is_valid_registry(base)
            policies.append(
                {
                    "name": d.name,
                    "path": str(base),
                    "scenes": _count_scenes(base) if healthy else 0,
                    "healthy": healthy,
                }
            )

    current = get_current_policy()
    resolved = resolve_registry_path()
    return {
        "template": tpl,
        "current": current,
        "resolved_path": resolved,
        "healthy": _is_valid_registry(resolved),
        "policies": policies,
    }


# ─── 切换（免特权） ──────────────────────────────────────────────
def switch_policy(name: str) -> Tuple[Dict[str, Any], int]:
    name = (name or "").strip()
    if not POLICY_NAME_RE.match(name):
        return {"ok": False, "error": "Policy 名只能包含字母、数字、下划线和中划线（1-64 字符）"}, 400

    path = resolve_registry_path(name)
    if not _is_valid_registry(path):
        return {"ok": False, "error": f"策略库目录无效：{path}（需包含 scenes.json 与 tools/）"}, 400

    _set_cfg(CFG_CURRENT, name)
    _set_cfg(CFG_PATH, path)
    _reload()
    return {"ok": True, "data": {"current": name, "path": path}}, 200


# ─── 新建 / 复制 ─────────────────────────────────────────────────
def create_policy(name: str, src: Optional[str] = None) -> Tuple[Dict[str, Any], int]:
    name = (name or "").strip()
    if not POLICY_NAME_RE.match(name):
        return {"ok": False, "error": "Policy 名只能包含字母、数字、下划线和中划线（1-64 字符）"}, 400

    target = _policy_dir_of(name)
    if target.exists():
        return {"ok": False, "error": f"Policy 已存在：{name}"}, 400

    try:
        if src:
            src_name = src.strip()
            if not POLICY_NAME_RE.match(src_name):
                return {"ok": False, "error": "源 Policy 名不合法"}, 400
            src_dir = _policy_dir_of(src_name)
            if not _is_valid_registry(src_dir):
                return {"ok": False, "error": f"源策略库无效：{src_dir}"}, 400
            shutil.copytree(src_dir, target)
        else:
            # 空骨架：空 scenes.json + 空 tools/
            (target / "tools").mkdir(parents=True, exist_ok=True)
            with open(target / "scenes.json", "w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return {"ok": False, "error": f"创建失败：{e}"}, 500

    _reload()
    return {"ok": True, "data": {"name": name, "path": str(target), "scenes": _count_scenes(target)}}, 200


# ─── 重命名 ──────────────────────────────────────────────────────
def rename_policy(old: str, new: str) -> Tuple[Dict[str, Any], int]:
    old, new = (old or "").strip(), (new or "").strip()
    if not POLICY_NAME_RE.match(new):
        return {"ok": False, "error": "新 Policy 名只能包含字母、数字、下划线和中划线（1-64 字符）"}, 400

    src, dst = _policy_dir_of(old), _policy_dir_of(new)
    if not _is_valid_registry(src):
        return {"ok": False, "error": f"源策略库无效：{src}"}, 400
    if dst.exists():
        return {"ok": False, "error": f"目标 Policy 已存在：{new}"}, 400

    # 移动整个容器目录（<root>/<name>），避免残留空的旧目录
    src_c, dst_c = _policy_container_dir_of(old), _policy_container_dir_of(new)
    try:
        shutil.move(str(src_c), str(dst_c))
    except Exception as e:
        return {"ok": False, "error": f"重命名失败：{e}"}, 500

    # 重命名的是当前生效 Policy → 同步切换，避免指向失效目录
    switched = False
    if get_current_policy() == old:
        _set_cfg(CFG_CURRENT, new)
        _set_cfg(CFG_PATH, str(dst))
        switched = True
    _reload()
    return {"ok": True, "data": {"name": new, "path": str(dst), "switched": switched}}, 200


# ─── 删除 ────────────────────────────────────────────────────────
def delete_policy(name: str) -> Tuple[Dict[str, Any], int]:
    name = (name or "").strip()
    if not POLICY_NAME_RE.match(name):
        return {"ok": False, "error": "Policy 名不合法"}, 400

    if name == get_current_policy():
        return {"ok": False, "error": "不能删除当前正在使用的 Policy，请先切换到其他 Policy"}, 400

    container = _policy_container_dir_of(name)
    if not container.exists():
        return {"ok": False, "error": f"Policy 目录不存在：{container}"}, 400

    # 仅当删除的是「有效」Policy 时才要求至少保留一个有效 Policy；
    # 无效的空壳目录（幽灵 Policy）始终允许清理。
    if _is_valid_registry(_policy_dir_of(name)):
        root, _ = _template_parts(get_template())
        if root is not None and root.is_dir():
            valid = sum(1 for d in root.iterdir() if d.is_dir() and _is_valid_registry(_policy_dir_of(d.name)))
            if valid <= 1:
                return {"ok": False, "error": "至少需保留一个有效 Policy"}, 400

    # 删除整个容器目录（<root>/<name>），避免残留空的 <name> 目录
    try:
        shutil.rmtree(container)
    except Exception as e:
        return {"ok": False, "error": f"删除失败：{e}"}, 500

    _reload()
    return {"ok": True}, 200


# ─── 模板配置 ────────────────────────────────────────────────────
def set_template(tpl: str) -> Tuple[Dict[str, Any], int]:
    tpl = (tpl or "").strip()
    if not tpl:
        return {"ok": False, "error": "路径模板不能为空"}, 400
    if "{policy}" not in tpl:
        return {"ok": False, "error": "路径模板必须包含 {policy} 动态占位符"}, 400
    if not tpl.endswith("policy_registry"):
        return {"ok": False, "error": "路径必须以 policy_registry 结尾"}, 400

    root, _ = _template_parts(tpl)
    if root is None or not root.is_dir():
        return {"ok": False, "error": f"模板父目录不存在：{root}"}, 400

    _set_cfg(CFG_TEMPLATE, tpl)

    # 模板变更后重新解析当前 Policy；有效则同步 registry_path 并热重载
    resolved = resolve_registry_path()
    applied = _is_valid_registry(resolved)
    if applied:
        _set_cfg(CFG_PATH, resolved)
        _reload()
    return {"ok": True, "data": {"template": tpl, "resolved_path": resolved, "applied": applied}}, 200


# ─── 启动同步 ────────────────────────────────────────────────────
def sync_registry_path() -> bool:
    """启动时确保 registry_path 与「模板 + 当前 Policy」一致（迁移/纠错场景）。

    返回是否发生了写入。
    """
    try:
        resolved = resolve_registry_path()
        if not _is_valid_registry(resolved):
            return False
        current = (_cfg(CFG_PATH, "") or "").strip()
        if current != resolved:
            _set_cfg(CFG_PATH, resolved)
            _reload()
            return True
    except Exception:
        return False
    return False
