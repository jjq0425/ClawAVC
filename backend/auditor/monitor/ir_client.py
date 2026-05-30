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


TRANSLATOR_URL = "http://127.0.0.1:15100/api/translator/translate"


def translate(
    query: str,
    round_id: str = "",
    *,
    use_llm: bool = True,
    timeout: float = 60.0,
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
    if not query or query == "(not found)":
        return {}, "empty query"

    payload = {
        "query": query,
        "round_id": round_id,
        "use_llm": use_llm,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            if parsed.get("ok"):
                return parsed.get("data", parsed), None
            # Some endpoints return {ok, data} or flat
            return parsed, None
        return {"value": parsed}, None
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return {}, f"HTTP {exc.code}: {err_body[:200]}"
    except Exception as exc:
        return {}, str(exc)
