"""Venv metadata schema and lock-hash helpers (Plan 00100 Phase 3).

This module intentionally lives separately from :mod:`paths` because
``paths.py`` is invoked as a bare script at install time (via
``scripts/install/venv_resolver.sh``) using the host's ``python3``, which
only carries the standard library. Pulling Pydantic into ``paths`` at
module load would break that stdlib-only guarantee. All Pydantic-dependent
metadata code is confined here so it is only imported from contexts where
the daemon venv exists and Pydantic is already installed.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)


_DAEMON_METADATA_FILENAME = ".daemon-metadata.json"
_LOCK_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_DAEMON_VERSION_RE = re.compile(r"^v\d+\.\d+\.\d+$")


class DaemonVenvMetadata(BaseModel):
    """Installer-time venv metadata persisted atomically inside each venv.

    Written on venv creation; read by the daemon on every startup so the
    resolver can use ``python_path`` authoritatively and compare
    ``lock_hash`` against the current project state to decide stale/fresh.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    python_path: str = Field(min_length=1)
    fingerprint: str = Field(min_length=1)
    lock_hash: str
    daemon_version: str
    written_at: str

    @field_validator("python_path")
    @classmethod
    def _python_path_must_be_absolute(cls, value: str) -> str:
        if not Path(value).is_absolute():
            raise ValueError("python_path must be an absolute path")
        return value

    @field_validator("lock_hash")
    @classmethod
    def _lock_hash_must_be_sha256_prefixed(cls, value: str) -> str:
        if not _LOCK_HASH_RE.fullmatch(value):
            raise ValueError("lock_hash must be 'sha256:<64 lowercase hex>'")
        return value

    @field_validator("daemon_version")
    @classmethod
    def _daemon_version_must_be_v_prefixed(cls, value: str) -> str:
        if not _DAEMON_VERSION_RE.fullmatch(value):
            raise ValueError("daemon_version must match 'vMAJOR.MINOR.PATCH'")
        return value

    @field_validator("written_at")
    @classmethod
    def _written_at_must_be_iso8601(cls, value: str) -> str:
        candidate = value.replace("Z", "+00:00") if value.endswith("Z") else value
        try:
            datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise ValueError("written_at must be ISO 8601") from exc
        return value


def write_daemon_metadata(venv_dir: Path | str, meta: DaemonVenvMetadata) -> None:
    """Atomically persist metadata to ``{venv_dir}/.daemon-metadata.json``.

    Writes to a sibling ``.tmp`` file and ``os.replace``s it into final
    position so readers never observe a half-written file. Caller owns
    the venv directory layout — if ``venv_dir`` does not exist, the
    write raises; we do not silently create missing parents.
    """
    venv_path = Path(venv_dir)
    if not venv_path.is_dir():
        raise FileNotFoundError(f"venv dir does not exist: {venv_path}")
    final_path = venv_path / _DAEMON_METADATA_FILENAME
    tmp_path = venv_path / f"{_DAEMON_METADATA_FILENAME}.tmp"
    tmp_path.write_text(meta.model_dump_json())
    os.replace(tmp_path, final_path)


def read_daemon_metadata(venv_dir: Path | str) -> DaemonVenvMetadata | None:
    """Return the metadata if present and valid, else ``None``.

    Any unusable state — missing file, empty file, malformed JSON,
    schema-mismatch — collapses to ``None``. Callers interpret ``None``
    as "treat this venv as stale and rebuild"; the function never raises
    for ordinary "no metadata" conditions.
    """
    candidate = Path(venv_dir) / _DAEMON_METADATA_FILENAME
    if not candidate.is_file():
        return None
    try:
        raw = candidate.read_text()
    except OSError as exc:
        # A present-but-unreadable file (permission / I/O error) is still an
        # "unusable metadata" condition, not a fatal one. Returning None keeps
        # the documented contract ("never raises for ordinary no-metadata
        # conditions") and matches the byte-for-byte stdlib mirror
        # ``_read_venv_metadata_stdlib`` in paths.py, which also guards
        # ``read_text`` with ``except OSError: return None``.
        logger.debug("metadata at %s could not be read: %s", candidate, exc)
        return None
    if not raw.strip():
        return None
    try:
        return DaemonVenvMetadata.model_validate_json(raw)
    except (ValidationError, ValueError) as exc:
        logger.debug("metadata at %s failed schema validation: %s", candidate, exc)
        return None


_PYPROJECT_FILENAME = "pyproject.toml"
_UV_LOCK_FILENAME = "uv.lock"
_UV_LOCK_ABSENT_MARKER = b"\x00no-uv-lock\x00"


def compute_project_lock_hash(project_root: Path | str) -> str:
    """Return ``sha256:<64-hex>`` summarising the project's lock inputs.

    Inputs: ``pyproject.toml`` (required) and ``uv.lock`` (optional). The
    presence vs absence of ``uv.lock`` must be reflected in the hash — a
    sentinel marker stands in for the missing file so a freshly-generated
    ``uv.lock`` always flips the hash even if ``pyproject.toml`` is
    unchanged.

    NOTE: this algorithm is a byte-for-byte mirror of
    ``paths._compute_project_lock_hash_stdlib``. The two MUST stay identical —
    ``ensure_venv`` writes the lock_hash via this function and reads/compares it
    via the stdlib mirror, so any change here must be applied there too.

    Raises:
        FileNotFoundError: if ``pyproject.toml`` does not exist.
    """
    root = Path(project_root)
    pyproject = root / _PYPROJECT_FILENAME
    if not pyproject.is_file():
        raise FileNotFoundError(f"pyproject.toml missing at {pyproject}")
    hasher = hashlib.sha256()
    hasher.update(pyproject.read_bytes())
    uv_lock = root / _UV_LOCK_FILENAME
    if uv_lock.is_file():
        hasher.update(uv_lock.read_bytes())
    else:
        hasher.update(_UV_LOCK_ABSENT_MARKER)
    return f"sha256:{hasher.hexdigest()}"
