from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

FRONTMATTER_PATTERN = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)
ENV_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b")
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
)
KNOWN_BINARIES = {
    "bash",
    "curl",
    "docker",
    "git",
    "helm",
    "jq",
    "kubectl",
    "node",
    "npm",
    "npx",
    "python",
    "python3",
    "sh",
    "terraform",
    "uv",
}


def parse_frontmatter(markdown: str) -> tuple[dict[str, Any], str, str | None]:
    match = FRONTMATTER_PATTERN.match(markdown)
    if not match:
        return {}, markdown, "Missing YAML frontmatter"
    try:
        parsed = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        return {}, markdown, f"Invalid YAML frontmatter: {exc}"
    if not isinstance(parsed, dict):
        return {}, markdown, "Frontmatter must parse to a mapping"
    body = markdown[match.end() :]
    return parsed, body, None


def has_secret(text: str) -> str | None:
    for pattern in SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


def find_env_references(text: str) -> set[str]:
    return {
        match.group(0)
        for match in ENV_PATTERN.finditer(text)
        if not match.group(0).startswith("HTTP")
    }


CODE_FENCE_PATTERN = re.compile(r"```\w+")


def find_binary_references(text: str) -> set[str]:
    cleaned = CODE_FENCE_PATTERN.sub("", text)
    references: set[str] = set()
    for binary in KNOWN_BINARIES:
        if re.search(rf"\b{re.escape(binary)}\b", cleaned):
            references.add(binary)
    return references


def result(name: str, status: str, detail: str | None = None) -> dict[str, str | None]:
    return {"name": name, "status": status, "detail": detail}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")
