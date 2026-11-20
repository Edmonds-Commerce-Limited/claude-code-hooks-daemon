## 19:48 · decision · —

Task 3.7 (proof P6, adopt a tarball beside its original) built test-first in two commits.

Unit 1 (8cfbe3915): restore accepts the P6 `name/...` layout. Each layout now requires one prefix style for every header (a mixture is refused), and the stale `p6-layout` refusal test was replaced by real round-trips (gzip, plain, xz which skips here because xz is not installed) plus truthful-count refusals. The compression sniff is a shared pack helper (`compression_of`, `compression_flags`, `tarfile_mode`, `require_decompressor`): gzip and xz by magic, plain tar by `ustar` at offset 257, anything else refused; tar and tarfile get the explicit choice, never `r|*`. `batched_compare` takes extra flags. An adopted root's archived mode is restored after the move.

Unit 2 (4e9382afc): `core/scratch_archive_adopt.py`. All checks before any write; the compare is the probe's working form (every member but the root, `--strip-components=1 --no-recursion --no-wildcards --no-unquote`) plus member-set equality plus SHA-256 re-read after the compare. An entry holding only its root is proved by the member set alone, since a compare with no operands hits the stripped-root "Cannot stat". Order: adopt event, no-replace move, moved-file identity and digest check (a swapped file is moved back, or left named by its event as AdoptStuck), record. `discard_unrecorded` now refuses an adopted id.

New move surfaces pinned: `scratch_archive_adopt._move_in` and `_move_back` (`rename_noreplace_between`). No new deletion surface. Nothing wired to the CLI.

Five OPEN rows added to DESIGN.md section 13 as Task 3.8 preconditions: the three Task 3.6 follow-ups (removal's proof not reading the events file, crash-leftover `.restoring-*` not reclaimed, misleading RestoreRefused after a successful move), plus removal's re-verify not reading adopted archives, and finishing an adoption a crash left unrecorded.
