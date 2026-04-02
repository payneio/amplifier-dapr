"""Tests for deterministic service name hashing."""

from ampctl.hasher import generate_service_name, hash_source


def test_hash_determinism() -> None:
    """Same input always produces the same 8-character hash."""
    result1 = hash_source("ghcr.io/example/orchestrator:latest")
    result2 = hash_source("ghcr.io/example/orchestrator:latest")
    assert result1 == result2
    assert len(result1) == 8


def test_hash_different_inputs() -> None:
    """Different inputs produce different hashes."""
    h1 = hash_source("ghcr.io/example/orchestrator:latest")
    h2 = hash_source("ghcr.io/example/context-manager:latest")
    assert h1 != h2


def test_generate_service_name_format() -> None:
    """Service name follows the svc-{role}-{hash} pattern."""
    name = generate_service_name("bash", "ghcr.io/example/bash:latest")
    assert name.startswith("svc-bash-")
    parts = name.split("-")
    # svc, bash, <8-char-hash>
    assert parts[0] == "svc"
    assert parts[1] == "bash"
    assert len(parts[2]) == 8


def test_generate_service_name_with_build_path() -> None:
    """Build paths work as source keys for name generation."""
    name = generate_service_name("orchestrator", "./services/my-service")
    assert name.startswith("svc-orchestrator-")
    hash_part = name[len("svc-orchestrator-") :]
    assert len(hash_part) == 8
    assert all(c in "0123456789abcdef" for c in hash_part)


def test_same_image_same_hash() -> None:
    """Two different roles using the same image share the same hash suffix."""
    name1 = generate_service_name("orchestrator", "ghcr.io/shared/runtime:v1")
    name2 = generate_service_name("providers", "ghcr.io/shared/runtime:v1")
    suffix1 = name1[len("svc-orchestrator-") :]
    suffix2 = name2[len("svc-providers-") :]
    assert suffix1 == suffix2
