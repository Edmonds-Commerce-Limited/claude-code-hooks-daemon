# Security review — check `F-HYG`

**Check**: `F-HYG` — "On-disk hygiene of protected material: modes, gitignore
coverage, stray copies under `untracked/`."
**Run**: Routine 00001, run 2026-001, FULL sweep.
**Scope**: current on-disk state of this checkout. One check, nothing else.
**Findings**: 3.
**Confidence**: high on 1 and 2, moderate-high on 3 (see each).

## A note on spelling

The protected globs are referred to below by their source line and a short
label, never spelled out. Spelling one in this file gets the write denied by
`secret_file_guard`'s Write/Edit content scan
(`src/claude_code_hooks_daemon/handlers/pre_tool_use/secret_file_guard.py:270`)
— the guard cannot tell a security report from a disclosure, and it is right
not to try. The literal set is at
`src/claude_code_hooks_daemon/utils/secret_file_matching.py:54-61`. Labels:

| Label      | What it is                                                                |
| ---------- | ------------------------------------------------------------------------- |
| `G1`       | The word-list extension, as a BOTH-EDGES wildcard glob (the first entry)  |
| `G2`–`G4`  | Three spellings of a vault-password filename                              |
| `G5`, `G6` | Two classic SSH private-key filenames                                     |
| `I1`, `I2` | The two EXACT-suffix forms of the same extension as `G1`, in `.gitignore` |
| `I3`       | The `.example` variant of that extension, in `.gitignore`                 |

No protected material is quoted anywhere in this report, and none was read.

---

## Finding 1 — the ignore list and the protect list are two independent hardcoded sets, and the ignore list is strictly narrower

**Citation**

- `src/claude_code_hooks_daemon/handlers/session_start/gitignore_safety_checker.py:25-51`
  — `_REQUIRED_GITIGNORE_PATTERNS`, a literal 5-tuple. Its only secret-related
  entries are `I1` and `I2`, both described in-line as "sensitive_content
  handler's secret word list — must never be committed".
- `src/claude_code_hooks_daemon/utils/secret_file_matching.py:54-61`
  — `DEFAULT_PROTECTED_PATTERNS`, a literal 6-tuple: `G1`–`G6`.
- `.gitignore:238-242` — the repository's own secret block: `I1`, `I2`, `I3`.

Nothing imports both. There is no derivation, no assertion, no test in common.

**What it concretely allows**

`G1` is a both-edges wildcard; `I1`/`I2`/`I3` are exact suffixes. Any filename
that carries the protected extension with *anything after it* is protected and
not ignored. Worked example, using only the rename the brief asks about: take
the word list under `.claude/`, rename it with a `.old` suffix. The new name
still matches `G1`, so every read route stays denied — `Read`, `Grep`, `cat`,
an interpreter one-liner, all of it. It matches none of `I1`, `I2`, `I3`, and
none of the backup patterns (`.gitignore:150-162` covers `.bak`, `.bak.`,
`.bak-`, `.orig`, `.rej`, `~` — not `.old`, not `.2`, not a date suffix, not
`.json`). So `git add -A && git commit` stages and commits it, and no handler
objects. The guard has made the file unreadable to the agent that would have
noticed it, while leaving it committable.

`G2`–`G6` are worse: they have **no required gitignore entry at all**, and this
repository's `.gitignore` contains no rule for any of them. An SSH private key
dropped at the repository root under the name at `secret_file_matching.py:60`
or `:61` is read-protected and fully stageable, today, with no advisory and no
block at any point in the sequence.

The third leg is the extension point. `protected_paths` under
`secret_file_guard` (resolved at `secret_file_matching.py:163-231`) is the
documented, supported way for a downstream project to protect its real
secrets, and `mode: replace` lets a project discard the shipped defaults
entirely. Every pattern added that way widens the protected set and can never
widen `_REQUIRED_GITIGNORE_PATTERNS`, which is a literal tuple in a module that
does not import the resolver. A client who does exactly what the documentation
tells them gets read protection with no ignore coverage, and the one advisory
whose whole job is ignore coverage stays silent about it.

**The class**

*A guard whose protected set is resolved dynamically, paired with a second
guard whose equivalent set is a hardcoded literal, with no assertion that the
second covers the first.* The test for membership: two constants in different
modules describe the same real-world category, one is derived from config and
one is not, and widening the derived one silently narrows effective coverage.
This is not specific to secrets — it is the shape, and the shape is what the
register wants.

**Why the test suite does not catch it**

`tests/unit/handlers/session_start/test_gitignore_safety_checker.py` asserts
the handler's behaviour against *its own* list; `tests/unit/utils/test_secret_file_matching.py`
asserts matching against *the guard's* list. Both pass. Neither can fail on a
disagreement *between* the lists, because neither test imports the other
module's constant. Consistency between two hardcoded constants in separate
modules is not a property that either unit suite is capable of expressing —
each is individually correct and jointly they say nothing.

**Detector hypothesis**

A QA check in `scripts/qa/` that calls `sfm.resolve_configured_patterns()`,
synthesises one representative filename per returned glob into a scratch
directory, and asserts `git check-ignore` claims each one. It fails, naming the
glob and a suggested `.gitignore` line. This checks the *effective* set, so it
follows a project's `protected_paths` automatically — which is the whole point,
and is what the current advisory cannot do.

*Likely false positives*: a protected glob a project deliberately tracks (an
`.example` template matching the extension is the obvious one, and this
repository had exactly that until 2026-09-01); a `protected_paths` entry added
to suppress read *noise* rather than to protect a secret (a public certificate
sharing an extension with a private key is the case `secret_file_matching.py:51-53`
already calls out as the reason those extensions are not shipped by default);
an absolute-path entry, which has no meaningful representative filename. I
would expect roughly one legitimate exemption per mature project, so the check
needs a named opt-out key from day one or it will be disabled rather than
satisfied. Noise: low, but non-zero and concentrated in `.example` files.

**Confidence**: high. Both constants read directly from source; the gitignore
semantics are unambiguous from `.gitignore:238-242`; the absence of any
cross-import verified by grep over `src/` and `scripts/`.

---

## Finding 2 — the hygiene checker reads the index, never history, and its own remedy produces a state it then calls clean

**Citation**

- `src/claude_code_hooks_daemon/handlers/session_start/secret_file_hygiene_checker.py:133-142`
  — `_scan_repo` builds its universe from three `git ls-files` calls:
  `--cached`, `--others --exclude-standard`, `--others --ignored --exclude-standard`. All three describe the tree *now*. No call reads history.
- `:49` — `_ISSUE_TRACKED = "git-tracked -- untrack it: git rm --cached <path>"`.
- `:158-163` — the three issues are computed purely from membership in those
  present-tense sets.

**What it concretely allows**

This is not hypothetical here. The word list's `.example` sibling under
`.claude/` was **committed** in `b317c854` (2026-08-07, "Plan 00201:
sensitive-content guard + the bug it hid from itself") — 31 lines, per
`git show --stat` — and **untracked and gitignored** in `6cc845d1`
(2026-09-01). It is absent from `HEAD` and absent from disk. The blob remains
reachable in history, in this clone and every other, for ever.

Run the checker against this checkout today and it reports nothing. That is the
correct answer to the question it asks and the wrong answer to the question
`F-HYG` asks.

The sharper edge is the remedy. `git rm --cached <path>` is the checker's own
printed instruction, and it is specifically carved out of the read guard for
this purpose (`secret_file_matching.py:1117-1153`, with a genuinely careful
`--pathspec-from-file` exclusion). An operator who follows it moves the path
from `tracked` into `ignored`, the advisory goes quiet on the next session, and
the material is still in every clone, every fork and every CI cache. The
silence is then read as *resolved*, because the advisory gave the instruction
and the advisory stopped complaining. A remedy that converts a true finding
into a false clean is worse than no remedy, because it consumes the one signal
that would have prompted the force-push conversation.

Note that this project *knows* the history problem exists and has tooling for a
different instance of it: `sensitive_content`'s config carries two keys
"consumed by `scripts/qa/check_git_history.py`, not by the handler"
(`.claude/hooks-daemon.yaml:219-226`), with a comment explaining that already-
committed history "can only be cleaned by a force-push, which only a human may
run". That reasoning is about secret *terms* in commit *metadata*. The same
reasoning applied to a protected *path* in commit *content* has not been made,
and the hygiene checker is the handler that would have made it.

**The class**

*An advisory that answers a present-tense question, whose remediation advice
changes the present-tense answer without changing the underlying fact.* Test
for membership: does following the advice make the advisory stop firing while
leaving the risk in place? If yes, the advisory is worse than silence, because
it has spent the operator's attention and returned a false receipt.

**Why the test suite does not catch it**

`tests/unit/handlers/session_start/test_secret_file_hygiene_checker.py` builds
fixture repositories and asserts the three issue strings appear for the three
corresponding states. Every test constructs a *current* state. Catching this
would need a fixture that commits a protected file and then removes it in a
second commit, then asserts the handler still reports — a shape no test
constructs, because the handler's documented contract is working-tree hygiene
and the tests encode that contract faithfully. The tests are not wrong; the
contract is narrower than the check it is standing in for.

**Detector hypothesis**

`git log --all --full-history --diff-filter=A --name-only --format=` , piped
through `sfm.resolve_configured_patterns()`, as a `scripts/qa/` Detector beside
the existing `check_git_history.py` (which already owns the "history needs a
human" framing and the allowlist keys to go with it). Reports each protected
path that ever entered history, with the introducing commit. Verified working
during this review — it is what surfaced `b317c854`.

*Likely false positives*: `.example` and template files that match a protected
glob and never held a real secret — precisely this repository's only hit, so
the very first run produces a finding that must be permanently allowlisted;
vendored subtrees; test fixtures that deliberately construct protected names. A
shallow or partial clone cannot answer at all and must say "could not look"
rather than pass — the `--full-history` walk over a truncated graph returns a
clean result that means nothing. Noise: moderate on first run, near-zero after,
since the finding set is append-only and small. It shares
`check_git_history.py`'s allowlist design, so the exemption mechanism already
exists.

**Confidence**: high on the mechanism and on the historical instance (both
verified directly). I deliberately did **not** establish whether those 31 lines
held real terms or placeholders — see *Limits* below.

---

## Finding 3 — nothing gates a protected PATH at staging or commit time, and the one content-side scanner that would compensate is inert in this checkout

**Citation** — the complete set of `path_is_protected` / `find_protected_mention`
consumers outside the matching module itself:

| Site                                                              | What it does with the answer                              |
| ----------------------------------------------------------------- | --------------------------------------------------------- |
| `handlers/pre_tool_use/secret_file_guard.py:210,226,270`          | Denies a read (Bash mention, tool path, authored content) |
| `handlers/pre_tool_use/staged_lint_gate.py:249`                   | **Skips** the file                                        |
| `handlers/post_tool_use/lint_on_edit.py:229`                      | **Skips** the file                                        |
| `daemon/payload_capture.py:67,71`                                 | Suppresses a capture                                      |
| `daemon/server.py:1359`                                           | Passes patterns through                                   |
| `handlers/session_start/secret_file_hygiene_checker.py:155,193`   | Advises                                                   |
| `handlers/pre_tool_use/quarantine_artefact_read_guard.py:219,248` | Denies a read                                             |
| `handlers/pre_tool_use/flaggable_content_channel_guard.py:222`    | Denies a channel                                          |

Not one of them denies `git add` or `git commit` on the grounds that a staged
path is protected.

**What it concretely allows**

`staged_lint_gate.py:236-256` is the sharp bit. It is a commit-time handler; it
already enumerates every staged path; it already calls `path_is_protected` on
each one — and at `:249-250` it uses the answer only to `continue`. The comment
is correct about *why* (a lint diagnostic can quote the offending source line
verbatim). But the value that would justify a deny is computed, used to buy
silence, and discarded. The commit proceeds.

The compensating control is `sensitive_content`'s commit-time scan of added
lines. Its secret-word source is the file named by
`.claude/hooks-daemon.yaml:218`, and `bin/hooks-daemon secret-meta` reports
that file **`exists: false`** in this checkout. Per the handler's own
documented contract, a missing word list makes that source *silently inert*.
The `public_patterns` half (`.claude/hooks-daemon.yaml:190-217`) still fires —
this is a partial, not a total, outage — but the word-list half does not, and
nothing announces it: `bin/hooks-daemon status` says nothing about the word
list, and there is no `secret-redaction-status` subcommand (checked against the
CLI's own subcommand list).

Chain the three findings and the concrete outcome is: an SSH private key at the
repository root is (1) unreadable to the agent that would have spotted it
\[`secret_file_guard`\], (2) not ignored [Finding 1], (3) not scanned at commit
[this finding], and (4) committed by a routine `git add -A`. Each guard is
individually working as designed.

Note also the circularity worth writing down: even with the word list present,
`sensitive_content` cannot protect the word list itself in the general case —
its terms *are* the file, so it is the one protected file whose staging the
term-scan would catch, and every *other* protected file (a key, a vault
password, a `.pem`) matches no term and sails through.

**The class**

*A handler that computes a security-relevant predicate on the exact objects a
gate would need to judge, and uses the result only to suppress its own output.*
Membership test: is there a call site where `path_is_protected(x)` is true and
the handler's response is `continue`, inside a handler that runs on the
event where the damage occurs? That is a gate that was three lines from
existing.

**Why the test suite does not catch it**

This is an absent handler. No test can fail for a gate nobody wrote — the
`routine-never-run` argument applied to coverage, which is `CHECKS.md`'s own
framing for `F-GAP` (`CLAUDE/Routine/00001-security-review-full/CHECKS.md:58`).
**This finding overlaps `F-GAP`**; I am reporting it under `F-HYG` because it
is what makes Findings 1 and 2 reach a committed tree rather than stopping at
an advisory, and flagging the overlap so the caller can route it rather than
counting it twice.

**Detector hypothesis**

Not a Detector so much as the fix having a Detector shape: extend
`staged_lint_gate`'s existing enumeration to DENY when a staged path is
protected, reusing the value already computed at `:249`. The standing Detector
is then the regression test plus a `scripts/qa/` rule that greps for
`path_is_protected(...)` followed by a bare `continue` in any handler on a
mutating event.

*Likely false positives*: a project that deliberately tracks a file matching a
protected glob — the `.example` template case again, which is the same
exemption Finding 1 needs and should share it. Low noise. The grep-shaped half
(`path_is_protected` → `continue`) would fire on `lint_on_edit.py:229`, where
skipping is genuinely correct because `PostToolUse` is after the fact and there
is nothing to gate; that is one permanent, explainable exemption.

**Confidence**: moderate-high. The call-site table is exhaustive over the
matching module's public functions, which is how I establish the absence. An
absence claim is refutable by a gate I failed to grep for — I searched for the
matching functions, not for every possible spelling of a commit-time protected-
path check. The `exists: false` result and the inert-source consequence are
directly verified and high confidence.

---

## Clean results — looked, found nothing

These are *looked and found nothing*, not *did not look*.

- **Nothing stageable.** `git status --porcelain --untracked-files=all` returns
  **0** untracked-and-unignored paths. A `git add -A` right now stages nothing.
- **No stray copies or backup detritus.** A `find` over the whole tree
  (excluding `.git/` and the venv) for `.bak`, `.bak.*`, `.bak-*`, `.orig`,
  `.rej`, `~`, `.swp`, `.swo`, `.tmp` returns nothing.
- **No protected file exists on disk at all.** `bin/hooks-daemon secret-meta`
  reports `exists: false` for both the configured word list and its `.example`
  sibling. Every glob-shaped enumeration of tracked + untracked + ignored paths
  turned up only source modules, `__pycache__` artefacts and venv
  `site-packages` noise — no protected-glob match anywhere, including under
  `untracked/`, `untracked/scratch/`, `untracked/qa/` and `untracked/agent-reports/`.
- **`untracked/` is doubly ignored** — `.gitignore:200` (`untracked/`) plus
  `untracked/.gitignore` (`*` with `!.gitignore`). Correct defence in depth: the
  inner file survives a mistaken edit to the outer one.
- **Daemon-written artefacts all land inside `untracked/`** and are mode 0600
  with 0700 directories (`payload_capture.py:166` calls `make_private_dir`).
  `payload_capture` is `enabled: false` and scoped to `[Status]`
  (`.claude/hooks-daemon.yaml:27-31`). `untracked/logs/`, `untracked/events-*/`,
  `untracked/reports/`, `untracked/bug-reports/`, `untracked/issue-reports/`,
  `untracked/transcripts/` are all under that ignored root. Nothing the daemon
  writes automatically lands where a `git add -A` would stage it.
- **`.claude/` hygiene is sound.** Directory 0700, every file 0600. The runtime
  env file is ignored via `.claude/.gitignore:16` and is mode 0600.
  `.claude/ccy/.gitignore` is a correct deny-all-with-allowlist (`*` then
  explicit `!` entries). `.claude/ccy/ccy.env` *is* tracked and *not* ignored —
  I checked its variable names without printing values and it defines only
  `CCY_CLAUDE_WRAPPER` and `CCY_FLAG_COMPACT`. Not a credential; not a finding.
- **`.claude/worktrees-archive/` is not ignored, and does not exist.** It
  appears only as a string in `gitignore_safety_checker.py:148` and its tests,
  as the worked example of a substring that must *not* count as coverage. No
  code writes it. Not a finding.
- **Worktree seeding is symlink-mode** (`core/worktree_seed.py:48`,
  `DEFAULT_SEED_MODE`), and both worktree roots (`.claude/worktrees/` at
  `.gitignore:203`, `untracked/worktrees/`) are ignored. A `copy` mode exists
  and would materialise a real copy of each seeded file; here that copy would
  still land ignored. Noted as a residual for a project whose worktree root is
  elsewhere, not claimed as a finding for this checkout.
- **`untracked/rejected-writes/CLAUDE.md.rejected`** is 77549 bytes — byte-for-
  byte the size of the tracked, injected `CLAUDE.md` and of
  `.CLAUDE.md.pre-inject`. It is a captured denied write of this project's own
  instruction file, ignored, mode 0600. Not protected material. Flagging only
  that the *mechanism* (capturing a denied write's full content to disk) is one
  a future `sensitive_content` denial would route protected text through; it is
  written by `.claude/ccy/claude-supervise.py`, outside the daemon's redaction
  chain (`utils/secret_redaction.py:9-14` enumerates that chain and this is not
  in it). Low priority while the capture directory stays under `untracked/`.
- **No group- or world-writable file or directory** anywhere in the tree
  outside `.git/` and the venv.

## Limits — what I could not establish

- **I did not read the 31 lines of the historical `.example` file, and could
  not.** It matches a protected glob, so reading it by any route is the thing
  this brief forbids. Finding 2 therefore claims *a file matching a protected
  glob reached git history*, not *a secret reached git history*. Those are
  different claims and I am only making the first. A human with the word list
  settles it with one `git show b317c854` — that is the next action, and it
  belongs to a human, not to an agent.
- **Mode checks are weak in this container and I am not reporting them as
  clean.** The process runs as `root`, and root bypasses discretionary access
  control entirely, so `0600` restricts nothing here. What the bits *do*
  establish is that nothing is group- or world-readable or -writable, so the
  hygiene checker's permission rule would not fire — a true negative about the
  bits, not evidence that permissions are an effective control in this
  environment. On a multi-user host the same bits would be load-bearing.
- **Session transcripts are out of scope and already recorded.**
  `utils/secret_redaction.py:19-24` documents that Claude Code's own transcripts
  are redacted by nothing (Plan 00233), and explicitly warns that a clean scan
  of daemon-owned outputs is not evidence a term is absent from the machine.
  Not re-reported.

## Register

Per `.claude/agents/security-reviewer.md`, nothing is written to
`CLAUDE/Security/` by this report. Findings 1 and 2 look like one category —
*a guard's coverage set and its compensating control's coverage set drift
apart, with no assertion binding them* — but the caller writes the register
once a Defence exists, because a category naming no Defence is a claim the
register cannot make honestly.
