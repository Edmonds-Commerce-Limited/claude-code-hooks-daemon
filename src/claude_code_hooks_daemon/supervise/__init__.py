"""claude-supervise: a standalone PTY supervisor for wrapping `claude`.

v0 is a transparent, dry-run PTY passthrough: it spawns the wrapped process
on a pseudo-terminal, forwards stdin/stdout/window-resize faithfully, and
observes input activity -- but performs NO keystroke injection. Injection and
the state machine that decides when to inject are out of scope for v0 (v1).

This package is standalone: it does not require the hooks daemon to be
running and does not import daemon runtime/server code. It uses only the
standard library for the PTY supervision loop; `ProjectContext` is used
solely to resolve a sensible default decision-log directory.
"""

from claude_code_hooks_daemon.supervise.cli import main
from claude_code_hooks_daemon.supervise.supervisor import InputActivity, supervise

__all__ = ["InputActivity", "main", "supervise"]
