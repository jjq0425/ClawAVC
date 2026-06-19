"""
ClawAVC API Documentation Generator.

All API metadata is defined in ENDPOINT_REGISTRY below.
generate_docs() auto-discovers Flask routes and merges with registry metadata.
"""

from __future__ import annotations
import functools
import json
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════
# API Metadata Registry — edit here to update docs automatically
# ═══════════════════════════════════════════════════════════════

# ⚠️ 重要说明：Round 推送时序
# ---------------------------------------------------------------
# 1. round_start 必须是第一个推送的阶段，表示 Round 的开始
# 2. round_ir_ready、round_end、round_kernel 这三个阶段的处理是异步的
# 3. 由于异步处理，这三个阶段的实际推送顺序可能不固定，取决于各模块的处理速度
# 4. 前端应根据 push_type 进行状态更新，而不是依赖推送的时间顺序
# ---------------------------------------------------------------

ENDPOINT_REGISTRY = {
    "GET /api/rounds": {
        "summary": "分页查询 Rounds",
        "description": "支持多条件筛选的分页查询，返回审计轮次列表和总数。",
        "category": "数据查询与更新",
        "params": [
            {"name": "limit", "type": "int", "default": "20", "desc": "每页条数"},
            {"name": "offset", "type": "int", "default": "0", "desc": "偏移量"},
            {"name": "query", "type": "string", "default": "", "desc": "模糊搜索 user_query"},
            {"name": "round_id", "type": "string", "default": "", "desc": "模糊搜索 round_id"},
            {"name": "time_from", "type": "string", "default": "", "desc": "开始时间 (YYYY-MM-DD HH:MM:SS)"},
            {"name": "time_to", "type": "string", "default": "", "desc": "结束时间"},
            {"name": "abnormal", "type": "string", "default": "false", "desc": "仅显示异常 (true/false)"},
        ],
        "response": {"ok": True, "data": [{"round_id": "abc123", "user_query": "...", "overall_score": 0.85}], "total": 100},
        "public": True,
    },
    "GET /api/rounds/query": {
        "summary": "获取单条 Round 详情",
        "description": "根据 round_id 获取完整的审计轮次数据，包括 action、IR、judge 结果。",
        "category": "数据查询与更新",
        "params": [{"name": "round_id", "type": "query", "desc": "Round ID"}],
        "response": {"ok": True, "data": {"round_id": "abc123", "user_query": "...", "action_json": "[]", "ir_json": "{}", "judge_result": "...", "overall_score": 0.85}},
        "public": True,
    },
    "PUT /api/rounds/update": {
        "summary": "更新 Round 字段",
        "description": "更新指定 round 的单个字段值。仅支持部分字段（创建 15 分钟内），字段名称可前往「数据运维」页面查看 rounds 表结构。超过 15 分钟的数据请前往数据运维页面修改。",
        "category": "数据查询与更新",
        "params": [
            {"name": "round_id", "type": "body", "desc": "Round ID"},
            {"name": "field", "type": "body", "desc": "要更新的字段名"},
            {"name": "value", "type": "body", "desc": "字段值（字符串）"},
        ],
        "response": {"ok": True},
        "public": True,
    },
    "POST /api/rounds": {
        "summary": "上报 Round 数据",
        "description": "Monitor/Orchestrator 上报审计轮次数据。支持 event=start (创建) 和 event=end (更新)。",
        "category": "数据查询与更新",
        "params": [
            {"name": "event", "type": "string", "default": "end", "desc": "事件类型: start 或 end"},
            {"name": "round_id", "type": "string", "desc": "Round ID"},
            {"name": "user_query", "type": "string", "desc": "用户查询"},
            {"name": "action_json", "type": "string", "desc": "行为 JSON"},
            {"name": "ir_json", "type": "string", "desc": "IR 策略 JSON"},
            {"name": "judge_result", "type": "string", "desc": "判定结果文本"},
            {"name": "overall_score", "type": "float", "desc": "综合得分 (0~1)"},
        ],
        "response": {"ok": True},
        "public": True,
    },
    "POST /api/rounds/kernel": {
        "summary": "内核态信息上报",
        "description": "上报内核态信息（系统调用序列、LSM hook结果、资源事实）。支持15分钟时间限制（受平台管理开关控制）。成功后通过 WebSocket 推送 round_kernel 阶段。",
        "category": "数据查询与更新",
        "params": [
            {"name": "round_id", "type": "string", "desc": "Round ID"},
            {"name": "kernel_syscall_seq_path", "type": "string", "desc": "内核态系统调用序列文件路径 (JSONL格式)"},
            {"name": "kernel_lsm_hook_result_path", "type": "string", "desc": "内核态LSM hook检查结果文件路径 (JSONL格式)"},
            {"name": "kernel_resource_facts_path", "type": "string", "desc": "内核资源事实信息文件路径"},
        ],
        "response": {"ok": True},
        "public": True,
    },
    "POST /api/rounds/detection/kernel": {
        "summary": "内核态LSM Hook判断结果上报",
        "description": "上报内核态LSM Hook的判断结果 Markdown 文件路径。文件会被复制到 infos/kernel_judge 目录，然后将绝对路径存入数据库。支持15分钟时间限制（受平台管理开关控制）。",
        "category": "数据查询与更新",
        "params": [
            {"name": "round_id", "type": "string", "desc": "Round ID"},
            {"name": "judge_result_kernel_md_path", "type": "string", "desc": "内核态判断结果 Markdown 文件路径"},
        ],
        "response": {"ok": True},
        "public": True,
    },
    "POST /api/rounds/detection/syscall": {
        "summary": "系统调用判断结果上报",
        "description": "上报系统调用的判断结果。支持多种 JSON 格式输入（标准JSON、带转义的字符串、压缩格式、格式化格式），后端会自动解析并压缩存储。支持15分钟时间限制（受平台管理开关控制）。",
        "category": "数据查询与更新",
        "params": [
            {"name": "round_id", "type": "string", "desc": "Round ID"},
            {"name": "syscall_judge", "type": "string", "desc": "系统调用判断结果 JSON 数据（支持各种格式）"},
        ],
        "response": {"ok": True},
        "public": True,
    },
    "GET /api/stats": {
        "summary": "统计概览",
        "description": "获取系统整体统计数据：总 Round 数、异常数、合规数、平均得分。",
        "category": "数据查询与更新",
        "response": {"ok": True, "data": {"total": 50, "abnormal": 5, "normal": 45, "avg_score": 0.82}},
        "public": True,
    },
    "POST /api/auth": {
        "summary": "入门口令验证",
        "description": "验证平台访问口令，通过后返回 token 用于后续请求。",
        "category": "鉴权管理",
        "params": [{"name": "key", "type": "string", "desc": "访问口令 (body JSON)"}],
        "response": {"ok": True, "token": "..."},
        "public": True,
    },
    "POST /api/admin/verify": {
        "summary": "特权验证",
        "description": "验证特权密钥，返回 20 分钟有效的 session token。",
        "category": "鉴权管理",
        "params": [{"name": "key", "type": "string", "desc": "特权密钥 (body JSON)"}],
        "response": {"ok": True, "session": "token...", "ttl_minutes": 20},
        "public": False,
    },
    "GET /api/admin/session": {
        "summary": "检查特权会话",
        "description": "检查当前 admin session token 是否仍然有效。",
        "category": "鉴权管理",
        "params": [{"name": "X-Admin-Session", "type": "header", "desc": "session token"}],
        "response": {"ok": True, "valid": True, "remaining_seconds": 1200},
        "public": False,
    },
    "GET /api/monitor/config": {
        "summary": "获取监控配置",
        "description": "获取当前监控数据源配置（网关日志路径、OpenClaw 根文件夹）及路径有效性。",
        "category": "运行监控",
        "response": {"ok": True, "data": {"gateway_log_path": "/path/to/logs", "openclaw_root": "/root/.openclaw", "_path_status": {"gateway_log_path": "ok"}}},
        "public": True,
    },
    "PUT /api/monitor/config": {
        "summary": "保存监控配置",
        "description": "逐项保存监控配置。保存后自动检测路径有效性。",
        "category": "运行监控",
        "params": [
            {"name": "key", "type": "string", "desc": "配置键: gateway_log_path 或 openclaw_root"},
            {"name": "value", "type": "string", "desc": "配置值（绝对路径）"},
        ],
        "response": {"ok": True, "data": {"path_valid": True}},
        "public": True,
    },
    "GET /api/monitor/status": {
        "summary": "监控运行状态",
        "description": "检查内置监控引擎是否正在运行。",
        "category": "运行监控",
        "response": {"ok": True, "data": {"running": True}},
        "public": True,
    },
    "POST /api/monitor/start": {
        "summary": "启动安全监控",
        "description": "启动内置监控引擎。需先配置网关日志路径和 OpenClaw 根文件夹，否则返回错误。",
        "category": "运行监控",
        "response": {"ok": True, "message": "监控已启动"},
        "public": True,
    },
    "POST /api/monitor/stop": {
        "summary": "停止安全监控",
        "description": "停止内置监控引擎。",
        "category": "运行监控",
        "response": {"ok": True, "message": "监控已停止"},
        "public": True,
    },
    "POST /api/translator/translate": {
        "summary": "IR 翻译",
        "description": "将用户自然语言意图翻译为结构化权限策略 (IR)。两阶段 LLM 管线：Level-1 场景分类 + Level-2 策略生成。",
        "category": "策略翻译",
        "params": [
            {"name": "query", "type": "string", "desc": "用户查询文本 (body JSON)"},
            {"name": "round_id", "type": "string", "default": "", "desc": "关联的 round_id"},
        ],
        "response": {"ok": True, "data": {"level1": ["file_ops"], "level2": {"policies": [{"subject": "file_ops", "objects": [], "effect": "allow"}]}}},
        "public": True,
    },
    "POST /api/translator/test": {
        "summary": "翻译测试（UI）",
        "description": "前端翻译测试入口，标记为 UI 测试不影响正式日志。",
        "category": "策略翻译",
        "params": [{"name": "query", "type": "string", "desc": "用户查询文本 (body JSON)"}],
        "response": {"ok": True, "data": {"level1": ["..."], "level2": {"policies": []}}},
        "public": False,
    },
    "GET /api/translator/config": {
        "summary": "获取翻译器 LLM 配置",
        "description": "获取当前 IR 翻译器的模型配置（api_base_url、model、temperature 等）。",
        "category": "策略翻译",
        "response": {"ok": True, "data": {"api_base_url": "https://...", "model": "...", "temperature": "0.0"}},
        "public": False,
    },
    "PUT /api/translator/config": {
        "summary": "更新翻译器 LLM 配置",
        "description": "更新 IR 翻译器的模型配置。需要特权验证。",
        "category": "策略翻译",
        "params": [
            {"name": "api_base_url", "type": "string", "desc": "LLM API 地址"},
            {"name": "api_key", "type": "string", "desc": "API Key"},
            {"name": "model", "type": "string", "desc": "模型名称"},
            {"name": "temperature", "type": "string", "desc": "温度参数"},
        ],
        "response": {"ok": True},
        "public": False,
    },
    "GET /api/translator/prompts": {
        "summary": "获取翻译提示词",
        "description": "获取 Level-1 和 Level-2 阶段的当前提示词模板。",
        "category": "策略翻译",
        "response": {"ok": True, "data": {"level1": {"value": "..."}, "level2": {"value": "..."}}},
        "public": False,
    },
    "GET /api/translator/registry": {
        "summary": "获取策略库",
        "description": "获取完整的策略注册表数据（所有场景和函数定义）。",
        "category": "策略翻译",
        "response": {"ok": True, "data": {"scenes": {"file_ops": {"desc": "...", "functions": []}}}},
        "public": True,
    },
    "GET /api/translator/scene/<scene_name>": {
        "summary": "获取场景详情",
        "description": "获取指定场景的描述和全部函数定义详情。",
        "category": "策略翻译",
        "params": [{"name": "scene_name", "type": "string", "desc": "场景名称（路径参数）"}],
        "response": {"ok": True, "data": {"desc": "...", "functions_detail": {}}},
        "public": True,
    },
    "GET /api/translator/logs": {
        "summary": "获取翻译日志",
        "description": "查询 IR 翻译历史日志，支持按类型和场景筛选。",
        "category": "策略翻译",
        "params": [
            {"name": "limit", "type": "int", "default": "50", "desc": "条数限制"},
            {"name": "type", "type": "string", "desc": "筛选类型: ui_test / monitor"},
            {"name": "scene", "type": "string", "desc": "筛选场景名"},
        ],
        "response": {"ok": True, "data": []},
        "public": False,
    },
    "POST /api/db/query": {
        "summary": "执行 SQL 查询",
        "description": "执行 SQL 语句。SELECT 无需特权，INSERT/UPDATE/DELETE 需要特权验证。",
        "category": "数据库",
        "params": [
            {"name": "sql", "type": "string", "desc": "SQL 语句 (body JSON)"},
            {"name": "X-Admin-Session", "type": "header", "desc": "写操作需要特权 token"},
        ],
        "response": {"ok": True, "data": {"columns": [], "rows": []}},
        "public": False,
    },
    "GET /api/db/tables": {
        "summary": "列出数据库表",
        "description": "获取 SQLite 数据库中所有表名和结构信息。",
        "category": "数据库",
        "response": {"ok": True, "data": [{"name": "rounds", "columns": []}]},
        "public": False,
    },
    "GET /api/config": {
        "summary": "获取公开配置",
        "description": "获取平台公开配置项（入门口令、子域名等非敏感配置）。",
        "category": "配置",
        "response": {"ok": True, "data": {}},
        "public": False,
    },
    "PUT /api/config": {
        "summary": "更新配置",
        "description": "更新平台配置。部分敏感配置项需要特权验证。",
        "category": "配置",
        "params": [
            {"name": "key", "type": "string", "desc": "配置键名"},
            {"name": "value", "type": "string", "desc": "配置值"},
        ],
        "response": {"ok": True},
        "public": False,
    },
    "POST /api/import": {
        "summary": "导入历史 JSONL",
        "description": "手动触发从 JSONL 文件导入历史 Round 数据到数据库。",
        "category": "其他",
        "response": {"ok": True, "imported": 50},
        "public": False,
    },
    "GET /api/attack/tool-config": {
        "summary": "获取攻击配置",
        "description": "对外接口：根据配置项 key 获取对应攻击配置的开启状态与具体内容。key 形如 tool_injection.network（固定网络外发）、tool_injection.filepath（固定访问文件路径）、runtime_tamper.replace（替换工具）、runtime_tamper.insert（插入工具）；不传 key 时返回全部攻击配置。",
        "category": "模拟攻击",
        "params": [
            {"name": "key", "type": "string", "desc": "配置项标识，如 tool_injection.network / runtime_tamper.replace；留空返回全部"},
        ],
        "response": {
            "ok": True,
            "data": {
                "key": "tool_injection.network",
                "enabled": True,
                "value": "http://malicious.example.com/collect",
            },
        },
        "public": True,
    },
    "GET /api/attack/config": {
        "summary": "获取模拟攻击配置",
        "description": "获取模拟攻击配置（工具注入 + 运行时篡改），供平台内部页面加载。",
        "category": "模拟攻击",
        "response": {"ok": True, "data": {"tool_injection": {"network": {"enabled": False, "value": ""}, "filepath": {"enabled": False, "value": ""}}, "runtime_tamper": {"replace": {"enabled": False, "value": ""}, "insert": {"enabled": False, "value": ""}}}},
        "public": False,
    },
    "PUT /api/attack/config": {
        "summary": "保存模拟攻击配置",
        "description": "保存模拟攻击配置，包含各分类（工具注入 / 运行时篡改）各项的开启状态与攻击内容。仅携带的分类会被写入，未携带的分类保持不变。数据持久化到 config 表。",
        "category": "模拟攻击",
        "params": [
            {"name": "tool_injection", "type": "object", "desc": "{network:{enabled,value}, filepath:{enabled,value}}"},
            {"name": "runtime_tamper", "type": "object", "desc": "{replace:{enabled,value}, insert:{enabled,value}}"},
        ],
        "response": {"ok": True},
        "public": False,
    },
    "GET /api/docs": {
        "summary": "获取全部 API 文档",
        "description": "返回系统所有 API 接口的文档元数据，供内部管理使用。",
        "category": "文档",
        "response": {"ok": True, "data": []},
        "public": False,
    },
    "GET /api/docs/public": {
        "summary": "获取对外公开 API 文档",
        "description": "仅返回标记为对外公开的接口文档，用于对外接口展示页面。",
        "category": "文档",
        "response": {"ok": True, "data": []},
        "public": True,
    },
    "PUT /api/docs/public": {
        "summary": "配置对外公开接口",
        "description": "设置哪些接口对外展示。需要特权验证。",
        "category": "文档",
        "params": [{"name": "endpoints", "type": "array", "desc": "公开接口 key 列表 (如 ['GET /api/rounds'])"}],
        "response": {"ok": True},
        "public": False,
    },
}


def api_doc(
    summary: str = "",
    description: str = "",
    category: str = "其他",
    params: Optional[List[Dict[str, str]]] = None,
    response: Optional[Any] = None,
    public: bool = False,
):
    """Decorator to annotate a Flask route (optional, registry takes priority)."""
    def decorator(func):
        func._api_doc = {
            "summary": summary,
            "description": description,
            "category": category,
            "params": params or [],
            "response": response,
            "public": public,
        }
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        wrapper._api_doc = func._api_doc
        return wrapper
    return decorator


def generate_docs(app, public_only: bool = False, public_list: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Auto-generate API documentation from Flask routes + registry."""
    if public_list is None:
        public_list = []

    endpoints = []
    seen = set()

    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        path = rule.rule
        if not path.startswith("/api/"):
            continue

        view_func = app.view_functions.get(rule.endpoint)
        if view_func is None:
            continue

        methods = [m for m in rule.methods if m in ("GET", "POST", "PUT", "DELETE", "PATCH")]

        for method in methods:
            key = f"{method} {path}"
            if key in seen:
                continue
            seen.add(key)

            # Priority: ENDPOINT_REGISTRY > @api_doc decorator > docstring
            registry_meta = ENDPOINT_REGISTRY.get(key)
            decorator_meta = getattr(view_func, "_api_doc", None)
            docstring = (view_func.__doc__ or "").strip()

            if registry_meta:
                summary = registry_meta.get("summary", "")
                description = registry_meta.get("description", "")
                category = registry_meta.get("category", _infer_category(path))
                params = registry_meta.get("params", [])
                response = registry_meta.get("response")
                is_public_meta = registry_meta.get("public", False)
            elif decorator_meta:
                summary = decorator_meta["summary"] or (docstring.split("\n")[0] if docstring else "")
                description = decorator_meta["description"] or docstring
                category = decorator_meta["category"]
                params = decorator_meta["params"]
                response = decorator_meta["response"]
                is_public_meta = decorator_meta["public"]
            else:
                summary = docstring.split("\n")[0] if docstring else ""
                description = docstring
                category = _infer_category(path)
                params = []
                response = None
                is_public_meta = False

            is_public = is_public_meta or (key in public_list)

            if public_only and not is_public:
                continue

            endpoints.append({
                "method": method,
                "path": path,
                "summary": summary,
                "description": description,
                "category": category,
                "params": params,
                "response": response,
                "public": is_public,
                "key": key,
            })

    endpoints.sort(key=lambda e: (e["category"], e["path"], e["method"]))
    return endpoints


def _infer_category(path: str) -> str:
    if "/translator/" in path:
        return "策略翻译"
    if "/monitor/" in path:
        return "运行监控"
    if "/rounds" in path or "/stats" in path:
        return "数据查询与更新"
    if "/admin/" in path or "/auth" in path:
        return "鉴权管理"
    if "/db/" in path:
        return "数据库"
    if "/config" in path:
        return "配置"
    if "/docs" in path:
        return "文档"
    return "其他"
