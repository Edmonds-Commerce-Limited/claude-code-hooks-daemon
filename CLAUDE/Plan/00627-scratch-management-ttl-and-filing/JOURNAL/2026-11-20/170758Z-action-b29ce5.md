## 17:07 · action · — — F-BYPS 3: a sub-root reference names every entry

Security review F-BYPS 3 fixed in `core/scratch_references.py`, per the coordinator's ruling on the handoff's open question.

- For a root deeper than `untracked/<name>` (`names_whole_root`), the git grep pattern is `<root>[class]*`. A match whose stripped or `normpath` form equals the root itself is recorded in `ReferenceSet.root_sites`, which `for_entry` adds to every entry's sites (deduplicated). A path under the root still names its own entry.
- A mention of an ANCESTOR (`untracked/scratch/`, `untracked/`) names nothing, and neither does a sibling sharing the prefix (`untracked/scratch/subway/x`). This keeps sub-root sweeps usable in a repo whose docs cite `untracked/scratch/` everywhere (the handoff's alternative design would have made every sub-root sweep REFERENCED).
- Default (top-level) root unchanged; test pins that a bare `untracked/scratch/` mention protects nothing.
- Tests: `TestSubRoot` in test_scratch_references.py (root forms, ancestor/sibling, dedup, default root) and two sweep-level tests (the reviewer's probe shape: `qa-findings.md`/`run.log` under `--root untracked/scratch/sub` are REFERENCED; an ancestor mention leaves them DISPOSABLE). DESIGN 3.4 updated.
