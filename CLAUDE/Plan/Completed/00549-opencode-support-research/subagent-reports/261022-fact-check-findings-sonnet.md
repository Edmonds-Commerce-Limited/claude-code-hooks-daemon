# Fact check: FINDINGS.md (Plan 00549 Task 3.1)

Scope: every section pointer and every number or claim in `FINDINGS.md`, checked against the cited supporting
documents, the two sub-agent reports, and (for repository facts) the current tree. PLAN.md diff: only the Task 3.1
tick, which is consistent with `FINDINGS.md` now existing.

Totals: about 60 claims and pointers checked. 50 verified, 8 refuted, 2 unverifiable-here.

## REFUTED (most consequential first)

1. **Line 65, "Status line, cron: Neither / Absent in opencode"** stated as fact. ARCH §8 row 17 says whether TUI
   plugins can add status segments is UNVERIFIED, and row 18 says "None found in core ... UNVERIFIED, since only core
   and cli were checked". PLANWF §1 fact 3 searched `core`, `schema` and `cli` only. Change: "none found in core, schema
   or cli; plugin/TUI scope not checked".
2. **Lines 87-88, "Equivalence table from ~40 probes; the shim ... is the only layout that restores native behaviour,
   including nested loads"**. AMD §5.1 says symlinks also work (probe f3), and AMD §6 says the nested Write, Edit and
   Bash behaviour comes from source and docs, not observation (child CLI not logged in); the table also has docs-only
   rows (L437, L438) and an UNVERIFIED row. The same "only layout" wording is repeated in the Plan 2 evidence line
   (159-160). Change: "the recommended layout; symlinks also work but fail on Windows; Write/Edit/Bash nested loads are
   source-derived".
3. **Line 86, "a loose `.claude/skills/CLAUDE.md` becomes a phantom skill in opencode"** (and "agents' frontmatter is
   incompatible") as fact. DUAL §8: both are "derived from code reading ... not observed by running opencode".
   Change: say code-derived, not observed.
4. **Lines 130-133 (Plan 1), "CLI entry points for the conflict-marker, staged-lint and sensitive-content scans (the
   others are already CLIs)"**. PLANWF §4 row 4 says "CLI entry points not checked"; row 7 and PLANWF Gaps say the
   `docs-qa` staged mode is not checked; guard-config, closing-keyword (message-only) and remote-docs provenance gates
   are not shown to be CLIs at all. OPTIONS §2 A ("no CLI entry point yet") already overstates PLANWF. Change: "none
   of these was checked for a CLI entry point; plan-qa and issue-validity are the confirmed CLIs".
5. **Lines 3-4, "The harness refused a Write to the canonical path, so this is the fallback location. Move it to
   `../FINDINGS.md`"**. The file is already at the canonical path, tracked at
   `CLAUDE/Plan/00549-opencode-support-research/FINDINGS.md` (`git ls-files`). No other copy exists. Change: delete the
   note.
6. **Lines 11-12, "33 of 35 claims verified, one minor count corrected"**. The fact-check report has 33 VERIFIED,
   1 REFUTED (59 of 82, now fixed to 81 in COUP lines 209, 487) and 1 UNVERIFIABLE-HERE (claim 35: Bun socket
   reachability, v2.1 contract break, V1 loader rejection). The summary hides the unverifiable one. Change: "33 verified,
   1 refuted and fixed, 1 unverifiable without a live run".
7. **Lines 202-203, pointer "(OPTIONS §4 item 3; MAP Gaps)"** for "whether every mutating tool calls
   `permission.assert`". MAP Gaps does not list it (it lists the `execute.before`/`permission.evaluate` ask-correlation
   as untested). The item is in OPTIONS §4 item 3 and the MAP Table 2 `ask` row. Change: cite "MAP Table 2".
8. **Lines 93-94, "A missing plugin is made loud by an `ask` permission baseline"**, and **line 84, "so a stop
   re-drive works"**, stated without caveat. OPTIONS §4 item 3 marks the baseline "UNVERIFIED as complete"; PLANWF Gaps
   lists re-drive timing as untested and MAP/OPTIONS flag a loop risk. PLANWF §1 fact 1 only establishes that a
   synthetic message wakes the loop. Change: "designed to be loud (unproven until plan 0)"; "a re-drive can restart the
   loop; timing untested". Related, line 91-92: "expected faster than the 4.3 ms relay path" is an OPTIONS INFERENCE
   (dispatch alone is 1.8-10.2 ms, PERF line 49), correctly marked "to be measured" but not marked INFERENCE.

## UNVERIFIABLE-HERE

- Line 212 (item 8) / line 24-26 "V2 loader rejects V1": SURFACE §0 gives code evidence (`module.ts:78-91`); the
  fact-check did not re-trace it (its claim 35). Needs a live opencode run. The website-currency question is UNVERIFIED
  in SURFACE Gaps, and FINDINGS lists it correctly.
- Line 67, "V2.1 broke plugin contracts in a minor release": SURFACE §7 cites `CHANGELOG.md:73,87`; not re-read here.

## Verified (summary)

- All short-name pointers resolve to real headings: SURFACE §0-§7 and Gaps; ARCH §1.2, §8, §8.1, Gaps; DUAL §1
  (findings 1, 3, 5), §2-§8; COUP Counts and "The 10 most load-bearing couplings"; AMD §1, §4, §5 (designs 1, 2 (a)-(e)),
  §6; SYNC §1, §4, §6, §7 (E1-E6, I1-I2); MAP "How opencode is hooked", Tables 1-3, Summary, Gaps; PLANWF §1 (facts 1-3),
  §2.4, §3, §4, §5 (A-D), Gaps; OPTIONS §2 A "Size", §2 B "Performance" and "Open unknowns", §2 C, §3, §4 (items 1, 3),
  §5 step 0, §6, Gaps; RULINGS Q1.1-Q1.7, Q4.3.
- Numbers: 187 handlers, 108/54/7/18 and 162 (87%) (MAP Summary; fact-check 26); 34 catalogued events (31 wired,
  3 unwired in one Table 1 row); 41 couplings, Option B 23, six unsupported (COUP Counts; OPTIONS §3); 26-row ARCH §8
  table; 118,604 bytes and 12 nested `CLAUDE.md` (fact-check 30); Claude Code 2.1.308 and 2.1.277 (AMD §1);
  ~94 handlers (OPTIONS §2 B); 4.3 ms relay (PERF line 94); 35+ providers, MIT, default allow-all, config deny final
  (ARCH §8 rows 1, 4, 8).
- Decisions table matches RULINGS (Q1-Q4, M1-M4, M5 UNCLEAR non-blocking with default (a), E6 out of scope). The
  step renumbering (RULINGS "step 6" is FINDINGS plan 7; "after step 5" is "after plan 6") is consistent with OPTIONS §5
  and the added plans 1/2 split.
- Stated limits are present: line 197 "All UNVERIFIED ... no live opencode run", and item 9 carries the AMD §6 caveat.
