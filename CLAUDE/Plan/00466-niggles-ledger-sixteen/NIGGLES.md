# Niggles ledger sixteen: write-ups

Newest first. Each entry says how it was found, why it happens, and the
candidate remedies.

### N16 — `secret_file_guard`'s N4 splat exemption still false-positives against a BOTH-EDGES pattern

**Found by the 00466 review** (nit n2, `subagent-reports/260924-n466-review-opus-5-5.md`), out of scope for the N10/N11 fix turn. N4 fixed the Python unpacking splat false positive (`*words[position + 1 :]`, `*wordlist`) against `*.vault-password` — the ONE shipped pattern with a leading wildcard and NO trailing one. The same splat shape is still denied against `*vault_pass*`, which has a wildcard on BOTH edges: `f(*assets)`, `f(*ssh_args)`, `f(*passthrough)` and `f(*assertions)` are each denied live, because the N4 fix's `pattern_has_trailing_wildcard` escape only widens the gate for a pattern with NO trailing wildcard — `*vault_pass*` has one, so the gate's stricter requirement never applies and the pre-N4 overlap-only behaviour (which is what produces this false positive) is untouched. `*assets`/`*args`-style splats are common Python, so this is a live nuisance, not a rare shape.

**Candidate remedy:** the both-edges branch of `_glob_token_overlaps_stem` already has a stricter "near-total-match" discriminator (`_both_edges_residue_is_near_total_stem_match`) for exactly this over-promiscuity — a leading-wildcard-only token (no trailing wildcard of its own) matched against a both-edges pattern is presently routed through the SAME lenient overlap check as a genuine `*passXXX`-style truncation, rather than through that stricter discriminator. Route a token with no trailing wildcard of its own through the near-total-match test regardless of which edge(s) the PATTERN has open, and keep the existing near-total-match behaviour for tokens that themselves have a trailing wildcard too. RED tests: each `f(*assets)`-style splat against `*vault_pass*` is allowed; a genuine both-edges truncation (`*vault_pass*` reached via, e.g., `*zzz-passwd*`-shaped tokens) still denies.

### N24 — `daemon.strict_mode` never reaches the live daemon, so every guard fails OPEN on a handler exception

**Found by the guard-defects security review 2**
([report](subagent-reports/260924-n466-guards-review2-opus-5-5.md), M3), with a
live probe against this repository's own daemon. `.claude/hooks-daemon.yaml`
sets `strict_mode: true`. A Write payload that makes a handler raise
(`ValueError: no path specified`, the still-live N5 shape) came back as
`additionalContext: "Handler exception: ..."`: an ALLOW, not the strict-mode
`SYSTEM ERROR ... blocking for safety` deny.

`daemon/controller.py:959` reads `self._config.strict_mode if self._config else False`. The constructor's own comment (`:162-166`) says the `config`
parameter "is not populated by the real daemon startup path", and
`get_controller()` (`:1210`) builds `DaemonController()` with no config. So
`strict_mode` is inert in every install. Every SAFETY guard treats its own
crash as "no match". The per-guard wrapper that N11 adds to `secret_file_guard`
is the only thing between a crash and a bypass, and no other guard has one.
The N5 and N11 entries' claim that "this repository runs `strict_mode: true`,
so here the crash denied" is false.

**Candidate remedy (both halves):**

1. Plumb `config.daemon.strict_mode` into the controller's real startup path,
   through the same narrow-slice injection already used for `ChainConfig`.
   Test it through `get_controller()` and a real daemon start, not by
   constructing the controller with a config the daemon never passes.
2. Independently of `strict_mode`, the chain denies when a handler tagged
   SAFETY and BLOCKING raises, because a safety guard that crashes has not
   judged the call. That closes the class for every guard at once, including
   the review's m1 (`handle()` outside the fail-closed wrapper).

RED tests: a live-path daemon with `strict_mode: true` denies on a raising
handler; a SAFETY+BLOCKING handler that raises denies even with `strict_mode`
off; a non-safety advisory handler that raises still allows, and says so.

### N22 — `lsp_enforcement` takes another command's argument for a grep symbol lookup

**Found by the coordinator**, live. The command was `python scripts/qa/llm_qa.py format lint ... plan_qa docs_qa ... > out.txt; grep -E '^(✅|❌)|^QA:' out.txt`. It was denied with `BLOCKED [R-LSP-SYMBOL-LOOKUP]: ... pattern 'plan_qa' looks like a symbol search`. `plan_qa` is a positional argument to `llm_qa.py`, not to `grep`. The grep's real pattern, `^(✅|❌)|^QA:`, is not symbol-shaped at all. The handler found a `grep` somewhere in the command and then took a symbol-like word from elsewhere in it. `block_once` let the identical retry through, so the cost was one wasted turn. But every "run a QA tool, then grep its capture" command is the everyday shape here, and each one is a coin toss on which word gets picked.

**Candidate remedy:** tokenise the command into its separate simple commands (`;`, `&&`, `||`, `|`), and judge only the pattern argument of a `grep`/`rg` command, never a word belonging to a different command. RED test: the command above is allowed, and `python x.py foo; grep -rn 'def my_function' src/` is still caught on `my_function`. Once 00463/00464 land, this belongs on the shared shell lexer that the parser consolidation (coordinator queue) produces.

### N21 — the semgrep QA gate passes when a rule times out

**Found by the 00414/00415 agent.** Its first version of a new semgrep rule timed out on `daemon/cli.py`, and `scripts/qa/run_semgrep_check.sh` reported PASS. A rule that times out has checked nothing for that file, so the gate fails OPEN, and the slower and more complex a rule is, the more likely it is to be silently skipped on exactly the large files it exists for.

**Candidate remedy:** a timeout, or any semgrep error entry in its JSON output (`errors[]`), fails the gate and names the rule and file. RED test: a rule forced to time out on a fixture makes the gate exit non-zero with the rule named. Check the other QA wrappers for the same "tool error reads as clean" shape, and pin the class.

### N20 — the capture-corruption auditor judges a multi-line single-quoted string one line at a time

**Found by the B1 integration agent**, as the stated limit of its fix for the auditor's backslash-continuation false positive. `scripts/qa/audit_capture_corruption.py` now joins `\`-continued lines, but a single-quoted string that spans physical lines (`echo 'x` followed by `y' >&2`) is still judged per line. So the redirect on the second line is not seen, and the echo is flagged. Nothing in the repository has that shape today, so it is latent. The same false positive that broke B1's gate would come back the first time someone writes one.

**Candidate remedy:** carry the open-quote state across physical lines for single-quoted strings too, joining the logical line the same way continuations are joined. RED test: the two-line single-quoted echo with the redirect on the second line is not flagged, and one without the redirect is.

N16 is filed on the unmerged `worktree-n466-guard-defects` branch; it joins this file at integration.

### N19 — the registry's options-collection failure is logged at debug level

**Found by the N13/N14 agent.** The handler registry's pass-1 `except Exception` logs a failure to collect a handler's options at debug level only. During the N14 work, a local variable that shadowed the new accessor made the registry silently drop EVERY handler's options, and only an existing registry test caught it before commit. In production, that failure would have looked like every handler running on defaults, with nothing at a visible log level.

**Candidate remedy:** narrow the catch to the exceptions that option collection can legitimately raise, and log anything else at error level with the handler name. If a handler's configured options cannot be applied, that is a degraded protection state and should surface in `health`. RED test: an injected failure while collecting options is visible at error level and in health.

### N18 — PlanWorkflow.core.md says the plan index is linted against one rule

**Found by the N13/N14 agent.** `CLAUDE/core/PlanWorkflow.core.md:407` and its deployed template copy say the plan index is linted "against one rule". `index-no-log` already made that false, and N13 adds `plan-stats-arithmetic` to the commit gate. The page is a deployed template pair, so it ships to clients.

**Candidate remedy:** name the rules, or better, point at the plan QA rule list, which is the source of truth, instead of counting. Change both copies of the pair together, and pin it with a doc-truth test that the page names no count that disagrees with the registry.

### N17 — `skill_opportunity_detector` never receives its configured options

**Found by the N13/N14 agent.** `_options()` reads `self.config["options"]`, which only `configure()` populates. Nothing in `src/` calls `configure()`; the registry injects options as `_<key>` attributes instead. So a configured `check_interval_days` is ignored at runtime, and only the unit tests, which call `configure()` directly, exercise the option.

**Candidate remedy:** read options the way the registry delivers them, through the shared accessor. RED test: a handler built by the real registry from a config with a non-default `check_interval_days` uses it. Then audit every handler for a `configure()`-only options path, and pin the class with a test that instantiates each handler through the registry with a non-default value for every declared option and checks that it is honoured.

> > > > > > > main

### N15 — `remote-docs add` scans a capture with an unconfigured `sensitive_content` handler

**Found by the Plan 00468 docs agent.** `daemon/cli.py` (~:6377) builds `SensitiveContentHandler()` with none of its configured options for the capture-time `scan_text` in `remote-docs add`. So the scan at the moment a page is vendored runs with no public patterns at all. That is how 28 example UUIDs were vendored into `hooks.md` without a warning, to be caught only later by the tree-wide QA scan. The secret word list happens to be found only because the configured path equals the default. This is the same class as N14: a component reads a handler's behaviour without that handler's configured options.

**Candidate remedy:** construct the handler from the project's resolved config, through the same shared handler-options accessor N14 introduces. RED test: `remote-docs add` of a page carrying a configured public-pattern match reports it at capture time, and a non-default `secret_word_list_path` is honoured. Add the construct-without-config shape to N14's class audit.

### N14 — log and payload redaction ignore a configured secret word list path

**Found by the 00414/00415 agent**, outside its brief. `utils/secret_redaction.py` `_resolve_active_path` reads `handler_cfg.get("options", {})` only when `isinstance(handler_cfg, dict)`. But `Config` coerces every handler entry to a `HandlerConfig` model (`type(c.handlers.pre_tool_use.get("sensitive_content"))` is `HandlerConfig`), so the isinstance test is never true. The daemon-wide resolver therefore never reads a configured `secret_word_list_path`, and always falls back to the default `.claude/block-words.secret`. The `sensitive_content` handler reads its own option correctly, so blocking still works. But payload capture and log redaction silently use the wrong list, or no list, in any project whose word list lives somewhere else. That is exactly how a secret term reaches a log. This repository is unaffected only because its configured path equals the default. `secret_file_matching.resolve_configured_patterns` carries a comment about this same mistake and fixed its own copy, so this is the second sighting of the class.

**Candidate remedy:** read the option through `HandlerConfig.options`, via one shared accessor for handler options that accepts either shape. RED test: with a non-default `secret_word_list_path`, a term from that list is redacted from a captured payload and a log line. Then audit every `isinstance(<handler config>, dict)` read of handler config across `src/`, and pin the class with a test or QA check that fails when handler config is read as a dict.

### N13 — the plan-index statistics arithmetic is checked only by full QA, so a wrong count reaches main

**Found by the coordinator**, through Plan 00421's agent. Opening Plan 00468 updated the README statistics bullets (468 allocated, 455 distinct) but missed the closing self-check line (`454 + 13 = 467`). `check_repo_hygiene.py`'s `plan-stats-arithmetic` check catches exactly this. But it runs only in `llm_qa.py all`, and the commit-time plan QA gate that runs on every README commit does not include it. The inconsistent index was therefore committed and pushed (d10bbf13), and was found only when an agent ran the hygiene checker by hand. The same README gate already enforces row length and the 30-row completed window at commit time.

**Candidate remedy:** run the `plan-stats-arithmetic` check in the commit-time plan QA gate whenever the staged tree touches the plan index, or move the check into plan QA and have repo_hygiene call it. Either way there is one implementation. RED test: a commit staging a README whose statistics disagree with the self-check line is denied, and names the line to fix.

### N12 — a hand-built probe payload is logged as real traffic, because nothing tells a prober to mark it

**Found by the Plan 00467 plugin audit.** The audit fed synthetic PreToolUse payloads through `.claude/hooks/pre-tool-use` to probe handler verdicts. They carried no `synthetic_source` field, and their session ids (`plugin-audit-probe` and similar) match no known synthetic shape. So `daemon/synthetic_traffic.py` classed them as REAL traffic in `verdicts.jsonl`, including the orchestrator-simulate record that Plan 00418's enforcement decision will be read from. The marker (`SYNTHETIC_SOURCE_FIELD`, `synthetic_traffic.py:39`) is documented only in that module's docstring. CLAUDE/DEBUGGING_HOOKS.md, the handler-development guide and the agent-facing docs never mention it, so a prober cannot know to set it.

**Candidate remedy:** document the marker wherever probing a handler is taught (DEBUGGING_HOOKS.md, HANDLER_DEVELOPMENT.md, and the acceptance and playbook guidance), with a copy-paste payload that sets it. Consider a small `bin/hooks-daemon probe <event> <json>` helper that sets the marker itself. Add a test that the probing docs name the field.

### N11 — any exception in `secret_file_guard.matches()` lets the call through unless `strict_mode` is on

**Found by the 00466 review** (major M4, `subagent-reports/260924-n466-review-opus-5-5.md`). N5's crash was the second time an exception in this guard's `matches()` skipped the guard entirely; Plan 00357 was the first. Under the default `strict_mode: false` the chain logs the exception and allows the call. This entry originally claimed the repository's own `strict_mode: true` made the crash deny here, with only a client on the defaults failing open. **That is false — corrected by N24**: `daemon.strict_mode` is inert in every install, this one included, so the crash was a fail-open everywhere, not just on a client left on the default `false`. One raise path is still live after N5, though it isn't exploitable: a file path containing a NUL byte.

**Candidate remedy:** make the guard structurally fail closed. A raise anywhere in its match or route computation becomes a deny naming the internal error, whatever the global `strict_mode`, because a protected-read guard that fails open is worse than a false deny. Pin it with a test that injects an exception at each stage. Then audit the other security guards that should behave the same (`sensitive_content`, `project_containment`, the destructive-git rules) and decide each one explicitly.

**Remedy (implemented) — `secret_file_guard`:** the pattern-matching body of `_matched_pattern_and_route` was renamed to `_evaluate`; the public method is now a thin try/except wrapper that NEVER raises — any exception, from any stage of route or pattern computation, resolves to a new internal `_ERROR_ROUTE` naming the raised exception's type and message. `handle()` checks for that route first and denies through a new `_deny_for_evaluation_error` method with a dedicated `RuleID.SECRET_EVALUATION_ERROR`, added to `get_rules()`. Because the guard itself never raises, the chain's `strict_mode` branch (`core/chain.py`) is never reached for this failure mode at all — the guard's behaviour is now independent of that global setting, closing the class of bug N5 was one instance of (a raise anywhere in `matches()`/`handle()` used to fall through to `strict_mode`'s allow-on-default). Pinned with `TestFailsClosedOnEvaluationError` (6 tests), including the live NUL-byte path with no monkeypatch — a genuine crash, now caught. 82 tests pass.

**Audit — the three named sibling guards, each decided explicitly:**

- **`project_containment`: genuine gap found and fixed.** `_resolved_root()` calls `ProjectContext.project_root()`, which raises `RuntimeError` when uninitialised — an unguarded raise inside `matches()`/`handle()`'s pre-existing `_offending_targets()` call, and a SECOND independent call site inside `handle()`'s own deny-message construction (fixed by threading the resolved `root` through as a parameter instead of re-resolving it, so closing the first call site could not silently leave the second exposed). Given the identical treatment: `_offending_targets` now takes `root: Path` as a parameter; a new `_offending_targets_or_error` wrapper never raises; a new `RuleID.PROJECT_CONTAINMENT_EVALUATION_ERROR` rule and `_deny_for_evaluation_error` method mirror the shape above. Pinned with `TestFailsClosedOnEvaluationError` (3 tests). 96 tests pass.
- **`sensitive_content`: audited, no fix needed.** Already defensively coded throughout: `_relative_path_text` wraps `.resolve().relative_to()` in try/except `ValueError`, `_is_secret_list_itself` wraps its file check in try/except `OSError`/`ValueError`, `_compiled_public_pattern` wraps `re.compile` in try/except `re.error` (docstring: "never crashes"), and `get_active_secret_terms`/`find_first_match_index`/`term_matches` do plain literal substring matching via `re.escape`, never a raw regex over untrusted input. No raise path found.
- **`destructive_git`: audited, negligible risk, no fix needed.** Pure regex matching over the Bash command string (`get_bash_command` plus a compiled pattern's `.search()`) — no file I/O, no path resolution, no `ProjectContext` call anywhere in the handler. The one route a regex engine could raise through (a pattern rejecting its own input) applies only to a pattern this project itself compiles at import time, not to attacker-controlled input, so this is a design defect it would have shipped broken from day one, not a live fail-open risk worth hardening defensively.

### N10 — a wildcard in the middle of a protected filename gets past `secret_file_guard`

**Found by the 00466 review** as a pre-existing problem on main, security-relevant. `cat .vault-pas?word` and `cat prod.vault-passw*rd` name a protected file through a glob the shell expands, and the guard does not deny them. The mention scan handles a leading or trailing wildcard (the N4 overlap logic), but not a `?`, `*` or `[...]` inside the name.

**Candidate remedy:** treat any shell-glob token as a pattern, and deny when the pattern could match a protected name. Compare against the protected basenames and stems, or expand it against the directory when that exists. Keep it no looser than the N4 rule. RED tests: interior `?`, `*` and bracket globs of each shipped protected pattern are denied, while unrelated globs such as `*.py` and `src/*.md` are allowed.

**Remedy (implemented):** `secret_file_matching.py` gained `_globs_can_intersect(a, b)`, a real two-glob language-intersection test (standard sequence-alignment DP over `*`/`?`, O(len(a) · len(b))) — not another edge heuristic, because an interior wildcard has no edge for the existing leading/trailing overlap check to key on. A new `_interior_wildcard_mention` runs it for every token whose raw spelling carries glob syntax (`_is_glob_shaped(raw_form)`), over each of its bracket-expanded forms — so a finite bracket class (`.vault-pa[sz]word`) is covered too, even after expansion strips its wildcard-ness down to a plain literal, since the intersection test degenerates correctly to exact-match in that case. Scoped narrowly to keep N4 intact: only a token with NEITHER a leading NOR a trailing wildcard reaches it (an open-edge token is already handled by the pre-existing checks, N4/m1 fixes and all), and a pattern with wildcards on BOTH edges (`*.secret*`, `*vault_pass*`) is excluded — full intersection against a "contains this text anywhere" pattern is satisfiable by nearly any token carrying its own wildcard (`report-[0-9]*.txt` and `secret*.py` genuinely glob-intersect with `*.secret*`, live-verified as new false positives during implementation, neither is evidence of a protected file), the same over-promiscuity `_both_edges_residue_is_near_total_stem_match` already exists to guard against elsewhere in this module. RED tests (confirmed failing pre-fix, passing after) in `TestBashMentionsProtectedPath`: `test_interior_question_mark_truncation_is_matched`, `test_interior_star_with_unrelated_prefix_is_matched`, `test_interior_bracket_expression_truncation_is_matched`, plus `test_unrelated_interior_wildcard_tokens_are_not_matched` and `test_splat_false_positive_from_n4_still_allowed` pinning the N4 fix stays intact. Full `test_secret_file_matching.py` (203 tests) and `test_secret_file_guard.py` (82 tests) pass.

**Correction (M2, guard-defects review 2)**: this entry's acceptance criterion
("interior `?`, `*` and bracket globs of each shipped protected pattern are
denied") was not met for 2 of the 6 shipped patterns — `*.secret*` and
`*vault_pass*` (both-edges patterns, deliberately excluded from
`_interior_wildcard_mention` above) stayed fully open to every interior
spelling, an edge-plus-interior combination on any pattern escaped every
check, and an unenumerable bracket class (`[!x]`, `[^x]`, `[[:alpha:]]`, an
over-cap range) reached the DP with its brackets read as LITERAL characters
instead of a wildcard, so it failed OPEN rather than closed. Brace expansion
(`.vault-pas{s,}word`) was also uncovered for every pattern. Fixed on the
guard-defects-review-2 branch: the DP now runs for edge-open tokens too
(against every pattern that is not both-edges, gated by a new degenerate-
orientation check so a leading-wildcard token is never blindly tested
against a trailing-wildcard pattern — that combination is satisfiable by
ANY literal on either side, which is not evidence of anything); an
unexpanded bracket expression is substituted with `?` before the DP runs (a
safe superset); both-edges patterns get a filesystem-truth route instead
(`_both_edges_glob_mention`, gated by a cheap literal-overlap pre-filter so
it never pays for a real directory listing on an unrelated token); and
brace groups are expanded against the raw command text before tokenising,
the same conflict `enforce_llm_qa`'s own M1 fix resolves. Pinned with 4 new
test classes (16 tests) in `tests/unit/utils/test_secret_file_matching.py`.

### N9 — `docs_qa` judges gitignored markdown, so installing a Claude Code plugin fails local full QA

**Found by the coordinator** right after installing the Defence Before Fix plugin at project scope (Plan 00467). In this container Claude Code's config directory is `.claude/ccy/`, so the plugin's cache (`.claude/ccy/plugins/cache/...`) and marketplace clone (`.claude/ccy/plugins/marketplaces/...`) land inside the repository. Both are gitignored (`.claude/ccy/.gitignore:3: *`). `llm_qa.py docs_qa` then reported 12 `source-tree-markdown` findings, one per vendored spec file, and the tool FAILED. It reported 0 findings at batch A's gate, before the install. CI does not see this, because a fresh checkout has no `.claude/ccy/`. Every local full QA run, including the coordinator's integration gate, now fails on files that are not part of the project.

The docs corpus walks the filesystem without honouring `.gitignore` (`docs_qa/corpus.py`; it already special-cases `.claude/ccy/CLAUDE.md`, lines 149 and 421).

**Candidate remedy:** the corpus considers only tracked files plus untracked files that are NOT ignored, i.e. `git ls-files --cached --others --exclude-standard`, with a defined fallback outside a git repository. Keep any deliberate inclusion that is ignored but meant to be scanned explicit and named. RED test: a gitignored markdown file under a source-like directory produces no finding, and a tracked one still does. Audit the other QA corpora (plan_qa, doc_snippets, doc_truth, repo_hygiene, sensitive_content, british_english) for the same filesystem-walk assumption, and pin the class.

### N8 — ✅ Remedied — `reference_repo_freshness` says BLOCKED on a call it allows

**Found by the coordinator.** A Read of a fresh clone under `untracked/repos/` was denied (`R-REFERENCE-REPO-NOT-VERIFIED`), as the default `block_once` posture intends. The next command that named that clone, a `mv` moving it to `untracked/work/`, RAN. Its hook context still opened with `BLOCKED [R-REFERENCE-REPO-NOT-VERIFIED]: a read of a governed reference clone...`.

`_verdict()` (`handlers/pre_tool_use/reference_repo_freshness.py:575-576`) returns `GatingResult(decision=Decision.ALLOW, context=[message])` for a repeat in `block_once` mode, and for `advise` mode at :565. `message` is the verbose DENY rendering (`self._formatter.verbose(rule)`), which starts with `BLOCKED`. An agent reading its context is therefore told a call was blocked when it ran. It either retries something that already happened, or learns that "BLOCKED" means nothing.

**Remedy:** `RuleFormatter` gained a fourth rendering, `advisory(rule)` (`core/rule.py`) — same `rule_id` and the same `Rule.verbose` teaching content as `verbose()`, headed `ADVISORY` instead of `BLOCKED`, matching the "ADVISORY:" convention several handlers already use for their own hand-rolled non-blocking reports (no new format was invented). `reference_repo_freshness.handle()` now computes `_is_blocking(session_id, subject, mode)` — a preview of `_verdict()`'s own decision, pinned to it by `TestIsBlockingMatchesVerdict` — BEFORE building the message, and `_not_verified`/`_stale` select `verbose()` when the call will actually be denied and `advisory()` when it will not (an `advise`-mode result or a `block_once` repeat). `_verdict()` itself is unchanged; it stays the sole place that decides and records.

An AST-based static sweep of every handler for `Decision.ALLOW` built from `formatter.verbose`/`terse` content (directly or through an assignment chain) found exactly one other confirmed occurrence: `reference_repo_freshness` itself — the fix above. Two structurally similar but SAFE call sites surfaced for manual review (`lint_on_edit._run_lint_command`'s `language_name` parameter, `plan_qa_edit._advisory_result`'s `findings` parameter) and were confirmed not to carry deny-shaped content. `lsp_enforcement`, named by name as a suspect, was confirmed already correct: its `block_once` repeat and `advisory` mode both return a plain `dynamic_detail` string with no rule-id/BLOCKED prefix.

The class-wide guard lives at `tests/integration/test_allow_never_carries_deny_headline.py`: it drives every handler's own declared BLOCKING acceptance test twice against the SAME instance, replicating the history-recording step `DaemonController.dispatch()` performs after every route (`daemon/controller.py`) so a handler whose block-once state lives in the shared `HandlerHistory` data layer (not an in-instance dict, e.g. `lsp_enforcement`) genuinely sees its repeat call transition to ALLOW — and asserts the repeat's `reason`/`context` never contains the `"BLOCKED ["` signature. Confirmed RED against a deliberately reintroduced defect in `lsp_enforcement` (caught it), then GREEN once reverted. `reference_repo_freshness`'s own regression coverage lives in its unit tests (`TestBlockOnce`, `TestConfiguredModes`, `TestNotVerified`) instead, RED/GREEN-verified the same way — its only DENY acceptance test declares `harness_cannot_produce` (no fixture can build a real governed checkout), so the integration harness cannot reach it.

### N7 — the regenerated CLAUDE.md guidance block is not deterministic, so every daemon restart can commit a reorder

**Found by the coordinator** at the batch A merge. The integration worktree's daemon had just regenerated CLAUDE.md, and that result was committed. The main checkout's daemon then restarted on the same tree and auto-committed `ce31d6d8` ("Auto: hooks daemon regenerated CLAUDE.md handler guidance"). The commit changed 18 lines both ways. Every change is the same handler markers in a new order: `tool-disable-advisor`, `project-handler-load-checker`, `hook-registration-checker`, `routine-qa-sweep` and `secret-file-hygiene-checker` among them. The earlier 00462 merge restart committed `6359ad0c`, changing 83 lines both ways, with the same shape.

`ClaudeMdInjector._collect_tiers()` emits handlers in the order of `self._handlers` (`core/claude_md_injector.py:642`) and never sorts them. Two daemons on one tree can therefore produce different blocks, apparently for handlers that share a priority. The results:

- A spurious auto-commit on restart.
- A CLAUDE.md conflict whenever two branches merge. This happened twice while building batch A.
- A worktree's regenerated block that never matches main's.

**Candidate remedy:** emit in a total order that depends only on the handler set, for example tier, then priority, then handler name. Test that two injector runs over the same handlers in shuffled input order produce byte-identical blocks. Check whether `HOOKS-DAEMON.md` generation has the same tie problem, and give it the same fix.

### N6 — `enforce_llm_qa` denies a PROSE mention of `run_all.sh` inside an unrelated command's own argument

**Found by the coordinator**, live: a `CLAUDE/Plan/mkplan.bash --journal ... --title "..."` journal entry was denied by `enforce_llm_qa` (a project-handler; it has no rule ID), naming `run_all.sh`, even though the runner's name appeared only
inside the quoted `--title` prose, not as anything the command would execute.

**Cause** (`.claude/project-handlers/pre_tool_use/enforce_llm_qa.py`,
`_is_inspection_only` and its call site in `matches()`, pre-fix): the handler
split a command into top-level segments, then for any segment CONTAINING the
substring `run_all.sh` ANYWHERE, checked only the segment's OWN leading word
against an inspection/VCS allowlist (`cat`, `grep`, `git`, ...). A word
appearing inside a quoted argument to an unrelated command was invisible to
that check — the leading word of `CLAUDE/Plan/mkplan.bash --title "... run_all.sh ..."` is `mkplan.bash`, which is on no allowlist, so the whole segment was
treated as a potential invocation and denied. The same shape denied a `gh issue comment --body "... run_all.sh ..."` (a plain prose mention) and a
`bash scripts/qa/run_tests.sh; echo "see run_all.sh notes"` compound (a
DIFFERENT script's wrapper plus unrelated prose in the next segment).

**Remedy (implemented)**: replaced the substring-plus-allowlist check with a
`shlex`-based real-invocation detector (`_has_real_invocation` /
`_segment_executes_script`), reusing this project's already-established
`shlex.split()` + `try/except ValueError` tokenisation pattern
(`project_containment.py`'s `_tokenise`) rather than a third hand-rolled
parser. A segment matches only when the script is named at the command's own
HEAD, or as an argument to a wrapper — recursing into a wrapper's `-c`
subshell argument and into any `$(...)`/backtick substitution's inner text,
since bash runs both before the rest of the line. A prose word that merely
CONTAINS the script's name inside a longer shlex token (a whole quoted
`--title "..."` phrase is ONE token) is no longer conflated with a token that
IS the script's path.

**First cut (M1, found by the 00466 review) turned this ALLOW-by-default**:
gating on a fixed list of "wrapper" heads meant every OTHER real invocation
shape — `source`/`.`, `time`, a `VAR=1` prefix, `(subshell)`, `{ group; }`,
`!`, `if`/`for`, `nohup`/`sudo`/`command`/`setsid`/`stdbuf`, `... | xargs bash` — passed through unexamined; 16 such shapes that main correctly denied
were allowed on the branch. **Fixed by restoring deny-by-default**: a segment
is now denied whenever ANY shlex word — at any position, not just the head —
equals the script or ends in `/` + the script, UNLESS the segment's head is a
recognised data consumer (an inspection command such as `cat`/`grep`/`head`,
or `git`/`gh`) that could not execute it. Only the WORD SPLITTING changed
from the naive substring check: `shlex.shlex(..., punctuation_chars="(){}!")`
with `whitespace_split = True` so `(`, `)`, `{`, `!` split off a word with no
surrounding whitespace, and a leading `VAR=value` assignment is skipped when
finding the segment's head — so a quoted multi-word argument
(`--title "... run_all.sh ..."`) stays ONE word and is never mistaken for the
script's own path. The `_INSPECTION_COMMANDS`/`_VCS_COMMANDS` head allowlist
from before M1 stays in place under the new name `_DATA_CONSUMERS`.

One pre-existing acceptance-test fixture (`get_acceptance_tests()`, "Block
run_all.sh") turned out to be the SAME false-positive class in miniature: it
used `echo "./scripts/qa/run_all.sh"` as a "safe to execute" DENY case, which
only denied because `echo` happened to be absent from the old allowlist — a
prose mention, not an invocation. Replaced with `bash -n scripts/qa/run_all.sh`
(a genuine wrapper-invocation shape; `-n` keeps it parse-only and harmless if
the block ever regresses).

RED tests (confirmed failing pre-fix, passing after), added to
`.claude/project-handlers/pre_tool_use/test_enforce_llm_qa.py`:
`test_does_not_match_a_prose_mention_in_a_quoted_title_flag` (the exact live
shape) and `test_does_not_match_an_unrelated_wrapper_invocation`, plus (M1)
`test_still_matches_shell_prefix_and_process_control_forms`,
`test_still_matches_subshell_and_control_flow_forms`,
`test_still_matches_a_bare_path_piped_into_xargs_bash` covering all 16 of the
review's cases, and `test_does_not_match_further_prose_and_data_consumer_shapes`
pinning the prose-mention fix stays intact. A companion "must still deny"
regression guard was written alongside (already passing pre-fix, kept as a
pin): `cd ... && ./run_all.sh`, `sh -c './scripts/qa/run_all.sh'`, and a bare
`$(./run_all.sh)` substitution — `gh issue comment --body "... run_all.sh ..."` is NOT one of these: `gh` was already VCS-exempt on main (`_VCS_COMMANDS`,
now `_DATA_CONSUMERS`), so a `gh --body` prose mention was ALLOW before this
fix too, and `test_does_not_match_a_prose_mention_in_a_gh_body` was never RED.
All 45 tests in that file pass, and all project-handler tests pass
(`bin/hooks-daemon test-project-handlers --verbose`).

**Correction (M1, guard-defects review 2)**: this entry's "restoring
deny-by-default" and "Only the WORD SPLITTING changed" overstated the fix —
19 further regressions were still ALLOW on this branch where main denied: a
string-executor argument (`bash -c`/`eval`/`ssh`/`watch`/`su -c`/`timeout … sh -c`/`python -c`) where the script is not the LAST thing in the string, a
glued redirection with no whitespace before `<`/`>`, and a glob/brace word
that could expand to the script. Fixed on the guard-defects-review-2 branch:
string-executor arguments are re-parsed recursively (extended `-c`/`-lc`,
`eval`, `ssh <host>`, `watch`, `su -c`, `timeout … <shell> -c`, and a
substring test for `python* -c`), `_PUNCTUATION_CHARS` gained `<`/`>` so a
glued redirect splits into its own token, and a word that could glob- or
brace-expand to the script is now checked the same as an exact spelling.
Pinned with 8 new test methods covering all 19 regressions plus the M1
brace/glob cases, in `.claude/project-handlers/pre_tool_use/test_enforce_llm_qa.py`.

### N5 — SECURITY FAIL-OPEN: an empty path-mention token crashes `secret_file_guard.matches()`, skipping the whole guard for that write

**Found by 00463's agent** live, reported to the coordinator; reproduced here
via the daemon after the coordinator saved the exact triggering `tool_input`s
and replayed them for a full traceback. Three Edits to
`subagent_full_qa_blocker.py` (a WIP file inside a worktree) each drew
`Handler exception: ValueError: no path specified` as PreToolUse:Edit
context. The added content declared tuples of shell/Python path-expansion
operands, e.g. `_HOME_PREFIXES: Final[tuple[str, ...]] = ("~/", "$HOME/", "${HOME}/", "$PWD/", "${PWD}/")` and `_UNSEEN_CD_PREFIXES: Final[tuple[str, ...]] = ("$", "~", "` `")`.

**Cause**, traced through a live daemon log:
`chain.py:431 handler.matches (block-secret-file-read)` →
`secret_file_guard.py _matched_pattern_and_route` → `_script_content_mention`
→ `secret_file_matching.py find_protected_mention_detail` →
`iter_protected_mentions` → `_token_mention`: `path_matches_globs(form, ...)`
with `form == ""` → `path_exclusion.py _candidate_paths`:
`os.path.relpath(raw, root)` with `raw == ""` →
`ValueError: no path specified` (`os.path.relpath` rejects an empty PATH
argument outright, regardless of `start`).

The empty `form` came from `_normalised_token_forms`: for a token EQUAL to
one of `_HOME_PREFIXES` (e.g. the tokeniser isolates `"~/"` cleanly out of a
quoted Python string literal, since neither `~` nor `/` is a token
delimiter), `token[len(prefix):]` on a token exactly as long as the prefix is
`""`. That empty spelling then reached the glob matcher, which had never been
asked to answer for an empty path before.

**Severity — this is a fail-OPEN under the default config, not noise.** The
exception is raised inside `matches()`, not `handle()`. The daemon's
per-handler catch (`core/chain.py`) branches on `daemon.strict_mode`: under
the default `false` it logs the exception as context and moves on to the NEXT
handler, treating this one as "did not match", so a Write/Edit whose content
contains an empty-yielding token SKIPS `secret_file_guard` ENTIRELY for that
call — including any genuine protected-path mention elsewhere in the same
content. This entry originally claimed `.claude/hooks-daemon.yaml:8`'s
`strict_mode: true` made the crash a fail-CLOSED SYSTEM ERROR deny in THIS
repository, with the fail-open applying only to a client install left on the
default `false`. **That is false — corrected by N24.** `daemon.strict_mode`
never reaches the live daemon at all (`daemon/controller.py:959` reads a
`config` parameter the real startup path never populates), so the crash was
a fail-open here too, live-verified against this repository's own running
daemon. The trigger was a bare `~/` only — `$` is a tokeniser
delimiter (`_TOKEN_DELIMITERS`), so `"$PWD/"`/`"${PWD}/"` never reach the
prefix-stripping branch at all (they tokenise to `PWD/`/`{PWD}/`, neither of
which equals a configured prefix). Both surfaces were affected: the
Write/Edit content scan above, and the Bash command scan (`ls ~/ && cat <protected>` crashed the same way pre-fix).

**Remedy (implemented), both layers per the coordinator's instruction:**

(a) `_normalised_token_forms`
(`src/claude_code_hooks_daemon/utils/secret_file_matching.py`) never emits an
empty form: the home/pwd-prefix-stripping branch now requires
`len(token) > len(prefix)`, the same non-empty guard shape the adjacent
`./`-stripping branch already used.

(b) `_candidate_paths` (`src/claude_code_hooks_daemon/utils/path_exclusion.py`)
is now TOTAL on an empty `file_path`: it returns early with a single empty
candidate (matching nothing) rather than calling `os.path.relpath` at all —
defence in depth, so no OTHER caller of `path_matches_globs`/`is_path_excluded`
can hit the same crash by a different route.

(c) Fail-safe pinned with a RED test: content carrying BOTH a home-prefix
token and a genuine protected mention (`id_rsa`) elsewhere in the same blob
must still deny — confirmed failing (crashing) before the fix, passing
after. A corpus test iterates every operand shape from the live payloads
(alone, inside a quoted string, inside a call) asserting the mention scan
never raises.

RED tests: `tests/unit/utils/test_path_exclusion.py ::TestEmptyAndNoMatch::test_empty_file_path_with_a_project_root_does_not_raise`
and `tests/unit/utils/test_secret_file_matching.py ::TestBareHomePrefixTokenDoesNotCrash` (6 tests). Full
`test_secret_file_matching.py` (196), `test_path_exclusion.py` (55) and
`test_secret_file_guard.py` (76) pass — 327 total.

**Nit fixed (n1, 00466 review):** `_candidate_paths`'s docstring said an empty
`file_path` yields "an empty candidate list that matches nothing", but the
code returned `[""]` — a list holding one empty string, which DOES match
`*`/`**` (`fnmatch("", "*")` is True). Not a regression (main behaved the
same with no `project_root`), but worth aligning: it now returns `[]`, so the
code matches its own documented contract. RED test:
`test_empty_file_path_does_not_match_a_bare_wildcard`.

### N4 — `secret_file_guard`'s leading-wildcard overlap check denies an unrelated Python splat expression as `*.vault-password`

**Found by a peer agent** working in a worktree, reported to the coordinator;
reproduced independently here before fixing (per instruction, its account was
treated as a hypothesis, not a fact). An Edit adding the Python expression
`*words[position + 1 :]` (a plain unpacking of a slice, e.g. `rest = [words[0], *words[position + 1 :]]`) to a `.py` file was denied under
`R-SECRET-SCRIPT-AUTHOR`, naming the protected glob `*.vault-password`. The
same shape denies the equivalent Bash mention (`cat 'rest = [words[0], *words[position + 1 :]]'`) and, stripped of any bracket at all, a bare
`def f(*wordlist): pass` or `call(*wordlist)`.

**Cause** (`src/claude_code_hooks_daemon/utils/secret_file_matching.py`,
`_glob_token_overlaps_stem` and its call site in `_token_mention`): the
tokeniser splits `*words[position + 1 :]` on whitespace into `*words[position`,
`+`, `1` and `:]` (`_tokenise`'s delimiter set includes space but not `[`/`]`/
`:`/`+`). The first token starts with a literal `*` (Python's unpacking
operator, not a shell glob), so `_has_leading_wildcard` reports it as a
leading-wildcard token. Its literal residue, after stripping `*`/`[`, is
`wordsposition`. The leading-wildcard branch of `_glob_token_overlaps_stem`
then checks whether the STEM's suffix overlaps the residue's PREFIX
(`_suffix_prefix_overlap_length`) — and `.vault-password`'s last 4 characters
(`word`, from "pass-**word**") exactly equal `wordsposition`'s first 4
characters, clearing the 2-char minimum. The same coincidence reproduces
without any bracket: `*wordlist`'s residue `wordlist` shares the same 4-char
`word` overlap.

That overlap check was correct for the case it was built for — a token like
`*passXXX` against a BOTH-EDGES pattern (`*vault_pass*`), where the pattern's
own trailing wildcard can absorb whatever the token's residue doesn't cover
after the overlap. It was applied uniformly to every leading-wildcard pattern
though, including `*.vault-password` — the ONLY pattern in the shipped
defaults with a leading wildcard and NO trailing one. For such a pattern a
matching real filename must end EXACTLY at the stem (nothing can follow), so
a token with no trailing wildcard of its own (as `*words[position`/`*wordlist`
both are — the whole point of a leading-only token) can only be a genuine
truncation if its ENTIRE residue is a literal suffix of the stem, not merely a
short boundary coincidence. That stronger case was already covered by the
pre-existing substring+fnmatch check earlier in the same function (confirmed:
no test in the existing suite exercises a leading-only token against a
leading-only pattern needing the overlap branch specifically) — so the overlap
branch contributed nothing there but this false positive.

**Remedy** (implemented): `_glob_token_overlaps_stem` takes a new `pattern_has_trailing_wildcard` parameter; its leading-wildcard branch now also requires `pattern_has_trailing_wildcard or stem_basename.endswith(residue)` before counting the overlap as a mention. The call site passes `_has_trailing_wildcard(pattern)` — a function already used elsewhere in the same module for the token's own edges, reused here for the pattern's. This is parametrised on the pattern's own shape, not special-cased to `.vault-password`, so any future or project-configured leading-wildcard-only glob is covered the same way. RED tests (confirmed failing pre-fix, passing after): `TestBashMentionsProtectedPath::test_leading_wildcard_python_splat_operator_is_not_matched` (the reported shape plus the bracket-free forms) and a paired `..._full_suffix_of_anchored_stem_still_matched` regression guard proving a genuine truncation of an anchored pattern (`*password`, `*ult-password` against `*.vault-password`) still denies. Full `test_secret_file_matching.py` (190 tests) and `test_secret_file_guard.py` (76 tests) pass.

**Correction (m1, found by the 00466 review):** the `stem_basename.endswith(residue)` requirement above is only correct for the simple splat shape (`*identifier`, nothing else) — a token that carries ANOTHER wildcard besides its leading one (`*rd*rd`, project-configured `*on*.json`) is not that shape, since fnmatch expands the internal wildcard too and can still glob-match a protected name without its residue being a literal suffix of the stem at all (`*rd*rd` matches `rd.vault-password`). Applying the stricter requirement there silently dropped that detection. Fixed with a new `_has_wildcard_after_leading` predicate and a `token_has_wildcard_after_leading` parameter: the stricter requirement is now scoped to a token with NO wildcard after its leading one, restoring the pre-N4 overlap-only behaviour for genuinely multi-wildcard tokens. RED tests: `test_leading_wildcard_with_an_internal_wildcard_too_still_matched` (`*rd*rd`, `*word*word`) and `test_leading_wildcard_project_pattern_with_an_internal_wildcard_still_matched` (`*on*.json` against a project `*secret*.json` pattern). Full `test_secret_file_matching.py` (198 tests at the time) and `test_secret_file_guard.py` (82 tests) pass.

### N3 — `goal_injection` treats any edit of an In Progress plan as the plan starting

**Found by the coordinator**, live. The supervisor had set the goal to Plan
00461\. The coordinator then added a table row to this ledger's PLAN.md. That
edit drew `⚠️ GOAL DISPLACED: ... Plan(s) 00461 is now superseded by Plan 00466's goal`, and the handler wrote a goal-intent signal for 00466.

The handler's docstring says it writes the signal "when a plan flips to In
Progress". `handle()` never looks for a flip. It reads the PLAN.md from disk
after the write, and `_STATUS_IN_PROGRESS_RE` matches any plan whose
**Status** line reads In Progress. The once-per-plan-per-session latch is
the only limit. So the first Write or Edit in a session to any plan that is
already In Progress fires, however unrelated to its status. That includes a
ledger row, a task tick or a typo fix. The results:

- The supervisor receives a goal for a plan nobody started. For a rolling
  ledger that goal cannot complete.
- The displacement advisory tells the session that the goal it is really
  working was superseded.
- The ledger now tracks the edited plan as owed work, and the Stop hook
  challenges stops on its behalf.

**Candidate remedy:** fire only on a real transition. For `Edit`, the
`old_string` → `new_string` pair changes the **Status** line to In Progress.
For `Write`, the file's previous content (for example the pre-write copy
`write_clobber_guard` already reasons about, or git's `HEAD` version) did
not read In Progress, or the file is new. An edit that leaves an In
Progress status unchanged emits nothing and displaces nothing. RED tests:
an Edit that adds a table row to an In Progress plan emits no signal and no
advisory; an Edit flipping Not Started to In Progress still emits; a Write
creating a new In Progress plan still emits.

### N2 — `setup_worktree.sh` tells every agent to run the full suite through `run_all.sh`

**Found by the coordinator** when it set up an integration worktree.
`scripts/setup_worktree.sh` ends with an "Agent prompt template" whose last
line is `Run ./scripts/qa/run_all.sh before committing.`, and a "Run QA" hint
with the same command (lines 389 and 400). Step 7 also treats `run_all.sh` as
the QA entry point (line 343). Two things are wrong with that:

- `enforce_llm_qa` denies `run_all.sh`; `./scripts/qa/llm_qa.py all` is the
  only full-QA entry. An agent that follows the template is denied at once.
- Plan 00463 makes full QA a coordinator gate. A sub-agent runs targeted QA
  only, and the coordinator runs one full pass over the batch of merged
  branches. The template sends every sub-agent to run the full suite, which
  is the concurrent full QA that 00463 exists to stop.

**Candidate remedy:** the template names targeted QA (`llm_qa.py <tools>`
plus the touched tests) and says that full QA is the coordinator's
integration gate. The "Run QA" hint and Step 7 name `llm_qa.py`. A test
checks that the script names no denied QA entry point.

**Graduated to Plan 00463**, which owns the sub-agent QA policy.

### N1 — ✅ Remedied — `resolve_venv_python`'s fallback accepts a venv interpreter that cannot run on this host

**Found by Plan 00457's agent** (#55; recorded in 00457's JOURNAL as a
finding). When the slug-exact venv is absent, `resolve_venv_python` falls
back to globbing `untracked/venv-*/bin/python`, and accepts a candidate on
its executable bit alone. #55 is about a host whose only venv was built
inside a container. That interpreter may be for another architecture or
libc, or may symlink into a path that exists only in the container. It is
executable but cannot run. The fallback would then report "resolved", so
`bin/hooks-daemon` never reaches `_run_venv_free_verb` (the `repair` and
`signal` arms from Plans 00456 and 00457). It would fail when it runs the
interpreter, not with the clear venv-missing path. No test covers it on
either side of #53 or #55.

**Candidate remedies:**

1. The fallback proves a candidate RUNS, e.g.
   `"$candidate" -c 'import sys'` with a short bound, before accepting it.
   It moves on to the next candidate, then to the venv-free path, on
   failure. Test it with a fake executable that exits non-zero, and with a
   dangling symlink.
2. At minimum, a candidate that fails at exec time produces a message
   naming the venv it tried and the `repair` command, not a raw exec error.

**Remedy** (remedy 1, plus remedy 2's diagnostic): every implementation
that trusted a venv interpreter's executable bit alone now proves it RUNS
first.

- Bash: `scripts/lib/resolve_venv.sh::_rv_pick_python`'s two glob loops
  (`venv-*/bin/python`, `venv-*/bin/python3`) probe each candidate with a
  new `_rv_candidate_runs` helper (`"$candidate" -c 'import sys'`) before
  accepting it, falling through to the next candidate — and eventually to
  `bin/hooks-daemon`'s venv-free path — on failure. The bound is enforced
  by a watchdog subprocess (`( sleep N; kill -KILL "$pid" )  &` + a
  blocking `wait "$pid"`), not a `sleep`-poll loop: a poll loop always
  costs at least one full poll interval even for a candidate that exits
  in milliseconds, because the first check almost always lands before the
  process has exited. Measured on this repo's own real venv `bin/python`:
  ~1005ms/candidate under an earlier `sleep 1`-poll draft, ~15-40ms/candidate
  under the watchdog. `HOOKS_DAEMON_VENV_PROBE_TIMEOUT` overrides the
  5-second default bound (mirrors `Timeout.VALIDATION_CHECK`). Both glob
  loops now report which candidate they rejected and why on stderr before
  moving on, closing remedy 2 for the bash side.
- Python: `resolve_existing_venv_python_with_diagnostics`'s shared
  `_pick_interpreter` closure (used by steps 3, 4 and 5) and step 2's
  metadata `python_path` check now all route through a new
  `_venv_interpreter_runs` helper before accepting a candidate — the SAME
  `-c 'import sys'` probe, via `subprocess.run(..., timeout=5)`. Steps 3
  and 5 (single-candidate) and step 4 (scan) each report which candidate(s)
  were executable-but-unrunnable and name the `repair` command, closing
  remedy 2 there too. The "slug-exact" fingerprint-keyed venv (step 3) is
  probed too, not exempted — #55 already showed an exact-fingerprint match
  can be container-built and still unrunnable (e.g. a shared/NFS-mounted
  `untracked/`), and this resolver only runs on a bash-side resolver-cache
  MISS, so the extra spawn never lands on the per-hook hot path.
- `resolve_existing_venv_python` (the simpler, no-diagnostics function)
  deliberately stays un-probed: it is called fresh on every user turn by
  `daemon_upgrade_detector`, which only reads `.daemon-metadata.json` next
  to the returned path and never executes it, so probing there would add
  a real hot-path cost for no correctness gain.
  `client_validator.py::validate_daemon_can_start` — the other caller,
  which DOES execute the result — already ran its own
  `subprocess.run(..., timeout=Timeout.VALIDATION_CHECK)` probe before
  doing so, so it needed no change. Both are recorded in the sibling audit
  in the delivery report.
- `check_canonical_callers.sh` was already the sibling-audit backstop for
  the bash side: it denies any OTHER shell script that iterates
  `untracked/venv-*` directly, so `_rv_pick_python` is the only bash glob
  site that needed the fix.

TDD: RED tests confirmed failing against the pre-fix code first, in both
`tests/unit/daemon/test_paths_resolve_venv_diagnostics.py::TestRunnabilityProbe`
and the new `tests/integration/test_resolve_venv_runnability_probe.py`,
covering a fake executable that exits non-zero, a dangling symlink, a
hanging candidate (bound respected), fall-through to a good second
candidate, all-candidates-bad reaching the venv-free path, and the
slug-exact venv unaffected when it genuinely works.

**Follow-up defect, fixed at integration (766677c1).** The B1 full gate
failed `tests/acceptance/test_v391_field_regression.py`. That test runs the
resolver with a PATH holding only a broken `python3`. The watchdog ran
`sleep` from PATH, so with no `sleep` it went straight to `kill -KILL`. A
working venv was then rejected as "timed out after 5s", which is the v3.9.1
field case this resolver exists to survive. The branch's targeted QA had
not run that acceptance test. `_rv_wait_secs` now uses `sleep` when PATH
has one. Otherwise it waits on `read -t` against a read-write
process-substitution pipe, which needs no PATH lookup, and the kill runs
only if the full bound elapsed. Two regression tests cover a PATH with no
`sleep`: a good candidate still resolves, and a hanging one is still
bounded.

**✅ Remedied** on main (B1, 2e6483a3).
