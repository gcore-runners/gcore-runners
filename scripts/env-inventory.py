#!/usr/bin/env python3
"""Опись раннера: ОС, железо и версии инструментов (Linux, Windows; macOS — как запасной вариант).

Печатает JSON в stdout. Всё, что не удалось узнать, — пустая строка: опись остаётся валидной и сравнимой.
"""
import json, os, platform, re, shutil, subprocess, sys, time

started = time.time()

def run(argv, timeout=60):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except Exception as ex:
        return "ERR %s" % ex

# Ответы-заглушки версией не считаем
BAD = ("error", "unable", "not found", "no such file", "cannot find", "couldn\u2019t", "couldn't")

ANSI = re.compile(r"\x1b\[[0-9;]*m")

def clean(v):
    if not v:
        return ""
    v = " ".join(ANSI.sub("", v).split())
    return "" if any(b in v.lower() for b in BAD) else v

def ver_line(out):
    for line in out.splitlines():
        line = line.strip()
        if not line or line.endswith(":") or line.startswith(("/", "-", "[")):
            continue
        if any(ch.isdigit() for ch in line):
            return clean(line)
    return ""

def tool(cands, args):
    for c in cands:
        p = shutil.which(c)
        if p:
            v = ver_line(run([p] + args, 30))
            if v:
                return v
    return ""

TOOLS = [
    ("python3", (["python3", "python"], ["--version"])),
    ("pip3", (["pip3", "pip"], ["--version"])),
    ("node", (["node"], ["--version"])),
    ("npm", (["npm"], ["--version"])),
    ("yarn", (["yarn"], ["--version"])),
    ("pnpm", (["pnpm"], ["--version"])),
    ("bun", (["bun"], ["--version"])),
    ("ruby", (["ruby"], ["--version"])),
    ("gem", (["gem"], ["--version"])),
    ("bundler", (["bundle"], ["--version"])),
    ("cocoapods", (["pod"], ["--version"])),
    ("fastlane", (["fastlane"], ["--version"])),
    ("go", (["go"], ["version"])),
    ("java", (["java"], ["-version"])),
    ("javac", (["javac"], ["-version"])),
    ("dotnet", (["dotnet"], ["--version"])),
    ("rustc", (["rustc"], ["--version"])),
    ("cargo", (["cargo"], ["--version"])),
    ("gcc", (["gcc"], ["--version"])),
    ("clang", (["clang"], ["--version"])),
    ("cmake", (["cmake"], ["--version"])),
    ("ninja", (["ninja"], ["--version"])),
    ("make", (["make"], ["--version"])),
    ("git", (["git"], ["--version"])),
    ("docker", (["docker"], ["--version"])),
    ("pwsh", (["pwsh"], ["--version"])),
    ("az", (["az"], ["--version"])),
    ("kubectl", (["kubectl"], ["version", "--client"])),
]

def os_info():
    if sys.platform.startswith("linux"):
        name = ver = ""
        try:
            for line in open("/etc/os-release"):
                k, _, v = line.strip().partition("=")
                v = v.strip('"')
                if k == "PRETTY_NAME":
                    name = v
                elif k == "VERSION_ID":
                    ver = v
        except Exception:
            pass
        return name or platform.platform(), ver, platform.release()
    if sys.platform == "win32":
        rel, ver, csd, _ = platform.win32_ver()
        name = ("Windows Server " + rel[:-6]) if rel.endswith("Server") else ("Windows " + rel)
        return name, ver, (ver + (" " + csd if csd and csd != "SP0" else ""))
    if sys.platform == "darwin":
        return ("macOS " + run(["sw_vers", "-productVersion"], 10).strip(),
                run(["sw_vers", "-buildVersion"], 10).strip(), platform.release())
    return platform.platform(), platform.release(), platform.version()

def cpu_model():
    if sys.platform.startswith("linux"):
        try:
            for line in open("/proc/cpuinfo"):
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
        except Exception:
            pass
    if sys.platform == "win32":
        for line in run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"], 60).splitlines():
            if line.strip():
                return line.strip()
    if sys.platform == "darwin":
        return run(["sysctl", "-n", "machdep.cpu.brand_string"], 10).strip() or run(["sysctl", "-n", "hw.model"], 10).strip()
    return platform.processor() or platform.machine()

def ram_gb():
    if sys.platform.startswith("linux"):
        try:
            for line in open("/proc/meminfo"):
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) * 1024 / 2**30, 1)
        except Exception:
            pass
    if sys.platform == "win32":
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        m = MS()
        m.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return round(m.ullTotalPhys / 2**30, 1)
    out = run(["sysctl", "-n", "hw.memsize"], 10).strip()
    return round(int(out) / 2**30, 1) if out.isdigit() else 0

def disk_gb():
    p = "C:\\" if sys.platform == "win32" else "/"
    try:
        u = shutil.disk_usage(p)
        return round(u.total / 2**30), round(u.free / 2**30)
    except Exception:
        return 0, 0

name, ver, build = os_info()
total, free = disk_gb()
out = {
    "label": os.environ.get("INV_LABEL", ""),
    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "image_os": os.environ.get("ImageOS", ""),
    "image_version": os.environ.get("ImageVersion", ""),
    "os_name": name,
    "os_version": ver,
    "os_build": build,
    "arch": platform.machine(),
    "cpu": cpu_model(),
    "ncpu": os.cpu_count() or 0,
    "ram_gb": ram_gb(),
    "disk_total_gb": total,
    "disk_free_gb": free,
    "tools": {k: tool(c, a) for k, (c, a) in TOOLS},
    "collect_seconds": round(time.time() - started, 1),
}
json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
