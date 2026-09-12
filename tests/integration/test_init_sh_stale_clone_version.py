"""`init.sh` names a stale clone instead of failing generically (Plan 00386).

Field report (GitHub issue #38): a container checkout held a leftover v3.15.1
clone under the gitignored `.claude/hooks-daemon/`, while the repository's
TRACKED daemon assets had been deployed from v3.60.0. The daemon refused to
start, and every hook event for the whole session returned:

    HOOKS DAEMON: Not currently running
    Error: daemon_startup_failed - Failed to start hooks daemon.

Every safety handler was inactive, under `--dangerously-skip-permissions`, until
a human noticed. The message points at `logs` and `restart`, and a restart cannot
change either version — so the advice loops forever and the reader never learns
what is actually wrong.

**This check has to live in bash.** The daemon cannot report its own absence, and
the clone that failed to start is frequently the one whose venv or Python is the
problem — so nothing here may depend on importing the package. Both versions are
read with `grep` from files that are plain text by contract.

`TestTheShellAgreesWithThePythonParser` is the anti-drift pin: the same header
line is fed to the shell extractor and to
:data:`claude_code_hooks_daemon.utils.deployed_version.VERSION_MARKER_RE`, and
they must return the same version. The two parsers cannot be shared across the
language boundary, so the contract is asserted instead of assumed.
"""

from __future__ import annotations

import subprocess  # nosec B404 — runs the trusted system `bash`
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.deployed_version import version_marker_in

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_INIT_SH: Final[Path] = _REPO_ROOT / ".claude" / "init.sh"

_TIMEOUT_SECONDS: Final[int] = 30

#: `init.sh` always exits successfully: a hook that fails must never block
#: Claude Code, so the exit status says nothing about which branch ran.
_FAIL_OPEN_EXIT: Final[int] = 0

_STALE_CLONE: Final[str] = "3.15.1"
_TRACKED: Final[str] = "3.60.0"


def _marker_line(version: str, date: str = "2026-09-11") -> str:
    """The exact header `docs_generator._render_header()` emits."""
    return (
        f"> Generated on {date} (v{version}) by `generate-docs`. "
        f"Regenerate: `.claude/hooks-daemon/bin/hooks-daemon generate-docs`"
    )


def _project(
    tmp_path: Path,
    *,
    clone_version: str | None = _STALE_CLONE,
    tracked_version: str | None = _TRACKED,
) -> Path:
    """A client-shaped checkout: tracked assets beside a gitignored clone.

    A COPY of `init.sh`, deliberately — it derives `PROJECT_PATH` from
    `BASH_SOURCE`, so sourcing the real file would resolve to this repository
    and the test would assert against whatever the developer's tree happens to
    hold rather than against the contract.
    """
    project = tmp_path / "project"
    claude = project / ".claude"
    claude.mkdir(parents=True)
    (claude / "init.sh").write_text(_INIT_SH.read_text(encoding="utf-8"), encoding="utf-8")

    if tracked_version is not None:
        (claude / "HOOKS-DAEMON.md").write_text(
            f"# Hooks Daemon - Active Configuration\n\n{_marker_line(tracked_version)}\n",
            encoding="utf-8",
        )

    if clone_version is not None:
        version_py = claude / "hooks-daemon" / "src" / "claude_code_hooks_daemon" / "version.py"
        version_py.parent.mkdir(parents=True)
        version_py.write_text(
            f'"""Version information."""\n\n__version__ = "{clone_version}"\n',
            encoding="utf-8",
        )

    return project


def _run(project: Path, script: str) -> subprocess.CompletedProcess[str]:
    """Source the project's `init.sh`, then run `script` against its functions."""
    return subprocess.run(  # nosec B603 — fixed argv, no shell, trusted input
        ["bash", "-c", f'source "{project / ".claude" / "init.sh"}"\n{script}'],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(project)},
        check=False,
    )


def _rc(call: str) -> str:
    """A snippet reporting `call`'s status without tripping `init.sh`'s `set -e`.

    `init.sh` runs under `set -e`, so a bare failing call at top level would kill
    the shell before anything could be printed — and these functions return 1 on
    every NORMAL "nothing to report" path. An `if` condition is exempt from
    `set -e`, and is also exactly how the generated forwarders call `ensure_daemon`
    (`if ! ensure_daemon; then ...`), so this is the production shape rather than
    a test-only workaround.
    """
    return f'if {call}; then echo "rc=0"; else echo "rc=1"; fi'


class TestReadingTheTwoVersions:
    def test_the_clone_version_comes_from_the_installed_package(self, tmp_path: Path) -> None:
        result = _run(_project(tmp_path), "_clone_version")
        assert result.stdout.strip() == _STALE_CLONE, result.stderr

    def test_the_tracked_version_comes_from_the_generated_doc_marker(self, tmp_path: Path) -> None:
        result = _run(_project(tmp_path), "_tracked_deployed_version")
        assert result.stdout.strip() == _TRACKED, result.stderr

    def test_an_absent_clone_reports_nothing_rather_than_guessing(self, tmp_path: Path) -> None:
        """A fresh checkout that never installed the daemon is a NORMAL state."""
        result = _run(_project(tmp_path, clone_version=None), _rc("_clone_version"))
        assert "rc=1" in result.stdout
        assert _STALE_CLONE not in result.stdout

    def test_a_doc_with_no_marker_reports_nothing(self, tmp_path: Path) -> None:
        """A project whose generated doc predates the header is also normal."""
        project = _project(tmp_path)
        (project / ".claude" / "HOOKS-DAEMON.md").write_text("# No marker here\n", encoding="utf-8")
        result = _run(project, _rc("_tracked_deployed_version"))
        assert "rc=1" in result.stdout


class TestTheShellAgreesWithThePythonParser:
    """The anti-drift pin: one header line, two languages, one answer."""

    def test_both_parsers_extract_the_same_version(self, tmp_path: Path) -> None:
        line = _marker_line("3.60.0")

        from_python = version_marker_in(line)
        from_shell = _run(_project(tmp_path), "_tracked_deployed_version").stdout.strip()

        assert from_python == "3.60.0"
        assert from_shell == from_python, (
            "the shell extractor in init.sh and VERSION_MARKER_RE disagree about "
            "the same header line — they cannot be shared across the language "
            "boundary, so this assertion is the only thing holding them together"
        )


class TestDetection:
    def test_differing_versions_are_a_mismatch(self, tmp_path: Path) -> None:
        result = _run(
            _project(tmp_path),
            _rc("_detect_stale_clone")
            + '\necho "clone=$_HOOKS_DAEMON_CLONE_VERSION tracked=$_HOOKS_DAEMON_TRACKED_VERSION"',
        )
        assert "rc=0" in result.stdout, result.stderr
        assert f"clone={_STALE_CLONE} tracked={_TRACKED}" in result.stdout, result.stderr

    def test_identical_versions_are_silent(self, tmp_path: Path) -> None:
        """The healthy case, which is nearly every project."""
        project = _project(tmp_path, clone_version=_TRACKED, tracked_version=_TRACKED)
        result = _run(project, _rc("_detect_stale_clone"))
        assert "rc=1" in result.stdout

    def test_a_missing_marker_is_not_a_mismatch(self, tmp_path: Path) -> None:
        """Unknowable is not the same as wrong — never accuse on absent evidence."""
        result = _run(_project(tmp_path, tracked_version=None), _rc("_detect_stale_clone"))
        assert "rc=1" in result.stdout


class TestTheMessage:
    """What the reporter would actually have read."""

    def _context(self, tmp_path: Path, *, clone: str, tracked: str) -> str:
        project = _project(tmp_path, clone_version=clone, tracked_version=tracked)
        result = _run(
            project,
            _rc("_detect_stale_clone") + "\n"
            "_HOOKS_DAEMON_VERSION_MISMATCH=true\n"
            'emit_hook_error "PreToolUse" "daemon_startup_failed" "Failed to start"',
        )
        assert result.returncode == _FAIL_OPEN_EXIT, result.stderr
        assert "rc=0" in result.stdout, "the two versions were expected to differ"
        # Drop the detection probe's own line; what follows is the hook response.
        return result.stdout.split("rc=0\n", 1)[1]

    def test_it_names_both_versions(self, tmp_path: Path) -> None:
        """A generic message IS the defect; naming one version is half a fix."""
        context = self._context(tmp_path, clone=_STALE_CLONE, tracked=_TRACKED)
        assert _STALE_CLONE in context
        assert _TRACKED in context

    def test_it_names_the_upgrade_command_when_the_clone_is_behind(self, tmp_path: Path) -> None:
        context = self._context(tmp_path, clone=_STALE_CLONE, tracked=_TRACKED)
        assert "upgrade" in context.lower()
        assert _TRACKED in context, "the command must target the tracked version"

    def test_it_says_a_restart_cannot_fix_this(self, tmp_path: Path) -> None:
        """The reporter followed restart advice in a loop. The message has to
        close that loop explicitly, not merely offer a better option."""
        context = self._context(tmp_path, clone=_STALE_CLONE, tracked=_TRACKED).lower()
        assert "restart" in context
        assert "cannot" in context or "will not" in context

    def test_a_clone_ahead_of_the_tracked_assets_gets_the_other_remedy(
        self, tmp_path: Path
    ) -> None:
        """Both directions. Upgrading a clone that is already newer would be
        advice that cannot work — here the TRACKED assets are the stale half."""
        context = self._context(tmp_path, clone="3.63.0", tracked="3.60.0")
        assert "3.63.0" in context and "3.60.0" in context
        lowered = context.lower()
        assert "regenerate" in lowered or "redeploy" in lowered or "generate-docs" in lowered

    def test_the_response_is_still_valid_fail_open_json(self, tmp_path: Path) -> None:
        """A new branch must not break the transport contract every hook relies on."""
        import json

        raw = self._context(tmp_path, clone=_STALE_CLONE, tracked=_TRACKED)
        payload = json.loads(raw)
        assert payload["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert _TRACKED in payload["hookSpecificOutput"]["additionalContext"]


class TestEnsureDaemonWiresItUp:
    """Detection that nothing calls is detection that never fires."""

    def test_a_failed_start_with_drifted_versions_sets_the_flag(self, tmp_path: Path) -> None:
        result = _run(
            _project(tmp_path),
            "is_daemon_running() { return 1; }\n"
            "start_daemon() { return 1; }\n"
            "_is_ci_environment() { return 1; }\n"
            "_is_ci_enforced() { return 1; }\n"
            "_is_daemon_installed() { return 0; }\n"
            # The forwarders' own shape: `if ! ensure_daemon; then emit_hook_error ...`
            "if ! ensure_daemon; then :; fi\n" 'echo "mismatch=$_HOOKS_DAEMON_VERSION_MISMATCH"',
        )
        assert "mismatch=true" in result.stdout, result.stderr

    def test_a_failed_start_with_matching_versions_leaves_it_alone(self, tmp_path: Path) -> None:
        project = _project(tmp_path, clone_version=_TRACKED, tracked_version=_TRACKED)
        result = _run(
            project,
            "is_daemon_running() { return 1; }\n"
            "start_daemon() { return 1; }\n"
            "_is_ci_environment() { return 1; }\n"
            "_is_ci_enforced() { return 1; }\n"
            "_is_daemon_installed() { return 0; }\n"
            # The forwarders' own shape: `if ! ensure_daemon; then emit_hook_error ...`
            "if ! ensure_daemon; then :; fi\n" 'echo "mismatch=$_HOOKS_DAEMON_VERSION_MISMATCH"',
        )
        assert "mismatch=false" in result.stdout, result.stderr

    def test_an_unresolvable_venv_does_not_mask_the_version_mismatch(self, tmp_path: Path) -> None:
        """`_is_daemon_installed` needs a RESOLVED venv interpreter, and a clone
        stale enough to fail startup often cannot resolve one. If that check ran
        first, a genuine version mismatch would be reported as "not installed" —
        a message that names no version and sends the reader to install rather
        than upgrade. The mismatch can only fire when a clone is really on disk,
        so it is safe to test first, and this pins that order."""
        result = _run(
            _project(tmp_path),
            "is_daemon_running() { return 1; }\n"
            "start_daemon() { return 1; }\n"
            "_is_ci_environment() { return 1; }\n"
            "_is_ci_enforced() { return 1; }\n"
            # The real failure: no venv interpreter resolved, so this returns 1.
            "_is_daemon_installed() { return 1; }\n"
            "if ! ensure_daemon; then :; fi\n"
            'echo "mismatch=$_HOOKS_DAEMON_VERSION_MISMATCH '
            'notinstalled=$_HOOKS_DAEMON_NOT_INSTALLED"',
        )
        assert "mismatch=true notinstalled=false" in result.stdout, result.stderr

    def test_a_checkout_with_no_clone_at_all_is_still_reported_as_not_installed(
        self, tmp_path: Path
    ) -> None:
        """The control for the test above: reordering must not swallow the
        fresh-checkout diagnosis, which is the common case for a new contributor."""
        result = _run(
            _project(tmp_path, clone_version=None),
            "is_daemon_running() { return 1; }\n"
            "start_daemon() { return 1; }\n"
            "_is_ci_environment() { return 1; }\n"
            "_is_ci_enforced() { return 1; }\n"
            "_is_daemon_installed() { return 1; }\n"
            "if ! ensure_daemon; then :; fi\n"
            'echo "mismatch=$_HOOKS_DAEMON_VERSION_MISMATCH '
            'notinstalled=$_HOOKS_DAEMON_NOT_INSTALLED"',
        )
        assert "mismatch=false notinstalled=true" in result.stdout, result.stderr
