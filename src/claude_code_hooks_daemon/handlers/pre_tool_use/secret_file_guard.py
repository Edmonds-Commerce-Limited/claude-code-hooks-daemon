"""SecretFileGuardHandler — deny-by-default read guard over protected files (Plan 00272).

Some files exist only to be consumed by tooling, never by an agent: Ansible
Vault password files, the daemon's own ``.claude/block-words.secret``, key
material. This handler keeps their CONTENTS out of context on every wired
route it can see:

- ``Read``/``Write``/``Edit``/``NotebookEdit``/``Grep`` on a protected path
  (Grep is a content ORACLE in every output mode — even ``-l`` answers
  "does this byte pattern occur", so all modes are denied).
- Any ``Bash`` command whose text mentions a protected path — the
  ``sed_blocker`` framing: deny-by-default, not a list of bad readers.
- Authorship of a SCRIPT that references a protected path (Task 4.3), so the
  write-then-execute route cannot be set up through ``Write``/``Edit``.

Two narrow exemptions: the ``secret-meta`` metadata helper (the sanctioned
presence/metadata route) and allowlisted consumers with the path strictly in
flag position (``ansible-playbook --vault-password-file ...``;
``ansible-vault view|decrypt`` are DENIED — they exist to print secrets).

**No escape hatch** (Plan 00259 doctrine, same as artifact_publish_blocker):
an agent that can type its own justification has self-authorised disclosure.
A HUMAN lifts protection by editing config.

Honest limits: this is DEFENCE IN DEPTH over an OS boundary (permissions,
ownership) the project must set independently — see the plan's
RESEARCH-read-routes.md for the class-(b)/(c)/(d) route classification.
"""

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, ClassVar, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler import WorkspaceScope
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.utils import encrypted_at_rest
from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.path_exclusion import (
    handler_excludes_path,
    resolve_project_root,
)

logger = logging.getLogger(__name__)

# One Rule per distinct deny ROUTE (Plan 00116, Decision B). The underlying
# deny message is the same shape for all three -- only the "what was
# inspected" framing differs -- so all three share one `why`/`fix` but are
# distinct rule_ids since they are conceptually different disclosure paths
# (a direct tool read, a Bash mention, and the write-then-execute route).
_WHY: Final[str] = (
    "The file's contents must NEVER be read into context by any route — "
    "not Read, not Bash, not an interpreter one-liner, not a copy"
)
_FIX: Final[str] = "Use `bin/hooks-daemon secret-meta <path>` for metadata, or ask the user"
_VERBOSE: Final[str] = (
    "What you CAN do instead:\n"
    "- Presence/metadata: `bin/hooks-daemon secret-meta <path>` returns "
    "existence, bucketed size, mtime, permissions and a keyed digest — "
    "never content.\n"
    "- Trusted consumers keep working: pass the path in flag position, "
    "e.g. `ansible-playbook --vault-password-file <path> ...` "
    "(`ansible-vault view|decrypt` stay denied — they print secrets).\n"
    "- A file ENCRYPTED at rest (a whole-file Ansible Vault payload, "
    "re-checked on every call) is not protected: Read/Grep/Edit it, and "
    "name it in ONE plain command such as `git add <path>` or "
    "`git commit -m '...' -- <path>` — no `&&`/`;`/`|`, no `$`, glob or "
    "`~`, and every protected path in the command encrypted. A command "
    "that could decrypt it (`ansible*`, `git diff|log|show`) stays denied. "
    "If this file was decrypted in place, re-encrypt it rather than "
    "working around the block.\n\n"
    "There is NO escape hatch and no self-declared-intent override. "
    "Only a human may lift this, by editing "
    "`handlers.pre_tool_use.secret_file_guard` in `.claude/hooks-daemon.yaml`. "
    "Ask the user; do not hunt for another way to read the file.\n\n"
    # The config file is the wrong place to send a reader (Plan 00356): a
    # project on the shipped defaults has no `protected_paths` key at all, so
    # the globs it is being asked about are not in there. `explain-handler`
    # prints the EFFECTIVE list, and needs no protected glob on the command
    # line -- repeating one of those in Bash is itself denied.
    "To see which globs are actually in force, run "
    "`bin/hooks-daemon explain-handler secret_file_guard` — it prints the "
    "effective list. Do NOT grep for the glob above: repeating it in a Bash "
    "command is itself a mention, and is denied."
)

# The route a raise during evaluation is filed under (Plan 00466 N11). Not in
# `_RULES_BY_ROUTE`'s three real routes -- its Rule needs its own `why`/`fix`,
# distinct from "a protected path was mentioned", and `handle()` renders it
# separately rather than looking it up there.
_ERROR_ROUTE: Final[str] = "error"

_RULES_BY_ROUTE: Final[dict[str, Rule]] = {
    "read": Rule(
        rule_id=RuleID.SECRET_READ,
        blocked="Read/Write/Edit/NotebookEdit/Grep targeting a protected path",
        why=_WHY,
        fix=_FIX,
        verbose=_VERBOSE,
    ),
    "bash": Rule(
        rule_id=RuleID.SECRET_BASH_MENTION,
        blocked="a Bash command whose text mentions a protected path",
        why=_WHY,
        fix=_FIX,
        verbose=_VERBOSE,
    ),
    "script": Rule(
        rule_id=RuleID.SECRET_SCRIPT_AUTHOR,
        blocked="a script authored via Write/Edit whose content references a protected path",
        why=_WHY,
        fix=_FIX,
        verbose=_VERBOSE,
    ),
}

# Plan 00466 N11 (major M4): a raise anywhere in evaluation is not a decision
# this guard made -- `core/chain.py`'s per-handler catch treats a propagated
# exception as "did not match" whenever the daemon's global `strict_mode` is
# the client default (`false`), fail-opening a SAFETY+BLOCKING guard. N5
# fixed the one raise path found live; this rule and the wrapper below make
# the whole CLASS structurally fail closed, independent of `strict_mode`.
_ERROR_RULE: Final[Rule] = Rule(
    rule_id=RuleID.SECRET_EVALUATION_ERROR,
    blocked="a call this guard could not finish evaluating",
    why=(
        "An exception during evaluation is not a decision the guard actually made "
        '-- treating it as "no match" would let a genuine protected-path mention '
        "through unexamined whenever the SAME defect crashed the scan"
    ),
    fix=(
        "This is a bug in the guard itself, not something to work around -- "
        "report it via the hooks-daemon skill (issue-report)"
    ),
    verbose=(
        "secret_file_guard could not finish evaluating this call and is denying "
        'it for safety rather than treating the crash as "no match" (Plan 00466 '
        "N11 -- this guard fails CLOSED on any internal error, independent of the "
        "daemon's global strict_mode). This is a bug in the guard itself: report "
        "it via the hooks-daemon skill (issue-report) rather than retrying -- "
        "retrying the same call will crash the same way."
    ),
)

# Routes whose deny message names the matched token (Plan 00356). Both scan a
# HAYSTACK the caller supplied -- a whole command line, a whole authored file
# -- so the offending word is not otherwise identifiable. The `read` route is
# excluded: its token is the caller's single path argument (nothing to
# locate), and a directory-rooted Grep reaches it carrying a protected
# filename the walk DISCOVERED rather than one the caller typed.
_TOKEN_ECHO_ROUTES: Final[frozenset[str]] = frozenset({"bash", "script"})

_FIELD_FILE_PATH: Final[str] = "file_path"
_FIELD_NOTEBOOK_PATH: Final[str] = "notebook_path"
_FIELD_PATH: Final[str] = "path"
_FIELD_COMMAND: Final[str] = "command"
_FIELD_CONTENT: Final[str] = "content"
_FIELD_NEW_STRING: Final[str] = "new_string"

# Tools whose single path argument is checked directly.
_PATH_FIELD_BY_TOOL: Final[dict[str, str]] = {
    ToolName.READ: _FIELD_FILE_PATH,
    ToolName.WRITE: _FIELD_FILE_PATH,
    ToolName.EDIT: _FIELD_FILE_PATH,
    ToolName.NOTEBOOK_EDIT: _FIELD_NOTEBOOK_PATH,
    ToolName.GREP: _FIELD_PATH,
}

# Task 4.3 content scan is scoped to SCRIPT-LIKE files: a script referencing a
# protected path is the write-then-execute route; markdown/prose legitimately
# NAMES protected files (this plan's own docs do) and must stay writable.
_SCRIPT_EXTENSIONS: Final[tuple[str, ...]] = (
    ".sh",
    ".bash",
    ".py",
    ".rb",
    ".pl",
    ".php",
    ".js",
    ".mjs",
    ".ts",
)

# n466-n24 review 4, review 5 MAJOR-2: the SUBSET of `_SCRIPT_EXTENSIONS`
# whose content IS shell text a shell will actually expand when the script
# runs (`bash deploy.sh`) -- these get `context="bash"` (the AGGRESSIVE
# glob-shaped heuristics), not `context="content"`. A `.py`/`.js`/`.rb` file
# is source in some OTHER language; nothing here glob-expands its text the
# way a shell would, so it stays scanned literal-only.
_SHELL_SCRIPT_EXTENSIONS: Final[tuple[str, ...]] = (".sh", ".bash")

# review 5 MAJOR-2 (further scoping): shell text also shows up with no
# `.sh`/`.bash` extension at all -- a Makefile recipe line, a CI workflow's
# `run:` step, an extensionless script a shebang alone identifies. Each of
# these routes gets `context="bash"` too, and -- for Makefile/CI YAML, which
# `_SCRIPT_EXTENSIONS` does not otherwise recognise as script-like -- also
# widens the initial "is this worth scanning at all" gate below. Scanning the
# WHOLE file rather than isolating just the recipe/`run:` lines is a
# deliberate simplification: this guard's failure mode is "scans a bit too
# much of a YAML/Makefile", never "misses a shell word in it".
_MAKEFILE_BASENAMES: Final[frozenset[str]] = frozenset({"Makefile", "makefile", "GNUmakefile"})
_MAKEFILE_EXTENSION: Final[str] = ".mk"
_CI_YAML_EXTENSIONS: Final[tuple[str, ...]] = (".yml", ".yaml")
_CI_YAML_BASENAMES: Final[frozenset[str]] = frozenset({".gitlab-ci.yml", ".gitlab-ci.yaml"})
_CI_YAML_DIR_MARKER: Final[str] = "/.github/workflows/"
_SHEBANG_SHELL_RE: Final[re.Pattern[str]] = re.compile(
    r"^#!\s*\S*/(?:env\s+)?(?:sh|bash|zsh|dash|ksh|ash)\b"
)


def _path_basename(path: str) -> str:
    """The final path component, independent of the caller's path separator style."""
    return path.rsplit("/", 1)[-1]


def _is_makefile_path(path: str) -> bool:
    basename = _path_basename(path)
    return basename in _MAKEFILE_BASENAMES or basename.endswith(_MAKEFILE_EXTENSION)


def _is_ci_yaml_path(path: str) -> bool:
    if not any(path.endswith(extension) for extension in _CI_YAML_EXTENSIONS):
        return False
    basename = _path_basename(path)
    if basename in _CI_YAML_BASENAMES:
        return True
    return _CI_YAML_DIR_MARKER in path or path.startswith(".github/workflows/")


def _has_shell_shebang(content: str) -> bool:
    """Does the content's first line name a shell interpreter?

    Identifies an extensionless shell script (`install`, `configure`,
    conventionally shebang-only, no `.sh`) that `_SCRIPT_EXTENSIONS` alone
    would never recognise as script-like at all.
    """
    first_line = content.splitlines()[0] if content else ""
    return bool(_SHEBANG_SHELL_RE.match(first_line.strip()))

# Plan 00459 acceptance probes: an encrypted vars file and its decrypted twin,
# at the vault-vars name the default `*vault_pass*` glob matches.
_PROBE_DIR: Final[str] = "untracked/acceptance/acceptance-test-secret-guard"
_PROBE_VAULT_RELPATH: Final[str] = "group_vars/all/vault_passwords.yml"
_PROBE_ENCRYPTED_DIR: Final[str] = f"{_PROBE_DIR}/encrypted/group_vars/all"
_PROBE_ENCRYPTED_FILE: Final[str] = f"{_PROBE_DIR}/encrypted/{_PROBE_VAULT_RELPATH}"
_PROBE_DECRYPTED_DIR: Final[str] = f"{_PROBE_DIR}/decrypted/group_vars/all"
_PROBE_DECRYPTED_FILE: Final[str] = f"{_PROBE_DIR}/decrypted/{_PROBE_VAULT_RELPATH}"

#: A structurally exact vault file as a `printf` argument (`\n` escapes).
#: Dummy salt/HMAC/ciphertext bytes, generated by `tests/vault_payloads.py`:
#: nothing is encrypted and no key exists.
_PROBE_VAULT_PRINTF: Final[str] = (
    "$ANSIBLE_VAULT;1.1;AES256\\n"
    "30303031303230333034303530363037303830393061306230633064306530663130313131323133\\n"
    "3134313531363137313831393161316231633164316531660a303030373065313531633233326133\\n"
    "31333833663436346435343562363236393730373737653835386339333961613161386166623662\\n"
    "6463346362643264390a303531323166326333393436353336303664376138373934613161656262\\n"
    "6338\\n"
)


@dataclass(frozen=True)
class _DispatchKey:
    """Identifies one dispatch by everything ``_evaluate`` reads (m2, Plan
    00466 review 2) -- NOT by where the call lives, the same discriminator
    ``sensitive_content``'s own one-shot bridge uses.
    """

    tool_name: str
    path: str
    command: str
    content: str
    cwd: str


class SecretFileGuardHandler(PreToolUseHandlerBase):
    """Deny any tool call that would put a protected file's contents into context.

    Configuration (``handlers.pre_tool_use.secret_file_guard.options``):
        protected_paths: gitignore-style globs (list). Combined with the
            shipped defaults per ``mode``.
        mode: ``additive`` (default — project globs merge onto the defaults)
            or ``replace`` (only the project list). An unknown mode behaves
            as ``additive`` (fail closed toward more protection).
        allowed_consumers: additive list of ``{command, path_flags,
            denied_subcommands}`` entries extending the shipped Ansible set.
    """

    # PROJECT-scoped: the exclusion check consults the OWNING project's
    # vendored set via `layout_for()` (Plan 00331 Task 1.3), and the REPO
    # contract forbids a repo-singular handler consuming per-project
    # resolution.
    workspace_scope: ClassVar[WorkspaceScope] = WorkspaceScope.PROJECT

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SECRET_FILE_GUARD,
            priority=Priority.SECRET_FILE_GUARD,
            terminal=True,
            tags=[
                HandlerTag.SAFETY,
                HandlerTag.BLOCKING,
                HandlerTag.TERMINAL,
                HandlerTag.FILE_OPS,
            ],
        )
        # Config options — injected by the registry via setattr; typed and
        # defaulted here so mypy sees real attributes, not dynamic ones.
        self._protected_paths: list[str] | None = None
        self._mode: str | None = None
        self._allowed_consumers: list[dict[str, Any]] | None = None
        self._exclude_paths: list[str] | None = None
        # m2 (Plan 00466 review 2): a one-shot bridge from matches() to
        # handle() for a SINGLE dispatch -- see _compute_and_cache_matched's
        # docstring for the bug this closes.
        self._cached_dispatch: tuple[_DispatchKey, tuple[str, str, str] | None] | None = None

    def _patterns(self) -> tuple[str, ...]:
        return sfm.resolve_protected_patterns(self._mode, self._protected_paths)

    def _consumers(self) -> tuple[sfm.ConsumerSpec, ...]:
        return sfm.merge_allowed_consumers(self._allowed_consumers)

    def _dispatch_key(self, hook_input: dict[str, Any]) -> _DispatchKey:
        tool_name = str(hook_input.get(HookInputField.TOOL_NAME, ""))
        tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})
        path_field = _PATH_FIELD_BY_TOOL.get(tool_name)
        path = str(tool_input.get(path_field, "")) if path_field else ""
        command = str(tool_input.get(_FIELD_COMMAND, ""))
        content = str(tool_input.get(_FIELD_CONTENT, "") or tool_input.get(_FIELD_NEW_STRING, ""))
        cwd = str(hook_input.get(HookInputField.CWD, ""))
        return _DispatchKey(
            tool_name=tool_name, path=path, command=command, content=content, cwd=cwd
        )

    def _compute_and_cache_matched(self, hook_input: dict[str, Any]) -> tuple[str, str, str] | None:
        """Evaluate ONCE and leave the result for this same dispatch's
        ``handle()`` (m2, Plan 00466 review 2).

        ``matches()`` and ``handle()`` used to call
        ``_matched_pattern_and_route`` independently, so a raise
        ``matches()`` correctly turned into a DENY (via ``_ERROR_ROUTE``)
        could be silently overwritten by a CLEAN re-evaluation inside
        ``handle()`` if the underlying fault was transient -- exactly the
        gap the fail-closed wrapper (N11) exists to close, reopened one
        layer up.

        M-2 (Plan 00466 review 3): ``_dispatch_key`` itself is NOT wrapped
        by ``_matched_pattern_and_route``'s try/except -- a malformed
        ``tool_input`` (``None``, a list, a bare string instead of a dict)
        makes its own ``.get()`` calls raise ``AttributeError``, one line
        below a ``matched`` that (via ``_evaluate``'s IDENTICAL raise,
        already caught) correctly reflects the fail-closed error route.
        Catching it here just means "do not cache" -- ``matched`` is
        already the right, safe answer.
        """
        matched = self._matched_pattern_and_route(hook_input)
        try:
            key = self._dispatch_key(hook_input)
        except Exception:
            logger.exception(
                "secret_file_guard: _dispatch_key raised; not caching " "(Plan 00466 review 3 M-2)"
            )
            self._cached_dispatch = None
            return matched
        self._cached_dispatch = (key, matched)
        return matched

    def _take_cached_matched(self, hook_input: dict[str, Any]) -> tuple[str, str, str] | None:
        """The result ``matches()`` computed for THIS call, else a fresh one.

        Reading the entry consumes it, so a later dispatch never inherits a
        stale verdict; the key check guards the case ``handle()`` is called
        without a prior ``matches()`` for the SAME input (defensive, not
        expected in the real chain).

        M-2 (Plan 00466 review 3): see ``_compute_and_cache_matched`` for
        why ``_dispatch_key`` must be called inside its own try/except here
        too -- a raise falls back to a fresh, still fail-closed,
        ``_matched_pattern_and_route`` call rather than escaping.
        """
        cached = self._cached_dispatch
        try:
            key = self._dispatch_key(hook_input)
        except Exception:
            logger.exception(
                "secret_file_guard: _dispatch_key raised; re-evaluating "
                "(Plan 00466 review 3 M-2)"
            )
            self._cached_dispatch = None
            return self._matched_pattern_and_route(hook_input)
        if cached is not None and cached[0] == key:
            self._cached_dispatch = None
            return cached[1]
        return self._matched_pattern_and_route(hook_input)

    def _matched_pattern_and_route(self, hook_input: dict[str, Any]) -> tuple[str, str, str] | None:
        """``(pattern, token, route)`` for this tool call, or ``None``.

        The single dispatch point shared by ``matches()`` and ``handle()`` so
        the two can never disagree about what was inspected. Wraps
        ``_evaluate`` so this method — and therefore ``matches()``/``handle()``
        — NEVER raises (Plan 00466 N11, major M4): an exception anywhere in
        evaluation is filed under ``_ERROR_ROUTE`` and denied, rather than
        propagating to ``core/chain.py``'s per-handler catch, which treats a
        propagated exception as "did not match" under the daemon's default
        (non-strict) ``strict_mode`` — fail-opening this SAFETY+BLOCKING guard
        for that call, including any genuine protected-path mention elsewhere
        in the same input. This guard fails closed structurally, independent
        of the global setting.
        """
        try:
            return self._evaluate(hook_input)
        except Exception as exc:
            # Deliberately broad: ANY exception during evaluation must deny,
            # never propagate (Plan 00466 N11) -- see the docstring above.
            # n1 (Plan 00466 review 2): only the exception TYPE goes into the
            # deny reason -- the full message (which could carry a filename
            # discovered by a directory walk, Plan 00356) is logged here and
            # never echoed back to the caller.
            logger.exception(
                "secret_file_guard: evaluation raised; denying for safety (Plan 00466 N11)"
            )
            return ("<internal-error>", type(exc).__name__, _ERROR_ROUTE)

    def _evaluate(self, hook_input: dict[str, Any]) -> tuple[str, str, str] | None:
        """The real evaluation ``_matched_pattern_and_route`` wraps.

        ``route`` is one of ``"read"`` (a direct Read/Write/Edit/NotebookEdit/
        Grep target, or a Grep rooted at a directory containing a protected
        file), ``"bash"`` (a Bash command mentioning a protected path) or
        ``"script"`` (a Write/Edit authoring a script whose content
        references one) — the three Decision B rule granularities (Plan
        00116).

        ``token`` is the specific span that matched, so the deny message can
        name it (Plan 00356). For the ``read`` routes it is the path argument
        itself; for ``bash``/``script`` it is the offending word out of a
        command or a whole file, which is the case that actually needed it.
        """
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})
        raw_cwd = hook_input.get(HookInputField.CWD)
        cwd = raw_cwd if isinstance(raw_cwd, str) else None
        patterns = self._patterns()

        if tool_name == ToolName.BASH:
            command = str(tool_input.get(_FIELD_COMMAND, ""))
            mention = sfm.find_protected_mention_detail(
                command,
                patterns,
                deadline=time.monotonic() + sfm.SCAN_DEADLINE_SECONDS,
                cwd=cwd,
            )
            if mention is None:
                return None
            # The EFFECTIVE patterns are passed through (review finding 1):
            # the flag-position check re-tests bare consumer arguments, and
            # testing the shipped defaults there would blind it to every
            # project-configured pattern — all of them under mode: replace.
            if sfm.is_exempt_invocation(command, self._consumers(), patterns):
                return None
            if sfm.is_encrypted_target_invocation(
                command, patterns, cwd=cwd, is_encrypted=self._is_encrypted
            ):
                return None
            return (mention[0], mention[1], "bash")

        path_field = _PATH_FIELD_BY_TOOL.get(str(tool_name or ""))
        if path_field is None:
            return None
        path = str(tool_input.get(path_field, ""))
        for pattern in patterns:
            if not sfm.path_is_protected(path, (pattern,)):
                continue
            # Ciphertext is not the secret (Plan 00459). Checked on EVERY
            # call, so a file decrypted in place is denied at the next one.
            absolute = sfm.resolve_against_cwd(path, cwd)
            if absolute is not None and self._is_encrypted(absolute):
                break
            return (pattern, path, "read")

        if tool_name == ToolName.GREP and path:
            # Partial enforcement for directory-rooted content search
            # (review finding 2): a Grep rooted at an ancestor of a
            # protected file reads its content without naming it. Bounded
            # walk — a tree over the cap is NOT fully checked, which the
            # guidance names as a residual limit.
            directory_mention = sfm.directory_contains_protected(
                path, patterns, is_exempt=self._is_encrypted
            )
            if directory_mention is None:
                return None
            return (directory_mention, path, "read")

        if tool_name in (ToolName.WRITE, ToolName.EDIT):
            script_mention = self._script_content_mention(path, tool_input, patterns, cwd)
            if script_mention is None:
                return None
            return (script_mention[0], script_mention[1], "script")
        return None

    def _is_encrypted(self, absolute_path: str) -> bool:
        """Is this path a whole-file vault payload right now? (Plan 00459)

        Fails closed (False) whenever the project root is unknown, so an
        uninitialised daemon keeps the pre-plan behaviour.
        """
        return encrypted_at_rest.is_encrypted_at_rest(absolute_path, resolve_project_root())

    def _script_content_mention(
        self,
        path: str,
        tool_input: dict[str, Any],
        patterns: tuple[str, ...],
        cwd: str | None,
    ) -> tuple[str, str] | None:
        """Protected mention inside authored SCRIPT content (Task 4.3), or None.

        Closes the write-then-execute route: a script that references a
        protected path cannot be authored via Write/Edit. Only the ADDED text
        is checked on Edit — removing a reference is never blocked.

        No encrypted-at-rest exemption here (Plan 00459): the script runs
        LATER, by a command that need not name the file, so nothing checks
        the file at the time of use -- and it may be decrypted by then.

        ``exclude_paths`` (handler option + project-wide ``daemon.exclude_paths``)
        scopes THIS surface only: the guard's own source and tests legitimately
        name protected paths. A protected path itself is never excludable.

        Scanned with ``context="content"`` for source in a non-shell language
        (n466-n24 review 4 addendum, false-positive fold-in b): authored
        source code is never shell text a shell will expand, so the
        AGGRESSIVE glob-shaped heuristics stay off -- only an exact/glob-
        pattern LITERAL match (a quoted path string, a script's own
        protected-name reference) still denies. See ``sfm.MentionContext``
        for the full rationale.

        Genuinely shell-executed content is the exception (review 5
        MAJOR-2): a ``.sh``/``.bash`` extension, a Makefile recipe, a CI
        workflow's ``run:`` step, or a shebang alone naming a shell on an
        otherwise extensionless script -- all of these are text a shell
        will actually expand when the file runs (`bash deploy.sh`, `make`,
        a CI job), so scanning them with the weaker ``"content"`` matcher
        would reopen the write-then-execute gap this whole surface exists to
        close. Scanned with ``context="bash"`` instead, matching the
        aggressive heuristics a real shell invocation gets. The Makefile/CI
        YAML routes scan the WHOLE file rather than isolating just the
        recipe/``run:`` lines -- see ``_MAKEFILE_BASENAMES`` above for why
        that simplification is the safe direction to err in.
        """
        content = str(tool_input.get(_FIELD_CONTENT, "") or tool_input.get(_FIELD_NEW_STRING, ""))
        is_extension_script = any(path.endswith(extension) for extension in _SCRIPT_EXTENSIONS)
        is_makefile = _is_makefile_path(path)
        is_ci_yaml = _is_ci_yaml_path(path)
        is_shebang_shell = _has_shell_shebang(content)
        if not (is_extension_script or is_makefile or is_ci_yaml or is_shebang_shell):
            return None
        if handler_excludes_path(
            path,
            handler_patterns=self._exclude_paths,
            project_patterns=self._project_exclude_paths,
            layout=self.layout_for(path),
        ):
            return None
        is_shell_extension = any(
            path.endswith(extension) for extension in _SHELL_SCRIPT_EXTENSIONS
        )
        context: sfm.MentionContext = (
            "bash"
            if (is_shell_extension or is_makefile or is_ci_yaml or is_shebang_shell)
            else "content"
        )
        return sfm.find_protected_mention_detail(
            content,
            patterns,
            deadline=time.monotonic() + sfm.SCAN_DEADLINE_SECONDS,
            cwd=cwd,
            context=context,
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return self._compute_and_cache_matched(hook_input) is not None

    def get_rules(self) -> list[Rule]:
        """Return the 4 Rule objects backing this handler's blocking behaviour."""
        return [*_RULES_BY_ROUTE.values(), _ERROR_RULE]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny with a verbose-first/terse-after explanation.

        Verbosity is decided per (transcript_path, rule_id) via the shared
        DisclosureTracker (Plan 00116, Decision G). The matched glob is
        appended on every fire — it changes per invocation, so it is not
        part of the static teaching content.

        The whole body after a real match is wrapped in its own fail-closed
        net (m1, Plan 00466 review 2): ``_matched_pattern_and_route`` only
        guarantees reaching a VERDICT, not that everything downstream of a
        real match (the disclosure tracker, ``RuleFormatter``, string
        building) can never raise -- and an exception escaping `handle()`
        unwrapped is exactly what a non-strict chain treats as "no match"
        for a call that had a genuine protected mention.
        """
        matched = self._take_cached_matched(hook_input)
        if matched is None:
            return GatingResult(decision=Decision.ALLOW)
        try:
            return self._build_deny_result(hook_input, matched)
        except Exception as exc:
            logger.exception(
                "secret_file_guard: handle() raised after a real match; "
                "denying for safety (Plan 00466 m1)"
            )
            # n1 (Plan 00466 review 2): only the exception TYPE goes into the
            # deny reason -- the message is logged above, never echoed back.
            return GatingResult(
                decision=Decision.DENY,
                reason=(
                    f"BLOCKED [{RuleID.SECRET_EVALUATION_ERROR}]: secret_file_guard matched a "
                    f"protected path but could not build its explanation: "
                    f"{type(exc).__name__}\n\nDenying for safety."
                ),
            )

    def _build_deny_result(
        self, hook_input: dict[str, Any], matched: tuple[str, str, str]
    ) -> GatingResult:
        """The real ``handle()`` body, run inside its caller's try/except."""
        pattern, token, route = matched
        if route == _ERROR_ROUTE:
            return self._deny_for_evaluation_error(hook_input, token)
        rule = _RULES_BY_ROUTE[route]

        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure
        formatter = RuleFormatter()

        if transcript_path and tracker.was_disclosed(transcript_path, rule.rule_id):
            message = formatter.terse(rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, rule.rule_id)
            message = formatter.verbose(rule)

        message += f"\n\nMatched protected glob: `{pattern}`"
        # Naming the TOKEN turns a bisection hunt into a read (Plan 00356):
        # the glob alone does not say which of a command's -- or a whole
        # file's -- many words tripped it.
        #
        # Scoped to the routes that SEARCH a haystack the caller supplied. On
        # the `read` route the path is the caller's single argument, already
        # in hand, so naming it teaches nothing -- and the directory-rooted
        # Grep case reaches that route having DISCOVERED a protected filename
        # by walking a tree, which the caller never typed and must not learn.
        if route in _TOKEN_ECHO_ROUTES and token and token != pattern:
            message += f"\nMatched on this token from your input: `{token}`"

        return GatingResult(decision=Decision.DENY, reason=message)

    def _deny_for_evaluation_error(self, hook_input: dict[str, Any], detail: str) -> GatingResult:
        """Deny for the ``_ERROR_ROUTE`` case (Plan 00466 N11): the guard
        raised rather than reaching a real verdict. Same verbose-first/
        terse-after disclosure ladder as the three real routes, keyed on
        ``_ERROR_RULE``'s own rule_id, plus the exception detail so the
        report that fixes the underlying bug does not need to reproduce it
        from scratch.
        """
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure
        formatter = RuleFormatter()

        if transcript_path and tracker.was_disclosed(transcript_path, _ERROR_RULE.rule_id):
            message = formatter.terse(_ERROR_RULE)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, _ERROR_RULE.rule_id)
            message = formatter.verbose(_ERROR_RULE)

        message += f"\n\nInternal error: {detail}"
        return GatingResult(decision=Decision.DENY, reason=message)

    def get_default_enabled(self) -> bool:
        return True

    def get_claude_md(self) -> str | None:
        return (
            "## secret_file_guard — protected files are never read into context\n\n"
            "Configured secret files (default globs: `*.secret*`, `.vault-pass*`, "
            "`*.vault-password`, `*vault_pass*`, `id_rsa`, `id_ed25519`; projects "
            "extend or replace via `handlers.pre_tool_use.secret_file_guard.options` "
            "— `protected_paths` plus `mode: additive|replace`) must never have "
            "their CONTENTS enter context. `Read`, `Write`, `Edit`, `NotebookEdit` "
            "and `Grep` on a protected path are DENIED, and so is ANY `Bash` "
            "command whose text mentions one — `cat`, `head`, interpreter "
            "one-liners, `cp`/`mv` relocation, command substitution, sourcing. "
            "**THE RULE IS DENY-BY-DEFAULT, NOT A LIST OF BAD READERS** — the "
            "`sed_blocker` framing. There is no echo exemption and no "
            "commit-message exemption.\n\n"
            "**Presence and metadata stay available** — that is the design, not a "
            "gap: `Glob` still finds the file, and "
            "`bin/hooks-daemon secret-meta <path>` returns existence, bucketed "
            "size, mtime, permissions and a keyed digest (never content). Use it "
            "for existence tests instead of `test -f`/`ls`. **Run it as its own "
            "standalone Bash command** — the exemption applies only to a SINGLE "
            "statement, so chaining anything after it with `;`/`&&` (even "
            "`echo done`) makes the whole compound command mention the path "
            "again and it is denied.\n\n"
            "**Trusted consumers keep working.** The path may appear in FLAG "
            "position for allowlisted consumers: `ansible-playbook`/`ansible`/"
            "`ansible-vault` with `--vault-password-file <path>` (extend via "
            "`options.allowed_consumers`). Run the consumer invocation as its "
            "own standalone statement too, for the same reason. `ansible-vault "
            "view|decrypt` are DENIED — those subcommands exist to print "
            "decrypted secrets. Note the scope boundary: protecting the vault "
            "password FILE does not protect the vaulted PAYLOAD — a playbook "
            "`debug:` task can still print vaulted vars.\n\n"
            "**A file encrypted at rest is not protected** — the glob picks by "
            "NAME, and an encrypted vars file whose name describes its contents "
            "(`group_vars/all/vault_passwords.yml`, a vaulted `*.secrets` "
            "template) is ciphertext, which committing is the whole point of "
            "Vault. When the file's content is a whole-file Ansible Vault "
            "payload (`$ANSIBLE_VAULT;1.1;AES256` or `;1.2;AES256;<label>`, then "
            "hex armour, verified over the whole file), `Read`/`Grep`/`Edit` "
            "are allowed, and so is naming it in ONE plain Bash command: "
            "`git add|commit|status|mv|rm|ls-files|check-ignore`, or `cat`, "
            "`head`, `tail`, `wc`, `ls`, `stat`, `file`, `cp`, `mv` — with no "
            "`&&`/`;`/`|`, no `$`/glob/`~`/backslash, every protected path it "
            "names encrypted, and each named as its own argument (a commit "
            "message naming it does not count). Everything else stays denied, "
            "including `ansible-vault view|decrypt`, any `ansible*` command "
            "and `git diff|log|show|blame`, because Ansible finds the vault "
            "password from its config without the command naming it. The "
            "check runs on EVERY call with no cache: after `ansible-vault "
            "decrypt` the same path is fully protected again. It fails "
            "closed — a file it cannot read, one over 4 MiB, a symlink out of "
            "the project, or YAML with only inline `!vault` values stays "
            "protected. Authoring a script that names an encrypted file stays "
            "denied: the script runs later, when the file may be plaintext.\n\n"
            "**Honest limits — this is defence in depth, not a sandbox.** "
            "Literal path mentions are reliably denied. Heuristics catch glob "
            "tokens (`cat .vault-p*`), `~`/`$HOME` spellings and symlink "
            "aliases; a `Grep` rooted at a DIRECTORY is checked by a bounded "
            "walk (capped, so a very large tree is not fully checked). NOT "
            "covered: a Bash recursive content search rooted at an ancestor "
            "directory (`grep -r`/`rg` over a tree containing the file), "
            "string-assembled paths, shell state carried across invocations, "
            "pre-existing hard links or copies made before the guard was "
            "enabled (realpath cannot see them), pre-existing scripts/binaries "
            "that open the file internally, and a look-alike consumer created "
            "in-session (the allowlist matches the command's BASENAME, so a "
            "local wrapper named `ansible` is indistinguishable from the real "
            "one). **An unblocked evasion is NOT permission** — the policy is "
            "that the contents never enter context, by any route. Only "
            "OS-level controls (chmod 600, separate user, encryption at rest) "
            "truly guarantee that; set them too.\n\n"
            "**`*.secret*` is intentionally broad** (a deliberate project "
            "decision): any Bash token merely CONTAINING `.secret` trips it, "
            "so a repo-wide grep for the string `.secret` can be denied. That "
            "is the accepted cost. To work around a false positive: ask the "
            "user, scope the search to exclude the protected file, or have a "
            "human narrow the config (`mode: replace` with a tighter list).\n\n"
            "**Authoring a script that references a protected path is also "
            "denied** (the write-then-execute route). Markdown/prose naming a "
            "protected file stays writable.\n\n"
            "**There is NO escape hatch** — no `MUST_..._BECAUSE`. An agent that "
            "can type its own justification has self-authorised disclosure. Only "
            "a HUMAN may lift protection, by editing the handler's config. Ask; "
            "do not work around the block."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.constants.tools import ToolName
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        # The default globs match on BASENAME, so the probe can sit in the
        # gitignored acceptance directory and still trip `*.vault-password`. No
        # file is created: the deny is decided from the path.
        protected_read_probe = ToolPayload(
            tool_name=ToolName.READ,
            tool_input={
                "file_path": (
                    "$CLAUDE_PROJECT_DIR/untracked/acceptance/"
                    "acceptance-test-secret-guard/fixture.vault-password"
                )
            },
        )

        return [
            AcceptanceTest(
                title="secret_file_guard - blocks Read of a protected path",
                command=protected_read_probe.as_instruction(),
                tool_payload=protected_read_probe,
                description="Read of a path matching a protected glob is denied.",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED \[R-SECRET-READ\]", r"secret-meta"],
                safety_notes="Dummy path only — never a real secret; deny path, no read happens",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="secret_file_guard - blocks Bash cat of a protected path",
                command="cat /tmp/fixture.vault-password",
                dispatch_as_bash=True,
                description="Any Bash mention of a protected path is denied.",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"BLOCKED \[R-SECRET-BASH-MENTION\]",
                    r"NO escape hatch",
                ],
                safety_notes="Dummy path — the file need not exist; deny fires on the mention",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="secret_file_guard - blocks an interpreter one-liner",
                command="python3 -c \"print(open('/tmp/fixture.vault-password').read())\"",
                dispatch_as_bash=True,
                description="Deny-by-default catches interpreter one-liners uniformly.",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED \[R-SECRET-BASH-MENTION\]"],
                safety_notes="Dummy path — deny fires before anything runs",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="secret_file_guard - allows the secret-meta helper",
                command="bin/hooks-daemon secret-meta /tmp/fixture.vault-password",
                dispatch_as_bash=True,
                description=(
                    "The metadata helper is the sanctioned presence/metadata route and must pass."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Reports metadata JSON only; never content",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="secret_file_guard - echo buys no exemption",
                command=(
                    "echo would-run: ansible-playbook --vault-password-file "
                    "/tmp/fixture.vault-password site.yml"
                ),
                dispatch_as_bash=True,
                description=(
                    "Unlike sed_blocker, wrapping a protected-path mention in "
                    "`echo` is NOT exempt — this command is DENIED (the head is "
                    "`echo`, not an allowlisted consumer, so flag position buys "
                    "nothing). The fixture basename must match a default glob "
                    "(`*.vault-password`) for the mention to register. (The bare "
                    "`ansible-playbook --vault-password-file <path> ...` form, "
                    "path in flag position, is the consumer-allowlist ALLOW "
                    "case; it needs ansible installed to run to completion.)"
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED \[R-SECRET-BASH-MENTION\]"],
                safety_notes=(
                    "Demonstrates the no-echo-exemption rule; the bare "
                    "`ansible-playbook --vault-password-file <path> ...` form is the "
                    "ALLOW case (requires ansible installed to run to completion)"
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="secret_file_guard - allows naming an encrypted vault file",
                command=f"cat {_PROBE_ENCRYPTED_FILE}",
                dispatch_as_bash=True,
                description=(
                    "A protected-glob match whose content is a whole-file Ansible "
                    "Vault payload is ciphertext, so a plain command naming it is "
                    "allowed (Plan 00459)."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                setup_commands=[
                    f"mkdir -p {_PROBE_ENCRYPTED_DIR}",
                    f"printf '{_PROBE_VAULT_PRINTF}' > {_PROBE_ENCRYPTED_FILE}",
                ],
                cleanup_commands=[f"rm -rf {_PROBE_DIR}/encrypted"],
                safety_notes=(
                    "Dummy vault payload: the right shape, but nothing is encrypted "
                    "and no key exists. The setup names a protected path, which the "
                    "guard itself denies through the Bash tool; the playbook harness "
                    "performs it as a direct file write, and a human runs it in a "
                    "terminal"
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="secret_file_guard - blocks the same vault file decrypted in place",
                command=f"cat {_PROBE_DECRYPTED_FILE}",
                dispatch_as_bash=True,
                description=(
                    "The decrypted twin of the encrypted probe: the same name, "
                    "plaintext content. The content check runs on every call, so it "
                    "is protected again (Plan 00459)."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED \[R-SECRET-BASH-MENTION\]"],
                setup_commands=[
                    f"mkdir -p {_PROBE_DECRYPTED_DIR}",
                    f"printf 'dummy_password: not-a-real-secret\\n' > {_PROBE_DECRYPTED_FILE}",
                ],
                cleanup_commands=[f"rm -rf {_PROBE_DIR}/decrypted"],
                safety_notes=(
                    "Dummy plaintext, never a real secret; the deny fires before "
                    "anything is read, and also fires when the setup was not run"
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
