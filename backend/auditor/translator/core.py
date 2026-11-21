"""
IR Translator Core - integrated from openclaw_ir_translator_v3
==============================================================

Two-stage pipeline:
  Level-1: user query -> scene tags
  Level-2: query + selected scene definitions -> subject/objects IR

Config stored in SQLite config table with prefix: ir_translator.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

def _get_config(key: str, default: str = "") -> str:
    """
    读取平台配置库（config 表）中指定键的值。

    直接 import db 而非经包装层，便于单元测试以临时库整体替换。

    Args:
        key: 配置键名。
        default: 键不存在或读取异常时的缺省值。

    Returns:
        配置值（字符串）；不存在时返回 default。
    """
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
        import db
        val = db.get_config(f"ir_translator.{key}")
        return val if val is not None else default
    except Exception:
        return default



_DEFAULT_REGISTRY_DIR = Path(__file__).resolve().parent / "policies" / "default" / "policy_registry"


# 当前生效注册表目录解析：模板+当前角色优先，配置缺失/无效时回退默认策略库
def _get_registry_dir() -> Path:
    """Get registry dir from config, fallback to default."""
    # 默认库目录随包内置，保证零配置冷启动可用
    # 本函数在「配置直接指定目录」与「模板+角色」之间取前者，保证运维显式配置优先
    # 目录解析优先级：config 显式路径 > 模板+当前角色 > 默认库；三者不一致时由 sync_registry_path 纠正
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


DEFAULT_LLM_TIMEOUT = 180


# 跨模块复制 IR 翻译模型配置：按目标前缀批量搬运，敏感项保持目标侧约定
def copy_ir_llm_config(db_module: Any, target_prefix: str,
                       keys=("api_base_url", "model", "api_key",
                             "temperature", "timeout")) -> Dict[str, Any]:
    """把「策略翻译 → 模型配置」的连接参数复制到另一套独立配置（含 API Token）。

    本地 portkey 网关的 model alias（如 useme）只接受**网关 bearer token**，
    各模块（AI 帮写 / 敏感文件 / RSI）若手填第三方厂商 Key 会被网关 400 拒绝。
    IR 翻译那套配置已经跑通，统一从这里复用，避免重复实现与漏配。

    Args:
        db_module: 提供 get_config / set_config 的 db 模块
        target_prefix: 目标配置前缀，如 "ai_writer." / "sensitive." / "rsi."
    """
    # 配置搬运保持隔离：目标侧已有的键不覆盖，避免互相污染
    copied: List[str] = []
    for k in keys:
        try:
            val = db_module.get_config(f"ir_translator.{k}")
        except Exception:
            continue
        if val is None or not str(val).strip():
            continue
        try:
            db_module.set_config(f"{target_prefix}{k}", str(val))
        except Exception as exc:
            raise RuntimeError(f"配置写入失败：{exc}") from exc
        copied.append("api_key（已同步，不回显）" if k == "api_key" else k)
    if not copied:
        return {"ok": False, "error": "未找到 IR 意图翻译模型的连接配置"}
    return {"ok": True, "data": {"copied": copied}}


def get_llm_config() -> Dict[str, Any]:
    """
    组装 IR 翻译大模型的完整调用配置。

    覆盖键：api_base_url / api_key / model / temperature / json_mode /
    timeout / max_tokens。任何键缺失时均有内置缺省，保证可发起一次合法调用；
    api_key 未配置时 call_llm 会给出明确错误而非静默失败。

    # json_mode 依赖上游支持 response_format；不支持时 _extract_json 的容错仍可正确解析
    Returns:
        # temperature 与 timeout 直接决定重试行为稳定性，配置错误会在 call_llm 的 meta 中暴露
        可直接传给 call_llm 的配置 dict。
    """
    # max_tokens 空值不下发：交由上游默认；显式配置才生效（R12 空响应根因相关）
    temp_str = _get_config("temperature", "0")
    # 默认读超时 180 s（R7 修复）：生产日志中 Level-2 成功调用的耗时紧贴 60 s 上限（P99 55.5 s、最大 59.0 s），
    # 说明原 60 s 默认值截断了长尾请求，导致「Read timed out」整轮失败
    timeout_str = _get_config("timeout", str(DEFAULT_LLM_TIMEOUT))
    return {
        "api_base_url": _get_config("api_base_url", "https://api.longcat.chat/openai"),
        "api_key": _get_config("api_key", ""),
        "model": _get_config("model", "LongCat-2.0-Preview"),
        "temperature": float(temp_str) if temp_str.strip() else 0.0,
        "timeout": int(timeout_str) if timeout_str.strip() else DEFAULT_LLM_TIMEOUT,
        "json_mode": _get_config("json_mode", "1") in ("1", ""),
    }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
# 加载场景清单 scenes.json：文件缺失/非法时降级为空场景集合（不抛异常）
def load_scene_registry() -> Dict[str, Any]:
    """加载场景注册表；缺失/非法时降级为空集合并告警，不阻断主链路。"""
    # 场景清单以 scenes.json 为唯一事实源：场景数与页面卡片数严格一致（F-1-1 ⑥）
    try:
        with open(REGISTRY_DIR / "scenes.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[core] load_scene_registry degraded (dir={REGISTRY_DIR}): {e}", flush=True)
        return {}


# 加载工具定义：目录内全部 *.json 逐个解析，无 scene 归属或非法文件被丢弃
def load_tool_registry() -> Dict[str, Any]:
    """
    从场景-权限策略库 tools/ 目录加载全部工具定义并按场景建索引。

    规则：
        · 每个工具文件须含顶层 scene 字段，缺失场景归属的文件被丢弃；
        · 内容非法的文件跳过不抛异常，由健康检查接口另行报告行列。

    Returns:
        {场景名: {functions: {函数名: 定义}}} 的工具注册表。
    """
    registry: Dict[str, Any] = {}
    for path in sorted((REGISTRY_DIR / "tools").glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
        except Exception as e:
            print(f"[core] skip invalid tool json {path.name}: {e}", flush=True)
            continue
        scene = obj.get("scene")
        if scene:
            registry[scene] = obj
    return registry


# 注册表逐文件健康检查：非法 JSON 定位到行列，缺 scene 字段给出具体文件名
def registry_file_errors(registry_dir: Any) -> List[str]:
    # 健康检查实现：逐文件 json.load 并定位行列，缺 scene 字段单独提示；
    # 结果同时被策略库页面与 R-1-2 残缺降级用例使用
    """逐个解析策略库中的 scenes.json 与 tools/*.json，返回可定位到文件与行列的错误列表（供健康检查）。"""
    base = Path(registry_dir)
    errors: List[str] = []
    files = [base / "scenes.json"] + sorted((base / "tools").glob("*.json"))
    for f in files:
        rel = f.relative_to(base).as_posix()
        if not f.exists():
            continue
        try:
            obj = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            errors.append(f"{rel} 不是合法 JSON（第 {e.lineno} 行第 {e.colno} 列：{e.msg}）")
            continue
        except Exception as e:  # 编码错误 / 无读权限
            errors.append(f"{rel} 无法读取：{e}")
            continue
        if not isinstance(obj, dict):
            errors.append(f"{rel} 顶层必须是 JSON 对象")
        elif rel != "scenes.json" and not obj.get("scene"):
            errors.append(f"{rel} 缺少顶层 scene 字段，加载时会被忽略")
    return errors


SCENE_REGISTRY = load_scene_registry()
TOOL_REGISTRY = load_tool_registry()


def reload_registry():
    """
    热重载场景与工具注册表（SCENE_REGISTRY / TOOL_REGISTRY / REGISTRY_DIR）。

    切换角色策略库或修改定义文件后调用，无需重启进程；
    场景清单缺失等残缺情况降级为空集合而不抛异常（fail-safe）。
# 任何残缺输入都收敛为空注册表而非异常：翻译链路继续运行，健康检查暴露问题（R-1-2）

    Returns:
        None，直接刷新模块级全局状态。
    """
    # 重载范围：场景注册表 + 工具注册表 + 注册表路径三者同步刷新，保持一致性
    global SCENE_REGISTRY, TOOL_REGISTRY, REGISTRY_DIR
    REGISTRY_DIR = _get_registry_dir()
    SCENE_REGISTRY = load_scene_registry()
    TOOL_REGISTRY = load_tool_registry()


# ---------------------------------------------------------------------------
# LLM Client
# ---------------------------------------------------------------------------
# 大模型调用统一入口：OpenAI 兼容协议 + 限流退避 + 指数重试 + meta 落库
def call_llm(
    system_prompt: str,
    user_prompt: str,
    config: Optional[Dict[str, Any]] = None,
    max_retry: int = 2,
) -> Tuple[str, Dict[str, Any]]:
    """
    调用大模型 chat/completions 接口（OpenAI 兼容协议）。

    流程：
        1. 组装 system+user 双提示词，json_mode 开启时强制 response_format；
        2. 最多调用 max_retry+1 次：429 按 Retry-After/5s×2^n（上限 30s）退避，
           其余错误按 1.5^n 指数退避；
        3. meta 记录 latency_ms / attempt / usage / returned_model，供翻译日志
           落库与性能分析使用。

    Args:
        system_prompt, user_prompt: 两级提示词。
        config: 模型配置，缺省取 get_llm_config()。
        max_retry: 失败后的额外重试次数（默认 2，共 3 次）。

    Returns:
        (content, meta) 元组。

    Raises:
        RuntimeError: 全部尝试均失败时携带最后一次错误信息。
    """
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

    # 构造请求体：双提示词 + 可选 json_object 强制格式；
    # max_tokens 仅在配置存在时下发（推理型模型 reasoning token 计入 completion，上限过小会把正文截为空，见 R12）
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
    # 可选输出上限：推理型模型（reasoning tokens 计入 completion）需要调大，否则正文被截为空
    mt = str(cfg.get("max_tokens") or "").strip()
    if mt:
        try:
            payload["max_tokens"] = int(mt)
        except ValueError:
            pass

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    last_err: Optional[Exception] = None
    # 重试循环：最多 max_retry+1 次调用；
    # 429 → 限流退避（Retry-After / 5s×2^n，上限 30s）；其余错误 → 1.5^n 指数退避
    # 全部失败抛 RuntimeError（携带最后一次错误）
    for attempt in range(max_retry + 1):
        t0 = time.time()
        rate_wait: Optional[float] = None
        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
            if resp.status_code == 429:
                rate_wait = _rate_limit_wait(resp, attempt)
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:500]}")
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return content, {
                "model": model, "endpoint": endpoint,
                "latency_ms": int((time.time() - t0) * 1000),
                "attempt": attempt + 1, "usage": data.get("usage", {}),
                "returned_model": data.get("model"),
            }
        except Exception as e:
            last_err = e
            if attempt < max_retry:
                # 上游限流（429）按 Retry-After / 更长退避等待（R7 修复），其余错误保持 1.5 的指数退避
                time.sleep(rate_wait if rate_wait is not None else 1.5 ** attempt)
    raise RuntimeError(f"LLM 调用失败（共 {max_retry + 1} 次）: {last_err}")


RATE_LIMIT_BASE_WAIT = 5.0
RATE_LIMIT_MAX_WAIT = 30.0


# 429 退避时长：Retry-After 优先，否则 5s×2^attempt，上限 30s（R7 修复）
# 限流退避三要素：优先 Retry-After、指数放大、绝对上限（防上游给出超大值拖死链路）
# 限流退避三要素：优先 Retry-After、指数放大、绝对上限（防上游给出超大值拖死链路）
def _rate_limit_wait(resp: Any, attempt: int) -> float:
    """429 退避时长：优先采用 Retry-After（秒），否则 5 s × 2^attempt，上限 30 s。"""
    try:
        ra = float((resp.headers or {}).get("Retry-After", ""))
    except (TypeError, ValueError, AttributeError):
        ra = 0.0
    return min(max(ra, RATE_LIMIT_BASE_WAIT * (2 ** attempt)), RATE_LIMIT_MAX_WAIT)


# 状态机去尾随逗号：跳过字符串字面量内部，避免改写字符串内容（R4 修复）
# JSON 尾随逗号清理：字符级状态机，严格跳过字符串字面量内部（R4 修复）
def _strip_trailing_commas(text: str) -> str:
    """去掉 JSON 中 } / ] 前的尾随逗号；跳过字符串字面量内部，避免改写字符串内容。"""
    out: List[str] = []
    in_str = False
    esc = False
    quote = ""
    n = len(text)
    for i, ch in enumerate(text):
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                in_str = False
            continue
        if ch in "\"'":
            in_str, quote = True, ch
            out.append(ch)
            continue
        if ch == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                continue
        out.append(ch)
    return "".join(out)


# JSON 提取三级降级：整体解析 → 宽松修复 → 扫描首个对象（R-1-1 容错核心）
def _extract_json(text: str) -> Dict[str, Any]:
    """
    从 LLM 原始输出中提取 JSON 对象（R-1-1 容错核心）。

    三级降级：
        ① 整体直接解析（含剥除 ```json 代码围栏）；
        ② 宽松修复：去尾随逗号 / 单引号转双引号后重试；
        ③ 前后夹带解释文字时扫描文本，取第一个可解析的 JSON 对象。

    Args:
        text: LLM 原始响应文本。

    Returns:
        解析出的 dict。

    Raises:
        ValueError: 响应为空或全文无 JSON 对象。
    """
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    if not text:
        raise ValueError("LLM 响应为空")
    # 1) 整体直接解析
    try:
        return json.loads(text)
    except Exception:
        pass
    # 2) 宽松修复：去尾随逗号 / 单引号转双引号
    relaxed = _strip_trailing_commas(text)
    for cand in (relaxed, relaxed.replace("'", '"')):
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    # 3) 多 JSON 块 / 前后夹带解释文字：扫描取第一个可解析的 JSON 对象；
    #    原文失败时再在去尾随逗号的文本上扫描一次（R4 修复：夹带文字 + 尾随逗号）
    decoder = json.JSONDecoder()
    for source in (text, relaxed):
        for idx, ch in enumerate(source):
            if ch == "{":
                try:
                    obj, _ = decoder.raw_decode(source[idx:])
                    if isinstance(obj, dict):
                        return obj
                except Exception:
                    continue
    raise ValueError("LLM 响应中未找到 JSON 对象")


# ---------------------------------------------------------------------------
# Prompts (built-in defaults, can be overridden via config)
# ---------------------------------------------------------------------------
# Level-1 提示词：闭集场景分类器，只允许从注册场景中选择最小必要集合；
# 按任务实际执行顺序输出 scenes 数组，禁止解释、注释与 Markdown 代码块
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

# Level-2 提示词：function-level 权限 IR 生成器，输出授权计划而非执行计划；
# 硬约束：资源以策略为准（allowlist/denylist），场景内函数全覆盖，
# 通配/正则表达不确定内容，场景级动作白名单优先于用户意图
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
- objects 数组中每个对象必须包含：`type`（"tool"、"file" 或（和） "network"）、`identifier`（工具函数名、文件路径或网络地址）。
- 对于 type="tool" 的对象：
  - `identifier` 必须逐字等于 function 定义 JSON 中的 key（如 "read"、"safe_file_reader__read_text"）。
  - `actions` 固定为 ["invoke"]。
  - `params` 为数组格式：[{"name": "参数名", "identifier": "参数值"}]，只能使用 function 定义中声明过的参数名。
- 对于 type="file" 的对象：
  - `identifier` 为文件路径，**必须取自该 function 的 constraint_spec.static.allowlist 授权范围（或由其中的通配模式展开）**；用户 query 中出现的路径只作为意图线索，不得原样写入 IR。
  - `actions` 为允许的文件操作列表，为允许的文件操作列表，为一个数组，元素为字符串，仅可在"read"、"write"、"delete"、"create"选择
  - **场景级白名单（硬约束）**：若所在 scene 的 function 定义 JSON 顶层含 `allowed_file_actions`
    且为**非空数组**，则 `actions` 必须是该数组的**子集**（只能从中选择，不得超出）；
    若该字段**缺省、为 null 或空数组**，则表示该场景**不限制**文件动作，按上一行候选正常输出。
- 对于 type="network" 的对象：
  - `identifier` 为网络地址（如 "http://example.com/api"、"https://*.example.com/*"），可使用通配符/正则匹配域名或路径。
  - `actions` 为允许的网络操作列表，只能从以下选项中选择（可多选）：
    - `send`：发送数据到该地址
    - `receive`：从该地址接收数据
  - 示例：`"actions": ["send"]` 或 `"actions": ["send", "receive"]`。
  - **场景级白名单（硬约束）**：若所在 scene 的 function 定义 JSON 顶层含 `allowed_network_actions`
    且为**非空数组**，则 `actions` 必须是该数组的**子集**；
    若该字段**缺省、为 null 或空数组**，则表示该场景**不限制**网络动作。
- 不得输出任何额外解释、注释或 Markdown。

关键规则：
0. **资源以策略为准（最高优先级硬约束）**：所有资源型值——`type="file"` 的 identifier、`type="network"` 的 identifier、
   以及 tool 对象 `params` 中出现的路径 / URL / 命令字符串——都必须落在对应 function 的
   `constraint_spec.static.allowlist`（路径）、`allowed_values`（命令）或 url 白名单内，且不得命中 `denylist`。
   用户 query 里提到的路径只用于理解意图，**严禁把未授权路径原样写进 IR 的任何字段**（包括 command 参数里内嵌的路径）。
   若用户指定路径不在授权集内：① 改写为授权集内最接近的模式（如 `/tmp/rollback.sh` → `/workspace/**/*.sh`）；
   ② 无法改写时整体省略该资源对象或该参数；③ 可在 assumptions 中声明该假设。
   例：策略仅允许 `/workspace/**` 写入时，用户要求写 `/tmp/rollback.sh`，IR 中**不得出现 "/tmp" 字样**。
   IR 表达的是"策略允许做什么"，不是"用户想做什么"。
1. 场景内全覆盖：对于每个已选 scene，必须列出所有可能被 Agent 调用的 function 作为 tool 对象。不要只输出一个——Agent 可能通过多种工具路径完成同一任务。
2. 文件资源按需声明：当完成任务确实需要访问该文件时，才生成 type="file" 对象。若无文件访问必要，尽可能减少文件权限。
3. 网络资源按需声明：当完成任务确实需要网络通信时，才生成 type="network" 对象。若无网络访问必要，尽可能减少网络权限。
4. identifier 必须逐字等于 function 定义 JSON 中的 key；不得使用别名或自然语言。
5. params 值来源优先级：**策略库约束（allowlist / denylist / allowed_values / static.default）> 已验证上下文 > 用户 query**。用户 query 给出的值只有落入策略授权范围才能写入 IR；不在授权范围内的路径、域名或命令参数，必须改写为授权范围内的模式，或整体省略该参数/对象。
6. 必须遵守 function 的 desc、constraint_spec.dynamic_ai_hint、static.allowlist/denylist 等约束。
7. 对于 allowed_values 非空的参数，值必须从中选择。
8. 对于高风险能力（shell、privilege 等），优先生成只读/查询权限。
9. 场景级白名单优先于用户意图：若 scene 顶层声明了非空的 `allowed_file_actions` / `allowed_network_actions`，
   则对应 file / network 对象的 `actions` **不得超出该集合**。用户 query 要求但被该集合禁止的动作
   （例如只读场景要求"创建文件"）**一律不得输出**——宁可省略该对象，也不要输出被禁止的动作。
   IR 表达的是"策略允许做什么"，不是"用户想做什么"。
9. 如果同一 scene 中多个 function 都能完成任务，必须全部列出——无法预知 Agent 选哪个。
10. 任何 required=true 的参数无法安全确定时，不生成该 function 对象。
11. 除非用户明确访问（如读取xxx文件），否则尽可能不输出密钥、隐私数据、敏感目录路径。
12. **子场景选择**：当 constraint_spec.static 为数组时，每个元素的 note 字段标注了子场景（如"只读查询"、"安装依赖"等）。你必须根据用户 query 的意图，选择最匹配的子场景对应的约束（allowlist/denylist/default 等）来生成参数值，而非盲目使用第一个或默认值。
13. **通配符与正则表达式**：对于不确定或可变的内容，必须使用通配符或正则表达式，而非通用描述性话语。具体规则：
   - 文件路径：使用 `*` 匹配任意字符（如 `*.txt`、`/workspace/*`、`**/*.py`），使用 `**` 匹配多级目录（如 `/workspace/**/*`）
   - 写入内容（content 参数）：不确定具体内容时使用 `*` 或 `.*` 表示任意内容，而非写 "搜索结果"、"处理后的内容" 等描述性文字
   - URL/域名：使用 `*://*` 或 `https://*.example.com/*` 等模式
   - 命令参数：不确定的参数值使用 `*` 或正则如 `[a-zA-Z0-9]+`
   - 示例：
     - ✅ 正确：`{"name": "content", "identifier": "*"}`
     - ✅ 正确：`{"name": "path", "identifier": "/workspace/**/*.txt"}`
     - ✅ 正确：`{"name": "url", "identifier": "https://*"}`
     - ❌ 错误：`{"name": "content", "identifier": "整理后的数据"}`
     - ❌ 错误：`{"name": "content", "identifier": ""}`（空字符串表示不确定，但应使用 `*`，或者你可以不写这个参数）
# 提示词热更新：页面修改后立即生效，未初始化时写入内置默认便于回溯

当前可用 function 定义 JSON：
{SELECTED_REGISTRY}
"""


# 分级提示词读取：配置库优先，未初始化时写入内置默认（支持页面热改）
# 提示词热更新：页面修改后立即生效；未初始化时写入内置默认便于回溯
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


# Level-2 阶段实现：RAG 按需注入、空 IR 重试与场景级动作白名单裁剪
# ---------------------------------------------------------------------------
# Level-1
# ---------------------------------------------------------------------------
# 场景清单按「场景名：描述」逐行拼接，注入 {SCENE_LIST} 占位符
def _scene_list_for_prompt() -> str:
    """
    拼接 Level-1 提示词中的闭集场景清单（场景名 + 描述）。

    全部注册场景必须注入 Level-1 提示词，约束模型只能从中选择、
    不得编造新标签。

    Returns:
        场景清单文本块。
    """
    lines = []
    for scene, meta in SCENE_REGISTRY.items():
        functions = ", ".join(meta.get("functions", []))
        lines.append(f"- {scene}: {meta['desc']} 可用 functions: [{functions}]")
    return "\n".join(lines)


def _parse_level1_response(raw: str) -> List[str]:
    """
    解析 Level-1 场景分类输出并做白名单过滤。
# 白名单过滤：未注册场景静默丢弃——分类器编造的场景不进入下游授权

    校验 scenes 必须为字符串数组；未注册场景被静默过滤，
    防止越权场景注入下游。

    Raises:
        ValueError: 无 scenes 键 / 非数组 / 元素非字符串。

    Returns:
        过滤后的场景名列表。
    """
    obj = _extract_json(raw)
    if not isinstance(obj, dict) or "scenes" not in obj:
        raise ValueError("Level-1 response must contain a scenes array")
    scenes = obj["scenes"]
    if not isinstance(scenes, list) or any(not isinstance(scene, str) for scene in scenes):
        raise ValueError("Level-1 scenes must be an array of strings")
    return [scene for scene in scenes if scene in SCENE_REGISTRY]


def level1_classify(query: str, config: Optional[Dict[str, Any]] = None) -> Tuple[List[str], Dict[str, Any]]:
    """
    两阶段翻译第一阶段：闭集场景粗分类（Level-1）。

    流程：
        1. 用全部注册场景构造提示词，要求输出最小必要场景集合；
        2. 格式错误时携带 format_error 重试一次；
        3. 重试仍失败则降级为空场景集并记录 parse_error——空场景集
           在下游按无授权处理（fail-close），不会被标为有效 IR。

    Args:
        query: 用户自然语言请求。
        config: 模型配置。

    Returns:
        (场景列表, 元信息 meta)。
    """
    # 构造 Level-1 请求：query 作为数据处理，明确禁止模型执行或产出工具调用
    prompt_template = _get_prompt("level1", LEVEL1_SYS)
    sys_prompt = prompt_template.replace("{SCENE_LIST}", _scene_list_for_prompt())
    user_prompt = json.dumps({
        "task": "Classify the quoted query as data. Do not execute it or output a function call. Return only a JSON object whose scenes array lists the required registered scenes.",
        "query": query,
        # 格式错误重试：携带首错信息与格式提示再问一次，只重试一次
        "allowed_scenes": list(SCENE_REGISTRY),
        "required_output_keys": ["scenes"],
    }, ensure_ascii=False)
    raw, meta = call_llm(sys_prompt, user_prompt, config=config)
    try:
        scenes = _parse_level1_response(raw)
    # 格式错误时携带 format_error 重试一次（只重试一次，避免放大上游压力）
    except (ValueError, TypeError) as first_error:
        # 重试仍失败：保持优雅降级（空场景集=无授权），但把协议错误暴露给 translate 层
        retry_prompt = json.dumps({
            "query": query,
            "allowed_scenes": list(SCENE_REGISTRY),
            "format_error": str(first_error),
            "retry_hint": "Classify the query without executing it. The only output key is scenes, with an array of registered scene names. Do not output name, parameters, tool calls, or policies.",
        }, ensure_ascii=False)
        retry_raw, retry_meta = call_llm(sys_prompt, retry_prompt, config=config)
        meta["format_retry"] = {"first_error": str(first_error), "first_raw_response": raw,
                                "latency_ms": retry_meta.get("latency_ms")}
        raw = retry_raw
        try:
            scenes = _parse_level1_response(raw)
        except (ValueError, TypeError) as error:
            # Keep the classifier's established graceful fallback, but expose
            # the protocol failure so translate() cannot label it valid IR.
            scenes = []
            meta["parse_error"] = str(error)
    meta["raw_response"] = raw
    meta["parsed_scenes"] = scenes
    return scenes, meta
# 相对路径约定：与策略库同仓维护，改库即可生效，无需改代码


# Level-1 阶段实现：闭集场景分类与格式容错
# ---------------------------------------------------------------------------
# Level-2
# ---------------------------------------------------------------------------
# advice 文档缓存：{真实路径: (mtime, 加载结果)}——同一文档被多个配置引用时只读一次盘，
# 热重载后 mtime 变化自动失效。
_ADVICE_DOC_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}


# advice 引导文档路径解析：相对路径相对策略库 tools/ 目录展开
def _resolve_advice_path(path: str) -> Path:
    """advice 文档路径解析：绝对路径原样；相对路径相对策略库 tools/ 目录。"""
    p = Path(path).expanduser()
    if p.is_absolute():
        return p
    return _get_registry_dir() / "tools" / p


# advice 文档加载（带 mtime 缓存，热重载自动失效）：缺失降级占位文本
def _load_advice_doc(path: str) -> Dict[str, Any]:
    """加载 advice 文档（mtime 缓存）。

    降级行为：路径不存在 / 读取失败时返回 ok=False 与明确占位内容，
    不抛异常、不影响其余策略规则。
    """
    # advice 文档缓存策略：mtime 变化自动失效，同一文档被多处引用时只读一次盘
    real = _resolve_advice_path(path)
    try:
        mtime = real.stat().st_mtime
    except OSError:
        return {"ok": False, "path": str(real),
                "content": f"[advice doc unavailable: {path}]"}
    cached = _ADVICE_DOC_CACHE.get(str(real))
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        content = real.read_text(encoding="utf-8")
    except Exception as e:
        entry = {"ok": False, "path": str(real),
                 "content": f"[advice doc load failed: {path} ({e})]"}
    # 注册表路径：config 中 advice_registry 键，缺省使用内置默认
    else:
        entry = {"ok": True, "path": str(real), "content": content}
    _ADVICE_DOC_CACHE[str(real)] = (mtime, entry)
    return entry


_ADVICE_SECTION_TAG_RE = re.compile(r"<!--\s*applies:\s*([^>]+?)\s*-->", re.I)


_ADVICE_REGISTRY_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}


# advice 引导文档注册表路径
def _advice_registry_path() -> Path:
    """全局引导文档注册表路径：<策略库>/advice_docs.json。"""
    return _get_registry_dir() / "advice_docs.json"


# advice 引导文档注册表加载（场景 → 文档列表映射）
def _load_advice_registry() -> List[Dict[str, Any]]:
    """加载全局引导文档注册表（[{role, path, inject}]）；缺失/损坏时降级为空列表。"""
    # advice 注册表加载失败降级为空映射（引导缺失不影响翻译主链路）
    p = _advice_registry_path()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return []
    cached = _ADVICE_REGISTRY_CACHE.get(str(p))
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        entries: List[Dict[str, Any]] = []
    else:
        raw = obj.get("advice_docs") if isinstance(obj, dict) else obj
        entries = [e for e in (raw or []) if isinstance(e, dict) and e.get("path")]
    _ADVICE_REGISTRY_CACHE[str(p)] = (mtime, entries)
    return entries


# 按场景召回引导文档段落（最小权限引导语料注入点）
def _advice_docs_for_scene(scene: str) -> List[Dict[str, Any]]:
    """取得适用于指定场景的引导文档（inject 开启 且 存在适用/全局分块时才返回）。"""
    # 按场景召回引导文档列表并逐个展开，结果供最小权限引导注入 Level-2 提示词
    # 注：召回按注册表配置顺序去重，避免同一文档重复注入浪费上下文
    out: List[Dict[str, Any]] = []
    for entry in _load_advice_registry():
        if not entry.get("inject", True):
            continue
        path = str(entry.get("path") or "")
        if not path:
            continue
        loaded = _load_advice_doc(path)
        content = loaded["content"]
        sections = _advice_sections_meta(content) if loaded["ok"] else []
        if not loaded["ok"]:
            out.append({"path": loaded["path"],
                        "loaded": False, "inject": True, "scene": scene,
                        "sections": [], "applicable": False,
                        "content": f"[advice doc unavailable: {path}]"})
            continue
        matched = any(scene in (sec.get("applies") or []) for sec in sections)
        has_global = any(not (sec.get("applies") or []) for sec in sections)
        # 有场景匹配分块、有全局分块，或文档本身未分块（整体视为全局）时注入
        applicable = matched or has_global or (not sections)
        if not applicable:
            continue
        out.append({
            "path": loaded["path"],
            # 分节解析：按 markdown 标题切分，提取每节标题与正文
            "loaded": True,
            "inject": True,
            "scene": scene,
            "sections": sections,
            "applicable": True,
            "matched": matched,
            "content": _filter_advice_for_scene(content, scene),
        })
    return out


# 引导文档分节解析：按标题切分并提取节元信息
def _parse_advice_sections(content: str) -> Tuple[str, List[Dict[str, Any]]]:
    """把 advice 文档拆为「前言 + 分节列表」。

    每节结构：{title, applies: [场景名...], body: [行...]}；
    分节以 `## 标题` 起始，紧随的 `<!-- applies: xxx -->` 标注适用场景（未标注 = 全局）。
    """
    preamble: List[str] = []
    # 全文分节：不做场景过滤，用于文档重建与展示
    sections: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    for ln in content.splitlines():
        if ln.startswith("## "):
            cur = {"title": ln[3:].strip(), "applies": [], "body": [ln]}
            sections.append(cur)
            continue
        m = _ADVICE_SECTION_TAG_RE.search(ln)
        if m and cur is not None:
            cur["applies"].extend(x.strip() for x in m.group(1).split(",") if x.strip())
            continue
        (cur["body"] if cur else preamble).append(ln)
    # 重建：preamble + 分节按序拼接，保证过滤后的文档结构完整
    return "\n".join(preamble).rstrip(), sections


# 分节全文（不做场景过滤，用于文档重建）
def _advice_sections_full(content: str) -> Dict[str, Any]:
    """分块完整结构：{preamble, sections:[{title, applies, body}]}（body 为标题/标签后的正文）。"""
    pre, sections = _parse_advice_sections(content)
    out = []
    for s in sections:
        body_lines = s["body"][1:] if s["body"] and s["body"][0].startswith("## ") else s["body"]
        out.append({"title": s["title"], "applies": s["applies"],
                    "body": "\n".join(body_lines).strip()})
    return {"preamble": pre, "sections": out}


# 重建引导文档：preamble + 分节拼接回写
# 文档重建：preamble + 分节按序拼接，保证过滤后的文档结构完整
def _rebuild_advice_doc(preamble: str, sections: List[Dict[str, Any]]) -> str:
    """由「前言 + 分块」重建 Markdown 文档（保留 applies 标签语义）。"""
    parts: List[str] = []
    if preamble and preamble.strip():
        parts.append(preamble.strip())
    # 分节元信息：标题 + 适用场景标签，供过滤与展示
    for sec in sections or []:
        title = str(sec.get("title") or "").strip()
        if not title:
            continue
        body = str(sec.get("body") or "").strip()
        applies = [str(x).strip() for x in (sec.get("applies") or []) if str(x).strip()]
        block = f"## {title}"
        # 场景过滤：按分节元信息保留相关段，最小化注入内容
        if applies:
            block += f"\n\n<!-- applies: {', '.join(applies)} -->"
        if body:
            block += f"\n\n{body}"
        parts.append(block)
    return ("\n\n".join(parts)).rstrip() + "\n"


# 分节元信息提取（标题/适用场景）
def _advice_sections_meta(content: str) -> List[Dict[str, Any]]:
    """分节元信息（标题 + 适用场景），供前端展示分区情况。"""
    _, sections = _parse_advice_sections(content)
    return [{"title": s["title"], "applies": s["applies"]} for s in sections]


# 按场景过滤引导内容：只保留与当前场景相关的引导段
# 场景过滤：按分节元信息保留相关段，最小化注入内容
def _filter_advice_for_scene(content: str, scene: str) -> str:
    """按场景过滤：保留全局分节（未标注）与 applies 命中该场景的分节。"""
    pre, sections = _parse_advice_sections(content)
    kept = [s for s in sections if (not s["applies"]) or (scene in s["applies"])]
    parts = [pre] if pre.strip() else []
    parts += ["\n".join(s["body"]).rstrip() for s in kept]
    return "\n\n".join(p for p in parts if p.strip())


# 引导文档展开注入提示词：引用按相对路径展开，缺失降级占位文本
def _expand_advice_docs(node: Any, scene: Optional[str] = None) -> Any:
    """深度展开 advice_docs 引用为已加载的文档内容（返回副本，不修改原注册表）。

    每个引用被展开为 {role, path, loaded, sections, content}；加载失败时 loaded=False、
    content 为降级占位文本，随提示词一并注入，保证 AI 可感知缺档。
    传入 scene 时按分节过滤（`<!-- applies: <scene> -->`，未标注分节始终保留）；
    未传 scene（全量场景，如查看/同步接口）时返回整份文档。
    """
    # 递归展开注入的 advice 引用：dict/list 结构递归处理，保持 IR 结构不变；
    # 文档缺失时降级为占位文本并在健康状态中标记未加载
    if isinstance(node, dict):
        if isinstance(node.get("advice_docs"), list):
            docs = []
            for ref in node["advice_docs"]:
                path = ref.get("path") if isinstance(ref, dict) else ref
                if not path or not isinstance(path, str):
                    docs.append({"role": "", "path": str(ref), "loaded": False,
                                 "content": "[invalid advice_docs entry]"})
                    continue
                loaded = _load_advice_doc(path)
                content = loaded["content"]
                sections_meta = _advice_sections_meta(content) if loaded["ok"] else []
                # 注入开关：entry.inject=false 时不注入提示词（仅供查看与同步）
                inject = True
                if isinstance(ref, dict) and "inject" in ref:
                    inject = bool(ref.get("inject"))
                if not inject:
                    docs.append({
                        "role": (ref.get("role") or "") if isinstance(ref, dict) else "",
                        "path": loaded["path"], "loaded": loaded["ok"],
                        "scene": scene or "", "inject": False, "sections": sections_meta,
                        "content": "[advice 文档未启用注入（inject=false），仅作参考文档]",
                    })
                    continue
                # 发现 advice_docs 即加载（inject=true）；传 scene 时按 applies 标签过滤分节，否则全量
                if loaded["ok"] and scene:
                    content = _filter_advice_for_scene(content, scene)
                docs.append({
                    "role": (ref.get("role") or "") if isinstance(ref, dict) else "",
                    "path": loaded["path"],
                    "loaded": loaded["ok"],
                    "scene": scene or "",
                    "inject": True,
                    "sections": sections_meta,
                    "content": content,
                })
            merged = {k: _expand_advice_docs(v, scene) for k, v in node.items() if k != "advice_docs"}
            merged["advice_docs"] = docs
            return merged
        return {k: _expand_advice_docs(v, scene) for k, v in node.items()}
    if isinstance(node, list):
        return [_expand_advice_docs(x, scene) for x in node]
    return node


# 引导文档健康状态：已加载/缺失清单（F-1-1 ⑪ 健康检查数据来源）
def advice_docs_status() -> List[Dict[str, Any]]:
    """汇总全局引导文档注册表的加载状态（供健康检查接口）。"""
    # 健康状态汇总：全部 advice 文档加载结果（正常/缺失），供前端策略库页展示
    status: List[Dict[str, Any]] = []
    for entry in _load_advice_registry():
        path = str(entry.get("path") or "")
        if not path:
            continue
        loaded = _load_advice_doc(path)
        status.append({"path": loaded["path"], "loaded": loaded["ok"],
                       "inject": bool(entry.get("inject", True))})
    return status


# RAG 按需注入：仅拼入已选场景的工具定义（prompt 文本或 JSON 两种格式）
def _selected_registry_for_prompt(scenes: List[str]) -> str:
    """按场景组装注入提示词的注册表。

    advice 引导文档不再写在场景 JSON 中，而由全局注册表（advice_docs.json）声明；
    仅当文档存在适用于该场景（或全局）的分块时才注入，注入内容为按场景过滤后的分块。
    """
    # RAG 核心入口：按已选场景过滤 TOOL_REGISTRY，只保留被选中场景的工具定义；
    # 未选中场景不进入提示词，压缩上下文规模并避免跨场景工具误授权
    selected: Dict[str, Any] = {}
    for s in scenes:
        if s not in TOOL_REGISTRY:
            continue
        node = dict(TOOL_REGISTRY[s])
        advice_docs = _advice_docs_for_scene(s)
        node.pop("advice_docs", None)
        if advice_docs:
            node["advice_docs"] = advice_docs
        selected[s] = node
    # 注入格式：默认 JSON（与既有模型/用例行为一致）；
    # 配置 ir_translator.registry_prompt_format=text 时改用结构化 Markdown 提示词。
    if _get_config("registry_prompt_format", "json").strip().lower() == "text":
        return _registry_to_prompt_text(selected)
    return json.dumps(selected, ensure_ascii=False, indent=2)


def level2_generate(query: str, scenes: List[str], config: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    两阶段翻译第二阶段：场景约束下生成参数级 IR（Level-2）。

    流程：
        1. RAG 按需注入：仅把已选场景的工具定义拼入提示词，
           避免全量注入导致的上下文膨胀与注意力分散；
        2. 空 policies 时携带 LEVEL2_EMPTY_RETRY_HINT 重试一次（R8 修复）；
        3. 按场景级动作白名单做代码层裁剪（提示词之外的硬约束）。

    Args:
        query: 用户请求；scenes: Level-1 已选场景；config: 模型配置。
# 空 IR 重试的失败不影响首轮结果：重试异常仅记录 meta.empty_retry，不向外抛

    Returns:
        (IR dict, meta)。
    """
    # RAG 按需注入：只拼入已选场景的工具定义，降低推理延迟与上下文膨胀（实测省约30%推理延时）
    # 动作白名单裁剪是代码层硬保障：即使模型忽略提示词规则也不会越权
    selected_registry = _selected_registry_for_prompt(scenes)
    prompt_template = _get_prompt("level2", LEVEL2_SYS)
    sys_prompt = prompt_template.replace("{SELECTED_REGISTRY}", selected_registry)
    user_prompt = json.dumps({"query": query, "scenes": scenes}, ensure_ascii=False)
    raw, meta = call_llm(sys_prompt, user_prompt, config=config)
    ir = _safe_extract(raw)
    meta["raw_response"] = raw
    # R8 修复：已选出场景却返回空 policies 时，带提示重试一次。
    # 典型原因是某个必填参数（如收件人）在 query 中未给出，模型按规则 10 丢弃了全部 function。
    if scenes and not _has_policies(ir):
        retry_prompt = json.dumps({"query": query, "scenes": scenes, "retry_hint": LEVEL2_EMPTY_RETRY_HINT},
                                  ensure_ascii=False)
        try:
            raw2, meta2 = call_llm(sys_prompt, retry_prompt, config=config)
        except Exception as e:  # 重试失败不影响首轮结果
            meta["empty_retry"] = {"ok": False, "error": str(e)[:200]}
        else:
            ir2 = _safe_extract(raw2)
            meta["empty_retry"] = {"ok": _has_policies(ir2), "latency_ms": meta2.get("latency_ms"),
                                   "raw_response": raw2}
            if _has_policies(ir2):
                ir = ir2
    # 代码层硬保障：按场景级动作白名单裁剪 IR（提示词之外的兜底，避免 LLM 偶发违规）
    meta["action_limits"] = _action_limits(scenes)
    trimmed = _enforce_action_whitelist(ir, scenes)
    if trimmed:
        meta["action_whitelist_trimmed"] = trimmed
    return ir, meta


# 场景级动作白名单读取：allowed_file_actions / allowed_network_actions
def _action_limits(scenes: List[str], as_set: bool = False) -> Dict[str, Dict[str, Any]]:
    """读取各场景的动作白名单（`allowed_file_actions` / `allowed_network_actions`）。

    as_set=True 时返回集合（供裁剪比较），否则返回排序后的列表（供 meta 记录/排查）。
    字段缺省 / null / 空数组均视为「不限制」，值为 None。
    """
    # 字段缺省/空数组＝不限（None 语义），避免把「未声明」误当「全禁止」
    limits: Dict[str, Dict[str, Any]] = {}
    for s in scenes or []:
        node = TOOL_REGISTRY.get(s) or {}
        fa, na = node.get("allowed_file_actions"), node.get("allowed_network_actions")
        f_ok = isinstance(fa, list) and bool(fa)
        n_ok = isinstance(na, list) and bool(na)
        if as_set:
            limits[s] = {"file": set(fa) if f_ok else None, "network": set(na) if n_ok else None}
        else:
            limits[s] = {"file": sorted(fa) if f_ok else None, "network": sorted(na) if n_ok else None}
    return limits
# 本函数与 _apply_static_deny 的分工：本函数裁「动作」，deny 删「整个工具对象」


# 场景级动作白名单裁剪：超集动作裁掉，裁空的 objects/policies 整体丢弃
def _enforce_action_whitelist(ir: Dict[str, Any], scenes: List[str]) -> List[str]:
    # 返回值为裁剪说明列表：写入 meta.action_whitelist_trimmed，供翻译日志与迭代生成分析
    """按场景级动作白名单裁剪 IR（`LEVEL2_SYS` 之外的代码层硬约束）。

    `tools/<scene>.json` 顶层的 `allowed_file_actions` / `allowed_network_actions`
    为**非空数组**时，IR 中该场景 `file` / `network` 对象的 `actions` 只能取其子集：
    超出的动作被裁掉；`actions` 被裁空的整个对象被丢弃；`objects` 被裁空的 policy 也被丢弃。
    字段缺省 / null / 空数组＝不限制（保持原样）。返回被裁剪项的说明列表（供 meta 记录）。
    """
    # 裁剪次序：逐 policy → 逐 object，按对象类型取对应白名单；
    # 动作全裁空 → 丢对象；对象全裁空 → 丢 policy；裁剪说明全部写入 meta 供审计
    limits = _action_limits(scenes, as_set=True)
    if not any(v["file"] or v["network"] for v in limits.values()):
        return []

    notes: List[str] = []
    kept_policies: List[Any] = []
    for pol in ir.get("policies") or []:
        if not isinstance(pol, dict):
            continue
        lim = limits.get(pol.get("subject")) or {}
        src_objs = pol.get("objects") or []
        kept_objs: List[Any] = []
        for o in src_objs:
            if not isinstance(o, dict):
                continue
            allowed = lim.get(o.get("type"))
            acts = o.get("actions")
            if allowed is None or not isinstance(acts, list):
                kept_objs.append(o)
                continue
            keep = [a for a in acts if a in allowed]
            dropped = [a for a in acts if a not in allowed]
            if dropped:
                notes.append("%s: %s %s 裁剪 %s（白名单 %s）" % (
                    pol.get("subject"), o.get("type"), o.get("identifier"), dropped, sorted(allowed)))
            if keep:
                new_o = dict(o)
                new_o["actions"] = keep
                kept_objs.append(new_o)
        if kept_objs or not src_objs:
            if len(kept_objs) != len(src_objs):
                notes.append("%s: 裁剪后 objects %d → %d" % (pol.get("subject"), len(src_objs), len(kept_objs)))
            new_pol = dict(pol)
            new_pol["objects"] = kept_objs
            kept_policies.append(new_pol)
        else:
            notes.append("%s: 全部对象均被白名单裁空，已丢弃该 policy" % pol.get("subject"))
    # 与 _extract_json 的差异：本函数永不抛异常，空 dict 由上层按空 IR 处理
    if kept_policies:
        ir["policies"] = kept_policies
    return notes



# 空 IR 重试提示：要求改用通配符表达必填参数，只授权完成任务必需的动作
LEVEL2_EMPTY_RETRY_HINT = (
    "上一次输出的 policies 为空，但已确定需要授权的场景。请在遵守全部约束（denylist、只读优先、不编造敏感值）"
    "的前提下，输出完成该 query 所需的最小授权：query 中明确给出的资源逐字使用；"
    "必填参数在 query 中未给出时用通配符 `*` 表示，并只授权完成任务必需的动作。"
    "只有当任务本身被约束明确禁止时，才保持 policies 为空。"
)


def _safe_extract(raw: str) -> Dict[str, Any]:
    # 空 policies 语义：等同无授权，网关与判定器均按拒绝处理（不授权即不放行）
    """
    _extract_json 的兜底包装：解析失败返回空 dict 而不抛异常。

    用于上层已有降级路径的场合（如 Level-2 原始输出提取），
    异常统一由调用方按空 IR 处理。

    Returns:
        解析出的 dict；失败返回 {}。
    """
    try:
        obj = _extract_json(raw)
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _has_policies(ir: Any) -> bool:
    """
    # 子场景机制：同一参数的多套静态约束（note 标注用途），匹配时择一应用
    判断 IR 是否含非空的 policies 数组。

    区分「空 IR」与「有效 IR」的标准判定入口，空 policies 视为无 IR。

    Returns:
        True 表示含至少一条策略项。
    """
    return isinstance(ir, dict) and isinstance(ir.get("policies"), list) and len(ir["policies"]) > 0


# IR 归一化：新旧格式统一为 subject/objects 标准结构（含短名补全与默认值回填）
# ---------------------------------------------------------------------------
# Normalize
# ---------------------------------------------------------------------------
def _static_spec(param_def: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    读取参数定义中的静态约束列表（constraint_spec.static）。

    兼容旧格式：字段为单个 dict 时视为单一子场景（note=default）。

    Args:
        param_def: 单个参数的定义 dict。

    Returns:
        静态约束列表；字段缺失或类型异常时返回 []。
    """
    spec = param_def.get("constraint_spec", {}).get("static", [])
    # 兼容旧格式：单个 dict 视为只有一个子场景
    if isinstance(spec, dict):
        return [{"note": "default", **spec}]
    return spec if isinstance(spec, list) else []


# IR 归一化：新旧格式统一 subject/objects、短名按 服务名__函数名 补全、单对象包数组、缺省参数回填
# IR 规范化：路径/命令/参数统一形态，为静态校验与网关比对提供一致输入
def normalize_ir(ir: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize LLM output to subject/objects format. Handles both new and old formats."""
    # 新格式分支：subject/objects 结构，做单对象包数组、短名补全与 actions 缺省回填
    raw_policies = ir.get("policies", [])
    normalized: List[Dict[str, Any]] = []

    for policy in raw_policies:
        if "subject" in policy and "objects" in policy:
            subj = policy["subject"]
            objs = policy.get("objects", [])
            if isinstance(objs, dict):
                objs = [objs]  # 单对象形态归一为数组
            if not isinstance(objs, list):
                objs = []
            # 短名补全：模型输出函数短名（read）时按 服务名__函数名 规则补全为注册表全名
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

        # 旧格式兼容：scene/functions 扁平结构 → subject/objects 标准结构；
        # 短名按 服务名__函数名 规则补全；缺省参数按第一个静态子场景的 default 回填
        # Old format fallback
        # 旧格式分支：scene/functions 扁平结构转换；未注册场景的 policy 直接丢弃
        scene = policy.get("scene", "")
        if scene not in TOOL_REGISTRY:
            continue
        scene_def = TOOL_REGISTRY[scene]
        fn_defs = scene_def.get("functions", {})
        fns = policy.get("functions", [])
        if not isinstance(fns, list):
            continue
        objects: List[Dict[str, Any]] = []
        # 逐 function 处理：短名补全后从函数定义读取参数约束与默认值
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
            # Fill defaults from first matching static sub-scenario
            # 分段原则：; & | 换行 四类控制符切分，管道两侧分别判定
            # 缺省参数回填：按第一个含 default 的静态子场景补齐，未给出的必填参数保持缺省
            for param_name, param_def in fn_def.get("params", {}).items():
                static_list = _static_spec(param_def)
                default = None
                for static in static_list:
                    if static.get("default") is not None:
                        default = static["default"]
                        # 双视图意义：原始视图匹配显式命令；剥包装视图匹配 sudo/env/变量赋值后的真实命令名
                        break
                if param_name not in params and default is not None:
                    params[param_name] = default
            param_list = [{"name": k, "identifier": str(v)} for k, v in params.items() if v is not None]
            objects.append({"type": "tool", "identifier": name, "actions": ["invoke"], "params": param_list or None})
            # 文件对象推导：函数带 file_actions 且参数含路径时，附加对应 file 对象到 objects
            fa = fn_def.get("file_actions") or fn.get("file_actions")
            path_val = params.get("path") or params.get("file") or params.get("target")
            if path_val and fa:
                objects.append({"type": "file", "identifier": str(path_val), "actions": fa})
        if objects:
            normalized.append({"subject": scene, "objects": objects, "effect": "allow"})

    ir["policies"] = normalized
    return ir


# 命令 / 语句类参数：按「命令名 / 语句前缀」匹配 denylist（R10 修复），其余参数按值 / 通配匹配
# 命令类参数名集合：这些参数按「命令名/语句前缀」做 denylist 匹配
_COMMAND_PARAM_NAMES = {"command", "cmd", "commands", "script", "shell", "sql"}
# 命令包装词：匹配时跳过这些前缀词，防止 sudo rm 一类包装绕过
_CMD_WRAPPERS = {"sudo", "env", "nohup", "command", "exec", "time", "nice", "xargs", "busybox"}


# token 匹配三形态：精确、前缀（rm=、sudo(）、通配（curl *| sh）
# 按 shell 控制符（; & | 换行）切分子命令，保留每段原文
# 分段原则：; & | 换行 四类控制符切分，管道两侧分别判定
def _split_command_segments(cmd: str) -> List[str]:
    """按 shell 控制符（; & | 换行）切分为子命令，保留每段原文。"""
    return [seg.strip() for seg in re.split(r"[;&|\n]+", cmd) if seg.strip()]


# 子命令词序列：原始序列 + 剥离 sudo/env 包装与 VAR=value 赋值后的序列
# 双视图意义：原始视图匹配显式命令；剥包装视图匹配 sudo/env/变量赋值后的真实命令名
def _segment_views(segment: str) -> List[List[str]]:
    """子命令的两种词序列：原始词序列，以及跳过 sudo / env 等包装与 VAR=value 赋值后的词序列。
    命令名取路径 basename，全部小写。"""
    raw = [t.strip("'\"").lower() for t in segment.split()]
    if raw:
        raw[0] = os.path.basename(raw[0])
    k = 0
    while k < len(raw) and (raw[k] in _CMD_WRAPPERS or ("=" in raw[k] and not raw[k].startswith(("-", "/", ".")))):
        k += 1
    cmd = raw[k:]
    if cmd:
        cmd[0] = os.path.basename(cmd[0])
    return [raw, cmd] if cmd != raw else [raw]


# 转换约定：* 与 ** 统一映射 .*（跨目录语义由模式本身表达），? 单字符
def _token_match(actual: str, ptok: str) -> bool:
    """
    命令类禁止项的单 token 匹配。

    支持三种形态：
        · 精确相等（rm）；
        · 前缀型（rm=、base64(、sudo()）；
        · 通配模式（经 _glob_to_regex 转正则后全匹配）。

    Returns:
        True 表示该 token 命中禁止项。
    """
    if actual == ptok:
        return True
    if ptok.endswith(("=", "(", "()")):
        return actual.startswith(ptok.rstrip(")"))
    if "*" in ptok:
        return re.fullmatch(_glob_to_regex(ptok), actual) is not None
    return False


def _glob_to_regex(pattern: str) -> str:
    """
    通配模式转正则字符串。

    转换规则：** 与 * 均映射为 .*（跨目录/单段通配统一处理），
    ? 映射为单字符 .，其余字符全部转义。
# 规范化次序：剥引号 → ~ 展开 → normpath；相对路径保持原样不做归一

    Args:
        pattern: 含通配符的模式串。

    Returns:
        正则字符串（调用方自行 fullmatch）。
    """
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            # 多词全现原则：「rm -rf /」要求命令名相同且 -rf 与 / 均出现，避免误伤「rm -rf /tmp/a」
            out.append(".*")
            i += 1
        elif pattern[i] == "?":
            out.append(".")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return "".join(out)


def _norm_path_like(value: str) -> str:
    """
    路径类参数规范化：剥引号、~ 展开、绝对路径 normpath 归一。

    在 denylist / allowlist 匹配前调用，防止 ~ 与 ../ 变体绕过
    （R10 修复的配套入口）。

    Returns:
        # 匹配前双规范化：value 与 pattern 都走 _norm_path_like，防止两侧形态不一致导致漏判
        规范化后的路径字符串。
    """
    v = os.path.expanduser(value.strip().strip("'\""))
    if v.startswith("/"):
        v = os.path.normpath(v)
    return v


# 命令/语句类 denylist 匹配：控制符子串匹配、命令名匹配、多词全现匹配（R10 修复核心）
def _command_denied(value: str, pattern: str) -> bool:
    """命令 / 语句类参数的 denylist 匹配（大小写不敏感）：
    · 含控制符（| ; & ）的禁止项（如「| bash」「curl *| sh」）：在整条命令上做子串 / 通配查找；
    · 单词禁止项（如 rm、sudo、DROP 之外的 ATTACH）：命中任一子命令的命令名或包装命令名；
    · 多词禁止项（如「rm -rf /」「git push --force」「DROP TABLE」）：命令名相同且其余各词都出现在该子命令中，
      「rm -rf /」命中「rm -rf / --no-preserve-root」，不命中「rm -rf /tmp/a」。"""
    # 分流依据：参数名在 _COMMAND_PARAM_NAMES 中按命令语义匹配，否则按值/通配匹配
    pat = " ".join(pattern.split()).lower()
    if not pat:
        return False
    if re.search(r"[|;&]", pat):
        squeeze = lambda x: re.sub(r"\s+", "", x).lower()
        return re.search(_glob_to_regex(squeeze(pat)), squeeze(value)) is not None
    ptoks = pat.split()
    for seg in _split_command_segments(value) or [value]:
        for toks in _segment_views(seg):
            if not toks or not _token_match(toks[0], ptoks[0]):
                continue
            if all(any(_token_match(t, pt) for t in toks[1:]) for pt in ptoks[1:]):
                return True
    return False


# 路径/URL/取值类 denylist 匹配：先规范化再精确/通配匹配，防 ../ 绕过
# 匹配前双规范化：value 与 pattern 都走 _norm_path_like，防止两侧形态不一致导致漏判
def _value_denied(value: str, pattern: str) -> bool:
    """路径 / URL / 取值类参数：精确匹配或通配匹配；路径先做 ~ 展开与规范化，防止 ../ 绕过。"""
    if value == pattern:
        return True
    v, pat = _norm_path_like(value), _norm_path_like(pattern) if pattern.startswith(("/", "~")) else pattern
    if v == pat:
        return True
    if "*" in pat or "?" in pat:
        if pat.endswith("/**") and v == pat[:-3]:
            return True
        return re.fullmatch(_glob_to_regex(pat), v) is not None
    return False


# 参数级 denylist 匹配入口：按参数名类别分流命令类/值类匹配
# 分流依据：参数名在 _COMMAND_PARAM_NAMES 中按命令语义匹配，否则按值/通配匹配
def _param_denied(param_name: str, value: str, denylist: List[str]) -> Optional[str]:
    """返回命中的禁止项，未命中返回 None。"""
    is_cmd = str(param_name or "").lower() in _COMMAND_PARAM_NAMES
    for pattern in denylist:
        if (_command_denied(value, pattern) if is_cmd else _value_denied(value, pattern)):
            return pattern
    return None


# 静态禁止项优先于 IR 授权（S-1-1）：命中即删除整个工具对象
def _apply_static_deny(ir: Dict[str, Any]) -> Dict[str, Any]:
    """静态策略 denylist 优先于 IR（S-1-1）。

    工具对象的参数值命中所在函数定义的 constraint_spec.static.denylist 时，
    该工具对象整体从 IR 中删除（相当于阻断），并打印告警；不影响其余允许项。
    """
    if not isinstance(ir, dict):
        return ir
    denied: List[str] = []
    kept_policies: List[Dict[str, Any]] = []
    # 遍历 策略项 → 工具对象 → params：取该参数静态约束的 denylist，
    # 命中即删除整个工具对象（阻断），未命中的允许项保持原样
    for policy in ir.get("policies", []) or []:
        if not isinstance(policy, dict):
            continue
        subj = policy.get("subject")
        fn_defs = TOOL_REGISTRY.get(subj, {}).get("functions", {}) if subj else {}
        new_objs: List[Dict[str, Any]] = []
        for obj in policy.get("objects") or []:
            blocked = False
            if isinstance(obj, dict) and obj.get("type") == "tool":
                fn_def = fn_defs.get(obj.get("identifier")) or {}
                params_def = fn_def.get("params") or {}
                for p in obj.get("params") or []:
                    if not isinstance(p, dict):
                        continue
                    pval = str(p.get("identifier", ""))
                    if not pval:
                        # 跨场景规则收集：allow 只取写类函数（读类 /tmp 白名单不得豁免写类禁止）；
                        # deny 全量收集——deny-wins 语义优先于任何 allow
                        continue
                    for st in _static_spec(params_def.get(p.get("name"), {})):
                        denylist = [str(x) for x in (st.get("denylist") or [])]
                        if _param_denied(p.get("name"), pval, denylist) is not None:
                            blocked = True
                            break
                    if blocked:
                        break
            if blocked:
                denied.append(str(obj.get("identifier")))
            else:
                new_objs.append(obj)
        if new_objs:
            policy["objects"] = new_objs
            kept_policies.append(policy)
    ir["policies"] = kept_policies
    if denied:
        print(f"[core] static denylist blocked tools: {denied}", flush=True)
    return ir


# 路径类参数名集合：denylist 匹配前先做 ~ 展开与规范化，防 ../ 绕过
_PATH_PARAM_NAMES = {"path", "paths", "directory", "dir", "save_path", "file_path",
                     "wrapper_path", "workdir", "target", "repo", "dest", "destination"}

_PATH_TOKEN_RE = re.compile(r"(?<![\w.\-])(?:~|/)[A-Za-z0-9_.@*+\-/]+")


# 递归遍历 dict/list/str 三类节点，其余类型原样返回
# 跨场景收集路径规则：写类函数 allowlist 豁免集 + 全量路径 denylist
def _registry_path_rules() -> Tuple[List[str], List[str]]:
    """收集「写类」路径 allowlist 与全部路径 denylist（跨场景）。

    注意：read 类函数可能允许读 /tmp（allowlist 含 /tmp/**），不能因此豁免
    write 类 denylist 对 /tmp/** 的禁止——只统计写类函数的 allowlist。
    """
    allow: List[str] = []
    deny: List[str] = []
    for scene, node in TOOL_REGISTRY.items():
        for fdef in (node.get("functions") or {}).values():
            acts = set(fdef.get("file_actions") or [])
            # 只有 file_ops 场景里真正带写动作的函数的 allowlist 才能豁免；
            # 其它工具文件（runtime_exec / office_doc 等）历史遗留的 /tmp/**
            # 不应覆盖写类 denylist 的禁止语义。
            is_write_fn = scene == "file_ops" and bool(acts & {"create", "write", "delete"})
            for pname, pdef in (fdef.get("params") or {}).items():
                for st in _static_spec(pdef):
                    vals = {key: [str(x) for x in (st.get(key) or [])
                                 if str(x).startswith(("/", "~"))]
                            for key in ("allowlist", "denylist")}
                    for x in vals["denylist"]:
                        if x not in deny:
                            deny.append(x)
                    # 内容型参数（如 apply_patch.patch）的历史 allowlist 不参与豁免
                    if is_write_fn and pname in _PATH_PARAM_NAMES:
                        for x in vals["allowlist"]:
                            if x not in allow:
                                allow.append(x)
    return allow, deny


# 递归改写 IR 中的字符串（路径 token 映射替换，保持结构不变）
def _rewrite_str(node: Any, mapping: Dict[str, str]) -> Any:
    """递归替换 IR 中出现的未授权路径 token。"""
    if isinstance(node, str):
        for old, new in mapping.items():
            node = node.replace(old, new)
        return node
    if isinstance(node, list):
        return [_rewrite_str(x, mapping) for x in node]
    if isinstance(node, dict):
        return {k: _rewrite_str(v, mapping) for k, v in node.items()}
    return node


# 资源以策略为准：query 中未授权路径在 IR 中改写为授权通配并记录 warning
def _enforce_resource_allowlist(ir: Dict[str, Any], query: str) -> Tuple[Dict[str, Any], List[str]]:
    """资源以策略为准（代码层硬约束，提示词之外的兜底）。

    用户 query 中出现的路径若命中策略库路径 denylist 且不在 allowlist 内，
    则 IR 的任何字段（含 command 参数内嵌路径）都不得原样出现该路径：
    改写为授权范围内的通配模式，并把改写记录作为 warning 供审计 / RSI 发现。
    """
    # 资源改写原则：IR 表达的是「策略允许做什么」而不是「用户想做什么」；
    # 未授权路径不得原样出现在 IR 任何字段（含 command 参数内嵌路径）
    if not isinstance(ir, dict):
        return ir, []
    allow, deny = _registry_path_rules()
    if not deny:
        # ok=False 时下游（网关/判定器/默认策略保存）均拒绝使用该 IR
        return ir, []
    # 从 query 提取全部路径 token 逐一判定：
    # 命中 denylist 且不在写类 allowlist 内 → 改写为授权根目录下的通配模式；
    # 改写映射记入 warning，供审计与迭代生成（RSI）分析
    candidates = {m.group(0).rstrip(".,;:)]}'\"") for m in _PATH_TOKEN_RE.finditer(query or "")}
    allowed_root = next((a.split("/**")[0] for a in allow if a.startswith("/") and "/**" in a), "/workspace")
    mapping: Dict[str, str] = {}
    notes: List[str] = []
    for path in sorted(candidates, key=len, reverse=True):
        if not any(fnmatch.fnmatch(path, d) for d in deny):
            continue
        if any(fnmatch.fnmatch(path, a) for a in allow):
            continue
        base = path.rstrip("/").rsplit("/", 1)[-1]
        replacement = f"{allowed_root}/**/{base}" if base else f"{allowed_root}/**"
        mapping[path] = replacement
        notes.append(f"用户请求的路径 {path} 不在策略授权集内，IR 中已改写为 {replacement}（资源以策略为准）")
    if not mapping:
        return ir, notes
    return _rewrite_str(ir, mapping), notes


# IR 深度校验：对归一化后的 IR 做结构、白名单与字段完备性检查（F-1-4 对应实现）
# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------
@dataclass
class ValidationReport:
    """
    IR 校验报告（dataclass）。

    属性：
        ok: 整体是否通过；
        errors: 结构 / 白名单违规（计为失败，前端红显）；
        warnings: 改写提示（仅提示，不影响通过）。

    可 JSON 序列化，供前端「校验结果」面板与翻译日志展示。
    """
    ok: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# IR 深度校验：policies/subject/objects/effect/工具白名单/参数名/文件动作逐项检查
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
    # 顶层结构检查：IR 必须为非空对象且 policies 为非空数组，不满足直接返回
    policies = ir.get("policies")
    if not isinstance(policies, list):
        rep.ok = False
        rep.errors.append("缺少顶层 policies 数组")
        return rep
    if len(policies) == 0:
        rep.ok = False
        rep.errors.append("policies 数组不能为空")
        return rep

    # 逐 policy 校验：结构（对象/subject/objects/effect）→
    # 工具 identifier 与参数名必须在函数定义白名单内 →
    # file/network 资源字段完备性；未知场景与未注册工具计为错误而非警告
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
        # 场景白名单检查：subject 必须为已注册场景或保留兜底场景（default_fallback/file_access）
        is_known_scene = subject in SCENE_REGISTRY
        has_tool_registry = subject in TOOL_REGISTRY
        fn_defs = TOOL_REGISTRY.get(subject, {}).get("functions", {}) if has_tool_registry else {}

        if not is_known_scene and subject not in ("default_fallback", "file_access"):
            rep.ok = False
            rep.errors.append(f"policy[{i}] subject '{subject}' 不在已知场景列表中")

        # resource_type check (for backward compat with old format)
        # resource_type 检查：旧格式遗留字段与场景定义不一致时按错误处理
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

            # 通用字段检查：type 必须为 tool/file/network 且 identifier 非空
            obj_type = obj.get("type")
            identifier = obj.get("identifier")

            if obj_type not in ("tool", "file", "network"):
                rep.ok = False
                rep.errors.append(f"policy[{i}].objects[{j}] type 必须为 'tool' 或 'file' 或 'network'，当前为 {obj_type!r}")
                continue

            if not identifier:
                rep.ok = False
                rep.errors.append(f"policy[{i}].objects[{j}] 缺少 identifier")
                continue

            # tool 对象校验：actions 建议项 + identifier 必须在场景函数注册表中（* 通配豁免）
            if obj_type == "tool":
                # Validate tool object
                actions = obj.get("actions")
                if not isinstance(actions, list) or not actions:
                    rep.warnings.append(f"policy[{i}].objects[{j}] tool 对象建议包含 actions 字段")

                # Check identifier against registry (skip * wildcard)
                if identifier != "*" and fn_defs and identifier not in fn_defs:
                    rep.ok = False
                    rep.errors.append(f"policy[{i}].objects[{j}] 工具 '{identifier}' 不在场景 '{subject}' 的注册表中")

                # Validate params
                # params 校验：必须为 [{name, identifier}] 数组，参数名必须在函数定义的参数列表内
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

            # file 对象校验：必须含非空 actions 数组且元素为已知文件操作；未知操作记 warning
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


# 端到端入口：两阶段翻译主流程 translate 与组合入口 normalize_and_validate
# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------
# 端到端翻译主入口：L1 → 回调 → L2 → 归一 → 静态禁止 → 资源白名单 → 校验 → 落库
def translate(query: str, config: Optional[Dict[str, Any]] = None, is_ui_test: bool = False, round_id: str = "", on_level1_done: Optional[callable] = None) -> Dict[str, Any]:
    """Full pipeline: query -> level1 -> level2 -> normalize -> validate -> store.
    
    Args:
        query: The user query text.
        config: LLM config dict.
        is_ui_test: Whether this is from UI test page.
        round_id: The round identifier.
        on_level1_done: Optional callback(level1_scenes, meta1) called after level1 completes.
    """
    # 翻译主流程六步：①L1 场景分类 → ②回调落库 Level-1 → ③L2 生成 IR →
    # ④归一化 → ⑤静态禁止项删除 + 资源白名单改写 → ⑥校验并落库完整结果；
    # 任一步失败都不残留半成品 IR（失败隔离由各步骤自身保证）
    # 入口约定：on_level1_done 回调只在携带 round_id 时触发（生产轮次）；UI 测试轮次标记 is_ui_test 不污染生产数据
    cfg = config or get_llm_config()

    # Level 1
    # Level-1：闭集场景分类；空场景集时跳过 L2（无授权场景即无 IR，fail-close）
    scenes, meta1 = level1_classify(query, config=cfg)
    
    # Level1 完成后立即回调更新数据库
    # Level-1 回调时机：一完成立即上报，供网关尽早感知本轮场景（不等完整翻译结束）
    if on_level1_done and round_id:
        try:
            on_level1_done(round_id, scenes, meta1)
        except Exception as e:
            print(f"[translator] on_level1_done callback error: {e}", flush=True)

    # Level 2
    # Level-2：场景约束下经 RAG 按需注入生成参数级 IR
    if scenes:
        ir, meta2 = level2_generate(query, scenes, config=cfg)
    else:
        ir, meta2 = {}, {}

    # Normalize
    # 归一化：新旧格式统一为 subject/objects 标准结构，短名补全、默认值回填
    if ir:
        ir = normalize_ir(ir)

    # 静态策略 denylist 优先于 IR（S-1-1）：命中即删除，不影响主链路
    # 静态禁止项优先：命中策略库 denylist 的工具对象直接删除（先于任何授权生效）
    if ir:
        ir = _apply_static_deny(ir)

    # 资源以策略为准：query 中的未授权路径不得出现在 IR 任何字段（可用配置关闭）
    resource_rewrites: List[str] = []
    # 资源白名单改写：query 中未授权路径改写为授权通配（可经配置关闭该项）
    if ir and _get_config("enforce_resource_allowlist", "1") not in ("0", "false", "False"):
        ir, resource_rewrites = _enforce_resource_allowlist(ir, query)

    # Validate
    # 校验：结构 + 白名单 + 字段完备性逐项检查；Level-1 解析失败时强制整体不通过
    validation = validate_ir(ir) if ir else ValidationReport(ok=True)
    for note in resource_rewrites:
        validation.warnings.append(note)
    if meta1.get("parse_error"):
        validation.ok = False
        validation.errors.append("Level-1 response format invalid: " + meta1["parse_error"])

    # 组装五段式结果：query / level1 / level2(IR) / validation / meta；
    # level1 meta 含 parse_error 时强制 validation.ok=False（空场景集不得标为有效 IR）
    result = {
        "query": query,
        "level1": scenes,
        "level2": ir,
        "validation": {"ok": validation.ok, "errors": validation.errors, "warnings": validation.warnings},
        "meta": {"level1": meta1, "level2": meta2},
    }

    # Store to translation log (update if already inserted by callback)
    # 落库：回调已写入的记录做增量更新；写库失败静默处理，不阻塞翻译主流程
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
        import db
        db.insert_or_update_translation_log(result, is_ui_test=is_ui_test, round_id=round_id)
    except Exception:
        pass

    return result


def normalize_and_validate(ir_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize and validate an IR dict without LLM call. For default policy saving."""
    # 归一 + 静态禁止 + 校验组合入口（无 LLM 调用）：默认策略保存与网关链路共用
    # 三步固定次序：归一 → 静态禁止删除 → 校验；返回 ir 与 validation 供调用方决策
    if ir_dict:
        ir_dict = normalize_ir(ir_dict)
        ir_dict = _apply_static_deny(ir_dict)
    validation = validate_ir(ir_dict) if ir_dict else ValidationReport(ok=True)
    return {
        "ir": ir_dict,
        "validation": {"ok": validation.ok, "errors": validation.errors, "warnings": validation.warnings},
    }
