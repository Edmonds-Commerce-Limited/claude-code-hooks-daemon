# Guard effort and pragmatism review (Opus, read-only)

Scope: `secret_file_guard`, `quarantine_artefact_read_guard`, `flaggable_content_channel_guard`, `project_containment`,
`bash_safe_mode`, and the shared shell parsing they depend on. Commissioned by the coordinator for the owner. No code was
changed.

## Summary

**Verdict: the owner is right.** This area has gone off the rails on cost and on breakage. It has not drifted outside the
threat model as written. The bigger cause is in the model itself: "globs are in scope however rarely typed" plus "fail
closed on whatever you cannot read" is an obligation without a bound. Meeting it means walking the filesystem on the
PreToolUse hot path. Walks need caps, caps give verdicts that depend on size and host load, and each fix for one of those
breaks a normal command somewhere else.

- **Size**: area source grew from 2,970 lines (09-01) to 4,721 (09-20) to **17,951** (10-04), 6x in 5 weeks.
  `shell_expansion.py` (4,394 lines), `secret_file_matching.py` (3,573) and `shell_segmentation.py` (3,320) are each over 3x
  the project's own 1,000-line bound (N314).
- **Effort**: 163 non-merge commits and 53 merges since 09-04; +18,852/-3,838 source lines plus +16,993 test lines. Guard
  test functions went from 398 to 1,770. That is about 15% of all `src/` lines added in the period.
- **Review cost**: N101, one false-positive fix, took 24 Opus reports over 13+ fix rounds (327 KB of report text). Two
  more branches (N38, N53) were dropped after 9+ review rounds each, and six branches (55 entries) were judged "too
  tangled to merge". Saved guard-related report text alone exceeds 1 MB, and the tokens actually spent are a large
  multiple of that.
- **Breakage**: since 09-30, loosening commits outnumber tightening ones 22 to 9. In ledger 00474, area entries split 16
  false positive or breakage against 2 bypass. Clients filed 4 false-positive issues in 4 days (#64, #66, #68, #70) and no
  bypass reports. Three of them are `TooManyToEnumerateError` denials from the cap-fail-closed wave shipped in v3.67.0.
- **The cycle, in one day (10-04)**: 04:18 N220 tightening, then 05:28 the fix for its own false positive (`ls */*/*`),
  then 11:29 a new rule for N348, then 16:35 a 1,266-line capped tree walk (N130). The same day, N350 (`for d in dir/*`)
  was denied.
- **Live sample (this session)**: 7 of about 33 read-only Bash calls were denied and 3 drew noise advisories. None
  touched a protected file.

**Top 5 recommendations** (all except #1 need an owner decision):

1. Freeze tightening in this area now. Only false-positive narrowing and crash fixes land until #2 exists.
2. Build an ordinary-command regression gate: a corpus drawn from real session logs, run against all blocking handlers,
   over a fixture tree that holds protected files and a large ignored directory. Any ALLOW that flips to deny fails the
   change.
3. Amend the fail-closed rule. Deny on a literal protected name, or on a command that cannot be tokenised at all. Allow
   with an advisory when a cap, a deadline or cwd placement runs out.
4. Rip out the per-call filesystem walks (bare-glob expansion and the 250k-entry tree scan). Replace them with a cached
   index of protected-file locations from the existing SessionStart sweep. Also remove the ~1,600 lines of out-of-scope
   code that INVENTORY.md ties to FP-1 to FP-4.
5. Set a budget: 1 open branch in the area at a time, at most 2 review rounds per item (then drop or narrow), net
   non-positive line count, and a p99 latency bound per Bash call.

---

## 1. Effort

### 1.1 Source size over time (lines, `git show <commit>:<path> | wc -l` at the last main commit before each date)

| File                                  | 09-01 | 09-10 | 09-20 | 09-27 | 10-01 |   now |
| ------------------------------------- | ----: | ----: | ----: | ----: | ----: | ----: |
| `utils/secret_file_matching.py`       |   714 | 1,194 | 1,194 | 2,584 | 2,864 | 3,573 |
| `utils/shell_expansion.py`            |     0 |     0 |     0 | 2,113 | 4,256 | 4,394 |
| `utils/shell_segmentation.py`         |   217 |   390 |   828 |   962 | 2,990 | 3,320 |
| `pre_tool_use/secret_file_guard.py`   |   427 |   490 |   490 | 1,832 | 1,942 | 2,040 |
| `pre_tool_use/project_containment.py` |     0 |   683 |   695 |   952 | 1,048 | 1,070 |

Other area files now: `recursive_search.py` 509 and `protected_tree_scan.py` 356 (both created 10-04),
`command_position.py` 358 (10-02), `command_evasion.py` 398, `bash_flags.py` 244, `bash_safe_mode.py` 470,
`flaggable_content_channel_guard.py` 657, `quarantine_artefact_read_guard.py` 562.

**Area total (13 source files): 2,970 (09-01), 4,721 (09-20), 17,951 (10-04).** About 8.6% of the 208k lines in `src/`.

### 1.2 Commits and churn (non-merge commits touching the 13 area source files)

| Window      | Commits | First-parent merges | Lines added | Lines removed |
| ----------- | ------: | ------------------: | ----------: | ------------: |
| since 08-01 |     209 |                  58 |      22,718 |         4,107 |
| since 09-04 |     163 |                  53 |      18,852 |         3,838 |
| since 09-20 |     127 |                  46 |      16,933 |         3,593 |

- Whole repository, since 09-04: 896 commits touching `src/`, with +127,137 lines. The area therefore took 21% of the
  `src/` commits and 15% of the `src/` lines added.
- By month: 30 commits in August, 132 in September, 36 in October so far. Peak days were 09-24, 09-25 and 09-26, with 25,
  27 and 25 commits.
- Tests: 29 area test files, 19,408 lines, **1,770 test functions** now, against **398 on 09-01** and 617 on 09-20.
  Since 09-04, +16,993/-1,291 test lines.

### 1.3 Plans, ledgers, reports and review rounds

| Item                                                          | Count / size                                                                 |
| ------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| Plans whose subject is a secret-guard false positive          | 00306, 00356, 00412 decision doc (plus the 00272 original build)             |
| Ledger 00466 `NIGGLES.md`                                     | 5,787 lines, 383 KB                                                          |
| Ledger 00466 subagent reports                                 | 105 files, 1.67 MB; 47 of them guard/N24/N40/N101 reports (682 KB)           |
| N101 alone: `drule` 1-8, `dsec` 1-7, `fix` 2-9 and the opener | 24 Opus reports, 327 KB; commits labelled "round 1" up to "round 13b"        |
| Guard-defects review rounds (00466)                           | reviews 2 to 8, each with its own fix report                                 |
| Branches dropped as too tangled (00466 cleanup)               | 6 branches, 55 entries carried (`CARRIED-REFIX-BRANCHES.md`, 101 KB)         |
| N53 branch (commit walker for text-assembled commits)         | 9+ review rounds, then dropped; 4 entries later dismissed under threat model |
| N38 branch                                                    | reviews 6-9 and fix round 11+ recorded, then dropped                         |
| Ledger 00474 `NIGGLES.md`                                     | 2,028 lines, 133 KB; 56 reports (268 KB)                                     |
| Plan 00483 folder                                             | 497 KB incl. a 335 KB INVENTORY.md; 19 reports, 9 of them guard batches      |

Saved report output is a lower bound on spend. Each report is the final reply of an agent that read thousands of lines of
code and ran test suites, so the tokens consumed are a large multiple of those bytes.

## 2. Breakage of normal sessions

### 2.1 Ledger 00474 entries in the area (N253 to N351)

Classification is mine, from each entry's evidence. "Loosen" means the entry exists because a guard denied, or broke,
legitimate use.

| Entry    | Guard              | What broke                                                                     | Class           |
| -------- | ------------------ | ------------------------------------------------------------------------------ | --------------- |
| N255     | secret             | `git commit -F - <<'EOF'` denied (ENAMETOOLONG evaluation error)               | loosen          |
| N256     | secret             | quoted heredoc bodies glob-walked; a hit cap reads as an evaluation error      | loosen          |
| N265     | secret             | 2.2 s CPU on one realistic Python program; CI red                              | perf / breakage |
| N266     | flaggable          | denies greps that never touch a flagged path                                   | loosen          |
| N269     | secret             | single-quoted grep regex expanded as a filename glob                           | loosen          |
| N275     | secret             | Edit of a YAML workflow judged as an unreadable shell command                  | loosen          |
| N281     | secret             | 100k-char hostile-input scan timed out and denied on slow CI runners           | breakage        |
| N291     | secret             | grep regex inside `$( )` denied as a path mention                              | loosen          |
| N293/#68 | secret, quarantine | absolute glob with 2+ wildcards denied (TooManyToEnumerateError); client issue | loosen          |
| N312     | bash_safe_mode     | every one-command heredoc write denied after block-by-default; main red        | loosen          |
| N320     | containment        | `D=path && cmd > $D/f` denied, though the safe-mode advice leads to it         | loosen          |
| N321     | bash_safe_mode     | strict default broke 4 acceptance probes; found at release                     | breakage        |
| N338     | containment        | only the first `cd` followed                                                   | loosen (open)   |
| N339     | bash_safe_mode     | `{ …; }` and `for … do …; done` read as ungated (2 reproductions)              | loosen          |
| N348     | secret             | `ls */*/*/*` denied once the tree passed a size cap                            | loosen          |
| N350     | secret             | `for d in repos/* worktrees/*` denied on a lone `*`                            | loosen (open)   |
| N328     | bash_safe_mode     | the `set -e` prelude it demands does nothing under the Claude Code harness     | design          |
| N253     | secret             | exemptions parsed options from open lists                                      | tighten         |
| N283     | secret             | protected name in `rev:path` at the repo root missed                           | tighten         |

**Area: 16 loosen/breakage, 2 tighten, 1 design.** In the same ledger, ordinary-command false positives from other
shell-parsing guards add 11 more: N284, N285, N292, N298, N302, N311, N313, N341, N347, plus N36/N49/N58/N60/N65/N97
fixed as one batch. All of them share the parsing in this area.

### 2.2 Commits since 09-30 (the 44 area commits, classified by subject)

| Class                                | Count | Examples                                                                                                                   |
| ------------------------------------ | ----: | -------------------------------------------------------------------------------------------------------------------------- |
| Loosening (fixes a false positive)   |    22 | #70 regex x2, N291 x2, N293, N266 x2, N275, N256, N320, N339, X-1, FP batch 2, N241 x3, N312, quoted-text batch, bbabec672 |
| Tightening (closes a bypass)         |     9 | N283, N253, N220, N184/N221, N48/N87/N93, batch H, safe-mode block default x2, N275 review narrowing                       |
| Mixed                                |     2 | N130/N348 walk, N170/N242/N136                                                                                             |
| Other (perf, refactor, QA, messages) |    11 | N265, N289 x2, CI fix, N328, N348 message                                                                                  |

**Loosening to tightening: 22 to 9, about 2.4 to 1.** The wave that created most of these false positives is the
09-24 to 09-29 run: guard-defects reviews 2-8, N24/N40 fail-closed, and the N101 rounds. Over 80 commits in that window
mostly tightened: "fail closed on what cannot be seen", "over-cap fallback removed", "fail-close `_expand_glob_token`",
"close the shell-parser fail-opens". v3.67.0 shipped that wave on 09-30. Clients filed #64 and #66 the same day and #68 two
days later, all `TooManyToEnumerateError` denials of benign commands.

### 2.3 Client-filed issues (GitHub, last 30)

| Issue | Date  | Guard              | Shape                                                             | State  |
| ----- | ----- | ------------------ | ----------------------------------------------------------------- | ------ |
| #64   | 09-30 | quarantine         | any read-only command with a relative `**` when daemon cwd is `/` | closed |
| #66   | 09-30 | secret             | quoted `*` path pattern plus `{}` and a comma: evaluation error   | closed |
| #68   | 10-02 | secret, quarantine | absolute glob with 2+ wildcards ("still reproduces on main")      | closed |
| #69   | 10-02 | full-QA advisory   | UNSEEN advisory on `wc -c`, `head -c`, `grep -e` (N302)           | open   |
| #70   | 10-02 | secret             | `grep '.*ErrorCount'` denied as a glob overlapping `.vault-pass*` | open   |

No client issue in the period reports a bypass. Every client report in the area is a false positive. (#74, #75 and #76
are false positives in other guards that show the same pattern.)

### 2.4 The tighten, false positive, loosen cycle, timed (10-04)

| Time     | Commit    | Event                                                                                   |
| -------- | --------- | --------------------------------------------------------------------------------------- |
| 04:18    | 63163f185 | N220: expand a bare-`*` last component against the filesystem, capped, fail closed      |
| 05:28    | bbabec672 | review round 1: `ls */*/*` was denied by the cap; walk changed                          |
| later    | (ledger)  | N348 filed: `ls */*/*/*` (18,373 paths) still denied by size                            |
| 11:29    | 495217e2c | new rule R-SECRET-SCAN-INCOMPLETE so the deny at least names the cause                  |
| 16:35    | b5b5e9162 | N130/N348: 250k-entry capped tree walk plus git listings, +1,266/-271 lines in 13 files |
| same day | (ledger)  | N350 filed: `for d in repos/* worktrees/* …` denied on a lone `*`                       |

### 2.5 Live sample from this session

I ran about 33 Bash commands, all read-only. None read a protected file.

| Command shape                                                         | Verdict                                                              |
| --------------------------------------------------------------------- | -------------------------------------------------------------------- |
| `cd /workspace && ls …; ls …; git log …` (×3 variants, all read-only) | denied, R-BASH-SAFE-MODE-PRELUDE-MISSING                             |
| `cd CLAUDE/Plan && … grep -rl "N38\b" --include=*.md .`               | denied, R-SECRET-READ "recursive search would read a protected file" |
| `find . -name '*secret*'` under `CLAUDE/Plan`                         | denied, R-SECRET-BASH-MENTION on the `-name` pattern                 |
| `git ls-files -o … \| grep -ci "\.secret"`                            | denied, R-SECRET-BASH-MENTION on the grep pattern (N124 residual)    |
| `R=…/subagent-reports; … ls -d $R/* …`                                | denied, R-SECRET-BASH-MENTION on token `*/*` (FP-3 class)            |
| `bin/hooks-daemon find-plan niggles`, `… \| uniq -c` (×2)             | advisory "UNSEEN interpreter inline code" (N302/#69)                 |

Every tracked, untracked and ignored file under `CLAUDE/Plan` was checked with `git ls-files`, and none matches the
protected glob. So the recursive-grep deny is a false positive. A likely cause, not confirmed with `probe`: batch F judges
paths "from the hook's cwd and each literal cd target", and `.` judged from `/workspace` reaches the project's word list.
My sample is biased, because I was researching this guard and typed its name. The `;` denials and the `$R/*` denial are
not biased that way.

## 3. Value: did the work stay inside the threat model?

The threat model (`CLAUDE/ARCHITECTURE.md` § "Threat model: the agent is careless, not hostile", written 10-02) puts two
kinds of shape out of scope. Limb 1 is text not visible at call time. Limb 2 is a shape whose only purpose is to defeat a
parser.

**Before 10-02 the work drifted well outside it.** INVENTORY.md part A lists about 1,600 lines in `shell_expansion.py` and
`shell_segmentation.py`, plus about 25 in `secret_file_matching.py`, that serve only limb-1 or limb-2 shapes. Examples:
quote-exact brace grouping for `.p-{"} x",q}`, ANSI-C `\x` decoding, percent-decoded `file:` URLs, `> >(bash)` output
process substitution, symlink loops, and the alias/function/PATH "rebinding" machinery. Four of these branches cause
verified in-scope false positives:

- FP-1: `x=${P:-"/usr"}; awk '{print $1}' f` is denied as unreadable.
- FP-2: `cd "$DIR"`, `trap`, `shopt` or `source` before a commit heredoc gets the message denied.
- FP-3: `ls "$d"_rsa`-style words become a glob.
- FP-4: `echo {1..300}` and `touch f{1..1000}` are denied.

The shared parsing adds another 550-640 lines of limb-1 rebinding code (INVENTORY part D). This is what the N101 rounds
and guard-defects reviews 6-7 built. The trigger was adversarial security reviews ("dsec", "close the shell-parser
fail-opens") rather than anything a careless agent typed.

**After 10-02 the work is formally in scope, and that is the problem.** Each Task 3.1 batch was triaged IN-SCOPE:

- N220 `cat dir/*`;
- N143/N144 `find . | xargs rg`;
- N130 a Grep tool call at the repo root;
- N184/N221 `..` and `cd`.

The model calls these in scope "however rarely typed", and says a protected file stays protected "against every ORDINARY
read route, including `Grep -l`". Closing them honestly takes filesystem truth: which files `dir/*` or `grep -r .` would
read. That truth costs walks, which need caps. The model then requires a cap hit to fail closed, so verdicts come to depend
on tree size (N348) and host load (N222, N281, N346). The ruling bounded which shapes must be caught. It did not bound
what catching them may cost, or how many ordinary commands may be broken to do it.

**Realism of the closed bypasses**, judged against a careless agent:

| Bypass closed                                                | Realistic for a careless agent?                                                 |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------- |
| literal name via `cat`, `grep`, `python -c`, `bash -c '…'`   | yes; this is the core value and was cheap                                       |
| `rev:path`, `~/`, `./`, `..` collapse                        | yes, cheap token normalisation                                                  |
| `grep -rn API_KEY .` printing a protected file's lines       | **yes, the most plausible real leak**; deserves a cheap, coarse rule            |
| `cat dir/*` where `dir` holds a protected file               | plausible but rare; a one-`listdir` check covers it                             |
| bare `*/*/*/*` expansion to depth N                          | almost never reaches a protected file in practice; costs size-dependent denials |
| quoted `}` in brace groups, `$'\x…'`, `%73` URL, `> >(bash)` | no (limb 2)                                                                     |
| alias/function/PATH rebinding of a heredoc sink              | no (limb 1 + 2)                                                                 |
| `$VAR` fused to a name edge                                  | no (limb 1)                                                                     |
| 300+ brace spellings                                         | no; the cap exists only for hostile input                                       |

## 4. Complexity cost

- **Hot-path work per Bash call**: up to 26 named caps and budgets in the area. They include `SCAN_DEADLINE_SECONDS = 5.0`,
  `TREE_SCAN_MAX_ENTRIES = 250_000`, `_MAX_BARE_GLOB_FS_EXPANSIONS = 100_000`, `DIRECTORY_SCAN_MAX_ENTRIES = 5000`,
  `_DP_MAX_CELLS = 20_000`, `_BRACE_SCAN_BUDGET = 250_000` and `DEFAULT_MAX_BRACE_SPELLINGS = 256`. Every one of them is a
  point where the verdict depends on size or load.
- **Measured latency** (N130 design report): a full scandir of `/workspace` costs 3.28 s (1.83M entries, 1.15M of them
  under ignored `untracked/`). A bare glob of depth 4 or 5 costs 0.32-0.62 s to expand and match. A 200k-file tree walk
  costs 0.2-0.9 s, and 1M entries cost 1-4.6 s. The chain budget is 20 s and the client's is 30 s. A client timeout fails
  the chain. N265 measured 2.2 s CPU for one Python program before it was fixed.
- **Rules**: secret_file_guard alone can answer with 6 rule IDs: READ, BASH-MENTION, SCRIPT-AUTHOR, EVALUATION-ERROR,
  COMMAND-UNREADABLE and SCAN-INCOMPLETE. An agent cannot easily tell a real hit from a cap or a parse failure without
  reading the reason closely.
- **Tests**: 1,770 functions, about 4.4x in 5 weeks. A linearity harness (N349) and load-scaling helpers (N344) now exist
  largely to keep these guards' own tests from flaking.
- **Maintenance**: three modules are over 3,300 lines. Any fix touches the shared parser, which 10+ guards consume. Per
  the 00466 cleanup, six branches became unmergeable, and coordinator merges repeatedly left main red: N286, N303, N310 ×6,
  N312, N318 and N321.

## 5. Recommendations (prioritised)

Each item is marked **[OWNER]** where it needs an owner decision, **[COORD]** where the coordinator can act.

### R1. Freeze tightening in this area now. [COORD, effective now; OWNER to confirm]

No new deny shape, no new cap and no new parser branch in `secret_file_guard`, `quarantine_artefact_read_guard`,
`flaggable_content_channel_guard`, `project_containment` or `utils/shell_*`/`secret_file_matching`. Allowed: narrowing
fixes for verified false positives, crash fixes and deletions. The freeze holds until R2 is green on main.

### R2. Build an ordinary-command regression gate. [COORD to build; OWNER to approve as a merge gate]

- Source: real commands from this repository's daemon logs and transcripts, which every session already captures.
  Include at least 2,000 commands, de-duplicated by shape, plus every command named in a false-positive ledger entry or
  client issue. N79's 171-command corpus is the seed.
- Run every blocking PreToolUse handler, not only the secret guard. Use a **realistic fixture tree**: a protected file at
  root and at depth 2, a 50k-entry ignored directory, a nested worktree, and a cwd different from the project root. The
  existing corpus never caught `ls */*/*/*`, `for d in dir/*` or `grep -r .` after a `cd`, because it has no filesystem.
- The gate: every corpus command must ALLOW. Any guard change that flips one fails, unless the owner adds a row
  explicitly.
- Put a matching false-positive budget on releases: any client-filed false-positive issue in this area blocks the next
  minor release until it is fixed or the shape is accepted.

### R3. Narrow the fail-closed rule to what actually protects secrets. [OWNER: amends ARCHITECTURE.md "What this ruling does not change"]

The minimum that protects protected files from a careless agent:

1. Tool path match: Read, Write, Edit, NotebookEdit, and Grep with an explicit path (exact and cheap).
2. A Bash or authored-script token that literally names a protected path after quote removal and `~`, `./`, `..` and
   `rev:` normalisation, interpreter one-liners and literal `bash -c` included. This is already done and cheap.
3. A glob token whose literal text can overlap a protected pattern (stem check, no filesystem).
4. A recursive search, or a `dir/*`, whose root contains a known protected file. Answer this from a cached index (R4),
   not a per-call walk.
5. The `sensitive_content` commit gate as the backstop for the outcome that matters most, secrets reaching git.

Proposed rule: **deny** on 1-4 and on a command that cannot be tokenised at all. **Allow with an advisory** (and log)
when a cap, a deadline, brace enumeration or cwd placement runs out. This removes every size- and load-dependent verdict
(N222 guard half, N281, N348, #64/#66/#68). The trade-off, stated honestly: a command crafted to exhaust a cap passes.
That is limb 2 by the model's own definition, and a hostile agent can stop the daemon anyway.

### R4. Rip-out and simplification list. [OWNER per item; ARCHITECTURE.md says removal is an owner decision]

| Candidate                                                                                       | Lines (approx) | Replace with                                                                                                                                                      | Removes                            |
| ----------------------------------------------------------------------------------------------- | -------------: | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| Bare-glob filesystem expansion (`_bare_glob_mention`, `_expand_glob_token` FS walk, 100k cap)   |           300+ | stem-overlap check plus one `listdir` of the glob's literal directory                                                                                             | N348, N350, #68 class              |
| Per-call recursive tree scan (`protected_tree_scan.py`, the walk half of `recursive_search.py`) |           600+ | index of protected-file locations from the existing SessionStart `protected_among` sweep, refreshed lazily; deny if a search root is an ancestor and not excluded | load/size verdicts, hot-path walks |
| Rebinding machinery (SEG ~2335-2885), FP-2                                                      |           ~550 | treat only alias/function/PATH as rebinding, or nothing                                                                                                           | FP-2                               |
| `${…}` quote raise and quote-exact `_BashBraces` (SE ~363-388, 455-640, 823-872), FP-1          |           ~475 | plain brace expansion; unbalanced quoting inside braces is allowed                                                                                                | FP-1                               |
| `$VAR` collapsed to `*` (SE ~2782-2833, 2903-2954), FP-3                                        |            ~40 | drop (limb 1)                                                                                                                                                     | FP-3, `$R/*` deny                  |
| Brace-spelling cap fail-closed (SE ~206-275), FP-4                                              |            ~70 | past the cap, judge the literal residue and allow                                                                                                                 | FP-4                               |
| Opaque transform, `> >(bash)`, `$'\x'`, `%xx` URL, fd aliases, symlink-loop branches            |           ~260 | delete (limb 1/2, no FP but pure maintenance)                                                                                                                     | maintenance                        |

Expected effect: the three oversized modules shrink by roughly 2,000-2,500 lines, with no loss on any route in R3.

### R5. A budget for this area. [OWNER]

- At most **1 open branch** in the area at a time (00483 Task 3.1 now allows 3 across the plan).
- At most **2 review rounds** per item. If round 2 still finds issues, ship the narrower half or drop the item. Do not
  iterate further. N101 (13+ rounds), N38 and N53 (9+ each, both dropped) are the counter-examples.
- **Reviewer brief**: a review of a false-positive fix may not raise a new bypass unless it is an ordinary command a
  careless agent would type in normal work, shown with an example. Other ideas go to the ledger for triage, not into the
  branch. Adversarial "dsec" rounds are not run on false-positive fixes.
- **Size**: each change in the area is net non-positive in source lines until the three modules are under 2,000 lines
  each. `check_module_length.py` already reports this; make it a gate for these three files.
- **Latency**: p99 at most 50 ms per Bash call for the area's handlers on this repository, measured in CI. No more than
  one `listdir` per glob on the hot path.

### R6. `bash_safe_mode`. [OWNER: revisits the N308 ruling]

The ruling said strict mode "should be harmless". The evidence says otherwise:

- N312 (every heredoc write denied, main red);
- N321 (release-time acceptance failures);
- N339 (compound syntax, 2 reproductions);
- N320 (its own advice leads into a containment deny);
- 3 of my read-only commands denied here.

N328 adds that the `set -e` prelude it asks for does nothing under the Claude Code harness. Options:

- (a) return to `only_with_mutator: true`, the earlier config, so read-only sequences pass;
- (b) keep block mode but replace the shallow `;` splitter with the compound-aware segmentation that already exists;
- (c) drop it to warn.

I recommend (a). It is a one-line config change, and it keeps the protection where a mutator is involved.

### R7. In-flight items

| Item                          | What it is                                                                                       | Recommendation                                                                                                    |
| ----------------------------- | ------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| N350                          | `for d in dir/*` denied on a lone `*`                                                            | Probe it. If R4's bare-glob removal is approved, it disappears; otherwise make a narrowing fix only. **Keep**     |
| N229                          | `@FILE` and attached short-option values (`-fFILE`) unseen                                       | Strip a leading `@` or `-X` in the literal tokeniser, at most ~20 lines. Otherwise **drop**                       |
| N23                           | recovery_cron_advisor phase on a singleton (concurrency bug)                                     | **Keep**; real bug, not guard parsing                                                                             |
| N28                           | containment: `cd /tmp && echo x > rel.txt` allowed                                               | **Defer**; containment is not secret protection. Fix only if it reuses the existing cd tracker with no new parser |
| N35                           | daemon_sync_after_merge uses the session root after `cd <worktree>`                              | **Keep**; small correctness fix                                                                                   |
| N53                           | WorktreeCreate exit 127 (00466 numbering)                                                        | **Keep**; real infrastructure bug                                                                                 |
| N75                           | Write/Edit content route misses `.pyw`, `.cjs`, `.mts`, Ruby `spawn`, PHP `passthru` and similar | Add file extensions only (one list). **Drop** the per-language call shapes                                        |
| N76                           | Python argv `['/bin/bash','-c',…]` missed by the regex fallback and Go reader                    | **Drop** (dismiss as low value: a script that launches a shell to read a protected file is far from careless use) |
| N79                           | false-positive corpus 171 of 200                                                                 | **Promote** into R2; it becomes the gate                                                                          |
| N86                           | over-length AF_UNIX path, liveness indeterminate                                                 | **Keep** (infrastructure)                                                                                         |
| N91                           | extra `protected_paths` ignored by capture/lint seams if the first call precedes init            | **Keep**; small config-plumbing bug that under-protects real config                                               |
| N95                           | test fixtures run git under the 5 s hook budget                                                  | **Keep**; fold into the N344 load-scaling helper                                                                  |
| N98                           | AF_UNIX fallback socket shared across hostnames                                                  | **Keep** (infrastructure)                                                                                         |
| N197                          | about 28 quadratic `shlex` call sites                                                            | **Keep, low**; a mechanical swap to `linear_shlex` plus a semgrep ban, no new parsing                             |
| N222                          | wall-clock bounds in tests; guard scan deadline is wall-clock                                    | Test half **keep**. Guard half is resolved by R3: a deadline allows with an advisory                              |
| N260                          | local gate runs project-handler tests differently from CI                                        | **Keep** (QA infrastructure)                                                                                      |
| N74                           | `grep -r` above a protected path (NEEDS-OWNER)                                                   | Resolve with R4's cached index, not a walk                                                                        |
| O1-O5 (00483 open question 3) | caps as constants, Grep ALL view, deny past cap, quarantine fail-closed, index deferred          | Superseded if R3 and R4 are approved: no deny past a cap, and the index (O5) becomes the primary design           |

Of the 16 in-flight items, only N350, N229, N75 and N76 are guard-parsing work. The others are ordinary infrastructure
or QA bugs and are not part of the problem.

## 6. Where the evidence points the other way

- The core routes work and are cheap: literal-name mentions, the tool path match, one level of `$( )`, literal `bash -c`
  and interpreter one-liners. The N283 `rev:path` fix and the N184/N221 `..` collapse are cheap and worthwhile.
- `grep -rn KEY .` dumping a protected file is a genuinely plausible careless leak. Some recursive-search rule is
  justified. The disagreement is only about cost: a per-call 250k-entry walk against a cached index.
- The 00483 audit itself (INVENTORY.md, triage, the two-part test) is good work. It produced the evidence this report
  relies on, and it has already dismissed real out-of-scope items (N135, N176, N177, N189). Since 10-02, the drift has been
  in cost and fail-closed policy, not in scope classification.
- Some recent work reduced friction: N346 and N348 made deny reasons honest, and N265 halved scan CPU. These are not
  waste. They are the cost of the policy, paid after the fact.

## Method and caveats

- Line counts come from `git show <commit>:<path> | wc -l` at the last main commit before each date. Commit counts come
  from `git log --no-merges` and `--first-parent --merges` over the 13 named source files. Test counts are `def test_`
  occurrences, so parametrised cases are undercounted.
- The loosen and tighten classification of commits and ledger entries is mine, from subjects and entry evidence. It is
  approximate, but the direction is not close.
- The live sample in 2.5 is small and partly biased, as noted there. The recursive-grep false positive's cause is
  inferred, not probed.
- Files read: `CLAUDE/ARCHITECTURE.md` threat model; 00483 PLAN.md, INVENTORY.md parts A and F, TRIAGE files;
  00474 NIGGLES.md and PLAN.md index; 00466 NIGGLES.md headings and N101; the N130 design report; RELEASES v3.67.0 and
  v3.68.0 headings; GitHub issues #38 to #78.
