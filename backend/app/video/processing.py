"""FFmpeg-based video processing. Commands are argument lists (no shell)."""

import json
import re
import shutil
import subprocess
from pathlib import Path


class VideoToolMissing(RuntimeError):
    pass


def _bin(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise VideoToolMissing(f"{name} is not installed; it is included in the backend Docker image")
    return path


def probe(path: Path) -> dict:
    out = subprocess.run([_bin("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                         capture_output=True, text=True, timeout=60, check=True).stdout
    data = json.loads(out)
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if v is None:
        raise ValueError("file has no video stream")
    return {
        "duration_s": float(data["format"].get("duration", 0) or 0),
        "width": v.get("width"), "height": v.get("height"), "codec": v.get("codec_name"),
        "has_audio": any(s.get("codec_type") == "audio" for s in data.get("streams", [])),
        "format": data["format"].get("format_name"),
    }


_PTS = re.compile(r"pts_time:([0-9.]+)")


def sample_frames(path: Path, out_dir: Path, scene_threshold: float = 0.25, floor_every_s: float = 8.0,
                  max_frames: int = 48) -> list[dict]:
    """Scene-change frames plus a uniform floor so static stretches are still covered."""
    out_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict] = []
    for tag, vf in (("scene", f"select='gt(scene,{scene_threshold})',showinfo"),
                    ("floor", f"fps=1/{floor_every_s},showinfo")):
        pattern = out_dir / f"{tag}_%04d.jpg"
        r = subprocess.run([_bin("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-i", str(path), "-vf", vf,
                            "-vsync", "vfr", "-q:v", "4", str(pattern)],
                           capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg frame extraction failed: {r.stderr[-500:]}")
        times = [float(t) for t in _PTS.findall(r.stderr)]
        files = sorted(out_dir.glob(f"{tag}_*.jpg"))
        for f, t in zip(files, times, strict=False):
            frames.append({"path": str(f), "t": round(t, 2), "kind": tag})
    frames.sort(key=lambda f: f["t"])
    # de-duplicate frames within 1 s, preferring scene changes
    dedup: list[dict] = []
    for f in frames:
        if dedup and f["t"] - dedup[-1]["t"] < 1.0:
            if f["kind"] == "scene":
                dedup[-1] = f
            continue
        dedup.append(f)
    if len(dedup) > max_frames:
        step = len(dedup) / max_frames
        dedup = [dedup[int(i * step)] for i in range(max_frames)]
    return dedup


def extract_audio(path: Path, out: Path) -> Path | None:
    r = subprocess.run([_bin("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-i", str(path), "-vn", "-ac", "1",
                        "-ar", "16000", "-b:a", "48k", str(out)], capture_output=True, text=True, timeout=900)
    return out if r.returncode == 0 and out.exists() else None


def segment(frames: list[dict], duration: float, transcript_segments: list[dict], max_segments: int = 16) -> list[dict]:
    """Action segments bounded by scene changes; each carries its frames and overlapping speech."""
    cuts = [0.0] + [f["t"] for f in frames if f["kind"] == "scene"] + [duration]
    cuts = sorted(set(round(c, 2) for c in cuts))
    bounds = [(a, b) for a, b in zip(cuts, cuts[1:], strict=False) if b - a >= 1.5] or [(0.0, duration)]
    while len(bounds) > max_segments:  # merge the shortest neighbouring pair
        i = min(range(len(bounds) - 1), key=lambda k: bounds[k + 1][1] - bounds[k][0])
        bounds[i:i + 2] = [(bounds[i][0], bounds[i + 1][1])]
    segs = []
    for a, b in bounds:
        fs = [f["path"] for f in frames if a <= f["t"] < b] or [min(frames, key=lambda f: abs(f["t"] - a))["path"]] if frames else []
        speech = " ".join(t["text"].strip() for t in transcript_segments if t["end"] > a and t["start"] < b)
        segs.append({"t_start": a, "t_end": b, "frames": fs, "transcript": speech})
    return segs
