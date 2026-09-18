from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid


MAX_FILES = 4
MIN_FILES = 2
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 300 * 1024 * 1024
ALLOWED_SUFFIXES = {".mp4", ".mov"}
DEFAULT_JOB_PREFIX = "videosync-"


_job_lock = threading.Lock()


@dataclass(frozen=True)
class UploadedVideo:
    name: str
    data: bytes


@dataclass(frozen=True)
class SyncOptions:
    audio: str = "first"
    frequency: str = "auto"
    pre_roll: float = 1.0
    height: int = 720
    fps: float = 30.0
    search_seconds: float = 30.0
    timeout_seconds: float = 600.0


@dataclass(frozen=True)
class JobResult:
    job_dir: Path
    output_path: Path
    stdout: str
    stderr: str
    command: list[str]


def _job_root(job_root: Path | None = None) -> Path:
    root = job_root or Path(tempfile.gettempdir()) / "videosync-web"
    root.mkdir(parents=True, exist_ok=True)
    return root


def validate_uploads(uploads) -> None:
    if len(uploads) < MIN_FILES:
        raise ValueError("Upload at least two videos.")
    if len(uploads) > MAX_FILES:
        raise ValueError("Upload no more than four videos.")

    total = 0
    for upload in uploads:
        suffix = Path(upload.name).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise ValueError("Use MP4 or MOV files.")
        size = len(upload.data)
        if size > MAX_FILE_BYTES:
            raise ValueError("Each video must be 100 MB or smaller.")
        total += size

    if total > MAX_TOTAL_BYTES:
        raise ValueError("The combined upload must be 300 MB or smaller.")


def build_command(script_path: Path, inputs, output: Path, options: SyncOptions) -> list[str]:
    return [
        sys.executable,
        str(script_path),
        *[str(path) for path in inputs],
        "-o",
        str(output),
        "--frequency",
        str(options.frequency),
        "--audio",
        options.audio,
        "--pre-roll",
        str(options.pre_roll),
        "--search-seconds",
        str(options.search_seconds),
        "--height",
        str(options.height),
        "--fps",
        str(options.fps),
        "--overwrite",
    ]


def _write_uploads(job_dir: Path, uploads) -> list[Path]:
    paths = []
    for index, upload in enumerate(uploads, start=1):
        suffix = Path(upload.name).suffix.lower()
        path = job_dir / f"input-{index}{suffix}"
        path.write_bytes(upload.data)
        paths.append(path)
    return paths


def run_sync_job(
    uploads,
    options: SyncOptions,
    *,
    job_root: Path | None = None,
    runner=subprocess.run,
    script_path: Path | None = None,
) -> JobResult:
    validate_uploads(uploads)
    if not _job_lock.acquire(blocking=False):
        raise RuntimeError("Another sync job is already running. Please try again in a moment.")

    job_dir = _job_root(job_root) / f"{DEFAULT_JOB_PREFIX}{uuid.uuid4().hex}"
    try:
        job_dir.mkdir(parents=True)
        inputs = _write_uploads(job_dir, uploads)
        output = job_dir / "synced.mp4"
        command = build_command(script_path or Path(__file__).with_name("videosync.py"), inputs, output, options)
        completed = runner(command, capture_output=True, text=True, timeout=options.timeout_seconds)
        if completed.returncode != 0:
            raise RuntimeError(_failure_message(completed))
        if not output.exists():
            raise RuntimeError("Rendering finished without producing an output file.")
        return JobResult(job_dir, output, completed.stdout, completed.stderr, command)
    except subprocess.TimeoutExpired as exc:
        clear_path(job_dir)
        raise TimeoutError("Rendering timed out. Try shorter clips or smaller files.") from exc
    except Exception:
        clear_path(job_dir)
        raise
    finally:
        _job_lock.release()


def _failure_message(completed) -> str:
    text = (completed.stderr or completed.stdout or "Video synchronization failed.").strip()
    return text.splitlines()[-1] if text else "Video synchronization failed."


def cleanup_expired_jobs(job_root: Path | None = None, *, max_age_seconds: float = 3600.0) -> int:
    root = _job_root(job_root)
    now = time.time()
    removed = 0
    for path in root.iterdir():
        if not path.is_dir() or not path.name.startswith(DEFAULT_JOB_PREFIX):
            continue
        age = now - path.stat().st_mtime
        if age <= max_age_seconds:
            continue
        clear_path(path)
        removed += 1
    return removed


def clear_job(result: JobResult | None) -> None:
    if result is not None:
        clear_path(result.job_dir)


def clear_path(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
