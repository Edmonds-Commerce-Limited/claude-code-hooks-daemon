"""format.json must agree with black's own exit code (00466 N21).

``run_format_check.sh`` captures black's exit code correctly (``EXIT_CODE``,
used at the very end of the script) but the JSON it writes along the way
never reads it. Black exits 123 ("error: cannot format") when a file cannot
even be PARSED -- distinct from "0 files need reformatting" -- yet the parser
only ever looked for ``"reformatted <file>"`` lines, so a file black could
not touch at all produced an empty ``violations`` list and
``format.json``'s ``summary.passed: true``, while the process itself
correctly exited 123. The script's own exit code was right; only the JSON
disagreed with it.

These tests drive the real wrapper end to end against a file real black
cannot parse, so the proof is the gate's own JSON and exit code together,
not a re-implementation of black's parser.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_WRAPPER = _REPO_ROOT / "scripts" / "qa" / "run_format_check.sh"
_WRAPPER_TIMEOUT_SECONDS = 300

# Valid Python 3.11 syntax (parses fine) but tagged for a Python version this
# interpreter cannot parse back out during black's AST safety check -- the
# same shape that produces black's real "error: cannot format ... Cannot
# parse for target version" exit-123 failure, without depending on a black
# release's exact unparseable-syntax repertoire.
_UNFORMATTABLE_PYTHON = "def f(:\n    pass\n"


def _run_gate(tmp_path: Path, *, paths: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    """Run the real wrapper with QA_FORMAT_* overrides; return (process, JSON).

    SECURITY: fixed argv, no shell, the repository's own QA wrapper.
    """
    output_dir = tmp_path / "qa"
    env = {
        **os.environ,
        "QA_FORMAT_OUTPUT_DIR": str(output_dir),
        "QA_FORMAT_PATHS": paths,
    }
    completed = subprocess.run(
        ["bash", str(_WRAPPER)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        timeout=_WRAPPER_TIMEOUT_SECONDS,
        check=False,
    )
    output = json.loads((output_dir / "format.json").read_text(encoding="utf-8"))
    return completed, output


class TestFormatGateAgreesWithExitCode:
    def test_an_unparseable_file_fails_the_json_too(self, tmp_path: Path) -> None:
        """Exit 123 (cannot format) must not coexist with summary.passed: true."""
        target = tmp_path / "broken.py"
        target.write_text(_UNFORMATTABLE_PYTHON, encoding="utf-8")

        completed, output = _run_gate(tmp_path, paths=str(target))

        assert completed.returncode == 123, completed.stdout + completed.stderr
        assert output["summary"]["passed"] is False, (
            "black exited 123 (cannot format) but format.json still reported "
            f"passed: true -- summary was {output['summary']!r}"
        )
        assert output["violations"], "count without detail is the defect this fix removes"
        assert target.name in output["violations"][0]["file"] or target.name in str(
            output["summary"].get("error", "")
        )

    def test_a_clean_target_still_passes(self, tmp_path: Path) -> None:
        """No false alarm: a file black is happy with is a clean run."""
        target = tmp_path / "quick.py"
        target.write_text("x = 1\n", encoding="utf-8")

        completed, output = _run_gate(tmp_path, paths=str(target))

        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert output["summary"]["passed"] is True
        assert output["violations"] == []
