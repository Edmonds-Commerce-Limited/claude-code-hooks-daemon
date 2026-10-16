"""The model-family rank table, shared by the status line and the tier handlers (Plan 00472).

One table answers "which family is this model, and how capable is it" for every
consumer: the downgrade indicator compares a render's family with the session's
high-water mark, and the subagent tier handlers compare a dispatch's predicted
family with a ceiling or a floor. Two tables would drift, and a drift here
mislabels a downgrade or names the wrong cheaper tier.

A model is named either by an alias (``opus``) or by a full id
(``claude-opus-5-5``); both resolve by case-insensitive substring. ``inherit``
and anything unrecognised resolve to None, which every consumer treats as "no
opinion": never a downgrade, never an advisory.
"""

from __future__ import annotations

from typing import Final

HAIKU: Final[str] = "haiku"
SONNET: Final[str] = "sonnet"
OPUS: Final[str] = "opus"
FABLE: Final[str] = "fable"

#: Families from least to most capable; the index is the rank.
FAMILIES: Final[tuple[str, ...]] = (HAIKU, SONNET, OPUS, FABLE)

# `mythos` is a known alias that canonicalises to the `fable` family and rank.
_FAMILY_SUBSTRINGS: Final[tuple[tuple[str, str], ...]] = (
    ("haiku", HAIKU),
    ("sonnet", SONNET),
    ("opus", OPUS),
    ("fable", FABLE),
    ("mythos", FABLE),
)

#: The built-in Explore agent inherits the main model capped at this family on
#: the Claude API (sub-agents.md, "Explore").
EXPLORE_CAP_FAMILY: Final[str] = OPUS


def resolve_model_family(model_id: str) -> tuple[str, int] | None:
    """Resolve an alias or full model id to ``(family, rank)``, or None when unknown.

    Args:
        model_id: An alias (``"opus"``) or a full id (``"claude-opus-5-5"``),
            matched by case-insensitive substring.
    """
    if not model_id:
        return None
    lowered = model_id.lower()
    for substring, family in _FAMILY_SUBSTRINGS:
        if substring in lowered:
            return family, FAMILIES.index(family)
    return None


def family_rank(family: str) -> int | None:
    """The rank of a canonical family name, or None for one this table does not know."""
    return FAMILIES.index(family) if family in FAMILIES else None


def family_below(family: str) -> str | None:
    """The next cheaper family, or None at the bottom of the ladder or for an unknown one."""
    rank = family_rank(family)
    if rank is None or rank == 0:
        return None
    return FAMILIES[rank - 1]


def predicted_explore_family(main_family: str) -> str:
    """The family built-in Explore runs on under a ``main_family`` session."""
    main_rank = family_rank(main_family)
    cap_rank = FAMILIES.index(EXPLORE_CAP_FAMILY)
    if main_rank is not None and main_rank > cap_rank:
        return EXPLORE_CAP_FAMILY
    return main_family
