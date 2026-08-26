"""secret-meta core (Plan 00272 Phase 5): metadata about a protected file, never content.

The ``bin/hooks-daemon secret-meta <path>`` helper is the ONE sanctioned way
to inspect a protected file: existence, bucketed size, mtime, permissions and
a keyed digest. Design points (PLAN.md Decisions 2/6/9, draft-review
finding 5):

- **Keyed HMAC-SHA256 by default.** A plain sha256 of a low-entropy secret is
  an offline-crackable commitment once it lands in a transcript. The HMAC key
  is per-project, generated on first use, gitignored (it lives under
  ``untracked/``), owner-only (0600) — and ITSELF a protected file
  (``*.secret*`` naming, see :data:`KEY_FILE_NAME`).
- **Bucketed size by default.** Exact byte length is the single most valuable
  disclosure to an offline cracker of a passphrase file; ``size_bucket``
  answers "did it change?" without it. Exact ``size_bytes`` and plain
  ``sha256`` appear only behind ``allow_plain_hash``.
- **A permissive key refuses to sign.** A group/world-readable key is a
  compromised key; emitting a digest under it would be signing with a key an
  attacker may hold.
- **No route to any backstop-internal digest** (Decision 6): this module
  computes only the whole-file digest; no prefix/rolling digests exist here,
  so the CLI cannot be used as a byte-by-byte extraction oracle.

Also carries the Task 6.1 cheaply-shippable OS-boundary piece: the output
flags a group/world-readable protected file with a ``chmod 600`` hint.
"""

import hashlib
import hmac
import os
import secrets
import stat
from pathlib import Path
from typing import Any, Final

# Key file name deliberately matches the shipped `*.secret*` protected glob,
# so the key is guarded by the same handler whose helper uses it.
KEY_FILE_NAME: Final[str] = "secret-meta.key.secret"

_KEY_LENGTH_BYTES: Final[int] = 32
_OWNER_ONLY_MODE: Final[int] = 0o600
# Any group/other permission bit set means the file is readable or writable
# beyond its owner — the hygiene threshold for both key and secret.
_GROUP_OTHER_BITS: Final[int] = 0o077

# Size buckets (upper bounds, bytes): coarse enough to deny an offline
# cracker a useful length, fine enough to answer "did it change class?".
_SIZE_BUCKET_BOUNDS: Final[tuple[int, ...]] = (64, 256, 1024, 4096, 65536)
_SIZE_BUCKET_OVERFLOW_LABEL: Final[str] = ">65536B"

_CHMOD_HINT: Final[str] = "run: chmod 600 <path> (owner read/write only)"


def _size_bucket(size: int) -> str:
    for bound in _SIZE_BUCKET_BOUNDS:
        if size <= bound:
            return f"<={bound}B"
    return _SIZE_BUCKET_OVERFLOW_LABEL


def _ensure_key(key_path: Path) -> bytes | None:
    """Load (or create, owner-only) the HMAC key; None when unusable.

    Returns None when the key file exists but is group/world-accessible —
    a compromised key must never sign.
    """
    if key_path.exists():
        mode = stat.S_IMODE(key_path.stat().st_mode)
        if mode & _GROUP_OTHER_BITS:
            return None
        return key_path.read_bytes()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(_KEY_LENGTH_BYTES)
    try:
        descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _OWNER_ONLY_MODE)
    except FileExistsError:
        # Two concurrent first uses raced on O_EXCL; the loser adopts the
        # winner's key so both report the same digest (review finding 7).
        return _ensure_key(key_path)
    try:
        os.write(descriptor, key)
    finally:
        os.close(descriptor)
    return key


def collect_secret_meta(
    path: Path | str,
    *,
    key_path: Path,
    allow_plain_hash: bool = False,
) -> dict[str, Any]:
    """Metadata JSON-able dict for ``path``. NEVER includes content bytes.

    The file's bytes are read only to compute digests and are held in memory
    transiently (best-effort in Python); they never appear in the result.
    """
    target = Path(path)
    result: dict[str, Any] = {"path": str(target), "exists": target.exists()}
    if not result["exists"]:
        return result
    if target.is_dir():
        # A directory has no content to digest; report it plainly rather
        # than crashing on read_bytes (review finding 7).
        result["error"] = "path is a directory, not a file"
        return result

    file_stat = target.stat()
    mode = stat.S_IMODE(file_stat.st_mode)
    result["mtime"] = int(file_stat.st_mtime)
    result["mode"] = format(mode, "04o")
    permissions_ok = not mode & _GROUP_OTHER_BITS
    result["permissions_ok"] = permissions_ok
    if not permissions_ok:
        result["permissions_hint"] = _CHMOD_HINT

    try:
        content = target.read_bytes()
    except PermissionError:
        # A permission problem is exactly what this tool exists to REPORT —
        # the mode/permissions fields above still stand (review finding 7).
        result["error"] = "permission denied reading the file (metadata above still valid)"
        return result
    if allow_plain_hash:
        result["size_bytes"] = len(content)
        result["sha256"] = hashlib.sha256(content).hexdigest()
    else:
        result["size_bucket"] = _size_bucket(len(content))

    key = _ensure_key(key_path)
    if key is None:
        result["digest"] = None
        result["digest_refused"] = (
            "HMAC key file is group/world-accessible; refusing to sign with a "
            f"potentially compromised key ({_CHMOD_HINT.replace('<path>', str(key_path))})"
        )
    else:
        result["digest"] = hmac.new(key, content, hashlib.sha256).hexdigest()
    return result
