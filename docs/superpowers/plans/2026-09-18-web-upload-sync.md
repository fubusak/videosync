# VideoSync Web Upload Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Docker placeholder page with a private upload -> sync -> preview/download flow backed by the existing VideoSync CLI.

**Architecture:** Add a focused `web_jobs.py` module for upload validation, generated job filenames, CLI command construction, one-job admission, subprocess execution, and cleanup. Keep `web_app.py` as a Streamlit UI that authenticates the browser session, captures options, calls `web_jobs.run_sync_job()`, and exposes the result only from session state. The existing `videosync.py` engine remains the renderer.

**Tech Stack:** Python 3.12, Streamlit 1.63.0, FFmpeg, existing VideoSync CLI.

**Spec:** `docs/superpowers/specs/2026-09-16-web-mvp-design.md`

## Global Constraints

- Use Streamlit for the interface and the existing Python CLI as a subprocess.
- Invoke the CLI with an argument list, never shell interpolation.
- Each job gets a random private directory and generated input filenames; uploaded filenames are display only.
- Run a single application process/container with a global job lock allowing one processing job at a time.
- Initial limits: 100 MB per file, 300 MB total per job, at most four files, two minutes duration per input.
- Read the password from deployment secrets, never repository source.
- Delete failed job files and expire successful results after one hour.
- Preserve existing engine behavior and existing local edits.

---

### Task 1: Testable Job Runner

**Files:**
- Create: `web_jobs.py`
- Create: `tests/test_web_jobs.py`
- Modify: `Dockerfile`
- Modify: `tests/test_docker_assets.py`

**Interfaces:**
- Produces: `UploadedVideo(name: str, data: bytes)`.
- Produces: `SyncOptions(audio: str = "first", frequency: str = "auto", pre_roll: float = 1.0, height: int = 720, fps: float = 30.0, search_seconds: float = 30.0, timeout_seconds: float = 600.0)`.
- Produces: `JobResult(job_dir: Path, output_path: Path, stdout: str, stderr: str, command: list[str])`.
- Produces: `validate_uploads(uploads: Sequence[UploadedVideo]) -> None`.
- Produces: `build_command(script_path: Path, inputs: Sequence[Path], output: Path, options: SyncOptions) -> list[str]`.
- Produces: `run_sync_job(uploads: Sequence[UploadedVideo], options: SyncOptions, *, job_root: Path | None = None, runner=subprocess.run, script_path: Path | None = None) -> JobResult`.
- Produces: `cleanup_expired_jobs(job_root: Path | None = None, *, max_age_seconds: float = 3600.0) -> int`.
- Produces: `clear_job(result: JobResult | None) -> None`.

- [ ] **Step 1: Write failing job-runner tests**

```python
import subprocess
import tempfile
import unittest
from pathlib import Path

from web_jobs import UploadedVideo, SyncOptions, build_command, cleanup_expired_jobs, run_sync_job, validate_uploads


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
            validate_uploads([self.upload("a.mp4", b"x" * (100 * 1024 * 1024 + 1)), self.upload("b.mp4")])

    def test_build_command_uses_argument_list_with_expected_defaults(self):
        command = build_command(Path("videosync.py"), [Path("input-1.mp4"), Path("input-2.mov")], Path("out.mp4"), SyncOptions())
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
            result = run_sync_job([self.upload("friendly name.mp4"), self.upload("other.mov")], SyncOptions(), job_root=Path(temp), runner=runner)
            self.assertTrue(result.output_path.exists())
            self.assertEqual(result.output_path.read_bytes(), b"rendered")
            self.assertEqual([path.name for path in result.job_dir.glob("input-*")], ["input-1.mp4", "input-2.mov"])
            self.assertNotIn("friendly name", " ".join(map(str, calls[0][0])))

    def test_run_sync_job_cleans_failed_job(self):
        def runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 2, "", "bad beep")

        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(RuntimeError):
                run_sync_job([self.upload("a.mp4"), self.upload("b.mp4")], SyncOptions(), job_root=Path(temp), runner=runner)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_cleanup_expired_jobs_removes_old_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            old = Path(temp) / "videosync-old"
            old.mkdir()
            import os, time
            stale = time.time() - 7200
            os.utime(old, (stale, stale))
            self.assertEqual(cleanup_expired_jobs(Path(temp), max_age_seconds=3600), 1)
            self.assertFalse(old.exists())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m unittest tests.test_web_jobs -v`

Expected: FAIL because `web_jobs.py` does not exist.

- [ ] **Step 3: Implement `web_jobs.py` minimally**

Implement the public interfaces above with:
- MP4/MOV extension validation.
- 2-4 uploads, 100 MB per file, 300 MB total.
- Generated `input-1.ext` filenames.
- `sys.executable` command invocation with `--frequency`, `--audio`, `--pre-roll`, `--search-seconds`, `--height`, `--fps`, `--overwrite`, and `-o`.
- Nonblocking global lock; raise `RuntimeError("Another sync job is already running. Please try again in a moment.")` if busy.
- Cleanup on validation/runtime/timeout failures.
- Successful jobs retained for download until cleanup.

- [ ] **Step 4: Include `web_jobs.py` in Docker image**

Update `Dockerfile` to copy `web_jobs.py`, and update `tests/test_docker_assets.py` to assert it is included.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m unittest tests.test_web_jobs tests.test_docker_assets -v`

Expected: PASS.

### Task 2: Streamlit Upload UI

**Files:**
- Modify: `web_app.py`
- Modify: `tests/test_docker_assets.py`

**Interfaces:**
- Consumes: `web_jobs.UploadedVideo`, `web_jobs.SyncOptions`, `web_jobs.run_sync_job`, `web_jobs.clear_job`.
- Produces: authenticated Streamlit UI with file uploader, audio choice, optional known frequency, sync button, status/error messages, video preview, download button, and clear button.

- [ ] **Step 1: Write failing source checks for upload UI**

Extend `tests/test_docker_assets.py` with a source-level check that `web_app.py` imports `web_jobs`, calls `st.file_uploader`, builds `SyncOptions`, calls `run_sync_job`, calls `st.video`, and calls `st.download_button`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m unittest tests.test_docker_assets.DockerAssetTests.test_web_app_exposes_upload_sync_preview_and_download -v`

Expected: FAIL until the UI is wired.

- [ ] **Step 3: Implement Streamlit flow**

Replace the placeholder shell with:
- A retention note and beep guidance.
- `st.file_uploader(..., accept_multiple_files=True, type=["mp4", "mov"])`.
- Audio choice: first, mix, muted.
- Frequency choice: auto or known Hz.
- Sync button that converts uploads to `UploadedVideo`, calls `run_sync_job()`, stores `JobResult` in session state, and displays errors without exposing job paths.
- Preview/download using the output bytes from the session-owned `JobResult`.
- Clear button calling `clear_job()` and removing session result.

- [ ] **Step 4: Run focused tests**

Run: `.venv\Scripts\python.exe -m unittest tests.test_docker_assets tests.test_web_jobs -v`

Expected: PASS.

### Task 3: Container Rebuild and Smoke Test

**Files:**
- No source files unless verification finds a defect.

**Interfaces:**
- Consumes: Docker image `videosync-web:dev`.
- Produces: running container `videosync-web-dev` on port 8501.

- [ ] **Step 1: Run full tests**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -v`

Expected: PASS.

- [ ] **Step 2: Rebuild Docker image**

Run: `docker build -t videosync-web:dev .`

Expected: image builds successfully and includes `web_jobs.py`.

- [ ] **Step 3: Restart local container**

Run:

```powershell
docker rm -f videosync-web-dev
docker run -d --name videosync-web-dev -p 8501:8501 -e VIDEOSYNC_PASSWORD=videosync-beta videosync-web:dev
```

Expected: container starts and maps port 8501.

- [ ] **Step 4: Verify health endpoint**

Run: `Invoke-WebRequest -UseBasicParsing -Uri http://localhost:8501/_stcore/health`

Expected: HTTP 200 with body `ok`.

### Self-Review

- Spec coverage: This plan covers upload selection, explicit ordering by displayed list order, CLI subprocess execution without shell interpolation, generated private job dirs, one-job admission, basic cleanup, preview/download, Docker inclusion, and local container smoke test. Duration probing and decoded video dimension validation remain for the next hardening slice.
- Placeholder scan: No placeholder wording is left in executable steps.
- Type consistency: The dataclass and function names are consistent across job tests, Streamlit UI, Docker assets, and verification steps.
