# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow"]
# ///
"""Assemble build/frames (from record.py) into the looping MP4.

Cross-fades (0.6 s) are blended here with Pillow; the last item fades back into the title
card, so the file loops without a visible seam. Output: H.264, 1920x1080, 30 fps,
yuv420p, faststart (plays in QuickTime, browsers, VLC, PowerPoint).

  uv run explorer/demo_video/assemble.py [--ffmpeg /opt/homebrew/bin/ffmpeg]
"""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
FRAMES = HERE / "build" / "frames"
FADES = HERE / "build" / "fades"
OUT = HERE / "troute_lab_demo_loop.mp4"
FADE_S = 0.6


def blend(a, b, n, tag):
    A, B = Image.open(FRAMES / a).convert("RGB"), Image.open(FRAMES / b).convert("RGB")
    out = []
    for k in range(1, n + 1):
        f = FADES / f"{tag}_{k:02d}.png"
        Image.blend(A, B, k / (n + 1)).save(f)
        out.append(f)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg")
    args = ap.parse_args()
    meta = json.loads((FRAMES / "list.json").read_text())
    fps, items = meta["fps"], meta["items"]
    nf = round(FADE_S * fps)
    FADES.mkdir(parents=True, exist_ok=True)
    seq = []  # (path, seconds)
    for i, (name, dur, fade) in enumerate(items):
        if fade and i > 0:
            prev_path = Path(seq[-1][0])
            prev_name = prev_path.name if prev_path.parent == FRAMES else items[i - 1][0]
            fr = blend(prev_name, name, nf, f"x{i:05d}")
            if dur == 0:  # loop marker: borrow the fade time from the previous item
                p, d = seq[-1]
                seq[-1] = (p, max(1 / fps, d - nf / fps))
            else:
                dur = max(1 / fps, dur - nf / fps)
            seq += [(str(f), 1 / fps) for f in fr]
        if dur > 0:
            seq.append((str(FRAMES / name), dur))
    lst = HERE / "build" / "concat.txt"
    with lst.open("w") as fh:
        for p, d in seq:
            fh.write(f"file '{p}'\nduration {d:.5f}\n")
        fh.write(f"file '{seq[-1][0]}'\n")  # concat demuxer: repeat last entry
    total = sum(d for _, d in seq)
    print(f"{len(seq)} entries, {total:.1f} s")
    subprocess.run([args.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-vf", f"fps={fps},scale=1920:1080:flags=lanczos,format=yuv420p", "-t", f"{total:.3f}",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "18",
                    "-profile:v", "high", "-level", "4.1", "-r", str(fps), "-movflags", "+faststart", str(OUT)], check=True)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
