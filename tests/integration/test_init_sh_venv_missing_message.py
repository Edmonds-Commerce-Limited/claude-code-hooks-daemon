"""A clone present with no usable venv must not be told to (re)install (#53).

Field shape: a bind-mounted project opened from a second view — host versus
container, or two containers sharing one mount — shares the gitignored
`.claude/hooks-daemon/` clone but NOT its venv, because the venv is keyed to a
Python-environment fingerprint that differs per view (Plan 00099). The first
hook call from the second view finds the directory but no interpreter it can
use, and `_is_daemon_installed()` — one boolean AND of "directory present" and
"venv interpreter present" — collapses that onto the exact same
`_HOOKS_DAEMON_NOT_INSTALLED` state as a genuinely fresh checkout with no clone
at all.

Following that answer's advice is destructive here. The skill's health probe
cannot pass against the other view's venv, so it escalates to `--force`
un-asked, and the installer's force path is `rm -rf "$DAEMON_DIR"`
(`install.sh:72`) — deleting the OTHER view's venv, which lives inside the
same directory this view is missing an interpreter for. Because it compounds,
alternating between views destroys each other's venv on every switch.

The safe remedy already exists and does not touch this problem: a
same-version upgrade. `scripts/upgrade_version.sh`'s idempotent path starts
with `ensure_venv` (Plan 00099/00104), builds the missing venv, and deletes
nothing. This module pins that the new diagnosis — clone present, venv
missing for THIS path — gets its own state and message, distinct from both
`NOT_INSTALLED` (no clone at all) and `VERSION_MISMATCH` (a stale clone).

Modelled on `test_init_sh_stale_clone_version.py` (the ladder-ordering
pattern) and `test_not_installed_fallback_names_the_checkout.py` (the
two-encoder + checkout-naming pattern).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Final

import pytest

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_INIT_SH: Final[Path] = _REPO_ROOT / ".claude" / "init.sh"
_TIMEOUT_SECONDS: Final[int] = 30

#: init.sh always exits 0 — a hook that fails must never block Claude Code.
_FAIL_OPEN_EXIT: Final[int] = 0

_CLONE_VERSION: Final[str] = "3.61.0"

#: Tools init.sh may invoke at source time, plus the fallback's own encoder —
#: mirrors test_not_installed_fallback_names_the_checkout.py's curated PATH.
_ESSENTIAL_TOOLS: Final[tuple[str, ...]] = (
    "sh",
    "bash",
    "env",
    "python3",
    "cat",
    "dirname",
    "basename",
    "tr",
    "hostname",
    "stat",
    "date",
    "mkdir",
    "touch",
    "chmod",
    "rm",
    "ls",
    "grep",
    "sed",
    "awk",
    "uname",
    "head",
    "cut",
    "sort",
    "wc",
)


def _project(tmp_path: Path, *, version_readable: bool = True) -> Path:
    """A checkout whose daemon clone directory exists but has no usable venv.

    A COPY of init.sh (it derives PROJECT_PATH from BASH_SOURCE — sourcing the
    real file would resolve to this repository, not a sandbox).
    """
    project = tmp_path / "project"
    claude = project / ".claude"
    claude.mkdir(parents=True)
    (claude / "init.sh").write_text(_INIT_SH.read_text(encoding="utf-8"), encoding="utf-8")

    clone_dir = claude / "hooks-daemon"

    # The real-clone marker _daemon_clone_present() checks for. Required:
    # HOOKS_DAEMON_ROOT_DIR always exists once init.sh has been sourced (it
    # unconditionally mkdir -p's its own untracked/ subdirectory), so bare
    # directory presence cannot distinguish a real clone from a fresh
    # checkout — this file is what makes the fixture a "real clone".
    resolve_venv_lib = clone_dir / "scripts" / "lib" / "resolve_venv.sh"
    resolve_venv_lib.parent.mkdir(parents=True)
    resolve_venv_lib.write_text("#!/bin/bash\n", encoding="utf-8")

    version_py = clone_dir / "src" / "claude_code_hooks_daemon" / "version.py"
    version_py.parent.mkdir(parents=True)
    if version_readable:
        version_py.write_text(
            f'"""Version information."""\n\n__version__ = "{_CLONE_VERSION}"\n',
            encoding="utf-8",
        )
    else:
        # Damaged/partial clone: file present, no parseable version marker.
        version_py.write_text("# truncated\n", encoding="utf-8")

    # No venv anywhere under clone_dir/untracked/ — this is the discriminator.
    return project


def _project_with_orphan_venv(tmp_path: Path, *, version_readable: bool = False) -> Path:
    """A clone that has LOST `scripts/lib/resolve_venv.sh` but still holds
    another environment's venv under `untracked/venv-*` — the case
    `_daemon_clone_present()` alone cannot see (review finding 1). Deleting
    this directory via install/force would destroy that venv exactly as
    surely as deleting a healthy clone would, so this must not read as a
    fresh checkout either.
    """
    project = tmp_path / "project"
    claude = project / ".claude"
    claude.mkdir(parents=True)
    (claude / "init.sh").write_text(_INIT_SH.read_text(encoding="utf-8"), encoding="utf-8")

    clone_dir = claude / "hooks-daemon"

    # Deliberately NO scripts/lib/resolve_venv.sh — that is the point.
    orphan_venv = clone_dir / "untracked" / "venv-other-view" / "bin"
    orphan_venv.mkdir(parents=True)
    (orphan_venv / "python").write_text("#!/bin/bash\n", encoding="utf-8")

    if version_readable:
        version_py = clone_dir / "src" / "claude_code_hooks_daemon" / "version.py"
        version_py.parent.mkdir(parents=True)
        version_py.write_text(
            f'"""Version information."""\n\n__version__ = "{_CLONE_VERSION}"\n',
            encoding="utf-8",
        )

    return project


def _curated_bin(tmp_path: Path, *, with_jq: bool) -> Path:
    bindir = tmp_path / ("bin-with-jq" if with_jq else "bin-without-jq")
    bindir.mkdir(exist_ok=True)
    tools = (*_ESSENTIAL_TOOLS, "jq") if with_jq else _ESSENTIAL_TOOLS
    for tool in tools:
        real = shutil.which(tool)
        if real is not None:
            dest = bindir / tool
            if not dest.exists():
                dest.symlink_to(real)
    return bindir


def _run(
    project: Path,
    script: str,
    *,
    with_jq: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Source the project's init.sh, then run `script` against its functions."""
    bindir = _curated_bin(project.parent, with_jq=with_jq)
    return subprocess.run(  # nosec B603 — fixed argv, no shell, trusted input
        ["bash", "-c", f'source "{project / ".claude" / "init.sh"}"\n{script}'],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        env={"PATH": str(bindir), "HOME": str(project)},
        check=False,
    )


#: The forwarders' own shape: `if ! ensure_daemon; then emit_hook_error ...`
#: with is_daemon_running/start_daemon/_is_ci_* stubbed so the failure path is
#: reached deterministically regardless of the host's real daemon state.
_FORCE_FAILED_START = (
    "is_daemon_running() { return 1; }\n"
    "start_daemon() { return 1; }\n"
    "_is_ci_environment() { return 1; }\n"
    "_is_ci_enforced() { return 1; }\n"
)


class TestEnsureDaemonWiresItUp:
    """The discriminator is a real-clone marker OR a leftover venv under
    `untracked/venv-*` — never version readability, and never bare directory
    presence (`HOOKS_DAEMON_ROOT_DIR` always exists post-source, see below)."""

    def test_clone_dir_present_no_venv_sets_the_new_flag_not_not_installed(
        self, tmp_path: Path
    ) -> None:
        result = _run(
            _project(tmp_path),
            _FORCE_FAILED_START + "if ! ensure_daemon; then :; fi\n"
            'echo "venv_missing=$_HOOKS_DAEMON_VENV_MISSING '
            'not_installed=$_HOOKS_DAEMON_NOT_INSTALLED"',
        )
        assert "venv_missing=true not_installed=false" in result.stdout, result.stderr

    def test_no_clone_at_all_is_still_not_installed_unchanged(self, tmp_path: Path) -> None:
        """State A (control): a genuinely fresh checkout is unaffected."""
        project = tmp_path / "project"
        claude = project / ".claude"
        claude.mkdir(parents=True)
        (claude / "init.sh").write_text(_INIT_SH.read_text(encoding="utf-8"), encoding="utf-8")

        result = _run(
            project,
            _FORCE_FAILED_START + "if ! ensure_daemon; then :; fi\n"
            'echo "venv_missing=$_HOOKS_DAEMON_VENV_MISSING '
            'not_installed=$_HOOKS_DAEMON_NOT_INSTALLED"',
        )
        assert "venv_missing=false not_installed=true" in result.stdout, result.stderr

    def test_an_unreadable_clone_version_still_sets_the_new_flag(self, tmp_path: Path) -> None:
        """A damaged/partial clone (version.py unparseable) must not fall
        through to the install advice either — see docstring."""
        result = _run(
            _project(tmp_path, version_readable=False),
            _FORCE_FAILED_START + "if ! ensure_daemon; then :; fi\n"
            'echo "venv_missing=$_HOOKS_DAEMON_VENV_MISSING '
            'not_installed=$_HOOKS_DAEMON_NOT_INSTALLED"',
        )
        assert "venv_missing=true not_installed=false" in result.stdout, result.stderr

    def test_a_real_stale_clone_version_mismatch_still_wins_over_venv_missing(
        self, tmp_path: Path
    ) -> None:
        """Ordering control: when BOTH a version mismatch and a missing venv
        are true, the more actionable mismatch diagnosis is reported (it
        names a concrete upgrade target; venv-missing's is looser)."""
        project = _project(tmp_path)
        (project / ".claude" / "HOOKS-DAEMON.md").write_text(
            "# Hooks Daemon - Active Configuration\n\n"
            "> Generated on 2026-09-11 (v3.99.0) by `generate-docs`. "
            "Regenerate: `.claude/hooks-daemon/bin/hooks-daemon generate-docs`\n",
            encoding="utf-8",
        )
        result = _run(
            project,
            _FORCE_FAILED_START + "if ! ensure_daemon; then :; fi\n"
            'echo "mismatch=$_HOOKS_DAEMON_VERSION_MISMATCH '
            'venv_missing=$_HOOKS_DAEMON_VENV_MISSING"',
        )
        assert "mismatch=true venv_missing=false" in result.stdout, result.stderr

    def test_an_orphaned_venv_with_no_resolve_venv_sh_still_sets_the_new_flag(
        self, tmp_path: Path
    ) -> None:
        """Review finding 1: `_daemon_clone_present()` alone is blind to a
        clone that lost `scripts/lib/resolve_venv.sh` but still holds
        another view's venv. That venv is exactly what install/force would
        destroy, so this case must not fall through to NOT_INSTALLED."""
        result = _run(
            _project_with_orphan_venv(tmp_path),
            _FORCE_FAILED_START + "if ! ensure_daemon; then :; fi\n"
            'echo "venv_missing=$_HOOKS_DAEMON_VENV_MISSING '
            'not_installed=$_HOOKS_DAEMON_NOT_INSTALLED"',
        )
        assert "venv_missing=true not_installed=false" in result.stdout, result.stderr

    def test_a_fresh_checkout_has_no_orphan_venv_either(self, tmp_path: Path) -> None:
        """Companion control: `mkdir -p untracked/` creates an EMPTY
        directory, so a genuinely fresh checkout never has a `venv-*` under
        it — the venv-* signal does not misfire on the common case."""
        project = tmp_path / "project"
        claude = project / ".claude"
        claude.mkdir(parents=True)
        (claude / "init.sh").write_text(_INIT_SH.read_text(encoding="utf-8"), encoding="utf-8")

        result = _run(
            project,
            _FORCE_FAILED_START + "if ! ensure_daemon; then :; fi\n"
            'echo "venv_missing=$_HOOKS_DAEMON_VENV_MISSING '
            'not_installed=$_HOOKS_DAEMON_NOT_INSTALLED"',
        )
        assert "venv_missing=false not_installed=true" in result.stdout, result.stderr


class TestTheMessage:
    """What the reporter would actually have read."""

    def _context(self, tmp_path: Path, *, version_readable: bool = True) -> str:
        project = _project(tmp_path, version_readable=version_readable)
        result = _run(
            project,
            _FORCE_FAILED_START + "if ! ensure_daemon; then :; fi\n"
            'emit_hook_error "PreToolUse" "daemon_startup_failed" "Failed to start"',
        )
        assert result.returncode == _FAIL_OPEN_EXIT, result.stderr
        return result.stdout

    def test_it_says_the_clone_is_present(self, tmp_path: Path) -> None:
        context = self._context(tmp_path).lower()
        assert "clone" in context
        assert "present" in context or "already" in context

    def test_it_names_the_version_pinned_upgrade_not_install(self, tmp_path: Path) -> None:
        context = self._context(tmp_path)
        assert "upgrade" in context.lower()
        assert _CLONE_VERSION in context

    def test_it_explicitly_warns_against_install(self, tmp_path: Path) -> None:
        context = self._context(tmp_path).lower()
        assert "do not" in context or "not use" in context or "never" in context
        assert "install" in context

    def test_it_explains_why_install_is_unsafe_here(self, tmp_path: Path) -> None:
        """The house principle: when the usual advice cannot succeed, say
        why — not just that it would fail."""
        context = self._context(tmp_path).lower()
        assert "delete" in context or "rm -rf" in context or "destroy" in context
        assert "venv" in context

    def test_it_names_the_checkout(self, tmp_path: Path) -> None:
        context = self._context(tmp_path)
        assert str(tmp_path / "project") in context

    def test_an_unreadable_version_still_gets_a_safe_message_not_a_blank(
        self, tmp_path: Path
    ) -> None:
        context = self._context(tmp_path, version_readable=False).lower()
        assert "install" in context
        assert "do not" in context or "not use" in context or "never" in context
        # No blank/placeholder version rendered into the message.
        assert 'v"' not in context
        assert (
            "version.py" in context or "cannot be determined" in context or "unreadable" in context
        )

    def test_the_response_is_still_valid_fail_open_json(self, tmp_path: Path) -> None:
        raw = self._context(tmp_path)
        payload = json.loads(raw)
        assert payload["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert "upgrade" in payload["hookSpecificOutput"]["additionalContext"].lower()

    def _orphan_context(self, tmp_path: Path, *, version_readable: bool = False) -> str:
        project = _project_with_orphan_venv(tmp_path, version_readable=version_readable)
        result = _run(
            project,
            _FORCE_FAILED_START + "if ! ensure_daemon; then :; fi\n"
            'emit_hook_error "PreToolUse" "daemon_startup_failed" "Failed to start"',
        )
        assert result.returncode == _FAIL_OPEN_EXIT, result.stderr
        return result.stdout

    def test_an_orphaned_venv_never_gets_the_install_advice(self, tmp_path: Path) -> None:
        """`args=install` must never appear — a substring match on bare "do
        not" is too weak here: NOT_INSTALLED's own message says "do not
        improvise" while still recommending install, so a fix that merely
        fell through to NOT_INSTALLED would pass a weaker assertion."""
        context = self._orphan_context(tmp_path).lower()
        assert "args=install" not in context
        assert "install/force" in context

    def test_an_orphaned_venv_gets_the_damaged_clone_message_even_when_a_version_reads(
        self, tmp_path: Path
    ) -> None:
        """Without `scripts/lib/resolve_venv.sh`, the clone is not trusted
        enough to hand out a version-pinned upgrade command, even if
        `version.py` happens to still parse — a partially-damaged clone can
        have some files intact and others gone, and guessing which half to
        trust is exactly the mistake this branch exists to avoid."""
        context = self._orphan_context(tmp_path, version_readable=True).lower()
        assert "args=upgrade" not in context
        assert "do not" in context or "not use" in context or "never" in context
        assert "install" in context


class TestTheStopFamilysBlock:
    """Stop/SubagentStop get their own block reason, following NOT_INSTALLED's
    pattern (`emit_hook_error` formats Stop-family events as `decision: block`,
    never `hookSpecificOutput`)."""

    def _block_reason(self, tmp_path: Path, event: str) -> dict[str, object]:
        project = _project(tmp_path)
        result = _run(
            project,
            _FORCE_FAILED_START + "if ! ensure_daemon; then :; fi\n"
            f'emit_hook_error "{event}" "daemon_startup_failed" "Failed to start"',
        )
        assert result.returncode == _FAIL_OPEN_EXIT, result.stderr
        return json.loads(result.stdout)

    def test_stop_blocks_and_does_not_say_plain_not_installed(self, tmp_path: Path) -> None:
        parsed = self._block_reason(tmp_path, "Stop")
        assert parsed["decision"] == "block"
        reason = str(parsed["reason"]).lower()
        assert "venv" in reason
        # Must be distinguishable from the plain "not installed" block reason.
        assert "not installed" not in reason

    def test_subagent_stop_blocks_and_does_not_say_plain_not_installed(
        self, tmp_path: Path
    ) -> None:
        parsed = self._block_reason(tmp_path, "SubagentStop")
        assert parsed["decision"] == "block"
        reason = str(parsed["reason"]).lower()
        assert "venv" in reason
        assert "not installed" not in reason


class TestTheEncodersAgree:
    """A message present in only one encoder is missing exactly where the
    host is unusual — jq-less hosts exist in production (Plan 00156)."""

    def _context_without_jq(self, tmp_path: Path, event: str) -> str:
        project = _project(tmp_path)
        result = _run(
            project,
            _FORCE_FAILED_START + "if ! ensure_daemon; then :; fi\n"
            f'emit_hook_error "{event}" "daemon_startup_failed" "Failed to start"',
            with_jq=False,
        )
        assert result.returncode == _FAIL_OPEN_EXIT, result.stderr
        return result.stdout

    def test_pretooluse_context_survives_the_jq_less_fallback(self, tmp_path: Path) -> None:
        stdout = self._context_without_jq(tmp_path, "PreToolUse")
        context = json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
        assert "upgrade" in context.lower()
        assert "install" in context.lower()

    def test_stop_block_reason_survives_the_jq_less_fallback(self, tmp_path: Path) -> None:
        stdout = self._context_without_jq(tmp_path, "Stop")
        parsed = json.loads(stdout)
        assert parsed["decision"] == "block"
        assert "venv" in str(parsed["reason"]).lower()

    @pytest.mark.skipif(shutil.which("jq") is None, reason="jq is not installed on this machine")
    def test_both_encoders_produce_the_same_pretooluse_answer(self, tmp_path: Path) -> None:
        project = _project(tmp_path)
        with_jq = _run(
            project,
            _FORCE_FAILED_START + "if ! ensure_daemon; then :; fi\n"
            'emit_hook_error "PreToolUse" "daemon_startup_failed" "Failed to start"',
            with_jq=True,
        ).stdout
        without_jq = _run(
            project,
            _FORCE_FAILED_START + "if ! ensure_daemon; then :; fi\n"
            'emit_hook_error "PreToolUse" "daemon_startup_failed" "Failed to start"',
            with_jq=False,
        ).stdout
        assert json.loads(with_jq) == json.loads(without_jq)
