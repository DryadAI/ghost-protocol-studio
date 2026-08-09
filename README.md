# THE GHOST PROTOCOL // AI Show Runner & Studio

Single-file, zero-dependency (Python 3 stdlib only) production studio for the AI debate show. Dark terminal aesthetic, four show formats, human banter injection, live transcript editing, and one-click export to a fully open-source Piper + FFmpeg render pipeline.

## Run

```bash
python3 ghost_protocol_studio.py
# open http://localhost:7860
```

No pip installs. Env overrides: `GP_PORT`, `GP_ENDPOINT`, `GP_API_KEY`, `GP_MODEL`.

## Backend

Defaults to your Bifrost gateway at `http://localhost:8080/v1/chat/completions` with model `ollama/qwen3:14b`. Any OpenAI-compatible endpoint works — change it in the UI (03 // ENGINE) or via env vars. Free-tier direct options if Bifrost is down:

- Groq: `https://api.groq.com/openai/v1/chat/completions`, model e.g. `llama-3.3-70b-versatile`
- Gemini: `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`, model `gemini-2.0-flash`

Put the key in the API KEY field (or leave blank if Bifrost holds keys). TEST CONNECTION pings `<base>/models`.

**Simulation Mode** (checkbox) runs the whole flow with canned lines and zero API calls — use it to learn the UI and test exports.

## The four formats

1. **Socratic Stress-Test** — SUBROUTINE_ALPHA (interrogator) vs SUBROUTINE_BETA (defender), N rounds, SYSTEM_KERNEL verdict with fallacy detection.
2. **Round Table** — PROTOCOL-7 (deadpan literalist), M.I.R-A (techno-optimist), CYNIC.EXE (doom-poster) discuss the topic; after each round the run *pauses* and each human co-host (set names in 01 // FORMAT) types banter that feeds the next AI turns. Kernel closes with "Best Line of the Night."
3. **Grand Tribunal** — AUDIT-9 prosecutes the thesis, ADVOCATE-0 defends, SUBJECT-X testifies; openings, N examination rounds, closings, Kernel ruling, then a human jury verdict prompt. Optionally **CALL A STAR WITNESS** (01 // FORMAT, tribunal only) — name a witness and give them a background, and they're called to the stand after the accused's examination: prosecution questions them, defense cross-examines. Fully AI-voiced and editable in 02 // CAST like any other speaker.
4. **Triad Synthesis** — STOIC-1, NIHIL-0, UTIL-3 argue N rounds; SYNTHESIS_CORE forges the compromise position.

Every cast member's name, system prompt, model override, and Piper voice is editable in 02 // CAST. Every transcript bubble is click-to-edit; RE-ROLL regenerates a line in context; CUT deletes it.

## Character registry (`characters.json`)

All 13 unique cast members (some reused across formats, like SYSTEM_KERNEL) have a full profile in `characters.json`: a debate archetype (Interrogator, Logician, Skeptic, Synthesizer, ...), a distinct comedic voice, a transparent cutout portrait, and — the big one — **a genuinely unique AI model each**, pulled only from what's actually working through Bifrost right now (Ollama + Groq; `vllm/*` is deliberately excluded — see CLAUDE.md, it's paid-subscription-backed and "not a default for any agent"). The app fetches this at boot (`/api/characters`) and pre-fills each cast card's MODEL OVERRIDE, portrait thumbnail, and archetype badge — still fully editable per-run in 02 // CAST. `characters.json` is the design-intent source of truth; `CASTS` in the app is what actually runs, kept in sync by hand.

## Export → video (04 // EXPORT)

- `transcript.json` / `transcript.txt` — JSON export includes each line's sid, archetype, humor style, model, and voice for full reproducibility.
- `▶ RENDER EPISODE.MP4` (in the UI) — server-side **piper-tts** (per-speaker voices) + **ffmpeg** render. Each cast member with a portrait in `assets/portraits/<sid>.png` (transparent cutout, background-removed with `rembg`) gets a Terry Gilliam-style floating cutout — Ken Burns zoom, wobbling pan, and a rotation jitter — composited directly onto the format's backdrop; lines without a portrait (human co-hosts) fall back to the original full-width text layout. If `assets/backdrops/<format>.jpg` exists (one per show format — socratic/roundtable/tribunal/triad), it fills the whole frame; falls back to the flat color background otherwise.
- `compile_show.sh` — manual/offline export with full parity to the server-side render (same portraits, backdrops, Ken Burns + rotation animation). Useful for rendering on another machine.

One-time setup on Arch:

```bash
sudo pacman -S ffmpeg
yay -S piper-tts-bin        # or: pipx install piper-tts
mkdir voices                 # download the .onnx + .onnx.json voice files
# voices used by default: en_US-lessac-medium, en_US-ryan-high, en_US-amy-medium,
# en_US-joe-medium, en_GB-alan-medium, en_GB-northern_english_male-medium
# from https://huggingface.co/rhasspy/piper-voices
bash compile_show.sh         # -> episode.mp4
```

`VOICEDIR=/path/to/voices bash compile_show.sh` if your voices live elsewhere.

## Workflow for one episode

1. Pick format + topic, set rounds (4 is a good 10-min episode).
2. TEST CONNECTION (or tick Simulation Mode).
3. ▶ INITIALIZE — watch the feed; type when the yellow human box appears.
4. Edit/re-roll any weak lines after the run.
5. Click **▶ RENDER EPISODE.MP4** — server-side piper+ffmpeg render, playable in the panel, ready to upload. (`compile_show.sh` download still available for rendering elsewhere.)
