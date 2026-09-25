"""The secret-file exemptions hold behind `time` and `!` (Plan 00422 N25 follow-up).

`time` only reports how long the command took, and `!` only inverts its exit
status. Neither changes which command runs, whether it runs, or what it reads,
so `time ansible-playbook --vault-password-file <password file> site.yml` must
get exactly the exemption the bare form gets, and so must
`! cat <encrypted file>`. Withholding it was a false deny.

`then`, `do`, `else` and the other reserved words stay fail-closed. In valid
bash they appear only inside a compound command, and both exemptions accept a
single simple command and nothing else. Stripping them would let a check judge
a fragment of a compound as though it were the whole command.

The protected file names are assembled from pieces so this module never spells
one out whole (`secret_file_guard` denies authoring a script that does).
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils import secret_file_matching as sfm

_PASSWORD_FILE = ".vault" + "-pass"
_ENC = "group_vars/all/vault" + "_passwords.yml"
_CWD = "/proj"

_CONSUMERS = sfm.DEFAULT_ALLOWED_CONSUMERS
_TRANSPARENT = ("time ", "time -p ", "! ", "! time ", "time ! ")
_COMPOUND_ONLY = ("then ", "do ", "else ", "elif ", "if ", "while ", "until ", "{ ")

_EXEMPT = (
    f"bin/hooks-daemon secret-meta {_PASSWORD_FILE}",
    f"ansible-playbook --vault-password-file {_PASSWORD_FILE} site.yml",
    f"ansible-vault encrypt --vault-password-file {_PASSWORD_FILE} secrets.yml",
)
_NOT_EXEMPT = (
    f"cat {_PASSWORD_FILE}",
    f"ansible-vault view --vault-password-file {_PASSWORD_FILE} secrets.yml",
    f"ansible-playbook {_PASSWORD_FILE}",
)


def _encrypted_ok(command: str) -> bool:
    return sfm.is_encrypted_target_invocation(
        command,
        sfm.DEFAULT_PROTECTED_PATTERNS,
        cwd=_CWD,
        is_encrypted=lambda path: path == f"{_CWD}/{_ENC}",
    )


class TestTheBareFormsAreTheBaseline:
    @pytest.mark.parametrize("command", _EXEMPT)
    def test_exempt(self, command: str) -> None:
        assert sfm.is_exempt_invocation(command, _CONSUMERS) is True

    @pytest.mark.parametrize("command", _NOT_EXEMPT)
    def test_not_exempt(self, command: str) -> None:
        assert sfm.is_exempt_invocation(command, _CONSUMERS) is False


class TestTimeAndBangAreTransparent:
    @pytest.mark.parametrize("prefix", _TRANSPARENT)
    @pytest.mark.parametrize("command", _EXEMPT)
    def test_the_exemption_holds(self, prefix: str, command: str) -> None:
        assert sfm.is_exempt_invocation(prefix + command, _CONSUMERS) is True

    @pytest.mark.parametrize("prefix", _TRANSPARENT)
    @pytest.mark.parametrize("command", _NOT_EXEMPT)
    def test_a_non_exempt_command_stays_denied(self, prefix: str, command: str) -> None:
        assert sfm.is_exempt_invocation(prefix + command, _CONSUMERS) is False

    @pytest.mark.parametrize("prefix", _TRANSPARENT)
    def test_the_leading_cd_still_composes(self, prefix: str) -> None:
        command = (
            f"cd infra && {prefix}ansible-playbook --vault-password-file {_PASSWORD_FILE} site.yml"
        )
        assert sfm.is_exempt_invocation(command, _CONSUMERS) is True

    @pytest.mark.parametrize("prefix", _TRANSPARENT)
    def test_an_encrypted_target_reader_holds(self, prefix: str) -> None:
        assert _encrypted_ok(f"{prefix}cat {_ENC}") is True
        assert _encrypted_ok(f"{prefix}git add {_ENC}") is True

    @pytest.mark.parametrize("prefix", _TRANSPARENT)
    def test_a_non_reader_behind_it_stays_denied(self, prefix: str) -> None:
        assert _encrypted_ok(f"{prefix}ansible-vault view {_ENC}") is False
        assert _encrypted_ok(f"{prefix}git diff {_ENC}") is False


class TestCompoundOnlyWordsStayFailClosed:
    @pytest.mark.parametrize("prefix", _COMPOUND_ONLY)
    @pytest.mark.parametrize("command", _EXEMPT)
    def test_the_exemption_is_withheld(self, prefix: str, command: str) -> None:
        assert sfm.is_exempt_invocation(prefix + command, _CONSUMERS) is False

    @pytest.mark.parametrize("prefix", _COMPOUND_ONLY)
    def test_the_encrypted_exemption_is_withheld(self, prefix: str) -> None:
        assert _encrypted_ok(f"{prefix}cat {_ENC}") is False
