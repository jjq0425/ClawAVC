# -*- coding: utf-8 -*-
"""参数内容检测规则的组件基础设施。

每条检测规则（如路径穿越、注入标记）都是一个独立的 Rule 组件：
- 元数据（key / 中文名 / 说明 / 可配置参数）用于前端自动渲染配置表单；
- check() 只负责判定，严重级与启用开关统一由配置层注入。

新增规则只需在 path_rules.py / content_rules.py 里追加一个 Rule 并注册到
registry.py，前端表单、校验、文档会自动同步——无需改动 UI 代码。
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

SEVERITIES = ("critical", "high", "medium", "low")
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def worst_severity(severities: List[str]) -> str:
    """返回一组严重级里最严重的一个。"""
    if not severities:
        return ""
    return sorted(severities, key=lambda s: SEVERITY_RANK.get(s, 9))[0]


@dataclass
class Hit:
    """一次规则命中。"""

    tool: str
    param: str
    rule: str
    severity: str
    evidence: str

    def as_dict(self) -> Dict[str, str]:
        return {
            "tool": self.tool,
            "param": self.param,
            "rule": self.rule,
            "severity": self.severity,
            "evidence": str(self.evidence)[:200],
        }


@dataclass
class RuleParam:
    """规则的可调参数（前端据此渲染控件）。"""

    name: str
    label: str
    type: str  # severity | int | list | bool
    default: Any = None
    min: Optional[int] = None
    max: Optional[int] = None
    hint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = {"name": self.name, "label": self.label, "type": self.type, "default": self.default}
        if self.min is not None:
            d["min"] = self.min
        if self.max is not None:
            d["max"] = self.max
        if self.hint:
            d["hint"] = self.hint
        return d


@dataclass
class ParamCtx:
    """单个参数的检测上下文（由 registry 预先算好，规则组件只读）。"""

    tool: str
    name: str
    raw: str
    lower: str
    decoded: str  # URL 解码最多两轮后的值
    write_tool: bool  # 当前工具是否写类工具

    def hit(self, rule: str, severity: str, evidence: str) -> Hit:
        return Hit(self.tool, self.name, rule, severity, evidence)


# check(ctx, cfg) -> None | Hit | List[Hit]
Checker = Callable[[ParamCtx, Dict[str, Any]], Optional[Any]]


@dataclass
class Rule:
    """一条可插拔的检测规则组件。"""

    key: str  # 配置键（path 段的键 / content 段的键）
    side: str  # path | content
    label: str  # 中文名（前端展示）
    description: str  # 说明（前端展示）
    check: Checker
    severity: str = "high"  # 默认严重级
    param: Optional[RuleParam] = None  # 该规则对应的可调参数
    extra_params: List[RuleParam] = field(default_factory=list)  # 附加参数（如 min_token）
    default_enabled: bool = True
    needs_write_tool: bool = False  # True 时只对写类工具生效

    def to_dict(self) -> Dict[str, Any]:
        params = []
        for p in ([self.param] if self.param else []) + self.extra_params:
            pd = p.to_dict()
            # severity 参数的默认值跟随规则自身的默认级别
            if p.name == "severity":
                pd["default"] = self.severity
            params.append(pd)
        return {
            "key": self.key,
            "side": self.side,
            "label": self.label,
            "description": self.description,
            "default_severity": self.severity,
            "default_enabled": self.default_enabled,
            "needs_write_tool": self.needs_write_tool,
            "params": params,
        }


@dataclass
class RuleGroup:
    """规则分组（前端按组渲染）。"""

    side: str
    title: str
    description: str
    rules: List[Rule]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "side": self.side,
            "title": self.title,
            "description": self.description,
            "rules": [r.to_dict() for r in self.rules],
        }
