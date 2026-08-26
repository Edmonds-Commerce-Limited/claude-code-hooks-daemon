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

from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.path_exclusion import handler_excludes_path

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

    def _patterns(self) -> tuple[str, ...]:
        return sfm.resolve_protected_patterns(self._mode, self._protected_paths)

    def _consumers(self) -> tuple[sfm.ConsumerSpec, ...]:
        return sfm.merge_allowed_consumers(self._allowed_consumers)

    def _matched_pattern(self, hook_input: dict[str, Any]) -> str | None:
        """The protected glob this tool call trips, or ``None``.

        The single dispatch point shared by ``matches()`` and ``handle()`` so
        the two can never disagree about what was inspected.
        """
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})
        patterns = self._patterns()

        if tool_name == ToolName.BASH:
            command = str(tool_input.get(_FIELD_COMMAND, ""))
            mention = sfm.find_protected_mention(command, patterns)
            if mention is None:
                return None
            # The EFFECTIVE patterns are passed through (review finding 1):
            # the flag-position check re-tests bare consumer arguments, and
            # testing the shipped defaults there would blind it to every
            # project-configured pattern — all of them under mode: replace.
            if sfm.is_exempt_invocation(command, self._consumers(), patterns):
                return None
            return mention

        path_field = _PATH_FIELD_BY_TOOL.get(str(tool_name or ""))
        if path_field is None:
            return None
        path = str(tool_input.get(path_field, ""))
        for pattern in patterns:
            if sfm.path_is_protected(path, (pattern,)):
                return pattern

        if tool_name == ToolName.GREP and path:
            # Partial enforcement for directory-rooted content search
            # (review finding 2): a Grep rooted at an ancestor of a
            # protected file reads its content without naming it. Bounded
            # walk — a tree over the cap is NOT fully checked, which the
            # guidance names as a residual limit.
            return sfm.directory_contains_protected(path, patterns)

        if tool_name in (ToolName.WRITE, ToolName.EDIT):
            return self._script_content_mention(path, tool_input, patterns)
        return None

    def _script_content_mention(
        self, path: str, tool_input: dict[str, Any], patterns: tuple[str, ...]
    ) -> str | None:
        """Protected mention inside authored SCRIPT content (Task 4.3), or None.

        Closes the write-then-execute route: a script that references a
        protected path cannot be authored via Write/Edit. Only the ADDED text
        is checked on Edit — removing a reference is never blocked.

        ``exclude_paths`` (handler option + project-wide ``daemon.exclude_paths``)
        scopes THIS surface only: the guard's own source and tests legitimately
        name protected paths. A protected path itself is never excludable.
        """
        if not any(path.endswith(extension) for extension in _SCRIPT_EXTENSIONS):
            return None
        if handler_excludes_path(
            path,
            handler_patterns=self._exclude_paths,
            project_patterns=self._project_exclude_paths,
        ):
            return None
        content = str(tool_input.get(_FIELD_CONTENT, "") or tool_input.get(_FIELD_NEW_STRING, ""))
        return sfm.find_protected_mention(content, patterns)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return self._matched_pattern(hook_input) is not None

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        pattern = self._matched_pattern(hook_input)
        if pattern is None:
            return GatingResult(decision=Decision.ALLOW)
        return GatingResult(
            decision=Decision.DENY,
            reason=(
                "SECRET FILE PROTECTED: this tool call would put the contents of a "
                f"protected file into context (matched protected glob: `{pattern}`).\n\n"
                "The file's contents must NEVER be read into context by any route — "
                "not Read, not Bash, not an interpreter one-liner, not a copy.\n\n"
                "What you CAN do instead:\n"
                "- Presence/metadata: `bin/hooks-daemon secret-meta <path>` returns "
                "existence, bucketed size, mtime, permissions and a keyed digest — "
                "never content.\n"
                "- Trusted consumers keep working: pass the path in flag position, "
                "e.g. `ansible-playbook --vault-password-file <path> ...` "
                "(`ansible-vault view|decrypt` stay denied — they print secrets).\n\n"
                "There is NO escape hatch and no self-declared-intent override. "
                "Only a human may lift this, by editing "
                "`handlers.pre_tool_use.secret_file_guard` in `.claude/hooks-daemon.yaml`. "
                "Ask the user; do not hunt for another way to read the file."
            ),
        )

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
            "for existence tests instead of `test -f`/`ls`.\n\n"
            "**Trusted consumers keep working.** The path may appear in FLAG "
            "position for allowlisted consumers: `ansible-playbook`/`ansible`/"
            "`ansible-vault` with `--vault-password-file <path>` (extend via "
            "`options.allowed_consumers`). `ansible-vault view|decrypt` are "
            "DENIED — those subcommands exist to print decrypted secrets. Note "
            "the scope boundary: protecting the vault password FILE does not "
            "protect the vaulted PAYLOAD — a playbook `debug:` task can still "
            "print vaulted vars.\n\n"
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
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="secret_file_guard - blocks Read of a protected path",
                command=(
                    "Use the Read tool on a dummy fixture file named "
                    "`/tmp/fixture.vault-password` (create nothing — the deny "
                    "fires on the path alone)"
                ),
                description="Read of a path matching a protected glob is denied.",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"SECRET FILE PROTECTED", r"secret-meta"],
                safety_notes="Dummy path only — never a real secret; deny path, no read happens",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="secret_file_guard - blocks Bash cat of a protected path",
                command="cat /tmp/fixture.vault-password",
                description="Any Bash mention of a protected path is denied.",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"SECRET FILE PROTECTED", r"NO escape hatch"],
                safety_notes="Dummy path — the file need not exist; deny fires on the mention",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="secret_file_guard - blocks an interpreter one-liner",
                command="python3 -c \"print(open('/tmp/fixture.vault-password').read())\"",
                description="Deny-by-default catches interpreter one-liners uniformly.",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"SECRET FILE PROTECTED"],
                safety_notes="Dummy path — deny fires before anything runs",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="secret_file_guard - allows the secret-meta helper",
                command="bin/hooks-daemon secret-meta /tmp/fixture.vault-password",
                description=(
                    "The metadata helper is the sanctioned presence/metadata route "
                    "and must pass."
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
                expected_message_patterns=[r"SECRET FILE PROTECTED"],
                safety_notes=(
                    "Demonstrates the no-echo-exemption rule; the bare "
                    "`ansible-playbook --vault-password-file <path> ...` form is the "
                    "ALLOW case (requires ansible installed to run to completion)"
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
