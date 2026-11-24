import json

from reviewer.report import render_run, summary_entry, write_reports


def make_run(date="2026-11-24"):
    return {
        "date": date,
        "generated_at": f"{date}T09:17:00+08:00",
        "generated_at_display": f"{date} 09:17:00 +0800",
        "repo": "cann/npu-simulator",
        "repo_url": "https://gitcode.com/cann/npu-simulator/pulls",
        "github_repo_url": "https://github.com/Komari-Koshigaya/gitcode-npusim-review",
        "dry_run": False,
        "llm_enabled": True,
        "truncated": False,
        "open_pr_count": 2,
        "considered_count": 2,
        "draft_count": 0,
        "reviewed_count": 1,
        "posted_count": 1,
        "skipped_count": 1,
        "failed_count": 0,
        "findings_total": 1,
        "severity_counts": {"high": 1, "medium": 0, "low": 0, "info": 0},
        "warnings": [],
        "prs": [
            {
                "number": 1,
                "title": "<script>alert(1)</script>",
                "author": "alice",
                "url": "https://gitcode.com/cann/npu-simulator/pulls/1",
                "head_sha": "a" * 40,
                "head_short": "aaaaaaaa",
                "branch": "feature/1 -> master",
                "status": "reviewed",
                "risk": "high",
                "findings_count": 1,
                "findings": [
                    {
                        "engine": "rules",
                        "rule": "hardcoded-secret",
                        "severity": "high",
                        "file": "a.c",
                        "line": 3,
                        "message": "bad <b>thing",
                        "snippet": "<img src=x onerror=alert(1)>",
                        "suggestion": "fix",
                    }
                ],
                "comment": "hello <script>alert('x')</script>",
                "warnings": [],
                "error": "",
                "engines": ["rules"],
                "additions": 1,
                "deletions": 1,
            },
            {
                "number": 2,
                "title": "ok",
                "author": "bob",
                "url": "https://gitcode.com/cann/npu-simulator/pulls/2",
                "head_sha": "b" * 40,
                "head_short": "bbbbbbbb",
                "branch": "feature/2 -> master",
                "status": "unchanged",
                "risk": "",
                "findings_count": 0,
                "findings": [],
                "comment": "",
                "warnings": [],
                "error": "",
                "engines": [],
                "additions": 0,
                "deletions": 0,
            },
        ],
    }


def test_render_run_escapes_untrusted_content():
    html = render_run(make_run())
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "2026-11-24" in html
    assert "hardcoded-secret" in html


def test_write_reports_creates_files_and_upserts(tmp_path):
    run = make_run("2026-11-24")
    path = write_reports(run, tmp_path)
    assert path.name == "2026-11-24.html"
    assert (tmp_path / "index.html").exists()

    runs = json.loads((tmp_path / "runs.json").read_text(encoding="utf-8"))
    assert len(runs) == 1
    assert runs[0]["date"] == "2026-11-24"
    assert runs[0]["file"] == "2026-11-24.html"

    # 同一天再次运行应覆盖而不是追加
    write_reports(make_run("2026-11-24"), tmp_path)
    runs = json.loads((tmp_path / "runs.json").read_text(encoding="utf-8"))
    assert len(runs) == 1


def test_index_sorted_newest_first(tmp_path):
    write_reports(make_run("2026-11-22"), tmp_path)
    write_reports(make_run("2026-11-24"), tmp_path)
    write_reports(make_run("2026-11-23"), tmp_path)
    runs = json.loads((tmp_path / "runs.json").read_text(encoding="utf-8"))
    assert [item["date"] for item in runs] == ["2026-11-24", "2026-11-23", "2026-11-22"]
    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "2026-11-24.html" in index


def test_summary_entry_shape():
    entry = summary_entry(make_run())
    assert entry["date"] == "2026-11-24"
    assert entry["posted_count"] == 1
    assert entry["file"] == "2026-11-24.html"
