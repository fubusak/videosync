# VideoSync private web MVP

Status: proposed implementation scope; web delivery selected by the user.

## Outcome

Three to five invited friends can open an HTTPS link, upload 2–4 recordings,
synchronize them by their starting beep, and download a side-by-side MP4 without
installing software or receiving technical help.

## User flow

1. Enter a shared password before accessing uploads or results.
2. Select 2–4 recordings. Display filenames and explicit left-to-right ordering
   controls. Explain that every recording needs the same kind of starting beep.
3. Press Sync videos. Show analyzing, rendering, complete, or failed status.
4. Preview the result and download it. Explain that this first release requires
   keeping the page open during processing and downloading promptly afterward.

Defaults: automatic beep detection, one-second pre-roll, 720-pixel panel height,
30 fps, and first-video audio. Offer first/mixed/muted audio and an optional known
beep frequency. Search the first 30 seconds, with a clear message on failure.
Preserve existing engine behavior for unequal clip lengths and aspect ratios.

## Implementation

Use Streamlit for the interface and the existing Python CLI as a subprocess.
Invoke it with an argument list, never shell interpolation. Keep detection and
rendering behavior in the existing engine. Each job gets a random private
directory and generated input filenames; uploaded filenames are display only.

Run a single application process in one Docker container, with a global job
lock allowing one processing job at a time. When occupied, reject another start
with an explicit busy message and allow retry; do not build a queue for v1.
Repeated clicks and Streamlit reruns must not launch duplicate subprocesses.

Bind result ownership to the authenticated browser session. Do not expose job
directories through static hosting or put uploaded media into a shared cache.
Read the password from deployment secrets, never repository source. Hosting
must provide HTTPS; the choice of provider does not change this application.

Initial limits: 100 MB per file, 300 MB total per job, at most four files, and
two minutes duration per input. Probe actual streams and duration rather than
trusting filename extensions. Accept MP4/MOV containers when the installed
FFmpeg can decode their video and audio streams. Reject missing audio, invalid
media, and oversized decoded video dimensions above 3840 pixels on either axis.
Apply a ten-minute processing deadline and terminate the entire job process tree
on timeout. Validate these provisional limits against real phone recordings.

Delete job files after failure and expire successful results after one hour.
Run periodic cleanup and startup cleanup for abandoned jobs. Tell users the
retention policy before upload. Release uploaded buffers and result references
when clearing a session; avoid retaining video bytes in application-wide caches.

## Deployment

Deliver a reproducible Docker image, pinned application dependencies, a health
endpoint, environment configuration instructions, and concise deployment steps.
Use one CPU server/container with sufficient temporary disk and memory, then
measure actual peak memory and rendering duration before choosing its final
size. No GPU, database, persistent media library, or object storage in v1.

The hosting account and spending limit are deployment inputs to resolve with
the user. Implementation can proceed before those are supplied. Publishing
depends on configured access and an agreed hosting target.

## Verification and release

Run the existing engine suite after integrating the wrapper, preserving any
pre-existing local edits. Exercise successful 2- and 4-video jobs, ordering,
audio selection, missing/mismatched beeps, corrupt media, excessive uploads,
timeouts, repeated clicks, and cleanup.

Use two independent browser sessions to verify one-job admission and that
results cannot cross sessions. Verify upload, playback, and MP4 download on
an actual iPhone/Safari and Android/Chrome before claiming those devices work.
Measure a representative full-size job in the deployment environment.

Invite three friends and consider the MVP validated when each completes a
useful comparison without assistance. Record failed job reasons and processing
duration without logging video content, passwords, or uploaded filenames.

## Deferred

Individual accounts, payments, saved projects, shareable result links, background
job recovery, a durable queue, manual timeline editing, and native mobile apps.
