"""Force-load the full-QA sink after pytest-cov has started measuring.

`addopts` names this module with `-p` so that `--noconftest` cannot drop the
sink (Plan 00463 round 10 M1). A `-p` plugin is imported while pytest parses
its arguments, before pytest-cov starts, so naming
`claude_code_hooks_daemon.qa.full_qa_gate` there ran the package `__init__`
unmeasured (00466 N110 round 3). This module sits OUTSIDE the package and
imports nothing from it; the sink is registered in `pytest_configure`, which
pytest calls after `pytest_load_initial_conftests`, where coverage starts.
"""

from __future__ import annotations

import importlib

import pytest

GATE_PLUGIN = "claude_code_hooks_daemon.qa.full_qa_gate"


def pytest_configure(config: pytest.Config) -> None:
    """Register the sink; see `full_qa_gate._gate_anchor` for the double registration.

    `register`, not `import_plugin`: a conftest.py has usually imported the
    module already, and `import_plugin` would then warn that it cannot
    rewrite its asserts. `register` still honours `-p no:<GATE_PLUGIN>`, and
    a plugin already registered under the name (`-p <GATE_PLUGIN>`) is left
    as it is, since registering a name twice raises.
    """
    if config.pluginmanager.has_plugin(GATE_PLUGIN):
        return
    config.pluginmanager.register(importlib.import_module(GATE_PLUGIN), GATE_PLUGIN)
