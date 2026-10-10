"""`--path FILE` runs four QA checkers over a single file (Plan 00484 G8, DETECTOR-SPEC 5.2).

DETECTOR-SPEC 5.2: a detector MUST support invocation over a subset, at
minimum a single file, because a check that takes the whole tree is too slow
to run on every edit and so is not run on any. Until now no `scripts/qa`
checker accepted a file: `--path` and `--root` took directories, and
`check_authored_path_stat.py` failed as vacuous when given one.

Phase 2 covers `check_magic_values.py`, `audit_error_hiding.py` and
`audit_shell.py`. The contract is the same for each: the named file is judged
as the tree run would judge it, the findings go to the command's own output
(JSON to stdout with `--json`), and the repository artefact `llm_qa.py`
publishes is never written, because a one-file answer is not an answer about
the repository.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
QA_DIR: Final[Path] = REPO_ROOT / "scripts" / "qa"
ARTEFACT_DIR: Final[Path] = REPO_ROOT / "untracked" / "qa"


@dataclass(frozen=True)
class SingleFileChecker:
    """One checker, a file it must flag, the rule it must name, and a clean file."""

    script: str
    artefact: str
    filename: str
    bad: str
    rule: str
    clean: str
    other_kind: str = "notes.txt"  # a name the checker does not judge


_CHECKERS: Final[tuple[SingleFileChecker, ...]] = (
    SingleFileChecker(
        "check_magic_values.py",
        "magic_values.json",
        "handler_sample.py",
        "from base import Handler\n"
        "class MyHandler(Handler):\n"
        "    def __init__(self):\n"
        '        super().__init__(name="my-handler", priority=10)\n',
        "magic-handler-name",
        "VALUE = 1\n",
    ),
    SingleFileChecker(
        "audit_error_hiding.py",
        "error_hiding.json",
        "swallow_sample.py",
        "def f():\n    try:\n        risky()\n    except Exception:\n        pass\n",
        "silent-pass",
        "def f() -> int:\n    return 1\n",
    ),
    SingleFileChecker(
        "audit_shell.py",
        "shell_audit.json",
        "sample.sh",
        "#!/bin/bash\nchmod +x hook 2>/dev/null || true\n",
        "double-suppression",
        "#!/bin/bash\necho ok\n",
    ),
    SingleFileChecker(
        "check_british_english.py",
        "british_english.json",
        "notes.md",
        "The behavior of the daemon is documented here.\n",
        "american-spelling",
        "The behaviour of the daemon is documented here.\n",
        other_kind="notes.json",
    ),
)


def _run(checker: SingleFileChecker, target: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(QA_DIR / checker.script), "--path", str(target), *extra],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )


@pytest.mark.parametrize("checker", _CHECKERS, ids=lambda c: c.script)
class TestAFileIsJudgedOnItsOwn:
    def test_a_bad_file_fails_naming_the_rule_and_the_file(
        self, checker: SingleFileChecker, tmp_path: Path
    ) -> None:
        target = tmp_path / checker.filename
        target.write_text(checker.bad, encoding="utf-8")
        result = _run(checker, target)
        assert result.returncode == 1, result.stdout + result.stderr
        assert checker.rule in result.stdout
        assert checker.filename in result.stdout

    def test_a_clean_file_passes(self, checker: SingleFileChecker, tmp_path: Path) -> None:
        target = tmp_path / checker.filename
        target.write_text(checker.clean, encoding="utf-8")
        result = _run(checker, target)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_json_goes_to_stdout_and_says_what_was_judged(
        self, checker: SingleFileChecker, tmp_path: Path
    ) -> None:
        target = tmp_path / checker.filename
        target.write_text(checker.bad, encoding="utf-8")
        result = _run(checker, target, "--json")
        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert data["summary"]["passed"] is False
        assert data["summary"]["files_scanned"] == 1
        assert any(v["rule"] == checker.rule for v in data["violations"])

    def test_the_repository_artefact_is_untouched(
        self, checker: SingleFileChecker, tmp_path: Path
    ) -> None:
        """`llm_qa` publishes that artefact as the repository's verdict."""
        artefact = ARTEFACT_DIR / checker.artefact
        before = artefact.read_bytes() if artefact.exists() else None
        target = tmp_path / checker.filename
        target.write_text(checker.bad, encoding="utf-8")
        _run(checker, target, "--json")
        after = artefact.read_bytes() if artefact.exists() else None
        assert after == before

    def test_a_missing_file_fails(self, checker: SingleFileChecker, tmp_path: Path) -> None:
        result = _run(checker, tmp_path / "absent.py")
        assert result.returncode == 1
        assert "absent.py" in result.stderr

    def test_a_directory_is_not_a_file(self, checker: SingleFileChecker, tmp_path: Path) -> None:
        result = _run(checker, tmp_path)
        assert result.returncode == 1
        assert "not a file" in result.stderr

    def test_a_file_of_another_kind_fails_rather_than_passing_vacuously(
        self, checker: SingleFileChecker, tmp_path: Path
    ) -> None:
        target = tmp_path / checker.other_kind
        target.write_text("nothing to judge\n", encoding="utf-8")
        result = _run(checker, target)
        assert result.returncode == 1
        assert checker.other_kind in result.stderr


@dataclass(frozen=True)
class ScopeCase:
    """A tracked file inside the repository, and whether the tree run judges it."""

    script: str
    relative: str
    judged: bool


#: `audit_error_hiding` audits src/, scripts/ and four root files; `audit_shell` audits
#: scripts/ and the skill scripts only. So the root `init.sh` is judged by the first and
#: not by the second, and a test module is judged by neither.
_SCOPE_CASES: Final[tuple[ScopeCase, ...]] = (
    ScopeCase("audit_error_hiding.py", "scripts/qa/check_module_length.py", True),
    ScopeCase("audit_error_hiding.py", "init.sh", True),
    ScopeCase("audit_error_hiding.py", "tests/unit/qa/test_qa_single_file_subset.py", False),
    ScopeCase("audit_shell.py", "scripts/lib/portable_time.sh", True),
    ScopeCase("audit_shell.py", "init.sh", False),
    ScopeCase("check_british_english.py", "README.md", True),
    ScopeCase("check_british_english.py", "CHANGELOG.md", False),
    ScopeCase("check_british_english.py", "CLAUDE/Plan/README.md", False),
)


class TestAFileInsideTheRepositoryIsJudgedOnlyIfTheTreeRunJudgesIt:
    """S4: `--path FILE` cannot pass a file the tree run would never look at."""

    @pytest.mark.parametrize("case", _SCOPE_CASES, ids=lambda c: f"{c.script}:{c.relative}")
    def test_scope_matches_the_tree_run(self, case: ScopeCase) -> None:
        checker = next(c for c in _CHECKERS if c.script == case.script)
        result = _run(checker, REPO_ROOT / case.relative)
        if case.judged:
            assert "not judged by the tree run" not in result.stderr
        else:
            assert result.returncode == 1
            assert "not judged by the tree run" in result.stderr
            assert case.relative in result.stderr

    @pytest.mark.parametrize("case", _SCOPE_CASES, ids=lambda c: f"{c.script}:{c.relative}")
    def test_an_out_of_scope_file_reports_nothing_on_stdout(self, case: ScopeCase) -> None:
        if case.judged:
            pytest.skip("only the refused files have a refusal to pin")
        checker = next(c for c in _CHECKERS if c.script == case.script)
        result = _run(checker, REPO_ROOT / case.relative, "--json")
        assert result.returncode == 1
        assert result.stdout.strip() == ""


class TestTheTreeRunIsUnchanged:
    def test_the_tree_run_still_takes_no_path(self) -> None:
        """No `--path`: the whole-repository behaviour and its artefact are as before."""
        result = subprocess.run(
            [sys.executable, str(QA_DIR / "audit_shell.py"), "--scan-dir", str(QA_DIR)],
            capture_output=True,
            text=True,
            check=False,
            cwd=REPO_ROOT,
        )
        assert result.returncode in (0, 1)
        assert "shell-audit" in result.stdout
