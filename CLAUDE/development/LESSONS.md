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
once-per-session UserPromptSubmit line (alongside `post_clear_auto_execute`).
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
