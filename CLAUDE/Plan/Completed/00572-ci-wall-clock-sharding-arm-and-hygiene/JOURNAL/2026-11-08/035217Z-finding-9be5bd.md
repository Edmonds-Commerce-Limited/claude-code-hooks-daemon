## 03:52 · finding · —   — first sharded nightly: 28.5 min, was 116

The first scheduled nightly on the sharded layout ran as run 42442365191, created 03:21:19 UTC on head 8dd877a6a, and concluded success. Measured with `untracked/scratch/runwall.py`:

- Wall-clock (run created to last job end): 28.5 min.
- Slowest test shard: `Full suite / tests py3.12 unit`, ended at 27.9 min. It was followed by the coverage combine at 28.4 and the QA gate at 28.5. The run finishes when its slowest shard does, plus the combine and gate steps.
- The non-blocking arm64 leg ended at 25.4 min, off the critical path.
- The previous nightly (run 42333472211, 2026-11-07, monolithic layout) took 116.0 min. Its `QA (Python3.12)` job alone ran 115.8 min.

With this, every success criterion holds. Criterion 1 is ticked, and the plan is ready for its completion fact-check and archive.
