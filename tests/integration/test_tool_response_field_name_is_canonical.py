"""The shared constants must name the field REAL PostToolUse events carry.

``POST_TOOL_USE_INPUT_SCHEMA`` requires ``tool_response`` and explicitly rejects
``tool_output`` — it carries a ``"not": {"required": ["tool_output"]}`` clause,
so the daemon refuses a payload containing that key outright. Two comments above
it say so in capitals, which is how you know the mistake has been made before.

Despite that, ``HookInputField`` offered ``TOOL_OUTPUT`` and no ``TOOL_RESPONSE``.
Nothing in ``src/`` used it; the one handler that legitimately reads the tool
response (``git_hooks_executable_fixer``) had to define its own private constant
for the correct name. So the shared module published exactly the wrong field
name and withheld the right one.

That is a trap rather than a mere oddity, because this project's NO MAGIC rule
tells an author to reach for a named constant instead of a string literal. An
author who obeys it lands on ``TOOL_OUTPUT``, reads a key that is never present,
and gets a handler that silently sees nothing forever — no error, no failing
test, because the value is simply always absent.

The fixtures in the tree show it already happened: five in the recovery-cron
advisor's tests and one in the daemon smoke test modelled ``tool_output`` as a
valid payload. Unit tests call handlers directly, bypassing validation, so those
fixtures passed while describing a payload production would reject.
"""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.core.input_schemas import POST_TOOL_USE_INPUT_SCHEMA

_REJECTED_FIELD = "tool_output"
_CANONICAL_FIELD = "tool_response"

#: Matched as a dict KEY, not as a bare mention. Scanning for the bare quoted
#: name flags prose that merely NAMES the wrong field — this file's own
#: docstring, and the comment in the smoke test warning against it — which would
#: make the guard unfixable by the very text explaining it. Only a payload
#: literally built with this key is a defect.
_REJECTED_KEY_FORM = f'"{_REJECTED_FIELD}":'

#: Files whose JOB is to prove the wrong field name is rejected. They must
#: contain it — that is the assertion. Every other test file naming it is
#: modelling a payload the daemon would refuse.
_REJECTION_PROVING_FILES = frozenset(
    {
        "tests/unit/core/test_input_schemas.py",
        "tests/unit/daemon/test_server_validation.py",
    }
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


class TestCanonicalFieldName:
    """The constants module is the thing authors reach for, so it must be right."""

    def test_hook_input_field_offers_the_canonical_name(self) -> None:
        """An author following NO MAGIC must find the field that exists."""
        assert getattr(HookInputField, "TOOL_RESPONSE", None) == _CANONICAL_FIELD, (
            "HookInputField has no TOOL_RESPONSE constant, so a handler author "
            "reading the tool response must either hardcode the string or reach "
            "for a constant naming a field that is never present"
        )

    def test_hook_input_field_does_not_publish_the_rejected_name(self) -> None:
        """Publishing it as a peer of the real fields is what makes it a trap."""
        assert not hasattr(HookInputField, "TOOL_OUTPUT"), (
            "HookInputField still publishes TOOL_OUTPUT. The PostToolUse schema "
            "explicitly rejects that key, so the constant can only ever be used "
            "to build a payload the daemon refuses"
        )

    def test_the_schema_still_backs_this_check(self) -> None:
        """Guard the guard — if the schema flips, this file must be revisited.

        The whole argument above rests on the schema requiring one name and
        rejecting the other. Asserting that here means a future protocol change
        fails loudly rather than leaving these tests enforcing a stale contract.
        """
        assert _CANONICAL_FIELD in POST_TOOL_USE_INPUT_SCHEMA["required"]
        assert POST_TOOL_USE_INPUT_SCHEMA["not"]["required"] == [_REJECTED_FIELD]


class TestNoFixtureModelsTheRejectedPayload:
    """A fixture that contradicts the schema tests a payload nothing sends."""

    @staticmethod
    def _offending_files() -> list[str]:
        root = _repo_root()
        offenders: list[str] = []
        for path in sorted((root / "tests").rglob("test_*.py")):
            relative = path.relative_to(root).as_posix()
            if relative in _REJECTION_PROVING_FILES:
                continue
            if _REJECTED_KEY_FORM in path.read_text(encoding="utf-8"):
                offenders.append(relative)
        return offenders

    def test_no_test_fixture_uses_the_rejected_field_name(self) -> None:
        """Only the files proving rejection may name it."""
        offenders = self._offending_files()

        assert not offenders, (
            f"test file(s) name {_REJECTED_FIELD!r}, which the PostToolUse schema "
            f"rejects. Use {_CANONICAL_FIELD!r} so the fixture matches what Claude "
            "Code actually sends:\n  " + "\n  ".join(offenders)
        )

    def test_the_allowlisted_files_still_exist_and_still_prove_rejection(self) -> None:
        """An allow-list entry that goes stale silently widens the exemption."""
        root = _repo_root()
        for relative in sorted(_REJECTION_PROVING_FILES):
            path = root / relative
            assert path.is_file(), f"allow-listed file {relative} no longer exists"
            assert _REJECTED_KEY_FORM in path.read_text(encoding="utf-8"), (
                f"{relative} is allow-listed as proving the wrong field name is "
                "rejected, but no longer names it — drop it from the allow-list"
            )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
