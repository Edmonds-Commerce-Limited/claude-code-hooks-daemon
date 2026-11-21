"""Check ``untracked-evidence-citation`` (EDIT; Plan 00627, Task 7.3).

A tracked document that cites a file under ``untracked/`` as its evidence
points at something that expires: scratch is swept after its TTL, and other
untracked trees are never reviewed or shared. The citation outlives the file
and resolves to nothing.

The check flags a markdown line that is NEW in this edit (absent from the
content before it), sits outside a fenced code block, names a FILE under
``untracked/`` (a path with an extension; a bare directory such as
``untracked/scratch/`` is an instruction, not evidence) and carries an
evidence word. It is a keyword approximation, so its severity is ADVISE and it
can never block.
"""

import re
from typing import Final

from claude_code_hooks_daemon.docs_qa.types import (
    CheckContext,
    CheckSpec,
    CheckStage,
    Finding,
    Severity,
)
from claude_code_hooks_daemon.utils.path_containment import path_relative_to

CHECK_ID: Final[str] = "untracked-evidence-citation"
STATEMENT: Final[str] = (
    "A tracked doc must not cite an untracked file as evidence. Copy the figures in, or file the artefact."
)

_MARKDOWN_SUFFIX: Final[str] = ".md"
_FENCE: Final[str] = "```"
_UNTRACKED_PREFIX: Final[str] = "untracked/"

_UNTRACKED_FILE: Final[re.Pattern[str]] = re.compile(
    r"(?<![\w./-])untracked/[\w./-]*?[\w-]\.[A-Za-z0-9]+\b"
)
_EVIDENCE_WORD: Final[re.Pattern[str]] = re.compile(
    r"\b(evidence|source|measured|measurements?|findings?|results?|verified|proof)\b",
    re.IGNORECASE,
)

_REMEDY: Final[str] = (
    "Untracked files expire (scratch is swept after 24 hours by default) and are never reviewed, so the "
    "citation will resolve to nothing. Copy the figures the claim rests on into this document, "
    "or file the artefact into the plan folder (`subagent-reports/`) and cite that path."
)


def _new_lines(content: str, before: str | None) -> list[tuple[int, str]]:
    previous = set(before.splitlines()) if before is not None else set()
    in_fence = False
    lines: list[tuple[int, str]] = []
    for number, line in enumerate(content.splitlines(), start=1):
        if line.lstrip().startswith(_FENCE):
            in_fence = not in_fence
            continue
        if in_fence or line in previous:
            continue
        lines.append((number, line))
    return lines


def _run_edit(context: CheckContext) -> list[Finding]:
    if context.file_path is None or context.file_content is None:
        return []
    if context.file_path.suffix != _MARKDOWN_SUFFIX:
        return []
    rel_path = path_relative_to(context.file_path, context.project_root).as_posix()
    if rel_path.startswith(_UNTRACKED_PREFIX):
        return []
    findings: list[Finding] = []
    for number, line in _new_lines(context.file_content, context.file_content_before):
        if not _EVIDENCE_WORD.search(line):
            continue
        for match in _UNTRACKED_FILE.finditer(line):
            findings.append(
                Finding(
                    check_id=CHECK_ID,
                    severity=Severity.ADVISE,
                    message=(
                        f"`{rel_path}` line {number} cites `{match.group(0)}` as evidence, "
                        "but that file is untracked."
                    ),
                    remediation=_REMEDY,
                    path=rel_path,
                )
            )
    return findings


CHECKS: Final[tuple[CheckSpec, ...]] = (
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.EDIT, run=_run_edit),
)
