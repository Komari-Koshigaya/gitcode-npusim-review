import reviewer.engine.llm as llm
from reviewer.config import Config, LLMConfig
from reviewer.diffparser import DiffData, DiffLine, FileDiff


def _diff():
    file = FileDiff(
        path="src/a.c",
        old_path="src/a.c",
        new_path="src/a.c",
        added=1,
        lines=[DiffLine(text="printf(1);", new_line=3, kind="add")],
    )
    return DiffData(files=[file], added_lines=1)


def test_no_key_degrades_gracefully():
    result = llm.review(_diff(), {"number": 1}, Config(llm=LLMConfig(api_key="")))
    assert result.engines == []
    assert result.warnings


def test_parse_json_object_handles_fences_and_prefix():
    assert llm._parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm._parse_json_object('说明文字 {"b": 2} 结束') == {"b": 2}


def test_normalize_severity_aliases():
    assert llm._normalize_severity("Critical") == "high"
    assert llm._normalize_severity("warning") == "medium"
    assert llm._normalize_severity("weird") == "info"


def test_review_success_and_risk_escalation(monkeypatch):
    def fake_chat(cfg, prompt):
        return (
            '{"summary": "存在风险", "risk_level": "medium", "findings": ['
            '{"severity": "high", "file": "src/a.c", "line": 3, '
            '"issue": "硬编码", "suggestion": "改掉"}]}'
        )

    monkeypatch.setattr(llm, "_chat", fake_chat)
    result = llm.review(_diff(), {"number": 1, "title": "t"}, Config(llm=LLMConfig(api_key="k")))
    assert result.engines == ["llm"]
    assert len(result.findings) == 1
    assert result.findings[0].severity == "high"
    assert result.risk_level == "high"  # 由 high finding 升级
    assert result.summary == "存在风险"


def test_review_failure_degrades(monkeypatch):
    def boom(cfg, prompt):
        raise RuntimeError("boom")

    monkeypatch.setattr(llm, "_chat", boom)
    result = llm.review(_diff(), {"number": 1}, Config(llm=LLMConfig(api_key="k")))
    assert result.engines == []
    assert any("LLM" in warning for warning in result.warnings)


def test_review_bad_json_degrades(monkeypatch):
    monkeypatch.setattr(llm, "_chat", lambda cfg, prompt: "not json")
    result = llm.review(_diff(), {"number": 1}, Config(llm=LLMConfig(api_key="k")))
    assert result.engines == []
    assert result.warnings
