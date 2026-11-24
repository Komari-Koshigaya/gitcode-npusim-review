"""生成 HTML 日报与历史索引。"""

from __future__ import annotations

import html
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from .comment import engines_label
from .engine.base import SEVERITY_LABEL, risk_label

STATUS_STYLE: Dict[str, tuple] = {
    "reviewed": ("本次已检视", "b-green"),
    "dry_run": ("试运行·未提交", "b-blue"),
    "unchanged": ("无新提交·跳过", "b-gray"),
    "skipped_existing": ("已检视过·跳过", "b-gray"),
    "draft_skipped": ("草稿·跳过", "b-gray"),
    "truncated": ("超出上限·未处理", "b-gray"),
    "report_only": ("无实质发现·未提交", "b-gray"),
    "failed": ("提交失败", "b-red"),
}

SEVERITY_STYLE = {
    "high": "b-red",
    "medium": "b-amber",
    "low": "b-blue",
    "info": "b-gray",
}

RISK_STYLE = {
    "high": ("高", "b-red"),
    "medium": ("中", "b-amber"),
    "low": ("低", "b-blue"),
    "info": ("提示", "b-gray"),
    "": ("无", "b-gray"),
}

CSS = """
:root{
  color-scheme: dark;
  --bg:#0a0f1c; --panel:#111c33; --panel-2:#0d1628; --text:#e6edf7; --muted:#93a4c3;
  --border:rgba(120,150,200,.18); --border-strong:rgba(120,150,200,.34);
  --accent:#5b8cff; --green:#34d399; --amber:#fbbf24; --red:#f87171; --gray:#94a3b8;
  --shadow:0 12px 34px rgba(0,0,0,.35);
}
@media (prefers-color-scheme: light){
  :root{
    color-scheme: light;
    --bg:#f4f7fc; --panel:#ffffff; --panel-2:#f7fafd; --text:#0f1b33; --muted:#5b6b86;
    --border:rgba(30,50,90,.12); --border-strong:rgba(30,50,90,.22);
    --shadow:0 12px 34px rgba(30,50,90,.08);
  }
}
*{box-sizing:border-box}
body{
  margin:0;color:var(--text);line-height:1.65;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans SC","PingFang SC","Microsoft YaHei",sans-serif;
  background:
    radial-gradient(1200px 600px at 8% -10%, rgba(91,140,255,.18), transparent 60%),
    radial-gradient(900px 500px at 100% 0%, rgba(34,211,238,.12), transparent 55%),
    var(--bg);
}
.container{max-width:1140px;margin:0 auto;padding:32px 20px 72px}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.hero{padding:8px 0 20px}
.hero .eyebrow{color:var(--muted);font-size:13px;letter-spacing:.08em;text-transform:uppercase}
.hero h1{margin:6px 0 8px;font-size:30px;line-height:1.25;letter-spacing:-.01em}
.hero .meta{color:var(--muted);font-size:14px}
.hero .links{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}
.hero .links a{font-size:13px;padding:6px 12px;border:1px solid var(--border-strong);border-radius:999px;background:var(--panel)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin:22px 0 8px}
.stat{background:var(--panel);border:1px solid var(--border);border-radius:16px;padding:16px 18px;box-shadow:var(--shadow)}
.stat .k{color:var(--muted);font-size:12px;letter-spacing:.05em}
.stat .v{font-size:28px;font-weight:750;margin-top:4px}
.section{margin-top:28px}
.section h2{font-size:18px;margin:0 0 12px;display:flex;align-items:center;gap:10px}
.section h2 .count{color:var(--muted);font-size:13px;font-weight:500}
.notice{border:1px solid var(--border-strong);background:var(--panel);border-radius:12px;padding:12px 16px;margin:14px 0;font-size:14px}
.notice.warn{border-color:rgba(251,191,36,.4);background:rgba(251,191,36,.08)}
.notice.blue{border-color:rgba(91,140,255,.4);background:rgba(91,140,255,.08)}
.table-wrap{overflow-x:auto;border:1px solid var(--border);border-radius:16px;background:var(--panel);box-shadow:var(--shadow)}
table{width:100%;border-collapse:collapse;font-size:14px;min-width:760px}
th,td{padding:11px 14px;border-bottom:1px solid var(--border);text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px;letter-spacing:.05em;text-transform:uppercase;background:var(--panel-2)}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(91,140,255,.05)}
td .title{font-weight:600}
td .sub{color:var(--muted);font-size:12px}
.badge{display:inline-flex;align-items:center;gap:6px;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:650;border:1px solid transparent;white-space:nowrap}
.b-green{background:rgba(52,211,153,.14);color:var(--green);border-color:rgba(52,211,153,.32)}
.b-red{background:rgba(248,113,113,.14);color:var(--red);border-color:rgba(248,113,113,.32)}
.b-amber{background:rgba(251,191,36,.14);color:var(--amber);border-color:rgba(251,191,36,.32)}
.b-blue{background:rgba(91,140,255,.16);color:var(--accent);border-color:rgba(91,140,255,.34)}
.b-gray{background:rgba(148,163,184,.14);color:var(--gray);border-color:rgba(148,163,184,.3)}
.pr{border:1px solid var(--border);border-radius:16px;background:var(--panel);margin:14px 0;overflow:hidden;box-shadow:var(--shadow)}
.pr>summary{cursor:pointer;padding:16px 18px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;list-style:none}
.pr>summary::-webkit-details-marker{display:none}
.pr>summary .num{font-weight:750;color:var(--muted)}
.pr>summary .ttl{font-weight:650}
.pr>summary .spacer{flex:1}
.pr-body{padding:4px 18px 20px;border-top:1px solid var(--border)}
.pr-body .grid{display:flex;flex-wrap:wrap;gap:16px;color:var(--muted);font-size:13px;margin:12px 0}
.finding{border-left:3px solid var(--border-strong);padding:10px 14px;margin:12px 0;background:var(--panel-2);border-radius:0 10px 10px 0}
.finding.high{border-left-color:var(--red)}
.finding.medium{border-left-color:var(--amber)}
.finding.low{border-left-color:var(--accent)}
.finding.info{border-left-color:var(--gray)}
.f-head{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:13px}
.f-head code{background:rgba(148,163,184,.14);padding:1px 7px;border-radius:6px;font-size:12.5px}
.f-head .origin{color:var(--muted);font-size:12px}
.f-msg{margin-top:6px;font-weight:550}
.f-sug{margin-top:4px;color:var(--muted);font-size:13px}
.snippet{background:rgba(0,0,0,.16);border:1px solid var(--border);border-radius:8px;padding:8px 10px;margin:8px 0 0;overflow:auto;font-size:12.5px;white-space:pre-wrap;word-break:break-all}
details.block{margin:12px 0}
details.block>summary{cursor:pointer;color:var(--accent);font-size:13px;padding:4px 0}
pre.comment{background:var(--panel-2);border:1px solid var(--border);border-radius:12px;padding:14px;overflow:auto;max-height:440px;font-size:12.5px;line-height:1.55;white-space:pre-wrap;word-break:break-word}
.err{border:1px solid rgba(248,113,113,.4);background:rgba(248,113,113,.08);border-radius:12px;padding:12px 16px;font-size:13.5px;color:var(--text);font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:pre-wrap;word-break:break-word}
.muted{color:var(--muted)}
.empty{color:var(--muted);padding:22px;text-align:center;border:1px dashed var(--border-strong);border-radius:16px}
.run-card{display:flex;gap:16px;align-items:center;flex-wrap:wrap;border:1px solid var(--border);border-radius:16px;background:var(--panel);padding:16px 18px;margin:12px 0;box-shadow:var(--shadow)}
.run-card .date{font-size:18px;font-weight:750;min-width:130px}
.run-card .nums{color:var(--muted);font-size:13px}
.run-card .spacer{flex:1}
footer{margin-top:44px;padding-top:18px;border-top:1px solid var(--border);color:var(--muted);font-size:13px;display:flex;flex-wrap:wrap;gap:12px;justify-content:space-between}
@media (max-width:640px){
  .hero h1{font-size:23px}
  .stat .v{font-size:23px}
}
""".strip()


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _badge(label: str, style: str) -> str:
    return f'<span class="badge {style}">{_esc(label)}</span>'


def _status_badge(status: str) -> str:
    label, style = STATUS_STYLE.get(status, (status or "未知", "b-gray"))
    return _badge(label, style)


def _risk_badge(risk: str) -> str:
    label, style = RISK_STYLE.get((risk or "").lower(), (risk_label(risk), "b-gray"))
    return _badge(label, style)


def now_local(tz_offset_hours: int) -> datetime:
    return datetime.now(timezone(timedelta(hours=tz_offset_hours)))


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN">\n<head>\n<meta charset="utf-8" />\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1" />\n'
        f"<title>{_esc(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n"
        f'<div class="container">\n{body}\n</div>\n</body>\n</html>\n'
    )


def _links(run: Dict[str, Any]) -> str:
    links = [
        f'<a href="{_esc(run.get("repo_url", "#"))}" target="_blank" rel="noopener">GitCode PR 列表 ↗</a>'
    ]
    github_url = run.get("github_repo_url")
    if github_url:
        links.append(
            f'<a href="{_esc(github_url)}" target="_blank" rel="noopener">GitHub 仓库 ↗</a>'
        )
    links.append('<a href="./index.html">历史报告</a>')
    return '<div class="links">' + "".join(links) + "</div>"


def _finding_html(finding: Dict[str, Any]) -> str:
    severity = (finding.get("severity") or "info").lower()
    origin = "AI" if finding.get("engine") == "llm" else "规则"
    file = finding.get("file") or ""
    if file:
        location = file + (f":{finding.get('line')}" if finding.get("line") else "")
    else:
        location = "（全局）"
    parts = [
        f'<div class="finding {_esc(severity)}">',
        '<div class="f-head">',
        _badge(SEVERITY_LABEL.get(severity, severity), SEVERITY_STYLE.get(severity, "b-gray")),
        f"<code>{_esc(location)}</code>",
        f'<span class="origin">{_esc(origin)} · {_esc(finding.get("rule", ""))}</span>',
        "</div>",
        f'<div class="f-msg">{_esc(finding.get("message", ""))}</div>',
    ]
    if finding.get("snippet"):
        parts.append(f'<pre class="snippet">{_esc(finding["snippet"])}</pre>')
    if finding.get("suggestion"):
        parts.append(f'<div class="f-sug">建议：{_esc(finding["suggestion"])}</div>')
    parts.append("</div>")
    return "".join(parts)


def _pr_detail_html(record: Dict[str, Any]) -> str:
    findings = record.get("findings") or []
    grouped: Dict[str, List[Dict[str, Any]]] = {"high": [], "medium": [], "low": [], "info": []}
    for finding in findings:
        severity = (finding.get("severity") or "info").lower()
        grouped.setdefault(severity, []).append(finding)

    body_parts: List[str] = ['<div class="grid">']
    body_parts.append(f"<span>提交：<code>{_esc((record.get('head_sha') or '')[:10])}</code></span>")
    body_parts.append(f"<span>变更：+{_esc(record.get('additions', 0))} / −{_esc(record.get('deletions', 0))}</span>")
    body_parts.append(f"<span>引擎：{_esc(engines_label(record.get('engines') or []))}</span>")
    body_parts.append(f"<span>发现：{_esc(len(findings))} 条</span>")
    body_parts.append("</div>")

    if record.get("error"):
        body_parts.append(f'<div class="err">{_esc(record["error"])}</div>')

    if findings:
        for severity in ("high", "medium", "low", "info"):
            group = grouped.get(severity) or []
            if not group:
                continue
            body_parts.append(
                f'<h3 style="font-size:15px;margin:18px 0 6px">'
                f"{_esc(SEVERITY_LABEL.get(severity, severity))}（{len(group)}）</h3>"
            )
            body_parts.extend(_finding_html(f) for f in group)
    elif record.get("status") == "reviewed":
        body_parts.append('<p class="muted">未发现需要提示的问题。</p>')

    warnings = record.get("warnings") or []
    if warnings:
        items = "".join(f"<li>{_esc(w)}</li>" for w in warnings)
        body_parts.append(f'<div class="notice warn"><strong>检视告警</strong><ul style="margin:6px 0 0 18px">{items}</ul></div>')

    if record.get("comment"):
        body_parts.append(
            '<details class="block"><summary>查看提交到 GitCode 的评论原文（Markdown）</summary>'
            f'<pre class="comment">{_esc(record["comment"])}</pre></details>'
        )

    number = record.get("number", "?")
    title = record.get("title", "")
    url = record.get("url") or "#"
    return (
        f'<details class="pr"><summary>'
        f'<span class="num">#{_esc(number)}</span>'
        f'<span class="ttl">{_esc(title)}</span>'
        f'<span class="spacer"></span>'
        f"{_status_badge(record.get('status', ''))}"
        f"{_risk_badge(record.get('risk', ''))}"
        f"</summary>"
        f'<div class="pr-body">{"".join(body_parts)}</div>'
        f'<div class="pr-body" style="border-top:none;padding-top:0">'
        f'<a href="{_esc(url)}" target="_blank" rel="noopener">在 GitCode 打开 PR ↗</a></div>'
        f"</details>"
    )


def render_run(run: Dict[str, Any]) -> str:
    records = run.get("prs") or []
    generated = run.get("generated_at_display") or run.get("generated_at", "")

    hero = (
        '<header class="hero">'
        '<div class="eyebrow">Automated Pull Request Review</div>'
        f'<h1>npu-simulator PR 检视日报 · {_esc(run.get("date", ""))}</h1>'
        f'<div class="meta">生成时间：{_esc(generated)} · 目标仓库：'
        f'<a href="{_esc(run.get("repo_url", "#"))}" target="_blank" rel="noopener">{_esc(run.get("repo", ""))}</a></div>'
        f"{_links(run)}"
        "</header>"
    )

    stats = (
        '<div class="stats">'
        f'<div class="stat"><div class="k">开启中的 PR</div><div class="v">{_esc(run.get("open_pr_count", 0))}</div></div>'
        f'<div class="stat"><div class="k">本次检视</div><div class="v">{_esc(run.get("reviewed_count", 0))}</div></div>'
        f'<div class="stat"><div class="k">已提交意见</div><div class="v">{_esc(run.get("posted_count", 0))}</div></div>'
        f'<div class="stat"><div class="k">跳过（无新提交）</div><div class="v">{_esc(run.get("skipped_count", 0))}</div></div>'
        f'<div class="stat"><div class="k">仅报告·未提交</div><div class="v">{_esc(run.get("report_only_count", 0))}</div></div>'
        f'<div class="stat"><div class="k">失败</div><div class="v">{_esc(run.get("failed_count", 0))}</div></div>'
        f'<div class="stat"><div class="k">发现总数</div><div class="v">{_esc(run.get("findings_total", 0))}</div></div>'
        "</div>"
    )

    notices: List[str] = []
    if run.get("dry_run"):
        notices.append('<div class="notice blue">本次为试运行（dry-run）：仅生成报告，未向 GitCode 提交评论。</div>')
    if run.get("truncated"):
        notices.append('<div class="notice warn">开放 PR 数量超过上限，本次仅处理了前一部分。</div>')
    if not run.get("llm_enabled"):
        notices.append('<div class="notice">未配置 LLM_API_KEY，本次仅使用规则检视。</div>')
    for warning in run.get("warnings") or []:
        notices.append(f'<div class="notice warn">{_esc(warning)}</div>')
    notice_html = "".join(notices)

    rows: List[str] = []
    for record in records:
        number = record.get("number", "?")
        url = record.get("url") or "#"
        author = record.get("author") or "—"
        branch = record.get("branch") or ""
        risk_html = _risk_badge(record.get("risk", "")) if record.get("status") in {"reviewed", "dry_run"} else ""
        rows.append(
            "<tr>"
            f'<td><a href="{_esc(url)}" target="_blank" rel="noopener">#{_esc(number)}</a></td>'
            f'<td><span class="title">{_esc(record.get("title", ""))}</span>'
            f'<div class="sub">{_esc(branch)}</div></td>'
            f"<td>{_esc(author)}</td>"
            f"<td>{_status_badge(record.get('status', ''))}</td>"
            f"<td>{risk_html}</td>"
            f"<td>{_esc(record.get('findings_count', 0))}</td>"
            "</tr>"
        )
    if rows:
        table = (
            '<div class="table-wrap"><table><thead><tr>'
            "<th>PR</th><th>标题 / 分支</th><th>作者</th><th>状态</th><th>风险</th><th>发现</th>"
            "</tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></div>"
        )
    else:
        table = '<div class="empty">本次没有需要展示的 open PR。</div>'

    details = "".join(
        _pr_detail_html(record)
        for record in records
        if record.get("findings") or record.get("comment") or record.get("error") or record.get("status") == "reviewed"
    )
    details_section = (
        f'<section class="section"><h2>已检视 PR 明细</h2>{details or "<div class=\"empty\">没有新的检视结果。</div>"}</section>'
    )

    body = (
        hero
        + stats
        + notice_html
        + '<section class="section"><h2>开启中的 PR 一览 '
        + f'<span class="count">共 {_esc(len(records))} 个</span></h2>{table}</section>'
        + details_section
        + '<footer>'
        + f'<span>由 GitHub Actions 自动生成 · <a href="{_esc(run.get("repo_url", "#"))}" target="_blank" rel="noopener">cann/npu-simulator</a></span>'
        + '<span>同一提交不会重复评论</span>'
        + "</footer>"
    )
    title = f'npu-simulator PR 检视日报 · {run.get("date", "")}'
    return _page(title, body)


def render_index(runs: List[Dict[str, Any]]) -> str:
    hero = (
        '<header class="hero">'
        '<div class="eyebrow">Automated Pull Request Review</div>'
        "<h1>npu-simulator PR 检视报告</h1>"
        '<div class="meta">由 GitHub Actions 定时运行，按日期归档每次检视结果。</div>'
        '<div class="links">'
        '<a href="https://gitcode.com/cann/npu-simulator/pulls" target="_blank" rel="noopener">GitCode PR 列表 ↗</a>'
        "</div></header>"
    )

    if not runs:
        body = hero + '<div class="empty">还没有运行记录。首次定时任务完成后会在这里出现日报。</div>'
    else:
        cards: List[str] = []
        for run in runs:
            date = run.get("date", "")
            file = run.get("file") or f"{date}.html"
            counts = run.get("severity_counts") or {}
            summary = (
                f"检视 {run.get('reviewed_count', 0)} · 提交意见 {run.get('posted_count', 0)} · "
                f"仅报告 {run.get('report_only_count', 0)} · 跳过 {run.get('skipped_count', 0)} · "
                f"失败 {run.get('failed_count', 0)} · 发现 {run.get('findings_total', 0)}"
            )
            badges = ""
            if run.get("dry_run"):
                badges += _badge("试运行", "b-blue")
            if counts.get("high"):
                badges += _badge(f"严重 {counts['high']}", "b-red")
            cards.append(
                '<div class="run-card">'
                f'<div class="date"><a href="{_esc(file)}">{_esc(date)}</a></div>'
                f'<div class="nums">{_esc(summary)}</div>'
                '<div class="spacer"></div>'
                f"<div>{badges}</div>"
                "</div>"
            )
        body = hero + '<section class="section"><h2>历史运行 <span class="count">共 ' + _esc(len(runs)) + " 次</span></h2>" + "".join(cards) + "</section>"

    body += (
        '<footer><span>由 GitHub Actions 自动生成</span>'
        '<span>同一提交不会重复评论</span></footer>'
    )
    return _page("npu-simulator PR 检视报告", body)


def summary_entry(run: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "date": run.get("date", ""),
        "generated_at": run.get("generated_at", ""),
        "generated_at_display": run.get("generated_at_display", ""),
        "repo": run.get("repo", ""),
        "open_pr_count": run.get("open_pr_count", 0),
        "reviewed_count": run.get("reviewed_count", 0),
        "posted_count": run.get("posted_count", 0),
        "skipped_count": run.get("skipped_count", 0),
        "report_only_count": run.get("report_only_count", 0),
        "failed_count": run.get("failed_count", 0),
        "findings_total": run.get("findings_total", 0),
        "severity_counts": run.get("severity_counts", {}),
        "dry_run": bool(run.get("dry_run")),
        "file": f'{run.get("date", "")}.html',
    }


def write_reports(run: Dict[str, Any], report_dir: Path) -> Path:
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    date = run.get("date") or "unknown"
    run_path = report_dir / f"{date}.html"
    run_path.write_text(render_run(run), encoding="utf-8")

    runs_path = report_dir / "runs.json"
    runs: List[Dict[str, Any]] = []
    if runs_path.exists():
        try:
            loaded = json.loads(runs_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                runs = [item for item in loaded if isinstance(item, dict)]
        except (OSError, json.JSONDecodeError):
            runs = []

    entry = summary_entry(run)
    runs = [item for item in runs if item.get("date") != date]
    runs.append(entry)
    runs.sort(key=lambda item: item.get("date", ""), reverse=True)

    runs_path.write_text(
        json.dumps(runs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (report_dir / "index.html").write_text(render_index(runs), encoding="utf-8")
    return run_path
