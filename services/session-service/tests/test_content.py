"""Tests for content assembly module."""

from __future__ import annotations

from session_service.content import _DEFAULT_SYSTEM_PROMPT, assemble_system_prompt


# ---------------------------------------------------------------------------
# TestAssembleSystemPrompt
# ---------------------------------------------------------------------------


class TestAssembleSystemPrompt:
    """Tests for assemble_system_prompt()."""

    def test_workspace_content_included(self) -> None:
        """A single workspace file is formatted as a context_file XML block."""
        routing_table: dict = {}
        workspace_content = {"docs/readme.md": "Hello world"}
        dapr_url = "http://localhost:3500"

        result = assemble_system_prompt(routing_table, workspace_content, dapr_url)

        assert "docs/readme.md" in result
        assert "Hello world" in result
        assert "<context_file" in result

    def test_empty_workspace_returns_default(self) -> None:
        """When workspace_content is empty, the default system prompt is returned."""
        routing_table: dict = {}
        workspace_content: dict[str, str] = {}
        dapr_url = "http://localhost:3500"

        result = assemble_system_prompt(routing_table, workspace_content, dapr_url)

        assert result == _DEFAULT_SYSTEM_PROMPT
        assert len(result) > 0

    def test_multiple_workspace_files(self) -> None:
        """Multiple workspace files are all included in the output."""
        routing_table: dict = {}
        workspace_content = {
            "src/main.py": "def main(): pass",
            "docs/guide.md": "# Usage Guide",
        }
        dapr_url = "http://localhost:3500"

        result = assemble_system_prompt(routing_table, workspace_content, dapr_url)

        assert "src/main.py" in result
        assert "docs/guide.md" in result
