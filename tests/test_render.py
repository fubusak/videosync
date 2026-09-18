"""Small real FFmpeg renders, exercising synchronization end to end."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from videosync import decode_audio, detect_beep, find_ffmpeg, video_endpoint


class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ffmpeg = find_ffmpeg()
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.inputs = []
        for i, (beep, duration, color) in enumerate([
                (.4, 3, 'red'), (1.4, 4, 'green'), (.4, 3, 'blue'), (.4, 2.5, 'yellow')]):
            path = cls.root / f'input {i}.mp4'
            command = [cls.ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                       f'color={color}:size=160x90:rate=30:duration={duration}',
                       '-f', 'lavfi', '-i', 'sine=frequency=2700:sample_rate=48000:duration=0.2',
                       '-filter_complex',
                       f'[0:v]drawbox=c=white:t=fill:enable=\'between(t,{beep},{beep + .17})\'[v];'
                       f'[1:a]adelay={round(beep * 1000)}:all=1,apad[a]',
                       '-map', '[v]', '-map', '[a]', '-t', str(duration),
                       '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(path)]
            subprocess.run(command, check=True, capture_output=True)
            cls.inputs.append(path)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def cli(self, inputs, *extra):
        return subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'videosync.py'),
                               *map(str, inputs), '--height', '90', *map(str, extra)],
                              capture_output=True, text=True, timeout=45)

    def frame(self, path, time, count):
        result = subprocess.run([self.ffmpeg, '-v', 'error', '-ss', str(time), '-i', str(path),
                                 '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'],
                                check=True, capture_output=True)
        return np.frombuffer(result.stdout, np.uint8).reshape(90, count * 160, 3)

    def test_two_to_four_videos_align_and_stop_at_longest(self):
        for count, audio, expected_duration in [(2, 'first', 3.6), (3, 'mix', 3.6), (4, 'none', 3.6)]:
            with self.subTest(count=count, audio=audio):
                output = self.root / f'output{count}.mp4'
                result = self.cli(self.inputs[:count], '-o', output, '--audio', audio)
                self.assertEqual(result.returncode, 0, result.stderr)
                # All panels turn white together at the aligned beep.
                frame = self.frame(output, 1.08, count)
                for i in range(count):
                    self.assertTrue(np.all(frame[45, i * 160 + 80] > 225))
                before = self.frame(output, .8, count)
                self.assertTrue(np.any(before[45, 80] < 150))
                if audio != 'none':
                    samples = decode_audio(self.ffmpeg, output, 5, 16000)
                    self.assertAlmostEqual(detect_beep(samples, 16000), 1, delta=.025)
                else:
                    with self.assertRaises(ValueError):
                        decode_audio(self.ffmpeg, output, 5, 16000)
                import imageio_ffmpeg
                frames = imageio_ffmpeg.read_frames(str(output))
                metadata = next(frames)
                frames.close()
                self.assertAlmostEqual(metadata['duration'], expected_duration, delta=.1)

    def test_finished_panel_turns_black_until_longer_video_ends(self):
        for short_first in (True, False):
            for audio in ('first', 'mix', 'none'):
                with self.subTest(short_first=short_first, audio=audio):
                    inputs = [self.inputs[3], self.inputs[1]]
                    if not short_first:
                        inputs.reverse()
                    output = self.root / f'black-{short_first}-{audio}.mp4'
                    result = self.cli(inputs, '-o', output, '--audio', audio)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertAlmostEqual(video_endpoint(self.ffmpeg, output), 3.6, delta=.05)
                    short_x, long_x = (80, 240) if short_first else (240, 80)
                    before = self.frame(output, 3.0, 2)
                    self.assertTrue(np.any(before[45, short_x] > 100))
                    after = self.frame(output, 3.4, 2)
                    self.assertTrue(np.all(after[45, short_x] < 10))
                    self.assertGreater(after[45, long_x, 1], 100)

    def test_duration_limit_still_caps_longest_video(self):
        for limit in (2, 3.3, 5):
            with self.subTest(limit=limit):
                output = self.root / f'limited-{limit}.mp4'
                result = self.cli([self.inputs[3], self.inputs[1]], '-o', output,
                                  '--duration', limit)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertAlmostEqual(video_endpoint(self.ffmpeg, output), min(limit, 3.6), delta=.05)

    def test_cli_rejects_bad_input_count_and_invalid_numbers(self):
        for inputs, flags in [(self.inputs[:1], []), (self.inputs * 2, []),
                              (self.inputs[:2], ['--frequency', 'nan']),
                              (self.inputs[:2], ['--height', '91'])]:
            with self.subTest(flags=flags, count=len(inputs)):
                self.assertNotEqual(self.cli(inputs, *flags).returncode, 0)

    def test_never_overwrites_input_even_when_requested(self):
        before = self.inputs[0].read_bytes()
        result = self.cli(self.inputs[:2], '-o', self.inputs[0], '--overwrite')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.inputs[0].read_bytes(), before)

    def test_detect_only_does_not_create_output(self):
        output = self.root / 'detect.mp4'
        result = self.cli(self.inputs[:2], '--detect-only', '-o', output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(output.exists())

    def test_cli_auto_reports_frequency_and_renders_mixed_audio(self):
        output = self.root / 'automatic.mp4'
        result = self.cli(self.inputs[:2], '--frequency', 'auto', '--audio', 'mix', '-o', output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('frequency=2700', result.stdout)
        samples = decode_audio(self.ffmpeg, output, 3, 16000)
        self.assertAlmostEqual(detect_beep(samples, 16000), 1, delta=.025)
        self.assertTrue(np.all(self.frame(output, 1.08, 2)[45, 80] > 225))

    def test_rejects_beep_after_video_ends(self):
        source = self.root / 'audio outlasts video.mp4'
        subprocess.run([self.ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'color=red:size=160x90:rate=30:duration=2', '-f', 'lavfi', '-i',
                        'sine=frequency=2700:sample_rate=48000:duration=0.2',
                        '-af', 'adelay=3500:all=1,apad=whole_dur=6',
                        '-c:v', 'libx264', '-c:a', 'aac', str(source)],
                       check=True, capture_output=True)
        result = self.cli([source, self.inputs[1]], '-o', self.root / 'empty.mp4')
        self.assertNotEqual(result.returncode, 0, 'Must reject a beep beyond the video endpoint')


if __name__ == '__main__':
    unittest.main()
