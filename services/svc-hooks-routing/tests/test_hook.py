import pytest
from svc_hooks_routing.hook import RoutingHook


SAMPLE_MATRIX = {
    "name": "balanced",
    "roles": {
        "general": {"description": "General purpose tasks"},
        "fast": {"description": "Quick utility tasks"},
    },
}


@pytest.fixture
def hook_no_matrix():
    """RoutingHook with empty matrix (no effective roles)."""
    return RoutingHook(matrix={})


@pytest.fixture
def hook_with_matrix():
    """RoutingHook with a populated routing matrix."""
    return RoutingHook(matrix=SAMPLE_MATRIX)


# --- Test 1: unknown event continues ---
@pytest.mark.asyncio
async def test_unknown_event_continues(hook_no_matrix):
    result = await hook_no_matrix.handle("some:event", {})
    assert result.action == "CONTINUE"


# --- Test 2: provider:request with no matrix continues ---
@pytest.mark.asyncio
async def test_provider_request_no_matrix_continues(hook_no_matrix):
    result = await hook_no_matrix.handle("provider:request", {})
    assert result.action == "CONTINUE"


# --- Test 3: session:start continues ---
@pytest.mark.asyncio
async def test_session_start_continues(hook_with_matrix):
    result = await hook_with_matrix.handle("session:start", {})
    assert result.action == "CONTINUE"


# --- Test 4: provider:request with matrix returns INJECT_CONTEXT with role names ---
@pytest.mark.asyncio
async def test_provider_request_with_matrix_injects_context(hook_with_matrix):
    result = await hook_with_matrix.handle("provider:request", {})
    assert result.action == "INJECT_CONTEXT"
    assert result.data is not None
    context_text = result.data["context_injection"]
    assert "general" in context_text
    assert "fast" in context_text


# --- Test 5: context injection marked ephemeral ---
@pytest.mark.asyncio
async def test_context_injection_ephemeral(hook_with_matrix):
    result = await hook_with_matrix.handle("provider:request", {})
    assert result.action == "INJECT_CONTEXT"
    assert result.data is not None
    assert result.data["ephemeral"] is True
