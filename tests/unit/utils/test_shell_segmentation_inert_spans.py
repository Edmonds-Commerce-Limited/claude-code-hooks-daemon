"""``strip_message_bodies`` / ``strip_inert_spans`` — the shared inert-span scan.

Plan 00377 N7. Blanking a ``-m``/``-F`` value was private to ``pipe_blocker``
while the heredoc half already lived here, so the second handler that needed the
same fact (``destructive_git``) could reach only half of it. That is the split
this module's own docstring exists to prevent: "One scanner, one set of rules,
one place to fix."

Two conditions gate the blanking, both carried over from Plan 00222 rather than
re-derived, because each was added after the unconditional form was measured to
be wrong:

* the owning command must actually TAKE a message, so ``python -m <module>``
  keeps naming a module, and
* the value must not be able to execute, since bash substitutes inside double
  quotes and blanking such a value CONCEALS a live command.
"""

from claude_code_hooks_daemon.utils.shell_segmentation import (
    strip_inert_spans,
    strip_message_bodies,
)

_FORCE = "--" + "force"
_HARD = "--" + "hard"


class TestStripMessageBodies:
    def test_a_single_quoted_message_is_blanked(self) -> None:
        blanked = strip_message_bodies(f"git commit -m 'mentions {_FORCE}'")
        assert _FORCE not in blanked
        assert blanked.startswith("git commit -m ")

    def test_a_double_quoted_prose_message_is_blanked(self) -> None:
        """Double quotes do not stop blanking — only a SUBSTITUTION does."""
        assert _FORCE not in strip_message_bodies(f'git commit -m "mentions {_FORCE}"')

    def test_a_substituting_value_is_left_alone(self) -> None:
        """Bash runs this, so blanking it would hide a real command."""
        command = f'git commit -m "$(git push {_FORCE})"'
        assert strip_message_bodies(command) == command

    def test_a_module_flag_is_not_a_message(self) -> None:
        """`python -m pytest` names a MODULE; blanking it loses the producer."""
        command = "python -m pytest tests/"
        assert strip_message_bodies(command) == command

    def test_a_command_beside_the_message_is_untouched(self) -> None:
        command = f"git commit -m 'ordinary' && git push {_FORCE} origin main"
        blanked = strip_message_bodies(command)
        assert f"git push {_FORCE} origin main" in blanked

    def test_a_command_with_no_message_is_returned_unchanged(self) -> None:
        command = "git status"
        assert strip_message_bodies(command) == command

    def test_an_unquoted_value_does_not_swallow_the_next_command(self) -> None:
        """An unquoted value ends at the separator, not at the next space.

        The bare-word alternative used to be ``\\S+``, and ``\\S`` matches ``&``
        and ``;`` -- so ``git commit -m x&&git reset --hard`` had ``x&&git``
        blanked as though it were prose, handing every downstream guard a
        ``reset --hard`` with no ``git`` in front of it while bash ran both
        commands. The value must stop at the metacharacter that ends it.
        """
        blanked = strip_message_bodies(f"git commit -m x&&git reset {_HARD}")
        assert f"git reset {_HARD}" in blanked

    def test_an_unquoted_value_does_not_swallow_a_semicolon_separated_command(
        self,
    ) -> None:
        blanked = strip_message_bodies("git commit -m x;git clean -fd")
        assert "git clean -fd" in blanked

    def test_an_unquoted_value_is_still_blanked(self) -> None:
        """Narrowing the alternative must not stop it blanking a real value."""
        blanked = strip_message_bodies("git commit -F commit-msg.txt")
        assert "commit-msg.txt" not in blanked


class TestStripInertSpans:
    def test_it_blanks_both_a_message_and_a_quoted_heredoc(self) -> None:
        command = (
            f"git commit -m 'names {_FORCE}' && cat <<'EOF' > notes.md\n"
            f"the body also names {_FORCE}\n"
            "EOF"
        )
        assert _FORCE not in strip_inert_spans(command)

    def test_an_unquoted_heredoc_body_survives(self) -> None:
        """Deliberate: bash expands inside `<<EOF`, so the body can run."""
        command = f"cat <<EOF\n{_FORCE}\nEOF"
        assert _FORCE in strip_inert_spans(command)

    def test_the_heredoc_redirect_target_is_preserved(self) -> None:
        """Blanking a body must remove no evidence but the body."""
        command = "cat <<'EOF' > notes.md\nprose\nEOF"
        assert "> notes.md" in strip_inert_spans(command)

    def test_order_does_not_matter_for_a_message_holding_a_heredoc(self) -> None:
        """The canonical multi-line message idiom is inert as a whole."""
        command = f"git commit -m \"$(cat <<'EOF'\nnames {_FORCE}\nEOF\n)\""
        assert _FORCE not in strip_inert_spans(command)
