#!/usr/bin/env python3
"""hire.py — cast Guild members into this show. Python 3 stdlib only.

  python3 hire.py cynic                       hire by sid from the Guild on GitHub
  python3 hire.py stoic nihil util            bulk hire
  python3 hire.py --list                      browse the registry
  python3 hire.py --guild /path/to/clone p7   hire from a local Guild checkout
  python3 hire.py --crew splice inkwell       hire crew (into crew/)

Copies the member package into cast/ (or crew/), instantiates MEMORY.md from
the template, and records name+version in cast.lock.json.
"""
import json
import os
import shutil
import sys
import urllib.request

GUILD_RAW = "https://raw.githubusercontent.com/DryadAI/agentic-actors-guild/main"
HERE = os.path.dirname(os.path.abspath(__file__))


def fetch(path, guild_local):
    if guild_local:
        with open(os.path.join(guild_local, path), encoding="utf-8") as f:
            return f.read()
    with urllib.request.urlopen(f"{GUILD_RAW}/{path}", timeout=30) as r:
        return r.read().decode("utf-8")


def main():
    args = sys.argv[1:]
    guild_local = None
    kind = "actors"
    dest_root = "cast"
    if "--guild" in args:
        i = args.index("--guild")
        guild_local = args[i + 1]
        del args[i:i + 2]
    if "--crew" in args:
        args.remove("--crew")
        kind, dest_root = "crew", "crew"

    registry = json.loads(fetch("guild.json", guild_local))

    if not args or "--list" in args:
        for section in ("actors", "crew"):
            print(f"\n== {section} ==")
            for m in registry[section]:
                extra = m.get("archetype") or m.get("role", "")
                print(f"  {m['sid']:<12} {m['name']:<18} v{m['version']}  {extra}")
        return

    lock_path = os.path.join(HERE, "cast.lock.json")
    lock = {}
    if os.path.exists(lock_path):
        lock = json.load(open(lock_path, encoding="utf-8"))

    members = {m["sid"]: m for m in registry[kind]}
    for sid in args:
        if sid not in members:
            sys.exit(f"no such {kind[:-1]} in the Guild: {sid} (try --list)")
        m = members[sid]
        dest = os.path.join(HERE, dest_root, sid)
        os.makedirs(dest, exist_ok=True)
        files = ["SOUL.md", "card.json"]
        if kind == "actors":
            files.append("MEMORY.template.md")
        for fn in files:
            content = fetch(f"{m['path']}/{fn}", guild_local)
            with open(os.path.join(dest, fn), "w", encoding="utf-8") as f:
                f.write(content)
        mem = os.path.join(dest, "MEMORY.md")
        tpl = os.path.join(dest, "MEMORY.template.md")
        if os.path.exists(tpl) and not os.path.exists(mem):
            shutil.copy(tpl, mem)
        lock[sid] = {"name": m["name"], "kind": kind[:-1], "version": m["version"],
                     "guild": guild_local or GUILD_RAW}
        print(f"hired: {m['name']} v{m['version']} -> {dest_root}/{sid}/")

    with open(lock_path, "w", encoding="utf-8") as f:
        json.dump(lock, f, indent=2, ensure_ascii=False)
    print(f"cast.lock.json updated ({len(lock)} members on contract)")


if __name__ == "__main__":
    main()
