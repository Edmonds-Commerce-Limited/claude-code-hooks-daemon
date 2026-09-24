# Niggles ledger sixteen: write-ups

Newest first. Each entry says how it was found, why it happens, and the
candidate remedies.

### N11 — any exception in `secret_file_guard.matches()` lets the call through unless `strict_mode` is on

**Found by the 00466 review** (major M4, `subagent-reports/260924-n466-review-opus-5-5.md`). N5's crash was the second time an exception in this guard's `matches()` skipped the guard entirely; Plan 00357 was the first. Under the default `strict_mode: false` the chain logs the exception and allows the call. This repository runs `strict_mode: true`, so here the crash denied, but a client on the defaults fails open. One raise path is still live after N5, though it isn't exploitable: a file path containing a NUL byte.

**Candidate remedy:** make the guard structurally fail closed. A raise anywhere in its match or route computation becomes a deny naming the internal error, whatever the global `strict_mode`, because a protected-read guard that fails open is worse than a false deny. Pin it with a test that injects an exception at each stage. Then audit the other security guards that should behave the same (`sensitive_content`, `project_containment`, the destructive-git rules) and decide each one explicitly.

### N10 — a wildcard in the middle of a protected filename gets past `secret_file_guard`

**Found by the 00466 review** as a pre-existing problem on main, security-relevant. `cat .vault-pas?word` and `cat prod.vault-passw*rd` name a protected file through a glob the shell expands, and the guard does not deny them. The mention scan handles a leading or trailing wildcard (the N4 overlap logic), but not a `?`, `*` or `[...]` inside the name.

**Candidate remedy:** treat any shell-glob token as a pattern, and deny when the pattern could match a protected name. Compare against the protected basenames and stems, or expand it against the directory when that exists. Keep it no looser than the N4 rule. RED tests: interior `?`, `*` and bracket globs of each shipped protected pattern are denied, while unrelated globs such as `*.py` and `src/*.md` are allowed.

### N9 — `docs_qa` judges gitignored markdown, so installing a Claude Code plugin fails local full QA

**Found by the coordinator** right after installing the Defence Before Fix plugin at project scope (Plan 00467). In this container Claude Code's config directory is `.claude/ccy/`, so the plugin's cache (`.claude/ccy/plugins/cache/...`) and marketplace clone (`.claude/ccy/plugins/marketplaces/...`) land inside the repository. Both are gitignored (`.claude/ccy/.gitignore:3: *`). `llm_qa.py docs_qa` then reported 12 `source-tree-markdown` findings, one per vendored spec file, and the tool FAILED. It reported 0 findings at batch A's gate, before the install. CI does not see this, because a fresh checkout has no `.claude/ccy/`. Every local full QA run, including the coordinator's integration gate, now fails on files that are not part of the project.

The docs corpus walks the filesystem without honouring `.gitignore` (`docs_qa/corpus.py`; it already special-cases `.claude/ccy/CLAUDE.md`, lines 149 and 421).

**Candidate remedy:** the corpus considers only tracked files plus untracked files that are NOT ignored, i.e. `git ls-files --cached --others --exclude-standard`, with a defined fallback outside a git repository. Keep any deliberate inclusion that is ignored but meant to be scanned explicit and named. RED test: a gitignored markdown file under a source-like directory produces no finding, and a tracked one still does. Audit the other QA corpora (plan_qa, doc_snippets, doc_truth, repo_hygiene, sensitive_content, british_english) for the same filesystem-walk assumption, and pin the class.

### N8 — `reference_repo_freshness` says BLOCKED on a call it allows

**Found by the coordinator.** A Read of a fresh clone under `untracked/repos/` was denied (`R-REFERENCE-REPO-NOT-VERIFIED`), as the default `block_once` posture intends. The next command that named that clone, a `mv` moving it to `untracked/work/`, RAN. Its hook context still opened with `BLOCKED [R-REFERENCE-REPO-NOT-VERIFIED]: a read of a governed reference clone...`.

`_verdict()` (`handlers/pre_tool_use/reference_repo_freshness.py:575-576`) returns `GatingResult(decision=Decision.ALLOW, context=[message])` for a repeat in `block_once` mode, and for `advise` mode at :565. `message` is the verbose DENY rendering (`self._formatter.verbose(rule)`), which starts with `BLOCKED`. An agent reading its context is therefore told a call was blocked when it ran. It either retries something that already happened, or learns that "BLOCKED" means nothing.

**Candidate remedy:** the allow paths render the advisory form of the rule (no `BLOCKED` prefix, same detail and fix line). Pin it with a test for each mode (`advise`, a `block_once` repeat): an ALLOW result's context never contains the deny headline. Then audit every other handler that returns `Decision.ALLOW` with a context built by the verbose deny formatter (`block_once` handlers especially, such as `lsp_enforcement`), and pin the class with a test that walks every handler's acceptance tests or allow paths.

### N7 — the regenerated CLAUDE.md guidance block is not deterministic, so every daemon restart can commit a reorder

**Found by the coordinator** at the batch A merge. The integration worktree's daemon had just regenerated CLAUDE.md, and that result was committed. The main checkout's daemon then restarted on the same tree and auto-committed `ce31d6d8` ("Auto: hooks daemon regenerated CLAUDE.md handler guidance"). The commit changed 18 lines both ways. Every change is the same handler markers in a new order: `tool-disable-advisor`, `project-handler-load-checker`, `hook-registration-checker`, `routine-qa-sweep` and `secret-file-hygiene-checker` among them. The earlier 00462 merge restart committed `6359ad0c`, changing 83 lines both ways, with the same shape.

`ClaudeMdInjector._collect_tiers()` emits handlers in the order of `self._handlers` (`core/claude_md_injector.py:642`) and never sorts them. Two daemons on one tree can therefore produce different blocks, apparently for handlers that share a priority. The results:

- A spurious auto-commit on restart.
- A CLAUDE.md conflict whenever two branches merge. This happened twice while building batch A.
- A worktree's regenerated block that never matches main's.

**Candidate remedy:** emit in a total order that depends only on the handler set, for example tier, then priority, then handler name. Test that two injector runs over the same handlers in shuffled input order produce byte-identical blocks. Check whether `HOOKS-DAEMON.md` generation has the same tie problem, and give it the same fix.

### N6 — `enforce_llm_qa` denies a PROSE mention of `run_all.sh` inside an unrelated command's own argument

**Found by the coordinator**, live: a `CLAUDE/Plan/mkplan.bash --journal ... --title "..."` journal entry was denied under `R-NPM...`-style project-handler
enforcement, naming `run_all.sh`, even though the runner's name appeared only
inside the quoted `--title` prose, not as anything the command would execute.

**Cause** (`.claude/project-handlers/pre_tool_use/enforce_llm_qa.py`,
`_is_inspection_only` and its call site in `matches()`, pre-fix): the handler
split a command into top-level segments, then for any segment CONTAINING the
substring `run_all.sh` ANYWHERE, checked only the segment's OWN leading word
against an inspection/VCS allowlist (`cat`, `grep`, `git`, ...). A word
appearing inside a quoted argument to an unrelated command was invisible to
that check — the leading word of `CLAUDE/Plan/mkplan.bash --title "... run_all.sh ..."` is `mkplan.bash`, which is on no allowlist, so the whole segment was
treated as a potential invocation and denied. The same shape denied a `gh issue comment --body "... run_all.sh ..."` (a plain prose mention) and a
`bash scripts/qa/run_tests.sh; echo "see run_all.sh notes"` compound (a
DIFFERENT script's wrapper plus unrelated prose in the next segment).

**Remedy (implemented)**: replaced the substring-plus-allowlist check with a
`shlex`-based real-invocation detector (`_has_real_invocation` /
`_segment_executes_script`), reusing this project's already-established
`shlex.split()` + `try/except ValueError` tokenisation pattern
(`project_containment.py`'s `_tokenise`) rather than a third hand-rolled
parser. A segment now matches only when the script is named at the command's
own HEAD, or as an argument to a wrapper (`bash`/`sh`/`env`/`timeout`/`nice`/
`exec`) — recursing into a wrapper's `-c` subshell argument and into any
`$(...)`/backtick substitution's inner text, since bash runs both before the
rest of the line. A prose word that merely CONTAINS the script's name inside a
longer shlex token (a whole quoted `--title "..."` phrase is ONE token) is no
longer conflated with a token that IS the script's path. This also let the
old `_INSPECTION_COMMANDS`/`_VCS_COMMANDS` allowlists be deleted outright
(YAGNI): a command whose head is not a wrapper and does not itself name the
script now correctly can't execute it, with no enumerated list of safe verbs
needed. A segment that can't be tokenised safely falls back to the prior
conservative substring check (deny), so an unparsed edge case still fails
closed rather than opening a bypass.

One pre-existing acceptance-test fixture (`get_acceptance_tests()`, "Block
run_all.sh") turned out to be the SAME false-positive class in miniature: it
used `echo "./scripts/qa/run_all.sh"` as a "safe to execute" DENY case, which
only denied because `echo` happened to be absent from the old allowlist — a
prose mention, not an invocation. Replaced with `bash -n scripts/qa/run_all.sh`
(a genuine wrapper-invocation shape; `-n` keeps it parse-only and harmless if
the block ever regresses).

RED tests (confirmed failing pre-fix, passing after), added to
`.claude/project-handlers/pre_tool_use/test_enforce_llm_qa.py`:
`test_does_not_match_a_prose_mention_in_a_quoted_title_flag` (the exact live
shape) and `test_does_not_match_an_unrelated_wrapper_invocation`. Four
companion "must still deny" regression guards were written alongside (already
passing pre-fix, kept as pins): a `gh --body` prose mention, `cd ... && ./run_all.sh`, `sh -c './scripts/qa/run_all.sh'`, and a bare `$(./run_all.sh)`
substitution. All 41 tests in that file pass, and all 198 project-handler
tests pass (`bin/hooks-daemon test-project-handlers --verbose`).

### N5 — SECURITY FAIL-OPEN: an empty path-mention token crashes `secret_file_guard.matches()`, skipping the whole guard for that write

**Found by 00463's agent** live, reported to the coordinator; reproduced here
via the daemon after the coordinator saved the exact triggering `tool_input`s
and replayed them for a full traceback. Three Edits to
`subagent_full_qa_blocker.py` (a WIP file inside a worktree) each drew
`Handler exception: ValueError: no path specified` as PreToolUse:Edit
context. The added content declared tuples of shell/Python path-expansion
operands, e.g. `_HOME_PREFIXES: Final[tuple[str, ...]] = ("~/", "$HOME/", "${HOME}/", "$PWD/", "${PWD}/")` and `_UNSEEN_CD_PREFIXES: Final[tuple[str, ...]] = ("$", "~", "` `")`.

**Cause**, traced through a live daemon log:
`chain.py:431 handler.matches (block-secret-file-read)` →
`secret_file_guard.py _matched_pattern_and_route` → `_script_content_mention`
→ `secret_file_matching.py find_protected_mention_detail` →
`iter_protected_mentions` → `_token_mention`: `path_matches_globs(form, ...)`
with `form == ""` → `path_exclusion.py _candidate_paths`:
`os.path.relpath(raw, root)` with `raw == ""` →
`ValueError: no path specified` (`os.path.relpath` rejects an empty PATH
argument outright, regardless of `start`).

The empty `form` came from `_normalised_token_forms`: for a token EQUAL to
one of `_HOME_PREFIXES` (e.g. the tokeniser isolates `"~/"` cleanly out of a
quoted Python string literal, since neither `~` nor `/` is a token
delimiter), `token[len(prefix):]` on a token exactly as long as the prefix is
`""`. That empty spelling then reached the glob matcher, which had never been
asked to answer for an empty path before.

**Severity — this is a fail-OPEN, not noise.** The exception is raised inside
`matches()`, not `handle()`. The daemon's per-handler catch
(`core/chain.py`) is non-strict by default for this path: it logs the
exception as context and moves on to the NEXT handler, treating this one as
"did not match". So a Write/Edit whose content contains an empty-yielding
operand token SKIPS `secret_file_guard` ENTIRELY for that call — including
any genuine protected-path mention elsewhere in the same content. An agent
could not have engineered this to bypass the guard (nothing here is a
crafted evasion — `~/`, `$PWD/` and friends are ordinary path-handling
vocabulary), but a real protected mention sitting anywhere in the same
Write/Edit as one of these operands would have gone undetected.

**Remedy (implemented), both layers per the coordinator's instruction:**

(a) `_normalised_token_forms`
(`src/claude_code_hooks_daemon/utils/secret_file_matching.py`) never emits an
empty form: the home/pwd-prefix-stripping branch now requires
`len(token) > len(prefix)`, the same non-empty guard shape the adjacent
`./`-stripping branch already used.

(b) `_candidate_paths` (`src/claude_code_hooks_daemon/utils/path_exclusion.py`)
is now TOTAL on an empty `file_path`: it returns early with a single empty
candidate (matching nothing) rather than calling `os.path.relpath` at all —
defence in depth, so no OTHER caller of `path_matches_globs`/`is_path_excluded`
can hit the same crash by a different route.

(c) Fail-safe pinned with a RED test: content carrying BOTH a home-prefix
token and a genuine protected mention (`id_rsa`) elsewhere in the same blob
must still deny — confirmed failing (crashing) before the fix, passing
after. A corpus test iterates every operand shape from the live payloads
(alone, inside a quoted string, inside a call) asserting the mention scan
never raises.

RED tests: `tests/unit/utils/test_path_exclusion.py ::TestEmptyAndNoMatch::test_empty_file_path_with_a_project_root_does_not_raise`
and `tests/unit/utils/test_secret_file_matching.py ::TestBareHomePrefixTokenDoesNotCrash` (6 tests). Full
`test_secret_file_matching.py` (196), `test_path_exclusion.py` (55) and
`test_secret_file_guard.py` (76) pass — 327 total.

### N4 — `secret_file_guard`'s leading-wildcard overlap check denies an unrelated Python splat expression as `*.vault-password`

**Found by a peer agent** working in a worktree, reported to the coordinator;
reproduced independently here before fixing (per instruction, its account was
treated as a hypothesis, not a fact). An Edit adding the Python expression
`*words[position + 1 :]` (a plain unpacking of a slice, e.g. `rest = [words[0], *words[position + 1 :]]`) to a `.py` file was denied under
`R-SECRET-SCRIPT-AUTHOR`, naming the protected glob `*.vault-password`. The
same shape denies the equivalent Bash mention (`cat 'rest = [words[0], *words[position + 1 :]]'`) and, stripped of any bracket at all, a bare
`def f(*wordlist): pass` or `call(*wordlist)`.

**Cause** (`src/claude_code_hooks_daemon/utils/secret_file_matching.py`,
`_glob_token_overlaps_stem` and its call site in `_token_mention`): the
tokeniser splits `*words[position + 1 :]` on whitespace into `*words[position`,
`+`, `1` and `:]` (`_tokenise`'s delimiter set includes space but not `[`/`]`/
`:`/`+`). The first token starts with a literal `*` (Python's unpacking
operator, not a shell glob), so `_has_leading_wildcard` reports it as a
leading-wildcard token. Its literal residue, after stripping `*`/`[`, is
`wordsposition`. The leading-wildcard branch of `_glob_token_overlaps_stem`
then checks whether the STEM's suffix overlaps the residue's PREFIX
(`_suffix_prefix_overlap_length`) — and `.vault-password`'s last 4 characters
(`word`, from "pass-**word**") exactly equal `wordsposition`'s first 4
characters, clearing the 2-char minimum. The same coincidence reproduces
without any bracket: `*wordlist`'s residue `wordlist` shares the same 4-char
`word` overlap.

That overlap check was correct for the case it was built for — a token like
`*passXXX` against a BOTH-EDGES pattern (`*vault_pass*`), where the pattern's
own trailing wildcard can absorb whatever the token's residue doesn't cover
after the overlap. It was applied uniformly to every leading-wildcard pattern
though, including `*.vault-password` — the ONLY pattern in the shipped
defaults with a leading wildcard and NO trailing one. For such a pattern a
matching real filename must end EXACTLY at the stem (nothing can follow), so
a token with no trailing wildcard of its own (as `*words[position`/`*wordlist`
both are — the whole point of a leading-only token) can only be a genuine
truncation if its ENTIRE residue is a literal suffix of the stem, not merely a
short boundary coincidence. That stronger case was already covered by the
pre-existing substring+fnmatch check earlier in the same function (confirmed:
no test in the existing suite exercises a leading-only token against a
leading-only pattern needing the overlap branch specifically) — so the overlap
branch contributed nothing there but this false positive.

**Remedy** (implemented): `_glob_token_overlaps_stem` takes a new `pattern_has_trailing_wildcard` parameter; its leading-wildcard branch now also requires `pattern_has_trailing_wildcard or stem_basename.endswith(residue)` before counting the overlap as a mention. The call site passes `_has_trailing_wildcard(pattern)` — a function already used elsewhere in the same module for the token's own edges, reused here for the pattern's. This is parametrised on the pattern's own shape, not special-cased to `.vault-password`, so any future or project-configured leading-wildcard-only glob is covered the same way. RED tests (confirmed failing pre-fix, passing after): `TestBashMentionsProtectedPath::test_leading_wildcard_python_splat_operator_is_not_matched` (the reported shape plus the bracket-free forms) and a paired `..._full_suffix_of_anchored_stem_still_matched` regression guard proving a genuine truncation of an anchored pattern (`*password`, `*ult-password` against `*.vault-password`) still denies. Full `test_secret_file_matching.py` (190 tests) and `test_secret_file_guard.py` (76 tests) pass.

### N3 — `goal_injection` treats any edit of an In Progress plan as the plan starting

**Found by the coordinator**, live. The supervisor had set the goal to Plan
00461\. The coordinator then added a table row to this ledger's PLAN.md. That
edit drew `⚠️ GOAL DISPLACED: ... Plan(s) 00461 is now superseded by Plan 00466's goal`, and the handler wrote a goal-intent signal for 00466.

The handler's docstring says it writes the signal "when a plan flips to In
Progress". `handle()` never looks for a flip. It reads the PLAN.md from disk
after the write, and `_STATUS_IN_PROGRESS_RE` matches any plan whose
**Status** line reads In Progress. The once-per-plan-per-session latch is
the only limit. So the first Write or Edit in a session to any plan that is
already In Progress fires, however unrelated to its status. That includes a
ledger row, a task tick or a typo fix. The results:

- The supervisor receives a goal for a plan nobody started. For a rolling
  ledger that goal cannot complete.
- The displacement advisory tells the session that the goal it is really
  working was superseded.
- The ledger now tracks the edited plan as owed work, and the Stop hook
  challenges stops on its behalf.

**Candidate remedy:** fire only on a real transition. For `Edit`, the
`old_string` → `new_string` pair changes the **Status** line to In Progress.
For `Write`, the file's previous content (for example the pre-write copy
`write_clobber_guard` already reasons about, or git's `HEAD` version) did
not read In Progress, or the file is new. An edit that leaves an In
Progress status unchanged emits nothing and displaces nothing. RED tests:
an Edit that adds a table row to an In Progress plan emits no signal and no
advisory; an Edit flipping Not Started to In Progress still emits; a Write
creating a new In Progress plan still emits.

### N2 — `setup_worktree.sh` tells every agent to run the full suite through `run_all.sh`

**Found by the coordinator** when it set up an integration worktree.
`scripts/setup_worktree.sh` ends with an "Agent prompt template" whose last
line is `Run ./scripts/qa/run_all.sh before committing.`, and a "Run QA" hint
with the same command (lines 389 and 400). Step 7 also treats `run_all.sh` as
the QA entry point (line 343). Two things are wrong with that:

- `enforce_llm_qa` denies `run_all.sh`; `./scripts/qa/llm_qa.py all` is the
  only full-QA entry. An agent that follows the template is denied at once.
- Plan 00463 makes full QA a coordinator gate. A sub-agent runs targeted QA
  only, and the coordinator runs one full pass over the batch of merged
  branches. The template sends every sub-agent to run the full suite, which
  is the concurrent full QA that 00463 exists to stop.

**Candidate remedy:** the template names targeted QA (`llm_qa.py <tools>`
plus the touched tests) and says that full QA is the coordinator's
integration gate. The "Run QA" hint and Step 7 name `llm_qa.py`. A test
checks that the script names no denied QA entry point.

**Graduated to Plan 00463**, which owns the sub-agent QA policy.

### N1 — `resolve_venv_python`'s fallback accepts a venv interpreter that cannot run on this host

**Found by Plan 00457's agent** (#55; recorded in 00457's JOURNAL as a
finding). When the slug-exact venv is absent, `resolve_venv_python` falls
back to globbing `untracked/venv-*/bin/python`, and accepts a candidate on
its executable bit alone. #55 is about a host whose only venv was built
inside a container. That interpreter may be for another architecture or
libc, or may symlink into a path that exists only in the container. It is
executable but cannot run. The fallback would then report "resolved", so
`bin/hooks-daemon` never reaches `_run_venv_free_verb` (the `repair` and
`signal` arms from Plans 00456 and 00457). It would fail when it runs the
interpreter, not with the clear venv-missing path. No test covers it on
either side of #53 or #55.

**Candidate remedies:**

1. The fallback proves a candidate RUNS, e.g.
   `"$candidate" -c 'import sys'` with a short bound, before accepting it.
   It moves on to the next candidate, then to the venv-free path, on
   failure. Test it with a fake executable that exits non-zero, and with a
   dangling symlink.
2. At minimum, a candidate that fails at exec time produces a message
   naming the venv it tried and the `repair` command, not a raw exec error.
