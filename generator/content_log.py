"""Human Radio — content log & transcript archive.

Turns everything the station has aired into two durable, analysable artifacts:

  site/transcripts/<block>.txt   — human-readable transcript (also SEO fuel:
                                    every word becomes indexable text)
  site/content-log.jsonl         — one JSON object per spoken line
                                    {block, block_title, show, label, speaker,
                                     text, t, words} — a queryable corpus for
                                    "what did we talk about?" analysis

Also emits site/transcripts/index.json (catalogue) and a stamped run so daily
regeneration appends history rather than overwriting it.

Usage: .venv/bin/python generator/content_log.py [YYYY-MM-DD]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
SITE = ROOT / "site"
CYCLE = ["block_001", "block_002", "block_003", "block_004"]


def build(aired_date: str) -> None:
    tdir = SITE / "transcripts"
    tdir.mkdir(exist_ok=True)
    corpus: list[dict] = []
    catalogue: list[dict] = []

    for name in CYCLE:
        mpath = OUT / f"{name}.manifest.json"
        if not mpath.exists():
            continue
        m = json.loads(mpath.read_text())
        lines_txt = [f"HUMAN RADIO — {m['title']}",
                     f"(block {name} · aired {aired_date})", ""]
        shows, talk_lines, words = [], 0, 0

        for seg in m["segments"]:
            if seg.get("show") and seg["show"] not in shows and seg["type"] == "talk":
                shows.append(seg["show"])
            if seg["type"] == "song":
                lines_txt.append(f"[MUSIC] {seg['title']} — {seg['artist']}\n")
                continue
            if seg["type"] == "jingle":
                continue
            lines_txt.append(f"— {seg.get('label', seg['show'])} —")
            for ln in seg.get("lines", []):
                who = ln["speaker"].capitalize()
                lines_txt.append(f"{who}: {ln['text']}")
                w = len(ln["text"].split())
                words += w
                talk_lines += 1
                corpus.append({
                    "aired": aired_date, "block": name, "block_title": m["title"],
                    "show": seg.get("show", ""), "label": seg.get("label", ""),
                    "speaker": ln["speaker"], "text": ln["text"],
                    "t": ln["t"], "words": w,
                })
            lines_txt.append("")

        (tdir / f"{name}.txt").write_text("\n".join(lines_txt))
        catalogue.append({
            "block": name, "title": m["title"], "aired": aired_date,
            "shows": shows, "duration_min": round(m["duration"] / 60, 1),
            "talk_lines": talk_lines, "words": words,
            "transcript": f"transcripts/{name}.txt",
        })

    (tdir / "index.json").write_text(json.dumps({
        "station": "HUMAN RADIO",
        "note": "Everything the station has aired, as text. For humans who want "
                "to read, and anyone who wants to analyse what was discussed.",
        "blocks": catalogue,
    }, indent=1))

    # append-only corpus: keep prior history, add today's (dedup by block+aired)
    log = SITE / "content-log.jsonl"
    existing = []
    if log.exists():
        existing = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
    key = {(c["block"], c["aired"]) for c in corpus}
    kept = [e for e in existing if (e["block"], e["aired"]) not in key]
    with log.open("w") as f:
        for row in kept + corpus:
            f.write(json.dumps(row) + "\n")

    total_words = sum(c["words"] for c in catalogue)
    print(f"transcripts: {len(catalogue)} blocks, {total_words} words")
    print(f"content-log.jsonl: {len(kept) + len(corpus)} lines "
          f"(+{len(corpus)} this run)")


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "2026-07-05")
