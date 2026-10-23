# Plan 00501 Task 8.3: ruling on the `manual-goals` expiry

Question: every session-modes entry must carry a finite expiry (daemon and supervisor parsers). The design proposes
a fixed 30-day expiry for `manual-goals` that only reaps a dead session's file. Is that consistent with the owner's
"no TTL" (PLAN.md question 11), or must the parsers accept an expiry-less entry? Is there a cleaner option?

## Facts confirmed

- PLAN.md question 11 and Task 8.3: exit by explicit switch-back or a new session; no TTL; a typed `/goal` does not
  exit it. The owner specified observable behaviour, not a storage encoding.
- `utils/session_modes.py:146` documents `expires_at` as "every mode is bounded"; `__post_init__` (line 166) refuses
  `expires_at <= entered_at`; `renewal_ttl` (line 187) is `FOCUS_TTL_SECONDS` for focus and `None` for everything
  else; `renewed()` (line 195) moves the expiry to `now + ttl`.
- `core/session_mode_registry.py`: entries expire lazily on every read and in `reap()` (lines 330-340); an expiry
  emits a `NoticeKind.EXPIRED` notice whose text is `"<entry> expired"` (line 154), so an expiry that happens while
  the session is alive is STATED to it, not silent. The renew path exists (line 320: `renewed != live`).
- `.claude/ccy/claude-supervise.py:2862` `_SESSION_MODES_STORED_MODES = {"focus", "blocked"}`; line 2931
  `_parse_session_modes_record` requires a finite `expires_at > entered_at` (lines 2965-2974) and raises on any
  other mode. An unreadable record closes the supervisor's gate ("treated as BLOCKED", line 2903). Part 1 of the
  implementation report already requires adding `"manual-goals"` to that set with `label=None`.

## The three options

1. **Fixed 30-day expiry, no renewal** (the design as written). Consistent with "no TTL" only while no session
   lives longer than 30 days. A session that does reaches day 30, the mode ends, and the registry states
   "manual-goals expired" to it. That is a clock-driven exit the owner excluded, however rare. It is also an
   arbitrary constant whose docstring has to argue that it is not what it plainly is.
2. **Expiry-less entry for this label.** Needs a contract change in BOTH parsers (`_finite`/`__post_init__` on the
   daemon side; `_parse_session_modes_record` on the supervisor side, pinned by
   `tests/unit/supervise/test_session_modes_gate.py`), plus a special case in `is_live`, `_partition` and the
   supervisor's expiry return. Risks: the "every entry is bounded" invariant is lost, so a dead session's file is
   never reaped; and the supervisor fails CLOSED on a record it cannot parse, so any skew between a daemon that
   writes the new shape and a worker that has not hot-reloaded reads as BLOCKED and withholds `continue`, the exact
   breakage Part 1 fact 3 is avoiding. Rejected.
3. **Expiry refreshed on every prompt** (the bound is liveness, not a TTL). Give `MANUAL_GOALS` a `renewal_ttl`
   (the 30-day retention is fine; 7 days would do) and renew it on EVERY prompt the session receives, cron ticks
   included, not only genuine human text as focus does. While the session lives the expiry never arrives, so the
   mode ends only at switch-back or with the session id; once the session is gone its file is reaped by the existing
   machinery. No parser changes on either side, no new invariant, and the EXPIRED notice is unreachable for a live
   session.

## Ruling

Option 3. The reason: it is the only one that satisfies both constraints at once, "the mode outlives nothing but
the session" (the owner) and "every entry expires" (the file contract both parsers enforce), without a special case
in any reader. Option 1 breaks the owner's rule at a boundary; option 2 breaks the contract and the supervisor's
fail-closed gate.

Implementation notes for the next agent, all inside the daemon:

- `renewal_ttl` returns the retention for `SessionMode.MANUAL_GOALS`; keep `FOCUS_TTL_SECONDS` for focus.
- The renew call site in `focus_mode_trigger` renews focus only on `is_genuine_text`; `manual-goals` must be renewed
  on every prompt, so either the registry's renew takes a per-mode predicate or the trigger renews the two labels on
  different conditions. Pin it: a tick-only session keeps the mode; a session with no prompt for the retention
  period loses its file.
- The docstring says what the bound is for: liveness of a dead session's file, renewed by any prompt, never an exit
  while the session runs. Drop the word TTL from it.
- The supervisor change stays exactly what Part 1 fact 3 says: add the label to `_SESSION_MODES_STORED_MODES`,
  `label=None`, pinned in the gate test. Nothing about expiry changes there.

## Owner's call or engineering?

Engineering. The owner fixed the observable behaviour (no clock ends the mode while the session lives; switch-back
or a new session does). How the storage contract represents "as long as the session lives" is implementation, and
option 3 meets the stated behaviour exactly. It would become the owner's call only if an implementation made a
clock-driven exit visible to a live session, which is what option 1 does and option 3 avoids. No question for the
owner.
