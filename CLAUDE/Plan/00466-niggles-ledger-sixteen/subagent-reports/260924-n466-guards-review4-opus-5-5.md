# Plan 00466 — adversarial security review 4 of `worktree-n466-guard-defects`

**Reviewer**: Opus 5.5, read-only. I edited no tracked file. Probes are under
`/workspace/untracked/scratch/probe_guards_v4_*` (payloads carry
`"synthetic_source": "review-guards-v4"`); the review-3 probes
(`probe_guards_v3_*`, `probe_gd_failclosed.py`) were re-run as instructed.
**Branch**: `worktree-n466-guard-defects`, HEAD `3800bd00` (= `4d12497e` plus a
tests-only follow-up: `TestMalformedToolInputNeverRaises` for the quarantine
guard). Base: `git merge-base main HEAD` = `d14ff619`.
**Scope**: verify every review-3 finding (B1-R3, M1, M2, M3, m1, m2, n1, n2)
plus the review-4 addenda (ENOENT-narrow fail-close, quarantine wrapper,
1 MB timing) are ACTUALLY fixed; hunt NEW bypasses in the new primitives
(`utils/shell_expansion.py`, the per-scan memoisation, the three fail-closed
wrappers); confirm no new QA exclusions; confirm each fix is RED-pinned.

## Verdict: NOT READY for merge.

| Severity | Count |
| -------- | ----- |
| Blocker  | 0     |
| Major    | 1     |
| Minor    | 2     |
| Nit      | 1     |

Every review-3 finding and every review-4 addendum is verified fixed, fast,
and (with one gap, minor m-1 below) RED-pinned. The one reason this is NOT
READY is a **live secret-read fail-open I found in the new `expand_braces`
primitive** (M-1 below): `cat id_rs{a..a}` — which bash expands to the exact
protected file `id_rsa` — is ALLOWED, because the brace expander handles comma
alternation but not `{a..a}` SEQUENCE expansion or quote-stripping. It is
**pre-existing on main** (the pre-review-3 expander was comma-only too), so it
is not a regression this branch introduced — but it sits squarely in the remit
of the primitive this branch ships, and I am not willing to certify a guard I
just used to read `id_rsa`. If the coordinator scopes it to its own niggle,
the review-3/review-4 work is independently sound and mergeable.

## What holds up (verified on this branch)

- **B1-R3 (blocker) fixed.** `expand_braces` is lazy + capped: `{a,b}`×22 in a
  ~115-byte word raises `TooManyToEnumerateError` in ~0.001s, and the exploit
  `cat .vault-password; echo {a,b}×22` denies at wall 0.25s (was >90s / a
  socket-timeout ALLOW). Re-ran `probe_guards_v3_timing.pyprobe` and
  `probe_guards_v3_brace_bypass.pyprobe`: every brace shape denies, eval ≤
  0.001s (`probe_guards_v4_rerun_v3_timing.txt`, `_brace_bypass.txt`).
- **M-1 (the `/**/` FS walk) fixed.** Every `/**/`, `/*/*/*/…`, `**/`, bracket-
  form and 10-token shape now denies via `R-SECRET-EVALUATION-ERROR` (the
  `TooManyToEnumerateError` from `bounded_recursive_glob` reaching the N11
  wrapper) at eval ≤ 0.03s. `bounded_recursive_glob` directly verified
  (`probe_guards_v4_walker.pyprobe`): refuses root `**` and root `*/*/*.x`,
  the entries-visited cap trips on a no-match tree, a symlinked dir is NOT
  descended (`follow_symlinks=False`, so no loop), a mid-walk deadline raises
  `TimeoutError`.
- **M-2 (`_dispatch_key` outside the wrapper) fixed.** `tool_input` `None` /
  `[]` / a bare string now all DENY through `HandlerChain(strict_mode=False)`
  for both `secret_file_guard` and `project_containment`
  (`probe_guards_v3_toolinput_inner.pyprobe`, `probe_gd_failclosed.py`:
  `cases=44 bad=0`). `_dispatch_key` is wrapped in `_compute_and_cache_matched`
  and `_take_cached_matched`.
- **M-3 (enforce_llm_qa regex + brace + eval) fixed.** The catastrophic
  `\S*\{…\}\S*` word-finder is gone (delegates to `iter_brace_words`); the
  94/200 KB no-brace inputs are 0.3s/0.9s (was 15s/>45s); `eval`×100/250/400
  are ~0.9s (was >71s); the over-cap brace word fails closed to DENY
  (`probe_guards_v4_llmqa_cap.pyprobe`: over-cap → `could_name=True`).
- **Review-4 addenda fixed.** ENOENT-narrow: `_expand_glob_token` and
  `bounded_recursive_glob` continue on ENOENT but PROPAGATE `EACCES`/other
  OSErrors (`probe_guards_v4_walker.pyprobe`: "EACCES mid-walk → PermissionError
  RAISED"). Quarantine wrapper: a forced `PermissionError` via
  `find_protected_mention_strict` DENIES through the chain, and `tool_input`
  None/[]/str no longer raises (`probe_guards_v4_quarantine.pyprobe`:
  `cases=5 bad=0`; and the branch's own `TestMalformedToolInputNeverRaises`).
- **Per-scan memoisation is sound.** The `mention_cache` is a call-local
  `dict` built fresh inside `iter_protected_mentions`
  (`secret_file_matching.py:1269`); every other input to `_token_mention`
  (`patterns`, `stem_pairs`, `project_root`, `cwd`, both-edges tuples) is fixed
  for the whole call, so two occurrences of the same token text genuinely
  cannot judge differently. No cross-call or cross-cwd leakage: nothing keys
  the cache at module scope.
- **No new QA exclusions or suppressions.** `git diff d14ff619..HEAD` on
  `*exclusions*`/`*.yaml`/`*.yml`/`scripts/qa/*.json` shows only a REMOVAL
  (the obsolete `_expand_glob_token` `silent-continue` entry). No `noqa` /
  `nosec` / `type: ignore` / `nolint` added under `src/` or
  `.claude/project-handlers/`. `audit_error_hiding.py` (whole project): 0
  violations. Full related suite at HEAD: **628 passed**.
- **Fixes are RED-pinned (reverted individually in a scratch copy under
  `/workspace/untracked/scratch/probe_guards_v4_redcopy`, never the worktree):**
  reverting the brace cap → `test_exceeding_the_spelling_cap_raises` FAILS;
  reverting the M-2 `_dispatch_key` wrap → 6 `TestDispatchKeyMalformedToolInput`
  tests FAIL; reverting the EACCES-propagate →
  `test_a_permission_denied_subdirectory_raises` FAILS; reverting the
  quarantine wrapper → 3 `TestFailClosedOnEvaluationError` tests FAIL. (The one
  gap is m-1 below.)

---

## Major

### M-1 — `expand_braces` does not implement brace SEQUENCE expansion or quote-stripping, so `cat id_rs{a..a}` reads the exact protected file `id_rsa` (ALLOW)

- **Where:** `src/claude_code_hooks_daemon/utils/shell_expansion.py:79-130`
  (`_raw_brace_expansions` / `expand_braces`). The expander splits a `{...}`
  group on `,` only — it never expands a `{a..z}` / `{1..N}` SEQUENCE, and it
  never strips quotes inside a group. Bash does both. The result reaches the
  secret guard's Bash-mention route (`secret_file_matching.py:1307-1308`
  `_brace_expansion_tokens` → `iter_protected_mentions`).

- **Impact — a live secret read.** Verified end-to-end through the real
  `SecretFileGuardHandler.matches()`+`handle()`
  (`probe_guards_v4_seq_handler.pyprobe`):

  | command (bash expands to)                          | guard verdict                                      |
  | -------------------------------------------------- | -------------------------------------------------- |
  | `cat id_rs{a..a}` → `id_rsa`                       | **matches=False → ALLOW**                          |
  | `cat id_ed2551{9..9}` → `id_ed25519`               | **matches=False → ALLOW**                          |
  | `cat id_rs{'a',x}` → `id_rsa id_rsx`               | **ALLOW** (`probe_guards_v4_quote_bypass.pyprobe`) |
  | `cat id_rs{"a",x}` → `id_rsa id_rsx`               | **ALLOW**                                          |
  | `cat id_rs{a,x}` (comma control) → `id_rsa id_rsx` | deny (comma IS handled)                            |
  | `cat id_rsa` (literal control)                     | deny                                               |

  Bash truth confirmed with a live `bash -c 'echo id_rs{a..a}; echo id_rs{'a',x}'`
  → `id_rsa` / `id_rsa id_rsx`.

- **Scope — exact-name patterns only.** The two shipped WILDCARD patterns
  (`*.secret*`, `.vault-pass*`, `*.vault-password`, `*vault_pass*`) are
  self-protecting: you cannot spell enough of the name to reach the file
  without the literal stem (`.vault-passwor…`) already matching the `*`-glob.
  The exposure is the two shipped EXACT-name patterns (`id_rsa`, `id_ed25519`)
  — and, more importantly, ANY exact filename a project adds via
  `protected_paths` (e.g. `credentials.json`, `.env`, `master.key`), which is a
  common configuration.

- **Why it matters despite being pre-existing.** The comma form
  (`{a,x}`) IS expanded and denied — that is the whole point of the M2d brace
  route review 2 built. Sequence and quote-stripping are the same shell
  feature family; an expander that does one but not the others is a class-(c)
  heuristic gap, not a class-(d) undecidable one. (The mid-word-quote route
  `cat id_rs'a'` is a DIFFERENT, genuinely class-(d) string-assembly case —
  documented UNBLOCKABLE in `RESEARCH-read-routes.md:71` — and I do NOT count
  it as a finding; I mention it only to bound the scope.)

- **Reproducers:** `probe_guards_v4_brace_seq.pyprobe`,
  `probe_guards_v4_seq_handler.pyprobe`, `probe_guards_v4_quote_bypass.pyprobe`.

- **Fix direction:** extend `expand_braces` to (a) expand a `{start..end[..step]}`
  numeric/char sequence, capped by the SAME `max_spellings` guard (a
  `{1..100000}` sequence must raise `TooManyToEnumerateError`, not enumerate —
  I verified `{1..3}` is currently treated as one literal alternative, so the
  cap is not even reached today), and (b) strip surrounding `'`/`"` from each
  alternative before yielding. Add RED tests: `cat id_rs{a..a}`,
  `cat id_ed2551{9..9}`, `cat id_rs{'a',x}` each DENY; `{1..100000}` raises.

---

## Minor

### m-1 — the root-refusal branch of `bounded_recursive_glob` is not independently RED-pinned; the multi-wildcard-no-`**` own-finding has no test at all

`shell_expansion.py:253-261` refuses a root-anchored pattern that carries `**`
OR ≥2 wildcard segments. I deleted this whole branch in the scratch copy and
**all 35** `test_shell_expansion.py` + `TestBraceAndFsWalkAreBounded` tests
still PASSED (`probe_guards_v4_red_multiseg.txt`). Two reasons: (1) the `**`
tests use `max_entries_visited=100`, so the entries-visited cap masks the
missing immediate refusal; (2) there is NO test exercising the
`wildcard_segments >= 2` own-finding (`/*/*/*/*/*/*/*.x`), which — with the
branch removed — routes to an UNBOUNDED `base.glob()` on `/` (the exact ~1.1s
cost the fix report claims to close). The live code is correct (verified
directly: "root 3-wild → RAISED TooManyToEnumerateError"), but the fix is not
regression-protected. Add a test that asserts `bounded_recursive_glob(Path("/"), "*/*/*.x")` raises `TooManyToEnumerateError` (no `**`).

### m-2 — the both-edges FS route remains cwd/existence-dependent (unchanged from review 3's m-2)

Re-confirmed (`probe_guards_v3_bothedges.pyprobe`): an interior-wildcard
spelling of a `*.secret*`/`*vault_pass*` file denies only when the file EXISTS
and is reachable; absent, it ALLOWs (safe by construction — a glob that expands
to nothing reads nothing). Carried forward from review 3 as an honest ledger
sentence, not a new defect.

## Nit

### n-1 — `_strip_timeout_prefix` still mis-skips a flag VALUE (unchanged from review 3's n-1)

`enforce_llm_qa.py:316-333` skips `timeout`'s flags by leading `-` but not
their values; acknowledged in-docstring, fails toward the safe (usability)
direction for this guard. Low value, carried forward.

---

## Coverage of the review-4 brief, point by point

1. **Every review-3 shape under 1s ending in DENY** — yes (see "What holds up";
   `probe_guards_v4_rerun_v3_*.txt`, max eval 1.1s at 200 KB, all DENY).
2. **New bypasses in the new primitives** — found M-1 (brace sequence/quote).
   The cap "too many to enumerate" path DENIES in every caller
   (secret_file_guard via N11 wrapper; enforce_llm_qa via
   `_word_could_name_the_script` → True; project_containment does not use the
   expander at all). No brace/glob names a protected file only in expansion
   N+1 past the cap (past the cap it raises → deny). Quoting/escaped-comma/
   empty-alt over-expand (fail-safe) EXCEPT the sequence/quote-strip gap in
   M-1. Unicode look-alikes do not match (correct — not the same filename).
3. **Symlinked dirs / `..` / ENOENT-vs-EACCES spoofing** — walker uses
   `follow_symlinks=False` (no loop, no symlink descent); ENOENT continues
   (proven negative), EACCES/other propagate (fail closed). An attacker cannot
   make an existing protected dir raise ENOENT — ENOENT means absent, and an
   existing-but-unreadable dir raises EACCES which fails closed.
4. **Fail-closed wrappers with None/list/str/huge/forced exceptions** — all
   DENY across the three guards (`probe_gd_failclosed.py` cases=44 bad=0;
   `probe_guards_v4_quarantine.pyprobe` cases=5 bad=0).
5. **No new QA exclusions/suppressions; no audit_error_hiding dodge** — confirmed
   (one exclusion REMOVED; audit clean).
6. **Tests go RED when each fix is reverted** — confirmed for the cap, M-2,
   EACCES-propagate and the quarantine wrapper (scratch copy, worktree
   untouched); the one gap is m-1.

## Probe index (all under `/workspace/untracked/scratch/`)

- `probe_guards_v4_brace_seq.pyprobe` — brace sequence/quote/escape/empty/unicode
  vs `expand_braces` and the matcher.
- `probe_guards_v4_seq_handler.pyprobe` — the id_rsa/id_ed25519 sequence read
  end-to-end through the real handler.
- `probe_guards_v4_quote_bypass.pyprobe` — quote-in-brace and mid-word-quote vs
  exact-name patterns.
- `probe_guards_v4_walker.pyprobe` — `bounded_recursive_glob` symlink/ENOENT/
  EACCES/cap/root-refusal/deadline edges.
- `probe_guards_v4_quarantine.pyprobe` — quarantine wrapper fail-closed + the
  PermissionError path.
- `probe_guards_v4_llmqa_cap.pyprobe` — enforce_llm_qa cap fail-closed.
- `probe_guards_v4_rerun_v3_{timing,brace_bypass,llmqa_timing,toolinput,bothedges,fsroot_test}.txt`
  — review-3 probes re-run.
- `probe_guards_v4_red_{brace,m2,root,enoent,quar,multiseg}.txt` — the
  revert-to-RED runs (scratch copy `probe_guards_v4_redcopy`, worktree never
  modified).
- `probe_guards_v4_fullsuite.txt` (628 passed), `probe_guards_v4_errhide.txt`
  (0 violations).

No real protected file was opened. Every protected name in the probes is
assembled from reversed strings and judged as TEXT only; the walker probes
touched only scratch temp dirs.
