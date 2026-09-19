from __future__ import annotations

from dataclasses import dataclass
import json
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
MAX_FILE_BYTES = 500 * 1024 * 1024
MAX_TOTAL_BYTES = MAX_FILES * MAX_FILE_BYTES
MAX_DURATION_SECONDS = 120.0
MAX_DIMENSION_PIXELS = 3840
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
    layout: str = "horizontal"


@dataclass(frozen=True)
class JobResult:
    job_dir: Path
    output_path: Path
    stdout: str
    stderr: str
    command: list[str]


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    width: int
    height: int
    has_video: bool
    has_audio: bool


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
            raise ValueError("Each video must be 500 MB or smaller.")
        total += size

    if total > MAX_TOTAL_BYTES:
        raise ValueError("The combined upload must be 2000 MB or smaller.")


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
        "--layout",
        options.layout,
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


def probe_media(path: Path, *, runner=subprocess.run) -> MediaInfo:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]
    completed = runner(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise ValueError("Could not read the uploaded video.")
    try:
        metadata = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("Could not read the uploaded video metadata.") from exc
    return media_info_from_probe(metadata)


def media_info_from_probe(metadata) -> MediaInfo:
    streams = metadata.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
    duration = _duration_from_metadata(metadata, video)
    return MediaInfo(
        duration=duration,
        width=int(video.get("width", 0)) if video else 0,
        height=int(video.get("height", 0)) if video else 0,
        has_video=video is not None,
        has_audio=has_audio,
    )


def _duration_from_metadata(metadata, video) -> float:
    for value in [
        metadata.get("format", {}).get("duration"),
        video.get("duration") if video else None,
    ]:
        if value not in (None, "N/A"):
            try:
                return float(value)
            except ValueError:
                pass
    return 0.0


def validate_media_constraints(media: MediaInfo, path: Path) -> None:
    if not media.has_video:
        raise ValueError(f"{path.name}: video stream is missing.")
    if not media.has_audio:
        raise ValueError(f"{path.name}: audio stream is missing.")
    if media.duration > MAX_DURATION_SECONDS:
        raise ValueError(f"{path.name}: video is longer than 2 minutes.")
    if media.width > MAX_DIMENSION_PIXELS or media.height > MAX_DIMENSION_PIXELS:
        raise ValueError(f"{path.name}: video dimensions exceed 3840 pixels.")


def run_sync_job(
    uploads,
    options: SyncOptions,
    *,
    job_root: Path | None = None,
    runner=subprocess.run,
    prober=probe_media,
    script_path: Path | None = None,
) -> JobResult:
    validate_uploads(uploads)
    if not _job_lock.acquire(blocking=False):
        raise RuntimeError("Another sync job is already running. Please try again in a moment.")

    job_dir = _job_root(job_root) / f"{DEFAULT_JOB_PREFIX}{uuid.uuid4().hex}"
    try:
        job_dir.mkdir(parents=True)
        inputs = _write_uploads(job_dir, uploads)
        for path in inputs:
            validate_media_constraints(prober(path), path)
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
