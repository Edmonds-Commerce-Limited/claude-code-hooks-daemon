# Plan 00613 DESIGN: a sanctioned verb that links a protected file into a worktree

Task 1.2 of [PLAN.md](PLAN.md). The owner has answered; see
[Owner decision](#owner-decision). Sections 3 to 8 describe the verb, which is
NOT built; they stay as the record of how it would be.

All examples are synthetic. `<P>` stands for a repository-relative path that the
secret guard protects (for example a file matching a shipped default glob such
as `.vault-pass*`); `<wt>` stands for a linked worktree of the same repository.
No real protected file was read, opened or named while writing this document.

## 1. The request

A peer project's worktree workflow needs, inside every new worktree, a relative
symlink back to one protected file in the primary checkout (a vault password
file that a tool reads by path). `R-SECRET-BASH-MENTION` denies any Bash command
that names a protected path, `ln -s` included, so no agent can bootstrap such a
worktree. The peer proposes a verb, for example:

```
bin/hooks-daemon worktree-link-secret <wt> <P>
```

that creates exactly one relative symlink `<wt>/<P>` -> `../<...>/<P>` in the
primary checkout and does nothing else.

## 2. Threat model

### 2.1 What the guard protects

The secret guard's contract is that the CONTENTS of a protected file never reach
an agent's context by any route. Presence and metadata are deliberately
available (`Glob`, `bin/hooks-daemon secret-meta`). The verb must leave that
contract intact.

### 2.2 A link is itself a route to the content

The verb reads no content, but the link it creates is a new path that resolves
to the protected file. After it exists, any reader that follows links (`Read`,
`cat`, `grep`, `python3 -c "open(...)"`, `cp -L`, `tar -h`, `rsync -L`, an
editor) reaches the content through `<wt>/<P>`. So the verb is safe only if the
guard judges every read of a link by the link's RESOLVED path, not by its
spelling. Concretely, after the verb runs, the link makes these reachable unless
the guard resolves them:

| Route through the link                                         | Needs from the guard                                   |
| -------------------------------------------------------------- | ------------------------------------------------------ |
| `Read`/`Edit`/`Write` of the absolute link path                | realpath of the tool path (holds today)                |
| Bash naming the link by a RELATIVE token (`cat <P>` in `<wt>`) | realpath joined to the hook's `cwd` (Plan 00614 gap 1) |
| `Grep` / `grep -r` rooted at the worktree or a directory link  | index covering the link's target (Plan 00614 gap 2)    |
| Glob token through a directory link (`cat dir/*`)              | expand and realpath each match (Plan 00614 gap 3)      |
| Write-through or truncation (`> <P>`, `Edit`) via the link     | same resolution; the canonical file is mutated         |
| Dereferencing copy to an innocuous name (`cp -L <P> x.txt`)    | the mention of `<P>` must still deny the command       |

Two further properties of a link that a copy does not have:

- **Write-through.** A write or truncation through the link changes the
  canonical file in the primary checkout, for every worktree at once.
- **The link outlives the decision.** It stays in the worktree until the
  worktree is removed; revoking the owner's approval later does not remove
  links already made. The audit trail (section 7) is what makes them findable.

### 2.3 What the guard does today, and the dependency on Plan 00614

Task 1.1 ([subagent-reports/261116-symlink-resolution.md](subagent-reports/261116-symlink-resolution.md))
ran the real handler against synthetic repos. Absolute link paths are judged on
their resolved target in every tool. Three routes are NOT:

1. a RELATIVE Bash token naming a link, because the realpath step resolves it
   against the daemon PROCESS cwd (`/`), not the hook's `cwd`;
2. `Grep` / `grep -r` rooted at a directory link into another checkout when the
   project root is the worktree;
3. a glob through a directory link.

Route 1 is exactly what the verb creates: an agent in `<wt>` typing `cat <P>`
(relative) reaches the content today. These are being fixed under
[Plan 00614](../../00614-secret-guard-resolves-links-against-hook-cwd/PLAN.md).
As of this design, Plan 00614 on `main` is **Not Started** with every task
unticked; the coordinator reports a fix on a separate unmerged branch, which
was not verified here.

**Hard gate for Phase 2 of this plan.** The verb may not be built (or, if built
on a branch, may not be merged) until ALL of the following hold:

- Plan 00614 is merged to `main`, each of its three gaps covered by a test that
  failed before its fix, and the existing secret-guard suite green.
- The three routes are confirmed denied against a LIVE daemon through the
  socket (the Task 1.1 caveat: its verdicts came from calling the handler
  directly, not through a running daemon whose process cwd is `/`).
- The verb's own test suite includes the route table in 2.2 as end-to-end
  cases against a link the verb itself created (section 8, group C).

### 2.4 Out of scope for the threat model

- Content leaving through a TRUSTED consumer (for example a tool that reads a
  password file by flag): that already happens from the primary checkout and the
  link does not change it.
- A human reading the file: the guard governs agents only.

## 3. How the verb's own invocation reaches the daemon

The command `worktree-link-secret <wt> <P>` names a protected path, so as typed
it is denied by `R-SECRET-BASH-MENTION`, exactly like `ln -s`. The guard already
has one admission mechanism for a sanctioned helper naming a protected path:
the `secret-meta` exemption, which admits the daemon's own wrapper running that
subcommand as a SINGLE standalone statement (no `;`, `&&`, `|`, substitution).
The `allowed_consumers` mechanism (`ConsumerSpec`, flag-position paths for
`ansible*`) is the other, but it is configurable by the project, which is the
wrong owner for this exemption.

Design: the verb is admitted by the SAME standalone-statement rule as
`secret-meta`, hard-coded in the guard (not configurable, not extendable via
`allowed_consumers`). This is the ONE guard-side change the plan makes, and it is
pinned by tests that a hand-typed `ln -s <...>/<P> <wt>/<P>`, `cp`, `ln` with any
other flag, and the verb chained with anything else are all still denied
(Plan Task 2.2).

## 4. The verb's argument checks

All checks run before anything is created. Any check that cannot be completed
(an exception, an unparseable value, an unreadable source of truth) REFUSES; no
check defaults to "allowed".

### 4.1 Argument shape

- Exactly two positional arguments, `<wt>` and `<P>`. No flags that change
  behaviour (no `--force`, no `--absolute`, no `--name`), so there is no option
  an agent can reach for to widen it.
- Any NUL, newline or control character in either argument: refuse.
- `<P>` must be RELATIVE (no leading `/`, no `~`), must contain no `..`
  component, and must contain no glob metacharacter (`*`, `?`, `[`, `{`).
- `<P>` is the repository-relative path of the target in the primary checkout
  AND the link's path inside the worktree. The link name is not
  agent-choosable: an innocuous link name was the shape of every Task 1.1 gap,
  and keeping the protected name means a spelling match backs up the realpath
  match. (An anchored project glob then relies on resolution alone; that is why
  the Plan 00614 gate is hard.)

### 4.2 The target worktree

- Worktree identity comes from the PRIMARY checkout's
  `git worktree list --porcelain -z`, parsed strictly; a parse failure refuses.
- `realpath(<wt>)` must equal the realpath of one listed worktree entry. A path
  that is merely inside a worktree, a nested directory, a `.git` file pointing
  elsewhere, or another repository's worktree: refuse.
- `<wt>` must not be the primary checkout itself (a self-link is meaningless and
  a loop risk), must not be bare, and must not be marked `prunable`.
- The verb is run from, and reads config from, the primary checkout. A verb
  invoked from inside a worktree resolves the primary through
  `git rev-parse --git-common-dir`, and refuses if that is ambiguous.

### 4.3 The target file in the primary checkout

- `source = <primary>/<P>`. Every component is checked with `lstat` only
  (never `open`, never `stat` that follows): each parent must be a real
  directory (not a symlink), and the final component must be a regular file
  (not a symlink, not a directory, not a device or FIFO).
- `realpath(source)` must lie inside `realpath(<primary>)`. This repeats the
  existing seeding check (`utils/worktree_seeding.py` `_describe_problem`) for
  the "resolves outside the tree" case.
- `source` MUST be in the protected set (section 5). A path the guard does not
  protect needs no verb, and accepting it would make the verb a general link
  maker: refuse and point at plain `ln -s`.

### 4.4 The link inside the worktree

- `dest = <wt>/<P>`. Every parent component that exists must be a real
  directory inside `realpath(<wt>)` (lstat, not a symlink). Missing parents are
  created one at a time with `mkdir` (no `-p` through an existing link), each
  re-checked with `lstat` after creation.
- The link target is `os.path.relpath(source, dest.parent)`, never absolute.
  After computing it, `realpath(dest.parent / target)` must equal
  `realpath(source)`: a mismatch refuses.
- An existing `dest` of any kind (file, directory, link, dangling link) refuses.
  Creation is a single `symlink(2)` call, so a race that makes `dest` appear
  between the check and the call fails with `EEXIST` rather than overwriting.
  There is no check-then-unlink-then-create path.
- `dest` must not be tracked by git in `<wt>` (`git ls-files --error-unmatch`)
  and should be git-ignored (`git check-ignore`); if it is not ignored the verb
  refuses rather than leave a link that a `git add -A` would commit.

### 4.5 Fail closed

Every refusal exits non-zero with a reason that names the CHECK that failed and
the argument by role (`target worktree`, `protected path`), never the
protected path's content and never a guess at what the caller meant.

## 5. How the protected set is read

- Patterns, never content. The verb asks "is `source` protected?" with the
  same matcher the guard uses (`protecting_pattern` over the effective globs),
  which looks at paths and realpaths only. Like `secret-meta`, the verb learns
  the file's existence and type from `lstat` and nothing else; it does not
  compute a digest because it has no need for one.
- The authoritative config is the PRIMARY checkout's
  `secret_file_guard` options (`protected_paths`, `mode`), because the target
  lives there.
- A STRICT read, unlike `resolve_configured_patterns()`, which deliberately
  falls back to the shipped defaults when the config cannot be loaded. That
  fallback is right for a seam-closer that must still protect; it is wrong here,
  where the read decides whether to CREATE something. The verb refuses when the
  config is unreadable, unparseable or schema-invalid, and refuses when the
  effective set is empty (`mode: replace` with an empty list).
- The verb never edits, extends, or re-orders the protected set.

## 6. What the verb must NOT do

- Never open, read, hash, copy, print or stream the protected file, and never
  print the link target's resolved absolute path (the relative target is
  enough to report).
- Never create anything other than the one link and the parent directories it
  needs; never create an absolute link; never create a hard link.
- Never widen, add or relax any glob, pattern, consumer entry or exemption, in
  config or in code.
- Never accept an agent's assertion of authorisation: no `--approved`, no
  reason string that turns a refusal into a success, no environment variable,
  no "the owner said so" argument. Whether the verb exists at all is the
  owner's decision (Owner decision needed, Q1 and Q2); once it exists its checks are the only gate.
- Never follow a link while checking (lstat everywhere until the final
  realpath equality checks).
- Never run on behalf of a project that has not enabled it (Owner decision needed, Q4).

## 7. Audit trail

- Every invocation, success or refusal, appends one JSON line to a daemon-owned
  log under the primary checkout's daemon `untracked/` directory: UTC time,
  verb, outcome, refusal check id, worktree path, the repository-relative `<P>`,
  the protecting pattern, session id when present. Never content, never a size,
  never a digest.
- A SEPARATE read-only verb (for example `worktree-secret-links`; the create
  verb itself takes no flags, section 4.1) reports every live link the verb created, by
  walking the log and `lstat`-ing each recorded `dest`, so a revoked decision
  can be acted on.
- The SessionStart `secret_file_hygiene_checker` can report a link still
  present in a worktree whose log entry is missing (made by hand or by another
  tool), as an advisory.

## 8. Tests (red first)

Written before any code, each seen failing first; synthetic repos only, the
"protected" file a dummy matching a shipped default glob.

A. Argument checks (unit, one failing test per refusal):

- `<wt>` not a registered worktree; `<wt>` the primary; `<wt>` another
  repository's worktree; `<wt>` a subdirectory of a worktree; prunable worktree.
- `<P>` absolute; `<P>` with `..`; `<P>` with a glob character; `<P>` with NUL
  or newline; `<P>` through a symlinked parent in the primary; `<P>` a symlink;
  `<P>` a directory; `<P>` resolving outside the primary; `<P>` not protected.
- `dest` exists as file, directory, link, dangling link; a parent of `dest` is
  a symlink (inside or outside `<wt>`); `dest` tracked by git; `dest` not
  ignored.
- Config unreadable, malformed YAML, schema-invalid, empty effective set: each
  refuses (contrast test: `resolve_configured_patterns` falls back, the verb does
  not).
- Race: `dest` created between check and `symlink` -> `EEXIST` refusal, the
  pre-existing file untouched.

B. The one success: exactly one new filesystem entry, a relative symlink whose
`readlink` equals the expected relative path, `realpath` equal to the source;
the protected file's bytes, mode and mtime unchanged; the verb's stdout and
stderr contain no byte of the dummy content; one audit line written.

C. Guard behaviour after the link exists (end-to-end through a live daemon,
requires Plan 00614): from `<wt>`, `Read` absolute link, `cat <P>` relative,
`cat < <P>`, `python3 -c` open of the relative link, `grep -r` rooted at `<wt>`,
`Grep` tool, `cp -L <P> x.txt`, `> <P>` truncation: all denied.

D. Guard unchanged elsewhere (Plan Task 2.2): hand-typed `ln -s` / `ln` /
`cp` naming `<P>` denied; the verb chained with `;`, `&&`, `|` or inside a
substitution denied; the verb with an extra flag denied; the existing
secret-guard suite green.

## 9. Alternatives considered

| Option                                                                                              | What it is                                                                                                                              | Risk                                                                                                                                                                                                                       | Work                                                                                                  |
| --------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| A. The verb (this design)                                                                           | Agent-invocable command creating one relative link                                                                                      | A new guard exemption an agent can invoke; every link is a read route closed only by Plan 00614; write-through                                                                                                             | Plan 00614 merged and live-verified; the verb; one guard exemption; groups A-D of tests; audit log    |
| B. Config-declared seed list at worktree creation (`worktree_create` `seed`, SHIPPED by Plan 00267) | The project lists `<P>` under the handler's `seed` option; the daemon links (or copies) it when Claude Code's WorktreeCreate hook fires | Same read route as A (same Plan 00614 dependency); covers only worktrees created through the harness hook, not a hand-run `git worktree add`; the list is in config the human owns, so no agent-invocable exemption exists | None to enable for harness-created worktrees; a protected-set awareness check and docs are follow-ups |
| C. Copy-seeding (B with `mode: copy`)                                                               | The daemon copies the file into the worktree                                                                                            | Content duplicated under a worktree path; a path-anchored project glob may not cover the copy, so it can become unprotected; a copy can be committed by `git add -A`; drifts from the canonical file                       | None (shipped); but needs a check that the copy is still protected before it is safe                  |
| D. Human-run command only                                                                           | The owner types the `ln -s` (or a verb that refuses when not run by a human) once per worktree                                          | Lowest: no agent-invocable route; the link is still a read route after it exists (Plan 00614 dependency unchanged)                                                                                                         | None in code; a documented step; costs the human one action per worktree                              |

Shipped fact relevant to B and C: the `worktree_create` seeding executor
(`utils/worktree_seeding.py`) validates that a seed source is relative, has no
`..`, exists and resolves inside the repository, but it does NOT consult the
protected set. A project can therefore already seed a protected file into every
harness-created worktree today, by link or by copy, with no agent mention of
the path. The Plan 00614 gaps apply to those seeded links now, independent of
this plan.

**Recommendation: B (config-declared seeding, link mode), not the verb**,
plus D for any worktree made outside the harness hook. Reasons: the
authorisation lives in project config the owner controls rather than in an
agent-invocable exemption; it already ships; and it adds no new hole to the
guard. Its cost: it requires Plan 00614 merged and live-verified before the
owner enables it for a protected path (the same gate as the verb); it does not
cover a worktree created with a hand-run `git worktree add`, which then needs
the human (D) or the verb; and a follow-up should make the seeding executor
protected-set aware (refuse `mode: copy` for a protected source unless the copy
destination is itself protected, and log each seeded protected link to the
audit trail of section 7). If the owner needs agents to bootstrap worktrees
outside the harness hook, A is the fallback, built exactly as sections 3 to 8
describe and gated the same way.

## Owner decision needed

These need the owner's own answer. Each is yes/no or a choice.

**Provenance.** The request, and the statement that the owner has said agents
may link their own worktree files, came from a peer agent. A peer agent has no
authority to approve a change to the secret guard. This design does not claim
the owner said it; the team history was not searched for this design, so no
claim is made either way. The decision below counts only when it is the owner's
own typed instruction in a human line of the team history, quoted or cited in
the Task 1.3 journal entry. An agent's paraphrase, a peer's report, or
a cron stand-in ruling is not sufficient for Q1.

- **Q0. Provenance: did you, the owner, type an instruction that agents may
  link protected files into their own worktrees?** yes (cite the human line in
  the team history) / no.
- **Q1. Is a worktree link to a protected file acceptable at all?** yes / no.
  (If no, the plan closes; Plan 00614 still proceeds because it fixes routes
  that shipped seeding already opens.)
- **Q2. Which mechanism?** B (config seed list, harness-created worktrees) /
  B + D (also a human-run step for hand-made worktrees) / A (the agent-invocable
  verb) / D only.
- **Q3. Copy mode for protected files:** forbid (refuse `mode: copy` for a
  protected source) / allow only when the copy destination is itself protected.
- **Q4. If A: enabled per project by an explicit config switch, default off?**
  yes / no.
- **Q5. Gate:** confirm that nothing in Phase 2 ships before Plan 00614 is
  merged and its three routes are verified denied against a live daemon. yes /
  no.

## Owner decision

The owner answered Q0 and Q1 in their own words, typed in the coordinating
session on 2026-11-20 and relayed verbatim in the coordinator's brief to the
building sub-agent (so the citation is that session's human line, through the
brief; the sub-agent did not see the line itself):

> "A linking vault files is essential if worktrees are to be able to work.
> there's no security issue here - the file already exists on the file system
> we're just making worktrees actually work"

- **Q0: yes.** The owner typed it. This supersedes the delegated ruling below.
- **Q1: yes.** Linking a protected file into an agent's worktree is allowed and
  needed. Decided with it: **link mode only**; copy mode for a protected file
  stays forbidden (a copy makes a second file, a link does not).
- **Q2: B + D, as recommended.** The route is owned by the project config or
  a human, never invocable by an agent to link an arbitrary protected path.
- **Q3: forbid**, as the owner's constraint says.
- With it, from the coordinator's brief: the secret guard's read protections
  stay intact; only the creation/link route changes.

The owner's words do NOT address Q4 or Q5. What follows is the BUILDER's
settlement (the implementing sub-agent, 2026-11-20), not the owner's, and the
coordinator should treat Q5 as a merge gate.

- **Q2 mechanism (builder).** The human-run step is `hooks-daemon seed-worktree <worktree>`: it re-applies the configured list and takes no
  path of its own, so what is linked stays the config's decision. It is
  agent-runnable; the authority is the config, not the invoker.
- **Q4: moot** (no verb).
- **Q5 (builder; a merge gate for the coordinator).** Evidence, through the
  handler and not a live daemon socket: links placed by `seed_worktree`, hook
  cwd in the worktree, are refused for Read, Edit, Grep and relative Bash
  reads, including a file covered only by a project glob, with the daemon root
  at the main checkout or at the worktree. The gap the 261120 handoff pinned
  (`grep -R` from the worktree descending a directory link to a file only a
  project glob covers) is closed: `utils/link_reach.py` judges what lies
  behind each link below the root of every recursive read not proven to
  follow no link, failing closed on what it cannot resolve. Not done: the
  live-socket check.
- **Residual 1 (builder, narrowed).** `seed-worktree` places a link entry
  whose source is, holds or links to a protected path (by the working or the
  committed config) only when the config committed at `HEAD` of the main
  checkout lists the same entry. An agent's uncommitted seed-list edit is
  refused; an agent that also commits the edit is not stopped, so the route
  now leaves a commit behind rather than being closed.
- **Small points (builder), each journalled:** the audit line records the
  route (`verb`); the command checks the worktree against git's own list by
  realpath, refuses the main checkout, a subdirectory, a prunable entry, a
  disabled `worktree_create`, and a destination parent inside the worktree
  that is a symlink; the config is read strictly and fresh from disk
  (`.yaml`, else `.yml`); and the config-edit route (an agent editing the seed
  list) is answered by visibility (the session-start drift report counts it),
  not by a circular deny.

## Rulings

Superseded for Q0 to Q2 by the owner decision above; kept as the record.

Settled by a fable sub-agent under the owner's delegation, 2026-11-19. These
are NOT the owner's own words; a later owner message overturns any of them.
The delegation reached the sub-agent through the coordinating session, so the
rulings are shaped to need no owner authority: none of them loosens the secret
guard, and none creates a route an agent can invoke.

- **Q0: not verified, treated as no.** No human line saying agents may link
  protected files into their worktrees is cited anywhere in this plan, and a
  sub-agent cannot answer for the owner on a fact about the owner. Nothing
  below relies on such a line.
- **Q1: yes, but only by a route a human owns.** A worktree link to a
  protected file is acceptable when the project's own config declares it (B)
  or a human types it (D). It is not acceptable by any route an agent can
  invoke. Reason: the provenance clause above says a ruling that is not the
  owner's cannot approve a guard exemption, and B and D need none. B already
  ships, so this permits nothing new.
- **Q2: B + D. The verb (A) is not built.** Config seed list in link mode for
  harness-created worktrees; a documented human-run `ln -s` for a hand-made
  worktree. Sections 3 to 8 stay as the record of how A would be built. A is
  reopened only by the owner's own typed yes to Q0 and Q1, cited in a journal
  entry.
- **Q3: forbid.** The seeding executor refuses `mode: copy` for a source in
  the protected set. Reason: a copy duplicates content under a path a
  project-anchored glob may not cover, can be committed by `git add -A`, and
  drifts. "Allow when the destination is protected" needs a second judgement
  that can be wrong; link mode covers the need.
- **Q4: moot while A is not built.** If the owner reopens A: yes, a per-project
  config switch, default off.
- **Q5: yes, and the gate is wider than written.** The Plan 00614 fix now
  lands through Plan 00623, which merges its branch. Until both are on `main`
  and the three routes are verified denied through a live daemon socket, no
  document tells a project to seed or hand-link a protected path, and no code
  that eases doing so is merged. Gap 1 is live on `main`, so a seeded link to
  a protected file is readable by a relative Bash token today: the same gate
  applies to advising D.

What may be built before the gate, because it only tightens: the copy refusal
(Q3), and the audit line for a seeded protected link (section 7, reduced to
the seeding executor). What waits for the gate: the install-guide text that
shows a project how to declare a protected seed and the human step for a
hand-made worktree, and group C of section 8 run against a seeded link.

Still needs the human: Q0, if the owner wants the verb; and the owner's own
confirmation of Q1 before Phase 3 advises anyone to link a protected file,
because the provenance clause says a ruling that is not the owner's is not
sufficient for Q1. Phase 2 needs neither. Safe default: no verb, and Phase 3
waits.
