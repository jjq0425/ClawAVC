"""
XiaoYi Skill — 基于工具调用的逐步异常分析引擎

让 LLM (小异) 通过 function calling 自主调用后端工具，
逐步获取 Round 数据，最终输出综合分析 + 策略建议。

SSE 事件流产出:
  - tool_call (started/completed/error) — 工具调用进度
  - text                         — 流式文本块（最终分析）
  - text_done                    — 最终文本完成
  - done                         — 分析结束
  - error                        — 致命错误
  - tool_limit_reached           — 达到最大工具调用轮次
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, Generator

import requests as http_requests

import db

# ─── 从 app.py 导入现有 simplify 工具函数 ────────────────────────
# app.py 在模块级定义了这些纯函数，Flask 端点懒加载本模块，
# 因此导入时 app.py 已完全加载，不存在循环依赖问题。
from app import (
    _simplify_ir_json,
    _simplify_action_json,
    _simplify_resource_facts,
    _simplify_syscall_judge,
    _simplify_kernel_judge_from_path,
    _read_file_text,
    _try_json,
)

# ─── 常量 ────────────────────────────────────────────────────────
MAX_TOOL_ROUNDS = 6  # 最大工具调用轮次，防止无限循环
DEFAULT_MAX_TOKENS = 4096

# 需要完整 arguments 才能执行的工具：这类工具的入参在流式响应中分片到达，
# 必须等本轮流结束后再执行（见 run_skill_analysis）。其余工具只需 round_id，
# 可以在拿到函数名的瞬间就执行，保持原有的实时呈现体验。
ARG_TOOLS = {"search_selinux_knowledge"}

# ─── 13 个工具的 OpenAI-compatible function calling 定义 ─────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_round_info",
            "description": "获取本轮的基本元信息：round_id、用户意图摘要、时间范围、总体评分、是否异常标记",
            "parameters": {
                "type": "object",
                "properties": {
                    "round_id": {
                        "type": "string",
                        "description": "要查询的 Round ID",
                    }
                },
                "required": ["round_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_selinux_knowledge",
            "description": (
                "检索本地 SELinux 知识库：refpolicy 策略源码（类型声明、布尔值、接口、allow 规则、"
                "文件上下文）、SELinux Notebook 教程、官方 wiki 排错指南。"
                "凡是要解释 SELinux 标签/类型、判断两个类型之间是否存在 allow 规则、"
                "确认布尔值名称与默认值、查某个路径对应的文件上下文，"
                "或者准备给出 SELinux 策略建议之前，都必须先调用本工具核对，"
                "禁止凭记忆输出类型名、布尔名或规则。"
                "返回结果带「文件:行号」出处，可在结论中直接引用。"
                "若上下文的「SELinux 知识参考」段落已经覆盖了要查的内容，则不必重复调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "检索关键词，建议用英文技术术语，多个词用空格分隔。"
                            "例如 'httpd_t var_log_t write'、'apache_read_user_content'、"
                            "'httpd_can_network_connect'、'/etc/httpd'、"
                            "'type_transition'、'AVC denied'。"
                        ),
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["all", "rule", "symbol", "interface", "file_context", "doc"],
                        "description": (
                            "结果类型：all=全部（默认）；rule=allow 等访问规则；"
                            "symbol=类型/布尔值/宏的定义；interface=接口；"
                            "file_context=路径对应的文件上下文；doc=教程与文档。"
                        ),
                    },
                    "module": {
                        "type": "string",
                        "description": "限定 refpolicy 模块名缩小范围，如 apache、container、systemd（可选）",
                    },
                    "k": {
                        "type": "integer",
                        "description": "返回条数，默认 5，最大 10",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_query",
            "description": "获取用户的原始请求意图（本轮 user_query）",
            "parameters": {
                "type": "object",
                "properties": {
                    "round_id": {
                        "type": "string",
                        "description": "要查询的 Round ID",
                    }
                },
                "required": ["round_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ir_policy",
            "description": "获取 IR 权限声明策略（结构化权限声明，含主体/客体/动作/参数约束）",
            "parameters": {
                "type": "object",
                "properties": {
                    "round_id": {
                        "type": "string",
                        "description": "要查询的 Round ID",
                    }
                },
                "required": ["round_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_action_json",
            "description": "获取用户态工具调用记录（Agent 实际调用的工具/函数、参数、访问的资源）",
            "parameters": {
                "type": "object",
                "properties": {
                    "round_id": {
                        "type": "string",
                        "description": "要查询的 Round ID",
                    }
                },
                "required": ["round_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_judge_result",
            "description": "获取用户态异常判定结果（一阶段 judge_result，文本形式）",
            "parameters": {
                "type": "object",
                "properties": {
                    "round_id": {
                        "type": "string",
                        "description": "要查询的 Round ID",
                    }
                },
                "required": ["round_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_kernel_resource_facts",
            "description": "获取内核态资源事实（文件访问/网络访问详情，从内核态采集）",
            "parameters": {
                "type": "object",
                "properties": {
                    "round_id": {
                        "type": "string",
                        "description": "要查询的 Round ID",
                    }
                },
                "required": ["round_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_kernel_judge",
            "description": "获取内核态 LSM Hook 判断结果（Markdown 或 JSON，内核态异常检测结论）",
            "parameters": {
                "type": "object",
                "properties": {
                    "round_id": {
                        "type": "string",
                        "description": "要查询的 Round ID",
                    }
                },
                "required": ["round_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_syscall_judge",
            "description": "获取系统调用分析判断结果（syscall 审计分析，含告警/风险评分）",
            "parameters": {
                "type": "object",
                "properties": {
                    "round_id": {
                        "type": "string",
                        "description": "要查询的 Round ID",
                    }
                },
                "required": ["round_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pid_info",
            "description": "获取进程上下文信息（PID、SELinux/AppArmor 标签、capabilities、namespaces 等）",
            "parameters": {
                "type": "object",
                "properties": {
                    "round_id": {
                        "type": "string",
                        "description": "要查询的 Round ID",
                    }
                },
                "required": ["round_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_previous_llm_analysis",
            "description": "获取之前二阶段大模型自动分析的结果（anomaly_llm_v2_judge_res）",
            "parameters": {
                "type": "object",
                "properties": {
                    "round_id": {
                        "type": "string",
                        "description": "要查询的 Round ID",
                    }
                },
                "required": ["round_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_syscall_sequence",
            "description": "获取内核系统调用序列原始数据（JSONL 格式的 syscall 事件流），数据量可能较大",
            "parameters": {
                "type": "object",
                "properties": {
                    "round_id": {
                        "type": "string",
                        "description": "要查询的 Round ID",
                    }
                },
                "required": ["round_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_kernel_lsm_hook",
            "description": "获取内核 LSM Hook 原始数据（JSONL 格式的 hook 事件流），数据量可能较大",
            "parameters": {
                "type": "object",
                "properties": {
                    "round_id": {
                        "type": "string",
                        "description": "要查询的 Round ID",
                    }
                },
                "required": ["round_id"],
            },
        },
    },
]

# ─── 默认系统提示词（可通过 anomaly_llm_skill_prompt 配置覆盖） ──
DEFAULT_SKILL_SYSTEM_PROMPT = (
    "你叫「小异」，是 ClawAVC 平台的异常分析检测大模型（二阶段），"
    "专门对 AI Agent 的行为进行异常分析检测。\n\n"
    "你可以使用以下工具逐步获取 Round 数据。请根据分析需要，依次调用工具获取所需信息：\n"
    "1. 先获取 round_info 了解基本信息\n"
    "2. 再根据需要获取 user_query、IR 策略、工具调用记录等\n"
    "3. 如有内核数据，可获取 resource_facts、kernel_judge、syscall_judge 等\n\n"
    "当需要解释 SELinux 标签/类型、核对某条 allow 规则是否存在、确认布尔值名称，"
    "或给出 SELinux 策略建议时，必须先调用 search_selinux_knowledge 检索本地知识库，"
    "以检索结果作为依据；禁止凭记忆编造类型名、布尔名、接口名或规则。"
    "策略建议中引用的类型名必须来自检索结果，并标注出处（文件:行号）。\n\n"
    "获取足够信息后，请综合分析该 Agent 行为是否存在越权访问、越界操作、数据外泄、"
    "后门注入、隐蔽提权等异常。\n\n"
    "最终输出格式要求：\n"
    "1. **异常判定**：是否存在异常行为 (是/否)\n"
    "2. **风险等级**：low / medium / high\n"
    "3. **详细分析理由**：分点说明判断依据\n"
    "4. **策略建议**：如果存在异常，给出处置建议（如告警、阻断、降权、审计等），【务必给出selinux策略建议】\n\n"
    "使用工具时，一次调用可以同时请求多个工具（并行），以减少轮次。"
    "获取到足够信息后，用自然语言输出最终分析结果。"
)


# ═══════════════════════════════════════════════════════════════════
# 工具处理函数
# ═══════════════════════════════════════════════════════════════════

def _handler_round_info(round_id: str) -> str:
    """返回本轮基本元信息。"""
    row = db.get_round_by_id(round_id)
    if not row:
        return f"错误：未找到 round_id={round_id}"
    return json.dumps({
        "round_id": row.get("round_id"),
        "user_query": (row.get("user_query") or "")[:200],
        "time_start": row.get("time_start"),
        "time_end": row.get("time_end"),
        "overall_score": row.get("overall_score"),
        "is_abnormal": bool(row.get("is_abnormal")),
    }, ensure_ascii=False)


def _handler_user_query(round_id: str) -> str:
    """返回用户原始请求。"""
    row = db.get_round_by_id(round_id)
    return (row or {}).get("user_query") or "（无用户请求）"


def _handler_ir_policy(round_id: str) -> str:
    """返回 IR 权限声明（精简）。"""
    row = db.get_round_by_id(round_id)
    if not row:
        return "错误：未找到该 round"
    return _simplify_ir_json(row.get("ir_json") or "{}")


def _handler_action_json(round_id: str) -> str:
    """返回用户态工具调用记录（精简）。"""
    row = db.get_round_by_id(round_id)
    if not row:
        return "错误：未找到该 round"
    return _simplify_action_json(row.get("action_json") or "[]")


def _handler_judge_result(round_id: str) -> str:
    """返回用户态异常判定结果。"""
    row = db.get_round_by_id(round_id)
    return (row or {}).get("judge_result") or "（无比对结果）"


def _handler_kernel_resource_facts(round_id: str) -> str:
    """返回内核态资源事实（精简）。"""
    row = db.get_round_by_id(round_id)
    if not row:
        return "错误：未找到该 round"
    raw = row.get("kernel_resource_facts") or ""
    if not raw:
        return "（无内核资源事实数据）"
    return _simplify_resource_facts(raw)


def _handler_kernel_judge(round_id: str) -> str:
    """返回内核态 LSM Hook 判断结果（精简）。"""
    row = db.get_round_by_id(round_id)
    if not row:
        return "错误：未找到该 round"
    path = row.get("judge_result_kernel") or ""
    return _simplify_kernel_judge_from_path(path) or "（无内核 LSM Hook 判断结果）"


def _handler_syscall_judge(round_id: str) -> str:
    """返回系统调用分析判断结果（精简）。"""
    row = db.get_round_by_id(round_id)
    if not row:
        return "错误：未找到该 round"
    raw = row.get("syscall_judge") or ""
    if not raw:
        return "（无系统调用分析数据）"
    return _simplify_syscall_judge(raw)


def _handler_pid_info(round_id: str) -> str:
    """返回进程上下文信息摘要。"""
    row = db.get_round_by_id(round_id)
    if not row:
        return "错误：未找到该 round"
    raw = row.get("pid_info") or ""
    if not raw:
        return "（无进程上下文信息）"
    obj, ok = _try_json(raw)
    if ok and isinstance(obj, dict):
        summary = {
            "pid": obj.get("main", {}).get("pid"),
            "comm": obj.get("main", {}).get("comm"),
            "selinux_label": obj.get("main_selinux_label"),
            "discovery_method": obj.get("discovery", {}).get("method"),
            "tool_subprocess_count": len(obj.get("tool_subprocess_labels") or []),
        }
        return json.dumps(summary, ensure_ascii=False)
    return raw


def _handler_previous_llm_analysis(round_id: str) -> str:
    """返回此前二阶段大模型自动分析结果。"""
    row = db.get_round_by_id(round_id)
    raw = (row or {}).get("anomaly_llm_v2_judge_res") or ""
    if not raw:
        return "（无此前自动分析结果）"
    obj, ok = _try_json(raw)
    if ok and isinstance(obj, dict):
        return json.dumps(obj, ensure_ascii=False)
    return raw


def _handler_syscall_sequence(round_id: str) -> str:
    """返回内核 syscall 序列文件的前 200 行。"""
    row = db.get_round_by_id(round_id)
    path = (row or {}).get("kernel_syscall_seq") or ""
    if not path:
        return "（无内核系统调用序列数据）"
    text = _read_file_text(path)
    if text is None:
        return f"（无法读取序列文件：{path}）"
    lines = text.strip().splitlines()
    if len(lines) > 200:
        return "\n".join(lines[:200]) + f"\n\n...（共 {len(lines)} 行，仅显示前 200 行）"
    return text


def _handler_kernel_lsm_hook(round_id: str) -> str:
    """返回内核 LSM Hook 文件的前 200 行。"""
    row = db.get_round_by_id(round_id)
    path = (row or {}).get("kernel_lsm_hook_result") or ""
    if not path:
        return "（无内核 LSM Hook 原始数据）"
    text = _read_file_text(path)
    if text is None:
        return f"（无法读取 LSM Hook 文件：{path}）"
    lines = text.strip().splitlines()
    if len(lines) > 200:
        return "\n".join(lines[:200]) + f"\n\n...（共 {len(lines)} 行，仅显示前 200 行）"
    return text


# ─── SELinux 知识库检索（依赖 backend/selinux_kb/，索引缺失时降级为提示信息） ───

_KB_IMPORT_ERROR: Any = None


def _load_kb_search():
    """延迟导入 selinux_kb.search。

    放在函数内导入，避免索引文件缺失或目录未拷贝时影响 xy_skill 的模块加载。
    """
    global _KB_IMPORT_ERROR
    try:
        from selinux_kb import search as kb_search
        return kb_search
    except Exception as exc:  # 首次导入失败时补齐 sys.path 再试一次
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)
        try:
            from selinux_kb import search as kb_search
            return kb_search
        except Exception as exc2:
            _KB_IMPORT_ERROR = exc2
            return None


def _load_kb_prefetch():
    """延迟导入 selinux_kb.prefetch（预取失败不应该影响技能分析主流程）。"""
    try:
        from selinux_kb import prefetch as kb_prefetch
        return kb_prefetch
    except Exception:
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)
        try:
            from selinux_kb import prefetch as kb_prefetch
            return kb_prefetch
        except Exception:
            return None


def _handler_selinux_knowledge(round_id: str, query: str = "", kind: str = "all",
                               module: str = "", k: int = 5) -> str:
    """检索本地 SELinux 知识库（refpolicy 源码 / SELinux Notebook / 官方 wiki）。

    与其它工具不同，本工具不使用 round_id，而是按 query 检索静态知识库，
    为「策略建议」提供可引用、可核查的依据。
    """
    query = str(query or "").strip()
    if not query:
        return (
            "错误：query 不能为空。请传入要查证的关键词，例如 "
            '{"query": "httpd_t var_log_t write"} 或 {"query": "httpd_can_network_connect"}；'
            "也可用 kind 指定 rule / symbol / interface / file_context / doc。"
        )
    try:
        k = int(k)
    except (TypeError, ValueError):
        k = 5
    k = max(1, min(k, 10))
    kind = str(kind or "all").strip().lower() or "all"
    module = str(module or "").strip()

    kb_search = _load_kb_search()
    if kb_search is None:
        return ("SELinux 知识库不可用（导入失败：%s）。请确认 backend/selinux_kb/ 已随代码一起拷贝，"
                "且 infos/selinux_kb/selinux_kb.db 已生成。" % _KB_IMPORT_ERROR)
    try:
        return kb_search.search(query, kind=kind, module=module or None, k=k)
    except Exception as exc:
        return "SELinux 知识库检索失败：%s" % exc


# 参数类工具的合法入参名，多余字段会被忽略
_ARG_TOOL_KEYS = {"query", "kind", "module", "k"}


def _call_tool_handler(func_name: str, round_id: str, arguments_json: str) -> str:
    """分发工具调用。

    Round 类工具只需要 round_id；ARG_TOOLS 里的工具需要解析 JSON 参数后再调用。
    """
    handler = TOOL_HANDLERS.get(func_name)
    if handler is None:
        return f"错误：未知工具 '{func_name}'"
    if func_name not in ARG_TOOLS:
        return handler(round_id)
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except Exception:
        return ('错误：工具参数不是合法 JSON。请重新调用，例如 '
                '{"query": "httpd_t var_log_t", "kind": "rule"}')
    if not isinstance(args, dict):
        return "错误：工具参数必须是 JSON 对象。"
    kwargs = {k: v for k, v in args.items() if k in _ARG_TOOL_KEYS and v not in (None, "")}
    try:
        return handler(round_id, **kwargs)
    except TypeError as exc:
        return "错误：工具参数不正确（%s）" % exc


# 工具名 → 处理函数 registry
TOOL_HANDLERS: Dict[str, Any] = {
    "get_round_info": _handler_round_info,
    "get_user_query": _handler_user_query,
    "get_ir_policy": _handler_ir_policy,
    "get_action_json": _handler_action_json,
    "get_judge_result": _handler_judge_result,
    "get_kernel_resource_facts": _handler_kernel_resource_facts,
    "get_kernel_judge": _handler_kernel_judge,
    "get_syscall_judge": _handler_syscall_judge,
    "get_pid_info": _handler_pid_info,
    "get_previous_llm_analysis": _handler_previous_llm_analysis,
    "get_syscall_sequence": _handler_syscall_sequence,
    "get_kernel_lsm_hook": _handler_kernel_lsm_hook,
    "search_selinux_knowledge": _handler_selinux_knowledge,
}


# ═══════════════════════════════════════════════════════════════════
# LLM 调用辅助
# ═══════════════════════════════════════════════════════════════════

# ─── 上下文预算控制 ────────────────────────────────────────────────
# vLLM 在「prompt token 数 + max_tokens > max_model_len」时会直接返回 400，
# 而本模块会把整轮审计数据（syscall 序列、LSM hook、工具返回）累积进上下文，
# 因此每次调用前都必须先按预算裁剪，否则必然触发 400。

LLM_ERROR_PREFIX = "[LLM 请求异常]"

DEFAULT_MAX_CONTEXT = 8192        # 探测失败时的保守默认值（token）
CONTEXT_SAFETY_MARGIN = 512       # 预留给 chat 模板与特殊 token
_COMPRESS_INPUT_MAX = 8000        # 送去压缩的原文上限（字符）
_MODEL_MAX_CONTEXT: Dict[str, int] = {}   # url -> max_model_len，进程内缓存


def _cfg_int(key: str, default: int) -> int:
    """读取整数配置项，缺失或非法时返回默认值。"""
    try:
        raw = (db.get_config(key) or "").strip()
        val = int(raw)
        return val if val > 0 else default
    except Exception:
        return default


def _detect_max_context(llm_url: str) -> int:
    """探测 vLLM 的 max_model_len（GET /v1/models），失败时返回保守默认值。"""
    try:
        base = llm_url.rstrip("/")
        for suffix in ("/v1/chat/completions", "/chat/completions", "/v1", "/completions"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        resp = http_requests.get(base.rstrip("/") + "/v1/models", timeout=5)
        if resp.status_code < 400:
            data = resp.json()
            items = data.get("data") if isinstance(data, dict) else None
            if isinstance(items, list):
                for item in items:
                    val = item.get("max_model_len") if isinstance(item, dict) else None
                    if isinstance(val, int) and val > 1024:
                        return val
    except Exception:
        pass
    return DEFAULT_MAX_CONTEXT


def _get_max_context(llm_url: str) -> int:
    """模型上下文上限：优先取配置，其次探测并缓存。"""
    configured = _cfg_int("monitor_conf.anomaly_llm_max_context", 0)
    if configured:
        return configured
    if llm_url not in _MODEL_MAX_CONTEXT:
        _MODEL_MAX_CONTEXT[llm_url] = _detect_max_context(llm_url)
    return _MODEL_MAX_CONTEXT[llm_url]


def _llm_model_field() -> Optional[str]:
    """请求体里的 model 字段。

    默认不发送——若目标 vLLM 不校验该字段，保持现状最稳妥；
    当服务要求 model 且为空会返回 400 时，配置
    monitor_conf.anomaly_llm_model 填成 /v1/models 返回的 id 即可。
    """
    try:
        val = (db.get_config("monitor_conf.anomaly_llm_model") or "").strip()
    except Exception:
        return None
    return val or None


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数：CJK 约 1 字 1 token，其余约 3.5 字符 1 token。"""
    if not text:
        return 0
    cjk = 0
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f":
            cjk += 1
    return cjk + int((len(text) - cjk) / 3.5) + 1


def _messages_tokens(messages: list) -> int:
    total = 0
    for msg in messages:
        total += _estimate_tokens(msg.get("content") or "")
        for tc in (msg.get("tool_calls") or []):
            fn = tc.get("function") or {}
            total += _estimate_tokens(fn.get("arguments") or "") + 8
        total += 8          # 每条消息的角色分隔开销
    return total


def _clamp_max_tokens(llm_url: str, max_tokens: int) -> int:
    """输出上限不能超过「上下文上限 - 预留输入空间」，否则 vLLM 直接 400。"""
    limit = max(512, _get_max_context(llm_url) - 1536)
    try:
        max_tokens = int(max_tokens)
    except (TypeError, ValueError):
        max_tokens = DEFAULT_MAX_TOKENS
    return max(256, min(max_tokens, limit))


def _shrink_messages(messages: list, llm_url: str, max_tokens: int) -> list:
    """按上下文预算裁剪消息历史。

    保留 system 提示与最后一条 user 消息，优先截断最长的历史消息
    （通常是体积巨大的工具返回），避免整轮分析因超上下文而失败。
    """
    max_ctx = _get_max_context(llm_url)
    budget = max_ctx - max_tokens - CONTEXT_SAFETY_MARGIN
    if budget < 1024:
        budget = max(512, max_ctx // 2)

    out = [dict(m) for m in messages]
    total = _messages_tokens(out)
    if total <= budget:
        return out

    protected = {0}                                   # 首条 system 始终保留
    for i in range(len(out) - 1, -1, -1):             # 最后一条 user 始终保留
        if out[i].get("role") == "user":
            protected.add(i)
            break

    excess_chars = int((total - budget) * 3.5) + 200
    order = sorted((i for i in range(len(out)) if i not in protected),
                   key=lambda i: -len(out[i].get("content") or ""))
    for i in order:
        if excess_chars <= 0:
            break
        content = out[i].get("content") or ""
        if len(content) <= 600:
            continue
        keep = max(400, len(content) - excess_chars)
        removed = len(content) - keep
        out[i]["content"] = content[:keep] + "\n…（上下文超限，已截断 %d 字符）" % removed
        excess_chars -= removed
    return out


def _call_llm_with_tools(
    url: str,
    messages: list,
    tools: list,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> Dict[str, Any]:
    """非流式 LLM 调用（含 tools 参数），返回完整响应。"""
    max_tokens = _clamp_max_tokens(url, max_tokens)
    payload = {
        "temperature": 0.3,
        "messages": _shrink_messages(messages, url, max_tokens),
        "tools": tools,
        "tool_choice": "auto",
        "max_tokens": max_tokens,
    }
    _model = _llm_model_field()
    if _model:
        payload["model"] = _model
    headers = {"Content-Type": "application/json"}
    resp = http_requests.post(url, headers=headers, json=payload, timeout=120)
    if resp.status_code >= 400:
        raise RuntimeError(f"LLM HTTP {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def _call_llm_stream(
    url: str,
    messages: list,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> Generator[str, None, None]:
    """流式 LLM 调用（无 tools），逐个 yield 文本块。"""
    max_tokens = _clamp_max_tokens(url, max_tokens)
    payload = {
        "temperature": 0.3,
        "messages": _shrink_messages(messages, url, max_tokens),
        "stream": True,
        "max_tokens": max_tokens,
    }
    _model = _llm_model_field()
    if _model:
        payload["model"] = _model
    headers = {"Content-Type": "application/json"}
    resp = http_requests.post(url, headers=headers, json=payload, stream=True, timeout=180)
    if resp.status_code >= 400:
        # 必须带上响应体：vLLM 的报错正文会直接说明原因
        # （上下文超限 / 模型名不存在 / 未开启 tool calling 等）
        body = (resp.text or "").replace("\n", " ")[:400]
        yield f"{LLM_ERROR_PREFIX} HTTP {resp.status_code}: {body}"
        return
    for raw in resp.iter_lines(decode_unicode=True):
        if not raw:
            continue
        line = raw.strip()
        if not line.startswith("data:"):
            continue
        data_str = line[len("data:"):].strip()
        if data_str == "[DONE]":
            break
        try:
            chunk = json.loads(data_str)
        except Exception:
            continue
        try:
            delta = chunk["choices"][0]["delta"]
            text = delta.get("content") or ""
        except Exception:
            text = ""
        if text:
            yield text


def _stream_llm_with_tools(
    url: str,
    messages: list,
    tools: list,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> Generator[tuple, None, None]:
    """流式 LLM 调用（含 tools）。

    边接收边解析，逐个 yield 事件，让工具调用可以实时呈现：
      ("content", text_chunk)     — 模型输出的文本增量（最终分析 / 思考）
      ("tool_start", idx, slot)   — 首次确定某个工具调用的名称，可立即执行
      ("final", {content, tool_calls, indices})
                                  — 流结束，返回完整文本与组装好的 tool_calls
    """
    max_tokens = _clamp_max_tokens(url, max_tokens)
    payload = {
        "temperature": 0.3,
        "messages": _shrink_messages(messages, url, max_tokens),
        "tools": tools,
        "tool_choice": "auto",
        "stream": True,
        "max_tokens": max_tokens,
    }
    _model = _llm_model_field()
    if _model:
        payload["model"] = _model
    headers = {"Content-Type": "application/json"}
    resp = http_requests.post(url, headers=headers, json=payload, stream=True, timeout=180)
    if resp.status_code >= 400:
        raise RuntimeError(f"LLM HTTP {resp.status_code}: {resp.text[:500]}")

    content_parts: list[str] = []
    tool_map: Dict[int, Dict[str, Any]] = {}   # index -> {id, name, arguments}
    started_indices: set[int] = set()

    for raw in resp.iter_lines(decode_unicode=True):
        if not raw:
            continue
        line = raw.strip()
        if not line.startswith("data:"):
            continue
        data_str = line[len("data:"):].strip()
        if data_str == "[DONE]":
            break
        try:
            chunk = json.loads(data_str)
        except Exception:
            continue
        try:
            delta = chunk["choices"][0]["delta"]
        except Exception:
            continue

        # 文本增量
        text = delta.get("content") or ""
        if text:
            content_parts.append(text)
            yield ("content", text)

        # 工具调用增量（OpenAI 协议：分片传输，按 index 累积）
        for tcd in (delta.get("tool_calls") or []):
            idx = tcd.get("index", 0)
            slot = tool_map.setdefault(idx, {"id": None, "name": None, "arguments": ""})
            if tcd.get("id"):
                slot["id"] = tcd["id"]
            fn = tcd.get("function") or {}
            if fn.get("name"):
                slot["name"] = fn["name"]
            if fn.get("arguments"):
                slot["arguments"] += fn["arguments"]
            # 名称一旦确定且未通知过 → 立即让调用方执行（handler 只需 round_id，不依赖 arguments）
            if slot["name"] and idx not in started_indices:
                started_indices.add(idx)
                yield ("tool_start", idx, slot)

    # 组装最终 tool_calls（按 index 排序，补全 id）
    tool_calls: list = []
    indices: list = []
    for idx in sorted(tool_map.keys()):
        slot = tool_map[idx]
        if not slot["name"]:
            continue
        tool_calls.append({
            "id": slot["id"] or f"call_{idx}",
            "type": "function",
            "function": {
                "name": slot["name"],
                "arguments": slot["arguments"] or "{}",
            },
        })
        indices.append(idx)
    yield ("final", {
        "content": "".join(content_parts),
        "tool_calls": tool_calls,
        "indices": indices,
    })


# ═══════════════════════════════════════════════════════════════════
# 核心编排器
# ═══════════════════════════════════════════════════════════════════

def _get_skill_system_prompt() -> str:
    """从 DB 读取自定义 skill 提示词，未配置则用默认值。

    无论用户是否自定义提示词，都会追加 SELinux 依据约束（见 prefetch.DIRECTIVE），
    避免自定义提示词把「先查证再给建议」的要求覆盖掉。
    """
    custom = (db.get_config("monitor_conf.anomaly_llm_skill_prompt") or "").strip()
    base = custom if custom else DEFAULT_SKILL_SYSTEM_PROMPT
    prefetch = _load_kb_prefetch()
    if prefetch is None:
        return base
    try:
        return prefetch.extend_skill_prompt(base)
    except Exception:
        return base


# ─── 工具结果压缩开关 ──────────────────────────────────────────
# 工具返回数据过长时的处理策略：
#   - 开关开启 (monitor_conf.anomaly_llm_tool_compress=true) → 调用大模型压缩
#   - 开关关闭 → 直接截断到阈值长度
# 阈值: monitor_conf.anomaly_llm_tool_compress_max (字符数, 默认 2000)
def _get_tool_compress_switch() -> bool:
    return (db.get_config("monitor_conf.anomaly_llm_tool_compress") or "").strip().lower() == "true"


def _get_tool_compress_max() -> int:
    try:
        v = int((db.get_config("monitor_conf.anomaly_llm_tool_compress_max") or "").strip() or 2000)
    except (ValueError, TypeError):
        v = 2000
    return v if v > 0 else 2000


_COMPRESS_SYSTEM_PROMPT = (
    "你是一个信息压缩助手。用户会提供一段较长的工具返回数据，"
    "请在不丢失关键事实（数值、路径、PID、判定结论、风险等级、异常点）的前提下，"
    "尽量精简地用中文总结该数据，保留原始关键字段与结论。"
    "直接输出压缩后的内容，不要额外解释或评价。"
)


def _compress_tool_result(text: str, llm_url: str, max_tokens: int) -> str:
    """调用 LLM 压缩过长的工具返回结果；失败时返回空串（由调用方兜底截断）。

    注意两点：
      1. 送给压缩模型的原文也要限长——为了压缩而把原文整段发过去，
         同样会撑爆上下文，反而制造出新的 400。
      2. 必须识别出错误标记：否则 "[LLM 请求异常] ..." 会被当成压缩结果，
         再作为「工具返回」喂回模型，污染整轮分析。
    """
    payload_text = text
    if len(payload_text) > _COMPRESS_INPUT_MAX:
        payload_text = (payload_text[:_COMPRESS_INPUT_MAX]
                        + "\n…（原文共 %d 字符，此处仅取前 %d 字符）"
                        % (len(text), _COMPRESS_INPUT_MAX))
    messages = [
        {"role": "system", "content": _COMPRESS_SYSTEM_PROMPT},
        {"role": "user", "content": f"待压缩内容如下：\n\n{payload_text}"},
    ]
    chunks = []
    try:
        for chunk in _call_llm_stream(llm_url, messages, max_tokens):
            chunks.append(chunk)
    except Exception:
        return ""
    compressed = "".join(chunks).strip()
    if not compressed or LLM_ERROR_PREFIX in compressed:
        return ""
    return compressed


def _process_tool_result(result_text: str, llm_url: str, max_tokens: int):
    """根据压缩开关处理过长工具结果，返回 (处理后文本, 是否经大模型压缩)。"""
    threshold = _get_tool_compress_max()
    if len(result_text) <= threshold:
        return result_text, False
    fallback = (result_text[:threshold]
                + "\n\n...（结果过长，已截断至 %d 字符）" % threshold)
    if _get_tool_compress_switch() and llm_url:
        compressed = _compress_tool_result(result_text, llm_url, max_tokens)
        if compressed:
            return compressed, True
        return fallback, False      # 压缩失败 → 退回截断，绝不把错误信息当结果
    # 开关关闭：直接截断到阈值长度
    return fallback, False


def run_skill_analysis(
    round_id: str,
    llm_url: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> Generator[Dict[str, Any], None, None]:
    """
    技能分析编排器 —— generator 产出 SSE-compatible 事件字典。

    Event types:
        {"type": "tool_call", "name": "...", "status": "started|completed|error", "result": "..."}
        {"type": "text", "content": "..."}
        {"type": "text_done", "content": "..."}
        {"type": "done"}
        {"type": "error", "message": "..."}
        {"type": "tool_limit_reached", "message": "..."}
    """
    # 1. 验证 round 存在
    row = db.get_round_by_id(round_id)
    if not row:
        yield {"type": "error", "message": f"未找到 round_id={round_id}"}
        return

    # 2. 构造初始消息
    system_prompt = _get_skill_system_prompt()

    # 回答前自动检索 SELinux 知识：把依据直接放进上下文，
    # 不依赖模型是否主动调用 search_selinux_knowledge
    user_content = (
        f"请对 Round {round_id} 进行全面的异常行为分析。\n\n"
        f"你可以使用上述工具逐步获取所需数据。\n"
        f"获取足够信息后，请给出：\n"
        f"1. 异常判定（是/否）\n"
        f"2. 风险等级（low/medium/high）\n"
        f"3. 详细分析理由\n"
        f"4. 策略建议"
    )
    prefetch = _load_kb_prefetch()
    if prefetch is not None:
        try:
            kb_block = prefetch.block_for_round(row)
        except Exception:
            kb_block = ""
        if kb_block:
            user_content += "\n\n" + kb_block

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    # 3. 工具调用循环
    tool_round = 0
    while tool_round < MAX_TOOL_ROUNDS:
        tool_round += 1

        # 3a. 流式请求 LLM（含 tools）——边接收边执行工具，实时呈现
        content_final = ""
        tool_calls_final: list = []
        indices_final: list = []
        results_by_idx: Dict[int, str] = {}   # 原始 index -> 工具返回文本

        def _run_tool(func_name: str, arguments: str = "{}"):
            """执行单个工具，yield SSE 事件，返回追加到 messages 的结果文本。

            Round 类工具在 tool_start 阶段（只拿到函数名）即可执行；
            ARG_TOOLS 里的参数类工具必须等 arguments 完整接收后再调用。
            """
            yield {"type": "tool_call", "name": func_name, "status": "started"}
            handler = TOOL_HANDLERS.get(func_name)
            if handler is None:
                rt = f"错误：未知工具 '{func_name}'"
                yield {"type": "tool_call", "name": func_name, "status": "error", "result": rt}
                yield ("__result__", rt)
                return
            try:
                raw_text = _call_tool_handler(func_name, round_id, arguments)
                processed_text, was_compressed = _process_tool_result(raw_text, llm_url, max_tokens)
                preview = processed_text
                if len(preview) > 1000:
                    preview = preview[:1000] + "\n\n...（结果过长，已截断显示）"
                if was_compressed:
                    preview += "\n\n[已调用大模型对过长工具结果进行压缩]"
                yield {"type": "tool_call", "name": func_name, "status": "completed", "result": preview}
                yield ("__result__", processed_text)
            except Exception as e:
                rt = f"工具执行异常: {e}"
                yield {"type": "tool_call", "name": func_name, "status": "error", "result": rt}
                yield ("__result__", rt)

        try:
            for ev in _stream_llm_with_tools(llm_url, messages, TOOLS, max_tokens):
                kind = ev[0]
                if kind == "content":
                    # 模型边思考/边输出文本 → 实时转发（若本轮最终无工具，则为最终分析）
                    yield {"type": "text", "content": ev[1]}
                elif kind == "tool_start":
                    idx, slot = ev[1], ev[2]
                    func_name = slot["name"]
                    if func_name in ARG_TOOLS:
                        # 参数仍在流式接收中，推迟到 final 事件（arguments 完整后）再执行
                        continue
                    result_text = ""
                    for item in _run_tool(func_name):
                        if isinstance(item, tuple) and item[0] == "__result__":
                            result_text = item[1]
                        else:
                            yield item
                    results_by_idx[idx] = result_text
                elif kind == "final":
                    content_final = ev[1]["content"]
                    tool_calls_final = ev[1]["tool_calls"]
                    indices_final = ev[1]["indices"]
                    # arguments 已接收完整，执行参数类工具
                    for i, tc in enumerate(tool_calls_final):
                        fname = (tc.get("function") or {}).get("name")
                        if fname not in ARG_TOOLS:
                            continue
                        args_json = (tc.get("function") or {}).get("arguments") or "{}"
                        result_text = ""
                        for item in _run_tool(fname, args_json):
                            if isinstance(item, tuple) and item[0] == "__result__":
                                result_text = item[1]
                            else:
                                yield item
                        results_by_idx[indices_final[i]] = result_text
        except Exception as e:
            yield {"type": "error", "message": f"LLM 调用失败（第 {tool_round} 轮）: {e}"}
            return

        # 3b. 本轮无工具调用 → 即为最终分析，结束循环
        if not tool_calls_final:
            if not content_final:
                yield {"type": "error", "message": "LLM 未返回任何内容"}
                return
            messages.append({"role": "assistant", "content": content_final})
            yield {"type": "text_done", "content": content_final}
            break

        # 3c. 组装 assistant 的 tool_calls 消息
        messages.append({
            "role": "assistant",
            "content": content_final,
            "tool_calls": tool_calls_final,
        })

        # 3d. 按顺序追加各工具响应（已在流中实时执行）
        for i, tc in enumerate(tool_calls_final):
            orig_idx = indices_final[i]
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": results_by_idx.get(orig_idx, "（工具无返回）"),
            })

    # 4. 达到最大轮次 → 强制生成最终分析（流式）
    if tool_round >= MAX_TOOL_ROUNDS:
        yield {
            "type": "tool_limit_reached",
            "message": f"已达到最大工具调用轮次（{MAX_TOOL_ROUNDS}），基于已有信息生成最终分析",
        }
        messages.append({
            "role": "user",
            "content": (
                f"你已经达到最大工具调用轮次（{MAX_TOOL_ROUNDS}）。"
                "请基于已有信息生成最终分析结论，不要再调用任何工具。"
                "要求包含异常判定、风险等级、详细分析理由和策略建议。"
            ),
        })
        final_chunks: list[str] = []
        for chunk in _call_llm_stream(llm_url, messages, max_tokens):
            yield {"type": "text", "content": chunk}
            final_chunks.append(chunk)
        yield {"type": "text_done", "content": "".join(final_chunks)}

    # 5. 完成
    yield {"type": "done"}
