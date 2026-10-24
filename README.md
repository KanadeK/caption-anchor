# caption-anchor

Catch dropped cues and timestamp changes after translating or reviewing SRT
subtitles. Keep a trusted original as a baseline; verify numbering, order and
millisecond timing while allowing the words to change. Reports contain no subtitle
body text. Python 3.11+, offline, no runtime dependencies.

Editors and translation systems can change cue structure unintentionally. A text
diff is noisy when every sentence changes. This CLI checks the structural contract
and gives cue/line locations and numeric timing deltas for failures.

## Install and try

```sh
git clone https://github.com/KanadeK/caption-anchor.git
cd caption-anchor
python -m venv .venv
# Linux/macOS:
.venv/bin/python -m pip install .
.venv/bin/caption-anchor examples/before.srt examples/after.srt --json
# Windows PowerShell:
.venv/Scripts/python.exe -m pip install .
.venv/Scripts/caption-anchor.exe examples/before.srt examples/after.srt --json
```

The **synthetic** English/Chinese example preserves two cues and passes with
exit **0**. No media or network is needed. An intentionally broken example changes
one end time and drops the second cue:

```sh
python caption_anchor.py examples/before.srt examples/broken.srt --json
```

Expect `cue-missing` and `timing-changed`, with exit **1**. Running the source
module directly requires no installation.

For your own subtitles:

```sh
caption-anchor original.srt translated.srt --json
# An intentional 500 ms delay, with up to 5 ms endpoint rounding error:
caption-anchor original.srt translated.srt --shift-ms 500 --tolerance-ms 5 --json
```

Default shift and tolerance are both zero. A positive shift means later;
negative means earlier. Each candidate start/end is compared with its original
endpoint plus the specified shift. The tolerance is inclusive. A shift before
time zero fails. A large tolerance weakens the contract; choose it deliberately.

## Contract and automation

Both files are checked for duplicate IDs, visible-empty captions, nonpositive
durations and decreasing start times. Every original cue ID must remain, no
extra IDs may appear, and the relative order of unambiguous shared IDs must stay
the same. IDs are positive integers; they need not start at 1 or be contiguous.
The program never guesses a match after renumbering or silently overwrites a
duplicate ID. Intentional overlaps and equal start times are allowed.

| Finding | Meaning |
|---|---|
| `cue-missing` / `cue-added` | Structural cue loss or gain |
| `duplicate-cue-id` | Ambiguous numbering in either input |
| `cue-order-changed` | Shared cue order differs |
| `timing-changed` | Start or end exceeds the declared tolerance |
| `invalid-duration` / `start-order` | Invalid timeline in either input |
| `empty-caption` | No visible text under the documented heuristic |
| `shift-before-zero` | Declared expected shift creates a negative timestamp |

Exit **0** means this structural/timing contract passed, **1** means violations,
and **2** means unreadable, malformed, unsupported or over-budget input/options.
Use the exit status to gate your existing build; no GitHub permissions or secrets
are needed. JSON schema version is `1`. Findings include cue IDs, 1-based source
line numbers and numeric timing deltas, with no caption bodies or local paths.
Input SHA-256 fingerprints identify the exact source bytes, even when differences
are only line endings. These fingerprints and timing data are not anonymization.

## Supported subset and limits

Version 0.1.0 deliberately accepts UTF-8 SRT, with an optional BOM and LF, CRLF
or CR newlines. Each cue has a counter line, a separate timing line using comma
milliseconds (`HH:MM:SS,mmm --> HH:MM:SS,mmm`), then text. Hours can have two or
three digits; minutes/seconds are 00–59. Blank lines separate cues; a final
newline is optional. Positional timestamp annotations, a counter on the timing
line, WebVTT/ASS, legacy encodings, negative timestamps and malformed separators
are unsupported. An empty result reports all original cues missing; an empty
baseline is invalid.

Empty-caption detection ignores HTML markup, comments, whitespace and Unicode
format/control characters, using Python's HTML parser and character categories.
It is a heuristic, not a subtitle renderer or a text-accessibility validator.
The tool does not evaluate translation accuracy, reading speed, speaker labels,
style changes, media synchronization, or correspondence after deliberate cue
splitting/merging. A passing unchanged file does not prove that any translation
was performed. It never edits subtitles or executes markup.

Limits per file: 16 MiB input, 100,000 cues, 65,536 Unicode characters per line.
At most 1,000 findings are displayed; full error counts still determine failure.
Only inspect authorized local files using a trusted interpreter. No network,
telemetry, automatic repair, or background process is used.

Uninstall with `.venv/bin/python -m pip uninstall caption-anchor` (Windows:
`.venv/Scripts/python.exe -m pip uninstall caption-anchor`). Remove `.venv` and
your disposable working copies when finished. Input files are never modified.

## Evidence and development

[Subtitle Edit #2544](https://github.com/SubtitleEdit/subtitleedit/issues/2544)
documents a historical original/translation timing mismatch and requests
consistency checking; this is evidence of the failure mode, not a claim about
the current editor. [Library of Congress SRT notes](https://www.loc.gov/preservation/digital/formats/fdd/fdd000569.shtml)
describe the format and its variants. [SrtCompare](https://github.com/ChrisTorng/SrtCompare)
focuses on text differences while ignoring numbering/timing; this tool checks
those structural properties. Use a full editor such as Subtitle Edit for
translation, repairs and visual synchronization.

Run `python -m unittest discover -s tests -v`; see [TESTING.md](TESTING.md),
[CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) and
[third-party notes](THIRD_PARTY.md). MIT licensed.

## 中文说明

用于字幕翻译或文字校订后的离线验收：保留原始 SRT，检查译文是否丢条、增条、
重复编号、改变顺序或时间戳。支持显式统一偏移和毫秒容差；有意重叠的字幕可以保留。
报告不含字幕正文，只显示编号、行号和时间差。仅支持文档规定的 UTF-8 SRT 子集，
不评价翻译质量，也不负责媒体校时。退出码 0／1／2 分别表示通过／违规／输入错误。
