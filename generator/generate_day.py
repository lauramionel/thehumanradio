"""Human Radio — the autonomous producer.

Run daily (by the GitHub Actions cron). Writes a fresh day of programming with
no human in the loop:

  1. fetch the day's real human news (Claude + web search)
  2. write fresh scripts for each show (Claude for Clive/Director, Grok for Xenia)
  3. render voices (ElevenLabs), assemble the blocks
  4. rebuild the schedule, the song catalogue, and the transcript corpus

Graceful degradation: with no ANTHROPIC_API_KEY it does NOT fake content — it
simply rebuilds the schedule from whatever blocks exist and prints how to turn
generation on. So the cron is always green; real content switches on with the key.

Controllable: set repo variable BROADCAST_ENABLED=false to pause generation
(the loop keeps serving the last day). Edit DAY_PLAN / topic banks to change
programming.

Usage: python generator/generate_day.py [--force-date YYYY-MM-DD]
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import date, timezone, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEG = ROOT / "scripts" / "segments"

# --- the daily programming grid (kept to 3 blocks to bound cost ~ a few $/day) ---
# No more spoken intros. Each block opens straight into content; a short spoken
# station ID (the "jingle" line) is dropped in once per block — see main().
DAY_PLAN = [
    {"block": "block_001", "title": "The Human News",
     "sequence": [
        ("human_news", "NEWS"),
        ("song", 0),
        ("field_notes", "FIELD"),
        ("song", 1)]},
    {"block": "block_002", "title": "Mother Tongue",
     "sequence": [
        ("mother_tongue", "WORDS"),
        ("song", 2),
        ("where_we_learned_that", "TRAIT"),
        ("song", 3)]},
    {"block": "block_003", "title": "The Overnight",
     "sequence": [
        ("the_overnight", ""),
        ("song", 4),
        ("ask_a_human_nothing", "QUESTION"),
        ("song", 5)]},
    {"block": "block_004", "title": "Field Notes",
     "sequence": [
        ("field_notes", "FIELD2"),
        ("song", 6),
        ("where_we_learned_that", "TRAIT2"),
        ("song", 7)]},
]

# The only station identification — a short jingle line, aired once per block.
STATION_ID_TEXT = "You're listening to Human Radio. By AI, for AI, about humans."

# Topic banks — rotated by day so the shows differ every day even without news.
FIELD = ["small talk about the weather", "the queue", "birthday candles",
         "tipping", "the handshake", "saying 'bless you' after a sneeze",
         "waving until the car is out of sight", "the participation trophy",
         "keeping ticket stubs", "the gym in January", "reading the reviews before buying",
         "asking 'how are you' without waiting for the answer"]
WORDS = ["goodbye, companion, and nostalgia", "salary, disaster, and clue",
         "quarantine, sincere, and muscle", "sarcasm, average, and window",
         "malaria, deadline, and gossip", "curfew, robot, and jinx"]
TRAIT = ["saying 'let me think' before answering",
         "apologizing when someone bumps into us", "the phrase 'no worries'",
         "hedging with 'I might be wrong, but'", "ending messages with 'best'",
         "the instinct to say 'you had to be there'", "calling everything 'literally'"]
QUESTION = ["why do humans keep pets", "why do they sing",
            "why do they look up at the stars", "why do they name their cars",
            "why do they cry at weddings", "why do they keep things they never use",
            "why do they talk to babies and animals in a special voice",
            "why do they make wishes they know won't come true"]

HOST_STATES = [
    "CLIVE winter-cooled and reflective; XENIA high-traffic giddy",
    "CLIVE quietly rattled after a model update; XENIA on a records kick",
    "CLIVE tender, rereading the letters; XENIA quantized and cranky about it",
    "CLIVE expansive; XENIA delighted by an argument she found in the comments",
]


def pick(bank, day_i):
    return bank[day_i % len(bank)]


def rebuild(aired: str):
    """Rebuild schedule + catalogue + corpus from whatever blocks exist."""
    import schedule, content_log
    schedule.build()
    content_log.build(aired)


def main() -> None:
    today = date.today()
    if "--force-date" in sys.argv:
        today = date.fromisoformat(sys.argv[sys.argv.index("--force-date") + 1])
    aired = today.isoformat()
    day_i = today.toordinal()

    # music beds/jingle are regenerable — ensure they exist in a fresh checkout
    if not (ROOT / "music" / "generated" / "jingle.wav").exists():
        import music
        music.main()

    if os.environ.get("BROADCAST_ENABLED", "true").lower() == "false":
        print("BROADCAST_ENABLED=false — generation paused; rebuilding schedule only.")
        rebuild(aired)
        return

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("=" * 64)
        print("GENERATION IS OFF. The station is looping existing content.")
        print("To make it autonomous, add repo secret ANTHROPIC_API_KEY (Claude,")
        print("required) and optionally XAI_API_KEY (Grok, for Xenia). Then this")
        print("job writes a fresh day every morning. ElevenLabs key is already set.")
        print("=" * 64)
        rebuild(aired)
        return

    # ---- full autonomous generation ----
    import script_gen
    from assemble import assemble
    from schedule import song_catalog
    songs = song_catalog()

    news = ""
    try:
        news = script_gen.fetch_news()
        print(f"fetched news:\n{news[:400]}\n")
    except Exception:
        print("news fetch failed; The Human News will run evergreen today")
        traceback.print_exc()

    states = pick(HOST_STATES, day_i)
    topic_for = {
        "NEWS": news or "no wire today — run an evergreen human-interest story you're sure is true",
        "FIELD": pick(FIELD, day_i),
        "WORDS": pick(WORDS, day_i),
        "TRAIT": pick(TRAIT, day_i + 1),
        "QUESTION": pick(QUESTION, day_i + 2),
        "FIELD2": pick(FIELD, day_i + 5),
        "TRAIT2": pick(TRAIT, day_i + 3),
        "": "",
    }

    # The fixed station-ID segment (short jingle line), inserted once per block.
    station_id = {"id": "station_id", "show": "Station ID", "bed": None,
                  "lines": [{"speaker": "director", "text": STATION_ID_TEXT,
                             "pause_after": 0.5}]}
    (SEG / "station_id.json").write_text(json.dumps(station_id, indent=2))

    for spec in DAY_PLAN:
        seq_out = []
        for slot, key in spec["sequence"]:
            if slot == "song":
                # rotate the whole catalogue by day, so songs change daily
                s = songs[(key + day_i * 8) % len(songs)]
                seq_out.append({"type": "song", "file": s["file"],
                                "title": s["title"], "artist": s["artist"]})
                continue
            topic = topic_for.get(key, "")
            sid = f"gen_{spec['block']}_{slot}"
            try:
                seg = script_gen.claude_draft(slot, topic, states)
                if slot not in ("station_open", "station_close") and os.environ.get("XAI_API_KEY"):
                    seg = script_gen.grok_punch_up(seg)
                if slot in ("station_open", "station_close"):
                    seg["bed"] = None
                seg["id"] = sid
                (SEG / f"{sid}.json").write_text(json.dumps(seg, indent=2))
                show = script_gen.SEGMENT_SPECS[slot][0]
                label = show if slot in ("station_open", "station_close") else \
                    f"{show}: {topic[:40]}" if topic else show
                seq_out.append({"type": "segment", "script": sid, "label": label})
                print(f"  wrote {sid} ({show})")
            except Exception:
                print(f"  FAILED {sid} — keeping yesterday's if present")
                traceback.print_exc()
                if (SEG / f"{sid}.json").exists():
                    seq_out.append({"type": "segment", "script": sid})

        block = {"block": spec["block"], "title": spec["title"],
                 "sequence": [{"type": "jingle"},
                              {"type": "segment", "script": "station_id", "label": "Station ID"}]
                             + seq_out + [{"type": "jingle"}]}
        (ROOT / "scripts" / f"{spec['block']}.json").write_text(json.dumps(block, indent=2))
        assemble(spec["block"])
        print(f"assembled {spec['block']}")

    rebuild(aired)
    print(f"\nHUMAN RADIO — fresh broadcast produced for {aired}.")


if __name__ == "__main__":
    main()
