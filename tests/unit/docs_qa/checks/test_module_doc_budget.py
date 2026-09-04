"""Tests for check ``module-doc-budget`` (Plan 00284, Task 3.1e)."""

import os
from collections.abc import Callable, Generator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.layout import CORE_VENDORED_BUILD_DIR_NAMES
from claude_code_hooks_daemon.docs_qa.checks.module_doc_budget import (
    CHECK_ID,
    CHECKS,
    UNREGISTERED_MODULE_DOC_LINE_BUDGET,
    _iter_module_doc_paths,
)
from claude_code_hooks_daemon.docs_qa.context import edit_context, sweep_context
from claude_code_hooks_daemon.docs_qa.corpus import DocCorpus
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy, DocumentationQaPolicy
from claude_code_hooks_daemon.docs_qa.types import CheckContext, CheckStage, Finding, Severity
from claude_code_hooks_daemon.utils.vendor_paths import VendorScope


def _run_edit(context: CheckContext) -> list[Finding]:
    for spec in CHECKS:
        if spec.stage is CheckStage.EDIT:
            return spec.run(context)
    raise AssertionError("no EDIT check registered")


def _run_sweep(context: CheckContext) -> list[Finding]:
    for spec in CHECKS:
        if spec.stage is CheckStage.SWEEP:
            return spec.run(context)
    raise AssertionError("no SWEEP check registered")


_LONG_BODY = "\n".join(f"line {i}" for i in range(UNREGISTERED_MODULE_DOC_LINE_BUDGET + 10))
_SHORT_BODY = "short module doc\n"


class TestRegistration:
    def test_registers_edit_and_sweep(self) -> None:
        stages = {spec.stage for spec in CHECKS}
        assert stages == {CheckStage.EDIT, CheckStage.SWEEP}
        assert all(spec.check_id == CHECK_ID for spec in CHECKS)


class TestScope:
    def test_root_claude_md_is_exempt(self, tmp_path: Path) -> None:
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE.md",
            file_content=_LONG_BODY,
            file_exists_before=False,
        )
        assert _run_edit(context) == []

    def test_agent_tree_root_claude_md_is_exempt(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "CLAUDE" / "CLAUDE.md",
            file_content=_LONG_BODY,
            file_exists_before=False,
        )
        assert _run_edit(context) == []

    def test_non_claude_md_file_is_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "src" / "Other.md",
            file_content=_LONG_BODY,
            file_exists_before=False,
        )
        assert _run_edit(context) == []


class TestUnregisteredBudget:
    def test_under_budget_produces_no_finding(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "foo").mkdir(parents=True)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "src" / "foo" / "CLAUDE.md",
            file_content=_SHORT_BODY,
            file_exists_before=False,
        )
        assert _run_edit(context) == []

    def test_new_over_budget_doc_is_advise_never_block(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "foo").mkdir(parents=True)
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "src" / "foo" / "CLAUDE.md",
            file_content=_LONG_BODY,
            file_exists_before=False,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert findings[0].check_id == CHECK_ID
        assert findings[0].severity is Severity.ADVISE
        assert findings[0].path == "src/foo/CLAUDE.md"


class TestRegisteredBudget:
    def test_registered_well_under_advisory_tier_is_clean(self, tmp_path: Path) -> None:
        """A registered doc is a canonical home (R7d), not a routing table --
        it must be measured against the registered advisory tier (350
        lines), never the unregistered 40-line routing/guard budget. This is
        the module-doc-budget bug: ``.claude/ccy/CLAUDE.md`` (65 lines,
        registered) was reported against the wrong tier with an "or
        register it" remediation that made no sense for an already
        registered doc."""
        (tmp_path / "src" / "foo").mkdir(parents=True)
        policy = DocumentationPolicy(
            qa=DocumentationQaPolicy(registered_module_docs=("src/foo/CLAUDE.md",))
        )
        context = edit_context(
            project_root=tmp_path,
            policy=policy,
            file_path=tmp_path / "src" / "foo" / "CLAUDE.md",
            file_content=_LONG_BODY,
            file_exists_before=False,
        )
        assert _run_edit(context) == []

    def test_registered_over_advisory_under_block_tier_is_advise(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "foo").mkdir(parents=True)
        policy = DocumentationPolicy(
            qa=DocumentationQaPolicy(registered_module_docs=("src/foo/CLAUDE.md",))
        )
        body = "\n".join(f"line {i}" for i in range(400))  # over 350, under 900
        context = edit_context(
            project_root=tmp_path,
            policy=policy,
            file_path=tmp_path / "src" / "foo" / "CLAUDE.md",
            file_content=body,
            file_exists_before=False,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE
        assert "register it" not in findings[0].remediation

    def test_registered_growing_past_block_tier_is_block(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "foo").mkdir(parents=True)
        policy = DocumentationPolicy(
            qa=DocumentationQaPolicy(registered_module_docs=("src/foo/CLAUDE.md",))
        )
        huge_body = "\n".join(f"line {i}" for i in range(1000))
        context = edit_context(
            project_root=tmp_path,
            policy=policy,
            file_path=tmp_path / "src" / "foo" / "CLAUDE.md",
            file_content=huge_body,
            file_exists_before=False,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.BLOCK

    def test_registered_unchanged_size_over_block_tier_is_advise(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "foo").mkdir(parents=True)
        policy = DocumentationPolicy(
            qa=DocumentationQaPolicy(registered_module_docs=("src/foo/CLAUDE.md",))
        )
        huge_body = "\n".join(f"line {i}" for i in range(1000))
        context = edit_context(
            project_root=tmp_path,
            policy=policy,
            file_path=tmp_path / "src" / "foo" / "CLAUDE.md",
            file_content=huge_body,
            file_exists_before=True,
            file_content_before=huge_body,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE

    def test_registered_shrinking_past_block_tier_is_silent(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "foo").mkdir(parents=True)
        policy = DocumentationPolicy(
            qa=DocumentationQaPolicy(registered_module_docs=("src/foo/CLAUDE.md",))
        )
        huge_body = "\n".join(f"line {i}" for i in range(1000))
        smaller_but_still_over = "\n".join(f"line {i}" for i in range(950))
        context = edit_context(
            project_root=tmp_path,
            policy=policy,
            file_path=tmp_path / "src" / "foo" / "CLAUDE.md",
            file_content=smaller_but_still_over,
            file_exists_before=True,
            file_content_before=huge_body,
        )
        assert _run_edit(context) == []


class TestGrandfatherAllowlist:
    def test_grandfathered_registered_doc_growing_past_block_tier_is_advise(
        self, tmp_path: Path
    ) -> None:
        """F2 (Plan 00287): grandfather_allowlist must downgrade a NEW
        over-block-tier finding to ADVISE, mirroring rules-file-shape and
        pointer-resolves -- R12's "held to advise-only forever" promise."""
        (tmp_path / "src" / "foo").mkdir(parents=True)
        policy = DocumentationPolicy(
            qa=DocumentationQaPolicy(
                registered_module_docs=("src/foo/CLAUDE.md",),
                grandfather_allowlist=("src/foo/CLAUDE.md",),
            )
        )
        huge_body = "\n".join(f"line {i}" for i in range(1000))
        context = edit_context(
            project_root=tmp_path,
            policy=policy,
            file_path=tmp_path / "src" / "foo" / "CLAUDE.md",
            file_content=huge_body,
            file_exists_before=False,
        )
        findings = _run_edit(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE


class TestQuoteBlocksExcludedFromCount:
    def test_ssot_quote_body_does_not_count_toward_the_budget(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "foo").mkdir(parents=True)
        quote_lines = "\n".join(f"quoted line {i}" for i in range(200))
        content = (
            "short intro\n\n<!-- ssot-quote: CLAUDE/Doc.md#x -->\n"
            f"{quote_lines}\n<!-- /ssot-quote -->\n"
        )
        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            file_path=tmp_path / "src" / "foo" / "CLAUDE.md",
            file_content=content,
            file_exists_before=False,
        )
        assert _run_edit(context) == []


class TestSweepStage:
    """SWEEP walks project_root directly -- module-doc CLAUDE.md files are not
    necessarily inside the doc corpus's own tree scope (the same reason
    generated_doc_hand_edit's SWEEP is corpus-independent)."""

    def test_reports_over_budget_module_doc_as_advise(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "src" / "foo").mkdir(parents=True)
        (tmp_path / "src" / "foo" / "CLAUDE.md").write_text(_LONG_BODY)
        policy = DocumentationPolicy()

        context = sweep_context(
            project_root=tmp_path, policy=policy, corpus=DocCorpus(project_root=tmp_path)
        )
        findings = _run_sweep(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE
        assert findings[0].path == "src/foo/CLAUDE.md"

    def test_clean_tree_produces_no_findings(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "src" / "foo").mkdir(parents=True)
        (tmp_path / "src" / "foo" / "CLAUDE.md").write_text(_SHORT_BODY)
        policy = DocumentationPolicy()

        context = sweep_context(
            project_root=tmp_path, policy=policy, corpus=DocCorpus(project_root=tmp_path)
        )
        assert _run_sweep(context) == []

    def test_root_and_agent_tree_claude_md_are_skipped_by_sweep(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "CLAUDE.md").write_text(_LONG_BODY)
        (tmp_path / "CLAUDE" / "CLAUDE.md").write_text(_LONG_BODY)
        policy = DocumentationPolicy()

        context = sweep_context(
            project_root=tmp_path, policy=policy, corpus=DocCorpus(project_root=tmp_path)
        )
        assert _run_sweep(context) == []

    def test_registered_well_under_advisory_tier_is_clean_in_sweep(self, tmp_path: Path) -> None:
        """Sweep-side counterpart of the EDIT-arm regression above: the
        registry must be consulted here too, or a registered doc keeps
        being reported against the unregistered budget by the sweep even
        after the EDIT arm is fixed."""
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "src" / "foo").mkdir(parents=True)
        (tmp_path / "src" / "foo" / "CLAUDE.md").write_text(_LONG_BODY)
        policy = DocumentationPolicy(
            qa=DocumentationQaPolicy(registered_module_docs=("src/foo/CLAUDE.md",))
        )

        context = sweep_context(
            project_root=tmp_path, policy=policy, corpus=DocCorpus(project_root=tmp_path)
        )
        assert _run_sweep(context) == []

    def test_registered_over_block_tier_is_downgraded_to_advise_in_sweep(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "src" / "foo").mkdir(parents=True)
        huge_body = "\n".join(f"line {i}" for i in range(1000))
        (tmp_path / "src" / "foo" / "CLAUDE.md").write_text(huge_body)
        policy = DocumentationPolicy(
            qa=DocumentationQaPolicy(registered_module_docs=("src/foo/CLAUDE.md",))
        )

        context = sweep_context(
            project_root=tmp_path, policy=policy, corpus=DocCorpus(project_root=tmp_path)
        )
        findings = _run_sweep(context)
        assert len(findings) == 1
        assert findings[0].severity is Severity.ADVISE

    def test_broken_symlink_named_claude_md_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "src" / "foo").mkdir(parents=True)
        broken_link = tmp_path / "src" / "foo" / "CLAUDE.md"
        broken_link.symlink_to(tmp_path / "does-not-exist.md")
        policy = DocumentationPolicy()
        context = sweep_context(
            project_root=tmp_path, policy=policy, corpus=DocCorpus(project_root=tmp_path)
        )
        assert _run_sweep(context) == []

    def test_excludes_common_heavy_directories(self, tmp_path: Path) -> None:
        for heavy_dir in (
            "node_modules",
            "untracked",
            ".git",
            "vendor",
            "dist",
            "build",
            "target",
            ".venv",
            ".next",
            "third_party",
        ):
            nested = tmp_path / heavy_dir / "sub"
            nested.mkdir(parents=True)
            (nested / "CLAUDE.md").write_text(_LONG_BODY)
        policy = DocumentationPolicy()

        context = sweep_context(
            project_root=tmp_path, policy=policy, corpus=DocCorpus(project_root=tmp_path)
        )
        assert _run_sweep(context) == []

    def test_walk_does_not_physically_descend_into_excluded_directories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """F3 (Plan 00287): the walk must PRUNE excluded directories (never
        enter them at all), not merely post-filter their results -- a plain
        ``Path.rglob`` still physically descends a huge ``node_modules`` or
        ``.git`` tree every session start even though its matches are later
        discarded."""
        (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
        (tmp_path / "node_modules" / "pkg" / "CLAUDE.md").write_text(_LONG_BODY)
        (tmp_path / "src" / "foo").mkdir(parents=True)
        (tmp_path / "src" / "foo" / "CLAUDE.md").write_text(_SHORT_BODY)

        entered_dirs: list[str] = []
        real_walk = os.walk

        def _spying_walk(
            top: str,
            topdown: bool = True,
            onerror: Callable[[OSError], object] | None = None,
            followlinks: bool = False,
        ) -> Generator[tuple[str, list[str], list[str]], None, None]:
            for dirpath, dirnames, filenames in real_walk(
                top, topdown=topdown, onerror=onerror, followlinks=followlinks
            ):
                entered_dirs.append(dirpath)
                yield dirpath, dirnames, filenames

        monkeypatch.setattr(os, "walk", _spying_walk)

        matches = _iter_module_doc_paths(tmp_path, "CLAUDE")

        assert "src/foo/CLAUDE.md" in matches
        # Proves the walk went through os.walk at all (a pruned rglob never
        # calls it) -- an empty entered_dirs would make the assertion below
        # pass vacuously without actually exercising the pruning behaviour.
        assert entered_dirs
        assert not any("node_modules" in entered for entered in entered_dirs)

    def test_excludes_claude_worktrees_copies(self, tmp_path: Path) -> None:
        """Task 3.3 T2: this check's OWN rglob walk (independent of
        docs_qa.corpus) must also skip transient agent-worktree checkouts,
        or every module CLAUDE.md gets re-flagged once per live worktree."""
        worktree_doc = tmp_path / ".claude" / "worktrees" / "agent-x" / "src" / "foo" / "CLAUDE.md"
        worktree_doc.parent.mkdir(parents=True)
        worktree_doc.write_text(_LONG_BODY)
        policy = DocumentationPolicy()

        context = sweep_context(
            project_root=tmp_path, policy=policy, corpus=DocCorpus(project_root=tmp_path)
        )
        assert _run_sweep(context) == []

    def test_excludes_vendored_daemon_install_copies(self, tmp_path: Path) -> None:
        """Task 3.6: this check's OWN rglob walk must also skip a CLIENT
        project's vendored ``.claude/hooks-daemon/`` install, or every one of
        the daemon's own module docs gets reported as the client's findings."""
        vendored_doc = tmp_path / ".claude" / "hooks-daemon" / "src" / "foo" / "CLAUDE.md"
        vendored_doc.parent.mkdir(parents=True)
        vendored_doc.write_text(_LONG_BODY)
        policy = DocumentationPolicy()

        context = sweep_context(
            project_root=tmp_path, policy=policy, corpus=DocCorpus(project_root=tmp_path)
        )
        assert _run_sweep(context) == []

    def test_unreadable_file_is_skipped_not_fatal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """N5 (Plan 00287): an unreadable file must not abort the whole
        SessionStart sweep."""
        (tmp_path / "src" / "foo").mkdir(parents=True)
        target = tmp_path / "src" / "foo" / "CLAUDE.md"
        target.write_text(_LONG_BODY)
        policy = DocumentationPolicy()

        original_read_text = Path.read_text

        def _raising_read_text(
            self: Path, encoding: str | None = None, errors: str | None = None
        ) -> str:
            if self == target:
                raise OSError("permission denied")
            return original_read_text(self, encoding=encoding, errors=errors)

        monkeypatch.setattr(Path, "read_text", _raising_read_text)
        context = sweep_context(
            project_root=tmp_path, policy=policy, corpus=DocCorpus(project_root=tmp_path)
        )
        assert _run_sweep(context) == []

    def test_self_install_mode_is_unaffected(self, tmp_path: Path) -> None:
        """Self-install mode (this repo) has no ``.claude/hooks-daemon/``
        vendored copy -- a real module doc under a dir that merely CONTAINS
        "hooks-daemon" in its path must still be swept and flagged."""
        real_doc = (
            tmp_path / "src" / "claude_code_hooks_daemon" / "skills" / "hooks-daemon" / "CLAUDE.md"
        )
        real_doc.parent.mkdir(parents=True)
        real_doc.write_text(_LONG_BODY)
        policy = DocumentationPolicy()

        context = sweep_context(
            project_root=tmp_path, policy=policy, corpus=DocCorpus(project_root=tmp_path)
        )
        findings = _run_sweep(context)
        assert len(findings) == 1
        assert findings[0].path == "src/claude_code_hooks_daemon/skills/hooks-daemon/CLAUDE.md"


class TestConfiguredScopeExclusionsAreHonoured:
    """Client bug: a project configured ignored directories and this check
    kept reporting module docs inside them.

    Cause: this check enumerates with its OWN ``os.walk`` rather than going
    through ``docs_qa.corpus``, and prunes only the hardcoded
    ``_EXCLUDED_DIR_NAMES``. The configured ``scope_exclude_globs`` was
    consulted nowhere in either stage. ``corpus.matches_scope_exclude`` is
    public for exactly this case -- ``source_tree_markdown`` already applies
    it to paths outside the corpus's scope; this check simply never did.
    """

    # The reported path shape, deliberately. An earlier draft of these tests
    # used ``vendor/`` and ``third_party/`` and passed against the UNFIXED
    # code -- both are already in ``COMMON_VENDORED_BUILD_DIR_NAMES``, so the
    # hardcoded prune was doing the work and the configured exclusion was
    # never exercised at all. An ansible-galaxy role directory is covered by
    # no hardcoded rule, which is exactly why the client had to configure one.
    _ROLES_GLOB = "infra/ansible/roles/**"
    _EXCLUDED = DocumentationQaPolicy(scope_exclude_globs=(_ROLES_GLOB,))
    _DOC_REL = "infra/ansible/roles/lts.vault-scripts/shellscripts/CLAUDE.md"

    @staticmethod
    def _write_role_doc(tmp_path: Path) -> Path:
        doc = tmp_path / TestConfiguredScopeExclusionsAreHonoured._DOC_REL
        doc.parent.mkdir(parents=True)
        doc.write_text(_LONG_BODY)
        return doc

    def test_sweep_skips_a_module_doc_under_an_excluded_dir(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        self._write_role_doc(tmp_path)

        context = sweep_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(qa=self._EXCLUDED),
            corpus=DocCorpus(project_root=tmp_path),
        )
        assert _run_sweep(context) == []

    def test_edit_skips_a_module_doc_under_an_excluded_dir(self, tmp_path: Path) -> None:
        """The EDIT arm had no exclusion test at all, so fixing only the
        walk would still report a doc the project declared out of scope."""
        doc = self._write_role_doc(tmp_path)

        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(qa=self._EXCLUDED),
            file_path=doc,
            file_content=_LONG_BODY,
            file_exists_before=False,
        )
        assert _run_edit(context) == []

    def test_a_filename_shape_pattern_is_honoured_too(self, tmp_path: Path) -> None:
        """``matches_scope_exclude`` matches the bare basename as well as the
        full path, so a slash-less pattern must work here identically."""
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "infra").mkdir()
        (tmp_path / "infra" / "CLAUDE.md").write_text(_LONG_BODY)

        context = sweep_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(
                qa=DocumentationQaPolicy(scope_exclude_globs=("CLAUDE.md",))
            ),
            corpus=DocCorpus(project_root=tmp_path),
        )
        assert _run_sweep(context) == []

    def test_a_doc_outside_the_exclusion_is_still_reported(self, tmp_path: Path) -> None:
        """Guard against over-fixing: the exclusion must not silence the
        check generally, only inside the configured directories."""
        (tmp_path / "CLAUDE").mkdir()
        self._write_role_doc(tmp_path)
        (tmp_path / "src" / "foo").mkdir(parents=True)
        (tmp_path / "src" / "foo" / "CLAUDE.md").write_text(_LONG_BODY)

        context = sweep_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(qa=self._EXCLUDED),
            corpus=DocCorpus(project_root=tmp_path),
        )
        findings = _run_sweep(context)
        assert [finding.path for finding in findings] == ["src/foo/CLAUDE.md"]

    def test_the_walk_does_not_descend_into_an_excluded_dir(self, tmp_path: Path) -> None:
        """Pruning, not post-filtering: the point of the hardcoded set is
        that a heavy directory is never ENTERED. A configured exclusion
        should buy the same, or a client's vendored tree is still walked on
        every session start even though its findings are discarded."""
        (tmp_path / "CLAUDE").mkdir()
        self._write_role_doc(tmp_path)

        assert _iter_module_doc_paths(tmp_path, "CLAUDE", (self._ROLES_GLOB,)) == []


class TestDeclaredVendorDirsArePruned:
    """Plan 00331: this check reads the CANONICAL set, so a declared
    ``layout.vendor_dirs`` never reached it.

    The sibling defect to the ``scope_exclude_globs`` gap above, and the same
    client tree. ``scope_exclude_globs`` gave them a workaround; declaring the
    directory as vendored is the mechanism they should have been able to use,
    and it silently did nothing.

    ``roles`` is used deliberately -- it is NOT in
    ``CORE_VENDORED_BUILD_DIR_NAMES`` and must never be added to it (the
    canonical set admits only names no consumer could be wrong to skip), so a
    test using ``vendor/`` or ``node_modules`` would pass without the fix.
    """

    _DECLARED = frozenset(CORE_VENDORED_BUILD_DIR_NAMES | {"roles"})

    def _write_role_doc(self, root: Path) -> Path:
        doc = root / "infra" / "roles" / "lts.vault-scripts" / "CLAUDE.md"
        doc.parent.mkdir(parents=True)
        doc.write_text(_LONG_BODY)
        return doc

    def test_sweep_skips_a_module_doc_under_a_declared_vendor_dir(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        self._write_role_doc(tmp_path)

        context = sweep_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(vendor_scopes=(VendorScope(vendor_dirs=self._DECLARED),)),
            corpus=DocCorpus(project_root=tmp_path),
        )
        assert _run_sweep(context) == []

    def test_edit_skips_a_module_doc_under_a_declared_vendor_dir(self, tmp_path: Path) -> None:
        doc = self._write_role_doc(tmp_path)

        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(vendor_scopes=(VendorScope(vendor_dirs=self._DECLARED),)),
            file_path=doc,
            file_content=_LONG_BODY,
            file_exists_before=False,
        )
        assert _run_edit(context) == []

    def test_the_walk_prunes_rather_than_post_filters(self, tmp_path: Path) -> None:
        """Same reason the hardcoded set prunes: a vendored tree must never
        be ENTERED, or a client pays the walk cost on every session start to
        produce findings that are then discarded."""
        (tmp_path / "CLAUDE").mkdir()
        self._write_role_doc(tmp_path)

        assert (
            _iter_module_doc_paths(
                tmp_path, "CLAUDE", vendor_scopes=(VendorScope(vendor_dirs=self._DECLARED),)
            )
            == []
        )

    def test_an_undeclared_vendor_dir_is_still_reported(self, tmp_path: Path) -> None:
        """The skip must come from the DECLARATION, not from the name --
        otherwise this passes just as well if `roles` were quietly added to
        the canonical set, which is the Non-Goal."""
        (tmp_path / "CLAUDE").mkdir()
        self._write_role_doc(tmp_path)

        context = sweep_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(),
            corpus=DocCorpus(project_root=tmp_path),
        )
        assert [finding.path for finding in _run_sweep(context)] == [
            "infra/roles/lts.vault-scripts/CLAUDE.md"
        ]

    def test_a_declaration_does_not_displace_the_canonical_set(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        vendored = tmp_path / "node_modules" / "pkg"
        vendored.mkdir(parents=True)
        (vendored / "CLAUDE.md").write_text(_LONG_BODY)

        context = sweep_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(vendor_scopes=(VendorScope(vendor_dirs=self._DECLARED),)),
            corpus=DocCorpus(project_root=tmp_path),
        )
        assert _run_sweep(context) == []


class TestVendorExceptionsSurviveThePrune:
    """Plan 00331 Phase 3: the prune is what would silently defeat this.

    This check does NOT post-filter -- it removes vendored directories from
    `os.walk` in place, so it never descends them. A first-party library
    declared inside a vendored tree is therefore unreachable unless the prune
    itself asks whether the directory could contain an exception. That is the
    exact reason git cannot re-include a file whose parent is excluded, and
    the failure is silent: the doc simply never appears.
    """

    _DECLARED = frozenset(CORE_VENDORED_BUILD_DIR_NAMES | {"roles"})
    _EXCEPTION = ("infra/roles/ours/**",)

    def _write_two_roles(self, root: Path) -> None:
        for owner in ("ours", "theirs"):
            doc = root / "infra" / "roles" / owner / "CLAUDE.md"
            doc.parent.mkdir(parents=True)
            doc.write_text(_LONG_BODY)

    def test_the_walk_reaches_a_doc_inside_a_vendored_tree(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        self._write_two_roles(tmp_path)

        assert _iter_module_doc_paths(
            tmp_path,
            "CLAUDE",
            vendor_scopes=(
                VendorScope(vendor_dirs=self._DECLARED, vendor_exceptions=self._EXCEPTION),
            ),
        ) == ["infra/roles/ours/CLAUDE.md"]

    def test_sweep_reports_the_excepted_doc_and_not_its_neighbour(self, tmp_path: Path) -> None:
        """Descending is not including: the sibling reached by the same walk
        must still be treated as vendored."""
        (tmp_path / "CLAUDE").mkdir()
        self._write_two_roles(tmp_path)

        context = sweep_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(
                vendor_scopes=(
                    VendorScope(vendor_dirs=self._DECLARED, vendor_exceptions=self._EXCEPTION),
                )
            ),
            corpus=DocCorpus(project_root=tmp_path),
        )
        assert [finding.path for finding in _run_sweep(context)] == ["infra/roles/ours/CLAUDE.md"]

    def test_edit_judges_the_excepted_doc(self, tmp_path: Path) -> None:
        """The author editing their own library must get the normal feedback,
        not silence -- silence here is the bug, not the feature."""
        doc = tmp_path / "infra" / "roles" / "ours" / "CLAUDE.md"
        doc.parent.mkdir(parents=True)
        doc.write_text(_LONG_BODY)

        context = edit_context(
            project_root=tmp_path,
            policy=DocumentationPolicy(
                vendor_scopes=(
                    VendorScope(vendor_dirs=self._DECLARED, vendor_exceptions=self._EXCEPTION),
                )
            ),
            file_path=doc,
            file_content=_LONG_BODY,
            file_exists_before=False,
        )
        assert _run_edit(context) != []

    def test_no_exception_still_prunes_the_whole_tree(self, tmp_path: Path) -> None:
        """Zero-config must not make the walker descend every vendored tree."""
        (tmp_path / "CLAUDE").mkdir()
        self._write_two_roles(tmp_path)

        assert (
            _iter_module_doc_paths(
                tmp_path, "CLAUDE", vendor_scopes=(VendorScope(vendor_dirs=self._DECLARED),)
            )
            == []
        )


class TestMissingFilePathOrContent:
    def test_missing_file_path_or_content_produces_no_findings(self, tmp_path: Path) -> None:
        context_no_path = CheckContext(
            project_root=tmp_path, policy=DocumentationPolicy(), file_content="x"
        )
        context_no_content = CheckContext(
            project_root=tmp_path, policy=DocumentationPolicy(), file_path=tmp_path / "X.md"
        )
        assert _run_edit(context_no_path) == []
        assert _run_edit(context_no_content) == []
