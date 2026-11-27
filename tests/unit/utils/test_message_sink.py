"""Ledger 00474 N744 / N760: the teamchat message-verb sink grammar.

``message_sink_view`` answers one question: is the WHOLE command one plain
teamchat message-verb statement whose message arrives on stdin (a quoted
heredoc, a single-quoted here-string, or one literal ``printf``/``echo``
piped in)? If so it returns the command with the message removed, so the
teamchat words themselves are still judged; otherwise None, and nothing is
relaxed.

Invented names only; nothing here names a real protected file.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.message_sink import MESSAGE_SINK_VERBS, message_sink_view

_BODY = "prose that quotes a glob such as x.y*z and a/b/** and a name like k_e_y"


class TestTheVerbList:
    def test_exactly_the_message_verbs(self) -> None:
        assert MESSAGE_SINK_VERBS == frozenset(
            {"say", "reply", "report", "thread", "ask-human", "close", "retitle"}
        )


class TestAcceptedShapes:
    @pytest.mark.parametrize(
        ("command", "view"),
        [
            (f"teamchat report <<'EOF'\n{_BODY}\nEOF", "teamchat report"),
            (f"teamchat report <<'EOF'\n{_BODY}\nEOF\n", "teamchat report"),
            (f'teamchat say --to lead <<"MSG"\n{_BODY}\nMSG', "teamchat say --to lead"),
            (
                f"teamchat reply ev1 --verb ack <<'EOF'\n{_BODY}\nEOF",
                "teamchat reply ev1 --verb ack",
            ),
            (f"teamchat thread Q3 --note <<'EOF'\n{_BODY}\nEOF", "teamchat thread Q3 --note"),
            (f"teamchat close Q1 Q2 <<'EOF'\n{_BODY}\nEOF", "teamchat close Q1 Q2"),
            (f"teamchat retitle Q4 <<'EOF'\n{_BODY}\nEOF", "teamchat retitle Q4"),
            (
                f"teamchat ask-human --for a,b --remind-after 600 <<'EOF'\n{_BODY}\nEOF",
                "teamchat ask-human --for a,b --remind-after 600",
            ),
            (f"teamchat say --to-coordinator <<< '{_BODY}'", "teamchat say --to-coordinator"),
            (f"teamchat report <<<'{_BODY}'", "teamchat report"),
            (f"printf '%s\\n' 'head' '{_BODY}' | teamchat report", "teamchat report"),
            (f"printf '{_BODY}\\n' | teamchat say --to lead", "teamchat say --to lead"),
            (f'echo "{_BODY}" | teamchat report', "teamchat report"),
            (f"echo '{_BODY}' | teamchat reply ev9", "teamchat reply ev9"),
            (f"teamchat report --team core <<'EOF'\n{_BODY}\nEOF", "teamchat report --team core"),
            (f"teamchat say --to=lead <<'EOF'\n{_BODY}\nEOF", "teamchat say --to=lead"),
        ],
    )
    def test_shape_gives_the_view(self, command: str, view: str) -> None:
        assert message_sink_view(command) == view

    def test_a_body_line_that_only_starts_like_the_closer_is_body(self) -> None:
        command = f"teamchat report <<'EOF'\nEOF but not the closer\n{_BODY}\nEOF"
        assert message_sink_view(command) == "teamchat report"

    def test_a_reference_argument_stays_in_the_view(self) -> None:
        command = "teamchat reply ev1 --verb done --ref path:o/r@abc:d/f.txt <<'EOF'\nok\nEOF"
        assert message_sink_view(command) == (
            "teamchat reply ev1 --verb done --ref path:o/r@abc:d/f.txt"
        )


class TestRejectedShapes:
    """Each returns None: the command is judged whole, exactly as before."""

    @pytest.mark.parametrize(
        "command",
        [
            # Not a message verb, or not teamchat.
            f"teamchat run --plain -- bash <<'EOF'\n{_BODY}\nEOF",
            f"teamchat ping review --to a <<'EOF'\n{_BODY}\nEOF",
            f"teamchat send general <<'EOF'\n{_BODY}\nEOF",
            f"teamchat history <<'EOF'\n{_BODY}\nEOF",
            f"/usr/bin/teamchat report <<'EOF'\n{_BODY}\nEOF",
            f"command teamchat report <<'EOF'\n{_BODY}\nEOF",
            f"X=1 teamchat report <<'EOF'\n{_BODY}\nEOF",
            f"cat <<'EOF'\n{_BODY}\nEOF",
            f"tee out.txt <<'EOF'\n{_BODY}\nEOF",
            "teamchat report",
            # An unknown flag.
            f"teamchat report --file x <<'EOF'\n{_BODY}\nEOF",
            f"teamchat say --body-file=x <<'EOF'\n{_BODY}\nEOF",
            # An unquoted or dashed heredoc: bash expands or strips the body.
            f"teamchat report <<EOF\n{_BODY}\nEOF",
            f"teamchat report <<-'EOF'\n{_BODY}\nEOF",
            # No closer, or anything after it.
            f"teamchat report <<'EOF'\n{_BODY}\n",
            f"teamchat report <<'EOF'\n{_BODY}\nEOF\ncat x",
            f"teamchat report <<'EOF'\n{_BODY}\nEOF\n\necho done",
            # Words after the heredoc operator, or a second feed.
            f"teamchat report <<'EOF' --team x\n{_BODY}\nEOF",
            "teamchat report <<'A' <<'B'\nx\nA\ny\nB",
            f"printf 'x' | teamchat report <<'EOF'\n{_BODY}\nEOF",
            # A redirect, chain, pipe out, substitution or expansion anywhere.
            f"teamchat report > out.txt <<'EOF'\n{_BODY}\nEOF",
            f"teamchat report 2>&1 <<'EOF'\n{_BODY}\nEOF",
            "teamchat report < notes.txt",
            f"teamchat report <<'EOF' | bash\n{_BODY}\nEOF",
            f"teamchat report <<'EOF' && cat x\n{_BODY}\nEOF",
            f"teamchat report; teamchat report <<'EOF'\n{_BODY}\nEOF",
            "printf 'x' | teamchat report | bash",
            "printf 'x' | teamchat report > o",
            "printf 'x' | teamchat report && cat y",
            "printf 'x' || teamchat report",
            "printf 'x' |& teamchat report",
            f"teamchat say --to \"$(cat x)\" <<'EOF'\n{_BODY}\nEOF",
            f"teamchat say --to $WHO <<'EOF'\n{_BODY}\nEOF",
            f"teamchat say --to `id` <<'EOF'\n{_BODY}\nEOF",
            f"teamchat say --to a* <<'EOF'\n{_BODY}\nEOF",
            f"teamchat say --to ~x <<'EOF'\n{_BODY}\nEOF",
            f"teamchat say --to a\\ b <<'EOF'\n{_BODY}\nEOF",
            f"teamchat say --to a'b' <<'EOF'\n{_BODY}\nEOF",
            f"teamchat\tsay --to a <<'EOF'\n{_BODY}\nEOF",
            # A here-string that bash would expand.
            'teamchat report <<< "$(cat x)"',
            'teamchat report <<< "plain"',
            "teamchat report <<< plain",
            "teamchat report <<< 'a' 'b'",
            # A producer that opens, expands or is not a plain literal printer.
            "cat notes.txt | teamchat report",
            "cat <<'EOF' | teamchat report\nx\nEOF",
            "tee x | teamchat report",
            "printf | teamchat report",
            "printf x | teamchat report",
            "printf -v v 'x' | teamchat report",
            "printf '-v' 'v' 'x' | teamchat report",
            "printf '%s' \"$X\" | teamchat report",
            "printf '%s' \"`id`\" | teamchat report",
            "printf '%s' \"a\\b\" | teamchat report",
            "printf '%s' \"hi!\" | teamchat report",
            "echo -e 'x' | teamchat report",
            "echo '-n' 'x' | teamchat report",
            "echo x* | teamchat report",
            "echo 'a'b | teamchat report",
            "printf 'x' > o | teamchat report",
            "printf 'x' 'y' 2>o | teamchat report",
            "(printf 'x') | teamchat report",
            "printf 'x' | printf 'y' | teamchat report",
            # Unterminated quotes.
            "printf 'x | teamchat report",
            f"teamchat say --to 'a <<'EOF'\n{_BODY}\nEOF",
            "",
        ],
    )
    def test_shape_is_not_a_sink(self, command: str) -> None:
        assert message_sink_view(command) is None
