# Release verification

Version 0.1.0 ran 35 unittest cases on Windows with Python 3.13.16; all passed,
none skipped. Ruff 0.17.2 lint and formatting checks passed. The wheel and source
distribution built with build 1.6.1 and setuptools 84.2.1.

Coverage includes changed-language text with identical timing, missing/added/
renumbered/duplicate cues, reordered cues, start/end drift independently,
inclusive tolerance boundaries, positive and negative expected shifts, shifts
before zero, invalid original timelines, nonpositive durations, empty/markup-only
captions, HTML entities, Unicode, multiline content, CR/LF/CRLF/BOM, missing final
newline, noncontiguous IDs, intentionally overlapping cues, strict timestamp
syntax, missing separators, encoding/control errors and resource budgets.
Reports and returned structures are checked not to contain subtitle bodies.
The findings cap does not suppress the total error count or failing status.

The built wheel was installed with `--no-index --no-deps` into a new disposable
virtual environment from outside the checkout. The installed CLI ran the
documented passing translated example, the intentionally broken example and
malformed input, verifying exit 0/1/2. All input bytes remained unchanged. The
tool was uninstalled, its launcher disappeared and the environment was removed.

CI checks Linux/macOS/Windows on Python 3.11 and 3.13; consult the actual Actions
run for its status. All sample subtitles are original synthetic fixtures, not
production/video transcripts. No playback, linguistic evaluation, visual-rendering
validation, full encoding compatibility or large-file benchmark has been performed.
