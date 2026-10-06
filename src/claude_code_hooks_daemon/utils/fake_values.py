"""The fake-values registry: the one list of approved FAKE values used in docs (Plan 00492).

Docs and vendored pages need example session ids, tokens and the like. A real
credential must never appear, but a sensitive-content pattern cannot tell a
real UUID from an invented one by shape alone. The owner's ruling (Plan 00483
D1) is a single registry: a value that is EXACTLY on the list is allowed, and
anything else keeps being judged as before.

A registry entry belongs to a *kind*, and a kind is named after the
``sensitive_content`` public pattern it exempts (``session-uuid``). Declaring
a new kind of fake therefore means adding a key here; nothing else keeps a
second list.

The file lives at :data:`REGISTRY_RELATIVE_PATH` and is read by every surface
that judges a fake: the ``sensitive_content`` handler, its whole-tree QA
scanner, the ``unlisted-fake-value`` docs QA check and ``remote-docs add``.
A missing file is an empty registry (nothing is exempt); a malformed one
raises :class:`FakeValuesError`, because a guard that silently reads an
unparseable list as empty would look strict while ignoring the project's
intent.
"""

import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import yaml

#: Where a project keeps its registry, relative to the project root.
REGISTRY_RELATIVE_PATH: Final[str] = ".claude/fake-values.yaml"

_KEY_KINDS: Final[str] = "kinds"
_KEY_DESCRIPTION: Final[str] = "description"
_KEY_FAKE_LOOKING: Final[str] = "fake_looking"
_KEY_VALUES: Final[str] = "values"
_KIND_KEYS: Final[frozenset[str]] = frozenset({_KEY_DESCRIPTION, _KEY_FAKE_LOOKING, _KEY_VALUES})


class FakeValuesError(ValueError):
    """The registry is malformed, or a swap cannot be completed."""


@dataclass(frozen=True)
class FakeKind:
    """One kind of fake value and the exact values approved for it."""

    name: str
    values: tuple[str, ...]
    description: str = ""
    #: What a fake of this kind LOOKS like, so an unlisted one can be reported.
    fake_looking: re.Pattern[str] | None = None


@dataclass(frozen=True)
class ValueSwap:
    """One swap of an unlisted fake for a listed one, as recorded in provenance.

    The original value is deliberately NOT stored: it is exactly the text the
    sensitive-content patterns refused, so recording it would trip them again.
    Its hash still lets a reader confirm which upstream value was swapped.
    """

    kind: str
    replacement: str
    occurrences: int
    original_sha256: str


#: Text in, the same text with unlisted fakes swapped plus the record of each swap.
ValueSwapper = Callable[[str], tuple[str, tuple[ValueSwap, ...]]]


@dataclass(frozen=True)
class FakeValuesRegistry:
    """The approved fakes, by kind."""

    kinds: Mapping[str, FakeKind] = field(default_factory=dict)

    @property
    def kind_names(self) -> tuple[str, ...]:
        """Names of every registered kind."""
        return tuple(self.kinds)

    def allows(self, kind: str, value: str) -> bool:
        """Whether ``value`` is EXACTLY one of the approved fakes of ``kind``."""
        entry = self.kinds.get(kind)
        return entry is not None and value in entry.values

    def unlisted_fake_looking(self, text: str) -> list[tuple[str, str]]:
        """Fake-looking values in ``text`` that are not on the registry, as ``(kind, value)``."""
        found: list[tuple[str, str]] = []
        for entry in self.kinds.values():
            if entry.fake_looking is None:
                continue
            for match in entry.fake_looking.finditer(text):
                if match.group(0) not in entry.values:
                    found.append((entry.name, match.group(0)))
        return found


def _parse_kind(name: str, raw: Any, source: Path) -> FakeKind:
    if not isinstance(raw, dict):
        raise FakeValuesError(f"{source}: kind `{name}` must be a mapping")
    unknown = set(raw) - _KIND_KEYS
    if unknown:
        raise FakeValuesError(f"{source}: kind `{name}` has unknown key(s): {sorted(unknown)}")

    raw_values = raw.get(_KEY_VALUES)
    if not isinstance(raw_values, list) or not raw_values:
        raise FakeValuesError(f"{source}: kind `{name}` needs a non-empty `values` list")
    values: list[str] = []
    for item in raw_values:
        if not isinstance(item, str) or not item:
            raise FakeValuesError(f"{source}: kind `{name}` values must be non-empty strings")
        if item in values:
            raise FakeValuesError(f"{source}: kind `{name}` lists {item!r} more than once")
        values.append(item)

    fake_looking: re.Pattern[str] | None = None
    raw_pattern = raw.get(_KEY_FAKE_LOOKING)
    if raw_pattern is not None:
        try:
            fake_looking = re.compile(str(raw_pattern), re.IGNORECASE)
        except re.error as exc:
            raise FakeValuesError(
                f"{source}: kind `{name}` `fake_looking` is not a valid regex ({exc})"
            ) from exc
    return FakeKind(
        name=name,
        values=tuple(values),
        description=str(raw.get(_KEY_DESCRIPTION, "")),
        fake_looking=fake_looking,
    )


def load_fake_values(project_root: Path) -> FakeValuesRegistry:
    """Read the registry under ``project_root``.

    A missing file is an empty registry, so a project that keeps none exempts
    nothing.

    Raises:
        FakeValuesError: The file exists but cannot be read or does not follow
            the schema.
    """
    source = project_root / REGISTRY_RELATIVE_PATH
    if not source.is_file():
        return FakeValuesRegistry()
    try:
        loaded = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise FakeValuesError(f"{source}: cannot be read as YAML ({exc})") from exc
    if not isinstance(loaded, dict) or not isinstance(loaded.get(_KEY_KINDS), dict):
        raise FakeValuesError(f"{source}: must hold a `{_KEY_KINDS}` mapping")
    return FakeValuesRegistry(
        kinds={
            str(name): _parse_kind(str(name), raw, source)
            for name, raw in loaded[_KEY_KINDS].items()
        }
    )


def swap_unlisted_fakes(
    text: str,
    patterns: Mapping[str, re.Pattern[str]],
    registry: FakeValuesRegistry,
) -> tuple[str, tuple[ValueSwap, ...]]:
    """Replace every unlisted fake in ``text`` with a listed fake of the same kind.

    ``patterns`` maps a kind name to the public-pattern regex that judges it;
    a kind's own ``fake_looking`` regex is applied as well. Only kinds the
    registry lists are touched. Occurrences of one original share one
    replacement and distinct originals get distinct ones, so a page that keeps
    two sessions apart still does. A listed value already in ``text`` is left
    alone and never reused as a replacement.

    Raises:
        FakeValuesError: A kind has fewer unused listed fakes than the text
            has distinct originals to replace.
    """
    swaps: list[ValueSwap] = []
    for name, entry in registry.kinds.items():
        regexes = [rx for rx in (patterns.get(name), entry.fake_looking) if rx is not None]
        found: list[tuple[int, str]] = []
        for regex in regexes:
            found.extend((m.start(), m.group(0)) for m in regex.finditer(text))
        found.sort()
        listed_present = {value for _, value in found if value in entry.values}
        originals = list(dict.fromkeys(v for _, v in found if v not in entry.values))
        if not originals:
            continue

        pool = [value for value in entry.values if value not in listed_present]
        if len(pool) < len(originals):
            raise FakeValuesError(
                f"kind `{name}` has {len(originals)} distinct unlisted value(s) to replace but "
                f"no unused listed fake for each ({len(pool)} available); extend "
                f"{REGISTRY_RELATIVE_PATH}"
            )
        mapping = dict(zip(originals, pool, strict=False))
        counts = dict.fromkeys(originals, 0)

        def replace(
            match: re.Match[str], mapping: dict[str, str] = mapping, counts: dict[str, int] = counts
        ) -> str:
            value = match.group(0)
            if value not in mapping:
                return value
            counts[value] += 1
            return mapping[value]

        for regex in regexes:
            text = regex.sub(replace, text)
        swaps.extend(
            ValueSwap(
                kind=name,
                replacement=mapping[original],
                occurrences=counts[original],
                original_sha256=hashlib.sha256(original.encode("utf-8")).hexdigest(),
            )
            for original in originals
        )
    return text, tuple(swaps)
