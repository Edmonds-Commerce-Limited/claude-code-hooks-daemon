"""Flag a verifier whose result nothing consumes before a mutator runs.

A field report recorded an `ansible-lint` that exited 2, had its exit code
CAPTURED AND PRINTED, had its full diagnosis PRINTED — and was then followed by
`git add`, `git commit` and `git push` in the same Bash invocation. An
unloadable play sat on the default branch for one commit. The failure was not
that nobody ran the check; it is that **nothing consumed the check's result**.

**The separator in that incident was a NEWLINE, not a `;`.** The lint was on
line 1 and the commit on line 3. A handler scanning for `;` between commands
inspects line 1, finds its internal `;`s, and never connects them to the commit
two lines down — so the obvious implementation misses the very bug that
prompted it. `split_unquoted` already accepts a separator tuple and both
existing callers already include ``"\\n"``; this handler uses the same shared
scanner rather than growing a third private one.

**This is NOT `;` → `&&` enforcement, which was considered and REJECTED.** That
rule is simultaneously leaky (it misses this incident) and noisy: `grep -q p f;
echo done` exits 1 on a legitimate no-match, `cmd > f 2>&1; echo "exit=$?"`
exists precisely to observe a failure, and a diagnostic sweep wants every
section even when a probe fails. A handler that fired on those would be mostly
wrong, and a handler that is mostly wrong gets switched off — leaving the
project worse off than with no gate at all.

Precision therefore comes from the TAXONOMY, not from separator analysis. Every
false-positive shape above contains no mutator at all, so it cannot fire
however its segments are separated.

See ``CLAUDE/Plan/00268-*/DESIGN-verifier-mutator.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority, ToolName
from claude_code_hooks_daemon.core import AcceptanceTest, Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.command_evasion import (
    ENV_PREFIX,
    GIT_INVOCATION,
    compile_command_name_pattern,
    normalise_line_continuations,
)
from claude_code_hooks_daemon.utils.shell_segmentation import (
    split_unquoted,
    strip_quoted_heredoc_bodies,
)

_MODE_WARN: Final = "warn"
_MODE_BLOCK: Final = "block"

# Statements run UNCONDITIONALLY with respect to each other. A newline is a
# command terminator in shell exactly as `;` is -- see the module docstring.
_STATEMENT_SEPARATORS: Final[tuple[str, ...]] = (";", "\n")

# Within one statement, these separate the individual commands. Longest-first
# per split_unquoted's contract, so `||` is never read as two `|`.
_SPAN_SEPARATORS: Final[tuple[str, ...]] = ("||", "&&", "|")

# A statement whose head opens one of these consumes whatever came before it.
# This is what covers `rc=$?` followed by a branch, WITHOUT having to track the
# variable: if a conditional is present at all, the result reached a decision.
_CHAIN_BREAKING_HEADS: Final[tuple[str, ...]] = (
    "if",
    "elif",
    "case",
    "while",
    "until",
    "exit",
    "return",
)
_CHAIN_BREAKING_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"^\s*(?:{'|'.join(_CHAIN_BREAKING_HEADS)})\b"
)

# `set -e`, `set -euo pipefail`, `set -o errexit`. Any of these makes the WHOLE
# invocation gated, so the handler stands down entirely.
_ERREXIT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^\s*set\s+(?:-[a-zA-Z]*e[a-zA-Z]*\b|-o\s+errexit\b)"
)

# The flags that turn `ansible-playbook` from a machine-changing MUTATOR into a
# read-only VERIFIER. The same binary sits on both tables, separated by these.
_ANSIBLE_DRY_RUN_FLAGS: Final[tuple[str, ...]] = ("--syntax-check", "--check")


@dataclass(frozen=True)
class CommandSignature:
    """One entry in the verifier or mutator taxonomy.

    Attributes:
        name: A LITERAL command name, possibly several words (``go vet``).
            Never a regex -- a project can extend these tables from config, and
            a config entry must not be able to smuggle a pattern in.
        required_any_flags: At least ONE of these must appear in the command
            span. ANY rather than ALL because the flags that make a command
            read-only are alternatives, not a set: ``--syntax-check`` and
            ``--check`` each independently make ``ansible-playbook`` a verifier.
        forbidden_flags: If ANY of these appears, the signature does not match.
            Used for the mutator half of the same binary.
    """

    name: str
    required_any_flags: tuple[str, ...] = ()
    forbidden_flags: tuple[str, ...] = ()


# Verifiers: a non-zero exit means "do not proceed".
_VERIFIERS: Final[tuple[CommandSignature, ...]] = (
    CommandSignature("ansible-lint"),
    CommandSignature("ansible-playbook", required_any_flags=_ANSIBLE_DRY_RUN_FLAGS),
    CommandSignature("shellcheck"),
    CommandSignature("bash", required_any_flags=("-n",)),
    CommandSignature("pytest"),
    CommandSignature("ruff"),
    CommandSignature("mypy"),
    CommandSignature("golangci-lint"),
    CommandSignature("go vet"),
    CommandSignature("php", required_any_flags=("-l",)),
    CommandSignature("npm test"),
    CommandSignature("yamllint"),
    CommandSignature("hooks-daemon plan-qa"),
)

# Mutators: state-changing, outward-facing, or hard to reverse.
_MUTATORS: Final[tuple[CommandSignature, ...]] = (
    CommandSignature("git add"),
    CommandSignature("git commit"),
    CommandSignature("git push"),
    CommandSignature("git tag"),
    CommandSignature("gh pr create"),
    CommandSignature("gh issue create"),
    CommandSignature("gh pr merge"),
    CommandSignature("ansible-playbook", forbidden_flags=_ANSIBLE_DRY_RUN_FLAGS),
)

# Cheap pre-filter for `matches`: the first word of every mutator name. A Bash
# command containing none of these cannot possibly be a finding, which is most
# of them.
_MUTATOR_HEAD_WORDS: Final[frozenset[str]] = frozenset(
    signature.name.split()[0] for signature in _MUTATORS
)

_GIT: Final = "git"


def _compile_signature(name: str) -> re.Pattern[str]:
    """Anchor ``name`` at the start of a command span.

    ``git`` is special-cased because it accepts GLOBAL OPTIONS before its
    subcommand, and `git -C /path commit` reading "/path" as the subcommand is
    how a real guard in this codebase was walked past. Everything else goes
    through the shared helper.
    """
    words = name.split()
    if words[0] != _GIT or len(words) < 2:
        return compile_command_name_pattern(name)
    subcommand = r"\s+".join(re.escape(word) for word in words[1:])
    return re.compile(rf"^\s*{ENV_PREFIX}{GIT_INVOCATION}{subcommand}(?=\s|$)")


def _compile_table(
    signatures: tuple[CommandSignature, ...],
) -> tuple[tuple[CommandSignature, re.Pattern[str]], ...]:
    return tuple((signature, _compile_signature(signature.name)) for signature in signatures)


_COMPILED_VERIFIERS: Final = _compile_table(_VERIFIERS)
_COMPILED_MUTATORS: Final = _compile_table(_MUTATORS)


def _signature_matches(signature: CommandSignature, pattern: re.Pattern[str], span: str) -> bool:
    if pattern.search(span) is None:
        return False
    tokens = span.split()
    if signature.required_any_flags and not any(
        flag in tokens for flag in signature.required_any_flags
    ):
        return False
    return not any(flag in tokens for flag in signature.forbidden_flags)


def _first_match(
    table: tuple[tuple[CommandSignature, re.Pattern[str]], ...], span: str
) -> CommandSignature | None:
    for signature, pattern in table:
        if _signature_matches(signature, pattern, span):
            return signature
    return None


@dataclass(frozen=True)
class _Finding:
    """A verifier and the later mutator its result never gated."""

    verifier: str
    mutator: str


class VerificationResultGateHandler(PreToolUseHandlerBase):
    """Advise when a verifier's exit status is never consumed before a mutator.

    Configuration options (set via config YAML):
        mode: "warn" (default) or "block".
        extra_verifiers: list[str] - additional literal verifier command names.
        extra_mutators: list[str] - additional literal mutator command names.

    Both extension options are ADDITIVE only, deliberately. A project that
    could REPLACE the mutator table could silently empty it, and a gate nobody
    can tell is off is worse than one that is loud.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.VERIFICATION_RESULT_GATE,
            priority=Priority.VERIFICATION_RESULT_GATE,
            terminal=False,
            tags=[HandlerTag.VALIDATION, HandlerTag.QA_ENFORCEMENT, HandlerTag.NON_TERMINAL],
        )
        # Config options: set via setattr AFTER __init__.
        self._mode: str = _MODE_WARN
        self._extra_verifiers: Any = None
        self._extra_mutators: Any = None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Cheap pre-filter: a Bash command that could contain a mutator."""
        if hook_input.get("tool_name") != ToolName.BASH:
            return False
        command = get_bash_command(hook_input)
        if not command:
            return False
        return any(word in command for word in self._mutator_head_words())

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Report a verifier whose result nothing consumed before a mutator."""
        command = get_bash_command(hook_input)
        finding = self._find(command) if command else None
        if finding is None:
            return GatingResult(decision=Decision.ALLOW)

        if self._mode == _MODE_BLOCK:
            return GatingResult(decision=Decision.DENY, reason=self._message(finding))
        return GatingResult(
            decision=Decision.ALLOW,
            context=[
                f"`{finding.verifier}` can fail here and `{finding.mutator}` "
                "would still run — nothing consumes the result.",
            ],
            guidance=self._message(finding),
        )

    def _find(self, command: str) -> _Finding | None:
        """Locate a verifier followed by an ungated mutator, or None."""
        if not command:
            return None

        normalised = strip_quoted_heredoc_bodies(normalise_line_continuations(command))
        statements = [
            statement.strip()
            for statement in split_unquoted(normalised, _STATEMENT_SEPARATORS)
            if statement.strip()
        ]

        if any(_ERREXIT_PATTERN.match(statement) for statement in statements):
            return None

        verifiers = _COMPILED_VERIFIERS + _compile_table(self._extra("_extra_verifiers"))
        mutators = _COMPILED_MUTATORS + _compile_table(self._extra("_extra_mutators"))

        pending: str | None = None
        for statement in statements:
            if pending is not None:
                if _CHAIN_BREAKING_PATTERN.match(statement):
                    pending = None
                    continue
                mutator = self._classify(statement, mutators, verifiers)
                if mutator is not None:
                    return _Finding(verifier=pending, mutator=mutator)

            found = self._classify(statement, verifiers, ())
            if found is not None:
                pending = found

        return None

    @staticmethod
    def _classify(
        statement: str,
        table: tuple[tuple[CommandSignature, re.Pattern[str]], ...],
        beaten_by: tuple[tuple[CommandSignature, re.Pattern[str]], ...],
    ) -> str | None:
        """Name of the first ``table`` signature matching a span of ``statement``.

        ``beaten_by`` is consulted FIRST for each span. That ordering is what
        keeps `ansible-playbook --syntax-check` off the mutator table: the same
        binary appears on both, separated only by a flag, and the read-only
        reading must win.
        """
        for span in split_unquoted(statement, _SPAN_SEPARATORS):
            if _first_match(beaten_by, span) is not None:
                continue
            signature = _first_match(table, span)
            if signature is not None:
                return signature.name
        return None

    def _extra(self, attribute: str) -> tuple[CommandSignature, ...]:
        """Parse an additive config list, ignoring anything malformed.

        Options arrive by blind ``setattr`` from YAML, so the type is not
        trusted. A bad entry is skipped rather than raised on: this handler is
        advisory, and a typo in one project's config must not take the daemon
        down.
        """
        value = getattr(self, attribute, None)
        if not isinstance(value, list):
            return ()
        return tuple(
            CommandSignature(entry.strip())
            for entry in value
            if isinstance(entry, str) and entry.strip()
        )

    def _mutator_head_words(self) -> frozenset[str]:
        extra = self._extra("_extra_mutators")
        if not extra:
            return _MUTATOR_HEAD_WORDS
        return _MUTATOR_HEAD_WORDS | {signature.name.split()[0] for signature in extra}

    @staticmethod
    def _message(finding: _Finding) -> str:
        return (
            f"VERIFICATION RESULT NOT CONSUMED: `{finding.verifier}` → `{finding.mutator}`\n\n"
            f"`{finding.verifier}` can fail in this command and `{finding.mutator}` "
            "would still run. A check whose outcome nothing acts on is not a check.\n\n"
            "Note a NEWLINE separates commands exactly as `;` does — the two halves "
            "being on different lines does not gate anything.\n\n"
            "ANY of these consumes the result:\n"
            f"  {finding.verifier} … && {finding.mutator} …\n"
            f"  {finding.verifier} … || {{ echo 'failed'; exit 1; }}\n"
            f'  {finding.verifier} …; rc=$?; if [ "$rc" -ne 0 ]; then exit 1; fi\n'
            "  set -euo pipefail   # at the top of the invocation\n\n"
            "This is NOT a rule about `;` versus `&&`. Chaining every command is "
            "explicitly rejected — `grep -q` exits 1 on a legitimate no-match, and a "
            "diagnostic sweep wants every section. Only this specific pair is flagged."
        )

    def get_claude_md(self) -> str | None:
        return (
            "## verification_result_gate — a check's result must be consumed\n\n"
            "Flagged: a **verifier** (`ansible-lint`, `shellcheck`, `pytest`, `ruff`, "
            "`mypy`, `yamllint`, `go vet`, `bash -n`, `php -l`, `golangci-lint`, "
            "`npm test`, `ansible-playbook --syntax-check`) followed by a **mutator** "
            "(`git add`/`commit`/`push`/`tag`, `gh pr create`/`gh issue create`/"
            "`gh pr merge`, a real `ansible-playbook` run) in the SAME Bash "
            "invocation, with nothing consuming the verifier's exit status.\n\n"
            "**A NEWLINE separates commands exactly as `;` does.** Putting the lint on "
            "one line and the commit on the next gates nothing — that is precisely how "
            "an unloadable file reached a default branch: the lint failed, its exit "
            "code was printed, and the commit ran anyway.\n\n"
            '**Printing `$?` is not consuming it.** `echo "exit=$?"` reports the '
            "result; it does not act on it.\n\n"
            "**Any of these is accepted** — use whichever fits:\n\n"
            "- `verifier … && mutator …`\n"
            "- `verifier … || { echo failed; exit 1; }`\n"
            "- `verifier …; rc=$?` then an `if`/`case` that branches on it\n"
            "- `set -euo pipefail` at the top of the invocation\n\n"
            "**This is NOT a style rule about `;` versus `&&`.** Blanket chaining was "
            "considered and rejected: `grep -q p f; echo done` exits 1 on a legitimate "
            'no-match, `cmd > f 2>&1; echo "exit=$?"` exists to observe a failure, and '
            "a labelled diagnostic sweep wants every section even when a probe fails. "
            "None of those contains a mutator, so none of them fires here.\n\n"
            "Ships advisory (`mode: warn`). Set "
            "`handlers.pre_tool_use.verification_result_gate.options.mode: block` to "
            "deny instead; extend the tables additively with `extra_verifiers` / "
            "`extra_mutators`."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for the verification result gate.

        Both use a real verifier name with ``--help``, which runs nothing and
        changes nothing, paired with a ``git tag --list`` that is equally
        read-only. The handler judges the SHAPE of the invocation, so a safe
        pair exercises it exactly as a dangerous one would.
        """
        from claude_code_hooks_daemon.core import RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Verification result gate - newline-separated verifier then mutator",
                command="yamllint --version\ngit tag --list",
                description=(
                    "The motivating shape, with a newline as the separator. Advisory "
                    "by default: the command runs and the context names the pair."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"yamllint", r"git tag"],
                safety_notes="--version and --list are read-only; nothing is tagged.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Verification result gate - a gated pair is silent",
                command="yamllint --version && git tag --list",
                description="`&&` consumes the result, so nothing is reported.",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="--version and --list are read-only; nothing is tagged.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
