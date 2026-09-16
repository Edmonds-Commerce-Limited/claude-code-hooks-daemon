# Security review — `F-PRIV`

**Check**: What this repository's public surface — issues, releases, generated
bodies — has actually disclosed to date.

**Run**: Routine 00001, run 2026-001, FULL sweep. Reviewer: `security-reviewer`
(opus). Read-only throughout; nothing was created, edited, commented on or
published.

**Disclosure discipline**: no finding below quotes the material it describes.
Every citation is a location — a path, a line, a commit sha, an issue number —
and a CATEGORY. This document is safe to read without re-disclosing anything.

## Scope actually exercised

| Surface                                                 | Examined                                                     | Result                                     |
| ------------------------------------------------------- | ------------------------------------------------------------ | ------------------------------------------ |
| Git metadata (messages, identities, refs, tag messages) | `scripts/qa/check_git_history.py`, 3,818 commits / 150 refs  | Clean, including with the baseline removed |
| Working tree (contents + paths)                         | `scripts/qa/check_sensitive_content.py`, 3,598 tracked files | Clean                                      |
| Published issue bodies and comments                     | 36 issues, all states, via `gh`, bodies + comments           | One category found (F-PRIV-3)              |
| Published GitHub releases                               | 137 release bodies via `gh`                                  | Clean                                      |
| Historical blob CONTENT                                 | 18,025 blobs, all refs                                       | **Contaminated — F-PRIV-1, F-PRIV-2**      |
| Historical file PATHS absent from HEAD                  | 2,480 paths                                                  | Clean                                      |

The repository is confirmed `PUBLIC` (`gh repo view`), owner
`Edmonds-Commerce-Limited`, so every row above is world-readable and every clone
carries the history rows permanently.

**One methodological correction, recorded because it changes how the numbers
should be read.** A first pass run under the system interpreter reported 37
tree violations and zero secret terms. Both were artefacts: `scripts/qa/check_sensitive_content.py:176-183`
and `:145-146` return unfiltered/empty on `ImportError`, so an interpreter that
cannot import the daemon package silently disables exclusions and the secret
list. Every number in this report is from the resolved venv interpreter. The
silent-degradation shape itself is reported as F-PRIV-4.

## F-PRIV-1 — 16 real-shaped session UUIDs are permanently published in git history, and both gates report clean

**Confidence: high.** Directly measured; the introducing and cleaning commits
are both on published `main`.

### Citation

Representative introducing commits, each followed by its own clean-up:

| Introduced                           | Cleaned                       | Paths affected                                                                         |
| ------------------------------------ | ----------------------------- | -------------------------------------------------------------------------------------- |
| `02a05c97` (2026-08-26 06:30)        | `378ff748` (2026-08-26 07:14) | 27 of the 33 files added under `contracts/claude-code-hooks/`                          |
| `a22b6129` / `9b33a568` (2026-08-30) | `64b41a3e` (2026-08-30 14:51) | `CLAUDE/Plan/Completed/00292-codex-cli-dual-host-research/RESEARCH-codex-lifecycle.md` |

Pre-baseline residue in the same class, non-excluded paths:

- `CLAUDE/Plan/00101-recap-stoppage-investigation/PLAN.md` (7 revisions)
- `CLAUDE/Plan/00166-supervisor-multi-terminal-session-isolation/JOURNAL/00166-Journal-26-07-15.md` (5)
- `CLAUDE/Plan/Completed/00101-recap-stoppage-investigation/PLAN.md` (4)
- `CLAUDE/Plan/Completed/00042-auto-continue-stop-bug/CONTEXT.md` (2)
- `CLAUDE/Plan/00188-hook-event-semantic-response-audit/JOURNAL/00188-Journal-26-07-24.md` (2)
- `CLAUDE/Plan/Completed/001-test-fixture-validation/POSTTOOLUSE_FIXTURE_VERIFICATION.md` (2)
- `CLAUDE/Plan/00161-idle-housekeeping-mode/BRAINSTORM.md` (1)

**Measured total**: 16 distinct values matching the project's own `session-uuid`
public pattern, across 51 blob revisions in 34 non-excluded paths, all reachable
from published refs. 27 of those revisions were first published AFTER the
configured `history_baseline`.

### What it concretely allows

Anyone — no account needed — can retrieve a real Claude Code session identifier
by browsing the repository at any of those commits, or by cloning and running a
blob sweep. The clean-up commits do not remove them; they only change what HEAD
shows. The project's own rule (`.claude/hooks-daemon.yaml:203-205`) states that
a real session UUID must never be written to a file and that an all-same-digit
placeholder must be used instead. **The rule holds for the current tree and does
not hold for the published history.**

Meanwhile `scripts/qa/check_git_history.py` prints, today:

> No git-history violations found (2222 commits, 150 refs scanned)

That line is the defect's most damaging property. It is not merely silent about
the residue; it makes an affirmative clean claim over the exact history that
carries it.

### Why the window existed — and it is closed for the future, not for the past

Three dates, all verifiable from the repository:

| Date       | Commit     | What landed                                                       |
| ---------- | ---------- | ----------------------------------------------------------------- |
| 2026-08-07 | `2a39521b` | the `session-uuid` public pattern entered the config              |
| 2026-08-09 | `f6629233` | Plan 00202 — git **metadata** became a checked surface            |
| 2026-09-08 | `6c9a6f6f` | Plan 00362 — `sensitive_content` began judging **staged content** |

Both contaminations fall inside `2026-08-09 .. 2026-09-08`. In that window a
file written by Bash (a vendoring/capture script, not the `Write` tool) reached
disk unexamined by the write-time content guard, and the commit that recorded it
was judged on its message only. Every layer was present and none of them looked
at the bytes.

The staged-content scan now closes that route for NEW commits. Nothing closes it
for the 51 revisions already published, and nothing reports them.

### The class

**A leak surface whose write-time guard was added without a batch equivalent
over already-published history.**

Membership test, decidable without asking: *does this guard judge an artefact at
the moment it is created, and is the artefact retained after creation by
something the guard does not re-read?* If yes, everything created before the
guard — and everything that slipped past it once — is permanently unexamined,
and the guard's clean verdict will not say so.

This project already articulated exactly this class and applied it once:
`scripts/qa/check_git_history.py:21-24` says "every write-time rule needs a batch
equivalent, or everything predating the rule is permanently unexamined". That
reasoning produced a batch sweep for the five metadata surfaces. The two
remaining surfaces of the seven — blob **content** and historical **paths** —
were assigned to `check_sensitive_content.py`, which scans `git ls-files`, i.e.
HEAD only. The batch equivalent for content was never built, and the docstring's
own table reads as though it was.

### Why the test suite does not catch it

The tests pass and the defect is present because no test can assert over
history. `check_git_history.py`'s tests fix a synthetic repository and assert
that a planted term in a commit MESSAGE is found; they never plant one in a
blob, because the module does not claim to read blobs. `check_sensitive_content.py`'s
tests assert over a tree it constructs. Both suites are correct about their
units. The gap is between two modules that each correctly cover their own half
of a surface split that leaves content-in-history belonging to neither — a
property of the composition, which has no test because it has no owner.

The clean-up commits are the sharpest evidence: `378ff748` and `64b41a3e` both
carry messages describing the placeholder substitution, so a human noticed both
leaks within hours and fixed the tree. The suite was green before the leak,
during it, and after it.

### Detector hypothesis

A `scripts/qa/check_git_blobs.py` gate, wired into `run_all.sh` as a peer of the
existing two, that streams `git cat-file --batch-all-objects --batch`, skips
binaries, and applies the same compiled `public_patterns` and secret-term matcher
the other two already share — then subtracts (a) blobs currently in HEAD whose
path is in `exclude_paths`, and (b) blobs under a declared blob baseline, using
the same fail-safe as `grandfathered_commits` (an unresolvable baseline exempts
nothing). Report locator = short blob sha plus the paths it was ever stored
under; never the matched text, matching the existing disclosure rules.

**Likely false positives, and they are the reason to report this rule as noisy
rather than clean:**

1. **Self-referential rule text.** The file that DEFINES the patterns necessarily
   contains them. Measured here: of 149 `vhosts-path` blob hits, **every single
   one** resolved to `.claude/hooks-daemon.yaml`, `sensitive_content.py` or
   `test_sensitive_content.py` — all three already in `exclude_paths`. A
   path-aware subtraction reduces that pattern from 149 findings to **zero**. A
   detector without it would fire 149 times on its own rulebook and be switched
   off in a day.
2. **Exclusion drift over time.** `exclude_paths` describes HEAD. A historical
   blob's path may not be the path the exclusion was written for, so the
   subtraction must consider every path the blob was ever stored under, not just
   its current one.
3. **Unbounded findings on a first run.** Measured totals here are 143 profanity,
   149 vhosts-path and 54 session-uuid blob hits before subtraction. Landing this
   red is the failure mode `grandfathered_commits` (`check_git_history.py:246-256`)
   already documents: "a gate that is red on the day it lands and stays red until
   then does not get fixed — it gets disabled." The blob baseline is not optional
   polish; it is what makes the gate survivable.
4. **Runtime.** 18,025 blobs took well under a minute here, but this grows with
   history and `run_all.sh` is run often.

### What would settle the residual uncertainty

Nothing about the finding itself — it is measured. The open question is
**remediation**, which is a human's call and is outside this reviewer's remit:
removing the residue needs a second `git filter-repo` pass over 3,818 commits and
a force-push, against one word class and 16 identifiers whose sessions are long
dead. The project already made precisely this trade once and wrote the reasoning
down (`.claude/hooks-daemon.yaml:236-241`). The finding here is not that the
trade is wrong; it is that **the trade is currently being made silently**,
because no gate states what is being tolerated.

## F-PRIV-2 — profanity residue in the project's own authored voice, published in history

**Confidence: high.** Same measurement, same method.

### Citation

44 blob revisions across 9 non-excluded paths, history-only:

- `CLAUDE/Plan/00100-venv-ssot-consolidation/PLAN.md` (24 revisions) and its `PLAN-v1.md` (2)
- `CLAUDE/Plan/00103-v3.9.1-venv-resolution-failfast/PLAN.md` (4), `Completed/…/PLAN.md` (1), `Completed/…/PLAN-v1-ambitious-superseded.md` (2)
- `CLAUDE/AgentTeam.md` (4)
- `CLAUDE/QA.md` (3)
- `CLAUDE/Plan/00063-fail-fast-plugin-handler-audit/PLAN.md` (3) and `Completed/…/PLAN.md` (1)

### What it allows

A reader browsing published history sees the project's own engineering
documentation in a register the project decided it did not want to publish. The
config records that decision and the scan that motivated it
(`.claude/hooks-daemon.yaml:136-145`): a hand-audit found 6 instances, a
systematic scan found 27, "25 of them in the project's own authored voice in
live docs". The paraphrase pass cleaned the tree. The residue above is what the
paraphrase pass could not reach.

This is the same CLASS as F-PRIV-1 and needs no separate Detector — the blob
sweep finds both. It is reported separately because the remediation calculus
differs: the config's stated reason for tolerating the baseline
(`.claude/hooks-daemon.yaml:236-241`) is that it covers "exactly one known
finding … one word in one message body". **That claim is accurate for commit
messages and understates the tolerance by two orders of magnitude for blobs.** I
verified the message-level claim directly: re-running the sweep with the baseline
removed yields exactly one violation, a single `commit-message` profanity hit.
The comment is true about what it measured; it is read as true about the
baseline, which is a different and much larger thing.

## F-PRIV-3 — an absolute developer home path is published in issue comments, and no pattern covers that shape

**Confidence: high for the disclosure; high for the coverage gap.**

### Citation

- Issue **#1**, comment index 0 and comment index 1 — author `edmondscommerce`
- Issue **#27**, comment index 0 — author `edmondscommerce`
- Tracked and published: `CLAUDE/Plan/Completed/00099-python-fingerprint-venv-isolation/PLAN.md:100`

Category: an absolute `/home/<account>/…` path from a developer machine,
revealing a local account name and the on-disk project layout. The account
segment is **not** the GitHub login of the account that posted, so it is a
disclosure rather than a self-evident restatement of a public profile. Severity
is modest — the segment is a short personal name already inferable from the
public maintainer profile — but the disclosure is permanent and the class is not
covered.

### What it allows

Nothing exploitable on its own. It is reported because of what it proves about
coverage, which is the durable part:

`sensitive_content` DOES judge `gh issue comment` bodies
(`src/claude_code_hooks_daemon/handlers/pre_tool_use/sensitive_content.py:31`,
`:1231-1232`), and `issue_filing_gate.py:41-45` names that scan as the reason a
comment needs no provenance check: "The secret-term scan in `sensitive_content`
already covers `gh issue comment` bodies, which is the leak class that cannot be
retracted." But the configured `public_patterns` are exactly three
(`.claude/hooks-daemon.yaml:190-217`): `vhosts-path`, `session-uuid`, `profanity`.
**None matches an absolute home path**, and the secret-term half is inert (F-PRIV-4).
So the compensating control that `issue_filing_gate` relies on does not cover the
one category that has actually leaked through comments on this tracker.

The project already owns the correct redaction logic —
`src/claude_code_hooks_daemon/utils/report_scrubbing.py:92-95` replaces the home
prefix with `<home>` — but it applies only to generated reports, by exact-string
match against the *local* machine's home. Nothing applies it to a hand-typed
comment body.

Everything else on the published surface was clean. Release bodies (137) carried
only placeholder home paths, the maintainer's own contact domains and an
Anthropic co-author address — all intentional. Issue bodies carried no token,
key, internal hostname or private URL; the only non-GitHub hosts across all 36
issues and 137 releases were ordinary public documentation sites.

### Why the test suite does not catch it

There is no defect in any unit to catch. Every unit behaves as specified: the
handler scans comment bodies, the pattern list contains what it contains, the
scrubber scrubs what it is given. The finding lives in the sentence in
`issue_filing_gate.py:41-45` that asserts a coverage relationship between two
components, and no test asserts that relationship — a prose claim about another
module's adequacy is not executable.

### Detector hypothesis

Add a fourth public pattern for an absolute home-directory path
(`/home/<seg>/`, `/Users/<seg>/`, `/root/<seg>`), with an allowlist of
placeholder segments.

**This rule is noisy and must be reported as noisy.** Measured across the tracked
tree: 157 `/home/` hits over 13 distinct segments, of which `user` (49), `dev`
(48), `jbloggs` (24), `runner` (11), `someone` (8) and `testuser` (2) are
deliberate placeholders and CI paths — roughly 90% false positive before
allowlisting. It would also fire on `.claude/hooks-daemon.yaml.example`,
generated docs, and the `report_scrubbing` tests that must contain the shape they
strip. A segment allowlist plus the existing `exclude_paths` brings it to a
handful of real hits, but this pattern needs the allowlist designed before the
rule, not after — the profanity rule's own history
(`.claude/hooks-daemon.yaml:206-214`, 1,308 false positives on its first
formulation) is the precedent.

A cheaper and strictly-better-targeted variant, if the noise proves unmanageable:
apply the rule ONLY to outbound `gh` bodies and commit messages, not to tracked
files. That is where retraction is impossible, and it is where the measured
disclosures are.

### What would settle it

Whether the tracked-tree half of the rule is worth its noise is a judgement the
register owner should make with the false-positive count above in hand. The
`gh`-body half I would recommend without reservation.

## F-PRIV-4 — the secret-word-list half of every disclosure guard is inert, and every gate reports clean without saying so

**Confidence: high for the mechanism and the current state.** The state is
checkout-local by design, which is exactly what makes it dangerous.

### Citation

- `.claude/hooks-daemon.yaml:218` configures `secret_word_list_path`.
- `bin/hooks-daemon secret-meta` reports the configured path **`"exists": false`**
  in this checkout. (The file is read-protected and gitignored; it was never
  opened, and its path is not written out here.)
- Under the resolved venv interpreter, `resolve_secret_terms()` returns **0
  terms** while the path itself resolves successfully (not `None`).
- `scripts/qa/check_git_history.py:550-563` and
  `scripts/qa/check_sensitive_content.py` (main, final print) emit their clean
  lines with a scanned-file and scanned-commit count and **no term count**.
- Neither `scripts/qa/run_all.sh` nor `scripts/qa/llm_qa.py` asserts a non-zero
  term count.

### What it concretely allows

Every claim this repository makes about not disclosing specific identifiers —
the employer name, a client name, a real person's name — rests on the secret
list. `.claude/hooks-daemon.yaml:122-135` states this explicitly: a specific
identifier "is exactly what `secret_word_list_path` is for". In any checkout
where that file is absent — a fresh clone, CI, a worktree that did not get the
symlink — that entire category is unguarded at write time, at commit time, on
`gh` bodies, and in both batch sweeps. All four then report clean.

The `sensitive_content` half of the deny path still works for the three public
patterns, so the guard is not wholly dead; it is *half* dead, and the half that
died is the half that covers the identifiers the project most wants withheld.

### The class

**A guard whose data source is optional, whose absence is the documented
behaviour, and whose report cannot distinguish "nothing matched" from "nothing
was checked."**

That is the precise distinction `.claude/agents/security-reviewer.md:59-65`
requires of a human reviewer — "'I looked and found nothing' and 'I could not
look' are different results, and a report that renders them identically is worse
than no report." The obligation is stated for the reviewer and not enforced on
the tooling the reviewer reads.

The same shape appears twice more in these scripts and should be swept with the
same rule: `check_sensitive_content.py:176-183` returns files unfiltered on
`ImportError`, and `:145-146` returns `None` for the list path on the same
condition. That one is fail-loud (more findings), so it is benign — but
`resolve_secret_terms` on the identical `ImportError` returns `()`, which is
fail-silent-and-clean. **Two adjacent functions degrade in opposite directions
on the same condition**, and only one of them is safe. That is what produced the
misleading first pass recorded at the top of this report.

### Why the test suite does not catch it

The behaviour is tested and correct. `check_git_history.py:195-202` documents
`_never_matches` as the deliberate stand-in, and the empty-tuple return is the
specified contract. A test asserting "zero terms yields zero violations" would
PASS and would encode the defect. The defect is not in the function; it is in the
absence of any statement, at the point of REPORTING, that the run was partial.

### Detector hypothesis

Two parts, both cheap:

1. **Report the denominator.** Make both scripts' clean lines carry the term
   count and the pattern count alongside the file/commit counts, and have
   `llm_qa.py` surface them. A clean result that says "0 secret terms loaded" is
   no longer a clean result to a reader.
2. **A QA check that fails when a configured source resolves to nothing.** If
   `secret_word_list_path` is configured and loads zero terms, that is a
   configuration defect — the config asked for a check that is not running.

False positives for part 2: a project that deliberately configures the key while
keeping the list empty (a placeholder, or a client with nothing to hide yet) gets
a hard failure it cannot clear without removing the key. That is arguably the
correct pressure, but it is a real cost and should be a warning before it is a
block. Part 1 has no false positives at all — it only adds information — and is
the part worth doing unconditionally.

### What would settle it

Whether this checkout is representative. If the file is present on the
maintainer's machine and absent only here, the live exposure is narrower than the
text above implies — but CI and every fresh clone are still in the exposed state,
and part 1 of the Detector costs nothing and removes the ambiguity permanently.
That question is for the register owner, who knows the deployment; it does not
change the finding, because the finding is that **no reader of the output can
currently tell which case they are in.**

## Checks NOT answerable, and why

None. `F-PRIV` was fully exercised: `gh` was authenticated and permitted
read-only listing and reading of issues, comments and releases; git history was
complete and readable; both QA gates ran. There is no "could not look" row.

One deliberate limit, stated rather than left implicit: the protected secret word
list was never read (it is guarded by `secret_file_guard`, and reading it is
forbidden regardless). Its CONTENT therefore played no part in any scan above,
which is precisely the condition F-PRIV-4 describes. Everything reported here was
found by the public patterns and by structural heuristics applied on top of them.

## Summary

| ID       | Finding                                                                     | Class                                                | Confidence |
| -------- | --------------------------------------------------------------------------- | ---------------------------------------------------- | ---------- |
| F-PRIV-1 | 16 real session UUIDs, 51 blob revisions, published history                 | write-time guard with no batch equivalent            | high       |
| F-PRIV-2 | profanity residue, 44 blob revisions in the project's own docs              | same class as F-PRIV-1                               | high       |
| F-PRIV-3 | absolute developer home path published in 3 issue comments + 1 tracked file | a prose coverage claim no test asserts               | high       |
| F-PRIV-4 | secret word list loads 0 terms; every gate reports clean regardless         | guard whose absence is indistinguishable from a pass | high       |

F-PRIV-1 and F-PRIV-2 share one Detector (a blob sweep) and one register
category. F-PRIV-3 and F-PRIV-4 are independent and each needs its own.

Per `CLAUDE/Security/README.md`, none of these is recorded in the register by
this reviewer: a category with no Defence is a claim the register cannot make
honestly, and the Defences above are hypotheses, not code.
