"""Check ``generated-doc-hand-edit`` (EDIT + SWEEP; R10, DESIGN section 2.1).

Deliberately stays EDIT+SWEEP, no STAGED half (Task 3.1e decision). The
DESIGN table lists this check as EDIT/SWEEP only, and that stays correct:
EDIT catches a hand-edit the moment it happens, and SWEEP catches anything
already on disk at the next session start regardless of how it got there
(a script, a merge, content predating this check's rollout). A STAGED-only
gap would be narrow -- content staged via a route other than Write/Edit
within the SAME session a sweep has not run yet -- and freshness is a
session-start concern (regenerate before you start working), not a
per-commit gate concern the way a broken link or a drifted quote is.
Adding STAGED here would flag the commit for something the sweep already
owns, without covering anything EDIT+SWEEP together do not.

R10 — "Generated docs are compliant SSoT; declare them": a doc generated
from code is generation, not duplication, provided it is declared in the
``documentation.qa.generated_docs`` manifest (config: ``glob`` + a
``generator`` command shown in the advisory).

**EDIT half** (block-eligible): a Write/Edit whose target path matches a
manifest glob is a hand-edit of a generated artefact — it will be silently
overwritten the next time the generator runs. This half needs NO corpus at
all: matching a single edited path against a glob is pure string matching
(:func:`fnmatch.fnmatch`), independent of whatever the doc corpus does or
does not contain — so it runs identically whether the corpus is warm,
cold, or was never built (the cold-index rule has nothing to degrade
here, because nothing here ever reads it).

**SWEEP half** (advisory only, per the design critique — a write-time-only
guard cannot see drift introduced by regeneration itself, or a hand-edit
made before this check existed): staleness detection via a narrowly
recognised version marker. This slice recognises exactly ONE marker shape
— the ``> Generated on YYYY-MM-DD (vX.Y.Z) by ...`` header
:mod:`daemon.docs_generator` emits — and compares its embedded version
against :data:`claude_code_hooks_daemon.version.__version__`, the daemon's
own source of truth. A generated doc with NO recognisable marker is
skipped silently: inventing a heuristic for every possible generator's
freshness signal is explicitly out of scope, and a false "stale" advisory
on a doc this check cannot actually read is worse than saying nothing.
Also independent of the corpus: manifest globs are matched directly
against the filesystem (:meth:`pathlib.Path.glob`), not against whatever
the doc corpus happens to have indexed — the manifest's declared scope is
the authority here, not the corpus's audience-tree scope.
"""

import re
from fnmatch import fnmatch
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.docs_qa.policy import GeneratedDocEntry
from claude_code_hooks_daemon.docs_qa.types import (
    CheckContext,
    CheckSpec,
    CheckStage,
    Finding,
    Severity,
)
from claude_code_hooks_daemon.version import __version__ as _DAEMON_VERSION

CHECK_ID: Final[str] = "generated-doc-hand-edit"

# Mirrors the exact header docs_generator.py._render_header() emits:
# "> Generated on {today} (v{__version__}) by `generate-docs`. ...". Kept
# narrow on purpose — this is the ONE marker shape this slice recognises;
# any other generated doc (or a differently-worded header) is skipped
# silently rather than guessed at.
_VERSION_MARKER_RE: Final[re.Pattern[str]] = re.compile(
    r"> Generated on \d{4}-\d{2}-\d{2} \(v(\d+\.\d+\.\d+)\) by"
)


def matched_manifest_entry(
    rel_path: str, generated_docs: tuple[GeneratedDocEntry, ...]
) -> GeneratedDocEntry | None:
    """The first manifest entry whose glob matches ``rel_path``, or ``None``.

    Public: also used by the ``docs-qa --lint`` CLI to widen its scope
    check — a manifest entry may legitimately name a path outside the doc
    corpus's two-tree/satellite scope (the default entry,
    ``.claude/HOOKS-DAEMON.md``, is exactly this case), so lint validity
    cannot rely on :func:`docs_qa.corpus.is_in_scope` alone.
    """
    for entry in generated_docs:
        if fnmatch(rel_path, entry.glob):
            return entry
    return None


def _matches_allowlist(rel_path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch(rel_path, pattern) for pattern in patterns)


def _hand_edit_finding(rel_path: str, entry: GeneratedDocEntry, severity: Severity) -> Finding:
    return Finding(
        check_id=CHECK_ID,
        severity=severity,
        message=(
            f"`{rel_path}` is generated from source; hand-edits will be "
            f"overwritten. Regenerate with: `{entry.generator}`"
        ),
        remediation=(
            f"Do not hand-edit `{rel_path}`. Change its source and regenerate "
            f"with `{entry.generator}` instead."
        ),
        path=rel_path,
    )


def _run_edit(context: CheckContext) -> list[Finding]:
    if context.file_path is None or context.file_content is None:
        return []
    rel_path = str(context.file_path.relative_to(context.project_root))
    entry = matched_manifest_entry(rel_path, context.policy.qa.generated_docs)
    if entry is None:
        return []
    grandfathered = _matches_allowlist(rel_path, context.policy.qa.grandfather_allowlist)
    severity = Severity.ADVISE if grandfathered else Severity.BLOCK
    return [_hand_edit_finding(rel_path, entry, severity)]


def _extract_marker_version(text: str) -> str | None:
    """The version embedded in the recognised header marker, or ``None``."""
    match = _VERSION_MARKER_RE.search(text)
    return match.group(1) if match else None


def _staleness_finding(rel_path: str, marker_version: str, entry: GeneratedDocEntry) -> Finding:
    return Finding(
        check_id=CHECK_ID,
        severity=Severity.ADVISE,
        message=(
            f"`{rel_path}` looks stale: it embeds v{marker_version} but the "
            f"daemon is v{_DAEMON_VERSION}."
        ),
        remediation=f"Regenerate `{rel_path}` with: `{entry.generator}`",
        path=rel_path,
    )


def _iter_manifest_matches(
    project_root: Path, generated_docs: tuple[GeneratedDocEntry, ...]
) -> list[tuple[Path, GeneratedDocEntry]]:
    """Every on-disk file matching a manifest glob, resolved directly against
    the filesystem — not the doc corpus (see module docstring)."""
    matches: list[tuple[Path, GeneratedDocEntry]] = []
    for entry in generated_docs:
        matches.extend(
            (path, entry) for path in sorted(project_root.glob(entry.glob)) if path.is_file()
        )
    return matches


def _run_sweep(context: CheckContext) -> list[Finding]:
    findings: list[Finding] = []
    for abs_path, entry in _iter_manifest_matches(
        context.project_root, context.policy.qa.generated_docs
    ):
        marker_version = _extract_marker_version(abs_path.read_text(encoding="utf-8"))
        if marker_version is None or marker_version == _DAEMON_VERSION:
            continue
        rel_path = str(abs_path.relative_to(context.project_root))
        findings.append(_staleness_finding(rel_path, marker_version, entry))
    return findings


CHECKS: Final[tuple[CheckSpec, CheckSpec]] = (
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.EDIT, run=_run_edit),
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.SWEEP, run=_run_sweep),
)
