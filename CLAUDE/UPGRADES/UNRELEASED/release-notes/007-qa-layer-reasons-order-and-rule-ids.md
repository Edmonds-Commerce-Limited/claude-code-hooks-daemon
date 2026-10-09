# Callout: the QA runner checks suppression reasons, runs detectors first and explains rule IDs

**Plan**: 00484
**Audience**: everyone

`llm_qa.py` gains a gate, `inline_suppressions`, that fails any inline `nosec`, `noqa`, `type: ignore`, `nosemgrep`, `pragma: no cover` or `shellcheck disable` that carries no reason (on the line, in the same comment or in the comment block directly above), so a contributor who keeps a suppression must now say why; there is no baseline file. Every static detector now runs before the test suite and the other runners, and once a detector has failed the runners' lines are marked `NOT MEANINGFUL: detector failed` and left out of the pass count (every tool still runs), so a green `tests` line beside a red detector no longer reads as a pass. A failing tool's summary now names its first five findings with their rule IDs and the absolute path of the full report, `llm_qa.py --explain <ID>` prints what any `scripts/qa` rule ID means and how to fix it (`--explain` alone lists them), and `check_magic_values.py`, `audit_error_hiding.py` and `audit_shell.py` accept `--path FILE` to judge one file.
