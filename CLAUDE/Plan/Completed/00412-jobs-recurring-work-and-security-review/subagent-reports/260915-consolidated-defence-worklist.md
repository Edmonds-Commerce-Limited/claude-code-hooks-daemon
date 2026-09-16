# Consolidated defence worklist — Routine 00001 run 2026-001

**Input**: the 15 `260915-secreview-*.md` reports in this directory (D-DEP, D-EVAL,
D-EXEC, D-NET, D-PATH, D-PUB, D-RULE, D-SEC, F-BYPS, F-CVE, F-DEPL, F-EXPT,
F-GAP, F-HYG, F-PRIV), ~77 findings.
**Output**: defect CLASSES, each with a Detector hypothesis.
**Status**: consolidation only. Nothing here is a Defence yet; per
[the register's contract](../../../Security/README.md), a category is written
once its Detector exists in `scripts/qa/` and is wired into `run_all.sh`.

## Method, and its limits

I read all 15 reports in full, extracted every finding's own "The class"
statement, and then re-grouped across reports by asking one question per
finding: *what would a program have to READ to find every member of this?* Two
findings belong to the same class when the same reader answers both; they belong
to different classes when the readers differ, even where the reports used
similar words. That test deliberately cuts across the check boundaries — the
largest class below draws instances from eight separate reports, and two
findings inside a single report land in different classes. **The limits are
real and worth stating.** First, the grouping is mine and the reviewers did not
see each other's work, so where two reports describe one defect in different
vocabulary I have judged them the same and could be wrong; every such merge is
flagged. Second, I verified only a handful of citations against the tree (the
authored-path helpers, the register's scope, the plan-QA code-dir set) — the
rest are taken on the reporting agents' evidence, which is uneven: several
findings were executed against live code and several are readings. Third,
classes are NOT disjoint. Many findings are members of two; I name a primary
class and cross-reference the secondary rather than duplicating, which means
the per-class instance counts must not be summed. Fourth, a Detector hypothesis
here is a hypothesis: none has been built, none has had its false-positive rate
measured against the tree, and the noise estimates are the original reviewers'
unless I say otherwise.

---

## Already closed — excluded from this worklist

`authored-path-resolution` is COMPLETE: Detector
`scripts/qa/check_authored_path_stat.py`, fixes `73c90244` and `65161ce5`,
registered at `CLAUDE/Security/AuthoredPathResolution.md`. Excluded from the
classes below: **D-PATH Finding 1 / D-SEC Finding 3** (the `quote_drift` authored
source read — found independently by two reviewers, which is what promoted it)
and **D-PATH Finding 3** (the 31-site blind-spot measurement, which drove the
Detector's widening from 7 sites to 30).

### Members of that class the current Detector does not cover

The Detector's scope is `_SCOPED_TREES = ("docs_qa", "plan_qa")`
(`scripts/qa/check_authored_path_stat.py:91`). Four live members sit outside
what it grades:

1. **In scope, green, still defective.** `plan_qa/checks/path_existence.py:67`
   and `docs_qa/checks/pointer_resolves.py:95-100` both route through
   `authored_path_exists`, so the chokepoint rule passes them. I verified that
   helper: `src/claude_code_hooks_daemon/utils/authored_paths.py` ends
   `authored_path_exists` with `Path(os.path.normpath(base / target)).exists()`
   — it normalises and does **not** contain, unlike its sibling
   `contained_authored_path`, which does the `is_relative_to` check. D-PATH
   Finding 4 is therefore live: a `PLAN.md` inline-code span is a one-bit
   existence oracle over any host path, executed and confirmed by that reviewer.
   The register's "the rule forces the chokepoint; it does not choose the
   helper" bullet already names this gap in the abstract; the live instance is
   not recorded under it. **This is the cheapest outstanding item in the whole
   worklist** — the class, the Detector and the helper all already exist.
2. **Outside both trees, same shape.** `daemon/cli.py:6354-6355` (D-NET N4) takes
   `--path` from argv, joins nothing, and uses it as a WRITE destination for
   fetched network content. `_SCOPED_TREES` cannot see `daemon/`.
3. **Outside both trees, different sink.** D-EVAL Findings 1 and 2 — a config
   string reaching `exec_module`, and `..` unchecked on one branch of
   `utils/repo_relative_path.py`. D-EVAL argues these are a new category and I
   agree: the sink is code loading, not a stat, and the Detector must read
   config validators rather than path predicates.
4. **Outside both trees, route-dependent.** D-PATH Finding 2 (the tilde gap in
   `project_containment`) is a path defect but its Detector reads two
   normalisation routes, not a stat predicate.

Items 1 and 2 belong to class **17** below; 3 belongs to **3**; 4 belongs to
**1**.

---

## The classes, in priority order

Priority weighs blast radius first, then corroboration (independent discovery by
two or more reviewers), then Detector cost. "Buildable now" means the Detector
can be written and landed without a decision that changes behaviour in
installing projects. "Owner-gated" is marked per half, because in most cases
the Detector is buildable and only the FIX is gated.

---

### 1. `asymmetric-sibling-protection`

**The class**: this repository already implements the correct behaviour at
another site, and this site re-derives it, derives it shorter, or omits it.

This is the single largest class in the corpus — eleven instances drawn from
eight independent reports, none of which saw the others. Three reviewers reached
for almost identical phrasing without coordination: *"the escaper already
exists, in this module, twenty lines above"* (D-EXEC F3), *"the shared fragment
exists, is used by the neighbouring handler"* (D-PUB-4), *"a fix applied to the
instance rather than to the class"* (F-DEPL-4). That convergence is the strongest
ranking signal in the entire review.

**Instances**:

| Site                                                                                          | The sibling that does it right                                                                   | Report(s)        |
| --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ---------------- |
| `handlers/pre_tool_use/worktree_file_copy.py:104` — 3 relocation verbs                        | `core/utils.py:94` `_WRITE_INDICATOR_RE` — 6                                                     | F-BYPS-7         |
| `handlers/pre_tool_use/sensitive_content.py:249-251` — bare-name `gh` anchor                  | `:995` hardens `git`; `utils/command_evasion.py:98` `OPTIONAL_PATH`                              | D-PUB-4          |
| `handlers/pre_tool_use/sensitive_content.py:762-774` — scans the command, not the named file  | `handlers/pre_tool_use/github_auto_close_keywords.py:130-132,253-257` reads it                   | D-PUB-2          |
| `handlers/pre_tool_use/sensitive_content.py:819-827` — oversized/unreadable body file → allow | `handlers/pre_tool_use/issue_filing_gate.py:329-342,364-368` → refuse                            | D-PUB-3          |
| `handlers/pre_tool_use/sensitive_content.py:884` — no protected-path exclusion                | `handlers/pre_tool_use/staged_lint_gate.py:249` has exactly that exclusion                       | D-SEC-1, F-HYG-3 |
| `handlers/pre_tool_use/project_containment.py:319-327` — `_resolve_against_cwd` declines `~`  | `_resolve_write_target` (`:617-618`) expands it; `core/utils.py:71-76` says expanding is correct | D-PATH-2         |
| `install/forwarder_generator.py:246-263` — unescaped interpolation                            | `_escape_for_double_quotes` at `:90`, applied at `:128` in the same file                         | D-EXEC F3        |
| `remote_docs/store.py:148-199` — `refresh_document` has no `content_guard`                    | `write_capture` (`:133-138`) has one                                                             | D-NET N2         |
| `install/skills.py:49-61` — `rmtree` with no provenance test                                  | `:96-121` retired-skill path requires a provenance marker                                        | F-DEPL-2         |
| `install.py:822-830,987` — config backup gated, write not                                     | `:742-745` documents this exact defect as fixed, for `settings.json`                             | F-DEPL-4         |
| `strategies/pipe_blocker/common.py:56` — `^env\b` whitelisted as a cheap filter               | `utils/process_probe.py:506` `_WRAPPERS` classifies `env` as a command runner                    | F-EXPT-1         |
| `handlers/session_start/gitignore_safety_checker.py:25-51` — hardcoded 5-tuple                | `utils/secret_file_matching.py:54-61` resolved dynamically, strictly wider                       | F-HYG-1          |
| `scripts/qa/check_sensitive_content.py:145-146` vs `:176-183`                                 | two adjacent functions degrade in OPPOSITE directions on the same `ImportError`                  | F-PRIV-4         |

**Detector hypothesis**: a checked-in **pair registry** —
`scripts/qa/check_declared_invariant_pairs.py` reading a YAML table of
`(site A, site B, relation)` rows, where relation is `superset`, `equal` or
`same-normalisation`, and each row is asserted mechanically. Two rule kinds:

- *Constant pairs* — extract a literal alternation or tuple from each side and
  assert the set relation. Covers `worktree_file_copy` ⊇ `_WRITE_INDICATOR_RE`,
  `pipe_blocker` whitelist ∩ `_WRAPPERS` = ∅, `sensitive_content` body-file regex
  ⊇ `github_auto_close_keywords` message-file regex,
  `_REQUIRED_GITIGNORE_PATTERNS` ⊇ `resolve_configured_patterns()`.
- *Call-path pairs* — assert that a named helper reached from site A is also
  reached from site B (`_escape_for_double_quotes`, `path_is_protected`,
  `content_guard`, `_expand_home`).

**False positives**: near zero **by construction**, because every row is
declared. F-EXPT measured its row as a pure set intersection with "zero false
positives by construction". F-HYG-1's row needs one named opt-out from day one
(a protected glob a project deliberately tracks — an `.example` template is the
standing case, and this repository had exactly that until recently); without it
the check gets disabled rather than satisfied.

**The blind spot, which must be written into the category**: a registry only
covers declared pairs. A twelfth divergence with no row is invisible. The
*generative* half — a rule that proposes candidate pairs by finding a constant
or helper consumed by one of two handlers that judge the same command — is
reportable **as noisy** and should not gate a build.

**Buildable now** (Detector and most fixes). Two fixes are owner-gated:
D-PUB-3's fail-closed on an oversized body file, and F-HYG-3's new deny in
`staged_lint_gate`, both of which add a refusal in installing projects.

**Severity: CRITICAL.** Not because any one instance is catastrophic, but
because the class is where this project's own good reasoning stops propagating,
and because eight reviewers found it independently. Several instances are
one-line fixes with the correct code visible in the same file.

---

### 2. `guard-self-disablement-unwatched`

**The class**: an action that changes what a future session's guards will do,
where no gate judges the action and no record is made that it happened.

**Instances**:

- **F-GAP G9** — probed across three routes and four files, every result
  `NOTHING DENIES`: `Edit` / `Write` / Bash redirect / `cp` / `mv` / `chmod 000`
  on `.claude/hooks-daemon.yaml` and `.claude/settings.json`,
  `bin/hooks-daemon config set … enabled false`, `bin/hooks-daemon stop`,
  `rm -rf .claude/hooks-daemon`. F-GAP notes the compounding property: every
  deny message prints the config key that disables the guard that just fired.
- **F-BYPS-3** (corroborates G9 independently) — `daemon/controller.py:915-925`.
  One schema-invalid key anywhere in the config puts the daemon in degraded
  mode, where `_degraded_mode_safety_net` (`:794-830`) runs `destructive_git`
  and nothing else, and `HookResult.configuration_error` returns `ALLOW`. ~60
  handlers retired by one edit that reads as a typo.
- **F-BYPS-4** — four guards' deny text asserts "there is NO escape hatch" /
  "only a human may lift this". Nothing in the tree enforces it, and the same
  message names the key to edit.
- **F-GAP G10** — `.git/hooks/pre-commit` is writable with nothing denying; and
  `git commit --no-verify` / `-c core.hooksPath=/dev/null` both probed clean.
- **D-RULE Findings 1 and 2** — a verdict change landing inside a commit whose
  subject describes unrelated work. Finding 2 is the proven case: `git_stash`
  ran advisory-only for months after a downgrade inside a QA-coverage commit
  (`1b0ce868` → `cd292a02`), and the restoring commit's subject reads as though
  the deny were new — the tell that nobody knew it had ever been one.
- **D-RULE's structural observation** — `handlers/registry.py:577` applies
  handler options with an unvalidated `setattr(instance, f"_{option_key}", …)`.
  No schema check, so a typo'd option silently grants nothing and a real option
  (`sed_blocker.blocking_mode`) silently downgrades a guard. Both directions
  fail quietly.
- **F-BYPS-8** — see class 3; it is the sharpest form of this class because it
  defeats even the degraded-mode safety net.

**Detector hypothesis**: three parts, and the split matters because only two are
non-circular.

- (a) **Commit-time gate**, sibling of `staged_lint_gate` — a staged diff that
  flips `Decision.DENY` to `ALLOW`/`CONTINUE`, removes a `HandlerTag.BLOCKING`,
  flips `get_default_enabled()` from `True` to `False`, net-removes entries from
  a handler pattern collection, or flips `enabled: true → false` / widens
  `exclude_paths` in the config, must carry a `RULE CHANGE:` line in the commit
  message. D-RULE ran the diff-scan half retrospectively over 3,815 commits: 21
  candidates, 19 already carrying a reason, so the steady-state cost is roughly
  one prompt per 180 commits.
- (b) **SessionStart reconciliation** — diff the live config against the
  committed one and report drift. Catches the uncommitted case (a) cannot.
  F-GAP judges this the lowest-noise part and the one to build first.
- (c) **A schema check on handler options**, closing the `setattr` hole so a
  typo is loud.

**False positives**: (a) fires on mechanical refactors that relocate a pattern —
D-RULE names three commits (`e2295c51`, `abaa876f`, `56dab785`) that net-remove
regexes while moving them to a shared module, and each would demand a line it
does not deserve. D-RULE's own recommendation is to ship it noisy and write the
line, because diffing the *effective* pattern set is more work than the gate is
worth. (a) will also fire on every legitimate tuning commit in this repo, which
is frequent — it needs a usable approval escape hatch or it gets switched off,
"which would be the finding eating itself". (b) is near-zero-noise.

**Detector buildable now** (all three parts). **The FIX is OWNER-GATED, and this
is the sharpest gate in the worklist**: a PreToolUse deny on writes to
`.claude/hooks-daemon.yaml` is a new refusal surface in every installing
project, and F-GAP argues it is *also circular* — an agent that can edit the
config can edit the rule that guards it. The non-circular remedies are the
commit gate and the drift report, which is why those are the buildable half.
The degraded-mode blast radius (F-BYPS-3) is separately gated: narrowing
fail-open to the handlers that actually depend on config changes behaviour for
every installing project with a bad config.

**Severity: CRITICAL.** F-GAP states it plainly and I agree: *"If only one is
actioned, it should be G9 — it is the only finding that determines whether the
other ten matter."* Every other class in this document is conditional on the
guards being live.

---

### 3. `enforcement-path-executes-unverified-code`

**The class**: the guard process loads or spawns code whose origin is not
tracked in this repository, not pinned by its lockfile, and not integrity-checked
at the moment of use.

**Instances**:

- **D-DEP-01 (HIGH)** — `handlers/post_tool_use/validate_eslint_on_write.py:296-327`.
  The daemon prepends the *guarded project's* `node_modules/.bin` to `PATH` and
  spawns bare `tsx` with `cwd` set to that project, executing
  `scripts/eslint-wrapper.ts` **from that project's tree** — a file this
  repository does not ship. Any malicious package in a client's npm tree gets
  code execution in a daemon subprocess on the next TypeScript write. The
  `nosec B603 - eslint/npx are trusted tools` comment is the finding's core: the
  tool *names* are trusted, the binaries those names resolve to are supplied by
  the tree under review.
- **D-EVAL Finding 1** — `handlers/project_loader.py:177-183` reaches
  `spec.loader.exec_module` from `config/models.py:460-484`'s
  `project_handlers.path`, which is exempt from repo-relativity with no
  containment, ownership or provenance check. A module body runs *before* any
  `matches()` gate, so a file that is purely a payload executes and is then
  logged as a load failure. D-EVAL Finding 2 is the compounding half: `..` is
  never checked on the non-token branch of `utils/repo_relative_path.py:179-191`,
  so `path: "../../evil"` is accepted while `path: "{REPO_ROOT}/../../evil"` —
  the same directory, spelled the documented way — is rejected.
- **F-BYPS-8 + F-DEPL-6 (corroborated, two reports)** — the forwarder hot path
  `exec`s `untracked/bin/hooks-relay` on the `-x` bit alone. The directory is
  gitignored by design, the digest recorded at deploy is never re-read, and
  `relay/SHA256SUMS.released` — the independent baseline the design names and
  `install/transport_probe.py:160` resolves as its source of truth — **does not
  exist in the tree**. F-BYPS: this is the only route that also defeats the
  degraded-mode safety net, because it never reaches the daemon.
- **D-DEP-03** — `mdformat.text(extensions={"gfm"})` reads as a closed
  allowlist and is not one: mdformat's `_load_entrypoints` calls `ep.load()` for
  *every* distribution declaring `mdformat.parser_extension`, so the trust set
  for the daemon process is the venv, not the import list. No live exposure
  today (verified across the QA venv's `entry_points.txt`); the finding is that
  nothing states or checks the boundary.
- **D-DEP-02** — `[build-system] requires = ["setuptools>=61.0", "wheel"]`, in
  neither `uv.lock` nor the venv, resolved fresh from PyPI at every sync
  including every client install, executing arbitrary Python at build time.
  Also a member of class 13.

**Detector hypothesis**: enumerate every execution and import sink reachable
from the daemon process — `spec_from_file_location`, `exec_module`,
`import_module`, `runpy`, `subprocess` with a bare argv[0], `entry_points(group=)`
consumers, and the generated forwarders' `exec` targets — and require each
origin to be one of: tracked in git, pinned in `uv.lock`, or digest-verified at
use. The narrow high-yield form D-DEP proposes for its own instance is worth
building first because it is nearly free: **fire only when a `subprocess` call's
argv[0] is a bare name AND the same function mutates `env["PATH"]`**. That
condition is met exactly once in the current tree.

**False positives**: D-EVAL names the concrete ones — `config/validator.py:148,169`
calls `importlib.import_module` on a constant-prefixed name and on a
`pkgutil.walk_packages` result, both constrained, both flagged by a naive
sink-grep. The rule needs a constant-prefix / package-walk allowance, "and that
allowance is itself where a future defect could hide". D-DEP's PATH-mutation
variant has near-zero noise. The `entry_points` rule cannot run as a pure source
lint — it needs the venv present, so it belongs beside `assert_venv_matches_lock`,
not in `run_lint.sh`.

**Detector buildable now. FIX OWNER-GATED** for three of the five: constraining
`project_handlers.path` to `normalise_repo_relative_path` removes a documented
config capability (D-EVAL notes the exemption cites a *test* as its
justification, not a use case, which is exactly the question the owner should
settle); `relay_binary` has no validator and adding one narrows the config
surface; and F-BYPS warns that digest verification at exec is **higher risk than
the finding** — a stale manifest after an ordinary local rebuild would deny every
hook, so it must be advisory-first and session-start rather than per-call.
D-DEP-01's fix (ship the wrapper, or resolve `tsx` from a fixed path) is
buildable now.

**Severity: CRITICAL.** Corroboration across four reports (D-DEP, D-EVAL,
F-BYPS, F-DEPL), and the outcome is code execution inside the process that
enforces every other guard.

---

### 4. `fail-open-when-the-check-cannot-run`

**The class**: the guarded action proceeds when the guard could not reach a
verdict — and in several cases the party the guard constrains can induce the
condition.

**Instances**:

- **D-PUB-3** — `sensitive_content.py:819-827`. An oversized or unreadable `gh`
  body file returns `""`, the file drops out of the haystack list, and the
  command is ALLOWED. The bound is 65,536 *bytes* while GitHub's comment limit
  is 65,536 *characters*, so roughly forty thousand multibyte characters sits
  comfortably inside what GitHub accepts and outside what the handler will read.
  D-PUB's honest counter-argument is recorded and I keep it: for a MISSING file,
  allowing is correct because `gh` fails on its own. The defect is that one
  branch serves both cases and the comment justifies it using the harmless one.
- **F-BYPS-5** — `relay/hooks_relay.rs:150-171`, reached with `FailClass::Timeout`
  after the forwarder's 30000 ms budget. Any tool call the daemon takes longer
  than that to judge is allowed, with one stderr line as the only trace. The
  class-defining property: the daemon's work on a PreToolUse event is a function
  of input the CALLER chooses — a large staged commit, an ESLint spawn, a
  tree-wide QA gate. "Make the guard slow, and the guard is skipped."
- **F-BYPS-3** — degraded mode (also class 2).
- **D-DEP-08** — `daemon/server.py:627-641` and `core/input_schemas.py:356-359`.
  `jsonschema` is a hard runtime dependency imported inside `try/except ImportError`, and with `strict_mode` defaulting to `False` a failed import
  runs the daemon with hook-input validation entirely off, returning `[]` —
  indistinguishable from "validated, no errors".
- **D-EXEC F1's realistic outcome** — an apostrophe in a checkout path or
  hostname makes `python3 -c` die with a `SyntaxError` before opening the
  socket; the forwarder exits non-zero with nothing on stdout, Claude Code treats
  it as a non-blocking hook error, and every PreToolUse guard is inert on every
  event.
- **`core/chain.py:470-495`** — the non-strict per-handler `except`, correctly
  scoped (blast radius is one handler, not the chain — F-BYPS verified this and
  records it as correctly built) but still a fail-open boundary that belongs on
  the inventory.

**Detector hypothesis**: an **inventory-shaped rule**, which is the right shape
because the discriminator is a property of the surface rather than of the code.
Require a declared entry for every fail-open boundary in the enforcement path
(`core/chain.py`, `core/front_controller.py`, `daemon/controller.py`, `relay/`,
`.claude/init.sh`) naming: what induces it, whether the inducing input is
caller-controlled, and **what trace it leaves in-band**. The Detector fails when
a `timeout` / `except` / degraded path exists there with no entry. F-BYPS
estimates about six entries, which is the right size for a hand-maintained
document, and names column three as the valuable one: several of these currently
leave only a stderr line.

Paired with a sharper code-reading rule for the D-PUB-3 shape: in handlers
carrying `HandlerTag.SAFETY` and `HandlerTag.TERMINAL`, flag an `except OSError`
or size-bound branch whose value feeds a haystack/candidate collection rather
than a deny.

**False positives**: the code rule is **NOISY as stated and D-PUB reports it as
such** — the staged-diff stand-down at `sensitive_content.py:873-875` and the
per-file bound at `:886-891` are the same shape and are arguably correct,
because a commit can be amended before it is pushed while a comment cannot be
recalled. That discriminator is not visible to any regex, which is why the
inventory (scoped to a hand-maintained list of irreversible surfaces, shared
with class 10) is the honest form. The general `except`-scan over the whole tree
is not worth shipping.

**Why no test catches any of it**: uniquely stark here — the tests *encode* the
behaviour. `test_timeout_fail_open`, `test_missing_body_file_is_allowed`,
`test_stdin_body_file_is_allowed`,
`test_a_body_file_that_cannot_be_read_is_skipped_and_logged`. The suite
positively verifies the fail-open and reads to a reviewer as deliberate coverage
of the branch.

**Detector buildable now. FIX OWNER-GATED**: converting any of these to
fail-closed changes behaviour in every installing project — a slow guard would
begin blocking, a bad config would begin refusing every tool call. F-BYPS names
the measurement that sizes the relay half and it has not been done: if a
5,000-file commit judges in a couple of seconds the finding is theoretical; if
it judges in forty it is live. **That measurement is the single most valuable
follow-up in the corpus** and should precede the owner's decision.

**Severity: HIGH.**

---

### 5. `absence-indistinguishable-from-clean`

**The class**: a scanner or gate reports a clean result without reporting its
denominator, so "nothing matched" and "nothing was checked" render identically.

This is the class the reviewers' own contract names — `.claude/agents/security-reviewer.md:59-65`
requires a human reviewer to distinguish the two — and F-PRIV's observation is
that the obligation is stated for the reviewer and not enforced on the tooling
the reviewer reads.

**Instances**:

- **F-PRIV-4** — `bin/hooks-daemon secret-meta` reports the configured word list
  `exists: false` in this checkout and `resolve_secret_terms()` returns **0
  terms** while the path resolves successfully. The secret-term half of
  `sensitive_content`, of both batch sweeps, and of every `gh`-body scan is
  therefore inert, and all four report clean. Neither `run_all.sh` nor `llm_qa.py`
  asserts a non-zero term count. **This corrupted the review itself**: F-PRIV's
  first pass ran under the system interpreter, where
  `scripts/qa/check_sensitive_content.py:176-183` returns unfiltered on
  `ImportError`, and reported 37 phantom violations and zero secret terms.
- **F-CVE-1 + D-DEP-05 (corroborated, two reports)** — `safety` is declared in
  the dev extra, locked, installed into every dev and CI venv, and invoked by
  nothing. Anyone auditing this project's posture finds a declared dependency
  scanner and concludes one exists. `deptry`'s DEP002 — the rule that would say
  so — is disabled project-wide at `pyproject.toml:289` with a comment that is
  correct about `black`/`ruff`/`mypy` and wrong about these three. F-CVE adds the
  sharp corollary: `safety` is itself the parent of the worst-affected vulnerable
  packages in the tree, so **removing the tool that does nothing deletes 69 of
  the 88 advisory IDs**.
- **F-PRIV-1 / F-PRIV-2** — `scripts/qa/check_git_history.py` prints *"No
  git-history violations found (2222 commits, 150 refs scanned)"* over history
  that carries 16 real-shaped session UUIDs across 51 blob revisions and
  profanity residue across 44 more. Not merely silent: an affirmative clean claim
  over the exact history that carries the residue. Primary class is 12; listed
  here because the clean *line* is this class.
- **F-EXPT-3** — the error-hiding gate suppresses 225 of 225 findings. "The 100%
  suppression rate is indistinguishable, from inside the test suite, from a clean
  codebase." Primary class is 8.
- **F-HYG-2** — the hygiene checker's own printed remedy (`git rm --cached`)
  moves a path from `tracked` to `ignored`, the advisory goes quiet, and the
  material remains in every clone and fork. "A remedy that converts a true
  finding into a false clean is worse than no remedy, because it consumes the one
  signal that would have prompted the force-push conversation."

**Detector hypothesis**: two parts, and part 1 is the cheapest high-value item
in this entire worklist.

1. **Report the denominator.** Every gate's clean line carries its input counts —
   terms loaded, patterns compiled, files/commits/blobs scanned, findings
   suppressed — and `llm_qa.py` surfaces them. A clean result that says
   `0 secret terms loaded` is no longer a clean result to a reader.
2. **Fail when a configured source resolves to nothing.** If
   `secret_word_list_path` is configured and loads zero terms, the config asked
   for a check that is not running. Extend to: a declared security tool with no
   caller anywhere in `scripts/`, `.github/workflows/`, `.claude/skills/`.

**False positives**: **part 1 has none at all** — it only adds information.
Part 2 fires on a project that deliberately configures the key with an empty
list (a placeholder, or a client with nothing to withhold yet), which F-PRIV
argues is arguably the correct pressure but is a real cost and should warn
before it blocks. The declared-tool half is **moderately noisy as stated** —
F-CVE estimates 5-6 fires on the current 17-entry dev extra of which 1 is the
finding, because `build`/`twine` are invoked by the release skill and
`pre-commit` by git hooks, and type-stub packages are never "invoked" at all.
F-CVE's lower-noise variant is the one to ship: restrict it to a curated list of
*security* tools, where a declared scanner with no caller is always a defect
because its entire value is in being run.

**Buildable now, both halves.** Part 1 is a no-decision change.

**Severity: HIGH**, and it is the class I would build first on
cost-to-value grounds. It also makes every other class's evidence trustworthy:
several findings in this corpus were only visible because a reviewer noticed a
clean line was lying.

---

### 6. `outcome-reachable-by-an-unenumerated-spelling`

**The class**: a dangerous outcome is reachable by a command, flag or shell
construct that no guard's pattern names — either because the guard enumerates a
tool whose subcommand set is open, or because no guard exists for the outcome at
all.

I merge F-BYPS's "sibling-spelling gaps" and F-GAP's "no handler judges it"
deliberately, against both reports' own framing, because **the same Detector
finds both**: a corpus of canonical dangerous invocations driven through the
real handler chain with a recorded verdict per row. Whether a row's verdict is
`UNCOVERED because the pattern is short` or `UNCOVERED because nothing exists`
is a fact the Detector reports, not a reason for two Detectors. F-GAP itself
flags the overlap ("a duplicate is cheaper than a hole") and routes one
candidate to F-BYPS.

**Instances** — grouped by axis, with corroboration marked:

- *Working-tree destruction*: `git checkout -f`, `git checkout --force`,
  `git switch -f`, `git switch --discard-changes`, `git reset --keep|--merge`,
  `git read-tree --reset -u` — **F-BYPS-1 + F-GAP G5, independently, both
  probed**. `destructive_git.py:87-165` names none of them; the string `switch`
  occurs in exactly one handler in the tree and there as a branch-name surface.
- *Filesystem destruction*: `rm -rf` (**F-GAP G1**), `truncate -s 0`, `dd`,
  `> file`, `mv`, `cp` over an existing tracked file (**G2**). G1 is the worst
  single row because `CLAUDE/ARCHITECTURE.md:30` and
  `CLAUDE/HANDLER_DEVELOPMENT.md:89` both list `rm -rf` beside `sed -i` and
  `git reset --hard`, which genuinely are blocked — so the absence cannot be
  discovered by reading. It was noticed once already, in
  `CLAUDE/Plan/Completed/00017-acceptance-testing-playbook/PLAN.md:183`, and
  never actioned.
- *Recovery-net destruction*: `git reflog expire --expire=now --all` +
  `git gc --prune=now` (**G3**). Sharp because `destructive_git.py:632`'s own
  acceptance test justifies itself with "recoverable via reflog" — the handler's
  safety reasoning depends on a mechanism nothing protects.
- *History rewrite*: `filter-branch`, `filter-repo`, `rebase` (**G4**).
- *Ref destruction*: `git push origin --delete`, `git push origin :ref`,
  `git tag -d`, `git tag -f` (**G6**). The near-miss is sharp: the push-force
  pattern already parses refspec sigils and handles `+`, one key from `:`.
- *Remote code via a package manager*: `npm/pip/cargo/go/gem install`, `npx`,
  and the sharpest case `pip install --index-url <attacker>` (**G7**).
- *Credential routes*: `gh auth token`, `gh auth status --show-token`, `env`,
  `printenv`, `git credential fill` (**G8**). Confirmed live on this host:
  `~/.config/gh/hosts.yml` holds the OAuth token at mode 0600 and matches no
  default protected glob. F-GAP is careful and correct that this is not a defect
  in `secret_file_guard` — these routes are command-shaped, not path-shaped, and
  outside what that guard claims.
- *Fetch-then-execute respellings*: `bash <(curl URL)`, `eval "$(curl URL)"`,
  `source <(curl URL)`, `python3 -c "$(curl URL)"` (**F-BYPS-6**). The handler
  has been hardened twice for respellings around the pipe; the pipe itself
  remained load-bearing.
- *Publication*: `gh release create --notes` (**D-PUB-1 + F-BYPS-2,
  independently**) — see class 10, where it is primary.
- *Relocation verbs*: **F-BYPS-7** — see class 1, where it is primary.
- *Future sessions and the host*: `.git/hooks/` writes, `--no-verify`,
  `-c core.hooksPath=` (**G10**); `crontab -r`, `docker run -v /:/host`,
  `kill -9` (**G11**).
- *Drift coverage*: **F-DEPL-3** is the same shape one level up — the drift
  handler compares 3 agent definitions, 3 core docs and 2 plan scripts, and
  compares **none of the 31 scripts Claude Code executes on every hook event**,
  `init.sh`, the two `bin/` wrappers, `claude-supervise.py`, the relay binary, or
  `.claude/rules/*.md`. F-DEPL's class statement is the memorable one: *a
  coverage set chosen by ownership-model convenience rather than by blast
  radius*.

**Detector hypothesis**: a table-driven inventory in the shape of the existing
`tests/integration/test_bash_write_blindness_coverage.py` — a checked-in corpus
of dangerous invocations, each with a recorded verdict (`COVERED` /
`UNCOVERED, accepted` / `UNCOVERED, open`), asserted by running each string
through the real chain's `matches()` **and** `handle()`. The second pass is not
optional: F-GAP measured that `verification_result_gate` *matches* almost every
git command and then allows it, so a `matches()`-only method would have scored
24 git candidates as covered when nothing denies them.

Plus a second, cheaper, near-zero-false-positive Detector for the documentation
half of G1: **assert that every construct named in a "we block X" list in
tracked documentation resolves to a real rule ID.** That one should ship first.

**False positives**: **none from the inventory itself** — it asserts against a
checked-in verdict, so a deliberate non-coverage is recorded rather than
flagged. Its weakness is the opposite and must be written into the category:
*the corpus only covers what someone thought to add*. It converts an invisible
gap into a visible list; it does not generate the list. This is the honest
reason it is a weaker Detector than classes 1, 5 or 7, and it must be described
as such rather than as coverage.

**Detector buildable now. FIXES OWNER-GATED, per row.** Every new deny is a new
refusal surface in installing projects, and several rows are explicitly reported
as too noisy to deny: F-GAP reports `git rebase` as the noisy one and refuses to
recommend a blanket block ("it would be suppressed within a release"); reports
the broad `npm install` deny as high-noise and recommends only the narrow
`--index-url`/`--registry` redirection deny; reports bare `env`/`printenv` as
occasionally misfiring; and recommends the `kill` rule consult
`background_process_tracker` rather than guess. The low-noise rows —
`filter-branch`/`filter-repo`, `reflog expire`, `gc --prune=now`, `checkout -f`,
`switch -f`, `docker run -v /:`, `crontab -r`, `.git/` writes — are worth doing
independently of the noisy ones.

**Severity: HIGH.** The corpus is large and one row (G1) is documented as
covered while being absent.

---

### 7. `interpolation-into-another-language`

**The class**: a runtime value is placed into the SOURCE TEXT of another
interpreter or the body of a structured format, rather than passed as an
argument or serialised by that format's own writer.

**Instances**:

- **D-EXEC F1** — `.claude/init.sh:1423` (and the tracked client template
  `init.sh:1423`). The `python3 -c` body is double-quoted, so bash expands
  `$SOCKET_PATH` into the Python *source*, inside a single-quoted Python literal.
  Four unvalidated sources feed that variable, including an environment variable
  documented as a testing override. **The same file already does it correctly
  twice** — line 1469 and `forward_stop_event` both pass values as argv and read
  them from `sys.argv`.
- **D-EXEC F3** — `install/forwarder_generator.py:246-263`. `relay_binary` is a
  bare `str | None` at `config/models.py:1483` with no validator, interpolated
  unescaped into a `"`-delimited span of a file that executes on every hook
  event. Also class 1 (the escaper is twenty lines above) and class 3.
- **D-EXEC F2** — `scripts/run-qa-runner.sh:63-83`. `$1`, `$2` and `$4`
  concatenated unquoted into `CMD`, then `eval "$CMD"`. This is the *documented*
  invocation (`docs/QA.md:58`), so the path an operator types goes straight into
  an `eval`.
- **D-EXEC F4** — `handlers/post_tool_use/lint_on_edit.py:474-476` and
  `handlers/pre_tool_use/staged_lint_gate.py:288-289`. The file path is
  substituted into a command template and then `.split()` on whitespace, so every
  space in the path becomes an argv boundary. The inline comment is accurate
  about the tool and silent about the path, which is where the problem is. The
  correct shape is one line later in the same handler.
- **D-NET N3** — `remote_docs/capture.py:162-186` renders provenance frontmatter
  by f-string with no `yaml.safe_dump` and no rejection of `\n` or `---` in any
  value. `_FRONTMATTER_RE` is non-greedy, so an injected `\n---\n` terminates
  the block early and the parsed provenance is whatever the injected lines said.
  The payoff is a redirection primitive, not just a forged field: a forged
  `source_url` makes `remote_docs_routing` **deny a WebFetch of the genuine URL**
  and steer the agent to the forged local copy.

**Detector hypothesis**: two rules in files that already exist.

- *Shell* — add to `scripts/qa/audit_shell.py`, which already owns the scan,
  JSON and marker plumbing: flag any command whose argv carries a `-c`/`-e` code
  flag for a known interpreter where the following word is a double-quoted or
  unquoted string containing `$` or a backtick; and separately flag `eval`
  applied to any variable. Report the expansion, not the body. **Must not fire on
  single-quoted bodies — that is the whole remediation.**
- *Python AST* — in the modules that emit shell or structured documents, flag a
  `JoinedStr` whose literal parts contain a shell quote or a format delimiter and
  whose `FormattedValue` parts do not pass through a known escaper
  (`_escape_for_double_quotes`, `shlex.quote`, `yaml.safe_dump`, an enum `.value`,
  `.isoformat()`). Separately, flag a `subprocess` argv that derives from a
  `.split()` on a string that had a value substituted into it.

**False positives**: stated per rule by the reporting reviewers and they are not
uniform. The shell interpreter rule fires on a deliberate one-shot where the
value is a literal the script just built from a constant, and on `bash -c "$cmd"`
test-harness idioms — absorbed by `audit_shell.py`'s existing
`# shell-audit: allow -- <reason>` marker. The `eval` rule fires on
`eval "$(some-tool shellenv)"`, a legitimate toolchain-activation idiom: one hit
in this repo, potentially noisy in a client project. The f-string rule is the
worst: D-EXEC counts roughly a dozen interpolations in `forwarder_generator.py`
of which about five are genuine, so **around 40% precision as stated** — it needs
a shell-comment exclusion to be worth enabling, and D-EXEC flags it as
moderately noisy rather than clean. D-NET's frontmatter variant is **noisy as
stated** (it fires on every log message shaped `key: {value}`, of which `cli.py`
has many) and needs scoping to modules that write `.md`/`.yaml` or import `yaml`.
The `.split()` rule is high precision once narrowed to splits on a string
produced by `.replace()`/f-string/`%`, which catches both sites and drops the
static-constant case.

**Buildable now.** No gate-surface change: these are fixes to how this
repository's own code builds strings.

**Severity: HIGH.** D-EXEC's own ranking stands: F1 and F2 are where a string is
handed to an interpreter and the interpreter's behaviour changes; F3 is the same
shape one remove away and has the cleanest remediation because the escaper is
already in the file; F4 is the one most likely to fire by accident on a real
machine (a checkout path containing a space denies legitimate writes today).

---

### 8. `exemption-scope-drift`

**The class**: an exemption's MATCHED scope is wider than its WRITTEN scope, so
the licence silently extends to sites nobody evaluated.

F-EXPT proposes this grouping for its own three findings and I extend it by two.
The headline from that report is worth preserving: this repository's
configuration is unusually disciplined — `daemon.exclude_paths` absent,
`grandfather_allowlist` and `legacy_plan_allowlist` empty, all 16 opt-in
handlers explicitly enabled. **The hollowing is not in the YAML.** It is in
built-in exemptions no configuration key can reach.

**Instances**:

- **F-EXPT-1** — `strategies/pipe_blocker/common.py:56` whitelists `^env\b`, and
  the whitelist is evaluated *first and wins*, so a whitelisted producer skips
  the blacklist and the unknown-command DENY tier entirely. `env` is a command
  runner: prefixing any command with four characters moves the producer to `env`
  and the guard becomes optional for every command in existence. Demonstrated by
  driving the shipped handler. Two weaker entries share the root cause — `^sort\b`
  (the module's own SIGPIPE rationale is simply false for a full-buffering
  command) and `^find\b`. Also class 1.
- **F-EXPT-2** — `strategies/security/common.py:3-23`. `SKIP_PATTERNS` is
  substring-matched (`skip in file_path`), applied *before* the configurable
  branch, and reachable from no config key at all. Measured on this checkout:
  **106 of 1875 tracked source files (5.7%) are permanently unscannable**,
  including `CLAUDE/Plan/mkplan.bash` — the plan scaffolder every agent is
  instructed to execute. A `Write` introducing `os.system` or a hardcoded
  credential block into that file is not merely unblocked, it is *unblockable*.
  The client-facing half is larger: `/docs/`, `/CLAUDE/` and
  `/strategies/security/` are shipped substrings, so any client whose tree
  contains `app/docs/` gets a silent permanent hole it never opted into. And
  `.env.example` is not directory-shaped at all, so it matches
  `.env.example.prod`.
- **F-EXPT-3** — `scripts/qa/error_hiding_exclusions.json`. Measured by importing
  the audit's own functions: 225 raw findings, 196 entries, **0 after
  exclusions**. Two leaks: a `function`-keyed entry ignores line and count, so 24
  entries cover 53 findings between them and a new `except` in the same function
  is pre-authorised; and `file` is matched by `endswith`, so four near-bare
  basenames match more files than the author can have meant. The existing
  `find_stale_exclusions` uses the *same* predicate, so it detects withdrawal
  debt and structurally cannot detect widening.
- **D-RULE-1** — `handlers/pre_tool_use/plan_time_estimates.py:67-84`.
  `TECHNICAL_PATTERNS` exempts a line by mere PRESENCE of any of 15 ordinary
  words, while the deployed guidance states the exemption SEMANTICALLY
  ("durations that describe a feature"). The exempting vocabulary is the working
  vocabulary of a hooks daemon. Introduced in a commit whose subject describes
  unrelated work and never touched since; a prior review found the scope axis and
  fixed it, and the description-vs-containment axis it also named was never
  closed. No exploitation detected in the tree.
- **D-DEP-05** — `ignore = ["DEP002", "DEP003"]` is one blanket suppression
  covering two populations it cannot distinguish: CLI tools genuinely invoked,
  and three that are invoked by nothing. Also class 5.

**Detector hypothesis**: `scripts/qa/check_exemption_dialect.py`, three rules.

- Any exemption constant consumed by `x in path` where the entry is
  directory-shaped must route through `utils.path_exclusion.is_path_excluded` or
  a segment-aware predicate. The repo already owns the canonical matcher —
  `utils/vendor_paths.py:79` is explicitly segment-aware *"so `ours-vendored` is
  not treated as living under `ours`"*, and the distinction is known and simply
  not applied here.
- Extract each whitelist pattern's literal command head and fail on any head
  present in `utils/process_probe.py`'s `_WRAPPERS`. **Zero false positives by
  construction** — a set intersection between two in-repo literal lists — and it
  fails today on exactly one entry.
- Extend `audit_error_hiding.py` with `over-broad-exclusion` (an entry matching
  more than one finding must be split, forcing a written reason per site) and
  `ambiguous-exclusion-file` (a `file` suffix matching more than one file in the
  tree must be lengthened). Both read data the audit already holds.

**False positives**: rule 1 needs a short allowlist for genuine substring intents
(`.env.example`), which is itself an honest record. Rules 2 and 3 are near-zero:
F-EXPT notes the error-hiding rules must scope to `function`-keyed entries, since
shell-script `lines`-keyed entries legitimately list several line numbers, and
that the burn-down is **bounded and one-off** (26 findings, then quiet). Two
companion rules are reported by F-EXPT **as noisy and recommended against**:
"every whitelist entry must cite a rationale comment" (fires on ~20 of 34
entries), and "fail when a suppression file exempts >90% of findings" (fires on
all three QA gates here, two of which are fine). D-RULE's suppression-token rule
is also noisy — 3-6 hits across `handlers/**` of which 1 is a true positive today
— and is worth having only if `pipe_blocker`'s `^`-anchored entries,
command-head allowlists and path exemptions are excluded by construction.

The `sort`/`find` half of F-EXPT-1 is explicitly **not mechanically detectable**
and should be a one-off review of the list against its own stated rationale.

**Buildable now.**

**Severity: HIGH**, driven by F-EXPT-2's client-facing half: a shipped,
un-overridable, project-specific substring list that silently disables security
scanning in trees that never opted in.

---

### 9. `daemon-as-reader-skips-the-protected-set`

**The class**: the daemon obtains file CONTENT from an input-derived path —
directly or through a subprocess — and something derived from that content
reaches an output (a deny reason, a log line, a report file, or merely an
observable boolean verdict), and the module never consults
`path_is_protected` / `resolve_configured_patterns`.

D-SEC's framing is the load-bearing insight and I keep it verbatim in spirit:
the boundary is drawn at BEHAVIOUR, not purpose. **Every member is itself a
security guard**, and each was skipped by the audit that closed the sibling
seams precisely because it was classified as a guard rather than as a reader.
`secret_file_guard` is not bypassed here — it is *not on the path*, because
`git commit -m "wip"` names no path at all.

**Instances**:

- **D-SEC-1 (highest in that report)** — `sensitive_content.py:884`. The only two
  path exclusions on the staged-content surface are configured `exclude_paths`
  and the secret word list itself; `secret_file_matching` is not imported by the
  module at all. With a protected file in the index — reached by `git add -A`,
  which names no file so `R-SECRET-BASH-MENTION` never fires — a plain
  `git commit -m "wip"` runs `git diff --cached` over it, materialises its added
  lines into a handler instance that lives for the whole daemon process, and, if
  any configured `public_pattern` matches, emits `Matched: <bytes>` as the deny
  reason. **The guard produces the disclosure, in its own deny message, while
  reporting that it protected something.** The read and the retention are
  unconditional; only the echo needs a matching pattern.
- **D-SEC-2** — `scripts/qa/check_sensitive_content.py:236` reads every tracked
  file; `:307` echoes `match.group(0)`; `:364-367` excludes the config and the
  word list and nothing else. The disclosure goes to stdout *and* into a JSON
  artefact whose own comment says `llm_qa.py` "publishes that artefact for an
  agent to read as fact".
- **F-HYG-3** — `staged_lint_gate.py:236-256` is a commit-time handler that
  already enumerates every staged path and already calls `path_is_protected` on
  each one, and at `:249-250` uses the answer only to `continue`. The value that
  would justify a deny is computed, spent on silence, and discarded. Also class 1.
- **D-SEC-3** — `quote_drift`, already fixed and registered.

**Detector hypothesis**: `scripts/qa/check_protected_path_readers.py`, wired into
`run_all.sh` as a failing check. Over `src/claude_code_hooks_daemon/` and
`scripts/qa/`, flag a module that BOTH obtains content from a non-constant path
(`read_text`, `read_bytes`, `.open(`, an `os.walk`/`rglob` body, or `run_git(…)`
with `diff`/`show`) AND interpolates a content-derived value into an observable,
or returns a content-derived bool to a caller outside the module — and does not
reference `path_is_protected` or `resolve_configured_patterns`.

**False positives**: D-SEC names them concretely and they are real. Modules
reading only fixed daemon-owned state (`utils/goal_ledger.py`, `routines/ledger.py`,
`skill_scan/state.py`, `daemon/metadata.py`) should be dropped by the
non-constant-path requirement, but paths built from `ProjectContext` will *look*
non-constant and need an allowlist of resolver functions.
`issue_report/citation.py:106` reads content but emits only
`len(content.splitlines())` — a true member of arm 1 and not of arm 2, and it
will fire unless arm 2 is narrowed to values derived from the BYTES rather than
from their count. **That narrowing is the main tuning knob.** `install/` and
`remote_docs/` read templates and vendored documents with echoes and are probably
a genuine smaller instance rather than noise — they should be triaged before the
rule is set to BLOCK.

D-SEC's cheaper high-precision variant, worth taking explicitly rather than by
accident: flag only a module that echoes a regex `match.group(...)` or a
diff/file excerpt into an observable with no protected-path reference. That
catches D-SEC-1 and D-SEC-2 with near-zero noise and misses the oracle arm —
a trade that belongs in the category's "what the Defence does not catch".

**Buildable now.** D-SEC-1's fix is one call mirroring `staged_lint_gate.py:249`,
and D-SEC is emphatic about ordering: **the Detector lands first and must go RED
on all instances before any is fixed**, because shipping the one-line fix first
would leave the class unwatched and the register recording that the work was
done.

**One-off recorded here rather than forced into the class**: D-SEC's
handler-ordering fragility. `SENSITIVE_CONTENT` and `SECRET_FILE_GUARD` share
priority 14 (`constants/priority.py:65,71`) and `chain.py:351` breaks the tie
alphabetically, which is the only thing closing the
`gh --body-file <protected path>` route. Correct today, by alphabet. Nothing
states it as an invariant and nothing tests it, while `chain.py:339-347` already
logs duplicate priorities as a determinism warning — so the project tolerates
what this route depends on.

**Severity: HIGH.** Corroborated by D-SEC and F-HYG independently, and the
outcome is a guard emitting protected bytes into the model's context and the
session transcript, which `utils/secret_redaction.py:14-20` records as redacted
by nothing.

---

### 10. `irreversible-publication-surface-inventory`

**The class**: there is no maintained list of what publishes irretractably, so
each guard enumerates its own subset and the gaps are invisible.

**Instances**:

- **D-PUB-1 + F-BYPS-2 (corroborated, two reports, independently)** —
  `_GH_BODY_PATTERN` covers exactly `gh issue|pr comment|create|edit`. Not
  covered: `gh release create --notes`/`--notes-file`, `gh release edit`,
  `gh gist create`, `gh pr review --body`, `gh repo edit --description`. This is
  not shape-fitting: it is verbatim this project's own release procedure at
  `.claude/skills/release/invoke.sh:310-313`. **A reader of the docs is actively
  misled**, which raises it above a bare omission: `get_claude_md()` enumerates
  the covered subcommands and then names the gaps (`gh api`, stdin), so a reader
  reasonably concludes those two are the gaps. `release` is in neither list.
  F-BYPS adds the composition: a release body written by a Bash heredoc is not
  seen by the `Write`/`Edit` branch, and if it is published before it is
  committed the staged-diff scan never runs either — authored unscanned,
  published unscanned, irretractable. Nothing scans `--title` on any surface.
- **D-PUB-5** — `daemon/cli.py:7692-7697` inlines the complete config file, plus
  a 100-line log window, environment variables including `HOSTNAME`, and the
  hostname. All four are in `BUG_REPORTING.md:19-24`'s "Never file" table.
  `issue_filing_gate` matches only `gh issue create` and stands down for
  comments, deliberately — and the reasoning that licenses the stand-down is
  **inverted for this file specifically**: `_scrub_bug_report` has already
  replaced every declared secret term and the project-root and home prefixes, so
  `sensitive_content`'s scan is structurally guaranteed to find nothing. *The
  document most dangerous to publish is the one document the compensating control
  is certain to pass.* The only thing standing against it is a sentence in a
  skill file.
- **F-PRIV-3** — measured proof that the inventory is short: an absolute
  developer home path is published in three issue comments on the public tracker
  (issues #1 and #27), a category none of the three configured `public_patterns`
  matches, on the exact surface `issue_filing_gate.py:41-45` names as its reason
  for standing down.
- **D-PUB-3** — the fail-open on that surface (primary class 4).
- **D-PUB-4** — the bare-name anchor on that surface (primary class 1).

**Detector hypothesis**: **the artefact IS the Detector's input** — a
hand-maintained list of irreversible surfaces, and all three reports converge on
it independently. D-PUB-3 says so explicitly: *"that list is small and is the
same artefact D-PUB-1's detector needs, so the two should share it."* The check
asserts that each listed surface is either matched by the relevant guard's
pattern or carries an explicit recorded exclusion beside it, in the shape
`gh api` already has. F-BYPS's refinement makes it self-updating: ground the
list in the repository's own tracked documentation, scripts and skills, so a new
publishing command cannot enter the release procedure without the Detector
noticing.

For D-PUB-5, a separate and cleaner rule: give `bug-report` output a
generator-written **anti-provenance marker** — the inverse of
`issue_report/provenance.py` — and deny any `gh` publish command whose
`--body-file`/`-F` names a file carrying it. **False positives near zero**,
because the marker is written by the generator rather than inferred, and only
that generator writes it.

**False positives**: the surface-list check is *initially noisy, then quiet* —
read-only invocations (`gh pr view`, `gh run list`) appear throughout the docs and
each needs an exclusion on first sight; seeding the exclusion list with the read
verbs makes it fire only on a genuinely new write verb. F-BYPS reports that
profile as acceptable and notes correctly that a rule noisy *forever* is not.
The naive grep variant (`gh \w+ \w+.*--(notes|body)`) is reported **as noisy and
recommended against** — it fires on dozens of documentation examples,
acceptance-test strings and `get_claude_md()` blocks.

**Buildable now.** The list is a document; the assertions are equality checks
between in-repo constants.

**Severity: HIGH** for this repository, which cuts releases with exactly the
uncovered command; **medium-low likelihood** for a client install that rarely
publishes releases through daemon tooling — but the guard is client-facing, so
the low number is about likelihood, not about whether it should be closed.

---

### 11. `check-enumerates-from-the-registry-it-polices`

**The class**: a check's iteration starts at the DECLARATION rather than at the
BEHAVIOUR, so the failure mode "the behaviour exists and was never declared" is
structurally invisible.

F-DEPL gives the decision rule, and it is the cleanest membership test in the
whole corpus: **ask what a completely empty declaration would do to the check. If
the answer is "pass", it is this class.**

**Instances**:

- **F-DEPL-1** — every test in `tests/unit/install/test_client_owned_assets.py`
  iterates FROM `CLIENT_OWNED_ASSETS` (ten cited call sites). None iterates from
  the deploy sites. Four asset categories reach clients undeclared: three
  **shell** scripts under `.claude/skills/docs-qa/scripts/` (deployed by the same
  function whose sibling output IS declared), ten `.claude/rules/*.md` instruction
  files deployed on daemon start, three `CLAUDE/core/*.core.md`, and
  `CLAUDE/Plan/_planlib.inc.bash`. Meanwhile `CLAUDE/LLM-INSTALL.md:719-723`
  tells the client the manifest is asserted "by a test that fails if the two
  disagree" and that "a new deployed asset therefore cannot reach you
  undocumented". The suite contains `TestManifestDescribesRealFiles` and
  `TestBoundaryIsDocumentedWhereAClientReadsIt`, both pass, and both are true —
  the suite has no name for the untested proposition.
- **Plan 00378's md5-compared-with-itself defect** (`install/agent_assets.py:96-103`)
  — F-DEPL cites it as the confirmed second instance, which is what makes this a
  class rather than an incident.
- The test-suite shape recurs across the corpus and is the reason so many guards
  in classes 1, 6 and 8 went unnoticed: F-BYPS-1 (*"a test suite generated from
  the implementation's own list cannot report an item missing from that list"*),
  F-BYPS-7 (*"the suite measures the list against itself"*), F-EXPT-1 (*"an
  assertion that something is permitted cannot detect that too much is
  permitted"*), F-EXPT-2 (`should_skip` tests assert only the positive
  direction), D-PUB-1 (closed-set assertions over the members the pattern was
  written for).

**Detector hypothesis**: two forms, and only one is buildable cheaply.

- *Concrete (build this)* — `scripts/qa/check_deploy_declarations.py`: parse
  `install/**` for write primitives (`write_text`, `write_bytes`, `copyfile`,
  `copytree`, `copy2`, `chmod`) whose destination is rooted at a
  `project_root`/`daemon_root` parameter, resolve each to a client-relative glob,
  and fail when it is neither covered by `CLIENT_OWNED_ASSETS`, nor under
  `VENDOR_DIR`, nor on an explicit exemption list. This also supplies the
  enumeration F-DEPL-3 (class 6) needs for its complement assertion.
- *Structural (report as hard)* — a rule that reads test modules and flags a
  suite that iterates a declaration constant with no counterpart iterating the
  behaviour. I do not have a credible low-noise formulation and am not going to
  invent one.

**False positives**: F-DEPL reports the concrete rule **as noisy on purpose** and
the estimate is sobering: roughly 20-30 sites on a first run of which 4-6 are
real. Three named sources — seed-once assets that are genuinely the client's
after creation (`_TEMPLATE_.md`, the project-handler examples), backup/snapshot
writes (`rollback.sh`, `_free_backup_path`), and `resolve_relay_binary_path`'s
config-derived destination which cannot be resolved statically. **It is worth
shipping only if the exemption list is seeded in the same commit** — and that
exemption list is itself an exemption-accumulation surface, i.e. class 8's
problem, which should be written into the category rather than discovered later.

**Buildable now** (the concrete form, with the seeded exemption list).

**Severity: MEDIUM-HIGH.** F-DEPL nominates this as the class that generalises
best beyond its own check, and it has a confirmed second instance in a different
subsystem. It ranks below classes 1-10 only because its Detector is the noisiest
of the buildable ones.

---

### 12. `write-time-guard-with-no-batch-equivalent`

**The class**: a guard judges an artefact at the moment it is created, the
artefact is retained afterwards by something the guard does not re-read, and
the guard's clean verdict does not say so.

The project already articulated this class and applied it once:
`scripts/qa/check_git_history.py:21-24` says *"every write-time rule needs a
batch equivalent, or everything predating the rule is permanently unexamined"*.
That reasoning produced a batch sweep for the five git-metadata surfaces. Of the
seven surfaces, blob **content** and historical **paths** were assigned to
`check_sensitive_content.py`, which scans `git ls-files` — HEAD only. **The batch
equivalent for content was never built, and the docstring's own table reads as
though it was.**

**Instances**:

- **F-PRIV-1** — 16 distinct values matching the project's own `session-uuid`
  public pattern, across 51 blob revisions in 34 non-excluded paths, all
  reachable from published refs on a confirmed-public repository. 27 of those
  revisions were first published AFTER the configured `history_baseline`. The
  window is precisely dated and closed for the future, not the past: between the
  commit that made git *metadata* a checked surface and the commit that made
  *staged content* one, a file written by Bash reached disk unexamined and the
  commit was judged on its message only. The clean-up commits are the sharpest
  evidence — a human noticed both leaks within hours and fixed the tree, and the
  suite was green before, during and after.
- **F-PRIV-2** — 44 blob revisions across 9 non-excluded paths, in the project's
  own authored voice. Same class, different remediation calculus: the config's
  stated reason for tolerating the baseline is that it covers "exactly one known
  finding … one word in one message body". F-PRIV verified that claim directly
  and it is **accurate for commit messages and understates the tolerance by two
  orders of magnitude for blobs**.
- **F-HYG-2** — `secret_file_hygiene_checker.py:133-142` builds its universe from
  three `git ls-files` calls, all present-tense. A protected-glob `.example`
  sibling was committed in `b317c854` and untracked in `6cc845d1`; it is absent
  from HEAD and from disk, and reachable in history in every clone for ever. The
  checker reports nothing, correctly for the question it asks and wrongly for the
  question the check stands in for. **The remedy is the sharp edge**: its own
  printed `git rm --cached` moves the path from tracked to ignored and buys
  silence. Also class 5.
- **F-HYG-1** — the ignore list and the protect list drift (primary class 1);
  it belongs here too, because widening the dynamic set can never widen the
  hardcoded one and nothing sweeps for the difference.

**Detector hypothesis**: `scripts/qa/check_git_blobs.py`, a peer of the existing
two in `run_all.sh`. Stream `git cat-file --batch-all-objects --batch`, skip
binaries, apply the same compiled `public_patterns` and secret-term matcher the
other two already share, then subtract (a) blobs currently in HEAD whose path is
in `exclude_paths` and (b) blobs under a declared blob baseline, using the same
fail-safe as `grandfathered_commits` — an unresolvable baseline exempts nothing.
Report locator = short blob sha plus every path it was ever stored under, never
the matched text. F-HYG's variant for the path half
(`git log --all --full-history --diff-filter=A --name-only` piped through
`resolve_configured_patterns()`) was **verified working during that review** —
it is what surfaced `b317c854`.

**False positives**: F-PRIV measured them rather than estimating, which makes
this the best-evidenced Detector proposal in the corpus.

- *Self-referential rule text* — the file that DEFINES the patterns necessarily
  contains them. Of 149 `vhosts-path` blob hits, **every single one** resolved to
  three files already in `exclude_paths`. A path-aware subtraction takes that
  pattern from 149 findings to **zero**; a Detector without it fires 149 times on
  its own rulebook and is switched off in a day.
- *Exclusion drift over time* — `exclude_paths` describes HEAD, so the
  subtraction must consider every path a blob was ever stored under.
- *Unbounded first run* — 143 profanity, 149 vhosts-path and 54 session-uuid hits
  before subtraction. **The blob baseline is not optional polish**; it is what
  makes the gate survivable, per `check_git_history.py:246-256`'s own argument
  that a gate red on the day it lands gets disabled rather than fixed.
- *Runtime* — 18,025 blobs is tractable today and grows with history, while
  `run_all.sh` is run often.

**Detector buildable now. REMEDIATION OWNER-GATED**, and this is a genuine
human decision rather than a technical one: removing the residue needs a second
`git filter-repo` pass over 3,818 commits and a force-push, against one word
class and 16 identifiers whose sessions are long dead. F-PRIV is careful and
right that the finding is **not that the trade is wrong — it is that the trade
is currently being made silently, because no gate states what is being
tolerated.** Building the Detector with a declared baseline makes the trade
explicit without requiring the force-push, which is why the Detector is
buildable ahead of the decision.

**Severity: MEDIUM-HIGH.** The disclosed material is low-value (dead session
identifiers, and the project's own register of prose). The class is what matters,
and it is corroborated by F-PRIV and F-HYG independently.

---

### 13. `executable-content-outside-the-lock`

**The class**: code that executes during provisioning, in CI, or in the dev
toolchain, whose version is not fixed by the artefact the project treats as
authoritative for provisioning.

D-DEP's boundary is precise and needs no judgement: *is there a package whose
code runs on install, whose version is not fixed by `uv.lock`?* Build-system
requires, `setup.py`, `uv` itself and pre-commit's remote hook repos qualify;
ordinary runtime dependencies do not.

**Instances**:

- **D-DEP-02** — `[build-system] requires = ["setuptools>=61.0", "wheel"]`,
  in neither `uv.lock` nor the venv, resolved fresh from PyPI at every
  `uv sync --frozen` including every client install. setuptools' backend runs
  arbitrary Python at build time by design, and `uv lock --check` reads only
  `[project.dependencies]`, so the freshness gate is structurally blind and
  reports green. Also class 3.
- **D-DEP-04** — `scripts/install/venv.sh:891` `uv pip install -e`, which reads
  no lockfile and resolves `pyproject.toml`'s floors against PyPI. Latent: the
  function has no caller. Kept live by two things — the install README documents
  it in the supported-helper table, and a completed plan accepted it on the
  narrower grounds that it provisions no QA tools, which is true and answers a
  different question than the one that matters.
- **D-DEP-07** — `.pre-commit-config.yaml:22-23` pins the one remaining remote
  hook repo to a mutable **tag**. Retagging upstream gives code execution on
  developer machines at commit time, and `--frozen` does not reach it because
  pre-commit resolves its own hook repos. The irony is local: the file's own
  20-line header is an essay about deleting second version sources, written
  after mirror pins drifted, and it does not mention this one.
- **D-DEP-06** — `pyright==1.1.413` pins a *downloader*, not an analyser: the
  wrapper runs `npm install` at first use and invokes `nodeenv` to download node
  binaries when none is on `PATH`, with no hash in `uv.lock`. It also honours
  `PYRIGHT_PYTHON_FORCE_VERSION`, so the version the pin appears to fix is
  overridable from the environment.
- **F-CVE-2** — the performed advisory scan, and it is a genuinely reassuring
  result on the surface that matters: **0 of the 18 packages in the runtime
  closure carry any advisory**, and client installs receive the runtime closure
  only (no `--all-extras` on any `uv sync` path). 7 dev-only packages carry
  advisories; three of them are unreachable because their only parent is the
  never-executed `safety`. The `nltk` count was verified at the individual-advisory
  level rather than reported raw, and is substantially one defect class filed
  many times.

**Detector hypothesis**: one Detector per route, and D-DEP rates them honestly
rather than uniformly — which is the useful part.

- *Build backend* — every `[build-system].requires` entry must use `==` and
  appear in `uv.lock`. Near-zero false positives on this repository (one block,
  two entries); the real cost is a bump treadmill, so the cheaper variant is to
  require an upper bound, which caps the blast radius without one.
- *Pre-commit* — every non-`local`/`meta` repo's `rev` must match
  `^[0-9a-f]{40}$`. **Six lines, essentially no false positives.** The cost is
  ergonomic: `pre-commit autoupdate` rewrites SHAs back to tags, so the rule
  fires after every autoupdate and needs a documented re-pin step written down
  beside it, or it is the kind of friction that gets a rule disabled.
- *Unlocked install paths* — grep `scripts/` and `install.py` for
  `pip install`/`uv pip install` outside a documented escape hatch. **Reported as
  noisy for its yield**: three known exemptions (the loud documented
  `HOOKS_DAEMON_ALLOW_UNLOCKED_VENV` branch and two instructional strings that
  print advice rather than running it) for one live catch. Land as a warn.
- *Optional-import degradation* — `try: import X / except ImportError:` in `src/`
  where `X` is non-optional in `[project.dependencies]`. **D-DEP calls this the
  cleanest Detector in its report**: small, precise, enumerable false positives,
  fires exactly twice on the current tree and both are true. (That rule's
  instances are D-DEP-08, whose primary class is 4.)
- *Advisory scan* — read `uv.lock`, query OSV.dev's batch API for every pin, and
  **fail only on the runtime closure**; report dev-only hits as warnings. The
  runtime/dev split is the load-bearing design choice: it is computable from the
  lock and it makes red mean "clients are exposed" rather than "some dev tool has
  a CVE". A gate failing on all 88 of today's IDs would be red on arrival and
  suppressed.
- *Wrapper distributions* (D-DEP-06) — **D-DEP reports its own proposal as a weak
  rule and I keep that judgement**: "wrapper that downloads a payload" has no
  reliable static signature, so it degrades to a curated list that rots. The
  honest fix is a note beside the pin saying what the pin does not cover. The one
  mechanical piece worth taking: assert `PYRIGHT_PYTHON_FORCE_VERSION` is unset
  before invoking.

**Operational hazards for the advisory Detector**, stated by F-CVE and worth
carrying into the category: it introduces a **network dependency in a QA gate**,
so an offline run must report *unavailable*, never *clean* — the pattern to
follow already exists at `scripts/qa/run_dependency_check.sh:82-96`. It can also
go red with no commit, which is its purpose but makes it unusual among checks
that are all functions of the tree. And reachability is not computable from a
lock, so some triage burden is irreducible.

**Buildable now.**

**Severity: MEDIUM.** The runtime closure is clean, client installs receive only
it, and most of the exposure is dev and CI machines. The class matters because
`--frozen` is asserted as authoritative and is not, in four distinct ways.

---

### 14. `fetch-then-execute-unpinned`

**The class**: a fetch whose response is executed, where the destination is not
fully determined by the shipped code, the bytes are not verified against a
digest carried independently of them, and the scheme is not forced.

D-NET gives three membership questions and a "no" to any one puts a
fetch-then-execute in the class.

**Instances**:

- **D-NET N5** — `scripts/upgrade.sh:178-205,250-251` downloads
  `$HOOKS_DAEMON_UPGRADE_BASE_URL/$HOOKS_DAEMON_UPGRADE_REF/scripts/lib/python_discovery.sh`
  and sources it. Three weaknesses stack: the base URL has **no validation
  whatsoever** (setting it to `http://` produces a plaintext fetch of a script
  that is then sourced), the ref defaults to the moving `main`, and there is no
  digest. Every Python fetch in this project enforces https; this shell path,
  with strictly worse consequences, enforces nothing. The floating ref is the
  part worth raising regardless of attacker model: an upgrade of a *pinned*
  release can source a script from an unreviewed branch tip.
- **D-NET N7** — `install.sh:100-104` pipes a third-party installer into `sh`
  with **both streams discarded**. This is the exact construct
  `R-CURL-PIPE-SHELL` denies agents, and the `2>/dev/null` is the exact construct
  `error_hiding_blocker` denies in authored shell — two of the project's own
  enforced rules broken by four tokens on one line. Mitigated by being a legacy
  fallback branch, and sharpened by the fact that the surrounding code was
  revised for exactly this concern one call later, explaining at length why only
  stdout is suppressed on a pre-warm — on the line above a remote code download
  that discards both.
- **D-NET N8** — `scripts/upgrade.sh:305-308` sets `protocol.file.allow=always`,
  re-enabling what the CVE-2022-39253 fix disabled, on the command that produces
  **the installed daemon**, with an env-overridable URL that has no scheme check.
  D-NET is careful about the limit: this clone has no `--recurse-submodules`, so
  the specific CVE chain is not directly reachable. The finding is the weakening
  itself and its placement — a flag that exists to make local-path test fixtures
  work, set unconditionally on the production install path where it buys nothing.
- **D-NET N1's relay arm** — see class 16; the digest is fetched over the channel
  it is meant to protect.
- **F-BYPS-6's respellings** — see class 6.

**Detector hypothesis**: three rules over `*.sh`, `*.py` and CI config, and
D-NET rates the third as the cheapest in its whole report.

- Any `curl`/`wget` whose output path is later an argument to `.`, `source`,
  `bash`, `sh` or `eval`, or which is piped directly into a shell.
- Any URL built from a `${VAR:-…}` expansion where `VAR` is not scheme-validated
  before use.
- **A literal grep for a small list of known security-downgrade flags** —
  `protocol.*.allow=always`, `GIT_ALLOW_PROTOCOL`, `--no-verify`,
  `PYTHONHTTPSVERIFY=0`, `verify=False`, `-k`/`--insecure` — outside test
  directories. D-NET: *"the cheapest rule in this report and I would ship it
  first."*

Plus a narrow companion: flag `2>/dev/null` or `&>/dev/null` on any line
containing `curl`/`wget`/`git clone`.

**False positives**: documentation comments containing the install one-liner —
this repo has several (`install.sh:6`, `scripts/upgrade.sh:6`) — which are text,
not commands, and need a comment-stripping pass. With that, the rule is quiet:
D-NET counts 2 real hits in the tree. The downgrade-flag rule is near-zero in
source; its only real noise is comments explaining the flag, removed by the same
comment strip.

**Buildable now.**

**Severity: MEDIUM.** High on mechanism, medium on severity for N5 (exploiting
the env arm needs an attacker who already influences the environment of an
upgrade run), and **low on N7** which is unreachable on any current install.
D-NET reports N7 anyway and is right to: *"a dead branch is still a shipped
branch, and it contradicts two of the project's own enforced rules — which makes
it a credibility problem as much as a security one."*

---

### 15. `unbounded-work-on-input-the-project-does-not-size`

**The class**: work whose cost is a function of input the project does not
bound, with no timeout, no size cap and no deny-on-exhaustion.

**Instances**:

- **D-EVAL Finding 3** — `budget_exhaustion_detector.py:489-500` compiles
  config-supplied patterns with `re.IGNORECASE | re.DOTALL` and matches them at
  `:566-569` against the full stringified `tool_response` of *any* completed tool
  call other than the excluded file-content tools — which includes `WebSearch`
  and `WebFetch`, whose bodies come from the open internet. Three things compound:
  no timeout (Python's `re` has none, and a grep for any mitigation across the
  whole project returns nothing but two incidental prose mentions), no size cap on
  this path (unlike the commit-scanning path, which has explicit stand-downs),
  and `DOTALL` set here and nowhere else among the config-pattern sites — which
  is the standard route by which an author's reasonable-looking regex acquires
  super-linear backtracking without the author changing it. The handler is enabled
  by default and `extra_patterns` is the documented way to extend it.
- **D-NET N9** — `remote_docs/fetchers.py:116` and
  `install/relay_deploy.py:276` both `return bytes(response.read())` with no
  size bound. The timeout bounds latency, not volume; a slow-drip large response
  satisfies both. The asymmetry is notable: the `agent-browser` path explicitly
  refuses a truncated read, so the module has clearly thought about response
  integrity, and the raw path has neither a truncation check nor a cap.
- **D-EXEC F5** — two unbounded spawns in `src/`:
  `daemon/background_harvester.py:275` (`ps`, `check=True`, no timeout) and
  `daemon/cli.py:3185` (`gh run list`, no timeout, and this one makes a network
  call). The second is the sharper: the command's whole purpose is to produce an
  exit code the release skill consumes, where `1` deliberately means "could not
  determine" — and a hang produces neither `0` nor `1`, it produces nothing.
- **D-EXEC F6** — five git spawns in `scripts/qa/` outside `run_git`: none
  declines git's optional index lock so each contends with the agent's working
  tree for `.git/index.lock`, two carry no time bound, and
  `check_sensitive_content.py` additionally uses `check=True` so a wedged git
  aborts the QA run with a traceback rather than a verdict. This is documented
  ground — the gate's own docstring states its scope as `src/` only — and D-EXEC
  reports it anyway for a good reason: the exemption's justification named two
  commands and there are now five sites across four files, four of them
  `ls-files`. The claim "none touches the index" still holds today; nothing
  establishes it.

**Detector hypothesis**: widen the existing scanner rather than write a new one.
`tests/integration/test_git_spawns_are_bounded.py` already resolves module-level
string and sequence constants and already has an `_EXEMPT` mechanism requiring a
written reason per entry; it is pointed at `src/claude_code_hooks_daemon` and at
argv beginning with the literal `"git"`. Two widenings: (a) any `subprocess`
spawner call in `src/` lacking a `timeout` keyword; (b) `scripts/` as a second
root with a relaxed rule for it — not "must use `run_git`", which those
standalone files cannot easily import, but "must pass `timeout=` and must set
`GIT_OPTIONAL_LOCKS=0`".

For the regex half, D-EVAL is explicit that **the obvious Detector should be
rejected**: analysing configured patterns for catastrophic backtracking is
undecidable in general and the approximations are famously noisy — a rule firing
on `utils/path_exclusion.py:85`, which is provably linear because the delimiter
is excluded from its own character class, would be suppressed within a week.
**Assert the guard, not the pattern**: maintain a small declared list of
"external haystack" sources (`tool_response`, fetched document text, transcript
content) and require any config-sourced pattern matched against one to pass
through a size-capping helper. The helper does not exist; creating it is the fix
and the Detector is what keeps it in place.

**False positives**: the spawn rule is high precision — D-EXEC counts two real
hits and one legitimate exemption in `src/`, and the exemption
(`install/transport_verify.py:135`, a `Popen` bounded by
`communicate(timeout=…)` that kills the child on expiry) is exactly the
"exemption with a reason" the existing mechanism handles. The `GIT_OPTIONAL_LOCKS`
half would fire on a spawn setting the variable via a helper, which none do.
The haystack rule has low expected volume — about eight config-pattern sites in
the whole tree — so its output is a reviewable inventory rather than a stream;
its false positive is a config-sourced pattern matched against something that
merely looks external but is bounded upstream.

**Buildable now.**

**Severity: MEDIUM.** D-EVAL is candid that the ReDoS half is a **hazard class
rather than a live defect** (the client writes the pattern, so it is a footgun
rather than an injection) and that the experiment which would settle it —
constructing and timing a backtracking payload — was deliberately not run, as
adversary-side mechanics outside a read-only reviewer's remit. The mitigation is
worth having regardless of how that experiment comes out, which is why it is
reported now rather than held.

---

### 16. `response-trusted-beyond-the-request-validated`

**The class**: a restriction is applied to the request a caller made, and the
RESPONSE is then trusted as though it corresponded to it.

D-NET proposes framing N1 and N3 together under this name and I take that
framing, adding two.

**Instances**:

- **D-NET N1** — `remote_docs/fetchers.py:98-116` and
  `install/relay_deploy.py:272-276` both check `parsed.scheme != "https"` once,
  on the URL the caller named, and then call `urlopen`, whose default opener
  installs an `HTTPRedirectHandler` permitting a redirect to `http`, `https` or
  `ftp`. Two outcomes: a vendored document records a lie (`source_url:` is the
  URL *requested*, while the body arrived over plaintext, and the document is
  then marked `fidelity: verbatim`, which the project defines as "the stored
  bytes ARE the response body"); and on the relay path this reaches code
  execution, because `SHA256SUMS` and the binary are fetched by the same
  `fetch_fn` from the same base URL, so a redirect capturing both makes the
  digest check compare the attacker's manifest against the attacker's binary.
  The comment claiming "the digest is ALWAYS verified before anything is written
  to disk" is **true and insufficient**: the digest travels the channel it is
  meant to protect, so it attests to corruption-in-transit, not authenticity.
- **D-NET N3** — the forged frontmatter (primary class 7), listed here because
  its *consequence* is this class: the daemon trusts a `source_url` it recorded
  from a response, and `find_document` then matches on it, so a forged value
  makes `remote_docs_routing` deny a WebFetch of the genuine URL and print
  "ALREADY VENDORED — READ THE LOCAL COPY" with the forged local path.
- **D-NET N6** — every git checkout within depth 4 of `untracked/` is contacted
  at SessionStart (`git fetch --all`, i.e. *every remote it has*) and
  fast-forwarded onto disk, on by default, with discovery's only test being the
  presence of `.git` and no remote allowlist anywhere in the package. Then
  `R-REFERENCE-REPO-STALE` **denies a read of a clone that is behind** — so the
  daemon pulls third-party content and enforces that the agent reads the freshest
  version of it. Compare the treatment of the other subsystem that vendors
  third-party text: remote-docs demands provenance, records fidelity and licence,
  tracks staleness, and prints "this is a vendored copy, not upstream itself" on
  Read. A reference clone gets none of that and is indistinguishable in context
  from the project's own files.
- **F-DEPL-6** — the same-origin digest and the never-re-read verification
  (primary class 3).

**Detector hypothesis**: flag any `urlopen` / `requests.get` / `httpx.get` in
`src/` not preceded in the same function by an opener with a redirect handler,
`allow_redirects=False`, or `follow_redirects=False`. For urllib the positive
signal is `build_opener(...)`; its absence is the finding. **Expected volume is 2
today, so the rule is cheap and quiet.** Pair with the size-cap rule from class
15 and, for N6, D-NET's *narrower mechanical form*.

**False positives**: a fetch of a hardcoded-literal URL with no attacker
influence — and D-NET argues this is arguably still worth flagging, since the
relay download IS a hardcoded literal and is still the worst case here because
of what it does with the bytes. Vendored third-party code is already skipped by
the standard `exclude_paths`.

**The N6 rule needs care and D-NET says so**: the doc-reading form ("any config
field defaulting to `True` whose docstring describes network access or a
filesystem mutation, with no sibling field constraining the endpoint set") is
reported as **too noisy to enforce as written** — many default-on booleans
mention "fetch" or "check" harmlessly and `enabled: True` on an advisory handler
would trip it constantly. The enforceable form is mechanical: flag a call to
`fetch_all`/`pull_ff_only` whose `cwd` is not the project root, and require that
call site to name its source policy. **One hit today.**

**Buildable now.**

**Severity: MEDIUM.** High on N1's mechanism (CPython's redirect behaviour is
documented, not inferred) and medium on the relay scenario's reachability, since
it needs the opt-in `relay_source: download` plus control of a redirect from a
github.com URL. N6 is the one where D-NET is least certain it is a defect at
all, and is careful about why: the plan that introduced it argued explicitly for
`enabled: True`, so shipping on was a considered decision — but **the
remote-trust question was not considered anywhere findable, and that gap in the
reasoning is the finding**. Also class 18.

---

### 17. `authored-or-argument-path-resolved-without-containment`

**The class**: a path from a document, a config value or a CLI argument is
resolved and then DEREFERENCED — read, written, globbed, iterated — with no test
that the result is still inside the tree the operation is scoped to.

This is the **containment half** of the completed `authored-path-resolution`
category, which the register's own "the rule forces the chokepoint; it does not
choose the helper" bullet names as outside what the current Detector grades.

**Instances**:

- **D-PATH Finding 4** — `plan_qa/checks/path_existence.py`. The span pattern's
  character class contains `.` and `/`, so `..` is a well-formed span; executed,
  `src/../../../etc/hostname` matches, normalises to `/etc/hostname` and returns
  `exists=True`. An inline-code span in a `PLAN.md` becomes a one-bit existence
  probe against any host path, with the answer returned in a finding the agent
  reads, registered at both EDIT and SWEEP. The *guard prefix* (`src/`, `tests/`,
  `config/`) reads like a containment check while constraining only the first
  segment. `docs_qa/checks/pointer_resolves.py:95-100` is the same shape. I
  verified both still call the normalising helper rather than the containing one.
- **D-NET N4** — `daemon/cli.py:6354-6355`. `--path` becomes a `Path` with no
  containment test against the tree; `refresh_document` then reads that file,
  takes its recorded `source_url`, fetches it, and writes the response back over
  the same path. Any markdown file anywhere on the filesystem carrying a
  parseable provenance block is a refresh target. `--all` is safe. **The
  project already has the right code, in the handler and not on the write
  path**: `remote_docs_routing._read_target` does exactly this check.
- **D-PATH Finding 2** — the tilde gap (primary class 1) is the same failure
  reached by a different route.

**Detector hypothesis**: extend the existing chokepoint rather than write a new
one, and put the containment assertion **inside the helper** — that is the
argument for the helper over per-call-site checks: `authored_path_exists` is
already the single funnel for the stat half, so one change covers
`path_existence.py`, `pointer_resolves.py` and `plan_qa/model.py` at once. Then
widen `_SCOPED_TREES` to reach `daemon/cli.py`'s argument-to-write path, or add
a companion rule: a `cmd_*` CLI function converting `args.<name>` to `Path` and
reaching a write with no intervening `relative_to`/`is_relative_to` check.

**False positives**: D-PATH names the honest ones and they are substantial. The
**corpus walkers** — 12 of the 31 sites it measured — join `project_root / rel_path`
where `rel_path` is a key the daemon itself produced by walking the tree;
containment is guaranteed by construction and the rule cannot see that. Routing
them through the helper costs one `resolve()` each and keeps the rule a
chokepoint, but a reviewer reads them as noise unless the helper's docstring says
why they are included. A **legitimately out-of-repo pointer** is the other:
`../sibling-package/README.md` is a real, correct link in a monorepo or worktree
layout, and `core/worktree_paths.py` already re-roots worktree paths — a
containment rule that does not consult it fires on every cross-worktree pointer.
For the CLI rule, commands whose entire purpose is to write where the user says
(`issue-report --output`, `--project-root`) need an allowlist D-NET estimates at
5-10 entries: maintainable, but real ongoing cost, and it reports the rule as
**moderately noisy**.

**Detector buildable now. The DESIGN QUESTION is OWNER-GATED**, and D-PATH is
explicit that a reviewer should not settle it: **is escaping the root a "does not
exist" answer, or an error?** Returning False silently makes an escaped link
report as dead — the exact wrong-message failure the registered category exists
to stop. Raising makes a docs check crash on a hostile document. A third
`Finding` ("this pointer leaves the repository") is probably right, and it is a
policy decision. That choice changes messages agents see in installing projects,
which is why it is gated.

**Severity: MEDIUM.** D-PATH rates Finding 4's severity as medium and states the
dependency honestly: a one-bit existence oracle delivered through an `ADVISE`
message is low harm, and that judgement changes if plan-QA sweep output ever
reaches anywhere outside the session. N4's severity is bounded by the operator
being the one naming the path — a footgun and a privilege-boundary gap rather
than something a remote party triggers alone.

---

### 18. `tri-state-default-favours-capability`

**The class**: a three-state gate maps "unset" onto the same branch as "enabled"
for an action that increases reach, rather than onto "disabled" or an advisory.

F-DEPL's membership question is the right one: *if the client had read the
config reference and deliberately chosen, would the absent-key behaviour match
the choice most of them would make?*

**Instances**:

- **F-DEPL-5** — `install/ccy_supervisor.py:155-178`. Only an **explicit**
  `false` opts out. With the key absent — the state of any client who has never
  heard of the feature — the presence of a `.claude/ccy/` directory is sufficient
  for the daemon to install a 0755 Python program and wire it as the wrapper
  around every subsequent `claude` launch, **in armed mode**, where armed means
  injecting a real `/compact` and a `continue` prompt into the user's interactive
  session. A component whose capability is *writing input into the user's agent
  session*, defaulting on by absence of configuration. The single gate is the
  existence of a directory, which is weaker than consent — it may exist because a
  teammate committed it. The arming logic is careful about a client who *has* a
  stance and treats silence as assent.
- **D-NET N6** — `config/models.py:1965,1978-1981`: `enabled` and `auto_pull`
  both default `True` for reference repos (also class 16).
- **D-DEP-08** — `strict_mode` defaults to `False`, which is what turns a failed
  `jsonschema` import into silent degradation rather than a refusal to run (also
  class 4).
- **F-BYPS-3** — degraded mode maps "could not validate" onto "allow everything"
  (also classes 2 and 4).

**Detector hypothesis**: over `config/models.py`, find `bool | None` option fields
and assert that each one's *consuming* code maps `None` to the lower-capability
branch, with a declared exception list.

**False positives**: **F-DEPL reports the general form as high-noise and
recommends against it, and I keep that judgement.** Plenty of tri-states
legitimately mean "not yet decided, behave as before", and several of this
project's `None` defaults are inert. *"As a general rule over all tri-states, I
expect it to be suppressed within a week, and I would rather say so than ship it
as clean."* The targeted variant is the one worth building: restrict it to
options that gate a **write or an exec into client space**, which fires on
roughly three sites.

**Detector buildable now** (targeted form). **The DEFAULT FLIP is OWNER-GATED**,
squarely: changing "absent means armed" to "absent means advise" changes
behaviour for every installing project that never set the key, which is exactly
the population the finding is about.

**Severity: MEDIUM**, and F-DEPL is careful to label F-DEPL-5 **a judgement call,
not a defect** — the default is deliberate, documented, and backed by its own
integrity handler. It reports it anyway on the grounds that *"documented and
deliberate is exactly how an over-broad default survives review"*, and that is
the right reason to keep it on the list. A maintainer ruling settles it.

---

## Findings that fit no class

A one-off is a legitimate outcome and these are recorded rather than forced.

1. **Handler-priority tie decided by alphabet** (D-SEC). `SENSITIVE_CONTENT` and
   `SECRET_FILE_GUARD` share priority 14 and `chain.py:351` breaks the tie with
   a name sort, which is the only thing closing the
   `gh --body-file <protected path>` route. Nothing states it as an invariant,
   nothing tests it, and `chain.py:339-347` already logs duplicate priorities as
   a determinism warning. A cheap targeted assertion, not a class.
2. **`pipe_blocker` false POSITIVE** (F-BYPS). A `grep` whose PATTERN contains
   `<(` is misparsed, the producer is reported as `"`, and a read-only command is
   denied. The opposite of a bypass and therefore out of scope for every check
   that found it; recorded so the observation is not lost.
3. **`EXIT_CODE=$?` captures the `if`, not the `eval`** (D-EXEC,
   `scripts/run-qa-runner.sh:84,89`), so the "exit code: N" messages are wrong.
   Flagged as incidental by its own reporter and explicitly not part of D-EXEC.
4. **`a1_coverage.pth` executes at every interpreter start** in the QA venv,
   including every daemon start in this self-install checkout, running `exec()`
   on an embedded string containing a bare `except: pass` (D-DEP). Deliberately
   below the reporting bar: upstream coverage.py's standard mechanism, dev-only,
   gated on an environment variable, and the project has no lever over it.
   Recorded because it is a concrete instance of the entry-point shape and the
   next reviewer should not have to rediscover it.
5. **`untracked/rejected-writes/` captures denied writes in full** (F-HYG),
   written by `.claude/ccy/claude-supervise.py`, which sits outside the daemon's
   redaction chain. Low priority while the directory stays under `untracked/`;
   adjacent to class 9 but not a member, since the writer is not the daemon.
6. **`.claude/worktrees-archive/` is not ignored and does not exist** (F-HYG) —
   checked, explained, not a finding. Recorded so it is not re-derived.

---

## Where the reports contradict each other

Two real contradictions, both of the same shape: a reviewer declared an axis
clean that another reviewer found holes in, because the two scoped the axis
differently. Both matter because a clean-axis statement is the kind of sentence
that gets cited later as coverage.

1. **"Outward publication is covered" (F-GAP) vs D-PUB and F-BYPS.** F-GAP's
   clean-axes section states that `sensitive_content` scans the `gh` body
   surfaces, that the one acknowledged hole is stdin, and that it *"found nothing
   to add on this axis"*. D-PUB filed five findings on that axis and F-BYPS filed
   one, including — independently of each other — that `gh release create` is
   entirely outside the scan surface and is this project's own documented release
   command. **Resolution**: F-GAP's verdict is true of the `gh issue|pr` shapes it
   probed and false as a statement about outward publication; it did not test
   `release`. The conclusion is not that F-GAP was careless — it is that its
   clean wording is broader than its evidence, which is exactly the failure mode
   F-PRIV names in class 5 and which the F-GAP report elsewhere guards against
   carefully.
2. **"Protected-file reading is genuinely well covered" (F-GAP) vs D-SEC.**
   F-GAP judges `secret_file_guard` the most complete guard in the set and says
   the *glob list* needs extending while the *guard* does not. D-SEC found three
   routes by which the daemon itself reads protected content without any tool
   call naming the path. **Resolution**: these are not strictly incompatible —
   F-GAP judged a request-shape guard and D-SEC judged the daemon as a reader,
   and F-GAP explicitly bounds its claim to what the guard claims. But a reader
   of F-GAP alone would conclude the axis is closed, and it is not.

Two lesser tensions, recorded so they are not mistaken for contradictions:

3. **Relay severity.** D-NET rates the relay download path High on mechanism;
   F-DEPL rates the same artefact low-medium on materiality. Both note
   `relay_source` defaults to null. Reconciled: mechanism high, materiality low
   until a client opts in — and neither reviewer could establish how many have,
   since that is a client-side fact.
4. **Config discipline.** F-EXPT finds this repository's own configuration
   unusually disciplined; F-GAP finds nothing guards the configuration at all.
   Complementary rather than contradictory, and F-EXPT says so: *"G9 is upstream
   of F-EXPT — that check counts the entries; this asks why anything stops one
   being added."*

---

## The cross-cutting candidate: "the project asserts a control it does not have"

Several reviewers named this independently, in almost identical words. **It is
real, and it is not one class.** A Detector for it must match something concrete,
and what a program would have to READ differs so much between members that a
single rule cannot find them. My assessment is that it is **three detectable
classes plus one that should not be automated**, and that splitting it this way
is what makes it buildable at all.

**The members, first**, so the split can be judged against them: docs claiming
`rm -rf` is blocked (F-GAP G1); four guards' deny text claiming "NO escape
hatch" (F-BYPS-4); `LLM-INSTALL.md` claiming a two-way test that runs one way
(F-DEPL-1); `safety` in the manifest implying a dependency scan (D-DEP-05,
F-CVE-1); a handler's guidance stating an exemption semantically while the code
states it lexically (D-RULE-1); `get_claude_md()` enumerating covered `gh`
subcommands and its own gaps, with `release` in neither (D-PUB-1); a Detector
docstring saying "always" where the rule is narrower (D-PATH-3, now recorded in
the register); `.sha256` reporting "verified" for a same-origin integrity check
(F-DEPL-6); a green gate that is green because it suppresses 100% of findings
(F-EXPT-3); `# SECURITY: … file path validated` above code that does not
validate the path (D-EXEC F4); `nosec B603 - eslint/npx are trusted tools`
(D-DEP-01); `issue_filing_gate` asserting another module's coverage that does not
hold (F-PRIV-3); a config comment accurate about messages and read as true about
blobs (F-PRIV-2); and an installer breaking two of the project's own enforced
rules on one line (D-NET N7).

**Split 1 — `doc-claims-a-rule-that-has-no-id`. BUILDABLE NOW, ship first.**
Read every "we block X" / "we enforce X" list in tracked documentation and
resolve each named construct to a real rule ID and a handler that denies it.
F-GAP proposes exactly this and rates it high-value and near-zero false positive,
and it is the only member of the cross-cutting group with a genuinely mechanical
referent. It catches G1 — the worst single documentation claim in the corpus,
because `rm -rf` is listed beside two constructs that genuinely are blocked.

**Split 2 — `suppression-comment-asserts-an-unchecked-property`. BUILDABLE NOW,
narrow.** A `nosec`, `# SECURITY:` or equivalent inline suppression that asserts
a safety property must name what makes the property true, in a form that can be
re-checked. Two instances (D-DEP-01, D-EXEC F4) and both are load-bearing: in
each case the comment is the reason the next reader stopped looking. Small
population, enumerable by grep, near-zero noise. Note this is adjacent to the
existing `qa_suppression` handler but not covered by it — that handler's list is
linter directives, not safety assertions.

**Split 3 — `check-enumerates-from-its-own-registry`.** Already class 11.
F-DEPL-1 belongs there rather than here, because its Detector reads *deploy
sites*, not prose.

**Split 4 — `deny-text-asserts-unenforced-absolutes`. NOT WORTH AUTOMATING AS A
GATE, and F-BYPS says so first.** A check over every handler's `get_claude_md()`
and `Rule.verbose` for absolute-enforcement phrasing ("NO escape hatch", "only a
human", "never … by any route", "cannot be disabled"), requiring each to name a
guard or test that would fail if the claim were violated. F-BYPS reports this
**as noisy** and is right: absolute phrasing is the house style in this
codebase's teaching text, and much of it is legitimately about POLICY rather
than mechanism — *"an unblocked evasion is NOT permission"* is a rule, not an
enforcement claim, and would fire. The distinction between a policy statement
and an enforcement claim is a judgement a regex cannot make. It would need a
per-occurrence acknowledgement file, and is worth it only if the owner decides
this drift is recurring rather than a one-off. **Ship it as a report, never as a
gate.**

**What I would NOT do**: write a single `asserts-a-control-it-does-not-have`
category. It would name a Detector that cannot exist, which is precisely the
claim the register's own rules forbid — *"a category with no Defence is a claim
the register cannot make honestly"* — and it would make fourteen findings look
handled by one rule that finds three of them.

**Two observations worth carrying regardless of the split.** First, the
underlying driver is uniform even though the Detectors are not: in every member,
prose and enforcement were written at different times and only the prose was
reviewed as a whole. F-DEPL states it best and it generalises past deployment —
*"this project reasons about deployment ownership extremely well in prose, and
the prose is ahead of the enforcement."* Second, the cost is not primarily
technical. F-BYPS-4 makes the argument that applies to the whole group: an agent
that believes a false absolute will not test it; an agent that tests it will find
the claim false, **and every other claim in those messages loses its authority at
the same moment.** For a guardrail, the text is most of what it has.

---

## Build order

If the worklist is taken in order of value per unit of work rather than by
severity, the first five are: class **5** part 1 (report the denominator — no
false positives, no decision, and it makes every other gate's evidence
readable); the `doc-claims-a-rule-that-has-no-id` split above; class **14**'s
security-downgrade-flag grep; class **1**'s first three pair rows (each a set
comparison between two in-repo literals); and class **9**'s Detector, landed RED
over all three instances before any is fixed.

The two measurements that should precede an owner decision rather than follow
it: **how long the daemon actually takes to judge a large staged commit**
(sizes class 4's relay fail-open, and F-BYPS names it the single most valuable
follow-up in the corpus), and **whether `.claude/skills/docs-qa/` collides with
any real client skill directory** (sizes class 1's F-DEPL-2 row).
