# THE GHOST PROTOCOL — master plan

The full map: what each repo is, what it becomes, and the phases that get us there.
This is the umbrella document; each repo's ROADMAP.md tracks its own slice.

## The repos

| Repo | Job | Today | End state |
|---|---|---|---|
| `ghost-protocol-studio` | **The engine** ("the lot") | Single-file studio + show content mixed together; 4 formats; dice; piper+ffmpeg export | Pure engine: soul loader, stage manager, bus, control plane UI, renderer. No show-specific content. Tagged releases the template pins. |
| `agentic-actors-guild` | **The talent** | 13 charter actors + 13 crew, registry, bylaws | Community registry: audition CI, semver releases, alumni/, growing roster from outside contributors |
| `show-template` | **The kit** | Bible skeleton, hire.py, vendored engine, default crew, ep-001 skeleton | Fully wired: hiring changes what airs; episode pipeline runs end-to-end from a fresh "Use this template" |
| `the-ghost-protocol` *(phase 4, new)* | **The flagship show** | — (show lives inside the engine repo) | Our actual channel's repo, generated from the template, hiring from the Guild. Living documentation: real episodes with full bus logs |

Dependency direction: `show repos → (pin) engine` and `show repos → (hire) guild`. The Guild and engine never depend on each other.

## Invariants (hold across all phases)

1. Engine stays a **single Python file, stdlib only**. The show logic may move server-side, but never behind a pip install.
2. **Free/open models only** as defaults, everywhere (Bifrost/ollama/groq free tier). Guild bylaw 3.
3. **Simulation Mode always works** — every phase must be testable with zero API calls.
4. **Souls are prompts, memory is local, memory never flows upstream.**
5. Renderer stays 100% open source (piper + ffmpeg).
6. Every phase ends with something an episode can use *that night*.

---

## Phase 0 — Foundation ✅ (done)

Engine with 4 formats, human banter, transcript edit/re-roll, Simulation Mode, piper+ffmpeg export, 1000-topic dice, character registry, tribunal witness. Guild chartered (26 members). Template live with hire.py, verified end-to-end from a fresh clone.

---

## Phase 1 — Souls go live (engine reads the cast)

**Goal: hiring changes what airs.** The single feature that makes the kit real.

- Engine looks for `../cast/` and `../crew/` (or `GP_SHOW_DIR`) at startup; parses `card.json` + `SOUL.md` per member.
- New `/api/cast` endpoint; the UI cast panel is *populated from hired souls* (name, color, system prompt from soul, model recommendation, piper voice) instead of the built-in `CASTS`. Built-ins remain as fallback when no cast/ exists (template freshness, backwards compat).
- Format slotting via `card.json` `formats` + `role`: e.g. tribunal needs `interrogator/defender/accused/judge` roles filled; UI shows a casting picker per slot when multiple hires qualify.
- `SOUL.md` → system prompt assembly: Identity + Craft rules + Voice + Hard lines + (Director's standing notes) + a MEMORY.md digest when present.

Repos touched: engine (feature), template (engine bump + README wiring-status update), guild (none).
Acceptance: fresh template checkout → hire 2 actors → they appear in the UI → a Simulation episode runs with their names/colors → editing a SOUL.md changes the next run's prompt.
Estimate: one evening.

---

## Phase 2 — Stage manager + bus (episodes become artifacts)

**Goal: an episode is a replayable directory, not a browser session.**

- Turn orchestration moves from browser JS to the server (`CALLSHEET` becomes real): `POST /api/episode/start` with format/topic/cast → server runs the loop, appends every event to `episodes/ep-NNN/bus.jsonl` (`{ts, from, to, type, ref, body}`).
- UI becomes a bus-tailer (SSE or polling): live feed, human-input turns block the loop until `POST /api/episode/input`.
- Headless mode: `python3 ghost_protocol_studio.py --episode ep-002 --run` for overnight batch generation.
- Replay: load any bus.jsonl back into the UI; transcript.json derived from the bus.
- Episode state machine: `brief → running → awaiting_human → post → rendered`.

Repos touched: engine, template (episode dir conventions already match).
Acceptance: run an episode, kill the browser mid-run, reopen — the feed resumes; replay yesterday's episode; run one headless in Simulation Mode.
Estimate: 1–2 evenings. The biggest single refactor in the plan.

---

## Phase 3 — Crew comes online (one hire at a time)

**Goal: the pipeline from the diagram — each crew agent is a bus participant with its soul as system prompt.** Order chosen so every step improves episodes immediately:

| Order | Agent | What it does on the bus | Why this order |
|---|---|---|---|
| 3.1 | `SPLICE` (editor) | Post-run pass: proposes cuts on the transcript, one-word justifications; user approves per-cut | Instant quality win, zero risk — it only deletes |
| 3.2 | `INKWELL` (head writer) | Pre-run: brief.md → beatsheet.md (beats, planned collisions, callback slots); stage manager feeds beats into turn instructions | Episodes get *structure* |
| 3.3 | `CANON.LOCK` (archivist) | Post-episode: diffs to each cast MEMORY.md; pre-episode: continuity brief to writers | **The moment characters start living.** Memory feedback loop closes |
| 3.4 | `AUTEUR-0` (director) | Mid-run: per-turn retake notes ("again, 30% more contempt"); triggers a re-roll with the note appended | Turns re-roll from a button into a collaborator |
| 3.5 | `GAG.DLL` + `CITE-SEER` | Punch-up pass on beatsheet + fact brief with risk ratings | Writers room complete |
| 3.6 | `EXEC.SYS` + `ROLODEX` | Reads bible + roster → proposes episode slates; casting proposals with chemistry notes | Season planning |
| 3.7 | `FOLEY.WAV` + `GRIP-88` | [beat]/emphasis pass consumed by renderer; scene specs → render themes | Render quality |
| 3.8 | `HYPE.CYCLE` + `TWO-STARS` | Titles/desc/tags/thumbnail text; 200-word pre-render pan with ship/hold | Publish pipeline |

Each sub-phase: soul already exists (hired in template); work = a bus message type + a UI surface + a stage-manager hook.
Acceptance per agent: its output lands on the bus, is visible in the UI, and is actionable (approve/reject), all working in Simulation Mode.
Estimate: 3.1–3.3 one evening each; 3.4–3.8 batchable.

---

## Phase 4 — The flagship split

**Goal: our show becomes a user of our own kit.**

- Create `the-ghost-protocol` from show-template; hire the founding 13; write the real SERIES_BIBLE.md (premise, tone, "Best Line of the Night", season-one slate).
- Migrate show content out of the engine repo: characters.json/assets → already in Guild; episodes we've made → flagship repo.
- Engine repo goes content-neutral; starts tagging releases (`v0.x`); template pins by tag; add a one-line `update-engine.sh` to the template.
- Studio repo's built-in CASTS shrink to a minimal demo pair (so the bare engine still demos).

Repos touched: all four.
Acceptance: episode produced entirely from the flagship repo; engine repo contains no Ghost-Protocol-specific cast; template updates engine by tag.
Estimate: one evening, mostly moving files.

---

## Phase 5 — Director's chair + agent panels

**Goal: the control plane earns the name.**

- Approval gates as first-class bus messages: beat sheet approval, cut approval, rough-cut ship/hold — each renders as a panel in the UI.
- Panel mini-catalog (A2UI-inspired, vanilla JS, ~6 components: card, list, form, buttons, meter, choice); crew agents emit `type:"panel"` bus messages. Keep the envelope loosely A2UI-shaped for a future migration.
- Pipeline kanban view: every episode dir as a card in its state-machine column.
- Soul inspector: view/edit any hired member's soul + memory from the UI.

Repos touched: engine.
Estimate: 1–2 evenings. Do after Phase 3.3 minimum (needs real approvals to render).

---

## Phase 6 — Publish pipeline

**Goal: from rendered mp4 to uploaded episode with minimum clicks.**

- HYPE.CYCLE output → `episodes/ep-NNN/publish/` (title, description with Guild credits per bylaw 9, tags, thumbnail text, poll question, shorts timestamps).
- Publish checklist page in the UI; description includes cast + versions automatically from cast.lock.json.
- Optional later: youtube-upload via API (only if worth the OAuth hassle — manual upload with generated assets is fine indefinitely).

Repos touched: engine, flagship.
Estimate: one evening.

---

## Phase 7 — Community Guild

**Goal: other people's shows, other people's actors.**

- Audition CI on the Guild: GitHub Action validating member packages (schema check on card.json, required SOUL sections, audition transcript present, bylaw 3 model check) — stdlib script, no external CI deps beyond the runner.
- CONTRIBUTING.md with the audition-tape walkthrough; issue templates ("New member audition", "Soul revision").
- Semver release tags on the Guild; hire.py `--at v1.2.0` pinned hiring.
- `alumni/` mechanics per bylaw 10.
- Template polish driven by the first outside user's pain.

Repos touched: guild, template.
Estimate: one evening for CI + docs; ongoing thereafter.

---

## Sequence and gates

```
P1 souls live ─→ P2 stage manager/bus ─→ P3.1–3.3 core crew ─→ P4 flagship split
                                              │                     │
                                              └─→ P5 director's chair
                                                        │
                                              P3.4–3.8 remaining crew
                                                        │
                                                  P6 publish ─→ P7 community
```

Hard gates: P2 requires P1 (souls must load before the server orchestrates them). P4 requires P3.3 (flagship split is only worth it once memory works — that's what makes the show repo precious). P5 requires P3.1+ (needs something to approve). P6/P7 anytime after P4.

Meanwhile, episodes ship every week regardless of phase — the current engine already makes episodes, and no phase is allowed to break that (invariant 6).

## Git strategy

- Engine: feature branches per phase (`p1-souls`, `p2-stage-manager`…), merged to main behind the py_compile + simulation smoke test; tag on phase completion.
- Guild: PRs only, even for us — we follow our own bylaws, audition tapes included.
- Template: tracks engine tags; its own changes via PR.
- Flagship: episodes committed with their full bus logs; the repo is the archive.

## Risks

- **Free-tier rate limits** during multi-agent phases (a full crew episode = many calls): mitigate with per-agent model spread (ollama local for crew, groq for cast), bus-level caching, and batch/headless overnight runs.
- **Scope creep in P2** (the big refactor): the SSE/polling choice and state machine are decided above; anything else waits.
- **A2UI spec churn**: we only mimic the envelope shape; no dependency, no risk.
- **Single-file strain**: the engine file will grow past 100KB by P5. Acceptable; if it truly hurts, the release artifact stays single-file via a build step that concatenates — but only if it truly hurts.
