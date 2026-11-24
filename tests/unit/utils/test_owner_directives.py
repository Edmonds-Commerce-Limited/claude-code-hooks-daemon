"""Tests for the owner directives register parser and renderer (Plan 00636 Task 2.2, s3)."""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.owner_directives import (
    MAX_DIRECTIVES,
    MAX_TEXT_CHARS,
    Directive,
    parse_directives,
    render_directives,
)


class TestParse:
    def test_none_and_empty_list_are_an_empty_register(self) -> None:
        for raw in (None, []):
            register = parse_directives(raw)
            assert register.directives == ()
            assert register.problems == ()

    def test_valid_entries_keep_their_order(self) -> None:
        register = parse_directives(
            [{"id": "no-squash", "text": "Never squash."}, {"id": "b", "text": "Do B."}]
        )
        assert register.directives == (
            Directive("no-squash", "Never squash."),
            Directive("b", "Do B."),
        )
        assert register.problems == ()

    def test_same_id_is_recorded_once(self) -> None:
        register = parse_directives(
            [{"id": "A", "text": "first wording"}, {"id": "a", "text": "second wording"}]
        )
        assert register.directives == (Directive("A", "first wording"),)
        assert register.collapsed == 1

    def test_same_text_under_another_id_is_recorded_once(self) -> None:
        register = parse_directives(
            [{"id": "a", "text": "Use  the   bus."}, {"id": "b", "text": "use the bus."}]
        )
        assert [d.id for d in register.directives] == ["a"]
        assert register.collapsed == 1

    def test_non_list_is_a_problem_and_empty(self) -> None:
        register = parse_directives({"id": "a", "text": "x"})
        assert register.directives == ()
        assert len(register.problems) == 1

    @pytest.mark.parametrize(
        "entry",
        [
            "just a string",
            {"id": "a"},
            {"text": "no id"},
            {"id": "", "text": "x"},
            {"id": "a", "text": "   "},
            {"id": 3, "text": "x"},
            {"id": "a", "text": 3},
            {"id": "bad id!", "text": "x"},
            {"id": "a", "text": "x" * (MAX_TEXT_CHARS + 1)},
        ],
    )
    def test_malformed_entry_is_skipped_with_a_problem(self, entry: object) -> None:
        register = parse_directives([entry, {"id": "ok", "text": "fine"}])
        assert register.directives == (Directive("ok", "fine"),)
        assert len(register.problems) == 1

    def test_count_is_bounded(self) -> None:
        raw = [{"id": f"d{n}", "text": f"directive {n}"} for n in range(MAX_DIRECTIVES + 3)]
        register = parse_directives(raw)
        assert len(register.directives) == MAX_DIRECTIVES
        assert len(register.problems) == 1


class TestRender:
    def test_names_the_register_and_lists_each_directive_once(self) -> None:
        text = render_directives((Directive("a", "Do A."), Directive("b", "Do B.")))
        assert "owner_directives_register" in text
        assert "[a] Do A." in text
        assert "[b] Do B." in text

    def test_is_not_a_human_instruction_and_never_a_countermand(self) -> None:
        text = render_directives((Directive("a", "Do A."),)).lower()
        assert "not a fresh human instruction" in text
        assert "not a citable" in text
        for word in ("ignore", "override", "disregard"):
            assert word not in text

    def test_tells_the_seat_to_check_before_asking(self) -> None:
        assert "before asking the owner" in render_directives((Directive("a", "x"),))
