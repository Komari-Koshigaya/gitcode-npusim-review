from reviewer.comment import (
    contains_inline_marker,
    contains_inline_sha,
    contains_marker,
    inline_marker,
    marker,
)
from reviewer.state import ReviewState


def test_state_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    state = ReviewState(path)
    assert state.is_reviewed("cann/npu-simulator", 1, "abc") is False

    state.mark("cann/npu-simulator", 1, "abc", severity="high")
    assert state.is_reviewed("cann/npu-simulator", 1, "abc") is True
    assert state.is_reviewed("cann/npu-simulator", 1, "def") is False
    state.save()

    reloaded = ReviewState(path)
    record = reloaded.get("cann/npu-simulator", 1)
    assert record["head_sha"] == "abc"
    assert record["severity"] == "high"


def test_state_handles_corrupt_file(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("not json", encoding="utf-8")
    state = ReviewState(path)
    assert state.is_reviewed("cann/npu-simulator", 1, "abc") is False
    state.mark("cann/npu-simulator", 2, "xyz")
    assert state.is_reviewed("cann/npu-simulator", 2, "xyz") is True


def test_inline_marker_roundtrip():
    sha = "a" * 40
    text = inline_marker(sha, "src/a.c", 7)
    assert "npu-review-inline sha=" in text
    assert "file=src/a.c" in text and "line=7" in text
    comments = [{"body": f"hello\n{text}\nbye"}]
    assert contains_inline_marker(comments, text) is True
    assert contains_inline_marker(comments, inline_marker(sha, "src/a.c", 8)) is False
    assert contains_inline_marker([], text) is False


def test_contains_inline_sha_matches_submission():
    sha = "a" * 40
    comments = [{"body": inline_marker(sha, "src/a.c", 3)}]
    assert contains_inline_sha(comments, sha) is True
    assert contains_inline_sha(comments, "b" * 40) is False
    assert contains_inline_sha([], sha) is False


def test_contains_marker_matches_exact_sha():
    sha = "a" * 40
    comments = [{"body": f"hello\n{marker(sha)}\nbye"}]
    assert contains_marker(comments, sha) is True
    assert contains_marker(comments, "b" * 40) is False
    assert contains_marker([], sha) is False
    assert contains_marker([{"body": "no marker"}], sha) is False
