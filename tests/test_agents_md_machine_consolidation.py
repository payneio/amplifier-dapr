"""Tests to verify AGENTS.md reflects machine service consolidation.

These tests verify that AGENTS.md has been updated to document:
1. Container count updated to ~26 services
2. Workspace layout shows single svc-machine/ entry (no svc-bash/, svc-filesystem/, svc-search/)
3. Architecture diagram reflects consolidated machine service
4. Key patterns updated to reflect consolidation
"""

from pathlib import Path


AGENTS_MD = Path(__file__).parent.parent / ".amplifier" / "AGENTS.md"


def read_agents_md() -> str:
    return AGENTS_MD.read_text()


def test_container_count_updated_to_26():
    """Container count should be ~26 services (3 removed: svc-bash, svc-filesystem, svc-search)."""
    content = read_agents_md()
    assert "~26 services" in content, (
        "AGENTS.md should show ~26 services, not ~29. "
        "Three services were removed: svc-bash, svc-filesystem, svc-search."
    )


def test_architecture_diagram_shows_consolidated_machine():
    """Architecture diagram should show svc-machine handling bash/filesystem/search directly."""
    content = read_agents_md()
    assert "--> svc-machine (bash, filesystem, search), svc-web, etc. (tools)" in content, (
        "Architecture diagram should show svc-machine (bash, filesystem, search) directly, "
        "not the old split svc-bash/svc-filesystem/svc-search services."
    )


def test_architecture_diagram_no_old_split_services():
    """Architecture diagram should not show old split tool services."""
    content = read_agents_md()
    assert "svc-bash, svc-filesystem, svc-search, svc-web" not in content, (
        "Architecture diagram should no longer list svc-bash, svc-filesystem, svc-search separately."
    )


def test_workspace_layout_single_svc_machine_entry():
    """Workspace layout should have a single consolidated svc-machine/ entry."""
    content = read_agents_md()
    assert "Consolidated machine service (bash, read_file, write_file, edit_file, grep, glob)" in content, (
        "svc-machine/ workspace entry should describe the consolidated service."
    )
    assert "Per-session instances via SSH/SFTP or local driver" in content, (
        "svc-machine/ workspace entry should mention per-session instance management."
    )


def test_workspace_layout_no_svc_bash():
    """Workspace layout should not have a separate svc-bash/ entry."""
    content = read_agents_md()
    assert "svc-bash/" not in content, (
        "svc-bash/ should not appear in workspace layout — it is now consolidated into svc-machine/."
    )


def test_workspace_layout_no_svc_filesystem():
    """Workspace layout should not have a separate svc-filesystem/ entry."""
    content = read_agents_md()
    assert "svc-filesystem/" not in content, (
        "svc-filesystem/ should not appear in workspace layout — it is now consolidated into svc-machine/."
    )


def test_workspace_layout_no_svc_search():
    """Workspace layout should not have a separate svc-search/ entry."""
    content = read_agents_md()
    assert "svc-search/" not in content, (
        "svc-search/ should not appear in workspace layout — it is now consolidated into svc-machine/."
    )


def test_key_patterns_updated_for_consolidation():
    """Key patterns section should reflect that machine tools are consolidated in svc-machine."""
    content = read_agents_md()
    # The new text describes the consolidated machine service (bold on leading term follows file convention)
    assert (
        "(bash, read_file, write_file, edit_file, grep, glob) are consolidated in svc-machine "
        "with per-session instance management. Other tool services (web, skills, etc.) are standalone."
    ) in content, (
        "Key patterns should describe the consolidated svc-machine approach, not the old delegation pattern."
    )


def test_key_patterns_no_old_delegation_description():
    """Key patterns should not have the old 'Tool services call svc-machine via Dapr SI' text."""
    content = read_agents_md()
    # The old content uses markdown bold: **Tool services** call svc-machine via Dapr SI...
    assert "**Tool services** call svc-machine via Dapr SI for filesystem/command access" not in content, (
        "Old delegation pattern description should be replaced with consolidated machine service description."
    )
