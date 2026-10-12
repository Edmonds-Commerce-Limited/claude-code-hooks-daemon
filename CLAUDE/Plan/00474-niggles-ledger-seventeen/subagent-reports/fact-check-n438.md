# Fact check: N438 (commit 39a964554)

Result: 13 claims: 12 verified, 0 refuted, 0 unverifiable. One verified claim carries a caveat (C11).

## REFUTED claims

None.

## Caveat

C11: Plan 00264 mentions `shlex` once, in Task 2.3, as a failure case ("a `shlex` parse failure", PLAN.md:147). It never spells out "its own shlex parse of gh flags". The inference is reasonable but implicit. A tighter wording would be "plans to parse gh flags (Task 2.2, 2.3 mention shlex)".

## Table

| #   | Claim                                                                                                                          | Verdict              | Evidence                                                                                                                                       |
| --- | ------------------------------------------------------------------------------------------------------------------------------ | -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `_BODY_FILE` is at `issue_filing_gate.py:105`                                                                                  | VERIFIED             | Line 105: `_BODY_FILE: Final[re.Pattern[str]] = re.compile(`                                                                                   |
| 2   | `_REPO_FLAG` is at line 93                                                                                                     | VERIFIED             | Line 93, same form                                                                                                                             |
| 3   | `_BODY_FILE` is used with `finditer` over the raw segment                                                                      | VERIFIED             | Line 375: `matches = list(_BODY_FILE.finditer(segment))`                                                                                       |
| 4   | `_REPO_FLAG` uses `.search()`                                                                                                  | VERIFIED             | Line 293: `flag = _REPO_FLAG.search(segment)`                                                                                                  |
| 5   | `_BODY_FILE.finditer` on `--title 'git merge -F - reads stdin' --body-file r.md` yields `-` then `r.md`                        | VERIFIED             | Run with the main venv: groups `[(None, None, '-'), (None, None, 'r.md')]`                                                                     |
| 6   | For `gh issue create --title 'see -R someone/else' --repo <this tracker> --body-file r.md`, `_REPO_FLAG` picks `someone/else'` | VERIFIED             | `_REPO_FLAG.search(c2).groups()` returned `(None, None, "someone/else'")`                                                                      |
| 7   | `_filing_segments` returns `[]` for that command, so the gate stands down                                                      | VERIFIED             | `_filing_segments(c2, None)` returned `[]`. The slug used was `UPSTREAM_REPO_SLUG`.                                                            |
| 8   | With a plain title the same command is judged                                                                                  | VERIFIED             | `_filing_segments` on the plain-title variant returned a one-element list holding the segment                                                  |
| 9   | The first bug refuses a valid report with "body is piped in on stdin"                                                          | VERIFIED (partly)    | Lines 114 and 375 onward show `-` is treated as stdin. Claim 5 shows `-` is extracted. The exact deny text was not checked.                    |
| 10  | The PLAN.md header's "143 rows" for STATUS-INDEX.md                                                                            | VERIFIED             | \`grep -c '^                                                                                                                                   |
| 11  | Plan 00264 is "comment size cap, Not Started" and plans a shlex parse of gh flags                                              | VERIFIED, see caveat | Directory `00264-github-comment-size-cap`. PLAN.md:3 `**Status**: Not Started`. shlex appears only at line 147.                                |
| 12  | Counts: 120 ✅, 16 🔄, 7 🚫, 3 🟡, 1 ↩️, 4 ⬜, giving 20 in progress or graduated (16+3+1)                                     | VERIFIED             | Whole-file `grep -c` on STATUS-INDEX.md: ✅ 120, 🔄 16, 🚫 7, 🟡 3, ↩️ 1, ⬜ 4                                                                 |
| 13  | N438 sits among the 16 🔄, alongside N280, N425, N431 and N433                                                                 | VERIFIED             | The index shows 🔄 on N438 (line 7), N433, N431, N425 (its status is "✅ Fixed; 🔄 CI to confirm") and N280 ("✅ Guarded (AN); 🔄 follow-ups") |
