"""生成提交到 GitCode PR 的 Markdown 检视评论，以及去重标记。"""

from __future__ import annotations

from typing import Any, Dict, List

from .config import Config
from .diffparser import DiffData
from .engine.base import SEVERITY_LABEL, ReviewResult, risk_label, severity_counts

MARKER_PREFIX = "npu-review sha="


def marker(head_sha: str) -> str:
    return f"<!-- {MARKER_PREFIX}{head_sha} -->"


def contains_marker(comments: List[Dict[str, Any]], head_sha: str) -> bool:
    """判断已有评论中是否包含针对该提交的检视标记（第二层防重复）。"""
    if not head_sha:
        return False
    needle = f"{MARKER_PREFIX}{head_sha}"
    for comment in comments or []:
        if not isinstance(comment, dict):
            continue
        body = comment.get("body") or comment.get("content") or ""
        if needle in str(body):
            return True
    return False


INLINE_MARKER_PREFIX = "npu-review-inline sha="


def inline_marker(head_sha: str, file: str, line: int) -> str:
    return f"<!-- {INLINE_MARKER_PREFIX}{head_sha} file={file} line={line} -->"


def contains_inline_marker(
    comments: List[Dict[str, Any]], marker_text: str
) -> bool:
    """判断是否已有同一条行内评论（用于部分失败后的重试去重）。"""
    if not marker_text:
        return False
    for comment in comments or []:
        if not isinstance(comment, dict):
            continue
        body = comment.get("body") or comment.get("content") or ""
        if marker_text in str(body):
            return True
    return False


def contains_inline_sha(comments: List[Dict[str, Any]], head_sha: str) -> bool:
    """判断是否已有针对该提交的任意行内评论（用于去重，不依赖汇总评论标记）。"""
    if not head_sha:
        return False
    needle = f"{INLINE_MARKER_PREFIX}{head_sha}"
    for comment in comments or []:
        if not isinstance(comment, dict):
            continue
        body = comment.get("body") or comment.get("content") or ""
        if needle in str(body):
            return True
    return False


def build_inline_comment(finding: Any, head_sha: str) -> str:
    origin = "AI" if getattr(finding, "engine", "rules") == "llm" else "规则"
    lines: List[str] = [
        f"🤖 **自动检视 · {SEVERITY_LABEL.get(finding.severity, finding.severity)}**",
        "",
        finding.message,
    ]
    if finding.suggestion:
        lines.append("")
        lines.append(f"建议：{finding.suggestion}")
    lines.append("")
    lines.append(f"<sub>{origin} · {finding.rule}</sub>")
    if head_sha:
        lines.append(inline_marker(head_sha, finding.file, int(finding.line)))
    return "\n".join(lines).strip() + "\n"


def engines_label(engines: List[str]) -> str:
    has_rules = "rules" in engines
    has_llm = "llm" in engines
    if has_rules and has_llm:
        return "规则 + AI"
    if has_llm:
        return "AI"
    if has_rules:
        return "规则"
    return "无"


def build_comment(
    pr: Dict[str, Any],
    diff: DiffData,
    result: ReviewResult,
    config: Config,
    inline_posted: int = 0,
) -> str:
    number = pr.get("number", "?")
    head = pr.get("head") if isinstance(pr.get("head"), dict) else {}
    head_sha = str(head.get("sha") or "")
    short_sha = head_sha[:8] if head_sha else "unknown"
    counts = severity_counts(result.findings)
    label = engines_label(result.engines)

    lines: List[str] = [
        "## 🤖 自动代码检视报告",
        "",
    ]
    if head_sha:
        lines.append(marker(head_sha))
    lines.append(
        f"> PR #{number} · 提交 `{short_sha}` · 引擎：{label} · 总体风险：**{risk_label(result.risk_level)}**"
    )
    lines.append("")
    lines.append(
        f"**变更规模**：+{diff.added_lines} / −{diff.removed_lines}，{len(diff.files)} 个文件"
    )
    lines.append("")
    lines.append(
        f"**发现统计**：严重 {counts['high']} · 中等 {counts['medium']} · "
        f"较低 {counts['low']} · 提示 {counts['info']}（共 {len(result.findings)} 条）"
    )
    lines.append("")
    if inline_posted > 0:
        lines.append(f"**行内意见**：已在 {inline_posted} 处代码行留下行内评论。")
        lines.append("")

    if result.summary:
        lines.append(result.summary)
        lines.append("")

    shown = result.findings[: max(0, config.max_findings_in_comment)]
    omitted = len(result.findings) - len(shown)

    for severity in ("high", "medium", "low", "info"):
        group = [f for f in shown if f.severity == severity]
        if not group:
            continue
        lines.append(f"### {SEVERITY_LABEL[severity]}（{len(group)}）")
        for finding in group:
            origin = "AI" if finding.engine == "llm" else "规则"
            location = f"`{finding.location}`" if finding.file else "（全局）"
            lines.append(f"- {location} — {finding.message}  _[{origin} · {finding.rule}]_")
            if finding.snippet:
                snippet = finding.snippet.replace("`", "'").strip()
                lines.append(f"  > `{snippet}`")
            if finding.suggestion:
                lines.append(f"  - 建议：{finding.suggestion}")
        lines.append("")

    if omitted > 0:
        lines.append(f"> 另有 {omitted} 条发现未在此展开，可在报告中查看。")
        lines.append("")

    if result.warnings:
        lines.append("<details><summary>检视过程告警</summary>")
        lines.append("")
        for warning in result.warnings:
            lines.append(f"- {warning}")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    lines.append("---")
    lines.append(
        "<sub>本评论由自动检视机器人生成，仅供参考，不构成人工审批结论；"
        "同一提交（head SHA）不会重复评论。</sub>"
    )

    text = "\n".join(lines).strip() + "\n"
    if len(text) > 50000:
        text = text[:50000] + "\n\n...（评论过长，已截断）\n"
    return text
