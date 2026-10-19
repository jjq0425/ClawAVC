# -*- coding: utf-8 -*-
"""本地 SELinux 策略读取模块。

提供两个核心能力：
  1. read_loaded_policy  — 读取 Linux 主机已加载的编译策略（通过 seinfo/sesearch 命令）
  2. read_policy_source  — 解析策略源文件目录（.te/.if/.fc）

策略建议不在此模块：证据来自 overpriv_evidence，定向查询走 selinux_policy_query，
建议文本由 policy_gate 校验后产出。

设计约束：
  * 仅依赖标准库 + 系统命令（seinfo/sesearch），无第三方依赖
  * 兼容 Python 3.8+，主要面向 Linux 环境
  * macOS/非 Linux 环境下读取已编译策略时会返回明确的错误提示
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

# ─── 命令行工具检测 ───────────────────────────────────────────────


def _has_command(cmd: str) -> bool:
    """检测系统命令是否可用。"""
    return shutil.which(cmd) is not None


def _run_cmd(cmd: List[str], timeout: int = 30) -> Tuple[str, str, int]:
    """执行命令，返回 (stdout, stderr, returncode)。"""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout, result.stderr, result.returncode
    except FileNotFoundError:
        return "", f"命令未找到: {cmd[0]}", -1
    except subprocess.TimeoutExpired:
        return "", f"命令超时: {' '.join(cmd)}", -2
    except Exception as e:
        return "", str(e), -1


# ─── 功能一：读取已加载的编译策略 ────────────────────────────────


def read_loaded_policy(
    policy_path: str = "/sys/fs/selinux/policy",
    focus: str = "all",
) -> Dict[str, Any]:
    """读取当前 Linux 主机已加载的 SELinux 编译策略。

    通过 seinfo / sesearch 命令行工具解析策略，返回结构化数据。

    Args:
        policy_path: 编译策略文件路径（默认 /sys/fs/selinux/policy）
        focus: 返回哪类信息 "all"|"types"|"booleans"|"rules"|"file_contexts"。
            注意 focus="all" 不含 allow 规则，只有显式 focus="rules" 才会全量导出。

    Returns:
        {
            "available": True/False,
            "source": "loaded_policy",
            "policy_path": "...",
            "types": [...],          # 类型声明
            "type_attributes": [...], # 类型属性映射
            "booleans": [...],       # 布尔值及其默认值
            "allow_rules": [...],    # allow 规则（仅 focus="rules"）
            "allow_rules_note": "",  # 未加载 allow 规则时的说明
            "file_contexts": [...],  # 文件上下文（若可获取）
            "classes": [...],        # 对象类
            "errors": [...]          # 读取过程中的错误信息
        }
    """
    result: Dict[str, Any] = {
        "available": False,
        "source": "loaded_policy",
        "policy_path": policy_path,
        "types": [],
        "type_attributes": [],
        "booleans": [],
        "allow_rules": [],
        "allow_rules_note": "",
        "file_contexts": [],
        "classes": [],
        "errors": [],
    }

    # 检查是否在 Linux 系统上
    if not os.path.exists("/sys/fs/selinux") and not os.path.exists(policy_path):
        result["errors"].append(
            "SELinux 策略文件不存在（%s）。此功能需要在启用 SELinux 的 Linux 环境下运行。"
            % policy_path
        )
        return result

    # 检查命令行工具
    if not _has_command("seinfo"):
        result["errors"].append(
            "seinfo 命令不可用。请安装 setools-console 包：\n"
            "  Ubuntu/Debian: apt install setools-console\n"
            "  RHEL/CentOS/Fedora: dnf install setools-console"
        )
        return result

    result["available"] = True

    if focus in ("all", "types"):
        _load_types(result)

    if focus in ("all", "booleans"):
        _load_booleans(result)

    if focus == "rules":
        _load_allow_rules(result)
    else:
        # 全量 allow 规则通常有十几万条：既跑不动也进不了上下文，
        # 截断后还会让「没看到这条规则」被误读成「策略里没有这条规则」。
        result["allow_rules_note"] = (
            "本次未加载 allow 规则（focus=%s）。要判断某个访问是否已被放行，"
            "请用 selinux_policy_query 的 allow_search / probe_access 做定向查询，"
            "不要把这里的空列表当成策略缺口。" % focus
        )

    if focus in ("all", "classes"):
        _load_classes(result)

    if focus in ("all", "file_contexts"):
        _load_file_contexts_from_semanage(result)

    return result


def _load_types(result: Dict[str, Any]) -> None:
    """通过 seinfo 加载类型声明。"""
    stdout, stderr, rc = _run_cmd(["seinfo", "-x", "-t"])
    if rc != 0:
        result["errors"].append(f"seinfo -x -t 失败: {stderr}")
        return

    types_list = []
    for line in stdout.splitlines():
        line = line.strip().rstrip(",")
        if not line or line.startswith("#") or line.startswith("type") and line.endswith("{"):
            continue
        # 输出格式: type_name,
        name = line.rstrip(",").strip()
        if name and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
            types_list.append(name)
    result["types"] = types_list

    # 加载类型属性映射
    stdout2, _, rc2 = _run_cmd(["seinfo", "-x", "-a"])
    if rc2 == 0:
        attr_map = {}
        current_attr = None
        for line in stdout2.splitlines():
            line = line.strip().rstrip(",")
            if not line:
                continue
            if line.endswith("{"):
                # 属性块开始: attribute_name {
                current_attr = line.rstrip("{").strip()
                attr_map[current_attr] = []
            elif line == "}":
                current_attr = None
            elif current_attr:
                type_name = line.rstrip(",").strip()
                if type_name:
                    attr_map.setdefault(current_attr, []).append(type_name)
        for attr, types in attr_map.items():
            result["type_attributes"].append({
                "attribute": attr,
                "types": types,
            })


def _load_booleans(result: Dict[str, Any]) -> None:
    """通过 seinfo 加载布尔值及默认值。"""
    stdout, stderr, rc = _run_cmd(["seinfo", "-b"])
    if rc != 0:
        result["errors"].append(f"seinfo -b 失败: {stderr}")
        return

    booleans = []
    for line in stdout.splitlines():
        # 输出格式: SELinux boolean    description  default
        # 或简单格式: boolean_name
        line = line.strip()
        if not line or line.startswith("SELinux") or line.startswith("---"):
            continue
        # 尝试解析 tab/多空格分隔的输出
        parts = re.split(r"\s{2,}", line)
        if len(parts) >= 1:
            name = parts[0].strip()
            if name and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
                default_val = ""
                if len(parts) >= 3:
                    default_val = parts[2].strip().lower()
                booleans.append({
                    "name": name,
                    "default": default_val if default_val in ("on", "off", "true", "false") else "unknown",
                })
    result["booleans"] = booleans


def _load_allow_rules(result: Dict[str, Any]) -> None:
    """通过 sesearch 加载 allow 规则。"""
    if not _has_command("sesearch"):
        result["errors"].append(
            "sesearch 命令不可用，无法读取 allow 规则。请安装 setools-console 包。"
        )
        return

    stdout, stderr, rc = _run_cmd(["sesearch", "--allow", "-A"], timeout=60)
    if rc != 0:
        result["errors"].append(f"sesearch --allow 失败: {stderr}")
        return

    rules = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("allow"):
            # sesearch 输出格式:
            # allow source_type target_type : class { perms };  (conditionals)
            pass
        # 解析: allow src tgt:class perms
        m = re.match(
            r"allow\s+(\S+)\s+(\S+):(\S+)\s+\{([^}]*)\}",
            line,
        )
        if m:
            src, tgt, tclass, perms = m.group(1), m.group(2), m.group(3), m.group(4)
            rules.append({
                "rule_type": "allow",
                "src": src,
                "tgt": tgt,
                "tclass": tclass,
                "perms": sorted(perms.split()),
            })
    result["allow_rules"] = rules


def _load_classes(result: Dict[str, Any]) -> None:
    """通过 seinfo 加载对象类定义。"""
    stdout, stderr, rc = _run_cmd(["seinfo", "-c"])
    if rc != 0:
        result["errors"].append(f"seinfo -c 失败: {stderr}")
        return

    classes = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("class") or line.startswith("---"):
            continue
        name = line.strip()
        if name and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
            classes.append(name)
    result["classes"] = classes


def _load_file_contexts_from_semanage(result: Dict[str, Any]) -> None:
    """通过 semanage 获取文件上下文映射。"""
    if not _has_command("semanage"):
        return  # semanage 不可用时不报错，文件上下文是可选的

    stdout, stderr, rc = _run_cmd(["semanage", "fcontext", "-l"], timeout=30)
    if rc != 0:
        return

    fctxs = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("SELinux") or line.startswith("---"):
            continue
        # 格式: /path(/.*)?\s+all files\s+system_u:object_r:type_t:s0
        parts = line.split()
        if len(parts) >= 3:
            pattern = parts[0]
            # 找到 context 部分（通常是最后一个 : 分隔的字符串）
            for part in reversed(parts):
                if ":" in part and "_t" in part:
                    ctx_parts = part.split(":")
                    if len(ctx_parts) >= 3:
                        fctxs.append({
                            "pattern": pattern,
                            "context_type": ctx_parts[2] if len(ctx_parts) > 2 else "",
                            "raw": line,
                        })
                    break
    result["file_contexts"] = fctxs


# ─── 功能二：读取策略源文件目录 ────────────────────────────────


def read_policy_source(source_dir: str, focus: str = "all") -> Dict[str, Any]:
    """解析 SELinux 策略源文件目录（.te/.if/.fc）。

    复用 selinux_kb/parsers.py 的解析能力。

    Args:
        source_dir: 策略源文件根目录（含 policy/modules/ 子目录）
        focus: 返回哪类信息

    Returns:
        {
            "available": True/False,
            "source": "policy_source",
            "source_dir": "...",
            "modules": {...},      # 模块名 -> {types, rules, interfaces, file_contexts}
            "types": [...],        # 所有类型声明
            "booleans": [...],     # 所有布尔值声明
            "allow_rules": [...],  # 所有 allow 规则
            "interfaces": [...],   # 所有接口定义
            "file_contexts": [...],# 所有文件上下文
            "errors": [...]
        }
    """
    result: Dict[str, Any] = {
        "available": False,
        "source": "policy_source",
        "source_dir": source_dir,
        "modules": {},
        "types": [],
        "booleans": [],
        "allow_rules": [],
        "interfaces": [],
        "file_contexts": [],
        "errors": [],
    }

    if not os.path.isdir(source_dir):
        result["errors"].append(f"策略源文件目录不存在: {source_dir}")
        return result

    try:
        from selinux_kb import parsers as P
    except ImportError:
        import sys
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)
        try:
            from selinux_kb import parsers as P
        except ImportError as exc:
            result["errors"].append(f"无法导入 selinux_kb.parsers: {exc}")
            return result

    result["available"] = True

    # 定位 policy/modules 目录
    modules_root = os.path.join(source_dir, "policy", "modules")
    if not os.path.isdir(modules_root):
        # 尝试直接使用 source_dir 作为 modules 目录
        # 检查是否有 .te 文件
        te_files = [f for f in os.listdir(source_dir) if f.endswith(".te")] if os.path.isdir(source_dir) else []
        if te_files:
            modules_root = source_dir
        else:
            result["errors"].append(
                f"在 {source_dir} 下未找到 policy/modules/ 子目录或 .te 文件"
            )
            return result

    # 遍历 .te/.if/.fc 文件
    all_types = []
    all_booleans = []
    all_rules = []
    all_interfaces = []
    all_fctxs = []
    modules = {}

    for path in P.walk_files(modules_root, (".te", ".if", ".fc"), skip_dirs=(".git",)):
        rel = P.rel_path(path, source_dir)
        module = os.path.splitext(os.path.basename(path))[0]
        mod_data = modules.setdefault(module, {
            "types": [], "rules": [], "interfaces": [], "file_contexts": []
        })

        try:
            if path.endswith(".te"):
                chunks, symbols, rules, balanced = P.parse_te(path, rel, module)
                for s in symbols:
                    entry = {
                        "name": s["name"],
                        "kind": s["kind"],
                        "module": module,
                        "path": rel,
                        "line": s["line"],
                    }
                    if s["kind"] == "type":
                        all_types.append(entry)
                        mod_data["types"].append(entry)
                    elif s["kind"] == "bool":
                        all_booleans.append(entry)
                for r in rules:
                    entry = {
                        "rule_type": r["rule_type"],
                        "src": r["src"],
                        "tgt": r["tgt"],
                        "tclass": r["tclass"],
                        "perms": r["perms"],
                        "module": module,
                        "path": rel,
                        "line": r["line"],
                    }
                    all_rules.append(entry)
                    mod_data["rules"].append(entry)

            elif path.endswith(".if"):
                chunks, symbols, rules = P.parse_if(path, rel, module)
                for s in symbols:
                    entry = {
                        "name": s["name"],
                        "kind": s["kind"],
                        "module": module,
                        "path": rel,
                        "line": s["line"],
                        "summary": s.get("summary", ""),
                    }
                    all_interfaces.append(entry)
                    mod_data["interfaces"].append(entry)
                for r in rules:
                    entry = {
                        "rule_type": r["rule_type"],
                        "src": r["src"],
                        "tgt": r["tgt"],
                        "tclass": r["tclass"],
                        "perms": r["perms"],
                        "module": module,
                        "path": rel,
                        "line": r["line"],
                    }
                    all_rules.append(entry)
                    mod_data["rules"].append(entry)

            elif path.endswith(".fc"):
                chunks, fctxs = P.parse_fc(path, rel, module)
                for f in fctxs:
                    entry = {
                        "pattern": f["pattern"],
                        "ftype": f["ftype"],
                        "context_type": f["context_type"],
                        "module": module,
                        "path": rel,
                        "line": f["line"],
                    }
                    all_fctxs.append(entry)
                    mod_data["file_contexts"].append(entry)

        except Exception as exc:
            result["errors"].append(f"解析 {rel} 失败: {exc}")

    result["types"] = all_types
    result["booleans"] = all_booleans
    result["allow_rules"] = all_rules
    result["interfaces"] = all_interfaces
    result["file_contexts"] = all_fctxs
    result["modules"] = modules

    return result


# ─── 便捷接口 ────────────────────────────────────────────────────


def get_policy_summary(policy: Dict[str, Any]) -> str:
    """将策略数据格式化为人类可读的摘要文本。"""
    lines = []
    lines.append("【本地 SELinux 策略摘要】")
    lines.append(f"数据来源: {policy.get('source', '未知')}")

    types = policy.get("types", [])
    if types:
        if isinstance(types[0], dict):
            lines.append(f"类型数量: {len(types)}")
            # 列出 type 类型的声明
            type_names = [t["name"] for t in types if t.get("kind") == "type"]
            if type_names:
                lines.append(f"  type 声明: {', '.join(type_names[:20])}" +
                           (f"... 等 {len(type_names)} 个" if len(type_names) > 20 else ""))
        else:
            lines.append(f"类型数量: {len(types)}")

    booleans = policy.get("booleans", [])
    if booleans:
        lines.append(f"布尔值数量: {len(booleans)}")
        for b in booleans[:10]:
            if isinstance(b, dict):
                lines.append(f"  {b.get('name', '?')} (默认: {b.get('default', '未知')})")
            else:
                lines.append(f"  {b}")
        if len(booleans) > 10:
            lines.append(f"  ... 等 {len(booleans)} 个")

    rules = policy.get("allow_rules", [])
    if rules:
        lines.append(f"allow 规则数量: {len(rules)}")

    interfaces = policy.get("interfaces", [])
    if interfaces:
        lines.append(f"接口数量: {len(interfaces)}")

    fctxs = policy.get("file_contexts", [])
    if fctxs:
        lines.append(f"文件上下文数量: {len(fctxs)}")

    errors = policy.get("errors", [])
    if errors:
        lines.append(f"读取错误: {len(errors)}")
        for e in errors[:3]:
            lines.append(f"  - {e}")

    return "\n".join(lines)
