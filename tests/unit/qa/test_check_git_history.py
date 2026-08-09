"""Tests for the git-history sensitive-content sweep (Plan 00202).

The batch equivalent of the write-time guard. A PreToolUse handler only ever
sees what Claude Code is about to do; it cannot see what is already committed,
and this repository's own history needed four distinct ``git-filter-repo``
mechanisms to clean because a term can sit in a commit message, an author
identity, a tag name, a tag message or a branch name — none of which is a file.

Same two sources and the same no-echo rule as the tree scanner: a secret-list
match reports a locator and an entry INDEX, never the term.

NOTE: this repo's own dogfood config enables a real public path pattern, so the
example path below is built by concatenation at runtime and never appears as
one contiguous literal in this file — otherwise editing this very file would
trip the live handler. (It did, on the first draft.)
"""

import json
import subprocess  # nosec B404 - subprocess used for git fixtures and the QA checker
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHECKER = _REPO_ROOT / "scripts" / "qa" / "check_git_history.py"
_JSON_OUTPUT = _REPO_ROOT / "untracked" / "qa" / "git_history.json"

_TERM = "zzqx-nonsense-term"
_EXAMPLE_PATH = "/var/www" + "/vh" + "osts"


def _git(repo: Path, *args: str, **env: str) -> None:
    """Run a git command in ``repo``, failing loudly."""
    environment = {
        "GIT_AUTHOR_NAME": "Clean Author",
        "GIT_AUTHOR_EMAIL": "clean@example.com",
        "GIT_COMMITTER_NAME": "Clean Author",
        "GIT_COMMITTER_EMAIL": "clean@example.com",
        "PATH": "/usr/bin:/bin",
        "HOME": str(repo),
        **env,
    }
    subprocess.run(  # nosec B603 B607 - trusted system tool (git), list form
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )


def _head_sha(repo: Path) -> str:
    return subprocess.run(  # nosec B603 B607 - trusted system tool (git), list form
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    (repo / "file.txt").write_text("clean body\n")
    _git(repo, "add", "file.txt")
    _git(repo, "commit", "-q", "-m", "an ordinary first commit")


def _write_config(
    config_path: Path,
    *,
    history_baseline: str | None = None,
    grandfathered_refs: list[str] | None = None,
    public_patterns: list[dict[str, str]] | None = None,
) -> None:
    lines = [
        "handlers:",
        "  pre_tool_use:",
        "    sensitive_content:",
        "      enabled: true",
        "      options:",
    ]
    if grandfathered_refs is not None:
        lines.append("        history_grandfathered_refs:")
        lines.extend(f"          - '{name}'" for name in grandfathered_refs)
    if history_baseline is not None:
        lines.append(f"        history_baseline: {history_baseline}")
    if public_patterns:
        lines.append("        public_patterns:")
        for entry in public_patterns:
            lines.append(f"          - name: {entry['name']}")
            lines.append(f"            pattern: '{entry['pattern']}'")
            lines.append(f"            description: '{entry.get('description', '')}'")
    else:
        # Keeps the options block non-empty however the other knobs are set.
        lines.append("        public_patterns: []")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("\n".join(lines) + "\n")


def _secret_list(repo: Path) -> Path:
    secret_file = repo / ".claude" / "block-words.secret"
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    secret_file.write_text(f"{_TERM}\n")
    return secret_file


def _run_checker(repo: Path, config_path: Path) -> dict[str, Any]:
    subprocess.run(  # nosec B603 - trusted first-party checker script
        [
            sys.executable,
            str(_CHECKER),
            "--json",
            "--repo",
            str(repo),
            "--config",
            str(config_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert _JSON_OUTPUT.exists(), f"Expected JSON output at {_JSON_OUTPUT}"
    return json.loads(_JSON_OUTPUT.read_text())


class TestCleanHistory:
    def test_clean_repo_passes(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        _secret_list(repo)
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)

        data = _run_checker(repo, config)

        assert data["summary"]["passed"] is True
        assert data["summary"]["total_violations"] == 0

    def test_non_repo_is_inert(self, tmp_path: Path) -> None:
        """A directory that is not a git repo is not a finding — it is not a repo."""
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)

        data = _run_checker(tmp_path / "not-a-repo", config)

        assert data["summary"]["passed"] is True

    def test_missing_secret_file_is_inert(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        _git(repo, "commit", "-q", "--allow-empty", "-m", f"mentions {_TERM}")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)

        data = _run_checker(repo, config)

        assert data["summary"]["passed"] is True


class TestCommitMessageSurface:
    def test_term_in_commit_message_is_flagged(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        _secret_list(repo)
        _git(repo, "commit", "-q", "--allow-empty", "-m", f"fixes {_TERM} handling")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)

        data = _run_checker(repo, config)

        assert data["summary"]["passed"] is False
        assert "commit-message" in {v["surface"] for v in data["violations"]}

    def test_term_never_appears_in_the_whole_report(self, tmp_path: Path) -> None:
        """THE core security property — scan the entire response, not one field."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        _secret_list(repo)
        _git(repo, "commit", "-q", "--allow-empty", "-m", f"fixes {_TERM} handling")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)

        data = _run_checker(repo, config)

        assert _TERM not in json.dumps(data)
        assert any("entry 1 of 1" in v["message"] for v in data["violations"])

    def test_violation_names_the_commit(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        _secret_list(repo)
        _git(repo, "commit", "-q", "--allow-empty", "-m", f"fixes {_TERM} handling")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)

        data = _run_checker(repo, config)

        offending = next(v for v in data["violations"] if v["surface"] == "commit-message")
        assert offending["locator"].startswith(_head_sha(repo)[:7])


class TestIdentityAndRefSurfaces:
    def test_term_in_author_identity_is_flagged(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        _secret_list(repo)
        _git(
            repo,
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "an ordinary message",
            GIT_AUTHOR_NAME=_TERM,
            GIT_AUTHOR_EMAIL=f"{_TERM}@example.com",
            GIT_COMMITTER_NAME="Clean Author",
            GIT_COMMITTER_EMAIL="clean@example.com",
        )
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)

        data = _run_checker(repo, config)

        assert "commit-identity" in {v["surface"] for v in data["violations"]}

    def test_term_in_tag_name_is_flagged(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        _secret_list(repo)
        _git(repo, "tag", f"{_TERM}-v1")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)

        data = _run_checker(repo, config)

        assert "ref-name" in {v["surface"] for v in data["violations"]}

    def test_term_in_tag_message_is_flagged(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        _secret_list(repo)
        _git(repo, "tag", "-a", "v1.0.0", "-m", f"ships {_TERM}")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)

        data = _run_checker(repo, config)

        assert "tag-message" in {v["surface"] for v in data["violations"]}

    def test_branch_tip_message_is_not_reported_as_a_tag_message(self, tmp_path: Path) -> None:
        """``%(contents)`` on a branch head returns the TIP COMMIT's message.

        Scanning it blindly reports every commit message a second time under
        the wrong surface — and, worse, launders it past the baseline, because
        a ref is deliberately never grandfathered. Caught by the baseline test
        failing on a repo whose only sin was already exempt.
        """
        repo = tmp_path / "repo"
        _init_repo(repo)
        _secret_list(repo)
        _git(repo, "commit", "-q", "--allow-empty", "-m", f"sin: {_TERM}")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)

        data = _run_checker(repo, config)

        surfaces = {v["surface"] for v in data["violations"]}
        assert "commit-message" in surfaces
        assert "tag-message" not in surfaces

    def test_lightweight_tag_does_not_report_the_commit_message_as_its_own(
        self, tmp_path: Path
    ) -> None:
        """Same trap: a lightweight tag is a commit, so its contents is that message."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        _secret_list(repo)
        _git(repo, "commit", "-q", "--allow-empty", "-m", f"sin: {_TERM}")
        _git(repo, "tag", "clean-tag-name")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)

        data = _run_checker(repo, config)

        assert "tag-message" not in {v["surface"] for v in data["violations"]}

    def test_term_in_branch_name_is_flagged(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        _secret_list(repo)
        _git(repo, "branch", f"{_TERM}-work")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)

        data = _run_checker(repo, config)

        assert "ref-name" in {v["surface"] for v in data["violations"]}


class TestPublicPatterns:
    def test_public_pattern_in_commit_message_names_the_match(self, tmp_path: Path) -> None:
        """Public patterns are safe to name — that is what makes them fixable."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        _git(repo, "commit", "-q", "--allow-empty", "-m", f"deploy to {_EXAMPLE_PATH}/site")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(
            config,
            public_patterns=[
                {"name": "vhosts-path", "pattern": _EXAMPLE_PATH, "description": "server path"}
            ],
        )

        data = _run_checker(repo, config)

        assert data["summary"]["passed"] is False
        assert any("vhosts-path" in v["rule"] for v in data["violations"])


class TestInvalidConfiguration:
    def test_uncompilable_public_pattern_is_reported_not_skipped(self, tmp_path: Path) -> None:
        """A rule that cannot compile is a guard that silently stopped guarding.

        The live handler treats a bad regex as a no-match so one config typo
        cannot break every Write. A QA gate has the opposite obligation: a
        dropped rule makes it pass because it stopped looking.
        """
        repo = tmp_path / "repo"
        _init_repo(repo)
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(
            config,
            public_patterns=[{"name": "broken", "pattern": "[unclosed", "description": ""}],
        )

        data = _run_checker(repo, config)

        assert data["summary"]["passed"] is False
        assert any(v["surface"] == "config" for v in data["violations"])


class TestHistoryBaseline:
    """Grandfathering, without which this gate is red on day one and stays red.

    This repository's own history carries the term in 25 commit-message lines,
    1 identity and 5 tag messages, and cannot be cleaned without a force-push
    that only a human may run. A gate that cannot go green until then is a gate
    that gets disabled — so history at or before a declared baseline commit is
    exempt, and the gate enforces "no NEW contamination" from the moment it
    lands.
    """

    def test_contamination_at_or_before_the_baseline_is_exempt(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        _secret_list(repo)
        _git(repo, "commit", "-q", "--allow-empty", "-m", f"old sin: {_TERM}")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config, history_baseline=_head_sha(repo))

        data = _run_checker(repo, config)

        assert data["summary"]["passed"] is True

    def test_contamination_after_the_baseline_is_still_flagged(self, tmp_path: Path) -> None:
        """The half that matters: grandfathering must not become an amnesty."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        _secret_list(repo)
        baseline = _head_sha(repo)
        _git(repo, "commit", "-q", "--allow-empty", "-m", f"new sin: {_TERM}")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config, history_baseline=baseline)

        data = _run_checker(repo, config)

        assert data["summary"]["passed"] is False
        assert "commit-message" in {v["surface"] for v in data["violations"]}

    def test_unknown_baseline_ref_sweeps_everything(self, tmp_path: Path) -> None:
        """An unresolvable baseline must FAIL SAFE — sweep all, never exempt all.

        A typo'd or rewritten-away SHA silently exempting the entire history is
        the failure mode that turns this gate into decoration.
        """
        repo = tmp_path / "repo"
        _init_repo(repo)
        _secret_list(repo)
        _git(repo, "commit", "-q", "--allow-empty", "-m", f"sin: {_TERM}")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config, history_baseline="0" * 40)

        data = _run_checker(repo, config)

        assert data["summary"]["passed"] is False

    def test_grandfathered_ref_is_exempt(self, tmp_path: Path) -> None:
        """Refs need their own list — the commit baseline structurally cannot cover them."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        _secret_list(repo)
        _git(repo, "tag", "-a", "v1.0.0", "-m", f"ships {_TERM}")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config, grandfathered_refs=["v1.0.0"])

        data = _run_checker(repo, config)

        assert data["summary"]["passed"] is True

    def test_a_grandfather_entry_that_is_no_longer_needed_is_reported(self, tmp_path: Path) -> None:
        """The escape hatch polices its own obsolescence.

        Unlike the commit baseline, a ref allowlist does NOT auto-expire: the
        same tag names survive a history rewrite with cleaned messages, so a
        forgotten entry would exempt them silently forever — and swallow any
        FUTURE leak on that ref name.
        """
        repo = tmp_path / "repo"
        _init_repo(repo)
        _secret_list(repo)
        _git(repo, "tag", "-a", "v1.0.0", "-m", "an entirely clean tag message")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config, grandfathered_refs=["v1.0.0"])

        data = _run_checker(repo, config)

        assert data["summary"]["passed"] is False
        assert any(v["rule"] == "stale-grandfather" for v in data["violations"])

    def test_a_grandfather_entry_for_a_vanished_ref_is_reported(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        _secret_list(repo)
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config, grandfathered_refs=["v-never-existed"])

        data = _run_checker(repo, config)

        assert data["summary"]["passed"] is False
        assert any(v["rule"] == "stale-grandfather" for v in data["violations"])

    def test_grandfathering_one_ref_does_not_exempt_another(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        _secret_list(repo)
        _git(repo, "tag", "-a", "v1.0.0", "-m", f"ships {_TERM}")
        _git(repo, "tag", "-a", "v2.0.0", "-m", f"also ships {_TERM}")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config, grandfathered_refs=["v1.0.0"])

        data = _run_checker(repo, config)

        assert data["summary"]["passed"] is False
        assert {v["locator"] for v in data["violations"]} == {"v2.0.0"}

    def test_baseline_does_not_exempt_a_tag_created_after_it(self, tmp_path: Path) -> None:
        """Refs have no ancestry of their own — a NEW tag on an OLD commit still counts.

        Exempting by the tagged commit alone would let a fresh tag name carry a
        term into a repository whose commits are all grandfathered.
        """
        repo = tmp_path / "repo"
        _init_repo(repo)
        _secret_list(repo)
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config, history_baseline=_head_sha(repo))
        _git(repo, "tag", f"{_TERM}-v1")

        data = _run_checker(repo, config)

        assert data["summary"]["passed"] is False
        assert "ref-name" in {v["surface"] for v in data["violations"]}
