"""Three branch pools: open work, parked, merged (Plan 00571 Phase 3, DESIGN.md sections 1-7).

Each test builds its own small repository, so the shared inventory fixture is
left alone. Commit dates are pinned against ``NOW`` so ages are exact.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import (
    BranchDuplicatesConfig,
    BranchesConfig,
    BranchMergedConfig,
    BranchParkedConfig,
    BranchWipConfig,
    Config,
)
from claude_code_hooks_daemon.core.branch_creation import creation_verdict
from claude_code_hooks_daemon.core.branch_inventory import (
    BranchState,
    Pool,
    build_inventory,
    pool_of,
)
from claude_code_hooks_daemon.core.branch_sweep import (
    group_records,
    open_work_count,
    pool_count,
    render_report,
    report_json,
)

NOW = 1_800_000_000
DAY = 86_400


def _env(days_ago: float) -> dict[str, str]:
    stamp = f"@{int(NOW - days_ago * DAY)} +0000"
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_DATE": stamp,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }


def _git(repo: Path, *args: str, days_ago: float = 0) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
        text=True,
        env=_env(days_ago),
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "commit", "-q", "--allow-empty", "-m", "root", days_ago=40)
    return root


def _work(repo: Path, name: str, *, days_ago: float = 0, start: str = "main") -> str:
    """A branch one tree-identical commit ahead of ``start``; returns its tip."""
    tree = _git(repo, "rev-parse", f"{start}^{{tree}}")
    sha = _git(repo, "commit-tree", tree, "-p", start, "-m", name, days_ago=days_ago)
    _git(repo, "update-ref", f"refs/heads/{name}", sha)
    return sha


def _unique(repo: Path, name: str, *, days_ago: float = 0) -> str:
    """A branch with a real file change, so it is never patch-equivalent."""
    _git(repo, "checkout", "-q", "-b", name, "main")
    (repo / f"{name.replace('/', '_')}.txt").write_text(name)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", name, days_ago=days_ago)
    _git(repo, "checkout", "-q", "main")
    return _git(repo, "rev-parse", name)


def _park(repo: Path, name: str, *, days_ago: float = 0, reason: str = "waiting") -> str:
    _git(repo, "checkout", "-q", name)
    _git(
        repo,
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "Park branch",
        "-m",
        f"Parked-Reason: {reason}\nParked-By: t",
        days_ago=days_ago,
    )
    _git(repo, "checkout", "-q", "main")
    return _git(repo, "rev-parse", name)


def _merged(repo: Path, name: str) -> None:
    """A branch at main's tip: merged into the default."""
    _git(repo, "branch", name, "main")


def _remote_only(repo: Path, name: str, sha: str) -> None:
    _git(repo, "update-ref", f"refs/remotes/origin/{name}", sha)


def _config(cap: int = 10, **extra: object) -> BranchesConfig:
    return BranchesConfig.model_validate(
        {
            "default": "main",
            "wip": {"cap": cap, "mode": "block", "count_remote": True},
            "duplicates": {"mode": "off"},
            **extra,
        }
    )


# --- config ---------------------------------------------------------------------------


class TestPoolConfig:
    def test_bot_owned_defaults_to_dependabot(self) -> None:
        assert BranchesConfig().bot_owned == ["dependabot/*"]

    def test_a_project_exempt_list_does_not_drop_the_bot_default(self) -> None:
        config = BranchesConfig.model_validate({"exempt": ["users/*"]})
        assert config.bot_owned == ["dependabot/*"]

    @pytest.mark.parametrize("pool", ["parked", "merged"])
    def test_pool_defaults(self, pool: str) -> None:
        section = getattr(BranchesConfig(), pool)
        assert section.cap is None
        assert section.max_age_days is None
        assert section.mode == "block"

    def test_pool_models_forbid_unknown_keys(self) -> None:
        with pytest.raises(ValidationError):
            BranchParkedConfig.model_validate({"limit": 3})
        with pytest.raises(ValidationError):
            BranchMergedConfig.model_validate({"limit": 3})

    def test_pool_cap_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            BranchParkedConfig(cap=0)

    @pytest.mark.parametrize("pool", ["parked", "merged"])
    def test_unset_cap_is_the_wip_cap(self, pool: str) -> None:
        config = BranchesConfig.model_validate({"wip": {"cap": 7}})
        assert config.effective_pool_cap(Pool[pool.upper()]) == 7

    def test_unset_cap_follows_the_legacy_wip_option(self) -> None:
        config = Config.model_validate(
            {"handlers": {"session_start": {"branch_sweep": {"options": {"max_open_branches": 4}}}}}
        )
        assert config.branches.effective_pool_cap(Pool.MERGED) == 4

    def test_set_cap_wins(self) -> None:
        config = BranchesConfig.model_validate({"wip": {"cap": 7}, "parked": {"cap": 3}})
        assert config.effective_pool_cap(Pool.PARKED) == 3
        assert config.effective_pool_cap(Pool.MERGED) == 7
        assert config.effective_pool_cap(Pool.OPEN) == 7

    def test_unset_age_is_the_dormancy_block_stage(self) -> None:
        assert BranchesConfig().effective_pool_max_age(Pool.PARKED) == 30
        strict = BranchesConfig.model_validate({"dormancy": {"preset": "strict"}})
        assert strict.effective_pool_max_age(Pool.MERGED) == 7

    def test_set_age_wins(self) -> None:
        config = BranchesConfig.model_validate({"merged": {"max_age_days": 3}})
        assert config.effective_pool_max_age(Pool.MERGED) == 3
        assert config.effective_pool_max_age(Pool.PARKED) == 30


# --- inventory: bot-owned and pool membership -----------------------------------------


class TestPoolOf:
    @pytest.mark.parametrize(
        ("state", "pool"),
        [
            (BranchState.LIVE, Pool.OPEN),
            (BranchState.DORMANT, Pool.OPEN),
            (BranchState.UNCLASSIFIED, Pool.OPEN),
            (BranchState.PARKED, Pool.PARKED),
            (BranchState.MERGED_DEFAULT, Pool.MERGED),
            (BranchState.MERGED_LINE, Pool.MERGED),
            (BranchState.PATCH_EQUIVALENT, Pool.MERGED),
            (BranchState.EXEMPT, None),
            (BranchState.DEFAULT, None),
            (BranchState.PROTECTED, None),
            (BranchState.INTEGRATION_LINE, None),
            (BranchState.BOT_OWNED, None),
        ],
    )
    def test_each_state_has_one_pool(self, state: BranchState, pool: Pool | None) -> None:
        assert pool_of(state) == pool


class TestBotOwned:
    def test_dependabot_branch_is_bot_owned_and_in_no_pool(self, repo: Path) -> None:
        sha = _unique(repo, "scratch")
        _git(repo, "branch", "-D", "scratch")
        _remote_only(repo, "dependabot/pip/foo-1.2", sha)
        inventory = build_inventory(repo, _config(), now=NOW)
        record = inventory.records["dependabot/pip/foo-1.2"]
        assert record.state == BranchState.BOT_OWNED
        assert pool_count(inventory, Pool.OPEN) == 0

    def test_bot_owned_is_listed_in_its_own_group_without_all(self, repo: Path) -> None:
        sha = _unique(repo, "scratch")
        _git(repo, "branch", "-D", "scratch")
        _remote_only(repo, "dependabot/npm/bar", sha)
        inventory = build_inventory(repo, _config(), now=NOW)
        assert [r.name for r in group_records(inventory).bot_owned] == ["dependabot/npm/bar"]
        text = "\n".join(render_report(inventory, _config(), cap=10))
        assert "Bot-owned" in text and "dependabot/npm/bar" in text

    def test_bot_branches_do_not_count_toward_the_creation_cap(self, repo: Path) -> None:
        _unique(repo, "one")
        for index in range(3):
            sha = _work(repo, f"tmp{index}")
            _git(repo, "branch", "-D", f"tmp{index}")
            _remote_only(repo, f"dependabot/pip/p{index}", sha)
        assert creation_verdict(repo, _config(cap=2), "fresh").decision == "allow"

    def test_a_custom_bot_glob_is_honoured(self, repo: Path) -> None:
        sha = _unique(repo, "scratch")
        _git(repo, "branch", "-D", "scratch")
        _remote_only(repo, "renovate/foo", sha)
        config = _config(bot_owned=["dependabot/*", "renovate/*"])
        assert build_inventory(repo, config, now=NOW).records["renovate/foo"].state == (
            BranchState.BOT_OWNED
        )


# --- the pool split ---------------------------------------------------------------------


class TestPoolSplit:
    def test_parked_branches_leave_the_wip_count(self, repo: Path) -> None:
        _unique(repo, "one")
        _unique(repo, "two")
        _park(repo, "two")
        inventory = build_inventory(repo, _config(), now=NOW)
        assert open_work_count(inventory) == 1
        assert pool_count(inventory, Pool.PARKED) == 1
        assert creation_verdict(repo, _config(cap=2), "fresh", now=NOW).decision == "allow"

    def test_merged_branches_leave_the_wip_count(self, repo: Path) -> None:
        _unique(repo, "one")
        _merged(repo, "done")
        inventory = build_inventory(repo, _config(), now=NOW)
        assert open_work_count(inventory) == 1
        assert pool_count(inventory, Pool.MERGED) == 1
        assert creation_verdict(repo, _config(cap=2), "fresh", now=NOW).decision == "allow"

    def test_a_remote_merged_copy_leaves_the_wip_count(self, repo: Path) -> None:
        _unique(repo, "one")
        _remote_only(repo, "main", _git(repo, "rev-parse", "main"))
        _remote_only(repo, "done", _git(repo, "rev-parse", "main"))
        assert creation_verdict(repo, _config(cap=2), "fresh", now=NOW).decision == "allow"

    def test_a_patch_equivalent_label_leaves_the_wip_count(self, repo: Path) -> None:
        _unique(repo, "one")
        _unique(repo, "cherry")
        labels = {"cherry": {"group": "patch-equivalent", "action": None, "stage": None}}
        verdict = creation_verdict(repo, _config(cap=2), "fresh", labels=labels, now=NOW)
        assert verdict.decision == "allow"

    def test_the_wip_deny_lists_open_work_only(self, repo: Path) -> None:
        _unique(repo, "one")
        _unique(repo, "two")
        _merged(repo, "done")
        _unique(repo, "held")
        _park(repo, "held")
        verdict = creation_verdict(repo, _config(cap=2), "fresh", now=NOW)
        assert verdict.decision == "deny"
        listed = "\n".join(line for line in verdict.lines if line.startswith("  - "))
        assert "one" in listed and "two" in listed
        assert "done" not in listed and "held" not in listed

    def test_open_work_beats_parked_within_one_group(self, repo: Path) -> None:
        """A local parked copy and a remote unparked copy of one name: open work wins."""
        before = _unique(repo, "one")
        _park(repo, "one")
        _remote_only(repo, "one", before)
        _unique(repo, "two")
        assert creation_verdict(repo, _config(cap=2), "fresh", now=NOW).decision == "deny"

    def test_report_footer_names_each_pool_key(self, repo: Path) -> None:
        _unique(repo, "one")
        _merged(repo, "done")
        inventory = build_inventory(repo, _config(), now=NOW)
        text = "\n".join(render_report(inventory, _config(), cap=10))
        assert "Open work: 1 of 10 (branches.wip.cap)" in text
        assert "Parked: 0 of 10 (branches.parked.cap)" in text
        assert "Merged, not deleted: 1 of 10 (branches.merged.cap)" in text

    def test_json_carries_pool_per_record_and_pool_counts(self, repo: Path) -> None:
        _unique(repo, "one")
        _merged(repo, "done")
        sha = _work(repo, "tmp")
        _git(repo, "branch", "-D", "tmp")
        _remote_only(repo, "dependabot/x", sha)
        inventory = build_inventory(repo, _config(), now=NOW)
        document = report_json(inventory, cap=10, config=_config())
        pools = {record["name"]: record["pool"] for record in document["branches"]}
        assert pools == {"done": "merged", "one": "open", "main": None, "dependabot/x": None}
        assert document["pools"]["open"] == {"count": 1, "cap": 10}
        assert document["pools"]["merged"] == {"count": 1, "cap": 10}
        assert document["pools"]["parked"] == {"count": 0, "cap": 10}


def test_duplicates_still_cover_parked_work(repo: Path) -> None:
    """The duplicate warning is about names, not pools: a parked twin still warns."""
    _unique(repo, "fix-login")
    _park(repo, "fix-login")
    config = BranchesConfig(
        default="main",
        wip=BranchWipConfig(cap=10),
        duplicates=BranchDuplicatesConfig(mode="warn"),
    )
    assert creation_verdict(repo, config, "fix-login-2", now=NOW).decision == "warn"
