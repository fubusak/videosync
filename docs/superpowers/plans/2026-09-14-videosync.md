# VideoSync Implementation Plan

> Execute inline in the user-authorized workspace; the repository has no commits or existing implementation.

**Goal:** Align 2–4 recordings by their beep and render a horizontal MP4.

**Architecture:** One importable Python CLI module with separate detection,
audio decoding, rendering, and argument validation functions.

**Tech Stack:** Python 3.10+, NumPy, FFmpeg via imageio-ffmpeg or PATH.

**Spec:** ../specs/2026-09-14-videosync-design.md

## Tasks

- [x] Add `tests/test_videosync.py`: generated 2700 Hz beeps must produce onset
  within 15 ms; reject silence, broadband noise, wrong tones, and 10 ms clicks;
  detect a tone in opposing-phase stereo. Run unittest before implementation.
- [x] Implement `detect_beep(samples, sample_rate, frequency, tolerance,
  min_beep_duration)` in `videosync.py` using 20 ms Hann windows and 5 ms hops,
  frequency-band concentration, absolute silence floor and sustained runs.
- [x] Implement CLI decoding and rendering. Test subprocess CLI errors and
  synthetic MP4s with known offsets, unequal durations, and early beeps.
  Use FFmpeg horizontal stacking and independent trim/padding filters.
- [x] Write README installation, usage and limitations. Run unittest and
  real-input render; inspect output audio onset and a frame. Review code for
  overwritten inputs, missing streams, timestamp offsets and resource usage.

## Review and verification

14 tests pass, including real renders for two to four videos and all audio
modes. Review regressions cover a later loud beep masking an earlier clear
one and audio outlasting video. The renderer scans copied video packet
timestamps to determine the usable endpoint and verifies nonempty output.
The supplied recordings require 1500 Hz; the requested default remains 2700 Hz.
