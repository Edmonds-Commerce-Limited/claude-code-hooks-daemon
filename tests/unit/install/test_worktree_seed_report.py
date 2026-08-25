"""Tests for the worktree seed config report (Plan 00267 Phase 5).

The report answers "is my seed config current?" for a repository as it stands
NOW — a question no version-gated migration advisory can answer, because the
daemon's shipped default here is necessarily empty.

It REPORTS; it never writes. The suggested YAML is rendered for a human (or an
agent) to place, because rewriting the config through PyYAML would strip every
comment out of a file the project owns.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from claude_code_hooks_daemon.core.worktree_seed import (
    DEFAULT_SEED_MODE,
    SEED_MODE_COPY,
    SeedEntry,
    parse_seed_config,
)
from claude_code_hooks_daemon.install.worktree_seed_report import (
    SEED_CONFIG_KEY,
    build_seed_report,
    format_report_for_llm,
    suggested_yaml_block,
)


def _init_repo(root: Path, gitignore: str) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t.t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
    (root / ".gitignore").write_text(gitignore, encoding="utf-8")
    (root / "README.md").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "init"], check=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root, ".env.local\nsettings.local.json\nnode_modules/\n")
    return root


def _config_with_seed(seed: Any) -> dict[str, Any]:
    """Build a config mapping carrying ``seed`` at the real nesting depth."""
    config: dict[str, Any] = {}
    node = config
    *branches, leaf = SEED_CONFIG_KEY.split(".")
    for part in branches:
        node[part] = {}
        node = node[part]
    node[leaf] = seed
    return config


class TestBuildSeedReport:
    def test_unconfigured_repo_with_local_files_reports_drift(self, repo: Path) -> None:
        (repo / ".env.local").write_text("SECRET=1\n", encoding="utf-8")

        report = build_seed_report(repo, {})

        assert report.seed_key_configured is False
        assert report.configured == ()
        assert report.unconfigured == (SeedEntry(path=".env.local", mode=DEFAULT_SEED_MODE),)
        assert report.missing == ()
        assert report.has_drift is True

    def test_unconfigured_repo_with_no_local_files_is_clean(self, repo: Path) -> None:
        report = build_seed_report(repo, {})

        assert report.seed_key_configured is False
        assert report.has_drift is False

    def test_fully_configured_repo_is_clean(self, repo: Path) -> None:
        (repo / ".env.local").write_text("SECRET=1\n", encoding="utf-8")
        config = _config_with_seed({"entries": [".env.local"]})

        report = build_seed_report(repo, config)

        assert report.seed_key_configured is True
        assert report.configured == (SeedEntry(path=".env.local", mode=DEFAULT_SEED_MODE),)
        assert report.has_drift is False

    def test_configured_entry_whose_source_is_gone_is_missing(self, repo: Path) -> None:
        config = _config_with_seed({"entries": [".env.local"]})

        report = build_seed_report(repo, config)

        assert report.missing == (SeedEntry(path=".env.local", mode=DEFAULT_SEED_MODE),)
        assert report.has_drift is True

    def test_per_entry_mode_survives_into_the_report(self, repo: Path) -> None:
        (repo / ".env.local").write_text("SECRET=1\n", encoding="utf-8")
        config = _config_with_seed({"entries": [{"path": ".env.local", "mode": SEED_MODE_COPY}]})

        report = build_seed_report(repo, config)

        assert report.configured == (SeedEntry(path=".env.local", mode=SEED_MODE_COPY),)

    def test_a_deliberate_mode_choice_is_not_drift(self, repo: Path) -> None:
        """The mode is the project's decision; the scanner only ever suggests
        the default. Reporting the difference would nag about a choice already
        made deliberately (DESIGN section 8)."""
        (repo / ".env.local").write_text("SECRET=1\n", encoding="utf-8")
        config = _config_with_seed({"entries": [{"path": ".env.local", "mode": SEED_MODE_COPY}]})

        assert build_seed_report(repo, config).has_drift is False

    def test_seed_key_present_but_empty_still_counts_as_configured(self, repo: Path) -> None:
        """A project that deliberately configured no entries is distinguishable
        from one that has never heard of the option — the two get different
        remediation text."""
        config = _config_with_seed({"entries": []})

        report = build_seed_report(repo, config)

        assert report.seed_key_configured is True
        assert report.configured == ()

    def test_malformed_seed_config_does_not_raise(self, repo: Path) -> None:
        """Shape errors warn and skip in the parser; the reporter inherits that
        and must not turn a mistyped config into a crashed command."""
        report = build_seed_report(repo, _config_with_seed(".env.local"))

        assert report.configured == ()
        assert report.seed_key_configured is True

    def test_non_repository_root_reports_nothing_rather_than_failing(self, tmp_path: Path) -> None:
        report = build_seed_report(tmp_path, {})

        assert report.unconfigured == ()
        assert report.has_drift is False


class TestSuggestedYamlBlock:
    def test_block_for_an_unconfigured_project_carries_the_full_nesting(self) -> None:
        block = suggested_yaml_block(
            (SeedEntry(path=".env.local", mode=DEFAULT_SEED_MODE),),
            seed_key_configured=False,
        )

        loaded = yaml.safe_load(block)
        node: Any = loaded
        for part in SEED_CONFIG_KEY.split("."):
            assert part in node, f"{part} missing from suggested block"
            node = node[part]
        assert parse_seed_config(node) == [SeedEntry(path=".env.local", mode=DEFAULT_SEED_MODE)]

    def test_block_for_a_configured_project_shows_entries_only(self) -> None:
        block = suggested_yaml_block(
            (SeedEntry(path=".env.local", mode=DEFAULT_SEED_MODE),),
            seed_key_configured=True,
        )

        loaded = yaml.safe_load(block)
        assert "handlers" not in loaded
        assert loaded["entries"] == [".env.local"]

    def test_a_non_default_mode_is_rendered_as_a_mapping_entry(self) -> None:
        block = suggested_yaml_block(
            (SeedEntry(path=".secrets", mode=SEED_MODE_COPY),),
            seed_key_configured=True,
        )

        assert yaml.safe_load(block)["entries"] == [{"path": ".secrets", "mode": SEED_MODE_COPY}]

    def test_no_entries_yields_no_block(self) -> None:
        assert suggested_yaml_block((), seed_key_configured=True) == ""


class TestFormatReportForLlm:
    def test_clean_report_says_so_and_offers_no_yaml(self, repo: Path) -> None:
        text = format_report_for_llm(build_seed_report(repo, {}))

        assert "entries" not in text
        assert "up to date" in text.lower() or "nothing" in text.lower()

    def test_missing_entry_is_named_and_its_consequence_stated(self, repo: Path) -> None:
        config = _config_with_seed({"entries": [".env.local"]})

        text = format_report_for_llm(build_seed_report(repo, config))

        assert ".env.local" in text
        # The executor fails fast on an absent source, so this is not cosmetic.
        assert "worktree" in text.lower()

    def test_unconfigured_candidate_is_named_with_a_paste_ready_block(self, repo: Path) -> None:
        (repo / ".env.local").write_text("SECRET=1\n", encoding="utf-8")

        text = format_report_for_llm(build_seed_report(repo, {}))

        assert ".env.local" in text
        assert SEED_CONFIG_KEY.split(".")[-1] in text

    def test_report_never_reads_or_echoes_file_contents(self, repo: Path) -> None:
        """Suggestions name a path; they must never surface what is inside it."""
        (repo / ".env.local").write_text("API_TOKEN=hunter2\n", encoding="utf-8")

        text = format_report_for_llm(build_seed_report(repo, {}))

        assert "hunter2" not in text
