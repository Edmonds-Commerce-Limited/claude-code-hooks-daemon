"""The deterministic owner-wait decision (Plan 00636 Task 2.1a, 00630 DESIGN.md 20.1).

Pure logic: typed bus entries in, stale thread ids out. Every acceptance
bullet of DESIGN.md 20.1 that is about the decision (not the handler wiring)
has a test here.
"""

from __future__ import annotations

import dataclasses

from claude_code_hooks_daemon.utils.owner_wait_check import (
    BusPost,
    BusSnapshot,
    OwnerThread,
    ThreadKind,
    has_meaningful_body,
    printable_thread_id,
    stale_threads,
)

NOW = 1_000_000.0
WINDOW = 30 * 60.0
Q61_ROOT = "$q61root"
OWNER_ROOT = "$ownerMsg1"


def _question(thread_id: str = "Q61", root: str = Q61_ROOT, *, open_: bool = True) -> OwnerThread:
    return OwnerThread(
        thread_id=thread_id,
        root_event_id=root,
        kind=ThreadKind.SEAT_QUESTION,
        is_open=open_,
        started_at=NOW - 7200,
    )


def _owner_started(root: str = OWNER_ROOT, at: float = NOW - 3600) -> OwnerThread:
    return OwnerThread(
        thread_id=root, root_event_id=root, kind=ThreadKind.OWNER_STARTED, started_at=at
    )


def _post(
    root: str | None = Q61_ROOT,
    *,
    at: float = NOW - 60,
    notifying: bool | None = True,
    from_self: bool | None = True,
    readable: bool = True,
    in_reply_to: str | None = None,
    body: str = "still waiting: which branch to retire?",
) -> BusPost:
    return BusPost(
        event_id="$p",
        timestamp=at,
        from_self=from_self,
        notifying=notifying,
        thread_root=root,
        relation_readable=readable,
        in_reply_to=in_reply_to,
        body=body,
    )


def _stale(*threads: OwnerThread, posts: tuple[BusPost, ...] = ()) -> tuple[str, ...]:
    snapshot = BusSnapshot(threads=threads, posts=posts)
    return stale_threads(snapshot, now=NOW, window_seconds=WINDOW)


class TestSeatQuestions:
    def test_open_question_with_no_post_is_stale(self) -> None:
        assert _stale(_question()) == ("Q61",)

    def test_recent_notifying_post_satisfies(self) -> None:
        assert _stale(_question(), posts=(_post(),)) == ()

    def test_plain_non_notifying_post_does_not_satisfy(self) -> None:
        assert _stale(_question(), posts=(_post(notifying=False),)) == ("Q61",)

    def test_unreadable_notify_flag_counts_as_non_notifying(self) -> None:
        assert _stale(_question(), posts=(_post(notifying=None),)) == ("Q61",)

    def test_post_older_than_window_is_stale(self) -> None:
        assert _stale(_question(), posts=(_post(at=NOW - WINDOW - 1),)) == ("Q61",)

    def test_post_exactly_at_window_edge_counts(self) -> None:
        assert _stale(_question(), posts=(_post(at=NOW - WINDOW),)) == ()

    def test_empty_body_does_not_count(self) -> None:
        assert _stale(_question(), posts=(_post(body="   "),)) == ("Q61",)

    def test_boilerplate_only_body_does_not_count(self) -> None:
        assert _stale(_question(), posts=(_post(body="@owner still waiting:"),)) == ("Q61",)

    def test_post_from_another_member_does_not_count(self) -> None:
        assert _stale(_question(), posts=(_post(from_self=False),)) == ("Q61",)

    def test_post_with_unreadable_author_does_not_count(self) -> None:
        assert _stale(_question(), posts=(_post(from_self=None),)) == ("Q61",)

    def test_post_in_another_thread_does_not_count(self) -> None:
        assert _stale(_question(), posts=(_post(root="$other"),)) == ("Q61",)

    def test_closed_question_is_ignored(self) -> None:
        assert _stale(_question(open_=False)) == ()

    def test_foreign_question_is_ignored(self) -> None:
        foreign = OwnerThread(
            thread_id="Q9",
            root_event_id="$q9",
            kind=ThreadKind.FOREIGN,
            is_open=True,
            started_at=NOW - 7200,
        )
        assert _stale(foreign) == ()

    def test_several_stale_threads_are_all_named_in_order(self) -> None:
        assert _stale(_question(), _question("Q64", "$q64")) == ("Q61", "Q64")

    def test_post_in_the_future_does_not_count(self) -> None:
        # A clock-skewed entry stamped after "now" is not evidence of a recent bump.
        assert _stale(_question(), posts=(_post(at=NOW + 3600),)) == ("Q61",)


class TestOwnerStartedThreads:
    def test_open_owner_thread_with_no_reply_is_stale(self) -> None:
        assert _stale(_owner_started()) == (OWNER_ROOT,)

    def test_notifying_reply_in_another_thread_does_not_close_it(self) -> None:
        assert _stale(_owner_started(), posts=(_post(root="$elsewhere"),)) == (OWNER_ROOT,)

    def test_non_notifying_reply_in_the_thread_does_not_close_it(self) -> None:
        reply = _post(root=OWNER_ROOT, notifying=False)
        assert _stale(_owner_started(), posts=(reply,)) == (OWNER_ROOT,)

    def test_reply_with_unreadable_notify_flag_does_not_close_it(self) -> None:
        reply = _post(root=OWNER_ROOT, notifying=None)
        assert _stale(_owner_started(), posts=(reply,)) == (OWNER_ROOT,)

    def test_notifying_reply_in_the_thread_from_self_closes_it(self) -> None:
        assert _stale(_owner_started(), posts=(_post(root=OWNER_ROOT),)) == ()

    def test_closing_reply_needs_no_recent_window(self) -> None:
        reply = _post(root=OWNER_ROOT, at=NOW - 3000)
        assert _stale(_owner_started(at=NOW - 3500), posts=(reply,)) == ()

    def test_reply_before_the_owner_message_does_not_close_it(self) -> None:
        reply = _post(root=OWNER_ROOT, at=NOW - 4000)
        assert _stale(_owner_started(at=NOW - 3600), posts=(reply,)) == (OWNER_ROOT,)

    def test_in_reply_to_only_does_not_close_it(self) -> None:
        reply = _post(root=None, in_reply_to=OWNER_ROOT)
        assert _stale(_owner_started(), posts=(reply,)) == (OWNER_ROOT,)

    def test_unreadable_relation_does_not_close_it(self) -> None:
        reply = _post(root=OWNER_ROOT, readable=False)
        assert _stale(_owner_started(), posts=(reply,)) == (OWNER_ROOT,)


class TestBody:
    def test_default_bump_body_names_what_is_awaited(self) -> None:
        assert has_meaningful_body("still waiting: retire the plan-00599 branch?")

    def test_mentions_and_prefix_only_is_boilerplate(self) -> None:
        assert not has_meaningful_body("@owner:example.org still waiting")

    def test_empty_is_boilerplate(self) -> None:
        assert not has_meaningful_body("")

    # F7 (PR 226 review): a thread id, a stopword or a politeness word is not content.
    def test_bump_with_a_question_id_is_boilerplate(self) -> None:
        assert not has_meaningful_body("bump Q61")

    def test_bump_with_an_event_id_is_boilerplate(self) -> None:
        assert not has_meaningful_body("bump $abc123:example.org")

    def test_still_waiting_on_a_mention_is_boilerplate(self) -> None:
        assert not has_meaningful_body("still waiting on @owner")

    def test_ping_please_is_boilerplate(self) -> None:
        assert not has_meaningful_body("ping please")

    def test_stopwords_only_is_boilerplate(self) -> None:
        assert not has_meaningful_body("re Q61: any news on this, please?")

    def test_one_content_word_beside_an_id_counts(self) -> None:
        assert has_meaningful_body("bump Q61: merge?")


class TestAdapterContract:
    # F8 (PR 226 review): a defaulted started_at of 0.0 let any past self-reply
    # close an owner-started thread, so an adapter must always supply it.
    def test_started_at_has_no_default(self) -> None:
        started_at = {field.name: field for field in dataclasses.fields(OwnerThread)}["started_at"]
        assert started_at.default is dataclasses.MISSING
        assert started_at.default_factory is dataclasses.MISSING

    def test_the_contract_states_timestamps_are_in_seconds(self) -> None:
        for documented in (OwnerThread.__doc__, BusPost.__doc__):
            assert documented is not None
            assert "seconds" in documented
            assert "millisecond" in documented


class TestPrintableId:
    def test_question_id_is_printable(self) -> None:
        assert printable_thread_id("Q61") == "Q61"

    def test_event_id_is_single_quoted(self) -> None:
        assert printable_thread_id("$abc_DEF-123") == "'$abc_DEF-123'"

    def test_id_with_shell_metacharacters_is_refused(self) -> None:
        assert printable_thread_id("$x; rm -rf ~") is None

    def test_id_with_quote_is_refused(self) -> None:
        assert printable_thread_id("$x'y") is None

    def test_unknown_shape_is_refused(self) -> None:
        assert printable_thread_id("hello") is None
