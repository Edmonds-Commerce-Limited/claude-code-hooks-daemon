## 15:29 · decision · — — Stand-in declined: coverage trade-off is the owner's call

**Stand-in DECLINED, made by a fable sub-agent on the working session's behalf, not by the owner.**

Question: which option, A, B or C, should apply to glob-shaped tokens in interpreter code (#205, N626)?

The stand-in declined to choose. Its reasons:

- B and C both reduce what `secret_file_guard` denies, which is a coverage call on a safety guard and so the owner's.
- In the text checks, the two-character floor is safe only because the index still judges globs that do not depend on a protected name. Applying the floor to index matches removes the last check on an interpreter-side `glob.glob('.*')`, which does read a protected dotfile.
- C turns a deny into an allow with a note.
- The guard's documentation records its allow-what-cannot-be-judged policy as an owner ruling.
- Choosing A would settle #205 as won't-fix on the owner's behalf.

The plan stays Blocked on the owner, and #205 stays parked.
