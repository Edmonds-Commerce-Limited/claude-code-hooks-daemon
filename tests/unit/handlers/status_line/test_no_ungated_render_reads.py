"""Guard: no status-line module reads a file on the render path ungated.

Plan 00238 Task 3.2. Four handlers had independently grown the same shape — a
small file read and parsed on EVERY render, forever, for a value that changes
daily at most. Measured at ~9,000-12,500 avoidable file operations an hour.

Fixing the four instances by hand is exactly the failure DBF exists to prevent:
nothing would stop a fifth appearing, and nothing did stop the first four. The
cost is invisible at every surface a human looks at — the status line renders
correctly, no error is logged, and a `stat`-per-render versus a
`read`-per-render is indistinguishable without measuring.

So the rule is enforced here rather than remembered: a module in this package
may not read a file directly. It routes through ``MtimeCachedFile`` (which
turns the read into one ``stat()``), or it appears below with a reason.

The allowlist is deliberately awkward to extend. Adding an entry means writing
down why the render must pay a real read every time, which is a claim that
should be hard to make casually.
"""

import ast
from pathlib import Path

import claude_code_hooks_daemon.handlers.status_line as status_line_pkg

_PACKAGE_DIR = Path(status_line_pkg.__file__).parent

# Reading APIs that hit the disk on every call. ``open`` is included because it
# is the obvious way around a rule that only named the Path helpers.
_READ_CALLS = frozenset({"read_text", "read_bytes", "open"})

# The one implementation of the gate — it reads by definition.
_GATE_MODULE = "mtime_cache.py"

# module filename -> why a direct read is correct there.
_ALLOWED_DIRECT_READS: dict[str, str] = {
    "thread_registry.py": (
        "An mtime gate cannot help: this handler WRITES its own heartbeat into "
        "the registry immediately before reading it, so the directory's mtime "
        "has always just moved and every render would miss. The read is also "
        "bounded by the number of live sessions (normally one), not by the "
        "render rate."
    ),
    "git_branch.py": (
        "Reads the top-level `.git` FILE only when one exists (linked-worktree "
        "detection), and the whole probe already sits behind this handler's "
        "render TTL — so it is paid per cache miss, not per render."
    ),
    "supervisor_indicator.py": (
        "Reads the ccy supervisor's transient message file, whose entire "
        "purpose is to be fresh — caching it would defeat the feature — plus "
        "/proc/<pid>/cmdline, which has no meaningful mtime. Its per-render "
        "cost is tracked separately as Plan 00238 Task 2.2, where the fix is "
        "to bound the /proc WALK rather than to cache a read."
    ),
}


def _modules() -> list[Path]:
    return sorted(p for p in _PACKAGE_DIR.glob("*.py") if p.name != "__init__.py")


def _direct_read_lines(module: Path) -> list[int]:
    """Line numbers of direct file-read calls in ``module``."""
    tree = ast.parse(module.read_text(encoding="utf-8"))
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.attr
            if isinstance(func, ast.Attribute)
            else func.id if isinstance(func, ast.Name) else None
        )
        if name in _READ_CALLS:
            lines.append(node.lineno)
    return lines


class TestTheScannerWorks:
    """Guard the guard. A scanner that finds nothing and a scanner that IS
    nothing produce the same green tick, so prove it can see before trusting
    its silence."""

    def test_it_finds_the_reads_inside_the_gate_itself(self) -> None:
        assert _direct_read_lines(_PACKAGE_DIR / _GATE_MODULE)

    def test_it_finds_every_allowlisted_module_still_reading(self) -> None:
        """Doubles as staleness detection: an allowlist entry that no longer
        reads anything is a licence nobody needs, and it should be deleted
        rather than left as cover for a future read."""
        for name in _ALLOWED_DIRECT_READS:
            module = _PACKAGE_DIR / name
            assert module.exists(), f"{name} is allowlisted but no longer exists"
            assert _direct_read_lines(module), (
                f"{name} is allowlisted for direct file reads but no longer "
                "performs any — remove its entry from _ALLOWED_DIRECT_READS."
            )

    def test_it_does_not_flag_a_gated_module(self) -> None:
        """The handlers fixed by this plan must come back clean, or the rule
        below is passing for the wrong reason."""
        for name in ("account_display.py", "upgrade_notifier.py", "startup_cleanup.py"):
            assert not _direct_read_lines(_PACKAGE_DIR / name)


class TestNoUngatedRenderReads:
    def test_every_direct_read_is_gated_or_justified(self) -> None:
        offenders: list[str] = []
        for module in _modules():
            if module.name == _GATE_MODULE or module.name in _ALLOWED_DIRECT_READS:
                continue
            lines = _direct_read_lines(module)
            if lines:
                offenders.append(f"{module.name}:{','.join(str(line) for line in lines)}")

        assert not offenders, (
            "Status-line module(s) read a file directly: "
            + "; ".join(offenders)
            + ". The status line re-renders ~3,100 times an hour for the life "
            "of the daemon, so a per-render read is thousands of file "
            "operations an hour for a value that has almost certainly not "
            "changed. Route it through MtimeCachedFile (mtime_cache.py) — one "
            "stat() replaces the read + parse — or add an entry to "
            "_ALLOWED_DIRECT_READS in this file explaining why the render must "
            "genuinely re-read every time."
        )
