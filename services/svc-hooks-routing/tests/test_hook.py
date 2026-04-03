"""Tests for RoutingHook with real resolve(model_role) logic."""

from pathlib import Path

import pytest
from svc_hooks_routing.hook import RoutingHook, load_matrix_from_file

SAMPLE_MATRIX = {
    "name": "balanced",
    "roles": {
        "fast": {
            "description": "Quick utility tasks",
            "candidates": [{"provider": "anthropic", "model": "claude-haiku-4-5"}],
        },
        "general": {
            "description": "General purpose tasks",
            "candidates": [{"provider": "anthropic", "model": "claude-sonnet-4-6"}],
        },
    },
}

EMPTY_CANDIDATES_MATRIX = {
    "name": "test",
    "roles": {
        "empty_role": {
            "description": "Role with no candidates",
            "candidates": [],
        }
    },
}


@pytest.fixture
def hook_no_matrix():
    """RoutingHook with empty matrix (no effective roles)."""
    return RoutingHook(matrix={})


@pytest.fixture
def hook_with_matrix():
    """RoutingHook with a populated routing matrix including candidates."""
    return RoutingHook(matrix=SAMPLE_MATRIX)


@pytest.fixture
def hook_empty_candidates():
    """RoutingHook with a role that has no candidates."""
    return RoutingHook(matrix=EMPTY_CANDIDATES_MATRIX)


class TestBasicBehavior:
    """Covers basic hook event routing behavior."""

    async def test_unknown_event_continues(self, hook_no_matrix):
        result = await hook_no_matrix.handle("some:event", {})
        assert result.action == "CONTINUE"

    async def test_provider_request_no_matrix_continues(self, hook_no_matrix):
        result = await hook_no_matrix.handle("provider:request", {})
        assert result.action == "CONTINUE"

    async def test_session_start_continues(self, hook_with_matrix):
        result = await hook_with_matrix.handle("session:start", {})
        assert result.action == "CONTINUE"

    async def test_provider_request_no_role_injects_context(self, hook_with_matrix):
        """provider:request without model_role and with matrix → INJECT_CONTEXT listing roles."""
        result = await hook_with_matrix.handle("provider:request", {})
        assert result.action == "INJECT_CONTEXT"
        assert result.data is not None
        context_text = result.data["context_injection"]
        assert "general" in context_text
        assert "fast" in context_text
        assert "Quick utility tasks" in context_text
        assert "General purpose tasks" in context_text


class TestResolveModelRole:
    """Covers resolve(model_role) behavior via provider:request."""

    async def test_fast_role_returns_modify_with_haiku(self, hook_with_matrix):
        result = await hook_with_matrix.handle(
            "provider:request", {"model_role": "fast"}
        )
        assert result.action == "MODIFY"
        assert result.data is not None
        assert result.data["provider"] == "anthropic"
        assert result.data["model"] == "claude-haiku-4-5"

    async def test_general_role_returns_modify_with_sonnet(self, hook_with_matrix):
        result = await hook_with_matrix.handle(
            "provider:request", {"model_role": "general"}
        )
        assert result.action == "MODIFY"
        assert result.data is not None
        assert result.data["provider"] == "anthropic"
        assert result.data["model"] == "claude-sonnet-4-6"

    async def test_unknown_role_returns_continue(self, hook_with_matrix):
        result = await hook_with_matrix.handle(
            "provider:request", {"model_role": "nonexistent"}
        )
        assert result.action == "CONTINUE"

    async def test_empty_candidates_returns_continue(self, hook_empty_candidates):
        result = await hook_empty_candidates.handle(
            "provider:request", {"model_role": "empty_role"}
        )
        assert result.action == "CONTINUE"

    async def test_modify_preserves_original_data_fields(self, hook_with_matrix):
        original_data = {
            "model_role": "fast",
            "messages": [{"role": "user", "content": "Hello"}],
            "temperature": 0.7,
        }
        result = await hook_with_matrix.handle("provider:request", original_data)
        assert result.action == "MODIFY"
        assert result.data is not None
        # Original fields preserved in merged result
        assert result.data["messages"] == [{"role": "user", "content": "Hello"}]
        assert result.data["temperature"] == 0.7
        assert result.data["model_role"] == "fast"
        # Resolved fields added
        assert result.data["provider"] == "anthropic"
        assert result.data["model"] == "claude-haiku-4-5"


class TestLoadMatrixFromFile:
    """Covers load_matrix_from_file() and resolve() with a real YAML file."""

    def test_loads_yaml_and_resolves_role(self, tmp_path: Path) -> None:
        """load_matrix_from_file() loads YAML; resolve() returns correct provider+model."""
        matrix_yaml = """\
name: test_matrix
roles:
  coding:
    description: Code generation tasks
    candidates:
      - provider: anthropic
        model: claude-opus-4-5
"""
        matrix_file = tmp_path / "routing.yaml"
        matrix_file.write_text(matrix_yaml)

        matrix = load_matrix_from_file(matrix_file)
        hook = RoutingHook(matrix=matrix)

        resolved = hook.resolve("coding")
        assert resolved is not None
        assert resolved["provider"] == "anthropic"
        assert resolved["model"] == "claude-opus-4-5"

    def test_matrix_name_preserved(self, tmp_path: Path) -> None:
        """load_matrix_from_file() preserves the matrix name field."""
        matrix_yaml = """\
name: my_routing_matrix
roles: {}
"""
        matrix_file = tmp_path / "routing.yaml"
        matrix_file.write_text(matrix_yaml)

        matrix = load_matrix_from_file(matrix_file)
        assert matrix["name"] == "my_routing_matrix"

    def test_missing_file_returns_empty_dict(self, tmp_path: Path) -> None:
        """load_matrix_from_file() returns {} when the file does not exist."""
        missing = tmp_path / "nonexistent.yaml"
        result = load_matrix_from_file(missing)
        assert result == {}

    def test_unresolvable_role_returns_none(self, tmp_path: Path) -> None:
        """resolve() returns None for a role absent from the loaded matrix."""
        matrix_yaml = """\
name: sparse
roles:
  fast:
    candidates:
      - provider: anthropic
        model: claude-haiku-4-5
"""
        matrix_file = tmp_path / "routing.yaml"
        matrix_file.write_text(matrix_yaml)

        matrix = load_matrix_from_file(matrix_file)
        hook = RoutingHook(matrix=matrix)

        assert hook.resolve("nonexistent") is None
