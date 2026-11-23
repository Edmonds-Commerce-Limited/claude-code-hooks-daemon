# PR 230 unit-leg failure (run 45254007557)

**Verdict: (a) real and branch-caused, but both are host-dependent TESTS, not product
defects.** Each failed on both the py3.11 unit fallback leg and the arm64 leg; locally
(uid 0, smaller checkout) both passed.

## Failing tests

1. `tests/unit/handlers/pre_tool_use/test_secret_file_guard_glob_later_parts.py::TestShapesTheMatcherMustNotNarrow::test_a_glob_after_a_literal_variable_is_judged_like_its_literal`
   - globbed `(DENY, DENY)` against literal `(ALLOW, ALLOW)`; stop reason `a globbed word passes a directory or an entry that cannot be read`.
   - Cause: the guard also judges `$D/*/late` with `$D` empty, i.e. `/*/late` on the
     REAL host root. It probes `/<each top-level dir>/late`. On a non-root runner,
     `lstat('/root/late')` is EACCES, and `_GlobListings._probe` fails closed. The
     literal `$D/bin/late` only probes `/bin/late` (ENOENT), so it stays allowed.
   - Reproduced as root with a plugin that raises EACCES for `lstat('/root/...')`.
   - Fix (test): lead both words with `./` so the empty-variable view stays inside
     the tmp project. Green under the EACCES plugin.
2. `tests/unit/handlers/test_safety_handlers_hostile_input_performance.py::TestCombinatorialSmallInputShapesStayLinear::test_bash_command[star_star_slash_star]`
   - At 24 the result is `(True, 'deny', True)`; at 3 it is `(True, 'allow', False)`.
     The stop reason is `a globbed word matches more than the guard follows`
     (GLOB_LISTING_CAP).
   - Cause: the input carries no cwd, so `**/***/*...` walks the process cwd, which
     is the checkout. Whether the size-24 walk crosses the 4096-listing cap depends on
     how many directories the host's checkout holds. This is the same class as the
     N281 scan deadline.
   - Reproduced locally by lowering GLOB_LISTING_CAP to 600 or 1500. Fix (test):
     `monkeypatch.chdir(tmp_path)` in `test_bash_command`. Green at caps 50, 600
     and 1500.

## Product changes: none

The fail-closed reading of EACCES in `_probe` matches the literal path's own N663
rule: `_realpath_if_resolvable` raises ResolutionFailedError on a non-ENOENT stat
failure.

## Follow-ups for the coordinator (not fixed here)

- **Usability.** For a non-root user, `cat $VAR/*/name` (a pattern in the middle and
  a literal last part) is now always denied: the empty-`$VAR` view probes
  `/root/name`. It is fail-closed and consistent with `cat /root/name`, but it is a
  new false positive that the branch introduces. Either accept it or treat an EACCES
  probe as "no match", which is what bash's own glob does. If the second, it needs a
  security delta review.
- **Latent sibling.** `test_bash_command[double_star_glob]` (`/**/` repeated) walks
  the real `/`, and flips at small caps (600). It passes CI at the real cap of 4096,
  and chdir cannot help it, since the path is absolute.
- **Observed, outside this change.** `D=kit; cat $D/bin/late` is ALLOWED even
  though `kit/bin/late` links to a protected file: the guard does not follow `D=kit`.
  The test only asserts that the glob is judged the same as the literal.
