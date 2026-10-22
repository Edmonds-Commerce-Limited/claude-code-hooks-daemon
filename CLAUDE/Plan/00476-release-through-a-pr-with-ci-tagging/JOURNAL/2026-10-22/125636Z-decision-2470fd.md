## 12:56 · decision · —   — Owner authorises a release once focus mode is merged and CI is green

The owner authorised a release in this session, conditional, in their words: "ok you are authorised to run release once
focus mode is in and CI is all sorted".

The conditions, as the coordinator reads them:

- "focus mode is in": Plan 00501 Phase 3 (Tasks 3.1-3.3, focus mode) is merged to main.
- "CI is all sorted": main CI is green on the head that is released.

Until both hold, no release starts. The release then runs through `/release` (RELEASING.md), and every blocking gate still
applies. Plan 00476 was blocked on this release.
