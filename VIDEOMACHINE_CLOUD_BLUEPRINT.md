# VIDEOMACHINE_CLOUD_BLUEPRINT.md

Specification and reference implementation for `VideoMachine`: Sony FX3 / a7V 4K 10-bit footage in, 9:16 reels out, on macOS Apple Silicon. No paid APIs, no cloud keys, no NVIDIA/CUDA.

**Status: written in a cloud session with no shell and no Mac. None of the code below has been executed.** The first job of the downstream worker is to create the four files and run `python3 verify_pipeline.py` on the Mac. Section 5 lists the points most likely to need adjustment.

## 0. Layout and contracts

```
videomachine_core.py      # section 1: processes, time math, temp files
videomachine_render.py    # section 2: filtergraph builder + render()
videomachine_preset.py    # section 3: preset + cut-list validator
verify_pipeline.py        # section 4: smoke test
presets/preset.schema.json
presets/*.json            # e.g. automotive-roadster-outlier-2026-10-31.json
raw/test_clip.mp4         # 10 s, 720x1280, 30 fps
```

- **Cut list**: `[[start_s, end_s], ...]`, the segments to *keep*, in playback order, all from one source file. Cut points at 3.0 s and 7.0 s on the test clip mean the segments `[0,3] [3,7] [7,10]`.
- **Frame rule**: every time is converted to a frame index once (`to_frame`), and all later math is in integer frames and `Fraction`. A segment is the half-open frame range `[to_frame(start), to_frame(end))`.
- **Run from the repo root.** Preset LUT paths are relative to it.

Global rules:

- IF a module other than `videomachine_core.py` imports `subprocess`, `tempfile` or `shutil.rmtree` THEN reject the change.
- IF a render needs a file written between the source and the final MP4 THEN the design is wrong; the render path is one `ffmpeg` process.
- IF a video came from `yt-dlp` THEN it is reference material for trend analysis (metadata, cut cadence, transcript) and never an input to `render()`.
- IF `encode.codec` is anything other than `h264` or `hevc` on VideoToolbox THEN reject; `VM_VCODEC` exists only so the smoke test can run on a non-Mac CI box.

## 1. Unified core module (`videomachine_core.py`)

```python
"""videomachine_core.py - the ONLY module that may spawn processes, do time math, or create temp files."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path

TOOLS = {  # name: (binary, args always prepended)
    "ffmpeg": ("ffmpeg", ["-hide_banner", "-nostdin", "-y", "-loglevel", "error"]),
    "ffprobe": ("ffprobe", ["-v", "error", "-of", "json"]),
    "whisper": ("whisper-cli", ["-np"]),
    "ytdlp": ("yt-dlp", ["--no-playlist", "--no-progress"]),
}
TMP_PREFIX = "vm_"


class ToolError(RuntimeError):
    pass


# ---------- process execution ----------
def run(tool, *args, timeout=3600):
    """Run one external tool and return its stdout. Returning at all means exit code 0."""
    exe, base = TOOLS[tool]
    exe = os.environ.get(f"VM_{tool.upper()}_BIN", exe)
    if shutil.which(exe) is None:
        raise ToolError(f"{exe}: not found on PATH")
    cmd = [exe, *base, *map(str, args)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise ToolError(f"{exe}: timed out after {timeout}s") from e
    if p.returncode != 0:
        raise ToolError(f"{exe}: exit {p.returncode}\n{p.stderr.strip()[-2000:]}")
    return p.stdout


# ---------- time and frame math ----------
def frac(x):
    return x if isinstance(x, Fraction) else Fraction(str(x))


def to_frame(t, fps):
    """Nearest frame index for a non-negative time; exact halves round up."""
    return int(frac(t) * fps + Fraction(1, 2))


def to_time(frame, fps):
    return Fraction(frame) / fps


def snap(t, fps):
    return to_time(to_frame(t, fps), fps)


def sec(x):
    """Format a time for an ffmpeg argument."""
    return f"{float(x):.6f}"


def parse_ts(ts):
    """'HH:MM:SS.mmm', 'MM:SS', '12.5' or whisper's '00:00:01,500' -> Fraction seconds."""
    total = Fraction(0)
    for part in str(ts).strip().replace(",", ".").split(":"):
        total = total * 60 + Fraction(part)
    return total


def fmt_ts(t):
    ms = int(frac(t) * 1000 + Fraction(1, 2))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


# ---------- probing ----------
def _num(x):
    try:
        return Fraction(str(x))
    except (ValueError, ZeroDivisionError):
        return Fraction(0)


def probe(path):
    d = json.loads(run("ffprobe", "-show_format", "-show_streams", path))
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    if v is None:
        raise ToolError(f"{path}: no video stream")
    fps = _num(v["r_frame_rate"])
    dur = _num(v.get("duration") or d["format"]["duration"])
    w, h = int(v["width"]), int(v["height"])
    rot = next((int(float(sd["rotation"])) for sd in v.get("side_data_list", []) if "rotation" in sd), 0)
    if rot % 180:  # ffmpeg auto-rotates on decode, so report the displayed size
        w, h = h, w
    return {
        "width": w, "height": h, "fps": fps, "duration": dur, "pix_fmt": v.get("pix_fmt"),
        "cfr": fps > 0 and abs(_num(v.get("avg_frame_rate")) - fps) * 1000 < fps,
        "frames": int(v["nb_frames"]) if str(v.get("nb_frames", "")).isdigit() else to_frame(dur, fps),
        "v_start": _num(v.get("start_time")),
        "has_audio": a is not None,
        "a_start": _num(a.get("start_time")) if a else None,
        "a_duration": _num(a.get("duration")) if a else None,
    }


def count_frames(path):
    """Decode the file and count video frames (slow, exact)."""
    d = json.loads(run("ffprobe", "-count_frames", "-select_streams", "v:0",
                       "-show_entries", "stream=nb_read_frames", path))
    return int(d["streams"][0]["nb_read_frames"])


# ---------- temp files ----------
def tmp_root():
    p = Path(os.environ.get("VM_TMP") or tempfile.gettempdir())
    p.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def workdir():
    """Scratch directory that is removed on exit, error or not."""
    d = Path(tempfile.mkdtemp(prefix=TMP_PREFIX, dir=tmp_root()))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


@contextmanager
def atomic_output(dst):
    """Yield a hidden sibling path; rename it onto dst on success, delete it on failure."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_name(f".{TMP_PREFIX}part_{dst.name}")
    try:
        yield part
        os.replace(part, dst)
    finally:
        part.unlink(missing_ok=True)


def leftovers():
    return sorted(tmp_root().glob(TMP_PREFIX + "*"))


# ---------- whisper.cpp and yt-dlp ----------
def extract_wav(src, dst):
    """16 kHz mono PCM, the only input whisper-cli accepts."""
    run("ffmpeg", "-i", src, "-vn", "-ac", 1, "-ar", 16000, "-c:a", "pcm_s16le", dst)
    return Path(dst)


def transcribe(src, model, lang="auto"):
    """-> [{'start': Fraction, 'end': Fraction, 'text': str}, ...]"""
    with workdir() as d:
        run("whisper", "-m", model, "-f", extract_wav(src, d / "a.wav"), "-l", lang, "-oj", "-of", d / "out")
        segs = json.loads((d / "out.json").read_text(encoding="utf-8"))["transcription"]
    return [{"start": Fraction(s["offsets"]["from"], 1000), "end": Fraction(s["offsets"]["to"], 1000),
             "text": s["text"].strip()} for s in segs]


def ytdlp_meta(url):
    return json.loads(run("ytdlp", "-J", "--skip-download", url))


def ytdlp_download(url, outdir):
    out = run("ytdlp", "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b", "--merge-output-format", "mp4",
              "-P", outdir, "-o", "%(id)s.%(ext)s", "--no-simulate", "--print", "after_move:filepath", url)
    return Path(out.strip().splitlines()[-1])
```

Rules:

- IF a tool is needed THEN call `vm.run("<name>", ...)`; a new tool is one new row in `TOOLS`, never a new wrapper.
- IF `run()` returns THEN the exit code was 0; any other outcome (missing binary, timeout, non-zero exit) is a `ToolError` carrying the last 2000 characters of stderr.
- IF a time crosses a module boundary THEN it is seconds as `int`, `float` or `Fraction`; convert with `to_frame` once and never multiply a float by a frame rate.
- IF the frame rate is fractional (29.97, 23.976, 59.94) THEN it stays a `Fraction` (`30000/1001`) from `probe()` all the way into the filtergraph.
- IF a scratch file is needed THEN it lives inside `with vm.workdir()`; IF a final file is written THEN it goes through `vm.atomic_output()`.
- IF `vm.leftovers()` is non-empty after a run THEN a process was killed mid-run; delete the listed `vm_*` directories before the next run.
- IF a binary lives outside `PATH` THEN set `VM_FFMPEG_BIN`, `VM_FFPROBE_BIN`, `VM_WHISPER_BIN` or `VM_YTDLP_BIN`.

## 2. Single-pass filtergraph and VideoToolbox builder (`videomachine_render.py`)

How it stays in sync without intermediates:

1. Consecutive cuts in chronological order share one decoder ("run"). A run is opened with `-ss` half a frame before its first frame, so the first decoded frame is always that frame, even at 29.97.
2. Video is cut by **frame index** (`trim=start_frame/end_frame`), audio by the matching exact times (`atrim`). Each segment's audio is the same length as its video to within one sample.
3. The `concat` filter joins video and audio together, so any sub-sample remainder is absorbed per segment and never accumulates.
4. `setpts=N/fps/TB,fps=fps` rewrites video timestamps from the frame counter, so the encoder receives exactly `sum(frames)` frames at a constant rate.

```python
"""videomachine_render.py - cut list + 9:16 crop + loudness normalisation in ONE ffmpeg process."""
from __future__ import annotations

import os
from fractions import Fraction

import videomachine_core as vm
from videomachine_preset import validate

VCODECS = {"h264": "h264_videotoolbox", "hevc": "hevc_videotoolbox"}


def build_command(src, dst, cuts, preset, info):
    """Return (ffmpeg args, expected output frame count). Assumes validate() has passed."""
    fps, audio = info["fps"], info["has_audio"]
    rate = f"{fps.numerator}/{fps.denominator}"
    fr, col, aud, enc = (preset[k] for k in ("framing", "color", "audio", "encode"))
    codec = os.environ.get("VM_VCODEC") or VCODECS[enc["codec"]]
    hw = ["-hwaccel", "videotoolbox"] if codec.endswith("videotoolbox") else []

    runs = []  # chronological runs of (first_frame, end_frame); one decoder per run
    for s, e in cuts:
        a, b = vm.to_frame(s, fps), vm.to_frame(e, fps)
        if runs and a >= runs[-1][-1][1]:
            runs[-1].append((a, b))
        else:
            runs.append([(a, b)])

    inputs, graph, pads, j = [], [], "", 0
    for i, run in enumerate(runs):
        first, last, m = run[0][0], run[-1][1], len(run)
        ss = max(Fraction(0), (first - Fraction(1, 2)) / fps)  # half a frame early
        lead = first / fps - ss                                # time of frame `first` after the seek
        inputs += [*hw, "-ss", vm.sec(ss), "-t", vm.sec((last - first + 2) / fps), "-i", str(src)]
        vsrc = [f"[{i}:v:0]"] if m == 1 else [f"[sv{j + q}]" for q in range(m)]
        asrc = [f"[{i}:a:0]"] if m == 1 else [f"[sa{j + q}]" for q in range(m)]
        if m > 1:
            graph.append(f"[{i}:v:0]split={m}{''.join(vsrc)}")
            if audio:
                graph.append(f"[{i}:a:0]asplit={m}{''.join(asrc)}")
        for (a, b), vs, as_ in zip(run, vsrc, asrc):
            graph.append(f"{vs}trim=start_frame={a - first}:end_frame={b - first},setpts=PTS-STARTPTS[v{j}]")
            if audio:
                t0 = lead + (a - first) / fps
                graph.append(f"{as_}atrim=start={vm.sec(t0)}:end={vm.sec(t0 + (b - a) / fps)},"
                             f"asetpts=PTS-STARTPTS[a{j}]")
            pads += f"[v{j}]" + (f"[a{j}]" if audio else "")
            j += 1
    total = sum(b - a for run in runs for a, b in run)

    if audio:
        graph.append(f"{pads}concat=n={j}:v=1:a=1[vc][ac]")
    else:  # silent source: synthesise a silent track so every reel has audio
        graph.append(f"{pads}concat=n={j}:v=1:a=0[vc]")
        graph.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={vm.sec(total / fps)}[ac]")

    W, H, ow, oh = info["width"], info["height"], fr["width"], fr["height"]
    cw, ch = min(W, H * ow // oh) // 2 * 2, min(H, W * oh // ow) // 2 * 2
    x, y = int((W - cw) * fr["anchor_x"]) // 2 * 2, int((H - ch) * fr["anchor_y"]) // 2 * 2
    ten = enc["codec"] == "hevc" and enc["bit_depth"] == 10
    vf = [f"crop={cw}:{ch}:{x}:{y}"]
    if col["lut"]:
        vf += [f"scale={ow}:{oh}:flags=lanczos:in_color_matrix=bt709", "format=gbrp10le",
               f"lut3d=file={col['lut']}:interp={col['lut_interp']}",
               "scale=out_color_matrix=bt709:out_range=tv"]
    else:
        vf.append(f"scale={ow}:{oh}:flags=lanczos")
    vf += [f"format={'p010le' if ten else 'yuv420p'}", "setsar=1", f"setpts=N/({rate})/TB", f"fps={rate}"]
    graph.append("[vc]" + ",".join(vf) + "[vout]")
    graph.append(f"[ac]loudnorm=I={aud['lufs']}:TP={aud['true_peak_db']}:LRA={aud['lra']},"
                 f"aresample=48000[aout]")

    profile = ["-profile:v", "main10" if ten else "main", "-tag:v", "hvc1"] if enc["codec"] == "hevc" \
        else ["-profile:v", "high"]
    tags = ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"] if col["lut"] else []
    cmd = [*inputs, "-filter_complex", ";".join(graph), "-map", "[vout]", "-map", "[aout]",
           "-c:v", codec, "-b:v", enc["bitrate"], *profile, *tags,
           "-g", str(round(fps * 2)), "-fps_mode", "passthrough",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(dst)]
    return cmd, total


def render(src, dst, cuts, preset):
    """Validate, then encode in one pass. Returns the number of frames written."""
    info = vm.probe(src)
    validate(preset, cuts, info)  # raises before any encoder process exists
    with vm.atomic_output(dst) as part:
        args, frames = build_command(src, part, cuts, preset, info)
        vm.run("ffmpeg", *args)
    return frames
```

For the test clip with cuts `[[0,3],[7,10]]` this produces one input and this graph:

```
[0:v:0]split=2[sv0][sv1];[0:a:0]asplit=2[sa0][sa1];
[sv0]trim=start_frame=0:end_frame=90,setpts=PTS-STARTPTS[v0];
[sa0]atrim=start=0.000000:end=3.000000,asetpts=PTS-STARTPTS[a0];
[sv1]trim=start_frame=210:end_frame=300,setpts=PTS-STARTPTS[v1];
[sa1]atrim=start=7.000000:end=10.000000,asetpts=PTS-STARTPTS[a1];
[v0][a0][v1][a1]concat=n=2:v=1:a=1[vc][ac];
[vc]crop=720:1280:0:0,scale=720:1280:flags=lanczos,format=yuv420p,setsar=1,setpts=N/(30/1)/TB,fps=30/1[vout];
[ac]loudnorm=I=-14.0:TP=-1.5:LRA=11.0,aresample=48000[aout]
```

Rules:

- IF cuts are in chronological order THEN the source is decoded once; IF a cut starts before the previous cut ended THEN it opens a new run (one more decoder on the same file).
- IF a cut list has more than 8 runs THEN reorder it or split the job; each run holds a 4K decoder open.
- IF `encode.codec` is `h264` THEN output is 8-bit `yuv420p`, profile `high` (the delivery default for reels).
- IF `encode.codec` is `hevc` and `bit_depth` is 10 THEN output is `p010le`, profile `main10`, tagged `hvc1`; IF `hevc` and 8 THEN `yuv420p`, profile `main`, tagged `hvc1`.
- IF the source is S-Log3 THEN `color.lut` must point to a log-to-Rec.709 `.cube`; the LUT is applied after the downscale in 10-bit RGB and the output is tagged BT.709.
- IF `color.lut` is `null` THEN no RGB conversion happens and the source colour tags pass through.
- IF `framing.face_track` is true THEN the planner runs MediaPipe face detection on the kept segments, takes the median face centre, and writes it into a copy of the preset as `anchor_x` / `anchor_y` before calling `render()`. The crop is static per render.
- IF the source has no audio stream THEN a silent stereo track of the exact video length is generated.
- IF the source is variable frame rate THEN `validate()` rejects it; conform it to CFR first.
- IF tighter loudness accuracy than single-pass `loudnorm` is required THEN run a measurement pass to `-f null -` (no file written) and feed `measured_*` values into the same graph; do not add a second encode.
- IF you need to add `-ss`, `-t`, `-r`, `-vsync` or `-shortest` to the output side THEN stop; frame count and sync are owned by the filtergraph.

## 3. Preset schema and validator

`presets/preset.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "VideoMachine style preset",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "name", "cadence", "sync", "framing", "color", "audio", "encode"],
  "properties": {
    "schema_version": {"const": 1},
    "name": {"type": "string", "pattern": "^[a-z0-9-]+$"},
    "cadence": {
      "type": "object", "additionalProperties": false, "required": ["min_cut_s", "max_cut_s"],
      "properties": {
        "min_cut_s": {"type": "number", "minimum": 0.1, "maximum": 60},
        "max_cut_s": {"type": "number", "minimum": 0.1, "maximum": 600}
      }
    },
    "sync": {
      "type": "object", "additionalProperties": false, "required": ["prefer", "beat_snap_ms", "speech_pad_ms"],
      "properties": {
        "prefer": {"enum": ["beat", "speech", "none"]},
        "beat_snap_ms": {"type": "number", "minimum": 0, "maximum": 500},
        "speech_pad_ms": {"type": "number", "minimum": 0, "maximum": 1000}
      }
    },
    "framing": {
      "type": "object", "additionalProperties": false,
      "required": ["aspect", "width", "height", "anchor_x", "anchor_y", "face_track"],
      "properties": {
        "aspect": {"const": "9:16"},
        "width": {"type": "integer", "minimum": 2, "maximum": 2160},
        "height": {"type": "integer", "minimum": 2, "maximum": 3840},
        "anchor_x": {"type": "number", "minimum": 0, "maximum": 1},
        "anchor_y": {"type": "number", "minimum": 0, "maximum": 1},
        "face_track": {"type": "boolean"}
      }
    },
    "color": {
      "type": "object", "additionalProperties": false, "required": ["lut", "lut_interp"],
      "properties": {
        "lut": {"type": ["string", "null"], "pattern": "^[A-Za-z0-9_./-]+\\.cube$"},
        "lut_interp": {"enum": ["tetrahedral", "trilinear"]}
      }
    },
    "audio": {
      "type": "object", "additionalProperties": false, "required": ["lufs", "true_peak_db", "lra"],
      "properties": {
        "lufs": {"type": "number", "minimum": -30, "maximum": -5},
        "true_peak_db": {"type": "number", "minimum": -9, "maximum": 0},
        "lra": {"type": "number", "minimum": 1, "maximum": 20}
      }
    },
    "encode": {
      "type": "object", "additionalProperties": false, "required": ["codec", "bit_depth", "bitrate"],
      "properties": {
        "codec": {"enum": ["h264", "hevc"]},
        "bit_depth": {"enum": [8, 10]},
        "bitrate": {"type": "string", "pattern": "^[1-9][0-9]*[kM]$"}
      }
    }
  }
}
```

Example, `presets/automotive-roadster-outlier-2026-10-31.json` (values are placeholders to be replaced by the trend-extraction output):

```json
{
  "schema_version": 1,
  "name": "automotive-roadster-outlier-2026-10-31",
  "cadence": {"min_cut_s": 0.4, "max_cut_s": 3.0},
  "sync": {"prefer": "beat", "beat_snap_ms": 80, "speech_pad_ms": 120},
  "framing": {"aspect": "9:16", "width": 1080, "height": 1920, "anchor_x": 0.5, "anchor_y": 0.5, "face_track": false},
  "color": {"lut": null, "lut_interp": "tetrahedral"},
  "audio": {"lufs": -14.0, "true_peak_db": -1.5, "lra": 11.0},
  "encode": {"codec": "h264", "bit_depth": 8, "bitrate": "12M"}
}
```

`videomachine_preset.py` (standard library only; the JSON Schema file is the documentation, this is the gate):

```python
"""videomachine_preset.py - reject bad presets and bad cut lists before ffmpeg starts."""
import re
from pathlib import Path

import videomachine_core as vm

NUM = (int, float)
SECTIONS = {"schema_version", "name", "cadence", "sync", "framing", "color", "audio", "encode"}
RANGES = {  # (section, key): (type, min, max)
    ("cadence", "min_cut_s"): (NUM, 0.1, 60), ("cadence", "max_cut_s"): (NUM, 0.1, 600),
    ("sync", "beat_snap_ms"): (NUM, 0, 500), ("sync", "speech_pad_ms"): (NUM, 0, 1000),
    ("framing", "width"): (int, 2, 2160), ("framing", "height"): (int, 2, 3840),
    ("framing", "anchor_x"): (NUM, 0, 1), ("framing", "anchor_y"): (NUM, 0, 1),
    ("audio", "lufs"): (NUM, -30, -5), ("audio", "true_peak_db"): (NUM, -9, 0), ("audio", "lra"): (NUM, 1, 20),
}
ENUMS = {
    ("sync", "prefer"): ("beat", "speech", "none"), ("framing", "aspect"): ("9:16",),
    ("framing", "face_track"): (True, False), ("color", "lut_interp"): ("tetrahedral", "trilinear"),
    ("encode", "codec"): ("h264", "hevc"), ("encode", "bit_depth"): (8, 10),
}


class PresetError(ValueError):
    pass


def validate(preset, cuts, info):
    """Raise PresetError listing every problem found. info is vm.probe(source)."""
    get = lambda s, k: (preset.get(s) or {}).get(k)
    err = [f"unknown key {k!r}" for k in sorted(set(preset) - SECTIONS)]
    if preset.get("schema_version") != 1:
        err.append("schema_version: must be 1")
    for (s, k), (typ, lo, hi) in RANGES.items():
        v = get(s, k)
        if isinstance(v, bool) or not isinstance(v, typ) or not lo <= v <= hi:
            err.append(f"{s}.{k}={v!r}: need a number in [{lo}, {hi}]")
    err += [f"{s}.{k}={get(s, k)!r}: need one of {ok}" for (s, k), ok in ENUMS.items() if get(s, k) not in ok]
    lut = get("color", "lut")
    if lut is not None and not (re.fullmatch(r"[A-Za-z0-9_./-]+\.cube", str(lut)) and Path(lut).is_file()):
        err.append(f"color.lut={lut!r}: need an existing .cube path using only [A-Za-z0-9_./-]")
    if not re.fullmatch(r"[1-9][0-9]*[kM]", str(get("encode", "bitrate"))):
        err.append("encode.bitrate: need a string such as '12M'")
    if not err:
        w, h, fps = get("framing", "width"), get("framing", "height"), info["fps"]
        lo, hi = get("cadence", "min_cut_s"), get("cadence", "max_cut_s")
        if w * 16 != h * 9 or w % 2 or h % 2:
            err.append(f"framing {w}x{h}: must be even and exactly 9:16")
        if lo > hi or (get("encode", "codec"), get("encode", "bit_depth")) == ("h264", 10):
            err.append("cadence min_cut_s > max_cut_s, or 10-bit requested with h264 (use hevc)")
        if not info["cfr"] or not cuts:
            err.append("source is variable frame rate, or the cut list is empty")
        for i, (s, e) in enumerate(cuts):
            a, b = vm.to_frame(max(s, 0), fps), vm.to_frame(max(e, 0), fps)
            if s < 0 or b > info["frames"]:
                err.append(f"cut[{i}] {s}-{e}s: outside the source (0..{info['frames']} frames)")
            if b <= a:
                err.append(f"cut[{i}] {s}-{e}s: zero-length or reversed")
            elif not lo <= (b - a) / fps <= hi:
                err.append(f"cut[{i}] {s}-{e}s: {float((b - a) / fps):.3f}s is outside cadence [{lo}, {hi}]")
    if err:
        raise PresetError("\n".join(err))
```

Rules:

- IF `validate()` raises THEN no `ffmpeg` process is started and no output path is touched.
- IF a cut rounds to zero frames at the source frame rate (for example 3.000 to 3.010 s at 30 fps) THEN it is a zero-length cut, even though `end > start`.
- IF a cut's end frame exceeds the source frame count, or its start is negative, THEN reject; cuts are never clamped silently.
- IF a cut is shorter than `cadence.min_cut_s` or longer than `cadence.max_cut_s` THEN reject; the planner must fix the cut list, not the renderer.
- IF `sync.prefer` is `beat` THEN the planner moves a cut point to the nearest beat when it is within `beat_snap_ms`; IF `speech` THEN cut points are pushed `speech_pad_ms` outside the nearest whisper segment boundary; IF `none` THEN cut points are only frame-snapped.
- IF a preset has a key the schema does not list THEN reject (catches typos such as `min_cut`).
- IF `framing.width * 16 != framing.height * 9` THEN reject; valid sizes are 720x1280, 1080x1920, 2160x3840.
- IF a LUT path contains anything outside `[A-Za-z0-9_./-]` THEN reject; this is what keeps the filtergraph free of escaping.

## 4. Smoke test (`verify_pipeline.py`)

Three renders of the test clip, split at 3.0 s and 7.0 s:

| Case | Cut list | Expected frames | Exercises |
|---|---|---|---|
| `keep_all` | `[0,3] [3,7] [7,10]` | 300 | adjacent segments, 3-way split |
| `drop_middle` | `[0,3] [7,10]` | 180 | a gap inside one decoder run |
| `reordered` | `[7,10] [0,3]` | 180 | two decoder runs, half-frame seek |

```python
#!/usr/bin/env python3
"""verify_pipeline.py - deterministic smoke test against raw/test_clip.mp4. Exit code 0 == healthy."""
import os
import shutil
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SANDBOX = Path(tempfile.mkdtemp(prefix="vmverify_"))
os.environ["VM_TMP"] = str(SANDBOX / "tmp")  # all pipeline temp dirs land here
sys.path.insert(0, str(ROOT))

import videomachine_core as vm  # noqa: E402
from videomachine_preset import PresetError  # noqa: E402
from videomachine_render import VCODECS, render  # noqa: E402

CLIP = ROOT / "raw" / "test_clip.mp4"
FPS, FRAMES, SIZE = Fraction(30), 300, (720, 1280)
ONE_FRAME = 1 / FPS
PRESET = {
    "schema_version": 1, "name": "smoke-test",
    "cadence": {"min_cut_s": 0.2, "max_cut_s": 10.0},
    "sync": {"prefer": "none", "beat_snap_ms": 0, "speech_pad_ms": 0},
    "framing": {"aspect": "9:16", "width": 720, "height": 1280, "anchor_x": 0.5, "anchor_y": 0.5,
                "face_track": False},
    "color": {"lut": None, "lut_interp": "tetrahedral"},
    "audio": {"lufs": -14.0, "true_peak_db": -1.5, "lra": 11.0},
    "encode": {"codec": "h264", "bit_depth": 8, "bitrate": "4M"},
}
CASES = {
    "keep_all": ([(0.0, 3.0), (3.0, 7.0), (7.0, 10.0)], 300),
    "drop_middle": ([(0.0, 3.0), (7.0, 10.0)], 180),
    "reordered": ([(7.0, 10.0), (0.0, 3.0)], 180),
}
BAD = {"zero_length": [(3.0, 3.0)], "out_of_bounds": [(7.0, 10.5)]}


def check(ok, msg):
    if not ok:
        raise AssertionError(msg)


def make_clip():
    """Only used when raw/test_clip.mp4 is absent: colour bars + 440 Hz tone, 10 s, 720x1280, 30 fps."""
    CLIP.parent.mkdir(parents=True, exist_ok=True)
    vm.run("ffmpeg", "-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=30:duration=10",
           "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=10",
           "-c:v", os.environ.get("VM_VCODEC") or VCODECS["h264"], "-b:v", "4M", "-pix_fmt", "yuv420p",
           "-c:a", "aac", CLIP)


def main():
    out = SANDBOX / "out"
    if not CLIP.exists():
        make_clip()
    src = vm.probe(CLIP)
    check((src["width"], src["height"], src["fps"], src["frames"]) == (*SIZE, FPS, FRAMES),
          f"test clip is not 720x1280 / 30 fps / 300 frames: {src}")

    for name, cuts in BAD.items():  # the validator must stop these before ffmpeg runs
        try:
            render(CLIP, out / f"{name}.mp4", cuts, PRESET)
        except PresetError:
            pass
        else:
            raise AssertionError(f"{name}: validator accepted a bad cut list")
        check(not (out / f"{name}.mp4").exists(), f"{name}: output written despite invalid cuts")

    for name, (cuts, want) in CASES.items():
        dst = out / f"{name}.mp4"
        planned = render(CLIP, dst, cuts, PRESET)  # returns only if ffmpeg exited 0
        got, info, dur = vm.count_frames(dst), vm.probe(dst), want / FPS
        check(planned == want and got == want, f"{name}: frames planned={planned} decoded={got} want={want}")
        check((info["width"], info["height"], info["fps"]) == (*SIZE, FPS), f"{name}: wrong geometry {info}")
        check(info["has_audio"], f"{name}: no audio stream")
        check(abs(info["duration"] - dur) < ONE_FRAME / 2, f"{name}: video is {float(info['duration'])}s")
        check(abs(info["a_start"] - info["v_start"]) < ONE_FRAME, f"{name}: A/V start offset >= 1 frame")
        check(abs(info["a_duration"] - dur) < ONE_FRAME, f"{name}: audio is {float(info['a_duration'])}s, "
              f"video is {float(dur)}s")
        print(f"PASS {name}: {got} frames, audio within one frame")

    with vm.workdir() as d:  # temp lifecycle: normal exit
        vm.extract_wav(CLIP, d / "a.wav")
    try:  # temp lifecycle: exit by exception
        with vm.workdir() as d:
            (d / "x").write_text("x")
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    stray = vm.leftovers() + sorted(out.glob(".vm_*"))
    check(not stray, f"leftover temp files: {stray}")
    print("PASS no leftover temp files")


if __name__ == "__main__":
    try:
        main()
        code = 0
    except (AssertionError, PresetError, vm.ToolError) as e:
        print(f"FAIL {e}", file=sys.stderr)
        code = 1
    finally:
        shutil.rmtree(SANDBOX, ignore_errors=True)
    sys.exit(code)
```

Rules:

- IF `python3 verify_pipeline.py` exits non-zero THEN no change to the four files may be merged.
- IF `raw/test_clip.mp4` is missing THEN the script generates an equivalent clip; IF it exists but is not 720x1280 / 30 fps / 300 frames THEN the test fails rather than adapting.
- IF the decoded frame count differs from the planned count by even one frame THEN fail; there is no tolerance on frames.
- IF audio start or audio length differs from video by one frame (33.3 ms) or more THEN fail. AAC pads the last packet by up to 21.3 ms, which is why this bound is not zero.
- IF the test runs on a machine without VideoToolbox THEN set `VM_VCODEC=libx264`; that run checks the filtergraph and frame math only and does not replace the run on the Mac.
- "Deterministic" here means frame count, geometry and durations. VideoToolbox output is not bit-identical between runs, so the test never compares hashes.
- This test checks stream timing, not picture-to-sound alignment inside the content. A flash-and-beep marker clip would be needed for that.

## 5. First things to check on the Mac

Unverified points, in the order they are most likely to bite:

1. **Half-frame seek plus frame-index trim.** `reordered` is the case that proves it. If it yields 179 or 181 frames, the seek is not landing on the intended first frame.
2. **`-hwaccel videotoolbox` with FX3 footage.** HEVC 4:2:2 10-bit (XAVC HS) should decode in hardware on Apple Silicon; H.264 4:2:2 10-bit (XAVC S-I) should fall back to software automatically. Confirm on one real clip of each.
3. **LUT colour path.** The `in_color_matrix` / `out_color_matrix` settings assume BT.709-matrix S-Log3 footage and a full-to-Rec.709 LUT. Check one graded frame against the same LUT in Resolve or Catalyst before trusting it.
4. **`whisper-cli` JSON shape.** `transcribe()` reads `transcription[].offsets.from/to` in milliseconds, as written by `-oj`. Confirm against the installed whisper.cpp build.
5. **`loudnorm` on very short reels.** Under about 3 s of audio, single-pass measurement is unreliable; the smoke test's shortest case is 6 s.
6. **ffmpeg version.** `-fps_mode` needs ffmpeg 5.1 or newer.
