"""Tests for docker/base/Dockerfile — validates structure and required directives.

TDD: These tests were written BEFORE the Dockerfile was created.
"""

from __future__ import annotations

import re
from pathlib import Path

# Resolve the repo root relative to this test file (tests/ → project root)
REPO_ROOT = Path(__file__).parent.parent
DOCKERFILE_PATH = REPO_ROOT / "docker" / "base" / "Dockerfile"


def _content() -> str:
    """Return the Dockerfile content (fails if file missing)."""
    assert DOCKERFILE_PATH.exists(), (
        f"Dockerfile not found at {DOCKERFILE_PATH}. "
        "Create docker/base/Dockerfile per spec."
    )
    return DOCKERFILE_PATH.read_text()


def test_dockerfile_exists() -> None:
    """Dockerfile exists at docker/base/Dockerfile."""
    assert DOCKERFILE_PATH.exists(), f"Expected {DOCKERFILE_PATH} to exist"


def test_base_image_is_python_312_slim() -> None:
    """Base image must be python:3.12-slim."""
    content = _content()
    assert re.search(r"^FROM\s+python:3\.12-slim\b", content, re.MULTILINE), (
        "Dockerfile must start with 'FROM python:3.12-slim'"
    )


def test_workdir_is_app() -> None:
    """Working directory must be /app."""
    content = _content()
    assert re.search(r"^WORKDIR\s+/app\b", content, re.MULTILINE), (
        "Dockerfile must set 'WORKDIR /app'"
    )


def test_uv_installed_via_pip() -> None:
    """uv must be installed via pip with --no-cache-dir."""
    content = _content()
    assert "pip install --no-cache-dir uv" in content, (
        "Dockerfile must install uv with: pip install --no-cache-dir uv"
    )


def test_sdk_copied_to_build() -> None:
    """SDK source must be copied into /build/amplifier-service-sdk/."""
    content = _content()
    assert re.search(
        r"COPY\s+amplifier-service-sdk/\s+/build/amplifier-service-sdk/",
        content,
    ), "Dockerfile must COPY amplifier-service-sdk/ /build/amplifier-service-sdk/"


def test_sdk_installed_system_wide() -> None:
    """SDK must be installed system-wide via uv pip install --system."""
    content = _content()
    assert "uv pip install --system ." in content, (
        "Dockerfile must run 'uv pip install --system .' inside the SDK directory"
    )


def test_build_directory_removed() -> None:
    """Build artefacts must be removed after SDK installation."""
    content = _content()
    assert "rm -rf /build" in content, "Dockerfile must clean up with 'rm -rf /build'"


def test_healthcheck_configured() -> None:
    """HEALTHCHECK must use interval=10s, timeout=3s, retries=3."""
    content = _content()
    hc = re.search(r"HEALTHCHECK\s+(.+)", content)
    assert hc, "Dockerfile must contain a HEALTHCHECK instruction"
    hc_line = hc.group(1)
    assert "--interval=10s" in hc_line, "HEALTHCHECK must set --interval=10s"
    assert "--timeout=3s" in hc_line, "HEALTHCHECK must set --timeout=3s"
    assert "--retries=3" in hc_line, "HEALTHCHECK must set --retries=3"


def test_healthcheck_uses_python_urllib() -> None:
    """HEALTHCHECK CMD must use python urllib to probe /healthz."""
    content = _content()
    assert "urllib" in content, (
        "HEALTHCHECK must use Python's urllib to check the health endpoint"
    )
    assert "healthz" in content, "HEALTHCHECK must probe the /healthz endpoint"
    assert "localhost:8000" in content, (
        "HEALTHCHECK must probe http://localhost:8000/healthz"
    )


def test_port_8000_exposed() -> None:
    """Port 8000 must be EXPOSEd."""
    content = _content()
    assert re.search(r"^EXPOSE\s+8000\b", content, re.MULTILINE), (
        "Dockerfile must EXPOSE 8000"
    )
