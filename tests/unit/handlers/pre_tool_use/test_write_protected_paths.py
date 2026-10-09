"""The write_protected_paths handler (Plan 00499).

A project lists repository-relative globs that agents may READ and never
create, change, move onto or delete. Every test builds the real handler over a
temporary project and a temporary file: nothing here names, creates or touches
a real protected file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.write_protected_paths import (
    WriteProtectedPathsHandler,
)
from claude_code_hooks_daemon.handlers.registry import apply_handler_options

PROTECTED = ".claude/ccy/ccy.env.local"


def _make(root: Path, paths: list[str] | None = None) -> WriteProtectedPathsHandler:
    handler = WriteProtectedPathsHandler(project_root=root)
    apply_handler_options(handler, {"paths": [PROTECTED] if paths is None else paths})
    return handler


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / ".claude" / "ccy").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def handler(root: Path) -> WriteProtectedPathsHandler:
    return _make(root)


def _bash(root: Path, command: str, cwd: Path | None = None) -> dict[str, Any]:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd or root),
    }


def _tool(name: str, **tool_input: str) -> dict[str, Any]:
    return {"tool_name": name, "tool_input": tool_input}


class TestOffByDefault:
    def test_the_handler_ships_disabled(self) -> None:
        assert WriteProtectedPathsHandler().get_default_enabled() is False

    @pytest.mark.parametrize("paths", [None, []])
    def test_with_no_paths_nothing_matches(self, root: Path, paths: list[str] | None) -> None:
        handler = WriteProtectedPathsHandler(project_root=root)
        if paths is not None:
            apply_handler_options(handler, {"paths": paths})
        assert handler.matches(_bash(root, f"rm {root}/{PROTECTED}")) is False
        assert handler.matches(_tool("Write", file_path=f"{root}/{PROTECTED}")) is False


class TestFileTools:
    @pytest.mark.parametrize(
        ("tool", "key"),
        [("Write", "file_path"), ("Edit", "file_path"), ("NotebookEdit", "notebook_path")],
    )
    def test_a_write_to_a_listed_path_is_denied(
        self, handler: WriteProtectedPathsHandler, root: Path, tool: str, key: str
    ) -> None:
        hook_input = _tool(tool, **{key: f"{root}/{PROTECTED}"})
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        reason = result.reason or ""
        assert "IaC" in reason
        assert "human" in reason
        assert PROTECTED in reason

    def test_a_path_through_dot_dot_is_still_the_listed_path(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        hook_input = _tool("Write", file_path=f"{root}/.claude/x/../ccy/ccy.env.local")
        assert handler.matches(hook_input) is True

    def test_a_path_through_a_symlink_is_still_the_listed_path(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        (root / "alias").symlink_to(root / ".claude" / "ccy")
        assert handler.matches(_tool("Write", file_path=f"{root}/alias/ccy.env.local")) is True

    def test_an_unlisted_path_is_allowed(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        assert (
            handler.matches(_tool("Write", file_path=f"{root}/.claude/ccy/ccy.env.local.dist"))
            is False
        )
        assert handler.matches(_tool("Edit", file_path=f"{root}/README.md")) is False

    def test_reading_is_never_denied(self, handler: WriteProtectedPathsHandler, root: Path) -> None:
        assert handler.matches(_tool("Read", file_path=f"{root}/{PROTECTED}")) is False
        assert handler.matches(_tool("Grep", path=f"{root}/{PROTECTED}", pattern="x")) is False

    def test_a_missing_path_does_not_match(self, handler: WriteProtectedPathsHandler) -> None:
        assert handler.matches(_tool("Write")) is False


class TestBashWrites:
    @pytest.mark.parametrize(
        "template",
        [
            "echo x > {p}",
            "echo x >> {p}",
            "echo x >| {p}",
            "echo x | tee {p}",
            "echo x | tee -a other.txt {p}",
            "cat > {p} <<'EOF'\nline\nEOF",
            ": > {p}",
            "> {p}",
            "sed -i s/a/b/ {p}",
            "sed -i.bak -e s/a/b/ {p}",
            "dd if=/dev/zero of={p}",
            "cp /tmp/source.txt {p}",
            "mv /tmp/source.txt {p}",
            "install /tmp/source.txt {p}",
            "ln -s /tmp/source.txt {p}",
            "ln -sf /tmp/source.txt {p}",
            "rm {p}",
            "rm -f {p}",
            "rm -rf -- {p}",
            "truncate -s 0 {p}",
            "mv {p} /tmp/gone.txt",
            "echo ok && rm {p}",
            "git rm {p}",
        ],
    )
    def test_a_command_that_changes_the_listed_path_is_denied(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        hook_input = _bash(root, template.format(p=f"{root}/{PROTECTED}"))
        assert handler.matches(hook_input) is True
        assert handler.handle(hook_input).decision == Decision.DENY

    @pytest.mark.parametrize(
        "template",
        [
            "echo x > {p}",
            "rm {p}",
            "cp /tmp/source.txt {p}",
            "truncate -s 0 {p}",
            "sed -i s/a/b/ {p}",
        ],
    )
    def test_the_relative_spelling_is_judged_from_the_working_directory(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert handler.matches(_bash(root, template.format(p=PROTECTED))) is True
        inside = root / ".claude" / "ccy"
        assert handler.matches(_bash(root, template.format(p="ccy.env.local"), cwd=inside)) is True
        assert (
            handler.matches(_bash(root, template.format(p="./ccy.env.local"), cwd=inside)) is True
        )

    def test_copying_into_the_directory_under_the_listed_name_is_denied(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        command = f"cp /tmp/ccy.env.local {root}/.claude/ccy/"
        assert handler.matches(_bash(root, command)) is True

    def test_copying_into_the_directory_under_another_name_is_allowed(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        command = f"cp /tmp/other.txt {root}/.claude/ccy/"
        assert handler.matches(_bash(root, command)) is False

    @pytest.mark.parametrize(
        "template",
        ["rm -rf {r}/.claude/ccy", "rm -rf {r}/.claude", "mv {r}/.claude/ccy /tmp/elsewhere"],
    )
    def test_removing_or_moving_a_directory_that_holds_it_is_denied(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert handler.matches(_bash(root, template.format(r=root))) is True

    def test_a_cd_then_a_relative_write_is_denied(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        command = f"cd {root}/.claude/ccy && rm ccy.env.local"
        assert handler.matches(_bash(root, command)) is True

    @pytest.mark.parametrize(
        "command",
        [
            "cat {p}",
            "grep -n X {p}",
            "head -n 5 {p}",
            "diff {p} /tmp/other.txt",
            "cp {p} /tmp/copy.txt",
            "cat {p} > /tmp/out.txt",
            "wc -l < {p}",
            "sed -n 1,5p {p}",
            "sed s/a/b/ {p}",
            "ls -l {p}",
            "echo {p}",
            "echo x > /tmp/elsewhere.txt",
            "rm /tmp/elsewhere.txt",
        ],
    )
    def test_reading_is_never_denied(
        self, handler: WriteProtectedPathsHandler, root: Path, command: str
    ) -> None:
        assert handler.matches(_bash(root, command.format(p=f"{root}/{PROTECTED}"))) is False

    def test_a_path_that_only_shares_the_directory_is_allowed(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        command = f"echo x > {root}/.claude/ccy/ccy.env.local.dist"
        assert handler.matches(_bash(root, command)) is False

    def test_a_non_bash_non_file_tool_never_matches(
        self, handler: WriteProtectedPathsHandler
    ) -> None:
        assert handler.matches(_tool("WebFetch", url="https://example.com")) is False


class TestFailClosed:
    @pytest.mark.parametrize(
        "command",
        [
            'echo x > "$DIR/ccy.env.local"',
            "rm $HOME_DIR/.claude/ccy/ccy.env.local",
            "rm .claude/ccy/ccy.env.*",
            "rm .claude/ccy/*",
            "truncate -s 0 .claude/ccy/ccy.env.l?cal",
            "cp /tmp/x $(pwd -P)/.claude/ccy/ccy.env.local",
        ],
    )
    def test_an_unresolved_destination_that_names_the_path_is_denied(
        self, handler: WriteProtectedPathsHandler, root: Path, command: str
    ) -> None:
        assert handler.matches(_bash(root, command)) is True

    @pytest.mark.parametrize(
        "command",
        [
            'echo x > "$OUT"',
            "rm $TARGET",
            "rm /tmp/*.txt",
            "echo x > $(mktemp)",
        ],
    )
    def test_an_unresolved_destination_that_names_nothing_listed_is_allowed(
        self, handler: WriteProtectedPathsHandler, root: Path, command: str
    ) -> None:
        assert handler.matches(_bash(root, command)) is False

    def test_a_known_variable_is_resolved_and_judged(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        command = f"F={root}/{PROTECTED}; rm $F"
        assert handler.matches(_bash(root, command)) is True

    def test_unreadable_text_naming_the_path_is_denied(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        command = f'true\necho "never closed {root}/{PROTECTED}'
        assert handler.matches(_bash(root, command)) is True

    def test_unreadable_text_naming_nothing_listed_is_allowed(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        assert handler.matches(_bash(root, 'true\necho "never closed')) is False

    def test_a_script_fed_to_a_shell_is_read_like_the_command(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        command = f"bash <<'EOF'\nrm {root}/{PROTECTED}\nEOF"
        assert handler.matches(_bash(root, command)) is True


class TestConfiguration:
    def test_a_recursive_glob_is_honoured(self, root: Path) -> None:
        handler = _make(root, ["**/*.env.local"])
        assert handler.matches(_bash(root, f"echo x > {root}/deep/er/a.env.local")) is True
        assert handler.matches(_bash(root, f"echo x > {root}/deep/er/a.env")) is False

    def test_several_paths_are_each_protected(self, root: Path) -> None:
        handler = _make(root, [PROTECTED, "secrets/*.txt"])
        assert handler.matches(_tool("Write", file_path=f"{root}/secrets/a.txt")) is True
        assert handler.matches(_tool("Write", file_path=f"{root}/{PROTECTED}")) is True
        assert handler.matches(_tool("Write", file_path=f"{root}/secrets/a.md")) is False

    def test_a_worktree_of_the_project_is_protected_too(self, root: Path, tmp_path: Path) -> None:
        worktree = tmp_path.parent / f"{tmp_path.name}-worktree"
        (worktree / ".claude" / "ccy").mkdir(parents=True)
        (worktree / ".git").write_text("gitdir: elsewhere\n")
        handler = _make(root)
        hook_input = _bash(root, f"rm {worktree}/{PROTECTED}", cwd=worktree)
        assert handler.matches(hook_input) is True

    @pytest.mark.parametrize(
        ("options", "expected_keys"),
        [
            ({"paths": "not-a-list"}, {"paths"}),
            ({"paths": [1]}, {"paths"}),
            ({"paths": [""]}, {"paths"}),
            ({"paths": ["/abs/path"]}, {"paths"}),
            ({"paths": ["../outside"]}, {"paths"}),
            ({"paths": [PROTECTED]}, set()),
            ({}, set()),
        ],
    )
    def test_malformed_options_are_refused(
        self, options: dict[str, Any], expected_keys: set[str]
    ) -> None:
        assert set(WriteProtectedPathsHandler.validate_options(options)) == expected_keys


class TestGuidanceAndAcceptance:
    def test_it_is_a_terminal_pre_tool_use_blocker(self) -> None:
        handler = WriteProtectedPathsHandler()
        assert handler.terminal is True
        assert handler.name == "write-protected-paths"

    def test_the_guidance_says_what_is_protected_and_who_to_ask(self) -> None:
        guidance = WriteProtectedPathsHandler().get_claude_md()
        assert guidance is not None
        assert "write_protected_paths" in guidance
        assert "human" in guidance

    def test_it_backs_one_rule(self) -> None:
        (rule,) = WriteProtectedPathsHandler().get_rules()
        assert rule.rule_id == "R-WRITE-PROTECTED-PATH"

    def test_the_drivable_acceptance_test_allows_through_the_real_handler(self, root: Path) -> None:
        tests = WriteProtectedPathsHandler().get_acceptance_tests()
        (allow,) = [t for t in tests if t.expected_decision == Decision.ALLOW]
        assert _make(root).matches(_bash(root, allow.command)) is False

    def test_the_deny_acceptance_test_is_declared_undrivable_and_says_why(self) -> None:
        tests = WriteProtectedPathsHandler().get_acceptance_tests()
        (deny,) = [t for t in tests if t.expected_decision == Decision.DENY]
        assert deny.harness_cannot_produce
