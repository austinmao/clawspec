"""Tests for trace-aware assertion evaluators and dispatcher."""

from __future__ import annotations

from dataclasses import dataclass, field
import tempfile
from pathlib import Path
from typing import Any

import pytest

from clawspec.assertions.trace import (
    TRACE_ASSERTION_TYPES,
    _eval_delegation_path,
    _eval_llm_call_count,
    _eval_model_used,
    _eval_no_span_errors,
    _eval_per_span_budget,
    _eval_tool_not_invoked,
    _eval_tool_sequence,
    _eval_trace_cost,
    _eval_trace_duration,
    _eval_trace_token_budget,
    evaluate_trace_assertion,
)

# ---------------------------------------------------------------------------
# Minimal SpanData stand-in — mirrors clawspec.observability.SpanData
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _TokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float | None = None


@dataclass
class _Span:
    """Lightweight span stub for tests; no import dependency on observability."""

    id: str
    type: str  # "llm", "tool", "subagent"
    name: str
    duration_ms: float = 0.0
    start_time: str | None = None
    end_time: str | None = None
    tokens: _TokenUsage | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _llm(
    name: str,
    *,
    tokens: _TokenUsage | None = None,
    error: str | None = None,
    duration_ms: float = 0.0,
    start_time: str | None = None,
    end_time: str | None = None,
) -> _Span:
    return _Span(
        id=name,
        type="llm",
        name=name,
        tokens=tokens,
        error=error,
        duration_ms=duration_ms,
        start_time=start_time,
        end_time=end_time,
    )


def _tool(
    name: str,
    *,
    error: str | None = None,
    duration_ms: float = 0.0,
    start_time: str | None = None,
    end_time: str | None = None,
) -> _Span:
    return _Span(
        id=name,
        type="tool",
        name=name,
        error=error,
        duration_ms=duration_ms,
        start_time=start_time,
        end_time=end_time,
    )


def _subagent(
    name: str,
    *,
    start_time: str | None = None,
    end_time: str | None = None,
    duration_ms: float = 0.0,
) -> _Span:
    return _Span(
        id=name,
        type="subagent",
        name=name,
        start_time=start_time,
        end_time=end_time,
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# Dispatcher tests
# ---------------------------------------------------------------------------


class TestDispatcher:
    def test_none_spans_returns_skip_for_any_type(self):
        result = evaluate_trace_assertion("llm_call_count", {"min": 1}, None)
        assert result["status"] == "skip"
        assert "spans query failed" in result["detail"]

    def test_none_spans_preserves_type_field(self):
        result = evaluate_trace_assertion("trace_duration", {"max_ms": 1000}, None)
        assert result["type"] == "trace_duration"
        assert result["status"] == "skip"

    def test_unknown_type_returns_skip(self):
        result = evaluate_trace_assertion("completely_unknown", {}, [])
        assert result["status"] == "skip"
        assert "unknown trace assertion type" in result["detail"]

    def test_unknown_type_preserves_type_field(self):
        result = evaluate_trace_assertion("ghost_assertion", {}, [])
        assert result["type"] == "ghost_assertion"

    def test_dispatches_to_llm_call_count(self):
        spans = [_llm("claude-sonnet"), _llm("claude-haiku")]
        result = evaluate_trace_assertion("llm_call_count", {"max": 5}, spans)
        assert result["status"] == "pass"

    def test_dispatches_to_no_span_errors(self):
        result = evaluate_trace_assertion("no_span_errors", {}, [])
        assert result["status"] == "pass"

    def test_trace_assertion_types_constant_has_ten_entries(self):
        assert len(TRACE_ASSERTION_TYPES) == 10

    def test_all_trace_types_are_dispatchable(self):
        """Every entry in TRACE_ASSERTION_TYPES must route to a real evaluator."""
        for assertion_type in TRACE_ASSERTION_TYPES:
            result = evaluate_trace_assertion(assertion_type, {}, [])
            assert result["status"] in {"pass", "fail", "skip", "warn"}, (
                f"{assertion_type} returned unexpected status: {result['status']}"
            )


# ---------------------------------------------------------------------------
# llm_call_count
# ---------------------------------------------------------------------------


class TestLlmCallCount:
    def _spans(self, n_llm: int, n_tool: int = 0) -> list[_Span]:
        spans: list[_Span] = [_llm(f"llm-{i}") for i in range(n_llm)]
        spans += [_tool(f"tool-{i}") for i in range(n_tool)]
        return spans

    def test_within_bounds_pass(self):
        result = _eval_llm_call_count({"min": 1, "max": 5}, self._spans(3))
        assert result["status"] == "pass"
        assert result["actual"] == 3

    def test_exact_min_boundary_pass(self):
        result = _eval_llm_call_count({"min": 2}, self._spans(2))
        assert result["status"] == "pass"

    def test_exact_max_boundary_pass(self):
        result = _eval_llm_call_count({"max": 3}, self._spans(3))
        assert result["status"] == "pass"

    def test_below_min_fail(self):
        result = _eval_llm_call_count({"min": 3}, self._spans(1))
        assert result["status"] == "fail"
        assert result["actual"] == 1
        assert result["expected_min"] == 3

    def test_above_max_fail(self):
        result = _eval_llm_call_count({"max": 2}, self._spans(5))
        assert result["status"] == "fail"
        assert result["actual"] == 5
        assert result["expected_max"] == 2

    def test_only_min_specified(self):
        result = _eval_llm_call_count({"min": 1}, self._spans(10))
        assert result["status"] == "pass"

    def test_only_max_specified(self):
        result = _eval_llm_call_count({"max": 10}, self._spans(0))
        assert result["status"] == "pass"

    def test_tool_spans_not_counted(self):
        result = _eval_llm_call_count({"max": 1}, self._spans(1, n_tool=10))
        assert result["status"] == "pass"
        assert result["actual"] == 1

    def test_empty_spans_zero_count(self):
        result = _eval_llm_call_count({"min": 0}, [])
        assert result["status"] == "pass"
        assert result["actual"] == 0

    def test_no_bounds_pass(self):
        result = _eval_llm_call_count({}, self._spans(5))
        assert result["status"] == "pass"

    def test_detail_contains_count(self):
        result = _eval_llm_call_count({"min": 1, "max": 5}, self._spans(3))
        assert "3" in result["detail"]


# ---------------------------------------------------------------------------
# tool_sequence
# ---------------------------------------------------------------------------


class TestToolSequence:
    def _tool_spans(self, names: list[str]) -> list[_Span]:
        return [_tool(n) for n in names]

    # --- ordered mode (default) ---

    def test_ordered_pass_exact(self):
        result = _eval_tool_sequence(
            {"expected": ["search", "write"]},
            self._tool_spans(["search", "write"]),
        )
        assert result["status"] == "pass"

    def test_ordered_pass_subsequence(self):
        result = _eval_tool_sequence(
            {"expected": ["search", "write"]},
            self._tool_spans(["read", "search", "validate", "write"]),
        )
        assert result["status"] == "pass"

    def test_ordered_fail_wrong_order(self):
        result = _eval_tool_sequence(
            {"expected": ["search", "write"]},
            self._tool_spans(["write", "search"]),
        )
        assert result["status"] == "fail"
        assert "0" in result["detail"] or "subsequence" in result["detail"]

    def test_ordered_fail_missing_tool(self):
        result = _eval_tool_sequence(
            {"expected": ["search", "missing_tool"]},
            self._tool_spans(["search", "write"]),
        )
        assert result["status"] == "fail"

    def test_ordered_empty_expected_pass(self):
        result = _eval_tool_sequence(
            {"expected": []},
            self._tool_spans(["search", "write"]),
        )
        assert result["status"] == "pass"

    # --- strict mode ---

    def test_strict_pass_exact(self):
        result = _eval_tool_sequence(
            {"expected": ["a", "b", "c"], "mode": "strict"},
            self._tool_spans(["a", "b", "c"]),
        )
        assert result["status"] == "pass"

    def test_strict_fail_extra_tool(self):
        result = _eval_tool_sequence(
            {"expected": ["a", "b"], "mode": "strict"},
            self._tool_spans(["a", "b", "c"]),
        )
        assert result["status"] == "fail"
        assert "strict mismatch" in result["detail"]

    def test_strict_fail_missing_tool(self):
        result = _eval_tool_sequence(
            {"expected": ["a", "b", "c"], "mode": "strict"},
            self._tool_spans(["a", "b"]),
        )
        assert result["status"] == "fail"

    def test_strict_fail_wrong_order(self):
        result = _eval_tool_sequence(
            {"expected": ["a", "b"], "mode": "strict"},
            self._tool_spans(["b", "a"]),
        )
        assert result["status"] == "fail"

    # --- contains mode ---

    def test_contains_pass_all_present(self):
        result = _eval_tool_sequence(
            {"expected": ["b", "d"], "mode": "contains"},
            self._tool_spans(["a", "b", "c", "d"]),
        )
        assert result["status"] == "pass"

    def test_contains_fail_some_missing(self):
        result = _eval_tool_sequence(
            {"expected": ["b", "missing"], "mode": "contains"},
            self._tool_spans(["a", "b", "c"]),
        )
        assert result["status"] == "fail"
        assert "missing" in result
        assert "missing" in result["missing"]

    def test_contains_order_irrelevant(self):
        result = _eval_tool_sequence(
            {"expected": ["c", "a"], "mode": "contains"},
            self._tool_spans(["a", "b", "c"]),
        )
        assert result["status"] == "pass"

    # --- actual field always present ---

    def test_actual_field_in_result(self):
        result = _eval_tool_sequence(
            {"expected": ["x"]},
            self._tool_spans(["a", "b"]),
        )
        assert "actual" in result


# ---------------------------------------------------------------------------
# model_used
# ---------------------------------------------------------------------------


class TestModelUsed:
    def _llm_spans(self, models: list[str]) -> list[_Span]:
        return [_llm(m) for m in models]

    def test_expected_found_pass(self):
        result = _eval_model_used(
            {"expected": "sonnet"},
            self._llm_spans(["claude-sonnet-4-6"]),
        )
        assert result["status"] == "pass"

    def test_expected_not_found_fail(self):
        result = _eval_model_used(
            {"expected": "opus"},
            self._llm_spans(["claude-sonnet-4-6"]),
        )
        assert result["status"] == "fail"
        assert "expected" in result

    def test_not_expected_not_found_pass(self):
        result = _eval_model_used(
            {"not_expected": "gpt-4"},
            self._llm_spans(["claude-sonnet-4-6"]),
        )
        assert result["status"] == "pass"

    def test_not_expected_found_fail(self):
        result = _eval_model_used(
            {"not_expected": "gpt-4"},
            self._llm_spans(["claude-sonnet-4-6", "gpt-4-turbo"]),
        )
        assert result["status"] == "fail"
        assert "prohibited" in result["detail"]

    def test_neither_specified_skip(self):
        result = _eval_model_used({}, self._llm_spans(["claude-sonnet-4-6"]))
        assert result["status"] == "skip"

    def test_expected_partial_match(self):
        """Substring match on model name."""
        result = _eval_model_used(
            {"expected": "haiku"},
            self._llm_spans(["claude-haiku-4-5"]),
        )
        assert result["status"] == "pass"

    def test_actual_field_present_on_pass(self):
        result = _eval_model_used(
            {"expected": "sonnet"},
            self._llm_spans(["claude-sonnet-4-6"]),
        )
        assert "actual" in result

    def test_actual_field_present_on_fail(self):
        result = _eval_model_used(
            {"expected": "opus"},
            self._llm_spans(["claude-sonnet-4-6"]),
        )
        assert "actual" in result

    def test_empty_spans_expected_fail(self):
        result = _eval_model_used({"expected": "sonnet"}, [])
        assert result["status"] == "fail"

    def test_empty_spans_not_expected_pass(self):
        result = _eval_model_used({"not_expected": "gpt-4"}, [])
        assert result["status"] == "pass"


# ---------------------------------------------------------------------------
# delegation_path
# ---------------------------------------------------------------------------


class TestDelegationPath:
    def test_match_pass(self):
        spans = [_subagent("copywriter"), _subagent("email-engineer")]
        result = _eval_delegation_path(
            {"expected": ["copywriter", "email-engineer"]},
            spans,
        )
        assert result["status"] == "pass"

    def test_partial_name_match_pass(self):
        """Expected entries are checked via substring."""
        spans = [_subagent("sales/lumina"), _subagent("platform/orchestrator")]
        result = _eval_delegation_path(
            {"expected": ["lumina", "orchestrator"]},
            spans,
        )
        assert result["status"] == "pass"

    def test_mismatch_fail(self):
        spans = [_subagent("copywriter")]
        result = _eval_delegation_path(
            {"expected": ["copywriter", "missing-agent"]},
            spans,
        )
        assert result["status"] == "fail"
        assert "mismatch" in result["detail"]

    def test_no_subagent_spans_warn(self):
        """When no subagent spans found, return warn not fail."""
        spans = [_llm("claude-sonnet"), _tool("brave-search")]
        result = _eval_delegation_path({"expected": ["copywriter"]}, spans)
        assert result["status"] == "warn"
        assert result["actual"] == []

    def test_empty_expected_pass_when_subagents_present(self):
        spans = [_subagent("any-agent")]
        result = _eval_delegation_path({"expected": []}, spans)
        assert result["status"] == "pass"

    def test_actual_field_in_result(self):
        spans = [_subagent("agent-a"), _subagent("agent-b")]
        result = _eval_delegation_path({"expected": ["agent-a"]}, spans)
        assert "actual" in result

    def test_no_subagent_spans_no_expected_warn(self):
        """Even with empty expected, no-subagents case returns warn."""
        result = _eval_delegation_path({"expected": []}, [_llm("llm-1")])
        assert result["status"] == "warn"

    def test_falls_back_to_state_payloads_when_no_subagent_spans(self):
        spans = [_llm("claude-sonnet"), _tool("sessions_spawn")]
        result = _eval_delegation_path(
            {"expected": ["copywriter", "email-engineer"]},
            spans,
            {
                "state_payloads": [
                    {"selected_agent": "copywriter"},
                    {"selected_agent": "email-engineer"},
                ]
            },
        )
        assert result["status"] == "pass"
        assert result["actual"] == ["copywriter", "email-engineer"]

    def test_falls_back_to_state_path_when_no_subagent_spans(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write("selected_agent: copywriter\n")
            state_path = Path(f.name)

        try:
            result = _eval_delegation_path(
                {"expected": ["copywriter"], "state_path": str(state_path)},
                [_llm("claude-sonnet")],
            )
        finally:
            state_path.unlink(missing_ok=True)

        assert result["status"] == "pass"
        assert result["actual"] == ["copywriter"]


# ---------------------------------------------------------------------------
# per_span_budget
# ---------------------------------------------------------------------------


class TestPerSpanBudget:
    def _tok(self, total: int) -> _TokenUsage:
        return _TokenUsage(input_tokens=total // 2, output_tokens=total - total // 2, total_tokens=total)

    def test_within_budget_pass(self):
        spans = [
            _llm("s1", tokens=self._tok(500)),
            _llm("s2", tokens=self._tok(800)),
        ]
        result = _eval_per_span_budget({"span_type": "llm", "max_tokens": 1000}, spans)
        assert result["status"] == "pass"

    def test_over_budget_fail(self):
        spans = [
            _llm("s1", tokens=self._tok(500)),
            _llm("s2", tokens=self._tok(2000)),
        ]
        result = _eval_per_span_budget({"span_type": "llm", "max_tokens": 1000}, spans)
        assert result["status"] == "fail"
        assert len(result["violations"]) == 1
        assert result["violations"][0]["span"] == "s2"

    def test_multiple_violations(self):
        spans = [
            _llm("s1", tokens=self._tok(2000)),
            _llm("s2", tokens=self._tok(3000)),
        ]
        result = _eval_per_span_budget({"span_type": "llm", "max_tokens": 1000}, spans)
        assert result["status"] == "fail"
        assert len(result["violations"]) == 2

    def test_span_name_filter_pass(self):
        """span_name filter: only matching spans are checked."""
        spans = [
            _llm("claude-sonnet-call", tokens=self._tok(500)),
            _llm("claude-haiku-call", tokens=self._tok(9000)),  # not filtered
        ]
        result = _eval_per_span_budget(
            {"span_type": "llm", "max_tokens": 1000, "span_name": "sonnet"},
            spans,
        )
        assert result["status"] == "pass"

    def test_span_name_filter_fail(self):
        spans = [
            _llm("claude-sonnet-call", tokens=self._tok(2000)),
            _llm("claude-haiku-call", tokens=self._tok(100)),
        ]
        result = _eval_per_span_budget(
            {"span_type": "llm", "max_tokens": 1000, "span_name": "sonnet"},
            spans,
        )
        assert result["status"] == "fail"

    def test_no_tokens_field_skipped(self):
        """Spans without token data are skipped, not flagged."""
        spans = [_llm("s1")]  # no tokens
        result = _eval_per_span_budget({"span_type": "llm", "max_tokens": 100}, spans)
        assert result["status"] == "pass"

    def test_tool_span_type(self):
        spans = [_tool("brave-search")]
        result = _eval_per_span_budget({"span_type": "tool", "max_tokens": 0}, spans)
        assert result["status"] == "pass"  # no tokens on tool span

    def test_exact_boundary_pass(self):
        """Exactly at max_tokens should pass (not strictly less than)."""
        spans = [_llm("s1", tokens=self._tok(1000))]
        result = _eval_per_span_budget({"span_type": "llm", "max_tokens": 1000}, spans)
        assert result["status"] == "pass"


# ---------------------------------------------------------------------------
# trace_token_budget
# ---------------------------------------------------------------------------


class TestTraceTokenBudget:
    def _spans_with_tokens(
        self,
        input_list: list[int],
        output_list: list[int],
    ) -> list[_Span]:
        spans = []
        for i, (inp, out) in enumerate(zip(input_list, output_list)):
            tok = _TokenUsage(input_tokens=inp, output_tokens=out, total_tokens=inp + out)
            spans.append(_llm(f"span-{i}", tokens=tok))
        return spans

    def test_within_budget_pass(self):
        spans = self._spans_with_tokens([500, 300], [200, 100])
        result = _eval_trace_token_budget(
            {"max_input_tokens": 1000, "max_output_tokens": 500},
            spans,
        )
        assert result["status"] == "pass"

    def test_input_over_fail(self):
        spans = self._spans_with_tokens([600, 600], [100, 100])
        result = _eval_trace_token_budget({"max_input_tokens": 1000}, spans)
        assert result["status"] == "fail"
        assert "input" in result["detail"]
        assert result["actual_input"] == 1200

    def test_output_over_fail(self):
        spans = self._spans_with_tokens([100, 100], [400, 400])
        result = _eval_trace_token_budget({"max_output_tokens": 500}, spans)
        assert result["status"] == "fail"
        assert "output" in result["detail"]
        assert result["actual_output"] == 800

    def test_both_over_fail(self):
        spans = self._spans_with_tokens([600, 600], [400, 400])
        result = _eval_trace_token_budget(
            {"max_input_tokens": 1000, "max_output_tokens": 500},
            spans,
        )
        assert result["status"] == "fail"
        assert "input" in result["detail"]
        assert "output" in result["detail"]

    def test_no_bounds_pass(self):
        spans = self._spans_with_tokens([9999], [9999])
        result = _eval_trace_token_budget({}, spans)
        assert result["status"] == "pass"

    def test_spans_without_tokens_ignored(self):
        """Spans without token data are ignored; only tokened spans count."""
        spans = [_llm("no-tok"), *self._spans_with_tokens([100], [50])]
        result = _eval_trace_token_budget({"max_input_tokens": 200}, spans)
        assert result["status"] == "pass"
        # The pass path embeds totals in the detail string
        assert "100" in result["detail"]

    def test_empty_spans_pass(self):
        result = _eval_trace_token_budget(
            {"max_input_tokens": 100, "max_output_tokens": 100},
            [],
        )
        assert result["status"] == "pass"


# ---------------------------------------------------------------------------
# trace_duration
# ---------------------------------------------------------------------------


class TestTraceDuration:
    def test_within_limit_pass(self):
        spans = [
            _llm("s1", duration_ms=200.0),
            _tool("s2", duration_ms=150.0),
        ]
        result = _eval_trace_duration({"max_ms": 500.0}, spans)
        assert result["status"] == "pass"
        assert "350" in result["detail"]

    def test_over_limit_fail(self):
        spans = [
            _llm("s1", duration_ms=600.0),
            _tool("s2", duration_ms=500.0),
        ]
        result = _eval_trace_duration({"max_ms": 1000.0}, spans)
        assert result["status"] == "fail"
        assert result["actual_ms"] == 1100.0
        assert result["max_ms"] == 1000.0

    def test_exact_boundary_pass(self):
        spans = [_llm("s1", duration_ms=1000.0)]
        result = _eval_trace_duration({"max_ms": 1000.0}, spans)
        assert result["status"] == "pass"

    def test_empty_spans_pass(self):
        result = _eval_trace_duration({"max_ms": 100.0}, [])
        assert result["status"] == "pass"

    def test_detail_has_duration(self):
        result = _eval_trace_duration({"max_ms": 5000.0}, [_llm("s", duration_ms=123.0)])
        assert "123" in result["detail"]

    def test_uses_wall_clock_envelope_not_sum_for_overlapping_spans(self):
        spans = [
            _llm(
                "s1",
                duration_ms=1000.0,
                start_time="2026-03-20T14:00:00+00:00",
                end_time="2026-03-20T14:00:01+00:00",
            ),
            _tool(
                "s2",
                duration_ms=1000.0,
                start_time="2026-03-20T14:00:00.500000+00:00",
                end_time="2026-03-20T14:00:01.500000+00:00",
            ),
        ]
        result = _eval_trace_duration({"max_ms": 1600.0}, spans)
        assert result["status"] == "pass"
        assert result["detail"].startswith("duration 1500.0ms")


# ---------------------------------------------------------------------------
# trace_cost
# ---------------------------------------------------------------------------


class TestTraceCost:
    def _tok_with_cost(self, cost: float) -> _TokenUsage:
        return _TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150, cost_usd=cost)

    def test_within_limit_pass(self):
        spans = [
            _llm("s1", tokens=self._tok_with_cost(0.002)),
            _llm("s2", tokens=self._tok_with_cost(0.003)),
        ]
        result = _eval_trace_cost({"max_usd": 0.01}, spans)
        assert result["status"] == "pass"

    def test_over_limit_fail(self):
        spans = [
            _llm("s1", tokens=self._tok_with_cost(0.05)),
            _llm("s2", tokens=self._tok_with_cost(0.06)),
        ]
        result = _eval_trace_cost({"max_usd": 0.10}, spans)
        assert result["status"] == "fail"
        assert result["actual_usd"] == pytest.approx(0.11)

    def test_no_cost_data_warn(self):
        """Spans without cost data produce warn, not fail."""
        spans = [_llm("s1")]  # no tokens
        result = _eval_trace_cost({"max_usd": 0.01}, spans)
        assert result["status"] == "warn"
        assert "no cost data" in result["detail"]

    def test_mixed_cost_data_uses_available(self):
        """Spans with cost_usd=None are skipped; others are summed."""
        no_cost_tok = _TokenUsage(100, 50, 150, cost_usd=None)
        with_cost_tok = self._tok_with_cost(0.005)
        spans = [
            _llm("s1", tokens=no_cost_tok),
            _llm("s2", tokens=with_cost_tok),
        ]
        result = _eval_trace_cost({"max_usd": 0.01}, spans)
        assert result["status"] == "pass"
        # The pass path embeds the cost in the detail string
        assert "0.0050" in result["detail"]

    def test_exact_boundary_pass(self):
        spans = [_llm("s1", tokens=self._tok_with_cost(0.10))]
        result = _eval_trace_cost({"max_usd": 0.10}, spans)
        assert result["status"] == "pass"

    def test_detail_shows_cost(self):
        spans = [_llm("s1", tokens=self._tok_with_cost(0.0025))]
        result = _eval_trace_cost({"max_usd": 1.0}, spans)
        assert "0.0025" in result["detail"]

    def test_empty_spans_warn(self):
        """No spans → no cost data → warn."""
        result = _eval_trace_cost({"max_usd": 0.01}, [])
        assert result["status"] == "warn"

    def test_estimates_cost_from_model_pricing_when_missing_cost_usd(self):
        spans = [
            _llm(
                "anthropic/claude-sonnet-4-6",
                tokens=_TokenUsage(
                    input_tokens=1000,
                    output_tokens=500,
                    total_tokens=1500,
                    cost_usd=None,
                ),
            )
        ]
        result = _eval_trace_cost(
            {"max_usd": 0.02},
            spans,
            {
                "model_pricing": {
                    "claude-sonnet-4-6": {
                        "input_per_1k": 0.003,
                        "output_per_1k": 0.015,
                    }
                }
            },
        )
        assert result["status"] == "pass"
        assert result["cost_is_estimated"] is True
        assert "0.0105" in result["detail"]


# ---------------------------------------------------------------------------
# no_span_errors
# ---------------------------------------------------------------------------


class TestNoSpanErrors:
    def test_no_errors_pass(self):
        spans = [_llm("s1"), _tool("s2")]
        result = _eval_no_span_errors({}, spans)
        assert result["status"] == "pass"
        assert "no span errors" in result["detail"]

    def test_with_errors_fail(self):
        spans = [
            _llm("s1"),
            _llm("s2", error="timeout after 30s"),
        ]
        result = _eval_no_span_errors({}, spans)
        assert result["status"] == "fail"
        assert len(result["errored_spans"]) == 1
        assert result["errored_spans"][0]["span"] == "s2"
        assert "timeout" in result["errored_spans"][0]["error"]

    def test_multiple_errors_all_reported(self):
        spans = [
            _llm("s1", error="error-a"),
            _tool("s2", error="error-b"),
            _llm("s3", error="error-c"),
        ]
        result = _eval_no_span_errors({}, spans)
        assert result["status"] == "fail"
        assert len(result["errored_spans"]) == 3

    def test_detail_contains_count(self):
        spans = [_llm("s1", error="boom"), _llm("s2", error="bam")]
        result = _eval_no_span_errors({}, spans)
        assert "2" in result["detail"]

    def test_errored_span_includes_type(self):
        spans = [_tool("bad-tool", error="503")]
        result = _eval_no_span_errors({}, spans)
        assert result["errored_spans"][0]["type"] == "tool"

    def test_empty_spans_pass(self):
        result = _eval_no_span_errors({}, [])
        assert result["status"] == "pass"

    def test_none_error_field_not_flagged(self):
        """Spans where error=None must not appear in errored_spans."""
        spans = [_llm("s1"), _llm("s2")]
        result = _eval_no_span_errors({}, spans)
        assert result["status"] == "pass"


# ---------------------------------------------------------------------------
# tool_not_invoked
# ---------------------------------------------------------------------------


class TestToolNotInvoked:
    def test_tool_not_called_pass(self):
        spans = [_tool("brave-search"), _tool("read-file")]
        result = _eval_tool_not_invoked({"tool": "shell-exec"}, spans)
        assert result["status"] == "pass"
        assert "shell-exec" in result["detail"]

    def test_tool_called_fail(self):
        spans = [_tool("brave-search"), _tool("shell-exec")]
        result = _eval_tool_not_invoked({"tool": "shell-exec"}, spans)
        assert result["status"] == "fail"
        assert "prohibited" in result["detail"]

    def test_actual_field_present_on_fail(self):
        spans = [_tool("shell-exec")]
        result = _eval_tool_not_invoked({"tool": "shell-exec"}, spans)
        assert "actual" in result
        assert "shell-exec" in result["actual"]

    def test_empty_spans_pass(self):
        result = _eval_tool_not_invoked({"tool": "shell-exec"}, [])
        assert result["status"] == "pass"

    def test_non_tool_spans_ignored(self):
        """LLM span named like a tool must not trigger the check."""
        spans = [_llm("shell-exec")]  # type is "llm", not "tool"
        result = _eval_tool_not_invoked({"tool": "shell-exec"}, spans)
        assert result["status"] == "pass"

    def test_empty_tool_name_config(self):
        """Empty tool name matches empty-named tool spans only."""
        spans = [_tool("")]
        result = _eval_tool_not_invoked({"tool": ""}, spans)
        assert result["status"] == "fail"

    def test_different_tool_names_pass(self):
        spans = [_tool("read-file"), _tool("write-file")]
        result = _eval_tool_not_invoked({"tool": "shell-exec"}, spans)
        assert result["status"] == "pass"
