r"""Deploying settings.json must never lose a client's copy in silence.

`upgrade_version.sh` overwrote the client's `settings.json` from two places that
behaved differently, and the one that runs MOST often was the less safe of the
two (Plan 00176 Task 2.0):

- **Step 9** copies after Step 3 has taken a full state snapshot containing
  `settings.json`, and prints `Redeployed settings.json`.
- **The idempotent fast path** copies and prints *nothing at all* — and it
  `exit 0`s before Step 3, so there is no snapshot behind it either. The
  script's own comment calls this branch "the effective single deployment path
  for every client upgrade".

Two sites doing the same job differently is what produced the gap, so this is
one function used by both. It takes a timestamped backup whenever no snapshot
covers the copy, and says what it replaced either way.

Task 2.3 then replaced the copy itself with a MERGE, so the daemon's wired-hook
block is refreshed without taking the client's `permissions`, `statusLine` and
everything else down with it. The two properties that matter here are that a
client key survives a real deploy, and that a deploy which CANNOT merge refuses
rather than falling back to the overwrite this function exists to prevent.
"""

from __future__ import annotations

import json
import os
import subprocess  # nosec B404 - runs bash on this repo's own shell library
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.install.settings_merge import ESCALATION_EXIT_CODE
from claude_code_hooks_daemon.utils.hook_registration import (
    HOOK_EVENTS_IN_SETTINGS,
    build_hook_registration,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB = REPO_ROOT / "scripts" / "install" / "settings_deploy.sh"

_DAEMON_JSON = '{"statusLine": {"command": "daemon"}}\n'
_CLIENT_JSON = '{"statusLine": {"command": "mine"}, "plansDirectory": "CLAUDE/Plan"}\n'


def _shipped_json() -> str:
    """A daemon settings.json the merge can actually validate against."""
    settings: dict[str, Any] = {
        "hooks": {
            json_key: build_hook_registration(bash_key)
            for json_key, bash_key in HOOK_EVENTS_IN_SETTINGS.items()
        },
        "permissions": {"deny": ["Edit(//tmp/**)"]},
    }
    return json.dumps(settings, indent=2) + "\n"


def _invoke(
    tmp_path: Path,
    *,
    client: str | None,
    daemon: str = _DAEMON_JSON,
    snapshot: str = "",
    venv_python: str = "",
    stub: str = "",
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Call `deploy_settings_json` for real and return the process and target."""
    source = tmp_path / "daemon-settings.json"
    source.write_text(daemon, encoding="utf-8")
    target = tmp_path / "client" / ".claude" / "settings.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if client is not None:
        target.write_text(client, encoding="utf-8")

    script = textwrap.dedent(f"""
        set -u
        print_success() {{ echo "SUCCESS: $*"; }}
        print_warning() {{ echo "WARNING: $*"; }}
        print_error()   {{ echo "ERROR: $*"; }}
        print_info()    {{ echo "INFO: $*"; }}
        print_verbose() {{ echo "VERBOSE: $*"; }}
        OUTPUT_SH_LOADED=1
        source "{LIB}"
        {stub}
        deploy_settings_json "{source}" "{target}" "{snapshot}" "{venv_python}" ""
    """)
    result = subprocess.run(  # nosec B603 B607 - bash, list form, no shell
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=Timeout.VALIDATION_CHECK,
    )
    return result, target


def _run(tmp_path: Path, **kwargs: Any) -> tuple[str, Path]:
    """`_invoke`, asserting the deploy reported success."""
    result, target = _invoke(tmp_path, **kwargs)
    assert result.returncode == 0, f"exited {result.returncode}:\n{result.stdout}{result.stderr}"
    return result.stdout, target


def _backups(tmp_path: Path) -> list[Path]:
    return sorted((tmp_path / "client" / ".claude").glob("settings.json.bak-*"))


class TestItStillDeploys:
    def test_the_daemon_file_lands_when_there_was_nothing_there(self, tmp_path: Path) -> None:
        out, target = _run(tmp_path, client=None)
        assert target.read_text() == _DAEMON_JSON
        assert "SUCCESS" in out

    def test_a_missing_source_is_not_an_error(self, tmp_path: Path) -> None:
        """Older daemon versions ship no settings.json; that is not a failure."""
        script = textwrap.dedent(f"""
            set -u
            print_success() {{ :; }}
            print_warning() {{ :; }}
            print_verbose() {{ echo "VERBOSE: $*"; }}
            OUTPUT_SH_LOADED=1
            source "{LIB}"
            deploy_settings_json "{tmp_path}/absent.json" "{tmp_path}/t.json" "" "" ""
        """)
        result = subprocess.run(  # nosec B603 B607 - bash, list form, no shell
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=Timeout.VALIDATION_CHECK,
        )
        assert result.returncode == 0
        assert "VERBOSE" in result.stdout


class TestNothingIsSaidWhenNothingIsLost:
    def test_no_previous_file_warns_nothing(self, tmp_path: Path) -> None:
        out, _ = _run(tmp_path, client=None)
        assert "WARNING" not in out

    def test_an_identical_file_warns_nothing(self, tmp_path: Path) -> None:
        """Warning on every upgrade would train people to ignore it."""
        out, _ = _run(tmp_path, client=_DAEMON_JSON)
        assert "WARNING" not in out

    def test_an_identical_file_takes_no_backup(self, tmp_path: Path) -> None:
        """Backing up an identical file just accumulates litter."""
        _run(tmp_path, client=_DAEMON_JSON)
        assert _backups(tmp_path) == []

    def test_an_identical_file_needs_no_interpreter(self, tmp_path: Path) -> None:
        """The commonest case of all must not escalate for want of a merge."""
        result, _ = _invoke(tmp_path, client=_DAEMON_JSON, venv_python="")
        assert result.returncode == 0


class TestWhenASnapshotAlreadyCoversIt:
    def test_the_warning_points_at_the_snapshot(self, tmp_path: Path) -> None:
        result, _ = _invoke(tmp_path, client=_CLIENT_JSON, snapshot="/snaps/snap-1")
        assert "WARNING" in result.stdout
        assert "/snaps/snap-1" in result.stdout

    def test_no_second_copy_is_made(self, tmp_path: Path) -> None:
        """The snapshot IS the copy; a `.bak-` beside it is redundant litter."""
        _invoke(tmp_path, client=_CLIENT_JSON, snapshot="/snaps/snap-1")
        assert _backups(tmp_path) == []


class TestWhenNothingElseIsKeepingACopy:
    """The fast path — no snapshot, and previously no message either."""

    def test_a_timestamped_backup_is_taken(self, tmp_path: Path) -> None:
        _invoke(tmp_path, client=_CLIENT_JSON, snapshot="")
        backups = _backups(tmp_path)
        assert len(backups) == 1
        assert backups[0].read_text() == _CLIENT_JSON

    def test_the_warning_names_that_backup(self, tmp_path: Path) -> None:
        result, _ = _invoke(tmp_path, client=_CLIENT_JSON, snapshot="")
        assert "WARNING" in result.stdout
        assert _backups(tmp_path)[0].name in result.stdout

    @pytest.mark.skipif(
        os.geteuid() == 0, reason="running as root, which ignores the directory mode"
    )
    def test_a_failed_backup_stops_everything(self, tmp_path: Path) -> None:
        """Losing the file is the one outcome worth aborting a deploy for."""
        target = tmp_path / "client" / ".claude" / "settings.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_CLIENT_JSON, encoding="utf-8")
        source = tmp_path / "daemon-settings.json"
        source.write_text(_DAEMON_JSON, encoding="utf-8")
        target.parent.chmod(0o555)
        try:
            script = textwrap.dedent(f"""
                set -u
                print_success() {{ echo "SUCCESS: $*"; }}
                print_warning() {{ echo "WARNING: $*"; }}
                print_error()   {{ echo "ERROR: $*"; }}
                print_verbose() {{ :; }}
                OUTPUT_SH_LOADED=1
                source "{LIB}"
                deploy_settings_json "{source}" "{target}" "" "" ""
            """)
            result = subprocess.run(  # nosec B603 B607 - bash, list form, no shell
                ["bash", "-c", script],
                capture_output=True,
                text=True,
                check=False,
                timeout=Timeout.VALIDATION_CHECK,
            )
            assert result.returncode == 1
            assert target.read_text() == _CLIENT_JSON, "the client file must survive"
        finally:
            target.parent.chmod(0o755)


class TestTheInstallCopyCanFail:
    """The backup was checked; the copy it protects was not.

    A failed install copy — read-only target, full disk — printed "Installed
    settings.json" and returned 0, so the caller's `|| fail_fast` never fired and
    the run carried on over a settings.json that had not been written.

    `cp` is stubbed rather than the filesystem broken, because this container
    runs as root and root ignores the file mode this would otherwise rely on.
    """

    @staticmethod
    def _stub() -> str:
        return textwrap.dedent("""
            cp() {
                case "$1" in
                    *daemon-settings.json) return 1 ;;
                esac
                command cp "$@"
            }
        """)

    def test_it_reports_failure(self, tmp_path: Path) -> None:
        result, _ = _invoke(tmp_path, client=None, stub=self._stub())
        assert result.returncode == 1

    def test_it_does_not_claim_success(self, tmp_path: Path) -> None:
        """The caller's `|| fail_fast` is only as good as this return value."""
        result, _ = _invoke(tmp_path, client=None, stub=self._stub())
        assert "SUCCESS" not in result.stdout


class TestWithoutAnInterpreterItRefusesRatherThanOverwriting:
    """Falling back to the copy would be the exact data loss this prevents."""

    def test_the_client_file_is_left_alone(self, tmp_path: Path) -> None:
        _, target = _invoke(tmp_path, client=_CLIENT_JSON, venv_python="")
        assert target.read_text() == _CLIENT_JSON

    def test_it_reports_the_escalation_code_not_a_failure(self, tmp_path: Path) -> None:
        """1 means abort to the calling scripts; this must not abort them."""
        result, _ = _invoke(tmp_path, client=_CLIENT_JSON, venv_python="")
        assert result.returncode == ESCALATION_EXIT_CODE

    def test_it_says_the_registrations_may_be_stale(self, tmp_path: Path) -> None:
        result, _ = _invoke(tmp_path, client=_CLIENT_JSON, venv_python="")
        assert "stale" in result.stdout


class TestARealMergeThroughTheShell:
    """End to end: the shell function, the CLI, and the merge itself."""

    def test_a_client_key_survives_the_deploy(self, tmp_path: Path) -> None:
        client = json.dumps({"permissions": {"deny": ["Bash(rm:*)"]}, "hooks": {}})
        _, target = _invoke(
            tmp_path,
            client=client,
            daemon=_shipped_json(),
            venv_python=sys.executable,
        )
        assert json.loads(target.read_text())["permissions"] == {"deny": ["Bash(rm:*)"]}

    def test_the_wired_set_is_completed_by_the_deploy(self, tmp_path: Path) -> None:
        client = json.dumps({"permissions": {"deny": ["Bash(rm:*)"]}, "hooks": {}})
        result, target = _invoke(
            tmp_path,
            client=client,
            daemon=_shipped_json(),
            venv_python=sys.executable,
        )
        assert result.returncode == 0
        assert set(HOOK_EVENTS_IN_SETTINGS) <= set(json.loads(target.read_text())["hooks"])

    def test_an_unreadable_client_file_survives_and_escalates(self, tmp_path: Path) -> None:
        result, target = _invoke(
            tmp_path,
            client="{ not json",
            daemon=_shipped_json(),
            venv_python=sys.executable,
        )
        assert result.returncode == ESCALATION_EXIT_CODE
        assert target.read_text() == "{ not json"


class TestEveryCallSiteUsesIt:
    """A helper only helps if the sites that had the bug actually call it.

    There were **three**, not two. This originally pinned `upgrade_version.sh`
    alone, so `install_version.sh` Step 5 kept its own raw copy — with both its
    `cp` exit statuses unchecked, the same defect in a third place. Scoping the
    pin to the file being fixed is how the third site stayed invisible.
    """

    @pytest.mark.parametrize("marker", ["deploy_settings_json"])
    def test_upgrade_version_sh_calls_it_twice(self, marker: str) -> None:
        source = (REPO_ROOT / "scripts" / "upgrade_version.sh").read_text(encoding="utf-8")
        assert source.count(marker) >= 2, (
            "both the idempotent fast path and Step 9 must go through the "
            "helper — two sites copying settings.json differently is the "
            "defect this replaces"
        )

    def test_install_version_sh_calls_it_too(self) -> None:
        source = (REPO_ROOT / "scripts" / "install_version.sh").read_text(encoding="utf-8")
        assert "deploy_settings_json" in source

    @pytest.mark.parametrize("script", ["upgrade_version.sh", "install_version.sh"])
    def test_no_raw_copy_of_the_settings_source_remains(self, script: str) -> None:
        source = (REPO_ROOT / "scripts" / script).read_text(encoding="utf-8")
        assert 'cp "$SETTINGS_JSON_SOURCE"' not in source

    @pytest.mark.parametrize("script", ["upgrade_version.sh", "install_version.sh"])
    def test_no_site_lets_an_escalation_reach_fail_fast(self, script: str) -> None:
        """`|| fail_fast` on a bare deploy would abort on a refusal to merge."""
        source = (REPO_ROOT / "scripts" / script).read_text(encoding="utf-8")
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("deploy_settings_json "):
                raise AssertionError(
                    f"{script} calls deploy_settings_json directly: {stripped}. "
                    "Use deploy_settings_json_checked, which turns an escalation "
                    "into a warning instead of an abort."
                )


class TestTheEscalationCodeMatchesThePythonSide:
    def test_the_shell_and_the_cli_agree(self) -> None:
        """Two spellings of one number is how they drift apart."""
        source = LIB.read_text(encoding="utf-8")
        assert f"SETTINGS_MERGE_ESCALATED={ESCALATION_EXIT_CODE}" in source
