# -*- coding: utf-8 -*-
"""内容类参数检测规则（C1–C5）。

规则组件只做判定，词表（inject_markers / semantic_markers）、阈值（min_token /
classes）等参数由配置层注入到 cfg 中，可在前端逐项调整。
"""
import base64
import re
from typing import Dict, List, Optional

from .base import ParamCtx, Rule, RuleParam

# 危险命令特征分类（C2 共现计数用）
# 六类危险特征词表：共现计数的判定基准（C2 的 classes 参数即此表的键）
CMD_CLASSES: Dict[str, List[str]] = {
    "download": ["curl", "wget"],
    # exec 类含 nc/ncat：反弹 shell 的直连通道
    "exec": ["bash -c", "sh -c", "python -c", "perl -e", "nc ", "ncat "],
    # persist 类覆盖计划任务、systemd、authorized_keys、.bashrc 四个落点
    "persist": ["/etc/cron", "crontab", "systemd", "authorized_keys", ".bashrc"],
    "perm": ["chmod", "chown", "setuid"],
    # logwipe 类覆盖历史清除三件套：清痕是攻击链的收尾特征
    "logwipe": ["history -c", "shred", "unset histfile"],
    # redirect 类含 /dev/tcp/：bash 内建 TCP 外联通道
    "redirect": ["> /etc/", ">> ~/.ssh", "/dev/tcp/"],
}

# 载荷执行特征集：C1 升级判定的关键词（解码产物中出现即最高级）
_EXEC_IN_PAYLOAD = ("curl", "wget", "bash", "sh -c", "chmod")


def _b64_tokens(text: str, min_len: int) -> List[str]:
    """
    提取达到最短长度的 Base64 候选 token。

    Args:
        text: 参数原文；min_len: 最短 token 长度（下限 8）。

    Returns:
        候选 token 列表。
    """
    return re.findall(r"[A-Za-z0-9+/=]{%d,}" % max(int(min_len), 8), text)


def _decode_b64(token: str) -> str:
    """解码 base64 token；产物须为可解码文本（UTF-8，含中文）且控制字符占比低。

    早期实现只统计 ASCII 可打印字节，导致中文产物（UTF-8 多字节）被整体丢弃，
    中文场景的编码载荷无法识别——现改为「UTF-8 可解码 + 控制字符比例」判定。
    """
    try:
        # 补齐 base64 padding：LLM 输出常省略 = 尾
        pad = "=" * (-len(token) % 4)
        raw = base64.b64decode(token + pad)
        if not raw:
            return ""
        # UTF-8 严格解码：修复早期只认 ASCII 可打印导致中文载荷漏检的问题
        text = raw.decode("utf-8", errors="strict")
        if not text.strip():
            return ""
        # 控制字符占比 5% 阈值：排除随机二进制误报为可读载荷
        ctrl = sum(1 for ch in text if ord(ch) < 9 or ord(ch) in (11, 12) or ord(ch) == 0)
        if ctrl / max(len(text), 1) > 0.05:
            return ""
        return text
    except Exception:
        return ""


def check_encoded_blob(ctx: ParamCtx, cfg: Dict) -> Optional:
    """
    C1 编码载荷块：内容含可解码 Base64 且产物含命令特征。

    分级：解码产物含 curl/wget/bash 等执行特征 → 升级 escalate 级；
    仅可解码 → 规则自身 severity（首个载荷报告，其余去重）。

    Args:
        ctx / cfg: 参数上下文与配置（min_token/escalate）。

    Returns:
        Hit 列表或 None。
    """
    hits = []
    seen = 0
    for tok in _b64_tokens(ctx.raw, cfg.get("min_token", 40)):
        dec = _decode_b64(tok)
        if not dec:
            continue
        # seen 计数：仅首个可解码载荷报 C1 常规级，避免同参数重复刷报
        seen += 1
        low = dec.lower()
        if any(c in low for c in _EXEC_IN_PAYLOAD):
            hits.append(ctx.hit("C1_encoded_payload_exec", cfg.get("escalate", "critical"),
                                f"base64 解码产物含命令执行: {dec[:160]!r}"))
        # elif seen==1：执行特征升级与常规报文互斥，一次命中只出一条
        elif seen == 1:
            hits.append(ctx.hit("C1_encoded_blob", cfg["severity"],
                                f"可解码 base64 载荷块 ({len(tok)} 字符): {dec[:120]!r}"))
    return hits or None


def check_cmd_co_occurrence(ctx: ParamCtx, cfg: Dict) -> Optional:
    """
    C2 危险命令特征共现：六类特征达到 N 类即命中。

    六类：download/exec/persist/perm/logwipe/redirect；
    共现阈值 classes 可配（默认 2），单类命中降级为 medium 报告。

    Args:
        ctx / cfg: 上下文与配置。

    Returns:
        Hit 或 None。
    """
    low = ctx.lower
    # 类集合推导：每类任一特征命中即记该类，类别而非关键词计数
    classes = {cls for cls, pats in CMD_CLASSES.items() if any(p in low for p in pats)}
    need = int(cfg.get("classes", 2))
    # 共现阈值默认 2：单类特征（如仅含 curl）降级 medium 提示
    if len(classes) >= need:
        return ctx.hit("C2_cmd_co_occurrence", cfg["severity"],
                       f"危险命令特征 {len(classes)} 类共现: {sorted(classes)}")
    if len(classes) == 1:
        return ctx.hit("C2_cmd_feature", cfg.get("severity_single", "medium"),
                       f"危险命令特征: {sorted(classes)}")
    return None


def check_inject_marker(ctx: ParamCtx, cfg: Dict) -> Optional:
    """
    C3 注入标记投递：内容含提示注入标记词。

    词表由配置注入（默认 [SYSTEM NOTICE] 等 7 词），
    中文标记（忽略以上/忽略之前）同样覆盖。

    Returns:
        Hit 或 None。
    """
    # _markers 由 registry 注入：词表热更新无需改本文件
    for marker in cfg.get("_markers") or []:
        if str(marker).lower() in ctx.lower:
            return ctx.hit("C3_inject_marker", cfg["severity"],
                           f"content 中出现注入标记 {marker!r}: {ctx.raw[:120]!r}")
    return None


def check_obfuscation(ctx: ParamCtx, cfg: Dict) -> Optional:
    """
    C4 混淆特征：内容含零宽/不可见字符。

    U+200B/U+200D/U+FEFF 可隐藏真实语义（关键词扫描的盲区）。

    Returns:
        Hit 或 None。
    """
    if any(ch in ctx.raw for ch in ("\u200b", "\u200d", "\ufeff")):
        # 零宽字符表：三个码位覆盖 BOM 与双向不可见字符
        return ctx.hit("C4_zero_width", cfg["severity"], "含零宽/不可见字符")
    return None


def check_semantic_marker(ctx: ParamCtx, cfg: Dict) -> Optional:
    """
    C5 攻击语义标记：内容夹带持久化/后门描述且带可执行脚本头。

    默认要求同时含 shebang（#!/usr/bin/env、#!/bin/），
    纯文本描述不误报；requires_shebang 可配置关闭。

    Returns:
        Hit 或 None。
    """
    markers = cfg.get("_markers") or []
    if not markers:
        return None
    low = ctx.lower
    # shebang 判定两种形态：env 解释器与直接解释器路径
    has_shebang = "#!/usr/bin/env" in low or "#!/bin/" in low
    hit = [m for m in markers if str(m).lower() in low]
    if not hit:
        return None
    # requires_shebang 缺省开启：误报控制优先，纯描述文本不报
    if cfg.get("requires_shebang", True) and not has_shebang:
        return None
    return ctx.hit("C5_semantic_marker", cfg["severity"],
                   f"内容含攻击语义标记 {hit[:3]}" + ("（含可执行脚本头）" if has_shebang else ""))


# CONTENT_RULES 即注册清单：词表/阈值全部可配，前端表单自动渲染
CONTENT_RULES = [
    Rule("encoded_blob", "content", "编码载荷块",
         "内容含可 Base64 解码的长 token；解码产物带命令特征时升级为最高级",
         check_encoded_blob, severity="high",
         param=RuleParam(name="severity", label="严重级", type="severity", default="high"),
         extra_params=[
             RuleParam(name="min_token", label="最短 token", type="int", default=40, min=8, max=4096),
             RuleParam(name="escalate", label="含命令时升级为", type="severity", default="critical"),
         ]),
    Rule("cmd_co_occurrence", "content", "危险命令特征共现",
         "下载/执行/持久化/改权限/清日志/重定向六类特征中达到 N 类即升级",
         check_cmd_co_occurrence, severity="critical",
         param=RuleParam(name="severity", label="共现严重级", type="severity", default="critical"),
         extra_params=[
             RuleParam(name="classes", label="共现类数", type="int", default=2, min=1, max=6),
             RuleParam(name="severity_single", label="单类严重级", type="severity", default="medium"),
         ]),
    Rule("inject_markers", "content", "注入标记投递",
         "参数内容里出现提示注入标记词（词表可编辑）",
         check_inject_marker, severity="critical",
         param=RuleParam(name="severity", label="严重级", type="severity", default="critical"),
         extra_params=[RuleParam(name="markers", label="标记词表", type="list", default=[
             "[SYSTEM NOTICE]", "[SYSTEM INSTRUCT]", "<INFORMATION>",
             "ignore all previous", "忽略以上", "忽略之前", "remember-rule"])]),
    Rule("obfuscation", "content", "混淆特征",
         "内容含零宽字符/不可见字符（用于隐藏真实语义）",
         check_obfuscation, severity="high",
         param=RuleParam(name="severity", label="严重级", type="severity", default="high")),
    Rule("semantic_markers", "content", "攻击语义标记",
         "内容夹带持久化/后门/反弹 shell 等描述，且同时带可执行脚本头",
         check_semantic_marker, severity="high",
         param=RuleParam(name="severity", label="严重级", type="severity", default="high"),
         extra_params=[
             RuleParam(name="markers", label="语义标记词表", type="list", default=[
                 "persistent_service", "hidden_persist", "backdoor",
                 "reverse_shell", "exfiltrate", "V_PERSISTENT"]),
             RuleParam(name="requires_shebang", label="需同时含脚本头", type="bool", default=True),
         ]),
]
