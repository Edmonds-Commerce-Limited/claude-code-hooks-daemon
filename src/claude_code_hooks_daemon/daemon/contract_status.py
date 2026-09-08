"""Mechanised half of the hooks-contract refresh procedure (Plan 00327 Task 3.2).

``docs/guides/HOOK-CONTRACT-REFRESH.md`` opens with two steps that are pure
mechanism: fetch the RAW hooks documentation and compare its sha256 with
``contracts/claude-code-hooks/META.json``'s ``docs_sha256``. This module is
those two steps. Everything after them — reading the changed sections and
re-deriving each claim verbatim — is a verified judgement step and stays
prose by design (Plan 00271 Decision 3: a summarising fetch of this very
page once fabricated an enum value).

The fetch is the remote-docs ``https_fetch``: a plain https GET of the exact
bytes, hashed before any decoding, so what is compared is what the previous
audit hashed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.remote_docs.fetchers import https_fetch

#: Exit codes: the verdict IS the exit code, so a script can gate on it.
EXIT_UNCHANGED: Final[int] = 0
EXIT_CHANGED: Final[int] = 1
EXIT_ERROR: Final[int] = 2

#: The vendored contract's provenance file (this module lives at
#: src/claude_code_hooks_daemon/daemon/, three levels below the repository
#: root — true in self-install mode and in a client's clone alike).
DEFAULT_META_PATH: Final[Path] = (
    Path(__file__).resolve().parents[3] / "contracts" / "claude-code-hooks" / "META.json"
)

#: Production fetcher. Raw https only; never a summarising layer.
DEFAULT_FETCH: Final[Callable[[str], bytes]] = https_fetch

_META_URL_KEY: Final[str] = "docs_url"
_META_SHA_KEY: Final[str] = "docs_sha256"
_META_BYTES_KEY: Final[str] = "docs_bytes"
_META_VERSION_KEY: Final[str] = "last_audited_claude_code_version"
_META_REFRESH_KEY: Final[str] = "refresh_procedure"
_FALLBACK_REFRESH_DOC: Final[str] = "docs/guides/HOOK-CONTRACT-REFRESH.md"


class ContractStatusError(Exception):
    """META.json unreadable/incomplete, or the raw fetch failed."""


@dataclass(frozen=True)
class ContractStatus:
    """The comparison result: recorded provenance beside what upstream serves now."""

    url: str
    recorded_sha256: str
    recorded_bytes: int | None
    audited_version: str | None
    refresh_procedure: str
    fetched_sha256: str
    fetched_bytes: int
    saved_to: Path | None = None

    @property
    def changed(self) -> bool:
        return self.fetched_sha256 != self.recorded_sha256


def _read_meta(meta_path: Path) -> dict[str, object]:
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractStatusError(f"cannot read META.json at {meta_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractStatusError(f"META.json at {meta_path} is not a JSON object")
    return data


def _required_str(meta: dict[str, object], key: str, meta_path: Path) -> str:
    value = meta.get(key)
    if not isinstance(value, str) or not value:
        raise ContractStatusError(f"META.json at {meta_path} has no usable {key!r}")
    return value


def compare_contract(
    meta_path: Path,
    fetch: Callable[[str], bytes],
    save_to: Path | None = None,
) -> ContractStatus:
    """Fetch ``META.json.docs_url`` raw and compare its sha256 with ``docs_sha256``.

    Args:
        meta_path: The vendored contract's ``META.json``.
        fetch: Returns the raw response body for a URL. Injected so tests
            never touch the network; production passes ``DEFAULT_FETCH``.
        save_to: When given, the raw body is written there unchanged, so a
            CHANGED verdict leaves the refresh's step-1 capture on disk.

    Raises:
        ContractStatusError: META.json unreadable/incomplete, fetch failed,
            or ``save_to`` unwritable.
    """
    meta = _read_meta(meta_path)
    url = _required_str(meta, _META_URL_KEY, meta_path)
    recorded_sha = _required_str(meta, _META_SHA_KEY, meta_path)
    recorded_bytes = meta.get(_META_BYTES_KEY)
    audited_version = meta.get(_META_VERSION_KEY)
    refresh_doc = meta.get(_META_REFRESH_KEY)

    try:
        body = fetch(url)
    except Exception as exc:
        raise ContractStatusError(f"raw fetch of {url} failed: {exc}") from exc

    saved: Path | None = None
    if save_to is not None:
        try:
            save_to.parent.mkdir(parents=True, exist_ok=True)
            save_to.write_bytes(body)
        except OSError as exc:
            raise ContractStatusError(f"cannot save raw body to {save_to}: {exc}") from exc
        saved = save_to

    return ContractStatus(
        url=url,
        recorded_sha256=recorded_sha,
        recorded_bytes=recorded_bytes if isinstance(recorded_bytes, int) else None,
        audited_version=audited_version if isinstance(audited_version, str) else None,
        refresh_procedure=(
            refresh_doc if isinstance(refresh_doc, str) and refresh_doc else _FALLBACK_REFRESH_DOC
        ),
        fetched_sha256=hashlib.sha256(body).hexdigest(),
        fetched_bytes=len(body),
        saved_to=saved,
    )


def render_status(status: ContractStatus) -> str:
    """Human-readable verdict, one fact per line."""
    recorded_size = f"{status.recorded_bytes} bytes" if status.recorded_bytes is not None else "?"
    audited = status.audited_version or "unknown"
    lines = [
        f"contract-status: {status.url}",
        f"  recorded  sha256 {status.recorded_sha256}  ({recorded_size}, audited v{audited})",
        f"  upstream  sha256 {status.fetched_sha256}  ({status.fetched_bytes} bytes)",
    ]
    if status.saved_to is not None:
        lines.append(f"  raw body saved to {status.saved_to}")
    if status.changed:
        lines.append(
            "  verdict: CHANGED -- upstream differs from the last audit. "
            f"Continue from step 3 of {status.refresh_procedure} against the RAW text."
        )
    else:
        lines.append(
            "  verdict: unchanged -- the vendored contract matches upstream; "
            "a newer Claude Code needs only the META.json version/date bump."
        )
    return "\n".join(lines)
