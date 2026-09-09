"""File offload for the upgrade-time report commands (Plan 00329).

``check-truth-changes`` and ``check-config-migrations`` grow with every
release, and both exit 1 precisely when they have something to say. Claude
Code delivers an exit-1 Bash result whole only up to roughly 10,000
characters; past that it hands the agent a head-and-tail excerpt with the
middle DROPPED and no file to go back to. A 90 KB report therefore reaches
the agent as ~10 KB with no marker saying what was cut.

So the full report goes to a file and stdout carries a summary bounded by
``SUMMARY_MAX_BYTES`` — the same idiom as ``bin/echd-capture`` and the
``subagent_report_size_blocker`` handler. The bound is a constant, not a
function of the corpus, so it holds however many releases an upgrade crosses.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

# Under the ~10,000-character ceiling Claude Code applies to a failing
# (exit-1) Bash result, with headroom because the documented figure is
# "roughly". Above the 4,000-character floor an operator can configure for
# the valid path, so the summary is never itself offloaded.
SUMMARY_MAX_BYTES = 8000

_ENCODING = "utf-8"


def bound_summary(
    head: list[str],
    items: list[str],
    tail: list[str],
    max_bytes: int,
    overflow: Callable[[int], str],
) -> str:
    """Join head, as many items as fit, an overflow line if any were cut, and tail.

    Items are kept in order from the start and dropped from the end. The
    result is guaranteed to be at most ``max_bytes`` when encoded as UTF-8.

    Args:
        head: Lines that must always appear first.
        items: Candidate lines, each optional.
        tail: Lines that must always appear last.
        max_bytes: The bound, in UTF-8 bytes.
        overflow: Builds the line that names how many items were omitted.

    Returns:
        The bounded text, newline-terminated.

    Raises:
        ValueError: If head, tail and the overflow line alone exceed the bound
            — a summary that cannot fit is a defect to surface, not to trim.
    """
    fixed_bytes = _bytes(head) + _bytes(tail)
    if fixed_bytes > max_bytes:
        raise ValueError(
            f"summary head and tail are {fixed_bytes} bytes, over the {max_bytes}-byte bound"
        )

    kept: list[str] = []
    used = fixed_bytes
    for index, item in enumerate(items):
        remaining = len(items) - index
        # Reserve the overflow line for the worst case (everything from here
        # on is cut) so that appending it later can never breach the bound.
        reserve = _bytes([overflow(remaining)]) if remaining > 0 else 0
        item_bytes = _bytes([item])
        if used + item_bytes + reserve > max_bytes:
            break
        kept.append(item)
        used += item_bytes

    omitted = len(items) - len(kept)
    lines = [*head, *kept]
    if omitted:
        overflow_line = overflow(omitted)
        if used + _bytes([overflow_line]) > max_bytes:
            raise ValueError(
                f"summary overflow line does not fit within the {max_bytes}-byte bound"
            )
        lines.append(overflow_line)
    lines.extend(tail)
    return "".join(f"{line}\n" for line in lines)


def write_offloaded_report(report_dir: Path, name: str, text: str) -> Path:
    """Write ``text`` to ``report_dir/name``, creating the directory, and return the path.

    Raises:
        OSError: If the directory cannot be created or the file cannot be
            written. The caller decides how to degrade; silently printing a
            path that does not exist would read as "the command produced
            nothing".
    """
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / name
    path.write_text(text, encoding=_ENCODING)
    return path


def _bytes(lines: list[str]) -> int:
    """UTF-8 byte length of ``lines`` once each is newline-terminated."""
    return sum(len(line.encode(_ENCODING)) + 1 for line in lines)
