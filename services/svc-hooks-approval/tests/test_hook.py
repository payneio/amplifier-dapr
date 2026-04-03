"""Tests for ApprovalHook — allow-list, deny-list, argument inspection, risk metadata."""

from svc_hooks_approval.hook import ApprovalHook


# ---------------------------------------------------------------------------
# TestBasicDenyList (6 tests)
# ---------------------------------------------------------------------------


class TestBasicDenyList:
    """Tests for the deny-list (deny_tools) behaviour."""

    async def test_unknown_event_continues(self):
        """Non-tool:pre events are always passed through."""
        hook = ApprovalHook(config={})
        result = await hook.handle("some:event", {"tool_name": "bash"})
        assert result.action == "CONTINUE"

    async def test_default_approved(self):
        """With no rules configured every tool is allowed."""
        hook = ApprovalHook(config={})
        result = await hook.handle("tool:pre", {"tool_name": "bash"})
        assert result.action == "CONTINUE"

    async def test_deny_by_rule(self):
        """Exact tool name in deny list is denied with a reason containing the name."""
        hook = ApprovalHook(config={"deny_tools": ["bash"]})
        result = await hook.handle("tool:pre", {"tool_name": "bash"})
        assert result.action == "DENY"
        assert result.reason is not None
        assert "bash" in result.reason

    async def test_glob_pattern_deny(self):
        """Glob wildcard in deny list matches tool names."""
        hook = ApprovalHook(config={"deny_tools": ["bash*"]})
        result = await hook.handle("tool:pre", {"tool_name": "bash_exec"})
        assert result.action == "DENY"
        assert result.reason is not None

    async def test_safe_tool_continues(self):
        """Tool not in deny list passes through even when other tools are denied."""
        hook = ApprovalHook(config={"deny_tools": ["bash"]})
        result = await hook.handle("tool:pre", {"tool_name": "web_search"})
        assert result.action == "CONTINUE"

    async def test_missing_tool_name_continues(self):
        """Missing tool_name key in data returns CONTINUE."""
        hook = ApprovalHook(config={"deny_tools": ["bash"]})
        result = await hook.handle("tool:pre", {})
        assert result.action == "CONTINUE"


# ---------------------------------------------------------------------------
# TestAllowList (4 tests)
# ---------------------------------------------------------------------------


class TestAllowList:
    """Tests for the allow-list (allow_tools) behaviour."""

    async def test_allowed_continues(self):
        """Tool present in allow_tools is passed through."""
        hook = ApprovalHook(config={"allow_tools": ["web_search", "bash"]})
        result = await hook.handle("tool:pre", {"tool_name": "bash"})
        assert result.action == "CONTINUE"

    async def test_unlisted_denied_with_reason(self):
        """Tool absent from allow_tools is denied with 'not in allow-list' reason."""
        hook = ApprovalHook(config={"allow_tools": ["web_search"]})
        result = await hook.handle("tool:pre", {"tool_name": "bash"})
        assert result.action == "DENY"
        assert result.reason is not None
        assert "not in allow-list" in result.reason

    async def test_deny_precedence_over_allow(self):
        """deny_tools overrides allow_tools when a tool appears in both."""
        hook = ApprovalHook(config={"allow_tools": ["bash"], "deny_tools": ["bash"]})
        result = await hook.handle("tool:pre", {"tool_name": "bash"})
        assert result.action == "DENY"

    async def test_allow_glob_pattern(self):
        """Glob wildcard in allow_tools matches tool names."""
        hook = ApprovalHook(config={"allow_tools": ["web_*"]})
        result = await hook.handle("tool:pre", {"tool_name": "web_search"})
        assert result.action == "CONTINUE"


# ---------------------------------------------------------------------------
# TestArgumentInspection (6 tests)
# ---------------------------------------------------------------------------


class TestArgumentInspection:
    """Tests for bash argument inspection against dangerous command patterns."""

    async def test_rm_rf_root_denied(self):
        """bash with 'rm -rf /' command is denied."""
        hook = ApprovalHook(config={})
        result = await hook.handle(
            "tool:pre",
            {"tool_name": "bash", "arguments": {"command": "rm -rf /"}},
        )
        assert result.action == "DENY"

    async def test_sudo_rm_denied(self):
        """bash with 'sudo rm' command is denied."""
        hook = ApprovalHook(config={})
        result = await hook.handle(
            "tool:pre",
            {"tool_name": "bash", "arguments": {"command": "sudo rm -rf /tmp/foo"}},
        )
        assert result.action == "DENY"

    async def test_mkfs_denied(self):
        """bash with 'mkfs' command is denied."""
        hook = ApprovalHook(config={})
        result = await hook.handle(
            "tool:pre",
            {"tool_name": "bash", "arguments": {"command": "mkfs.ext4 /dev/sda1"}},
        )
        assert result.action == "DENY"

    async def test_safe_ls_continues(self):
        """bash with safe 'ls -la' command is allowed."""
        hook = ApprovalHook(config={})
        result = await hook.handle(
            "tool:pre",
            {"tool_name": "bash", "arguments": {"command": "ls -la"}},
        )
        assert result.action == "CONTINUE"

    async def test_dd_to_dev_denied(self):
        """bash with 'dd ... of=/dev/...' command is denied."""
        hook = ApprovalHook(config={})
        result = await hook.handle(
            "tool:pre",
            {
                "tool_name": "bash",
                "arguments": {"command": "dd if=/dev/zero of=/dev/sda"},
            },
        )
        assert result.action == "DENY"

    async def test_non_bash_tool_skips_inspection(self):
        """Non-bash tools skip argument inspection even with dangerous-looking arguments."""
        hook = ApprovalHook(config={})
        result = await hook.handle(
            "tool:pre",
            {"tool_name": "web_search", "arguments": {"command": "rm -rf /"}},
        )
        assert result.action == "CONTINUE"


# ---------------------------------------------------------------------------
# TestRiskMetadata (2 tests)
# ---------------------------------------------------------------------------


class TestRiskMetadata:
    """Tests for risk metadata (data.metadata.requires_approval) check."""

    async def test_requires_approval_true_denies(self):
        """requires_approval=True in metadata results in DENY with risk_level in reason."""
        hook = ApprovalHook(config={})
        data = {
            "tool_name": "bash",
            "metadata": {"requires_approval": True, "risk_level": "high"},
        }
        result = await hook.handle("tool:pre", data)
        assert result.action == "DENY"
        assert result.reason is not None
        # reason must mention the risk_level value
        assert "high" in result.reason or "risk_level" in result.reason

    async def test_requires_approval_false_continues(self):
        """requires_approval=False in metadata allows the tool to continue."""
        hook = ApprovalHook(config={})
        data = {
            "tool_name": "bash",
            "metadata": {"requires_approval": False},
        }
        result = await hook.handle("tool:pre", data)
        assert result.action == "CONTINUE"
