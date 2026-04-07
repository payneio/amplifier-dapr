"""
Tests for amplifier-spec.md machine service consolidation updates.

These tests verify all 5 changes from task-13:
1. /describe example uses svc-machine with all 6 tools
2. Service invocation pattern removes proxy hop (svc-bash -> svc-machine)
3. Service inventory table has consolidated svc-machine entry (removes svc-bash/filesystem/search rows)
4. Individual service sections consolidated into one svc-machine section
5. Container count updated to ~26
"""

from pathlib import Path

SPEC_PATH = Path(__file__).parent.parent / "docs" / "specs" / "amplifier-spec.md"


def get_spec_content() -> str:
    return SPEC_PATH.read_text()


class TestDescribeExample:
    """Change 1: /describe example uses svc-machine with all 6 tools."""

    def test_describe_example_uses_svc_machine(self):
        """The /describe example should use svc-machine, not svc-filesystem."""
        content = get_spec_content()
        assert '"name": "svc-machine"' in content, (
            "/describe example should have 'svc-machine' as the service name"
        )

    def test_describe_example_no_svc_filesystem_name(self):
        """The /describe example should no longer use svc-filesystem as name."""
        content = get_spec_content()
        assert '"name": "svc-filesystem"' not in content, (
            "/describe example should not use 'svc-filesystem' as the service name"
        )

    def test_describe_example_includes_bash_tool(self):
        """The /describe example tools list should include bash."""
        content = get_spec_content()
        assert '"name": "bash"' in content, (
            "/describe example tools list should include 'bash'"
        )

    def test_describe_example_includes_all_six_tools(self):
        """The /describe example tools list should include all six machine tools."""
        content = get_spec_content()
        for tool in ["bash", "read_file", "write_file", "edit_file", "grep", "glob"]:
            assert f'"name": "{tool}"' in content, (
                f"/describe example tools list should include '{tool}'"
            )


class TestServiceInvocationPattern:
    """Change 2: Invocation pattern removes proxy hop."""

    def test_invocation_uses_svc_machine_directly(self):
        """Orchestrator should invoke svc-machine directly for bash."""
        content = get_spec_content()
        assert (
            "Orchestrator --[Dapr SI]--> svc-machine /tools/bash/execute" in content
        ), "Service invocation pattern should show Orchestrator -> svc-machine directly"

    def test_invocation_no_svc_bash_endpoint(self):
        """svc-bash endpoint should be removed from invocation pattern."""
        content = get_spec_content()
        assert (
            "Orchestrator --[Dapr SI]--> svc-bash /tools/bash/execute" not in content
        ), "Service invocation pattern should not have svc-bash endpoint"

    def test_invocation_no_proxy_hop(self):
        """Proxy hop line (svc-bash -> svc-machine /exec) should be removed."""
        content = get_spec_content()
        assert "svc-bash     --[Dapr SI]--> svc-machine /exec" not in content, (
            "Proxy hop line should be removed from service invocation pattern"
        )

    def test_invocation_keeps_providers_line(self):
        """Provider invocation line should be preserved."""
        content = get_spec_content()
        assert (
            "Orchestrator --[Dapr SI]--> svc-providers /providers/anthropic/complete"
            in content
        ), "Provider invocation line should still be present"

    def test_invocation_keeps_modes_line(self):
        """Modes invocation line should be preserved."""
        content = get_spec_content()
        assert "Orchestrator --[Dapr SI]--> svc-modes /hooks/mode/invoke" in content, (
            "Modes invocation line should still be present"
        )


class TestServiceInventoryTable:
    """Change 3: Service inventory table consolidated."""

    def test_table_no_svc_bash_row(self):
        """Service inventory table should not have svc-bash row."""
        content = get_spec_content()
        assert "| `svc-bash` | (tool) | BashTool |" not in content, (
            "Service inventory table should not have svc-bash row"
        )

    def test_table_no_svc_filesystem_row(self):
        """Service inventory table should not have svc-filesystem row."""
        content = get_spec_content()
        assert (
            "| `svc-filesystem` | (tool) | ReadTool, WriteTool, EditTool |"
            not in content
        ), "Service inventory table should not have svc-filesystem row"

    def test_table_no_svc_search_row(self):
        """Service inventory table should not have svc-search row."""
        content = get_spec_content()
        assert "| `svc-search` | (tool) | GrepTool, GlobTool |" not in content, (
            "Service inventory table should not have svc-search row"
        )

    def test_table_svc_machine_updated_description(self):
        """svc-machine entry should have updated description with all 6 tools."""
        content = get_spec_content()
        assert (
            "| `svc-machine` | Consolidated machine service: bash, read_file, write_file, edit_file, grep, glob. Per-session instances via SSH/SFTP driver. |"
            in content
        ), "svc-machine entry should have consolidated description"


class TestIndividualServiceSections:
    """Change 4: Individual service sections consolidated."""

    def test_no_svc_bash_section(self):
        """There should be no separate svc-bash section."""
        content = get_spec_content()
        assert "#### svc-bash" not in content, (
            "There should be no separate svc-bash section"
        )

    def test_no_svc_filesystem_section(self):
        """There should be no separate svc-filesystem section."""
        content = get_spec_content()
        assert "#### svc-filesystem" not in content, (
            "There should be no separate svc-filesystem section"
        )

    def test_no_svc_search_section(self):
        """There should be no separate svc-search section."""
        content = get_spec_content()
        assert "#### svc-search" not in content, (
            "There should be no separate svc-search section"
        )

    def test_consolidated_svc_machine_section_exists(self):
        """There should be a consolidated svc-machine section."""
        content = get_spec_content()
        assert "#### svc-machine" in content, (
            "There should be a consolidated svc-machine section"
        )

    def test_consolidated_section_has_correct_description(self):
        """The consolidated svc-machine section should have the right description."""
        content = get_spec_content()
        assert (
            "Consolidated machine service \u2014 shell execution, file operations, and search."
            in content
        ), "Consolidated svc-machine section should have the correct description"

    def test_consolidated_section_has_all_six_tools(self):
        """The consolidated svc-machine section should list all 6 tools."""
        content = get_spec_content()
        assert (
            "| Tools | bash, read_file, write_file, edit_file, grep, glob |" in content
        ), "Consolidated section should list all 6 machine tools"


class TestContainerCount:
    """Change 5: Container count updated to ~26."""

    def test_container_count_updated_to_26(self):
        """Container count should be ~26."""
        content = get_spec_content()
        assert "~26 application containers" in content, (
            "Container count should be updated to ~26"
        )

    def test_old_container_count_removed(self):
        """Old container count of ~29 should be removed."""
        content = get_spec_content()
        assert "~29 application containers" not in content, (
            "Old container count of ~29 should be removed"
        )
