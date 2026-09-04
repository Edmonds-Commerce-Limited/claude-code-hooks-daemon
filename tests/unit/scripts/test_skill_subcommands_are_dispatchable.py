"""A skill subcommand a human is told to type must actually dispatch.

Client-facing gap found while auditing the hooks-daemon skill: `optimise` was
documented in THREE places -- SKILL.md's own "Optimise Configuration" section,
`optimise.md`, and `upgrade.md` step 8, which calls it mandatory and says the
upgrade "is not finished until it has run" -- while being absent from the
`case` statement that routes subcommands. Typing `/hooks-daemon optimise` fell
through to the unknown-subcommand branch.

The sibling test `test_skill_scripts_are_referenced` did not catch it and
could not: it asks whether a bundled SCRIPT is mentioned by any markdown, and
`optimise-invoke.sh` was mentioned -- by `optimise.md`. The unchecked
direction is the other one: a subcommand the docs tell a human to type, that
the router does not answer.

The skill is the human-touching surface, so this is checked for EVERY release
rather than left to be noticed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

#: The tracked SOURCE, which is what ships to clients and what a fix must
#: land in.
_SOURCE_SKILL_MD: Final[Path] = (
    _REPO_ROOT / "src" / "claude_code_hooks_daemon" / "skills" / "hooks-daemon" / "SKILL.md"
)

#: The project's own DEPLOYED copy. Gitignored -- absent in a fresh clone and
#: in CI -- so every check over it skips rather than fails when it is missing.
#: It is still worth checking where it exists, because that is the copy this
#: repo actually runs, and a fix made only here is discarded on next deploy.
_DEPLOYED_SKILL_MD: Final[Path] = _REPO_ROOT / ".claude" / "skills" / "hooks-daemon" / "SKILL.md"

_SKILL_MDS: Final[tuple[Path, ...]] = (_DEPLOYED_SKILL_MD, _SOURCE_SKILL_MD)

#: A `/hooks-daemon <word>` occurrence in prose is a subcommand the docs are
#: telling a human to type.
#:
#: The lookbehind separates the SLASH COMMAND from the CLI wrapper: the docs
#: also carry `.claude/hooks-daemon/bin/hooks-daemon plan-qa --sweep`, whose
#: path contains a literal `/hooks-daemon `. `plan-qa` is deliberately a CLI
#: command and NOT a skill subcommand, so matching it here would demand a
#: routing arm for something no one is told to type as `/hooks-daemon plan-qa`.
_INVOCATION_RE: Final[re.Pattern[str]] = re.compile(r"(?<![\w./-])/hooks-daemon\s+([a-z][a-z-]*)")

#: Left-hand sides of the routing `case`, e.g. `logs|status|restart)`.
_CASE_ARM_RE: Final[re.Pattern[str]] = re.compile(r"^\s{4}([a-z|\-\"'_ ]+)\)\s*$", re.MULTILINE)

#: The fallback arm and its flag spellings. It prints the help rather than
#: naming a capability, so it is neither documented as a subcommand nor
#: expected to list itself.
_NOT_SUBCOMMANDS: Final[frozenset[str]] = frozenset({"help", "--help", "-h", ""})


def _documented_subcommands(text: str) -> set[str]:
    return {name for name in _INVOCATION_RE.findall(text) if name not in _NOT_SUBCOMMANDS}


def _case_arms(text: str) -> list[list[str]]:
    """Each routing arm as its list of accepted spellings.

    Kept grouped rather than flattened because an arm's alternatives are
    ALIASES of one subcommand (`regen-docs|regenerate-docs`), and the help
    text is expected to name the subcommand once, not every spelling.
    """
    arms: list[list[str]] = []
    for arm in _CASE_ARM_RE.findall(text):
        names = [name.strip().strip("\"'") for name in arm.split("|")]
        cleaned = [name for name in names if name and name.isascii()]
        if cleaned:
            arms.append(cleaned)
    return arms


def _dispatchable_subcommands(text: str) -> set[str]:
    return {name for arm in _case_arms(text) for name in arm}


@pytest.mark.parametrize("skill_md", _SKILL_MDS, ids=lambda p: p.parts[-4])
def test_every_documented_subcommand_is_dispatchable(skill_md: Path) -> None:
    if not skill_md.is_file():
        pytest.skip(f"{skill_md} absent (gitignored deployed copy, not in a fresh clone)")
    text = skill_md.read_text(encoding="utf-8")
    documented = _documented_subcommands(text)
    dispatchable = _dispatchable_subcommands(text)

    undispatchable = sorted(documented - dispatchable)
    assert not undispatchable, (
        f"{skill_md.relative_to(_REPO_ROOT)} tells a human to type "
        f"{undispatchable}, but the routing `case` has no arm for them, so the "
        "invocation hits the unknown-subcommand branch. Add a case arm, or "
        "stop documenting it as a subcommand."
    )


@pytest.mark.parametrize("skill_md", _SKILL_MDS, ids=lambda p: p.parts[-4])
def test_every_dispatchable_subcommand_is_listed_in_help(skill_md: Path) -> None:
    """The help text is how a human discovers the surface.

    A subcommand that routes but is absent from `help` is undiscoverable
    without reading the source -- the same defect as an undispatchable one,
    seen from the other side.
    """
    if not skill_md.is_file():
        pytest.skip(f"{skill_md} absent (gitignored deployed copy, not in a fresh clone)")
    text = skill_md.read_text(encoding="utf-8")
    help_listed = set(re.findall(r'echo "  ([a-z][a-z-]*)', text))

    # One spelling in `help` makes the arm discoverable -- listing every alias
    # would pad the help text with `optimize` and `regenerate-docs`, which
    # exist so a near-miss does not hit the unknown-subcommand branch, not
    # because a human should be taught two names for one command. The help arm
    # itself documents nothing and is skipped.
    missing = sorted(
        arm[0]
        for arm in _case_arms(text)
        if not (set(arm) & help_listed) and not (set(arm) & _NOT_SUBCOMMANDS)
    )
    assert not missing, (
        f"{skill_md.relative_to(_REPO_ROOT)} routes {missing} but names no "
        "spelling of them in the `help` output, so a human cannot discover them."
    )


def test_the_two_skill_trees_do_not_drift() -> None:
    """The deployed copy is overwritten from the source on every upgrade.

    Fixing only the deployed one produces a fix that works until the next
    upgrade silently discards it -- so a divergence is a defect regardless of
    which copy is 'right'.
    """
    if not _DEPLOYED_SKILL_MD.is_file():
        pytest.skip("deployed copy absent (gitignored, not present in a fresh clone)")
    deployed = _DEPLOYED_SKILL_MD.read_text(encoding="utf-8")
    source = _SOURCE_SKILL_MD.read_text(encoding="utf-8")
    assert deployed == source, (
        "`.claude/skills/hooks-daemon/SKILL.md` and its `src/` source have "
        "diverged. The deployed copy is refreshed from the source on upgrade, "
        "so any edit must be made to BOTH."
    )
