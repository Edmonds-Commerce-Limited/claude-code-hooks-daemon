# Plan 00466 — adversarial review 6 of `worktree-n466-guard-defects` (INCOMPLETE)

**Reviewer**: Opus 5.5, read-only. Target: HEAD `75747c2a`, diff since `daa3dca6`.
Worktree was clean at HEAD when the review ran. No tracked file was edited and
`.claude/block-words.secret` was not opened.

## Verdict: NOT READY. The review is also incomplete.

This review was stopped partway through. The reviewer's session was interrupted
while it was building more bypass-oriented probe content, so the review ended
early. Only the items listed under "What was checked" were done. False
positives, 1 MB timing, fail-closed paths, the gd5 re-run and QA integrity were
**not** checked in this round.

## What was checked

- Read the review-5 report, fix-report Addendum 4, and the source diff
  (`secret_file_guard.py` `_shell_exec_call_literals` and friends;
  `shell_expansion.py` option walk, eval/source/pipe/here-string triggers).
- Ran the two existing nested-shell probes in `/workspace/untracked/scratch/`
  (`probe_gd6_shell.pyprobe`, `probe_gd6_shell2.pyprobe`; outputs are in
  `gd6_out_shell*.txt`). The second probe uses a spelling that resolves only on
  a second, nested parse, so it tests the new code paths directly.
  Result: 80 cases with 33 mismatches, all fail-opens. The first probe's
  spelling is caught by the top-level scan anyway, so it says little about the
  new code (80 cases, 2 mismatches, both class-(d)).

## Findings (described by class; see the probe files for the exact cases)

### MAJOR-1: the round's own claims are incomplete

These cases fall inside what Addendum 4 says the round closed:

- **Option walk**: `_classify_interpreter_option_word` treats any word that
  starts with `+` as a non-option. The walk therefore stops before `-c` when
  bash's `+`-form options come first (for example the `+x` or `+O` forms).
- **Here-string**: the stdin-script route fires only when the here-string is
  the first non-option word. The operand forms bash also accepts (`-` or
  `/dev/stdin` before `<<<`) are missed. `source /dev/stdin <<<` is missed too.
- **Pipe to shell**: the shell word must come straight after the pipe and must
  end the command. The following all go unexamined:
  - the shell with any flag (`-s`, `-x`);
  - the shell behind a wrapper (`sudo`, `env`);
  - an intermediate stage such as `tee`;
  - process substitution given to the shell as its script (`bash <(echo …)`).
- **"Literal producer" is overclaimed**: `printf` (format directives) and
  `echo -e` (escape processing) are joined as though their output were
  literal. The module's doctrine is that anything non-literal fails closed, and
  these do not.

### MAJOR-2: `source <(…)` fails closed on very common benign commands (not probed; found by reading the code)

Step 6 of `_iter_normalised_shell_words` raises `TooManyToEnumerateError` for
any `source`/`.` process substitution whose producer is not `echo`/`printf`.
Everyday shell-completion setup lines of the form `source <(<tool> completion bash)` would therefore be DENIED as internal errors, on the Bash route and in
authored `.sh` content alike. This needs a false-positive probe to confirm. It
also needs a policy decision: fail closed only when a protected stem could be
involved, or accept the FP and document it.

### minor-1: interpreter coverage

`_SHELL_INTERPRETER_BASENAMES` covers sh/bash/zsh/dash/ksh/ash. Other real
shells and versioned binary names are missed: mksh, csh/tcsh, fish, and
`bash5`-style names. Command-running wrappers that take a command string
without an interpreter word are also missed: `script -c`, `su -c`, `flock -c`
and `watch`. Either widen the lists or document these as residuals.

### minor-2: item 3 is regex-on-call-shape (by design); the gaps should be documented

From reading the code:

- The Python route needs the `os.`/`subprocess.` prefix, so from-imports and
  aliases are missed.
- It tests for the substring `shell=True`, so spacing variants are missed.
- It compares argv literals to bare shell names, so absolute interpreter paths
  are missed.
- Shell-exec APIs outside the regex list are not covered at all.
- The Ruby/PHP/Perl/Node lists are similarly partial.
- Go, Rust and Java, and `.cjs`/`.tsx`/`.pm`/`.pyw`, are outside
  `_SCRIPT_EXTENSIONS`. They get no content scan of any kind. That scope came
  from Task 4.3 and is not a regression.
- Interpreter one-liners on the Bash route (`python3 -c` and similar) do not
  get the item-3 treatment, which is inconsistent with the file route.

Addendum 4 already calls this "not a parser". The concrete misses should be
listed as residuals.

### Not defects / class-(d) (already documented in `RESEARCH-read-routes.md:68,71,86`)

Variable indirection, aliases, command substitution feeding `-c`, base64
pipelines, write-then-run of a file named elsewhere, and remote execution
(`ssh`, `docker exec`).

### Verified as holding (deny)

- `-c` behind `env`, `sudo -u`, `nice`, `timeout`, `nohup`, `exec`, `command`.
- Option walk with `-o`, `--rcfile` and clustered `-xec`.
- Three- and four-deep nested quoting; `eval eval`, `builtin eval`,
  `command eval`, and multi-word eval.
- `xargs sh -c` and `find -exec sh -c`.
- Heredocs fed to or piped into bash (quoted, unquoted and `<<-`).
- `source <(echo …)` / `. <(printf …)` with plain literals.

## Not done (must be covered by a follow-up review before READY)

1. A false-positive corpus of 50+ realistic commands and files, including the
   completion-setup shape in MAJOR-2 and the 500-char window pulling unrelated
   literals into the bash-context scan.
2. The 1 MB timing probe (`probe_gd6_timing.pyprobe` exists, not run).
3. The fail-closed paths (depth/byte bounds, injected exceptions).
4. The gd5 probe re-run.
5. QA integrity of the new tests (split-string fixtures accepted per
   precedent; not inspected).
