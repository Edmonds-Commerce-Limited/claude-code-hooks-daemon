"""Where Claude Code keeps its own configuration (Plan 00468, audit G13).

Claude Code keeps its user settings, user agents and skills, session
transcripts and installed plugins under ``$CLAUDE_CONFIG_DIR`` when that is
set, else ``~/.claude``. Every daemon component that looks there asks this
module, so no two of them can disagree about where the directory is.

**Whose environment.** Called inside the daemon, this reads the DAEMON's
environment, which is fixed when the daemon starts. A session started with a
different ``CLAUDE_CONFIG_DIR`` or ``HOME`` is not visible here: the hook
payload does not carry either value.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Final

#: The environment variable Claude Code reads for its config directory.
CLAUDE_CONFIG_DIR_ENV: Final[str] = "CLAUDE_CONFIG_DIR"

#: The documented default, relative to the home directory.
DEFAULT_CLAUDE_CONFIG_DIRNAME: Final[str] = ".claude"

#: The config dir's subdirectory holding one directory per project.
PROJECTS_DIRNAME: Final[str] = "projects"

#: Claude Code cuts a longer project directory name and appends a hash.
PROJECT_DIR_NAME_MAX_LENGTH: Final[int] = 200

_REPLACEMENT_UNIT: Final[str] = "-"
_BASE36_DIGITS: Final[str] = "0123456789abcdefghijklmnopqrstuvwxyz"
_UTF16_UNIT_BYTES: Final[int] = 2
_JAVA_HASH_MULTIPLIER: Final[int] = 31
_UINT32_MASK: Final[int] = 0xFFFFFFFF
_INT32_SIGN_BIT: Final[int] = 0x80000000
_UINT32_RANGE: Final[int] = 0x100000000
_ASCII_LIMIT: Final[int] = 0x80


def claude_config_dir(
    *, environ: Mapping[str, str] | None = None, home: Path | None = None
) -> Path:
    """Claude Code's config directory: ``$CLAUDE_CONFIG_DIR``, else ``~/.claude``.

    Args:
        environ: The environment to read; defaults to the process environment.
        home: The home directory for the default; defaults to
            :meth:`Path.home`. Tests pass both so nothing real is consulted.

    Returns:
        The directory, unresolved: a symlinked home stays a symlink, so a
        caller that compares paths must resolve both sides itself.
    """
    source = os.environ if environ is None else environ
    configured = source.get(CLAUDE_CONFIG_DIR_ENV)
    base_home = home if home is not None else Path.home()
    if configured:
        if configured == "~" or configured.startswith("~/"):
            return base_home / configured[2:]
        return Path(configured).expanduser()
    return base_home / DEFAULT_CLAUDE_CONFIG_DIRNAME


def config_dir_within(project_root: Path, *, config_dir: Path | None = None) -> str | None:
    """The config dir as a project-relative POSIX path, when it lies inside.

    Under ccy the Claude home is a symlink into the project tree, so both
    paths are resolved before comparing. A config dir equal to the project
    root is refused: every project file would then count as config.

    Args:
        project_root: The project to test against.
        config_dir: Defaults to :func:`claude_config_dir`.

    Returns:
        e.g. ``".claude/ccy"``, or None when the directory is elsewhere.
    """
    directory = config_dir if config_dir is not None else claude_config_dir()
    resolved_root = project_root.resolve()
    resolved_dir = directory.resolve()
    if resolved_dir == resolved_root or not resolved_dir.is_relative_to(resolved_root):
        return None
    return resolved_dir.relative_to(resolved_root).as_posix()


def _utf16_units(text: str) -> list[int]:
    """The UTF-16 code units JavaScript sees for ``text``."""
    raw = text.encode("utf-16-le", "surrogatepass")
    return [
        int.from_bytes(raw[index : index + _UTF16_UNIT_BYTES], "little")
        for index in range(0, len(raw), _UTF16_UNIT_BYTES)
    ]


def _java_string_hash(units: list[int]) -> int:
    """JavaScript's ``(h << 5) - h + unit | 0`` over every unit: a signed 32-bit hash."""
    value = 0
    for unit in units:
        value = (value * _JAVA_HASH_MULTIPLIER + unit) & _UINT32_MASK
    return value - _UINT32_RANGE if value & _INT32_SIGN_BIT else value


def _base36(number: int) -> str:
    if number == 0:
        return _BASE36_DIGITS[0]
    digits: list[str] = []
    while number:
        number, remainder = divmod(number, len(_BASE36_DIGITS))
        digits.append(_BASE36_DIGITS[remainder])
    return "".join(reversed(digits))


def _is_ascii_alphanumeric(unit: int) -> bool:
    return unit < _ASCII_LIMIT and chr(unit).isalnum()


def project_dir_name(project_path: str) -> str:
    """Claude Code's directory name for a project path (00466 N27).

    This is the rule in Claude Code's own bundle, not an approximation: each
    UTF-16 code unit outside ``[a-zA-Z0-9]`` becomes ``-`` (``/``, ``.``,
    ``_`` and a space alike), and a name longer than 200 is cut to 200 and
    suffixed with ``-`` plus the base-36 absolute value of the path's 32-bit
    string hash, so two long paths sharing a prefix stay apart.
    """
    units = _utf16_units(project_path)
    name = "".join(
        chr(unit) if _is_ascii_alphanumeric(unit) else _REPLACEMENT_UNIT for unit in units
    )
    if len(name) <= PROJECT_DIR_NAME_MAX_LENGTH:
        return name
    suffix = _base36(abs(_java_string_hash(units)))
    return f"{name[:PROJECT_DIR_NAME_MAX_LENGTH]}{_REPLACEMENT_UNIT}{suffix}"


def claude_project_dir(
    project_root: Path, *, config_dir: Path | None = None, must_exist: bool = False
) -> Path:
    """The directory Claude Code keeps a project's transcripts and memory in.

    ``<config dir>/projects/<project_dir_name(real path)>``. Claude Code
    resolves the working directory's symlinks before naming it, so this does
    too. Every daemon component that reads transcripts asks this function, so
    none can name a different directory (00466 N27).

    Args:
        project_root: The project whose directory is wanted.
        config_dir: Defaults to :func:`claude_config_dir`.
        must_exist: Raise instead of returning a directory that is absent, for
            a caller whose "nothing found" would otherwise look like "no data".

    Raises:
        FileNotFoundError: ``must_exist`` is set and the directory is absent;
            the message names the directory that was looked for.
    """
    base = config_dir if config_dir is not None else claude_config_dir()
    directory = base / PROJECTS_DIRNAME / project_dir_name(str(project_root.resolve()))
    if must_exist and not directory.is_dir():
        raise FileNotFoundError(f"no Claude Code project directory at {directory}")
    return directory
