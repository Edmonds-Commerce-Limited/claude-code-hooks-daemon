# Plan 00466 — adversarial security review 2 of `worktree-n466-guard-defects`

**Reviewer**: Opus 5.5, read-only. I edited no tracked file. Every probe is under `untracked/scratch/probe_gd_*` with its raw output beside it.
**Branch**: `worktree-n466-guard-defects` at HEAD `dd73b459` (fixes in `d0de526d`, merged with main's N10–N16).
**Scope**: M1 (`enforce_llm_qa` deny-by-default), N11/M4 (fail-closed guards), N10 (interior wildcards), m1, the N4–N6 repros, and the sibling audit.

## Summary

| Severity | Count |
| -------- | ----- |
| Blocker  | 1     |
| Major    | 3     |
| Minor    | 4     |
| Nit      | 4     |

**Verdict: not ready to merge.**

- **B1.** The new N10 intersection DP gives `secret_file_guard` a timing fail-open that main does not have. A crafted 60 KB command reaches `cat <protected>` after the client's 30 s budget has already run out, and a PreToolUse socket timeout ALLOWS.
- **M1.** M1 is not fixed. 19 invocation shapes that main denies are allowed on the branch.
- **M2.** N10 is only partly fixed. Every interior wildcard against `*.secret*` is still allowed, and that pattern protects the daemon's own word list.
- **M3.** Separately: `daemon.strict_mode` is inert in the live daemon. I proved this against this repository's own running daemon. So N11's premise ("this repository fails closed") is false, and every unhardened guard fails open here too.

## What holds up (verified)

- **Targeted tests pass.** `test_secret_file_matching.py`, `test_path_exclusion.py`, `test_secret_file_guard.py`, `test_project_containment.py` and the project-handler `test_enforce_llm_qa.py`: **486 passed** (`probe_gd_pytest.txt`).
- **The N4–N6 repros stay fixed after the merge** (`probe_gd_repros.py`/`_out.txt`):
  - N4: splat `*words[position + 1 :]`, `def f(*wordlist)`, `call(*wordlist)` are ALLOW.
  - N5: a bare `"~/"` next to a real mention, and `ls ~/ && cat <vault>`, DENY with no crash.
  - N6: `mkplan.bash --title "... run_all.sh ..."` and `run_tests.sh; echo "see run_all.sh notes"` are ALLOW, and `cd scripts/qa && ./run_all.sh` is DENY.
- **The m1 named cases deny:** `*rd*rd`, `*word*word`, and `*on*.json` under a project `*secret*.json`.
- **The N11 evaluation wrapper works.** Each of these was checked through a real `HandlerChain(strict_mode=False)` (`probe_gd_failclosed.py`).
  - Injected raises deny with `R-SECRET-EVALUATION-ERROR` at 11 stages: `find_protected_mention_detail`, `is_exempt_invocation`, `is_encrypted_target_invocation`, `resolve_protected_patterns`, `merge_allowed_consumers`, `path_is_protected`, `resolve_against_cwd`, `handler_excludes_path`, `layout_for`, `is_encrypted_at_rest`, and `ProjectContext.project_root` for `project_containment`.
  - Hostile inputs are handled correctly: NUL in a Read, Grep, Write or Bash path; a 100 k-character path; 5000 path components; lone surrogates; a 1 MB token; a missing, nonexistent, int or NUL `cwd`; and a `tool_input` that is None or a list. Each one either denies (error route) or gives the correct verdict.
- **No leak through the error route.** The error deny carries only `Type: message`, and no evaluation stage puts protected CONTENT into an exception. `encrypted_at_rest` catches `OSError`/`BinasciiError` and logs the class name only.
- **Ordinary globs are not false-denied** (29 of 30 cases in `probe_gd_secret.py`): `*.py`, `src/*.md`, `secret*.py`, `report-[0-9]*.txt`, `tests/**/test_*.py`, `~/.ssh/*.pub`, URLs with `?`, `print(*args)` and the like.
  - `ls *word.txt` improved from DENY on main to ALLOW.
  - `ls .vault*.md` is newly denied. That is a genuine intersection with `.vault-pass*`, so it is acceptable.
  - `ls *secret*.md` stays denied, as on main. It is a genuine intersection with `*.secret*` (`x.secret.md`) under the documented "intentionally broad" policy.

## Blocker

### B1 — the N10 interior-wildcard DP opens a timing fail-open that bypasses the whole PreToolUse chain

- **Where:**

  - `src/claude_code_hooks_daemon/utils/secret_file_matching.py:805-847` (`_globs_can_intersect`, an unbounded O(len(a)·len(b)) Python DP);
  - `:850-894` (`_interior_wildcard_mention`, which runs it once per bracket expansion (up to 64), per non-both-edges pattern, per token);
  - `:1052-1055` (the call site, which runs before any later token is examined).

- **Why this is a bypass and not just a slowdown:** `.claude/hooks/pre-tool-use` gives the daemon `--timeout-ms 30000`. On a read-side `socket_timeout`, `.claude/init.sh:1654-1661` emits `hookSpecificOutput` with context only, which means ALLOW for every non-Stop event. `iter_protected_mentions` scans tokens in order, so slow tokens placed BEFORE a genuine mention delay the verdict past the budget.

- **Evidence** (`probe_gd_timing_main.py`/`_out.txt`, same input on main's matcher and the branch's):

  | Input                                                                    | main    | branch                     |
  | ------------------------------------------------------------------------ | ------- | -------------------------- |
  | `: a[bc][bc][bc][bc][bc][bc]<60000 × *>a; cat <vault>` (60 KB, one line) | 0.096 s | **31.151 s**, then the hit |
  | 200 × `a[bc]x6<500 × *>a` (105 KB)                                       | 0.232 s | **34.946 s**               |
  | 1 MB of `a*b ` tokens (ordinary, e.g. minified JS written via Write)     | 4.564 s | 15.381 s                   |

  - The 1 MB case needs no adversarial crafting: a ~2 MB `.js`/`.py` Write would cross 30 s at that rate.
  - A lone 5000-star token is cheap, as asked (0.001 s bare, 0.041 s as `a*…*a`). The cost comes from bracket expansions multiplying token length.

- **Fix direction:**

  1. Normalise before the DP. Collapse runs of `*` to one `*`, which is language-preserving, and bound the work: if `len(basename) * len(pattern) * len(expansions)` exceeds a small budget (a few 10⁴ cells), treat the glob token as a mention (fail closed). No legitimate path glob is 500 characters of wildcards.
  2. Add a whole-scan deadline to `iter_protected_mentions`, well under the client budget (for example 2 s): past it, deny with the evaluation-error rule rather than keep scanning.
  3. Pin both with timing tests: the 60 KB bypass shape must deny in under 1 s.

## Major

### M1 — `enforce_llm_qa` is still not deny-by-default: 19 shapes that main denies are allowed

- **Where:** `.claude/project-handlers/pre_tool_use/enforce_llm_qa.py:141-151` (`_word_names_the_script`: exact word equality or `endswith("/run_all.sh")`) and `:73` (`_PUNCTUATION_CHARS = "(){}!"`, so `<`, `>`, `;`, `|` and `&` stay glued inside a word).

- **Evidence:** `probe_gd_llmqa.py` with `probe_gd_llmqa_cases.json` gives 100 cases, 44 wrong on the branch, and **19 of those are regressions** (DENY on main, ALLOW on branch):

  - **A `-c`/`eval`/remote string where the script is not the LAST thing in the string.** The docstring at `:175-177` admits this limit:

    - `bash -c './scripts/qa/run_all.sh --fast'`
    - `bash -c "./scripts/qa/run_all.sh 2>&1"`
    - `bash -c '…run_all.sh; echo done'`
    - `bash -lc 'cd x && ./scripts/qa/run_all.sh > untracked/scratch/qa.txt 2>&1'`
    - `sh -c '…run_all.sh|cat'`
    - `timeout 900 bash -c '…run_all.sh > … 2>&1'`
    - `eval '…run_all.sh --fast'`, `eval "…run_all.sh;"`
    - `python3 -c 'import subprocess; subprocess.run(["./scripts/qa/run_all.sh"])'`, `python3 -c "import os; os.system('…')"`
    - `ssh localhost '…run_all.sh -v'`, `watch -n 60 '…run_all.sh >/dev/null'`

    `timeout N bash -c '… > file 2>&1'` is an everyday agent shape.

  - **A glued redirection:**

    - `./scripts/qa/run_all.sh>untracked/scratch/qa.txt`
    - `./scripts/qa/run_all.sh>…/qa.txt 2>&1`
    - `./scripts/qa/run_all.sh</dev/null`
    - `bash ./scripts/qa/run_all.sh>x`

  - **Glob or brace on the path:** `bash ./scripts/qa/run_all.sh*`, `bash {scripts/qa/run_all.sh,}`, `bash scripts/qa/{run_all.sh,x}`.

- **What the ledger claims:** the N6 entry says "Fixed by restoring deny-by-default" and "Only the WORD SPLITTING changed from the naive substring check", and release note 15 repeats the invocation description. That is false: main denied any segment CONTAINING the name under a non-consumer head, while the branch denies only an exact word.

- **Also ALLOW on both (pre-existing, not counted as regressions):**

  - globs with no literal `run_all.sh` (`run_all.s?`, `run_all*`, `run_*.sh`);
  - quote splicing (`run_all.s"h"`, `run_all''.sh`) and `$'…\x2e…'`;
  - variables;
  - a data-consumer head that executes: `git bisect run`, `git rebase -x`, `git -c alias.q='!…'`, `rg --pre`, `cat f | bash`, `cat <(…)`;
  - basename laundering: `untracked/scratch/cat <script>`, or a shell function named `cat`.

- **Fix direction** (keeps N6's `--title` fix):

  1. Tokenise with shlex's default punctuation set plus `{}!`, so `>`, `<` and `;` split off glued words.
  2. When a non-consumer segment has a word that CONTAINS the name but is not the script, re-run `_has_real_invocation` on that word as shell text, but ONLY when it is the argument of a string-executor. Those are `-c`/`-lc` of any `*sh`, `eval`, `ssh <host>`, `watch`, `su -c`, `timeout … <shell> -c`, and `python* -c`. For `python -c`, a substring test is fine.
  3. Treat a word that could glob- or brace-expand to the script (fnmatch the word against `run_all.sh` / `*/run_all.sh` after brace expansion) as the script.
  4. Add each regression above as a RED test.

  The `--title` case stays allowed, because `mkplan.bash` is not a string-executor.

### M2 — N10 is only partly closed: `*.secret*` and `*vault_pass*` stay fully open to interior wildcards, and edge+interior tokens escape every pattern

- **Where:**

  - `secret_file_matching.py:884-893`. `_interior_wildcard_mention` skips (a) any token with a leading OR trailing wildcard and (b) any both-edges pattern.
  - `:847`. The DP reads `[`, `!` and `]` as literals.

- **Evidence** (`probe_gd_secret.py` with `probe_gd_secret_cases.json`, output in `probe_gd_secret_out.txt`). Each of these is ALLOW on the branch, ALLOW on main, and globs to the protected name:

  - **`*.secret*`, which protects `.claude/block-words.secret`.** Every interior `?`/`*` spelling is allowed:
    - `cat .claude/block-words.se?ret`, `…s?cret`, `…sec?et`, `…secr?t`, `…*ret`, `…s*et`, `.claude/*.se?ret`, `.claude/b*.s*t`;
    - `config/prod.secre?.env` and 26 more `prod.secret.env` spellings.
    - Score: 6 of 18 `?` spellings and 6 of 18 `*` spellings of `block-words.secret` are allowed.
  - **`*vault_pass*`:** `group_vars/all/va?lt_passwords.yml`, `vault?passwords.yml`, `vault_p*sswords.yml` and 17 more; `*vault?pass*`, `va*_pass*`.
  - **An edge wildcard plus an interior wildcard, against any pattern:** `cat *.vault-pas?word`, `cat ?rod.vault-passw*rd`, and `cat *vault*password`. The last is review 1's P1 case, which this branch set out to close. The m1 predicate does not help: the overlap check still needs the residue's prefix to overlap the stem's suffix, and `.vault-pasword` does not.
  - **Bracket classes that cannot be expanded:** `id_r[!x]a`, `id_r[^x]a`, `id_r[[:alpha:]]a`, `.vault-pas[[:alpha:]]word`, `id_[a-z][a-z]a` (676 members, over the 64 cap). `_expand_bracket_expressions` returns these unexpanded "so the fallback fails CLOSED" (`:430-433`), but the DP then treats the bracket characters as literals, so they fail OPEN.
  - **Brace expansion** is uncovered for every pattern: `.vault-pas{s,}word`, `id_r{s,}a`, `{id_rsa,x}`, `block-words.se{c,}ret`. This is pre-existing and arguably under the documented "string-assembled paths" limit, but the guidance's "Heuristics catch glob tokens" does not say so.

- **What the ledger claims:** its N10 acceptance criterion ("interior `?`, `*` and bracket globs of each shipped protected pattern are denied") is not met for 2 of the 6 shipped patterns. It discloses the both-edges exclusion but not the edge+interior class. The guard's `get_claude_md` limits list mentions neither.

- **Fix direction:**

  - (a) Run `_globs_can_intersect` for edge-open tokens too, against every pattern that is NOT both-edges. For an end-anchored pattern this is exact, and strictly better than the overlap heuristic: `*wordlist` does not intersect `*.vault-password`, so N4 stays fixed.
  - (b) In the DP, treat any unexpanded bracket expression as `?`. That is a superset, so it fails closed.
  - (c) For both-edges patterns, add a filesystem-truth route as well: expand the token against the hook's `cwd` (not the daemon's; compare `_expand_glob_token`'s `Path.cwd()`), with a cap, and deny if any expansion is protected. This has no false positive by construction, and it is the only case that can disclose anything, because a glob that expands to nothing reads nothing.
  - (d) Expand `{a,b}` braces before tokenising. The tokeniser splits on `,`.
  - Pin each with the probe's spellings.

### M3 — `daemon.strict_mode` is inert in the live daemon, so this repository fails OPEN on every handler exception (pre-existing)

- **Where:**

  - `src/claude_code_hooks_daemon/daemon/controller.py:959`: `strict_mode = self._config.strict_mode if self._config else False`.
  - `:162-166`: the constructor comment says "the `config` constructor parameter above is not populated by the real daemon startup path".
  - `:1210`: `get_controller()` builds `DaemonController()` with no config.

- **Live evidence:** `probe_gd_live_payload.json` was fed to this repository's running daemon through `.claude/hooks/pre-tool-use`. The daemon runs main's code, `.claude/hooks-daemon.yaml:8` has `strict_mode: true`, and the payload has `synthetic_source: review`. The payload is a Write whose `.py` content carries a bare `"~/"`, which is N5, still live on main. The response was:

  ```
  {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "Handler exception: ValueError: no path specified\n\n…"}}
  ```

  That is an ALLOW, not the strict-mode `SYSTEM ERROR … blocking for safety` deny. The same thing happened, unprompted, to this reviewer's own Write of `probe_gd_sibling_fuzz.py`.

- **Consequences:**

  - The N5 ledger's severity paragraph and the N11 entry both say "This repository runs `strict_mode: true`, so here the crash denied". That is false.
  - Every guard in every install, including this one, treats an exception as "no match". N11's per-guard wrapper is therefore the ONLY thing standing between a crash and a bypass, and every other SAFETY guard has no such wrapper.

- **Fix direction:**

  - Plumb `config.daemon.strict_mode` into the controller's real startup path (the same narrow-slice DI already used for `ChainConfig`), with a test that goes through `get_controller()`.
  - Independently, adopt review 1's option (b): the chain denies on any exception from a handler tagged `SAFETY`+`BLOCKING`, whatever `strict_mode` says. That also closes m1 below for every guard at once.
  - Record this as a new ledger niggle. It is pre-existing, and it is out of this branch's diff.

## Minor

### m1 — `handle()` is outside the fail-closed wrapper in both guards, so "fails closed on ANY internal exception" is not true

- **Where:** `secret_file_guard.py:407-439` and `project_containment.py:563-598`. The disclosure tracker, `RuleFormatter` and message building run unwrapped after evaluation.
- **Evidence** (`probe_gd_failclosed_out.txt`, through a non-strict chain, each with a GENUINE protected mention or out-of-root write):
  - `RuleFormatter.verbose` raising gives ALLOW (both guards).
  - `get_data_layer` raising gives ALLOW.
  - An unhashable `transcript_path` gives ALLOW with `TypeError: unhashable type: 'list'` (both guards).
- **Reachability:** none of these is agent-reachable today, because `transcript_path` comes from the harness.
- **Fix:** wrap `handle()`'s tail the same way, or rely on the chain-level SAFETY policy (M3), which covers it structurally. Add a chain-level test.

### m2 — `matches()` and `handle()` each re-evaluate, so a transient raise in `matches()` becomes ALLOW

- **Where:** `secret_file_guard.py:392-409` (and the same pattern at `project_containment.py:554-564`).
- **Evidence:** in the probe, an `_evaluate` that raises once and then returns `None` makes the chain return ALLOW. `matches()` said "error, deny", and `handle()` re-evaluated cleanly and allowed.
- **Fix:** cache the evaluation per dispatch (the keyed one-shot bridge `sensitive_content` already uses), or have `handle()` deny whenever either evaluation errored.

### m3 — the sibling audit misses real gaps: the ledger's "no raise path" and "pure regex" claims are incomplete

- **`sensitive_content`:**
  - A Write whose `file_path` contains NUL raises `ValueError: embedded null byte` from `realpath` (`probe_gd_sibling_fuzz.py`: 485 of 12000 fuzzed payloads raised, all NUL paths; `probe_gd_sc_nul_out.txt`). Under M3 that is a fail-open, but a NUL path cannot be written, so it is not exploitable.
  - The Bash surfaces (commit `-m`/`-F`, `gh --body`/`--body-file`) did not raise.
  - The audit also did not consider its subprocess or time costs.
- **`destructive_git`:**
  - It raised nothing in 12000 fuzzed payloads.
  - But "pure regex" omits `strip_inert_spans`, which is super-linear: `git commit` + 40k × `-m x ` (200 KB) takes **99 s**, and 5k × `git commit -F - <<'EOF'…EOF` (110 KB) takes **98 s** (`probe_gd_timing_out.txt`).
  - Every handler shares one 30 s client budget, so any slow handler fails the WHOLE PreToolUse chain open. A crafted command ending in `; git reset --hard` would pass every guard.
- **Status and fix:** pre-existing (the files are unchanged on the branch). Record it as a ledger niggle, alongside B1's class ("a slow handler is a bypass"). Fix it with a per-handler or whole-chain deadline that denies when a SAFETY guard is still running.

### m4 — ledger and release-note claims overstate the fixes

- **N6 entry and release note 15:** "restoring deny-by-default" and "Only the WORD SPLITTING changed" (see M1).
- **N10 entry:** "interior … globs of each shipped protected pattern" (see M2).
- **N11 entry:**
  - "the guard's behaviour is now independent of that global setting": true for evaluation, false for `handle()` (m1).
  - "This repository runs `strict_mode: true`, so here the crash denied": false (M3).
- **N11 sibling audit:** "No raise path found" and "pure regex matching" (see m3).
- **Release note 13:** "A real truncation of any protected file is still denied exactly as before". It was never true for interior wildcards, and it still is not.

## Nit

- **n1 — the error route echoes `str(exc)` unfiltered** (`secret_file_guard.py:281`, `:460`).
  - For the `read` route that breaks Plan 00356's rule (`:147-153`) that a name DISCOVERED by the Grep directory walk must never be echoed. Today no walk-stage exception carries a filename, but an `OSError` from a future stat would.
  - Fix: echo only the exception type and put the message in the log.
- **n2 — pre-existing false positive, hit live while writing this probe:** a `.py` whose content contains `scripts/qa/run_all.s?` is denied as `*.secret*`. The token's 2-character `.s` residue suffix overlaps the stem prefix `.s`.
- **n3 — `enforce_llm_qa` data-consumer heads are matched by basename and include executing verbs:**
  - `git bisect run`, `git rebase -x`, `git -c alias`, `rg --pre`, a symlinked or function `cat`, `cat f | bash`, `cat <(…)`.
  - Pre-existing (P2 in review 1, extended here).
  - Fix: allowlist exact heads (no path prefix), and deny `git bisect run|rebase -x|-c alias.*=!` and `rg --pre` explicitly.
- **n4 — the new N11 tests call `matches()`/`handle()` directly.** None goes through `HandlerChain.execute(..., strict_mode=False)`, which is the property actually claimed. That is why m1 was not caught. Add one chain-level test per guard.

## Probe index (all under `/workspace/untracked/scratch/`)

- `probe_gd_llmqa.py` with `probe_gd_llmqa_cases.json` and `probe_gd_llmqa_main.py`: branch vs main, 100 cases. Output in `probe_gd_llmqa_out.txt`.
- `probe_gd_secret.py` with `probe_gd_secret_cases.json` and `probe_gd_sfm_main.py`: every-position `?`, `*`, `[c]`, `[cQ]`, `{c,}` and `*3` over 8 protected names, 41 extra attack shapes and 30 false-positive checks. Output in `probe_gd_secret_out.txt`.
- `probe_gd_failclosed.py`: 44 chain-level exception and hostile-input cases. Output in `probe_gd_failclosed_out.txt`.
- `probe_gd_timing.py` and `probe_gd_timing_main.py`: DP, `destructive_git` and `enforce_llm_qa` cost. Outputs in `probe_gd_timing_out.txt` and `probe_gd_timing_main_out.txt`.
- `probe_gd_repros.py` with `probe_gd_repros.json`: N4–N6 and m1. Output in `probe_gd_repros_out.txt`.
- `probe_gd_sibling_fuzz.py`: 12000 fuzzed payloads each for `sensitive_content` and `destructive_git`. Output in `probe_gd_sibling_fuzz_out.txt`, plus `probe_gd_sc_nul_out.txt`.
- `probe_gd_live_payload.json`: the synthetic (`synthetic_source: review`) PreToolUse payload for M3. Output in `probe_gd_live_out.json`.

No real protected file was opened, and `.claude/block-words.secret` was never read. Every protected name in the probes is judged as text only.
