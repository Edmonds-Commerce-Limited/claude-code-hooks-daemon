# settings.json merge spec (Plan 00176 Task 1.1)

The decided answer to the five open design questions in `PLAN.md`, plus the
key-ownership rule the implementation phases build against. Every claim here
was read out of the code rather than assumed; where the code already answers a
question, that is said outright rather than re-designed.

## Q1 — Reuse the YAML merge, or a dedicated command?

**A dedicated `settings-merge`, reusing the three-way *shape* and nothing else.**

`install/config_cli.py` is YAML-bound at the load boundary (`_load_yaml`, and
yaml referenced throughout), so `run_config_merge` would need its loader
parameterised at minimum. That alone would be a weak reason to split — a loader
is easy to inject.

The real reason is that the merge RULE differs, not just the parser. The YAML
merge answers one question uniformly across every key: *did the user change this
away from the old default?* `settings.json` has three ownership classes with
three different answers (below), and one of them — the `hooks` block — must be
force-refreshed **against** the user's copy, which is the exact inverse of what
`preserve_config_for_upgrade` exists to do. Threading that through the YAML path
would put a second, contradictory mode inside a function whose whole contract is
"preserve what the user changed".

What IS worth reusing is the three-way input shape (old-default, new-default,
user) and the workflow around it: back up, merge, validate, report
incompatibilities. `config_preserve.sh` is the model to mirror, not the code to
extend.

## Q2 — `hooks`-block strategy

**Match-and-replace per inner hook, keyed on the daemon-wrapper fragment. Not a
whole-block replace, and not the additive-only behaviour that exists today.**

This question is half-answered by code already in the tree, and the half that is
missing is precisely the gap the plan's Goals name.

`utils/hook_registration.py` has `reconcile_settings_hooks`, whose docstring is
explicit that it is **additive only**: *"Present events — including any
client-added custom entries — are left untouched."* It walks
`HOOK_EVENTS_IN_SETTINGS` (built from `EventID` with `wired=True`, StatusLine
excluded because it registers top-level) and adds any event key that is absent.

There are **two** statements of the wired set: this one, and
`_DAEMON_FORWARDER_HOOKS` at `install.py:321`, which the standalone bootstrap
script uses because it cannot import the daemon. A drift test holds them in
step. The merge runs inside the daemon, so it builds on the `src/` pair — but
anyone changing the wired set has to touch both.

So today:

| Situation                                   | Current behaviour     | Wanted             |
| ------------------------------------------- | --------------------- | ------------------ |
| Wired event missing from `hooks`            | added ✅              | added              |
| Wired event present, daemon entry correct   | untouched ✅          | untouched          |
| Wired event present, daemon entry **stale** | **untouched ❌**      | **refreshed**      |
| Client's own extra hook in the same array   | untouched ✅          | untouched          |
| `hooks` not a dict                          | replaced wholesale ✅ | replaced wholesale |

Row three is the gap: an upgrade cannot currently repair a forwarder entry that
exists but is wrong (an outdated command shape, a missing `timeout`, a
relative path), because the event key is present and presence is all that is
checked. That is exactly "an upgrade must never leave a client with a stale or
incomplete `hooks` block" failing.

### The discriminator: NOT the `/.claude/hooks/` substring

This spec first proposed testing `_DAEMON_WRAPPER_FRAGMENT = "/.claude/hooks/"`
against the `command` string. **That is wrong in both directions**, and the
adversarial audit proved it with a runnable probe
([`probe_fragment.py`](subagent-reports/probe_fragment.py), run against the real
constants):

| Command                                                                       | Substring says | Truth                                                              |
| ----------------------------------------------------------------------------- | -------------- | ------------------------------------------------------------------ |
| `.claude/hooks/pre-tool-use`                                                  | not ours       | **ours** — the relative legacy shape this section exists to repair |
| `bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/my-secret-scan`                     | ours           | **client's** — would be rewritten into a duplicate forwarder       |
| `bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/pre-tool-use && ./ci/extra-gate.sh` | ours           | **client's chained gate** — rebuilding drops `./ci/extra-gate.sh`  |
| `bash "$HOME"/dotfiles/.claude/hooks/lint`                                    | ours           | **client's**, not even in this repo                                |

The false NEGATIVE is the worst of them: the relative form is precisely the
"stale entry" row above, so a substring test would leave broken exactly the case
it was added to fix.

**Use `hook_command_migration.legacy_command_bash_key` instead**, which already
solves this and is anchored to the WHOLE command rather than searching inside
it. An inner hook is daemon-owned when either:

1. it equals `canonical_hook_command(key)` for a `key` in the wired set, or
2. `legacy_command_bash_key(command)` returns a `key` in the wired set.

Membership of the **wired set** is what rejects `my-secret-scan`; anchoring is
what rejects the chained command and the dotfiles path. Everything else is the
client's and is never touched. This is also why per-hook matching beats
whole-block replace — a client hook sitting in the same event array as a daemon
forwarder survives, as the plan's ownership table commits to.

`HOOK_COMMAND_TEMPLATE` is public precisely so several places render a
byte-identical command; the merge becomes a fourth caller, so a rebuilt entry is
identical to a freshly installed one by construction rather than by review.

## Q2b — Where the old-default baseline comes from

The audit's first critical finding: the three-way rule below assumes an
old-default baseline, and **for `settings.json` none exists**. Verified — the
repo ships `.claude/hooks-daemon.yaml.example` but there is no
`settings.json.example`, and by the time either deploy site runs, the daemon's
own `.claude/settings.json` is already the NEW default.

The mechanism to mirror is `config_preserve.sh:166` `resolve_old_default_config`,
which resolves the YAML baseline in two steps: an exported handover
(`HOOKS_DAEMON_OLD_DEFAULT_CONFIG`) captured by Layer 1 **before the checkout**,
falling back to the on-disk `.example`.

Settings differs in one way that makes this simpler, not harder: the daemon's
own `.claude/settings.json` **IS** its shipped default, so there is no
`.example` to invent — Layer 1 need only copy that file pre-checkout and export
it as `HOOKS_DAEMON_OLD_DEFAULT_SETTINGS`. Layer 1 currently hands over the YAML
baseline alone, so this is an extension of a working path rather than a new one.

**When no baseline is available** — a fresh install, or Layer 2 invoked directly
— the recommended-default class degrades to: **preserve every client value,
upgrade none.** Without the old default there is no way to tell an accepted
default from a deliberate override, and of the two possible errors only one
destroys anything. A stale `refreshInterval` costs a slow status line; a
stomped one costs a customisation the client chose. There must be **no
fallback that guesses the baseline** — the existing YAML resolver's stale-
handover warning exists precisely because a plausible-but-wrong baseline
misclassifies silently.

## Q3 — When does the merge escalate to an agent-assisted diff?

**On genuine conflict or validation failure only — never as routine narration.**

Presenting a summary on every upgrade is the `settings.json` version of a
warning that fires every time, which trains people to skip it (the same
reasoning that made Task 2.0's helper stay silent when the file is unchanged).
The escalation is worth something only if it is rare.

Escalate when, and only when:

1. the merged result fails validation, or
2. a client value and a new daemon default conflict in a way the ownership
   rules below do not resolve.

**Non-interactive fallback (CI, headless) is: change nothing, and say so.** Keep
the client's file exactly as it is, write the proposed merge alongside it, and
report a non-zero status naming both paths. That fails toward not destroying
client data, which is the Goal's stated tiebreak. It must never silently pick
either side — an unattended run that guesses is how a customisation disappears
with nobody watching.

## Q4 — Backup retention

**Already shipped, by Task 2.0 — nothing further is owed here.**

`scripts/install/settings_deploy.sh` is the single deploy path for both the
idempotent fast path and Step 9. The merge should call it rather than
re-implement backup handling. Its rules, each with a reason:

- **Acts only when the files actually differ.** A warning on every upgrade
  trains people to ignore it, and a `.bak-` per upgrade of an identical file is
  litter.
- **One copy, never two.** Timestamped `.bak-` when no rollback snapshot covers
  it; a pointer at the snapshot when one does.
- **Aborts without overwriting if the backup cannot be written.** Losing the
  client file is the one outcome worth failing a deploy for.

Tested by sourcing the real library and calling it, plus assertions that both
sites go through it and no raw `cp "$SETTINGS_JSON_SOURCE"` survives — a helper
only helps if the sites that had the bug use it.

The third route, `install.py`, had the same defect in a different shape and is
fixed under Task 2.0b: its backup was conditioned on `not force`, so `--force`
— the invocation that reinstalls over an existing install — was the one that
took no copy. All three routes now copy before they overwrite.

The original question assumed Step 9 was the unprotected site. It is the
opposite: Step 9 runs after Step 3's snapshot, while the fast path `exit 0`s
before Step 3 ever runs and used to copy silently. That correction is recorded
in `PLAN.md` Task 2.0.

## Q4b — Absence is not an override

The audit's second critical finding, verified: the daemon's shipped
`settings.json` has five top-level keys — `hooks`, `statusLine`, `permissions`,
`enableArtifact`, `plansDirectory`. Under the ownership table's
"client-owned: preserved verbatim, always", a client whose file lacks
`permissions` would **never receive it**, because preserving a client key
includes preserving its absence. Today's verbatim copy delivers it.

**Two of the three are security controls**, which makes this worse than the
preference regression it looks like:

| Key              | Shipped value                                                  | What silence costs         |
| ---------------- | -------------------------------------------------------------- | -------------------------- |
| `permissions`    | `deny: Edit(//tmp/**), Edit(//var/tmp/**), Edit(//dev/shm/**)` | write guards never applied |
| `enableArtifact` | `false`                                                        | publishing stays enabled   |
| `plansDirectory` | `./CLAUDE/Plan`                                                | plan workflow misroutes    |

So the rule is: **you can only override something you have expressed an opinion
about.** Presence is merged three-way exactly as value is —

- key absent from the client file **and** absent from the old default → it is
  NEW this version; deliver it.
- key absent from the client file **but present in the old default** → the
  client removed it deliberately; preserve the absence.
- key present → the client's; preserve their value.

**Where the "preserve, don't destroy" tiebreak does NOT apply.** That tiebreak
is about the client's DATA. Declining to deliver a deny rule destroys nothing,
but it does silently withhold a protection the client would have got from the
copy this merge replaces. With no baseline available (Q2b), a security-relevant
default should therefore be **delivered and reported**, not skipped — the
opposite of the degradation the preference class takes, and the reason the two
must not share one code path.

## Q5 — Interaction with Plan 00175's validator

**Moot: `statusline_refresh_checker` does not exist.** The only statusline
handler in `handlers/session_start/` is `suggest_statusline.py`. The question was
written conditionally ("if built"), and the condition is false, so there is no
division of labour to confirm and nothing to build against.

If it is built later the division is the obvious one, and it follows from the
ownership table rather than needing its own decision: the merge PRESERVES a
client's deliberate `refreshInterval`, and the advisory may NUDGE about it.
Neither forces it.

## The decided key-ownership rule

| Class                   | Keys                                                                                | Rule                                                                                                                              |
| ----------------------- | ----------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| **Daemon-owned**        | inner hooks under `hooks[event]` whose `command` contains `/.claude/hooks/`         | rebuilt from `HOOK_COMMAND_TEMPLATE`; missing wired events added; **siblings without the fragment never touched**                 |
| **Recommended default** | `statusLine.command`, `statusLine.refreshInterval`                                  | three-way: user value differing from the OLD default is preserved; user value equal to the old default is upgraded to the new one |
| **Client-owned**        | `permissions`, `plansDirectory`, `env`, every other top-level key, non-daemon hooks | preserved verbatim, always                                                                                                        |

Two invariants that fall out of it, and that Phase 2's tests should assert
directly rather than incidentally:

- **No client-owned key is ever read.** The merge cannot lose what it does not
  look at, so the implementation should copy the client document and edit the
  daemon-owned parts of it — not build a daemon document and graft client keys
  on. The direction of the copy is the safety property.
- **A daemon forwarder is identified by its command, not by its position.** An
  array index or an entry count is not identity; reordering a client's hooks
  must not change which entry is treated as ours.
