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

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.docs_qa.corpus import (
    COMMON_VENDORED_BUILD_DIR_NAMES,
    dir_matches_scope_exclude,
    is_module_doc_path,
    iter_markdown_paths,
    matches_scope_exclude,
)
from claude_code_hooks_daemon.docs_qa.types import (
    CheckContext,
    CheckSpec,
    CheckStage,
    Finding,
    Severity,
)
from claude_code_hooks_daemon.plan_qa.types import (
    DEFAULT_PLAN_DOC_ADVISORY_LINES,
    DEFAULT_PLAN_DOC_BLOCK_LINES,
)
from claude_code_hooks_daemon.utils.vendor_paths import (
    VendorScope,
    is_vendored_path_in_scopes,
)

logger = logging.getLogger(__name__)

CHECK_ID: Final[str] = "module-doc-budget"

_CLAUDE_MD_FILENAME: Final[str] = "CLAUDE.md"

# Unregistered module doc: routing/guard budget, not a canonical home.
UNREGISTERED_MODULE_DOC_LINE_BUDGET: Final[int] = 40

# Registered module doc: reuse plan_qa's own block-tier line-count constant
# rather than inventing a separate number for the same "generous ceiling"
# concept.
_REGISTERED_BLOCK_LINES: Final[int] = DEFAULT_PLAN_DOC_BLOCK_LINES

# Registered module doc's ADVISORY threshold: plan_qa's own advisory-tier
# line-count constant, NOT the unregistered 40-line routing/guard budget. A
# registered doc is a canonical home (R7d), not a routing table, so it must
# not be measured against the routing-table budget at all -- reusing that
# constant here was the bug this pair of tiers exists to fix (a registered
# doc between 40 and 350 lines was wrongly reported at the unregistered
# tier, with an "or register it" remediation that made no sense for a doc
# that was already registered).
_REGISTERED_ADVISORY_LINES: Final[int] = DEFAULT_PLAN_DOC_ADVISORY_LINES

# Marker-to-marker strip of ssot-quote block bodies (DESIGN section 2.4's
# budget note) -- not fence-aware, a deliberate simplification for a size
# count rather than a verification.
_QUOTE_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r"<!-- ssot-quote: [^\n]+ -->.+?<!-- /ssot-quote -->",
    re.DOTALL,
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
    """Registered docs get their OWN (larger) advisory tier plus a block
    tier above it; unregistered docs get the routing-table advisory tier
    only (never block-eligible). A registered doc is a canonical home, not
    a routing table (R7d) -- it must never be measured against the
    unregistered budget."""
    if not registered:
        return (
            _Tier("advisory-unregistered", UNREGISTERED_MODULE_DOC_LINE_BUDGET, Severity.ADVISE),
        )
    return (
        _Tier("block", _REGISTERED_BLOCK_LINES, Severity.BLOCK),
        _Tier("advisory-registered", _REGISTERED_ADVISORY_LINES, Severity.ADVISE),
    )


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
    elif tier.name == "advisory-registered":
        message = (
            f"`{rel_path}` is {line_count} lines, over the registered module "
            f"doc advisory tier of {tier.max_lines} lines."
        )
        remediation = (
            f"Consider trimming `{rel_path}` back under {tier.max_lines} "
            "lines, or extract durable detail into a linked supporting "
            "document. It is already registered as a canonical module-local "
            f"home, so it has until {_REGISTERED_BLOCK_LINES} lines before "
            "this escalates to a block-eligible finding."
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
    # The EDIT arm had no exclusion test at all, so a project that had
    # declared a tree out of scope was still judged when editing inside it.
    if matches_scope_exclude(rel_path, tuple(context.policy.qa.scope_exclude_globs)):
        return []
    # The SWEEP arm gets this from its prune; the EDIT arm walks nothing, so
    # it has to test the path's own segments (Plan 00331). The doc's own
    # basename is excluded from the test -- `vendor_dirs` names DIRECTORIES,
    # and the last segment here is always `CLAUDE.md`.
    if is_vendored_path_in_scopes(
        "/".join(Path(rel_path).parts[:-1]), context.policy.vendor_scopes
    ):
        return []
    registered = rel_path in context.policy.qa.registered_module_docs
    grandfathered = _matches_allowlist(rel_path, context.policy.qa.grandfather_allowlist)
    finding = _finding_for(
        rel_path, context.file_content, context.file_content_before, registered, grandfathered
    )
    return [finding] if finding is not None else []


def _filter_module_doc_paths(
    markdown_paths: Iterable[str],
    agent_tree: str,
    scope_exclude_globs: tuple[str, ...],
    vendor_scopes: tuple[VendorScope, ...],
) -> list[str]:
    """Narrow a raw ``.md``-path listing down to in-scope module docs.

    The post-filter half of what ``_iter_module_doc_paths`` used to do in
    one pass -- split out so :func:`_run_sweep` can apply it to an
    ALREADY-WALKED ``CheckContext.markdown_paths`` too, rather than walking
    the tree a second time (Plan 00295 Task 3.3).
    """
    matches: list[str] = []
    for rel_path in markdown_paths:
        if matches_scope_exclude(rel_path, scope_exclude_globs):
            continue
        # Descending is not including: a doc reached only because its parent
        # had to be walked for a vendor exception is still vendored unless
        # it IS the exception.
        if is_vendored_path_in_scopes(rel_path, vendor_scopes):
            continue
        if is_module_doc_path(rel_path, agent_tree):
            matches.append(rel_path)
    return sorted(matches)


def _iter_module_doc_paths(
    project_root: Path,
    agent_tree: str,
    scope_exclude_globs: tuple[str, ...] = (),
    *,
    vendor_scopes: tuple[VendorScope, ...] = (
        VendorScope(root="", vendor_dirs=COMMON_VENDORED_BUILD_DIR_NAMES),
    ),
) -> list[str]:
    """Every module-scoped CLAUDE.md on disk.

    A thin wrapper around the shared :func:`docs_qa.corpus.iter_markdown_paths`
    walk (Plan 00295 Task 3.3) plus :func:`_filter_module_doc_paths` --
    kept as its own function for callers (direct tests, and
    :func:`_run_sweep`'s fallback when no pre-built ``markdown_paths`` is
    available) that need the walk run fresh rather than shared.

    ``scope_exclude_globs`` is the project's configured exclusion (Plan
    00289), applied here BECAUSE this check walks the tree itself instead of
    reading ``docs_qa.corpus`` -- so it does not inherit the corpus's own
    ``_is_excluded``. Omitting it was a defect: a project that vendored a
    dependency carrying its own CLAUDE.md (an ansible-galaxy role, in the
    report) got a permanent sweep advisory that the one documented
    suppression could not silence. ``corpus.OWN_EXCLUDED_DIR_NAMES`` could not
    stand in for it either -- those are well-known BASENAMES, and a vendored
    path the project chose is not guessable. It reaches the shared walk as
    its ``also_prune`` predicate (via :func:`dir_matches_scope_exclude`),
    which is the ONLY thing this walk needs beyond the shared prune rules.

    ``vendor_dirs`` is the project's EFFECTIVE vendored-directory set
    (``ProjectLayout.vendor_dirs``, reaching here via
    ``DocumentationPolicy``). It is a parameter rather than a module
    constant because it is configurable: folding it into a module-scope
    frozenset froze the prune to the BUILT-IN names, which is what left a
    declared ``layout.vendor_dirs`` inert here (Plan 00331).
    """

    def scope_exclusion(rel_parts: tuple[str, ...]) -> bool:
        return dir_matches_scope_exclude(rel_parts, scope_exclude_globs)

    markdown_paths = iter_markdown_paths(
        project_root, vendor_scopes=vendor_scopes, also_prune=scope_exclusion
    )
    return _filter_module_doc_paths(markdown_paths, agent_tree, scope_exclude_globs, vendor_scopes)


def _run_sweep(context: CheckContext) -> list[Finding]:
    findings: list[Finding] = []
    agent_tree = context.policy.trees.agent
    scope_exclude_globs = tuple(context.policy.qa.scope_exclude_globs)
    vendor_scopes = context.policy.vendor_scopes
    # A sweep built via docs_qa.context.sweep_context() already carries the
    # ONE shared walk (Plan 00295 Task 3.3); walking fresh here is only a
    # fallback for a CheckContext built some other way.
    rel_paths = (
        _filter_module_doc_paths(
            context.markdown_paths, agent_tree, scope_exclude_globs, vendor_scopes
        )
        if context.markdown_paths is not None
        else _iter_module_doc_paths(
            context.project_root, agent_tree, scope_exclude_globs, vendor_scopes=vendor_scopes
        )
    )
    for rel_path in rel_paths:
        abs_path = context.project_root / rel_path
        if not abs_path.is_file():
            continue
        try:
            content = abs_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            # An unreadable or undecodable file must not abort the whole
            # SessionStart sweep (Plan 00287 N5) -- skip it, matching the
            # corpus's own UnicodeDecodeError handling.
            logger.debug("module-doc-budget: skipping unreadable %s: %s", rel_path, exc)
            continue
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
