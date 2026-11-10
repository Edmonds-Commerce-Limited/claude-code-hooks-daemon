"""strip_unrun_heredoc_bodies: a body nothing runs, now or later (Plan 00478 Task 2.2f)."""

import pytest

from claude_code_hooks_daemon.utils.shell_segmentation import strip_unrun_heredoc_bodies

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
