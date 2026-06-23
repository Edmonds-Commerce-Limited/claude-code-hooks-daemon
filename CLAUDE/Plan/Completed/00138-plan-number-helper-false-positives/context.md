# Context: plan_number_helper False-Positive Instance

## The specific instance

While the main session was working on Plan 00135
(`CLAUDE/Plan/00135-event-driven-send-keys-injection`) — rewriting that plan's
folder and probing the daemon — the `plan_number_helper` handler repeatedly and
wrongly BLOCKED commands that operated on the **specific, already-known** plan
00135 folder. These were not attempts to discover the next plan number; they
referenced a numbered folder that already existed.

## Confirmed false-positive commands (transcript evidence)

All of the following were blocked in a real session when they should NOT have
been:

- `find CLAUDE/Plan/00135-event-driven-send-keys-injection -maxdepth 1 -type d`
  → blocked
- `find /workspace/CLAUDE/Plan/00135-x -maxdepth 1 -name "PLAN*.md"`
  → (relative form blocked)
- `printf '{"...command":"... CLAUDE/Plan/00135-x ..."}'`
  (any `echo`/`printf` mentioning a specific numbered folder) → blocked
- `git mv CLAUDE/Plan/00135-x/PLAN.md CLAUDE/Plan/00135-x/PLAN-v1.md`
  → blocked as collateral (batched with a matching `printf`/`find` in the SAME
  Bash call — Claude Code cancels all sibling tool calls when one is denied)
- `ls CLAUDE/Plan/ | grep -i 135`
  → blocked as collateral

## Why they were hit

The work was operating ON Plan 00135's folder (a plan rewrite) and probing the
live daemon with `printf` payloads whose JSON `command` field mentioned
`CLAUDE/Plan/00135-x`. Both kinds of command merely *reference a specific
numbered folder*; neither enumerates the plan directory to find the highest
number.

## The two root causes (verified by probing live `matches()`)

1. **Pattern #2 (find)** — `rf"find\s+{re.escape(plan_dir)}"` matches
   `find CLAUDE/Plan/<ANY-subpath>`, including a find scoped to ONE specific
   plan folder. It must only match a find on the plan dir ITSELF.

2. **Pattern #3 (glob_echo / glob_printf)** —
   `rf"echo\s+[^;&|]*{re.escape(plan_dir)}/[0-9\*\[]"` (and the `printf` twin):
   the char class `[0-9\*\[]` matches a BARE DIGIT, so any `echo`/`printf`
   mentioning `CLAUDE/Plan/0...` (i.e. any numbered folder like `00135`) falsely
   matches. It must require an actual glob metacharacter (`*`, `[`, `?`).

## Shared root cause

Conflating "a reference to a specific numbered folder (e.g. `00135-name`)" with
"a discovery glob / enumeration of the plan directory." The handler must fire
ONLY on genuine discovery.

---

## Second handler: `validate_plan_number` (priority 41, Write/Edit + mkdir)

### The specific instance

Editing the PLAN.md of an ALREADY-EXISTING plan folder
(`CLAUDE/Plan/00135-event-driven-send-keys-injection/PLAN.md`) triggered the
advisory warning:

```
PLAN NUMBER INCORRECT
You are creating: CLAUDE/Plan/135-event-driven-send-keys-injection/
Expected next number: 139
Use the correct plan number: 139
```

### Two bugs visible there

1. It treated an EDIT/rewrite of an existing plan's PLAN.md as if a NEW plan was
   being created. It must not warn when the target plan folder already exists —
   only genuinely-new plan folders should be number-validated.
2. It rendered the folder as `135-...` (stripped the zero-padding from
   `00135-...`) in its message — a display bug caused by `int()` dropping the
   leading zeros. The real folder is `00135-`.

### Root causes

3. `matches()` fired on any Write/mkdir whose path matched
   `CLAUDE/Plan/(\d+)-name`, with no existence check.
4. `handle()` displayed `int(plan_number)`, stripping leading zeros.

Same disease as the first handler: conflating "operating on a specific,
already-known numbered folder" with "creating/discovering a NEW plan number".
