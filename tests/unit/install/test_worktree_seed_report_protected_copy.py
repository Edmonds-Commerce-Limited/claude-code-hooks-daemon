"""``check-worktree-seed`` reports a copy that worktree creation would refuse (Plan 00613).

Task 2.1 made worktree creation refuse a ``mode: copy`` seed of a path the
secret guard protects. A report that passed such a config would tell a project
its seed list is fine right up to the moment creation aborts on it, so the
report runs the SAME check, with the SAME refusal wording, over the guard
options of the config file it was given (not the daemon's own config).

A guard config whose options cannot be read refuses every copy entry, as
creation does. Paths only: no seeded file is opened.

Protected names are assembled from pieces so this file does not itself name a
protected path to the secret guard.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core.worktree_seed import SEED_MODE_COPY, SEED_MODE_SYMLINK
from claude_code_hooks_daemon.install.config_cli import run_check_worktree_seed
from claude_code_hooks_daemon.install.worktree_seed_report import (
    SEED_CONFIG_KEY,
    build_seed_report,
    format_report_for_llm,
)

VAULT = "." + "vault" + "-pass"
_SECRET_CONTENT = "do-not-copy-me\n"


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
    _init_repo(root, f".env.local\n{VAULT}\ndeploy.key\n")
    (root / ".env.local").write_text("PLAIN=1\n", encoding="utf-8")
    (root / VAULT).write_text(_SECRET_CONTENT, encoding="utf-8")
    (root / "deploy.key").write_text(_SECRET_CONTENT, encoding="utf-8")
    return root


def _config(entries: list[Any], guard_options: Any = None) -> dict[str, Any]:
    """A config carrying ``entries`` as the seed list and, optionally, guard options."""
    config: dict[str, Any] = {}
    node = config
    *branches, leaf = SEED_CONFIG_KEY.split(".")
    for part in branches:
        node[part] = {}
        node = node[part]
    node[leaf] = {"entries": entries}
    if guard_options is not None:
        config["handlers"]["pre_tool_use"] = {"secret_file_guard": {"options": guard_options}}
    return config


_ALL = [".env.local", VAULT, "deploy.key"]


def _covering(*modes: tuple[str, str]) -> list[Any]:
    """Seed entries that cover every local file, so only refusals can be drift."""
    chosen = dict(modes)
    return [{"path": path, "mode": chosen.get(path, SEED_MODE_SYMLINK)} for path in _ALL]


class TestAProtectedCopyIsReported:
    def test_it_is_listed_and_is_drift(self, repo: Path) -> None:
        report = build_seed_report(repo, _config(_covering((VAULT, SEED_MODE_COPY))))
        assert len(report.refused_copies) == 1
        assert "seed entry #2" in report.refused_copies[0]
        assert "secret_file_guard" in report.refused_copies[0]
        assert report.has_drift

    def test_the_refusal_never_names_the_protected_path(self, repo: Path) -> None:
        report = build_seed_report(repo, _config(_covering((VAULT, SEED_MODE_COPY))))
        assert VAULT not in report.refused_copies[0]
        text = format_report_for_llm(report)
        assert _SECRET_CONTENT.strip() not in text

    def test_the_text_names_the_section_and_does_not_advise_a_link(self, repo: Path) -> None:
        text = format_report_for_llm(
            build_seed_report(repo, _config(_covering((VAULT, SEED_MODE_COPY))))
        )
        assert "REFUSED" in text
        assert "seed entry #2" in text
        assert "mode: symlink" not in text

    def test_the_configs_own_protected_paths_are_honoured(self, repo: Path) -> None:
        clean = build_seed_report(repo, _config(_covering(("deploy.key", SEED_MODE_COPY))))
        assert clean.refused_copies == ()
        guarded = build_seed_report(
            repo,
            _config(_covering(("deploy.key", SEED_MODE_COPY)), {"protected_paths": ["*.key"]}),
        )
        assert len(guarded.refused_copies) == 1

    def test_replace_mode_with_an_empty_list_protects_nothing(self, repo: Path) -> None:
        report = build_seed_report(
            repo,
            _config(_covering((VAULT, SEED_MODE_COPY)), {"mode": "replace", "protected_paths": []}),
        )
        assert report.refused_copies == ()


class TestUnreadableGuardOptionsRefuseEveryCopy:
    @pytest.mark.parametrize(
        "guard_options",
        [
            {"protected_paths": "*.key"},
            {"protected_paths": [1]},
            {"mode": 3},
            "not-a-mapping",
        ],
    )
    def test_every_copy_entry_is_refused(self, repo: Path, guard_options: Any) -> None:
        report = build_seed_report(
            repo, _config(_covering((".env.local", SEED_MODE_COPY)), guard_options)
        )
        assert len(report.refused_copies) == 1
        assert "could not be read" in report.refused_copies[0]
        assert report.has_drift

    def test_a_link_only_config_is_unaffected(self, repo: Path) -> None:
        report = build_seed_report(repo, _config(_covering(), {"protected_paths": "*.key"}))
        assert report.refused_copies == ()
        assert not report.has_drift


class TestTheCliResult:
    def test_json_carries_the_refusals(self, repo: Path) -> None:
        import yaml

        config_path = repo / ".claude" / "hooks-daemon.yaml"
        config_path.parent.mkdir()
        config_path.write_text(
            yaml.safe_dump(_config(_covering((VAULT, SEED_MODE_COPY)))), encoding="utf-8"
        )
        result = run_check_worktree_seed(repo, config_path, output_format="json")
        assert result["has_drift"] is True
        assert len(result["refused_copies"]) == 1
        assert VAULT not in result["refused_copies"][0]
