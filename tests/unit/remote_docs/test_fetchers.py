"""Fetcher selection for remote-docs capture (Plan 00326).

``agent-browser read <url>`` is a DOCUMENTATION-aware fetch: it negotiates
``Accept: text/markdown``, retries the same URL with ``.md``, and consults the
nearest ancestor ``llms.txt`` before falling back to text extracted from HTML.
That is a better vendoring source than a raw GET, which stores whatever bytes
the server happens to serve a generic client.

Two things it is NOT, and both were assumed wrong once already:

* It does not render JavaScript. ``read <url>`` is an HTTP fetch plus
  extraction. Rendering needs ``open`` first, which is a different shape.
* It is not always spelled ``agent-browser``. Some environments ship
  mode-suffixed wrappers and deliberately BLOCK the bare name, so a binary
  being present on PATH does not mean it will run. Probing has to survive
  that without hard-failing the capture.
"""

import json
from typing import Any

import pytest

from claude_code_hooks_daemon.remote_docs.capture import CaptureError
from claude_code_hooks_daemon.remote_docs.fetchers import (
    _FETCH_TIMEOUT_SECONDS,
    BINARY_CANDIDATES,
    HTTPS_METHOD,
    agent_browser_fetch,
    resolve_fetcher,
)
from claude_code_hooks_daemon.remote_docs.provenance import Fidelity


def _payload(
    content: str = "# Upstream\n",
    *,
    source: str = "accept-markdown",
    truncated: bool = False,
    success: bool = True,
) -> bytes:
    return json.dumps(
        {
            "success": success,
            "data": {
                "content": content,
                "source": source,
                "truncated": truncated,
                "status": 200,
            },
            "error": None if success else "boom",
        }
    ).encode("utf-8")


class _Completed:
    def __init__(self, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _Runner:
    """Records invocations, and lets named binaries fail their probe or read."""

    def __init__(
        self,
        replies: dict[str, Any] | None = None,
        *,
        unusable: set[str] | None = None,
    ) -> None:
        self.calls: list[list[str]] = []
        self._replies = replies or {}
        self._unusable = unusable or set()

    def __call__(self, cmd: list[str], **_kwargs: Any) -> Any:
        self.calls.append(cmd)
        if cmd[0] in self._unusable:
            return _Completed(returncode=2, stderr=b"not available here")
        reply = self._replies.get(cmd[0])
        if reply is not None:
            return reply
        return _Completed(stdout=_payload())

    @property
    def fetch_binaries(self) -> list[str]:
        return [call[0] for call in self.calls if "read" in call]

    @property
    def probed_binaries(self) -> list[str]:
        return [call[0] for call in self.calls if "--version" in call]


def _only(*available: str):
    def which(name: str) -> str | None:
        return f"/usr/local/bin/{name}" if name in available else None

    return which


def _none(_name: str) -> str | None:
    return None


class TestResolution:
    def test_a_browser_is_preferred_when_one_is_available(self) -> None:
        resolved = resolve_fetcher(which=_only(*BINARY_CANDIDATES), runner=_Runner())

        assert resolved.method != HTTPS_METHOD
        assert resolved.warning is None

    def test_an_explicit_mode_wrapper_is_preferred_over_the_bare_name(self) -> None:
        """Where both exist, the bare name is the one that may be blocked."""
        assert BINARY_CANDIDATES.index("agent-browser") == len(BINARY_CANDIDATES) - 1

    def test_the_bare_name_is_still_used_when_it_is_all_there_is(self) -> None:
        """Most environments ship only upstream's own entrypoint."""
        runner = _Runner()
        resolved = resolve_fetcher(which=_only("agent-browser"), runner=runner)
        resolved.fetch_fn("https://example.com")

        assert resolved.method == "agent-browser"
        assert runner.fetch_binaries == ["agent-browser"]

    def test_a_browser_capture_never_claims_verbatim(self) -> None:
        """The content is extracted and normalised, not the response body."""
        resolved = resolve_fetcher(which=_only(*BINARY_CANDIDATES), runner=_Runner())

        assert resolved.fidelity is Fidelity.CONVERTED

    def test_the_https_fallback_claims_verbatim(self) -> None:
        resolved = resolve_fetcher(which=_none)

        assert resolved.method == HTTPS_METHOD
        assert resolved.fidelity is Fidelity.VERBATIM

    def test_the_fallback_warns_rather_than_downgrading_in_silence(self) -> None:
        resolved = resolve_fetcher(which=_none)

        assert resolved.warning is not None
        assert "agent-browser" in resolved.warning

    def test_the_fallback_warning_names_no_specific_container_layout(self) -> None:
        """The daemon installs into arbitrary projects; advice must travel."""
        warning = resolve_fetcher(which=_none).warning or ""

        assert "ccy" not in warning.lower()
        assert "PATH" in warning


class TestHttpsFetch:
    """The raw GET has to survive contact with real documentation hosts."""

    def test_it_sends_a_user_agent(self) -> None:
        """Default `Python-urllib/3.x` is 403'd by real doc hosts.

        Found against code.claude.com, which the hooks-contract refresh
        procedure fetches with `curl` -- so the procedure worked while this
        fetcher did not.
        """
        from unittest.mock import MagicMock, patch

        from claude_code_hooks_daemon.remote_docs.fetchers import https_fetch

        response = MagicMock()
        response.read.return_value = b"body"
        response.__enter__ = lambda self: response
        response.__exit__ = lambda *_args: False

        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            https_fetch("https://example.com/doc.md")

        request = urlopen.call_args[0][0]
        assert request.get_header("User-agent")

    def test_it_still_refuses_a_non_https_url(self) -> None:
        from claude_code_hooks_daemon.remote_docs.fetchers import https_fetch

        with pytest.raises(CaptureError, match="non-https"):
            https_fetch("http://example.com/doc.md")

    def test_it_refuses_a_file_url(self) -> None:
        """Scheme validation happens before urlopen, by construction."""
        from claude_code_hooks_daemon.remote_docs.fetchers import https_fetch

        with pytest.raises(CaptureError, match="non-https"):
            https_fetch("file:///etc/passwd")


class TestVerbatimIsDemandable:
    """Some captures need the response body, not an extraction of it.

    The hooks-contract refresh (docs/guides/HOOK-CONTRACT-REFRESH.md) exists
    because a summarising fetch layer once FABRICATED a contract enum value
    that appeared nowhere in the raw text. For that work, "close enough" is
    the failure mode, so the caller must be able to demand raw bytes rather
    than accept whatever the best available fetcher produces.
    """

    def test_verbatim_bypasses_the_browser_even_when_available(self) -> None:
        runner = _Runner()

        resolved = resolve_fetcher(which=_only(*BINARY_CANDIDATES), runner=runner, verbatim=True)

        assert resolved.method == HTTPS_METHOD
        assert resolved.fidelity is Fidelity.VERBATIM

    def test_verbatim_does_not_warn_about_the_missing_browser(self) -> None:
        """It is a deliberate choice here, not a degraded fallback."""
        resolved = resolve_fetcher(which=_only(*BINARY_CANDIDATES), runner=_Runner(), verbatim=True)

        assert resolved.warning is None

    def test_verbatim_does_not_probe_for_a_browser_at_all(self) -> None:
        runner = _Runner()

        resolve_fetcher(which=_only(*BINARY_CANDIDATES), runner=runner, verbatim=True)

        assert runner.calls == []


class TestCandidateProbing:
    """A binary on PATH is not necessarily a binary that runs.

    An environment that mandates an explicit browser mode keeps the bare name
    on PATH and makes it exit non-zero, so presence alone cannot decide this.
    A cheap `--version` probe can, and it costs no browser launch.
    """

    def test_a_binary_that_refuses_to_run_is_skipped(self) -> None:
        runner = _Runner(unusable={"agent-browser-lite-headless"})

        resolved = resolve_fetcher(which=_only(*BINARY_CANDIDATES), runner=runner)

        assert resolved.method == "agent-browser-headless"

    def test_the_recorded_method_is_the_binary_actually_used(self) -> None:
        """Provenance that names a tool which never ran is worse than none."""
        runner = _Runner(unusable={"agent-browser-lite-headless", "agent-browser-headless"})

        resolved = resolve_fetcher(which=_only(*BINARY_CANDIDATES), runner=runner)
        resolved.fetch_fn("https://example.com")

        assert resolved.method == "agent-browser"
        assert runner.fetch_binaries == ["agent-browser"]

    def test_probing_stops_at_the_first_usable_binary(self) -> None:
        runner = _Runner()

        resolve_fetcher(which=_only(*BINARY_CANDIDATES), runner=runner)

        assert runner.probed_binaries == ["agent-browser-lite-headless"]

    def test_no_usable_binary_falls_back_to_https_rather_than_failing(self) -> None:
        """Present-but-unusable must degrade exactly like absent."""
        runner = _Runner(unusable=set(BINARY_CANDIDATES))

        resolved = resolve_fetcher(which=_only(*BINARY_CANDIDATES), runner=runner)

        assert resolved.method == HTTPS_METHOD
        assert resolved.fidelity is Fidelity.VERBATIM
        assert resolved.warning is not None


class TestAgentBrowserFetch:
    def test_it_returns_the_extracted_content(self) -> None:
        runner = _Runner()

        assert (
            agent_browser_fetch("https://example.com", binary="agent-browser", runner=runner)
            == b"# Upstream\n"
        )

    def test_it_asks_for_json_so_the_metadata_is_available(self) -> None:
        runner = _Runner()

        agent_browser_fetch("https://example.com", binary="agent-browser", runner=runner)

        assert runner.calls[0] == [
            "agent-browser",
            "read",
            "https://example.com",
            "--json",
        ]

    def test_it_closes_the_session_it_opened(self) -> None:
        """A read starts a browser process; leaving it running leaks one per capture."""
        runner = _Runner()

        agent_browser_fetch("https://example.com", binary="agent-browser", runner=runner)

        assert ["agent-browser", "close", "--all"] in runner.calls

    def test_the_session_is_closed_even_when_the_fetch_fails(self) -> None:
        runner = _Runner({"agent-browser": _Completed(stdout=_payload(success=False))})

        with pytest.raises(CaptureError):
            agent_browser_fetch("https://example.com", binary="agent-browser", runner=runner)

        assert ["agent-browser", "close", "--all"] in runner.calls

    def test_a_truncated_read_is_an_error_rather_than_a_partial_document(self) -> None:
        """Vendoring half a page silently is worse than failing to vendor it."""
        runner = _Runner({"agent-browser": _Completed(stdout=_payload(truncated=True))})

        with pytest.raises(CaptureError, match="truncated"):
            agent_browser_fetch("https://example.com", binary="agent-browser", runner=runner)

    def test_an_empty_read_is_an_error(self) -> None:
        runner = _Runner({"agent-browser": _Completed(stdout=_payload(content="   \n"))})

        with pytest.raises(CaptureError, match="no readable content"):
            agent_browser_fetch("https://example.com", binary="agent-browser", runner=runner)

    def test_unparseable_output_is_reported_clearly(self) -> None:
        runner = _Runner({"agent-browser": _Completed(stdout=b"not json")})

        with pytest.raises(CaptureError, match="unreadable"):
            agent_browser_fetch("https://example.com", binary="agent-browser", runner=runner)

    def test_the_reported_source_is_available_for_provenance(self) -> None:
        """`accept-markdown` and `html-fallback` are different provenance claims."""
        runner = _Runner({"agent-browser": _Completed(stdout=_payload(source="html-fallback"))})

        _content, source = agent_browser_fetch(
            "https://example.com", binary="agent-browser", runner=runner, with_source=True
        )

        assert source == "html-fallback"

    def test_a_timeout_is_reported_as_a_capture_error(self) -> None:
        import subprocess

        def runner(cmd: list[str], **_kwargs: Any) -> Any:
            if "read" in cmd:
                raise subprocess.TimeoutExpired(cmd="agent-browser", timeout=_FETCH_TIMEOUT_SECONDS)
            return _Completed()

        with pytest.raises(CaptureError, match="timed out"):
            agent_browser_fetch("https://example.com", binary="agent-browser", runner=runner)

    def test_a_missing_binary_is_reported_as_a_capture_error(self) -> None:
        def runner(cmd: list[str], **_kwargs: Any) -> Any:
            if "read" in cmd:
                raise FileNotFoundError(2, "No such file or directory")
            return _Completed()

        with pytest.raises(CaptureError, match="agent-browser"):
            agent_browser_fetch("https://example.com", binary="agent-browser", runner=runner)

    def test_no_shell_is_used(self) -> None:
        """A shell would make the URL an injection vector."""
        seen: dict[str, Any] = {}

        def runner(cmd: list[str], **kwargs: Any) -> Any:
            seen.setdefault("kwargs", kwargs)
            return _Completed(stdout=_payload())

        agent_browser_fetch("https://example.com", binary="agent-browser", runner=runner)

        assert seen["kwargs"].get("shell") is not True
