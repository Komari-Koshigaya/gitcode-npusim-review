"""命令行入口与主流程编排。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__
from .comment import (
    build_comment,
    build_inline_comment,
    contains_inline_marker,
    contains_inline_sha,
    contains_marker,
    inline_marker,
)
from .config import Config
from .diffparser import DiffData, parse_files_payload, parse_text_diff
from .engine import llm, rules
from .engine.base import SEVERITY_ORDER, ReviewResult, highest_severity
from .gitcode import CommandResult, GitcodeClient, GitcodeError
from .report import now_local, write_reports
from .state import ReviewState


# --------------------------------------------------------------------------- helpers
def _head_key(pr: Dict[str, Any]) -> str:
    """返回用于幂等判断的提交标识；缺失 sha 时退回 updated_at。"""
    head = pr.get("head") if isinstance(pr.get("head"), dict) else {}
    sha = str(head.get("sha") or "").strip()
    if sha:
        return sha
    updated = str(pr.get("updated_at") or "").strip()
    if updated:
        return f"updated-{updated}"
    return ""


def _settle_risk(rule_risk: str, llm_risk: str) -> str:
    rank = dict(SEVERITY_ORDER)
    best = rule_risk or ""
    if llm_risk and (not best or rank.get(llm_risk, 9) < rank.get(best, 9)):
        best = llm_risk
    return best


_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2, "info": 3}


def _should_post(findings: List[Any], threshold: str) -> bool:
    """最高严重度达到阈值才提交评论；"any" 表示总是提交。"""
    threshold = (threshold or "info").lower()
    if threshold == "any":
        return True
    top = highest_severity(findings)
    if not top:
        return False
    return _SEVERITY_RANK.get(top, 99) <= _SEVERITY_RANK.get(threshold, 3)


def _inline_candidates(findings: List[Any], config: Config) -> List[Any]:
    """可挂到具体代码行的发现：有 file + 精确行号，且达到提交阈值。"""
    threshold = config.min_severity_to_post if config.min_severity_to_post != "any" else "info"
    limit = _SEVERITY_RANK.get(threshold, 2)
    candidates: List[Any] = []
    seen = set()
    for finding in findings:
        if not finding.file or not isinstance(finding.line, int) or finding.line <= 0:
            continue
        if _SEVERITY_RANK.get(finding.severity, 99) > limit:
            continue
        dedupe_key = (finding.file, finding.line, finding.rule, finding.message.strip())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        candidates.append(finding)
    candidates.sort(key=lambda f: (_SEVERITY_RANK.get(f.severity, 9), f.file, f.line or 0))
    return candidates[: max(0, config.max_inline_comments)]


def _combine(rule_result: ReviewResult, llm_result: ReviewResult) -> ReviewResult:
    findings = list(rule_result.findings) + list(llm_result.findings)
    seen = set()
    deduped = []
    for finding in findings:
        key = (finding.engine, finding.rule, finding.file, finding.line, finding.message.strip())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)

    summary_parts: List[str] = []
    if rule_result.summary:
        summary_parts.append(rule_result.summary)
    if llm_result.summary:
        summary_parts.append(f"**AI 总结**：{llm_result.summary}")

    engines: List[str] = []
    for engine in list(rule_result.engines) + list(llm_result.engines):
        if engine not in engines:
            engines.append(engine)

    return ReviewResult(
        findings=deduped,
        summary="\n\n".join(summary_parts),
        risk_level=_settle_risk(highest_severity(deduped), llm_result.risk_level),
        engines=engines,
        warnings=list(rule_result.warnings) + list(llm_result.warnings),
    )


def _fetch_diff(client: Any, number: int, title: str) -> DiffData:
    """优先结构化 API（精确行号），失败回退文本 diff。"""
    try:
        payload = client.get_files_payload(number)
        diff = parse_files_payload(payload, number=number, title=title)
        if diff.files:
            return diff
    except Exception:  # noqa: BLE001 - 回退到文本 diff
        pass

    text = client.get_text_diff(number)
    diff = parse_text_diff(text)
    diff.number = number
    diff.title = title
    return diff


class FixtureClient:
    """离线夹具客户端，用于本地演示与测试（不访问网络）。"""

    def __init__(self, path: str) -> None:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        prs = payload.get("prs") if isinstance(payload, dict) else None
        if not isinstance(prs, list):
            raise ValueError("fixture 文件需要包含 prs 数组")
        self._prs: List[Dict[str, Any]] = []
        self._payloads: Dict[int, Any] = {}
        self._diffs: Dict[int, str] = {}
        self._comments: Dict[int, List[Dict[str, Any]]] = {}
        self.posted: List[Dict[str, Any]] = []
        self.inline: List[Dict[str, Any]] = []
        for item in prs:
            if not isinstance(item, dict):
                continue
            pr = dict(item)
            number = int(pr.get("number") or 0)
            self._payloads[number] = pr.pop("files_payload", None)
            self._diffs[number] = pr.pop("diff", "") or ""
            self._comments[number] = pr.pop("comments", []) or []
            self._prs.append(pr)

    def list_open_prs(self) -> List[Dict[str, Any]]:
        return self._prs

    def get_files_payload(self, number: int) -> Dict[str, Any]:
        payload = self._payloads.get(number)
        if not isinstance(payload, dict):
            raise GitcodeError("fixture 未提供 files_payload")
        return payload

    def get_text_diff(self, number: int) -> str:
        return self._diffs.get(number, "")

    def list_comments(self, number: int) -> List[Dict[str, Any]]:
        return self._comments.get(number, [])

    def post_review_comment(self, number: int, body: str) -> CommandResult:
        self.posted.append({"number": number, "body": body})
        return CommandResult(ok=True, stdout="(fixture) posted", stderr="", returncode=0)

    def post_inline_comment(
        self, number: int, body: str, path: str, position: int
    ) -> CommandResult:
        self.inline.append(
            {"number": number, "body": body, "path": path, "position": position}
        )
        return CommandResult(ok=True, stdout="(fixture) inline posted", stderr="", returncode=0)


# --------------------------------------------------------------------------- main flow
def run_once(config: Config, client: Any, state: ReviewState) -> Dict[str, Any]:
    now = now_local(config.tz_offset_hours)
    date = now.strftime("%Y-%m-%d")
    generated_at = now.isoformat(timespec="seconds")
    generated_display = now.strftime("%Y-%m-%d %H:%M:%S %z")

    github_repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    github_repo_url = f"https://github.com/{github_repo}" if github_repo else ""

    run: Dict[str, Any] = {
        "date": date,
        "generated_at": generated_at,
        "generated_at_display": generated_display,
        "repo": config.repo,
        "repo_url": config.repo_url,
        "github_repo_url": github_repo_url,
        "dry_run": config.dry_run,
        "llm_enabled": config.llm.enabled,
        "truncated": False,
        "open_pr_count": 0,
        "considered_count": 0,
        "draft_count": 0,
        "reviewed_count": 0,
        "posted_count": 0,
        "skipped_count": 0,
        "report_only_count": 0,
        "inline_total": 0,
        "failed_count": 0,
        "findings_total": 0,
        "severity_counts": {key: 0 for key in SEVERITY_ORDER},
        "prs": [],
        "warnings": [],
    }

    prs = client.list_open_prs()
    run["open_pr_count"] = len(prs)

    processed = 0
    llm_budget = config.llm.max_prs if config.llm.enabled else 0

    for pr in prs:
        if not isinstance(pr, dict):
            continue
        number = int(pr.get("number") or 0)
        head = pr.get("head") if isinstance(pr.get("head"), dict) else {}
        base = pr.get("base") if isinstance(pr.get("base"), dict) else {}
        user = pr.get("user") if isinstance(pr.get("user"), dict) else {}
        key = _head_key(pr)
        record: Dict[str, Any] = {
            "number": number,
            "title": str(pr.get("title") or ""),
            "author": str(user.get("login") or user.get("name") or ""),
            "url": str(pr.get("html_url") or config.repo_url),
            "head_sha": key,
            "head_short": (key or "")[:8],
            "branch": f"{head.get('ref', '')} -> {base.get('ref', '')}".strip(" ->"),
            "status": "",
            "risk": "",
            "findings_count": 0,
            "findings": [],
            "comment": "",
            "warnings": [],
            "error": "",
            "engines": [],
            "additions": int(pr.get("additions") or 0),
            "deletions": int(pr.get("deletions") or 0),
        }

        if pr.get("draft") and not config.include_drafts:
            record["status"] = "draft_skipped"
            run["draft_count"] += 1
            run["prs"].append(record)
            continue

        if config.max_prs > 0 and processed >= config.max_prs:
            record["status"] = "truncated"
            run["truncated"] = True
            run["prs"].append(record)
            continue

        processed += 1
        run["considered_count"] += 1

        # 第一层：同一 head SHA 已检视 -> 跳过
        if not config.force_review and key and state.is_reviewed(config.repo, number, key):
            record["status"] = "unchanged"
            run["skipped_count"] += 1
            run["prs"].append(record)
            continue

        existing_comments: List[Dict[str, Any]] = []
        # 第二层：已有对应标记的评论 -> 跳过（防状态丢失 / 手动重跑重复）
        if not config.force_review and key:
            try:
                existing_comments = client.list_comments(number)
            except Exception:  # noqa: BLE001 - 读取失败不阻断
                existing_comments = []
            if contains_marker(existing_comments, key) or contains_inline_sha(
                existing_comments, key
            ):
                record["status"] = "skipped_existing"
                run["skipped_count"] += 1
                if not config.dry_run:
                    state.mark(
                        config.repo,
                        number,
                        key,
                        reviewed_at=generated_at,
                        source="comment-marker",
                    )
                run["prs"].append(record)
                continue

        # 获取 diff
        try:
            diff = _fetch_diff(client, number, record["title"])
        except Exception as exc:  # noqa: BLE001
            record["status"] = "failed"
            record["error"] = f"获取 diff 失败：{exc}"
            run["failed_count"] += 1
            run["prs"].append(record)
            continue

        record["additions"] = diff.added_lines
        record["deletions"] = diff.removed_lines

        rule_result = rules.review(diff, config)
        if config.llm.enabled:
            if llm_budget > 0:
                llm_result = llm.review(diff, pr, config)
                if llm_result.engines:
                    llm_budget -= 1
            else:
                llm_result = ReviewResult(
                    warnings=["已达到 LLM_MAX_PRS 上限，本 PR 仅使用规则检视。"]
                )
        else:
            llm_result = ReviewResult()

        combined = _combine(rule_result, llm_result)
        record["engines"] = combined.engines
        record["risk"] = combined.risk_level
        record["findings"] = [asdict(finding) for finding in combined.findings]
        record["findings_count"] = len(combined.findings)
        record["warnings"] = combined.warnings
        run["reviewed_count"] += 1

        comment_pr = dict(pr)
        comment_head = dict(head)
        comment_head["sha"] = key
        comment_pr["head"] = comment_head
        should_post = _should_post(combined.findings, config.min_severity_to_post)
        record["should_post"] = should_post

        inline_candidates = (
            _inline_candidates(combined.findings, config) if config.inline_comments else []
        )
        record["inline_candidates"] = len(inline_candidates)
        record["inline_posted"] = 0

        if config.dry_run:
            record["status"] = "dry_run" if should_post else "report_only"
            if not should_post:
                run["report_only_count"] += 1
            record["comment"] = build_comment(comment_pr, diff, combined, config)
            run["prs"].append(record)
            continue

        if not should_post:
            # 没有达到提交阈值：只写入报告，不评论、不落状态（下次可重新评估）。
            record["status"] = "report_only"
            run["report_only_count"] += 1
            record["comment"] = build_comment(comment_pr, diff, combined, config)
            run["prs"].append(record)
            continue

        # 先在具体代码行提交行内意见（各带独立标记，单条失败不阻断）
        inline_posted = 0
        inline_failed = 0
        for finding in inline_candidates:
            marker_text = inline_marker(key, finding.file, int(finding.line))
            if contains_inline_marker(existing_comments, marker_text):
                continue
            body = build_inline_comment(finding, key)
            try:
                inline_result = client.post_inline_comment(
                    number, body, finding.file, int(finding.line)
                )
            except Exception as exc:  # noqa: BLE001
                inline_failed += 1
                record["warnings"].append(
                    f"行内评论失败（{finding.file}:{finding.line}）：{exc}"
                )
                continue
            if inline_result.ok:
                inline_posted += 1
                existing_comments.append({"body": body})
            else:
                inline_failed += 1
                record["warnings"].append(
                    f"行内评论失败（{finding.file}:{finding.line}）：{inline_result.error_summary}"
                )
        record["inline_posted"] = inline_posted
        run["inline_total"] += inline_posted
        inline_meta = dict(
            reviewed_at=generated_at,
            severity=combined.risk_level,
            findings_count=len(combined.findings),
            engines=combined.engines,
            inline_posted=inline_posted,
        )

        # 汇总评论默认不提交（只写本地报告）；需要时用 --summary-comment / POST_SUMMARY_COMMENT=1
        comment = build_comment(
            comment_pr, diff, combined, config, inline_posted=inline_posted
        )
        record["comment"] = comment

        if config.summary_comment:
            try:
                result = client.post_review_comment(number, comment)
            except Exception as exc:  # noqa: BLE001
                record["status"] = "failed"
                record["error"] = f"提交汇总评论异常：{exc}"
                run["failed_count"] += 1
                run["prs"].append(record)
                continue
            if result.ok:
                record["status"] = "reviewed"
                run["posted_count"] += 1
                if key:
                    state.mark(config.repo, number, key, **inline_meta)
            else:
                record["status"] = "failed"
                record["error"] = f"提交汇总评论失败：{result.error_summary}"
                run["failed_count"] += 1
        elif inline_posted > 0:
            record["status"] = "reviewed"
            run["posted_count"] += 1
            if key:
                state.mark(config.repo, number, key, **inline_meta)
        elif inline_candidates and inline_failed > 0:
            record["status"] = "failed"
            record["error"] = f"行内评论全部失败（{inline_failed} 条）"
            run["failed_count"] += 1
        else:
            # 有发现但没有可挂载的代码行：只记录报告
            record["status"] = "report_only"
            run["report_only_count"] += 1
        run["prs"].append(record)

    counts = {key: 0 for key in SEVERITY_ORDER}
    total = 0
    for record in run["prs"]:
        for finding in record.get("findings") or []:
            severity = finding.get("severity", "info")
            if severity in counts:
                counts[severity] += 1
            total += 1
    run["severity_counts"] = counts
    run["findings_total"] = total

    return run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="npusim-review",
        description="检视 GitCode cann/npu-simulator 的 open PR，提交评论并生成 HTML 报告。",
    )
    parser.add_argument("--repo", default=None, help="目标仓库 owner/repo（默认 cann/npu-simulator）")
    parser.add_argument("--report-dir", default=None, help="报告输出目录（默认 report）")
    parser.add_argument("--state-file", default=None, help="状态文件（默认 state/reviews.json）")
    parser.add_argument("--dry-run", action="store_true", help="只生成报告，不提交评论")
    parser.add_argument("--force-review", action="store_true", help="忽略幂等状态，强制重新检视并评论")
    parser.add_argument("--max-prs", type=int, default=0, help="本次最多处理多少个 PR（0=用默认值）")
    parser.add_argument(
        "--min-severity",
        default=None,
        choices=["any", "high", "medium", "low", "info"],
        help="最高严重度达到该级别才提交评论（any=总是提交；默认 low，info 级只记录不评论）",
    )
    parser.add_argument(
        "--no-inline-comments",
        action="store_true",
        help="不提交行内评论（只发一条汇总评论）",
    )
    parser.add_argument(
        "--max-inline-comments",
        type=int,
        default=0,
        help="每个 PR 最多几条行内评论（0=默认 3）",
    )
    parser.add_argument(
        "--summary-comment",
        action="store_true",
        help="同时提交一条汇总评论（默认只发行内评论，汇总只写报告）",
    )
    parser.add_argument("--include-drafts", action="store_true", help="把草稿 PR 也纳入检视")
    parser.add_argument(
        "--offline-fixture",
        default=None,
        help="使用离线夹具运行（自动 dry-run，不访问网络）",
    )
    parser.add_argument("--version", action="store_true", help="打印版本后退出")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(__version__)
        return 0

    config = Config.from_args(args)

    if args.offline_fixture:
        config.dry_run = True
        try:
            client: Any = FixtureClient(args.offline_fixture)
        except Exception as exc:  # noqa: BLE001
            print(f"加载离线夹具失败：{exc}", file=sys.stderr)
            return 2
    else:
        try:
            client = GitcodeClient(config.repo)
        except GitcodeError as exc:
            print(f"初始化失败：{exc}", file=sys.stderr)
            return 2

    state = ReviewState(config.state_file)

    try:
        run = run_once(config, client, state)
    except GitcodeError as exc:
        print(f"运行失败：{exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"未预期错误：{exc}", file=sys.stderr)
        traceback.print_exc()
        return 1

    report_path = write_reports(run, config.report_dir)
    if not config.dry_run:
        state.save()

    print(
        "完成：open={open} reviewed={reviewed} posted={posted} inline={inline} "
        "skipped={skipped} report_only={report_only} failed={failed} findings={findings}".format(
            open=run["open_pr_count"],
            reviewed=run["reviewed_count"],
            posted=run["posted_count"],
            inline=run["inline_total"],
            skipped=run["skipped_count"] + run["draft_count"],
            report_only=run["report_only_count"],
            failed=run["failed_count"],
            findings=run["findings_total"],
        )
    )
    print(f"报告：{report_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
