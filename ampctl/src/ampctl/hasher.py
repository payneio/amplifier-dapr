"""Deterministic service name hashing for Dapr app-id generation."""

import hashlib


def hash_source(source_key: str) -> str:
    """Return the first 8 hex characters of the SHA-256 hash of source_key."""
    digest = hashlib.sha256(source_key.encode()).hexdigest()
    return digest[:8]


def generate_service_name(role_key: str, source_key: str) -> str:
    """Return a deterministic Dapr app-id in the form svc-{role_key}-{hash}."""
    return f"svc-{role_key}-{hash_source(source_key)}"
