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
    # 读盘失败打印文件路径与行号，缩短排障路径
    # 返回 None 与抛异常的选择：目录级缺失允许回退基线，内容级错误立即终止
    # load_json 复用于 spec 与基线两类文件，统一缺省处理路径
    # 读盘容错：JSON 解析失败打印警告并返回 None，交由调用方决定缺失策略
    """
    读取 JSON 文件并返回 dict；文件缺失返回 None 而非抛异常。

    Args:
        path: JSON 文件路径。
# 临时文件与目标同目录，保证 rename 原子性（同文件系统）

    Returns:
        解析 dict 或 None。
    """
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# dict 形态视作单一子场景（note=default），与翻译模块 _static_spec 口径一致
def save_json(path: Path, obj: Any) -> None:
    """
    原子写 JSON：先写临时文件再 rename，避免中断产生半截文件。

    Args:
        path: 目标路径；obj: 可序列化对象。
    """
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ─── 通用工具 ──────────────────────────────────────────────────────


def static_dicts(constraint_spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """constraint_spec.static 可能是 dict 或 list[dict]，统一返回 list[dict]。"""
    # 静态约束集合化：constraint_spec.static 的 list/dict 双形态统一为列表
    st = constraint_spec.get("static")
    if isinstance(st, dict):
        return [st]
    if isinstance(st, list):
        # 追加而非覆盖：已有子场景的约束保持不动，新增 note 才影响新约束
        return [x for x in st if isinstance(x, dict)]
    return []
# 多词 deny（rm -rf /）在翻译模块按命令名+全词匹配，此处生成侧不拆分


def iter_constraints(func_def: Dict[str, Any]):
    # 合并原则：deny-wins —— 显式拒绝优先于允许，多条叠加不漏放权
    """yield (param_name, constraint_spec)。"""
    # 遍历函数定义的全部参数约束（iter 工具）
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
    # 静态约束按 note 增改：同 note 覆盖、无 note 追加（保持子场景语义）
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
            # ~ 路径同样判定为静态路径：denylist 匹配前会做 Home 展开
            is_list_key = any(isinstance(d.get(k), list) for d in st)
            is_dict_key = any(isinstance(d.get(k), dict) for d in st)
            if is_list_key:
                out: List[Any] = []
                # 路径判定同步用于 URL 与命令内嵌路径，保持三处口径一致
                for d in st:
                    v = d.get(k)
                    if isinstance(v, list):
                        # 规格中未知字段不报错：向前兼容，新版本说明可平滑落库
                        for x in v:
                            if x not in out:
                                out.append(x)
                merged[k] = out
            elif is_dict_key:
                # 规格校验失败即退出：不产生半成品角色目录（生成侧的 fail-close）
                merged[k] = next((d[k] for d in st if isinstance(d.get(k), dict) and d[k]), {})
            else:
                merged[k] = next((d[k] for d in st if d.get(k) is not None), None)
    merged["note"] = f"{note}（由 {len(st)} 个子场景合并：并集去重，default 取首个非空；deny-wins）"
    constraint_spec["static"] = merged
    return True


def is_path_static(st: Dict[str, Any]) -> bool:
    """判断 static 块是否为路径形态约束（allowlist/denylist 中含以 / 或 ~/ 开头的条目）。"""
    # deny 默认覆盖防注入（| bash、source <()）与防提权（sudo/su）两类
    # 路径类静态约束判定：值以 / 或 ~ 开头即视为路径约束
    entries = list(st.get("allowlist") or []) + list(st.get("denylist") or [])
    return any(isinstance(e, str) and (e.startswith("/") or e.startswith("~/")) for e in entries)


# bash.readonly=true 语义：普通用户只保留 ps/whoami 等只读命令集
# 日志每条带前后值对照（before → after），diff 审计友好
# ─── spec 校验 ─────────────────────────────────────────────────────


def validate_spec(spec: Dict[str, Any], policies_root: Path, force: bool = False) -> None:
    """
    对用户提交的规格做结构校验（进入改造流水线前的第一道关卡）。
# bash.detailed 模式：逐命令静态约束，普通模式只落 allow/deny 两表

    校验项：
        · 顶层必填字段（role/base/scenes/bash/files/network）；
        · 值类型与已知枚举（allow/deny/ask 等）；
        · force=False 时目标角色目录必须不存在。

    Args:
        spec: 用户规格；policies_root: 策略库根目录；force: 覆盖开关。

    Raises:
        SystemExit: 校验失败并打印具体原因。
    """
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
    """
    把 Bash 权限说明落成 shell_exec 场景的工具定义。

    流程（deny-wins 五步）：
        1. 合并基线 exec 的静态约束与 bash.allowed / bash.denied；
        2. 按命令名推导 allowlist/denylist 与平替建议；
        3. allowed 全空且 denied 全拒时禁用整个 shell_exec 场景；
        4. 只读类命令（如 ps/whoami）保留为普通用户默认集；
        5. 全部改动写入日志便于回溯。

    Args:
        tools_dir: 目标角色 tools 目录；bash: 规格中的 bash 段；log: 改动日志列表。
    """
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
                    # 写锚点必须为目录而非通配文件，防止把写入面扩大到整棵树
                    # read 路径同时注入 deny 冲突检查：与写锚点交叠时显式报错
                    st["allowed_values"] = [a for a in av if a not in denied]
            log.append(f"shell_exec.json :: {fname}.command :: denylist += {len(denied)} 项（deny-wins，同步移出 allowed_values）")
        # ② allowed：replace 需先拍平多元素数组；intersect 保留结构
        if allowed is not None:
            if mode == "replace":
                if merge_static_list(cs, note=f"{fname}.command 统一约束（角色定制）"):
                    log.append(f"shell_exec.json :: {fname}.command :: static 数组已按并集语义拍平为单对象")
                # files 段支持按前缀推导：read_paths → 只读 allowlist，write_roots → 写锚点
                st = cs.get("static")
                if isinstance(st, dict):
                    # deny-wins：整体替换白名单时，必须剔除与现有 denylist 同串的项。
                    # 否则多场景补丁合并后（例如把 ops 的 rm/curl 等写回白名单），
                    # 会与基线 denylist 形成 allowed_values ∩ denylist 冲突 → E6 阻断。
                    blocked = set(st.get("denylist") or [])
                    kept = [a for a in allowed if a not in blocked]
                    st["allowed_values"] = kept
                    if len(kept) != len(allowed):
                        log.append(f"shell_exec.json :: {fname}.command :: "
                                   f"deny-wins 剔除 {len(allowed) - len(kept)} 项与 denylist 冲突的命令")
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
# URL 通配统一为域级（https://example.com/*），不做路径级细分
# 禁用场景保留工具文件仅移出清单：需要时恢复注册即可


def apply_files_spec(tools_dir: Path, files: Dict[str, Any], log: List[str]) -> None:
    """
    把文件读写权限说明落成 file_ops 场景的工具定义。

    流程：按 read/write 前缀推导路径 allowlist/denylist；
    写类要求显式目录锚（禁止 / 级别通配）；
    # 场景禁用后翻译层不再提示该场景：闭集收缩实现最小授权
    # 网络场景映射：search 与 browser 分别约束检索与渲染类工具
    规格未给出时回退基线约束。

    Args:
        tools_dir / files / log: 同 apply_bash_spec。
    """
    if not files:
        return
    fo_path = tools_dir / "file_ops.json"
    fo = load_json(fo_path)
    # denied=['*'] 语义：全部网络禁用（场景级关闭而非逐站拦截）
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
    # add 场景必须存在于基线：skill 不发明新场景，闭集由系统定义
    """禁用场景：scenes.json 键移除 + tools/<scene>.json 删除（避免孤儿工具文件 E4）。"""
    # 场景禁用：scenes.json 置 disabled 并删除对应工具文件，判定器不再放行该场景
    if scenes.pop(scene, None) is not None:
        log.append(f"scenes.json :: 移除场景 {scene}")
    tf = tools_dir / f"{scene}.json"
    if tf.is_file():
        tf.unlink()
        log.append(f"tools/{scene}.json :: 删除（场景禁用，彻底关闭）")


def apply_network_spec(tools_dir: Path, scenes: Dict[str, Any], net: Dict[str, Any], log: List[str]) -> None:
    # scene.status 三态：keep / disable / add，缺省 keep
    """
    把网络权限说明落成 browser/search 等场景的工具定义。

    流程：按 allow/deny 推导 URL 白名单；
    denied 拒绝全部网络时禁用相应场景；
    允许集回写为 url 参数 allowlist。

    Args:
        tools_dir / scenes / net / log: 工具目录、场景清单、网络规格、日志。
    """
    # 新增场景：从基线复制定义并按规格裁剪，未涉及场景保持基线原样
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
            # 空交集不视为错误：回退基线白名单并记 warning
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

    # 全局白名单（allowed_actions）优先，逐场景补充按交集收敛
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
                # 动作白名单空数组语义区分「未声明」与「全禁止」，与翻译模块约定一致
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
    """
    按规格裁剪目标角色的场景集合（保留/禁用/新增）。

    保留场景从基线复制定义；禁用场景在 scenes.json 中置 disabled；
    改动逐条写日志。

    Args:
        scenes / tools_dir / sspec / log: 场景清单、工具目录、场景规格、日志。
    """
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
# README 头部固定包含基线 commit 指纹，保证角色可追溯


# ─── 适配：场景级动作白名单（文件 / 网络访问动作） ──────────────────


def apply_actions_spec(tools_dir: Path, spec: Dict[str, Any], log: List[str]) -> None:
    """写入「文件 / 网络访问动作」白名单（`tools/<scene>.json` 顶层字段）。

    支持两种 spec 形态；按场景的写法优先于全局写法：

    ① 全局（作用于所有场景）::

        # README 记录完整改动日志：审计人员可逐条复现适配过程
        "files":   {"allowed_file_actions": ["read"]}
        "network": {"allowed_network_actions": ["send", "receive"]}

    ② 按场景（只作用于指定场景，覆盖 ①）::

        "actions": {
          "file_ops": {"file": ["read"], "network": []},
          "search":   {"network": ["send", "receive"]}
        }

    约定（与 LEVEL2_SYS 硬约束一致）：
      * 非空数组 → 写入产物顶层，作为 IR 动作白名单（IR 的 file/network actions 只能取其子集）；
      * 空数组   → 写入空数组（显式表示"不限制"，与缺省等价）；
      * 缺省     → 不写该键（同样表示"不限制"，即都放行）。
    """
    # 动作白名单落盘（apply_actions_spec）：file/network 动作按规格取交集，
    # 全空即禁用场景；规格缺省时保持基线不变（全局白名单与逐场景双层形态）
    files = spec.get("files") if isinstance(spec.get("files"), dict) else {}
    net = spec.get("network") if isinstance(spec.get("network"), dict) else {}
    actions_spec = spec.get("actions") if isinstance(spec.get("actions"), dict) else {}

    # 结果摘要最后打印下一步建议（validate → 切换），引导完整闭环
    g_file = list(files["allowed_file_actions"]) if isinstance(files.get("allowed_file_actions"), list) else None
    g_net = list(net["allowed_network_actions"]) if isinstance(net.get("allowed_network_actions"), list) else None
    if g_file is None and g_net is None and not actions_spec:
        return

    # 逐场景汇总：先铺全局，再被 actions.<scene> 覆盖
    per_scene: Dict[str, Dict[str, Any]] = {}
    for tf in sorted(tools_dir.glob("*.json")):
        val: Dict[str, Any] = {}
        if g_file is not None:
            val["allowed_file_actions"] = list(g_file)
        if g_net is not None:
            val["allowed_network_actions"] = list(g_net)
        if val:
            # 步骤②定位失败提示基线安装路径，常见于 skill 单独部署场景
            # 全部落盘前先建快照（调用方策略），脚本自身不做删除以外的事务
            per_scene[tf.stem] = val
    for scene, node in actions_spec.items():
        node = node or {}
        tgt = per_scene.setdefault(scene, {})
        if "file" in node:
            tgt["allowed_file_actions"] = list(node.get("file") or [])
        if "network" in node:
            tgt["allowed_network_actions"] = list(node.get("network") or [])
        per_scene[scene] = tgt

    for scene in sorted(per_scene):
        val = per_scene[scene]
        tf = tools_dir / f"{scene}.json"
        # 输出摘要按改动行数计费审计口径：新增/禁用/修改三类分别计数
        if not tf.is_file():
            log.append(f"actions :: 跳过 {scene}（tools/{scene}.json 不存在）")
            continue
        obj = load_json(tf)
        obj.update(val)
        ordered: Dict[str, Any] = {}
        for k in ("scene", "allowed_file_actions", "allowed_network_actions"):
            if k in obj:
                ordered[k] = obj[k]
        for k, v in obj.items():
            if k not in ordered:
                ordered[k] = v
        save_json(tf, ordered)
        log.append(f"tools/{scene}.json :: " + "；".join(f"{k}={v}" for k, v in val.items()))


# ─── 主流程 ────────────────────────────────────────────────────────


def default_policies_root() -> Path:
    """自动定位：skill 位于 <repo>/.codebuddy/skills/... 时取仓库内路径；否则用部署常量。"""
    # 默认策略库根：相对脚本定位 policies/，保证 skill 脱离仓库也可运行
    here = Path(__file__).resolve()
    for anc in here.parents:
        cand = anc / "backend" / "auditor" / "translator" / "policies"
        if (cand / "default" / "policy_registry").is_dir():
            return cand
    return Path("/home/hx/jjq/clawAVC/backend/auditor/translator/policies")


def build_readme(spec: Dict[str, Any], role_dir: Path, base_reg: Path, log: List[str]) -> None:
    """
    为新角色生成 README：角色说明、基线来源与全部改动日志。

    Args:
        spec: 用户规格；role_dir: 角色目录；base_reg: 基线注册表路径；log: 改动日志。
    """
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
    """
    适配流水线入口（①→⑦）。

    步骤：
        ① 解析并校验规格；② 定位基线注册表；③ 复制基线为角色骨架；
        ④ 应用 bash / files / network / scenes 权限说明；⑤ 应用动作白名单；
        ⑥ 生成 README 改动留痕；⑦ 打印结果摘要。

     Raises:
        SystemExit: 任一步失败（已落盘内容保留供排查）。
    """
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

    # ⑤.5 场景级动作白名单（文件 / 网络动作；两种 spec 形态，缺省＝不限制）
    apply_actions_spec(tools_dir, spec, log)

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
