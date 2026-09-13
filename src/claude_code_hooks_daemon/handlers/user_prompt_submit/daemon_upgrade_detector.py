"""DaemonUpgradeDetectorHandler — a running daemon notices its own upgrade (Plan 00395).

A daemon loads its code once, at startup, and keeps serving it for the life
of the process. When a DIFFERENT session or process on the same filesystem
upgrades this project's installed daemon while this one keeps running, every
safety handler in THIS process is still the OLD version, and nothing said so
before this handler existed.

**The signal needs no startup bookkeeping.** The version this process loaded
is already in memory (``claude_code_hooks_daemon.version.__version__``); the
version currently INSTALLED lives in the venv's ``.daemon-metadata.json``,
read through the existing public reader (``daemon.metadata.read_daemon_metadata``)
rather than a second one. Comparing the two on every UserPromptSubmit is
cheap enough to need no gate, and it is the moment an agent actually reads
what the daemon says.

**Re-resolve, never remember.** The venv is fingerprint-keyed
(``untracked/venv-{slug}-py{MM}-{fingerprint}/``), so an upgrade that changes
the fingerprint inputs creates a NEW venv directory rather than rewriting the
old one — a check that cached ``sys.prefix``, or a path resolved once at
construction, would keep reading the OLD venv's untouched metadata and report
"fresh" forever. ``resolve_existing_venv_python()`` is called fresh on every
``handle()``, exactly as the rest of the daemon's own startup resolution does.

**Silent when nothing changed.** An advisory on every turn for a fact that
changes at most once per upgrade would be worse than the defect it reports.

**Never restarts anything.** The owner's standing ruling (Plans 00386/00389):
advise loudly, name the command, never self-restart or self-upgrade. This
handler runs INSIDE the daemon serving the very hook that triggered it, so a
self-restart would drop the response this session is waiting on.

**Dormant in self-install mode.** In self-install mode the daemon runs from
``src/`` in this very repository — there is no separately deployed clone for
another session to upgrade underneath it, and the in-session cases (an
uncommitted source edit) are already covered by ``daemon_restart_verifier``
and ``check-source-fresh`` (Plan 00371), a different tier this handler must
not re-solve. Read via ``self_install_reader`` (defaulting to
``ProjectContext.self_install_mode()``) rather than re-parsing
``daemon.self_install_mode`` out of ``hooks-daemon.yaml`` directly: no
existing handler-injection channel carries an arbitrary top-level
``DaemonConfig`` field onto a handler instance (only ``worktree``,
``plan_workflow`` and ``documentation`` get that treatment in
``HandlerRegistry.register_all``), and adding one would be exactly the
``DaemonController``/registry startup change this plan's design rules out.
The two values cannot drift apart in a daemon that started successfully:
``daemon/validation.py`` and ``install/client_validator.py`` both refuse to
start unless the declared config flag and the actual daemon-source-at-
project-root layout agree.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import UserPromptSubmitHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.metadata import read_daemon_metadata
from claude_code_hooks_daemon.daemon.paths import resolve_existing_venv_python
from claude_code_hooks_daemon.install.install_stamp import parse_install_stamp
from claude_code_hooks_daemon.utils.cli_command import (
    daemon_cli_command,
    daemon_cli_command_for_docs,
    daemon_root,
)
from claude_code_hooks_daemon.version import __version__


class DaemonUpgradeDetectorHandler(UserPromptSubmitHandlerBase):
    """Advise when the INSTALLED daemon version has changed underneath this process."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.DAEMON_UPGRADE_DETECTOR,
            priority=Priority.DAEMON_UPGRADE_DETECTOR,
            terminal=False,
            tags=[HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )
        # Injection points for tests (mirrors ContractStalenessHandler's
        # self_install_reader/installed_version_reader pattern); production
        # reads the daemon's own cached self-install determination, the
        # daemon-root resolver and the version this process loaded.
        self.self_install_reader: Callable[[], bool] = ProjectContext.self_install_mode
        self.daemon_root_reader: Callable[[], Path] = daemon_root
        self.running_version_reader: Callable[[], str] = lambda: __version__

    def is_dormant(self) -> bool:
        """Whether self-install mode makes this check meaningless here.

        Fails toward dormant (True) when the reader cannot even tell which
        install mode is running: an advisory that does not know its own
        precondition must not announce itself as active policy.
        """
        try:
            return self.self_install_reader()
        except RuntimeError:
            return True

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Run on every UserPromptSubmit turn, except when dormant."""
        return not self.is_dormant()

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Compare the installed daemon version against the one this process loaded."""
        installed = self._resolve_installed_daemon_version()
        if installed is None:
            return BlockingResult(decision=Decision.ALLOW, context=[])

        running = self.running_version_reader()
        if installed == running:
            return BlockingResult(decision=Decision.ALLOW, context=[])

        return BlockingResult(
            decision=Decision.ALLOW,
            context=[self._advisory(running=running, installed=installed)],
        )

    def _resolve_installed_daemon_version(self) -> str | None:
        """Return the CURRENTLY INSTALLED daemon's bare ``X.Y.Z`` version.

        None covers every "cannot tell" case — no project context yet, no
        venv resolvable, no metadata file, malformed metadata, an
        unparseable version string — and every one of them means fail-open,
        never a block.
        """
        try:
            daemon_dir = self.daemon_root_reader()
        except RuntimeError:
            return None

        python_path = resolve_existing_venv_python(daemon_dir)
        if not python_path.is_file():
            return None

        venv_dir = python_path.parent.parent
        metadata = read_daemon_metadata(venv_dir)
        if metadata is None:
            return None

        try:
            return parse_install_stamp(metadata.daemon_version).version
        except ValueError:
            return None

    @staticmethod
    def _advisory(*, running: str, installed: str) -> str:
        """The full remedy, in one message: what changed and how to fix it."""
        return (
            "DAEMON VERSION CHANGED UNDERNEATH THIS SESSION: this process "
            f"loaded v{running}, but the installed daemon is now v{installed} "
            "-- another session or process upgraded it while this one kept "
            "running with everything it loaded at startup, safety handlers "
            "included. Restart to pick it up: "
            + daemon_cli_command("restart")
            + ". Nothing restarts itself: this handler runs INSIDE the "
            "daemon serving this very hook, so a self-restart would drop "
            "the response you are about to receive."
        )

    def get_claude_md(self) -> str | None:
        """Document the standing check: silent by default, loud when it fires."""
        return (
            "## daemon_upgrade_detector — a running daemon notices its own upgrade\n"
            "\n"
            "A daemon loads its code once at startup and keeps serving it for "
            "the life of the process. If a DIFFERENT session or process on "
            "the same filesystem upgrades this project's installed daemon "
            "while this one keeps running, every safety handler in this "
            "process is still the OLD version.\n"
            "\n"
            "Checked on every user turn: the version this process loaded "
            "against the CURRENTLY INSTALLED version on disk (the venv's "
            "`.daemon-metadata.json`), re-resolved fresh each time — never a "
            "value remembered from startup, because an upgrade that changes "
            "the venv's fingerprint creates a NEW venv directory rather than "
            "rewriting the old one. **Silent when they match** — an advisory "
            "on every turn for a fact that changes at most once per upgrade "
            "would be worse than the defect.\n"
            "\n"
            "When they differ, it names both versions and the restart "
            "command: " + daemon_cli_command_for_docs("restart") + ". "
            "ADVISORY ONLY, and never self-restarts: this handler runs "
            "INSIDE the daemon serving the very hook that triggered it, so "
            "restarting here would drop the response this session is "
            "waiting on.\n"
            "\n"
            "**Dormant in self-install mode** (this repository): there is "
            "no separately deployed clone for another session to upgrade "
            "underneath it here, and the in-session case (an uncommitted "
            "source edit) is already covered by "
            "`daemon_restart_verifier`/`check-source-fresh`. Relevant only "
            "to a CLIENT project with an installed `.claude/hooks-daemon/` "
            "clone.\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="daemon-upgrade-detector — reports a version changed underneath it",
                command=(
                    "Submit a prompt while the running daemon's installed "
                    "venv metadata records a different daemon_version than "
                    "claude_code_hooks_daemon.version.__version__"
                ),
                harness_cannot_produce=(
                    "This handler compares against the REAL installed venv's "
                    ".daemon-metadata.json, resolved fresh through "
                    "resolve_existing_venv_python() -- the harness has no way "
                    "to make a live daemon's own installation disagree with "
                    "itself without actually running a second install "
                    "underneath it. Covered by "
                    "tests/unit/handlers/user_prompt_submit/"
                    "test_daemon_upgrade_detector.py, which drives a real "
                    "fingerprint-keyed venv layout on disk and asserts both "
                    "the in-place-rewrite and new-venv-directory cases."
                ),
                description=(
                    "The UserPromptSubmit context contains a 'DAEMON VERSION "
                    "CHANGED UNDERNEATH THIS SESSION' block naming both "
                    "versions and the restart command; a matching version "
                    "produces no context at all."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"DAEMON VERSION CHANGED UNDERNEATH"],
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
            )
        ]
