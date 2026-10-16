"""A static read of a Workflow script's fan-out (Plan 00472 Task 3.6, 472-W section 3).

A ``Workflow`` script's ``agent()`` calls fire no PreToolUse of their own, so
the script text at PreToolUse(``Workflow``) is the only place their number and
model choice can be seen before any agent starts. This reads it WITHOUT running
it: strings and comments are blanked, brackets matched, and every ``agent(``
call site is multiplied by the fan-out constructs that enclose it:

- ``[...].map(...)``, ``pipeline([...], ...)`` and ``for (... of [...])`` over a
  literal array count its elements;
- ``Array.from({length: N}, ...)`` and ``for (let i = A; i < N; i++)`` count N;
- the same constructs over the tool's own ``args`` count ``len(args)`` when the
  call passed ``args`` as an array (the ``args`` bucket);
- everything else (a list the script computes, ``while`` and ``do`` loops, a
  spread) is UNKNOWN. An unknown multiplier counts as 1 in the total, which is
  therefore a lower bound ("at least N").

A site is "with model" when its own call carries a ``model:`` option. A phase's
``model`` (``meta.phases[].model``) is not resolved: such a site counts as
inheriting, which errs towards saying more, never less.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

_OPENERS: Final[str] = "([{"
_CLOSER_OF: Final[dict[str, str]] = {")": "(", "]": "[", "}": "{"}
_QUOTES: Final[str] = "'\"`"
_SPREAD: Final[str] = "..."
_ARGS: Final[str] = "args"

_AGENT_CALL: Final[re.Pattern[str]] = re.compile(r"(?<![\w.$])agent\s*\(")
_MODEL_OPTION: Final[re.Pattern[str]] = re.compile(r"(?<![\w$])model\s*:")
_MAP_CALL: Final[re.Pattern[str]] = re.compile(r"\.\s*(?:map|flatMap|forEach)\s*\(")
_PIPELINE_CALL: Final[re.Pattern[str]] = re.compile(r"(?<![\w.$])pipeline\s*\(")
_ARRAY_FROM_CALL: Final[re.Pattern[str]] = re.compile(r"(?<![\w$])Array\s*\.\s*from\s*\(")
_FOR_HEADER: Final[re.Pattern[str]] = re.compile(r"(?<![\w.$])for\s*(?:await\s*)?\(")
_WHILE_HEADER: Final[re.Pattern[str]] = re.compile(r"(?<![\w.$])while\s*\(")
_DO_BLOCK: Final[re.Pattern[str]] = re.compile(r"(?<![\w.$])do\s*\{")
_LENGTH_LITERAL: Final[re.Pattern[str]] = re.compile(r"\{\s*length\s*:\s*(\d+)\s*\}")
_ARRAY_FROM_LENGTH: Final[re.Pattern[str]] = re.compile(
    r"Array\s*\.\s*from\s*\(\s*\{\s*length\s*:\s*(\d+)\s*\}\s*\)"
)
_FOR_OF: Final[re.Pattern[str]] = re.compile(r"^.*?\bof\b(.*)$", re.DOTALL)
_FOR_COUNTED: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:let|var)?\s*([A-Za-z_$][\w$]*)\s*=\s*(\d+)\s*;" r"\s*\1\s*(<=?)\s*(\d+)\s*;"
)
_RECEIVER_NAME: Final[re.Pattern[str]] = re.compile(r"[\w.$]+$")
_CALLEE_NAME: Final[re.Pattern[str]] = re.compile(r"[\w.$]+\s*$")


class Bucket(StrEnum):
    """How a site's fan-out was resolved."""

    EXACT = "exact"
    ARGS = "args"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AgentSite:
    """One ``agent(`` call site and how many agents it starts."""

    offset: int
    #: Agents this site starts, with each unknown multiplier counted as 1.
    multiplier: int
    bucket: Bucket
    has_model: bool


@dataclass(frozen=True)
class FanoutReading:
    """Every site of one script."""

    sites: tuple[AgentSite, ...]

    @property
    def total(self) -> int:
        """Agents the script starts; a lower bound when :attr:`has_unknown`."""
        return sum(site.multiplier for site in self.sites)

    @property
    def has_unknown(self) -> bool:
        return any(site.bucket is Bucket.UNKNOWN for site in self.sites)

    @property
    def unknown_sites(self) -> int:
        return sum(1 for site in self.sites if site.bucket is Bucket.UNKNOWN)

    @property
    def sites_without_model(self) -> int:
        return sum(1 for site in self.sites if not site.has_model)


@dataclass(frozen=True)
class _Region:
    start: int
    end: int
    multiplier: int
    bucket: Bucket


_UNKNOWN: Final[tuple[int, Bucket]] = (1, Bucket.UNKNOWN)


def _mask(script: str) -> str:
    """``script`` with string contents and comments blanked, offsets kept."""
    out = list(script)
    size = len(script)

    def blank(start: int, end: int) -> None:
        for index in range(start, min(end, size)):
            if out[index] != "\n":
                out[index] = " "

    index = 0
    while index < size:
        char = script[index]
        if char in _QUOTES:
            end = index + 1
            while end < size and script[end] != char:
                end += 2 if script[end] == "\\" else 1
            blank(index + 1, end)
            index = end + 1
        elif script.startswith("//", index):
            end = script.find("\n", index)
            end = size if end < 0 else end
            blank(index, end)
            index = end
        elif script.startswith("/*", index):
            end = script.find("*/", index + 2)
            end = size if end < 0 else end + 2
            blank(index, end)
            index = end
        else:
            index += 1
    return "".join(out)


def _pairs(code: str) -> dict[int, int]:
    """Opening offset -> closing offset of every balanced bracket."""
    stack: list[int] = []
    pairs: dict[int, int] = {}
    for index, char in enumerate(code):
        if char in _OPENERS:
            stack.append(index)
        elif char in _CLOSER_OF and stack and code[stack[-1]] == _CLOSER_OF[char]:
            pairs[stack.pop()] = index
    return pairs


def _split_top(code: str, start: int, end: int) -> list[str]:
    """The comma-separated items between ``start`` and ``end`` at bracket depth 0."""
    items: list[str] = []
    depth = 0
    last = start
    for index in range(start, end):
        char = code[index]
        if char in _OPENERS:
            depth += 1
        elif char in _CLOSER_OF:
            depth -= 1
        elif char == "," and depth == 0:
            items.append(code[last:index])
            last = index + 1
    items.append(code[last:end])
    return [item for item in items if item.strip()]


def _iterable(expr: str, args_len: int | None) -> tuple[int, Bucket]:
    """How many items ``expr`` (masked) iterates over."""
    expr = expr.strip()
    if expr == _ARGS:
        return (args_len, Bucket.ARGS) if args_len is not None else _UNKNOWN
    if expr.startswith("[") and _pairs(expr).get(0) == len(expr) - 1:
        items = _split_top(expr, 1, len(expr) - 1)
        if any(item.strip().startswith(_SPREAD) for item in items):
            return _UNKNOWN
        return len(items), Bucket.EXACT
    length = _ARRAY_FROM_LENGTH.fullmatch(expr)
    if length is not None:
        return int(length.group(1)), Bucket.EXACT
    return _UNKNOWN


def _receiver(code: str, pairs: dict[int, int], dot: int) -> str:
    """The expression ``.map`` at ``dot`` is called on."""
    end = dot
    while end > 0 and code[end - 1].isspace():
        end -= 1
    if end == 0:
        return ""
    last = code[end - 1]
    if last in "])":
        closers = {close: open_ for open_, close in pairs.items()}
        start = closers.get(end - 1)
        if start is None:
            return ""
        if last == ")":
            callee = _CALLEE_NAME.search(code, 0, start)
            start = callee.start() if callee is not None else start
        return code[start:end]
    name = _RECEIVER_NAME.search(code, 0, end)
    return name.group(0) if name is not None else ""


def _body(code: str, pairs: dict[int, int], after: int) -> tuple[int, int] | None:
    """The statement or block following a loop header that ends at ``after``."""
    start = after
    while start < len(code) and code[start].isspace():
        start += 1
    if start >= len(code) or code[start] == ";":
        return None
    if code[start] == "{":
        return start, pairs.get(start, len(code))
    end = code.find(";", start)
    return start, len(code) if end < 0 else end


def _loop_count(header: str, args_len: int | None) -> tuple[int, Bucket]:
    counted = _FOR_COUNTED.match(header)
    if counted is not None:
        first, last = int(counted.group(2)), int(counted.group(4))
        count = last - first + (1 if counted.group(3) == "<=" else 0)
        return max(count, 0), Bucket.EXACT
    of_loop = _FOR_OF.match(header)
    if of_loop is not None:
        return _iterable(of_loop.group(1), args_len)
    return _UNKNOWN


def _regions(code: str, pairs: dict[int, int], args_len: int | None) -> list[_Region]:
    size = len(code)
    regions: list[_Region] = []

    def add(start: int, end: int, count: tuple[int, Bucket]) -> None:
        regions.append(_Region(start, end, count[0], count[1]))

    for match in _MAP_CALL.finditer(code):
        open_ = match.end() - 1
        add(
            open_,
            pairs.get(open_, size),
            _iterable(_receiver(code, pairs, match.start()), args_len),
        )
    for match in _PIPELINE_CALL.finditer(code):
        open_ = match.end() - 1
        close = pairs.get(open_, size)
        items = _split_top(code, open_ + 1, close)
        add(open_, close, _iterable(items[0], args_len) if items else _UNKNOWN)
    for match in _ARRAY_FROM_CALL.finditer(code):
        open_ = match.end() - 1
        close = pairs.get(open_, size)
        items = _split_top(code, open_ + 1, close)
        if len(items) >= 2:
            length = _LENGTH_LITERAL.fullmatch(items[0].strip())
            add(open_, close, (int(length.group(1)), Bucket.EXACT) if length else _UNKNOWN)
    for pattern, counted in ((_FOR_HEADER, True), (_WHILE_HEADER, False)):
        for match in pattern.finditer(code):
            open_ = match.end() - 1
            close = pairs.get(open_, size)
            body = _body(code, pairs, close + 1)
            if body is not None:
                count = _loop_count(code[open_ + 1 : close], args_len) if counted else _UNKNOWN
                add(body[0], body[1], count)
    for match in _DO_BLOCK.finditer(code):
        open_ = match.end() - 1
        add(open_, pairs.get(open_, size), _UNKNOWN)
    return regions


def mentions_agent_call(script: str) -> bool:
    """Whether the RAW script text calls ``agent(`` anywhere, strings and comments included.

    The reader blanks what it takes for strings: a regex literal holding a quote
    swallows the rest of the script, and a call inside a template ``${...}`` is
    blanked with the template. When it then finds no site but this is True, the
    script's fan-out is unread, not absent.
    """
    return _AGENT_CALL.search(script) is not None


def analyse_script(script: str, *, args_len: int | None) -> FanoutReading:
    """Every ``agent(`` site of ``script`` with its multiplier, bucket and model option.

    ``args_len`` is the length of the call's ``args`` array, or None when the
    call passed none (an ``args``-driven fan-out is then unknown).
    """
    code = _mask(script)
    pairs = _pairs(code)
    regions = _regions(code, pairs, args_len)
    sites: list[AgentSite] = []
    for match in _AGENT_CALL.finditer(code):
        open_ = match.end() - 1
        close = pairs.get(open_, len(code))
        multiplier = 1
        buckets: set[Bucket] = set()
        for region in regions:
            if region.start < match.start() < region.end:
                multiplier *= region.multiplier
                buckets.add(region.bucket)
        bucket = (
            Bucket.UNKNOWN
            if Bucket.UNKNOWN in buckets
            else Bucket.ARGS if Bucket.ARGS in buckets else Bucket.EXACT
        )
        sites.append(
            AgentSite(
                offset=match.start(),
                multiplier=multiplier,
                bucket=bucket,
                has_model=_MODEL_OPTION.search(code, open_, close) is not None,
            )
        )
    return FanoutReading(sites=tuple(sites))
