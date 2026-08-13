"""Shared helpers for Stage 1 (edit-time) plan QA checks.

Every edit-time check starts the same way: is this Write/Edit targeting a
``PLAN.md`` under the configured plan directory, and if so what does the
would-be content parse to? :func:`edit_target` answers that once, so each
check module stays a single focused rule.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final, NamedTuple

from claude_code_hooks_daemon.plan_qa.model import PLAN_DOC_FILENAME, PlanDoc, PlanLocation
from claude_code_hooks_daemon.plan_qa.paths import classify
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)

_PLAN_FOLDER_NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"^(\d{1,5})-[a-zA-Z]")

# Journal mode tokens (mirror PlanWorkflowQaJournalConfig.mode).
_JOURNAL_MODE_OFF: Final[str] = "off"
_JOURNAL_MODE_BLOCK: Final[str] = "block"

# journal-dayfile-is-today mode tokens (mirror
# PlanWorkflowQaJournalConfig.today_only_mode; Plan 00197).
_JOURNAL_TODAY_ONLY_MODE_OFF: Final[str] = "off"
_JOURNAL_TODAY_ONLY_MODE_BLOCK: Final[str] = "block"


@dataclass(frozen=True)
class DocumentTarget:
    """One plan document resolved for checking.

    Produced by :func:`edit_target` from a per-edit payload, and by
    :func:`tree_targets` from a scanned tree, so a document-level rule can be
    written once and run on both surfaces.

    ``text`` carries the raw document. A rule that reached for
    ``context.file_content`` instead was silently edit-only — that field is
    ``None`` on a sweep context — so the text belongs on the target, where
    both resolvers can supply it.
    """

    rel_path: str
    plan_number: int | None
    doc: PlanDoc
    in_archive: bool
    text: str


# Kept for readers who know the type by its edit-surface name.
EditTarget = DocumentTarget

_ARCHIVED_LOCATIONS: Final[frozenset[PlanLocation]] = frozenset(
    {PlanLocation.COMPLETED, PlanLocation.CANCELLED}
)


def edit_target(context: CheckContext) -> DocumentTarget | None:
    """Resolve an EDIT context to a plan-document target, or ``None``.

    ``None`` means "this check does not apply": no file in the context, or the
    shared classifier says this path is not a plan document — because it is
    outside the plan directory, is not named ``PLAN.md``, or is journal
    territory (Plan 00190).
    """
    if context.file_path is None or context.file_content is None:
        return None

    classified = classify(context.file_path, context)
    if not classified.is_plan_document:
        return None

    return DocumentTarget(
        rel_path=classified.rel_path,
        plan_number=classified.plan_number,
        doc=PlanDoc.parse(context.file_content),
        in_archive=classified.in_archive,
        text=context.file_content,
    )


def tree_targets(context: CheckContext) -> list[DocumentTarget]:
    """Every plan document in the scanned tree — the batch twin of :func:`edit_target`.

    A SWEEP context carries no file payload, so re-registering an edit-time
    check at ``Stage.SWEEP`` makes it no-match every time: registered, never
    firing, indistinguishable from passing. Batch rules must iterate the tree,
    which is what this resolver exists to give them.

    Folders with no ``PLAN.md`` are skipped — that gap is
    ``location-status-coherence``'s finding, and reporting it from every
    document rule as well would bury it.
    """
    if context.tree is None:
        return []

    targets: list[DocumentTarget] = []
    for folder in context.tree.folders:
        if folder.location == PlanLocation.OTHER or folder.doc is None:
            continue
        plan_md = folder.path / PLAN_DOC_FILENAME
        targets.append(
            DocumentTarget(
                rel_path=str(plan_md.relative_to(context.project_root)),
                plan_number=folder.number,
                doc=folder.doc,
                in_archive=folder.location in _ARCHIVED_LOCATIONS,
                text=plan_md.read_text(encoding="utf-8"),
            )
        )
    return targets


DocumentRule = Callable[[CheckContext, DocumentTarget], list[Finding]]


class DocumentRuleChecks(NamedTuple):
    """One document rule's two registrations, addressable by surface.

    A ``NamedTuple`` so ``*CHECKS`` still splats into the registry while
    ``CHECKS.edit`` / ``CHECKS.sweep`` name the halves — an index would leave
    every call site asserting against ``[0]``.
    """

    edit: CheckSpec
    sweep: CheckSpec


# Checks that are about the ACT OF WRITING, not about on-disk state, and so
# have no batch equivalent by design. Each entry records why, because the
# totality guard treats an unexplained omission as a gap.
WRITE_ACT_ONLY_RULES: Final[dict[str, str]] = {
    "archive_immutability": (
        "Reports that an ARCHIVED plan was edited. An archived plan sitting "
        "untouched on disk is the correct state, not a finding."
    ),
    "journal_append_only": (
        "Compares the would-be content against what the file already holds. "
        "There is no before/after to compare in a batch scan."
    ),
    "journal_dayfile_is_today": (
        "Reports that a day-file dated other than today is being WRITTEN. "
        "Yesterday's day-file existing on disk is exactly what a journal is."
    ),
    "plan_doc_size": (
        "Tiered on grow/shrink: only an edit that GROWS an over-limit document "
        "is blocked, so an oversized plan stays editable and can be refactored "
        "down. A batch scan has no direction of travel to judge."
    ),
    "template_metadata": (
        "Scoped to BRAND-NEW documents (file_exists_before is False) so legacy "
        "plans predating the template are never re-checked. Everything in a "
        "batch scan already exists, so batching it would re-check exactly the "
        "plans the rule documents itself as not applying to."
    ),
    "terminal_placement_hint": (
        "location-status-coherence already reports a terminal status loitering "
        "in the active root at SWEEP, at BLOCK level with the same remediation. "
        "A twin here would double-report every finding."
    ),
}


def document_rule_modules() -> frozenset[str]:
    """Short module names of every check registered at ``Stage.EDIT``."""
    return _modules_registered_for(Stage.EDIT)


def batched_document_rule_modules() -> frozenset[str]:
    """Short module names of every check registered at ``Stage.SWEEP``."""
    return _modules_registered_for(Stage.SWEEP)


def _modules_registered_for(stage: Stage) -> frozenset[str]:
    """Derive module attribution from the registry itself.

    Read from :func:`all_checks` rather than a hand-maintained list, so a new
    check is classified the moment it is registered — a list would need
    remembering, which is the failure this guard exists to prevent.
    """
    from claude_code_hooks_daemon.plan_qa.checks import all_checks

    return frozenset(
        spec.run.__module__.rsplit(".", 1)[-1] for spec in all_checks() if spec.stage == stage
    )


def document_rule_checks(
    *,
    check_id: str,
    level: Level,
    sins: Sequence[str],
    rule: DocumentRule,
) -> DocumentRuleChecks:
    """Register one document-level rule at BOTH edit time and sweep time.

    The rule is written once against a single :class:`DocumentTarget`; this
    adapter feeds it the edit payload on one surface and every document in the
    tree on the other. Both closures are attributed to the rule's own module so
    the registry can tell which check they belong to.
    """

    def run_edit(context: CheckContext) -> list[Finding]:
        target = edit_target(context)
        return [] if target is None else rule(context, target)

    def run_sweep(context: CheckContext) -> list[Finding]:
        findings: list[Finding] = []
        for target in tree_targets(context):
            findings.extend(rule(context, target))
        return findings

    run_edit.__module__ = rule.__module__
    run_sweep.__module__ = rule.__module__
    sins_tuple = tuple(sins)
    return DocumentRuleChecks(
        edit=CheckSpec(
            check_id=check_id, stage=Stage.EDIT, level=level, sins=sins_tuple, run=run_edit
        ),
        sweep=CheckSpec(
            check_id=check_id, stage=Stage.SWEEP, level=level, sins=sins_tuple, run=run_sweep
        ),
    )


def level_for_plan(context: CheckContext, plan_number: int | None) -> Level:
    """BLOCK for new material, ADVISE for grandfathered legacy plans.

    The ratchet only loosens for plans explicitly allowlisted in
    ``legacy_plan_allowlist`` — unknown or unnumbered material is held to
    the full standard.
    """
    if plan_number is not None and plan_number in context.legacy_plan_allowlist:
        return Level.ADVISE
    return Level.BLOCK


@dataclass(frozen=True)
class JournalEditTarget:
    """A journal day-file edit resolved against the plan directory."""

    rel_path: str
    plan_number: int | None
    basename: str


def journal_edit_target(context: CheckContext) -> JournalEditTarget | None:
    """Resolve an EDIT context to a journal day-file target, or ``None``.

    ``None`` means "this check does not apply": no file in the context, the
    file is not a ``.md`` directly inside a ``{journal_dir_name}/`` directory,
    or that directory is not inside a ``NNNNN-*`` plan folder under the plan
    directory. Journalling being disabled (``journal_enabled`` false or
    ``journal_mode == "off"``) is also a documented no-match.
    """
    if context.file_path is None or context.file_content is None:
        return None
    # POLICY gate — deliberately here and not in the classifier. Classification
    # is config-independent (Plan 00190 Decision 5) so that disabling
    # journalling can never re-apply plan rules to a journal file; it only
    # switches the journal CHECKS off.
    if not journalling_active(context):
        return None

    classified = classify(context.file_path, context)
    if not classified.is_journal:
        return None
    # Day-files live DIRECTLY in the journal directory. Anything nested deeper
    # is journal territory (so plan rules stay off it) but is not a day-file
    # the journal checks act on.
    if context.file_path.parent.name != context.journal_dir_name:
        return None

    return JournalEditTarget(
        rel_path=classified.rel_path,
        plan_number=classified.plan_number,
        basename=context.file_path.name,
    )


def journal_tree_targets(context: CheckContext) -> list[JournalEditTarget]:
    """Every journal day-file candidate on disk — the batch twin of :func:`journal_edit_target`.

    Yields every ``.md`` directly inside a plan folder's journal directory,
    INCLUDING files whose names do not parse: a malformed name is precisely
    what the naming check exists to report, so filtering by the grammar here
    would hide exactly the findings the caller wants.
    """
    if context.tree is None or not journalling_active(context):
        return []

    targets: list[JournalEditTarget] = []
    for folder in context.tree.folders:
        journal_dir = folder.path / context.journal_dir_name
        if not journal_dir.is_dir():
            continue
        for entry in sorted(journal_dir.iterdir()):
            if not entry.is_file() or entry.suffix != _MARKDOWN_SUFFIX:
                continue
            targets.append(
                JournalEditTarget(
                    rel_path=str(entry.relative_to(context.project_root)),
                    plan_number=folder.number,
                    basename=entry.name,
                )
            )
    return targets


def journal_level(context: CheckContext) -> Level:
    """BLOCK only when journal enforcement has been ratcheted to ``block``.

    Journalling ships advise-first (Plan 00163 Decision 4); only the
    naming check may ever honour ``mode: block``.
    """
    return Level.BLOCK if context.journal_mode == _JOURNAL_MODE_BLOCK else Level.ADVISE


def journalling_active(context: CheckContext) -> bool:
    """Whether journal checks should run at all under the current policy."""
    return context.journal_enabled and context.journal_mode != _JOURNAL_MODE_OFF


def journal_today_only_level(context: CheckContext) -> Level | None:
    """Level for ``journal-dayfile-is-today``, or ``None`` when its mode is off.

    Independent of :func:`journal_level` — this check ships BLOCK by default
    (Plan 00197), not advise-first, so it has its own mode knob rather than
    piggybacking on ``journal_mode``.
    """
    mode = context.journal_today_only_mode
    if mode == _JOURNAL_TODAY_ONLY_MODE_OFF:
        return None
    return Level.BLOCK if mode == _JOURNAL_TODAY_ONLY_MODE_BLOCK else Level.ADVISE


# --- COMMIT-stage journal helpers (Plan 00163 Phase 3) --------------------

_PLAN_MD_SUFFIX: Final[str] = "/" + PLAN_DOC_FILENAME
_COMMIT_ADD_STATUS: Final[str] = "A"
_COMMIT_MODIFY_STATUS: Final[str] = "M"
_COMMIT_RENAME_PREFIX: Final[str] = "R"


def staged_plan_md_folder(path: str, plan_dir_rel: str) -> str | None:
    """Repo-relative plan FOLDER for a staged ``PLAN.md`` path, else ``None``.

    ``None`` means the path is not a ``PLAN.md`` under the configured plan
    directory — a documented no-match, not an error.
    """
    prefix = plan_dir_rel.rstrip("/") + "/"
    if not path.startswith(prefix) or not path.endswith(_PLAN_MD_SUFFIX):
        return None
    return path[: -len(_PLAN_MD_SUFFIX)]


def plan_number_for_folder(folder: str) -> int | None:
    """Plan number parsed from the last path component of ``folder``."""
    match = _PLAN_FOLDER_NUMBER_RE.match(folder.rsplit("/", 1)[-1])
    return int(match.group(1)) if match else None


def journal_in_commit_scope(context: CheckContext, plan_number: int | None) -> bool:
    """Whether COMMIT journal checks apply to this plan under current policy.

    Journalling must be active AND the plan numbered at or above the
    grandfather threshold — legacy plans that never carried a ``JOURNAL/`` are
    never nagged at commit time (Plan 00163 Decision 7).
    """
    if not journalling_active(context):
        return False
    return plan_number is not None and plan_number >= context.journal_grandfather_before


def has_staged_journal_entry(context: CheckContext, folder: str) -> bool:
    """Whether a real (new or appended) journal entry is staged under ``folder``.

    A pure ``git mv`` of the plan folder into the archive renames existing
    day-files without changing their content; those renames are NOT new
    entries and must not satisfy the coupling. Only an Added file, a Modified
    file, or a rename whose staged content actually differs from its HEAD
    counterpart counts — which is why a bare
    :meth:`GitFacts.staged_paths_under` membership test is insufficient for the
    completion coupling (the moved files always match the prefix).
    """
    gitfacts = context.gitfacts
    if gitfacts is None:
        return False
    prefix = f"{folder}/{context.journal_dir_name}/"
    for change in gitfacts.staged_changes():
        if not change.path.startswith(prefix):
            continue
        if change.status in (_COMMIT_ADD_STATUS, _COMMIT_MODIFY_STATUS):
            return True
        if change.status.startswith(_COMMIT_RENAME_PREFIX):
            staged_text = gitfacts.staged_file_text(change.path)
            head_text = gitfacts.head_file_text(change.old_path or change.path)
            if staged_text is not None and staged_text != head_text:
                return True
    return False


_MARKDOWN_SUFFIX: Final[str] = ".md"


def has_staged_supporting_doc(context: CheckContext, folder: str) -> bool:
    """Whether a brand-new supporting document is staged directly in ``folder``.

    Extraction — moving durable, current detail (research, decisions,
    evidence tables) out of an oversized ``PLAN.md`` into a NAMED file in the
    same plan folder — is exactly as legitimate a relocation as a
    ``JOURNAL/`` entry (Plan 00211): a field report's restructure commit
    shrank PLAN.md by 9,525 bytes while staging three brand-new supporting
    ``.md`` files, and the check's only reason for not flagging it was that
    a journal entry happened to also be staged.

    Scoped to a NEW (Added) ``.md`` file DIRECTLY in ``folder`` — matching
    is by "no further ``/`` after the prefix", which naturally excludes
    ``JOURNAL/*`` (nested under the journal directory) and any other nested
    subdirectory (e.g. ``assets/``) without a separate check. ``PLAN.md``
    itself never counts — editing it is not evidence that something was
    relocated OUT of it. Only ``Added`` status counts (not ``Modified``):
    the report's own trigger case was extraction creating brand-new files,
    and a modify-only edit to a pre-existing supporting doc is unrelated
    editing churn, not evidence of THIS shrink being a relocation.
    """
    gitfacts = context.gitfacts
    if gitfacts is None:
        return False
    prefix = folder.rstrip("/") + "/"
    for change in gitfacts.staged_changes():
        if change.status != _COMMIT_ADD_STATUS:
            continue
        if not change.path.startswith(prefix):
            continue
        remainder = change.path[len(prefix) :]
        if "/" in remainder:
            continue
        if remainder == PLAN_DOC_FILENAME:
            continue
        if not remainder.endswith(_MARKDOWN_SUFFIX):
            continue
        return True
    return False
