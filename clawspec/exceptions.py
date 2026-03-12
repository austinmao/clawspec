from __future__ import annotations


class ClawspecError(Exception):
    """Base exception for ClawSpec errors."""


class SchemaError(ClawspecError):
    """Raised when a contract file fails schema validation."""


class GatewayError(ClawspecError):
    """Raised when the OpenClaw gateway cannot be reached or returns an error."""


class TriggerTimeoutError(GatewayError):
    """Raised when an invocation exceeds the configured timeout."""
