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

    def test_a_directory_destination_expands_to_the_file_actually_written(
        self, tmp_path: Path
    ) -> None:
        """`cp a.py somedir` writes `somedir/a.py` — a path we CAN name exactly.

        Found by differential-testing against a real shell: bash wrote
        `adir/src.txt` while this returned nothing. Declining was safe but
        lossy, and it left a live gap — copying a file INTO a guarded directory
        is the obvious way to reach one without ever naming the file.

        The destination basename comes from the SOURCE, which is why this
        needs the source operands and not just the last one.
        """
        destination = tmp_path / "dest"
        destination.mkdir()

        found = get_bash_write_targets(_bash(f"cp /tmp/a.py {destination}"))

        assert found == [str(destination / "a.py")]

    def test_a_target_directory_flag_expands_each_source(self, tmp_path: Path) -> None:
        """`cp -t DEST src` — destination first, so every operand is a source."""
        destination = tmp_path / "dest"
        destination.mkdir()

        found = get_bash_write_targets(_bash(f"cp -t {destination} /tmp/a.py /tmp/b.py"))

        assert found == [str(destination / "a.py"), str(destination / "b.py")]

    def test_a_multi_source_copy_expands_every_source(self, tmp_path: Path) -> None:
        """`cp a b destdir` — 3+ operands means a directory destination."""
        destination = tmp_path / "destdir"
        destination.mkdir()

        found = get_bash_write_targets(_bash(f"mv /tmp/a.py /tmp/b.py {destination}"))

        assert found == [str(destination / "a.py"), str(destination / "b.py")]

    def test_a_redirect_into_a_directory_still_yields_nothing(self, tmp_path: Path) -> None:
        """`echo x > somedir` is a shell ERROR — it writes nothing at all.

        The expansion above is specific to copy verbs. A redirect has no source
        operand to take a basename from, and bash refuses it outright, so
        inventing a path here would be pure fabrication.
        """
        destination = tmp_path / "dest"
        destination.mkdir()

        assert get_bash_write_targets(_bash(f"echo x > {destination}")) == []

    def test_a_target_directory_flag_yields_nothing_rather_than_the_source(self) -> None:
        """`cp -t DEST src` puts the destination FIRST, so "last operand" lies.

        This returned `/tmp/a.py` — a file the command READS. Naming a read as
        a write is the precise failure the conservative contract exists to
        prevent: a path-keyed guard would judge a file that was never written,
        while the real destination went unmentioned.

        With a destination that does not exist, there is still nothing to name:
        `-t` requires a directory, and bash fails outright when it is missing.
        When the directory DOES exist the sources are expanded instead — see
        `test_a_target_directory_flag_expands_each_source`.
        """
        for command in (
            "cp -t /tmp/nosuchdir-eb9f1 /tmp/a.py",
            "mv --target-directory /tmp/nosuchdir-eb9f1 /tmp/a.py",
            "install -t /tmp/nosuchdir-eb9f1 /tmp/a.py",
        ):
            assert get_bash_write_targets(_bash(command)) == [], command

    def test_a_trailing_slash_destination_is_declined(self) -> None:
        """`cp a.py dest/` names a directory that does not exist here.

        Kept as a decline because the expansion needs the destination to be a
        REAL directory; a trailing slash alone only signals intent.
        """
        assert get_bash_write_targets(_bash("cp /tmp/a.py /tmp/nosuchdir-eb9f1/")) == []


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


class TestAnEscapedQuoteDoesNotExposeProse:
    """Plan 00263: `\\"` inside a double-quoted argument must not end the quote.

    Found live, not by inspection. Within an hour of the two linters being wired
    to Bash-authored files (Plan 00260 Task 3.5), a command was DENIED for a file
    it had not authored: it carried a JSON probe payload whose body MENTIONED
    `cat > untracked/cmp-broken.py`, that file existed, and it contained
    deliberately-invalid Python -- so a real `SyntaxError` about a real file was
    attributed to a command that had only quoted the path.

    The cause is that `shlex(posix=False)` does not process backslash escapes,
    so an escaped quote TERMINATES the quoted region and everything after it is
    read as live shell. That makes the guarantee in
    :class:`TestProseIsNeverAWriteTarget` -- "a quoted string is one token" --
    false for any argument containing `\\"`.

    **The reach is wider than a redirect.** Once the quote is broken, `tee` and
    the copy verbs consume trailing operands, so an ordinary run of prose words
    becomes a list of "written files": the `tee` case below invents `loudly`
    from an adverb. A phantom that is a bare plausible word is worse than a
    malformed one, because a malformed path fails `Path.exists()` and a
    plausible one may not.
    """

    def test_an_escaped_quote_does_not_expose_a_redirect(self) -> None:
        """The measured shape: a JSON payload quoting a heredoc command."""
        command = 'echo "{\\"cmd\\": \\"cat > /workspace/untracked/phantom.py <<EOF\\"}"'
        assert get_bash_write_targets(_bash(command)) == []

    def test_an_escaped_quote_does_not_expose_a_tee(self) -> None:
        """`tee` claims every trailing operand, so prose became two targets."""
        command = 'echo "he said \\"pipe to tee /workspace/phantom.py\\" loudly"'
        assert get_bash_write_targets(_bash(command)) == []

    def test_an_escaped_quote_does_not_expose_a_copy_verb(self) -> None:
        """A copy verb claims its last operand -- here, the word `next`."""
        command = 'echo "run \\"cp /workspace/src.txt /workspace/phantom.py\\" next"'
        assert get_bash_write_targets(_bash(command)) == []

    def test_a_backslash_escaped_space_names_the_real_file(self) -> None:
        """Not a phantom but its mirror: the genuine write was MISSED.

        `sp\\ ace.txt` is one path to bash. Unprocessed escapes split it in two,
        so the accessor reported the fragment `sp\\` -- a file nothing writes --
        while missing `sp ace.txt`, which bash really wrote. An overclaim and a
        miss from a single defect.
        """
        assert get_bash_write_targets(_bash("echo hi > /workspace/sp\\ ace.txt")) == [
            "/workspace/sp ace.txt"
        ]


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

    def test_prose_in_a_scanned_body_CAN_yield_a_phantom_target(self) -> None:
        """The honest cost of `include_heredoc_bodies`, pinned rather than hidden.

        Found by differential-testing against a real shell: bash wrote only
        `notes.md`, while this also reported `somewhere` from the body text
        `route out > somewhere`. Nothing distinguishes a script being authored
        from prose containing a redirect, so scanning bodies necessarily
        produces a SUPERSET.

        The sibling test below passed while missing this, because it supplied
        no `cwd` and the relative target was declined for THAT reason. Real
        events always carry a cwd, so the test agreed with the code and both
        were wrong about the contract.

        This is safe only because the one caller filters every candidate by
        path before acting. Recorded here so the next caller sees the cost
        before opting in.
        """
        command = "cat > /tmp/notes.md <<'EOF'\nroute out > somewhere\nEOF"

        found = get_bash_write_targets(_bash(command, cwd="/repo"), include_heredoc_bodies=True)

        assert found == ["/tmp/notes.md", "/repo/somewhere"]

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
