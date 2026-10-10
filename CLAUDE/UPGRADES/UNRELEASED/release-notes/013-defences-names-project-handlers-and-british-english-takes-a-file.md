# Callout: defences lists a runnable probe command for project handlers, and one more checker takes a file

**Plan**: 00484
**Audience**: operators

`hooks-daemon defences` now gives a project handler of yours the same `--only` probe command as a bundled one. Before, a project handler's `detector_entry_point` was null because it was filed under an event the probe does not know. It now names the handler's real event and config key, and `hooks-daemon probe <event> --only <that key>` accepts it.

`probe --only` also takes the handler name with dashes (`my-handler`) wherever it is sent, not only at the command line.

`scripts/qa/check_british_english.py --path FILE` judges one document as the whole-tree run would and writes no artefact. A file the tree run skips (a plan, a release record, a fixture) is refused rather than passed. Nothing to do on upgrade.
