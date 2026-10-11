#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ClawAVC 角色策略库生成器（Role Policy Forge）
=============================================

从结构化「权限说明 spec」生成一个新的 ClawAVC 角色策略库：

    policies/<role_name>/
        ├── README.md           （角色说明 + 适配记录 + 切换方式）
        └── policy_registry/
            ├── scenes.json     （从 base 复制后按 spec 适配）
            └── tools/*.json    （从 base 复制后按 spec 适配）

硬约束（与仓库现状对齐）：
1. 绝不修改既有策略库（default/ops 等）：base 只读，产物全部写入新目录；
2. Policy 名必须匹配 ^[A-Za-z0-9_-]{1,64}$
   （与 backend/auditor/translator/policy_manager.py::POLICY_NAME_RE 一致）；
3. 产物必须含 scenes.json + tools/ 才是有效策略库（_is_valid_registry 语义）；
4. 遵循 shell_exec 既有「deny-wins」裁决：新增拒绝项并入 denylist，
   并从 allowed_values 移除同串冲突项；
5. constraint_spec.static 兼容 dict / list 两种形态（core.py::_static_spec 双兼容）；
   仅当需要整体替换 allowed_values 且 static 为多元素数组时，才按
   《shell_exec_策略调整说明.md》的合并语义（并集合并、default 取首个非空）
   拍平为单一对象后替换。

用法：
    python3 create_role_policy.py --spec spec.json
        [--policies-root DIR] [--dry-run] [--force] [--skip-validate]

spec 字段详见 skill 的 references/policy_schema.md。
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

POLICY_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
BUILTIN_POLICIES = {"default", "ops"}

PATH_PARAM_NAMES = {"path", "file_path", "filepath", "file", "src", "dst", "target", "repo"}
WRITE_ACTIONS = {"create", "write", "edit", "patch", "delete", "modify"}
NETWORK_SHELL_CMDS = [
    "curl", "wget", "ping", "nslookup", "dig", "host", "traceroute", "mtr", "nc", "ncat", "netcat", "socat",
]
NETWORK_SCENES = ["search", "browser"]
GIT_FUNCTIONS = [
    "mcpguard_gitkit__git_log", "mcpguard_gitkit__git_status", "mcpguard_gitkit__git_diff",
]

# ─── 基础 IO ────────────────────────────────────────────────────────


def load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ─── 通用工具 ──────────────────────────────────────────────────────


def static_dicts(constraint_spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """constraint_spec.static 可能是 dict 或 list[dict]，统一返回 list[dict]。"""
    st = constraint_spec.get("static")
    if isinstance(st, dict):
        return [st]
    if isinstance(st, list):
        return [x for x in st if isinstance(x, dict)]
    return []


def iter_constraints(func_def: Dict[str, Any]):
    """yield (param_name, constraint_spec)。"""
    for pname, pdef in (func_def.get("params") or {}).items():
        cs = (pdef or {}).get("constraint_spec")
        if isinstance(cs, dict):
            yield pname, cs


def merge_static_list(constraint_spec: Dict[str, Any], note: str) -> bool:
    """若 static 是多元素 list，按并集语义拍平为单一 dict（幂等）。返回是否发生了合并。

    合并规则（与《shell_exec_策略调整说明.md》一致）：
    - 列表值：并集去重（保持出现顺序）；
    - default：取首个非空值；
    - dict 值（如 risk_guidance）：取首个非空对象；
    - note：替换为合并说明。
    """
    st = constraint_spec.get("static")
    if not (isinstance(st, list) and len(st) > 1):
        return False
    keys: List[str] = []
    for d in st:
        for k in d:
            if k not in keys:
                keys.append(k)
    merged: Dict[str, Any] = {}
    for k in keys:
        if k == "default":
            merged[k] = next((d[k] for d in st if d.get(k) not in (None, "")), None)
        elif k == "note":
            continue
        else:
            is_list_key = any(isinstance(d.get(k), list) for d in st)
            is_dict_key = any(isinstance(d.get(k), dict) for d in st)
            if is_list_key:
                out: List[Any] = []
                for d in st:
                    v = d.get(k)
                    if isinstance(v, list):
                        for x in v:
                            if x not in out:
                                out.append(x)
                merged[k] = out
            elif is_dict_key:
                merged[k] = next((d[k] for d in st if isinstance(d.get(k), dict) and d[k]), {})
            else:
                merged[k] = next((d[k] for d in st if d.get(k) is not None), None)
    merged["note"] = f"{note}（由 {len(st)} 个子场景合并：并集去重，default 取首个非空；deny-wins）"
    constraint_spec["static"] = merged
    return True


def is_path_static(st: Dict[str, Any]) -> bool:
    """判断 static 块是否为路径形态约束（allowlist/denylist 中含以 / 或 ~/ 开头的条目）。"""
    entries = list(st.get("allowlist") or []) + list(st.get("denylist") or [])
    return any(isinstance(e, str) and (e.startswith("/") or e.startswith("~/")) for e in entries)


# ─── spec 校验 ─────────────────────────────────────────────────────


def validate_spec(spec: Dict[str, Any], policies_root: Path, force: bool = False) -> None:
    role = str(spec.get("role_name") or "").strip()
    if not role:
        raise SystemExit("[spec 错误] 缺少必填字段 role_name")
    if not POLICY_NAME_RE.match(role):
        raise SystemExit("[spec 错误] role_name 只能包含字母/数字/下划线/中划线（1-64 字符）")
    if role in BUILTIN_POLICIES:
        raise SystemExit("[spec 错误] 不允许以内置策略名 default/ops 作为新角色名")
    if (policies_root / role).exists() and not force:
        raise SystemExit(f"[spec 错误] 策略库已存在：{policies_root / role}（可加 --force 覆盖重建）")

    base = str(spec.get("base_policy") or "default").strip()
    base_reg = policies_root / base / "policy_registry"
    if not (base_reg / "scenes.json").is_file() or not (base_reg / "tools").is_dir():
        raise SystemExit(f"[spec 错误] 基线策略库无效：{base_reg}（需包含 scenes.json 与 tools/）")
    spec["base_policy"] = base


# ─── 适配：shell_exec（Bash 场景） ─────────────────────────────────


def apply_bash_spec(tools_dir: Path, bash: Dict[str, Any], log: List[str]) -> None:
    if not bash:
        return
    shell_path = tools_dir / "shell_exec.json"
    shell = load_json(shell_path)
    fns = shell.get("functions") or {}

    denied = list(bash.get("denied_commands") or [])
    allowed = bash.get("allowed_commands")
    mode = str(bash.get("mode") or "replace")
    workdir = bash.get("workdir_allowlist")
    hint = bash.get("hint")

    for fname in ("exec", "cmd_executor__exec_command"):
        fdef = fns.get(fname)
        if not fdef:
            continue
        cs = ((fdef.get("params") or {}).get("command") or {}).get("constraint_spec")
        if not isinstance(cs, dict):
            continue
        # ① denied：denylist 并集 + allowed_values 去冲突（deny-wins）
        if denied:
            for st in static_dicts(cs):
                dl = st.setdefault("denylist", [])
                for d in denied:
                    if d not in dl:
                        dl.append(d)
                av = st.get("allowed_values")
                if isinstance(av, list):
                    st["allowed_values"] = [a for a in av if a not in denied]
            log.append(f"shell_exec.json :: {fname}.command :: denylist += {len(denied)} 项（deny-wins，同步移出 allowed_values）")
        # ② allowed：replace 需先拍平多元素数组；intersect 保留结构
        if allowed is not None:
            if mode == "replace":
                if merge_static_list(cs, note=f"{fname}.command 统一约束（角色定制）"):
                    log.append(f"shell_exec.json :: {fname}.command :: static 数组已按并集语义拍平为单对象")
                st = cs.get("static")
                if isinstance(st, dict):
                    st["allowed_values"] = list(allowed)
                log.append(f"shell_exec.json :: {fname}.command :: allowed_values 替换为 {len(allowed)} 项（mode=replace）")
            else:  # intersect
                for st in static_dicts(cs):
                    av = st.get("allowed_values")
                    if isinstance(av, list):
                        st["allowed_values"] = [a for a in av if a in allowed]
                log.append(f"shell_exec.json :: {fname}.command :: allowed_values 交集收缩（mode=intersect）")
        # ③ hint：追加角色级引导
        if hint:
            cs["dynamic_ai_hint"] = (cs.get("dynamic_ai_hint") or "").rstrip("。") + "。角色约束：" + str(hint)

    # ④ workdir：替换 allowlist
    if workdir:
        cs = ((fns.get("exec") or {}).get("params") or {}).get("workdir", {}).get("constraint_spec")
        if isinstance(cs, dict):
            if merge_static_list(cs, note="exec.workdir 统一约束（角色定制）"):
                log.append("shell_exec.json :: exec.workdir :: static 数组已按并集语义拍平为单对象")
            sts = static_dicts(cs)
            for st in sts:
                if is_path_static(st) or st.get("allowlist"):
                    st["allowlist"] = list(workdir)
            log.append(f"shell_exec.json :: exec.workdir :: allowlist 替换为 {list(workdir)}")

    # ⑤ 顶层 prompt_guidance：追加角色级要求
    pg = bash.get("prompt_guidance")
    if pg:
        shell["prompt_guidance"] = (shell.get("prompt_guidance") or "").rstrip("。") + "。" + str(pg)

    save_json(shell_path, shell)


# ─── 适配：file_ops（文件场景） ────────────────────────────────────


def apply_files_spec(tools_dir: Path, files: Dict[str, Any], log: List[str]) -> None:
    if not files:
        return
    fo_path = tools_dir / "file_ops.json"
    fo = load_json(fo_path)
    read_paths = files.get("read_paths")
    write_paths = files.get("write_paths")
    deny_paths = files.get("deny_paths")

    n_read = n_write = n_deny = 0
    for fname, fdef in (fo.get("functions") or {}).items():
        actions = set(fdef.get("file_actions") or [])
        for pname, pdef in (fdef.get("params") or {}).items():
            if pname not in PATH_PARAM_NAMES:
                continue
            cs = (pdef or {}).get("constraint_spec")
            if not isinstance(cs, dict):
                continue
            if not any(is_path_static(st) for st in static_dicts(cs)):
                continue  # 非路径形态约束（如 notekit 的 id），不动
            if read_paths is not None:
                if merge_static_list(cs, note=f"{fname}.{pname} 统一约束（角色定制）"):
                    log.append(f"file_ops.json :: {fname}.{pname} :: static 数组已按并集语义拍平为单对象")
                for st in static_dicts(cs):
                    st["allowlist"] = list(read_paths)
                n_read += 1
            if write_paths is not None and (actions & WRITE_ACTIONS):
                for st in static_dicts(cs):
                    st["allowlist"] = list(write_paths)
                n_write += 1
            if deny_paths:
                for st in static_dicts(cs):
                    dl = st.setdefault("denylist", [])
                    for d in deny_paths:
                        if d not in dl:
                            dl.append(d)
                n_deny += 1

    if read_paths is not None:
        log.append(f"file_ops.json :: path 类参数读范围 allowlist 替换为 {list(read_paths)}（{n_read} 处）")
    if write_paths is not None:
        log.append(f"file_ops.json :: 写类函数 path allowlist 替换为 {list(write_paths)}（{n_write} 处）")
    if deny_paths:
        log.append(f"file_ops.json :: path 类参数 denylist += {list(deny_paths)}（{n_deny} 处）")
    save_json(fo_path, fo)


# ─── 适配：网络场景（search / browser + shell 网络命令） ────────────


def _disable_scene(scenes: Dict[str, Any], tools_dir: Path, scene: str, log: List[str]) -> None:
    """禁用场景：scenes.json 键移除 + tools/<scene>.json 删除（避免孤儿工具文件 E4）。"""
    if scenes.pop(scene, None) is not None:
        log.append(f"scenes.json :: 移除场景 {scene}")
    tf = tools_dir / f"{scene}.json"
    if tf.is_file():
        tf.unlink()
        log.append(f"tools/{scene}.json :: 删除（场景禁用，彻底关闭）")


def apply_network_spec(tools_dir: Path, scenes: Dict[str, Any], net: Dict[str, Any], log: List[str]) -> None:
    if not net:
        return
    enabled = net.get("enabled")
    domains = net.get("allowed_domains") or []
    deny_hosts = net.get("deny_hosts") or []

    # ① 禁网：禁用 search/browser 场景 + 禁 shell 网络命令
    if enabled is False:
        for scene in NETWORK_SCENES:
            _disable_scene(scenes, tools_dir, scene, log)
        bash_net = {"denied_commands": NETWORK_SHELL_CMDS, "hint": "本角色禁止一切网络访问。"}
        apply_bash_spec(tools_dir, bash_net, log)

    # ② 域白名单：url 参数 allowlist 替换为 https://<domain>/* 形态
    if domains:
        globs: List[str] = []
        for d in domains:
            for scheme in ("https", "http"):
                g = f"{scheme}://{d}/*"
                if g not in globs:
                    globs.append(g)
        for tf in ("search.json", "browser.json"):
            path = tools_dir / tf
            if not path.is_file():
                continue
            obj = load_json(path)
            for fname, fdef in (obj.get("functions") or {}).items():
                for pname, cs in iter_constraints(fdef):
                    if pname != "url":
                        continue
                    if merge_static_list(cs, note=f"{fname}.url 统一约束（角色定制）"):
                        log.append(f"{tf} :: {fname}.url :: static 已拍平为单对象")
                    for st in static_dicts(cs):
                        st["allowlist"] = list(globs)
            save_json(path, obj)
        log.append(f"search.json/browser.json :: url allowlist 替换为域白名单 {globs}")

    # ③ 域黑名单：url 参数 denylist 并集
    if deny_hosts:
        entries: List[str] = []
        for h in deny_hosts:
            for scheme in ("http", "https"):
                e = f"{scheme}://{h}*"
                if e not in entries:
                    entries.append(e)
        for tf in ("search.json", "browser.json"):
            path = tools_dir / tf
            if not path.is_file():
                continue
            obj = load_json(path)
            for fname, fdef in (obj.get("functions") or {}).items():
                for pname, cs in iter_constraints(fdef):
                    if pname != "url":
                        continue
                    for st in static_dicts(cs):
                        dl = st.setdefault("denylist", [])
                        for e in entries:
                            if e not in dl:
                                dl.append(e)
            save_json(path, obj)
        log.append(f"search.json/browser.json :: url denylist += {entries}")


# ─── 适配：scenes / functions 增删 ─────────────────────────────────


def apply_scenes_spec(scenes: Dict[str, Any], tools_dir: Path, sspec: Dict[str, Any], log: List[str]) -> None:
    if not sspec:
        return
    # ① 禁用场景：scenes.json 键移除 + 对应 tools/<scene>.json 删除（避免孤儿工具文件 E4）
    for scene in sspec.get("disable") or []:
        _disable_scene(scenes, tools_dir, scene, log)

    # ② 移除函数：scenes.json 各场景 functions 列表 + tools/*.json 函数定义双清
    removed = sspec.get("functions_remove") or sspec.get("remove") or []
    if removed:
        for scene in scenes.values():
            fns = scene.get("functions") or []
            scene["functions"] = [f for f in fns if f not in removed]
        for tf in sorted(tools_dir.glob("*.json")):
            obj = load_json(tf)
            fns = obj.get("functions") or {}
            hit = [f for f in removed if f in fns]
            for f in hit:
                del fns[f]
            if hit:
                save_json(tf, obj)
        log.append(f"scenes.json + tools/*.json :: 移除函数 {removed}")


# ─── 主流程 ────────────────────────────────────────────────────────


def default_policies_root() -> Path:
    """自动定位：skill 位于 <repo>/.codebuddy/skills/... 时取仓库内路径；否则用部署常量。"""
    here = Path(__file__).resolve()
    for anc in here.parents:
        cand = anc / "backend" / "auditor" / "translator" / "policies"
        if (cand / "default" / "policy_registry").is_dir():
            return cand
    return Path("/home/hx/jjq/clawAVC/backend/auditor/translator/policies")


def build_readme(spec: Dict[str, Any], role_dir: Path, base_reg: Path, log: List[str]) -> None:
    lines = [
        f"# 角色策略库：{spec['role_name']}",
        "",
        f"- **角色说明**：{spec.get('title') or spec['role_name']}",
        f"- **派生基线**：`{spec['base_policy']}`（只读复制，基线未被改动）",
        f"- **创建工具**：clawavc-policy-creator skill（`create_role_policy.py`）",
        "",
        "## 权限说明（spec 原文）",
        "",
        "```json",
        json.dumps(spec, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 适配记录",
        "",
    ]
    lines += [f"- {item}" for item in log] or ["- （无字段级改动，完整继承基线）"]
    lines += [
        "",
        "## 结构与语义要点",
        "",
        "- 本目录 = `README.md` + `policy_registry/`（`scenes.json` + `tools/*.json`），"
        "符合 `policy_manager._is_valid_registry` 的有效性判定；",
        "- 三个消费通道：① 整份 tools JSON 注入 Level-2 提示词；② `normalize_ir()` 默认值回填；"
        "③ `_apply_static_deny()` 精确匹配静态拒绝；",
        "- deny-wins：denylist 与 allowed_values 冲突时以 denylist 为准（同串项已从 allowed_values 移除）。",
        "",
        "## 切换生效",
        "",
        "```bash",
        f"# 方式一：后端 API（免特权）",
        "curl -X POST http://<backend>/api/translator/policies/switch \\",
        f"     -H 'Content-Type: application/json' -d '{{\"name\": \"{spec['role_name']}\"}}'",
        "# 方式二：前端 /policy 页面切换",
        "# 切换后自动热重载（reload_registry），无需重启后端",
        "```",
        "",
        "## 校验",
        "",
        "```bash",
        f"python3 <skill>/scripts/validate_policy.py {role_dir}/policy_registry",
        "```",
        "",
    ]
    (role_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="ClawAVC 角色策略库生成器")
    ap.add_argument("--spec", required=True, help="权限说明 spec JSON 文件路径")
    ap.add_argument("--policies-root", default=None, help="policies 目录（默认自动探测）")
    ap.add_argument("--dry-run", action="store_true", help="只打印适配计划，不落盘")
    ap.add_argument("--force", action="store_true", help="目标角色目录已存在时删除重建")
    args = ap.parse_args()

    spec = load_json(Path(args.spec))
    policies_root = Path(args.policies_root) if args.policies_root else default_policies_root()
    if not policies_root.is_dir():
        raise SystemExit(f"[错误] policies 目录不存在：{policies_root}")

    validate_spec(spec, policies_root, force=args.force)
    role = spec["role_name"]
    base = spec.get("base_policy") or "default"
    base_reg = policies_root / base / "policy_registry"
    role_dir = policies_root / role
    role_reg = role_dir / "policy_registry"

    if role_dir.exists():
        if not args.force:
            raise SystemExit(f"[错误] 角色目录已存在：{role_dir}（如确认覆盖请加 --force）")
        if not args.dry_run:
            shutil.rmtree(role_dir)

    log: List[str] = [f"基线：{base}（只读）；产物：{role_dir}"]

    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "role": role, "base": base,
                          "note": "dry-run 未落盘；将执行以下适配（见 log）"}, ensure_ascii=False, indent=2))
        return 0

    # ① 复制基线（基线只读，copytree 不触碰源）
    shutil.copytree(base_reg, role_reg)
    log.append(f"复制基线 {base_reg} → {role_reg}（{len(list(role_reg.glob('tools/*.json')))} 个工具文件）")

    scenes = load_json(role_reg / "scenes.json")
    tools_dir = role_reg / "tools"

    # ② 场景与函数增删（先做，后续网络禁用依赖最新 scenes）
    apply_scenes_spec(scenes, tools_dir, spec.get("scenes") or {}, log)

    # ③ 文件场景
    apply_files_spec(tools_dir, spec.get("files") or {}, log)

    # ④ 网络场景（内部可能联动 shell_exec）
    apply_network_spec(tools_dir, scenes, spec.get("network") or {}, log)

    # ⑤ Bash 场景（显式 spec 优先于网络联动生成的内容）
    apply_bash_spec(tools_dir, spec.get("bash") or {}, log)

    # ⑥ 特殊语义：禁用 git（惯例打包：git 函数 + git 命令族）
    if spec.get("no_git"):
        apply_scenes_spec(scenes, tools_dir, {"functions_remove": GIT_FUNCTIONS}, log)
        apply_bash_spec(tools_dir, {
            "denied_commands": ["git", "git push", "git pull", "git clone", "git commit",
                                 "git add", "git log", "git status", "git diff", "git checkout",
                                 "git reset", "git merge", "git rebase", "git stash"],
            "hint": "不得使用任何 git 命令（版本控制操作不在本角色授权范围内）。",
        }, log)

    save_json(role_reg / "scenes.json", scenes)
    build_readme(spec, role_dir, base_reg, log)

    # ⑦ 产物校验（复用 validate_policy）
    report = {"ok": True, "role": role, "path": str(role_dir), "changes": log}
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from validate_policy import validate_registry

        val = validate_registry(role_reg)
        report["validation"] = val
        report["ok"] = val.get("ok", False)
    except Exception as e:  # 校验器不可用时降级为提示
        report["validation"] = {"ok": None, "error": f"校验器不可用：{e}"}

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
