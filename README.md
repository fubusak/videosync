# VideoSync

Synchronize **2–4 videos using a beep**, then render them horizontally in input
order. The recordings can show entirely different events, but the batch is
assumed to use the **same kind of starting beep: similar frequency and duration**.
The CLI selects a consistent beep across all inputs and places its detected
onset approximately one second into the output.

## Installation

Python **3.10 or newer**:

```sh
python -m venv .venv
# Windows:
.venv\Scripts\python -m pip install -r requirements.txt
# macOS/Linux:
.venv/bin/python -m pip install -r requirements.txt
```

The dependencies are NumPy and imageio-ffmpeg. On supported platforms,
imageio-ffmpeg supplies FFmpeg; you can also use FFmpeg from PATH or pass
`--ffmpeg /path/to/ffmpeg`. No separate ffprobe installation is needed.

Activate the environment before the examples below (`.venv\Scripts\Activate.ps1`
in PowerShell or `source .venv/bin/activate` on macOS/Linux), or replace `python`
with the environment's Python path. On Windows, `videosync.cmd` automatically
uses the local `.venv` and forwards its arguments.

## Web Docker image

Build the private web MVP image:

```sh
docker build -t videosync-web:dev .
```

Run it locally with a shared beta password:

```sh
docker run --rm -p 8501:8501 -e VIDEOSYNC_PASSWORD=change-me videosync-web:dev
```

Then open `http://localhost:8501`. The container includes FFmpeg and runs the
Streamlit app entrypoint; upload and synchronization controls are being added
behind this image.

## Usage

```sh
python videosync.py first.mp4 second.mp4 -o synced.mp4
python videosync.py first.mp4 second.mp4 --frequency 2700 -o synced.mp4
python videosync.py first.mp4 second.mp4 --frequency auto --audio mix -o automatic.mp4
python videosync.py a.mp4 b.mp4 c.mp4 d.mp4 --audio mix -o four.mp4
python videosync.py first.mp4 second.mp4 --detect-only
```

Frequency is in **Hz**: 2.7 kHz is `2700`. Decimal commas are accepted in numeric
arguments (e.g. `--pre-roll 1,5` means 1.5 seconds).

Use **`--frequency auto`** to detect any stable beep within **1200–3000 Hz**,
including the endpoints. The CLI retains candidates in every recording, then
compares their frequencies and durations across the whole batch. It prints
each selected onset, measured frequency and observed duration. Without this
option, the default remains 2700 Hz; batch consistency also applies in fixed
frequency mode.

Matching requires a candidate in **every** video. If the frequencies or
durations disagree, the CLI reports an error instead of rendering unrelated
beeps. `--detect-only` performs this same batch check without rendering.

| Option | Default | Purpose |
| --- | --- | --- |
| `-f`, `--frequency` | `2700` | Beep frequency in Hz, or `auto` for 1200–3000 Hz |
| `-o`, `--output` | `synced.mp4` | Output MP4 path |
| `--pre-roll` | `1` | Seconds before the detected beep |
| `--search-seconds` | `30` | Search this many seconds from each input's start |
| `--tolerance` | `100` | Frequency band, plus/minus Hz |
| `--min-beep-duration` | `0.05` | Required sustained tone duration in seconds |
| `--audio` | `first` | First recording, `mix` all recordings, or `none` |
| `--height` | `720` | Common video height; positive even number |
| `--fps` | `30` | Output frame rate |
| `--duration` | longest aligned video | Limit output length, useful for previews |
| `--detect-only` | off | Print beep and trim/padding times without rendering |
| `--overwrite` | off | Allow replacing an existing output |
| `--ffmpeg` | auto | Explicit FFmpeg executable |

All inputs must contain a video and an audio stream, even in silent-output
mode: the audio is needed for detection. Output is H.264/AAC MP4 (no audio
stream with `--audio none`). Video aspect ratios are preserved at a common
height. Output width is the sum of the scaled video widths.

When a beep occurs before the requested pre-roll, the CLI adds a frozen first
frame and silence. It runs until the longest aligned video ends, turning each
shorter video's panel black when it finishes. A duration limit can end it sooner.
Input files are never overwritten, including with `--overwrite`.
Rendering errors or cancellation may leave a partial output; rerun with a new
output name or `--overwrite`.

## Included recordings

The supplied recordings have a prominent tone near **1500 Hz**, rather than
2700 Hz. The rendered `synced.mp4` was made with:

```powershell
.\videosync.cmd PXL_20260913_124051052.TS.mp4 PXL_20260913_125101103.TS.mp4 --frequency 1500 -o synced.mp4
```

The detector found 1.265 s and 0.350 s respectively, resulting in 0.265 s of
trimming on the first video and 0.650 s of initial padding on the second.

Automatic mode finds approximately 1506 Hz and 1502 Hz at the same onsets:

```powershell
.\videosync.cmd PXL_20260913_124051052.TS.mp4 PXL_20260913_125101103.TS.mp4 --frequency auto --audio mix -o synced-auto.mp4
```

## Detection and limitations

Batch matching uses a maximum 40 Hz frequency spread. Observed durations
normally must agree within 30% of the longest beep, or 40 ms for short beeps.
The earliest compatible group wins; frequency/duration agreement and signal
quality resolve ties at the same combined onset time.

Shooting can hide pieces of a beep, so observed duration is not always its
physical duration. A clear candidate in another file can support joining
same-frequency noisy fragments with gaps up to 300 ms, provided their full
span matches its duration. A noisy candidate may be up to 40% shorter than a
clear reference. The implementation uses a spectral-concentration score of
0.9 to distinguish clear references; this is a heuristic, not a calibrated
probability. These checks never invent an earlier onset or stretch playback.

The detector uses 20 ms Hann-windowed FFTs with 5 ms hops. It checks tone
strength and concentration relative to neighboring frequencies, requires a
sustained detection, and analyzes stereo channels independently to avoid
phase cancellation. FFmpeg preserves stream timestamp offsets while decoding
and rendering. See the [FFmpeg filter documentation](https://ffmpeg.org/ffmpeg-filters.html)
for the stacking, trimming and padding filters used here.

Automatic mode processes bounded FFT batches and reuses each batch for narrow
candidate bands throughout the search range. It checks the dominant frequency
in every window by interpolating the spectral peak, rejecting tones outside
the range rather than treating every
sound in one broad band as a beep. The frequency estimate is approximate;
there is a 1 Hz numerical margin at the boundaries. `--tolerance` controls
the candidate band width and does not expand the automatic search range.

If shooting or microphone overload masks the fundamental, automatic mode can
also infer it from matching **second and third harmonics**. Both must be
present at the same time in the same channel, persist for the minimum beep
duration, and imply the same fundamental (within 15 Hz). A single harmonic or
broadband impact is insufficient. Automatic CLI analysis uses 24 kHz audio
to retain the harmonics of fundamentals up to 3000 Hz. Direct Python calls
using lower sample rates can only use harmonics below their Nyquist limit.

For the local `hopacka_m.mp4` / `houpacka_v.mp4` recordings, this finds the start
beeps at **1.190 s** and **3.700 s**, respectively, near 1507 Hz. Previously the
second clip's masked fundamental was missed and a later unrelated tone was
selected. Create the corrected comparison with:

```powershell
.\videosync.cmd hopacka_m.mp4 houpacka_v.mp4 --frequency auto --audio mix -o houpacka-fixed.mp4
```

The timing is approximate: output video alignment is limited to the selected
frame rate, and noise masking the tone's attack can delay the detected onset.
Synthetic clear-tone tests allow 15 ms detection error and 25 ms after AAC
encoding. These are test tolerances, not an accuracy guarantee for noisy
recordings. This aligns the starting beep; it does not correct clock drift
over long recordings. If several sounds have matching frequency and duration
in every file, the earliest compatible group can still be the wrong event;
specify the known frequency or shorten the search window when needed. If no
consistent group exists, the CLI fails; check the inputs and search settings.

## Tests

```sh
python -m unittest discover -s tests -v
```

Tests cover synthetic tones, noise, masked fundamentals, clipped impacts,
matching and mismatched harmonics, batch frequency/duration disagreements,
earlier distractors, masked fragments, opposite stereo phase, missing
tones, input protection, and real FFmpeg renders of 2–4 clips with known audio
beeps and visual flashes. The houpacka regression runs when those two local
recordings are available and skips otherwise; recordings are not stored in Git.
