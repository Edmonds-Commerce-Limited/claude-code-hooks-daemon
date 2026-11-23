# Independent delta security review: PR #230 round 2 (N710), commits after 636ce6a69

Scope: `git log 636ce6a69..HEAD` in `untracked/worktrees/fix-n710-secret-guard-glob-later-parts`
(b1580356c, 7dd64527d, 5db5a4339, c681ca2d6), `git diff 636ce6a69..HEAD -- src tests`. Findings 1-3
of the first round (nocaseglob, extglob capture shapes, dotglob via GLOBIGNORE/BASHOPTS, ledgered as
N716) are not re-reported.

## Verdict

**Safe to merge.** The delta introduces no fail-open regression that matters in practice. The
shared listing cache, the shared read budget, the unreadable-directory memo and the new caps all
fail closed in every shape I tried. Earlier findings 4, 5 and 6 are fixed and reproduced as fixed.

There are two findings to ledger:

- **Finding 1 (HIGH, not introduced by the delta).** A POSIX class that is not the first member of
  its bracket is read narrowly, so the guard allows something bash would match. This is the same
  narrowing class as N716 and should be ledgered next to it.
- **Finding 2 (LOW).** A small narrowing that the `[^` translation in this delta does introduce.

## Method

- I read the full source delta in `src/claude_code_hooks_daemon/utils/secret_file_matching.py`.
- I compared bash's own glob expansion (`shopt -s nullglob`, a tmp directory of single-character
  names) against `_component_spells` and `LinkNames._component_matches` for 27 bracket shapes. The
  script is `bracket_probe.py` in my scratch directory.
- I ran end-to-end handler probes (Bash route and Write-script route, with and without the
  protected-file index) on the PR's own `project` fixture, plus a 520-link-holding-directory fixture
  that forces the `LinkNames` route (`named is not None` asserted). These are `test_delta_probe.py`
  and `test_posix_matrix.py`.
- I ran the same matrix against the round-1 source (636ce6a69) and against main (a3486b47b),
  extracted with `git archive`, to tell regression from pre-existing.
- I checked finding 5 in-process against this real repository (527 folders in `Completed/`) with
  the PR source.
- I used dummy tmp_path fixtures only. I read no real protected file.

Scratch: `untracked/scratch/s-20261121T111743Z-0a12d28f/pr230-delta-probes/`.

## Findings

### 1. HIGH, pre-existing (on main and in round 1, not a delta regression): a POSIX class that is not first in its bracket is narrowed

`secret_file_matching.py:4638`. `_component_regex` widens only when the component contains
`_POSIX_BRACKET_OPENERS` (`:4265`, `"[[:"`, `"[[="`, `"[[."`), which means a class that opens the
bracket. A class anywhere else falls through to `fnmatch.translate`. fnmatch closes the set at the
class's own `]`, so the pattern matches almost nothing that bash matches:

| pattern        | bash matches            | `_component_spells` / `LinkNames` match |
| -------------- | ----------------------- | --------------------------------------- |
| `[a[:alpha:]]` | a, b, x, z, A           | none of them                            |
| `[^[:alpha:]]` | `!`, `-`, `1`, `_`, ... | none of them                            |
| `[![:digit:]]` | every non-digit         | none of them                            |
| `[a[:digit:]]` | a, 1                    | none of them                            |

The delta routes `LinkNames` (`:4043`) through `_component_spells`, so it inherits the gap. It
already had the gap through `fnmatchcase`, so this is not new.

**Reproducer.** The decision matrix is identical on head, round 1 and main. Run
`run_matrix.bash` from the scratch directory. With `kit/bin/late` a link to the dummy protected
file:

| command (cwd)                                    | Bash  | Write | Bash, no index | Write, no index |
| ------------------------------------------------ | ----- | ----- | -------------- | --------------- |
| `cat kit/bin/late` (root), control               | deny  | deny  | deny           | deny            |
| `cat kit/[a[:lower:]]in/late` (root)             | deny  | ALLOW | ALLOW          | ALLOW           |
| `cat kit/[![:digit:]]in/late` (root)             | deny  | ALLOW | ALLOW          | ALLOW           |
| `cat kit/bin/[a[:lower:]]ate` (root)             | deny  | ALLOW | ALLOW          | ALLOW           |
| `cat k[a[:lower:]]t/bin/late` (root, first part) | deny  | ALLOW | ALLOW          | ALLOW           |
| `cat [a[:lower:]]in/late` (kit)                  | deny  | ALLOW | ALLOW          | ALLOW           |
| `cd "$D" && cat [a[:lower:]]in/late` (520 links) | ALLOW | ALLOW | ALLOW          | ALLOW           |
| `cd "$D" && cat [![:digit:]]in/late` (520 links) | ALLOW | ALLOW | ALLOW          | ALLOW           |

The leading form `kit/[[:lower:]]in/late` is denied on every route on head; main allowed it. So the
PR fixes the first-member form and misses the rest.

**Fix direction.** Widen to the any-name regex when the component holds a `[:`, `[=` or `[.`
anywhere inside an open bracket expression, not only right after the opening `[`. The same check
belongs in `_token_mention_judged` (`:3481`), which still feeds a raw POSIX class to fnmatch.

### 2. LOW, delta regression: `[^` is rewritten inside a bracket that is already open

`secret_file_matching.py:4643-4650`, `_bash_bracket_negation`, which is
`pattern.replace("[^", "[!")`. Inside an open bracket, `[^` is a literal `[` followed by a literal
`^`. The rewrite turns the `^` into `!`, so the set loses `^`:

- In bash, `[a[^z]` matches `a`, `[`, `^` and `z`. Head matches only `a`, `[` and `z`, plus `!`.
  The same happens with `[[^z]`.
- Unit reproducer (`caret_probe.py`): `LinkNames(["kit/x^/late"]).reaches("x[a[^z]/late")` is False
  on head and True on round 1. `x[[^z]/late` behaves the same.

`LinkNames` (`:4043`) and `_token_mention_judged` (`:3481`) read this correctly before the delta,
because fnmatch kept the `^`. The `expand_word_glob` route already had the gap in round 1.

Exploiting it needs a link or protected name containing `^` and a deliberately odd bracket, so the
severity is low.

**Fix.** Rewrite `^` to `!` only at the position immediately after a bracket-opening `[`. That
means walking the pattern with bracket state (fnmatch's own scanning rules), not running a global
replace.

### 3. INFO: the new mechanisms fail closed (no finding)

I hunted each item in the brief. None of them opens:

- **Cache key coarseness.** Listings, probes and steps are keyed by the literal spelled path
  (`base/component...`), never by the resolved path. So one directory reached from two bases, or
  through a link and plainly, gets separate entries; that costs reads, not correctness. The step
  key also carries `via_link` and `default_semantics`. Probes `test_same_dir_two_bases_one_command`
  (`ls kit/*/notes.txt; cd kit; cat */l*`) and `test_same_dir_via_link_and_plain` both deny.

- **Memoised failures.** An unreadable listing or probe is stored as the `_WordGlobStopped` itself
  and re-raised for every later word, never stored as an empty listing (`_list`, `_probe`). A
  directory that is absent is cached as `[]` or `None`, which is what the old code returned.
  `_leads_to_directory` memoises only definite answers. An entry it cannot classify is asked again
  and stops the walk each time.

- **Budget exhaustion.** `charge()` latches `exhausted`, and `expand_word_glob` (`:4686`) stops
  every later word, including words that only touch cached reads. A stopped expansion reaches the
  guard as `IncompleteScanError` (`required()`), or as `could_be_link` → True. Probe
  `test_exhausted_budget_still_denies_later_word` (cap patched to 3, `ls a/*/x; cat kit/b*/late`)
  denies on both routes.

- **Scope and state leaks.** The state lives in a `ContextVar` that is set and reset by
  `link_scan_scope`. Nested scopes reuse the outer one. No evaluation path uses threads, and there
  are no module-global mutable listings; the only global is the `lru_cache` of compiled regexes,
  which is pure. After a call the scope is `None`. Probe `test_cache_does_not_survive_between_calls`
  (create a link between two identical calls) denies the second call.

- **Routes.** The Bash route and the Write-script route each run inside the guard's own scope
  (`secret_file_guard.py:1438`). The literal fallback (`_literal_finding_or_advisory`) runs after
  that scope has closed. It now opens its own fresh scope (`find_protected_mention_strict`), so a
  budget spent by the main pass cannot starve it into an allow. The fallback also denies any
  unjudged glob through `_gave_up_finding_or_advisory`.

- **Stale listings mid-command.** The guard judges before anything runs. A link the command itself
  creates is no more visible with the cache than without it, so the cache changes nothing here.

- **Last-step links-only shortcut** (`_links_only`, `:4477`). Under a path reached through no link,
  only matches that are links themselves can make `via_link` true, and the final filter keeps only
  those. Returning `[]` for a link-less directory before testing an unreadable pattern is therefore
  equivalent, not narrower.

- **Caps.** A single word at about 4100 listings is denied in 0.04 s; globstar over the same tree
  in 0.05 s. 2000 words with a varied middle component over a 64x64 grid are denied in 0.18 s
  (past 4096 distinct reads). That deny is a fail-closed false positive only for globs spanning
  more than 4096 directories.

  Per-command work is 8 times the old per-word bound of 512 at worst. Listing size per directory
  is still unbounded, as before, and the 5 s deadline is checked between words, not inside one
  expansion. I measured no case near the hook budget, but a single expansion over a few thousand
  very large directories is not interruptible.

### 4. Earlier findings 4, 5 and 6 are fixed

- **Finding 4.** With 520 link-holding directories (`named is not None`), `cd "$D" && cat X` for X
  in `[^z]in/late`, `bin/[^z]ate`, `[^z]ate` and `kit/[^z]in/late` is denied on both routes and
  without the index. Round 1 allowed `[^z]in/late`; see the matrix.
- **Finding 5.** Run in-process against this repository (527 folders in `Completed/`, PR source, no
  index), `grep -l Complete CLAUDE/Plan/Completed/*/PLAN.md` is allowed in 0.01 s.
  `shopt -s globstar; ls CLAUDE/**/PLAN.md` is allowed too. The PR test
  `test_a_link_among_hundreds_of_plain_directories_is_still_denied` covers the deny side.
- **Finding 6.** `ls wide/*/x0* ... wide/*/x1999*` over 300 directories is allowed in 1.28 s on
  this host. Round 1 took 12.7 s and denied it.

## Recommendation

1. Merge.
2. Ledger finding 1 beside N716. It belongs to the same "reader narrower than bash" class, and the
   class detector should cover bracket expressions as a whole, not only their first member.
3. Fix finding 2 together with finding 1. A bracket-aware translator (one that tracks bracket
   state, handles `^`/`!` only at the bracket start, and widens on a class anywhere inside) closes
   both.
