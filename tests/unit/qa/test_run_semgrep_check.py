"""The semgrep gate must fail when semgrep could not check something (00466 N21).

A rule that times out on a file has checked nothing in that file, but semgrep
reports the timeout as a ``warn`` entry in its JSON ``errors[]`` and still
exits 0. ``run_semgrep_check.sh`` used to read only ``results[]``, so the gate
passed: it failed OPEN, and the slower a rule, the likelier it was to be
skipped on exactly the large files it exists for. Found when a draft of the
``freshness-verdict-read-piecemeal`` rule timed out on ``daemon/cli.py`` -- the
one file holding the defect it was written to catch.

These tests drive the real wrapper end to end against a rule built to time
out, so the proof is the gate's own exit code, not a re-implementation of it.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_WRAPPER = _REPO_ROOT / "scripts" / "qa" / "run_semgrep_check.sh"

# Four ellipsis-separated metavariables over a 300-argument call is a
# combinatorial match that cannot finish inside a one-second budget; the
# comparison can never hold, so a finished run would report nothing at all.
_SLOW_RULE = """rules:
  - id: forced-timeout
    languages: [python]
    severity: WARNING
    message: built to time out
    patterns:
      - pattern: foo(..., $A, ..., $B, ..., $C, ..., $D, ...)
      - metavariable-comparison:
          comparison: str($A) == "never"
"""
_SLOW_CALL_ARGUMENTS = 300
_FORCED_TIMEOUT_SECONDS = "1"
_WRAPPER_TIMEOUT_SECONDS = 300


def _run_gate(
    tmp_path: Path, target: Path, timeout: str = _FORCED_TIMEOUT_SECONDS
) -> tuple[subprocess.CompletedProcess[str], dict]:
    """Run the wrapper against ``target`` with the slow rule; return (process, output JSON).

    SECURITY: fixed argv, no shell, the repository's own QA wrapper.
    """
    rules = tmp_path / "rules"
    rules.mkdir(exist_ok=True)
    (rules / "slow.yaml").write_text(_SLOW_RULE, encoding="utf-8")
    output_dir = tmp_path / "qa"
    env = {
        **os.environ,
        "QA_SEMGREP_RULES_DIR": str(rules),
        "QA_SEMGREP_TARGETS": str(target),
        "QA_SEMGREP_OUTPUT_DIR": str(output_dir),
        "QA_SEMGREP_TIMEOUT": timeout,
    }
    completed = subprocess.run(
        ["bash", str(_WRAPPER)],
        capture_output=True,
        text=True,
        env=env,
        timeout=_WRAPPER_TIMEOUT_SECONDS,
        check=False,
    )
    output = json.loads((output_dir / "semgrep.json").read_text(encoding="utf-8"))
    return completed, output


@pytest.fixture()
def slow_target(tmp_path: Path) -> Path:
    args = ", ".join(f"a{index}" for index in range(_SLOW_CALL_ARGUMENTS))
    target = tmp_path / "slow.py"
    target.write_text(f"foo({args})\n", encoding="utf-8")
    return target


class TestSemgrepGateFailsClosed:
    def test_a_rule_timeout_fails_the_gate_naming_rule_and_file(
        self, tmp_path: Path, slow_target: Path
    ) -> None:
        completed, output = _run_gate(tmp_path, slow_target)

        assert completed.returncode != 0, completed.stdout + completed.stderr
        assert output["summary"]["passed"] is False
        reported = " ".join(completed.stdout.split())
        assert "forced-timeout" in reported
        assert str(slow_target) in reported or slow_target.name in reported
        assert "Timeout" in reported
        assert output["summary"]["total_violations"] == 1
        assert "error" in output["summary"], "llm_qa must show the TOOL ERROR line"
        (entry,) = output["violations"]
        assert entry["rule"] == "forced-timeout"
        assert entry["error_type"] == "Timeout"
        assert entry["file"].endswith(slow_target.name)

    def test_a_clean_target_still_passes(self, tmp_path: Path) -> None:
        """No false alarm: a file the rule finishes on is a clean run."""
        target = tmp_path / "quick.py"
        target.write_text("foo(a, b)\n", encoding="utf-8")

        completed, output = _run_gate(tmp_path, target)

        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert output["summary"]["passed"] is True
        assert output["violations"] == []
        assert "error" not in output["summary"]

    def test_a_semgrep_crash_never_reuses_the_previous_runs_output(self, tmp_path: Path) -> None:
        """A run that writes nothing must not be graded on the last run's file.

        A usage error (here an unparseable --timeout) makes semgrep exit 2 and
        write no output, while the previous clean run's raw JSON is still on
        disk.
        """
        target = tmp_path / "quick.py"
        target.write_text("foo(a, b)\n", encoding="utf-8")
        first, _ = _run_gate(tmp_path, target)
        assert first.returncode == 0, first.stdout + first.stderr

        crashed, output = _run_gate(tmp_path, target, timeout="not-a-number")

        assert crashed.returncode != 0, crashed.stdout + crashed.stderr
        assert output["summary"]["passed"] is False
