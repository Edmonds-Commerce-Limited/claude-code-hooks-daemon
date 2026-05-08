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
