# Security review — check `D-SEC` (Routine 00001, run 2026-001, FULL sweep)

**Check**: `D-SEC` — "New reads of protected material: the secret word list,
`.env`, credentials, anything `secret_file_guard` covers, by any route
including a subprocess."

**Interval**: the CURRENT tree at `5d59f7ff` (full sweep, not a diff).

**Scope discipline**: one check. No protected file was read, listed, hashed or
quoted in producing this report; `.claude/block-words.secret` was never opened.
The audit is of CODE PATHS only.

**Result**: 3 findings, all instances of ONE class. The class is new — the
register's only category (`authored path resolution`) does not cover it.

---

## The class

**Daemon-owned content readers that never consult the protected-path set.**

A defect belongs to this class when all three hold:

1. The code path obtains **file CONTENT** — directly (`read_text`,
   `read_bytes`, `.open()`) or through a **subprocess** (`git diff`,
   `git show`, a linter).
2. The path it reads is derived from an **input** — a tool argument, git's
   output, a tree walk, a marker inside an authored document — rather than
   being a fixed daemon-owned file (config, a ledger, a lockfile).
3. Something derived from that content can reach an **output**: a deny
   `reason`, a log line, a report file, a published artefact — or merely a
   **boolean verdict** the caller can observe (an oracle counts).

…and the module does **not** call `sfm.path_is_protected` /
`sfm.resolve_configured_patterns`.

The boundary is deliberately drawn at BEHAVIOUR, not purpose. That distinction
is the whole finding: every member below is itself a security guard, and each
was skipped by the audit that closed the sibling seams precisely because it was
classified as a guard rather than as a reader.

### Why this is the productive place to look

`secret_file_guard` is a **request-shape** guard. It judges the path an agent
named — a `Read` argument, a Bash token, an authored script's text. Its own
`get_claude_md()` is honest that it is "defence in depth, not a sandbox".

But the daemon is *also a reader in its own right*. Nothing an agent types
names the file when the daemon reaches it: a `git commit -m "wip"` names no
path at all, and `secret_file_guard.matches()` returns `False`. The guard is
not bypassed — it is **not on the path**. Plan 00272 saw this and closed three
seams (below). It did not close them all, and the reason it stopped is
recorded in its own documents.

### Seams Plan 00272 DID close (the control group)

| Site               | Citation                                        | Mechanism                             |
| ------------------ | ----------------------------------------------- | ------------------------------------- |
| Payload capture    | `daemon/payload_capture.py:52-72`, `:157-158`   | Whole event excluded from capture     |
| `lint_on_edit`     | `handlers/post_tool_use/lint_on_edit.py:229`    | Protected path is never lintable      |
| `staged_lint_gate` | `handlers/pre_tool_use/staged_lint_gate.py:249` | Protected path skipped before linting |

`staged_lint_gate.py:246-248` states the reasoning verbatim:

> `# A protected file must never surface in a lint diagnostic -- a`
> `# syntax-error message can quote the offending source line`
> `# verbatim (Plan 00272 Task 4-5).`

That argument transfers word-for-word to Finding 1 and Finding 2, where the
echoed text is not an incidental diagnostic but the **regex match span itself**.

---

## Finding 1 — `sensitive_content`'s staged-content scan reads, retains and can echo a protected file's bytes

**Severity**: the highest in this report. It is reachable by an ordinary
two-command workflow with no protected path typed anywhere.

### Citation

`src/claude_code_hooks_daemon/handlers/pre_tool_use/sensitive_content.py:884`

```python
if self._is_excluded(abs_path) or self._is_secret_list_itself(abs_path):
    continue
```

Those are the **only** two path exclusions on the staged-content surface:
configured `exclude_paths`, and the secret word list itself
(`:1075-1097` — scoped to "the resolved list path alone"). The
`secret_file_guard` protected set is never consulted; `secret_file_matching`
is not imported by this module at all.

Supporting citations:

- `:864-872` — `run_git(repo_root, "diff", ..., target)`: the **subprocess**
  read `D-SEC` names explicitly.
- `:945-957` — the file's added lines are materialised and stored as
  `_Haystack(subject=f"staged content of {relpath}", text=added)`.
- `:702` — that haystack is cached on `self._cached_dispatch`, an attribute of
  a handler instance the module's own docstring (`:728-729`) describes as one
  that "lives for the whole daemon process".
- `:1108-1110` → `:1142` → `:1155-1159` — the public-pattern deny branch:

```python
matched_text = match.get("_matched", "")
...
message += (
    f"\n\n{_SUBJECT_LABEL}: {subject}\n"
    f"Pattern: {name}" + (f" — {description}" if description else "") + "\n"
    f"Matched: {matched_text}"
)
```

### What it concretely allows

With a protected file in the index — reached by `git add -A` / `git add .`
(neither names the file, so `R-SECRET-BASH-MENTION` never fires), or by the
file being git-tracked and `git commit -a` being used — a plain
`git commit -m "wip"`:

1. Causes the daemon to run `git diff --cached` over that file and pull its
   added lines into handler memory, where they are retained on a
   process-lifetime instance until the dispatch's post-decision hook clears
   them (`:722-731`).
2. If **any** configured `public_pattern` matches inside those bytes, emits
   `Matched: <bytes from the protected file>` as the deny reason — which
   Claude Code renders into the model's context and writes to the session
   transcript. `secret_redaction.py:14-20` records that Claude Code's own
   transcripts are redacted by nothing.

The outcome is worse than the guard failing to block: the guard **produces**
the disclosure, in its own deny message, while reporting that it protected
something.

The precondition is not exotic. `secret_file_hygiene_checker.py:160-161`
raises `_ISSUE_TRACKED` for "a git-tracked protected path" — the project's own
model of the world says protected files do end up tracked, and the hygiene
advisory's recommended remedy (`git rm --cached`) has a dedicated exemption
carved into `secret_file_matching.py:95-101` for exactly that situation.

The one thing that is **not** free: the echo needs a `public_pattern` whose
regex matches inside the protected file. This repository's own two patterns
(a vhosts path; a session UUID — `.claude/hooks-daemon.yaml:190-205`) would
not match a PEM private key. A client pattern shaped like a credential — the
advertised use of the feature — would. The **read** and the **retention**
happen unconditionally, with no pattern configured at all.

### Why the test suite does not catch it

Three reasons, each independently sufficient:

1. **The audit classified it by purpose, not behaviour.** Plan 00272's
   `BRAINSTORM.md:269` reads: *"Plan 00252 (staged-content secret scan):
   commit-time, term-based; no overlap, cite as sibling."* `PLAN.md:77-78`
   repeats it: *"siblings, not overlaps."* Once `sensitive_content` was filed
   as a peer guard, nobody asked the reader question about it. The linter
   handlers were caught by the opposite move — `BRAINSTORM.md:242-246` files
   them under *"Also in this class: the daemon's own linter handlers"* because
   someone noticed they QUOTE a line.
2. **The verification checklist inherited the same blind spot.**
   `RESEARCH-read-routes.md:187-189`, item 7: *"Daemon-owned outputs: confirm
   what payload capture / debug logs record …, and what `staged_lint_gate` /
   `lint_on_edit` would quote for a staged/edited protected file."* Three
   sites named; the fourth is absent from the list it was supposed to be on.
3. **No test asserts the property.** Grepping the suite for
   `path_is_protected|resolve_configured_patterns` returns exactly four files:
   `tests/unit/handlers/post_tool_use/test_lint_on_edit.py`,
   `tests/unit/handlers/pre_tool_use/test_staged_lint_gate.py`,
   `tests/unit/handlers/session_start/test_secret_file_hygiene_checker.py`,
   `tests/unit/utils/test_secret_file_matching.py`. The seam test that exists
   for payload capture — `tests/unit/daemon/test_payload_capture.py:189`,
   *"Plan 00272 Task 4-5: a protected-path event is excluded, never
   redacted."* — has no counterpart. `tests/unit/handlers/pre_tool_use/ test_sensitive_content.py` contains no protected-path case of any kind.

Every test passes, because every test asserts what this handler was built to
do. None asserts what it must not read.

### Confidence

- **HIGH** that the read and the retention occur: the code path is
  unconditional and there is no protected-path branch anywhere in the module.
- **MEDIUM-HIGH** that the verbatim echo occurs: it additionally requires a
  configured `public_pattern` that matches inside the file.
- **What would settle it**: a fixture repo with a staged
  `fixture.vault-password` whose body contains a string matching a configured
  public pattern; dispatch a `git commit -m "x"` PreToolUse event and read the
  deny reason. That is a ~20-line unit test and it is also the regression test
  the fix needs.

---

## Finding 2 — `check_sensitive_content.py` reads every tracked file and echoes the match, with no protected-path exclusion

### Citation

`scripts/qa/check_sensitive_content.py:236` — `content = path.read_text(...)`,
for every file in `_tracked_files(repo_root)` (`:351`).

`:307` — the echo:

```python
+ f": {match.group(0)}"
```

`:364-367` — the complete structural exclusion list:

```python
excluded = {config_path}
if secret_word_list_file is not None:
    excluded.add(secret_word_list_file)
```

### What it concretely allows

The word list is excluded; nothing else protected is. A tracked `id_rsa`, a
tracked `*.vault-password`, any tracked `*.secret*` file other than the list is
read in full, and a public-pattern hit prints
`<path>:<line> [public:<name>] Matches public pattern '<name>': <matched text>`
to stdout (`:402-405`) **and** writes it into the JSON artefact at `:398-400`
— an artefact whose own comment (`:393-397`) says `llm_qa.py` "publishes that
artefact for an agent to read as fact". So the disclosure is both printed into
a QA log and persisted on disk in a file agents are directed to read.

This is the same class as Finding 1 on a different surface: the whole-tree
detector rather than the live handler. It matters separately because the two
fail at different times — the handler at commit, the scanner on every QA run,
including runs on a tree nobody is committing.

### Why the test suite does not catch it

The scanner is a Detector. Its tests assert it FINDS things; a test that
asserted it declines to read a file would be asserting a smaller result, which
is the shape of assertion nobody writes for a scanner. It is also a
`scripts/qa/` file, outside the `src/` tree the Plan 00272 seam audit walked —
the audit's own framing was "daemon-owned OUTPUTS", and a QA script's stdout
was not on that list.

### Confidence

**HIGH** on the read-and-echo path (both are unconditional given a match).
Same `public_pattern` precondition as Finding 1 for the echo; the read happens
regardless. Settled by the same fixture: a tracked protected file with a
pattern-matching body, then run the scanner and read its stdout.

---

## Finding 3 — `quote-drift` is a content oracle over any repo-relative path, protected ones included

Reported at lower confidence and with its limits stated, per the rule that a
hypothesis you could not confirm is a legitimate report and an unmarked guess
is not.

### Citation

`src/claude_code_hooks_daemon/docs_qa/checks/quote_drift.py:78-89`

```python
source_abs = project_root / block.source_path
if not source_abs.is_file():
    ...
source_text = source_abs.read_text(encoding="utf-8")
```

`block.source_path` comes from an `ssot-quote` marker **inside an authored
markdown document**. `:123` then decides the verdict:

```python
if verify_quote(block.body, span):
    return None
```

### What it concretely allows

`secret_file_guard._script_content_mention` (`secret_file_guard.py:123-136`,
`:260`) scans authored content for protected-path references **only** for
`_SCRIPT_EXTENSIONS`; markdown is deliberately exempt, because "markdown/prose
legitimately NAMES protected files". So authoring a document containing
`ssot-quote: <protected path>#<anchor>` is ALLOWED by design — and docs-qa then
reads that file, at EDIT time, at commit time (`_run_staged`) and at every
SessionStart sweep (`_run_sweep`).

The finding messages never quote source content, so there is no direct echo.
What leaks is the **verdict**:

- `:102-112` — "anchor was not found" vs. anything else answers *does this file
  contain a heading whose slug is X, or an `ssot-anchor` marker named X?*
- `:123-131` — clean vs. "has drifted" answers *does my guessed body occur
  verbatim in that section?*

Repeated, the second is a confirmation oracle that can be extended one
character at a time. `secret_meta.py:20-22` shows the project already treats
this exact shape as a threat it must design against — *"no prefix/rolling
digests exist here, so the CLI cannot be used as a byte-by-byte extraction
oracle"* — and `quote-drift` provides the capability that module refuses to.

### The limits, stated honestly

- The anchor must resolve (`docs_qa/quotes.py:110-141`): an
  `<!-- ssot-anchor: -->` marker, or an ATX heading whose slug matches. This
  works against **markdown-shaped** protected files — plausible under the
  deliberately broad `*.secret*` default (`notes.secret.md`,
  `runbook.secret.md`) — and not against a PEM key, which has no headings.
- `MIN_QUOTE_LENGTH_CHARS = 80` (`docs_qa/quotes.py:60`). An attacker needs an
  80-character correct foothold before the substring oracle yields any signal,
  which makes cold extraction expensive. Extension from a known foothold is
  cheap.
- The corpus is `.md`-only and honours `daemon.exclude_paths` /
  `scope_exclude_globs` (`docs_qa/corpus.py:403`, `:342-392`) — but never the
  protected set.

Net: a real oracle, narrow and expensive to drive. It is a member of the class
by the "boolean verdict counts" arm of the membership test, and it is the
member that shows why that arm has to be in the test at all.

### Why the test suite does not catch it

docs-qa's tests are about documentation invariants. Nothing in that suite has
any notion of a protected path, and the check's contract — "verify the quote
against its declared source" — is satisfied exactly as specified. The defect is
that the contract has no domain restriction on "its declared source".

### Confidence

**MEDIUM** that the oracle exists as described (read by inspection; the
verdict-to-caller wiring through `Finding` → the edit gate is clear).
**LOW** on practical exploitability against a high-entropy secret, given the
80-character floor.
**What would settle it**: write `untracked/scratch/<dir>/probe.secret.md` with
a heading and a >80-char body, author a doc quoting it correctly and then
incorrectly, and observe whether the edit gate's verdict differs. No real
protected file is needed, and none should be used.

---

## Detector hypothesis

One Detector, `scripts/qa/check_protected_path_readers.py`, wired into
`run_all.sh` as a failing check (per the register's obligation that a Defence
is a Detector, not a regression test).

**Rule.** Over `src/claude_code_hooks_daemon/` and `scripts/qa/`, flag a module
that BOTH:

1. obtains file content from a **non-constant** path — `read_text`,
   `read_bytes`, `.open(`, an `os.walk`/`rglob` body, or `run_git(...)` with
   `diff`/`show`, where the path expression is not a module-level constant or
   a fixed daemon-owned attribute; AND
2. interpolates a content-derived value into an observable — an f-string
   reaching `GatingResult(reason=...)`, `Finding(message=...)`, `print`,
   `logger.*`, or a file write — **or** returns a bool derived from content
   comparison to a caller outside the module;

…and does NOT reference `path_is_protected` or `resolve_configured_patterns`.

**Likely false positives, named because a rule believed noisy is worth
reporting as noisy:**

- Modules reading only fixed daemon-owned state: `utils/goal_ledger.py`,
  `routines/ledger.py`, `skill_scan/state.py`, `config/models.py`,
  `daemon/metadata.py`. Condition (1)'s non-constant-path requirement should
  drop most, but path expressions built from `ProjectContext` will look
  non-constant and need an allowlist of resolver functions.
- `issue_report/citation.py:106` — reads content but emits only
  `len(content.splitlines())`. A true member of arm (1), not of arm (2). The
  detector will flag it unless arm (2) is narrowed to values **derived from
  the bytes**, not from their count; that narrowing is the main tuning knob.
- The guard's own source and `tests/` fixtures, which name protected paths
  legitimately — handled by the existing `exclude_paths` convention.
- `install/` and `remote_docs/` read installer templates and vendored
  documents; both are non-constant paths with echoes. Probably a genuine
  smaller instance of the same class rather than noise, but they should be
  triaged before the rule is set to BLOCK.

**Cheaper high-precision variant**, if the above proves too noisy to ship
blocking: flag only a module that echoes a **regex `match.group(...)`** or a
**diff/file excerpt** into an observable without a protected-path reference.
That catches Findings 1 and 2 with near-zero noise and misses Finding 3 — a
trade worth making explicitly rather than by accident, and worth writing into
the category's "What the Defence does not catch" section if taken.

---

## Two observations that are not findings

**A fragility, recorded so it is not rediscovered as a finding.** The
`gh --body-file <protected path>` route (`sensitive_content.py:810-827` reads
the named body file wholesale) is closed only by handler ORDER:
`SENSITIVE_CONTENT` and `SECRET_FILE_GUARD` share priority 14
(`constants/priority.py:65`, `:71`), and `chain.py:351` breaks the tie with
`sort(key=lambda h: (h.priority, h.name))` — `secret_file_guard` sorts before
`sensitive_content` alphabetically, matches the command (the path IS named on
that command line), and terminates the chain. Correct today, by alphabet.
`chain.py:339-347` logs duplicate priorities as a determinism warning, so the
project already treats a shared priority as something it merely tolerates.
Nothing states this ordering as an invariant, and nothing tests it.

**What was checked and found clean.** `utils/secret_meta.py` — the sanctioned
metadata route — holds up: keyed HMAC by default, bucketed size, a refusal to
sign under a group/world-readable key (`:61-71`), and `allow_plain_hash`
reachable only from config, with `daemon/cli.py:5164` stating "there is no CLI
override" (verified: the flag appears in no argparse definition). An agent
cannot self-authorise the offline-crackable plain digest. `issue_report/ citation.py` is containment-checked to the daemon source tree and emits only a
line count. `core/router.py:188-196` redacts secret TERMS from the PreToolUse
debug log before serialisation, ahead of any handler. These are the places the
brief pointed at, and they were built the way the brief hopes they were.

---

## For the caller

Per the reviewer contract, the register is not written here: a category with no
Defence is a claim the register cannot make honestly. The inputs a
`CLAUDE/Security/DaemonOwnedContentReaders.md` category needs — the class
boundary, the instances, why the tests pass, the Detector and its false
positives — are all above.

Ordering, if this is taken forward under Defence Before Fix: the Detector lands
first and must go RED on all three instances before any of them is fixed.
Finding 1's fix is one call to `sfm.path_is_protected` at
`sensitive_content.py:884`, mirroring `staged_lint_gate.py:249` exactly — but
shipping that fix first would leave the class unwatched and the register
recording that the work was done.
