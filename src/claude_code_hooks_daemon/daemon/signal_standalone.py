"""Venv-free entry point for ``signal`` (Plan 00457, GitHub issue #55).

Run this file DIRECTLY with any system ``python3`` -- do not ``import`` it
and do not invoke it via ``-m``:

    python3 <daemon_root>/src/claude_code_hooks_daemon/daemon/signal_standalone.py \\
        <kind> [--minutes N] --all-sessions --project-root <root>

``bin/hooks-daemon`` resolves a venv before it reads the subcommand (Plan
00192). For a project whose only venv was built inside a container, that
venv's slug does not match the host path and its interpreter cannot run on
the host, so ``signal`` -- the operator-signal channel's host-reachable
caller (Plan 00417) -- was refused on the exact deployment it exists for.
This module needs no venv and no third-party package: only the standard
library, at Python 3.10+ (see ``tests/unit/daemon/test_signal_standalone.py``
``TestSyntaxFloor`` -- ``daemon/paths.py``'s bare ``X | Y`` annotations are
the binding constraint, not anything in this file).

``operator_signal.py`` is itself standard-library-only, but a normal
``from claude_code_hooks_daemon.utils.operator_signal import ...`` executes
``claude_code_hooks_daemon/__init__.py`` first (Python always initialises a
dotted import's parent packages), which imports pydantic. This module loads
``operator_signal.py`` -- and its own dependency, ``temp_names.py``, and
``daemon/paths.py`` for untracked-dir resolution -- directly by file path
instead, registering each under its real dotted name in ``sys.modules``
BEFORE executing it, so each module's own
``from claude_code_hooks_daemon...`` import statements resolve from that
cache rather than triggering a real package import. Validation, the closed
``kind`` set and the write itself are therefore reused unchanged from
``operator_signal.py`` via ``run_signal_cli`` -- the SAME function
``cmd_signal`` (``daemon/cli.py``) delegates to -- rather than
re-implemented here.

``--project-root`` is REQUIRED, unlike ``cmd_signal``'s optional flag with a
CWD walk-up fallback (``daemon.cli.get_project_path``): that walk-up
validates the installation through the full config-loading path, which
needs the very venv this module exists to avoid. A host-side caller with no
venv to run a session in also has no current-Claude-Code-project CWD to
walk up from, so the omission that would be a fallback there is a caller
error here. Untracked-dir resolution itself needs no git identity (only the
project root and whether ``src/claude_code_hooks_daemon`` exists at it), so
this module performs none of ``ProjectContext.initialize``'s git validation.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type-checking only -- never executed (see the module docstring for why
    # a REAL import of these here would defeat this module's whole point).
    # mypy/pyright run inside the fully-provisioned dev venv, so resolving
    # this costs nothing at check time; it gives `operator_signal`/`paths`
    # their real types below instead of the bare `ModuleType` a dynamic
    # load would otherwise leave them with.
    from claude_code_hooks_daemon.daemon import paths as _paths_type
    from claude_code_hooks_daemon.utils import operator_signal as _operator_signal_type

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_UTILS_DIR = _PACKAGE_ROOT / "utils"
_DAEMON_DIR = _PACKAGE_ROOT / "daemon"


def _load_by_file_path(dotted_name: str, file_path: Path) -> ModuleType:
    """Load a single module by file path, registered under its real dotted
    name in ``sys.modules`` -- see the module docstring for why.

    Returns the cached module if this process already loaded it (a second
    call to :func:`main`, or a dependency another loaded module already
    pulled in). Callers must load a module's own dependencies first, so
    that when a dependency's ``from claude_code_hooks_daemon... import ...``
    statement runs, it finds the cache already populated rather than
    falling through to a real package import.
    """
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
    operator_signal = _operator_signal_type
    paths = _paths_type
else:
    # temp_names has no internal dependencies; operator_signal needs it
    # cached first (its own
    # `from claude_code_hooks_daemon.utils.temp_names import ...` resolves
    # from sys.modules, not a real import). paths.py has no internal
    # claude_code_hooks_daemon dependencies of its own.
    _load_by_file_path("claude_code_hooks_daemon.utils.temp_names", _UTILS_DIR / "temp_names.py")
    operator_signal = _load_by_file_path(
        "claude_code_hooks_daemon.utils.operator_signal", _UTILS_DIR / "operator_signal.py"
    )
    paths = _load_by_file_path("claude_code_hooks_daemon.daemon.paths", _DAEMON_DIR / "paths.py")


def _build_parser() -> argparse.ArgumentParser:
    """Mirrors `cmd_signal`'s subparser (``daemon/cli.py``), minus the
    optional ``--project-root`` (required here -- see the module docstring).
    ``choices`` is derived from ``operator_signal.KINDS`` rather than a
    second hardcoded tuple, so the closed set cannot drift between the two
    entry points without a parity test catching it
    (``TestKindChoicesMatchCliPy``).
    """
    parser = argparse.ArgumentParser(
        prog="signal",
        description=(
            "Write an operator-signal file for the ccy supervisor "
            "(reboot/shutdown warnings), without a venv."
        ),
    )
    parser.add_argument("kind", choices=sorted(operator_signal.KINDS), help="Signal kind")
    parser.add_argument(
        "--minutes",
        type=int,
        default=None,
        metavar="N",
        help="Minutes until the reboot/shutdown (required for *-warning kinds only)",
    )
    parser.add_argument(
        "--all-sessions",
        dest="all_sessions",
        action="store_true",
        help="Reach every live session of this project instead of just $CLAUDE_CODE_SESSION_ID",
    )
    parser.add_argument(
        "--project-root",
        dest="project_root",
        type=Path,
        required=True,
        help="Project root (required: this entry point has no venv to walk up the CWD with)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and write the signal(s); see the module docstring."""
    args = _build_parser().parse_args(argv)

    project_root = args.project_root.resolve()
    if not project_root.is_dir():
        print(f"ERROR: Project root does not exist: {project_root}", file=sys.stderr)
        return 1

    untracked_dir = paths.get_untracked_dir(project_root)
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    return operator_signal.run_signal_cli(
        untracked_dir,
        kind=str(args.kind),
        minutes=args.minutes,
        all_sessions=bool(args.all_sessions),
        session_id=session_id,
    )


if __name__ == "__main__":
    sys.exit(main())
