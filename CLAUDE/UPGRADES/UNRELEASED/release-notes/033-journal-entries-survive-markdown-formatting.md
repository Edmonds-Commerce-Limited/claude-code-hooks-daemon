# Callout: a markdown formatter can no longer strand a journal entry

**Plan**: 00594
**Audience**: client projects

A QA pipeline that ran `hooks-daemon format-markdown <dir>` rewrote plan
journal entry headings. The commit gate (`journal-dayfile-is-today`) treats
an entry as immutable, so the rewritten file could be neither committed nor
restored by an agent, and every later run reformatted it again. Two fixes:

- `format-markdown` now skips plan journal files. A directory walk passes
  over them, and an explicitly named entry is reported as skipped. The
  edit-time formatter already did this.
- The journal immutability check, at both edit and commit time, no longer
  blocks a change that is whitespace-only: the same words in the same order.
  Any added, removed or changed word is still blocked.

If one of your entries is already stuck with a whitespace-only change, you
can now commit it.
