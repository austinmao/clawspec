from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

DEFAULT_WINDOW = 5


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "score"


def compute_rolling_average(scores: list[float], *, window: int = DEFAULT_WINDOW) -> float:
    if not scores:
        return 0.0
    relevant = scores[-window:]
    return sum(relevant) / len(relevant)


def compute_pass_at_k(passes: list[bool]) -> float:
    if not passes:
        return 0.0
    return 1.0 if any(passes) else 0.0


def compute_pass_caret_k(passes: list[bool]) -> float:
    if not passes:
        return 0.0
    return 1.0 if all(passes) else 0.0


class ScoreTracker:
    def __init__(self, *, base_dir: str | Path | None = None, window: int = DEFAULT_WINDOW) -> None:
        self.base_dir = (
            Path(base_dir)
            if base_dir is not None
            else _repo_root() / "memory" / "logs" / "qa" / "scores"
        )
        self.window = window

    def _score_file(self, workflow: str, scenario: str, metric: str) -> Path:
        filename = f"{_slug(workflow)}--{_slug(scenario)}--{_slug(metric)}.yaml"
        return self.base_dir / filename

    def _load_entries(self, workflow: str, scenario: str, metric: str) -> list[dict[str, Any]]:
        path = self._score_file(workflow, scenario, metric)
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or []
        return loaded if isinstance(loaded, list) else []

    def record_score(
        self,
        workflow: str,
        scenario: str,
        metric: str,
        *,
        score: float,
        passed: bool,
        timestamp: datetime | None = None,
    ) -> dict[str, Any]:
        entry = {
            "timestamp": (timestamp or datetime.now(UTC))
            .astimezone(UTC)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "score": float(score),
            "passed": bool(passed),
        }
        self.base_dir.mkdir(parents=True, exist_ok=True)
        entries = self._load_entries(workflow, scenario, metric)
        entries.append(entry)
        with self._score_file(workflow, scenario, metric).open("w", encoding="utf-8") as handle:
            yaml.safe_dump(entries, handle, sort_keys=False)
        return entry

    def get_metrics(
        self,
        workflow: str,
        scenario: str,
        metric: str,
        *,
        threshold: float,
    ) -> dict[str, Any]:
        entries = self._load_entries(workflow, scenario, metric)
        recent = entries[-self.window :]
        recent_scores = [float(entry["score"]) for entry in recent]
        recent_passes = [bool(entry["passed"]) for entry in recent]
        rolling_average = compute_rolling_average(recent_scores, window=self.window)
        return {
            "entries": recent,
            "rolling_average": rolling_average,
            "pass_at_k": compute_pass_at_k(recent_passes),
            "pass_caret_k": compute_pass_caret_k(recent_passes),
            "alert": bool(recent) and rolling_average < threshold,
        }
