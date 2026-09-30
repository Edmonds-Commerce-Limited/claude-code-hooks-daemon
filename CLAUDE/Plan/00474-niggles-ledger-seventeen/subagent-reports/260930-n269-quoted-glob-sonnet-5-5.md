# Issue #66 step 2 / N269 / N256: quoted text is not glob-judged (sonnet-5-5)

Branch `worktree-n269-quoted-glob`, on main after step 1 (`b39b8f8fc`).

## Reproductions (through `SecretFileGuardHandler` in a `HandlerChain`, process cwd `/`)

Red before the fix (6 of 36 new tests):

| Command                                                                                 | Result before                                          |
| --------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| `grep -a -n -E "TimeoutExpired\|...\|^tests/.*py:[0-9]+" untracked/scratch/qa-n268.txt` | DENY R-SECRET-BASH-MENTION, token `^tests/.*py:[0-9]+` |
| `grep -o ".*Error.*" somefile`                                                          | DENY, token `.*Error.*`                                |
| `grep -e '.*\.py:[0-9]+' log.txt`, `rg -n '^src/.*py:[0-9]+' log.txt`                   | DENY on the regex token                                |
| `cat > x.md <<'EOF'` with `^tests/.*py:[0-9]+` in the body                              | DENY on the body token                                 |
| same heredoc body holding a truncation of a protected name, file present                | DENY                                                   |

Did NOT reproduce (green before the fix, kept as regression tests): the first grep of the pair
(`FAILED|^.{0,40}_{5,} .* _{5,}`), N269's `grep -E '[a-z_/]+\.py'`, `grep -rn -E 'x[a-z_/]+\.py' src`,
`echo 'see src/**/bar.py and *.py'`, a `gh --body` and an awk pattern, and the `printf` with escaped
backticks (its TooManyToEnumerate was step 1's daemon-cwd base; with payload cwd it does not fire).

The brief's premise was that the deny is the both-edges filesystem enumeration. The reds are not:
the reported glob is `.vault-pass*` (not a both-edges pattern) and the token is a regex, so the deny
comes from the glob-shape heuristics in `_token_mention` (edge overlap, DP intersection), which also
ignore quoting. So the gate covers all of them, not only the `_expand_glob_token` walk.

## Fix (`utils/secret_file_matching.py`, `utils/shell_segmentation.py`)

- `_without_text_operands(command)` returns the command with the quoted operands of a text consumer
  replaced by a placeholder. It runs `strip_inert_spans` first (a `-m` message, and the body of a
  quoted heredoc fed to a data sink; the existing, already-reviewed receiver allowlist), then per
  segment blanks quoted words for `echo`/`printf` (any quoted word), `grep`/`egrep`/`fgrep` and
  `rg` (pattern-position words), `awk` (program words containing no `system`, `getline` or `|`) and
  `gh` (values of `--body/-b/--title/-t/--notes/-n`).
- A word is blanked only if `_is_literal_quoted_word`: it carries a quote, has no unquoted
  `* ? [ $ \` { ~`(escapes, single, ANSI-C and double-quoted contents are masked first), and no command substitution (an unescaped backtick or`$(\`, seen after masking so an escaped backtick
  is literal).
- `_GlobExpansionGate` re-tokenises that view once (only when the view differs from the command,
  and only when a glob-shaped token is judged) with the same four token streams, now factored into
  `_mention_token_stream`. A token that no longer occurs is text only. Text that also appears
  unquoted elsewhere stays judged.
- `_token_mention` takes `expands_globs`; when False, the glob heuristics and the filesystem walk
  are skipped for that token and the literal check (`first_matching_glob` on the word and its
  bracket expansions, then the realpath check) is the only judge.
- `shell_word_spans`: offset form of `iter_shell_words`.

## Every relaxed path

1. A glob-shaped token that occurs only as a quoted operand of the heads above is no longer judged
   by edge overlap, DP intersection or the both-edges walk. Its literal match still fires, so
   `cat '.vault-pass'` and `grep x ".vault-pass"` stay denied (tests).
2. A truncation such as `.vault-pa*` inside `echo '...'`, a grep pattern or a cat-fed heredoc is now
   allowed. Bash prints or searches it and never expands it.
3. awk is the widest trust: a program with `system`, `getline` or `|` is left judged (so
   `awk '/a|b/'` still false-positives), but an awk program with none of them cannot reach the shell.

Not relaxed (each has a test): unquoted words (`cat .vault-pa*`, `echo .vault-pa*`, `grep x .vault-pa*`),
mixed words (`.vault-'pa'*`), words with a substitution (`echo "$(cat .vault-pa*)"`),
`python3 -c`, `bash -c`, `sh -c`, `awk` with `system`, `bash <<'EOF'` (not a data sink), `cat $(echo *)`,
`grep --include GLOB` (both spellings), `rg -g` and `rg -ng`, `find -name`. The content (Write/Edit)
context and the quarantine guard are unchanged.

## Verification

- New: `tests/unit/utils/test_quoted_text_not_enumerated.py` (40 tests).
- Ran with the neighbours: `test_glob_base_payload_cwd.py`, `test_secret_file_matching.py`,
  `test_shell_segmentation.py`, `test_secret_exemptions_reserved_words.py`,
  `test_secret_file_guard.py`, `test_quarantine_artefact_read_guard.py`: 1580 passed.
- Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/184-...md`.

## Unverified

- `llm_qa.py changed --base main --allow-unmapped`: 28/28 passed on a still tree (3326 tests in 40
  files; `shell_segmentation.py` is unmapped, so the full gate must cover it). A first run had
  reformatted two files mid-run and was not recorded; the format was fixed and re-run.
- The 1 MB timing tests in `test_secret_file_guard.py` passed, but the added tokenisation pass on a
  quoted command with something to mask was not separately measured.
- `qa-n268`'s first grep (`FAILED|^.{0,40}_{5,}...`) never went red for me.
