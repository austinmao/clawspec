"""Performance baselines and regression detection for ClawSpec observability."""

from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

BASELINES_VERSION = "1.0"
MIN_RUNS = 5
RECOMMENDED_RUNS = 20


@dataclass
class MetricStats:
    """Percentile-based statistics for a single metric."""

    p50: float
    p95: float
    min: float
    max: float
    stddev: float


@dataclass
class ScenarioBaseline:
    """Baseline for a single scenario."""

    captured_at: str
    runs: int
    metrics: dict[str, MetricStats] = field(default_factory=dict)


@dataclass
class BaselineFile:
    """Top-level baselines.yaml structure."""

    version: str = BASELINES_VERSION
    baselines: dict[str, ScenarioBaseline] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Percentile computation
# ---------------------------------------------------------------------------


def compute_percentile(data: list[float], percentile: float) -> float:
    """Compute a percentile value from a sorted list."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    n = len(sorted_data)
    k = (n - 1) * (percentile / 100.0)
    floor_k = math.floor(k)
    ceil_k = min(math.ceil(k), n - 1)
    if floor_k == ceil_k:
        return sorted_data[floor_k]
    d = k - floor_k
    return sorted_data[floor_k] + d * (sorted_data[ceil_k] - sorted_data[floor_k])


def compute_stats(values: list[float]) -> MetricStats:
    """Compute percentile-based statistics from a list of values."""
    if not values:
        return MetricStats(p50=0.0, p95=0.0, min=0.0, max=0.0, stddev=0.0)
    return MetricStats(
        p50=compute_percentile(values, 50),
        p95=compute_percentile(values, 95),
        min=min(values),
        max=max(values),
        stddev=statistics.stdev(values) if len(values) > 1 else 0.0,
    )


# ---------------------------------------------------------------------------
# Baseline I/O
# ---------------------------------------------------------------------------


def load_baselines(path: Path) -> BaselineFile | None:
    """Load baselines from a YAML file."""
    if not path.exists():
        return None
    try:
        raw = yaml.safe_load(path.read_text())
        if not isinstance(raw, dict):
            return None
        version = str(raw.get("version", "1.0"))
        baselines: dict[str, ScenarioBaseline] = {}
        for name, data in raw.get("baselines", {}).items():
            metrics: dict[str, MetricStats] = {}
            for metric_name, stats in data.get("metrics", {}).items():
                metrics[metric_name] = MetricStats(
                    p50=float(stats.get("p50", 0)),
                    p95=float(stats.get("p95", 0)),
                    min=float(stats.get("min", 0)),
                    max=float(stats.get("max", 0)),
                    stddev=float(stats.get("stddev", 0)),
                )
            baselines[name] = ScenarioBaseline(
                captured_at=str(data.get("captured_at", "")),
                runs=int(data.get("runs", 0)),
                metrics=metrics,
            )
        return BaselineFile(version=version, baselines=baselines)
    except Exception as exc:
        logger.warning("Failed to load baselines from %s: %s", path, exc)
        return None


def save_baselines(path: Path, baseline_file: BaselineFile) -> None:
    """Save baselines to a YAML file."""
    data: dict[str, Any] = {
        "version": baseline_file.version,
        "baselines": {},
    }
    for name, scenario in baseline_file.baselines.items():
        metrics_data: dict[str, Any] = {}
        for metric_name, stats in scenario.metrics.items():
            metrics_data[metric_name] = {
                "p50": round(stats.p50, 6),
                "p95": round(stats.p95, 6),
                "min": round(stats.min, 6),
                "max": round(stats.max, 6),
                "stddev": round(stats.stddev, 6),
            }
        data["baselines"][name] = {
            "captured_at": scenario.captured_at,
            "runs": scenario.runs,
            "metrics": metrics_data,
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


# ---------------------------------------------------------------------------
# Baseline capture
# ---------------------------------------------------------------------------


_METRIC_KEYS = [
    "duration_ms",
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "llm_call_count",
    "tool_invocation_count",
    "subagent_delegation_count",
]


def capture_baseline(
    scenario_name: str,
    run_metrics: list[dict[str, float]],
    captured_at: str,
) -> tuple[ScenarioBaseline, list[str]]:
    """Capture a baseline from multiple run metrics.

    Args:
        scenario_name: Name of the scenario.
        run_metrics: List of dicts, each containing metric values from one run.
            Expected keys: duration_ms, total_tokens, input_tokens, output_tokens,
            cost_usd, llm_call_count, tool_invocation_count, subagent_delegation_count.
        captured_at: ISO timestamp.

    Returns:
        (ScenarioBaseline, list of warnings)
    """
    warnings: list[str] = []
    n = len(run_metrics)

    if n < MIN_RUNS:
        raise ValueError(
            f"Minimum {MIN_RUNS} runs required for baseline capture, got {n}"
        )

    if n < 10:
        warnings.append(
            f"Baseline captured with {n} runs; p95 estimate may be unreliable. "
            f"Use --runs {RECOMMENDED_RUNS}+ for stable percentiles."
        )

    metrics: dict[str, MetricStats] = {}
    for key in _METRIC_KEYS:
        values = [float(m.get(key, 0)) for m in run_metrics]
        metrics[key] = compute_stats(values)

    baseline = ScenarioBaseline(
        captured_at=captured_at,
        runs=n,
        metrics=metrics,
    )
    return baseline, warnings


# ---------------------------------------------------------------------------
# Baseline management
# ---------------------------------------------------------------------------


def reset_baseline(path: Path, scenario_name: str | None = None) -> bool:
    """Reset baselines. If scenario_name given, reset only that scenario."""
    baseline_file = load_baselines(path)
    if baseline_file is None:
        return False
    if scenario_name:
        if scenario_name in baseline_file.baselines:
            del baseline_file.baselines[scenario_name]
            save_baselines(path, baseline_file)
            return True
        return False
    # Reset all
    baseline_file.baselines.clear()
    save_baselines(path, baseline_file)
    return True


def show_baselines(path: Path) -> dict[str, Any] | None:
    """Return baselines as a plain dict for display."""
    baseline_file = load_baselines(path)
    if baseline_file is None:
        return None
    result: dict[str, Any] = {}
    for name, scenario in baseline_file.baselines.items():
        result[name] = {
            "captured_at": scenario.captured_at,
            "runs": scenario.runs,
            "metrics": {
                k: {
                    "p50": v.p50,
                    "p95": v.p95,
                    "min": v.min,
                    "max": v.max,
                    "stddev": v.stddev,
                }
                for k, v in scenario.metrics.items()
            },
        }
    return result


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------


@dataclass
class DriftCheck:
    """Result of a single drift check."""

    metric: str
    baseline_p50: float
    baseline_p95: float
    actual: float
    drift: float
    limit: float
    status: str  # "pass" or "fail"


_DRIFT_MAP = {
    "max_duration_drift": "duration_ms",
    "max_cost_drift": "cost_usd",
    "max_token_drift": "total_tokens",
    "max_step_drift": "llm_call_count",
}


def detect_drift(
    scenario_name: str,
    current_metrics: dict[str, float],
    baseline: ScenarioBaseline,
    regression_config: dict[str, Any],
) -> list[DriftCheck]:
    """Compare current metrics against baseline. Return list of drift checks."""
    compare = regression_config.get("compare", "p50")
    results: list[DriftCheck] = []

    for config_key, metric_key in _DRIFT_MAP.items():
        limit = regression_config.get(config_key)
        if limit is None:
            continue
        limit = float(limit)

        stats = baseline.metrics.get(metric_key)
        if stats is None:
            continue

        baseline_val = stats.p50 if compare == "p50" else stats.p95
        if baseline_val == 0:
            continue  # Can't compute drift from zero baseline

        actual = current_metrics.get(metric_key, 0)

        # max_step_drift is an absolute difference, not a ratio
        if config_key == "max_step_drift":
            drift_val = actual - baseline_val
            status = "pass" if drift_val <= limit else "fail"
        else:
            drift_val = actual / baseline_val
            status = "pass" if drift_val <= limit else "fail"

        results.append(
            DriftCheck(
                metric=metric_key,
                baseline_p50=stats.p50,
                baseline_p95=stats.p95,
                actual=actual,
                drift=round(drift_val, 2),
                limit=limit,
                status=status,
            )
        )

    return results


def format_regression_report(
    checks: list[DriftCheck],
    baseline_date: str,
    compare: str = "p50",
) -> dict[str, Any]:
    """Format drift checks into a report block."""
    any_failed = any(c.status == "fail" for c in checks)
    return {
        "baseline_date": baseline_date,
        "compare": compare,
        "status": "fail" if any_failed else "pass",
        "checks": [
            {
                "metric": c.metric,
                "baseline_p50": c.baseline_p50,
                "baseline_p95": c.baseline_p95,
                "actual": c.actual,
                "drift": c.drift,
                "limit": c.limit,
                "status": c.status,
            }
            for c in checks
        ],
    }
