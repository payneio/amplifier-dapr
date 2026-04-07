"""
Test that the old service directories (svc-bash, svc-filesystem, svc-search)
have been deleted as part of the consolidation refactor.

These directories were replaced by:
- svc-bash      -> svc-machine (bash execution now lives there)
- svc-filesystem -> svc-machine (filesystem access now lives there)
- svc-search    -> svc-machine (search now lives there)

"""

import subprocess
from pathlib import Path

SERVICES_DIR = Path(__file__).parent.parent / "services"
REPO_ROOT = SERVICES_DIR.parent


def test_svc_bash_directory_deleted():
    """services/svc-bash/ must not exist after consolidation."""
    assert not (SERVICES_DIR / "svc-bash").exists(), (
        "services/svc-bash/ should have been deleted during consolidation. "
        "Its functionality has been moved to svc-machine."
    )


def test_svc_filesystem_directory_deleted():
    """services/svc-filesystem/ must not exist after consolidation."""
    assert not (SERVICES_DIR / "svc-filesystem").exists(), (
        "services/svc-filesystem/ should have been deleted during consolidation. "
        "Its functionality has been moved to svc-machine."
    )


def test_svc_search_directory_deleted():
    """services/svc-search/ must not exist after consolidation."""
    assert not (SERVICES_DIR / "svc-search").exists(), (
        "services/svc-search/ should have been deleted during consolidation. "
        "Its functionality has been moved to svc-machine."
    )


def test_no_cross_service_imports_from_svc_bash():
    """No service in services/ (outside svc-bash itself) should import from svc_bash."""
    result = subprocess.run(
        [
            "grep",
            "-r",
            "--include=*.py",
            "from svc_bash\\|import svc_bash",
            "services/",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    # Filter out any matches that come from within svc-bash's own files
    matches = [line for line in result.stdout.splitlines() if "/svc-bash/" not in line]
    assert not matches, (
        "Found unexpected cross-service imports from svc_bash:\n" + "\n".join(matches)
    )


def test_no_cross_service_imports_from_svc_filesystem():
    """No service in services/ should import from svc_filesystem."""
    result = subprocess.run(
        [
            "grep",
            "-r",
            "--include=*.py",
            "from svc_filesystem\\|import svc_filesystem",
            "services/",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    matches = [
        line for line in result.stdout.splitlines() if "/svc-filesystem/" not in line
    ]
    assert not matches, (
        "Found unexpected cross-service imports from svc_filesystem:\n"
        + "\n".join(matches)
    )


def test_no_cross_service_imports_from_svc_search():
    """No service in services/ should import from svc_search."""
    result = subprocess.run(
        [
            "grep",
            "-r",
            "--include=*.py",
            "from svc_search\\|import svc_search",
            "services/",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    matches = [
        line for line in result.stdout.splitlines() if "/svc-search/" not in line
    ]
    assert not matches, (
        "Found unexpected cross-service imports from svc_search:\n" + "\n".join(matches)
    )
