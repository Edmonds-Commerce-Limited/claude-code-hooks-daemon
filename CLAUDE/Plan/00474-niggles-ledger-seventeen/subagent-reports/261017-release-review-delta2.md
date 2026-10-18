STOPPING BECAUSE: the review is complete and the report is below.

# Code Review: v3.70.0 Step 10 fixes, round 2 (`9d1a522b0..4b3a709e1 -- src/ tests/`)

## Summary

These four fixes add one new fail-open that I count as release-blocking: the Rust lint now lets a typo'd macro, derive or attribute name through. They also add one new wrong denial, for grouped commands in `sensitive_content`, plus two smaller gaps. No handler raises an exception on anything I threw at it. The targeted tests for the touched modules pass (502 tests, 9 files). I did not run the full suite.

Reviewed: 16 files, +449/-30. Found: 1 DEFECT, 3 MINOR, the rest OK.

Probe scripts are in `/workspace/untracked/scratch/rv2-probe/`: `comments.py`, `rust_probe.py` with `typo.rs`, `typo2.rs`, `serde.rs` and `pathtypo.rs`, `msg.py`, and the test output in `pytest.txt`. The baseline comparison used a temporary worktree at 9d1a522b0, which I have since removed.

## DEFECT

### 1. Rust lint (N494): a typo'd std macro, derive or attribute is now let through (confidence 90)
**Location:** `src/claude_code_hooks_daemon/strategies/lint/rust_strategy.py:52-55` and `:218`

The new uncoded pattern `cannot find (attribute|derive macro|attribute macro|macro)` cannot tell an external crate's name apart from a typo. I ran real rustc 1.99.1 on these files:
- `prinln!("hi")` gives `error: cannot find macro 'prinln'`. `is_tool_unavailable_output` returns True, so the write is allowed with only an advisory.
- `#[derive(Debg)]` and `#[tset]` are also allowed.

At 9d1a522b0 and in the shipped release, all three were denied. A careless typo is exactly what this guard is meant to catch.

rustc does label these cases. A typo produces `help: a (derive |attribute )?macro with a similar name exists` and `= note: similarly named ... defined here`. The real serde case (`#[serde]`, `json!`) produces neither.

**Fix:** if the output contains `with a similar name exists`, do not treat it as crate context. Add tests that run on the real rustc output for `prinln!`, `Debg` and `tset` and expect a deny. Today all the tests use hand-written strings, so they cannot catch this.

**Related, older and lower priority:** the N474 coded set already lets `use std::colections::HashMap;` through (E0432, with no similar-name hint). That was accepted design under N474, so I'm noting it rather than counting it here.

## MINOR

### 2. message_files (N496): a whole `( )`/`{ }` group is now judged, so an unrelated term inside it denies (confidence 85)
**Location:** `src/claude_code_hooks_daemon/utils/message_files.py:208-230` (`_statements`) and `:286-288`

- `( cd /tmp/<term> && echo msg > m.txt && git commit -F m.txt )` is now denied. At the baseline it was allowed.
- `{ cd /tmp/<term>; echo msg > m.txt; } && git commit -F m.txt` behaves the same way.

The group stays whole because it writes the named file, which brings back the N364/N341 problem (an unrelated term in a `cd` path) for subshell-wrapped commits.

**Fix:** keep the group whole only when the redirect or pipe that writes the file is outside the group (`} > m.txt`, `) | tee m.txt`). When the write happens inside the group, recurse into the group body's statements. Add both commands above as allow cases.

### 3. message_files: compound commands like `if/fi` and `for/done` still slip through (confidence 80)
`if true; then echo <term>; fi > m.txt; git commit -F m.txt` and `for i in 1; do echo <term>; done > m.txt; ...` are both allowed. This gap is not new; the baseline missed them too. It is the same class as the `{ }` gap N496 fixed, though, so the fix is incomplete.

**Fix:** treat `if/fi`, `for|while|until … done` and `case/esac` as groups in `_statements` (keyword depth alongside bracket depth).

### 4. Comment extractor (N495): an apostrophe can be paired with one inside the comment, which hides it (confidence 75)
**Location:** `src/claude_code_hooks_daemon/strategies/comments/extractor.py:269` and `:272-281`

`_has_closing_quote` searches the whole line, including the comment text after the opener. So in an Edit fragment:
- `fn f(x: &'a str) { /* Prior v1.2: it's …` produces no span. The lifetime `'` pairs with the apostrophe in `it's`.
- `impl<'a> X { /* don't …` and `const r = /"/; /* …` (a JS regex containing a quote) also produce no span.

These are narrow fail-opens in fragment mode only.

**Fix:** only accept a closing `'` that comes before `position`. Treat an unterminated `'` in `line[:position]` as not opening a literal (a Rust lifetime). Add these three lines as tests that expect a span. The existing lifetime test only uses lifetimes that come in pairs.

## OK

- **Extractor string tracking:** I checked double quotes, Go backticks, escaped quotes, the char literals `'"'` and `'/'`, and Python `'''` inside a string. Whole-file mode is unchanged, and the string check only runs on the unterminated fragment path.
- **message_files robustness:** no exceptions from either handler on unbalanced `((( )))`, `{ { {`, a leading or trailing `|`, `-F ""`, `-F ''`, or `$((`. `_reads_stdin_message` cannot hit StopIteration, because every alternative in the pattern needs at least one character. These still deny correctly: `-F "-"`, `|git`, `git -C . commit -F -`, `|&`, `-F <(echo …)`, and `-F /dev/stdin <<<`. These are still allowed: an ordinary `cat > m.txt <<'EOF' … git commit -F m.txt`, `git commit -F - <<'EOF'` followed by an unrelated `ls`, `case … a)`, and an escaped `\(`. When a group is left unbalanced, the extra text it pulls in is only judged if that statement also writes the named file.
- **agent_assets (N497):** the `is_file()` guard also skips FIFOs, which would otherwise block on read, and `OSError` is logged and skipped. The tests cover a directory, a dangling symlink and a read that raises PermissionError.
- **resolve_checker_agent:** handles values that are not strings, and warns once per (value, root). The process-global `_warned_tuned_agents` is never reset, but the tests use a unique value or `tmp_path`, so they stay isolated. The new drift header wording is fine.

## Test quality
- Rust: every test is a hand-written output string. Nothing runs real rustc output for a typo, which is how DEFECT 1 got through.
- message_files: the "unrelated statement" allow cases are all flat commands, with no group that contains a `cd` (MINOR 2).
- Extractor: no test has a single lifetime or a regex containing a quote before an opener (MINOR 4).

## Verdict
REQUEST CHANGES: DEFECT 1 should be fixed before the tag. MINOR 2 to 4 should be filed as plan tasks.