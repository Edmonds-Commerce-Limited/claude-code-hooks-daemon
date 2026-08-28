"""Tests for ``docs_qa.corpus`` (Plan 00284, Task 3.1a)."""

import json
from pathlib import Path

from claude_code_hooks_daemon.docs_qa.corpus import (
    DocCorpus,
    DocRecord,
    QuoteRef,
    build_and_save_corpus,
    extract_link_targets,
    is_in_scope,
    is_module_doc_path,
    iter_corpus_paths,
    load_cached_corpus,
    load_or_cold_corpus,
)
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy, DocumentationTreesPolicy


def _scaffold(root: Path) -> None:
    (root / "CLAUDE").mkdir(parents=True)
    (root / "CLAUDE" / "Foo.md").write_text("# Foo\n\n[link](Bar.md)\n")
    (root / "CLAUDE" / "Plan").mkdir()
    (root / "CLAUDE" / "Plan" / "Completed").mkdir()
    (root / "CLAUDE" / "Plan" / "Completed" / "OLD.md").write_text("# old\n")
    (root / "CLAUDE" / "Plan" / "Cancelled").mkdir()
    (root / "CLAUDE" / "Plan" / "Cancelled" / "GONE.md").write_text("# gone\n")
    (root / "docs").mkdir()
    (root / "docs" / "Guide.md").write_text("# Guide\n")
    (root / ".claude" / "rules").mkdir(parents=True)
    (root / ".claude" / "rules" / "one.md").write_text("---\npaths: ['*']\n---\nrule\n")
    (root / ".claude" / "skills").mkdir(parents=True)
    (root / ".claude" / "skills" / "SKILL.md").write_text("skill\n")
    (root / ".claude" / "agents").mkdir(parents=True)
    (root / ".claude" / "agents" / "agent.md").write_text("agent\n")
    (root / "README.md").write_text("# root readme\n")
    (root / "CHANGELOG.md").write_text("# changelog\n")
    (root / "RELEASES").mkdir()
    (root / "RELEASES" / "v1.md").write_text("# v1\n")
    (root / "src").mkdir()  # not a .md scope dir
    (root / "src" / "notes.md").write_text("# not in scope\n")


class TestExtractLinkTargets:
    def test_extracts_plain_markdown_links(self) -> None:
        text = "See [the guide](docs/Guide.md) and [other](../CLAUDE/Foo.md)."
        assert extract_link_targets(text) == ["docs/Guide.md", "../CLAUDE/Foo.md"]

    def test_skips_links_inside_fenced_code_blocks(self) -> None:
        text = "prose\n```\n[fenced](nope.md)\n```\nreal [ok](Bar.md)\n"
        assert extract_link_targets(text) == ["Bar.md"]

    def test_ignores_backticked_prose_paths(self) -> None:
        text = "See `src/foo.py` for details, not a link."
        assert extract_link_targets(text) == []

    def test_no_links_returns_empty_list(self) -> None:
        assert extract_link_targets("just prose, no links here") == []


class TestIsInScope:
    def test_agent_tree_md_is_in_scope(self, tmp_path: Path) -> None:
        _scaffold(tmp_path)
        assert is_in_scope(tmp_path / "CLAUDE" / "Foo.md", tmp_path, DocumentationPolicy())

    def test_human_tree_md_is_in_scope(self, tmp_path: Path) -> None:
        _scaffold(tmp_path)
        assert is_in_scope(tmp_path / "docs" / "Guide.md", tmp_path, DocumentationPolicy())

    def test_root_level_md_is_in_scope(self, tmp_path: Path) -> None:
        _scaffold(tmp_path)
        assert is_in_scope(tmp_path / "README.md", tmp_path, DocumentationPolicy())

    def test_rules_skills_agents_are_in_scope(self, tmp_path: Path) -> None:
        _scaffold(tmp_path)
        policy = DocumentationPolicy()
        assert is_in_scope(tmp_path / ".claude" / "rules" / "one.md", tmp_path, policy)
        assert is_in_scope(tmp_path / ".claude" / "skills" / "SKILL.md", tmp_path, policy)
        assert is_in_scope(tmp_path / ".claude" / "agents" / "agent.md", tmp_path, policy)

    def test_changelog_is_excluded(self, tmp_path: Path) -> None:
        _scaffold(tmp_path)
        assert not is_in_scope(tmp_path / "CHANGELOG.md", tmp_path, DocumentationPolicy())

    def test_releases_dir_is_excluded(self, tmp_path: Path) -> None:
        _scaffold(tmp_path)
        assert not is_in_scope(tmp_path / "RELEASES" / "v1.md", tmp_path, DocumentationPolicy())

    def test_plan_archive_dirs_are_excluded(self, tmp_path: Path) -> None:
        _scaffold(tmp_path)
        policy = DocumentationPolicy()
        assert not is_in_scope(
            tmp_path / "CLAUDE" / "Plan" / "Completed" / "OLD.md", tmp_path, policy
        )
        assert not is_in_scope(
            tmp_path / "CLAUDE" / "Plan" / "Cancelled" / "GONE.md", tmp_path, policy
        )

    def test_unscoped_directory_is_excluded(self, tmp_path: Path) -> None:
        _scaffold(tmp_path)
        assert not is_in_scope(tmp_path / "src" / "notes.md", tmp_path, DocumentationPolicy())

    def test_non_markdown_file_is_excluded(self, tmp_path: Path) -> None:
        _scaffold(tmp_path)
        (tmp_path / "CLAUDE" / "notes.txt").write_text("x")
        assert not is_in_scope(tmp_path / "CLAUDE" / "notes.txt", tmp_path, DocumentationPolicy())

    def test_module_doc_outside_every_tracked_tree_is_still_module_scoped(
        self, tmp_path: Path
    ) -> None:
        """The live scope gap this test guards: ``src/CLAUDE.md`` is not
        agent tree, human tree, or a satellite dir, so ``is_in_scope`` is
        (correctly) False for it -- but ``is_module_doc_path`` must be True,
        since module-doc-budget exists specifically to police files exactly
        like this one."""
        assert not is_in_scope(tmp_path / "src" / "CLAUDE.md", tmp_path, DocumentationPolicy())
        assert is_module_doc_path("src/CLAUDE.md", "CLAUDE")

    def test_respects_configured_tree_names(self, tmp_path: Path) -> None:
        (tmp_path / "AgentDocs").mkdir()
        (tmp_path / "AgentDocs" / "X.md").write_text("x")
        policy = DocumentationPolicy(
            trees=DocumentationTreesPolicy(agent="AgentDocs", human="HumanDocs")
        )
        assert is_in_scope(tmp_path / "AgentDocs" / "X.md", tmp_path, policy)


class TestIsModuleDocPath:
    def test_repo_root_claude_md_is_not_module_scoped(self) -> None:
        assert not is_module_doc_path("CLAUDE.md", "CLAUDE")

    def test_agent_tree_root_claude_md_is_not_module_scoped(self) -> None:
        assert not is_module_doc_path("CLAUDE/CLAUDE.md", "CLAUDE")

    def test_non_claude_md_filename_is_not_module_scoped(self) -> None:
        assert not is_module_doc_path("src/Other.md", "CLAUDE")

    def test_nested_claude_md_anywhere_is_module_scoped(self) -> None:
        assert is_module_doc_path("src/foo/CLAUDE.md", "CLAUDE")
        assert is_module_doc_path(".claude/ccy/CLAUDE.md", "CLAUDE")
        assert is_module_doc_path("CLAUDE/strategies/tdd/CLAUDE.md", "CLAUDE")

    def test_path_equal_to_project_root_is_excluded(self, tmp_path: Path) -> None:
        # An edge case where the "path" resolves to empty relative parts —
        # only reachable when project_root itself carries a .md suffix.
        weird_root = tmp_path / "weird.md"
        weird_root.mkdir()
        assert not is_in_scope(weird_root, weird_root, DocumentationPolicy())

    def test_path_outside_project_root_is_excluded(self, tmp_path: Path) -> None:
        other_root = tmp_path / "elsewhere"
        outside_file = other_root / "CLAUDE" / "Foo.md"
        outside_file.parent.mkdir(parents=True)
        outside_file.write_text("x")
        project_root = tmp_path / "project"
        project_root.mkdir()
        assert not is_in_scope(outside_file, project_root, DocumentationPolicy())


class TestIterCorpusPaths:
    def test_finds_every_in_scope_file_and_none_excluded(self, tmp_path: Path) -> None:
        _scaffold(tmp_path)
        paths = iter_corpus_paths(tmp_path, DocumentationPolicy())
        rel = {str(p.relative_to(tmp_path)) for p in paths}
        assert "CLAUDE/Foo.md" in rel
        assert "docs/Guide.md" in rel
        assert "README.md" in rel
        assert ".claude/rules/one.md" in rel
        assert ".claude/skills/SKILL.md" in rel
        assert ".claude/agents/agent.md" in rel
        assert "CHANGELOG.md" not in rel
        assert "RELEASES/v1.md" not in rel
        assert "CLAUDE/Plan/Completed/OLD.md" not in rel
        assert "CLAUDE/Plan/Cancelled/GONE.md" not in rel
        assert "src/notes.md" not in rel

    def test_skips_a_directory_that_merely_matches_the_md_glob(self, tmp_path: Path) -> None:
        (tmp_path / "weird.md").mkdir()  # a directory, not a file
        paths = iter_corpus_paths(tmp_path, DocumentationPolicy())
        assert tmp_path / "weird.md" not in paths

    def test_missing_configured_trees_are_skipped_without_error(self, tmp_path: Path) -> None:
        # Neither tmp_path/CLAUDE nor tmp_path/docs exists.
        assert iter_corpus_paths(tmp_path, DocumentationPolicy()) == []

    def test_missing_satellite_dirs_are_skipped_without_error(self, tmp_path: Path) -> None:
        (tmp_path / "CLAUDE").mkdir()
        (tmp_path / "CLAUDE" / "Foo.md").write_text("# foo\n")
        # No .claude/ directory at all.
        paths = iter_corpus_paths(tmp_path, DocumentationPolicy())
        assert paths == [tmp_path / "CLAUDE" / "Foo.md"]


class TestBuildAndSaveCorpus:
    def test_builds_records_for_every_in_scope_file(self, tmp_path: Path) -> None:
        _scaffold(tmp_path)
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        corpus = build_and_save_corpus(tmp_path, DocumentationPolicy(), index_path)
        assert corpus.cold is False
        assert "CLAUDE/Foo.md" in corpus.documents
        record = corpus.documents["CLAUDE/Foo.md"]
        assert record.links == ("Bar.md",)

    def test_writes_index_atomically_and_it_is_reloadable(self, tmp_path: Path) -> None:
        _scaffold(tmp_path)
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        build_and_save_corpus(tmp_path, DocumentationPolicy(), index_path)
        assert index_path.is_file()
        assert not index_path.with_suffix(".json.tmp").exists()
        payload = json.loads(index_path.read_text())
        assert "documents" in payload

        reloaded = load_cached_corpus(tmp_path, index_path)
        assert reloaded is not None
        assert set(reloaded.documents.keys()) == {
            "CLAUDE/Foo.md",
            "docs/Guide.md",
            "README.md",
            ".claude/rules/one.md",
            ".claude/skills/SKILL.md",
            ".claude/agents/agent.md",
        }

    def test_reuses_unchanged_entries_by_mtime_and_size(self, tmp_path: Path) -> None:
        _scaffold(tmp_path)
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        first = build_and_save_corpus(tmp_path, DocumentationPolicy(), index_path)
        second = build_and_save_corpus(tmp_path, DocumentationPolicy(), index_path)
        assert first.documents["CLAUDE/Foo.md"] == second.documents["CLAUDE/Foo.md"]

    def test_picks_up_content_changes_via_mtime_and_size(self, tmp_path: Path) -> None:
        _scaffold(tmp_path)
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        build_and_save_corpus(tmp_path, DocumentationPolicy(), index_path)
        (tmp_path / "CLAUDE" / "Foo.md").write_text("# Foo\n\n[new](Baz.md)\n\nextra padding\n")
        second = build_and_save_corpus(tmp_path, DocumentationPolicy(), index_path)
        assert second.documents["CLAUDE/Foo.md"].links == ("Baz.md",)

    def test_handles_non_utf8_file_without_crashing(self, tmp_path: Path) -> None:
        _scaffold(tmp_path)
        (tmp_path / "CLAUDE" / "Binaryish.md").write_bytes(b"\xff\xfe\x00\x01not valid utf8")
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        corpus = build_and_save_corpus(tmp_path, DocumentationPolicy(), index_path)
        assert corpus.documents["CLAUDE/Binaryish.md"].links == ()

    def test_drops_removed_files_from_the_index(self, tmp_path: Path) -> None:
        _scaffold(tmp_path)
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        build_and_save_corpus(tmp_path, DocumentationPolicy(), index_path)
        (tmp_path / "docs" / "Guide.md").unlink()
        second = build_and_save_corpus(tmp_path, DocumentationPolicy(), index_path)
        assert "docs/Guide.md" not in second.documents


class TestLoadCachedCorpus:
    def test_missing_index_returns_none(self, tmp_path: Path) -> None:
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        assert load_cached_corpus(tmp_path, index_path) is None

    def test_corrupt_index_returns_none(self, tmp_path: Path) -> None:
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        index_path.parent.mkdir(parents=True)
        index_path.write_text("not json{{{")
        assert load_cached_corpus(tmp_path, index_path) is None

    def test_documents_not_a_dict_returns_none(self, tmp_path: Path) -> None:
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        index_path.parent.mkdir(parents=True)
        index_path.write_text(json.dumps({"documents": "not-a-dict"}))
        assert load_cached_corpus(tmp_path, index_path) is None

    def test_malformed_entry_returns_none(self, tmp_path: Path) -> None:
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        index_path.parent.mkdir(parents=True)
        index_path.write_text(json.dumps({"documents": {"a.md": {"mtime_ns": 1}}}))
        assert load_cached_corpus(tmp_path, index_path) is None


class TestLoadOrColdCorpus:
    def test_missing_index_is_cold_and_empty(self, tmp_path: Path) -> None:
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        corpus = load_or_cold_corpus(tmp_path, index_path)
        assert corpus.cold is True
        assert corpus.documents == {}

    def test_valid_index_is_not_cold(self, tmp_path: Path) -> None:
        _scaffold(tmp_path)
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        build_and_save_corpus(tmp_path, DocumentationPolicy(), index_path)
        corpus = load_or_cold_corpus(tmp_path, index_path)
        assert corpus.cold is False
        assert "CLAUDE/Foo.md" in corpus.documents


class TestDocCorpusHelpers:
    def test_document_paths_are_sorted(self, tmp_path: Path) -> None:
        corpus = DocCorpus(
            project_root=tmp_path,
            documents={
                "b.md": DocRecord(rel_path="b.md", mtime_ns=1, size=1, links=()),
                "a.md": DocRecord(rel_path="a.md", mtime_ns=1, size=1, links=()),
            },
        )
        assert corpus.document_paths() == ("a.md", "b.md")


class TestQuoteExtractionAndReverseIndex:
    def test_build_extracts_quote_refs(self, tmp_path: Path) -> None:
        _scaffold(tmp_path)
        (tmp_path / "CLAUDE" / "Foo.md").write_text(
            "# Foo\n\n<!-- ssot-quote: CLAUDE/Bar.md#anchor -->\n"
            + ("word " * 20)
            + "\n<!-- /ssot-quote -->\n"
        )
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        corpus = build_and_save_corpus(tmp_path, DocumentationPolicy(), index_path)
        record = corpus.documents["CLAUDE/Foo.md"]
        assert record.quotes == (QuoteRef(source_path="CLAUDE/Bar.md", anchor="anchor"),)

    def test_quote_refs_round_trip_through_the_cache(self, tmp_path: Path) -> None:
        _scaffold(tmp_path)
        (tmp_path / "CLAUDE" / "Foo.md").write_text(
            "# Foo\n\n<!-- ssot-quote: CLAUDE/Bar.md#anchor -->\nbody\n<!-- /ssot-quote -->\n"
        )
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        build_and_save_corpus(tmp_path, DocumentationPolicy(), index_path)
        reloaded = load_cached_corpus(tmp_path, index_path)
        assert reloaded is not None
        assert reloaded.documents["CLAUDE/Foo.md"].quotes == (
            QuoteRef(source_path="CLAUDE/Bar.md", anchor="anchor"),
        )

    def test_no_quote_blocks_yields_empty_tuple(self, tmp_path: Path) -> None:
        _scaffold(tmp_path)
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        corpus = build_and_save_corpus(tmp_path, DocumentationPolicy(), index_path)
        assert corpus.documents["CLAUDE/Foo.md"].quotes == ()

    def test_legacy_cache_without_quotes_key_defaults_to_empty(self, tmp_path: Path) -> None:
        index_path = tmp_path / "untracked" / "docs-qa" / "index.json"
        index_path.parent.mkdir(parents=True)
        index_path.write_text(
            json.dumps({"documents": {"a.md": {"mtime_ns": 1, "size": 1, "links": []}}})
        )
        corpus = load_cached_corpus(tmp_path, index_path)
        assert corpus is not None
        assert corpus.documents["a.md"].quotes == ()

    def test_reverse_quote_index_finds_quoters(self, tmp_path: Path) -> None:
        corpus = DocCorpus(
            project_root=tmp_path,
            documents={
                "A.md": DocRecord(
                    rel_path="A.md",
                    mtime_ns=1,
                    size=1,
                    links=(),
                    quotes=(QuoteRef(source_path="Source.md", anchor="x"),),
                ),
                "B.md": DocRecord(
                    rel_path="B.md",
                    mtime_ns=1,
                    size=1,
                    links=(),
                    quotes=(QuoteRef(source_path="Source.md", anchor="x"),),
                ),
                "C.md": DocRecord(
                    rel_path="C.md",
                    mtime_ns=1,
                    size=1,
                    links=(),
                    quotes=(QuoteRef(source_path="Other.md", anchor="y"),),
                ),
            },
        )
        quoters = corpus.quoters_of("Source.md", "x")
        assert quoters == ("A.md", "B.md")

    def test_reverse_quote_index_empty_when_no_quoters(self, tmp_path: Path) -> None:
        corpus = DocCorpus(project_root=tmp_path, documents={})
        assert corpus.quoters_of("Source.md", "x") == ()
