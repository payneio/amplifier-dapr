import pytest
from svc_hooks_approval.hook import ApprovalHook


@pytest.fixture
def hook_no_deny():
    """ApprovalHook with empty deny list."""
    return ApprovalHook(config={"deny_tools": []})


@pytest.fixture
def hook_with_deny():
    """ApprovalHook with 'bash' in deny list."""
    return ApprovalHook(config={"deny_tools": ["bash"]})


# --- Test 1: unknown event continues ---
@pytest.mark.asyncio
async def test_unknown_event_continues(hook_no_deny):
    result = await hook_no_deny.handle("some:event", {"tool_name": "bash"})
    assert result.action == "CONTINUE"


# --- Test 2: tool:pre approved by default (no deny rules) ---
@pytest.mark.asyncio
async def test_tool_pre_approved_by_default(hook_no_deny):
    result = await hook_no_deny.handle("tool:pre", {"tool_name": "bash"})
    assert result.action == "CONTINUE"


# --- Test 3: tool:pre denied by exact rule ---
@pytest.mark.asyncio
async def test_tool_pre_denied_by_rule(hook_with_deny):
    result = await hook_with_deny.handle("tool:pre", {"tool_name": "bash"})
    assert result.action == "DENY"
    assert result.reason is not None
    assert "bash" in result.reason


# --- Test 4: glob pattern deny ---
@pytest.mark.asyncio
async def test_glob_pattern_deny():
    hook = ApprovalHook(config={"deny_tools": ["bash*"]})
    result = await hook.handle("tool:pre", {"tool_name": "bash_exec"})
    assert result.action == "DENY"
    assert result.reason is not None


# --- Test 5: safe tool continues with deny rules present ---
@pytest.mark.asyncio
async def test_safe_tool_continues_with_deny_rules(hook_with_deny):
    result = await hook_with_deny.handle("tool:pre", {"tool_name": "web_search"})
    assert result.action == "CONTINUE"


# --- Test 6: missing tool_name continues ---
@pytest.mark.asyncio
async def test_missing_tool_name_continues(hook_with_deny):
    result = await hook_with_deny.handle("tool:pre", {})
    assert result.action == "CONTINUE"
