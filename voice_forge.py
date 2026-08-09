#!/usr/bin/env python3
# =============================================================================
#  THE GHOST PROTOCOL — voice forge
#  Designs, auditions and drives the cast's OmniVoice voiceprints.
#  Python 3 stdlib only. The OmniVoice client lives in ghost_protocol_studio.py.
#
#    python3 voice_forge.py design              # design every missing voiceprint
#    python3 voice_forge.py design --sid cynic  # re-roll one until you like it
#    python3 voice_forge.py design --all --force
#    python3 voice_forge.py audition            # one wav, whole cast, slated
#    python3 voice_forge.py verify              # are they actually distinct?
#    python3 voice_forge.py speak --sid alpha --text "..." --out line.wav
#
#  Voiceprints land in assets/voices/<sid>.wav and are committed — they are the
#  cast's voices, not a build artifact. Re-rolling is cheap (~2s a voice);
#  the wav on disk is the source of truth once you've approved how it sounds.
# =============================================================================
import argparse
import array
import io
import json
import math
import os
import statistics
import sys
import wave

from ghost_protocol_studio import (
    CHARACTERS, CHARACTERS_FILE, GUEST_VOICES, OMNIVOICE_URL, VOICEPRINTS_DIR,
    ov_design, ov_speak, ov_voiceprint_path,
)

MANIFEST = os.path.join(VOICEPRINTS_DIR, "voiceprints.json")
# Everyone who needs a voiceprint: the 13 cast members plus the co-hosts and the star witness.
SUBJECTS = CHARACTERS + GUEST_VOICES


def by_sid(sid):
    for c in SUBJECTS:
        if c.get("sid") == sid:
            return c
    return None


def spec_of(c):
    s = dict(c.get("omnivoice") or {})
    if not s:
        raise SystemExit(f"{c['sid']}: no `omnivoice` block in {os.path.basename(CHARACTERS_FILE)}")
    return s


# ── wav helpers (stdlib only — every voiceprint is 24 kHz mono s16) ──────────
def read_wav(path):
    if isinstance(path, bytes):
        path = io.BytesIO(path)
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"{path}: expected 16-bit audio")
        rate, chans, n = w.getframerate(), w.getnchannels(), w.getnframes()
        samples = array.array("h", w.readframes(n))
    if chans > 1:  # mix to mono
        samples = array.array("h", [int(sum(samples[i:i + chans]) / chans)
                                    for i in range(0, len(samples) - chans + 1, chans)])
    return samples, rate


def write_wav(path, samples, rate):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())


def rms_dbfs(samples):
    if not samples:
        return -99.0
    acc = sum(s * s for s in samples) / len(samples)
    return 20 * math.log10(max(math.sqrt(acc), 1e-9) / 32768.0)


def median_f0(samples, rate):
    """Median voiced pitch, via autocorrelation on a 4x-decimated signal. Rough but comparable."""
    dec = 4
    sig = [float(samples[i]) for i in range(0, len(samples), dec)]
    sr = rate / dec
    frame, hop = 256, 128
    lo, hi = int(sr / 400), int(sr / 60)  # 60–400 Hz search window
    peak = max((abs(v) for v in sig), default=1.0) or 1.0
    found = []
    for start in range(0, max(0, len(sig) - frame), hop):
        f = sig[start:start + frame]
        energy = sum(v * v for v in f)
        if math.sqrt(energy / frame) < 0.04 * peak:
            continue  # silence / unvoiced
        best_lag, best_score = 0, 0.0
        for lag in range(lo, min(hi, frame - 1)):
            num = sum(f[i] * f[i + lag] for i in range(frame - lag))
            score = num / (frame - lag)
            if score > best_score:
                best_lag, best_score = lag, score
        if best_lag and best_score > 0.30 * (energy / frame):
            found.append(sr / best_lag)
    return statistics.median(found) if len(found) >= 5 else 0.0


def wav_seconds(path):
    with wave.open(path, "rb") as w:
        return w.getnframes() / float(w.getframerate())


def silence(rate, seconds):
    return array.array("h", [0] * int(rate * seconds))


# ── commands ────────────────────────────────────────────────────────────────
MIN_SEPARATION_HZ = 12   # two voices closer than this in the same format blur together on playback
DESIGN_TARGET_HZ = 20    # stop drawing takes once a voice is comfortably clear of its format-mates


def format_mates(sid):
    """Other cast members this one actually shares screen time with."""
    me = by_sid(sid) or {}
    mine = set(me.get("formats") or [])
    return [c["sid"] for c in SUBJECTS
            if c["sid"] != sid and mine & set(c.get("formats") or [])]


def pitch_of_voiceprint(sid, cache={}):  # noqa: B006 — deliberate memo across candidates
    path = ov_voiceprint_path(sid)
    if not os.path.isfile(path):
        return None
    key = (path, os.path.getmtime(path))
    if key not in cache:
        cache[key] = median_f0(*read_wav(path))
    return cache[key]


def separation(f0, sid):
    """Distance in Hz to the nearest already-designed voice sharing a format. inf when nobody clashes."""
    others = [pitch_of_voiceprint(m) for m in format_mates(sid)]
    gaps = [abs(f0 - o) for o in others if o]
    return min(gaps) if gaps else float("inf")


def cmd_design(args):
    targets = [by_sid(args.sid)] if args.sid else SUBJECTS
    if args.sid and not targets[0]:
        raise SystemExit(f"unknown sid '{args.sid}' — known: {', '.join(c['sid'] for c in SUBJECTS)}")
    os.makedirs(VOICEPRINTS_DIR, exist_ok=True)

    manifest = {}
    if os.path.isfile(MANIFEST):
        with open(MANIFEST, encoding="utf-8") as f:
            manifest = json.load(f).get("voiceprints", {})

    forced = args.force or bool(args.sid)
    made, kept, failed = [], [], []
    for c in targets:
        sid = c["sid"]
        path = ov_voiceprint_path(sid)
        if os.path.isfile(path) and not forced:
            kept.append(sid)
            continue
        spec = spec_of(c)
        line = args.text or spec.get("signature") or f"This is {c['name']}, reporting for the Ghost Protocol."
        print(f"  designing {sid:7} {spec['gender']}/{spec['age']}/{spec['pitch']} pitch/"
              f"{spec['accent']} accent @ {spec['speed']}x … ", end="", flush=True)
        # The design model is stochastic — the attributes steer it, they don't pin it down.
        # So draw a few takes and keep whichever sits furthest from the voices this
        # character shares a format with. That is the separation an ear actually notices.
        best = None
        for take in range(max(1, args.best_of)):
            try:
                wav = ov_design(line, spec)
            except Exception as e:  # noqa: BLE001 — one bad take must not kill the batch
                print(f"take {take + 1} failed: {e}; ", end="", flush=True)
                continue
            f0 = median_f0(*read_wav(wav))
            gap = separation(f0, sid)
            if best is None or gap > best[2]:
                best = (wav, f0, gap)
            if gap >= DESIGN_TARGET_HZ:
                break
        if best is None:
            print("FAILED: every take errored")
            failed.append(sid)
            continue
        wav, f0, gap = best
        with open(path, "wb") as f:
            f.write(wav)
        secs = wav_seconds(path)
        gap_note = "clear" if gap == float("inf") else f"+{gap:.0f}Hz clear"
        print(f"ok ({secs:.1f}s, {f0:.0f}Hz, {gap_note})")
        made.append(sid)
        manifest[sid] = {"name": c.get("name", sid), "engine": "omnivoice",
                         "file": f"assets/voices/{sid}.wav", "seconds": round(secs, 2),
                         "measured_hz": round(f0), "piper_fallback": c.get("piperVoice") or c.get("voice"),
                         **spec}

    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump({"_comment": "Generated by voice_forge.py — designed OmniVoice voiceprints for the cast. "
                               "The renderer clones these; assets/voices/<sid>.wav is the source of truth.",
                   "source": OMNIVOICE_URL, "voiceprints": manifest}, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"\n  designed {len(made)}  kept {len(kept)}  failed {len(failed)}")
    if kept:
        print(f"  (kept existing: {', '.join(kept)} — use --force to re-roll)")
    if failed:
        print(f"  FAILED: {', '.join(failed)}")
        return 1
    return 0


def cmd_speak(args):
    c = by_sid(args.sid)
    spec = spec_of(c) if c else {}
    wav = ov_speak(args.sid, args.text,
                   speed=args.speed if args.speed is not None else spec.get("speed", 1.0),
                   instruct=args.instruct)
    out = args.out or f"{args.sid}.wav"
    with open(out, "wb") as f:
        f.write(wav)
    print(f"{out}  ({wav_seconds(out):.1f}s)")
    return 0


def cmd_audition(args):
    """One wav, whole cast, each voice slated with its own signature line. Play it, then re-roll what grates."""
    sids = [c["sid"] for c in SUBJECTS if os.path.isfile(ov_voiceprint_path(c["sid"]))]
    if not sids:
        raise SystemExit("no voiceprints yet — run: python3 voice_forge.py design")
    reel, rate = array.array("h"), None
    for sid in sids:
        samples, r = read_wav(ov_voiceprint_path(sid))
        if rate is None:
            rate = r
        elif r != rate:
            raise SystemExit(f"{sid}.wav is {r} Hz, expected {rate} Hz")
        reel.extend(samples)
        reel.extend(silence(rate, 0.6))
    out = args.out or os.path.join(VOICEPRINTS_DIR, "_audition.wav")
    write_wav(out, reel, rate)
    print(f"{out}  ({len(reel)/rate:.1f}s, {len(sids)} voices in order: {', '.join(sids)})")
    return 0


def cmd_verify(args):
    """Measured proof the cast doesn't sound like one another. Pitch + level + pace per voice."""
    rows, missing = [], []
    for c in SUBJECTS:
        sid = c["sid"]
        path = ov_voiceprint_path(sid)
        if not os.path.isfile(path):
            missing.append(sid)
            continue
        samples, rate = read_wav(path)
        secs = len(samples) / rate
        chars = len((c.get("omnivoice") or {}).get("signature") or "")
        rows.append({"sid": sid, "f0": median_f0(samples, rate), "db": rms_dbfs(samples),
                     "secs": secs, "cps": (chars / secs if secs else 0),
                     "spec": c.get("omnivoice") or {}})

    print(f"\n  {'sid':8} {'pitch':>7}  {'level':>7}  {'len':>6}  {'pace':>7}   design")
    print("  " + "-" * 78)
    for r in sorted(rows, key=lambda r: r["f0"]):
        s = r["spec"]
        print(f"  {r['sid']:8} {r['f0']:6.0f}Hz  {r['db']:6.1f}dB  {r['secs']:5.1f}s  "
              f"{r['cps']:5.1f}c/s   {s.get('gender','?')[:1]}·{s.get('age','?')}·"
              f"{s.get('pitch','?')}·{s.get('accent','?')}")

    # Two voices this close together, in a format where they trade lines, blur on playback.
    fmt_of = {c["sid"]: set(c.get("formats") or []) for c in SUBJECTS}
    clashes = []
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            shared = fmt_of.get(a["sid"], set()) & fmt_of.get(b["sid"], set())
            if shared and a["f0"] and b["f0"] and abs(a["f0"] - b["f0"]) < MIN_SEPARATION_HZ:
                clashes.append((a["sid"], b["sid"], abs(a["f0"] - b["f0"]), sorted(shared)))
    print()
    if missing:
        print(f"  missing voiceprints: {', '.join(missing)}")
    if clashes:
        for a, b, d, fmts in clashes:
            print(f"  ⚠ {a} and {b} are {d:.0f} Hz apart and share {', '.join(fmts)} — re-roll one")
    else:
        print(f"  ✓ no two voices sharing a format are within {MIN_SEPARATION_HZ} Hz of each other")
    return 1 if clashes or missing else 0


def main():
    p = argparse.ArgumentParser(description="Design and drive the Ghost Protocol cast's OmniVoice voices.")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("design", help="design voiceprints from the characters.json specs")
    d.add_argument("--sid", help="one cast member (always re-rolls)")
    d.add_argument("--all", action="store_true", help="every cast member (default when --sid is absent)")
    d.add_argument("--force", action="store_true", help="overwrite voiceprints that already exist")
    d.add_argument("--text", help="override the signature line used for the design pass")
    d.add_argument("--best-of", type=int, default=3, metavar="N",
                   help="draw N takes and keep the one furthest from its format-mates (default 3)")
    d.set_defaults(fn=cmd_design)

    s = sub.add_parser("speak", help="say a line in a cast member's designed voice")
    s.add_argument("--sid", required=True)
    s.add_argument("--text", required=True)
    s.add_argument("--out")
    s.add_argument("--speed", type=float)
    s.add_argument("--instruct", help="style tags only, e.g. 'male, british accent, weary'")
    s.set_defaults(fn=cmd_speak)

    a = sub.add_parser("audition", help="concatenate the whole cast into one wav")
    a.add_argument("--out")
    a.set_defaults(fn=cmd_audition)

    v = sub.add_parser("verify", help="pitch/level/pace table + same-format collision check")
    v.set_defaults(fn=cmd_verify)

    args = p.parse_args()
    print(f"  OmniVoice: {OMNIVOICE_URL}")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
