from reviewer.comment import contains_marker, marker
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


def test_contains_marker_matches_exact_sha():
    sha = "a" * 40
    comments = [{"body": f"hello\n{marker(sha)}\nbye"}]
    assert contains_marker(comments, sha) is True
    assert contains_marker(comments, "b" * 40) is False
    assert contains_marker([], sha) is False
    assert contains_marker([{"body": "no marker"}], sha) is False
