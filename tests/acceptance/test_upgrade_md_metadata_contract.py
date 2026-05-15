"""Acceptance test: skill upgrade.md references the metadata contract symmetrically.

Plan 00109 Phase 3 Task 3.2 — every field the Layer 1 `scripts/upgrade.sh`
emits inside the `<<<UPGRADE_METADATA` … `UPGRADE_METADATA>>>` block MUST be
referenced in the skill `upgrade.md`, and every field referenced in
`upgrade.md` MUST exist in the script's emission contract. This catches
silent drift: if a future patch adds or removes a metadata field, this test
fails until `upgrade.md` is updated to match.

The test is intentionally cheap — no subprocess, no fixture project — so
it can run on every commit without slowing the suite down.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LAYER1_UPGRADE_SH = _REPO_ROOT / "scripts" / "upgrade.sh"
_SKILL_UPGRADE_MD = (
    _REPO_ROOT / "src" / "claude_code_hooks_daemon" / "skills" / "hooks-daemon" / "upgrade.md"
)

_OPEN_SENTINEL = "<<<UPGRADE_METADATA"
_CLOSE_SENTINEL = "UPGRADE_METADATA>>>"

_PRINTF_FIELD_RE = re.compile(r"^\s*printf\s+'([a-z_]+)=%s\\n'", re.MULTILINE)


def _extract_emitted_fields() -> list[str]:
    """Parse Layer 1 upgrade.sh and return the metadata fields it emits.

    Looks for `printf 'NAME=%s\\n' VALUE` lines between the two sentinels.
    """
    text = _LAYER1_UPGRADE_SH.read_text(encoding="utf-8")
    open_idx = text.find(_OPEN_SENTINEL)
    close_idx = text.find(_CLOSE_SENTINEL)
    assert open_idx != -1, f"open sentinel {_OPEN_SENTINEL!r} not found in {_LAYER1_UPGRADE_SH}"
    assert close_idx != -1, f"close sentinel {_CLOSE_SENTINEL!r} not found in {_LAYER1_UPGRADE_SH}"
    assert close_idx > open_idx, "close sentinel must come after open"

    block = text[open_idx : close_idx + len(_CLOSE_SENTINEL)]
    fields = _PRINTF_FIELD_RE.findall(block)
    assert fields, f"no metadata fields parsed from {_LAYER1_UPGRADE_SH}"
    return fields


def _extract_referenced_fields() -> set[str]:
    """Return every field-shaped token referenced in upgrade.md.

    A field reference is any backtick-quoted lowercase_underscore identifier
    that matches a metadata field name. This keeps the test simple and
    deterministic — agents reading upgrade.md learn the field names from
    these references.
    """
    md_text = _SKILL_UPGRADE_MD.read_text(encoding="utf-8")
    backtick_tokens = re.findall(r"`([a-z_][a-z0-9_]*)`", md_text)
    return set(backtick_tokens)


def test_every_emitted_field_is_referenced_in_upgrade_md() -> None:
    """Every field Layer 1 emits MUST appear in upgrade.md."""
    emitted = _extract_emitted_fields()
    referenced = _extract_referenced_fields()
    missing = [field for field in emitted if field not in referenced]
    assert not missing, (
        f"upgrade.md is missing references to metadata fields emitted by "
        f"scripts/upgrade.sh: {missing}. Update "
        f"{_SKILL_UPGRADE_MD.relative_to(_REPO_ROOT)} to mention them."
    )


def test_no_phantom_field_references_in_upgrade_md() -> None:
    """Every metadata field referenced in upgrade.md MUST exist in the contract.

    upgrade.md may mention non-metadata identifiers (`bash`, `git`, etc.) —
    those are filtered out by checking only tokens that look like metadata
    field names (snake_case with at least one underscore).
    """
    emitted = set(_extract_emitted_fields())
    referenced = _extract_referenced_fields()
    snake_case_tokens = {tok for tok in referenced if "_" in tok}

    contract_like = {
        tok
        for tok in snake_case_tokens
        if tok.endswith(("_version", "_path", "_root", "_dir", "_files", "_summary"))
        or tok in {"host", "from_version", "to_version"}
    }

    phantom = [tok for tok in contract_like if tok not in emitted]
    assert not phantom, (
        f"upgrade.md references metadata fields not in the script's "
        f"emission contract: {phantom}. Either add them to "
        f"scripts/upgrade.sh metadata emission, or remove the stale "
        f"references from {_SKILL_UPGRADE_MD.relative_to(_REPO_ROOT)}."
    )


def test_open_and_close_sentinels_appear_in_upgrade_md() -> None:
    """upgrade.md must mention both sentinels so the agent knows the parse markers."""
    md_text = _SKILL_UPGRADE_MD.read_text(encoding="utf-8")
    assert (
        _OPEN_SENTINEL in md_text
    ), f"open sentinel {_OPEN_SENTINEL!r} not mentioned in upgrade.md"
    assert (
        _CLOSE_SENTINEL in md_text
    ), f"close sentinel {_CLOSE_SENTINEL!r} not mentioned in upgrade.md"


def test_layer1_script_and_skill_md_both_exist() -> None:
    """Sanity check — both files the test compares are present in the repo."""
    assert _LAYER1_UPGRADE_SH.is_file(), f"missing {_LAYER1_UPGRADE_SH}"
    assert _SKILL_UPGRADE_MD.is_file(), f"missing {_SKILL_UPGRADE_MD}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
