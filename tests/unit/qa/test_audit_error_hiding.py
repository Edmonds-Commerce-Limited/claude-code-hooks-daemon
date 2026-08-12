"""Tests for the error-hiding auditor (scripts/qa/audit_error_hiding.py).

Plan 00200 Phase 5: the daemon ships TWO defences against error-hiding — this
batch auditor and the write-time ``error_hiding_blocker`` handler — yet
neither caught the textbook swallow that started this plan:

    except json.JSONDecodeError:
        # Empty or invalid JSON means no violations
        ruff_output = []

in ``scripts/qa/run_lint.sh`` (fixed in ``fad60fa6``). This auditor missed it
for THREE independent reasons, each closed by a section below:

1. It scanned ``src/`` only ("production code only") — the QA scripts that
   IMPLEMENT the gates were exempt from the gate they enforce.
   -> ``AUDITED_DIRECTORIES`` / ``AUDITED_ROOT_FILES``
2. It globbed ``*.py`` only — the swallow lived in Python embedded in a
   ``python3 << 'EOF'`` heredoc inside a ``.sh`` file, invisible a second
   time over.
   -> ``extract_heredoc_python_blocks`` / ``audit_heredoc_python``
3. Even a Python file at that exact path would NOT have been flagged: the
   AST visitor had no rule for "except: <bare assignment>" — only
   pass/continue/log-and-continue were detected. A handler that swallows an
   exception behind a fallback value with no logging and no re-raise is
   exactly as invisible as `except: pass`.
   -> the ``silent-fallback`` rule on ``ErrorHidingVisitor``

The centrepiece test, ``TestPreFixRunLintFixtureIsCaught``, points the fixed
auditor at the exact pre-fix file content (recovered via
``git show fad60fa6^:scripts/qa/run_lint.sh``, frozen at
``tests/fixtures/error_hiding/pre_fix_run_lint.sh``) and requires it to flag
the swallow. If it cannot catch the bug that motivated this work, it is not
fixed.

Shell-language patterns (``|| true``, ``set +e``, ...) are audited by reusing
``strategies/error_hiding/shell_strategy.py`` rather than reimplementing its
regex list — see ``TestShellPatternAudit`` — so the write-time handler and
this batch auditor can never disagree about what counts as shell
error-hiding.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "qa"))
from audit_error_hiding import (  # E402: sys.path insert above must precede this import
    AUDITED_DIRECTORIES,
    AUDITED_ROOT_FILES,
    ErrorHidingVisitor,
    audit_directory,
    audit_file,
    audit_heredoc_python,
    audit_shell_patterns,
    collect_python_violations,
    collect_shell_files,
    collect_shell_violations,
    extract_heredoc_python_blocks,
)

from claude_code_hooks_daemon.strategies.error_hiding.shell_strategy import (
    ShellErrorHidingStrategy,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "error_hiding"
PRE_FIX_RUN_LINT_SH = FIXTURE_DIR / "pre_fix_run_lint.sh"


def _rules(violations: list[dict[str, Any]]) -> list[str]:
    return [v["rule"] for v in violations]


class TestAuditedRootsCannotSilentlyNarrow:
    """Task 5.6: regression guard on the audited scope itself.

    Widening the scope once is not enough if the constant can quietly shrink
    back to ``src/`` in a later edit — pin the membership so that regresses
    loudly as a failing test, not silently as a re-opened blind spot.
    """

    def test_scripts_directory_is_audited(self) -> None:
        assert "scripts" in AUDITED_DIRECTORIES

    def test_src_directory_is_still_audited(self) -> None:
        assert "src" in AUDITED_DIRECTORIES

    def test_root_install_py_is_audited(self) -> None:
        assert "install.py" in AUDITED_ROOT_FILES

    def test_root_shell_scripts_are_audited(self) -> None:
        assert "daemon.sh" in AUDITED_ROOT_FILES
        assert "init.sh" in AUDITED_ROOT_FILES
        assert "install.sh" in AUDITED_ROOT_FILES


class TestSilentFallbackRule:
    """The AST rule closing gap #3: 'except: <bare assign>' is error-hiding."""

    def test_single_statement_assign_handler_is_flagged(self) -> None:
        source = (
            "def f():\n"
            "    try:\n"
            "        risky()\n"
            "    except ValueError:\n"
            "        result = []\n"
        )
        tree = ast.parse(source)
        visitor = ErrorHidingVisitor(REPO_ROOT / "scripts" / "qa" / "fake.py")
        visitor.visit(tree)
        assert "silent-fallback" in _rules(visitor.violations)

    def test_handler_that_reraises_is_not_flagged_as_fallback(self) -> None:
        # Two statements (assign THEN raise) — this is the *opposite* of
        # hiding: the failure is still visible to the caller.
        source = (
            "def f():\n"
            "    try:\n"
            "        risky()\n"
            "    except ValueError:\n"
            "        result = []\n"
            "        raise\n"
        )
        tree = ast.parse(source)
        visitor = ErrorHidingVisitor(REPO_ROOT / "scripts" / "qa" / "fake.py")
        visitor.visit(tree)
        assert "silent-fallback" not in _rules(visitor.violations)

    def test_logged_handler_is_not_double_counted_as_fallback(self) -> None:
        # Single-statement logger call is already "log-and-continue" — must
        # not ALSO fire as silent-fallback (it isn't an assignment).
        source = (
            "def f():\n"
            "    try:\n"
            "        risky()\n"
            "    except ValueError:\n"
            "        logger.error('boom')\n"
        )
        tree = ast.parse(source)
        visitor = ErrorHidingVisitor(REPO_ROOT / "scripts" / "qa" / "fake.py")
        visitor.visit(tree)
        assert "silent-fallback" not in _rules(visitor.violations)
        assert "log-and-continue" in _rules(visitor.violations)

    def test_reproduces_the_run_lint_swallow_shape_directly(self) -> None:
        """The exact shape from run_lint.sh, without the shell/heredoc layer."""
        source = (
            "import json\n"
            "ruff_output = []\n"
            "try:\n"
            "    ruff_output = json.loads(content)\n"
            "except json.JSONDecodeError:\n"
            "    # Empty or invalid JSON means no violations\n"
            "    ruff_output = []\n"
        )
        tree = ast.parse(source)
        visitor = ErrorHidingVisitor(REPO_ROOT / "scripts" / "qa" / "fake.py")
        visitor.visit(tree)
        assert "silent-fallback" in _rules(visitor.violations)


class TestHeredocPythonExtraction:
    """Gap #2: Python embedded in a shell heredoc must be found and parsed."""

    def test_extracts_single_quoted_python3_heredoc(self) -> None:
        content = "#!/bin/bash\n" "python3 << 'EOF'\n" "print('hi')\n" "EOF\n" "echo done\n"
        blocks = extract_heredoc_python_blocks(content)
        assert len(blocks) == 1
        body_start_line, source = blocks[0]
        assert body_start_line == 3
        assert source == "print('hi')"

    def test_extracts_unquoted_delimiter_heredoc(self) -> None:
        content = "python3 - << PYEOF\n" "print('hi')\n" "PYEOF\n"
        blocks = extract_heredoc_python_blocks(content)
        assert len(blocks) == 1
        assert blocks[0][1] == "print('hi')"

    def test_extracts_venv_python_variable_heredoc(self) -> None:
        content = '"${VENV_PYTHON}" - << PYEOF\n' "print('hi')\n" "PYEOF\n"
        blocks = extract_heredoc_python_blocks(content)
        assert len(blocks) == 1

    def test_extracts_dash_delimiter_with_indented_terminator(self) -> None:
        content = "python3 <<-'EOF'\n" "print('hi')\n" "\tEOF\n"
        blocks = extract_heredoc_python_blocks(content)
        assert len(blocks) == 1
        assert blocks[0][1] == "print('hi')"

    def test_ignores_non_python_heredoc(self) -> None:
        content = "cat << EOF\n" "just some text\n" "EOF\n"
        assert extract_heredoc_python_blocks(content) == []

    def test_ignores_heredoc_used_as_loop_input(self) -> None:
        # `done <<EOF` feeds a while-read loop, not a python invocation.
        content = "while read -r line; do\n" '    echo "$line"\n' "done <<EOF\n" "a\nb\nEOF\n"
        assert extract_heredoc_python_blocks(content) == []

    def test_reports_correct_body_start_line_with_preamble(self) -> None:
        content = (
            "#!/bin/bash\n"
            "set -euo pipefail\n"
            "\n"
            "python3 << 'EOF' > out.json\n"
            "import json\n"
            "print(json.dumps({}))\n"
            "EOF\n"
        )
        blocks = extract_heredoc_python_blocks(content)
        assert len(blocks) == 1
        body_start_line, source = blocks[0]
        assert body_start_line == 5
        assert source == "import json\nprint(json.dumps({}))"


class TestAuditHeredocPython:
    """End-to-end: a .sh file with an embedded swallow is caught, with the
    violation pointing at the correct absolute line in the .sh file."""

    def test_flags_swallow_inside_heredoc_with_correct_line(self, tmp_path: Path) -> None:
        script = tmp_path / "example.sh"
        script.write_text(
            "#!/bin/bash\n"
            "python3 << 'EOF'\n"
            "import json\n"
            "try:\n"
            "    x = json.loads(raw)\n"
            "except json.JSONDecodeError:\n"
            "    x = []\n"
            "EOF\n"
        )
        violations = audit_heredoc_python(script)
        assert "silent-fallback" in _rules(violations)
        hit = next(v for v in violations if v["rule"] == "silent-fallback")
        assert hit["line"] == 4  # the `try:` line, absolute within example.sh
        assert hit["file"] == str(script)

    def test_clean_heredoc_is_not_flagged(self, tmp_path: Path) -> None:
        script = tmp_path / "clean.sh"
        script.write_text(
            "#!/bin/bash\npython3 << 'EOF'\nimport json\nprint(json.dumps({}))\nEOF\n"
        )
        assert audit_heredoc_python(script) == []

    def test_unparseable_heredoc_body_is_skipped_not_crashed(self, tmp_path: Path) -> None:
        # Unquoted delimiter heredocs allow shell ${VAR} interpolation, which
        # is not valid Python syntax until the shell expands it — must be
        # skipped like any other SyntaxError, not raise.
        script = tmp_path / "interpolated.sh"
        script.write_text("python3 - << PYEOF\nx = ${SOME_SHELL_VAR}\nPYEOF\n")
        assert audit_heredoc_python(script) == []


class TestShellPatternAudit:
    """Gap in shell-language pattern coverage, closed by REUSING the
    write-time handler's strategy (not reimplementing its regex list)."""

    def test_detects_or_true_via_shared_strategy(self, tmp_path: Path) -> None:
        script = tmp_path / "bad.sh"
        script.write_text("#!/bin/bash\nsome_command || true\n")
        violations = audit_shell_patterns(script, ShellErrorHidingStrategy())
        assert len(violations) == 1
        assert violations[0]["line"] == 2
        assert violations[0]["file"] == str(script)

    def test_clean_script_is_not_flagged(self, tmp_path: Path) -> None:
        script = tmp_path / "good.sh"
        script.write_text("#!/bin/bash\nset -euo pipefail\ncmd || { echo failed; exit 1; }\n")
        assert audit_shell_patterns(script, ShellErrorHidingStrategy()) == []

    def test_reuses_the_injected_strategys_patterns_generically(self, tmp_path: Path) -> None:
        """Proves genuine reuse: a stub strategy's patterns drive the scan,
        not a hardcoded copy of the real shell patterns."""

        class _StubPattern:
            name = "TOTALLY-MADE-UP-PATTERN"
            regex = r"MAGIC_MARKER_XYZ"
            example = "MAGIC_MARKER_XYZ"
            suggestion = "remove the marker"

        class _StubStrategy:
            language_name = "Stub"
            extensions = (".sh",)
            patterns = (_StubPattern(),)

            def get_acceptance_tests(self) -> list[Any]:
                return []

        script = tmp_path / "stub.sh"
        script.write_text("#!/bin/bash\necho MAGIC_MARKER_XYZ\n")
        violations = audit_shell_patterns(script, _StubStrategy())
        assert len(violations) == 1
        assert violations[0]["rule"].endswith("TOTALLY-MADE-UP-PATTERN")

    def test_deduplicates_repeated_matches_on_same_line(self, tmp_path: Path) -> None:
        script = tmp_path / "dup.sh"
        script.write_text("#!/bin/bash\ncmd1 || true; cmd2 || true\n")
        violations = audit_shell_patterns(script, ShellErrorHidingStrategy())
        lines = [v["line"] for v in violations]
        assert lines.count(2) == 1


class TestCollectHelpersRespectWorkspaceRoot:
    """collect_python_violations / collect_shell_violations honour
    AUDITED_DIRECTORIES + AUDITED_ROOT_FILES against an arbitrary workspace,
    proving the wiring (not just the individual scanners) is correct."""

    def test_collects_python_violation_from_scripts_subdir(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "tool.py").write_text(
            "try:\n    risky()\nexcept ValueError:\n    result = []\n"
        )
        violations = collect_python_violations(tmp_path)
        assert "silent-fallback" in _rules(violations)

    def test_collects_python_violation_from_root_install_py(self, tmp_path: Path) -> None:
        (tmp_path / "install.py").write_text(
            "try:\n    risky()\nexcept ValueError:\n    result = []\n"
        )
        violations = collect_python_violations(tmp_path)
        assert "silent-fallback" in _rules(violations)
        assert any(v["file"].endswith("install.py") for v in violations)

    def test_collects_shell_violation_from_root_daemon_sh(self, tmp_path: Path) -> None:
        (tmp_path / "daemon.sh").write_text("#!/bin/bash\nsome_command || true\n")
        violations = collect_shell_violations(tmp_path)
        assert any(v["file"].endswith("daemon.sh") for v in violations)

    def test_collect_shell_files_finds_scripts_and_root_files(self, tmp_path: Path) -> None:
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "a.sh").write_text("#!/bin/bash\necho a\n")
        (tmp_path / "init.sh").write_text("#!/bin/bash\necho init\n")
        found = {p.name for p in collect_shell_files(tmp_path)}
        assert "a.sh" in found
        assert "init.sh" in found


class TestPreFixRunLintFixtureIsCaught:
    """The centrepiece acceptance test (Plan 00200 Phase 5).

    Points the fixed auditor at the EXACT pre-fix content of
    scripts/qa/run_lint.sh (recovered via
    ``git show fad60fa6^:scripts/qa/run_lint.sh``, frozen as a fixture) and
    requires it to flag the swallow. If this test cannot fail before the fix
    and pass after, the auditor is not fixed.
    """

    def test_fixture_exists_and_is_the_historical_content(self) -> None:
        assert PRE_FIX_RUN_LINT_SH.is_file()
        content = PRE_FIX_RUN_LINT_SH.read_text()
        assert "except json.JSONDecodeError:" in content
        assert "ruff_output = []" in content
        # The pre-fix file redirected stderr into the same capture ruff's
        # JSON is parsed from — part of what corrupted it. Confirms this is
        # genuinely the OLD content, not a hand-written approximation.
        assert '.raw" 2>&1' in content

    def test_heredoc_python_audit_flags_the_swallow(self) -> None:
        violations = audit_heredoc_python(PRE_FIX_RUN_LINT_SH)
        assert "silent-fallback" in _rules(violations), (
            "The widened auditor failed to catch the exact bug that started "
            f"Plan 00200. Violations found: {violations}"
        )
        hit = next(v for v in violations if v["rule"] == "silent-fallback")
        assert hit["line"] == 50

    def test_plain_python_only_audit_file_is_blind_to_it(self) -> None:
        """Demonstrates the gap this phase closes: treating the .sh as if it
        were a lone .py file (old behaviour's shape) finds nothing, because
        it isn't valid standalone Python — the swallow is only reachable by
        extracting the heredoc body first."""
        assert audit_file(PRE_FIX_RUN_LINT_SH) == []

    def test_full_shell_collection_pipeline_catches_it(self, tmp_path: Path) -> None:
        """Runs the real orchestration (collect_shell_violations) against a
        synthetic workspace containing only this fixture under scripts/qa/,
        matching how the fix is actually wired into main()."""
        scripts_qa = tmp_path / "scripts" / "qa"
        scripts_qa.mkdir(parents=True)
        target = scripts_qa / "run_lint.sh"
        target.write_text(PRE_FIX_RUN_LINT_SH.read_text())
        violations = collect_shell_violations(tmp_path)
        assert "silent-fallback" in _rules(violations)


class TestRealRepoSelfScan:
    """Self-scan regression guard, mirroring test_audit_shell.py's
    TestRealRepoScan: once Phase 5 triage lands, the repo's own widened scope
    must stay clean (or explicitly excluded) so a re-introduction fails CI
    immediately rather than waiting for someone to notice."""

    def test_repo_is_clean_under_widened_scope(self) -> None:
        from audit_error_hiding import apply_exclusions, load_exclusions

        violations = collect_python_violations(REPO_ROOT) + collect_shell_violations(REPO_ROOT)
        exclusions = load_exclusions(REPO_ROOT / "scripts" / "qa")
        violations = apply_exclusions(violations, exclusions)
        offenders = [f"{v['file']}:{v['line']} [{v['rule']}]" for v in violations]
        assert violations == [], f"Unaddressed error-hiding findings: {offenders}"


class TestStaleExclusionsAreReported:
    """An exclusion that suppresses nothing is a defect, not a no-op.

    Line-keyed exclusions silently drift: editing anything ABOVE one shifts
    the code without shifting the entry, so it then exempts an innocent line
    while the real violation resurfaces elsewhere. That happened twice in one
    session in upgrade_version.sh, and the only signal was two mysterious new
    violations — the mis-targeting itself was invisible.

    Line-keying cannot simply be abolished: every remaining `lines` entry is a
    shell script or a module-level import, where there is no enclosing
    function to key on. So the guard is applied to the exclusion rather than
    to the keying style, and it covers the other rot too — an exclusion whose
    underlying code was FIXED also stops matching, and should be deleted
    rather than left as a standing licence.

    This is the unused-`noqa` pattern (ruff's RUF100) applied to our own
    suppression file.
    """

    def _entry(self, **overrides: Any) -> dict[str, Any]:
        entry = {"file": "a/b.py", "rule": "silent-pass", "lines": [10]}
        entry.update(overrides)
        return entry

    def test_exclusion_matching_nothing_is_reported_as_stale(self) -> None:
        from audit_error_hiding import find_stale_exclusions

        violations = [{"file": "src/a/b.py", "line": 10, "rule": "silent-pass", "function": None}]
        drifted = self._entry(lines=[31])
        stale = find_stale_exclusions(violations, [drifted])
        assert len(stale) == 1
        assert "a/b.py" in stale[0]["message"]

    def test_exclusion_that_matches_is_not_reported(self) -> None:
        from audit_error_hiding import find_stale_exclusions

        violations = [{"file": "src/a/b.py", "line": 10, "rule": "silent-pass", "function": None}]
        assert find_stale_exclusions(violations, [self._entry()]) == []

    def test_function_keyed_exclusions_are_covered_too(self) -> None:
        """A renamed function orphans its exclusion just as surely as an
        edit orphans a line number."""
        from audit_error_hiding import find_stale_exclusions

        violations = [
            {"file": "src/a/b.py", "line": 10, "rule": "silent-pass", "function": "renamed_now"}
        ]
        entry = self._entry(function="old_name")
        entry.pop("lines")
        assert len(find_stale_exclusions(violations, [entry])) == 1

    def test_stale_finding_names_the_two_causes(self) -> None:
        """The message must distinguish drift from fixed-code, since the
        remedies are opposite: realign the entry, or delete it."""
        from audit_error_hiding import find_stale_exclusions

        stale = find_stale_exclusions([], [self._entry()])
        assert stale
        message = stale[0]["message"].lower()
        assert "drift" in message or "moved" in message
        assert "delete" in message or "remove" in message

    def test_the_live_exclusions_file_has_no_stale_entries(self) -> None:
        """The check applied to this repo's real exclusions.

        Positive control for the whole class: the three synthetic tests above
        would all pass against a `find_stale_exclusions` that worked only on
        hand-built dicts. This one runs it against the real 127-entry file
        and the real violation set.
        """
        from audit_error_hiding import find_stale_exclusions, load_exclusions

        violations = collect_python_violations(REPO_ROOT) + collect_shell_violations(REPO_ROOT)
        exclusions = load_exclusions(REPO_ROOT / "scripts" / "qa")
        assert exclusions, "no exclusions loaded — the control proves nothing"
        stale = find_stale_exclusions(violations, exclusions)
        assert stale == [], f"Stale exclusions: {[s['message'] for s in stale]}"


class TestAuditDirectoryUnaffectedByWidening:
    """audit_directory (the pre-existing Python-only scanner) keeps working
    unchanged — widening is additive, not a rewrite of the existing path."""

    def test_still_scans_py_files_recursively(self, tmp_path: Path) -> None:
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "mod.py").write_text("try:\n    risky()\nexcept:\n    pass\n")
        violations = audit_directory(tmp_path)
        assert "silent-pass" in _rules(violations)
