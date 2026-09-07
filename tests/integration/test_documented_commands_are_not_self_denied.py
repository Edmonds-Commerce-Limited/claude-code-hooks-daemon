"""No shipped document may instruct a command this daemon's own handlers deny.

Plan 00336 Phase 4. ``README.md``, ``CLAUDE/LLM-INSTALL.md``,
``CLAUDE/LLM-UPDATE.md``, ``docs/guides/GETTING_STARTED.md`` and
``CLAUDE/development/RELEASING.md`` all instruct a bootstrap fetch of the shape
``curl -fsSL <url> -o /tmp/<name>``. ``project_containment`` covers
``curl -o``/``--output``, so an agent following the documented AI-assisted
install, update or release-verification flow inside an installed project is
denied by this project's own handler — verified live, not inferred.

The update case is the guaranteed one: the daemon is by definition installed
and running, so every fetch in ``LLM-UPDATE.md`` is denied every time. The
release case bites in this repository itself, where the daemon is self-installed
and Step 14's verification stanza writes four files into ``/tmp``.

The security property to preserve is fetch-review-run: the operator downloads,
reads the script, and only then executes it — the reason these docs deliberately
avoid ``curl | bash``. Moving the destination inside the repository keeps that
intact, satisfies containment, and gains durability, because a container temp
directory does not survive a restart.

Rather than pattern-matching for ``/tmp`` — which would drift from whatever the
handler actually enforces — this test extracts the commands from the documents
and puts them through the live ``ProjectContainmentHandler``. If the handler's
boundary changes, this test follows it automatically.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.project_containment import (
    ProjectContainmentHandler,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Instruction documents an agent or operator is told to follow verbatim.
#: Deliberately NOT the whole markdown corpus:
#:
#: * ``CLAUDE/UPGRADES/`` records what a PAST upgrade looked like. Editing those
#:   to satisfy a handler that did not exist then would falsify the record.
#: * ``CLAUDE/Plan/`` quotes offending commands as evidence, which is the point.
DOCUMENT_GLOBS = (
    "README.md",
    "BUG_REPORTING.md",
    "CONTRIBUTING.md",
    "CLAUDE/*.md",
    "CLAUDE/development/*.md",
    "CLAUDE/CodeLifecycle/*.md",
    "docs/**/*.md",
    # The skill tree an agent follows verbatim. This is the SOURCE, not the
    # deployed `.claude/skills/` copy: the deployed one is a generated artifact
    # that `docs_qa` already guards against hand-edits, and it lags the source
    # until a redeploy — which would make this test fail for a deployment gap
    # rather than for a denied command.
    "src/claude_code_hooks_daemon/skills/**/*.md",
)

#: A fence: three or more backticks, optionally followed by an info string.
#: The length matters. CommonMark closes a fence only with a run at least as
#: long as the opening one, which is how a document can show a fence INSIDE a
#: fence — ``RELEASING.md`` does. Treating every ``` as a toggle desynchronises
#: there and silently skips 40 lines, including a denied command.
_FENCE = re.compile(r"^\s*(`{3,})\s*(\S*)\s*$")

#: Fence languages that hold commands a reader is expected to run.
_SHELL_LANGUAGES = frozenset({"", "bash", "sh", "shell", "console"})

#: A command line starts with a command. Untagged fences also carry prose and
#: path placeholders, and ``<project-root>/.claude/hooks-daemon.yaml`` parses as
#: a redirect to an absolute path that really is outside the repository — a true
#: reading of a line nobody would ever run. Anchoring on the first character
#: keeps the scan to things that are actually invocations.
_COMMAND_START = re.compile(r"[A-Za-z0-9_./$\"'-]")


def _shell_lines(markdown: str) -> list[tuple[int, str]]:
    """Return ``(line_number, command)`` for every shell line in a fenced block.

    Line numbers are 1-based so a failure message points straight at the file.
    """
    lines = markdown.splitlines()
    collected: list[tuple[int, str]] = []
    language: str | None = None
    open_length = 0

    for index, line in enumerate(lines, start=1):
        fence = _FENCE.match(line)
        if fence is not None:
            ticks, info = fence.group(1), fence.group(2).lower()
            if language is None:
                language, open_length = info, len(ticks)
                continue
            if not info and len(ticks) >= open_length:
                language, open_length = None, 0
                continue
        if language is None or language not in _SHELL_LANGUAGES:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not _COMMAND_START.match(stripped):
            continue
        collected.append((index, stripped))

    return collected


def _documents() -> list[Path]:
    found: list[Path] = []
    for glob in DOCUMENT_GLOBS:
        found.extend(sorted(REPO_ROOT.glob(glob)))
    return found


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> Any:
    """The handler suppresses repeat guidance; each command must be judged fresh."""
    reset_data_layer()
    yield
    reset_data_layer()


@pytest.fixture()
def handler() -> ProjectContainmentHandler:
    return ProjectContainmentHandler()


def _judge(handler: ProjectContainmentHandler, command: str) -> Any:
    """Run one documented command through the handler as a Bash PreToolUse event."""
    with patch(
        "claude_code_hooks_daemon.core.project_context.ProjectContext.project_root"
    ) as project_root:
        project_root.return_value = REPO_ROOT
        return handler.handle(
            {
                "tool_name": "Bash",
                "tool_input": {"command": command},
                "cwd": str(REPO_ROOT),
            }
        )


class TestShippedDocsDoNotInstructDeniedCommands:
    """Dogfooding: our own instructions must survive our own handlers."""

    def test_the_corpus_is_actually_being_scanned(self) -> None:
        """A glob typo would make every other test in this file vacuous."""
        documents = _documents()

        assert len(documents) > 10, f"only found {len(documents)} documents to scan"
        names = {document.name for document in documents}
        for required in ("README.md", "LLM-INSTALL.md", "LLM-UPDATE.md", "RELEASING.md"):
            assert required in names, f"{required} is not in the scanned corpus"

    def test_no_documented_command_is_denied_by_project_containment(
        self, handler: ProjectContainmentHandler
    ) -> None:
        """Every runnable line in every instruction doc must be allowed."""
        offences: list[str] = []

        for document in _documents():
            relative = document.relative_to(REPO_ROOT)
            for line_number, command in _shell_lines(document.read_text()):
                if _judge(handler, command).decision == Decision.DENY:
                    offences.append(f"{relative}:{line_number}: {command}")

        assert not offences, (
            "Shipped documents instruct commands this project's own "
            "project_containment handler denies. An agent following them is "
            "blocked by us, on our own guidance:\n  " + "\n  ".join(offences)
        )


class TestTheFetchReviewRunPatternSurvives:
    """The fix must not quietly become ``curl | bash``."""

    def test_the_bootstrap_docs_still_download_before_executing(self) -> None:
        """A separate download step is what makes review possible at all.

        ``LLM-INSTALL.md`` says so in as many words — "We intentionally avoid
        `curl | bash` because the daemon itself blocks that pattern as a
        security risk. Practice what we preach." Relocating the destination
        must not cost that.
        """
        for name in ("CLAUDE/LLM-INSTALL.md", "CLAUDE/LLM-UPDATE.md"):
            document = REPO_ROOT / name
            content = document.read_text()
            assert "curl" in content, f"{name} no longer fetches anything"

            # Only RUNNABLE lines count. LLM-INSTALL.md names `curl | bash` in
            # its prose precisely to say it refuses to use it, so scanning the
            # whole file would fail on the promise rather than on a breach.
            piped = [
                f"{name}:{line_number}: {command}"
                for line_number, command in _shell_lines(content)
                if "curl" in command and ("| bash" in command or "| sh" in command)
            ]
            assert not piped, (
                "A download is piped straight into a shell — the exact pattern "
                "this daemon blocks and these docs promise not to use:\n  " + "\n  ".join(piped)
            )

    def test_downloads_land_somewhere_durable_and_ignored(self) -> None:
        """``untracked/`` is gitignored and survives a container restart.

        ``ensure_scratch_dir`` (Plan 00333) creates ``untracked/scratch/`` and
        its ignore file, so by the time an UPDATE is run the destination is
        already there. A fresh INSTALL predates the daemon, so those documents
        must create the directory themselves rather than assume it.
        """
        for name in ("CLAUDE/LLM-INSTALL.md", "docs/guides/GETTING_STARTED.md"):
            content = (REPO_ROOT / name).read_text()
            assert "mkdir -p untracked/scratch" in content, (
                f"{name} downloads into untracked/scratch/ but never creates it "
                "— on a fresh install nothing has made that directory yet."
            )
