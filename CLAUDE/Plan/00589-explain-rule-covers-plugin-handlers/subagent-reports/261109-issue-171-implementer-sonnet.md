# Plan 00589 Task 1.1 report (GitHub #171)

RED (before the change): 5 failed, 49 passed in the two target files. Failures:
`assert None is not None` (plugin rule not found), `assert 0 == 1` (handler not listed),
failed-plugin test (no log record), and two CLI tests `assert 1 == 0` (explain-rule / explain-handler exit 1).
GREEN: 101 passed across tests/unit/rule_explain, test_cli_explain_rule.py, test_cli_defences.py.

Change: `rule_explain/lookup.py` gains `_plugin_handler_classes()` (uses
`PluginLoader.load_from_plugins_config(config.plugins, project_root)`, logs and returns [] on any load failure),
merged beside `_project_handler_classes()` under `include_project_handlers=True`, deduplicated by class.
Disabled entries: the loader skips them (verified by test). Library-only default unchanged.
Tests: `TestPluginHandlersAreDiscoverable` (test_lookup.py), `TestPluginHandlersResolveThroughTheCli`.
Plugin source is generated in tmp_path; no fixtures dir change.
Release note: UNRELEASED/release-notes/023.
No disagreement with the brief. The loader raises RuntimeError on a bad plugin (fail fast for the daemon), so the lookup catches broadly and logs.
The defences listing near cli.py:4282 shares discover_handler_rules; not changed separately.
