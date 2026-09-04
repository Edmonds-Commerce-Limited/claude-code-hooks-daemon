"""Check ``rules-file-shape`` (EDIT + SWEEP; R7a, DESIGN §refinements).

R7a — "`.claude/rules/*.md` — POINTERS ONLY (firm)": frontmatter, a trigger
statement, the rule in at most two imperative lines, and link(s) to the
agent tree or a registered ``CLAUDE.md``. No fences, no tables, no
numbered procedures, no ``ssot-quote`` blocks, and a body budget of
``RULES_FILE_BODY_LINE_BUDGET`` non-blank, non-frontmatter lines — the
15-line operational form of R7a from
``CLAUDE/Plan/00284-documentation-ssot-enforcement/RULESET-sub-claude-md.md``
§3.

**Scope**: a ``.md`` file directly inside ``.claude/rules/`` — NOT a nested
subdirectory (matching the two real files this contract governs today).

**Worse-only semantics are STRUCTURAL, not just an allowlist** (DESIGN
§refinements): every client with template rules files starts
non-compliant — this repo's own two rules files fail the contract today —
so a naive day-one deny would fire on unrelated typo fixes. Five
independent metrics are each compared would-be vs on-disk (or vs zero for
a brand-new file, so a brand-new violating file is "worse than absent" and
IS deny-eligible): fenced-code-block count, markdown-table count,
qualifying numbered-procedure-run count (3+ consecutive ordered-list
items), ``ssot-quote`` marker count, and the body line count against the
budget. For each: growing (or a brand-new nonzero count) is BLOCK-eligible
(subject to the surface's `edit_mode` and `grandfather_allowlist`,
exactly like every other check); unchanged-but-violating is ADVISE;
shrinking is silent — mirroring ``plan_doc_size``'s established tiering
philosophy exactly. SWEEP has no before/after, so it is always ADVISE.

Frontmatter (the leading ``---\\n...\\n---`` block) is stripped before
counting anything — it never counts toward a violation.

This check needs no corpus: EDIT is single-file content, and SWEEP
resolves ``.claude/rules/*.md`` directly against the filesystem (the same
independence rationale as ``generated_doc_hand_edit``).
"""

import logging
import re
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.docs_qa.corpus import matches_scope_exclude
from claude_code_hooks_daemon.docs_qa.types import (
    CheckContext,
    CheckSpec,
    CheckStage,
    Finding,
    Severity,
)

logger = logging.getLogger(__name__)

CHECK_ID: Final[str] = "rules-file-shape"

# RULESET-sub-claude-md.md §3: "Body budget: <= ~15 lines / <=3 sentences of
# orientation". Counted in non-blank, non-frontmatter LINES (the cheap,
# deterministic proxy the rest of docs_qa/plan_qa already use for a read-cost
# budget, e.g. plan_qa's DEFAULT_PLAN_DOC_ADVISORY_LINES).
RULES_FILE_BODY_LINE_BUDGET: Final[int] = 15

_RULES_DIR_PARTS: Final[tuple[str, str]] = (".claude", "rules")
_MARKDOWN_SUFFIX: Final[str] = ".md"
_MIN_PROCEDURE_RUN_LENGTH: Final[int] = 3

_FRONTMATTER_RE: Final[re.Pattern[str]] = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n?", re.DOTALL)
_FENCE_MARKER_RE: Final[re.Pattern[str]] = re.compile(r"^```", re.MULTILINE)
_TABLE_SEPARATOR_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$"
)
_ORDERED_LIST_ITEM_RE: Final[re.Pattern[str]] = re.compile(r"^\s*\d+\.\s+\S")
_SSOT_QUOTE_MARKER_RE: Final[re.Pattern[str]] = re.compile(r"<!--\s*ssot-quote:")

_ELEMENT_LABELS: Final[dict[str, str]] = {
    "fences": "fenced code block",
    "tables": "markdown table",
    "procedure_runs": "numbered-procedure run (3+ consecutive ordered-list items)",
    "ssot_quotes": "ssot-quote block",
}


def _strip_frontmatter(text: str) -> str:
    """The body of ``text`` with a leading YAML frontmatter block removed."""
    return _FRONTMATTER_RE.sub("", text, count=1)


def _count_fences(body: str) -> int:
    """Fenced-code-block count (a well-formed pair of ``` markers is one block)."""
    return len(_FENCE_MARKER_RE.findall(body)) // 2


def _count_tables(body: str) -> int:
    """Markdown-table count — one per GFM header-separator row."""
    return sum(1 for line in body.splitlines() if _TABLE_SEPARATOR_RE.match(line))


def _count_procedure_runs(body: str) -> int:
    """Count of RUNS of 3+ consecutive ordered-list items.

    A 1-2 item ordered list is a legitimate two-imperative-line rule (R7a
    permits up to two lines); only a RUN of 3 or more is a "numbered
    procedure" in the sense this check forbids.
    """
    runs = 0
    current_run = 0
    for line in body.splitlines():
        if _ORDERED_LIST_ITEM_RE.match(line):
            current_run += 1
            continue
        if current_run >= _MIN_PROCEDURE_RUN_LENGTH:
            runs += 1
        current_run = 0
    if current_run >= _MIN_PROCEDURE_RUN_LENGTH:
        runs += 1
    return runs


def _count_ssot_quotes(body: str) -> int:
    return len(_SSOT_QUOTE_MARKER_RE.findall(body))


def _body_line_count(body: str) -> int:
    """Non-blank line count of ``body`` (frontmatter already stripped)."""
    return sum(1 for line in body.splitlines() if line.strip())


@dataclass(frozen=True)
class _Metrics:
    fences: int
    tables: int
    procedure_runs: int
    ssot_quotes: int
    body_lines: int


_EMPTY_METRICS: Final[_Metrics] = _Metrics(
    fences=0, tables=0, procedure_runs=0, ssot_quotes=0, body_lines=0
)


def _measure(content: str) -> _Metrics:
    body = _strip_frontmatter(content)
    return _Metrics(
        fences=_count_fences(body),
        tables=_count_tables(body),
        procedure_runs=_count_procedure_runs(body),
        ssot_quotes=_count_ssot_quotes(body),
        body_lines=_body_line_count(body),
    )


def _is_rules_file(path: Path, project_root: Path) -> bool:
    """True only for a ``.md`` file DIRECTLY inside ``.claude/rules/``."""
    if path.suffix.lower() != _MARKDOWN_SUFFIX:
        return False
    try:
        rel_parts = path.resolve().relative_to(project_root.resolve()).parts
    except ValueError:
        return False
    return len(rel_parts) == 3 and rel_parts[:2] == _RULES_DIR_PARTS


def _matches_allowlist(rel_path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch(rel_path, pattern) for pattern in patterns)


def _remediation(element: str) -> str:
    return (
        f"`.claude/rules/*.md` files are pointers only (R7a) — see "
        f"CLAUDE/DocumentationStrategy.md. Promote the {element} content to "
        f"a canonical doc in the agent tree (or a registered `CLAUDE.md`) "
        f"FIRST, then thin this file to a trigger statement, the rule in "
        f"at most two imperative lines, and a link."
    )


def _element_finding(rel_path: str, element: str, severity: Severity) -> Finding:
    return Finding(
        check_id=CHECK_ID,
        severity=severity,
        message=f"`{rel_path}` contains a forbidden {element} (R7a: pointers only).",
        remediation=_remediation(element),
        path=rel_path,
    )


def _budget_finding(rel_path: str, body_lines: int, severity: Severity) -> Finding:
    return Finding(
        check_id=CHECK_ID,
        severity=severity,
        message=(
            f"`{rel_path}` body is {body_lines} non-blank lines, over the "
            f"{RULES_FILE_BODY_LINE_BUDGET}-line pointer budget (R7a)."
        ),
        remediation=_remediation("excess"),
        path=rel_path,
    )


def _element_findings_worse_only(
    rel_path: str, new: _Metrics, old: _Metrics, grandfathered: bool
) -> list[Finding]:
    findings: list[Finding] = []
    for attr, label in _ELEMENT_LABELS.items():
        new_count = getattr(new, attr)
        old_count = getattr(old, attr)
        if new_count > old_count:
            severity = Severity.ADVISE if grandfathered else Severity.BLOCK
            findings.append(_element_finding(rel_path, label, severity))
        elif new_count == old_count and new_count > 0:
            findings.append(_element_finding(rel_path, label, Severity.ADVISE))
        # new_count < old_count: shrinking is silent, even if still nonzero.
    if new.body_lines > RULES_FILE_BODY_LINE_BUDGET:
        if new.body_lines > old.body_lines:
            severity = Severity.ADVISE if grandfathered else Severity.BLOCK
            findings.append(_budget_finding(rel_path, new.body_lines, severity))
        elif new.body_lines == old.body_lines:
            findings.append(_budget_finding(rel_path, new.body_lines, Severity.ADVISE))
        # new.body_lines < old.body_lines: shrinking is silent.
    return findings


def _element_findings_always_advise(rel_path: str, metrics: _Metrics) -> list[Finding]:
    findings: list[Finding] = []
    for attr, label in _ELEMENT_LABELS.items():
        if getattr(metrics, attr) > 0:
            findings.append(_element_finding(rel_path, label, Severity.ADVISE))
    if metrics.body_lines > RULES_FILE_BODY_LINE_BUDGET:
        findings.append(_budget_finding(rel_path, metrics.body_lines, Severity.ADVISE))
    return findings


def _run_edit(context: CheckContext) -> list[Finding]:
    if context.file_path is None or context.file_content is None:
        return []
    if not _is_rules_file(context.file_path, context.project_root):
        return []

    rel_path = str(context.file_path.relative_to(context.project_root))
    new_metrics = _measure(context.file_content)
    old_metrics = (
        _measure(context.file_content_before)
        if context.file_content_before is not None
        else _EMPTY_METRICS
    )
    grandfathered = _matches_allowlist(rel_path, context.policy.qa.grandfather_allowlist)
    return _element_findings_worse_only(rel_path, new_metrics, old_metrics, grandfathered)


def _run_sweep(context: CheckContext) -> list[Finding]:
    findings: list[Finding] = []
    for path in sorted(context.project_root.glob("/".join((*_RULES_DIR_PARTS, "*.md")))):
        if not path.is_file():
            continue
        rel_path = str(path.relative_to(context.project_root))
        # This SWEEP globs the rules directory itself instead of reading the
        # corpus, so it inherits none of the corpus's exclusions -- the
        # project's configured ones have to be applied here explicitly, or a
        # scope-excluded rules file is reported with no way to silence it.
        if matches_scope_exclude(rel_path, tuple(context.policy.qa.scope_exclude_globs)):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            # An unreadable or undecodable file must not abort the whole
            # SessionStart sweep (Plan 00287 N5) -- skip it, matching the
            # corpus's own UnicodeDecodeError handling.
            logger.debug("rules-file-shape: skipping unreadable %s: %s", rel_path, exc)
            continue
        metrics = _measure(content)
        findings.extend(_element_findings_always_advise(rel_path, metrics))
    return findings


CHECKS: Final[tuple[CheckSpec, CheckSpec]] = (
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.EDIT, run=_run_edit),
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.SWEEP, run=_run_sweep),
)
