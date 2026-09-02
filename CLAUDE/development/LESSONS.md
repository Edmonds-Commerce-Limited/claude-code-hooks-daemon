# Engineering & Process Lessons

Durable, hard-won lessons for working on this repository — migrated out of
untracked Claude memory into a tracked, reviewed doc (Plan 00133 dogfood of the
`allow_untracked_claude_memory: false` policy). Each lesson is the **single
source of truth**; where a rule is already enforced by a handler or documented
elsewhere, this file links to it rather than restating it.

Keep entries lean. When a lesson becomes fully encoded in code/docs/tests,
delete it here and rely on that source.

---

## Acceptance gates must exercise the real production path

An acceptance gate added "to catch a regression class" only works if its fixture
runs the **actual production entrypoint end-to-end**. A fixture that synthesises
state (e.g. writes venv metadata via `write-venv-metadata` directly instead of
running `install.sh` → `ensure_venv` → `verify_venv`) will pass while the bug
class it claims to guard still ships.

**Why:** the v3.10.0 SEV-1 escaped the H-1 gate because the gate synthesised the
venv layout instead of running the `VAR=$(ensure_venv ...)` capture chain that
the `print_info`-to-stdout bug corrupted. See [RELEASING.md](RELEASING.md)
Step 12.0 — the H-1 gate now invokes the production install/diagnostic scripts.

**Apply:** before merging a gate, write down the production path the user hits,
make the fixture run it, and ask "what bug could ship while this gate passes?"
If the answer is "the bug we just fixed, in a different integration shape," the
gate is theatre — strengthen the fixture.

## A fixture must ESTABLISH the premise its test documents

An acceptance test whose docstring says "idempotent upgrade" is only testing
that if the fixture actually makes it idempotent. The three upgrade gates
resolved their target with `git describe --tags --abbrev=0` on a clone of
**HEAD** — true idempotency between releases, but during a release HEAD carries
the new version while the newest tag is still the previous one. The "upgrade"
silently became a **downgrade**, the version-specific upgrader rebuilt the venv,
and the run died with `No interpreter found at path ...` from uv — an error with
no visible connection to the premise that had quietly stopped holding.

**Why it bit at the worst moment:** the release bumps the version (Step 3) long
before it creates the tag (Step 14), and the BLOCKING QA gate runs in between.
So these gates were structurally unsatisfiable during every version-bumping
release — red exactly when the release most needs them green, which is precisely
the pressure under which someone talks themselves into shipping past a red test.

**Apply:** when a test's correctness rests on a premise, make the fixture
establish it *and then assert it*. `tests/acceptance/conftest.py` pins the clone
to its tag before the baseline install and re-checks with
`assert_clone_is_pinned`, so a future drift fails by name at the fixture instead
of as an unrelated-looking error three subprocesses deep. Also worth noticing:
the helper was copy-pasted into three files, and the duplication is what let the
same wrong assumption sit in all three unexamined.

## A QA gate only ever checks what you point it at — so test its BOUNDARY

A gate reporting green means "clean **within its scope**", never "clean". Scope
is a silent, unasserted assumption unless a test pins it. Three independent
dimensions can each be wrong while the gate stays green:

| Dimension     | How it goes wrong                        | Real instance                                                                                                                                   |
| ------------- | ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Scan roots    | Points at one tree, defect lives in more | `python_var_guidance` scoped to `src/`; 297 hits in `CLAUDE/` etc.                                                                              |
| File suffixes | Misses a surface that also instructs     | `.py`/`.md` only, so `.sh` scripts printing commands went unseen                                                                                |
| Pattern       | Matches one spelling of the defect       | `$PYTHON` only, missing `untracked/venv/bin/python` — 65 more <!-- python-var-guidance-exempt: names both banned spellings to contrast them --> |
| Invocation    | No gate runs it, and a doc says one does | 66 project-handler tests, cited by `gate-scope.bash` as the reason those handlers need no type checking, run by nothing                         |

**Why:** v3.50.0 shipped a release *specifically about* unrunnable guidance, with
a gate to prevent it, and 371 instances of that same defect survived across all
three dimensions (Plan 00193). Each was invisible to the search that found the
previous one. The gate had **no test file at all**, so nothing ever asserted
where it pointed.

**Apply:** every gate gets a test that runs it against its **real default
scope** and asserts zero findings (see `TestRepositoryIsClean` in
`tests/unit/qa/test_check_python_var_guidance.py`). Narrowing scan roots,
suffixes, or the pattern then becomes a test failure rather than a silent loss
of coverage. Before merging a gate, ask: "if this shipped green, where could the
defect still be?" — and encode the answer as scope.

Corollary: when a gate flags a case that is genuinely legitimate, prefer
**sharpening the rule** over adding an exemption. The `.sh` rule distinguishes
an output line showing a *command* from one reporting a resolved *value*, which
removed five false positives without a single exemption. Exemptions must be
inline and state their reason, so silencing a finding is visible in the diff.

**The invocation dimension is the worst of the four, because the documentation
argues against you finding it.** `scripts/qa/gate-scope.bash` excludes
`.claude/project-handlers/` from the mypy gate for a real reason — mypy refuses
a directory whose name contains a hyphen — and justified it in writing: "Those
handlers are covered by their own tests and by `validate-project-handlers`."
The tests existed. Nothing ran them: `pyproject.toml` sets
`testpaths = ["tests"]`, so `run_tests.sh`, `llm_qa.py` and the CI workflow all
missed them, and `validate-project-handlers` proves only that the modules
IMPORT. Two terminal handlers that DENY were unverified by every gate, and the
note explaining the exclusion was the very thing that discouraged anyone from
checking.

**Apply:** when a doc justifies an exclusion by citing coverage elsewhere, the
citation must NAME THE GATE that enforces it. "Covered by its own tests" is not
a claim about tests existing — it is a claim about a gate running them. If you
cannot name the gate, you have found a gap, not a justification.

## A verdict published under a key nobody reads is not a verdict

A QA report is consumed by code, and both consumers in this repo resolve a
report's status identically — `llm_qa.py`'s report resolution and the summary
block at the end of `run_all.sh` both take `summary["passed_all"]` when it is
present, and otherwise fall back to `summary["passed"]`.

That fallback is a trap for any TEST RUNNER, because there `summary.passed` is a
COUNT. A new check published its verdict as a top-level `passed` boolean — a key
neither consumer looks at — so a run of "60 passed, 1 failed" resolved through
the fallback to the truthy `60`, and both suites would have printed PASSED on a
red suite. The check's exit code was correct throughout; only the line a human
or an agent actually reads was wrong.

**Why it survives review:** the report looks right in isolation, and the happy
path agrees with the buggy path. Every green run prints PASSED either way, so
the defect stays invisible until something fails — which is the one moment the
report matters.

**Apply:** a report's verdict must live under the key its CONSUMERS read, and
the test must replay the consumers' own resolution rather than asserting the key
the producer happens to write. `run_tests.sh` publishes `summary.passed_all` for
exactly this reason; a new test-runner report follows it instead of inventing a
key. Generalised: when a producer and a consumer disagree about a token, the
count-only path is the one that goes quietly wrong.

## No silent fallback — surface errors loudly

Never pair `2>/dev/null` with a silent fallback to a default/legacy path when
invoking a critical helper (Python SSOT, resolver, validator). Capture stderr
and fail with an actionable directive instead.

**Why:** the v3.9.0 field regression — a `tomllib` import crashed under Python
3.9; all five SSOT shell sites suppressed it with `2>/dev/null` and silently
fell back to the retired `untracked/venv/bin/python`, <!-- python-var-guidance-exempt: names the retired layout to describe the bug --> so every diagnostic
reported "installation corrupted" on healthy hosts. This is the shell-script
form of the same principle the `error_hiding_blocker` handler and the FAIL FAST
standard in [CLAUDE.md](../../CLAUDE.md) enforce in source code.

**Apply:** reject `cmd 2>/dev/null || fallback_to_default`. Surface the error:
`echo "❌ <component>: <what failed> (see above)" >&2; exit N`. Only suppress
stderr that is genuinely uninteresting (probing an optional file's existence).

## Re-read QA results cleanly before an irreversible push

A QA verdict gates an irreversible action (push, tag, release). When terminal
output looks garbled or interleaved, do not trust a glanced "PASSED" — re-read
the result file with the **Read tool** (authoritative), looking for the
`QA: N/13` line and any `❌` markers, before acting.

**Why:** during Plan 00116 a corrupted Bash capture made `11/13 FAILED` read as
`13/13 PASSED`, and the failing tree was pushed to `origin/main` before a clean
re-read caught it. If output looks garbled, re-run to a **fresh** temp file and
Read that — stale temp files compound the confusion.

## Advisory-channel stickiness — interruption beats repetition

Hook delivery channels differ hugely in whether the agent actually attends to
them (empirically dogfooded, ranked strongest → weakest):

1. **PreToolUse deny / action interception** — stops the action, forces
   correction, perfectly recalled.
2. **UserPromptSubmit `additionalContext`** — re-injected every turn, reliably
   seen (this is the channel Claude Code's own POST-CLEAR signal rides).
3. **`get_claude_md()` / CLAUDE.md block** — always-on policy, but "wallpaper".
4. **PostToolUse advisory** — tuned out (repetition ≠ attention).
5. **SessionStart `additionalContext`** — weakest, nearly ignored: injected
   once, positionally buried, compacted away.

**Apply:** when designing an advisory handler that must change behaviour, do not
rely on SessionStart. Prefer riding an existing PreToolUse block, a PreToolUse
advisory at the Edit/Write that touches the relevant file, or a
once-per-session UserPromptSubmit line.
Stickiness comes from interrupting the relevant action at the decision moment.

## Restoring intended behaviour is a bug fix, not a breaking change

When a fix makes the daemon behave as it always claimed to (e.g. restoring the
per-tool approval flow in non-YOLO modes after `auto_approve_reads` wrongly
auto-approved), frame it as a **security/bug fix**, not a behaviour change. No
upgrade guide is owed, and no config flag should preserve the buggy behaviour. A
MINOR/PATCH is appropriate; MAJOR would wrongly imply a feature was removed.
Contrast a genuine default flip (e.g. Plan 00133's memory policy), which *does*
carry an upgrade guide and a post-upgrade task.

## Never weaken a test to match broken code

Tests define the correct behaviour. When a test fails — including during
acceptance testing — the default assumption is that the **code** is wrong, not
the test. Fix the code to pass the test; never adjust, weaken, or delete a test
to accommodate broken code. The only legitimate test edits are when the
*requirement itself* changed (then the test change is the deliberate spec
change, reviewed as such) or when a refactor moved a seam the test patched
(update the target, keep the assertion). If acceptance testing reveals a bug
(e.g. a handler that doesn't support 5-digit plan numbers), the handler is
wrong — fix it with TDD, do not relax the test.

## A test that restates the implementation is not a requirement

The rule above has a third case beyond its two stated exceptions, and it is
dangerous because it looks exactly like the forbidden one: a test that never
encoded a requirement at all, only a **restatement of the current constant**.
Such a test cannot fail when the code is wrong — it changes meaning whenever
the code does — and its real harm is that it makes a defect look deliberate and
covered.

**Why:** `pipe_blocker`'s `get_claude_md()` told every session that `git log`
and `git branch` were whitelisted, while `UNIVERSAL_WHITELIST_PATTERNS` had
never contained them, so agents were denied for doing what resident context
said was allowed. The same file contradicted itself — the `extra_whitelist`
docstring used `^git\s+log\b` as its example of a pattern you must ADD, three
hundred lines above the guidance claiming it was already there. Guarding the
divergence was a test whose entire docstring read *"git log is NOT whitelisted
(only git tag, status, diff are)"*: no rationale, no requirement, just the
constant spelled twice. It had shipped that way since the handler was written
and survived a full redesign.

**Apply:** when a test blocks a fix you believe is right, do not edit it on the
strength of that belief — this reasoning will rationalise almost any test edit.
Establish three things first, and abandon the change if any fails:

1. **Read the docstring.** Does it state a *requirement* ("X must be blocked
   because it is expensive") or *restate the implementation* ("X is not in the
   list")? Only the second is suspect.
2. **Check the history.** `git log -L` the assertion. A deliberate safety
   decision leaves a rationale somewhere — a commit message, a plan, a comment.
   Silence across its whole life is evidence it was never a decision.
3. **Justify the new behaviour independently**, on the merits, without
   reference to the text that disagreed with it. Here: `git log` is no more
   expensive than the already-whitelisted `git diff`, it writes continuously so
   a closed pipe raises `SIGPIPE`, and truncation is the *intent* of the pipe
   rather than the information loss the handler exists to prevent.

Then rewrite the test to assert the requirement with its reasoning, so the next
reader inherits a decision instead of an echo. And fix the guard, not just the
instance (Core Standard 15): the durable output here was a test deriving the
guidance's claims at runtime and asserting the handler honours them, so the two
cannot drift again in either direction.

## Backticks in a double-quoted `-m` message are executed, not quoted

`git commit -m "... `some command` ..."` does not quote the backticked text —
bash performs **command substitution** inside double quotes. The command runs,
and its stdout replaces the span in the message. Two consequences, one
cosmetic and one not:

- The commit message silently loses the phrase. Nothing errors, because the
  substitution "succeeded" — it just produced nothing useful.
- **The command actually executes.** A message describing a destructive
  command in backticks would run it.

**Why:** a commit here used `` pipe_blocker now allows `git branch ... | head`, so ... `` in a double-quoted `-m`. Bash ran `git branch ... | head`, which
printed `fatal: '...' is not a valid branch name` to stderr and nothing to
stdout, so the commit landed reading *"pipe_blocker now allows , so ..."*. The
`fatal:` looked like git rejecting the commit; it was bash executing a command
nobody asked it to run. The commit itself succeeded.

This repo's own blocking handlers do inspect the FULL Bash command string, so a
genuinely destructive backticked command would still be denied by
`destructive_git`/`sed_blocker` before bash saw it — the string-matching that
also causes the documented commit-message false positives. That is real
defence, not luck, but it is the last line, not the first.

**Apply:** in a `-m` message, write command names in single quotes, or in plain
prose, or pass the message via a file (`git commit -F`). If backticks are
genuinely wanted for markdown rendering, use a single-quoted `-m '...'` — no
substitution happens inside single quotes. And note the asymmetry when this
bites: `git commit --amend` is blocked in this repo, so a corrupted message
cannot be quietly rewritten — check the message before committing, not after.

## Verify through the production entry point, not a hand-rolled client

A verification harness that reimplements how production talks to a component
can fail in the direction that reports a **working guard as broken** — or, far
worse, a broken guard as working. Zero findings from a blind probe is
indistinguishable from zero findings from a clean system.

**Why:** closing Plan 00207 meant probing every ancestry-severing merge
spelling against the live daemon. A hand-rolled `AF_UNIX` client that guessed
the wire protocol returned `allow` for all six spellings that must be denied —
a clean-looking "the handler is not firing". It was caught only because the
live daemon had blocked those same commands minutes earlier through the real
hook path, so two observations of one daemon contradicted each other. Re-run
through the production forwarder (`.claude/hooks/pre-tool-use`, payload on
stdin), all ten spellings behaved as specified.

**Apply:** probe through the same entry point production uses. When a handler
matches on the full command string, assemble blocked literals from fragments at
runtime (`"--" + "squash"`) so the launching command does not trip the handler
under test — that false trigger is correct behaviour, not something to disable.
Always include a **positive control**: at least one case that must be denied.
Without it, a harness that silently reports "allow" for everything looks
identical to a passing run.

## Fix defects you find — don't just report them

When you discover a bug, inconsistency, or defect while doing other work —
including one you are tempted to downgrade to a "minor note" — **fix it in the
same pass**, then report that it is fixed. Surfacing a defect and moving on
leaves it to rot and quietly erodes trust in "done". "Done" means fixed and
verified, not catalogued. This is the same principle as the dogfooding mandate
([CLAUDE.md](../../CLAUDE.md) "Dogfooding Bug Fixes") and Plan 00157's "never
drop a finding" ([RELEASING.md](RELEASING.md)) — a finding is either fixed now
or captured as a tracked MUST-FIX plan item, never left as prose.

**Why:** v3.43.1 shipped with a stale `v3.43.0` header in the generated
`.claude/HOOKS-DAEMON.md`. The release summary flagged it as a "minor
non-blocking note" instead of fixing it — the user (rightly) pushed back with
"don't just report errors, fix them". Both the header and the root cause (the
release flow never regenerated the doc) were then fixed in minutes. Reporting
it cost a round-trip and shipped a wrong-versioned artifact; fixing it first
would have cost nothing.

**Apply:** when about to write "note:", "caveat:", "one minor thing:", or
"non-blocking:" about a defect in your own work, stop and ask "can I fix this
right now?" If yes, fix it and report the fix. If it is genuinely out of scope
or too large for this pass, capture it as a tracked plan item with file:line
and remediation — never as a disappearing sentence in a summary. Prefer fixing
the root cause too, so the class of defect cannot recur.

## Working in this repo: expect silent stops after Edits

In `/workspace` (the daemon's own repo) the Stop hook occasionally delivers as
`level: suggestion` instead of hard re-entry, so the agent can appear to stop
mid-task after a successful Edit. **Continue without stopping.** Always
**Read a file before Edit/Write** — editing an unread file returns a
`tool_use_error`; recover by Read → retry Edit, never stop silently. Large-file
Edits (notably `daemon/cli.py`) can trigger a `"Separator is found, but chunk is longer than limit"` PostToolUse error that swallows advisory context — a known
repo-specific trigger, not a reason to halt.

## Never add a top-level cross-package import to `daemon/paths.py`

`daemon/paths.py` is **bootstrap-critical**: it is imported at module top by the
standalone `python3 paths.py resolve-venv` wrapper on the *system* Python
(possibly 3.9, before any venv exists). It must stay import-light — new
dependencies belong in **function-local** imports, never at module top.
`test_paths_import_under_310` already enforces this for `tomllib` (Plan 00103
deferred it into `_load_toml_or_raise`); the rule generalises to *every*
non-stdlib import.

**Why:** Plan 00181 Task 3.2 added a top-level
`from ...utils.retention import prune_directory` to paths.py. Unit tests passed
and `pytest tests/unit/daemon/` passed in isolation, but the full QA suite
(run under `coverage --cov=src --cov=.claude/ccy`) failed **25 tests** — and the
failures did NOT reproduce under a plain `pytest tests/` (they looked flaky).
The discriminating variable was coverage's eager full-module import pulling the
whole `utils/__init__` chain into paths.py's module load in a
collection-order-sensitive way. Moving the single import into the body of
`cleanup_stale_session_dirs` took the exact coverage harness from *25 failed* to
*10443 passed, 0 failed* with no other change.

**Apply:** When a `daemon/paths.py` function needs a package-internal helper,
import it **inside the function**, with a comment pointing at this rule. Treat a
green `pytest tests/unit/daemon/` as necessary-but-not-sufficient: a
coverage-only, order-dependent failure is invisible to isolated runs — always
clear the full `./scripts/qa/llm_qa.py all` gate (which runs under coverage)
before declaring a paths.py change done.

## `git status` is a WRITE — a daemon sharing a working tree must decline optional locks

**Symptom:** stale `.git/index.lock` files, and git commands failing with
"Unable to create '.git/index.lock': File exists" for no visible reason.

**What happened (Plan 00246):** `git status` does not just read. It refreshes
the index and writes it back, which acquires `.git/index.lock`. The daemon ran
one on every user prompt (`git_context_injector`), one on every status-line
render (`git_branch`), and three git calls on every daemon start (the CLAUDE.md
auto-commit) — all in the working tree the agent is using. Every one of those was
contending with the agent's own git for the same lock, and none of them needed
to: `GIT_OPTIONAL_LOCKS=0` tells git to skip work requiring an OPTIONAL lock, and
it appeared **zero times** in the codebase.

Measured, not assumed: with the cached stat info made stale, a plain
`git status --porcelain` rewrote `.git/index`; the same command with
`GIT_OPTIONAL_LOCKS=0` did not. Output is byte-identical in both cases — git
still does the comparison in memory, it just stops PERSISTING the result.

**Apply:** any git the daemon runs against the project tree goes through
`utils.git_repo.run_git`, which sets the variable and a timeout by construction.
`tests/integration/test_git_spawns_are_bounded.py` fails on a new direct spawn.
More generally: before calling a subprocess "read-only", check whether it writes
— `stat` the artifact before and after rather than trusting the verb.

## A timeout can cause the failure it is there to prevent

**What happened (Plan 00246):** the CLAUDE.md auto-commit had no timeout on any
of its four git calls, so the fix was obviously "add one". But `subprocess`
KILLS the child when a timeout expires, and git killed part-way through writing
the index is exactly how `.git/index.lock` gets orphaned. A tight bound on a
commit — which may run the repo's pre-commit hooks — would have manufactured the
very symptom being fixed, while looking like a fix.

**Apply:** when adding a timeout to something that mutates state, pick the bound
from how long the legitimate slow case takes, not from how long you would like to
wait. Record the reasoning at the constant (`Timeout.GIT_COMMIT`), because the
next person will read 30 seconds as excessive and tighten it.

## A declared architecture that nothing enforces is a suggestion

**What happened (Plan 00246):** `utils/git_repo.py` has stated since Plan 00113
that "new git operations are added as methods on `GitRepo`, not by
re-implementing `subprocess.run(["git", ...])` in each caller". Fifteen files did
it anyway, across ~30 call sites. The cost only became visible when a one-line
fix (one environment variable, one timeout) turned into a thirty-site sweep.

**Apply:** if a module docstring states an invariant worth keeping, add the check
that fails when it is broken — in the same commit, not later. A convention with
no guard decays at exactly the rate people forget it, and the decay is invisible
until something forces you to touch every site at once. See DBF (`CLAUDE.md`
Core Standard 15).

## A permanently-red CI is a blind guard, not a nuisance

**What happened (Plan 00245):** GitHub Actions failed on every push for 25+
consecutive runs while the local suite was fully green. Because it was ALWAYS
red, no decision ever depended on it — so it had stopped being a check and
become scenery. The cost was not the red tick: it was that Plan 00244 had just
added a project-handler test step to that workflow, and a step added to an
already-red workflow can never be the thing that turns CI red or green. New
coverage was wired in and inert.

All 41 failures turned out to be real, diagnosable, and fixable in a day.

**Apply:** a check whose result nobody reads is the DBF failure mode (`CLAUDE.md`
Core Standard 15) one level up from the code. Treat "CI is always red" as an
outage, not a known quirk: while it is red, every guard downstream of it is
unverifiable, including ones added later by someone who assumed CI worked.

## Six CI-only failures, one defect: the test took its premise from the environment

**What happened (Plan 00245):** the failures looked like six unrelated bugs. Each
was the same mistake — a test depending on something the ENVIRONMENT supplied
rather than something it established:

| Symptom                            | Ambient thing depended on                    |
| ---------------------------------- | -------------------------------------------- |
| venv never created                 | `CI` being unset (`ensure_venv` skips on it) |
| fingerprints differed              | `sys.executable` being a venv of `/usr`      |
| resolver disagreed with the test   | discovery picking the running interpreter    |
| mode actions returned the fallback | `hasattr`-based protocol checks (pre-3.12)   |
| `commit-tree` exited 128           | a global git `user.email`                    |
| lint findings appeared             | the installed ruff's default rule set        |

Every one passes on a developer machine and fails on a fresh runner. Two also
passed for the WRONG REASON rather than failing: a gate test asserting "the skip
happens" passed because ambient `CI=true` was already causing the skip, and a
`dispatch.assert_not_called()` was vacuous because that interpreter took the
other branch entirely.

**Apply:** when a test asserts a property about a PAIR — an interpreter and its
venv, a config and its consumer — construct both rather than reading one from the
environment. Where the premise cannot be seen from the assertion (an interpreter
pin, an injected git identity), add a guard that fails LOCALLY when it is
removed; otherwise the next person rediscovers it from a red CI they cannot
reproduce. And when a test passes, check it would have failed: a passing
assertion whose subject was never reached is worse than a red one.

## Install the interpreter that failed; do not reason about it

**What happened (Plan 00245):** three failures were a Python 3.12 change
(`runtime_checkable` protocol `isinstance` now uses `inspect.getattr_static`,
which does not fire `Mock.__getattr__`) and one was a 3.13 change (`Path.is_dir()`
now calls `self.stat(follow_symlinks=...)`). Both were invisible on the local
3.11. `uv python install 3.12` fetched the exact runner interpreter in four
seconds, and `uv venv` + `uv pip install -e ".[dev]"` made a full local matrix.
Diagnosis went from "push and wait ~6 minutes" to seconds per iteration, and the
fixes were verified on the interpreters that actually failed instead of argued
about.

**Apply:** for any CI-only failure on a specific interpreter or toolchain
version, install that version locally before theorising. Also beware where you
put it: a scratch venv under `untracked/venv-*` is inside the namespace
`resolve_venv_python` globs, so it silently became the interpreter for every
`$PY` in the session and made several runs report the wrong Python.

## A skipped test is indistinguishable from a passing one

**What happened (Plan 00245):** fixing 41 CI failures left 4, on all three
interpreters. They looked like new regressions. They were not: four upgrade gates
in `tests/acceptance/` skip themselves when `uv` is missing, and CI had no `uv`,
so they had been skipping on every run since they were written. Installing `uv`
for an unrelated reason un-skipped them, and only then did anyone learn they
could not pass on a runner. Nothing had ever reported them as absent — a green
job and a job whose gates never ran render identically. The only trace was a
totals line (`14 skipped` in CI against `6` locally) that nobody diffs between
runs, and which does not say WHICH.

This is the DBF rule applied to test infrastructure: the defect was four dead
tests, but the bug worth fixing is that a dead test looked exactly like a live
one, so nothing would have reported the next one either.

**Apply:** run CI's pytest with `-rs` so every skip is NAMED with its reason in
the log. When you make a conditional dependency available (a tool, a service, a
credential), expect previously-skipped tests to wake up — treat their first
failures as long-standing, not as regressions from your change. And when writing
a `skipif` for a missing tool, remember you are choosing silence: prefer
installing the tool in CI to skipping — Plan 00245's Decision 3 settled that
here, and it is what surfaced these four.

**It paid out immediately.** The first green run after `-rs` landed named 11 more
silent skips nobody knew about: every socket-dependent acceptance test
(`test_absolute_path_socket_deny.py`, `test_stop_hook_hard_block.py`,
`test_tool_use_error_recovery.py`) skips in CI for want of a running daemon —
including files `RELEASING.md` Step 12.0 declares BLOCKING, one of which it says
explicitly "a skip there is itself an abort condition". Two rounds of this lesson
in one plan, from the same one-flag change.

## A test that was never ROUTED does not even appear as a skip

**What happened (v3.60.0 release gate, Plan 00319 Task 4.4):** the acceptance
playbook emits 276 tests. `RELEASING.md` Step 12.4 says to route each one by
its `Requires Main Thread` field, so the runner split the playbook on that
field into a delegable set and a main-thread set. Seven tests carry no such
field. Four are playbook-declared SKIPs and resolve themselves. The other three
are `Type: CLI Feature`, a shape the field does not describe — and they fell
into NEITHER set. They went unexecuted across two consecutive full acceptance
passes, and nothing reported them: not as failures, not as skips, not at all.

An eighth test was lost differently. Test 210 sat correctly inside a delegable
batch, but its runner's report simply omitted the row while its own summary
claimed a total (20) that did not match the rows it had written (23). A
self-reported total is an assertion by the thing being audited.

Both were caught the same way, and only that way: counting. 276 total minus 82
main-thread minus 187 delegable did not reconcile, and the union of every
runner's reported test numbers was one short of the delegable set.

**Apply:** this is the next rung below
[A skipped test is indistinguishable from a passing one](#a-skipped-test-is-indistinguishable-from-a-passing-one).
A skip at least appears in the report with a reason. A test that was never
routed produces no row at all, so no amount of reading the reports finds it —
the absence is visible only against the SOURCE OF TRUTH.

- Reconcile the executed set against the generator's full set by IDENTIFIER,
  not by total. Diff the sorted test numbers; do not compare counts alone, and
  never accept a runner's self-reported total as the denominator.
- When you route work by a field, first ask which items LACK that field.
  Routing on an optional attribute silently discards everything that does not
  carry it, and the discard looks identical to success.
- Prefer a router that fails loudly on an unroutable item over one that drops
  it. The defect worth fixing is not the three missed tests; it is that a
  dropped test and a passing test rendered identically.

The same reconcile-by-identifier discipline caught a second omission in the
same release: the follow-up plan capturing the review's ten non-blocking
findings held F1 and F3-F10, having skipped F2 in its own numbering. Nine
findings filed under a heading promising ten reads exactly like ten.

## Centralising a property imposes the centre's defaults on every call site

**What happened (Plan 00248):** Plan 00246 did the right thing and routed ~30
scattered `subprocess.run(["git", ...])` calls through one `run_git` chokepoint,
which is how the timeout and environment fixes became one-line changes. But every
one of those call sites inherited `run_git`'s default budget — five seconds, sized
for the hook context it was written for. `branch_safety.py` does nothing of the
kind: `git cherry` computes a patch-id per commit, `rev-list --objects` and
`ls-tree -r` enumerate every tree and blob in a ref. On a large repository the
centralisation therefore introduced a `CalledProcessError` into a command that had
previously run unbounded and worked. The consolidation was still correct; the
regression was the default riding along with it.

**Apply:** when you move N call sites behind one helper, the diff to review is not
only the code you deleted — it is the set of implicit properties each site used to
choose for itself and now cannot. Timeouts, encodings, `check=`, environment,
retries and cwd all behave this way. For each, ask which site had the most extreme
legitimate requirement, and either size the default for that site or keep the knob
per-call (`_git(..., timeout=Timeout.GIT_BUNDLE_CREATE)`). A chokepoint that is
right for the average caller is wrong for the tails, and the tails are where the
expensive work lives.

## Prefer the battle-tested tool's checks — they COMPOSE with yours

**What happened (Plans 00253, 00254):** `delete-branch` proves a branch recoverable
and then asks git to delete it. Three separate times the decision to keep `git branch`
rather than route around it paid off, and only the first was foreseen.

1. **00253** kept the safe delete for the `merged` tier so git re-runs its own
   ancestry check independently of ours — the stated reason being that a bug in our
   classifier then cannot cause a silent loss.
2. **00254** rejected a proposal to swap the force tiers for
   `git update-ref -d <ref> <expected-sha>`, which IS a genuine compare-and-swap and
   would have closed the moved-tip race completely. The premise was that the force
   tiers give up nothing because git checks nothing there. Executing it showed that
   false: `git branch`'s delete refuses a branch checked out in a linked worktree,
   and the plumbing delete removes it and leaves that worktree on a dangling `HEAD`.
   It also leaves `branch.<name>.remote`/`.merge` behind — the exact two keys that
   decide a later same-named branch's tier.
3. **Unforeseen:** when a same-named tag made the proof describe the wrong object
   entirely, the `merged`-tier case lost nothing — *because git refused what our
   corrupted proof had approved*. Git caught a bug in our reasoning, which is the
   argument in (1) paying out in a form nobody had written down.

**The sharpening that makes it a rule rather than a preference:** the two guards do
not overlap, they COMPOSE. Our tip re-check catches a branch whose sha moved; git's
delete-time check catches a peer *checkout*, which moves no sha and is therefore
structurally invisible to any tip comparison. Verified across all five tiers' actual
argv — the worktree check fires on the force delete too, not only on the safe one.
Swapping in the CAS would have closed one window and opened the other.

**Apply:** when you are about to replace a mature tool's operation with plumbing that
does exactly the part you care about, the question is not "is my version correct for
my case" but "what else was that operation checking, and who was relying on it".
Enumerate its checks by running it against the states you are not thinking about — a
branch someone else has checked out, a name that is also a tag, a ref that moved
underneath you. The checks you cannot enumerate are precisely the value you would be
discarding, and they are usually why the tool is longer than your replacement.

## Score a proposed guard against the defects it would have had to catch

**What happened (Plan 00255):** DBF says a defect fixed by hand recurs, so after
fixing the ambiguous-refname defect for a second time the obvious move was a QA
check that rejects bare branch names in git argv. Before writing it, I scored it
against the twelve call sites 00254 and 00255 had actually fixed. It would have
caught **none of them**: every one passes a *variable* (`base`, `name`, `rev`), and
no syntactic rule can tell whether a variable holds a branch name, `HEAD`, or
`origin/main`. The only thing it would have flagged is hardcoded literals — which in
this tree are the already-correct ones, like `show-ref --verify refs/heads/{x}`.

So the proposed guard had a 0% true-positive rate against real history and a live
false-positive rate. That is not a weak guard, it is a *negative* one: it costs
attention on correct code, teaches people the checker is wrong, and gets disabled.

What was checkable was the narrower READ side — `%(refname:short)` in a git format
string, a literal, with a named replacement to point at. That rule flags both real
pre-fix sites and does not fire on the docstrings that describe the defect.

**Apply:** a guard proposal is a hypothesis, and you already have the labelled data
to test it — the diff of the fix you just made. Before writing the checker, ask
"which of the sites I just fixed would this have flagged, and which correct sites
would it have flagged too?" If the answer is "none, and several", the defect class
is real but you have picked an unenforceable projection of it; find the subset that
is mechanically visible and guard that instead. Then say in the rule which half it
covers — a guard that overstates its reach is worse than an absent one, because the
next reader stops looking.

## Test in the host's invocation context, not your own

The relay dogfood shipped four defects to a live session while unit,
integration, acceptance AND manual smoke checks were all green — because every
one of those surfaces invoked the hooks differently from how Claude Code does.
Three distinct context gaps, one root failure mode:

1. **stdin fd type.** Claude Code hands hook commands a SOCKET as stdin; every
   test fed a pipe. `< /dev/stdin` re-opens the path — an `open()` on a socket
   fails ENXIO — so the transport failed on every REAL event and no test could
   see it. Pipes and sockets both read fine; they differ exactly at re-open.
   Guard: `tests/integration/test_forwarder_socket_stdin.py` invokes the real
   deployed forwarders with a socketpair as stdin.
2. **Payload shape.** Verification payloads were written BY THE VERIFIER, who
   helpfully included `hook_event_name` — the very field the transport under
   test is responsible for injecting. The check validated the author's
   assumptions, not the host's behaviour. Rule: an end-to-end payload must be
   what the host actually sends, with NOTHING hand-added that any layer under
   test is supposed to supply.
3. **Response direction.** The status line needs the daemon's JSON unwrapped
   to raw text on stdout; a byte-pump transport cannot do that, and nothing
   asserted the RESPONSE shape Claude Code consumes — only that "a response
   came back". Assert what the host will do with the answer, not that an
   answer exists.

The general form: a transport/adapter boundary has THREE contracts — how the
host calls you (fd types, env, argv), what the host sends (payload as-is), and
what the host does with your answer (parse mode, exit-code semantics). A test
suite that pins only the middle one can be fully green while every real
invocation fails. When a component sits on a host boundary, write at least one
test per contract IN the host's own manner of invocation — and treat "works
when I run it by hand" as evidence about your hand, not about the host.
