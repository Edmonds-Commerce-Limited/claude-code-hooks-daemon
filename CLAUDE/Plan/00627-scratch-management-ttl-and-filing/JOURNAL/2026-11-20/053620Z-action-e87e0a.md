## 05:36 · action · — — Task 1.7: the read-only scratch-sweep command

Task 1.7 built, test-first: `hooks-daemon scratch-sweep [--json] [--root PATH] [--budget-seconds N] [--max-inodes N]`, a dry run only. There is no `--apply` flag yet (a test pins that).

- `core/scratch_sweep.py`: `run_sweep` judges each entry as soon as it is walked and keeps only its row, never its node list, so memory grows with entries, not inodes. One `WalkBudget` covers the whole run; an entry reached after it is spent still gets a row (STUCK, or LIVE when its root ctime proves it), and the report names how many entries were not walked to the end and why the budget ran out.
- A missing scratch root is reported ("does not exist") and never created. A root that is a link is not followed, and a root that cannot be listed gives an INCOMPLETE report, never a clean empty one.
- The table states "dry run: nothing was changed", counts by verdict, names KEPT, PROTECTED and REFERENCED as not evaluated, carries the repository marker on every row (`repository, not judged` / `-` / `unknown (walk incomplete)`), escapes control characters in names, and is bounded by `scratch.sweep.max_listed`. It prints no content, no delete command and no removal suggestion. `--json` carries every row.
- Notes say once that no birth time is recorded (so the lifetime backstop is unevaluated), and say when no process working directory could be read.
- Defaults are 300 seconds and 5,000,000 inodes. These are flags, not a measurement: the real tree was deliberately not walked in Phase 1.
- `cmd_scratch_sweep` takes `scandir`, `wall_clock`, `budget_clock` and `process_cwds` as keyword parameters for tests. The read-only test runs the table and `--json` over a tree with a link to an outside dummy, a FIFO, a refused directory and a `.git` marker, and compares `snapshot()` of the whole test base, project directory included, before and after.
- `collections.abc.Callable` moved out of the `TYPE_CHECKING` block in `daemon/cli.py`: the new signature uses it at runtime.
