"""Tests for bash_file_writes: every path a Bash command writes, by any route (Plan 00461).

The shell grammar shows redirects, ``tee`` and copy verbs; this helper adds the
writes that grammar cannot show — an in-place editor, a program handed to an
interpreter (inline, on a heredoc, or behind a wrapper), a patch, a link — and
reports the directories the command changes into, because a relative path after
a ``cd`` cannot be placed. Destinations stay RAW: placing them is the caller's
decision, and a DENY guard fails closed on the ones it cannot place.
"""

import shlex
from pathlib import Path

import pytest

from claude_code_hooks_daemon.handlers.utils.bash_file_writes import bash_file_writes
from claude_code_hooks_daemon.utils.path_predicates import TextOrReason, read_text_or_reason

TARGET = "docs/target.md"


def _writes(command: str, cwd: Path | None = None) -> tuple[str, ...]:
    return bash_file_writes(command, str(cwd) if cwd else None, read_text_or_reason).destinations


class TestShellGrammar:
    def test_redirect_tee_and_copy(self) -> None:
        command = "echo a > one.md && echo b | tee -a two.md; cp x.md three.md"
        assert _writes(command) == ("one.md", "two.md", "three.md")

    def test_git_relocations_are_not_writes(self) -> None:
        assert _writes("git mv a.md b.md") == ()

    def test_a_redirect_on_a_git_stage_still_is(self) -> None:
        assert _writes("git show HEAD:a.md > a.md") == ("a.md",)

    def test_an_expansion_stays_raw(self) -> None:
        assert _writes("echo x >> dir/*.md") == ("dir/*.md",)


class TestDirectories:
    @pytest.mark.parametrize(
        "command",
        ["cd some/dir && echo x > f.md", "(cd some/dir && echo x > f.md)", "pushd some/dir; ls"],
    )
    def test_cd_and_pushd_are_reported(self, command: str) -> None:
        assert bash_file_writes(command, None, read_text_or_reason).directories == ("some/dir",)

    def test_a_flag_to_cd_is_not_the_directory(self) -> None:
        assert bash_file_writes("cd -P some/dir", None, read_text_or_reason).directories == (
            "some/dir",
        )


class TestInPlaceEditors:
    @pytest.mark.parametrize(
        "command",
        [
            f"sed -i 's/a/b/' {TARGET}",
            f"sed -Ei 's/a/b/' {TARGET}",
            f"sed --in-place=.bak 's/a/b/' {TARGET}",
            f"perl -pi -e 's/a/b/' {TARGET}",
            f"ruby -pi -e 'x' {TARGET}",
            f"awk -i inplace '{{print}}' {TARGET}",
            f"gawk -iinplace '{{print}}' {TARGET}",
            f"gawk --include=inplace '{{print}}' {TARGET}",
        ],
    )
    def test_in_place(self, command: str) -> None:
        assert _writes(command) == (TARGET,)

    @pytest.mark.parametrize(
        "command",
        [
            f"sed -n '1,5p' {TARGET}",
            f"sed -e 's/a/b/' {TARGET}",
            f"perl -Ilib script.pl {TARGET}",
            f"perl -Mlib=x script.pl {TARGET}",
            f"ruby -Ilib x.rb {TARGET}",
            f"awk -v n=1 '{{print}}' {TARGET}",
        ],
    )
    def test_not_in_place(self, command: str) -> None:
        assert _writes(command) == ()


class TestPrograms:
    @pytest.mark.parametrize(
        "command",
        [
            f"python3 -c \"open('{TARGET}', 'a').write('x')\"",
            f"python3 -c \"open('{TARGET}', mode='w')\"",
            f"python3 -c \"from pathlib import Path; Path('{TARGET}').write_text('x')\"",
            f"python3 -c \"from pathlib import Path; Path('{TARGET}').open('a')\"",
            f"python3 -c \"import shutil; shutil.copy('x', '{TARGET}')\"",
            f"node -e \"require('fs').appendFileSync('{TARGET}', 'x')\"",
            f"ruby -e \"File.write('{TARGET}', 'x')\"",
            f"ruby -e \"File.open('{TARGET}', 'a') {{ |f| f << 'x' }}\"",
            f'perl -e \'open(my $f, ">>", "{TARGET}")\'',
            f"perl -e 'open(F, \">>{TARGET}\")'",
            f"awk '{{print > \"{TARGET}\"}}' in.txt",
        ],
    )
    def test_a_write_tied_to_the_path(self, command: str) -> None:
        assert _writes(command) == (TARGET,)

    @pytest.mark.parametrize(
        "command",
        [
            f"python3 -c \"print(open('{TARGET}').read())\"",
            f"python3 -c \"import sys; sys.stdout.write(open('{TARGET}').read())\"",
            f"python3 -c \"print(len(open('{TARGET}').read()) > 3)\"",
            f"awk 'NR>=1 && NR<=20' {TARGET}",
            f"node -e \"require('fs').readFileSync('{TARGET}')\"",
        ],
    )
    def test_a_read_is_not_a_write(self, command: str) -> None:
        assert _writes(command) == ()

    def test_an_untied_sink_fails_closed_on_every_named_markdown_path(self) -> None:
        """The path reaches the sink through a variable, which is not followed."""
        command = f"python3 -c \"p = '{TARGET}'; open(p, 'a').write('x')\""
        assert _writes(command) == (TARGET,)

    def test_a_shell_program_is_analysed_as_a_command(self) -> None:
        assert _writes(f'bash -c "wc -l {TARGET} > out.txt"') == ("out.txt",)

    def test_nested_shell_programs_are_followed(self) -> None:
        assert _writes(f"sh -c \"bash -c 'echo x >> {TARGET}'\"") == (TARGET,)


class TestWrappers:
    @pytest.mark.parametrize(
        "command",
        [
            f"timeout 5 sed -i 's/a/b/' {TARGET}",
            f"timeout -s KILL 5m sed -i 's/a/b/' {TARGET}",
            f"nohup sed -i 's/a/b/' {TARGET}",
            f"nice -n 5 sed -i 's/a/b/' {TARGET}",
            f"stdbuf -oL sed -i 's/a/b/' {TARGET}",
            f"time sed -i 's/a/b/' {TARGET}",
            f"sudo -u root sed -i 's/a/b/' {TARGET}",
            f"FOO=1 env BAR=2 sed -i 's/a/b/' {TARGET}",
            f"uv run python -c \"open('{TARGET}', 'a')\"",
            f"uv run --with rich python -c \"open('{TARGET}', 'a')\"",
            f"poetry run python -c \"open('{TARGET}', 'a')\"",
        ],
    )
    def test_the_wrapped_command_is_judged(self, command: str) -> None:
        assert _writes(command) == (TARGET,)


class TestHeredocPrograms:
    @pytest.mark.parametrize(
        "command",
        [
            f"python3 - <<'PY'\nopen('{TARGET}', 'a').write('x')\nPY",
            f"python3 <<EOF\nopen('{TARGET}', 'a').write('x')\nEOF",
            f"bash <<'SH'\necho x >> {TARGET}\nSH",
            f"cat <<'PY' | python3\nopen('{TARGET}', 'a').write('x')\nPY",
        ],
    )
    def test_a_program_on_stdin_is_analysed(self, command: str) -> None:
        assert _writes(command) == (TARGET,)

    @pytest.mark.parametrize(
        "command",
        [
            f"cat > notes.md <<'EOF'\necho x >> {TARGET}\nEOF",
            f"cat > notes.md <<EOF\npython3 -c \"open('{TARGET}', 'a')\"\nEOF",
            f"python3 script.py <<'EOF'\nopen('{TARGET}', 'a')\nEOF",
            f"python3 -c 'import sys' <<'EOF'\nopen('{TARGET}', 'a')\nEOF",
        ],
    )
    def test_a_body_that_is_data_is_not(self, command: str) -> None:
        assert TARGET not in _writes(command)


class TestOtherWriters:
    @pytest.mark.parametrize(
        "command",
        [
            f"ln -sf /tmp/x {TARGET}",
            f"rsync -a src.md {TARGET}",
            f"echo x | sponge -a {TARGET}",
            f"patch {TARGET} fix.diff",
            f"patch -o {TARGET} orig.md fix.diff",
        ],
    )
    def test_writes_its_destination(self, command: str) -> None:
        assert TARGET in _writes(command)

    def test_ln_into_a_target_directory_names_no_file(self) -> None:
        assert _writes("ln -s -t somedir /tmp/x") == ()


class TestPatches:
    @pytest.fixture
    def cwd(self, tmp_path: Path) -> Path:
        (tmp_path / "fix.patch").write_text(
            f"diff --git a/{TARGET} b/{TARGET}\n--- a/{TARGET}\n+++ b/{TARGET}\n"
            "@@ -1 +1,2 @@\n x\n+y\n"
            "--- a/gone.md\n+++ /dev/null\n"
        )
        return tmp_path

    @pytest.mark.parametrize(
        "command",
        [
            "git apply fix.patch",
            "git -C . apply --index fix.patch",
            "patch -p1 < fix.patch",
            "patch -p1 -i fix.patch",
            "patch -p1 --input=fix.patch",
        ],
    )
    def test_the_patched_files_are_written(self, cwd: Path, command: str) -> None:
        assert _writes(command, cwd) == (TARGET,)

    def test_an_attached_stdin_redirect_and_an_absolute_patch(self, cwd: Path) -> None:
        assert _writes("patch -p1 <fix.patch", cwd) == (TARGET,)
        assert _writes(f"git apply {cwd / 'fix.patch'}") == (TARGET,)

    def test_an_unreadable_patch_names_nothing(self, cwd: Path) -> None:
        def refuse(path: Path) -> TextOrReason:
            return TextOrReason(reason="[Errno 13] Permission denied")

        result = bash_file_writes("git apply fix.patch", str(cwd), refuse)
        assert result.destinations == ()

    def test_a_patch_path_needing_expansion_is_not_read(self, cwd: Path) -> None:
        assert _writes("git apply $P", cwd) == ()

    def test_a_relative_patch_without_cwd_is_not_read(self) -> None:
        assert _writes("git apply fix.patch") == ()


class TestShapes:
    """Command shapes the analysis must walk without losing or inventing a write."""

    def test_nesting_is_followed_to_a_depth_and_no_further(self) -> None:
        shallow = f"echo x >> {TARGET}"
        for _ in range(3):
            shallow = "bash -c " + shlex.quote(shallow)
        deep = shallow
        for _ in range(3):
            deep = "bash -c " + shlex.quote(deep)
        assert _writes(shallow) == (TARGET,)
        assert _writes(deep) == ()

    @pytest.mark.parametrize("command", ["FOO=1", "timeout 5", "nohup", "> out.txt"])
    def test_a_stage_with_no_command_names_nothing_extra(self, command: str) -> None:
        assert TARGET not in _writes(command)

    def test_a_redirect_before_the_command_does_not_hide_it(self) -> None:
        assert _writes(f"2>/dev/null sed -i 's/a/b/' {TARGET}") == ("/dev/null", TARGET)

    def test_double_dash_ends_the_flags(self) -> None:
        assert _writes(f"sed -i -e 's/a/b/' -- {TARGET}") == (TARGET,)

    @pytest.mark.parametrize(
        "command",
        [
            f"node --eval \"require('fs').writeFileSync('{TARGET}', 'x')\"",
            f"gawk --source '{{print > \"{TARGET}\"}}' in.txt",
            f"gawk -i inplace -f prog.awk {TARGET}",
            f"gawk -i inplace -e '{{print}}' {TARGET}",
        ],
    )
    def test_long_and_file_program_forms(self, command: str) -> None:
        assert TARGET in _writes(command)

    @pytest.mark.parametrize(
        "command",
        [
            f"awk -f prog.awk {TARGET}",
            f"python3 -c \"open('{TARGET}', 'r')\"",
            f"python3 -c \"from pathlib import Path; Path('{TARGET}').open('r')\"",
        ],
    )
    def test_no_write(self, command: str) -> None:
        assert _writes(command) == ()


class TestHeredocReceivers:
    @pytest.mark.parametrize(
        "command",
        [
            f"echo start; python3 - <<'PY'\nopen('{TARGET}', 'a')\nPY",
            f"cat <<'PY' | cat | python3\nopen('{TARGET}', 'a')\nPY",
        ],
    )
    def test_the_receiving_interpreter_is_found(self, command: str) -> None:
        assert _writes(command) == (TARGET,)

    @pytest.mark.parametrize(
        "command",
        [
            f"grep x <<'EOF' | python3\nopen('{TARGET}', 'a')\nEOF",
            f"cat header.txt - <<'EOF' | python3\nopen('{TARGET}', 'a')\nEOF",
            f"python3 -m json.tool <<'EOF'\nopen('{TARGET}', 'a')\nEOF",
            f"awk '{{print}}' <<'EOF'\nprint > \"{TARGET}\"\nEOF",
            f"FOO=1 <<'EOF'\nopen('{TARGET}', 'a')\nEOF",
        ],
    )
    def test_a_body_that_does_not_reach_an_interpreter_as_its_program(self, command: str) -> None:
        assert TARGET not in _writes(command)


class TestUnparseableText:
    def test_an_unbalanced_quote_names_nothing(self) -> None:
        assert _writes(f"python3 -c \"open('{TARGET}', 'a')") == ()

    def test_a_stage_shlex_rejects_still_yields_its_words(self) -> None:
        command = f"sed -i 's/a/b/' {TARGET} && echo $'it\\'s done'"
        assert _writes(command) == (TARGET,)
