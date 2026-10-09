"""Verbs that change or remove a file they do not author: ``sed -i``, ``ln``,
``rm``, ``truncate`` and the SOURCE of ``mv`` (Plan 00499).

A guard that makes a path read-only for agents must see every route that alters
it, not only the ones that put new content there. The verbs are opt-in
(``include_mutations``), so the callers that judge what a command AUTHORS or
where it WRITES keep exactly the answers they had.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.utils import (
    get_bash_write_targets,
    get_written_file_paths,
    scan_bash_write_destinations,
    scan_bash_write_targets,
)


def _bash(command: str) -> dict[str, object]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/repo"}


def _mutated(command: str) -> list[str]:
    return scan_bash_write_targets(_bash(command), include_mutations=True).paths


class TestSedInPlace:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("sed -i s/a/b/ f.txt", ["/repo/f.txt"]),
            ("sed -i.bak s/a/b/ f.txt", ["/repo/f.txt"]),
            ("sed -ni p f.txt", ["/repo/f.txt"]),
            ("sed -Ei s/a/b/ f.txt g.txt", ["/repo/f.txt", "/repo/g.txt"]),
            ("sed --in-place s/a/b/ f.txt", ["/repo/f.txt"]),
            ("sed --in-place=.bak s/a/b/ f.txt", ["/repo/f.txt"]),
            ("sed -i -e s/a/b/ -e s/c/d/ f.txt", ["/repo/f.txt"]),
            ("sed -i --expression=s/a/b/ f.txt", ["/repo/f.txt"]),
            ("sed -i -f script.sed f.txt", ["/repo/f.txt"]),
            ("sed -s -i s/a/b/ f.txt", ["/repo/f.txt"]),
            ("echo x && sed -i s/a/b/ f.txt", ["/repo/f.txt"]),
        ],
    )
    def test_names_the_files_edited_in_place(self, command: str, expected: list[str]) -> None:
        assert _mutated(command) == expected

    @pytest.mark.parametrize(
        "command",
        [
            "sed s/a/b/ f.txt",
            "sed -n p f.txt",
            "sed -e s/a/b/ f.txt",
            "sed -E s/a/b/ f.txt",
            "sed --expression=s/a/b/ f.txt",
        ],
    )
    def test_a_read_only_sed_names_nothing(self, command: str) -> None:
        assert _mutated(command) == []

    def test_the_script_is_not_a_file(self) -> None:
        assert "/repo/s/a/b/" not in _mutated("sed -i s/a/b/ f.txt")


class TestLink:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("ln -s target link", ["/repo/link"]),
            ("ln -sf target /repo/dir/link", ["/repo/dir/link"]),
            ("ln target link", ["/repo/link"]),
            ("ln -s -- target link", ["/repo/link"]),
        ],
    )
    def test_names_the_link_that_is_created(self, command: str, expected: list[str]) -> None:
        assert _mutated(command) == expected


class TestRemove:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("rm f.txt", ["/repo/f.txt"]),
            ("rm -rf a b", ["/repo/a", "/repo/b"]),
            ("rm -f -- f.txt", ["/repo/f.txt"]),
            ("rm -v /abs/f.txt", ["/abs/f.txt"]),
            ("echo x; rm f.txt", ["/repo/f.txt"]),
            ("rm f.txt && echo done", ["/repo/f.txt"]),
        ],
    )
    def test_names_every_operand(self, command: str, expected: list[str]) -> None:
        assert _mutated(command) == expected


class TestTruncate:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("truncate -s 0 f.txt", ["/repo/f.txt"]),
            ("truncate -s0 f.txt g.txt", ["/repo/f.txt", "/repo/g.txt"]),
            ("truncate --size=0 f.txt", ["/repo/f.txt"]),
            ("truncate --size 0 f.txt", ["/repo/f.txt"]),
            ("truncate -r ref.txt f.txt", ["/repo/f.txt"]),
            ("truncate -c -s 10 f.txt", ["/repo/f.txt"]),
        ],
    )
    def test_names_the_files_not_the_size_or_reference(
        self, command: str, expected: list[str]
    ) -> None:
        assert _mutated(command) == expected


class TestTouchAndUnlink:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("touch f.txt", ["/repo/f.txt"]),
            ("touch -c f.txt g.txt", ["/repo/f.txt", "/repo/g.txt"]),
            ("touch -d yesterday f.txt", ["/repo/f.txt"]),
            ("touch --date=yesterday f.txt", ["/repo/f.txt"]),
            ("touch -r ref.txt f.txt", ["/repo/f.txt"]),
            ("touch -t 202001010000 f.txt", ["/repo/f.txt"]),
            ("unlink f.txt", ["/repo/f.txt"]),
        ],
    )
    def test_names_the_files_not_the_option_values(self, command: str, expected: list[str]) -> None:
        assert _mutated(command) == expected


class TestCommandPosition:
    """A verb is a command only where a command starts, or after a wrapper."""

    @pytest.mark.parametrize(
        "command",
        [
            "grep rm f.txt",
            "grep -n truncate f.txt",
            "grep touch f.txt",
            "echo unlink f.txt",
            "grep cp a.txt b.txt",
            "cat f.txt | grep rm",
            "git log -- rm f.txt",
        ],
    )
    def test_a_verb_that_is_only_an_argument_names_nothing(self, command: str) -> None:
        assert _mutated(command) == []

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("sudo rm f.txt", ["/repo/f.txt"]),
            ("sudo -u root rm f.txt", ["/repo/f.txt"]),
            ("echo x | xargs rm", []),
            ("echo f.txt | xargs rm f.txt", ["/repo/f.txt"]),
            ("FOO=1 rm f.txt", ["/repo/f.txt"]),
            ("env FOO=1 rm f.txt", ["/repo/f.txt"]),
            ("if true; then rm f.txt; fi", ["/repo/f.txt"]),
            ("(rm f.txt)", ["/repo/f.txt"]),
            ("git rm f.txt", ["/repo/f.txt"]),
            ("git -C /x rm f.txt", ["/repo/f.txt"]),
            ("find . -exec rm f.txt ;", ["/repo/f.txt"]),
            ("true && rm f.txt", ["/repo/f.txt"]),
            ("timeout 5 cp a.txt b.txt", ["/repo/b.txt"]),
        ],
    )
    def test_a_verb_at_the_command_head_or_after_a_wrapper_counts(
        self, command: str, expected: list[str]
    ) -> None:
        assert _mutated(command) == expected


class TestMoveSource:
    def test_the_file_moved_away_is_mutated_and_so_is_the_destination(self) -> None:
        assert _mutated("mv a.txt b.txt") == ["/repo/b.txt", "/repo/a.txt"]

    def test_target_directory_form_names_the_sources(self) -> None:
        assert "/repo/a.txt" in _mutated("mv -t /nonexistent-dir a.txt")

    def test_copy_does_not_mutate_its_source(self) -> None:
        assert _mutated("cp a.txt b.txt") == ["/repo/b.txt"]


class TestDirectories:
    def test_a_removed_directory_is_named(self, tmp_path: Path) -> None:
        (tmp_path / "ccy").mkdir()
        scan = scan_bash_write_targets(
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf ccy"}, "cwd": str(tmp_path)},
            include_mutations=True,
        )
        assert scan.paths == [str(tmp_path / "ccy")]

    def test_a_moved_directory_is_named(self, tmp_path: Path) -> None:
        (tmp_path / "ccy").mkdir()
        scan = scan_bash_write_targets(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "mv ccy elsewhere"},
                "cwd": str(tmp_path),
            },
            include_mutations=True,
        )
        assert str(tmp_path / "ccy") in scan.paths

    def test_a_copy_into_a_directory_still_names_the_file_inside(self, tmp_path: Path) -> None:
        (tmp_path / "dest").mkdir()
        scan = scan_bash_write_targets(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "cp /a/f.txt dest"},
                "cwd": str(tmp_path),
            },
            include_mutations=True,
        )
        assert scan.paths == [str(tmp_path / "dest" / "f.txt")]


class TestUnresolved:
    def test_an_unexpandable_operand_is_reported_unresolved(self) -> None:
        scan = scan_bash_write_targets(_bash("rm $DIR/ccy.env.local"), include_mutations=True)
        assert scan.paths == []
        assert scan.unresolved == ("$DIR/ccy.env.local",)


class TestExistingCallersAreUnchanged:
    """The verbs are opt-in: nothing that did not ask for them sees them."""

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("sed -i s/a/b/ f.txt", []),
            ("ln -s target link", []),
            ("rm -rf a b", []),
            ("truncate -s 0 f.txt", []),
            ("echo x > o.txt && rm o.txt", ["o.txt"]),
        ],
    )
    def test_the_default_destinations_name_no_mutation(
        self, command: str, expected: list[str]
    ) -> None:
        destinations = scan_bash_write_destinations(command).destinations
        assert [d.destination for d in destinations] == expected

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("sed -i s/a/b/ f.txt", []),
            ("ln -s target link", []),
            ("rm -rf a b", []),
            ("truncate -s 0 f.txt", []),
            ("mv a.txt b.txt", ["/repo/b.txt"]),
            ("echo x > o.txt && rm o.txt", ["/repo/o.txt"]),
        ],
    )
    def test_the_default_accessors_answer_as_before(
        self, command: str, expected: list[str]
    ) -> None:
        assert get_bash_write_targets(_bash(command)) == expected
        assert scan_bash_write_targets(_bash(command)).paths == expected

    def test_the_authored_accessor_is_unchanged(self) -> None:
        assert get_written_file_paths(_bash("sed -i s/a/b/ f.txt && rm g.txt")) == []

    def test_the_default_destinations_for_mv_are_the_destination_only(self) -> None:
        destinations = scan_bash_write_destinations("mv a.txt b.txt").destinations
        assert [d.destination for d in destinations] == ["b.txt"]
