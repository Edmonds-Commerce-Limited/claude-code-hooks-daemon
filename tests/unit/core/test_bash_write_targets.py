"""`get_bash_write_targets` — which files a Bash command actually writes.

Plan 00260 Task 3.1/3.1b. Twenty-two handlers key on the `Write`/`Edit` tools,
so a file reaching disk through Bash is invisible to them. The blindness lives
in one place — `core/utils.py`'s `get_file_path()`/`get_file_content()` return
`None` for any other tool — so the accessor that lifts it belongs beside them
rather than inside any one handler.

**This is NOT "move `markdown_organization._bash_memory_write_target` to a
shared module".** That detector is two unanchored regexes over the raw command
string, and generalising it would have been actively harmful. Measured against
the shapes in `CLAUDE/Plan/00260-*/BASH-BLINDSPOT-MAP.md`, it misses `>|`,
quoted paths containing a space, `dd of=`, `cp`/`mv`/`install`, and every
target after the first for `tee` — and, worse, it FALSE-POSITIVES on prose:
`echo 'the arrow > file thing'` yields the target `file`. It is tolerable today
only because it is filtered through a narrow substring test for memory paths.
Applied to every path in the tree, `lock_file_edit_blocker` would begin denying
commits whose MESSAGE mentions a redirect. That false positive is not
hypothetical — it denied a sub-agent gathering evidence for that very map.

So this uses `shlex` with `punctuation_chars=True`, which makes the prose case
structurally impossible rather than filtered: a quoted string is ONE token, so
a `>` inside it is never an operator.

**The contract is CONSERVATIVE.** A target is returned only when the command
plainly says so. Anything requiring expansion the daemon cannot perform — a
variable target, a glob, a subshell — yields nothing, because a wrong path is
worse than no path: it attributes a write to a file that was never touched, and
a path-keyed guard would then judge the wrong file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.utils import get_bash_write_targets


def _bash(command: str, cwd: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"tool_name": "Bash", "tool_input": {"command": command}}
    if cwd is not None:
        payload["cwd"] = cwd
    return payload


class TestOnlyBashEventsAreExamined:
    """A Write/Edit event has a real `file_path`; this accessor is not for it."""

    @pytest.mark.parametrize("tool", ["Write", "Edit", "Read", "Glob"])
    def test_a_non_bash_tool_yields_nothing(self, tool: str) -> None:
        assert (
            get_bash_write_targets({"tool_name": tool, "tool_input": {"file_path": "/a.py"}}) == []
        )

    def test_an_absent_command_yields_nothing(self) -> None:
        assert get_bash_write_targets({"tool_name": "Bash", "tool_input": {}}) == []

    def test_an_unparseable_command_yields_nothing(self) -> None:
        """An unbalanced quote must not raise out of an accessor."""
        assert get_bash_write_targets(_bash('cat > "unterminated')) == []


class TestRedirectTargets:
    """`>`, `>>` and `>|` are the ordinary shapes."""

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("echo x > /tmp/a.txt", ["/tmp/a.txt"]),
            ("echo x >> /tmp/a.txt", ["/tmp/a.txt"]),
            ("printf x >| /tmp/a.txt", ["/tmp/a.txt"]),
            ("make &> /tmp/all.log", ["/tmp/all.log"]),
            ("make &>> /tmp/all.log", ["/tmp/all.log"]),
            ("cat a.txt>/tmp/b.txt", ["/tmp/b.txt"]),
            ("python3 gen.py 2> /tmp/err.log", ["/tmp/err.log"]),
        ],
    )
    def test_redirects_are_found(self, command: str, expected: list[str]) -> None:
        assert get_bash_write_targets(_bash(command)) == expected

    def test_a_quoted_target_containing_a_space_survives(self) -> None:
        """The regex detector truncated this at the space, yielding `'/tmp/my`."""
        assert get_bash_write_targets(_bash('cat > "/tmp/my file.md"')) == ["/tmp/my file.md"]

    def test_every_target_in_a_compound_command_is_found(self) -> None:
        assert get_bash_write_targets(_bash("echo a > /tmp/1 && echo b > /tmp/2")) == [
            "/tmp/1",
            "/tmp/2",
        ]


class TestTeeAndCopyVerbs:
    """Writes that are not redirects at all."""

    def test_every_tee_target_is_found_not_just_the_first(self) -> None:
        """The regex detector returned only the first, silently losing the rest."""
        assert get_bash_write_targets(_bash("echo hi | tee -a /tmp/a /tmp/b")) == [
            "/tmp/a",
            "/tmp/b",
        ]

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("cp /tmp/a.py /tmp/b.py", ["/tmp/b.py"]),
            ("mv /tmp/a.py /tmp/b.py", ["/tmp/b.py"]),
            ("install -m 644 /tmp/a.md /tmp/b.md", ["/tmp/b.md"]),
            ("dd if=/dev/zero of=/tmp/a.img", ["/tmp/a.img"]),
        ],
    )
    def test_copy_verbs_report_their_destination(self, command: str, expected: list[str]) -> None:
        assert get_bash_write_targets(_bash(command)) == expected

    def test_a_target_directory_flag_yields_nothing_rather_than_the_source(self) -> None:
        """`cp -t DEST src` puts the destination FIRST, so "last operand" lies.

        This returned `/tmp/a.py` — a file the command READS. Naming a read as
        a write is the precise failure the conservative contract exists to
        prevent: a path-keyed guard would judge a file that was never written,
        while the real destination went unmentioned. `-t` also means the
        destination is a directory, so there is no correct single path to
        report and declining is the only right answer.
        """
        for command in (
            "cp -t /tmp/dest /tmp/a.py",
            "mv --target-directory /tmp/dest /tmp/a.py",
            "install -t /tmp/dest /tmp/a.py",
        ):
            assert get_bash_write_targets(_bash(command)) == [], command

    def test_an_existing_directory_destination_is_declined(self, tmp_path: Path) -> None:
        """`cp a.py somedir` writes `somedir/a.py`; the directory is not the file.

        Only reachable by asking the filesystem — `somedir` and `somefile` are
        indistinguishable as strings. One `is_dir()` per candidate is cheap
        next to naming the wrong path.
        """
        destination = tmp_path / "dest"
        destination.mkdir()

        assert get_bash_write_targets(_bash(f"cp /tmp/a.py {destination}")) == []

    def test_a_multi_source_copy_names_no_file(self, tmp_path: Path) -> None:
        """`cp a b destdir` — with 3+ operands the last is necessarily a directory."""
        destination = tmp_path / "destdir"
        destination.mkdir()

        command = f"mv /tmp/a /tmp/b {destination}"

        assert get_bash_write_targets(_bash(command)) == []

    def test_a_directory_destination_is_not_reported_as_the_written_file(self) -> None:
        """`cp a.py src/` writes `src/a.py`, not `src/`.

        Reporting the directory would attribute the write to a path no
        path-keyed guard matches, so it fails safe (a missed write) rather than
        dangerously (the wrong file judged). Recorded as a test so the
        behaviour is a decision rather than an accident.
        """
        assert get_bash_write_targets(_bash("cp /tmp/a.py /tmp/dest/")) == []


class TestProseIsNeverAWriteTarget:
    """The failure that makes a generalised regex unusable."""

    def test_a_redirect_inside_a_quoted_string_is_not_a_target(self) -> None:
        """`echo 'the arrow > file thing'` yielded the target `file`.

        This exact shape denied a sub-agent that was gathering evidence for
        the blind-spot map. `shlex` makes it structurally impossible: the
        quoted string is a single token, so the `>` is never an operator.
        """
        assert get_bash_write_targets(_bash("echo 'the arrow > file thing'")) == []

    def test_a_git_commit_message_mentioning_a_redirect_is_not_a_target(self) -> None:
        assert get_bash_write_targets(_bash("git commit -m 'route stdout > logfile'")) == []

    def test_a_read_is_not_a_write(self) -> None:
        for command in ("cat /tmp/a.txt", "grep foo /tmp/a.txt", "ls -la /tmp"):
            assert get_bash_write_targets(_bash(command)) == [], command


class TestUnresolvableTargetsAreDeclined:
    """A wrong path is worse than no path."""

    @pytest.mark.parametrize(
        "command",
        [
            'cat > "$OUT"',
            "cat > $HOME/notes.md",
            "cat > /tmp/*.txt",
            "echo x > /dev/null",
        ],
    )
    def test_targets_needing_expansion_are_not_reported(self, command: str) -> None:
        assert get_bash_write_targets(_bash(command)) == []


class TestTildeIsExpandedNotDeclined:
    """`~` is the one expansion the daemon can perform exactly.

    Not a nicety — a measured regression. `markdown_organization` blocks writes
    to Claude's auto-memory files, which live at `~/.claude/projects/*/memory/`,
    and its raw-string detector catches the tilde spelling today by substring.
    Declining `~` as "unexpandable" alongside `$VAR` would have silently
    un-enforced that policy for its most natural spelling the moment that
    handler migrated onto this accessor.

    `$HOME/notes.md` stays declined (see `TestUnresolvableTargetsAreDeclined`)
    and that asymmetry is deliberate: a variable's value is the SHELL's, unknown
    to this process, while a leading tilde is HOME by definition.
    """

    def test_a_tilde_memory_path_is_resolved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOME", "/home/someone")

        found = get_bash_write_targets(_bash("cat > ~/.claude/projects/x/memory/y.md"))

        assert found == ["/home/someone/.claude/projects/x/memory/y.md"]

    def test_a_bare_tilde_home_target_is_resolved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOME", "/home/someone")

        assert get_bash_write_targets(_bash("echo x > ~/notes.md")) == ["/home/someone/notes.md"]

    def test_an_unresolvable_user_tilde_is_declined(self) -> None:
        """`~nosuchuser` comes back unchanged; a literal `~` is not a path."""
        found = get_bash_write_targets(_bash("echo x > ~nosuchuser-eb9f1/notes.md"))

        assert found == []


class TestRelativeTargetsResolveAgainstTheEventCwd:
    """A bare `notes.md` means nothing without knowing where the command ran."""

    def test_a_relative_target_is_resolved_against_cwd(self) -> None:
        assert get_bash_write_targets(_bash("echo x > notes/a.md", cwd="/repo")) == [
            "/repo/notes/a.md"
        ]

    def test_a_relative_target_without_cwd_is_declined(self) -> None:
        """Guessing a root would name a real file that was never written."""
        assert get_bash_write_targets(_bash("echo x > notes/a.md")) == []

    def test_an_absolute_target_ignores_cwd(self) -> None:
        assert get_bash_write_targets(_bash("echo x > /tmp/a.md", cwd="/repo")) == ["/tmp/a.md"]


class TestHeredocBodies:
    """A heredoc body is DATA, and whether to read it depends on the caller."""

    _SCRIPT = "cat > /tmp/deploy.sh <<'EOF'\necho x > /tmp/inner.txt\nEOF"

    def test_the_body_is_not_scanned_by_default(self) -> None:
        """Authoring a script that would write later is not writing now."""
        assert get_bash_write_targets(_bash(self._SCRIPT)) == ["/tmp/deploy.sh"]

    def test_the_body_can_be_scanned_when_the_caller_asks(self) -> None:
        """Opt-in, because for a deny-by-default POLICY over-blocking is cheap.

        Not speculative: `markdown_organization` blocks memory writes today by
        regexing the RAW command, so it already catches a heredoc-authored
        script that would write to a memory path. Stripping bodies
        unconditionally would silently REGRESS that, which is why the choice
        belongs to the caller rather than to this function.
        """
        found = get_bash_write_targets(_bash(self._SCRIPT), include_heredoc_bodies=True)

        assert "/tmp/deploy.sh" in found
        assert "/tmp/inner.txt" in found

    def test_a_malformed_body_cannot_destroy_the_real_target(self) -> None:
        """A stray quote in prose must not silently drop the write on line one.

        Measured, not theoretical. Scanning the WHOLE command as one shell
        string means an unbalanced quote anywhere — `he said "hi` in ordinary
        prose — makes `shlex` raise, and the accessor then returns nothing at
        all. The genuine target on the introducing line disappears with it, so
        a policy keyed on that path stops firing. An agent needs no intent to
        trigger this; one typo in a document does it.

        The command and each body are therefore tokenised SEPARATELY: a body
        that cannot be parsed costs only that body.
        """
        command = "cat > /tmp/notes.md <<'EOF'\nhe said \"hi\nEOF"

        assert get_bash_write_targets(_bash(command), include_heredoc_bodies=True) == [
            "/tmp/notes.md"
        ]

    def test_a_body_with_no_write_verb_is_skipped_entirely(self) -> None:
        """Behaviour-neutral, but it is what keeps a large document cheap.

        Tokenising is per-character Python: a 40 KB prose body cost ~25 ms, and
        a dispatched event pays it twice — enough on its own to double the
        whole hook round trip. A body that contains no redirect and no write
        verb cannot name a target, so it is never tokenised. The observable
        contract is unchanged, which is the point.
        """
        body = "a line of ordinary prose about the change\n" * 50
        command = f"cat > /tmp/doc.md <<'EOF'\n{body}EOF"

        assert get_bash_write_targets(_bash(command), include_heredoc_bodies=True) == [
            "/tmp/doc.md"
        ]

    def test_prose_in_a_body_is_still_not_a_target(self) -> None:
        command = "cat > /tmp/notes.md <<'EOF'\nwrite output > somewhere sensible\nEOF"

        assert get_bash_write_targets(_bash(command), include_heredoc_bodies=True) == [
            "/tmp/notes.md"
        ]


class TestOrderAndDuplicates:
    """A stable, de-duplicated list keeps callers simple."""

    def test_targets_keep_command_order(self) -> None:
        assert get_bash_write_targets(_bash("echo a > /tmp/z && echo b > /tmp/a")) == [
            "/tmp/z",
            "/tmp/a",
        ]

    def test_a_repeated_target_is_reported_once(self) -> None:
        assert get_bash_write_targets(_bash("echo a > /tmp/x && echo b >> /tmp/x")) == ["/tmp/x"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
