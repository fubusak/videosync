# VideoSync

Synchronize **2–4 videos using a beep**, then render them horizontally in input
order. The recordings can show entirely different events. The CLI detects the
first sustained tone near the chosen frequency and places it approximately one
second into the output.

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

## Usage

```sh
python videosync.py first.mp4 second.mp4 -o synced.mp4
python videosync.py first.mp4 second.mp4 --frequency 2700 -o synced.mp4
python videosync.py a.mp4 b.mp4 c.mp4 d.mp4 --audio mix -o four.mp4
python videosync.py first.mp4 second.mp4 --detect-only
```

Frequency is in **Hz**: 2.7 kHz is `2700`. Decimal commas are accepted in numeric
arguments (e.g. `--pre-roll 1,5` means 1.5 seconds).

| Option | Default | Purpose |
| --- | --- | --- |
| `-f`, `--frequency` | `2700` | Beep frequency in Hz |
| `-o`, `--output` | `synced.mp4` | Output MP4 path |
| `--pre-roll` | `1` | Seconds before the detected beep |
| `--search-seconds` | `30` | Search this many seconds from each input's start |
| `--tolerance` | `100` | Frequency band, plus/minus Hz |
| `--min-beep-duration` | `0.05` | Required sustained tone duration in seconds |
| `--audio` | `first` | First recording, `mix` all recordings, or `none` |
| `--height` | `720` | Common video height; positive even number |
| `--fps` | `30` | Output frame rate |
| `--duration` | shortest aligned video | Limit output length, useful for previews |
| `--detect-only` | off | Print beep and trim/padding times without rendering |
| `--overwrite` | off | Allow replacing an existing output |
| `--ffmpeg` | auto | Explicit FFmpeg executable |

All inputs must contain a video and an audio stream, even in silent-output
mode: the audio is needed for detection. Output is H.264/AAC MP4 (no audio
stream with `--audio none`). Video aspect ratios are preserved at a common
height. Output width is the sum of the scaled video widths.

When a beep occurs before the requested pre-roll, the CLI adds a frozen first
frame and silence. It stops at the shortest aligned video; a duration limit can
end it sooner. Input files are never overwritten, including with `--overwrite`.
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

## Detection and limitations

The detector uses 20 ms Hann-windowed FFTs with 5 ms hops. It checks tone
strength and concentration relative to neighboring frequencies, requires a
sustained detection, and analyzes stereo channels independently to avoid
phase cancellation. FFmpeg preserves stream timestamp offsets while decoding
and rendering. See the [FFmpeg filter documentation](https://ffmpeg.org/ffmpeg-filters.html)
for the stacking, trimming and padding filters used here.

The timing is approximate: output video alignment is limited to the selected
frame rate, and noise masking the tone's attack can delay the detected onset.
Synthetic clear-tone tests allow 15 ms detection error and 25 ms after AAC
encoding. These are test tolerances, not an accuracy guarantee for noisy
recordings. This aligns the starting beep; it does not correct clock drift
over long recordings. An earlier sustained sound at the same frequency may
be mistaken for the intended beep. If no clear tone is found, the CLI fails
instead of silently guessing; check frequency or increase the search window.

## Tests

```sh
python -m unittest discover -s tests -v
```

Tests cover synthetic tones, noise, harmonics, opposite stereo phase, missing
tones, input protection, and real FFmpeg renders of 2–4 clips with known audio
beeps and visual flashes. No supplied recordings are needed for the tests.
