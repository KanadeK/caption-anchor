import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from caption_anchor import CaptionError, Limits, compare, read_srt


def stamp(value):
    seconds, milliseconds = divmod(value, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def document(cues):
    return (
        "\n\n".join(
            f"{identity}\n{stamp(start)} --> {stamp(end)}\n{text}"
            for identity, start, end, text in cues
        )
        + "\n"
    )


BASE = [(1, 1000, 2500, "Original synthetic caption."), (2, 3000, 4500, "Another line.")]


class CaptionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.counter = 0

    def source(self, text, **kwargs):
        self.counter += 1
        path = self.root / f"{self.counter}.srt"
        path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        return read_srt(path, **kwargs)

    def check(self, before=BASE, after=BASE, **kwargs):
        return compare(self.source(document(before)), self.source(document(after)), **kwargs)

    def test_identical_is_clean(self):
        report = self.check()
        self.assertTrue(report["passed"])
        self.assertEqual(report["compared_unambiguous_cues"], 2)

    def test_translation_changes_text_only(self):
        translated = [(1, 1000, 2500, "第一条字幕。"), (2, 3000, 4500, "Deuxième ligne.")]
        self.assertTrue(self.check(after=translated)["passed"])

    def test_start_delta_has_numeric_evidence(self):
        report = self.check(after=[(1, 1001, 2500, "translated"), BASE[1]])
        finding = report["findings"][0]
        self.assertEqual(finding["code"], "timing-changed")
        self.assertEqual(finding["start_delta_ms"], 1)
        self.assertEqual(finding["end_delta_ms"], 0)

    def test_end_delta_is_independent(self):
        self.assertFalse(self.check(after=[(1, 1000, 2499, "translated"), BASE[1]])["passed"])

    def test_missing_and_added_cues(self):
        self.assertIn("cue-missing", [f["code"] for f in self.check(after=BASE[:1])["findings"]])
        after = BASE + [(3, 5000, 6000, "extra")]
        self.assertIn("cue-added", [f["code"] for f in self.check(after=after)["findings"]])

    def test_renumbering_is_not_silent_alignment(self):
        report = self.check(after=[(3, 1000, 2500, "translated"), BASE[1]])
        self.assertFalse(report["passed"])
        self.assertEqual({f["code"] for f in report["findings"]}, {"cue-missing", "cue-added"})

    def test_reordered_cues_report_order(self):
        report = self.check(after=list(reversed(BASE)))
        self.assertIn("cue-order-changed", [f["code"] for f in report["findings"]])
        self.assertIn("start-order", [f["code"] for f in report["findings"]])

    def test_duplicate_ids_are_never_overwritten(self):
        report = self.check(after=[BASE[0], (1, 3000, 4500, "duplicate")])
        self.assertIn("duplicate-cue-id", [f["code"] for f in report["findings"]])
        self.assertEqual(report["compared_unambiguous_cues"], 0)

    def test_bad_baseline_also_fails(self):
        bad = [(1, 1000, 500, "backwards")]
        report = self.check(before=bad, after=bad)
        self.assertFalse(report["passed"])
        self.assertEqual(report["findings"][0]["side"], "before")

    def test_zero_duration_fails(self):
        self.assertFalse(self.check(after=[(1, 1000, 1000, "empty duration"), BASE[1]])["passed"])

    def test_intentional_overlap_and_equal_starts_allowed(self):
        overlap = [(1, 1000, 4000, "speaker one"), (2, 1000, 3000, "speaker two")]
        self.assertTrue(self.check(before=overlap, after=overlap)["passed"])

    def test_explicit_positive_global_shift(self):
        shifted = [(identity, start + 500, end + 500, text) for identity, start, end, text in BASE]
        self.assertFalse(self.check(after=shifted)["passed"])
        self.assertTrue(self.check(after=shifted, shift_ms=500)["passed"])

    def test_explicit_negative_global_shift(self):
        shifted = [(identity, start - 500, end - 500, text) for identity, start, end, text in BASE]
        self.assertTrue(self.check(after=shifted, shift_ms=-500)["passed"])

    def test_shift_underflow_is_failure(self):
        report = self.check(shift_ms=-2000, tolerance_ms=99999)
        self.assertIn("shift-before-zero", [f["code"] for f in report["findings"]])

    def test_tolerance_boundary_is_inclusive(self):
        after = [(1, 1005, 2495, "text"), BASE[1]]
        self.assertTrue(self.check(after=after, tolerance_ms=5)["passed"])
        self.assertFalse(self.check(after=after, tolerance_ms=4)["passed"])

    def test_invalid_options_rejected(self):
        for kwargs in [
            {"tolerance_ms": -1},
            {"max_findings": 0},
            {"shift_ms": 0.5},
            {"shift_ms": True},
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(CaptionError):
                self.check(**kwargs)

    def test_empty_and_markup_only_captions_fail(self):
        for text in ["", "<i> </i>", "<!-- comment -->", "&#32;", "<b>\u200b\u200d</b>"]:
            with self.subTest(text=text):
                report = self.check(after=[(1, 1000, 2500, text), BASE[1]])
                self.assertIn("empty-caption", [f["code"] for f in report["findings"]])

    def test_markup_and_html_entities_visible(self):
        after = [(1, 1000, 2500, "<i>翻译 &amp; text</i>"), BASE[1]]
        self.assertTrue(self.check(after=after)["passed"])

    def test_multiline_and_unicode_line_separator_are_text(self):
        after = [(1, 1000, 2500, "first\nsecond\u2028third"), BASE[1]]
        self.assertTrue(self.check(after=after)["passed"])

    def test_crlf_cr_bom_and_missing_final_newline(self):
        before = self.source(document(BASE))
        for newline in ("\r\n", "\r", "\n"):
            with self.subTest(newline=repr(newline)):
                data = ("\ufeff" + document(BASE).rstrip("\n").replace("\n", newline)).encode(
                    "utf-8"
                )
                self.assertTrue(compare(before, self.source(data))["passed"])

    def test_counter_need_not_start_at_one(self):
        clips = [(100, 1000, 2500, "clip"), (101, 3000, 4500, "clip")]
        self.assertTrue(self.check(before=clips, after=clips)["passed"])

    def test_zero_unicode_and_negative_counter_rejected(self):
        for counter in ("0", "-1", "一", "١"):
            with self.subTest(counter=counter), self.assertRaises(CaptionError):
                self.source(document(BASE).replace("1\n", counter + "\n", 1))

    def test_timestamp_subset_is_strict(self):
        for replacement in [
            "00:60:00,000",
            "00:00:60,000",
            "00:00:01.000",
            "0:00:01,000",
            "-00:00:01,000",
        ]:
            with self.subTest(replacement=replacement), self.assertRaises(CaptionError):
                self.source(document(BASE).replace("00:00:01,000", replacement, 1))

    def test_position_annotations_rejected(self):
        with self.assertRaises(CaptionError):
            self.source(document(BASE).replace("00:00:02,500", "00:00:02,500 X1:10 X2:20", 1))

    def test_missing_blank_separator_is_detected(self):
        with self.assertRaises(CaptionError):
            self.source(document(BASE).replace("\n\n2\n", "\n2\n"))

    def test_utf16_and_invalid_utf8_rejected(self):
        for raw in [document(BASE).encode("utf-16"), b"\xff"]:
            with self.subTest(raw=raw[:5]), self.assertRaises(CaptionError):
                self.source(raw)

    def test_controls_rejected(self):
        with self.assertRaises(CaptionError):
            self.source(document(BASE).replace("Another", "\x00Another"))

    def test_byte_cue_line_budgets(self):
        for limits in [
            Limits(bytes=10),
            Limits(cues=1),
            Limits(line_characters=10),
            Limits(cues=0),
        ]:
            with self.subTest(limits=limits), self.assertRaises(CaptionError):
                self.source(document(BASE), limits=limits)

    def test_empty_baseline_rejected_but_empty_result_reports_loss(self):
        with self.assertRaises(CaptionError):
            compare(self.source(""), self.source(document(BASE)))
        report = compare(self.source(document(BASE)), self.source(""))
        self.assertFalse(report["passed"])
        self.assertEqual(report["errors"], 2)

    def test_findings_cap_preserves_total_and_failure(self):
        report = self.check(after=[], max_findings=1)
        self.assertEqual(report["errors"], 2)
        self.assertTrue(report["findings_truncated"])

    def test_no_caption_text_in_structures_or_report(self):
        private = [(1, 1000, 2500, "SECRET_CAPTION")]
        source = self.source(document(private))
        self.assertNotIn("SECRET_CAPTION", repr(source))
        self.assertNotIn("SECRET_CAPTION", json.dumps(compare(source, self.source(""))))

    def test_fingerprint_identifies_exact_bytes(self):
        before = self.source(document(BASE))
        after = self.source(document(BASE) + "\n")
        self.assertNotEqual(before.sha256, after.sha256)
        self.assertTrue(compare(before, after)["passed"])

    def test_three_digit_hours_and_arrow_whitespace(self):
        data = "1\n100:00:00,000\t-->  100:00:01,000\nLong recording\n"
        source = self.source(data)
        self.assertEqual(source.cues[0].start, 360000000)
        self.assertTrue(compare(source, source)["passed"])

    def test_cli_real_files_and_exit_codes(self):
        script = Path(__file__).resolve().parents[1] / "caption_anchor.py"
        before, after = self.root / "before.srt", self.root / "after.srt"
        before.write_text(document(BASE), encoding="utf-8")
        after.write_text(document([(1, 1000, 2500, "译文"), BASE[1]]), encoding="utf-8")
        command = [sys.executable, "-I", "-S", str(script), str(before), str(after), "--json"]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["passed"])
        after.write_text(document(BASE[:1]), encoding="utf-8")
        self.assertEqual(subprocess.run(command, capture_output=True, check=False).returncode, 1)
        after.write_text("SECRET_BAD_INPUT", encoding="utf-8")
        invalid = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(invalid.returncode, 2)
        self.assertNotIn("SECRET_BAD_INPUT", invalid.stderr)

    def test_cli_explicit_shift(self):
        script = Path(__file__).resolve().parents[1] / "caption_anchor.py"
        before, after = self.root / "a.srt", self.root / "b.srt"
        before.write_text(document(BASE), encoding="utf-8")
        shifted = [(identity, start + 500, end + 500, text) for identity, start, end, text in BASE]
        after.write_text(document(shifted), encoding="utf-8")
        command = [
            sys.executable,
            "-I",
            "-S",
            str(script),
            str(before),
            str(after),
            "--shift-ms",
            "500",
        ]
        self.assertEqual(subprocess.run(command, capture_output=True, check=False).returncode, 0)


if __name__ == "__main__":
    unittest.main()
