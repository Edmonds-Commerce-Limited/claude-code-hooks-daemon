"""WorktreeFileCopyHandler - prevents copying files between worktrees and main repo."""

import re
import tempfile
from enum import Enum
from typing import Any, ClassVar

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.paths import ProjectPath
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler import WorkspaceScope
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_layout import main_repo_code_dirs
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.command_evasion import (
    RESERVED_WORD_PREFIX,
    strip_reserved_word_prefix,
)
from claude_code_hooks_daemon.utils.command_position import command_position_segments
from claude_code_hooks_daemon.utils.path_exclusion import resolve_project_root
from claude_code_hooks_daemon.utils.recursive_search import (
    FIND_EXEC_ACTIONS,
    FIND_EXEC_TERMINATORS,
    find_exec_end,
)
from claude_code_hooks_daemon.utils.shell_segmentation import (
    peel_command_wrappers,
    resolve_shell_word,
    shell_word_spans,
)

# Both worktree root prefixes — untracked/ is manually managed, .claude/ is Claude Code managed
_WORKTREE_PREFIXES = (ProjectPath.WORKTREES_DIR, ProjectPath.CLAUDE_WORKTREES_DIR)

# Regex alternation matching either worktree root (used in pattern strings below).
# Derived from _WORKTREE_PREFIXES (Plan 00288 Task 4.6/C8) rather than a second,
# independently hardcoded literal that could drift from it.
_WORKTREE_RE = "(?:" + "|".join(re.escape(prefix) for prefix in _WORKTREE_PREFIXES) + ")"

# The verbs that RELOCATE a file. Named rather than inlined so the
# `declared-invariant-pairs` Detector can read them and hold this list against
# `core.utils._WRITE_INDICATOR_RE`, the other place this repository enumerates
# the same idea. An alternation inlined at its only call site has no sibling to
# be checked against, and drifts from one silently.
#
# The declared relation is a SUPERSET, not equality: `rsync` matters to this
# handler and is not a plain write indicator, so it is absent from the sibling
# by design.
_RELOCATION_VERBS: tuple[str, ...] = ("cp", "mv", "rsync", "install", "dd")

# The verb must sit where a program NAME would: start of string, after a
# separator, after a `$(`, or after an opening QUOTE — optionally through
# `sudo` and a path prefix. A bare `\b(cp|mv|...)\b` search anywhere in the
# string cannot tell the coreutils `install`/`dd` this handler exists to
# catch from the same word used as another program's SUBCOMMAND, so
# `pip install -r requirements.txt` inside a worktree earned a TERMINAL deny
# announcing catastrophic data loss. In `pip install` the program is `pip`;
# `install` is an argument, and argument position is what this excludes.
#
# The opening quote counts so that a quoted body (`eval 'cp <wt> src/'`) the
# command-position view leaves as written is still read. A data command's
# quoted argument (`echo "cp <wt> src/"`, `grep 'mv <wt>' docs/`) never reaches
# this pattern: the view blanks it, and it is only a command when its output
# feeds an executor.
#
# The separator class includes the newline: a heredoc body runs each line as
# its own command, so `cp` starting a line is in command position even though
# nothing before it on that line is a separator character.
#
# Shell reserved words between the separator and the verb (`do cp`, `then mv`)
# leave the verb in command position, so they are skipped (Plan 00422 N25).
# So do leading `NAME=value` assignments and a shell invocation up to its `-c`
# (`sh -e -c`, `bash -n -c`, `bash -o pipefail -c`), whose body the
# command-position view splices in without its quotes.
_RELOCATION_VERB_RE = re.compile(
    r"""(?:^|[;&|\n"']|\$\()\s*"""
    + RESERVED_WORD_PREFIX
    + r"(?:[A-Za-z_]\w*=\S*\s+)*(?:sudo\s+)?(?:\S*/)?("
    + "|".join(_RELOCATION_VERBS)
    + r")\b",
    re.IGNORECASE,
)

_SHELL_NAMES = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
# Wrappers that run the command after them and are not in the shared
# `COMMAND_WRAPPERS` table, which `peel_command_wrappers` reads.
_EXTRA_WRAPPERS = frozenset({"time", "exec"})
_MAX_WRAP_DEPTH = 4


def _is_short_c_option(word: str | None) -> bool:
    """Whether a word is a short-option cluster carrying `-c` (`-c`, `-nc`, `-ec`)."""
    return word is not None and re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", word) is not None


def _words_before_unresolved(words: list[str | None]) -> list[str]:
    """The leading resolved words, ending at the first one the shared reader could not resolve."""
    resolved: list[str] = []
    for word in words:
        if word is None:
            break
        resolved.append(word)
    return resolved


def _effective_command(segment: str, depth: int = 0) -> str:
    """The text of the command a segment finally runs, read word by word.

    Skips `NAME=value` words, wrappers (`sudo`, `env`, `nice`, `command`, ...) with
    their options and a shell invocation up to its `-c`, whose body becomes the
    command (`sudo bash --login -c 'cp ...'`, `/bin/bash -n -c '...'`). The wrappers
    are the shared `peel_command_wrappers` table, so each one's own option grammar
    is honoured. A leading `(` or `{` opens a subshell or group and runs no command,
    so it is dropped. A word the shared readers cannot resolve ends the walk with
    the text as written.
    """
    segment = strip_reserved_word_prefix(segment).lstrip("({ \t")
    spans = shell_word_spans(segment)
    words = [resolve_shell_word(segment[a:b]) for a, b in spans]
    index = 0
    while index < len(words):
        word = words[index]
        if word is None:
            return segment[spans[index][0] :]
        name = word.rsplit("/", 1)[-1]
        _, peeled = peel_command_wrappers(_words_before_unresolved(words[index:]))
        if re.match(r"[A-Za-z_]\w*=", word):
            index += 1
        elif peeled:
            index += peeled
        elif name in _EXTRA_WRAPPERS:
            index += 1
            while index < len(words) and (words[index] or "").startswith("-"):
                index += 1
        elif name in _SHELL_NAMES and depth < _MAX_WRAP_DEPTH:
            body_at = next(
                (i + 1 for i in range(index + 1, len(words) - 1) if _is_short_c_option(words[i])),
                None,
            )
            if body_at is None:
                return segment[spans[index][0] :]
            # The command-position view splices a `-c` body in without its quotes, so
            # the body is the rest of the segment; a still-quoted body is one word.
            quoted = body_at == len(words) - 1 and words[body_at] is not None
            body = words[body_at] if quoted else segment[spans[body_at][0] :]
            return _effective_command(body or "", depth + 1)
        else:
            break
    return segment[spans[index][0] :] if index < len(spans) else segment


# --- Operand reading (Plan 00474 N385) -------------------------------------------
#
# The original patterns recognise a destination only when it is SPELLED as a
# main-repo code dir followed by `/`. A careless agent also copies into the
# checkout root (`cp -r <wt>/src .`), names the destination first
# (`cp -t src/ <wt>/x`), or has `find -exec` / `xargs` run the copy. These are
# read from the operands of the copy the segment finally runs.
#
# How the destination is decided:
#
# * An explicit destination (`src/`, `./src`, `/abs/root/src`, `-t src/`) is a
#   main-repo code dir when its first component is one; an absolute one is read
#   after the main checkout root it sits under (taken from the worktree paths in
#   the command, the cwd, or the project root), and under no known root it is
#   outside the project. This does not depend on the working directory, except
#   that a relative destination inside a worktree cwd is that worktree's.
# * When the cwd is inside a worktree, a relative SOURCE is a worktree path:
#   `cp src/x.py /root/src/` run from a worktree is the same copy as
#   `cp <wt>/src/x.py /root/src/`.
# * A bare `.` destination is the working directory, so it depends on the cwd,
#   which is tracked only from a LITERAL `cd`/`pushd` earlier in the same command
#   (and the hook's own `cwd` field for where the command starts). A literal path
#   inside a worktree is a worktree; a relative `cd` into a code dir is that code
#   dir; any other absolute path is the main checkout, except the process temp dir;
#   a `cd` the reader cannot resolve (`$VAR`, `$(...)`, `-`, no argument, `~`, a
#   relative path elsewhere) leaves the cwd UNKNOWN, and a bare `.` is then NOT
#   denied. The tradeoff is deliberate: a guess would deny `cd "$WT" && cp -r ... .`
#   as often as it caught `cd "$ROOT" && cp -r ... .`, and an explicit code-dir
#   destination is still denied whatever the cwd. A `cd` inside a subshell
#   (`(cd x; ...)`) is not tracked, since it ends with the subshell.
# * A bare `.` into the main checkout is denied only when the copy is a whole-tree
#   one (`-r`/`-a`, `mv`, a bare worktree root, `<wt>/.`) or the source is a
#   main-repo code path (`<wt>/src/x.py`). `cp <wt>/notes.txt .` is allowed.
# * `xargs` and `find -exec` take their source from another stage: a pipeline
#   stage just before `xargs`, or the `find` starting path, must name a worktree.

# The cwd the acceptance probes run their relative `src/` destination from. A
# probe sent with the suite's own checkout as cwd reads `src/` as a path inside
# whichever worktree the suite runs from, so its verdict would depend on where
# QA runs. The harnesses resolve `$MAIN_CHECKOUT_DIR` to the checkout holding
# the worktree (the checkout itself outside one). It must be a real checkout
# root rather than `/`: the playbook harness drives the whole chain, and
# `project_containment` denies `src/` read against `/` as outside the project.
_MAIN_CHECKOUT_CWD: dict[str, Any] = {HookInputField.CWD: "$MAIN_CHECKOUT_DIR"}

_COPY_VERBS = frozenset({"cp", "mv", "rsync", "install"})
_WORKTREE_PATH = re.compile(rf"(?:^|/)({_WORKTREE_RE}/)([^/]+)(?:/(.*))?$")
_SCRATCH_ROOT = tempfile.gettempdir()
_CD_VERBS = frozenset({"cd", "pushd"})
# Words here are resolved from the shell text but an unresolvable one keeps its
# backslash, so `\;` ends an action as well as the shared terminators.
_FIND_EXEC_END = FIND_EXEC_TERMINATORS | {"\\;"}
_FIND_PLACEHOLDER = "{}"
# Options whose NEXT word is a value, not an operand.
_VALUE_OPTIONS: dict[str, frozenset[str]] = {
    "cp": frozenset({"-S", "--suffix", "--backup-suffix", "-t", "--target-directory"}),
    "mv": frozenset({"-S", "--suffix", "-t", "--target-directory"}),
    "install": frozenset(
        {"-S", "--suffix", "-t", "--target-directory", "-m", "--mode", "-o", "-g"}
    ),
    "rsync": frozenset(
        {"-e", "--rsh", "--exclude", "--include", "--exclude-from", "--include-from"}
        | {"-f", "--filter", "--port", "--bwlimit", "--timeout", "--log-file", "--rsync-path"}
    ),
}
_TARGET_DIRECTORY_VERBS = frozenset({"cp", "mv", "install"})
_XARGS_VALUE_OPTIONS = frozenset({"-I", "-n", "-P", "-L", "-d", "-E", "-s", "-a"})
_CLOSERS = frozenset({")", "}"})


class _Cwd(Enum):
    """Where a bare `.` points, as far as a literal `cd` in the command says."""

    MAIN = "main"
    MAIN_CODE = "main-code-dir"
    WORKTREE = "worktree"
    UNKNOWN = "unknown"


def _worktree_path(word: str) -> tuple[str, str] | None:
    """`(branch, rest-of-path)` when `word` is a path inside a worktree, else None."""
    match = _WORKTREE_PATH.search(word)
    return None if match is None else (match.group(2), match.group(3) or "")


def _command_words(text: str) -> list[str]:
    """Words of the command `text` runs, quotes removed; an unresolvable word stays as written.

    Subshell and group punctuation around the command (`(cp a b)`, `{ cp a b; }`)
    is dropped.
    """
    text = _effective_command(text)
    words = [
        resolved if resolved is not None else text[a:b]
        for a, b in shell_word_spans(text)
        for resolved in [resolve_shell_word(text[a:b])]
    ]
    while words and words[-1] in _CLOSERS:
        words.pop()
    if words and words[-1].endswith(")") and not words[-1].endswith("$()"):
        words[-1] = words[-1].rstrip(")")
    return words


def _is_target_option(word: str) -> bool:
    """`-t`, or a short cluster ending in it (`-rt`)."""
    return re.fullmatch(r"-[A-Za-z]*t", word) is not None


def _split_copy_operands(verb: str, args: list[str]) -> tuple[list[str], str | None, bool]:
    """`(sources, destination, recursive)` of a `cp`/`mv`/`rsync`/`install` argument list.

    The destination is `-t DIR` / `--target-directory=DIR` when given, otherwise
    the last operand. Option values (`-S ~`, `rsync -e ssh`) are not operands.
    """
    value_options = _VALUE_OPTIONS[verb]
    operands: list[str] = []
    target: str | None = None
    recursive = verb == "mv"
    index = 0
    options_ended = False
    while index < len(args):
        word = args[index]
        index += 1
        if options_ended or not word.startswith("-") or word == "-":
            operands.append(word)
        elif word == "--":
            options_ended = True
        elif word.startswith("--target-directory="):
            target = word.partition("=")[2]
        elif verb in _TARGET_DIRECTORY_VERBS and _is_target_option(word):
            if index < len(args):
                target = args[index]
                index += 1
            recursive = recursive or bool(re.search(r"[rRa]", word))
        elif verb in _TARGET_DIRECTORY_VERBS and word.startswith("-t") and len(word) > 2:
            target = word[2:]
        elif word in value_options:
            if word in {"-t", "--target-directory"} and index < len(args):
                target = args[index]
            index += 1
        elif word in {"--recursive", "--archive"} or (
            not word.startswith("--") and re.search(r"[rRa]", word[1:])
        ):
            recursive = True
    if target is not None:
        return operands, target, recursive
    if len(operands) < 2:
        return operands, None, recursive
    return operands[:-1], operands[-1], recursive


def _copy_operands(
    words: list[str], pipe_names_worktree: bool
) -> tuple[list[str], str | None, bool, bool] | None:
    """`(sources, destination, recursive, fed)` of the copy `words` finally runs, or None.

    `fed` means the sources are not all on the command line: they come from a
    worktree path that another stage names (`find <wt> | xargs cp -t src/`, or
    `find <wt> -exec cp {} src/ \\;`).
    """
    if not words:
        return None
    _, start = peel_command_wrappers(words)
    words = words[start:]
    if not words:
        return None
    verb = words[0].rsplit("/", 1)[-1]
    if verb in _COPY_VERBS:
        sources, destination, recursive = _split_copy_operands(verb, words[1:])
        return sources, destination, recursive, False
    if verb == "xargs":
        return _xargs_operands(words[1:], pipe_names_worktree)
    if verb == "find":
        return _find_operands(words[1:])
    return None


def _xargs_operands(
    args: list[str], pipe_names_worktree: bool
) -> tuple[list[str], str | None, bool, bool] | None:
    """The copy an `xargs` runs, fed by the stage before it when that stage names a worktree."""
    index = 0
    while index < len(args) and args[index].startswith("-") and args[index] != "--":
        index += 2 if args[index] in _XARGS_VALUE_OPTIONS else 1
    inner = _copy_operands(args[index + 1 if args[index : index + 1] == ["--"] else index :], False)
    if inner is None:
        return None
    sources, destination, recursive, _ = inner
    return sources, destination, recursive, pipe_names_worktree


def _find_operands(args: list[str]) -> tuple[list[str], str | None, bool, bool] | None:
    """The first copy a `find -exec ... {} ;` runs, its `{}` standing for each starting path."""
    roots: list[str] = []
    for word in args:
        if word.startswith("-") or word in {"(", "!"}:
            break
        roots.append(word)
    worktree_roots = [root for root in roots if _worktree_path(root)]
    index = 0
    while index < len(args):
        if args[index] not in FIND_EXEC_ACTIONS:
            index += 1
            continue
        end = find_exec_end(args, index + 1, _FIND_EXEC_END)
        inner_words = args[index + 1 : end if end is not None else len(args)]
        inner = _copy_operands(
            [
                worktree_roots[0] if w == _FIND_PLACEHOLDER and worktree_roots else w
                for w in inner_words
            ],
            False,
        )
        if inner is not None:
            return inner
        index = end if end is not None else len(args)
    return None


def _next_cwd(
    words: list[str], cwd: tuple[_Cwd, str], code_dirs: tuple[str, ...]
) -> tuple[_Cwd, str]:
    """The working directory after a `cd`/`pushd` command; `cwd` itself for any other command.

    The second member is the directory's path while it is inside a worktree (what a
    relative source resolves against), else empty.
    """
    kind, path = cwd
    if not words or words[0].rsplit("/", 1)[-1] not in _CD_VERBS:
        return cwd
    operands = [word for word in words[1:] if word == "-" or not word.startswith("-")]
    if not operands:
        return _Cwd.UNKNOWN, ""
    target = operands[0]
    if target == "-" or any(char in target for char in "$`*?~"):
        return _Cwd.UNKNOWN, ""
    if _worktree_path(target) is not None:
        return _Cwd.WORKTREE, target
    if target.startswith("/"):
        scratch = target == _SCRATCH_ROOT or target.startswith(_SCRATCH_ROOT + "/")
        return (_Cwd.UNKNOWN if scratch else _Cwd.MAIN), ""
    parts = [part for part in target.split("/") if part not in {"", "."}]
    if not parts:
        return cwd
    if ".." in parts:
        return _Cwd.UNKNOWN, ""
    if kind is _Cwd.WORKTREE:
        return _Cwd.WORKTREE, path.rstrip("/") + "/" + "/".join(parts)
    if kind is _Cwd.MAIN and parts[0] in code_dirs:
        return _Cwd.MAIN_CODE, ""
    return _Cwd.UNKNOWN, ""


def _initial_cwd(hook_input: dict[str, Any]) -> tuple[_Cwd, str]:
    """The cwd the command starts in: a worktree when the hook says so, else the main checkout."""
    cwd = hook_input.get(HookInputField.CWD)
    if isinstance(cwd, str) and _worktree_path(cwd) is not None:
        return _Cwd.WORKTREE, cwd
    return _Cwd.MAIN, ""


def _is_whole_tree_or_code(source: str, code_dirs: tuple[str, ...]) -> bool:
    """Whether a worktree source is the whole tree or a path inside a main-repo code dir."""
    located = _worktree_path(source)
    if located is None:
        return False
    rest = located[1].strip("/")
    return rest in {"", "."} or rest.split("/")[0] in code_dirs


def _resolve_in_worktree(source: str, cwd_path: str) -> str:
    """A relative source made absolute against a worktree cwd, so it is seen as a worktree path.

    A source that is already absolute, uses `~`/`$`, is an option, or climbs with
    `..` is returned as written: its place is not known from the cwd alone.
    """
    if source.startswith(("/", "~", "$", "-")) or ".." in source.split("/"):
        return source
    rest = "/".join(part for part in source.split("/") if part not in {"", "."})
    return cwd_path.rstrip("/") + ("/" + rest if rest else "")


def _main_roots(paths: list[str]) -> list[str]:
    """The main checkouts that the absolute worktree paths in `paths` live under.

    `/workspace/.claude/worktrees/x/src` is a worktree of `/workspace`. The project
    root, when the daemon knows it, counts too (stripped to its checkout when the
    daemon itself runs inside a worktree).
    """
    candidates = list(paths)
    project_root = resolve_project_root()
    if project_root:
        candidates.append(project_root)
    roots: list[str] = []
    for path in candidates:
        match = _WORKTREE_PATH.search(path)
        root = path[: match.start(1)].rstrip("/") if match else path.rstrip("/")
        if path.startswith("/") and root and root not in roots:
            roots.append(root)
    return roots


def _bare_directory_is_main_code(
    cwd: _Cwd,
    code_dirs: tuple[str, ...],
    sources: list[str],
    recursive: bool,
    fed: bool,
) -> bool:
    """Whether a destination that is the cwd itself (`.`, `./`) is main-repo code."""
    if cwd is _Cwd.MAIN_CODE:
        return True
    if cwd is not _Cwd.MAIN:
        return False
    return recursive or fed or any(_is_whole_tree_or_code(s, code_dirs) for s in sources)


def _destination_is_main_code(
    destination: str,
    cwd: _Cwd,
    code_dirs: tuple[str, ...],
    sources: list[str],
    recursive: bool,
    fed: bool,
    roots: list[str],
) -> bool:
    """Whether the destination lands in the main checkout's code (see the block comment above).

    An absolute destination is read relative to the main checkout root it sits
    under, and only its FIRST component there counts, so `<root>/src/x` is code and
    `<root>/untracked/scratch/src` is not. One under no known root is outside the
    project and is not judged.
    """
    if _worktree_path(destination) is not None:
        return False
    if destination.startswith("/"):
        for root in roots:
            if destination == root or destination.startswith(root + "/"):
                rest = destination[len(root) :].strip("/")
                if rest in {"", "."}:
                    return _bare_directory_is_main_code(
                        _Cwd.MAIN, code_dirs, sources, recursive, fed
                    )
                return rest.split("/")[0] in code_dirs
        return False
    relative = destination
    while relative.startswith("./"):
        relative = relative[2:]
    if cwd is _Cwd.WORKTREE:
        return False
    if relative in {"", "."}:
        return _bare_directory_is_main_code(cwd, code_dirs, sources, recursive, fed)
    if cwd is _Cwd.MAIN_CODE:
        return not relative.startswith("..")
    return relative.split("/")[0] in code_dirs


class WorktreeFileCopyHandler(PreToolUseHandlerBase):
    """Prevent copying files between worktrees and main repo."""

    # PROJECT-scoped: the "main repo code dirs" alternation aggregates every
    # declared project's source/test/config dirs (see
    # CLAUDE/Code/WorkspaceResolution.md).
    workspace_scope: ClassVar[WorkspaceScope] = WorkspaceScope.PROJECT

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.WORKTREE_FILE_COPY,
            priority=Priority.WORKTREE_FILE_COPY,
            tags=[HandlerTag.SAFETY, HandlerTag.GIT, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )
        self._rule = Rule(
            rule_id=RuleID.WORKTREE_FILE_COPY,
            blocked="`cp`/`mv`/`rsync` from a worktree into the main repo's code dirs",
            why="Defeats worktree isolation, bypasses git tracking, and can "
            "nuke untracked work in the target directory",
            fix="cd into the worktree, commit, then git merge back",
            verbose=(
                "🔥 WHY THIS IS CATASTROPHIC:\n"
                "  1. Defeats entire purpose of worktrees (isolation)\n"
                "  2. Destroys branch isolation\n"
                "  3. Loses git history (bypasses git tracking)\n"
                "  4. Nukes untracked work in target directory\n"
                "  5. Creates merge conflicts\n\n"
                "✅ CORRECT WORKFLOW:\n"
                "  1. cd untracked/worktrees/your-branch\n"
                "  2. git add . && git commit -m 'feat: changes'\n"
                "  3. cd /workspace (main repo)\n"
                "  4. git merge your-branch\n\n"
                "📖 See CLAUDE/Worktree.md for complete guide."
            ),
        )
        self._formatter = RuleFormatter()

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's deny path."""
        return [self._rule]

    def _all_main_repo_code_dirs(self) -> tuple[str, ...]:
        """Union of "main repo code dirs" across every declared project.

        A Bash command's two paths can name any two declared projects (or
        none), so this must aggregate rather than resolve one owning
        project the way a per-file consumer (`tdd_enforcement`) does.
        Falls back to the single root `_project_layout` when no registry
        was injected -- a unit test exercising the handler directly, or a
        zero-config repository, where `iter_layouts()` yields only the root.
        """
        if self._project_registry is None:
            return main_repo_code_dirs(self._project_layout)
        seen: dict[str, None] = {}
        for _, layout in self._project_registry.iter_layouts():
            for name in main_repo_code_dirs(layout):
                seen.setdefault(name, None)
        return tuple(seen)

    def _is_same_worktree_operation(self, command: str) -> bool:
        """Return True if both paths in command refer to the same worktree branch."""
        for prefix in _WORKTREE_PREFIXES:
            if command.count(prefix) >= 2:
                escaped = re.escape(prefix)
                branches = re.findall(rf"{escaped}/([^/\s]+)", command)
                if len(branches) >= 2 and branches[0] == branches[1]:
                    return True
        return False

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if copying between worktree and main repo.

        Judges the command bash will RUN, not the raw string. A `git commit`
        message describing this handler -- naming a worktree path and a
        relocation verb -- is prose that git stores, and denying it reports a
        catastrophic data-loss scenario to someone writing a sentence.

        `command_position_segments` is this repository's answer to "what
        command is actually being run", shared with `destructive_git` and
        `git_stash`. It blanks a `-m`/`-F` message value, a quoted-delimiter
        heredoc body fed to a DATA SINK (not `bash <<'EOF'`, whose receiver
        runs the bytes) and the arguments of `echo`/`grep`, and splits what is
        left into command segments, which are judged one at a time.
        """
        command = get_bash_command(hook_input)
        if not command:
            return False
        # Each command segment is judged on its own tokens. The path patterns
        # run `.*` and would otherwise cross `&&`/`;` into the NEXT command,
        # and a segment that only prints a path (`grep`, `echo`) is blanked by
        # the command-position view unless its output feeds an executor.
        #
        # The segments are walked in order so that a literal `cd` before a copy
        # says where a bare `.` destination points, and so that an `xargs` knows
        # whether the stage feeding it named a worktree (see "Operand reading").
        cwd = _initial_cwd(hook_input)
        code_dirs = self._all_main_repo_code_dirs()
        previous_names_worktree = False  # a stage before an `xargs` that names a worktree
        for segment in command_position_segments(command):
            words = _command_words(segment)
            if words and words[0].rsplit("/", 1)[-1] in _CD_VERBS:
                # A `cd` inside a subshell ends with it, so it is not tracked.
                if not strip_reserved_word_prefix(segment).lstrip().startswith("("):
                    cwd = _next_cwd(words, cwd, code_dirs)
                continue
            verdict = self._operands_relocate(words, cwd, code_dirs, previous_names_worktree)
            # A copy whose operands were read is judged on them. The text patterns
            # judge what the operands cannot be read from (`dd of=`, an unparsed shape).
            if verdict if verdict is not None else self._segment_relocates(segment):
                return True
            previous_names_worktree = any(prefix in segment for prefix in _WORKTREE_PREFIXES)
        return False

    def _operands_relocate(
        self,
        words: list[str],
        cwd: tuple[_Cwd, str],
        code_dirs: tuple[str, ...],
        previous_names_worktree: bool,
    ) -> bool | None:
        """Whether the copy these words run takes a worktree path into main-repo code.

        None when the words are not a copy with a readable destination.
        """
        copy = _copy_operands(words, previous_names_worktree)
        if copy is None:
            return None
        sources, destination, recursive, fed = copy
        if destination is None:
            return None
        if cwd[0] is _Cwd.WORKTREE:
            sources = [_resolve_in_worktree(source, cwd[1]) for source in sources]
        worktree_sources = [source for source in sources if _worktree_path(source)]
        if not (worktree_sources or fed):
            return False
        into = _worktree_path(destination)
        if into is not None:
            # Within one worktree is fine; into ANOTHER worktree stays with the text patterns.
            same = any((_worktree_path(s) or ("",))[0] == into[0] for s in worktree_sources)
            return False if same else None
        roots = _main_roots([*worktree_sources, cwd[1]] if cwd[1] else worktree_sources)
        return _destination_is_main_code(
            destination, cwd[0], code_dirs, worktree_sources or sources, recursive, fed, roots
        )

    def _segment_relocates(self, command: str) -> bool:
        """Whether one command segment relocates a file from a worktree into main-repo code."""
        if not any(prefix in command for prefix in _WORKTREE_PREFIXES):
            return False

        # Check for forbidden operations
        # The verb is looked for in the segment as written and in the command
        # it finally runs (through wrappers and a shell `-c`).
        effective = _effective_command(command)
        if not (_RELOCATION_VERB_RE.search(command) or _RELOCATION_VERB_RE.search(effective)):
            return False
        command = effective if _RELOCATION_VERB_RE.search(effective) else command

        # Check patterns — the "main repo code dirs" alternation is built
        # from the ProjectLayout facade (Plan 00288 Task 4.3/C5) rather than
        # hardcoded, so a project declaring extra source/test/config dirs is
        # also protected. A Bash command can name ANY declared project's
        # code dirs (there is no single "owning file" here), so this
        # AGGREGATES across every declared project via `iter_layouts`
        # (Plan 00301 follow-up), never just the root `_project_layout`.
        code_dirs = "|".join(re.escape(d) for d in self._all_main_repo_code_dirs())
        patterns = [
            rf"{_WORKTREE_RE}/[^/\s]+/\S+\s+.*\b({code_dirs})/",
            rf"rsync.*{_WORKTREE_RE}.*\b({code_dirs})\b",
        ]

        for pattern in patterns:
            if re.search(pattern, command, re.IGNORECASE):
                if self._is_same_worktree_operation(command):
                    continue
                return True

        return False

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Block worktree file copying.

        Verbosity is decided per (transcript_path, rule_id) via the shared
        DisclosureTracker (Plan 00116, Decision G). The blocked command is
        invocation-specific evidence and is always appended, regardless of
        disclosure state.
        """
        command = get_bash_command(hook_input)

        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure
        rule_id = self._rule.rule_id

        if transcript_path and tracker.was_disclosed(transcript_path, rule_id):
            message = self._formatter.terse(self._rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, rule_id)
            message = self._formatter.verbose(self._rule)

        message += f"\n\nCommand: {command}"

        return GatingResult(decision=Decision.DENY, reason=message)

    def get_claude_md(self) -> str | None:
        return (
            "## worktree_file_copy — do not copy files between worktrees and the main repo\n\n"
            "`cp`, `mv`, and `rsync` operations that move files from a worktree directory "
            "(`untracked/worktrees/` or `.claude/worktrees/`) into the main repo "
            "(`src/`, `tests/`, `config/`) are blocked. A copy the other way, from the "
            "main repo into a worktree, is not.\n\n"
            "Worktrees are isolated branches. Cross-copying corrupts that isolation "
            "and can silently overwrite in-progress work.\n\n"
            "Each command is judged on its own: a `grep` or `echo` that only MENTIONS a "
            "worktree path, and a `ls <worktree>/src/ && cp README.md src/` whose copy "
            "does not read the worktree, are allowed. The target must be a main-repo "
            "code dir, so `mv <worktree>/notes.txt tmp.txt` is not blocked.\n\n"
            "A copy into the checkout root (`cp -r <worktree>/src .`, `rsync -a <worktree>/ ./`), "
            "`cp -t src/ <worktree>/...`, and a copy behind a wrapper, `xargs` or `find -exec` "
            "are blocked too. A bare `.` is the working directory: a literal `cd` earlier in "
            "the same command decides it, and a `cd` into a worktree makes `.` that worktree.\n\n"
            "**Allowed**: operations within the same worktree branch. "
            "**To merge changes**: use `git merge` or `git cherry-pick` instead."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for worktree file copy handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="cp from worktree to main repo",
                command=(
                    "bash -n -c 'cp untracked/worktrees/acceptance-probe-absent/src/file.py "
                    "src/acceptance-probe-absent.py'"
                ),
                dispatch_as_bash=True,
                extra_hook_input=_MAIN_CHECKOUT_CWD,
                description="Blocks copying files from worktree to main repo (breaks isolation)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"CATASTROPHIC",
                    r"worktree.*isolation",
                    r"git merge",
                ],
                safety_notes=(
                    "bash -n only parses, so nothing runs; the source worktree does not exist "
                    "either"
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="rsync from worktree to main repo",
                command=(
                    "bash -n -c 'rsync -a --dry-run "
                    "untracked/worktrees/acceptance-probe-absent/src/ src/'"
                ),
                dispatch_as_bash=True,
                extra_hook_input=_MAIN_CHECKOUT_CWD,
                description="Blocks rsync from worktree to main repo",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"from a worktree into the main repo",
                    r"git history",
                ],
                safety_notes=(
                    "bash -n only parses, so nothing runs; --dry-run and a nonexistent source "
                    "worktree back it up"
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
