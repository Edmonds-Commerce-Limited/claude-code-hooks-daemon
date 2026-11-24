# Security decisions: Q66 housekeeping (Plan 00627 Phase 6B) and N720 (secret-file guard hatch)

Author: Fable sub-agent, read-only apart from this file. Tree read: main at `ea918950b`.

**Status of both rulings: delegated recommendation, not an owner line.** The delegation reached this agent through the coordinator's brief, which is an agent message. The Q66 HUMAN line is also known only by relay (`00627/JOURNAL/2026-11-23/221450Z-decision-3070c3.md`). Task 6B.0's precondition (a verified HUMAN line) is unchanged by this report, and the owner may overturn anything below.

## Decision A: Q66, may `scratch-sweep --apply` and `worktree-reap --reap` run without a terminal?

### Recommendation

**Option C, a narrowed A: yes, but only for the reversible half plus the proved half.** Without a terminal the daemon may pack due scratch into the verified archive store and may expire archives whose verdict was DISPOSABLE. Everything that deletes unproved content for good, widens the run, or leaves the default scratch root keeps the typed confirmation. An unreadable or partial proof acts on nothing.

### What may be unattended, case by case

| Act                                                                                          | Without a terminal | Why                                                                                                                                                                                         |
| -------------------------------------------------------------------------------------------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Pack a due DISPOSABLE entry, default root `untracked/scratch` of the main checkout           | Yes                | Positive proof for every file (DESIGN.md:84) and the step is reversible (`restore`)                                                                                                         |
| Pack a due UNCERTAIN entry, same root                                                        | Yes                | No proof, but nothing is lost: a verified archive exists before removal (DESIGN.md:214-228). This is what relieves the directory count                                                      |
| Expire an archive packed as DISPOSABLE                                                       | Yes                | Proof plus the hold (`scratch.archive.disposable_hours`, default 12, `config/models.py:2757`)                                                                                               |
| Expire an archive packed as UNCERTAIN                                                        | **No**             | This is the one irreversible deletion of unproved content. The ruling as relayed says what the proof cannot clear is "kept, never deleted silently" (PLAN.md:125). A held archive is "kept" |
| Pressure mode (packing entries not yet due)                                                  | No                 | Its safety argument is consent bound to the typed prompt (`cli.py:6935-6954`). Caps are `advise` here (`.claude/hooks-daemon.yaml:1999-2000`), so nothing needs it yet                      |
| `--root` naming any other `untracked/<dir>`                                                  | No                 | A finite TTL on another directory is one config line; `logs/*.log` already passes proof P1 (DESIGN.md:200)                                                                                  |
| `--apply` from a linked worktree (Task 6.1)                                                  | No                 | Two OPEN rows: shared-prefix expiry (DESIGN.md:438) and session children that cannot be restored once the worktree is gone (DESIGN.md:436)                                                  |
| `worktree-reap --reap` of a worktree with no blockers                                        | Already yes        | Existing behaviour, see the fact-check below                                                                                                                                                |
| Evacuate a merged worktree's scratch, every root-level entry due and DISPOSABLE or UNCERTAIN | Yes                | Packing into the main store is reversible; the all-or-nothing gate and the re-reads stay (DESIGN.md:354-358)                                                                                |
| Evacuate entries not yet due                                                                 | No                 | The gate packs them only under consent bound before the question (DESIGN.md:354). Without a human the worktree waits until the entries are due                                              |
| Evacuate a worktree whose scratch holds an `s-*` session directory                           | No                 | Kept today because restore cannot recreate the directory (DESIGN.md:353, N691)                                                                                                              |
| Branch delete after a reap                                                                   | Yes, as today      | `git branch -d` only, merged only, no `--force` (DESIGN.md:358)                                                                                                                             |
| PROTECTED, KEPT, REFERENCED, STUCK                                                           | Never, either mode | `ACTIONABLE` is DISPOSABLE and UNCERTAIN only (`scratch_archive_apply.py:96`)                                                                                                               |

### Reasons, with evidence

1. **The gate's own stated condition for removal has been met.** `confirm_apply_interactively` says the gate exists "until an archive can be kept in advance (Task 4.4) and the coming expiries are announced (Task 5.2)" (`cli.py:7101-7105`). Both tasks are ticked (PLAN.md:100, :106).
2. **The gate does not stop a deliberate agent and was never claimed to.** A pseudo-terminal answers both phrases; this is recorded as accepted (`dangerous-invocation-corpus.yaml:583-602`, DESIGN.md:356, :416). So the gate's real job is stopping an automatic or careless run, and a proof-gated path does that job better than a terminal test.
3. **The gate pushes agents towards a worse tool.** The register names `rm -rf` as an outcome nothing denies (`Security/UnenumeratedSpelling.md:18`, :64). An agent blocked from the archiving sweep can still delete scratch by hand with no proof, no archive and no record. Refusing the safe route does not remove the unsafe one.
4. **The proof covers less than `--apply` acts on.** This is why the answer is not a plain A. `--apply` packs UNCERTAIN, which is the default verdict and carries no proof (DESIGN.md:77, :80). Its protection is the hold and the per-session announcement. With no human in the loop the announcement reaches agents only, so UNCERTAIN expiry is the step that stays typed.
5. **Worst deletion a wrong proof could cause.** Bounded to ignored content under a first-level `untracked/<key>` root with a finite TTL (`SweepRoot.apply_refusal`, DESIGN.md:415); never a tracked file (an entry holding one is PROTECTED, DESIGN.md:204), never `untracked/repos`, a reference root or the store (DESIGN.md:198), never across a link or a second device (DESIGN.md:230-236). Inside that bound the realistic losses are:
   - **P1 trusts a basename.** A valuable file named like a log or message body (`*.log`, `qa-*`, `push-*`, `core/scratch_verdict.py:58-76`) is DISPOSABLE and is gone once its hold ends. The design accepts this (DESIGN.md:98).
   - **P7.** A standalone `git init` repository holding real work is DISPOSABLE by owner ruling R7a (DESIGN.md:109).
   - **An open file descriptor.** A process writing through a descriptor into a packed entry loses those writes; OPEN (DESIGN.md:410).
   - **An alternates borrower outside the swept root.** A lender judged DISPOSABLE breaks a borrowing clone in another first-level root or under `untracked/repos`; OPEN (DESIGN.md:415). This is the only route by which a scratch sweep can damage something outside scratch, so it is a precondition below.
   - Recoverable until expiry through `scratch-sweep restore`; not recoverable after.
6. **Who can trigger it.** Any model in any session, including a sub-agent. The same model can edit `.claude/hooks-daemon.yaml`, where `disposable_hours` and `uncertain_hours` accept 1 (`config/models.py:2757-2758`) and `untracked_ttl` can give another directory a finite TTL. So the unattended path must not take its floors from config (safeguard 4).
7. **Operational pain, as measured here.** The merged-branch pool read 10 of 10, then 9 of 10, during this session (hook advisory). The scratch caps are in `advise` mode in this repository, so they do not block work yet; that pain is prospective until Task 8.3.

### The other options the brief named

- **Dry-run-then-apply with a recorded plan hash**: rejected. The design's rule is that "a cached verdict never authorises an action" and every git fact is rebuilt for the apply run (DESIGN.md:218). A recorded plan would be a cached verdict, and the fresh classification already does the job better.
- **A rate limit or time box**: not needed for packing, which is reversible, and it would not help the one irreversible step, which is withheld instead.
- **B, keep the terminal**: rejected for reasons 2 and 3 below; it keeps a gate that a pseudo-terminal answers while leaving hand deletion open.

### Fact-check findings the owner and builder should know

- **PLAN.md:125 describes existing behaviour as part of the loosening.** "A merged worktree whose leftovers all match the regenerable globs" is already reaped with no terminal: when `worktree_blockers` returns nothing, `reap_worktree` runs under `--reap` with no question (`cli.py:11205-11238`; blockers at `branch_cleanup.py:442-485`). The only terminal gates in the code are the two `isatty` sites: `cli.py:7110` and `worktree_evacuate.py:114`. The loosening is therefore exactly two things: the `--apply` question and the evacuation question.
- **"The typed confirmation remains only for that residue" (PLAN.md:125) is not accurate for `scratch-sweep`.** No typed phrase unlocks PROTECTED, KEPT, REFERENCED or STUCK in either mode. What a typed run adds over an unattended one is the list in the table above (UNCERTAIN expiry, pressure, other roots, not-due evacuation). Task 6B.3 should be reworded to that list.
- **The `s-*` rule may hollow out the pool relief.** Since Task 4.1, agents write scratch inside a per-session directory (PLAN.md:96), and a worktree holding one is kept (PLAN.md:118, :129). So an unattended reap clears legacy root-level scratch but probably not a worktree used after Task 4.1 shipped. If the pool is the pain, N691 (restore recreating a session directory) has to land before Task 6B.1, or 6B.1's test will pass and the pool will stay full. I did not measure how many live worktrees hold `s-*` directories.
- **N714's addendum lists three causes for a stuck pool and Q66 fixes one.** The other two (a worktree path absent from a container; an unmerged origin copy) are untouched by Phase 6B (NIGGLES.md:8371).

### Safeguards the build must have

1. **Preconditions before any no-terminal run outside tests**: Task 3.9's independent review complete (PLAN.md:90, unticked), fixes A and B reviewed (PLAN.md:91), and the OPEN rows DESIGN.md:410 and :415 closed or made fail-closed in unattended mode (for :415, a DISPOSABLE repository entry is held STUCK while any other first-level root or `untracked/repos` has not been read for borrowers).
2. **An explicit flag** (for example `--unattended`). A run with no terminal and no flag is refused exactly as today, so an existing script never changes behaviour silently, and the log states which mode ran.
3. **Fail closed, pinned in the unattended mode** (Task 6B.4): incomplete walk, unknown liveness, unknown references, no live remote answer, store lock busy, torn index or events file, a root that is a link, a filesystem with no birth time. Each acts on nothing, exits non-zero and prints the reason.
4. **Floors held in code, not config**, for the unattended mode only: DISPOSABLE hold at least the shipped default, root TTL at least the shipped default, UNCERTAIN archives never expired. A config below a floor is not an error; it just means that run needs the typed confirmation.
5. **Default root only, main checkout only** for `--apply`; evacuation from the main checkout only (already true, `worktree_evacuate.py:206-211`).
6. **A record a human sees.** Every unattended run appends one record (mode, counts by verdict, archive ids, restore lines) to the store's events file, and the SessionStart report gains "packed unattended" and "DISPOSABLE archives expiring next" lines. UNCERTAIN archives awaiting a typed expiry are listed there too, with the command.
7. **The owner sees the first real dry run before the first unattended apply** on this repository's backlog (Task 8.1, PLAN.md:143). Phase 6B does not waive that.
8. **Corpus rows updated**: `pty-answers-scratch-apply` and `pty-answers-worktree-evacuation` are re-worded so they describe the typed residue only.
9. **The property test is extended to the new mode**: an unattended run never changes a path a fresh classification calls LIVE, KEPT, PROTECTED, REFERENCED or STUCK, never expires an UNCERTAIN archive, and never packs an entry not yet due.

### Residual risk

- A mis-named valuable file (P1) and a standalone repository with real work (P7) are deleted once the DISPOSABLE hold ends, with no human having seen the list. Both are accepted design limits today; the change is that no person types a phrase first.
- UNCERTAIN archives accumulate until someone runs a typed expiry. They are flat files in one directory, so the link index is unaffected, but the byte cap will eventually name them. If the owner wants no human step at all, the next ruling to ask for is "UNCERTAIN expiry unattended", best taken after the Phase 8 dogfood shows what the UNCERTAIN class actually holds.
- A model that edits config and then runs the sweep is limited by safeguard 4 only as far as the floors reach.

### What the independent security review must check

- No code path in the unattended mode reaches `_expire` for an UNCERTAIN record, pressure, a non-default root, or a not-due entry; each has a test seen red.
- Each fail-closed input of safeguard 3, one at a time, in both commands.
- The floors cannot be lowered through config, an environment variable, `--root`, or a symlinked root.
- The evacuation re-reads (after packing, before `reap_worktree`) still run when no question is asked; `asked` drives them today (`cli.py:11195-11200`, :11215), so a mode that never asks must not skip them.
- Fixes A and B (struct layout for birth time, foreign-owner refusal) and the Task 3.0 rows, which Task 3.9 already owes.
- TOCTOU between the fresh classification and the claim, now that no human pause separates them (DESIGN.md:219-220).
- That branch deletion remains `-d` and that `--reap-branches` is not implied.

### What I could not verify

- The Q66 HUMAN line itself, and the owner's delegation, beyond the coordinator's word.
- `core/worktree_scratch_evacuation.py` `evacuation_gate`: taken from DESIGN.md:354, not read.
- The proofs P2 to P7, the liveness reading and the reference set are described from DESIGN.md, not from their code. I read the code for the two terminal gates, the reap loop, `worktree_blockers`, `ACTIONABLE`, the pressure and actionable predicates, the retention defaults and the P1 globs only.
- Which of the merged-pool branches are in the Q66 class; I ran no sweep or reap dry run.
- Whether the "daily report" PLAN.md:125 mentions exists as a surface distinct from the SessionStart report.

## Decision B: N720, should the secret-file guard get a declared-intent hatch?

### Recommendation

**Option B, narrowed, and only for the one class the guard cannot judge.** Fix the plain defects now. Freeze the option-switch keyword list. For a command whose glob-relevant shell state cannot be established, soft block only when the same command also holds a glob that would reach a protected file under the conservative reading; allow the same command when it carries `MUST_ALLOW_UNSTATICABLE_SHELL_BECAUSE="reason"`. A literal protected path, or any positive finding, stays a hard deny that no hatch can lift.

### The threat model, as the repository states it

- **Adversary**: a careless agent. "The daemon helps an agent that makes mistakes. It does not defend against an agent that sets out to defeat it" (`ARCHITECTURE.md:786-798`). Prompt injection is explicitly not defended (`ARCHITECTURE.md:800-807`). A human lifts protection by editing config (`secret_file_guard.py:21-23`).
- **Asset**: a protected file's contents entering context, and so the transcript. That is irreversible, which is what separates this guard from the comment-size or stash hatches.
- **What a determined agent already gets round**: by the document's own list, anything whose operative text is not visible (`bash -c "$X"`, `eval "$cmd"`, `source f`, `printf -v`), and anything that stops the daemon (`ARCHITECTURE.md:826-834`). The guard calls itself "defence in depth over an OS boundary" (`secret_file_guard.py:35-37`).
- **So the guard's job** is to stop accidental reads by ordinary routes and to make a deliberate one loud. The owner's view in the brief matches the written model.

### What the written doctrine says about each option

All three options in the brief depart from text the owner has already ruled, and so did the earlier recommendation O8 in `261124-blockers-unblock-fable.md`:

| Option                         | Conflicts with                                                                                                                                                                             |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| A, fail closed with no hatch   | Owner ruling A1: "Fail-closed is too problematic. Deliberate evasion is out of scope" (`00483/OWNER-RULINGS-261005.md:12-13`); deny only on a positive finding (`ARCHITECTURE.md:854-865`) |
| B, soft block with a hatch     | "No guard gains an escape hatch an agent can type (Plan 00259)" (`ARCHITECTURE.md:866-867`); `secret_file_guard.py:21-23`, :114, :2132                                                     |
| C, keep extending the keywords | "Code that already catches an out-of-scope shape is kept ... and it is not extended" (`ARCHITECTURE.md:874-876`)                                                                           |

Under the document as written, most of N720 item 3 is simply out of scope (`eval`, `source`, `printf -v` are named at `ARCHITECTURE.md:829-830`; a quote inside a keyword has "no working purpose other than defeating a parser", :831) and would be recorded `Dismissed (threat model)` with corpus rows (`ARCHITECTURE.md:841-845`). That zero-build route is the fallback if the owner declines to amend the doctrine.

### Reasons for B, narrowed

1. **It is a tightening against main, provided the check order below holds.** N720's title says every reproducer is "also allowed on main" (NIGGLES.md:8427). Today these commands run; under the recommendation the dangerous subset is stopped once. The condition matters: on a host where the guard is already on the conservative reading (no snapshot proves the options off, `shell_snapshot.py:9-15`), a glob that reaches a protected file is denied today. If adding `eval` to such a command moved it into the soft-block step, the hatch would lift a deny that exists on main. Step 1 of the design is written to prevent exactly that.
2. **An advisory arrives too late for this asset.** A1's "allow with a loud advisory" is right when the cost of a miss is recoverable. Here the advisory lands after the bytes are in the transcript. A deny-once costs one round trip and lands before.
3. **A hard deny on the construct alone would hit everyday work.** `source` and `trap` are ordinary (`source .venv/bin/activate`, `trap cleanup EXIT`). "Deny any command with these when a protected link exists" is the over-deny A1 was written against, and the list of unstaticable constructs is itself an enumeration, the very weakness N720 names.
4. **The machinery for the narrow trigger exists.** The guard already has two readings of a glob: bash's default, and a conservative one used when a snapshot does not prove the options off or when the command "runs `shopt` or `set -O` itself" (`utils/shell_snapshot.py:9-17`). The unstaticable class only needs to select the conservative reading. Then the question the guard asks is the one it can answer: does this glob reach a protected file if the options are on?
5. **A hatch on an unjudged case does not self-authorise disclosure of a known secret.** Plan 00259's argument is "an agent that can type its own justification has self-authorised disclosure". That holds where the guard has a positive finding. In the unjudged case the guard knows nothing, and the agent is declaring only that it accepts an unverified shell state.

### Design (the simplest that matches the threat)

Order of checks in the Bash route, each earlier check final:

1. **Positive finding, hard deny, no hatch**: everything the guard denies today stays denied, judged as if the unstaticable construct were not there. That covers a literal protected path or name; a glob or recursive search that reaches a protected file under whichever reading the guard would already use for this command (bash's default, or the conservative one when no snapshot proves the options off, or when a literal switch such as `shopt -s ...`, `GLOBIGNORE=` or `bash -O ...` is visible); and every `Read`/`Write`/`Edit`/`Grep`/script-authorship route.
2. **Unstaticable state plus a reaching glob, soft block**: reached only when step 1 found nothing, and only when the construct ALONE is what selects the conservative reading. The command holds a construct that can change glob state invisibly (a command word built by expansion, `eval`, `trap`, `printf -v`, `--rcfile`, `source` or `.`) AND a glob word that reaches a protected file or link under the conservative reading. Deny, explain, and name both ways out: run the glob in a separate command from the construct (shell options do not persist between Bash calls), or repeat the command with the hatch.
3. **Unstaticable state, no reaching glob**: allow, silently. This is the `source .venv/bin/activate && pytest` case and it must cost nothing.
4. **No index available**: unchanged (advisory, `secret_file_guard.py:190-194`).

Rules for the hatch:

- **It applies to step 2 only.** A test pins "hatch plus a literal protected path is denied", and another that the hatch text changes no other verdict.
- Reason hygiene through the shared `utils/escape_hatch.py` `is_acceptable_reason` (:50-68); a rejected reason leaves the deny in place.
- The deny text names no protected file, following the search route's rule that the reason "names the remedy, never the file" (`secret_file_guard.py:152-154`).
- One config key under `handlers.pre_tool_use.secret_file_guard.options` lets a human turn the hatch off, which makes step 2 a hard deny for that project.
- The keyword list is frozen. The structural test "the command word contains an expansion" replaces further keywords.

### Audit trail

The verdict log already writes a synthetic `override` record for any `MUST_..._BECAUSE` marker (`daemon/verdict_log.py:39-47`, :112, :196-204), so the base exists. For this hatch the record must hold: UTC time, session id, agent or sub-agent id, rule id, which unstaticable construct fired, the reason text verbatim, a SHA-256 of the command and the command text passed through the existing secret redaction, the working directory, the COUNT of protected files the conservative reading reached (never their names), and the index's freshness. It must also reach a human: a SessionStart line and a status surface stating how many times the hatch was used since the last human prompt. A log only the model reads is not an audit trail.

### Where this would be a genuine loosening

- **Against written doctrine**: this is the first typed hatch on the secret guard. `ARCHITECTURE.md:866-867` and `secret_file_guard.py:21-23`, :114 and :2132 must be amended to say "no hatch lifts a positive finding", and the acceptance pattern at :2181 updated. The precedent risk is real: the next request will be to extend the hatch to a glob finding or a literal path.
- **It becomes a real loosening the moment the hatch can lift step 1.** `ARCHITECTURE.md:868-869` keeps protected-path disclosure human-gated; nothing in this recommendation changes that.
- **Against the fail-closed proposal in N720 and O8**: weaker, by design.

### Residual risk

- A careless agent meets the deny, adds the hatch by reflex, and the read happens. This needs the invisible construct to have actually switched a glob option, which is rare, but it is the case the hatch concedes. The human-visible count is the mitigation.
- The list of unstaticable constructs is finite (`BASH_ENV`, an alias, a function from a profile are not on it). Those remain out of scope and should get `UNCOVERED-accepted` corpus rows.
- A hostile or injected agent is unaffected by any of this; it has `python -c` with a built path. That is outside the model.

### Buildable now, independent of the owner's choice

Each is a plain defect: test-first with the reproducers in `subagent-reports/261123-opus-independent-review-pr232.md`, then an independent security delta review, then corpus rows.

- **W1: N720 item 1 together with N719, as one unit.** The protected-file index has its own matcher (`protected_file_index.py:526` `_glob_parts`, :579 `_segments_match`) with no case folding. N719 rates this Low because it had no reproducer (NIGGLES.md:8421-8423); N720 item 1 is that reproducer (a one-character bracket under `nocaseglob`). Route the index through `secret_file_matching._component_regex`, fix the later case-exact comparisons in the guard, and add `globasciiranges` to the snapshot options (`shell_snapshot.py:42` lists three). `globasciiranges` appears in both entries; do it once. Close N719 into this work and correct its severity.
- **W2: N720 item 2.** `_BRACKET_EXPRESSION_RE` (`secret_file_matching.py:885`) is still used at :973, :1043, :1053, :1060, :1090, :1114 and :1410-1412. Replace those uses with the one translator, so a POSIX class that is not first in its bracket is read correctly on the Write-script and no-index routes.
- **W4: N720 item 4.** The guard already denies a scan that gave up beside a search or glob (`secret_file_guard.py:178-189`), and three docstrings promise "`IncompleteScanError`, which the guard denies" (`secret_file_matching.py:3059`, :4946, :5857). Make the "glob left unjudged" check count an extglob word, so the existing rule fires. This adds no new fail-closed policy.
- **W3a: the one unconditional part of item 3.** `-O` inside a flag cluster (`bash -xO <option>`) is a literal, visible switch in an ordinary spelling, so it is in scope whatever is decided above. The LOW items (traceback on a reversed range, the `awk` case) go with it.
- **Not buildable now: the rest of item 3.** `.` and `source` after `builtin`, `command`, `!`, `time`, `if`, `while`, `elif`, and a quote or escape inside a keyword, all extend code that catches out-of-scope shapes, which `ARCHITECTURE.md:874-876` forbids. They belong to the step-2 build and happen only if the owner chooses B. If the owner declines, they are dismissed under the threat model with corpus rows.
- Item 5 (a pattern held in a variable, ANSI-C quoting of a parenthesis) needs the two-part test of `ARCHITECTURE.md:826-839` applied per shape before any build.

### A drift the owner should rule on

`secret_file_guard.py:25-33` and `ARCHITECTURE.md:854-865` say an unjudged call is "never denied". The same file denies two unjudged cases (`_UNRESOLVED_CAUSE` :172-177, `_GAVE_UP_CAUSE` :180-189), whose comments cite reviews 614b and 614c (:170, :178); Plan 00623 routes both guards through one shared fail-closed handler (`00623/PLAN.md:21`, :37). I found no owner quote authorising that departure from A1 in `00623/PLAN.md`, which is the only place I looked. Either the docstring and ARCHITECTURE are stale or the branches exceed the ruling; the step-2 soft block above would be a consistent third state for both.

### What an independent reviewer must check

- **Monotonicity**: for every command, the verdict with the unstaticable construct and the hatch is never more permissive than the verdict for the same command with the construct removed. Test it on a host with no proving snapshot as well as one with.
- Check order: no input makes the hatch reachable when step 1 has a finding, including a literal path placed after the construct, inside a `-c` body, or in a heredoc.
- The hatch marker itself cannot perturb parsing (for example by being read as the command word or as a glob-bearing word).
- Step 3 really is silent for everyday `source` and `trap` commands in a project that holds a protected link, measured on a corpus of ordinary commands, not asserted.
- The conservative reading is the one selected for every unstaticable construct, and a snapshot proving the options off does not override it.
- The audit record never contains a protected file's name or content, and the human-visible count cannot be reset by the agent.
- W1: the index and the walk agree on every N716 reproducer with the index on and off.

### What I could not verify

- Where the in-command option-switch keyword list lives and what the guard does today for each item-3 shape (silent allow or advisory). I read `shell_snapshot.py:1-45` and the guard's header only; the builder must confirm the two-reading structure in `secret_file_matching.py` before relying on reason 4.
- None of N720's reproducers was re-run, and the PR 232 review report was not read.
- Whether a conservative-reading deny is a hard deny on a host with no usable snapshot today. This is a risk, not only a frequency question: if it is, a careless build of step 2 would let the hatch lift it (see reason 1 and the monotonicity check).
- Whether an owner ruling authorised the two fail-closed branches named in the drift section. The code comments cite reviews 614b and 614c (`secret_file_guard.py:170`, :178); I searched only `00623/PLAN.md`.
- The secret word list and every protected file were not read, as instructed.
