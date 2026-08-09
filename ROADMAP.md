# Roadmap

This file tracks the engine repo only. The master plan across all repos (engine, Guild, template, flagship show) lives in [PLAN.md](PLAN.md).

## Now (before first upload)
- [ ] First full episode rendered end-to-end on madhatter (Socratic, 4 rounds)
- [ ] Verify Bifrost model mappings + pick default voices per speaker
- [ ] systemd user service on madhatter (GP_BIND=0.0.0.0)

## Next
- [ ] ROLL ×3 — dice offers three candidate topics, click to pick
- [ ] Fallacy ticker — kernel tags fallacies with quotes; UI flashes "LOGICAL FALLACY DETECTED" overlay data into the export
- [ ] Contradiction meter — per-turn score from the kernel, rendered as a gauge in the video
- [ ] Per-line TTS preview button (calls local piper) before committing to a full render
- [ ] Save/load full sessions (transcript + cast + settings) as .json

## Later
- [ ] OBS overlay mode — a /overlay page with transparent bg for live streaming
- [ ] Episode packaging generator — title, description, tags, thumbnail text from transcript
- [ ] Waveform visualizer per speaker in the rendered video (ffmpeg showwaves)
- [ ] Second renderer theme (Neon Peripatos — synthwave columns) sharing the same transcript format
- [ ] Audience vote ingestion — paste YouTube comments, kernel tallies the verdict for a follow-up short

## Done
- [x] Single-file studio: 4 formats, human banter injection, transcript edit/re-roll
- [x] Bifrost/OpenAI-compatible backend + Simulation Mode
- [x] piper+ffmpeg episode compiler export
- [x] 1000-topic dice roller (500 serious / 500 absurd) with pool filter
- [x] LAN access (GP_BIND), panel toggles, GitHub repo
