"""Plan 00477 Task 1.2 - one bash resolver for the version a project expects.

``_resolve_expected_version`` in ``init.sh`` runs before any venv exists, so it
is bash with no python. It reads ``daemon.expected_version`` from
``.claude/hooks-daemon.yaml`` and falls back to the ``.claude/HOOKS-DAEMON.md``
header (``_tracked_deployed_version``) for projects that predate the key. It
says ``unknown`` rather than guessing, and a key that is present but invalid
is reported as invalid, not papered over with the header.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.install.expected_version import record_expected_version

REPO_ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash") or "/bin/bash"

HEADER = "> Generated on 2026-09-01 (v3.50.0) by the hooks daemon\n"


def _project(tmp_path: Path, config: str | None, header: str | None = None) -> Path:
    claude = tmp_path / "project" / ".claude"
    claude.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "init.sh", claude / "init.sh")
    if config is not None:
        (claude / "hooks-daemon.yaml").write_text(config)
    if header is not None:
        (claude / "HOOKS-DAEMON.md").write_text(f"# Hooks Daemon\n\n{header}")
    return tmp_path / "project"


def _resolve(project: Path) -> tuple[int, str, str]:
    """Return (rc, version, source) as the resolver reports them."""
    script = (
        f'source "{project}/.claude/init.sh"\n'
        "rc=0\n"
        "_resolve_expected_version || rc=$?\n"
        'printf "%s|%s|%s" "$rc" "$_HOOKS_DAEMON_EXPECTED_VERSION" '
        '"$_HOOKS_DAEMON_EXPECTED_VERSION_SOURCE"\n'
    )
    result = subprocess.run(  # nosec B603 - fixed argv, no shell
        [BASH, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=Timeout.REQUEST_DEFAULT,
        env={"PATH": "/usr/bin:/bin", "HOME": str(project.parent)},
    )
    assert result.returncode == 0, result.stderr
    rc, version, source = result.stdout.rsplit("|", 2)
    return int(rc.strip().splitlines()[-1]), version, source


class TestResolveExpectedVersion:
    def test_reads_the_config_key(self, tmp_path: Path) -> None:
        project = _project(tmp_path, 'daemon:\n  expected_version: "3.68.0"\n', HEADER)

        assert _resolve(project) == (0, "3.68.0", "config")

    def test_the_config_key_outranks_the_header(self, tmp_path: Path) -> None:
        project = _project(tmp_path, "daemon:\n  expected_version: 3.68.0  # c\n", HEADER)

        assert _resolve(project) == (0, "3.68.0", "config")

    def test_reads_what_the_installer_writes(self, tmp_path: Path) -> None:
        project = _project(
            tmp_path, 'version: "2.0"\ndaemon:\n  log_level: INFO\nhandlers: {}\n', None
        )
        record_expected_version(project / ".claude" / "hooks-daemon.yaml", "3.69.1")

        assert _resolve(project) == (0, "3.69.1", "config")

    def test_single_quoted_value(self, tmp_path: Path) -> None:
        project = _project(tmp_path, "daemon:\n  expected_version: '3.68.0'\n")

        assert _resolve(project) == (0, "3.68.0", "config")

    def test_falls_back_to_the_header_for_a_project_that_predates_the_key(
        self, tmp_path: Path
    ) -> None:
        project = _project(tmp_path, "daemon:\n  log_level: INFO\n", HEADER)

        assert _resolve(project) == (0, "3.50.0", "tracked-doc")

    def test_falls_back_to_the_header_when_there_is_no_config_file(self, tmp_path: Path) -> None:
        project = _project(tmp_path, None, HEADER)

        assert _resolve(project) == (0, "3.50.0", "tracked-doc")

    def test_reports_unknown_when_neither_source_names_a_version(self, tmp_path: Path) -> None:
        project = _project(tmp_path, "daemon:\n  log_level: INFO\n", None)

        assert _resolve(project) == (1, "unknown", "")

    def test_a_key_outside_the_daemon_block_is_not_the_key(self, tmp_path: Path) -> None:
        project = _project(
            tmp_path,
            'daemon:\n  log_level: INFO\nhandlers:\n  expected_version: "9.9.9"\n',
        )

        assert _resolve(project) == (1, "unknown", "")

    def test_a_nested_key_of_the_same_name_is_not_the_key(self, tmp_path: Path) -> None:
        project = _project(
            tmp_path,
            'daemon:\n  other:\n    expected_version: "9.9.9"\n  log_level: INFO\n',
            HEADER,
        )

        assert _resolve(project) == (0, "3.50.0", "tracked-doc")

    def test_reads_a_four_space_daemon_block(self, tmp_path: Path) -> None:
        project = _project(
            tmp_path, 'daemon:\n    log_level: INFO\n    expected_version: "3.68.0"\n'
        )

        assert _resolve(project) == (0, "3.68.0", "config")

    def test_a_commented_out_key_is_not_the_key(self, tmp_path: Path) -> None:
        project = _project(tmp_path, 'daemon:\n  # expected_version: "9.9.9"\n', None)

        assert _resolve(project) == (1, "unknown", "")

    @pytest.mark.parametrize("bad", ["main", "3.68", "v3.68.0", "3.68.0-rc1", "$(id)", "''"])
    def test_an_invalid_key_is_reported_not_papered_over_with_the_header(
        self, tmp_path: Path, bad: str
    ) -> None:
        project = _project(tmp_path, f"daemon:\n  expected_version: {bad}\n", HEADER)

        assert _resolve(project) == (1, "unknown", "config-invalid")
