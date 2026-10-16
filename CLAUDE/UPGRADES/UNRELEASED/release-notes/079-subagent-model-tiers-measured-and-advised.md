# Callout: which model each subagent runs on is measured, and a cheaper tier is suggested

**Plan**: 00472
**Audience**: client projects

A subagent nobody picks a model for runs on its spawner's. In the measured run, 36.5 % of agents never had a model chosen and almost all of them ran on Opus; a `Workflow` script's `agent()` calls do the same unless they pass `model`. The daemon now records the choice and advises on it. Nothing here denies.

- **Every `Agent` dispatch gets a tier row** in the spend ledger (`spend-ledger/<session>/dispatches/`): how its model was chosen (`fork`, `explicit`, `definition`, `env`, `inherited-capped`, `inherited`), the family that predicts, a role label and any `tier: <reason>` line. `agent_dispatch_recorder` now writes a row for unnamed dispatches too, and the new **`dispatch_model_recorder`** (PostToolUse) adds the model that actually started. Each per-agent ledger row also gains `tool_use_id` and a `downgraded` flag when the safety fallback swapped its model.
- **`hooks-daemon tiers [--session ID | --transcript PATH] [--by type|role|source] [--json]`** prints agents and spend by source, model and role, whether `CLAUDE_CODE_SUBAGENT_MODEL` is set in `.claude/settings.json`, and every agent whose model was swapped mid-run.
- **`subagent_tier_advisor`** (on): a dispatch that inherits Opus or above, or passes a `model` above its definition's own, gets a two-line note naming the cheaper tier, once per session, type and source. A `tier: <reason>` line in the prompt keeps the tier silently. Security, adversarial, decision and review work is never nudged. Ceilings and floors per agent type are configurable and ship empty.
- **`workflow_fanout_advisor`** (on): a `Workflow` call gets a note with the agent count, the `agent()` sites with no `model`, and whether the count is over the ceiling for the session's tier (fable 10, opus 25, sonnet 60, haiku 60). The first call of each session records the call's key names and value types (never values or the script) in `payload-capture/workflow-shape.json`.

**Recommended, not applied:** `CLAUDE_CODE_SUBAGENT_MODEL=sonnet` in `.claude/settings.json` moves every inherited subagent off the main model. Pin reviewers and security checks to `model: opus` (or configure floors) first. See `docs/guides/SUBAGENT_MODEL_TIERS.md`.
