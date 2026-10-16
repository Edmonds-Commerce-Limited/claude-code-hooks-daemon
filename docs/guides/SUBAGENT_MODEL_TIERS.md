# Subagent model tiers

A subagent that nobody chooses a model for runs on its spawner's model. When
the main thread runs on the top tier, routine delegated work (a bounded fix, a
test run, a search) runs there too, at several times the price of a tier that
would do it as well. The daemon measures which tier each delegation got and
advises when the choice looks mismatched. It never blocks a delegation, and it
never picks a model for you.

Per-handler options and defaults are in
[HANDLER_REFERENCE.md](HANDLER_REFERENCE.md#subagent_tier_advisor). The design
and the measurements behind it are in Plan 00472
(`CLAUDE/Plan/00472-subagent-model-tier-selection/`).

## How a subagent's model is chosen

Claude Code takes the first of these that is set:

1. the `model` parameter of the `Agent` call;
2. the agent definition's frontmatter `model` (`inherit` means the spawner's);
3. `CLAUDE_CODE_SUBAGENT_MODEL`;
4. the spawner's own model.

A fork always inherits. Built-in Explore inherits capped at Opus, and the
environment variable does not reach Explore or Plan.

## What the daemon does

- **Records every dispatch.** Each `Agent` call gets a row in the spend ledger:
  the source of its model (`fork`, `explicit`, `definition`, `env`,
  `inherited-capped`, `inherited`), the family that predicts, a role label, and
  afterwards the model that actually ran.
- **`hooks-daemon tiers`** prints agents and spend by source, by model and by
  role (`--by type|role|source` for one grouping), whether
  `CLAUDE_CODE_SUBAGENT_MODEL` is set in `.claude/settings.json`, and every
  agent whose model was swapped mid-run.
- **`subagent_tier_advisor`** adds a two-line note to a dispatch that inherits
  the top tier, or passes a `model` above the definition's own, naming the
  cheaper tier. It stays quiet for security, adversarial, decision and review
  work.
- **`workflow_fanout_advisor`** reads a `Workflow` script before it runs and
  says how many agents it starts, how many `agent()` calls pass no `model`, and
  whether the count is over the ceiling for the session's tier.

## Keeping a tier on purpose

Add a line `tier: <reason>` to the dispatch prompt. The advisory stays quiet
and the reason is recorded in the ledger:

```text
tier: hardest fail-closed line, two Sonnet rounds did not converge
```

## Ceilings and floors

Both are advisory and per project. A **ceiling** is the tier a type's routine
work fits; a dispatch above it draws the advisory. A **floor** is the lowest
tier a type or role should get; a dispatch below it draws the floor advisory.
Clients ship with empty tables, so only the two source-based triggers fire.
This repository's table, as an example:

```yaml
subagent_tier_advisor:
  options:
    default_ceiling: sonnet
    types:
      python-developer: {ceiling: sonnet}
      qa-fixer: {ceiling: sonnet}
      qa-runner: {ceiling: haiku}
      hooks-daemon-plan-dedupe-scout: {ceiling: haiku}
      Explore: {ceiling: sonnet}
      code-reviewer: {floor: opus}
      security-reviewer: {floor: opus}
      hooks-daemon-docs-qa: {floor: opus}
    role_floors: {security: opus, adversarial: opus, decide: opus}
```

Floors matter most if the main thread ever runs on a cheaper model: every
inherited reviewer would move down with it.

## Recommended: `CLAUDE_CODE_SUBAGENT_MODEL`

Setting `CLAUDE_CODE_SUBAGENT_MODEL=sonnet` in the `env` block of
`.claude/settings.json` moves every inherited subagent off the main model,
while explicit `model` parameters and definition models still win. It is the
largest saving for the least effort.

**Caveat:** it also moves inherited reviewers and security checks to Sonnet.
Give those definitions `model: opus`, or configure floors, before setting it.
Whether it reaches agent-team teammates is not yet verified. The daemon reports
the setting; it does not change it.

## Optional: a cheaper project `Explore`

A project agent definition named `Explore` with `model: sonnet` (or `haiku`)
overrides the built-in, which otherwise inherits up to Opus. It changes
Explore's behaviour for everyone in the project, so it is your call; the daemon
does not ship one.
