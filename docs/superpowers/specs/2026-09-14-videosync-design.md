# Video synchronization CLI

Approved in chat: a Python CLI accepting 2–4 videos and a beep frequency
(default 2700 Hz), aligning beep onset at one second, rendering a horizontal
row with preserved aspect ratios, and stopping at the shortest aligned video.

Use NumPy windowed spectral analysis, independently on each audio channel, to
find the first sustained tone near the requested frequency. This does not
require the recordings to contain the same scene. Decode and render with
FFmpeg, available through PATH or imageio-ffmpeg's bundled binary.

Search the first 30 seconds by default; expose search duration, frequency
tolerance, minimum beep duration, and pre-roll. Reject missing tones rather
than guessing. Print detected onsets and trim/padding offsets. Detection-only
mode supports inspection without rendering.

Default audio is the first input; optional mix and mute modes. Preserve video
aspect ratios at a common configurable height, use 30 fps by default, and
encode H.264/AAC MP4. Prepend a frozen first frame and silence if the recording
does not contain a full pre-roll. Refuse overwrites unless explicitly requested
and never overwrite an input. Synchronization is by onset, with video precision
limited to a frame; this does not correct long-term clock drift.

Validate detection with synthetic tones, noise, wrong frequencies, short
transients, and opposing stereo phase. Validate actual FFmpeg rendering for
2–4 inputs, audio modes, early beeps, and unequal durations. Run the supplied
two recordings and inspect a rendered frame and detected output beep.
