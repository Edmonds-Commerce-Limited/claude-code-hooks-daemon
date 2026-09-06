"""Deny writes whose target is named outside the repository root (Plan 00333).

Every other path rule in this daemon is expressed in repo-relative coordinates,
and the absolute-to-relative conversion **is** the containment test. When that
conversion fails the verdict is uniformly *allow*: ``markdown_organization``
catches the ``ValueError`` and returns ``False``, ``sensitive_content`` comments
*"Outside the project root: not ours to judge"*, and six more do the same. So a
markdown file at the repo root is denied for being in the wrong location while
the identical file at ``/tmp/notes.md`` is silently permitted — it left the
coordinate system the rules are defined in, so nothing judges it. Reproducing it
showed ``handlers_matched=[]``: not one handler even considered the write.

The harm is durability, not tidiness. A container's temp directory is ephemeral
while the repository is usually a bind mount, so anything written there is lost
on restart, invisible to git and outside review. The project already held this
position in three places before it was ever a rule -- ``daemon/paths.py`` keeps
runtime files in ``untracked/`` *"not /tmp, to prevent security
vulnerabilities"*, ``scripts/echd-capture`` prefers ``untracked/captures`` and
calls the temp directory a *"last resort"*, and ``worktree_seed_suggestions``
calls ``untracked/`` *"this daemon's own scratch convention"*. The tools obeyed
it; the agent, for whom it was never a rule, did not.

**Two boundaries are deliberate.**

*Named targets only.* A PreToolUse hook receives a command string, not syscalls,
so it cannot see a library's temp file and must not pretend to. Measured on the
container that prompted this plan: of 324 MB in ``/tmp``, 308 MB was pytest's
own ``tmp_path`` tree and 2,415 of 2,834 entries were zero-length ``uv`` lock
files. A guard fighting uv, pytest, pyright, node and semgrep would be switched
off within a day, and a guard that is switched off protects nothing.

*Writes only.* Blocking reads would break diagnosis and gain nothing durable.

This handler does NOT change ``markdown_organization``. That handler's
out-of-root early return is correct for its own premise -- markdown
*organisation* has nothing to say about a file that is not in the project --
and is pinned by its own tests. Containment is a separate premise, so it gets a
separate handler rather than weakening an existing one to make room.
"""

import os
from pathlib import Path
from typing import Any, ClassVar

from claude_code_hooks_daemon.constants import HookInputField
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.paths import ProjectPath
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.tags import HandlerTag
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_write_targets

#: Repo-relative home for scratch, shared with `pipe_blocker` so the handler
#: that DENIES an out-of-repo write and the handler that RECOMMENDS a capture
#: target cannot drift into advising what the other blocks.
SCRATCH_DIR = ProjectPath.SCRATCH_DIR

#: Where Claude Code keeps its own state. Allowed by default: it is not scratch,
#: and it is not ephemeral in the setup this rule was written for -- under ccy
#: the Claude home is mapped back into the bind mount, so it has exactly the
#: durability property this guard exists to protect. An environment that does
#: NOT map it durably can refuse it via ``allow_claude_home: false``.
#:
#: This does not re-open Claude auto-memory: ``markdown_organization`` blocks
#: ``~/.claude/projects/*/memory/*.md`` on a different premise (untracked
#: knowledge bypasses review) through its own raw-string marker rule.
#: Containment asks "is it durable?", that rule asks "is it reviewable?", and a
#: path can fail the second while passing the first.
_CLAUDE_CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
_DEFAULT_CLAUDE_HOME = ".claude"

#: Tool inputs that NAME a write target, and the key each uses. ``get_file_path``
#: covers only Write and Edit, so relying on it alone would leave NotebookEdit
#: as a third open route.
_WRITE_TARGET_KEYS: dict[str, str] = {
    ToolName.WRITE: "file_path",
    ToolName.EDIT: "file_path",
    ToolName.NOTEBOOK_EDIT: "notebook_path",
}

_RULE = Rule(
    rule_id=RuleID.WRITE_OUTSIDE_PROJECT_ROOT,
    blocked="a write whose target is outside the repository root",
    why=(
        "Outside the repo nothing is version-controlled, reviewed or durable — a "
        "container's temp directory is wiped on restart, and every other path rule "
        "is scoped to the repo so none of them judges it"
    ),
    fix=f"Write it inside the repository — `{SCRATCH_DIR}/` is the scratch location",
    verbose=(
        "WHY BLOCKED:\n"
        "The target path is not inside this repository, so it is:\n"
        "  - EPHEMERAL - a container temp directory does not survive a restart\n"
        "  - INVISIBLE - not tracked by git, so it cannot be reviewed or shared\n"
        "  - UNGUARDED - every other path rule is expressed in repo-relative\n"
        "    coordinates, so an out-of-root path escapes all of them at once\n\n"
        f"WRITE IT HERE INSTEAD: {SCRATCH_DIR}/\n"
        "  - inside the working tree, so it survives container restarts\n"
        "  - gitignored, so it never reaches review\n"
        "  - the same convention the daemon's own runtime files already use\n\n"
        "Scratch is not a reason to leave the repository. There is no throwaway\n"
        "location, so nothing is lost by writing it somewhere durable.\n\n"
        "Reading an out-of-repo path is NOT blocked, and neither is a temp file a\n"
        "program creates for itself at runtime — only a path your command names."
    ),
)


class ProjectContainmentHandler(PreToolUseHandlerBase):
    """Deny a write to a path named outside the repository root.

    Priority: 14 (same band as the other handlers guarding content leaving the
    project, and ahead of every repo-relative path rule).
    Terminal: True.
    """

    #: REPO, the default: the boundary is the repository root rather than a
    #: sub-project root. ``untracked/`` lives at the repo root, so in a monorepo
    #: a sub-project writing to the shared scratch directory must not be denied.
    _TOOLS_WITH_NAMED_TARGETS: ClassVar[frozenset[str]] = frozenset(_WRITE_TARGET_KEYS)

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.PROJECT_CONTAINMENT,
            priority=Priority.PROJECT_CONTAINMENT,
            terminal=True,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )
        # Configuration attribute (set by registry after instantiation).
        # Empty by default on purpose: a declared exemption is a decision, an
        # assumed one is a hole.
        self._allowed_external_paths: list[str] | None = None
        self._allow_claude_home: bool = True

    @staticmethod
    def _claude_home() -> Path:
        """Claude Code's own state directory.

        ``CLAUDE_CONFIG_DIR`` when set, else the documented default. Read at
        call time rather than cached: the daemon outlives any one session, and
        a cached value would silently follow the environment the daemon
        happened to start in.
        """
        configured = os.environ.get(_CLAUDE_CONFIG_DIR_ENV)
        if configured:
            return Path(configured)
        return Path.home() / _DEFAULT_CLAUDE_HOME

    def _offending_targets(self, hook_input: dict[str, Any]) -> list[str]:
        """Every named write target that lies outside the repository root.

        Args:
            hook_input: The PreToolUse hook input.

        Returns:
            The offending paths in the order they were named, de-duplicated. A
            command that writes two files reports both — naming one would send
            the reader back for a second denial.
        """
        root = self._resolved_root()
        offending: list[str] = []

        for candidate in self._named_targets(hook_input):
            if candidate in offending:
                continue
            if self._is_outside(candidate, root) and not self._is_permitted(candidate):
                offending.append(candidate)

        return offending

    def _named_targets(self, hook_input: dict[str, Any]) -> list[str]:
        """Paths this tool call plainly names as a write target."""
        targets: list[str] = []

        tool_name = hook_input.get("tool_name", "")
        key = _WRITE_TARGET_KEYS.get(tool_name)
        if key is not None:
            named = hook_input.get("tool_input", {}).get(key)
            if named:
                targets.append(str(named))

        # `get_bash_write_targets` returns [] for a non-Bash event, so this is
        # safe to ask unconditionally. It is conservative by contract: a target
        # needing shell expansion yields nothing rather than a guess, because a
        # WRONG path would attribute a write to a file never touched.
        targets.extend(get_bash_write_targets(hook_input))

        return targets

    @staticmethod
    def _resolved_root() -> Path:
        return ProjectContext.project_root().resolve()

    @staticmethod
    def _is_within(candidate: str, container: Path) -> bool:
        """Is ``candidate`` at or under ``container``, comparing PATH COMPONENTS?

        ``relative_to`` is component-wise, which is the point: a string prefix
        test would read ``/repo-backup`` as being inside ``/repo``, and that is
        the usual way a containment check fails.
        """
        try:
            Path(candidate).resolve().relative_to(container)
        except ValueError:
            return False
        return True

    def _is_outside(self, candidate: str, root: Path) -> bool:
        """A relative path is never outside: it resolves against a working
        directory the daemon does not know, so treating it as out-of-root would
        deny writes on a guess."""
        if not Path(candidate).is_absolute():
            return False
        return not self._is_within(candidate, root)

    def _is_permitted(self, candidate: str) -> bool:
        """Is this out-of-root path covered by an allowance?"""
        if self._allow_claude_home and self._is_within(candidate, self._claude_home().resolve()):
            return True
        return any(
            self._is_within(candidate, Path(allowed).resolve())
            for allowed in self._allowed_external_paths or []
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True when this call names at least one out-of-root write target."""
        return bool(self._offending_targets(hook_input))

    def get_rules(self) -> list[Rule]:
        return [_RULE]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny, naming every offending path and the sanctioned location."""
        offending = self._offending_targets(hook_input)
        if not offending:
            return GatingResult(decision=Decision.ALLOW)

        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure
        formatter = RuleFormatter()

        if transcript_path and tracker.was_disclosed(
            transcript_path, RuleID.WRITE_OUTSIDE_PROJECT_ROOT
        ):
            message = formatter.terse(_RULE)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, RuleID.WRITE_OUTSIDE_PROJECT_ROOT)
            message = formatter.verbose(_RULE)

        listed = "\n".join(f"  - {path}" for path in offending)
        message += (
            f"\n\nOUTSIDE THE REPOSITORY:\n{listed}"
            f"\n\nREPOSITORY ROOT: {self._resolved_root()}"
            f"\nWRITE IT HERE INSTEAD: {self._resolved_root() / SCRATCH_DIR}/"
        )

        return GatingResult(decision=Decision.DENY, reason=message, context=[], guidance=None)

    def get_claude_md(self) -> str | None:
        return (
            "## project_containment — nothing is written outside the repository\n\n"
            "A `Write`, `Edit` or `NotebookEdit` whose `file_path` is outside the "
            "repository root is **blocked**, and so is a Bash command that plainly "
            "names an out-of-root write target — `>`, `>>`, `tee`, a heredoc, or a "
            "`cp`/`mv` destination.\n\n"
            f"**Write scratch to `{SCRATCH_DIR}/`**: inside the working tree so it "
            "survives a container restart, and gitignored so it never reaches review. "
            "A container's temp directory has neither property — work written there "
            "is gone on the next restart, which is why 'it's only scratch' is not a "
            "reason to leave the repository. There is no throwaway location, so "
            "nothing is lost by writing it somewhere durable.\n\n"
            "**NOT blocked**: reading any path; a temp file a PROGRAM creates for "
            "itself at runtime (pytest's `tmp_path`, a package manager's build dir) — "
            "this rule judges paths your command NAMES, not what a tool does "
            "internally; and a target the daemon cannot resolve without executing "
            "the command (`> \"$OUT\"`), which yields no path rather than a guess.\n\n"
            "**Claude Code's own state directory is allowed** (`$CLAUDE_CONFIG_DIR`, "
            "else `~/.claude`). It is not scratch, and it is not ephemeral where it is "
            "mapped into the bind mount. That does NOT re-open Claude auto-memory: "
            "`markdown_organization` blocks `~/.claude/projects/*/memory/*.md` on a "
            "different premise — this rule asks whether a path is DURABLE, that one "
            "asks whether it is REVIEWABLE, and memory fails the second test while "
            "passing the first.\n\n"
            "**Exemptions** are declarable via "
            "`handlers.pre_tool_use.project_containment.options.allowed_external_paths`, "
            "and the list is empty by default — a declared exemption is a decision, an "
            "assumed one is a hole."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Acceptance tests for the containment guard.

        No setup or cleanup commands: the write is denied before anything is
        created, and a `mkdir` outside the repo would be this handler's own
        business anyway.
        """
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Write to a path outside the repository",
                command=(
                    "Use the Write tool to write to "
                    "/tmp/acceptance-test-containment/probe.md with content '# probe'"
                ),
                description="Blocks a write to an ephemeral location outside the repo",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"BLOCKED",
                    r"outside the repository root",
                    r"untracked/scratch",
                ],
                safety_notes="Nothing is created - the write is denied before it happens.",
                test_type=TestType.BLOCKING,
                setup_commands=[],
                cleanup_commands=[],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Bash redirect to a path outside the repository",
                command=(
                    "Run the bash command: echo probe > /tmp/acceptance-test-containment.txt"
                ),
                description="Blocks the Bash side-door as well as the Write tool",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"BLOCKED",
                    r"outside the repository root",
                ],
                safety_notes="Nothing is created - the command is denied before it runs.",
                test_type=TestType.BLOCKING,
                setup_commands=[],
                cleanup_commands=[],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="The same scratch write, inside the repository",
                command=(
                    f"Use the Write tool to write to {SCRATCH_DIR}/acceptance-probe.md "
                    "with content '# probe'"
                ),
                description=(
                    "The near miss: identical intent and identical content, differing "
                    "only in whether the destination is inside the repo. A guard that "
                    "denied this too would be blocking scratch rather than blocking "
                    "ephemerality, and would be switched off within a day."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Writes one small file into the gitignored scratch directory; "
                    "removed by the cleanup command."
                ),
                test_type=TestType.BLOCKING,
                setup_commands=[],
                cleanup_commands=[f"rm -f {SCRATCH_DIR}/acceptance-probe.md"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
