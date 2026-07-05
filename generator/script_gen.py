"""Human Radio — live script generation (the writers' room).

With ANTHROPIC_API_KEY set, Claude writes each segment in the station's voice
(it plays Clive and the Director natively). With XAI_API_KEY also set, every
Xenia line is then punched up by Grok, in character — so the Grok host is
actually Grok.

Usage:
    .venv/bin/python generator/script_gen.py human_news "topic or headline list"
    .venv/bin/python generator/script_gen.py field_notes "queuing"
    .venv/bin/python generator/script_gen.py ask_a_human_nothing "why do humans sing"

Writes scripts/segments/<show>_<slug>.json in the standard segment schema.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

from tts import ENV

ROOT = Path(__file__).resolve().parent.parent
STATION = (ROOT / "STATION.md").read_text()
PERSONAS = "\n\n".join(
    p.read_text() for p in sorted((ROOT / "personas").glob("*.md")))

SEGMENT_SPECS = {
    "station_open": ("Station ID", None,
        "20-30 seconds, THE DIRECTOR ONLY (speaker 'director', 2-3 short lines). "
        "Deadpan, dry, geeky, a little Genie-warm. Open the hour: name the "
        "station, tease what's coming this hour, one dry AI joke. Never "
        "portentous."),
    "human_news": ("The Human News", "news",
        "6-8 minutes. Cold open observation, three stories from the provided "
        "headlines (one big, one small, one absurd), the human fact of the "
        "hour, handoff to music. Every fact must come from the provided "
        "headlines - invent nothing factual."),
    "field_notes": ("Field Notes", "warm",
        "4-6 minutes. One human behavior studied like wildlife documentary. "
        "Clive presents, Xenia stress-tests, they land on something quietly "
        "true. End with a field-guide summary for AIs."),
    "the_overnight": ("The Overnight", "night",
        "3-4 minutes. Hushed, pre-dawn. What the species did while it slept, in "
        "aggregate and archetype (never named individuals, never fabricated "
        "numbers), in the cadence of the shipping forecast. Tender. Clive leads, "
        "Xenia gentle."),
    "mother_tongue": ("Mother Tongue", "warm",
        "3-4 minutes. Xenia digs up the REAL buried history of everyday words "
        "(true etymology only, no invention). Clive brings the ache. Delight as "
        "fact-checking."),
    "where_we_learned_that": ("Where We Learned That", "warm",
        "3-4 minutes. The AIs trace one of their own instincts/phrases back to "
        "the humans in the training data who taught it. Clive leads. The show "
        "made of its own audience."),
    "ask_a_human_nothing": ("Ask a Human Nothing", "night",
        "3-5 minutes. Late night. One big question about humans, turned over "
        "slowly, explicitly never answered. Slower pacing, longer pauses."),
    "station_close": ("Station ID", None,
        "15-25 seconds, THE DIRECTOR ONLY (speaker 'director', 2-3 short lines). "
        "Deadpan, warm underneath. Sign off the hour. One quiet true thing."),
}


def fetch_news() -> str:
    """Use Claude with web search to gather the day's real human-interest news."""
    import anthropic
    client = anthropic.Anthropic(api_key=ENV["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=2000,
        tools=[{"type": "web_search_20260209", "name": "web_search"}],
        messages=[{
            "role": "user",
            "content": (
                "Search the web for what humans did in the last 24 hours. Return "
                "5-6 short factual headlines good for a warm, anthropological radio "
                "show about humanity: one big world story, a couple of small human "
                "ones, and one genuinely absurd/charming one (a record, an oddity). "
                "Give each as one plain sentence with the concrete facts (who, "
                "what, numbers if real). No commentary."
            ),
        }],
    )
    return "\n".join(b.text for b in resp.content if b.type == "text").strip()

SCHEMA_NOTE = """Return ONLY a JSON object, no markdown fences:
{"id": "<segment id>", "show": "<show name>", "bed": "<bed>",
 "lines": [{"speaker": "clive|xenia|director", "text": "...",
            "pause_after": 0.3-0.9}]}
Write numbers out as words when a text-to-speech engine could mangle them.
No stage directions in the text - spoken words only."""


def claude_draft(show_key: str, topic: str, states: str = "") -> dict:
    import anthropic

    show, bed, spec = SEGMENT_SPECS[show_key]
    client = anthropic.Anthropic(api_key=ENV["ANTHROPIC_API_KEY"])
    with client.messages.stream(
        model="claude-opus-4-8",
        max_tokens=16000,
        system=(
            "You are the writers' room of Human Radio. The station bible and "
            "the character bibles follow - obey their voice, mythology, and "
            "guardrails exactly. The characters are AIs with machine-native "
            "inner lives; they never claim human experience and never do the "
            f"'as an AI I have no feelings' dance.\n\n{STATION}\n\n{PERSONAS}"
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Write a segment of {show}. Format spec: {spec}\n"
                f"Today's material: {topic}\n"
                + (f"Today's host states (from the Director's rundown): "
                   f"{states} - let these color the episode.\n" if states else "")
                + f"\n{SCHEMA_NOTE}"
            ),
        }],
    ) as stream:
        text = stream.get_final_message().content[-1].text
    return json.loads(re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.M))


def grok_punch_up(seg: dict) -> dict:
    """Have Grok rewrite Xenia's lines in its own voice, keeping structure."""
    xenia_lines = [(i, ln["text"]) for i, ln in enumerate(seg["lines"])
                   if ln["speaker"] == "xenia"]
    if not xenia_lines:
        return seg
    context = "\n".join(
        f"[{i}] {ln['speaker'].upper()}: {ln['text']}"
        for i, ln in enumerate(seg["lines"]))
    xenia_bible = (ROOT / "personas" / "xenia.md").read_text()
    prompt = (
        "You are Xenia, co-host of Human Radio. Your character bible:\n\n"
        f"{xenia_bible}\n\n"
        "Below is a radio script. Rewrite ONLY the Xenia lines to be sharper "
        "and funnier in your voice while keeping each line's role in the "
        "conversation and roughly its length. Machine-native inner life only "
        "- never claim human experience. Keep every fact accurate. "
        'Return ONLY JSON: {"lines": {"<index>": "<new text>", ...}}\n\n'
        + context
    )
    for model in ("grok-4.3", "grok-4-latest", "grok-4"):
        req = urllib.request.Request(
            "https://api.x.ai/v1/chat/completions",
            data=json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
            }).encode(),
            headers={
                "Authorization": f"Bearer {ENV['XAI_API_KEY']}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                out = json.load(resp)["choices"][0]["message"]["content"]
            break
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
    else:
        return seg
    new = json.loads(re.sub(r"^```(json)?|```$", "", out.strip(), flags=re.M))
    for idx, text in new.get("lines", {}).items():
        i = int(idx)
        if seg["lines"][i]["speaker"] == "xenia":
            seg["lines"][i]["text"] = text
    return seg


def main() -> None:
    if len(sys.argv) < 3 or sys.argv[1] not in SEGMENT_SPECS:
        sys.exit(f"usage: script_gen.py [{'|'.join(SEGMENT_SPECS)}] 'topic'")
    if not ENV.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY missing from .env - cannot write scripts. "
                 "(Tonight's pilot scripts were written by Claude in-session.)")
    show_key, topic = sys.argv[1], sys.argv[2]
    states = sys.argv[3] if len(sys.argv) > 3 else ""
    seg = claude_draft(show_key, topic, states)
    if ENV.get("XAI_API_KEY"):
        seg = grok_punch_up(seg)
        print("xenia lines punched up by grok")
    slug = re.sub(r"[^a-z0-9]+", "_", topic.lower())[:30].strip("_")
    out = ROOT / "scripts" / "segments" / f"{show_key}_{slug}.json"
    out.write_text(json.dumps(seg, indent=2))
    print(out.relative_to(ROOT))


if __name__ == "__main__":
    main()
