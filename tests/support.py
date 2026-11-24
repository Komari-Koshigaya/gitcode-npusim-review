"""测试辅助：构造 PR / diff 数据。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = "cann/npu-simulator"
SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40
SHA_D = "d" * 40


def make_payload(entries: List[Dict[str, Any]], path: str = "src/kernel.c") -> Dict[str, Any]:
    diffs = [
        {
            "new_path": path,
            "old_path": path,
            "content": {"text": entries},
        }
    ]
    added = sum(1 for e in entries if e.get("type") == "new")
    removed = sum(1 for e in entries if e.get("type") == "old")
    return {
        "added_lines": added,
        "remove_lines": removed,
        "count": 1,
        "diffs": diffs,
    }


def make_pr(
    number: int,
    sha: str,
    title: Optional[str] = None,
    draft: bool = False,
    files_payload: Optional[Dict[str, Any]] = None,
    diff: str = "",
    comments: Optional[List[Dict[str, Any]]] = None,
    author: str = "alice",
    updated_at: str = "",
) -> Dict[str, Any]:
    pr: Dict[str, Any] = {
        "number": number,
        "title": title or f"PR {number}",
        "user": {"login": author},
        "head": {"ref": f"feature/{number}", "sha": sha},
        "base": {"ref": "master"},
        "html_url": f"https://gitcode.com/{REPO}/pulls/{number}",
        "additions": 3,
        "deletions": 1,
    }
    if draft:
        pr["draft"] = True
    if files_payload is not None:
        pr["files_payload"] = files_payload
    if diff:
        pr["diff"] = diff
    if comments is not None:
        pr["comments"] = comments
    if updated_at:
        pr["updated_at"] = updated_at
    return pr


def write_fixture(path: Any, prs: List[Dict[str, Any]]) -> str:
    Path(path).write_text(
        json.dumps({"prs": prs}, ensure_ascii=False), encoding="utf-8"
    )
    return str(path)


def simple_diff_text(added: str = "print(1)", path: str = "src/x.py") -> str:
    return (
        "PR #1: demo\n"
        "Branch: feature -> master\n"
        "Changes: +1 -0 in 1 file(s)\n\n"
        f"diff --git a/{path} b/{path}\n"
        f"+{added}\n"
    )
