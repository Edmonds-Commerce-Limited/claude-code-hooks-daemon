"""The security gate must fail when bandit could not check something (00466 N21).

``run_security_check.sh`` discarded bandit's own exit code and read only
``results[]`` from its JSON capture. Bandit puts a file it could NOT scan
(syntax error, missing path, ...) into a top-level ``errors[]`` array and
still exits 0 -- that file was never checked by any rule, so ``results[]``
alone cannot distinguish "clean" from "blind". A CLI usage error (bad flag,
bad config) exits 2 and writes no output file at all; the old script read
``bandit_output = {}`` for a missing/empty raw file and reported
``passed: true`` over a scan that never ran.

These tests drive the real wrapper end to end (real bandit, planted targets),
so the proof is the gate's own exit code, not a re-implementation of it.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_WRAPPER = _REPO_ROOT / "scripts" / "qa" / "run_security_check.sh"
_WRAPPER_TIMEOUT_SECONDS = 300

_FAKE_BANDIT_CLI_ERROR = """#!/bin/sh
# Simulates `bandit: error: unrecognized arguments: ...` -- exits 2 and
# writes NO output file, matching real bandit's behaviour on a usage error.
echo "bandit: error: unrecognized arguments: --bogus-flag" >&2
exit 2
"""

_FAKE_BANDIT_NO_OUTPUT = """#!/bin/sh
# Exits 0 (as if clean) but never writes the -o output file at all.
exit 0
"""


def _run_gate(
    tmp_path: Path, *, targets: str, bandit_bin: str = ""
) -> tuple[subprocess.CompletedProcess[str], dict]:
    """Run the real wrapper with QA_SECURITY_* overrides; return (process, JSON).

    SECURITY: fixed argv, no shell, the repository's own QA wrapper.
    """
    output_dir = tmp_path / "qa"
    env = {
        **os.environ,
        "QA_SECURITY_OUTPUT_DIR": str(output_dir),
        "QA_SECURITY_TARGETS": targets,
    }
    if bandit_bin:
        env["QA_SECURITY_BANDIT_BIN"] = bandit_bin
    completed = subprocess.run(
        ["bash", str(_WRAPPER)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        timeout=_WRAPPER_TIMEOUT_SECONDS,
        check=False,
    )
    output = json.loads((output_dir / "security.json").read_text(encoding="utf-8"))
    return completed, output


def _write_fake_bandit(tmp_path: Path, script: str) -> str:
    fake = tmp_path / "fake-bandit"
    fake.write_text(script, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return str(fake)


class TestSecurityGateFailsClosed:
    def test_a_file_bandit_could_not_scan_fails_the_gate(self, tmp_path: Path) -> None:
        """The errors[] shape: bandit exits 0 having scanned nothing in one file."""
        target = tmp_path / "broken.py"
        target.write_text("def f(:\n    pass\n", encoding="utf-8")

        completed, output = _run_gate(tmp_path, targets=str(target))

        assert completed.returncode != 0, completed.stdout + completed.stderr
        assert output["summary"]["passed"] is False
        assert "error" in output["summary"], "llm_qa must show the TOOL ERROR line"
        assert output["summary"]["total_issues"] >= 1
        (entry,) = output["issues"]
        assert (
            "could not" in entry["message"].lower()
            or "could not" in output["summary"]["error"].lower()
        )
        assert target.name in entry["file"]

    def test_a_bandit_cli_usage_error_fails_the_gate_naming_the_exit_code(
        self, tmp_path: Path
    ) -> None:
        """Exit 2, no output file at all -- must not be read as a clean scan."""
        target = tmp_path / "quick.py"
        target.write_text("x = 1\n", encoding="utf-8")
        fake_bin = _write_fake_bandit(tmp_path, _FAKE_BANDIT_CLI_ERROR)

        completed, output = _run_gate(tmp_path, targets=str(target), bandit_bin=fake_bin)

        assert completed.returncode != 0, completed.stdout + completed.stderr
        assert output["summary"]["passed"] is False
        assert "2" in output["summary"]["error"]
        assert output["summary"]["total_issues"] >= 1
        assert output["issues"], "count without detail is the defect this fix removes"

    def test_a_missing_raw_output_file_fails_the_gate(self, tmp_path: Path) -> None:
        """bandit exits 0 but never wrote the raw JSON -- nothing was checked."""
        target = tmp_path / "quick.py"
        target.write_text("x = 1\n", encoding="utf-8")
        fake_bin = _write_fake_bandit(tmp_path, _FAKE_BANDIT_NO_OUTPUT)

        completed, output = _run_gate(tmp_path, targets=str(target), bandit_bin=fake_bin)

        assert completed.returncode != 0, completed.stdout + completed.stderr
        assert output["summary"]["passed"] is False
        assert output["issues"], "count without detail is the defect this fix removes"

    def test_a_clean_target_still_passes(self, tmp_path: Path) -> None:
        """No false alarm: a file bandit finds nothing wrong with is a clean run."""
        target = tmp_path / "quick.py"
        target.write_text("x = 1\n", encoding="utf-8")

        completed, output = _run_gate(tmp_path, targets=str(target))

        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert output["summary"]["passed"] is True
        assert output["issues"] == []
        assert "error" not in output["summary"]
