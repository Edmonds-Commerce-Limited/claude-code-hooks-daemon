"""Plan 00200 Task 6.2 — prose claims must agree with generated truth.

DBF (``CLAUDE.md`` Core Standard 15). Two handlers were described in
``README.md`` as doing the **opposite** of what they do:

- ``:86`` "Absolute path enforcer — Prevents absolute paths in tool calls". It
  *requires* them (``handlers/pre_tool_use/absolute_path.py:44`` returns
  ``not file_path.startswith("/")``).
- ``:98`` "Daemon restart verifier — Blocks commits if the daemon cannot
  restart cleanly". It is advisory: ``daemon_restart_verifier.py:42`` sets
  ``terminal=False`` and ``:101`` returns ``Decision.ALLOW``.

Neither survives a spot-check, which makes them the cheapest possible
credibility loss. The guard that should have caught them did not exist — yet
the ground truth did: ``.claude/HOOKS-DAEMON.md`` is generated from live config
by ``generate-docs`` and simply had no consumer.

Scope is deliberately narrow (the brief's own framing): a full NLP
claim-checker is not the goal. Three mechanically decidable rules only —
referenced handlers exist, blocking/advisory claims match the generated
Behavior column, and enumerated counts match the registry. Everything softer
stays a human review task; a gate that guesses gets switched off.

``qa-check-count-hardcoded`` is the inverse case: there is no generated ground
truth for how many QA checks exist, so the fix is to stop asserting a number
rather than to assert a better one.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "scripts" / "qa" / "check_doc_truth.py"
_TIMEOUT_SECONDS = 60

_GENERATED_DOC = """# Hooks Daemon - Active Configuration

## Active Handlers

### PreToolUse (2 handlers)

| Priority | Handler | Behavior | Description |
|----------|---------|----------|-------------|
| 10 | some_blocker | BLOCKING | Block dangerous things |
| 23 | some_advisor | ADVISORY | Advise about things |

### SessionStart (1 handler)

| Priority | Handler | Behavior | Description |
|----------|---------|----------|-------------|
| 10 | some_session_thing | ADVISORY | Notice something at session start |
"""


def _run_checker(root: Path) -> tuple[int, dict]:
    result = subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(root), "--report-stdout"],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.stdout, f"checker produced no report. stderr: {result.stderr[:500]}"
    return result.returncode, json.loads(result.stdout)


def _make_docs(tmp_path: Path, readme: str) -> Path:
    """Build a fixture tree with generated truth plus a README to check."""
    root = tmp_path / "fixture"
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "HOOKS-DAEMON.md").write_text(_GENERATED_DOC, encoding="utf-8")
    (root / "README.md").write_text(readme, encoding="utf-8")
    return root


def _rules(report: dict) -> set[str]:
    return {v["rule"] for v in report["violations"]}


def test_flags_blocking_claim_about_an_advisory_handler(tmp_path: Path) -> None:
    """The ``daemon_restart_verifier`` class: prose claims it blocks; it advises."""
    root = _make_docs(
        tmp_path,
        "## What's Built In\n\n"
        "The daemon ships with 3 production handlers across 2 event types:\n\n"
        "- **Some advisor** (`some_advisor`) — Blocks commits when things are wrong\n",
    )

    exit_code, report = _run_checker(root)

    assert exit_code == 1, "a blocking claim about an ADVISORY handler must fail"
    assert "handler-claim-mismatch" in _rules(report)


def test_flags_reference_to_a_handler_that_does_not_exist(tmp_path: Path) -> None:
    """A renamed or deleted handler leaves prose pointing at nothing."""
    root = _make_docs(
        tmp_path,
        "## What's Built In\n\n"
        "The daemon ships with 3 production handlers across 2 event types:\n\n"
        "- **Ghost** (`handler_that_was_deleted`) — Blocks things\n",
    )

    exit_code, report = _run_checker(root)

    assert exit_code == 1
    assert "handler-ref-unknown" in _rules(report)


def test_flags_handler_count_drift(tmp_path: Path) -> None:
    """Counts have generated ground truth, so they are asserted, not banned."""
    root = _make_docs(
        tmp_path,
        "## What's Built In\n\n"
        "The daemon ships with 92 production handlers across 15 event types:\n",
    )

    exit_code, report = _run_checker(root)

    assert exit_code == 1, "a stale handler count must fail"
    assert "handler-count-drift" in _rules(report)
    message = " ".join(v["message"] for v in report["violations"])
    assert "3" in message and "2" in message, f"the finding must name the real counts: {message}"


def test_flags_hardcoded_qa_check_count(tmp_path: Path) -> None:
    """No generated truth exists for the QA suite size, so asserting one drifts.

    ``CLAUDE.md`` claimed "ALL 10 checks" while the suite ran 13.
    """
    root = _make_docs(
        tmp_path,
        "## What's Built In\n\n"
        "The daemon ships with 3 production handlers across 2 event types:\n\n"
        "Run the suite and confirm ALL 10 checks pass before committing.\n",
    )

    exit_code, report = _run_checker(root)

    assert exit_code == 1
    assert "qa-check-count-hardcoded" in _rules(report)


def test_accurate_prose_passes(tmp_path: Path) -> None:
    """NEGATIVE CONTROL — the check must discriminate, not merely fire.

    Correct counts, a real handler and a matching behaviour claim must produce
    zero findings. Without this, a checker that flagged everything would
    satisfy all four positive cases above while being useless.
    """
    root = _make_docs(
        tmp_path,
        "## What's Built In\n\n"
        "The daemon ships with 3 production handlers across 2 event types:\n\n"
        "- **Some blocker** (`some_blocker`) — Blocks dangerous things\n"
        "- **Some advisor** (`some_advisor`) — Advises about things\n",
    )

    exit_code, report = _run_checker(root)

    assert exit_code == 0, f"accurate prose was flagged: {report['violations']}"
    assert report["violations"] == []


def test_real_repository_docs_are_truthful() -> None:
    """The gate itself: this repository's prose must match generated truth."""
    exit_code, report = _run_checker(REPO_ROOT)

    assert exit_code == 0, "Doc claims contradict generated truth:\n" + "\n".join(
        f"  [{v['rule']}] {v['file']}:{v['line']}: {v['message']}" for v in report["violations"]
    )
