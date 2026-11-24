"""对 GitCode CLI（`gitcode` / `gc`）的轻量封装。

所有网络访问都通过已安装的 `gitcode` CLI 完成，认证使用 `GC_TOKEN` /
`GITCODE_TOKEN` 环境变量。这样我们不必自己维护 API 认证与分页逻辑。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, List, Optional


class GitcodeError(RuntimeError):
    """gitcode CLI 调用失败。"""


@dataclass
class CommandResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int

    @property
    def error_summary(self) -> str:
        detail = (self.stderr or "").strip() or (self.stdout or "").strip()
        detail = " ".join(detail.split())
        return detail[:600] if detail else f"exit code {self.returncode}"


def _extract_json(text: str) -> Any:
    """从 CLI 输出中提取 JSON。

    `gitcode api` 通常直接打印 JSON；这里兼容前置提示行 / BOM 等情况。
    """
    text = (text or "").strip().lstrip("﻿")
    if not text:
        raise GitcodeError("命令返回为空，无法解析 JSON")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    starts = [idx for idx in (text.find("{"), text.find("[")) if idx >= 0]
    if not starts:
        raise GitcodeError("命令输出中未找到 JSON")
    start = min(starts)
    # 从第一个 { / [ 开始尝试截取到末尾并逐步收缩
    for end in range(len(text), start, -1):
        chunk = text[start:end]
        try:
            return json.loads(chunk)
        except json.JSONDecodeError:
            continue
    raise GitcodeError("命令输出中的 JSON 无法解析")


def _as_list(data: Any, *keys: str) -> List[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value
        # 单页接口可能返回 {"data": {"list": [...]}} 之类
        for value in data.values():
            if isinstance(value, list):
                return value
    return []


class GitcodeClient:
    """通过 subprocess 调用 `gitcode` CLI。"""

    def __init__(
        self,
        repo: str,
        binary: Optional[str] = None,
        token: Optional[str] = None,
        timeout: int = 120,
    ) -> None:
        self.repo = repo
        self.binary = (
            binary
            or os.environ.get("GITCODE_BIN")
            or shutil.which("gitcode")
            or shutil.which("gc")
        )
        if not self.binary:
            raise GitcodeError(
                "未找到 gitcode / gc 可执行文件。请先 `pip install gitcode-cli==0.13.0`。"
            )
        self.token = (
            token
            or os.environ.get("GC_TOKEN")
            or os.environ.get("GITCODE_TOKEN")
            or ""
        )
        self.timeout = timeout

    # ------------------------------------------------------------------ helpers
    def _env(self) -> dict:
        env = os.environ.copy()
        if self.token:
            env["GC_TOKEN"] = self.token
        env.setdefault("GC_NO_UPDATE_CHECK", "1")
        env.setdefault("CI", "true")
        return env

    def _run(self, args: List[str], timeout: Optional[int] = None) -> CommandResult:
        cmd = [self.binary, *args]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self._env(),
                timeout=timeout or self.timeout,
            )
        except FileNotFoundError as exc:  # pragma: no cover - 环境问题
            raise GitcodeError(f"无法执行 {self.binary}: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise GitcodeError(
                f"命令超时（{timeout or self.timeout}s）：gitcode {' '.join(args)}"
            ) from exc
        return CommandResult(
            ok=proc.returncode == 0,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            returncode=proc.returncode,
        )

    # ---------------------------------------------------------------- operations
    def list_open_prs(self) -> List[dict]:
        result = self._run(
            [
                "pr",
                "list",
                "-R",
                self.repo,
                "--state",
                "open",
                "--paginate",
                "--per-page",
                "100",
                "--json",
            ]
        )
        if not result.ok:
            raise GitcodeError(f"获取 open PR 失败：{result.error_summary}")
        data = _extract_json(result.stdout)
        return [item for item in _as_list(data, "pull_requests", "items", "data") if isinstance(item, dict)]

    def get_files_payload(self, number: int) -> dict:
        """获取 PR 结构化 diff（含每行 old_line/new_line）。"""
        endpoint = f"repos/{self.repo}/pulls/{int(number)}/files.json"
        result = self._run(["api", endpoint])
        if not result.ok:
            raise GitcodeError(f"获取 PR #{number} 文件 diff 失败：{result.error_summary}")
        data = _extract_json(result.stdout)
        if not isinstance(data, dict):
            raise GitcodeError("PR files 接口返回格式异常")
        return data

    def get_text_diff(self, number: int) -> str:
        result = self._run(["pr", "diff", str(number), "-R", self.repo])
        if not result.ok:
            raise GitcodeError(f"获取 PR #{number} 文本 diff 失败：{result.error_summary}")
        return result.stdout

    def list_comments(self, number: int) -> List[dict]:
        """读取 PR 评论；失败时返回空列表（不阻断主流程）。"""
        result = self._run(["pr", "comments", str(number), "-R", self.repo, "--json"])
        if not result.ok:
            return []
        try:
            data = _extract_json(result.stdout)
        except GitcodeError:
            return []
        return [item for item in _as_list(data, "comments", "items", "data") if isinstance(item, dict)]

    def post_review_comment(self, number: int, body: str) -> CommandResult:
        """以 `pr review --comment-file` 提交检视评论，返回原始结果。"""
        fd, path = tempfile.mkstemp(prefix="npusim-review-", suffix=".md")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(body)
            return self._run(
                [
                    "--no-interactive",
                    "pr",
                    "review",
                    str(number),
                    "-R",
                    self.repo,
                    "--comment-file",
                    path,
                ]
            )
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def version(self) -> str:
        result = self._run(["version"])
        return (result.stdout or result.stderr).strip()
