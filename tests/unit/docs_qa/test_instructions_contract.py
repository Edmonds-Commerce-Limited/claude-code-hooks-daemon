"""The Claude Code instruction-loading contract: schema, loader and anchor verification (Plan 00532)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.docs_qa.instructions_contract import (
    CONTRACT_DIR_RELATIVE,
    InstructionsContractError,
    heading_slug,
    load_contract,
    verify_anchors,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

PAGE = """# Title

## How files load

Files in the tree load at launch. Subdirectories load on demand.

### Imports

Imports go four hops deep.

## Other

Nothing here.
"""


def _meta() -> dict[str, Any]:
    return {
        "docs_url": "https://example.test/memory",
        "fetch_date": "2026-10-17",
        "docs_bytes": 10,
        "docs_sha256": "a" * 64,
        "vendored_path": "remote-docs/example.test/memory.md",
        "last_audited_claude_code_version": "2.1.302",
        "refresh_procedure": "docs/guides/HOOK-CONTRACT-REFRESH.md",
    }


def _fact(**overrides: Any) -> dict[str, Any]:
    fact: dict[str, Any] = {
        "id": "G1-01",
        "group": "G1",
        "statement": "Files in the tree load at launch.",
        "anchor": {"heading": "how-files-load", "quote": "load at launch"},
        "min_claude_code_version": None,
    }
    fact.update(overrides)
    return fact


def _write(
    directory: Path, meta: dict[str, Any] | None = None, facts_doc: dict[str, Any] | None = None
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "META.json").write_text(json.dumps(meta or _meta()), encoding="utf-8")
    document = facts_doc if facts_doc is not None else {"facts": [_fact()], "unmodelled": []}
    (directory / "FACTS.json").write_text(json.dumps(document), encoding="utf-8")
    return directory


class TestHeadingSlug:
    def test_lowercases_and_dashes_punctuation(self) -> None:
        assert heading_slug("How CLAUDE.md files load") == "how-claude-md-files-load"

    def test_drops_backticks_and_collapses_runs(self) -> None:
        assert heading_slug("Organize rules with `.claude/rules/`") == (
            "organize-rules-with-claude-rules"
        )


class TestLoadContract:
    def test_loads_a_valid_contract(self, tmp_path: Path) -> None:
        contract = load_contract(_write(tmp_path / "c"))
        assert contract.meta.last_audited_claude_code_version == "2.1.302"
        assert contract.meta.vendored_path == "remote-docs/example.test/memory.md"
        assert [f.id for f in contract.facts] == ["G1-01"]
        assert contract.facts[0].anchor.heading == "how-files-load"
        assert contract.facts[0].min_claude_code_version is None

    def test_unmodelled_entries_are_loaded(self, tmp_path: Path) -> None:
        doc = {
            "facts": [_fact()],
            "unmodelled": [{"id": "claudeMdExcludes", "description": "Excluded paths."}],
        }
        contract = load_contract(_write(tmp_path / "c", facts_doc=doc))
        assert [u.id for u in contract.unmodelled] == ["claudeMdExcludes"]

    def test_missing_directory_fails(self, tmp_path: Path) -> None:
        with pytest.raises(InstructionsContractError, match="META.json"):
            load_contract(tmp_path / "absent")

    def test_missing_audited_version_fails(self, tmp_path: Path) -> None:
        meta = _meta()
        del meta["last_audited_claude_code_version"]
        with pytest.raises(InstructionsContractError, match="last_audited_claude_code_version"):
            load_contract(_write(tmp_path / "c", meta=meta))

    def test_non_version_audited_value_fails(self, tmp_path: Path) -> None:
        meta = _meta()
        meta["last_audited_claude_code_version"] = "latest"
        with pytest.raises(InstructionsContractError, match="last_audited_claude_code_version"):
            load_contract(_write(tmp_path / "c", meta=meta))

    @pytest.mark.parametrize("key", ["docs_url", "fetch_date", "docs_sha256", "vendored_path"])
    def test_missing_provenance_key_fails(self, tmp_path: Path, key: str) -> None:
        meta = _meta()
        del meta[key]
        with pytest.raises(InstructionsContractError, match=key):
            load_contract(_write(tmp_path / "c", meta=meta))

    def test_fact_without_anchor_fails(self, tmp_path: Path) -> None:
        fact = _fact()
        del fact["anchor"]
        with pytest.raises(InstructionsContractError, match="G1-01.*anchor"):
            load_contract(_write(tmp_path / "c", facts_doc={"facts": [fact], "unmodelled": []}))

    def test_fact_with_empty_quote_fails(self, tmp_path: Path) -> None:
        fact = _fact(anchor={"heading": "how-files-load", "quote": ""})
        with pytest.raises(InstructionsContractError, match="G1-01.*quote"):
            load_contract(_write(tmp_path / "c", facts_doc={"facts": [fact], "unmodelled": []}))

    def test_duplicate_fact_ids_fail(self, tmp_path: Path) -> None:
        doc = {"facts": [_fact(), _fact()], "unmodelled": []}
        with pytest.raises(InstructionsContractError, match="duplicate"):
            load_contract(_write(tmp_path / "c", facts_doc=doc))

    def test_bad_min_version_fails(self, tmp_path: Path) -> None:
        doc = {"facts": [_fact(min_claude_code_version="soon")], "unmodelled": []}
        with pytest.raises(InstructionsContractError, match="min_claude_code_version"):
            load_contract(_write(tmp_path / "c", facts_doc=doc))

    def test_group_outside_modelled_set_fails(self, tmp_path: Path) -> None:
        doc = {"facts": [_fact(group="G6")], "unmodelled": []}
        with pytest.raises(InstructionsContractError, match="group"):
            load_contract(_write(tmp_path / "c", facts_doc=doc))

    def test_corrupt_json_fails(self, tmp_path: Path) -> None:
        directory = _write(tmp_path / "c")
        (directory / "FACTS.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(InstructionsContractError, match="FACTS.json"):
            load_contract(directory)


class TestVerifyAnchors:
    def test_clean_when_quote_is_under_heading(self, tmp_path: Path) -> None:
        contract = load_contract(_write(tmp_path / "c"))
        assert verify_anchors(contract, PAGE) == []

    def test_quote_matching_ignores_line_wrapping(self, tmp_path: Path) -> None:
        fact = _fact(
            anchor={"heading": "how-files-load", "quote": "Subdirectories load\non demand"}
        )
        contract = load_contract(
            _write(tmp_path / "c", facts_doc={"facts": [fact], "unmodelled": []})
        )
        assert verify_anchors(contract, PAGE) == []

    def test_unknown_heading_is_reported(self, tmp_path: Path) -> None:
        fact = _fact(anchor={"heading": "no-such-heading", "quote": "load at launch"})
        contract = load_contract(
            _write(tmp_path / "c", facts_doc={"facts": [fact], "unmodelled": []})
        )
        problems = verify_anchors(contract, PAGE)
        assert len(problems) == 1
        assert "G1-01" in problems[0] and "no-such-heading" in problems[0]

    def test_quote_absent_from_section_is_reported(self, tmp_path: Path) -> None:
        fact = _fact(anchor={"heading": "other", "quote": "load at launch"})
        contract = load_contract(
            _write(tmp_path / "c", facts_doc={"facts": [fact], "unmodelled": []})
        )
        assert "load at launch" in verify_anchors(contract, PAGE)[0]

    def test_section_includes_subheadings(self, tmp_path: Path) -> None:
        fact = _fact(anchor={"heading": "how-files-load", "quote": "four hops deep"})
        contract = load_contract(
            _write(tmp_path / "c", facts_doc={"facts": [fact], "unmodelled": []})
        )
        assert verify_anchors(contract, PAGE) == []

    def test_section_stops_at_next_same_level_heading(self, tmp_path: Path) -> None:
        fact = _fact(anchor={"heading": "how-files-load", "quote": "Nothing here"})
        contract = load_contract(
            _write(tmp_path / "c", facts_doc={"facts": [fact], "unmodelled": []})
        )
        assert verify_anchors(contract, PAGE) != []


class TestShippedContract:
    """The contract this repository ships (Plan 00532 Tasks 1.1 and 1.2)."""

    @pytest.fixture(scope="class")
    def contract(self) -> Any:
        return load_contract(REPO_ROOT / CONTRACT_DIR_RELATIVE)

    def test_every_anchor_resolves_in_the_vendored_page(self, contract: Any) -> None:
        page = (REPO_ROOT / contract.meta.vendored_path).read_text(encoding="utf-8")
        assert verify_anchors(contract, page) == []

    def test_groups_g1_to_g5_are_all_populated(self, contract: Any) -> None:
        assert {f.group for f in contract.facts} == {"G1", "G2", "G3", "G4", "G5"}

    def test_unmodelled_names_the_g6_inputs(self, contract: Any) -> None:
        ids = {u.id for u in contract.unmodelled}
        assert ids == {
            "claudeMdExcludes",
            "agents-md-selection",
            "add-dir-claude-md",
            "subagent-omitClaudeMd",
        }

    def test_vendored_page_hash_matches_provenance(self, contract: Any) -> None:
        text = (REPO_ROOT / contract.meta.vendored_path).read_text(encoding="utf-8")
        assert f"source_sha256: {contract.meta.docs_sha256}" in text

    def test_rules_facts_pin_paths_as_the_only_frontmatter_field(self, contract: Any) -> None:
        statements = " ".join(f.statement for f in contract.facts if f.group == "G3")
        assert "`paths`" in statements and "recursive" in statements
