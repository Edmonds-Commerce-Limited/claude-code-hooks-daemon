"""Check ``source-tree-markdown`` (SWEEP only; Plan 00288, DESIGN §4b).

Owner direction: markdown that IS present in a source/test directory must
follow the documentation-SSoT pattern — a collocated ``CLAUDE.md`` is
allowed (a directly relevant module doc, policed separately by
``module-doc-budget``), everything else should be promoted into the
configured agent/human tree, converted into a routing ``CLAUDE.md``, or
deleted.

**Deliberately SWEEP-only — no EDIT stage.** ``markdown_organization``
(PreToolUse, blocking) already gates "may a NEW ``.md`` be written here?"
at write time; adding an EDIT stage here would re-judge the SAME write and
double-report on every single markdown write under a source/test dir. The
DESIGN §4b division table is explicit that the two checks answer different
questions on different surfaces: EDIT belongs to ``markdown_organization``
alone, and this check closes the complementary gap — markdown that reached
disk by a route ``markdown_organization`` never saw (predates the rule,
arrived via ``git mv``/merge, or was written before this check shipped;
Core Standard 15's corollary). A write-time rule cannot see what predates
it; a sweep can.

**Scope comes from the ``ProjectLayout`` facade** (``context.layout``):
a ``.md`` file is in scope when :meth:`ProjectLayout.is_source_path` or
:meth:`ProjectLayout.is_test_path` is true for its project-relative path.
When ``context.layout`` is ``None`` (a calling surface built before the
facade existed) or when *both* lists resolve empty, the check is silent —
there is nothing declared to scope it to. Note the documented asymmetry
this inherits from the facade (see its own module docstring): with
zero-config composition, ``test_dirs`` already has cross-language
built-ins (:data:`~strategies.tdd.common.COMMON_TEST_DIRECTORIES`) while
``source_dirs`` has none until a project declares one (or Task 4.4/C6
wires per-language inference in as a fallback) — so a project with no
``layout:`` block declared may still see TEST-dir findings today while
SOURCE-dir findings stay dormant until ``source_dirs`` is populated. This
is a fact about the facade's current composition, not a bug in this check.

**Allowed in place, never flagged**:

- ``CLAUDE.md`` — shape is ``module-doc-budget``'s job, not this check's.
- ``README.md`` — the conventional package/module entry point (D4);
  flagging every ``README.md`` under ``src/`` would be pure noise.
- A path matching a ``documentation.qa.generated_docs`` manifest glob
  (R10) — generated, not hand-authored duplication.
- Test FIXTURE markdown (``tests/fixtures/``, ``tests/assets/``,
  ``__fixtures__/`` — the same conventions
  ``error_hiding_blocker``/``security_antipattern`` already use) — test
  data, not documentation.
- Vendored/worktree/daemon-install paths — the SAME corpus exclusion
  primitives ``module-doc-budget`` already relies on
  (:func:`~docs_qa.corpus.is_vendored_daemon_install_path`) are reused
  here rather than re-derived — confirmed scope, not reinvented. The
  vendored-directory NAMES come from ``DocumentationPolicy.vendor_dirs``
  (Plan 00331), which is the canonical set plus whatever the project
  declared in ``layout.vendor_dirs`` — not the constant directly, or the
  declaration could never reach this walk.

**Severity is always ADVISE** (R13: deterministic sweep-only checks ship
advisory; there is no before/after here for a worse-only BLOCK judgement).
``documentation.qa.grandfather_allowlist`` fully suppresses a matching
finding — the same treatment ``duplicate-block`` gives an always-advisory
check, since there is no severity left to downgrade.
"""

import os
from fnmatch import fnmatch
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.constants.paths import ProjectPath
from claude_code_hooks_daemon.docs_qa.checks.generated_doc_hand_edit import (
    matched_manifest_entry,
)
from claude_code_hooks_daemon.docs_qa.corpus import (
    COMMON_VENDORED_BUILD_DIR_NAMES,
    is_vendored_daemon_install_path,
    matches_scope_exclude,
)
from claude_code_hooks_daemon.docs_qa.types import (
    CheckContext,
    CheckSpec,
    CheckStage,
    Finding,
    Severity,
)

CHECK_ID: Final[str] = "source-tree-markdown"

_MARKDOWN_SUFFIX: Final[str] = ".md"
_CLAUDE_MD_FILENAME: Final[str] = "CLAUDE.md"
_README_FILENAME: Final[str] = "README.md"

# Directories heavy enough (or otherwise out of scope) that a SWEEP walk
# should never descend into them. Mirrors module_doc_budget's own walk
# exclusion set exactly -- this check does its OWN rglob-equivalent walk
# rather than the doc corpus (source/test-dir markdown is deliberately
# OUTSIDE docs_qa.corpus's audience-tree scope), so the exclusion set has
# to be re-applied here, not just its outcome.
#
# These are this check's OWN basenames only, WITHOUT the vendored/build
# set: that half is configurable (``layout.vendor_dirs``), so unioning it
# in here would freeze the prune to the BUILT-IN names and make a project's
# declaration inert (Plan 00331). It is passed to the walk instead.
_OWN_EXCLUDED_DIR_NAMES: Final[frozenset[str]] = frozenset(
    {"untracked", ".git", Path(ProjectPath.CLAUDE_WORKTREES_DIR).name}
)

# Test-fixture directory conventions, mirrored from
# handlers.pre_tool_use.error_hiding_blocker's ``_DEFAULT_EXCLUDE_GLOBS`` --
# no shared constant exists yet for this cross-handler convention (recorded
# as a possible future DRY fix, not done here: out of scope for Plan 00288
# Phase 5, and the two call sites classify different things -- a Bash/Write
# command string there, a swept relative path here).
_FIXTURE_DIR_PAIRS: Final[tuple[tuple[str, str], ...]] = (
    ("tests", "fixtures"),
    ("tests", "assets"),
)
_FIXTURE_DIR_SINGLE_NAMES: Final[frozenset[str]] = frozenset({"__fixtures__"})


def _path_parts(rel_path: str) -> tuple[str, ...]:
    return tuple(part for part in rel_path.split("/") if part)


def _is_fixture_path(rel_path: str) -> bool:
    """True when ``rel_path`` sits under a recognised fixture-dir convention."""
    parts = _path_parts(rel_path)
    if any(part in _FIXTURE_DIR_SINGLE_NAMES for part in parts):
        return True
    return any(
        parts[index] == outer and parts[index + 1] == inner
        for outer, inner in _FIXTURE_DIR_PAIRS
        for index in range(len(parts) - 1)
    )


def _matches_allowlist(rel_path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch(rel_path, pattern) for pattern in patterns)


def _iter_markdown_paths(
    project_root: Path, *, vendor_dirs: frozenset[str] = COMMON_VENDORED_BUILD_DIR_NAMES
) -> list[str]:
    """Every ``.md`` path under ``project_root``, minus the walk exclusions.

    Pruned ``os.walk`` (not ``Path.rglob``, which cannot skip a matched
    directory) -- the same idiom ``module_doc_budget`` uses, for the same
    reason: never physically descend a huge vendored/worktree tree only to
    discard the results a moment later.

    ``vendor_dirs`` is the project's EFFECTIVE vendored set, threaded from
    ``DocumentationPolicy`` rather than read from the canonical constant, so
    a declared ``layout.vendor_dirs`` prunes here too (Plan 00331).
    """
    excluded_dir_names = _OWN_EXCLUDED_DIR_NAMES | vendor_dirs
    matches: list[str] = []
    for dirpath, dirnames, filenames in os.walk(project_root):
        rel_dir_parts = Path(dirpath).relative_to(project_root).parts
        dirnames[:] = [
            name
            for name in dirnames
            if name not in excluded_dir_names
            and not is_vendored_daemon_install_path((*rel_dir_parts, name))
        ]
        for filename in filenames:
            if filename.endswith(_MARKDOWN_SUFFIX):
                matches.append("/".join((*rel_dir_parts, filename)))
    return sorted(matches)


def _finding(rel_path: str) -> Finding:
    return Finding(
        check_id=CHECK_ID,
        severity=Severity.ADVISE,
        message=(
            f"`{rel_path}` is markdown under a source/test directory that does not "
            "follow the documentation-SSoT pattern (a collocated `CLAUDE.md` or "
            "`README.md` is the only allowed in-place form)."
        ),
        remediation=(
            f"For `{rel_path}`: promote its content into the configured agent or "
            "human documentation tree and leave a pointer in its place, convert it "
            "into a routing `CLAUDE.md` for this module, or delete it if the "
            "content is obsolete."
        ),
        path=rel_path,
    )


def _run_sweep(context: CheckContext) -> list[Finding]:
    layout = context.layout
    if layout is None or not (layout.source_dirs or layout.test_dirs):
        return []

    findings: list[Finding] = []
    for rel_path in _iter_markdown_paths(
        context.project_root, vendor_dirs=context.policy.vendor_dirs
    ):
        basename = rel_path.rsplit("/", 1)[-1]
        if basename in (_CLAUDE_MD_FILENAME, _README_FILENAME):
            continue
        if not (layout.is_source_path(rel_path) or layout.is_test_path(rel_path)):
            continue
        if _is_fixture_path(rel_path):
            continue
        if matched_manifest_entry(rel_path, context.policy.qa.generated_docs) is not None:
            continue
        if matches_scope_exclude(rel_path, context.policy.qa.scope_exclude_globs):
            continue
        if _matches_allowlist(rel_path, context.policy.qa.grandfather_allowlist):
            continue
        findings.append(_finding(rel_path))
    return findings


CHECKS: Final[tuple[CheckSpec, ...]] = (
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.SWEEP, run=_run_sweep),
)
