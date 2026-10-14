# Report: issue 111, Maven/Gradle source set in tdd_enforcement

No disagreement with the brief. Implemented as specified.

## Red phase

New class `TestMavenGradleSourceSetLayout` in `tests/unit/handlers/test_tdd_enforcement.py`. Before the fix: 6 failed, 1 passed (the "src not followed by main adds nothing" test, correctly green). Key failures:

- `test_sibling_test_source_set_satisfies_the_gate[kotlin|java]`: `AssertionError: assert <Decision.DENY: 'deny'> == 'allow'`
- `test_missing_test_is_still_denied_and_the_location_is_listed[kotlin|java]`: expected `.../src/test/<lang>/com/app/WavWriterTest.<ext>` not in the deny reason
- `test_new_candidate_is_listed_once`, `test_only_the_first_src_segment_is_used`: expected path not in candidates

## Change

- `tdd_enforcement.py`: new `_map_source_set_test_path` (src immediately followed by main -> `<root>/src/test/<rest>/<test filename>`), called once after the casing loop inside the `_TEST_LOCATION_SEPARATE` block via `_append_unique`. It is appended after all existing separate candidates, so no existing candidate moves. It uses the first `src` segment, like the mirror resolvers; a deeper `src` stays in `<rest>`.
- `_map_src_to_tests_mirror` docstring no longer claims the Java layout; `get_claude_md()` lists the new location.
- Release note `057-tdd-enforcement-finds-the-maven-gradle-test-source-set.md`.

## Results

Full `test_tdd_enforcement.py`: 213 passed.
