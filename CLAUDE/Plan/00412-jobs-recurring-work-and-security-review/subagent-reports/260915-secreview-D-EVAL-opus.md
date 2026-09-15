# Security review — check `D-EVAL`

**Check**: `D-EVAL` — "New dynamic execution or deserialisation: `eval`, `exec`,
`pickle`, `yaml.load`, a regex assembled from input."
**Run**: Routine 00001, run 2026-001, FULL sweep (current tree, root
`74b0989cf254b24c3c713254b2c0b52ad5d7ed96` → HEAD `5d59f7ff`).
**Scope reviewed**: `src/claude_code_hooks_daemon/`, `scripts/`, `bin/` (673
files matching `*.py`/`*.sh`/`*.bash`).
**Reviewer**: security-reviewer (opus), read-only.

**Findings**: 3 (1 high confidence, 1 high confidence, 1 medium confidence).

This check WAS run. Everything in the "answered clean" section below was
looked at and found clean, as distinct from not looked at.

---

## The shape of the answer

The literal half of this check is clean, and cleanly so — the daemon contains
no `eval`, no `exec` of a string, no `compile()`, no `pickle`/`marshal`/
`shelve`/`dill`, and every YAML read in the repository is `yaml.safe_load`.
The only occurrences of the words `eval`, `exec` and `yaml.load` in the
source tree are *data*: the pattern definitions and deny-message copy of the
`security_antipattern` handler, which matches those constructs in a client's
code. As the brief anticipated, that handler's existence is not coverage of
the daemon's own code, and it is not treated as such below.

The findings are all in the second half — **"a regex assembled from input"**
generalised to its real form in this codebase: *a value from configuration or
another data file that is interpreted as code or as a pattern*. The daemon is
unusually disciplined about the narrow regex case (see "Answered clean"), and
the productive hits are one step out from it: a config *string* that
terminates in `exec_module`.

---

## Finding 1 — `project_handlers.path` reaches `exec_module` with no containment check, by design

**Confidence: high.** Verified by reading every link in the chain; the
behaviour is explicitly documented and explicitly tested, so there is no
ambiguity about what the code does — only about whether it is wanted.

### Citation

The terminal call, `src/claude_code_hooks_daemon/handlers/project_loader.py:177-183`:

```python
spec = importlib.util.spec_from_file_location(module_name, file_path)
...
module = importlib.util.module_from_spec(spec)
sys.modules[module_name] = module
spec.loader.exec_module(module)
```

The path that reaches it, `src/claude_code_hooks_daemon/daemon/controller.py:556-560`:

```python
handlers_path = resolve_repo_relative_path(project_handlers_config.path, workspace_root)
discovery = ProjectHandlerLoader.discover_handlers_with_failures(handlers_path)
```

The resolver, `src/claude_code_hooks_daemon/utils/repo_relative_path.py:194-206`
— *"an already-absolute result — a genuine machine-specific override — is used
as-is"*.

The config field, `src/claude_code_hooks_daemon/config/models.py:460-484`. Its
only validator is `_validate_path_token_placement` (`models.py:475-484`),
whose docstring states the position plainly:

> This field is exempt from repo-relativity, so only token PLACEMENT is
> checked here.

`discover_handlers_with_failures`
(`project_loader.py:325-410`) performs **no** containment, ownership or
provenance check on `project_handlers_path`. It checks `exists()` and
`is_dir()`, then globs `*.py` under each event-name subdirectory and imports
every file that does not start with `_` or `test_`.

### What it concretely allows

A single tracked-file edit executes attacker-chosen Python inside the daemon
process on the next daemon start.

`.claude/hooks-daemon.yaml` is version-controlled in this repository
(`git ls-files` confirms it), as are the eight live handler modules under
`.claude/project-handlers/`. So both of these are ordinary diffs:

1. Add `.claude/project-handlers/pre_tool_use/anything.py`. It is imported and
   its module body runs at daemon start — *before* any `matches()` gate, so
   the module never has to pretend to be a plausible handler; a file whose
   body is a payload and which exports no `Handler` subclass is logged as a
   load failure **after** its body has already executed.
2. Or leave the directory alone and change one line to
   `path: /tmp/x` or `path: ../../x`, pointing the loader outside the
   repository entirely (see Finding 2 for why the relative spelling also
   works).

The daemon is a long-lived process that sees every tool call, holds the
project's configuration, and runs with the developer's full privileges. It is
restarted routinely and often by the agent itself — this project ships a
`daemon_restart_verifier` handler whose entire purpose is to *require* a
restart before committing. So "on the next daemon start" is not a remote
contingency; it is part of the normal commit loop.

The gap that makes this a finding rather than a design note is the asymmetry
with the rest of the project's own stated posture. `project_containment`
denies a *write* to a path outside the repository, on the reasoning (quoted in
`CLAUDE.md`) that *"outside the repo nothing is version-controlled, reviewed or
durable"*. The same repository will `exec_module` a file from exactly such a
path on the strength of one config string, and no guard in the inventory
judges it.

### The class

**A configuration value that is consumed as a location to load and execute
code from, without being constrained to the reviewed tree.**

A member of this class has three properties, all checkable without judgement:

1. the value originates outside the daemon's own source (config file, env var,
   state file, CLI argument);
2. it is used as a path, module name, or import target — not merely read as
   data;
3. nothing between the two constrains it to the repository, or to a set fixed
   at build time.

`PluginConfig.path` is the sibling to check against the same three (it shares
the repo-relative exemption; not examined here because it falls outside this
check's scope as briefed).

### Why the test suite does not catch it

**Because the test suite asserts it.**
`tests/unit/daemon/test_controller_project_handlers.py:156` is
`test_load_project_handlers_uses_absolute_path_as_is`, and `models.py:463-467`
cites that test by name as the justification for the exemption. A test suite
cannot flag as a defect the behaviour it was written to pin. This is the
purest form of "the tests pass and the defect is present": the tests pass
*because* the behaviour is present.

More generally, no unit test can see this class at all. Every link is
individually correct — the resolver resolves, the loader loads, the validator
validates the one thing it claims to. The finding is the *absence* of a check
spanning three modules, and an absent check appears in no test's assertions.

### Detector hypothesis

A `scripts/qa/` detector over `config/models.py`: for every `str` field on a
config model, determine whether its value flows to a code-loading sink
(`spec_from_file_location`, `import_module`, `exec_module`, `__import__`,
`runpy`). Require that each such field either (a) validate through
`normalise_repo_relative_path` — the function that already rejects absolute
and `..` — or (b) carry an explicit, named exemption marker that the detector
reads and reports as a standing inventory line, so the exemption set is
countable rather than discoverable only by reading.

The flow analysis is the hard part and the cheap approximation is better:
**enumerate the code-loading sinks (there are few — the grep above finds
exactly two files) and assert that every path argument reaching one is derived
from a `normalise_repo_relative_path`-validated field.** That is a
whole-repository invariant with a handful of sites, which is the shape this
project's existing Detectors take (cf. `check_authored_path_stat.py`).

**Likely false positives**: the daemon's own internal imports —
`config/validator.py:148,169` calls `importlib.import_module` on a name built
from `f"claude_code_hooks_daemon.handlers.{event_type}"` and on `modname` from
`pkgutil.walk_packages`. Both are daemon-internal and constrained (the prefix
is a literal; `event_type` is validated against `VALID_EVENT_TYPES` upstream),
but a naive sink-grep flags them. The detector needs a
"constant-prefix / package-walk" allowance, and that allowance is itself where
a future defect could hide — worth stating in the category's "what the Defence
does not catch" section rather than leaving implicit.

**Noise estimate**: low. Two sink sites in the whole tree today.

### What would settle the open question

The open question is not *what the code does* — that is settled — but whether
the owner intends the exemption. Specifically: is a project-handlers directory
outside the repository a real supported use case with a real user, or is it an
exemption that was granted because the alternative (rejecting absolute paths)
looked like it might break someone? `models.py:463-467` asserts the former
("may legitimately live outside the repository") but cites only a test, not a
use case. If no real caller needs it, routing this field through
`normalise_repo_relative_path` closes the whole class at the cost of one
config-validation error message.

---

## Finding 2 — `..` escapes the repository on exactly the field where `{REPO_ROOT}/..` is rejected

**Confidence: high.** The asymmetry is visible in six consecutive lines.

### Citation

`src/claude_code_hooks_daemon/utils/repo_relative_path.py:179-191`:

```python
    if value != REPO_ROOT_PLACEHOLDER and not value.startswith(_TOKEN_PREFIX):
        if REPO_ROOT_PLACEHOLDER in value:
            raise ValueError(...)
        return value                               # <-- line 185: no `..` check

    remainder = "" if value == REPO_ROOT_PLACEHOLDER else value[len(_TOKEN_PREFIX):]
    if ".." in PurePosixPath(remainder).parts:     # <-- line 188: `..` checked
        raise ValueError(f"path must not escape the repository, got {value!r}")
```

Then `resolve_repo_relative_path` (`repo_relative_path.py:204-206`) joins the
unchecked value onto the root:

```python
    expanded = Path(expand_repo_root_token(value, project_root))
    if not expanded.is_absolute():
        expanded = project_root / expanded
    return expanded
```

### What it concretely allows

For `project_handlers.path` — and any other field exempt from repo-relativity
that resolves through this function:

- `path: "{REPO_ROOT}/../../evil"` → **rejected** at line 189.
- `path: "../../evil"` → **accepted**, and resolves to
  `<project_root>/../../evil`, which is the same directory.

The two spellings denote the identical location and get opposite verdicts. The
guarded one is the *portable, documented, recommended* spelling that a
careful config author would reach for; the unguarded one is the terse spelling
someone writes without thinking about it. A guard that catches only the
careful phrasing of an escape is a guard that will be walked past by accident
before it is ever walked past on purpose.

Combined with Finding 1, this means the escape does not even require the
absolute-path exemption to be reachable. Anyone who assumed the exemption was
narrow — "absolute paths only, and those are obvious in review" — has a
non-obvious second spelling to account for: `../` in a config value reads as a
relative path, which is what the field is nominally supposed to contain.

Note also that `Path.__truediv__` does not normalise. `project_root / "../../evil"`
retains its `..` components, so the resulting `Path` string does not visibly
announce where it lands; the log line at `project_loader.py:404-408`
("Discovered %d project handlers from %s") prints the unresolved form.

### The class

**A path-validation predicate applied on one branch of a two-branch
normaliser, where both branches produce a filesystem path.**

The test for membership: if a validator has a conditional early return, does
every check that applies after the branch point also apply before it? Any
check on one side only is a member — the sides are two spellings of the same
thing, and the difference in treatment is unmotivated by anything the user can
see.

This is a near relative of the register's existing
[authored path resolution](../../../Security/AuthoredPathResolution.md) category
(`..` handled differently by two code paths that resolve the same authored
string), but distinct: that one is about `..` resolved *through the
filesystem* by a stat predicate, this one is about `..` *never checked at all*
on a branch. Worth deciding deliberately whether it extends that category or
opens a new one; the existing Detector
(`scripts/qa/check_authored_path_stat.py`) does not look at config validators
and would not find this.

### Why the test suite does not catch it

The function's tests exercise the two branches separately and each behaves as
its own docstring says. The docstring for `validate_repo_root_token_placement`
(`repo_relative_path.py:92-96`) even states the gap as intended:

> It does not check repo-relativity or `..` escapes — those remain irrelevant
> for an exempt field and are left to `expand_repo_root_token`'s own escape
> check at expansion time.

But `expand_repo_root_token`'s escape check is on the token branch only, so
for a non-token value the check the docstring defers to does not exist. Each
half is separately documented and separately tested; the claim that fails is
the *composition* of the two docstrings, and no test asserts a composition of
two docstrings. Writing a test that would have caught it requires first
noticing the asymmetry — which is the review's job, not the suite's.

### Detector hypothesis

Within the path-validation modules, assert that any `".." in ...parts` check
is not reachable only from a subset of a function's return paths. Concretely:
flag a function containing both an early `return value` and a later `..`
check on a value derived from the same parameter.

**Likely false positives**: real cases where the early return is genuinely a
different kind of value (an empty string, an already-validated sentinel) and
`..` is meaningless for it. Low volume — this shape is rare — but each hit
needs a human read, so it is a **warn-with-inventory** Detector rather than a
hard fail, unless it is scoped to the two or three modules that own path
validation.

A cheaper and stricter alternative worth considering: assert that
`".." in PurePosixPath(...).parts` appears in `repo_relative_path.py` only in
positions that dominate every `return` in the module. Mechanical, no judgement
call, and this module is small enough that the rule is checkable by
inspection.

**Confidence in the Detector, as opposed to the finding**: medium. The finding
is certain; a general rule for this class is harder to write than for
Finding 1, because "check applied on one branch" is a common and usually
correct shape in ordinary code. Scoping it to path validators is what keeps it
honest.

---

## Finding 3 — config-supplied regexes run unbounded over external text

**Confidence: medium.** The mechanism is certain; the exploitability depends
on a client's own config, which is why it is reported as a hazard class rather
than a live defect.

### Citation

`src/claude_code_hooks_daemon/handlers/post_tool_use/budget_exhaustion_detector.py:489-500`:

```python
    def _resolved_extra_patterns(self) -> list[re.Pattern[str]]:
        if self._compiled_extra_patterns is None:
            compiled: list[re.Pattern[str]] = []
            for raw in self._extra_patterns or []:
                try:
                    compiled.append(re.compile(raw, re.IGNORECASE | re.DOTALL))
```

matched at `budget_exhaustion_detector.py:566-569` against
`_prepared_response_text`, which is the full stringified `tool_response`
(`:538-539`, `_stringify_tool_response` at `:364-378`).

The same shape, differently sourced, at:

- `handlers/pre_tool_use/sensitive_content.py:556` — `public_patterns`,
  matched against file content and staged-diff text.
- `handlers/pre_tool_use/pipe_blocker.py:62` — `extra_whitelist` /
  `extra_blacklist`, matched against command segments.
- `handlers/pre_tool_use/bash_safe_mode.py:159` — `exempt_patterns`.
- `handlers/pre_tool_use/flaggable_content_channel_guard.py:118`.
- `scripts/qa/check_sensitive_content.py:195` and
  `scripts/qa/check_git_history.py:178` — matched over whole-history content.

### What it concretely allows

A hang of the daemon (and therefore of the tool call waiting on it) on
content the project does not control.

The `budget_exhaustion_detector` case is the sharp one because of what it
reads. It scans the `tool_response` of *any* completed tool call other than
the excluded file-content tools — which includes `WebSearch` and `WebFetch`,
whose response bodies are fetched from the open internet. So the text side of
the match is genuinely external, arbitrary in size, and chosen by someone
else.

Three things compound:

1. **No timeout.** Python's `re` has none, and a grep for any mitigation
   (`redos`, `signal.alarm`, `regex.*timeout`, `catastrophic backtrack`)
   across `src/`, `scripts/`, `docs/` and `CLAUDE/` returns nothing but two
   incidental prose mentions in plan documents. There is no `regex` module
   fallback and no complexity check anywhere in the project.
2. **No size cap on this path.** `sensitive_content` has explicit size
   stand-downs for the commit-scanning path (512 KiB per file, 4 MiB per
   commit, per `CLAUDE.md`); this handler has none. A large fetched page is
   matched whole.
3. **`re.DOTALL` is set here and nowhere else among the config-pattern
   sites.** `DOTALL` makes `.` cross newlines, so a pattern that is benign
   against a single line — `.*budget.*exceeded.*` is the obvious thing a
   client would write for this handler — becomes a whole-document scan with
   multiple overlapping `.*` runs. That is the standard route by which an
   author's reasonable-looking regex acquires super-linear backtracking
   without the author changing it.

A client writes the pattern, so this is a footgun rather than an injection.
But the handler is **enabled by default** (`get_default_enabled` returns
`True`, `:483-489`), `extra_patterns` is the documented way to extend it, and
nothing at config-load time or at compile time tells the author that their
pattern will be run with `DOTALL` against unbounded third-party text.

### The class

**A pattern from configuration, compiled without a complexity bound and
matched against text whose size and origin the project does not control.**

Membership needs all three: the pattern is not authored in the source tree;
the haystack is not bounded by the project; and no timeout, size cap or
complexity check sits between them. A config pattern matched against a command
line (bounded, locally produced) is *not* a member — which correctly excludes
`pipe_blocker` and `bash_safe_mode` from the acute form and leaves them as the
same hazard at much lower severity.

### Why the test suite does not catch it

Tests supply well-behaved patterns and short haystacks, because a test that
supplied a catastrophic pattern and a megabyte of text would hang the suite —
so nobody writes one. The defect is a *performance cliff conditional on input
shape*, and unit tests assert outputs, not complexity. The handler returns the
correct answer for every input it is given; it just may not return in
reasonable time for an input the suite does not contain.

There is also nothing to assert against: no stated bound exists, so no test
can check one. The absent invariant is the finding.

### Detector hypothesis

Two candidates, and the second is much better than the first.

1. *Analyse configured patterns for catastrophic backtracking.* Reject. Regex
   complexity analysis is undecidable in the general case and approximations
   are famously noisy; a Detector that fires on `(?:[^/]+/)*` — which appears
   in `utils/path_exclusion.py:85` and is provably linear there, because the
   delimiter is excluded from the character class — will be suppressed within
   a week. **Reporting this as noisy rather than as clean**, per the agent
   brief.

2. *Assert the guard, not the pattern.* A Detector that finds every
   `re.compile` whose argument is not a literal, traces the compiled pattern to
   its match call, and requires that the haystack passed there be either
   (a) bounded by an explicit size cap, or (b) locally produced. Mechanically:
   maintain a small declared list of "external haystack" sources
   (`tool_response`, fetched document text, transcript content) and require any
   config-sourced pattern matched against one to pass through a size-capping
   helper. The helper does not exist yet; creating it is the fix, and the
   Detector is what keeps it in place.

**Likely false positives** for (2): a config-sourced pattern matched against
something that merely looks external but is bounded upstream. Expected volume
is low — there are about eight config-pattern sites in the whole tree, so this
Detector's output is a reviewable inventory rather than a stream.

### What would settle it

Empirically measuring whether a plausible client `extra_patterns` entry (say
`.*(?:budget|quota).*(?:exceeded|exhausted).*`) exhibits super-linear
behaviour under `DOTALL` against a large fetched page. I did not run that
experiment: constructing and timing a backtracking payload is adversary-side
mechanics, which the agent brief's scope discipline puts outside this
reviewer's remit. If the caller wants it confirmed before acting, it should be
routed to the `hooks-daemon-opus-security` quarantine executor rather than
done here. Note that the *mitigation* — a size cap on the haystack — is worth
having regardless of how that experiment comes out, which is why this is
reported now rather than held pending it.

---

## Answered clean (looked at, nothing found)

Recorded explicitly so a later reader can tell these were checked rather than
skipped.

| Construct                                                        | Result                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| ---------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `eval` / `exec` of a string                                      | **None** in daemon code. Every occurrence is data inside `handlers/pre_tool_use/security_antipattern.py` (`:87`, `:265`), `strategies/security/python_strategy.py` (`:47`, `:65`) and `constants/rule_ids.py` (`:285`, `:291`) — pattern definitions and deny-message copy describing what to block in *client* code.                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `compile()` (builtin)                                            | **None.**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `pickle` / `cPickle` / `marshal` / `shelve` / `dill` / `joblib`  | **None**, in any form.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `yaml.load` / `UnsafeLoader` / `FullLoader`                      | **None.** All eight YAML reads are `yaml.safe_load`: `config/loader.py:40`, `config/models.py:2140`, `daemon/validation.py:145`, `daemon/cli.py:4131`, `install/config_cli.py:79`. Writes are `safe_dump`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `eval` / dynamic `source` in shell                               | **None** in `bin/` (two files: `echd-capture`, `hooks-daemon`) or in `scripts/**/*.sh`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| Secret word list treated as a regex                              | **Correctly literal.** `utils/secret_redaction.py:356-372` documents and implements case-insensitive *substring* containment; `_redact_term` (`:376-386`) uses `re.escape`. A term that is itself a metacharacter string matches only itself. This is the place a "pattern assembled from input" defect would most naturally live, and it is closed deliberately.                                                                                                                                                                                                                                                                                                                                                                                                                            |
| Path values interpolated into regexes                            | **All escaped.** Checked every site: `plan_qa/checks/path_existence.py:52`, `plan_qa/checks/common.py:437`, `issue_report/currency.py:75`, `utils/command_evasion.py:198`, `handlers/pre_tool_use/verification_result_gate.py:161`, `handlers/post_tool_use/recovery_cron_advisor.py:88`, `handlers/post_tool_use/goal_injection.py:549`, `handlers/pre_tool_use/dispatch_declaration.py:127`, `handlers/pre_tool_use/markdown_organization.py:1177,1188`, `handlers/pre_tool_use/plan_number_helper.py:343,522`, `handlers/pre_tool_use/worktree_file_copy.py:89`. Every one calls `re.escape` on the interpolated part. `utils/command_evasion.py:191-193` states the rule as a contract: *"Regex metacharacters in it are escaped, so a caller cannot smuggle a pattern through config."* |
| Glob→regex translation                                           | **Sound.** `utils/path_exclusion.py:64-101` escapes every literal character (`:88`) and expands only `*`, `**`, `?`, `/`. No injection route from an `exclude_paths` entry into pattern syntax.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| Invalid config regex crashing or failing open                    | **Handled deliberately at every site**, with two documented and defensible postures: fail-soft-and-cache-`None` (`sensitive_content.py:546-560`, `pipe_blocker.py:54-72`, `budget_exhaustion_detector.py:493-502`) and fail-loud-at-load (`bash_safe_mode.py:139-163`). Not a finding.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `importlib.import_module` on a config-derived name               | `config/validator.py:148,169`. The prefix is a string literal and `event_type` is validated against `VALID_EVENT_TYPES` upstream; `modname` comes from `pkgutil.walk_packages` over an already-imported package. No route to an arbitrary module. Recorded because a Detector for Finding 1 will flag it (see that finding's false-positive note).                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| Playbook `expected_message_patterns` as a regex from a data file | `daemon/playbook_harness.py:345,478-480`. The blocks originate from handler-declared acceptance-test definitions, including project handlers' — so any pattern reaching here came from Python that Finding 1's chain has *already executed*. No additional capability; not a separate finding.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `nitpick` handlers' compiled patterns                            | `hedging_language.py:94`, `dismissive_language.py:132` compile from `_CATEGORY_PATTERNS`, a module-level literal — **not** config. Initially suspected, cleared on reading.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| Built-in patterns with catastrophic backtracking                 | Examined the nested-quantifier candidates found by structural grep: `utils/command_evasion.py:78,83,103`, `utils/path_exclusion.py:85`, `docs_qa/checks/rules_file_shape.py:71`, `docs_qa/checks/unenforced_approval_gate.py:71`, `handlers/pre_tool_use/markdown_organization.py:181`, `skill_scan/clustering.py:22`, `install/forwarder_generator.py:326`. All but the last are linear: each repeated group is separated by a delimiter excluded from its own character class, which forces a unique split. `forwarder_generator.py:326` (`[A-Za-z0-9._+-]*[A-Za-z0-9][A-Za-z0-9._+-]*`) has genuine polynomial ambiguity, but runs at install time over generated forwarder content, not over external input — noted, not filed.                                                          |

---

## Relationship to the existing register

[`CLAUDE/Security/README.md`](../../../Security/README.md) holds one category,
[authored path resolution](../../../Security/AuthoredPathResolution.md), whose
Defence is `scripts/qa/check_authored_path_stat.py`. That Detector examines
stat predicates on joined paths in the documentation-resolution trees. It does
not look at config validators, does not look at code-loading sinks, and would
not fire on any of the three findings above.

Finding 2 is the closest relative — it is `..` again — and the caller should
decide deliberately whether it extends that category or opens a new one. My
reading is that it is a **new** category: the existing one is about `..`
resolved *through the filesystem* by a stat, while this is about `..` never
being checked on one branch of a validator. The two need different Detectors,
and the register's own rule is that a category is defined by what one Detector
finds.

Findings 1 and 3 belong to categories that do not exist yet. Per the register's
contract, I am not writing them in: a category with no Defence is a claim the
register cannot make honestly, and the caller writes it once the Defence
exists.

---

## What I did not do

- I did not write, edit, move or delete any file other than this report, and
  ran no fix. Read-only throughout.
- I did not construct or time a backtracking payload (Finding 3), for the
  scope reason stated there.
- I reviewed only `D-EVAL`. `src/claude_code_hooks_daemon/`, `scripts/` and
  `bin/` were all covered for it. Adjacent constructs that belong to other
  checks — the `playbook_harness` mini-interpreter over shell-shaped strings
  (`daemon/playbook_harness.py:109-115`, `D-EXEC`), and the filesystem
  containment question that Finding 2 touches (`D-PATH`) — are flagged here
  for their owners, not analysed.
