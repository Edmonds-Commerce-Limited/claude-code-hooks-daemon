"""Venv-free entry point for the upgrade gate (Plan 00376 Tasks 1.2 and 3.1).

Run this file DIRECTLY with any python3 >= 3.11 -- do not ``import`` it and
do not invoke it via ``-m``:

    python3 <daemon_dir>/src/claude_code_hooks_daemon/install/upgrade_gate_standalone.py \\
        --daemon-dir <daemon_dir> --project-root <root> --to <target> \\
        --installed-stamp <venv stamp> --target-stamp <stamp> --target-ref <ref> \\
        [--include-unreleased] [--acknowledgement <digest>]

    python3 .../upgrade_gate_standalone.py approve --daemon-dir <daemon_dir> \\
        --project-root <root> --from <installed> --to <target>

    python3 .../upgrade_gate_standalone.py record-install --daemon-dir <daemon_dir> \\
        --project-root <root> --stamp <stamp>

The second form is the project owner's approval, from the target's own code
(an installed daemon older than the gate has no ``approve-upgrade``). It needs
a terminal and a typed phrase, so an agent's shell cannot run it.

The third form is what a FRESH install calls, so its first re-run is not sent
to the owner as an install of unknown history (N327).

Layer 2 (``scripts/upgrade_version.sh``) runs the gate BEFORE it builds the
target's venv, so a stopped upgrade has changed nothing but the checkout,
which it then restores. The gate and everything it uses are standard-library
only, but a normal dotted import runs ``claude_code_hooks_daemon/__init__.py``
first, and that imports pydantic. So this module loads each file by path,
registered under its real dotted name in ``sys.modules`` BEFORE executing it,
dependencies first -- the pattern ``daemon/signal_standalone.py`` established.
``tests/unit/install/test_upgrade_gate_standalone.py`` pins that no
third-party module and no package ``__init__`` loads, and that every package
import of a loaded file is itself in the load list below.

The floor is 3.11 because ``utils/one_shot_approval.py`` imports
``datetime.UTC``; the daemon itself needs the same.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

_MIN_PYTHON = (3, 11)

if sys.version_info[:2] < _MIN_PYTHON:
    print(
        "ERROR: upgrade_gate_standalone.py needs python3 >= 3.11 "
        f"(this interpreter is {sys.version_info[0]}.{sys.version_info[1]}).",
        file=sys.stderr,
    )
    sys.exit(1)

if TYPE_CHECKING:
    from claude_code_hooks_daemon.install import upgrade_gate as _upgrade_gate_type

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent

#: Load order: every module after its own package dependencies.
_LOAD_ORDER: tuple[tuple[str, str], ...] = (
    ("claude_code_hooks_daemon.install.version_parse", "install/version_parse.py"),
    ("claude_code_hooks_daemon.install.install_stamp", "install/install_stamp.py"),
    ("claude_code_hooks_daemon.utils.path_containment", "utils/path_containment.py"),
    ("claude_code_hooks_daemon.utils.path_predicates", "utils/path_predicates.py"),
    ("claude_code_hooks_daemon.install.upgrade_guides", "install/upgrade_guides.py"),
    ("claude_code_hooks_daemon.utils.escape_hatch", "utils/escape_hatch.py"),
    ("claude_code_hooks_daemon.utils.deliberate_swallow", "utils/deliberate_swallow.py"),
    ("claude_code_hooks_daemon.install.upgrade_tasks", "install/upgrade_tasks.py"),
    ("claude_code_hooks_daemon.utils.one_shot_approval", "utils/one_shot_approval.py"),
    ("claude_code_hooks_daemon.daemon.install_layout", "daemon/install_layout.py"),
    ("claude_code_hooks_daemon.install.upgrade_gate", "install/upgrade_gate.py"),
)


def _load_by_file_path(dotted_name: str, file_path: Path) -> ModuleType:
    """Load one module by path under its dotted name (see the module docstring)."""
    cached = sys.modules.get(dotted_name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(dotted_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {dotted_name!r} from {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[dotted_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[dotted_name]
        raise
    return module


if TYPE_CHECKING:
    upgrade_gate = _upgrade_gate_type
else:
    for _dotted, _relative in _LOAD_ORDER:
        upgrade_gate = _load_by_file_path(_dotted, _PACKAGE_ROOT / _relative)


_APPROVE_SUBCOMMAND = "approve"
_RECORD_INSTALL_SUBCOMMAND = "record-install"

if __name__ == "__main__":
    if sys.argv[1:2] == [_APPROVE_SUBCOMMAND]:
        sys.exit(upgrade_gate.approve_main(sys.argv[2:]))
    if sys.argv[1:2] == [_RECORD_INSTALL_SUBCOMMAND]:
        sys.exit(upgrade_gate.record_install_main(sys.argv[2:]))
    sys.exit(upgrade_gate.main())
