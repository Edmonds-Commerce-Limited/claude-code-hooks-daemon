//! hooks-screen -- render a terminal byte stream and say which Claude Code
//! view it shows.
//!
//! Plan 00538 Phase 2. A hooks-daemon component used by the ccy supervisor's
//! main-thread focus check (`.claude/ccy/claude-supervise.py`). Built like the
//! relay (relay/hooks_relay.rs): ONE std-only source file, zero crates, no
//! cargo, plain `rustc --edition 2021 -O -D warnings` against the musl target
//! (see screen/build.sh). No `#[allow]` attributes.
//!
//! The supervisor keeps the child's raw output in a bounded buffer and spawns
//! this binary only when a send is due, so nothing is parsed on the hot path.
//!
//! Argv:  hooks-screen [--cols N] [--rows N] [--dump] [--markers FILE]
//!   stdin      raw terminal output bytes (capped at MAX_INPUT_BYTES)
//!   default    prints ONE word: main | transcript | panel-selected | unknown
//!   --dump     prints the rendered rows instead (trailing blanks trimmed)
//!   --markers  replace the built-in marker table with the lines of FILE:
//!              `<verdict> <scope> <needle...>`, scope any | first:N | last:N
//!              (first/last N NON-BLANK rows); `#` starts a comment line
//! Exit codes: 0 rendered/classified (malformed input never panics);
//!             2 usage error or unreadable --markers file.
//!
//! BOUNDARIES (keep them, so the emulator can be swapped for a crate without
//! touching the classifier or the CLI):
//!   - `Screen::feed(&[u8])` and `Screen::rows() -> Vec<String>` are the whole
//!     emulator interface.
//!   - `classify(&[String], &[Marker]) -> Verdict` sees only rows.
//!
//! Emulated subset (what Claude Code's Ink TUI emits): CR LF VT FF BS TAB;
//! CSI CUU CUD CUF CUB CNL CPL CHA CUP HVP VPA, EL, ED (3 treated as 2), ICH
//! DCH ECH IL DL SU SD, SGR (parsed, ignored); DECSET/DECRST 1049/1047/47
//! (alternate screen; 2026 and the rest ignored: every byte is applied, so
//! the settled frame is the same); ESC 7/8, IND, NEL, RI, RIS; OSC, DCS, APC,
//! PM and SOS strings skipped. NOT emulated: scroll regions (DECSTBM),
//! scrollback, insert mode, tab stops other than every 8 columns. Width is a
//! small std-only table: East Asian wide and emoji ranges take 2 cells,
//! combining marks and joiners 0, everything else 1.

use std::env;
use std::fs;
use std::io::{self, Read, Write};
use std::process::exit;

const DEFAULT_COLS: usize = 80;
const DEFAULT_ROWS: usize = 24;
const MIN_DIM: usize = 2;
const MAX_DIM: usize = 1000;
const MAX_INPUT_BYTES: u64 = 8 * 1024 * 1024;
const MAX_CSI_PARAM_BYTES: usize = 64;
const TAB_WIDTH: usize = 8;
const EXIT_USAGE: i32 = 2;

const ESC: char = '\u{1b}';
const BEL: char = '\u{07}';
const CAN: char = '\u{18}';
const SUB: char = '\u{1a}';

// ---------------------------------------------------------------------------
// Classifier: markers are DATA. The built-in table is empty until real
// captures exist (Plan 00538 Slice 2), so every screen is `unknown`.
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Verdict {
    Main,
    Transcript,
    PanelSelected,
    Unknown,
}

impl Verdict {
    fn word(self) -> &'static str {
        match self {
            Verdict::Main => "main",
            Verdict::Transcript => "transcript",
            Verdict::PanelSelected => "panel-selected",
            Verdict::Unknown => "unknown",
        }
    }

    fn from_word(word: &str) -> Option<Verdict> {
        match word {
            "main" => Some(Verdict::Main),
            "transcript" => Some(Verdict::Transcript),
            "panel-selected" => Some(Verdict::PanelSelected),
            _ => None,
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Scope {
    Any,
    First(usize),
    Last(usize),
}

struct MarkerSpec {
    verdict: Verdict,
    scope: Scope,
    needle: &'static str,
}

/// The built-in marker table. Empty on purpose: no real capture has been
/// taken yet, and a guessed marker would hold sends on a wrong screen.
const BUILTIN_MARKERS: &[MarkerSpec] = &[];

struct Marker {
    verdict: Verdict,
    scope: Scope,
    needle: String,
}

fn builtin_markers() -> Vec<Marker> {
    BUILTIN_MARKERS
        .iter()
        .map(|spec| Marker {
            verdict: spec.verdict,
            scope: spec.scope,
            needle: spec.needle.to_string(),
        })
        .collect()
}

fn parse_scope(text: &str) -> Option<Scope> {
    if text == "any" {
        return Some(Scope::Any);
    }
    let (kind, count) = text.split_once(':')?;
    let count: usize = count.parse().ok()?;
    match kind {
        "first" => Some(Scope::First(count)),
        "last" => Some(Scope::Last(count)),
        _ => None,
    }
}

fn parse_markers(text: &str) -> Result<Vec<Marker>, String> {
    let mut markers = Vec::new();
    for (index, line) in text.lines().enumerate() {
        if line.trim().is_empty() || line.starts_with('#') {
            continue;
        }
        let mut parts = line.splitn(3, ' ');
        let verdict = parts.next().and_then(Verdict::from_word);
        let scope = parts.next().and_then(parse_scope);
        let needle = parts.next().unwrap_or("");
        match (verdict, scope) {
            (Some(verdict), Some(scope)) if !needle.is_empty() => markers.push(Marker {
                verdict,
                scope,
                needle: needle.to_string(),
            }),
            _ => return Err(format!("bad marker on line {}: {}", index + 1, line)),
        }
    }
    Ok(markers)
}

fn classify(rows: &[String], markers: &[Marker]) -> Verdict {
    let filled: Vec<&String> = rows.iter().filter(|row| !row.is_empty()).collect();
    for marker in markers {
        let hit = match marker.scope {
            Scope::Any => filled.iter().any(|row| row.contains(&marker.needle)),
            Scope::First(count) => filled
                .iter()
                .take(count)
                .any(|row| row.contains(&marker.needle)),
            Scope::Last(count) => filled
                .iter()
                .rev()
                .take(count)
                .any(|row| row.contains(&marker.needle)),
        };
        if hit {
            return marker.verdict;
        }
    }
    Verdict::Unknown
}

// ---------------------------------------------------------------------------
// Emulator
// ---------------------------------------------------------------------------

fn char_width(ch: char) -> usize {
    let code = ch as u32;
    match code {
        0x0300..=0x036F
        | 0x1AB0..=0x1AFF
        | 0x1DC0..=0x1DFF
        | 0x200B..=0x200F
        | 0x20D0..=0x20FF
        | 0xFE00..=0xFE0F => 0,
        0x1100..=0x115F
        | 0x2E80..=0x303E
        | 0x3041..=0xA4CF
        | 0xAC00..=0xD7A3
        | 0xF900..=0xFAFF
        | 0xFE30..=0xFE6F
        | 0xFF00..=0xFF60
        | 0xFFE0..=0xFFE6
        | 0x1F300..=0x1F64F
        | 0x1F900..=0x1F9FF
        | 0x20000..=0x3FFFD => 2,
        _ => 1,
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum State {
    Ground,
    Esc,
    EscInter,
    Csi,
    Str,
    StrEsc,
}

struct Screen {
    cols: usize,
    rows: usize,
    main: Vec<Vec<char>>,
    alt: Vec<Vec<char>>,
    use_alt: bool,
    row: usize,
    col: usize,
    wrap_pending: bool,
    saved: (usize, usize),
    state: State,
    csi: Vec<u8>,
    utf8_tail: Vec<u8>,
}

fn blank_grid(cols: usize, rows: usize) -> Vec<Vec<char>> {
    vec![vec![' '; cols]; rows]
}

impl Screen {
    fn new(cols: usize, rows: usize) -> Screen {
        let cols = cols.clamp(MIN_DIM, MAX_DIM);
        let rows = rows.clamp(MIN_DIM, MAX_DIM);
        Screen {
            cols,
            rows,
            main: blank_grid(cols, rows),
            alt: blank_grid(cols, rows),
            use_alt: false,
            row: 0,
            col: 0,
            wrap_pending: false,
            saved: (0, 0),
            state: State::Ground,
            csi: Vec::new(),
            utf8_tail: Vec::new(),
        }
    }

    /// Apply one chunk of terminal output.
    fn feed(&mut self, bytes: &[u8]) {
        let mut pending = std::mem::take(&mut self.utf8_tail);
        pending.extend_from_slice(bytes);
        let mut rest: &[u8] = &pending;
        while !rest.is_empty() {
            match std::str::from_utf8(rest) {
                Ok(text) => {
                    self.feed_text(text);
                    rest = &[];
                }
                Err(err) => {
                    let valid = err.valid_up_to();
                    if let Ok(text) = std::str::from_utf8(&rest[..valid]) {
                        self.feed_text(text);
                    }
                    match err.error_len() {
                        Some(bad) => {
                            self.step('\u{fffd}');
                            rest = &rest[valid + bad..];
                        }
                        None => {
                            self.utf8_tail = rest[valid..].to_vec();
                            rest = &[];
                        }
                    }
                }
            }
        }
    }

    /// The active screen as text rows, trailing blanks trimmed.
    fn rows(&self) -> Vec<String> {
        let grid = if self.use_alt { &self.alt } else { &self.main };
        grid.iter()
            .map(|cells| {
                let line: String = cells.iter().filter(|cell| **cell != '\0').collect();
                line.trim_end_matches(' ').to_string()
            })
            .collect()
    }

    fn feed_text(&mut self, text: &str) {
        for ch in text.chars() {
            self.step(ch);
        }
    }

    fn grid(&mut self) -> &mut Vec<Vec<char>> {
        if self.use_alt {
            &mut self.alt
        } else {
            &mut self.main
        }
    }

    fn step(&mut self, ch: char) {
        match self.state {
            State::Ground => self.ground(ch),
            State::Esc => self.escape(ch),
            State::EscInter => {
                if !('\u{20}'..='\u{2f}').contains(&ch) {
                    self.state = State::Ground;
                    if ch == ESC {
                        self.state = State::Esc;
                    }
                }
            }
            State::Csi => self.csi_byte(ch),
            State::Str => match ch {
                BEL | CAN | SUB => self.state = State::Ground,
                ESC => self.state = State::StrEsc,
                _ => {}
            },
            State::StrEsc => {
                if ch == '\\' {
                    self.state = State::Ground;
                } else {
                    self.state = State::Esc;
                    self.escape(ch);
                }
            }
        }
    }

    fn ground(&mut self, ch: char) {
        match ch {
            ESC => self.state = State::Esc,
            '\r' => {
                self.col = 0;
                self.wrap_pending = false;
            }
            '\n' | '\u{0b}' | '\u{0c}' => self.line_feed(),
            '\u{08}' => {
                self.col = self.col.saturating_sub(1);
                self.wrap_pending = false;
            }
            '\t' => {
                let next = (self.col / TAB_WIDTH + 1) * TAB_WIDTH;
                self.col = next.min(self.cols - 1);
                self.wrap_pending = false;
            }
            c if (c as u32) < 0x20 || c == '\u{7f}' => {}
            c if (0x80..0xa0).contains(&(c as u32)) => {}
            c => self.put_char(c),
        }
    }

    fn escape(&mut self, ch: char) {
        self.state = State::Ground;
        match ch {
            '[' => {
                self.state = State::Csi;
                self.csi.clear();
            }
            ']' | 'P' | '_' | '^' | 'X' => self.state = State::Str,
            '7' => self.saved = (self.row, self.col),
            '8' => {
                self.row = self.saved.0.min(self.rows - 1);
                self.col = self.saved.1.min(self.cols - 1);
                self.wrap_pending = false;
            }
            'D' => self.line_feed(),
            'E' => {
                self.col = 0;
                self.line_feed();
            }
            'M' => self.reverse_index(),
            'c' => self.reset(),
            ESC => self.state = State::Esc,
            c if ('\u{20}'..='\u{2f}').contains(&c) => self.state = State::EscInter,
            _ => {}
        }
    }

    fn csi_byte(&mut self, ch: char) {
        match ch {
            ESC => self.state = State::Esc,
            CAN | SUB => self.state = State::Ground,
            '\r' | '\n' | '\u{08}' | '\t' => self.ground(ch),
            c if (c as u32) < 0x20 => {}
            c if ('\u{20}'..='\u{3f}').contains(&c) => {
                if self.csi.len() < MAX_CSI_PARAM_BYTES {
                    self.csi.push(c as u8);
                }
            }
            c if ('\u{40}'..='\u{7e}').contains(&c) => {
                self.state = State::Ground;
                let raw = std::mem::take(&mut self.csi);
                self.run_csi(&raw, c);
            }
            _ => self.state = State::Ground,
        }
    }

    fn run_csi(&mut self, raw: &[u8], final_byte: char) {
        let private = raw.first() == Some(&b'?');
        let has_inter = raw.iter().any(|b| (0x20..=0x2f).contains(b));
        let params = parse_params(raw);
        let arg = |index: usize, default: usize| -> usize {
            match params.get(index) {
                Some(Some(value)) if *value > 0 => *value as usize,
                _ => default,
            }
        };
        if has_inter {
            return;
        }
        if private {
            self.private_mode(&params, final_byte);
            return;
        }
        self.wrap_pending = false;
        match final_byte {
            'A' => self.row = self.row.saturating_sub(arg(0, 1)),
            'B' => self.row = (self.row + arg(0, 1).min(self.rows)).min(self.rows - 1),
            'C' => self.col = (self.col + arg(0, 1).min(self.cols)).min(self.cols - 1),
            'D' => self.col = self.col.saturating_sub(arg(0, 1)),
            'E' => {
                self.row = (self.row + arg(0, 1).min(self.rows)).min(self.rows - 1);
                self.col = 0;
            }
            'F' => {
                self.row = self.row.saturating_sub(arg(0, 1));
                self.col = 0;
            }
            'G' => self.col = (arg(0, 1) - 1).min(self.cols - 1),
            'd' => self.row = (arg(0, 1) - 1).min(self.rows - 1),
            'H' | 'f' => {
                self.row = (arg(0, 1) - 1).min(self.rows - 1);
                self.col = (arg(1, 1) - 1).min(self.cols - 1);
            }
            'J' => self.erase_display(params.first().copied().flatten().unwrap_or(0)),
            'K' => self.erase_line(params.first().copied().flatten().unwrap_or(0)),
            'L' => self.insert_lines(arg(0, 1)),
            'M' => self.delete_lines(arg(0, 1)),
            '@' => self.insert_chars(arg(0, 1)),
            'P' => self.delete_chars(arg(0, 1)),
            'X' => self.erase_chars(arg(0, 1)),
            'S' => self.scroll_up(arg(0, 1)),
            'T' => self.scroll_down(arg(0, 1)),
            _ => {}
        }
    }

    fn private_mode(&mut self, params: &[Option<u32>], final_byte: char) {
        let on = match final_byte {
            'h' => true,
            'l' => false,
            _ => return,
        };
        for param in params.iter().flatten() {
            match param {
                1049 => self.switch_alt(on, true),
                1047 | 47 => self.switch_alt(on, false),
                _ => {}
            }
        }
    }

    fn switch_alt(&mut self, on: bool, save_cursor: bool) {
        if on == self.use_alt {
            return;
        }
        if on {
            if save_cursor {
                self.saved = (self.row, self.col);
            }
            self.alt = blank_grid(self.cols, self.rows);
            self.use_alt = true;
        } else {
            self.use_alt = false;
            if save_cursor {
                self.row = self.saved.0.min(self.rows - 1);
                self.col = self.saved.1.min(self.cols - 1);
            }
        }
        self.wrap_pending = false;
    }

    fn reset(&mut self) {
        self.main = blank_grid(self.cols, self.rows);
        self.alt = blank_grid(self.cols, self.rows);
        self.use_alt = false;
        self.row = 0;
        self.col = 0;
        self.saved = (0, 0);
        self.wrap_pending = false;
    }

    fn put_char(&mut self, ch: char) {
        let width = char_width(ch);
        if width == 0 {
            return;
        }
        if self.wrap_pending {
            self.col = 0;
            self.line_feed();
            self.wrap_pending = false;
        }
        if self.col + width > self.cols {
            self.col = 0;
            self.line_feed();
        }
        let (row, col) = (self.row, self.col);
        let cells = &mut self.grid()[row];
        cells[col] = ch;
        if width == 2 {
            cells[col + 1] = '\0';
        }
        self.col += width;
        if self.col >= self.cols {
            self.col = self.cols - 1;
            self.wrap_pending = true;
        }
    }

    fn line_feed(&mut self) {
        if self.row + 1 >= self.rows {
            self.scroll_up(1);
        } else {
            self.row += 1;
        }
    }

    fn reverse_index(&mut self) {
        if self.row == 0 {
            self.scroll_down(1);
        } else {
            self.row -= 1;
        }
    }

    fn scroll_up(&mut self, count: usize) {
        let (rows, cols) = (self.rows, self.cols);
        let grid = self.grid();
        for _ in 0..count.min(rows) {
            grid.remove(0);
            grid.push(vec![' '; cols]);
        }
    }

    fn scroll_down(&mut self, count: usize) {
        let (rows, cols) = (self.rows, self.cols);
        let grid = self.grid();
        for _ in 0..count.min(rows) {
            grid.pop();
            grid.insert(0, vec![' '; cols]);
        }
    }

    fn insert_lines(&mut self, count: usize) {
        let (row, rows, cols) = (self.row, self.rows, self.cols);
        let grid = self.grid();
        for _ in 0..count.min(rows - row) {
            grid.pop();
            grid.insert(row, vec![' '; cols]);
        }
    }

    fn delete_lines(&mut self, count: usize) {
        let (row, rows, cols) = (self.row, self.rows, self.cols);
        let grid = self.grid();
        for _ in 0..count.min(rows - row) {
            grid.remove(row);
            grid.push(vec![' '; cols]);
        }
    }

    fn insert_chars(&mut self, count: usize) {
        let (row, col, cols) = (self.row, self.col, self.cols);
        let cells = &mut self.grid()[row];
        for _ in 0..count.min(cols - col) {
            cells.pop();
            cells.insert(col, ' ');
        }
    }

    fn delete_chars(&mut self, count: usize) {
        let (row, col, cols) = (self.row, self.col, self.cols);
        let cells = &mut self.grid()[row];
        for _ in 0..count.min(cols - col) {
            cells.remove(col);
            cells.push(' ');
        }
    }

    fn erase_chars(&mut self, count: usize) {
        let (row, col, cols) = (self.row, self.col, self.cols);
        let end = (col + count).min(cols);
        for cell in &mut self.grid()[row][col..end] {
            *cell = ' ';
        }
    }

    fn erase_line(&mut self, mode: u32) {
        let (row, col, cols) = (self.row, self.col, self.cols);
        let (start, end) = match mode {
            0 => (col, cols),
            1 => (0, col + 1),
            2 => (0, cols),
            _ => return,
        };
        for cell in &mut self.grid()[row][start..end] {
            *cell = ' ';
        }
    }

    fn erase_display(&mut self, mode: u32) {
        let (row, rows) = (self.row, self.rows);
        match mode {
            0 => {
                self.erase_line(0);
                for index in row + 1..rows {
                    self.grid()[index].fill(' ');
                }
            }
            1 => {
                for index in 0..row {
                    self.grid()[index].fill(' ');
                }
                self.erase_line(1);
            }
            2 | 3 => {
                for line in self.grid().iter_mut() {
                    line.fill(' ');
                }
            }
            _ => {}
        }
    }
}

/// Split CSI parameter bytes into numbers; an empty field is `None`.
/// A leading private marker (`?`, `>`, `<`, `=`) is dropped.
fn parse_params(raw: &[u8]) -> Vec<Option<u32>> {
    let body: Vec<u8> = raw
        .iter()
        .copied()
        .skip_while(|b| matches!(b, b'?' | b'>' | b'<' | b'='))
        .collect();
    body.split(|b| *b == b';' || *b == b':')
        .map(|field| {
            let mut value: Option<u32> = None;
            for byte in field.iter().filter(|b| b.is_ascii_digit()) {
                let digit = u32::from(byte - b'0');
                value = Some(value.unwrap_or(0).saturating_mul(10).saturating_add(digit));
            }
            value
        })
        .collect()
}

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

struct Options {
    cols: usize,
    rows: usize,
    dump: bool,
    markers: Option<String>,
}

fn usage_error(message: &str) -> ! {
    eprintln!("hooks-screen: {message}");
    eprintln!("usage: hooks-screen [--cols N] [--rows N] [--dump] [--markers FILE] < bytes");
    exit(EXIT_USAGE);
}

fn parse_dim(value: Option<String>, flag: &str) -> usize {
    match value.as_deref().map(str::parse::<usize>) {
        Some(Ok(number)) => number,
        _ => usage_error(&format!("{flag} needs a whole number")),
    }
}

fn parse_args(args: impl Iterator<Item = String>) -> Options {
    let mut options = Options {
        cols: DEFAULT_COLS,
        rows: DEFAULT_ROWS,
        dump: false,
        markers: None,
    };
    let mut args = args;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--cols" => options.cols = parse_dim(args.next(), "--cols"),
            "--rows" => options.rows = parse_dim(args.next(), "--rows"),
            "--dump" => options.dump = true,
            "--markers" => match args.next() {
                Some(path) => options.markers = Some(path),
                None => usage_error("--markers needs a file"),
            },
            other => usage_error(&format!("unknown argument: {other}")),
        }
    }
    options
}

fn main() {
    let options = parse_args(env::args().skip(1));
    let markers = match &options.markers {
        None => builtin_markers(),
        Some(path) => match fs::read_to_string(path).map_err(|e| e.to_string()) {
            Ok(text) => match parse_markers(&text) {
                Ok(markers) => markers,
                Err(message) => usage_error(&message),
            },
            Err(message) => usage_error(&format!("cannot read {path}: {message}")),
        },
    };

    let mut input = Vec::new();
    if let Err(err) = io::stdin().take(MAX_INPUT_BYTES).read_to_end(&mut input) {
        eprintln!("hooks-screen: stdin read failed, using the bytes read so far: {err}");
    }
    let mut screen = Screen::new(options.cols, options.rows);
    screen.feed(&input);
    let rows = screen.rows();

    let mut out = String::new();
    if options.dump {
        for row in &rows {
            out.push_str(row);
            out.push('\n');
        }
    } else {
        out.push_str(classify(&rows, &markers).word());
        out.push('\n');
    }
    if let Err(err) = io::stdout().write_all(out.as_bytes()) {
        eprintln!("hooks-screen: write failed: {err}");
    }
}
