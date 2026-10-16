"""Tests for the static Workflow fan-out reader (Plan 00472 Task 3.6, 472-W section 3).

The fixtures follow the shapes of the workflow-authoring skill's worked examples.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.workflow_fanout import (
    Bucket,
    analyse_script,
    mentions_agent_call,
)

LITERAL_ARRAY = """
const results = await parallel(
  ['src/a.ts', 'src/b.ts', 'src/c.ts'].map((file) => () =>
    agent(`Review ${file}`, { model: 'sonnet' })
  )
);
"""

ARRAY_FROM = """
// Adversarial verify: three independent judges
const verdicts = await parallel(
  Array.from({ length: 3 }, (_, i) => () => agent('Judge the claim, take ' + i))
);
"""

LITERAL_LOOP = """
for (let i = 0; i < 8; i++) {
  await agent(`Shard ${i}`, { model: 'haiku' });
}
"""

ARGS_DRIVEN = """
await pipeline(args, async (file) => agent(`Migrate ${file}`));
"""

SCRIPT_COMPUTED = """
const files = await agent('List the changed files', { schema: listSchema });
await pipeline(files, async (file) => agent(`Fix ${file}`, { model: 'sonnet' }));
"""

BUDGET_LOOP = """
while (budget.total && budget.remaining() > 50_000) {
  const found = await agent('Find one more bug');
  bugs.push(found);
}
"""

MIXED = """
const plan = await agent('Plan the migration', { model: 'opus' });
const fixes = await parallel([
  () => agent('Fix the router'),
  () => agent('Fix the parser'),
]);
for (const area of ['auth', 'billing']) {
  await agent(`Audit ${area}`);
}
"""


class TestFixtures:
    @pytest.mark.parametrize(
        ("script", "args_len", "total", "sites", "no_model", "unknown"),
        [
            (LITERAL_ARRAY, None, 3, 1, 0, False),
            (ARRAY_FROM, None, 3, 1, 1, False),
            (LITERAL_LOOP, None, 8, 1, 0, False),
            (ARGS_DRIVEN, 12, 12, 1, 1, False),
            (ARGS_DRIVEN, None, 1, 1, 1, True),
            (SCRIPT_COMPUTED, None, 2, 2, 1, True),
            (BUDGET_LOOP, None, 1, 1, 1, True),
            (MIXED, None, 5, 4, 3, False),
        ],
    )
    def test_count_and_bucket(
        self,
        script: str,
        args_len: int | None,
        total: int,
        sites: int,
        no_model: int,
        unknown: bool,
    ) -> None:
        reading = analyse_script(script, args_len=args_len)
        assert reading.total == total
        assert len(reading.sites) == sites
        assert reading.sites_without_model == no_model
        assert reading.has_unknown is unknown

    def test_args_resolution_is_its_own_bucket(self) -> None:
        (site,) = analyse_script(ARGS_DRIVEN, args_len=12).sites
        assert site.bucket is Bucket.ARGS
        assert site.multiplier == 12

    def test_literal_sites_are_exact(self) -> None:
        assert {site.bucket for site in analyse_script(LITERAL_ARRAY, args_len=None).sites} == {
            Bucket.EXACT
        }

    def test_script_computed_list_is_unknown(self) -> None:
        sites = analyse_script(SCRIPT_COMPUTED, args_len=None).sites
        assert [site.bucket for site in sites] == [Bucket.EXACT, Bucket.UNKNOWN]


class TestScanner:
    def test_agent_in_a_string_or_comment_is_not_a_site(self) -> None:
        script = "// agent('x')\nconst s = \"agent('y')\";\nawait agent('real');\n"
        assert len(analyse_script(script, args_len=None).sites) == 1

    def test_a_method_named_agent_is_not_a_site(self) -> None:
        assert analyse_script("helper.agent('x')", args_len=None).sites == ()

    def test_nested_multipliers_multiply(self) -> None:
        script = (
            "for (let i = 0; i < 2; i++) { await parallel(['a','b','c'].map(x => () => agent(x))) }"
        )
        assert analyse_script(script, args_len=None).total == 6

    def test_inclusive_loop_bound(self) -> None:
        script = "for (let i = 1; i <= 4; i++) { agent('x') }"
        assert analyse_script(script, args_len=None).total == 4

    def test_array_from_length_mapped_without_a_mapper(self) -> None:
        script = "await parallel(Array.from({length: 5}).map(() => () => agent('x')));"
        reading = analyse_script(script, args_len=None)
        assert (reading.total, reading.has_unknown) == (5, False)

    @pytest.mark.parametrize(
        "script",
        [
            # a regex literal holding a quote is read as an unterminated string
            "const r = /'/; for (const f of ['a','b']) { await agent(f); }",
            # a call inside a template ${...} is blanked with the template
            "const s = `${await agent('x')}`;",
        ],
    )
    def test_shapes_the_reader_misses_are_still_seen_to_call_agent(self, script: str) -> None:
        """The static reader finds no site, but the raw text calls agent(): the
        advisor must report that as unparsed, never as a script with no agents."""
        assert analyse_script(script, args_len=None).sites == ()
        assert mentions_agent_call(script)

    def test_a_script_with_no_agent_call(self) -> None:
        assert not mentions_agent_call("const x = helper.agent; run(x);")

    def test_args_map(self) -> None:
        reading = analyse_script("await parallel(args.map(f => () => agent(f)))", args_len=7)
        assert reading.total == 7

    def test_a_spread_array_is_unknown(self) -> None:
        reading = analyse_script("[...items, 'x'].map(f => agent(f))", args_len=None)
        assert reading.has_unknown

    def test_empty_script(self) -> None:
        reading = analyse_script("", args_len=None)
        assert (reading.total, reading.sites, reading.has_unknown) == (0, (), False)

    def test_unbalanced_script_still_reads(self) -> None:
        reading = analyse_script("agent('x', { model: 'sonnet' }", args_len=None)
        assert len(reading.sites) == 1
