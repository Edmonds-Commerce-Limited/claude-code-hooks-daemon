"""The owner-wait bus adapter (Plan 00636 Task 2.1a): history reads and the bump command."""

from __future__ import annotations

from claude_code_hooks_daemon.utils.owner_wait_bus import (
    TEAM_PLACEHOLDER,
    BusUnreadable,
    TeamchatOwnerWaitBus,
)
from claude_code_hooks_daemon.utils.teamchat_seat import SessionSignals


class TestBumpCommand:
    def test_one_command_names_every_thread(self) -> None:
        bus = TeamchatOwnerWaitBus()
        assert bus.bump_command("alpha", ("Q61", "Q64")) == "teamchat bump Q61 Q64"

    def test_event_ids_are_single_quoted(self) -> None:
        bus = TeamchatOwnerWaitBus()
        assert bus.bump_command("alpha", ("Q61", "$abc")) == "teamchat bump Q61 '$abc'"

    def test_an_untrusted_id_falls_back_to_waiting(self) -> None:
        bus = TeamchatOwnerWaitBus()
        assert bus.bump_command("alpha", ("Q61", "$x; rm -rf ~")) == "teamchat bump --waiting"


class TestNotifyCommands:
    def test_the_v1_notifying_reply_forms_for_a_question_and_an_owner_message(self) -> None:
        question, owner_message = TeamchatOwnerWaitBus().notify_commands("alpha")
        assert question == "pingbus thread --team alpha Q<n> --ask"
        assert owner_message == "pingbus thread --team alpha --re <event id> --ask"

    def test_an_unsafe_team_name_is_shell_quoted(self) -> None:
        question, _ = TeamchatOwnerWaitBus().notify_commands("a b")
        assert question == "pingbus thread --team 'a b' Q<n> --ask"

    def test_the_team_placeholder_is_left_as_a_template_slot(self) -> None:
        question, _ = TeamchatOwnerWaitBus().notify_commands(TEAM_PLACEHOLDER)
        assert question == "pingbus thread --team <team> Q<n> --ask"


class TestRead:
    def test_history_is_unreadable_until_teamchat_documents_the_fields(self) -> None:
        # No teamchat history contract exposing the notify flag and the m.thread
        # relation is verified, so the adapter reports unreadable rather than
        # parsing an invented format; the guard's on_unreadable_bus decides.
        result = TeamchatOwnerWaitBus().read("alpha", SessionSignals("/run/x", "/opt/kit"))
        assert isinstance(result, BusUnreadable)
        assert "unverified" in result.reason
