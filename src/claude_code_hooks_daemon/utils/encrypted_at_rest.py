"""Is this protected file's content encrypted at rest? (Plan 00459)

``secret_file_guard`` and ``secret_file_hygiene_checker`` select files by
NAME, and a name cannot tell an Ansible Vault password file (plaintext, must
stay hidden) from an encrypted vars file whose name describes what it holds
(ciphertext, committing it is the point of Vault). The content can. This is
the ONE definition of that check; both handlers call it.

**What is confirmed.** Only a whole-file Ansible Vault payload, per the
format the vendored Ansible source writes (``format_vaulttext_envelope`` and
``VaultAES256.encrypt`` in
``remote-docs/raw.githubusercontent.com/ansible/ansible/devel/lib/ansible/
parsing/vault/__init__.py.md``): a ``$ANSIBLE_VAULT;1.1;AES256`` (or
``;1.2;AES256;<label>``) header, then lowercase hex armour that decodes to
``hex(salt) \\n hex(hmac-sha256) \\n hex(block-padded ciphertext)``. The WHOLE
file is verified, so plaintext appended after valid armour is not confirmed.
YAML carrying inline ``!vault |`` values is recognised separately and is NOT
confirmed: its keys, and possibly other values, are plaintext.

**Fails closed.** Anything this module cannot positively verify answers
``NONE``: a relative path, no project root, a realpath outside the project, a
non-regular file, a file over ``MAX_INSPECTED_BYTES``, an ``OSError``, a
malformed header or body. ``NONE`` means "keep protecting it".

**Checked at time of use, never cached.** ``ansible-vault decrypt`` rewrites
the file in place as plaintext, and the very next check must see that.

**Content never leaves.** The bytes read are judged here and dropped; only
the format enum is returned, and nothing but an exception class name is
logged.
"""

import logging
import os
import re
import stat
from binascii import Error as BinasciiError
from binascii import unhexlify
from enum import StrEnum
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

#: Largest file inspected. The armour is hex of (mostly) hex, so roughly four
#: bytes on disk per byte of plaintext: this admits about 1 MiB of vaulted
#: data. A larger file is not verified, and so not confirmed.
MAX_INSPECTED_BYTES: Final[int] = 4 * 1024 * 1024

# `O_NOFOLLOW` because the path opened is already the realpath, so a symlink
# there means the tree changed under us. `O_NONBLOCK` because opening a FIFO
# for reading blocks until a writer appears, and a FIFO swapped in after the
# `lstat` would otherwise hang a PreToolUse handler; it has no effect on a
# regular file.
_OPEN_FLAGS: Final[int] = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC

_READ_CHUNK_BYTES: Final[int] = 64 * 1024

#: Format 1.1 never carries a vault-id label; 1.2 always does (Ansible picks
#: 1.2 only for a non-default vault id). ``1.0;AES`` is read-only legacy and
#: is deliberately not accepted.
_HEADER_RE: Final[re.Pattern[bytes]] = re.compile(
    rb"\$ANSIBLE_VAULT;(?:1\.1;AES256|1\.2;AES256;[^\s;]+)"
)

#: ``hexlify()`` writes lowercase.
_ARMOUR_LINE_RE: Final[re.Pattern[bytes]] = re.compile(rb"[0-9a-f]+")

#: What the armour decodes to: salt of any non-empty length (``VAULT_ENCRYPT_
#: SALT`` may set one), a SHA-256 HMAC (32 bytes, 64 hex), and ciphertext
#: PKCS7-padded to the 16-byte AES block (32 hex per block).
_ARMOUR_PAYLOAD_RE: Final[re.Pattern[bytes]] = re.compile(
    rb"(?:[0-9a-f]{2})+\n[0-9a-f]{64}\n(?:[0-9a-f]{32})+"
)

#: A YAML value tagged ``!vault |`` (any block-scalar indicator) whose first
#: content line is an indented vault header.
_INLINE_VAULT_RE: Final[re.Pattern[bytes]] = re.compile(
    rb"!vault[ \t]*\|[-+0-9]*[ \t]*\r?\n[ \t]+\$ANSIBLE_VAULT;"
)


class AtRestFormat(StrEnum):
    """What a file's content was confirmed to be."""

    ANSIBLE_VAULT = "ansible-vault"
    """A whole-file Ansible Vault payload: nothing in it is plaintext."""

    ANSIBLE_VAULT_INLINE = "ansible-vault-inline"
    """YAML with inline ``!vault`` values: NOT safe to treat as ciphertext."""

    NONE = "none"
    """Not confirmed as either: treat as plaintext."""


def is_encrypted_at_rest(
    path: str | os.PathLike[str], project_root: str | os.PathLike[str] | None
) -> bool:
    """True only when ``path`` is confirmed to be a whole-file vault payload."""
    return classify_at_rest(path, project_root) is AtRestFormat.ANSIBLE_VAULT


def classify_at_rest(
    path: str | os.PathLike[str], project_root: str | os.PathLike[str] | None
) -> AtRestFormat:
    """Classify ``path``'s content, failing closed to ``NONE``.

    ``path`` must be absolute (a relative one would resolve against the
    DAEMON's working directory, not the caller's), and its realpath must lie
    inside ``project_root``.
    """
    data = _read_bounded(path, project_root)
    if data is None:
        return AtRestFormat.NONE
    if _is_whole_file_vault(data):
        return AtRestFormat.ANSIBLE_VAULT
    if _INLINE_VAULT_RE.search(data):
        return AtRestFormat.ANSIBLE_VAULT_INLINE
    return AtRestFormat.NONE


def _read_bounded(
    path: str | os.PathLike[str], project_root: str | os.PathLike[str] | None
) -> bytes | None:
    """The whole file's bytes, or ``None`` when any precondition fails."""
    if project_root is None or not Path(path).is_absolute():
        return None
    try:
        real = Path(os.path.realpath(path))
        if not real.is_relative_to(os.path.realpath(project_root)):
            return None
        before = os.lstat(real)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_INSPECTED_BYTES:
            return None
        descriptor = os.open(real, _OPEN_FLAGS)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
                before.st_dev,
                before.st_ino,
            ):
                return None
            return _read_at_most(descriptor, MAX_INSPECTED_BYTES)
        finally:
            os.close(descriptor)
    except OSError as exc:
        # Unreadable, vanished, or raced: all mean "not confirmed", which keeps
        # the file protected. The class name only -- never the path's content.
        logger.debug("encrypted-at-rest check failed closed: %s", type(exc).__name__)
        return None


def _read_at_most(descriptor: int, limit: int) -> bytes | None:
    """Read to EOF, or ``None`` if the file holds more than ``limit`` bytes.

    ``st_size`` was already checked, but the file can grow between that stat
    and this read, so the bound is enforced on what is actually read.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor, _READ_CHUNK_BYTES)
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)


def _is_whole_file_vault(data: bytes) -> bool:
    """True when every line of ``data`` belongs to one vault payload."""
    lines = data.splitlines()
    if len(lines) < 2 or not _HEADER_RE.fullmatch(lines[0]):
        return False
    armour_lines = lines[1:]
    if not all(_ARMOUR_LINE_RE.fullmatch(line) for line in armour_lines):
        return False
    try:
        payload = unhexlify(b"".join(armour_lines))
    except BinasciiError:
        return False
    return _ARMOUR_PAYLOAD_RE.fullmatch(payload) is not None
