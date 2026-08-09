# TASKS — THE GHOST PROTOCOL dev kit

Master plan: PLAN.md. Work top to bottom, one branch per phase, check off with [x] and commit TASKS.md with the work. Gate before every commit: `python3 -m py_compile ghost_protocol_studio.py`; boot server; `curl /` (200) and `/api/topics` (1000); one full Simulation Mode episode per format touched. STOP at every phase boundary for review.

Dev show directory: `show/` in this repo (`GP_SHOW_DIR=./show`). It is the Phase 1–3 test bed; the real flagship repo arrives in Phase 4.

## Phase 1 — Souls go live (branch: p1-souls)
- [ ] Engine: at startup resolve show dir (`GP_SHOW_DIR` env, default `./show` if present); scan `<show>/cast/*/` and `<show>/crew/*/` for card.json + SOUL.md (+ MEMORY.md)
- [ ] Soul → system prompt assembler: Identity + Craft rules + Voice + Hard lines + Director's standing notes + MEMORY.md digest (if non-empty)
- [ ] New GET /api/cast returning hired members (sid, name, color, formats, role, model_recommendation, piper_voice, assembled prompt)
- [ ] UI: cast panel populated from /api/cast when hires exist; built-in CASTS remains fallback when no cast/ dir
- [ ] Format slotting: map hired members into format roles via card.json formats+role; casting picker in UI when >1 member qualifies for a slot
- [ ] Acceptance: with GP_SHOW_DIR=./show, run a Simulation episode — hired names/colors/prompts appear; editing a SOUL.md changes the next run
- [ ] Cross-check in a fresh show-template checkout (hire 2 actors, point engine at it)
- [ ] show-template: bump vendored engine, update README "Current wiring status" section, push
- [ ] Merge, tag phase-1

## Phase 2 — Stage manager + bus (branch: p2-stage-manager)
- [ ] Server-side episode runner: POST /api/episode/start {format, topic, rounds, cast, humans} creates `<show>/episodes/ep-NNN/`
- [ ] Every event appended to episodes/ep-NNN/bus.jsonl as {ts, from, to, type, ref, body}; types: line, note, retake, artifact, panel, approval_request, state
- [ ] Episode state machine: brief → running → awaiting_human → post → rendered; transitions logged on the bus
- [ ] UI becomes a bus tailer (polling is fine); human turns block server loop until POST /api/episode/input
- [ ] Replay: GET /api/episode/<id>/bus loads any past episode read-only; transcript.json derived from bus
- [ ] Headless: `python3 ghost_protocol_studio.py --episode <id> --run` (works in Simulation Mode)
- [ ] Acceptance: kill browser mid-run, reopen, feed resumes; replay a finished episode; one headless Simulation run completes
- [ ] Merge, tag phase-2

## Phase 3.1 — SPLICE the editor (branch: p3-1-splice)
- [ ] Post-run "editor pass": SPLICE (soul from `<show>/crew/splice/`) reads transcript, emits per-line cut proposals on the bus with one-word justifications
- [ ] UI: proposals render as strikethroughs with approve/reject per cut; approved cuts produce the locked transcript used for export
- [ ] Works in Simulation Mode (canned cut proposals)
- [ ] Merge, tag phase-3.1

## Phase 3.2 — INKWELL the head writer (branch: p3-2-inkwell)
- [ ] Pre-run pass: INKWELL reads episodes/ep-NNN/brief.md + `<show>/SERIES_BIBLE.md` → writes beatsheet.md (beats, planned collisions, callback slots, cold open)
- [ ] Stage manager feeds the current beat into each turn's instruction
- [ ] UI: beat sheet visible during run; approval gate before the run starts (approval_request on the bus)
- [ ] Merge, tag phase-3.2

## Phase 3.3 — CANON.LOCK the archivist (branch: p3-3-canon-lock)
- [ ] Post-episode pass: CANON.LOCK reads locked transcript + each cast MEMORY.md → emits proposed MEMORY.md diffs (running gags, positions, grudges, notable lines) on the bus
- [ ] User approves diffs → files written in `<show>/cast/*/MEMORY.md` (never the Guild)
- [ ] Pre-episode: continuity brief artifact for the writers (callbacks available)
- [ ] Soul assembler (P1) includes updated memory digest — verify a gag carries into the next episode's prompt
- [ ] Merge, tag phase-3.3 — STOP: ask Nathan before the flagship split

## Phase 4 — Flagship split (branch: p4-flagship, plus new repo)
- [ ] Create the-ghost-protocol repo from show-template (`gh repo create --template DryadAI/show-template`); hire the founding 13; move `show/` content there as the real SERIES_BIBLE.md + episodes
- [ ] Engine repo goes content-neutral: built-in CASTS shrinks to a minimal 2-actor demo; `show/` becomes a tiny demo show; characters.json note pointing to the Guild
- [ ] Engine release tags start (v0.4.0); show-template pins by tag + gets update-engine.sh
- [ ] Acceptance: full episode produced from the-ghost-protocol repo alone
- [ ] Merge, tag phase-4

## Phase 5 — Director's chair + panels (branch: p5-directors-chair)
- [ ] Panel mini-catalog in UI (card, list, form, buttons, meter, choice) rendering type:"panel" bus messages (A2UI-shaped envelope, no dependency)
- [ ] AUTEUR-0 mid-run retake notes → re-roll with note appended to the turn prompt
- [ ] Approval gates from 3.2/3.3 rendered via panels; pipeline kanban view of episodes/ by state
- [ ] Soul inspector: view/edit hired souls + memory from the UI
- [ ] Merge, tag phase-5

## Phase 6 — Publish pipeline (branch: p6-publish)
- [ ] HYPE.CYCLE pass → episodes/ep-NNN/publish/: 5 titles (kill 4), description with Guild credits from cast.lock.json (bylaw 9), tags, thumbnail text, poll, shorts timestamps
- [ ] TWO-STARS pre-render review with ship/hold on the bus
- [ ] Remaining crew online: GAG.DLL + CITE-SEER (beatsheet passes), EXEC.SYS + ROLODEX (slates + casting), FOLEY.WAV + GRIP-88 ([beat] marks + scene specs into renderer)
- [ ] Merge, tag phase-6

## Phase 7 — Community Guild (in agentic-actors-guild repo)
- [ ] Audition CI: GitHub Action running a stdlib validator (card.json schema, required SOUL sections, audition transcript present, free-model check per bylaw 3)
- [ ] CONTRIBUTING.md audition walkthrough + issue templates; semver release tags; hire.py `--at <tag>` pinned hiring (change lands in show-template)
- [ ] alumni/ mechanics per bylaw 10
- [ ] Tag guild v1.1.0
