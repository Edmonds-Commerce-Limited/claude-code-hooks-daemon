"""Plan 00538 Phase 2: the hooks-screen Rust binary, driven with byte streams.

Builds the binary once with ``screen/build.sh`` (plain rustc, musl, no cargo)
and skips when no musl-capable rustc is present, the same fail-soft stance the
provisioning takes.
"""

from __future__ import annotations

import random
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BUILD_SCRIPT = REPO_ROOT / "screen" / "build.sh"
BINARY = REPO_ROOT / "untracked" / "screen-build" / "hooks-screen-x86_64-unknown-linux-musl"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "hooks_screen"
ESC = b"\x1b"


@pytest.fixture(scope="module")
def binary() -> Path:
    """Build hooks-screen from source; skip when the toolchain is absent."""
    result = subprocess.run(
        ["bash", str(BUILD_SCRIPT)], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        pytest.skip(f"hooks-screen cannot be built here: {result.stderr.strip()[:200]}")
    return BINARY


def run(
    binary: Path, data: bytes, *args: str, cols: int = 20, rows: int = 6
) -> subprocess.CompletedProcess[bytes]:
    """Feed ``data`` to hooks-screen with the given size and extra args."""
    return subprocess.run(
        [str(binary), "--cols", str(cols), "--rows", str(rows), *args],
        input=data,
        capture_output=True,
        check=False,
        timeout=20,
    )


def dump(binary: Path, data: bytes, **kwargs: int) -> list[str]:
    """The rendered rows of ``data``."""
    out = run(binary, data, "--dump", **kwargs)
    assert out.returncode == 0, out.stderr
    return out.stdout.decode().split("\n")[:-1]


class TestRendering:
    def test_plain_text_and_crlf(self, binary: Path) -> None:
        assert dump(binary, b"ab\r\ncd")[:2] == ["ab", "cd"]

    def test_lf_alone_keeps_column(self, binary: Path) -> None:
        assert dump(binary, b"ab\ncd")[:2] == ["ab", "  cd"]

    def test_backspace_and_tab(self, binary: Path) -> None:
        assert dump(binary, b"abc\x08X\tY")[0] == "abX     Y"

    def test_cursor_up_erase_line_redraw(self, binary: Path) -> None:
        raw = (FIXTURES / "ink_redraw.raw").read_bytes()
        assert dump(binary, raw)[:4] == ["done", "> prompt", "footer B", ""]

    def test_cursor_position_and_relative_moves(self, binary: Path) -> None:
        raw = ESC + b"[3;4HX" + ESC + b"[2D" + b"Y" + ESC + b"[1A" + b"Z" + ESC + b"[5G" + b"W"
        rows = dump(binary, raw)
        assert rows[1] == "   ZW"
        assert rows[2] == "  YX"

    def test_vpa_cha_and_hvp(self, binary: Path) -> None:
        rows = dump(binary, ESC + b"[4d" + ESC + b"[3GA" + ESC + b"[1;2fB")
        assert rows[3] == "  A"
        assert rows[0] == " B"

    def test_erase_line_modes(self, binary: Path) -> None:
        base = b"abcdef" + ESC + b"[3D"
        assert dump(binary, base + ESC + b"[K")[0] == "abc"
        assert dump(binary, base + ESC + b"[1K")[0] == "    ef"
        assert dump(binary, base + ESC + b"[2K")[0] == ""

    def test_erase_display_modes(self, binary: Path) -> None:
        base = b"aaa\r\nbbb\r\nccc" + ESC + b"[2;2H"
        assert dump(binary, base + ESC + b"[J")[:3] == ["aaa", "b", ""]
        assert dump(binary, base + ESC + b"[1J")[:3] == ["", "  b", "ccc"]
        assert dump(binary, base + ESC + b"[2J")[:3] == ["", "", ""]
        assert dump(binary, base + ESC + b"[3J")[:3] == ["", "", ""]

    def test_sgr_is_parsed_and_ignored(self, binary: Path) -> None:
        assert dump(binary, ESC + b"[1;38;5;196mred" + ESC + b"[0m ok")[0] == "red ok"

    def test_scroll_on_lf_at_bottom(self, binary: Path) -> None:
        raw = b"\r\n".join(f"l{i}".encode() for i in range(8))
        assert dump(binary, raw, rows=3) == ["l5", "l6", "l7"]

    def test_autowrap(self, binary: Path) -> None:
        assert dump(binary, b"abcdefgh", cols=4)[:2] == ["abcd", "efgh"]

    def test_osc_dcs_apc_strings_are_skipped(self, binary: Path) -> None:
        raw = (
            ESC
            + b"]0;title\x07A"
            + ESC
            + b"]8;;http://x"
            + ESC
            + b"\\B"
            + ESC
            + b"Pq;data"
            + ESC
            + b"\\C"
            + ESC
            + b"_apc"
            + ESC
            + b"\\D"
        )
        assert dump(binary, raw)[0] == "ABCD"

    def test_sync_update_mode_is_ignored(self, binary: Path) -> None:
        assert dump(binary, ESC + b"[?2026hhi" + ESC + b"[?2026l")[0] == "hi"

    def test_alternate_screen_enter_and_exit(self, binary: Path) -> None:
        assert dump(binary, (FIXTURES / "alt_screen.raw").read_bytes())[:3] == [
            "alt view",
            "second",
            "",
        ]
        assert dump(binary, (FIXTURES / "alt_screen_exit.raw").read_bytes())[:2] == [
            "main text",
            "",
        ]

    def test_insert_delete_lines_and_chars(self, binary: Path) -> None:
        raw = b"a\r\nb\r\nc" + ESC + b"[2;1H" + ESC + b"[L" + b"X"
        assert dump(binary, raw)[:4] == ["a", "X", "b", "c"]
        raw = b"a\r\nb\r\nc" + ESC + b"[2;1H" + ESC + b"[M"
        assert dump(binary, raw)[:3] == ["a", "c", ""]
        raw = b"abcdef" + ESC + b"[1;2H" + ESC + b"[2P"
        assert dump(binary, raw)[0] == "adef"

    def test_wide_characters_take_two_cells(self, binary: Path) -> None:
        assert dump(binary, "漢字ab".encode(), cols=6)[0] == "漢字ab"
        assert dump(binary, "漢字ab".encode(), cols=4)[:2] == ["漢字", "ab"]

    def test_utf8_split_across_nothing_is_replaced_not_fatal(self, binary: Path) -> None:
        assert dump(binary, b"a\xffb")[0] == "a�b"
        assert dump(binary, b"a\xe2\x82")[0] == "a"

    def test_save_restore_cursor(self, binary: Path) -> None:
        raw = b"ab" + ESC + b"7" + b"\r\n" + ESC + b"8" + b"X"
        assert dump(binary, raw)[0] == "abX"


class TestMalformedInput:
    @pytest.mark.parametrize("seed", range(40))
    def test_random_bytes_never_panic(self, binary: Path, seed: int) -> None:
        rng = random.Random(seed)
        data = bytes(rng.randrange(256) for _ in range(rng.randrange(1, 4096)))
        out = run(binary, data, cols=rng.randrange(1, 12), rows=rng.randrange(1, 8))
        assert out.returncode == 0, out.stderr
        assert out.stdout.decode().strip() == "unknown"

    @pytest.mark.parametrize("seed", range(40))
    def test_random_escape_soup_never_panics(self, binary: Path, seed: int) -> None:
        rng = random.Random(1000 + seed)
        pieces = [
            ESC,
            b"[",
            b"]",
            b"?",
            b";",
            b"A",
            b"H",
            b"J",
            b"K",
            b"1049",
            b"9999999999",
            b"h",
            b"l",
            b"L",
            b"M",
            b"P",
            b"@",
            b"X",
            b"S",
            b"T",
            b"d",
            b"G",
            b"\r",
            b"\n",
            b"\x08",
            b"\t",
            b"x",
            "漢".encode(),
        ]
        data = b"".join(rng.choice(pieces) for _ in range(3000))
        out = run(binary, data, "--dump", cols=rng.randrange(1, 9), rows=rng.randrange(1, 6))
        assert out.returncode == 0, out.stderr

    def test_empty_input(self, binary: Path) -> None:
        assert run(binary, b"").stdout.decode().strip() == "unknown"

    def test_huge_parameters_are_clamped(self, binary: Path) -> None:
        raw = ESC + b"[99999999999999999999;99999999999999999999H" + ESC + b"[99999999999L"
        assert run(binary, raw, "--dump").returncode == 0

    def test_dimensions_are_clamped(self, binary: Path) -> None:
        assert run(binary, b"x", "--dump", cols=0, rows=0).returncode == 0
        assert run(binary, b"x", "--dump", cols=10**7, rows=10**7).returncode == 0


class TestClassifier:
    def test_builtin_table_is_conservative(self, binary: Path) -> None:
        for name in ("ink_redraw", "alt_screen", "synthetic_transcript", "synthetic_panel"):
            out = run(binary, (FIXTURES / f"{name}.raw").read_bytes())
            assert out.stdout.decode().strip() == "unknown", name

    @pytest.mark.parametrize(
        ("fixture", "word"),
        [
            ("synthetic_transcript", "transcript"),
            ("synthetic_panel", "panel-selected"),
            ("ink_redraw", "unknown"),
        ],
    )
    def test_marker_file_drives_the_verdict(self, binary: Path, fixture: str, word: str) -> None:
        out = run(
            binary,
            (FIXTURES / f"{fixture}.raw").read_bytes(),
            "--markers",
            str(FIXTURES / "synthetic-markers.txt"),
        )
        assert out.returncode == 0
        assert out.stdout.decode().strip() == word

    def test_last_scope_counts_non_blank_rows(self, binary: Path, tmp_path: Path) -> None:
        markers = tmp_path / "m.txt"
        markers.write_text("main last:1 FOOT\n")
        out = run(binary, b"head\r\n\r\n\r\nFOOT", "--markers", str(markers), rows=10)
        assert out.stdout.decode().strip() == "main"

    def test_bad_marker_file_is_a_usage_error(self, binary: Path, tmp_path: Path) -> None:
        markers = tmp_path / "m.txt"
        markers.write_text("nonsense any x\n")
        out = run(binary, b"x", "--markers", str(markers))
        assert out.returncode == 2
        assert b"bad marker" in out.stderr

    def test_missing_marker_file_is_a_usage_error(self, binary: Path, tmp_path: Path) -> None:
        assert run(binary, b"x", "--markers", str(tmp_path / "none")).returncode == 2

    def test_unknown_argument_is_a_usage_error(self, binary: Path) -> None:
        assert run(binary, b"x", "--bogus").returncode == 2

    def test_non_numeric_size_is_a_usage_error(self, binary: Path) -> None:
        out = subprocess.run(
            [str(binary), "--cols", "wide"], input=b"", capture_output=True, check=False
        )
        assert out.returncode == 2
