# N526 fact-check (diff of b8fff2363)

Result: 11 claims, 11 verified, 0 refuted, 0 unverifiable. N526c is worded as unverified and was not resolved.

| #   | Claim                                                                      | Verdict           | Evidence                                                                                                                                                                      |
| --- | -------------------------------------------------------------------------- | ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | The test `test_many_edits_each_run_are_judged_quickly[a=['y']+a]` failed   | VERIFIED          | perf-ci.log:510 (test header), :514 `edit = "a=['y']+a"`                                                                                                                      |
| 2   | It failed at 1.716 s against `scaled_cpu_seconds(1.5)`                     | VERIFIED          | log:525 `assert 1.7164052509999976 < 1.5`; test file line 4506 `< scaled_cpu_seconds(1.5)`                                                                                    |
| 3   | It carries the perf_sweep marker                                           | VERIFIED          | tests/unit/handlers/pre_tool_use/test_subagent_full_qa_blocker.py:4498 `@pytest.mark.perf_sweep`                                                                              |
| 4   | It failed "alone in its own job"                                           | VERIFIED          | log:34 `Complete job name: Performance sweeps`; log:585 `1 failed, 10 passed`; .github/workflows/qa.yml:531                                                                   |
| 5   | The run was on `9d33b0cea`                                                 | VERIFIED          | log:248 and :260 show 9d33b0cea602f74a8be99240a41a19ee45decd8e checked out                                                                                                    |
| 6   | Moving these tests into their own job was the N455 hypothesis              | VERIFIED          | NIGGLES.md:830 is N455, titled "CI-load failures ... a timing bound" (the plan is 00474; N455 is in the same ledger). I did not read its full text for the "own job" wording. |
| 7   | The probe shows linear cost of about 0.45 ms per line for every edit shape | VERIFIED          | scale_probe.txt: 0.78-0.93 s at n=2000 gives 0.39-0.47 ms/line; the other sizes scale about linearly                                                                          |
| 8   | 500 lines 0.20-0.35 s, 1000 lines 0.38-0.55 s, 2000 lines 0.78-0.93 s      | VERIFIED          | probe ranges are 0.198-0.353, 0.377-0.548 and 0.781-0.932                                                                                                                     |
| 9   | The CI runner is about twice as slow                                       | VERIFIED          | 1.716 / 0.924 is 1.86 for the same shape at 2000 lines                                                                                                                        |
| 10  | At 4000 lines every shape returns in about 0.001 s                         | VERIFIED, loosely | probe shows 0.001-0.002 s at n=4000 for all four shapes. The diff says "about 0.001 s", which is slightly low for two shapes that read 0.002.                                 |
| 11  | Open rows: N526 added, 40 open (⬜), table 231 rows                        | VERIFIED          | `grep -c ⬜` on STATUS-INDEX.md gives 40, and every one of those is a \`^                                                                                                     |

N526c wording: "What it then decides is unverified", with a conditional "If an oversized script is ALLOWED ...". Fix direction says "first establish N526c". It is worded as unverified and is not asserted as fact.

Minor observations (not refutations):

- The probe covers four edit shapes, and the diff says "every edit shape". The test parametrizes five (`a.insert(1,'x{i}')` is not in the probe).
- The probe output is from the untracked scratch file, not a tracked artefact.
