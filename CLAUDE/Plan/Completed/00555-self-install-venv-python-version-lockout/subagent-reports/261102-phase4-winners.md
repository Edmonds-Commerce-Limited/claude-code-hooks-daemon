# Plan 00555 Phase 4: recommended winners (sub-agent pick, delegated by the owner)

**This is a sub-agent's recommendation, made under the owner's delegation of
2026-11-02 ("pick clear winners using sub agent, raise with me if its really not
clear").** It is not a stand-in ruling. Every pick below is offered for the owner
to record. Nothing here was judged NOT CLEAR. Two picks rest on one fact each,
and that fact is named so the owner can check it.

Read for this report:

- PLAN.md (Phase 4, Tasks 2.5, 2.6 and 2.8) and DBF-REPORT.md;
- both stand-in rulings, the Task 2.5/2.6 review and its re-review;
- the DBF spec 1.1.0, section 4. The cache had been cleared, so I fetched the spec again with
  `refresh-spec.bash`. It reported `SPEC.md fetched 1.1.0`.

I also checked the code, at main `bb9ee5708`.

## Summary table

| Decision                                          | Winner                                     | Confidence  |
| ------------------------------------------------- | ------------------------------------------ | ----------- |
| 4.1-1 Accept partial defence of the class         | ACCEPT, plus one cheap follow-up           | High        |
| 4.1-2 Build the wider data-flow rule              | DO NOT BUILD now; record a revisit trigger | High        |
| 4.1-3a Calibration: `tests/` excluded             | CONFIRM                                    | High        |
| 4.1-3b Calibration: workflow YAML uncovered       | CONFIRM                                    | High        |
| 4.1-3c Calibration: "cannot tell" passes          | CONFIRM                                    | Medium-high |
| 4.2a Stand-in ruling 1 (2.5 option b; 2.6 a, N=3) | CONFIRM, plus one gap to close             | High        |
| 4.2b Stand-in ruling 2 (S1, S2, S4, S5, all a)    | CONFIRM all four                           | High        |
| 4.2c Client may read daemon logs while down       | NO: keep `.claude/hooks-daemon/` denied    | High        |

---

## Task 4.1, decision 1: accept that the class is only partly defended

**Winner: ACCEPT.** Confidence: high.

**What is being accepted.** Thirteen "yes" items from the independent search have no lexical
signature (DBF-REPORT.md:286-294). They fall under:

- (c) cache invalidation by mtime only;
- (d) freshness judged by lock_hash or stamp;
- (e) self-heal and repair gated on "nothing resolves";
- (f) success meaning "it resolved";
- delegation.

All 13 were fixed by hand, with tests (DBF-REPORT.md:390-403). What remains for the owner is
whether a later regression in these causes can be caught by tests alone.

**Evidence:**

- SPEC section 4 says that when a rule is narrower than the search, "The Instances the search
  found are fixed regardless; what stays with the Owner is the Class left partly undefended"
  (SPEC.md:788-791). The precondition is met: there are 0 open instances.
- The only alternative to accepting is to defend (c) to (f) mechanically. Each of these causes is
  a missing term or the meaning of a branch condition, not a spelling (DBF-REPORT.md:291-292).
  Decision 2 shows that even a data-flow rule would not reach them.
- **The point against accepting.** One instance already escaped after the merge:
  `_venv_is_fresh`, cause (d) (DBF-REPORT.md:408-428). It is now fixed and gated
  (`scripts/install/venv.sh:1206-1214`). That shows the risk is real. It does not show that a
  rule could have caught it, because it has no lexical signature.

**Follow-up implied (cheap, recommended, not blocking).** Add a pinned list of the known
reuse, freshness and self-heal predicates to the existing detector. Each listed function would be
required to call a member of `GATES`, checked with the existing `proven_gates` body-proof
machinery. Candidates:

- `_venv_is_fresh`, `_cli_check_venv_fresh`, `_rv_cached_venv_current`;
- `_write_venv_metadata`, `_is_daemon_installed`.

This does not widen the class. It turns the hand-fixes for (d) and (e) into a defence that fails
if someone removes the gate call. That is exactly the regression `_venv_is_fresh` showed. It
does not cover new predicates, so the class stays partly defended, and the owner should record it
that way.

## Task 4.1, decision 2: build the wider data-flow rule?

The rule in question is "any execution of a venv interpreter not obtained from the SSoT
resolver".

**Winner: DO NOT BUILD now. Record it as a known gap with an explicit revisit trigger.**
Confidence: high.

**Evidence:**

- **It would not have caught the one real escape.** `_venv_is_fresh` executes no interpreter. It
  judged freshness from metadata (`venv.sh:1196-1236`). The escapes that actually happened sit in
  (c) to (f), and decision 2's rule cannot see them either.
- **The tool cannot cover where most instances live.** The rule doc's instance table has 17
  instance rows. 14 of them name shell sites (`.sh`/`.bash`/`bin/hooks-daemon`) and 5 name
  Python (`CLAUDE/Security/UntrustedVenvInterpreter.md`; some rows name both). The only
  data-flow candidate is CodeQL, which covers Python only and is rated amber. No listed tool
  traces values across sourced Bash (DBF-REPORT.md:300-303).
- **The cost is a new CI toolchain plus false positives** from a name-based approximation
  (DBF-REPORT.md:102-106). The benefit is small, because the gates and the resolver already sit
  on every known execution site.
- **The SSoT work that would make a cheap rule possible is still pending.** Plan 00100 (venv SSoT
  consolidation) is Dormant. Once it lands, every execution site reads one resolver output. "Run
  only what the resolver returned" then becomes a lexical rule that needs no data flow.

**Owner authority.** SPEC 4 reserves this decision because the rule was rejected for its cost and
false positives, not because no instance exists (SPEC.md:782-791). The owner's delegation covers
it, but the decision should be recorded in the owner's name, not the practitioner's.

**Revisit trigger to record.** Rebuild the case for this rule when either of these happens:

- an instance escapes that runs a hand-built `venv*/bin/python` without a gate; or
- Plan 00100 lands, which makes the lexical "only resolver output" rule possible.

## Task 4.1, decision 3: confirm the calibrations

### 3a. `tests/` excluded from the sweep: CONFIRM (high)

- The drift tests build drifted and stub venvs on purpose. Those fixtures are the hazard by
  design, so including `tests/` would report every reproduction test.
- The fixtures that relied on the hazard by accident were caught anyway, by the full gate, once
  the production gate became strict (DBF-REPORT.md:257-263). Nothing in `tests/` ships.

### 3b. Workflow YAML uncovered: CONFIRM (high)

The class needs a venv that outlives a change of interpreter. CI cannot produce one:

- Every job builds its venv fresh, in the same step and with the same interpreter, through the SSoT
  resolver, and asserts the resolver's answer. Examples: `qa.yml:123-135`, `:330-334`,
  `:600-603`, and `release-gate.yml:156-159` and later.
- Workflows cache only pip (`cache: pip`) and never a venv. A search for `actions/cache` finds no
  match.

### 3c. "Cannot tell" passes: CONFIRM (medium-high)

The gates in question:

- **Python:** `paths.py:982-1009`. A missing `pyvenv.cfg`, no recorded version, or a probe that
  printed no version is judged usable.
- **Bash:** `resolve_venv.sh:351-362`.

Both still fail an interpreter that is missing or does not run.

**Why confirm:**

- Every venv tool writes `pyvenv.cfg`, including uv, `python -m venv` and virtualenv. So "cannot
  tell" only arises for a non-venv prefix pointed at through the override, or for a corrupted
  venv.
- Failing closed there would break a legitimate non-venv prefix and gain little.
- **Backstop:** a venv that resolves but cannot import the package is caught by the wrapper's
  bounded import probe and rebuilt (PLAN.md Task 2.3).

**Why not "high".** Without `pyvenv.cfg`, a venv's interpreter does not run as a venv at all, so
its site-packages are invisible, which is the same consequence as drift. The import probe is the
only thing that catches it. If the owner wants this tightened, make a missing `pyvenv.cfg` (but
not a missing version line) fail in both gates. That is a small change. It needs a check that no
supported install path uses a cfg-less prefix.

## Task 4.2a: stand-in ruling 1 (Task 2.5 option b; Task 2.6 option a, N=3)

**Winner: CONFIRM both.** Confidence: high.

**Task 2.5(b).** The `diagnose` verb is the only item that answers the incident's question:
"can this interpreter see the venv's site-packages?"

- Its risk is lower than the rest of the set. It is one entry in the exact-match recovery list,
  `init.sh:174`.
- The security cost of the wider read-only set was paid in review. C1 and I1 to I4 were fixed,
  and N1, N2, S1, S2, S4 and S5 were closed in Task 2.8. The re-review verdict was SHIP, and its
  parity table found 0 globs where the daemon-down judge was looser than the daemon.

**Task 2.6(a), N=3.** Unbounded blocking is what the incident cost. The bound has three
properties:

- It applies only to stops, and PreToolUse still denies every write and exec, so an allowed stop
  bypasses no guard on the tree.
- N=3 is the smallest value that still forces a restart-then-repair attempt.
- It is a constant (`init.sh:210`), so it cannot be configured down to 1.
- 45 stop-bound tests and 52 read-only tests exist.

**Follow-up implied: one gap in what the ruling specified.** Ruling 1 (lines 220-222) required the
unguarded-stop log `untracked/.daemon-down-stops.log` so that "the daemon's next SessionStart /
`status` can surface that unguarded stops happened". The log is written (`init.sh:794`), but
nothing reads it. A search for `daemon-down-stops` across `src/`, `bin/`, `scripts/` and `init.sh`
finds only init.sh's own writer and counter code. Add a reader:

- `status`, and a SessionStart advisory, report the unguarded stops since the last start;
- then clear or rotate the log.

Without the reader, an unguarded stop leaves a trace that nobody is ever shown.

## Task 4.2b: stand-in ruling 2 (Task 2.8 S1, S2, S4, S5, all option a)

**Winner: CONFIRM all four.** Confidence: high. Each makes the bound or the set stricter or more
correct, and none costs recovery liveness.

- **S1, union on stale snapshot.** The result is stricter than either state alone (`init.sh:468-470`
  and `:495-498`). The lockdown keeps `.claude/hooks-daemon.yaml` and `settings*.json` readable,
  which is what an agent needs to see a config edit that broke the restart. Without S1, a glob
  added by that same edit would go unenforced for the whole outage.
- **S2, per-agent SubagentStop key.** Without it, three sub-agents each stopping once would release
  the third without a recovery attempt. A parent's `[awaiting-human]` would also release every
  sub-agent. Each agent still gets exactly N=3, so liveness is unchanged.
- **S4, drop `git status`.** It can rewrite `.git/index` and run a configured `core.fsmonitor`.
  Ruling 1 said that a shape which can write or exec is removed, not patched. The incident did not
  need it, and `git log`, `ls` and a Read of `.git/HEAD` cover the gap. Keeping it would mean the
  owner accepting an exec residual for no diagnostic gain.
- **S5, count reached-but-broken classes.** A daemon that accepts and then crashes is the
  incident's endless loop in another shape. PreToolUse still denies everything else, so counting
  these classes costs nothing.

No follow-up beyond what the build reports already record.

## Task 4.2c: may a client install read the daemon's own logs while the daemon is down?

**Winner: NO. Keep the whole `.claude/hooks-daemon/` tree, other than `bin/`, denied in a client
install (`init.sh:482-485`).** Confidence: high.

The question assumed two logs. The code shows something different.

**1. There is no on-disk daemon log.**

- The daemonised process points stdout and stderr at `/dev/null` (`daemon/cli.py:939-948`).
- Logging is in memory only: `cmd_start` prints "Logs: in-memory (query with 'logs' command)" at
  `cli.py:903`, and the comment at `:943` names `MemoryLogHandler`.
- `paths.get_log_path` (`paths.py:2030`, "untracked/daemon.log") has no caller. A search across
  `src/` finds only its definition, and no shell script names a daemon `.log`.
- No `daemon*.log` exists in this self-install's `untracked/`, and `untracked/logs/` holds only
  `hooks/`.
- The `untracked/logs/daemon.log` path in review I4 and the re-review is therefore a file that is
  never written. Allowing it would allow nothing.

**2. The build log is already readable whenever it matters.**

- The venv build log is `<daemon>/untracked/.venv-bootstrap-<fingerprint>.log`
  (`venv.sh:521-524`, `venv_lock.py:189-191`).
- A failed, missing or running build puts init.sh in the VENV_MISSING state. That state is outside
  the daemon-down deny entirely: PreToolUse is fail-open there (`init.sh:1339-1345`; comment at
  `:1332-1333`, "every named state below stays unconditionally fail-open"). So a client session
  can already read the build log in the "THE LAST AUTOMATIC BUILD ... FAILED. Its log says why"
  case (`init.sh:1479-1485`).
- The read-only set applies only to the STANDARD branch: a venv that resolves and a daemon that
  will not start. In that branch the build log describes a build that succeeded, and `diagnose`,
  which is allowed, is the right tool.

**3. What these files can contain:**

- **Build log.** The full stdout and stderr of the build (`venv_bootstrap.sh:445,462,775-788`): uv
  and hatchling output, absolute paths, interpreter and fingerprint, result lines. It records no
  hook payloads and no protected file content. The one plausible secret is a private index URL
  with embedded credentials in a uv error. uv normally redacts URL credentials, but nothing in
  this project guarantees that. The risk is low but not zero.

- **The rest of the client's `.claude/hooks-daemon/untracked/`.** It holds the known-sensitive
  artefacts named in `utils/private_io.py:3-5`:

  - `payload-capture/`, which holds raw Write/Edit bodies (`payload_capture.py:39`);
  - `logs/hooks/verdicts.jsonl` (`controller.py:1301`);
  - the event spools, sockets, the protected-paths snapshot and the venvs.

  The stop-event log `stop-events.jsonl` also lives there (`auto_continue_stop.py:1289,1324`).
  Its writer anchors it on a computed untracked dir; in this self-install it is `untracked/`.
  A blanket deny is the simplest correct rule.

**4. Widening costs more than it buys.**

- A named allow-list (`.venv-bootstrap*.log` and `.venv-bootstrap.result`) means more judge code
  in a function that the review cycle has already had to fix several times.
- Its only benefit is reading an old successful build log in the STANDARD branch.

**Follow-up implied: optional, cheap, and better than widening the read set.** If the owner wants
build output visible in the STANDARD branch, have the venv-free `diagnose` arm print the last ~40
lines of the recorded build log. It already prints the result and the log path
(`bin/hooks-daemon:402-416`). The daemon then decides what to show, and the read allow-list stays
unchanged.

**Correct the wording in PLAN.md.** Task 2.8's owner question refers to "the daemon log and the
venv build log under `.claude/hooks-daemon/`". There is no daemon log on disk, so the question
should be closed with that fact recorded.

**Side observation, not asked, recorded for the niggles ledger.** The legacy
`core/front_controller.py` `log_error_to_file` writes `untracked/hook-errors.log`
(`front_controller.py:253-297`). Its contents are the hook input, redacted against the secret word
list only, plus a traceback. That is payload-grade content.

- The self-install half of the I4 fix does not deny `untracked/hook-errors.log`
  (`init.sh:486-494`). Only `events*`, `payload-capture`, `stop-events*` and `logs/hooks` are
  denied.
- `FrontController` is exported from the package, but `src/` never instantiates it, and no
  `hook-errors.log` exists in this checkout. The exposure is latent.
- Fix: add `hook-errors.log*` to the self-install deny rule, or retire the writer.
