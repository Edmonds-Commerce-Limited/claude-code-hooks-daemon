## 12:36 · correction · 11:56 — N720 differential re-run on the final head

The N720 builder's differential figure of 252 tightened and 0 loosened was measured before three later changes: the index rework (letters are folded, POSIX classes are not), the narrowing of the `-O` cluster to shell words with long options allowed before it, and the bounded bracket scans. That run also never exercised the index route, because its fixture wrote the protected file after the index was built.

The re-run on head c20eb4f04 indexes the file after writing it. It covers 720 command/mode rows across three routes and finds 245 tightened and 0 loosened. The builder report and the PR body cite the new figure.
