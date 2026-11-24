"""已检视状态，用于避免重复评论。

结构：
{
  "version": 1,
  "repos": {
    "cann/npu-simulator": {
      "123": {"head_sha": "...", "reviewed_at": "...", "severity": "high", ...}
    }
  }
}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


class ReviewState:
    def __init__(self, path: Any) -> None:
        self.path = Path(path)
        self.data: Dict[str, Any] = {"version": 1, "repos": {}}
        self.load()

    def load(self) -> None:
        raw: Any = {}
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raw = {}
        if not isinstance(raw, dict):
            raw = {}
        repos = raw.get("repos")
        if not isinstance(repos, dict):
            repos = {}
        self.data = {"version": 1, "repos": repos}

    def _repo(self, repo: str) -> Dict[str, Any]:
        repos = self.data.setdefault("repos", {})
        mapping = repos.get(repo)
        if not isinstance(mapping, dict):
            mapping = {}
            repos[repo] = mapping
        return mapping

    def get(self, repo: str, number: int) -> Optional[Dict[str, Any]]:
        record = self._repo(repo).get(str(number))
        return record if isinstance(record, dict) else None

    def is_reviewed(self, repo: str, number: int, head_sha: str) -> bool:
        record = self.get(repo, number)
        return bool(record and head_sha and record.get("head_sha") == head_sha)

    def mark(self, repo: str, number: int, head_sha: str, **meta: Any) -> None:
        mapping = self._repo(repo)
        record = mapping.get(str(number))
        if not isinstance(record, dict):
            record = {}
        record["head_sha"] = head_sha
        record.update(meta)
        mapping[str(number)] = record

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self.path)
