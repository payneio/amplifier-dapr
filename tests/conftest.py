"""Root test conftest — applies to all tests/ modules.

Adds the amplifier-cli/src directory to sys.path so the amplifier_cli
package is importable without a pip install, regardless of whether the
package has been installed into the test environment.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# sys.path injection — makes the CLI package importable from any test file
# regardless of whether it has been pip-installed into the test environment.
# ---------------------------------------------------------------------------
_CLI_SRC = Path(__file__).parent.parent / "amplifier-cli" / "src"
if str(_CLI_SRC) not in sys.path:
    sys.path.insert(0, str(_CLI_SRC))
