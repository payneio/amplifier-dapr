"""Shared test configuration for session-service tests.

This conftest.py provides a sys.modules mock for ``amplifier_service_sdk``
so that tests can import from ``session_service.app`` even when the SDK
package is not installed in the test environment.
"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Pydantic-based Message stub
# ---------------------------------------------------------------------------


class _Message(BaseModel):
    """Minimal stub for amplifier_service_sdk.models.Message.

    Supports the model_dump() / model_validate() interface that
    session_service.state uses.
    """

    role: str = ""
    content: str | list = ""

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# amplifier_service_sdk stub modules
# ---------------------------------------------------------------------------


def _make_sdk_stub() -> None:
    """Inject stub modules into sys.modules for amplifier_service_sdk."""
    # Only inject if the real package cannot be imported.
    try:
        import amplifier_service_sdk  # noqa: F401

        return  # Real package is available; no stub needed.
    except ImportError:
        pass

    # Top-level package stub
    sdk = ModuleType("amplifier_service_sdk")
    sys.modules["amplifier_service_sdk"] = sdk

    # amplifier_service_sdk.models
    models_mod = ModuleType("amplifier_service_sdk.models")
    models_mod.Message = _Message  # type: ignore[attr-defined]
    sys.modules["amplifier_service_sdk.models"] = models_mod
    sdk.models = models_mod  # type: ignore[attr-defined]

    # amplifier_service_sdk.service
    service_mod = ModuleType("amplifier_service_sdk.service")
    service_mod.ServiceConfig = MagicMock(name="ServiceConfig")  # type: ignore[attr-defined]
    service_mod.create_app = MagicMock(name="create_app")  # type: ignore[attr-defined]
    sys.modules["amplifier_service_sdk.service"] = service_mod
    sdk.service = service_mod  # type: ignore[attr-defined]


# Install the stub immediately so that all collected test modules can import
# session_service.app successfully.
_make_sdk_stub()
