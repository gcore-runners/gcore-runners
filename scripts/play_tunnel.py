#!/usr/bin/env python3
"""Туннель Play через bore.pub: закреплённая версия, sha256, адрес в tunnel.json.

    python3 scripts/play_tunnel.py start --port 5900 --out "$RUNNER_TEMP/tunnel.json"

Скачивает bore нужной платформы (Linux/macOS/Windows), проверяет sha256, запускает
`bore local <port> --to bore.pub` и ждёт строку «listening at bore.pub:PORT».
Адрес пишется только в --out и в --github-output (если задан), не в stdout.
Только stdlib, Python 3.10+.
"""
import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile

VERSION = "0.6.0"
BASE = "https://github.com/ekzhang/bore/releases/download/v%s/" % VERSION
ASSETS = {
    ("Linux", "x86_64"): ("bore-v0.6.0-x86_64-unknown-linux-musl.tar.gz",
                          "e484d1e3acba77169b773f31a5bfb34192d4b660f44a094a658a2522cd2270f7", "tar"),
    ("Linux", "aarch64"): ("bore-v0.6.0-aarch64-unknown-linux-musl.tar.gz",
                           "ffc4515f3617420b243758cf36ed6a63208d7dba76b2ec3e90d1f476a9742951", "tar"),
    ("Darwin", "x86_64"): ("bore-v0.6.0-x86_64-apple-darwin.tar.gz",
                           "206db723a382bbc18d2893fc8472868e0b5f41de35975269aab7891ecc8659cc", "tar"),
    ("Darwin", "arm64"): ("bore-v0.6.0-aarch64-apple-darwin.tar.gz",
                          "65f43a67b90874700538bdb6064c5e92276e64dfba24f5cd72ef24a035eec3bc", "tar"),
    ("Windows", "AMD64"): ("bore-v0.6.0-x86_64-pc-windows-msvc.zip",
                           "01709c64fe2787cdc9a21d7030b0f08ad72dff0c36b7ecb72f4f667a55a34b4f", "zip"),
    # Windows 11 ARM: x64-сборка под эмуляцией
    ("Windows", "ARM64"): ("bore-v0.6.0-x86_64-pc-windows-msvc.zip",
                           "01709c64fe2787cdc9a21d7030b0f08ad72dff0c36b7ecb72f4f667a55a34b4f", "zip"),
}
ANSI = re.compile(r"\x1b\[[0-9;]*m")
IS_WIN = sys.platform.startswith("win")


def target():
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Windows":
        return "Windows", ("ARM64" if machine in ("arm64", "aarch64") else "AMD64")
    if system == "Darwin":
        return "Darwin", ("arm64" if machine in ("arm64", "aarch64") else "x86_64")
    return "Linux", ("aarch64" if machine in ("aarch64", "arm64") else "x86_64")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(name, digest, kind):
    cache = os.path.join(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir(), "play-bore")
    os.makedirs(cache, exist_ok=True)
    archive = os.path.join(cache, name)
    if not os.path.isfile(archive) or sha256(archive) != digest:
        tmp = archive + ".part"
        with urllib.request.urlopen(BASE + name, timeout=120) as r, open(tmp, "wb") as fh:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
        got = sha256(tmp)
        if got != digest:
            os.unlink(tmp)
            fail("sha256 не совпал для %s: %s" % (name, got))
        os.replace(tmp, archive)

    exe = os.path.join(cache, "bore.exe" if kind == "zip" else "bore")
    if not os.path.isfile(exe):
        if kind == "zip":
            with zipfile.ZipFile(archive) as z:
                for member in z.namelist():
                    if member.endswith("bore.exe"):
                        with z.open(member) as src, open(exe, "wb") as dst:
                            dst.write(src.read())
                        break
        else:
            with tarfile.open(archive, "r:gz") as t:
                for member in t.getmembers():
                    if member.isfile() and member.name.rstrip("/").endswith("bore") and "/" not in member.name:
                        with t.extractfile(member) as src, open(exe, "wb") as dst:
                            dst.write(src.read())
                        break
    if not os.path.isfile(exe):
        fail("в архиве %s нет bore" % name)
    if not IS_WIN:
        os.chmod(exe, 0o755)
    return exe


def fail(msg):
    sys.stderr.write("play_tunnel: %s\n" % msg)
    sys.exit(1)


def start(args):
    system, machine = target()
    if (system, machine) not in ASSETS:
        fail("нет сборки bore для %s/%s" % (system, machine))
    name, digest, kind = ASSETS[(system, machine)]
    exe = download(name, digest, kind)

    cache = os.path.dirname(exe)
    log = os.path.join(cache, "bore-%d.log" % args.port)
    with open(log, "wb") as out:
        kw = {}
        if IS_WIN:
            kw["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0)
        else:
            kw["start_new_session"] = True
        proc = subprocess.Popen([exe, "local", str(args.port), "--to", "bore.pub"],
                                stdout=out, stderr=subprocess.STDOUT, **kw)

    deadline = time.time() + 45
    addr = None
    while time.time() < deadline:
        try:
            with open(log, "rb") as fh:
                text = ANSI.sub("", fh.read().decode("utf-8", "replace"))
        except OSError:
            text = ""
        m = re.search(r"listening at bore\.pub:(\d+)", text)
        if m:
            addr = int(m.group(1))
            break
        if proc.poll() is not None:
            break
        time.sleep(0.5)

    if not addr:
        try:
            with open(log, "rb") as fh:
                tail = ANSI.sub("", fh.read().decode("utf-8", "replace")).strip().splitlines()[-8:]
        except OSError:
            tail = []
        fail("bore не выдал адрес; журнал:\n%s" % "\n".join(tail))

    data = {"host": "bore.pub", "port": addr, "pid": proc.pid}
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh)
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as fh:
            fh.write("host=bore.pub\nport=%d\n" % addr)
    print("play_tunnel: tunnel ready (порт %d)" % addr)


def main():
    ap = argparse.ArgumentParser(description="bore-туннель для Play")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--port", type=int, required=True)
    s.add_argument("--out", default="")
    s.add_argument("--github-output", default="")
    s.set_defaults(fn=start)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
