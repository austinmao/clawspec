"""Trace-aware assertion evaluators for ClawSpec observability integration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from clawspec.observability import compute_wall_clock_duration_ms


def _load_structured(path_str: str) -> Any | None:
    try:
        path = Path(path_str)
        if not path.exists():
            return None
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _ordered_subsequence_match(
    expected: list[str],
    actual: list[str],
) -> tuple[bool, int]:
    idx = 0
    for entry in actual:
        if idx < len(expected) and expected[idx] in entry:
            idx += 1
    return idx == len(expected), idx


def _extract_agent_name(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in ("selected_agent", "agent"):
            value = payload.get(key)
            if value:
                return str(value)
    if isinstance(payload, str) and payload:
        return payload
    return None


def _extract_routing_path(
    config: dict[str, Any],
    context: dict[str, Any] | None,
) -> list[str] | None:
    sources: list[dict[str, Any]] = []
    if context:
        sources.append(context)
    sources.append(config)

    direct_list_keys = (
        "routing_path",
        "decision_path",
        "delegation_fallback_path",
    )
    payload_list_keys = (
        "routing_decisions",
        "state_payloads",
        "decision_payloads",
    )
    payload_keys = (
        "routing_decision",
        "state_payload",
        "decision_payload",
    )
    path_list_keys = ("state_paths", "routing_state_paths")
    path_keys = ("state_path", "routing_state_path")

    for source in sources:
        for key in direct_list_keys:
            value = source.get(key)
            if isinstance(value, list):
                return [str(item) for item in value if str(item).strip()]

        for key in payload_list_keys:
            value = source.get(key)
            if isinstance(value, list):
                return [
                    name
                    for item in value
                    if (name := _extract_agent_name(item)) is not None
                ]

        for key in payload_keys:
            value = source.get(key)
            if value is not None:
                name = _extract_agent_name(value)
                return [name] if name is not None else []

        for key in path_list_keys:
            value = source.get(key)
            if isinstance(value, list):
                result = []
                for item in value:
                    payload = _load_structured(str(item))
                    if (name := _extract_agent_name(payload)) is not None:
                        result.append(name)
                return result

        for key in path_keys:
            value = source.get(key)
            if value:
                payload = _load_structured(str(value))
                name = _extract_agent_name(payload)
                return [name] if name is not None else []

    return None


def _get_pricing_entry(
    model_pricing: dict[str, Any],
    model_name: str,
) -> Any | None:
    if model_name in model_pricing:
        return model_pricing[model_name]
    for key, value in model_pricing.items():
        if model_name.endswith(key) or key.endswith(model_name):
            return value
    return None


def _estimate_cost(
    model_name: str,
    tokens: Any,
    model_pricing: dict[str, Any],
) -> float | None:
    if not model_pricing:
        return None

    pricing = _get_pricing_entry(model_pricing, model_name)
    if pricing is None:
        return None

    if isinstance(pricing, dict):
        input_per_1k = float(pricing.get("input_per_1k", 0.0))
        output_per_1k = float(pricing.get("output_per_1k", 0.0))
    else:
        input_per_1k = float(getattr(pricing, "input_per_1k", 0.0))
        output_per_1k = float(getattr(pricing, "output_per_1k", 0.0))

    return (
        float(getattr(tokens, "input_tokens", 0) or 0) * input_per_1k / 1000.0
        + float(getattr(tokens, "output_tokens", 0) or 0) * output_per_1k / 1000.0
    )


def evaluate_trace_assertion(
    assertion_type: str,
    assertion_config: dict[str, Any],
    spans: list | None,
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Dispatch a trace-aware assertion to its evaluator.

    Returns: {status: "pass"|"fail"|"skip"|"warn", type: str, detail: str, ...}
    """
    if spans is None:
        return {
            "type": assertion_type,
            "status": "skip",
            "detail": "spans query failed or trace not found",
        }

    evaluators = {
        "llm_call_count": _eval_llm_call_count,
        "tool_sequence": _eval_tool_sequence,
        "model_used": _eval_model_used,
        "delegation_path": _eval_delegation_path,
        "per_span_budget": _eval_per_span_budget,
        "trace_token_budget": _eval_trace_token_budget,
        "trace_duration": _eval_trace_duration,
        "trace_cost": _eval_trace_cost,
        "no_span_errors": _eval_no_span_errors,
        "tool_not_invoked": _eval_tool_not_invoked,
    }

    evaluator = evaluators.get(assertion_type)
    if evaluator is None:
        return {
            "type": assertion_type,
            "status": "skip",
            "detail": f"unknown trace assertion type: {assertion_type}",
        }

    return evaluator(assertion_config, spans, context or {})


TRACE_ASSERTION_TYPES = [
    "llm_call_count",
    "tool_sequence",
    "model_used",
    "delegation_path",
    "per_span_budget",
    "trace_token_budget",
    "trace_duration",
    "trace_cost",
    "no_span_errors",
    "tool_not_invoked",
]


# ---------------------------------------------------------------------------
# Individual evaluators
# ---------------------------------------------------------------------------


def _eval_llm_call_count(
    config: dict[str, Any],
    spans: list,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Count LLM spans, check against min/max."""
    llm_count = sum(1 for s in spans if getattr(s, "type", "") == "llm")
    min_val = config.get("min")
    max_val = config.get("max")

    if min_val is not None and llm_count < int(min_val):
        return {
            "type": "llm_call_count",
            "status": "fail",
            "detail": f"LLM call count {llm_count} < min {min_val}",
            "actual": llm_count,
            "expected_min": min_val,
        }
    if max_val is not None and llm_count > int(max_val):
        return {
            "type": "llm_call_count",
            "status": "fail",
            "detail": f"LLM call count {llm_count} > max {max_val}",
            "actual": llm_count,
            "expected_max": max_val,
        }
    return {
        "type": "llm_call_count",
        "status": "pass",
        "detail": f"LLM call count {llm_count} within bounds",
        "actual": llm_count,
    }


def _eval_tool_sequence(
    config: dict[str, Any],
    spans: list,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check tool invocation sequence. Three modes: ordered, strict, contains."""
    expected = config.get("expected", [])
    mode = config.get("mode", "ordered")

    actual_tools = [
        getattr(s, "name", "") for s in spans if getattr(s, "type", "") == "tool"
    ]

    if mode == "strict":
        if actual_tools == expected:
            return {
                "type": "tool_sequence",
                "status": "pass",
                "detail": "exact match",
                "actual": actual_tools,
            }
        return {
            "type": "tool_sequence",
            "status": "fail",
            "detail": f"strict mismatch: expected {expected}, got {actual_tools}",
            "actual": actual_tools,
            "expected": expected,
        }

    if mode == "contains":
        missing = [t for t in expected if t not in actual_tools]
        if not missing:
            return {
                "type": "tool_sequence",
                "status": "pass",
                "detail": "all expected tools found",
                "actual": actual_tools,
            }
        return {
            "type": "tool_sequence",
            "status": "fail",
            "detail": f"missing tools: {missing}",
            "actual": actual_tools,
            "expected": expected,
            "missing": missing,
        }

    # Default: ordered (subsequence match)
    idx = 0
    for tool in actual_tools:
        if idx < len(expected) and tool == expected[idx]:
            idx += 1
    if idx == len(expected):
        return {
            "type": "tool_sequence",
            "status": "pass",
            "detail": "ordered subsequence match",
            "actual": actual_tools,
        }
    next_expected = expected[idx] if idx < len(expected) else "?"
    return {
        "type": "tool_sequence",
        "status": "fail",
        "detail": (
            f"ordered subsequence failed at position {idx}: "
            f"looking for '{next_expected}' in {actual_tools}"
        ),
        "actual": actual_tools,
        "expected": expected,
    }


def _eval_model_used(
    config: dict[str, Any],
    spans: list,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check which model was used in LLM spans."""
    expected = config.get("expected")
    not_expected = config.get("not_expected")

    llm_models = [
        getattr(s, "name", "") for s in spans if getattr(s, "type", "") == "llm"
    ]

    if expected:
        if any(expected in m for m in llm_models):
            return {
                "type": "model_used",
                "status": "pass",
                "detail": f"model {expected} found",
                "actual": llm_models,
            }
        return {
            "type": "model_used",
            "status": "fail",
            "detail": f"expected model {expected} not found in {llm_models}",
            "actual": llm_models,
            "expected": expected,
        }

    if not_expected:
        if any(not_expected in m for m in llm_models):
            return {
                "type": "model_used",
                "status": "fail",
                "detail": f"prohibited model {not_expected} was used",
                "actual": llm_models,
                "not_expected": not_expected,
            }
        return {
            "type": "model_used",
            "status": "pass",
            "detail": f"model {not_expected} not found (good)",
            "actual": llm_models,
        }

    return {
        "type": "model_used",
        "status": "skip",
        "detail": "no expected or not_expected specified",
    }


def _eval_delegation_path(
    config: dict[str, Any],
    spans: list,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check delegation/sub-agent path."""
    expected = config.get("expected", [])
    subagent_names = [
        getattr(s, "name", "") for s in spans if getattr(s, "type", "") == "subagent"
    ]

    if not subagent_names:
        fallback_path = _extract_routing_path(config, context)
        if fallback_path is not None:
            matched, idx = _ordered_subsequence_match(expected, fallback_path)
            if matched:
                return {
                    "type": "delegation_path",
                    "status": "pass",
                    "detail": "delegation path matches via routing fallback",
                    "actual": fallback_path,
                }
            return {
                "type": "delegation_path",
                "status": "fail",
                "detail": f"delegation path mismatch via routing fallback at position {idx}",
                "actual": fallback_path,
                "expected": expected,
            }
        return {
            "type": "delegation_path",
            "status": "warn",
            "detail": "no subagent spans found — delegation_path may need log-based fallback",
            "actual": [],
            "expected": expected,
        }

    matched, idx = _ordered_subsequence_match(expected, subagent_names)
    if matched:
        return {
            "type": "delegation_path",
            "status": "pass",
            "detail": "delegation path matches",
            "actual": subagent_names,
        }
    return {
        "type": "delegation_path",
        "status": "fail",
        "detail": f"delegation path mismatch at position {idx}",
        "actual": subagent_names,
        "expected": expected,
    }


def _eval_per_span_budget(
    config: dict[str, Any],
    spans: list,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check per-span token budget."""
    span_type = config.get("span_type", "llm")
    span_name = config.get("span_name")
    max_tokens = int(config.get("max_tokens", 0))

    filtered = [s for s in spans if getattr(s, "type", "") == span_type]
    if span_name:
        filtered = [s for s in filtered if span_name in getattr(s, "name", "")]

    violations = []
    for s in filtered:
        tokens = getattr(s, "tokens", None)
        if tokens is None:
            continue
        total = getattr(tokens, "total_tokens", 0)
        if total > max_tokens:
            violations.append({
                "span": getattr(s, "name", ""),
                "tokens": total,
                "max": max_tokens,
            })

    if violations:
        return {
            "type": "per_span_budget",
            "status": "fail",
            "detail": f"{len(violations)} span(s) exceeded budget",
            "violations": violations,
        }
    return {
        "type": "per_span_budget",
        "status": "pass",
        "detail": f"all {len(filtered)} spans within budget",
    }


def _eval_trace_token_budget(
    config: dict[str, Any],
    spans: list,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check total token budget across all spans."""
    max_input = config.get("max_input_tokens")
    max_output = config.get("max_output_tokens")

    total_input = 0
    total_output = 0
    for s in spans:
        tokens = getattr(s, "tokens", None)
        if tokens is None:
            continue
        total_input += getattr(tokens, "input_tokens", 0)
        total_output += getattr(tokens, "output_tokens", 0)

    failures = []
    if max_input is not None and total_input > int(max_input):
        failures.append(f"input tokens {total_input} > max {max_input}")
    if max_output is not None and total_output > int(max_output):
        failures.append(f"output tokens {total_output} > max {max_output}")

    if failures:
        return {
            "type": "trace_token_budget",
            "status": "fail",
            "detail": "; ".join(failures),
            "actual_input": total_input,
            "actual_output": total_output,
        }
    return {
        "type": "trace_token_budget",
        "status": "pass",
        "detail": f"input={total_input}, output={total_output} within budget",
    }


def _eval_trace_duration(
    config: dict[str, Any],
    spans: list,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check total trace duration."""
    max_ms = float(config.get("max_ms", 0))
    total_ms = compute_wall_clock_duration_ms(
        spans=spans,
        trace=(context or {}).get("trace"),
    )

    if total_ms > max_ms:
        return {
            "type": "trace_duration",
            "status": "fail",
            "detail": f"duration {total_ms:.1f}ms > max {max_ms:.1f}ms",
            "actual_ms": total_ms,
            "max_ms": max_ms,
        }
    return {
        "type": "trace_duration",
        "status": "pass",
        "detail": f"duration {total_ms:.1f}ms within limit",
    }


def _eval_trace_cost(
    config: dict[str, Any],
    spans: list,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check total trace cost."""
    max_usd = float(config.get("max_usd", 0))
    model_pricing = dict((context or {}).get("model_pricing", {}) or {})

    total_cost = 0.0
    has_cost_data = False
    cost_is_estimated = False
    for s in spans:
        tokens = getattr(s, "tokens", None)
        if tokens is None:
            continue

        span_cost = getattr(tokens, "cost_usd", None)
        if span_cost is None:
            span_cost = _estimate_cost(getattr(s, "name", ""), tokens, model_pricing)
            if span_cost is not None:
                cost_is_estimated = True

        if span_cost is None:
            continue

        total_cost += float(span_cost)
        has_cost_data = True

    if not has_cost_data:
        return {
            "type": "trace_cost",
            "status": "warn",
            "detail": "no cost data available — use model_pricing config for estimation",
        }

    if total_cost > max_usd:
        return {
            "type": "trace_cost",
            "status": "fail",
            "detail": f"cost ${total_cost:.4f} > max ${max_usd:.4f}",
            "actual_usd": total_cost,
            "max_usd": max_usd,
        }
    return {
        "type": "trace_cost",
        "status": "pass",
        "detail": f"cost ${total_cost:.4f} within limit",
        "cost_is_estimated": cost_is_estimated,
    }


def _eval_no_span_errors(
    config: dict[str, Any],
    spans: list,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check that no spans have errors."""
    errored = []
    for s in spans:
        error = getattr(s, "error", None)
        if error:
            errored.append({
                "span": getattr(s, "name", ""),
                "type": getattr(s, "type", ""),
                "error": str(error),
            })

    if errored:
        return {
            "type": "no_span_errors",
            "status": "fail",
            "detail": f"{len(errored)} span(s) had errors",
            "errored_spans": errored,
        }
    return {"type": "no_span_errors", "status": "pass", "detail": "no span errors"}


def _eval_tool_not_invoked(
    config: dict[str, Any],
    spans: list,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check that a specific tool was NOT called."""
    tool = config.get("tool", "")
    tool_names = [
        getattr(s, "name", "") for s in spans if getattr(s, "type", "") == "tool"
    ]

    if tool in tool_names:
        return {
            "type": "tool_not_invoked",
            "status": "fail",
            "detail": f"prohibited tool '{tool}' was called",
            "actual": tool_names,
        }
    return {
        "type": "tool_not_invoked",
        "status": "pass",
        "detail": f"tool '{tool}' was not called",
    }


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


def register_trace_assertions(register_fn):
    """Register all trace assertion types with the assertion registry."""
    for atype in TRACE_ASSERTION_TYPES:
        register_fn(atype, lambda assertion, context, _t=atype: _trace_assertion_handler(assertion, context, _t))


def _trace_assertion_handler(assertion: dict, context: dict, assertion_type: str) -> dict:
    """Bridge between ClawSpec's assertion dispatch format and trace evaluators."""
    spans = context.get("_trace_spans")
    result = evaluate_trace_assertion(assertion_type, assertion, spans)
    # Map to ClawSpec's expected result format
    return {
        "name": assertion_type,
        "status": result.get("status", "skip").upper(),
        "detail": result.get("detail", ""),
        "elapsed": "0.0s",
    }
