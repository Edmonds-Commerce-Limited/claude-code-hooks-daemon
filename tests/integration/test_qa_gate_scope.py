"""Guard: the ruff / black / mypy gates must not silently narrow their scope.

DBF (``CLAUDE.md`` Core Standard 15). All three gates were scoped to
``src/ tests/ .claude/ccy/claude-supervise.py``. Every other tracked Python file
— ``scripts/``, ``install.py``, ``examples/``, and the entirety of
``scripts/qa/`` (the QA tooling itself) — went unexamined, and each gate
reported PASSED the whole time, because it *had* passed on the subset it looked
at. Nothing was lying; nothing was looking either.

That is invisible by construction: a gate's scope is an argument list, and an
argument list that shrinks produces a greener result, not a redder one. So the
scope needs a test, the same way Plan 00193 pinned the python-var gate.

What this asserts:

1. The scope is declared in ONE place (``scripts/qa/gate-scope.bash``) rather
   than as literals inside three scripts that can drift apart.
2. Each gate sources that file and uses the functions — no gate carries its own
   hardcoded path list.
3. The declared scope still covers the directories whose omission was the
   original defect.

What it deliberately does NOT assert: that mypy covers ``tests/`` and
``.claude/project-handlers/``. Those exclusions are real, documented in
``gate-scope.bash`` with their reasons, and tracked separately. A test that
demanded them would fail today and be deleted tomorrow — which is how a repo
ends up with no scope test at all.
"""

from __future__ import annotations

import re
import subprocess  # nosec B404 — runs the trusted system ``bash`` to read the scope
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QA_DIR: Final[Path] = _REPO_ROOT / "scripts" / "qa"
_SCOPE_FILE: Final[Path] = _QA_DIR / "gate-scope.bash"

_BASH_BINARY: Final[str] = "bash"
_BASH_TIMEOUT_SECONDS: Final[int] = 30

# gate script -> (scope function it must call, mapfile variable it must expand)
_GATES: Final[dict[str, tuple[str, str]]] = {
    "run_lint.sh": ("qa_lint_paths", "LINT_PATHS"),
    "run_format_check.sh": ("qa_format_paths", "FORMAT_PATHS"),
    "run_type_check.sh": ("qa_type_paths", "TYPE_PATHS"),
}

# The scope that was in force when every non-src path was unexamined. Kept as a
# named constant so a regression is reported by its real name.
_ORIGINAL_NARROW_SCOPE: Final[str] = "src/ tests/ .claude/ccy/claude-supervise.py"

# Directories whose absence from the type gate was the defect.
_REQUIRED_TYPE_PATHS: Final[tuple[str, ...]] = ("src/", "scripts/", "install.py", "examples/")


def _read_scope(function_name: str) -> list[str]:
    """Invoke a scope function in bash and return the paths it prints.

    Reads the values the gates ACTUALLY get, rather than re-parsing the file
    with a regex that could drift from what bash does.
    """
    result = subprocess.run(  # nosec B603 — fixed argv, no shell, trusted input
        [_BASH_BINARY, "-c", f'source "{_SCOPE_FILE}" && {function_name}'],
        capture_output=True,
        text=True,
        timeout=_BASH_TIMEOUT_SECONDS,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


class TestGateScopeIsCentralised:
    """One declaration, sourced by every gate."""

    def test_scope_file_exists(self) -> None:
        """The SSoT file is present."""
        assert _SCOPE_FILE.is_file(), (
            f"{_SCOPE_FILE} is missing. The ruff/black/mypy gates read their "
            f"scope from it; without it each gate reverts to its own literal "
            f"list, which is the condition this guard exists to prevent."
        )

    def test_every_gate_sources_the_scope_file(self) -> None:
        """No gate carries its own path list."""
        for gate in _GATES:
            text = (_QA_DIR / gate).read_text(encoding="utf-8")
            assert "gate-scope.bash" in text, (
                f"{gate} does not source gate-scope.bash. Its scope is "
                f"therefore invisible to this guard and free to drift."
            )

    def test_every_gate_expands_the_scope_it_sourced(self) -> None:
        """Sourcing is not enough — the gate must actually use the values."""
        for gate, (function_name, variable) in _GATES.items():
            text = (_QA_DIR / gate).read_text(encoding="utf-8")
            assert function_name in text, f"{gate} never calls {function_name}()."
            assert f'"${{{variable}[@]}}"' in text, (
                f"{gate} does not expand ${{{variable}[@]}} into its tool "
                f"invocation. A gate that sources the scope and then ignores "
                f"it is exactly as blind as one that hardcodes a list."
            )

    def test_no_gate_retains_the_original_narrow_scope(self) -> None:
        """The literal argument list that shipped the blind spot is gone."""
        for gate in _GATES:
            text = (_QA_DIR / gate).read_text(encoding="utf-8")
            invocations = [
                line
                for line in text.splitlines()
                if _ORIGINAL_NARROW_SCOPE in line and not line.lstrip().startswith("#")
            ]
            assert not invocations, (
                f"{gate} still passes the original narrow scope "
                f"({_ORIGINAL_NARROW_SCOPE!r}) as a live argument list: "
                f"{invocations}"
            )


class TestScopeStillCoversWhatItMustCover:
    """The declared values, read the way the gates read them."""

    def test_lint_and_format_cover_the_whole_repository(self) -> None:
        """Ruff and Black take the repo root."""
        for function_name in ("qa_lint_paths", "qa_format_paths"):
            paths = _read_scope(function_name)
            assert paths == ["."], (
                f"{function_name}() returned {paths}, expected ['.']. Ruff and "
                f"Black run over the whole tree; deliberate exclusions belong "
                f"in pyproject.toml's extend-exclude, not in a shrunken scope."
            )

    def test_type_scope_covers_the_previously_unexamined_paths(self) -> None:
        """Mypy reaches the directories whose omission was the defect."""
        paths = _read_scope("qa_type_paths")

        missing = [required for required in _REQUIRED_TYPE_PATHS if required not in paths]
        assert not missing, (
            f"The mypy gate no longer covers {missing}. Those paths were "
            f"unexamined when the gate was scoped to src/ alone, which is how "
            f"install.py shipped a function annotated '-> None' that returned a "
            f"Path, and how the package shipped with no py.typed marker."
        )

    def test_type_scope_is_not_empty(self) -> None:
        """Control: an empty scope would make every assertion above vacuous."""
        assert _read_scope("qa_type_paths"), "qa_type_paths() returned nothing."


class TestTypeGateCannotPassWithoutAnalysing:
    """A type check that analysed nothing has not passed — it has not run."""

    def test_gate_requires_a_positive_analysed_count(self) -> None:
        """``passed`` is conjoined with the file count, not derived from errors alone.

        The parser computed ``passed = len(errors) == 0`` from parsed finding
        lines only. A mypy usage failure (bad path, invalid package name,
        unreadable config) emits a message matching no ``file:line: error:``
        pattern, so it produced zero findings and reported PASSED having checked
        nothing.
        """
        text = (_QA_DIR / "run_type_check.sh").read_text(encoding="utf-8")

        assert "len(errors) == 0 and bool(analysed_count)" in text, (
            "run_type_check.sh no longer conjoins `passed` with the analysed "
            "file count. Restore it: without that term the gate reports PASSED "
            "when mypy fails before checking a single file."
        )

    def test_gate_parses_the_mypy_summary_line(self) -> None:
        """The analysed count comes from mypy, not from counting finding lines."""
        text = (_QA_DIR / "run_type_check.sh").read_text(encoding="utf-8")

        # Inspect executable lines only. The file's own commentary explains why
        # the flag is absent, so a naive whole-file substring search matches the
        # explanation and fails on a correct script.
        live_lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
        offenders = [line for line in live_lines if "--no-error-summary" in line]
        assert not offenders, (
            f"run_type_check.sh passes --no-error-summary again: {offenders}. "
            f"That flag suppresses the only line stating how many files mypy "
            f"analysed, which is the evidence `passed` now depends on."
        )
        assert re.search(r"Success: no issues found in", text), (
            "run_type_check.sh no longer matches mypy's success summary, so it "
            "cannot recover the analysed-file count on a clean run."
        )
