> **FILED AS PLAN 00260 — verification note added 2026-08-19.**
>
> This is the original field report, preserved below. It was an INPUT, not a
> finding: every claim was checked against the v3.54.0 tree and against the live
> daemon socket before Plan 00260 was written. Verdicts:
>
> | #   | Claim                                                                                      | Verdict                                                    | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
> | --- | ------------------------------------------------------------------------------------------ | ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
> | 1   | `sed -n` is blocked, though guidance implies otherwise                                     | **CONFIRMED**                                              | `_SED_WITH_EXECUTION_FLAG` is `\bsed\s+-[a-z]*[ien]` (`sed_blocker.py:53-56`) — `n` is in the class. Live probe of `sed -n '1,5p' README.md` → `deny`.                                                                                                                                                                                                                                                                                                                                               |
> | 2   | A flagless `sed` at a command head is blocked too                                          | **CONFIRMED**                                              | `_SED_AS_COMMAND_HEAD` matches `sed` at the start or after `;`, `&&`, `\|\|` (`:45-48`). Live probe of `sed '1,5p' README.md` → `deny`.                                                                                                                                                                                                                                                                                                                                                              |
> | 3   | `get_claude_md()` omits both, and its "Allowed (read-only…)" heading misleads              | **CONFIRMED**                                              | `sed_blocker.py:369-387`; the blocked list names only `-i`/`-e`, xargs, and `.sh` writes.                                                                                                                                                                                                                                                                                                                                                                                                            |
> | 4   | "Only `sed` as a pure stdout pipe stage survives"                                          | **REFUTED — the handler is STRICTER than the report says** | A pipe stage is denied unless a `grep` or `echo` also appears in the command: `_is_safe_readonly_command` (`:244-285`) falls through to `return False`. Live probe: `cat README.md` piped to `sed 's/x/y/'` → **deny**; the same command with a trailing `grep z` → allowed. Intentional and tested (`test_matches_bash_sed_in_pipeline_without_grep`, `test_is_safe_readonly_command_rejects_cat_pipe_sed`). The guidance's sole "allowed" example passes only because it happens to end in `grep`. |
> | 5   | The `bypassPermissions` system-reminder steers agents to Bash/heredocs over `Write`/`Edit` | **CONFIRMED**                                              | Reproduced verbatim in the verifying session's own context, including its `sed -n` recommendation.                                                                                                                                                                                                                                                                                                                                                                                                   |
> | 6   | 21 handlers key on `ToolName.WRITE`/`ToolName.EDIT`                                        | **CONFIRMED — count exact**                                | `grep -rln` over `pre_tool_use/` + `post_tool_use/` returns exactly 21 files.                                                                                                                                                                                                                                                                                                                                                                                                                        |
> | 7   | A heredoc-written file is seen by none of them                                             | **CONFIRMED, and broader than reported**                   | Live probes returned NO decision for heredoc/redirect/`tee` writes carrying a `shell=True` call, a hardcoded AWS key, a QA suppression, an error-suppression idiom, a new `src/` file with no test, a relative path, a lock-file overwrite, and a misplaced markdown file.                                                                                                                                                                                                                           |
> | 8   | `markdown_organization` is the only handler inspecting Bash for write targets              | **CONFIRMED**                                              | `_BASH_REDIRECT_TARGET_RE` / `_BASH_TEE_TARGET_RE` (`markdown_organization.py:58-62`) and `_bash_memory_write_target` (`:653-663`), scoped to Claude auto-memory paths only.                                                                                                                                                                                                                                                                                                                         |
>
> Minor inaccuracy, immaterial: the report calls the comment at `:50-52` a "class
> docstring"; it is a module-level comment. Its content is quoted correctly.
>
> Not verified: the reporter's environment details, which are external to this
> repository. The client project name has been REDACTED from the body below — it
> is an entry in this repo's gitignored secret word list, and the report reached
> this folder by `mv`, a route no write-time handler inspects. That is a live
> instance of the very defect class Plan 00252 is filed against.
>
> One consequence worth recording, because it shaped the filing: the word `sed`
> could not appear in this plan's folder slug, since the handler matches it
> inside `sed-blocker` and would deny every later `git add`/`git mv` naming such
> a folder. That false-positive matching is deliberate (see `CLAUDE.md`) and must
> not be "fixed" — it is what makes acceptance-testing the blocking handlers
> possible.

---

# Bug report — claude-code-hooks-daemon v3.53.1

**Two findings, one small and one architectural.** They were found together but
are independent; file as two issues if that suits you better.

**Reporter environment**: dogfooding client install, project name redacted
(it is an entry in this repo's gitignored secret word list),
daemon v3.53.1 RUNNING, Claude Code session in `bypassPermissions` mode
(deliberate and permanent for this project — see Finding 2).

---

## Finding 1 — `sed_blocker`'s injected guidance omits `-n` and the bare

command-head case

**Severity**: low (documentation only — the *behaviour* is correct)
**File**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/sed_blocker.py`

### Expected

A reader following only the resident `CLAUDE.md` guidance believes
`sed -n '130,150p' <file>` is permitted. It is a read: not in-place, not `-e`,
and the guidance's own heading says read-only sed is allowed.

### Actual

It is denied:

```
$ sed -n '130,150p' service/files/vms/ansibleRunner/usr/local/bin/playbook-run

BLOCKED: sed is forbidden. Use Edit tool (or parallel Haiku agents for bulk).
```

### Root cause

The code blocks `-n` deliberately — `sed_blocker.py:53-56`:

```python
_SED_WITH_EXECUTION_FLAG = re.compile(
    r"\bsed\s+-[a-z]*[ien]",     # <- 'n' is in the class, intentionally
    re.IGNORECASE,
)
```

and `_SED_AS_COMMAND_HEAD` (`:45-48`) additionally blocks `sed` at the start of
a command *regardless of flags*, so a flagless `sed '130,150p' file` is denied
too. Only `sed` as a pure stdout pipe stage survives. The class docstring
(`:50-52`) states this correctly: "in-place / script / quiet flag (-i, -e, -n)".

But `get_claude_md()` (`:375-380`) publishes only two of the three:

```
**Blocked**:
- `sed -i` / `sed -e` (in-place file editing via Bash tool)
- `grep -rl X | xargs sed -i` (mass file modification)
...
**Allowed** (read-only, no file modification):
- `cat file | sed 's/x/y/' | grep z` (pipeline transforming stdout only)
```

Two gaps: `-n` is absent from the blocked list, and the "Allowed" heading says
**read-only** when the actual rule is **pipe-stage only**. Those two together
positively suggest the wrong conclusion rather than merely omitting the right
one.

### Suggested fix

In `get_claude_md()`:

- add `sed -n` to the blocked list, and a line for "any `sed` as a command head,
  with or without flags";
- retitle the allowed section from "read-only, no file modification" to
  something like "as a pipe stage only (stdout transformation)".

No behaviour change; the handler is right, only its self-description is thin.

### Why it mattered here

The Claude Code harness, in `bypassPermissions` mode, injects a
`system-reminder` that names `sed -n` *by hand* as the preferred way to read
files (see Finding 2). An agent reconciling that against the resident guidance
concludes `sed -n` is the permitted read form. It isn't, and the denial also
cancels every sibling tool call batched with it.

---

## Finding 2 — the harness now actively directs agents away from `Write`/`Edit`,

which is where 21 handlers do their work

**Severity**: design question, not a defect
**Applies to**: any project whose sessions run in `bypassPermissions`

### The instruction

Claude Code injects this as a `system-reminder` when the session is in
`bypassPermissions` mode (verbatim):

> While bypass permissions mode is active:
>
> Do your work through the Bash tool wherever it can accomplish the job: read
> files with `cat`, `head`, or `sed -n`, search with `grep` and `find`, and make
> file changes with `sed`, heredocs, or short scripts, rather than using the
> dedicated Read, Edit, or Write tools. Fall back to a dedicated tool only when
> Bash genuinely cannot do the job.

It is not from the daemon, not from this project's config, and cannot be
disabled from either — it arrives with the session. **In this project
`bypassPermissions` is deliberate and permanent**, so the instruction is a
standing condition of every session, not a one-off.

### Why it matters to this daemon specifically

**21 handlers key on the `Write`/`Edit` tool names.** Measured on v3.53.1:

```
$ grep -rln "ToolName.WRITE\|ToolName.EDIT" \
    src/claude_code_hooks_daemon/handlers/pre_tool_use/ \
    src/claude_code_hooks_daemon/handlers/post_tool_use/
```

Among them: `security_antipattern`, `sensitive_content`, `error_hiding_blocker`,
`qa_suppression`, `lint_on_edit`, `validate_eslint_on_write`, `tdd_enforcement`,
`lock_file_edit_blocker`, `comment_changelog`, `comment_size`, `plan_qa_edit`,
`plan_time_estimates`, `validate_instruction_content`, `markdown_organization`,
`absolute_path`.

A file written by `cat > f <<'EOF' ... EOF` is seen by **none** of them. At
`PreToolUse` the daemon sees a `Bash` call whose `tool_input` is a command
string — no `file_path`, no `content` — and there is no post-write lint. A
heredoc carrying a hardcoded credential, a `|| true`, a `# noqa`, or a source
file created before its test all pass unexamined.

`sed_blocker` and `pipe_blocker` *do* fire, because they match the command
string. That catches the two idioms the instruction names by hand, which is
what makes this easy to mistake for a `sed` problem. It isn't: those two are
incidental, and the general case ("heredocs, or short scripts") is uncovered.

### The project already knows this gap exists

`markdown_organization` is the only handler that also inspects Bash for
write-shaped commands — `markdown_organization.py:58-59`:

```python
# Shell write-to-file patterns used to close the bash side-door to memory paths.
# Redirect (> / >>) and tee targets are WRITES; reads (cat/grep/less path) have no
```

One handler, one narrow path class (Claude auto-memory files, Plan 00131). The
design assumption everywhere else is that file mutation arrives as
`Write`/`Edit` — a reasonable assumption until a harness instruction inverts it
for the whole session.

### What we are NOT asking for

Not a blanket "parse shell redirects in every handler". That is a large surface
for a modest gain, and shell is genuinely hard to parse safely — the existing
`pipe_blocker` guidance shows how much nuance one command string already needs
(`$( )` nesting, quoted vs unquoted heredocs, git `-m` exemptions).

### What might actually help

Offered as options, not a prescription:

1. **A single shared "is this Bash call a file write?" utility**, generalising
   what `markdown_organization._bash_memory_write_target` already does
   (redirect + `tee` targets), which any handler could opt into. Handlers that
   care about *paths* (`markdown_organization`, `lock_file_edit_blocker`,
   `absolute_path`, `tdd_enforcement`, `plan_time_estimates`) get most of the
   value for little cost, since they only need the target path, not the content.
2. **A `bypassPermissions`-aware advisory** at session start, noting that the
   harness will push toward Bash-first editing and that the project's write-time
   guards do not cover it. Cheap, honest, no parsing required — it converts a
   silent gap into a known one.
3. **Documenting the boundary explicitly** in the handlers' own
   `get_claude_md()` output: "this handler sees `Write`/`Edit` only; a file
   written via a Bash heredoc is not checked." Several handlers already document
   their exclusions carefully (`comment_changelog`'s scope note, `lint_on_edit`'s
   "a linter that is not installed never blocks"), so this fits the house style.
   It also directly serves DBF — an agent that knows a guard is blind can
   compensate; one that assumes coverage cannot.

Option 3 alone would have prevented the confusion that produced this report.

---

## Reproduction

Both findings are observable without any special setup:

```bash
# Finding 1 — denied, though guidance implies it is allowed
sed -n '1,5p' README.md

# Finding 2 — a file written this way is seen by no write-time handler
cat > /tmp/demo.py <<'EOF'
import subprocess
subprocess.run("echo hi", shell=True)   # security_antipattern would DENY this
EOF                                      # via Write/Edit; via heredoc it lands
```

(The second is a demonstration of scope, not an exploit — it writes to `/tmp`.)

## Attachments to include when filing

Run and attach:

```bash
.claude/hooks-daemon/scripts/debug_info.py /tmp/hooks-daemon-bug-report.md
```

Submit to: <https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues>
