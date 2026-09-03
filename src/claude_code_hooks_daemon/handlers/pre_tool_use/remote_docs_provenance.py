"""Write-time provenance gate for the remote-docs tree (Plan 00326 Task 3.4).

Every file in the vendored tree must declare where it came from. This is the
rule that turns that from an aspiration into an invariant, and BRAINSTORM's
triage calls it the highest-value one in the set.

It blocks rather than advises (D7) because missing provenance is a FACT --
checkable offline, with no legitimate exception. Staleness, by contrast, is a
judgement a human may knowingly accept, and only advises.

A PreToolUse handler rather than a ``docs_qa`` check (D17): the gate judges
ONE file's content at write time, needs no corpus, and the remote tree is
deliberately outside corpus scope, so the docs-QA EDIT surface would never
dispatch on it in the first place.
"""

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
from claude_code_hooks_daemon.remote_docs.provenance import parse_provenance

_FIELD_FILE_PATH: Final[str] = "file_path"
_FIELD_CONTENT: Final[str] = "content"
_FIELD_NEW_STRING: Final[str] = "new_string"
_MARKDOWN_SUFFIX: Final[str] = ".md"
_FALLBACK_REMOTE_DOCS_DIR: Final[str] = "remote-docs"

_RULE_REMOTE_DOCS_PROVENANCE: Final[Rule] = Rule(
    rule_id=RuleID.REMOTE_DOCS_PROVENANCE,
    blocked="a write into the remote-docs tree without valid provenance frontmatter",
    why=(
        "A vendored document with no recorded source is indistinguishable from "
        "something we wrote ourselves, and cannot be refreshed, dated or trusted"
    ),
    fix="Capture with `hooks-daemon remote-docs add <url>` instead of hand-authoring",
    verbose=(
        "The remote-docs tree holds documentation captured from upstream, not "
        "written here. Every file carries provenance frontmatter: `source_url`, "
        "`fetched_at`, `fidelity`, `source_sha256`, `licence` and `stale_after`.\n\n"
        "Those fields are what make the corpus usable rather than merely present. "
        "Without `source_url` nothing can be refreshed; without `source_sha256` "
        "refresh cannot tell whether upstream actually changed; and without "
        "`fidelity` a model's paraphrase is indistinguishable from the document "
        "itself — which is the specific failure this tree exists to prevent, after "
        "a summarising fetch layer fabricated API detail in this repository.\n\n"
        "Capture: `bin/hooks-daemon remote-docs add <url>`\n"
        "Refresh: `bin/hooks-daemon remote-docs refresh --path <file>`\n\n"
        "Do not hand-edit a vendored document: rewording it silently falsifies "
        "its recorded `fidelity`."
    ),
)


class RemoteDocsProvenanceHandler(PreToolUseHandlerBase):
    """Deny a remote-tree write whose content lacks valid provenance."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.REMOTE_DOCS_PROVENANCE,
            priority=Priority.REMOTE_DOCS_PROVENANCE,
            tags=[HandlerTag.WORKFLOW, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )
        self._workspace_root: Path = ProjectContext.project_root()

    def _remote_docs_dir(self) -> str:
        layout = self._project_layout
        return layout.remote_docs_dir if layout is not None else _FALLBACK_REMOTE_DOCS_DIR

    def _relative_path(self, file_path: str) -> str | None:
        """Project-relative form of ``file_path``, or None when outside."""
        path = Path(file_path)
        if not path.is_absolute():
            return file_path
        try:
            return str(path.resolve().relative_to(self._workspace_root))
        except ValueError:
            return None

    def _added_text(self, hook_input: dict[str, Any]) -> str:
        """The text this call would put into the file.

        For ``Edit`` this is ``new_string``: only the ADDED text is judged,
        matching how every other content guard in this project treats an
        edit. Removing content is never blocked.
        """
        tool_input = hook_input.get(HookInputField.TOOL_INPUT, {})
        content = tool_input.get(_FIELD_CONTENT)
        if isinstance(content, str):
            return content
        new_string = tool_input.get(_FIELD_NEW_STRING)
        return new_string if isinstance(new_string, str) else ""

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True when this is a remote-tree markdown write lacking provenance."""
        if hook_input.get(HookInputField.TOOL_NAME) not in (ToolName.WRITE, ToolName.EDIT):
            return False

        file_path = hook_input.get(HookInputField.TOOL_INPUT, {}).get(_FIELD_FILE_PATH, "")
        if not isinstance(file_path, str) or not file_path.endswith(_MARKDOWN_SUFFIX):
            return False

        relative = self._relative_path(file_path)
        if relative is None:
            return False

        prefix = self._remote_docs_dir().strip("/") + "/"
        if not relative.startswith(prefix):
            return False

        return parse_provenance(self._added_text(hook_input)).provenance is None

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny, naming every invalid field and the way to do it properly."""
        result = parse_provenance(self._added_text(hook_input))
        problems = "\n".join(f"  - {error.field}: {error.message}" for error in result.errors)
        return GatingResult(
            decision=Decision.DENY,
            reason=(
                "REMOTE-DOCS PROVENANCE MISSING OR INVALID\n\n"
                "Every file in the vendored remote-docs tree must declare where "
                "it came from, so it can be refreshed, dated and trusted:\n\n"
                f"{problems}\n\n"
                "This tree is CAPTURED, not authored. Use:\n"
                "  bin/hooks-daemon remote-docs add <url>\n\n"
                "Editing a vendored document by hand also falsifies its recorded "
                "`fidelity` — if upstream changed, refresh it instead:\n"
                "  bin/hooks-daemon remote-docs refresh --path <file>"
            ),
        )

    def get_rules(self) -> list[Rule]:
        """The Rule backing this handler's blocking behaviour."""
        return [_RULE_REMOTE_DOCS_PROVENANCE]

    def get_claude_md(self) -> str | None:
        """Guidance injected into the project's CLAUDE.md."""
        return (
            "## remote_docs_provenance — vendored docs are captured, not written\n\n"
            "The remote-docs tree holds documentation fetched from upstream. A "
            "`Write`/`Edit` there is DENIED unless the content carries valid "
            "provenance frontmatter (`source_url`, `fetched_at`, `fidelity`, "
            "`source_sha256`, `licence`, `stale_after`).\n\n"
            "**Capture, do not author**: `bin/hooks-daemon remote-docs add <url>`. "
            "To pick up upstream changes: "
            "`bin/hooks-daemon remote-docs refresh --path <file>`.\n\n"
            "**Do not reword a vendored document.** Its `fidelity` field records "
            "whether the stored bytes are the upstream document or a paraphrase; "
            "editing it by hand makes that record false, and a paraphrase quoted "
            "as a citation is the failure this tree exists to prevent.\n\n"
            "**A `WebFetch` of a URL already vendored and still fresh is "
            "DENIED**, and the deny names the local path to read instead. A "
            "vendored copy that has gone STALE is never blocked — there the "
            "fetch is effectively the refresh. An unvendored URL is always "
            "allowed; if its domain is one the project declared as a "
            "documentation source (`documentation.remote.known_sources`), the "
            "allow carries a hint to capture the page durably.\n\n"
            "So: before fetching a URL, check whether it is already vendored "
            "— `bin/hooks-daemon remote-docs list` — and read the local copy."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Acceptance tests rendered into the release playbook."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="remote-docs provenance gate",
                command="Write remote-docs/example.com/page.md with no frontmatter",
                description=(
                    "A markdown write into the remote-docs tree without valid "
                    "provenance frontmatter is denied, naming every missing "
                    "field and the `remote-docs add` capture command"
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"REMOTE-DOCS PROVENANCE", r"remote-docs add"],
                safety_notes="Read-only check of the write payload; nothing is written",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="remote-docs provenance near-miss",
                command=(
                    "Write a markdown file OUTSIDE the remote-docs tree, e.g. "
                    "`docs/guides/notes.md`, with no frontmatter at all"
                ),
                description=(
                    "The gate is scoped to the vendored tree. Ordinary "
                    "documentation carries no provenance and must stay writable"
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Ordinary doc write; no provenance is expected there",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
