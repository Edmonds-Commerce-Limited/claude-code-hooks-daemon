# Security review (delta) — check `D-EVAL`

**Routine**: 00002 security-review-delta, run 2026-001.
**Check**: `D-EVAL` — new dynamic execution or deserialisation: `eval`, `exec`,
`pickle`, `yaml.load`, a regex assembled from input.
**Interval**: `v3.63.0..v3.64.0` — 432 commits, 907 files, +75521/-3636.
**Answerable**: yes. The diff was produced and read; nothing was unreachable.
**Findings**: 1.

> Written via a Bash heredoc because the `Write` tool was disabled for this
> session. It therefore did not pass the content guards that key on `Write`.

## Method

Whole-interval diff, added lines only, scanned for every D-EVAL construct:
dynamic execution in Python and shell, builtin `compile()`, `pickle` /
`marshal` / `shelve` / `dill` / `jsonpickle`, `yaml.load`, `__import__` /
`importlib` / `exec_module`, `literal_eval`, `tarfile` / `zipfile` / `xml`
parsing, and every `re.compile` / `re.search` / `re.match` / `re.sub` call in
the interval whose pattern argument is not a source literal. Candidates were
then read in the post-interval tree.

## Finding 1 — a payload-supplied regex is compiled and run unbounded on the PreToolUse path

**Severity**: high on mechanism, medium on end-to-end outcome (see *Confidence*).
**Newness**: the site pre-dates the interval; the interval touched it, widened
it, and — the point — the full sweep's own boundary rule routed this instance
into its dismissed column on a premise measurement shows to be false.

### Citation

`src/claude_code_hooks_daemon/utils/process_probe.py:983`:

    match = re.search(_as_python_regex(pattern), subject)

`pattern` arrives at `process_probe.py:1125` as
`pattern = invocation.operands[0]` — the first operand of a `pgrep`/`pkill`
invocation parsed out of the Bash command the handler is judging. It is
neither escaped nor length-bounded nor complexity-checked. `_as_python_regex`
(`:935-967`) only re-spells ERE anchors; it neutralises nothing.
`_is_expanded` (`:807-811`) returns `False` for a single-quoted operand, so a
quoted pattern is not diverted to the `UNRESOLVED` verdict and reaches the
search intact.

Entered from `handlers/pre_tool_use/self_matching_process_probe.py:409`
(`matches`) and `:423` (`handle`), each of which calls `self._collect(command)`
— so the whole classification, and therefore this search, runs **twice per
dispatch**. The handler is enabled at `.claude/hooks-daemon.yaml:325-327`.

### What it allows

Python's `re` has no timeout. Measured `re.search` of a nested-quantifier
operand against a subject of the shape of the probe invocation itself:

| operand chars | seconds |
| ------------- | ------- |
| 16            | 0.009   |
| 20            | 0.077   |
| 24            | 1.287   |
| 26            | 5.755   |
| 28            | 21.747  |

Growth is about 3.8x per added character. Hooks are configured with
`"timeout": 60` (`.claude/settings.json:22,33`), so an operand around 30
characters exceeds it inside a single search — and a command may carry several
probe invocations, each classified independently, twice per dispatch.

The concrete wrong outcome is not "the daemon is slow". It is that the
PreToolUse hook for that Bash call returns no verdict inside its timeout, and a
hook that does not return is not a hook that denied. Every other Bash guard
decided in the same dispatch — the destructive-git rules, `project_containment`,
the command-shape blockers — goes undecided with it.

### The class

**A regex whose pattern text comes from the tool payload under judgement,
compiled and matched with no timeout, no length cap and no complexity check, on
a path whose failure mode is a missing verdict.**

Membership test, usable without asking me: (1) the pattern string is neither
authored in the source tree nor read from project config — it is lifted out of
the input the handler exists to judge; (2) it reaches `re.compile` /
`re.search` / `re.match` rather than a literal comparison; (3) nothing between
the two bounds the work.

### Why the full sweep missed it

The whole-repo sweep's `D-EVAL` Finding 3
(`260915-secreview-D-EVAL-opus.md:313-448`) covered patterns from
*configuration* matched against *external* text. Its own membership rule says:
"A config pattern matched against a command line (bounded, locally produced) is
*not* a member — which correctly excludes `pipe_blocker` and `bash_safe_mode`
from the acute form and leaves them as the same hazard at much lower severity."

Two things separate this case:

- The pattern is not config-sourced. It is payload-sourced, a provenance that
  report never enumerated — `process_probe.py`, `pgrep`, `pkill`, `operand` and
  `_as_python_regex` appear nowhere in it.
- The premise the downgrade rests on — a command-line haystack is bounded,
  therefore low severity — does not hold. The cost is exponential in the
  PATTERN's structure, not the subject's length, and the table above shows the
  cliff arriving at under 30 characters of haystack. Bounding the haystack buys
  nothing here.

That is this delta run's reason to exist: the sweep covered the theme, and its
own boundary rule filed this instance under "much lower severity".

### What the interval changed

At `v3.63.0` there were two call sites of `_matches_own_command_line` (`:1019`,
`:1092` of the old file). At `v3.64.0` there are four (`:1128`, `:1130`,
`:1132`, `:1209`): `_pattern_verdict` was reshaped to re-test against
`own_text` and then locate the matched substring, so one probe invocation now
costs up to three compile-and-search calls instead of one.

Precisely what that does and does not mean: the pathological *non-matching*
pattern returns after the first search, so the multiplier is not what makes the
cliff reachable — one search already exceeds the timeout. What the extra calls
widen is the set of pattern shapes that reach it (one that matches `subject`
cheaply and then backtracks against `own_text`), and they triple the cost of
the shapes that do.

### Why the test suite does not catch it

The handler returns the correct verdict for every input the suite supplies. The
defect is a performance cliff conditional on the input's regex structure, and
no test supplies a catastrophic pattern — a test that did would hang the suite,
which is why nobody writes one. There is also no stated bound anywhere to
assert against: the absent invariant is the finding. `re.error` is caught
(`:984`) and a timeout is not an exception, so the existing defensive-handling
test passes while the hazard is untouched.

### Detector hypothesis

Flag every `re.compile` / `re.search` / `re.match` / `re.fullmatch` / `re.sub`
whose pattern argument is not a string literal and not a module-level
`Final[re.Pattern]`, where the argument traces back to a hook-input accessor
(`get_bash_command`, `tool_input`, `tool_response`) or to a value parsed out of
one, and where no `re.escape` or length cap sits between.

Implementable as an AST walk: collect names bound from the payload accessors,
propagate through local assignments and dataclass field reads within the
module, then flag the regex calls. Its negative tests already exist in this
interval: `install/report_currency.py::_subsystem_pattern` joins
`re.escape(word)` fragments, and `utils/shell_segmentation.py` builds an
f-string around `re.escape(name)` — both correct.

**Likely false positives**: a payload-derived string escaped in a helper one
call away, so the escape is not adjacent and a shallow trace misses it; and QA
scripts compiling a pattern read from a checked-in corpus, which is
source-authored in spirit but not a literal in the AST. Expected volume is
small — three non-literal pattern arguments across `src/` in the whole interval
— so its output is a reviewable inventory rather than a stream. I do not
believe this rule is noisy, and the reason is the tiny population: widen it to
"any non-literal pattern" without the payload-provenance condition and it
becomes noisy immediately, because every f-string built from module constants
would match.

**The Detector should land before the fix.** The obvious remediation — cap the
operand length and refuse to compile beyond it, or replace the search with a
literal-containment test plus a declared list of safe metacharacters — changes
a deny surface in every installing project, so it wants its own decision.

### Confidence, and what would settle it

- **Confirmed by measurement**: the operand is payload-controlled and reaches
  `re.search` unescaped; a sub-30-character pattern costs more than the
  configured 60 s hook timeout. I timed `re.search` directly with the same
  pattern text `_as_python_regex` would emit for these inputs — it is a no-op
  on them — rather than the full handler, because the package will not import
  in this worktree (no venv, `pydantic` absent). Handler overhead is excluded
  and can only make it worse.
- **Not confirmed**: what Claude Code does when a PreToolUse hook exceeds its
  timeout. I assumed the tool call proceeds — the ordinary fail-open reading,
  and what `CLAUDE/Security/FailOpenBoundaries.md:11` describes as the class —
  but did not verify it. If the harness treats a hook timeout as a denial, the
  severity drops to a denial of service against one's own session.
- Settling it needs one observation: run a Bash call whose PreToolUse hook
  exceeds the timeout and record whether the command executes. That is a live
  harness experiment, not code reading, and it is the single fact the severity
  hinges on.

## Adjacent, and explicitly NOT part of `D-EVAL` — routed, not filed

`handlers/post_tool_use/budget_exhaustion_detector.py:396-421` gained, in this
interval, a second regex pass: for every match of every builtin/extra pattern,
`_UNRENDERED_PLACEHOLDER_RE.search(_line_around(...))`. `_line_around`
(`:417-421`) returns `text[line_start:]` — the entire remainder — when no
newline follows the match, and `_stringify_tool_response` (`:373-378`) produces
`json.dumps` output, which has no newlines. So on the JSON path the "line"
window is the whole blob, re-scanned per match.

Two consequences, neither a D-EVAL question, both belonging to whoever owns the
full sweep's open Finding 3:

1. Cost becomes O(matches x blob) on the one path that report named as its
   acute case — unbounded `tool_response` text, including fetched page bodies.
2. More interesting: one placeholder-shaped substring anywhere in a
   newline-free response causes *every* match in that response to be skipped,
   so the detector silently reports nothing — "checked and clean" and "blinded"
   render identically. That is a guard-integrity question, not a
   dynamic-execution one.

Both patterns involved are source-authored and linear, so neither is a D-EVAL
finding. Recorded so the caller can route it rather than rediscover it.

## Answered clean — looked at in this interval, nothing found

| Construct | Result over `v3.63.0..v3.64.0` |
| --- | --- |
| Dynamic execution of a string (Python) | **None added.** The only added lines carrying the words are prose in plan and report documents describing what is blocked. |
| Dynamic execution in shell | **None added.** Two added occurrences, both documentation prose. |
| Builtin `compile()` | **None added.** |
| `pickle` / `marshal` / `shelve` / `dill` / `jsonpickle` | **None added.** One added mention, inside a prior report's own clean table. |
| `yaml.load` / `FullLoader` / `UnsafeLoader` | **None added.** |
| `tarfile` / `zipfile` / `extractall` / `xml` parsing | **None added.** |
| New deserialisation | All added parsing is `json.loads` / `json.load` plus one `tomllib.loads` in `install/` — data-only formats with no code-execution path. |
| New `importlib` / `exec_module` | **One new site, benign**: `scripts/debug_info.py::_load_daemon_util` loads `report_scrubbing.py` and `secret_redaction.py` by path. The path is derived from `__file__` and `name` is a literal at both call sites — no payload, no config, no traversal input. |
| Regex assembled from input | Three non-literal pattern arguments added across `src/`. `install/report_currency.py::_subsystem_pattern` joins `re.escape(word)` fragments — safe. `utils/shell_segmentation.py` wraps `re.escape(name)` in an f-string — safe. The third is Finding 1. |
| Multi-line `re.compile(` additions | All roughly 25 are literals or f-strings interpolating module-level constants (`GIT_INVOCATION`, `_SEGMENT`, `_APPROVAL`, `ENV_PREFIX`). No payload or config value reaches any of them. |
| `setattr` with a non-literal name | `core/handler_registry.py` gained two, both with the attribute name held in a local constant purely to satisfy a linter. Not dynamic in any meaningful sense. |
| `pipe_blocker` pattern change | `self._pipe_pattern` was rewritten this interval to exclude the shell OR operator. Source literal; noted only because a regex change on a guard is `D-RULE`'s question, not mine. |

## Full-only checks

Not attempted, per the delta routine: `F-CVE`, `F-EXPT`, `F-BYPS`, `F-GAP`,
`F-DEPL`, `F-HYG`, `F-PRIV`. Every clean row above means "no such construct was
ADDED in this interval", never "no such construct exists".

## What I did not do

- I did not run the full handler chain — no venv in this worktree, `pydantic`
  absent. Finding 1's timings are of the operation the code performs, without
  the handler's own overhead.
- I did not verify the harness's PreToolUse timeout semantics, the open
  question named above.
- I did not write anything to the security register. That is the caller's to
  write once a class is confirmed and a Defence exists.
