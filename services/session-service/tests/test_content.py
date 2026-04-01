"""Tests for content assembly module."""

from __future__ import annotations

import pytest

from session_service.content import assemble_system_prompt


# ---------------------------------------------------------------------------
# TestAssembleSystemPrompt
# ---------------------------------------------------------------------------


class TestAssembleSystemPrompt:
    """Tests for assemble_system_prompt()."""

    @pytest.mark.anyio
    async def test_workspace_content_included(self) -> None:
        """A workspace content string is included verbatim in the output."""
        routing_table: dict = {}
        workspace_content = (
            '<context_file path="docs/readme.md">\nHello world\n</context_file>'
        )

        result = await assemble_system_prompt(
            routing_table, workspace_content=workspace_content
        )

        assert "docs/readme.md" in result
        assert "Hello world" in result
        assert "<context_file" in result

    @pytest.mark.anyio
    async def test_empty_workspace_returns_default(self) -> None:
        """When no content sources are available, the fallback prompt is returned."""
        routing_table: dict = {}

        result = await assemble_system_prompt(routing_table)

        assert result == "You are a helpful assistant."
        assert len(result) > 0

    @pytest.mark.anyio
    async def test_multiple_workspace_files(self) -> None:
        """Multiple workspace context blocks are all included in the output."""
        routing_table: dict = {}
        ws_parts = [
            '<context_file path="src/main.py">\ndef main(): pass\n</context_file>',
            '<context_file path="docs/guide.md">\n# Usage Guide\n</context_file>',
        ]
        workspace_content = "\n\n".join(ws_parts)

        result = await assemble_system_prompt(
            routing_table, workspace_content=workspace_content
        )

        assert "src/main.py" in result
        assert "docs/guide.md" in result

    @pytest.mark.anyio
    async def test_agent_system_prompt_prepended(self) -> None:
        """Agent system prompt appears before workspace content."""
        routing_table: dict = {}
        workspace_content = (
            '<context_file path="readme.md">\ncontent\n</context_file>'
        )
        agent_prompt = "You are a specialist agent."

        result = await assemble_system_prompt(
            routing_table,
            workspace_content=workspace_content,
            agent_system_prompt=agent_prompt,
        )

        assert result.startswith(agent_prompt)
        assert "readme.md" in result

    @pytest.mark.anyio
    async def test_no_content_services_skips_fetch(self) -> None:
        """When _content_services is empty, no HTTP calls are made."""
        routing_table: dict = {"_content_services": {}}

        result = await assemble_system_prompt(routing_table)

        assert result == "You are a helpful assistant."
