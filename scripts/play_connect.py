#!/usr/bin/env python3
"""Служебные данные Play: проверка входа, connect.json, удержание машины.

    python3 scripts/play_connect.py validate --label L --method M --minutes N --desktop D
    python3 scripts/play_connect.py write --label L --method M --host H --port P --user U --password PW --minutes N --out F
    python3 scripts/play_connect.py hold --minutes N

validate печатает строки key=value для $GITHUB_OUTPUT. Пароль нигде не печатается.
Только stdlib, Python 3.10+.
"""
import argparse
import json
import os
import sys
import time

# Сколько держим машину: ubuntu-slim живёт 15 минут целиком, установка GUI съедает часть
LIMITS = {"ubuntu-slim": 8}
DEFAULT_LIMIT = 360

# Windows-консоль по умолчанию cp1252: русский текст не должен ронять шаг
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

NOTES = {
    "novnc": "браузер: http://{host}:{port}/vnc.html",
    "vnc": "VNC-клиент: {host}:{port} (Finder → Перейти → Подключиться к серверу…)",
    "ssh": "ssh -p {port} {user}@{host}",
    "rdp": "mstsc → {host}:{port}; пользователь {user}",
}


def family(label):
    if label.startswith("windows"):
        return "windows"
    if label.startswith(("macos", "xcode")):
        return "macos"
    if label.startswith("ubuntu"):
        return "linux"
    return ""


def fail(msg):
    sys.stderr.write("play: %s\n" % msg)
    sys.exit(1)


def validate(args):
    fam = family(args.label)
    if not fam:
        fail("неизвестная метка: %s" % args.label)
    if fam == "windows":
        fail("windows: используй windows-rdp.yml (RDP)")

    try:
        minutes = int(args.minutes)
    except ValueError:
        fail("minutes: нужно число")
    limit = LIMITS.get(args.label, DEFAULT_LIMIT)
    minutes = max(1, min(minutes, limit))

    method = "vnc" if args.method in ("", "auto") else args.method
    if method not in ("vnc", "ssh"):
        fail("method: auto|vnc|ssh")

    desktop = args.desktop.strip().lower() not in ("false", "0", "no")
    if args.label == "ubuntu-slim":
        desktop = False  # на 1 CPU xfce4 не успеть за 15 минут

    if method == "ssh":
        port, connect_method = 22, "ssh"
    elif fam == "linux":
        port, connect_method = 6080, "novnc"
    else:
        port, connect_method = 5900, "vnc"

    user = "runner"
    out = {
        "label": args.label,
        "family": fam,
        "method": method,
        "connect_method": connect_method,
        "minutes": minutes,
        "desktop": "true" if desktop else "false",
        "port": port,
        "user": user,
        "tunnel": "bore",
    }
    for k in ("label", "family", "method", "connect_method", "minutes",
              "desktop", "port", "user", "tunnel"):
        print("%s=%s" % (k, out[k]))


def write(args):
    minutes = max(1, int(args.minutes))
    expires = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + minutes * 60))
    note = NOTES.get(args.method, "").format(host=args.host, port=args.port, user=args.user)
    data = {
        "label": args.label,
        "method": args.method,
        "host": args.host,
        "port": int(args.port),
        "user": args.user,
        "password": args.password,
        "expires_at": expires,
        "note": note,
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "run_url": ("https://github.com/%s/actions/runs/%s"
                    % (os.environ.get("GITHUB_REPOSITORY", ""),
                       os.environ.get("GITHUB_RUN_ID", ""))) if os.environ.get("GITHUB_RUN_ID") else "",
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    print("connect.json: %s (%s)" % (data["method"], data["expires_at"]))


def hold(args):
    minutes = max(1, int(args.minutes))
    until = time.time() + minutes * 60
    sys.stderr.write("hold: %d минут\n" % minutes)
    while time.time() < until:
        time.sleep(min(60, max(1, int(until - time.time()))))


def main():
    ap = argparse.ArgumentParser(description="Play: connect.json и удержание машины")
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate")
    v.add_argument("--label", required=True)
    v.add_argument("--method", default="auto")
    v.add_argument("--minutes", default="60")
    v.add_argument("--desktop", default="true")
    v.set_defaults(fn=validate)

    w = sub.add_parser("write")
    w.add_argument("--label", required=True)
    w.add_argument("--method", required=True)
    w.add_argument("--host", required=True)
    w.add_argument("--port", required=True)
    w.add_argument("--user", default="runner")
    w.add_argument("--password", default=os.environ.get("PLAY_PASSWORD", ""))
    w.add_argument("--minutes", default="60")
    w.add_argument("--out", default="out/connect.json")
    w.set_defaults(fn=write)

    h = sub.add_parser("hold")
    h.add_argument("--minutes", default="60")
    h.set_defaults(fn=hold)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
