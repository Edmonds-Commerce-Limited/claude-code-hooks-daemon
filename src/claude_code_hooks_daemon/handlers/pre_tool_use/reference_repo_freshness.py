"""ReferenceRepoFreshnessHandler - the backstop between a stale clone and a read.

The SessionStart sweep fetches and safely fast-forwards every governed reference
repo. This handler covers what the sweep cannot: a repo that goes stale DURING a
session, one cloned after the sweep ran, and one the sweep could not make fresh
because the tree was dirty or had diverged.

**It performs no network I/O, ever.** ``Timeout.GIT_FETCH_SESSION`` and
``GIT_PULL_SESSION`` are 30s apiece against a 30s hook socket budget, so one
fetch here could consume the entire budget for a SINGLE repo — and a project can
govern several. Everything this handler knows comes from the cache the sweep
wrote. ``test_the_handler_never_performs_network_io`` is what keeps that true.

Two boundaries are worth stating because getting either wrong makes the system
unusable rather than merely wrong:

``git is always exempt``
    Inspecting and fixing a governed repo is exactly the work this handler wants
    to provoke, and the remedy it PRINTS is a ``git`` command. A handler that
    blocks the command it just told you to run cannot be satisfied, so every
    ``git`` segment passes. The exemption is asserted in the tests against the
    string ``remediation_command`` actually returns, so the two cannot drift.

``un-checkable never blocks``
    A repo with no remote, no upstream or a detached HEAD is reported by the
    sweep once and never gates a read. This project keeps a canary clone whose
    origin is invalid BY DESIGN; if un-checkable could block, that clone would
    be unreadable forever and the only fix would be to turn the system off.
"""

import logging
from pathlib import Path, PurePosixPath
from typing import Any, Final

from claude_code_hooks_daemon.config.models import ReferenceReposConfig
from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.reference_repos.cache import cached_states
from claude_code_hooks_daemon.reference_repos.model import RepoState
from claude_code_hooks_daemon.reference_repos.report import (
    NOT_VERIFIED_HEADLINE,
    display_path,
    remediation_command,
    repo_line,
)
from claude_code_hooks_daemon.utils.shell_segmentation import (
    split_unquoted,
    strip_message_bodies,
    strip_quoted_heredoc_bodies,
)

logger = logging.getLogger(__name__)

#: Tool input fields naming a single path, by tool. ``Glob`` and ``Grep`` both
#: use ``path`` to SCOPE a search, which reads the tree just as surely as a
#: ``Read`` of one file in it.
_PATH_FIELD_BY_TOOL: Final[dict[str, str]] = {
    ToolName.READ: "file_path",
    ToolName.GREP: "path",
    ToolName.GLOB: "path",
}

#: Shell operators that separate one command from the next. A chain is judged
#: per segment so a `git` segment cannot launder a read riding alongside it.
_CHAIN_SEPARATORS: Final[tuple[str, ...]] = ("&&", "||", ";", "|", "\n")

#: The one command word that is never intercepted. See the module docstring.
_EXEMPT_COMMAND: Final[str] = "git"

#: Words that only MOVE, and read nothing themselves. They matter because a
#: chain of navigation plus git is the second form of the remedy.
_NAVIGATION_COMMANDS: Final[frozenset[str]] = frozenset({"cd", "pushd", "popd"})

#: The three modes handled explicitly. ``block_once`` is deliberately absent:
#: it is the fall-through, so an unrecognised mode degrades to the documented
#: default rather than to silence.
_MODE_OFF: Final[str] = "off"
_MODE_ADVISE: Final[str] = "advise"
_MODE_BLOCK: Final[str] = "block"

#: Cap on how many sessions keep block_once state. The daemon outlives any one
#: session (Plan 00127), so an unbounded map is a slow leak; evicting the oldest
#: costs at most one extra advisory in a session nobody has touched in a while.
_MAX_TRACKED_SESSIONS: Final[int] = 64


_STALE_RULE = Rule(
    rule_id=RuleID.REFERENCE_REPO_STALE,
    blocked="a read of a governed reference clone that is behind or off its default branch",
    why=(
        "reasoning from a stale clone produces conclusions indistinguishable from "
        "correct ones -- no error, no failing test, just a wrong answer"
    ),
    fix="Run the `fix:` command printed beside the repo, then retry the read",
    verbose=(
        "Reference clones under `untracked/repos/` are fetched at session start and "
        "fast-forwarded when that is provably safe. This one could not be brought "
        "current, so what it contains is not what you think it is.\n\n"
        "`git` is NEVER intercepted, so the printed remedy is always runnable, and a "
        "repo that cannot be checked at all never blocks anything."
    ),
)

_NOT_VERIFIED_RULE = Rule(
    rule_id=RuleID.REFERENCE_REPO_NOT_VERIFIED,
    blocked="a read of a governed reference clone with no in-date freshness reading",
    why=(
        "nobody has checked this clone, which is a different fact from it being "
        "stale -- and treating the two the same either cries wolf or gives false comfort"
    ),
    fix="Run `hooks-daemon reference-repos` to fetch every governed repo and refresh",
    verbose=(
        "NOT VERIFIED means no sweep has run this session, or the cached reading "
        "expired. The repo may be perfectly current -- the point is that nothing has "
        "confirmed it.\n\n"
        "`hooks-daemon reference-repos` fetches every governed repo, fast-forwards the "
        "ones it safely can, and records the result."
    ),
)


def _command_word(word: str) -> str:
    """The bare command name, with any path or quoting stripped.

    ``/usr/bin/git`` and ``git`` are the same program, and this handler's
    exemption is the only thing keeping the remedy it prints runnable — so a
    respelling must not cost the exemption and deny a legitimate fix.
    """
    return PurePosixPath(word.strip("\"'")).name


def _is_git_only_chain(segments: list[list[str]]) -> bool:
    """True when the whole chain does nothing but navigate to a repo and run git.

    ``git -C <repo> pull`` was exempt from the start; ``cd <repo> && git pull``
    was not, which left a reader who does the obvious thing — navigate in, then
    fix the repo — blocked while doing exactly what the deny message asked for.
    Plan 00401 Task 4.3 names both forms.

    Scoped to a chain that is ONLY navigation and git: a `cd` that is followed
    by a read still engages, so `cd <repo> && git pull && cat x` is judged, not
    excused by the git segment sitting in front of the read.
    """
    heads = [_command_word(words[0]) for words in segments]
    if _EXEMPT_COMMAND not in heads:
        return False
    return all(head in _NAVIGATION_COMMANDS or head == _EXEMPT_COMMAND for head in heads)


class ReferenceRepoFreshnessHandler(PreToolUseHandlerBase):
    """Gate a read of a governed reference repo on a cached freshness reading."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.REFERENCE_REPO_FRESHNESS,
            priority=Priority.REFERENCE_REPO_FRESHNESS,
            tags=[HandlerTag.GIT, HandlerTag.BLOCKING, HandlerTag.WORKFLOW],
        )
        # Overwritten by the registry with the project's resolved
        # ``reference_repos`` block. Seeded with the model's own defaults rather
        # than None because in production it is never absent (Config declares a
        # default_factory), so a None branch would exist only to be wrong about:
        # `handle()` would have to re-check it on every Read in the session, and
        # a miss would raise inside PreToolUse rather than degrade.
        self._reference_repos: Any = ReferenceReposConfig()
        self._formatter = RuleFormatter()
        self.project_root_reader = self._default_project_root
        # session_id -> the governed subjects already reported in that session.
        self._reported: dict[str, set[str]] = {}

    @staticmethod
    def _default_project_root() -> Path:
        try:
            return ProjectContext.project_root()
        except RuntimeError:  # pragma: no cover - defensive, mirrors siblings
            logger.debug("ProjectContext not initialised; using cwd for the freshness gate")
            return Path.cwd()

    # ---------------------------------------------------------------- matching

    def _roots(self, project_root: Path) -> list[Path]:
        return [project_root / relative for relative in self._reference_repos.roots]

    def _touched_paths(self, hook_input: dict[str, Any], project_root: Path) -> list[Path]:
        """Every governed location this call would read.

        A ``Bash`` command is judged per segment, and a ``git`` segment
        contributes nothing — that is the exemption, applied where the command
        words are still attached to their own arguments.
        """
        tool_input = hook_input.get("tool_input") or {}
        tool_name = hook_input.get("tool_name", "")

        field = _PATH_FIELD_BY_TOOL.get(tool_name)
        if field is not None:
            raw = tool_input.get(field)
            if not raw:
                return []
            candidate = self._absolute(str(raw), project_root)
            roots = self._roots(project_root)
            return [candidate] if any(self._within(candidate, root) for root in roots) else []

        if tool_name != ToolName.BASH:
            return []

        # Strip the spans the SHELL never treats as commands before segmenting.
        # Without this, `_CHAIN_SEPARATORS` (which includes "\n") turns every
        # line of a `git commit -F - <<'EOF'` message into its own "segment", so
        # prose merely NAMING a governed repo parses as a read of it. That is
        # not hypothetical: it denied the commit shipping this handler's docs.
        raw_command = str(tool_input.get("command") or "")
        command = strip_message_bodies(strip_quoted_heredoc_bodies(raw_command))
        segments = [
            words
            for words in (segment.split() for segment in split_unquoted(command, _CHAIN_SEPARATORS))
            if words
        ]

        if _is_git_only_chain(segments):
            return []

        found: list[Path] = []
        for words in segments:
            if _command_word(words[0]) == _EXEMPT_COMMAND:
                continue
            found.extend(self._governed_words(words[1:], project_root))
        return found

    @staticmethod
    def _path_like(word: str) -> str | None:
        """The path a command word names, or ``None`` when it names none.

        Two normalisations, both added after probing found the parser silently
        blind to ordinary commands:

        - ``segment.split()`` leaves quote characters ATTACHED, so the word from
          ``cat 'untracked/repos/alpha/x.md'`` still carries its quotes and is
          relative to no root at all. That is the plainest shape there is.
        - A flag is skipped because a flag is not a path — but ``--file=<path>``
          is both, and the VALUE after ``=`` is what gets read.

        A false negative here is this handler's worst failure mode: it is
        silent, and silence from a freshness gate reads as "that repo is fine".
        """
        if word.startswith("-"):
            _, separator, value = word.partition("=")
            if not separator:
                return None
            word = value
        word = word.strip("\"'")
        return word or None

    def _governed_words(self, words: list[str], project_root: Path) -> list[Path]:
        """Arguments of one command segment that name a governed location."""
        roots = self._roots(project_root)
        governed: list[Path] = []
        for word in words:
            path_like = self._path_like(word)
            if path_like is None:
                continue
            candidate = self._absolute(path_like, project_root)
            if any(self._within(candidate, root) for root in roots):
                governed.append(candidate)
        return governed

    @staticmethod
    def _absolute(raw: str, project_root: Path) -> Path:
        path = Path(raw)
        return path if path.is_absolute() else project_root / path

    @staticmethod
    def _within(candidate: Path, root: Path) -> bool:
        return candidate == root or candidate.is_relative_to(root)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Engage only for a call that would read inside a governed root.

        Engagement is about LOCATION alone and reads no cache: the overwhelmingly
        common call touches nothing governed, and it should cost a prefix test
        and nothing more.
        """
        config = self._reference_repos
        if config is None or not config.enabled or config.mode == _MODE_OFF:
            return False
        project_root = self.project_root_reader()
        return bool(self._touched_paths(hook_input, project_root))

    # ----------------------------------------------------------------- verdict

    def _subject(self, path: Path, project_root: Path, known: dict[Path, RepoState] | None) -> Path:
        """The governed repo a touched path belongs to.

        Resolved from the cache when the repo is known. When it is not — a clone
        made after the sweep, or no cache at all — the convention's own shape
        gives the answer: one checkout per directory directly under a governed
        root. That keeps the block_once key stable across several reads of the
        same unknown repo, which is what stops one clone producing a block per
        file read.
        """
        if known:
            containing = [repo for repo in known if self._within(path, repo)]
            if containing:
                return max(containing, key=lambda repo: len(repo.parts))

        for root in self._roots(project_root):
            if self._within(path, root) and path != root:
                return root / path.relative_to(root).parts[0]
        return path

    def _already_reported(self, session_id: str, subject: Path) -> bool:
        return str(subject) in self._reported.get(session_id, set())

    def _record(self, session_id: str, subject: Path) -> None:
        if session_id not in self._reported and len(self._reported) >= _MAX_TRACKED_SESSIONS:
            self._reported.pop(next(iter(self._reported)))
        self._reported.setdefault(session_id, set()).add(str(subject))

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        config = self._reference_repos
        project_root = self.project_root_reader()
        session_id = str(hook_input.get("session_id") or "")

        known = cached_states(project_root, ttl_seconds=config.cache_ttl_minutes * 60)

        for path in self._touched_paths(hook_input, project_root):
            subject = self._subject(path, project_root, known)
            message = self._problem(subject, known, project_root)
            if message is None:
                continue
            return self._verdict(message, session_id, subject, config.mode)

        return GatingResult(decision=Decision.ALLOW)

    def _problem(
        self, subject: Path, known: dict[Path, RepoState] | None, project_root: Path
    ) -> str | None:
        """What is wrong with this repo, or ``None`` when nothing is.

        A missing reading and a stale reading get DIFFERENT sentences AND
        different rule IDs on purpose: "nobody checked" and "this is out of
        date" call for different responses, and collapsing them would either
        cry wolf or give false comfort. Two rules means `explain-rule` can
        answer each on its own terms.
        """
        if known is None or subject not in known:
            detail = (
                f"{NOT_VERIFIED_HEADLINE}: no in-date reading exists for "
                f"{display_path(subject, project_root)}, so what it contains may not be "
                "what you think it is."
            )
            return f"{self._formatter.verbose(_NOT_VERIFIED_RULE)}\n\n{detail}"

        state = known[subject]
        if not state.needs_attention:
            return None

        lines = [
            self._formatter.verbose(_STALE_RULE),
            "",
            "a governed reference repo is NOT up to date, and reading it now would "
            "mean reasoning from stale source:",
            "",
            f"  {repo_line(state, project_root=project_root)}",
        ]
        command = remediation_command(state)
        if command is not None:
            lines.extend(["", f"  fix: {command}"])
        else:
            lines.extend(
                [
                    "",
                    "  This repo carries uncommitted local changes, so there is no safe "
                    "mechanical fix — deal with those changes first; nothing here will "
                    "touch them.",
                ]
            )
        return "\n".join(lines)

    def _verdict(self, message: str, session_id: str, subject: Path, mode: str) -> GatingResult:
        """Apply the configured enforcement posture to a problem already found."""
        if mode == _MODE_ADVISE:
            return GatingResult(decision=Decision.ALLOW, context=[message])

        if mode == _MODE_BLOCK:
            return GatingResult.deny(message)

        # block_once (the default): tell the reader once per repo per session.
        # Per REPO because each stale clone is its own surprise, and per SESSION
        # because the daemon is shared (Plan 00127) — a daemon-wide count would
        # let one session consume every other session's single warning, which is
        # the bug Plan 00277 fixed for lsp_enforcement.
        if self._already_reported(session_id, subject):
            return GatingResult(decision=Decision.ALLOW, context=[message])

        self._record(session_id, subject)
        return GatingResult.deny(message)

    # ------------------------------------------------------------- self-report

    def get_rules(self) -> list[Rule]:
        """Two rules, because the two denials are genuinely different facts."""
        return [_STALE_RULE, _NOT_VERIFIED_RULE]

    def get_claude_md(self) -> str | None:
        """Guidance for the generated ``<hooksdaemon>`` block."""
        return (
            "## reference_repo_freshness — a stale reference clone is caught before you read it\n\n"
            "A `Read`, `Grep`, `Glob` or `Bash` call that reaches into a governed reference "
            "repository (`untracked/repos/` by default) is checked against the freshness "
            "reading taken at session start. A repo that is behind its upstream, or sitting "
            "on the wrong branch, is reported **once per repo per session** with a runnable "
            "`fix:` command; the retry then goes through.\n\n"
            "**The block is information, not an obstacle.** It fires once so that you cannot "
            "reason from weeks-old source without knowing it — which is a failure that "
            "otherwise produces confident, well-argued, wrong conclusions with nothing to "
            "signal them.\n\n"
            "**`git` is never intercepted**, so every printed remedy is runnable, and "
            "inspecting a governed repo is always allowed. A repo that cannot be checked at "
            "all — no remote, no upstream, detached HEAD — never blocks anything.\n\n"
            "`NOT VERIFIED` means something different from stale: nobody has checked, usually "
            "because no sweep has run this session. Run `hooks-daemon reference-repos` to "
            "fetch every governed repo and refresh the reading."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        # Both cases are driven as raw hook_input rather than as tool calls,
        # because the verdict depends on the CACHE rather than on anything in
        # the command. A real Read would assert whatever today's sweep happened
        # to record, so it would pass or fail for reasons unrelated to the code.
        # The probe path below is never a real clone, so it is never in the
        # cache, which makes NOT VERIFIED the deterministic answer.
        probe = "untracked/repos/__freshness_probe__"
        return [
            AcceptanceTest(
                title="reference-repo freshness - reading an unverified governed clone",
                command=f"Read {probe}/README.md",
                description=(
                    "A Read inside a governed reference repo with no in-date reading is "
                    "DENIED, and the message distinguishes NOT VERIFIED (nobody checked) "
                    "from stale (checked, and out of date). The retry is allowed: the block "
                    "informs once per repo per session rather than obstructing."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"NOT VERIFIED"],
                safety_notes=(
                    "Reads the cache only - never performs network I/O, never pulls, "
                    "and never blocks an un-checkable repo"
                ),
                test_type=TestType.BLOCKING,
                hook_input={
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Read",
                    "tool_input": {"file_path": f"{probe}/README.md"},
                    "session_id": "acceptance-freshness-deny",
                },
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="reference-repo freshness - git against the same repo is never blocked",
                command=f"git -C {probe} pull --ff-only",
                description=(
                    "The near-miss that keeps the handler satisfiable: this command touches "
                    "exactly the repo the deny message names, and is the very remedy that "
                    "message prints. A handler that blocked it could never be satisfied."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "--ff-only cannot create a merge commit, and the path is a probe that "
                    "does not exist - git simply reports it is not a repository"
                ),
                test_type=TestType.BLOCKING,
                hook_input={
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": f"git -C {probe} pull --ff-only"},
                    "session_id": "acceptance-freshness-allow",
                },
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
