"""Tests for the capture-corruption auditor (scripts/qa/audit_capture_corruption.py).

Plan 00105 Phase 2 Task 2.1.

The auditor enforces two complementary rules against shell scripts:

1. **Captured-function rule** — any function called via ``$(name ...)`` must
   only emit to stdout at terminal-return positions. Mid-function status
   echoes corrupt the captured value.

2. **Log-helper rule** — functions named ``print_*``, ``log_*``, ``warn_*``,
   ``err_*``, ``error_*``, ``fail_*``, ``die_*``, ``info_*`` must redirect
   every ``echo``/``printf`` with ``>&2``. The v3.10.0 SEV-1 was a missing
   ``>&2`` on ``print_info`` that ended up corrupting every
   ``VAR=$(ensure_venv ...)`` capture in the field.

These rules attack the same root cause from two angles. The captured-function
rule alone misses log helpers that are not yet captured but get captured in
future code. The log-helper rule alone misses non-conventionally-named
functions that ARE captured today.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "qa"))
from audit_capture_corruption import (
    Violation,
    audit_files,
)


def _rules(violations: list[Violation]) -> list[str]:
    return [v.rule for v in violations]


def _write(tmp_path: Path, name: str, body: str) -> Path:
    target = tmp_path / name
    target.write_text(body)
    return target


# ── Captured-function rule ─────────────────────────────────────────


class TestCapturedFunctionRule:
    """Functions called via $(name ...) must only emit at terminal returns."""

    def test_clean_terminal_return_passes(self, tmp_path: Path) -> None:
        defn = _write(
            tmp_path,
            "lib.sh",
            '#!/bin/bash\nresolve_path() {\n    echo "$resolved"\n}\n',
        )
        caller = _write(tmp_path, "use.sh", "#!/bin/bash\nVAR=$(resolve_path /a)\n")
        violations = audit_files([defn, caller])
        assert violations == []

    def test_mid_function_stdout_emit_fails(self, tmp_path: Path) -> None:
        defn = _write(
            tmp_path,
            "lib.sh",
            "#!/bin/bash\n"
            "resolve_path() {\n"
            '    echo "found path"\n'
            '    echo "$resolved"\n'
            "}\n",
        )
        caller = _write(tmp_path, "use.sh", "#!/bin/bash\nVAR=$(resolve_path /a)\n")
        violations = audit_files([defn, caller])
        assert "capture-corruption" in _rules(violations)
        assert any(v.function == "resolve_path" for v in violations)

    def test_uncaptured_function_is_not_audited(self, tmp_path: Path) -> None:
        defn = _write(
            tmp_path,
            "lib.sh",
            "#!/bin/bash\n" "show_status() {\n" '    echo "step 1"\n' '    echo "step 2"\n' "}\n",
        )
        violations = audit_files([defn])
        assert violations == []

    def test_alt_branch_returns_pass(self, tmp_path: Path) -> None:
        defn = _write(
            tmp_path,
            "lib.sh",
            "#!/bin/bash\n"
            "pick() {\n"
            "    if [[ -n $1 ]]; then\n"
            '        echo "$1"\n'
            "    else\n"
            '        echo "default"\n'
            "    fi\n"
            "}\n",
        )
        caller = _write(tmp_path, "use.sh", "#!/bin/bash\nV=$(pick X)\n")
        violations = audit_files([defn, caller])
        assert violations == []

    def test_marker_with_reason_suppresses(self, tmp_path: Path) -> None:
        defn = _write(
            tmp_path,
            "lib.sh",
            "#!/bin/bash\n"
            "resolve_path() {\n"
            '    echo "informational" # capture-audit: allow -- printed before stderr is set up\n'
            '    echo "$resolved"\n'
            "}\n",
        )
        caller = _write(tmp_path, "use.sh", "#!/bin/bash\nVAR=$(resolve_path /a)\n")
        violations = audit_files([defn, caller])
        assert violations == []

    def test_bare_marker_without_reason_is_violation(self, tmp_path: Path) -> None:
        defn = _write(
            tmp_path,
            "lib.sh",
            "#!/bin/bash\n"
            "resolve_path() {\n"
            '    echo "informational" # capture-audit: allow\n'
            '    echo "$resolved"\n'
            "}\n",
        )
        caller = _write(tmp_path, "use.sh", "#!/bin/bash\nVAR=$(resolve_path /a)\n")
        violations = audit_files([defn, caller])
        assert "marker-missing-reason" in _rules(violations)

    def test_function_level_marker_above_def_suppresses(self, tmp_path: Path) -> None:
        defn = _write(
            tmp_path,
            "lib.sh",
            "#!/bin/bash\n"
            "# capture-audit: allow -- legacy entry point, never captured\n"
            "ensure_venv() {\n"
            '    echo "Status message"\n'
            "    real_work\n"
            "}\n",
        )
        caller = _write(tmp_path, "use.sh", "#!/bin/bash\nVAR=$(ensure_venv /a)\n")
        violations = audit_files([defn, caller])
        assert violations == []


# ── Redirect-consumption rule (Plan 00200 Task 1.6) ───────────────


class TestRedirectConsumptionRule:
    """A ``cmd > file`` / ``cmd >> file`` redirect is as risky as ``$(cmd)``.

    Reproduces the exact historical miss: ``run_lint.sh`` corrupted its
    ruff JSON capture via ``venv_tool ruff ... > "${OUTPUT_FILE}.raw"`` --
    a plain file redirect, not a ``$(...)``/backtick command substitution.
    The pre-fix auditor had no regex recognising ``>``/``>>`` as a risky
    consumption context at all, so ``venv_tool`` (and, transitively,
    ``ensure_venv`` which it calls) was never audited.
    """

    def test_redirected_function_stdout_emit_fails(self, tmp_path: Path) -> None:
        defn = _write(
            tmp_path,
            "lib.sh",
            "#!/bin/bash\n" "run_tool() {\n" '    echo "banner"\n' '    "$1"\n' "}\n",
        )
        caller = _write(tmp_path, "use.sh", '#!/bin/bash\nrun_tool ruff > "${OUT}.raw"\n')
        violations = audit_files([defn, caller])
        assert "capture-corruption" in _rules(violations)
        assert any(v.function == "run_tool" for v in violations)

    def test_redirected_function_has_no_terminal_position_exemption(self, tmp_path: Path) -> None:
        """Unlike ``$(...)`` capture, a redirect has no privileged 'last echo'.

        A redirect concatenates the ENTIRE stdout stream of everything that
        runs before the redirect closes -- including whatever the tool
        invoked immediately afterwards also writes. So even an echo
        immediately before ``return`` (which the captured-function rule's
        terminal-position heuristic treats as safe -- it looks like the
        function's intended ``$(...)`` return value) is NOT safe here:
        anything else that runs later in the same redirected pipeline still
        lands in the file after it.
        """
        defn = _write(
            tmp_path,
            "lib.sh",
            "#!/bin/bash\n" "run_tool() {\n" '    echo "banner"\n' "    return 0\n" "}\n",
        )
        caller = _write(tmp_path, "use.sh", '#!/bin/bash\nrun_tool > "${OUT}.raw"\n')
        violations = audit_files([defn, caller])
        assert "capture-corruption" in _rules(violations)

    def test_append_redirect_is_also_detected(self, tmp_path: Path) -> None:
        defn = _write(
            tmp_path,
            "lib.sh",
            "#!/bin/bash\n" "run_tool() {\n" '    echo "banner"\n' "}\n",
        )
        caller = _write(tmp_path, "use.sh", '#!/bin/bash\nrun_tool >> "${OUT}.raw"\n')
        violations = audit_files([defn, caller])
        assert "capture-corruption" in _rules(violations)

    def test_redirect_to_stderr_is_not_a_redirect_consumption(self, tmp_path: Path) -> None:
        """``cmd 2>&1`` alone (no ``>``) does not send stdout to a file."""
        defn = _write(
            tmp_path,
            "lib.sh",
            "#!/bin/bash\n" "run_tool() {\n" '    echo "banner"\n' "}\n",
        )
        caller = _write(tmp_path, "use.sh", "#!/bin/bash\nrun_tool 2>&1\n")
        violations = audit_files([defn, caller])
        assert violations == []

    def test_callee_of_a_redirected_function_is_also_audited(self, tmp_path: Path) -> None:
        """Reproduces the actual historical shape: the redirected function
        (``venv_tool``) delegates its own stdout hygiene to a callee
        (``ensure_venv``) that it invokes by bare name, not ``$(...)``. The
        redirect on the OUTER call must propagate one level into the callee
        for this class of bug to be caught at all.
        """
        defn = _write(
            tmp_path,
            "lib.sh",
            "#!/bin/bash\n"
            "ensure_venv() {\n"
            '    echo "Venv exists"\n'
            "    return 0\n"
            "}\n"
            "venv_tool() {\n"
            "    ensure_venv || return 1\n"
            '    "$1"\n'
            "}\n",
        )
        caller = _write(tmp_path, "use.sh", '#!/bin/bash\nvenv_tool ruff > "${OUT}.raw"\n')
        violations = audit_files([defn, caller])
        assert "capture-corruption" in _rules(violations)
        assert any(v.function == "ensure_venv" for v in violations)

    def test_name_collision_across_files_does_not_leak_risk_to_the_other_definition(
        self, tmp_path: Path
    ) -> None:
        """Regression: two files defining a same-named function must not
        cross-contaminate. This reproduces a false positive found while
        implementing the redirect rule: the real repo has TWO unrelated
        ``ensure_venv`` functions (``venv-include.bash`` and
        ``scripts/install/venv.sh``). Flagging by bare name alone -- rather
        than the specific ``(file, name)`` definition -- caused the
        propagation step to wrongly mark the SECOND, entirely unrelated
        (and never redirect-consumed) ``ensure_venv`` as zero-tolerance too,
        purely because a function of the same name, in a DIFFERENT file, was
        legitimately at risk.
        """
        risky_file = _write(
            tmp_path,
            "risky.sh",
            "#!/bin/bash\n"
            "ensure_venv() {\n"
            '    echo "banner"\n'
            "    return 0\n"
            "}\n"
            "venv_tool() {\n"
            "    ensure_venv || return 1\n"
            '    "$1"\n'
            "}\n",
        )
        unrelated_file = _write(
            tmp_path,
            "unrelated.sh",
            "#!/bin/bash\n"
            "ensure_venv() {\n"
            '    echo "$resolved_path"\n'  # legitimate $(...) terminal return
            "}\n",
        )
        caller1 = _write(tmp_path, "use1.sh", '#!/bin/bash\nvenv_tool ruff > "${OUT}.raw"\n')
        caller2 = _write(tmp_path, "use2.sh", "#!/bin/bash\nVAR=$(ensure_venv /a)\n")

        violations = audit_files([risky_file, unrelated_file, caller1, caller2])

        risky_violations = [v for v in violations if v.file == str(risky_file)]
        unrelated_violations = [v for v in violations if v.file == str(unrelated_file)]
        assert "capture-corruption" in _rules(
            risky_violations
        ), "The redirect-consumed ensure_venv (risky.sh) must still be caught"
        assert unrelated_violations == [], (
            "The unrelated, never-redirected ensure_venv (unrelated.sh) must NOT "
            f"be flagged just because a same-named function elsewhere is at risk: "
            f"{unrelated_violations}"
        )

    def test_clean_redirected_function_passes(self, tmp_path: Path) -> None:
        defn = _write(
            tmp_path,
            "lib.sh",
            "#!/bin/bash\n" 'run_tool() {\n    echo "banner" >&2\n    "$1"\n}\n',
        )
        caller = _write(tmp_path, "use.sh", '#!/bin/bash\nrun_tool ruff > "${OUT}.raw"\n')
        violations = audit_files([defn, caller])
        assert violations == []


# ── Log-helper rule ────────────────────────────────────────────────


class TestLogHelperRule:
    """print_* / log_* / fail_* etc. must always redirect to stderr."""

    def test_print_info_to_stdout_is_violation(self, tmp_path: Path) -> None:
        src = _write(
            tmp_path,
            "out.sh",
            "#!/bin/bash\n" "print_info() {\n" '    echo "  $1"\n' "}\n",
        )
        violations = audit_files([src])
        assert "log-helper-stdout" in _rules(violations)

    def test_print_info_redirected_to_stderr_passes(self, tmp_path: Path) -> None:
        src = _write(
            tmp_path,
            "out.sh",
            "#!/bin/bash\n" "print_info() {\n" '    echo "  $1" >&2\n' "}\n",
        )
        violations = audit_files([src])
        assert violations == []

    def test_fail_fast_partial_stderr_redirect_is_violation(self, tmp_path: Path) -> None:
        src = _write(
            tmp_path,
            "out.sh",
            "#!/bin/bash\n"
            "fail_fast() {\n"
            '    print_error "$1"\n'
            '    echo ""\n'
            '    echo "Operation aborted."\n'
            "    exit 1\n"
            "}\n",
        )
        violations = audit_files([src])
        log_violations = [v for v in violations if v.rule == "log-helper-stdout"]
        assert len(log_violations) == 2

    def test_log_helper_with_pipe_passes(self, tmp_path: Path) -> None:
        src = _write(
            tmp_path,
            "out.sh",
            "#!/bin/bash\n" "log_thing() {\n" '    echo "$1" | tr a-z A-Z >&2\n' "}\n",
        )
        violations = audit_files([src])
        assert violations == []


# ── Real-repo smoke ────────────────────────────────────────────────


class TestRealRepoIsClean:
    """Phase 2 acceptance: the repo as it stands today must pass the audit.

    Phase 2 Task 2.1 fixed the two known real violations (``print_info``
    writing to stdout, ``fail_fast`` echoing plain) and added the
    function-level marker on legacy ``ensure_venv``. Any future regression
    that re-introduces the v3.10.0 shape will be caught here AND in the QA
    pipeline (``run_capture_corruption_check.sh``).
    """

    def test_default_scan_dirs_clean(self) -> None:
        from audit_capture_corruption import (
            DEFAULT_SCAN_DIRS,
            _collect_shell_files,
        )

        files = _collect_shell_files(list(DEFAULT_SCAN_DIRS))
        assert len(files) > 0
        violations = audit_files(files)
        assert violations == [], "Real-repo capture-corruption regression: " + "; ".join(
            f"{v.file}:{v.line} [{v.function}] [{v.rule}] {v.message}" for v in violations[:5]
        )
