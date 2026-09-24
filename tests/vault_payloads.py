"""Spec-shaped Ansible Vault payloads for tests (Plan 00459).

Built exactly the way the vendored Ansible source builds one --
``format_vaulttext_envelope`` for the header and 80-column armour, and
``VaultAES256.encrypt`` for what the armour encodes
(``hexlify(salt) \\n hexlify(hmac) \\n hexlify(ciphertext)``, hexlified again).
See ``remote-docs/raw.githubusercontent.com/ansible/ansible/devel/lib/ansible/
parsing/vault/__init__.py.md``.

Nothing is actually encrypted: the salt, HMAC and "ciphertext" are fixed
dummy bytes. The detector under test judges SHAPE, so a structurally exact
payload is what it needs, and a deterministic one keeps failures readable.
"""

from binascii import hexlify
from typing import Final

HEADER_FORMAT_ID: Final[bytes] = b"$ANSIBLE_VAULT"
CIPHER_NAME: Final[bytes] = b"AES256"
ARMOUR_WIDTH: Final[int] = 80

#: HMAC-SHA256 digest size, and the AES block size PKCS7 pads the plaintext to.
HMAC_BYTES: Final[int] = 32
AES_BLOCK_BYTES: Final[int] = 16

#: Ansible's default salt is ``os.urandom(32)``.
DEFAULT_SALT: Final[bytes] = bytes(range(32))


def vault_armour(*, salt: bytes = DEFAULT_SALT, ciphertext_blocks: int = 2) -> bytes:
    """The hex armour (no header, no line breaks) of a dummy vault payload."""
    hmac = bytes((index * 7) % 256 for index in range(HMAC_BYTES))
    ciphertext = bytes(
        (index * 13 + 5) % 256 for index in range(AES_BLOCK_BYTES * ciphertext_blocks)
    )
    inner = b"\n".join([hexlify(salt), hexlify(hmac), hexlify(ciphertext)])
    return hexlify(inner)


def vault_file_bytes(
    *,
    version: str = "1.1",
    label: str | None = None,
    salt: bytes = DEFAULT_SALT,
    ciphertext_blocks: int = 2,
    newline: bytes = b"\n",
    trailing_newline: bool = True,
) -> bytes:
    """A whole-file vault payload: header line, then 80-column hex armour."""
    header_parts = [HEADER_FORMAT_ID, version.encode(), CIPHER_NAME]
    if label is not None:
        header_parts.append(label.encode())
    armour = vault_armour(salt=salt, ciphertext_blocks=ciphertext_blocks)
    lines = [b";".join(header_parts)]
    lines += [armour[start : start + ARMOUR_WIDTH] for start in range(0, len(armour), ARMOUR_WIDTH)]
    if trailing_newline:
        lines.append(b"")
    return newline.join(lines)


def inline_vault_yaml() -> bytes:
    """A YAML vars file with one ``!vault |`` value beside a plaintext key."""
    body = vault_file_bytes().decode().splitlines()
    indented = "\n".join(f"  {line}" for line in body)
    return f"db_user: app\ndb_password: !vault |\n{indented}\n".encode()
