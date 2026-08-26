# Brainstorm: bash safe mode forcer (Plan 00270)

Design-space exploration for an opt-in handler that enforces bash safety
preludes (`set -e`, `set -o pipefail`, `set -u`) on Bash tool calls. Written
for human review before implementation; nothing here is decided except where
PLAN.md's Technical Decisions ratify it.

## 1. Framing: the opt-in counterpart Plan 00268 deferred

Plan 00268's Non-Goals reject enforcing `set -e` as a standalone rule and
direct that it be offered "as remedy text in the block message, not as its own
gate". Its DESIGN-verifier-mutator.md §6 gives the reasons:

- **Cry-wolf risk**: a handler that is mostly wrong gets disabled, leaving the
  project worse off than no handler.
- **Semantics change for every command**: under `set -e`, `grep -q p f; echo done`
  aborts on a legitimate no-match; a labelled diagnostic sweep stops at its
  first failing probe; `cmd > f 2>&1; echo "exit=$?"` — which exists to
  OBSERVE a failure — never reaches its observation.
- **`set -e` blind spots**: it does not fire inside `if`/`while` conditions,
  for non-final operands of `&&`/`||` chains, or for failures inside command
  substitutions used in assignments (`local x=$(fail)` masks the exit status
  entirely; `var=$(fail)` without `local` does propagate, a distinction almost
  nobody carries). Over-trusting the prelude is its own failure mode.

Those objections killed BLANKET enforcement. They do not kill an OPT-IN
handler, provided each objection maps to a mitigation:

| 00268 objection           | This design's mitigation                                                                                                                                  |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Cry-wolf → disabled       | Ships `enabled: false`; warn-first even when enabled; a project chooses this policy                                                                       |
| Breaks no-match `grep -q` | `min_statements` threshold; escape hatch; optionally scope to mutator-bearing commands                                                                    |
| Breaks diagnostic sweeps  | Escape hatch (`MUST_SKIP_SAFE_MODE_BECAUSE=`); warn mode never stops the sweep                                                                            |
| Breaks `$?` observers     | Same; and the guidance shows the `rc=$?` idiom that stays valid under `set -e`... it does not — see §4, this shape needs the escape hatch or `mode: warn` |
| Blind spots → over-trust  | Blind-spot education is mandatory guidance text (§5)                                                                                                      |

## 2. Research: can a PreToolUse hook rewrite tool input?

**Question**: does current Claude Code support a PreToolUse hook modifying the
tool input (so the handler could INJECT `set -euo pipefail` instead of
warning)?

**Verdict: supported by Claude Code; NOT yet supported by this daemon's
serialisation layer.**

- **Claude Code side — YES.** The official hooks documentation
  (https://code.claude.com/docs/en/hooks.md, PreToolUse response section)
  documents `hookSpecificOutput.updatedInput`: a partial object merged into
  the original `tool_input` before the tool runs. For Bash that is
  `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": {"command": "set -euo pipefail\n<original command>"}}}`. It works alongside
  `permissionDecision: "allow"`, with no documented permission-mode
  restriction.
- **Daemon side — NO, today.** The PreToolUse response schema in
  `src/claude_code_hooks_daemon/core/response_schemas.py` does not include
  `updatedInput` and declares `additionalProperties: false`, and
  `core/hook_result.py`'s PreToolUse formatter never emits the field. The
  PermissionRequest schema DOES already model `updatedInput`, so the daemon
  has the concept — just not on this event.
- **Consequence for this plan**: ship warn/deny-only. `mode: inject` is
  documented as a future value behind the same config surface, rejected at
  config load with a message naming the missing capability. Closing the
  serialisation gap is a small, separable daemon-core change (schema + a
  `GatingResult` field + formatter) but it touches the response contract for
  every PreToolUse handler, so it deserves its own plan rather than riding
  along here.

**Injection caveats even once supported** (record now so the follow-up
inherits them):

- Prepending `set -euo pipefail` to an arbitrary command CHANGES its
  semantics — exactly the objection in §1. Injection must obey the same
  scoping/exemptions as warn/block, not fire more broadly because it "fixes"
  rather than blocks.
- Silent rewriting is invisible to the agent, which then mis-learns what its
  commands do. Injection should pair with `additionalContext` naming what was
  prepended.
- A command whose first statement is itself a `set` call, or which starts with
  a shebang-style wrapper (`bash -c`, `env`), needs the prelude placed
  correctly, not blindly at byte 0.

## 3. Config surface (proposed)

```yaml
handlers:
  pre_tool_use:
    bash_safe_mode:
      enabled: false          # ships OFF; enabling is a per-project policy act
      options:
        mode: warn            # warn | block | inject (inject: reserved, load-rejected today)
        require:              # each independently toggleable
          - errexit           # set -e
          - pipefail          # set -o pipefail
          # - nounset         # set -u; NOT in the default list (see §4)
        min_statements: 2     # single-statement commands are never flagged
        exempt_patterns: []   # additive regexes over the whole command
        exclude_paths: []     # inherited convention; per-command handler, so likely unused
        only_with_mutator: false  # if true, reuse the verifier-gate mutator table as a scope filter
```

Notes:

- **`require` default is `[errexit, pipefail]`.** `nounset` is available but
  off: `set -u` breaks common idioms (`${VAR:-default}` is safe, but bare
  `$1`/`$OPTIONAL_VAR` probing is everywhere in exploratory shell) and would
  dominate the false-positive budget for marginal benefit.
- **A command that already sets the required flags passes.** Detection reuses
  `verification_result_gate`'s `_ERREXIT_PATTERN` generalised per-flag:
  `set -e`/`-o errexit`, combined clusters (`set -euo pipefail` satisfies all
  three), `set -o pipefail`, `set -u`/`-o nounset`. Partial presence flags
  only the MISSING members of `require`, and the message says which.
- **`min_statements`** counts statements after `strip_quoted_heredoc_bodies` +
  `split_unquoted` on `(";", "\n")` — the exact split
  `verification_result_gate` uses. A single `ls` gains nothing from `set -e`;
  the default of 2 means the handler only speaks where sequencing exists.
  Pipes matter for `pipefail` even in one statement, so an option worth
  discussing: treat a statement containing an unquoted `|` as satisfying the
  threshold for the `pipefail` requirement alone. (Open question 4.)
- **`only_with_mutator`** (default false): scope enforcement to commands that
  contain an entry from the shared mutator table (`git commit`, `git push`,
  `ansible-playbook`, ...). This is the strongest false-positive reducer —
  every 00268 false-positive shape contains no mutator — at the cost of the
  prelude not being enforced on pure diagnostics. Reusing the table means
  extracting it from `verification_result_gate` alongside the errexit pattern
  (PLAN Task 1.2); DRY forbids a second copy.
- **Escape hatch**: `MUST_SKIP_SAFE_MODE_BECAUSE="reason"; <command>` in the
  command itself, following the daemon's established `MUST_..._BECAUSE`
  convention (`git_stash`, `root_recursion_guard`, `ancestry_preserving_merge`).
  Consistent with those, it is an intent declaration, not consent — fine here
  because the consequences stay inside the invocation.

## 4. False-positive management, shape by shape

The 00268 §6 table, replayed against this design:

| Shape                          | Under forced errexit          | This handler's answer                                                                                                                                                             |
| ------------------------------ | ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `grep -q p f; echo done`       | Aborts on legitimate no-match | 2 statements → flagged in principle; `only_with_mutator: true` spares it; otherwise warn mode + escape hatch                                                                      |
| `cmd > f 2>&1; echo "exit=$?"` | Observation never runs        | Same; the guidance must NOT claim `rc=$?` capture works under `set -e` — a failing `cmd` exits the script before the capture. The honest remedy for observers is the escape hatch |
| Labelled diagnostic sweep      | Stops at first failing probe  | Warn mode never stops it; block mode needs the escape hatch                                                                                                                       |
| Single `ls` / one-liner        | No benefit, pure noise        | `min_statements: 2` — never flagged                                                                                                                                               |
| `lint && commit`               | Already gated                 | Still flagged if multi-statement without prelude? No: `&&`-only chaining IS consumption; see open question 3                                                                      |

The last row exposes the deepest tension: `verification_result_gate` treats an
`&&`-gated statement as safe, and this handler demanding a prelude ON TOP of
correct explicit gating would be exactly the style-rule noise 00268 refused to
ship. Proposed resolution: a command whose every multi-statement boundary is
`&&`-joined (i.e. `split_unquoted` on `(";", "\n")` yields one statement) is
already below `min_statements` — the threshold handles it for free. A command
mixing `&&` chains WITH `;`/newline boundaries is genuinely sequenced and the
flag stands.

## 5. Education: the guidance must teach the blind spots

Whatever mode fires, the message states — verbatim, as a fixed block — that
`set -e` is not a safety guarantee:

- It is DISABLED inside `if`/`elif`/`while`/`until` conditions and under `!`.
- A failure in any non-final operand of `&&`/`||` does not exit.
- `local x=$(fail)` and `export x=$(fail)` mask the substitution's exit
  status; the assignment succeeds.
- `cmd | head` under `pipefail` can fail on SIGPIPE alone — `pipefail` turns
  some benign shapes into failures, which is the point but surprises people.

This block also appears in `get_claude_md()` so the education is resident, not
only reactive. Rationale: a user who enables this handler is buying a
default-deny posture; the worst outcome is that they then DROP explicit gating
("`set -e` has it covered") in the shapes where it silently does not.

## 6. Relationship to `verification_result_gate`

Complementary, with a deliberate stand-down in one direction already built:
`verification_result_gate` treats any errexit `set` in the invocation as
consuming everything, so a command satisfying THIS handler is invisible to
that one. The composition:

- No prelude, verifier→mutator ungated → verifier gate speaks (specific,
  taxonomy-driven).
- No prelude, no verifier/mutator pair, multi-statement → only this handler
  speaks (generic, opt-in).
- Prelude present → both silent.

Shared code to extract (PLAN Task 1.2): the errexit/flag patterns, the
statement/span split constants, and (if `only_with_mutator` is ratified) the
mutator signature table. `utils/bash_flags.py` or widening
`utils/shell_segmentation.py` — implementer's choice, but ONE home.

## 7. Priority, identity, tiering

- Priority: workflow band (36–55), after the safety blockers and near its
  sibling `verification_result_gate`; non-terminal in warn mode.
- `HandlerID.BASH_SAFE_MODE`, `Priority.BASH_SAFE_MODE` constants per the
  no-magic rule.
- Rollout mirror: `plan_qa_commit_gate` / `verification_result_gate`
  warn-first precedent, except this one is additionally gated behind
  `enabled: false`.

## 8. Open questions for the human

1. **Scope default**: should `only_with_mutator` default to `true` (near-zero
   false positives, but the prelude is then only enforced where the verifier
   gate already watches) or `false` (broader, noisier)? Brainstorm leans
   `false` with warn mode, on the grounds that an opting-in project has asked
   for the broad rule.
2. **`nounset` in the default `require` list?** Brainstorm says no (breaks
   `$OPTIONAL_VAR` probing); confirm.
3. **Is `min_statements` the right consumption story for pure `&&` chains**, or
   should an explicit "fully-gated command is exempt" rule exist even when
   statements exceed the threshold (e.g. three statements, each internally
   `&&`-gated but `;`-joined)?
4. **Pipefail-only trigger**: should a single-statement command containing a
   pipe be flagged for missing `pipefail` even below `min_statements`? (The
   pipe_blocker whitelist means most surviving pipes are cheap filters, which
   argues no.)
5. **Escape-hatch spelling**: `MUST_SKIP_SAFE_MODE_BECAUSE` — acceptable, or
   prefer `MUST_OMIT_SAFE_PRELUDE_BECAUSE`?
6. **Follow-up plan for `updatedInput`**: should the daemon-core serialisation
   gap (§2) be filed now as its own plan, so `mode: inject` has a landing
   path, or wait until warn/block proves demand?

## 9. Hostile self-review — what it changed

- **Caught a false remedy**: an earlier draft of §4 claimed `rc=$?` capture
  as the escape for exit-code observers under `set -e`; that is wrong (the
  script exits before the capture unless the failing command is itself
  gated). Rewritten to name the escape hatch as the honest answer, and §5 now
  forbids the guidance from making the same false claim.
- **Resolved the `&&`-chain tension** (§4 last row) instead of leaving it as
  a latent contradiction with `verification_result_gate`'s consumption model;
  residual ambiguity surfaced as open question 3 rather than papered over.
- **Demoted `nounset` out of the default `require` list** after enumerating
  the `$OPTIONAL_VAR` probing idiom; originally all three flags were default.
- **Added the injection caveats block** (§2): the first draft treated
  `mode: inject` as strictly better than warn; it is not — silent rewriting
  changes semantics invisibly and must inherit the same scoping.
- **Checked the daemon schema claim against the source** rather than trusting
  the research summary alone: `response_schemas.py` PreToolUse block has
  `additionalProperties: false` and no `updatedInput`; PermissionRequest has
  it. Verdict stands.
