"""The cache that lets PreToolUse enforce without touching the network (Plan 00401 Task 1.4).

SessionStart does the fetching and writes what it found here; PreToolUse reads
it and nothing else. That split is the architecture, so this file's job is to
make one property impossible to get wrong:

    **anything other than a valid, in-date entry reads as NOT VERIFIED.**

Missing, expired, truncated, hand-edited, written by an older schema, or
stamped with a future time — every one of those must come back as "unknown",
never as "fresh". The asymmetry is deliberate: reporting a fresh repo as
unverified costs one avoidable check, while reporting a stale repo as fresh is
precisely the defect this plan exists to prevent, and it is silent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.reference_repos.cache import (
    DEFAULT_TTL_SECONDS,
    cache_path,
    cached_states,
    write_cache,
)
from claude_code_hooks_daemon.reference_repos.model import Checkability, RepoState

_NOW = 1_000_000.0


def _state(path: Path, *, behind: int = 0, branch: str = "main") -> RepoState:
    return RepoState(
        path=path,
        checkability=Checkability.CHECKABLE,
        branch=branch,
        default_branch="main",
        upstream="origin/main",
        behind=behind,
        ahead=0,
        dirty=False,
    )


class TestRoundTrip:
    def test_what_was_written_is_what_is_read(self, tmp_path: Path) -> None:
        repo = tmp_path / "repos" / "alpha"
        state = _state(repo, behind=3)

        write_cache(tmp_path, [state], now=_NOW)
        read = cached_states(tmp_path, now=_NOW)

        assert read == {repo: state}

    def test_every_field_survives_the_round_trip(self, tmp_path: Path) -> None:
        """A field silently dropped would read as a default, i.e. as innocent."""
        repo = tmp_path / "repos" / "beta"
        state = RepoState(
            path=repo,
            checkability=Checkability.NO_UPSTREAM,
            branch="wip",
            default_branch="trunk",
            upstream=None,
            behind=7,
            ahead=2,
            dirty=True,
        )

        write_cache(tmp_path, [state], now=_NOW)
        read = cached_states(tmp_path, now=_NOW)

        assert read is not None
        assert read[repo] == state

    def test_several_repos_round_trip_independently(self, tmp_path: Path) -> None:
        first = tmp_path / "repos" / "alpha"
        second = tmp_path / "repos" / "beta"

        write_cache(tmp_path, [_state(first), _state(second, behind=9)], now=_NOW)
        read = cached_states(tmp_path, now=_NOW)

        assert read is not None
        assert read[second].behind == 9

    def test_the_cache_file_lives_under_the_daemon_untracked_dir(self, tmp_path: Path) -> None:
        """Runtime state, not tracked source — it must never reach a commit."""
        path = cache_path(tmp_path)

        assert "untracked" in str(path)
        assert path.suffix == ".json"


class TestExpiry:
    def test_an_entry_within_the_ttl_is_returned(self, tmp_path: Path) -> None:
        repo = tmp_path / "repos" / "alpha"
        write_cache(tmp_path, [_state(repo)], now=_NOW)

        assert cached_states(tmp_path, now=_NOW + DEFAULT_TTL_SECONDS - 1) is not None

    def test_an_entry_exactly_at_the_ttl_is_still_valid(self, tmp_path: Path) -> None:
        """The boundary is pinned so a refactor cannot quietly move it."""
        repo = tmp_path / "repos" / "alpha"
        write_cache(tmp_path, [_state(repo)], now=_NOW)

        assert cached_states(tmp_path, now=_NOW + DEFAULT_TTL_SECONDS) is not None

    def test_an_entry_past_the_ttl_reads_as_not_verified(self, tmp_path: Path) -> None:
        repo = tmp_path / "repos" / "alpha"
        write_cache(tmp_path, [_state(repo)], now=_NOW)

        assert cached_states(tmp_path, now=_NOW + DEFAULT_TTL_SECONDS + 1) is None

    def test_a_future_timestamp_reads_as_not_verified(self, tmp_path: Path) -> None:
        """Clock skew must not make an entry immortal.

        A naive ``age > ttl`` test passes a negative age, so an entry stamped
        far in the future would never expire — the one way a cache can pin a
        stale reading in place permanently.
        """
        repo = tmp_path / "repos" / "alpha"
        write_cache(tmp_path, [_state(repo)], now=_NOW + 10_000)

        assert cached_states(tmp_path, now=_NOW) is None

    def test_a_custom_ttl_is_honoured(self, tmp_path: Path) -> None:
        repo = tmp_path / "repos" / "alpha"
        write_cache(tmp_path, [_state(repo)], now=_NOW)

        assert cached_states(tmp_path, ttl_seconds=10, now=_NOW + 11) is None
        assert cached_states(tmp_path, ttl_seconds=10, now=_NOW + 9) is not None


class TestUnusableCacheReadsAsNotVerified:
    """Every corruption shape, because each one could otherwise read as fresh."""

    def test_a_missing_cache_reads_as_not_verified(self, tmp_path: Path) -> None:
        assert cached_states(tmp_path, now=_NOW) is None

    def test_undecodable_bytes_read_as_not_verified(self, tmp_path: Path) -> None:
        """A byte that is not UTF-8 raises UnicodeDecodeError, not JSONDecodeError.

        It is a ValueError, so the original `(OSError, json.JSONDecodeError)`
        band missed it and let it escape `handle()` into the front controller —
        which ALLOWS the operation. The gate failed OPEN on a corrupt cache,
        which is the one direction this design must never fail.
        """
        path = cache_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xfe not utf-8 at all")

        assert cached_states(tmp_path) is None

    def test_malformed_json_reads_as_not_verified(self, tmp_path: Path) -> None:
        path = cache_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")

        assert cached_states(tmp_path, now=_NOW) is None

    def test_a_truncated_write_reads_as_not_verified(self, tmp_path: Path) -> None:
        """A crash mid-write leaves valid-looking JSON with pieces missing."""
        repo = tmp_path / "repos" / "alpha"
        write_cache(tmp_path, [_state(repo)], now=_NOW)
        path = cache_path(tmp_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        del payload["repos"][0]["behind"]
        path.write_text(json.dumps(payload), encoding="utf-8")

        assert cached_states(tmp_path, now=_NOW) is None

    def test_an_older_schema_version_reads_as_not_verified(self, tmp_path: Path) -> None:
        """A format change must invalidate the cache, not be misread by it."""
        repo = tmp_path / "repos" / "alpha"
        write_cache(tmp_path, [_state(repo)], now=_NOW)
        path = cache_path(tmp_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["version"] = payload["version"] - 1
        path.write_text(json.dumps(payload), encoding="utf-8")

        assert cached_states(tmp_path, now=_NOW) is None

    def test_a_missing_timestamp_reads_as_not_verified(self, tmp_path: Path) -> None:
        """No timestamp means no way to judge age, so it cannot be trusted."""
        repo = tmp_path / "repos" / "alpha"
        write_cache(tmp_path, [_state(repo)], now=_NOW)
        path = cache_path(tmp_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        del payload["recorded_at"]
        path.write_text(json.dumps(payload), encoding="utf-8")

        assert cached_states(tmp_path, now=_NOW) is None

    def test_an_unknown_checkability_value_reads_as_not_verified(self, tmp_path: Path) -> None:
        repo = tmp_path / "repos" / "alpha"
        write_cache(tmp_path, [_state(repo)], now=_NOW)
        path = cache_path(tmp_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["repos"][0]["checkability"] = "brand-new-state"
        path.write_text(json.dumps(payload), encoding="utf-8")

        assert cached_states(tmp_path, now=_NOW) is None

    def test_a_json_document_that_is_not_an_object_reads_as_not_verified(
        self, tmp_path: Path
    ) -> None:
        path = cache_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[1, 2, 3]", encoding="utf-8")

        assert cached_states(tmp_path, now=_NOW) is None

    def test_a_repos_list_that_is_not_a_list_reads_as_not_verified(self, tmp_path: Path) -> None:
        repo = tmp_path / "repos" / "alpha"
        write_cache(tmp_path, [_state(repo)], now=_NOW)
        path = cache_path(tmp_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["repos"] = {"alpha": "yes"}
        path.write_text(json.dumps(payload), encoding="utf-8")

        assert cached_states(tmp_path, now=_NOW) is None

    def test_an_entry_that_is_not_an_object_reads_as_not_verified(self, tmp_path: Path) -> None:
        """A hand-edited file can put anything in that list."""
        repo = tmp_path / "repos" / "alpha"
        write_cache(tmp_path, [_state(repo)], now=_NOW)
        path = cache_path(tmp_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["repos"] = ["just a string"]
        path.write_text(json.dumps(payload), encoding="utf-8")

        assert cached_states(tmp_path, now=_NOW) is None

    def test_a_non_numeric_count_reads_as_not_verified(self, tmp_path: Path) -> None:
        """``behind`` must be a number; coercing a word would raise, not default.

        Defaulting it to 0 would read as "up to date", turning a corrupt file
        into a silent all-clear — the precise failure this module prevents.
        """
        repo = tmp_path / "repos" / "alpha"
        write_cache(tmp_path, [_state(repo, behind=4)], now=_NOW)
        path = cache_path(tmp_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["repos"][0]["behind"] = "not a number"
        path.write_text(json.dumps(payload), encoding="utf-8")

        assert cached_states(tmp_path, now=_NOW) is None

    def test_one_bad_entry_condemns_the_whole_file(self, tmp_path: Path) -> None:
        """Returning the readable remainder would silently drop a repo.

        A dropped repo is indistinguishable from one that was never governed,
        so a partial read would quietly stop enforcing on it.
        """
        first = tmp_path / "repos" / "alpha"
        second = tmp_path / "repos" / "beta"
        write_cache(tmp_path, [_state(first), _state(second)], now=_NOW)
        path = cache_path(tmp_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["repos"][1]["checkability"] = "nonsense"
        path.write_text(json.dumps(payload), encoding="utf-8")

        assert cached_states(tmp_path, now=_NOW) is None


class TestWriting:
    def test_writing_creates_the_directory_if_absent(self, tmp_path: Path) -> None:
        """First run in a fresh checkout has no untracked dir yet."""
        repo = tmp_path / "repos" / "alpha"

        write_cache(tmp_path, [_state(repo)], now=_NOW)

        assert cache_path(tmp_path).is_file()

    def test_writing_replaces_rather_than_appends(self, tmp_path: Path) -> None:
        """A repo that stopped being governed must not linger in the cache."""
        first = tmp_path / "repos" / "alpha"
        second = tmp_path / "repos" / "beta"
        write_cache(tmp_path, [_state(first)], now=_NOW)

        write_cache(tmp_path, [_state(second)], now=_NOW)
        read = cached_states(tmp_path, now=_NOW)

        assert read is not None
        assert set(read) == {second}

    def test_writing_no_repos_is_valid_and_reads_back_empty(self, tmp_path: Path) -> None:
        """A project with no governed repos is verified-and-empty, not unverified.

        These must stay distinguishable: empty means the sweep ran and found
        nothing, while None means nothing is known — and only one of them should
        make an enforcing caller speak up.
        """
        write_cache(tmp_path, [], now=_NOW)

        assert cached_states(tmp_path, now=_NOW) == {}

    def test_an_unwritable_location_does_not_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A cache write failing must not break SessionStart; it just means unverified."""
        repo = tmp_path / "repos" / "alpha"

        def _explode(*_args: object, **_kwargs: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(Path, "write_text", _explode)

        write_cache(tmp_path, [_state(repo)], now=_NOW)

        assert cached_states(tmp_path, now=_NOW) is None
