"""Handler keeping listed paths read-only for agents (Plan 00499).

Some files are maintained outside the agent: an infrastructure-as-code run
places them, or a human edits them, and the agent only ever READS them. This
handler denies every route by which an agent could create, change, move onto or
delete such a file, and never denies reading one.

It is off by default and does nothing without the ``paths`` option, a list of
repository-relative globs. It covers the file tools (``Write``, ``Edit``,
``NotebookEdit``) and the Bash routes the shared write scan can name: a
redirect, ``tee``, a heredoc redirect, ``sed -i``, ``dd of=``, a copy, move,
install or link onto the path, and a deletion or truncation of it
(``rm``, ``unlink``, ``touch``, ``truncate``, ``: >``). It is a guard against an agent's mistake, not
against a human or a process running outside Claude Code.
"""

from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, ClassVar, Final

from claude_code_hooks_daemon.constants import HandlerTag, HookInputField
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import repository_root, scan_bash_write_targets

#: The tool-input field each file tool names its target in.
_FILE_TOOL_TARGET_KEYS: Final[dict[str, str]] = {
    ToolName.WRITE: "file_path",
    ToolName.EDIT: "file_path",
    ToolName.NOTEBOOK_EDIT: "notebook_path",
}

PATHS_OPTION: Final[str] = "paths"

_RECURSIVE: Final[str] = "**"
_WILDCARDS: Final[re.Pattern[str]] = re.compile(r"[*?\[]")
_EXPANSION_CHARS: Final[str] = "$`"

#: A command that builds a path from a substitution the scan reads as separate
#: words. Such a path is judged by its file name as well.
_SUBSTITUTION_RE: Final[re.Pattern[str]] = re.compile(r"\$\(|`")

#: `xargs` running a verb that changes the files it is handed.
_XARGS_MUTATION_RE: Final[re.Pattern[str]] = re.compile(
    r"\bxargs\b[^|;&]*?\b(?:rm|unlink|touch|truncate|mv|cp|ln|install|tee)\b"
)

_CD_WORD_RE: Final[re.Pattern[str]] = re.compile(r"\b(?:cd|pushd|popd)\b")
_CD_ARGUMENT_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:cd|pushd)\s+(?:-[LP]\s+)?(?:--\s+)?(\"[^\"]*\"|'[^']*'|[^\s;&|()]+)"
)
#: A `cd` argument the handler cannot follow to a directory.
_UNFOLLOWABLE_CD: Final[re.Pattern[str]] = re.compile(r"[$`*?~]|^-$")
#: Characters that make a name part of a longer one (`.env` inside `.envrc`).
_NAME_CHARACTER: Final[str] = r"[\w.-]"

_RULE: Final[Rule] = Rule(
    rule_id=RuleID.WRITE_PROTECTED_PATH,
    blocked="a write, move onto, deletion or truncation of a path the project keeps read-only",
    why="The file is maintained outside the agent (infrastructure-as-code or a human); an agent's change is overwritten or breaks that process",
    fix="Do not change it; ask the human for any change to the file",
    verbose=(
        "WHY BLOCKED:\n"
        "This project lists the path below as maintained OUTSIDE the agent: an\n"
        "infrastructure-as-code (IaC) run places it, or a human edits it. Agents may\n"
        "read it and must never create, change, overwrite, move onto, link over,\n"
        "truncate or delete it, by any tool or any shell command.\n\n"
        "DO INSTEAD:\n"
        "  Leave the file alone and ask the human for the change you need.\n"
        "  Reading it is always allowed."
    ),
)


def _segments(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


def _matches_in_full(path: Sequence[str], glob: Sequence[str]) -> bool:
    """Do the components of ``path`` match those of ``glob``? ``**`` spans directories."""
    if not glob:
        return not path
    head, rest = glob[0], glob[1:]
    if head == _RECURSIVE:
        return any(_matches_in_full(path[skip:], rest) for skip in range(len(path) + 1))
    return bool(path) and fnmatch.fnmatchcase(path[0], head) and _matches_in_full(path[1:], rest)


def _is_ancestor(path: Sequence[str], glob: Sequence[str]) -> bool:
    """Could ``path`` be a directory that holds a file ``glob`` names?

    Removing or moving such a directory removes the protected file with it.
    Below a recursive ``**`` no particular directory is singled out, so only
    the directories above it count.
    """
    if not path:
        return bool(glob)
    if not glob or glob[0] == _RECURSIVE:
        return False
    return fnmatch.fnmatchcase(path[0], glob[0]) and _is_ancestor(path[1:], glob[1:])


def _segment_could_match(token: str, listed: str) -> bool:
    """Could a path component written as ``token`` be one ``listed`` describes?

    Wildcards follow the shell: a wildcard component never matches a name that
    starts with a dot unless it starts with one itself.
    """
    token_wild = _WILDCARDS.search(token) is not None
    listed_wild = _WILDCARDS.search(listed) is not None
    if not token_wild and not listed_wild:
        return token == listed
    if token_wild and listed.startswith(".") and not token.startswith("."):
        return False
    if token_wild and not listed_wild:
        return fnmatch.fnmatchcase(listed, token)
    if listed_wild and not token_wild:
        return fnmatch.fnmatchcase(token, listed)
    return True


def _could_match(token: Sequence[str], listed: Sequence[str]) -> bool:
    """Could a shell wildcard path, as components, expand to a listed path or to a
    directory that holds one? ``token`` may stop early: that is a directory."""
    if not token:
        return True
    if not listed:
        return False
    if listed[0] == _RECURSIVE:
        return _could_match(token, listed[1:]) or _could_match(token[1:], listed)
    return _segment_could_match(token[0], listed[0]) and _could_match(token[1:], listed[1:])


def _names_segment(name: str, glob: str) -> bool:
    """Is ``name`` a whole component of ``glob``: its file name, or a directory above it?"""
    parts = [part for part in _segments(glob) if part != _RECURSIVE]
    return any(
        fnmatch.fnmatchcase(name, part)
        for position, part in enumerate(parts)
        if position == len(parts) - 1 or not _is_all_wildcard(part)
    )


def _is_all_wildcard(part: str) -> bool:
    return not part.strip("*?")


def _name_pattern(glob: str) -> re.Pattern[str] | None:
    """A pattern finding the literal part of ``glob``'s file name in free text,
    only as a whole name; ``None`` when the name has no literal part."""
    parts = _segments(glob)
    last = parts[-1] if parts else ""
    fragments = [fragment for fragment in _WILDCARDS.split(last) if fragment]
    if not fragments:
        return None
    fragment = max(fragments, key=len)
    start = last.find(fragment)
    before = f"(?<!{_NAME_CHARACTER})" if start == 0 else ""
    after = f"(?!{_NAME_CHARACTER})" if start + len(fragment) == len(last) else ""
    return re.compile(f"{before}{re.escape(fragment)}{after}")


def _option_problem(options: Mapping[str, Any]) -> str | None:
    """Why the ``paths`` option is unusable, or None."""
    if PATHS_OPTION not in options:
        return None
    value = options[PATHS_OPTION]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return f"{PATHS_OPTION} must be a list of repository-relative path globs"
    for item in value:
        if not item.strip():
            return f"{PATHS_OPTION} must not hold an empty path"
        if item.startswith("/") or ".." in _segments(item):
            return f"{PATHS_OPTION} entries are relative to the repository root: {item!r}"
    return None


class WriteProtectedPathsHandler(PreToolUseHandlerBase):
    """Deny any agent write to a configured path; reading is never denied.

    Opt-in: ships disabled, and without ``paths`` it matches nothing.
    """

    default_enabled = False

    #: Injected by the registry from the handler's options (``self._<key>``).
    _paths: list[str] | None = None

    _TOOLS: ClassVar[frozenset[str]] = frozenset({*_FILE_TOOL_TARGET_KEYS, ToolName.BASH})

    def __init__(self, project_root: Path | None = None) -> None:
        super().__init__(
            handler_id=HandlerID.WRITE_PROTECTED_PATHS,
            priority=Priority.WRITE_PROTECTED_PATHS,
            terminal=True,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )
        self._project_root = project_root
        self._last: tuple[str, str | None] | None = None

    def get_default_enabled(self) -> bool:
        """Off until a project lists the paths it keeps read-only."""
        return False

    @staticmethod
    def validate_options(options: Mapping[str, Any]) -> dict[str, str]:
        """Refuse a malformed ``paths`` value; the handler then protects nothing."""
        problem = _option_problem(options)
        return {PATHS_OPTION: problem} if problem is not None else {}

    # ------------------------------------------------------------------
    # Where is a path, relative to the project?
    # ------------------------------------------------------------------

    def _root(self) -> Path:
        return self._project_root or ProjectContext.project_root()

    def _roots(self, cwd: str) -> list[str]:
        """The project root and the repository root the call runs in (a worktree
        is a separate checkout of the same project), as written and resolved."""
        found = [str(self._root())]
        enclosing = repository_root(cwd)
        if enclosing is not None:
            found.append(enclosing)
        return list(dict.fromkeys([*found, *(os.path.realpath(root) for root in found)]))

    @staticmethod
    def _relative(path: str, roots: Sequence[str]) -> Iterator[list[str]]:
        """``path`` below each root it sits under, as components."""
        for form in dict.fromkeys((os.path.normpath(path), os.path.realpath(path))):
            for root in roots:
                if form == root or form.startswith(root.rstrip("/") + "/"):
                    yield _segments(form[len(root) :])

    def _globs(self) -> list[str]:
        # `validate_options` withholds a malformed value, so this is a list of strings.
        return [glob for glob in (self._paths or []) if glob.strip()]

    def _protecting(self, path: str, roots: Sequence[str]) -> str | None:
        """The glob keeping ``path`` (or a file inside it) read-only, else None."""
        globs = self._globs()
        for relative in self._relative(path, roots):
            for glob in globs:
                parts = _segments(glob)
                if _matches_in_full(relative, parts) or _is_ancestor(relative, parts):
                    return glob
        return None

    def _protecting_by_name(self, path: str) -> str | None:
        """The glob whose file name ``path`` carries, in whatever directory."""
        name = Path(path).name
        return next((glob for glob in self._globs() if _names_segment(name, glob)), None)

    def _token_naming(self, token: str, roots: Sequence[str], bases: Sequence[str]) -> str | None:
        """The glob an unresolved destination ``token`` visibly names, else None.

        Where the token writes is unknown, so it is judged by what it SAYS. A
        token built from an expansion (`$DIR/name`) has an unknown directory, so
        only its final component is judged, whole. A plain wildcard is expanded
        the way the shell would from each directory the command may be in: a
        `*` stays inside one component and never matches a leading dot.
        """
        if any(char in token for char in _EXPANSION_CHARS):
            final = token.rstrip("/").rsplit("/", 1)[-1]
            if not final or any(char in final for char in _EXPANSION_CHARS):
                return None
            return next((glob for glob in self._globs() if _names_segment(final, glob)), None)
        for base in bases:
            written = _segments(os.path.normpath(str(Path(base) / token)))
            for root in roots:
                for glob in self._globs():
                    if _could_match(written, [*_segments(root), *_segments(glob)]):
                        return glob
        return None

    def _text_naming(self, text: str) -> str | None:
        """The glob that command text we could not read visibly names, else None."""
        for glob in self._globs():
            pattern = _name_pattern(glob)
            if pattern is None or pattern.search(text):
                return glob
        return None

    @staticmethod
    def _bases(command: str, working: str) -> tuple[list[str], bool]:
        """The directories a command may run in, and whether it may run in others.

        Starts from the hook's working directory and follows each literal
        `cd`/`pushd` the command names. A directory change it cannot follow
        (`cd "$D"`, `cd -`, `popd`, a bare `cd`) or a path built by a
        substitution leaves relative paths untrustworthy, so those are also
        judged by file name.
        """
        bases = [working]
        followed = 0
        untrusted = _SUBSTITUTION_RE.search(command) is not None
        for raw in _CD_ARGUMENT_RE.findall(command):
            argument = raw.strip("\"'")
            if _UNFOLLOWABLE_CD.search(argument):
                untrusted = True
                continue
            followed += 1
            bases.append(os.path.normpath(str(Path(bases[-1]) / argument)))
        if len(_CD_WORD_RE.findall(command)) != followed:
            untrusted = True
        return bases, untrusted

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def _violation(self, hook_input: dict[str, Any]) -> str | None:
        """The glob this call breaks, or None when it leaves every listed path alone.

        ``matches`` and ``handle`` ask about the same call back to back, so the
        last answer is kept and the command is read once.
        """
        key = repr(
            (
                hook_input.get(HookInputField.TOOL_NAME),
                hook_input.get(HookInputField.TOOL_INPUT),
                hook_input.get(HookInputField.CWD),
            )
        )
        if self._last is not None and self._last[0] == key:
            return self._last[1]
        glob = self._judge(hook_input)
        self._last = (key, glob)
        return glob

    def _judge(self, hook_input: dict[str, Any]) -> str | None:
        if not self._globs():
            return None
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        cwd = hook_input.get(HookInputField.CWD)
        working = cwd if isinstance(cwd, str) and cwd else str(self._root())
        roots = self._roots(working)

        key = _FILE_TOOL_TARGET_KEYS.get(str(tool_name))
        if key is not None:
            named = hook_input.get(HookInputField.TOOL_INPUT, {}).get(key)
            if not isinstance(named, str) or not named:
                return None
            return self._protecting(str(Path(working) / named), roots)
        if tool_name != ToolName.BASH:
            return None
        return self._bash_violation({**hook_input, HookInputField.CWD: working}, roots, working)

    def _bash_violation(
        self, hook_input: dict[str, Any], roots: Sequence[str], working: str
    ) -> str | None:
        """The glob a shell command breaks, judged from every directory it may run in."""
        command = hook_input[HookInputField.TOOL_INPUT].get("command", "")
        bases, untrusted = self._bases(command if isinstance(command, str) else "", working)
        unresolved: list[str] = []
        unreadable: str | None = None
        for base in bases:
            scan = scan_bash_write_targets(
                {**hook_input, HookInputField.CWD: base}, include_mutations=True
            )
            for path in scan.paths:
                glob = self._protecting(path, roots)
                if glob is None and untrusted:
                    glob = self._protecting_by_name(path)
                if glob is not None:
                    return glob
            unresolved.extend(token for token in scan.unresolved if token not in unresolved)
            unreadable = unreadable if unreadable is not None else scan.unreadable
        # `xargs rm` takes its operands from the pipe, so none are visible to
        # the scan: the command text is what can name the file.
        if _XARGS_MUTATION_RE.search(command if isinstance(command, str) else ""):
            glob = self._text_naming(command)
            if glob is not None:
                return glob
        # What the scan could not place is unknown, not nothing: it is denied
        # only when it visibly names a listed path.
        for token in unresolved:
            glob = self._token_naming(token, roots, bases)
            if glob is not None:
                return glob
        return self._text_naming(unreadable) if unreadable is not None else None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True when the call would change a listed path."""
        if hook_input.get(HookInputField.TOOL_NAME) not in self._TOOLS:
            return False
        return self._violation(hook_input) is not None

    def get_rules(self) -> list[Rule]:
        """The Rule backing this handler's denial."""
        return [_RULE]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny, saying the file is maintained outside the agent."""
        glob = self._violation(hook_input)
        if glob is None:
            return GatingResult(decision=Decision.ALLOW)
        return GatingResult.deny(f"{RuleFormatter().verbose(_RULE)}\n\nPROTECTED PATH: {glob}")

    # ------------------------------------------------------------------
    # Guidance and acceptance
    # ------------------------------------------------------------------

    def get_claude_md(self) -> str | None:
        """Resident guidance: what is protected and who to ask."""
        return (
            "## write_protected_paths — files maintained outside the agent are read-only\n\n"
            "Paths listed under `handlers.pre_tool_use.write_protected_paths.options.paths` "
            "are maintained by infrastructure-as-code or by a human. You may read them. "
            "`Write`, `Edit` and `NotebookEdit` on one are denied, and so is a Bash command "
            "that redirects into it, `tee`s, `dd`s or `sed -i`s it, copies, moves, "
            "installs or links (`ln`) onto it, or `touch`es, `truncate`s, `rm`s or `unlink`s it "
            "(or removes or moves a directory holding it, as `rm -rf` and `mv` do). A "
            "wildcard is denied when the shell could expand it to the file.\n\n"
            "**Known gaps, still not for you to use**: `perl -i`, `rsync`, `find -delete`, "
            "`python -c`/`open()` and any other interpreter reach the file without being "
            "seen. The rule is the same whether or not the guard sees the route.\n\n"
            "**When it is denied, do not look for another route to the same file.** Ask the "
            "human for the change you need; the file is theirs (or the IaC's) to place."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """A near-miss that must allow, and the deny declared as undrivable."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="write protected paths - echo that only names a file",
                command='echo "ccy.env.local is maintained by IaC"',
                dispatch_as_bash=True,
                description=(
                    "Mentioning a file name in text is not writing it: nothing is "
                    "redirected, copied, moved or deleted."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses echo - safe to execute; touches no file.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="write protected paths - write to a listed path",
                command="Write, or run `echo x > <a listed path>` / `rm <a listed path>`",
                description=(
                    "Denied with the message that the file is maintained outside the "
                    "agent (IaC or a human) and the human is the one to ask."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"IaC", r"human", r"PROTECTED PATH"],
                safety_notes=(
                    "A probe that fires only if the handler is loaded would WRITE the "
                    "real protected file when it is not. Never probe it live."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                harness_cannot_produce=(
                    "The protected paths are the project's own configuration, and a probe "
                    "against one would create or destroy the real file if the handler were "
                    "not loaded. Covered by "
                    "tests/unit/handlers/pre_tool_use/test_write_protected_paths.py over "
                    "temporary files."
                ),
            ),
        ]
