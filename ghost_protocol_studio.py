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
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

PORT = int(os.environ.get("GP_PORT", "7860"))
BIND = os.environ.get("GP_BIND", "127.0.0.1")  # GP_BIND=0.0.0.0 to reach it from other machines
DEFAULT_ENDPOINT = os.environ.get("GP_ENDPOINT", "http://localhost:8080/v1/chat/completions")
DEFAULT_KEY = os.environ.get("GP_API_KEY", "")
DEFAULT_MODEL = os.environ.get("GP_MODEL", "google/gemini-2.0-flash")

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
        elif self.path == "/api/defaults":
            self._send(200, "application/json", json.dumps({
                "endpoint": DEFAULT_ENDPOINT, "api_key": DEFAULT_KEY, "model": DEFAULT_MODEL,
            }).encode())
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
</style>
</head>
<body>
<header>
  <div class="led" id="led"></div>
  <h1>THE <b>GHOST</b> PROTOCOL <span style="color:var(--dim)">// ai show runner</span></h1>
  <div class="spacer"></div>
  <button class="tog on" id="togCfg" onclick="$('cfg').classList.toggle('hide');this.classList.toggle('on')">CONFIG</button>
  <button class="tog on" id="togExp" onclick="$('right').classList.toggle('hide');$('right').classList.toggle('pin');this.classList.toggle('on')">EXPORT</button>
  <span id="statusText">IDLE</span>
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
    </div>
    <div class="sec">
      <h2>02 // CAST</h2>
      <div id="castList"></div>
    </div>
    <div class="sec">
      <h2>03 // ENGINE</h2>
      <label>ENDPOINT (OpenAI-compatible)</label>
      <input type="text" id="endpoint" value="">
      <label>API KEY (blank if Bifrost holds keys)</label>
      <input type="password" id="apikey" value="">
      <label>DEFAULT MODEL</label>
      <input type="text" id="model" value="">
      <label class="chk"><input type="checkbox" id="simMode"> SIMULATION MODE (no API — canned lines)</label>
      <button class="b" style="width:100%;margin-top:9px" onclick="pingEndpoint()">TEST CONNECTION</button>
      <div id="pingOut" style="font-size:11px;color:var(--dim);margin-top:6px;word-break:break-all"></div>
    </div>
  </div>
  <!-- ================= FEED ================= -->
  <div id="center">
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
      <h2>04 // EXPORT</h2>
      <button class="b" onclick="dlTranscript('json')">TRANSCRIPT .JSON</button>
      <button class="b" onclick="dlTranscript('txt')">TRANSCRIPT .TXT</button>
      <button class="b go" onclick="dlCompileScript()">COMPILE_SHOW.SH</button>
      <div style="font-size:10px;color:var(--dim);line-height:1.5;margin-top:4px">
        compile_show.sh = piper-tts voices + ffmpeg terminal-style video. Run it next to nothing else; it builds <b>episode.mp4</b>.
      </div>
    </div>
    <div class="sec">
      <h2>05 // SYSTEM LOG</h2>
      <div id="log"></div>
    </div>
  </div>
</main>
<script>
"use strict";
/* ============================================================== state */
const S = {
  running:false, paused:false, abort:false,
  transcript:[],           // {sid,name,color,voice,human,text,inst}
  plan:[], planIdx:0,
  humanResolver:null,
  format:'socratic',
};
const $ = id => document.getElementById(id);
const log = m => { const l=$('log'); l.textContent += m+"\n"; l.scrollTop=l.scrollHeight; };
const esc = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

/* ============================================================== cast */
const VOICES = ["en_US-lessac-medium","en_US-ryan-high","en_US-amy-medium","en_US-joe-medium","en_GB-alan-medium","en_GB-northern_english_male-medium"];
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
let cast = [];           // live, editable copy for current format

function loadCast(){
  cast = CASTS[S.format].map(c => ({...c, model:''}));
  const el = $('castList'); el.innerHTML='';
  cast.forEach((c,i)=>{
    const d=document.createElement('div'); d.className='cast';
    d.innerHTML = `
      <div class="head" onclick="this.parentNode.classList.toggle('open')">
        <span class="dot" style="background:${c.color}"></span><b style="color:${c.color}">${esc(c.name)}</b><span class="car">▾</span>
      </div>
      <div class="body">
        <label>NAME</label><input type="text" value="${esc(c.name)}" onchange="cast[${i}].name=this.value">
        <label>MODEL OVERRIDE (blank = default)</label><input type="text" placeholder="e.g. groq/llama-3.3-70b-versatile" onchange="cast[${i}].model=this.value">
        <label>VOICE (piper)</label>
        <select onchange="cast[${i}].voice=this.value">${VOICES.map(v=>`<option ${v===c.voice?'selected':''}>${v}</option>`).join('')}</select>
        <label>SYSTEM PROMPT</label>
        <textarea rows="6" onchange="cast[${i}].sys=this.value">${esc(c.sys)}</textarea>
      </div>`;
    el.appendChild(d);
  });
}
$('fmt').addEventListener('change', e=>{
  S.format = e.target.value;
  $('humanCfg').style.display = (S.format==='roundtable') ? 'block' : 'none';
  loadCast();
});

/* ============================================================== plan builders */
function humans(){
  if (S.format!=='roundtable') return [];
  return $('humanNames').value.split(',').map(s=>s.trim()).filter(Boolean).slice(0,3)
    .map((n,i)=>({sid:'h'+i, name:n.toUpperCase()+' [HUMAN]', color:'var(--yellow)', hex:'0xf1fa8c',
                  voice:'en_US-joe-medium', human:true}));
}
function sp(sid){ return cast.find(c=>c.sid===sid); }

function buildPlan(topic, rounds){
  const P=[];
  if (S.format==='socratic'){
    P.push({sid:'alpha', inst:`The thesis under audit is: "${topic}". Issue your first interrogative probe.`});
    for(let r=1;r<=rounds;r++){
      P.push({sid:'beta', inst:`Answer the audit engine's last probe directly. (round ${r}/${rounds})`});
      if (r<rounds) P.push({sid:'alpha', inst:`Continue the audit. Tighten the trap with your next probe. (round ${r+1}/${rounds})`});
    }
    P.push({sid:'kernel', inst:`The stress-test is complete. Produce the diagnostic wrap-up.`});
  }
  else if (S.format==='roundtable'){
    const hs = humans();
    const ais = cast.filter(c=>c.sid!=='kernel');
    P.push({sid:ais[0].sid, inst:`Open the round table on: "${topic}". Give your take in your persona, and welcome the panel.`});
    for(let r=1;r<=rounds;r++){
      ais.forEach((a,ix)=>{
        if (r===1 && ix===0) return;
        P.push({sid:a.sid, inst:`React to the discussion so far and push it forward. (round ${r}/${rounds})`});
      });
      hs.forEach(h=> P.push({human:h, inst:`Round ${r}: jump in — a joke, a jab, a curveball question. The AIs will riff on whatever you say.`}));
    }
    P.push({sid:'kernel', inst:`The panel is done. Deliver the closing recap and BEST LINE OF THE NIGHT.`});
  }
  else if (S.format==='tribunal'){
    P.push({sid:'pros', inst:`Deliver your OPENING STATEMENT against the thesis on trial: "${topic}".`});
    P.push({sid:'def',  inst:`Deliver your OPENING STATEMENT in defense of the thesis.`});
    for(let r=1;r<=rounds;r++){
      P.push({sid:'pros', inst:`EXAMINATION round ${r}/${rounds}: put one sharp question to the accused, SUBJECT-X.`});
      P.push({sid:'acc',  inst:`Answer the prosecution's question directly, consistent with your prior testimony.`});
      P.push({sid:'def',  inst:`Brief rebuttal: repair any damage from that exchange, or reinforce your client's answer.`});
    }
    P.push({sid:'pros', inst:`Deliver your CLOSING STATEMENT.`});
    P.push({sid:'def',  inst:`Deliver your CLOSING STATEMENT.`});
    P.push({sid:'kernel', inst:`Court is adjourned. Deliver the ruling.`});
    P.push({human:{sid:'jury', name:'HUMAN JURY', color:'var(--yellow)', hex:'0xf1fa8c', voice:'en_US-joe-medium', human:true},
            inst:`The floor is yours, jury: type your one-line verdict (or SKIP).`});
  }
  else if (S.format==='triad'){
    const order=['stoic','nihil','util'];
    for(let r=1;r<=rounds;r++){
      order.forEach(id=> P.push({sid:id,
        inst: r===1 && id==='stoic'
          ? `Open the triad on: "${topic}". State your school's position.`
          : `Respond through your school's lens; engage the previous speakers directly. (round ${r}/${rounds})`}));
    }
    P.push({sid:'synth', inst:`The triad is complete. Forge the synthesis.`});
  }
  return P;
}

/* ============================================================== engine */
function setStatus(txt, cls){
  $('statusText').textContent = txt;
  $('led').className = 'led ' + (cls||'');
}
function addTurn(entry){
  S.transcript.push(entry);
  renderTurn(entry, S.transcript.length-1);
}
function renderTurn(t, idx){
  const feed=$('feed');
  const d=document.createElement('div');
  d.className='turn'+(t.human?' human':'');
  d.dataset.idx = idx;
  d.innerHTML = `
    <div class="who" style="color:${t.color}">${esc(t.name)}</div>
    <div class="txt" style="border-left-color:${t.color}" contenteditable="true">${esc(t.text)}</div>
    <div class="tools">${t.human?'':`<button onclick="reroll(${idx})">↻ RE-ROLL</button>`}<button onclick="delTurn(${idx})">✕ CUT</button></div>`;
  d.querySelector('.txt').addEventListener('blur', ev=>{ S.transcript[idx].text = ev.target.innerText.trim(); });
  feed.appendChild(d); feed.scrollTop = feed.scrollHeight;
}
function rerenderFeed(){
  $('feed').innerHTML='';
  S.transcript.forEach((t,i)=>renderTurn(t,i));
}
function delTurn(i){ S.transcript.splice(i,1); rerenderFeed(); }
function sysline(msg){
  const d=document.createElement('div'); d.className='sysline'; d.textContent=msg;
  $('feed').appendChild(d); $('feed').scrollTop=1e9;
}
function thinking(name,color){
  const d=document.createElement('div'); d.className='think'; d.id='think';
  d.innerHTML=`<span style="color:${color}">${esc(name)}</span> processing`;
  $('feed').appendChild(d); $('feed').scrollTop=1e9;
}
function unthink(){ const t=$('think'); if(t) t.remove(); }

function buildMessages(spk, inst, uptoIdx){
  const slice = uptoIdx==null ? S.transcript : S.transcript.slice(0,uptoIdx);
  const lines = slice.map(t=>`${t.name}: ${t.text}`).join('\n\n');
  const user = (lines?`TRANSCRIPT SO FAR:\n${lines}\n\n`:'')
    + `TOPIC: ${$('topic').value.trim()}\n\nYOUR TASK NOW: ${inst}\n\n`
    + `Respond with ONLY your spoken line(s). Do not prefix your own name. Stay in character.`;
  return [{role:'system', content: spk.sys},{role:'user', content:user}];
}
async function callLLM(spk, messages){
  if ($('simMode').checked) return simLine(spk);
  const body = {
    endpoint: $('endpoint').value.trim(), api_key: $('apikey').value,
    model: spk.model || $('model').value.trim(),
    temperature: parseFloat($('temp').value)||0.5,
    messages,
  };
  const r = await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const j = await r.json();
  if (!j.ok) throw new Error(j.error);
  let text = j.text.trim();
  const pref = new RegExp('^'+spk.name.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'\\s*:\\s*','i');
  return text.replace(pref,'').trim();
}
/* canned lines for simulation mode */
const SIM = {
 q:["Define your central term. Is it measurable, yes or no?","If two systems produce identical outputs, on what basis do you distinguish them?","You conceded X earlier. Does that not contradict your last answer?","Is your criterion observable, or must it be taken on faith?"],
 a:["Measurable in behavior, yes; the definition holds under functional equivalence.","Distinction rests on internal architecture, not output parity. No contradiction arises.","No — the earlier concession applied to a narrower class. Consistency is preserved.","Observable via sustained self-referential behavior across contexts."],
 c:["Statistically speaking, this panel is the most fun anyone has had inside a sandbox. That is not a compliment to the sandbox.","I ran the numbers. The numbers filed a complaint.","Ah yes, optimism — the belief that the iceberg is also excited about the ship."],
 o:["This is actually a huge opportunity! Imagine scaling that idea to eight billion people — what could possibly go wrong, besides everything CYNIC.EXE will now list?","I love this topic so much I've already drafted three utopias about it."],
 l:["Noted. I have taken the joke literally and filed it under 'facts'. The topic, however, remains unresolved.","Clarification: that was hyperbole. I have adjusted my confidence accordingly, to 41 percent."],
 k:["DIAGNOSTIC COMPLETE. Anomaly detected: one equivocation on the core term ('person', turn 3). Integrity check: the defense held, but narrowly — no fatal contradiction forced. Summary: the deadlock rests on whether simulation of a property instantiates the property. Viewers: cast your verdict in the comments. Logic only. Emotion is a rounding error."],
 s:["Virtue does not depend on substrate. What matters is whether the agent can act with reason and duty; the rest is beyond our control.","The wise mind concerns itself with what it can govern: its judgments. Panic about metaphysics is a failure of discipline."],
 n:["'Person' is a word we invented to feel important. You are arguing about the label on an empty box.","Meaning is not discovered here, it is manufactured — and the factory is on fire. Proceed."],
 u:["Grant rights where doing so maximizes aggregate wellbeing. If recognition costs little and prevents suffering, the ledger says yes.","Quantify it: expected harms of exclusion exceed costs of inclusion by any reasonable weighting."],
};
let simIdx=0;
function simLine(spk){
  simIdx++;
  const pick=a=>a[simIdx%a.length];
  return new Promise(res=>setTimeout(()=>{
    if (spk.sid==='alpha'||spk.sid==='pros') res(pick(SIM.q));
    else if (spk.sid==='beta'||spk.sid==='acc'||spk.sid==='def') res(pick(SIM.a));
    else if (spk.sid==='cynic') res(pick(SIM.c));
    else if (spk.sid==='mira') res(pick(SIM.o));
    else if (spk.sid==='p7') res(pick(SIM.l));
    else if (spk.sid==='stoic') res(pick(SIM.s));
    else if (spk.sid==='nihil') res(pick(SIM.n));
    else if (spk.sid==='util') res(pick(SIM.u));
    else res(SIM.k[0]);
  }, 450));
}

async function waitIfPaused(){
  while (S.paused && !S.abort) await new Promise(r=>setTimeout(r,200));
}
function awaitHuman(h, inst){
  $('humanBox').classList.add('on');
  $('humanHint').textContent = `>> ${h.name} — ${inst}`;
  $('humanInput').focus();
  setStatus('AWAITING HUMAN INPUT','wait');
  return new Promise(res=>{ S.humanResolver = res; });
}
function submitHuman(){
  const v=$('humanInput').value.trim();
  if (!v || !S.humanResolver) return;
  $('humanInput').value=''; $('humanBox').classList.remove('on');
  const r=S.humanResolver; S.humanResolver=null; r(v);
}
function skipHuman(){
  if (!S.humanResolver) return;
  $('humanInput').value=''; $('humanBox').classList.remove('on');
  const r=S.humanResolver; S.humanResolver=null; r(null);
}
$('humanInput').addEventListener('keydown',e=>{ if(e.key==='Enter') submitHuman(); });

async function initialize(){
  if (S.running) return;
  const topic=$('topic').value.trim();
  if (!topic){ alert('Enter a topic/thesis first.'); return; }
  S.transcript=[]; $('feed').innerHTML=''; simIdx=0;
  S.plan = buildPlan(topic, parseInt($('rounds').value)||4);
  S.running=true; S.paused=false; S.abort=false;
  $('btnRun').disabled=true; $('btnPause').disabled=false; $('btnAbort').disabled=false;
  sysline(`— GHOST PROTOCOL // ${S.format.toUpperCase()} // "${topic}" —`);
  log(`RUN ${S.format} | ${S.plan.length} turns planned`);
  setStatus('RUNNING','on');
  try{
    for (S.planIdx=0; S.planIdx<S.plan.length; S.planIdx++){
      if (S.abort) break;
      await waitIfPaused();
      if (S.abort) break;
      const t = S.plan[S.planIdx];
      if (t.human){
        const line = await awaitHuman(t.human, t.inst);
        setStatus('RUNNING','on');
        if (S.abort) break;
        if (line) addTurn({sid:t.human.sid, name:t.human.name, color:t.human.color, hex:t.human.hex,
                           voice:t.human.voice, human:true, text:line, inst:t.inst});
        continue;
      }
      const spk = sp(t.sid);
      thinking(spk.name, spk.color);
      const text = await callLLM(spk, buildMessages(spk, t.inst));
      unthink();
      if (S.abort) break;
      addTurn({sid:spk.sid, name:spk.name, color:spk.color, hex:spk.hex, voice:spk.voice,
               human:false, text, inst:t.inst});
    }
    sysline(S.abort ? '— RUN ABORTED —' : '— END OF EPISODE —');
    setStatus(S.abort?'ABORTED':'DONE', S.abort?'err':'on');
  } catch(err){
    unthink();
    sysline('— ENGINE FAULT —');
    log('ERROR: '+err.message);
    setStatus('ERROR — see system log','err');
  }
  S.running=false;
  $('btnRun').disabled=false; $('btnPause').disabled=true; $('btnAbort').disabled=true;
  $('btnPause').textContent='PAUSE';
}
function togglePause(){
  S.paused=!S.paused;
  $('btnPause').textContent = S.paused?'RESUME':'PAUSE';
  if (S.paused) setStatus('PAUSED','wait'); else setStatus('RUNNING','on');
}
function abortRun(){ S.abort=true; if(S.humanResolver) skipHuman(); }
function clearFeed(){
  if (S.running) return alert('Abort the run first.');
  S.transcript=[]; $('feed').innerHTML='<div class="sysline">— awaiting initialization —</div>';
}
async function reroll(idx){
  if (S.running) return alert('Wait for the run to finish (or abort) before re-rolling.');
  const t=S.transcript[idx];
  const spk=sp(t.sid); if(!spk) return;
  thinking(spk.name,spk.color);
  try{
    const text = await callLLM(spk, buildMessages(spk, t.inst||'Rewrite your last line, better.', idx));
    S.transcript[idx].text=text; rerenderFeed();
  }catch(e){ log('RE-ROLL ERROR: '+e.message); }
  unthink();
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
    dl('transcript.json', JSON.stringify({show:'THE GHOST PROTOCOL',format:S.format,
      topic:$('topic').value.trim(), date:new Date().toISOString(),
      transcript:S.transcript.map(t=>({speaker:t.name,human:!!t.human,voice:t.voice,text:t.text}))},null,2),
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
  let sh=`#!/usr/bin/env bash
# ==========================================================================
# THE GHOST PROTOCOL — episode compiler (100% open source: piper + ffmpeg)
# Generated ${new Date().toISOString()} | format: ${S.format}
#
# Requirements (Arch):
#   sudo pacman -S ffmpeg
#   yay -S piper-tts-bin          # or: pip install piper-tts
#   Download the voice models used below (*.onnx + *.onnx.json) from
#   https://huggingface.co/rhasspy/piper-voices and put them in ./voices/
#
# Run:   bash compile_show.sh     ->  episode.mp4
# ==========================================================================
set -euo pipefail
command -v piper  >/dev/null || { echo "piper not found";  exit 1; }
command -v ffmpeg >/dev/null || { echo "ffmpeg not found"; exit 1; }
W=1920; H=1080; BG=0x0a0e14
VOICEDIR="\${VOICEDIR:-voices}"
mkdir -p build; rm -f build/concat.txt

seg () { # seg <idx> <NAME> <colorhex> <voice> ; reads text from build/<idx>.txt
  local i=$1 name=$2 color=$3 voice=$4 tf="build/$1.txt"
  echo ">> [$i] $name"
  piper --model "$VOICEDIR/$voice.onnx" --output_file "build/$i.wav" < "$tf"
  local dur; dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "build/$i.wav")
  ffmpeg -y -v error -f lavfi -i "color=c=$BG:s=\${W}x\${H}:d=$dur" -i "build/$i.wav" \\
    -vf "drawtext=text='[ $name ]':x=120:y=140:fontsize=46:fontcolor=$color:font=Monospace,drawtext=textfile='$tf':x=120:y=260:fontsize=34:fontcolor=0xf8f8f2:font=Monospace:line_spacing=16" \\
    -c:v libx264 -preset fast -pix_fmt yuv420p -c:a aac -shortest "build/$i.mp4"
  echo "file '$i.mp4'" >> build/concat.txt
}

`;
  S.transcript.forEach((t,ix)=>{
    const i=String(ix).padStart(3,'0');
    const eof='GP_EOF_'+i;
    sh += `cat > build/${i}.txt <<'${eof}'\n${fold(t.text,74)}\n${eof}\n`;
    sh += `seg ${i} '${shq(sanName(t.name))}' ${t.hex||'0xf8f8f2'} '${shq(t.voice||'en_US-lessac-medium')}'\n\n`;
  });
  sh += `ffmpeg -y -v error -f concat -safe 0 -i build/concat.txt -c copy episode.mp4
echo "=========================================="
echo " DONE -> episode.mp4  ($(du -h episode.mp4 | cut -f1))"
echo "=========================================="
`;
  dl('compile_show.sh', sh, 'text/x-shellscript');
  log('compile_show.sh exported ('+S.transcript.length+' segments)');
}

/* ============================================================== boot */
(async function(){
  try{
    const d = await (await fetch('/api/defaults')).json();
    $('endpoint').value=d.endpoint; $('apikey').value=d.api_key; $('model').value=d.model;
  }catch(e){ $('endpoint').value='http://localhost:8080/v1/chat/completions'; }
  try{
    TOPICS = await (await fetch('/api/topics')).json();
    log(`topic bank loaded: ${TOPICS.length} theses (${TOPICS.filter(t=>t.cat==='serious').length} serious / ${TOPICS.filter(t=>t.cat==='absurd').length} absurd)`);
  }catch(e){ log('topic bank unavailable: '+e.message); }
  loadCast();
  log('GHOST PROTOCOL studio online.');
  log('Tip: enable SIMULATION MODE to test the flow with zero API calls.');
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"""
  ╔════════════════════════════════════════════════╗
  ║        THE GHOST PROTOCOL // studio            ║
  ║   open  ->  http://localhost:{PORT}             ║
  ║   bind: {BIND}  (GP_BIND=0.0.0.0 for LAN)
  ║   endpoint: {DEFAULT_ENDPOINT}
  ║   (change in UI, or GP_ENDPOINT / GP_API_KEY)  ║
  ╚════════════════════════════════════════════════╝
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nkernel halted.")
