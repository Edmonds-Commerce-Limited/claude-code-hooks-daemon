# Plan 00474 batch AE report (N414, N415, N416)

## N416 (reproduced, fixed)

`_runs_inline_code` flagged any unknown program run with `-e`/`-E`/`-c`/`-r`/`--eval`. Reproduced on `set -e`
(alone, `set -e; cd x; ls`, `set -e; echo hi`), `uniq -c` (coordinator lead confirmed), and also `echo -e`, `rm -r`,
`cp -r`, `ls -r`, `diff -r`, `tr -c`, `cat -e`, `stat -c`, `du -c`, `read -r`, `declare -r`, `pip install -r`.
`set -euo pipefail` did not fire (cluster). Fix: those names added to `_INLINE_CODE_FLAG_TEXT_TOOLS`
(exact basename match; `perl -e`, `foo -c`, `grepx -c` unchanged).

## N415 (fixed)

`_operands_run_in_process` replaces the `ast.walk` plus `_opened_files` pair: one explicit-stack source-order pass
tracks names bound to an opened file and names bound to its text. Covers `fh = open(p); src = fh.read(); exec(src)`,
`Path(p).read_text()`, `with open(p) as fh`, `compile(src, ...)`. A later store drops the name; `+=` keeps it.
Linear; a 3000-binding perf test added.

## N414 (fixed)

1. "needs update"/"needs merge" are nothing-staged; git prints them on stdout so both streams are read.
2. `git diff|format-patch --output[=]F` is a write target (`authored=False`) in `_write_target_tokens`. Conflict
   with the content accessor is real (`get_written_file_paths` feeds linters), so it is NOT in that accessor; the
   staging simulation reads the full scan instead. `format-patch -o DIR` not modelled (unnamed files).
3. `SimpleCommand.reads_input` from the segment's own redirection words; `stdin_fed` uses it plus pipes.

## Verification

Targeted: tests/unit/utils (7507 passed), tests/unit/core (2996), subagent_full_qa_blocker + corpus (1662), commit
gates, sensitive_content, containment, write_protected_paths, post_tool_use (2376): all pass. black clean; pyright
reports only unresolved `pytest` imports (environment). NIGGLES.md N414-N416 updated.
