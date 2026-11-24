"""确定性规则检视。

只扫描 diff 的“新增行”，并补充少量文件级检查。规则追求低误报、可解释，
适合在无人值守的定时任务里稳定运行。
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from ..config import Config
from ..diffparser import DiffData, FileDiff
from .base import Finding, ReviewResult, highest_severity, severity_counts

# 生成物 / 第三方 / 锁文件：跳过“超长行”等低价值检查，降低噪声
_GENERATED_HINTS = (
    "package-lock.json",
    "yarn.lock",
    "go.sum",
    "poetry.lock",
    "cargo.lock",
    ".min.js",
    ".min.css",
    ".pb.go",
    "_pb2.py",
    "/dist/",
    "/third_party/",
    "/thirdparty/",
)

_SECRET_ASSIGN = re.compile(
    r"(?i)\b(api[_-]?key|secret|password|passwd|pwd|access[_-]?token|auth[_-]?token|private[_-]?key)\b"
    r"\s*[:=]\s*[\"'][^\"']{4,}[\"']"
)
_SECRET_AWS = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_SECRET_PEM = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")
_SECRET_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}")

_CONFLICT_MARKER = re.compile(r"^(?:<<<<<<<|=======|>>>>>>>)(?:\s|$)")

_DEBUG_PRINT = re.compile(
    r"(\bprint\s*\(|\bprintf\s*\(|\bconsole\.log\s*\(|\bfmt\.Print(?:f|ln)?\s*\(|"
    r"\bstd::(?:cout|cerr)\b|\bSystem\.out\.println\s*\(|\bdbg!\s*\(|"
    r"\bpdb\.set_trace\s*\(|\bbreakpoint\s*\(\s*\))"
)

_EMPTY_EXCEPT = re.compile(r"^\s*except\b[^:]*:\s*pass\s*(?:#.*)?$")
_EMPTY_CATCH = re.compile(r"\bcatch\s*\([^)]*\)\s*\{\s*\}")

_TODO = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")

_MAX_PER_RULE = 8


def _is_generated(path: str) -> bool:
    lowered = path.lower().replace("\\", "/")
    return any(hint in lowered for hint in _GENERATED_HINTS)


def _snippet(text: str, limit: int = 180) -> str:
    text = text.strip()
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def review(diff: DiffData, config: Config) -> ReviewResult:
    findings: List[Finding] = []
    per_rule: Dict[str, int] = {}
    skipped: Dict[str, int] = {}

    def add(
        rule: str,
        severity: str,
        file: str,
        line: Optional[int],
        message: str,
        snippet: str = "",
        suggestion: str = "",
    ) -> None:
        if per_rule.get(rule, 0) >= _MAX_PER_RULE:
            skipped[rule] = skipped.get(rule, 0) + 1
            return
        per_rule[rule] = per_rule.get(rule, 0) + 1
        findings.append(
            Finding(
                rule=rule,
                severity=severity,
                file=file,
                line=line,
                message=message,
                snippet=snippet,
                suggestion=suggestion,
                engine="rules",
            )
        )

    changed_code = False
    changed_tests = False

    for file, line in diff.added():
        text = line.text
        location_line = line.new_line
        generated = _is_generated(file.path)

        if _SECRET_ASSIGN.search(text) or _SECRET_AWS.search(text) or _SECRET_PEM.search(text) or _SECRET_BEARER.search(text):
            add(
                "hardcoded-secret",
                "high",
                file.path,
                location_line,
                "疑似硬编码的密钥 / 口令 / Token。",
                _snippet(text),
                "请改用环境变量或密钥管理服务，并考虑轮换已暴露的凭据。",
            )

        if _CONFLICT_MARKER.match(text.strip()):
            add(
                "merge-conflict",
                "high",
                file.path,
                location_line,
                "提交中残留合并冲突标记。",
                _snippet(text),
                "请解决冲突并移除 <<<<<<< / ======= / >>>>>>> 标记。",
            )

        if _EMPTY_EXCEPT.search(text):
            add(
                "swallowed-exception",
                "medium",
                file.path,
                location_line,
                "空 `except: pass` 会吞掉异常。",
                _snippet(text),
                "建议记录日志，或只捕获预期异常并做对应处理。",
            )

        if _EMPTY_CATCH.search(text):
            add(
                "empty-catch",
                "medium",
                file.path,
                location_line,
                "空 catch 块会隐藏错误。",
                _snippet(text),
                "建议至少记录日志或返回明确错误。",
            )

        if not generated and _DEBUG_PRINT.search(text):
            add(
                "debug-print",
                "low",
                file.path,
                location_line,
                "新增了调试输出语句。",
                _snippet(text),
                "生产路径中建议删除，或改用受级别控制的正式日志。",
            )

        todo = _TODO.search(text)
        if todo:
            add(
                "todo-marker",
                "info",
                file.path,
                location_line,
                f"新增待办标记 `{todo.group(1)}`。",
                _snippet(text),
                "请确认是否应在本 PR 内处理，或关联对应 Issue。",
            )

        if not generated and config.long_line_chars > 0 and len(text) > config.long_line_chars:
            add(
                "long-line",
                "low",
                file.path,
                location_line,
                f"该行长度 {len(text)} 超过阈值 {config.long_line_chars}。",
                _snippet(text),
                "建议拆分长行以提升可读性。",
            )

    for file in diff.files:
        if file.deleted:
            add(
                "deleted-file",
                "info",
                file.path,
                None,
                "该文件被删除。",
                "",
                "请确认没有未迁移的引用或调用方。",
            )
        if file.added + file.removed >= config.large_file_lines > 0:
            add(
                "large-change",
                "info",
                file.path,
                None,
                f"单文件改动 {file.added + file.removed} 行，超过阈值 {config.large_file_lines}。",
                "",
                "建议拆分为更小的 PR，便于评审与回归。",
            )
        if not diff.is_test_file(file.path) and (file.added > 0 or file.removed > 0):
            changed_code = True
        if diff.is_test_file(file.path) and (file.added > 0 or file.removed > 0):
            changed_tests = True

    if changed_code and not changed_tests and diff.files:
        add(
            "missing-tests",
            "info",
            "",
            None,
            "本 PR 修改了代码，但未包含测试变更。",
            "",
            "建议补充或更新覆盖改动的测试用例。",
        )

    warnings: List[str] = []
    if skipped:
        detail = "、".join(f"{rule} 省略 {count} 条" for rule, count in sorted(skipped.items()))
        warnings.append(f"规则发现过多，已按规则上限截断：{detail}。")

    if diff.source == "text":
        warnings.append("使用了文本 diff 回退模式，行号为近似值。")

    counts = severity_counts(findings)
    engine_summary = (
        f"规则检视共发现 {len(findings)} 个问题"
        f"（严重 {counts['high']}、中等 {counts['medium']}、较低 {counts['low']}、提示 {counts['info']}）。"
    )

    return ReviewResult(
        findings=findings,
        summary=engine_summary,
        risk_level=highest_severity(findings),
        engines=["rules"],
        warnings=warnings,
    )
