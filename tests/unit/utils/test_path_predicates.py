"""Path predicates that cannot raise, and cannot silently pick a side.

``pathlib`` swallows the stat failures it considers expected — ENOENT, ENOTDIR,
EBADF, ELOOP — and answers ``False``. **EACCES is not in that set**, so
``exists()``, ``is_file()`` and ``is_dir()`` all raise ``PermissionError`` when
any directory in the parent chain lacks ``+x`` for the daemon's user. Handlers
call those predicates on paths taken straight from a user's tool input, where
the daemon has no say in whether it can stat them.

The obvious fix — one canonical fallback, mirroring what pathlib does for the
failures it already ignores — was falsified by Plan 00347's classification pass
before any code was written to it. ``write_clobber_guard.matches()`` reads
``if not Path(path).is_file(): return False`` ("creating a new file destroys
nothing"), so a ``False`` fallback there makes the guard decline to fire and the
clobber it exists to prevent is allowed. The safe answer at that site is
``True``; at ``comment_size`` it is ``False``; at ``plan_qa_edit`` no boolean is
safe at all, because a downstream consumer tests ``is not True``.

So these predicates take the fallback as a REQUIRED keyword argument. A default
would be a guess made once, in this file, on behalf of 14 call sites that do not
agree — and it would read as principled while inverting a guard.

Every test here FORCES the error. A permission-based fixture reproduces nothing
when the suite runs as root, which is exactly how the originating instance
(``core/utils.py:_written_paths``, fixed at ``f17fabcd``) reached CI unnoticed.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import pytest

from claude_code_hooks_daemon.utils.path_predicates import (
    path_exists,
    path_is_dir,
    path_is_file,
)

_PREDICATES: Final[dict[str, tuple[Callable[..., Any], str]]] = {
    "path_exists": (path_exists, "exists"),
    "path_is_file": (path_is_file, "is_file"),
    "path_is_dir": (path_is_dir, "is_dir"),
}


@pytest.fixture
def deny_every_stat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make all three pathlib predicates raise EACCES.

    This is what an untraversable parent directory does to a real process. It
    is patched rather than provoked because mode bits do not apply to root, and
    this suite runs as root.
    """

    def _denied(self: Path) -> bool:
        raise PermissionError(13, "Permission denied", str(self))

    for _name, (_func, attr) in _PREDICATES.items():
        monkeypatch.setattr(Path, attr, _denied)


class TestTheFixtureIsNotVacuous:
    """Guards against the failure mode that keeps recurring in this plan.

    A test that passes before the thing it tests exists proves nothing. Here
    the specific trap is that a fallback which happens to MATCH the path's real
    answer makes an unpatched predicate look like a working one.
    """

    @pytest.mark.parametrize("attr", ["exists", "is_file", "is_dir"])
    def test_the_forced_denial_really_raises(self, attr: str, deny_every_stat: None) -> None:
        with pytest.raises(PermissionError):
            getattr(Path("/anything"), attr)()

    def test_the_asserted_fallback_contradicts_the_real_answer(
        self, tmp_path: Path, deny_every_stat: None
    ) -> None:
        """The file below really exists, so an unpatched ``is_file`` answers
        ``True``. Asserting ``False`` therefore cannot pass by coincidence."""
        real_file = tmp_path / "present.txt"
        real_file.write_text("x", encoding="utf-8")

        assert path_is_file(real_file, unreadable_means=False) is False


class TestTheAnswerIsTheCallersWhenTheStatFails:
    @pytest.mark.parametrize("name", sorted(_PREDICATES))
    @pytest.mark.parametrize("fallback", [True, False, None, "unknown"])
    def test_the_caller_supplied_value_is_returned_verbatim(
        self, name: str, fallback: Any, deny_every_stat: None
    ) -> None:
        """Not coerced to a bool. ``plan_qa_edit`` feeds ``file_exists_before``
        to a consumer that tests ``is not True``, so ``None`` has to survive as
        itself rather than collapsing into ``False``."""
        predicate, _attr = _PREDICATES[name]

        assert predicate("/root/unreadable/target", unreadable_means=fallback) is fallback

    def test_an_inverted_site_can_ask_for_true(self, deny_every_stat: None) -> None:
        """``write_clobber_guard`` reads a ``False`` as 'nothing to destroy'.

        This is the site that falsified the single-canonical-fallback design:
        the value that keeps a DENY guard firing is the opposite of the one
        pathlib would give.
        """
        assert path_is_file("/root/unreadable/CLAUDE.md", unreadable_means=True) is True


class TestPathlibsOwnIgnoredFailuresAreUnchanged:
    """The fallback covers what pathlib RAISES on, and nothing else.

    A missing path is not an unreadable one. Widening the fallback to ENOENT
    would make every guard treat "not there" as "could not look", which is a
    different and much louder lie.
    """

    @pytest.mark.parametrize("name", sorted(_PREDICATES))
    def test_a_missing_path_answers_false_not_the_fallback(self, name: str, tmp_path: Path) -> None:
        predicate, _attr = _PREDICATES[name]

        assert predicate(tmp_path / "no-such-entry", unreadable_means=True) is False

    def test_a_real_file_is_still_reported_as_one(self, tmp_path: Path) -> None:
        real_file = tmp_path / "present.txt"
        real_file.write_text("x", encoding="utf-8")

        assert path_is_file(real_file, unreadable_means=False) is True
        assert path_exists(real_file, unreadable_means=False) is True
        assert path_is_dir(real_file, unreadable_means=True) is False

    def test_a_real_directory_is_still_reported_as_one(self, tmp_path: Path) -> None:
        assert path_is_dir(tmp_path, unreadable_means=False) is True
        assert path_is_file(tmp_path, unreadable_means=True) is False


class TestTheSubstitutionIsRecorded:
    """A silent fallback fails ``audit_error_hiding.py``, correctly.

    Without a record, "the guard decided this is not a file" and "the guard
    could not look" are indistinguishable to whoever asks why a policy did not
    fire. ``f17fabcd`` was rejected by that auditor on its first draft for
    exactly this.
    """

    @pytest.mark.parametrize("name", sorted(_PREDICATES))
    def test_the_eacces_path_logs_a_warning(
        self, name: str, deny_every_stat: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        predicate, _attr = _PREDICATES[name]

        with caplog.at_level(logging.WARNING):
            predicate("/root/unreadable/target", unreadable_means=False)

        assert caplog.records, f"{name} substituted an answer without recording it"

    @pytest.mark.parametrize("name", sorted(_PREDICATES))
    def test_the_record_names_the_path_and_the_substituted_answer(
        self, name: str, deny_every_stat: None, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Enough to act on: which path, why it failed, and what was assumed
        instead. A warning that says only "stat failed" cannot tell an operator
        whether a guard fired or abstained."""
        predicate, _attr = _PREDICATES[name]

        with caplog.at_level(logging.WARNING):
            predicate("/root/unreadable/target", unreadable_means=True)

        message = " ".join(record.getMessage() for record in caplog.records)
        assert "/root/unreadable/target" in message
        assert "Permission denied" in message
        assert "True" in message

    @pytest.mark.parametrize("name", sorted(_PREDICATES))
    def test_a_successful_stat_is_not_logged(
        self, name: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The warning marks an abstention. Emitting it on the happy path would
        make it noise, and noise is how a real one gets missed."""
        predicate, _attr = _PREDICATES[name]

        with caplog.at_level(logging.WARNING):
            predicate(tmp_path, unreadable_means=False)

        assert not caplog.records


class TestTheCallerCannotAvoidChoosing:
    """The whole point of the helper. A default would be a guess made once, in
    one file, on behalf of call sites that provably disagree."""

    @pytest.mark.parametrize("name", sorted(_PREDICATES))
    def test_the_fallback_has_no_default(self, name: str) -> None:
        predicate, _attr = _PREDICATES[name]

        parameter = inspect.signature(predicate).parameters["unreadable_means"]

        assert parameter.default is inspect.Parameter.empty, (
            f"{name} supplies a default fallback, so a new call site inherits "
            "an answer instead of choosing one -- which at write_clobber_guard "
            "silently exempts the guard"
        )

    @pytest.mark.parametrize("name", sorted(_PREDICATES))
    def test_omitting_the_fallback_is_an_error(self, name: str) -> None:
        predicate, _attr = _PREDICATES[name]

        with pytest.raises(TypeError):
            predicate("/tmp")

    @pytest.mark.parametrize("name", sorted(_PREDICATES))
    def test_the_fallback_cannot_be_passed_positionally(self, name: str) -> None:
        """Keyword-only, so the value is always read WITH its reasoning at the
        call site. ``path_is_file(p, True)`` says nothing about what True means
        here; ``unreadable_means=True`` says all of it."""
        predicate, _attr = _PREDICATES[name]

        with pytest.raises(TypeError):
            predicate("/tmp", True)


class TestBothPathSpellingsWork:
    @pytest.mark.parametrize("name", sorted(_PREDICATES))
    def test_a_str_and_a_path_agree(self, name: str, tmp_path: Path) -> None:
        """Call sites hold both -- ``tool_input`` gives a str, internal callers
        hold a ``Path``. A helper that only took one would be routed around."""
        predicate, _attr = _PREDICATES[name]

        assert predicate(tmp_path, unreadable_means=None) is predicate(
            str(tmp_path), unreadable_means=None
        )
