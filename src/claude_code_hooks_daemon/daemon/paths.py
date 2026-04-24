"""
Path management for daemon Unix socket and PID files.

Generates unique socket and PID file paths based on project directory,
enabling multi-project daemon isolation.

SECURITY: All runtime files stored in daemon's untracked directory,
not /tmp, to prevent security vulnerabilities.
"""

import argparse
import contextlib
import hashlib
import json
import logging
import os
import platform
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# AF_UNIX socket path limit (108 bytes on Linux, 104 bytes on macOS)
# Use conservative limit for cross-platform compatibility
_UNIX_SOCKET_PATH_LIMIT = 104


def _get_hostname_suffix() -> str:
    """
    Get hostname-based suffix for runtime files.

    Uses HOSTNAME environment variable directly to isolate daemon runtime
    files across different environments (containers, machines).

    Returns:
        "-{sanitized-hostname}" or "-{time-hash}" if no hostname

    Example:
        HOSTNAME="laptop" -> "-laptop"
        HOSTNAME="506355bfbc76" -> "-506355bfbc76"
        HOSTNAME="My-Server" -> "-my-server"
        No HOSTNAME -> "-a1b2c3d4" (MD5 of timestamp)
    """
    hostname = os.environ.get("HOSTNAME", "")

    # No hostname? Use MD5 of current time for uniqueness
    if not hostname:
        import time

        timestamp = str(time.time())
        hash_obj = hashlib.md5(timestamp.encode("utf-8"), usedforsecurity=False)
        return f"-{hash_obj.hexdigest()[:8]}"

    # Sanitize hostname for filesystem safety: lowercase, no spaces
    sanitized = hostname.lower().replace(" ", "-")
    return f"-{sanitized}"


# Plan 00100 Task 3.0.5: filesystem-safe chars for the project path slug.
# Anything outside this alphabet is stripped after path-separator substitution.
_SLUG_SAFE_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
# Slug is truncated to this total length; longer paths get ``36 + "-" + 4-hex`` = 41.
_SLUG_MAX_LEN = 40
_SLUG_TRUNCATED_PREFIX_LEN = 36
_SLUG_TRUNCATED_HASH_LEN = 4


def project_path_slug(root: str | Path) -> str:
    """Return a filesystem-safe slug derived from the project root path.

    Purpose: distinguish venvs for the same Python interpreter viewed from
    different project roots. The same image may be opened as both a host
    (``/home/dev/proj``) and a container (``/workspace``); the Python
    fingerprint alone matches but each view needs its own venv.

    Algorithm:
        1. Resolve to absolute path, coerce to string.
        2. Strip leading ``/``; replace remaining ``/`` with ``_``.
        3. Remove any character not in ``[A-Za-z0-9_-]``.
        4. If length > 40: keep first 36 chars + ``-`` + 4-hex md5 suffix
           computed on the full original absolute path (deterministic
           disambiguator for pathological paths sharing a long common prefix).

    Examples::

        project_path_slug("/workspace")         -> "workspace"
        project_path_slug("/home/user/proj")    -> "home_user_proj"
        project_path_slug("/a/b/c/.../very/long") -> 36 chars + "-" + 4 hex

    MD5 is used for a short path-identifier only (``usedforsecurity=False``).
    """
    abs_path = str(Path(root).resolve())
    stripped = abs_path.lstrip("/")
    if not stripped:
        stripped = "root"
    replaced = stripped.replace("/", "_")
    safe = "".join(ch for ch in replaced if ch in _SLUG_SAFE_CHARS)
    if not safe:
        safe = "root"
    if len(safe) > _SLUG_MAX_LEN:
        suffix = hashlib.md5(abs_path.encode("utf-8"), usedforsecurity=False).hexdigest()[
            :_SLUG_TRUNCATED_HASH_LEN
        ]
        safe = safe[:_SLUG_TRUNCATED_PREFIX_LEN] + "-" + suffix
    return safe


def python_venv_fingerprint(root: str | Path | None = None) -> str:
    """Return a stable per-Python-environment fingerprint for venv keying.

    Components hashed (separator ``|``):
    - ``sys.version`` (catches patch version + build-tag differences)
    - ``sys.base_prefix`` (distinguishes pyenv vs distro vs other installs)
    - ``platform.machine()`` (distinguishes architectures cross-mounted)

    ``sys.base_prefix`` is deliberately used in place of ``sys.executable``
    so that the fingerprint is stable whether computed from the system
    Python (during fresh install, before a venv exists) or from the venv
    Python (once the daemon is running). Both share the same base prefix
    (``/usr``, ``/home/user/.pyenv/versions/3.11.5``, etc.).

    Concurrent containers from the same image produce the same fingerprint
    and share one venv. Distinct Pythons (pyenv vs distro, different minor
    versions, different arches) produce distinct fingerprints and get
    distinct venvs.

    When ``root`` is provided, the project path slug (see
    :func:`project_path_slug`) is prepended to disambiguate host-vs-container
    views of the same Python interpreter on the same filesystem.

    Format (no root):   ``py{MM}-{8-hex}``           e.g. ``py311-2fa8b3c1``
    Format (with root): ``{slug}-py{MM}-{8-hex}``    e.g. ``workspace-py311-2fa8b3c1``

    MD5 is used for short path-identifier purposes only (``usedforsecurity=False``).
    """
    parts = f"{sys.version}|{sys.base_prefix}|{platform.machine()}"
    digest = hashlib.md5(parts.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    py_fp = f"py{sys.version_info.major}{sys.version_info.minor}-{digest}"
    if root is None:
        return py_fp
    return f"{project_path_slug(root)}-{py_fp}"


# ----------------------------------------------------------------------
# Plan 00100 Phase 3: atomic metadata persistence lives in a sibling module
# (``metadata.py``) because ``paths.py`` is invoked as a bare script at
# install time with the host's stdlib-only ``python3``. Pulling Pydantic
# in here would break that guarantee — so the schema, persistence and
# lock-hash helpers all live in ``metadata.py`` and are imported only by
# callers that run under the daemon venv.
#
# The two ``_stdlib`` helpers below (``_read_venv_metadata_stdlib`` and
# ``_compute_project_lock_hash_stdlib``) exist solely so that
# ``resolve_existing_venv_python_with_diagnostics`` — which runs under
# bare-stdlib ``python3`` at install time — can perform metadata-driven
# resolution without touching Pydantic. They mirror the schema-field
# names and hash algorithm from ``metadata.py`` byte-for-byte; any change
# to ``metadata.DaemonVenvMetadata`` or ``metadata.compute_project_lock_hash``
# MUST be reflected here.
# ----------------------------------------------------------------------

_DAEMON_METADATA_FILENAME = ".daemon-metadata.json"
_PYPROJECT_FILENAME = "pyproject.toml"
_UV_LOCK_FILENAME = "uv.lock"
_UV_LOCK_ABSENT_MARKER = b"\x00no-uv-lock\x00"
_REQUIRED_METADATA_KEYS = ("python_path", "lock_hash")

# Plan 00099 v3.1.1 wrote ``.daemon-version`` into every provisioned venv as
# a simple upgrade marker. Plan 00100 Phase 3 supersedes that stamp with the
# richer ``.daemon-metadata.json`` (Pydantic-validated, lock-hash-indexed).
# A venv that still carries the legacy stamp but lacks the new metadata file
# is a pre-Phase-3 leftover — returning it from the resolver would hand the
# daemon a venv whose dependency state is unknown relative to the current
# pyproject.toml/uv.lock. Task 3.5 refuses those venvs so the next
# ``ensure_venv`` cycle rebuilds cleanly; Task 3.9 adds eager removal.
_LEGACY_DAEMON_VERSION_STAMP = ".daemon-version"


def _read_venv_metadata_stdlib(venv_dir: Path) -> dict[str, str] | None:
    """Stdlib-only reader for ``.daemon-metadata.json``.

    Returns the parsed dict if the file exists, parses as valid JSON, is a
    dict, and contains both ``python_path`` and ``lock_hash`` keys with
    string values. Any deviation collapses to ``None`` — callers treat
    ``None`` as "no usable metadata, skip this venv".

    Never raises. Mirrors the permissive contract of
    :func:`metadata.read_daemon_metadata` but without Pydantic.
    """
    candidate = venv_dir / _DAEMON_METADATA_FILENAME
    if not candidate.is_file():
        return None
    try:
        raw = candidate.read_text()
    except OSError:
        return None
    if not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    for key in _REQUIRED_METADATA_KEYS:
        value = data.get(key)
        if not isinstance(value, str) or not value:
            return None
    return data


def _is_legacy_stamp_only(venv_dir: Path) -> bool:
    """Return True iff ``venv_dir`` is a Plan-00099-era legacy leftover.

    A legacy leftover is a venv directory that carries the old
    ``.daemon-version`` stamp but NOT the new ``.daemon-metadata.json``.
    The resolver refuses those venvs so ``ensure_venv`` rebuilds them with
    the current lock_hash on the next install/upgrade.

    A venv with neither marker is NOT legacy — it may be a pristine
    pre-v3.1.1 install or a test double. Task 3.9 handles those via eager
    upgrade-time cleanup; until then the resolver accepts them.
    """
    has_stamp = (venv_dir / _LEGACY_DAEMON_VERSION_STAMP).is_file()
    has_metadata = (venv_dir / _DAEMON_METADATA_FILENAME).is_file()
    return has_stamp and not has_metadata


def _compute_project_lock_hash_stdlib(project_root: Path) -> str | None:
    """Stdlib-only mirror of :func:`metadata.compute_project_lock_hash`.

    Returns ``sha256:<64-hex>`` when ``pyproject.toml`` exists under
    ``project_root``; returns ``None`` when it does not (so the resolver
    can report "cannot compute current lock_hash" rather than raise).

    Must match the algorithm in ``metadata.compute_project_lock_hash``
    byte-for-byte, including the ``uv.lock`` absence sentinel, or
    installer-written hashes will fail to match.
    """
    pyproject = project_root / _PYPROJECT_FILENAME
    if not pyproject.is_file():
        return None
    hasher = hashlib.sha256()
    hasher.update(pyproject.read_bytes())
    uv_lock = project_root / _UV_LOCK_FILENAME
    if uv_lock.is_file():
        hasher.update(uv_lock.read_bytes())
    else:
        hasher.update(_UV_LOCK_ABSENT_MARKER)
    return f"sha256:{hasher.hexdigest()}"


def get_venv_path(project_dir: Path | str) -> Path:
    """Return the current Python env's isolated venv directory.

    The venv directory name embeds the Python-env fingerprint so that
    two different Pythons on the same filesystem (e.g. container Python
    and desktop-host pyenv Python) never stomp on each other's venv.

    Args:
        project_dir: Path to the project directory.

    Returns:
        ``{project}/untracked/venv-{fingerprint}/`` in self-install mode or
        ``{project}/.claude/hooks-daemon/untracked/venv-{fingerprint}/`` otherwise.
    """
    project_path = Path(project_dir).resolve()
    untracked_dir = _get_untracked_dir(project_path)
    return untracked_dir / f"venv-{python_venv_fingerprint(project_path)}"


def resolve_existing_venv_python(daemon_dir: Path | str) -> Path:
    """Resolve the bin/python of an already-installed venv under ``daemon_dir``.

    Precedence (matches
    ``src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/_resolve-venv.sh``
    so Python-side and bash-side resolvers agree):

    1. ``$HOOKS_DAEMON_VENV_PATH/bin/python`` — explicit override
    2. ``{daemon_dir}/untracked/venv-{current-fingerprint}/bin/python`` — fingerprint match
    3. First executable ``{daemon_dir}/untracked/venv-*/bin/python`` — scan fallback
    4. ``{daemon_dir}/untracked/venv/bin/python`` — legacy (pre-v3.7.0)

    The scan fallback (step 3) handles the case where the installer built
    the venv under one interpreter (e.g. ``/usr/bin/python3.13`` →
    fingerprint ``py313-956ed987``) but the resolver's current Python is
    a different interpreter (e.g. ``python3`` → 3.9 → fingerprint
    ``py39-3bb0ae3d``). The venv's own ``bin/python`` is a symlink to the
    installer's chosen base interpreter, so the scanned venv is fully
    usable regardless of the resolver's current PATH.

    Step 4 is returned without an existence check so callers can produce
    a useful "venv missing" error message that still mentions the legacy
    path (relevant for brand-new installs where nothing has been
    provisioned yet).

    Args:
        daemon_dir: Daemon installation directory (holds ``untracked/``).
          In client installs: ``{project}/.claude/hooks-daemon``.
          In self-install mode: the project root itself.

    Returns:
        Absolute path to the resolved ``bin/python``.
    """
    daemon_path = Path(daemon_dir)

    override = os.environ.get("HOOKS_DAEMON_VENV_PATH")
    if override:
        return Path(override) / "bin" / "python"

    untracked = daemon_path / "untracked"

    keyed = untracked / f"venv-{python_venv_fingerprint(daemon_path)}" / "bin" / "python"
    if keyed.is_file() and os.access(keyed, os.X_OK):
        return keyed

    if untracked.is_dir():
        for candidate_dir in sorted(untracked.glob("venv-*")):
            candidate = candidate_dir / "bin" / "python"
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate

    # TODO Plan 00100 Phase 2: once this Python entry point becomes the single
    # SSOT (bash resolvers shell out here), remove the scan fallback above and
    # return based solely on the persisted `.daemon-metadata.json` choice.
    # Legacy fallback retained only for pre-v3.7.0 installs.
    return untracked / "venv" / "bin" / "python"


def resolve_existing_venv_python_with_diagnostics(
    daemon_dir: Path | str,
) -> tuple[Path | None, list[str]]:
    """Resolve the venv python path, returning diagnostics for every step tried.

    Unlike :func:`resolve_existing_venv_python`, this function never returns a
    path that does not exist. It returns ``(resolved_path, steps)`` where
    ``resolved_path`` is ``None`` on failure and ``steps`` is the full
    per-precedence-step diagnostic log (always populated, for both success
    and failure).

    Precedence (Plan 00100 Task 3.5 — 5 steps, with legacy-stamp migration):

    1. ``$HOOKS_DAEMON_VENV_PATH/bin/python(3)`` — explicit override
    2. **Metadata-authoritative**: any ``{daemon_dir}/untracked/venv-*/`` whose
       ``.daemon-metadata.json`` has ``lock_hash`` matching the current
       project's ``sha256(pyproject.toml + uv.lock)``. Returns
       ``metadata.python_path`` directly — fingerprint is NOT recomputed
       for lookup.
    3. ``{daemon_dir}/untracked/venv-{current-fingerprint}/bin/python(3)`` —
       fingerprint-keyed (legacy naming convenience)
    4. First executable ``{daemon_dir}/untracked/venv-*/bin/python(3)`` —
       scan fallback (legacy)
    5. ``{daemon_dir}/untracked/venv/bin/python(3)`` — legacy (pre-v3.7.0)

    Steps 3, 4 and 5 refuse any venv that carries the Plan-00099-era
    ``.daemon-version`` stamp without the new ``.daemon-metadata.json``
    (see :func:`_is_legacy_stamp_only`). Those venvs are pre-Phase-3
    leftovers whose dependency state is unknown relative to the current
    lock_hash — the resolver skips them so ``ensure_venv`` rebuilds on
    the next install/upgrade.

    This is the Python SSOT entry point referenced by bash wrappers.
    """
    daemon_path = Path(daemon_dir)
    steps: list[str] = []

    def _pick_interpreter(venv_dir: Path) -> Path | None:
        """Return the first executable interpreter in ``venv_dir/bin``.

        Real venvs have both ``bin/python`` and ``bin/python3``. Some bash
        callers (notably ``scripts/venv-include.bash`` and its test fakes)
        create only one of the two. The SSOT must accept either so every
        caller agrees on whether a venv is usable.
        """
        for name in ("python", "python3"):
            candidate = venv_dir / "bin" / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate
        return None

    override = os.environ.get("HOOKS_DAEMON_VENV_PATH")
    if override:
        override_py = _pick_interpreter(Path(override))
        if override_py is not None:
            steps.append(f"step 1: HOOKS_DAEMON_VENV_PATH={override} OK — using {override_py}")
            return override_py, steps
        steps.append(
            f"step 1: HOOKS_DAEMON_VENV_PATH={override} set but "
            f"{Path(override) / 'bin' / 'python'} is missing or not executable"
        )
    else:
        steps.append("step 1: HOOKS_DAEMON_VENV_PATH unset")

    untracked = daemon_path / "untracked"

    # Step 2: metadata-authoritative resolution.
    current_lock_hash = _compute_project_lock_hash_stdlib(daemon_path)
    if current_lock_hash is None:
        steps.append(
            f"step 2: no pyproject.toml at {daemon_path / _PYPROJECT_FILENAME} "
            "— cannot compute current lock_hash, skipping metadata-driven resolution"
        )
    elif not untracked.is_dir():
        steps.append(f"step 2: untracked dir {untracked} does not exist — no metadata to read")
    else:
        metadata_candidates: list[Path] = sorted(untracked.glob("venv-*"))
        stale_reports: list[str] = []
        no_metadata_count = 0
        matched = False
        for candidate_dir in metadata_candidates:
            metadata = _read_venv_metadata_stdlib(candidate_dir)
            if metadata is None:
                no_metadata_count += 1
                continue
            if metadata["lock_hash"] != current_lock_hash:
                stale_reports.append(
                    f"{candidate_dir.name} (lock_hash={metadata['lock_hash'][:15]}...)"
                )
                continue
            python_path = Path(metadata["python_path"])
            if python_path.is_file() and os.access(python_path, os.X_OK):
                steps.append(
                    f"step 2: metadata match OK — using {python_path} "
                    f"(from {candidate_dir / _DAEMON_METADATA_FILENAME})"
                )
                return python_path, steps
            steps.append(
                f"step 2: metadata at {candidate_dir / _DAEMON_METADATA_FILENAME} "
                f"matches current lock_hash but python_path={python_path} "
                "is missing or not executable"
            )
            matched = True
            break
        if not matched:
            if stale_reports:
                steps.append(
                    f"step 2: metadata stale — lock_hash mismatch in: {', '.join(stale_reports)}"
                )
            elif metadata_candidates and no_metadata_count == len(metadata_candidates):
                steps.append(
                    f"step 2: no venv-*/ under {untracked} has a readable " ".daemon-metadata.json"
                )
            else:
                steps.append(f"step 2: no venv-*/ found under {untracked}")

    fingerprint = python_venv_fingerprint(daemon_path)
    keyed_dir = untracked / f"venv-{fingerprint}"
    keyed_py = _pick_interpreter(keyed_dir)
    if keyed_py is not None:
        if _is_legacy_stamp_only(keyed_dir):
            steps.append(
                f"step 3: skipping legacy-stamped venv {keyed_dir} "
                f"(has {_LEGACY_DAEMON_VERSION_STAMP}, lacks {_DAEMON_METADATA_FILENAME}) "
                "— needs rebuild via ensure_venv"
            )
        else:
            steps.append(f"step 3: fingerprint-keyed venv OK — using {keyed_py}")
            return keyed_py, steps
    else:
        steps.append(
            f"step 3: fingerprint-keyed path {keyed_dir / 'bin' / 'python'} "
            "missing or not executable"
        )

    scanned: list[str] = []
    legacy_skipped: list[str] = []
    if untracked.is_dir():
        for candidate_dir in sorted(untracked.glob("venv-*")):
            scanned.append(str(candidate_dir / "bin" / "python"))
            candidate_py = _pick_interpreter(candidate_dir)
            if candidate_py is None:
                continue
            if _is_legacy_stamp_only(candidate_dir):
                legacy_skipped.append(str(candidate_dir))
                continue
            steps.append(f"step 4: scan-fallback hit — using {candidate_py}")
            return candidate_py, steps
        if legacy_skipped:
            steps.append(
                f"step 4: skipping legacy-stamped venv(s) {legacy_skipped} "
                f"(have {_LEGACY_DAEMON_VERSION_STAMP}, lack {_DAEMON_METADATA_FILENAME}) "
                "— need rebuild via ensure_venv"
            )
        elif scanned:
            steps.append(f"step 4: scan fallback found no executable bin/python among {scanned}")
        else:
            steps.append(f"step 4: scan fallback found no venv-* under {untracked}")
    else:
        steps.append(f"step 4: scan fallback — {untracked} does not exist")

    legacy_dir = untracked / "venv"
    legacy_py = _pick_interpreter(legacy_dir)
    if legacy_py is not None:
        if _is_legacy_stamp_only(legacy_dir):
            steps.append(
                f"step 5: skipping legacy-stamped venv {legacy_dir} "
                f"(has {_LEGACY_DAEMON_VERSION_STAMP}, lacks {_DAEMON_METADATA_FILENAME}) "
                "— needs rebuild via ensure_venv"
            )
        else:
            steps.append(f"step 5: legacy fallback OK — using {legacy_py}")
            return legacy_py, steps
    else:
        steps.append(
            f"step 5: legacy path {legacy_dir / 'bin' / 'python'} missing or not executable"
        )

    return None, steps


def get_project_hash(project_path: Path | str) -> str:
    """
    Generate a short hash from the absolute project path.

    Args:
        project_path: Absolute path to project directory

    Returns:
        First 8 characters of MD5 hash of absolute path
    """
    abs_path = str(Path(project_path).resolve())
    # MD5 used only for generating short path identifier, not for security
    hash_obj = hashlib.md5(abs_path.encode("utf-8"), usedforsecurity=False)
    return hash_obj.hexdigest()[:8]


def get_project_name(project_path: Path | str) -> str:
    """
    Extract sanitized project name from path, truncated to 20 characters.

    Args:
        project_path: Path to project directory

    Returns:
        Last component of path (directory name), truncated to 20 chars for readability
    """
    name = Path(project_path).resolve().name
    # Truncate to 20 characters for readability in /tmp/
    return name[:20]


def _get_fallback_runtime_dir(project_dir: Path, filename: str) -> Path:
    """
    Get fallback path when project path exceeds Unix socket length limit.

    Tries directories in order of preference:
    1. $XDG_RUNTIME_DIR (standard on modern Linux)
    2. /run/user/{uid} (common on Linux)
    3. /tmp (last resort, with warning logged)

    Args:
        project_dir: Resolved project directory path
        filename: File extension without dot (e.g. "sock", "pid", "log")

    Returns:
        Path in a shorter directory using project hash for uniqueness
    """
    project_hash = get_project_hash(project_dir)
    base_name = f"hooks-daemon-{project_hash}"

    # Try XDG_RUNTIME_DIR first (standard)
    xdg_dir = os.environ.get("XDG_RUNTIME_DIR")
    if xdg_dir and Path(xdg_dir).is_dir():
        fallback_dir = Path(xdg_dir)
        logger.info("Socket path too long, using XDG_RUNTIME_DIR: %s", fallback_dir)
        return fallback_dir / f"{base_name}.{filename}"

    # Try /run/user/{uid} (common on Linux)
    run_user = Path(f"/run/user/{os.getuid()}")
    if run_user.is_dir():
        logger.info("Socket path too long, using /run/user: %s", run_user)
        return run_user / f"{base_name}.{filename}"

    # Last resort: /tmp (with warning)
    logger.warning(
        "Socket path too long and no XDG_RUNTIME_DIR or /run/user available. "
        "Using /tmp for runtime files. Set CLAUDE_HOOKS_SOCKET_PATH to override."
    )
    return Path("/tmp") / f"{base_name}.{filename}"  # nosec B108 - /tmp is last resort fallback


def _get_untracked_dir(project_path: Path) -> Path:
    """
    Get the untracked directory for daemon runtime files.

    Detects self-install mode (daemon source at project root) to use the
    shorter path, avoiding unnecessary `.claude/hooks-daemon/` nesting.

    Args:
        project_path: Resolved absolute project directory path

    Returns:
        - Self-install mode: {project}/untracked
        - Normal mode: {project}/.claude/hooks-daemon/untracked
    """
    # Self-install mode: daemon source exists at project root
    if (project_path / "src" / "claude_code_hooks_daemon").is_dir():
        return project_path / "untracked"
    return project_path / ".claude" / "hooks-daemon" / "untracked"


def get_socket_path(project_dir: Path | str) -> Path:
    """
    Generate Unix socket path for project-specific daemon.

    SECURITY: Stored in daemon's untracked directory, not /tmp.
    Pattern: {project}/.claude/hooks-daemon/untracked/daemon.sock
    Container: {project}/.claude/hooks-daemon/untracked/daemon-{hash}.sock

    Can be overridden via CLAUDE_HOOKS_SOCKET_PATH environment variable
    (useful for testing to avoid collision with production daemon).

    Args:
        project_dir: Path to project directory (Path object or string)

    Returns:
        Path object for Unix socket file

    Example:
        >>> get_socket_path(Path('/home/dev/alpha'))
        Path('/home/dev/alpha/.claude/hooks-daemon/untracked/daemon.sock')
    """
    # Allow environment variable override for testing
    if env_path := os.environ.get("CLAUDE_HOOKS_SOCKET_PATH"):
        return Path(env_path)

    # Use daemon's untracked directory (secure, project-specific)
    # Self-install mode uses shorter path: {project}/untracked/
    # Normal mode uses: {project}/.claude/hooks-daemon/untracked/
    project_path = Path(project_dir).resolve()
    untracked_dir = _get_untracked_dir(project_path)
    untracked_dir.mkdir(parents=True, exist_ok=True)

    # Add hostname-based suffix for isolation
    suffix = _get_hostname_suffix()
    path = untracked_dir / f"daemon{suffix}.sock"

    # Fallback if path exceeds AF_UNIX socket length limit
    if len(str(path)) > _UNIX_SOCKET_PATH_LIMIT:
        return _get_fallback_runtime_dir(project_path, "sock")

    return path


def get_pid_path(project_dir: Path | str) -> Path:
    """
    Generate PID file path for project-specific daemon.

    SECURITY: Stored in daemon's untracked directory, not /tmp.
    Pattern: {project}/.claude/hooks-daemon/untracked/daemon.pid
    Self-install: {project}/untracked/daemon.pid
    Container: daemon-{hostname}.pid

    Can be overridden via CLAUDE_HOOKS_PID_PATH environment variable
    (useful for testing to avoid collision with production daemon).

    Args:
        project_dir: Path to project directory (Path object or string)

    Returns:
        Path object for PID file

    Example:
        >>> get_pid_path(Path('/home/dev/alpha'))
        Path('/home/dev/alpha/.claude/hooks-daemon/untracked/daemon.pid')
    """
    # Allow environment variable override for testing
    if env_path := os.environ.get("CLAUDE_HOOKS_PID_PATH"):
        return Path(env_path)

    # Use daemon's untracked directory (secure, project-specific)
    # Self-install mode uses shorter path: {project}/untracked/
    # Normal mode uses: {project}/.claude/hooks-daemon/untracked/
    project_path = Path(project_dir).resolve()
    untracked_dir = _get_untracked_dir(project_path)
    untracked_dir.mkdir(parents=True, exist_ok=True)

    # Add hostname-based suffix for isolation
    suffix = _get_hostname_suffix()
    path = untracked_dir / f"daemon{suffix}.pid"

    # Fallback if path exceeds AF_UNIX socket length limit (consistency with socket)
    if len(str(path)) > _UNIX_SOCKET_PATH_LIMIT:
        return _get_fallback_runtime_dir(project_path, "pid")

    return path


def get_log_path(project_dir: Path | str) -> Path:
    """
    Generate log file path for project-specific daemon.

    SECURITY: Stored in daemon's untracked directory, not /tmp.
    Pattern: {project}/.claude/hooks-daemon/untracked/daemon.log
    Self-install: {project}/untracked/daemon.log
    Container: daemon-{hostname}.log

    Can be overridden via CLAUDE_HOOKS_LOG_PATH environment variable
    (useful for testing to avoid collision with production daemon).

    Args:
        project_dir: Path to project directory (Path object or string)

    Returns:
        Path object for log file

    Example:
        >>> get_log_path(Path('/home/dev/alpha'))
        Path('/home/dev/alpha/.claude/hooks-daemon/untracked/daemon.log')
    """
    # Allow environment variable override for testing
    if env_path := os.environ.get("CLAUDE_HOOKS_LOG_PATH"):
        return Path(env_path)

    # Use daemon's untracked directory (secure, project-specific)
    # Self-install mode uses shorter path: {project}/untracked/
    # Normal mode uses: {project}/.claude/hooks-daemon/untracked/
    project_path = Path(project_dir).resolve()
    untracked_dir = _get_untracked_dir(project_path)
    untracked_dir.mkdir(parents=True, exist_ok=True)

    # Add hostname-based suffix for isolation
    suffix = _get_hostname_suffix()
    path = untracked_dir / f"daemon{suffix}.log"

    # Fallback if path exceeds AF_UNIX socket length limit (consistency with socket)
    if len(str(path)) > _UNIX_SOCKET_PATH_LIMIT:
        return _get_fallback_runtime_dir(project_path, "log")

    return path


def write_socket_discovery_file(project_dir: Path | str, socket_path: Path | str) -> None:
    """Write the actual socket path to a discovery file.

    When the daemon uses a fallback socket path (e.g., XDG_RUNTIME_DIR)
    because the default path exceeds the AF_UNIX length limit, bash hook
    forwarders (init.sh) need to discover the actual socket location.

    The discovery file is written to the default untracked directory
    (which init.sh can always compute) and contains the actual socket path.

    Args:
        project_dir: Path to project directory
        socket_path: Actual socket path the daemon is listening on
    """
    project_path = Path(project_dir).resolve()
    untracked_dir = _get_untracked_dir(project_path)
    untracked_dir.mkdir(parents=True, exist_ok=True)

    suffix = _get_hostname_suffix()
    discovery_file = untracked_dir / f"daemon{suffix}.socket-path"

    try:
        discovery_file.write_text(str(socket_path))
        logger.debug("Wrote socket discovery file: %s -> %s", discovery_file, socket_path)
    except OSError as e:
        logger.warning("Failed to write socket discovery file: %s", e)


def cleanup_socket_discovery_file(project_dir: Path | str) -> None:
    """Remove the socket discovery file on daemon shutdown.

    Args:
        project_dir: Path to project directory
    """
    project_path = Path(project_dir).resolve()
    untracked_dir = _get_untracked_dir(project_path)
    suffix = _get_hostname_suffix()
    discovery_file = untracked_dir / f"daemon{suffix}.socket-path"

    try:
        if discovery_file.exists():
            discovery_file.unlink()
            logger.debug("Removed socket discovery file: %s", discovery_file)
    except OSError as e:
        logger.warning("Failed to cleanup socket discovery file: %s", e)


def is_pid_alive(pid: int) -> bool:
    """
    Check if process with given PID is running.

    Args:
        pid: Process ID to check

    Returns:
        True if process exists and is running
    """
    try:
        # Send signal 0 - no actual signal sent, just checks if process exists
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't access it
        return True
    except (OSError, TypeError, ValueError) as e:
        logger.debug("PID check failed for %d: %s", pid, e)
        return False
    except Exception as e:
        logger.error("Unexpected error checking PID %d: %s", pid, e, exc_info=True)
        return False


def read_pid_file(pid_path: Path | str) -> int | None:
    """
    Read PID from file and verify process is alive.

    Args:
        pid_path: Path to PID file (Path object or string)

    Returns:
        PID if file exists and process is alive, None otherwise
    """
    pid_path = Path(pid_path)
    try:
        with pid_path.open() as f:
            pid = int(f.read().strip())

        if is_pid_alive(pid):
            return pid
        else:
            # Stale PID file, clean it up
            with contextlib.suppress(Exception):
                pid_path.unlink()
            return None
    except FileNotFoundError:
        return None
    except ValueError as e:
        logger.debug("Invalid PID value in %s: %s", pid_path, e)
        return None
    except (OSError, PermissionError) as e:
        logger.debug("Failed to read PID file %s: %s", pid_path, e)
        return None


def write_pid_file(pid_path: Path | str, pid: int) -> None:
    """
    Write PID to file.

    Args:
        pid_path: Path to PID file (Path object or string)
        pid: Process ID to write
    """
    pid_path = Path(pid_path)
    with pid_path.open("w") as f:
        f.write(str(pid))


def cleanup_socket(socket_path: Path | str) -> None:
    """
    Remove Unix socket file if it exists.

    Args:
        socket_path: Path to socket file (Path object or string)
    """
    try:
        socket_path = Path(socket_path)
        if socket_path.exists():
            socket_path.unlink()
    except (OSError, PermissionError) as e:
        logger.warning("Failed to cleanup socket %s: %s", socket_path, e)
    except Exception as e:
        logger.error("Unexpected error cleaning socket %s: %s", socket_path, e, exc_info=True)


def cleanup_pid_file(pid_path: Path | str) -> None:
    """
    Remove PID file if it exists.

    Args:
        pid_path: Path to PID file (Path object or string)
    """
    try:
        pid_path = Path(pid_path)
        if pid_path.exists():
            pid_path.unlink()
    except (OSError, PermissionError) as e:
        logger.warning("Failed to cleanup PID file %s: %s", pid_path, e)
    except Exception as e:
        logger.error("Unexpected error cleaning PID file %s: %s", pid_path, e, exc_info=True)


# Prefix for all daemon runtime files
_DAEMON_FILE_PREFIX = "daemon-"

# Filename for the cleanup status file read by the startup_cleanup statusline handler
_CLEANUP_STATUS_FILENAME = "cleanup_status.json"


def cleanup_stale_daemon_files(project_dir: Path | str, max_age_days: int = 7) -> int:
    """Remove daemon runtime files that haven't been touched within max_age_days.

    Active daemons call touch_daemon_files() periodically to keep their files
    fresh. Files whose mtime has aged past the cutoff belong to dead containers
    and are safe to remove.

    This is deliberately NOT hostname-based: multiple containers can legitimately
    share a single codebase, so removing by hostname would break live daemons.

    Args:
        project_dir: Path to project directory
        max_age_days: Files older than this many days are removed (default 7)

    Returns:
        Number of stale files removed
    """
    project_path = Path(project_dir).resolve()
    untracked_dir = _get_untracked_dir(project_path)

    if not untracked_dir.is_dir():
        return 0

    cutoff = time.time() - (max_age_days * 86400)
    removed = 0

    for filepath in untracked_dir.iterdir():
        if not filepath.name.startswith(_DAEMON_FILE_PREFIX):
            continue
        try:
            if filepath.stat().st_mtime < cutoff:
                filepath.unlink()
                removed += 1
                logger.info("Removed stale daemon file: %s", filepath)
        except OSError as e:
            logger.warning("Failed to remove stale daemon file %s: %s", filepath, e)
        except Exception as e:
            logger.error("Unexpected error removing %s: %s", filepath, e, exc_info=True)

    if removed:
        logger.info(
            "Cleaned up %d stale daemon file(s) (older than %d days)", removed, max_age_days
        )

    return removed


def touch_daemon_files_in_dir(untracked_dir: Path) -> None:
    """Touch the current daemon's runtime files in a known untracked directory.

    Inner implementation used by both touch_daemon_files() (project-path API)
    and the server's periodic task (socket-path API).

    Args:
        untracked_dir: The untracked directory containing daemon runtime files
    """
    if not untracked_dir.is_dir():
        return

    suffix = _get_hostname_suffix()
    current_prefix = f"daemon{suffix}."

    for filepath in untracked_dir.iterdir():
        if not filepath.name.startswith(current_prefix):
            continue
        try:
            filepath.touch()
            logger.debug("Touched daemon file: %s", filepath)
        except OSError as e:
            logger.debug("Failed to touch daemon file %s: %s", filepath, e)


def touch_daemon_files(project_dir: Path | str) -> None:
    """Touch the current daemon's runtime files to mark them as active.

    Called periodically by the running daemon so that cleanup_stale_daemon_files()
    can distinguish live containers (recently touched) from dead ones (aged out).

    Only touches files belonging to the current hostname instance.

    Args:
        project_dir: Path to project directory
    """
    project_path = Path(project_dir).resolve()
    untracked_dir = _get_untracked_dir(project_path)
    touch_daemon_files_in_dir(untracked_dir)


def write_cleanup_status(project_dir: Path | str, total_removed: int) -> None:
    """Write cleanup result to a JSON file for the statusline handler.

    The startup_cleanup statusline handler reads this file to briefly display
    a cleanup summary after daemon startup.

    Args:
        project_dir: Path to project directory
        total_removed: Total number of stale files removed during startup cleanup
    """
    project_path = Path(project_dir).resolve()
    untracked_dir = _get_untracked_dir(project_path)

    try:
        untracked_dir.mkdir(parents=True, exist_ok=True)
        status_file = untracked_dir / _CLEANUP_STATUS_FILENAME
        status_file.write_text(json.dumps({"count": total_removed, "timestamp": time.time()}))
        logger.debug("Wrote cleanup status: %d files removed", total_removed)
    except OSError as e:
        logger.warning("Failed to write cleanup status: %s", e)


def _cli_resolve_venv(args: argparse.Namespace) -> int:
    """CLI handler for the ``resolve-venv`` subcommand.

    Plan 00100 Task 2.3: Python SSOT entry point that bash wrappers shell out
    to. Prints the resolved ``bin/python`` path to stdout on success (exit 0),
    or a per-step diagnostic trace to stderr on failure (exit 1).

    Plan 00100 Task 2.4: when ``--fallback-target`` is set, a miss returns
    the fingerprint-keyed creation target (exit 0) instead of exit 1 — this
    is what ``scripts/venv-include.bash::ensure_venv`` needs when no venv
    has been created yet on a fresh project.
    """
    daemon_dir = Path(args.daemon_dir) if args.daemon_dir else Path.cwd()
    fallback_target: bool = getattr(args, "fallback_target", False)
    resolved, steps = resolve_existing_venv_python_with_diagnostics(daemon_dir)
    if resolved is not None:
        print(str(resolved))
        return 0

    if fallback_target:
        fingerprint = python_venv_fingerprint(daemon_dir)
        print(str(daemon_dir / "untracked" / f"venv-{fingerprint}" / "bin" / "python"))
        return 0

    print(
        "resolve-venv: no usable venv found. Precedence trace:",
        file=sys.stderr,
    )
    for step in steps:
        print(f"  {step}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    """Dispatcher for ``python -m claude_code_hooks_daemon.daemon.paths``.

    Currently exposes the ``resolve-venv`` subcommand (Plan 00100 Phase 2);
    more SSOT subcommands may be added later.
    """
    parser = argparse.ArgumentParser(
        description="Hooks-daemon path utilities (SSOT for bash wrappers).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve_venv_parser = subparsers.add_parser(
        "resolve-venv",
        help="Resolve the active venv's bin/python path for this daemon install.",
    )
    resolve_venv_parser.add_argument(
        "--daemon-dir",
        default=None,
        help=(
            "Daemon installation directory (defaults to the current working "
            "directory). Self-install mode: the project root. Client install: "
            "{project}/.claude/hooks-daemon."
        ),
    )
    resolve_venv_parser.add_argument(
        "--fallback-target",
        action="store_true",
        help=(
            "On miss, print the fingerprint-keyed creation target path "
            "($DAEMON_DIR/untracked/venv-{fingerprint}/bin/python) and exit "
            "0 instead of exit 1. Used by scripts/venv-include.bash so "
            "ensure_venv has a creation target before any venv exists."
        ),
    )
    resolve_venv_parser.set_defaults(func=_cli_resolve_venv)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
