#!/usr/bin/env python3
"""Synchronize 2–4 videos by a tone and render them in a horizontal row."""

import argparse
import math
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np

from beep_batch import BeepCandidate, merge_candidates, select_batch


def detect_beep(samples, sample_rate, frequency=2700, tolerance=100,
                min_beep_duration=0.05):
    """Return first sustained beep onset in seconds, or raise ValueError.

    Samples are floats with shape (time,) or (time, channels). Channels are
    analyzed separately so opposing stereo phase cannot cancel the beep.
    """
    if not (0 < frequency - tolerance < frequency + tolerance < sample_rate / 2):
        raise ValueError('Frequency band must be above zero and below the Nyquist frequency.')
    result = scan_tones(samples, sample_rate, [frequency], tolerance, min_beep_duration)
    if result is None:
        raise ValueError('No clear sustained beep found; check --frequency, --tolerance or --search-seconds.')
    return result[0]


def detect_beep_auto(samples, sample_rate, tolerance=100, min_beep_duration=0.05):
    """Return (onset seconds, estimated Hz) for the first tone in 1200–3000 Hz.

    Compute one spectrum, then test narrow candidate bands independently. A
    wide band alone would also accept speech and broadband impacts.
    """
    if not math.isfinite(tolerance) or not 0 < tolerance < 1200:
        raise ValueError('Automatic detection requires 0 < --tolerance < 1200 Hz.')
    if 3000 + max(600, tolerance * 3) >= sample_rate / 2:
        raise ValueError('Sample rate is too low for automatic detection.')
    result = scan_tones(samples, sample_rate, None, tolerance, min_beep_duration,
                        frequency_range=(1200, 3000))
    if result is None:
        raise ValueError('No clear sustained beep found in 1200–3000 Hz; check --search-seconds or use --frequency HZ.')
    return result


def scan_tones(samples, sample_rate, frequencies, tolerance, min_beep_duration, frequency_range=None):
    for power, bins, window_size, hop, base in audio_spectrum(samples, sample_rate, min_beep_duration):
        if frequencies is None:
            low, high = frequency_range
            frequencies = bins[(bins >= low) & (bins <= high)]
        candidates = []
        for frequency in frequencies:
            candidates.extend(tone_candidates(power, bins, window_size, hop, sample_rate,
                                              frequency, tolerance, min_beep_duration,
                                              frequency_range))
        if frequency_range is not None:
            # A bin-sized step at the fundamental would become a three-bin
            # gap at the third harmonic. Seed from third-harmonic bins instead.
            low, high = frequency_range
            harmonic_frequencies = bins[(bins >= 3 * low) & (bins <= 3 * high)] / 3
            for frequency in harmonic_frequencies:
                candidates.extend(harmonic_candidates(power, bins, window_size, hop, sample_rate,
                                                       frequency, tolerance, min_beep_duration,
                                                       frequency_range))
        # Lookahead resolves tones starting at the end of a batch before we
        # select its earliest match. Starts in the next batch wait for that batch.
        candidates = [candidate for candidate in candidates if candidate[0] < 2048]
        if candidates:
            frame, _, frequency = min(candidates)[:3]
            frame += base
            onset = 0.0 if frame == 0 else (frame * hop + window_size / 2) / sample_rate
            return onset, frequency
    return None


def audio_spectrum(samples, sample_rate, min_beep_duration):
    if min_beep_duration <= 0 or not math.isfinite(min_beep_duration):
        raise ValueError('Minimum beep duration must be positive and finite.')
    samples = np.asarray(samples)
    if samples.ndim == 1:
        samples = samples[:, None]
    if samples.ndim != 2 or samples.shape[1] == 0:
        raise ValueError('Expected audio samples with one or more channels.')
    window_size = round(sample_rate * 0.020)
    hop = max(1, round(sample_rate * 0.005))
    if len(samples) < window_size:
        raise ValueError('Audio is too short to detect a beep.')
    window = np.hanning(window_size)
    bins = np.fft.rfftfreq(window_size, 1 / sample_rate)
    frames = np.lib.stride_tricks.sliding_window_view(samples, window_size, axis=0)[::hop]
    lookahead = max(1, math.ceil(min_beep_duration * sample_rate / hop))
    for start in range(0, len(frames), 2048):
        power = np.abs(np.fft.rfft(frames[start:start + 2048 + lookahead] * window, axis=-1)) ** 2
        yield power, bins, window_size, hop, start


def tone_candidates(power, bins, window_size, hop, sample_rate, frequency,
                    tolerance, min_beep_duration, frequency_range=None):
    band = np.abs(bins - frequency) <= tolerance
    if not band.any():
        raise ValueError('Frequency tolerance is too narrow for the analysis resolution.')
    neighborhood = np.abs(bins - frequency) <= max(600, tolerance * 3)
    levels = power[..., band].sum(axis=-1)
    ratios = levels / np.maximum(power.sum(axis=-1), 1e-20)
    local_ratios = levels / np.maximum(power[..., neighborhood].sum(axis=-1), 1e-20)
    # Use an absolute silence floor and local spectral contrast. A later loud
    # event must not retroactively disqualify an earlier clear tone.
    floor = (1e-4 * window_size) ** 2
    strong = ((levels >= floor) &
              (ratios >= 0.08) & (local_ratios >= 0.65))
    measured_frequencies = None
    if frequency_range is not None:
        # Validate each window's peak, not the average of a whole event: an
        # adjacent out-of-range tone must never contribute to the beep onset.
        measured_frequencies, valid_peaks = spectral_peaks(power, band, bins)
        low, high = frequency_range
        strong &= (valid_peaks &
                   (measured_frequencies >= low - 1) & (measured_frequencies <= high + 1))
    required = max(1, math.ceil(min_beep_duration * sample_rate / hop))
    candidates = []
    for channel in range(power.shape[1]):
        mask = strong[:, channel]
        edges = np.diff(np.r_[False, mask, False].astype(np.int8))
        starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
        for start, end in zip(starts, ends):
            if end - start >= required:
                measured = frequency
                if frequency_range is not None:
                    low, high = frequency_range
                    measured = float(np.clip(np.median(measured_frequencies[start:end, channel]), low, high))
                else:
                    values, valid = spectral_peaks(power[start:end, channel:channel + 1], band, bins)
                    if valid.any():
                        measured = float(np.median(values[valid]))
                candidates.append((start, -float(local_ratios[start:end, channel].mean()), measured, end))
    return candidates


def spectral_peaks(power, band, bins):
    """Interpolate local peaks independently for each time window/channel."""
    peaks = np.flatnonzero(band)[np.argmax(power[..., band], axis=-1)]
    safe_peaks = np.clip(peaks, 1, len(bins) - 2)
    left, center, right = [np.log(np.maximum(np.take_along_axis(
        power, (safe_peaks + offset)[..., None], axis=-1)[..., 0], 1e-30))
        for offset in (-1, 0, 1)]
    curvature = left - 2 * center + right
    offsets = np.divide(.5 * (left - right), curvature,
                        out=np.zeros_like(curvature), where=curvature < -1e-12)
    return (peaks + offsets) * (bins[1] - bins[0]), (peaks == safe_peaks) & (np.abs(offsets) <= .5)


def harmonic_candidates(power, bins, window_size, hop, sample_rate, frequency,
                        tolerance, min_beep_duration, frequency_range):
    """Recover a masked fundamental from simultaneous second/third harmonics.

    Both narrow peaks must persist in the same channel and imply the same
    in-range fundamental. A single out-of-range tone is never sufficient.
    """
    if 3 * frequency + tolerance >= bins[-1]:
        return []
    masks, estimates, scores = [], [], []
    total = np.maximum(power.sum(axis=-1), 1e-20)
    floor = (1e-4 * window_size) ** 2
    low, high = frequency_range
    for harmonic in (2, 3):
        center = harmonic * frequency
        band = np.abs(bins - center) <= tolerance
        if not band.any():
            return []
        neighborhood = np.abs(bins - center) <= max(600, tolerance * 3)
        level = power[..., band].sum(axis=-1)
        local = level / np.maximum(power[..., neighborhood].sum(axis=-1), 1e-20)
        measured, valid = spectral_peaks(power, band, bins)
        fundamental = measured / harmonic
        masks.append(valid & (level >= floor) & (level / total >= .02) & (local >= .5) &
                     (fundamental >= low - 1) & (fundamental <= high + 1))
        estimates.append(fundamental)
        scores.append(local)
    strong = masks[0] & masks[1] & (np.abs(estimates[0] - estimates[1]) <= 15)
    required = max(1, math.ceil(min_beep_duration * sample_rate / hop))
    candidates = []
    for channel in range(power.shape[1]):
        edges = np.diff(np.r_[False, strong[:, channel], False].astype(np.int8))
        starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
        for start, end in zip(starts, ends):
            if end - start >= required:
                measured = np.median((estimates[0][start:end, channel] + estimates[1][start:end, channel]) / 2)
                score = np.minimum(scores[0][start:end, channel], scores[1][start:end, channel]).mean()
                candidates.append((start, -float(score), float(np.clip(measured, low, high)), end))
    return candidates


def find_beep_candidates(samples, sample_rate, frequency='auto', tolerance=100, min_beep_duration=.05):
    """Retain all qualifying events so the batch can resolve local ambiguity."""
    automatic = frequency == 'auto'
    if automatic:
        if not 0 < tolerance < 1200 or sample_rate / 2 <= 3000 + max(600, tolerance * 3):
            raise ValueError('Invalid tolerance or sample rate for automatic detection.')
        frequency_range = (1200, 3000)
    else:
        if not 0 < frequency - tolerance < frequency + tolerance < sample_rate / 2:
            raise ValueError('Frequency band must be above zero and below the Nyquist frequency.')
        frequency_range = None
    events = []
    for power, bins, window_size, hop, base in audio_spectrum(samples, sample_rate, min_beep_duration):
        frequencies = bins[(bins >= 1200) & (bins <= 3000)] if automatic else [frequency]
        candidates = []
        for center in frequencies:
            candidates.extend(tone_candidates(power, bins, window_size, hop, sample_rate,
                                              center, tolerance, min_beep_duration, frequency_range))
        if automatic:
            for center in bins[(bins >= 3600) & (bins <= 9000)] / 3:
                candidates.extend(harmonic_candidates(power, bins, window_size, hop, sample_rate,
                                                       center, tolerance, min_beep_duration, frequency_range))
        for start, score, measured, end in candidates:
            if start >= 2048:
                continue
            frame = start + base
            onset = 0.0 if frame == 0 else (frame * hop + window_size / 2) / sample_rate
            events.append(BeepCandidate(onset, measured, (end - start) * hop / sample_rate, -score))
    return merge_candidates(events)


def find_ffmpeg(explicit=None):
    if explicit:
        found = shutil.which(explicit)
        if not found:
            raise ValueError(f'FFmpeg executable not found: {explicit}')
        return found
    found = shutil.which('ffmpeg')
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as exc:
        raise ValueError('Install dependencies with: python -m pip install -r requirements.txt') from exc


def decode_audio(ffmpeg, path, seconds, sample_rate):
    # Keep original A/V offsets, normalizing the container start to zero.
    command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin',
               '-copyts', '-start_at_zero', '-i', str(path), '-t', str(seconds),
               '-map', '0:a:0', '-vn', '-af', 'aresample=async=1:first_pts=0',
               '-ac', '2', '-ar', str(sample_rate), '-f', 'f32le', 'pipe:1']
    result = subprocess.run(command, capture_output=True)
    if result.returncode:
        raise ValueError(f'Cannot decode audio from {path}:\n{result.stderr.decode(errors="replace").strip()}')
    return np.frombuffer(result.stdout, dtype='<f4').reshape(-1, 2)


def video_endpoint(ffmpeg, path):
    """Read packet PTS and durations without decoding the video.

    The container's duration can describe audio continuing after video ends.
    framecrc exposes the actual video packet timestamps without ffprobe.
    """
    result = subprocess.run([ffmpeg, '-hide_banner', '-v', 'error', '-nostdin',
                             '-copyts', '-start_at_zero', '-i', str(path),
                             '-map', '0:v:0', '-c:v', 'copy', '-f', 'framecrc', 'pipe:1'],
                            capture_output=True, text=True)
    timebase = re.search(r'#tb 0: (\d+)/(\d+)', result.stdout)
    if result.returncode or not timebase:
        raise ValueError(f'Cannot read video timestamps for {path}: {result.stderr.strip()}')
    endpoints = []
    for line in result.stdout.splitlines():
        if line.startswith('0,'):
            fields = line.split(',')
            try:
                endpoints.append(int(fields[2]) + int(fields[3]))
            except (ValueError, IndexError) as exc:
                raise ValueError(f'Invalid video packet timestamp in {path}.') from exc
    if not endpoints:
        raise ValueError(f'No video frames found in {path}.')
    numerator, denominator = map(int, timebase.groups())
    return max(endpoints) * numerator / denominator


def render(ffmpeg, files, beeps, output, *, pre_roll=1, height=720, fps=30,
           audio='first', duration=None, overwrite=False):
    # Bound padding explicitly: an infinite apad can stall a multi-input graph
    # before FFmpeg's output-level -shortest gets a chance to terminate it.
    remaining = []
    for path, beep in zip(files, beeps):
        endpoint = video_endpoint(ffmpeg, path)
        if beep >= endpoint:
            raise ValueError(f'{path}: detected beep lies beyond the video endpoint ({endpoint:.3f}s).')
        remaining.append(endpoint - beep + pre_roll)
    output_duration = max(remaining)
    if duration is not None:
        output_duration = min(output_duration, duration)
    if output_duration < 1 / fps:
        raise ValueError('Output duration must contain at least one video frame.')
    command = [ffmpeg, '-hide_banner', '-loglevel', 'warning', '-stats', '-nostdin',
               '-y' if overwrite else '-n', '-copyts', '-start_at_zero']
    for path in files:
        command += ['-i', str(path)]
    filters, audio_labels = [], []
    for i, beep in enumerate(beeps):
        trim, pad = max(0, beep - pre_roll), max(0, pre_roll - beep)
        filters.append(
            f'[{i}:v:0]trim=start={trim:.9f},setpts=PTS-{trim:.9f}/TB,'
            f'scale=w=trunc(oh*dar/2)*2:h={height},setsar=1,'
            f'fps=fps={fps}:start_time=0,format=yuv420p,'
            f'tpad=start_mode=clone:start_duration={pad:.9f}:'
            f'stop_mode=add:color=black:stop_duration={output_duration:.9f}[v{i}]')
        if audio == 'mix' or (audio == 'first' and i == 0):
            delay_samples = round(pad * 48000)
            filters.append(
                f'[{i}:a:0]aresample=48000:async=1:first_pts=0,'
                f'atrim=start={trim:.9f},asetpts=PTS-STARTPTS,'
                f'adelay=delays={delay_samples}S:all=1[a{i}]')
            audio_labels.append(f'[a{i}]')
    filters.append(''.join(f'[v{i}]' for i in range(len(files))) +
                   f'hstack=inputs={len(files)}:shortest=1[vout]')
    if audio_labels:
        if audio == 'mix':
            filters.append(''.join(audio_labels) +
                           f'amix=inputs={len(audio_labels)}:duration=longest:normalize=1,'
                           f'apad=whole_dur={output_duration:.9f}[aout]')
        else:
            filters.append(f'{audio_labels[0]}apad=whole_dur={output_duration:.9f}[aout]')
    command += ['-filter_complex', ';'.join(filters), '-map', '[vout]']
    if audio_labels:
        command += ['-map', '[aout]', '-c:a', 'aac', '-b:a', '192k', '-shortest']
    else:
        command += ['-an']
    command += ['-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
                '-pix_fmt', 'yuv420p', '-movflags', '+faststart']
    command += ['-t', str(output_duration)]
    command += [str(output)]
    result = subprocess.run(command)
    if result.returncode:
        raise ValueError(f'FFmpeg rendering failed (exit {result.returncode}). See messages above.')
    video_endpoint(ffmpeg, output)  # Do not report success for an empty render.


def positive_float(value):
    try:
        number = float(value.replace(',', '.'))
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Expected a number.') from exc
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('Must be a positive finite number.')
    return number


def frequency_argument(value):
    return 'auto' if value.lower() == 'auto' else positive_float(value)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('inputs', nargs='+', type=Path, help='2–4 input videos, in left-to-right order')
    parser.add_argument('-f', '--frequency', type=frequency_argument, default=2700,
                        help='Beep frequency in Hz, or auto to search 1200–3000 Hz')
    parser.add_argument('-o', '--output', type=Path, default=Path('synced.mp4'), help='Output MP4')
    parser.add_argument('--pre-roll', type=positive_float, default=1.0, help='Seconds before the beep')
    parser.add_argument('--search-seconds', type=positive_float, default=30.0, help='Seconds to search at the beginning')
    parser.add_argument('--tolerance', type=positive_float, default=100.0, help='Frequency tolerance in Hz, plus/minus')
    parser.add_argument('--min-beep-duration', type=positive_float, default=0.05, help='Minimum sustained tone in seconds')
    parser.add_argument('--height', type=int, default=720, help='Output height in pixels (positive even integer)')
    parser.add_argument('--fps', type=positive_float, default=30.0, help='Output frames per second')
    parser.add_argument('--audio', choices=['first', 'mix', 'none'], default='first', help='Output audio source')
    parser.add_argument('--duration', type=positive_float, help='Limit rendered duration in seconds')
    parser.add_argument('--detect-only', action='store_true', help='Print beep timings without rendering')
    parser.add_argument('--overwrite', action='store_true', help='Replace an existing output file')
    parser.add_argument('--ffmpeg', help='Path to an FFmpeg executable')
    args = parser.parse_args(argv)
    if not 2 <= len(args.inputs) <= 4:
        parser.error('Provide 2–4 input videos.')
    if args.height < 2 or args.height % 2:
        parser.error('--height must be a positive even integer.')
    automatic = args.frequency == 'auto'
    if automatic and args.tolerance >= 1200:
        parser.error('Automatic detection requires --tolerance below 1200 Hz.')
    if not automatic and (args.frequency > 20000 or args.frequency <= args.tolerance):
        parser.error('--frequency must exceed --tolerance and be at most 20000 Hz.')
    for path in args.inputs:
        if not path.is_file():
            parser.error(f'Input file does not exist: {path}')
        if args.output.resolve() == path.resolve() or (args.output.exists() and os.path.samefile(args.output, path)):
            parser.error('Output must not overwrite an input video.')
    if not args.detect_only:
        if args.output.suffix.lower() != '.mp4':
            parser.error('Output must use the .mp4 extension.')
        if not args.output.parent.is_dir():
            parser.error('Output directory does not exist.')
        if args.output.exists() and not args.overwrite:
            parser.error('Output already exists; use --overwrite to replace it.')
    try:
        ffmpeg = find_ffmpeg(args.ffmpeg)
        rate = (max(24000, math.ceil((9000 + args.tolerance + 1000) * 2))
                if automatic else max(16000, math.ceil((args.frequency + args.tolerance + 1000) * 2)))
        candidate_lists = []
        for path in args.inputs:
            print(f'Analyzing {path} ...', flush=True)
            samples = decode_audio(ffmpeg, path, args.search_seconds, rate)
            try:
                candidates = find_beep_candidates(samples, rate, args.frequency, args.tolerance,
                                                  args.min_beep_duration)
            except ValueError as exc:
                raise ValueError(f'{path}: {exc}') from exc
            candidate_lists.append(candidates)
            print(f'  {len(candidates)} beep candidate(s)', flush=True)
        selected = select_batch(candidate_lists)
        beeps = [candidate.onset for candidate in selected]
        print('Matched beep across the batch:', flush=True)
        for path, candidate in zip(args.inputs, selected):
            beep, frequency = candidate.onset, candidate.frequency
            print(f'  {path}: beep={beep:.3f}s  frequency={frequency:.0f}Hz  duration={candidate.duration:.3f}s'
                  f'  trim={max(0, beep - args.pre_roll):.3f}s'
                  f'  pad={max(0, args.pre_roll - beep):.3f}s', flush=True)
        if not args.detect_only:
            render(ffmpeg, args.inputs, beeps, args.output, pre_roll=args.pre_roll,
                   height=args.height, fps=args.fps, audio=args.audio,
                   duration=args.duration, overwrite=args.overwrite)
            print(f'Saved {args.output.resolve()}', flush=True)
        return 0
    except (ValueError, OSError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Cancelled.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
