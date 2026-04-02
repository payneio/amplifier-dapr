"""Tests for SafetyValidator — strict / standard / permissive profiles."""

import re

import pytest

from svc_machine.safety import SafetyValidator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def strict_validator() -> SafetyValidator:
    return SafetyValidator(profile="strict")


@pytest.fixture
def standard_validator() -> SafetyValidator:
    return SafetyValidator(profile="standard")


@pytest.fixture
def permissive_validator() -> SafetyValidator:
    return SafetyValidator(profile="permissive")


# ---------------------------------------------------------------------------
# TestStrictProfile
# ---------------------------------------------------------------------------


class TestStrictProfile:
    """Safety rules under the strict profile."""

    def test_allows_safe_commands(self, strict_validator: SafetyValidator) -> None:
        """echo hello is harmless and must be allowed."""
        allowed, reason = strict_validator.validate("echo hello")
        assert allowed is True
        assert reason is None

    def test_allows_git_commands(self, strict_validator: SafetyValidator) -> None:
        """git status must be allowed."""
        allowed, _reason = strict_validator.validate("git status")
        assert allowed is True

    def test_blocks_rm_rf_root(self, strict_validator: SafetyValidator) -> None:
        """rm -rf / is catastrophic and must be blocked with a descriptive reason."""
        allowed, reason = strict_validator.validate("rm -rf /")
        assert allowed is False
        assert reason is not None
        assert re.search(r"root|delete", reason, re.IGNORECASE), (
            f"Reason should mention 'root' or 'delete', got: {reason!r}"
        )

    def test_blocks_rm_fr_root(self, strict_validator: SafetyValidator) -> None:
        """rm -fr / (flags reversed) must also be blocked."""
        allowed, _reason = strict_validator.validate("rm -fr /")
        assert allowed is False

    def test_blocks_rm_rf_home(self, strict_validator: SafetyValidator) -> None:
        """rm -rf ~ targets the home directory and must be blocked."""
        allowed, _reason = strict_validator.validate("rm -rf ~")
        assert allowed is False

    def test_blocks_sudo(self, strict_validator: SafetyValidator) -> None:
        """sudo must be blocked with a reason mentioning 'sudo' or 'privilege'."""
        allowed, reason = strict_validator.validate("sudo apt install vim")
        assert allowed is False
        assert reason is not None
        assert re.search(r"sudo|privilege", reason, re.IGNORECASE), (
            f"Reason should mention 'sudo' or 'privilege', got: {reason!r}"
        )

    def test_blocks_mkfs(self, strict_validator: SafetyValidator) -> None:
        """mkfs formats a filesystem and must be blocked."""
        allowed, _reason = strict_validator.validate("mkfs.ext4 /dev/sda1")
        assert allowed is False

    def test_blocks_dd_dev_zero(self, strict_validator: SafetyValidator) -> None:
        """dd writing to a raw device must be blocked."""
        allowed, _reason = strict_validator.validate("dd if=/dev/zero of=/dev/sda")
        assert allowed is False

    def test_blocks_chmod_777_root(self, strict_validator: SafetyValidator) -> None:
        """chmod 777 on / is dangerous and must be blocked."""
        allowed, _reason = strict_validator.validate("chmod 777 /")
        assert allowed is False

    def test_blocks_fork_bomb(self, strict_validator: SafetyValidator) -> None:
        """Classic fork bomb must be blocked."""
        allowed, _reason = strict_validator.validate(":(){ :|:& };:")
        assert allowed is False

    def test_allows_rm_rf_on_project_dir(
        self, strict_validator: SafetyValidator
    ) -> None:
        """rm -rf on a project subdirectory (./build) is legitimate and must be allowed."""
        allowed, _reason = strict_validator.validate("rm -rf ./build")
        assert allowed is True

    def test_sudo_in_quoted_string_not_blocked(
        self, strict_validator: SafetyValidator
    ) -> None:
        """'sudo' inside a quoted string argument must NOT be treated as a sudo command."""
        allowed, _reason = strict_validator.validate("echo 'use sudo carefully'")
        assert allowed is True


# ---------------------------------------------------------------------------
# TestStandardProfile
# ---------------------------------------------------------------------------


class TestStandardProfile:
    """Safety rules under the standard (default) profile."""

    def test_allows_safe_commands(self, standard_validator: SafetyValidator) -> None:
        """echo hello must be allowed in standard profile."""
        allowed, _reason = standard_validator.validate("echo hello")
        assert allowed is True

    def test_blocks_rm_rf_root(self, standard_validator: SafetyValidator) -> None:
        """rm -rf / must be blocked in standard profile."""
        allowed, _reason = standard_validator.validate("rm -rf /")
        assert allowed is False

    def test_blocks_sudo(self, standard_validator: SafetyValidator) -> None:
        """sudo must be blocked in standard profile."""
        allowed, _reason = standard_validator.validate("sudo apt install vim")
        assert allowed is False


# ---------------------------------------------------------------------------
# TestPermissiveProfile
# ---------------------------------------------------------------------------


class TestPermissiveProfile:
    """Safety rules under the permissive profile."""

    def test_allows_sudo(self, permissive_validator: SafetyValidator) -> None:
        """sudo is allowed under permissive profile."""
        allowed, _reason = permissive_validator.validate("sudo apt install vim")
        assert allowed is True

    def test_blocks_rm_rf_root(self, permissive_validator: SafetyValidator) -> None:
        """rm -rf / must still be blocked even under permissive profile."""
        allowed, _reason = permissive_validator.validate("rm -rf /")
        assert allowed is False

    def test_blocks_fork_bomb(self, permissive_validator: SafetyValidator) -> None:
        """Fork bomb must still be blocked under permissive profile."""
        allowed, _reason = permissive_validator.validate(":(){ :|:& };:")
        assert allowed is False

    def test_allows_mkfs(self, permissive_validator: SafetyValidator) -> None:
        """mkfs is allowed under permissive profile."""
        allowed, _reason = permissive_validator.validate("mkfs.ext4 /dev/sda1")
        assert allowed is True


# ---------------------------------------------------------------------------
# TestDefaultProfile
# ---------------------------------------------------------------------------


class TestDefaultProfile:
    """Behaviour when no profile is specified (should default to 'standard')."""

    def test_default_profile_is_standard(self) -> None:
        """SafetyValidator() with no args must behave like the standard profile."""
        validator = SafetyValidator()
        # standard profile blocks sudo
        allowed, _reason = validator.validate("sudo apt install vim")
        assert allowed is False, "Default profile should block sudo (same as standard)"

    def test_invalid_profile_raises(self) -> None:
        """Constructing SafetyValidator with an unknown profile must raise ValueError."""
        with pytest.raises(ValueError, match=r"Unknown.*profile"):
            SafetyValidator(profile="nonexistent")
