"""Every lint command must be one the handler can actually run, as written.

`lint_on_edit` splits a command with `shlex` and runs it through
`subprocess.run` in **list form with no shell**. Nothing expands a redirect, a
pipe or a glob — those characters reach the tool as literal arguments.

That, plus a missing crate-type flag, is how two "valid code passes" acceptance
probes came to DENY on a GitHub runner while passing here (Plan 00250): the
machine that ran them had the real linters installed, and this machine has the
rustup shim and no `kotlinc`, so the wrong commands were never executed. Absent
tooling had been standing in for correct commands.

These are unit tests on the declared command strings precisely because they must
hold on a machine that has none of the tools.
"""

from __future__ import annotations

import shlex

import pytest

from claude_code_hooks_daemon.strategies.lint.kotlin_strategy import KotlinLintStrategy
from claude_code_hooks_daemon.strategies.lint.registry import LintStrategyRegistry
from claude_code_hooks_daemon.strategies.lint.rust_strategy import RustLintStrategy

#: Characters only a shell gives meaning to. `lint_on_edit` runs no shell, so
#: each of these would be handed to the tool as part of an argument.
_SHELL_METACHARACTERS = ("2>&1", ">", "<", "|", "&", ";", "$(", "`", "*")


def _all_declared_commands() -> list[tuple[str, str, str]]:
    """(language, which command, the command string) for every strategy."""
    commands = []
    for strategy in LintStrategyRegistry.create_default().strategies():
        commands.append((strategy.language_name, "default", strategy.default_lint_command))
        extended = strategy.extended_lint_command
        if extended is not None:
            commands.append((strategy.language_name, "extended", extended))
    return commands


class TestNoLintCommandNeedsAShell:
    """A shell metacharacter in a command run without a shell is a bug."""

    @pytest.mark.parametrize(
        ("language", "which", "command"),
        [pytest.param(*row, id=f"{row[0]}-{row[1]}") for row in _all_declared_commands()],
    )
    def test_the_command_carries_no_shell_metacharacter(
        self, language: str, which: str, command: str
    ) -> None:
        offenders = [char for char in _SHELL_METACHARACTERS if char in command]
        assert not offenders, (
            f"{language}'s {which} lint command contains {offenders}, but "
            f"lint_on_edit runs commands in list form with NO shell — so these "
            f"reach the tool as literal arguments rather than being "
            f"interpreted: {command!r}"
        )

    def test_the_guard_would_catch_a_redirect(self) -> None:
        """Vacuity: the check must fail on the shape it exists to reject."""
        offenders = [char for char in _SHELL_METACHARACTERS if char in "kotlinc {file} 2>&1"]
        assert offenders

    def test_there_are_commands_to_check(self) -> None:
        """Vacuity: an empty registry would pass every parametrised case."""
        assert len(_all_declared_commands()) >= 10


class TestRustLintsALibraryWithoutDemandingMain:
    """`clippy-driver {file}` compiles as a BINARY crate, so it needs `fn main`.

    A library file is the common case in Rust, and `pub fn hello() {}` — the
    project's own "valid code" probe — is rejected with E0601 by a real clippy.
    The default command already frames the file as a lib for exactly this
    reason; the extended one did not.
    """

    def test_the_extended_command_frames_the_file_as_a_library(self) -> None:
        extended = RustLintStrategy().extended_lint_command
        assert extended is not None
        assert "--crate-type lib" in extended, (
            "clippy-driver defaults to a binary crate, so without "
            "`--crate-type lib` every library-shaped .rs file fails with "
            "E0601 'main function not found' on any machine where the clippy "
            f"component is genuinely installed: {extended!r}"
        )

    def test_the_extended_command_writes_artefacts_away_from_the_users_file(
        self,
    ) -> None:
        """The same reason the default command carries `--out-dir`."""
        extended = RustLintStrategy().extended_lint_command
        assert extended is not None
        assert "--out-dir" in extended

    def test_both_commands_agree_on_the_crate_framing(self) -> None:
        """Two commands for one language must not disagree about what it is."""
        strategy = RustLintStrategy()
        extended = strategy.extended_lint_command
        assert extended is not None
        assert "--crate-type lib" in strategy.default_lint_command
        assert "--crate-type lib" in extended


class TestKotlinLintsTheFilesItClaims:
    """`kotlinc -script` accepts a `.kts` script; this strategy handles `.kt`."""

    def test_the_default_command_does_not_demand_a_script_file(self) -> None:
        strategy = KotlinLintStrategy()
        assert ".kts" not in strategy.extensions, "fixture premise: .kt only"
        tokens = shlex.split(strategy.default_lint_command)
        assert "-script" not in tokens, (
            "kotlinc -script expects a .kts script, but this strategy is "
            f"registered for {strategy.extensions} — so the command rejects "
            f"every file it is ever given: {strategy.default_lint_command!r}"
        )

    def test_the_default_command_still_invokes_kotlinc(self) -> None:
        """The fix must keep checking Kotlin, not stop checking it."""
        tokens = shlex.split(KotlinLintStrategy().default_lint_command)
        assert tokens[0] == "kotlinc"
        assert "{file}" in tokens

    def test_the_default_command_sends_class_files_somewhere_else(self) -> None:
        """Without `-d`, kotlinc writes `.class` files beside the user's source.

        Kotlin's compiler reference: `-d path` — "Place the generated class
        files into the specified location." The Rust strategy carries
        `--out-dir` for the same reason.
        """
        tokens = shlex.split(KotlinLintStrategy().default_lint_command)
        assert "-d" in tokens
        destination = tokens[tokens.index("-d") + 1]
        assert destination != "{file}"
        assert destination.startswith("/")
