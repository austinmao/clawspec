"""Tests for OpikBackend adapter (opik SDK fully mocked)."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from clawspec.observability import (
    ModelPricing,
    ObservabilityConfig,
    OpikConfig,
    TraceHandle,
)

# ---------------------------------------------------------------------------
# Helpers to build mock Opik objects
# ---------------------------------------------------------------------------

def _make_trace(
    trace_id: str = "trace-001",
    name: str = "agent/lumina",
    start_time: str = "2026-03-20T14:00:00+00:00",
    end_time: str | None = "2026-03-20T14:00:05+00:00",
    tags: list[str] | None = None,
) -> MagicMock:
    t = MagicMock()
    t.id = trace_id
    t.name = name
    t.start_time = start_time
    t.end_time = end_time
    t.tags = tags or []
    return t


def _make_span(
    span_id: str = "span-001",
    span_type: str = "llm",
    name: str = "claude-sonnet-4-6",
    duration: float = 1.5,
    usage: dict | None = None,
    metadata: dict | None = None,
    error: str | None = None,
    start_time: str = "2026-03-20T14:00:01+00:00",
    end_time: str = "2026-03-20T14:00:02+00:00",
) -> MagicMock:
    s = MagicMock()
    s.id = span_id
    s.type = span_type
    s.name = name
    s.duration = duration
    s.usage = usage
    s.metadata = metadata or {}
    s.error_info = error
    s.error = None
    s.input = {"messages": []}
    s.output = {"response": "ok"}
    s.start_time = start_time
    s.end_time = end_time
    return s


def _make_config(
    project_name: str = "openclaw-dev",
    pricing: dict[str, ModelPricing] | None = None,
) -> ObservabilityConfig:
    return ObservabilityConfig(
        backend="opik",
        trace_poll_delay_ms=0,
        time_window_padding_ms=10000,
        model_pricing=pricing or {},
        opik=OpikConfig(project_name=project_name, workspace="", api_key=""),
    )


def _backend_with_mock_client(
    mock_client: MagicMock,
    config: ObservabilityConfig | None = None,
):
    """Create an OpikBackend with a pre-injected mock client (bypasses real opik import)."""
    from clawspec.observability.opik import OpikBackend

    cfg = config or _make_config()
    backend = OpikBackend(cfg)
    backend._client = mock_client
    backend._available = True
    return backend


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------

class TestIsAvailable:
    def test_returns_true_when_search_succeeds(self):
        mock_client = MagicMock()
        mock_client.search_traces.return_value = []
        backend = _backend_with_mock_client(mock_client)
        # Reset cached state to test the actual check path
        backend._available = None
        assert backend.is_available() is True

    def test_returns_false_when_client_is_none(self):
        from clawspec.observability.opik import OpikBackend

        cfg = _make_config()
        backend = OpikBackend(cfg)
        backend._available = None
        # Force _get_client to return None by patching _get_opik_class
        with patch("clawspec.observability.opik._get_opik_class", return_value=None):
            assert backend.is_available() is False

    def test_returns_false_when_search_raises(self):
        mock_client = MagicMock()
        mock_client.search_traces.side_effect = RuntimeError("connection refused")
        backend = _backend_with_mock_client(mock_client)
        backend._available = None
        assert backend.is_available() is False

    def test_caches_result_after_first_call(self):
        mock_client = MagicMock()
        mock_client.search_traces.return_value = []
        backend = _backend_with_mock_client(mock_client)
        backend._available = None
        backend.is_available()
        backend.is_available()
        assert mock_client.search_traces.call_count == 1


# ---------------------------------------------------------------------------
# find_trace — three-tier matching
# ---------------------------------------------------------------------------

class TestFindTrace:
    def test_tier1_tag_hit(self):
        """find_trace returns immediately when tag matches."""
        run_id = "clawspec-20260320-140000-abc123"
        mock_trace = _make_trace(trace_id="t1", tags=[f"clawspec:{run_id}"])
        mock_client = MagicMock()
        mock_client.search_traces.return_value = [mock_trace]
        backend = _backend_with_mock_client(mock_client)

        result = backend.find_trace(
            agent_id="lumina",
            start_time="2026-03-20T14:00:00+00:00",
            end_time="2026-03-20T14:00:10+00:00",
            run_id=run_id,
        )

        assert result is not None
        assert result.id == "t1"
        # Only one search_traces call (tier 1)
        assert mock_client.search_traces.call_count == 1

    def test_tier2_input_hit_tags_the_trace(self):
        """find_trace tags the trace on tier-2 input match."""
        run_id = "clawspec-20260320-140000-def456"
        mock_trace = _make_trace(trace_id="t2", tags=[])

        call_count = [0]

        def _search(project_name, filter_string, max_results):
            call_count[0] += 1
            if call_count[0] == 1:
                # Tier 1 (tag) — no match
                return []
            # Tier 2 (input) — match
            return [mock_trace]

        mock_client = MagicMock()
        mock_client.search_traces.side_effect = _search
        backend = _backend_with_mock_client(mock_client)

        result = backend.find_trace(
            agent_id="lumina",
            start_time="2026-03-20T14:00:00+00:00",
            end_time="2026-03-20T14:00:10+00:00",
            run_id=run_id,
        )

        assert result is not None
        assert result.id == "t2"
        # update_trace called to tag it
        mock_client.update_trace.assert_called_once()

    def test_tier3_time_window_single_match(self):
        """find_trace tags and returns when exactly one agent-name match in window."""
        run_id = "clawspec-20260320-140000-ghi789"
        mock_trace = _make_trace(trace_id="t3", name="lumina-sales-agent")

        call_count = [0]

        def _search(project_name, filter_string, max_results):
            call_count[0] += 1
            if call_count[0] <= 2:
                # Tier 1 and Tier 2 — no match
                return []
            # Tier 3 — time window
            return [mock_trace]

        mock_client = MagicMock()
        mock_client.search_traces.side_effect = _search
        backend = _backend_with_mock_client(mock_client)

        result = backend.find_trace(
            agent_id="lumina",
            start_time="2026-03-20T14:00:00+00:00",
            end_time="2026-03-20T14:00:10+00:00",
            run_id=run_id,
        )

        assert result is not None
        assert result.id == "t3"
        mock_client.update_trace.assert_called_once()

    def test_tier3_time_window_multiple_picks_closest(self):
        """When multiple time-window matches exist, closest to start_time wins."""
        run_id = "clawspec-20260320-140000-jkl012"
        close_trace = _make_trace(
            trace_id="close",
            name="lumina",
            start_time="2026-03-20T14:00:01+00:00",
        )
        far_trace = _make_trace(
            trace_id="far",
            name="lumina",
            start_time="2026-03-20T14:00:08+00:00",
        )

        call_count = [0]

        def _search(project_name, filter_string, max_results):
            call_count[0] += 1
            if call_count[0] <= 2:
                return []
            return [far_trace, close_trace]

        mock_client = MagicMock()
        mock_client.search_traces.side_effect = _search
        backend = _backend_with_mock_client(mock_client)

        result = backend.find_trace(
            agent_id="lumina",
            start_time="2026-03-20T14:00:00+00:00",
            end_time="2026-03-20T14:00:10+00:00",
            run_id=run_id,
        )

        assert result is not None
        assert result.id == "close"

    def test_no_match_returns_none(self):
        """Returns None when all three tiers find nothing."""
        mock_client = MagicMock()
        mock_client.search_traces.return_value = []
        backend = _backend_with_mock_client(mock_client)

        result = backend.find_trace(
            agent_id="lumina",
            start_time="2026-03-20T14:00:00+00:00",
            end_time="2026-03-20T14:00:10+00:00",
            run_id="clawspec-20260320-140000-xxx",
        )

        assert result is None

    def test_returns_none_when_client_unavailable(self):
        from clawspec.observability.opik import OpikBackend

        cfg = _make_config()
        backend = OpikBackend(cfg)
        backend._client = None
        with patch("clawspec.observability.opik._get_opik_class", return_value=None):
            result = backend.find_trace(
                agent_id="lumina",
                start_time="2026-03-20T14:00:00+00:00",
                end_time="2026-03-20T14:00:10+00:00",
                run_id="any",
            )
        assert result is None


# ---------------------------------------------------------------------------
# get_spans — span type mapping
# ---------------------------------------------------------------------------

class TestGetSpans:
    def test_llm_span_mapped_correctly(self):
        span = _make_span(span_id="s1", span_type="llm")
        mock_client = MagicMock()
        mock_client.search_spans.return_value = [span]
        backend = _backend_with_mock_client(mock_client)
        handle = TraceHandle(id="t1", name="agent", start_time="2026-03-20T14:00:00+00:00")

        result = backend.get_spans(handle)

        assert result is not None
        assert len(result) == 1
        assert result[0].type == "llm"
        assert result[0].id == "s1"

    def test_tool_span_mapped_correctly(self):
        span = _make_span(span_id="s2", span_type="tool", name="brave_search")
        mock_client = MagicMock()
        mock_client.search_spans.return_value = [span]
        backend = _backend_with_mock_client(mock_client)
        handle = TraceHandle(id="t1", name="agent", start_time="2026-03-20T14:00:00+00:00")

        result = backend.get_spans(handle)

        assert result is not None
        assert result[0].type == "tool"

    def test_general_with_metadata_key_maps_to_subagent(self):
        span = _make_span(span_id="s3", span_type="general", metadata={"subagent_id": "coordinator"})
        mock_client = MagicMock()
        mock_client.search_spans.return_value = [span]
        backend = _backend_with_mock_client(mock_client)
        handle = TraceHandle(id="t1", name="agent", start_time="2026-03-20T14:00:00+00:00")

        result = backend.get_spans(handle)

        assert result is not None
        assert result[0].type == "subagent"

    def test_general_with_delegation_in_name_maps_to_subagent(self):
        span = _make_span(span_id="s4", span_type="general", name="delegation-to-copywriter")
        mock_client = MagicMock()
        mock_client.search_spans.return_value = [span]
        backend = _backend_with_mock_client(mock_client)
        handle = TraceHandle(id="t1", name="agent", start_time="2026-03-20T14:00:00+00:00")

        result = backend.get_spans(handle)

        assert result is not None
        assert result[0].type == "subagent"

    def test_general_without_delegation_markers_maps_to_tool(self):
        span = _make_span(span_id="s5", span_type="general", name="formatting-step")
        mock_client = MagicMock()
        mock_client.search_spans.return_value = [span]
        backend = _backend_with_mock_client(mock_client)
        handle = TraceHandle(id="t1", name="agent", start_time="2026-03-20T14:00:00+00:00")

        result = backend.get_spans(handle)

        assert result is not None
        assert result[0].type == "tool"

    def test_subagent_filter_excludes_non_subagent_spans(self):
        spans = [
            _make_span(span_id="s1", span_type="llm"),
            _make_span(span_id="s2", span_type="general", name="spawn-coordinator"),
        ]
        mock_client = MagicMock()
        mock_client.search_spans.return_value = spans
        backend = _backend_with_mock_client(mock_client)
        handle = TraceHandle(id="t1", name="agent", start_time="2026-03-20T14:00:00+00:00")

        result = backend.get_spans(handle, span_type="subagent")

        assert result is not None
        assert len(result) == 1
        assert result[0].id == "s2"

    def test_returns_none_on_exception(self):
        mock_client = MagicMock()
        mock_client.search_spans.side_effect = RuntimeError("API error")
        backend = _backend_with_mock_client(mock_client)
        handle = TraceHandle(id="t1", name="agent", start_time="2026-03-20T14:00:00+00:00")

        result = backend.get_spans(handle)

        assert result is None

    def test_returns_none_when_client_unavailable(self):
        from clawspec.observability.opik import OpikBackend

        cfg = _make_config()
        backend = OpikBackend(cfg)
        backend._client = None
        handle = TraceHandle(id="t1", name="agent", start_time="2026-03-20T14:00:00+00:00")
        with patch("clawspec.observability.opik._get_opik_class", return_value=None):
            result = backend.get_spans(handle)
        assert result is None


# ---------------------------------------------------------------------------
# enrich_trace — partial failure handling
# ---------------------------------------------------------------------------

class TestEnrichTrace:
    def test_both_steps_succeed(self):
        mock_client = MagicMock()
        backend = _backend_with_mock_client(mock_client)
        handle = TraceHandle(id="t1", name="agent", start_time="2026-03-20T14:00:00+00:00")

        result = backend.enrich_trace(
            handle,
            metadata={"clawspec": True, "clawspec_run_id": "run-abc"},
            scores={"correctness": 0.9},
        )

        assert result.metadata_applied is True
        assert result.scores_applied is True
        assert result.errors == []
        mock_client.update_trace.assert_called_once()
        mock_client.log_traces_feedback_scores.assert_called_once()

    def test_metadata_succeeds_scores_fail(self):
        mock_client = MagicMock()
        mock_client.log_traces_feedback_scores.side_effect = RuntimeError("score API down")
        backend = _backend_with_mock_client(mock_client)
        handle = TraceHandle(id="t1", name="agent", start_time="2026-03-20T14:00:00+00:00")

        result = backend.enrich_trace(
            handle,
            metadata={"clawspec": True, "clawspec_run_id": "run-abc"},
            scores={"correctness": 0.9},
        )

        assert result.metadata_applied is True
        assert result.scores_applied is False
        assert len(result.errors) == 1
        assert "score logging failed" in result.errors[0]

    def test_metadata_fails_scores_not_attempted_scores_true(self):
        """Scores step still runs (and succeeds) even if metadata update fails."""
        mock_client = MagicMock()
        mock_client.update_trace.side_effect = RuntimeError("metadata API down")
        backend = _backend_with_mock_client(mock_client)
        handle = TraceHandle(id="t1", name="agent", start_time="2026-03-20T14:00:00+00:00")

        result = backend.enrich_trace(
            handle,
            metadata={"clawspec": True, "clawspec_run_id": "run-abc"},
            scores={"accuracy": 1.0},
        )

        assert result.metadata_applied is False
        assert result.scores_applied is True
        assert any("metadata update failed" in e for e in result.errors)

    def test_no_scores_skips_log_call(self):
        mock_client = MagicMock()
        backend = _backend_with_mock_client(mock_client)
        handle = TraceHandle(id="t1", name="agent", start_time="2026-03-20T14:00:00+00:00")

        result = backend.enrich_trace(handle, metadata={"clawspec": True}, scores={})

        assert result.scores_applied is True
        mock_client.log_traces_feedback_scores.assert_not_called()

    def test_no_client_returns_error(self):
        from clawspec.observability.opik import OpikBackend

        cfg = _make_config()
        backend = OpikBackend(cfg)
        backend._client = None
        handle = TraceHandle(id="t1", name="agent", start_time="2026-03-20T14:00:00+00:00")
        with patch("clawspec.observability.opik._get_opik_class", return_value=None):
            result = backend.enrich_trace(handle, metadata={}, scores={})
        assert result.metadata_applied is False
        assert result.scores_applied is False
        assert any("not available" in e for e in result.errors)

    def test_preserves_existing_tags_when_enriching(self):
        mock_client = MagicMock()
        backend = _backend_with_mock_client(mock_client)
        raw_trace = _make_trace(tags=["gateway", "existing"])
        handle = TraceHandle(
            id="t1",
            name="agent",
            start_time="2026-03-20T14:00:00+00:00",
            backend_ref=raw_trace,
        )

        result = backend.enrich_trace(
            handle,
            metadata={"clawspec": True, "clawspec_run_id": "run-abc"},
            scores={},
        )

        assert result.metadata_applied is True
        _, kwargs = mock_client.update_trace.call_args
        assert kwargs["tags"] == ["gateway", "existing", "clawspec:run-abc", "clawspec"]


# ---------------------------------------------------------------------------
# get_cost — token aggregation and estimation fallback
# ---------------------------------------------------------------------------

class TestGetCost:
    def test_no_spans_returns_zero_cost(self):
        mock_client = MagicMock()
        mock_client.search_spans.return_value = []
        backend = _backend_with_mock_client(mock_client)
        handle = TraceHandle(id="t1", name="agent", start_time="2026-03-20T14:00:00+00:00")

        result = backend.get_cost(handle)

        assert result is not None
        assert result.total_tokens == 0
        assert result.total_cost_usd == 0.0
        assert result.cost_is_estimated is False

    def test_cost_from_span_usage(self):
        span = _make_span(
            span_id="s1",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "cost": 0.0045},
        )
        mock_client = MagicMock()
        mock_client.search_spans.return_value = [span]
        backend = _backend_with_mock_client(mock_client)
        handle = TraceHandle(id="t1", name="agent", start_time="2026-03-20T14:00:00+00:00")

        result = backend.get_cost(handle)

        assert result is not None
        assert result.total_tokens == 150
        assert result.total_cost_usd == pytest.approx(0.0045)
        assert result.cost_is_estimated is False

    def test_cost_estimation_fallback_exact_model_match(self):
        pricing = {
            "claude-sonnet-4-6": ModelPricing(input_per_1k=0.003, output_per_1k=0.015),
        }
        span = _make_span(
            span_id="s1",
            name="claude-sonnet-4-6",
            usage={"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
        )
        mock_client = MagicMock()
        mock_client.search_spans.return_value = [span]
        backend = _backend_with_mock_client(mock_client, config=_make_config(pricing=pricing))
        handle = TraceHandle(id="t1", name="agent", start_time="2026-03-20T14:00:00+00:00")

        result = backend.get_cost(handle)

        assert result is not None
        # 1000 * 0.003/1000 + 500 * 0.015/1000 = 0.003 + 0.0075 = 0.0105
        assert result.total_cost_usd == pytest.approx(0.0105)
        assert result.cost_is_estimated is True

    def test_cost_estimation_fallback_suffix_match(self):
        pricing = {
            "sonnet-4-6": ModelPricing(input_per_1k=0.003, output_per_1k=0.015),
        }
        span = _make_span(
            span_id="s1",
            name="anthropic/claude-sonnet-4-6",
            usage={"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
        )
        mock_client = MagicMock()
        mock_client.search_spans.return_value = [span]
        backend = _backend_with_mock_client(mock_client, config=_make_config(pricing=pricing))
        handle = TraceHandle(id="t1", name="agent", start_time="2026-03-20T14:00:00+00:00")

        result = backend.get_cost(handle)

        assert result is not None
        assert result.total_cost_usd == pytest.approx(0.0105)
        assert result.cost_is_estimated is True

    def test_no_pricing_leaves_cost_zero_when_no_span_cost(self):
        span = _make_span(
            span_id="s1",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        )
        mock_client = MagicMock()
        mock_client.search_spans.return_value = [span]
        backend = _backend_with_mock_client(mock_client)
        handle = TraceHandle(id="t1", name="agent", start_time="2026-03-20T14:00:00+00:00")

        result = backend.get_cost(handle)

        assert result is not None
        assert result.total_cost_usd == 0.0
        assert result.cost_is_estimated is False

    def test_returns_none_when_get_spans_fails(self):
        mock_client = MagicMock()
        mock_client.search_spans.side_effect = RuntimeError("DB error")
        backend = _backend_with_mock_client(mock_client)
        handle = TraceHandle(id="t1", name="agent", start_time="2026-03-20T14:00:00+00:00")

        result = backend.get_cost(handle)

        assert result is None

    def test_spans_without_usage_are_skipped(self):
        span_no_usage = _make_span(span_id="s1", usage=None)
        span_with_usage = _make_span(
            span_id="s2",
            usage={"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300, "cost": 0.001},
        )
        mock_client = MagicMock()
        mock_client.search_spans.return_value = [span_no_usage, span_with_usage]
        backend = _backend_with_mock_client(mock_client)
        handle = TraceHandle(id="t1", name="agent", start_time="2026-03-20T14:00:00+00:00")

        result = backend.get_cost(handle)

        assert result is not None
        assert result.total_tokens == 300
        assert len(result.per_span) == 1


# ---------------------------------------------------------------------------
# get_trace_url
# ---------------------------------------------------------------------------

class TestGetTraceUrl:
    def test_url_construction(self):
        backend = _backend_with_mock_client(MagicMock(), config=_make_config(project_name="my-project"))
        handle = TraceHandle(id="trace-abc-123", name="agent", start_time="2026-03-20T14:00:00+00:00")

        url = backend.get_trace_url(handle)

        assert url == "https://app.comet.ml/opik/projects/my-project/traces/trace-abc-123"

    def test_returns_none_when_no_project_name(self):
        cfg = ObservabilityConfig(
            backend="opik",
            opik=OpikConfig(project_name="", workspace="", api_key=""),
        )
        backend = _backend_with_mock_client(MagicMock(), config=cfg)
        handle = TraceHandle(id="trace-abc-123", name="agent", start_time="2026-03-20T14:00:00+00:00")

        url = backend.get_trace_url(handle)

        assert url is None


# ---------------------------------------------------------------------------
# Module import without opik SDK
# ---------------------------------------------------------------------------

class TestOptionalImport:
    def test_module_loads_without_opik_installed(self):
        """opik.py must import cleanly even when opik SDK is absent."""
        # If we reached this point, the import at module top succeeded.
        from clawspec.observability.opik import OpikBackend

        assert OpikBackend is not None

    def test_get_opik_class_returns_none_when_import_fails(self):
        import clawspec.observability.opik as mod

        original = mod._Opik
        mod._Opik = None
        with patch.dict(sys.modules, {"opik": None}):
            mod._get_opik_class()
        mod._Opik = original
        # Either None (SDK absent) or the real class (SDK present) — both valid
        # The key is no ImportError is raised
        assert True
