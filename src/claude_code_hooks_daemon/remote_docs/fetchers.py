"""How a remote document's bytes are actually obtained (Plan 00326).

``agent-browser read <url>`` is the default because it is DOCUMENTATION-aware
in a way a generic GET is not: it negotiates ``Accept: text/markdown``, retries
the URL with ``.md`` appended, and consults the nearest ancestor ``llms.txt``
before falling back to text extracted from HTML. For vendoring docs as
markdown that is a materially better source than whatever bytes a server hands
an anonymous client.

Two limits are load-bearing, and both were guessed wrong before being checked:

* ``read <url>`` does NOT render JavaScript -- it is an HTTP fetch plus
  extraction. A client-side-rendered page still captures thinly. Rendering
  needs ``open`` first, which is a different shape and is not what this does.
* The binary is not always spelled ``agent-browser``. Environments that
  require an explicit browser mode ship suffixed wrappers and BLOCK the bare
  name, so presence on PATH does not imply it will run. Hence a candidate
  list, and a fall-through when one refuses.

Because the content is extracted and normalised rather than handed back
untouched, a browser capture declares ``converted``. Only the raw GET may
claim ``verbatim`` -- nothing here asserts that on another component's
behalf (D3).

No fetcher is reached from a handler. The daemon's CLI injects one; the
handlers stay offline and testable.
"""

import functools
import json
import shutil
import subprocess  # nosec B404 - no shell is used; see _invoke
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final

from claude_code_hooks_daemon.remote_docs.capture import CaptureError, FetchFn, FetchResult
from claude_code_hooks_daemon.remote_docs.provenance import Fidelity

# Preference order. The mode-suffixed wrappers come first because where they
# exist the bare name is the one that may be deliberately disabled; where they
# do not exist, `which` simply skips them and upstream's own entrypoint (last)
# is used. This works in both kinds of environment without detecting either.
BINARY_CANDIDATES: Final[tuple[str, ...]] = (
    "agent-browser-lite-headless",
    "agent-browser-headless",
    "agent-browser",
)

HTTPS_METHOD: Final[str] = "https-get"
_READ: Final[str] = "read"
_JSON_FLAG: Final[str] = "--json"
_FETCH_TIMEOUT_SECONDS: Final[int] = 60
# Identifies the fetcher honestly rather than impersonating a browser: a host
# that wants to refuse automated capture should be able to.
_USER_AGENT: Final[str] = "claude-code-hooks-daemon-remote-docs/1.0 (+vendoring documentation)"

Which = Callable[[str], str | None]
Runner = Callable[..., Any]

_FALLBACK_WARNING: Final[str] = (
    "agent-browser is not available -- falling back to a plain HTTPS GET.\n"
    "A plain GET is not documentation-aware: it does not negotiate markdown, "
    "retry with `.md`, or consult llms.txt, so a docs page that offers a "
    "markdown form will be vendored as raw HTML instead.\n"
    "To improve captures, install agent-browser and make it available on PATH, "
    "then re-run."
)


@dataclass(frozen=True)
class ResolvedFetcher:
    """A fetch function together with the provenance claim it may honestly make.

    ``fidelity`` travels WITH the fetcher rather than being decided by the
    caller, so no component can claim ``verbatim`` on another's behalf (D3).
    """

    fetch_fn: FetchFn
    fidelity: Fidelity
    method: str
    warning: str | None = None


def https_fetch(url: str) -> bytes:
    """Fetch ``url`` over https only.

    Same defence-in-depth shape as ``install/relay_deploy._default_fetch``:
    the scheme is validated before ``urlopen`` is reached, so ``file:`` and
    custom schemes are impossible by construction rather than by convention.
    """
    import urllib.parse
    import urllib.request

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise CaptureError(f"refusing to fetch non-https URL: {url!r}")

    # Real documentation hosts 403 the default `Python-urllib/3.x`. Found
    # against code.claude.com, whose docs the hooks-contract refresh fetches
    # with curl -- so the documented procedure worked while this did not.
    # `Accept` asks for markdown first, matching what the tree stores.
    request = urllib.request.Request(  # nosec B310 - scheme validated to https above
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "text/markdown, text/plain;q=0.9, text/html;q=0.8, */*;q=0.5",
        },
    )
    with urllib.request.urlopen(  # nosec B310 - scheme validated to https above
        request, timeout=_FETCH_TIMEOUT_SECONDS
    ) as response:
        return bytes(response.read())


def _invoke(command: list[str], runner: Runner) -> Any:
    """Run ``command`` with no shell, turning process failures into CaptureError."""
    try:
        return runner(
            command,
            capture_output=True,
            timeout=_FETCH_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CaptureError(f"{command[0]} timed out after {_FETCH_TIMEOUT_SECONDS}s") from exc
    except FileNotFoundError as exc:
        raise CaptureError(f"{command[0]} could not be executed: {exc}") from exc


def _close_session(binary: str, runner: Runner) -> None:
    """Reap the browser session the read started.

    A read launches a real browser process. Without this every capture leaks
    one until an idle timeout fires. A failure to close is logged by the
    caller's exception path rather than masking the original error, so the
    close result is deliberately not inspected -- there is nothing useful to
    do about a failed reap, and raising here would replace a real fetch error
    with a cleanup one.
    """
    try:
        runner(
            [binary, "close", "--all"],
            capture_output=True,
            timeout=_FETCH_TIMEOUT_SECONDS,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        raise CaptureError(f"{binary}: could not close the browser session: {exc}") from exc


def _extract(binary: str, url: str, completed: Any) -> tuple[bytes, str]:
    """Content and reported source from a ``read --json`` result."""
    if completed.returncode != 0:
        detail = (completed.stderr or b"").decode("utf-8", errors="replace").strip()
        raise CaptureError(
            f"{binary} failed for {url} (exit {completed.returncode}): "
            f"{detail or 'no error output'}"
        )

    try:
        parsed = json.loads((completed.stdout or b"").decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CaptureError(f"{binary} produced unreadable output for {url}: {exc}") from exc

    if not parsed.get("success"):
        raise CaptureError(f"{binary} failed for {url}: {parsed.get('error') or 'unknown error'}")

    data = parsed.get("data") or {}
    if data.get("truncated"):
        # Half a page stored with full provenance would read as a complete,
        # citable document. Failing is the safer outcome.
        raise CaptureError(
            f"{binary} truncated its read of {url}; refusing to vendor a partial document"
        )

    content = data.get("content") or ""
    if not content.strip():
        raise CaptureError(f"{binary} returned no readable content for {url}")

    return content.encode("utf-8"), str(data.get("source") or "unknown")


def agent_browser_fetch(
    url: str,
    *,
    binary: str = BINARY_CANDIDATES[-1],
    runner: Runner | None = None,
    with_source: bool = False,
) -> Any:
    """Fetch ``url`` through ``agent-browser read`` and return its content.

    Returns the content bytes, or a ``(bytes, source)`` pair when
    ``with_source`` is set. ``source`` is agent-browser's own account of where
    the text came from (``accept-markdown``, ``html-fallback``, ...), which is
    provenance worth recording.

    Raises:
        CaptureError: the browser failed, timed out, truncated the page, or
            returned nothing readable.
    """
    run = runner or subprocess.run

    try:
        completed = _invoke([binary, _READ, url, _JSON_FLAG], run)
        content, source = _extract(binary, url, completed)
    finally:
        _close_session(binary, run)

    return (content, source) if with_source else content


def _fetch_with_source(url: str, *, binary: str, runner: Runner | None) -> FetchResult:
    """Fetch, carrying agent-browser's own account of where the text came from.

    ``source`` reaches provenance because "upstream served markdown" and "we
    extracted this from HTML" are different claims about how close the stored
    text is to the document. It does NOT raise ``fidelity``: agent-browser
    only guarantees an unchanged response body under ``--raw``, which this
    does not use.
    """
    content, source = agent_browser_fetch(url, binary=binary, runner=runner, with_source=True)
    return FetchResult(content=content, source=source)


def _is_usable(binary: str, runner: Runner) -> bool:
    """Whether ``binary`` actually runs, not merely whether it exists.

    An environment that mandates an explicit browser mode keeps the bare name
    on PATH and makes every invocation exit non-zero, so presence cannot
    decide this. ``--version`` answers it without launching a browser.
    """
    try:
        completed = _invoke([binary, "--version"], runner)
    except CaptureError:
        return False
    return bool(completed.returncode == 0)


def resolve_fetcher(
    *,
    which: Which | None = None,
    https_fetch_fn: FetchFn | None = None,
    runner: Runner | None = None,
    binaries: Sequence[str] = BINARY_CANDIDATES,
    verbatim: bool = False,
) -> ResolvedFetcher:
    """Pick the best available fetcher, saying so when the best is missing.

    ``verbatim`` demands the response body rather than the best extraction
    available: no browser is probed and no warning is issued, because using
    the raw GET is the CHOICE here rather than a degraded fallback. Work that
    must quote upstream exactly needs this -- see
    ``docs/guides/HOOK-CONTRACT-REFRESH.md``, which exists because a
    summarising fetch layer once fabricated a contract enum value.

    ``which`` and ``https_fetch_fn`` are injected so this is testable without a
    browser, a network, or a PATH that happens to be right.
    """
    if verbatim:
        return ResolvedFetcher(
            fetch_fn=https_fetch_fn or https_fetch,
            fidelity=Fidelity.VERBATIM,
            method=HTTPS_METHOD,
        )

    locate = which or shutil.which
    probe = runner or subprocess.run

    for binary in binaries:
        if locate(binary) is None or not _is_usable(binary, probe):
            continue
        return ResolvedFetcher(
            # `partial` rather than a lambda: it binds `binary` eagerly (the
            # lambda needed a default-argument trick for that) and, unlike a
            # lambda, carries a type mypy can check against `FetchFn`.
            fetch_fn=functools.partial(_fetch_with_source, binary=binary, runner=runner),
            # Extracted and normalised text is not the response body, however
            # faithful it looks.
            fidelity=Fidelity.CONVERTED,
            method=binary,
        )

    return ResolvedFetcher(
        fetch_fn=https_fetch_fn or https_fetch,
        fidelity=Fidelity.VERBATIM,
        method=HTTPS_METHOD,
        warning=_FALLBACK_WARNING,
    )
