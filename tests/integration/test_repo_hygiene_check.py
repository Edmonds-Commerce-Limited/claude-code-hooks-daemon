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
