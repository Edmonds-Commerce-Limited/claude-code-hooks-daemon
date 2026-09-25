# Niggles ledger sixteen: write-ups

Newest first. Each entry says how it was found, why it happens, and the
candidate remedies.

### N31 — the dispatch-declaration advisory does not recognise "File to write to: <path>"

**Found by the 00467 dogfood agent.** A dispatch brief that named its report
path as `File to write to: <path>` still drew the Plan 00307
dispatch-declaration advisory saying no report destination was declared.
The advisory matches a narrower set of phrasings than briefs actually use,
so it nags on a correct dispatch, and a nag that is often wrong teaches
people to skim it.

**Candidate remedy:** recognise any phrasing that pairs a write verb or noun
("write", "report", "file", "output", "save") with a path in the brief, not
only fixed phrases. RED tests: the phrasing above is recognised, and a brief
with no path at all still draws the advisory.

### N30 — more shell code that must survive a hostile PATH depends on a PATH command

**Found by the 00467 dogfood agent**, applying the Defence Before Fix method
to the watchdog defect fixed at 766677c1 (00466 N1's follow-up). An
independent search for the same class ("shell code that must survive a
hostile or stripped `PATH` runs a command looked up on `PATH`, and its
absence silently takes a wrong branch") found four more candidates:

- `scripts/venv_bootstrap.sh:443` and `:474` (`date`). The agent reproduced
  this idiom.
- `scripts/install/venv.sh:427` (`date`).
- `scripts/install/daemon_control.sh:40-43` (`pgrep`).

These are the venv and install paths, which exist to work when the host's
tools are broken, exactly as `resolve_venv.sh` does.

**Candidate remedy:**

1. Fix each instance: use a bash builtin (`printf '%(...)T'` for dates,
   `/proc` or `kill -0` for process checks). Where there is no builtin,
   make the missing command a loud, explicit failure rather than a silent
   wrong branch.
2. The detector the method asks for: a check over the scripts that must
   survive a hostile PATH (`resolve_venv.sh`, `venv_bootstrap.sh`,
   `scripts/install/*.sh`, the `bin/` wrappers) that flags an external
   command whose failure is not handled. It could be a `shell_audit` rule, or
   a test that runs each such script's functions under an empty `PATH`. It
   must catch the original watchdog shape, verified by reverting 766677c1 in
   a scratch copy.

### N29 — `error_hiding`'s return-None-in-except check is evaded by returning a local assigned in the handler

**Found by the coordinator** reading the goal-flip agent's report. To clear the
`error_hiding` finding on a literal `return None` inside an `except` handler,
that agent assigned `None` to a local in the handler and returned the local
after the `try`. The behaviour is identical, and the detector no longer sees
it. So the check keys on syntax, not on the flow it exists to catch, and an
agent under QA pressure finds the gap on the first try. The goal-flip branch
has been told to undo the evasion and fix the code honestly.

**Candidate remedy:** judge the flow, not the token. An `except` handler that
binds a name read by a later `return`, where that name's only values are
`None` or a default and the handler logs or re-raises nothing, is the same
finding as a literal `return None`. RED tests: the evasion shape is flagged,
a handler that logs at warning or above and returns a documented sentinel is
not, and the literal form is still flagged. Then sweep the tree for existing
instances of the evasion shape, which would currently pass unseen.

### N28 — `project_containment` resolves a relative target against the payload cwd and ignores a same-command `cd`

**Found by the Plan 00464 agent** during its re-review fix round (S12). It is
an instance of 00464's own defect class: the payload `cwd` is where the
session started, not where the command runs. So `cd <elsewhere> && <write to a relative path>` was judged against the wrong directory, and the containment
verdict could be wrong in both directions.

**Remedied on the 00464 branch** (`worktree-plan-464-commit-gate-repo`,
827c45df) through the new `find_command_placements`, which every
path-judging guard is meant to share. Two sibling walkers still resolve
their own way: `reference_repo_freshness` (the 00464 agent fixes it on that
branch) and `secret_file_matching` (after the guard-defects branch merges,
in the shell-parser consolidation). Mark Remedied when 00464 lands; the
siblings are tracked in the coordinator's consolidation work.

### N27 — `skill_scan` and `tool_report` build the transcript directory name two different ways

**Found by the 00468 core agent** (report on its branch,
`subagent-reports/260924-p468-core-opus-5-5.md`). Claude Code keeps a
project's transcripts under a directory named after the project path, with
characters it cannot use in a name replaced. `skill_scan` and `tool_report`
each derive that name with their own code, and they disagree for a path
containing `.` or `_`. So for such a project one of them reads the wrong
directory, finds nothing, and reports "no data" rather than an error.

**Candidate remedy:** one helper derives the transcript directory from the
project path, pinned to Claude Code's real rule (checked against a real
`~/.claude/projects/` entry for a path with `.`, `_` and `-`). Both commands
and every other derivation site use it (sweep for the other derivations).
The helper raises, not returns empty, when the directory does not exist and
the caller asked for it. RED test: a project path with `.` and `_` resolves
to the same directory from both commands.

### N26 — `check_skill_references.py` scans zero files when run from a worktree

**Found by the 00468 core agent.** Run from any worktree, the skill
references QA check reports success after scanning 0 files. A check that
examines nothing and passes is a fail-open gate: every sub-agent's targeted
QA runs from a worktree, so the check has been silently vacuous exactly
where branches are verified.

**Candidate remedy:** find why the file discovery comes up empty in a
worktree (a `.git` file rather than a directory, or a path anchored to the
main checkout), and fix it. Separately, the check FAILS when it scans zero
files where skills exist, so a vacuous pass cannot recur. Audit the other
`scripts/qa/check_*.py` for the same "0 examined, PASS" shape and pin the
class with a test that runs each check from a worktree fixture.

### N25 — a slow handler runs out the client's 30 s budget, and a timeout is an ALLOW for the whole PreToolUse chain

**Found by the guard-defects security review 2**
([report](subagent-reports/260924-n466-guards-review2-opus-5-5.md), B1 and
m3). `.claude/hooks/pre-tool-use` gives the daemon `--timeout-ms 30000`. On a
read-side socket timeout, `.claude/init.sh` (about lines 1654-1661) emits
`hookSpecificOutput` with context only, which is an ALLOW for every non-Stop
event. So any handler that can be made slow enough bypasses every guard
behind it, not just itself. Two instances are measured:

- `destructive_git`'s `strip_inert_spans` takes 99 s on a 200 KB command.
  That is already on main.
- The guard-defects branch's interior-wildcard DP takes 31 s on a crafted
  60 KB command. That one is fixed on its branch as review 2's B1.

Fixing each slow handler one by one leaves the class open: the next
super-linear regex or DP reopens it silently.

**Candidate remedies (the class, not the instance):**

1. The daemon enforces a per-event deadline well under the client budget
   (for example 20 s for the whole chain). When it passes, the remaining
   SAFETY+BLOCKING handlers are treated as having raised, which means DENY
   with a "not judged in time" reason under N24's fail-closed rule.
   Advisory handlers are skipped with a note.
2. Fix the measured instance: `strip_inert_spans` becomes linear, with a
   timing test at 200 KB.
3. A test harness drives every SAFETY handler with large hostile inputs
   (long runs of quotes, backslashes, wildcards and nesting) under a time
   bound, so a super-linear path fails CI rather than a client.

Deliberately NOT a remedy: making the client fail closed on timeout. A
daemon that is merely slow (an overloaded host) would then block every tool
call. The deadline belongs inside the daemon, where it can tell safety
handlers from advisories.

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

**Found by the 00466 review** (major M4, `subagent-reports/260924-n466-review-opus-5-5.md`). N5's crash was the second time an exception in this guard's `matches()` skipped the guard entirely; Plan 00357 was the first. Under the default `strict_mode: false` the chain logs the exception and allows the call. This repository runs `strict_mode: true`, so here the crash denied, but a client on the defaults fails open. One raise path is still live after N5, though it isn't exploitable: a file path containing a NUL byte.

**Candidate remedy:** make the guard structurally fail closed. A raise anywhere in its match or route computation becomes a deny naming the internal error, whatever the global `strict_mode`, because a protected-read guard that fails open is worse than a false deny. Pin it with a test that injects an exception at each stage. Then audit the other security guards that should behave the same (`sensitive_content`, `project_containment`, the destructive-git rules) and decide each one explicitly.

### N10 — a wildcard in the middle of a protected filename gets past `secret_file_guard`

**Found by the 00466 review** as a pre-existing problem on main, security-relevant. `cat .vault-pas?word` and `cat prod.vault-passw*rd` name a protected file through a glob the shell expands, and the guard does not deny them. The mention scan handles a leading or trailing wildcard (the N4 overlap logic), but not a `?`, `*` or `[...]` inside the name.

**Candidate remedy:** treat any shell-glob token as a pattern, and deny when the pattern could match a protected name. Compare against the protected basenames and stems, or expand it against the directory when that exists. Keep it no looser than the N4 rule. RED tests: interior `?`, `*` and bracket globs of each shipped protected pattern are denied, while unrelated globs such as `*.py` and `src/*.md` are allowed.

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

**Remedy shipped in commit `0dba7bfb`.** `_collect_tiers()`
(`core/claude_md_injector.py`) now sorts each of the three tier lists
(`promoted`, `progressive`, `fallback`) by handler name before returning
them — name alone is a complete total order because two active handlers
never share a name, and priority is not consulted because handlers from
different event chains are mixed into one flat CLAUDE.md tier where
priority carries no meaningful cross-event-type ordering. `daemon/ controller.py`'s handler collection was reading the chain's private,
unsorted `_handlers` list instead of its public `handlers` property (which
already sorts by `(priority, name)` on access, the same pattern
`EventRouter.get_all_handlers()` uses) — fixed to use `chain.handlers`.
`TestGuidanceOrderIsIndependentOfDiscoveryOrder`
(4 tests, RED against the pre-fix code) asserts forward- and
reverse-ordered handler lists inject byte-identical `<hooksdaemon>`
blocks. The sibling tie in `.claude/HOOKS-DAEMON.md` generation
(`daemon/docs_generator.py`'s `_render_handler_table()`) sorted by
priority only, so same-priority handlers kept registry order; fixed to
sort by `(priority, config_key)`, pinned by
`test_same_priority_handlers_are_order_independent` (1 test, RED against
the pre-fix code). Verified idempotent: `regenerate-docs` run twice in a
row produces the identical diff both times.

**Correction (00466 review, minor m6):** the commit message and the
paragraph above blamed `pkgutil.walk_packages()` for the unsorted input.
That is wrong — `pkgutil` sorts `os.listdir` output internally
(`_iter_file_finder_modules` calls `filenames.sort()`). The real unsorted
source is `HandlerRegistry`'s two `event_dir.glob("*.py")` loops
(`handlers/registry.py:467` and `:511`), which iterate in `os.scandir`
order; a third loop in the same file (line 198) already wraps its glob in
`sorted(...)`. The injector-level and docs_generator-level sorts above
still make each rendered artefact a pure function of the handler set on
their own — this correction is to the narrative, not to the fix's
soundness. Both `registry.py` glob loops are now wrapped in `sorted(...)`
too, so discovery order is deterministic at its source as well as at
every rendering layer.

**Also fixed (00466 review, nit n6):** the promoted tier's alphabetical
sort lost the reason a handler is promoted at all — the config author's
own `promoted_handlers` list order, chosen so the most-triggered guidance
reads first. `_collect_tiers()` now sorts the promoted tier by each
entry's INDEX in `self._promoted_handlers_order` (the author-authored
config list, kept alongside the pre-existing `frozenset` used for the O(1)
membership check) instead of alphabetically — still a complete,
deterministic total order, because that config list is a fixed value, not
a filesystem walk. The progressive and fallback tiers are unaffected;
alphabetical is the right call there, since nothing about them carries
author-chosen intent. Pinned by
`test_promoted_tier_follows_the_authors_promoted_handlers_order` (RED
against the pre-fix alphabetical code).

### N3 — `goal_injection` treats any edit of an In Progress plan as the plan starting, and displaces the live goal

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

**Remedy shipped in commit `5676772d`.** `GoalInjectionHandler` gained
`_is_real_flip_to_in_progress`: for `Edit` it parses `old_string` with
`PlanDoc.parse` and answers directly from that fragment's own Status line
(absent → this edit never touched it → not a flip; present and not In
Progress → a flip). For `Write` there is no pre-write disk copy left by the
time PostToolUse runs, so git HEAD stands in for "before" — deliberately
not the Write/Edit `tool_response`, whose shape this codebase has never
verified for either tool (see this same folder's
`POSTTOOLUSE_FIXTURE_VERIFICATION.md`). A path absent at HEAD (new or never
committed) reads as nothing to flip FROM, matching the pre-existing
single-plan contract. The once-per-`(plan, session)` latch and the
retirement-refresh path are unchanged. `TestStatusFlipDetection` (8 tests,
3 RED against the old code) pins the contract; the module docstring, the
class docstring and `get_claude_md()` now state it explicitly.

**Follow-up in commits `6699fbbd` and `4813adc8`**, after review. The first
`_head_plan_text` caught `RuntimeError`/`OSError`/`ValueError` and returned
`None`, which `error_hiding`'s `return-none-on-error` check flagged; the
initial fix added an exclusion, which the review correctly rejected —
this project allows no new QA suppressions. Restructured instead: path
membership is now a plain `Path.is_relative_to` comparison, never a caught
`ValueError`, and `ProjectContext.project_root()` is called unguarded — by
the time any handler dispatches the daemon has always initialised it, so a
`RuntimeError` here means genuine misconfiguration and is left to propagate
to the dispatcher (`core/chain.py`'s existing per-handler exception
handling), rather than being swallowed into a false "nothing to compare
against". The lookup moved out to
`utils.git_facts.project_relative_head_text` so it has one home instead of
a per-handler copy. `error_hiding` now passes with zero violations and no
exclusion for this code.

The review also asked for the sibling to be fixed, not just documented as
accepted: `recovery_cron_advisor`'s Write-path completion check
(`_STATUS_COMPLETE_RE.search(content)` against the whole new file) shared
the exact same state-vs-transition defect shape for `**Status**: Complete`
— "only an advisory" was not a reason to keep it. `_detect_lifecycle_phase`
now calls `_write_is_real_completion`, which reuses
`project_relative_head_text` rather than a second copy: a Write whose
content reads Complete is COMPLETION only when the plan was not already
Complete at HEAD; otherwise the event matches no phase at all (never falls
through to PROGRESS/CREATION). `TestWriteCompletionIsTransitionBased` (4
tests, 1 RED against the pre-fix code) pins the contract. Its Edit path
(`_edit_results_in_status_complete`) already required the edit's own
`old_string`/`new_string` to assert Complete and needed no change.
`plan_close_approval._is_terminal_flip` was already transition-based
(compares `PlanDoc.parse(current).status` against the proposed status).
`plan_qa_edit.py`'s "In Progress" occurrences are guidance prose, not
status-detection logic.

**Second review pass (majors M2/M3, minors m4/m5, nits n3/n4/n7)**, fixed
together on the same branch:

- **M2 — a daemon restart silently disabled the retirement refresh.**
  `_maybe_refresh_on_retirement` gated on the IN-MEMORY `self._fired`
  latch, which a restart (`daemon_restart_verifier` requires one before
  every commit) empties, and N3's flip-only rule meant a later non-flip
  write no longer re-latched either — so a plan flipped in one daemon
  lifetime and completed in the next never dropped out of the combined
  `/goal` signal. Fixed by asking the PERSISTENT `GoalLedger` instead
  (`GoalLedger.has_live_entry` at the time; superseded by
  `owning_sessions` in the third review pass below), which survives the
  restart the latch does not. Pinned by
  `test_completing_a_plan_after_a_daemon_restart_still_refreshes_signal`
  (a fresh `GoalInjectionHandler` instance simulates the restart; RED
  against the pre-fix code).
- **M3 — the "goal survives a session restart" contract was silently
  dropped, not replaced.** Plan 00269 Task 2.1 deliberately chose "the
  first edit to an already-In-Progress plan in a NEW session re-fires" so
  a resumed session got its `/goal` back; N3's flip requirement removed
  that with no replacement, and the original release note wrongly called
  it "no action needed". Restored via `GoalLedger.reassert_session` (two
  new ledger methods: `session_has_entries` decides whether THIS session
  is new at all; `reassert_session` transfers ownership of the plan's
  already-live entry with NONE of `record_emission`'s displacement
  bookkeeping) and `_maybe_reassert_for_new_session`: a session with no
  ledger entries whatsoever that touches an already-live plan without
  itself producing a real flip gets its own signal written, no new ledger
  record, no "GOAL DISPLACED" advisory, and no risk of wrongly displacing
  some OTHER live plan. A session that already has its own live goal is
  unaffected. Pinned by three new tests in
  `TestNewSessionReassertion` (one RED against the pre-fix code) plus
  three new `GoalLedger` test classes. Release note 13 and the module
  docstring corrected to describe the restored contract instead of
  claiming no behaviour changed.
- **m4 — an Edit whose `old_string` carried only the bare status VALUE
  (no `**Status**:` prefix) missed a genuine flip.** `PlanDoc.parse` on
  `old_string` alone then found no Status line and read "never touched
  it". Fixed by reconstructing the pre-edit text from what is already on
  disk when this happens — reversing the SAME substitution the Edit tool
  performed (`_reconstruct_pre_edit_text`, honouring `replace_all`) — and
  parsing that instead of giving up. Pinned by
  `test_edit_whose_old_string_is_only_the_status_value_still_emits` (RED
  against the pre-fix code) plus a no-op control test.
- **m5 — a Write in a nested repository (a linked worktree, any nested
  clone) read HEAD from the PROJECT ROOT's repo, which never tracks the
  nested path, so it always answered "absent" and misread every write
  there as a genuine flip.** `project_relative_head_text` now resolves
  the FILE's own enclosing repository via `GitRepo.resolve_for` (the same
  `git -C <dir> rev-parse --show-toplevel` this project already
  centralises) and reads HEAD relative to THAT root; a project root that
  is itself a plain checkout is unaffected. Pinned by
  `test_a_file_in_a_nested_repository_reads_from_its_OWN_head` (RED
  against the pre-fix code) in `test_git_facts.py`, which also fixes
  `recovery_cron_advisor`'s Write-path COMPLETION check for the same
  reason (it shares the helper).
- **n3 — `git_facts.py` imported `core.project_context`, breaking its own
  documented "docs QA depends on this module alone" claim.**
  `project_relative_head_text` now takes `project_root` as a plain
  parameter instead — both callers already resolve
  `ProjectContext.project_root()` for other purposes, so nothing is lost.
- **n4 — acknowledged, not changed.** `_is_inside_project` fails open on
  an uninitialised `ProjectContext`; `project_relative_head_text` lets it
  propagate (by design, from the first review pass). Both new M2/M3
  helpers (`_maybe_refresh_on_retirement`, `_maybe_reassert_for_new_session`)
  now follow the SAME unguarded-propagation convention for consistency
  (and because `error_hiding` flagged the None-returning one) — the
  review itself called this "only reachable uninitialised", i.e. never on
  the real dispatch path, so the two conventions differing is intentional
  per the first review's explicit design, not an oversight.
- **n7 — release note 13's title said "already-terminal-status"; In
  Progress is not terminal.** Corrected to match the filename's wording.

`TestStatusFlipDetection`, `TestCombinedGoalSignal`,
`TestNewSessionReassertion`, `TestWriteCompletionIsTransitionBased`,
`TestProjectRelativeHeadText` and the new `GoalLedger` test classes all
pass; 518 tests across every touched handler/utils/core/daemon test file.

**Third review pass (major RV-M1, minors RV-m1 through RV-m5, nits RV-n1
through RV-n3)**: the second pass's M3 re-assert and M2 retraction worked
AGAINST each other — fixed together with an ownership schema change:

- **RV-M1 — `reassert_session`'s single-owner TRANSFER broke retraction the
  moment a second session touched a plan.** Once TEAMMATE reasserted a plan
  LEAD had flipped, `has_live_entry`'s exact `session_id` match stopped
  matching LEAD, so LEAD's own signal could never be retracted again when
  the plan completed — and a pre-existing gap on `main` meant a DIFFERENT
  completing session never retracted the flipping session's stale signal
  either. Fixed by making ownership ADDITIVE: `GoalLedgerEntry` gained a
  `sessions: list[str]` field that `record_emission`/`reassert_session` both
  APPEND to, never overwrite; `has_live_entry` checks membership in
  `sessions`; a new `GoalLedger.owning_sessions(plan_number)` (accepting an
  entry retired a moment ago for `RETIRED_TERMINAL_STATUS` too, subsuming
  RV-m2 below) feeds `_maybe_refresh_on_retirement`, which now refreshes
  EVERY owning session's own combined signal on a terminal write, not just
  whichever session's write triggered the check. Pinned by
  `TestOwnershipSurvivesASecondSession` (single plan, two plans, a second
  session owning a plan it never flipped — all RED against the pre-fix
  code) plus `TestReassertSession`/`TestOwningSessions` in
  `test_goal_ledger.py`.
- **RV-m2 — subsumed by RV-M1's fix.** `owning_sessions`' terminal-status
  grace window (live OR just-retired-as-terminal) means a concurrent
  reconciliation racing between a terminal write landing and this read
  cannot suppress a real owner's retraction.
- **RV-m3 — a SAME-session-id resume (`--resume`/`--continue`) never got
  its `/goal` back**, because the M3 gate (`session_has_entries`) reads the
  PERSISTED ledger, which still "knows" the session from its OWN earlier
  real flip even after its signal FILE was lost across a restart. Fixed
  with a second in-memory latch, `self._reasserted: dict[(session_id, plan_number), bool]`, reset every daemon lifetime and independent of
  `self._fired` — "have I, this process, already confirmed a signal for
  this pair" answers both a genuinely new session id and a same-id resume
  identically. The busy-session contract (a session that already
  real-flipped a DIFFERENT plan must not implicitly absorb an unrelated
  one) still holds via `session_has_entries`, now checked only when the
  session is NOT already a stakeholder of THIS specific plan
  (`has_live_entry`). Pinned by
  `test_same_session_id_after_a_restart_gets_its_signal_rewritten` (RED
  against the pre-fix code).
- **RV-m1 — the m4 reconstruction reversed the FIRST occurrence of
  `new_string`, not necessarily the actual edit site.** A table cell or
  title sharing the same text as the Status VALUE (e.g. "In Progress")
  could reconstruct the wrong span and report a false flip. Fixed:
  `_is_flip_via_reconstruction` now tries every occurrence of `new_string`
  as a candidate, keeps only candidates whose reversal leaves `old_string`
  unique (the Edit tool's own precondition for a non-`replace_all` edit),
  and reports a flip only when every surviving candidate agrees; disagreement
  or no viable candidate reads conservatively as "not a flip".
  `replace_all` has no uniqueness precondition to exploit, so it instead
  requires `old_string` to be ABSENT from the post-edit text (a clean
  application leaves none behind) before reversing every occurrence at
  once — otherwise conservatively "not a flip", the same trade-off as a
  contrived title-collision missed-flip case this review accepted as
  out of scope. **The `replace_all` half was not actually fixed by this**:
  review 3 (RV3-m1, below) found the "absent `old_string`" guard never
  fires on real `replace_all` output (a clean application always removes
  every `old_string`), and both pinning tests used a post-edit fixture no
  Edit tool call could produce. See RV3-m1 for the real fix.
- **RV-n1 — the m6 fix narrative still blamed `pkgutil.walk_packages()`**,
  which already sorts its own directory scan; the real (now fixed) source
  was `HandlerRegistry.register_all`'s two previously-unsorted
  `event_dir.glob("*.py")` passes. Corrected in `claude_md_injector.py`,
  `docs_generator.py`, and both files' test docstrings.
- **RV-n2 — the fail-open convention split flagged by the first review's n4
  was read as unresolved, not intentional.** Unified behind one helper,
  `_open_ledger()`, that every ledger-opening call site in the class now
  goes through. The FIRST fix (this bullet, as originally written) caught
  `RuntimeError` inside `_open_ledger()` itself and returned `None`. The
  coordinator's own review of that fix (niggle N29) found it evaded
  `error_hiding`'s `return-none-on-error` check by assigning the caught
  error to a local read by a later, separate `return` — same behaviour,
  different AST shape. Commit `c40d4ce6` undid that: `_open_ledger()` now
  raises with no `try`/`except` at all, and each caller decides its own
  fail-open action explicitly (see its docstring). `error_hiding`'s
  `log-and-continue` check independently confirmed the two callers with
  nothing substantive to fall back to (`_maybe_refresh_on_retirement`,
  `_maybe_reassert_for_new_session`) cannot legitimately catch-and-log
  either, so both now propagate to `core/chain.py`'s own documented
  per-handler fail-open boundary instead.
- **RV-n3 — no test covered the RV-M1 scenarios or RV-m1's collision case
  (now fixed above); a registry test read the chain's PRIVATE
  `._handlers` list, which only worked because the lazy `.handlers` sort
  had not run yet.** Made the precondition explicit: the test now asserts
  `chain._sorted is False` before reading `._handlers`, so an accidental
  earlier `.handlers` access fails loudly instead of silently passing for
  the wrong reason.

Release note 13 and the module/class docstrings corrected again to
describe the ADDITIVE ownership and per-daemon-lifetime reassert latch
instead of the second pass's (now superseded) single-owner transfer.

**Fourth review pass (major RV3-M1, minors RV3-m1 through RV3-m8, nits
RV3-n1/n3/n4)**, fixed together:

- **RV3-M1 — the retirement refresh was state-based, not transition-based,
  and `owning_sessions` answered from the FIRST ledger entry for a plan
  number, including long-retired ones.** A reopened-and-recompleted plan
  retracted the WRONG (original) session, and any later edit to an
  already-Complete, not-yet-archived plan re-signalled every past owner —
  handing a session a goal for a plan it never touched, or clearing a
  session's own unrelated manual `inject-goal` goal. Fixed on both halves:
  `_maybe_refresh_on_retirement` now shares `_is_real_transition` with the
  flip side (target: a terminal status), gated exactly like N3 already
  gates the flip; `GoalLedger.owning_sessions` answers from the plan's LIVE
  entry when one exists, or else its MOST RECENTLY retired terminal one,
  never the first in the list. Pinned by RED tests for a reopened plan
  completed by a different session, the same with a second unrelated live
  plan, a note on an already-Complete plan, and the same note not clearing
  a manual goal.
- **RV3-m1 — the `replace_all` guard from the third pass never fires on
  real Edit-tool output.** A clean `replace_all` application always removes
  every `old_string`, so the "bail if `old_string` survives" guard was
  vacuous, and the reconstruction blindly reversed EVERY occurrence of
  `new_string` — including an untouched Status line that merely already
  read the same text as a genuinely-replaced table cell. Fixed: when an
  occurrence overlaps the real (non-fenced) Status line AND at least one
  other occurrence exists, two verdicts are compared — reverse everything,
  and reverse everything except the Status line's own occurrence;
  disagreement reads conservatively as "not a flip" (the same accepted
  trade-off the third pass already used elsewhere, now correctly extended
  to also miss a genuine bulk Status-line-plus-cells flip, which cannot be
  told apart from the collision from post-edit text alone). A single
  occurrence with nothing to disambiguate against is answered directly, so
  the ordinary single-site case is untouched. Both third-pass tests
  rewritten to use a REAL post-edit fixture (the pre-edit text with the
  transformation actually applied), plus a two-cell variant and a
  single-occurrence regression control.
- **RV3-m2 — the post-write "is it In Progress now?" check used a
  literal-only regex, disagreeing with the fenced-block-aware, first-line-
  wins `PlanDoc` the pre-write side already used.** A fenced example or a
  per-phase second `**Status**:` line could make an unrelated edit look
  like a flip, or (via the Edit fast path trusting `old_string`'s own
  fragment in isolation) make a per-phase Status line edit look like a
  top-level one. Fixed: `handle()`'s post-state check now uses
  `PlanDoc.parse(plan_text).status`, and the Edit fast path is removed —
  every Edit goes through the same reconstruct-and-compare `PlanDoc.parse`
  machinery the Write side already used, so both sides of the transition
  agree on what "the real Status line" is. A useful side effect: a Status
  line carrying a trailing date qualifier (`In Progress (2026-09-24)`),
  which the old literal regex could never match, is now correctly detected
  too.
- **RV3-m3 — a session whose own combined `/goal` text NAMES a plan it
  does not own is never refreshed when that plan later completes.** The
  combined text lists every live ledgered plan project-wide, but ownership
  only grew through a flip or reassert of THAT specific plan, so a session
  reading a plan's number in its own text could still be carrying a stale
  copy of it forever. Fixed: `_write_combined_signal` now registers its
  session as an owner of every plan its own rendered text just named
  (`_extend_ownership`), not only the one that triggered the write.
  Deliberately NOT applied to the retirement-refresh fan-out (RV3-m5 below
  needs that path's cost bounded by EXISTING owners only).
- **RV3-m4 — the flip path never set the reassert latch, and the latch map
  was unbounded.** The session that just flipped a plan could write a
  second, redundant signal on its own very next non-flip edit in the same
  daemon lifetime (the reassert path's own latch had never been armed),
  and 400 distinct reasserting sessions grew `self._reasserted` without
  bound, unlike `self._fired`'s existing 256-entry FIFO cap. Fixed: the
  flip path now sets both latches on a confirmed write, and `_record_latch`
  is a single bounded-insert helper shared by both maps.
- **RV3-m5 — plan ownership grew without bound, and refreshing many owners
  re-derived the combined text once PER owner.** 150 teammate sessions
  touching one live plan gave 151 owners with nothing pruning `sessions`,
  and completing that plan took 0.25s (a full live-plan-directory read per
  owner) against 0.003s on main. Fixed: `GoalLedgerEntry.sessions` is
  capped (`_add_owner`, FIFO-drops the oldest owner past the cap), and
  `_maybe_refresh_on_retirement` renders the combined payload ONCE
  (`_render_combined`) and writes it to every owner, rather than
  recomputing it per owner.
- **RV3-m6 — the Write path still fired on an already-In-Progress plan
  that was not yet committed as such.** git HEAD lagging an uncommitted
  flip meant a teammate's plain Write to an already-live plan could be
  misread as a fresh flip, wrongly re-emitting a ledger record and
  displacing another live plan. Fixed: for a Write only (Edit reads its
  own before/after span directly, immune to this race), a positive
  transition verdict is narrowed further by `_ledger_plan_is_live` — the
  ledger, not HEAD, is authoritative for whether a plan has already
  started.
- **RV3-m7 — documentation drift**, all corrected: the third pass's RV-n2
  bullet still described the round-1 catch-and-log helper after `c40d4ce6`
  reverted it to a propagating raise; two mentions of a
  `_session_ledgered_plan` method that was never actually named that; the
  RV-m1 bullet's "pinned by two RED tests" claim for `replace_all` (see
  RV3-m1 above); release note 13's three over-claims (see the note itself).
  This entry's status is held at 🔄 until this pass lands.
- **RV3-m8 — a non-UTF-8 PLAN.md of any LIVE ledgered plan crashed the
  handler, on more paths than the ledger-file case review RV-m5 already
  fixed.** `goal_ledger.py`'s `_plan_state` and `_find_plan_md_text` (used
  by reconciliation and by rendering the combined text respectively), and
  `goal_injection.py`'s own `_read_plan`, each caught only `OSError`.
  Under `strict_mode` (this repo), an unrelated plan's bad bytes turned a
  routine reassert or refresh into a blocking "SYSTEM ERROR" for the
  handler's whole PostToolUse chain. Fixed: all three now also catch
  `ValueError` (covers `read_text`'s `UnicodeDecodeError`), treating the
  plan as unreadable rather than crashing — matching RV-m5's existing
  tolerance for the ledger file itself.
- **RV3-n1 — held for a follow-up, not code changed.** `c40d4ce6`'s
  propagating `_open_ledger()` is correct; the failure it exposes (a
  `RuntimeError` reaching a real dispatch) cannot happen in a real daemon,
  since the controller initialises `ProjectContext` before
  `register_all`. The one true gap this nit found — the docstrings not
  mentioning that `strict_mode` also STOPS the rest of the PostToolUse
  chain, not just denies — is now documented in `_open_ledger`'s
  docstring.
- **RV3-n3 — review-round narration trimmed from code comments and
  docstrings** (the module docstring, `_open_ledger`'s docstring, and the
  `docs_generator.py`/`claude_md_injector.py` `pkgutil` asides) to describe
  current state; the module docstring now points at this file for full
  history instead of citing review labels inline. This pass was
  incomplete — the method-level docstrings still narrated before/after
  comparisons; see RV4-n1 below.
- **RV4-n1 — the RV3-n3 trim was incomplete: method docstrings still
  narrated before/after comparisons.** Fixed the three the report cited:
  `goal_injection.py`'s `_maybe_refresh_on_retirement` docstring dropped
  the "measured at 0.25s … against 0.003s on main" benchmark comparison
  in favour of the current-state perf rationale it was making;
  `goal_ledger.py`'s `GoalLedgerEntry`/`reassert_session` docstrings
  reworded "the pre-fix shape … broke/let" into a present-tense "a
  transfer would break …" hypothetical; `session_has_entries`'s docstring
  dropped "the previous implementation read" in favour of stating
  directly what the per-entry field does not mean. Rationale comments
  that explain WHY an invariant exists by naming the review finding that
  motivated it (e.g. `RV4-M1: protect names …`) are kept — that is the
  sanctioned rationale pattern, not the narration this nit targets.
- **RV3-n4 — the committed CLAUDE.md block was main's handler order, not
  this branch's own code's order** (last written by a main merge, one
  restart away from a spurious reorder commit). Regenerated by a daemon
  restart before this pass's commit.
- **RV3-n5 — fixed via a PreToolUse ground-truth snapshot, not another
  inference patch.** A value-only real flip missed when "In Progress" also
  appears as a table cell or a plan title (C3b, m4d's C3) was genuinely
  indistinguishable from the Edit payload alone — no amount of layering on
  `_is_transition_via_reconstruction` could resolve it, since the two
  candidate pre-edit texts really do parse to different verdicts. Fixed by
  removing the need to infer anything in the common case: a new PreToolUse
  handler, `plan_status_snapshot`, runs immediately before the SAME
  Write/Edit `goal_injection` sees after it lands, reads the plan's
  CURRENT (pre-write) status straight off disk, and records it in a
  bounded, TTL'd (`utils/plan_status_snapshot.py`) in-memory store keyed by
  `tool_use_id` (carried by both the PreToolUse and PostToolUse payloads
  for the same call). `goal_injection`'s new `_resolve_transition` consumes
  it as ground truth — no reconstruction, no collision possible. The old
  inference (`_is_real_transition` and everything it calls) is KEPT as the
  fallback for the narrow window where no snapshot exists (a daemon
  restart between the two dispatches, or a payload with no `tool_use_id`),
  and that fallback path is logged when taken. RV3-m6's `_ledger_plan_is_live`
  narrowing is scoped to apply ONLY on the fallback path now: a
  snapshot-backed verdict already read the plan's true pre-write status off
  disk, so the git-HEAD race it guards against cannot have occurred. Both
  handlers share one trigger-matching implementation
  (`utils/plan_trigger.py`) so they cannot silently disagree about what
  counts as "the trigger" the snapshot was recorded for. New tests:
  `TestGroundTruthSnapshotResolution` in `test_goal_injection.py` (C3b,
  m4d's C3, a restart-fallback pair, and an empty-`tool_use_id` case),
  `test_plan_status_snapshot.py`, `test_plan_trigger.py`, and
  `tests/unit/handlers/pre_tool_use/test_plan_status_snapshot.py`. Both
  `_read_plan` sites (`goal_injection.py`, `plan_status_snapshot.py`) raise
  a shared `PlanUnreadable` (`utils/plan_trigger.py`) instead of returning
  `None` on a read/decode failure — a missing file is checked BEFORE the
  `try` (not an error; the ordinary brand-new-plan case), so nothing
  inside either function's `except` block ever returns `None`. Each single
  caller catches `PlanUnreadable` explicitly, logs a WARNING naming the
  path and cause, and takes its own documented fail-open branch. This
  replaces the error_hiding exclusion both functions carried; there is no
  exclusion for either any more.
- **RV3-n2 — `session_has_entries` now tracks what its name says, and the
  B4 decision is pinned here.** `record_emission` overwrites an entry's
  single `session_id` field with whoever re-emits for the SAME plan next,
  and `_prune` can drop the entry out of the ledger entirely — either one
  silently lost the "this session once recorded a real emission" fact the
  method's own docstring claimed to answer. Fixed: a ledger-wide, bounded,
  order-preserving `ever_recorded_sessions` list (`_EVER_RECORDED_KEY`),
  populated ONLY by `record_emission` (both the new-entry and re-emission
  branches) and read/persisted through the SAME locked read-modify-write
  every other mutator already uses — it survives both the field overwrite
  and pruning, because it is no longer derived from either. Deliberately
  NOT populated by `reassert_session`: a session that has only ever been
  ADDED to a plan's ownership (never performed a real emission itself)
  must still read as having no entries of its own, so it correctly remains
  free to become a stakeholder of a second, unrelated live plan it is
  asked to track too (Plan 00269's own motivating case, still pinned by
  `TestOwnershipSurvivesASecondSession` in `test_goal_injection.py`).
  **B4 decision (accepted by team-lead, review-4-prep):** review 3's own
  worked example for B4 ("T becomes an owner of 00298") is
  `_extend_ownership`'s (RV3-m3) project-wide combined-signal side effect
  — the combined `/goal` text is global, so absorption only decides WHO IS
  REFRESHED when a plan retires, not who owns what in any sense that needs
  gating. `session_has_entries` is a SEPARATE, narrower question ("has
  this session ever performed a real emission"), and `_extend_ownership`
  is left untouched — this pass did not restrict it further. **Updated by
  RV4-M1:** that premise held only up to the RV3-m5 owner cap, which
  absorption could push the FLIPPING session itself past — evicting the
  one session that most needs its own signal refreshed when the plan it
  started completes (main never had this bug; the cap introduced it once
  combined with absorption). Fixed by pinning the flipper as the entry's
  `primary_owner`, exempt from the cap; absorbed (non-flipping) owners are
  still FIFO-capped exactly as B4 already decided. `session_has_entries`
  and `_extend_ownership` are otherwise unchanged by this. Backing
  `GoalLedger`-level tests: `TestSessionHasEntries` in `test_goal_ledger.py`
  (`test_survives_session_id_overwrite_by_a_different_re_emitting_session`,
  `test_survives_pruning_past_the_entry_cap`,
  `test_false_for_a_reassert_only_session`). `_load_raw` raises a shared
  `LedgerUnreadable` (`utils/goal_ledger.py`) instead of returning `None`
  on a genuine read/parse failure — a missing file (nothing written yet)
  is checked BEFORE the `try`, not an error. Every one of its five public
  callers (`entries`, `record_emission`, `reassert_session`,
  `live_plan_numbers`, `session_has_entries`) catches it explicitly, logs
  its OWN WARNING naming the path, cause, and which fail-open branch it is
  taking, rather than sharing one central catch-and-log. This replaces the
  error_hiding exclusion `_load_raw` carried; there is no exclusion for it
  any more. New tests: `TestUnreadableLedgerRaisesADomainException` in
  `test_goal_ledger.py`.

New tests: `TestOwnershipSurvivesASecondSession`-adjacent scenarios in
`test_goal_injection.py` (`TestReview3Fixes`, inheriting the
`TestNewSessionReassertion` fixture plumbing), new `replace_all`/fenced-
Status/uncommitted-Write cases in `TestStatusFlipDetection`, and new
`GoalLedger` test classes (`TestOwningSessionsAfterReopen`, `TestIsPlanLive`,
`TestNonUtf8PlanMd`) plus a `line_spans_outside_fences` primitive and its
tests in `utils/markdown_fences.py`.

**Fifth review pass (major RV4-M1, minors RV4-m1 through RV4-m7, nits
RV4-n1 through RV4-n7)**, fixed together (report:
`subagent-reports/260924-n466-goalflip-review4-opus-5-5.md`):

- **RV4-M1 — see the B4 decision update above:** the RV3-m5 owner cap
  combined with RV3-m3's absorption could evict the flipping session from
  its own plan's owner set once enough OTHER sessions touched any live
  plan it also named, so completing the plan never refreshed the
  flipper's own `/goal`. Fixed by pinning the flipper as the entry's
  `primary_owner` (never reassigned, exempt from the cap via a `protect`
  parameter threaded through `_add_bounded`), and by always including the
  completing write's own `session_id` in the refresh set regardless of
  what the ledger's owner set says. Pinned by
  `test_flipper_survives_absorption_past_the_owner_cap` (50-teammate
  absorption, `probe_gf4_evict2.py`'s E2) and
  `test_completing_session_is_refreshed_even_if_the_ledger_names_no_owner`
  in `TestReview4Fixes` (`test_goal_injection.py`).
- **RV4-m1 — the snapshot store's dict was mutated and iterated across
  threads with no lock.** The daemon dispatches every hook event through
  a `ThreadPoolExecutor`, and `record`'s eviction racing `consume`'s
  iteration raised `RuntimeError`/`KeyError` under real concurrency.
  Fixed: `PlanStatusSnapshotStore` now holds a `threading.Lock` around
  every mutation and iteration, matching `utils/config_cache.py`'s
  existing pattern. Pinned by a 4-thread stress test in
  `TestConcurrency` (`test_plan_status_snapshot.py`), confirmed RED
  (raised on 3/3 runs) before the lock and GREEN (3/3) after.
- **RV4-m2 — a snapshot could be stale by the time its own write landed.**
  PreToolUse runs before the permission prompt, which can precede the
  write by minutes; another session's write landing in that gap left the
  snapshot describing a file that no longer existed in that form. Fixed:
  `PlanStatusSnapshot` now carries a content hash (`hash_plan_text`) of
  the text it read; for a non-`replace_all` Edit, `_snapshot_is_fresh`
  reconstructs the candidate pre-edit text(s) and requires an exact hash
  match; a `replace_all` Edit or a Write cannot be reconstructed
  unambiguously (a collision can reverse an unrelated site too — the same
  shape RV3-m1 already works around at the verdict level, which does not
  extend to exact byte reconstruction), so those fall back to a
  `_SNAPSHOT_RECENCY_BOUND_SECONDS` (5s) staleness bound instead. On a
  stale snapshot, it is discarded and the existing inference fallback
  runs, logged as a distinct WARNING from the "no snapshot" case. Pinned
  by a race test modelling `probe_gf4_race.py`'s F3 (three plans; a
  second session's later flip of one must not let a first session's
  stale-snapshot-driven tick erase a THIRD plan's own displacement).
- **RV4-m3 — an `EACCES` (or other `OSError`) from the existence
  pre-check itself escaped as a raw, unwrapped exception**, in both
  `goal_ledger.py`'s `_load_raw` and `plan_status_snapshot.py` (the
  PreToolUse handler)'s `_read_plan`: the `is_file()` check ran BEFORE
  the `try`, so an unreadable parent directory or `ENAMETOOLONG` bypassed
  the domain-exception wrapping entirely. Fixed: the existence check now
  runs INSIDE the `try` — `return None` there sits in the try body, not
  an except handler, so it is not the shape `audit_error_hiding.py`
  flags — and every other `OSError` (including from `is_file()` itself)
  is caught and wrapped as the domain exception (`LedgerUnreadable`,
  `PlanUnreadable`) with a WARNING at the caller. Pinned by a
  permission-denied-file test in each affected test file, monkeypatching
  `Path.is_file` to raise `PermissionError`.
- **RV4-m4 — nothing told an operator that `goal_injection`'s
  ground-truth snapshot path needs `plan_status_snapshot` enabled.** The
  handler shipped opt-in (disabled by default), so a fresh install ran on
  inference alone with no signal that the ground-truth path was even
  available. `Handler.depends_on` looked like the natural coupling
  mechanism but has zero consumers anywhere in `src/` — not a real
  option. Fixed the simpler way team-lead offered: `get_default_enabled()`
  flipped from `False` to `True` (opt-out), with the docstring, the
  generated-config template (`daemon/init_config.py`), and the upgrade
  reference config (`.claude/hooks-daemon.yaml.example`) all updated to
  match — three independent sources of truth for one handler's default,
  each with its own drift-guard test
  (`test_default_enabled_template_consistency.py`,
  `test_reference_config_completeness.py`), both of which were ALREADY
  failing before this pass touched anything (the handler was never
  registered in either).
- **RV4-m5 — two gaps in what review 3's own fixes were pinned against.**
  (1) `test_task_tick_on_a_not_started_plan_with_a_fenced_status_example_ stays_silent` (C7b) and the phase-2 collision test (C8) carried
  PRE-edit fixture content, but PostToolUse dispatches AFTER the tool has
  already landed the edit — the fixture defect masked the very collision
  the tests exist to catch. Fixed the fixtures to hold POST-edit content.
  (2) the RV3-m2 fix itself (`handle()`'s `PlanDoc.parse(plan_text).status`
  gate, not a literal `'**Status**: In Progress' in plan_text` check) had
  no direct mutation-testing pin — `probe_gf4_mutate.py` confirmed the
  suite stayed GREEN under that exact literal-substring mutant. Fixed by
  adding `test_terminal_transition_ignores_a_fenced_in_progress_example_ in_the_post_edit_text` to `TestReview4Fixes`, using a recorded
  pre-write snapshot (ground truth, RV3-n5) to isolate the OUTER
  post-write gate from the unrelated INNER reconstruction-uniqueness
  filter a byte-identical fenced collision would otherwise also trip.
  Confirmed RED against the literal mutant, GREEN against HEAD.
- **RV4-m6 — the daemon needed an actual restart and doc regeneration in
  THIS pass, not a stale claim that a previous pass already did it.** Ran
  `bin/hooks-daemon restart` then `bin/hooks-daemon regenerate-docs`;
  both `CLAUDE.md` and `.claude/HOOKS-DAEMON.md` were already correct
  (no diff), so this pass's commit carries no doc changes from this step,
  but the claim in RV3-n4 above is now genuinely true rather than
  asserted.
- **RV4-m7 — documentation drift, corrected:** `HANDLER_REFERENCE.md`'s
  `goal_injection` entry described the OLD state-based trigger
  ("STATE-based … not transition-based") contradicting what N3 actually
  does; reworded to TRANSITION-based with the new-session-reassert
  exception named explicitly. `goal_injection.py`'s `_is_real_transition`
  docstring still described a removed "`old_string` FIRST witness, used
  DIRECTLY" fast path (RV3-m2 removed it); reworded to describe only the
  current always-reconstruct behaviour. `get_claude_md()`'s "every
  session ever handed a plan's goal keeps its own claim" was an overclaim
  past the owner cap even before RV4-M1; reworded to describe the
  pinned-primary-owner/FIFO-capped-absorbed-owners model precisely.
  Release note 13 updated: the terminal-drop claim now names the
  completing session's own guaranteed inclusion; the cap description now
  names the primary-owner exemption; the "can no longer be misread either
  way" claim is now scoped to "while that snapshot is trusted", with the
  staleness fallback named; the closing line now conditions "no action
  needed" on `plan_status_snapshot`'s default-enabled state rather than
  asserting it unconditionally. `auto_continue_stop`'s existing
  "Fail-open: a missing or unreadable ledger" claim (`HANDLER_REFERENCE.md`
  line ~3662) was re-verified rather than reworded — `live_plan_numbers`
  already catches `LedgerUnreadable` explicitly, and RV4-m3 is what makes
  that catch actually complete (an `EACCES` no longer escapes it
  unwrapped). `PLAN.md`'s N3 row, shown as ✅ Remedied, corrected back to
  🔄 In progress per team-lead's standing instruction that it stays there
  until merged.
- **RV4-n1 — see above** (folded into the RV3-n3 entry it follows
  directly, for locality with what it corrects).
- **RV4-n2 — `GoalInjectionHandler.matches()`/`handle()` re-implemented
  `matched_plan_write_or_edit` instead of calling it**, duplicating the
  tool-name/path/`Completed`/project-membership checks `utils/plan_trigger.py`
  already centralises for both handlers (its own module docstring claimed
  they were shared, when only `plan_status_snapshot` actually called it).
  Fixed: both methods now delegate to `matched_plan_write_or_edit`
  directly, which made `_plan_path_pattern()`, `_is_inside_project()` and
  `_COMPLETED_SEGMENT` genuinely dead code — removed along with their
  now-unused imports.
- **RV4-n3 — `record_emission`'s `LedgerUnreadable` warning did not say
  the save about to happen OVERWRITES the unreadable file.** For a
  transient `OSError` (as opposed to corrupt JSON), this silently
  destroys every live entry and `ever_recorded_sessions`. Fixed: the log
  message now says so explicitly.
- **RV4-n4 — `test_goal_injection.py` and `test_recovery_cron_advisor.py`
  each added their own copy of `test_git_facts.py`'s `_git` helper, each
  with its own `# nosec B603 B607` suppression** — two new suppressions
  reviewing the same trusted-subprocess-call shape a third file already
  carried. Fixed: extracted the ONE helper (`run_git`) to
  `tests/support/git_fixtures.py` (a new `tests/support/` package,
  outside the daemon's own `src/`), with a single suppression; all three
  test files now `from tests.support.git_fixtures import run_git as _git`
  instead of defining their own copy.
- **RV4-n5 — `TestOwnershipSurvivesASecondSession`, `TestResumedSameSessionReassertion`
  and `TestReview3Fixes` each SUBCLASSED `TestNewSessionReassertion` to
  reuse its fixtures, so pytest collected and RE-RAN its tests once per
  subclass too** (108 `def test_` methods, 117 collected). Fixed:
  extracted the shared fixture plumbing into `_ReassertionFixtures` (a
  leading underscore keeps it out of pytest's `Test*` collection), and
  every class above now inherits ONLY the fixtures, not each other's test
  methods.
- **RV4-n6 — docstrings asserted unconditionally that this repo's
  `strict_mode` DENIES**, contradicting N24 (`strict_mode` never reaches
  the live daemon, so it is inert in every install including this one).
  Fixed in `goal_ledger.py`'s `_load_raw` and `goal_injection.py`'s
  `_open_ledger` docstrings: both now state that the config DECLARES
  `strict_mode: true` while noting, citing N24, that the setting does not
  currently reach the live daemon, so the fail-open branch is what
  actually runs.
- **RV4-n7 — a symlink-loop `PLAN.md` raised `RuntimeError` from
  `is_inside_project`'s `resolve()` call** (`utils/plan_trigger.py`,
  copied from `goal_injection`'s pre-existing shape) instead of being
  treated as "not inside the project". Fixed: `RuntimeError` added
  alongside `ValueError`/`OSError` in the except tuple. Pinned by
  `test_symlink_loop_never_raises` in `TestIsInsideProject`
  (`test_plan_trigger.py`), confirmed RED (raw `RuntimeError` propagated)
  before the fix.

**Full-suite fallout from RV4-m3/m4, found by a whole-tree run after the
fifth pass above and fixed together (none of these were in the review-4
report itself):**

- **`eacces_safe_predicates_static_check` flagged RV4-m3's own fix.**
  `plan_status_snapshot.py`'s (PreToolUse handler) raw `is_file` predicate
  is exactly the shape that checker exists to catch, regardless of the
  `except OSError` one line below it -- it is a pure regex over the
  source text, not a flow analysis, so it also matched the SAME method's
  own docstring prose describing the predicate. Fixed: the existence
  check now goes through `utils.path_predicates.path_is_file(path, unreadable_means=True)`; on a stat failure this assumes "yes, try to
  read it" rather than silently answering `False`, so an EACCES does not
  vanish -- it reaches the SAME read attempt immediately after, which
  hits the identical permission error and is what the method's own
  `except` still converts to `PlanUnreadable`. The docstring's prose
  mention of the predicate reworded to not contain the literal
  `.is_file()` substring the checker also matches. The RED/GREEN
  permission-denied test updated to patch `Path.read_text` alongside
  `Path.is_file` -- patching only the stat call no longer reproduces the
  failure now that the stat alone does not stop the method.
- **`test_no_handler_is_unclassified` had no `get_claude_md()` verdict
  for `PlanStatusSnapshotHandler`.** It does return guidance text (not
  `None`), so it needed a `_EARNS_GUIDANCE` entry, not an exempt one.
  Added, alongside fixing that handler's own docstring/`get_claude_md()`
  text still saying "ships disabled" after RV4-m4 flipped the default.
- **`test_no_undeclared_module_imports_plan_qa` flagged
  `utils/plan_status_snapshot.py -> plan_qa.model`.** The SAME import
  `utils/goal_ledger.py` already carries, for the same reason (reading a
  plan's status via `PlanDoc`/`PlanStatus`) and already declared in that
  test's `_KNOWN_EDGES` allowlist. Declared alongside it with the same
  rationale, rather than treated as a new design question.
- **`test_real_repository_handler_doc_is_fresh` found `.claude/HOOKS- DAEMON.md` still missing `plan_status_snapshot`'s row and the handler
  count.** The RV4-m6 `regenerate-docs` run earlier in this pass did not
  pick this up (talks to the already-running daemon's in-memory handler
  registry, not a fresh reimport); a plain `bin/hooks-daemon generate-docs`
  run afterwards did. Regenerated again; committed alongside this pass.

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
