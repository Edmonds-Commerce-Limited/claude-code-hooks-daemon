"""Check ``archival-links-resolve`` (Stage 2, block; Plan 00408 Task 3.2b).

Archiving a plan moves it one directory deeper, so every relative link it makes
shifts by one level. Archiving Plans 00406 and 00407 turned four ``../00408-…``
links and two ``../Completed/00405-…`` links dead, and a full ``docs-qa
--sweep`` straight afterwards reported the corpus clean.

**Why here and not in the sweep.** Docs QA excludes the archive directories from
its corpus, and plan QA's ``plan-link-resolves`` exempts archived plans, both
for the reason ``archive-immutability`` states: an archived plan is a RECORD,
and editing one to match today's tree falsifies it. That exemption is right for
a link that goes dead LATER, because somebody else moved its target. It is wrong
for the archival commit itself, which is the one commit still writing the
record, and the one that breaks the link. So this runs there and nowhere else:
on each ``.md`` file this commit RENAMES into an archive directory.

A link the move broke BLOCKS, with the repoint that restores it. A link that
was already dead before the move is reported as advice: this commit did not
cause it. ``JOURNAL/`` day-files are skipped, because they are append-only and
``journal-append-only`` forbids the repoint this check would ask for.
"""

import posixpath
from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.plan_link_resolves import is_skippable_link
from claude_code_hooks_daemon.plan_qa.gitfacts import StagedChange
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)
from claude_code_hooks_daemon.utils.authored_paths import authored_path_exists
from claude_code_hooks_daemon.utils.link_resolution import link_resolves_literally
from claude_code_hooks_daemon.utils.markdown_links import extract_link_targets

CHECK_ID: Final[str] = "archival-links-resolve"

_RENAME_STATUS_PREFIX: Final[str] = "R"
_MARKDOWN_SUFFIX: Final[str] = ".md"
_FRAGMENT: Final[str] = "#"
_ROOT_PREFIX: Final[str] = "/"
_PARENT: Final[str] = ".."


def _archived_renames(
    context: CheckContext, changes: tuple[StagedChange, ...]
) -> list[StagedChange]:
    """Markdown files this commit moves INTO an archive directory, journals excluded."""
    plan_dir = context.plan_dir_rel.rstrip("/")
    archives = [name for name in (context.completed_dir, context.cancelled_dir) if name]
    prefixes = tuple(f"{plan_dir}/{name}/" for name in archives)
    moved: list[StagedChange] = []
    for change in changes:
        if not change.status.startswith(_RENAME_STATUS_PREFIX) or change.old_path is None:
            continue
        if not change.path.endswith(_MARKDOWN_SUFFIX) or not change.path.startswith(prefixes):
            continue
        if context.journal_dir_name in change.path.split("/"):
            continue
        moved.append(change)
    return moved


def _after_this_commit(path: str, renames: dict[str, str]) -> str:
    """Where ``path`` (a file or a directory) lives once this commit lands."""
    if path in renames:
        return renames[path]
    prefix = path.rstrip("/") + "/"
    for old, new in renames.items():
        if old.startswith(prefix):
            suffix = old[len(prefix) :]
            if new.endswith("/" + suffix):
                return new[: -len(suffix) - 1]
    return path


def _link_finding(
    context: CheckContext, change: StagedChange, link: str, renames: dict[str, str]
) -> Finding | None:
    old_dir = posixpath.dirname(change.old_path or "")
    new_dir = posixpath.dirname(change.path)
    if link_resolves_literally(context.project_root, context.project_root / new_dir, link):
        return None

    file_part, hash_sign, fragment = link.partition(_FRAGMENT)
    before = posixpath.normpath(posixpath.join(old_dir, file_part))
    depth_sensitive = not file_part.startswith(_ROOT_PREFIX) and not before.startswith(_PARENT)
    current = _after_this_commit(before, renames) if depth_sensitive else None
    if current is None or not authored_path_exists(context.project_root, current):
        return Finding(
            check_id=CHECK_ID,
            level=Level.ADVISE,
            message=f"`{change.path}` links to `{link}`, which did not resolve before the move either",
            remediation="Repoint or remove the link while the record is still being written.",
            path=change.path,
        )

    repoint = posixpath.relpath(current, new_dir) + hash_sign + fragment
    return Finding(
        check_id=CHECK_ID,
        level=Level.BLOCK,
        message=(
            f"Archiving `{change.old_path}` breaks its link `{link}`: the plan moved one "
            "level deeper, so every relative link shifted with it"
        ),
        remediation=(
            f"In `{change.path}`, repoint `{link}` to `{repoint}` and re-stage. "
            "archive-immutability will advise on the edit; this is the deliberate "
            "correction it asks about, made in the commit that writes the record."
        ),
        path=change.path,
    )


def _run(context: CheckContext) -> list[Finding]:
    gitfacts = context.gitfacts
    if gitfacts is None:
        return []
    changes = gitfacts.staged_changes()
    renames = {
        change.old_path: change.path
        for change in changes
        if change.status.startswith(_RENAME_STATUS_PREFIX) and change.old_path is not None
    }
    findings: list[Finding] = []
    for change in _archived_renames(context, changes):
        text = gitfacts.staged_file_text(change.path)
        if text is None:
            continue
        for link in dict.fromkeys(extract_link_targets(text)):
            if is_skippable_link(link):
                continue
            finding = _link_finding(context, change, link, renames)
            if finding is not None:
                findings.append(finding)
    return findings


CHECK: Final[CheckSpec] = CheckSpec(
    check_id=CHECK_ID,
    stage=Stage.COMMIT,
    level=Level.BLOCK,
    sins=(),
    run=_run,
)
