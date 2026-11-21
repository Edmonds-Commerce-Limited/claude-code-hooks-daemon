## 20:18 · action · — — Task 3.8 precondition: finish an unrecorded adoption

Task 3.8 precondition unit 5 (finish an adoption a crash left without a record) closed.

`unfinished_adoptions(store)` lists adopt events with no record and no expired event. `finish_adoption`
(under the lock) refuses a torn events file or index, an already-recorded id, an expired id, an unknown id,
an entry name the event's path does not end in, an archive absent from the store (crash before the move)
or not a singly-linked regular file; otherwise it runs adopt's own `_prove` against the original and
appends the record with `packed_at` = the event time. Every refusal is `AdoptRefused` with the archive left
in place (still refused by `discard_unrecorded`). Nothing moves, so the pinned rename and deletion surface
sets are unchanged. Moving the archive back beside its original is deliberately not offered. Not wired to
the CLI. Targeted QA: tests/unit/core/test_scratch\_\*.py all pass; ruff, black, mypy --strict clean.
