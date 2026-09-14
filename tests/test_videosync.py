import unittest

import numpy as np

from videosync import detect_beep, detect_beep_auto


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

    def test_auto_detects_range_boundaries_and_intermediate_tones(self):
        for frequency in [1200, 1234, 1500, 2173, 2700, 2975, 3000]:
            with self.subTest(frequency=frequency):
                onset, measured = detect_beep_auto(self.signal(frequency=frequency), self.rate)
                self.assertAlmostEqual(onset, 1.237, delta=.015)
                self.assertAlmostEqual(measured, frequency, delta=15)

    def test_auto_rejects_out_of_range_tones_and_noise(self):
        for samples in [self.signal(frequency=1100), self.signal(frequency=3100),
                        self.signal(frequency=1180), self.signal(frequency=3020),
                        self.signal(duration=.01), np.zeros(self.rate),
                        np.random.default_rng(7).normal(0, .2, self.rate * 3)]:
            with self.subTest(samples=samples.shape):
                with self.assertRaises(ValueError):
                    detect_beep_auto(samples, self.rate)

    def test_auto_picks_first_tone_not_louder_later_frequency(self):
        samples = .04 * self.signal(onset=.5, frequency=1500, noise=0)
        samples += self.signal(onset=2, frequency=2700, noise=0)
        onset, frequency = detect_beep_auto(samples, self.rate)
        self.assertAlmostEqual(onset, .5, delta=.015)
        self.assertAlmostEqual(frequency, 1500, delta=15)

    def test_auto_handles_opposing_phase_and_harmonics(self):
        samples = self.signal(frequency=1500) + 2 * self.signal(frequency=4500)
        onset, frequency = detect_beep_auto(np.column_stack([samples, -samples]), self.rate)
        self.assertAlmostEqual(onset, 1.237, delta=.015)
        self.assertAlmostEqual(frequency, 1500, delta=15)

    def test_auto_does_not_backdate_into_out_of_range_tone(self):
        for outside, inside in [(1100, 1200), (3100, 3000)]:
            samples = .2 * self.signal(onset=.5, duration=1.5, frequency=outside, noise=0)
            samples += self.signal(onset=2, duration=1.5, frequency=inside, noise=0)
            onset, frequency = detect_beep_auto(samples, self.rate)
            self.assertAlmostEqual(onset, 2, delta=.02)
            self.assertAlmostEqual(frequency, inside, delta=15)

    def test_detection_across_fft_batch_boundary(self):
        samples = np.zeros(self.rate * 12)
        start = round(10.237 * self.rate)
        samples[start:start + 3200] = .5 * np.sin(2 * np.pi * 2173 * np.arange(3200) / self.rate)
        onset, frequency = detect_beep_auto(samples, self.rate)
        self.assertAlmostEqual(onset, 10.237, delta=.015)
        self.assertAlmostEqual(frequency, 2173, delta=15)

    def test_auto_recovers_masked_fundamental_from_two_harmonics(self):
        rng = np.random.default_rng(84)
        samples = np.clip(rng.normal(0, .2, self.rate * 4), -.4, .4)
        samples += .6 * self.signal(frequency=3020, noise=0)
        samples += .6 * self.signal(frequency=4530, noise=0)
        onset, frequency = detect_beep_auto(samples, self.rate)
        self.assertAlmostEqual(onset, 1.237, delta=.02)
        self.assertAlmostEqual(frequency, 1510, delta=15)

    def test_auto_requires_matching_simultaneous_harmonics(self):
        cases = [self.signal(frequency=3020),
                 self.signal(frequency=3020) + self.signal(frequency=4400),
                 self.signal(frequency=3020) + self.signal(frequency=4530, onset=2)]
        for samples in cases:
            with self.subTest():
                with self.assertRaises(ValueError):
                    detect_beep_auto(samples, self.rate)

    def test_auto_rejects_clipped_impacts_without_a_beep(self):
        rng = np.random.default_rng(182)
        samples = np.zeros(self.rate * 4)
        for onset in [.1, .7, 1.3, 2.0, 2.4, 3.1]:
            start = round(onset * self.rate)
            decay = np.exp(-np.arange(6000) / 1200)
            samples[start:start + 6000] += np.clip(5 * rng.normal(size=6000) * decay, -.8, .8)
        with self.assertRaises(ValueError):
            detect_beep_auto(samples, self.rate)

    def test_harmonic_beep_between_candidates_with_narrow_tolerance(self):
        samples = self.signal(onset=.2, frequency=3050, noise=0)
        samples += self.signal(onset=.2, frequency=4575, noise=0)
        samples += self.signal(onset=.7, frequency=2700, noise=0)
        onset, frequency = detect_beep_auto(samples, self.rate, tolerance=50)
        self.assertAlmostEqual(onset, .2, delta=.02)
        self.assertAlmostEqual(frequency, 1525, delta=15)


if __name__ == '__main__':
    unittest.main()
