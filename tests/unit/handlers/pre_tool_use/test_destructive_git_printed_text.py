"""Printed git text that is captured or reformatted is data (GitHub #197, Plan 00596).

``msg=$(printf '%s\\n' 'then git push origin --delete b'); echo "$msg"`` and
``printf '...git reset --hard' | fold -w 40`` run no git. Every allow below has an
EXECUTING twin that must still be denied.
"""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import DestructiveGitHandler

_DELETE = "git push origin --delete b"
_RESET = "git reset --hard"
_PRINT_DELETE = f"printf '%s\\n' 'then {_DELETE}'"


def _allowed(command: str, cwd: Path) -> bool:
    handler = DestructiveGitHandler()
    event = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}
    return (not handler.matches(event)) or handler.handle(event).decision == Decision.ALLOW


class TestCapturedPrintIsData:
    @pytest.mark.parametrize(
        "command",
        [
            f'msg=$({_PRINT_DELETE}); echo "$msg"',
            f"msg=$({_PRINT_DELETE})",
            f'msg="$({_PRINT_DELETE})"; printf "%s" "$msg"',
            f'echo "$({_PRINT_DELETE})"',
            f"echo $({_PRINT_DELETE})",
            f"printf '%s' \"$(echo '{_RESET}')\"",
            f'msg=$(echo "then {_RESET}"); echo "$msg"',
        ],
    )
    def test_it_is_allowed(self, command: str, tmp_path: Path) -> None:
        assert _allowed(command, tmp_path)

    def test_a_real_delete_beside_a_captured_print_still_denies(self, tmp_path: Path) -> None:
        assert not _allowed(f'{_DELETE}; echo "$({_PRINT_DELETE})"', tmp_path)


class TestAnythingThatMayRunTheCapturedTextStillDenies:
    @pytest.mark.parametrize(
        "command",
        [
            f"$({_PRINT_DELETE})",
            f'eval "$({_PRINT_DELETE})"',
            f'bash -c "$({_PRINT_DELETE})"',
            f"sh <({_PRINT_DELETE})",
            f"source <({_PRINT_DELETE})",
            f"$({_PRINT_DELETE}) | sh",
            f'echo "$({_PRINT_DELETE})" | sh',
            f'echo "$({_PRINT_DELETE})" | xargs -I{{}} sh -c "{{}}"',
            f'echo "$({_PRINT_DELETE})" > s.sh && sh s.sh',
            f"x=$({_DELETE})",
            f'echo "$({_DELETE})"',
            f"msg=$({_PRINT_DELETE}); $msg",
            f'msg=$({_PRINT_DELETE}); eval "$msg"',
            f'msg=$({_PRINT_DELETE}); bash -c "$msg"',
            f'msg=$({_PRINT_DELETE}); sh -c "$msg"',
            f'msg=$({_PRINT_DELETE}); echo "$msg" | sh',
            f"msg=$({_PRINT_DELETE}); y=$msg; $y",
            f'msg=$({_PRINT_DELETE}); echo "$(eval "$msg")"',
            f"msg=$({_PRINT_DELETE}) sh -c 'eval \"$msg\"'",
            f'msg=$({_PRINT_DELETE}); {{ eval "$msg"; }}',
            f"$({_PRINT_DELETE}; sh)",
            f'echo "$({_PRINT_DELETE} | sh)"',
            f'echo "$({_PRINT_DELETE} > s.sh)"; sh s.sh',
        ],
    )
    def test_it_is_still_denied(self, command: str, tmp_path: Path) -> None:
        assert not _allowed(command, tmp_path)


_CAPTURE_RESET = f"m=$(printf '{_RESET}');"
_CAPTURE_DELETE = f"m=$(printf '%s\\n' '{_DELETE}');"


class TestACaptureIsDataOnlyWhenTheWholeCommandOnlyPrints:
    """Fail closed: a capture's text is blanked only when every segment of the
    command is an assignment of it, a print of it, or a formatter stage."""

    @pytest.mark.parametrize(
        "command",
        [
            f'{_CAPTURE_RESET} echo "$m"',
            f'{_CAPTURE_DELETE} echo "$m"',
            f"{_CAPTURE_DELETE} echo $m",
            f'{_CAPTURE_DELETE} echo "$m" | fold -w 40',
            f'{_CAPTURE_DELETE} n=$(echo hi); printf "%s %s" "$m" "$n"',
            f'{_CAPTURE_DELETE} echo "${{m}}" && echo done',
        ],
    )
    def test_a_print_only_command_is_allowed(self, command: str, tmp_path: Path) -> None:
        assert _allowed(command, tmp_path)

    @pytest.mark.parametrize(
        "command",
        [
            f'{_CAPTURE_RESET} echo "$m" > s.sh; sh "$x" < s.sh',
            f'{_CAPTURE_RESET} echo "$m" > s.sh; sh -- "$x" < s.sh',
            f'{_CAPTURE_RESET} echo "$m" > s.sh; sh $opt < s.sh',
            f'{_CAPTURE_RESET} echo "$m" > s.sh; sh ${{o:-}} < s.sh',
            f'{_CAPTURE_RESET} echo "$m" > s.sh; bash "$@" < s.sh',
            f'{_CAPTURE_RESET} echo "$m" > s.sh; sh $opt s.sh',
            f'{_CAPTURE_RESET} echo "$m" > s.sh; bash $flags s.sh',
            f'{_CAPTURE_RESET} echo "$m" > s.sh; sh "$PWD/s.sh"',
            f'{_CAPTURE_RESET} echo "$m" > s.sh; $SHELL s.sh',
            f'{_CAPTURE_RESET} echo "$m" > s.sh; cat s.sh | $SHELL',
            f"{_CAPTURE_RESET} echo \"$m\" > s.sh; xargs -a s.sh -I{{}} sh -c '{{}}'",
            f"{_CAPTURE_RESET} r=m; ${{!r}}",
            f"{_CAPTURE_DELETE} declare -n r=m; $r",
            f"{_CAPTURE_DELETE} local -n r=m; $r",
            f"{_CAPTURE_DELETE} typeset -n r=m; $r",
            f"{_CAPTURE_DELETE} export m; bash -c 'eval \"$m\"'",
            f"echo \"$(printf '%s\\n' '{_DELETE}')\" >> ~/.bashrc; bash -i",
            f"echo \"$(printf '%s\\n' '{_DELETE}')\" > ~/.bash_profile",
            f"echo \"$(printf '%s\\n' '{_DELETE}')\" > .git/hooks/pre-commit",
            f'{_CAPTURE_RESET} echo "$m" > notes.md',
            f'{_CAPTURE_RESET} echo "$m" 2>&1',
            f'{_CAPTURE_RESET} echo "$m" | tee s.sh',
            f'{_CAPTURE_RESET} echo "$m" | fold s.sh',
            f'{_CAPTURE_RESET} echo "$m" & sh s.sh',
            f'{_CAPTURE_RESET} echo "$q"; $q',
            f"{_CAPTURE_RESET} m=$m; $m",
            f'{_CAPTURE_RESET} a=($m); "${{a[@]}}"',
            f'{_CAPTURE_RESET} echo "$m"; "$m"',
            f'{_CAPTURE_RESET} echo "$m" `sh`',
            f"{_CAPTURE_RESET} cat <<EOF\n$m\nEOF",
        ],
    )
    def test_anything_else_in_the_command_keeps_the_text_a_command(
        self, command: str, tmp_path: Path
    ) -> None:
        assert not _allowed(command, tmp_path)


class TestAWrittenScriptRunThroughStdinDenies:
    @pytest.mark.parametrize(
        "command",
        [
            f"echo \"$(printf '{_RESET}')\" > s.sh; sh < s.sh",
            f"echo \"$(printf '{_RESET}')\" > s.sh; bash -s < s.sh",
            f"echo \"$(printf '{_RESET}')\" > s.sh; bash < s.sh",
            f"echo \"$(printf '{_RESET}')\" > s.sh; cat s.sh | sh",
            f"echo \"$(printf '{_RESET}')\" > s.sh; cat s.sh | bash",
            f"m=$(printf '{_RESET}'); echo \"$m\" > s.sh; sh < s.sh",
            f"echo '{_RESET}' > s.sh; sh < s.sh",
            f"echo '{_RESET}' > s.sh; cat s.sh | sh",
        ],
    )
    def test_it_is_denied(self, command: str, tmp_path: Path) -> None:
        assert not _allowed(command, tmp_path)


_WRITE_CAPTURED = f"m=$(printf '{_RESET}'); echo \"$m\" > s.sh;"
_WRITE_LITERAL = f"echo '{_RESET}' > s.sh;"


class TestAWrittenScriptReachesTheShellHoweverStdinIsSpelled:
    @pytest.mark.parametrize("write", [_WRITE_CAPTURED, _WRITE_LITERAL])
    @pytest.mark.parametrize(
        "runner",
        [
            "sh 0< s.sh",
            "sh 0<s.sh",
            "sh < ./s.sh",
            "< s.sh sh",
            "<s.sh sh",
            "sh<s.sh",
            "cp s.sh t.sh; sh < t.sh",
            "mv s.sh t.sh; sh < t.sh",
            "exec sh < s.sh",
            "env sh < s.sh",
            "env -i A=1 sh < s.sh",
            "command sh < s.sh",
            "env -u HOME sh < s.sh",
            "env -i < s.sh sh",
            "sh -e < s.sh",
            "bash --noprofile < s.sh",
            "bash -o errexit < s.sh",
            "bash -- < s.sh",
            "bash -s -- < s.sh",
            "bash /dev/stdin < s.sh",
            "cat s.sh - | bash",
        ],
    )
    def test_it_is_denied(self, write: str, runner: str, tmp_path: Path) -> None:
        assert not _allowed(f"{write} {runner}", tmp_path)


class TestAShellThatDoesNotReadTheWrittenFileIsNotFedIt:
    @pytest.mark.parametrize(
        "command",
        [
            f"echo '{_RESET}' > notes.txt; cat notes.txt && bash scripts/qa.sh",
            f"echo '{_RESET}' > notes.txt; cat notes.txt || bash scripts/qa.sh",
            f"echo '{_RESET}' > s.sh; cat s.sh; sh other.sh",
            f"echo '{_RESET}' > s.sh; cat s.sh; bash build.sh",
            f"echo '{_RESET}' > s.sh; bash -n < s.sh",
            f"echo '{_RESET}' > s.sh; sh < other.sh",
            f"echo '{_RESET}' > s.sh; cat s.sh | wc -l",
            f"{_WRITE_LITERAL} cat s.sh; bash build.sh",
            f"{_WRITE_LITERAL} bash -c 'echo hi' < s.sh",
            f"{_WRITE_LITERAL} bash build.sh < s.sh",
            f"{_WRITE_LITERAL} bash -- build.sh < s.sh",
            f"{_WRITE_LITERAL} bash -o errexit build.sh < s.sh",
            f"{_WRITE_LITERAL} cp -r; sh < t.sh",
            f"{_WRITE_LITERAL} cp other.sh t.sh; sh < t.sh",
            f"{_WRITE_LITERAL} sh <",
            "cat README.md && bash scripts/qa.sh",
            "bash -n < a.txt",
            "cp a b; sh setup.sh",
            "printf -v x '%s' hi; echo \"$x\"",
            "sh < s.sh",
            "cat notes.md | less",
            "echo 'git status' > s.sh; cat s.sh | bash",
            f"echo '{_RESET}' > notes.md; cat notes.md | less",
            f"echo '{_RESET}' > s.sh; shellcheck < s.sh",
            f"echo '{_RESET}' > s.sh; sha256sum < s.sh",
        ],
    )
    def test_it_is_allowed(self, command: str, tmp_path: Path) -> None:
        assert _allowed(command, tmp_path)


class TestPrintfDashVAssignsRatherThanPrints:
    @pytest.mark.parametrize(
        "command",
        [
            f'm=$(printf \'{_RESET}\'); printf -v n "$m"; eval "$n"',
            f"printf -v n '%s' '{_RESET}'; $n",
            f"printf -v n '%s' '{_RESET}'; eval \"$n\"",
            f"printf -vn '%s' '{_RESET}'; $n",
            f"printf -vn '%s' '{_RESET}'; eval \"$n\"",
            f"builtin printf -v n '%s' '{_RESET}'; eval \"$n\"",
            f"command printf -v n '%s' '{_RESET}'; eval \"$n\"",
            f"printf -v \"$k\" '%s' '{_RESET}'; eval \"${{!k}}\"",
            f"printf -v; printf -v n '{_RESET}'; eval \"$n\"",
            f'echo "$(printf -v n \'{_RESET}\')"; eval "$n"',
            f"m=$(printf '%s' 'then {_RESET}'); printf -vn '%s' \"$m\"; eval \"$n\"",
            f"m=$(printf '%s' 'then {_RESET}'); builtin printf -v n '%s' \"$m\"; eval \"$n\"",
            f"m=$(printf '%s' 'then {_RESET}'); command printf -v n '%s' \"$m\"; eval \"$n\"",
            f"printf -v n '{_RESET}'; echo \"$n\" | sh",
            f"printf -v n '{_RESET}'; echo \"$n\" > s.sh; sh s.sh",
            f"printf -v n '{_RESET}'; echo \"${{!n}}\"",
            f'printf -v n \'{_RESET}\'; echo "$(eval "$n")"',
            f"printf -v n '{_RESET}'; echo \"$n\"; $n",
        ],
    )
    def test_it_is_denied(self, command: str, tmp_path: Path) -> None:
        assert not _allowed(command, tmp_path)

    @pytest.mark.parametrize(
        "command",
        [
            f"printf -v x '%s' '{_RESET}'",
            f"printf -v x '{_RESET}'; echo done",
            f"printf -vx '%s' '{_RESET}'; echo \"$y\"",
            f"printf -v cmd '{_RESET}'; echo \"$cmd\"",
            f"printf -v cmd '%s' 'run {_RESET} later'; echo \"$cmd\"",
            f"printf -v cmd '%s' '{_RESET}'; echo $cmd | fold -w 40",
        ],
    )
    def test_an_assignment_nothing_expands_is_allowed(self, command: str, tmp_path: Path) -> None:
        assert _allowed(command, tmp_path)


class TestTextFormattersNeverRunTheirInput:
    @pytest.mark.parametrize(
        "formatter",
        [
            "fold -w 40",
            "fmt -w 40",
            "tr a b",
            "cut -c1-40",
            "column -t",
            "nl",
            "expand",
            "unexpand",
            "paste -sd,",
            "rev",
            "tac",
        ],
    )
    @pytest.mark.parametrize("text", [_DELETE, _RESET])
    def test_a_printed_removal_through_a_formatter_is_allowed(
        self, formatter: str, text: str, tmp_path: Path
    ) -> None:
        assert _allowed(f"printf 'run {text}\\n' | {formatter}", tmp_path)

    @pytest.mark.parametrize(
        "receiver",
        [
            "sh",
            "bash",
            "xargs -I{} sh -c '{}'",
            "python3",
            "my-messenger send",
            "fold -w 40 | sh",
            "fold -w 40 | my-messenger send",
            "tac | bash",
        ],
    )
    @pytest.mark.parametrize("text", [_DELETE, _RESET])
    def test_an_executing_or_unknown_receiver_still_denies(
        self, receiver: str, text: str, tmp_path: Path
    ) -> None:
        assert not _allowed(f"printf 'run {text}\\n' | {receiver}", tmp_path)
