# Cohort A: pre_tool_use safety handlers — evidence dossier

Scope: 18 handlers in `src/claude_code_hooks_daemon/handlers/pre_tool_use/`:
absolute_path, ancestry_preserving_merge, ask_user_question_blocker,
curl_pipe_shell, dangerous_permissions, destructive_git, error_hiding_blocker,
git_message_backtick, git_stash, lock_file_edit_blocker, pip_break_system,
pipe_blocker, root_recursion_guard, sed_blocker, security_antipattern,
sensitive_content, sudo_pip, worktree_file_copy.

All 18 are `enabled: true` in `/workspace/.claude/hooks-daemon.yaml` (lines
47-247) and are members of the installer's **base config** — i.e. shipped on
even under the `minimal` profile (`install/handler_profiles.py:35`: "Minimal
enables nothing extra (base config already has safety handlers on)"). None of
the 18 appears in `PROFILES["recommended"]` or `PROFILES["strict"]`
(`handler_profiles.py:39-78`) — they are baseline, not opt-in.

**Empirical firing data** (`/workspace/bin/hooks-daemon verdicts`, a *bounded
rolling window* of 44,166 recorded decisions — NOT lifetime totals, a handler
that fired before the window's start would not appear): of the 18, only
**three actually fired** in the retained window — `absolute_path` (3 denies),
`pipe_blocker` (4 denies), `sed_blocker` (3 denies). The other 15 are in the
report's "Never-fired handlers (59)" list. This is presented as context, not a
verdict: a rarely-firing safety guard on a rare-but-catastrophic operation
(force-push, chmod 777, lock-file edit) is doing its job if it never needs to
fire; it is only a red flag combined with a MECHANISM that cannot plausibly
match real input. Each entry below assesses that separately.

## Cohort summary

| Handler                   | Signal                                                   | Reason                                                                                                                                                                                                                                                                                                                                             |
| ------------------------- | -------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| absolute_path             | KEEP                                                     | Trivial, correct mechanism; empirically fired (3 denies); own docstring proves it's needed only for non-Claude-Code clients since the harness pre-resolves paths — that's documented, not hidden                                                                                                                                                   |
| ancestry_preserving_merge | KEEP                                                     | Real, narrow mechanism (3 exact ancestry-severing spellings), well-tested, escape hatch; never fired in window but plausible and cheap                                                                                                                                                                                                             |
| ask_user_question_blocker | KEEP                                                     | Real mechanism, well-designed prefix-gate; docstring says "disabled by default" but is actually in the shipped base config here — stale doc comment, not a functional defect                                                                                                                                                                       |
| curl_pipe_shell           | KEEP                                                     | Simple, correct regex covering 8 interpreters + sudo/path evasion; classic supply-chain vector, cheap to run                                                                                                                                                                                                                                       |
| dangerous_permissions     | KEEP                                                     | Correct octal/symbolic world-writable detection; narrow and cheap                                                                                                                                                                                                                                                                                  |
| destructive_git           | KEEP                                                     | Core safety handler, single source of truth for 9 patterns, progressive-verbosity UX, most-referenced handler in CLAUDE.md; zero denies in the sampled window is a rarity story, not a vacuity story                                                                                                                                               |
| error_hiding_blocker      | SUSPECT                                                  | Clean Strategy-pattern mechanism and real per-language patterns, BUT never fired in the window and duplicates ground also covered by `qa_suppression`/lint-on-edit review culture; worth checking language-strategy false-positive risk (e.g. legitimate empty `except` re-raises)                                                                 |
| git_message_backtick      | KEEP                                                     | Narrow, surgical fix for a documented REAL incident (commit cc7dddc0 lost text); shares GIT_INVOCATION with siblings, well-tested                                                                                                                                                                                                                  |
| git_stash                 | KEEP                                                     | Simple, well-scoped, escape hatch, complements (not duplicates) destructive_git's stash-drop/-clear coverage                                                                                                                                                                                                                                       |
| lock_file_edit_blocker    | KEEP                                                     | Simple pure-data table match (14 files x 8 ecosystems), essentially can't false-positive, cheap                                                                                                                                                                                                                                                    |
| pip_break_system          | KEEP                                                     | Simple regex, narrow scope, no overlap with sudo_pip (disjoint flag focus)                                                                                                                                                                                                                                                                         |
| pipe_blocker              | STRONG-SUSPECT (on complexity/cost grounds, not vacuity) | 1,265 lines, 38 commits, 14 fix/bug commits, 8 dedicated test files, and its OWN `get_claude_md()` was proven wrong about its own whitelist for an unknown period (LESSONS.md) — genuine, still-fired guard, but the concept has needed constant patching for shell-parsing edge cases; complexity is now a maintenance liability in its own right |
| root_recursion_guard      | KEEP                                                     | Born from a real incident (115 min at >1000% CPU), narrow well-tested mechanism, explicitly documents why `pipe_blocker` cannot cover it (no overlap)                                                                                                                                                                                              |
| sed_blocker               | KEEP                                                     | Empirically fired (3 denies), addresses a documented LLM failure mode (regex-syntax errors destroying files at scale), CLAUDE.md explicitly defends its commit-message false-positive as a feature not a bug                                                                                                                                       |
| security_antipattern      | SUSPECT                                                  | Real, cheap, well-tested construct-matching mechanism — BUT shipped documentation FALSELY claimed SQL-injection/weak-crypto/path-traversal coverage that never existed in any of 11 language strategies (caught at the v3.52.0 release gate, doc now fixed, Plan 00204 open and "Not Started" to decide whether to implement them at all)          |
| sensitive_content         | KEEP                                                     | Sophisticated, two-source design (public regex + gitignored word list), covers git metadata that no file-write hook could reach, heavily self-documented with dogfooding-derived edge-case fixes                                                                                                                                                   |
| sudo_pip                  | KEEP                                                     | Simple regex, narrow, complements pip_break_system                                                                                                                                                                                                                                                                                                 |
| worktree_file_copy        | KEEP                                                     | Real mechanism (cp/mv/rsync + worktree-path + src/tests/config heuristic), same-worktree exemption tested; never fired in window but plausible given worktree docs elsewhere in CLAUDE.md actively promote worktree usage                                                                                                                          |

**Cross-cutting observations for the judge:**

1. **No transcript_archiver-shaped handler exists in this cohort.** Every
   handler here produces a DECISION (allow/deny/advise), not an artefact
   nobody reads — so the specific failure mode that killed
   `transcript_archiver` (accumulating unread output) does not apply. The
   closer risk in this cohort is CONCEPT COMPLEXITY (pipe_blocker) and
   CLAIM-VS-MECHANISM DRIFT (security_antipattern's now-fixed doc overclaim,
   pipe_blocker's now-fixed whitelist doc overclaim) — a documentation claim
   outliving the code that was supposed to back it, twice, independently, in
   this cohort alone.
2. **The "never fired" list is dominated by rare-but-catastrophic ops**
   (force-push, lock-file edits, chmod 777, sudo pip, git stash) where zero
   firings across 44K decisions is the EXPECTED shape of a working guard on
   an operation nobody attempts often — not evidence the guard is vacuous.
   Each was individually checked for a plausible, non-synthetic matching
   input via its own `get_acceptance_tests()`, which every handler in this
   cohort implements with realistic commands (not reverse-engineered fixture
   soup).
3. **Every handler in the cohort has both a unit test file and a
   `get_acceptance_tests()` method** exercised by the real playbook —
   unlike `transcript_archiver`, none of these is running untested.
4. **Two doc/mechanism mismatches found and already partly fixed by prior
   plans** (security_antipattern's SQL-injection/crypto/path-traversal
   overclaim, pipe_blocker's git-log/git-branch whitelist overclaim) suggest
   this project's actual failure mode is not "vacuous guard" but "guidance
   text drifts ahead of or behind the regex it describes." Worth a
   structural fix (e.g. a test that derives `get_claude_md()` claims from the
   pattern tables) rather than one-off doc edits — LESSONS.md already
   proposes exactly this for pipe_blocker.

---

## absolute_path

**CLAIM**: "Require absolute paths for Read/Write/Edit tool file_path parameters" (`absolute_path.py:16`).

**MECHANISM**: `matches()` (`absolute_path.py:29-44`) restricts to Read/Write/Edit and denies when `file_path` does not start with `/`. Trivial, correct, cannot misfire on unrelated input.

**CONSUMER**: N/A — produces a decision only.

**VACUITY**: The handler's OWN docstring on `get_acceptance_tests()` (`absolute_path.py:80-97`) states both acceptance tests are `harness_cannot_produce`: Claude Code resolves `file_path` to absolute BEFORE PreToolUse dispatch, so a *harness-originated* call can never trigger the deny path — verified live during the v3.51.0 acceptance gate (a relative-path Write reached later handlers already resolved to `/workspace/...`). BUT the verdict log shows `require-absolute-paths: 3 (deny=3)` — it DID fire 3 times in the retained window, which the handler's own docs attribute to non-Claude-Code clients hitting the daemon socket directly (covered by `tests/acceptance/test_absolute_path_socket_deny.py`).

**DUPLICATION**: None — Claude Code's own harness does the equivalent normalisation, but the handler's stated purpose (protecting non-Claude-Code socket clients) is a real, distinct audience the harness does not cover.

**CONFIG**: Base config, `enabled: true`, priority 12, `HandlerTag.TERMINAL`.

**COST**: One string-prefix check per Read/Write/Edit call. Negligible.

**HISTORY**: 11 commits, `git log --follow`, dates to `74b0989c Initial commit`.

**FALSE-POSITIVE RECORD**: None found.

**SIGNAL: KEEP** — rare but real fire count in production data, self-documents its own limited applicability rather than hiding it.

---

## ancestry_preserving_merge

**CLAIM**: "Block (or, in warn mode, advise against) ancestry-severing merges" (`ancestry_preserving_merge.py:82`) — `git merge --squash`, `gh pr merge --squash`, `gh pr merge --rebase`.

**MECHANISM**: Three precise regexes (`ancestry_preserving_merge.py:51-67`) scoped to a shell segment (`_SEGMENT`) so a match can't leak across `;`/`&&`. `git merge --no-ff` and `gh pr merge --merge` are explicitly tested as NOT matching (`ancestry_preserving_merge.py:284-308`). Cannot false-positive on ordinary merges by construction.

**CONSUMER**: Decision only.

**VACUITY**: Plausible — squash/rebase merges are common developer actions, and the handler's rationale (branch deletion becomes permanently blocked post-squash) is documented as the exact motivating problem for the `delete-branch` CLI tool referenced elsewhere in CLAUDE.md. Not fired in the sampled window, but not synthetic-fixture-only either — the acceptance tests are literal real CLI invocations.

**DUPLICATION**: None internal. Explicitly documents what it CANNOT see (GitHub web UI squash/rebase button) rather than overclaiming coverage.

**CONFIG**: Base config, `enabled: true`, priority 19, `mode: block` (escape hatch: `MUST_SQUASH_BECAUSE=`).

**COST**: 3 compiled regexes per Bash call. Negligible.

**HISTORY**: 2 commits, `54d2ed8f Plan 00207: Phase 1-2 - ancestry_preserving_merge handler (TDD + integration)` — recent, purpose-built, justified against a stated need (git_branch -d refusing branches post-squash).

**FALSE-POSITIVE RECORD**: None found; only 2 commits total suggests it hasn't needed patching.

**SIGNAL: KEEP** — clean, narrow, justified.

---

## ask_user_question_blocker

**CLAIM**: "Allow AskUserQuestion only when every question is prefix-justified" (`ask_user_question_blocker.py:79`), mirroring the Stop handler's `STOPPING BECAUSE:` convention.

**MECHANISM**: `_all_questions_justified()` (`ask_user_question_blocker.py:125-151`) fails closed on any malformed/missing prefix, requiring literal `ASKING BECAUSE:` (case-sensitive) at the start of every question string. Straightforward string-prefix check, cannot misfire on unrelated tool calls (`matches()` gates on `tool_name == ASK_USER_QUESTION`).

**CONSUMER**: Decision only (strict mode denies; advisory mode allows with context).

**VACUITY**: Module docstring (`ask_user_question_blocker.py:16`) says "Disabled by default. Enable in hooks-daemon.yaml" — but `hooks-daemon.yaml:244-246` has it `enabled: true`, and it is NOT gated behind any installer profile (`handler_profiles.py` never references it — it ships in base config regardless of profile). **This is a stale docstring, not a functional bug**: the actual shipped default in this repo has it on. Real AskUserQuestion calls happen routinely in agentic sessions, so the mechanism is plausible; never fired in the sampled window, consistent with the daemon's own CLAUDE.md guidance training the agent NOT to ask tautological questions in the first place (the intended effect, not vacuity).

**DUPLICATION**: None — no other handler or Claude Code built-in gates AskUserQuestion content.

**CONFIG**: Base config, `enabled: true`, priority 23, `HandlerTag.TERMINAL`.

**COST**: One string check per AskUserQuestion call (rare tool).

**HISTORY**: 3 commits, `926462ae Fix: auto_approve_reads uses wrong field + add AskUserQuestion blocker`.

**FALSE-POSITIVE RECORD**: None found in Plan/LESSONS search.

**SIGNAL: KEEP** — one doc inaccuracy (docstring says disabled-by-default, shipped config says enabled) worth a one-line fix, not a design problem.

---

## curl_pipe_shell

**CLAIM**: Blocks piping curl/wget output directly to a shell/interpreter (`curl_pipe_shell.py:42-60`).

**MECHANISM**: Regex covers 8 interpreters (`bash, sh, zsh, ksh, dash, python, perl, ruby`), tolerates `sudo` with arbitrary flags and path-qualified interpreters (`/bin/bash`) via shared `OPTIONAL_SUDO`/`OPTIONAL_PATH` fragments (`curl_pipe_shell.py:17-39`). Comment at line 28-29 documents that path-qualified bypass (`curl | /bin/bash`) was a real gap that got closed.

**CONSUMER**: Decision only.

**VACUITY**: `curl | bash` install scripts are one of the most common real-world patterns an agent might reach for; plausible even though it never fired in the sampled window.

**DUPLICATION**: None — closest relative is `pipe_blocker`, which is about truncation/information-loss to tail/head, not RCE via shell execution. Different threat model entirely.

**CONFIG**: Base config, `enabled: true`, priority 16, `terminal=True`.

**COST**: One regex per Bash call. Negligible.

**HISTORY**: 12 commits, `9b9868fe Plan 00022: Add CurlPipeShellHandler to block curl/wget piped to shell` — the evasion-hardening commits (sudo flags, path-qualified interpreters) are incremental improvements to a sound original concept, not signs the concept is wrong.

**FALSE-POSITIVE RECORD**: None found.

**SIGNAL: KEEP**

---

## dangerous_permissions

**CLAIM**: Blocks `chmod 777` and other world-writable permission commands (`dangerous_permissions.py:34-51`).

**MECHANISM**: Two precise patterns — octal (last digit has the write bit set: 2/3/6/7, optionally preceded by a special-bits digit) and symbolic (`[ao]+[rwx]*w[rwx]*`, requiring `+` so `go-w` removals are excluded) (`dangerous_permissions.py:17-31`). Explicitly does NOT match safe modes (755, 644, 600) or removals — verified by comment and by the negative-case docstring at lines 70-71.

**CONSUMER**: Decision only.

**VACUITY**: Plausible mechanism; the module even documents CLAUDE.md's own `chmod 777` example verbatim in acceptance tests. Never fired in the sampled window.

**DUPLICATION**: None.

**CONFIG**: Base config, `enabled: true`, priority 18, `terminal=True`.

**COST**: One regex per Bash call.

**HISTORY**: 11 commits, `28af5797 Plan 00022: Add DangerousPermissionsHandler to block chmod 777`.

**FALSE-POSITIVE RECORD**: None found.

**SIGNAL: KEEP**

---

## destructive_git

**CLAIM**: "Block destructive git commands that permanently destroy data" — 9 named patterns (`destructive_git.py:213-227` table): reset --hard, clean -f, checkout -- file, restore, stash drop/clear, push --force, branch -D, commit --amend.

**MECHANISM**: Single source-of-truth ordered `(pattern, reason)` tuples (`destructive_git.py:54-105`) consumed identically by `matches()` and `handle()` so they can never drift. Uses shared `GIT_INVOCATION` fragment to tolerate `git -C <path>` and other global options — the file's own header comment (lines 18-35) documents a REAL historical bypass where a bare `\bgit\s+reset` anchor was defeated by `git -C /path reset --hard`, and a second near-miss where `--git-dir=/repo/.git reset --hard` looked covered "only by accident" because the path happened to end in `.git`. The push-force pattern is explicitly scoped to the push segment only, with a regression test proving `git tag -f` (unrelated `-f`) is NOT blocked (lines 389-404) — a documented dogfooding false positive from Plan 00200 that was fixed.

**CONSUMER**: Decision only; also drives progressive verbosity via `get_data_layer().history.count_blocks_by_handler()` (terse → standard → verbose across repeat blocks).

**VACUITY**: Mechanism plausibility is not in question — every pattern targets a real, named, commonly-typed git subcommand. **Empirically it did NOT fire in the sampled 44K-decision window** despite being arguably the single most load-bearing safety handler in the project (referenced by name throughout CLAUDE.md, RELEASING.md's "destructive git commands" table, and the git_message_backtick/root_recursion_guard docstrings as "the thing that already covers execution risk"). This is presented as a rarity story, not a vacuity story: CLAUDE.md actively trains the agent away from these commands, which is presumably suppressing attempts, and the daemon's own escape-hatch/override counter in the verdicts report shows 0 overrides — consistent with "rarely attempted, correctly blocked the few times it was."

**DUPLICATION**: `git_message_backtick` explicitly scopes itself to NOT duplicate this handler (its own docstring, lines 28-32, says the "dangerous command inside backticks" case is "already covered" by `destructive_git`'s full-string matching). `git_stash` explicitly defers stash-drop/-clear to this handler (its own comment: "Note: drop/clear are blocked by DestructiveGitHandler").

**CONFIG**: Base config, `enabled: true`, priority 10 (lowest/first safety handler), `HandlerTag.TERMINAL`.

**COST**: 9 compiled regexes per `git`-containing Bash call (short-circuits on `"git" not in command.lower()` first).

**HISTORY**: 21 commits (second-most-patched in cohort after pipe_blocker), dates to `74b0989c Initial commit`. Patches are evasion-hardening (global options, `-f` scoping) rather than concept reversals.

**FALSE-POSITIVE RECORD**: Plan 00200's `git tag -f` false positive (fixed, regression-tested). CLAUDE.md itself documents and DEFENDS a class of false positive (commit messages describing a blocked command get blocked) as intentional, load-bearing behaviour for acceptance testing — not a bug to fix.

**SIGNAL: KEEP** — the single strongest piece of evidence is the handler's own documented history of closing REAL bypasses (the `git -C` global-options hole), which is the opposite of a handler nobody has scrutinised.

---

## error_hiding_blocker

**CLAIM**: "Block error-hiding patterns in code written via Write or Edit tools" across Python/Shell/JS/Go (`error_hiding_blocker.py:53-66`) — e.g. `except: pass`, `|| true`, empty `catch`, `_ = err`.

**MECHANISM**: Strategy Pattern, zero language logic in the handler itself (`error_hiding_blocker.py:52-66`). `matches()` gates on Write/Edit + registered extension + non-excluded path, then delegates to per-language regex lists. Python strategy example: `except\s*:\s*\n\s*pass\b` and `except\s+\w[\w\s,]*:\s*\n\s*pass\b` (bare-except-pass, exception-pass) — both require the block body to be LITERALLY just `pass`, so a `except Exception as e: pass  # noqa comment then re-raise` on a later line would not match (the regex only looks at the immediate next line). This is a reasonably tight construct match, not prose-matching.

**CONSUMER**: Decision only.

**VACUITY**: Plausible in principle (LLMs do write `except: pass` and `|| true` under time pressure) but it is the ONLY handler in this cohort that (a) never fired in the sampled window AND (b) has zero individual git-history evidence of being hardened against a real bypass (5 commits total, all additive — language strategies being added, not fixes to false positives or false negatives). Its file-count footprint (4 languages x ~2-6 patterns each) is modest.

**DUPLICATION**: Partial, conceptual only — `qa_suppression` (a sibling handler, priority 30, not in this cohort) blocks `noqa`/`type: ignore` suppression annotations, a related-but-distinct failure mode (suppressing a LINTER's complaint vs. suppressing a runtime EXCEPTION). Not the same regex space, but both exist because "the LLM tries to make a red light go green without fixing the underlying problem" — a project-level theme covered by two separate handlers rather than one generalized one. Not clearly wrong, but worth the judge's attention as a possible consolidation candidate given error_hiding_blocker's low observed value so far.

**CONFIG**: Base config, `enabled: true`, priority 13, `HandlerTag.TERMINAL`. Default excludes vendor/node_modules/test-fixture dirs.

**COST**: Per Write/Edit call: registry lookup by extension (O(1)), then up to ~6 regex searches over the new content only (not full file). Cheap.

**HISTORY**: 5 commits, `a8c878fb Add: ErrorHidingBlockerHandler - language-aware error-hiding detection` — straightforwardly additive, no evidence of false-positive firefighting (could mean it's well-designed, or could mean it's rarely exercised enough to have generated complaints).

**FALSE-POSITIVE RECORD**: None found in Plan/LESSONS search.

**SIGNAL: SUSPECT** — not vacuous (real construct matches, real language coverage), but the combination of (a) zero fires in 44K decisions, (b) zero hardening history, and (c) conceptual adjacency to `qa_suppression` makes it the cohort's best candidate for "is this pulling its weight, or is it dormant machinery" — worth the judge cross-checking against a longer verdict window or broader git blame before a keep/cut call.

---

## git_message_backtick

**CLAIM**: Blocks an unescaped backtick inside a double-quoted `-m`/`--message` value on `git commit`/`git tag`, because bash executes it as command substitution (`git_message_backtick.py:76-81`).

**MECHANISM**: Three components: (1) a git-invocation + message-bearing-subcommand matcher built on shared `GIT_INVOCATION`, (2) a double-quoted-message extractor tolerating backslash escapes, (3) an unescaped-backtick detector. All three composed correctly per the docstring's worked example.

**CONSUMER**: Decision only.

**VACUITY**: Not synthetic — the handler's own docstring (`git_message_backtick.py:20-26`) names a REAL prior incident in THIS repository: commit `cc7dddc0` lost the phrase "pipe_blocker now allows `git branch ... | head`, so ..." because bash executed the backticked span and replaced it with (empty) stdout. This is independently corroborated in `CLAUDE/development/LESSONS.md:201-230` ("Backticks in a double-quoted `-m` message are executed, not quoted"). This is about as far from a synthetic fixture as a test case gets — it's a documented production incident.

**DUPLICATION**: None — explicitly scoped to the CORRUPTION case only, deferring the EXECUTION-of-dangerous-command case to `destructive_git`/`sed_blocker`'s full-string matching (own docstring, lines 28-32). Cleanly complementary, not overlapping.

**CONFIG**: Base config, `enabled: true`, priority 20, `HandlerTag.TERMINAL`.

**COST**: 2-3 regex operations per git commit/tag call. Cheap, and commits are inherently low-frequency events.

**HISTORY**: 2 commits, `f167d9fa Plan 00219 + 00221: close two laundering routes past blocking handlers` — purpose-built directly from the incident.

**FALSE-POSITIVE RECORD**: None found (single-quoted messages, escaped backticks, and `-F` file messages are all explicitly exempted and tested).

**SIGNAL: KEEP** — strongest possible justification: a real, named, dated incident in this repo's own git log.

---

## git_stash

**CLAIM**: Blocks `git stash`/`push`/`save` (creation) while always allowing `pop`/`apply`/`list`/`show` (recovery) (`git_stash.py:28-37`).

**MECHANISM**: Two-part regex gate — an allowlist for recovery subcommands checked FIRST, then a stash-creation matcher, both built on shared `GIT_INVOCATION` to tolerate global options. Own comment (lines 11-18) documents that the allowlist had to be widened in lockstep with the block pattern, because narrowing only one side would "turn a bypass into a false positive on the one form that RECOVERS work" — a subtle correctness point that's actually handled correctly.

**CONSUMER**: Decision only.

**VACUITY**: Plausible — `git stash` is an extremely common developer reflex; the handler's own comment (lines 53-58) notes it's matched even inside `echo "git stash"` quoted strings DELIBERATELY, because that's how the project's OWN acceptance tests verify blocking handlers (Plan 00228 considered exempting quoted spans and rejected it).

**DUPLICATION**: None — explicitly complements `destructive_git`, which owns `stash drop`/`stash clear` (own comment: "Note: drop/clear are blocked by DestructiveGitHandler").

**CONFIG**: Base config, `enabled: true`, priority 19, `mode: deny` (escape hatch: `MUST_STASH_BECAUSE=`).

**COST**: 2-3 regexes per Bash call containing "stash". Cheap.

**HISTORY**: 14 commits, dates to `74b0989c Initial commit`.

**FALSE-POSITIVE RECORD**: None found; the "quoted string still matches" behaviour looks like a false positive at first glance but is explicitly defended by Plan 00228 as required for testability (same class of defended false positive as destructive_git's commit-message matching).

**SIGNAL: KEEP**

---

## lock_file_edit_blocker

**CLAIM**: Blocks direct Write/Edit of 14 package-manager lock files across 8 ecosystems (`lock_file_edit_blocker.py:22-35`).

**MECHANISM**: Pure data-table lookup — `matches()` checks tool is Write/Edit and `file_path` case-insensitively ends with an entry in `LOCK_FILES` (`lock_file_edit_blocker.py:89-121`). No regex, cannot misfire on unrelated content — the only way to trigger it is to target a file literally named e.g. `package-lock.json`.

**CONSUMER**: Decision only.

**VACUITY**: Plausible — an LLM might reasonably try to hand-patch a lock file to resolve a conflict or add an entry; the mechanism cannot false-positive (exact filename suffix match) and cannot vacuously never-match either (any Write/Edit to a file with that literal name triggers it 100% of the time). Never fired in the sampled window, consistent with lock files being edited relatively rarely.

**DUPLICATION**: None.

**CONFIG**: Base config, `enabled: true`, priority 20, `terminal=True`.

**COST**: One list membership check (`any(...endswith...)` over 14 short strings) per Write/Edit. Trivial.

**HISTORY**: 7 commits, `ff6957f6 Plan 00031: Implement lock file edit blocker handler`.

**FALSE-POSITIVE RECORD**: None found.

**SIGNAL: KEEP**

---

## pip_break_system

**CLAIM**: Blocks `pip install --break-system-packages` and its `pip3`/`python -m pip`/`python3 -m pip` variants (`pip_break_system.py:19-31`).

**MECHANISM**: Single regex `\b(pip3?|python3?\s+-m\s+pip)\s+install\s+.*--break-system-packages` (`pip_break_system.py:67`), case-insensitive. Simple and correct for its narrow scope.

**CONSUMER**: Decision only.

**VACUITY**: Plausible — this flag is a documented quick-fix an LLM might reach for after seeing a PEP 668 error; CLAUDE.md's own security-standards prose references this exact scenario.

**DUPLICATION**: None with `sudo_pip` — disjoint trigger (this one is about the FLAG regardless of sudo; sudo_pip is about the PREFIX regardless of the flag). A command using both (`sudo pip install --break-system-packages x`) would trigger both handlers independently, which is redundant-but-harmless (whichever handler's priority runs first denies it; the other never gets a chance to also deny, since PreToolUse dispatch presumably stops at the first DENY on a terminal handler) rather than duplicative in the sense of one being dead weight.

**CONFIG**: Base config, `enabled: true`, priority 21, `terminal=True`.

**COST**: One regex per Bash call. Negligible.

**HISTORY**: 10 commits, `a4c8e1a4 Plan 00022: Add PipBreakSystemHandler to block --break-system-packages`.

**FALSE-POSITIVE RECORD**: None found.

**SIGNAL: KEEP**

---

## pipe_blocker

**CLAIM**: "Three-tier decision for commands piped to tail/head" — whitelist → allow, blacklist → deny (expensive), unknown → deny (`pipe_blocker.py:1-11`).

**MECHANISM**: By far the most complex handler in the cohort (1,265 lines vs. next-largest sensitive_content at 554). Per-pipe classification (not just the first pipe in a command — the docstring at lines 433-451 documents THREE historical bypasses this fixed: (1) only-first-pipe-classified letting a cheap `git log | head -1 &&` launder an expensive second pipe, (2) `tail -f`/`head -c` exemptions searched across the WHOLE string rather than per-consumer, (3) producer read from outer text misattributing a pipe inside `$( )`). Also has a dedicated "prose guard" (lines 53-150) built specifically because the verbose remediation template, when fed a false-positive match, extracted "the" (first word of a sentence) as a fake binary name and offered a nonsensical `extra_whitelist: - "^the\\b"` suggestion — a correctness bug in the DENY MESSAGE, not the matching, but still a real defect that shipped and was fixed (Plan 00209/00228).

**CONSUMER**: Decision only.

**VACUITY**: Not vacuous — 4 real fires in the sampled window (the only cohort handler besides sed_blocker and absolute_path to fire at all), and the concept (guard against silent truncation via `| tail`/`| head`) is a genuinely common LLM habit this project actively works around via the `echd-capture` helper referenced throughout CLAUDE.md.

**DUPLICATION**: Explicitly NOT duplicated by `root_recursion_guard` (that handler's own docstring explains the boundary: pipe_blocker guards truncation/information-loss, root_recursion_guard guards resource blow-up, and documents that `| head` does NOT even bound a `-rl` scan — different failure mode entirely).

**CONFIG**: Base config, `enabled: true`, priority 17.

**COST**: Highest in the cohort. Per Bash call: strips message-bodies and heredoc bodies from a copy of the command (2 string-processing passes), then iterates EVERY pipe operator in the command doing quote-aware segment extraction, chain-separator splitting, and command-substitution-boundary detection for each one, plus (on a match) a function-word-ratio prose-vs-command classifier before building the deny message. This is materially more CPU per invocation than any other handler in the cohort, though still sub-millisecond in absolute terms for typical command lengths.

**HISTORY**: 38 commits — the most-patched handler in the ENTIRE pre_tool_use directory by a wide margin. 14 of those 38 (37%) are fix/bug/false-positive commits by commit-message keyword search. 8 dedicated test files exist just for this one handler (`test_pipe_blocker.py`, `_bug.py`, `_chain_segmentation.py`, `_command_substitution.py`, `_comprehensive.py`, `_guidance_truth.py`, `_message_substitution.py`, `_prose_remediation.py`) — an order of magnitude more test-file fragmentation than any sibling handler.

**FALSE-POSITIVE RECORD**: Substantial and DOCUMENTED, not merely inferred from commit counts. `CLAUDE/development/LESSONS.md:159-199` ("A test that restates the implementation is not a requirement") describes a case where `pipe_blocker`'s `get_claude_md()` told every session `git log`/`git branch` were whitelisted while the actual `UNIVERSAL_WHITELIST_PATTERNS` never contained them — agents were denied for doing exactly what the resident guidance told them was safe, and a test whose ENTIRE docstring was "git log is NOT whitelisted (only git tag, status, diff are)" (a restatement of the bug, not a requirement) guarded the divergence and survived a full redesign. `CLAUDE/Plan/Completed/00222-pipe-blocker-message-redaction-overbreadth/` and `00228-prose-guard-for-text-matching-handlers/` are two more recent, fully-resolved false-positive plans specifically about this handler (message-substitution overbreadth, and the "the" prose bug above).

**SIGNAL: STRONG-SUSPECT** (on complexity/maintenance-cost grounds, explicitly NOT on vacuity — it is real, it fires, and every individual fix closed a genuine bug). The single strongest piece of evidence: 14/38 commits (37%) are fix/bug commits and it required a purpose-built "is this actually English prose vs a shell command" classifier subsystem just to keep its OWN error messages from being embarrassingly wrong. A handler whose deny-message-generation code needs its own NLP-lite heuristic is worth the judge's scrutiny on whether the underlying three-tier concept (vs., e.g., a simpler "always redirect to echd-capture" default) is proportionate to the problem, independent of whether any individual fix was correct.

---

## root_recursion_guard

**CLAIM**: Blocks recursive scanners (`grep -r`, `find`, `fd`, `rg`, ...) rooted at catastrophic paths (`/`, `/proc`, `/sys`, `/home`, `/root`, `~`, `$HOME`) (`root_recursion_guard.py:1-22`).

**MECHANISM**: Tokenizes each shell segment with `shlex` (falling back to whitespace split on unbalanced quotes — fail-safe toward catching the dangerous case), skips leading env-var assignments, checks the command basename against always-recursive vs. grep-family-with-flag scanner sets, and checks arguments against dangerous-root sets with correct exact-vs-prefix matching (`/` and `/home` match ONLY exactly, so a project living under `/home/...` is not blocked; `/proc`/`/sys` match the dir or descendants).

**CONSUMER**: Decision only.

**VACUITY**: Not synthetic — the docstring (`root_recursion_guard.py:1-22`) names a REAL incident: "an orphaned `ugrep -rl "class X" /` ran unreaped for ~115 minutes at >1000% CPU," with a reference to `untracked/hooks-daemon-runaway-background-shell-harvester.md`. Never fired in the sampled window (consistent with the incident being rare-but-catastrophic, exactly the profile this guard exists for), but the mechanism is demonstrably plausible.

**DUPLICATION**: Explicitly checked against `pipe_blocker` in its own docstring (lines 14-18) and found NOT to overlap: pipe_blocker guards truncation, this guards resource exhaustion, and `| head` does not even bound the scenario this handler blocks (head closes the pipe, but a `-l`/`-rl` producer that matches nothing never gets SIGPIPE and runs to completion regardless).

**CONFIG**: Base config, `enabled: true`, priority 15, `HandlerTag.TERMINAL`.

**COST**: shlex tokenization + a handful of set-membership checks per shell segment. Cheap, bounded by command length.

**HISTORY**: 3 commits, `2d0925c3 Plan 00142: Phase 1 - root_recursion_guard PreToolUse handler` — purpose-built directly from the incident, minimal subsequent churn.

**FALSE-POSITIVE RECORD**: None found.

**SIGNAL: KEEP** — same class of evidence as git_message_backtick: a dated, named, documented production incident, not a hypothetical.

---

## sed_blocker

**CLAIM**: "sed is forbidden for file modification — Claude gets sed syntax wrong and a single error can silently destroy hundreds of files" (`sed_blocker.py:71-93`).

**MECHANISM**: Multi-tier: sed-as-command-head detection, sed-with-execution-flag detection (`-i`/`-e`/`-n`), sed-via-xargs detection, plus git-commit/gh-command context exemptions (sed mentioned in a commit message or PR body is safe) and a read-only-pipeline allowance (`cat f | sed 's/x/y/' | grep z`). The `_is_git_command`/`_is_gh_command` helpers correctly check for an intervening command SEPARATOR between the git/gh invocation and the word "sed" so a genuinely separate destructive `sed` chained after `git commit` is still caught (lines 145-224).

**CONSUMER**: Decision only.

**VACUITY**: Empirically fired 3 times in the sampled window. Concept is well-justified: `find -exec sed` syntax errors destroying files at scale is a documented class of LLM failure this project explicitly designed around (CLAUDE.md's dedicated section defends the handler's commit-message false positives as intentional and load-bearing for acceptance testing).

**DUPLICATION**: None internal.

**CONFIG**: Base config, `enabled: true`, priority 11, `blocking_mode: strict` (default) — also gates Write-tool creation of `.sh`/`.bash` scripts containing sed, not just Bash direct invocation.

**COST**: Several regex checks per Bash call containing "sed" (short-circuited by a single `\bsed\b` search first), plus for Write calls a content scan gated on `.sh`/`.bash` extension. Cheap.

**HISTORY**: 16 commits, dates to `74b0989c Initial commit`.

**FALSE-POSITIVE RECORD**: The commit-message matching is a KNOWN, ACKNOWLEDGED, and DEFENDED false-positive class — CLAUDE.md has a dedicated subsection ("Blocking Handler False Positives in Commit Messages") stating this "is intentional and must NOT be 'fixed'" because it's what enables safe acceptance testing. Not a hidden defect; a documented design tradeoff.

**SIGNAL: KEEP**

---

## security_antipattern

**CLAIM (as currently shipped, `security_antipattern.py:134-161`)**: Blocks code-injection, command-injection, unsafe deserialization, XSS, and hardcoded-credential constructs across 11 languages. Explicitly and correctly states it is "pattern matching on known-dangerous constructs, not analysis" and does NOT detect SQL injection, weak hashing, or path traversal.

**MECHANISM**: Strategy Pattern, zero language logic in the handler (`security_antipattern.py:39-52`). `_find_all_violations()` is the single scan path shared by `matches()`/`handle()` so they cannot disagree (line 109-111 comment). Per-language pattern counts are small (2-7 patterns/language + a 6-pattern universal `secret_strategy.py` for hardcoded credentials that applies "regardless of extension" per its own docstring, line 58).

**CONSUMER**: Decision only.

**VACUITY**: Real constructs (`eval`, `os.system`, `pickle.load`, `innerHTML`) are plausible LLM output under normal coding tasks; never fired in the sampled window but the acceptance tests use literal realistic code snippets, not fixture soup.

**DUPLICATION**: The universal `secret_strategy.py` (AWS keys, GitHub tokens, Stripe keys, private-key blocks) structurally OVERLAPS with `sensitive_content`'s `public_patterns`/`secret_word_list_path` mechanism — both can, in principle, be configured/built to catch "a hardcoded AWS key." They differ in mechanism (security_antipattern's credential patterns are hardcoded in Python and language-agnostic-by-construction; sensitive_content's are YAML-configured per-project and additionally cover git metadata that security_antipattern never sees) and in disclosure policy (sensitive_content's secret-word-list path never echoes the match; security_antipattern's deny reason shows the OWASP category and pattern name freely). Not clearly wrong to have both, but a real, un-cross-referenced overlap the judge should weigh.

**CONFIG**: Base config, `enabled: true`, priority 14.

**COST**: 2-7 regexes per applicable-language Write/Edit call, plus a fixed 6 universal credential patterns. Cheap.

**HISTORY**: 8 commits, `6330dc53 Add: SecurityAntipatternHandler - blocks hardcoded secrets and injection patterns`.

**FALSE-POSITIVE RECORD / CLAIM-EXCEEDS-MECHANISM (the significant finding)**: `CLAUDE/Plan/00204-security-antipattern-dataflow-categories/PLAN.md` (Status: **Not Started**, created 2026-08-10) documents that this handler's shipped guidance CLAIMED SQL-injection, weak-cryptography, and path-traversal detection that **never existed in any of the 11 language strategies, since the handler was first written** ("They were absent for a structural reason... found during the v3.52.0 release acceptance gate: a string-concatenated SQL query written at the live daemon was allowed. `eval()` at the same path was blocked, proving the handler was live and the path not excluded — so the miss was a genuinely absent pattern"). The v3.52.0 release corrected the DOCUMENTATION to match the actual mechanism (the `get_claude_md()` text I read above already reflects the fix). Plan 00204 is the still-open follow-up asking whether to actually BUILD the three missing categories, and explicitly reasons that naive construct-level regexes for them would be dangerous (high false-positive rate on the common safe case: `"SELECT ... " + str(row_id)` in a migration script is not an injection; `md5(path, usedforsecurity=False)` is this project's OWN sanctioned pattern) — i.e., the plan's own authors are wary of adding vacuous-guard-shaped rules to fix the doc gap.

**SIGNAL: SUSPECT** — the mechanism that exists is sound and not vacuous, but this is the cohort's clearest documented instance of a handler's CLAIM outrunning its MECHANISM for an unknown span of the project's life (found reactively, at a release gate, not by design) — precisely the category of defect this audit is looking for, even though the fix here was "correct the docs" rather than "the handler does nothing."

---

## sensitive_content

**CLAIM**: Blocks Write/Edit content (and git-metadata-writing Bash commands) matching configured public patterns or a gitignored secret word list (`sensitive_content.py:1-20`).

**MECHANISM**: Two independent, well-separated sources with different disclosure policies (public patterns show the match; the secret word list shows only a numeric index, delegated entirely to `utils/secret_redaction.py`). `_haystacks_for()` (lines 191-231) is the single dispatch point for BOTH `matches()` and `handle()`, preventing the "denied for text that wasn't actually the match basis" class of bug. Correctly scopes git-metadata checking to only WRITE subcommands (`commit`, `config`, `tag`, `branch`, `checkout`, `switch`, `merge`) gated on git appearing as an actual token (not a substring — line 239-264 uses `git_subcommand_index` specifically because `git -C /path commit` would otherwise offer `-C` as the subcommand and silently bypass the check, a documented near-miss the code comment calls out explicitly). Read-only git flags (`--grep`, `--list`, `-l`, `--get`) are explicitly exempted so cleanup/search work is never blocked by the tool meant to enable it.

**CONSUMER**: Decision only; the secret word list itself is read by `utils/secret_redaction.py` (a real, used consumer, not an orphaned artefact) and by `scripts/qa/check_git_history.py` for the separate whole-history sweep referenced in config comments.

**VACUITY**: Not vacuous — the public-pattern mechanism is live and configured with 3 real patterns in THIS project's own config (`vhosts-path`, `session-uuid`, `profanity`), each with a documented discovery story (the UUID pattern's negative lookahead was added after it blocked the ALL-ZEROS placeholder its own remediation message recommends; the profanity pattern's history includes a documented 1,308-false-positive regex-obfuscation failure before the literal form was adopted). This handler has the densest evidence of REAL prior false-positive discovery-and-fix in the cohort outside pipe_blocker.

**DUPLICATION**: See security_antipattern above — partial overlap on "hardcoded credential" detection, different mechanism and scope (this one also reaches git metadata, which security_antipattern cannot).

**CONFIG**: Base config, `enabled: true`, priority 14. `history_baseline` / `history_grandfathered_refs` config keys are consumed by a SEPARATE script (`scripts/qa/check_git_history.py`), not by this handler — worth noting the config block mixes write-time-handler options with batch-scan options in one YAML section, which could confuse a future maintainer about what this handler itself actually reads.

**COST**: Public patterns are compiled once and cached (`_COMPILED_PATTERN_CACHE`, module-level, keyed by source string) — a broken regex is cached as `None` so it's never re-attempted. Secret-term matching is delegated to `secret_redaction.get_cached_secret_terms`. Reasonably cheap per Write/Edit/git-metadata-Bash call.

**HISTORY**: 6 commits, `2a39521b Plan 00201: Add sensitive_content handler + shared secret-redaction utility`.

**FALSE-POSITIVE RECORD**: Multiple DOCUMENTED and FIXED false positives, all captured in the handler's own comments: (1) the all-zeros-UUID-placeholder self-block (fixed via negative lookahead), (2) the 1,308-false-positive profanity-regex-obfuscation incident (fixed by using literal word forms + a self-file exclude), (3) `_is_secret_list_itself()` exists specifically because the handler would otherwise "brick its own configuration" — found by dogfooding, per its own docstring (lines 330-343) — the first edit to add a term would deny itself with an opaque index and no way to act on it.

**SIGNAL: KEEP** — extensive, transparent self-documentation of prior false positives and their fixes is exactly what makes this handler trustworthy rather than suspect; the design shows active maintenance against real discovered edge cases, not accumulated cruft.

---

## sudo_pip

**CLAIM**: Blocks `sudo pip install` and its `sudo pip3`/`sudo python -m pip`/`sudo python3 -m pip` variants (`sudo_pip.py:31-42`).

**MECHANISM**: Single regex built from shared `SUDO_INVOCATION` + `OPTIONAL_PATH` fragments (`sudo_pip.py:17-28`), explicitly hardened (per its own comment) against two real respelling bypasses: `sudo -H pip install` (sudo's own options) and `sudo /usr/bin/pip install` (path-qualified binary) — both are described as "the FIRST thing a real user types," i.e. not exotic evasion but ordinary usage that the original `\bsudo\s+(pip3?|...)` anchor missed.

**CONSUMER**: Decision only.

**VACUITY**: Plausible — sudo-prefixed pip is an extremely common (if wrong) reflex.

**DUPLICATION**: See pip_break_system above — disjoint trigger conditions, not duplicative in a wasteful sense.

**CONFIG**: Base config, `enabled: true`, priority 22, `terminal=True`.

**COST**: One regex per Bash call. Negligible.

**HISTORY**: 11 commits, `e540fde4 Plan 00022: Add SudoPipHandler to block sudo pip install`.

**FALSE-POSITIVE RECORD**: None found; the two hardening fixes described above are BYPASS closures (false negatives fixed), not false-positive corrections.

**SIGNAL: KEEP**

---

## worktree_file_copy

**CLAIM**: Prevents `cp`/`mv`/`rsync` between a worktree directory and the main repo's `src/`/`tests`/`config/` (`worktree_file_copy.py:18-27`).

**MECHANISM**: Requires BOTH a worktree-path prefix AND a cp/mv/rsync verb AND a src/tests/config destination pattern to match (`worktree_file_copy.py:38-63`) — a 3-way AND, so it cannot fire on an unrelated copy command. Includes a same-worktree-branch exemption (`_is_same_worktree_operation`, lines 28-36) so moving files WITHIN one worktree's own branch is correctly allowed.

**CONSUMER**: Decision only.

**VACUITY**: Never fired in the sampled window. Plausibility is genuine but narrower than most of the cohort: it requires the agent to be actively using worktrees (an `isolation: "worktree"` Agent call or `--worktree` session) AND then attempt a cross-copy specifically into `src/`/`tests`/`config/` — a fairly specific compound scenario. CLAUDE.md's `worktree_create` and `agent_isolation_advisor` sections actively promote worktree usage elsewhere in this project, so the precondition (worktrees exist and are used) is real and growing, but the specific dangerous action (copying OUT of one instead of merging) is a narrower target than e.g. `destructive_git`'s everyday-command surface.

**DUPLICATION**: None.

**CONFIG**: Base config, `enabled: true`, priority 15, `HandlerTag.TERMINAL`.

**COST**: A handful of regex/string operations per Bash call containing a worktree-path substring (cheap pre-filter via `any(prefix in command...)` before the more expensive regex patterns run).

**HISTORY**: 9 commits, dates to `74b0989c Initial commit`.

**FALSE-POSITIVE RECORD**: None found.

**SIGNAL: KEEP** — real, narrow, correctly-scoped mechanism; lower observed/plausible trigger frequency than most of the cohort but not vacuous — the 3-way AND and the same-branch exemption show deliberate false-positive avoidance in the design itself, not just luck.
