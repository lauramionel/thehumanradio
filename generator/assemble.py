"""Human Radio — block assembler.

Reads scripts/block_XXX.json, renders every line through tts.speak(), mixes
music beds under speech, stitches jingle + segments + songs into one MP3, and
writes a manifest.json with timings the website uses for now-playing and the
live transcript.

Usage: .venv/bin/python generator/assemble.py [block_001]
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

from music import SR, write_wav
from tts import speak

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / "music" / "generated"
USER_MUSIC = ROOT / "music"
OUT = ROOT / "output"
PARTS = OUT / "parts"

SPEECH_RMS = 0.07          # target speech level (~ -23 dBFS RMS)
BED_RATIO = 0.20           # bed RMS relative to speech RMS
SONG_RMS = 0.075           # songs sit just about speech level, never above it
GAP_DEFAULT = 0.35         # default pause between lines (s)
GAP_PART = 0.5             # gap between block parts (s)
GAP_JINGLE = 0.15          # jingle has its own fade tail — keep it tight
GAP_SONG = 0.9             # extra breathing room around songs (s)


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == SR and w.getnchannels() == 2, path
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    return (data.reshape(-1, 2) / 32768.0).astype(np.float32)


def decode(path: Path) -> np.ndarray:
    """Decode any audio file to 44.1k stereo float32 via ffmpeg."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        tmp = Path(tf.name)
    try:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(path),
                        "-ar", str(SR), "-ac", "2", str(tmp)], check=True)
        return read_wav(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def trim_edges(x: np.ndarray, thresh: float = 0.004, pad_s: float = 0.04) -> np.ndarray:
    """Cut leading/trailing silence, keep a little padding."""
    loud = np.abs(x).max(axis=1) > thresh
    idx = np.flatnonzero(loud)
    if idx.size == 0:
        return x
    pad = int(pad_s * SR)
    a = max(0, idx[0] - pad)
    b = min(x.shape[0], idx[-1] + pad)
    return x[a:b]


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)))) or 1e-9


def silence(dur: float) -> np.ndarray:
    return np.zeros((int(dur * SR), 2), dtype=np.float32)


def build_segment(seg: dict) -> tuple[np.ndarray, list[dict]]:
    """Render one talk segment. Returns (audio, line timings rel. to start)."""
    chunks: list[np.ndarray] = [silence(0.25)]
    timings: list[dict] = []
    t = 0.25
    for line in seg["lines"]:
        audio = trim_edges(read_wav(speak(line["text"], line["speaker"])))
        audio = audio * (SPEECH_RMS / rms(audio))
        timings.append({"t": round(t, 2), "speaker": line["speaker"],
                        "text": line["text"]})
        chunks.append(audio)
        t += audio.shape[0] / SR
        gap = float(line.get("pause_after", GAP_DEFAULT))
        chunks.append(silence(gap))
        t += gap
    speech = np.concatenate(chunks)

    bed_name = seg.get("bed")
    if bed_name:
        bed = read_wav(GEN / f"bed_{bed_name}.wav")
        reps = int(np.ceil(speech.shape[0] / bed.shape[0]))
        bed = np.tile(bed, (reps, 1))[: speech.shape[0]]
        bed = bed * (SPEECH_RMS * BED_RATIO / rms(bed))
        fade = int(1.2 * SR)
        ramp = np.linspace(0, 1, fade, dtype=np.float32)[:, None]
        bed[:fade] *= ramp
        bed[-fade:] *= ramp[::-1]
        speech = speech + bed
    return speech, timings


def load_song(item: dict) -> np.ndarray:
    """Prefer an exact music/<file>.mp3, then a title match, then a generated fallback."""
    exact = USER_MUSIC / f"{item['file']}.mp3"
    candidates = [exact] if exact.exists() else []
    candidates += [f for f in USER_MUSIC.glob("*.mp3")
                   if item["title"].lower() in f.stem.lower()]
    if candidates:
        song = decode(candidates[0])
        limit = int(150 * SR)
        if song.shape[0] > limit:  # cap at 2:30 with a fade
            song = song[:limit]
            fade = int(2.0 * SR)
            song[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)[:, None]
        return song
    return read_wav(GEN / f"{item['file']}.wav")


def assemble(block_name: str) -> None:
    block = json.loads((ROOT / "scripts" / f"{block_name}.json").read_text())
    PARTS.mkdir(parents=True, exist_ok=True)
    for old in PARTS.glob("*.wav"):
        old.unlink()

    manifest: list[dict] = []
    part_files: list[Path] = []
    t = 0.0

    for i, item in enumerate(block["sequence"]):
        if item["type"] == "jingle":
            audio = read_wav(GEN / "jingle.wav") * 0.9
            entry = {"type": "jingle", "label": "Station jingle"}
            gap = GAP_JINGLE
        elif item["type"] == "segment":
            seg = json.loads(
                (ROOT / "scripts" / "segments" / f"{item['script']}.json").read_text())
            audio, lines = build_segment(seg)
            entry = {"type": "talk", "label": item.get("label", seg["show"]),
                     "show": seg["show"], "lines": lines}
            gap = GAP_PART
        else:  # song
            audio = load_song(item)
            audio = audio * (SONG_RMS / rms(audio))  # match broadcast speech level
            entry = {"type": "song", "label": f"♪ {item['title']}",
                     "title": item["title"], "artist": item["artist"]}
            gap = GAP_SONG

        dur = audio.shape[0] / SR
        entry.update({"start": round(t, 2), "end": round(t + dur, 2)})
        if "lines" in entry:
            for ln in entry["lines"]:
                ln["t"] = round(ln["t"] + t, 2)
        manifest.append(entry)

        part = PARTS / f"{i:02d}_{item.get('script', item['type'])}.wav"
        write_wav(part, np.concatenate([audio, silence(gap)]))
        part_files.append(part)
        t += dur + gap

    # concat -> loudness normalize -> mp3
    concat_list = PARTS / "concat.txt"
    concat_list.write_text(
        "".join(f"file '{p.name}'\n" for p in part_files))
    mp3 = OUT / f"{block_name}.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", str(concat_list),
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
         "-codec:a", "libmp3lame", "-b:a", "192k", str(mp3)],
        check=True, cwd=PARTS)

    meta = {
        "block": block_name,
        "title": block.get("title", block_name),
        "duration": round(t, 2),
        "segments": manifest,
    }
    (OUT / f"{block_name}.manifest.json").write_text(json.dumps(meta, indent=2))
    print(f"{mp3.name}: {t/60:.1f} min, {len(manifest)} parts")


if __name__ == "__main__":
    assemble(sys.argv[1] if len(sys.argv) > 1 else "block_001")
