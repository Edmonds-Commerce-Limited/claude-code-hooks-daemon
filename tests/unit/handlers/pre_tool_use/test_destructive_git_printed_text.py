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


class TestAWrittenScriptReachesTheShellHoweverStdinIsSpelled:
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
    def test_it_is_denied(self, runner: str, tmp_path: Path) -> None:
        assert not _allowed(f"{_WRITE_CAPTURED} {runner}", tmp_path)


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
            f"{_WRITE_CAPTURED} cat s.sh; bash build.sh",
            f"{_WRITE_CAPTURED} bash -c 'echo hi' < s.sh",
            f"{_WRITE_CAPTURED} bash build.sh < s.sh",
            f"{_WRITE_CAPTURED} bash -- build.sh < s.sh",
            f"{_WRITE_CAPTURED} bash -o errexit build.sh < s.sh",
            f"{_WRITE_CAPTURED} cp -r; sh < t.sh",
            f"{_WRITE_CAPTURED} cp other.sh t.sh; sh < t.sh",
            f'{_WRITE_CAPTURED} env "$w" sh < s.sh',
            f'{_WRITE_CAPTURED} sh "$script" < s.sh',
            f"{_WRITE_CAPTURED} sh <",
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
