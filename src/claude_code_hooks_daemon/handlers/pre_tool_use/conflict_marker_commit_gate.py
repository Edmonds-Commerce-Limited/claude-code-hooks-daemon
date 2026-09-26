"""Deny a commit whose added lines carry a merge-conflict marker (Plan 00466 N211).

Two merge-conflict closers reached ledger 00466's NIGGLES.md as seven-deep
blockquotes. An Edit on the conflicted file ran the markdown formatter, which
rewrote the opener as an escaped heading and the closer as a blockquote, and
from then on no check read either as a marker. The formatter now refuses a
conflicted file, but a marker can still reach the index by other routes: a
file never edited, a Bash write, an older formatter, or a file that is not
markdown at all.

So this gate reads what the commit would RECORD -- the index, the working
tree for ``git commit -a``, or the named paths for a pathspec commit -- and
denies it when an ADDED line carries a marker in either spelling. Only added
lines count: a marker already in history must not block an unrelated edit,
and removing one is never blocked.

Cost: one ``git diff --name-only`` and one ``git grep`` per recorded source,
whatever the commit's size, plus one ``git diff -U0`` per file that actually
holds a marker-shaped line. ``git grep`` does the search in C and returns
only candidate lines.
"""

from __future__ import annotations

import logging
import re
import shlex
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.command_evasion import (
    GIT_GLOBAL_OPTIONS_TAKING_SEPARATE_VALUE,
    normalise_line_continuations,
    strip_reserved_word_prefix,
)
from claude_code_hooks_daemon.utils.conflict_markers import (
    GIT_GREP_PREFILTER,
    ConflictMarker,
    find_conflict_markers,
)
from claude_code_hooks_daemon.utils.git_commit_parsing import (
    commits_working_tree,
    extract_commit_pathspecs,
)
from claude_code_hooks_daemon.utils.git_repo import GitRepo, run_git
from claude_code_hooks_daemon.utils.shell_segmentation import split_unquoted

logger = logging.getLogger(__name__)

# A newline separates commands exactly as `;` does, and `&&`/`||`/`|` each
# start a new command within a statement.
_SEGMENT_SEPARATORS: Final[tuple[str, ...]] = ("||", "&&", "|", ";", "\n")

_GIT: Final[str] = "git"
_COMMIT: Final[str] = "commit"
_ENV: Final[str] = "env"
_DASH_C: Final[str] = "-C"
_CONTINUE: Final[str] = "--continue"
# A dry run records nothing.
_DRY_RUN: Final[str] = "--dry-run"
_PATHSPEC_SEPARATOR: Final[str] = "--"
_INCLUDE_FLAGS: Final[frozenset[str]] = frozenset({"-i", "--include"})
# Each of these records the INDEX as a commit once a conflict is resolved.
_CONTINUING_SUBCOMMANDS: Final[frozenset[str]] = frozenset(
    {"merge", "cherry-pick", "revert", "rebase"}
)
_DIRECTORY_CHANGERS: Final[frozenset[str]] = frozenset({"cd", "pushd"})
_CD_TOKEN_COUNT: Final[int] = 2
_PREVIOUS_DIRECTORY: Final[str] = "-"
_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")

# `git diff` targets: the index against HEAD, or the working tree against it.
_INDEX_TARGET: Final[str] = "--cached"
_HEAD: Final[str] = "HEAD"
# Added, Copied, Modified. `--no-renames` turns a rename into delete + add,
# so a renamed file's lines count as added rather than vanishing from ACM.
_DIFF_FILTER: Final[str] = "--diff-filter=ACM"
_DIFF_FLAGS: Final[tuple[str, ...]] = ("--no-renames", "--no-ext-diff", "--no-textconv")
_GREP_FLAGS: Final[tuple[str, ...]] = ("-n", "-z", "-I", "--full-name", "--no-color", "-E")
_NUL: Final[str] = "\0"
_NEWLINE: Final[str] = "\n"
# `git grep` exits 1 when nothing matched: an answer, not a failure.
_GREP_NO_MATCH: Final[int] = 1
_HUNK_HEADER: Final[re.Pattern[str]] = re.compile(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@")

# A deny names at most this many markers; the rest are counted.
_MAX_LISTED: Final[int] = 25
_WITHHELD: Final[str] = "(text withheld: protected path)"

_RULE: Final[Rule] = Rule(
    rule_id=RuleID.CONFLICT_MARKER_COMMIT,
    blocked="a commit whose added lines carry a merge-conflict marker",
    why=(
        "A leftover marker becomes history, and one disguised by the markdown "
        "formatter reads as prose to every later check"
    ),
    fix="Resolve the conflict at each line listed below, re-stage, and commit again",
    verbose=(
        "git writes a conflict as an opener of seven `<`, an optional base of "
        "seven `|`, a separator of seven `=` and a closer of seven `>`, each at "
        "column 0. Running the markdown formatter over a conflicted file "
        "disguises two of them: the opener becomes an escaped heading and the "
        "closer a seven-deep blockquote (`>` seven times, space-separated). "
        "Both spellings are checked here.\n\n"
        "Only lines this commit ADDS count, so a marker already in history "
        "never blocks an unrelated edit, and deleting one is never blocked. A "
        "line of seven `=` counts only between an opener and a closer, so a "
        "setext heading underline is not a marker."
    ),
)


@dataclass(frozen=True)
class _Source:
    """One thing a commit records: the index, or the working tree (some paths)."""

    working_tree: bool
    pathspecs: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Commit:
    """A commit-recording command: which repository, and what it records."""

    directory: Path
    sources: tuple[_Source, ...]


@dataclass(frozen=True)
class _Finding:
    """A marker on an added line. ``withheld`` hides the text of a protected file."""

    path: str
    marker: ConflictMarker
    withheld: bool


class _UnreadableTree(Exception):
    """git could not answer, so this commit could not be checked."""


def _shell_tokens(segment: str) -> list[str]:
    """Shell tokens of one segment; an unbalanced quote falls back to whitespace."""
    try:
        return shlex.split(segment)
    except ValueError:
        return segment.split()


def _git_arguments(segment: str) -> list[str] | None:
    """The arguments after ``git`` when ``segment`` runs git, else None.

    ``git`` must be the COMMAND, past any reserved word, ``env`` and
    ``NAME=value`` assignments -- so ``echo git commit`` is not a commit.
    """
    tokens = _shell_tokens(strip_reserved_word_prefix(segment))
    index = 0
    while index < len(tokens) and (tokens[index] == _ENV or _ASSIGNMENT.fullmatch(tokens[index])):
        index += 1
    if index >= len(tokens):
        return None
    head = tokens[index]
    if head != _GIT and not head.endswith(f"/{_GIT}"):
        return None
    return tokens[index + 1 :]


def _commit_sources(subcommand: str, options: list[str]) -> tuple[_Source, ...] | None:
    """What a git subcommand records as a commit, or None when it records none."""
    if subcommand in _CONTINUING_SUBCOMMANDS:
        return (_Source(working_tree=False),) if _CONTINUE in options else None
    if subcommand != _COMMIT or _DRY_RUN in options:
        return None
    if commits_working_tree(options):
        return (_Source(working_tree=True),)
    pathspecs = tuple(extract_commit_pathspecs([_COMMIT, *options]))
    if not pathspecs:
        return (_Source(working_tree=False),)
    named = _Source(working_tree=True, pathspecs=pathspecs)
    if _PATHSPEC_SEPARATOR in options:
        options = options[: options.index(_PATHSPEC_SEPARATOR)]
    if _INCLUDE_FLAGS.intersection(options):
        return (_Source(working_tree=False), named)
    return (named,)


def _parse_commit(segment: str, cwd: Path) -> _Commit | None:
    """The commit ``segment`` records, resolving each ``git -C`` against ``cwd``."""
    arguments = _git_arguments(segment)
    if arguments is None:
        return None
    directory = cwd
    index = 0
    while index < len(arguments) and arguments[index].startswith("-"):
        option = arguments[index]
        if option in GIT_GLOBAL_OPTIONS_TAKING_SEPARATE_VALUE:
            if option == _DASH_C and index + 1 < len(arguments):
                directory = directory / arguments[index + 1]
            index += 2
        else:
            index += 1
    if index >= len(arguments):
        return None
    sources = _commit_sources(arguments[index], arguments[index + 1 :])
    if sources is None:
        return None
    return _Commit(directory=directory, sources=sources)


def _commits(command: str, cwd: Path) -> Iterator[_Commit]:
    """Every commit-recording git invocation in ``command``.

    A ``cd``/``pushd`` earlier in the command moves the directory the later
    segments run in, so ``cd repo && git commit`` is judged in ``repo``.
    """
    for segment in split_unquoted(normalise_line_continuations(command), _SEGMENT_SEPARATORS):
        cwd = _after_directory_change(segment, cwd)
        commit = _parse_commit(segment, cwd)
        if commit is not None:
            yield commit


def _after_directory_change(segment: str, cwd: Path) -> Path:
    """``cwd`` after ``segment`` when it is ``cd <dir>``/``pushd <dir>``, else ``cwd``.

    ``cd -`` names a directory this command never states, so it is left alone.
    """
    tokens = _shell_tokens(strip_reserved_word_prefix(segment))
    if len(tokens) != _CD_TOKEN_COUNT or tokens[0] not in _DIRECTORY_CHANGERS:
        return cwd
    if tokens[1] == _PREVIOUS_DIRECTORY:
        return cwd
    return cwd / Path(tokens[1]).expanduser()


def _git_or_raise(root: Path, *args: str) -> str:
    result = run_git(root, *args)
    if result.returncode != 0:
        raise _UnreadableTree(result.stderr.strip() or f"git {args[0]} exited {result.returncode}")
    return result.stdout


def _has_head(root: Path) -> bool:
    return run_git(root, "rev-parse", "--verify", "--quiet", _HEAD).returncode == 0


def _nul_separated(output: str) -> list[str]:
    return [entry for entry in output.split(_NUL) if entry]


def _recorded_paths(directory: Path, source: _Source, has_head: bool) -> set[str]:
    """The Added/Copied/Modified paths ``source`` puts in the commit.

    Asked from the command's own ``directory``, because a commit's pathspecs
    are relative to it. The answer is repository-relative either way.
    """
    pathspec_args = (_PATHSPEC_SEPARATOR, *source.pathspecs) if source.pathspecs else ()
    if source.working_tree and not has_head:
        # Nothing to diff against: every tracked path is new.
        output = _git_or_raise(directory, "ls-files", "-z", "--full-name", *pathspec_args)
        return set(_nul_separated(output))
    target = _HEAD if source.working_tree else _INDEX_TARGET
    output = _git_or_raise(
        directory, "diff", target, "--name-only", "-z", _DIFF_FILTER, *_DIFF_FLAGS, *pathspec_args
    )
    return set(_nul_separated(output))


def _candidate_lines(root: Path, source: _Source) -> dict[str, list[tuple[int, str]]]:
    """Marker-shaped lines by path, from the tree ``source`` records."""
    tree = () if source.working_tree else (_INDEX_TARGET,)
    result = run_git(root, "grep", *tree, *_GREP_FLAGS, "-e", GIT_GREP_PREFILTER)
    if result.returncode == _GREP_NO_MATCH:
        return {}
    if result.returncode != 0:
        raise _UnreadableTree(result.stderr.strip() or f"git grep exited {result.returncode}")
    return _parse_grep_stream(result.stdout)


def _parse_grep_stream(stream: str) -> dict[str, list[tuple[int, str]]]:
    """``git grep -n -z`` output as numbered lines by path.

    ``-z`` writes ``path NUL line-number NUL text NEWLINE``, and a path may
    itself hold a newline, so the stream is read field by field rather than
    split into lines. A truncated record ends the parse.
    """
    found: dict[str, list[tuple[int, str]]] = {}
    position = 0
    while position < len(stream):
        path_end = stream.find(_NUL, position)
        number_end = stream.find(_NUL, path_end + 1)
        text_end = stream.find(_NEWLINE, number_end + 1)
        if path_end < 0 or number_end < 0:
            break
        if text_end < 0:
            text_end = len(stream)
        path = stream[position:path_end]
        number = stream[path_end + 1 : number_end]
        if number.isdigit():
            found.setdefault(path, []).append((int(number), stream[number_end + 1 : text_end]))
        position = text_end + 1
    return found


def _added_line_numbers(root: Path, source: _Source, path: str, has_head: bool) -> set[int] | None:
    """Line numbers ``path`` gains in this commit; None means every line is new."""
    if source.working_tree and not has_head:
        return None
    target = _HEAD if source.working_tree else _INDEX_TARGET
    output = _git_or_raise(
        root,
        "--literal-pathspecs",
        "diff",
        target,
        "--unified=0",
        "--no-color",
        *_DIFF_FLAGS,
        _PATHSPEC_SEPARATOR,
        path,
    )
    added: set[int] = set()
    for line in output.splitlines():
        match = _HUNK_HEADER.match(line)
        if match is None:
            continue
        start = int(match.group(1))
        count = int(match.group(2)) if match.group(2) is not None else 1
        added.update(range(start, start + count))
    return added


def _findings(root: Path, directory: Path, source: _Source) -> list[_Finding]:
    """Markers on lines ``source`` adds, in path and line order."""
    has_head = _has_head(root)
    recorded = _recorded_paths(directory, source, has_head)
    if not recorded:
        return []
    protected_patterns = sfm.resolve_configured_patterns()
    findings: list[_Finding] = []
    for path, lines in sorted(_candidate_lines(root, source).items()):
        if path not in recorded:
            continue
        markers = find_conflict_markers(lines)
        if not markers:
            continue
        # A protected file is still checked -- skipping it would let a marker
        # through -- but its line text never reaches the deny (Plan 00272).
        withheld = sfm.path_is_protected(str(root / path), protected_patterns)
        added = _added_line_numbers(root, source, path, has_head)
        findings.extend(
            _Finding(path=path, marker=marker, withheld=withheld)
            for marker in markers
            if added is None or marker.line_number in added
        )
    return findings


def _findings_block(findings: list[_Finding]) -> str:
    rows: list[str] = []
    for finding in findings[:_MAX_LISTED]:
        marker = finding.marker
        spelling = "disguised by the markdown formatter" if marker.disguised else "raw"
        text = _WITHHELD if finding.withheld else marker.text
        rows.append(
            f"  {finding.path}:{marker.line_number}: {marker.kind} marker ({spelling}): {text}"
        )
    hidden = len(findings) - _MAX_LISTED
    if hidden > 0:
        rows.append(f"  ... and {hidden} more")
    return "\n".join(rows)


class ConflictMarkerCommitGateHandler(PreToolUseHandlerBase):
    """Deny a commit that would record a merge-conflict marker."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.CONFLICT_MARKER_COMMIT_GATE,
            priority=Priority.CONFLICT_MARKER_COMMIT_GATE,
            tags=[
                HandlerTag.GIT,
                HandlerTag.QA_ENFORCEMENT,
                HandlerTag.BLOCKING,
                HandlerTag.TERMINAL,
            ],
        )
        self._formatter = RuleFormatter()

    @staticmethod
    def _cwd(hook_input: dict[str, Any]) -> Path:
        cwd = hook_input.get(HookInputField.CWD)
        if isinstance(cwd, str) and cwd:
            return Path(cwd)
        return ProjectContext.project_root()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True for a command that records a commit; the tree decides the verdict."""
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.BASH:
            return False
        command = get_bash_command(hook_input)
        if not command:
            return False
        # The directory only matters to handle(); matching needs the shape.
        return next(_commits(command, Path()), None) is not None

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny when an added line of the recorded tree carries a marker."""
        command = get_bash_command(hook_input) or ""
        findings: list[_Finding] = []
        for commit in _commits(command, self._cwd(hook_input)):
            repo = GitRepo.resolve_for(commit.directory)
            if repo is None:
                continue
            try:
                for source in commit.sources:
                    findings.extend(_findings(repo.root, commit.directory, source))
            except _UnreadableTree as exc:
                logger.warning(
                    "conflict_marker_commit_gate: %s was NOT checked: %s", repo.root, exc
                )
                return GatingResult(
                    decision=Decision.ALLOW,
                    context=[
                        f"conflict-marker-commit-gate: git could not read what this commit "
                        f"records in {repo.root} ({exc}), so it was NOT checked for "
                        "merge-conflict markers."
                    ],
                )
        if not findings:
            return GatingResult(decision=Decision.ALLOW)
        return GatingResult(
            decision=Decision.DENY,
            reason=f"{self._teaching(hook_input)}\n\n{_findings_block(findings)}",
        )

    def _teaching(self, hook_input: dict[str, Any]) -> str:
        """Verbose the first time in a transcript, terse after (Plan 00116)."""
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure
        if transcript_path and tracker.was_disclosed(transcript_path, _RULE.rule_id):
            return self._formatter.terse(_RULE)
        if transcript_path:
            tracker.mark_disclosed(transcript_path, _RULE.rule_id)
        return self._formatter.verbose(_RULE)

    def get_rules(self) -> list[Rule]:
        """The Rule backing this handler's denial."""
        return [_RULE]

    def get_claude_md(self) -> str | None:
        return (
            "## conflict_marker_commit_gate — no merge-conflict marker reaches a commit\n\n"
            "A `git commit` (and `git merge|cherry-pick|revert|rebase --continue`) is "
            "denied when a line it ADDS carries a merge-conflict marker, naming each "
            "`file:line`. Both spellings count: git's raw column-0 markers, and the "
            "disguise the markdown formatter gives them — the opener as an escaped "
            "heading, the closer as a seven-deep blockquote (`>` seven times, "
            "space-separated). A line of seven `=` counts only between an opener and a "
            "closer, so a setext heading underline is fine.\n\n"
            "It reads what the commit RECORDS: the index, the working tree for "
            "`commit -a`, the named paths for a pathspec commit, in the repository an "
            "earlier `cd` or `git -C` names. A marker already in history never blocks an unrelated "
            "edit, and deleting one is never blocked. **Fix:** resolve the conflict at "
            "each listed line and re-stage."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Acceptance tests rendered into the release playbook."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="conflict-marker commit gate",
                command=(
                    "Stage a markdown file with a seven-deep blockquote closer line "
                    "added, then git commit"
                ),
                harness_cannot_produce=(
                    "The gate reads the REAL git index, so the precondition is a "
                    "staged file rather than anything the event carries, and the "
                    "harness's fixture allowlist has no `git add`. Staging into the "
                    "checkout under test would also mutate state the running session "
                    "shares. Covered by "
                    "tests/unit/handlers/pre_tool_use/test_conflict_marker_commit_gate.py."
                ),
                description=(
                    "The commit is denied, naming the file and line of the disguised " "closer"
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"R-CONFLICT-MARKER-COMMIT", r"disguised"],
                safety_notes="Nothing is written; the index is read only",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="conflict-marker commit gate - a dry-run commit of a clean tree",
                command="git commit --dry-run",
                dispatch_as_bash=True,
                description=(
                    "`--dry-run` records nothing, and a tree with no added marker "
                    "commits normally"
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="--dry-run never creates a commit or modifies the index.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
