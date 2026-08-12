# Task: A new agent appears in .claude/agents/ if you use the plan workflow

**Type**: notification
**Severity**: optional
**Applies to**: projects with `plan_workflow.enabled: true`
**Idempotent**: yes

## Why

Nothing in the plan system could tell you that an existing plan already covered
the work you were about to file a plan for. `plan_qa` checks structure — number
collisions, index/folder bijection, statistics, status coherence — and is blind
to two plans being about the same thing. In the daemon's own repository that
cost a wasted evaluation: one plan was filed for a proposal another plan had
already covered five days earlier, and an agent then spent a large amount of
context re-deriving conclusions that were already on disk.

A deterministic check was built and measured first, then rejected. Across 215
real plans, the reliable `**GitHub Issue**: #N` spelling produced **zero**
shared pairs and would not have fired on the case that motivated the work; the
loose `#N` spelling was 34/35 false positives (`resolver #1`, `Bug #3`, `the #1 correctness risk`); and matching supporting-document filenames was dominated by
project-wide docs and by *correct* prior-art citations. Duplicate plans share
subject matter, not citations, so this needs a reader rather than a rule.

So this ships as a specialist sub-agent, and it is **suggested, never
enforced** — it is a judgement call, it can be wrong, and nothing blocks on it.

## What changed

`.claude/agents/hooks-daemon-plan-dedupe-scout.md` is now deployed alongside the
rest of the plan tooling, gated on `plan_workflow.enabled`. It is
**daemon-owned**: like `mkplan.bash` and the deployed skills, it is refreshed on
every upgrade so prompt fixes reach existing installs. Only that one file is
touched — any other agent definitions in `.claude/agents/` are left alone.

The `hooks-daemon-` prefix is deliberate. `.claude/agents/` is a FLAT namespace
your project owns and fills with its own agents, and a name collision there
silently drops one definition rather than erroring — so a bare
`plan-dedupe-scout` could quietly shadow, or be shadowed by, one of yours. The
file also opens with a `DAEMON-OWNED FILE - do not edit` banner explaining that
customising means copying it to a name of your own, not editing it in place.

Two places now suggest using it:

- `mkplan.bash` next-steps output, as a backstop — the folder exists by then,
  but nothing is invested, so merging still costs one `git rm -r`.
- `plan_number_helper` guidance, which fires *before* a plan is created, which
  is the cheaper moment.

## How to detect if this applies to you

It applies if `plan_workflow.enabled` is `true` in `.claude/hooks-daemon.yaml`.
After upgrading:

```bash
ls .claude/agents/hooks-daemon-plan-dedupe-scout.md
```

If the plan workflow is disabled, nothing is deployed and there is nothing to
do.

**A newly deployed agent is not dispatchable immediately.** For a while after
the upgrade you may get `Agent type 'hooks-daemon-plan-dedupe-scout' not found`, listing every other agent — which reads exactly like a broken deploy.
Nothing is broken: the file is on disk, and Claude Code picks it up when it
next re-scans `.claude/agents/`.

Observed during development: the agent appeared later in the SAME session,
with no restart, so a restart is not required — it is simply the quickest way
to force the re-scan if you do not want to wait. Check `ls .claude/agents/hooks-daemon-plan-dedupe-scout.md` first; if the file is there,
the deploy worked and only the pick-up is outstanding.

The same delay applies to CHANGES to the file, which matters if you fork it:
editing your copy may not take effect until the next re-scan either.

## What to do

1. **Commit the file.** `.claude/agents/` is a directory your project owns and
   commits; an uncommitted agent works for you and for nobody else on the team.

2. **Decide whether you want it.** If you do not, delete it — but note it is
   daemon-owned and will be redeployed on the next upgrade while the plan
   workflow is enabled. To stop it permanently, disable `plan_workflow` or keep
   deleting it; there is deliberately no separate opt-out flag for a single
   advisory agent.

3. **Try it once before trusting it.** Dispatch it with a description of work
   you know is already planned, and check that it names the right plan. It
   reads only the title, status and Overview of plans that are NOT
   Complete/Cancelled/Superseded, so an archived plan covering the same ground
   is deliberately not reported.

## Known limitation

This check is non-deterministic and therefore cannot be QA-gated the way the
`plan_qa` rules are. It is tuned to prefer false negatives over false
positives: a wrong candidate makes you read an unrelated plan and teaches you
to ignore the agent, after which the next real duplicate goes through anyway.
If it is quiet when you expected a hit, give it a fuller description of the
intended work — a bare kebab-case folder name is thin evidence to judge on.
