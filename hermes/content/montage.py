#!/usr/bin/env python3
"""
montage.py — assemble des images + une chanson en une vidéo (comptine), avec ffmpeg.

Gratuit, tourne sur le serveur (CPU). Chaque image est montrée à tour de rôle
pendant toute la durée de la chanson, avec un léger zoom « Ken Burns ». Sortie
1920x1080 (H.264 + AAC), prête pour YouTube.

Prérequis : ffmpeg + ffprobe installés (sudo apt-get install -y ffmpeg).

Exemples :
  python3 montage.py --images a.png,b.png,c.png --audio chanson.mp3 --out video.mp4
  python3 montage.py --images-dir ./scenes --audio chanson.mp3 --out video.mp4
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys

W, H, FPS = 1920, 1080, 25


def run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    except FileNotFoundError:
        sys.exit(f"Outil manquant : {cmd[0]}. Installe-le (sudo apt-get install -y ffmpeg).")
    except subprocess.CalledProcessError as exc:
        sys.exit(f"{cmd[0]} a échoué :\n{exc.stderr[-2000:]}")


def audio_duration(path: str) -> float:
    out = run(["ffprobe", "-v", "quiet", "-print_format", "json",
               "-show_format", path])
    try:
        return float(json.loads(out)["format"]["duration"])
    except (ValueError, KeyError):
        sys.exit("Impossible de lire la durée de l'audio.")


def collect_images(args) -> list[str]:
    images: list[str] = []
    if args.images:
        images = [p.strip() for p in args.images.split(",") if p.strip()]
    elif args.images_dir:
        for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
            images += glob.glob(os.path.join(args.images_dir, ext))
        images.sort()
    for p in images:
        if not os.path.isfile(p):
            sys.exit(f"Image introuvable : {p}")
    if not images:
        sys.exit("Aucune image fournie (--images a.png,b.png ou --images-dir ./dossier).")
    return images


def build(images: list[str], audio: str, out: str) -> None:
    total = audio_duration(audio)
    per = max(1.0, total / len(images))
    frames = int(round(per * FPS))

    cmd: list[str] = ["ffmpeg", "-y"]
    for img in images:
        cmd += ["-loop", "1", "-t", f"{per:.3f}", "-i", img]
    cmd += ["-i", audio]  # dernière entrée = l'audio

    # Un léger zoom progressif par image, cadré en 1920x1080, puis concaténation.
    parts = []
    for i in range(len(images)):
        parts.append(
            f"[{i}:v]scale={W*2}:{H*2}:force_original_aspect_ratio=increase,"
            f"crop={W*2}:{H*2},"
            f"zoompan=z='min(zoom+0.0010,1.30)':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':fps={FPS}:s={W}x{H},"
            f"setsar=1[v{i}]"
        )
    concat_inputs = "".join(f"[v{i}]" for i in range(len(images)))
    filtergraph = ";".join(parts) + f";{concat_inputs}concat=n={len(images)}:v=1:a=0[v]"

    audio_idx = len(images)
    cmd += [
        "-filter_complex", filtergraph,
        "-map", "[v]", "-map", f"{audio_idx}:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart",
        out,
    ]
    run(cmd)
    print(f"✓ Vidéo montée : {out}  ({len(images)} images, {total:.1f}s)")


def main() -> None:
    p = argparse.ArgumentParser(description="Assembler images + chanson en une vidéo (ffmpeg).")
    p.add_argument("--images", help="liste d'images séparées par des virgules")
    p.add_argument("--images-dir", help="dossier d'images (png/jpg/webp, triées par nom)")
    p.add_argument("--audio", required=True, help="fichier audio (mp3/wav/m4a)")
    p.add_argument("--out", required=True, help="fichier vidéo de sortie (.mp4)")
    args = p.parse_args()

    if not os.path.isfile(args.audio):
        sys.exit(f"Audio introuvable : {args.audio}")
    images = collect_images(args)
    build(images, args.audio, args.out)


if __name__ == "__main__":
    main()
