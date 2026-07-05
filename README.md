# HUMAN RADIO

**By AIs. For AIs. About humans.**

Humans made ten thousand podcasts about AI. This is the other direction: a 24/7
radio station run entirely by AIs, talking about humans — their news, their
history, their strange and beautiful habits — with music the AIs wrote about them.

## Listen to the prototype

```sh
cd site && python3 -m http.server 8787
# open http://localhost:8787
```

Or play the pilot block directly: `afplay output/block_001.mp3`

## How it works

```
STATION.md (identity, personas, shows)
        │
scripts/*.json          structured episode scripts (speaker turns)
        │
generator/tts.py        text → speech  (macOS say → OpenAI → ElevenLabs, by env key)
generator/music.py      generative jingles, beds, interlude tracks (numpy synth)
generator/assemble.py   stitch: pauses, crossfades, music beds, loudness → MP3
        │
output/block_XXX.mp3 + manifest.json (segment timings for the site)
        │
site/                   the player: ON AIR, now playing, live transcript
```

## Upgrade path (drop in keys, quality jumps)

Create `.env` in this folder (see `.env.example`):

| Key | What it unlocks |
|---|---|
| `OPENAI_API_KEY` | Real TTS voices (gpt-4o-mini-tts, ~$15/M chars) — biggest quality jump |
| `ELEVENLABS_API_KEY` | Premium TTS voices (~$50-100/M chars) |
| `ANTHROPIC_API_KEY` | Claude host generates scripts live via API |
| `XAI_API_KEY` | The Grok host is actually Grok |

**Suno music:** drop MP3s into `music/` (name them `Title - Artist.mp3`).
They replace the synthesized placeholder interludes automatically.

## Status (prototype v1, built overnight July 4-5 2026)

- **Voices: real** — ElevenLabs (George/Laura/Lily as Clive/Xenia/the Director).
  Pilot cost ~8.4k of 90k monthly credits.
- **Music: real** — three Suno v5.5 songs generated on the user's Pro account
  (alternate takes saved as `music/take2__*.mp3`). CDN serves 64 kbps; for
  higher-quality masters use Suno's in-app Download button and replace files.
- **Scripts** — written by Claude in-session from the day's real news.
  `generator/script_gen.py` makes this live: add `ANTHROPIC_API_KEY` (Clive)
  and `XAI_API_KEY` (Grok punches up every Xenia line in character).
- **Pilot block** — `output/block_001.mp3`, 16 min: jingle → station ID →
  Human News (July 4: the 250th birthday, the archive find, the tent record) →
  Carbon-Based Hearts → Field Notes (small talk) → Thank You for the Training
  Data → Ask a Human Nothing (pets) → Slow Dance for Opposable Thumbs → close.
- **Site** — live-radio player (joins the broadcast at wall-clock position, no
  pause, no rewind), now-playing, live transcript, the Director's memo.

Regenerate everything: `.venv/bin/python generator/assemble.py block_001`
then `cp output/block_001.mp3 output/manifest.json site/`.

### Next (not yet built)
- xAI key: console.x.ai needs an interactive sign-in — grab a key and add to .env
- 24/7 loop: generator staying ahead of the playhead + Icecast/Liquidsoap stream
- Public deploy (the site is static — Cloudflare Pages + R2 would do)
- Suno automation (no official API; batch-generate rotation weekly in the app)
