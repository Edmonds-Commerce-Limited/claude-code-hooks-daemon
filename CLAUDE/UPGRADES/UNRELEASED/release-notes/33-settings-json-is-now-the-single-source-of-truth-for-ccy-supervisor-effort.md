# Callout: settings.json is now the single source of truth for ccy supervisor effort

**Plan**: 00466
**Audience**: operators

The ccy supervisor used to keep its own opinion of per-model effort (a
built-in floor table plus the `CCY_MIN_EFFORT_LEVELS` env var), which could
fight Claude Code's own `settings.json` — a configured medium effort could
still be overwritten with `/effort high`, or `/effort xhigh` on every model
restore. Adversarial review found that first fix still held too much
opinion of its own, so the supervisor's effort logic was simplified again:
it now holds almost none. Exactly two interventions are sanctioned:

- while a downgrade episode leaves a session on a fallback model, effort
  goes to xhigh, for that exact destination only (never inferred from which
  path typed `/model`);
- Fable never runs above low effort — the separate, continuously-verified
  Plan 00297 DROP ANCHOR invariant, not this mechanism.

For every OTHER family, once no downgrade episode is open, the supervisor
corrects effort (in either direction) toward whatever `settings.json`
resolves for the EXACT model id on screen — matching Claude Code's own
resolution: per exact model id (never a sibling in the same family), across
local project, shared project, and user settings files in Claude Code's
precedence, a user-file top-level `effortLevel` skipped for Opus 5.5 and
later, `"max"` never accepted from settings, and `CLAUDE_CODE_EFFORT_LEVEL`
taking precedence over all of it. Nothing configured means Claude Code's own
per-model default already applies and is never fought — the built-in floor
table and `CCY_MIN_EFFORT_LEVELS` are both gone, not just superseded.

`/effort auto` was investigated as a possible non-mutating reset for the
restore path and rejected: per Claude Code's own settings reference, it
*writes* — it clears the saved `modelSettings` entry for the model you're
using — so an automated restore using it would mutate the user's persisted
settings.json. The supervisor instead resolves the value itself from the
settings files it already reads and injects a plain `/effort <value>`,
which never touches disk.

`settings.json` DATA is re-read on change without a supervisor relaunch (it
always was). The RESOLUTION LOGIC in this release is new code, though: the
coupled-effort correction moved from one-shot host-side arming to a
per-tick worker-side decision, which is what makes it hot-reloadable at
all. A ccy session started before this release needs a relaunch (or a
forced worker reload — see `CLAUDE/development/CcySupervisor.md`) to pick
up this behaviour; a settings.json edit alone will not.
