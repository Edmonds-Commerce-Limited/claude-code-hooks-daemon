"""DaemonSyncAfterMergeHandler — a merge/pull/rebase can silently stale the daemon.

The daemon reads its config ONCE, at startup, and imports every handler module
once at ``initialise()`` without ever hot-reloading. So a ``git pull`` that
brings in someone else's `hooks-daemon.yaml` — a new blocking handler, a retuned
priority, a changed option — leaves the project running the OLD config while the
repository contains the new one. Nothing says so, and the failure is the worst
shape there is: a guard that is committed, believed, and not actually applying.

**A pull is the moment that mismatch is created**, which makes it a cheaper place
to catch it than startup: the operation is right there, in context, with the
person who ran it.

ADVISORY ONLY, and that is not timidity. The owner ruled it (Plan 00386 Task
1.1), and the alternative is not available anyway: the daemon serves this very
hook in-process, so a daemon that restarted itself here would be killing the
process that still owes a response. A lost hook response is a failed hook, and a
failed hook can block the user's next tool call — trading a silent staleness bug
for a loud breakage.

Scope is bounded the same way ``merge_qa_report`` bounds its own: only what
``ORIG_HEAD..HEAD`` actually introduced. Re-reporting pre-existing state on every
pull is the noise failure that gets an advisory ignored, and this handler runs on
every pull, so the SILENT path is the common one.

Not covered, deliberately: a pull run in ANOTHER terminal, which this session
never sees. That needs a check at startup rather than at the operation, and is
Plan 00386's half of the same defect.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.deployed_version import (
    TRACKED_VERSION_DOC_REL_PATH,
    read_tracked_deployed_version,
)
from claude_code_hooks_daemon.utils.git_repo import GitRepo
from claude_code_hooks_daemon.utils.merge_scope import (
    changed_path_is_or_is_under,
    changed_paths,
    is_git_merge_pull_rebase_command,
)


def _running_version() -> str:
    """The version of the daemon serving this hook.

    Wrapped in a function rather than imported as a constant so a test can state
    a version without reaching into module globals.
    """
    from claude_code_hooks_daemon.version import __version__

    return __version__


#: Handler-code locations whose change makes the running daemon stale. The
#: CONFIG file is not listed here because it is resolved from
#: ``ProjectContext.config_path()`` instead — asking the runtime where its own
#: config is cannot drift, whereas a second literal can.
#:
#: ``project_handlers.path`` is configurable (default ``.claude/project-handlers``)
#: and is NOT injected into this handler, so a project that relocates it should
#: set ``watch_paths`` rather than rely on this default. Said plainly in
#: ``get_claude_md`` too, because a default that is silently wrong for a
#: relocated tree is exactly the kind of thing nobody discovers.
_DEFAULT_WATCH_PATHS: Final[tuple[str, ...]] = (".claude/project-handlers",)

_CWD_FIELD: Final[str] = "cwd"

_HEADER: Final[str] = (
    "DAEMON MAY BE STALE: this merge/pull/rebase changed daemon configuration "
    "or handler code. The running daemon read its config at startup and imported "
    "its handlers once, and does NOT hot-reload — so what you just pulled is not "
    "in force yet."
)


class DaemonSyncAfterMergeHandler(PostToolUseHandlerBase):
    """Advise a restart when a merge/pull/rebase changed daemon config or handlers."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.DAEMON_SYNC_AFTER_MERGE,
            priority=Priority.DAEMON_SYNC_AFTER_MERGE,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
                HandlerTag.GIT,
            ],
        )
        #: Configurable via ``options.watch_paths``; injected by the registry
        #: with the ``_``-prefixed name.
        self._watch_paths: tuple[str, ...] | list[str] = _DEFAULT_WATCH_PATHS

    def matches(self, hook_input: dict[str, Any]) -> bool:
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.BASH:
            return False
        command = get_bash_command(hook_input)
        if not command:
            return False
        return is_git_merge_pull_rebase_command(command)

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        project_root = ProjectContext.project_root()
        if self._is_foreign_repo(hook_input, project_root):
            return BlockingResult(decision=Decision.ALLOW)

        changed = changed_paths(project_root)
        if not changed:
            return BlockingResult(decision=Decision.ALLOW)

        sections: list[str] = []
        hits = self._stale_making_paths(project_root, changed)
        if hits:
            sections.extend([self._what_changed(hits), self._remedy()])
        sections.extend(self._version_section(project_root, changed))
        if not sections:
            return BlockingResult(decision=Decision.ALLOW)

        return BlockingResult(decision=Decision.ALLOW, context=[_HEADER, *sections])

    def _version_section(self, project_root: Path, changed: frozenset[str]) -> list[str]:
        """Report a daemon-VERSION mismatch this operation introduced.

        Gated on the marker file actually being touched. The doc is regenerated
        on every upgrade, so "the file changed" is not "the version changed" --
        conflating them would advise upgrading to the version already installed.
        A version difference this operation did NOT introduce belongs to the
        startup check (Plan 00386), not here.
        """
        if not changed_path_is_or_is_under(TRACKED_VERSION_DOC_REL_PATH, changed):
            return []
        tracked = read_tracked_deployed_version(project_root)
        if tracked is None:
            return []
        running = _running_version()
        if tracked == running:
            return []

        from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command

        return [
            f"DAEMON VERSION MISMATCH: this project's TRACKED assets were "
            f"deployed from v{tracked}, but the daemon running here is "
            f"v{running}. `.claude/hooks-daemon/` is gitignored, so the clone is "
            f"per-checkout and a pull cannot update it.",
            "Bring the clone up to the tracked version: "
            + daemon_cli_command("upgrade")
            + f" (the tracked marker says v{tracked} -- prefer it over the "
            "clone's own version when choosing an upgrade range, or the "
            "truth-changes and config-migration output covers a span already "
            "reconciled in this repository).",
            "Then close the loop the other way: the upgrade regenerates TRACKED "
            "artefacts, so re-check `git status` and commit that diff. Left "
            "uncommitted, the repository keeps describing a daemon it no longer "
            "has. Nothing here is upgraded, regenerated or committed for you.",
        ]

    def _stale_making_paths(self, project_root: Path, changed: frozenset[str]) -> list[str]:
        """Watched locations this operation actually touched, in report order."""
        candidates = [self._config_path_rel(project_root), *self._watch_paths]
        return [
            candidate
            for candidate in candidates
            if candidate and changed_path_is_or_is_under(candidate, changed)
        ]

    @staticmethod
    def _is_foreign_repo(hook_input: dict[str, Any], project_root: Path) -> bool:
        """True when the command runs inside a repo other than the project's.

        Mirrors `merge_qa_report._is_foreign_repo`: a merge inside a nested or
        vendored checkout owns its own history, and `ORIG_HEAD..HEAD` read
        against THIS project would describe an operation that never happened
        here.
        """
        cwd_raw = hook_input.get(_CWD_FIELD)
        if not cwd_raw:
            return False
        repo = GitRepo.resolve_for(Path(cwd_raw))
        return repo is not None and repo.root != project_root

    @staticmethod
    def _config_path_rel(project_root: Path) -> str | None:
        """The daemon's own config file, repo-relative; None when it is outside.

        A config path outside the repository cannot appear in a diff of that
        repository, so there is nothing to attribute and nothing to report.
        That is an ordinary state, not a failure — so it is TESTED for rather
        than caught. Letting ``relative_to`` raise and swallowing the
        ``ValueError`` would read identically to hiding a real error, and the
        error-hiding audit is correct to refuse the distinction.
        """
        config = ProjectContext.config_path()
        if not config.is_relative_to(project_root):
            return None
        return config.relative_to(project_root).as_posix()

    @staticmethod
    def _what_changed(hits: list[str]) -> str:
        """Name the paths. An advisory that says "config changed" without saying
        WHICH is one the reader cannot act on or verify."""
        return "Changed by this operation: " + ", ".join(f"`{hit}`" for hit in hits)

    @staticmethod
    def _remedy() -> str:
        from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command

        return (
            "Restart to load it: "
            + daemon_cli_command("restart")
            + " — then re-check with "
            + daemon_cli_command("status")
            + ". Nothing is restarted for you: this handler runs INSIDE the "
            "daemon serving this hook, so restarting here would kill the process "
            "still owing a response."
        )

    def get_claude_md(self) -> str | None:
        return (
            "## daemon_sync_after_merge — a pull can leave the daemon stale\n"
            "\n"
            "The daemon reads `hooks-daemon.yaml` ONCE at startup and imports "
            "handler modules once at initialise; it never hot-reloads. So a "
            "`git pull`/`merge`/`rebase` that brings in daemon config or "
            "project-handler code leaves the repository describing one set of "
            "protections while the process enforces the previous set — committed, "
            "believed, and not applying.\n"
            "\n"
            "This handler reports that, naming the exact paths the operation "
            "changed and the restart command. It is ADVISORY: it never restarts "
            "anything, because it runs inside the daemon that is serving the hook "
            "and a self-restart would drop the in-flight response. **Act on it — "
            "a config you pulled is not in force until you restart.**\n"
            "\n"
            "It also reports a daemon-VERSION mismatch. `.claude/hooks-daemon/` "
            "is gitignored, so the clone is per-checkout and a pull CANNOT update "
            "it — a pull that moves the tracked assets to a newer version leaves "
            "the clone behind, and a large enough gap makes the daemon refuse to "
            "start with every safety handler inactive. The version the tracked "
            "assets came from is read from `.claude/HOOKS-DAEMON.md`'s generated "
            "header; both versions are named so the upgrade range is honest.\n"
            "\n"
            "That mismatch runs BOTH ways, so the advisory asks for two things: "
            "upgrade the clone, then commit the tracked artefacts the upgrade "
            "regenerates. Skip the second and the repository keeps describing a "
            "daemon it no longer has.\n"
            "\n"
            "Scope is `ORIG_HEAD..HEAD`, so it reports only what THIS operation "
            "introduced and is silent otherwise — which is the usual outcome. The "
            "marker doc is regenerated on every upgrade, so a changed marker with "
            "an unchanged version says nothing. A pull performed in a DIFFERENT "
            "terminal is not seen at all.\n"
            "\n"
            "`options.watch_paths` lists the handler-code locations to watch "
            "(default `.claude/project-handlers`). The config file itself is "
            "resolved from the running daemon and always watched. **If your "
            "project sets a non-default `project_handlers.path`, add it to "
            "`watch_paths`** — it is not injected here, so the default would "
            "silently watch the wrong directory.\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="daemon-sync-after-merge - reports a stale daemon, silent otherwise",
                command=(
                    "On a branch that edits `.claude/hooks-daemon.yaml`, run "
                    "`git merge --no-ff <branch>` on the default branch"
                ),
                harness_cannot_produce=(
                    "This handler reads `git diff --name-only ORIG_HEAD HEAD` "
                    "against the REAL repository, so the precondition is a real "
                    "merge that actually sets `ORIG_HEAD` -- the harness's "
                    "fixture allowlist has no `git merge`, and `ORIG_HEAD` "
                    "cannot be fabricated without performing one. Covered by "
                    "tests/unit/handlers/post_tool_use/test_daemon_sync_after_merge.py, "
                    "which asserts both that a changed config is reported with "
                    "the path named and that an unrelated change stays silent."
                ),
                description=(
                    "The PostToolUse context contains a 'DAEMON MAY BE STALE' "
                    "block naming the changed path and the restart command; an "
                    "operation touching nothing daemon-related produces no "
                    "context at all."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"DAEMON MAY BE STALE|hooks-daemon\.yaml"],
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
            )
        ]
