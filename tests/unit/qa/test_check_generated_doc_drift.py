"""Plan 00402 — the committed handler doc must match what generate-docs produces.

``.claude/HOOKS-DAEMON.md`` is written by exactly one command, ``generate-docs``
(and ``regenerate-docs``, which calls it). A daemon restart regenerates the
``CLAUDE.md`` block but never this file, so a handler added in-repo left it
stale: it sat announcing "UserPromptSubmit (5 handlers)" while six were
registered, with ``daemon_upgrade_detector`` missing entirely.

Nothing could see it. The docs-QA staleness sweep compares the embedded
version marker against ``__version__``, so drift WITHIN one version is
invisible by construction, and ``tests/conftest.py`` forbids any test from
writing the file.

The ruled fix (option 3) is a QA check that regenerates the doc into a
throwaway location and compares the BODY with the committed file. The
``> Generated on ... (vX.Y.Z)`` marker line is excluded from the comparison:
it is the only durable record of the version the tracked assets were deployed
from, ``scripts/upgrade.sh`` reads it as the upgrade's FROM side, and a check
that demanded today's version would push every reader to restamp it.
"""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404 - runs the QA checker and the daemon CLI only
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKER = REPO_ROOT / "scripts" / "qa" / "check_generated_doc_drift.py"
TRACKED_DOC = REPO_ROOT / ".claude" / "HOOKS-DAEMON.md"
_TIMEOUT_SECONDS = 120

RULE_DRIFT = "generated-doc-drift"
RULE_MARKER_MISSING = "generated-doc-marker-missing"

# The minimum config generate-docs accepts for a tree with no installed clone.
_FIXTURE_CONFIG = 'version: "2.0"\ndaemon:\n  self_install_mode: true\n'
_FIXTURE_REMOTE = "https://example.invalid/fixture.git"

# The handler whose absence was the originating instance of this defect.
_ORIGINATING_HANDLER = "daemon_upgrade_detector"
_ORIGINATING_SECTION = "### UserPromptSubmit"

_MARKER_PREFIX = "> Generated on "
_OLD_MARKER = "> Generated on 2020-01-01 (v1.0.0) by `generate-docs`. Regenerate: `old`"


def _run_checker(root: Path) -> tuple[int, dict[str, Any], str]:
    result = subprocess.run(  # nosec B603 - fixed argv, trusted checker script
        [sys.executable, str(CHECKER), "--root", str(root), "--report-stdout"],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )
    report: dict[str, Any] = json.loads(result.stdout) if result.stdout.strip() else {}
    return result.returncode, report, result.stderr


def _rules(report: dict[str, Any]) -> list[str]:
    return [violation["rule"] for violation in report.get("violations", [])]


@pytest.fixture(scope="module")
def generated_fixture(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A self-install tree whose committed doc is exactly what generate-docs writes.

    Generated ONCE per module through the real CLI, so every test starts from
    genuine generator output rather than a hand-typed imitation of it.
    """
    root = tmp_path_factory.mktemp("generated") / "project"
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "hooks-daemon.yaml").write_text(_FIXTURE_CONFIG, encoding="utf-8")
    # Config validation refuses a project that is not a git repository with an
    # origin remote.
    for git_args in (("init", "-q"), ("remote", "add", "origin", _FIXTURE_REMOTE)):
        subprocess.run(  # nosec B603 B607 - fixed argv, git only
            ["git", *git_args], cwd=root, check=True, capture_output=True
        )
    result = subprocess.run(  # nosec B603 - fixed argv, the daemon's own CLI
        [
            sys.executable,
            "-m",
            "claude_code_hooks_daemon.daemon.cli",
            "generate-docs",
            "--project-root",
            str(root),
            "--output",
            str(root / ".claude" / "HOOKS-DAEMON.md"),
        ],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode == 0, f"fixture generation failed: {result.stderr[:500]}"
    return root


@pytest.fixture
def project(generated_fixture: Path, tmp_path: Path) -> Path:
    """A private copy of the generated tree, so a test may damage its doc."""
    root = tmp_path / "project"
    shutil.copytree(generated_fixture, root)
    return root


def _doc(root: Path) -> Path:
    return root / ".claude" / "HOOKS-DAEMON.md"


def _rewrite_lines(root: Path, lines: list[str]) -> None:
    _doc(root).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _lines(root: Path) -> list[str]:
    return _doc(root).read_text(encoding="utf-8").splitlines()


class TestDriftIsDetected:
    def test_fresh_doc_passes(self, project: Path) -> None:
        """NEGATIVE CONTROL: output straight from the generator is not drift."""
        exit_code, report, stderr = _run_checker(project)

        assert exit_code == 0, f"fresh generator output was flagged: {report or stderr}"
        assert report["violations"] == []

    def test_flags_the_originating_instance(self, project: Path) -> None:
        """A handler row missing and its section count one short — the observed rot."""
        lines = _lines(project)
        assert any(
            f"| {_ORIGINATING_HANDLER} |" in line for line in lines
        ), f"fixture no longer renders {_ORIGINATING_HANDLER}; pick another handler"

        damaged: list[str] = []
        for line in lines:
            if f"| {_ORIGINATING_HANDLER} |" in line:
                continue
            if line.startswith(_ORIGINATING_SECTION):
                line = f"{_ORIGINATING_SECTION} (1 handlers)"
            damaged.append(line)
        _rewrite_lines(project, damaged)

        exit_code, report, stderr = _run_checker(project)

        assert exit_code == 1, f"a stale handler doc passed: {report or stderr}"
        assert set(_rules(report)) == {RULE_DRIFT}
        messages = " ".join(v["message"] for v in report["violations"])
        assert _ORIGINATING_HANDLER in messages, "the missing row must be named"
        assert _ORIGINATING_SECTION in messages, "the stale section heading must be named"

    def test_flags_a_row_the_generator_no_longer_emits(self, project: Path) -> None:
        """The other direction: a documented handler that is no longer registered."""
        lines = _lines(project)
        table_row = next(i for i, line in enumerate(lines) if line.startswith("| 10 |"))
        lines.insert(table_row, "| 10 | retired_handler | BLOCKING | Gone from the registry |")
        _rewrite_lines(project, lines)

        exit_code, report, _stderr = _run_checker(project)

        assert exit_code == 1
        assert _rules(report) == [RULE_DRIFT]
        assert "retired_handler" in report["violations"][0]["message"]
        assert report["violations"][0]["line"] == table_row + 1


class TestMarkerIsPreserved:
    """The deployed-from marker is never compared, never rewritten, never optional."""

    def test_an_older_marker_is_not_drift(self, project: Path) -> None:
        """A doc deployed from an older version, with a current body, passes.

        If this failed, the only way to pass would be to restamp the marker
        with the running version — destroying the FROM signal upgrade.sh reads.
        """
        lines = [
            _OLD_MARKER if line.startswith(_MARKER_PREFIX) else line for line in _lines(project)
        ]
        _rewrite_lines(project, lines)

        exit_code, report, stderr = _run_checker(project)

        assert exit_code == 0, f"an older deployed-from marker was flagged: {report or stderr}"

    def test_a_missing_marker_is_flagged(self, project: Path) -> None:
        """Excluding the marker must not make its absence invisible."""
        _rewrite_lines(project, [ln for ln in _lines(project) if not ln.startswith(_MARKER_PREFIX)])

        exit_code, report, _stderr = _run_checker(project)

        assert exit_code == 1
        assert _rules(report) == [RULE_MARKER_MISSING]

    def test_the_check_never_writes_the_doc(self, project: Path) -> None:
        """Comparing must never repair: the committed bytes, marker included, survive."""
        lines = [
            _OLD_MARKER if line.startswith(_MARKER_PREFIX) else line for line in _lines(project)
        ]
        lines.append("| 99 | drifted_row | ADVISORY | Forces a failing run |")
        _rewrite_lines(project, lines)
        before = _doc(project).read_bytes()

        exit_code, _report, _stderr = _run_checker(project)

        assert exit_code == 1
        assert _doc(project).read_bytes() == before


class TestOperationalFailures:
    """A check that cannot compare must say so, never report clean."""

    def test_missing_doc_is_an_operational_failure(self, project: Path) -> None:
        _doc(project).unlink()

        exit_code, _report, stderr = _run_checker(project)

        assert exit_code == 2
        assert "HOOKS-DAEMON.md" in stderr

    def test_generator_failure_is_an_operational_failure(self, project: Path) -> None:
        (project / ".claude" / "hooks-daemon.yaml").unlink()

        exit_code, _report, stderr = _run_checker(project)

        assert exit_code == 2
        assert "generate-docs" in stderr


def test_real_repository_handler_doc_is_fresh() -> None:
    """The gate itself: this repository's committed doc matches its generator."""
    before = TRACKED_DOC.read_bytes()

    exit_code, report, stderr = _run_checker(REPO_ROOT)

    assert TRACKED_DOC.read_bytes() == before, "the check rewrote the tracked doc"
    assert exit_code == 0, (
        "`.claude/HOOKS-DAEMON.md` has drifted from `generate-docs` output. "
        "Run `bin/hooks-daemon generate-docs` and commit the result:\n"
        + (
            "\n".join(
                f"  [{v['rule']}] line {v['line']}: {v['message']}" for v in report["violations"]
            )
            if report
            else stderr
        )
    )
