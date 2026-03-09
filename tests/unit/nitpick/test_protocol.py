"""Tests for NitpickState dataclass."""

from claude_code_hooks_daemon.nitpick.protocol import NitpickState


class TestNitpickState:
    """Tests for NitpickState mutable dataclass."""

    def test_state_defaults(self) -> None:
        """NitpickState has sensible defaults."""
        state = NitpickState()
        assert state.last_byte_offset == 0
        assert state.last_audited_uuid is None
        assert state.findings_count == 0

    def test_state_custom_values(self) -> None:
        """NitpickState accepts custom values."""
        state = NitpickState(
            last_byte_offset=1024,
            last_audited_uuid="abc-123",
            findings_count=5,
        )
        assert state.last_byte_offset == 1024
        assert state.last_audited_uuid == "abc-123"
        assert state.findings_count == 5

    def test_state_is_mutable(self) -> None:
        """NitpickState fields can be updated (mutable dataclass)."""
        state = NitpickState()
        state.last_byte_offset = 2048
        state.last_audited_uuid = "new-uuid"
        state.findings_count = 3
        assert state.last_byte_offset == 2048
        assert state.last_audited_uuid == "new-uuid"
        assert state.findings_count == 3
