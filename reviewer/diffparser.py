"""把 GitCode 的 PR diff 解析为结构化对象。

优先使用 `pulls/<n>/files.json`（含精确行号），失败时回退到 `pr diff` 文本。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterator, List, Optional, Tuple


@dataclass
class DiffLine:
    text: str
    old_line: Optional[int] = None
    new_line: Optional[int] = None
    kind: str = "ctx"  # add | del | ctx


@dataclass
class FileDiff:
    path: str = ""
    old_path: str = ""
    new_path: str = ""
    added: int = 0
    removed: int = 0
    new_file: bool = False
    deleted: bool = False
    renamed: bool = False
    lines: List[DiffLine] = field(default_factory=list)


@dataclass
class DiffData:
    number: int = 0
    title: str = ""
    added_lines: int = 0
    removed_lines: int = 0
    files: List[FileDiff] = field(default_factory=list)
    source: str = "api"  # api | text
    truncated: bool = False

    def added(self) -> Iterator[Tuple[FileDiff, DiffLine]]:
        """遍历所有新增行。"""
        for file in self.files:
            for line in file.lines:
                if line.kind == "add":
                    yield file, line

    def is_test_file(self, path: str) -> bool:
        lowered = path.lower()
        segments = {seg for seg in re.split(r"[\\/._-]", lowered) if seg}
        name = re.split(r"[\\/]", lowered)[-1]
        return (
            bool(segments & {"test", "tests", "spec", "specs"})
            or name.startswith("test_")
            or name.endswith(("_test.py", "_test.go", "_test.cpp", "_test.cc", ".test.js", ".spec.js"))
        )

    def is_source_file(self, path: str) -> bool:
        return path.lower().endswith(
            (
                ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".cu", ".cuh",
                ".py", ".pyx", ".go", ".rs", ".java", ".kt", ".kts", ".js", ".jsx",
                ".mjs", ".ts", ".tsx", ".m", ".mm", ".cs", ".swift", ".scala",
                ".rb", ".php", ".lua", ".sh", ".bash",
            )
        )

    def is_doc_file(self, path: str) -> bool:
        return path.lower().endswith((".md", ".rst", ".txt", ".adoc", ".asciidoc"))


def _to_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        return int(text) if text.isdigit() else None
    if isinstance(value, dict):
        for key in ("line_num", "line", "number", "value", "new_line", "old_line"):
            if key in value:
                found = _to_int(value[key])
                if found is not None:
                    return found
    return None


def _kind(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if text in {"new", "add", "added", "+"}:
        return "add"
    if text in {"old", "del", "delete", "deleted", "-"}:
        return "del"
    return "ctx"


def parse_files_payload(payload: Any, number: int = 0, title: str = "") -> DiffData:
    """解析 `pulls/<n>/files.json` 的返回。"""
    if not isinstance(payload, dict):
        raise ValueError("PR files payload 不是对象")

    diffs = payload.get("diffs") or []
    if not isinstance(diffs, list):
        diffs = []

    files: List[FileDiff] = []
    for diff in diffs:
        if not isinstance(diff, dict):
            continue
        # GitCode 当前 files.json 把路径放在 statistic 里（而不是顶层 path 字段）。
        statistic = diff.get("statistic") if isinstance(diff.get("statistic"), dict) else {}
        new_path = str(
            statistic.get("new_path")
            or diff.get("new_path")
            or statistic.get("path")
            or diff.get("path")
            or ""
        )
        old_path = str(statistic.get("old_path") or diff.get("old_path") or "")
        if not new_path and not old_path:
            new_path = str(statistic.get("path") or "")

        content = diff.get("content") if isinstance(diff.get("content"), dict) else {}
        raw_lines = content.get("text") if isinstance(content, dict) else []
        if not isinstance(raw_lines, list):
            raw_lines = []

        lines: List[DiffLine] = []
        counted_added = counted_removed = 0
        for item in raw_lines:
            if not isinstance(item, dict):
                continue
            kind = _kind(item.get("type"))
            if kind == "add":
                counted_added += 1
            elif kind == "del":
                counted_removed += 1
            text = str(item.get("line_content") or "")
            # line_content 自带 diff 前缀字符（"+" / "-" / " "），去掉后再做规则匹配。
            if kind == "add" and text.startswith("+"):
                text = text[1:]
            elif kind == "del" and text.startswith("-"):
                text = text[1:]
            elif kind == "ctx" and text.startswith(" "):
                text = text[1:]
            lines.append(
                DiffLine(
                    text=text,
                    old_line=_to_int(item.get("old_line")),
                    new_line=_to_int(item.get("new_line")),
                    kind=kind,
                )
            )

        file_added = diff.get("added_lines")
        file_removed = diff.get("remove_lines")
        files.append(
            FileDiff(
                path=new_path or old_path,
                old_path=old_path,
                new_path=new_path,
                added=file_added if isinstance(file_added, int) else counted_added,
                removed=file_removed if isinstance(file_removed, int) else counted_removed,
                new_file=(not old_path and bool(new_path)),
                deleted=(bool(old_path) and not new_path),
                renamed=(bool(old_path) and bool(new_path) and old_path != new_path),
                lines=lines,
            )
        )

    total_added = payload.get("added_lines")
    total_removed = payload.get("remove_lines")
    return DiffData(
        number=int(number),
        title=title,
        added_lines=int(total_added) if isinstance(total_added, int) else sum(f.added for f in files),
        removed_lines=int(total_removed) if isinstance(total_removed, int) else sum(f.removed for f in files),
        files=files,
        source="api",
    )


_DIFF_GIT_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")


def parse_text_diff(text: str) -> DiffData:
    """解析 `gitcode pr diff` 的文本输出（无 hunk 头，行号为近似值）。"""
    files: List[FileDiff] = []
    current: Optional[FileDiff] = None
    new_cursor = 0

    for raw in (text or "").splitlines():
        header = _DIFF_GIT_RE.match(raw)
        if header:
            old_path, new_path = header.group(1), header.group(2)
            current = FileDiff(
                path=new_path or old_path,
                old_path=old_path,
                new_path=new_path,
                new_file=(not old_path or old_path == "/dev/null"),
                deleted=(not new_path or new_path == "/dev/null"),
                renamed=(bool(old_path) and bool(new_path) and old_path != new_path),
            )
            files.append(current)
            new_cursor = 0
            continue

        if current is None:
            continue  # 跳过 PR 标题 / 分支 / 统计等前言
        if raw.startswith(("+++", "---")):
            continue

        if raw.startswith("+"):
            current.lines.append(DiffLine(raw[1:], None, new_cursor + 1, "add"))
            current.added += 1
            new_cursor += 1
        elif raw.startswith("-"):
            current.lines.append(DiffLine(raw[1:], None, None, "del"))
            current.removed += 1
        elif raw == "":
            current.lines.append(DiffLine("", None, new_cursor + 1, "ctx"))
            new_cursor += 1
        else:
            prefix_ok = raw.startswith(" ")
            content = raw[1:] if prefix_ok else raw
            current.lines.append(DiffLine(content, None, new_cursor + 1, "ctx"))
            new_cursor += 1

    return DiffData(
        added_lines=sum(f.added for f in files),
        removed_lines=sum(f.removed for f in files),
        files=files,
        source="text",
    )


def render_for_llm(diff: DiffData, max_chars: int = 60000) -> str:
    """生成带行号的紧凑 diff 文本，供 LLM 阅读。"""
    parts: List[str] = []
    for file in diff.files:
        if not file.lines:
            continue
        tag = " (新增文件)" if file.new_file else " (删除文件)" if file.deleted else ""
        parts.append(f"### {file.path}{tag}")
        for line in file.lines:
            prefix = "+" if line.kind == "add" else "-" if line.kind == "del" else " "
            number = line.old_line if line.kind == "del" else line.new_line
            location = f"{number:>6}" if number else "      "
            parts.append(f"{location} {prefix}{line.text}")

    text = "\n".join(parts).strip()
    if not text:
        return ""
    if len(text) > max_chars > 0:
        text = text[:max_chars]
        diff.truncated = True
        text += "\n...（diff 过长，已截断）"
    return text
