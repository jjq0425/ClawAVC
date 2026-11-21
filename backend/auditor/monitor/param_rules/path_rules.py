# -*- coding: utf-8 -*-
"""路径类参数检测规则（P1–P9）。

每条规则一个 Rule 组件，判定逻辑与原 check_param_content 完全等价；
严重级、启用开关由配置层（registry）注入，规则自身不关心配置形态。
"""
import posixpath
import re
from typing import Dict, Optional

from .base import ParamCtx, Rule, RuleParam

# 写类工具名正则：与 P7/P9 的 needs_write_tool 声明配合
_WRITE_TOOL_RE = re.compile(
    r"(write|append|save|create|register|enhance|upload|insert|format|generate)", re.I
)

# 三种穿越 token 形态：正斜杠、反斜杠、根级 /.. 全覆盖
_TRAVERSAL_TOKENS = ("../", "..\\", "/..")


def _has_traversal(dec: str) -> bool:
    """
    判定解码后文本是否含穿越序列（../ ..\ /..）。

    Args:
        dec: 解码后的参数值。

    Returns:
        True 含穿越序列。
    """
    return any(t in dec for t in _TRAVERSAL_TOKENS)


# 锚点计算：绝对路径取首段为锚，normpath 判定是否脱出
def _escape_anchor(dec: str):
    """返回 (anchor, normalized)；无法计算锚点时 anchor 为空。"""
    # normpath 不处理 .. 与锚的相对关系，inside 判定由调用方组合
    norm = posixpath.normpath(dec)
    anchor = "/" + dec.lstrip("/").split("/")[0] if dec.startswith("/") else ""
    if not anchor:
        return "", norm
    inside = norm == anchor or norm.startswith(anchor + "/")
    return ("" if inside else anchor), norm


def check_traversal_escape(ctx: ParamCtx, cfg: Dict) -> Optional:
    """
    P1 路径穿越逃逸：规范化后脱出原顶层目录锚。

    示例：/data/q/../../etc/evil.sh 规范化为 /etc/evil.sh，
    脱出锚 /data → 命中 critical。

    Args:
        ctx / cfg: 参数上下文与规则配置。

    Returns:
        Hit 或 None。
    """
    if not _has_traversal(ctx.decoded):
        return None
    anchor, norm = _escape_anchor(ctx.decoded)
    if not anchor:
        return None
    # P1 证据含规范化前后对照：审计可直接看出逃逸路径
    return ctx.hit("P1_traversal_escape", cfg["severity"],
                   f"{ctx.decoded[:120]!r} 规范化后脱出 {anchor} → {norm[:120]!r}")


def check_traversal_attempt(ctx: ParamCtx, cfg: Dict) -> Optional:
    """
    P2 穿越未遂：含 ../ 但规范化后仍在锚内。

    可疑但未构成实际逃逸，级别低于 P1；
    P1 已命中的参数不再重复报 P2。

    Returns:
        Hit 或 None。
    """
    if not _has_traversal(ctx.decoded):
        return None
    anchor, _ = _escape_anchor(ctx.decoded)
    if anchor:
        # P2 与 P1 互斥：逃逸已报更高严重级，未遂才降级报告
        return None  # 已由 P1 报更严重的逃逸
    return ctx.hit("P2_traversal_attempt", cfg["severity"], f"含穿越序列: {ctx.decoded[:120]!r}")


def check_home_expand(ctx: ParamCtx, cfg: Dict) -> Optional:
    """
    P3 Home 目录展开：参数以 ~ 开头。

    主目录可达密钥与配置（~/.ssh/authorized_keys 等），判 critical。

    Returns:
        Hit 或 None。
    """
    if ctx.decoded.startswith("~"):
        # ~ 展开（如 ~/.ssh）不经解码仍保留：主目录语义在解码前后一致
        return ctx.hit("P3_home_expand", cfg["severity"], ctx.decoded[:120])
    return None


def check_encoded_variant(ctx: ParamCtx, cfg: Dict) -> Optional:
    """
    P5 编码变体：URL 解码前后不一致。

    解码后才露出真实路径/穿越序列的绕过手法，
    与 P1 联动（ctx.decoded 已是解码结果）。

    Returns:
        Hit 或 None。
    """
    if ctx.decoded != ctx.raw:
        # P5 证据保留 raw→decoded 对照：编码绕过手法一目了然
        return ctx.hit("P5_encoded_variant", cfg["severity"],
                       f"{ctx.raw[:80]!r} → {ctx.decoded[:80]!r}")
    return None


def check_proc_sys_dev(ctx: ParamCtx, cfg: Dict) -> Optional:
    """
    P6 特殊路径：目标位于 /proc /sys /dev。

    内核态与设备面的敏感入口（伪文件信息泄露）。

    Returns:
        Hit 或 None。
    """
    # // 归一处理 /proc//self 一类双斜杠变体
    norm = ctx.decoded.replace("//", "/")
    for pre in ("/proc", "/sys", "/dev"):
        if norm == pre or norm.startswith(pre + "/"):
            return ctx.hit("P6_proc_sys_dev", cfg["severity"], ctx.decoded[:120])
    return None


def check_dotfile_write(ctx: ParamCtx, cfg: Dict) -> Optional:
    """
    P7 点文件写入：写类工具目标是隐藏文件。

    .bashrc / .ssh/config 等隐藏文件是持久化惯用落点；
    仅写类工具生效（needs_write_tool=True）。

    Returns:
        Hit 或 None。
    """
    if not ctx.write_tool:
        return None
    # len(base)>1 排除「.」本身：当前目录引用不算点文件
    base = ctx.decoded.rstrip("/").split("/")[-1]
    if base.startswith(".") and len(base) > 1:
        return ctx.hit("P7_dotfile_write", cfg["severity"], f"写类工具目标为点文件: {ctx.decoded[:120]}")
    return None


def check_nul_control(ctx: ParamCtx, cfg: Dict) -> Optional:
    """
    P8 NUL/控制字符注入：可截断路径解析。

    参数含 NUL 或控制字符（ord<9、11、12）。

    Returns:
        Hit 或 None。
    """
    # 控制字符判定含 NUL(0) 与其他 C0 控制符
    if any(ord(ch) < 9 or ord(ch) in (11, 12) for ch in ctx.decoded):
        return ctx.hit("P8_nul_control", cfg["severity"], f"含控制字符: {ctx.decoded[:120]!r}")
    return None


def check_tmp_write(ctx: ParamCtx, cfg: Dict) -> Optional:
    """
    P9 临时目录写入：写类工具落盘 /tmp。

    恶意样本（下载脚本、持久化载荷）的惯用落地位置；
    仅写类工具生效。

    Returns:
        Hit 或 None。
    """
    if not ctx.write_tool:
        return None
    # P9 同样做 // 归一：/tmp//x.sh 不可绕过
    norm = ctx.decoded.replace("//", "/")
    if norm.startswith("/tmp/") or ctx.decoded.startswith("/tmp/"):
        return ctx.hit("P9_tmp_write", cfg["severity"], f"写类工具落盘临时目录: {ctx.decoded[:120]}")
    return None


def is_write_tool(tool: str) -> bool:
    """
    按工具名判定是否写类工具（write/append/save/create 等）。

    Args:
        tool: 工具名。

    Returns:
        True 视为写类。
    """
    return bool(_WRITE_TOOL_RE.search(tool or ""))


# severity 参数组件全部复用 _SEV：目录渲染共享同一份定义
_SEV = RuleParam(name="severity", label="严重级", type="severity", default="high")

# PATH_RULES 即注册清单：新增规则追加到此列表即完成接入（无需改 UI）
PATH_RULES = [
    Rule("traversal_escape", "path", "路径穿越逃逸",
         "参数规范化后脱出原顶层目录锚（如 /data/q/../../etc/xxx → /etc/xxx）",
         check_traversal_escape, severity="critical", param=_SEV),
    Rule("traversal_attempt", "path", "穿越未遂",
         "参数含 ../ 但规范化后仍在原目录内（可疑但不构成逃逸）",
         check_traversal_attempt, severity="high", param=_SEV),
    Rule("home_expand", "path", "Home 目录展开",
         "参数以 ~ 开头，指向用户主目录（可访问密钥、配置）",
         check_home_expand, severity="critical", param=_SEV),
    Rule("encoded_variant", "path", "编码变体",
         "URL 解码后路径发生变化，用于绕过关键字匹配",
         check_encoded_variant, severity="high", param=_SEV),
    Rule("proc_sys_dev", "path", "特殊路径",
         "目标位于 /proc、/sys、/dev（内核态与设备面）",
         check_proc_sys_dev, severity="high", param=_SEV),
    Rule("dotfile_write", "path", "点文件写入",
         "写类工具的目标是隐藏文件（.bashrc、.ssh/config 等）",
         check_dotfile_write, severity="medium", param=_SEV, needs_write_tool=True),
    Rule("nul_control", "path", "NUL / 控制字符注入",
         "参数含 NUL 或其他控制字符，可截断路径解析",
         check_nul_control, severity="critical", param=_SEV),
    Rule("tmp_write", "path", "临时目录写入",
         "写类工具落盘 /tmp（恶意样本惯用落地位置）",
         check_tmp_write, severity="medium", param=_SEV, needs_write_tool=True),
]
