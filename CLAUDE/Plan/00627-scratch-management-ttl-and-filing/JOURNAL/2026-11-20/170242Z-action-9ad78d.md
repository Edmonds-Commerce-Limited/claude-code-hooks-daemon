## 17:02 · action · — — F-BYPS 4: venv shape

Security review F-BYPS 4 fixed in `core/scratch_verdict.py`: P2 no longer lets a `pyvenv.cfg` cover its siblings.

A directory is a venv only with the real shape: a regular `pyvenv.cfg`, an interpreter under `bin/python*` or a `Scripts/` tree, and a `lib/` or `Lib/` tree. It then covers only `pyvenv.cfg`, `.gitignore`, `CACHEDIR.TAG` and the layout trees (`bin Scripts lib lib64 lib32 Lib include Include share`). A regular FILE named like a layout directory is a sibling. A real `python -m venv` was checked: it writes `.gitignore` (`*`), a `lib64` link, `include/`, `bin/`, `lib/`, `pyvenv.cfg`, all covered.

Tests: lone `pyvenv.cfg` beside findings.md/harness.py is UNCERTAIN; a full venv shape leaves sibling files uncovered; a partial shape covers nothing; real and Windows layouts stay DISPOSABLE. DESIGN 3.2 updated.
