"""Tests for the shell-script error-hiding auditor (scripts/qa/audit_shell.py).

Gap closed here: the Python AST auditor in scripts/qa/audit_error_hiding.py
never scans .sh/.bash files, so shell-level error hiding like
``cmd 2>/dev/null || true`` slipped through the QA pipeline for the
lifetime of the project — exactly how the hooks_deploy.sh chmod-silencer
(issue #29) got committed.

The shell auditor:

- Scans .sh / .bash files under scripts/ (configurable)
- Flags combined stderr+exit-code suppression patterns:
  ``2>/dev/null || true``, ``>/dev/null 2>&1 || true``, ``&>/dev/null || true``
- Allows explicit per-line opt-out via a ``# shell-audit: allow -- <reason>``
  marker, either inline or on the line immediately above
- Emits JSON output compatible with llm_qa.py

The marker is preferred over a central exclusions JSON because it co-locates
the justification with the code — the same line-drift argument used in the
Python auditor's exclusions file applies here, but markers solve it without
needing a lookup table.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "qa"))
from audit_shell import (
    Violation,
    audit_file,
    audit_text,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
AUDIT_SHELL_SCRIPT = REPO_ROOT / "scripts" / "qa" / "audit_shell.py"


def _rules(violations: list[Violation]) -> list[str]:
    return [v.rule for v in violations]


class TestDetectsDoubleSuppression:
    """The core motivating case: ``2>/dev/null || true`` silences both streams."""

    def test_detects_stderr_to_devnull_or_true(self) -> None:
        violations = audit_text(
            "#!/bin/bash\nchmod +x hook 2>/dev/null || true\n",
            "<test>",
        )
        assert "double-suppression" in _rules(violations)
        assert any(v.line == 2 for v in violations)

    def test_detects_both_streams_devnull_or_true(self) -> None:
        violations = audit_text(
            "#!/bin/bash\nrm target >/dev/null 2>&1 || true\n",
            "<test>",
        )
        assert "double-suppression" in _rules(violations)

    def test_detects_ampersand_devnull_or_true(self) -> None:
        violations = audit_text(
            "#!/bin/bash\nrm target &>/dev/null || true\n",
            "<test>",
        )
        assert "double-suppression" in _rules(violations)

    def test_reports_multiple_violations_in_same_file(self) -> None:
        src = "#!/bin/bash\ncmd_a 2>/dev/null || true\ncmd_b 2>/dev/null || true\n"
        violations = audit_text(src, "<test>")
        lines = sorted(v.line for v in violations)
        assert lines == [2, 3]


class TestInlineMarkerAllowsSuppression:
    """Inline marker on the same line is an explicit per-call opt-out."""

    def test_inline_marker_suppresses_violation(self) -> None:
        src = (
            "#!/bin/bash\n"
            "kill_daemon 2>/dev/null || true  # shell-audit: allow -- daemon may not be running\n"
        )
        violations = audit_text(src, "<test>")
        assert violations == []

    def test_inline_marker_requires_reason_after_double_dash(self) -> None:
        # Marker without a reason is rejected — forces the author to document why.
        src = "#!/bin/bash\nkill_daemon 2>/dev/null || true  # shell-audit: allow\n"
        violations = audit_text(src, "<test>")
        assert "marker-missing-reason" in _rules(violations)


class TestAboveLineMarkerAllowsSuppression:
    """Marker on the line *above* covers the line below — useful for long commands."""

    def test_above_line_marker_suppresses_violation(self) -> None:
        src = (
            "#!/bin/bash\n"
            "# shell-audit: allow -- snapshot restore is best-effort\n"
            "cp snap/settings.json .claude/ 2>/dev/null || true\n"
        )
        violations = audit_text(src, "<test>")
        assert violations == []

    def test_above_line_marker_only_covers_next_line(self) -> None:
        # Marker covers line+1 only; a second suppression two lines later is still flagged.
        src = (
            "#!/bin/bash\n"
            "# shell-audit: allow -- first call is best-effort\n"
            "cmd_a 2>/dev/null || true\n"
            "cmd_b 2>/dev/null || true\n"
        )
        violations = audit_text(src, "<test>")
        assert len(violations) == 1
        assert violations[0].line == 4


class TestIgnoresNonShellPatterns:
    """Don't report false positives on patterns that only look similar."""

    def test_plain_comment_line_is_ignored(self) -> None:
        src = "#!/bin/bash\n# cmd 2>/dev/null || true (documenting the anti-pattern)\n"
        violations = audit_text(src, "<test>")
        assert violations == []

    def test_devnull_without_or_true_is_allowed(self) -> None:
        # ``2>/dev/null`` alone (without ``|| true``) is sometimes legitimate — we only
        # flag the *combined* pattern because that's the one with no recovery path.
        src = "#!/bin/bash\nquiet_cmd 2>/dev/null\n"
        violations = audit_text(src, "<test>")
        assert violations == []

    def test_or_true_without_devnull_is_allowed_for_now(self) -> None:
        # Bare ``|| true`` is a separate concern (and has legitimate uses like
        # grep-with-no-match in pipelines); the current scope is double-suppression.
        src = "#!/bin/bash\nrm target || true\n"
        violations = audit_text(src, "<test>")
        assert violations == []


class TestAuditFile:
    """File-based audit wraps audit_text and reports the filename."""

    def test_audit_file_reports_violations_with_filepath(self, tmp_path: Path) -> None:
        script = tmp_path / "example.sh"
        script.write_text("#!/bin/bash\nchmod +x target 2>/dev/null || true\n")
        violations = audit_file(script)
        assert len(violations) == 1
        assert violations[0].file.endswith("example.sh")
        assert violations[0].line == 2
        assert violations[0].rule == "double-suppression"

    def test_audit_file_clean_file_returns_empty(self, tmp_path: Path) -> None:
        script = tmp_path / "clean.sh"
        script.write_text("#!/bin/bash\nset -euo pipefail\nchmod +x target\n")
        assert audit_file(script) == []


class TestJsonOutput:
    """--json flag writes the QA-pipeline-compatible JSON contract."""

    def test_json_output_schema_matches_qa_pipeline(self, tmp_path: Path) -> None:
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "violator.sh").write_text(
            "#!/bin/bash\nchmod +x target 2>/dev/null || true\n"
        )
        output_json = tmp_path / "shell_audit.json"

        result = subprocess.run(
            [
                sys.executable,
                str(AUDIT_SHELL_SCRIPT),
                "--json",
                "--scan-dir",
                str(scripts_dir),
                "--output",
                str(output_json),
            ],
            capture_output=True,
            text=True,
        )
        # Non-zero exit when violations exist (QA pipeline contract).
        assert result.returncode == 1, f"stderr={result.stderr!r}"
        assert output_json.exists()
        data = json.loads(output_json.read_text())
        assert "summary" in data
        assert data["summary"]["total_violations"] == 1
        assert data["summary"]["passed"] is False
        assert len(data["violations"]) == 1
        v = data["violations"][0]
        assert v["rule"] == "double-suppression"
        assert v["file"].endswith("violator.sh")
        assert v["line"] == 2

    def test_json_output_clean_scan_is_passing(self, tmp_path: Path) -> None:
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "clean.sh").write_text("#!/bin/bash\nset -euo pipefail\necho ok\n")
        output_json = tmp_path / "shell_audit.json"

        result = subprocess.run(
            [
                sys.executable,
                str(AUDIT_SHELL_SCRIPT),
                "--json",
                "--scan-dir",
                str(scripts_dir),
                "--output",
                str(output_json),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"stderr={result.stderr!r}"
        data = json.loads(output_json.read_text())
        assert data["summary"]["passed"] is True
        assert data["summary"]["total_violations"] == 0
        assert data["violations"] == []


class TestRealRepoScan:
    """Self-scan: once markers are added, the repo's own scripts must pass.

    This is the integration-style guard that prevents regression: if anyone
    re-introduces ``2>/dev/null || true`` without a marker, CI fires.
    """

    def test_repo_scripts_directory_is_clean_or_marked(self) -> None:
        scripts_dir = REPO_ROOT / "scripts"
        assert scripts_dir.is_dir()
        violations: list[Violation] = []
        for shell_script in scripts_dir.rglob("*.sh"):
            violations.extend(audit_file(shell_script))
        offenders = [f"{v.file}:{v.line}" for v in violations]
        assert violations == [], (
            "Shell scripts contain unmarked error suppression. Either fix the "
            f"code or add '# shell-audit: allow -- <reason>' marker. Offenders: {offenders}"
        )
