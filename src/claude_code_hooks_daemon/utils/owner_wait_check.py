"""Which owner-facing threads a coordinator seat has left un-bumped (Plan 00636 Task 2.1a).

The pure decision behind ``owner_wait_stop_guard`` (00630 DESIGN.md 20.1):
typed bus entries in, stale thread ids out. No I/O, no clock, no LLM
judgement: ids, timestamps, the notify flag and the thread relation only.

Two kinds of thread need this seat's attention, and they close differently:

- ``SEAT_QUESTION``: a question this seat asked or owns, open in the
  questions room. It stays satisfied only while a qualifying post landed in
  its thread within the window (``window_seconds``); older is stale.
- ``OWNER_STARTED``: a top-level human message in the questions room. It is
  open until ONE qualifying reply from this seat lands in its thread after
  it; no window applies.

A qualifying post is from this seat, NOTIFYING, in the thread by its
``m.thread`` relation (never ``m.in_reply_to``), and has a body that names
something beyond mentions and bump boilerplate. Every unreadable fact fails
closed: an unknown notify flag, author or relation does not qualify.

``FOREIGN`` threads (asked and owned by someone else) are ignored.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

#: Words a bump, a chase or a mention adds on its own; removing them must leave content.
BOILERPLATE_WORDS: Final[frozenset[str]] = frozenset(
    {
        "still",
        "waiting",
        "wait",
        "bump",
        "bumped",
        "bumping",
        "ping",
        "pinging",
        "nudge",
        "reminder",
        "chasing",
        "follow",
        "up",
        "update",
        "news",
        "please",
        "thanks",
        "re",
    }
)
#: Function words that name nothing on their own; a body of only these is boilerplate.
STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "a",
        "an",
        "the",
        "on",
        "for",
        "to",
        "of",
        "in",
        "at",
        "by",
        "with",
        "from",
        "about",
        "this",
        "that",
        "it",
        "any",
        "and",
        "or",
        "is",
        "are",
        "i",
        "am",
        "you",
        "me",
        "your",
        "my",
        "we",
        "us",
        "there",
        "here",
        "yet",
    }
)
_MENTION: Final[re.Pattern[str]] = re.compile(r"@\S+")
_WORD: Final[re.Pattern[str]] = re.compile(r"[^\W_]+")
#: The two thread-id shapes the bump command may name: a question, or a Matrix event id.
_QUESTION_ID: Final[re.Pattern[str]] = re.compile(r"Q[0-9]{1,6}")
_EVENT_ID: Final[re.Pattern[str]] = re.compile(r"\$[A-Za-z0-9._~+/=:-]{1,255}")
#: A thread id inside free text, which names the thread rather than what is awaited.
_THREAD_ID_IN_TEXT: Final[re.Pattern[str]] = re.compile(
    r"(?<![\w$])(?:[Qq][0-9]{1,6}\b|\$[A-Za-z0-9._~+/=:-]{1,255})"
)


class ThreadKind(StrEnum):
    SEAT_QUESTION = "seat_question"
    OWNER_STARTED = "owner_started"
    FOREIGN = "foreign"


@dataclass(frozen=True)
class OwnerThread:
    """One thread in the questions room.

    ``thread_id`` is what a bump command names (``Q61``, or the owner
    message's event id); ``root_event_id`` is what an ``m.thread`` relation
    points at. ``is_open`` is read for seat questions; an owner-started
    thread's openness is decided here from the replies.
    """

    thread_id: str
    root_event_id: str
    kind: ThreadKind
    is_open: bool = True
    started_at: float = 0.0


@dataclass(frozen=True)
class BusPost:
    """One posted entry. ``None`` in a tri-state field means unreadable.

    ``thread_root`` is the ``m.thread`` relation's target (``None``: no
    relation); ``relation_readable`` is False when the entry's relations
    could not be read at all. ``in_reply_to`` is carried only so it can be
    shown NOT to count.
    """

    event_id: str
    timestamp: float
    from_self: bool | None
    notifying: bool | None
    thread_root: str | None
    relation_readable: bool = True
    in_reply_to: str | None = None
    body: str = ""


@dataclass(frozen=True)
class BusSnapshot:
    threads: tuple[OwnerThread, ...] = ()
    posts: tuple[BusPost, ...] = ()


def has_meaningful_body(body: str) -> bool:
    """Whether ``body`` names something beyond mentions, thread ids and bump boilerplate.

    Mentions and thread ids are removed first; what is left must hold at least
    one word that is neither bump/chase boilerplate nor a stopword.
    """
    stripped = _THREAD_ID_IN_TEXT.sub(" ", _MENTION.sub(" ", body))
    words = _WORD.findall(stripped.casefold())
    return any(word not in BOILERPLATE_WORDS and word not in STOPWORDS for word in words)


def printable_thread_id(thread_id: str) -> str | None:
    """``thread_id`` ready for a shell command line, or None when its shape is not trusted.

    Thread ids come from the bus, so they are untrusted: only a question id or
    a Matrix event id of a plain grammar is printed, and an event id is quoted
    because its leading ``$`` would otherwise expand.
    """
    if _QUESTION_ID.fullmatch(thread_id):
        return thread_id
    if _EVENT_ID.fullmatch(thread_id):
        return shlex.quote(thread_id)
    return None


def _qualifies(post: BusPost, root: str, *, not_before: float, now: float) -> bool:
    return (
        post.from_self is True
        and post.notifying is True
        and post.relation_readable
        and post.thread_root == root
        and not_before <= post.timestamp <= now
        and has_meaningful_body(post.body)
    )


def _is_stale(thread: OwnerThread, posts: tuple[BusPost, ...], now: float, window: float) -> bool:
    if thread.kind is ThreadKind.SEAT_QUESTION:
        if not thread.is_open:
            return False
        not_before = now - window
    elif thread.kind is ThreadKind.OWNER_STARTED:
        not_before = thread.started_at
    else:
        return False
    root = thread.root_event_id
    return not any(_qualifies(post, root, not_before=not_before, now=now) for post in posts)


def stale_threads(snapshot: BusSnapshot, *, now: float, window_seconds: float) -> tuple[str, ...]:
    """The ids of every thread this seat must bump, in snapshot order."""
    return tuple(
        thread.thread_id
        for thread in snapshot.threads
        if _is_stale(thread, snapshot.posts, now, window_seconds)
    )
