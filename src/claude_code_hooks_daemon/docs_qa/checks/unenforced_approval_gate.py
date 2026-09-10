"""Check ``unenforced-approval-gate`` (EDIT + STAGED + SWEEP; Plan 00367).

A DAEMON-owned core document (``install/templates/core/*.core.md``, deployed
verbatim as ``<agent tree>/core/*.core.md`` into every project including
this one) is the daemon's statement of its intended workflow. When such a document tells an agent to obtain a
human's approval and the daemon has no gate that enforces it, the agent
either stalls finished work on a human who never asked for the gate, or
learns to ignore the document. The originating instance told every agent to
ask for approval before marking a plan complete while every daemon gate
(holding-area criterion, terminal-placement hint, archive atomicity, the
supervisor's "work until complete" goal) drove it straight through.

The rule: a line in a core template that prescribes a human approval gate
must sit in a paragraph that names, in backticks, a daemon config key that
exists (``plan_workflow.close_requires_human_approval``). The gate is then
enforced, configurable, and documented in one place. A negated mention ("no
approval needed") and a review VERDICT ("report approved") are not gates.

Block-eligible for an instruction NEW in the edit or commit (mirroring
``pointer-resolves``); a pre-existing instance advises, and the sweep counts
every instance as advisory.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Final

from claude_code_hooks_daemon.docs_qa.types import (
    CheckContext,
    CheckSpec,
    CheckStage,
    Finding,
    Severity,
)

CHECK_ID: Final[str] = "unenforced-approval-gate"

# The daemon-owned core documents live at ``<agent tree>/core/*.core.md``:
# the deployed, byte-identical copies of ``install/templates/core/`` (the
# templates themselves sit under ``src/`` and are outside the doc corpus).
# In the daemon's own checkout the copy IS the template's mirror, so a
# commit that stages it is the commit gate for the template; in a client
# the copy is refreshed on every deploy, so a clean daemon ships no finding.
_CORE_DIR_NAME: Final[str] = "core"
_CORE_DOC_SUFFIX: Final[str] = ".core.md"

_HUMAN: Final[str] = r"(?:human|user|owner|stakeholder)s?'?s?"
_APPROVAL: Final[str] = r"(?:approval|authori[sz]ation|sign-?off)"
_GATE_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"""
    \b(?:ask(?:ed|s)?|get|obtain|request|require[sd]?|need(?:s|ed)?|wait(?:s|ed)?\s+for|seek)\b
        [^.\n]{{0,40}}?\b{_HUMAN}\b[^.\n]{{0,25}}?\b{_APPROVAL}\b
    | \b{_HUMAN}\s+for\s+(?:final\s+)?{_APPROVAL}\b
    | \b{_HUMAN}\s+{_APPROVAL}\b[^.\n]{{0,20}}?\b(?:required|needed|mandatory|first)\b
    | \b(?:requires?|needs?)\s+(?:human\s+|user\s+|owner\s+)?{_APPROVAL}\b
    | \bMUST\s+ask\s+(?:the\s+)?{_HUMAN}\b
    """,
    re.IGNORECASE | re.VERBOSE,
)
# A line that says the gate does NOT apply is not an instruction to stop.
_NEGATION_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"""
    \b(?:no|without|needs?\s+no|never)\b[^.\n]{{0,15}}?\b{_APPROVAL}\b
    | \b{_APPROVAL}\b[^.\n]{{0,12}}?\b(?:not|never)\s+(?:required|needed)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)
_CONFIG_KEY_PATTERN: Final[re.Pattern[str]] = re.compile(r"`([a-z_]+(?:\.[a-z_]+)+)(?::\s*\S+)?`")


def config_key_exists(dotted: str) -> bool:
    """True when ``dotted`` names a field path in the daemon's config model.

    Imported lazily: this package stays pydantic-decoupled everywhere else,
    and the model is only needed to answer this one question.
    """
    from claude_code_hooks_daemon.config.models import Config

    model: type[object] = Config
    for part in dotted.split("."):
        fields = getattr(model, "model_fields", None)
        if fields is None or part not in fields:
            return False
        annotation = fields[part].annotation
        if annotation is None:
            return False
        model = annotation
    return True


# Indirection so tests can pin the key set without the real config model.
_key_exists: Callable[[str], bool] = config_key_exists


def _is_core_doc(rel_path: str, agent_tree: str) -> bool:
    parts = tuple(rel_path.replace("\\", "/").split("/"))
    return (
        len(parts) == 3
        and parts[0] == agent_tree
        and parts[1] == _CORE_DIR_NAME
        and parts[2].endswith(_CORE_DOC_SUFFIX)
    )


def _paragraph(lines: list[str], index: int) -> str:
    start = index
    while start > 0 and lines[start - 1].strip():
        start -= 1
    end = index
    while end + 1 < len(lines) and lines[end + 1].strip():
        end += 1
    return "\n".join(lines[start : end + 1])


def _gate_lines(content: str) -> list[tuple[int, str, str | None]]:
    """``(line_number, line, unknown_key)`` for every unenforced gate.

    ``unknown_key`` is the cited key when one is present but does not exist
    in the daemon's config; ``None`` when no key is cited at all.
    """
    lines = content.splitlines()
    hits: list[tuple[int, str, str | None]] = []
    for index, line in enumerate(lines):
        if _NEGATION_PATTERN.search(line) or not _GATE_PATTERN.search(line):
            continue
        cited = _CONFIG_KEY_PATTERN.findall(_paragraph(lines, index))
        if any(_key_exists(key) for key in cited):
            continue
        hits.append((index + 1, line.strip(), cited[0] if cited else None))
    return hits


def _finding(
    rel_path: str, line_number: int, unknown_key: str | None, severity: Severity
) -> Finding:
    if unknown_key is None:
        what = "asks for human approval with no daemon config key governing the gate"
    else:
        what = f"asks for human approval citing `{unknown_key}`, which is not a daemon config key"
    return Finding(
        check_id=CHECK_ID,
        severity=severity,
        message=f"`{rel_path}:{line_number}` {what}",
        remediation=(
            "A daemon-owned core document may not prescribe a human gate the daemon "
            "does not enforce. Put the gate behind a config key, name that key in "
            "backticks in the same paragraph (e.g. "
            "`plan_workflow.close_requires_human_approval`), or delete the instruction."
        ),
        path=rel_path,
    )


def _findings_for(
    rel_path: str, content: str, before: str | None, *, block_new: bool
) -> list[Finding]:
    before_lines = {line.strip() for line in before.splitlines()} if before else set()
    findings: list[Finding] = []
    for line_number, line, unknown_key in _gate_lines(content):
        is_new = line not in before_lines
        severity = Severity.BLOCK if (block_new and is_new) else Severity.ADVISE
        findings.append(_finding(rel_path, line_number, unknown_key, severity))
    return findings


def _run_edit(context: CheckContext) -> list[Finding]:
    if context.file_path is None or context.file_content is None:
        return []
    rel_path = str(context.file_path.relative_to(context.project_root))
    if not _is_core_doc(rel_path, context.policy.trees.agent):
        return []
    return _findings_for(
        rel_path, context.file_content, context.file_content_before, block_new=True
    )


def _run_staged(context: CheckContext) -> list[Finding]:
    if context.staged_documents is None or context.gitfacts is None:
        return []
    findings: list[Finding] = []
    for rel_path, content in sorted(context.staged_documents.items()):
        if not _is_core_doc(rel_path, context.policy.trees.agent):
            continue
        head = context.gitfacts.head_file_text(rel_path)
        findings.extend(_findings_for(rel_path, content, head, block_new=True))
    return findings


def _run_sweep(context: CheckContext) -> list[Finding]:
    if context.corpus is None:
        return []
    findings: list[Finding] = []
    for rel_path in sorted(context.corpus.documents):
        if not _is_core_doc(rel_path, context.policy.trees.agent):
            continue
        try:
            content = (context.project_root / rel_path).read_text(encoding="utf-8")
        except OSError:
            continue
        findings.extend(_findings_for(rel_path, content, None, block_new=False))
    return findings


CHECKS: Final[tuple[CheckSpec, CheckSpec, CheckSpec]] = (
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.EDIT, run=_run_edit),
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.STAGED, run=_run_staged),
    CheckSpec(check_id=CHECK_ID, stage=CheckStage.SWEEP, run=_run_sweep),
)
