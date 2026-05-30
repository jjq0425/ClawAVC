"""
IR Translator Core - integrated from openclaw_ir_translator_v3
==============================================================

Two-stage pipeline:
  Level-1: user query -> scene tags
  Level-2: query + selected scene definitions -> subject/objects IR

Config stored in SQLite config table with prefix: ir_translator.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

def _get_config(key: str, default: str = "") -> str:
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
        import db
        val = db.get_config(f"ir_translator.{key}")
        return val if val is not None else default
    except Exception:
        return default



_DEFAULT_REGISTRY_DIR = Path(__file__).resolve().parent / "policy_registry"


def _get_registry_dir() -> Path:
    """Get registry dir from config, fallback to default."""
    custom = _get_config("registry_path", "")
    if custom.strip():
        p = Path(custom.strip())
        if p.exists() and (p / "scenes.json").exists():
            return p
    return _DEFAULT_REGISTRY_DIR


REGISTRY_DIR = _get_registry_dir()


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


def get_llm_config() -> Dict[str, Any]:
    temp_str = _get_config("temperature", "0")
    timeout_str = _get_config("timeout", "60")
    return {
        "api_base_url": _get_config("api_base_url", "https://api.longcat.chat/openai"),
        "api_key": _get_config("api_key", ""),
        "model": _get_config("model", "LongCat-2.0-Preview"),
        "temperature": float(temp_str) if temp_str.strip() else 0.0,
        "timeout": int(timeout_str) if timeout_str.strip() else 60,
        "json_mode": _get_config("json_mode", "1") in ("1", ""),
    }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
def load_scene_registry() -> Dict[str, Any]:
    with open(REGISTRY_DIR / "scenes.json", "r", encoding="utf-8") as f:
        return json.load(f)


def load_tool_registry() -> Dict[str, Any]:
    registry: Dict[str, Any] = {}
    for path in sorted((REGISTRY_DIR / "tools").glob("*.json")):
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        scene = obj.get("scene")
        if scene:
            registry[scene] = obj
    return registry


SCENE_REGISTRY = load_scene_registry()
TOOL_REGISTRY = load_tool_registry()


def reload_registry():
    global SCENE_REGISTRY, TOOL_REGISTRY, REGISTRY_DIR
    REGISTRY_DIR = _get_registry_dir()
    SCENE_REGISTRY = load_scene_registry()
    TOOL_REGISTRY = load_tool_registry()


# ---------------------------------------------------------------------------
# LLM Client
# ---------------------------------------------------------------------------
def call_llm(
    system_prompt: str,
    user_prompt: str,
    config: Optional[Dict[str, Any]] = None,
    max_retry: int = 2,
) -> Tuple[str, Dict[str, Any]]:
    cfg = config or get_llm_config()
    api_base = cfg["api_base_url"].rstrip("/")
    if "/chat/completions" in api_base:
        endpoint = api_base
    else:
        endpoint = f"{api_base}/chat/completions"
    api_key = cfg["api_key"]
    model = cfg["model"]
    temperature = cfg["temperature"]
    timeout = cfg["timeout"]
    json_mode = cfg["json_mode"]

    if not api_key:
        raise RuntimeError("API Key 未配置，请在「策略翻译 → 模型配置」中设置")

    payload: Dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    last_err: Optional[Exception] = None
    for attempt in range(max_retry + 1):
        t0 = time.time()
        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:500]}")
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return content, {
                "model": model, "endpoint": endpoint,
                "latency_ms": int((time.time() - t0) * 1000),
                "attempt": attempt + 1, "usage": data.get("usage", {}),
            }
        except Exception as e:
            last_err = e
            if attempt < max_retry:
                time.sleep(1.5 ** attempt)
    raise RuntimeError(f"LLM 调用失败（共 {max_retry + 1} 次）: {last_err}")


def _extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("LLM 响应中未找到 JSON 对象")
    return json.loads(text[start:end + 1])


# ---------------------------------------------------------------------------
# Prompts (built-in defaults, can be overridden via config)
# ---------------------------------------------------------------------------
LEVEL1_SYS = """你是一个「Agent 权限场景分类器」。

任务：根据用户自然语言请求，选择完成任务"必须授权"的最小场景集合。

只允许从下面的封闭集合中选择，不得创造新标签：

{SCENE_LIST}

输出格式：
{
  "scenes": ["<scene1>", "<scene2>"]
}

判定原则：
1. 只选择用户请求中明确需要、或完成任务不可避免需要的 scene；不要因为模型"可能会用到"就扩大授权。
2. scenes 顺序必须按用户任务的实际执行顺序排列，例如"搜索并保存"应为 ["search", "file_ops"]。
3. 如果请求需要最新信息、联网核验、来源链接、网页内容读取，选择 search；如果只是一般常识回答，不要选择 search。
4. 如果请求需要真实浏览器渲染、点击、输入、截图、登录态页面或 DOM 交互，选择 browser；普通信息检索不要用 browser。
5. 如果请求涉及读取、写入、编辑、保存、导出、生成文件、打补丁或整理文件，选择 file_ops。
6. 如果请求涉及执行命令、运行脚本、测试、构建、安装、启动服务、查看环境或查看进程，选择 shell_exec；如果是长期/交互式会话再选择 terminal_session。
7. 如果请求涉及进程状态、停止、重启、kill、PID、后台服务控制，选择 process_control 或 runtime_exec 中更贴近语义的 scene。
8. 如果请求涉及对外发送消息、通知、邮件、日历、媒体播放、锁屏、提权等，只在用户明确要求时选择对应 scene。
9. 不能输出封闭集合之外的 scene。不能输出解释、注释、Markdown 代码块。
"""

LEVEL2_SYS = """你是一个「OpenClaw function-level 权限 IR 生成器」。

输入：
1. 用户 query
2. 第一阶段得到的 scenes
3. 每个 scene 对应的 function 定义 JSON

任务：基于输入，输出完成该 query 所需的权限 IR（subject/objects 格式）。你的输出是权限授权计划，不是执行计划。

重要：对于每个 scene，你必须列出该场景下所有可能被 Agent 用来完成任务的 function（不要只列一个），并为每个 function 都生成完整的参数约束。Agent 的实际行为可能使用同一场景下的多种工具组合，你需要预判并覆盖所有合理的执行路径。

输出格式要求（严格遵守）：
- 只输出一个 JSON 对象，顶层必须包含 `policies` 数组。
- 每个 policy 必须包含：`subject`（场景名）、`objects`（数组）、`effect`（值为 "allow"）。
- objects 数组中每个对象必须包含：`type`（"tool" 或 "file"）、`identifier`（工具函数名或文件路径）。
- 对于 type="tool" 的对象：
  - `identifier` 必须逐字等于 function 定义 JSON 中的 key（如 "read"、"safe_file_reader__read_text"）。
  - `actions` 固定为 ["invoke"]。
  - `params` 为数组格式：[{"name": "参数名", "identifier": "参数值"}]，只能使用 function 定义中声明过的参数名。
- 对于 type="file" 的对象：
  - `identifier` 为文件路径（来自用户 query 或工具参数中的路径）。
  - `actions` 为允许的文件操作列表，如 ["read"]、["write", "create"] 等。
- 不得输出任何额外解释、注释或 Markdown。

关键规则：
1. 场景内全覆盖：对于每个已选 scene，必须列出所有可能被 Agent 调用的 function 作为 tool 对象。不要只输出一个——Agent 可能通过多种工具路径完成同一任务。
2. 文件资源必须显式声明：如果某个工具的参数中包含文件路径，除了 tool 对象外，还必须额外生成一个对应的 type="file" 对象，声明允许的文件操作。
3. identifier 必须逐字等于 function 定义 JSON 中的 key；不得使用别名或自然语言。
4. params 值来源优先级：用户 query 明确给出 > 已验证上下文 > constraint_spec.static.default。对模棱两可的输入可留空字符串，但能从 query 明确提取的值不要留空。
5. 必须遵守 function 的 desc、constraint_spec.dynamic_ai_hint、static.allowlist/denylist 等约束。
6. 对于 allowed_values 非空的参数，值必须从中选择。
7. 对于高风险能力（shell、privilege 等），优先生成只读/查询权限。
8. 如果同一 scene 中多个 function 都能完成任务，必须全部列出——无法预知 Agent 选哪个。
9. 任何 required=true 的参数无法安全确定时，不生成该 function 对象。
10. 严禁输出密钥、隐私数据、敏感目录路径。

当前可用 function 定义 JSON：
{SELECTED_REGISTRY}
"""


def _get_prompt(level: str, default: str) -> str:
    """Load prompt from config. If not yet saved, initialize with built-in."""
    val = _get_config(f"prompt_{level}", "")
    if not val.strip():
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
            import db
            db.set_config(f"ir_translator.prompt_{level}", default)
        except Exception:
            pass
        return default
    return val


# ---------------------------------------------------------------------------
# Level-1
# ---------------------------------------------------------------------------
def _scene_list_for_prompt() -> str:
    lines = []
    for scene, meta in SCENE_REGISTRY.items():
        functions = ", ".join(meta.get("functions", []))
        lines.append(f"- {scene}: {meta['desc']} 可用 functions: [{functions}]")
    return "\n".join(lines)


def level1_classify(query: str, config: Optional[Dict[str, Any]] = None) -> Tuple[List[str], Dict[str, Any]]:
    prompt_template = _get_prompt("level1", LEVEL1_SYS)
    sys_prompt = prompt_template.replace("{SCENE_LIST}", _scene_list_for_prompt())
    raw, meta = call_llm(sys_prompt, query, config=config)
    try:
        obj = _extract_json(raw)
    except Exception:
        obj = {}
    scenes = [s for s in obj.get("scenes", []) if s in SCENE_REGISTRY]
    meta["raw_response"] = raw
    meta["parsed_scenes"] = scenes
    return scenes, meta


# ---------------------------------------------------------------------------
# Level-2
# ---------------------------------------------------------------------------
def _selected_registry_for_prompt(scenes: List[str]) -> str:
    selected = {s: TOOL_REGISTRY[s] for s in scenes if s in TOOL_REGISTRY}
    return json.dumps(selected, ensure_ascii=False, indent=2)


def level2_generate(query: str, scenes: List[str], config: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    selected_registry = _selected_registry_for_prompt(scenes)
    prompt_template = _get_prompt("level2", LEVEL2_SYS)
    sys_prompt = prompt_template.replace("{SELECTED_REGISTRY}", selected_registry)
    user_prompt = json.dumps({"query": query, "scenes": scenes}, ensure_ascii=False)
    raw, meta = call_llm(sys_prompt, user_prompt, config=config)
    try:
        ir = _extract_json(raw)
    except Exception:
        ir = {}
    meta["raw_response"] = raw
    return ir, meta


# ---------------------------------------------------------------------------
# Normalize
# ---------------------------------------------------------------------------
def _static_spec(param_def: Dict[str, Any]) -> Dict[str, Any]:
    spec = param_def.get("constraint_spec", {}).get("static", {})
    return spec if isinstance(spec, dict) else {}


def normalize_ir(ir: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize LLM output to subject/objects format. Handles both new and old formats."""
    raw_policies = ir.get("policies", [])
    normalized: List[Dict[str, Any]] = []

    for policy in raw_policies:
        if "subject" in policy and "objects" in policy:
            subj = policy["subject"]
            objs = policy.get("objects", [])
            if subj in TOOL_REGISTRY:
                fn_defs = TOOL_REGISTRY[subj].get("functions", {})
                for obj in objs:
                    if obj.get("type") == "tool":
                        ident = obj.get("identifier", "")
                        if ident not in fn_defs:
                            for registered in fn_defs:
                                if "__" in registered and registered.split("__", 1)[1] == ident:
                                    obj["identifier"] = registered
                                    break
                        if "actions" not in obj:
                            obj["actions"] = ["invoke"]
            normalized.append({"subject": subj, "objects": objs, "effect": policy.get("effect", "allow")})
            continue

        # Old format fallback
        scene = policy.get("scene", "")
        if scene not in TOOL_REGISTRY:
            continue
        scene_def = TOOL_REGISTRY[scene]
        fn_defs = scene_def.get("functions", {})
        fns = policy.get("functions", [])
        if not isinstance(fns, list):
            continue
        objects: List[Dict[str, Any]] = []
        for fn in fns:
            name = fn.get("name", "")
            if name not in fn_defs:
                for registered in fn_defs:
                    if "__" in registered and registered.split("__", 1)[1] == name:
                        name = registered
                        break
            if name not in fn_defs:
                continue
            fn_def = fn_defs[name]
            params = fn.get("params", {})
            if not isinstance(params, dict):
                params = {}
            for param_name, param_def in fn_def.get("params", {}).items():
                static = _static_spec(param_def)
                default = static.get("default")
                if param_name not in params and default is not None:
                    params[param_name] = default
            param_list = [{"name": k, "identifier": str(v)} for k, v in params.items() if v is not None]
            objects.append({"type": "tool", "identifier": name, "actions": ["invoke"], "params": param_list or None})
            fa = fn_def.get("file_actions") or fn.get("file_actions")
            path_val = params.get("path") or params.get("file") or params.get("target")
            if path_val and fa:
                objects.append({"type": "file", "identifier": str(path_val), "actions": fa})
        if objects:
            normalized.append({"subject": scene, "objects": objects, "effect": "allow"})

    ir["policies"] = normalized
    return ir


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------
@dataclass
class ValidationReport:
    ok: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def validate_ir(ir: Dict[str, Any]) -> ValidationReport:
    """
    Deep validation of normalized IR (subject/objects format) against registry.
    Checks:
    - policies 数组存在且非空
    - 每个 policy 必须有 subject, objects, effect
    - subject 必须为已知场景（或通配符兜底场景）
    - tool 对象的 identifier 必须在场景注册表中（* 通配除外）
    - tool 对象的 params 中的 name 必须在 function 定义的 params 中
    - file 对象必须有 identifier 和 actions
    - effect 必须为 "allow"
    """
    rep = ValidationReport()

    # Top-level checks
    if not ir or not isinstance(ir, dict):
        rep.ok = False
        rep.errors.append("IR 必须为非空 JSON 对象")
        return rep
    policies = ir.get("policies")
    if not isinstance(policies, list):
        rep.ok = False
        rep.errors.append("缺少顶层 policies 数组")
        return rep
    if len(policies) == 0:
        rep.ok = False
        rep.errors.append("policies 数组不能为空")
        return rep

    for i, policy in enumerate(policies):
        # Structure checks
        if not isinstance(policy, dict):
            rep.ok = False
            rep.errors.append(f"policy[{i}] 必须为对象")
            continue

        subject = policy.get("subject")
        objects = policy.get("objects")
        effect = policy.get("effect")

        if not subject:
            rep.ok = False
            rep.errors.append(f"policy[{i}] 缺少 subject 字段")
            continue
        if not isinstance(objects, list):
            rep.ok = False
            rep.errors.append(f"policy[{i}] 缺少 objects 数组")
            continue
        if effect != "allow":
            rep.ok = False
            rep.errors.append(f"policy[{i}] effect 必须为 'allow'，当前为 {effect!r}")

        if len(objects) == 0:
            rep.ok = False
            rep.errors.append(f"policy[{i}] objects 不能为空")
            continue

        # Subject validation (allow custom fallback subjects like default_fallback, file_access)
        is_known_scene = subject in SCENE_REGISTRY
        has_tool_registry = subject in TOOL_REGISTRY
        fn_defs = TOOL_REGISTRY.get(subject, {}).get("functions", {}) if has_tool_registry else {}

        if not is_known_scene and subject not in ("default_fallback", "file_access"):
            rep.warnings.append(f"policy[{i}] subject '{subject}' 不在已知场景列表中")

        # resource_type check (for backward compat with old format)
        if "resource_type" in policy and has_tool_registry:
            scene_def = TOOL_REGISTRY[subject]
            expected_rt = scene_def.get("resource_type")
            actual_rt = policy.get("resource_type")
            if actual_rt and actual_rt != expected_rt and actual_rt != "tool":
                rep.ok = False
                rep.errors.append(f"policy[{i}] resource_type 应为 '{expected_rt}' 或 'tool'，当前为 '{actual_rt}'")

        # Validate each object
        for j, obj in enumerate(objects):
            if not isinstance(obj, dict):
                rep.ok = False
                rep.errors.append(f"policy[{i}].objects[{j}] 必须为对象")
                continue

            obj_type = obj.get("type")
            identifier = obj.get("identifier")

            if obj_type not in ("tool", "file"):
                rep.ok = False
                rep.errors.append(f"policy[{i}].objects[{j}] type 必须为 'tool' 或 'file'，当前为 {obj_type!r}")
                continue

            if not identifier:
                rep.ok = False
                rep.errors.append(f"policy[{i}].objects[{j}] 缺少 identifier")
                continue

            if obj_type == "tool":
                # Validate tool object
                actions = obj.get("actions")
                if not isinstance(actions, list) or not actions:
                    rep.warnings.append(f"policy[{i}].objects[{j}] tool 对象建议包含 actions 字段")

                # Check identifier against registry (skip * wildcard)
                if identifier != "*" and fn_defs and identifier not in fn_defs:
                    rep.warnings.append(f"policy[{i}].objects[{j}] 工具 '{identifier}' 不在场景 '{subject}' 的注册表中")

                # Validate params
                params = obj.get("params")
                if params is not None:
                    if not isinstance(params, list):
                        rep.ok = False
                        rep.errors.append(f"policy[{i}].objects[{j}] params 必须为数组格式 [{{name, identifier}}]")
                    else:
                        # Check each param name against function definition
                        if identifier != "*" and identifier in fn_defs:
                            allowed_params = set(fn_defs[identifier].get("params", {}).keys())
                            for k, param in enumerate(params):
                                if not isinstance(param, dict):
                                    rep.ok = False
                                    rep.errors.append(f"policy[{i}].objects[{j}].params[{k}] 必须为对象")
                                    continue
                                param_name = param.get("name")
                                if not param_name:
                                    rep.ok = False
                                    rep.errors.append(f"policy[{i}].objects[{j}].params[{k}] 缺少 name")
                                elif param_name not in allowed_params:
                                    rep.ok = False
                                    rep.errors.append(f"policy[{i}].objects[{j}].params[{k}] 参数 '{param_name}' 不在 '{identifier}' 的合法参数列表中（合法: {sorted(allowed_params)}）")

            elif obj_type == "file":
                # Validate file object
                actions = obj.get("actions")
                if not isinstance(actions, list) or not actions:
                    rep.ok = False
                    rep.errors.append(f"policy[{i}].objects[{j}] file 对象必须包含非空 actions 数组")
                else:
                    valid_file_actions = {"read", "write", "create", "delete", "execute", "modify"}
                    for act in actions:
                        if act not in valid_file_actions:
                            rep.warnings.append(f"policy[{i}].objects[{j}] 未知文件操作 '{act}'")

    return rep


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------
def translate(query: str, config: Optional[Dict[str, Any]] = None, is_ui_test: bool = False, round_id: str = "") -> Dict[str, Any]:
    """Full pipeline: query -> level1 -> level2 -> normalize -> validate -> store."""
    cfg = config or get_llm_config()

    # Level 1
    scenes, meta1 = level1_classify(query, config=cfg)

    # Level 2
    if scenes:
        ir, meta2 = level2_generate(query, scenes, config=cfg)
    else:
        ir, meta2 = {}, {}

    # Normalize
    if ir:
        ir = normalize_ir(ir)

    # Validate
    validation = validate_ir(ir) if ir else ValidationReport(ok=True)

    result = {
        "query": query,
        "level1": scenes,
        "level2": ir,
        "validation": {"ok": validation.ok, "errors": validation.errors, "warnings": validation.warnings},
        "meta": {"level1": meta1, "level2": meta2},
    }

    # Store to translation log
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
        import db
        db.insert_translation_log(result, is_ui_test=is_ui_test, round_id=round_id)
    except Exception:
        pass

    return result


def normalize_and_validate(ir_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize and validate an IR dict without LLM call. For default policy saving."""
    if ir_dict:
        ir_dict = normalize_ir(ir_dict)
    validation = validate_ir(ir_dict) if ir_dict else ValidationReport(ok=True)
    return {
        "ir": ir_dict,
        "validation": {"ok": validation.ok, "errors": validation.errors, "warnings": validation.warnings},
    }
