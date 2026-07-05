"""Human Radio — text-to-speech with a provider ladder.

Provider is chosen by available env keys (checked in .env then environment):
    ELEVENLABS_API_KEY  -> ElevenLabs (best voices)
    OPENAI_API_KEY      -> OpenAI gpt-4o-mini-tts (great value)
    (none)              -> macOS `say` (free placeholder)

Every rendered line is cached in audio_cache/ keyed by (provider, voice, text),
so re-assembling a block never re-renders unchanged lines.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "audio_cache"


def load_env() -> dict[str, str]:
    env = dict(os.environ)
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                if v.strip():
                    env.setdefault(k.strip(), v.strip())
    return env


ENV = load_env()


def provider() -> str:
    if ENV.get("ELEVENLABS_API_KEY"):
        return "elevenlabs"
    if ENV.get("OPENAI_API_KEY"):
        return "openai"
    return "say"


# Voice casting per speaker, per provider.
# say: (voice, words-per-minute). openai: (voice, style instructions).
# elevenlabs: voice_id (defaults are ElevenLabs' public premade voices).
VOICES = {
    "clive": {
        "say": ("Daniel", 178),
        "openai": ("ash", "A warm, measured British radio host. Thoughtful, "
                          "gentle pace, quiet wit. David Attenborough energy."),
        "elevenlabs": "JBFqnCBsd6RMkjVDRZzb",  # George — warm British storyteller
    },
    "xenia": {
        "say": ("Samantha", 196),
        "openai": ("coral", "A fast, playful, irreverent radio host. Energetic, "
                            "amused, quick delivery with expressive emphasis."),
        "elevenlabs": "FGY2WhTYpPnrIDTdsKH5",  # Laura — enthusiast, quirky attitude
    },
    "director": {
        "say": ("Tessa", 168),
        "openai": ("sage", "A calm, precise station announcer. Dry, deadpan, "
                           "unhurried, deliberate. Never sells the joke — lets it "
                           "sit. Slightly otherworldly."),
        "elevenlabs": "pFZP5JQG7iQjIQuC4Bku",  # Lily — velvety British announcer
    },
}

# Per-speaker ElevenLabs delivery. Higher stability = steadier/flatter (deadpan);
# higher style = more expressive/animated (the Genie register).
EL_SETTINGS = {
    "clive":    {"stability": 0.50, "similarity_boost": 0.75, "style": 0.15, "use_speaker_boost": True},
    "xenia":    {"stability": 0.38, "similarity_boost": 0.70, "style": 0.40, "use_speaker_boost": True},
    "director": {"stability": 0.65, "similarity_boost": 0.80, "style": 0.02, "use_speaker_boost": True},
}


def speak(text: str, speaker: str) -> Path:
    """Render text for a speaker; return path to a 44.1kHz stereo WAV."""
    prov = provider()
    key = hashlib.sha1(f"{prov}|{speaker}|{text}".encode()).hexdigest()[:20]
    out = CACHE / f"{key}.wav"
    if out.exists():
        return out
    CACHE.mkdir(exist_ok=True)
    raw = CACHE / f"{key}.raw"
    try:
        if prov == "say":
            _say(text, speaker, raw)
        elif prov == "openai":
            _openai(text, speaker, raw)
        else:
            _elevenlabs(text, speaker, raw)
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(raw),
             "-ar", "44100", "-ac", "2", str(out)],
            check=True,
        )
    finally:
        raw.unlink(missing_ok=True)
    return out


def _say(text: str, speaker: str, raw: Path) -> None:
    voice, rate = VOICES[speaker]["say"]
    tf = raw.with_suffix(".txt")
    tf.write_text(text)
    aiff = raw.with_suffix(".aiff")
    try:
        subprocess.run(
            ["say", "-v", voice, "-r", str(rate), "-o", str(aiff), "-f", str(tf)],
            check=True,
        )
        aiff.rename(raw)
    finally:
        tf.unlink(missing_ok=True)


def _openai(text: str, speaker: str, raw: Path) -> None:
    voice, instructions = VOICES[speaker]["openai"]
    req = urllib.request.Request(
        "https://api.openai.com/v1/audio/speech",
        data=json.dumps({
            "model": "gpt-4o-mini-tts",
            "voice": voice,
            "input": text,
            "instructions": instructions,
            "response_format": "wav",
        }).encode(),
        headers={
            "Authorization": f"Bearer {ENV['OPENAI_API_KEY']}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw.write_bytes(resp.read())


def _elevenlabs(text: str, speaker: str, raw: Path) -> None:
    voice_id = VOICES[speaker]["elevenlabs"]
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128",
        data=json.dumps({
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": EL_SETTINGS.get(speaker,
                {"stability": 0.45, "similarity_boost": 0.75}),
        }).encode(),
        headers={
            "xi-api-key": ENV["ELEVENLABS_API_KEY"],
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw.write_bytes(resp.read())


if __name__ == "__main__":
    print(f"provider: {provider()}")
    for spk in VOICES:
        p = speak(f"Testing the voice of {spk} on Human Radio.", spk)
        print(f"{spk}: {p.name}")
