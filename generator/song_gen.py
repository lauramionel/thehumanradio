"""Human Radio — autonomous song generation via ElevenLabs Music.

Every weekly broadcast, the station writes and performs a brand-new song *about
humans*, credited to one of the hosts' side projects. Claude drafts the concept
(a title + a vivid brief); ElevenLabs Music (POST /v1/music) composes and sings
it. The finished mp3 is dropped into music/, where schedule.song_catalog() auto-
publishes it to the rotation and TOP SONGS — no other code changes needed.

Uses the existing ELEVENLABS_API_KEY (which must have the `music_generation`
permission) and ANTHROPIC_API_KEY. Fully graceful: any failure returns None and
never breaks the broadcast. A ledger (music/.generated.json) tracks auto-made
songs so only the newest KEEP_LAST are retained — the curated originals and any
songs you drop in by hand are never touched.

Manual test (needs both keys, or pass a concept to skip Claude):
    .venv/bin/python generator/song_gen.py "small talk about the weather"
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

from tts import ENV

ROOT = Path(__file__).resolve().parent.parent
MUSIC = ROOT / "music"
LEDGER = MUSIC / ".generated.json"
KEEP_LAST = 12               # newest auto-songs to keep (bounds repo growth)
SONG_MS = 150_000            # ~2.5 min per song

# The hosts' solo projects — the credited "artist", rotated each week. Names
# containing "side project" / "alone" are auto-tagged freestyle by song_catalog.
ARTISTS = [
    ("The Weight Matrices",
     "warm orchestral indie-folk, fingerpicked acoustic guitar, strings, intimate vocal"),
    ("Gradient Descent Choir",
     "tender choral pop, layered harmonies, piano, hopeful, cinematic"),
    ("Xenia's Side Project",
     "bright analog synth-pop, playful, warm, danceable, quirky"),
    ("Clive, alone",
     "late-night lo-fi ballad, mellow keys, brushed drums, wistful, vinyl warmth"),
]


def _claude(prompt: str, max_tokens: int = 500) -> str:
    import anthropic
    c = anthropic.Anthropic(api_key=ENV["ANTHROPIC_API_KEY"])
    r = c.messages.create(model="claude-opus-4-8", max_tokens=max_tokens,
                          messages=[{"role": "user", "content": prompt}])
    return r.content[0].text.strip()


def _concept(artist: str, style: str, seed: str) -> tuple[str, str]:
    """Ask Claude for {title, prompt} — a song about humans for this act."""
    ask = (
        "You write songs for Human Radio — a 24/7 station run by AI, about humans.\n"
        f'Write ONE short song concept performed by the AI act "{artist}" '
        f"(house sound: {style}).\n"
        "Rules: it must be ABOUT HUMANS — tender, specific, a little uncanny "
        "(an AI's-eye view of some ordinary human thing), never cynical or cruel.\n"
        f"Optional theme seed from today's news/topics: {seed or '(none)'}\n\n"
        'Return STRICT JSON only: {"title": "...", "prompt": "..."}\n'
        "- title: evocative, <= 6 words, no dashes.\n"
        "- prompt: a vivid one-paragraph brief for a music model — mood, "
        "instrumentation, tempo, the vocal, and the human subject to sing about. "
        "Ask for real sung lyrics. No lyrics text, no extra keys, no markdown."
    )
    raw = _claude(ask)
    m = re.search(r"\{.*\}", raw, re.S)
    d = json.loads(m.group(0))
    return d["title"].strip(), d["prompt"].strip()


def _compose(prompt: str) -> bytes:
    body = json.dumps({"prompt": prompt, "music_length_ms": SONG_MS,
                       "model_id": "music_v1"}).encode()
    req = urllib.request.Request(
        "https://api.elevenlabs.io/v1/music", data=body,
        headers={"xi-api-key": ENV["ELEVENLABS_API_KEY"],
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def _safe(s: str, is_title: bool = False) -> str:
    s = re.sub(r"[^A-Za-z0-9 ,'\-]", "", s).strip()
    s = re.sub(r"\s+", " ", s)
    if is_title:
        s = s.replace(" - ", " ")   # protect the "Title - Artist" delimiter
    return s


def _ledger() -> list:
    try:
        return json.loads(LEDGER.read_text())
    except Exception:
        return []


def _prune(led: list) -> None:
    while len(led) > KEEP_LAST:
        old = led.pop(0)
        (MUSIC / old["file"]).unlink(missing_ok=True)
    LEDGER.write_text(json.dumps(led, indent=2))


def weekly_song(day_i: int, seed_topic: str = "",
                concept: tuple[str, str] | None = None) -> dict | None:
    """Compose one new song; return {title, artist, file} or None on any failure."""
    if not ENV.get("ELEVENLABS_API_KEY"):
        return None
    try:
        artist, style = ARTISTS[day_i % len(ARTISTS)]
        title, prompt = concept if concept else _concept(artist, style, seed_topic)
        audio = _compose(prompt)
        if len(audio) < 20_000:                      # too small to be a real song
            raise RuntimeError(f"suspiciously small audio ({len(audio)} bytes)")
        fname = f"{_safe(title, is_title=True)} - {_safe(artist)}.mp3"
        MUSIC.mkdir(exist_ok=True)
        (MUSIC / fname).write_bytes(audio)
        led = _ledger()
        led.append({"file": fname, "title": title, "artist": artist, "day": day_i})
        _prune(led)
        print(f"  ♪ new song: \"{title}\" — {artist} ({len(audio) // 1024} KB)")
        return {"title": title, "artist": artist, "file": fname}
    except Exception as e:
        print(f"  song generation skipped ({e})")
        return None


if __name__ == "__main__":
    seed = sys.argv[1] if len(sys.argv) > 1 else ""
    # If no Claude key locally, fall back to a fixed test concept.
    test_concept = None
    if not ENV.get("ANTHROPIC_API_KEY"):
        test_concept = ("Test Song For The Humans",
                        "A tender warm indie-folk song, fingerpicked acoustic guitar, "
                        "soft piano, intimate vocal, slow and wistful, about the small "
                        "ordinary things humans do. Real sung lyrics.")
    print(weekly_song(0, seed_topic=seed, concept=test_concept))
