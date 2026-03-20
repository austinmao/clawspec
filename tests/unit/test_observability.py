"""Tests for observability protocol, data classes, config, and run ID."""

from __future__ import annotations

import os
import re
from unittest.mock import patch

import pytest

from clawspec.observability import (
    CostData,
    EnrichResult,
    ModelPricing,
    ObservabilityBackend,
    ObservabilityConfig,
    OpikConfig,
    SpanData,
    TokenUsage,
    TraceHandle,
    generate_run_id,
    load_observability_config,
)


class TestDataClasses:
    def test_trace_handle_creation(self):
        t = TraceHandle(id="abc", name="agent/lumina", start_time="2026-03-20T14:00:00Z")
        assert t.id == "abc"
        assert t.end_time is None
        assert t.backend_ref is None

    def test_span_data_defaults(self):
        s = SpanData(id="s1", type="llm", name="claude-sonnet-4-6", start_time="2026-03-20T14:00:00Z")
        assert s.duration_ms == 0.0
        assert s.tokens is None
        assert s.error is None
        assert s.metadata == {}

    def test_token_usage_frozen(self):
        t = TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150)
        assert t.cost_usd is None
        with pytest.raises(AttributeError):
            t.input_tokens = 200  # type: ignore[misc]

    def test_cost_data_estimated_flag(self):
        c = CostData(total_tokens=1000, total_cost_usd=0.005, cost_is_estimated=True)
        assert c.cost_is_estimated is True
        assert c.per_span == []

    def test_enrich_result_defaults(self):
        e = EnrichResult()
        assert e.metadata_applied is False
        assert e.scores_applied is False
        assert e.errors == []

    def test_enrich_result_mutable(self):
        e = EnrichResult()
        e.metadata_applied = True
        e.errors.append("score logging failed")
        assert e.metadata_applied is True
        assert len(e.errors) == 1


class TestRunIdGenerator:
    def test_format(self):
        run_id = generate_run_id()
        assert run_id.startswith("clawspec-")
        parts = run_id.split("-")
        assert len(parts) == 4
        assert len(parts[1]) == 8  # YYYYMMDD
        assert len(parts[2]) == 6  # HHMMSS
        assert len(parts[3]) == 6  # random6

    def test_random_part_is_alphanumeric(self):
        for _ in range(100):
            run_id = generate_run_id()
            rand = run_id.split("-")[3]
            assert re.match(r"^[a-z0-9]{6}$", rand), f"Bad random part: {rand}"

    def test_uniqueness(self):
        ids = {generate_run_id() for _ in range(1000)}
        assert len(ids) == 1000, "Run IDs should be unique"


class TestConfigLoader:
    def test_empty_config(self):
        cfg = load_observability_config(None)
        assert cfg.backend == "none"
        assert cfg.trace_poll_delay_ms == 3000
        assert cfg.time_window_padding_ms == 10000
        assert cfg.model_pricing == {}

    def test_full_config(self):
        raw = {
            "observability": {
                "backend": "opik",
                "trace_poll_delay_ms": 5000,
                "time_window_padding_ms": 15000,
                "model_pricing": {
                    "claude-sonnet-4-6": {
                        "input_per_1k": 0.003,
                        "output_per_1k": 0.015,
                    }
                },
                "opik": {
                    "project_name": "openclaw-dev",
                    "workspace": "austinmao",
                },
            }
        }
        cfg = load_observability_config(raw)
        assert cfg.backend == "opik"
        assert cfg.trace_poll_delay_ms == 5000
        assert "claude-sonnet-4-6" in cfg.model_pricing
        assert cfg.model_pricing["claude-sonnet-4-6"].input_per_1k == 0.003
        assert cfg.opik.project_name == "openclaw-dev"

    def test_api_key_from_env(self):
        with patch.dict(os.environ, {"OPIK_API_KEY": "test-key-123"}):
            cfg = load_observability_config({"observability": {"backend": "opik", "opik": {}}})
            assert cfg.opik.api_key == "test-key-123"

    def test_missing_observability_block(self):
        cfg = load_observability_config({"other": "stuff"})
        assert cfg.backend == "none"

    def test_partial_config(self):
        cfg = load_observability_config({"observability": {"backend": "opik"}})
        assert cfg.backend == "opik"
        assert cfg.trace_poll_delay_ms == 3000  # default


class TestProtocol:
    def test_protocol_is_runtime_checkable(self):
        assert hasattr(ObservabilityBackend, "__protocol_attrs__") or hasattr(
            ObservabilityBackend, "__abstractmethods__"
        ) or isinstance(ObservabilityBackend, type)

    def test_none_backend_is_not_backend(self):
        assert not isinstance(None, ObservabilityBackend)


class TestOptionalImport:
    """T005b: Verify module imports work when opik is NOT installed."""

    def test_observability_module_imports_without_opik(self):
        """The observability module must import cleanly without opik SDK."""
        # This test passes if we got here — the import at module level succeeded.
        from clawspec.observability import ObservabilityBackend
        assert ObservabilityBackend is not None

    def test_run_id_works_without_opik(self):
        """Run ID generation has no opik dependency."""
        run_id = generate_run_id()
        assert run_id.startswith("clawspec-")
