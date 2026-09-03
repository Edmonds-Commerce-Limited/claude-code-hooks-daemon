"""Routing agents to the vendored copy (Plan 00326 Tasks 5.1 and 5.3).

A corpus nobody is routed to is a corpus nobody reads. One handler, two
branches, because both answer the same question at different moments:

``WebFetch``
    Vendored and fresh -- DENY, and name the local path. Fetching a page we
    already hold is slower, costs tokens, and bypasses the corpus the tree
    exists to build. Vendored but STALE -- allow: the fetch is effectively
    the refresh, and denying it would strand the document. Not vendored --
    allow, with a hint naming the exact capture command.

``Read``
    A document past its ``stale_after`` is allowed with an advisory, so the
    warning arrives WITH the content and cannot be skipped (D16). An
    ``unreviewed`` licence rides in the SAME advisory rather than a second
    one -- two notices for one Read is how one of them gets ignored.

The capture hint is conditional on the tree existing. A project that vendors
nothing has not opted into any of this, and a hint on every fetch would be
the fastest way to teach someone to ignore advisories.
"""

import logging
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule

logger = logging.getLogger(__name__)

_FIELD_URL: Final[str] = "url"
_FIELD_FILE_PATH: Final[str] = "file_path"
_MARKDOWN_SUFFIX: Final[str] = ".md"
_FALLBACK_REMOTE_DOCS_DIR: Final[str] = "remote-docs"

_RULE_VENDORED_COPY: Final[Rule] = Rule(
    rule_id=RuleID.REMOTE_DOCS_VENDORED_COPY,
    blocked="a WebFetch of a URL this project already holds a fresh vendored copy of",
    why=(
        "The local copy is faster, costs no network round trip, and is the "
        "corpus the remote-docs tree exists to build"
    ),
    fix="Read the local path named in the message, or refresh it if you need newer content",
    verbose=(
        "This project vendors documentation under its remote-docs tree, and "
        "the URL you asked to fetch is already there and still within its "
        "freshness window.\n\n"
        "Read the local file instead: it is markdown, it is greppable "
        "alongside the rest of the corpus, and it costs no fetch.\n\n"
        "If you genuinely need newer content than the vendored copy, that is "
        "a refresh rather than a fetch:\n"
        "  bin/hooks-daemon remote-docs refresh --path <file>\n\n"
        "A refresh re-fetches from the recorded `source_url`, keeps the "
        "licence review already on the document, and no-ops when upstream "
        "has not changed.\n\n"
        "A STALE vendored copy is never blocked -- there the fetch is "
        "effectively the refresh, and stopping it would strand the document."
    ),
)


class RemoteDocsRoutingHandler(PreToolUseHandlerBase):
    """Route a fetch to the vendored copy; warn when that copy is stale."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.REMOTE_DOCS_ROUTING,
            priority=Priority.REMOTE_DOCS_ROUTING,
            tags=[HandlerTag.WORKFLOW, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )
        # Injection points for tests; production uses the real clock and the
        # project's own configuration.
        self.today_reader: Callable[[], date] = date.today
        self.declared_domains_reader: Callable[[], set[str]] = self._declared_domains

    def _declared_domains(self) -> set[str]:
        """Domains the project has declared as documentation sources.

        Read off ``documentation.remote.known_sources`` rather than a second
        list: a domain you have recorded a licence for IS a domain you vendor
        from, and two lists that mean nearly the same thing drift apart. To
        declare a source before its licence is reviewed, record the
        ``unreviewed`` sentinel as the value.
        """
        config = self._config_reader()
        if config is None:
            return set()
        return {domain.lower() for domain in config.documentation.remote.known_sources}

    def _config_reader(self) -> Any:
        """The project's loaded config, or None when it cannot be read."""
        from claude_code_hooks_daemon.config.models import Config

        try:
            return Config.load_or_default(
                ProjectContext.project_root() / ".claude" / "hooks-daemon.yaml"
            )
        except (OSError, ValueError) as exc:
            logger.debug("remote-docs routing could not read config: %s", exc)
            return None

    def _is_declared(self, url: str) -> bool:
        """Whether ``url``'s host is a declared documentation domain.

        An EXACT host match, never a suffix one: `docs.example` must not
        match `evil-docs.example`.
        """
        from urllib.parse import urlsplit

        try:
            host = (urlsplit(url).hostname or "").lower()
        except ValueError:
            return False
        return bool(host) and host in self.declared_domains_reader()

    def _tree(self) -> Path:
        layout = self._project_layout
        name = layout.remote_docs_dir if layout is not None else _FALLBACK_REMOTE_DOCS_DIR
        return ProjectContext.project_root() / name

    def _url(self, hook_input: dict[str, Any]) -> str | None:
        url = hook_input.get(HookInputField.TOOL_INPUT, {}).get(_FIELD_URL)
        return url if isinstance(url, str) and url else None

    def _read_target(self, hook_input: dict[str, Any]) -> Path | None:
        """A markdown path inside the tree, or None.

        A prefix test before any file I/O, as ``secret_file_guard`` does: the
        overwhelming majority of Reads are nowhere near this tree.
        """
        raw = hook_input.get(HookInputField.TOOL_INPUT, {}).get(_FIELD_FILE_PATH)
        if not isinstance(raw, str) or not raw.endswith(_MARKDOWN_SUFFIX):
            return None
        path = Path(raw)
        if not path.is_absolute():
            return None
        tree = self._tree()
        try:
            path.resolve().relative_to(tree.resolve())
        except (ValueError, OSError):
            return None
        return path

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True when this call is about a vendored document."""
        tool = hook_input.get(HookInputField.TOOL_NAME)

        if tool == ToolName.WEB_FETCH:
            url = self._url(hook_input)
            # No tree means the project never opted in; stay entirely silent.
            if url is None or not self._tree().is_dir():
                return False
            # Either we already hold this page (route to it), or its domain is
            # a declared documentation source (nudge). Everything else — a
            # GitHub issue, a status page, a blog post — is left alone: an
            # advisory that is usually wrong teaches people to skim past it.
            from claude_code_hooks_daemon.remote_docs.lookup import find_document

            if self._is_declared(url):
                return True
            return find_document(self._tree(), url) is not None

        if tool == ToolName.READ:
            target = self._read_target(hook_input)
            return target is not None and self._read_advisory(target) is not None

        return False

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny a redundant fetch; advise on a stale read."""
        if hook_input.get(HookInputField.TOOL_NAME) == ToolName.READ:
            target = self._read_target(hook_input)
            advisory = self._read_advisory(target) if target is not None else None
            return GatingResult(decision=Decision.ALLOW, context=advisory or [])

        return self._handle_fetch(hook_input)

    def _handle_fetch(self, hook_input: dict[str, Any]) -> GatingResult:
        from claude_code_hooks_daemon.remote_docs.lookup import find_document

        url = self._url(hook_input)
        if url is None:
            return GatingResult(decision=Decision.ALLOW)

        tree = self._tree()
        document = find_document(tree, url)

        if document is None or document.provenance is None:
            if not self._is_declared(url):
                return GatingResult(decision=Decision.ALLOW)
            return GatingResult(
                decision=Decision.ALLOW,
                context=[
                    "📄 REMOTE DOCS: this domain is a declared documentation "
                    "source for this project, but the page is not vendored "
                    "yet. Capture it so the whole project can grep it offline "
                    "instead of re-fetching:",
                    f"  bin/hooks-daemon remote-docs add {url}",
                ],
            )

        if document.provenance.is_stale(self.today_reader()):
            # The fetch IS the refresh. Blocking here would strand the doc.
            return GatingResult(
                decision=Decision.ALLOW,
                context=[
                    "📄 REMOTE DOCS: the vendored copy of this URL is stale, "
                    "so this fetch is allowed. Consider recording the result:",
                    f"  bin/hooks-daemon remote-docs refresh --path {document.path}",
                ],
            )

        return GatingResult(
            decision=Decision.DENY,
            reason=(
                "ALREADY VENDORED — READ THE LOCAL COPY\n\n"
                f"This project already holds a fresh copy of {url}:\n\n"
                f"  {document.path}\n\n"
                f"  captured: {document.provenance.fetched_at.date()}\n"
                f"  fresh until: {document.provenance.stale_after}\n\n"
                "It is markdown, greppable alongside the rest of the corpus, "
                "and costs no fetch.\n\n"
                "If you genuinely need newer content, that is a refresh:\n"
                f"  bin/hooks-daemon remote-docs refresh --path {document.path}"
            ),
        )

    def _read_advisory(self, path: Path) -> list[str] | None:
        """Advisory lines for a stale or unreviewed document, or None."""
        from claude_code_hooks_daemon.remote_docs.provenance import UNREVIEWED
        from claude_code_hooks_daemon.remote_docs.store import read_document

        document = read_document(path)
        provenance = document.provenance
        if provenance is None:
            return None

        stale = provenance.is_stale(self.today_reader())
        unreviewed = provenance.licence == UNREVIEWED
        if not stale and not unreviewed:
            return None

        lines = ["📄 REMOTE DOCS: this is a vendored copy, not upstream itself."]
        if stale:
            lines.extend(
                [
                    f"  captured {provenance.fetched_at.date()}, "
                    f"stale since {provenance.stale_after}",
                    f"  refresh: bin/hooks-daemon remote-docs refresh --path {path}",
                ]
            )
        if unreviewed:
            # Same advisory, deliberately: a second notice for one Read is
            # how one of them stops being read (D16).
            lines.append(
                f"  licence is `{UNREVIEWED}` — check it before quoting this "
                "anywhere it matters"
            )
        return lines

    def get_rules(self) -> list[Rule]:
        """The Rule backing the WebFetch denial."""
        return [_RULE_VENDORED_COPY]

    def get_claude_md(self) -> str | None:
        """No resident guidance: the sibling gate's section covers the corpus."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Acceptance tests rendered into the release playbook."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="remote-docs fetch routing",
                command="WebFetch a URL that is already vendored and fresh",
                description=(
                    "The fetch is denied and the local path is named, along "
                    "with the refresh command for genuinely newer content"
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"ALREADY VENDORED", r"remote-docs refresh"],
                safety_notes="No network access occurs; the tree is read locally",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="remote-docs routing near-miss",
                command="WebFetch a URL that is NOT vendored",
                description=(
                    "An unvendored URL is allowed through; only a capture "
                    "hint is added, never a block"
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Read-only check against the local tree",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
