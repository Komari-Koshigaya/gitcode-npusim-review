"""验证“已检视过就跳过、不重复评论”的双层幂等。"""

from reviewer.cli import FixtureClient, run_once
from reviewer.config import Config, LLMConfig
from reviewer.state import ReviewState
from tests.support import (
    REPO,
    SHA_A,
    SHA_B,
    SHA_C,
    SHA_D,
    make_payload,
    make_pr,
    write_fixture,
)


def _config(tmp_path, dry_run=False, min_severity="low"):
    return Config(
        repo=REPO,
        report_dir=tmp_path,
        state_file=tmp_path / "state.json",
        dry_run=dry_run,
        min_severity_to_post=min_severity,
        llm=LLMConfig(),  # 无 key -> 仅规则
    )


def _payload_with_secret():
    return make_payload(
        [{"type": "new", "new_line": 3, "line_content": 'password = "hunter2secret";'}]
    )


def test_layer1_skips_same_head_sha(tmp_path):
    fixture = write_fixture(
        tmp_path / "f.json",
        [make_pr(101, SHA_A, files_payload=_payload_with_secret())],
    )
    state = ReviewState(tmp_path / "state.json")
    state.mark(REPO, 101, SHA_A)
    client = FixtureClient(fixture)

    run = run_once(_config(tmp_path), client, state)

    assert run["prs"][0]["status"] == "unchanged"
    assert client.posted == []
    assert run["posted_count"] == 0
    assert run["skipped_count"] == 1


def test_layer2_existing_marker_prevents_duplicate(tmp_path):
    marker_comment = {"body": "历史评论\n<!-- npu-review sha=" + SHA_B + " -->\n"}
    fixture = write_fixture(
        tmp_path / "f.json",
        [
            make_pr(
                102,
                SHA_B,
                files_payload=_payload_with_secret(),
                comments=[marker_comment],
            )
        ],
    )
    state = ReviewState(tmp_path / "state.json")
    client = FixtureClient(fixture)

    run = run_once(_config(tmp_path), client, state)

    assert run["prs"][0]["status"] == "skipped_existing"
    assert client.posted == []
    assert state.get(REPO, 102)["source"] == "comment-marker"


def test_fresh_pr_posts_once_then_skips_on_rerun(tmp_path):
    fixture = write_fixture(
        tmp_path / "f.json",
        [make_pr(103, SHA_C, files_payload=_payload_with_secret())],
    )
    state = ReviewState(tmp_path / "state.json")
    client = FixtureClient(fixture)
    config = _config(tmp_path)

    first = run_once(config, client, state)
    assert first["prs"][0]["status"] == "reviewed"
    assert len(client.posted) == 1
    assert f"npu-review sha={SHA_C}" in client.posted[0]["body"]
    state.save()

    # 第二次运行：状态已持久化，同一 SHA 直接跳过
    client2 = FixtureClient(fixture)
    state2 = ReviewState(tmp_path / "state.json")
    second = run_once(config, client2, state2)
    assert second["prs"][0]["status"] == "unchanged"
    assert client2.posted == []
    assert second["posted_count"] == 0


def test_new_sha_on_same_pr_is_reviewed_again(tmp_path):
    state = ReviewState(tmp_path / "state.json")
    state.mark(REPO, 104, SHA_C)
    fixture = write_fixture(
        tmp_path / "f.json",
        [make_pr(104, SHA_D, files_payload=_payload_with_secret())],
    )
    client = FixtureClient(fixture)

    run = run_once(_config(tmp_path), client, state)

    assert run["prs"][0]["status"] == "reviewed"
    assert len(client.posted) == 1


def test_dry_run_does_not_post_or_mark(tmp_path):
    fixture = write_fixture(
        tmp_path / "f.json",
        [make_pr(105, SHA_D, files_payload=_payload_with_secret())],
    )
    state = ReviewState(tmp_path / "state.json")
    client = FixtureClient(fixture)

    run = run_once(_config(tmp_path, dry_run=True), client, state)

    assert run["prs"][0]["status"] == "dry_run"
    assert client.posted == []
    assert state.get(REPO, 105) is None


def test_dry_run_respects_marker_without_marking_state(tmp_path):
    marker_comment = {"body": "<!-- npu-review sha=" + SHA_B + " -->"}
    fixture = write_fixture(
        tmp_path / "f.json",
        [
            make_pr(
                107,
                SHA_B,
                files_payload=_payload_with_secret(),
                comments=[marker_comment],
            )
        ],
    )
    state = ReviewState(tmp_path / "state.json")
    client = FixtureClient(fixture)

    run = run_once(_config(tmp_path, dry_run=True), client, state)

    assert run["prs"][0]["status"] == "skipped_existing"
    assert client.posted == []
    assert state.get(REPO, 107) is None


def test_docs_only_pr_is_report_only(tmp_path):
    payload = make_payload(
        [{"type": "new", "new_line": 1, "line_content": "hello doc"}],
        path="docs/guide.md",
    )
    fixture = write_fixture(tmp_path / "f.json", [make_pr(108, SHA_A, files_payload=payload)])
    state = ReviewState(tmp_path / "state.json")
    client = FixtureClient(fixture)

    run = run_once(_config(tmp_path), client, state)

    assert run["prs"][0]["status"] == "report_only"
    assert run["report_only_count"] == 1
    assert client.posted == []
    assert state.get(REPO, 108) is None


def test_info_only_report_only_by_default(tmp_path):
    payload = make_payload(
        [{"type": "new", "new_line": 1, "line_content": "int x = 1;"}],
        path="src/a.c",
    )
    fixture = write_fixture(tmp_path / "f.json", [make_pr(109, SHA_A, files_payload=payload)])
    state = ReviewState(tmp_path / "state.json")
    client = FixtureClient(fixture)

    run = run_once(_config(tmp_path), client, state)  # 默认 min_severity=low：info 不评论

    assert run["prs"][0]["status"] == "report_only"
    assert run["report_only_count"] == 1
    assert client.posted == []
    assert state.get(REPO, 109) is None


def test_info_only_posted_when_threshold_info(tmp_path):
    payload = make_payload(
        [{"type": "new", "new_line": 1, "line_content": "int x = 1;"}],
        path="src/a.c",
    )
    fixture = write_fixture(tmp_path / "f.json", [make_pr(110, SHA_A, files_payload=payload)])
    state = ReviewState(tmp_path / "state.json")
    client = FixtureClient(fixture)

    run = run_once(_config(tmp_path, min_severity="info"), client, state)

    assert run["prs"][0]["status"] == "reviewed"
    assert len(client.posted) == 1


def test_low_finding_posted_by_default(tmp_path):
    payload = make_payload(
        [{"type": "new", "new_line": 1, "line_content": 'printf("debug");'}],
        path="src/a.c",
    )
    fixture = write_fixture(tmp_path / "f.json", [make_pr(111, SHA_A, files_payload=payload)])
    state = ReviewState(tmp_path / "state.json")
    client = FixtureClient(fixture)

    run = run_once(_config(tmp_path), client, state)  # low（debug-print）应提交

    assert run["prs"][0]["status"] == "reviewed"
    assert len(client.posted) == 1


def test_low_finding_posts_inline_comment(tmp_path):
    payload = make_payload(
        [{"type": "new", "new_line": 7, "line_content": 'printf("debug");'}],
        path="src/a.c",
    )
    fixture = write_fixture(tmp_path / "f.json", [make_pr(112, SHA_A, files_payload=payload)])
    state = ReviewState(tmp_path / "state.json")
    client = FixtureClient(fixture)

    run = run_once(_config(tmp_path), client, state)

    assert run["prs"][0]["status"] == "reviewed"
    assert len(client.posted) == 1  # 汇总评论
    assert len(client.inline) == 1  # 行内评论
    assert client.inline[0]["path"] == "src/a.c"
    assert client.inline[0]["position"] == 7
    assert "npu-review-inline sha=" in client.inline[0]["body"]
    assert "行内意见" in client.posted[0]["body"]
    assert run["inline_total"] == 1


def test_inline_comments_can_be_disabled(tmp_path):
    payload = make_payload(
        [{"type": "new", "new_line": 7, "line_content": 'printf("debug");'}],
        path="src/a.c",
    )
    fixture = write_fixture(tmp_path / "f.json", [make_pr(113, SHA_A, files_payload=payload)])
    state = ReviewState(tmp_path / "state.json")
    client = FixtureClient(fixture)
    config = _config(tmp_path)
    config.inline_comments = False

    run = run_once(config, client, state)

    assert run["prs"][0]["status"] == "reviewed"
    assert len(client.posted) == 1
    assert client.inline == []
    assert run["inline_total"] == 0


def test_info_only_has_no_inline_comment(tmp_path):
    payload = make_payload(
        [{"type": "new", "new_line": 1, "line_content": "int x = 1;"}],
        path="src/a.c",
    )
    fixture = write_fixture(tmp_path / "f.json", [make_pr(114, SHA_A, files_payload=payload)])
    state = ReviewState(tmp_path / "state.json")
    client = FixtureClient(fixture)

    run = run_once(_config(tmp_path), client, state)

    assert run["prs"][0]["status"] == "report_only"
    assert client.posted == []
    assert client.inline == []
    assert run["inline_total"] == 0


def test_draft_pr_is_skipped_by_default(tmp_path):
    fixture = write_fixture(
        tmp_path / "f.json",
        [make_pr(106, SHA_A, draft=True, files_payload=_payload_with_secret())],
    )
    state = ReviewState(tmp_path / "state.json")
    client = FixtureClient(fixture)

    run = run_once(_config(tmp_path), client, state)

    assert run["prs"][0]["status"] == "draft_skipped"
    assert run["draft_count"] == 1
    assert client.posted == []
