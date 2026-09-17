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

The sets below were taken by measurement, not from the original report, which
named three. Seven more share the shape, in two flavours.

A checker whose override names an INPUT FILE (``--inventory``, ``--corpus``,
``--registry``) has no scanned directory to report beside, but it has the same
defect: two of the three still sweep this repository, so the override changes
the DECLARATIONS it is graded against, and "clean against our registry" is not
the fact "clean against someone else's" establishes. The third grades only the
corpus it was handed. All three reported into the repository artefact anyway, so
they report beside the file they were pointed at instead.
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


@dataclass(frozen=True)
class InputFileChecker:
    """One checker whose override names a FILE it is graded against."""

    script: str
    flag: str
    artefact: str
    default_input: str


_INPUT_FILE_CHECKERS: Final[tuple[InputFileChecker, ...]] = (
    InputFileChecker(
        "check_fail_open_inventory.py",
        "--inventory",
        "fail_open_inventory.json",
        "fail-open-boundaries.yaml",
    ),
    InputFileChecker(
        "check_dangerous_invocation_corpus.py",
        "--corpus",
        "dangerous_invocation_corpus.json",
        "dangerous-invocation-corpus.yaml",
    ),
    InputFileChecker(
        "check_declared_invariant_pairs.py",
        "--registry",
        "declared_invariant_pairs.json",
        "declared-invariant-pairs.yaml",
    ),
)


@pytest.mark.parametrize("checker", _INPUT_FILE_CHECKERS, ids=lambda c: c.script)
class TestAnAlternativeInputFileReportsBesideThatFile:
    def test_the_repository_artefact_is_untouched(
        self, checker: InputFileChecker, tmp_path: Path
    ) -> None:
        repo_artefact = _ARTEFACT_DIR / checker.artefact
        before = repo_artefact.read_bytes() if repo_artefact.exists() else None

        substitute = tmp_path / checker.default_input
        substitute.write_text(
            (_QA_DIR / checker.default_input).read_text(encoding="utf-8"), encoding="utf-8"
        )
        result = subprocess.run(  # nosec B603 - fixed argv from a repo-internal table
            [
                sys.executable,
                str(_QA_DIR / checker.script),
                "--json",
                checker.flag,
                str(substitute),
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=_REPO_ROOT,
        )

        after = repo_artefact.read_bytes() if repo_artefact.exists() else None
        assert after == before, (
            f"{checker.script} graded against {substitute} overwrote "
            f"{repo_artefact}, which llm_qa publishes as this check's evidence "
            f"for the declarations THIS repository ships.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert (tmp_path / checker.artefact).is_file(), (
            f"no scoped artefact at {tmp_path / checker.artefact}; the caller "
            f"passed --json and must be able to read its own result.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    def test_the_default_input_it_names_still_exists(self, checker: InputFileChecker) -> None:
        """Control: the substitute above is a COPY of the real declarations.

        A renamed default would make the copy step fail loudly rather than
        quietly grade an empty file and pass.
        """
        assert (_QA_DIR / checker.default_input).is_file()


class TestTheInventoryItself:
    def test_every_named_script_exists(self) -> None:
        """Control: a renamed checker would silently drop out of the sweep."""
        named = [c.script for c in _CHECKERS] + [c.script for c in _INPUT_FILE_CHECKERS]
        missing = [script for script in named if not (_QA_DIR / script).is_file()]
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
