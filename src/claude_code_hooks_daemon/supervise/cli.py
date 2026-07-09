"""CLI entry point for claude-supervise (v0: transparent dry-run passthrough).

Invoke this module directly with Python's `-m` flag, passing supervisor flags
before `--` and the wrapped command's own argv after it. See `_USAGE` below
for the exact invocation form.
"""

# Example invocations (kept as comments, not docstring text, so this file's
# own usage instructions are never mistaken for agent-facing daemon-CLI
# guidance by the skill-reference QA check):
#   python -m claude_code_hooks_daemon.supervise -- <child argv...>
#   python -m claude_code_hooks_daemon.supervise --arm --log PATH -- claude --dangerously-skip-permissions

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.supervise.decision_log import DecisionLog
from claude_code_hooks_daemon.supervise.supervisor import supervise

_USAGE = (
    "Usage: python -m claude_code_hooks_daemon.supervise "
    "[--dry-run | --arm] [--log PATH] -- <child argv...>\n"
)


def _split_child_argv(argv: list[str]) -> list[str] | None:
    """Return everything after the first `--` separator, or None if absent/empty."""
    if "--" not in argv:
        return None
    child = argv[argv.index("--") + 1 :]
    return child if child else None


def _parse_supervisor_flags(argv: list[str]) -> argparse.Namespace:
    """Parse only the flags that appear before `--` (argparse never sees the child argv)."""
    supervisor_argv = argv[: argv.index("--")] if "--" in argv else argv

    parser = argparse.ArgumentParser(
        prog="claude-supervise",
        description="Transparent PTY supervisor for wrapping `claude` (v0).",
        add_help=False,
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Log-only observation mode (default). No behavioural effect in v0.",
    )
    mode_group.add_argument(
        "--arm",
        dest="dry_run",
        action="store_false",
        help="Documented no-op in v0 (injection does not exist yet); reserved for v1.",
    )
    parser.add_argument(
        "--log",
        dest="log_path",
        type=Path,
        default=None,
        help="Decision log file path (default: daemon untracked dir).",
    )
    return parser.parse_args(supervisor_argv)


def _resolve_decision_log(explicit_path: Path | None) -> DecisionLog:
    """Build the DecisionLog, initializing ProjectContext if needed for the default path."""
    if explicit_path is not None:
        return DecisionLog(explicit_path)

    if not ProjectContext._initialized:
        config_path = Path.cwd() / ".claude" / "hooks-daemon.yaml"
        ProjectContext.initialize(config_path)
    return DecisionLog()


def main(argv: list[str] | None = None) -> int:
    """Entry point: parse args, run the PTY supervisor, return the exit code.

    Args:
        argv: Command-line arguments (excluding program name). Defaults to
            `sys.argv[1:]` when None.

    Returns:
        2 if no child argv is supplied after `--`; otherwise the supervised
        child's exit code.
    """
    argv = argv if argv is not None else sys.argv[1:]

    child_argv = _split_child_argv(argv)
    if child_argv is None:
        sys.stderr.write(_USAGE)
        return 2

    flags = _parse_supervisor_flags(argv)
    log = _resolve_decision_log(flags.log_path)

    return supervise(child_argv, dry_run=flags.dry_run, log=log)
