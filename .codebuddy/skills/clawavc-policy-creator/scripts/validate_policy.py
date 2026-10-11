#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ClawAVC 策略库校验器
====================

校验一个 policy_registry 目录（scenes.json + tools/*.json）的结构一致性，
可独立使用，也被 create_role_policy.py 在生成后自动调用。

校验项：
  E1 scenes.json 存在、合法 JSON、非空 dict
  E2 tools/ 存在且至少含一个 *.json
  E3 每个 tools/*.json：合法 JSON、含 scene（str）与 functions（dict）
  E4 tools 文件的 scene 键必须存在于 scenes.json（防孤儿）
  E5 scenes.json 各场景 functions 声明的函数应存在于对应 tools 文件（warning：
     基线 default 本身存在历史遗留缺口，仅提示不判失败）
  E6 deny-wins：所有 constraint_spec.static（dict 或 list[dict]）中
     allowed_values ∩ denylist = ∅（error：策略自相矛盾）
  W1 risk_guidance.advice_docs 引用的文档存在（相对路径相对 tools/ 解析）
  W2 exec.command 每处 static 均有非空 default（normalize_ir 回填依赖）

用法：
    python3 validate_policy.py <policy_registry_dir> [--json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _walk_statics(obj: Any):
    """递归遍历 dict/list，yield 每个形如 constraint_spec 的 dict（含 static 键）。"""
    if isinstance(obj, dict):
        if "static" in obj and isinstance(obj.get("static"), (dict, list)):
            yield obj
        for v in obj.values():
            yield from _walk_statics(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_statics(item)


def _static_blocks(constraint_spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    st = constraint_spec.get("static")
    if isinstance(st, dict):
        return [st]
    if isinstance(st, list):
        return [x for x in st if isinstance(x, dict)]
    return []


def validate_registry(reg: Path) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    info: Dict[str, Any] = {}

    # E1
    scenes_path = reg / "scenes.json"
    if not scenes_path.is_file():
        errors.append("E1: scenes.json 不存在")
        scenes = None
    else:
        try:
            scenes = json.loads(scenes_path.read_text(encoding="utf-8"))
        except Exception as e:
            errors.append(f"E1: scenes.json 解析失败：{e}")
            scenes = None
        if isinstance(scenes, dict) and not scenes:
            errors.append("E1: scenes.json 是空 dict（Level-1 场景分类将失效）")
    if isinstance(scenes, dict):
        info["scenes"] = len(scenes)

    # E2
    tools_dir = reg / "tools"
    tool_files = sorted(tools_dir.glob("*.json")) if tools_dir.is_dir() else []
    if not tools_dir.is_dir() or not tool_files:
        errors.append("E2: tools/ 目录不存在或为空")
    info["tool_files"] = len(tool_files)

    # E3 / E4 / E5 / E6 / W1 / W2
    scene_of_file: Dict[str, str] = {}
    functions_of_file: Dict[str, Dict[str, Any]] = {}
    for tf in tool_files:
        try:
            obj = json.loads(tf.read_text(encoding="utf-8"))
        except Exception as e:
            errors.append(f"E3: {tf.name} 解析失败：{e}")
            continue
        scene = obj.get("scene")
        fns = obj.get("functions")
        if not isinstance(scene, str) or not scene:
            errors.append(f"E3: {tf.name} 缺少有效 scene 字段")
            continue
        if not isinstance(fns, dict):
            errors.append(f"E3: {tf.name} 的 functions 不是对象")
            continue
        scene_of_file[tf.name] = scene
        functions_of_file[tf.name] = fns
        if isinstance(scenes, dict) and scene not in scenes:
            errors.append(f"E4: {tf.name} 的 scene「{scene}」未在 scenes.json 中定义（孤儿工具文件）")

        # E6 deny-wins（含嵌套 risk_guidance 之外的全部 static 块）
        for cs in _walk_statics(obj):
            for st in _static_blocks(cs):
                av = st.get("allowed_values") or []
                dl = st.get("denylist") or []
                conflict = sorted(set(av) & set(dl))
                if conflict:
                    errors.append(f"E6: {tf.name} 存在 allowed_values ∩ denylist 冲突：{conflict}")

        # W1 advice_docs
        for cs in _walk_statics(obj):
            for st in _static_blocks(cs):
                rg = st.get("risk_guidance")
                if isinstance(rg, dict):
                    for doc in rg.get("advice_docs") or []:
                        p = str(doc.get("path") or "")
                        if not p:
                            continue
                        resolved = Path(p) if Path(p).is_absolute() else tools_dir / p
                        if not resolved.is_file():
                            warnings.append(f"W1: {tf.name} advice_docs 引用的文档缺失：{p}（注入时降级为占位提示）")

        # W2 exec.command default
        exec_def = fns.get("exec")
        if isinstance(exec_def, dict):
            cs = ((exec_def.get("params") or {}).get("command") or {}).get("constraint_spec")
            if isinstance(cs, dict):
                for st in _static_blocks(cs):
                    if not st.get("default"):
                        warnings.append(f"W2: {tf.name} exec.command 的某 static 块缺少非空 default")

    # E5 scenes → tools 函数覆盖（warning）
    if isinstance(scenes, dict):
        for scene, sc in scenes.items():
            declared = (sc or {}).get("functions") or []
            fns = functions_of_file.get(f"{scene}.json", {})
            for fn in declared:
                if fn not in fns:
                    warnings.append(f"E5(w): scenes[{scene}] 声明的函数 {fn} 未在 tools/{scene}.json 中定义（历史遗留或删漏）")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "info": info,
    }


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 2
    reg = Path(sys.argv[1])
    as_json = "--json" in sys.argv[2:]
    if not reg.is_dir():
        print(f"[错误] 目录不存在：{reg}")
        return 2
    report = validate_registry(reg)
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"策略库：{reg}")
        print(f"scenes={report['info'].get('scenes')} tool_files={report['info'].get('tool_files')}")
        for e in report["errors"]:
            print(f"  [ERROR] {e}")
        for w in report["warnings"]:
            print(f"  [WARN ] {w}")
        print(f"结论：{'通过' if report['ok'] else '失败'}（{len(report['errors'])} errors / {len(report['warnings'])} warnings）")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
