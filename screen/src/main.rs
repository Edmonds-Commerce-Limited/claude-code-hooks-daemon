//! hooks-screen -- render a terminal byte stream and say which Claude Code
//! view it shows.
//!
//! Plan 00538 Phase 2. A hooks-daemon component used by the ccy supervisor's
//! main-thread focus check (`.claude/ccy/claude-supervise.py`). Unlike the
//! std-only relay (relay/hooks_relay.rs), this binary depends on ONE crate,
//! `vt100`, vendored under screen/vendor/ (owner ruling, Plan 00538): terminal
//! emulation is a correctness problem a hand-written emulator got partly
//! wrong. Built offline with cargo (see screen/build.sh). No `#[allow]`
//! attributes.
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
//! BOUNDARIES (keep them, so the renderer stays swappable without touching
//! the classifier or the CLI):
//!   - `Screen::feed(&[u8])` and `Screen::rows() -> Vec<String>` are the whole
//!     emulator interface; `Screen` is a thin wrapper over `vt100::Parser`
//!     with no scrollback.
//!   - `classify(&[String], &[Marker]) -> Verdict` sees only rows.

use std::env;
use std::fs;
use std::io::{self, Read, Write};
use std::num::NonZeroU16;
use std::process::exit;

const DEFAULT_COLS: usize = 80;
const DEFAULT_ROWS: usize = 24;
const MIN_DIM: usize = 2;
const MAX_DIM: usize = 1000;
const MAX_INPUT_BYTES: u64 = 8 * 1024 * 1024;
const NO_SCROLLBACK: usize = 0;
const EXIT_USAGE: i32 = 2;

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
// Emulator: the vendored vt100 crate behind the Screen boundary.
// ---------------------------------------------------------------------------

/// Clamp a requested dimension into MIN_DIM..=MAX_DIM as a non-zero u16.
fn dimension(requested: usize) -> NonZeroU16 {
    let clamped = u16::try_from(requested.clamp(MIN_DIM, MAX_DIM)).unwrap_or(u16::MAX);
    NonZeroU16::new(clamped).unwrap_or(NonZeroU16::MIN)
}

struct Screen {
    cols: NonZeroU16,
    parser: vt100::Parser,
}

impl Screen {
    fn new(cols: usize, rows: usize) -> Screen {
        let cols = dimension(cols);
        Screen {
            cols,
            parser: vt100::Parser::new(dimension(rows), cols, NO_SCROLLBACK),
        }
    }

    /// Apply one chunk of terminal output.
    fn feed(&mut self, bytes: &[u8]) {
        self.parser.process(bytes);
    }

    /// The active screen as text rows, trailing blanks trimmed.
    fn rows(&self) -> Vec<String> {
        self.parser
            .screen()
            .rows(0, self.cols.get())
            .map(|line| line.trim_end_matches(' ').to_string())
            .collect()
    }
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
