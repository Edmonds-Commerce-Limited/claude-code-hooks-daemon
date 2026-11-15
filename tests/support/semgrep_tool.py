"""The pinned semgrep command, built the way ``run_semgrep_check.sh`` builds it.

semgrep is not in the project venv (Plan 00607); the QA gate runs it from uv's
isolated tool environment at the one version in ``scripts/qa/semgrep-version.txt``.
Rule-pinning tests use this helper so they run the same binary the gate does.
"""

import shutil
from pathlib import Path
from typing import Final

_VERSION_FILE: Final[Path] = (
    Path(__file__).resolve().parents[2] / "scripts" / "qa" / "semgrep-version.txt"
)


def semgrep_argv() -> list[str]:
    """Return the argv prefix that runs the pinned semgrep; append semgrep arguments.

    Raises:
        RuntimeError: If the version pin is empty or uv is not on PATH.
    """
    version = _VERSION_FILE.read_text(encoding="utf-8").strip()
    if not version:
        raise RuntimeError(f"no semgrep version pinned in {_VERSION_FILE}")
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv not found, so the pinned semgrep cannot be obtained")
    return [uv, "tool", "run", "--quiet", "--from", f"semgrep=={version}", "semgrep"]
