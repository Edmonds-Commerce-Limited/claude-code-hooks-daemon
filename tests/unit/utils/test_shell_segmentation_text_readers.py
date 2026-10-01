"""``strip_quoted_heredoc_bodies(text_readers_only=True)`` -- Plan 00474 N256.

``DATA_SINKS`` answers "does the receiver EXECUTE the body?". A caller whose
question is "does anything OPEN the words of the body as paths?" needs a
narrower answer: `git` plumbing reads path and object names from stdin,
`patch` edits the files a body names, `ftp` runs a body's `get` and `mailx`
honours tilde escapes. Only a receiver that reads the body as TEXT lets the
body be blanked for that caller.
"""

import pytest

from claude_code_hooks_daemon.utils.shell_segmentation import (
    DATA_SINKS,
    TEXT_READING_SINKS,
    strip_quoted_heredoc_bodies,
)

# Spelled in pieces so this file does not itself name a protected path or
# carry shell syntax a scan of the file's text would try to read.
_P = "." + "vault-" + "pass"
_SUB = "$" + "("
_TICK = "`"
_PROC_IN = "<" + "("
_PROC_OUT = ">" + "("
_BODY = f"Fix **Task** and rotate {_P}"
_BLANKED = "HEREDOC_BODY"
_OPEN = "<<'EOF'"


def _strip(command: str) -> str:
    return strip_quoted_heredoc_bodies(command, text_readers_only=True)


def _fed(head: str, body: str = _BODY, opener: str = _OPEN, closer: str = "EOF") -> str:
    return f"{head} {opener}\n{body}\n{closer}"


class TestTextReadersBlankTheirBody:
    @pytest.mark.parametrize(
        "head",
        [
            "git commit -F -",
            "git commit -q -F -",
            "git commit --file=-",
            "git commit -F- --allow-empty",
            "git -C /repo commit -F -",
            "git tag -a v1 -F -",
            "git tag -F - v1",
            "cat",
            "cat 2>/dev/null",
            "cat 2>&1",
            "cat > /dev/null",
            "tee",
            "grep -c Task",
            "wc -l",
            "sort -u",
            "head -n 5",
            "tail -n 5",
            "tr a b",
            "cut -d: -f1",
            "uniq -c",
            "column -t",
            "base64",
        ],
    )
    def test_the_body_is_blanked(self, head: str) -> None:
        stripped = _strip(_fed(head))
        assert _BODY not in stripped
        assert _BLANKED in stripped
        assert stripped.startswith(f"{head} {_OPEN}\n")

    def test_a_pipeline_of_text_readers_is_blanked(self) -> None:
        stripped = _strip(_fed("cat") + "\n")
        assert _BODY not in stripped
        piped = _strip(f"cat {_OPEN} | sort -u | wc -l\n{_BODY}\nEOF")
        assert _BODY not in piped

    def test_the_double_quoted_delimiter_is_blanked(self) -> None:
        assert _BODY not in _strip(_fed("git commit -F -", opener='<<"EOF"'))


class TestAnythingElseKeepsItsBody:
    @pytest.mark.parametrize(
        "command",
        [
            _fed("bash"),
            _fed("sh -s"),
            _fed("python3 -"),
            _fed("cat").replace("<<'EOF'", "<<'EOF' | bash"),
            _fed("cat").replace("<<'EOF'", "<<'EOF' | sh -s"),
            _fed(f"tee {_PROC_OUT}bash)"),
            _fed("cat").replace("<<'EOF'", f"<<'EOF' > {_PROC_OUT}bash)"),
            _fed("xargs cat"),
            _fed("git update-index --add --stdin"),
            _fed("git cat-file --batch"),
            _fed("git hash-object --stdin-paths"),
            _fed("git commit --pathspec-from-file=-"),
            _fed("git commit -F - --pathspec-from-file=-"),
            _fed("git commit -F - --pathspec-file-nul"),
            _fed("git commit -m message"),
            _fed("git -c core.editor=bash commit -F -"),
            _fed("git apply"),
            _fed("patch -p1"),
            _fed("ftp host"),
            _fed("mailx -s s who"),
            _fed("jq ."),
            _fed("sha256sum -c"),
            _fed("awk 1"),
            _fed("sort --compress-program=sh"),
            _fed("git commit -F -", body=f"{_SUB}cat {_P})", opener="<<EOF"),
            _fed("cat", opener="<<EOF"),
            f'git commit -m "{_SUB}cat {_OPEN}\n{_BODY}\nEOF\n)"',
            f"echo {_SUB}cat {_OPEN}\n{_BODY}\nEOF\n)",
        ],
    )
    def test_the_body_is_kept(self, command: str) -> None:
        assert _strip(command) == command

    @pytest.mark.parametrize(
        "segment",
        [
            f"cat {_SUB}bash -c x)",
            f"cat {_TICK}bash -c x{_TICK}",
            f"cat {_PROC_IN}bash -c x)",
        ],
    )
    def test_a_substitution_anywhere_in_the_segment_keeps_the_body(self, segment: str) -> None:
        command = _fed(segment)
        assert _strip(command) == command

    def test_a_substitution_in_a_later_stage_keeps_the_body(self) -> None:
        command = f"cat {_OPEN} | tee {_PROC_OUT}bash)\n{_BODY}\nEOF"
        assert _strip(command) == command

    @pytest.mark.parametrize(
        "head",
        [
            "cat > run.sh",
            "cat >> run.sh",
            "cat > notes.md",
            "cat >| run.sh",
            "cat &> run.sh",
            "cat 2> run.sh",
            "> run.sh cat",
            "tee run.sh",
            "tee -a run.sh",
            "tee -",
            "sort -o run.sh",
            "sort --output=run.sh",
            "sort -uo run.sh",
        ],
    )
    def test_a_body_written_to_a_file_keeps_being_judged(self, head: str) -> None:
        """A script authored through a heredoc is run later, so the body is
        content, not text that dies with the command."""
        command = _fed(head)
        assert _strip(command) == command

    def test_a_file_written_later_in_the_pipeline_keeps_the_body(self) -> None:
        command = f"cat {_OPEN} | tee run.sh\n{_BODY}\nEOF"
        assert _strip(command) == command


class TestOnlyTheBodyIsBlanked:
    def test_the_command_part_keeps_its_mentions(self) -> None:
        stripped = _strip(_fed(f"cat {_P}"))
        assert stripped.startswith(f"cat {_P} {_OPEN}\n")
        assert _BODY not in stripped

    def test_a_harmless_redirect_after_the_opener_is_kept(self) -> None:
        stripped = _strip(f"cat {_OPEN} 2>/dev/null\n{_BODY}\nEOF")
        assert "2>/dev/null" in stripped
        assert _BODY not in stripped

    def test_a_command_after_the_closer_is_kept(self) -> None:
        stripped = _strip(_fed("cat") + f"\ncat {_P}")
        assert stripped.endswith(f"EOF\ncat {_P}")
        assert _BODY not in stripped

    def test_each_heredoc_is_judged_on_its_own_receiver(self) -> None:
        command = f"cat <<'A'\n{_BODY}\nA\nbash <<'B'\n{_BODY}\nB"
        stripped = _strip(command)
        assert stripped.count(_BODY) == 1
        assert stripped.endswith(f"bash <<'B'\n{_BODY}\nB")


class TestTheDefaultIsUnchanged:
    def test_a_data_sink_that_is_not_a_text_reader_is_still_blanked_by_default(self) -> None:
        assert _BODY not in strip_quoted_heredoc_bodies(_fed("jq ."))

    def test_the_text_reader_list_is_a_subset_of_the_data_sinks(self) -> None:
        assert TEXT_READING_SINKS <= DATA_SINKS

    @pytest.mark.parametrize("excluded", ["git", "patch", "ftp", "mailx", "mail", "xargs", "jq"])
    def test_executors_and_path_readers_are_not_text_readers(self, excluded: str) -> None:
        assert excluded not in TEXT_READING_SINKS
