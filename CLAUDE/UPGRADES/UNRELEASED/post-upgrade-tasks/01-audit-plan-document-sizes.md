# Task: Audit plan-document sizes before the new block tier bites

**Type**: workflow-change
**Severity**: recommended
**Applies to**: ≤v3.49.1 (any project using `plan_workflow` with a plan directory)
**Idempotent**: yes

## Why

This release adds `plan-doc-size` (Plan 00190), which enforces tiered read-cost
limits on plan **documents**. It is **on by default**, and its top tier
**denies** an edit that would push a `PLAN.md` past 35,000 bytes or 900 lines.

The motivation: a `PLAN.md` is read in full at the start of every session that
touches the plan, so every kilobyte is a recurring context cost paid before any
work starts. A `JOURNAL/` day-file is only ever sampled — tailed, grepped, or
read by a sub-agent — so journals are unbounded by design and exempt.

The block is deliberately narrow: **only an edit that GROWS the file can be
denied**. Shrinking is silent and a same-size edit such as ticking a checkbox
only advises, so an already-oversized plan can always be updated and refactored
down. You are therefore never trapped — but if your project has large plans you
will start seeing advisories immediately, and growth on the largest ones will
be refused. Knowing which plans those are before it happens is worth five
minutes.

## How to detect if this applies to you

Applies to any project with a plan directory. Measure the tree against the
tiers — **sample**, adapt the path to your configured `track_plans_in_project`:

```bash
python3 - <<'EOF'
import pathlib
root = pathlib.Path("CLAUDE/Plan")          # adapt to your plan directory
rows = []
for p in root.rglob("PLAN.md"):
    if "JOURNAL" in p.parts:                 # journals are exempt
        continue
    text = p.read_text(errors="replace")
    rows.append((len(text.encode()), text.count("\n"), str(p)))
rows.sort(reverse=True)
for b, l, path in rows:
    tier = ("BLOCK"    if b > 35000 or l > 900 else
            "warning"  if b > 25000 or l > 500 else
            "advisory" if b > 18000 or l > 350 else None)
    if tier:
        print(f"{tier:9} {b:>7,}B {l:>5}L  {path}")
EOF
```

Anything printed as `BLOCK` cannot be grown until it is dealt with.

## How to handle

For each plan over a tier, decide which of **two** remedies applies. **Neither
is deletion** — git keeps history, but destroying narrative loses the grounding
a future agent needs:

1. **Relocate** — if the bulk is dated progress notes, incident write-ups or
   hand-off prose (often under a `## Notes & Updates` heading), move it into
   that plan's `JOURNAL/` day-file, which is append-only and unbounded. Append;
   never rewrite existing journal entries.
2. **Split** — if the bulk is the task tree itself, the plan is over-scoped and
   better journalling will not fix it. Split it into focused plans using your
   normal plan-creation flow so numbering and the README index stay correct.

Act autonomously for relocation on plans you are actively working. **Escalate
to the user before splitting a plan** — that changes plan numbering and the
index, which is a project-level decision.

If a plan genuinely warrants its size (a long-running multi-subsystem
migration), declare it in the file rather than fighting the check:

```markdown
<!-- MUST_EXCEED_PLAN_SIZE_BECAUSE: tracks a 12-subsystem migration -->
```

If you would rather not adopt the limits yet, tune or disable them in
`.claude/hooks-daemon.yaml` — **sample**:

```yaml
plan_workflow:
  qa:
    plan_doc_size:
      enabled: true
      block_bytes: 60000    # raise the ceiling during a rollout period
      block_lines: 1500
```

Tiers must increase strictly on both axes (advisory < warning < block) or the
daemon fails fast at startup with a clear message. Historic plans can instead
be added to `plan_workflow.qa.legacy_plan_allowlist`, which holds them to
advise-only.

Note also that a commit shrinking a `PLAN.md` by 2,000+ bytes with no staged
journal entry is now flagged by `plan-shrink-without-journal`. That is advisory
and is fine to proceed past when the removed content was genuinely obsolete —
it exists so you notice whether you relocated or deleted.

## How to confirm

Re-run the detection script. A clean result is no `BLOCK` lines; advisories on
a few large plans are acceptable and will keep nudging.

Then confirm the daemon agrees:

```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli plan-qa --sweep
```

## Rollback / if this goes wrong

Nothing in this task modifies files unless you choose to relocate or split.
If a relocation moved the wrong content, recover it from git
(`git diff HEAD -- <plan>` before committing, or `git show HEAD:<plan>` after)
and append it back to the journal rather than re-adding it to `PLAN.md`.

To back the enforcement out entirely, set
`plan_workflow.qa.plan_doc_size.enabled: false` and restart the daemon.
