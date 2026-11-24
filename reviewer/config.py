"""运行时配置：环境变量 + 命令行参数。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_REPO = "cann/npu-simulator"
DEFAULT_LLM_BASE_URL = "https://api.deepseek.com"
DEFAULT_LLM_MODEL = "deepseek-chat"


def _env_str(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or not str(value).strip():
        return default
    try:
        return int(str(value).strip())
    except ValueError:
        return default


@dataclass
class LLMConfig:
    api_key: str = ""
    base_url: str = DEFAULT_LLM_BASE_URL
    model: str = DEFAULT_LLM_MODEL
    timeout: int = 120
    max_diff_chars: int = 60000
    max_prs: int = 20

    @property
    def enabled(self) -> bool:
        """是否具备调用 LLM 的最小条件。"""
        return bool(self.api_key)


@dataclass
class Config:
    repo: str = DEFAULT_REPO
    report_dir: Path = Path("report")
    state_file: Path = Path("state/reviews.json")
    include_drafts: bool = False
    max_prs: int = 100
    tz_offset_hours: int = 8
    dry_run: bool = False
    force_review: bool = False
    large_file_lines: int = 800
    long_line_chars: int = 200
    max_findings_in_comment: int = 30
    # 只有最高严重度达到该阈值时才提交评论；"any" 表示即使无发现也提交。
    # 默认 low：info 级提示（例如"建议补充测试"）只记录到报告，不评论。
    min_severity_to_post: str = "low"
    llm: LLMConfig = field(default_factory=LLMConfig)

    @property
    def repo_url(self) -> str:
        return f"https://gitcode.com/{self.repo}/pulls"

    @classmethod
    def from_args(cls, args: Any) -> "Config":
        """由 argparse.Namespace（或任意带同名属性的对象）构建配置。"""

        def opt(name: str, default):
            value = getattr(args, name, None)
            return default if value is None else value

        repo = (opt("repo", "") or _env_str("GITCODE_REPO", DEFAULT_REPO)).strip()
        report_dir = Path(opt("report_dir", "") or _env_str("REPORT_DIR", "report"))
        state_file = Path(opt("state_file", "") or _env_str("STATE_FILE", "state/reviews.json"))
        min_severity = (opt("min_severity", "") or _env_str("MIN_SEVERITY_TO_POST", "low")).strip().lower()
        if min_severity not in {"any", "high", "medium", "low", "info"}:
            min_severity = "low"

        return cls(
            repo=repo,
            report_dir=report_dir,
            state_file=state_file,
            include_drafts=bool(opt("include_drafts", False) or _env_bool("INCLUDE_DRAFTS", False)),
            max_prs=int(opt("max_prs", 0) or _env_int("MAX_PRS", 100)),
            tz_offset_hours=_env_int("REPORT_TZ_OFFSET_HOURS", 8),
            dry_run=bool(opt("dry_run", False) or _env_bool("DRY_RUN", False)),
            force_review=bool(opt("force_review", False)),
            large_file_lines=_env_int("LARGE_FILE_LINES", 800),
            long_line_chars=_env_int("LONG_LINE_CHARS", 200),
            max_findings_in_comment=_env_int("MAX_FINDINGS_IN_COMMENT", 30),
            min_severity_to_post=min_severity,
            llm=LLMConfig(
                api_key=_env_str("LLM_API_KEY", ""),
                base_url=_env_str("LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
                model=_env_str("LLM_MODEL", DEFAULT_LLM_MODEL),
                timeout=_env_int("LLM_TIMEOUT", 120),
                max_diff_chars=_env_int("LLM_MAX_DIFF_CHARS", 60000),
                max_prs=_env_int("LLM_MAX_PRS", 20),
            ),
        )
