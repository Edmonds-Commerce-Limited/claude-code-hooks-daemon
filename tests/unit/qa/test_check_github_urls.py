"""Every GitHub URL naming this project must name THIS repository (Plan 00403).

The defect that motivated this check is not a broken link. The `report` skill —
the one a CLIENT project runs when the daemon misbehaves — told the reporter to
open an issue at `anthropics/claude-code-hooks-daemon`, a repository this
project does not control. Following that instruction aims a client's
diagnostics at a third party, and two shipped `RELEASES/` notes carry
`git clone` commands pointing at a different third org again, which is an
install-from-the-wrong-source hazard rather than a typo.

One detail is load-bearing and is why the checker walks the tree itself rather
than shelling out to a search tool: `.claude/` is a HIDDEN directory, and `rg`
skips hidden directories unless asked not to. The deployed copy of the very
skill at fault lives there, so the obvious one-line sweep silently misses the
file that matters most. `test_a_hidden_directory_is_searched` pins that.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHECKER = _REPO_ROOT / "scripts" / "qa" / "check_github_urls.py"


def _load_checker() -> ModuleType:
    """Import the checker by path, without mutating `sys.path`.

    `scripts/qa/` is not a package, so the sibling suites shell out to the
    script and read its JSON. Loading it in-process here keeps the assertions
    against real return values rather than a re-parsed file, and avoids the
    shared `untracked/qa/` artefact two suites would then race over.
    """
    spec = importlib.util.spec_from_file_location("check_github_urls", _CHECKER)
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
    def test_the_canonical_repository_is_clean(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "docs/guide.md",
            f"See https://github.com/{checker.CANONICAL_REPO}/issues\n",
        )

        assert checker.find_violations(tmp_path) == []

    def test_another_org_naming_this_project_is_a_violation(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "docs/guide.md",
            "Open an issue at https://github.com/anthropics/claude-code-hooks-daemon/issues\n",
        )

        violations = checker.find_violations(tmp_path)

        assert len(violations) == 1
        assert violations[0]["file"] == "docs/guide.md"
        assert violations[0]["line"] == 1

    def test_the_violation_names_the_wrong_org_so_it_can_be_judged(self, tmp_path: Path) -> None:
        """A finding that does not say WHICH org cannot be triaged from the report."""
        _write(
            tmp_path,
            "docs/guide.md",
            "https://github.com/cravend/claude-code-hooks-daemon.git\n",
        )

        assert "cravend" in checker.find_violations(tmp_path)[0]["message"]

    def test_an_unrelated_github_url_is_not_touched(self, tmp_path: Path) -> None:
        """This checks OUR repository's identity, not every link in the tree."""
        _write(tmp_path, "docs/guide.md", "https://github.com/astral-sh/ruff\n")

        assert checker.find_violations(tmp_path) == []

    def test_a_clone_command_is_reported_like_any_other_url(self, tmp_path: Path) -> None:
        """The worst case: it installs code from a repository we do not control."""
        _write(
            tmp_path,
            "RELEASES/v2.19.0.md",
            "git clone -b v2.19.0 https://github.com/cravend/claude-code-hooks-daemon.git x\n",
        )

        assert len(checker.find_violations(tmp_path)) == 1


class TestWhereItLooks:
    def test_a_hidden_directory_is_searched(self, tmp_path: Path) -> None:
        """The regression guard. `rg` skips hidden dirs unless told otherwise.

        The deployed skill that carried the wrong org lives at
        `.claude/skills/hooks-daemon/report.md`, so a checker that inherits that
        default reports a clean tree while the worst instance sits untouched —
        which is exactly what the first sweep for this bug did.
        """
        _write(
            tmp_path,
            ".claude/skills/hooks-daemon/report.md",
            "https://github.com/anthropics/claude-code-hooks-daemon/issues\n",
        )

        violations = checker.find_violations(tmp_path)

        assert len(violations) == 1
        assert violations[0]["file"] == ".claude/skills/hooks-daemon/report.md"

    def test_the_git_directory_is_skipped(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            ".git/COMMIT_EDITMSG",
            "https://github.com/anthropics/claude-code-hooks-daemon\n",
        )

        assert checker.find_violations(tmp_path) == []

    def test_untracked_output_is_skipped(self, tmp_path: Path) -> None:
        """Scratch captures routinely quote a bad URL while diagnosing it."""
        _write(
            tmp_path,
            "untracked/scratch/notes.md",
            "https://github.com/anthropics/claude-code-hooks-daemon\n",
        )

        assert checker.find_violations(tmp_path) == []

    def test_the_supervisor_runtime_tree_is_skipped(self, tmp_path: Path) -> None:
        """`.claude/ccy/` records the session that DIAGNOSED the bad URL.

        Session transcripts, subagent logs and tool-result dumps all quote the
        text being investigated, so a checker that read them would fail on its
        own evidence and keep failing after the real fix landed. Gitignored
        runtime state, not project source.
        """
        _write(
            tmp_path,
            ".claude/ccy/projects/-workspace/session.jsonl",
            '{"text":"https://github.com/anthropics/claude-code-hooks-daemon"}\n',
        )

        assert checker.find_violations(tmp_path) == []

    def test_a_binary_file_does_not_stop_the_sweep(self, tmp_path: Path) -> None:
        """One unreadable file must not silently truncate the whole check."""
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")
        _write(
            tmp_path,
            "docs/guide.md",
            "https://github.com/anthropics/claude-code-hooks-daemon\n",
        )

        assert len(checker.find_violations(tmp_path)) == 1

    def test_an_undecodable_file_is_reported_rather_than_dropped(self, tmp_path: Path) -> None:
        """Skipping a binary blob is right; skipping it SILENTLY is not.

        An encoding change or a permissions mistake could drop a swathe of the
        tree, and the resulting clean sweep would be indistinguishable from a
        genuinely clean one.
        """
        (tmp_path / "docs").mkdir(parents=True)
        (tmp_path / "docs" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")
        unreadable: list[str] = []

        checker.find_violations(tmp_path, unreadable=unreadable)

        assert len(unreadable) == 1
        assert "docs/logo.png" in unreadable[0]

    def test_a_clean_readable_tree_reports_nothing_unreadable(self, tmp_path: Path) -> None:
        """The other half — otherwise the sink could be noise nobody can read."""
        _write(tmp_path, "docs/guide.md", "no urls here\n")
        unreadable: list[str] = []

        checker.find_violations(tmp_path, unreadable=unreadable)

        assert unreadable == []


class TestTheAllowlist:
    def test_a_test_fixture_org_is_allowed(self, tmp_path: Path) -> None:
        """`example/` in a test fixture is deliberate, not a mistake."""
        _write(
            tmp_path,
            "tests/unit/test_install.py",
            'stdout="https://github.com/example/claude-code-hooks-daemon.git\\n",\n',
        )

        assert checker.find_violations(tmp_path) == []

    def test_an_archived_third_party_report_is_allowed(self, tmp_path: Path) -> None:
        """It records what someone ELSE wrote; rewriting it would falsify it."""
        _write(
            tmp_path,
            "CLAUDE/Plan/Completed/00165-install-permission-bug-fixes/report.md",
            "https://github.com/anthropics/claude-code-hooks-daemon\n",
        )

        assert checker.find_violations(tmp_path) == []

    def test_the_checker_does_not_flag_its_own_patterns(self, tmp_path: Path) -> None:
        """Otherwise the fix for every violation is to delete the checker."""
        _write(
            tmp_path,
            "scripts/qa/check_github_urls.py",
            '_WRONG = "https://github.com/anthropics/claude-code-hooks-daemon"\n',
        )

        assert checker.find_violations(tmp_path) == []

    def test_this_test_file_is_allowed(self, tmp_path: Path) -> None:
        """This suite quotes bad URLs on purpose, and must not fail on itself."""
        _write(
            tmp_path,
            "tests/unit/qa/test_check_github_urls.py",
            "https://github.com/anthropics/claude-code-hooks-daemon\n",
        )

        assert checker.find_violations(tmp_path) == []


class TestTheLiveRepositoryIsClean:
    def test_no_tracked_file_points_at_another_org(self) -> None:
        """The check that actually protects the repository, run against it.

        Deliberately not a fixture: the point is that a real file in this tree
        told clients to file issues at a repository we do not own, and only a
        sweep of the real tree can say it no longer does.
        """
        violations = checker.find_violations(_REPO_ROOT)

        assert violations == [], "GitHub URLs naming another org:\n" + "\n".join(
            f"  {item['file']}:{item['line']}  {item['message']}" for item in violations
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/anthropics/claude-code-hooks-daemon",
        "http://github.com/anthropics/claude-code-hooks-daemon",
        "https://www.github.com/anthropics/claude-code-hooks-daemon",
        "git@github.com:anthropics/claude-code-hooks-daemon.git",
    ],
)
def test_every_url_form_is_recognised(tmp_path: Path, url: str) -> None:
    """A checker that only knows the https form leaves the ssh form unguarded."""
    _write(tmp_path, "docs/guide.md", f"{url}\n")

    assert len(checker.find_violations(tmp_path)) == 1
