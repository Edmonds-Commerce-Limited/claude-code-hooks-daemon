"""Directory and absolute-path patterns are matched on the path a command reaches.

Ledger 00474 N184 (a ``..`` segment is collapsed before matching) and N221 (a
relative path is joined to the command's effective cwd: the hook's cwd, then
each literal ``cd <dir>`` earlier in the same command).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use import secret_file_guard as guard_module
from claude_code_hooks_daemon.utils import secret_file_matching as sfm


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A real directory tree: ``vault/`` (protected), ``x/`` and ``open/``."""
    root = Path(os.path.realpath(tmp_path))
    for name in ("vault", "x", "open"):
        (root / name).mkdir()
    (root / "vault" / "r.md").write_text("synthetic")
    (root / "open" / "r.md").write_text("synthetic")
    return root


def _patterns(root: Path) -> tuple[str, ...]:
    return (f"{root}/vault/**",)


def _mention(command: str, root: Path, cwd: str | None = None) -> tuple[str, str] | None:
    return sfm.find_protected_mention_detail(command, _patterns(root), cwd=cwd)


class TestDotDotCollapse:
    """N184: ``..`` is collapsed lexically before a directory pattern is matched."""

    def test_direct_spelling_matches(self, tree: Path) -> None:
        assert _mention(f"cat {tree}/vault/r.md", tree) is not None

    def test_dotdot_through_sibling_matches(self, tree: Path) -> None:
        assert _mention(f"cat {tree}/x/../vault/r.md", tree) is not None

    def test_dotdot_through_missing_directory_matches(self, tree: Path) -> None:
        assert _mention(f"cat {tree}/nope/../vault/r.md", tree) is not None

    def test_spelling_inside_protected_directory_still_matches_after_collapse(
        self, tree: Path
    ) -> None:
        """Collapsing only adds a spelling to judge; the as-spelled match is kept (fail closed)."""
        assert _mention(f"cat {tree}/vault/../open/r.md", tree) is not None

    def test_relative_dotdot_from_hook_cwd_matches(self, tree: Path) -> None:
        assert _mention("cat ../vault/r.md", tree, cwd=str(tree / "x")) is not None

    def test_relative_dotdot_from_hook_cwd_to_open_file_is_allowed(self, tree: Path) -> None:
        assert _mention("cat ../open/r.md", tree, cwd=str(tree / "x")) is None


class TestEffectiveCwd:
    """N221: a relative path is judged from where the command actually runs."""

    def test_hook_cwd_inside_protected_directory(self, tree: Path) -> None:
        assert _mention("cat r.md", tree, cwd=str(tree / "vault")) is not None

    def test_hook_cwd_outside_protected_directory_is_allowed(self, tree: Path) -> None:
        assert _mention("cat r.md", tree, cwd=str(tree / "open")) is None

    def test_literal_cd_then_read(self, tree: Path) -> None:
        assert _mention("cd vault && cat r.md", tree, cwd=str(tree)) is not None

    def test_literal_absolute_cd_then_read(self, tree: Path) -> None:
        assert _mention(f"cd {tree}/vault && cat r.md", tree) is not None

    def test_cd_with_semicolon_then_read(self, tree: Path) -> None:
        assert _mention("cd vault; cat r.md", tree, cwd=str(tree)) is not None

    def test_chained_cds_accumulate(self, tree: Path) -> None:
        assert _mention("cd x && cd ../vault && cat r.md", tree, cwd=str(tree)) is not None

    def test_pushd_then_read(self, tree: Path) -> None:
        assert _mention("pushd vault && cat r.md", tree, cwd=str(tree)) is not None

    def test_cd_to_open_directory_is_allowed(self, tree: Path) -> None:
        assert _mention("cd open && cat r.md", tree, cwd=str(tree)) is None

    def test_cd_to_variable_is_left_as_before(self, tree: Path) -> None:
        assert _mention("cd $D && cat r.md", tree, cwd=str(tree / "open")) is None

    def test_cd_to_substitution_is_left_as_before(self, tree: Path) -> None:
        assert _mention("cd $(pwd)/vault && cat r.md", tree, cwd=str(tree / "open")) is None

    def test_relative_cd_without_known_cwd_is_ignored(self, tree: Path) -> None:
        assert _mention("cd vault && cat r.md", tree) is None

    def test_prose_word_in_content_is_not_joined_to_cwd(self, tree: Path) -> None:
        found = sfm.find_protected_mention_detail(
            "see r.md", _patterns(tree), cwd=str(tree / "vault"), context="content"
        )
        assert found is None


class TestInterpreterOneLiner:
    """N221: a shell-exec literal in a one-liner runs where the whole command ``cd``-ed."""

    COMMAND = "cd vault && python3 -c 'import subprocess; subprocess.getoutput(\"cat r.md\")'"

    def test_literal_after_cd_matches(self, tree: Path) -> None:
        found = guard_module._bash_interpreter_one_liner_mention(
            self.COMMAND, _patterns(tree), deadline=float("inf"), cwd=str(tree)
        )
        assert found is not None

    def test_literal_without_cd_is_allowed(self, tree: Path) -> None:
        found = guard_module._bash_interpreter_one_liner_mention(
            self.COMMAND.replace("cd vault", "cd open"),
            _patterns(tree),
            deadline=float("inf"),
            cwd=str(tree),
        )
        assert found is None


class TestEffectiveCwds:
    """The helper that lists the directories a command may run in."""

    def test_hook_cwd_only(self, tree: Path) -> None:
        assert sfm.effective_cwds("cat r.md", str(tree)) == (str(tree),)

    def test_no_cwd_no_cd(self) -> None:
        assert sfm.effective_cwds("cat r.md", None) == ()

    def test_relative_hook_cwd_is_not_a_base(self) -> None:
        assert sfm.effective_cwds("cat r.md", "relative/dir") == ()

    def test_cd_targets_follow_in_order(self, tree: Path) -> None:
        assert sfm.effective_cwds("cd x && cd ../vault", str(tree)) == (
            str(tree),
            str(tree / "x"),
            str(tree / "vault"),
        )

    def test_unbalanced_quote_is_skipped(self, tree: Path) -> None:
        assert sfm.effective_cwds("cd 'vault && cat r.md", str(tree)) == (str(tree),)

    def test_cd_without_operand_is_skipped(self, tree: Path) -> None:
        assert sfm.effective_cwds("cd && cat r.md", str(tree)) == (str(tree),)

    def test_cd_dash_is_skipped(self, tree: Path) -> None:
        assert sfm.effective_cwds("cd - && cat r.md", str(tree)) == (str(tree),)

    def test_cd_option_before_operand(self, tree: Path) -> None:
        assert sfm.effective_cwds("cd -P vault", str(tree)) == (str(tree), str(tree / "vault"))
