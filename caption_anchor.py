"""Verify SRT cue identities and timestamps after text-only translation or review."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

__version__ = "0.1.0"
STAMP = r"([0-9]{2,3}):([0-5][0-9]):([0-5][0-9]),([0-9]{3})"
TIMING = re.compile(rf"{STAMP}[ \t]+-->[ \t]+{STAMP}")


class CaptionError(ValueError):
    """SRT input is unsupported, malformed, or over budget."""


@dataclass(frozen=True)
class Limits:
    bytes: int = 16 * 1024 * 1024
    cues: int = 100_000
    line_characters: int = 65_536


@dataclass(frozen=True)
class Cue:
    id: int
    start: int
    end: int
    line: int
    visible: bool


@dataclass(frozen=True)
class Captions:
    cues: tuple[Cue, ...]
    sha256: str


class _Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.visible = False

    def handle_data(self, data):
        self.visible = self.visible or any(
            not c.isspace() and unicodedata.category(c) not in {"Cc", "Cf", "Cs"} for c in data
        )


def _milliseconds(values: tuple[str, ...]) -> int:
    hour, minute, second, millisecond = map(int, values)
    return ((hour * 60 + minute) * 60 + second) * 1000 + millisecond


def read_srt(path: Path, limits: Limits | None = None) -> Captions:
    """Parse strict UTF-8 SRT; returned structures deliberately contain no caption text."""
    limits = limits or Limits()
    if min(vars(limits).values()) < 1:
        raise CaptionError("all limits must be positive")
    if not path.is_file():
        raise CaptionError("SRT input must be a regular file")
    with path.open("rb") as stream:
        raw = stream.read(limits.bytes + 1)
    if len(raw) > limits.bytes:
        raise CaptionError("SRT byte budget exceeded")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise CaptionError("only UTF-8 SRT (optional BOM) is supported") from exc
    if any(ord(c) < 32 and c not in "\r\n\t" for c in text):
        raise CaptionError("unsupported control character in SRT")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if any(len(line) > limits.line_characters for line in lines):
        raise CaptionError("SRT line character budget exceeded")
    cues = []
    position = 0
    while position < len(lines):
        if not lines[position].strip(" \t"):
            position += 1
            continue
        first = position
        block = []
        while position < len(lines) and lines[position].strip(" \t"):
            block.append(lines[position])
            position += 1
        if len(block) < 2:
            raise CaptionError(f"line {first + 1}: cue requires a counter and timing line")
        counter = block[0].strip(" \t")
        if not re.fullmatch(r"[0-9]{1,9}", counter) or int(counter) < 1:
            raise CaptionError(f"line {first + 1}: counter must be a positive ASCII integer")
        timing = TIMING.fullmatch(block[1].strip(" \t"))
        if not timing:
            raise CaptionError(f"line {first + 2}: expected HH:MM:SS,mmm --> HH:MM:SS,mmm")
        if any(TIMING.fullmatch(line.strip(" \t")) for line in block[2:]):
            raise CaptionError(
                f"line {first + 1}: timing in cue text; possible missing blank separator"
            )
        visible = _Visible()
        visible.feed("\n".join(block[2:]))
        visible.close()
        cues.append(
            Cue(
                int(counter),
                _milliseconds(timing.groups()[:4]),
                _milliseconds(timing.groups()[4:]),
                first + 1,
                visible.visible,
            )
        )
        if len(cues) > limits.cues:
            raise CaptionError("SRT cue count budget exceeded")
    return Captions(tuple(cues), hashlib.sha256(raw).hexdigest())


def compare(
    before: Captions,
    after: Captions,
    *,
    shift_ms: int = 0,
    tolerance_ms: int = 0,
    max_findings: int = 1_000,
) -> dict:
    """Require stable cue identities/order and expected timing; never compare words."""
    if not before.cues:
        raise CaptionError("baseline must contain at least one cue")
    if any(type(v) is not int for v in (shift_ms, tolerance_ms, max_findings)):
        raise CaptionError("shift, tolerance and finding limit must be integers")
    if tolerance_ms < 0 or max_findings < 1:
        raise CaptionError("tolerance must be nonnegative and finding limit positive")
    findings = []
    errors = 0
    worst = 0
    compared = 0

    def emit(code: str, **details):
        nonlocal errors
        errors += 1
        if len(findings) < max_findings:
            findings.append({"code": code, **details})

    maps = []
    for side, source in (("before", before), ("after", after)):
        ids: dict[int, list[Cue]] = defaultdict(list)
        previous = None
        for cue in source.cues:
            ids[cue.id].append(cue)
            location = {"side": side, "cue": cue.id, "line": cue.line}
            if cue.end <= cue.start:
                emit("invalid-duration", **location)
            if not cue.visible:
                emit("empty-caption", **location)
            if previous is not None and cue.start < previous:
                emit("start-order", **location)
            previous = cue.start
        for identity, cues in ids.items():
            if len(cues) > 1:
                emit("duplicate-cue-id", side=side, cue=identity, lines=[c.line for c in cues])
        maps.append(ids)
    old, new = maps
    for identity, cues in old.items():
        if identity not in new:
            emit("cue-missing", cue=identity, before_line=cues[0].line)
    for identity, cues in new.items():
        if identity not in old:
            emit("cue-added", cue=identity, after_line=cues[0].line)
    shared = {
        identity
        for identity in old.keys() & new.keys()
        if len(old[identity]) == len(new[identity]) == 1
    }
    order_before = [cue.id for cue in before.cues if cue.id in shared]
    order_after = [cue.id for cue in after.cues if cue.id in shared]
    if order_before != order_after:
        position = next(
            i
            for i, pair in enumerate(zip(order_before, order_after, strict=True))
            if pair[0] != pair[1]
        )
        emit(
            "cue-order-changed",
            shared_position=position + 1,
            before_cue=order_before[position],
            after_cue=order_after[position],
        )
    for identity in sorted(shared):
        original, replacement = old[identity][0], new[identity][0]
        expected_start, expected_end = original.start + shift_ms, original.end + shift_ms
        if expected_start < 0 or expected_end < 0:
            emit("shift-before-zero", cue=identity)
            continue
        start_delta = replacement.start - expected_start
        end_delta = replacement.end - expected_end
        worst = max(worst, abs(start_delta), abs(end_delta))
        compared += 1
        if abs(start_delta) > tolerance_ms or abs(end_delta) > tolerance_ms:
            emit(
                "timing-changed",
                cue=identity,
                before_line=original.line,
                after_line=replacement.line,
                start_delta_ms=start_delta,
                end_delta_ms=end_delta,
            )
    return {
        "schema_version": 1,
        "tool_version": __version__,
        "before_sha256": before.sha256,
        "after_sha256": after.sha256,
        "before_cues": len(before.cues),
        "after_cues": len(after.cues),
        "compared_unambiguous_cues": compared,
        "expected_shift_ms": shift_ms,
        "tolerance_ms": tolerance_ms,
        "max_absolute_timing_error_ms": worst,
        "errors": errors,
        "findings_truncated": errors > len(findings),
        "findings": findings,
        "passed": errors == 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument(
        "--shift-ms", type=int, default=0, help="explicit expected global timing shift"
    )
    parser.add_argument(
        "--tolerance-ms", type=int, default=0, help="allowed error for each endpoint"
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = compare(
            read_srt(args.before),
            read_srt(args.after),
            shift_ms=args.shift_ms,
            tolerance_ms=args.tolerance_ms,
        )
    except (OSError, ValueError) as exc:
        message = str(exc) if isinstance(exc, CaptionError) else "cannot read SRT input"
        print(json.dumps({"error": message}, ensure_ascii=True), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        print(
            f"compared={report['compared_unambiguous_cues']}; errors={report['errors']}; max error={report['max_absolute_timing_error_ms']} ms"
        )
        for finding in report["findings"]:
            print(json.dumps(finding, ensure_ascii=True))
    return int(not report["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
