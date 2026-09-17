# Callout: a scoped QA scan no longer overwrites the repository's artefact

**Plan**: 00432
**Audience**: operators

`llm_qa` publishes each check's JSON artefact as that check's evidence surface —
it prints the path and a `jq` hint for a reader to query. Seven checkers wrote
that artefact to a fixed path inside the checkout whenever `--json` was passed,
even when the scan had been pointed somewhere else with `--path`, `--root` or
`--repo`. A scoped run therefore replaced a repository-wide verdict with one
about a directory it had never been asked about.

Both directions of that were wrong and only one was visible. A check that passed
could be left holding a scoped FAILURE, which sends a reader hunting a finding
that does not exist. A check that failed could be left holding a scoped PASS,
which masks a real defect — and that is the direction nobody notices. Which one
you got depended on the order things happened to run in.

`check_git_history.py`, `check_skill_references.py`,
`check_python_var_guidance.py`, `check_github_urls.py`,
`check_security_downgrade_flags.py`, `check_eacces_safe_predicates.py` and
`check_authored_path_stat.py` now write their verdict beside what they scanned,
exactly as `check_sensitive_content.py` already did.

Three more take an override that names an input FILE rather than a directory —
`check_fail_open_inventory.py` (`--inventory`),
`check_dangerous_invocation_corpus.py` (`--corpus`) and
`check_declared_invariant_pairs.py` (`--registry`). Two of those still sweep the
repository, so the override changes the DECLARATIONS the sweep is graded
against, and "clean against your registry" is not the fact "clean against a
substitute" establishes. They report beside the file they were pointed at.

An unscoped run — which is every run `llm_qa` itself makes — is unchanged and
still writes `untracked/qa/<check>.json`.

If you script any of these ten with an override and read its JSON afterwards,
read it from the scanned directory (or the input file's directory) rather than
from `untracked/qa/`.
