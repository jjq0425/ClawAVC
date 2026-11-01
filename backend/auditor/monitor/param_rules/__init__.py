# -*- coding: utf-8 -*-
"""参数内容检测规则组件包。

对外只暴露注册表层 API；judge.py 通过本包调用，规则实现细节不外泄。
"""
from .base import Hit, ParamCtx, Rule, RuleGroup, RuleParam, SEVERITIES, worst_severity
from .content_rules import CONTENT_RULES
from .path_rules import PATH_RULES
from .registry import (
    DEFAULT_PARAM_CONTENT_RULES,
    GROUPS,
    catalog,
    check_param_content,
    check_param_content_to_text,
)

__all__ = [
    "Hit", "ParamCtx", "Rule", "RuleGroup", "RuleParam", "SEVERITIES", "worst_severity",
    "PATH_RULES", "CONTENT_RULES", "GROUPS",
    "DEFAULT_PARAM_CONTENT_RULES", "catalog",
    "check_param_content", "check_param_content_to_text",
]
