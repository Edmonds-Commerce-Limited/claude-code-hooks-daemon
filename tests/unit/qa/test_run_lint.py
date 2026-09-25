"""The lint gate must fail when ruff could not check something (00466 N21).

``run_lint.sh`` discarded ruff's own exit code and read only its stdout
capture. A bad rule code or config makes ruff exit 2 with EMPTY stdout (no
JSON at all) -- the old script read that as ``ruff_output = []`` via the
st_size guard, which is indistinguishable from a genuinely clean scan, and
reported ``passed: true`` over a lint that never ran.

These tests drive the real wrapper end to end (a fake ruff binary for the
exit-code cases, the real ruff for the clean-run sanity check), so the proof
is the gate's own exit code, not a re-implementation of it.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_WRAPPER = _REPO_ROOT / "scripts" / "qa" / "run_lint.sh"
_WRAPPER_TIMEOUT_SECONDS = 300

_FAKE_RUFF_BAD_CONFIG = """#!/bin/sh
# Simulates a bad rule code/config: exits 2, empty stdout, diagnostic on
# stderr -- matching real ruff's behaviour on an invalid --select value.
echo "error: invalid value for '--select <RULE_CODE>'" >&2
exit 2
"""

_FAKE_RUFF_NO_OUTPUT = """#!/bin/sh
# Exits 0 (as if clean) but writes nothing to stdout at all -- distinct from
# a genuinely empty violations list, which real ruff also spells as "[]".
exit 0
"""


def _run_gate(
    tmp_path: Path, *, paths: str, ruff_bin: str = ""
) -> tuple[subprocess.CompletedProcess[str], dict]:
    """Run the real wrapper with QA_LINT_* overrides; return (process, JSON).

    SECURITY: fixed argv, no shell, the repository's own QA wrapper.
    """
    output_dir = tmp_path / "qa"
    env = {
        **os.environ,
        "QA_LINT_OUTPUT_DIR": str(output_dir),
        "QA_LINT_PATHS": paths,
    }
    if ruff_bin:
        env["QA_LINT_RUFF_BIN"] = ruff_bin
    completed = subprocess.run(
        ["bash", str(_WRAPPER)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        timeout=_WRAPPER_TIMEOUT_SECONDS,
        check=False,
    )
    output = json.loads((output_dir / "lint.json").read_text(encoding="utf-8"))
    return completed, output


def _write_fake_ruff(tmp_path: Path, script: str) -> str:
    fake = tmp_path / "fake-ruff"
    fake.write_text(script, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return str(fake)


class TestLintGateFailsClosed:
    def test_a_bad_config_exit_fails_the_gate_naming_the_exit_code(self, tmp_path: Path) -> None:
        """Exit 2, empty stdout -- must not be read as an empty violation list."""
        target = tmp_path / "quick.py"
        target.write_text("x = 1\n", encoding="utf-8")
        fake_bin = _write_fake_ruff(tmp_path, _FAKE_RUFF_BAD_CONFIG)

        completed, output = _run_gate(tmp_path, paths=str(target), ruff_bin=fake_bin)

        assert completed.returncode != 0, completed.stdout + completed.stderr
        assert output["summary"]["passed"] is False
        assert "2" in output["summary"]["error"]
        assert output["summary"]["total_violations"] >= 1
        assert output["violations"], "count without detail is the defect this fix removes"

    def test_a_missing_stdout_capture_fails_the_gate(self, tmp_path: Path) -> None:
        """ruff exits 0 but the capture file is empty -- must not pass silently."""
        target = tmp_path / "quick.py"
        target.write_text("x = 1\n", encoding="utf-8")
        fake_bin = _write_fake_ruff(tmp_path, _FAKE_RUFF_NO_OUTPUT)

        completed, output = _run_gate(tmp_path, paths=str(target), ruff_bin=fake_bin)

        assert completed.returncode != 0, completed.stdout + completed.stderr
        assert output["summary"]["passed"] is False
        assert output["violations"], "count without detail is the defect this fix removes"

    def test_a_clean_target_still_passes(self, tmp_path: Path) -> None:
        """No false alarm: real ruff on a clean file is a clean run."""
        target = tmp_path / "quick.py"
        target.write_text("x = 1\n", encoding="utf-8")

        completed, output = _run_gate(tmp_path, paths=str(target))

        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert output["summary"]["passed"] is True
        assert output["violations"] == []
        assert "error" not in output["summary"]
