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
