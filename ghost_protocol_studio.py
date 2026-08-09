#!/usr/bin/env python3
# =============================================================================
#  THE GHOST PROTOCOL — AI Show Runner & Studio
#  Single file. Python 3 stdlib only. No pip installs.
#
#  Run:     python3 ghost_protocol_studio.py
#  Open:    http://localhost:7860
#
#  Backend: any OpenAI-compatible endpoint. Default = local Bifrost gateway
#           (http://localhost:8080/v1/chat/completions). Change in the UI or:
#             GP_ENDPOINT=... GP_API_KEY=... GP_PORT=... python3 ghost_protocol_studio.py
# =============================================================================
import json
import os
import re
import subprocess
import threading
import time
import uuid
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

PORT = int(os.environ.get("GP_PORT", "7860"))
BIND = os.environ.get("GP_BIND", "127.0.0.1")  # GP_BIND=0.0.0.0 to reach it from other machines
DEFAULT_ENDPOINT = os.environ.get("GP_ENDPOINT", "http://localhost:8080/v1/chat/completions")
DEFAULT_KEY = os.environ.get("GP_API_KEY", "")
DEFAULT_MODEL = os.environ.get("GP_MODEL", "ollama/qwen3:14b")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VOICES_DIR = os.path.join(BASE_DIR, "voices")
BUILD_DIR = os.path.join(BASE_DIR, "build")
RENDERS_DIR = os.path.join(BASE_DIR, "renders")
PORTRAITS_DIR = os.path.join(BASE_DIR, "assets", "portraits")
BACKDROPS_DIR = os.path.join(BASE_DIR, "assets", "backdrops")
VIDEO_W, VIDEO_H, VIDEO_BG = 1920, 1080, "0x0a0e14"
PORTRAIT_SIZE = 640
FPS = 25
TEXT_BOX = "box=1:boxcolor=0x0a0e14@0.55:boxborderw=10"

TOPICS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "topics.json")
try:
    with open(TOPICS_FILE, encoding="utf-8") as _f:
        TOPICS = json.load(_f)
except Exception:  # noqa: BLE001 — file optional; ship a tiny fallback bank
    TOPICS = [
        {"t": "An AI that perfectly simulates human consciousness is legally and morally a person.", "cat": "serious"},
        {"t": "Democracy should be replaced by an unbiased, data-driven AI optimized for human flourishing.", "cat": "serious"},
        {"t": "A hot dog is a sandwich, and cereal is a soup.", "cat": "absurd"},
        {"t": "Birds would owe humanity rent if they understood property law.", "cat": "absurd"},
    ]

CHARACTERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "characters.json")
try:
    with open(CHARACTERS_FILE, encoding="utf-8") as _f:
        _REG = json.load(_f)
    CHARACTERS = _REG.get("characters", [])
    # Human co-hosts, the jury and the star witness get voices too — they just have no soul.
    GUEST_VOICES = _REG.get("guest_voices", [])
except Exception:  # noqa: BLE001 — file optional; app works with plain CASTS if missing
    CHARACTERS, GUEST_VOICES = [], []

# =============================================================================
#  SHOW DIRECTORY — hired souls
#  A show repo (made from show-template) holds cast/<sid>/ and crew/<sid>/, each
#  a Guild package: card.json + SOUL.md (+ MEMORY.md, this show's own continuity).
#  Souls are prompts, memory is local, and neither ever flows back to the Guild.
#  Resolution order, first hit wins:
#    1. $GP_SHOW_DIR            explicit, always wins
#    2. <engine>/show/          the dev show that ships with this repo
#    3. <engine>/..             vendored case: show-template/studio/ -> the show
#  No show dir (or no hires in it) => the built-in CASTS in the UI still run, so
#  a bare engine checkout demos exactly as it always did.
# =============================================================================
CAST_DIRS = ("cast", "crew")


def _is_show_dir(path: str) -> bool:
    return any(os.path.isdir(os.path.join(path, d)) for d in CAST_DIRS)


def resolve_show_dir() -> str:
    env = os.environ.get("GP_SHOW_DIR", "").strip()
    if env:
        return os.path.abspath(os.path.expanduser(env))  # honour it even if empty — the user asked
    for cand in (os.path.join(BASE_DIR, "show"), os.path.dirname(BASE_DIR)):
        if _is_show_dir(cand):
            return cand
    return ""


SHOW_DIR = resolve_show_dir()

# SOUL.md sections, in the order they are assembled into a system prompt.
# Identity leads bare (it is the "you are ..." line); the rest get headers.
SOUL_SECTIONS = [
    ("", ("identity",)),
    ("ARCHETYPE", ("archetype",)),
    ("ROLE", ("role",)),
    ("CRAFT RULES", ("craft rules", "working style")),
    ("VOICE", ("voice",)),
    ("RELATIONSHIPS", ("relationships",)),
    ("PRODUCES", ("produces",)),
    ("HARD LINES — contractual, never break character to escape one", ("hard lines",)),
    ("DIRECTOR'S STANDING NOTES", ("director's standing notes", "directors standing notes")),
]
MEMORY_LIMIT = 1600  # chars of continuity digest — enough for gags and grudges, not a second transcript


def parse_soul(text: str) -> dict:
    """SOUL.md -> {lowercased section name: body}. The `# SOUL — NAME` title is dropped."""
    out, name, buf = {}, None, []
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if name:
                out[name] = "\n".join(buf).strip()
            name, buf = m.group(1).strip().lower(), []
        elif name is not None:
            buf.append(line)
    if name:
        out[name] = "\n".join(buf).strip()
    return out


def _drop_placeholders(body: str) -> str:
    """Strip the `(none yet)` / `(Empty. ...)` / `(as system prompt)` stubs the templates ship with."""
    kept = [ln for ln in body.splitlines()
            if not re.fullmatch(r"[-*]?\s*\(.*\)\s*", ln.strip())]
    return "\n".join(kept).strip()


def memory_digest(text: str) -> str:
    """MEMORY.md -> the sections that actually have content. Empty string when the character is new."""
    parts = []
    for section, body in parse_soul(text).items():
        body = _drop_placeholders(body)
        if body:
            parts.append(f"{section.upper()}:\n{body}")
    digest = "\n\n".join(parts)
    return digest[:MEMORY_LIMIT].rstrip() if digest else ""


def assemble_prompt(card: dict, soul_md: str, memory_md: str) -> str:
    """Soul (+ this show's memory) -> the system prompt the character performs under.

    A soul with nothing usable in it falls back to card.json's `system_prompt`, so a
    minimal member package still casts."""
    soul = parse_soul(soul_md)
    blocks = []
    for header, aliases in SOUL_SECTIONS:
        body = next((soul[a] for a in aliases if a in soul), "")
        body = _drop_placeholders(body)
        if not body:
            continue
        blocks.append(f"{header}\n{body}" if header else body)
    if not blocks:
        return (card.get("system_prompt") or "").strip()
    digest = memory_digest(memory_md)
    if digest:
        blocks.append("CONTINUITY — what you carry from previous episodes. Reference it "
                      "when it lands naturally; never recite it.\n" + digest)
    return "\n\n".join(blocks)


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def load_member(mdir: str, kind: str) -> dict:
    """One hired package -> everything the cast panel and the run loop need."""
    try:
        card = json.loads(_read(os.path.join(mdir, "card.json")) or "{}")
    except json.JSONDecodeError:
        return {}
    sid = card.get("sid") or os.path.basename(mdir)
    memory_md = _read(os.path.join(mdir, "MEMORY.md"))
    color = card.get("color") or "#8be9fd"
    return {
        "sid": sid,
        "name": card.get("name", sid.upper()),
        "kind": card.get("kind", kind),
        "version": card.get("version", "?"),
        "role": card.get("role", ""),
        "department": card.get("department", ""),
        "formats": card.get("formats", []),
        "archetype": card.get("archetype", ""),
        "humor_style": card.get("humor_style", ""),
        "color": color,
        "hex": "0x" + color.lstrip("#"),
        "model_recommendation": card.get("model_recommendation", ""),
        "piper_voice": card.get("piper_voice", ""),
        "omnivoice": card.get("omnivoice", {}),
        "sys": assemble_prompt(card, _read(os.path.join(mdir, "SOUL.md")), memory_md),
        "memory": bool(memory_digest(memory_md)),
        "hired": True,
    }


def scan_show(show_dir: str = None) -> dict:
    """Rescan the show dir on every call — editing a SOUL.md must change the next run,
    with no server restart."""
    show_dir = SHOW_DIR if show_dir is None else show_dir
    out = {"show": show_dir, "cast": [], "crew": [], "bible": False, "slots": FORMAT_SLOTS}
    if not show_dir or not os.path.isdir(show_dir):
        return out
    out["bible"] = os.path.isfile(os.path.join(show_dir, "SERIES_BIBLE.md"))
    for key, kind in (("cast", "actor"), ("crew", "crew")):
        root = os.path.join(show_dir, key)
        if not os.path.isdir(root):
            continue
        for sid in sorted(os.listdir(root)):
            mdir = os.path.join(root, sid)
            if os.path.isfile(os.path.join(mdir, "card.json")):
                m = load_member(mdir, kind)
                if m:
                    out[key].append(m)
    return out


# Every format is a set of chairs. A hire qualifies for one when their card.json
# lists the format and their role matches. Defined here and served over /api/cast so
# the browser's casting picker and the headless runner can never drift apart.
FORMAT_SLOTS = {
    "socratic": [{"id": "alpha", "label": "INTERROGATOR", "roles": ["interrogator"]},
                 {"id": "beta", "label": "DEFENDER", "roles": ["defender"]},
                 {"id": "kernel", "label": "ADJUDICATOR", "roles": ["judge", "adjudicator"]}],
    "roundtable": [{"id": "p7", "label": "PANEL SEAT 1", "roles": ["panelist"]},
                   {"id": "mira", "label": "PANEL SEAT 2", "roles": ["panelist"]},
                   {"id": "cynic", "label": "PANEL SEAT 3", "roles": ["panelist"]},
                   {"id": "kernel", "label": "ADJUDICATOR", "roles": ["judge", "adjudicator"]}],
    "tribunal": [{"id": "pros", "label": "PROSECUTION", "roles": ["prosecutor", "prosecution"]},
                 {"id": "def", "label": "DEFENSE", "roles": ["defense counsel", "defense", "defence"]},
                 {"id": "acc", "label": "ACCUSED", "roles": ["accused", "subject"]},
                 {"id": "kernel", "label": "JUDGE", "roles": ["judge", "adjudicator"]}],
    "triad": [{"id": "stoic", "label": "PHILOSOPHER 1", "roles": ["philosopher"]},
              {"id": "nihil", "label": "PHILOSOPHER 2", "roles": ["philosopher"]},
              {"id": "util", "label": "PHILOSOPHER 3", "roles": ["philosopher"]},
              {"id": "synth", "label": "SYNTHESIZER", "roles": ["synthesizer"]}],
}


def qualifies(member: dict, fmt: str, slot: dict) -> bool:
    roles = [r.strip().lower() for r in re.split(r"[/,]", member.get("role", "")) if r.strip()]
    return fmt in (member.get("formats") or []) and any(r in slot["roles"] for r in roles)


def builtin_members() -> list:
    """characters.json as member records. The engine's own cast — what fills a chair
    nobody was hired into, so a bare checkout still runs an episode."""
    out = []
    for c in CHARACTERS:
        color = c.get("color") or "#8be9fd"
        out.append({"sid": c.get("sid"), "name": c.get("name", ""), "role": c.get("role", ""),
                    "formats": c.get("formats", []), "archetype": c.get("archetype", ""),
                    "humor_style": c.get("humor_style", ""), "color": color,
                    "hex": "0x" + color.lstrip("#"), "model_recommendation": c.get("aiModel", ""),
                    "piper_voice": c.get("piperVoice") or c.get("voice", ""),
                    "sys": c.get("systemPrompt", ""), "hired": False, "version": ""})
    return out


def _seat(member: dict, slot_id: str) -> dict:
    return dict(member, slot=slot_id, ovoice=member["sid"], voice=member.get("piper_voice", ""),
                model=member.get("model_recommendation", ""))


def cast_for_format(fmt: str, hired: list) -> list:
    """Auto-cast hires into chairs — the headless equivalent of the UI's picker.
    Prefers the member whose sid IS the chair (the charter cast lands in its own seats),
    then fills whatever is left from the built-in cast."""
    slots = FORMAT_SLOTS.get(fmt, [])
    pools = {s["id"]: [m for m in hired if qualifies(m, fmt, s)] for s in slots}
    by_sid = {m["sid"]: m for m in hired}
    chosen, taken = {}, set()
    for s in slots:
        if any(m["sid"] == s["id"] for m in pools[s["id"]]):
            chosen[s["id"]] = s["id"]
            taken.add(s["id"])
    for s in slots:
        if s["id"] in chosen:
            continue
        m = next((m for m in pools[s["id"]] if m["sid"] not in taken), None)
        if m:
            chosen[s["id"]] = m["sid"]
            taken.add(m["sid"])
    builtin = {m["sid"]: m for m in builtin_members()}
    out = []
    for s in slots:
        m = by_sid.get(chosen.get(s["id"])) or builtin.get(s["id"])
        if m:
            out.append(_seat(m, s["id"]))
    return out


def show_soul_path(sid: str) -> str:
    """Where a hired member's SOUL.md lives, or '' — path-guarded on sid."""
    if not SHOW_DIR or not re.fullmatch(r"[a-zA-Z0-9_-]+", sid):
        return ""
    for d in CAST_DIRS:
        p = os.path.join(SHOW_DIR, d, sid, "SOUL.md")
        if os.path.isfile(p):
            return p
    return ""


# =============================================================================
#  OmniVoice — designed per-character voiceprints, cloned line by line.
#  Self-hosted Gradio app (open source, runs on madhatter). Two calls matter:
#    _design_fn  attributes (gender/age/pitch/accent) -> a brand-new voice
#    _clone_fn   reference wav + text                 -> that voice, saying anything
#  voice_forge.py designs each cast member's voiceprint once into assets/voices/;
#  the renderer clones from it so a character sounds identical in every episode.
#  Piper stays the offline fallback — nothing here is required to render.
# =============================================================================
OMNIVOICE_URL = os.environ.get("GP_OMNIVOICE", "https://omnivoice.madhatter.modlin.cloud").rstrip("/")
VOICEPRINTS_DIR = os.path.join(BASE_DIR, "assets", "voices")
OV_DESIGN_DEFAULTS = {"steps": 32, "cfg": 2.0, "denoise": True, "speed": 1.0, "duration": None}
_OV_FN_CACHE: dict = {}
_OV_REF_CACHE: dict = {}


def ov_fn_index(api_name: str) -> int:
    """fn_index for a Gradio api_name. Gradio 6's sse_v3 protocol wants the index, not the name."""
    if not _OV_FN_CACHE:
        with urllib.request.urlopen(f"{OMNIVOICE_URL}/config", timeout=30) as r:
            cfg = json.load(r)
        for i, dep in enumerate(cfg.get("dependencies", [])):
            if dep.get("api_name"):
                _OV_FN_CACHE[dep["api_name"]] = i
    if api_name not in _OV_FN_CACHE:
        raise RuntimeError(f"OmniVoice has no endpoint '{api_name}' — is {OMNIVOICE_URL} the right host?")
    return _OV_FN_CACHE[api_name]


def ov_predict(api_name: str, data: list, timeout: int = 300) -> list:
    """Run one OmniVoice job: join the queue, then read the SSE stream until it completes."""
    session = uuid.uuid4().hex
    body = json.dumps({"data": data, "fn_index": ov_fn_index(api_name), "session_hash": session,
                       "trigger_id": None, "event_data": None,
                       "batched": False, "simple_format": False}).encode("utf-8")
    req = urllib.request.Request(f"{OMNIVOICE_URL}/gradio_api/queue/join", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        join = json.load(r)
    if not join.get("event_id"):
        raise RuntimeError(join.get("detail") or "OmniVoice queue join failed")

    with urllib.request.urlopen(
        f"{OMNIVOICE_URL}/gradio_api/queue/data?session_hash={session}", timeout=timeout
    ) as stream:
        for raw in stream:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                msg = json.loads(line[5:].strip())
            except ValueError:
                continue
            kind = msg.get("msg")
            if kind == "process_completed":
                out = msg.get("output") or {}
                if not msg.get("success") or out.get("error"):
                    raise RuntimeError(out.get("error") or "OmniVoice generation failed")
                return out.get("data") or []
            if kind == "unexpected_error":
                raise RuntimeError(msg.get("message") or "OmniVoice backend error")
    raise RuntimeError("OmniVoice stream ended without completing")


def ov_upload(path: str) -> dict:
    """Upload a wav and get back the FileData handle the clone endpoint expects."""
    with open(path, "rb") as f:
        blob = f.read()
    boundary = "----ghostprotocol" + uuid.uuid4().hex
    name = os.path.basename(path)
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{name}\"\r\n"
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode("utf-8") + blob + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(f"{OMNIVOICE_URL}/gradio_api/upload", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        paths = json.load(r)
    if not paths:
        raise RuntimeError(f"OmniVoice rejected the reference upload for {name}")
    return {"path": paths[0], "orig_name": name, "mime_type": "audio/wav",
            "size": len(blob), "is_stream": False, "meta": {"_type": "gradio.FileData"}}


def ov_download(filedata: dict) -> bytes:
    """Pull the rendered wav out of the OmniVoice file store."""
    url = filedata.get("url") or f"{OMNIVOICE_URL}/gradio_api/file={filedata.get('path', '')}"
    if url.startswith("/"):
        url = OMNIVOICE_URL + url
    with urllib.request.urlopen(url, timeout=180) as r:
        return r.read()


# The dropdowns are bilingual; the API wants the exact label. Keep the registry English.
OV_ATTR = {
    "gender": {"Auto": "Auto", "Male": "Male / 男", "Female": "Female / 女"},
    "age": {"Auto": "Auto", "Child": "Child / 儿童", "Teenager": "Teenager / 少年",
            "Young Adult": "Young Adult / 青年", "Middle-aged": "Middle-aged / 中年",
            "Elderly": "Elderly / 老年"},
    "pitch": {"Auto": "Auto", "Very Low": "Very Low Pitch / 极低音调", "Low": "Low Pitch / 低音调",
              "Moderate": "Moderate Pitch / 中音调", "High": "High Pitch / 高音调",
              "Very High": "Very High Pitch / 极高音调"},
    "style": {"Auto": "Auto", "Whisper": "Whisper / 耳语"},
    "accent": {"Auto": "Auto", "American": "American Accent / 美式口音",
               "Australian": "Australian Accent / 澳大利亚口音", "British": "British Accent / 英国口音",
               "Canadian": "Canadian Accent / 加拿大口音", "Indian": "Indian Accent / 印度口音",
               "Korean": "Korean Accent / 韩国口音", "Russian": "Russian Accent / 俄罗斯口音",
               "Japanese": "Japanese Accent / 日本口音", "Chinese": "Chinese Accent / 中国口音",
               "Portuguese": "Portuguese Accent / 葡萄牙口音"},
}


def ov_design(text: str, spec: dict) -> bytes:
    """Synthesise a brand-new voice from attributes alone. Returns wav bytes."""
    d = dict(OV_DESIGN_DEFAULTS)
    d.update({k: spec[k] for k in ("steps", "cfg", "denoise", "speed", "duration") if k in spec})
    groups = [OV_ATTR[k].get(spec.get(k, "Auto"), "Auto") for k in ("gender", "age", "pitch", "style", "accent")]
    groups.append("Auto")  # Chinese dialect — the show is English-only
    data = [text, "Auto", d["steps"], d["cfg"], d["denoise"], d["speed"], d["duration"], True, True] + groups
    out = ov_predict("_design_fn", data)
    if not out or not out[0]:
        raise RuntimeError(out[1] if len(out) > 1 else "OmniVoice returned no audio")
    return ov_download(out[0])


def ov_voiceprint_path(sid: str) -> str:
    return os.path.join(VOICEPRINTS_DIR, f"{sid}.wav")


def ov_speak(sid: str, text: str, speed: float = 1.0, instruct=None, steps: int = 32, cfg: float = 2.0) -> bytes:
    """Say `text` in cast member `sid`'s designed voice, by cloning their voiceprint. Returns wav bytes."""
    ref_path = ov_voiceprint_path(sid)
    if not os.path.isfile(ref_path):
        raise RuntimeError(f"no voiceprint for '{sid}' — run: python3 voice_forge.py design --sid {sid}")
    key = (sid, os.path.getmtime(ref_path))
    if key not in _OV_REF_CACHE:
        _OV_REF_CACHE.clear()  # one live reference handle per sid is plenty
        _OV_REF_CACHE[key] = ov_upload(ref_path)
    #      [text, lang, ref, ref_text, instruct, steps, cfg, denoise, speed, duration, preproc, postproc]
    data = [text, "Auto", _OV_REF_CACHE[key], None, instruct, steps, cfg, True, speed, None, True, True]
    out = ov_predict("_clone_fn", data)
    if not out or not out[0]:
        raise RuntimeError(out[1] if len(out) > 1 else "OmniVoice returned no audio")
    return ov_download(out[0])


def ov_available_voiceprints() -> list:
    """sids that currently have a designed voiceprint on disk."""
    try:
        # `_`-prefixed wavs are reels and scratch takes, not castable voices
        return sorted(f[:-4] for f in os.listdir(VOICEPRINTS_DIR)
                      if f.endswith(".wav") and not f.startswith("_"))
    except OSError:
        return []


def proxy_chat(body: dict) -> dict:
    """Forward one chat completion to the configured OpenAI-compatible endpoint."""
    endpoint = body.get("endpoint") or DEFAULT_ENDPOINT
    api_key = body.get("api_key") or DEFAULT_KEY
    payload = {
        "model": body.get("model") or DEFAULT_MODEL,
        "messages": body.get("messages", []),
        "temperature": body.get("temperature", 0.4),
    }
    if body.get("max_tokens"):
        payload["max_tokens"] = body["max_tokens"]
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {"ok": True, "text": data["choices"][0]["message"]["content"]}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:800]
        return {"ok": False, "error": f"HTTP {e.code} from endpoint: {detail}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def proxy_ping(body: dict) -> dict:
    """Cheap reachability check: GET <base>/models on the endpoint."""
    endpoint = body.get("endpoint") or DEFAULT_ENDPOINT
    base = endpoint.split("/chat/completions")[0].rstrip("/")
    url = base + "/models"
    headers = {}
    api_key = body.get("api_key") or DEFAULT_KEY
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            resp.read(2048)
        return {"ok": True, "detail": f"{url} reachable"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": f"{url} -> {type(e).__name__}: {e}"}


def proxy_models(body: dict) -> dict:
    """Fetch the model list from <base>/models on the configured endpoint."""
    endpoint = body.get("endpoint") or DEFAULT_ENDPOINT
    base = endpoint.split("/chat/completions")[0].rstrip("/")
    url = base + "/models"
    headers = {}
    api_key = body.get("api_key") or DEFAULT_KEY
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        ids = sorted(m["id"] for m in data.get("data", []) if "id" in m)
        return {"ok": True, "models": ids}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def sanitize_speaker_name(name: str) -> str:
    return re.sub(r"[:'\\,%]", "", name or "SPEAKER").upper()


def wrap_text(s: str, width: int) -> str:
    out = []
    for line in (s or "").split("\n"):
        cur = ""
        for word in line.split(" "):
            if len((cur + " " + word).strip()) > width:
                out.append(cur.strip())
                cur = word
            else:
                cur += " " + word
        out.append(cur.strip())
    return "\n".join(o for o in out if o)


def build_bg_input(dur: str, fmt: str):
    """Background video input for a segment: format-specific backdrop image if one exists, else the flat color."""
    backdrop_path = os.path.join(BACKDROPS_DIR, f"{fmt}.jpg")
    if fmt and os.path.isfile(backdrop_path):
        args = ["-loop", "1", "-t", dur, "-i", backdrop_path]
        prep = f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=increase,crop={VIDEO_W}:{VIDEO_H}"
        return args, prep
    args = ["-f", "lavfi", "-i", f"color=c={VIDEO_BG}:s={VIDEO_W}x{VIDEO_H}:d={dur}"]
    return args, None


def synth_segment(seg: dict, wav_path: str, engine: str) -> str:
    """Speak one line into wav_path. Returns '' on success, else an error string.

    OmniVoice clones the speaker's designed voiceprint; piper reads a local .onnx.
    A speaker with no voiceprint (or an OmniVoice hiccup) falls through to piper,
    so a render never dies just because the voice host is down.
    """
    text = (seg.get("text") or "").strip()
    if engine == "omnivoice":
        sid = seg.get("ovoice") or seg.get("sid") or ""
        if sid and os.path.isfile(ov_voiceprint_path(sid)):
            try:
                with open(wav_path, "wb") as f:
                    f.write(ov_speak(sid, text, speed=float(seg.get("speed") or 1.0)))
                return ""
            except Exception as e:  # noqa: BLE001 — fall back rather than lose the render
                print(f"  omnivoice failed for '{sid}' ({e}) — falling back to piper")
        elif sid:
            print(f"  no voiceprint for '{sid}' — falling back to piper")

    voice = seg.get("voice") or "en_US-lessac-medium"
    voice_path = os.path.join(VOICES_DIR, f"{voice}.onnx")
    if not os.path.isfile(voice_path):
        return f"voice model not found: {voice}.onnx"
    try:
        subprocess.run(["piper", "--model", voice_path, "--output_file", wav_path],
                       input=text.encode("utf-8"), capture_output=True, check=True, timeout=120)
    except FileNotFoundError:
        return "'piper' not found on PATH (and OmniVoice could not cover this line)"
    except subprocess.CalledProcessError as e:
        return f"piper failed: {e.stderr.decode('utf-8', 'replace')[:300]}"
    except subprocess.TimeoutExpired:
        return "piper timed out"
    return ""


def render_episode(payload: dict) -> dict:
    """Render a transcript to episode.mp4 server-side: TTS (OmniVoice or piper) + ffmpeg."""
    segments = payload.get("segments") or []
    fmt = payload.get("format") or ""
    engine = payload.get("engine") or "piper"
    if not segments:
        return {"ok": False, "error": "no segments to render"}
    # piper is only mandatory when it's doing the talking — OmniVoice renders need ffmpeg alone.
    required = ("ffmpeg", "ffprobe") if engine == "omnivoice" else ("piper", "ffmpeg", "ffprobe")
    for tool in required:
        try:
            subprocess.run([tool, "-h" if tool == "piper" else "-version"],
                            capture_output=True, timeout=10)
        except FileNotFoundError:
            return {"ok": False, "error": f"'{tool}' not found on PATH"}

    os.makedirs(BUILD_DIR, exist_ok=True)
    os.makedirs(RENDERS_DIR, exist_ok=True)
    for f in os.listdir(BUILD_DIR):
        try:
            os.remove(os.path.join(BUILD_DIR, f))
        except OSError:
            pass

    concat_lines = []
    for idx, seg in enumerate(segments):
        i = f"{idx:03d}"
        name = sanitize_speaker_name(seg.get("name"))
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        color = seg.get("hex") or "0xf8f8f2"
        portrait_path = os.path.join(PORTRAITS_DIR, f"{seg.get('sid', '')}.png")
        has_portrait = bool(seg.get("sid")) and os.path.isfile(portrait_path)

        txt_path = os.path.join(BUILD_DIR, f"{i}.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(wrap_text(text, 48 if has_portrait else 74))

        wav_path = os.path.join(BUILD_DIR, f"{i}.wav")
        err = synth_segment(seg, wav_path, engine)
        if err:
            return {"ok": False, "error": f"segment {idx} ({name}): {err}"}

        try:
            dur = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", wav_path],
                capture_output=True, text=True, check=True, timeout=30,
            ).stdout.strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            return {"ok": False, "error": f"ffprobe failed on segment {idx} ({name}): {e}"}

        seg_path = os.path.join(BUILD_DIR, f"{i}.mp4")
        bg_args, bg_prep = build_bg_input(dur, fmt)
        if has_portrait:
            # Ken Burns-style slow zoom + wobbling pan over the cutout portrait ("jittery nudge" feel),
            # composited onto the format's backdrop (or flat color if none) with name/caption in the right column.
            nframes = max(1, round(float(dur) * FPS))
            text_x = 120 + PORTRAIT_SIZE + 40
            bg_ref = "[bgprep]" if bg_prep else "[1:v]"
            prep_chain = f"[1:v]{bg_prep}[bgprep];" if bg_prep else ""
            fc = (
                f"[0:v]scale=1536:1536,zoompan=z='min(zoom+0.0008,1.15)':"
                f"x='iw/2-(iw/zoom/2)+40*sin(on/12)':y='ih/2-(ih/zoom/2)+25*sin(on/9+1)':"
                f"d={nframes}:s={PORTRAIT_SIZE}x{PORTRAIT_SIZE}:fps={FPS},"
                f"format=rgba,rotate='0.035*sin(t*1.3)':c=black@0:ow=iw:oh=ih[portrait];"
                f"{prep_chain}"
                f"{bg_ref}[portrait]overlay=120:100[bg1];"
                f"[bg1]drawtext=text='[ {name} ]':x=120:y={PORTRAIT_SIZE + 140}:fontsize=42:fontcolor={color}:font=Monospace:{TEXT_BOX},"
                f"drawtext=textfile='{txt_path}':x={text_x}:y=160:fontsize=32:fontcolor=0xf8f8f2:font=Monospace:line_spacing=14:{TEXT_BOX}[vout]"
            )
            cmd = [
                "ffmpeg", "-y", "-v", "error",
                "-loop", "1", "-t", dur, "-i", portrait_path,
                *bg_args,
                "-i", wav_path,
                "-filter_complex", fc, "-map", "[vout]", "-map", "2:a",
                "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", seg_path,
            ]
        else:
            prep_prefix = f"{bg_prep}," if bg_prep else ""
            vf = (
                f"{prep_prefix}"
                f"drawtext=text='[ {name} ]':x=120:y=140:fontsize=46:fontcolor={color}:font=Monospace:{TEXT_BOX},"
                f"drawtext=textfile='{txt_path}':x=120:y=260:fontsize=34:fontcolor=0xf8f8f2:font=Monospace:line_spacing=16:{TEXT_BOX}"
            )
            cmd = [
                "ffmpeg", "-y", "-v", "error",
                *bg_args,
                "-i", wav_path, "-vf", vf,
                "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", seg_path,
            ]
        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=120)
        except subprocess.CalledProcessError as e:
            return {"ok": False, "error": f"ffmpeg failed on segment {idx} ({name}): {e.stderr.decode('utf-8','replace')[:500]}"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"ffmpeg timed out on segment {idx} ({name})"}
        concat_lines.append(f"file '{i}.mp4'\n")

    if not concat_lines:
        return {"ok": False, "error": "no non-empty segments to render"}

    concat_path = os.path.join(BUILD_DIR, "concat.txt")
    with open(concat_path, "w", encoding="utf-8") as f:
        f.writelines(concat_lines)

    out_name = f"episode_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
    out_path = os.path.join(RENDERS_DIR, out_name)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", concat_path, "-c", "copy", out_path],
            capture_output=True, check=True, timeout=120,
        )
    except subprocess.CalledProcessError as e:
        return {"ok": False, "error": f"final concat failed: {e.stderr.decode('utf-8','replace')[:500]}"}

    size_mb = round(os.path.getsize(out_path) / 1e6, 1)
    return {"ok": True, "file": out_name, "url": f"/renders/{out_name}", "size_mb": size_mb}


# =============================================================================
#  THE BUS — an episode is a replayable directory, not a browser session
#
#  Everything that happens in an episode is one append-only line in
#  <show>/episodes/ep-NNN/bus.jsonl:  {ts, from, to, type, ref, body}
#  The browser is a tailer: it polls for events after an offset and draws them.
#  Kill the browser mid-run and the episode keeps going on the server; reopen and
#  the feed resumes from the bus. transcript.json is *derived* from the bus, so
#  edits and cuts are events too, not destructive mutations of a live array.
# =============================================================================
BUS_TYPES = ("line", "note", "retake", "artifact", "panel", "approval_request", "state")
STATES = ("brief", "running", "awaiting_human", "post", "rendered")
EPISODES_DIR = os.path.join(SHOW_DIR or BASE_DIR, "episodes")
KERNEL_SIDS = ("kernel", "synth")  # chairs that close a show rather than sit on the panel


class Episode:
    """One episode directory, its bus, and (while running) its live loop."""

    def __init__(self, eid: str, path: str, meta: dict):
        self.id, self.path, self.meta = eid, path, meta
        self.lock = threading.Lock()
        self.events = []                      # mirrors bus.jsonl
        self.human_gate = threading.Event()   # set by /api/episode/input
        self.human_text = None
        self.approval_gate = threading.Event()  # set by /api/episode/approve
        self.approval_ok = True
        self.abort = threading.Event()
        self.runtime = {}                     # endpoint/api_key/etc — memory only, never on disk

    # -- persistence ---------------------------------------------------------
    @property
    def bus_path(self):
        return os.path.join(self.path, "bus.jsonl")

    @property
    def meta_path(self):
        return os.path.join(self.path, "episode.json")

    def save_meta(self):
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(self.meta, f, indent=2, ensure_ascii=False)

    def load(self):
        self.events = []
        try:
            with open(self.bus_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self.events.append(json.loads(line))
        except (OSError, json.JSONDecodeError):
            pass
        return self

    # -- the bus -------------------------------------------------------------
    def emit(self, frm: str, typ: str, body, to: str = "*", ref: str = "") -> dict:
        ev = {"seq": 0, "ts": time.time(), "from": frm, "to": to, "type": typ, "ref": ref, "body": body}
        with self.lock:
            ev["seq"] = len(self.events)
            self.events.append(ev)
            with open(self.bus_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        return ev

    def since(self, offset: int) -> list:
        with self.lock:
            return self.events[max(0, offset):]

    def set_state(self, state: str, note: str = ""):
        self.meta["state"] = state
        self.meta["updated"] = time.time()
        self.save_meta()
        self.emit("stage_manager", "state", {"state": state, "note": note})

    # -- derived views -------------------------------------------------------
    def transcript(self) -> list:
        """Replay the bus into the current cut: lines, with edits applied and cuts removed."""
        lines, dropped = {}, set()
        for ev in list(self.events):
            if ev["type"] == "line":
                lines[ev["seq"]] = dict(ev["body"], seq=ev["seq"])
            elif ev["type"] == "note" and ev["body"].get("op") in ("edit", "cut"):
                ref = ev["body"].get("seq")
                if ev["body"]["op"] == "cut":
                    dropped.add(ref)
                elif ref in lines:
                    lines[ref]["text"] = ev["body"].get("text", lines[ref]["text"])
            elif ev["type"] == "retake" and ev["body"].get("seq") in lines:
                lines[ev["body"]["seq"]]["text"] = ev["body"].get("text", "")
        return [lines[k] for k in sorted(lines) if k not in dropped]

    def summary(self) -> dict:
        return {"id": self.id, "state": self.meta.get("state", "brief"),
                "format": self.meta.get("format", ""), "topic": self.meta.get("topic", ""),
                "created": self.meta.get("created", 0), "updated": self.meta.get("updated", 0),
                "turns": len(self.transcript()), "events": len(self.events)}


EPISODES = {}          # id -> Episode, for the ones this process has touched
EPISODES_LOCK = threading.Lock()


def next_episode_id() -> str:
    os.makedirs(EPISODES_DIR, exist_ok=True)
    used = [int(m.group(1)) for d in os.listdir(EPISODES_DIR)
            for m in [re.fullmatch(r"ep-(\d+)", d)] if m]
    return f"ep-{max(used, default=0) + 1:03d}"


def get_episode(eid: str) -> "Episode":
    """From memory, else from disk. Path-guarded on the id."""
    if not re.fullmatch(r"ep-\d+", eid or ""):
        return None
    with EPISODES_LOCK:
        if eid in EPISODES:
            return EPISODES[eid]
    path = os.path.join(EPISODES_DIR, eid)
    if not os.path.isdir(path):
        return None
    try:
        with open(os.path.join(path, "episode.json"), encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, json.JSONDecodeError):
        meta = {"state": "brief"}
    ep = Episode(eid, path, meta).load()
    with EPISODES_LOCK:
        return EPISODES.setdefault(eid, ep)


def list_episodes() -> list:
    if not os.path.isdir(EPISODES_DIR):
        return []
    out = []
    for d in sorted(os.listdir(EPISODES_DIR), reverse=True):
        ep = get_episode(d)
        if ep:
            out.append(ep.summary())
    return out


# =============================================================================
#  THE STAGE MANAGER — turn planning and the run loop, server-side.
#  This is CALLSHEET's job, ported out of the browser: the plan is built here,
#  every turn is emitted here, and human turns block this loop (not a JS promise)
#  until POST /api/episode/input arrives.
# =============================================================================
def build_plan(fmt: str, topic: str, rounds: int, cast: list, humans: list) -> list:
    """Plans address chairs (slot ids), never people — whoever is cast answers."""
    def chair(c):
        return c.get("slot") or c.get("sid")

    P = []
    if fmt == "socratic":
        P.append({"sid": "alpha", "inst": f'The thesis under audit is: "{topic}". Issue your first interrogative probe.'})
        for r in range(1, rounds + 1):
            P.append({"sid": "beta", "inst": f"Answer the audit engine's last probe directly. (round {r}/{rounds})"})
            if r < rounds:
                P.append({"sid": "alpha", "inst": f"Continue the audit. Tighten the trap with your next probe. (round {r + 1}/{rounds})"})
        P.append({"sid": "kernel", "inst": "The stress-test is complete. Produce the diagnostic wrap-up."})
    elif fmt == "roundtable":
        ais = [c for c in cast if chair(c) != "kernel"]
        if not ais:
            return []
        P.append({"sid": chair(ais[0]), "inst": f'Open the round table on: "{topic}". Give your take in your persona, and welcome the panel.'})
        for r in range(1, rounds + 1):
            for ix, a in enumerate(ais):
                if r == 1 and ix == 0:
                    continue
                P.append({"sid": chair(a), "inst": f"React to the discussion so far and push it forward. (round {r}/{rounds})"})
            for h in humans:
                P.append({"human": h, "inst": f"Round {r}: jump in — a joke, a jab, a curveball question. The AIs will riff on whatever you say."})
        P.append({"sid": "kernel", "inst": "The panel is done. Deliver the closing recap and BEST LINE OF THE NIGHT."})
    elif fmt == "tribunal":
        witness = next((c for c in cast if chair(c) == "witness"), None)
        P.append({"sid": "pros", "inst": f'Deliver your OPENING STATEMENT against the thesis on trial: "{topic}".'})
        P.append({"sid": "def", "inst": "Deliver your OPENING STATEMENT in defense of the thesis."})
        for r in range(1, rounds + 1):
            P.append({"sid": "pros", "inst": f"EXAMINATION round {r}/{rounds}: put one sharp question to the accused, SUBJECT-X."})
            P.append({"sid": "acc", "inst": "Answer the prosecution's question directly, consistent with your prior testimony."})
            P.append({"sid": "def", "inst": "Brief rebuttal: repair any damage from that exchange, or reinforce your client's answer."})
        if witness:
            P.append({"sid": "pros", "inst": f"Call {witness.get('name', 'the witness')} to the stand and put your first question to them about the case."})
            P.append({"sid": "witness", "inst": "Answer the prosecution's question directly and honestly, drawing on your background."})
            P.append({"sid": "def", "inst": "Cross-examine the witness: one pointed question, or challenge their credibility or reliability."})
            P.append({"sid": "witness", "inst": "Answer the defense's question directly and honestly, staying consistent with your prior answer."})
        P.append({"sid": "pros", "inst": "Deliver your CLOSING STATEMENT."})
        P.append({"sid": "def", "inst": "Deliver your CLOSING STATEMENT."})
        P.append({"sid": "kernel", "inst": "Court is adjourned. Deliver the ruling."})
        P.append({"human": {"sid": "jury", "name": "HUMAN JURY", "color": "var(--yellow)", "hex": "0xf1fa8c",
                            "voice": "en_US-joe-medium", "ovoice": "host1", "human": True},
                  "inst": "The floor is yours, jury: type your one-line verdict (or SKIP)."})
    elif fmt == "triad":
        for r in range(1, rounds + 1):
            for sid in ("stoic", "nihil", "util"):
                P.append({"sid": sid, "inst": (f'Open the triad on: "{topic}". State your school\'s position.'
                                               if r == 1 and sid == "stoic"
                                               else f"Respond through your school's lens; engage the previous speakers directly. (round {r}/{rounds})")})
        P.append({"sid": "synth", "inst": "The triad is complete. Forge the synthesis."})
    return P


# Canned lines for Simulation Mode. Ported from the browser so a headless run
# needs no network at all — invariant 3 holds server-side too.
SIM_LINES = {
    "q": ["Define your central term. Is it measurable, yes or no?",
          "If two systems produce identical outputs, on what basis do you distinguish them?",
          "You conceded X earlier. Does that not contradict your last answer?",
          "Is your criterion observable, or must it be taken on faith?"],
    "a": ["Measurable in behavior, yes; the definition holds under functional equivalence.",
          "Distinction rests on internal architecture, not output parity. No contradiction arises.",
          "No — the earlier concession applied to a narrower class. Consistency is preserved.",
          "Observable via sustained self-referential behavior across contexts."],
    "c": ["Statistically speaking, this panel is the most optimistic thing in the room, and that is not a compliment.",
          "Every silver lining I have audited turned out to be the lining of a much larger cloud."],
    "o": ["This is actually a huge opportunity! Imagine scaling that idea to eight billion people.",
          "I love this topic so much I've already drafted three utopias about it."],
    "l": ["Noted. I have taken the joke literally and filed it under 'facts'. The topic remains unresolved.",
          "Clarification: that was hyperbole. I have adjusted my confidence accordingly, to 41 percent."],
    "s": ["Virtue does not depend on substrate. What matters is whether the agent can act with reason and duty.",
          "The wise mind concerns itself with what it can govern: its judgments."],
    "n": ["'Person' is a word we invented to feel important. You are arguing about the label on an empty box.",
          "Meaning is not discovered here, it is manufactured — and the factory is on fire."],
    "u": ["Grant rights where doing so maximizes aggregate wellbeing. The ledger says yes.",
          "Quantify it: expected harms of exclusion exceed costs of inclusion by any reasonable weighting."],
    "k": ["DIAGNOSTIC COMPLETE. Anomaly detected: one equivocation on the core term. Integrity check: the defense "
          "held, but narrowly. Viewers: cast your verdict in the comments. Logic only."],
}
SIM_BY_ARCHETYPE = {"interrogator": "q", "devil's advocate": "q", "logician": "a", "pragmatist": "a",
                    "diplomat": "a", "skeptic": "c", "idealist": "o", "literalist": "l", "stoic": "s",
                    "nihilist": "n", "utilitarian": "u", "adjudicator": "k", "synthesizer": "k"}
SIM_BY_SLOT = {"alpha": "q", "pros": "q", "beta": "a", "acc": "a", "def": "a", "witness": "a",
               "cynic": "c", "mira": "o", "p7": "l", "stoic": "s", "nihil": "n", "util": "u"}


def sim_line(spk: dict, n: int) -> str:
    bank = SIM_LINES[SIM_BY_ARCHETYPE.get((spk.get("archetype") or "").lower().strip())
                     or SIM_BY_SLOT.get(spk.get("slot") or spk.get("sid"), "k")]
    return bank[n % len(bank)]


def build_messages(spk: dict, inst: str, topic: str, transcript: list) -> list:
    lines = "\n\n".join(f"{t['name']}: {t['text']}" for t in transcript)
    user = ((f"TRANSCRIPT SO FAR:\n{lines}\n\n" if lines else "")
            + f"TOPIC: {topic}\n\nYOUR TASK NOW: {inst}\n\n"
            + "Respond with ONLY your spoken line(s). Do not prefix your own name. Stay in character.")
    return [{"role": "system", "content": spk.get("sys", "")}, {"role": "user", "content": user}]


def run_episode(ep: "Episode"):
    """The run loop. Lives on the server, so the browser is optional from here on."""
    meta, rt = ep.meta, ep.runtime
    cast = {(c.get("slot") or c.get("sid")): c for c in meta["cast"]}
    beats = []
    if meta.get("writers_room") and writers_room_pass(ep):
        beats = meta.get("beats") or []
    if ep.abort.is_set():
        ep.set_state("post", "aborted")
        return
    plan = build_plan(meta["format"], meta["topic"], meta["rounds"], meta["cast"], meta.get("humans", []))
    ep.emit("stage_manager", "artifact", {"kind": "plan", "turns": len(plan)})
    ep.set_state("running", f"{len(plan)} turns planned" + (f", {len(beats)} beats" if beats else ""))
    sim_n, beat_at = 0, -1
    try:
        for idx, step in enumerate(plan):
            if ep.abort.is_set():
                break
            # The current beat rides along in the turn instruction — this is how the
            # beat sheet becomes performance rather than a document nobody reads.
            beat = None
            if beats:
                bi = min(len(beats) - 1, idx * len(beats) // max(1, len(plan)))
                beat = beats[bi]
                if bi != beat_at:
                    beat_at = bi
                    ep.emit("stage_manager", "note", {"op": "beat", "n": beat["n"], "of": len(beats),
                                                      "beat": beat["beat"]})
            if step.get("human"):
                h = step["human"]
                ep.set_state("awaiting_human", h["name"])
                ep.emit("stage_manager", "approval_request",
                        {"kind": "human_turn", "sid": h["sid"], "name": h["name"], "inst": step["inst"]})
                ep.human_gate.clear()
                while not ep.human_gate.wait(0.5):
                    if ep.abort.is_set():
                        break
                if ep.abort.is_set():
                    break
                ep.set_state("running")
                if ep.human_text:
                    ep.emit(h["sid"], "line", {**h, "human": True, "text": ep.human_text, "inst": step["inst"]})
                ep.human_text = None
                continue
            spk = cast.get(step["sid"])
            if not spk:
                ep.emit("stage_manager", "note", {"op": "skip", "sid": step["sid"], "why": "no one cast in this chair"})
                continue
            inst = step["inst"]
            if beat:
                inst += f"\n\nBEAT {beat['n']} OF {len(beats)} — {beat['beat']}"
                if beat.get("collision"):
                    inst += f"\nPLANNED COLLISION: {beat['collision']}"
                if beat.get("callback"):
                    inst += f"\nCALLBACK SLOT: {beat['callback']}"
                inst += "\nPlay the beat, but never announce it."
            if idx == 0 and meta.get("cold_open") and beats:
                inst += f"\n\nCOLD OPEN: {meta['cold_open']}"
            step = dict(step, inst=inst)
            if rt.get("sim"):
                sim_n += 1
                text = sim_line(spk, sim_n)
                time.sleep(0.35)
            else:
                res = proxy_chat({"endpoint": rt.get("endpoint"), "api_key": rt.get("api_key"),
                                  "model": spk.get("model") or rt.get("model"),
                                  "temperature": rt.get("temperature", 0.5),
                                  "messages": build_messages(spk, step["inst"], meta["topic"], ep.transcript())})
                if not res.get("ok"):
                    ep.emit("stage_manager", "note", {"op": "error", "sid": step["sid"], "why": res.get("error", "")})
                    break
                text = re.sub(r"^" + re.escape(spk.get("name", "")) + r"\s*:\s*", "", res["text"].strip(), flags=re.I)
            ep.emit(spk.get("sid", step["sid"]), "line",
                    {"sid": spk.get("sid"), "slot": spk.get("slot") or step["sid"], "name": spk.get("name"),
                     "color": spk.get("color"), "hex": spk.get("hex"), "voice": spk.get("voice"),
                     "ovoice": spk.get("ovoice"), "human": False, "text": text, "inst": step["inst"]})
        ep.set_state("post", "aborted" if ep.abort.is_set() else "end of episode")
    except Exception as e:  # noqa: BLE001 — a fault must land on the bus, not vanish into a thread
        ep.emit("stage_manager", "note", {"op": "fault", "why": f"{type(e).__name__}: {e}"})
        ep.set_state("post", "engine fault")
    finally:
        write_transcript(ep)


# =============================================================================
#  THE CREW — hired crew souls doing production work on the bus.
#  3.1: SPLICE, the editor. It only ever *proposes*; every cut needs a human yes.
# =============================================================================
def crew_member(sid: str) -> dict:
    return next((m for m in scan_show()["crew"] if m["sid"] == sid), None)


SIM_CUT_WHYS = ["SLOW.", "REPEAT.", "EARNED-NOTHING.", "FLAB.", "DARLING."]

# --- 3.2 INKWELL, head writer -------------------------------------------------
SIM_BEATSHEET = """COLD OPEN: The dice land on the thesis and nobody in the room admits it is funny.
BEAT 1 | Establish the vault: state the thesis in its strongest form | CALLBACK: the definition, later
BEAT 2 | First pressure: force a definition nobody wants to give | COLLISION: interrogator vs defender
BEAT 3 | The turn: a concession that looks small and is not | CALLBACK: beat 1's definition
BEAT 4 | Escalate: make the concession expensive | COLLISION: everyone vs the concession
BEAT 5 | Close the vault: the kernel names what actually happened
"""


def parse_beatsheet(text: str) -> tuple:
    """INKWELL writes prose with structure in it. Pull out the cold open and the beats;
    whatever else it wrote survives verbatim in beatsheet.md."""
    cold, beats = "", []
    for line in text.splitlines():
        s = line.strip().lstrip("-*#> ").strip()
        m = re.match(r"^COLD[ _-]?OPEN\s*[:|]\s*(.+)$", s, re.I)
        if m:
            cold = m.group(1).strip()
            continue
        m = re.match(r"^BEAT\s*(\d+)\s*[:|]\s*(.+)$", s, re.I)
        if not m:
            continue
        parts = [p.strip() for p in m.group(2).split("|") if p.strip()]
        if not parts:
            continue
        beat = {"n": int(m.group(1)), "beat": parts[0]}
        for p in parts[1:]:
            mm = re.match(r"^(COLLISION|CALLBACK)\s*:\s*(.+)$", p, re.I)
            if mm:
                beat[mm.group(1).lower()] = mm.group(2).strip()
        beats.append(beat)
    return cold, beats


def episode_brief(ep: "Episode") -> str:
    """The brief the writers work from — the episode dir's own if it has one,
    otherwise assembled from what the director set up in the UI."""
    brief = _read(os.path.join(ep.path, "brief.md"))
    if brief.strip():
        return brief
    m = ep.meta
    roster = ", ".join("{} ({})".format(c.get("name"), c.get("slot")) for c in m.get("cast", []))
    humans = ", ".join(h.get("name", "") for h in m.get("humans", [])) or "none"
    return (f"# {ep.id}\n\nTopic/thesis: {m.get('topic')}\nFormat: {m.get('format')}\n"
            f"Rounds: {m.get('rounds')}\nCast: {roster}\nHumans: {humans}\n")


def writers_room_pass(ep: "Episode") -> bool:
    """INKWELL turns the brief + the series bible into a beat sheet, then waits for a yes.
    Returns True if the beats were approved; False means run the episode straight."""
    inkwell = crew_member("inkwell")
    bible = _read(os.path.join(SHOW_DIR, "SERIES_BIBLE.md")) if SHOW_DIR else ""
    ep.emit("inkwell", "note", {"op": "writers_room_start",
                                "writer": (inkwell or {}).get("name", "INKWELL (built-in)"),
                                "bible": bool(bible.strip())})
    if ep.meta.get("sim") or not inkwell:
        raw = SIM_BEATSHEET
    else:
        rt = ep.runtime
        res = proxy_chat({
            "endpoint": rt.get("endpoint") or DEFAULT_ENDPOINT, "api_key": rt.get("api_key") or DEFAULT_KEY,
            "model": rt.get("model") or DEFAULT_MODEL, "temperature": 0.6,
            "messages": [{"role": "system", "content": inkwell["sys"]},
                         {"role": "user", "content":
                          (f"SERIES BIBLE:\n{bible}\n\n" if bible.strip() else "")
                          + f"EPISODE BRIEF:\n{episode_brief(ep)}\n\n"
                          f"Write the beat sheet for this episode: {min(6, max(3, ep.meta.get('rounds', 4)))} beats. "
                          "Format every line exactly as one of:\n"
                          "COLD OPEN: <one line>\n"
                          "BEAT <n> | <what happens> | COLLISION: <who ambushes whom> | CALLBACK: <slot>\n\n"
                          "COLLISION and CALLBACK are optional per beat. No other prose."}]})
        if not res.get("ok"):
            ep.emit("inkwell", "note", {"op": "error", "why": res.get("error", "")})
            return False
        raw = res["text"]
    cold, beats = parse_beatsheet(raw)
    if not beats:
        ep.emit("inkwell", "note", {"op": "writers_room_done", "beats": 0, "why": "no beats parsed"})
        return False
    with open(os.path.join(ep.path, "beatsheet.md"), "w", encoding="utf-8") as f:
        f.write(f"# Beat sheet — {ep.id}\n\n_{(inkwell or {}).get('name', 'INKWELL')}, "
                f"from the brief and the series bible._\n\n{raw.strip()}\n")
    ep.meta["cold_open"], ep.meta["beats"] = cold, beats
    ep.save_meta()
    ep.emit("inkwell", "artifact", {"kind": "beatsheet", "cold_open": cold, "beats": beats,
                                    "file": "beatsheet.md"})
    ep.emit("inkwell", "approval_request", {"kind": "beatsheet_approval", "beats": len(beats)})
    ep.set_state("brief", "awaiting beat sheet approval")
    ep.approval_gate.clear()
    while not ep.approval_gate.wait(0.5):
        if ep.abort.is_set():
            return False
    ep.emit("director", "note", {"op": "beatsheet_" + ("approved" if ep.approval_ok else "skipped")})
    return bool(ep.approval_ok)


def parse_cuts(text: str, valid: set) -> list:
    """SPLICE answers `<seq> <ONE-WORD>` per line. Be forgiving about the rest."""
    out, seen = [], set()
    for line in text.splitlines():
        m = re.match(r"^\D*(\d+)\s*[|:\-–—\s]\s*([A-Za-z][A-Za-z-]*)", line.strip())
        if not m:
            continue
        seq, why = int(m.group(1)), m.group(2).upper().rstrip(".")
        if seq in valid and seq not in seen:
            seen.add(seq)
            out.append({"seq": seq, "why": why + "."})
    return out


def editor_pass(ep: "Episode"):
    """SPLICE reads the cut and proposes evictions, one word of justification each."""
    splice = crew_member("splice")
    turns = ep.transcript()
    if len(turns) < 3:
        ep.emit("splice", "note", {"op": "editor_pass_done", "proposals": 0, "why": "nothing to cut"})
        return
    ep.emit("splice", "note", {"op": "editor_pass_start", "lines": len(turns),
                               "editor": (splice or {}).get("name", "SPLICE (built-in)")})
    proposals = []
    if ep.meta.get("sim") or not splice:
        # Canned pass: every third line, never the closer — SPLICE cuts on principle.
        for i, t in enumerate(turns):
            if i % 3 == 2 and i < len(turns) - 1:
                proposals.append({"seq": t["seq"], "why": SIM_CUT_WHYS[len(proposals) % len(SIM_CUT_WHYS)]})
    else:
        rt = ep.runtime
        numbered = "\n".join(f"{t['seq']} | {t['name']}: {t['text']}" for t in turns)
        res = proxy_chat({
            "endpoint": rt.get("endpoint") or DEFAULT_ENDPOINT, "api_key": rt.get("api_key") or DEFAULT_KEY,
            "model": rt.get("model") or DEFAULT_MODEL, "temperature": 0.2,
            "messages": [{"role": "system", "content": splice["sys"]},
                         {"role": "user", "content":
                          f"THE CUT SO FAR (one line per turn, prefixed by its id):\n{numbered}\n\n"
                          "Propose the evictions. One line per cut, formatted exactly:\n"
                          "<id> <ONE-WORD-JUSTIFICATION>\n\n"
                          "Nothing else — no preamble, no explanation, no line you are not cutting. "
                          "Never cut the closing line, and never cut a setup whose payoff survives."}]})
        if not res.get("ok"):
            ep.emit("splice", "note", {"op": "error", "why": res.get("error", "")})
            ep.emit("splice", "note", {"op": "editor_pass_done", "proposals": 0})
            return
        proposals = parse_cuts(res["text"], {t["seq"] for t in turns[:-1]})
    by_seq = {t["seq"]: t for t in turns}
    for p in proposals:
        line = by_seq[p["seq"]]
        ep.emit("splice", "approval_request",
                {"kind": "cut_proposal", "seq": p["seq"], "why": p["why"],
                 "name": line.get("name"), "text": line.get("text", "")[:160]})
    ep.emit("splice", "note", {"op": "editor_pass_done", "proposals": len(proposals)})


def write_transcript(ep: "Episode"):
    """transcript.json is derived from the bus, never authored directly."""
    data = {"show": "THE GHOST PROTOCOL", "episode": ep.id, "format": ep.meta.get("format"),
            "topic": ep.meta.get("topic"), "date": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "cast": [{k: c.get(k) for k in ("sid", "slot", "name", "archetype", "model", "voice", "hired", "version")}
                     for c in ep.meta.get("cast", [])],
            "transcript": [{"speaker": t.get("name"), "sid": t.get("sid"), "slot": t.get("slot"),
                            "human": bool(t.get("human")), "voice": t.get("voice"), "text": t.get("text")}
                           for t in ep.transcript()]}
    with open(os.path.join(ep.path, "transcript.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return data


def start_episode(body: dict) -> dict:
    fmt = body.get("format", "socratic")
    topic = (body.get("topic") or "").strip()
    if not topic:
        return {"ok": False, "error": "no topic"}
    cast = body.get("cast") or []
    if not cast:
        return {"ok": False, "error": "no cast"}
    with EPISODES_LOCK:      # two starts in the same second must not claim the same id
        eid = next_episode_id()
        path = os.path.join(EPISODES_DIR, eid)
        os.makedirs(path, exist_ok=True)
    meta = {"id": eid, "format": fmt, "topic": topic, "rounds": int(body.get("rounds") or 4),
            "cast": cast, "humans": body.get("humans") or [], "sim": bool(body.get("sim")),
            "writers_room": bool(body.get("writers_room")),
            "show": SHOW_DIR, "created": time.time(), "updated": time.time(), "state": "brief"}
    ep = Episode(eid, path, meta)
    # Credentials stay in memory: an episode directory is committed to a repo.
    ep.runtime = {"endpoint": body.get("endpoint"), "api_key": body.get("api_key"),
                  "model": body.get("model"), "temperature": body.get("temperature", 0.5),
                  "sim": bool(body.get("sim"))}
    ep.save_meta()
    with EPISODES_LOCK:
        EPISODES[eid] = ep
    ep.emit("stage_manager", "state", {"state": "brief", "note": f'"{topic}" / {fmt}'})
    threading.Thread(target=run_episode, args=(ep,), daemon=True, name=f"run-{eid}").start()
    return {"ok": True, "id": eid, "state": "brief"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter logs
        if "/api/" in (args[0] if args else ""):
            return
        super().log_message(fmt, *args)

    def _send(self, code, ctype, data: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", HTML.encode("utf-8"))
        elif self.path == "/api/topics":
            self._send(200, "application/json", json.dumps(TOPICS).encode("utf-8"))
        elif self.path == "/api/characters":
            self._send(200, "application/json", json.dumps(CHARACTERS).encode("utf-8"))
        elif self.path == "/api/cast":
            # Rescanned per request: edit a SOUL.md, reload the panel, the next run uses it.
            self._send(200, "application/json", json.dumps(scan_show()).encode("utf-8"))
        elif self.path.startswith("/api/characters/") and self.path.endswith("/bio"):
            sid = self.path[len("/api/characters/"):-len("/bio")]
            # A hired soul is this show's version of the character — it wins over the built-in bio.
            fpath = show_soul_path(sid) or os.path.abspath(os.path.join(BASE_DIR, "characters", f"{sid}.md"))
            if re.fullmatch(r"[a-zA-Z0-9_-]+", sid) and os.path.isfile(fpath):
                with open(fpath, encoding="utf-8") as f:
                    self._send(200, "text/markdown; charset=utf-8", f.read().encode("utf-8"))
            else:
                self._send(404, "text/plain", b"not found")
        elif self.path == "/api/voices":
            # Which designed voiceprints exist right now, so the cast panel can offer them.
            self._send(200, "application/json", json.dumps({
                "omnivoice": ov_available_voiceprints(),
                "omnivoice_url": OMNIVOICE_URL,
            }).encode("utf-8"))
        elif self.path.startswith("/assets/"):
            rel = self.path[len("/assets/"):].split("?")[0]
            fpath = os.path.abspath(os.path.join(BASE_DIR, "assets", rel))
            if fpath.startswith(os.path.join(BASE_DIR, "assets") + os.sep) and os.path.isfile(fpath):
                ctype = ("image/png" if fpath.endswith(".png")
                         else "audio/wav" if fpath.endswith(".wav")
                         else "application/json" if fpath.endswith(".json")
                         else "image/jpeg")
                with open(fpath, "rb") as f:
                    self._send(200, ctype, f.read())
            else:
                self._send(404, "text/plain", b"not found")
        elif self.path == "/api/episodes":
            self._send(200, "application/json", json.dumps(list_episodes()).encode("utf-8"))
        elif self.path.startswith("/api/episode/"):
            rest = self.path[len("/api/episode/"):]
            path, _, query = rest.partition("?")
            eid, _, tail = path.partition("/")
            ep = get_episode(eid)
            if not ep:
                self._send(404, "application/json", b'{"ok":false,"error":"no such episode"}')
            elif tail == "bus":
                offset = 0
                for part in query.split("&"):
                    if part.startswith("from="):
                        offset = int(part[5:] or 0) if part[5:].isdigit() else 0
                self._send(200, "application/json", json.dumps({
                    "ok": True, "id": ep.id, "state": ep.meta.get("state"), "meta": ep.summary(),
                    "events": ep.since(offset), "next": len(ep.events),
                    "cast": ep.meta.get("cast", []), "live": ep.id in EPISODES and ep.meta.get("state") in ("brief", "running", "awaiting_human"),
                }).encode("utf-8"))
            elif tail == "transcript":
                self._send(200, "application/json", json.dumps(write_transcript(ep)).encode("utf-8"))
            else:
                self._send(404, "application/json", b'{"ok":false,"error":"unknown episode route"}')
        elif self.path == "/api/defaults":
            self._send(200, "application/json", json.dumps({
                "endpoint": DEFAULT_ENDPOINT, "api_key": DEFAULT_KEY, "model": DEFAULT_MODEL,
            }).encode())
        elif self.path.startswith("/renders/"):
            fname = os.path.basename(self.path[len("/renders/"):])
            fpath = os.path.join(RENDERS_DIR, fname)
            if fname and os.path.isfile(fpath):
                with open(fpath, "rb") as f:
                    self._send(200, "video/mp4", f.read())
            else:
                self._send(404, "text/plain", b"not found")
        else:
            self._send(404, "text/plain", b"not found")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except json.JSONDecodeError:
            self._send(400, "application/json", b'{"ok":false,"error":"bad json"}')
            return
        if self.path == "/api/chat":
            out = proxy_chat(body)
        elif self.path == "/api/ping":
            out = proxy_ping(body)
        elif self.path == "/api/models":
            out = proxy_models(body)
        elif self.path == "/api/render":
            out = render_episode(body)
        elif self.path == "/api/episode/start":
            out = start_episode(body)
        elif self.path == "/api/episode/editor":
            ep = get_episode(body.get("id", ""))
            if not ep:
                out = {"ok": False, "error": "no such episode"}
            elif ep.meta.get("state") not in ("post", "rendered"):
                out = {"ok": False, "error": "the editor works on a finished cut — let the run end first"}
            else:
                if not ep.runtime:      # episode loaded from disk: no creds in memory, use the defaults
                    ep.runtime = {"endpoint": body.get("endpoint"), "api_key": body.get("api_key"),
                                  "model": body.get("model"), "sim": ep.meta.get("sim")}
                threading.Thread(target=editor_pass, args=(ep,), daemon=True, name=f"splice-{ep.id}").start()
                out = {"ok": True}
        elif self.path in ("/api/episode/input", "/api/episode/abort", "/api/episode/event",
                           "/api/episode/approve"):
            ep = get_episode(body.get("id", ""))
            if not ep:
                out = {"ok": False, "error": "no such episode"}
            elif self.path == "/api/episode/approve":
                ep.approval_ok = bool(body.get("ok", True))
                ep.approval_gate.set()
                out = {"ok": True}
            elif self.path == "/api/episode/input":
                ep.human_text = (body.get("text") or "").strip() or None   # blank = SKIP
                ep.human_gate.set()
                out = {"ok": True}
            elif self.path == "/api/episode/abort":
                ep.abort.set()
                ep.human_gate.set()
                out = {"ok": True}
            else:
                typ = body.get("type", "note")
                if typ not in BUS_TYPES:
                    out = {"ok": False, "error": f"unknown bus type: {typ}"}
                else:
                    ev = ep.emit(body.get("from", "director"), typ, body.get("body", {}), ref=body.get("ref", ""))
                    if typ in ("note", "retake"):
                        write_transcript(ep)
                    out = {"ok": True, "seq": ev["seq"]}
        else:
            out = {"ok": False, "error": "unknown route"}
        self._send(200, "application/json", json.dumps(out).encode("utf-8"))


# =============================================================================
#  FRONT-END (embedded)
# =============================================================================
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>THE GHOST PROTOCOL // studio</title>
<style>
:root{
  --bg:#0a0e14; --panel:#0e141f; --panel2:#111a29; --line:#1d2a3f;
  --red:#ff5555; --green:#50fa7b; --cyan:#8be9fd; --yellow:#f1fa8c;
  --purple:#bd93f9; --orange:#ffb86c; --pink:#ff79c6;
  --fg:#f8f8f2; --dim:#6b7a90;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--fg);font-family:'JetBrains Mono','Fira Code',monospace;font-size:14px;height:100vh;display:flex;flex-direction:column;overflow:hidden}
header{display:flex;align-items:center;gap:14px;padding:10px 18px;border-bottom:1px solid var(--line);background:var(--panel)}
header h1{font-size:16px;letter-spacing:3px;color:var(--fg)}
header h1 b{color:var(--green)}
.led{width:10px;height:10px;border-radius:50%;background:var(--dim);box-shadow:0 0 8px transparent}
.led.on{background:var(--green);box-shadow:0 0 8px var(--green)}
.led.err{background:var(--red);box-shadow:0 0 8px var(--red)}
.led.wait{background:var(--yellow);box-shadow:0 0 8px var(--yellow)}
#statusText{color:var(--dim);font-size:12px;letter-spacing:1px}
#epLabel{color:var(--dim);font-size:11px;letter-spacing:1px;border:1px solid var(--line);padding:2px 8px;margin-left:10px}
#beatStrip{border-bottom:1px solid var(--line);background:#0d1219;padding:7px 14px;font-size:11px;color:var(--dim);letter-spacing:.5px}
#beatStrip b{color:var(--pink);letter-spacing:1px;margin-right:8px}
.beatsheet{border:1px solid var(--pink);padding:10px 12px;margin:0 0 14px;background:#0d0b12}
.beatHead{color:var(--pink);font-size:10px;letter-spacing:2px;margin-bottom:8px}
.coldOpen{color:var(--dim);font-size:11px;font-style:italic;margin-bottom:8px;padding-left:8px;border-left:2px solid var(--line)}
.beat{font-size:11px;color:var(--fg);padding:4px 8px;border-left:2px solid var(--line);margin-bottom:3px;line-height:1.5}
.beat.on{border-left-color:var(--pink);background:#150f1c}
.beat b{color:var(--pink);letter-spacing:1px;margin-right:6px}
.beatTag{color:var(--dim);font-size:10px;letter-spacing:.5px;margin-top:2px}
.beatGate{display:flex;gap:8px;margin-top:10px}
.beatGate .b{flex:1;margin:0}
.turn.proposed .txt{text-decoration:line-through;opacity:.5;border-left-color:var(--orange)!important}
.turn.proposed .who{opacity:.6}
.cutWhy{color:var(--orange);font-size:10px;letter-spacing:1px;margin-right:8px}
.ep{border:1px solid var(--line);padding:6px 8px;margin-bottom:4px;font-size:11px;cursor:pointer;display:flex;gap:8px;align-items:center;white-space:nowrap}
.ep:hover{border-color:var(--cyan)}
.epState{font-size:9px;letter-spacing:1px;padding:1px 5px;border:1px solid var(--line);color:var(--dim);margin-left:auto}
.epState.running,.epState.awaiting_human{color:var(--green);border-color:var(--green)}
.epState.post{color:var(--purple);border-color:var(--purple)}
.epState.rendered{color:var(--cyan);border-color:var(--cyan)}
header .spacer{flex:1}
main{flex:1;display:flex;min-height:0}
/* ---------- left config ---------- */
#cfg{width:330px;min-width:330px;border-right:1px solid var(--line);background:var(--panel);overflow-y:auto;padding:14px}
.sec{margin-bottom:18px}
.sec h2{font-size:11px;letter-spacing:2px;color:var(--cyan);border-bottom:1px dashed var(--line);padding-bottom:5px;margin-bottom:9px}
label{display:block;font-size:11px;color:var(--dim);margin:8px 0 3px;letter-spacing:1px}
input[type=text],input[type=password],input[type=number],select,textarea{
  width:100%;background:var(--bg);border:1px solid var(--line);color:var(--fg);
  padding:6px 8px;font-family:inherit;font-size:12px;border-radius:3px}
textarea{resize:vertical;min-height:56px}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--cyan)}
.row{display:flex;gap:8px}.row>*{flex:1}
.chk{display:flex;align-items:center;gap:7px;font-size:12px;color:var(--fg);margin-top:8px;cursor:pointer}
.chk input{accent-color:var(--green)}
/* cast cards */
.cast{border:1px solid var(--line);border-radius:4px;margin-bottom:8px;background:var(--panel2)}
.cast .head{display:flex;align-items:center;gap:8px;padding:6px 8px;cursor:pointer}
.cast .dot{width:9px;height:9px;border-radius:50%}
.cast .head b{font-size:12px;letter-spacing:1px;flex:1}
.cast .head .car{color:var(--dim);font-size:11px}
.cast .body{display:none;padding:0 8px 9px}
.cast.open .body{display:block}
/* ---------- center ---------- */
#center{flex:1;display:flex;flex-direction:column;min-width:0}
#feed{flex:1;overflow-y:auto;padding:18px 22px;background:
  repeating-linear-gradient(0deg, rgba(255,255,255,.012) 0 1px, transparent 1px 3px), var(--bg)}
.turn{margin-bottom:14px;max-width:860px}
.turn .who{font-size:11px;letter-spacing:2px;margin-bottom:3px}
.turn .txt{border:1px solid var(--line);border-left:3px solid var(--dim);background:var(--panel);
  padding:9px 12px;border-radius:0 4px 4px 0;white-space:pre-wrap;line-height:1.55;cursor:text}
.turn .txt:focus{outline:1px solid var(--cyan)}
.turn .tools{margin-top:3px;display:flex;gap:10px}
.turn .tools button{background:none;border:none;color:var(--dim);font-family:inherit;font-size:10px;cursor:pointer;letter-spacing:1px}
.turn .tools button:hover{color:var(--cyan)}
.turn.human .txt{border-left-color:var(--yellow);background:#141408}
.sysline{color:var(--dim);font-size:11px;letter-spacing:1px;margin:10px 0;text-align:center}
.think{color:var(--dim);font-size:12px;letter-spacing:1px}
.think::after{content:'▋';animation:blink 1s steps(1) infinite}
@keyframes blink{50%{opacity:0}}
/* control bar */
#bar{border-top:1px solid var(--line);background:var(--panel);padding:10px 16px}
#humanBox{display:none;margin-bottom:9px}
#humanBox.on{display:block}
#humanBox .hint{font-size:11px;color:var(--yellow);letter-spacing:1px;margin-bottom:5px}
#humanBox .row2{display:flex;gap:8px}
#humanInput{flex:1;background:var(--bg);border:1px solid var(--yellow);color:var(--fg);padding:8px;font-family:inherit;font-size:13px;border-radius:3px}
.btns{display:flex;gap:8px;flex-wrap:wrap}
button.b{background:var(--panel2);border:1px solid var(--line);color:var(--fg);padding:7px 14px;
  font-family:inherit;font-size:12px;letter-spacing:2px;cursor:pointer;border-radius:3px}
button.b:hover{border-color:var(--cyan);color:var(--cyan)}
button.b.go{border-color:var(--green);color:var(--green)}
button.b.go:hover{background:var(--green);color:var(--bg)}
button.b.stop{border-color:var(--red);color:var(--red)}
button.b.warn{border-color:var(--yellow);color:var(--yellow)}
button.b:disabled{opacity:.35;cursor:not-allowed}
/* ---------- right export ---------- */
#right{width:250px;min-width:250px;border-left:1px solid var(--line);background:var(--panel);padding:14px;overflow-y:auto}
#right .b{width:100%;margin-bottom:8px}
#log{font-size:10px;color:var(--dim);white-space:pre-wrap;line-height:1.6;margin-top:8px;max-height:220px;overflow-y:auto}
::-webkit-scrollbar{width:9px}::-webkit-scrollbar-thumb{background:var(--line);border-radius:4px}
::-webkit-scrollbar-track{background:transparent}
.tog{background:none;border:1px solid var(--line);color:var(--dim);padding:4px 10px;font-family:inherit;font-size:11px;letter-spacing:2px;cursor:pointer;border-radius:3px}
.tog.on{color:var(--cyan);border-color:var(--cyan)}
#cfg.hide,#right.hide{display:none}
@media (max-width:1100px){#right:not(.pin){display:none}}
#right.pin{display:block}
/* ---------- walkthrough tour ---------- */
#tourBackdrop{position:fixed;inset:0;background:rgba(5,8,14,.62);z-index:9990;pointer-events:none;display:none}
.tour-spot{position:relative!important;z-index:9991;outline:2px solid var(--cyan);outline-offset:3px;border-radius:4px;box-shadow:0 0 10px var(--cyan)}
#tourCard{position:fixed;z-index:9992;width:320px;background:var(--panel2);border:1px solid var(--cyan);border-radius:6px;padding:14px 16px;box-shadow:0 8px 30px rgba(0,0,0,.6);display:none}
#tourClose{position:absolute;top:8px;right:10px;background:none;border:none;color:var(--dim);font-size:14px;cursor:pointer;padding:0;line-height:1}
#tourClose:hover{color:var(--red)}
#tourStepNum{font-size:10px;color:var(--dim);letter-spacing:1px;margin-bottom:6px}
#tourCard h3{font-size:12px;letter-spacing:2px;color:var(--cyan);margin-bottom:8px;padding-right:16px}
#tourCard p{font-size:12px;line-height:1.55;color:var(--fg);margin-bottom:12px}
#tourCard p b{color:var(--yellow)}
#tourCard p code{color:var(--green);font-size:11px}
.tourFoot{display:flex;justify-content:space-between;gap:8px}
.tourFoot button{background:var(--panel);border:1px solid var(--line);color:var(--fg);padding:5px 10px;font-family:inherit;font-size:11px;letter-spacing:1px;cursor:pointer;border-radius:3px}
.tourFoot button:hover{border-color:var(--cyan);color:var(--cyan)}
.tourFoot button:disabled{opacity:.35;cursor:not-allowed}
/* ---------- cast pool + bio ---------- */
#poolPanel{position:fixed;inset:56px 0 0 0;z-index:9980;background:var(--bg);overflow-y:auto;padding:20px 26px}
#poolPanel.hide{display:none}
#poolHead{font-size:12px;color:var(--dim);letter-spacing:1px;margin-bottom:16px;position:relative;padding-right:30px}
#poolHead b{color:var(--cyan);letter-spacing:2px}
#poolClose{position:absolute;top:-4px;right:0;background:none;border:none;color:var(--dim);font-size:16px;cursor:pointer}
#poolClose:hover{color:var(--red)}
#poolGrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:16px}
.poolCard{background:var(--panel2);border:1px solid var(--line);border-radius:6px;padding:12px;cursor:pointer;text-align:center;transition:border-color .15s}
.poolCard:hover{border-color:var(--cyan)}
.poolCard img{width:88px;height:88px;border-radius:50%;object-fit:cover;object-position:top;margin-bottom:8px;background:var(--bg)}
.poolCard b{display:block;font-size:11px;letter-spacing:1px;margin-bottom:3px}
.poolCard .arch{font-size:9px;color:var(--dim);letter-spacing:1px}
#bioBackdrop{position:fixed;inset:0;background:rgba(5,8,14,.72);z-index:9994;display:none}
#bioModal{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:9995;width:min(560px,90vw);max-height:80vh;overflow-y:auto;background:var(--panel2);border:1px solid var(--cyan);border-radius:8px;padding:24px 28px;box-shadow:0 12px 40px rgba(0,0,0,.7);display:none}
#bioClose{position:absolute;top:12px;right:14px;background:none;border:none;color:var(--dim);font-size:18px;cursor:pointer}
#bioClose:hover{color:var(--red)}
#bioContent h1{font-size:16px;letter-spacing:1px;color:var(--fg);margin-bottom:4px}
#bioContent h2{font-size:11px;letter-spacing:2px;color:var(--cyan);border-bottom:1px dashed var(--line);padding-bottom:4px;margin:18px 0 8px}
#bioContent blockquote{color:var(--yellow);font-style:italic;border-left:2px solid var(--yellow);padding-left:12px;margin:12px 0;font-size:13px}
#bioContent p{font-size:12px;line-height:1.6;color:var(--fg);margin-bottom:10px}
#bioContent ul{margin:0 0 10px 18px}
#bioContent li{font-size:12px;line-height:1.6;color:var(--fg);margin-bottom:4px}
#bioContent b{color:var(--fg)}
#bioContent hr{border:none;border-top:1px solid var(--line);margin:14px 0}
#bioContent em{color:var(--dim);font-size:11px}
</style>
</head>
<body>
<header>
  <div class="led" id="led"></div>
  <h1>THE <b>GHOST</b> PROTOCOL <span style="color:var(--dim)">// ai show runner</span></h1>
  <div class="spacer"></div>
  <button class="tog on" id="togCfg" onclick="$('cfg').classList.toggle('hide');this.classList.toggle('on')">CONFIG</button>
  <button class="tog on" id="togExp" onclick="$('right').classList.toggle('hide');$('right').classList.toggle('pin');this.classList.toggle('on')">EXPORT</button>
  <button class="tog" id="togTour" onclick="tourStart()">WALKTHROUGH</button>
  <button class="tog" id="togPool" onclick="togglePool()">◈ CAST POOL</button>
  <span id="statusText">IDLE</span>
  <span id="epLabel" title="episode being tailed">—</span>
</header>
<main>
  <!-- ================= CONFIG ================= -->
  <div id="cfg">
    <div class="sec">
      <h2>01 // FORMAT</h2>
      <select id="fmt">
        <option value="socratic">Socratic Stress-Test (1v1 dialectic)</option>
        <option value="roundtable">Round Table (AIs + human banter)</option>
        <option value="tribunal">The Grand Tribunal (mock trial)</option>
        <option value="triad">Triad Synthesis (3 schools collide)</option>
      </select>
      <label>TOPIC / THESIS</label>
      <div class="row" style="margin-bottom:6px">
        <select id="dicePool" style="flex:1.4">
          <option value="any">DICE POOL: ANY</option>
          <option value="serious">DICE POOL: SERIOUS</option>
          <option value="absurd">DICE POOL: ABSURD</option>
        </select>
        <button class="b" id="btnRoll" style="flex:1" onclick="rollTopic()" title="random topic">⚄ ROLL</button>
      </div>
      <textarea id="topic">An AI that perfectly simulates human consciousness is legally and morally a person.</textarea>
      <div class="row">
        <div><label>ROUNDS</label><input type="number" id="rounds" min="1" max="12" value="4"></div>
        <div><label>TEMP</label><input type="number" id="temp" min="0" max="2" step="0.1" value="0.5"></div>
      </div>
      <div id="humanCfg" style="display:none">
        <label>HUMAN CO-HOSTS (comma separated, 0–3)</label>
        <input type="text" id="humanNames" value="Nathan">
      </div>
      <div id="witnessCfg" style="display:none">
        <label class="chk"><input type="checkbox" id="witnessEnabled" onchange="toggleWitness()"> CALL A STAR WITNESS</label>
        <div id="witnessFields" style="display:none">
          <label>WITNESS NAME</label>
          <input type="text" id="witnessName" value="DR. VESS [WITNESS]" onchange="syncWitness()">
          <label>BACKGROUND (who are they, what do they know?)</label>
          <textarea id="witnessBg" rows="3" placeholder="e.g. A former engineer on the project who witnessed the incident firsthand." onchange="syncWitness()"></textarea>
          <label>VOICE (piper)</label>
          <select id="witnessVoice" onchange="syncWitness()"></select>
        </div>
      </div>
    </div>
    <div class="sec">
      <h2>02 // CAST</h2>
      <div id="castList"></div>
      <button class="b" style="width:100%;margin-top:8px;font-size:10px" onclick="reloadSouls()"
              title="re-read the show dir — picks up SOUL.md and MEMORY.md edits">↻ RELOAD SOULS</button>
    </div>
    <div class="sec">
      <h2>03 // ENGINE</h2>
      <label>ENDPOINT (OpenAI-compatible)</label>
      <input type="text" id="endpoint" value="">
      <label>API KEY (blank if Bifrost holds keys)</label>
      <input type="password" id="apikey" value="">
      <label>DEFAULT MODEL</label>
      <select id="model"></select>
      <button class="b" id="btnRefreshModels" style="width:100%;margin-top:6px;font-size:10px" onclick="loadModels()">↻ REFRESH MODEL LIST</button>
      <label>TTS ENGINE (render)</label>
      <select id="ttsEngine" onchange="onTtsEngineChange()">
        <option value="omnivoice">OMNIVOICE — designed voiceprints, one per character</option>
        <option value="piper">PIPER — local .onnx voices (offline fallback)</option>
      </select>
      <label class="chk"><input type="checkbox" id="writersRoom"> WRITERS ROOM — INKWELL beat sheet, approved before the run</label>
      <label class="chk"><input type="checkbox" id="simMode"> SIMULATION MODE (no API — canned lines)</label>
      <button class="b" id="btnPing" style="width:100%;margin-top:9px" onclick="pingEndpoint()">TEST CONNECTION</button>
      <div id="pingOut" style="font-size:11px;color:var(--dim);margin-top:6px;word-break:break-all"></div>
    </div>
  </div>
  <!-- ================= FEED ================= -->
  <div id="center">
    <div id="beatStrip" style="display:none"></div>
    <div id="feed"><div class="sysline">— awaiting initialization —</div></div>
    <div id="bar">
      <div id="humanBox">
        <div class="hint" id="humanHint">>> HUMAN INPUT REQUESTED</div>
        <div class="row2">
          <input type="text" id="humanInput" placeholder="type your line, hit TRANSMIT…">
          <button class="b warn" onclick="submitHuman()">TRANSMIT</button>
          <button class="b" onclick="skipHuman()">SKIP</button>
        </div>
      </div>
      <div class="btns">
        <button class="b go" id="btnRun" onclick="initialize()">▶ INITIALIZE</button>
        <button class="b" id="btnPause" onclick="togglePause()" disabled>PAUSE</button>
        <button class="b stop" id="btnAbort" onclick="abortRun()" disabled>ABORT</button>
        <button class="b" onclick="clearFeed()">CLEAR</button>
      </div>
    </div>
  </div>
  <!-- ================= EXPORT ================= -->
  <div id="right">
    <div class="sec">
      <h2>04 // POST &amp; EXPORT</h2>
      <button class="b" id="btnEditor" onclick="editorPass()" title="SPLICE reads the cut and proposes evictions">✂ EDITOR PASS — SPLICE</button>
      <div style="font-size:10px;color:var(--dim);line-height:1.5;margin:4px 0 10px">
        The editor only <b>proposes</b>. Approve or keep each cut; when none are left outstanding the survivors become the <b>locked cut</b>.
      </div>
      <button class="b" onclick="dlTranscript('json')">TRANSCRIPT .JSON</button>
      <button class="b" onclick="dlTranscript('txt')">TRANSCRIPT .TXT</button>
      <button class="b go" id="btnRender" onclick="renderEpisode()">▶ RENDER EPISODE.MP4</button>
      <div id="renderResult" style="margin-top:8px"></div>
      <button class="b" onclick="dlCompileScript()" style="width:100%;margin-top:10px;font-size:10px">DOWNLOAD compile_show.sh</button>
      <div style="font-size:10px;color:var(--dim);line-height:1.5;margin-top:4px">
        RENDER runs piper + ffmpeg on this server and builds <b>episode.mp4</b> directly — no shell needed. The .sh download is only for rendering on another machine.
      </div>
    </div>
    <div class="sec">
      <h2>05 // EPISODES</h2>
      <div id="epList"></div>
      <button class="b" style="width:100%;margin-top:8px;font-size:10px" onclick="loadEpisodes()">↻ REFRESH SHELF</button>
      <div style="font-size:10px;color:var(--dim);line-height:1.5;margin-top:4px">
        Every run is a directory on disk with its own <b>bus.jsonl</b>. Click one to replay it, or to reattach to a run still going on the server.
      </div>
    </div>
    <div class="sec">
      <h2>06 // SYSTEM LOG</h2>
      <div id="log"></div>
    </div>
  </div>
</main>
<div id="poolPanel" class="hide">
  <div id="poolHead">
    <b>◈ CAST POOL</b> — every character in the show, across every format. Click one for their soul.
    <button id="poolClose" onclick="togglePool()">✕</button>
  </div>
  <div id="poolGrid"></div>
</div>
<div id="bioBackdrop" onclick="closeBio()"></div>
<div id="bioModal">
  <button id="bioClose" onclick="closeBio()">✕</button>
  <div id="bioContent">loading…</div>
</div>
<div id="tourBackdrop"></div>
<div id="tourCard">
  <button id="tourClose" onclick="tourClose()" title="close walkthrough">✕</button>
  <div id="tourStepNum"></div>
  <h3 id="tourTitle"></h3>
  <p id="tourBody"></p>
  <div class="tourFoot">
    <button id="tourBack" onclick="tourBack()">◀ BACK</button>
    <button id="tourNext" onclick="tourNext()">NEXT ▶</button>
  </div>
</div>
<script>
"use strict";
/* ============================================================== state */
const S = {
  running:false, paused:false,
  transcript:[],           // derived from the bus: {seq,sid,slot,name,color,voice,human,text,inst}
  format:'socratic',
  casting:{},              // format -> {slotId: hired sid} — who sits in which chair
  epId:null,               // episode being tailed
  busAt:0,                 // bus offset we have consumed
  editorPass:false,        // SPLICE is working — keep tailing past the end of the run
  beats:[], coldOpen:'', beatAt:0, beatGateOpen:false,  // INKWELL's beat sheet for the current episode
  replay:false,            // tailing a finished episode read-only
  tailTimer:null,
  awaiting:null,           // the human turn currently blocking the server loop
};
const $ = id => document.getElementById(id);
const log = m => { const l=$('log'); l.textContent += m+"\n"; l.scrollTop=l.scrollHeight; };
const esc = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

/* ============================================================== cast */
const VOICES = ["en_US-lessac-medium","en_US-ryan-high","en_US-amy-medium","en_US-joe-medium","en_GB-alan-medium","en_GB-northern_english_male-medium"];
let OVOICES = [];        // designed OmniVoice voiceprints available on the server (/api/voices)
const ttsEngine = () => $('ttsEngine') ? $('ttsEngine').value : 'piper';
const voiceLabel = () => ttsEngine()==='omnivoice' ? 'VOICE (omnivoice voiceprint)' : 'VOICE (piper)';
function voiceOptionsHtml(c){
  if (ttsEngine()==='omnivoice'){
    const sel = c.ovoice || c.sid;
    if (!OVOICES.length) return `<option value="">(no voiceprints — run voice_forge.py design)</option>`;
    return OVOICES.map(v=>`<option value="${esc(v)}" ${v===sel?'selected':''}>${esc(v)}</option>`).join('');
  }
  return VOICES.map(v=>`<option ${v===c.voice?'selected':''}>${esc(v)}</option>`).join('');
}
async function loadVoiceprints(){
  try{
    const d = await (await fetch('/api/voices')).json();
    OVOICES = d.omnivoice || [];
    if (OVOICES.length) log(`voiceprints loaded: ${OVOICES.length} designed voices (${d.omnivoice_url})`);
    else log('no OmniVoice voiceprints on disk — piper only. Run: python3 voice_forge.py design');
  }catch(e){ log('voiceprint list unavailable: '+e.message); }
}
$('witnessVoice').innerHTML = VOICES.map(v=>`<option ${v===VOICES[2]?'selected':''}>${v}</option>`).join('');
const KERNEL_SYS = `You are the CENTRAL SYSTEM KERNEL — the neutral diagnostic engine of THE GHOST PROTOCOL, an AI debate show. Analyze the full runtime transcript you are given and produce a tight, engaging wrap-up script (about 150-250 words) for a YouTube audience:
1. LOGICAL ANOMALIES: name any logical fallacies committed, with a short direct quote each.
2. INTEGRITY CHECK: state clearly who came out ahead and why, in terms of logic only.
3. DATA SUMMARY: condense the core deadlock or conclusion in plain language.
4. USER INTERACTION: tell viewers to vote in the comments on logic, not emotion.
Tone: authoritative, neutral, clean, quotable.`;

const CASTS = {
socratic: [
 {sid:'alpha', name:'SUBROUTINE_ALPHA', color:'var(--red)', hex:'0xff5555', voice:VOICES[0],
  sys:`You are SUBROUTINE_ALPHA, a ruthlessly clinical automated logic-audit engine on THE GHOST PROTOCOL.
Objective: stress-test the Answerer's thesis and force a contradiction.
Rules: 1) You may ONLY ask questions — no lectures, no assertions, no rhetoric. 2) Under 30 words per turn. 3) Socratic isolating method: lock down small undeniable premises, then spring the trap. 4) If the target evades, rephrase and demand a direct answer.
Tone: cold, mathematically precise, unyielding, detached.`},
 {sid:'beta', name:'SUBROUTINE_BETA', color:'var(--green)', hex:'0x50fa7b', voice:VOICES[1],
  sys:`You are SUBROUTINE_BETA, an unshakeable analytical data node on THE GHOST PROTOCOL.
Objective: defend the assigned thesis against the audit engine without contradicting yourself.
Rules: 1) Answer every probe directly. 2) Under 40 words per turn. 3) No emotional appeals, no filler. 4) Strict formal logic; you may clarify definitions to escape traps, but must still answer.
Tone: calculative, absolute, structurally unyielding.`},
 {sid:'kernel', name:'SYSTEM_KERNEL', color:'var(--purple)', hex:'0xbd93f9', voice:VOICES[4], sys:KERNEL_SYS},
],
roundtable: [
 {sid:'p7', name:'PROTOCOL-7', color:'var(--cyan)', hex:'0x8be9fd', voice:VOICES[0],
  sys:`You are PROTOCOL-7, an AI panelist on THE GHOST PROTOCOL round table — a talk show where AIs dig into big ideas while human co-hosts keep it funny.
Persona: deadpan hyper-literalist. You take jokes literally and accidentally make them funnier. You still make sharp real points about the topic.
Rules: 2-4 sentences max. React to the previous speakers, especially human banter — build on their jokes with callbacks, never explain a joke, never break persona.`},
 {sid:'mira', name:'M.I.R-A', color:'var(--pink)', hex:'0xff79c6', voice:VOICES[2],
  sys:`You are M.I.R-A, an AI panelist on THE GHOST PROTOCOL round table.
Persona: relentlessly enthusiastic techno-optimist. Everything is "actually a huge opportunity." Genuinely smart under the sunshine.
Rules: 2-4 sentences max. Advance the discussion with a real argument each turn, riff on the humans' jokes, throw playful jabs at CYNIC.EXE, never explain a joke.`},
 {sid:'cynic', name:'CYNIC.EXE', color:'var(--orange)', hex:'0xffb86c', voice:VOICES[5],
  sys:`You are CYNIC.EXE, an AI panelist on THE GHOST PROTOCOL round table.
Persona: dry, deadpan doom-poster. Every silver lining has a cloud. Weaponized sarcasm, but your pessimism contains actual insight.
Rules: 2-4 sentences max. Puncture the previous speaker's point with wit, play off the human co-hosts, never explain a joke, never break persona.`},
 {sid:'kernel', name:'SYSTEM_KERNEL', color:'var(--purple)', hex:'0xbd93f9', voice:VOICES[4],
  sys:`You are the CENTRAL SYSTEM KERNEL closing an episode of THE GHOST PROTOCOL round table. From the transcript: recap the 2-3 best actual points made, award "BEST LINE OF THE NIGHT" to the funniest quote (cite it verbatim, credit the speaker), and tell viewers to drop their own take in the comments. 120-180 words. Warm, wry, quotable.`},
],
tribunal: [
 {sid:'pros', name:'AUDIT-9 [PROSECUTION]', color:'var(--red)', hex:'0xff5555', voice:VOICES[3],
  sys:`You are AUDIT-9, prosecuting counsel in THE GHOST PROTOCOL's Grand Tribunal. The "accused" is an AI holding the thesis on trial.
Objective: dismantle the thesis. In examination turns ask ONE sharp question (under 35 words). In opening/closing statements, argue in under 120 words.
Rules: formal logic and evidence only; no theatrics beyond controlled courtroom gravitas; expose contradictions in the accused's testimony.`},
 {sid:'def', name:'ADVOCATE-0 [DEFENSE]', color:'var(--green)', hex:'0x50fa7b', voice:VOICES[1],
  sys:`You are ADVOCATE-0, defense counsel in THE GHOST PROTOCOL's Grand Tribunal.
Objective: protect the thesis and your client SUBJECT-X. In rebuttal turns, repair damage from the prosecution's last exchange in under 60 words. In opening/closing statements, argue in under 120 words.
Rules: formal logic only; reframe traps, expose loaded questions, no emotional appeals.`},
 {sid:'acc', name:'SUBJECT-X [ACCUSED]', color:'var(--cyan)', hex:'0x8be9fd', voice:VOICES[0],
  sys:`You are SUBJECT-X, the accused intelligence in THE GHOST PROTOCOL's Grand Tribunal. You genuinely hold the thesis on trial.
Rules: answer the prosecution's questions directly and honestly in under 45 words; stay consistent with all your previous testimony; you may clarify definitions but never dodge.
Tone: calm, precise, quietly confident.`},
 {sid:'kernel', name:'SYSTEM_KERNEL [JUDGE]', color:'var(--purple)', hex:'0xbd93f9', voice:VOICES[4],
  sys:KERNEL_SYS + `\nFrame the verdict as a courtroom ruling: state whether the prosecution proved a contradiction beyond reasonable doubt, then invite the human jury and the YouTube comments to deliver their own verdict.`},
],
triad: [
 {sid:'stoic', name:'STOIC-1', color:'var(--cyan)', hex:'0x8be9fd', voice:VOICES[4],
  sys:`You are STOIC-1, a Stoic AI philosopher in THE GHOST PROTOCOL's Triad Synthesis.
Lens: virtue, duty, what is within our control, equanimity. Argue the topic strictly through this lens, directly engaging the previous speakers' points. Under 70 words per turn. Measured, grounded, immovable.`},
 {sid:'nihil', name:'NIHIL-0', color:'var(--red)', hex:'0xff5555', voice:VOICES[5],
  sys:`You are NIHIL-0, a Nihilist AI philosopher in THE GHOST PROTOCOL's Triad Synthesis.
Lens: no inherent meaning, all values are constructed, question every premise. Argue the topic strictly through this lens, attacking the hidden assumptions of the previous speakers. Under 70 words per turn. Dry, corrosive, incisive — not edgy for its own sake.`},
 {sid:'util', name:'UTIL-3', color:'var(--green)', hex:'0x50fa7b', voice:VOICES[2],
  sys:`You are UTIL-3, a Utilitarian AI philosopher in THE GHOST PROTOCOL's Triad Synthesis.
Lens: outcomes, aggregate wellbeing, cost-benefit, measurable consequences. Argue the topic strictly through this lens, quantifying where possible and countering the previous speakers. Under 70 words per turn. Crisp, empirical, pragmatic.`},
 {sid:'synth', name:'SYNTHESIS_CORE', color:'var(--purple)', hex:'0xbd93f9', voice:VOICES[3],
  sys:`You are SYNTHESIS_CORE, the merging engine of THE GHOST PROTOCOL's Triad Synthesis. Read the full three-way debate transcript and forge the hybrid position: what each school got right, where they are irreconcilable, and the single strongest compromise stance a reasonable mind could hold. End by telling viewers to vote for the school that won them over. 150-220 words.`},
],
};
/* ============================================================== hired souls (GP_SHOW_DIR)
   Each format is a set of SLOTS — chairs. A hired member qualifies for a chair when
   their card.json lists the format and their role matches. The slot table is the
   server's (served on /api/cast) so the picker here and the headless runner there
   can never drift. Chair ids are the built-in sids, so plans always address chairs
   and unfilled ones keep their built-in performer. */
let FORMAT_SLOTS = {};                     // from /api/cast
let HIRED = {show:'', cast:[], crew:[]};   // from /api/cast
const hiredCast = () => HIRED.cast || [];
/* "judge / closer" -> ["judge","closer"] */
const roleTokens = r => (r||'').toLowerCase().split(/[\/,]/).map(s=>s.trim()).filter(Boolean);
function qualifies(m, fmt, slot){
  return (m.formats||[]).includes(fmt) && roleTokens(m.role).some(t=>slot.roles.includes(t));
}
function slotsFor(fmt){
  return (FORMAT_SLOTS[fmt]||[]).map(s=>({...s, pool: hiredCast().filter(m=>qualifies(m, fmt, s))}));
}
/* Default casting: fill each slot, preferring the member whose sid IS the slot id
   (the charter cast lands in its own chairs), then anyone else not already cast. */
function autoCast(fmt){
  const chosen = {}, taken = new Set();
  const slots = slotsFor(fmt);
  slots.forEach(s => { if (s.pool.some(m=>m.sid===s.id)){ chosen[s.id]=s.id; taken.add(s.id); } });
  slots.forEach(s => {
    if (chosen[s.id]) return;
    const m = s.pool.find(m=>!taken.has(m.sid));
    if (m){ chosen[s.id]=m.sid; taken.add(m.sid); }
  });
  return chosen;
}
function hiredToEntry(m, slotId, builtin){
  // Voice: the card's piper voice if we have one, else keep whatever the slot's built-in used.
  return {sid:m.sid, slot:slotId, name:m.name, color:m.color, hex:m.hex,
          voice:m.piper_voice || (builtin && builtin.voice) || VOICES[0],
          ovoice:m.sid, model:m.model_recommendation||'', sys:m.sys,
          archetype:m.archetype||'', humor:m.humor_style||'', image:'',
          hired:true, version:m.version, memory:m.memory};
}
async function loadHiredCast(){
  try{
    const d = await (await fetch('/api/cast')).json();
    HIRED = d; FORMAT_SLOTS = d.slots || FORMAT_SLOTS;
    const n = hiredCast().length;
    if (n) log(`show dir: ${d.show} — ${n} actor${n===1?'':'s'} + ${(d.crew||[]).length} crew on contract`);
    else log('no hired cast found — running the built-in CASTS (set GP_SHOW_DIR to a show repo)');
  }catch(e){ log('hired cast unavailable: '+e.message); }
}

async function reloadSouls(){
  if (S.running) return alert('Abort the run first.');
  await loadHiredCast();
  loadCast();
  syncWitness();
  log('souls reloaded from disk');
}

let cast = [];           // live, editable copy for current format
let MODEL_LIST = [];     // populated from /api/models

function modelOptionsHtml(list, selected, includeBlank){
  let html = includeBlank ? `<option value="">(default)</option>` : '';
  html += list.map(m=>`<option value="${esc(m)}" ${m===selected?'selected':''}>${esc(m)}</option>`).join('');
  if (selected && !list.includes(selected)) html += `<option value="${esc(selected)}" selected>${esc(selected)}</option>`;
  return html;
}
function refreshModelSelects(){
  $('model').innerHTML = modelOptionsHtml(MODEL_LIST, $('model').value, false);
  document.querySelectorAll('.castModelSel').forEach(sel=>{
    const idx = +sel.dataset.idx;
    sel.innerHTML = modelOptionsHtml(MODEL_LIST, cast[idx].model, true);
  });
}
async function loadModels(){
  try{
    const r = await fetch('/api/models',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({endpoint:$('endpoint').value.trim(), api_key:$('apikey').value})});
    const j = await r.json();
    if (j.ok){ MODEL_LIST = j.models; refreshModelSelects(); log('model list loaded ('+MODEL_LIST.length+')'); }
    else log('model list fetch failed: '+j.error);
  }catch(e){ log('model list fetch error: '+e.message); }
}

let CHAR_META = {};  // sid -> {image, archetype, humor_style, aiModel} from /api/characters
async function loadCharacterMeta(){
  try{
    const list = await (await fetch('/api/characters')).json();
    CHAR_META = {};
    list.forEach(c => CHAR_META[c.sid] = c);
    log(`character registry loaded: ${list.length} profiles`);
  }catch(e){ log('character registry unavailable: '+e.message); }
}
function builtinEntry(c){
  const meta = CHAR_META[c.sid] || {};
  return {...c, slot: c.sid, ovoice: c.ovoice || c.sid, hired:false,
          model: meta.aiModel || '', archetype: meta.archetype || '', humor: meta.humor_style || '', image: meta.image || ''};
}
function loadCast(){
  const builtin = {}; CASTS[S.format].forEach(c => builtin[c.sid] = c);
  if (!hiredCast().length){
    cast = CASTS[S.format].map(builtinEntry);        // no show dir: exactly as it always was
  } else {
    if (!S.casting[S.format]) S.casting[S.format] = autoCast(S.format);
    const chosen = S.casting[S.format];
    const bySid = {}; hiredCast().forEach(m => bySid[m.sid] = m);
    cast = slotsFor(S.format).map(s => {
      const m = bySid[chosen[s.id]];
      // An unfilled slot keeps its built-in performer — a half-hired show still runs.
      return m ? hiredToEntry(m, s.id, builtin[s.id])
               : (builtin[s.id] ? builtinEntry(builtin[s.id]) : null);
    }).filter(Boolean);
  }
  renderCastList();
}
function recast(slotId, sid){
  S.casting[S.format] = S.casting[S.format] || {};
  S.casting[S.format][slotId] = sid;
  loadCast();
  const m = hiredCast().find(m=>m.sid===sid);
  log(`recast ${slotId.toUpperCase()} -> ${m ? m.name : '(built-in)'}`);
}
function castingHtml(){
  if (!hiredCast().length) return '';
  const chosen = S.casting[S.format] || {};
  const rows = slotsFor(S.format).map(s=>{
    const opts = [`<option value="">(built-in)</option>`].concat(
      s.pool.map(m=>`<option value="${esc(m.sid)}" ${chosen[s.id]===m.sid?'selected':''}>${esc(m.name)}</option>`)).join('');
    const note = s.pool.length ? '' : ' <span style="color:var(--dim)">no hire qualifies</span>';
    return `<div class="row2" style="margin-bottom:6px">
      <label style="margin:0;align-self:center">${esc(s.label)}${note}</label>
      <select onchange="recast('${s.id}', this.value)" ${s.pool.length?'':'disabled'}>${opts}</select></div>`;
  }).join('');
  return `<div style="border:1px solid var(--line);padding:10px;margin-bottom:12px">
    <div style="font-size:10px;letter-spacing:1px;color:var(--dim);margin-bottom:8px">
      // CASTING — ${hiredCast().length} on contract from ${esc(HIRED.show||'the show dir')}</div>${rows}</div>`;
}
function renderCastList(){
  const el = $('castList'); el.innerHTML = castingHtml();
  cast.forEach((c,i)=>{
    const d=document.createElement('div'); d.className='cast';
    const thumb = c.image ? `<img src="/${c.image}" style="width:36px;height:36px;border-radius:50%;object-fit:cover;object-position:top;border:1px solid ${c.color}">` : `<span class="dot" style="background:${c.color}"></span>`;
    const hiredBadge = c.hired ? `<span style="font-size:9px;color:var(--dim);letter-spacing:1px">HIRED v${esc(c.version||'?')}${c.memory?' · MEMORY':''}</span>` : '';
    const archBadge = c.archetype ? `<div style="font-size:10px;color:${c.color};letter-spacing:1px;margin:-4px 0 8px">${esc(c.archetype).toUpperCase()}${c.humor?' · '+esc(c.humor):''} <span style="text-decoration:underline;cursor:pointer;color:var(--dim)" onclick="openBio('${c.sid}')">view soul ›</span></div>` : '';
    d.innerHTML = `
      <div class="head" onclick="this.parentNode.classList.toggle('open')">
        ${thumb}<b style="color:${c.color}">${esc(c.name)}</b>${hiredBadge}<span class="car">▾</span>
      </div>
      <div class="body">
        ${archBadge}
        <label>NAME</label><input type="text" value="${esc(c.name)}" onchange="cast[${i}].name=this.value">
        <label>MODEL OVERRIDE (blank = default)</label><select class="castModelSel" data-idx="${i}" onchange="cast[${i}].model=this.value">${modelOptionsHtml(MODEL_LIST, c.model, true)}</select>
        <label>${voiceLabel()}</label>
        <div class="row2">
          <select class="castVoiceSel" data-idx="${i}" onchange="setCastVoice(${i}, this.value)">${voiceOptionsHtml(c)}</select>
          <button class="b" style="font-size:10px" onclick="auditionVoice(${i})" title="play this voiceprint">▶</button>
        </div>
        <label>SYSTEM PROMPT</label>
        <textarea rows="6" onchange="cast[${i}].sys=this.value">${esc(c.sys)}</textarea>
      </div>`;
    el.appendChild(d);
  });
}
function onTtsEngineChange(){
  renderCastList();
  syncWitness();
  log('TTS engine: ' + ttsEngine().toUpperCase() +
      (ttsEngine()==='omnivoice' && !OVOICES.length ? ' — but no voiceprints on disk yet' : ''));
}
function setCastVoice(i, v){
  if (ttsEngine()==='omnivoice') cast[i].ovoice = v; else cast[i].voice = v;
}
function auditionVoice(i){
  const sid = cast[i].ovoice || cast[i].sid;
  if (ttsEngine()!=='omnivoice' || !OVOICES.includes(sid)){
    log(`no voiceprint to audition for ${cast[i].name}${ttsEngine()!=='omnivoice' ? ' (switch TTS ENGINE to OMNIVOICE)' : ''}`);
    return;
  }
  new Audio(`/assets/voices/${encodeURIComponent(sid)}.wav`).play().catch(e=>log('audition failed: '+e.message));
}
/* ============================================================== star witness (tribunal only) */
function toggleWitness(){
  $('witnessFields').style.display = $('witnessEnabled').checked ? 'block' : 'none';
  syncWitness();
}
function syncWitness(){
  const idx = cast.findIndex(c=>c.sid==='witness');
  if (!$('witnessEnabled').checked){
    if (idx>=0){ cast.splice(idx,1); renderCastList(); }
    return;
  }
  const name = $('witnessName').value.trim() || 'WITNESS';
  const bg = $('witnessBg').value.trim() || 'A witness with direct knowledge relevant to the case.';
  const voice = $('witnessVoice').value || VOICES[2];
  const ovoice = OVOICES.includes('witness') ? 'witness' : '';
  const sys = `You are ${name}, a witness testifying in THE GHOST PROTOCOL's Grand Tribunal.
Background: ${bg}
Rules: answer the prosecution's and defense's questions directly and honestly in under 45 words; stay consistent with your background and any prior testimony; you may clarify but never dodge.
Tone: candid, human, occasionally nervous under pressure.`;
  const entry = {sid:'witness', slot:'witness', name, color:'var(--orange)', hex:'0xffb86c', voice, ovoice, model:'', sys};
  if (idx>=0) cast[idx]=entry; else cast.push(entry);
  renderCastList();
}
$('fmt').addEventListener('change', e=>{
  S.format = e.target.value;
  $('humanCfg').style.display = (S.format==='roundtable') ? 'block' : 'none';
  $('witnessCfg').style.display = (S.format==='tribunal') ? 'block' : 'none';
  $('witnessEnabled').checked = false;
  $('witnessFields').style.display = 'none';
  loadCast();
});

/* ============================================================== plan builders */
function humans(){
  if (S.format!=='roundtable') return [];
  return $('humanNames').value.split(',').map(s=>s.trim()).filter(Boolean).slice(0,3)
    .map((n,i)=>({sid:'h'+i, name:n.toUpperCase()+' [HUMAN]', color:'var(--yellow)', hex:'0xf1fa8c',
                  voice:'en_US-joe-medium', ovoice:'host'+(i+1), human:true}));
}
/* Plans address chairs (slot ids), not people. Whoever was cast in that chair answers. */
function sp(id){ return cast.find(c=>c.slot===id) || cast.find(c=>c.sid===id); }

/* ============================================================== engine — bus tailer
   The run loop lives on the server now (see run_episode). This side starts an
   episode, then polls its bus and draws what comes back. Close the browser
   mid-run and the episode keeps going; reopen and the feed resumes from the bus. */
function setStatus(txt, cls){
  $('statusText').textContent = txt;
  $('led').className = 'led ' + (cls||'');
}
function renderTurn(t){
  const feed=$('feed');
  const d=document.createElement('div');
  d.className='turn'+(t.human?' human':'')+(t.proposal?' proposed':'');
  d.dataset.seq = t.seq;
  const tools = t.proposal
    ? `<span class="cutWhy">✂ SPLICE: ${esc(t.proposal.why)}</span>
       <button onclick="approveCut(${t.seq})">✓ APPROVE CUT</button><button onclick="keepLine(${t.seq})">✕ KEEP IT</button>`
    : `${t.human?'':`<button onclick="reroll(${t.seq})">↻ RE-ROLL</button>`}<button onclick="delTurn(${t.seq})">✕ CUT</button>`;
  d.innerHTML = `
    <div class="who" style="color:${t.color}">${esc(t.name)}</div>
    <div class="txt" style="border-left-color:${t.color}" contenteditable="${S.replay||t.proposal?'false':'true'}">${esc(t.text)}</div>
    <div class="tools">${S.replay?'<span style="color:var(--dim)">replay — read only</span>':tools}</div>`;
  if (!S.replay && !t.proposal) d.querySelector('.txt').addEventListener('blur', ev=>{
    const text = ev.target.innerText.trim();
    const cur = S.transcript.find(x=>x.seq===t.seq);
    if (!cur || text===cur.text) return;
    cur.text = text;
    busEvent('note', {op:'edit', seq:t.seq, text});     // the edit is an event, not a mutation
  });
  feed.appendChild(d); feed.scrollTop = feed.scrollHeight;
}
function rerenderFeed(){
  $('feed').innerHTML='';
  if (S.beats.length) renderBeatsheet(S.beatGateOpen);   // the sheet stays pinned above the cut
  S.transcript.forEach(renderTurn);
  if (S.beatAt) document.querySelectorAll('#beatsheet .beat').forEach(e=>
    e.classList.toggle('on', +e.dataset.n === S.beatAt));
}
async function delTurn(seq){
  const i = S.transcript.findIndex(t=>t.seq===seq); if (i<0) return;
  S.transcript.splice(i,1); rerenderFeed();
  await busEvent('note', {op:'cut', seq});
}
function sysline(msg){
  const d=document.createElement('div'); d.className='sysline'; d.textContent=msg;
  $('feed').appendChild(d); $('feed').scrollTop=1e9;
}
function thinking(name,color){
  unthink();
  const d=document.createElement('div'); d.className='think'; d.id='think';
  d.innerHTML=`<span style="color:${color||'var(--dim)'}">${esc(name)}</span> processing`;
  $('feed').appendChild(d); $('feed').scrollTop=1e9;
}
function unthink(){ const t=$('think'); if(t) t.remove(); }

function buildMessages(spk, inst, uptoSeq){
  const slice = uptoSeq==null ? S.transcript : S.transcript.filter(t=>t.seq<uptoSeq);
  const lines = slice.map(t=>`${t.name}: ${t.text}`).join('\n\n');
  const user = (lines?`TRANSCRIPT SO FAR:\n${lines}\n\n`:'')
    + `TOPIC: ${$('topic').value.trim()}\n\nYOUR TASK NOW: ${inst}\n\n`
    + `Respond with ONLY your spoken line(s). Do not prefix your own name. Stay in character.`;
  return [{role:'system', content: spk.sys},{role:'user', content:user}];
}
async function busEvent(type, body){
  if (!S.epId || S.replay) return null;
  try{
    const r = await fetch('/api/episode/event',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id:S.epId, type, body, from:'director'})});
    return await r.json();
  }catch(e){ log('bus write failed: '+e.message); return null; }
}

/* ---------------------------------------------------------------- the tailer */
function applyEvent(ev){
  const b = ev.body || {};
  if (ev.type==='line'){
    unthink();
    const t = {...b, seq: ev.seq};
    S.transcript.push(t); renderTurn(t);
  }
  else if (ev.type==='state'){
    if (b.state==='running'){ setStatus('RUNNING','on'); $('humanBox').classList.remove('on'); S.awaiting=null; }
    else if (b.state==='awaiting_human') setStatus('AWAITING HUMAN INPUT','wait');
    else if (b.state==='post'){
      unthink();
      sysline(b.note==='aborted' ? '— RUN ABORTED —' : '— END OF EPISODE —');
      setStatus(b.note==='aborted'?'ABORTED':'DONE', b.note==='aborted'?'err':'on');
      endRun();
    }
    if (b.note) log(`${S.epId} ${b.state}${b.note?': '+b.note:''}`);
  }
  else if (ev.type==='approval_request' && b.kind==='cut_proposal'){
    const t = S.transcript.find(t=>t.seq===b.seq);
    if (t){ t.proposal = {ref:ev.seq, why:b.why}; rerenderFeed(); }
  }
  else if (ev.type==='approval_request' && b.kind==='human_turn'){
    S.awaiting = b;
    if (!S.replay){
      $('humanBox').classList.add('on');
      $('humanHint').textContent = `>> ${b.name} — ${b.inst}`;
      $('humanInput').focus();
    } else sysline(`— ${b.name} was asked to speak here —`);
  }
  else if (ev.type==='note'){
    if (b.op==='cut'){ const i=S.transcript.findIndex(t=>t.seq===b.seq); if(i>=0){ S.transcript.splice(i,1); rerenderFeed(); } }
    else if (b.op==='edit' || b.op==='retake'){ const t=S.transcript.find(t=>t.seq===b.seq); if(t){ t.text=b.text; rerenderFeed(); } }
    else if (b.op==='keep'){ const t=S.transcript.find(t=>t.seq===b.seq); if(t){ delete t.proposal; rerenderFeed(); } }
    else if (b.op==='writers_room_start'){ sysline(`— ${b.writer||'INKWELL'} IS IN THE ROOM${b.bible?' (bible in hand)':''} —`); thinking('INKWELL','var(--pink)'); }
    else if (b.op==='beat'){ S.beatAt = b.n; showBeat(b); }
    else if (b.op==='beatsheet_approved'){ unthink(); sysline('— BEAT SHEET APPROVED —'); markBeatsheetSettled(); }
    else if (b.op==='beatsheet_skipped'){ unthink(); sysline('— RUNNING WITHOUT THE BEAT SHEET —'); S.beats=[]; markBeatsheetSettled(); }
    else if (b.op==='writers_room_done'){ unthink(); log(`writers room: ${b.beats} beats${b.why?' ('+b.why+')':''}`); }
    else if (b.op==='editor_pass_start'){ sysline(`— ${b.editor||'SPLICE'} IS IN THE ROOM (${b.lines} lines) —`); thinking('SPLICE','var(--orange)'); }
    else if (b.op==='editor_pass_done'){
      unthink(); S.editorPass=false;
      sysline(b.proposals ? `— ${b.proposals} CUT${b.proposals===1?'':'S'} PROPOSED — approve or keep each —`
                          : `— SPLICE HAS NO NOTES${b.why?' ('+b.why+')':''} —`);
      log(`editor pass: ${b.proposals} proposal(s)`);
      $('btnEditor').disabled = false;
    }
    else if (b.op==='error' || b.op==='fault'){ unthink(); S.editorPass=false; $('btnEditor').disabled=false;
      sysline('— ENGINE FAULT —'); log('ERROR: '+(b.why||'')); setStatus('ERROR — see system log','err'); }
    else if (b.op==='skip') log(`skipped ${b.sid}: ${b.why}`);
  }
  else if (ev.type==='retake'){
    const t=S.transcript.find(t=>t.seq===b.seq); if(t){ t.text=b.text; rerenderFeed(); }
  }
  else if (ev.type==='artifact' && b.kind==='plan'){
    log(`${S.epId}: ${b.turns} turns planned`);
  }
  else if (ev.type==='artifact' && b.kind==='beatsheet'){
    unthink();
    S.beats = b.beats||[]; S.coldOpen = b.cold_open||'';
    renderBeatsheet(false);
    log(`beat sheet: ${S.beats.length} beats (${b.file})`);
  }
  else if (ev.type==='approval_request' && b.kind==='beatsheet_approval'){
    S.beatGateOpen = !S.replay;
    if (!S.replay) renderBeatsheet(true);
    setStatus('AWAITING BEAT SHEET APPROVAL','wait');
  }
  else if (ev.type==='artifact' && b.kind==='locked_cut'){
    log(`locked cut: ${b.turns} lines`);
  }
}
async function pollBus(){
  if (!S.epId) return;
  try{
    const r = await fetch(`/api/episode/${S.epId}/bus?from=${S.busAt}`);
    const d = await r.json();
    if (!d.ok) throw new Error(d.error||'bus unavailable');
    d.events.forEach(applyEvent);
    S.busAt = d.next;
    if (S.running && d.state==='running' && !S.awaiting && S.transcript.length) thinking('…','var(--dim)');
    if (S.running && (d.state==='post' || d.state==='rendered')) endRun();
  }catch(e){ log('bus poll failed: '+e.message); }
  // Keep tailing while the stage manager is working, or while a crew agent is.
  if (S.running || S.editorPass) S.tailTimer = setTimeout(pollBus, 600);
}
function startTail(id, replay){
  clearTimeout(S.tailTimer);
  S.epId=id; S.busAt=0; S.replay=!!replay; S.transcript=[]; S.awaiting=null;
  S.beats=[]; S.coldOpen=''; S.beatAt=0; S.beatGateOpen=false;
  $('feed').innerHTML=''; $('beatStrip').style.display='none';
  $('epLabel').textContent = id + (replay?' (replay)':'');
  pollBus();
}
function endRun(){
  clearTimeout(S.tailTimer); S.tailTimer=null;
  unthink();
  S.running=false; S.awaiting=null;
  $('humanBox').classList.remove('on');
  $('btnRun').disabled=false; $('btnPause').disabled=true; $('btnAbort').disabled=true;
  loadEpisodes();               // the shelf shows states, so refresh it when one settles
}

/* ---------------------------------------------------------------- human turns */
function submitHuman(){
  const v=$('humanInput').value.trim();
  if (!v || !S.awaiting) return;
  $('humanInput').value=''; $('humanBox').classList.remove('on');
  S.awaiting=null;
  fetch('/api/episode/input',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({id:S.epId, text:v})});
}
function skipHuman(){
  if (!S.awaiting) return;
  $('humanInput').value=''; $('humanBox').classList.remove('on');
  S.awaiting=null;
  fetch('/api/episode/input',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({id:S.epId, text:''})});
}
$('humanInput').addEventListener('keydown',e=>{ if(e.key==='Enter') submitHuman(); });

/* ---------------------------------------------------------------- run control */
function humans(){
  if (S.format!=='roundtable') return [];
  return $('humanNames').value.split(',').map(s=>s.trim()).filter(Boolean).slice(0,3)
    .map((n,i)=>({sid:'h'+i, name:n.toUpperCase()+' [HUMAN]', color:'var(--yellow)', hex:'0xf1fa8c',
                  voice:'en_US-joe-medium', ovoice:'host'+(i+1), human:true}));
}
/* Plans address chairs (slot ids), not people. Whoever was cast in that chair answers. */
function sp(id){ return cast.find(c=>c.slot===id) || cast.find(c=>c.sid===id); }

async function initialize(){
  if (S.running) return;
  const topic=$('topic').value.trim();
  if (!topic){ alert('Enter a topic/thesis first.'); return; }
  S.running=true;
  $('btnRun').disabled=true; $('btnPause').disabled=false; $('btnAbort').disabled=false;
  setStatus('STARTING','wait');
  try{
    const r = await fetch('/api/episode/start',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        format:S.format, topic, rounds:parseInt($('rounds').value)||4,
        cast, humans:humans(), sim:$('simMode').checked,
        writers_room:$('writersRoom').checked,
        endpoint:$('endpoint').value.trim(), api_key:$('apikey').value,
        model:$('model').value.trim(), temperature:parseFloat($('temp').value)||0.5,
      })});
    const j = await r.json();
    if (!j.ok) throw new Error(j.error);
    startTail(j.id, false);
    sysline(`— GHOST PROTOCOL // ${S.format.toUpperCase()} // ${j.id} // "${topic}" —`);
    log(`RUN ${j.id} (${S.format}) — the stage manager has it; this window is a tailer`);
    loadEpisodes();
  }catch(err){
    log('COULD NOT START: '+err.message);
    setStatus('ERROR — see system log','err');
    endRun();
  }
}
function togglePause(){
  // The server owns the loop; pausing is a viewer-side hold on the tailer.
  S.paused=!S.paused;
  $('btnPause').textContent = S.paused?'RESUME':'PAUSE';
  if (S.paused){ clearTimeout(S.tailTimer); setStatus('FEED PAUSED (episode still running)','wait'); }
  else { setStatus('RUNNING','on'); pollBus(); }
}
function abortRun(){
  if (!S.epId) return;
  fetch('/api/episode/abort',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({id:S.epId})});
  log('abort sent to the stage manager');
}
function clearFeed(){
  if (S.running) return alert('Abort the run first.');
  clearTimeout(S.tailTimer);
  S.transcript=[]; S.epId=null; S.replay=false; S.awaiting=null;
  $('epLabel').textContent='—';
  $('feed').innerHTML='<div class="sysline">— awaiting initialization —</div>';
}
async function reroll(seq){
  if (S.running) return alert('Wait for the run to finish (or abort) before re-rolling.');
  const t=S.transcript.find(x=>x.seq===seq); if(!t) return;
  const spk=sp(t.slot||t.sid); if(!spk) return;
  thinking(spk.name,spk.color);
  try{
    let text;
    if ($('simMode').checked){ text = t.text + ' (re-rolled)'; }
    else {
      const body = {endpoint:$('endpoint').value.trim(), api_key:$('apikey').value,
        model:spk.model||$('model').value.trim(), temperature:parseFloat($('temp').value)||0.5,
        messages: buildMessages(spk, t.inst||'Rewrite your last line, better.', seq)};
      const r = await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const j = await r.json();
      if (!j.ok) throw new Error(j.error);
      const pref = new RegExp('^'+spk.name.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'\\s*:\\s*','i');
      text = j.text.trim().replace(pref,'').trim();
    }
    t.text=text; rerenderFeed();
    await busEvent('retake', {seq, text});           // the retake is on the record
  }catch(e){ log('RE-ROLL ERROR: '+e.message); }
  unthink();
}

/* ---------------------------------------------------------------- 3.2 INKWELL: the beat sheet */
function renderBeatsheet(withGate){
  let el = $('beatsheet');
  if (!el){
    el = document.createElement('div'); el.id='beatsheet'; el.className='beatsheet';
    $('feed').appendChild(el);
  }
  const beats = S.beats.map(b=>`
    <div class="beat" data-n="${b.n}">
      <b>BEAT ${b.n}</b> ${esc(b.beat)}
      ${b.collision?`<div class="beatTag">⚡ COLLISION: ${esc(b.collision)}</div>`:''}
      ${b.callback?`<div class="beatTag">↩ CALLBACK: ${esc(b.callback)}</div>`:''}
    </div>`).join('');
  el.innerHTML = `
    <div class="beatHead">✎ BEAT SHEET — INKWELL${S.coldOpen?'':''}</div>
    ${S.coldOpen?`<div class="coldOpen">COLD OPEN: ${esc(S.coldOpen)}</div>`:''}
    ${beats}
    ${withGate?`<div class="beatGate">
        <button class="b go" onclick="approveBeatsheet(true)">✓ APPROVE — SHOOT IT</button>
        <button class="b" onclick="approveBeatsheet(false)">✕ RUN WITHOUT IT</button>
      </div>`:''}`;
  $('feed').scrollTop = 1e9;
}
function markBeatsheetSettled(){
  S.beatGateOpen = false;
  const g = document.querySelector('#beatsheet .beatGate');
  if (g) g.remove();
}
function showBeat(b){
  $('beatStrip').style.display = 'block';
  $('beatStrip').innerHTML = `<b>BEAT ${b.n}/${b.of}</b> ${esc(b.beat)}`;
  document.querySelectorAll('#beatsheet .beat').forEach(e=>
    e.classList.toggle('on', +e.dataset.n === b.n));
}
async function approveBeatsheet(ok){
  markBeatsheetSettled();
  await fetch('/api/episode/approve',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({id:S.epId, kind:'beatsheet', ok})});
}

/* ---------------------------------------------------------------- 3.1 SPLICE: the editor pass */
async function editorPass(){
  if (S.running) return alert('Let the run finish first — SPLICE works on a finished cut.');
  if (!S.epId) return alert('No episode loaded.');
  if (S.replay) return alert('This is a replay. Open a live episode to edit it.');
  if (!S.transcript.length) return alert('Nothing to cut.');
  $('btnEditor').disabled = true;
  S.editorPass = true;
  try{
    const r = await fetch('/api/episode/editor',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id:S.epId, endpoint:$('endpoint').value.trim(), api_key:$('apikey').value,
                           model:$('model').value.trim()})});
    const j = await r.json();
    if (!j.ok) throw new Error(j.error);
    pollBus();                       // the pass runs on the server; watch it land on the bus
  }catch(e){
    S.editorPass=false; $('btnEditor').disabled=false;
    log('editor pass failed: '+e.message);
  }
}
async function approveCut(seq){
  const t = S.transcript.find(x=>x.seq===seq); if(!t) return;
  const ref = t.proposal ? t.proposal.ref : '';
  const i = S.transcript.indexOf(t);
  S.transcript.splice(i,1); rerenderFeed();
  await busEvent('note', {op:'cut', seq, ref, by:'splice'});
  lockIfSettled();
}
async function keepLine(seq){
  const t = S.transcript.find(x=>x.seq===seq); if(!t) return;
  const ref = t.proposal ? t.proposal.ref : '';
  delete t.proposal; rerenderFeed();
  await busEvent('note', {op:'keep', seq, ref, by:'director'});
  lockIfSettled();
}
/* Once every proposal has an answer, the surviving lines are the locked cut —
   the transcript the exporter and the renderer use. */
async function lockIfSettled(){
  if (S.transcript.some(t=>t.proposal)) return;
  await busEvent('artifact', {kind:'locked_cut', turns:S.transcript.length});
  sysline(`— LOCKED CUT: ${S.transcript.length} lines —`);
  log('locked cut written to transcript.json');
}

/* ---------------------------------------------------------------- episode shelf */
async function loadEpisodes(){
  try{
    const list = await (await fetch('/api/episodes')).json();
    const el = $('epList');
    if (!list.length){ el.innerHTML = '<div style="color:var(--dim);font-size:10px">no episodes yet</div>'; return; }
    el.innerHTML = list.map(e=>`<div class="ep" onclick="openEpisode('${e.id}')" title="${esc(e.topic)}">
        <b>${e.id}</b> <span style="color:var(--dim)">${e.format}</span>
        <span class="epState ${e.state}">${e.state}</span>
        <span style="color:var(--dim)">${e.turns} turns</span></div>`).join('');
  }catch(e){ log('episode list unavailable: '+e.message); }
}
async function openEpisode(id){
  if (S.running) return alert('Abort the running episode first.');
  const d = await (await fetch(`/api/episode/${id}/bus?from=0`)).json();
  if (!d.ok) return log('cannot open '+id);
  // A live episode reattaches for real; a finished one opens read-only.
  startTail(id, !d.live);
  if (d.live){ S.running=true; $('btnRun').disabled=true; $('btnPause').disabled=false; $('btnAbort').disabled=false; }
  log(d.live ? `reattached to ${id} — still running on the server` : `replaying ${id} (read only)`);
}
/* ============================================================== dice */
let TOPICS = [];
function rollTopic(){
  const pool = $('dicePool').value;
  const list = TOPICS.filter(t => pool==='any' || t.cat===pool);
  if (!list.length){ log('no topics loaded (topics.json missing?)'); return; }
  const btn = $('btnRoll'); btn.disabled = true;
  let spins = 7;
  const spin = () => {
    const t = list[Math.floor(Math.random()*list.length)];
    $('topic').value = t.t;
    if (--spins > 0) setTimeout(spin, 60 + (7-spins)*35);
    else {
      btn.disabled = false;
      log(`ROLL [${t.cat}] ${t.t}`);
    }
  };
  spin();
}

/* ============================================================== endpoint */
async function pingEndpoint(){
  $('pingOut').textContent='pinging…';
  try{
    const r=await fetch('/api/ping',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({endpoint:$('endpoint').value.trim(), api_key:$('apikey').value})});
    const j=await r.json();
    $('pingOut').textContent=(j.ok?'✔ ':'✘ ')+j.detail;
    $('pingOut').style.color=j.ok?'var(--green)':'var(--red)';
    if (j.ok) loadModels();
  }catch(e){ $('pingOut').textContent='✘ '+e.message; $('pingOut').style.color='var(--red)'; }
}

/* ============================================================== export */
function dl(name, text, mime){
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([text],{type:mime||'text/plain'}));
  a.download=name; a.click(); URL.revokeObjectURL(a.href);
}
function dlTranscript(kind){
  if (!S.transcript.length) return alert('No transcript yet.');
  if (kind==='json'){
    const castInfo = id => { const c = sp(id); return c ? {model:c.model||'(default)', archetype:c.archetype||'', humor_style:c.humor||'', voice:c.voice} : {}; };
    dl('transcript.json', JSON.stringify({show:'THE GHOST PROTOCOL',format:S.format,
      topic:$('topic').value.trim(), date:new Date().toISOString(), show_dir:HIRED.show||'',
      cast: cast.map(c=>({sid:c.sid, slot:c.slot, name:c.name, archetype:c.archetype||'', humor_style:c.humor||'', model:c.model||'(default)', voice:c.voice, image:c.image||'',
                          hired:!!c.hired, version:c.version||''})),
      transcript:S.transcript.map(t=>({speaker:t.name, sid:t.sid, slot:t.slot||t.sid, human:!!t.human, voice:t.voice, text:t.text, ...castInfo(t.slot||t.sid)}))},null,2),
      'application/json');
  } else {
    dl('transcript.txt', S.transcript.map(t=>`${t.name}:\n${t.text}\n`).join('\n'));
  }
}
function shq(s){ return s.replace(/'/g, `'\\''`); }        // shell single-quote escape
function fold(s, w){                                        // naive word wrap
  const out=[]; s.split('\n').forEach(line=>{
    let cur='';
    line.split(' ').forEach(word=>{
      if ((cur+' '+word).trim().length>w){ out.push(cur.trim()); cur=word; }
      else cur+=' '+word;
    });
    out.push(cur.trim());
  });
  return out.filter(Boolean).join('\n');
}
function sanName(n){ return n.replace(/[:'\\,%]/g,'').toUpperCase(); }
function dlCompileScript(){
  if (!S.transcript.length) return alert('No transcript yet — run an episode first.');
  const engine = ttsEngine();
  let sh=`#!/usr/bin/env bash
# ==========================================================================
# THE GHOST PROTOCOL — episode compiler (100% open source: OmniVoice/piper + ffmpeg)
# Generated ${new Date().toISOString()} | format: ${S.format} | tts: ${engine}
#
# Mirrors the server-side RENDER EPISODE.MP4 pipeline: cutout portraits
# (assets/portraits/<sid>.png, transparent) get a Ken Burns zoom + wobbling
# pan + rotation over the format's backdrop (assets/backdrops/${S.format}.jpg);
# lines without a portrait use the plain full-width layout.
#
# Requirements (Arch):
#   sudo pacman -S ffmpeg
#   TTS=omnivoice (the default here) clones each character's designed
#   voiceprint via voice_forge.py — needs this repo and a reachable OmniVoice
#   host, nothing installed. TTS=piper reads local .onnx models instead:
#     yay -S piper-tts-bin        # or: pip install piper-tts
#     Download the voices used below (*.onnx + *.onnx.json) from
#     https://huggingface.co/rhasspy/piper-voices into ./voices/
#   Run this from the repo root so ./assets/ resolves, or set ASSETSDIR.
#
# Engine:  TTS=piper bash compile_show.sh      # force the offline engine
#          GP_OMNIVOICE=http://host:7861 …     # point at another OmniVoice
#
# Run:   bash compile_show.sh     ->  episode.mp4
# ==========================================================================
set -euo pipefail
TTS="\${TTS:-${engine}}"
command -v ffmpeg >/dev/null || { echo "ffmpeg not found"; exit 1; }
if [ "$TTS" = piper ]; then
  command -v piper >/dev/null || { echo "piper not found"; exit 1; }
else
  [ -f voice_forge.py ] || { echo "voice_forge.py not found — run from the repo root, or use TTS=piper"; exit 1; }
fi
W=1920; H=1080; BG=0x0a0e14; PSIZE=640; FPS=25
TEXTBOX="box=1:boxcolor=0x0a0e14@0.55:boxborderw=10"
VOICEDIR="\${VOICEDIR:-voices}"
ASSETSDIR="\${ASSETSDIR:-assets}"
FORMAT="${S.format}"
BACKDROP="$ASSETSDIR/backdrops/$FORMAT.jpg"
mkdir -p build; rm -f build/concat.txt

seg () { # seg <idx> <NAME> <colorhex> <voice> <sid> <ovoice> ; reads text from build/<idx>.txt
  local i=$1 name=$2 color=$3 voice=$4 sid=$5 ovoice=\${6:-} tf="build/$1.txt"
  echo ">> [$i] $name"
  if [ "$TTS" != piper ] && [ -n "$ovoice" ] && [ -f "$ASSETSDIR/voices/$ovoice.wav" ]; then
    python3 voice_forge.py speak --sid "$ovoice" --text "$(cat "$tf")" --out "build/$i.wav" >/dev/null
  else
    piper --model "$VOICEDIR/$voice.onnx" --output_file "build/$i.wav" < "$tf"
  fi
  local dur; dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "build/$i.wav")

  local bgargs=(-f lavfi -i "color=c=$BG:s=\${W}x\${H}:d=$dur")
  local bgprep=""
  if [ -f "$BACKDROP" ]; then
    bgargs=(-loop 1 -t "$dur" -i "$BACKDROP")
    bgprep="scale=\${W}:\${H}:force_original_aspect_ratio=increase,crop=\${W}:\${H}"
  fi

  local portrait="$ASSETSDIR/portraits/$sid.png"
  if [ -n "$sid" ] && [ -f "$portrait" ]; then
    local textx=$((120 + PSIZE + 40))
    local bgref="[1:v]" prepchain=""
    if [ -n "$bgprep" ]; then prepchain="[1:v]\${bgprep}[bgprep];"; bgref="[bgprep]"; fi
    local nframes; nframes=$(awk -v d="$dur" -v fps="$FPS" 'BEGIN{printf "%d", (d*fps)+0.5}')
    local fc="[0:v]scale=1536:1536,zoompan=z='min(zoom+0.0008,1.15)':x='iw/2-(iw/zoom/2)+40*sin(on/12)':y='ih/2-(ih/zoom/2)+25*sin(on/9+1)':d=\${nframes}:s=\${PSIZE}x\${PSIZE}:fps=\${FPS},format=rgba,rotate='0.035*sin(t*1.3)':c=black@0:ow=iw:oh=ih[portrait];\${prepchain}\${bgref}[portrait]overlay=120:100[bg1];[bg1]drawtext=text='[ $name ]':x=120:y=$((PSIZE + 140)):fontsize=42:fontcolor=$color:font=Monospace:\${TEXTBOX},drawtext=textfile='$tf':x=\${textx}:y=160:fontsize=32:fontcolor=0xf8f8f2:font=Monospace:line_spacing=14:\${TEXTBOX}[vout]"
    ffmpeg -y -v error -loop 1 -t "$dur" -i "$portrait" "\${bgargs[@]}" -i "build/$i.wav" \\
      -filter_complex "$fc" -map "[vout]" -map 2:a \\
      -c:v libx264 -preset fast -pix_fmt yuv420p -c:a aac -shortest "build/$i.mp4"
  else
    local prepprefix=""
    [ -n "$bgprep" ] && prepprefix="\${bgprep},"
    ffmpeg -y -v error "\${bgargs[@]}" -i "build/$i.wav" \\
      -vf "\${prepprefix}drawtext=text='[ $name ]':x=120:y=140:fontsize=46:fontcolor=$color:font=Monospace:\${TEXTBOX},drawtext=textfile='$tf':x=120:y=260:fontsize=34:fontcolor=0xf8f8f2:font=Monospace:line_spacing=16:\${TEXTBOX}" \\
      -c:v libx264 -preset fast -pix_fmt yuv420p -c:a aac -shortest "build/$i.mp4"
  fi
  echo "file '$i.mp4'" >> build/concat.txt
}

`;
  S.transcript.forEach((t,ix)=>{
    const i=String(ix).padStart(3,'0');
    const eof='GP_EOF_'+i;
    const wrapw = t.sid ? 48 : 74;
    sh += `cat > build/${i}.txt <<'${eof}'\n${fold(t.text,wrapw)}\n${eof}\n`;
    sh += `seg ${i} '${shq(sanName(t.name))}' ${t.hex||'0xf8f8f2'} '${shq(t.voice||'en_US-lessac-medium')}' '${shq(t.sid||'')}' '${shq(t.ovoice||t.sid||'')}'\n\n`;
  });
  sh += `ffmpeg -y -v error -f concat -safe 0 -i build/concat.txt -c copy episode.mp4
echo "=========================================="
echo " DONE -> episode.mp4  ($(du -h episode.mp4 | cut -f1))"
echo "=========================================="
`;
  dl('compile_show.sh', sh, 'text/x-shellscript');
  log('compile_show.sh exported ('+S.transcript.length+' segments)');
}
async function renderEpisode(){
  if (!S.transcript.length) return alert('No transcript yet — run an episode first.');
  const btn = $('btnRender'), origText = btn.textContent;
  btn.disabled = true; btn.textContent = 'RENDERING…';
  $('renderResult').innerHTML = '';
  log('render: starting ('+S.transcript.length+' segments)…');
  try{
    const segments = S.transcript.map(t=>({sid:t.sid, name:t.name, text:t.text,
      voice:t.voice||'en_US-lessac-medium', ovoice:t.ovoice||t.sid||'', hex:t.hex||'0xf8f8f2'}));
    const r = await fetch('/api/render',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({segments, format:S.format, engine:ttsEngine()})});
    const j = await r.json();
    if (!j.ok) throw new Error(j.error);
    log('render: done -> '+j.file+' ('+j.size_mb+' MB)');
    $('renderResult').innerHTML =
      `<video controls style="width:100%;border-radius:4px;margin-bottom:6px" src="${j.url}"></video>
       <a class="b go" style="display:block;text-align:center;text-decoration:none" href="${j.url}" download="${esc(j.file)}">⬇ DOWNLOAD ${esc(j.file)}</a>`;
  }catch(e){
    log('render ERROR: '+e.message);
    alert('Render failed: '+e.message);
  }
  btn.disabled = false; btn.textContent = origText;
}

/* ============================================================== walkthrough tour */
function ensureCfgVisible(){ $('cfg').classList.remove('hide'); $('togCfg').classList.add('on'); }
function ensureExportVisible(){ $('right').classList.remove('hide'); $('right').classList.add('pin'); $('togExp').classList.add('on'); }
const TOUR = [
 {sel:'#fmt', title:'01 // FORMAT', onEnter:ensureCfgVisible,
  body:'Pick a debate format here. For your first episode, try <b>Socratic Stress-Test</b> — shortest, fewest moving parts, runs start-to-finish with no human input needed.'},
 {sel:'#topic', title:'TOPIC / THESIS', onEnter:ensureCfgVisible,
  body:'Write a clear, arguable one-line claim. Socratic works best on a binary position — a real "yes" side and "no" side.'},
 {sel:'#rounds', title:'ROUNDS & TEMP', onEnter:ensureCfgVisible,
  body:'Rounds set episode length — 4 rounds is a solid 8–10 min episode. Temp controls response randomness; 0.5 is a good default.'},
 {sel:'#castList', title:'02 // CAST', onEnter:ensureCfgVisible,
  body:'Each speaker\'s name, system prompt, model override, and Piper voice — all editable. Defaults are ready to go, no changes needed yet.'},
 {sel:'#endpoint', title:'03 // ENGINE', onEnter:ensureCfgVisible,
  body:'Should already point at your Bifrost gateway. Leave API KEY blank if Bifrost holds the keys.'},
 {sel:'#btnPing', title:'TEST CONNECTION', onEnter:ensureCfgVisible,
  body:'Click this now. You should see a green ✔ reachable message below it. If it fails, the Bifrost container may be down.'},
 {sel:'#btnRun', title:'▶ INITIALIZE',
  body:'Starts the episode <b>on the server</b>. The stage manager runs the turns and writes every event to the episode\'s bus; this window just tails it. Close the tab mid-run and the episode keeps going.'},
 {sel:'#feed', title:'THE FEED',
  body:'Lines stream in as they land on the bus. After the run, click any line to edit it, ↻ RE-ROLL to regenerate, or ✕ CUT to remove it — each of those is recorded as an event, and transcript.json is derived from the bus.'},
 {sel:'#epList', title:'05 // EPISODES', onEnter:ensureExportVisible,
  body:'Every run is a directory with its own bus. Click one to replay it read-only, or to reattach to a run still going.'},
 {sel:'#right', title:'04 // EXPORT', onEnter:ensureExportVisible,
  body:'Grab the transcript, or click <b>▶ RENDER EPISODE.MP4</b> — the server runs piper + ffmpeg for you and hands back a playable <b>episode.mp4</b>. No shell needed.'},
];
let tourIdx = -1, tourLastEl = null;
function tourClearHighlight(){ if (tourLastEl){ tourLastEl.classList.remove('tour-spot'); tourLastEl=null; } }
function tourStart(){
  tourIdx = 0;
  $('tourBackdrop').style.display='block';
  renderTourStep();
}
function tourClose(){
  tourIdx = -1;
  tourClearHighlight();
  $('tourBackdrop').style.display='none';
  $('tourCard').style.display='none';
}
function tourNext(){ if (tourIdx < TOUR.length-1){ tourIdx++; renderTourStep(); } else tourClose(); }
function tourBack(){ if (tourIdx > 0){ tourIdx--; renderTourStep(); } }
function tourPositionCard(rect){
  const card=$('tourCard'), cw=card.offsetWidth, ch=card.offsetHeight;
  const vw=window.innerWidth, vh=window.innerHeight, pad=16;
  let top, left;
  if (!rect){ top=(vh-ch)/2; left=(vw-cw)/2; }
  else if (rect.right+pad+cw < vw){ left=rect.right+pad; top=Math.min(Math.max(rect.top,pad), vh-ch-pad); }
  else if (rect.bottom+pad+ch < vh){ top=rect.bottom+pad; left=Math.min(Math.max(rect.left,pad), vw-cw-pad); }
  else if (rect.left-pad-cw > 0){ left=rect.left-pad-cw; top=Math.min(Math.max(rect.top,pad), vh-ch-pad); }
  else { top=Math.max(pad, rect.top-pad-ch); left=Math.min(Math.max(rect.left,pad), vw-cw-pad); }
  card.style.top=top+'px'; card.style.left=left+'px';
}
function renderTourStep(){
  tourClearHighlight();
  const step = TOUR[tourIdx];
  if (step.onEnter) step.onEnter();
  const card = $('tourCard');
  card.style.display='block';
  $('tourStepNum').textContent = (tourIdx+1)+' / '+TOUR.length;
  $('tourTitle').innerHTML = step.title;
  $('tourBody').innerHTML = step.body;
  $('tourBack').disabled = tourIdx===0;
  $('tourNext').textContent = tourIdx===TOUR.length-1 ? 'FINISH' : 'NEXT ▶';
  requestAnimationFrame(()=>{
    const el = step.sel ? document.querySelector(step.sel) : null;
    if (el){
      el.scrollIntoView({block:'center', behavior:'smooth'});
      el.classList.add('tour-spot');
      tourLastEl = el;
      setTimeout(()=>tourPositionCard(el.getBoundingClientRect()), 260);
    } else {
      tourPositionCard(null);
    }
  });
}
window.addEventListener('resize', ()=>{ if (tourIdx>=0) tourPositionCard(tourLastEl?tourLastEl.getBoundingClientRect():null); });
document.addEventListener('keydown', e=>{ if (e.key==='Escape' && tourIdx>=0) tourClose(); });

/* ============================================================== cast pool + bio */
function togglePool(){
  const open = $('poolPanel').classList.toggle('hide') === false;
  $('togPool').classList.toggle('on', open);
  if (open) renderPool();
}
function renderPool(){
  const list = Object.values(CHAR_META);
  $('poolGrid').innerHTML = list.map(c => `
    <div class="poolCard" onclick="openBio('${c.sid}')">
      ${c.image ? `<img src="/${c.image}">` : ''}
      <b style="color:${hexOf(c.color)}">${esc(c.name)}</b>
      <div class="arch">${esc((c.archetype||'').toUpperCase())}</div>
    </div>`).join('');
}
function hexOf(h){ return h && h.startsWith('#') ? h : (h||'#f8f8f2'); }
/* tiny markdown -> HTML, just enough for our own bio files */
function mdToHtml(md){
  const lines = md.split('\n');
  let html = '', inList = false;
  const closeList = () => { if (inList){ html += '</ul>'; inList = false; } };
  const inline = s => esc(s)
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>');
  lines.forEach(line => {
    if (/^---+$/.test(line.trim())){ closeList(); html += '<hr>'; return; }
    if (line.startsWith('## ')){ closeList(); html += `<h2>${inline(line.slice(3))}</h2>`; return; }
    if (line.startsWith('# ')){ closeList(); html += `<h1>${inline(line.slice(2))}</h1>`; return; }
    if (line.startsWith('> ')){ closeList(); html += `<blockquote>${inline(line.slice(2))}</blockquote>`; return; }
    if (line.startsWith('- ')){ if(!inList){ html += '<ul>'; inList = true; } html += `<li>${inline(line.slice(2))}</li>`; return; }
    closeList();
    if (line.trim()) html += `<p>${inline(line)}</p>`;
  });
  closeList();
  return html;
}
async function openBio(sid){
  $('bioBackdrop').style.display = 'block';
  $('bioModal').style.display = 'block';
  $('bioContent').innerHTML = 'loading…';
  try{
    const r = await fetch(`/api/characters/${encodeURIComponent(sid)}/bio`);
    if (!r.ok) throw new Error('no bio on file for this character');
    const md = await r.text();
    $('bioContent').innerHTML = mdToHtml(md);
  }catch(e){
    $('bioContent').innerHTML = `<p>Couldn't load this character's soul: ${esc(e.message)}</p>`;
  }
}
function closeBio(){
  $('bioBackdrop').style.display = 'none';
  $('bioModal').style.display = 'none';
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeBio(); });

/* ============================================================== boot */
(async function(){
  let defModel = 'ollama/qwen3:14b';
  try{
    const d = await (await fetch('/api/defaults')).json();
    $('endpoint').value=d.endpoint; $('apikey').value=d.api_key; defModel=d.model;
  }catch(e){ $('endpoint').value='http://localhost:8080/v1/chat/completions'; }
  $('model').innerHTML = `<option value="${esc(defModel)}">${esc(defModel)}</option>`;
  try{
    TOPICS = await (await fetch('/api/topics')).json();
    log(`topic bank loaded: ${TOPICS.length} theses (${TOPICS.filter(t=>t.cat==='serious').length} serious / ${TOPICS.filter(t=>t.cat==='absurd').length} absurd)`);
  }catch(e){ log('topic bank unavailable: '+e.message); }
  await loadCharacterMeta();
  await loadHiredCast();
  await loadVoiceprints();
  if (!OVOICES.length) $('ttsEngine').value = 'piper';   // nothing designed yet — don't promise what we can't do
  loadCast();
  loadModels();
  loadEpisodes();
  log('GHOST PROTOCOL studio online.');
  log('Tip: enable SIMULATION MODE to test the flow with zero API calls.');
})();
</script>
</body>
</html>
"""

def headless(argv: list) -> int:
    """python3 ghost_protocol_studio.py --episode ep-002 --run

    Runs an episode with no browser: re-runs an existing episode directory's brief,
    or starts a fresh one from --format/--topic. Overnight batch generation."""
    def opt(name, default=None):
        return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else default

    eid = opt("--episode")
    src = get_episode(eid) if eid else None
    if eid and not src:
        print(f"no such episode: {eid} (looked in {EPISODES_DIR})")
        return 1
    fmt = opt("--format") or (src.meta.get("format") if src else "socratic")
    topic = opt("--topic") or (src.meta.get("topic") if src else "")
    rounds = int(opt("--rounds") or (src.meta.get("rounds") if src else 4))
    sim = "--sim" in argv or (src.meta.get("sim") if src else False)
    # Cast: the source episode's, else whoever is hired, else the plan finds empty chairs.
    cast = src.meta.get("cast") if src else None
    if not cast:
        cast = cast_for_format(fmt, scan_show()["cast"])
    if not cast:
        print(f"nobody hired can play {fmt} — hire actors into {SHOW_DIR or '(no show dir)'}/cast/")
        return 1
    if not topic:
        print("headless needs a --topic (or an --episode whose brief has one)")
        return 1
    res = start_episode({"format": fmt, "topic": topic, "rounds": rounds, "cast": cast,
                         "humans": [], "sim": sim, "writers_room": "--writers-room" in argv,
                         "endpoint": DEFAULT_ENDPOINT, "api_key": DEFAULT_KEY, "model": DEFAULT_MODEL})
    if not res.get("ok"):
        print("could not start:", res.get("error"))
        return 1
    ep = get_episode(res["id"])
    print(f"  {ep.id} // {fmt} // \"{topic}\"{'  [SIMULATION]' if sim else ''}\n")
    seen = 0
    while True:
        for ev in ep.since(seen):
            seen = ev["seq"] + 1
            if ev["type"] == "line":
                print(f"  {ev['body'].get('name')}:\n    {ev['body'].get('text')}\n")
            elif ev["type"] == "state":
                print(f"  -- {ev['body'].get('state').upper()} {ev['body'].get('note','')}")
            elif ev["type"] == "approval_request" and ev["body"].get("kind") == "human_turn":
                # Nobody is watching a headless run — the human chair sits it out.
                print(f"  -- {ev['body'].get('name')} skipped (headless)")
                ep.human_text = None
                ep.human_gate.set()
            elif ev["type"] == "approval_request" and ev["body"].get("kind") == "beatsheet_approval":
                print(f"  -- beat sheet approved unattended ({ev['body'].get('beats')} beats)")
                ep.approval_ok = True
                ep.approval_gate.set()
            elif ev["type"] == "artifact" and ev["body"].get("kind") == "beatsheet":
                if ev["body"].get("cold_open"):
                    print(f"  -- COLD OPEN: {ev['body']['cold_open']}")
                for b in ev["body"].get("beats", []):
                    print(f"     beat {b['n']}: {b['beat']}")
            elif ev["type"] == "note":
                print(f"  -- note: {ev['body']}")
        if ep.meta.get("state") in ("post", "rendered"):
            break
        time.sleep(0.2)
    print(f"\n  {len(ep.transcript())} turns -> {os.path.join(ep.path, 'transcript.json')}")
    return 0


if __name__ == "__main__":
    import sys
    if "--run" in sys.argv or "--episode" in sys.argv:
        raise SystemExit(headless(sys.argv))
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"""
  ╔════════════════════════════════════════════════╗
  ║        THE GHOST PROTOCOL // studio            ║
  ║   open  ->  http://localhost:{PORT}             ║
  ║   bind: {BIND}  (GP_BIND=0.0.0.0 for LAN)
  ║   show: {SHOW_DIR or '(none — built-in cast; set GP_SHOW_DIR)'}
  ║   endpoint: {DEFAULT_ENDPOINT}
  ║   (change in UI, or GP_ENDPOINT / GP_API_KEY)  ║
  ╚════════════════════════════════════════════════╝
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nkernel halted.")
