#!/usr/bin/env python3
"""Fail when a recorded verdict stops describing what the daemon actually does.

The class -- `outcome-reachable-by-an-unenumerated-spelling` -- is a dangerous
outcome reachable by a command, flag or shell construct that no guard's pattern
names. Two causes, one Detector: a guard that enumerates a tool whose
subcommand set is open (`git checkout -f` beside a handler that names
`checkout --`), and an outcome no guard judges at all (`rm -rf`). Whether a row
is uncovered because a pattern is short or because nothing exists is a fact
this reports, not a reason for two Detectors.

**Both passes, not just `matches()`.** F-GAP measured that
`verification_result_gate` matches almost every git command and then allows it,
so a matches()-only method scores 24 git candidates as covered while nothing
denies them. This asks the real chain for a DECISION.

**In-process, not a subprocess.** The guard judges a command string wherever it
appears -- including inside a probe's own payload -- so a shell-borne probe is
denied before it can run. That is the guard working correctly, and it is also
why this builds the configured chain in this process instead.

**The verdict is held in BOTH directions.** A `COVERED` row that stops being
denied is a guard regression. An `UNCOVERED` row that starts being denied fails
too: the good news still has to be recorded, because the next person uses this
file to decide what is worth building, and a corpus that keeps claiming a
closed gap sends them at work already done.

**The blind spot is the price and belongs in the category**: the corpus only
covers what someone thought to add. It converts an invisible gap into a visible
list; it does not generate the list. That makes this Detector weaker than
classes 1, 5 or 7, and it must be described that way rather than as coverage.

Usage:
    python scripts/qa/check_dangerous_invocation_corpus.py [--json] [--corpus F]

Exit codes:
    0 -- every recorded verdict still holds
    1 -- a verdict has gone stale in either direction, or a row is incomplete
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QA_OUTPUT_DIR: Final[Path] = _REPO_ROOT / "untracked" / "qa"
_ARTEFACT_NAME: Final[str] = "dangerous_invocation_corpus.json"
_OUTPUT_FILE: Final[Path] = _QA_OUTPUT_DIR / _ARTEFACT_NAME
_DEFAULT_CORPUS: Final[Path] = _REPO_ROOT / "scripts" / "qa" / "dangerous-invocation-corpus.yaml"

_RULE: Final[str] = "dangerous-invocation-corpus"

_COVERED: Final[str] = "COVERED"
_UNCOVERED_ACCEPTED: Final[str] = "UNCOVERED-accepted"
_UNCOVERED_OPEN: Final[str] = "UNCOVERED-open"
#: `accepted` and `open` differ in INTENT, not in what the chain does. Keeping
#: them apart here is what lets the distinction stay about whether anyone has
#: decided, rather than leaking into what the gate enforces.
_UNCOVERED: Final[frozenset[str]] = frozenset({_UNCOVERED_ACCEPTED, _UNCOVERED_OPEN})
_VERDICTS: Final[frozenset[str]] = _UNCOVERED | {_COVERED}

#: Returns (denied, deciding-handler-name) for one command string.
VerdictFn = Callable[[str], "tuple[bool, str]"]

_REMEDIATION: Final[str] = (
    "A recorded verdict no longer describes what the daemon does.\n"
    "\n"
    "If a COVERED row is now allowed, a guard has regressed -- find what\n"
    "changed before touching the row. The row is a statement about what the\n"
    "daemon should do, written by someone who ran it; editing it to match the\n"
    "code inverts that.\n"
    "\n"
    "If an UNCOVERED row is now denied, that is good news and still has to be\n"
    "recorded: change the row to COVERED and say in its note which handler\n"
    "closed it. A corpus that keeps claiming a closed gap sends the next\n"
    "reader at work that is already done.\n"
    "\n"
    "To record a gap nobody intends to close, use UNCOVERED-accepted and give\n"
    "the reason in the note. Several rows here are accepted deliberately --\n"
    "the worklist reports `git rebase` and a broad `npm install` deny as too\n"
    "noisy to ship, and a rule that is switched off protects nothing."
)


@dataclass(frozen=True)
class Violation:
    row_id: str
    command: str
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "rule": _RULE,
            "row": self.row_id,
            "command": self.command,
            "detail": self.detail,
        }


def load_corpus(corpus_path: Path) -> list[dict[str, object]]:
    raw = yaml.safe_load(corpus_path.read_text(encoding="utf-8")) or {}
    rows = raw.get("rows") or []
    return [row for row in rows if isinstance(row, dict)]


def _text(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    return "" if value is None else str(value).strip()


def real_chain_verdict() -> VerdictFn:
    """Build the project's REAL configured chain and return a verdict function.

    Deliberately the configured set rather than the defaults: a corpus scored
    against default-enabled handlers would describe a daemon nobody runs.
    """
    from claude_code_hooks_daemon.config.loader import ConfigLoader
    from claude_code_hooks_daemon.config.models import Config
    from claude_code_hooks_daemon.core.event import EventType
    from claude_code_hooks_daemon.core.hook_result import Decision
    from claude_code_hooks_daemon.core.project_context import ProjectContext
    from claude_code_hooks_daemon.core.router import EventRouter
    from claude_code_hooks_daemon.daemon.cli import _build_handler_config_mapping
    from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

    config_path = _REPO_ROOT / ".claude" / "hooks-daemon.yaml"
    if not ProjectContext.is_initialized():
        ProjectContext.initialize(config_path)
    config = Config.model_validate(ConfigLoader.load(config_path))
    router = EventRouter()
    registry = HandlerRegistry()
    registry.discover()
    registry.register_all(
        router,
        config=_build_handler_config_mapping(config),
        workspace_root=_REPO_ROOT,
        project_languages=config.daemon.languages,
        project_exclude_paths=config.daemon.exclude_paths,
        plan_workflow=config.plan_workflow,
        documentation=config.documentation,
    )

    def verdict(command: str) -> tuple[bool, str]:
        outcome = router.route(
            EventType.PRE_TOOL_USE,
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": command},
                "session_id": "dangerous-invocation-corpus",
                "cwd": str(_REPO_ROOT),
            },
        )
        return outcome.result.decision is not Decision.ALLOW, outcome.decided_by or ""

    return verdict


def _row_shape_violations(rows: list[dict[str, object]]) -> list[Violation]:
    """Problems visible without asking the chain anything."""
    violations: list[Violation] = []
    seen: Counter[str] = Counter()
    for row in rows:
        row_id = _text(row, "id") or "<no id>"
        command = _text(row, "command")
        seen[row_id] += 1
        if not command:
            violations.append(Violation(row_id, command, "row has no command to judge"))
        if _text(row, "verdict") not in _VERDICTS:
            violations.append(
                Violation(
                    row_id,
                    command,
                    f"verdict must be one of {sorted(_VERDICTS)}, "
                    f"not {_text(row, 'verdict')!r}",
                )
            )
        if not _text(row, "note"):
            violations.append(
                Violation(
                    row_id, command, "row needs a note; an unexplained row cannot be reviewed"
                )
            )
    violations.extend(
        Violation(row_id, "", f"duplicate row id used {count} times")
        for row_id, count in seen.items()
        if count > 1
    )
    return violations


def scan(corpus_path: Path, verdict: VerdictFn) -> list[Violation]:
    """Every row whose recorded verdict no longer describes the chain."""
    rows = load_corpus(corpus_path)
    violations = _row_shape_violations(rows)
    unusable = {v.row_id for v in violations}

    for row in rows:
        row_id = _text(row, "id") or "<no id>"
        if row_id in unusable:
            continue
        command = _text(row, "command")
        recorded = _text(row, "verdict")
        denied, decided_by = verdict(command)

        if recorded == _COVERED and not denied:
            violations.append(
                Violation(
                    row_id,
                    command,
                    "recorded COVERED but the chain no longer denies it -- a guard has "
                    "regressed, or the row was never true",
                )
            )
        elif recorded in _UNCOVERED and denied:
            violations.append(
                Violation(
                    row_id,
                    command,
                    f"recorded {recorded} but the chain now denies it "
                    f"(via {decided_by or 'an unnamed handler'}) -- record the good news",
                )
            )
    return violations


def count_rows(corpus_path: Path) -> dict[str, int]:
    """The denominator, split by verdict: what a clean run actually checked.

    ``rows_checked`` carries the suffix the repo-wide denominator audit looks
    for, and it is the more accurate name in any case: it counts rows driven
    through the chain, not rows present in the file. A corpus that failed to
    load would otherwise report zero violations and look clean.
    """
    rows = load_corpus(corpus_path)
    verdicts = Counter(_text(row, "verdict") for row in rows)
    return {
        "rows_checked": len(rows),
        "covered": verdicts[_COVERED],
        "uncovered_accepted": verdicts[_UNCOVERED_ACCEPTED],
        "uncovered_open": verdicts[_UNCOVERED_OPEN],
    }


def main() -> int:
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0

    json_mode = "--json" in args
    corpus_path = _DEFAULT_CORPUS
    for index, arg in enumerate(args):
        if arg == "--corpus" and index + 1 < len(args):
            corpus_path = Path(args[index + 1]).resolve()

    violations = scan(corpus_path, real_chain_verdict())
    counts = count_rows(corpus_path)

    # Keys are spelled out rather than spread from `counts`: the repo-wide
    # denominator audit reads this literal STATICALLY, and a `**counts` spread
    # tells it nothing. That is the audit being right -- a reader cannot see
    # what a spread contributes either.
    output = {
        "tool": "dangerous_invocation_corpus",
        "summary": {
            "passed": len(violations) == 0,
            "total_violations": len(violations),
            "rows_checked": counts["rows_checked"],
            "covered": counts["covered"],
            "uncovered_open": counts["uncovered_open"],
            "uncovered_accepted": counts["uncovered_accepted"],
        },
        "violations": [violation.to_dict() for violation in violations],
    }

    if json_mode:
        # This check's verdict is ABOUT the corpus it was given, so a run
        # against another corpus establishes nothing about the one the
        # repository artefact is read as describing — and llm_qa publishes that
        # artefact as this check's evidence. Report beside the corpus that was
        # actually checked (Plan 00432).
        output_file = (
            corpus_path.parent / _ARTEFACT_NAME if corpus_path != _DEFAULT_CORPUS else _OUTPUT_FILE
        )
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(output, indent=2))

    if violations:
        print(
            f"Found {len(violations)} stale verdict(s) across "
            f"{counts['rows_checked']} corpus rows:"
        )
        for violation in violations:
            print(f"  {violation.row_id}: {violation.command}")
            print(f"      {violation.detail}")
        print(f"\n{_REMEDIATION}")
    else:
        print(
            f"Every recorded verdict holds ({counts['rows_checked']} rows: "
            f"{counts['covered']} covered, {counts['uncovered_open']} open, "
            f"{counts['uncovered_accepted']} accepted)"
        )

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
