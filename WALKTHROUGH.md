# Episode 01 Walkthrough

Concrete, this-instance steps for producing the first Ghost Protocol episode on madhatter. For general reference see `README.md`.

## 0. What's already live

- App: running as systemd user service `ghost-protocol.service` (enabled, survives reboot)
- URL: `http://localhost:7860` (this box) / `http://10.0.0.224:7860` (LAN) / `http://100.72.190.41:7860` (Tailscale, e.g. from precision)
- Engine: Bifrost gateway (`http://localhost:8080/v1/chat/completions`), default model `ollama/qwen3:14b` — confirmed working
- Voices: all 6 default Piper voices already in `./voices/` — piper/ffmpeg pipeline smoke-tested and working

## 1. Open it

Browser → `http://localhost:7860` (or the LAN/Tailscale URL above).

## 2. Pick format + topic (01 // FORMAT)

For episode 1, use **Socratic Stress-Test** — it's the shortest format (2 AI speakers + Kernel verdict), fewest moving parts, best for confirming the whole pipeline works before trying Round Table (which needs live human typing) or Tribunal/Triad (longer casts).

- Format: `Socratic Stress-Test (1v1 dialectic)`
- Topic: use the default thesis, or write your own one-liner. Keep it a clear, arguable claim — the format works best on binary positions.
- Rounds: `4` (good ~8-10 min episode)
- Temp: `0.5` (default is fine)

## 3. Check the cast (02 // CAST)

Leave defaults for episode 1: SUBROUTINE_ALPHA / SUBROUTINE_BETA / SYSTEM_KERNEL, each already mapped to a downloaded voice (`en_US-lessac-medium`, `en_US-ryan-high`, `en_GB-alan-medium`). No edits needed — just confirm the voice dropdowns show a value.

## 4. Confirm the engine (03 // ENGINE)

Should already be pre-filled from `/api/defaults`:
- Endpoint: `http://localhost:8080/v1/chat/completions`
- API key: blank (Bifrost holds keys)
- Model: `ollama/qwen3:14b`

Click **TEST CONNECTION** — expect a green `✔` reachable message. If it fails, Bifrost container may be down (`docker ps | grep bifrost` — should show `healthy`).

Leave **SIMULATION MODE** unchecked — you want real model output for episode 1, not canned lines. (Check it first only if you just want to rehearse the UI with zero API calls.)

## 5. Run it

- Click **▶ INITIALIZE**.
- Watch the feed: each speaker's line streams in with a "processing" indicator first.
- Socratic format has no human-input pauses, so it runs to completion unattended (~2-4 min for 4 rounds on `qwen3:14b`).
- When done: `— END OF EPISODE —` and status goes to `DONE`.

## 6. Edit pass

- Click any line's text to edit it inline (auto-saves on blur).
- `↻ RE-ROLL` regenerates a line in context if a response was weak or off-persona.
- `✕ CUT` removes a line entirely.
- Do this before exporting — the compiled video uses whatever's in the transcript at export time.

## 7-8. Export & render (04 // EXPORT)

- `TRANSCRIPT .JSON` / `.TXT` — raw transcript, useful for show notes/captions.
- **`▶ RENDER EPISODE.MP4`** — click it. The server runs `piper` per line (using each speaker's assigned voice from `./voices/`) and `ffmpeg` to build a terminal-styled 1080p segment per line, concatenates them, and hands back a playable video right in the panel — no terminal needed. Takes roughly a few seconds per line.

Output lands in `./renders/episode_<timestamp>.mp4` on the server; the browser also gets a `<video>` preview and a download link.

- `DOWNLOAD compile_show.sh` is still there as a manual fallback — useful if you want to render on a different machine, or offline:

```bash
mv ~/Downloads/compile_show.sh /home/katalyst/GitHub/ghost-protocol-studio/
cd /home/katalyst/GitHub/ghost-protocol-studio
bash compile_show.sh   # VOICEDIR=/path/to/voices bash compile_show.sh if voices live elsewhere
```

## 9. Sanity check the output

```bash
ffprobe -v error -show_entries format=duration,size -of default=noprint_wrappers=0 renders/episode_<timestamp>.mp4
```

Play it locally (`mpv episode.mp4` or copy it off-box) before uploading anywhere.

## 10. Next episode

Once episode 1 confirms the pipeline end to end, Round Table is the natural next format to try — it's the one built for human banter (you get pulled in as a co-host between AI turns via the yellow HUMAN INPUT box).

## Notes / known limits

- Voices are **Piper only** for now (local, offline, unlimited, zero cost). ElevenLabs was considered — free tier caps at ~10k credits/mo (~10 min audio) and explicitly excludes commercial use, so it's not wired in. Revisit if a paid ElevenLabs tier is worth it for a specific episode's audio quality.
- `compile_show.sh` is self-contained per export — re-export after every edit pass, it doesn't read the live transcript state, it's a snapshot at click time.
