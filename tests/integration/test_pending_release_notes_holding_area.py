"""Plan 00360 — the pending release-notes holding area keeps its schema.

A plan closes by leaving a callout in ``CLAUDE/UPGRADES/UNRELEASED/release-notes/``
and the release folds every callout into ``RELEASES/vX.Y.Z.md`` mechanically.
That only works if every callout is the shape the README promises: a
``# Callout:`` title, the plan it came from, an audience the release notes
can group by, and a body in the notes' own voice. This test reads the real
holding area so a malformed callout fails CI at the plan's commit, not at
the release.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.release_slate import PENDING_RELEASE_NOTES_DIR

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOLDING_AREA = _REPO_ROOT / PENDING_RELEASE_NOTES_DIR
_CALLOUT_NAME = re.compile(r"^\d{2}-[a-z0-9]+(-[a-z0-9]+)*\.md$")
_PLAN_LINE = re.compile(r"^\*\*Plan\*\*: \d{5}$", re.MULTILINE)
_AUDIENCE_LINE = re.compile(
    r"^\*\*Audience\*\*: (operators|handler authors|client projects|everyone)$",
    re.MULTILINE,
)


def _callouts() -> list[Path]:
    return sorted(p for p in _HOLDING_AREA.iterdir() if p.is_file() and p.name != "README.md")


def test_the_holding_area_exists_with_its_readme() -> None:
    assert (_HOLDING_AREA / "README.md").is_file()


def test_the_readme_documents_the_schema_the_release_relies_on() -> None:
    text = (_HOLDING_AREA / "README.md").read_text(encoding="utf-8")
    assert "# Callout:" in text
    assert "**Plan**" in text
    assert "**Audience**" in text


@pytest.mark.parametrize("callout", _callouts(), ids=lambda p: p.name)
def test_every_pending_callout_is_the_shape_the_release_folds_in(callout: Path) -> None:
    assert _CALLOUT_NAME.match(callout.name), f"{callout.name}: expected NN-kebab-slug.md"
    text = callout.read_text(encoding="utf-8")
    title, _, body = text.partition("\n")
    assert title.startswith("# Callout: ") and len(title) > len("# Callout: ")
    assert _PLAN_LINE.search(body), f"{callout.name}: missing `**Plan**: NNNNN`"
    assert _AUDIENCE_LINE.search(body), f"{callout.name}: missing or unknown `**Audience**`"
    prose = body.split("**Audience**", 1)[1].partition("\n")[2].strip()
    assert prose, f"{callout.name}: no sentence after the headers"
