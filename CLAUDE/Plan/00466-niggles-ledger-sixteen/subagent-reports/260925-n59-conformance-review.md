# Conformance review: Plan 00466 N59 -- unproven signal target (Defence Before Fix)

Reviewer: independent conformance reviewer (Opus 5.5), Sonnet 5 session.
Spec: Defence Before Fix Method Specification, version 1.0.1 (vendored,
`defence-before-fix` plugin 0.1.1). Sections 3, 4, 7, 8 applied.

Scope reviewed: commit range `d59056b5f..3ca34976e` on branch
`worktree-n466-n59` (final commit updated per coordinator instruction from
`a36175c8d` to `3ca34976e`, an unrelated test-skip fix that touches only
`tests/daemon/test_paths.py` and does not affect `signal_targets`).

## Reproduction (done first, per clause 7)

All three runs were reproduced from a fresh detached checkout of the named
commit, in a worktree sharing this repository's object store, through the
project's own entry point: `./scripts/qa/llm_qa.py signal_targets`, with
`HOOKS_DAEMON_VENV_PATH` pointed at a pre-built interpreter (the reviewer's
own worktree had no venv; none of the reproduction commands touched the
worktree under review).

| Commit | Role | Result |
| --- | --- | --- |
| `904f1c314` | first red (Python rules) | RED, reproduced. `signal_targets` exits 1, 4 violations, 653 files scanned: `process_verification.py:184,192` (`unproven-process-handle`), `client_validator.py:320,329` (`raw-signal`). Matches the draft report exactly. |
| `548403a0d` | second red (shell rule) | RED, reproduced. `signal_targets` exits 1, 3 violations, 795 files scanned: `cli.py:788` (`raw-signal`), `dummy-client-repo.sh:139`, `venv_bootstrap.sh:378` (`shell-unproven-kill`). Matches the draft report exactly. |
| `a36175c8d` (stated final) | green | GREEN, reproduced. `signal_targets` exits 0, 0 violations, 795 files scanned. |
| `3ca34976e` (corrected final) | green | GREEN, reproduced. Same result: exit 0, 0 violations, 795 files scanned. The intervening commit only edits a test-skip condition in `tests/daemon/test_paths.py`; it does not touch the detector, the shell/Python sites, or the Security doc. |

Both red commits (`904f1c314`, `548403a0d`) are reachable ancestors of the
final commit (checked with `merge-base --is-ancestor`), so the proof
survives as its own commit under clause 3.3 and is not reconstructable only
by hand-reverting lines.

Overall verdict: the remediation substantially conforms, with one
significant clause-4 finding (scope narrowing merged ahead of Owner
sign-off) and one moderate finding (the shell "gating" claim is disclosed
correctly, but its own referral undersells what is already merged). Neither
finding rests only on the report -- both are demonstrated by reading the
merged rule's own code.

## Findings, ranked by severity

### 1. SIGNIFICANT -- `tests/` is already excluded, permanently and by the merged Rule, not merely "referred" (clauses 3.4, 4)

What the report claims. Section "Decisions referred to the owner", item 2,
frames "Leave `tests/` outside the rule" as a pending Owner decision: 6 sites
found, all examined, none hazardous today, and the exclusion is "referred"
because "exceptions are the owner's."

What the code actually does. Both scan surfaces hard-exclude `tests/`
already, unconditionally, in the merged and blocking Rule:

- Python: `_SCAN_TREES` in `scripts/qa/check_signal_targets.py` is
  `(src/claude_code_hooks_daemon, scripts)` plus two one-level dirs
  (`.claude/ccy`, `bin`) -- `tests/` is never a member.
- Shell: `scanned_shell_files()` explicitly filters
  `path.relative_to(_REPO_ROOT).parts[0] != "tests"`.

This is confirmed by the entry-point reproduction above: the green run at
both `a36175c8d` and `3ca34976e` reports 795 files scanned, which is
exactly 653 Python + 142 shell -- the same total the report gives for its
non-`tests/` sweep, and excludes the whole `tests/` tree, not just the 6
sites the report examined.

Why this is a clause 4 problem, not a documentation nit. Section 4 is
explicit: "A decision awaiting the Owner MUST NOT stall the rest of the
work... and leaves the Rule unmerged rather than merged in a weakened
form." The one named exception is narrow: "the Rule MAY merge at full
width with that case recorded as a known Instance awaiting the Owner" --
full width, with the specific case flagged, not narrowed. What happened
here is the opposite shape: the Rule was narrowed (a whole directory
excluded from every future scan) and merged as permanently blocking, and
the narrowing itself -- not a single flagged instance -- is what was
"referred." The report's own reasoning for the exclusion ("the net's own
tests must signal pid 1 and our own group... scanning `tests/` would need
an exception for them") names a handful of specific files
(`test_signal_safety_net.py` and two identity-checked cleanup files) that
need a genuine Exception. That is a sound case for a narrow, sentence-backed
Exception on those specific files. It is not a case for excluding the
entire `tests/` tree from the Rule's enforcement going forward, which is
what the merged code does. Per clause 3.3: "A Narrowing that excludes more
code than the Rule still covers MUST be reported to the Owner as if it
were a Suppression" -- that reporting happened, but the code did not wait
for it, and clause 4 requires waiting (or the narrower
full-width-with-flagged-instance shape) when the Practitioner is not sure
an exclusion is hazard-free going forward. The report itself concedes the
uncertainty: "The exclusion is still not hazard-free as a rule for new test
code" -- which, under the "uncertainty is itself an Escalation trigger"
language in section 4, means the exclusion needed to wait rather than ship
blocking and merged.

What would resolve it. Either (a) keep `tests/` inside the Sweep's scope by
default (the spec's own default for unrecorded scope decisions in 3.4 is
"Sweep all first-party source... and exclude generated code and vendored
dependencies" -- test fixtures are not generated/vendored, so the default
includes them), with a narrow, sentence-backed Exception carved for the
handful of test files that deliberately exercise the hazard on purpose (the
safety net's own tests, and the two identity-checked cleanups), or (b) get
the Owner's actual sign-off on the blanket `tests/` exclusion before merging
it as blocking, rather than merging first and reporting after.

### 2. MODERATE -- the shell rule's "proof" is honestly disclosed, but the referral's framing undersells that the weaker shape is already the permanent, merged behaviour

Per the task's specific instruction, I read `_verified_earlier` and
`_kill_target_is_proven` in `scripts/qa/check_signal_targets.py` directly
(lines ~801-841). The proof is exactly what the report's referral #3 and
`CLAUDE/Security/UnprovenSignalTarget.md` say it is: `_verified_earlier`
requires only that a command whose head is in `SHELL_VERIFIERS` and that
references the same variable appear earlier in the same function
(`command.seq < kill.seq`, same `_scope_of(...)` span). There is no check
that the `kill` sits inside the success branch of an `if`/`&&` on that
verifier's result, or after a `||`-guarded early return. This is sequencing,
not gating, and the report is correct to say so rather than overclaim.

I spot-checked all six shell sites the report claims gate correctly
(`upgrade.sh` `_stop_running_daemons`, `dummy-client-repo.sh` teardown,
`venv_bootstrap.sh` `_vb_watchdog` and `_vb_signal_job`, `venv.sh`
`venv_heartbeat_stop`, `resolve_venv.sh` watchdog) -- every one I read does
in fact gate the kill behind an `if ! <check>; then continue/skip; fi` or
equivalent, so the report's factual claim about today's code holds.

The finding is narrower than a factual error: this is a real, permanent,
merged weakening of the Rule's proof strength (sequence rather than control
flow), and it is disclosed in the Security doc's "What the Defence does not
catch" section -- which is the right channel (clause 3.6/8.5 enumerability)
and is not a worked-around toolchain gap. Framing it as an item under
"Decisions referred to the owner" is slightly misleading only in that,
unlike items 1 and 3 in that same list (which describe a rule that could
additionally widen, with current behaviour unchanged), this one describes an
existing weakness in the Rule's current semantics that is already shipped
and blocking. It is defensible as an owner-authority item because
tightening it "is harder to check without false positives" (clause 4's
named ground for leaving a Rule narrower than a search showed), but the
write-up would be clearer if it distinguished "gaps in what we might add"
from "a known weakness in what already ships," since a reader skimming the
referral list could mistake this for a speculative future improvement rather
than a present limitation of the merged proof.

What would resolve it. No code change is required to conform; a small
wording change in the DBF report (not the Security doc, which already gets
this right) separating "extend the rule" referrals from "tighten a shipped
but weaker-than-ideal check" referrals would remove the ambiguity.

### 3. MINOR -- referral #1 (the `$!`-after-reap wider rule) and referral #3 (gating) are correctly scoped Owner referrals

Checked against section 4's enumerated list. Referral #1 ("leave the named
wider rule unbuilt... resolve_venv.sh was an instance") matches the clause 4
allowance precisely: the one found instance (`resolve_venv.sh`) was fixed
regardless of the referral, and what is left to the Owner is only whether to
build the additional wider Rule -- current scanned code is not narrowed by
leaving it unbuilt. I independently confirmed the five sites named as
"judged safe by construction" are real, `$!`-bound kills accepted by the
rule today (`.claude/skills/hooks-daemon/scripts/install.sh` lines 219-257,
and the `venv.sh` equivalent) -- the report is not inventing the gap. This
referral is a genuine, correctly-routed Owner decision, not a Practitioner
decision dressed up as one.

Referral #3 (the gating referral discussed under finding 2) is likewise
correctly routed under the same clause-4 ground ("harder to build without
false positives"), with the caveat noted above about how it is framed
relative to referral 1.

### 4. Independent search: comprehensive, run before the Rule, and reconciled in the search's favour

The search report (`260925-n59-independent-search.md`) is dated/scoped to
main `9f83b9ff9`, before any of the N59 commits. Its file was only committed
into the branch at the final commit (`a36175c8d`), so commit order alone
cannot prove it was run first -- but its content is independently
corroborated: I checked its `venv_bootstrap.sh` finding (N7 comment, lines
~440-448) against the tree at `9f83b9ff9` and it matches exactly, including
line numbers that only line up with main's pre-fix state, not any later
commit's renumbered file. That is strong circumstantial evidence the search
was genuinely run against the unmodified branch point, consistent with the
report's account of it being dispatched by the lead before the rule
existed. This detail cannot be fully verified independently of the two
agents' own transcripts, which I do not have access to, so I flag it as
corroborated but not fully reproducible -- a reviewer with transcript
access should confirm dispatch ordering directly.

The two techniques (text search for the raw-signal spellings vs. reading
each hit's pid provenance) are genuinely independent under clause 3.1's
test -- a text search cannot see whether a `pgrep` result was re-verified,
and reading cannot enumerate every call site with the certainty a grep-style
pass gives you. The record states what each found that the other could not
have (clause 3.1's closing requirement), and where the two disagreed (four
sites: three shell sites the first Python-only rule missed, plus `cmd_stop`
which the searcher judged SAFE and the lead overruled as an instance), the
search won except where the lead explicitly ruled, which is the correct
resolution order under clause 3.1 ("If an independent search finds
Instances the Rule missed, the Class was drawn too narrowly and the Rule
MUST be widened until it catches them").

### 5. Sweep, fixes, permanence -- conforms, modulo finding 1

- Sweep count and scope. 795 files (653 Python + 142 shell), reproduced
  exactly via the entry point at both green commits. The stated scope
  ("first-party source in both languages the pattern occurs in") is
  correctly the whole project, not just the component that reported the
  defect (`upgrade.sh`, `client_validator.py`, `cli.py`,
  `venv_bootstrap.sh`, `venv.sh`, `resolve_venv.sh`, `dummy-client-repo.sh`
  span several unrelated subsystems, which the Sweep correctly reached).
- Fixes. Each of the 10 non-`tests/` instances is fixed by routing through
  a proven mechanism (`safe_signal.py` helpers in Python, same-function
  identity checks in shell), and the report states each was examined
  individually -- I did not find evidence of a fix applied by unexamined
  pattern. No instance is satisfied by a suppression marker (the detector
  has none), a baseline, or leaving the hazard in place; the green run at
  0 violations across 795 files corroborates this directly.
- Permanence. `signal_targets` is check 33 in `run_all.sh`, gated by
  a genuine failure (not a warning), and is also wired into `llm_qa.py`'s
  `ToolConfig` registry. This was verified by reading the code, not only
  trusting the report.
- Message and identifier (clause 3.6, 8.3). The failure message is terse
  and names `CLAUDE/Security/UnprovenSignalTarget.md` by path, which is a
  file the practitioner (or an Agent) can read directly -- resolving
  without a human, per clause 8.3. The doc states what the Rule is about,
  why it exists, and how to fix a violation correctly (clause 3.6's
  three-part requirement), including a worked table of "what is NOT
  proof," which is unusually concrete and satisfies 8.4's "state the
  correct construction" bar well.
- Toolchain gaps reported, not worked around. The report and the Security
  doc both list real limitations (no single-rule harness, no
  identifier-resolving command, lexer-not-parser limits on shell) rather
  than silently accepting them; this matches section 8.1/8.3's spirit even
  though no bespoke resolver command exists yet.
- Original defect fixed last, with a test.
  `tests/unit/utils/test_safe_signal.py::test_a_magicmock_pid_which_coerces_to_one`
  (and siblings) reproduce the MagicMock/pid-1 shape and pass at the final
  commit; the safety net (`d59056b5f`) landed first, before any instance
  was fixed, and is itself a separate, reachable commit -- consistent with
  clause 3.3's ordering (net/proof before fix) and section 3's closing
  instruction ("Only then fix the original Defect").

## Summary for the coordinator

- Both red runs (904f1c314 Python, 548403a0d shell) reproduce exactly as
  the draft report claims, through the project's own entry point.
- The green run reproduces at both the originally-named final commit
  (`a36175c8d`) and the corrected final commit (`3ca34976e`); the extra
  commit does not touch the defence.
- The one significant conformance problem is clause 4: the merged, blocking
  Rule already hard-excludes the entire `tests/` tree from every future
  scan, while the report frames that exclusion as still pending Owner
  approval. The exclusion should either be narrowed to the specific files
  that need a genuine Exception, or held for actual Owner sign-off before
  merging as blocking.
- The shell "proof" is honestly documented as sequence-only rather than
  control-flow-gated (verified by reading `_verified_earlier` directly, not
  by trusting the report), and every site currently scanned does in fact
  gate correctly today -- the gap is about future code, and it is
  disclosed rather than hidden.
- The other two referrals (the `$!`-after-reap wider rule, and the gating
  tightening) are correctly routed to the Owner under section 4 and do not
  narrow currently-enforced coverage.
- The independent search is genuinely two techniques, run before the Rule,
  corroborated against main's actual pre-fix source, and reconciled in the
  search's favour per clause 3.1.
