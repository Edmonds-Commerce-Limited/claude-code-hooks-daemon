"""Tests for the instruction-file footprint measurement (Plan 00532 Phase 3)."""

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.docs_qa.footprint import (
    CLAUDE_MD_LINE_TARGET,
    FILE_SKIP_BYTES,
    ON_DEMAND_CHAR_LIMIT,
    Footprint,
    FootprintEntry,
    format_footprint,
    measure_footprint,
)
from claude_code_hooks_daemon.docs_qa.instructions_contract import (
    InstructionsContract,
    default_contract_dir,
    load_contract,
)
from claude_code_hooks_daemon.utils.vendor_paths import VendorScope


@pytest.fixture(scope="module")
def contract() -> InstructionsContract:
    return load_contract(default_contract_dir())


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _measure(
    root: Path, contract: InstructionsContract, installed: str | None = "2.1.302"
) -> Footprint:
    home = root.parent / "home"
    home.mkdir(exist_ok=True)
    return measure_footprint(
        project_root=root,
        contract=contract,
        installed_version=installed,
        home_dir=home,
        documentation_enabled=False,
    )


def _entry(footprint: Footprint, path: str) -> FootprintEntry:
    matches = [entry for entry in footprint.entries if entry.path == path]
    assert len(matches) == 1, f"{path} not exactly once in {[e.path for e in footprint.entries]}"
    return matches[0]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    return project


class TestConstantsMatchContract:
    def test_line_target_is_the_pinned_fact(self, contract: InstructionsContract) -> None:
        statement = next(f.statement for f in contract.facts if f.id == "G4-01")
        assert str(CLAUDE_MD_LINE_TARGET) in statement

    def test_skip_threshold_is_the_pinned_fact(self, contract: InstructionsContract) -> None:
        statement = next(f.statement for f in contract.facts if f.id == "G4-03")
        assert "4 MiB" in statement
        assert "at launch" in statement
        assert FILE_SKIP_BYTES == 4 * 1024 * 1024

    def test_on_demand_limit_is_the_pinned_fact(self, contract: InstructionsContract) -> None:
        fact = next(f for f in contract.facts if f.id == "G4-05")
        assert "40,000 characters" in fact.statement
        assert "only its start" in fact.statement
        assert fact.min_claude_code_version == "2.1.309"
        assert ON_DEMAND_CHAR_LIMIT == 40_000


class TestSessionStartSet:
    def test_root_claude_md_loads_at_launch(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / "CLAUDE.md", "one\ntwo\nthree\n")
        entry = _entry(_measure(root, contract), "CLAUDE.md")
        assert (entry.loads, entry.lines, entry.proposable) == ("launch", 3, True)
        assert entry.size_bytes == len("one\ntwo\nthree\n")

    def test_dot_claude_claude_md_loads_at_launch(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / ".claude" / "CLAUDE.md", "x\n")
        assert _entry(_measure(root, contract), ".claude/CLAUDE.md").loads == "launch"

    def test_unscoped_rule_found_recursively_loads_at_launch(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / ".claude" / "rules" / "deep" / "er" / "style.md", "always\n")
        entry = _entry(_measure(root, contract), ".claude/rules/deep/er/style.md")
        assert (entry.loads, entry.role, entry.proposable) == ("launch", "rule", True)

    def test_rule_with_paths_is_on_demand(self, root: Path, contract: InstructionsContract) -> None:
        _write(root / ".claude" / "rules" / "api.md", '---\npaths:\n  - "src/api/**"\n---\nbody\n')
        assert _entry(_measure(root, contract), ".claude/rules/api.md").loads == "on-demand"

    def test_rule_with_only_description_frontmatter_is_unconditional(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / ".claude" / "rules" / "d.md", "---\ndescription: hi\n---\nbody\n")
        assert _entry(_measure(root, contract), ".claude/rules/d.md").loads == "launch"

    def test_rule_with_unparseable_frontmatter_is_unconditional(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / ".claude" / "rules" / "bad.md", "---\npaths: [unclosed\n---\nbody\n")
        assert _entry(_measure(root, contract), ".claude/rules/bad.md").loads == "launch"

    def test_nested_claude_md_is_on_demand(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / "pkg" / "sub" / "CLAUDE.md", "nested\n")
        entry = _entry(_measure(root, contract), "pkg/sub/CLAUDE.md")
        assert (entry.loads, entry.role) == ("on-demand", "nested-claude-md")

    def test_hidden_and_vendor_directories_are_not_walked(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / "node_modules" / "x" / "CLAUDE.md", "n\n")
        _write(root / ".git" / "CLAUDE.md", "g\n")
        _write(root / "untracked" / "wt" / "CLAUDE.md", "u\n")
        assert _measure(root, contract).entries == ()

    def test_ancestor_claude_md_loads_and_is_not_proposable(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root.parent / "CLAUDE.md", "above\n")
        entry = _entry(_measure(root, contract), str(root.parent / "CLAUDE.md"))
        assert (entry.loads, entry.role, entry.proposable) == ("launch", "ancestor", False)


class TestImports:
    def test_import_loads_at_launch_and_is_proposable(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / "CLAUDE.md", "see @docs/a.md\n")
        _write(root / "docs" / "a.md", "a\nb\n")
        entry = _entry(_measure(root, contract), "docs/a.md")
        assert (entry.loads, entry.role, entry.lines, entry.proposable) == (
            "launch",
            "import",
            2,
            True,
        )

    def test_nested_claude_md_import_loads_on_demand_with_it(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        # G2-01: an import loads alongside the CLAUDE.md that references it.
        _write(root / "pkg" / "CLAUDE.md", "@notes.md\n")
        _write(root / "pkg" / "notes.md", "@deeper.md\n")
        _write(root / "pkg" / "deeper.md", "d\n")
        footprint = _measure(root, contract)
        for path in ("pkg/notes.md", "pkg/deeper.md"):
            entry = _entry(footprint, path)
            assert (entry.loads, entry.role) == ("on-demand", "import")
        assert footprint.totals.on_demand_files == 3
        assert footprint.totals.launch_files == 0

    def test_file_imported_at_launch_and_by_nested_file_counts_at_launch(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / "CLAUDE.md", "@shared.md\n")
        _write(root / "pkg" / "CLAUDE.md", "@../shared.md\n")
        _write(root / "shared.md", "s\n")
        assert _entry(_measure(root, contract), "shared.md").loads == "launch"

    def test_relative_import_resolves_against_importing_file(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / "CLAUDE.md", "@docs/a.md\n")
        _write(root / "docs" / "a.md", "@b.md\n")
        _write(root / "docs" / "b.md", "b\n")
        assert _entry(_measure(root, contract), "docs/b.md").loads == "launch"

    def test_imports_stop_after_four_hops(self, root: Path, contract: InstructionsContract) -> None:
        _write(root / "CLAUDE.md", "@h1.md\n")
        for hop in range(1, 6):
            _write(root / f"h{hop}.md", f"@h{hop + 1}.md\n")
        _write(root / "h6.md", "end\n")
        paths = {entry.path for entry in _measure(root, contract).entries}
        assert {"h1.md", "h2.md", "h3.md", "h4.md"} <= paths
        assert "h5.md" not in paths

    def test_import_cycle_terminates_and_counts_once(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / "CLAUDE.md", "@a.md\n")
        _write(root / "a.md", "@CLAUDE.md\n@a.md\n")
        paths = [entry.path for entry in _measure(root, contract).entries]
        assert sorted(paths) == ["CLAUDE.md", "a.md"]

    def test_code_span_and_fence_are_not_imports(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / "CLAUDE.md", "`@a.md`\n```\n@b.md\n```\n")
        _write(root / "a.md", "a\n")
        _write(root / "b.md", "b\n")
        assert [e.path for e in _measure(root, contract).entries] == ["CLAUDE.md"]

    def test_missing_import_target_is_ignored(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / "CLAUDE.md", "ping @someone and mail me@example.com\n")
        assert [e.path for e in _measure(root, contract).entries] == ["CLAUDE.md"]

    def test_import_of_daemon_deployed_artefact_is_counted_not_proposable(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / "CLAUDE.md", "@.claude/HOOKS-DAEMON.md\n")
        _write(root / ".claude" / "HOOKS-DAEMON.md", "generated\n")
        entry = _entry(_measure(root, contract), ".claude/HOOKS-DAEMON.md")
        assert entry.loads == "launch"
        assert entry.proposable is False
        assert "daemon" in entry.not_proposable_reason


class TestCountedNeverProposed:
    def test_claude_local_md_is_counted_not_proposable(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / "CLAUDE.local.md", "mine\n")
        entry = _entry(_measure(root, contract), "CLAUDE.local.md")
        assert (entry.loads, entry.proposable) == ("launch", False)
        assert entry.not_proposable_reason

    def test_user_scope_files_are_counted_not_proposable(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        home = root.parent / "home"
        _write(home / ".claude" / "CLAUDE.md", "user\n")
        _write(home / ".claude" / "rules" / "r.md", "rule\n")
        footprint = _measure(root, contract)
        by_role = {e.role: e for e in footprint.entries}
        assert by_role["user-claude-md"].proposable is False
        assert by_role["user-rule"].proposable is False
        assert by_role["user-claude-md"].loads == "launch"

    def test_daemon_block_lines_counted_and_excluded_from_proposable(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        block = "<hooksdaemon>\nline\nline\n</hooksdaemon>\n"
        _write(root / "CLAUDE.md", "intro\n" + block + "outro\n")
        footprint = _measure(root, contract)
        entry = _entry(footprint, "CLAUDE.md")
        assert entry.daemon_block_lines == 4
        assert entry.lines == 6
        assert footprint.totals.launch_lines == 6
        assert footprint.totals.launch_daemon_block_lines == 4
        assert footprint.totals.launch_proposable_lines == 2

    def test_tag_mentioned_in_prose_or_a_fence_is_not_the_daemon_block(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        # Only whole-line tags outside a code fence delimit the injected block.
        _write(
            root / "CLAUDE.md",
            "See the `<hooksdaemon>` block below.\n"
            "mine\n"
            "```text\n"
            "<hooksdaemon>\n"
            "```\n"
            "<hooksdaemon>\n"
            "x\n"
            "</hooksdaemon>\n",
        )
        footprint = _measure(root, contract)
        assert _entry(footprint, "CLAUDE.md").daemon_block_lines == 3
        assert footprint.totals.launch_daemon_block_lines == 3
        assert footprint.totals.launch_proposable_lines == 5

    def test_inline_tag_pair_in_prose_is_no_daemon_block(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / "CLAUDE.md", "The `<hooksdaemon>` and `</hooksdaemon>` tags.\nmine\n")
        assert _entry(_measure(root, contract), "CLAUDE.md").daemon_block_lines == 0


class TestSizeGuidance:
    def test_claude_md_over_target_is_flagged(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / "CLAUDE.md", "x\n" * (CLAUDE_MD_LINE_TARGET + 1))
        _write(root / "pkg" / "CLAUDE.md", "x\n" * CLAUDE_MD_LINE_TARGET)
        footprint = _measure(root, contract)
        assert _entry(footprint, "CLAUDE.md").over_line_target is True
        assert _entry(footprint, "pkg/CLAUDE.md").over_line_target is False

    def test_file_over_skip_threshold_is_skipped_and_not_totalled(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        big = root / "CLAUDE.md"
        big.write_bytes(b"a" * (FILE_SKIP_BYTES + 1))
        footprint = _measure(root, contract)
        entry = _entry(footprint, "CLAUDE.md")
        assert entry.skipped is True
        assert footprint.totals.launch_bytes == 0

    def test_launch_file_over_skip_threshold_is_reported_as_skipped(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        (root / "CLAUDE.md").write_bytes(b"a" * (FILE_SKIP_BYTES + 1))
        assert "skipped by Claude Code" in format_footprint(_measure(root, contract))

    def test_nested_claude_md_over_on_demand_limit_loads_its_start(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        # G4-05: an on-demand file over the per-file limit is truncated, not skipped.
        _write(root / "pkg" / "CLAUDE.md", "x" * (ON_DEMAND_CHAR_LIMIT + 1))
        footprint = _measure(root, contract)
        entry = _entry(footprint, "pkg/CLAUDE.md")
        assert (entry.skipped, entry.truncated) == (False, True)
        assert footprint.totals.on_demand_files == 1
        text = format_footprint(footprint)
        assert "loads only its start" in text
        assert "skipped" not in text

    def test_nested_claude_md_over_skip_threshold_is_not_skipped(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        (root / "pkg").mkdir()
        (root / "pkg" / "CLAUDE.md").write_bytes(b"a" * (FILE_SKIP_BYTES + 1))
        footprint = _measure(root, contract)
        entry = _entry(footprint, "pkg/CLAUDE.md")
        assert (entry.skipped, entry.truncated) == (False, True)
        text = format_footprint(footprint)
        assert "its lines were not counted" in text
        assert "skipped" not in text

    def test_scoped_rule_over_on_demand_limit_is_truncated(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        body = "x" * ON_DEMAND_CHAR_LIMIT
        _write(root / ".claude" / "rules" / "api.md", f'---\npaths:\n  - "src/**"\n---\n{body}\n')
        assert _entry(_measure(root, contract), ".claude/rules/api.md").truncated is True

    def test_launch_file_over_on_demand_limit_is_not_truncated(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / "CLAUDE.md", "x" * (ON_DEMAND_CHAR_LIMIT + 1))
        assert _entry(_measure(root, contract), "CLAUDE.md").truncated is False

    def test_nested_claude_md_at_on_demand_limit_is_whole(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / "pkg" / "CLAUDE.md", "x" * ON_DEMAND_CHAR_LIMIT)
        assert _entry(_measure(root, contract), "pkg/CLAUDE.md").truncated is False

    def test_totals_split_launch_and_on_demand(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / "CLAUDE.md", "a\nb\n")
        _write(root / "pkg" / "CLAUDE.md", "c\n")
        totals = _measure(root, contract).totals
        assert (totals.launch_lines, totals.on_demand_lines) == (2, 1)
        assert (totals.launch_files, totals.on_demand_files) == (1, 1)


class TestContractFields:
    def test_versions_and_unmodelled_come_from_the_contract(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        footprint = _measure(root, contract, installed="2.1.400")
        assert footprint.audited_version == contract.meta.last_audited_claude_code_version
        assert footprint.installed_version == "2.1.400"
        assert footprint.unmodelled == tuple(item.id for item in contract.unmodelled)

    def test_unknown_installed_version_is_none(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        assert _measure(root, contract, installed=None).installed_version is None


class TestReport:
    def test_to_dict_is_json_serialisable_and_complete(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / "CLAUDE.md", "a\n")
        payload = json.loads(json.dumps(_measure(root, contract).to_dict()))
        assert set(payload) >= {
            "audited_version",
            "installed_version",
            "documentation_enabled",
            "unmodelled",
            "totals",
            "entries",
        }
        assert payload["entries"][0]["path"] == "CLAUDE.md"

    def test_text_report_names_versions_unmodelled_and_totals(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / "CLAUDE.md", "a\n")
        text = format_footprint(_measure(root, contract, installed="2.1.400"))
        assert "2.1.400" in text
        assert contract.meta.last_audited_claude_code_version in text
        assert "claudeMdExcludes" in text
        assert "CLAUDE.md" in text
        assert "session start" in text.lower()

    def test_text_report_warns_when_installed_is_newer_than_audited(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        text = format_footprint(_measure(root, contract, installed="9.9.9"))
        assert "newer" in text

    def test_text_report_says_when_installed_version_unknown(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        assert "unknown" in format_footprint(_measure(root, contract, installed=None))


def _measure_with(root: Path, contract: InstructionsContract, **options: Any) -> Footprint:
    home = root.parent / "home"
    home.mkdir(exist_ok=True)
    return measure_footprint(
        project_root=root,
        contract=contract,
        installed_version=None,
        home_dir=home,
        documentation_enabled=False,
        **options,
    )


class TestDaemonDeployedMarkers:
    """Files carrying a daemon ownership marker are counted, never proposed (Plan 00532 3.2)."""

    @pytest.mark.parametrize(
        "marker",
        [
            "<!-- hooks-daemon-rule-version: 1.0.0 -->",
            "<!-- hooks-daemon-agent-version: 1.1.0 -->",
            "# DAEMON-OWNED FILE - do not edit. Deployed by the installer.",
        ],
    )
    def test_marked_rules_file_is_counted_not_proposable(
        self, root: Path, contract: InstructionsContract, marker: str
    ) -> None:
        _write(
            root / ".claude" / "rules" / "source-dirs.md",
            f"---\ndescription: x\n---\n\n{marker}\n\nbody\n",
        )
        entry = _entry(_measure(root, contract), ".claude/rules/source-dirs.md")
        assert entry.proposable is False
        assert "daemon" in entry.not_proposable_reason

    def test_marker_mentioned_in_prose_does_not_make_a_file_daemon_owned(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(
            root / ".claude" / "rules" / "mine.md", "We cite hooks-daemon-rule-version: in prose.\n"
        )
        assert _entry(_measure(root, contract), ".claude/rules/mine.md").proposable is True


class TestUnreadableEntries:
    """A path that is not a readable file is skipped, not a traceback."""

    def test_broken_symlink_in_rules_is_skipped(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        rules = root / ".claude" / "rules"
        rules.mkdir(parents=True)
        (rules / "dangling.md").symlink_to(root / "nowhere.md")
        _write(root / "CLAUDE.md", "a\n")
        assert [e.path for e in _measure(root, contract).entries] == ["CLAUDE.md"]

    def test_directory_named_like_a_rule_is_skipped(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        (root / ".claude" / "rules" / "x.md").mkdir(parents=True)
        _write(root / "CLAUDE.md", "a\n")
        assert [e.path for e in _measure(root, contract).entries] == ["CLAUDE.md"]

    def test_dangling_nested_claude_md_symlink_is_skipped(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        (root / "pkg").mkdir()
        (root / "pkg" / "CLAUDE.md").symlink_to(root / "nowhere.md")
        assert _measure(root, contract).entries == ()


class TestVendorAndExclusions:
    def test_declared_vendor_dir_is_not_walked(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / "thirdparty" / "CLAUDE.md", "v\n")
        _write(root / "app" / "CLAUDE.md", "a\n")
        scope = VendorScope(root="", vendor_dirs=frozenset({"thirdparty"}), vendor_exceptions=())
        footprint = _measure_with(root, contract, vendor_scopes=(scope,))
        assert [e.path for e in footprint.entries] == ["app/CLAUDE.md"]

    def test_default_vendor_dirs_skip_build_directories(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / "vendor" / "x" / "CLAUDE.md", "v\n")
        assert _measure(root, contract).entries == ()

    def test_exclude_paths_are_not_walked(self, root: Path, contract: InstructionsContract) -> None:
        _write(root / "gen" / "CLAUDE.md", "g\n")
        _write(root / "app" / "CLAUDE.md", "a\n")
        footprint = _measure_with(root, contract, exclude_paths=("gen/**",))
        assert [e.path for e in footprint.entries] == ["app/CLAUDE.md"]


class TestOrdering:
    def test_entries_are_launch_first_then_by_path(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / "z" / "CLAUDE.md", "z\n")
        _write(root / "a" / "CLAUDE.md", "a\n")
        _write(root / ".claude" / "rules" / "b.md", "b\n")
        _write(root / ".claude" / "rules" / "a.md", "a\n")
        _write(root / "CLAUDE.md", "root\n")
        assert [e.path for e in _measure(root, contract).entries] == [
            ".claude/rules/a.md",
            ".claude/rules/b.md",
            "CLAUDE.md",
            "a/CLAUDE.md",
            "z/CLAUDE.md",
        ]


class TestPinnedFactsModelled:
    def test_block_level_html_comments_are_not_counted(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        # G1-06: stripped before injection, so they cost no context.
        _write(root / "CLAUDE.md", "intro\n<!--\nmulti\nline\n-->\n<!-- one -->\noutro\n")
        entry = _entry(_measure(root, contract), "CLAUDE.md")
        assert entry.lines == 2
        assert entry.size_bytes == len("intro\noutro\n")

    def test_inline_comment_and_fenced_comment_are_kept(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / "CLAUDE.md", "text <!-- inline --> more\n```\n<!-- in fence -->\n```\n")
        assert _entry(_measure(root, contract), "CLAUDE.md").lines == 4

    def test_daemon_block_opening_comment_is_not_counted(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / "CLAUDE.md", "<hooksdaemon>\n<!-- generated -->\nx\n</hooksdaemon>\n")
        entry = _entry(_measure(root, contract), "CLAUDE.md")
        assert entry.lines == 3
        assert entry.daemon_block_lines == 3

    def test_skip_threshold_uses_on_disk_size(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        _write(root / "CLAUDE.md", "<!--\n" + "x" * FILE_SKIP_BYTES + "\n-->\n")
        assert _entry(_measure(root, contract), "CLAUDE.md").skipped is True

    def test_user_scope_rule_with_paths_is_on_demand(
        self, root: Path, contract: InstructionsContract
    ) -> None:
        # G3-04 and G3-09: path-scoped user rules do not load at session start.
        home = root.parent / "home"
        _write(home / ".claude" / "rules" / "scoped.md", '---\npaths:\n  - "src/**"\n---\nb\n')
        _write(home / ".claude" / "rules" / "plain.md", "b\n")
        footprint = _measure(root, contract)
        by_name = {e.path.rsplit("/", 1)[-1]: e for e in footprint.entries}
        assert by_name["scoped.md"].loads == "on-demand"
        assert by_name["scoped.md"].proposable is False
        assert by_name["plain.md"].loads == "launch"
