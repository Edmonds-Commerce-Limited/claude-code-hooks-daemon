"""Plan 00483 Task 3.2: the working-directory expansions and the device test."""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.utils import is_device_path, substitute_cwd_expansions


class TestIsDevicePath:
    @pytest.mark.parametrize("target", ["/dev/null", "/dev/stderr"])
    def test_a_device_node_is_one(self, target: str) -> None:
        assert is_device_path(target) is True

    @pytest.mark.parametrize("target", ["/devious/x", "/dev", "dev/null", "/tmp/dev/null"])
    def test_anything_else_is_not(self, target: str) -> None:
        assert is_device_path(target) is False


class TestSubstituteCwdExpansions:
    def test_pwd_spellings_read_as_the_cwd(self) -> None:
        for token in ("$PWD/x", "${PWD}/x", "$(pwd)/x", "$( pwd )/x"):
            assert substitute_cwd_expansions(token, "echo", "/a/b") == "/a/b/x"

    def test_a_longer_variable_name_is_left_alone(self) -> None:
        assert substitute_cwd_expansions("$PWDX/x", "echo", "/a/b") == "$PWDX/x"

    @pytest.mark.parametrize("cwd", [None, "", "relative/dir", 7])
    def test_no_absolute_cwd_leaves_the_token(self, cwd: object) -> None:
        assert substitute_cwd_expansions("$PWD/x", "echo", cwd) == "$PWD/x"

    @pytest.mark.parametrize("command", ["cd /t && x", "pushd /t", "popd", "PWD=/t; x"])
    def test_a_command_that_moves_the_directory_leaves_the_token(self, command: str) -> None:
        assert substitute_cwd_expansions("$PWD/x", command, "/a/b") == "$PWD/x"

    def test_the_toplevel_is_the_nearest_enclosing_repository(self, tmp_path: Path) -> None:
        (tmp_path / ".git").write_text("gitdir: elsewhere")
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        token = "$(git rev-parse --show-toplevel)/x"
        assert substitute_cwd_expansions(token, "echo", str(nested)) == f"{tmp_path}/x"

    def test_the_toplevel_is_left_when_no_repository_encloses_the_cwd(self, tmp_path: Path) -> None:
        token = "$(git rev-parse --show-toplevel)/x"
        assert substitute_cwd_expansions(token, "echo", str(tmp_path)) == token
