# Callout: a deployed daemon-owned file that has drifted now says so

**Plan**: 00377
**Audience**: operators

Daemon-owned files deployed into your project — the agents under
`.claude/agents/`, the core documents under `CLAUDE/core/`, and the plan tooling
(`mkplan.bash`, `_planlib.inc.bash`) — are refreshed by install and upgrade.
Between those events a template can move on while your deployed copy stays
behind, and nothing told you. Earlier changes in this release made such a copy
repairable; this one makes it visible.

A new session-start advisory compares every deployed daemon-owned file with the
template it came from and names anything that differs, along with the command
that repairs that particular file. It never blocks, and it is silent when
nothing has drifted.

**Only files you actually have are compared.** A core document whose gating
config is switched off was never deployed, so it is absent by design and is
never reported as drift. An absent `mkplan.bash` is still reported by the
existing plan-asset advisory rather than by this one, so a project missing its
plan tooling gets one message, not two.

**A drifted AGENT is reported differently from the rest, deliberately.** Core
documents and the plan tooling are rewritten unconditionally on every deploy, so
nothing there protects a local edit and any difference is drift. Agents are the
opposite: a customised agent is never clobbered. The advisory therefore consults
the revision ledger and tells you which case you are in — a copy matching a
previously shipped revision is safe to refresh with a plain install, while one
matching no shipped revision is either your own edit or an unrecorded one, and
is named with the explicit `--force` escape rather than the plain command that
would refuse it.

If you have never edited a daemon-owned file and your install is current, you
will not see this advisory at all.
