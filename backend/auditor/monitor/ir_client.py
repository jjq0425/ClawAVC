#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IR Translator Client.

Calls the existing clawAVC translator API to obtain IR from user query.
Endpoint: POST /api/translator/test
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Any, Dict, Optional, Tuple


# 翻译端点固定为本机后端：监控与平台同机部署，缺省值即生产可用
TRANSLATOR_URL = "http://127.0.0.1:15100/api/translator/translate"


def translate(
    query: str,
    round_id: str = "",
    *,
    use_llm: bool = True,
    timeout: float = 300.0,
    base_url: str = TRANSLATOR_URL,
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Call the IR translator service.

    Args:
        query: The user query text.
        round_id: The round identifier.
        use_llm: Whether to use LLM for translation.
        timeout: HTTP timeout in seconds.
        base_url: The translator endpoint URL.

    Returns:
        Tuple of (ir_dict, error_string_or_None).
    """
    # 空 query/占位符直接跳过：不发起翻译（R-3-4 的空请求隔离）
    if not query or query == "(not found)":
        return {}, "empty query"

    payload = {
        "query": query,
        "round_id": round_id,
        "use_llm": use_llm,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    # User-Agent 标识监控来源：后端 api_trace 可区分监控与人工调用
    req = urllib.request.Request(
        base_url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "ClawAVC-Monitor/1.0",
        },
    )
    try:
        # timeout 缺省 300s：覆盖 Level-2 长尾（生产日志中位约 9s、最大 59s）
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            # 响应三形态兼容：{ok,data} 包装 / 扁平 dict / 非 dict 包装为 value
            if parsed.get("ok"):
                return parsed.get("data", parsed), None
            # Some endpoints return {ok, data} or flat
            return parsed, None
        return {"value": parsed}, None
    # 错误信息截断 200 字符：错误详情供日志，超长 traceback 不占内存
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return {}, f"HTTP {exc.code}: {err_body[:200]}"
    except Exception as exc:
        # 任何异常都返回明确错误字符串：调用方只记日志不中断（监控隔离边界）
        return {}, str(exc)
