"""A swapped fake is recorded in provenance, and capture performs the swap (Plan 00492)."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from claude_code_hooks_daemon.remote_docs.capture import CaptureError, capture
from claude_code_hooks_daemon.remote_docs.provenance import (
    Fidelity,
    is_unaltered_capture,
    parse_provenance,
)
from claude_code_hooks_daemon.remote_docs.store import write_capture
from claude_code_hooks_daemon.utils.fake_values import (
    REGISTRY_RELATIVE_PATH,
    ValueSwap,
    ValueSwapper,
    load_fake_values,
    swap_unlisted_fakes,
)

_LISTED_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_LISTED_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
# Built at runtime so this file never carries a real-looking UUID literal.
_UPSTREAM = "-".join(("8e11bfb5", "7dc2", "432b", "9206", "928fa5c35731"))
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_NOW = datetime(2026, 10, 6, tzinfo=UTC)
_URL = "https://example.com/docs/statusline"
_SHA = hashlib.sha256(b"x").hexdigest()


def _swapper(tmp_path: Path) -> ValueSwapper:
    target = tmp_path / REGISTRY_RELATIVE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"kinds:\n  session-uuid:\n    values:\n      - '{_LISTED_A}'\n      - '{_LISTED_B}'\n",
        encoding="utf-8",
    )
    registry = load_fake_values(tmp_path)
    return lambda text: swap_unlisted_fakes(text, {"session-uuid": _UUID_RE}, registry)


def _swap_block(**overrides: object) -> str:
    entry: dict[str, object] = {
        "kind": "session-uuid",
        "replacement": _LISTED_A,
        "occurrences": 2,
        "original_sha256": _SHA,
    }
    entry.update(overrides)
    return yaml.safe_dump({"value_swaps": [entry]}, sort_keys=False)


def _doc(*, fidelity: str = "converted", extra: str = "") -> str:
    return (
        "---\n"
        "source_url: https://example.com/docs/page\n"
        "fetched_at: 2026-10-06T00:00:00+00:00\n"
        f"fidelity: {fidelity}\n"
        f"source_sha256: {_SHA}\n"
        "licence: unreviewed\n"
        "stale_after: 2027-01-01\n"
        f"{extra}---\n\nbody\n"
    )


class TestProvenanceCarriesSwaps:
    def test_no_swaps_by_default(self) -> None:
        result = parse_provenance(_doc())
        assert result.provenance is not None
        assert result.provenance.value_swaps == ()

    def test_a_recorded_swap_parses(self) -> None:
        result = parse_provenance(_doc(extra=_swap_block()))
        assert result.errors == ()
        assert result.provenance is not None
        assert result.provenance.value_swaps == (
            ValueSwap(
                kind="session-uuid", replacement=_LISTED_A, occurrences=2, original_sha256=_SHA
            ),
        )

    def test_swaps_are_not_allowed_on_a_verbatim_document(self) -> None:
        result = parse_provenance(_doc(fidelity="verbatim", extra=_swap_block()))
        assert result.provenance is None
        assert [error.field for error in result.errors] == ["value_swaps"]
        assert "verbatim" in result.errors[0].message

    @pytest.mark.parametrize(
        "override",
        [
            {"kind": ""},
            {"replacement": ""},
            {"occurrences": 0},
            {"occurrences": "many"},
            {"original_sha256": "abc"},
        ],
    )
    def test_a_malformed_swap_entry_is_rejected(self, override: dict[str, object]) -> None:
        result = parse_provenance(_doc(extra=_swap_block(**override)))
        assert result.provenance is None
        assert [error.field for error in result.errors] == ["value_swaps"]

    def test_value_swaps_must_be_a_list_of_mappings(self) -> None:
        result = parse_provenance(_doc(extra="value_swaps: nope\n"))
        assert [error.field for error in result.errors] == ["value_swaps"]
        result = parse_provenance(_doc(extra="value_swaps:\n  - just-a-string\n"))
        assert [error.field for error in result.errors] == ["value_swaps"]


class TestCaptureSwaps:
    def test_an_unlisted_fake_is_swapped_and_recorded(self, tmp_path: Path) -> None:
        body = f'{{"session_id": "{_UPSTREAM}"}}\n'.encode()
        result = capture(_URL, fetch_fn=lambda _u: body, now=_NOW, value_swapper=_swapper(tmp_path))

        assert _UPSTREAM not in result.content
        assert _LISTED_A in result.content
        parsed = parse_provenance(result.content)
        assert parsed.provenance is not None
        assert [(s.kind, s.replacement, s.occurrences) for s in parsed.provenance.value_swaps] == [
            ("session-uuid", _LISTED_A, 1)
        ]

    def test_source_hash_stays_the_hash_of_the_raw_upstream_bytes(self, tmp_path: Path) -> None:
        body = f"id {_UPSTREAM}\n".encode()
        result = capture(_URL, fetch_fn=lambda _u: body, now=_NOW, value_swapper=_swapper(tmp_path))
        assert result.source_sha256 == hashlib.sha256(body).hexdigest()

    def test_a_swapped_capture_never_claims_verbatim(self, tmp_path: Path) -> None:
        body = f"id {_UPSTREAM}\n".encode()
        result = capture(
            _URL,
            fetch_fn=lambda _u: body,
            now=_NOW,
            fidelity=Fidelity.VERBATIM,
            value_swapper=_swapper(tmp_path),
        )
        parsed = parse_provenance(result.content)
        assert parsed.provenance is not None
        assert parsed.provenance.fidelity is Fidelity.CONVERTED

    def test_a_swapped_capture_keeps_a_lower_claim_than_converted(self, tmp_path: Path) -> None:
        body = f"id {_UPSTREAM}\n".encode()
        result = capture(
            _URL,
            fetch_fn=lambda _u: body,
            now=_NOW,
            fidelity=Fidelity.SUMMARISED,
            value_swapper=_swapper(tmp_path),
        )
        parsed = parse_provenance(result.content)
        assert parsed.provenance is not None
        assert parsed.provenance.fidelity is Fidelity.SUMMARISED

    def test_a_swapped_capture_is_not_an_unaltered_capture(self, tmp_path: Path) -> None:
        body = f"id {_UPSTREAM}\n".encode()
        result = capture(_URL, fetch_fn=lambda _u: body, now=_NOW, value_swapper=_swapper(tmp_path))
        assert is_unaltered_capture(result.content) is False

    def test_the_original_is_recorded_only_as_a_hash(self, tmp_path: Path) -> None:
        body = f"id {_UPSTREAM}\n".encode()
        result = capture(_URL, fetch_fn=lambda _u: body, now=_NOW, value_swapper=_swapper(tmp_path))
        assert _UPSTREAM not in result.content
        assert hashlib.sha256(_UPSTREAM.encode()).hexdigest() in result.content

    def test_a_page_with_nothing_to_swap_is_unchanged_and_keeps_its_fidelity(
        self, tmp_path: Path
    ) -> None:
        body = f"id {_LISTED_A}\n".encode()
        result = capture(_URL, fetch_fn=lambda _u: body, now=_NOW, value_swapper=_swapper(tmp_path))
        parsed = parse_provenance(result.content)
        assert parsed.provenance is not None
        assert parsed.provenance.fidelity is Fidelity.VERBATIM
        assert parsed.provenance.value_swaps == ()
        assert is_unaltered_capture(result.content) is True
        assert "value_swaps" not in result.content

    def test_without_a_swapper_nothing_is_swapped(self) -> None:
        body = f"id {_UPSTREAM}\n".encode()
        result = capture(_URL, fetch_fn=lambda _u: body, now=_NOW)
        assert _UPSTREAM in result.content

    def test_write_capture_vendors_the_swapped_page(self, tmp_path: Path) -> None:
        body = f"id {_UPSTREAM}\n".encode()
        written = write_capture(
            tmp_path / "remote-docs",
            _URL,
            fetch_fn=lambda _u: body,
            now=_NOW,
            value_swapper=_swapper(tmp_path),
        )
        text = written.read_text(encoding="utf-8")
        assert _UPSTREAM not in text
        assert _LISTED_A in text

    def test_running_out_of_listed_fakes_is_a_capture_error(self, tmp_path: Path) -> None:
        other = "-".join(("0c9e6a2f", "7d41", "4f4e", "9a15", "3f4f7c2b8d10"))
        third = "-".join(("5b2a9c8e", "1f63", "4d8a", "b7c4", "9e0d2a6f1c3b"))
        body = f"{_UPSTREAM} {other} {third}\n".encode()
        with pytest.raises(CaptureError, match="no unused listed fake"):
            capture(_URL, fetch_fn=lambda _u: body, now=_NOW, value_swapper=_swapper(tmp_path))
