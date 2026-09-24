"""Tests for the encrypted-at-rest detector (Plan 00459).

The detector relaxes a security guard, so almost every test here is a way it
must say NO: a lookalike header, plaintext after the armour, a file decrypted
in place, a symlink out of the project, a FIFO, a file too large to verify.
Only a structurally exact whole-file Ansible Vault payload is confirmed.
"""

import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.utils import encrypted_at_rest as ear
from claude_code_hooks_daemon.utils.encrypted_at_rest import AtRestFormat
from tests.vault_payloads import (
    inline_vault_yaml,
    vault_armour,
    vault_file_bytes,
)


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    return root


def _write(root: Path, relpath: str, data: bytes) -> Path:
    target = root / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


class TestWholeFileVaultIsConfirmed:
    def test_format_1_1(self, project: Path) -> None:
        target = _write(project, "group_vars/all/vars.yml", vault_file_bytes())
        assert ear.classify_at_rest(str(target), str(project)) is AtRestFormat.ANSIBLE_VAULT
        assert ear.is_encrypted_at_rest(str(target), str(project)) is True

    def test_format_1_2_with_vault_id_label(self, project: Path) -> None:
        data = vault_file_bytes(version="1.2", label="prod")
        target = _write(project, "vars.yml", data)
        assert ear.is_encrypted_at_rest(str(target), str(project)) is True

    def test_crlf_line_endings(self, project: Path) -> None:
        """Ansible's own parser uses splitlines(), so a CRLF checkout decrypts."""
        target = _write(project, "vars.yml", vault_file_bytes(newline=b"\r\n"))
        assert ear.is_encrypted_at_rest(str(target), str(project)) is True

    def test_no_trailing_newline(self, project: Path) -> None:
        target = _write(project, "vars.yml", vault_file_bytes(trailing_newline=False))
        assert ear.is_encrypted_at_rest(str(target), str(project)) is True

    def test_custom_salt_length(self, project: Path) -> None:
        """VAULT_ENCRYPT_SALT sets an arbitrary salt, so its length is not fixed."""
        target = _write(project, "vars.yml", vault_file_bytes(salt=b"configured-salt"))
        assert ear.is_encrypted_at_rest(str(target), str(project)) is True

    def test_path_object_accepted(self, project: Path) -> None:
        target = _write(project, "vars.yml", vault_file_bytes())
        assert ear.is_encrypted_at_rest(target, project) is True


class TestLookalikesAreNotConfirmed:
    def test_empty_file(self, project: Path) -> None:
        target = _write(project, "vars.yml", b"")
        assert ear.classify_at_rest(str(target), str(project)) is AtRestFormat.NONE

    def test_header_only(self, project: Path) -> None:
        target = _write(project, "vars.yml", b"$ANSIBLE_VAULT;1.1;AES256\n")
        assert ear.is_encrypted_at_rest(str(target), str(project)) is False

    def test_lookalike_header_then_plaintext(self, project: Path) -> None:
        data = b"$ANSIBLE_VAULT;1.1;AES256\ndb_password: hunter2\n"
        target = _write(project, "vars.yml", data)
        assert ear.is_encrypted_at_rest(str(target), str(project)) is False

    def test_lookalike_header_then_a_hex_secret(self, project: Path) -> None:
        """A plaintext hex token is hex, but it is not the vault's inner structure."""
        data = b"$ANSIBLE_VAULT;1.1;AES256\n" + b"0123456789abcdef" * 5 + b"\n"
        target = _write(project, "vars.yml", data)
        assert ear.is_encrypted_at_rest(str(target), str(project)) is False

    def test_plaintext_appended_after_valid_armour(self, project: Path) -> None:
        data = vault_file_bytes() + b"db_password: hunter2\n"
        target = _write(project, "vars.yml", data)
        assert ear.is_encrypted_at_rest(str(target), str(project)) is False

    def test_blank_line_inside_armour(self, project: Path) -> None:
        lines = vault_file_bytes().split(b"\n")
        data = b"\n".join([*lines[:2], b"", *lines[2:]])
        target = _write(project, "vars.yml", data)
        assert ear.is_encrypted_at_rest(str(target), str(project)) is False

    def test_uppercase_hex(self, project: Path) -> None:
        """hexlify() writes lowercase; anything else was not written by Ansible."""
        header, _, rest = vault_file_bytes().partition(b"\n")
        target = _write(project, "vars.yml", header + b"\n" + rest.upper())
        assert ear.is_encrypted_at_rest(str(target), str(project)) is False

    def test_leading_whitespace_before_header(self, project: Path) -> None:
        target = _write(project, "vars.yml", b" " + vault_file_bytes())
        assert ear.is_encrypted_at_rest(str(target), str(project)) is False

    @pytest.mark.parametrize(
        "header",
        [
            b"$ANSIBLE_VAULT;1.0;AES",
            b"$ANSIBLE_VAULT;1.1;AES128",
            b"$ANSIBLE_VAULT;1.2;AES256",
            b"$ANSIBLE_VAULT;1.1;AES256;label",
            b"$ANSIBLE_VAULT;1.2;AES256;two words",
            b"$ANSIBLE_VAULT;9.9;AES256",
            b"$ANSIBLE_VAULT_X;1.1;AES256",
        ],
    )
    def test_malformed_or_unsupported_header(self, project: Path, header: bytes) -> None:
        _, _, rest = vault_file_bytes().partition(b"\n")
        target = _write(project, "vars.yml", header + b"\n" + rest)
        assert ear.is_encrypted_at_rest(str(target), str(project)) is False

    def test_armour_not_decoding_to_three_fields(self, project: Path) -> None:
        from binascii import hexlify

        armour = hexlify(b"00ff\n00ff")
        target = _write(project, "vars.yml", b"$ANSIBLE_VAULT;1.1;AES256\n" + armour + b"\n")
        assert ear.is_encrypted_at_rest(str(target), str(project)) is False

    def test_odd_length_armour(self, project: Path) -> None:
        armour = vault_armour() + b"a"
        target = _write(project, "vars.yml", b"$ANSIBLE_VAULT;1.1;AES256\n" + armour + b"\n")
        assert ear.is_encrypted_at_rest(str(target), str(project)) is False

    def test_binary_non_utf8(self, project: Path) -> None:
        target = _write(project, "vars.yml", b"\xff\xfe\x00\x01" * 32)
        assert ear.is_encrypted_at_rest(str(target), str(project)) is False


class TestTimeOfUse:
    def test_decrypted_in_place_is_not_confirmed_at_the_next_check(self, project: Path) -> None:
        """`ansible-vault decrypt` rewrites the file as plaintext: no cache may survive it."""
        target = _write(project, "vars.yml", vault_file_bytes())
        assert ear.is_encrypted_at_rest(str(target), str(project)) is True

        target.write_bytes(b"db_password: hunter2\n")
        assert ear.is_encrypted_at_rest(str(target), str(project)) is False

        target.write_bytes(vault_file_bytes())
        assert ear.is_encrypted_at_rest(str(target), str(project)) is True


class TestFailsClosed:
    def test_file_over_the_bound(self, project: Path) -> None:
        data = vault_file_bytes()
        target = _write(project, "vars.yml", data)
        with patch.object(ear, "MAX_INSPECTED_BYTES", len(data) - 1):
            assert ear.is_encrypted_at_rest(str(target), str(project)) is False

    def test_file_exactly_at_the_bound(self, project: Path) -> None:
        data = vault_file_bytes()
        target = _write(project, "vars.yml", data)
        with patch.object(ear, "MAX_INSPECTED_BYTES", len(data)):
            assert ear.is_encrypted_at_rest(str(target), str(project)) is True

    def test_missing_file(self, project: Path) -> None:
        assert ear.is_encrypted_at_rest(str(project / "absent.yml"), str(project)) is False

    def test_directory(self, project: Path) -> None:
        (project / "adir").mkdir()
        assert ear.is_encrypted_at_rest(str(project / "adir"), str(project)) is False

    def test_fifo_is_rejected_without_blocking(self, project: Path) -> None:
        fifo = project / "vars.yml"
        os.mkfifo(fifo)
        assert ear.is_encrypted_at_rest(str(fifo), str(project)) is False

    def test_unreadable_file(self, project: Path) -> None:
        target = _write(project, "vars.yml", vault_file_bytes())
        with patch.object(ear.os, "open", side_effect=PermissionError("denied")):
            assert ear.is_encrypted_at_rest(str(target), str(project)) is False

    def test_file_swapped_between_lstat_and_open(self, project: Path) -> None:
        """The inode opened must be the inode inspected."""
        target = _write(project, "vars.yml", vault_file_bytes())
        other = _write(project, "other.yml", vault_file_bytes())
        real_open = os.open

        def swapping_open(path: str, flags: int, *args: int) -> int:
            return real_open(str(other), flags, *args)

        with patch.object(ear.os, "open", side_effect=swapping_open):
            assert ear.is_encrypted_at_rest(str(target), str(project)) is False

    def test_relative_path(self, project: Path) -> None:
        _write(project, "vars.yml", vault_file_bytes())
        assert ear.is_encrypted_at_rest("vars.yml", str(project)) is False

    def test_no_project_root(self, project: Path) -> None:
        target = _write(project, "vars.yml", vault_file_bytes())
        assert ear.is_encrypted_at_rest(str(target), None) is False

    def test_file_outside_the_project(self, tmp_path: Path, project: Path) -> None:
        outside = _write(tmp_path, "elsewhere/vars.yml", vault_file_bytes())
        assert ear.is_encrypted_at_rest(str(outside), str(project)) is False

    def test_symlink_inside_project_to_a_vault_inside_project(self, project: Path) -> None:
        target = _write(project, "real/vars.yml", vault_file_bytes())
        link = project / "alias.yml"
        link.symlink_to(target)
        assert ear.is_encrypted_at_rest(str(link), str(project)) is True

    def test_symlink_to_a_vault_outside_the_project(self, tmp_path: Path, project: Path) -> None:
        outside = _write(tmp_path, "elsewhere/vars.yml", vault_file_bytes())
        link = project / "vars.yml"
        link.symlink_to(outside)
        assert ear.is_encrypted_at_rest(str(link), str(project)) is False

    def test_symlink_named_like_a_vault_pointing_at_plaintext(self, project: Path) -> None:
        plaintext = _write(project, "notes.txt", b"db_password: hunter2\n")
        link = project / "vars.yml"
        link.symlink_to(plaintext)
        assert ear.is_encrypted_at_rest(str(link), str(project)) is False

    def test_dangling_symlink(self, project: Path) -> None:
        link = project / "vars.yml"
        link.symlink_to(project / "gone.yml")
        assert ear.is_encrypted_at_rest(str(link), str(project)) is False

    def test_mode_is_irrelevant_to_the_verdict(self, project: Path) -> None:
        target = _write(project, "vars.yml", vault_file_bytes())
        target.chmod(stat.S_IRUSR)
        assert ear.is_encrypted_at_rest(str(target), str(project)) is True


class TestInlineVaultValues:
    def test_inline_values_are_classified_but_not_confirmed(self, project: Path) -> None:
        """Plaintext keys (and maybe plaintext values) sit beside the vaulted ones."""
        target = _write(project, "vars.yml", inline_vault_yaml())
        assert ear.classify_at_rest(str(target), str(project)) is AtRestFormat.ANSIBLE_VAULT_INLINE
        assert ear.is_encrypted_at_rest(str(target), str(project)) is False

    def test_plain_yaml_is_none(self, project: Path) -> None:
        target = _write(project, "vars.yml", b"db_password: hunter2\n")
        assert ear.classify_at_rest(str(target), str(project)) is AtRestFormat.NONE

    def test_vault_tag_without_a_vault_block_is_none(self, project: Path) -> None:
        target = _write(project, "vars.yml", b"note: the !vault | tag is used elsewhere\n")
        assert ear.classify_at_rest(str(target), str(project)) is AtRestFormat.NONE

    def test_inline_file_over_the_bound_is_none(self, project: Path) -> None:
        data = inline_vault_yaml()
        target = _write(project, "vars.yml", data)
        with patch.object(ear, "MAX_INSPECTED_BYTES", len(data) - 1):
            assert ear.classify_at_rest(str(target), str(project)) is AtRestFormat.NONE
