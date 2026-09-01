"""Package import smoke test for claude_code_hooks_daemon.config_optimisation."""

from __future__ import annotations

import claude_code_hooks_daemon.config_optimisation as config_optimisation


def test_package_imports() -> None:
    assert config_optimisation is not None
