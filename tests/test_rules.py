from reviewer.config import Config
from reviewer.diffparser import DiffData, DiffLine, FileDiff
from reviewer.engine import rules


def make_file(path, entries, deleted=False, new_file=False):
    file = FileDiff(
        path=path,
        old_path="" if new_file else path,
        new_path="" if deleted else path,
        deleted=deleted,
        new_file=new_file,
    )
    cursor = 1
    for kind, text in entries:
        if kind == "add":
            file.lines.append(DiffLine(text=text, new_line=cursor, kind="add"))
            file.added += 1
            cursor += 1
        elif kind == "del":
            file.lines.append(DiffLine(text=text, old_line=cursor, kind="del"))
            file.removed += 1
        else:
            file.lines.append(DiffLine(text=text, new_line=cursor, kind="ctx"))
            cursor += 1
    return file


def rules_hit(result):
    return {finding.rule for finding in result.findings}


def test_rules_detect_common_issues():
    code = make_file(
        "src/kernel.c",
        [
            ("add", 'password = "hunter2secret";'),
            ("add", "<<<<<<< HEAD"),
            ("add", 'printf("debug");'),
            ("add", "except: pass"),
            ("add", "# TODO: handle error"),
            ("add", "x" * 250),
        ],
    )
    result = rules.review(DiffData(files=[code]), Config())
    hits = rules_hit(result)
    assert "hardcoded-secret" in hits
    assert "merge-conflict" in hits
    assert "debug-print" in hits
    assert "swallowed-exception" in hits
    assert "todo-marker" in hits
    assert "long-line" in hits
    assert result.risk_level == "high"


def test_generated_file_skips_long_line_and_debug():
    generated = make_file("package-lock.json", [("add", "x" * 300), ("add", 'console.log("hi")')])
    result = rules.review(DiffData(files=[generated]), Config())
    hits = rules_hit(result)
    assert "long-line" not in hits
    assert "debug-print" not in hits


def test_deleted_file_and_large_change():
    deleted = make_file("old/a.c", [("del", "int x;")], deleted=True)
    big = make_file("src/big.c", [("add", f"line {i}") for i in range(10)])
    result = rules.review(DiffData(files=[deleted, big]), Config(large_file_lines=5))
    hits = rules_hit(result)
    assert "deleted-file" in hits
    assert "large-change" in hits


def test_missing_tests_reported_only_without_test_changes():
    code = make_file("src/a.c", [("add", "int x = 1;")])
    without_tests = rules.review(DiffData(files=[code]), Config())
    assert "missing-tests" in rules_hit(without_tests)

    code2 = make_file("src/a.c", [("add", "int x = 1;")])
    test = make_file("tests/test_a.c", [("add", "assert(1);")])
    with_tests = rules.review(DiffData(files=[code2, test]), Config())
    assert "missing-tests" not in rules_hit(with_tests)


def test_docs_long_line_is_ignored():
    docs = make_file("docs/guide.md", [("add", "长" * 300)])
    result = rules.review(DiffData(files=[docs]), Config())
    assert "long-line" not in rules_hit(result)


def test_docs_change_does_not_trigger_missing_tests():
    docs = make_file("docs/guide.md", [("add", "hello")])
    result = rules.review(DiffData(files=[docs]), Config())
    assert "missing-tests" not in rules_hit(result)


def test_empty_diff_yields_no_findings():
    result = rules.review(DiffData(files=[]), Config())
    assert result.findings == []
    assert result.risk_level == ""
    assert result.engines == ["rules"]
