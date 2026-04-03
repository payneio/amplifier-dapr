"""Safety validation for machine commands.

Provides SafetyValidator with strict, standard, and permissive profiles
for blocking dangerous shell commands.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Literal


@dataclass
class _BlockPattern:
    pattern: str
    reason: str
    check_type: Literal["command", "substring", "regex"] = "substring"


# ---------------------------------------------------------------------------
# Pattern lists
# ---------------------------------------------------------------------------

_STRICT_PATTERNS: list[_BlockPattern] = [
    # Catastrophic filesystem deletions — command-position checks
    _BlockPattern(
        pattern="rm -rf /",
        reason="Deletes the root filesystem — catastrophic, unrecoverable",
        check_type="command",
    ),
    _BlockPattern(
        pattern="rm -rf ~",
        reason="Deletes the home directory",
        check_type="command",
    ),
    _BlockPattern(
        pattern="rm -fr /",
        reason="Deletes the root filesystem — catastrophic, unrecoverable",
        check_type="command",
    ),
    _BlockPattern(
        pattern="rm -fr ~",
        reason="Deletes the home directory",
        check_type="command",
    ),
    # Privilege escalation — command-position checks
    _BlockPattern(
        pattern="sudo",
        reason="sudo privilege escalation is not permitted",
        check_type="command",
    ),
    _BlockPattern(
        pattern="su -",
        reason="su - privilege escalation is not permitted",
        check_type="command",
    ),
    # Raw device destruction — substring checks (dd is frequently piped/chained)
    _BlockPattern(
        pattern="dd if=/dev/zero",
        reason="dd from /dev/zero can overwrite and destroy raw devices",
        check_type="substring",
    ),
    _BlockPattern(
        pattern="dd if=/dev/random",
        reason="dd from /dev/random can overwrite and destroy raw devices",
        check_type="substring",
    ),
    # Filesystem formatting — command-position check
    _BlockPattern(
        pattern="mkfs",
        reason="mkfs formats a filesystem and permanently destroys existing data",
        check_type="command",
    ),
    # Raw device redirect — regex check
    _BlockPattern(
        pattern=r">\s*/dev/",
        reason="Redirecting output directly to a raw device is dangerous",
        check_type="regex",
    ),
    # Password changes — command-position check
    _BlockPattern(
        pattern="passwd",
        reason="passwd changes user account passwords",
        check_type="command",
    ),
    # Dangerous permission/ownership changes — substring checks
    _BlockPattern(
        pattern="chmod 777 /",
        reason="chmod 777 / makes the root filesystem world-writable",
        check_type="substring",
    ),
    _BlockPattern(
        pattern="chown -R /",
        reason="chown -R / recursively changes ownership of the entire filesystem",
        check_type="substring",
    ),
    # Fork bomb — substring check
    _BlockPattern(
        pattern=":(){ :|:& };:",
        reason="Fork bomb detected — will exhaust system resources and crash",
        check_type="substring",
    ),
]

# Standard profile is identical to strict
_STANDARD_PATTERNS: list[_BlockPattern] = list(_STRICT_PATTERNS)

# Permissive profile only blocks the most catastrophic commands
_PERMISSIVE_PATTERNS: list[_BlockPattern] = [
    _BlockPattern(
        pattern="rm -rf /",
        reason="Deletes the root filesystem — catastrophic, unrecoverable",
        check_type="command",
    ),
    _BlockPattern(
        pattern="rm -fr /",
        reason="Deletes the root filesystem — catastrophic, unrecoverable",
        check_type="command",
    ),
    _BlockPattern(
        pattern=":(){ :|:& };:",
        reason="Fork bomb detected — will exhaust system resources and crash",
        check_type="substring",
    ),
]

_PROFILES: dict[str, list[_BlockPattern]] = {
    "strict": _STRICT_PATTERNS,
    "standard": _STANDARD_PATTERNS,
    "permissive": _PERMISSIVE_PATTERNS,
}


# ---------------------------------------------------------------------------
# SafetyValidator
# ---------------------------------------------------------------------------


class SafetyValidator:
    """Validates shell commands against a configurable safety profile."""

    def __init__(self, profile: str | None = None) -> None:
        if profile is None:
            profile = os.environ.get("SAFETY_PROFILE", "standard")
        if profile not in _PROFILES:
            raise ValueError(f"Unknown safety profile: {profile!r}")
        self._profile = profile
        self._patterns = _PROFILES[profile]

    def validate(self, command: str) -> tuple[bool, str | None]:
        """Return (True, None) if the command is allowed, (False, reason) if blocked."""
        for bp in self._patterns:
            if self._check(command, bp):
                return False, bp.reason
        return True, None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check(self, command: str, bp: _BlockPattern) -> bool:
        """Dispatch to the appropriate check based on check_type."""
        if bp.check_type == "substring":
            return bp.pattern.lower() in command.lower()
        if bp.check_type == "regex":
            return bool(re.search(bp.pattern, command))
        if bp.check_type == "command":
            return self._at_command_position(command, bp.pattern)
        return False  # pragma: no cover

    def _at_command_position(self, command: str, pattern: str) -> bool:
        """Return True if *pattern* appears at a command-start position in *command*.

        A command-start position is:
        - the beginning of the string, or
        - immediately after a shell operator (;, |, &&, ||, (, $()

        Occurrences inside quoted strings are ignored.

        Extra guard: if *pattern* contains '/' and the character immediately
        after the matched text is a non-separator character (i.e. the '/' is
        the start of a longer path, not the filesystem root), skip the match.
        """
        search_from = 0
        while True:
            pos = command.find(pattern, search_from)
            if pos == -1:
                break
            search_from = pos + 1

            # Skip matches inside quoted strings
            if self._in_quoted(command, pos):
                continue

            # Must be at a command-start position
            if not self._is_cmd_start(command, pos):
                continue

            # Extra guard: if the pattern ends with (or contains) '/' and the
            # very next character is a non-separator, the '/' is part of a
            # longer path — skip.
            if "/" in pattern:
                end_pos = pos + len(pattern)
                if end_pos < len(command) and command[end_pos] not in (
                    " ",
                    "\t",
                    ";",
                    "|",
                    "&",
                    "\n",
                    "(",
                    ")",
                ):
                    continue

            return True
        return False

    def _find_quoted_regions(self, command: str) -> list[tuple[int, int]]:
        """Return a list of (start, end) index pairs for quoted substrings.

        Handles single and double quotes; respects backslash escapes inside
        double-quoted strings.
        """
        regions: list[tuple[int, int]] = []
        i = 0
        while i < len(command):
            ch = command[i]
            if ch in ('"', "'"):
                quote_char = ch
                start = i
                i += 1
                while i < len(command):
                    if command[i] == "\\" and quote_char == '"':
                        i += 2  # skip the escaped character
                    elif command[i] == quote_char:
                        regions.append((start, i))
                        i += 1
                        break
                    else:
                        i += 1
            else:
                i += 1
        return regions

    def _in_quoted(self, command: str, pos: int) -> bool:
        """Return True if *pos* falls within a quoted region of *command*."""
        return any(
            start < pos <= end for start, end in self._find_quoted_regions(command)
        )

    def _is_cmd_start(self, command: str, pos: int) -> bool:
        """Return True if *pos* is at a command-start position.

        A position is a command start if it is at index 0 or if the text
        before it (stripped of whitespace) ends with a shell operator:
        ;, |, &, (, `
        """
        if pos == 0:
            return True
        prefix = command[:pos].rstrip()
        if not prefix:
            return True
        return prefix.endswith((";", "|", "&", "(", "`"))
