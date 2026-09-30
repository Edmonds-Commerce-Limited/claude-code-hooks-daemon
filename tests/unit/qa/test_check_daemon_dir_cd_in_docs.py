"""No doc instructs an agent to `cd` into `.claude/hooks-daemon/` (Plan 00376).

`daemon_location_guard`'s `R-DAEMON-DIR-CD` rule denies that command
unconditionally for an agent -- daemon CLI commands must run from the project
root. A doc that instructs it anyway is a defect an agent following the doc
hits immediately, every time it upgrades across versions.

This checker reuses `daemon_location_guard`'s own compiled pattern, so if the
handler's rule ever changes what it denies, this checker's notion of a
violation moves with it, in one place -- `test_the_checker_shares_the_handlers_pattern`
pins that.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHECKER = _REPO_ROOT / "scripts" / "qa" / "check_daemon_dir_cd_in_docs.py"


def _load_checker() -> ModuleType:
    """Import the checker by path, without mutating `sys.path`.

    `scripts/qa/` is not a package, so loading it in-process here keeps the
    assertions against real return values rather than a re-parsed file, and
    avoids the shared `untracked/qa/` artefact other suites would race over.
    """
    spec = importlib.util.spec_from_file_location("check_daemon_dir_cd_in_docs", _CHECKER)
    assert spec is not None and spec.loader is not None, f"cannot load {_CHECKER}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestWhatCountsAsAViolation:
    def test_a_plain_cd_into_the_daemon_dir_is_a_violation(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "CLAUDE/UPGRADES/v9/v9.0-to-v9.1.md",
            "```bash\ncd .claude/hooks-daemon\nbin/hooks-daemon status\n```\n",
        )

        violations = checker.find_violations(tmp_path)

        assert len(violations) == 1
        assert violations[0]["file"] == "CLAUDE/UPGRADES/v9/v9.0-to-v9.1.md"
        assert violations[0]["line"] == 2

    def test_a_trailing_slash_is_still_a_violation(self, tmp_path: Path) -> None:
        _write(tmp_path, "CLAUDE/LLM-UPDATE.md", "cd .claude/hooks-daemon/\n")

        assert len(checker.find_violations(tmp_path)) == 1

    def test_cd_into_an_unrelated_directory_is_not_flagged(self, tmp_path: Path) -> None:
        _write(tmp_path, "CLAUDE/LLM-UPDATE.md", "cd /path/to/your/project\n")

        assert checker.find_violations(tmp_path) == []

    def test_a_bare_mention_with_no_cd_is_not_flagged(self, tmp_path: Path) -> None:
        """Naming the path is fine; only the `cd` instruction is a defect."""
        _write(
            tmp_path,
            "CLAUDE/LLM-UPDATE.md",
            "cat .claude/hooks-daemon/src/claude_code_hooks_daemon/version.py\n",
        )

        assert checker.find_violations(tmp_path) == []


class TestWhereItLooks:
    def test_markdown_outside_the_upgrade_tree_is_still_checked(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/guides/SOMETHING.md", "cd .claude/hooks-daemon\n")

        assert len(checker.find_violations(tmp_path)) == 1

    def test_the_plan_tree_is_skipped(self, tmp_path: Path) -> None:
        """`CLAUDE/Plan/` is a process/audit trail, not an operational run-book."""
        _write(
            tmp_path,
            "CLAUDE/Plan/Completed/00047-example/PLAN.md",
            "cd .claude/hooks-daemon\n",
        )

        assert checker.find_violations(tmp_path) == []

    def test_the_releases_tree_is_skipped(self, tmp_path: Path) -> None:
        """One frozen per-version announcement, not a doc a future upgrade reads."""
        _write(tmp_path, "RELEASES/v2.19.0.md", "cd .claude/hooks-daemon\n")

        assert checker.find_violations(tmp_path) == []

    def test_the_changelog_is_skipped(self, tmp_path: Path) -> None:
        _write(tmp_path, "CHANGELOG.md", "cd .claude/hooks-daemon\n")

        assert checker.find_violations(tmp_path) == []

    def test_untracked_output_is_skipped(self, tmp_path: Path) -> None:
        _write(tmp_path, "untracked/scratch/notes.md", "cd .claude/hooks-daemon\n")

        assert checker.find_violations(tmp_path) == []

    def test_a_worktree_checkout_path_does_not_defeat_the_sweep(self, tmp_path: Path) -> None:
        """This repo is routinely checked out under `untracked/worktrees/<name>/`.

        Skip-dir membership must be checked against the path RELATIVE to the
        scanned root, not the absolute path -- otherwise every file in the
        whole tree matches on that ancestor alone and nothing is scanned.
        """
        worktree_root = tmp_path / "untracked" / "worktrees" / "worktree-example"
        _write(worktree_root, "CLAUDE/LLM-UPDATE.md", "cd .claude/hooks-daemon\n")

        assert len(checker.find_violations(worktree_root)) == 1


class TestTheExemptionMarkers:
    def test_owner_only_within_the_context_window_is_exempt(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "CLAUDE/UPGRADES/v9/v9.0-to-v9.1.md",
            "Rollback -- OWNER-ONLY:\n\n```bash\ncd .claude/hooks-daemon\ngit checkout v9.0.0\n```\n",
        )

        assert checker.find_violations(tmp_path) == []

    def test_blocked_example_within_the_context_window_is_exempt(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "docs/guides/HANDLER_REFERENCE.md",
            "Example trigger (BLOCKED-EXAMPLE):\n\n```bash\ncd .claude/hooks-daemon\n```\n",
        )

        assert checker.find_violations(tmp_path) == []

    def test_a_marker_outside_the_context_window_does_not_exempt(self, tmp_path: Path) -> None:
        filler = "\n".join(f"filler line {n}" for n in range(20))
        _write(
            tmp_path,
            "CLAUDE/UPGRADES/v9/v9.0-to-v9.1.md",
            f"OWNER-ONLY\n{filler}\ncd .claude/hooks-daemon\n",
        )

        assert len(checker.find_violations(tmp_path)) == 1

    def test_the_marker_must_match_exactly(self, tmp_path: Path) -> None:
        """`owner-only` prose elsewhere must not accidentally exempt a step."""
        _write(
            tmp_path,
            "CLAUDE/UPGRADES/v9/v9.0-to-v9.1.md",
            "this step is for the owner only\ncd .claude/hooks-daemon\n",
        )

        assert len(checker.find_violations(tmp_path)) == 1


class TestTheCheckerSharesTheHandlersPattern:
    def test_the_checker_shares_the_handlers_pattern(self) -> None:
        """If the handler's own regex changes, this checker moves with it."""
        import sys

        sys.path.insert(0, str(_REPO_ROOT / "src"))
        from claude_code_hooks_daemon.handlers.pre_tool_use.daemon_location_guard import (
            _CD_INTO_DAEMON_DIR,
        )

        assert checker._daemon_dir_cd_pattern() is _CD_INTO_DAEMON_DIR


class TestTheLiveRepositoryIsClean:
    def test_no_tracked_doc_instructs_cd_into_the_daemon_dir(self) -> None:
        """The check that actually protects agents following these docs, run for real."""
        violations = checker.find_violations(_REPO_ROOT)

        assert violations == [], "cd-into-daemon-dir instructions found:\n" + "\n".join(
            f"  {item['file']}:{item['line']}  {item['message']}" for item in violations
        )
