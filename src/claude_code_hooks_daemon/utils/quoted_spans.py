"""Blank quoted spans so a MENTIONED phrase is not read as a USED one.

Plan 00225. Content-scanning advisories (dismissive language, hedging language)
match their trigger phrases by plain substring, which cannot separate:

- a phrase USED to deflect  -- "that is out of scope"
- a phrase MENTIONED        -- 'the hook flagged my "out of scope"'

The advisory those detectors emit asks the agent to acknowledge rather than
deflect, and naming the phrase is how one acknowledges — so complying with the
instruction re-triggered it.

The approach mirrors ``pipe_blocker._strip_message_bodies`` (Plan 00222): the
pattern lists are NOT touched. A copy of the text is scanned with the exempt
spans blanked, so a real trigger anywhere else in the same text is still found.
"""

from __future__ import annotations

import re

# Only DOUBLE quotes and BACKTICKS mark a mention. Single quotes deliberately
# do NOT: an apostrophe inside an ordinary English word ("doesn't", "it's")
# reads as an opening quote, and pairing on those would blank arbitrary spans
# of real sentences. A blanked span is a span the detector can no longer see,
# so that failure mode is silence — strictly worse than the noise being fixed.
# `pipe_blocker` records the same constraint for the same reason.
#
# Each alternative requires a CLOSING delimiter, so an unterminated quote
# matches nothing and the text is scanned intact (fail open).
_QUOTED_SPAN_PATTERN = re.compile(r'"[^"\n]*"|`[^`\n]*`')

# Blanking preserves LENGTH rather than deleting, so character offsets into the
# scanned copy still line up with the original text.
_BLANK_CHARACTER = " "


def blank_quoted_spans(text: str) -> str:
    """Return ``text`` with the contents of quoted spans replaced by spaces.

    The delimiters are blanked along with their contents; only double-quoted
    and backticked spans are affected. Text outside them is returned verbatim,
    so a genuine trigger phrase sitting beside a quotation is still detected.

    Args:
        text: The message text to normalise before pattern matching.

    Returns:
        A same-length copy with quoted spans blanked out.
    """
    if not text:
        return text

    return _QUOTED_SPAN_PATTERN.sub(lambda m: _BLANK_CHARACTER * len(m.group(0)), text)
