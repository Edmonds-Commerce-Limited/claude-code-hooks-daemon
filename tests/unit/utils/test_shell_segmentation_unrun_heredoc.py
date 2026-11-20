"""strip_unrun_heredoc_bodies: a body nothing runs, now or later (Plan 00478 Task 2.2f)."""

import pytest

from claude_code_hooks_daemon.utils.shell_segmentation import (
    strip_never_run_heredoc_bodies,
    strip_unrun_heredoc_bodies,
)

_BODY = "pytest -q"


@pytest.mark.parametrize(
    "command",
    [
        f"cat > notes.md <<'EOF'\n{_BODY}\nEOF",
        f"cat <<'EOF' >> notes.md\n{_BODY}\nEOF",
        f"tee a.md b.md <<'EOF'\n{_BODY}\nEOF",
        f"cat <<'EOF'\n{_BODY}\nEOF",
        f"git commit -F - <<'EOF'\n{_BODY}\nEOF",
        f"gh pr create --title t --body-file - <<'EOF'\n{_BODY}\nEOF",
    ],
)
def test_a_prose_body_is_blanked(command: str) -> None:
    assert _BODY not in strip_unrun_heredoc_bodies(command)


@pytest.mark.parametrize(
    "command",
    [
        f"cat > t.sh <<'EOF'\n{_BODY}\nEOF",
        f"tee notes.md t.sh <<'EOF'\n{_BODY}\nEOF",
        f"cat > notes.md <<EOF\n{_BODY}\nEOF",
        f"cat <<'EOF' | bash\n{_BODY}\nEOF",
        f"bash <<'EOF'\n{_BODY}\nEOF",
        f"cat > \"$OUT\" <<'EOF'\n{_BODY}\nEOF",
    ],
)
def test_a_body_something_may_run_is_kept(command: str) -> None:
    assert _BODY in strip_unrun_heredoc_bodies(command)


@pytest.mark.parametrize(
    "command",
    [
        f"cat > notes.md <<'EOF'\n{_BODY}\nEOF",
        f"cat <<'EOF' > notes.md\n{_BODY}\nEOF\necho done",
        f"git commit -F - <<'EOF'\n{_BODY}\nEOF",
    ],
)
def test_never_run_blanks_a_markdown_body_named_once(command: str) -> None:
    assert _BODY not in strip_never_run_heredoc_bodies(command)


@pytest.mark.parametrize(
    "command",
    [
        f"cat > n.md <<'EOF'\n{_BODY}\nEOF\nbash n.md",
        f"cat > n.md <<'EOF'\n{_BODY}\nEOF\n. n.md",
        f"tee a.md b.md <<'EOF'\n{_BODY}\nEOF",
        f"cat > t.sh <<'EOF'\n{_BODY}\nEOF",
        f"bash <<'EOF'\n{_BODY}\nEOF",
        f"cat > n.md <<'EOF'\n{_BODY}\nEOF\nsh n.m?",
        f"cat > n.md <<'EOF'\n{_BODY}\nEOF\nsh n.*",
        f"cat > n.md <<'EOF'\n{_BODY}\nEOF\ncp n.[m]d r.sh; . ./r.sh",
    ],
)
def test_never_run_keeps_a_body_the_command_may_run(command: str) -> None:
    """Review 2 F4: a markdown file the command names again may be run by it."""
    assert _BODY in strip_never_run_heredoc_bodies(command)


@pytest.mark.parametrize(
    "runner",
    [
        "bash $(ls -t | sort -r)",
        "bash `ls -t`",
        "for f in $(ls); do bash $f; done",
        "bash n.{md,}",
        "bash n.m''d",
        'bash n.m""d',
        "bash n.m\\d",
        "bash ${f}d",
        "bash $f",
        "bash <(cat n.m)",
    ],
)
def test_never_run_keeps_a_body_a_respelt_word_may_run(runner: str) -> None:
    """A substitution, expansion, brace, quote or escape may spell the ``.md`` file unseen."""
    command = f"cat > n.md <<'EOF'\n{_BODY}\nEOF\n{runner}"
    assert _BODY in strip_never_run_heredoc_bodies(command)


@pytest.mark.parametrize(
    "command",
    [
        f'cat > n.md <<"EOF"\n{_BODY}\nEOF',
        f"cat > n.md <<-'EOF'\n{_BODY}\nEOF",
        f"cat <<'EOF' > n.md\n{_BODY}\nEOF\necho done",
    ],
)
def test_never_run_ignores_the_quotes_of_the_heredoc_delimiter(command: str) -> None:
    """The delimiter's own quotes respell no file name, so they keep nothing."""
    assert _BODY not in strip_never_run_heredoc_bodies(command)
