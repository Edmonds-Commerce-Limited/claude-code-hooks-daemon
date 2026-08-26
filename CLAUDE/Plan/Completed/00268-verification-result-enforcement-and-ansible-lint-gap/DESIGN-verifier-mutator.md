# Design: the `verifier → mutator` gate (Plan 00268 Phase 2)

Decisions taken before implementation, so the reasoning is not re-derived from
the diff. The incident and the rejected alternatives live in
[ANALYSIS-command-chaining.md](ANALYSIS-command-chaining.md); this document
covers only what the handler does and why it is shaped this way.

## 1. What fires

> A **verifier** runs, and a **mutator** runs later in the same Bash
> invocation, with nothing between them that consumes the verifier's exit
> status.

Precision comes from the TAXONOMY, not from separator analysis. That is the
whole reason this is buildable: every false-positive shape in the analysis
table (`grep -q p f; echo done`, `cmd > f 2>&1; echo "exit=$?"`, `diff a b; echo ---`, independent `ls -1t` listings, a labelled diagnostic sweep) contains
no mutator at all, so it cannot fire however the segments are separated. A
handler that reasoned about `;` instead would have to distinguish all of them.

## 2. A newline separates exactly as `;` does

The single most important point, and the one the obvious implementation gets
wrong. In the motivating incident the lint was on line 1 and the `git commit`
on line 3 of one multi-line Bash command; a scanner looking for `;` between
commands finds only the `;`s INSIDE line 1 and never connects them.

`split_unquoted` already takes a separator tuple and both existing callers
already include `"\n"`, so this needs no new machinery — only that the handler
uses the shared scanner rather than growing a third private one (the exact
duplication Plan 00200 Task 3.7 consolidated away).

## 3. Two split passes, because they answer different questions

- **Statements**: split on `(";", "\n")`. These are the units that run
  UNCONDITIONALLY with respect to each other. A verifier in statement *i* and a
  mutator in statement *j > i* is the dangerous shape.
- **Command spans**: split each statement further on `("||", "&&", "|")`, so a
  statement's individual commands can be classified.

Splitting only once would be wrong in both directions. Split on everything and
`lint && git commit` looks identical to `lint; git commit`. Split on `;`/`\n`
alone and a statement containing several piped commands is judged by its first
word.

A statement containing `&&` or `||` is treated as **gated**: its verifier's
result is consumed by construction. This deliberately also spares
`lint || true`, which suppresses rather than consumes — `error_hiding_blocker`
owns that shape, and claiming it here would be a second opinion on the same
line.

## 4. Ordering the taxonomies matters: `ansible-playbook` is both

`ansible-playbook --syntax-check` is a verifier. Bare `ansible-playbook` is a
mutator — it changes remote machines. The same binary, separated only by a
flag. So a command span is tested against the VERIFIER table first and, if it
matches, is never also read as a mutator.

That forces the taxonomy entry to carry more than a name. Each entry is a
`CommandSignature(name, required_flags, forbidden_flags)`:

| Entry                                                    | Meaning                                      |
| -------------------------------------------------------- | -------------------------------------------- |
| `ansible-playbook` + requires `--syntax-check`/`--check` | verifier                                     |
| `ansible-playbook` + forbids the same flags              | mutator                                      |
| `git commit`                                             | two-token name, matched via `GIT_INVOCATION` |

## 5. What counts as consuming the result

Not firing is the default whenever any of these appears between the verifier
and the mutator:

- the verifier's own statement contains `&&` or `||` (§3);
- `set -e` / `set -euo pipefail` / `set -o errexit` anywhere in the invocation
  — it makes the whole invocation gated;
- a statement opening a conditional construct (`if`, `case`, `while`, `until`)
  — this is what covers `rc=$?` followed by a branch, without needing to track
  the variable;
- a statement whose head is `exit`.

A bare MENTION of `$?` does not count. `echo "lint exit=$?"` is precisely what
the incident did, and it consumed nothing — it printed. Treating a `$?`
reference as a gate would exempt the motivating case.

## 6. Warn first, and never phrased as a style opinion

Ships `mode: warn`, mirroring `plan_qa_commit_gate`'s rollout. The message
names the specific pair — "`ansible-lint` can fail here and `git commit` would
still run" — and shows the accepted forms. It must not say "use `&&`": the
analysis rejects blanket `&&` enforcement outright, and a message that reads as
a style rule invites exactly the disabling this handler cannot afford.

`set -euo pipefail` is offered as REMEDY TEXT in that message rather than
enforced as its own rule, for the reason the analysis gives — it changes
semantics for every command in the invocation, including the ones that
legitimately expect a non-zero exit.

## 7. Project-extensible, additively

`extra_verifiers` and `extra_mutators` accept plain command names, appended to
the built-in tables. This follows `pipe_blocker`'s `extra_whitelist` rather
than `command_hints`' `additive`/`replace` modes: a project that could REPLACE
the mutator table could silently empty it, and a gate nobody can tell is off is
worse than one that is loud.
