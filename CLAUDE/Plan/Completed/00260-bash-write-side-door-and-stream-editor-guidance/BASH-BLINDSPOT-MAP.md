# Bash-Write Blind Spot Map — the 21 Write/Edit-keyed handlers

> **This census is a SNAPSHOT and is already one row short.** It was taken at
> v3.53.1; the enumerating test added in Task 2.3
> (`tests/integration/test_bash_write_blindness_coverage.py`) finds **22**,
> because `write_clobber_guard` shipped a day later with exactly this hole. The
> 21 rows below remain accurate and the analysis stands — but the test, not this
> file, is the authority on WHICH handlers are affected, precisely because a
> hand-written census cannot notice a handler added after it was written.

Input to Plan 00260 Task 2.1. Every row below was settled by reading
`matches()`/`handle()` in the named file; nothing here is inferred from the
handler's documentation or from `get_claude_md()`. The headline result is that
the provisional PATH/CONTENT split in the plan needs three corrections, and
they all move in the same direction — **more of the blind surface is
recoverable from a target path alone than the plan assumed**. In particular the
three PostToolUse handlers `lint_on_edit`, `validate_eslint_on_write` and
`markdown_table_formatter` look content-keyed but are not: they run their
checker against the path and read the bytes off disk themselves, so a path-only
utility restores them completely. Two of those three DENY. Against that, one
handler the plan lists as path-keyed (`plan_time_estimates`, in Task 3.1's
list) genuinely needs content, and one (`absolute_path`) should not be extended
to Bash at all. Of the 21, exactly **4** have any Bash awareness today
(`sed_blocker`, `sensitive_content`, `markdown_organization`,
`recovery_cron_advisor`), and in three of those four the awareness covers a
different premise from the one at risk.

## Where the blindness is actually implemented

It is not 21 independent decisions. `core/utils.py` line 36 defines the shared
accessor:

```python
def get_file_path(hook_input: dict[str, Any]) -> str | None:
    if hook_input.get("tool_name") not in ["Write", "Edit"]:
        return None
```

`get_file_content()` immediately below it gates the same way. Most of the 21
call one or both, so the tool-name test is enforced *before* any handler logic
runs — a handler cannot opt into seeing a Bash write even if its author wanted
to. The remainder (`absolute_path`, `lock_file_edit_blocker`,
`validate_instruction_content`, `plan_qa_edit`) read `tool_input["file_path"]`
directly and apply their own equivalent tool-name test.

This matters for Task 3.1: the thing to generalise is not only
`markdown_organization._bash_memory_write_target` but this choke point. A new
`bash_write_targets(hook_input) -> list[str]` belongs beside `get_file_path`,
not inside one handler.

## One distinction the plan does not yet draw: heredoc vs redirect

The three Bash write routes are not equally opaque.

- **Heredoc** (`cat > f <<EOF ... EOF`) — the body is *literally in the command
  string*. Content-keyed handlers could see it at no parsing cost beyond
  locating the delimiter.
- **Redirect of a command's output** (`python3 gen.py > f`) — the content does
  not exist until the command runs. Genuinely unknowable at PreToolUse.
- **`tee` from a pipe** — same as redirect.

So the PATH-vs-CONTENT split is the right axis for deciding what a path-only
utility buys, but a utility that returned `(target_path, heredoc_body or None)`
would additionally serve most of the content-keyed column, because the
harness-injected instruction that motivated this plan pushes agents toward
heredocs specifically.

## The map

`Bash write can violate the premise?` asks only whether the guarded premise can
be broken by a file reaching disk through Bash — not whether that is likely.

| #   | Handler                        | Event       | Premise guarded                                                                                    | Bash write can violate?                                                 | Keying                                                                     |
| --- | ------------------------------ | ----------- | -------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| 1   | `absolute_path`                | PreToolUse  | A Read/Write/Edit `file_path` argument must be absolute                                            | NO (see note A)                                                         | PATH                                                                       |
| 2   | `british_english`              | PreToolUse  | Prose in `.md`/`.txt`/`.html`/`.ejs` under `CLAUDE`/`docs`/`private_html` uses British spellings   | YES                                                                     | BOTH — path gate, then content scan                                        |
| 3   | `comment_changelog`            | PreToolUse  | No historical narrative inside a code comment                                                      | YES                                                                     | BOTH — path selects the language strategy, content is scanned              |
| 4   | `comment_size`                 | PreToolUse  | No comment line or block over the configured limit                                                 | YES                                                                     | BOTH — plus needs the before-state for its grow/shrink tiering             |
| 5   | `daemon_docs_guard`            | PreToolUse  | You are reading the daemon's internal `CLAUDE/` copy, not the project's                            | YES, but it is a READ path (see note B)                                 | PATH                                                                       |
| 6   | `error_hiding_blocker`         | PreToolUse  | No error-suppression idiom in written code                                                         | YES                                                                     | BOTH — path selects strategy, content decides                              |
| 7   | `lock_file_edit_blocker`       | PreToolUse  | Package-manager lock files are generated, never hand-edited                                        | YES                                                                     | PATH only                                                                  |
| 8   | `markdown_organization`        | PreToolUse  | Markdown lives in an allowed location; this project also bans untracked Claude memory              | PARTIAL — memory paths partly covered, the location rule is fully blind | PATH only                                                                  |
| 9   | `plan_qa_edit`                 | PreToolUse  | A plan document satisfies the plan-QA edit-stage rules                                             | YES                                                                     | BOTH — path gate, then a content lint                                      |
| 10  | `plan_time_estimates`          | PreToolUse  | No work/effort estimates in a plan document                                                        | YES                                                                     | BOTH — content required (see note C)                                       |
| 11  | `plan_workflow`                | PreToolUse  | Creating a `PLAN.md` surfaces the workflow contract                                                | YES                                                                     | PATH only                                                                  |
| 12  | `qa_suppression`               | PreToolUse  | No QA-suppression annotation in source                                                             | YES                                                                     | BOTH — path selects strategy, content decides                              |
| 13  | `security_antipattern`         | PreToolUse  | No OWASP antipattern construct in written code                                                     | YES                                                                     | BOTH — path selects strategy, content decides                              |
| 14  | `sed_blocker`                  | PreToolUse  | Two premises; the Write-branch one is that a `.sh`/`.bash` script must not contain a stream editor | PARTIAL, and accidentally so (see note D)                               | Command-anchored                                                           |
| 15  | `sensitive_content`            | PreToolUse  | A blocked pattern or secret term never enters the repository                                       | YES — Bash is handled, but only for git metadata                        | BOTH — the PATH is a haystack in its own right, as well as the body        |
| 16  | `tdd_enforcement`              | PreToolUse  | No production source file exists without a test file                                               | YES                                                                     | PATH — content feeds only the `should_skip` check                          |
| 17  | `validate_instruction_content` | PreToolUse  | `CLAUDE.md`/`README.md` hold stable instructions, not session state                                | YES                                                                     | BOTH — `matches()` is path-only, `handle()` is content-driven (see note E) |
| 18  | `lint_on_edit`                 | PostToolUse | Every write to a lintable source file passes its linter                                            | YES                                                                     | PATH only — reads from disk                                                |
| 19  | `markdown_table_formatter`     | PostToolUse | Markdown tables are re-aligned after every write                                                   | YES                                                                     | PATH only — reads and rewrites from disk                                   |
| 20  | `recovery_cron_advisor`        | PostToolUse | Plan lifecycle moments prompt recovery-cron management                                             | PARTIAL — `mkplan.bash` already covered                                 | BOTH — creation is path/command, progress and completion need content      |
| 21  | `validate_eslint_on_write`     | PostToolUse | Every `.ts`/`.tsx` write passes ESLint                                                             | YES                                                                     | PATH only — reads from disk                                                |

### Notes

**A — `absolute_path` does not fit the frame, and extending it would be a
mistake.** Its premise is about a *tool argument*, not about a file on disk.
Relative paths in Bash are normal, correct and everywhere; a Bash-aware version
would have to block `ls src/`. Its own `get_acceptance_tests()` docstring also
records that Claude Code resolves `file_path` to absolute *before* PreToolUse
dispatch, so the handler already almost never fires from a real session and
exists for non-Claude-Code socket clients. **Task 3.1 currently lists
`absolute_path` among the handlers that "get most of the value" from the shared
utility. It should be removed from that list.**

**B — `daemon_docs_guard` is a read-path guard.** `cat .claude/hooks-daemon/CLAUDE/PlanWorkflow.md` is exactly the mistake it exists to
catch and is invisible to it, so the premise *is* violable via Bash — but this
is a side-door on reading, not on writing, so a "is this Bash call a file
write?" utility does nothing for it. Closing it needs a read-target detector
instead. Worth recording as out of scope rather than as a blind row.

**C — `plan_time_estimates` needs content.** Its `matches()` gates on the path
(`/Plan/` and `.md`, minus journal files) and then runs
`_has_unexempted_estimate(content)` line by line. Task 3.1's task text lists it
alongside the path-keyed handlers; that is wrong. The path gate is restorable
from a path-only utility, the decision is not.

**D — `sed_blocker`'s partial coverage is incidental, not designed.** Its Bash
branch regexes the raw command string, and `_SED_WITH_EXECUTION_FLAG`
(`\bsed\s+-[a-z]*[ien]`) is unanchored — so a stream editor with an execution
flag sitting in a *heredoc body* destined for a `.sh` file is matched, and the
Write-branch premise is upheld by accident. Verified live: an earlier probe in
this task was denied for exactly that reason. The gap is the flagless form.
`_SED_AS_COMMAND_HEAD` is compiled without `re.MULTILINE`, so its `^` is
start-of-string only and a body line beginning with a flagless invocation
matches neither pattern:

| Heredoc body line | `_SED_AS_COMMAND_HEAD` | `_SED_WITH_EXECUTION_FLAG` |
| ----------------- | ---------------------- | -------------------------- |
| with `-i`         | no                     | **yes**                    |
| flagless          | no                     | no                         |

So `cat > x.sh <<EOF` carrying a flagless invocation writes a script the
Write-branch would have blocked. Narrow, but real.

**E — `validate_instruction_content` has a trap for Task 3.1.** `matches()` is
path-only, so a path-only utility would make it fire — but `handle()` has an
explicit `else: return HookResult(decision=Decision.ALLOW, reason="Tool type not handled by validator")` for any tool that is not Write/Edit. Routing a Bash
event to it without also supplying content yields a **silent ALLOW**, which
reads as a pass. Any handler migrated onto the shared utility must have its
`handle()` audited for this shape, or the migration converts a blind spot into
a false all-clear, which is worse.

## Corrected PATH / CONTENT split

Three groups, not two. Counts sum to 21.

**Group 1 — PATH only (7). A path-only utility restores these completely.**

`lock_file_edit_blocker`, `markdown_organization`, `plan_workflow`,
`tdd_enforcement`, `lint_on_edit`, `markdown_table_formatter`,
`validate_eslint_on_write`.

`tdd_enforcement` is in this group with one caveat: it passes content to
`strategy.should_skip(file_path, content)`, so a generated-file marker in the
body would be missed. That makes it stricter, not looser, and the premise
(a test file must exist for this path) is decided from the path.

**Group 2 — PATH-gated but CONTENT-required (11). The utility restores the
gate; the decision still needs the bytes.**

`british_english`, `comment_changelog`, `comment_size`, `error_hiding_blocker`,
`plan_qa_edit`, `plan_time_estimates`, `qa_suppression`,
`security_antipattern`, `sensitive_content`, `validate_instruction_content`,
`recovery_cron_advisor`.

For heredocs the bytes are already present in the command string, so this group
is not out of reach — it is out of reach *for redirect and `tee` routes only*.

**Group 3 — outside the frame (3).**

`absolute_path` (premise is about a tool argument; extending it would block
ordinary shell usage), `daemon_docs_guard` (read path, not write path),
`sed_blocker` (command-anchored by design; its Write branch is a secondary
rule that is incidentally mostly covered).

**Changes from the provisional split in the task brief:** `lint_on_edit` and
`validate_eslint_on_write` move from CONTENT to PATH; `markdown_table_formatter`
is confirmed PATH; `recovery_cron_advisor` moves from PATH to BOTH;
`plan_time_estimates` is confirmed BOTH (and must be removed from the
path-keyed list inside Task 3.1's text); `absolute_path` moves out of the frame
entirely.

## Severity ranking, worst first

**1. `sensitive_content` — a term enters the tree and nothing ever reports it.**
The handler already reasons carefully about Bash, but only for git metadata:
`_git_metadata_haystacks` returns the command only when `_writes_git_metadata`
is true. A file written by heredoc, redirect or `tee` is not a haystack at all.
Its own docstring calls the commit-message surface "the one leak surface that
cannot be undone without rewriting published history" — the file surface has
that same property once pushed, and it is the surface the handler was built for
first. This repository has already performed one history rewrite that needed
`--path-rename` for three files whose names carried terms; a single heredoc can
silently reintroduce what that rewrite removed, and both this handler and the
whole-tree scanner then report all-clear. Plan 00252 covers content arriving at
the commit gate via `mv`; a heredoc lands it directly, so the two routes need
to be checked together or the fix has a hole.

**2. `lint_on_edit` and `validate_eslint_on_write` — guards that DENY, going
silent, and they are the cheapest to fix.** Both tell the agent in
`get_claude_md()` that a failure denies the tool call. Via Bash the file lands
with no check and no advisory, so the agent's model ("my writes are linted")
is false precisely when it is most trusted. Consequence: broken code sits on
disk and surfaces at the QA gate or in CI instead of at the keystroke. They are
ranked this high mostly on cost — both are Group 1, so a path-only utility
fixes them outright with no content plumbing at all.

**3. `security_antipattern` and `error_hiding_blocker` — a successful write
reads as evidence of safety.** The plan's own verification confirmed live that
a `shell=True` call and a hardcoded AWS key pass via heredoc having been denied
via Write. The damage is not just the unblocked construct; it is that the
resident guidance states these constructs "are blocked", so an agent treats a
clean write as a security signal. That inference is wrong on the Bash route and
the agent has no way to know which route it took mattered.

**4. `tdd_enforcement` — the only chance to fire is at creation, and it is
gone.** The gate is "this production file must not come into existence without
a test". Once the file exists by the Bash route, the gate can never fire for
that file again — a later `Edit` is not a creation. There is no batch
equivalent that walks the tree looking for untested source files, which is the
exact corollary spelled out in Core Standard 15 (DBF): a write-time rule does
not cover what is already on disk.

**5. `lock_file_edit_blocker` — damage lands on someone else's machine.** A
hand-written `package-lock.json` produces checksum mismatches and a broken
dependency graph that surfaces at install time in CI or for a teammate, not in
the session that caused it. Group 1, so cheap to close.

**6. `qa_suppression` — the written artefact is itself a blinding device.** A
`noqa` placed by heredoc suppresses a real finding permanently, and QA then
goes green *because of* the thing that should have been blocked. Every other
entry in this list leaves the underlying problem detectable by some later
check; this one removes the later check too.

**7. `markdown_organization`'s memory ban — enforced, but only partly, which
is worse than not at all.** This project has explicitly opted into
`allow_untracked_claude_memory: false`, and the handler closes the redirect and
`tee` routes. It does not close `cp`, `mv`, `install`, `dd of=`, `>|`, a
quoted target containing a space, a variable target, or a script that opens the
file itself. A policy believed to be enforced, that is enforced against two
spellings out of many, is trusted more than it deserves.

**8. The document-quality group — real but recoverable.** `plan_qa_edit`,
`plan_time_estimates`, `validate_instruction_content`, `comment_changelog`,
`comment_size`, `british_english`, `plan_workflow`. These are ranked last not
because the drift is acceptable but because a batch equivalent exists or is
easy: `plan_qa_sweep` already re-checks plan documents at session start on
both surfaces precisely so that violations arriving by a non-Write route are
still reported. That is the pattern the other groups lack.

## `markdown_organization._bash_memory_write_target` — what it does and does not cover

The only existing bash-write-target detector, at
`src/claude_code_hooks_daemon/handlers/pre_tool_use/markdown_organization.py:653`.
Introduced by Plan 00131 to close `cat > <memory-path>` specifically.

### How it finds the target

Two unanchored regexes over the raw command string, defined at lines 61-62:

```python
_BASH_REDIRECT_TARGET_RE = re.compile(r">>?\s*([^\s|&;<>]+)")
_BASH_TEE_TARGET_RE = re.compile(r"\btee\b(?:\s+-[^\s]+)*\s+([^\s|&;<>]+)")
```

Every match is stripped of surrounding quotes and tested with
`_is_claude_memory_path`, which is a plain substring test for
`/.claude/projects/` and `/memory/`. The first hit is returned. `matches()`
consults it *before* the Write/Edit tool-name test (line 693), which is the
structural move Task 3.1 wants to generalise. There is no shell parsing, no
tokenisation, no path resolution and no `cwd` awareness anywhere in it.

### Coverage, measured

Each row below was run against the two live patterns.

| Command shape                                   | Target found              | Verdict                                     |
| ----------------------------------------------- | ------------------------- | ------------------------------------------- |
| `cat > /abs/path.md <<'EOF'`                    | `/abs/path.md`            | covered                                     |
| `cat <<'EOF' > /tmp/a.md` (heredoc first)       | `/tmp/a.md`               | covered                                     |
| `cmd >> /tmp/a.md` (append)                     | `/tmp/a.md`               | covered                                     |
| `echo x` piped to `tee /tmp/a.md`               | `/tmp/a.md`               | covered                                     |
| `sudo tee /etc/hosts`                           | `/etc/hosts`              | covered                                     |
| `python3 gen.py 2> /tmp/err.log` (fd-qualified) | `/tmp/err.log`            | covered, unintentionally                    |
| `~/`-prefixed memory path                       | matches by substring luck | covered for memory only; no tilde expansion |
| `tee -a /tmp/a.md /tmp/b.md` (two targets)      | `/tmp/a.md` only          | **partial** — second target lost            |
| `printf x >\| /tmp/a.md` (noclobber override)   | none                      | **missed**                                  |
| `cat > '/tmp/my file.md'` (space in path)       | `'/tmp/my`                | **missed** — truncated at the space         |
| `cat > "$OUT"` (variable target)                | `"$OUT"`                  | **missed** — returned unexpanded            |
| `dd if=/dev/zero of=/tmp/a.md`                  | none                      | **missed**                                  |
| `cp` / `mv` / `install` to a target             | none                      | **missed**                                  |
| a heredoc'd script that opens the file itself   | none                      | **missed**                                  |
| relative target (`> notes/x.md`)                | `notes/x.md`              | returned, but never resolved against cwd    |
| `echo 'the arrow > file thing'` (quoted prose)  | `file`                    | **false positive**                          |

The false-positive row is not hypothetical. While gathering evidence for this
document, a `python3 -c` probe was denied by this handler because a
memory-shaped path appeared as a **quoted string literal inside a heredoc
body** — no write to it was taking place. The detector has no way to tell a
redirect from the characters `>` and a filename appearing in prose or in data.

### What this means for Task 3.1

Generalising it as-is would take a false-positive rate that is tolerable
against one narrow substring test (`/.claude/projects/` plus `/memory/`) and
apply it to every path in the tree. `lock_file_edit_blocker` would start
denying commits whose message mentions a redirect into a lock file;
`tdd_enforcement` would fire on prose. The narrow matcher is safe *because* it
is narrow. A generalised version needs at least: quote-aware and heredoc-aware
scanning so string bodies are excluded, `shlex`-style tokenisation for
quoted and spaced targets, all of `>|`, `cp`, `mv`, `dd of=` and `install`, and
resolution of relative targets against the session `cwd`. That is a materially
larger piece of work than "move this method to a shared module", and Task 3.1
should be re-scoped to say so before the option is compared against 3.2.

## Not determined

Recorded explicitly rather than guessed.

- **Whether the Bash PreToolUse payload carries anything beyond `command`.**
  If Claude Code supplies a `cwd` field, relative-target resolution becomes
  straightforward; if not, it cannot be done reliably. I read handler source
  only, not a captured real payload. `scripts/debug_hooks.sh` would settle it.
- **Whether firing the PostToolUse handlers on a Bash write is performant.**
  `lint_on_edit` shells out to a linter per file. A single Bash command can
  write many files, so the Group 1 restoration might mean many synchronous
  linter invocations on one event. I did not measure this, and it could change
  the recommendation for handlers 18 and 21.
- **Whether `british_english`'s code-block skipping covers inline backticks or
  only fenced blocks.** Affects how noisy it would be if extended, but not its
  verdict.
- **The behaviour of `comment_size`'s grow/shrink tiering under a Bash write.**
  Its tiering compares against the previous state. At PreToolUse the old file
  is still on disk so the before-state is obtainable, but I did not trace
  whether `_region_after` can be built without `old_string`/`new_string`. Row 4
  is marked BOTH on the strength of the content requirement alone.
- **Whether Plan 00252's staged-content work already provides a content
  accessor** that Group 2 could reuse. The plan's Dependencies section says to
  sequence after it; I did not read 00252.
