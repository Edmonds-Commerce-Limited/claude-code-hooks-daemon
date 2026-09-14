"""Eliding runtime arguments out of a log record (Plan 00403 Task 1.5).

`bin/hooks-daemon bug-report` captures the last 100 daemon log lines into a
report the reporter is then invited to share on a PUBLIC tracker. Scrubbing
rewrites the project root, `$HOME` and the hostname, and that is not nearly
enough: running the scrubbed command against this repository and reading the
result showed whole `hook_input` payloads in the window — the verbatim Bash
command, `session_name` (free text a user wrote), `session_id`, `prompt_id`
and `tool_use_id` — none of which a path rule touches.

The split this module rests on is available by CONSTRUCTION rather than by
guessing what content looks like:

``the template is ours, the arguments are the client's``
    `logger.debug("PRE_TOOL_USE hook_input:\\n%s", json.dumps(payload))` has a
    developer-authored format string and a runtime value. The daemon logs
    `%s`-style at 341 of its 368 call sites, so the two stay separable right
    up to the moment a record is rendered.

``a payload is a structure; a daemon fact is a short scalar``
    Handler names, event types, counts and durations are what the other 339
    sites interpolate, and they are what makes the window worth reading. A
    dict or a list is a payload whatever its size, and an over-long string is
    a dump whatever its type. Neither test asks what the value MEANS.
"""

from __future__ import annotations

import logging

import pytest

from claude_code_hooks_daemon.utils.log_elision import (
    MAX_INLINE_ARGUMENT_LENGTH,
    elide_record_arguments,
)


def _record(msg: str, *args: object) -> logging.LogRecord:
    return logging.LogRecord(
        name="claude_code_hooks_daemon.core.router",
        level=logging.DEBUG,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args or None,
        exc_info=None,
    )


class TestADaemonFactSurvives:
    """The window is only worth capturing if it still says what happened."""

    def test_a_short_string_argument_is_kept(self) -> None:
        record = _record("Routing %s event to chain with %d handlers", "PreToolUse", 63)

        assert elide_record_arguments(record).getMessage() == (
            "Routing PreToolUse event to chain with 63 handlers"
        )

    @pytest.mark.parametrize("value", [0, -1, 63, 2.16, True, False, None])
    def test_a_scalar_argument_is_kept(self, value: object) -> None:
        record = _record("value=%s", value)

        assert str(value) in elide_record_arguments(record).getMessage()

    def test_an_integer_argument_stays_an_integer(self) -> None:
        """A `%d` placeholder raises if its argument is replaced with text."""
        record = _record("Request processed in %dms", 2)

        assert elide_record_arguments(record).getMessage() == "Request processed in 2ms"

    def test_a_record_with_no_arguments_is_returned_unchanged(self) -> None:
        record = _record("Daemon started")

        assert elide_record_arguments(record) is record


class TestAPayloadDoesNot:
    def test_a_dict_argument_is_elided_whatever_its_size(self) -> None:
        """A structure is a payload by construction — no size reasoning needed.

        This is `controller.py`'s `StatusLine raw hook_input: %s`, which passes
        the hook input dict straight through.
        """
        record = _record("StatusLine raw hook_input: %s", {"session_name": "Q4 payroll fix"})

        message = elide_record_arguments(record).getMessage()

        assert "Q4 payroll fix" not in message
        assert "session_name" not in message
        assert "dict" in message, "the reader must be told what was removed"

    def test_a_list_argument_is_elided(self) -> None:
        record = _record("items=%s", ["/srv/acme/secret.yaml"])

        assert "acme" not in elide_record_arguments(record).getMessage()

    def test_an_arbitrary_object_argument_is_elided(self) -> None:
        class Payload:
            def __repr__(self) -> str:
                return "Payload(client='acme')"

        record = _record("payload=%s", Payload())

        assert "acme" not in elide_record_arguments(record).getMessage()

    def test_an_over_long_string_argument_is_elided(self) -> None:
        """This is `router.py`'s serialised `PRE_TOOL_USE hook_input`.

        It reaches the logger as a `str` — `json.dumps(...)` — so the structure
        rule cannot catch it and the length rule is what does.
        """
        dump = '{\n  "command": "psql -h db.acme-internal.example"\n}' + " " * 200
        record = _record("PRE_TOOL_USE hook_input:\n%s", dump)

        message = elide_record_arguments(record).getMessage()

        assert "acme-internal" not in message
        assert "PRE_TOOL_USE hook_input:" in message, "the template is ours and stays"

    def test_the_elision_says_how_much_was_removed(self) -> None:
        """A reader who needs the detail has to know detail existed."""
        record = _record("dump=%s", "x" * 5000)

        assert "5000" in elide_record_arguments(record).getMessage()


class TestTheLengthBoundary:
    """A guard nobody can locate exactly is a guard nobody can reason about."""

    def test_a_string_at_the_boundary_is_kept(self) -> None:
        value = "v" * MAX_INLINE_ARGUMENT_LENGTH
        record = _record("value=%s", value)

        assert value in elide_record_arguments(record).getMessage()

    def test_one_character_over_the_boundary_is_elided(self) -> None:
        value = "v" * (MAX_INLINE_ARGUMENT_LENGTH + 1)
        record = _record("value=%s", value)

        assert value not in elide_record_arguments(record).getMessage()


class TestTheOriginalRecordIsNotDamaged:
    """`hooks-daemon logs` serves the same buffer and must stay full-fidelity.

    The buffer holds one set of `LogRecord` objects shared by every reader, so
    eliding in place would silently degrade the operator's own local diagnostic
    — on their own machine, about their own data, where there is nothing to
    protect them from.
    """

    def test_the_source_record_keeps_its_arguments(self) -> None:
        payload = {"session_name": "Q4 payroll fix"}
        record = _record("StatusLine raw hook_input: %s", payload)

        elide_record_arguments(record)

        assert record.args is payload, "stdlib unwraps a lone Mapping to the mapping itself"
        assert "Q4 payroll fix" in record.getMessage()

    def test_a_new_record_is_returned_when_anything_was_elided(self) -> None:
        record = _record("payload=%s", {"a": 1})

        assert elide_record_arguments(record) is not record

    def test_the_record_metadata_is_preserved(self) -> None:
        """The prefix a formatter renders — time, level, logger — is untouched."""
        record = _record("payload=%s", {"a": 1})

        elided = elide_record_arguments(record)

        assert elided.name == record.name
        assert elided.levelno == record.levelno
        assert elided.created == record.created


class TestMappingStyleFormatting:
    """`logger.info("%(user)s", {"user": ...})` is a mapping, not an argument.

    Python's logging treats a lone dict argument as the format MAPPING. Turning
    it into a string would make the `%(key)s` placeholders fail to resolve, so
    the mapping shape is kept and its VALUES are elided instead.
    """

    def test_the_mapping_still_resolves(self) -> None:
        record = _record("user=%(user)s count=%(count)d", {"user": "jbloggs", "count": 3})

        assert elide_record_arguments(record).getMessage() == "user=jbloggs count=3"

    def test_an_over_long_mapping_value_is_elided(self) -> None:
        record = _record("dump=%(dump)s", {"dump": "x" * 5000})

        message = elide_record_arguments(record).getMessage()

        assert "xxxx" not in message
        assert "5000" in message

    def test_the_template_is_what_tells_the_two_shapes_apart(self) -> None:
        """The same dict, two templates, two correct-but-opposite outcomes.

        `LogRecord.__init__` replaces a lone non-empty Mapping argument with
        the mapping itself, so `args` is byte-identical in both records below
        and cannot distinguish them. Only the format string can — and it is the
        half the daemon's own developers wrote.

        Losing this distinction is not cosmetic in either direction: treating
        the positional case as a mapping republishes the payload's keys, which
        is the `StatusLine raw hook_input` leak; treating the mapping case as
        positional leaves `%(user)s` unresolvable and raises at render time.
        """
        payload = {"user": "jbloggs"}
        positional = _record("hook_input: %s", payload)
        mapping = _record("user=%(user)s", payload)

        assert positional.args == mapping.args, "stdlib stores both identically"

        assert "jbloggs" not in elide_record_arguments(positional).getMessage()
        assert "jbloggs" in elide_record_arguments(mapping).getMessage()
