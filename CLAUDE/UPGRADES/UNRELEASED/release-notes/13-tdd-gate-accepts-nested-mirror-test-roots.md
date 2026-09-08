# Callout: the TDD gate can be told about a nested mirror test root

**Plan**: 00362
**Audience**: client projects

A `tdd_enforcement.test_path_map` entry now takes `mirror: true`, which
places the expected test at `<test_dir>/<source path after the glob's root>/<TestName>` instead of flat in `test_dir`, and a nested
`layout.test_dirs` entry such as `tests/Small` is searched as a mirror root
with no map entry at all. A PHP project laid out as
`tests/Small/<mirror of src>/FooTest.php` and `tests/Large/...` can therefore
keep the gate on -- every declared root is checked and every one is listed in
a deny -- and can drop the `enabled: false` it needed until now.
