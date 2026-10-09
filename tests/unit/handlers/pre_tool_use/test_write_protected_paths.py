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


class TestWildcardsFollowTheShell:
    """An unresolved wildcard names the file only if the shell could expand it to it."""

    @pytest.mark.parametrize(
        ("command", "where"),
        [
            ("rm -f *", "untracked/scratch"),
            ("rm -rf *", ""),
            ("rm -rf */*", ""),
            ("rm -f *.local", "untracked/scratch"),
            ("rm -- *.log *", "untracked/scratch"),
            ("mv * ../dest/", "untracked/scratch"),
            ("truncate -s0 *", "untracked/scratch"),
        ],
    )
    def test_a_wildcard_that_cannot_reach_the_file_is_allowed(
        self, handler: WriteProtectedPathsHandler, root: Path, command: str, where: str
    ) -> None:
        (root / where).mkdir(parents=True, exist_ok=True)
        assert handler.matches(_bash(root, command, cwd=root / where)) is False

    @pytest.mark.parametrize(
        ("command", "where"),
        [
            ("rm -f *", ".claude/ccy"),
            ("rm -f *.local", ".claude/ccy"),
            ("rm -f ccy.env.*", ".claude/ccy"),
            ("rm -rf .claude/*", ""),
            ("rm -rf .claude/c*", ""),
            ("rm .claude/ccy/*", ""),
            ("rm -rf */*", ".claude"),
            ("rm -rf *", ".claude"),
            ("mv .claude/ccy/c* /tmp/", ""),
        ],
    )
    def test_a_wildcard_that_can_reach_the_file_is_denied(
        self, handler: WriteProtectedPathsHandler, root: Path, command: str, where: str
    ) -> None:
        assert handler.matches(_bash(root, command, cwd=root / where)) is True

    def test_a_wildcard_never_matches_a_leading_dot(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        assert handler.matches(_bash(root, "rm -rf *")) is False
        assert handler.matches(_bash(root, "rm -rf .*")) is True


class TestOnlyCommandsAreJudged:
    @pytest.mark.parametrize(
        "command",
        [
            "grep rm {p}",
            "grep -n truncate {p}",
            "grep touch {p}",
            "echo unlink {p}",
            "grep cp /tmp/a {p}",
        ],
    )
    def test_a_verb_named_as_an_argument_is_a_read(
        self, handler: WriteProtectedPathsHandler, root: Path, command: str
    ) -> None:
        assert handler.matches(_bash(root, command.format(p=f"{root}/{PROTECTED}"))) is False

    @pytest.mark.parametrize(
        "template",
        [
            "sudo rm {p}",
            "sudo -u root rm {p}",
            "echo x | xargs rm {p}",
            "FOO=1 rm {p}",
            "env FOO=1 rm {p}",
            "if true; then rm {p}; fi",
            "(rm {p})",
            "git rm {p}",
            "git -C /somewhere rm {p}",
            "timeout 5 rm {p}",
            "find /tmp -exec rm {p} ;",
        ],
    )
    def test_a_verb_behind_a_wrapper_or_at_a_command_head_is_denied(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert handler.matches(_bash(root, template.format(p=f"{root}/{PROTECTED}"))) is True


class TestNameOnlyMatchingNeedsTheParentChain:
    @pytest.mark.parametrize(
        "command",
        [
            'rm -rf "$TMPDIR/.claude"',
            'cp -r "$SRC/.claude" "$DEST/.claude"',
            'rm -rf "$WORK/ccy"',
            'cd "$D" && rm -rf ccy',
        ],
    )
    def test_a_bare_directory_name_is_not_the_protected_path(
        self, handler: WriteProtectedPathsHandler, root: Path, command: str
    ) -> None:
        assert handler.matches(_bash(root, command)) is False

    @pytest.mark.parametrize(
        "command",
        [
            'rm -rf "$W/.claude/ccy"',
            'cd "$D" && rm -rf .claude/ccy',
            'rm "$W/ccy.env.local"',
        ],
    )
    def test_the_chain_toward_the_file_or_the_file_name_is(
        self, handler: WriteProtectedPathsHandler, root: Path, command: str
    ) -> None:
        assert handler.matches(_bash(root, command)) is True


class TestEachCommandRunsWhereItRuns:
    @pytest.mark.parametrize(
        "command",
        [
            "cd /tmp/otherclone && rm -rf .claude",
            "cd .claude; cd /tmp/x; rm -rf ccy",
            "cd /tmp/x && cd ../y && rm -rf .claude/ccy",
        ],
    )
    def test_a_command_after_a_cd_elsewhere_is_judged_there(
        self, handler: WriteProtectedPathsHandler, root: Path, command: str
    ) -> None:
        assert handler.matches(_bash(root, command)) is False

    @pytest.mark.parametrize(
        "command",
        [
            "rm -rf .claude/ccy && cd /tmp",
            "cd /tmp/x; cd {r}/.claude && rm -rf ccy",
            "(cd /tmp/x); rm -rf .claude/ccy",
        ],
    )
    def test_a_command_that_runs_in_the_project_is_still_denied(
        self, handler: WriteProtectedPathsHandler, root: Path, command: str
    ) -> None:
        assert handler.matches(_bash(root, command.format(r=root))) is True


class TestVariablesSurviveACd:
    @pytest.mark.parametrize(
        "template",
        [
            "F={p}; cd /tmp; rm $F",
            'F={p} && cd /tmp && rm "$F"',
            'F={p}; cd /tmp && echo x > "$F"',
            "export F={p}; cd /tmp; rm $F",
        ],
    )
    def test_an_assignment_before_a_cd_still_resolves_after_it(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert handler.matches(_bash(root, template.format(p=f"{root}/{PROTECTED}"))) is True

    def test_an_assignment_naming_another_file_stays_allowed(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        assert handler.matches(_bash(root, "F=/tmp/other.txt; cd /tmp; rm $F")) is False


class TestCachedVerdictIsNotReused:
    def test_an_allow_is_not_reused_after_the_configuration_changes(self, root: Path) -> None:
        handler = _make(root, [])
        hook_input = _bash(root, f"rm {root}/{PROTECTED}")
        assert handler.matches(hook_input) is False
        apply_handler_options(handler, {"paths": [PROTECTED]})
        assert handler.matches(hook_input) is True

    def test_a_later_identical_call_is_judged_again(self, root: Path) -> None:
        handler = _make(root)
        hook_input = _bash(root, f"rm {root}/{PROTECTED}")
        assert handler.matches(hook_input) is True
        assert handler.handle(hook_input).decision == Decision.DENY
        apply_handler_options(handler, {"paths": []})
        assert handler.matches(hook_input) is False


class TestXargs:
    def test_names_fed_to_a_mutating_verb_by_xargs_are_denied(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        assert handler.matches(_bash(root, f"echo {PROTECTED} | xargs rm")) is True
        assert handler.matches(_bash(root, f"printf '%s\\n' {PROTECTED} | xargs -r unlink")) is True

    def test_xargs_over_other_names_or_a_reading_verb_is_allowed(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        assert handler.matches(_bash(root, "echo other.txt | xargs rm")) is False
        assert handler.matches(_bash(root, f"echo {PROTECTED} | xargs cat")) is False

    @pytest.mark.parametrize(
        "template",
        [
            "ls {p} | xargs -I{{}} cp {{}} /tmp/backup",
            "ls {p} | xargs -I{{}} install {{}} /tmp/backup",
            "echo {p}; echo other.txt | xargs rm",
            "echo {p} && echo other.txt | xargs rm",
        ],
    )
    def test_a_copy_out_or_another_pipeline_is_allowed(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert handler.matches(_bash(root, template.format(p=PROTECTED))) is False


class TestCreationAndRemoval:
    @pytest.mark.parametrize("template", ["touch {p}", "touch -c {p}", "unlink {p}"])
    def test_creating_or_unlinking_is_denied(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert handler.matches(_bash(root, template.format(p=f"{root}/{PROTECTED}"))) is True

    @pytest.mark.parametrize(
        "template",
        ["touch -r {p} /tmp/other.txt", "touch /tmp/other.txt", "unlink /tmp/other.txt"],
    )
    def test_a_reference_read_or_another_file_is_allowed(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert handler.matches(_bash(root, template.format(p=f"{root}/{PROTECTED}"))) is False

    def test_the_guidance_names_every_denied_verb(self) -> None:
        guidance = WriteProtectedPathsHandler().get_claude_md() or ""
        for word in ("touch", "unlink", "truncate", "rm", "tee", "ln", "dd", "perl", "rsync"):
            assert word in guidance


class TestDirectoryChanges:
    def test_a_literal_cd_is_followed_to_the_directory_it_names(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        assert handler.matches(_bash(root, "cd .claude && rm -rf ccy")) is True
        assert handler.matches(_bash(root, "cd .claude/ccy; echo x > ccy.env.local")) is True
        assert handler.matches(_bash(root, "cd .claude && cd ccy && rm ccy.env.local")) is True
        assert handler.matches(_bash(root, "cd /tmp && rm ccy.env.local")) is False

    def test_a_cd_the_handler_cannot_follow_is_judged_by_name(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        assert handler.matches(_bash(root, 'cd "$D" && rm ccy.env.local')) is True
        assert handler.matches(_bash(root, 'cd "$D" && rm -rf .claude/ccy')) is True
        assert handler.matches(_bash(root, 'cd "$D" && rm other.txt')) is False

    def test_a_wildcard_entry_is_not_a_project_wide_name_match(self, root: Path) -> None:
        handler = _make(root, ["deploy/*.env"])
        assert handler.matches(_bash(root, "cd frontend && echo A=1 > .env")) is False
        assert handler.matches(_bash(root, "cd deploy && echo A=1 > .env")) is True
        assert handler.matches(_bash(root, "echo A=1 > deploy/prod.env")) is True

    def test_a_name_is_matched_as_a_whole_segment_not_a_substring(self, root: Path) -> None:
        handler = _make(root, ["deploy/*.env"])
        assert handler.matches(_bash(root, 'echo x > "$X/.envrc"')) is False
        assert handler.matches(_bash(root, 'echo x > "$X/prod.env"')) is True


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


ABS = "{r}/" + PROTECTED


def _denied(handler: WriteProtectedPathsHandler, root: Path, template: str) -> bool:
    command = template.format(p=PROTECTED, a=ABS.format(r=root), r=root)
    return handler.matches(_bash(root, command))


class TestUnlistedWrappersHideNothing:
    """Plan 00499 Task 1b.1: a command that names the file and is not known to
    only read is denied, however it is wrapped."""

    @pytest.mark.parametrize(
        "template",
        [
            "flock /tmp/l rm {p}",
            "flock -x /tmp/l rm -f {a}",
            "chronic rm {p}",
            "chronic mv {p} /tmp/gone",
            "nice -n 5 rm {p}",
            "stdbuf -o0 tee {p}",
            "echo x | stdbuf -o0 tee {p}",
            "ionice -c3 truncate -s0 {p}",
            "doas rm {p}",
            "setsid rm {p}",
            "flock /tmp/l rm -rf .claude/ccy",
            "chronic rm -rf {r}/.claude",
            "python3 tool.py --out {p}",
            "perl -i -pe s/a/b/ {p}",
            "rsync /tmp/new.env {p}",
            "shred -u {p}",
            "find {p} -delete",
            "gawk -i inplace 1 {a}",
            "make {p}",
        ],
    )
    def test_a_command_that_names_the_file_and_is_not_known_to_read_is_denied(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert _denied(handler, root, template) is True

    @pytest.mark.parametrize(
        "template",
        [
            "cat {p}",
            "less {p}",
            "head -n 3 {a}",
            "tail -n 3 {p}",
            "grep -n X {p}",
            "rg X {p}",
            "wc -l {p}",
            "stat {p}",
            "ls -l {p}",
            "file {p}",
            "diff {p} /tmp/other",
            "cmp {p} /tmp/other",
            "sha256sum {p}",
            "md5sum {a}",
            "test -f {p}",
            "[ -f {p} ]",
            "[[ -f {p} ]]",
            "git diff -- {p}",
            "git log --oneline -- {p}",
            "git show HEAD:{p}",
            "git status {p}",
            "git blame {p}",
            "git -C {r} diff {p}",
            "git add {p}",
            "source {p}",
            ". {p}",
            "export F={p}",
            "F={p}; echo $F",
            "flock /tmp/l cat {p}",
            "nice -n 5 grep X {p}",
            "ionice -c3 cat {p}",
            "chronic cat {p}",
            "sudo cat {p}",
            "env FOO=1 cat {p}",
            "timeout 5 grep X {p}",
            "/bin/cat {p}",
            "/usr/bin/grep -n X {a}",
            "cat {p} | wc -l",
            "echo ok && cat {p}",
            "if true; then cat {p}; fi",
            "python3 tool.py --out /tmp/elsewhere",
            "flock /tmp/l rm /tmp/elsewhere",
            "git commit -m 'document .claude/ccy/ccy.env.local'",
            "echo 'docs: ccy.env.local is placed by IaC' > /tmp/note.txt",
            "cat > /tmp/notes.md <<'EOF'\nThe file .claude/ccy/ccy.env.local is placed by IaC.\nEOF",
        ],
    )
    def test_a_command_known_to_only_read_is_allowed(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert _denied(handler, root, template) is False

    def test_a_read_only_command_with_a_write_redirect_is_still_denied(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        assert _denied(handler, root, "cat /tmp/x > {p}") is True
        assert _denied(handler, root, "flock /tmp/l cat /tmp/x >> {p}") is True

    def test_a_known_variable_naming_the_file_is_followed_into_an_unknown_command(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        assert _denied(handler, root, "F={p}; flock /tmp/l rm $F") is True
        assert _denied(handler, root, "F={p}; python3 tool.py $F") is True
        assert _denied(handler, root, "F=/tmp/other; python3 tool.py $F") is False

    def test_an_unresolved_operand_is_judged_by_name_for_an_unknown_command(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        assert _denied(handler, root, 'python3 tool.py "$D/ccy.env.local"') is True
        assert _denied(handler, root, 'python3 tool.py "$D/other.txt"') is False

    def test_a_wildcard_that_could_reach_the_file_is_denied_for_an_unknown_command(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        assert _denied(handler, root, "python3 tool.py .claude/ccy/ccy.env.*") is True
        assert _denied(handler, root, "python3 tool.py /tmp/*.txt") is False

    def test_an_option_value_naming_the_file_is_denied(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        assert _denied(handler, root, "python3 tool.py --out={p}") is True

    def test_an_input_redirect_from_the_file_is_not_a_write(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        assert _denied(handler, root, "python3 tool.py < {p}") is False

    def test_an_unknown_command_naming_only_a_directory_above_it_is_allowed(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        assert _denied(handler, root, "ruff check .claude") is False
        assert _denied(handler, root, "pytest .") is False

    def test_the_deny_reason_names_the_read_only_commands(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        hook_input = _bash(root, f"python3 tool.py {PROTECTED}")
        assert handler.matches(hook_input) is True
        reason = handler.handle(hook_input).reason or ""
        assert "cat" in reason
        assert "grep" in reason


class TestBraceExpansion:
    """Plan 00499 Task 1b.2: brace groups are spelled out before the path is judged."""

    @pytest.mark.parametrize(
        "template",
        [
            "rm .claude/ccy/ccy.env.{{local,bak}}",
            "rm .claude/ccy/ccy.env.{{bak,local}}",
            "rm -f {r}/.claude/ccy/ccy.env.{{local,bak}}",
            "echo x | tee .claude/ccy/ccy.env.{{local,bak}}",
            "cp /tmp/x .claude/ccy/ccy.env.{{local,dist}}",
            "cp /tmp/x .claude/ccy/ccy.env.{{dist,local}}",
            "mv /tmp/x .claude/ccy/ccy.env.{{bak,local}}",
            "rm .claude/{{ccy,other}}/ccy.env.local",
            "rm .claude/ccy/ccy.env.{{lo{{c,x}}al,bak}}",
            "rm .claude/ccy/ccy.env.l{{o..p}}cal",
            "touch .claude/ccy/ccy.env.{{local,}}",
            "rm -rf .claude/{{ccy,x}}",
            "truncate -s0 .claude/ccy/{{ccy.env.local,x}}",
            "flock /tmp/l rm .claude/ccy/ccy.env.{{local,bak}}",
            "bash -c 'rm .claude/ccy/ccy.env.{{local,bak}}'",
            "echo x > .claude/ccy/ccy.env.{{local,bak}}",
            "cd .claude && rm ccy/ccy.env.{{local,bak}}",
        ],
    )
    def test_a_group_that_spells_the_file_is_denied(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert _denied(handler, root, template) is True

    @pytest.mark.parametrize(
        "command",
        [
            "rm .claude/ccy/ccy.env.{dist,bak}",
            "rm .claude/ccy/other.{local,bak}",
            "cp /tmp/x .claude/ccy/ccy.env.{dist,bak}",
            "cat .claude/ccy/ccy.env.{local,bak}",
            "ls .claude/ccy/ccy.env.{local,dist}",
            "grep X .claude/ccy/ccy.env.{local,bak}",
            "echo {a,b} {1..3}",
            "rm /tmp/x.{a,b}",
            "echo ${HOME}/x {}",
            "echo '.claude/ccy/ccy.env.{local,bak}'",
            "git commit -m 'drop ccy.env.{local,bak}'",
        ],
    )
    def test_a_group_that_does_not_spell_the_file_or_only_reads_it_is_allowed(
        self, handler: WriteProtectedPathsHandler, root: Path, command: str
    ) -> None:
        assert handler.matches(_bash(root, command)) is False

    def test_a_group_with_too_many_spellings_is_denied_only_when_it_names_the_file(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        many = "{a,b}" * 20
        assert handler.matches(_bash(root, f"echo {many}")) is False
        assert handler.matches(_bash(root, f"rm {many} ccy.env.local")) is True

    def test_a_group_after_an_unreadable_substitution_is_judged_by_name(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        assert handler.matches(_bash(root, "rm $(date) .claude/ccy/ccy.env.local{,.bak}")) is True
        assert handler.matches(_bash(root, "rm $(date) /tmp/x.{a,b}")) is False


class TestShellStringsAndAbsoluteCommands:
    """Plan 00499 Task 1b.3: code handed to a shell is a command; so is a path to one."""

    @pytest.mark.parametrize(
        "template",
        [
            "bash -c 'rm {p}'",
            'sh -c "rm {p}"',
            "bash -c 'echo x > {p}'",
            "bash -lc 'rm {p}'",
            "bash -x -c 'rm {p}'",
            "/bin/bash -c 'rm {p}'",
            "sudo bash -c 'rm {p}'",
            "chronic sh -c 'rm {p}'",
            "dash -c 'truncate -s0 {p}'",
            "eval 'rm {p}'",
            "eval rm {p}",
            'eval "rm {p}"',
            "flock /tmp/l -c 'rm {p}'",
            "su -c 'rm {p}' root",
            "bash -c \"bash -c 'rm {p}'\"",
            "bash -c 'cd .claude && rm -rf ccy'",
            "cd .claude && bash -c 'rm ccy/ccy.env.local'",
            'F={p}; bash -c "rm $F"',
            "/bin/rm {p}",
            "/usr/bin/rm -f {a}",
            "echo x | /usr/bin/tee {p}",
            "/usr/bin/tee {p} < /tmp/x",
            "/bin/mv /tmp/x {p}",
            "/bin/cp /tmp/x {p}",
            "/usr/bin/env rm {p}",
            "FOO=1 /bin/rm {p}",
            "'/bin/rm' {p}",
            "bash -c 'true; rm {p}'",
        ],
    )
    def test_a_write_through_a_shell_string_or_an_absolute_command_is_denied(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert _denied(handler, root, template) is True

    @pytest.mark.parametrize(
        "template",
        [
            "bash -c 'cat {p}'",
            'sh -c "grep X {p}"',
            "bash -lc 'cat {p}'",
            "eval 'cat {p}'",
            "eval cat {p}",
            "flock /tmp/l -c 'cat {p}'",
            "bash -c 'rm /tmp/elsewhere'",
            "bash -c 'echo x > /tmp/elsewhere'",
            "bash -c 'cat {p} | wc -l'",
            "bash script.sh {p}",
            "/bin/rm /tmp/elsewhere",
            "/usr/bin/tee /tmp/elsewhere",
            "/bin/cat {p}",
            "/bin/cp {p} /tmp/copy",
            "sudo bash -c 'cat {p}'",
        ],
    )
    def test_a_read_through_a_shell_string_or_an_absolute_command_is_allowed(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert _denied(handler, root, template) is False

    def test_nesting_deeper_than_the_bound_is_judged_by_name(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        deep = "rm ccy.env.local"
        for _ in range(8):
            deep = "bash -c " + "'" + deep.replace("'", "'\"'\"'") + "'"
        assert handler.matches(_bash(root, deep, cwd=root / ".claude" / "ccy")) is True
        harmless = "bash -c 'true'"
        for _ in range(8):
            harmless = "bash -c " + "'" + harmless.replace("'", "'\"'\"'") + "'"
        assert handler.matches(_bash(root, harmless)) is False


class TestDirectoryChangeWithRedirectAndLoops:
    """Plan 00499 Task 1b.4."""

    @pytest.mark.parametrize(
        "command",
        [
            "cd .claude 2>/dev/null && rm -rf ccy",
            "cd .claude >/dev/null 2>&1 && rm ccy/ccy.env.local",
            "cd .claude &>/dev/null; rm -rf ccy",
            "cd .claude 2>/dev/null; cd ccy && rm ccy.env.local",
            "cd .claude > /dev/null && rm -rf ccy",
            "cd .claude/ccy 2>/dev/null && echo x > ccy.env.local",
        ],
    )
    def test_a_cd_carrying_a_redirect_still_changes_the_directory(
        self, handler: WriteProtectedPathsHandler, root: Path, command: str
    ) -> None:
        assert handler.matches(_bash(root, command)) is True

    @pytest.mark.parametrize(
        "command",
        [
            "cd /tmp 2>/dev/null && rm -rf ccy",
            "cd /tmp >/dev/null 2>&1 && rm ccy.env.local",
            "cd .claude 2>/dev/null && cat ccy/ccy.env.local",
            "cd .claude 2>/dev/null && rm other.txt",
        ],
    )
    def test_a_cd_carrying_a_redirect_elsewhere_or_a_read_is_allowed(
        self, handler: WriteProtectedPathsHandler, root: Path, command: str
    ) -> None:
        assert handler.matches(_bash(root, command)) is False

    @pytest.mark.parametrize(
        "template",
        [
            'for f in {p}; do rm "$f"; done',
            "for f in {a}; do rm -f $f; done",
            'for f in /tmp/a {p}; do rm "$f"; done',
            'for f in {p}\ndo\n  rm "$f"\ndone',
            'for f in {p}; do echo x > "$f"; done',
            "for f in {p}; do truncate -s0 ${{f}}; done",
            'for f in .claude/ccy/*; do rm "$f"; done',
            'for f in {p}; do chronic rm "$f"; done',
            'for f in {p}; do bash -c "rm $f"; done',
            'for f in .claude/ccy/ccy.env.{{local,bak}}; do rm "$f"; done',
            "for f in a b; do echo $f; done; rm {p}",
        ],
    )
    def test_a_loop_over_the_file_that_writes_it_is_denied(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert _denied(handler, root, template) is True

    @pytest.mark.parametrize(
        "template",
        [
            'for f in {p}; do cat "$f"; done',
            'for f in {p}; do grep X "$f"; done',
            'for f in /tmp/a /tmp/b; do rm "$f"; done',
            "for f in a b; do echo $f; done",
            'for f in {p}; do echo "$f"; done',
            'for f in a b; do rm "/tmp/$f"; done',
        ],
    )
    def test_a_loop_that_only_reads_or_leaves_it_alone_is_allowed(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert _denied(handler, root, template) is False


_LINEAR_SHAPES: dict[str, Any] = {
    "wrapped_reads": lambda n: "; ".join(["flock /tmp/l cat /tmp/x"] * n),
    "assignments_then_cd": lambda n: "; ".join(["F=a"] * n) + "; cd a; echo x",
    "cd_parts": lambda n: "; ".join(["cd a"] * n) + "; echo x",
    "brace_groups": lambda n: "echo " + " ".join(["x{a,b}"] * n),
    "loops": lambda n: "; ".join(["for f in a b c; do echo /tmp/$f; done"] * n),
    "newline_run": lambda n: "true" + "\n" * (n * 20),
    "export_run": lambda n: "export A=1;" * n + "echo x",
    "nested_shells": lambda n: "; ".join(["bash -c 'echo a; echo b'"] * n),
}


class TestHostileInputStaysLinear:
    """Cost may not grow faster than the command, with `paths` SET (review B1, S11)."""

    @pytest.mark.parametrize("shape", sorted(_LINEAR_SHAPES))
    def test_a_long_command_is_judged_in_proportion_to_its_length(
        self, handler: WriteProtectedPathsHandler, root: Path, shape: str
    ) -> None:
        import time

        def cost(count: int) -> float:
            command = _LINEAR_SHAPES[shape](count)
            started = time.perf_counter()
            assert handler.matches(_bash(root, command)) is False
            return time.perf_counter() - started

        cost(20)
        small, large = min(cost(40) for _ in range(2)), min(cost(320) for _ in range(2))
        assert large < small * 8 * 3

    def test_ten_kilobytes_of_assignments_before_a_cd_is_judged_quickly(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        import time

        command = "; ".join(["F=a"] * 2000) + "; cd a; rm ccy.env.local"
        started = time.perf_counter()
        handler.matches(_bash(root, command))
        assert time.perf_counter() - started < 5

    def test_assignments_before_a_cd_still_resolve_after_it(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        many = "; ".join(f"V{i}=x" for i in range(100))
        command = f"{many}; F={root}/{PROTECTED}; cd /tmp; rm $F"
        assert handler.matches(_bash(root, command)) is True


def _nest(inner: str, depth: int) -> str:
    import shlex

    for _ in range(depth):
        inner = "bash -c " + shlex.quote(inner)
    return inner


class TestPastTheNestingLimitFailsClosed:
    """Review B2: text the reader stops at is denied when it names, or could name, a listed path."""

    @pytest.mark.parametrize(
        "inner",
        [
            "rm {r}/.claude/ccy/*",
            "rm {r}/.claude/ccy/ccy.env.{{local,x}}",
            "rm {r}/.claude/ccy/ccy.env.loc''al",
            "cd {r}/.claude && rm -rf ccy",
            "rm -rf {r}/.claude",
            "rm {a}",
        ],
    )
    @pytest.mark.parametrize("depth", [4, 6])
    def test_a_deep_body_naming_the_file_is_denied(
        self, handler: WriteProtectedPathsHandler, root: Path, inner: str, depth: int
    ) -> None:
        command = _nest(inner.format(r=root, a=f"{root}/{PROTECTED}"), depth)
        assert handler.matches(_bash(root, command)) is True

    def test_a_deep_eval_chain_naming_the_file_is_denied(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        import shlex

        command = "eval " + shlex.quote(_nest(f"rm {root}/.claude/ccy/*", 4))
        assert handler.matches(_bash(root, command)) is True

    def test_a_deep_body_naming_nothing_listed_is_allowed(
        self, handler: WriteProtectedPathsHandler, root: Path
    ) -> None:
        assert handler.matches(_bash(root, _nest("rm /tmp/elsewhere", 6))) is False
        assert handler.matches(_bash(root, _nest("true", 8))) is False


class TestPlainWrappersAndDeclarations:
    """Review B3, careless parts: a plain wrapper or declaration hides nothing."""

    @pytest.mark.parametrize(
        "template",
        [
            "time -p rm {p}",
            "time rm {p}",
            "command rm {p}",
            "builtin cd /tmp && command rm {p}",
            "exec rm {p}",
            "nohup rm {p}",
            "export F={a}; rm $F",
            'export F={a}; rm "$F"',
            "declare F={a}; rm $F",
            "declare -x F={a}; rm $F",
            "local F={a}; rm $F",
            "readonly F={a}; rm $F",
            "typeset F={a}; truncate -s0 $F",
            "export F={a}; cd /tmp; rm $F",
            "export F=/tmp/x; rm {p}",
        ],
    )
    def test_the_command_behind_it_is_judged(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert _denied(handler, root, template) is True

    @pytest.mark.parametrize(
        "template",
        ["time -p cat {p}", "command cat {p}", "export F={a}; cat $F", "export F=/tmp/x; rm $F"],
    )
    def test_a_read_behind_it_is_allowed(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert _denied(handler, root, template) is False


class TestXargsIsJudgedLikeAnyOtherCommand:
    """Review S2."""

    @pytest.mark.parametrize(
        "template",
        [
            "echo {a} | xargs shred -u",
            "echo {a} | xargs -n1 cp /dev/null",
            "ls .claude/ccy/* | xargs rm",
            "ls {r}/.claude/ccy/* | xargs -r unlink",
            "echo {p} | xargs -I{{}} mv {{}} /tmp/gone",
            "echo {p} | xargs -I{{}} cp /dev/null {{}}",
            "echo {p} | xargs python3 tool.py",
            "printf '%s\\n' {p} | xargs -P4 -n1 truncate -s0",
        ],
    )
    def test_a_producer_naming_the_file_feeding_a_non_reading_command_is_denied(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert _denied(handler, root, template) is True

    @pytest.mark.parametrize(
        "template",
        [
            "echo {p} | xargs cat",
            "echo {p} | xargs -n1 grep X",
            "ls {p} | xargs -I{{}} cp {{}} /tmp/backup",
            "echo other.txt | xargs rm",
            "ls /opt/* | xargs rm",
            "xargs -a /tmp/list rm",
        ],
    )
    def test_a_read_or_a_copy_out_or_another_producer_is_allowed(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert _denied(handler, root, template) is False


class TestReadLoops:
    """Review S3."""

    @pytest.mark.parametrize(
        "template",
        [
            'ls .claude/ccy/* | while read f; do rm "$f"; done',
            "while read f; do rm $f; done <<< {p}",
            'echo {p} | while read -r f; do truncate -s0 "$f"; done',
            'while read f; do echo x > "$f"; done <<< {a}',
        ],
    )
    def test_a_loop_whose_input_names_the_file_and_that_writes_is_denied(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert _denied(handler, root, template) is True

    @pytest.mark.parametrize(
        "template",
        [
            'ls .claude/ccy/* | while read f; do cat "$f"; done',
            "while read f; do rm $f; done <<< /tmp/x",
            'ls /opt/* | while read f; do rm "$f"; done',
        ],
    )
    def test_a_loop_that_reads_or_whose_input_names_nothing_listed_is_allowed(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert _denied(handler, root, template) is False


class TestFindWithAnAction:
    """Review S5."""

    @pytest.mark.parametrize(
        "template",
        [
            "find .claude/ccy -name '*.local' -delete",
            "find .claude -name ccy.env.local -delete",
            "find .claude -name 'ccy.env.*' -exec rm {{}} +",
            "find {r}/.claude/ccy -delete",
            "find .claude/ccy -type f -exec rm {{}} \\;",
            "find . -path '*ccy*' -delete",
            "find {r} -delete",
            "find .claude -fprint {p}",
        ],
    )
    def test_a_find_that_acts_on_a_tree_holding_the_file_is_denied(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert _denied(handler, root, template) is True

    @pytest.mark.parametrize(
        "template",
        [
            "find .claude -name ccy.env.local -print",
            "find .claude/ccy -type f",
            "find . -name '*.pyc' -delete",
            "find /tmp -delete",
            "find .claude -name '*.pyc' -exec rm {{}} +",
            "find .claude/ccy -name ccy.env.local -exec cat {{}} \\;",
            "find .claude/ccy -name ccy.env.local -exec grep X {{}} +",
        ],
    )
    def test_a_find_that_only_looks_or_cannot_reach_the_file_is_allowed(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert _denied(handler, root, template) is False


class TestTheFilesOwnDirectoryAsADestination:
    """Review S6."""

    @pytest.mark.parametrize(
        "template",
        [
            "rsync /tmp/ccy.env.local {r}/.claude/ccy/",
            "rsync -a --delete /tmp/empty/ .claude/ccy/",
            "tar -xf a.tar -C .claude/ccy",
            "tar -xf a.tar --directory=.claude/ccy",
            "unzip -o a.zip -d .claude/ccy",
            "cp -r /tmp/dir/. .claude/ccy",
            "cp -a /tmp/dir/ {r}/.claude/ccy/",
            "mv -T /tmp/dir .claude/ccy",
            "cd .claude/ccy && tar -xf /tmp/a.tar -C .",
        ],
    )
    def test_writing_into_the_directory_is_denied(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert _denied(handler, root, template) is True

    @pytest.mark.parametrize(
        "template",
        [
            "ruff check .claude",
            "pytest .",
            "tar -xf a.tar -C /tmp/x",
            "rsync -a /tmp/a/ /tmp/b/",
            "cp /tmp/other.txt .claude/ccy/",
            "ls .claude/ccy",
        ],
    )
    def test_naming_a_directory_above_or_elsewhere_stays_allowed(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert _denied(handler, root, template) is False


class TestReadersThatWrite:
    """Review S9."""

    @pytest.mark.parametrize(
        "template",
        [
            "git diff --output={p}",
            "git diff --output {p}",
            "git log --output={a}",
            "git -C {r} show --output={p} HEAD",
            "less -o {p} /tmp/x",
            "less -O {p} /tmp/x",
            "less --log-file={p} /tmp/x",
            "sort -o {p} /tmp/x",
            "sort --output={p} /tmp/x",
            "xxd -r /tmp/hex {p}",
            "uniq /tmp/in {p}",
        ],
    )
    def test_a_write_option_naming_the_file_is_a_write(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert _denied(handler, root, template) is True

    @pytest.mark.parametrize(
        "template",
        ["git diff --output=/tmp/out -- {p}", "sort -o /tmp/out {p}", "less -o /tmp/log {p}"],
    )
    def test_the_same_options_writing_elsewhere_are_reads_of_the_file(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert _denied(handler, root, template) is False


class TestOrdinaryReadsAreNotDenied:
    """Review S10: the allowlist must cover what an agent reads a file with."""

    @pytest.mark.parametrize(
        "template",
        [
            "sort {p}",
            "sort -u {a}",
            "awk 1 {p}",
            "awk -F= '{{print $1}}' {p}",
            "gawk '/X/' {p}",
            "xxd {p}",
            "hexdump -C {p}",
            "column -t {p}",
            "bat {p}",
            "shellcheck {p}",
            "od -c {p}",
            "strings {p}",
            "file {p}",
            "md5sum {p}",
            "comm -12 {p} /tmp/other",
            "paste {p} /tmp/other",
            "fold -w 80 {p}",
            "base64 {p}",
            "uniq {p}",
            "nl {p}",
            "diff <(sort {p}) <(sort /tmp/other)",
            "view {p}",
            "docker run --env-file {p} img",
            "docker compose --env-file {p} up",
            "docker compose -f {p} up",
            "docker-compose -f {a} config",
            "ansible-playbook site.yml --vault-password-file {p}",
            "ansible-playbook --vault-password-file={p} site.yml",
            "dotenv -f {p} list",
            "cat {p} | tool --stdin",
            "set -a; . {p}; set +a",
        ],
    )
    def test_a_known_reader_or_an_input_file_option_is_allowed(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert _denied(handler, root, template) is False

    @pytest.mark.parametrize(
        "template",
        [
            "awk -i inplace '{{print}}' {p}",
            "awk '{{print > \"{p}\"}}' /tmp/x",
            "docker run --env-file /tmp/x -v {p}:/x img",
            "docker run -v {p}:/etc/x img",
            "python3 tool.py --config {p}",
        ],
    )
    def test_a_write_or_an_unknown_use_of_the_file_is_still_denied(
        self, handler: WriteProtectedPathsHandler, root: Path, template: str
    ) -> None:
        assert _denied(handler, root, template) is True

    def test_the_documentation_says_exactly_what_is_denied(self) -> None:
        guidance = WriteProtectedPathsHandler().get_claude_md() or ""
        assert "Reading it is always allowed" not in guidance
        assert "cat P | tool" in guidance
        assert "careless-agent" in guidance or "careless agent" in guidance
        docs = (
            Path(__file__).resolve().parents[4] / "docs" / "guides" / "HANDLER_REFERENCE.md"
        ).read_text()
        section = docs.split("#### write_protected_paths", 1)[1].split("\n---\n", 1)[0]
        assert "Reading is never denied" not in section
        assert "cat P | tool" in section


class TestGuidanceAndAcceptance:
    def test_the_guidance_no_longer_lists_closed_gaps(self) -> None:
        guidance = WriteProtectedPathsHandler().get_claude_md() or ""
        assert "Known gaps" in guidance
        for closed in ("brace expansion", "`bash -c", "`/bin/rm`", "`flock`"):
            assert closed not in guidance.split("Known gaps", 1)[1]

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
