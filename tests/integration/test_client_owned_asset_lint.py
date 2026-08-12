"""Guard: daemon-owned assets in CLIENT-owned paths stay clean under DEFAULT rules.

DBF (``CLAUDE.md`` Core Standard 15). Plan 00217's field report is a defect
whose *symptom* was three ruff findings in `.claude/ccy/claude-supervise.py`.
The bug worth fixing is that **nothing was looking**: the daemon deploys four
kinds of lintable artifact — around 39 files in a typical install — outside its
own git-ignored vendor directory, straight into directories a client owns,
commits and runs quality gates over, and no check anywhere asserted that any of
them was clean under the tooling a client would actually point at them.

That blindness is invisible by construction. This repository's own ruff config
selects `E,W,F,I,B,C4,UP,ARG,SIM,TCH,PTH,RUF`, and its shellcheck run uses a
`.shellcheckrc`. Both are perfectly reasonable *for us*, and both are the wrong
question for a deployed asset: what matters is what the asset looks like to
someone who did not choose our configuration. So this guard deliberately throws
our configuration away — `ruff --isolated`, `shellcheck --norc` — and asks only
whether the shipped artifact is clean under the tool's own defaults.

The contract this pins down, stated the same way in ``CLAUDE/LLM-INSTALL.md``:

* Upstream GUARANTEES every deployed asset is clean under its language's
  default rule set. A finding here is an upstream bug, and this test is how it
  gets caught before a client sees it.
* Upstream CANNOT guarantee cleanliness under rules a client *chooses* — the
  reported `BLE001`/`DTZ005`/`DTZ006` require `BLE` and `DTZ` to be selected,
  which is neither ruff's default nor predictable from here. That case is
  served by the documented exclusion, not by this test.

Deliberately NOT asserted: formatting (`black --check`). Line length and quote
style are project preferences, not findings a client can mistake for a defect.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 - runs trusted linters with fixed argument lists
import sys
from pathlib import Path
from typing import Final

import pytest

from claude_code_hooks_daemon.install.client_owned_assets import (
    CLIENT_BOUNDARY_DOC,
    AssetLanguage,
    ClientOwnedAsset,
    resolve_sources,
)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

_RUFF_MODULE: Final[str] = "ruff"
_SHELLCHECK_BINARY: Final[str] = "shellcheck"
_LINT_TIMEOUT_SECONDS: Final[int] = 120
_CLEAN_EXIT_CODE: Final[int] = 0

# `--isolated` makes ruff ignore every pyproject.toml / ruff.toml on disk,
# including ours, so it applies its own default select (E4, E7, E9, F).
_RUFF_DEFAULT_ARGS: Final[tuple[str, ...]] = ("check", "--isolated", "--output-format", "concise")

# `--norc` discards this repo's .shellcheckrc for the same reason.
#
# `-x --source-path=SCRIPTDIR` is source RESOLUTION, not rule suppression, and
# the distinction matters. Our scripts source siblings through a computed path
# (`source "$(dirname "$0")/_resolve-venv.sh"`). Shellcheck cannot evaluate
# `$0`, so without these flags it does not follow the source and then reports
# the consequences of not having looked: SC1091 "not following", plus a
# spurious SC2034 "DAEMON_DIR appears unused" for a variable the sourced file
# uses. Both vanish once shellcheck can see the sourced file — they describe
# the invocation, not the script. Its own SC1091 message recommends `-x`, and
# `CLAUDE/LLM-INSTALL.md` gives clients the same one-line setting.
_SHELLCHECK_DEFAULT_ARGS: Final[tuple[str, ...]] = ("--norc", "-x", "--source-path=SCRIPTDIR")


def _assets_for(language: AssetLanguage) -> list[tuple[ClientOwnedAsset, Path]]:
    """Manifest entries of one language, resolved to concrete repository files."""
    return [
        (asset, path) for asset, path in resolve_sources(_REPO_ROOT) if asset.language is language
    ]


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a linter from the repository root and return its completed process."""
    # SECURITY: fixed argv built from a repo-internal manifest; no shell, no user input.
    return subprocess.run(  # nosec B603 - fixed trusted argv, no shell
        argv,
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=_LINT_TIMEOUT_SECONDS,
        check=False,
    )


def _remediation(paths: list[Path], output: str) -> str:
    """Explain what a failure here means, since the fix is counter-intuitive."""
    names = ", ".join(str(path.relative_to(_REPO_ROOT)) for path in paths)
    return (
        f"Daemon-owned asset(s) deployed into client-owned paths are not clean "
        f"under their language's DEFAULT rule set:\n\n{output}\n\n"
        f"Files: {names}\n\n"
        f"These ship into directories the client owns, commits and lints. A "
        f"client cannot fix a finding here (the next upgrade overwrites the "
        f"file) and cannot suppress it (the daemon's own qa_suppression handler "
        f"denies writing a directive), so it reaches them as permanent noise "
        f"they must independently diagnose.\n\n"
        f"Fix the code. Do NOT add a suppression directive: this repo selects "
        f"RUF but not BLE/DTZ, so a directive for a non-enabled rule is itself "
        f"a RUF100 violation of our own gate (Plan 00217, EVIDENCE.md E2). If "
        f"the finding is genuinely correct-as-written, it belongs in the "
        f"exclusion documented in {CLIENT_BOUNDARY_DOC}, not in the source."
    )


class TestPythonAssetsAreCleanUnderRuffDefaults:
    """`ruff check --isolated` — no project config, ruff's own default select."""

    def test_manifest_has_python_assets(self) -> None:
        """Control: an empty set would make the check below pass vacuously."""
        assert _assets_for(AssetLanguage.PYTHON), (
            "No PYTHON assets resolved from the manifest. The ccy supervisor is "
            "one; if it stopped resolving, this guard is checking nothing."
        )

    def test_python_assets_are_clean(self) -> None:
        """Every deployed Python asset passes ruff's defaults."""
        paths = [path for _asset, path in _assets_for(AssetLanguage.PYTHON)]
        argv = [sys.executable, "-m", _RUFF_MODULE, *_RUFF_DEFAULT_ARGS, *map(str, paths)]
        result = _run(argv)
        assert result.returncode == _CLEAN_EXIT_CODE, _remediation(
            paths, result.stdout + result.stderr
        )


class TestShellAssetsAreCleanUnderShellcheckDefaults:
    """`shellcheck --norc -x` — no project rc, every severity level."""

    def test_shellcheck_is_available(self) -> None:
        """Fail rather than skip: a guard that opts out is the blindness again.

        ``scripts/qa/run_shell_check.sh`` already treats a missing shellcheck as
        a hard failure, so this matches the gate it complements.
        """
        assert shutil.which(_SHELLCHECK_BINARY), (
            f"{_SHELLCHECK_BINARY} is not installed, so the shell half of this "
            f"guard cannot run. Install it (apt-get install shellcheck) — "
            f"skipping would leave the deployed forwarders and skill scripts "
            f"unexamined, which is the condition this test exists to end."
        )

    def test_manifest_has_shell_assets(self) -> None:
        """Control: guards the assertion below against an empty resolution."""
        assert _assets_for(AssetLanguage.SHELL), (
            "No SHELL assets resolved from the manifest, yet the daemon "
            "deploys init.sh, the hook forwarders and the skill scripts."
        )

    def test_shell_assets_are_clean(self) -> None:
        """Every deployed shell asset passes shellcheck with no rc."""
        if not shutil.which(_SHELLCHECK_BINARY):  # pragma: no cover - reported above
            pytest.fail(f"{_SHELLCHECK_BINARY} missing; see test_shellcheck_is_available")

        paths = [path for _asset, path in _assets_for(AssetLanguage.SHELL)]
        argv = [_SHELLCHECK_BINARY, *_SHELLCHECK_DEFAULT_ARGS, *map(str, paths)]
        result = _run(argv)
        assert result.returncode == _CLEAN_EXIT_CODE, _remediation(
            paths, result.stdout + result.stderr
        )
