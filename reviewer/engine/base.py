"""检视结果的通用数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

SEVERITY_ORDER: Dict[str, int] = {"high": 0, "medium": 1, "low": 2, "info": 3}
SEVERITY_LABEL: Dict[str, str] = {
    "high": "严重",
    "medium": "中等",
    "low": "较低",
    "info": "提示",
}
RISK_LABEL: Dict[str, str] = {
    "high": "高",
    "medium": "中",
    "low": "低",
    "info": "提示",
    "": "无",
}


@dataclass
class Finding:
    rule: str
    severity: str
    file: str
    line: Optional[int]
    message: str
    snippet: str = ""
    suggestion: str = ""
    engine: str = "rules"

    @property
    def location(self) -> str:
        if self.file and self.line:
            return f"{self.file}:{self.line}"
        return self.file or "(未知位置)"


@dataclass
class ReviewResult:
    findings: List[Finding] = field(default_factory=list)
    summary: str = ""
    risk_level: str = ""
    engines: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def severity_counts(findings: List[Finding]) -> Dict[str, int]:
    counts = {key: 0 for key in SEVERITY_ORDER}
    for finding in findings:
        if finding.severity in counts:
            counts[finding.severity] += 1
    return counts


def highest_severity(findings: List[Finding]) -> str:
    """返回最严重的等级；无发现时返回空字符串。"""
    best = ""
    best_rank = 99
    for finding in findings:
        rank = SEVERITY_ORDER.get(finding.severity, 99)
        if rank < best_rank:
            best_rank = rank
            best = finding.severity
    return best


def risk_label(level: str) -> str:
    return RISK_LABEL.get((level or "").lower(), "无")
