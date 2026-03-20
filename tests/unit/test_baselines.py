"""Tests for baselines and drift detection."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from clawspec.baselines import (
    BaselineFile,
    DriftCheck,
    MetricStats,
    ScenarioBaseline,
    capture_baseline,
    compute_percentile,
    compute_stats,
    detect_drift,
    format_regression_report,
    load_baselines,
    reset_baseline,
    save_baselines,
    show_baselines,
)


class TestComputeStats:
    def test_basic_list(self):
        stats = compute_stats([1.0, 2.0, 3.0, 4.0, 5.0])
        assert stats.p50 == 3.0
        assert stats.min == 1.0
        assert stats.max == 5.0
        assert stats.stddev > 0

    def test_single_value(self):
        stats = compute_stats([42.0])
        assert stats.p50 == 42.0
        assert stats.p95 == 42.0
        assert stats.stddev == 0.0

    def test_empty_list(self):
        stats = compute_stats([])
        assert stats.p50 == 0.0
        assert stats.stddev == 0.0


class TestComputePercentile:
    def test_p50(self):
        assert compute_percentile([1, 2, 3, 4, 5], 50) == 3.0

    def test_p95(self):
        result = compute_percentile(list(range(1, 101)), 95)
        assert 95 <= result <= 96

    def test_single_element(self):
        assert compute_percentile([7.0], 50) == 7.0
        assert compute_percentile([7.0], 95) == 7.0

    def test_empty_list_returns_zero(self):
        assert compute_percentile([], 50) == 0.0
        assert compute_percentile([], 95) == 0.0


class TestCaptureBaseline:
    def _make_runs(self, n: int) -> list[dict[str, float]]:
        return [
            {
                "duration_ms": 3000 + i * 100,
                "total_tokens": 4000 + i * 50,
                "input_tokens": 2500 + i * 30,
                "output_tokens": 1500 + i * 20,
                "cost_usd": 0.003 + i * 0.0001,
                "llm_call_count": 2.0,
                "tool_invocation_count": 3.0,
                "subagent_delegation_count": 0.0,
            }
            for i in range(n)
        ]

    def test_capture_with_5_runs(self):
        baseline, warnings = capture_baseline(
            "smoke", self._make_runs(5), "2026-03-20T14:00:00Z"
        )
        assert baseline.runs == 5
        assert "duration_ms" in baseline.metrics
        assert baseline.metrics["duration_ms"].p50 > 0
        assert len(warnings) == 1  # <10 runs warning

    def test_capture_with_20_runs(self):
        baseline, warnings = capture_baseline(
            "smoke", self._make_runs(20), "2026-03-20T14:00:00Z"
        )
        assert baseline.runs == 20
        assert len(warnings) == 0

    def test_below_minimum_raises(self):
        with pytest.raises(ValueError, match="Minimum 5"):
            capture_baseline("smoke", self._make_runs(3), "2026-03-20T14:00:00Z")


class TestBaselineIO:
    def test_round_trip(self):
        baseline = ScenarioBaseline(
            captured_at="2026-03-20T14:00:00Z",
            runs=10,
            metrics={
                "duration_ms": MetricStats(
                    p50=3200, p95=4100, min=2800, max=4500, stddev=620
                ),
                "cost_usd": MetricStats(
                    p50=0.0037, p95=0.0042, min=0.0034, max=0.0045, stddev=0.0004
                ),
            },
        )
        bf = BaselineFile(baselines={"smoke-basic": baseline})

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = Path(f.name)

        save_baselines(path, bf)
        loaded = load_baselines(path)
        assert loaded is not None
        assert "smoke-basic" in loaded.baselines
        assert loaded.baselines["smoke-basic"].runs == 10
        assert loaded.baselines["smoke-basic"].metrics["duration_ms"].p50 == 3200
        path.unlink()

    def test_load_missing_file(self):
        assert load_baselines(Path("/nonexistent/baselines.yaml")) is None

    def test_load_non_dict_yaml(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write("- just\n- a\n- list\n")
            path = Path(f.name)
        assert load_baselines(path) is None
        path.unlink()

    def test_load_corrupt_yaml(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write("version: 1.0\nbaselines:\n  smoke:\n    runs: not_an_int_but_valid\n")
            path = Path(f.name)
        # Should either load (tolerating) or return None — must not raise
        result = load_baselines(path)
        path.unlink()
        # result may be None or a valid baseline — the key is no exception raised
        assert result is None or isinstance(result, BaselineFile)


class TestResetBaseline:
    def test_reset_specific(self):
        bf = BaselineFile(
            baselines={
                "a": ScenarioBaseline(captured_at="x", runs=5),
                "b": ScenarioBaseline(captured_at="y", runs=5),
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = Path(f.name)
        save_baselines(path, bf)
        assert reset_baseline(path, "a") is True
        loaded = load_baselines(path)
        assert loaded is not None
        assert "a" not in loaded.baselines
        assert "b" in loaded.baselines
        path.unlink()

    def test_reset_all(self):
        bf = BaselineFile(
            baselines={
                "a": ScenarioBaseline(captured_at="x", runs=5),
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = Path(f.name)
        save_baselines(path, bf)
        assert reset_baseline(path) is True
        loaded = load_baselines(path)
        assert loaded is not None
        assert len(loaded.baselines) == 0
        path.unlink()

    def test_reset_missing_file_returns_false(self):
        assert reset_baseline(Path("/nonexistent/baselines.yaml")) is False

    def test_reset_nonexistent_scenario_returns_false(self):
        bf = BaselineFile(baselines={"a": ScenarioBaseline(captured_at="x", runs=5)})
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = Path(f.name)
        save_baselines(path, bf)
        assert reset_baseline(path, "z") is False
        path.unlink()


class TestDriftDetection:
    def _make_baseline(self) -> ScenarioBaseline:
        return ScenarioBaseline(
            captured_at="2026-03-20T14:00:00Z",
            runs=20,
            metrics={
                "duration_ms": MetricStats(
                    p50=3200, p95=4100, min=2800, max=4500, stddev=620
                ),
                "cost_usd": MetricStats(
                    p50=0.0037, p95=0.0042, min=0.0034, max=0.0045, stddev=0.0004
                ),
                "total_tokens": MetricStats(
                    p50=4850, p95=5200, min=4600, max=5400, stddev=280
                ),
                "llm_call_count": MetricStats(
                    p50=2, p95=2, min=2, max=3, stddev=0.4
                ),
            },
        )

    def test_within_threshold(self):
        checks = detect_drift(
            "smoke",
            {"duration_ms": 4000, "cost_usd": 0.004},
            self._make_baseline(),
            {"max_duration_drift": 2.0, "max_cost_drift": 1.5},
        )
        assert all(c.status == "pass" for c in checks)

    def test_over_threshold(self):
        checks = detect_drift(
            "smoke",
            {"duration_ms": 7000, "cost_usd": 0.004},
            self._make_baseline(),
            {"max_duration_drift": 2.0, "max_cost_drift": 1.5},
        )
        duration_check = next(c for c in checks if c.metric == "duration_ms")
        assert duration_check.status == "fail"
        assert duration_check.drift > 2.0

    def test_step_drift_absolute(self):
        checks = detect_drift(
            "smoke",
            {"llm_call_count": 4},
            self._make_baseline(),
            {"max_step_drift": 1},
        )
        step_check = next(c for c in checks if c.metric == "llm_call_count")
        assert step_check.status == "fail"  # 4 - 2 = 2 > 1

    def test_compare_p95(self):
        checks = detect_drift(
            "smoke",
            {"duration_ms": 7000},
            self._make_baseline(),
            {"compare": "p95", "max_duration_drift": 2.0},
        )
        check = checks[0]
        # 7000 / 4100 ≈ 1.7 < 2.0 → pass
        assert check.status == "pass"

    def test_missing_metric_in_baseline_is_skipped(self):
        baseline = ScenarioBaseline(
            captured_at="2026-03-20T14:00:00Z",
            runs=10,
            metrics={},  # No metrics at all
        )
        checks = detect_drift(
            "smoke",
            {"duration_ms": 5000},
            baseline,
            {"max_duration_drift": 2.0},
        )
        assert checks == []

    def test_zero_baseline_is_skipped(self):
        baseline = ScenarioBaseline(
            captured_at="2026-03-20T14:00:00Z",
            runs=10,
            metrics={
                "duration_ms": MetricStats(p50=0.0, p95=0.0, min=0.0, max=0.0, stddev=0.0),
            },
        )
        checks = detect_drift(
            "smoke",
            {"duration_ms": 5000},
            baseline,
            {"max_duration_drift": 2.0},
        )
        assert checks == []


class TestShowBaselines:
    def test_show_returns_plain_dict(self):
        bf = BaselineFile(
            baselines={
                "smoke": ScenarioBaseline(
                    captured_at="2026-03-20T14:00:00Z",
                    runs=10,
                    metrics={
                        "duration_ms": MetricStats(
                            p50=3200, p95=4100, min=2800, max=4500, stddev=620
                        ),
                    },
                )
            }
        )
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = Path(f.name)
        save_baselines(path, bf)
        result = show_baselines(path)
        assert result is not None
        assert "smoke" in result
        assert result["smoke"]["runs"] == 10
        assert result["smoke"]["metrics"]["duration_ms"]["p50"] == 3200
        path.unlink()

    def test_show_missing_file(self):
        assert show_baselines(Path("/nonexistent/baselines.yaml")) is None


class TestFormatReport:
    def test_mixed_results(self):
        checks = [
            DriftCheck("duration_ms", 3200, 4100, 6400, 2.0, 2.0, "fail"),
            DriftCheck("cost_usd", 0.0037, 0.0042, 0.0041, 1.1, 1.5, "pass"),
        ]
        report = format_regression_report(checks, "2026-03-20T14:00:00Z")
        assert report["status"] == "fail"
        assert len(report["checks"]) == 2
        assert report["checks"][0]["status"] == "fail"
        assert report["checks"][1]["status"] == "pass"
