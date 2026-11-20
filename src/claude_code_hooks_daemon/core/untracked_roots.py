"""Which directory a scratch sweep may judge, and with what TTL (Plan 00627 DESIGN.md section 4.1).

Every sweep root goes through :func:`resolve_sweep_root`. It refuses, before
anything is listed:

- ``untracked/repos``, every reference-repository root and the archive store
  (``untracked/scratch-archive``), whatever ``scratch.untracked_ttl`` says,
  and any path inside one of them;
- the project root, ``untracked/`` itself, and any path that holds the project;
- a directory whose TTL is ``"*"`` (never cleared), which is what an unlisted
  ``untracked/`` directory falls through to by default;
- any root that is not inside THIS project's ``untracked/`` (a tracked
  directory, a test tree, another checkout);
- any root whose path, literal or link-resolved, passes through an
  ``untracked/repos`` or ``untracked/scratch-archive`` of ANY checkout.

A protected path that lies inside an accepted root is skipped as an entry and
named in a note. A root at any depth inside ``untracked/`` takes the TTL of
its first directory there (``untracked/logs/inner`` is ``logs``). Paths are compared both as
given and with links resolved, so a link cannot carry a root past the check.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from claude_code_hooks_daemon.config.models import ScratchConfig
from claude_code_hooks_daemon.utils.path_containment import (
    path_is_relative_to,
    path_relative_to,
)

#: ``untracked/`` directories never swept, whatever the config says.
NEVER_SWEPT: tuple[str, ...] = ("repos", "scratch-archive")

#: The default sweep root's TTL key.
SCRATCH_KEY = "scratch"

_UNTRACKED = "untracked"


@dataclass(frozen=True)
class SweepRoot:
    """A root the sweep may judge, or why it may not."""

    path: Path
    #: Hours; None when the root is refused.
    ttl_hours: int | None
    #: Empty when the root may be swept.
    refusal: str
    #: Entry names that hold a protected path and are never judged.
    skip: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def _forms(path: Path) -> tuple[Path, ...]:
    absolute = Path(path).absolute()
    resolved = absolute.resolve()
    return (absolute,) if resolved == absolute else (absolute, resolved)


def _within(path: Path, container: Path) -> bool:
    return path == container or path_is_relative_to(path, container)


def resolve_sweep_root(
    root: Path,
    *,
    project_root: Path,
    config: ScratchConfig,
    reference_roots: Sequence[str],
) -> SweepRoot:
    """Resolve ``root`` against the never-swept set and its TTL; reads no directory listing."""
    project_forms = _forms(project_root)
    protected: list[Path] = []
    for project in project_forms:
        protected.extend(project / _UNTRACKED / name for name in NEVER_SWEPT)
        protected.extend(project / reference for reference in reference_roots)
    root_forms = _forms(root)

    def refused(reason: str) -> SweepRoot:
        return SweepRoot(Path(root), None, reason)

    for form in root_forms:
        parts = form.parts
        for index in range(len(parts) - 1):
            if parts[index] == _UNTRACKED and parts[index + 1] in NEVER_SWEPT:
                return refused(
                    f"{root} passes through an untracked/{parts[index + 1]} directory: never swept"
                )
        for project in project_forms:
            if form in (project, project / _UNTRACKED):
                return refused(f"{root} is the project or its untracked/ directory: never swept")
            if path_is_relative_to(project, form):
                return refused(f"{root} holds the project: never swept")
        for guarded in protected:
            if _within(form, guarded):
                return refused(f"{root} is or lies inside {guarded}: never swept")

    keys = {
        path_relative_to(form, project / _UNTRACKED).parts[0]
        for form in root_forms
        for project in project_forms
        if path_is_relative_to(form, project / _UNTRACKED)
    }
    if len(keys) > 1:
        return refused(f"{root} names more than one untracked/ directory once links are resolved")
    if not keys or not all(
        any(path_is_relative_to(form, project / _UNTRACKED) for project in project_forms)
        for form in root_forms
    ):
        return refused(f"{root} is not inside this project's untracked/ directory: never swept")
    key = keys.pop()
    ttl = config.ttl_hours_for(key)
    if ttl is None:
        return refused(f'untracked/{key} has the TTL "*": never swept')

    skip: set[str] = set()
    for form in root_forms:
        for guarded in protected:
            if path_is_relative_to(guarded, form):
                skip.add(path_relative_to(guarded, form).parts[0])
    ordered = tuple(sorted(skip))
    notes = tuple(f"entry {name} holds a never-swept path: not judged" for name in ordered)
    return SweepRoot(Path(root), ttl, "", ordered, notes)


__all__ = ["NEVER_SWEPT", "SCRATCH_KEY", "SweepRoot", "resolve_sweep_root"]
