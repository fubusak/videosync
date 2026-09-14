"""Optional regressions using the user's local recordings (not stored in Git)."""
from pathlib import Path
import unittest

from videosync import decode_audio, detect_beep_auto, find_beep_candidates, find_ffmpeg
from beep_batch import select_batch


class RecordingTests(unittest.TestCase):
    def test_houpacka_start_beeps(self):
        root = Path(__file__).resolve().parents[1]
        paths = [root / 'hopacka_m.mp4', root / 'houpacka_v.mp4']
        if not all(path.is_file() for path in paths):
            self.skipTest('Local houpacka recordings are not present.')
        for path, expected in zip(paths, [1.19, 3.70]):
            with self.subTest(path=path.name):
                samples = decode_audio(find_ffmpeg(), path, 10, 24000)
                onset, frequency = detect_beep_auto(samples, 24000)
                self.assertAlmostEqual(onset, expected, delta=.03)
                self.assertAlmostEqual(frequency, 1507, delta=15)

    def test_batch_matching_preserves_both_real_start_beeps(self):
        root = Path(__file__).resolve().parents[1]
        pairs = [('hopacka_m.mp4', 'houpacka_v.mp4', [1.19, 3.70]),
                 ('PXL_20260913_124051052.TS.mp4', 'PXL_20260913_125101103.TS.mp4', [1.265, .35])]
        for first, second, expected in pairs:
            if not (root / first).exists() or not (root / second).exists():
                self.skipTest('Local sample recordings are not present.')
            candidates = [find_beep_candidates(decode_audio(find_ffmpeg(), root / path, 30, 24000), 24000)
                          for path in (first, second)]
            matched = select_batch(candidates)
            for actual, wanted in zip(matched, expected):
                self.assertAlmostEqual(actual.onset, wanted, delta=.03)
