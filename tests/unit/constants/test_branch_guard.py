"""The shared principle text every branch-limit deny carries (Plan 00558 DESIGN section 12)."""

from claude_code_hooks_daemon.constants.branch_guard import (
    BRANCH_LIMIT_PRINCIPLE,
    POOL_DELETE_CONDITION,
    POOL_PARK_CLAUSE,
)


def test_the_principle_says_the_limit_exists_so_work_finishes() -> None:
    assert "work FINISHES, never so it disappears" in BRANCH_LIMIT_PRINCIPLE


def test_the_principle_names_an_ignored_copy_as_lost_work() -> None:
    assert "ignored or untracked directory is lost work" in BRANCH_LIMIT_PRINCIPLE


def test_the_principle_says_to_ask_a_human_rather_than_lose_work() -> None:
    assert "stop and ask a human" in BRANCH_LIMIT_PRINCIPLE


def test_the_principle_says_parking_is_a_short_bounded_pause() -> None:
    assert "Parking is a short, bounded pause" in BRANCH_LIMIT_PRINCIPLE


def test_the_principle_accepts_only_machine_proof_or_a_human_for_a_delete() -> None:
    assert "the guard proves by machine that nothing is lost" in BRANCH_LIMIT_PRINCIPLE
    assert "a human confirmed it" in BRANCH_LIMIT_PRINCIPLE
    assert "never counts" in BRANCH_LIMIT_PRINCIPLE


def test_the_pool_delete_condition_is_machine_proof_or_the_human_deleting() -> None:
    assert "the guard proves nothing is lost" in POOL_DELETE_CONDITION
    assert "the human deletes it themselves" in POOL_DELETE_CONDITION
    assert "your own assertion never counts" in POOL_DELETE_CONDITION
    assert "\n" not in POOL_DELETE_CONDITION


def test_the_pool_park_clause_says_a_short_bounded_pause() -> None:
    assert "short, bounded pause" in POOL_PARK_CLAUSE


def test_the_principle_names_no_bypass_flag() -> None:
    for word in ("allow-unproven", "bundle", "valueless"):
        assert word not in BRANCH_LIMIT_PRINCIPLE


def test_the_principle_is_one_paragraph() -> None:
    assert "\n" not in BRANCH_LIMIT_PRINCIPLE
