import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from web_jobs import (
    MediaInfo,
    SyncOptions,
    UploadedVideo,
    build_command,
    cleanup_expired_jobs,
    run_sync_job,
    validate_media_constraints,
    validate_uploads,
)


class WebJobTests(unittest.TestCase):
    def upload(self, name="clip.mp4", data=b"video"):
        return UploadedVideo(name, data)

    def test_validate_upload_count_types_and_size_limits(self):
        with self.assertRaises(ValueError):
            validate_uploads([self.upload()])
        with self.assertRaises(ValueError):
            validate_uploads([self.upload(f"{i}.mp4") for i in range(5)])
        with self.assertRaises(ValueError):
            validate_uploads([self.upload("clip.txt"), self.upload("clip.mp4")])
        with self.assertRaises(ValueError):
            validate_uploads([
                self.upload("a.mp4", b"x" * (100 * 1024 * 1024 + 1)),
                self.upload("b.mp4"),
            ])

    def test_build_command_uses_argument_list_with_expected_defaults(self):
        command = build_command(
            Path("videosync.py"),
            [Path("input-1.mp4"), Path("input-2.mov")],
            Path("out.mp4"),
            SyncOptions(),
        )
        self.assertEqual(command[1], "videosync.py")
        self.assertIn("--frequency", command)
        self.assertIn("auto", command)
        self.assertIn("--audio", command)
        self.assertIn("first", command)
        self.assertIn("--overwrite", command)

    def test_run_sync_job_writes_generated_names_and_keeps_success(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            Path(command[command.index("-o") + 1]).write_bytes(b"rendered")
            return subprocess.CompletedProcess(command, 0, "ok", "")

        with tempfile.TemporaryDirectory() as temp:
            result = run_sync_job(
                [self.upload("friendly name.mp4"), self.upload("other.mov")],
                SyncOptions(),
                job_root=Path(temp),
                runner=runner,
                prober=lambda path: MediaInfo(60, 1920, 1080, True, True),
            )
            self.assertTrue(result.output_path.exists())
            self.assertEqual(result.output_path.read_bytes(), b"rendered")
            self.assertEqual(
                [path.name for path in sorted(result.job_dir.glob("input-*"))],
                ["input-1.mp4", "input-2.mov"],
            )
            self.assertNotIn("friendly name", " ".join(map(str, calls[0][0])))

    def test_validate_media_constraints_rejects_bad_streams(self):
        cases = [
            MediaInfo(duration=121, width=1920, height=1080, has_video=True, has_audio=True),
            MediaInfo(duration=60, width=3841, height=1080, has_video=True, has_audio=True),
            MediaInfo(duration=60, width=1920, height=3841, has_video=True, has_audio=True),
            MediaInfo(duration=60, width=1920, height=1080, has_video=False, has_audio=True),
            MediaInfo(duration=60, width=1920, height=1080, has_video=True, has_audio=False),
        ]
        for media in cases:
            with self.subTest(media=media):
                with self.assertRaises(ValueError):
                    validate_media_constraints(media, Path("clip.mp4"))

    def test_run_sync_job_probes_inputs_before_rendering_and_cleans_rejections(self):
        render_calls = []

        def runner(command, **kwargs):
            render_calls.append(command)
            Path(command[command.index("-o") + 1]).write_bytes(b"rendered")
            return subprocess.CompletedProcess(command, 0, "ok", "")

        with tempfile.TemporaryDirectory() as temp:
            result = run_sync_job(
                [self.upload("a.mp4"), self.upload("b.mp4")],
                SyncOptions(),
                job_root=Path(temp),
                runner=runner,
                prober=lambda path: MediaInfo(60, 1920, 1080, True, True),
            )
            self.assertTrue(result.output_path.exists())
            self.assertEqual(len(render_calls), 1)

        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                run_sync_job(
                    [self.upload("a.mp4"), self.upload("b.mp4")],
                    SyncOptions(),
                    job_root=Path(temp),
                    runner=runner,
                    prober=lambda path: MediaInfo(121, 1920, 1080, True, True),
                )
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_run_sync_job_cleans_failed_job(self):
        def runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 2, "", "bad beep")

        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(RuntimeError):
                run_sync_job(
                    [self.upload("a.mp4"), self.upload("b.mp4")],
                    SyncOptions(),
                    job_root=Path(temp),
                    runner=runner,
                    prober=lambda path: MediaInfo(60, 1920, 1080, True, True),
                )
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_cleanup_expired_jobs_removes_old_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            old = Path(temp) / "videosync-old"
            old.mkdir()
            stale = time.time() - 7200
            os.utime(old, (stale, stale))
            self.assertEqual(cleanup_expired_jobs(Path(temp), max_age_seconds=3600), 1)
            self.assertFalse(old.exists())


if __name__ == "__main__":
    unittest.main()
