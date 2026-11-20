"""Fresh facts for an apply run's claim re-check (Plan 00627 Task 3.8, DESIGN.md section 5.2).

:class:`~claude_code_hooks_daemon.core.scratch_archive_apply.ApplyFacts` takes
callables; these are the ones the CLI wires. Both fail towards "not safe": an
answer that cannot be known counts as live, or as referenced.

:func:`entry_in_use` deliberately reads no age signal. The sweep's liveness
(``scratch_liveness.entry_liveness``) also treats a recently changed root ctime
as activity; the claim's own rename changes that ctime, so the same signal at
claim time would refuse every claim. Age is judged once, by the classification.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from claude_code_hooks_daemon.core.scratch_archive_claim import CLAIM_PREFIX
from claude_code_hooks_daemon.core.scratch_liveness import BackgroundRecords, ProcessCwdReading
from claude_code_hooks_daemon.core.scratch_references import ReferenceSet
from claude_code_hooks_daemon.utils.path_containment import path_is_relative_to


def entry_in_use(
    name: str,
    *,
    root: Path,
    relative_root: str | None,
    reading: ProcessCwdReading,
    background: BackgroundRecords,
) -> bool:
    """True when a process or a tracked background command may be using entry ``name``.

    ``root`` must be the resolved scratch root (process working directories are
    resolved). Both ``<root>/<name>`` and ``<root>/.sweeping-<name>`` count. An
    unreadable pid, an empty process map or unreadable background records are
    all "live": liveness is then unknown.
    """
    if reading.unreadable or not reading.cwds or background.error:
        return True
    names = (name, f"{CLAIM_PREFIX}{name}")
    paths = tuple(root / each for each in names)
    if any(path_is_relative_to(cwd, path) for cwd in reading.cwds.values() for path in paths):
        return True
    needles = [str(path) for path in paths]
    if relative_root:
        needles.extend(f"{relative_root}/{each}" for each in names)
    return any(needle in command for command in background.commands for needle in needles)


class LazyReferences:
    """``referenced(name)``: the reference set built on first use, once per run.

    True when a tracked file names the entry, when the set is unknown, when the
    name cannot be searched for, or when building the set failed.
    """

    def __init__(self, build: Callable[[], ReferenceSet]) -> None:
        self._build = build
        self._set: ReferenceSet | None = None

    def __call__(self, name: str) -> bool:
        if self._set is None:
            try:
                self._set = self._build()
            except Exception as exc:  # any failure leaves the answer unknown
                self._set = ReferenceSet(unknown=f"reference set could not be built: {exc}")
        found = self._set.for_entry(name)
        return bool(found.unknown or found.sites)


__all__ = ["LazyReferences", "entry_in_use"]
