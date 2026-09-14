import unittest

import numpy as np

from videosync import detect_beep


class DetectionTests(unittest.TestCase):
    rate = 16000

    def signal(self, onset=1.237, duration=0.18, frequency=2700, noise=0.01):
        rng = np.random.default_rng(42)
        samples = rng.normal(0, noise, self.rate * 4)
        start, count = round(onset * self.rate), round(duration * self.rate)
        samples[start:start + count] += 0.5 * np.sin(
            2 * np.pi * frequency * np.arange(count) / self.rate)
        return samples

    def test_onset_in_noise(self):
        self.assertAlmostEqual(detect_beep(self.signal(), self.rate), 1.237, delta=0.015)

    def test_frequency_tolerance(self):
        self.assertAlmostEqual(detect_beep(self.signal(frequency=2740), self.rate),
                               1.237, delta=0.015)

    def test_custom_frequency(self):
        self.assertAlmostEqual(detect_beep(self.signal(frequency=1200), self.rate,
                                          frequency=1200), 1.237, delta=0.015)

    def test_opposing_stereo_phase(self):
        tone = self.signal()
        self.assertAlmostEqual(detect_beep(np.column_stack([tone, -tone]), self.rate),
                               1.237, delta=0.015)

    def test_first_beep_even_when_later_beep_is_louder(self):
        samples = self.signal(onset=0.5) + 2 * self.signal(onset=2.0)
        self.assertAlmostEqual(detect_beep(samples, self.rate), 0.5, delta=0.015)

    def test_later_loud_beep_does_not_hide_earlier_quiet_beep(self):
        samples = .04 * self.signal(onset=.5, noise=0) + self.signal(onset=2, noise=0)
        self.assertAlmostEqual(detect_beep(samples, self.rate), .5, delta=.015)

    def test_beep_at_start(self):
        self.assertAlmostEqual(detect_beep(self.signal(onset=0), self.rate), 0, delta=0.015)

    def test_harmonics_do_not_delay_detection(self):
        samples = self.signal() + 2 * self.signal(frequency=5400)
        self.assertAlmostEqual(detect_beep(samples, self.rate), 1.237, delta=0.015)

    def test_rejects_missing_beeps(self):
        cases = [np.zeros(self.rate), self.signal(frequency=1800),
                 self.signal(duration=0.01), np.random.default_rng(3).normal(0, .3, self.rate)]
        for samples in cases:
            with self.subTest(samples=samples.shape):
                with self.assertRaises(ValueError):
                    detect_beep(samples, self.rate)


if __name__ == '__main__':
    unittest.main()
