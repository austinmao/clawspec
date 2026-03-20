from __future__ import annotations

from clawspec.api import baseline_capture, baseline_reset, baseline_show, coverage, init, run, validate
from clawspec.config import ClawspecConfig
from clawspec.interfaces import AgentInterface, OpenClawInterface
from clawspec.models import CoverageReport, InitReport, RunReport, ValidationReport

try:
    from clawspec.observability import ObservabilityBackend, ObservabilityConfig
    _OBS_AVAILABLE = True
except ImportError:
    _OBS_AVAILABLE = False

__all__ = [
    "AgentInterface",
    "ClawspecConfig",
    "CoverageReport",
    "InitReport",
    "OpenClawInterface",
    "RunReport",
    "ValidationReport",
    "baseline_capture",
    "baseline_reset",
    "baseline_show",
    "coverage",
    "init",
    "run",
    "validate",
]

if _OBS_AVAILABLE:
    __all__ += ["ObservabilityBackend", "ObservabilityConfig"]

__version__ = "0.1.0"
