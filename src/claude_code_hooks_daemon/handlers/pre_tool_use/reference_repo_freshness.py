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
import shlex
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.config.models import ReferenceReposConfig
from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.handlers.utils.bounded_fifo_map import BoundedFifoMap
from claude_code_hooks_daemon.reference_repos.cache import cached_states
from claude_code_hooks_daemon.reference_repos.discovery import GIT_ENTRY as _GIT_ENTRY
from claude_code_hooks_daemon.reference_repos.model import RepoState
from claude_code_hooks_daemon.reference_repos.report import (
    NOT_VERIFIED_HEADLINE,
    display_path,
    remediation_command,
    repo_line,
    unconfirmed_note,
)
from claude_code_hooks_daemon.reference_repos.sweep import governed_roots
from claude_code_hooks_daemon.utils.command_evasion import strip_reserved_word_prefix
from claude_code_hooks_daemon.utils.path_predicates import path_exists
from claude_code_hooks_daemon.utils.shell_segmentation import (
    command_word,
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
#: ``||`` is listed before ``|`` so the longer operator matches first.
_CHAIN_SEPARATORS: Final[tuple[str, ...]] = ("&&", "||", ";", "\n")

#: Split SEPARATELY from the chain, because position within a pipeline matters:
#: only the first stage runs against the working directory, and the rest read
#: the previous stage's stdout.
_PIPE_SEPARATORS: Final[tuple[str, ...]] = ("|",)

#: Commands that take a path but never read what is inside it. Denying these
#: over a stale repo answers a question nobody asked -- there is no sense in
#: which `rm -rf <repo>` needs the repo to be up to date first.
_NON_READING_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        "rm",
        "rmdir",
        "mkdir",
        "touch",
        "echo",
        "printf",
        "ln",
        "chmod",
        "chown",
        "mktemp",
        "install",
        "gh",
        "true",
        "false",
        "test",
    }
)

#: Commands that read whatever directory they are run from. Used ONLY for the
#: `cd <repo> && <read>` inference, where no path is named and the working
#: directory is the only thing that says which repo is being read. A positive
#: list rather than "anything unrecognised": this is an inference, and an
#: inference that fires on every unknown word fires on shell noise too.
_READING_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        "cat",
        "bat",
        "head",
        "tail",
        "less",
        "more",
        "rg",
        "grep",
        "egrep",
        "fgrep",
        "ag",
        "ack",
        "find",
        "ls",
        "tree",
        "awk",
        "wc",
        "diff",
        "jq",
        "sort",
        "cut",
        "file",
        "stat",
        "python",
        "python3",
        "node",
        "bash",
        "sh",
    }
)

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

#: Namespaces the "could not be confirmed" note apart from the block_once record
#: for the same repo. Two things are said at most once per repo per session and
#: they are NOT the same thing; one key for both would let the harmless one
#: silence the one that matters.
_UNCONFIRMED_KEY_PREFIX: Final[str] = "unconfirmed:"


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


def _tokenise(segment: str) -> list[str]:
    """Split one command into words the way the SHELL would.

    ``str.split()`` cuts ``cat "a/some file.md"`` at the space and yields a word
    that is not the path anyone typed. ``shlex`` splits on the same boundaries
    bash does and drops the quotes, so the path arrives intact.

    Falls back to a whitespace split when ``shlex`` refuses the string (an
    unbalanced quote, most often mid-edit). Over-splitting can only cost a
    match; raising here would cost the user their tool call.
    """
    try:
        return shlex.split(segment, comments=False)
    except ValueError:
        return segment.split()


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
        # Bounded with atomic FIFO eviction: this is a blocking handler, and a
        # race on its bookkeeping must not raise out of handle().
        self._reported: BoundedFifoMap[str, set[str]] = BoundedFifoMap(
            max_entries=_MAX_TRACKED_SESSIONS
        )

    @staticmethod
    def _default_project_root() -> Path:
        try:
            return ProjectContext.project_root()
        except RuntimeError:  # pragma: no cover - defensive, mirrors siblings
            logger.debug("ProjectContext not initialised; using cwd for the freshness gate")
            return Path.cwd()

    # ---------------------------------------------------------------- matching

    def _roots(self, project_root: Path) -> list[Path]:
        return governed_roots(project_root, self._reference_repos.roots)

    def _touched_paths(self, hook_input: dict[str, Any], project_root: Path) -> list[Path]:
        """Every governed location this call would read.

        A ``Bash`` command is judged per segment, and a ``git`` segment
        contributes nothing — that is the exemption, applied where the command
        words are still attached to their own arguments.
        """
        tool_input = hook_input.get(HookInputField.TOOL_INPUT) or {}
        tool_name = hook_input.get(HookInputField.TOOL_NAME, "")

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
        return self._governed_reads(command, project_root)

    def _governed_reads(self, command: str, project_root: Path) -> list[Path]:
        """The governed checkouts this command would actually READ.

        Three distinctions the first version collapsed, each of which produced a
        false positive on an ordinary command:

        ``naming a path is not reading it``
            ``rm -rf <repo>`` and ``echo see <repo>`` mention a repo without
            reading a byte of it, and answering them with "run `git pull` first"
            is advice about a different command than the one being run.

        ``a pipe SINK does not read the repo``
            In ``cd <repo> && git log | cat`` the ``cat`` reads git's stdout,
            not the checkout, so it must not resurrect a chain that is otherwise
            pure ``git``.

        ``cd establishes context, it does not read``
            A ``cd`` alone touches nothing. It only matters once a later reading
            command runs with no path of its own — which is exactly how
            ``cd <repo> && rg pattern .`` reads a repo it never names.
        """
        found: list[Path] = []
        # `cwd` persists ACROSS chain segments, because a `cd` does: in
        # `cd <repo> && rg x` the two halves are separate segments and the
        # second really does run inside the first's directory.
        cwd: Path | None = None
        for chain in split_unquoted(command, _CHAIN_SEPARATORS):
            for stage_index, stage in enumerate(split_unquoted(chain, _PIPE_SEPARATORS)):
                # `then rg x` runs rg: judge the command, not the reserved word.
                words = _tokenise(strip_reserved_word_prefix(stage))
                if not words:
                    continue
                head = command_word(words[0])

                if head == _EXEMPT_COMMAND:
                    continue
                if head in _NAVIGATION_COMMANDS:
                    cwd = next(iter(self._governed_words(words[1:], project_root)), None)
                    continue
                if head in _NON_READING_COMMANDS:
                    continue

                named = self._governed_words(words[1:], project_root)
                if named:
                    found.extend(named)
                elif cwd is not None and stage_index == 0 and head in _READING_COMMANDS:
                    # A reading command with no path of its own, run from inside
                    # a governed repo. Three conditions, each load-bearing:
                    #
                    # - only the FIRST stage of a pipeline; the rest read stdin;
                    # - only a command KNOWN to read. Inferring it from "not a
                    #   command I recognise" fired on the `HEREDOC_BODY`/`EOF`
                    #   placeholders that heredoc stripping leaves behind, which
                    #   is how this branch first blocked a plain `git commit`.
                    #   An unrecognised reader is still caught by a named path,
                    #   which is the primary signal; only this inference is
                    #   narrowed.
                    found.append(cwd)
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
        return any(
            self._subject(path, project_root, None) is not None
            for path in self._touched_paths(hook_input, project_root)
        )

    # ----------------------------------------------------------------- verdict

    def _subject(
        self, path: Path, project_root: Path, known: dict[Path, RepoState] | None
    ) -> Path | None:
        """The governed CHECKOUT a touched path belongs to, or ``None``.

        ``None`` matters more than the happy path. The first version invented a
        subject for any path under a root — the root itself, a loose note, a
        plain subdirectory — and then reported it as unverified. Nothing could
        ever clear that: :mod:`discovery` only records directories carrying a
        ``.git``, so no sweep and no CLI run could ever put those subjects in
        the cache, and the reader was handed a ``fix:`` command incapable of
        working. Under ``mode: block`` it was a permanent dead end, and it
        denied ``ls untracked/repos`` in this repository.

        So a path is governed only when a real checkout contains it. The cache
        answers first (deepest wins, for a checkout nested inside another), and
        a ``.git`` on disk answers second — which is what keeps a clone made
        after the sweep governed rather than invisible.
        """
        if known:
            containing = [repo for repo in known if self._within(path, repo)]
            if containing:
                return max(containing, key=lambda repo: len(repo.parts))

        for root in self._roots(project_root):
            if not self._within(path, root):
                continue
            # Walk DOWN from the root towards the path, taking the deepest
            # ancestor that is actually a checkout.
            candidate = root
            deepest: Path | None = None
            for part in path.relative_to(root).parts:
                candidate = candidate / part
                # `unreadable_means=False`: "I could not look" must not become
                # "this is a governed clone". A path whose ancestor is not
                # traversable cannot be READ either, so denying it would block a
                # call that was going to fail anyway, with a `fix:` command
                # incapable of clearing it — the same unclearable block that
                # inventing a subject produced. The cache is consulted BEFORE
                # this walk, so a repo that really was swept is still found.
                if path_exists(candidate / _GIT_ENTRY, unreadable_means=False):
                    deepest = candidate
            if deepest is not None:
                return deepest
        return None

    def _already_reported(self, session_id: str, key: str) -> bool:
        return key in self._reported.get(session_id, set())

    def _record(self, session_id: str, key: str) -> None:
        self._reported.get_or_insert(session_id, set()).add(key)

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Judge every governed checkout this call reaches into.

        Three answers, in descending order of what a reader must act on:
        nothing has checked this repo, this repo is out of date, or this repo's
        reading was never confirmed against an upstream. The first two are
        findings and obey the configured mode; the third is a NOTE that never
        blocks — see :func:`unconfirmed_note` for why blocking on it would make
        an unreachable clone permanently unreadable.
        """
        config = self._reference_repos
        project_root = self.project_root_reader()
        session_id = str(hook_input.get(HookInputField.SESSION_ID) or "")

        known = cached_states(project_root, ttl_seconds=config.cache_ttl_minutes * 60)

        notes: list[str] = []
        for path in self._touched_paths(hook_input, project_root):
            subject = self._subject(path, project_root, known)
            if subject is None:
                # Under a governed root but not inside any checkout — a loose
                # file, a scratch directory, the root itself. Nothing to judge.
                continue

            if known is None or subject not in known:
                blocking = self._is_blocking(session_id, subject, config.mode)
                message = self._not_verified(subject, project_root, blocking=blocking)
                return self._verdict(message, session_id, subject, config.mode)

            state = known[subject]
            if state.needs_attention:
                blocking = self._is_blocking(session_id, subject, config.mode)
                message = self._stale(state, project_root, blocking=blocking)
                return self._verdict(message, session_id, subject, config.mode)

            note = self._unconfirmed(state, subject, session_id, project_root)
            if note is not None:
                notes.append(note)

        return GatingResult(decision=Decision.ALLOW, context=notes)

    def _unconfirmed(
        self, state: RepoState, subject: Path, session_id: str, project_root: Path
    ) -> str | None:
        """The note for a repo nobody could confirm, at most once per session.

        Tracked under its OWN key rather than the subject alone. Sharing the key
        would let a note at the start of a session spend that repo's single
        block, so a genuine staleness discovered minutes later would arrive as
        quiet context instead of stopping anyone.
        """
        note = unconfirmed_note(state, project_root=project_root)
        if note is None:
            return None
        key = f"{_UNCONFIRMED_KEY_PREFIX}{subject}"
        if self._already_reported(session_id, key):
            return None
        self._record(session_id, key)
        return note

    def _not_verified(self, subject: Path, project_root: Path, *, blocking: bool) -> str:
        """Nobody has checked this repo.

        A DIFFERENT sentence and a different rule ID from :meth:`_stale`, on
        purpose: "nobody checked" and "this is out of date" call for different
        responses, and collapsing them would either cry wolf or give false
        comfort. Two rules means `explain-rule` can answer each on its own terms.

        ``blocking`` selects the headline: the deny rendering when this call
        will actually be denied, the ALLOW-path advisory rendering (Plan
        00466 N8) when it will not -- an `advise`-mode result or a
        `block_once` repeat must never open with "BLOCKED", because the
        call already ran.
        """
        headline = (
            self._formatter.verbose(_NOT_VERIFIED_RULE)
            if blocking
            else self._formatter.advisory(_NOT_VERIFIED_RULE)
        )
        detail = (
            f"{NOT_VERIFIED_HEADLINE}: no in-date reading exists for "
            f"{display_path(subject, project_root)}, so what it contains may not be "
            "what you think it is."
        )
        return f"{headline}\n\n{detail}"

    def _stale(self, state: RepoState, project_root: Path, *, blocking: bool) -> str:
        """This repo was checked, and it is not what the reader thinks it is.

        See :meth:`_not_verified` for what ``blocking`` selects and why.
        """
        headline = (
            self._formatter.verbose(_STALE_RULE)
            if blocking
            else self._formatter.advisory(_STALE_RULE)
        )
        lines = [
            headline,
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

    def _is_blocking(self, session_id: str, subject: Path, mode: str) -> bool:
        """Whether THIS occurrence, under ``mode``, will actually stop the call.

        Mirrors :meth:`_verdict`'s own decision exactly, without the
        recording side effect: a message must be built with the RIGHT
        headline before ``_verdict`` is called, so this preview has to
        exist separately from the one authoritative decision (and
        recording) `_verdict` still makes. Consistency between the two is
        pinned by ``TestIsBlockingMatchesVerdict``.
        """
        if mode == _MODE_ADVISE:
            return False
        if mode == _MODE_BLOCK:
            return True
        return not self._already_reported(session_id, str(subject))

    def _verdict(self, message: str, session_id: str, subject: Path, mode: str) -> GatingResult:
        """Apply the configured enforcement posture to a problem already found.

        ``message`` must already be rendered for the outcome this produces
        -- see :meth:`_is_blocking`, called by ``handle()`` before this.
        """
        if mode == _MODE_ADVISE:
            return GatingResult(decision=Decision.ALLOW, context=[message])

        if mode == _MODE_BLOCK:
            return GatingResult.deny(message)

        # block_once (the default): tell the reader once per repo per session.
        # Per REPO because each stale clone is its own surprise, and per SESSION
        # because the daemon is shared (Plan 00127) — a daemon-wide count would
        # let one session consume every other session's single warning, which is
        # the bug Plan 00277 fixed for lsp_enforcement.
        if self._already_reported(session_id, str(subject)):
            return GatingResult(decision=Decision.ALLOW, context=[message])

        self._record(session_id, str(subject))
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
            "fetch every governed repo and refresh the reading.\n\n"
            "**`COULD NOT BE CONFIRMED` is a third answer, and it never blocks.** A sweep ran "
            "and could not compare this clone against an upstream — the remote was unreachable, "
            "or there is none. The repo may be perfectly current; nothing confirmed it, and the "
            "commit counts you would otherwise see came off the refs already on disk. It is "
            "said once per repo per session as context, because there is no command that makes "
            "an unreachable remote reachable and a block you cannot clear is not a block."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        # The governed root, and a path under it that is NOT a checkout. Both
        # are the shapes that must stay allowed; the root is untracked, so in a
        # clean checkout neither exists, and both are allowed for that reason
        # too. That is the point — these assert a NON-verdict, which is exactly
        # what a false positive here destroys.
        root = "untracked/repos"
        probe = f"{root}/__freshness_probe__"
        return [
            AcceptanceTest(
                title="reference-repo freshness - reading an unverified governed clone",
                command="Read a file inside a governed reference clone with no cached reading",
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
                harness_cannot_produce=(
                    "The verdict needs a real git checkout under `reference_repos.roots`, and "
                    "that root is untracked — a clean checkout and CI have none. Naming a path "
                    "that merely LOOKS like one does not work, deliberately: the handler "
                    "resolves a subject only when a directory carrying a `.git` contains the "
                    "path, because inventing one denied `ls untracked/repos` with a remedy "
                    "nothing could ever satisfy. Fixture commands are bounded to "
                    "`untracked/acceptance/`, so the harness cannot build a checkout under a "
                    "governed root either. The deny path is covered end to end by "
                    "`tests/unit/handlers/pre_tool_use/test_reference_repo_freshness.py` "
                    "against a real cache on disk."
                ),
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="reference-repo freshness - git against a governed repo is never blocked",
                command=f"git -C {probe} pull --ff-only",
                description=(
                    "The near-miss that keeps the handler satisfiable: this command touches "
                    "exactly the repo a deny message would name, and is the very remedy that "
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
                    "session_id": "acceptance-freshness-git",
                },
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="reference-repo freshness - listing the governed root is never blocked",
                command=f"ls {root}",
                description=(
                    "The regression this handler actually shipped: the root is under a "
                    "governed root but is not a checkout, so nothing could ever cache a "
                    "reading for it — and it was denied with a `fix:` command incapable of "
                    "clearing the block. A freshness gate must judge CHECKOUTS, not "
                    "everything that shares a prefix with one."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Read-only listing; touches nothing",
                test_type=TestType.BLOCKING,
                hook_input={
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": f"ls {root}"},
                    "session_id": "acceptance-freshness-root",
                },
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="reference-repo freshness - naming a repo is not reading it",
                command=f"rm -rf {probe}",
                description=(
                    "A command that mentions a governed clone without reading a byte of it "
                    "must pass. Answering `rm -rf <repo>` with 'pull it first' is advice "
                    "about a different command than the one being run."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "The path is a probe that never exists, and rm -rf of a missing path is a no-op"
                ),
                test_type=TestType.BLOCKING,
                hook_input={
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": f"rm -rf {probe}"},
                    "session_id": "acceptance-freshness-mention",
                },
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
