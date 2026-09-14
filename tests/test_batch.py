import unittest

import numpy as np

from beep_batch import BeepCandidate, merge_candidates, select_batch


def beep(onset, frequency=1500, duration=.3):
    return BeepCandidate(onset, frequency, duration, .9)


class BatchTests(unittest.TestCase):
    def test_common_frequency_beats_unrelated_early_tones(self):
        selected = select_batch([[beep(.2, 2200), beep(1.2, 1505)],
                                 [beep(.1, 1800), beep(3.7, 1508)]])
        self.assertEqual([x.onset for x in selected], [1.2, 3.7])

    def test_common_duration_disambiguates_same_frequency(self):
        selected = select_batch([[beep(.2, duration=.8), beep(1.2)],
                                 [beep(3.7, duration=.32)]])
        self.assertEqual([x.onset for x in selected], [1.2, 3.7])

    def test_match_required_in_every_video(self):
        selected = select_batch([[beep(i, 1500 + i, .3 + i * .005)] for i in range(4)])
        self.assertEqual(len(selected), 4)
        with self.assertRaises(ValueError):
            select_batch([[beep(1)], [beep(2)], [beep(3, 2200)]])

    def test_rejects_duration_disagreement_and_missing_candidates(self):
        for candidates in [[[beep(1)], [beep(2, duration=1)]], [[beep(1)], []]]:
            with self.subTest():
                with self.assertRaises(ValueError):
                    select_batch(candidates)

    def test_all_frequencies_must_agree_not_just_neighbors(self):
        with self.assertRaises(ValueError):
            select_batch([[beep(1, 1470)], [beep(2, 1500)], [beep(3, 1530)]])

    def test_earliest_consistent_group_is_selected(self):
        selected = select_batch([[beep(1), beep(5)], [beep(2), beep(6)]])
        self.assertEqual([x.onset for x in selected], [1, 2])

    def test_clear_beep_guides_grouping_of_masked_fragments(self):
        selected = select_batch([[BeepCandidate(1.265, 1506, .48, .98)],
                                 [BeepCandidate(.35, 1502, .05, .78),
                                  BeepCandidate(.67, 1506, .07, .82), beep(8, 2200)]])
        self.assertEqual([x.onset for x in selected], [1.265, .35])
        self.assertAlmostEqual(selected[1].duration, .39)

    def test_noisy_duration_can_be_partially_hidden(self):
        selected = select_batch([[BeepCandidate(1.19, 1507, .405, .99)],
                                 [BeepCandidate(3.7, 1506, .255, .76)]])
        self.assertEqual([x.onset for x in selected], [1.19, 3.7])
        with self.assertRaises(ValueError):
            select_batch([[BeepCandidate(1.19, 1507, .405, .99)],
                          [BeepCandidate(3.7, 1506, .1, .76)]])

    def test_signal_candidates_keep_later_matching_beeps(self):
        from videosync import find_beep_candidates
        rate = 24000

        def recording(events):
            samples = np.zeros(rate * 4)
            for onset, frequency, duration in events:
                count = round(duration * rate)
                start = round(onset * rate)
                samples[start:start + count] += .5 * np.sin(2 * np.pi * frequency * np.arange(count) / rate)
            return samples

        cases = [([( .2, 2200, .2), (1.2, 1510, .3)],
                  [( .3, 1800, .2), (2.0, 1508, .3)], [1.2, 2.0]),
                 ([( .2, 1510, .8), (2.0, 1510, .3)],
                  [( .5, 1508, .3)], [2.0, .5])]
        for first, second, expected in cases:
            matched = select_batch([find_beep_candidates(recording(events), rate) for events in [first, second]])
            for item, wanted in zip(matched, expected):
                self.assertAlmostEqual(item.onset, wanted, delta=.02)

    def test_separate_clear_short_beeps_are_not_one_long_beep(self):
        candidates = merge_candidates([beep(.2, duration=.1), beep(.4, duration=.1)])
        self.assertEqual(len(candidates), 2)
        with self.assertRaises(ValueError):
            select_batch([candidates, [beep(1, duration=.3)]])

    def test_intervening_distractor_does_not_block_fragments(self):
        selected = select_batch([[BeepCandidate(1.265, 1500, .48, .98)],
                                 [BeepCandidate(.35, 1470, .05, .78),
                                  BeepCandidate(.50, 1530, .06, .80),
                                  BeepCandidate(.67, 1470, .07, .82)]])
        self.assertEqual([item.onset for item in selected], [1.265, .35])


if __name__ == '__main__':
    unittest.main()
