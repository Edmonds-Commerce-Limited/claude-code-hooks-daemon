r"""Plan 00109 Phase 2 — failing acceptance gate for the thin-shim skill upgrade.sh.

The skill-published ``upgrade.sh`` MUST become a thin shim: detect project
root, fetch the canonical ``scripts/upgrade.sh`` from the configured ref on
GitHub, and ``exec bash`` against it. The shim carries ZERO upgrade logic.

This test is RED until Plan 00109 Phase 2.2 replaces the skill script body
with the new shim implementation.

Contract (Plan 00109 Decision 1):

  - Default URL: ``https://raw.githubusercontent.com/<repo>/<ref>/scripts/upgrade.sh``
  - ``HOOKS_DAEMON_UPGRADE_REF`` env (default ``main``) selects the ref.
  - ``HOOKS_DAEMON_UPGRADE_BASE_URL`` env overrides the base URL (used here
    and in any future testing context). When BASE_URL is set, the shim joins
    ``${BASE_URL}/${REF}/scripts/upgrade.sh`` verbatim — no host hardcoding.
  - Curl failure aborts loudly with a non-zero exit code (no silent fallback).
  - On success, shim ``exec``s ``bash <tmp> --project-root "$PROJECT_ROOT" "$@"``.

Test strategy: serve a tiny stand-in ``scripts/upgrade.sh`` from a local
``file://`` directory tree, point the shim at it via the base-URL override,
and assert the stand-in's sentinel-marker output appears on stdout. That
proves the shim fetched the override target and exec'd it (instead of, say,
running its own logic or hitting the real GitHub URL).
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_UPGRADE_SH = (
    REPO_ROOT
    / "src"
    / "claude_code_hooks_daemon"
    / "skills"
    / "hooks-daemon"
    / "scripts"
    / "upgrade.sh"
)
BASH = shutil.which("bash") or "/bin/bash"

_FIXTURE_MARKER = "SHIM_FIXTURE_EXEC_OK"
_SHIM_TIMEOUT_SECONDS = 60
_MAX_SHIM_LINES = 30  # PLAN.md Success Criteria: shim is < 30 lines.


@pytest.mark.slow
def test_skill_upgrade_sh_is_a_thin_shim(tmp_path: Path) -> None:
    """Skill upgrade.sh must curl the canonical script and exec it.

    Serves a stand-in ``scripts/upgrade.sh`` from a local file:// tree, runs
    the shim with ``HOOKS_DAEMON_UPGRADE_BASE_URL`` pointed at that tree, and
    asserts the stand-in's marker output appears — proving the shim fetched
    the override target and exec'd it.
    """
    if not SKILL_UPGRADE_SH.is_file():
        pytest.skip(f"Skill upgrade.sh missing at {SKILL_UPGRADE_SH}")

    # Assertion (a): the shim file is small (< 30 lines, per success criteria).
    # This is the hard guarantee that "zero logic in the skill" is enforced
    # mechanically rather than by reviewer goodwill.
    shim_lines = SKILL_UPGRADE_SH.read_text().splitlines()
    shim_line_count = sum(1 for ln in shim_lines if ln.strip() and not ln.lstrip().startswith("#"))
    assert shim_line_count <= _MAX_SHIM_LINES, (
        f"Skill upgrade.sh must be a thin shim (<= {_MAX_SHIM_LINES} non-blank, "
        f"non-comment lines). Currently has {shim_line_count} lines of logic. "
        f"Plan 00109 Phase 2.2 replaces the body with a thin shim — this "
        f"assertion stays RED until then."
    )

    # Fixture project: minimal layout the shim needs to walk for PROJECT_ROOT.
    project_root = tmp_path / "fixture-project"
    project_root.mkdir()
    (project_root / ".claude").mkdir()
    (project_root / ".claude" / "hooks-daemon.yaml").write_text("daemon: {}\n")

    # Fixture canonical script: served from file://<base>/<ref>/scripts/upgrade.sh.
    # Stand-in script just emits the sentinel marker and exits 0 so we can
    # confirm exec routing without running the real upgrade flow.
    base_dir = tmp_path / "fixture-base"
    ref_dir = base_dir / "main"
    scripts_dir = ref_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    fixture_upgrade_sh = scripts_dir / "upgrade.sh"
    fixture_upgrade_sh.write_text(textwrap.dedent(f"""\
            #!/bin/bash
            # Stand-in canonical upgrade.sh — proves the shim fetched and exec'd us.
            echo "{_FIXTURE_MARKER} project_root=$2 argv_tail=$*"
            exit 0
            """))
    fixture_upgrade_sh.chmod(fixture_upgrade_sh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)

    env = os.environ.copy()
    env["HOOKS_DAEMON_UPGRADE_BASE_URL"] = f"file://{base_dir}"
    env["HOOKS_DAEMON_UPGRADE_REF"] = "main"
    # Self-bootstrap is gone from the shim by design (Plan 00109 Phase 2 — the
    # whole point is no bootstrap stanza in the skill). If a transitional
    # build still has the old stanza, opt out so it doesn't reach the real
    # GitHub releases URL during the test.
    env["HOOKS_DAEMON_SKIP_BOOTSTRAP"] = "1"

    result = subprocess.run(
        [BASH, str(SKILL_UPGRADE_SH)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=_SHIM_TIMEOUT_SECONDS,
        cwd=project_root,
    )

    # Assertion (b): shim exited 0.
    assert result.returncode == 0, (
        f"Skill upgrade.sh shim must exit 0 when the fixture canonical script exits 0.\n"
        f"returncode={result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )

    # Assertion (c): fixture marker appears on stdout — proves the shim
    # fetched the BASE_URL override and exec'd the stand-in script.
    assert _FIXTURE_MARKER in result.stdout, (
        f"Skill upgrade.sh shim must fetch + exec the canonical script from "
        f"HOOKS_DAEMON_UPGRADE_BASE_URL. Fixture marker '{_FIXTURE_MARKER}' "
        f"missing — the shim ran its own logic instead of the override.\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )

    # Assertion (d): shim passed --project-root to the exec'd script. The
    # canonical Layer 1 script requires --project-root explicitly, so the
    # shim's one job (besides curl+exec) is to detect and forward it.
    assert f"project_root={project_root}" in result.stdout, (
        f"Shim must invoke canonical script with --project-root <detected root>.\n"
        f"Expected: 'project_root={project_root}' in stdout.\n"
        f"--- stdout ---\n{result.stdout}"
    )


@pytest.mark.slow
def test_skill_upgrade_sh_aborts_on_fetch_failure(tmp_path: Path) -> None:
    """Shim must abort loudly on curl failure (no silent fallback).

    Points the shim at a non-existent file:// path so curl gets a 404-equivalent
    (file not found). The shim must surface that as a non-zero exit, NOT fall
    back to any local upgrade.sh on disk.
    """
    if not SKILL_UPGRADE_SH.is_file():
        pytest.skip(f"Skill upgrade.sh missing at {SKILL_UPGRADE_SH}")

    project_root = tmp_path / "fixture-project"
    project_root.mkdir()
    (project_root / ".claude").mkdir()
    (project_root / ".claude" / "hooks-daemon.yaml").write_text("daemon: {}\n")

    missing_base = tmp_path / "does-not-exist"  # never created

    env = os.environ.copy()
    env["HOOKS_DAEMON_UPGRADE_BASE_URL"] = f"file://{missing_base}"
    env["HOOKS_DAEMON_UPGRADE_REF"] = "main"
    env["HOOKS_DAEMON_SKIP_BOOTSTRAP"] = "1"

    result = subprocess.run(
        [BASH, str(SKILL_UPGRADE_SH)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=_SHIM_TIMEOUT_SECONDS,
        cwd=project_root,
    )

    assert result.returncode != 0, (
        f"Shim must exit non-zero when curl cannot fetch the canonical script.\n"
        f"returncode={result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
