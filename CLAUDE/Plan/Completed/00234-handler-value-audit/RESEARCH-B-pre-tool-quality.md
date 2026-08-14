# Cohort B — PreToolUse Quality/Workflow Handlers (18 handlers)

Evidence gathered 2026-08-13 against `/workspace` (self-install mode; this repo IS the
daemon's own upstream). All 18 handlers were read in full, config-checked against
`/workspace/.claude/hooks-daemon.yaml`, git-logged, and cross-checked against
`CLAUDE/development/LESSONS.md` and `CLAUDE/Plan/`. Two handlers were dogfooded live
during this audit (see `lsp_enforcement` — it blocked my own research greps, and a real
bug was found in the process).

## Cohort summary

| Handler                        | Signal              | Reason                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| ------------------------------ | ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `qa_suppression`               | KEEP                | Blocking, terminal, 40 tests, DBF-consistent (batch companion is the QA suppression check itself via linters); clean single-responsibility Strategy delegation                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `tdd_enforcement`              | KEEP                | Blocking, terminal, well-tested (strategy-per-language), directly named in CLAUDE.md's mandatory Code Lifecycle docs, no false-positive history found                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `comment_changelog`            | KEEP                | Blocking; docstring cites a measured zero-false-positive self-scan (Plan 00208) and explicitly demoted 3 signals to advisory after finding real false positives — rare, exemplary calibration discipline                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `comment_size`                 | KEEP                | Blocking with grow/shrink/same-size tiering that specifically avoids trapping legacy files; 35 tests including near-miss ALLOW case                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `markdown_organization`        | KEEP                | Blocking; largest/most complex handler in cohort (1080 lines) but load-bearing — I was blocked by its untracked-memory policy in this very session; 44-commit history of incremental precision fixes (worktrees, monorepo, daemon-owned templates), latest as recent as the last handful of commits — still being hardened, not abandoned                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `daemon_location_guard`        | KEEP                | Terminal blocking guard with a precise, well-commented regex; realistic risk (agents cd-ing into a vendored dependency dir) with a clear correct-usage alternative                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `gh_issue_comments`            | KEEP                | Terminal blocking; segment-scoped regex closes a real chained-command bypass (Plan 00140 "close bypasses in five...safety handlers"); 36 tests                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `gh_pr_comments`               | KEEP                | Near-identical twin of `gh_issue_comments`, same rigor, 37 tests. Flagging the pair's duplication as a DRY observation, not a signal against either                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `daemon_restart_verifier`      | SUSPECT             | Advisory fires on every `git commit` in this repo, unconditionally, with **no rate limiting** — and its entire message is a near-verbatim repeat of guidance already resident in CLAUDE.md body text (twice) and in its own `get_claude_md()` (auto-injected a third time). Net: the same paragraph appears in context 3 ways for every commit                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `task_tdd_advisor`             | SUSPECT             | `get_claude_md()` returns `None` (undocumented in CLAUDE.md) yet injects ~30 lines of RED/GREEN/REFACTOR guidance that is a near-restatement of `CLAUDE/CodeLifecycle/Features.md` and `CLAUDE/PlanWorkflow.md` — both of which are `@`-imported into CLAUDE.md and therefore **already fully resident in every session's context**, confirmed by direct observation in this conversation's own system prompt                                                                                                                                                                                                                                                                                                                                                  |
| `agent_isolation_advisor`      | KEEP                | Well-reasoned (postmortem-driven, Plan 00200), correctly silent in the single-agent case, has an explicit negative-case acceptance test, fails safe (registry-unreadable → 0 → silent)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `lsp_enforcement`              | STRONG-SUSPECT      | Not vacuous — it fired on my own realistic greps live during this audit (see dossier). But: (1) a genuine reproducible bug in the single-file exemption when a command is multi-line (very common Bash-tool shape) causes false positives on exactly the "obviously fine" case its own regression test targets; (2) it steers toward LSP tools (`goToDefinition` etc.) that were **not resolvable via `ToolSearch` in this session** despite `ENABLE_LSP_TOOL=1` being set — unverifiable whether the tools it prescribes actually exist for the agent hitting the block; (3) `block_once` accounting appears session/history-scoped in a way that reblocked a *different* pattern shortly after an apparent "already blocked once" state, worth a closer look |
| `global_npm_advisor`           | KEEP                | Simple, narrowly-scoped, advisory-only, non-blocking; dormant in this project (no `package.json` anywhere in the repo) but that's expected — it's a portable handler for JS/TS client projects, not a self-install concern                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `npm_command`                  | KEEP                | Same "dormant here, live in JS projects" profile as `global_npm_advisor`; blocking behaviour is config/package.json-gated (degrades to advisory automatically when no `llm:` scripts exist), which is a deliberately safe default                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `validate_instruction_content` | KEEP                | Terminal blocking scoped tightly to CLAUDE.md/README.md; 49 tests incl. a clean-content ALLOW case; code-block exemption is correct and tested                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `daemon_docs_guard`            | KEEP (scope caveat) | Correctly-built, well-tested (22 tests), advisory-only — but **structurally vacuous in THIS repo**: the pattern it matches (`hooks-daemon/CLAUDE/`) only exists in a client install layout (daemon cloned to `.claude/hooks-daemon/`); in self-install mode (this repo) that path never exists, so the guard cannot fire here. Not evidence it's dead everywhere, only that its "consumer" is exclusively client installs                                                                                                                                                                                                                                                                                                                                      |
| `web_search_year`              | KEEP                | Simple, correctly time-relative (computes current year live, not hardcoded), advisory-only, one clear job                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `british_english`              | KEEP (with history) | Advisory-only, but its own git history contains a striking DBF case study: 82 pre-existing violations across 27 tracked files accumulated silently for years because the handler is write-time-only and cannot see what's already on disk. Fixed by adding a batch companion (`scripts/qa/check_british_english.py`, wired into `run_all.sh`) that shares the same pattern dict by identity. The gap is now closed; flagging as history, not a live defect                                                                                                                                                                                                                                                                                                     |

## Cross-cutting observations

1. **Structural duplication for advisory handlers with non-null `get_claude_md()`.** Any handler whose guidance is auto-injected into CLAUDE.md's `<hooksdaemon>` section (which is itself resident in *every* session) pays for its advice at least twice: once as always-loaded doc text, again as live context on every match. `daemon_restart_verifier` is the clearest example — its fire-time message and its `get_claude_md()` text are nearly identical, and the same instruction *also* appears twice more in CLAUDE.md's hand-written body (Release Workflow section, Code Lifecycle "Non-Negotiable Rule"). None of the 18 handlers in this cohort implement any rate-limiting/TTL despite the codebase having an established convention for it elsewhere (`command_hints`, `critical_thinking_advisory` — outside this cohort) — no shared rate-limit utility exists in `core/` or `utils/` for this cohort to reuse, which may be *why* none of them do it.

2. **DBF gap pattern confirmed once, closed once.** `british_english` is a real, documented instance of the exact failure mode the audit brief calls out (write-time guard blind to pre-existing violations) — and it's the one instance in this cohort where the batch companion was actually built and wired in. Worth checking whether `comment_changelog`, `comment_size`, `qa_suppression`, `tdd_enforcement`, and `markdown_organization` (all of which are also write-time-only PreToolUse blockers) have equivalent batch/sweep companions — I did not verify this for all five; `qa_suppression`'s territory is already covered by language linters (ruff/eslint/etc.) at QA time, but that's a different check catching a different symptom, not a scan for *pre-existing suppression comments already on disk*.

3. **`lsp_enforcement` deserves the deepest follow-up.** It is unambiguously NOT vacuous (it fired on me twice, unprompted, during ordinary research greps), which makes it the opposite problem from `transcript_archiver` — it's active and consequential, but I found a live, reproducible false-positive class in its single-file exemption (multi-line Bash commands escape the exemption because the segmentation regex doesn't treat `\n` as a terminator), and I could not confirm the LSP tools it recommends are actually reachable from a subagent context in this environment. This is the one handler in the cohort where "fires on realistic input" and "fires *correctly*" diverge.

4. **Two near-identical pairs.** `gh_issue_comments`/`gh_pr_comments` and `global_npm_advisor`/`npm_command`(partial) show the same logic duplicated per-domain rather than parameterized. Not a correctness problem — both pairs are well-tested — but a DRY opportunity if anyone revisits this cohort.

---

## agent_isolation_advisor

**CLAIM**: Advise `isolation: "worktree"` on the Agent tool when ≥2 live agent threads already share the checkout, because a peer's bare `git commit` can silently absorb another agent's staged work (`agent_isolation_advisor.py:56-64`).

**MECHANISM**: `matches()` (`:92-105`) requires: tool is `Task`, `tool_input.prompt` is non-empty, `isolation` is not already `"worktree"` (case-insensitive), AND `_count_live_threads() >= 2` read from the on-disk thread registry (`status_line/thread_registry.py`). All four conditions are independently checkable against realistic input — no impossible condition.

**CONSUMER**: Pure advisory context injection to the spawning agent's window. Text: use `isolation: "worktree"`, merge back with `git merge`/`git cherry-pick`; explicitly names when to KEEP the shared tree. This project's own `<hooksdaemon>` CLAUDE.md section carries the identical guidance as static resident text — so, like the others below, this info exists twice, but the live-fire version is genuinely tied to a real-time signal (thread count) the static text can't carry.

**VACUITY**: Not vacuous — requires genuine multi-thread state, which is realistic in this multi-agent audit itself (this session is one of ~30 sibling agents per the teammate list). 14 unit tests including a registry-unreadable-degrades-to-0 test and a negative acceptance test (already-isolated agent stays silent, Plan 00200 Task 6.4 — explicitly designed to avoid nagging someone who already did the right thing).

**DUPLICATION**: Overlaps only with its own `get_claude_md()` text (see cross-cutting #1). No other handler covers concurrent-agent git-index collisions.

**CONFIG**: `enabled: true`, priority 46, default-enabled (no `get_default_enabled` override) — `.claude/hooks-daemon.yaml:324-326`.

**COST**: One extra file read (thread registry) + regex/string check per `Task` tool call. Cheap. Fires only when the precondition (≥2 threads) is real, so no baseline tax in single-agent sessions.

**HISTORY**: 1 commit total (`af58d535`, Plan 00200 Task 6.5) — brand new, added directly in response to a documented 3-incident postmortem (staged work absorbed/lost by a peer's bare commit), not speculative.

**FALSE-POSITIVE RECORD**: None found (too new / no incidents in LESSONS.md or Plan folders).

**SIGNAL: KEEP** — postmortem-driven, narrowly scoped, provably silent in the common case, real negative-case test.

---

## british_english

**CLAIM**: Warn (never block) about American spellings (`color`, `behavior`, `organize`, etc.) in `.md`/`.ejs`/`.html`/`.txt` files under `private_html`, `docs`, `CLAUDE` directories (`british_english.py:17-34`).

**MECHANISM**: `matches()` requires Write/Edit, extension in list, directory-name substring match, then a code-block-aware regex scan (`find_american_spellings`, `:121-161`). All conditions realistic; the directory-substring check (`dir in file_path`) is loose (matches `CLAUDE` anywhere in the path, e.g. `/tmp/xCLAUDEy/`) but that's an over-broad match, not an impossible one.

**CONSUMER**: Advisory context to the writing agent. `get_claude_md()` returns `None` — this handler carries **no** resident CLAUDE.md guidance, so it is entirely undocumented outside firing live (confirmed absent from the `<hooksdaemon>` section text in this session's system prompt).

**VACUITY**: Not vacuous — genuinely fires on ordinary American spelling in prose, which is common. One dedicated acceptance test with realistic content ("The color of the organization logo should favor readability").

**DUPLICATION**: Its own batch equivalent exists and is wired into QA: `scripts/qa/check_british_english.py` (confirmed present in `scripts/qa/run_all.sh:226`), sharing `SPELLING_CHECKS` by object identity per the handler's own docstring (`:124-128`) and per commit `dc1513d3`.

**CONFIG**: `enabled: true`, priority 60, default-enabled — `.claude/hooks-daemon.yaml:405-407`.

**COST**: Per-line regex scan (9 patterns) over Write/Edit content restricted to a handful of directories/extensions — cheap, narrowly gated.

**HISTORY**: 10 commits. Most notable: `dc1513d3` "Resume audit: the British-English handler was failing its own author" — a genuine DBF incident. The project's OWN tracked docs (this project enforces the rule it wrote) carried **82 American spellings across 27 files** at the time of that audit, invisible to this write-time-only handler because they predated it or were introduced through non-Write/Edit paths (e.g. a generated doc). Root cause: no batch scanner existed yet. Fixed in the same commit by adding `check_british_english.py`.

**FALSE-POSITIVE RECORD**: Same commit also fixed a batch/handler divergence risk: `behavior` is a genuine Claude Code JSON field name (`decision.behavior`) that must NOT be rewritten when it appears in a code block — both scanners correctly skip fenced blocks, and the fix was applied "line-precisely," not via blanket find/replace, to avoid breaking documented API text.

**SIGNAL: KEEP** — real DBF gap found and closed with a proper batch companion; the handler itself was never wrong, its *isolation* (no batch equivalent) was the defect, and that's now fixed.

---

## comment_changelog

**CLAIM**: Block (or advise) writing changelog-shaped historical narrative into code comments; history belongs in git/changelog/JOURNAL, not comments (`comment_changelog.py:1-20`).

**MECHANISM**: Two high-precision BLOCK signals (`Prior <version>:`/`Previously <version>:`, dated entries `YYYY-MM-DD:`) and five lower-precision ADVISE-only signals. `matches()`/`handle()` scope detection to actual comment SPANS (via a shared `CommentStrategyRegistry`), not raw code — so it can't fire on non-comment text. Both realistic and non-trivial to trigger by accident (requires the specific phrasing).

**CONSUMER**: DENY reason (blocking signals) or ALLOW+context (advisory signals) to the writing agent.

**VACUITY**: Emphatically not vacuous, and — unusually for this cohort — the docstring cites a **measured** false-positive analysis: Plan 00208 ran a whole-repo self-scan across ~1,080 source/test files and found the two blocking signals hit ZERO false positives, while three OTHER candidate signals (originally proposed as blocking) DID false-positive on legitimate code (version-processing utility docstrings, external-tool deprecation notes) and were explicitly demoted to advisory-only as a result (`:67-81`). This is the strongest calibration evidence in the cohort — a documented instance of the project correctting its own false positives before shipping, not after a field incident.

**DUPLICATION**: None found — no other handler or QA script scans comment content for changelog narrative specifically (`comment_size` scans the same spans but for LENGTH, an orthogonal property; both explicitly reference each other in their docstrings as siblings, not overlap).

**CONFIG**: `enabled: true`, priority 31, default-enabled — `.claude/hooks-daemon.yaml:266-271`.

**COST**: Comment-span extraction (shared with `comment_size`) + a handful of regexes over each span's text. Bounded by file size; no subprocess spawns.

**HISTORY**: 3 commits, all Plan 00208 (a dedicated plan for this exact handler + its sibling `comment_size`), including the field report that motivated it (a bash version-marker comment that grew to 5,645 characters over six releases and broke a banner that echoed it).

**FALSE-POSITIVE RECORD**: The self-scan (documented in the code, not just claimed) IS the false-positive record — and it's a clean one for the two shipped blocking signals.

**SIGNAL: KEEP** — the strongest-evidenced handler in the cohort; explicit measurement-driven precision tuning is exactly what the audit is checking for and rarely found elsewhere.

---

## comment_size

**CLAIM**: Cap over-long comments (single line >400 chars OR contiguous block >40 lines), using the same grow/shrink/same-size tiering as the existing `plan-doc-size` check so legacy oversized comments stay editable (`comment_size.py:1-20`).

**MECHANISM**: `matches()` finds any breaching non-doc comment span. `handle()` then compares total comment character count before/after the edit: growth → DENY (unless escape hatch or warn mode); same-size → advise only; shrink → silent ALLOW. This tiering is specifically designed to make the "impossible to ever fix" failure mode (a blocker that can never be satisfied because the existing content already breaches) structurally impossible — shrinking a violation is always allowed.

**CONSUMER**: DENY reason / advisory context to the writing agent, with an escape hatch (`MUST_EXCEED_COMMENT_SIZE_BECAUSE:`) for verbatim licence text etc.

**VACUITY**: Not vacuous. 35 tests including an explicit near-miss ALLOW case (an ordinary short comment) and a DENY case for a brand-new file whose comment already exceeds the limit (correctly always counts as "growth" since there's no prior state).

**DUPLICATION**: None — comment length is not checked anywhere else. Explicitly NOT the same concern as `comment_changelog` (orthogonal: length vs. content-shape).

**CONFIG**: `enabled: true`, priority 33, default-enabled — `.claude/hooks-daemon.yaml:273-279`.

**COST**: Same span-extraction machinery as `comment_changelog`; for Edit it also reads `old_string` (already in the tool call) or, for Write, does a disk read of the pre-existing file to compute the "before" total — one extra file I/O only on Write-to-existing-file (rare — Write normally targets new/overwritten files).

**HISTORY**: 2 commits, both Plan 00208 (paired sibling of `comment_changelog`).

**FALSE-POSITIVE RECORD**: None found; too new, and the tiering design pre-empts the most likely failure mode (freezing a legacy file) by construction.

**SIGNAL: KEEP** — precise scope, thoughtful tiering, good tests, no history of trouble.

---

## daemon_docs_guard

**CLAIM**: Warn when Read/Write/Edit targets `.../hooks-daemon/CLAUDE/...` — the daemon's OWN internal docs copy that ships alongside a client project's real `CLAUDE/` directory in normal (non-self-install) installs — because Claude Code's `@CLAUDE/...` resolution can accidentally read the wrong copy (`daemon_docs_guard.py:14-38`).

**MECHANISM**: `matches()` is a single substring check: `"hooks-daemon/CLAUDE/" in file_path` for Read/Write/Edit tools. Extremely narrow, precise, cannot false-positive on unrelated paths, and cannot fire at all unless that literal path segment exists.

**CONSUMER**: Advisory context pointing the agent at the correct project-root path instead.

**VACUITY — important caveat**: This handler is realistic and correctly built, but **its trigger condition cannot exist in THIS repo**. This project (`/workspace`) is the daemon's own upstream, running in **self-install mode** — the daemon's source lives at `/workspace/src/`, not cloned to `.claude/hooks-daemon/`. `src/CLAUDE.md` (read during this audit) confirms the client-install directory layout this handler defends against is a DIFFERENT deployment shape than this one. So: not vacuous in general (client installs genuinely have this directory collision), but structurally dormant for the entire life of this specific repository. 22 unit tests use synthetic `/tmp/...` fixtures (not a real client install), which is appropriate but means there's no evidence from a LIVE client-mode test that the collision path is hit in practice — `CLAUDE.md`'s own "Client-Mode Testing" convention (`scripts/dummy-client-repo.sh`) would be the way to get that evidence and I did not run it (out of scope: research-only, no destructive/mutating commands).

**DUPLICATION**: None found.

**CONFIG**: `enabled: true`, priority 57, default-enabled — `.claude/hooks-daemon.yaml:401-403`.

**COST**: Single substring check — negligible.

**HISTORY**: 2 commits; added alongside an "installer rename for CLAUDE/ collision fix" (i.e., a real bug this handler was built specifically to catch/mitigate going forward).

**FALSE-POSITIVE RECORD**: None found.

**SIGNAL: KEEP** — correctly scoped for its actual audience (client installs), just note for the judge that self-install-mode repos (like this one) will never see it fire, which is expected and fine, not a defect.

---

## daemon_location_guard

**CLAIM**: Block `cd` into `.claude/hooks-daemon/` (or subdirectories) because daemon CLI commands must run from the project root (`daemon_location_guard.py:23-29`).

**MECHANISM**: A single, carefully-commented regex (`_CD_INTO_DAEMON_DIR`, `:18-20`) anchored on `\bcd\s+` targeting the daemon dir, with an explicit boundary condition documented to avoid matching the CONFIG FILE `.claude/hooks-daemon.yaml` (only a path separator/whitespace/separator/quote/EOL can follow, never `.`). This is a rare case in the cohort of a regex whose false-positive avoidance is explicitly reasoned about in a comment rather than discovered via a field incident.

**CONSUMER**: DENY reason with the correct alternative commands and an upgrade-process walkthrough.

**VACUITY**: Realistic — an agent debugging the daemon plausibly tries to `cd` into its source to poke around. 19 tests.

**DUPLICATION**: None — unique concern.

**CONFIG**: `enabled: true`, priority 11, default-enabled (implied by `.claude/hooks-daemon.yaml:51`, though not shown with an explicit `enabled:` line in the excerpt I captured — the comment confirms it's configured, priority matches `Priority.DAEMON_LOCATION_GUARD` used in code).

**COST**: One regex search per Bash command — negligible.

**HISTORY**: 7 commits, oldest substantive one adding the handler alongside `project_root` config plumbing (not itself a sign of trouble — infrastructure commits, not fix commits).

**FALSE-POSITIVE RECORD**: None found in LESSONS.md/Plan search.

**SIGNAL: KEEP** — precise, well-reasoned regex, clean test coverage, genuine risk (this project literally instructs agents elsewhere in CLAUDE.md never to edit `.claude/hooks-daemon/` — this handler enforces the physical precondition for that rule).

---

## daemon_restart_verifier

**CLAIM**: Advise (never block) verifying `./bin/hooks-daemon restart` before any `git commit` in this repo, because unit tests alone don't catch import errors (`daemon_restart_verifier.py:1-10`).

**MECHANISM**: `matches()`: Bash tool, `is_hooks_daemon_repo()` true, command contains `\bgit\s+commit\b`. Realistic and correct — fires on literally every commit in this repo.

**CONSUMER**: Advisory context + guidance block, same wording every time, no memory of whether the agent already restarted the daemon this session.

**VACUITY**: Not vacuous — I would expect this to have fired on every commit made in this repo's history since it shipped.

**DUPLICATION — the real finding**: This exact guidance is stated at least **three** times in resident/injected context for every single commit in this repo:

1. CLAUDE.md's own hand-written body: "## ⚠️ CRITICAL: RELEASE WORKFLOW" and the "Code Lifecycle" "🚨 The Non-Negotiable Rule" section both already say, verbatim in spirit, "EVERY change MUST pass daemon restart verification" / "restart the daemon, verify RUNNING" (this text is directly visible in this session's own system prompt).
2. This handler's own `get_claude_md()` (`:106-117`), auto-injected into the `<hooksdaemon>` section of CLAUDE.md — also resident every session.
3. This handler's live `handle()` context, fired again at the moment of every `git commit`, word-for-word similar to #2.

None of the three carry session-scoped state (e.g., "has the daemon already been restarted since the last source edit this session?") — the same static paragraph fires unconditionally regardless of whether the agent already did exactly what it's being told to do. Compare to `agent_isolation_advisor`, which DOES condition on a live, checkable signal (thread count) rather than firing on every occurrence of its trigger tool.

**CONFIG**: `enabled: true`, priority 23, default-enabled — `.claude/hooks-daemon.yaml:248-250`.

**COST**: One regex match per Bash command containing "git commit" in this repo only (gated correctly to avoid firing in client projects) — cheap per-call, but the injected text is a multi-line reminder repeated on every commit with zero variation and zero rate limiting.

**HISTORY**: 7 commits; framed from the start around the "5-handler import bug" postmortem this project references repeatedly (a real, named incident — not speculative).

**FALSE-POSITIVE RECORD**: None found (it can't really false-positive — `git commit` really is happening).

**SIGNAL: SUSPECT** — not wrong to exist, but the STRONGEST candidate in this cohort for "already stated in CLAUDE.md and therefore resident anyway" (category i from the brief) — it is textually near-identical to content injected via `get_claude_md()` AND to hand-written CLAUDE.md prose, with no rate-limiting or session-state check to avoid repeating itself on every commit in a session that just restarted the daemon five minutes ago.

---

## gh_issue_comments

**CLAIM**: Block `gh issue view` without `--comments` (or `--json ...,comments`) because issue comments carry context not in the issue body (`gh_issue_comments.py:14-19`).

**MECHANISM**: `matches()` extracts the `gh issue view` SEGMENT of the command (bounded by the next `;`/`&&`/`||`/`|`) and checks for `--comments` or `--json` with `comments` in the field list WITHIN that segment only — deliberately scoped so a flag in an unrelated chained command can't spuriously satisfy the requirement (`:34-51`). This segment-scoping is itself the fix for a real bypass (see HISTORY).

**CONSUMER**: DENY reason with a computed suggested corrected command.

**VACUITY**: Realistic and simple — `gh issue view N` without `--comments` is exactly what an agent would type by default. 36 tests.

**DUPLICATION**: `gh_pr_comments` is the same logic for PRs instead of issues — genuinely duplicated implementation (two ~150-line files that are near copy-paste of each other with issue/pr swapped), a DRY opportunity but not a correctness problem.

**CONFIG**: `enabled: true`, priority 40, default-enabled — `.claude/hooks-daemon.yaml:328-330`.

**COST**: A handful of regex operations per Bash `gh` command — negligible.

**HISTORY**: 16 commits — notably more churn than its twin (`gh_pr_comments`, 2 commits). Two drivers: (1) a "command redirection" feature was added then fully reverted a few commits later (`f03fcbd4` add → `6898a159` remove) — a shipped-then-reverted feature experiment, not a false-positive bug; (2) `16767504` "Plan 00140 fix(safety): close bypasses in five pre_tool_use safety handlers" — this IS the commit that added the segment-scoping described above, i.e. a real bypass (chained-command flag satisfying an unrelated `gh issue view`) was found and fixed.

**FALSE-POSITIVE RECORD**: The Plan 00140 fix was closing a BYPASS (false negative — command that should have been blocked wasn't), not a false positive. No over-blocking incidents found.

**SIGNAL: KEEP** — simple, well-tested, and its one real historical issue (a bypass) was found and fixed with a regression test.

---

## gh_pr_comments

**CLAIM**: Same as `gh_issue_comments` but for `gh pr view` (`gh_pr_comments.py:25-31`).

**MECHANISM**: Structurally identical to `gh_issue_comments` — segment-scoped extraction (`_extract_gh_pr_view_segment`, `:46-69`), same `--comments`/`--json` logic. Already ships with the segment-scoping that `gh_issue_comments` had to retrofit via a bypass fix, since this handler was added later.

**CONSUMER**: DENY reason with computed suggestion.

**VACUITY**: Same profile as `gh_issue_comments` — realistic, simple, 37 tests.

**DUPLICATION**: See `gh_issue_comments` — this pair should arguably share one parameterized implementation.

**CONFIG**: `enabled: true`, priority 40, default-enabled — `.claude/hooks-daemon.yaml:332-334`.

**COST**: Negligible, same profile as its twin.

**HISTORY**: Only 2 commits (added directly with segment-scoping already in place, benefiting from the lesson learned on its older twin) — never needed the bypass fix `gh_issue_comments` did.

**FALSE-POSITIVE RECORD**: None found.

**SIGNAL: KEEP** — same reasoning as `gh_issue_comments`; if anything, cleaner history because it inherited the fix its twin needed.

---

## global_npm_advisor

**CLAIM**: Advise (never block) considering `npx` instead of `npm install -g` / `yarn global add` (`global_npm_advisor.py:19-34`).

**MECHANISM**: `matches()`: single regex `\b(npm\s+(install|i)\s+-g|yarn\s+global\s+add)\b` on the Bash command. Simple, precise, cannot misfire on unrelated npm usage (requires the `-g`/`global add` token specifically).

**CONSUMER**: Advisory context listing npx benefits and explicitly naming when a global install IS appropriate (dev tools used across all projects) — avoids being a blanket "never do this."

**VACUITY**: Realistic for JS/TS projects, but **this project itself has no `package.json` anywhere** (confirmed via `find`), so this handler is dormant in its own home repo. That's expected — it's a portable rule for client JS/TS projects, not a self-install-mode concern, same caveat class as `daemon_docs_guard` but for the opposite reason (this one targets client projects generically, not the daemon-specific directory layout).

**DUPLICATION**: None found; distinct concern from `npm_command` (global installs vs. script-running conventions).

**CONFIG**: `enabled: true`, priority 42, default-enabled — `.claude/hooks-daemon.yaml:340-342`.

**COST**: One regex match per Bash command — negligible.

**HISTORY**: 10 commits, oldest substantive `3e46911c` "Plan 00022: Add GlobalNpmAdvisorHandler to advise on npm install -g" — a deliberate, planned addition, not speculative.

**FALSE-POSITIVE RECORD**: None found.

**SIGNAL: KEEP** — simple, correctly scoped, advisory-only with a fair two-sided message (not just "never do X").

---

## npm_command

**CLAIM**: Enforce `llm:`-prefixed `npm run`/block raw `npx` tool usage when `llm:` scripts exist in `package.json`; degrade to advisory when they don't (`npm_command.py:1-5`).

**MECHANISM**: `matches()` checks for piped npm/npx commands (always blocked — `llm:` commands write to cache files, piping is pointless), then `npm run <script>` not already `llm:`-prefixed and not in a small allowlist (`clean`, `dev:permissive`), then `npx <tool>` where tool has a known `llm:` equivalent (tsc, eslint, prettier, cspell, playwright, tsx). All conditions are realistic for a JS/TS project using this project's own `llm:` convention.

**CONSUMER**: DENY reason (enforcement mode) or ALLOW+advisory (when no `llm:` scripts exist yet) pointing at `npm run llm:X` and a cache-file/`jq` workflow.

**VACUITY**: Same "dormant in this specific repo" caveat as `global_npm_advisor` (no `package.json` here) — but the logic itself is sound and doesn't require this repo to validate it; 74 unit tests is the largest test suite in the cohort relative to handler complexity, covering both enforcement and advisory modes.

**DUPLICATION**: None found; complements rather than overlaps `global_npm_advisor`.

**CONFIG**: `enabled: true`, priority 49, default-enabled — `.claude/hooks-daemon.yaml:364-366`.

**COST**: A handful of regex operations per Bash command, plus one `has_llm_commands_in_package_json()` call cached at `__init__` (not re-read per event) — cheap.

**HISTORY**: 20 commits (present since Initial commit, so this includes iterative hardening over the whole project life) — the highest commit count relative to file size in the cohort after `markdown_organization`, suggesting steady incremental refinement rather than a single burst of false-positive firefighting.

**FALSE-POSITIVE RECORD**: None specifically named in LESSONS.md/Plan search, though the acceptance test itself (`:214-228`) is conditional on `self.has_llm_commands`, meaning its own test suite's expected outcome changes based on repo state — a slightly fragile test design worth the judge's attention, though not a production false-positive.

**SIGNAL: KEEP** — sound design, good degrade-to-advisory default, large test suite; the "dormant here" caveat is not a defect.

---

## lsp_enforcement

**CLAIM**: Steer `Grep`/`Bash(grep|rg)` symbol-lookup-shaped queries toward LSP tools (`goToDefinition`, `findReferences`, `workspaceSymbol`, `hover`, `documentSymbol`) instead, in `block_once` mode by default (first occurrence denied, subsequent allowed) (`lsp_enforcement.py:1-19`).

**MECHANISM**: Extensive, carefully-commented pattern classification (`_is_symbol_like`, `:281-326`): definition keywords, import statements, PascalCase/snake_case identifiers vs. regex-metacharacter-bearing text searches. A dedicated single-file exemption (`_is_single_file_bash_grep`, `:220-250`) was added in Plan 00200 specifically to stop it firing on a grep already scoped to one named file (a real dogfooding false positive, per its own regression test comment at `:471-485`).

**CONSUMER**: DENY (or ALLOW+context in advisory/strict modes) naming a suggested LSP operation.

**VACUITY — directly observed, not inferred**: This handler is unambiguously **not** vacuous. During this very audit, it fired TWICE on my own ordinary research greps (`grep -n "lsp_enforcement" ...` and later `grep -n "get_default_enabled" ...`), unprompted, mid-session. This is about as strong a "fires on realistic input" signal as evidence gathering can produce — I was not trying to test it, it caught me doing normal work.

**A live, reproducible false positive was found during this audit**: the single-file exemption (built specifically to fix a prior false positive, Plan 00200) itself has a gap. `_is_single_file_bash_grep` extracts the "tail" after the grep match and looks for shell separators (`&&`, `||`, `;`, `|`) to bound the segment — but **not newline**. When the Bash tool call is a genuine multi-line script (extremely common shape for this tool — multiple commands on separate lines with no explicit `;`), the "tail" spans every subsequent line as if they were additional positional arguments to the SAME grep, `len(targets) != 1` becomes true, and the exemption silently fails to apply. I reproduced this directly: a `grep -n "X" single-file.yaml` embedded as the first line of a 3-line Bash call was BLOCKED; the identical command run alone in its own Bash call was ALLOWED with zero context (confirmed no match at all). This is exactly the class of false positive the Plan 00200 fix was supposed to eliminate, still present for the (very common) multi-line-script shape.

**Unresolved**: `ENABLE_LSP_TOOL=1` is set in this environment (confirming the daemon believes LSP is configured), but `ToolSearch` in this session could not resolve any LSP tool (`goToDefinition` et al.) as a callable deferred tool — I could not confirm the tools this handler prescribes are actually reachable from wherever the block fires. This may be a subagent-specific limitation (all four `lsp_enforcement` acceptance tests are marked `requires_main_thread=True`, unlike every other handler in the cohort, which is itself a signal the handler's author knows LSP tool availability is main-thread-only or otherwise conditional) rather than proof the tools don't exist for the main session — flagging as unresolved, not as a defect.

**DUPLICATION**: This is the ONLY opt-in-by-default handler in the whole cohort (`get_default_enabled()` returns `False`, `:155-163`) — every other handler in this cohort defaults to enabled. This project has explicitly opted in (`.claude/hooks-daemon.yaml:309-314`).

**CONFIG**: `enabled: true` (explicit opt-in), priority 38, `mode: block_once`, `no_lsp_mode: block`.

**COST**: Non-trivial regex work per Grep/Bash-grep call (multiple compiled patterns, segment extraction, flag-skipping), plus a persisted block-count lookup via the data layer on every match (`_get_block_count`, `:177-190`) — the heaviest per-event cost in the cohort among the ones I inspected closely, though still sub-millisecond-class work, not a subprocess.

**HISTORY**: 9 commits. Plan 00075 (original), then incremental hardening (Plan 00133 opt-in flip, Plan 00140 "narrow lsp errors, drop dead code", Plan 00200 single-file scoping). The trajectory is "repeatedly patched for precision," which per the audit brief's framing is worth flagging — though in this case each patch closed a genuine, named gap rather than symptomatically chasing a wrong concept.

**FALSE-POSITIVE RECORD**: Plan 00075's own success criteria explicitly targeted "\<5% false positive rate" (an accepted-nonzero target, unusual candor for this codebase). Plan 00200 fixed one concrete false positive (single-file grep). This audit found a live gap in that same fix (multi-line command shape).

**SIGNAL: STRONG-SUSPECT** — not for vacuity (it's the most demonstrably-live handler in the cohort) but for correctness: a real, reproducible false positive was found live during this audit in the exact code path meant to have already fixed this class of bug, plus an unresolved question about whether the tools it prescribes are reachable in every context that can trigger it.

---

## markdown_organization

**CLAIM**: Enforce markdown file organization (only `CLAUDE/`, `docs/`, `untracked/`, `RELEASES/`, a few other named locations are valid write targets), redirect Claude Code's native planning-mode writes into the project's `CLAUDE/Plan/` structure, and (configurable) block untracked Claude auto-memory writes including via Bash redirect/tee side-doors (`markdown_organization.py:1-90`).

**MECHANISM**: By far the most complex handler in the cohort (1080 lines, `matches()` alone spans ~230 lines). Layers: bash-memory-write-target detection → planning-mode-write detection → Claude-memory-path detection → project-root containment check → worktree re-rooting → standard-root-file allowlist → monorepo/dependency-directory sub-project handling → custom `allowed_markdown_paths` override → `extra_allowed_markdown_paths` additive rescue. Every branch I read maps to a plausible real scenario (documented in comments with the specific bug it fixes), not a synthetic edge case.

**CONSUMER**: DENY reason with a full menu of valid locations, or a specialist DENY message for the untracked-memory policy explaining the tracked-docs alternative (progressive disclosure via `.claude/rules/*.md`, skills, etc.).

**VACUITY — directly observed**: Not vacuous. The `allow_untracked_claude_memory: false` policy this handler enforces is EXACTLY what the memory-writing instructions in my own system prompt describe ("Writing to Claude auto-memory files... is blocked"). This handler is genuinely load-bearing for this project's own memory-management policy.

**DUPLICATION**: None found as a competing handler, though its `get_claude_md()` output (~40 lines on the untracked-memory policy alone) is, like others in this cohort, ALSO resident via the `<hooksdaemon>` CLAUDE.md section — but unlike the SUSPECT cases above, that policy text does NOT then also duplicate into a live fire-time message word-for-word; the fire-time DENY message (`_deny_untracked_memory`, `:978-1011`) is substantively the same content but is the ONLY place a blocked agent actually sees it in the moment of being blocked, so this is a defensible single live+doc pairing, not triple-redundancy.

**CONFIG**: `enabled: true`, priority 50, default-enabled, `allow_untracked_claude_memory: false` explicitly set (this project's own dogfooding, per its own comment) — `.claude/hooks-daemon.yaml:368-394`.

**COST**: The most expensive `matches()` in the cohort — multiple `Path.resolve()` calls, `relative_to()`, several regex matches, potential filesystem stat calls via `effective_project_relative_path`. Still well under any threshold that would matter for a hook round-trip, but worth naming as the heaviest single handler here.

**HISTORY**: 44 commits — the most-patched handler in the cohort by a wide margin, and the most recent commit (`d8d5b7b7 Fix: markdown_organization misdetects daemon-owned template/snapshot files as plans`) is within the last handful of commits to this file, i.e. **still being actively hardened for false positives as of very recently**. Per the audit brief's framing ("repeatedly patched for false positives — a signal the concept is wrong, not the regex"), this is worth the judge weighing carefully: the pattern here reads more like "broad, high-surface-area policy enforcement across an inherently varied set of real-world path shapes (worktrees, monorepos, vendored deps, daemon-internal template files)" than "the core concept doesn't work" — each fix closed a distinct, named, real scenario rather than re-litigating the same bug. But 44 commits of fixes on one handler is nonetheless the strongest volume-of-churn signal in the cohort and deserves scrutiny beyond what I can certify from a read-only pass.

**FALSE-POSITIVE RECORD**: Extensive, all in commit messages: worktree misclassification (`ec7c8490`), standard-root files wrongly blocked (`b13c3212`), plan-folder race condition (`92881f11`, `ef15bc8d`), and most recently daemon-owned template files misdetected as plans (`d8d5b7b7`).

**SIGNAL: KEEP** — genuinely load-bearing (I was blocked by it, correctly, in the memory-policy sense elsewhere in this very session's constraints), well-tested (173 tests, the largest suite in the cohort), but flagging the 44-commit churn history explicitly so the judge can decide whether "still finding new edge cases after this many fixes" crosses into "the surface area is too broad for one handler" — I don't have a strong opinion either way from a read-only audit.

---

## qa_suppression

**CLAIM**: Block QA suppression directives (`noqa`, `type: ignore`, `eslint-disable`, `nolint`, `@SuppressWarnings`, `#[allow(...)]`, etc.) across 11 languages via Strategy Pattern delegation (`qa_suppression.py:1-8`).

**MECHANISM**: Zero language-specific logic in the handler itself — delegates entirely to `QaSuppressionStrategyRegistry`/`QaSuppressionStrategy` per file extension. `matches()` requires Write/Edit, a resolvable strategy for the extension, not in `skip_directories` or configured excludes, and a forbidden-pattern regex hit in the content. Every condition is realistic — this is precisely the kind of suppression an agent under QA pressure is tempted to add.

**CONSUMER**: DENY reason naming the exact suppression(s) found, with language-specific remediation guidance and tool doc links.

**VACUITY**: Not vacuous — this is a textbook "an agent facing a failing lint/type check reaches for a suppression comment" scenario, and the handler exists specifically to close that loophole. 40 unit tests plus per-strategy acceptance tests aggregated across all 11 languages (`get_acceptance_tests`, `:245-255`).

**DUPLICATION**: This is DELIBERATE and DBF-consistent, not accidental: `qa_suppression` is the write-time guard; the QA suite's own linters (ruff, mypy, eslint, etc.) are what actually enforce the underlying rules the suppression would have silenced. The write-time block and the QA-time enforcement are two different mechanisms catching two different moments (writing the suppression vs. running the suite), which is exactly the DBF pattern CLAUDE.md's Core Standard 15 asks for — I did not find an explicit BATCH scanner for "suppression comments already on disk" (unlike `british_english`'s `check_british_english.py`), so if any suppression predates this handler or was added another way, nothing currently sweeps for it. Worth flagging as a potential DBF gap, though I did not find evidence of one having actually occurred (no incident in LESSONS.md/Plan search).

**CONFIG**: `enabled: true`, priority 30, default-enabled — `.claude/hooks-daemon.yaml:253-264`.

**COST**: Regex search per forbidden pattern per matched strategy — bounded by the number of patterns for one language, not all 11 (strategy is resolved by extension first).

**HISTORY**: 7 commits, oldest substantive `56dab785` "Add: Strategy Pattern for language-aware handlers (Plan 00045)" — this handler is one of the ORIGINAL Strategy Pattern exemplars referenced throughout CLAUDE.md's Engineering Principles section.

**FALSE-POSITIVE RECORD**: None found.

**SIGNAL: KEEP** — clean architecture, directly named as an exemplar in this project's own engineering principles, no incident history. Minor note for the judge: unlike `british_english`, no batch/sweep companion was found for pre-existing suppression comments — worth a quick check whether one is needed.

---

## task_tdd_advisor

**CLAIM**: Inject a RED/GREEN/REFACTOR TDD reminder when the `Task` tool is spawned with an implementation-shaped prompt (`implement`, `create...handler`, `write code`, `build`, `develop`, etc.) (`task_tdd_advisor.py:17-39`).

**MECHANISM**: `matches()`: Task tool, non-empty string prompt, regex hit on implementation keywords (`:54-73`). The keyword list is broad (`implement|create.*handler|write\s+code|add\s+feature|build|develop|code\s+up|write\s+handler`) — `build` and `develop` alone are common enough words that this will fire on a wide range of Task prompts, not narrowly on "write new production code" intent specifically (e.g. "build a summary of the findings" or "develop a plan for X" would plausibly match, per the regex as written, though I did not construct a live test to confirm).

**CONSUMER — the central finding**: Pure advisory context, ~30 lines of RED/GREEN/REFACTOR/VERIFY guidance (`:81-119`) referencing `@CLAUDE/CodeLifecycle/Features.md` and `@CLAUDE/PlanWorkflow.md` BY NAME. Both of those files are `@`-imported directly into this project's own `CLAUDE.md` (confirmed: I received their full text verbatim in this very session's system prompt, under "Contents of /workspace/CLAUDE/CodeLifecycle/Features.md" and "Contents of /workspace/CLAUDE/PlanWorkflow.md"). That means the ENTIRE substance of what this handler injects — RED phase, GREEN phase, REFACTOR phase, run QA, restart daemon, verify RUNNING — is **already fully resident in every session's context before this handler ever fires**, word-for-neighboring-word. This handler's `get_claude_md()` returns `None` (`:122-123`), so unlike most of the cohort, its own guidance is not even cross-referenced in the CLAUDE.md handler-summary section — it is a standalone, undocumented, ~30-line repeat of two files that are ALREADY fully inlined into context via CLAUDE.md's own `@`-imports.

**VACUITY**: Not vacuous in the sense of "can it match" (broad regex, will match plenty of realistic Task prompts) — 30 unit tests confirm this. But its INFORMATIONAL vacuity (does it tell the agent anything not already known) is the real question, and the evidence above suggests: no, not really, for any session where CLAUDE.md has already been loaded (i.e. every session).

**DUPLICATION**: The strongest documented case of category (i) from the audit brief — "already stated in CLAUDE.md and therefore resident anyway."

**CONFIG**: `enabled: true`, priority 36, default-enabled — `.claude/hooks-daemon.yaml:321-323`.

**COST**: One regex match per `Task` tool call with a non-empty prompt — cheap to compute, but the PAYLOAD is a large, static block of text injected into context on every implementation-shaped Task spawn, uncapped and unrated-limited, for information the model already has.

**HISTORY**: 7 commits, oldest `2644643e` "Feat: Add TaskTddAdvisorHandler for TDD workflow enforcement."

**FALSE-POSITIVE RECORD**: None found as an over-blocking incident (it never blocks — it's pure advisory), but that's exactly the category this audit is most worried about: an advisory handler that "fires on realistic input" is not the same as one that's earning its keep.

**SIGNAL: SUSPECT** — the clearest example in this cohort of advisory content that is very likely already fully resident via CLAUDE.md's own `@`-imports, undocumented in the handler-summary section itself (`get_claude_md() -> None`), broad enough to fire often, with no rate-limiting.

---

## tdd_enforcement

**CLAIM**: Block creation of a production source file until a corresponding test file exists in one of several valid locations, across 11 languages via Strategy Pattern (`tdd_enforcement.py:1-8`).

**MECHANISM**: Zero language-specific logic in the handler — delegates to `TddStrategyRegistry`. `matches()`: Write tool only, resolvable strategy, not `should_skip` (vendor/build/etc.), not itself a test file, and IS classified as production source by the strategy. `handle()` searches multiple candidate test-file locations (mirror, unit-style, fallback, collocated, `__tests__/`) before denying — genuinely permissive about WHERE the test lives, only insists that ONE exists somewhere plausible.

**CONSUMER**: DENY reason listing every searched location and the standard RED/GREEN/REFACTOR remediation.

**VACUITY**: Not vacuous — this is the literal mechanism enforcing the TDD workflow this entire project is built around (referenced constantly throughout CLAUDE.md, PlanWorkflow.md, CodeLifecycle/\*.md as MANDATORY). The multi-location search logic (5 distinct candidate-path strategies) is complex enough that I'd want to see it exercised against a real multi-convention codebase to be fully confident, but the test suite (via `tests/unit/handlers/test_tdd_enforcement.py`, confirmed present) plus per-language strategy tests give reasonable confidence.

**DUPLICATION**: This IS the write-time enforcement of a policy CLAUDE.md states in prose repeatedly (Planning Workflow, PlanWorkflow.md's TDD Integration section, CodeLifecycle/Features.md Phase 2). Unlike `task_tdd_advisor`, this handler does not merely REPEAT the policy in text — it actually BLOCKS the violating action, which is a materially different (and load-bearing) kind of enforcement, not text duplication.

**CONFIG**: `enabled: true`, priority 35, default-enabled — `.claude/hooks-daemon.yaml:281-299`.

**COST**: Multiple `Path.exists()` filesystem checks per candidate location (up to 5) on every Write to a production-source-shaped path — the second-most filesystem-I/O-heavy handler in the cohort after `markdown_organization`, but bounded and necessary (existence-checking is the whole point).

**HISTORY**: 17 commits, present since Initial commit — high commit count consistent with steady incremental refinement (collocated test support, monorepo-style path mapping, etc.) rather than a burst of false-positive firefighting; I did not find a specific over-blocking incident in the commits I sampled.

**FALSE-POSITIVE RECORD**: None found in LESSONS.md/Plan search.

**SIGNAL: KEEP** — this is core to the project's identity (TDD enforcement is one of the handful of things CLAUDE.md calls NON-NEGOTIABLE), sound Strategy Pattern design matching the project's own stated architecture principles, no incident history found.

---

## validate_instruction_content

**CLAIM**: Block ephemeral/session-specific content (implementation logs, status emoji + "Done", ISO timestamps, "## Summary" headings, test-output counts, changelog-style file listings, "N lines added", "ALL DONE!") from being written to `CLAUDE.md`/`README.md` (`validate_instruction_content.py:1-25`).

**MECHANISM**: 8 pattern categories, each a small list of regexes, checked against content with fenced code blocks stripped first. `matches()` is a simple filename-suffix check (case-insensitive `CLAUDE.MD`/`README.MD`, any directory) — realistically broad (matches vendored/nested README.md files too, which may be a minor over-scope, though the daemon's own `validate_instruction_content` presumably only cares about docs an agent is actively editing, not reading).

**CONSUMER**: DENY reason naming the specific blocked category, with the full list of blocked categories and the code-block exemption explained.

**VACUITY**: Realistic — the DENY test case content ("Created the file ProductService.php and added the class") is exactly the kind of narration an agent naturally writes when told "update CLAUDE.md," and this project's OWN CLAUDE.md (visible in this session's system prompt) explicitly forbids exactly this in prose ("`validate_instruction_content` — CLAUDE.md and README.md must have stable content"). 49 tests, including both a DENY case and a clean-content ALLOW case (near-miss coverage present, unlike some others in the cohort).

**DUPLICATION**: Overlaps conceptually with `comment_changelog` (both fight "history creeping into a document that should describe current state") but operates on a completely different surface (whole-file Markdown prose in two specific filenames vs. code comment spans in source files) — no functional overlap, just a shared philosophy, which the project states explicitly elsewhere (plan-doc-size, journal-append-only follow the same "current state vs. history" separation).

**CONFIG**: `enabled: true` (implied — this handler was NOT found with an explicit config block in my `.claude/hooks-daemon.yaml:240-407` excerpt, meaning it likely runs on its base-class default of `enabled=True`/`get_default_enabled()` unset — I did not locate an explicit `validate_instruction_content:` stanza in the config file at all, which the judge may want to verify directly since this differs from every other handler in the cohort, all of which had explicit stanzas).

**COST**: 8 pattern-category regex passes over content minus code blocks — one of the more regex-dense handlers per byte of content, but bounded to two specific filenames.

**HISTORY**: 8 commits, oldest `f29084f8` "feat: php-qa-ci integration - handlers enhanced" (an unusually generic commit message for this project's later convention).

**FALSE-POSITIVE RECORD**: None found in LESSONS.md/Plan search.

**SIGNAL: KEEP (config caveat)** — sound design, real self-referential need (this project's own CLAUDE.md discipline depends on it), good near-miss test coverage. Flagging for the judge: I could not confirm an explicit `enabled:` config stanza for this handler in `.claude/hooks-daemon.yaml`, unlike all 17 others in the cohort — worth a direct config lookup (`hooks-daemon-cli` or a targeted single-line grep) to confirm it's actually active rather than relying on the base-class default.

---

## web_search_year

**CLAIM**: Advise updating outdated years (2020 through current-year-minus-1) in `WebSearch` tool queries (`web_search_year.py:1-19`).

**MECHANISM**: `matches()`: WebSearch tool, non-empty query, word-boundary regex built dynamically from `range(2020, CURRENT_YEAR)` where `CURRENT_YEAR` is computed live via `datetime.now().year` (a `@property`, re-evaluated every call — correctly NOT hardcoded, so this handler cannot go stale the way a hardcoded "current year" constant would).

**CONSUMER**: Advisory context + guidance suggesting the current year or removing the year entirely for general topics.

**VACUITY**: Realistic — an agent (or the model's training-data habits) plausibly includes a stale year in a search query, and this is exactly the kind of thing training data can bias toward. The acceptance test itself is well-designed to stay correct over time (`'Python best practices 2024'`, checked against a dynamically-computed current year in the expected pattern).

**DUPLICATION**: None found.

**CONFIG**: `enabled: true`, priority 55, default-enabled — `.claude/hooks-daemon.yaml:397-399`.

**COST**: One dynamically-built regex compiled PER CALL (`_outdated_year_pattern()` rebuilds the `\b(?:...)\b` alternation from `_OLDEST_TRACKED_YEAR` to `CURRENT_YEAR` every time `matches()` runs, rather than caching it) — trivially cheap in absolute terms (a few dozen alternatives), but worth noting as the one handler in the cohort that recomputes a compiled pattern on every single match check instead of caching it at class/instance level, a minor inefficiency rather than a correctness issue.

**HISTORY**: 10 commits, present since Initial commit.

**FALSE-POSITIVE RECORD**: None found. Word-boundary anchoring is explicitly documented (`:46-49`) to avoid matching embedded digit runs like "20200" or "2021abc" — a specific, sensible precision detail.

**SIGNAL: KEEP** — small, correct, self-updating (no stale hardcoded year risk), one minor perf nit (uncached regex rebuild) not worth blocking on.

---

*End of dossier — evidence for 18 handlers. Cohort summary table is at the top of this document.*
