"""A QA checker pointed elsewhere must not overwrite THIS repository's artefact.

``llm_qa`` publishes each check's JSON artefact as that check's evidence
surface: it prints the path and a ``jq`` hint for a reader to query. A checker
that writes a module-level absolute path whenever ``--json`` is passed therefore
publishes whatever the last run happened to scan — and its own unit tests point
it at a pytest fixture directory.

Both directions are wrong and only one is visible. A check that PASSED can be
left holding a fixture FAILURE (observed: three checks read ``passed: false``
against ``/tmp`` paths after a full run, and it cost a mid-run diagnosis). A
check that FAILED can be left holding a fixture PASS, which masks a real defect
and is the direction nobody would notice. Which one you get depends on the order
the checks and the tests happen to run in, which is incidental.

``check_sensitive_content.py`` already fixed this for itself, with the reasoning
written at its write site: a scoped scan answers "is this DIRECTORY clean",
which is not the question the repository artefact answers, so it reports beside
what it scanned. This module pins that boundary for every checker that takes a
scan-target override (Plan 00422 N10, Plan 00432).

The set below was taken by measurement, not from the original report, which
named three. Four more share the shape. Checkers whose override names an INPUT
file rather than a directory to scan (``--inventory``, ``--corpus``,
``--registry``) are deliberately out: there is no scanned directory to report
beside.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
_QA_DIR: Final[Path] = _REPO_ROOT / "scripts" / "qa"
_ARTEFACT_DIR: Final[Path] = _REPO_ROOT / "untracked" / "qa"


@dataclass(frozen=True)
class ScopedChecker:
    """One checker, and how to point it somewhere other than this repository."""

    script: str
    flag: str
    artefact: str
    needs_git_repo: bool = False


_CHECKERS: Final[tuple[ScopedChecker, ...]] = (
    ScopedChecker("check_git_history.py", "--repo", "git_history.json", needs_git_repo=True),
    ScopedChecker("check_skill_references.py", "--path", "skill_references.json"),
    ScopedChecker("check_python_var_guidance.py", "--path", "python_var_guidance.json"),
    ScopedChecker("check_github_urls.py", "--path", "github_urls.json"),
    ScopedChecker("check_security_downgrade_flags.py", "--root", "security_downgrade_flags.json"),
    ScopedChecker("check_eacces_safe_predicates.py", "--path", "eacces_safe.json"),
    ScopedChecker("check_authored_path_stat.py", "--path", "authored_path_stat.json"),
)


def _prepare(checker: ScopedChecker, target: Path) -> None:
    """Make `target` a directory the checker will actually scan."""
    (target / "harmless.py").write_text("VALUE = 1\n", encoding="utf-8")
    if checker.needs_git_repo:
        subprocess.run(  # nosec B603 B607 - fixed argv, no shell
            ["git", "init", "--quiet", str(target)], check=True, capture_output=True
        )


def _run_scoped(checker: ScopedChecker, target: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 - fixed argv from a repo-internal table
        [sys.executable, str(_QA_DIR / checker.script), "--json", checker.flag, str(target)],
        capture_output=True,
        text=True,
        check=False,
        cwd=_REPO_ROOT,
    )


@pytest.mark.parametrize("checker", _CHECKERS, ids=lambda c: c.script)
class TestAScopedScanReportsBesideWhatItScanned:
    def test_the_repository_artefact_is_untouched(
        self, checker: ScopedChecker, tmp_path: Path
    ) -> None:
        """The artefact `llm_qa` publishes must keep describing this repository."""
        repo_artefact = _ARTEFACT_DIR / checker.artefact
        before = repo_artefact.read_bytes() if repo_artefact.exists() else None

        _prepare(checker, tmp_path)
        result = _run_scoped(checker, tmp_path)

        after = repo_artefact.read_bytes() if repo_artefact.exists() else None
        assert after == before, (
            f"{checker.script} pointed at {checker.flag} {tmp_path} overwrote "
            f"{repo_artefact}, which llm_qa publishes as this check's evidence. "
            f"Its verdict now describes a fixture directory, not this "
            f"repository.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    def test_the_scoped_verdict_lands_beside_the_target(
        self, checker: ScopedChecker, tmp_path: Path
    ) -> None:
        """It still has to go somewhere — the caller asked for `--json`."""
        _prepare(checker, tmp_path)
        result = _run_scoped(checker, tmp_path)

        scoped = tmp_path / checker.artefact
        assert scoped.is_file(), (
            f"{checker.script} wrote no scoped artefact at {scoped}. Not "
            f"overwriting the repository's is only half the contract; a caller "
            f"that passed --json and got nothing cannot read its own "
            f"result.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert json.loads(scoped.read_text(encoding="utf-8")), scoped.read_text(encoding="utf-8")


class TestTheInventoryItself:
    def test_every_named_script_exists(self) -> None:
        """Control: a renamed checker would silently drop out of the sweep."""
        missing = [c.script for c in _CHECKERS if not (_QA_DIR / c.script).is_file()]
        assert not missing, f"named in this guard but absent from {_QA_DIR}: {missing}"

    def test_each_checker_still_accepts_its_override_flag(self) -> None:
        """Control: a flag that no longer parses makes the scan repo-wide again.

        A checker that ignored `--path` would scan this repository, write the
        repository artefact with a correct verdict, and pass the test above by
        accident — the artefact would be identical because nothing had changed.
        """
        unsupported = [
            c.script
            for c in _CHECKERS
            if c.flag not in (_QA_DIR / c.script).read_text(encoding="utf-8")
        ]
        assert not unsupported, (
            f"these no longer mention their own override flag, so this guard "
            f"may be scanning the repository rather than a fixture: {unsupported}"
        )
