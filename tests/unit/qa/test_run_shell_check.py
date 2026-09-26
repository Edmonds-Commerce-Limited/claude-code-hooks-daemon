"""The shellcheck gate must fail on SC1091 whatever level shellcheck gives it
(00466 N21).

``run_shell_check.sh`` only failed the gate on ``error``/``warning`` severity
issues. shellcheck reports a sourced file it cannot open or follow as SC1091
at level ``info`` (``Not following: ... does not exist``), so that defect
passed silently: the sourced file was never checked, and nothing said so.

These tests drive the real wrapper end to end against a planted fixture, so
the proof is the gate's own exit code and JSON, not a re-implementation of
its parsing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_WRAPPER = _REPO_ROOT / "scripts" / "qa" / "run_shell_check.sh"
_WRAPPER_TIMEOUT_SECONDS = 60
_SCRATCH_ROOT = _REPO_ROOT / "untracked" / "scratch"


@pytest.fixture()
def scratch_path() -> Iterator[Path]:
    """A unique, cleaned-up directory INSIDE the repo, not under system /tmp.

    shellcheck's ``-x`` source-following resolves a sourced path's
    ``${SCRIPT_DIR}``-style prefix relative to the invoking process, and that
    resolution only succeeds when the target lives under the same tree the
    gate scans in production. A fixture rooted at pytest's default
    ``tmp_path`` (system ``/tmp``, outside the repo) makes shellcheck emit a
    spurious SC1091 on a perfectly ordinary ``source "${SCRIPT_DIR}/lib.sh"``
    line -- confirmed by reproducing the same fixture both places. Rooting
    fixtures here instead matches how the gate is actually invoked and avoids
    that artifact.
    """
    _SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(dir=_SCRATCH_ROOT))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _run_gate(scratch: Path, target_dir: Path) -> tuple[subprocess.CompletedProcess[str], dict]:
    """Run the wrapper against ``target_dir`` with an isolated output dir.

    SECURITY: fixed argv, no shell, the repository's own QA wrapper.
    """
    output_dir = scratch / "qa"
    env = {
        **os.environ,
        "QA_SHELL_CHECK_TARGETS": str(target_dir),
        "QA_SHELL_CHECK_OUTPUT_DIR": str(output_dir),
    }
    completed = subprocess.run(
        ["bash", str(_WRAPPER)],
        capture_output=True,
        text=True,
        env=env,
        timeout=_WRAPPER_TIMEOUT_SECONDS,
        check=False,
    )
    output = json.loads((output_dir / "shell_check.json").read_text(encoding="utf-8"))
    return completed, output


class TestShellCheckGateFailsClosedOnSC1091:
    def test_an_unresolvable_source_fails_the_gate(self, scratch_path: Path) -> None:
        target_dir = scratch_path / "scripts"
        target_dir.mkdir()
        script = target_dir / "probe.sh"
        script.write_text('#!/bin/bash\nsource "/no/such/file.sh"\necho hi\n', encoding="utf-8")

        completed, output = _run_gate(scratch_path, target_dir)

        assert completed.returncode != 0, completed.stdout + completed.stderr
        assert output["summary"]["passed"] is False
        sc1091 = [i for i in output["issues"] if i["rule"] == "SC1091"]
        assert sc1091, output["issues"]
        assert sc1091[0]["severity"] == "info"

    def test_a_clean_script_still_passes(self, scratch_path: Path) -> None:
        """No false alarm: a script with a resolvable source stays green."""
        target_dir = scratch_path / "scripts"
        target_dir.mkdir()
        sourced = target_dir / "lib.sh"
        sourced.write_text("#!/bin/bash\ntrue\n", encoding="utf-8")
        script = target_dir / "probe.sh"
        script.write_text(
            '#!/bin/bash\nSCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
            'source "${SCRIPT_DIR}/lib.sh"\necho hi\n',
            encoding="utf-8",
        )

        completed, output = _run_gate(scratch_path, target_dir)

        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert output["summary"]["passed"] is True
        assert not [i for i in output["issues"] if i["rule"] == "SC1091"]
