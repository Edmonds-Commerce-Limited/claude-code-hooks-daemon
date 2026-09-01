"""Shared repo-relative-path validation (Plan 00303).

Config carries ZERO absolute paths -- the owner ruling behind Plan 00296's
``ProjectConfig.root``/``bin_dirs`` validators. A repository is mounted at
different places on different machines (a container bind mount, a
developer's home directory, a CI checkout), so an absolute path in committed
config is correct on exactly one of them and silently wrong everywhere else.

This is the ONE implementation of that rule, deliberately free of any
pydantic import. Two different call sites need it:

- A pydantic ``field_validator`` (e.g. ``config.models._repo_relative_path``,
  which wraps this function) -- a wrong value there is a config-authoring
  mistake and should be a hard validation error.
- A runtime resolver reading an ``options`` dict by hand (e.g.
  ``payload_capture.resolve_capture_dir``, ``secret_redaction``'s secret word
  list path, ``model_fallback_detector``'s snapshot dir) -- those modules are
  deliberately pydantic-free for testability, and their contract is
  fail-open/advisory, so THEY catch :class:`ValueError` from this function
  and degrade (log + fall back to the default) rather than raise.
"""

from __future__ import annotations

from pathlib import PurePosixPath


def normalise_repo_relative_path(value: str, label: str) -> str:
    """Validate and normalise a repository-relative config path.

    Escapes (``..``) are rejected for the same portability reason: a path
    that leaves the repository is by definition describing something the
    repository does not carry.

    Normalisation makes ``web/``, ``./web`` and ``web`` one declaration, and
    an empty string normalises to ``.`` (the repository root itself) rather
    than staying a special-cased empty string.

    Args:
        value: The raw configured path.
        label: What is being validated, for the error message.

    Returns:
        The normalised relative path; ``.`` for the repository root itself.

    Raises:
        ValueError: If the path is absolute or escapes the repository.
    """
    if value.startswith("/") or PurePosixPath(value).is_absolute():
        raise ValueError(
            f"{label} must be repository-relative, got absolute {value!r}. "
            f"Absolute paths break when the repository is mounted elsewhere."
        )
    if value.startswith("~"):
        raise ValueError(
            f"{label} must be repository-relative, got home-relative {value!r}. "
            f"Absolute paths break when the repository is mounted elsewhere."
        )

    # PurePosixPath normalises "./web", "web/" and "a//b" without touching
    # ".." components, which are then rejected rather than resolved.
    normalised = PurePosixPath(value).as_posix()
    if ".." in PurePosixPath(normalised).parts:
        raise ValueError(f"{label} must not escape the repository, got {value!r}")

    return normalised
