"""Record the daemon version a project expects in its config (Plan 00477).

``daemon.expected_version`` in ``.claude/hooks-daemon.yaml`` names the version
``.claude/provision.sh`` installs into a fresh checkout of the project. ``install``
and ``upgrade`` write it, after the deploy, so the tracked config always says
which daemon the rest of the tracked assets came from.

The file is edited as TEXT. A round trip through a YAML library would drop the
client's comments and reorder their layout, and this file is the one they edit
by hand. The shell resolver that reads the key back (``_resolve_expected_version``
in ``init.sh``) runs before any venv exists, so it is a line-oriented reader as
well; both accept exactly the shape written here.

Run as ``python -m claude_code_hooks_daemon.install.expected_version
--project-root DIR [--version X.Y.Z]`` (the install and upgrade scripts do,
with the running daemon's own version).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.install.install_stamp import is_branch_install
from claude_code_hooks_daemon.version import __version__

EXPECTED_VERSION_KEY: Final[str] = "expected_version"

#: Strict X.Y.Z. The value goes into a git ref, so nothing looser is accepted.
#: ``\Z`` rather than ``$``: ``$`` matches before a trailing newline.
VERSION_PATTERN: Final[str] = r"[0-9]+\.[0-9]+\.[0-9]+"
_VERSION_RE: Final[re.Pattern[str]] = re.compile(rf"\A{VERSION_PATTERN}\Z")

_DAEMON_HEADER_RE: Final[re.Pattern[str]] = re.compile(r"^daemon:(?P<rest>.*)$")
_KEY_LINE_RE: Final[re.Pattern[str]] = re.compile(rf"^(?P<indent>[ \t]+){EXPECTED_VERSION_KEY}:")
_COMMENT: Final[str] = "daemon version this project expects; `provision.sh` installs exactly this"


def _key_line(indent: str, version: str) -> str:
    return f'{indent}{EXPECTED_VERSION_KEY}: "{version}"  # {_COMMENT}\n'


def _block_end(lines: list[str], header_index: int) -> int:
    """Index one past the last line belonging to the ``daemon:`` block.

    The block runs to the next non-blank, non-comment line that is not
    indented. Trailing blank and comment lines belong to whatever follows.
    """
    last_member = header_index
    for index in range(header_index + 1, len(lines)):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line[0].isspace():
            break
        last_member = index
    return last_member + 1


def _member_indent(lines: list[str], header_index: int, end: int) -> str:
    """Indent of the block's first direct member; two spaces when it has none.

    A member at any other indent belongs to a nested mapping, so neither the
    inserted key nor the one replaced may sit there.
    """
    for index in range(header_index + 1, end):
        line = lines[index]
        if line.strip() and not line.lstrip().startswith("#"):
            return line[: len(line) - len(line.lstrip(" \t"))]
    return "  "


def record_expected_version(config_path: Path, version: str) -> bool:
    """Set ``daemon.expected_version`` in the config file, preserving everything else.

    Args:
        config_path: The project's ``.claude/hooks-daemon.yaml``.
        version: The daemon version, strictly ``X.Y.Z``.

    Returns:
        True when the file changed, False when it already said this.

    Raises:
        ValueError: ``version`` is not ``X.Y.Z``, or ``daemon`` is an inline
            mapping this text editor will not guess at.
        FileNotFoundError: ``config_path`` does not exist.
    """
    if not _VERSION_RE.match(version):
        raise ValueError(f"expected_version must be X.Y.Z, got {version!r}")
    if not config_path.is_file():
        raise FileNotFoundError(f"Config not found: {config_path}")

    original = config_path.read_text()
    lines = original.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"

    header_index: int | None = None
    for index, line in enumerate(lines):
        header = _DAEMON_HEADER_RE.match(line.rstrip("\n"))
        if header is None:
            continue
        if header.group("rest").split("#", 1)[0].strip():
            raise ValueError(
                "`daemon:` is an inline mapping; add `expected_version` to it by hand"
                f" ({config_path})"
            )
        header_index = index
        break

    if header_index is None:
        lines.extend(["\n", "daemon:\n", _key_line("  ", version)])
    else:
        end = _block_end(lines, header_index)
        indent = _member_indent(lines, header_index, end)
        for index in range(header_index + 1, end):
            key = _KEY_LINE_RE.match(lines[index])
            if key is not None and key.group("indent") == indent:
                lines[index] = _key_line(indent, version)
                break
        else:
            lines.insert(end, _key_line(indent, version))

    updated = "".join(lines)
    if updated == original:
        return False
    config_path.write_text(updated)
    return True


def main(argv: list[str] | None = None) -> int:
    """Command line entry point for the install and upgrade scripts."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument(
        "--version",
        default=__version__,
        help="Version to record (default: the running daemon version)",
    )
    args = parser.parse_args(argv)

    # A branch install runs code that is not the release its base version names,
    # so recording that version would make provision fetch a different daemon
    # from the one the tracked assets came from. Any existing key stays as is.
    if is_branch_install():
        print("expected_version: branch install, not recorded (the key is left as it is)")
        return 0

    config_path = args.project_root / ".claude" / "hooks-daemon.yaml"
    try:
        changed = record_expected_version(config_path, args.version)
    except (ValueError, FileNotFoundError) as exc:
        print(f"expected_version: {exc}", file=sys.stderr)
        return 1
    print(
        f"expected_version: {'recorded' if changed else 'already'} {args.version} in {config_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
