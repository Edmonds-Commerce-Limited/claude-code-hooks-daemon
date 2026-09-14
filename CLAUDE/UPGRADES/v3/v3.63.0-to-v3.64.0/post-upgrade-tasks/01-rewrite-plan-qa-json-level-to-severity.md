# Task: Rewrite `level` → `severity` at any call site parsing `plan-qa --json`

**Type**: workflow-change
**Severity**: critical
**Applies to**: all (any project whose tooling parses `hooks-daemon plan-qa --json`)
**Idempotent**: yes

## Why

`plan-qa --json` and `docs-qa --json` described the same concept under two
names: `docs-qa` emitted `severity`, `plan-qa` emitted `level`. One concept with
two live spellings IS the defect — a reader keys on one name and silently drops
every finding carrying the other. `plan-qa --json` now emits `severity` and
nothing else, matching `docs-qa`.

This is a BREAKING change to the JSON contract, deliberately shipped without a
deprecation window. A window would have made the two-names defect *correct by
policy* for the length of a release, and the daemon is installed inside the
consuming repository by an agent with write access — so it can migrate call
sites rather than merely announce the change. That is what this task is.

**The failure mode is silence, which is why this is critical.** A consumer
reading `finding["level"]` raises `KeyError` at best; one using
`finding.get("level")` gets `None` for every finding and reports a clean tree
that is not clean.

## How to detect if this applies to you

Search your project for anything consuming `plan-qa --json`. Sample:

```bash
# sample — adapt to your layout and toolchain
grep -rn --include='*.py' --include='*.sh' --include='*.js' --include='*.ts' \
  -e 'plan-qa' -e 'plan_qa' .
```

For each hit, check whether it reads a `level` key from the parsed findings —
`["level"]`, `.get("level")`, `.level`, `jq '.findings[].level'`, or a
destructuring form. Those are the call sites to change.

If nothing in your project parses `plan-qa --json`, this task does not apply;
the human-readable output is unchanged.

## How to handle

Rename the key at each consuming call site — the values are unchanged, only the
key name moves:

```bash
# sample — inspect each match first; do NOT blind-replace "level" project-wide,
# it is an ordinary word and will appear in unrelated code (log levels, nesting
# levels, config levels).
```

Guidance:

- Change only reads of a finding object produced by `plan-qa --json`.
- `docs-qa --json` already emitted `severity` and needs no change.
- If a call site handles BOTH verbs and currently branches on which key is
  present, delete the branch — one name now works for both.
- If you cannot tell whether a `level` read belongs to this output, ask the
  user rather than guessing. A wrong rename here is silent in the same way the
  original defect was.

## How to confirm

Run the verb and confirm the key your tooling reads is the one now emitted:

```bash
# sample
bin/hooks-daemon plan-qa --sweep --json
```

Every object under `findings` carries `severity`; no object carries `level`.
Then re-run your own tooling and confirm it still reports findings it
previously reported — a run that suddenly reports zero findings is the symptom
this task exists to prevent, not evidence of success.

## Rollback / if this goes wrong

The change is a key rename at call sites you control, so `git diff` /
`git checkout` of those files restores the previous state. Nothing in the
daemon's own output needs reverting, and no stored data is transformed.

## Note on timing

This is a POST-upgrade task because that is the channel that exists today. It
would be better run BEFORE the upgrade lands, so no call site is ever broken —
building that pre-upgrade surface is Plan 00376's work, which will move this
task earlier rather than change its substance.
