"""Loader for the Claude Code instruction-loading contract (Plan 00532).

``contracts/claude-code-instructions/`` is a vendored, versioned statement of
how Claude Code loads agent instruction files (``CLAUDE.md``, ``@`` imports,
``.claude/rules/``). It is the sibling of ``contracts/claude-code-hooks/``: a
``META.json`` with provenance and the Claude Code version it was audited
against, plus ``FACTS.json`` in which every fact cites its anchor in the
vendored upstream page.

The footprint measurement, the restructure guidance and the staleness advisory
read this contract instead of restating Claude Code's behaviour. Loading is
strict (fail fast): a contract with no audited version, or a fact with no
source anchor, is a defect in this repository and raises.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

CONTRACT_DIR_RELATIVE: Final[str] = "contracts/claude-code-instructions"
META_FILENAME: Final[str] = "META.json"
FACTS_FILENAME: Final[str] = "FACTS.json"

#: Fact groups the contract models. G6 (AGENTS.md selection and other variants)
#: is deliberately absent and is named in ``unmodelled`` instead.
MODELLED_GROUPS: Final[frozenset[str]] = frozenset({"G1", "G2", "G3", "G4", "G5"})

_VERSION_RE: Final[re.Pattern[str]] = re.compile(r"^\d+\.\d+\.\d+$")
_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_NON_SLUG_RE: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")
_WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"\s+")

_META_STRING_KEYS: Final[tuple[str, ...]] = (
    "docs_url",
    "fetch_date",
    "docs_sha256",
    "vendored_path",
    "refresh_procedure",
)
_AUDITED_KEY: Final[str] = "last_audited_claude_code_version"


class InstructionsContractError(Exception):
    """The contract is missing, unreadable or violates its schema."""


@dataclass(frozen=True)
class Anchor:
    """Where a fact comes from in the vendored page."""

    heading: str
    quote: str


@dataclass(frozen=True)
class Fact:
    """One pinned statement about instruction loading."""

    id: str
    group: str
    statement: str
    anchor: Anchor
    min_claude_code_version: str | None


@dataclass(frozen=True)
class Unmodelled:
    """An input the contract knowingly does not model."""

    id: str
    description: str


@dataclass(frozen=True)
class ContractMeta:
    """Provenance of the vendored page and the audited Claude Code version."""

    docs_url: str
    fetch_date: str
    docs_bytes: int
    docs_sha256: str
    vendored_path: str
    last_audited_claude_code_version: str
    refresh_procedure: str


@dataclass(frozen=True)
class InstructionsContract:
    """The loaded contract."""

    meta: ContractMeta
    facts: tuple[Fact, ...]
    unmodelled: tuple[Unmodelled, ...]


def heading_slug(heading: str) -> str:
    """Lowercase ``heading`` with every run of non-alphanumerics collapsed to one dash."""
    return _NON_SLUG_RE.sub("-", heading.lower()).strip("-")


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstructionsContractError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise InstructionsContractError(f"{path} is not a JSON object")
    return data


def _required_str(data: dict[str, Any], key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InstructionsContractError(f"{where}: {key!r} must be a non-empty string")
    return value


def _version(value: str, key: str, where: str) -> str:
    if not _VERSION_RE.match(value):
        raise InstructionsContractError(f"{where}: {key!r} must look like 2.1.302, got {value!r}")
    return value


def _parse_meta(path: Path) -> ContractMeta:
    data = _read_json_object(path)
    where = str(path)
    strings = {key: _required_str(data, key, where) for key in _META_STRING_KEYS}
    audited = _version(_required_str(data, _AUDITED_KEY, where), _AUDITED_KEY, where)
    docs_bytes = data.get("docs_bytes")
    if not isinstance(docs_bytes, int) or isinstance(docs_bytes, bool) or docs_bytes <= 0:
        raise InstructionsContractError(f"{where}: 'docs_bytes' must be a positive integer")
    return ContractMeta(
        docs_url=strings["docs_url"],
        fetch_date=strings["fetch_date"],
        docs_bytes=docs_bytes,
        docs_sha256=strings["docs_sha256"],
        vendored_path=strings["vendored_path"],
        last_audited_claude_code_version=audited,
        refresh_procedure=strings["refresh_procedure"],
    )


def _parse_fact(raw: object, where: str) -> Fact:
    if not isinstance(raw, dict):
        raise InstructionsContractError(f"{where}: a fact must be a JSON object")
    fact_id = _required_str(raw, "id", where)
    here = f"{where} fact {fact_id}"
    group = _required_str(raw, "group", here)
    if group not in MODELLED_GROUPS:
        raise InstructionsContractError(
            f"{here}: group {group!r} is not one of {sorted(MODELLED_GROUPS)}"
        )
    anchor = raw.get("anchor")
    if not isinstance(anchor, dict):
        raise InstructionsContractError(f"{here}: missing anchor (heading and quote)")
    minimum = raw.get("min_claude_code_version")
    if minimum is not None:
        if not isinstance(minimum, str):
            raise InstructionsContractError(f"{here}: min_claude_code_version must be a string")
        _version(minimum, "min_claude_code_version", here)
    return Fact(
        id=fact_id,
        group=group,
        statement=_required_str(raw, "statement", here),
        anchor=Anchor(
            heading=_required_str(anchor, "heading", f"{here} anchor"),
            quote=_required_str(anchor, "quote", f"{here} anchor"),
        ),
        min_claude_code_version=minimum,
    )


def _parse_unmodelled(raw: object, where: str) -> Unmodelled:
    if not isinstance(raw, dict):
        raise InstructionsContractError(f"{where}: an unmodelled entry must be a JSON object")
    return Unmodelled(
        id=_required_str(raw, "id", f"{where} unmodelled"),
        description=_required_str(raw, "description", f"{where} unmodelled"),
    )


def load_contract(contract_dir: Path) -> InstructionsContract:
    """Load and validate the contract in ``contract_dir``.

    Raises:
        InstructionsContractError: A file is missing or unparseable, the audited
            version is missing or malformed, a fact lacks a source anchor, or
            fact ids repeat.
    """
    meta = _parse_meta(contract_dir / META_FILENAME)
    facts_path = contract_dir / FACTS_FILENAME
    document = _read_json_object(facts_path)
    where = str(facts_path)
    raw_facts = document.get("facts")
    if not isinstance(raw_facts, list) or not raw_facts:
        raise InstructionsContractError(f"{where}: 'facts' must be a non-empty list")
    facts = tuple(_parse_fact(raw, where) for raw in raw_facts)
    ids = [fact.id for fact in facts]
    duplicates = sorted({fact_id for fact_id in ids if ids.count(fact_id) > 1})
    if duplicates:
        raise InstructionsContractError(f"{where}: duplicate fact ids {duplicates}")
    raw_unmodelled = document.get("unmodelled", [])
    if not isinstance(raw_unmodelled, list):
        raise InstructionsContractError(f"{where}: 'unmodelled' must be a list")
    return InstructionsContract(
        meta=meta,
        facts=facts,
        unmodelled=tuple(_parse_unmodelled(raw, where) for raw in raw_unmodelled),
    )


def _sections(page_text: str) -> dict[str, str]:
    """Map each heading slug to its section text, subheadings included."""
    headings: list[tuple[int, int, str]] = []
    lines = page_text.splitlines()
    in_fence = False
    for index, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        match = None if in_fence else _HEADING_RE.match(line)
        if match:
            headings.append((index, len(match.group(1)), heading_slug(match.group(2))))
    sections: dict[str, str] = {}
    for position, (index, level, slug) in enumerate(headings):
        end = len(lines)
        for later_index, later_level, _ in headings[position + 1 :]:
            if later_level <= level:
                end = later_index
                break
        sections.setdefault(slug, "\n".join(lines[index + 1 : end]))
    return sections


def _squash(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def verify_anchors(contract: InstructionsContract, page_text: str) -> list[str]:
    """Check every fact's quote occurs under its heading in the vendored page.

    Returns:
        One problem string per fact whose heading is absent or whose quote is
        not in that heading's section. Empty when every anchor resolves.
    """
    sections = _sections(page_text)
    problems: list[str] = []
    for fact in contract.facts:
        section = sections.get(fact.anchor.heading)
        if section is None:
            problems.append(f"{fact.id}: heading {fact.anchor.heading!r} not found in the page")
        elif _squash(fact.anchor.quote) not in _squash(section):
            problems.append(
                f"{fact.id}: quote {fact.anchor.quote!r} not found under {fact.anchor.heading!r}"
            )
    return problems
