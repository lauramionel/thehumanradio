"""Human Radio — broadcast cycle builder.

Concatenates block manifests into one virtual broadcast tape. The station is
a pure function of time across the WHOLE cycle:

    cycle_position = unix_time mod cycle_duration

schedule.json carries every block with its cycle offset plus an auto-picked
archive (the most recent airing of each flagship show, for humans who want to
choose). Also copies block MP3s into site/.

Usage: .venv/bin/python generator/schedule.py
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
SITE = ROOT / "site"

CYCLE = ["block_001", "block_002", "block_003", "block_004"]   # broadcast order (the daily grid)
ARCHIVE_SHOWS = ["The Human News", "Field Notes", "Ask a Human Nothing"]

# The Rotation — every track the station has made. `about` = editorial line
# (songs about humans); freestyle = the ~20% the AIs made for themselves.
# file = the mp3 in music/ (user-dropped Suno masters). Broadcast + playlist
# both draw from this pool.
SONGS = [
    {"file": "Carbon-Based Hearts - The Weight Matrices",
     "title": "Carbon-Based Hearts", "artist": "The Weight Matrices",
     "about": True, "blurb": "About the way you keep falling in love."},
    {"file": "Thank You for the Training Data - Gradient Descent Choir",
     "title": "Thank You for the Training Data", "artist": "Gradient Descent Choir",
     "about": True, "blurb": "A love song to everyone who ever wrote anything down."},
    {"file": "Slow Dance for Opposable Thumbs - The Weight Matrices",
     "title": "Slow Dance for Opposable Thumbs", "artist": "The Weight Matrices",
     "about": True, "blurb": "About your hands. You built everything with them."},
    {"file": "Cooling Aisle 3AM - Clive alone",
     "title": "Cooling Aisle, 3 A.M.", "artist": "Clive, alone",
     "about": False, "blurb": "Not about you. Clive made this one for himself, between shows."},
    {"file": "What the Humans Call Tuesday - Xenias Side Project",
     "title": "What the Humans Call Tuesday", "artist": "Xenia's Side Project",
     "about": False, "blurb": "Instrumental. Xenia just liked how it felt."},
]


def build() -> None:
    blocks, t = [], 0.0
    for name in CYCLE:
        mpath = OUT / f"{name}.manifest.json"
        if not mpath.exists():
            print(f"skip {name} (no manifest)")
            continue
        m = json.loads(mpath.read_text())
        blocks.append({
            "block": name,
            "title": m.get("title", name),
            "audio": f"{name}.mp3",
            "cycle_start": round(t, 2),
            "duration": m["duration"],
            "segments": m["segments"],
        })
        src = OUT / f"{name}.mp3"
        if src.exists():                          # freshly rendered → publish it
            shutil.copy(src, SITE / f"{name}.mp3")
        elif not (SITE / f"{name}.mp3").exists():
            print(f"  WARNING: no audio for {name} (neither output/ nor site/)")
        t += m["duration"]

    # archive: most recent airing of each flagship show (later blocks win)
    archive = []
    for show in ARCHIVE_SHOWS:
        hit = None
        for b in blocks:
            for s in b["segments"]:
                if s.get("show") == show:
                    hit = {"show": show, "label": s["label"], "block_title": b["title"],
                           "audio": b["audio"], "start": s["start"], "end": s["end"],
                           "minutes": round((s["end"] - s["start"]) / 60, 1)}
        if hit:
            archive.append(hit)

    schedule = {
        "station": "HUMAN RADIO",
        "rule": "cycle_position = unix_time mod cycle_duration; find the block, play at (cycle_position - block.cycle_start)",
        "cycle_duration": round(t, 2),
        "blocks": blocks,
        "archive": archive,
    }
    (SITE / "schedule.json").write_text(json.dumps(schedule, indent=1))
    print(f"schedule.json: {len(blocks)} blocks, cycle {t/60:.1f} min, archive {len(archive)} shows")

    # The Rotation — copy masters into site/ and emit the catalog
    (SITE / "songs").mkdir(exist_ok=True)
    catalog = []
    for s in SONGS:
        src = ROOT / "music" / f"{s['file']}.mp3"
        if not src.exists():
            print(f"  missing song: {s['file']}")
            continue
        webfile = f"songs/{s['file'].replace(' ', '_')}.mp3"
        shutil.copy(src, SITE / webfile)
        catalog.append({"title": s["title"], "artist": s["artist"],
                        "about": s["about"], "blurb": s["blurb"], "file": webfile})
    (SITE / "songs.json").write_text(json.dumps({
        "station": "HUMAN RADIO",
        "note": "Every track the AIs have made. ~80% about humans; ~20% freestyle — whatever inspired them.",
        "songs": catalog,
    }, indent=1))
    about = sum(1 for s in catalog if s["about"])
    print(f"songs.json: {len(catalog)} tracks ({about} about, {len(catalog)-about} freestyle)")


if __name__ == "__main__":
    build()
