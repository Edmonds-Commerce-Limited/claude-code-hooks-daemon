# Context — Suggesting Feature Enablement on Upgrade

## The problem the user raised

> "As part of the upgrade post-process (e.g. truth update) we need to also be
> strongly suggesting that new features are enabled. Otherwise we ship them but
> they are dormant."
>
> "Memory disabling was a key part of this — really should be promoting that
> this is enabled."
>
> "I wonder if we can do another hot-fix release to bring this in and back-fill
> it with recently added features that might simply not be enabled in client
> projects because we didn't suggest it."

## The scene

This project ships handler features as **opt-in** wherever a default-on change
would alter existing behaviour. The canonical recent example is **Plan 00131 /
v3.23.0** — *Block Untracked Claude Memory*:

- New option `markdown_organization.allow_untracked_claude_memory`
- **Default `True`** (= unchanged behaviour; memory writes still allowed)
- The protective behaviour only activates when a client explicitly sets it to
  `False`.

Because the default preserves old behaviour, **a client who upgrades gets the
new code but never the new protection** unless something actively tells them
"this capability now exists — here is how to turn it on." Today nothing does
that loudly. The feature is, in the user's words, **dormant**.

This is not unique to the memory feature. Any opt-in option added across the
v3.x line has the same fate: shipped, but silently inert in client projects.

## How upgrades currently communicate change

Three adjacent mechanisms already exist under `CLAUDE/UPGRADES/`:

1. **truth-changes** (Plan 00118) — `truth-changes/v{X.Y.Z}.yaml`, a `was → now`
   doc-reconciliation list. Surfaced by `cli check-truth-changes` and wired into
   `upgrade.md` step 4. Answers *"what statement in your docs became false?"*

2. **config-changes / config_migrations** (`install/config_migrations.py`) —
   `config-changes/v{X.Y.Z}.yaml` with `added / renamed / removed / changed`
   keys. `cli check-config-migrations` diffs the manifest against the client's
   actual config and emits a `💡 New Options Available` advisory. Answers
   *"what config keys changed?"*

3. **post-upgrade-tasks** — per-release task files moved into the versioned
   upgrade guide at release time. Answers *"what one-off remediation should you
   run after upgrading?"*

The **config-changes** mechanism is the closest fit to what the user wants —
its whole purpose is announcing newly-available options. See `findings.md` for
why it is not currently doing the job.

## What "good" looks like

After upgrading, a client project's LLM (or operator) should see a clear,
**recommendation-grade** prompt along the lines of:

> 🆕 New opt-in protection available since your previous version:
> `markdown_organization.allow_untracked_claude_memory: false` blocks untracked
> Claude memory writes and routes durable knowledge into tracked project docs.
> **Recommended.** To enable: …

…for every high-value dormant feature in the version range they crossed — not
just a quiet "options available" line, and not nothing at all.

## Constraints / sensibilities

- **Reuse, don't reinvent.** A parallel mechanism alongside truth-changes /
  config-changes would violate DRY and the project's single-source-of-truth
  principle. Prefer reviving and strengthening the existing config-changes path.
- **Respect default-on semantics.** The suggestion must distinguish "new option,
  default already does the safe thing" from "new option, dormant unless you opt
  in" — only the latter deserves a strong enable nudge.
- **Backfill is in scope.** v3.x manifests are missing entirely; the dormant
  features the user cares about live in that gap.
- **Release discipline.** Any release follows `/release`. A hot-fix/patch is
  viable if the change is additive (manifests + advisory wording + wiring) and
  passes the H-1 gate; scope to be decided in PLAN.md.
