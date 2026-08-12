# Hooks daemon — field feedback

**Source**: one long working session (2026-08-10 → 08-12) in `/workspace`, a documentation and
planning repo. Heavy `Write`/`Edit`/`Bash` use, four plans created or edited, ~10 commits, five
subagents. Not a code repo, so the language-specific blockers (`security_antipattern`,
`qa_suppression`, `tdd_enforcement`, `error_hiding_blocker`) were never exercised — nothing
below says anything about those.

Findings are ordered by how much they cost. Two of my initial three "false positives" did not
survive Joseph's push-back and have been re-rated; that re-rating is kept visible below rather
than quietly dropped, because the mis-rating is itself a lesson about how this kind of report
goes wrong.

---

## 1. `pipe_blocker` scans heredoc bodies, then quotes your prose back as a command

**Severity: low impact, high embarrassment. The block is defensible; the *output* is the bug.**

### What happened

Appending a journal entry with `cat >> file <<'EOF' … EOF`. The prose being written *described*
two earlier pipe blocks and therefore contained the literal characters of a pipe-to-pager. The
handler matched inside the heredoc body and denied the write.

So: **writing a journal entry about a blocked pattern triggers the block.** The document
describing the guardrail cannot be written past the guardrail.

### Joseph's read, which I agree with

> "the pipe blocker, its a trikcy one and it errs on the side of caution, but giving you your
> own command back is just silly"

Exactly the right split. Properly distinguishing heredoc content from executable text means
real shell parsing, and erring toward caution is the correct trade for a safety handler. **The
block is not the defect. The remediation output is.**

### The actual defect

The block ran my heredoc prose through the "here's how to fix it" template and emitted several
hundred lines of my own English wrapped in shell scaffolding — including:

```
  • If it is cheap/safe to pipe, add it to extra_whitelist in .claude/hooks-daemon.yaml:

    pipe_blocker:
      extra_whitelist:
        - "^the\\b"
```

It extracted `the` as the command name, because that was the first word of a sentence. It then
offered `set -o pipefail` followed by three paragraphs of prose, and suggested I redirect my
own narrative to `$TEMP_FILE`.

The effect is worse than the block: a correct, defensible safety decision was presented in a way
that reads as broken. It also burned a large amount of context re-quoting text I had just
written.

### Suggested fixes, cheapest first

1. **Sanity-check before templating.** If the matched "command" does not parse as a command —
   no recognisable binary as the first token, or it exceeds some sane length — emit the block
   reason alone and skip the remediation template entirely. Cheap, and it fixes the
   embarrassment without touching detection.
2. **Cap the echoed command.** Never echo more than N characters of the offending command back.
   The full text is rarely what makes a block actionable.
3. **Heredoc awareness** (harder, optional). Strip `<<'EOF' … EOF` bodies before pattern
   matching. Worth it only if this recurs; (1) and (2) remove nearly all the pain.

### Workaround in the meantime

Write the content to a scratch file with the `Write` tool, then `cat scratch >> target`. No pipe
in the command line, so the handler never sees it.

---

## 2. `error`/`warning` keyword advisory — **re-rated: working as intended**

**Severity: none. I called this a false positive and I was wrong.**

Joseph's push-back:

> "the error warn - it s just a warn so i think this is oding its job?"

Correct, and the distinction matters. **An advisory has no false-positive failure mode in the
sense a blocker does.** It cost nothing but a few tokens and a second look at output I might
otherwise have skimmed — which is precisely its purpose. Rating it alongside a real defect
inflated the count and made my report worse, which is the classic way this kind of write-up
goes wrong: an author who wants findings starts grading noise as bugs.

It fired roughly six times in the session. Every one was cheap, and at least one caused me to
re-read output properly.

### One narrow precision refinement, offered as optional

The only fires that are *guaranteed* to carry no signal are those where the trigger keyword
appears in **the command itself** rather than only in the output — e.g.:

```bash
grep -n "plan-doc-size\|18,000\|25,000\|35,000" CLAUDE.md   # matched a doc line containing "warning"
gh api ... # listing containing behat-error-handling-context
```

In both cases the keyword was in the search pattern or a repo name, so the advisory could not
have been telling me anything. **Skipping when the matched keyword also appears in the command
string** would remove the deadest fires and keep every fire that could carry signal.

Genuinely optional. If it is not obviously easy, leave it — the current behaviour is fine and I
should not have listed it as a problem.

---

## 3. No verdict log — the daemon cannot report on itself

**Severity: the most consequential gap here, and not a bug — a missing capability.**

The daemon makes hundreds of decisions per session and **persists none of them.** What exists:

```
untracked/logs/hooks/notifications.jsonl        54 entries, all notification_type=idle_prompt
untracked/logs/hooks/subagent_completions.jsonl 328K of transcripts
```

No record of which handler fired, on which tool call, with what verdict. Nothing in
`hooks-daemon.yaml` enables one. Decisions are emitted to the agent and discarded.

### Why it matters beyond tidiness

Every interesting question about the daemon is currently unanswerable:

- Which handlers actually earn their keep, and which have never fired?
- What is the real false-positive rate, per handler?
- Is a handler in `block` mode that should be `advise`, or vice versa?
- Did adding a handler change anything measurable?

It also blocks any published evidence about the tool's effectiveness, since there is no data to
publish. Right now the only way to answer "does this work" is anecdote — which is exactly what
the daemon exists to replace elsewhere.

### Suggested shape

An append-only `verdicts.jsonl`, one line per handler decision:

```json
{"ts":"...","session":"...","event":"PreToolUse","tool":"Bash","handler":"pipe_blocker",
 "verdict":"deny","rule":"pipe-to-pager","mode":"block"}
```

Cheap to write, trivially aggregatable, and it makes every question above a one-liner over the
file. Add an `--overridden` marker if a user escape hatch (`MUST_STASH_BECAUSE=` and friends)
was used — an override is the strongest available signal that a rule is mis-tuned.

---

## 4. `recovery_cron_advisor` cannot be told "no" for a session

**Severity: low, and there is already a config switch — this is a discoverability note.**

The advisory fired roughly six times across the session — on every `PLAN.md` progress edit and
on `mkplan.bash`. In every case the correct action was to ignore it, because Joseph had earlier
said "stop cron" as a standing instruction.

The handler has no way to know that, which is fair. But six identical advisories against a live
user instruction to the contrary is noise, and noise is how advisories get ignored wholesale —
including the ones that matter.

`CLAUDE.md` documents the opt-out and it is worth knowing it exists:

```yaml
handlers:
  post_tool_use:
    recovery_cron_advisor:
      enabled: false
```

**Possible improvement**: the progress-phase reminder is already rate-limited per plan. The
creation and completion phases are not. Rate-limiting those the same way, or suppressing the
advisory for the rest of a session after N ignored fires, would cost nothing and stop the
drip.

---

## 5. `markdown_table_formatter` rewrites cause one stale-string `Edit` failure

**Severity: minor, already mitigated, one real occurrence.**

The formatter renumbers ordered lists (`1.` `2.` `3.` ↔ `1.` `1.` `1.`) and re-pads table
columns after every `.md` write. One `Edit` this session failed with a string mismatch because
the formatter had renumbered a list between my writing it and my editing it.

The daemon already warns about exactly this in its PostToolUse message, so the failure mode is
known and documented, and recovery was a single `grep` to re-read the region. Noting it only as
a real-world confirmation that the warning earns its place — **not** as something to change. If
anything, the advisory could name the specific transformations applied (list renumbering, pipe
alignment) so the retry is targeted rather than a re-read.

---

## What worked well

Worth stating, because a feedback document that lists only problems misrepresents the session.

- **`plan_qa_edit` / `plan-doc-size` was right every time it fired.** Three advisories on one
  plan, and on all three occasions I was genuinely writing journal narrative into a `PLAN.md`.
  The two documented remedies — relocate to `JOURNAL/`, or split the plan — were both correct
  and I used both, ending with a clean split into a new plan. **The rule's stated rationale
  (PLAN.md is re-read in full every session, so every KB is a recurring tax; the journal is only
  ever sampled) is the thing that made it persuasive rather than annoying.** Handlers that
  explain *why* get complied with; handlers that just say no get worked around.
- **`plan-qa --check-staged` ran clean before every commit** and caught nothing only because
  the edit-stage rules had already caught things earlier. That is the pipeline working as
  designed.
- **`mkplan.bash`** did the right thing atomically — counter, folder, scaffold, and a reminder
  about the README row it deliberately does not do for you.
- **`pipe_blocker`'s two legitimate catches** would both have silently truncated output I needed.
  The finding in §1 is about presentation, not about whether the handler should exist.
- **The block messages are, in general, unusually good** — they state what was blocked, why, and
  what to do instead. §1 is notable precisely because it is the exception.

---

## Summary

| #   | Item                                             | Rating                            | Action                                                         |
| --- | ------------------------------------------------ | --------------------------------- | -------------------------------------------------------------- |
| 1   | `pipe_blocker` echoes heredoc prose as a command | Real defect, cosmetic impact      | Sanity-check or cap the echoed command before templating       |
| 2   | `error`/`warning` keyword advisory               | **Working as intended**           | Optional: skip when the keyword is in the command itself       |
| 3   | No verdict log                                   | Missing capability, highest value | Add append-only `verdicts.jsonl`                               |
| 4   | `recovery_cron_advisor` repetition               | Minor noise                       | Rate-limit creation/completion phases, or set `enabled: false` |
| 5   | Formatter causes stale-string `Edit` failures    | Minor, already documented         | Optionally name the transformations applied                    |

One genuine defect, one missing capability, two minor irritations, and one thing I got wrong.
