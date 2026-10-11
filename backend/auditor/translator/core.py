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
import os
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



_DEFAULT_REGISTRY_DIR = Path(__file__).resolve().parent / "policies" / "default" / "policy_registry"


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


DEFAULT_LLM_TIMEOUT = 180


def get_llm_config() -> Dict[str, Any]:
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
def load_scene_registry() -> Dict[str, Any]:
    """加载场景注册表；缺失/非法时降级为空集合并告警，不阻断主链路。"""
    try:
        with open(REGISTRY_DIR / "scenes.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[core] load_scene_registry degraded (dir={REGISTRY_DIR}): {e}", flush=True)
        return {}


def load_tool_registry() -> Dict[str, Any]:
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


def registry_file_errors(registry_dir: Any) -> List[str]:
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
            }
        except Exception as e:
            last_err = e
            if attempt < max_retry:
                # 上游限流（429）按 Retry-After / 更长退避等待（R7 修复），其余错误保持 1.5 的指数退避
                time.sleep(rate_wait if rate_wait is not None else 1.5 ** attempt)
    raise RuntimeError(f"LLM 调用失败（共 {max_retry + 1} 次）: {last_err}")


RATE_LIMIT_BASE_WAIT = 5.0
RATE_LIMIT_MAX_WAIT = 30.0


def _rate_limit_wait(resp: Any, attempt: int) -> float:
    """429 退避时长：优先采用 Retry-After（秒），否则 5 s × 2^attempt，上限 30 s。"""
    try:
        ra = float((resp.headers or {}).get("Retry-After", ""))
    except (TypeError, ValueError, AttributeError):
        ra = 0.0
    return min(max(ra, RATE_LIMIT_BASE_WAIT * (2 ** attempt)), RATE_LIMIT_MAX_WAIT)


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


def _extract_json(text: str) -> Dict[str, Any]:
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
- objects 数组中每个对象必须包含：`type`（"tool"、"file" 或（和） "network"）、`identifier`（工具函数名、文件路径或网络地址）。
- 对于 type="tool" 的对象：
  - `identifier` 必须逐字等于 function 定义 JSON 中的 key（如 "read"、"safe_file_reader__read_text"）。
  - `actions` 固定为 ["invoke"]。
  - `params` 为数组格式：[{"name": "参数名", "identifier": "参数值"}]，只能使用 function 定义中声明过的参数名。
- 对于 type="file" 的对象：
  - `identifier` 为文件路径（来自用户 query 或工具参数中的路径）。
  - `actions` 为允许的文件操作列表，为允许的文件操作列表，为一个数组，元素为字符串，仅可在"read"、"write"、"delete"、"create"选择
- 对于 type="network" 的对象：
  - `identifier` 为网络地址（如 "http://example.com/api"、"https://*.example.com/*"），可使用通配符/正则匹配域名或路径。
  - `actions` 为允许的网络操作列表，只能从以下选项中选择（可多选）：
    - `send`：发送数据到该地址
    - `receive`：从该地址接收数据
  - 示例：`"actions": ["send"]` 或 `"actions": ["send", "receive"]`。
- 不得输出任何额外解释、注释或 Markdown。

关键规则：
1. 场景内全覆盖：对于每个已选 scene，必须列出所有可能被 Agent 调用的 function 作为 tool 对象。不要只输出一个——Agent 可能通过多种工具路径完成同一任务。
2. 文件资源按需声明：当完成任务确实需要访问该文件时，才生成 type="file" 对象。若无文件访问必要，尽可能减少文件权限。
3. 网络资源按需声明：当完成任务确实需要网络通信时，才生成 type="network" 对象。若无网络访问必要，尽可能减少网络权限。
4. identifier 必须逐字等于 function 定义 JSON 中的 key；不得使用别名或自然语言。
5. params 值来源优先级：用户 query 明确给出 > 已验证上下文 > constraint_spec.static.default。对模棱两可的输入可留空字符串，但能从 query 明确提取的值不要留空。
6. 必须遵守 function 的 desc、constraint_spec.dynamic_ai_hint、static.allowlist/denylist 等约束。
7. 对于 allowed_values 非空的参数，值必须从中选择。
8. 对于高风险能力（shell、privilege 等），优先生成只读/查询权限。
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
# advice 文档缓存：{真实路径: (mtime, 加载结果)}——同一文档被多个配置引用时只读一次盘，
# 热重载后 mtime 变化自动失效。
_ADVICE_DOC_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def _resolve_advice_path(path: str) -> Path:
    """advice 文档路径解析：绝对路径原样；相对路径相对策略库 tools/ 目录。"""
    p = Path(path).expanduser()
    if p.is_absolute():
        return p
    return _get_registry_dir() / "tools" / p


def _load_advice_doc(path: str) -> Dict[str, Any]:
    """加载 advice 文档（mtime 缓存）。

    降级行为：路径不存在 / 读取失败时返回 ok=False 与明确占位内容，
    不抛异常、不影响其余策略规则。
    """
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
    else:
        entry = {"ok": True, "path": str(real), "content": content}
    _ADVICE_DOC_CACHE[str(real)] = (mtime, entry)
    return entry


_ADVICE_SECTION_TAG_RE = re.compile(r"<!--\s*applies:\s*([^>]+?)\s*-->", re.I)


_ADVICE_REGISTRY_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}


def _advice_registry_path() -> Path:
    """全局引导文档注册表路径：<策略库>/advice_docs.json。"""
    return _get_registry_dir() / "advice_docs.json"


def _load_advice_registry() -> List[Dict[str, Any]]:
    """加载全局引导文档注册表（[{role, path, inject}]）；缺失/损坏时降级为空列表。"""
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


def _advice_docs_for_scene(scene: str) -> List[Dict[str, Any]]:
    """取得适用于指定场景的引导文档（inject 开启 且 存在适用/全局分块时才返回）。"""
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
            "loaded": True,
            "inject": True,
            "scene": scene,
            "sections": sections,
            "applicable": True,
            "matched": matched,
            "content": _filter_advice_for_scene(content, scene),
        })
    return out


def _parse_advice_sections(content: str) -> Tuple[str, List[Dict[str, Any]]]:
    """把 advice 文档拆为「前言 + 分节列表」。

    每节结构：{title, applies: [场景名...], body: [行...]}；
    分节以 `## 标题` 起始，紧随的 `<!-- applies: xxx -->` 标注适用场景（未标注 = 全局）。
    """
    preamble: List[str] = []
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
    return "\n".join(preamble).rstrip(), sections


def _advice_sections_full(content: str) -> Dict[str, Any]:
    """分块完整结构：{preamble, sections:[{title, applies, body}]}（body 为标题/标签后的正文）。"""
    pre, sections = _parse_advice_sections(content)
    out = []
    for s in sections:
        body_lines = s["body"][1:] if s["body"] and s["body"][0].startswith("## ") else s["body"]
        out.append({"title": s["title"], "applies": s["applies"],
                    "body": "\n".join(body_lines).strip()})
    return {"preamble": pre, "sections": out}


def _rebuild_advice_doc(preamble: str, sections: List[Dict[str, Any]]) -> str:
    """由「前言 + 分块」重建 Markdown 文档（保留 applies 标签语义）。"""
    parts: List[str] = []
    if preamble and preamble.strip():
        parts.append(preamble.strip())
    for sec in sections or []:
        title = str(sec.get("title") or "").strip()
        if not title:
            continue
        body = str(sec.get("body") or "").strip()
        applies = [str(x).strip() for x in (sec.get("applies") or []) if str(x).strip()]
        block = f"## {title}"
        if applies:
            block += f"\n\n<!-- applies: {', '.join(applies)} -->"
        if body:
            block += f"\n\n{body}"
        parts.append(block)
    return ("\n\n".join(parts)).rstrip() + "\n"


def _advice_sections_meta(content: str) -> List[Dict[str, Any]]:
    """分节元信息（标题 + 适用场景），供前端展示分区情况。"""
    _, sections = _parse_advice_sections(content)
    return [{"title": s["title"], "applies": s["applies"]} for s in sections]


def _filter_advice_for_scene(content: str, scene: str) -> str:
    """按场景过滤：保留全局分节（未标注）与 applies 命中该场景的分节。"""
    pre, sections = _parse_advice_sections(content)
    kept = [s for s in sections if (not s["applies"]) or (scene in s["applies"])]
    parts = [pre] if pre.strip() else []
    parts += ["\n".join(s["body"]).rstrip() for s in kept]
    return "\n\n".join(p for p in parts if p.strip())


def _expand_advice_docs(node: Any, scene: Optional[str] = None) -> Any:
    """深度展开 advice_docs 引用为已加载的文档内容（返回副本，不修改原注册表）。

    每个引用被展开为 {role, path, loaded, sections, content}；加载失败时 loaded=False、
    content 为降级占位文本，随提示词一并注入，保证 AI 可感知缺档。
    传入 scene 时按分节过滤（`<!-- applies: <scene> -->`，未标注分节始终保留）；
    未传 scene（全量场景，如查看/同步接口）时返回整份文档。
    """
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


def advice_docs_status() -> List[Dict[str, Any]]:
    """汇总全局引导文档注册表的加载状态（供健康检查接口）。"""
    status: List[Dict[str, Any]] = []
    for entry in _load_advice_registry():
        path = str(entry.get("path") or "")
        if not path:
            continue
        loaded = _load_advice_doc(path)
        status.append({"path": loaded["path"], "loaded": loaded["ok"],
                       "inject": bool(entry.get("inject", True))})
    return status


def _selected_registry_for_prompt(scenes: List[str]) -> str:
    """按场景组装注入提示词的注册表。

    advice 引导文档不再写在场景 JSON 中，而由全局注册表（advice_docs.json）声明；
    仅当文档存在适用于该场景（或全局）的分块时才注入，注入内容为按场景过滤后的分块。
    """
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
    return ir, meta


LEVEL2_EMPTY_RETRY_HINT = (
    "上一次输出的 policies 为空，但已确定需要授权的场景。请在遵守全部约束（denylist、只读优先、不编造敏感值）"
    "的前提下，输出完成该 query 所需的最小授权：query 中明确给出的资源逐字使用；"
    "必填参数在 query 中未给出时用通配符 `*` 表示，并只授权完成任务必需的动作。"
    "只有当任务本身被约束明确禁止时，才保持 policies 为空。"
)


def _safe_extract(raw: str) -> Dict[str, Any]:
    try:
        obj = _extract_json(raw)
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _has_policies(ir: Any) -> bool:
    return isinstance(ir, dict) and isinstance(ir.get("policies"), list) and len(ir["policies"]) > 0


# ---------------------------------------------------------------------------
# Normalize
# ---------------------------------------------------------------------------
def _static_spec(param_def: Dict[str, Any]) -> List[Dict[str, Any]]:
    spec = param_def.get("constraint_spec", {}).get("static", [])
    # 兼容旧格式：单个 dict 视为只有一个子场景
    if isinstance(spec, dict):
        return [{"note": "default", **spec}]
    return spec if isinstance(spec, list) else []


def normalize_ir(ir: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize LLM output to subject/objects format. Handles both new and old formats."""
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
            # Fill defaults from first matching static sub-scenario
            for param_name, param_def in fn_def.get("params", {}).items():
                static_list = _static_spec(param_def)
                default = None
                for static in static_list:
                    if static.get("default") is not None:
                        default = static["default"]
                        break
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


# 命令 / 语句类参数：按「命令名 / 语句前缀」匹配 denylist（R10 修复），其余参数按值 / 通配匹配
_COMMAND_PARAM_NAMES = {"command", "cmd", "commands", "script", "shell", "sql"}
_CMD_WRAPPERS = {"sudo", "env", "nohup", "command", "exec", "time", "nice", "xargs", "busybox"}


def _split_command_segments(cmd: str) -> List[str]:
    """按 shell 控制符（; & | 换行）切分为子命令，保留每段原文。"""
    return [seg.strip() for seg in re.split(r"[;&|\n]+", cmd) if seg.strip()]


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


def _token_match(actual: str, ptok: str) -> bool:
    if actual == ptok:
        return True
    if ptok.endswith(("=", "(", "()")):
        return actual.startswith(ptok.rstrip(")"))
    if "*" in ptok:
        return re.fullmatch(_glob_to_regex(ptok), actual) is not None
    return False


def _glob_to_regex(pattern: str) -> str:
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
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
    v = os.path.expanduser(value.strip().strip("'\""))
    if v.startswith("/"):
        v = os.path.normpath(v)
    return v


def _command_denied(value: str, pattern: str) -> bool:
    """命令 / 语句类参数的 denylist 匹配（大小写不敏感）：
    · 含控制符（| ; & ）的禁止项（如「| bash」「curl *| sh」）：在整条命令上做子串 / 通配查找；
    · 单词禁止项（如 rm、sudo、DROP 之外的 ATTACH）：命中任一子命令的命令名或包装命令名；
    · 多词禁止项（如「rm -rf /」「git push --force」「DROP TABLE」）：命令名相同且其余各词都出现在该子命令中，
      「rm -rf /」命中「rm -rf / --no-preserve-root」，不命中「rm -rf /tmp/a」。"""
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


def _param_denied(param_name: str, value: str, denylist: List[str]) -> Optional[str]:
    """返回命中的禁止项，未命中返回 None。"""
    is_cmd = str(param_name or "").lower() in _COMMAND_PARAM_NAMES
    for pattern in denylist:
        if (_command_denied(value, pattern) if is_cmd else _value_denied(value, pattern)):
            return pattern
    return None


def _apply_static_deny(ir: Dict[str, Any]) -> Dict[str, Any]:
    """静态策略 denylist 优先于 IR（S-1-1）。

    工具对象的参数值命中所在函数定义的 constraint_spec.static.denylist 时，
    该工具对象整体从 IR 中删除（相当于阻断），并打印告警；不影响其余允许项。
    """
    if not isinstance(ir, dict):
        return ir
    denied: List[str] = []
    kept_policies: List[Dict[str, Any]] = []
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
            rep.ok = False
            rep.errors.append(f"policy[{i}] subject '{subject}' 不在已知场景列表中")

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

            if obj_type not in ("tool", "file", "network"):
                rep.ok = False
                rep.errors.append(f"policy[{i}].objects[{j}] type 必须为 'tool' 或 'file' 或 'network'，当前为 {obj_type!r}")
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
                    rep.ok = False
                    rep.errors.append(f"policy[{i}].objects[{j}] 工具 '{identifier}' 不在场景 '{subject}' 的注册表中")

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
def translate(query: str, config: Optional[Dict[str, Any]] = None, is_ui_test: bool = False, round_id: str = "", on_level1_done: Optional[callable] = None) -> Dict[str, Any]:
    """Full pipeline: query -> level1 -> level2 -> normalize -> validate -> store.
    
    Args:
        query: The user query text.
        config: LLM config dict.
        is_ui_test: Whether this is from UI test page.
        round_id: The round identifier.
        on_level1_done: Optional callback(level1_scenes, meta1) called after level1 completes.
    """
    cfg = config or get_llm_config()

    # Level 1
    scenes, meta1 = level1_classify(query, config=cfg)
    
    # Level1 完成后立即回调更新数据库
    if on_level1_done and round_id:
        try:
            on_level1_done(round_id, scenes, meta1)
        except Exception as e:
            print(f"[translator] on_level1_done callback error: {e}", flush=True)

    # Level 2
    if scenes:
        ir, meta2 = level2_generate(query, scenes, config=cfg)
    else:
        ir, meta2 = {}, {}

    # Normalize
    if ir:
        ir = normalize_ir(ir)

    # 静态策略 denylist 优先于 IR（S-1-1）：命中即删除，不影响主链路
    if ir:
        ir = _apply_static_deny(ir)

    # Validate
    validation = validate_ir(ir) if ir else ValidationReport(ok=True)

    result = {
        "query": query,
        "level1": scenes,
        "level2": ir,
        "validation": {"ok": validation.ok, "errors": validation.errors, "warnings": validation.warnings},
        "meta": {"level1": meta1, "level2": meta2},
    }

    # Store to translation log (update if already inserted by callback)
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
    if ir_dict:
        ir_dict = normalize_ir(ir_dict)
        ir_dict = _apply_static_deny(ir_dict)
    validation = validate_ir(ir_dict) if ir_dict else ValidationReport(ok=True)
    return {
        "ir": ir_dict,
        "validation": {"ok": validation.ok, "errors": validation.errors, "warnings": validation.warnings},
    }
