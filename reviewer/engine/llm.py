"""可选的 LLM 检视，兼容 OpenAI 风格的 /chat/completions 接口。

设计原则：任何异常都只降级、不抛出，确保定时任务不会因为 AI 服务不可用而失败。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from ..config import Config, LLMConfig
from ..diffparser import DiffData, render_for_llm
from .base import Finding, ReviewResult, SEVERITY_ORDER, highest_severity

SYSTEM_PROMPT = (
    "你是一名资深代码评审专家，负责评审 GitCode 仓库 cann/npu-simulator 的 Pull Request。"
    "请只基于给定的 diff 找出真实、可操作、与改动直接相关的问题，避免臆测、"
    "避免纯风格挑剔、避免重复罗列同一问题。"
    "只输出一个 JSON 对象，不要输出 Markdown 代码块或任何额外文字。JSON 结构："
    '{"summary":"面向作者的简要总结（中文）",'
    '"risk_level":"high|medium|low",'
    '"findings":[{"severity":"high|medium|low|info",'
    '"file":"相对路径","line":123,'
    '"issue":"问题描述（中文）",'
    '"suggestion":"修改建议（中文）"}]}'
    "。severity 使用规则：会导致错误/安全/数据损坏=high；明显缺陷或风险=medium；"
    "可维护性建议=low；提示=info。若没有实质问题，findings 返回空数组，summary 说明通过。"
)

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if limit > 0 and len(text) > limit:
        return text[:limit] + "…"
    return text


def _build_user_prompt(pr: dict, diff_text: str, diff: DiffData) -> str:
    number = pr.get("number", "?")
    title = str(pr.get("title") or "")
    body = _truncate(str(pr.get("body") or pr.get("description") or ""), 2000)
    head = (pr.get("head") or {}).get("ref") if isinstance(pr.get("head"), dict) else ""
    base = (pr.get("base") or {}).get("ref") if isinstance(pr.get("base"), dict) else ""
    stats = f"+{diff.added_lines} / -{diff.removed_lines}，{len(diff.files)} 个文件"
    parts = [
        f"PR #{number}《{title}》",
        f"分支：{head} -> {base}",
        f"变更规模：{stats}",
    ]
    if body:
        parts.append(f"PR 描述：\n{body}")
    parts.append("请评审以下 diff（左侧为行号，+ 为新增，- 为删除）：")
    parts.append(diff_text or "(diff 为空)")
    return "\n\n".join(parts)


def _chat(cfg: LLMConfig, user_prompt: str) -> str:
    url = cfg.base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "stream": False,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {cfg.api_key}",
        },
    )
    with urllib.request.urlopen(request, timeout=cfg.timeout) as response:
        raw = response.read().decode("utf-8", "replace")

    obj = json.loads(raw)
    choices = obj.get("choices") if isinstance(obj, dict) else None
    if not choices:
        raise RuntimeError("LLM 响应缺少 choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):  # 少数兼容实现返回内容分段
        content = "".join(
            str(part.get("text", "")) for part in content if isinstance(part, dict)
        )
    if not content:
        raise RuntimeError("LLM 响应缺少内容")
    return str(content)


def _parse_json_object(content: str) -> Dict[str, Any]:
    text = content.strip()
    block = _JSON_BLOCK_RE.search(text)
    if block:
        text = block.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("未找到 JSON 对象")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("JSON 顶层不是对象")
    return data


def _normalize_severity(value: Any) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "critical": "high",
        "error": "high",
        "warning": "medium",
        "warn": "medium",
        "minor": "low",
        "suggestion": "low",
        "note": "info",
    }
    text = aliases.get(text, text)
    return text if text in SEVERITY_ORDER else "info"


def _safe_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return " ".join(text.split())[:300]


def review(diff: DiffData, pr: dict, config: Config) -> ReviewResult:
    """调用 LLM 检视；失败时返回带 warnings 的空结果，不抛出。"""
    cfg = config.llm
    if not cfg.enabled:
        return ReviewResult(engines=[], warnings=["未配置 LLM_API_KEY，本次仅使用规则检视。"])

    diff_text = render_for_llm(diff, cfg.max_diff_chars)
    if not diff_text:
        return ReviewResult(engines=[], warnings=["PR 没有可供 LLM 阅读的 diff。"])

    prompt = _build_user_prompt(pr, diff_text, diff)
    try:
        content = _chat(cfg, prompt)
    except urllib.error.HTTPError as exc:
        return ReviewResult(
            engines=[],
            warnings=[f"LLM 接口返回 HTTP {exc.code}，已降级为仅规则检视。"],
        )
    except Exception as exc:  # noqa: BLE001 - 必须降级而不是中断
        return ReviewResult(
            engines=[],
            warnings=[f"LLM 检视失败，已降级为仅规则检视：{_safe_error(exc)}"],
        )

    try:
        data = _parse_json_object(content)
    except Exception as exc:  # noqa: BLE001
        return ReviewResult(
            engines=[],
            warnings=[f"LLM 返回内容无法解析为 JSON，已丢弃 AI 结果：{_safe_error(exc)}"],
        )

    findings: List[Finding] = []
    raw_findings = data.get("findings")
    if isinstance(raw_findings, list):
        for item in raw_findings[:40]:
            if not isinstance(item, dict):
                continue
            file = str(item.get("file") or "").strip()
            issue = str(item.get("issue") or item.get("message") or "").strip()
            if not issue:
                continue
            line_value = item.get("line")
            try:
                line: Optional[int] = int(line_value) if line_value not in (None, "") else None
            except (TypeError, ValueError):
                line = None
            findings.append(
                Finding(
                    rule="llm-review",
                    severity=_normalize_severity(item.get("severity")),
                    file=file,
                    line=line,
                    message=issue,
                    suggestion=str(item.get("suggestion") or "").strip(),
                    engine="llm",
                )
            )

    summary = str(data.get("summary") or "").strip()
    declared = str(data.get("risk_level") or "").strip().lower()
    computed = highest_severity(findings)
    if declared in {"high", "medium", "low"}:
        risk = declared
        if computed and SEVERITY_ORDER.get(computed, 9) < SEVERITY_ORDER.get(risk, 9):
            risk = computed
    else:
        risk = computed

    return ReviewResult(
        findings=findings,
        summary=summary,
        risk_level=risk,
        engines=["llm"],
    )
