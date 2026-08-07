"""Plan 00200 Tasks 6.1 + 6.3 — the tracked tree must stay free of detritus.

DBF (``CLAUDE.md`` Core Standard 15): the defect is not that ``coverage.json``
(1,464,897 bytes, stale from v2.16.0) and ``.claude/settings.json.bak`` were
committed — it is that **nothing could see them**. ``coverage.xml``,
``htmlcov/`` and ``.coverage`` were all gitignored; ``coverage.json`` simply
leaked through the gap and no batch check existed to notice.

The corollary in that standard applies directly: a write-time PreToolUse
handler cannot cover what is already on disk, so this must be a batch check
over the **tracked** tree. ``git ls-files`` is the ground truth — an untracked
``coverage.json`` in a working tree is normal and must NOT be flagged.

These tests drive the checker against synthesised git repos so each rule is
proved in isolation, then assert the real repository is clean. The synthesised
cases are what stop the real-repo assertion from being vacuous: a checker that
found nothing anywhere would satisfy it just as well.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "scripts" / "qa" / "check_repo_hygiene.py"
_TIMEOUT_SECONDS = 60


def _run_checker(root: Path) -> tuple[int, dict]:
    """Run the checker against ``root``, returning (exit code, parsed report)."""
    result = subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(root), "--report-stdout"],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.stdout, f"checker produced no report. stderr: {result.stderr[:500]}"
    return result.returncode, json.loads(result.stdout)


def _make_repo(tmp_path: Path, tracked: dict[str, str]) -> Path:
    """Create a git repo whose index contains exactly ``tracked``."""
    repo = tmp_path / "fixture"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, timeout=_TIMEOUT_SECONDS)
    for rel, content in tracked.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", "-f", rel], cwd=repo, check=True, timeout=_TIMEOUT_SECONDS)
    return repo


def _rules(report: dict) -> set[str]:
    return {v["rule"] for v in report["violations"]}


def _paths(report: dict) -> set[str]:
    return {v["path"] for v in report["violations"]}


def test_flags_tracked_coverage_artifact(tmp_path: Path) -> None:
    """A tracked ``coverage.json`` is the exact artifact that leaked through."""
    repo = _make_repo(tmp_path, {"coverage.json": "{}", "README.md": "# ok\n"})

    exit_code, report = _run_checker(repo)

    assert exit_code == 1, "a tracked build artifact must fail the gate"
    assert "tracked-build-artifact" in _rules(report)
    assert "coverage.json" in _paths(report)


def test_flags_tracked_backup_file(tmp_path: Path) -> None:
    """``.bak`` detritus is tracked-able today and must be caught.

    The daemon itself writes ``settings.json.bak.pre-registration-repair`` at
    runtime (``utils/settings_repair.py:34``), so this shape appears in real
    working trees and must never reach the index.
    """
    repo = _make_repo(
        tmp_path,
        {
            ".claude/settings.json.bak": "{}",
            ".claude/settings.json.bak.pre-registration-repair": "{}",
        },
    )

    exit_code, report = _run_checker(repo)

    assert exit_code == 1
    assert "tracked-build-artifact" in _rules(report)
    assert ".claude/settings.json.bak" in _paths(report)
    assert ".claude/settings.json.bak.pre-registration-repair" in _paths(report), (
        "the daemon's own runtime backup suffix must be caught too — it is the "
        "shape most likely to be swept in by a later `git add -A`"
    )


def test_flags_test_script_stranded_at_repo_root(tmp_path: Path) -> None:
    """A ``test_*.sh`` at the repo root has no owning context."""
    repo = _make_repo(
        tmp_path,
        {"test_forwarders.sh": "#!/bin/bash\n", "README.md": "# ok\n"},
    )

    exit_code, report = _run_checker(repo)

    assert exit_code == 1
    assert "root-test-script" in _rules(report)
    assert "test_forwarders.sh" in _paths(report)


def test_flags_frozen_session_summary_document(tmp_path: Path) -> None:
    """A tracked doc that is unedited agent session output.

    DBF: ``validate_instruction_content`` already blocks this material at write
    time — but only for ``CLAUDE.md`` and ``README.md``, and only for the write
    that is happening now. Two such documents (``CLAUDE/AGENT_TEAM_EXECUTION_
    STATUS.md``, ``CLAUDE/TDD_RESPONSE_VALIDATION_SUMMARY.md``) sat tracked at
    the top of ``CLAUDE/`` for months, one advertising 13 failing tests in its
    header. Neither was reachable by that handler. This is its batch half.
    """
    repo = _make_repo(
        tmp_path,
        {
            "CLAUDE/SUMMARY.md": "# Work\n\n## Mission Accomplished\n\nWe built it.\n",
            "README.md": "# ok\n",
        },
    )

    exit_code, report = _run_checker(repo)

    assert exit_code == 1
    assert "frozen-session-summary" in _rules(report)
    assert "CLAUDE/SUMMARY.md" in _paths(report)


def test_flags_frozen_summary_reporting_failing_tests(tmp_path: Path) -> None:
    """A frozen pass/fail tally is the most damaging shape of this class."""
    repo = _make_repo(
        tmp_path,
        {"docs/NOTES.md": "**Test Results**: 1429 PASSING / 13 FAILING\n"},
    )

    exit_code, report = _run_checker(repo)

    assert exit_code == 1
    assert "frozen-session-summary" in _rules(report)


def test_does_not_flag_session_summary_markers_inside_plan_or_journal(tmp_path: Path) -> None:
    """NEGATIVE CONTROL — a plan and its journal are SUPPOSED to read like this.

    ``CLAUDE/Plan/**`` and ``RELEASES/**`` are dated, deliberately-narrative
    records; flagging them would fire on hundreds of legitimate files and the
    gate would be switched off within a day. The defect class is a frozen
    session summary tracked as though it were reference documentation.
    """
    repo = _make_repo(
        tmp_path,
        {
            "CLAUDE/Plan/00001-x/PLAN.md": "## Mission Accomplished\n",
            "CLAUDE/Plan/00001-x/JOURNAL/00001-Journal-26-08-07.md": (
                "**Test Results**: 12 PASSING / 3 FAILING\n"
            ),
            "RELEASES/v1.0.0.md": "## Mission Accomplished\n",
            "CHANGELOG.md": "**Test Results**: 5 PASSING / 1 FAILING\n",
        },
    )

    exit_code, report = _run_checker(repo)

    assert exit_code == 0, f"narrative record flagged: {report['violations']}"


def test_flags_test_stub_under_src(tmp_path: Path) -> None:
    """A ``test_*.py`` under ``src/`` that pytest can never collect.

    ``src/tests/test_acceptance_test.py`` existed for one reason, stated in its
    own docstring: *"This file satisfies the TDD enforcement handler
    requirement."* It had no test function, no import and no assertion, and
    ``testpaths = ["tests"]`` meant nothing ever ran it. A committed decoy that
    documents bypassing the project's flagship guardrail is worse than the
    missing test it stood in for, and no guard could see it.
    """
    repo = _make_repo(
        tmp_path,
        {"src/tests/test_thing.py": '"""Satisfies TDD enforcement."""\n'},
    )

    exit_code, report = _run_checker(repo)

    assert exit_code == 1
    assert "src-test-stub" in _rules(report)
    assert "src/tests/test_thing.py" in _paths(report)


def test_does_not_flag_tests_in_the_real_test_tree(tmp_path: Path) -> None:
    """NEGATIVE CONTROL — collectable tests are the point of the repo."""
    repo = _make_repo(
        tmp_path,
        {
            "tests/unit/test_thing.py": "def test_x() -> None:\n    assert True\n",
            "src/pkg/module.py": "X = 1\n",
        },
    )

    exit_code, report = _run_checker(repo)

    assert exit_code == 0, f"clean tree flagged: {report['violations']}"


def test_does_not_flag_test_scripts_beside_the_code_they_test(tmp_path: Path) -> None:
    """NEGATIVE CONTROL — the rule must discriminate, not just fire.

    A rule broad enough to flag every ``test_*.sh`` anywhere in the tree would
    be a naming-convention rule wearing a hygiene rule's name, and would fire on
    shell tests that legitimately sit next to the code they exercise. A gate
    that cries wolf gets switched off. The defect class is *stranded at the
    repository root* — a location where a test script has no owning context —
    so that is exactly what the rule targets, and this asserts it stays there.
    """
    repo = _make_repo(
        tmp_path,
        {
            "scripts/install/test_venv.sh": "#!/bin/bash\n",
            "tests/integration/test_thing.py": "",
        },
    )

    exit_code, report = _run_checker(repo)

    assert exit_code == 0, f"clean tree flagged: {report['violations']}"
    assert report["violations"] == []


def test_ignores_untracked_artifacts(tmp_path: Path) -> None:
    """NEGATIVE CONTROL — an untracked ``coverage.json`` is normal.

    Generating coverage locally must not fail the gate; only *committing* it
    does. Without this, the check would fire on every developer who ran the
    test suite, and would be disabled within a day.
    """
    repo = _make_repo(tmp_path, {"README.md": "# ok\n"})
    (repo / "coverage.json").write_text("{}", encoding="utf-8")

    exit_code, report = _run_checker(repo)

    assert exit_code == 0, f"untracked artifact wrongly flagged: {report['violations']}"


def test_real_repository_is_clean() -> None:
    """The gate itself: this repository must carry no tracked detritus."""
    exit_code, report = _run_checker(REPO_ROOT)

    assert exit_code == 0, "Tracked detritus found in this repository:\n" + "\n".join(
        f"  [{v['rule']}] {v['path']}: {v['message']}" for v in report["violations"]
    )
