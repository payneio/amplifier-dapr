"""Tests for CreateSessionRequest and CreateSessionResponse models."""

from __future__ import annotations

from session_service.app import CreateSessionRequest, CreateSessionResponse


class TestCreateSessionModels:
    """Tests for session creation Pydantic models."""

    def test_create_session_request_defaults(self) -> None:
        """CreateSessionRequest with agent_ref='foundation' has machine_config=None."""
        req = CreateSessionRequest(agent_ref="foundation")
        assert req.agent_ref == "foundation"
        assert req.machine_config is None

    def test_create_session_request_with_machine_config(self) -> None:
        """CreateSessionRequest accepts a machine_config dict with type/host/working_dir."""
        config = {
            "type": "ssh",
            "host": "example.com",
            "working_dir": "/workspace",
        }
        req = CreateSessionRequest(agent_ref="default", machine_config=config)
        assert req.agent_ref == "default"
        assert req.machine_config is not None
        assert req.machine_config == config
        assert req.machine_config["type"] == "ssh"
        assert req.machine_config["host"] == "example.com"
        assert req.machine_config["working_dir"] == "/workspace"

    def test_create_session_response_fields(self) -> None:
        """CreateSessionResponse stores session_id and machine_instance_id."""
        resp = CreateSessionResponse(
            session_id="sess-abc123",
            machine_instance_id="machine-xyz",
        )
        assert resp.session_id == "sess-abc123"
        assert resp.machine_instance_id == "machine-xyz"

    def test_create_session_response_no_machine(self) -> None:
        """CreateSessionResponse machine_instance_id defaults to None."""
        resp = CreateSessionResponse(session_id="sess-def456")
        assert resp.session_id == "sess-def456"
        assert resp.machine_instance_id is None
