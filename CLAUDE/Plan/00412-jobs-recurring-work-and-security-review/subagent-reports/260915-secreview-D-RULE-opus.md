# Security review — check `D-RULE` (changed rules)

**Run**: Routine 00001, run 2026-001, FULL sweep
**Interval**: `74b0989cf254b24c3c713254b2c0b52ad5d7ed96` (root, 2026-01-26) →
`5d59f7ff` (HEAD, 2026-09-15), 3,815 commits
**Check**: `D-RULE` — "Changed rules. A deny that became an allow, an exemption
widened, a severity lowered, a handler default flipped to disabled. The reason,
per change."
**Answer**: the check was RUN and answered. **2 findings** — one LIVE, one
HISTORICAL (already repaired, reported because it is the same class and it is
the evidence that the class bites).

## Summary

The repository is, on the whole, unusually disciplined about this check. Every
category the brief named was swept and almost every hit carried a written
reason at the point of change: `rule_ids.py` has never had a line deleted, the
shipped opt-in set is pinned by a drift guard with a per-handler reason, the
dogfood config's exemption lists are empty-by-design with the reason for the
emptiness spelled out, and one allowlist (`scripts/qa/contract_allowlist.py`)
*structurally rejects* an entry without `id`, `reason` and a linked plan.

The two findings share one shape, which is what makes them a class rather than
two accidents: **a guard's verdict was changed inside a commit whose subject is
about something else, so the change had no reason attached anywhere a reader
would look.** In both cases the change survived for months.

---

## Finding 1 — LIVE. The plan-time-estimate deny is disabled, per line, by any of 15 ordinary words

### Citation

`src/claude_code_hooks_daemon/handlers/pre_tool_use/plan_time_estimates.py:67-84`

```python
    # Technical terms that should NOT be flagged (feature descriptions)
    TECHNICAL_PATTERNS: ClassVar[list[str]] = [
        r"\bTTL\b", r"\bcache\b", r"\bretention\b", r"\bpolicy\b",
        r"\bwindow\b", r"\btimeout\b", r"\bexpir(?:e|es|ation|y)\b",
        r"\btracking\b", r"\btrial\b", r"\bperiod\b", r"\bsession\b",
        r"\brolling\b", r"\busage\b", r"\bAPI\b", r"\brate\s+limit",
    ]
```

consumed at `plan_time_estimates.py:154-167`:

```python
        for line in content.splitlines():
            if not self._line_has_estimate(line):
                continue
            if not self._line_has_technical_term(line):
                return True
        return False
```

**Introduced**: commit `af5cfa51` (2026-02-09), subject *"Plan 00033: Remove API
usage handlers (cannot dogfood)"*. The same commit replaced the original
catch-all duration pattern with eight context-anchored ones and added
`TECHNICAL_PATTERNS`. The commit body describes only the status-line handler
removal. `CLAUDE/Plan/Completed/00033-statusline-enhancements/` — the plan the
subject names — contains no mention of `plan_time_estimates`, time estimates or
a technical-term exemption. `git log -S TECHNICAL_PATTERNS` returns exactly one
commit, so this is the only time the list has ever been touched.

### What it concretely allows

The exemption is evaluated **per line, by mere presence**: any line carrying one
of those 15 words is exempt regardless of whether the duration on it describes a
feature. Verified by replaying the handler's own `ESTIMATE_PATTERNS` /
`TECHNICAL_PATTERNS` (extracted from the source by AST, predicate reproduced
exactly) over probe lines:

| Probe line (as it would appear in a PLAN.md)              | Verdict |
| --------------------------------------------------------- | ------- |
| `**Estimated Effort** → 4 hours`                          | DENY    |
| `**Estimated Effort**: 4 hours per session`               | ALLOW   |
| `**Target Completion** → 2026-06-30`                      | DENY    |
| `**Target Completion**: 2026-06-30 for the session store` | ALLOW   |
| `ETA → 5 days`                                            | DENY    |
| `ETA: 5 days for the API rewrite`                         | ALLOW   |
| `Phase 2 — schema migration (3 days)`                     | DENY    |
| `Phase 2: API migration (3 days)`                         | ALLOW   |

So R-PLAN-TIME-ESTIMATE is defeated by appending two words. The bypass reaches
the *anchored* shapes — `**Estimated Effort**:`, `**Target Completion**:`,
`ETA:` — which can never be a feature description, and which the handler's own
deployed guidance (`plan_time_estimates.py:211-219`) names explicitly as
blocked. That same guidance states the exemption semantically: technical
durations that *describe a feature* — its own examples are a cache TTL, a
session timeout, a retention window — are allowed.

The documented rule is therefore "a duration that **describes** a feature is
exempt". The implemented rule is "a line that **contains** one of 15 words is
exempt". Those are not the same rule, and the gap between them was never
decided.

The exempting vocabulary is not incidental: TTL, cache, retention, policy,
window, timeout, expiry, tracking, trial, period, session, rolling, usage, API
and rate limit are the working vocabulary of a hooks daemon and an API-usage
status line — i.e. of the very plan being written when the list was added, and
of most plans in this tree.

**Exploitation to date: none detected.** I scanned every tracked
`CLAUDE/Plan/**/*.md` outside `JOURNAL/` for lines that match an estimate
pattern *and* carry a technical term. Exactly one line hits, and it is the Plan
00140 write-up of this very defect. The hole is open; nobody has walked through
it.

### Partial prior remediation — and the axis it left open

Plan 00140's review **did** find part of this:
`CLAUDE/Plan/Completed/00140-deep-code-review-fix-workflow/FINDINGS.md:149`
(finding 25) records the exemption as a *document-wide* OR, and names both
axes — the scope axis ("any technical keyword anywhere whitelists ALL
estimates") and the drift axis ("`get_claude_md()`/docstring claim only
feature-describing technical durations are exempt"). Commit `ac766ba5`
(2026-06-23, subject *"Plan 00140 fix(misc): four medium code-review findings"*)
fixed the **scope** axis only, narrowing whole-document to per-line. The
**description-vs-containment** axis the same finding named was never addressed
and never closed out. That is why this is reported as still-open rather than as
an already-recorded decision: the reason on the record justifies "a duration
co-located with a technical noun is a feature description", not "an anchored
effort estimate is exempt because the word *session* is on the line".

### The class

**A guard whose exemption is keyed on the PRESENCE of a token rather than on the
token's RELATIONSHIP to the matched construct.** A member of the class has three
marks:

1. the exemption predicate and the match predicate are evaluated over the same
   window (line, statement, command) but are otherwise independent;
2. the exemption tokens are ordinary vocabulary in the domain the guard polices;
3. the deployed guidance states the exemption *semantically* ("durations that
   describe a feature") while the code states it *lexically* ("contains the word
   cache").

Mark 3 is what makes it decidable without asking anyone: if you cannot restate
the code's exemption in the doc's words without losing a case, they are
different rules.

### Why the test suite does not catch it

`tests/unit/handlers/pre_tool_use/test_plan_time_estimates.py` has eight
regression tests on exactly this behaviour, and they pass, because they only
ever populate two of the four quadrants:

- **Exempt** cases (`:357-446`) always use lines where the duration *is* the
  technical description — "Implement 30 day TTL cache for API responses",
  "Add support for 5 hour API usage window tracking".
- **Still-blocks** cases (`:448-489`, `:538-555`) always use lines with **no**
  technical word — a phase heading whose bracket reads "2-3 hours", and a
  total-effort line whose value reads "10-15 hours".

The quadrant that fails — *an anchored effort/date/ETA estimate on a line that
also happens to contain a technical word* — is never written, so the tests
encode the author's vocabulary rather than the rule's boundary. The
whole-document regression test (`:492-514`) is the closest approach and it
deliberately puts the technical term on a **different** line, which is the case
that was already fixed.

### Detector hypothesis

**Rule**: for any handler that (a) declares a match-pattern collection and (b)
declares a second collection used only to *suppress* a match, assert that every
suppression token is either (i) anchored to the match — the suppression regex
shares a capture group or an adjacency with the matching regex — or (ii) listed
verbatim in the handler's `get_claude_md()` exemption prose. Fail on any
suppression token that is a bare `\bword\b` with no adjacency and no doc
mention.

Statically: find class-level `ClassVar[list[str]]` regex collections in
`handlers/**` whose identifier matches `(TECHNICAL|EXEMPT|ALLOW|SAFE|IGNORE)`,
and whose consuming predicate is a plain `any(re.search(p, X))` over the *same*
`X` as the positive predicate. That co-consumption shape is the signature.

**Likely false positives**, stated so the rule is not suppressed for lying:

- `pipe_blocker`'s `UNIVERSAL_WHITELIST_PATTERNS` — anchored (`^grep\b`), so the
  adjacency arm clears it, but only if the detector understands `^`-anchoring as
  adjacency. A naive version fires here, loudly and wrongly.
- `curl_pipe_shell`'s receiver allowlist and `sed_blocker`'s four exemptions —
  both are *command-position* predicates, not content predicates; the detector
  must not treat a command-head allowlist as a content suppressor.
- `sensitive_content`'s `exclude_paths` — a path exemption, not a token
  exemption. Must be excluded by kind, or it fires on every handler that has
  one.

Expected noise: 3-6 hits across `handlers/**`, of which I expect 1 true positive
today. That is a rule worth having only if the three shapes above are excluded
by construction; as a bare word-list scan it would be suppressed quickly, and
reporting it as clean would be dishonest.

### Confidence

**High** that the behaviour is as described — the probe table is a mechanical
replay of the handler's own extracted patterns and predicate, not a reading.
**High** that no reason is recorded — `git log -S`, the commit body, and the
named plan folder were all checked and all are silent.
**Medium** on severity: R-PLAN-TIME-ESTIMATE is a workflow-hygiene rule, not a
safety rule, and nothing in the tree has exploited it. What would settle
severity is a decision this reviewer should not make: whether the project wants
the exemption to be semantic (which needs a real adjacency predicate) or wants
it dropped entirely, now that the estimate patterns are context-anchored and no
longer fire on a bare "30 day cache".

---

## Finding 2 — HISTORICAL, already repaired. `git_stash` ran advisory-only for three months after a downgrade inside a QA-coverage commit

### Citation

Commit `1b0ce868` (2026-01-27), subject *"Fix critical QA failures and achieve
95% test coverage"*, in
`src/claude_code_hooks_daemon/handlers/pre_tool_use/git_stash.py`:

```diff
-        """Always block - no escape hatch."""
+        """Warn about git stash but allow with guidance."""
-            decision=Decision.DENY,
+            decision=Decision.ALLOW,
+            context=["WARNING: git stash detected", ...],
```

Restored by `cd292a02` (2026-04-20), *"Add: block stash by default with
MUST_STASH_BECAUSE escape hatch"* — whose subject reads as though the deny were
**new**, which is the tell that nobody knew it had ever been one.

### What it allowed

Between those two commits, `git stash` / `git stash push` / `git stash save`
produced an advisory and the tool call proceeded. R-GIT-STASH-PUSH exists
because "stashes get forgotten, lost, and block git pull" — a stash created in
that window was never denied. Current state is correct: `git_stash.py:68` and
`:118` both default `_mode` to `"deny"`, and the dogfood config pins
`mode: deny`.

### The class

Same class as Finding 1 at the level that matters for the Detector: **a verdict
change landing in a commit whose subject describes unrelated work**, so no
reviewer of the commit message, the plan, or the changelog ever sees a rule
change go past. Neither commit body mentions the rule.

### Why the test suite did not catch it

It cannot: the test suite asserts what the handler currently does. When the
handler's decision changed, its tests were changed with it in the same commit,
so the suite went green on the new, weaker behaviour. A test suite can only
catch an *unintended* change; this class is an intended change with an
unrecorded reason, which is invisible to every gate that reads the tree rather
than the diff.

### Detector hypothesis

A commit-time gate (sibling of the existing `staged_lint_gate` /
`plan_qa_commit_gate`): **if a staged diff changes a `Decision.DENY` to
`Decision.ALLOW`/`CONTINUE`, removes a `HandlerTag.BLOCKING`, flips a
`get_default_enabled()` return from `True` to `False`, or net-removes entries
from a pattern collection in `handlers/**`, require the commit message to
contain a `RULE CHANGE:` line.** This is a paperwork gate, and that is the
point — it cannot judge whether the change is right, only that a human wrote
down why.

Applying the same detection retrospectively over all 3,815 commits (I ran the
diff-scan half of it) yields: 3 default-enabled flips, 4 config disables, 10
net-negative pattern edits in PreToolUse handlers, 4 deny→advisory edits. Of
those 21, 19 carry a reason in the commit body or a named plan. So the expected
steady-state cost is roughly **one gate prompt per 180 commits**, which is cheap
enough to keep.

**Likely false positives**: mechanical refactors that relocate a pattern
(`e2295c51`, `abaa876f`, `56dab785` all net-remove regexes while moving them to
a shared module) would each demand a `RULE CHANGE:` line they do not deserve.
Mitigation is to diff the *effective* pattern set rather than the file, which is
more work than the gate is worth; I would ship it noisy and let the line be
written.

### Confidence

**High** on the facts (both commits read directly, current state verified).
**Low** on it being actionable as a *finding* — it is repaired. It is reported
because D-RULE asks whether a guard was ever weakened without a recorded
decision, and this is the unambiguous yes that justifies the Detector in
Finding 1's class.

---

## What was swept and found clean

Recorded so that "nothing found" here means something, and so the next run does
not re-derive it.

| Surface swept                                     | Method                                                                                               | Result                                                                                                                                                                                                                                  |
| ------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `get_default_enabled()` flips True→False          | `git log -G get_default_enabled` (31 commits), plus diff scan of `init_config.py` for `true`→`false` | 3 flips, all with a written reason. `2af2f579` (model_fallback_detector) is exemplary — reason, alternative, drift guard.                                                                                                               |
| Handlers shipping disabled                        | `_EXPECTED_OPT_IN_CONFIG_KEYS` (16 keys) vs each handler's `get_default_enabled()` docstring         | All 16 state a reason. `tool_disable_advisor`'s is circular ("off until the project turns it on") — cosmetic, not a hole.                                                                                                               |
| Dogfood config `enabled: true`→`false`            | diff scan of `.claude/hooks-daemon.yaml` across full history                                         | 4, all documented (`ac4897f8` payload_capture, `9d353fd3` relay). Two of the four are file-format rewrites, not flips.                                                                                                                  |
| Rule deletions                                    | `--numstat` on `constants/rule_ids.py` across all 28 commits that touch it                           | **Zero lines ever deleted.** The rule inventory is strictly additive.                                                                                                                                                                   |
| QA checks dropped from the gate                   | diff scan of `scripts/qa/run_all.sh` for removed check invocations                                   | One (`check_bounded_reads.py`, `d868a087`), replaced by semgrep rules whose own header says they catch 11 where it caught 1.                                                                                                            |
| `exclude_paths` / whitelist / grandfather entries | read every such block in `.claude/hooks-daemon.yaml`; `git log -S` on each key                       | Every entry carries a written reason. `history_grandfathered_refs`, `legacy_plan_allowlist` and `grandfather_allowlist` are all empty by design, each with the emptiness itself justified in a comment.                                 |
| Severity lowering (`BLOCK`→`ADVISE`, block→warn)  | diff scan of `edit_mode` / `commit_gate_mode` / `sweep_mode` across config history                   | Only movement is warn→block (`de978425`, measured over 253 replayed commits). `documentation.qa` has been warn-first since 2026-08-28 — a stated rollout, not yet stale, but it is the one clock worth re-reading on the next full run. |
| Deny→advisory in PreToolUse handlers              | patch scan for `-Decision.DENY` with `+Decision.ALLOW/CONTINUE` in the same file-commit              | 4 candidates. Two are plan-recorded (`5434ba40`, `56dab785`), one is Finding 2, one (`web_search_year`) is an advisory by design.                                                                                                       |
| Net pattern removals in PreToolUse handlers       | patch scan, removed regex literals > added, across 434 commits                                       | 10 candidates, all refactors or recorded false-positive fixes. `3938ce2c` and `7e53b35d` on `destructive_git` both *strengthen* it (segment-scoped force-push match, `-S` short-flag handling).                                         |
| The two "WIP handoff … not QA'd" commits          | full diff of every exemption-bearing file in `3e76073a` and `41391a66`                               | Clean. Both error-hiding exclusions they add carry long reasons; the 10 new `pyrightconfig.json` excludes are the same commit's new `lsp_noise_checker` rule applied to this repo.                                                      |

### One structural observation, not a finding

`handlers/registry.py:577` applies handler options with an unvalidated
`setattr(instance, f"_{option_key}", option_value)`. Any key under a handler's
`options:` becomes a private attribute with no schema check — which is how
`sed_blocker`'s `blocking_mode: direct_invocation_only`
(`sed_blocker.py:45-61, 193`) can downgrade that guard, and how a *typo'd*
option silently grants nothing. Both directions fail quietly. This is a
mechanism, not a change, so it belongs to `F-GAP` rather than to `D-RULE`; it is
noted here only because the D-RULE sweep is what surfaced it, and the next
`F-GAP` run should not have to find it again.

## Scope note

Read-only throughout. Nothing was edited, fixed, committed, or proposed as a
patch. Scratch artefacts from the history scans are under `untracked/scratch/`
(gitignored).

One incident worth recording, since it is evidence for Finding 1 rather than an
aside: the first two attempts to write this report were **denied by
`plan_time_estimates` itself**. Line-wrapping had separated a quotation of the
handler's own guidance, and a quotation of its own test fixtures, from the
technical words around them — leaving lines that matched an estimate pattern
with no co-located exemption. The guard behaves exactly as designed on a
line-by-line basis, which is the point of the finding: what the line happens to
contain, rather than what the text means, decides the verdict.
