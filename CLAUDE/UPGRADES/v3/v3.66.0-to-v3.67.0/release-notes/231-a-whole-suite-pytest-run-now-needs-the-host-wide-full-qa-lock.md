# Callout: a whole-suite pytest run now needs the host-wide full-QA lock

**Plan**: 00463
**Audience**: operators

Full QA runs are now serialised across every checkout and worktree on the host by one lock, so concurrent agents no longer each run the whole suite at once. `scripts/qa/run_tests.sh`, `llm_qa.py all`, `run_all.sh` and CI take the lock for you, and the extra-interpreter runs carry its proof. A pytest run that collects more than a quarter of the suite's test files without the lock held is refused, whatever launched it, and `--noconftest` no longer drops that check because `pyproject.toml`'s `addopts` force-loads it. Targeted runs are unaffected. If you invoke a whole-suite pytest by hand, run it through `scripts/qa/run_tests.sh`.
