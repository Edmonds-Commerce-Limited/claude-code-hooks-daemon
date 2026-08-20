"""`get_written_file_paths` — the accessor a CONTENT guard should use.

Plan 00260 Task 3.5. `get_file_path` answers "which file did Write/Edit touch?"
and `get_bash_write_targets` answers "which files does this Bash command write?".
A content guard — a linter, a syntax check — wants the union of those two, and
every handler that wants it would otherwise re-derive the same tool-name switch.

**The interesting part is what it deliberately EXCLUDES.** For Bash it returns
only the paths the command AUTHORS content into — redirects, `tee`, heredocs —
and never the ones it merely RELOCATES with `cp`/`mv`/`install`/`dd`.

The distinction is not cosmetic, because these handlers DENY. `cp broken.py
copy.py` writes `copy.py`, so a location guard must see it: copying INTO a
guarded directory is a real bypass. But a linter denying that copy would be
reporting a fault the command did not introduce — the content was already on
disk, already broken, and already past (or around) whatever check should have
caught it. Blaming the copy is blaming the messenger, and the agent's only
remedy would be to fix a file it never chose to write.

So: location guards take every route (`get_bash_write_targets`), content guards
take the authoring routes only (this function).
"""

from __future__ import annotations

from claude_code_hooks_daemon.core.utils import get_written_file_paths


def _bash(command: str, cwd: str = "/repo") -> dict[str, object]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd}


class TestWriteAndEditAreUnchanged:
    """The Write/Edit answer must be exactly what `get_file_path` already gave."""

    def test_write_yields_its_one_file_path(self) -> None:
        payload = {"tool_name": "Write", "tool_input": {"file_path": "/repo/a.py"}}
        assert get_written_file_paths(payload) == ["/repo/a.py"]

    def test_edit_yields_its_one_file_path(self) -> None:
        payload = {"tool_name": "Edit", "tool_input": {"file_path": "/repo/b.py"}}
        assert get_written_file_paths(payload) == ["/repo/b.py"]

    def test_write_without_a_path_yields_nothing(self) -> None:
        assert get_written_file_paths({"tool_name": "Write", "tool_input": {}}) == []

    def test_an_unrelated_tool_yields_nothing(self) -> None:
        payload = {"tool_name": "Read", "tool_input": {"file_path": "/repo/a.py"}}
        assert get_written_file_paths(payload) == []


class TestBashAuthoringRoutesAreIncluded:
    """A command that puts NEW content on disk is the linter's business."""

    def test_a_redirect_authors_content(self) -> None:
        assert get_written_file_paths(_bash("echo x > /repo/a.py")) == ["/repo/a.py"]

    def test_an_append_authors_content(self) -> None:
        assert get_written_file_paths(_bash("echo x >> /repo/a.py")) == ["/repo/a.py"]

    def test_a_heredoc_authors_content(self) -> None:
        command = "cat > /repo/a.py <<'EOF'\nimport os\nEOF"
        assert get_written_file_paths(_bash(command)) == ["/repo/a.py"]

    def test_tee_authors_content_into_every_operand(self) -> None:
        found = get_written_file_paths(_bash("echo x | tee /repo/a.py /repo/b.py"))
        assert found == ["/repo/a.py", "/repo/b.py"]

    def test_a_relative_target_resolves_against_the_event_cwd(self) -> None:
        assert get_written_file_paths(_bash("echo x > a.py", cwd="/repo")) == ["/repo/a.py"]


class TestBashRelocationRoutesAreExcluded:
    """Moving existing bytes is not authoring them, and must not be linted.

    Each of these DOES write a file, and `get_bash_write_targets` reports it —
    that is what the memory-path guard needs. A denying content guard must not
    see it, or an agent gets blamed for a defect it did not write.
    """

    def test_cp_is_not_an_authoring_route(self) -> None:
        assert get_written_file_paths(_bash("cp /repo/a.py /repo/b.py")) == []

    def test_mv_is_not_an_authoring_route(self) -> None:
        assert get_written_file_paths(_bash("mv /repo/a.py /repo/b.py")) == []

    def test_install_is_not_an_authoring_route(self) -> None:
        assert get_written_file_paths(_bash("install -m 644 /repo/a.py /repo/b.py")) == []

    def test_dd_is_not_an_authoring_route(self) -> None:
        assert get_written_file_paths(_bash("dd if=/repo/a.py of=/repo/b.py")) == []

    def test_a_copy_alongside_a_redirect_yields_only_the_redirect(self) -> None:
        """The authoring half is still linted; the relocation half is still not."""
        command = "cp /repo/a.py /repo/b.py && echo x > /repo/c.py"
        assert get_written_file_paths(_bash(command)) == ["/repo/c.py"]


class TestProseIsNeverATarget:
    """Inherited from the strict contract, and worth pinning at THIS boundary too.

    A denying handler acting on a phantom path is the worst outcome available,
    so the heredoc-body superset must NOT be in play here.
    """

    def test_an_arrow_inside_a_quoted_string_is_not_a_redirect(self) -> None:
        assert get_written_file_paths(_bash("echo 'the arrow > file thing'")) == []

    def test_a_redirect_inside_a_quoted_heredoc_body_is_not_a_target(self) -> None:
        command = "cat > /repo/notes.md <<'EOF'\nroute out > somewhere\nEOF"
        assert get_written_file_paths(_bash(command)) == ["/repo/notes.md"]

    def test_an_unresolvable_variable_target_yields_nothing(self) -> None:
        assert get_written_file_paths(_bash('echo x > "$OUT"')) == []
