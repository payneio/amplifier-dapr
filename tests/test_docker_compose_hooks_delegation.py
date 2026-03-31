"""Tests for hooks + delegation services in docker-compose.yaml (task-12).

TDD: These tests were written BEFORE docker-compose.yaml was updated.
Validates that all 5 new hook/delegation service+sidecar pairs are defined
with correct configuration, and that subscriptions.yaml exists with the
correct Dapr Subscription resources.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
COMPOSE_PATH = REPO_ROOT / "docker-compose.yaml"
SUBSCRIPTIONS_PATH = REPO_ROOT / "docker" / "dapr" / "components" / "subscriptions.yaml"

# The 5 new service names (application services)
HOOK_DELEGATION_SERVICES = [
    "svc-hooks-approval",
    "svc-hooks-routing",
    "svc-hooks-async",
    "svc-hooks-shell",
    "svc-delegation",
]

# Sidecar names for the 5 new services
HOOK_DELEGATION_SIDECARS = [f"{svc}-dapr" for svc in HOOK_DELEGATION_SERVICES]

# Expected env vars per service (in addition to DAPR_HTTP_PORT)
EXPECTED_EXTRA_ENV: dict[str, dict[str, str]] = {
    "svc-hooks-approval": {"DENY_TOOLS": ""},
    "svc-hooks-routing": {"ROUTING_MATRIX_PATH": ""},
    "svc-hooks-async": {"LOG_TEMPLATE": "~/.amplifier/logs/{session_id}/events.jsonl"},
    "svc-hooks-shell": {"SHELL_HOOKS_DIR": ""},
    "svc-delegation": {},  # standard config, no extra env
}

# Topics and their expected scopes
SUBSCRIPTION_TOPICS: dict[str, list[str]] = {
    "tool.post": ["svc-hooks-async", "svc-hooks-shell"],
    "tool.pre": ["svc-hooks-async"],
    "session.start": ["svc-hooks-async", "svc-hooks-shell"],
    "session.end": ["svc-hooks-async", "svc-hooks-shell"],
    "provider.request": ["svc-hooks-async"],
    "prompt.complete": ["svc-hooks-async", "svc-hooks-shell"],
}


def _load_compose() -> dict:
    """Load and parse docker-compose.yaml."""
    assert COMPOSE_PATH.exists(), f"Required file not found: {COMPOSE_PATH}."
    with COMPOSE_PATH.open() as f:
        return yaml.safe_load(f)


def _services(compose: dict) -> dict:
    """Return the services dict from a parsed compose file."""
    return compose.get("services", {})


def _load_subscriptions() -> list[dict]:
    """Load and parse subscriptions.yaml, returning list of YAML documents."""
    assert SUBSCRIPTIONS_PATH.exists(), (
        f"Required file not found: {SUBSCRIPTIONS_PATH}. "
        "Create docker/dapr/components/subscriptions.yaml with Dapr Subscription resources."
    )
    with SUBSCRIPTIONS_PATH.open() as f:
        docs = list(yaml.safe_load_all(f))
    # Filter out None documents (from empty sections)
    return [d for d in docs if d is not None]


def _env_has_key(env: dict | list, key: str) -> bool:
    """Check if an env var key exists in list or dict format."""
    if isinstance(env, list):
        return any(str(e).startswith(f"{key}=") or str(e) == key for e in env)
    return key in env


def _env_get_value(env: dict | list, key: str) -> str | None:
    """Get an env var value from list or dict format, or None if not present.

    Note: when env is a dict and YAML yields a bare key with no value (e.g.
    ``DENY_TOOLS:``), ``env.get(key)`` returns ``None``, which is
    indistinguishable from a missing key.  The current compose file always
    supplies an explicit value (``""`` or a path string), so this case is not
    triggered in practice.
    """
    if isinstance(env, list):
        for entry in env:
            s = str(entry)
            if s == key:
                return ""
            if s.startswith(f"{key}="):
                return s[len(key) + 1 :]
        return None
    val = env.get(key)
    return str(val) if val is not None else None


def _deps_list(deps: dict | list) -> list:
    """Normalise a depends_on value to a plain list of service names.

    Docker Compose allows depends_on as either a list of strings or a dict
    mapping service names to condition objects.  Both forms are valid YAML;
    this helper coerces either into a flat list so callers can use ``in``.
    """
    return list(deps) if isinstance(deps, dict) else deps


class TestHookDelegationServicesExist:
    """All 5 new hook/delegation application services must be defined."""

    def test_all_hook_delegation_services_present(self) -> None:
        """docker-compose.yaml defines all 5 new hook/delegation services."""
        compose = _load_compose()
        services = _services(compose)
        for svc in HOOK_DELEGATION_SERVICES:
            assert svc in services, (
                f"Service '{svc}' not found in docker-compose.yaml. "
                f"Found: {sorted(services.keys())}"
            )

    def test_all_hook_delegation_sidecars_present(self) -> None:
        """docker-compose.yaml defines all 5 new hook/delegation Dapr sidecars."""
        compose = _load_compose()
        services = _services(compose)
        for svc in HOOK_DELEGATION_SERVICES:
            sidecar = f"{svc}-dapr"
            assert sidecar in services, (
                f"Sidecar '{sidecar}' not found in docker-compose.yaml."
            )


class TestHookDelegationBuildConfig:
    """Each new application service must have correct build configuration."""

    def test_all_services_have_build_context(self) -> None:
        """All hook/delegation services use build context '.'."""
        compose = _load_compose()
        services = _services(compose)
        for svc in HOOK_DELEGATION_SERVICES:
            build = services[svc].get("build", {})
            context = build.get("context", "")
            assert context == ".", (
                f"Service '{svc}' should have build context '.', got '{context}'"
            )

    def test_all_services_have_dockerfile(self) -> None:
        """All hook/delegation services specify a dockerfile path."""
        compose = _load_compose()
        services = _services(compose)
        for svc in HOOK_DELEGATION_SERVICES:
            build = services[svc].get("build", {})
            dockerfile = build.get("dockerfile", "")
            assert dockerfile, (
                f"Service '{svc}' should specify a dockerfile path, got: {build}"
            )
            assert "Dockerfile" in dockerfile, (
                f"Service '{svc}' dockerfile path should reference 'Dockerfile', got '{dockerfile}'"
            )


class TestHookDelegationEnvironment:
    """Each service must have the correct environment variables."""

    def test_all_services_have_dapr_http_port(self) -> None:
        """All hook/delegation services have DAPR_HTTP_PORT=3500."""
        compose = _load_compose()
        services = _services(compose)
        for svc in HOOK_DELEGATION_SERVICES:
            env = services[svc].get("environment", {})
            assert _env_get_value(env, "DAPR_HTTP_PORT") == "3500", (
                f"Service '{svc}' should have DAPR_HTTP_PORT=3500 in environment, got: {env}"
            )

    def test_all_services_have_correct_extra_env(self) -> None:
        """All hook/delegation services have the expected extra environment variables."""
        compose = _load_compose()
        services = _services(compose)
        for svc, expected in EXPECTED_EXTRA_ENV.items():
            env = services[svc].get("environment", {})
            for key, val in expected.items():
                assert _env_has_key(env, key), (
                    f"Service '{svc}' missing '{key}' in environment, got: {env}"
                )
                if val:  # Only assert value equality when a specific value is expected
                    assert _env_get_value(env, key) == val, (
                        f"Service '{svc}'.{key} should be '{val}', "
                        f"got '{_env_get_value(env, key)}'"
                    )


class TestHookDelegationDependencies:
    """Verify correct dependency chains for new services."""

    def test_all_services_depend_on_redis(self) -> None:
        """All hook/delegation services depend on redis."""
        compose = _load_compose()
        services = _services(compose)
        for svc in HOOK_DELEGATION_SERVICES:
            deps = services[svc].get("depends_on", [])
            deps_list = _deps_list(deps)
            assert "redis" in deps_list, (
                f"Service '{svc}' should depend on redis, got: {deps_list}"
            )


class TestHookDelegationDaprSidecars:
    """Each new Dapr sidecar must follow the established pattern."""

    def test_all_sidecars_use_correct_image(self) -> None:
        """All hook/delegation Dapr sidecars use daprio/daprd:1.14.4."""
        compose = _load_compose()
        services = _services(compose)
        for svc in HOOK_DELEGATION_SERVICES:
            sidecar = f"{svc}-dapr"
            img = services[sidecar].get("image", "")
            assert img == "daprio/daprd:1.14.4", (
                f"{sidecar} should use image 'daprio/daprd:1.14.4', got '{img}'"
            )

    def test_all_sidecars_correct_app_id(self) -> None:
        """Each sidecar's command includes --app-id=<service-name>."""
        compose = _load_compose()
        services = _services(compose)
        for svc in HOOK_DELEGATION_SERVICES:
            sidecar = f"{svc}-dapr"
            command = services[sidecar].get("command", [])
            cmd_str = " ".join(str(c) for c in command)
            assert f"--app-id={svc}" in cmd_str, (
                f"{sidecar} command should include '--app-id={svc}', got: {cmd_str}"
            )

    def test_all_sidecars_app_port_8000(self) -> None:
        """Each sidecar's command includes --app-port=8000."""
        compose = _load_compose()
        services = _services(compose)
        for svc in HOOK_DELEGATION_SERVICES:
            sidecar = f"{svc}-dapr"
            command = services[sidecar].get("command", [])
            cmd_str = " ".join(str(c) for c in command)
            assert "--app-port=8000" in cmd_str, (
                f"{sidecar} command should include '--app-port=8000', got: {cmd_str}"
            )

    def test_all_sidecars_dapr_http_port(self) -> None:
        """Each sidecar's command includes --dapr-http-port=3500."""
        compose = _load_compose()
        services = _services(compose)
        for svc in HOOK_DELEGATION_SERVICES:
            sidecar = f"{svc}-dapr"
            command = services[sidecar].get("command", [])
            cmd_str = " ".join(str(c) for c in command)
            assert "--dapr-http-port=3500" in cmd_str, (
                f"{sidecar} command should include '--dapr-http-port=3500', got: {cmd_str}"
            )

    def test_all_sidecars_dapr_grpc_port(self) -> None:
        """Each sidecar's command includes --dapr-grpc-port=50001."""
        compose = _load_compose()
        services = _services(compose)
        for svc in HOOK_DELEGATION_SERVICES:
            sidecar = f"{svc}-dapr"
            command = services[sidecar].get("command", [])
            cmd_str = " ".join(str(c) for c in command)
            assert "--dapr-grpc-port=50001" in cmd_str, (
                f"{sidecar} command should include '--dapr-grpc-port=50001', got: {cmd_str}"
            )

    def test_all_sidecars_resources_path(self) -> None:
        """Each sidecar's command includes --resources-path=/components."""
        compose = _load_compose()
        services = _services(compose)
        for svc in HOOK_DELEGATION_SERVICES:
            sidecar = f"{svc}-dapr"
            command = services[sidecar].get("command", [])
            cmd_str = " ".join(str(c) for c in command)
            assert "--resources-path=/components" in cmd_str, (
                f"{sidecar} command should include '--resources-path=/components', got: {cmd_str}"
            )

    def test_all_sidecars_config(self) -> None:
        """Each sidecar's command includes --config=/config/config.yaml."""
        compose = _load_compose()
        services = _services(compose)
        for svc in HOOK_DELEGATION_SERVICES:
            sidecar = f"{svc}-dapr"
            command = services[sidecar].get("command", [])
            cmd_str = " ".join(str(c) for c in command)
            assert "--config=/config/config.yaml" in cmd_str, (
                f"{sidecar} command should include '--config=/config/config.yaml', got: {cmd_str}"
            )

    def test_all_sidecars_volumes(self) -> None:
        """Each Dapr sidecar mounts components and config volumes."""
        compose = _load_compose()
        services = _services(compose)
        for svc in HOOK_DELEGATION_SERVICES:
            sidecar = f"{svc}-dapr"
            volumes = services[sidecar].get("volumes", [])
            volumes_str = " ".join(str(v) for v in volumes)
            assert "components" in volumes_str, (
                f"{sidecar} should mount a components volume, got: {volumes}"
            )
            assert "config" in volumes_str or "dapr" in volumes_str, (
                f"{sidecar} should mount a config/dapr volume, got: {volumes}"
            )

    def test_all_sidecars_network_mode(self) -> None:
        """Each Dapr sidecar uses network_mode: service:<svc>."""
        compose = _load_compose()
        services = _services(compose)
        for svc in HOOK_DELEGATION_SERVICES:
            sidecar = f"{svc}-dapr"
            network_mode = services[sidecar].get("network_mode", "")
            expected = f"service:{svc}"
            assert network_mode == expected, (
                f"{sidecar} network_mode should be '{expected}', got '{network_mode}'"
            )

    def test_all_sidecars_depend_on_their_service(self) -> None:
        """Each Dapr sidecar depends on its own application service."""
        compose = _load_compose()
        services = _services(compose)
        for svc in HOOK_DELEGATION_SERVICES:
            sidecar = f"{svc}-dapr"
            deps = services[sidecar].get("depends_on", [])
            deps_list = _deps_list(deps)
            assert svc in deps_list, (
                f"{sidecar} should depend on '{svc}', got: {deps_list}"
            )


class TestSessionServiceUpdatedForHooksDelegation:
    """session-service depends_on must include all new hook/delegation Dapr sidecars."""

    def test_session_service_depends_on_all_new_sidecars(self) -> None:
        """session-service depends_on includes all 5 new hook/delegation Dapr sidecars."""
        compose = _load_compose()
        services = _services(compose)
        deps = services["session-service"].get("depends_on", [])
        deps_list = _deps_list(deps)
        for sidecar in HOOK_DELEGATION_SIDECARS:
            assert sidecar in deps_list, (
                f"session-service should depend on '{sidecar}', got: {deps_list}"
            )


class TestSubscriptionsYaml:
    """docker/dapr/components/subscriptions.yaml must exist with correct Subscription resources."""

    def test_subscriptions_file_exists(self) -> None:
        """docker/dapr/components/subscriptions.yaml exists."""
        assert SUBSCRIPTIONS_PATH.exists(), (
            f"subscriptions.yaml not found at {SUBSCRIPTIONS_PATH}"
        )

    def test_subscriptions_file_is_valid_yaml(self) -> None:
        """subscriptions.yaml is valid YAML."""
        docs = _load_subscriptions()
        assert len(docs) > 0, (
            "subscriptions.yaml should contain at least one YAML document"
        )

    def test_all_subscriptions_are_dapr_v1alpha1(self) -> None:
        """All subscription resources use apiVersion: dapr.io/v1alpha1."""
        docs = _load_subscriptions()
        for doc in docs:
            assert doc.get("apiVersion") == "dapr.io/v1alpha1", (
                f"Subscription should have apiVersion 'dapr.io/v1alpha1', got: {doc.get('apiVersion')}"
            )

    def test_all_subscriptions_are_subscription_kind(self) -> None:
        """All subscription resources have kind: Subscription."""
        docs = _load_subscriptions()
        for doc in docs:
            assert doc.get("kind") == "Subscription", (
                f"Resource should have kind 'Subscription', got: {doc.get('kind')}"
            )

    def test_all_subscriptions_have_pubsubname(self) -> None:
        """All subscription resources have spec.pubsubName: pubsub."""
        docs = _load_subscriptions()
        for doc in docs:
            spec = doc.get("spec", {})
            pubsubname = spec.get("pubsubName") or spec.get("pubsubname")
            assert pubsubname == "pubsub", (
                f"Subscription '{doc.get('metadata', {}).get('name')}' "
                f"should have spec.pubsubName 'pubsub', got: {pubsubname!r}"
            )

    def test_all_required_topics_covered(self) -> None:
        """subscriptions.yaml covers all 6 required topics."""
        docs = _load_subscriptions()
        covered_topics = set()
        for doc in docs:
            spec = doc.get("spec", {})
            topic = spec.get("topic")
            if topic:
                covered_topics.add(topic)
        for topic in SUBSCRIPTION_TOPICS:
            assert topic in covered_topics, (
                f"Topic '{topic}' not covered in subscriptions.yaml. "
                f"Covered topics: {covered_topics}"
            )

    def test_tool_post_scopes(self) -> None:
        """tool.post subscription has scopes: svc-hooks-async, svc-hooks-shell."""
        docs = _load_subscriptions()
        _assert_topic_scopes(docs, "tool.post", ["svc-hooks-async", "svc-hooks-shell"])

    def test_tool_pre_scopes(self) -> None:
        """tool.pre subscription has scope: svc-hooks-async."""
        docs = _load_subscriptions()
        _assert_topic_scopes(docs, "tool.pre", ["svc-hooks-async"])

    def test_session_start_scopes(self) -> None:
        """session.start subscription has scopes: svc-hooks-async, svc-hooks-shell."""
        docs = _load_subscriptions()
        _assert_topic_scopes(
            docs, "session.start", ["svc-hooks-async", "svc-hooks-shell"]
        )

    def test_session_end_scopes(self) -> None:
        """session.end subscription has scopes: svc-hooks-async, svc-hooks-shell."""
        docs = _load_subscriptions()
        _assert_topic_scopes(
            docs, "session.end", ["svc-hooks-async", "svc-hooks-shell"]
        )

    def test_provider_request_scopes(self) -> None:
        """provider.request subscription has scope: svc-hooks-async."""
        docs = _load_subscriptions()
        _assert_topic_scopes(docs, "provider.request", ["svc-hooks-async"])

    def test_prompt_complete_scopes(self) -> None:
        """prompt.complete subscription has scopes: svc-hooks-async, svc-hooks-shell."""
        docs = _load_subscriptions()
        _assert_topic_scopes(
            docs, "prompt.complete", ["svc-hooks-async", "svc-hooks-shell"]
        )

    def test_routes_to_events_endpoint(self) -> None:
        """Each subscription routes to /events/{topic}."""
        docs = _load_subscriptions()
        for doc in docs:
            spec = doc.get("spec", {})
            topic = spec.get("topic")
            if not topic:
                continue
            # Route can be a string directly or inside a rules structure
            route = spec.get("route", "")
            if isinstance(route, str):
                expected = f"/events/{topic}"
                assert route == expected, (
                    f"Subscription for topic '{topic}' should route to '{expected}', got '{route}'"
                )


def _assert_topic_scopes(
    docs: list[dict], topic: str, expected_scopes: list[str]
) -> None:
    """Helper: assert that a subscription for the given topic has the expected scopes."""
    # Collect all scopes across all docs matching this topic
    all_scopes: list[str] = []
    for doc in docs:
        spec = doc.get("spec", {})
        if spec.get("topic") == topic:
            scopes = spec.get("scopes", [])
            all_scopes.extend(scopes)

    assert all_scopes, (
        f"No subscription found for topic '{topic}' in subscriptions.yaml"
    )
    for scope in expected_scopes:
        assert scope in all_scopes, (
            f"Topic '{topic}' should have scope '{scope}', got scopes: {all_scopes}"
        )
