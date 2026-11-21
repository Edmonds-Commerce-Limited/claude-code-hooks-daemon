## 19:18 · decision · — — Task 3.6: store events file; tar --compare strip-components probe

Task 3.6 unit 1: the store events file.

- `events.jsonl` sits beside `index.jsonl`, because `read_index` refuses the whole store on any line that is not an `ArchiveRecord`. `ArchiveStore.append` and the new `append_event` share `_append_line`, which keeps the torn-tail truncation, and `read_events` parses strictly. An interior bad line raises `StoreRefused`.
- Event kinds are `keep`, `expired` and `adopt`. `adopt` is the P6 intent record, written before the tarball move. Every instant must parse with a zone (`parse_instant`), so a malformed keep `until` refuses the store and can never read as "no keep".
- The pin test's ftruncate surface moved from `append` to `_append_line`. Its behaviour is unchanged.
- Added `test_ctypes_moves_are_only_the_listed_ones`. It pins every reference to `rename_noreplace`, `rename_noreplace_between` and `_RENAMEAT2`, because the deleter AST scan cannot see a ctypes move.

Tar probe for Task 3.7, now permanent tests in `test_scratch_archive_adopt.py`:

- `--compare --gzip --strip-components=1` with no operands FAILS on the root member. It strips to an empty name: "Cannot stat: No such file or directory".
- A top-level file member (too few components) fails the same way.
- Adopt therefore compares with `--no-recursion --no-wildcards --no-unquote --` and every member except the root as an operand. That form is clean on an equal tree, and it sees a changed or a missing file.
- It is silent about a tree file the archive lacks, so the member-set equality check is mandatory.
- Without `--gzip`, tar refuses a gzip stream on stdin.
