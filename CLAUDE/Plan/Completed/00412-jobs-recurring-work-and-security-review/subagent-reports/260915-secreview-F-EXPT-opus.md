# Security review — `F-EXPT` (full sweep, Routine 00001 run 2026-001)

**Check**: the UNION of every exemption — `exclude_paths`, whitelists,
`extra_whitelist`, per-handler opt-outs. Is any guard now hollow?

**Answer**: the check was RUN, not merely attempted. Every source named in the
brief was enumerated and, where a fraction was claimable, measured by executing
the guard's own code against this checkout. **Three findings.**

The headline is not the one the check's framing predicts. This repository's own
`.claude/hooks-daemon.yaml` is unusually disciplined about accumulated
exemptions — `daemon.exclude_paths` is absent entirely, `grandfather_allowlist`
and `legacy_plan_allowlist` are `[]`, `allowed_external_paths` is `[]` with a
comment saying so deliberately, `history_grandfathered_refs` is `[]` after
self-reported staleness emptied it, and all 16 handlers whose
`get_default_enabled()` returns `False` are explicitly `enabled: true` here. The
hollowing is not in the YAML. It is in **built-in exemptions that no
configuration key can reach**, and in **one whitelist entry whose semantics
admit everything**.

---

## The union, enumerated

| Source                                                            | Entries                          | Where                                     | Reasoned?                                               | Self-auditing?                                                      |
| ----------------------------------------------------------------- | -------------------------------- | ----------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------- |
| `daemon.exclude_paths` (project-wide)                             | **0** — key absent               | —                                         | n/a                                                     | n/a                                                                 |
| `sensitive_content.exclude_paths`                                 | 5 files                          | `hooks-daemon.yaml:256-276`               | yes, each                                               | no                                                                  |
| `sensitive_content.history_baseline`                              | **1596 of 3817 commits (41.8%)** | `hooks-daemon.yaml:242`                   | yes                                                     | yes — an unresolvable baseline exempts nothing                      |
| `sensitive_content.history_grandfathered_refs`                    | 0                                | `:255`                                    | —                                                       | yes — reports `stale-grandfather`                                   |
| `secret_file_guard.exclude_paths`                                 | 7 files                          | `:290-297`                                | yes                                                     | no                                                                  |
| `project_containment.allowed_external_paths`                      | 0                                | `:339`                                    | deliberate                                              | n/a                                                                 |
| `plan_qa.grandfather_allowlist` / `legacy_plan_allowlist`         | 0 / 0                            | `:1170`, `:1231`                          | —                                                       | n/a                                                                 |
| `plan_qa.collision_allowlist`                                     | 3 (`34, 39, 41`)                 | `:1173`                                   | yes                                                     | no                                                                  |
| `documentation.qa.scope_exclude_globs`                            | 6 globs                          | `:1247-1259`                              | yes, each                                               | no                                                                  |
| `pipe_blocker.extra_whitelist`                                    | **0 configured**                 | —                                         | n/a                                                     | n/a                                                                 |
| `pipe_blocker` UNIVERSAL whitelist (built-in)                     | **34 patterns**                  | `strategies/pipe_blocker/common.py:22-91` | mostly                                                  | **no** → Finding 1                                                  |
| `tdd_enforcement.test_path_map` / `exclude_paths`                 | 0 / 0                            | —                                         | n/a                                                     | n/a                                                                 |
| `security_antipattern` `SKIP_PATTERNS` (built-in, un-overridable) | **10 substrings**                | `strategies/security/common.py:4-14`      | no comment per entry                                    | **no** → Finding 2                                                  |
| `error_hiding_exclusions.json`                                    | **196 entries**                  | `scripts/qa/`                             | yes, each                                               | partial → Finding 3                                                 |
| `contracts/.../ALLOWLIST.yaml`                                    | 30                               | —                                         | yes, each                                               | yes                                                                 |
| `contracts/.../INPUT-ALLOWLIST.yaml`                              | 3                                | —                                         | yes, each                                               | yes                                                                 |
| semgrep `paths.exclude`                                           | 3 globs total across 3 rules     | `scripts/qa/semgrep/`                     | yes                                                     | no                                                                  |
| in-code `# eacces-safe-exempt:`                                   | 30 production sites              | —                                         | **30/30 carry a reason**                                | yes — empty marker rejected (`check_eacces_safe_predicates.py:153`) |
| in-code `# canonical-resolver-exempt:`                            | 8                                | —                                         | yes                                                     | —                                                                   |
| in-code `# python-var-guidance-exempt:`                           | 6                                | —                                         | yes                                                     | —                                                                   |
| in-code `# hostname-suffix-exempt:`                               | 3                                | —                                         | yes                                                     | —                                                                   |
| handlers with `get_default_enabled() == False`                    | 16                               | —                                         | **0 disabled here** (all 16 explicitly `enabled: true`) | n/a                                                                 |

Three QA gates report **100% of their current findings as allowlisted**:
error-hiding (225/225), hook-contract (30/30), input-contract (3/3). Two of the
three self-audit for stale entries; that is what keeps them from being Finding-
grade on their own. The third is Finding 3.

---

## Finding 1 — `pipe_blocker`'s whitelist contains a command RUNNER, so the whole guard is a 4-character prefix away from off

### Citation

`src/claude_code_hooks_daemon/strategies/pipe_blocker/common.py:56`

```python
    r"^env\b",
```

Consumed at `src/claude_code_hooks_daemon/handlers/pre_tool_use/pipe_blocker.py:467`:

```python
            producer = self._extract_producer(command, match.start())
            if self._matches_whitelist(producer):
                continue
```

The whitelist is checked **first and wins** — a whitelisted producer `continue`s
past the blacklist and past the unknown-command DENY tier entirely.

### What it concretely allows

Driving the real handler (`PipeBlockerHandler.matches`) over constructed
commands, `[P]` standing for the pipe character:

```
BLOCK | pytest tests/                    [P] head -5
ALLOW | env pytest tests/                [P] head -5
ALLOW | env FOO=1 pytest tests/          [P] head -5
ALLOW | env npm run build                [P] head -5
BLOCK | timeout 30 pytest                [P] head -5
BLOCK | nice pytest                      [P] head -5
BLOCK | xargs pytest                     [P] head -5
```

`env` is a command runner: `env [NAME=VALUE]... COMMAND [ARG]...`. Prefixing any
command with `env ` moves the producer's first word from the blocked/unknown
command to `env`, which `^env\b` whitelists. The guard exists to stop an
expensive command's output being silently truncated; `env` makes that guard
optional for every command in existence, at the cost of four characters, with no
config change and no visible block.

Two weaker entries from the same list share the root cause — a whitelist
justified by a rationale that does not hold for every member:

- `^sort\b` (`common.py:29`). The module docstring and the `pgrep` comment both
  justify entries on the grounds that the producer "writes continuously (so a
  closed pipe raises SIGPIPE and it stops)". `sort` is a **full-buffering**
  command: it must consume its entire input before emitting a byte, so the
  SIGPIPE argument is simply false for it.
- `^find\b` (`common.py:58`). An unbounded filesystem walk. `root_recursion_guard`
  covers only `/`, `/proc`, `/sys`, `~`, `$HOME` — `find . -name x` over a large
  tree is neither cheap nor loss-free when truncated.

### The class

**A whitelist entry whose command accepts another COMMAND as an operand, in a
guard whose whitelist is evaluated before its deny tiers.** The test for
membership does not require judgement: does the named binary's man page take
`COMMAND [ARG]...`? If yes, the entry does not exempt that binary — it exempts
the whole command space.

This repository already owns the authoritative answer to that question and does
not consult it here. `src/claude_code_hooks_daemon/utils/process_probe.py:506`
defines `_WRAPPERS`, docstring *"A command that RUNS another command, and what
to skip to reach it"*, listing `watch`, `timeout`, `nohup`, `sudo`, **`env`**,
`nice`, `stdbuf`, `command`. One handler classifies `env` as a wrapper to be
peeled off; another classifies it as a cheap filter to be trusted.

### Why the test suite does not catch it

`grep -rn "env" tests/unit/handlers/pre_tool_use/test_pipe_blocker*.py` returns
**two hits, both incidental** (venv paths inside unrelated fixtures). There is
no `env` producer test at all.

More structurally: whitelist tests are written *per entry* and assert ALLOW. A
test for `^env\b` would take the form "`env | head -5` is allowed" and would
pass. The defect is that the entry allows **more** than its test asserts, and a
whitelist test can never fail for over-allowing — an assertion that something is
permitted cannot detect that too much is permitted. The suite would need a test
of the whitelist's *shape* (no entry names a command runner), and no such test
exists for any handler.

### Detector hypothesis

`scripts/qa/check_whitelist_command_runners.py`: parse
`UNIVERSAL_WHITELIST_PATTERNS`, extract each pattern's literal command head
(the token between `^` and `\b`), and fail on any head present in
`process_probe._WRAPPERS`. Both inputs are literal in-repo lists, so this is a
set intersection — **zero false positives by construction**, and it fails today
on exactly one entry (`env`).

Likely false positives if generalised beyond the `_WRAPPERS` cross-reference
(e.g. to "any binary accepting a COMMAND operand"): `xargs` and `find -exec`
would be flagged, but neither is currently whitelisted, so the noise is
hypothetical rather than present. A second, noisier rule — "every whitelist
entry must cite a rationale comment" — would fire on ~20 of the 34 entries and
should be reported as noisy if attempted.

The `sort`/`find` half of this class is **not** mechanically detectable and
should be handled as a one-off review of the list against its own stated
rationale, not as a Detector.

### Confidence

**High** for `env` — demonstrated by executing the shipped handler, and
corroborated by the repository's own contradictory classification of the same
binary. **Medium** for `sort`/`find`: the rationale mismatch is certain, the
practical exposure depends on how often those producers are genuinely expensive
here.

What would settle the remainder: a `block-report` scan for commands that reached
ALLOW through a whitelist entry other than `grep`/`rg`/`cat`.

---

## Finding 2 — `security_antipattern`'s built-in skip list is substring-matched, unconditional, and unreachable from configuration

### Citation

`src/claude_code_hooks_daemon/strategies/security/common.py:3-23`

```python
# Directories to skip (vendor code, test fixtures, documentation, rule definitions)
SKIP_PATTERNS: tuple[str, ...] = (
    "/vendor/", "/node_modules/", "/tests/fixtures/", "/tests/assets/",
    ".env.example", "/docs/", "/CLAUDE/", "/eslint-rules/",
    "/tests/PHPStan/", "/strategies/security/",
)

def should_skip(file_path: str) -> bool:
    """Check if file should be excluded from security scanning."""
    return any(skip in file_path for skip in SKIP_PATTERNS)
```

Applied at `handlers/pre_tool_use/security_antipattern.py:323`:

```python
        if should_skip(file_path) or self._is_excluded(file_path):
```

`should_skip` runs **before** the configurable branch, and `exclude_paths` is
purely additive (`utils/path_exclusion.py:315`, `merge_exclude_patterns`). No
project-wide key, no per-handler key and no `{vendor-dirs}` token can narrow,
anchor or disable this list. It is the only exemption surface in the audited set
with no configuration path at all.

### What it concretely allows

`skip in file_path` is plain substring containment, not a path-segment match, so
each entry matches at **any depth and any position**. Executing the shipped
predicate:

```
True  /workspace/CLAUDE/Plan/mkplan.bash
True  /proj/src/app/docs/runner.py
True  /proj/app/strategies/security/scan.py
True  /proj/.env.example.prod
True  /proj/src/handlers/CLAUDE/x.py
False /workspace/bin/hooks-daemon
```

Measured over this checkout's tracked code files (15 source extensions):
**106 of 1875 files (5.7%) are permanently unscannable** —
`/CLAUDE/` 44, `/strategies/security/` 32, `/tests/fixtures/` 30.

The 5.7% understates it, because of *which* files they are. `CLAUDE/Plan/mkplan.bash`
is the plan scaffolder that `plan_number_helper` instructs **every agent in every
session** to execute, and the daemon deploys it. A `Write`/`Edit` introducing
`eval "$(...)"`, `os.system`, a hardcoded credential block or any other
`security_antipattern` category into that script is not merely unblocked — it is
unblockable, because the path contains `/CLAUDE/`. The same holds for the 20
other executable files under `CLAUDE/Plan/` and the 7 acceptance-test shell
scripts under `CLAUDE/AcceptanceTests/`.

The client-facing exposure is larger than this repo's own. `/docs/`, `/CLAUDE/`
and `/strategies/security/` are shipped substrings, not this project's
convention declared locally: any client whose tree contains `app/docs/`,
`src/.../CLAUDE/` or `lib/strategies/security/` gets a silent, permanent
security-scanning hole it never opted into and cannot close. `.env.example` is
worse than the rest because it is not even directory-shaped — it matches
`.env.example.prod`, `.env.example.real`, and any path with that substring
anywhere.

### The class

**A built-in exemption applied before the configurable one, matched by substring
rather than by path segment, with no key that can narrow or disable it.** Three
independent properties, each sufficient on its own:

1. *Precedence* — evaluated before the configurable branch, so config cannot
   reach it.
2. *Dialect* — `in` rather than segment-aware matching, so the entry's blast
   radius is unbounded in depth and position. (Contrast
   `utils/vendor_paths.py:79`, `_is_under`, which is explicitly segment-aware
   *"so `ours-vendored` is not treated as living under `ours`"* — the repo knows
   this distinction and applies it in the vendor path but not here.)
3. *Provenance* — entries encoding this project's own layout (`/CLAUDE/`,
   `/strategies/security/`) shipped as defaults to every client.

Deciding a new case needs no judgement: does the exemption have a config key
that can remove it, and does it match on segments?

### Why the test suite does not catch it

`should_skip` has tests, and they pass, because they assert the **positive**
direction: a path under `/vendor/` is skipped, a path under `/src/` is not.
Nothing asserts that the list is minimal, that its entries are segment-anchored,
or that a path *not intended* to be skipped isn't. A test would have to be
written against a path nobody thought of — `/proj/app/docs/runner.py` — which is
precisely the case the exemption's author did not have in mind.

The handler's own tests write to synthetic `tmp` paths that contain none of the
ten substrings, so they exercise the non-skipped branch exclusively and can
never observe over-skipping.

### Detector hypothesis

`scripts/qa/check_exemption_dialect.py`, two rules:

- **R1 (precise)**: any exemption constant consumed by `x in path` where the
  entry is directory-shaped (starts and ends with `/`) is a finding; it must
  route through `utils.path_exclusion.is_path_excluded` or a segment-aware
  predicate. False positives: low — the repo already has the canonical matcher,
  so a legitimate remaining `in` is rare. Expect it to fire on this file and to
  need a short allowlist for genuine substring intents (`.env.example`), which
  would itself be an honest record.
- **R2 (noisier, report AS noisy)**: any hard-coded exemption list consumed by a
  handler with no corresponding `exclude_paths`-style key. False positives are
  likely wherever a built-in default is *meant* to be non-negotiable — the
  `secret_file_guard` protected-path set is correctly un-exemptable, and R2
  would flag it. R2 is worth having only if its output is reviewed by a human
  rather than gating a build.

Neither rule detects the *provenance* property (project-specific names shipped
as defaults); that needs review, not a regex.

### Confidence

**High** on the mechanism and the measurement — both were executed against the
shipped code, and every path verdict above is the real predicate's output.
**Medium** on severity: within this repository the 5.7% is bounded and the
highest-value member (`mkplan.bash`) is short, reviewed and tracked. The
client-facing half is unquantifiable from here and would be settled by
Routine 00001's `F-DEPL` check against a real client install.

---

## Finding 3 — the error-hiding Detector exempts 100% of what it can currently see, and 24 of its licences are open-ended

### Citation

`scripts/qa/error_hiding_exclusions.json` (196 entries) and
`scripts/qa/audit_error_hiding.py:576-595`:

```python
    if "function" in exclusion:
        return bool(violation.get("function") == exclusion["function"])
```

keyed on `(file-suffix, rule, function)` — with no line number and no count.

### What it concretely allows

Running the audit's own collectors, then its own exclusion application:

```
RAW findings:        225
exclusion entries:   196
after exclusions:      0
suppressed:          225  (100.0%)
```

The gate is green, and it is green because **every single finding it is capable
of producing carries a licence**. Its entire remaining signal is "no *new*
error-hiding", which is a ratchet, not a guard — and the ratchet has two leaks:

**Leak A — a function-keyed entry is an unbounded licence.** Because matching
ignores line and count, one entry suppresses every finding of that rule in that
function, present and future. Measured: **24 entries each suppress more than one
finding, covering 53 findings between them** — so 29 findings today are
suppressed by a licence written for a different site. Worst offenders:

```
4 findings  daemon/playbook_generator.py :: _collect_tests          log-and-continue
3 findings  scripts/qa/measure_instruction_footprint.py :: _load_all_handler_instances
3 findings  handlers/status_line/daemon_stats.py :: handle          log-and-continue
2 findings  utils/goal_ledger.py :: _locked                         log-and-continue
2 findings  handlers/registry.py :: register_all                    log-and-continue
```

Adding a third `except Exception: log; continue` to `_collect_tests` tomorrow is
pre-authorised by an entry whose written reason describes a different statement.

**Leak B — `file` is matched by `endswith`.** `audit_error_hiding.py:585`:

```python
    if not violation["file"].endswith(file_suffix):
        return False
```

Four entries use bare or near-bare basenames, which match more files than the
author can have meant:

| entry `file`   | files in this repo ending with it                                                                                                       |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `init.sh`      | `./init.sh`, `./.claude/init.sh`                                                                                                        |
| `/install.sh`  | `./install.sh`, `.claude/skills/hooks-daemon/scripts/install.sh`, `src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/install.sh` |
| `install.py`   | `./install.py` (1 today)                                                                                                                |
| `qa/runner.py` | `src/.../qa/runner.py` (1 today; `plan_qa/runner.py` and `docs_qa/runner.py` are near-misses)                                           |

The `init.sh` entry licenses `emit_hook_error` in **both** files. Neither leak
is visible in any diff, which is the `F-EXPT` shape exactly.

**What already mitigates this, and where the mitigation stops.**
`find_stale_exclusions` (`:598`) reports an entry matching **zero** findings —
genuinely good, and it is why entries here have a decay path at all. But it uses
the *same* `_exclusion_matches` predicate, so an entry that matched 1 finding
when written and matches 3 now is not stale and is not reported. The
self-audit detects *withdrawal* debt; it cannot detect *widening*.

The same 100%-allowlisted shape holds at `check_hook_contract.py` (30 of 30) and
`check_input_contract.py` (3 of 3). Both are reported here as part of the union
rather than as findings, because both allowlists are individually reasoned,
carry `link:` provenance, and fail on a stale entry — and their finding
populations are small, closed and externally driven (the vendored Claude Code
contract), where error-hiding's is open and grows with the codebase.

### The class

**A suppression entry whose match key is coarser than the finding it was written
for**, so the licence silently extends to sites the author never evaluated. The
membership test: can a code change add a NEW finding that an EXISTING entry
suppresses, without editing the suppression file? If yes, the entry is
open-ended. Applies to `function`-keyed entries (new statement in the same
function), to `endswith` file keys (new file with the same tail), and would
apply to any future rule-only or directory-level key.

### Why the test suite does not catch it

`tests/` exercises `apply_exclusions` and `find_stale_exclusions` with small
synthetic fixtures where each entry matches exactly one violation — the
one-to-one case, which is the case that works. No test constructs two violations
in one function and asserts that one entry suppresses only the licensed one,
because that behaviour is *not what the code does*; a test asserting it would be
writing the fix, not testing the code. And the whole-repo run is green, so the
suite's strongest signal actively confirms health: **the 100% suppression rate
is indistinguishable, from inside the test suite, from a clean codebase.** That
equivalence is the defect.

### Detector hypothesis

Extend `audit_error_hiding.py` with a third integrity rule beside
`stale-exclusion` and `malformed-allowlist-entry`:

- **`over-broad-exclusion`** — an entry matching more than one finding fails,
  with the remedy being to split it into one entry per site (which forces a
  written reason per site, the property the file already claims). Today it
  fires 24 times. **False positives: the shell-script `lines`-keyed entries,
  which legitimately list several line numbers in one entry** (`/install.sh`
  `[55, 100, 103]`) — the rule must scope to `function`-keyed entries, or count
  `lines` entries as matching `len(lines)` legitimately.
- **`ambiguous-exclusion-file`** — an entry whose `file` suffix matches more
  than one file in the tree fails; the remedy is a longer, repo-relative
  suffix. Fires twice today (`init.sh`, `/install.sh`). False positives: near
  zero, and it self-resolves as soon as the path is lengthened.

Both read the data the audit already has in hand, so neither costs a second
scan. Noise estimate is low and, crucially, **bounded and one-off**: 26 findings
to burn down, after which the rules are quiet unless someone widens an entry.

A companion rule worth stating and probably worth *rejecting*: "fail when a
suppression file exempts >90% of findings". It would fire on all three QA gates
here, two of which are fine, and a rule that cries wolf gets disabled — the
`error_hiding_exclusions.json` header makes that argument itself. Report it as
noisy; do not ship it.

### Confidence

**High.** Every number above was produced by importing the audit module and
calling its own `collect_*`, `load_exclusions`, `apply_exclusions` and
`_exclusion_matches` against this checkout — no reimplementation and no
estimation. What it does not settle is whether the 29 over-covered findings are
individually *wrong*; they may each be defensible. The finding is that nobody
has been asked.

---

## Checks NOT answerable from here

None. Every source the brief named was reachable and read. Two are worth naming
as *bounded*, so the coverage claim is honest:

- **Client-install exemptions** (`F-DEPL`'s territory): the shipped-default half
  of Finding 2 was reasoned from the constants and confirmed against synthetic
  client paths, not against a real client tree. That is a different check.
- **`untracked/`**: excluded from the file-count measurements, since it is
  gitignored scratch and not part of the protected surface.

---

## What the register would need

Findings 1 and 2 are the same underlying class at different scales — **an
exemption whose written scope is narrower than its matched scope** — and could
share one register category (`exemption scope drift`) with two Detectors. Finding
3 is the same class again, applied to a suppression file rather than a handler
constant.

Per `CLAUDE/Security/README.md`, none of this goes into the register until a
Defence exists in `scripts/qa/` and is wired into `run_all.sh`. The Detector
hypotheses above are the inputs for that, not the Defence.
