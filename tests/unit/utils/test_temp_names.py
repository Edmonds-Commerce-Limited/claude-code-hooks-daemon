"""Every atomic writer builds its temp filename from ONE helper (Plan 00159).

Nine writers spelled ``.{stem}.{os.getpid()}.tmp`` by hand, and the count grew
from the four the plan enumerated to nine by copy. A pid-only name is unique
across processes but not across threads of one process, and the spelling has
no single home to fix. ``unique_temp_path`` is that home; the grep guard below
keeps the hand-rolled form from spreading again.
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path

from claude_code_hooks_daemon.utils.temp_names import unique_temp_path

_SRC_ROOT = Path(__file__).resolve().parents[3] / "src" / "claude_code_hooks_daemon"

#: The writers Plan 00362's ledger item R2 enumerates. Each must route through
#: the helper rather than spelling a pid-keyed name itself.
_WRITER_MODULES = (
    "handlers/post_tool_use/goal_injection.py",
    "handlers/pre_compact/compaction_signal.py",
    "handlers/status_line/context_sidecar.py",
    "handlers/user_prompt_submit/standing_authorisations.py",
    "handlers/status_line/thread_registry.py",
    "handlers/session_start/model_fallback_detector.py",
    "handlers/status_line/downgrade_state.py",
    "utils/model_downgrade_signal.py",
)

_HAND_ROLLED = re.compile(r"getpid\(\)}[^\"']*\.tmp")


class TestUniqueTempPath:
    def test_sits_beside_the_final_path_as_a_dotfile(self, tmp_path: Path) -> None:
        final = tmp_path / "session.json"
        tmp = unique_temp_path(final)
        assert tmp.parent == final.parent
        assert tmp.name.startswith(".session.json.")
        assert tmp.suffix == ".tmp"

    def test_carries_the_pid(self, tmp_path: Path) -> None:
        tmp = unique_temp_path(tmp_path / "x.json")
        assert f".{os.getpid()}." in tmp.name

    def test_two_calls_in_one_thread_differ(self, tmp_path: Path) -> None:
        final = tmp_path / "x.json"
        assert unique_temp_path(final) != unique_temp_path(final)

    def test_concurrent_threads_never_share_a_name(self, tmp_path: Path) -> None:
        final = tmp_path / "x.json"
        names: list[str] = []
        lock = threading.Lock()

        def worker() -> None:
            local = [unique_temp_path(final).name for _ in range(50)]
            with lock:
                names.extend(local)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(names) == len(set(names))

    def test_replace_lands_the_final_file(self, tmp_path: Path) -> None:
        final = tmp_path / "x.json"
        tmp = unique_temp_path(final)
        tmp.write_text("{}", encoding="utf-8")
        tmp.replace(final)
        assert final.read_text(encoding="utf-8") == "{}"
        assert not list(tmp_path.glob(".*.tmp"))


class TestNoWriterHandRollsItsTempName:
    def test_no_source_file_spells_a_pid_keyed_temp_name(self) -> None:
        offenders = [
            str(p.relative_to(_SRC_ROOT))
            for p in _SRC_ROOT.rglob("*.py")
            if p.name != "temp_names.py" and _HAND_ROLLED.search(p.read_text(encoding="utf-8"))
        ]
        assert offenders == [], f"hand-rolled temp names (use unique_temp_path): {offenders}"

    def test_every_enumerated_writer_imports_the_helper(self) -> None:
        missing = [
            rel
            for rel in _WRITER_MODULES
            if "unique_temp_path" not in (_SRC_ROOT / rel).read_text(encoding="utf-8")
        ]
        assert missing == [], f"writers not routed through unique_temp_path: {missing}"
