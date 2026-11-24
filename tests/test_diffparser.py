from reviewer.diffparser import (
    DiffData,
    DiffLine,
    FileDiff,
    parse_files_payload,
    parse_text_diff,
    render_for_llm,
)


def test_parse_files_payload_extracts_lines_and_flags():
    payload = {
        "added_lines": 2,
        "remove_lines": 1,
        "count": 1,
        "diffs": [
            {
                "new_path": "src/k.c",
                "old_path": "src/k.c",
                "content": {
                    "text": [
                        {"type": "old", "old_line": 5, "line_content": "old()"},
                        {"type": "new", "new_line": 5, "line_content": "new()"},
                        {"type": "new", "new_line": 6, "line_content": "print(1)"},
                    ]
                },
            }
        ],
    }
    diff = parse_files_payload(payload, number=7, title="t")
    assert diff.number == 7
    assert diff.source == "api"
    file = diff.files[0]
    assert file.path == "src/k.c"
    assert file.added == 2
    assert file.removed == 1
    adds = [(fd.path, ln.new_line, ln.text) for fd, ln in diff.added()]
    assert adds == [("src/k.c", 5, "new()"), ("src/k.c", 6, "print(1)")]
    assert diff.is_test_file("tests/test_x.py")
    assert diff.is_test_file("src/foo_test.go")
    assert not diff.is_test_file("src/k.c")


def test_parse_files_payload_handles_odd_line_numbers():
    payload = {
        "diffs": [
            {
                "new_path": "a.py",
                "old_path": "",
                "content": {
                    "text": [
                        {"type": "new", "new_line": {"line": 12}, "line_content": "x = 1"},
                        {"type": "new", "new_line": "...", "line_content": "y = 2"},
                    ]
                },
            }
        ]
    }
    diff = parse_files_payload(payload)
    file = diff.files[0]
    assert file.new_file is True
    assert file.lines[0].new_line == 12
    assert file.lines[1].new_line is None


def test_parse_files_payload_real_gitcode_statistic_shape():
    payload = {
        "added_lines": 2,
        "remove_lines": 1,
        "count": 1,
        "diffs": [
            {
                "new_blob_id": "abc",
                "added_lines": 2,
                "remove_lines": 1,
                "statistic": {
                    "type": "text_type",
                    "path": "docs/a.md",
                    "old_path": "docs/a.md",
                    "new_path": "docs/a.md",
                    "view": False,
                },
                "head": {"url": "https://example", "commit_id": "deadbeef"},
                "content": {
                    "text": [
                        {
                            "type": "match",
                            "old_line": "...",
                            "new_line": "...",
                            "line_content": "@@ -2,7 +2,7 @@",
                        },
                        {
                            "type": None,
                            "old_line": {"line_num": 2},
                            "new_line": {"line_num": 2},
                            "line_content": " ## 概述",
                        },
                        {
                            "type": "new",
                            "old_line": "...",
                            "new_line": {"line_num": 3, "line_code": "x"},
                            "line_content": "+新增",
                        },
                        {
                            "type": "old",
                            "old_line": {"line_num": 4},
                            "new_line": "...",
                            "line_content": "-删除",
                        },
                    ]
                },
            }
        ],
    }
    diff = parse_files_payload(payload, number=70)
    file = diff.files[0]
    assert file.path == "docs/a.md"
    assert file.new_path == "docs/a.md"
    assert file.added == 2
    assert file.removed == 1
    adds = list(diff.added())
    assert adds[0][1].new_line == 3
    assert adds[0][1].text == "新增"  # 前缀 "+" 已剥离
    assert file.lines[1].text == "## 概述"  # 上下文前缀空格已剥离


def test_parse_text_diff_fallback():
    text = (
        "PR #1: t\n"
        "Branch: a -> b\n"
        "Changes: +1 -1 in 1 file(s)\n\n"
        "diff --git a/src/x.py b/src/x.py\n"
        "+print(1)\n"
        "-old\n"
        " ctx\n"
    )
    diff = parse_text_diff(text)
    assert diff.source == "text"
    assert diff.added_lines == 1
    adds = list(diff.added())
    assert len(adds) == 1
    assert adds[0][0].path == "src/x.py"
    assert adds[0][1].text == "print(1)"


def test_render_for_llm_includes_line_numbers_and_truncates():
    file = FileDiff(
        path="src/a.py",
        old_path="src/a.py",
        new_path="src/a.py",
        lines=[
            DiffLine(text="x = 1", new_line=10, kind="add"),
            DiffLine(text="y = 2", new_line=11, kind="add"),
        ],
    )
    file.added = 2
    diff = DiffData(files=[file], added_lines=2)
    rendered = render_for_llm(diff, max_chars=1000)
    assert "### src/a.py" in rendered
    assert "10 +x = 1" in rendered
    assert "11 +y = 2" in rendered

    rendered_small = render_for_llm(diff, max_chars=5)
    assert diff.truncated is True
    assert "已截断" in rendered_small
