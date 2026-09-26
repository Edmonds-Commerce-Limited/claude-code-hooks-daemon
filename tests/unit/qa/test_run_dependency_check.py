"""The dependency gate must fail when deptry -- or uv -- could not check something (00466 N21).

``run_dependency_check.sh`` discarded deptry's own exit code and read only its
JSON output file; a missing raw file (deptry writes JSON only after a full,
successful run) became ``issues_raw = []`` via the st_size guard and reported
``passed: true`` over a dependency check that never ran. Separately, when
``uv`` was not on PATH the ``uv lock --check`` freshness gate was SKIPPED
with a warning and the run still passed -- silently dropping the lockfile
gate rather than failing it.

These tests drive the real wrapper end to end (a fake deptry binary for the
exit-code/missing-output cases, ``QA_DEPENDENCY_FORCE_NO_UV`` for the uv
case, real deptry for the clean-run sanity check), so the proof is the
gate's own exit code, not a re-implementation of it.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_WRAPPER = _REPO_ROOT / "scripts" / "qa" / "run_dependency_check.sh"
_WRAPPER_TIMEOUT_SECONDS = 300

_FAKE_DEPTRY_CLI_ERROR = """#!/bin/sh
# Simulates a deptry CLI usage error: exits 2, writes no JSON output at all.
echo "Error: Invalid value for 'ROOT...': path does not exist." >&2
exit 2
"""

_FAKE_DEPTRY_NO_OUTPUT = """#!/bin/sh
# Exits 0 (as if clean) but never writes the --json-output file at all.
exit 0
"""


def _run_gate(
    tmp_path: Path,
    *,
    targets: str,
    deptry_bin: str = "",
    force_no_uv: bool = False,
) -> tuple[subprocess.CompletedProcess[str], dict]:
    """Run the real wrapper with QA_DEPENDENCY_* overrides; return (process, JSON).

    SECURITY: fixed argv, no shell, the repository's own QA wrapper.
    """
    output_dir = tmp_path / "qa"
    env = {
        **os.environ,
        "QA_DEPENDENCY_OUTPUT_DIR": str(output_dir),
        "QA_DEPENDENCY_TARGETS": targets,
    }
    if deptry_bin:
        env["QA_DEPENDENCY_DEPTRY_BIN"] = deptry_bin
    if force_no_uv:
        env["QA_DEPENDENCY_FORCE_NO_UV"] = "1"
    completed = subprocess.run(
        ["bash", str(_WRAPPER)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        timeout=_WRAPPER_TIMEOUT_SECONDS,
        check=False,
    )
    output_path = output_dir / "dependencies.json"
    output = json.loads(output_path.read_text(encoding="utf-8")) if output_path.exists() else {}
    return completed, output


def _write_fake_deptry(tmp_path: Path, script: str) -> str:
    fake = tmp_path / "fake-deptry"
    fake.write_text(script, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return str(fake)


class TestDependencyGateFailsClosed:
    def test_uv_missing_fails_the_gate_instead_of_skipping(self, tmp_path: Path) -> None:
        """A missing uv used to warn and continue; it must now fail the run."""
        completed, _ = _run_gate(tmp_path, targets="src/", force_no_uv=True)

        assert completed.returncode != 0, completed.stdout + completed.stderr
        combined = completed.stdout + completed.stderr
        assert "uv" in combined.lower()

    def test_a_deptry_cli_error_fails_the_gate_naming_the_exit_code(self, tmp_path: Path) -> None:
        """Exit 2, no JSON output at all -- must not be read as zero issues."""
        target = tmp_path / "pkg"
        target.mkdir()
        (target / "mod.py").write_text("x = 1\n", encoding="utf-8")
        fake_bin = _write_fake_deptry(tmp_path, _FAKE_DEPTRY_CLI_ERROR)

        completed, output = _run_gate(tmp_path, targets=str(target), deptry_bin=fake_bin)

        assert completed.returncode != 0, completed.stdout + completed.stderr
        assert output["summary"]["passed"] is False
        assert "2" in output["summary"]["error"]
        assert output["issues"], "count without detail is the defect this fix removes"

    def test_a_missing_json_output_fails_the_gate(self, tmp_path: Path) -> None:
        """deptry exits 0 but never wrote --json-output -- nothing was checked."""
        target = tmp_path / "pkg"
        target.mkdir()
        (target / "mod.py").write_text("x = 1\n", encoding="utf-8")
        fake_bin = _write_fake_deptry(tmp_path, _FAKE_DEPTRY_NO_OUTPUT)

        completed, output = _run_gate(tmp_path, targets=str(target), deptry_bin=fake_bin)

        assert completed.returncode != 0, completed.stdout + completed.stderr
        assert output["summary"]["passed"] is False
        assert output["issues"], "count without detail is the defect this fix removes"

    def test_the_real_project_scope_still_passes(self, tmp_path: Path) -> None:
        """No false alarm: the real gate, on the real tree, is still green."""
        completed, output = _run_gate(tmp_path, targets="src/")

        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert output["summary"]["passed"] is True
        assert "error" not in output["summary"]
