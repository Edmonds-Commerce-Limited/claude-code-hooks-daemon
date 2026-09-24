"""Every QA corpus that enumerates files from disk answers "is this part of
the project" the same way (Plan 00466 N9).

``docs_qa/corpus.py`` walked the filesystem with no regard for
``.gitignore``, so installing a Claude Code plugin -- which vendors spec
markdown into the gitignored ``.claude/ccy/plugins/`` tree -- made
``source-tree-markdown`` report 12 findings for files that are not this
project's documentation. The fix was :func:`utils.git_repo.git_visible_paths`
(tracked files, plus untracked files no ``.gitignore`` rule excludes), now
consumed by ``docs_qa/corpus.py`` and ``scripts/qa/check_doc_truth.py``
(which had the SAME gap under a different name: ``.claude/ccy/plugins/cache/``
was never added to its directory denylist).

That remedy's own text asks for a CLASS audit: every other QA corpus named in
the ledger entry either moves onto the same shared helper, or documents why
it must see ignored files. This is that audit, made mechanical rather than a
one-off note: :data:`_AUDIT` is the declared verdict for each corpus, and the
tests below verify each declared fact still holds, the same ratchet shape
``test_qa_package_dependency_direction.py`` uses for import edges. A corpus
that starts walking the filesystem again without updating its entry here, or
whose entry claims "migrated" but stops importing the shared helper, fails
the test that exercises it.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

#: The one shared "what counts as part of the project" function every
#: migrated corpus must import and call.
_SHARED_HELPER_MODULE: Final[str] = "claude_code_hooks_daemon.utils.git_repo"
_SHARED_HELPER_NAME: Final[str] = "git_visible_paths"


class Verdict(Enum):
    """Whether a corpus's file discovery goes through the shared helper."""

    MIGRATED = "migrated"
    ALLOWLISTED = "allowlisted"


@dataclass(frozen=True)
class AuditEntry:
    """One corpus's declared verdict, evidence file, and reason."""

    verdict: Verdict
    source: str  # repo-relative path to the file that does the enumeration
    reason: str  # why MIGRATED is safe to skip, or ALLOWLISTED is justified


#: Every QA corpus named in ledger 00466 N9's remedy text, plus ``docs_qa``
#: itself (the corpus the defect was found in). Shrink an entry's verdict to
#: MIGRATED when it moves onto the shared helper; never mark ALLOWLISTED
#: without a reason a reviewer could check.
_AUDIT: Final[dict[str, AuditEntry]] = {
    "docs_qa": AuditEntry(
        verdict=Verdict.MIGRATED,
        source="src/claude_code_hooks_daemon/docs_qa/corpus.py",
        reason=(
            "iter_markdown_paths/iter_corpus_paths both filter through "
            "git_visible_paths -- the corpus this defect was found in."
        ),
    ),
    "doc_truth": AuditEntry(
        verdict=Verdict.MIGRATED,
        source="scripts/qa/check_doc_truth.py",
        reason=(
            "_iter_markdown had the SAME gap under a different name -- its "
            "_UNSCANNED_DIR_NAMES denylist covered `marketplaces` but not "
            "`.claude/ccy/plugins/cache/`. Reproduced directly "
            "(test_does_not_scan_a_gitignored_vendored_plugin_install) and "
            "fixed by filtering through git_visible_paths too."
        ),
    ),
    "doc_snippets": AuditEntry(
        verdict=Verdict.ALLOWLISTED,
        source="scripts/qa/check_doc_snippets.py",
        reason=(
            "_SCANNED_GLOBS names CLAUDE/**, docs/**, .claude/*.md (top-level "
            "only), .claude/agents/*.md, src/**, examples/**, README.md, "
            "CONTRIBUTING.md -- none reaches .claude/ccy/ (a *nested* .claude "
            "subtree), so the gitignored plugin install this ledger entry "
            "reports is structurally unreachable by this glob set today."
        ),
    ),
    "repo_hygiene": AuditEntry(
        verdict=Verdict.ALLOWLISTED,
        source="scripts/qa/check_repo_hygiene.py",
        reason=(
            "Ground truth is `git ls-files` by design (its own module "
            "docstring): only a TRACKED file can be a hygiene violation, "
            "an untracked one is a normal working-tree byproduct. Already "
            "git-native, deliberately narrower than git_visible_paths "
            "(tracked only, no --others)."
        ),
    ),
    "sensitive_content": AuditEntry(
        verdict=Verdict.ALLOWLISTED,
        source="scripts/qa/check_sensitive_content.py",
        reason=(
            "Scans `git ls-files` by design (its own module docstring: "
            "'the whole GIT-TRACKED tree ... never a filesystem walk') -- "
            "already git-native."
        ),
    ),
    "british_english": AuditEntry(
        verdict=Verdict.ALLOWLISTED,
        source="scripts/qa/check_british_english.py",
        reason="Already scans `git ls-files -z` directly -- git-native.",
    ),
    "magic_values": AuditEntry(
        verdict=Verdict.ALLOWLISTED,
        source="scripts/qa/check_magic_values.py",
        reason=(
            "rglob is scoped to src/claude_code_hooks_daemon and tests/ "
            "only -- pure project-code directories with no .gitignore rule "
            "that creates a gap in either (unlike a config/cache tree such "
            "as .claude/ccy/), so there is no route to gitignored content."
        ),
    ),
    "error_hiding": AuditEntry(
        verdict=Verdict.ALLOWLISTED,
        source="scripts/qa/audit_error_hiding.py",
        reason=(
            "AUDITED_DIRECTORIES is ('src', 'scripts') plus a named root-file "
            "list -- same reasoning as magic_values: project-code "
            "directories only, no gitignore gap to close."
        ),
    ),
    "handler_reference": AuditEntry(
        verdict=Verdict.ALLOWLISTED,
        source="scripts/qa/check_handler_reference.py",
        reason=(
            "Does not enumerate files at all -- it imports HandlerRegistry "
            "and introspects live handler objects. Not exposed to this "
            "defect class because it never walks a directory."
        ),
    ),
    "plan_qa": AuditEntry(
        verdict=Verdict.ALLOWLISTED,
        source="src/claude_code_hooks_daemon/plan_qa/model.py",
        reason=(
            "PlanTree.scan descends the CONFIGURED plan directory only, via "
            "iterdir() -- never a project-root-wide walk. Nothing under "
            "CLAUDE/Plan/ is gitignored in this repo, and the plan tree is "
            "core tracked content the whole plan workflow already assumes "
            "is tracked."
        ),
    ),
}


def _read(rel_path: str) -> str:
    return (_REPO_ROOT / rel_path).read_text(encoding="utf-8")


def _imports_shared_helper(source: str) -> bool:
    """Whether ``source`` imports :data:`_SHARED_HELPER_NAME` from the
    shared module, by either import form."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == _SHARED_HELPER_MODULE
            and node.level == 0
            and any(alias.name == _SHARED_HELPER_NAME for alias in node.names)
        ):
            return True
        if isinstance(node, ast.Import) and any(
            alias.name == _SHARED_HELPER_MODULE for alias in node.names
        ):
            # A plain `import module` form would need `module.git_visible_paths(...)`
            # -- checked as a call below, not here, since the import alone
            # does not prove the module's own alias is spelt this way.
            continue
    return False


def _calls_shared_helper(source: str) -> bool:
    """Whether ``source`` actually CALLS the shared helper, not merely imports it."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == _SHARED_HELPER_NAME:
            return True
        if isinstance(func, ast.Attribute) and func.attr == _SHARED_HELPER_NAME:
            return True
    return False


class TestEveryNamedCorpusIsAudited:
    """The set this file covers must match the ledger's own list exactly."""

    def test_every_ledger_named_corpus_has_an_entry(self) -> None:
        named = {
            "plan_qa",
            "doc_snippets",
            "doc_truth",
            "repo_hygiene",
            "sensitive_content",
            "british_english",
            "magic_values",
            "error_hiding",
            "handler_reference",
            "docs_qa",
        }
        missing = named - set(_AUDIT)
        assert missing == set(), f"corpora named in the ledger with no audit entry: {missing}"


class TestMigratedCorporaActuallyUseTheSharedHelper:
    """A MIGRATED verdict is a claim this test enforces, not just records."""

    def test_every_migrated_entry_imports_and_calls_the_shared_helper(self) -> None:
        failures: list[str] = []
        for name, entry in _AUDIT.items():
            if entry.verdict is not Verdict.MIGRATED:
                continue
            source = _read(entry.source)
            if not _imports_shared_helper(source):
                failures.append(f"{name} ({entry.source}): does not import {_SHARED_HELPER_NAME}")
            elif not _calls_shared_helper(source):
                failures.append(f"{name} ({entry.source}): imports but never calls it")
        assert failures == [], "; ".join(failures)


class TestEveryAuditedSourceFileExists:
    """A stale path claim is worse than no audit at all -- it looks checked."""

    def test_every_declared_source_path_exists(self) -> None:
        missing = sorted(
            f"{name} -> {entry.source}"
            for name, entry in _AUDIT.items()
            if not (_REPO_ROOT / entry.source).is_file()
        )
        assert missing == [], f"audited source files no longer exist: {missing}"


class TestEveryAllowlistedEntryHasAReason:
    def test_every_allowlisted_entry_has_a_non_trivial_reason(self) -> None:
        thin = sorted(
            name
            for name, entry in _AUDIT.items()
            if entry.verdict is Verdict.ALLOWLISTED and len(entry.reason) < 20
        )
        assert thin == [], f"allowlisted with no real reason: {thin}"


class TestTheDetectionWouldSeeAMigrationIfItHappened:
    """A ratchet nobody has watched fire is a ratchet nobody has tested."""

    def test_a_from_import_and_call_is_detected(self) -> None:
        source = (
            "from claude_code_hooks_daemon.utils.git_repo import git_visible_paths\n"
            "def f(root):\n    return git_visible_paths(root)\n"
        )
        assert _imports_shared_helper(source) is True
        assert _calls_shared_helper(source) is True

    def test_import_without_a_call_is_not_a_migration(self) -> None:
        source = "from claude_code_hooks_daemon.utils.git_repo import git_visible_paths\n"
        assert _imports_shared_helper(source) is True
        assert _calls_shared_helper(source) is False

    def test_an_unrelated_import_is_not_detected(self) -> None:
        source = "from claude_code_hooks_daemon.utils.git_repo import run_git\n"
        assert _imports_shared_helper(source) is False
