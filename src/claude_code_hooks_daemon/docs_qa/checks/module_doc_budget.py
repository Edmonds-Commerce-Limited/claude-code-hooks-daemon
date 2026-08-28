"""Check module-doc-budget (EDIT + SWEEP; R7d, RULESET section 2 / S6).

R7d -- a sub-folder CLAUDE.md is either a pure routing table or a
REGISTERED module-local canonical home. This check enforces the budget
half of that contract: an UNREGISTERED module doc gets a routing/guard
budget (UNREGISTERED_MODULE_DOC_LINE_BUDGET, ~40 lines, advisory
only -- RULESET S6: both guards and the exemplar routing tables fit); a
REGISTERED module doc (documentation.qa.registered_module_docs) gets
plan-doc-size-style tiers at generous thresholds -- this check literally
reuses plan_qa's own block-tier line-count constant rather than
inventing a separate number, since RULESET S6 measured a 705-line
auto-loaded doc as needing to fit under generous thresholds without
blocking; the plan-doc block tier (900 lines) does exactly that.

Simplified to TWO tiers, not three: this slice implements an advisory
threshold and a (grow-only, worse-only) block threshold, folding
plan_qa's middle "escalated warning" tier into the advisory wording rather
than adding a third severity value docs_qa's Severity enum does not have.

Scope: any CLAUDE.md that is NOT at the repo root and NOT at
{trees.agent}/CLAUDE.md (both are the canonical roots, not "module"
docs). ssot-quote block bodies are excluded from the line count
(DESIGN section 2.4's budget note) via a simple marker-to-marker strip --
not fence-aware, a deliberate simplification for a size count rather than
a verification.

Worse-only semantics for the registered-doc block tier mirror
rules-file-shape exactly: growing while already over the block tier is
BLOCK-eligible; unchanged is ADVISE; shrinking is silent. A path matching
``grandfather_allowlist`` is held to ADVISE-only regardless (R12).
"""

import re
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.constants.paths import ProjectPath
from claude_code_hooks_daemon.docs_qa.corpus import (
    is_module_doc_path,
    is_vendored_daemon_install_path,
)
from claude_code_hooks_daemon.docs_qa.types import (
    CheckContext,
    CheckSpec,
    CheckStage,
    Finding,
    Severity,
)
from claude_code_hooks_daemon.plan_qa.types import DEFAULT_PLAN_DOC_BLOCK_LINES

CHECK_ID: Final[str] = "module-doc-budget"

_CLAUDE_MD_FILENAME: Final[str] = "CLAUDE.md"

# Unregistered module doc: routing/guard budget, not a canonical home.
UNREGISTERED_MODULE_DOC_LINE_BUDGET: Final[int] = 40

# Registered module doc: reuse plan_qa's own block-tier line-count constant
# rather than inventing a separate number for the same "generous ceiling"
# concept.
_REGISTERED_BLOCK_LINES: Final[int] = DEFAULT_PLAN_DOC_BLOCK_LINES

# Marker-to-marker strip of ssot-quote block bodies (DESIGN section 2.4's
# budget note) -- not fence-aware, a deliberate simplification for a size
# count rather than a verification.
_QUOTE_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r"<!-- ssot-quote: [^\n]+ -->.+?<!-- /ssot-quote -->",
    re.DOTALL,
)

# Directories heavy enough that a SWEEP walk should never descend into them.
# "untracked" already covers ProjectPath.WORKTREES_DIR
# ("untracked/worktrees"); "worktrees" (the shared basename of BOTH worktree
# roots -- ProjectPath.CLAUDE_WORKTREES_DIR is ".claude/worktrees", whose
# ".claude" segment is not otherwise excluded) added for Task 3.3 T2 -- this
# check does its OWN rglob walk rather than using docs_qa.corpus, so the
# corpus's worktree exclusion (corpus._is_worktree_path) does not reach it.
# The same is true of a vendored daemon install (Task 3.6): its own basename
# is not distinctive enough for this set (it also names this daemon's OWN
# tracked ``skills/hooks-daemon/`` source in self-install mode), so it is
# excluded by full path prefix via corpus.is_vendored_daemon_install_path
# instead, applied separately below.
_EXCLUDED_DIR_NAMES: Final[frozenset[str]] = frozenset(
    {
        "node_modules",
        "vendor",
        "untracked",
        ".git",
        Path(ProjectPath.CLAUDE_WORKTREES_DIR).name,
    }
)


def _matches_allowlist(rel_path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch(rel_path, pattern) for pattern in patterns)


def _strip_quote_blocks(content: str) -> str:
    return _QUOTE_BLOCK_RE.sub("", content)


def _line_count(content: str) -> int:
    return len(_strip_quote_blocks(content).splitlines())


@dataclass(frozen=True)
class _Tier:
    """One threshold band. ``_tiers_for`` orders these highest-first."""

    name: str
    max_lines: int
    severity: Severity


def _tiers_for(registered: bool) -> tuple[_Tier, ...]:
    """Registered docs get a block tier ABOVE the shared advisory tier;
    unregistered docs get the advisory tier only (never block-eligible)."""
    advisory = _Tier("advisory", UNREGISTERED_MODULE_DOC_LINE_BUDGET, Severity.ADVISE)
    if not registered:
        return (advisory,)
    return (_Tier("block", _REGISTERED_BLOCK_LINES, Severity.BLOCK), advisory)


def _finding(rel_path: str, line_count: int, tier: _Tier, severity: Severity) -> Finding:
    if tier.name == "block":
        message = (
            f"`{rel_path}` is {line_count} lines, over the registered module "
            f"doc block tier of {tier.max_lines} lines."
        )
        remediation = (
            f"Trim `{rel_path}` back under {tier.max_lines} lines, or extract "
            "durable detail into a linked supporting document."
        )
    else:
        message = (
            f"`{rel_path}` is {line_count} lines, over the module doc "
            f"advisory budget of {tier.max_lines} lines (R7d)."
        )
        remediation = (
            f"Keep `{rel_path}` as a routing table/guard summary under "
            f"{tier.max_lines} lines, or register it as a canonical "
            "module-local home via `documentation.qa.registered_module_docs` "
            "to get the larger block-tier budget instead."
        )
    return Finding(
        check_id=CHECK_ID,
        severity=severity,
        message=message,
        remediation=remediation,
        path=rel_path,
    )


def _finding_for(
    rel_path: str,
    content: str,
    content_before: str | None,
    registered: bool,
    grandfathered: bool = False,
) -> Finding | None:
    """plan-doc-size's own tiering, mirrored: shrinking is silent, a
    non-growing edit never escalates past ADVISE, and the highest breached
    tier otherwise sets the severity (worse-only, like rules-file-shape).
    A path matching ``grandfather_allowlist`` is held to ADVISE-only (R12),
    the same downgrade every other block-eligible check applies."""
    line_count = _line_count(content)
    if content_before is not None:
        old_line_count = _line_count(content_before)
        if line_count < old_line_count:
            return None
        grows = line_count > old_line_count
    else:
        grows = True

    breached = next((tier for tier in _tiers_for(registered) if line_count > tier.max_lines), None)
    if breached is None:
        return None
    severity = breached.severity if (grows and not grandfathered) else Severity.ADVISE
    return _finding(rel_path, line_count, breached, severity)


def _run_edit(context: CheckContext) -> list[Finding]:
    if context.file_path is None or context.file_content is None:
        return []
    rel_path = str(context.file_path.relative_to(context.project_root))
    if not is_module_doc_path(rel_path, context.policy.trees.agent):
        return []
    registered = rel_path in context.policy.qa.registered_module_docs
    grandfathered = _matches_allowlist(rel_path, context.policy.qa.grandfather_allowlist)
    finding = _finding_for(
        rel_path, context.file_content, context.file_content_before, registered, grandfathered
    )
    return [finding] if finding is not None else []


def _iter_module_doc_paths(project_root: Path, agent_tree: str) -> list[str]:
    """Every module-scoped CLAUDE.md on disk (``rglob`` always yields paths
    under ``project_root``, so ``relative_to`` here cannot fail)."""
    matches: list[str] = []
    for path in project_root.rglob(_CLAUDE_MD_FILENAME):
        rel_path = str(path.relative_to(project_root))
        parts = rel_path.split("/")
        if any(part in _EXCLUDED_DIR_NAMES for part in parts[:-1]):
            continue
        if is_vendored_daemon_install_path(tuple(parts[:-1])):
            continue
        if is_module_doc_path(rel_path, agent_tree):
            matches.append(rel_path)
    return sorted(matches)


def _run_sweep(context: CheckContext) -> list[Finding]:
    findings: list[Finding] = []
    for rel_path in _iter_module_doc_paths(context.project_root, context.policy.trees.agent):
        abs_path = context.project_root / rel_path
        if not abs_path.is_file():
            continue
        content = abs_path.read_text(encoding="utf-8")
        registered = rel_path in context.policy.qa.registered_module_docs
        finding = _finding_for(rel_path, content, None, registered)
        if finding is not None:
            # SWEEP has no before/after to judge worse-only against -- a
            # BLOCK-eligible finding at EDIT is reported as ADVISE here.
            findings.append(finding if finding.severity is Severity.ADVISE else _as_advise(finding))
    return findings


def _as_advise(finding: Finding) -> Finding:
    return Finding(
        check_id=finding.check_id,
        severity=Severity.ADVISE,
        message=finding.message,
        remediation=finding.remediation,
        path=finding.path,
    )


CHECKS: Final[tuple[CheckSpec, CheckSpec]] = (
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.EDIT, run=_run_edit),
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.SWEEP, run=_run_sweep),
)
