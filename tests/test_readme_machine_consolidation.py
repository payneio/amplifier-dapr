"""
Tests for README.md machine service consolidation documentation updates.

These tests verify:
1. Architecture diagram reflects consolidated machine service.
2. Workspace layout shows no old service directories.
3. Example command references svc-machine.
"""

from pathlib import Path

README_PATH = Path(__file__).parent.parent / "README.md"


def get_readme_content() -> str:
    return README_PATH.read_text()


class TestArchitectureDiagram:
    def test_architecture_shows_consolidated_machine_service(self):
        """Architecture diagram should show svc-machine with bash/filesystem/search."""
        content = get_readme_content()
        assert "--> svc-machine (bash, filesystem, search), svc-web, etc. (tools)" in content, (
            "Architecture diagram should reference consolidated svc-machine service"
        )

    def test_architecture_no_separate_tool_services(self):
        """Old split tool services should not appear in architecture diagram."""
        content = get_readme_content()
        # The old line that listed svc-bash, svc-filesystem, svc-search as separate tool services
        assert "svc-bash, svc-filesystem, svc-search, svc-web, etc. (tools)" not in content, (
            "Architecture diagram should not list svc-bash/svc-filesystem/svc-search separately"
        )

    def test_architecture_no_svc_machine_filesystem_suffix(self):
        """Old architecture reference to svc-machine (filesystem) should be gone."""
        content = get_readme_content()
        assert "--> svc-machine (filesystem)" not in content, (
            "Architecture diagram should not show old '(filesystem)' suffix for svc-machine"
        )


class TestWorkspaceLayout:
    def test_workspace_no_svc_bash_entry(self):
        """Workspace layout should not list svc-bash/ as a separate service."""
        content = get_readme_content()
        assert "svc-bash/" not in content, (
            "Workspace layout should not list svc-bash/ (it is now consolidated into svc-machine)"
        )

    def test_workspace_no_svc_filesystem_entry(self):
        """Workspace layout should not list svc-filesystem/ as a separate service."""
        content = get_readme_content()
        assert "svc-filesystem/" not in content, (
            "Workspace layout should not list svc-filesystem/ (it is now consolidated into svc-machine)"
        )

    def test_workspace_no_svc_search_entry(self):
        """Workspace layout should not list svc-search/ as a separate service."""
        content = get_readme_content()
        assert "svc-search/" not in content, (
            "Workspace layout should not list svc-search/ (it is now consolidated into svc-machine)"
        )

    def test_workspace_consolidated_machine_service_entry(self):
        """Workspace layout should have consolidated svc-machine entry."""
        content = get_readme_content()
        assert (
            "svc-machine/            Consolidated machine service (bash, read_file, write_file, edit_file, grep, glob)."
            in content
        ), "Workspace layout should have consolidated svc-machine service description"


class TestExampleCommand:
    def test_dev_example_uses_svc_machine(self):
        """Development example command should reference svc-machine."""
        content = get_readme_content()
        assert "cd services/svc-machine" in content, (
            "Development example should use 'cd services/svc-machine'"
        )

    def test_dev_example_no_svc_bash(self):
        """Development example command should not reference svc-bash."""
        content = get_readme_content()
        assert "cd services/svc-bash" not in content, (
            "Development example should not use 'cd services/svc-bash'"
        )
