"""Redaction pre-hook: scans all event data for secrets and redacts them."""

from __future__ import annotations

import re
from typing import Any, Literal

from amplifier_service_sdk.models import HookResult

# Structural fields that are never scanned — they carry control metadata, not content.
_STRUCTURAL_FIELDS = frozenset(
    {"tool_name", "event", "hook_name", "action", "session_id"}
)

# Compiled regex patterns for secret detection.
# Each entry is (pattern, replacement_tag).
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # AWS access key IDs: AKIA followed by 16 uppercase alphanumerics
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED:aws-key]"),
    # JWTs: three base64url segments separated by dots, all starting with eyJ
    (
        re.compile(r"eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),
        "[REDACTED:jwt]",
    ),
    # OpenAI-style API keys: sk- followed by 20+ alphanumerics
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "[REDACTED:api-key]"),
    # Email addresses
    (
        re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),
        "[REDACTED:email]",
    ),
    # PEM private key headers
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "[REDACTED:private-key]"),
]


def _redact_string(value: str) -> str:
    """Apply all redaction patterns to a single string value."""
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def _redact_value(value: Any) -> tuple[Any, bool]:
    """Recursively redact secrets from a value.

    Returns (redacted_value, was_changed).
    """
    if isinstance(value, str):
        redacted = _redact_string(value)
        return redacted, redacted != value

    if isinstance(value, dict):
        return _redact_dict(value)

    if isinstance(value, list):
        return _redact_list(value)

    # Non-string scalars (int, float, bool, None) need no redaction.
    return value, False


def _redact_dict(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Recursively redact a dict, skipping structural fields."""
    changed = False
    result: dict[str, Any] = {}
    for key, val in data.items():
        if key in _STRUCTURAL_FIELDS:
            result[key] = val
        else:
            new_val, val_changed = _redact_value(val)
            result[key] = new_val
            if val_changed:
                changed = True
    return result, changed


def _redact_list(items: list[Any]) -> tuple[list[Any], bool]:
    """Recursively redact a list."""
    changed = False
    result: list[Any] = []
    for item in items:
        new_item, item_changed = _redact_value(item)
        result.append(new_item)
        if item_changed:
            changed = True
    return result, changed


class RedactionHook:
    """Universal pre-hook that scans all event data for secrets and redacts them.

    Fires on every event type (events=['*']), runs synchronously at priority 1
    (highest) so secrets are stripped before any downstream hook sees the data.

    Structural control fields (tool_name, event, hook_name, action, session_id)
    are preserved as-is to avoid breaking the hook dispatch machinery.
    """

    name: str = "redaction"
    events: list[str] = ["*"]
    priority: int = 1
    mode: Literal["sync", "async"] = "sync"

    async def handle(self, event: str, data: dict[str, Any]) -> HookResult:
        """Scan data for secrets and return MODIFY if any were found."""
        redacted_data, changed = _redact_dict(data)
        if changed:
            return HookResult(action="MODIFY", data=redacted_data)
        return HookResult(action="CONTINUE")
