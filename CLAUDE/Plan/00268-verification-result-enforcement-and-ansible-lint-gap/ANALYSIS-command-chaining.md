# Should the hooks daemon enforce `&&` chaining?

Written 2026-08-25, after a verification command failed, printed the correct diagnosis, and
was ignored by the `git commit` that followed it in the same Bash invocation.

**Short answer: yes to the *idea*, no to the *rule as stated*.** Blanket `&&` enforcement
would be both leaky (it would have missed the incident that prompted it) and noisy (it
would fire constantly on legitimate diagnostic sequences). There is a narrow version worth
building, and a different handler that would have caught this incident more reliably.

---

## 1. What actually happened

Editing `play-gather-replica-io.yml`, I added an explanatory comment containing a
possessive apostrophe inside a `shell:` block. Ansible's `split_args` tokenises the raw
block string at parse time — before a `#` is a comment — so one unbalanced quote aborts the
whole play load with `failed at splitting arguments`. `service/CLAUDE.md` documents this
trap **by name, with this exact error string**.

The Bash invocation was, in essence:

```bash
cd /workspace/service; ansible-lint ../…/play-gather-replica-io.yml > /tmp/al7.txt 2>&1; echo "lint exit=$?"; cat /tmp/al7.txt
cd /workspace; git add …/play-gather-replica-io.yml
git commit -q -F - <<'EOF'
…
EOF
git log --oneline -1; git push 2>&1
```

`ansible-lint` exited 2. The exit code was **captured and printed** (`lint exit=2`). The
full diagnosis was **printed** (`cat /tmp/al7.txt`). Then `git add`, `git commit` and
`git push` ran anyway. An unloadable play sat on `main` for one commit.

The failure is not that I did not check. It is that **nothing consumed the check's result.**
A check whose outcome nothing acts on is not a check — it is decoration that produces the
feeling of having verified something.

---

## 2. Why the rule as stated would not have caught this

**The dangerous separator here was a NEWLINE, not a `;`.** The lint ran on line 1; the
`git add`/`git commit` were on lines 2–3 of a multi-line Bash command. In shell, a newline
terminates a command exactly as `;` does. A handler that scans for `;` between commands and
demands `&&` would have inspected line 1, found its internal `;`s, and never connected them
to the `git commit` two lines down.

So any rule in this space **must treat newline separation as equivalent to `;`**, or it is
trivially — and in this case accidentally — bypassed. This is the single most important
design point in this document, because the obvious implementation misses the motivating
incident.

---

## 3. Why blanket `&&` enforcement is the wrong rule

`&&` means "only if the previous command succeeded". A great deal of legitimate shell
deliberately does not want that, and this session is full of examples:

| Shape                                              | Why `&&` breaks it                                                                                                                                                                              |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `grep -q pattern file; echo done`                  | `grep` exits **1** when it matches nothing. That is a normal, expected result, not a failure. Chaining with `&&` aborts every search that finds nothing — which is often the answer you wanted. |
| `echo "=== A ==="; cmd_a; echo "=== B ==="; cmd_b` | A diagnostic sweep wants **all** sections even when one probe fails. This is the `plan::gather_leg` pattern the plan library formalises, and R7 explicitly sanctions it for read-only runs.     |
| `ls -1t dir_a; ls -1t dir_b`                       | Independent listings. One missing directory should not suppress the other.                                                                                                                      |
| `cmd > file 2>&1; echo "exit=$?"`                  | The whole point is to observe a non-zero exit. `&&` would skip the observation precisely when it matters.                                                                                       |
| `diff a b; echo "---"`                             | `diff` exits 1 on difference — the informative case.                                                                                                                                            |

A handler that fired on all of these would be **mostly wrong**, and a handler that is mostly
wrong gets disabled — which is the same failure mode the `#1288` backup gate was designed
around (a gate that cries wolf gets switched off, leaving you worse off than no gate).

There is also a correctness trap: `a && b; c` and `a && b && c` differ, and mechanical
rewriting of `;` to `&&` changes semantics in ways that can be *less* safe (a cleanup step
that must always run — `rm -f "$tmp"` — silently stops running).

---

## 4. The narrow rule that IS worth building

The dangerous shape is not "`;` between commands". It is:

> **a VERIFIER followed by a MUTATOR, without the verifier gating the mutator.**

That is high-precision and cheaply detectable. Concretely:

**Verifiers** (a non-zero exit means "do not proceed"): `ansible-lint`, `ansible-playbook --syntax-check`, `shellcheck`, `bash -n`, `pytest`, `ruff`, `golangci-lint`, `go vet`, `php -l`, `mypy`, `npm test`, `yamllint`, `hooks-daemon plan-qa`, `*/qa-version-check.bash`.

**Mutators** (state-changing, outward-facing, or hard to reverse): `git add`, `git commit`,
`git push`, `git tag`, `gh pr create`, `gh issue create`, `gh pr merge`,
`ansible-playbook` (without `--check`), `*-ansible-playbook`, `deploy.bash`-shaped plan
scripts.

**Fire when**: a verifier and a later mutator appear in the same Bash invocation, separated
by `;` **or a newline**, with no `&&` linking them and no explicit exit-code gate between
them.

**Do not fire when** any of these is present, because each is a correct way to consume the
result:

- `verifier && mutator` — the direct form.
- `verifier || { echo …; exit 1; }` — explicit failure branch.
- `rc=$?` followed by an `if`/`case` that branches on it.
- `set -e` in effect for the invocation (see §6).
- The mutator is inside a heredoc body or a quoted string (not actually executed).

The block message should not say "use `&&`". It should say **"`ansible-lint` can fail here
and `git commit` would still run — gate it"**, and show the two accepted forms. Naming the
specific pair is what makes the finding actionable rather than stylistic.

**Suggested severity: `warn` initially.** The verifier/mutator lists will need tuning
against real usage, and this is precisely the handler that must not cry wolf.

---

## 5. The handler that would have caught this more reliably

The chaining rule defends the *syntax*. There is a gap one level down that defends the
*outcome*, and it is the reason this bug reached a commit at all:

**`lint_on_edit` does not cover Ansible YAML.**

Verified: `handlers/post_tool_use/lint_on_edit.py` contains no reference to `yaml`, `yml` or
`ansible`. Its documented languages are Python, Shell, Go, PHP, Ruby, Rust, Swift, Kotlin
and Dart. `validate_eslint_on_write` covers TS/TSX. `plan_script_qa` lints plan-folder
`*.yml` against **R14 only** (does this play converge durable state) — not against whether
Ansible can load it.

So this repo — whose primary artefact is Ansible playbooks — lints every language it
touches **except the one it is written in.**

Had `lint_on_edit` run `ansible-lint` (or even just `ansible-playbook --syntax-check`) on
the Edit, the write would have been **denied at the moment I made it**, with the correct
diagnosis, before any commit was contemplated. No chaining rule needed, and it catches the
much larger class of "never ran the lint at all" — which the chaining rule cannot touch,
because there is nothing to chain.

**This is the higher-value change of the two.** Notes for implementing it:

- Only lint files that are plausibly Ansible: under `playbooks/`, `tasks/`, `roles/`, or a
  plan folder, or matching `play-*.yml` / `playbook-*.yml`. Do not lint arbitrary YAML —
  `.github/workflows/`, `hooks-daemon.yaml`, inventory `hosts.yml` and vault files are not
  playbooks and would produce noise or spurious failures.
- Run from the right project directory (`service/` vs `cluster/`), since `ansible.cfg`,
  `.ansible-lint` and the vendored collections all resolve relative to it. Getting this
  wrong makes the linter fail for the wrong reason, which is worse than not running it.
- `--syntax-check` alone is cheap and would have caught *this* bug (it is a load-time
  parse failure). Full `ansible-lint` is slower but catches `jinja[invalid]` and the rest.
  Consider syntax-check always, full lint at the `extended` tier — mirroring how
  `lint_on_edit` already splits cheap syntax check from deeper linter.
- Follow `lint_on_edit`'s existing denial semantics and say plainly that **the write has
  already landed** — a PostToolUse denial is a failure report, not a rollback.

---

## 6. Two cheaper mitigations worth considering alongside

**(a) Require `set -e` on multi-command Bash invocations that contain a mutator.**
One rule, no verifier/mutator taxonomy to maintain, and it fixes the entire class rather
than the enumerated pairs — `set -euo pipefail` at the top of my command would have stopped
at the failing lint. Downside: it changes semantics for every command in the invocation,
including the ones that legitimately expect non-zero (`grep`), so it trades one false-
positive surface for another. Probably best offered as the *remedy text* in the §4 block
message rather than enforced on its own.

**(b) Lint staged files at `git commit`.** The daemon already runs `plan_qa_commit_gate` on
every commit, so the hook point exists and the pattern is proven. Extending it to run the
appropriate linter over staged playbooks would catch the outcome regardless of how the
commit was invoked — chained, separate, or from a later turn entirely. This is the
belt-and-braces companion to §5's braces: §5 stops it being written, this stops it being
committed.

---

## 7. Recommendation, in priority order

1. **Add Ansible YAML to `lint_on_edit`** (§5). Highest value, catches the largest class,
   catches it earliest, and closes a genuinely surprising gap in an Ansible-first repo.
2. **Add the verifier-then-mutator chaining handler** (§4), in `warn` mode, **treating
   newlines as separators** (§2). Narrow, high-precision, and it generalises beyond Ansible
   to every language the repo lints.
3. **Extend the commit gate to lint staged files** (§6b) as the backstop.

Do **not** implement blanket `;` → `&&` enforcement (§3). It would have missed this
incident, and it would fire on correct code often enough to get itself turned off.

---

## 8. The honest caveat

None of these would have prevented the *original* mistake — writing an apostrophe into a
`shell:` block after having read the documentation that warns about it. They would have
caught it in seconds instead of in a push.

That is the right thing to optimise. The lesson from this plan, four times over now, is
that re-reading code does not find this class of defect and **executing it does** — so the
leverage is in making execution automatic and its result impossible to ignore, not in
trying harder to notice.
