"""Observability backend protocol and data classes for ClawSpec trace integration."""

from __future__ import annotations

import os
import random
import string
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TraceHandle:
    """Lightweight reference to a discovered trace."""
    id: str
    name: str
    start_time: str
    end_time: str | None = None
    backend_ref: Any = None


@dataclass(frozen=True)
class TokenUsage:
    """Token consumption for a single span."""
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float | None = None


@dataclass(frozen=True)
class SpanData:
    """Individual execution step within a trace."""
    id: str
    type: str  # "llm", "tool", "subagent"
    name: str
    start_time: str
    end_time: str | None = None
    duration_ms: float = 0.0
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    tokens: TokenUsage | None = None
    error: str | None = None


@dataclass(frozen=True)
class CostData:
    """Aggregate cost for an entire trace."""
    total_tokens: int
    total_cost_usd: float
    cost_is_estimated: bool = False
    per_span: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class EnrichResult:
    """Outcome of trace enrichment (metadata + scores)."""
    metadata_applied: bool = False
    scores_applied: bool = False
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Observability config schema
# ---------------------------------------------------------------------------

@dataclass
class ModelPricing:
    """Per-model pricing for cost estimation fallback."""
    input_per_1k: float
    output_per_1k: float


@dataclass
class OpikConfig:
    """Opik-specific configuration."""
    project_name: str = ""
    workspace: str = ""
    api_key: str = ""  # loaded from env, never from file


@dataclass
class ObservabilityConfig:
    """Top-level observability configuration from clawspec.yaml."""
    backend: str = "none"  # "opik" or "none"
    trace_poll_delay_ms: int = 3000
    time_window_padding_ms: int = 10000
    model_pricing: dict[str, ModelPricing] = field(default_factory=dict)
    opik: OpikConfig = field(default_factory=OpikConfig)


def load_observability_config(raw: dict[str, Any] | None = None) -> ObservabilityConfig:
    """Parse observability config from a dict (e.g., parsed clawspec.yaml).

    Falls back to defaults for missing keys. Loads OPIK_API_KEY from env.
    """
    if raw is None:
        return ObservabilityConfig()

    obs = raw.get("observability", {})
    if not obs:
        return ObservabilityConfig()

    # Parse model_pricing
    pricing: dict[str, ModelPricing] = {}
    raw_pricing = obs.get("model_pricing", {})
    for model_name, prices in raw_pricing.items():
        if isinstance(prices, dict):
            pricing[model_name] = ModelPricing(
                input_per_1k=float(prices.get("input_per_1k", 0.0)),
                output_per_1k=float(prices.get("output_per_1k", 0.0)),
            )

    # Parse opik config
    raw_opik = obs.get("opik", {})
    opik_cfg = OpikConfig(
        project_name=str(raw_opik.get("project_name", "")),
        workspace=str(raw_opik.get("workspace", "")),
        api_key=os.environ.get("OPIK_API_KEY", ""),
    )

    return ObservabilityConfig(
        backend=str(obs.get("backend", "none")),
        trace_poll_delay_ms=int(obs.get("trace_poll_delay_ms", 3000)),
        time_window_padding_ms=int(obs.get("time_window_padding_ms", 10000)),
        model_pricing=pricing,
        opik=opik_cfg,
    )


def parse_observability_timestamp(value: Any) -> datetime | None:
    """Parse an ISO timestamp from traces/spans. Returns None on invalid input."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    text = str(value).strip()
    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def compute_wall_clock_duration_ms(
    spans: list[Any] | None = None,
    trace: Any | None = None,
) -> float:
    """Compute wall-clock trace duration from trace envelope or span timestamps.

    Preferred sources, in order:
    1. Trace start/end envelope
    2. Earliest span start to latest span end
    3. Legacy duration fallback when no timestamps are available
    """
    trace_start = parse_observability_timestamp(
        getattr(trace, "start_time", None) if trace is not None else None
    )
    trace_end = parse_observability_timestamp(
        getattr(trace, "end_time", None) if trace is not None else None
    )
    if trace_start is not None and trace_end is not None:
        return max(0.0, (trace_end - trace_start).total_seconds() * 1000.0)

    if spans:
        ranges: list[tuple[datetime, datetime]] = []
        for span in spans:
            start = parse_observability_timestamp(getattr(span, "start_time", None))
            end = parse_observability_timestamp(getattr(span, "end_time", None))
            if start is not None and end is not None:
                ranges.append((start, end))
                continue

            duration_ms = float(getattr(span, "duration_ms", 0.0) or 0.0)
            if start is not None and duration_ms > 0:
                ranges.append((start, start + timedelta(milliseconds=duration_ms)))

        if ranges:
            earliest = min(start for start, _ in ranges)
            latest = max(end for _, end in ranges)
            return max(0.0, (latest - earliest).total_seconds() * 1000.0)

        if len(spans) == 1:
            return float(getattr(spans[0], "duration_ms", 0.0) or 0.0)

        return sum(float(getattr(span, "duration_ms", 0.0) or 0.0) for span in spans)

    return 0.0


# ---------------------------------------------------------------------------
# Run ID generator
# ---------------------------------------------------------------------------

def generate_run_id() -> str:
    """Generate a unique ClawSpec run ID.

    Format: clawspec-{YYYYMMDD}-{HHMMSS}-{random6}
    random6: lowercase alphanumeric (a-z0-9), 36^6 ≈ 2.2B combinations.
    """
    now = datetime.now(timezone.utc)
    date_part = now.strftime("%Y%m%d")
    time_part = now.strftime("%H%M%S")
    rand_part = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"clawspec-{date_part}-{time_part}-{rand_part}"


# ---------------------------------------------------------------------------
# ObservabilityBackend protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class ObservabilityBackend(Protocol):
    """Abstract interface for observability backends.

    Opik is the first and reference adapter. The protocol is vendor-agnostic.
    """

    def is_available(self) -> bool:
        """Lightweight connectivity check. Called once per session, cached."""
        ...

    def find_trace(
        self,
        agent_id: str,
        start_time: str,
        end_time: str,
        run_id: str,
        time_window_padding_ms: int = 10000,
    ) -> TraceHandle | None:
        """Find the gateway-created trace for a scenario run."""
        ...

    def get_spans(
        self,
        trace: TraceHandle,
        span_type: str | None = None,
    ) -> list[SpanData] | None:
        """Retrieve spans from a trace. Returns None on query failure."""
        ...

    def enrich_trace(
        self,
        trace: TraceHandle,
        metadata: dict[str, Any],
        scores: dict[str, float],
    ) -> EnrichResult:
        """Tag trace with metadata and assertion scores. Non-atomic."""
        ...

    def get_trace_url(self, trace: TraceHandle) -> str | None:
        """Return a dashboard URL for this trace."""
        ...

    def get_cost(self, trace: TraceHandle) -> CostData | None:
        """Return token usage and cost breakdown."""
        ...


__all__ = [
    "TraceHandle",
    "TokenUsage",
    "SpanData",
    "CostData",
    "EnrichResult",
    "ModelPricing",
    "OpikConfig",
    "ObservabilityConfig",
    "ObservabilityBackend",
    "load_observability_config",
    "parse_observability_timestamp",
    "compute_wall_clock_duration_ms",
    "generate_run_id",
]
