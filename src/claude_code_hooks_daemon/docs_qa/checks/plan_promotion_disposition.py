"""Check ``plan-promotion-disposition`` (STAGED only, never blocks; R8).

R8 — "Plan folders are a drafting ground, not a home": at terminal-status
flip, every supporting doc in the plan folder gets an explicit disposition
recorded in the closing journal entry (promote / historical / delete).
This check is a deliberately WEAK mechanical approximation: a staged
terminal-status flip of a ``PLAN.md`` whose folder has supporting docs
(non-``PLAN.md``, non-``JOURNAL/`` ``.md`` files) is flagged advisory when
the staged closing journal entry mentions none of the three disposition
words. False negatives are expected and fine (a real disposition sentence
that avoids these exact words is missed); false positives are the thing to
avoid, hence a plain keyword scan rather than any attempt at real prose
understanding.

Minimal LOCAL terminal-status and folder detection (no ``plan_qa`` import):
docs_qa deliberately stays decoupled from plan_qa's typed ``PlanDoc``
parser — this check only needs a status regex and a folder listing, not
the plan system's full document model.

STAGED only, like ``rules-file-orphan-shrink``: "does the folder have
undispositioned supporting docs" is a cross-file, whole-plan-folder
question that only makes sense at the commit that performs the flip.
"""

import re
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.docs_qa.types import (
    CheckContext,
    CheckSpec,
    CheckStage,
    Finding,
    Severity,
)

CHECK_ID: Final[str] = "plan-promotion-disposition"

_PLAN_DOC_FILENAME: Final[str] = "PLAN.md"
_JOURNAL_DIR_NAME: Final[str] = "JOURNAL"
_MARKDOWN_SUFFIX: Final[str] = ".md"

_STATUS_RE: Final[re.Pattern[str]] = re.compile(
    r"\*\*Status\*\*:\s*(Complete|Cancelled|Superseded)\b", re.IGNORECASE
)
_DISPOSITION_KEYWORDS: Final[tuple[str, ...]] = ("promote", "historical", "delete")


def _is_terminal_flip(content: str) -> bool:
    return bool(_STATUS_RE.search(content))


def _supporting_docs(folder_abs: Path) -> list[str]:
    if not folder_abs.is_dir():
        return []
    docs: list[str] = []
    for entry in sorted(folder_abs.iterdir()):
        if not entry.is_file() or entry.suffix != _MARKDOWN_SUFFIX:
            continue
        if entry.name == _PLAN_DOC_FILENAME:
            continue
        docs.append(entry.name)
    return docs


def _finding(rel_path: str, folder: str, supporting_docs: list[str]) -> Finding:
    doc_list = ", ".join(f"`{name}`" for name in supporting_docs)
    return Finding(
        check_id=CHECK_ID,
        severity=Severity.ADVISE,
        message=(
            f"`{rel_path}` flips to a terminal status, and `{folder}` has "
            f"supporting doc(s) with no disposition mentioned in the staged "
            f"closing journal entry: {doc_list}."
        ),
        remediation=(
            "Per R8, record an explicit disposition for each supporting doc "
            "in the closing journal entry: PROMOTE (canonical content moves "
            "into the doc trees, a stub pointer stays behind), HISTORICAL "
            "(the default for dated snapshots -- archive immutability "
            "applies, never retro-edited), or DELETE."
        ),
        path=rel_path,
    )


def _run_staged(context: CheckContext) -> list[Finding]:
    if context.staged_documents is None:
        return []

    findings: list[Finding] = []
    for rel_path, content in sorted(context.staged_documents.items()):
        if not rel_path.endswith(f"/{_PLAN_DOC_FILENAME}"):
            continue
        if not _is_terminal_flip(content):
            continue

        folder = rel_path[: -len(f"/{_PLAN_DOC_FILENAME}")]
        supporting_docs = _supporting_docs(context.project_root / folder)
        if not supporting_docs:
            continue

        journal_prefix = f"{folder}/{_JOURNAL_DIR_NAME}/"
        journal_text = "\n".join(
            staged_content
            for staged_rel_path, staged_content in context.staged_documents.items()
            if staged_rel_path.startswith(journal_prefix)
        ).lower()
        if any(keyword in journal_text for keyword in _DISPOSITION_KEYWORDS):
            continue

        findings.append(_finding(rel_path, folder, supporting_docs))
    return findings


CHECKS: Final[tuple[CheckSpec, ...]] = (
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.STAGED, run=_run_staged),
)
