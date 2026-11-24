"""The owner directives register: parse, dedupe and render (Plan 00636 Task 2.2, s3).

A directive the owner gave once and had to repeat (the retrospective counted
one given about eight times) is recorded ONCE, in config, and replayed to a
coordinator seat, so the seat checks the register instead of asking again.

The register is a recorded request, never a countermand and never a fresh
human instruction: the replayed text says so, and it is not a citable human
approval (that is the HUMAN check's, Plan 00634). Nothing here reads the bus.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

MAX_DIRECTIVES: Final[int] = 20
MAX_TEXT_CHARS: Final[int] = 400
_ID: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_WHITESPACE: Final[re.Pattern[str]] = re.compile(r"\s+")
CONFIG_LOCATION: Final[str] = (
    ".claude/hooks-daemon.yaml under "
    "handlers.user_prompt_submit.owner_directives_register.options.directives"
)


@dataclass(frozen=True)
class Directive:
    id: str
    text: str


@dataclass(frozen=True)
class DirectiveRegister:
    """The validated register: what to replay, what was collapsed, what was skipped."""

    directives: tuple[Directive, ...] = ()
    #: Entries dropped as repeats of an earlier id or wording.
    collapsed: int = 0
    #: One category line per skipped entry; never entry text.
    problems: tuple[str, ...] = ()


def _same_wording(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip().casefold()


def _entry(raw: object) -> Directive | str:
    """The directive an entry declares, or the problem with it."""
    if not isinstance(raw, dict):
        return "an entry is not a mapping with id and text"
    entry_id, text = raw.get("id"), raw.get("text")
    if not isinstance(entry_id, str) or not _ID.fullmatch(entry_id.strip()):
        return "an entry id is missing or not a plain token"
    if not isinstance(text, str) or not text.strip():
        return "an entry text is missing or blank"
    if len(text.strip()) > MAX_TEXT_CHARS:
        return f"an entry text is longer than {MAX_TEXT_CHARS} characters"
    return Directive(entry_id.strip(), _WHITESPACE.sub(" ", text).strip())


def parse_directives(raw: object) -> DirectiveRegister:
    """Validate ``options.directives``; a repeat of an id or a wording is recorded once.

    Never raises: a malformed option or entry is skipped and reported in
    ``problems``, so one bad line cannot silence the rest of the register.
    """
    if raw is None:
        return DirectiveRegister()
    if not isinstance(raw, list):
        return DirectiveRegister(problems=("options.directives is not a list",))
    kept: list[Directive] = []
    problems: list[str] = []
    seen_ids: set[str] = set()
    seen_text: set[str] = set()
    collapsed = 0
    for item in raw:
        parsed = _entry(item)
        if isinstance(parsed, str):
            problems.append(parsed)
            continue
        if parsed.id.casefold() in seen_ids or _same_wording(parsed.text) in seen_text:
            collapsed += 1
            continue
        if len(kept) >= MAX_DIRECTIVES:
            problems.append(f"more than {MAX_DIRECTIVES} directives; the rest are not replayed")
            break
        seen_ids.add(parsed.id.casefold())
        seen_text.add(_same_wording(parsed.text))
        kept.append(parsed)
    return DirectiveRegister(tuple(kept), collapsed, tuple(problems))


def render_directives(directives: Sequence[Directive]) -> str:
    """The text replayed to a coordinator seat."""
    lines = [
        "OWNER DIRECTIVES REGISTER (on file for this project). The owner has already "
        "given these directives; each is recorded once here, so check this list before "
        "asking the owner something it answers. This is a recorded request, not a "
        "fresh human instruction, and not a citable human approval for any act that "
        "needs one.",
        *(f"- [{d.id}] {d.text}" for d in directives),
        f"Recorded in {CONFIG_LOCATION} (owner_directives_register), where it can be "
        "read and withdrawn.",
    ]
    return "\n".join(lines)
