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

from pathlib import Path, PurePosixPath

#: Canonical notation for "the repository root" in documented and configured
#: paths (owner ruling, Plan 00302 extension). It is optional sugar on any
#: repo-relative field -- a bare relative path stays valid without it -- and
#: it is the portable alternative to a genuine absolute path on the handful
#: of fields that are exempt from the repo-relative-only rule (plugin/project
#: handler paths). It must appear only as the very first path segment.
#: Named PLACEHOLDER rather than TOKEN: bandit B105 treats any ``*TOKEN``
#: string-literal constant as a possible hardcoded credential, and this
#: project's security gate runs with no skip list.
REPO_ROOT_PLACEHOLDER = "{REPO_ROOT}"

_TOKEN_PREFIX = REPO_ROOT_PLACEHOLDER + "/"


def _check_token_placement(value: str, label: str) -> None:
    """Raise if ``{REPO_ROOT}`` appears anywhere other than the very start of ``value``.

    Shared by every caller that needs the placement rule -- stripping it
    (:func:`_strip_repo_root_token`), expanding it
    (:func:`expand_repo_root_token`), or validating placement alone on a
    field that is otherwise exempt from repo-relativity
    (:func:`validate_repo_root_token_placement`).
    """
    if value == REPO_ROOT_PLACEHOLDER or value.startswith(_TOKEN_PREFIX):
        return
    if REPO_ROOT_PLACEHOLDER in value:
        raise ValueError(
            f"{label} may only use {REPO_ROOT_PLACEHOLDER!r} at the very start of the path, "
            f"followed by '/' (or alone, for the repository root itself), got {value!r}"
        )


def _strip_repo_root_token(value: str, label: str) -> str:
    """Strip a leading ``{REPO_ROOT}`` token, if present, from ``value``.

    Args:
        value: The raw configured path, possibly token-prefixed.
        label: What is being validated, for the error message.

    Returns:
        ``value`` with the token and its following ``/`` removed, or
        ``value`` unchanged if it carries no token at all.

    Raises:
        ValueError: If the token appears anywhere other than at the very
            start of ``value`` (either alone, or immediately followed by
            ``/``).
    """
    _check_token_placement(value, label)
    if value == REPO_ROOT_PLACEHOLDER:
        return ""
    if value.startswith(_TOKEN_PREFIX):
        return value[len(_TOKEN_PREFIX) :]
    return value


def validate_repo_root_token_placement(value: str, label: str) -> str:
    """Validate ``{REPO_ROOT}`` token PLACEMENT only, leaving ``value`` unchanged.

    For a config field that is EXEMPT from the repo-relative-only rule (e.g.
    ``PluginConfig.path``, ``ProjectHandlersConfig.path``) but still accepts
    the optional ``{REPO_ROOT}`` token, this is the pydantic ``field_validator``
    seam: it turns a misplaced token into a named config validation error at
    load time, instead of a startup ``ValueError`` from the unguarded
    ``expand_repo_root_token`` call each such field's consumer makes later
    (Plan 00305 Task 1.2). It does not check repo-relativity or ``..``
    escapes -- those remain irrelevant for an exempt field and are left to
    :func:`expand_repo_root_token`'s own escape check at expansion time.

    Args:
        value: The raw configured path, possibly token-prefixed.
        label: What is being validated, for the error message.

    Returns:
        ``value`` unchanged.

    Raises:
        ValueError: If the token appears anywhere other than at the very
            start of ``value``.
    """
    _check_token_placement(value, label)
    return value


def normalise_repo_relative_path(value: str, label: str) -> str:
    """Validate and normalise a repository-relative config path.

    Escapes (``..``) are rejected for the same portability reason: a path
    that leaves the repository is by definition describing something the
    repository does not carry.

    Normalisation makes ``web/``, ``./web`` and ``web`` one declaration, and
    an empty string normalises to ``.`` (the repository root itself) rather
    than staying a special-cased empty string. A leading ``{REPO_ROOT}``
    token is optional sugar -- ``{REPO_ROOT}/web`` normalises the same as
    ``web`` -- see :data:`REPO_ROOT_PLACEHOLDER`.

    Args:
        value: The raw configured path.
        label: What is being validated, for the error message.

    Returns:
        The normalised relative path; ``.`` for the repository root itself.

    Raises:
        ValueError: If the path is absolute or escapes the repository.
    """
    value = _strip_repo_root_token(value, label)

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


def expand_repo_root_token(value: str, project_root: Path) -> str:
    """Expand a leading ``{REPO_ROOT}`` token against ``project_root``.

    For config surfaces that are EXEMPT from the repo-relative-only rule
    (e.g. ``PluginConfig.path``, ``ProjectHandlersConfig.path``), an absolute
    path is a deliberate, machine-specific override and a plain relative
    path keeps whatever meaning the surface's own loader already gives it.
    The ``{REPO_ROOT}`` token is the third, portable option: it names the
    project root explicitly without hardcoding a machine-specific absolute
    path.

    Args:
        value: The raw configured path.
        project_root: The resolved project root to expand the token against.

    Returns:
        An absolute path string when ``value`` is token-prefixed; ``value``
        unchanged (leading ``/`` or plain relative) otherwise.

    Raises:
        ValueError: If the token appears somewhere other than the start, or
            the token-prefixed remainder escapes the repository via ``..``.
    """
    if value != REPO_ROOT_PLACEHOLDER and not value.startswith(_TOKEN_PREFIX):
        if REPO_ROOT_PLACEHOLDER in value:
            raise ValueError(
                f"path may only use {REPO_ROOT_PLACEHOLDER!r} at the very start of the path, "
                f"followed by '/' (or alone, for the repository root itself), got {value!r}"
            )
        return value

    remainder = "" if value == REPO_ROOT_PLACEHOLDER else value[len(_TOKEN_PREFIX) :]
    if ".." in PurePosixPath(remainder).parts:
        raise ValueError(f"path must not escape the repository, got {value!r}")

    return str(project_root / remainder) if remainder else str(project_root)
