"""Check ``journal-dayfile-is-today`` (Stage 1, block by default; Plan 00197).

A journal day-file edit whose embedded date is not EXACTLY today is blocked.
Unlike ``journal-dayfile-naming`` (which tolerates yesterday as a legitimate
midnight-rollover exception), this check treats the rollover as the MAIN case
it defends against: an agent whose session spans midnight must start today's
day-file, not keep appending to yesterday's — that confusion is precisely
what "never log against the wrong day" means.

Scope is deliberately narrow (SRP): grammar, plan-number coherence and
calendar validity all remain ``journal-dayfile-naming``'s job. This check only
judges recency of an otherwise well-formed, parseable name — a malformed name
or an impossible calendar date defers entirely (returns no finding) so the two
checks never produce contradictory advice about the same file.

Ships BLOCK by default via its own ``today_only_mode`` knob, independent of
``journal_mode`` — the write-time freshness rule is not given the advise-first
rollout grace period the original journalling checks received (Decision 4 in
``journal_dayfile_naming``), because the user-reported failure mode is agents
silently mis-filing entries, not a rollout concern.

**An existing journal file is closed (Plan 00543).** New entries are new files
(``JOURNAL/YYYY-MM-DD/HHMMSSZ-<category>-<hex>.md``), so a write to a journal
file that already exists rewrites the record whatever its date: a legacy
day-file is closed and an entry file is immutable. Two rewrites destroy
nothing and stay clean, for parity with ``plan_journal_guard``: removing only
conflict-marker lines, and restoring the committed (HEAD) bytes. Creating an
entry file is clean; creating a legacy day-file keeps the not-today rule.

The COMMIT half covers what no EDIT hook sees — a Bash write: a staged
modification or deletion of an entry file, or a rename whose content differs
from the file it was moved from. A pure rename (archiving a plan) is clean.
"""

from datetime import date
from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import (
    JournalEditTarget,
    journal_edit_target,
    journal_today_only_level,
    journalling_active,
    level_for_plan,
)
from claude_code_hooks_daemon.plan_qa.model import (
    JOURNAL_BODY_FILE_HINT,
    journal_append_command,
    only_conflict_markers_removed,
    parse_journal_dayfile_name,
)
from claude_code_hooks_daemon.plan_qa.paths import PlanFileKind, classify
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)
from claude_code_hooks_daemon.utils.git_facts import GitFactsBase, StagedChange

CHECK_ID: Final[str] = "journal-dayfile-is-today"
STATEMENT: Final[str] = (
    "An existing journal file is closed, and a legacy day-file must be dated exactly today. Record entries as new files with `mkplan.bash --journal`."
)

_GENERIC_DAYFILE_NAME: Final[str] = "NNNNN-Journal-YY-MM-DD.md"


def _suggested_filename(plan_number: int, today: date) -> str:
    """The exact today-dated day-file name the stamping tool will write to."""
    return f"{plan_number:05d}-Journal-{today.strftime('%y-%m-%d')}.md"


def _remediation(plan_dir: str, plan_number: int | None, today: date) -> str:
    dayfile = (
        _GENERIC_DAYFILE_NAME if plan_number is None else _suggested_filename(plan_number, today)
    )
    return (
        "A journal is append-only — never edit a stale legacy day-file, "
        "even one dated yesterday. Record the entry with "
        f"`{journal_append_command(plan_dir, plan_number)}` instead "
        f"({JOURNAL_BODY_FILE_HINT}); a new entry is its own file, so there is "
        f"no day-file (`{dayfile}`) to append to."
    )


def _closed_remediation(plan_dir: str, plan_number: int | None) -> str:
    return (
        "A journal file is never rewritten once it exists: a legacy day-file is "
        "closed and an entry file is immutable. Record the change as a NEW entry "
        f"with `{journal_append_command(plan_dir, plan_number)}` ({JOURNAL_BODY_FILE_HINT}); "
        "a correction entry names the one it corrects."
    )


def _effective_level(context: CheckContext, level: Level, plan_number: int | None) -> Level:
    if level is Level.BLOCK:
        return level_for_plan(context, plan_number)
    return level


def _head_text(context: CheckContext, rel_path: str) -> str | None:
    """The committed (HEAD) content of ``rel_path``; ``None`` when there is none."""
    gitfacts = context.gitfacts or GitFactsBase(context.project_root)
    return gitfacts.head_file_text(rel_path)


def _existing_file_findings(
    context: CheckContext, target: JournalEditTarget, level: Level
) -> list[Finding]:
    after = context.file_content
    before = context.file_content_before
    if after is None or after == before:
        return []
    if before is not None and only_conflict_markers_removed(before, after):
        return []
    if after == _head_text(context, target.rel_path):
        return []
    return [
        Finding(
            check_id=CHECK_ID,
            level=_effective_level(context, level, target.plan_number),
            message=(
                f"Journal file `{target.basename}` already exists; writing to it "
                "rewrites the journal record"
            ),
            remediation=_closed_remediation(context.plan_dir_rel, target.plan_number),
            path=target.rel_path,
        )
    ]


def _run_edit(context: CheckContext) -> list[Finding]:
    target = journal_edit_target(context)
    if target is None:
        return []

    level = journal_today_only_level(context)
    if level is None:
        return []

    if context.file_exists_before is True:
        return _existing_file_findings(context, target, level)

    if target.is_entry_file:
        return []

    # Grammar / plan-number / calendar-validity problems belong to
    # journal-dayfile-naming; deferring here (rather than re-reporting) keeps
    # the two checks from ever giving contradictory advice about one file.
    parsed = parse_journal_dayfile_name(target.basename)
    if parsed is None or not parsed.is_valid_date:
        return []

    # Fail OPEN on an unknown clock (e.g. the `plan-qa --lint` CLI path never
    # supplies `today`) — blocking on missing date information would be worse
    # than the bug this check exists to catch.
    if context.today is None:
        return []

    if parsed.date == context.today:
        return []

    return [
        Finding(
            check_id=CHECK_ID,
            level=_effective_level(context, level, target.plan_number),
            message=(
                f"Journal day-file `{target.basename}` is dated "
                f"{parsed.date.isoformat()}, not today ({context.today.isoformat()})"
            ),
            remediation=_remediation(context.plan_dir_rel, target.plan_number, context.today),
            path=target.rel_path,
        )
    ]


_MODIFY_STATUS: Final[str] = "M"
_DELETE_STATUS: Final[str] = "D"
_RENAME_PREFIX: Final[str] = "R"

_CHANGE_WORDS: Final[dict[str, str]] = {
    _MODIFY_STATUS: "modified",
    _DELETE_STATUS: "deleted",
    _RENAME_PREFIX: "moved with its content changed",
}


def _rewrite_kind(context: CheckContext, change: StagedChange) -> str | None:
    """The status key of a staged change that rewrites an entry file, else ``None``."""
    if change.status in (_MODIFY_STATUS, _DELETE_STATUS):
        return change.status
    if change.status.startswith(_RENAME_PREFIX) and context.gitfacts is not None:
        staged = context.gitfacts.staged_file_text(change.path)
        if staged != context.gitfacts.head_file_text(change.old_path or change.path):
            return _RENAME_PREFIX
    return None


def _run_commit(context: CheckContext) -> list[Finding]:
    gitfacts = context.gitfacts
    if gitfacts is None or not journalling_active(context):
        return []
    level = journal_today_only_level(context)
    if level is None:
        return []

    findings: list[Finding] = []
    for change in gitfacts.staged_changes():
        rel_path = change.old_path or change.path
        classified = classify(context.project_root / rel_path, context)
        if classified.kind is not PlanFileKind.JOURNAL_ENTRY:
            continue
        kind = _rewrite_kind(context, change)
        if kind is None:
            continue
        findings.append(
            Finding(
                check_id=CHECK_ID,
                level=_effective_level(context, level, classified.plan_number),
                message=(
                    f"Journal entry file `{rel_path}` is {_CHANGE_WORDS[kind]} in this "
                    "commit; an entry file is immutable once written"
                ),
                remediation=_closed_remediation(context.plan_dir_rel, classified.plan_number),
                path=rel_path,
            )
        )
    return findings


EDIT_CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.EDIT,
    level=Level.BLOCK,
    sins=(),
    run=_run_edit,
)

COMMIT_CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.COMMIT,
    level=Level.BLOCK,
    sins=(),
    run=_run_commit,
)

CHECKS: Final[tuple[CheckSpec, CheckSpec]] = (EDIT_CHECK, COMMIT_CHECK)
