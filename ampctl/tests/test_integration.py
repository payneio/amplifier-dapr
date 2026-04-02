"""End-to-end integration test for ampctl: add / list / compose / inspect / remove."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from ampctl.main import main

# Locate the real agent YAML files relative to this test file:
#   ampctl/tests/test_integration.py → ampctl/tests/ → ampctl/ → amplifier-ipc/ → agents/
AGENTS_DIR = Path(__file__).parent.parent.parent / "agents"


def test_full_workflow(tmp_path: Path) -> None:
    """End-to-end: add two agents, list, compose (with deduplication), inspect, remove."""
    runner = CliRunner()
    env = {"AMPLIFIER_HOME": str(tmp_path)}

    foundation_yaml = AGENTS_DIR / "foundation.yaml"
    default_yaml = AGENTS_DIR / "default.yaml"

    # Precondition: agent files must exist
    assert foundation_yaml.exists(), (
        f"agents/foundation.yaml not found at {foundation_yaml}"
    )
    assert default_yaml.exists(), f"agents/default.yaml not found at {default_yaml}"

    # -------------------------------------------------------------------------
    # Step 1: Add foundation agent
    # -------------------------------------------------------------------------
    result = runner.invoke(main, ["add", str(foundation_yaml), "foundation"], env=env)
    assert result.exit_code == 0, f"add foundation failed:\n{result.output}"
    assert "Added" in result.output, f"Expected 'Added' in output:\n{result.output}"

    # Verify cache: foundation.yaml copied to agents dir
    cached_foundation = tmp_path / "agents" / "foundation.yaml"
    assert cached_foundation.exists(), "foundation.yaml not cached in agents dir"

    # Cached file must be valid YAML with a top-level 'agent' key
    parsed = yaml.safe_load(cached_foundation.read_text())
    assert isinstance(parsed, dict), "Cached foundation YAML is not a dict"
    assert "agent" in parsed, "Cached foundation YAML missing 'agent' key"

    # Verify service-map: foundation entry with expected fields
    sm_path = tmp_path / "service-map.yaml"
    assert sm_path.exists(), "service-map.yaml not created after add"
    sm_data = yaml.safe_load(sm_path.read_text())
    assert "foundation" in sm_data["agents"], "'foundation' not in service-map agents"

    foundation_entry = sm_data["agents"]["foundation"]
    assert "orchestrator" in foundation_entry, "foundation entry missing 'orchestrator'"
    assert "context_manager" in foundation_entry, (
        "foundation entry missing 'context_manager'"
    )
    assert "providers" in foundation_entry, "foundation entry missing 'providers'"
    assert "behaviors" in foundation_entry, "foundation entry missing 'behaviors'"

    # All app-ids follow the svc-* naming convention
    all_foundation_ids = [
        foundation_entry["orchestrator"],
        foundation_entry["context_manager"],
        foundation_entry["providers"],
    ] + list(foundation_entry["behaviors"].values())
    for app_id in all_foundation_ids:
        assert app_id.startswith("svc-"), (
            f"App-id '{app_id}' does not start with 'svc-'"
        )

    # -------------------------------------------------------------------------
    # Step 2: Add default agent
    # -------------------------------------------------------------------------
    result = runner.invoke(main, ["add", str(default_yaml), "default"], env=env)
    assert result.exit_code == 0, f"add default failed:\n{result.output}"

    cached_default = tmp_path / "agents" / "default.yaml"
    assert cached_default.exists(), "default.yaml not cached in agents dir"

    # -------------------------------------------------------------------------
    # Step 3: List agents — both should appear
    # -------------------------------------------------------------------------
    result = runner.invoke(main, ["list"], env=env)
    assert result.exit_code == 0, f"list failed:\n{result.output}"
    assert "foundation" in result.output, (
        f"'foundation' missing from list output:\n{result.output}"
    )
    assert "default" in result.output, (
        f"'default' missing from list output:\n{result.output}"
    )

    # -------------------------------------------------------------------------
    # Step 4: Generate compose file
    # -------------------------------------------------------------------------
    compose_output = tmp_path / "docker-compose.yaml"
    result = runner.invoke(main, ["compose", "--output", str(compose_output)], env=env)
    assert result.exit_code == 0, f"compose failed:\n{result.output}"
    assert compose_output.exists(), "docker-compose.yaml was not written"

    compose_data = yaml.safe_load(compose_output.read_text())
    services = compose_data["services"]

    # Redis always present
    assert "redis" in services, "redis missing from compose"

    # session-service and its Dapr sidecar always present
    assert "session-service" in services, "session-service missing from compose"
    assert "session-service-dapr" in services, (
        "session-service-dapr missing from compose"
    )

    # Every svc-* app service has a corresponding -dapr sidecar
    svc_app_names = [
        k for k in services if k.startswith("svc-") and not k.endswith("-dapr")
    ]
    assert len(svc_app_names) > 0, "No svc-* services found in compose output"
    for svc_name in svc_app_names:
        assert f"{svc_name}-dapr" in services, (
            f"Dapr sidecar '{svc_name}-dapr' missing from compose"
        )

    # Deduplication: foundation and default share the same orchestrator build path
    # → both derive to "svc-orchestrator"; it must appear exactly once in compose.
    orch_count = sum(1 for k in services if k == "svc-orchestrator")
    assert orch_count == 1, (
        f"Orchestrator service 'svc-orchestrator' appears {orch_count} times (expected 1)"
    )

    # Broader dedup: every svc-* app service must appear exactly once (no duplicates
    # from processing the same build path via two different agent files).
    svc_names = [
        k for k in services if k.startswith("svc-") and not k.endswith("-dapr")
    ]
    assert len(svc_names) > 0, "Expected svc-* services in compose output"
    for svc_name in svc_names:
        count = sum(1 for k in services if k == svc_name)
        assert count == 1, (
            f"Service '{svc_name}' appears {count} times in compose (dedup failed)"
        )

    # -------------------------------------------------------------------------
    # Step 5: Inspect foundation agent
    # -------------------------------------------------------------------------
    result = runner.invoke(main, ["inspect", "foundation"], env=env)
    assert result.exit_code == 0, f"inspect failed:\n{result.output}"
    # Ref for foundation.yaml is "foundation"
    assert "foundation" in result.output, (
        f"Agent ref 'foundation' missing from inspect output:\n{result.output}"
    )
    # Description from foundation.yaml
    assert "Full-featured agent" in result.output, (
        f"Agent description missing from inspect output:\n{result.output}"
    )

    # -------------------------------------------------------------------------
    # Step 6: Remove default agent
    # -------------------------------------------------------------------------
    result = runner.invoke(main, ["remove", "default"], env=env)
    assert result.exit_code == 0, f"remove default failed:\n{result.output}"

    # Cache file must be gone
    assert not cached_default.exists(), (
        "default.yaml still present in agents dir after remove"
    )

    # List should no longer contain 'default'
    result = runner.invoke(main, ["list"], env=env)
    assert result.exit_code == 0, f"list after remove failed:\n{result.output}"
    assert "foundation" in result.output, (
        f"'foundation' disappeared from list after removing default:\n{result.output}"
    )
    # 'default' as an agent name (stem) or ref should be absent
    # (the ref in default.yaml is "default" so both the filename and the ref would appear)
    lines = result.output.splitlines()
    agent_lines = [ln for ln in lines if "foundation" in ln or "default" in ln]
    default_lines = [ln for ln in agent_lines if ln.strip().startswith("default")]
    assert len(default_lines) == 0, (
        f"'default' agent row still present in list after remove:\n{result.output}"
    )

    # service-map must not have 'default'
    sm_data = yaml.safe_load(sm_path.read_text())
    assert "default" not in sm_data.get("agents", {}), (
        "'default' still present in service-map after remove"
    )
