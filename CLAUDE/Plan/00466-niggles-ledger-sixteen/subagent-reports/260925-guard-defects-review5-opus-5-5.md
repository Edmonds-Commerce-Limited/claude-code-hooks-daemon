# Plan 00466 — adversarial security review 5 of `worktree-n466-guard-defects`

**Reviewer**: Opus 5.5, read-only. I edited no tracked file. Probes are under
`/workspace/untracked/scratch/probe_gd5_*` (every synthetic payload carries
`"synthetic_source": "review-gd5"`; protected names are assembled from reversed
placeholders so no probe file spells one). I did NOT open
`.claude/block-words.secret` and did not restart the main checkout's daemon.
**Stated target**: branch `worktree-n466-guard-defects`, HEAD `ef0600ed`.

## Verdict: NOT READY.

| Severity | Count |
| -------- | ----- |
| Blocker  | 0     |
| Major    | 2     |
| Minor    | 1     |
| Nit      | 0     |

The **committed** work at HEAD `ef0600ed` (N10, N11, and the review-4 M-1
shell-word normaliser) is sound, fast, and fail-closed — on its own merits it
would be READY. The reason this is NOT READY is that **the worktree is not at
HEAD**: two safety-critical source files carry uncommitted changes that were
still being edited *during this review*, and they deliberately WEAKEN the
authored-script content scan on a premise that is false for shell scripts.
What a merge would actually contain is therefore ambiguous, and if it is the
working tree, it ships a write-then-execute regression.

---

## Major

### MAJOR-1 — the worktree diverges from the stated review target and is a moving target

`git status` in the worktree is NOT clean at HEAD `ef0600ed`. When I began it
showed two modified source files; partway through it grew to four:

```
 M src/claude_code_hooks_daemon/handlers/pre_tool_use/secret_file_guard.py
 M src/claude_code_hooks_daemon/utils/secret_file_matching.py
 M tests/unit/handlers/pre_tool_use/test_secret_file_guard.py   (appeared mid-review)
 M tests/unit/utils/test_secret_file_matching.py                (appeared mid-review)
```

`git show HEAD:…` confirms none of the diff below is in the committed tree
(the `context=`/`MentionContext`/`_both_edges_residue_mention` additions do not
exist at `ef0600ed`). The source files' mtime is `2026-09-25 01:42`, i.e. an
agent is actively developing here concurrently with the review. A reviewer
cannot certify a tree that is changing under them, and "the branch at HEAD
`ef0600ed`" and "the branch as it sits on disk" are two different things right
now. Resolve before any merge: either commit the WIP and re-review it, or
revert it so the merge is exactly `ef0600ed`.

Note the committed release-note corpus (`CLAUDE/UPGRADES/UNRELEASED/release-notes/`)
already advertises fixes; release note #13 ("no longer flags a Python unpacking
splat") describes a *committed* bash-route gating change, but the further
content-scan work in the uncommitted diff has no committed counterpart — the
code and the advertised behaviour are drifting.

### MAJOR-2 — the uncommitted content-context change opens a write-then-execute gap for shell scripts

The uncommitted diff threads a `MentionContext = Literal["bash", "content"]`
through the matcher and, for `context="content"` (the Write/Edit authored-script
scan, `secret_file_guard.py:_script_content_mention`), SKIPS every glob-shaped
heuristic (`secret_file_matching.py`, the new `if context != "bash": continue`
in `_token_mention`). Only the literal / brace-expandable matcher runs for
content.

The stated rationale (in the new `MentionContext` docstring): *"content is
never expanded by a shell."* That is true for `.py`/`.js`/`.rb`, but **false
for `.sh`/`.bash`** — which are in `_SCRIPT_EXTENSIONS` and go through the
identical `context="content"` path. A shell script's glob-shaped protected
reference IS expanded when the script runs, which is exactly the
write-then-execute route the content scan exists to close
(`RESEARCH-read-routes.md:85`).

Verified end-to-end through the real `SecretFileGuardHandler` on the WORKING
TREE vs the committed `ef0600ed` overlay (`probe_gd5_content2.pyprobe`,
`probe_gd5_ctxcmp.pyprobe`; HEAD overlay built at
`/workspace/untracked/scratch/gd5_head_pkg`):

| authored `.sh`/`.bash` content                | HEAD ef0600ed | working tree (WIP) |
| --------------------------------------------- | ------------- | ------------------ |
| `cat prod.vault-pass*` (G2 shape)             | **deny**      | **ALLOW**          |
| `cat id_rs?`                                  | **deny**      | **ALLOW**          |
| `cat id*a`                                    | **deny**      | **ALLOW**          |
| `cat id_rsa` (literal)                        | deny          | deny               |
| `cat .vault-pass*` (leading-anchored literal) | deny          | deny               |

Concrete (`probe_gd5_content2` extended): authoring `deploy.sh` /`deploy.bash`
whose body is `#!/bin/bash\ncat prod.vault-pass*` is ALLOWED on the working
tree; at HEAD it is denied. The follow-on `bash deploy.sh` line names nothing,
so the write-time scan was the only layer.

The WIP tests bake this in rather than catch it:
`TestContentContextSkipsAggressiveGlobIntersection::test_an_interior_wildcard_string_literal_denies_on_bash_but_not_content`
asserts the content route deliberately does NOT deny an interior-wildcard
mention. So the suite stays green (389 passed) while the hole is open.

**Fix direction:** scope the exemption by language, not by "is content". Use
`context="content"` only for genuinely non-shell script extensions; keep the
`"bash"` (aggressive) heuristics for `.sh`/`.bash` content, since that content
is shell text a shell will expand. The Python-splat false positive this was
meant to solve (`*words[subcommand_index`) is a `.py` concern and is already
independently addressed by the `_token_literal_residue` change (stop stripping
an unterminated `[`) — that narrower fix does not require disabling glob
heuristics for shell scripts.

---

## Minor

### minor-1 — `bash -c '…'` / `eval '…'` nested single-quote splice reads a protected file (class-(d), pre-existing, present at HEAD)

`bash -c 'cat id_'\''rs'\''a'` is ALLOWED at both HEAD and the working tree
(`probe_gd5_edge.pyprobe`). The review-4 normaliser correctly reads the
`bash -c` argument as one shell word — `cat id_'rs'a` — but does not RE-PARSE
that word as a nested command, so the inner quote-splice that spells `id_rsa`
is never recognised. Traced in `probe_gd5_trace.pyprobe`:
`iter_normalised_shell_words` yields `['bash', '-c', "cat id_'rs'a"]`; the
single-level form `cat id_'rs'a` on its own DOES normalise to `id_rsa` and
denies.

This is the nested-interpreter / string-assembly family that
`RESEARCH-read-routes.md:71` and its conclusion already classify as (d)
UNBLOCKABLE, and it fails open on plain `main` too (the crude tokeniser splits
the escaped quotes into fragments), so it is **not a regression** this branch
introduced, and not something the review-4 fix claimed to close. I raise it
only because `eval`/`bash -c` nesting was in the review brief and is not
named in the resident residual list. Recommend either (a) documenting
`bash -c`/`sh -c`/`eval` string-argument nesting explicitly as a class-(d)
residual, or (b) optionally recursively normalising a `bash -c`/`sh -c`/`eval`
string argument as a command (a modest hardening, not required for merge).

---

## Not defects (verified, listed so they are not re-reported)

- **Deny-on-literal-mention is correct, not a false positive.** `grep 'id_rsa' docs/ssh-setup.md` and `echo id_rsa is a key type` deny because the exact
  protected filename appears verbatim in the command text — the documented
  conservative class-(b/c) behaviour for an exact-name pattern.
- **`cat id_rsa#c` and `cat id_r\163a` correctly ALLOW.** In bash a mid-word
  `#` is not a comment and an unquoted `\1` is the literal digit, so both name
  a *different* filename (`id_rsa#c`, `id_r163a`), not `id_rsa`. The guard is
  right to allow them (`probe_gd5_exotic.pyprobe`).
- **Unicode homoglyphs / suffixes correctly ALLOW.** `cat іd_rsa` (Cyrillic i),
  `id_rsaX`, `myid_rsa`, `id_rsa_backup` are different filenames and are not
  matched.

---

## Confirmations against committed HEAD `ef0600ed`

(Re-run against a clean HEAD overlay at `/workspace/untracked/scratch/gd5_head_pkg`,
built by overwriting only the two dirty files with `git show HEAD:…`.)

- **review-4 M-1 fixed; N10 + N11 hold.** All **52** read spellings DENY
  (`probe_gd5_reads.pyprobe`, TOTAL fail-open = 0), against the shipped
  defaults AND a project-configured exact `.env` pattern: brace SEQUENCE
  (`id_rs{a..a}`, `id_ed2551{9..9}`, stepped, reverse, `Z..a`), comma
  alternation, single/double-quote mid-word splices and whole-word quoting,
  empty-quote splices, quote-inside-brace-alt, backslash escapes, ANSI-C
  `$'\xHH'`/`\NNN`/`\uHHHH`, interior/edge/negated/POSIX-class globs, `$VAR`/
  `${…}`/`$(…)`/backtick collapse-to-glob, `~`/`$HOME`/`${HOME}` prefixes,
  `~user`, python/perl/node one-liners, `find -exec`/`xargs`, redirection and
  process substitution, `env`/`env -S`, `/proc/self/cwd`, `..` traversal,
  here-strings, single-level `bash -c`/`sh -c`/`eval`.
- **Tool inputs (`probe_gd5_tools_res.pyprobe`).** Read/Grep/Edit/Write/
  NotebookEdit on a protected path DENY; `Glob` (names-only) and `id_rsa.pub`
  ALLOW. 0 mismatches.
- **Resource / DoS — all well under 1 s, no freeze, no catastrophic backtrack.**
  Brace/sequence/nesting blowups (`{a,b}×22`, `{1..100000}`, `{…}` depth 200)
  fail-closed-DENY in 0.6–2.4 ms; `100k` quote splices 69 ms; `100k` backslash
  escapes 44 ms; `50k` substitutions 55 ms; `30k` ANSI-C 86 ms; unterminated
  500k quote/subst 22–152 ms; 1 MB single token 322 ms; 1 MB glob tokens
  193 ms. All bounded by the caps in `shell_expansion.py` and the 5 s scan
  deadline.
- **Fail-closed on every exception path (`probe_gd5_failclosed.pyprobe`,
  FAIL-OPEN = 0).** Malformed `tool_input` (`None`, `[]`, a bare string) DENY;
  injected `RuntimeError` in `find_protected_mention_detail`,
  `is_exempt_invocation`, `is_encrypted_target_invocation` each DENY via the
  N11 `_ERROR_ROUTE`; a clean `ls -la` allows.
- **No QA dodge.** No `noqa`/`type: ignore`/`nosec`/`nolint`/`eslint-disable`
  added in the branch diff. The four added `except Exception:` blocks
  (`project_containment`, `secret_file_guard`) all `logger.exception(...)` and
  return a DENY — fail-closed, not error-hiding. The only `pragma: no cover`
  additions are on `yield` stubs in a test file (the mypy generator idiom).
  `scripts/qa/error_hiding_exclusions.json` had one entry **removed** (obsolete
  `_expand_glob_token` silent-continue), none added. `audit_error_hiding.py`:
  "No error hiding violations found".
- **The 9 whole-suite failures are pre-existing, not branch-caused.** Ledger
  N39 is committed on `main` HEAD `c92bfbc1` ("nine unit tests fail only in a
  whole-suite run"). The four named files
  (`test_model_fallback_detector.py`, `test_absolute_path.py`,
  `rule_explain/test_lookup.py`, `test_dangerous_invocation_corpus_checker.py`)
  pass **105/105 in isolation** on this branch (`gd5_iso.txt`). The branch
  touches none of them nor any obvious polluter of them, so the order-dependent
  failures are inherited from main, not introduced here.
- **Committed module suites green.** `test_secret_file_matching.py`,
  `test_shell_expansion.py`, `test_secret_file_guard.py`,
  `test_project_containment.py` → 525 passed on the working tree (`gd5_mods.txt`).

## Probe index (all under `/workspace/untracked/scratch/`)

- `probe_gd5_common.pyprobe` — shared harness (placeholder substitution, real handler).
- `probe_gd5_reads.pyprobe` — 52 read spellings must DENY.
- `probe_gd5_fp.pyprobe` — 55-command everyday false-positive corpus.
- `probe_gd5_edge.pyprobe` — eval/bash -c/env -S/proc/../tilde/xargs + bare-glob FP.
- `probe_gd5_exotic.pyprobe` — exotic spellings + should-not-match (homoglyph/suffix).
- `probe_gd5_tools_res.pyprobe` — tool inputs + resource/DoS bounds.
- `probe_gd5_failclosed.pyprobe` — malformed input + injected-exception fail-closed.
- `probe_gd5_content2.pyprobe`, `probe_gd5_ctxcmp.pyprobe` — the content-context weakening (MAJOR-2).
- `probe_gd5_trace.pyprobe` — nested bash -c splice normalisation (minor-1).
- `gd5_head_pkg/` — clean committed-HEAD overlay used for the confirmations.

No real protected file was opened; the walker/handler probes touched only
scratch temp state and judged assembled names as TEXT.
