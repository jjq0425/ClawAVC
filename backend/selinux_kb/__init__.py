# -*- coding: utf-8 -*-
"""SELinux 知识库：语料解析、索引构建与检索。

对外常用入口：
    from selinux_kb import search
    search.search("httpd_t var_log_t write", kind="rule", k=5)
"""

from __future__ import annotations

__all__ = ["parsers", "search", "build_index"]
