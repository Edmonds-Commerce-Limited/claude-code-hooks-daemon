"""Check ``plan-stats-arithmetic`` (Stage 1 advise, Stage 2/3 block; Plan 00466 N13).

The plan index's folder-to-number reconciliation bullet states several figures
and then self-checks them with a sum carrying a tick. That tick is an assertion
by the author that the figures agree; nothing verified it, and it drifted
(Plan 00379 N4): the bullet read "365 distinct ... 378 allocated" and closed
with ``364 + 13 = 377. ✅``.

Note what would NOT have caught it. 364 + 13 really is 377, so a rule that only
checks arithmetic validity passes. The defect is that the OPERANDS contradict
figures stated inches above them, which is a cross-reference question.

This is the ONE implementation. ``scripts/qa/check_repo_hygiene.py`` calls
:func:`stats_arithmetic_disagreements` rather than carrying its own copy; it
held the only copy until Plan 00466 N13, which is why a README whose closing
line disagreed with its bullets passed every fast gate and reached main.

Every clause is optional and absence is silence, so a client project's index,
which has no such bullet, reports nothing.

**EDIT advises, never blocks.** Updating the bullet takes more than one edit
and the index is inconsistent between them, so a block would deny the first
half of a correct update. The COMMIT is where the figures must agree, and it
blocks only a commit that stages the index with a disagreement HEAD did not
already carry (``commit_scoped_level``).
"""

import re
from dataclasses import dataclass
from typing import Final

from claude_code_hooks_daemon.plan_qa.checks.common import commit_scoped_level, head_readme_index
from claude_code_hooks_daemon.plan_qa.model import README_FILENAME
from claude_code_hooks_daemon.plan_qa.paths import PlanFileKind, classify
from claude_code_hooks_daemon.plan_qa.types import (
    CheckContext,
    CheckSpec,
    Finding,
    Level,
    Stage,
)

CHECK_ID: Final[str] = "plan-stats-arithmetic"

REMEDIATION: Final[str] = (
    "Recount from disk and correct the reconciliation bullet in the plan index "
    "so every figure in it agrees with the others — do not just adjust whichever "
    "number the message names. The bullet ends in a self-check carrying a tick; "
    "that tick claims the figures were verified, so leaving it above numbers "
    "that disagree is worse than having no check at all."
)

#: `16 + 340 + 13 = **369 folders**` — the three category counts and their total.
_FOLDER_SUM_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(\d+)\s*\+\s*(\d+)\s*\+\s*(\d+)\s*=\s*\*\*([\d,]+)\s+folders\*\*"
)
#: `**366 distinct plan numbers**`
_DISTINCT_PATTERN: Final[re.Pattern[str]] = re.compile(r"\*\*([\d,]+)\s+distinct plan numbers\*\*")
#: `That leaves **13** of the 379 allocated numbers with no folder: 00005, ...`
_FOLDERLESS_PATTERN: Final[re.Pattern[str]] = re.compile(
    # Every inter-word gap is \s+, never a literal space: the bullet is wrapped
    # prose, so any of these gaps can fall on a line break.
    r"leaves\s+\*\*(\d+)\*\*\s+of\s+the\s+([\d,]+)\s+allocated\s+numbers\s+with\s+no\s+folder:"
    r"(.*?)(?:—|--|\n\n)",
    re.DOTALL,
)
#: The closing self-check `366 + 13 = 379.` — two operands, unbolded result.
_CLOSING_SUM_PATTERN: Final[re.Pattern[str]] = re.compile(r"(\d+)\s*\+\s*(\d+)\s*=\s*(\d+)\s*\.")
#: A zero-padded plan number in the folderless list.
_PLAN_NUMBER_PATTERN: Final[re.Pattern[str]] = re.compile(r"\b\d{3,5}\b")


@dataclass(frozen=True)
class StatsDisagreement:
    """One figure in the bullet that disagrees with another.

    ``line`` is 1-based and is also written into ``message``, so every surface
    that prints the message names the line to fix.
    """

    line: int
    message: str


def _as_int(raw: str) -> int:
    """``"1,234"`` → ``1234``; the index writes thousands separators."""
    return int(raw.replace(",", ""))


def _line_of(text: str, match: re.Match[str]) -> int:
    return text.count("\n", 0, match.start()) + 1


def _at(text: str, match: re.Match[str], detail: str) -> StatsDisagreement:
    line = _line_of(text, match)
    return StatsDisagreement(line=line, message=f"line {line}: {detail}")


def stats_arithmetic_disagreements(text: str) -> tuple[StatsDisagreement, ...]:
    """Figures in the reconciliation bullet of ``text`` that disagree with each other.

    Only INTERNAL consistency is checked, so this needs no access to the tree
    or the git counter and cannot go stale against them.
    """
    found: list[StatsDisagreement] = []

    folder_sum = _FOLDER_SUM_PATTERN.search(text)
    if folder_sum is not None:
        parts = [_as_int(folder_sum.group(n)) for n in (1, 2, 3)]
        stated_total = _as_int(folder_sum.group(4))
        if sum(parts) != stated_total:
            joined = " + ".join(str(part) for part in parts)
            found.append(
                _at(
                    text,
                    folder_sum,
                    f"folder sum does not add up: {joined} = {sum(parts)}, "
                    f"but the bullet states {stated_total}",
                )
            )

    distinct_match = _DISTINCT_PATTERN.search(text)
    folderless_match = _FOLDERLESS_PATTERN.search(text)
    if folderless_match is not None:
        stated_folderless = _as_int(folderless_match.group(1))
        listed = _PLAN_NUMBER_PATTERN.findall(folderless_match.group(3))
        if len(listed) != stated_folderless:
            found.append(
                _at(
                    text,
                    folderless_match,
                    f"the bullet states {stated_folderless} folderless numbers "
                    f"but lists {len(listed)}",
                )
            )

    closing = _CLOSING_SUM_PATTERN.search(text)
    if closing is None:
        return tuple(found)
    left, right, total = (_as_int(closing.group(n)) for n in (1, 2, 3))
    if left + right != total:
        found.append(
            _at(
                text,
                closing,
                f"the closing self-check does not add up: {left} + {right} "
                f"= {left + right}, not {total}",
            )
        )
    if distinct_match is not None and left != _as_int(distinct_match.group(1)):
        found.append(
            _at(
                text,
                closing,
                f"the closing self-check starts from {left}, but the bullet "
                f"states {_as_int(distinct_match.group(1))} distinct plan numbers",
            )
        )
    if folderless_match is not None:
        stated_folderless = _as_int(folderless_match.group(1))
        stated_allocated = _as_int(folderless_match.group(2))
        if right != stated_folderless:
            found.append(
                _at(
                    text,
                    closing,
                    f"the closing self-check adds {right}, but the bullet "
                    f"states {stated_folderless} folderless numbers",
                )
            )
        if total != stated_allocated:
            found.append(
                _at(
                    text,
                    closing,
                    f"the closing self-check totals {total}, but the bullet "
                    f"states {stated_allocated} allocated numbers",
                )
            )
    return tuple(found)


def _finding(disagreement: StatsDisagreement, level: Level, rel_path: str) -> Finding:
    return Finding(
        check_id=CHECK_ID,
        level=level,
        message=disagreement.message,
        remediation=REMEDIATION,
        path=rel_path,
    )


def _index_rel_path(context: CheckContext) -> str:
    return f"{context.plan_dir_rel.rstrip('/')}/{README_FILENAME}"


def _commit_stages_the_index(context: CheckContext) -> bool:
    gitfacts = context.gitfacts
    if gitfacts is None:
        return False
    rel_path = _index_rel_path(context)
    return any(change.path == rel_path for change in gitfacts.staged_changes())


def _run_edit(context: CheckContext) -> list[Finding]:
    """Stage 1: the would-be content of a Write/Edit to the plan index."""
    if context.file_path is None or context.file_content is None:
        return []
    classified = classify(context.file_path, context)
    if classified.kind is not PlanFileKind.PLAN_INDEX:
        return []
    return [
        _finding(disagreement, Level.ADVISE, classified.rel_path)
        for disagreement in stats_arithmetic_disagreements(context.file_content)
    ]


def _run_tree(context: CheckContext) -> list[Finding]:
    """Stages 2 and 3: the primary index as it stands.

    Reads ``readme.lines``, not ``rows``: the figures are the primary index's
    own text, and ``rows`` also carries the archive index's rows.
    """
    readme = context.readme
    if readme is None:
        return []
    disagreements = stats_arithmetic_disagreements("\n".join(readme.lines))
    if not disagreements:
        return []

    before_index = head_readme_index(context)
    inherited = (
        {item.message for item in stats_arithmetic_disagreements("\n".join(before_index.lines))}
        if before_index is not None
        else set()
    )
    stages_index = _commit_stages_the_index(context)
    rel_path = _index_rel_path(context)
    return [
        _finding(
            disagreement,
            commit_scoped_level(
                context,
                None,
                pre_existing=not stages_index or disagreement.message in inherited,
            ),
            rel_path,
        )
        for disagreement in disagreements
    ]


CHECKS: Final[tuple[CheckSpec, CheckSpec, CheckSpec]] = (
    # B5, like ``stats-recount``: hand-maintained statistics that drift.
    CheckSpec(check_id=CHECK_ID, stage=Stage.EDIT, level=Level.ADVISE, sins=("B5",), run=_run_edit),
    CheckSpec(
        check_id=CHECK_ID, stage=Stage.COMMIT, level=Level.BLOCK, sins=("B5",), run=_run_tree
    ),
    CheckSpec(check_id=CHECK_ID, stage=Stage.SWEEP, level=Level.BLOCK, sins=("B5",), run=_run_tree),
)
