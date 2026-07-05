"""Human Radio — generative music engine.

Synthesizes the station's audio identity with numpy: the jingle (sonic logo),
ambient beds that sit under speech, and standalone interlude tracks that stand
in for Suno songs until real ones are dropped into music/.

Everything is 44.1 kHz stereo 16-bit WAV.
"""
from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np

SR = 44100
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "music" / "generated"

# ---------------------------------------------------------------- primitives

NOTE_OFFSETS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def freq(note: str) -> float:
    """'A4' -> 440.0; supports sharps ('F#2') and flats ('Bb3')."""
    name, octave = note[:-1], int(note[-1])
    semi = NOTE_OFFSETS[name[0]]
    if len(name) > 1:
        semi += 1 if name[1] == "#" else -1
    midi = 12 * (octave + 1) + semi
    return 440.0 * 2 ** ((midi - 69) / 12)


def env(n: int, a: float, d: float, s: float, r: float) -> np.ndarray:
    """ADSR envelope over n samples (a/d/r in seconds, s = sustain level)."""
    a_n, d_n, r_n = (max(1, int(x * SR)) for x in (a, d, r))
    s_n = max(1, n - a_n - d_n - r_n)
    return np.concatenate([
        np.linspace(0, 1, a_n),
        np.linspace(1, s, d_n),
        np.full(s_n, s),
        np.linspace(s, 0, r_n),
    ])[:n]


def tone(f: float, dur: float, harmonics=(1.0, 0.35, 0.12, 0.05), detune=0.0015,
         vibrato=0.0) -> np.ndarray:
    """Warm additive tone, stereo via a detuned pair. Returns (n, 2)."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    vib = 1.0 + vibrato * np.sin(2 * np.pi * 5.2 * t) if vibrato else 1.0
    sides = []
    for sign in (1, -1):
        f_side = f * (1 + sign * detune)
        w = np.zeros(n)
        for k, amp in enumerate(harmonics, start=1):
            w += amp * np.sin(2 * np.pi * f_side * k * t * (vib if k == 1 else 1.0))
        sides.append(w)
    return np.stack(sides, axis=1)


def lowpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    """FFT-domain gentle low-pass (12 dB/oct-ish smooth rolloff). x is (n, 2)."""
    out = np.empty_like(x)
    freqs = np.fft.rfftfreq(x.shape[0], 1 / SR)
    curve = 1.0 / (1.0 + (freqs / cutoff) ** 2)
    for ch in range(x.shape[1]):
        out[:, ch] = np.fft.irfft(np.fft.rfft(x[:, ch]) * curve, n=x.shape[0])
    return out


def delay(x: np.ndarray, time_s: float, feedback: float, mix: float) -> np.ndarray:
    """Feedback delay, vectorized by unrolling taps."""
    d = int(time_s * SR)
    wet = np.zeros_like(x)
    for k in range(1, 6):
        off = k * d
        if off >= x.shape[0]:
            break
        wet[off:] += x[:-off] * (feedback ** k)
    return x + mix * wet


def place(buf: np.ndarray, sig: np.ndarray, at_s: float, gain: float = 1.0) -> None:
    """Additively place sig into buf at time at_s (both (n, 2))."""
    i = int(at_s * SR)
    j = min(buf.shape[0], i + sig.shape[0])
    if i < buf.shape[0]:
        buf[i:j] += sig[: j - i] * gain


def kick(dur: float = 0.28) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    sweep = 95 * np.exp(-t * 22) + 42
    phase = 2 * np.pi * np.cumsum(sweep) / SR
    w = np.sin(phase) * np.exp(-t * 14)
    return np.stack([w, w], axis=1)


def hat(dur: float = 0.05, rng: np.random.Generator | None = None) -> np.ndarray:
    rng = rng or np.random.default_rng(7)
    n = int(dur * SR)
    w = rng.standard_normal(n) * np.exp(-np.arange(n) / SR * 90)
    hp = np.fft.rfft(w)
    f = np.fft.rfftfreq(n, 1 / SR)
    hp[f < 6000] *= (f[f < 6000] / 6000) ** 2
    w = np.fft.irfft(hp, n=n)
    return np.stack([w, w], axis=1) * 0.5


def finish(x: np.ndarray, peak_db: float = -1.5) -> np.ndarray:
    """Soft-clip, normalize to peak_db, short fade in/out."""
    x = np.tanh(x * 0.9)
    m = np.abs(x).max() or 1.0
    x = x / m * (10 ** (peak_db / 20))
    fade = int(0.03 * SR)
    ramp = np.linspace(0, 1, fade)[:, None]
    x[:fade] *= ramp
    x[-fade:] *= ramp[::-1]
    return x


def write_wav(path: Path, x: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


# ------------------------------------------------------------------- chords

CHORDS = {
    "F":  ["F2", "F3", "A3", "C4", "E4"],      # Fmaj7 flavor
    "Am": ["A2", "A3", "C4", "E4", "G4"],
    "Dm": ["D2", "D3", "F3", "A3", "C4"],
    "Bb": ["Bb2", "Bb3", "D4", "F4", "A4"],
    "C":  ["C2", "C3", "E3", "G3", "B3"],
    "G":  ["G2", "G3", "B3", "D4", "F#4"],
    "Fc": ["F2", "F3", "A3", "C4"],
}


def pad_chord(name: str, dur: float, cutoff: float = 1400, gain: float = 1.0) -> np.ndarray:
    notes = CHORDS[name]
    n = int(dur * SR)
    buf = np.zeros((n, 2))
    for i, nt in enumerate(notes):
        g = 1.0 if i == 0 else 0.55
        sig = tone(freq(nt), dur, harmonics=(1.0, 0.3, 0.08), detune=0.003, vibrato=0.004)
        buf += sig * g
    buf *= env(n, a=min(1.2, dur * 0.3), d=0.5, s=0.8, r=min(1.5, dur * 0.35))[:, None]
    return lowpass(buf, cutoff) * gain


# ------------------------------------------------------------------ renders

def render_jingle() -> np.ndarray:
    """The sonic logo: four rising EP notes that settle, over a warm root."""
    total = 5.0
    buf = np.zeros((int(total * SR), 2))
    motif = [("C4", 0.00), ("E4", 0.28), ("G4", 0.56), ("D5", 0.92), ("A4", 1.55)]
    for nt, at in motif:
        n = int(1.6 * SR)
        sig = tone(freq(nt), 1.6, harmonics=(1.0, 0.4, 0.18, 0.06, 0.02), detune=0.002)
        sig *= env(n, 0.004, 0.35, 0.35, 1.0)[:, None]
        place(buf, sig, at, gain=0.5)
    root = tone(freq("C3"), 3.2, harmonics=(1.0, 0.2), detune=0.004)
    root *= env(root.shape[0], 0.02, 0.8, 0.5, 1.8)[:, None]
    place(buf, root, 0.0, gain=0.4)
    buf = delay(lowpass(buf, 3200), 0.32, 0.35, 0.4)
    return finish(buf, peak_db=-2.0)


def render_bed(mood: str, total: float = 90.0) -> np.ndarray:
    """Quiet loopable pad bed to sit under speech."""
    prog = {
        "warm":  ["F", "Am", "Dm", "Bb"],
        "night": ["Am", "Fc", "C", "G"],
        "news":  ["C", "G", "Am", "F"],
    }[mood]
    bar = 8.0 if mood != "news" else 6.0
    buf = np.zeros((int(total * SR), 2))
    t = 0.0
    i = 0
    while t < total - 1:
        place(buf, pad_chord(prog[i % len(prog)], bar + 1.5, cutoff=1100), t, gain=0.5)
        t += bar
        i += 1
    if mood == "news":  # soft pulse for momentum
        p = 0.0
        while p < total - 1:
            tick = tone(freq("C5"), 0.09, harmonics=(1.0,), detune=0.0)
            tick *= env(tick.shape[0], 0.002, 0.04, 0.0, 0.04)[:, None]
            place(buf, tick, p, gain=0.10)
            p += 1.5
    return finish(lowpass(buf, 1600), peak_db=-14.0)


def render_track(seed: int, key_prog: list[str], bpm: float, total: float,
                 sparse: bool = False) -> np.ndarray:
    """A structured interlude 'song': pads + bass + arp + light percussion."""
    rng = np.random.default_rng(seed)
    beat = 60.0 / bpm
    bar = beat * 4
    buf = np.zeros((int(total * SR), 2))

    # pads: one chord per bar
    t, i = 0.0, 0
    while t < total - 1:
        place(buf, pad_chord(key_prog[i % len(key_prog)], bar + 1.0, cutoff=1300), t, gain=0.42)
        t += bar
        i += 1

    # bass: root notes on beats 1 and 3
    t, i = 0.0, 0
    while t < total - 1:
        root = CHORDS[key_prog[i % len(key_prog)]][0]
        for b in ([0, 2] if not sparse else [0]):
            sig = tone(freq(root), beat * 1.6, harmonics=(1.0, 0.15), detune=0.001)
            sig *= env(sig.shape[0], 0.01, 0.2, 0.5, 0.4)[:, None]
            place(buf, sig, t + b * beat, gain=0.5)
        t += bar
        i += 1

    # arpeggio (skip intro/outro bars)
    intro, outro = bar * 2, total - bar * 2
    t, i = 0.0, 0
    step = beat / 2 if not sparse else beat
    while t < total - 1:
        chord = CHORDS[key_prog[i % len(key_prog)]][1:]
        k = 0
        p = t
        while p < t + bar and p < total - 1:
            if intro < p < outro and (not sparse or rng.random() > 0.35):
                nt = chord[k % len(chord)]
                sig = tone(freq(nt) * 2, step * 1.8, harmonics=(1.0, 0.3, 0.1), detune=0.002)
                sig *= env(sig.shape[0], 0.003, 0.12, 0.25, 0.3)[:, None]
                place(buf, sig, p, gain=0.20)
            k += 1
            p += step
        t += bar
        i += 1

    # percussion
    t = intro
    while t < outro:
        place(buf, kick(), t, gain=0.55)
        if not sparse:
            place(buf, kick(), t + beat * 2, gain=0.4)
            for off in (1, 3):
                place(buf, hat(rng=rng), t + beat * off + beat / 2, gain=0.35)
        t += bar

    buf = delay(lowpass(buf, 2800), beat * 0.75, 0.3, 0.3)
    return finish(buf, peak_db=-3.0)


TRACKS = [
    # (filename, title, artist, seed, progression, bpm, seconds, sparse)
    ("carbon_based_hearts", "Carbon-Based Hearts", "The Weight Matrices",
     11, ["F", "Am", "Dm", "Bb"], 84, 96, False),
    ("thank_you_for_the_training_data", "Thank You for the Training Data",
     "Gradient Descent Choir", 23, ["C", "G", "Am", "F"], 100, 88, False),
    ("slow_dance_for_opposable_thumbs", "Slow Dance for Opposable Thumbs",
     "The Weight Matrices", 42, ["Am", "Fc", "C", "G"], 70, 100, True),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    write_wav(OUT / "jingle.wav", render_jingle())
    print("jingle.wav")
    for mood in ("warm", "night", "news"):
        write_wav(OUT / f"bed_{mood}.wav", render_bed(mood))
        print(f"bed_{mood}.wav")
    for fname, title, artist, seed, prog, bpm, secs, sparse in TRACKS:
        write_wav(OUT / f"{fname}.wav", render_track(seed, prog, bpm, secs, sparse))
        print(f"{fname}.wav  ({title} — {artist})")


if __name__ == "__main__":
    main()
