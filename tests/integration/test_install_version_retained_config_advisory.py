"""install_version.sh Step 7 surfaces the migration advisory for a retained config
(Plan 00362 Task 2.2, D12; Plan 00291 Task 2.2).

A client in the fresh-clone state re-runs the INSTALLER with a config that
already exists — often one written for a version many releases behind the
daemon being installed. Step 7 kept that config and said only "keeping
existing configuration". The config-migration advisory
(``check-config-migrations``) already exists and works; it was simply never
run on this path, so nothing told the operator that the retained config
predates the installed version's migrations.

The installer has no record of which version the retained config was written
for (a fresh clone carries no venv stamp), so the advisory is run from the
EARLIEST known manifest: a renamed key still present, or a recommended
default the config does not hold, is reported regardless of when it was
introduced. The advisory is informational and never aborts the install.

These tests run the REAL Step 7 block, extracted from the script between its
step banners, with the test venv's interpreter standing in for the freshly
built one.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = REPO_ROOT / "scripts" / "install_version.sh"
INSTALL_LIB = REPO_ROOT / "scripts" / "install"

_STEP7_PATTERN = re.compile(
    r"# Step 7: Deploy config\n# =+\n(?P<body>.*?)\n# =+\n# Step 7b:",
    re.DOTALL,
)

_HARNESS = """
set -euo pipefail
source "$INSTALL_LIB/output.sh"
log_step() { echo "STEP $1: $2"; }
source "$STEP7_FILE"
echo "STEP7_COMPLETED"
"""

# A config shaped like one written long before the current release: the
# schema header is present but none of the keys later manifests added, and a
# default that a manifest flipped (status_line.daemon_stats) is still on.
_OLD_CONFIG = """\
version: "2.0"
daemon:
  log_level: INFO
handlers:
  status_line:
    daemon_stats:
      enabled: true
"""


def _step7_body() -> str:
    match = _STEP7_PATTERN.search(INSTALL_SH.read_text())
    assert match is not None, "scripts/install_version.sh no longer has a Step 7 banner pair"
    return match.group("body")


def _run_step7(tmp_path: Path, *, existing_config: str | None) -> subprocess.CompletedProcess[str]:
    project_root = tmp_path / "client"
    (project_root / ".claude").mkdir(parents=True)
    if existing_config is not None:
        (project_root / ".claude" / "hooks-daemon.yaml").write_text(existing_config)
    step7_file = tmp_path / "step7.sh"
    step7_file.write_text(_step7_body() + "\n")
    env = os.environ.copy()
    env.update(
        INSTALL_LIB=str(INSTALL_LIB),
        STEP7_FILE=str(step7_file),
        PROJECT_ROOT=str(project_root),
        DAEMON_DIR=str(REPO_ROOT),
        EXAMPLE_CONFIG=str(REPO_ROOT / ".claude" / "hooks-daemon.yaml.example"),
        VENV_PYTHON=sys.executable,
        INSTALLED_VERSION="v" + _current_version(),
        NO_COLOR="1",
    )
    return subprocess.run(
        ["bash", "-c", _HARNESS],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _current_version() -> str:
    from claude_code_hooks_daemon.version import __version__

    return __version__


def test_retained_old_config_surfaces_the_migration_advisory(tmp_path: Path) -> None:
    result = _run_step7(tmp_path, existing_config=_OLD_CONFIG)
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "STEP7_COMPLETED" in result.stdout
    assert "keeping existing configuration" in combined
    # The advisory itself, not just a pointer: the flipped default is named.
    assert "daemon_stats" in combined, combined
    # And the operator is told how to re-run it after the install.
    assert "check-config-migrations" in combined, combined


def test_retained_config_advisory_names_the_baseline_it_checked_from(tmp_path: Path) -> None:
    """The install cannot know the config's true origin version, so it says
    which baseline it assumed rather than presenting a guess as fact."""
    result = _run_step7(tmp_path, existing_config=_OLD_CONFIG)
    combined = result.stdout + result.stderr
    assert re.search(
        r"earliest|every manifest|since v?\d+\.\d+\.\d+", combined, re.IGNORECASE
    ), combined


def test_retained_config_is_never_rewritten_by_the_advisory(tmp_path: Path) -> None:
    result = _run_step7(tmp_path, existing_config=_OLD_CONFIG)
    assert result.returncode == 0, result.stderr
    retained = tmp_path / "client" / ".claude" / "hooks-daemon.yaml"
    assert retained.read_text() == _OLD_CONFIG


def test_fresh_install_deploys_default_config_without_an_advisory(tmp_path: Path) -> None:
    result = _run_step7(tmp_path, existing_config=None)
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "Deployed default config" in combined
    assert "check-config-migrations" not in combined
    assert (tmp_path / "client" / ".claude" / "hooks-daemon.yaml").is_file()


def test_unparseable_retained_config_does_not_abort_the_install(tmp_path: Path) -> None:
    """The advisory is informational; a config the advisory cannot read is a
    warning here and a validation failure later, never a rollback."""
    result = _run_step7(tmp_path, existing_config="handlers: [\n")
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "STEP7_COMPLETED" in result.stdout
