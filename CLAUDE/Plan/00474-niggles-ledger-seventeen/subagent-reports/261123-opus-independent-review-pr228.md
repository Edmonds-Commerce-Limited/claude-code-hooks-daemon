# Independent review: PR #228 (N709, secret guard link loop)

**Branch**: `fix-n709-secret-guard-bootstrap` at `54d7af7fc`. **Reviewer**: Opus, read-only. No protected file and no secret word list was opened. The probes used the PR's own hermetic fixture: 20 link-holding directories plus the loop, and a dummy `id_rsa` outside the project.

## Verdict

**The guard change is SAFE TO MERGE.** It weakens no deny that a loop-free tree did not already lack. **Renumber one release note before merging**: 087 collides with PR #225.

## Why the change is narrow

`_listing` (`src/claude_code_hooks_daemon/utils/secret_file_matching.py:4419-4435`) has one consumer, `CwdSet.could_be_link` (`:4438-4470`). That method reads `is_dir` only for NON-link entries (`:4464-4469`); a link entry returns True on `is_link` alone. So `_listed_kind` (`:4301-4323`) changes two things:

- **(a)** An entry whose link-following stat raised (ELOOP, or EACCES on the target) no longer turns the whole directory into `None`. `None` used to deny every word in every directory.
- **(b)** The `is_dir` value stored for a link is now computed without raising. Nothing reads that value.

A deeper word that passes through such a link is still judged by `_realpath_if_resolvable` (`:4953-4986`):

- A link chain gives realpath != normpath, so the word is a finding.
- A stat error that is not "no such path" raises `ResolutionFailedError`, and `@fails_closed` turns that into a deny.

## Differential probes: main vs branch, 30 shapes, after the computed move, Bash and Write routes agree

Still denied on the branch:

- `t2`, `chat`, `t*`
- `late`, `bin/late`, `kit/bin/late`, `./bin/late`, `bin/./late`, `bin//late`
- `*/late`, `../bin/late`, `kit/bin/../bin/late`
- `deny`, `bin/deny`, `kit/bin/deny`
- `deep/late`, `bin/sub/late`, `w00/.bin/tool`

Newly allowed: `bin/t2`, `bin/chat`, `kit/bin/t2`, `bin/t2/x`, `bin/../bin/t2`, `kit/bin/deny/x`, `r.md`, `bin/nothing`, `BIN/late`, `kit/*/late`, `bin/l*`, `b?n/late`.

**Key control.** I removed the loop and ran main again. Main then allows EXACTLY the same set. The branch makes a looped tree judge like a loop-free one, and introduces nothing new.

What the newly allowed words actually reach:

- The `t2`/`chat` paths end in ELOOP, so `open()` fails and nothing can be read. This answers question (2): `bin/t2` is not a protected file.
- `kit/bin/deny/x` fails with ENOTDIR.
- `BIN/late` names nothing on a case-sensitive filesystem.

## Findings, ranked

1. **MEDIUM, PRE-EXISTING, not caused by this PR. File as a new niggle.** A glob that is not in the first component reaches a link to a protected file and is ALLOWED on main.

   - Shapes: `kit/*/late`, `bin/l*`, `b?n/late`.
   - This happens even with no `cd` at all. From the project root, plain `cat kit/*/late` and `cat b?n/late` are allowed, while `cat kit/bin/late` is denied.
   - Mechanism: `could_be_link` (`:4455`, `:4468`) treats a word as globbed only when its first component is, and otherwise realpaths the literal glob text. That text gets ENOENT, so the word counts as no link. `_link_targets` never expands the glob either.
   - Before this PR a loop masked the gap. Only in a looped tree after a computed move, which is the case where everything was denied.

2. **HIGH, release-process. Release-note number collision.** See the next section.

3. **LOW, dead data.** The link's `is_dir` half of `_listed_kind` (`:4322-4323`) is never read by `could_be_link`. It is harmless, but the `(True, True)` fail-closed for an unclassifiable entry (`:4319`) matters only through `is_link`.

4. **LOW, tests.** Results of the four test runs:

   | Matcher                                                                         | Result                                                                                                                                                                                                                                |
   | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
   | Branch                                                                          | 23/23 pass                                                                                                                                                                                                                            |
   | Main (re-run)                                                                   | 14 fail. That is 13 allow/listing tests plus `test_an_entry_that_cannot_be_classified...`, which counts as "still denied" but fails on main because main's listing is `None`. The report's "2 listing-shape tests" is loosely worded. |
   | Fail-open mutant (`could_be_link` returns False)                                | 6 of the 9 deny-side tests fail: loop names x3, `late`, scandir-refused, unclassifiable entry.                                                                                                                                        |
   | Per-entry fail-open mutant (an unclassifiable entry counts as `(False, False)`) | The unclassifiable-entry test fails, so it pins `:4319`.                                                                                                                                                                              |

   Three deny tests still pass under the `could_be_link` mutant, so they do not pin it: `bin/late`, the deep `w03/zz/late`, and the literal protected name. They are denied by other paths (`_link_targets`/`bases_above_scanned`, and the literal match). They are still valid end-to-end guards, not dead tests.

5. **Fail-closed on genuine errors (question 3): kept.**

   - A `scandir` OSError still gives `None`, which denies every word (`:4427-4434`). It is pinned, and the mutant breaks it.
   - The listing has no entry cap. That is unchanged.
   - A race (an entry vanishing) behaves as before. `DirEntry.is_dir` maps ENOENT to False, which makes the entry OTHER.
   - **Not verified:** the EACCES-target link probe. The tests run as root, so `chmod 0` restricts nothing. The code path is covered by reasoning: `_link_kind` gives UNKNOWN, so the entry is a link, so the word is denied. A deeper word raises `ResolutionFailedError`, which denies.

## Release-note numbers (UNRELEASED/, origin refs, fetched)

**On main** (`d9d9e9d58`), `release-notes/`: 009, 010, 013, 014, 015, 017-025, 086. The other UNRELEASED folders hold no numbered files.

**Collision**: `087-human-approval-check.md` on `plan-00634-human-approval-check` (PR #225) and `087-secret-guard-link-loop-no-longer-denies-every-word.md` on PR #228. Renumber one of them to 088.

**No collision**: `026-coordinator-waiting-stop-must-notify-the-owner-on-the-bus.md` on `plan-00636-stop-guard` (PR #226). Note that it continues the 0xx series and not the 08x series.

**Conflict to expect**: PRs #225 and #226 both modify `config-changes/v3.77.0.yaml`. That is a merge conflict, not a number collision.

**Stale branches without a PR** also add notes: `origin/agent-a1feef6afbe418af7-5a658292` adds `085-secret-guard-allows-directories-only-globs.md`, and `origin/agent-a5947fd1e83f03452-ba288018` adds `003-automatic-upgrade-standing-authorisation-and-upgrade-lock.md`. Neither collides with main or with the open PRs.
