"""Opik backend adapter for ClawSpec observability integration."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from clawspec.observability import (
    CostData,
    EnrichResult,
    ObservabilityConfig,
    SpanData,
    TokenUsage,
    TraceHandle,
)

logger = logging.getLogger(__name__)

# Lazy import — opik is optional
_Opik = None


def _get_opik_class() -> type | None:
    global _Opik
    if _Opik is None:
        try:
            from opik import Opik as _OpikClass  # type: ignore[import-not-found]

            _Opik = _OpikClass
        except ImportError:
            _Opik = None
    return _Opik


class OpikBackend:
    """Opik adapter implementing the ObservabilityBackend protocol."""

    def __init__(self, config: ObservabilityConfig) -> None:
        self._config = config
        self._client: Any | None = None
        self._available: bool | None = None

    def _get_client(self) -> Any | None:
        if self._client is not None:
            return self._client
        opik_class = _get_opik_class()
        if opik_class is None:
            return None
        try:
            kwargs: dict[str, Any] = {}
            if self._config.opik.api_key:
                kwargs["api_key"] = self._config.opik.api_key
            if self._config.opik.workspace:
                kwargs["workspace"] = self._config.opik.workspace
            self._client = opik_class(**kwargs)
            return self._client
        except Exception as exc:
            logger.warning("Failed to create Opik client: %s", exc)
            return None

    def is_available(self) -> bool:
        """Lightweight connectivity check. Called once per session, cached."""
        if self._available is not None:
            return self._available
        client = self._get_client()
        if client is None:
            self._available = False
            return False
        try:
            client.search_traces(
                project_name=self._config.opik.project_name,
                max_results=1,
            )
            self._available = True
        except Exception as exc:
            logger.warning("Opik backend unavailable: %s", exc)
            self._available = False
        return self._available

    def find_trace(
        self,
        agent_id: str,
        start_time: str,
        end_time: str,
        run_id: str,
        time_window_padding_ms: int = 10000,
    ) -> TraceHandle | None:
        """Find the gateway-created trace for a scenario run.

        Three-tier matching strategy:
        1. Tag contains clawspec:{run_id} (fastest — already tagged)
        2. Input contains run_id (first discovery — tags on hit)
        3. Time-window + agent name fallback (tags on hit)
        """
        client = self._get_client()
        if client is None:
            return None
        project = self._config.opik.project_name

        # Strategy 1: Search by clawspec tag
        try:
            tag_query = f'tags contains "clawspec:{run_id}"'
            traces = client.search_traces(
                project_name=project,
                filter_string=tag_query,
                max_results=5,
            )
            if traces:
                return self._to_handle(traces[0])
        except Exception:
            pass

        # Strategy 2: Search by input containing run_id
        try:
            input_query = f'input contains "{run_id}"'
            traces = client.search_traces(
                project_name=project,
                filter_string=input_query,
                max_results=5,
            )
            if traces:
                handle = self._to_handle(traces[0])
                self._tag_trace(client, traces[0], run_id)
                return handle
        except Exception:
            pass

        # Strategy 3: Time-window + agent name fallback
        try:
            padding = timedelta(milliseconds=time_window_padding_ms)
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            from_time = start_dt - padding
            to_time = end_dt + padding

            time_query = (
                f'start_time >= "{from_time.isoformat()}" '
                f'AND start_time <= "{to_time.isoformat()}"'
            )
            traces = client.search_traces(
                project_name=project,
                filter_string=time_query,
                max_results=20,
            )
            matching = [t for t in (traces or []) if agent_id in getattr(t, "name", "")]
            if not matching:
                return None
            if len(matching) == 1:
                handle = self._to_handle(matching[0])
                self._tag_trace(client, matching[0], run_id)
                return handle
            # Multiple matches — pick closest to start_time
            best = min(
                matching,
                key=lambda t: abs(
                    (
                        datetime.fromisoformat(
                            getattr(t, "start_time", start_time).replace("Z", "+00:00")
                        )
                        - start_dt
                    ).total_seconds()
                ),
            )
            handle = self._to_handle(best)
            self._tag_trace(client, best, run_id)
            return handle
        except Exception as exc:
            logger.warning("find_trace time-window fallback failed: %s", exc)

        return None

    def get_spans(
        self,
        trace: TraceHandle,
        span_type: str | None = None,
    ) -> list[SpanData] | None:
        """Retrieve spans from a trace. Returns None on query failure."""
        client = self._get_client()
        if client is None:
            return None
        try:
            filter_parts = []
            if span_type and span_type in ("llm", "tool"):
                filter_parts.append(f'type = "{span_type}"')
            filter_str = " AND ".join(filter_parts) if filter_parts else None

            kwargs: dict[str, Any] = {
                "project_name": self._config.opik.project_name,
                "trace_id": trace.id,
                "max_results": 1000,
            }
            if filter_str:
                kwargs["filter_string"] = filter_str

            raw_spans = client.search_spans(**kwargs)
            if raw_spans is None:
                return None

            result: list[SpanData] = []
            for s in raw_spans:
                mapped_type = self._map_span_type(s)
                if span_type == "subagent" and mapped_type != "subagent":
                    continue
                tokens = self._extract_tokens(s)
                result.append(
                    SpanData(
                        id=getattr(s, "id", ""),
                        type=mapped_type,
                        name=getattr(s, "name", ""),
                        start_time=str(getattr(s, "start_time", "")),
                        end_time=(
                            str(getattr(s, "end_time", ""))
                            if getattr(s, "end_time", None)
                            else None
                        ),
                        duration_ms=float(getattr(s, "duration", 0) or 0) * 1000,
                        input=getattr(s, "input", None),
                        output=getattr(s, "output", None),
                        metadata=dict(getattr(s, "metadata", {}) or {}),
                        tokens=tokens,
                        error=getattr(s, "error_info", None) or getattr(s, "error", None),
                    )
                )
            return result
        except Exception as exc:
            logger.warning("get_spans failed: %s", exc)
            return None

    def enrich_trace(
        self,
        trace: TraceHandle,
        metadata: dict[str, Any],
        scores: dict[str, float],
    ) -> EnrichResult:
        """Tag trace with metadata and assertion scores. Non-atomic."""
        result = EnrichResult()
        client = self._get_client()
        if client is None:
            result.errors.append("Opik client not available")
            return result

        # Step 1: Update metadata and tags
        try:
            existing_tags = list(getattr(trace.backend_ref, "tags", []) or [])
            tags = list(existing_tags)
            run_tag = f"clawspec:{metadata.get('clawspec_run_id', '')}"
            if run_tag not in tags:
                tags.append(run_tag)
            if metadata.get("clawspec"):
                if "clawspec" not in tags:
                    tags.append("clawspec")
            client.update_trace(
                trace_id=trace.id,
                project_name=self._config.opik.project_name,
                metadata=metadata,
                tags=tags,
            )
            if trace.backend_ref is not None:
                setattr(trace.backend_ref, "tags", tags)
            result.metadata_applied = True
        except Exception as exc:
            result.errors.append(f"metadata update failed: {exc}")

        # Step 2: Log feedback scores
        try:
            if scores:
                score_entries = [
                    {"id": trace.id, "name": name, "value": value, "source": "clawspec"}
                    for name, value in scores.items()
                ]
                client.log_traces_feedback_scores(
                    scores=score_entries,
                    project_name=self._config.opik.project_name,
                )
            result.scores_applied = True
        except Exception as exc:
            result.errors.append(f"score logging failed: {exc}")

        return result

    def get_trace_url(self, trace: TraceHandle) -> str | None:
        """Return a dashboard URL for this trace."""
        project = self._config.opik.project_name
        if not project:
            return None
        return f"https://app.comet.ml/opik/projects/{project}/traces/{trace.id}"

    def get_cost(self, trace: TraceHandle) -> CostData | None:
        """Return token usage and cost breakdown."""
        spans = self.get_spans(trace)
        if spans is None:
            return None
        if not spans:
            return CostData(total_tokens=0, total_cost_usd=0.0)

        total_tokens = 0
        total_cost = 0.0
        is_estimated = False
        per_span: list[dict[str, Any]] = []

        for s in spans:
            if s.tokens is None:
                continue
            total_tokens += s.tokens.total_tokens
            span_cost = s.tokens.cost_usd
            if span_cost is None:
                span_cost = self._estimate_cost(s.name, s.tokens)
                if span_cost is not None:
                    is_estimated = True
                else:
                    span_cost = 0.0
            total_cost += span_cost
            per_span.append(
                {
                    "span_id": s.id,
                    "type": s.type,
                    "name": s.name,
                    "tokens": s.tokens.total_tokens,
                    "cost": span_cost,
                }
            )

        return CostData(
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            cost_is_estimated=is_estimated,
            per_span=per_span,
        )

    # --- Private helpers ---

    def _to_handle(self, raw_trace: Any) -> TraceHandle:
        return TraceHandle(
            id=getattr(raw_trace, "id", ""),
            name=getattr(raw_trace, "name", ""),
            start_time=str(getattr(raw_trace, "start_time", "")),
            end_time=(
                str(getattr(raw_trace, "end_time", ""))
                if getattr(raw_trace, "end_time", None)
                else None
            ),
            backend_ref=raw_trace,
        )

    def _tag_trace(self, client: Any, raw_trace: Any, run_id: str) -> None:
        """Tag trace with clawspec run_id for future fast lookup (best-effort)."""
        try:
            existing_tags = list(getattr(raw_trace, "tags", []) or [])
            new_tag = f"clawspec:{run_id}"
            if new_tag not in existing_tags:
                existing_tags.append(new_tag)
                client.update_trace(
                    trace_id=getattr(raw_trace, "id", ""),
                    project_name=self._config.opik.project_name,
                    tags=existing_tags,
                )
        except Exception:
            pass  # Non-critical — tagging is for future query optimization

    def _map_span_type(self, raw_span: Any) -> str:
        """Map Opik SpanType to ClawSpec taxonomy (llm, tool, subagent)."""
        raw_type = str(getattr(raw_span, "type", "general")).lower()
        if raw_type == "llm":
            return "llm"
        if raw_type == "tool":
            return "tool"
        # "general" type — check metadata and name for delegation markers
        meta = getattr(raw_span, "metadata", {}) or {}
        name = str(getattr(raw_span, "name", "")).lower()
        if any(k in meta for k in ("subagent_id", "delegation", "spawned_agent")):
            return "subagent"
        if "subagent" in name or "delegation" in name or "spawn" in name:
            return "subagent"
        return "tool"

    def _extract_tokens(self, raw_span: Any) -> TokenUsage | None:
        """Extract token usage from an Opik span's usage field."""
        usage = getattr(raw_span, "usage", None)
        if usage is None:
            return None
        if isinstance(usage, dict):
            inp = int(usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0))
            out = int(usage.get("completion_tokens", 0) or usage.get("output_tokens", 0))
            total = int(usage.get("total_tokens", inp + out))
            cost = usage.get("cost") or usage.get("total_cost")
            return TokenUsage(
                input_tokens=inp,
                output_tokens=out,
                total_tokens=total,
                cost_usd=float(cost) if cost is not None else None,
            )
        # Object with attributes
        inp = int(getattr(usage, "prompt_tokens", 0) or getattr(usage, "input_tokens", 0))
        out = int(getattr(usage, "completion_tokens", 0) or getattr(usage, "output_tokens", 0))
        total = int(getattr(usage, "total_tokens", inp + out))
        cost = getattr(usage, "cost", None) or getattr(usage, "total_cost", None)
        return TokenUsage(
            input_tokens=inp,
            output_tokens=out,
            total_tokens=total,
            cost_usd=float(cost) if cost is not None else None,
        )

    def _estimate_cost(self, model_name: str, tokens: TokenUsage) -> float | None:
        """Estimate span cost from model_pricing config (exact then suffix match)."""
        pricing = self._config.model_pricing
        if not pricing:
            return None
        # Exact match
        if model_name in pricing:
            p = pricing[model_name]
            return (tokens.input_tokens * p.input_per_1k / 1000) + (
                tokens.output_tokens * p.output_per_1k / 1000
            )
        # Suffix match
        for key, p in pricing.items():
            if model_name.endswith(key) or key.endswith(model_name):
                return (tokens.input_tokens * p.input_per_1k / 1000) + (
                    tokens.output_tokens * p.output_per_1k / 1000
                )
        return None
