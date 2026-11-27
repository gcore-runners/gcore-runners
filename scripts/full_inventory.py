#!/usr/bin/env python3
"""Полная инвентаризация GitHub-раннера: ОС, железо, инструменты, приложения и подключение.

    python3 scripts/full_inventory.py --out out [--no-apps] [--label LABEL]

Пишет в --out: inventory.json, apps.tsv, tools.tsv, os.txt, errors.txt, summary.md.
В stdout — одна строка прогресса. Только stdlib, Python 3.10+.
Опись собирает только положительные факты: чего на раннере нет, в файлы не попадает.
Неудачи не ломают опись — они идут в errors.txt и в inventory.json["errors"].
"""
import argparse
import glob
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

STARTED = time.time()
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
HERE = os.path.dirname(os.path.abspath(__file__))
NO_WINDOW = 0x08000000 if IS_WIN else 0
ERRORS = []

# Типовые каталоги, которые образ может не добавить в PATH
if IS_MAC:
    os.environ["PATH"] = os.environ.get("PATH", "") + ":/opt/homebrew/bin:/usr/local/bin"
elif IS_LINUX:
    os.environ["PATH"] = os.environ.get("PATH", "") + ":/usr/local/go/bin"

BAD = ("error", "unable", "not found", "no such file", "cannot find",
       "couldn\u2019t", "couldn't", "command not found", "is not recognized",
       "не найдено", "не найден")
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def err(msg):
    ERRORS.append(str(msg))


def run(argv, timeout=60, env=None, cwd=None):
    """stdout+stderr команды; при сбое/таймауте — строка 'ERR ...'."""
    try:
        e = dict(os.environ)
        if env:
            e.update(env)
        r = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                           timeout=timeout, env=e, cwd=cwd, creationflags=NO_WINDOW)
        return (r.stdout + r.stderr).strip()
    except Exception as ex:
        return "ERR %s" % ex


def run_bytes(argv, timeout=60):
    """Как run(), но сам разбирает кодировку: wsl/systeminfo отдают UTF-16 или OEM."""
    try:
        r = subprocess.run(argv, capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
        b = r.stdout + r.stderr
        if b[:80].count(b"\x00") >= 10:
            return b.decode("utf-16-le", "replace").strip()
        return b.decode("utf-8", "replace").strip()
    except Exception as ex:
        return "ERR %s" % ex


def run_prog(path, args, timeout=30, env=None):
    """Запуск найденного бинаря; на Windows .cmd/.bat идут через cmd.exe."""
    if IS_WIN and path.lower().endswith((".cmd", ".bat")):
        return run(["cmd", "/c", path] + list(args), timeout, env)
    return run([path] + list(args), timeout, env)


def clean(v):
    if not v:
        return ""
    v = " ".join(ANSI.sub("", v).split())
    if any(b in v.lower() for b in BAD):
        return ""
    return v


def ver_line(out):
    """Строка с версией: первая непустая с цифрой, без заголовков и путей."""
    if not out or out.startswith("ERR "):
        return ""
    for line in out.splitlines():
        line = line.strip()
        if not line or line.endswith(":") or line.startswith(("/", "-", "[", "{", '"', "'")):
            continue
        if any(ch.isdigit() for ch in line):
            return clean(line)
    return ""


def first_line(out):
    for line in (out or "").splitlines():
        line = line.strip()
        if line and not line.startswith("ERR "):
            return line
    return ""


def to_int(v):
    try:
        return int(str(v).strip())
    except Exception:
        return 0


def method(status, **kw):
    """Запись connect.<метод>: статус + только заполненные поля."""
    d = {"status": status}
    for k, v in kw.items():
        if v not in (None, "", [], {}):
            d[k] = v
    return d


def pick(*vals):
    for v in vals:
        if v not in (None, "", 0, [], {}):
            return v
    return vals[-1] if vals else ""


# ---------------------------------------------------------------- инструменты

TOOL_SPECS = [
    ("python3", ("python3", "python"), ("--version",)),
    ("pip3", ("pip3", "pip"), ("--version",)),
    ("node", ("node",), ("--version",)),
    ("npm", ("npm",), ("--version",)),
    ("yarn", ("yarn",), ("--version",)),
    ("pnpm", ("pnpm",), ("--version",)),
    ("bun", ("bun",), ("--version",)),
    ("deno", ("deno",), ("--version",)),
    ("uv", ("uv",), ("--version",)),
    ("poetry", ("poetry",), ("--version",)),
    ("conda", ("conda",), ("--version",)),
    ("ruby", ("ruby",), ("--version",)),
    ("gem", ("gem",), ("--version",)),
    ("bundler", ("bundle",), ("--version",)),
    ("cocoapods", ("pod",), ("--version",)),
    ("fastlane", ("fastlane",), ("--version",)),
    ("go", ("go",), ("version",)),
    ("java", ("java",), ("-version",)),
    ("javac", ("javac",), ("-version",)),
    ("mvn", ("mvn",), ("-version",)),
    ("gradle", ("gradle",), ("--version",)),
    ("bazel", ("bazel",), ("version",)),
    ("dotnet", ("dotnet",), ("--version",)),
    ("rustc", ("rustc",), ("--version",)),
    ("cargo", ("cargo",), ("--version",)),
    ("gcc", ("gcc",), ("--version",)),
    ("g++", ("g++",), ("--version",)),
    ("clang", ("clang",), ("--version",)),
    ("clang++", ("clang++",), ("--version",)),
    ("cmake", ("cmake",), ("--version",)),
    ("meson", ("meson",), ("--version",)),
    ("ninja", ("ninja",), ("--version",)),
    ("make", ("make",), ("--version",)),
    ("git", ("git",), ("--version",)),
    ("svn", ("svn",), ("--version",)),
    ("hg", ("hg",), ("--version",)),
    ("docker", ("docker",), ("--version",)),
    ("podman", ("podman",), ("--version",)),
    ("kubectl", ("kubectl",), ("version", "--client")),
    ("helm", ("helm",), ("version",)),
    ("kustomize", ("kustomize",), ("version",)),
    ("terraform", ("terraform",), ("version",)),
    ("ansible", ("ansible",), ("--version",)),
    ("packer", ("packer",), ("version",)),
    ("aws", ("aws",), ("--version",)),
    ("az", ("az",), ("--version",)),
    ("gcloud", ("gcloud",), ("--version",)),
    ("gh", ("gh",), ("--version",)),
    ("glab", ("glab",), ("--version",)),
    ("jq", ("jq",), ("--version",)),
    ("yq", ("yq",), ("--version",)),
    ("curl", ("curl",), ("--version",)),
    ("wget", ("wget",), ("--version",)),
    ("ffmpeg", ("ffmpeg",), ("-version",)),
    ("magick", ("magick", "convert"), ("--version",)),
    ("sqlite3", ("sqlite3",), ("--version",)),
    ("psql", ("psql",), ("--version",)),
    ("mysql", ("mysql",), ("--version",)),
    ("redis-cli", ("redis-cli",), ("--version",)),
    ("mongosh", ("mongosh",), ("--version",)),
    ("openssl", ("openssl",), ("version",)),
    ("ssh", ("ssh",), ("-V",)),
    ("R", ("R",), ("--version",)),
    ("julia", ("julia",), ("--version",)),
    ("php", ("php",), ("--version",)),
    ("composer", ("composer",), ("--version",)),
    ("swift", ("swift",), ("--version",)),
    ("xcodebuild", ("xcodebuild",), ("-version",)),
    ("xcrun", ("xcrun",), ("--version",)),
    ("xcodegen", ("xcodegen",), ("--version",)),
    ("tuist", ("tuist",), ("version",)),
    ("xcbeautify", ("xcbeautify",), ("--version",)),
    ("swiftlint", ("swiftlint",), ("version",)),
    ("swiftformat", ("swiftformat",), ("--version",)),
    ("carthage", ("carthage",), ("version",)),
    ("flutter", ("flutter",), ("--version",)),
    ("dart", ("dart",), ("--version",)),
    ("adb", ("adb",), ("version",)),
    ("sdkmanager", ("sdkmanager",), ("--version",)),
    ("emulator", ("emulator",), ("-version",)),
    ("ndk-build", ("ndk-build",), ("--version",)),
    ("qemu-system-x86_64", ("qemu-system-x86_64",), ("--version",)),
    ("brew", ("brew",), ("--version",)),
]
SLOW_TOOLS = {"gradle", "bazel", "mvn", "flutter", "sdkmanager", "conda", "az", "gcloud"}


def ndk_version():
    """NDK не имеет --version: читаем Pkg.Revision из source.properties."""
    for env in ("ANDROID_NDK_HOME", "ANDROID_NDK_ROOT", "ANDROID_NDK_LATEST_HOME"):
        p = os.environ.get(env)
        if not p:
            continue
        f = os.path.join(p, "source.properties")
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if line.startswith("Pkg.Revision"):
                        return line.split("=", 1)[1].strip()
        except Exception:
            continue
    return ""


def collect_tools():
    """Версии только найденных инструментов + команда, которой они получены."""
    versions, cmds = {}, {}
    for key, cands, args in TOOL_SPECS:
        path = ""
        for c in cands:
            path = shutil.which(c) or ""
            if path:
                break
        if not path:
            continue
        if key == "ndk-build":
            v = ndk_version()
            if not v:
                continue
            versions[key] = v
            cmds[key] = "cat $ANDROID_NDK_HOME/source.properties"
            continue
        out = run_prog(path, args, 60 if key in SLOW_TOOLS else 30)
        v = ver_line(out)
        if v:
            versions[key] = v
            cmds[key] = "%s %s" % (key, " ".join(args))
    return versions, cmds


# ------------------------------------------------------------------- ОС/железо

def os_release():
    d = {}
    try:
        with open("/etc/os-release", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                k, _, v = line.strip().partition("=")
                d[k] = v.strip('"')
    except Exception:
        pass
    return d


def windows_product_name(name, build):
    """Реестр Windows 11 до сих пор отдаёт ProductName «Windows 10 …» — правим по сборке."""
    b = to_int((build or "").split(".")[0])
    if b >= 22000 and name.startswith("Windows 10"):
        return "Windows 11" + name[len("Windows 10"):]
    return name


def windows_os_info():
    """ProductName/DisplayVersion/CurrentBuild/UBR из реестра — точнее, чем platform."""
    info = {"name": "", "version": "", "build": ""}
    try:
        import winreg
    except Exception:
        return info
    try:
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                           r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
        def g(name):
            try:
                return str(winreg.QueryValueEx(k, name)[0]).strip()
            except OSError:
                return ""
        name = g("ProductName") or g("EditionID")
        disp = g("DisplayVersion")
        build = g("CurrentBuild")
        ubr = g("UBR")
        info["name"] = windows_product_name(name, build)
        info["version"] = disp
        info["build"] = build + (".%s" % ubr if ubr else "")
        info["display_version"] = disp
    except OSError as ex:
        err("windows registry OS info: %s" % ex)
    return info


def os_info():
    if IS_LINUX:
        rel = os_release()
        return {
            "name": rel.get("PRETTY_NAME") or platform.platform(),
            "version": rel.get("VERSION_ID", ""),
            "build": "",
            "kernel": platform.release() or run(["uname", "-r"], 10),
        }
    if IS_MAC:
        return {
            "name": "macOS " + first_line(run(["sw_vers", "-productVersion"], 10)),
            "version": first_line(run(["sw_vers", "-productVersion"], 10)),
            "build": first_line(run(["sw_vers", "-buildVersion"], 10)),
            "kernel": platform.release() or first_line(run(["uname", "-r"], 10)),
        }
    if IS_WIN:
        w = windows_os_info()
        return {
            "name": pick(w["name"], platform.platform()),
            "version": pick(w["version"], ""),
            "build": pick(w["build"], platform.version()),
            "kernel": platform.version(),
        }
    return {"name": platform.platform(), "version": platform.release(),
            "build": "", "kernel": platform.version()}


def linux_physical_cores():
    out = run(["lscpu"], 20)
    if out and not out.startswith("ERR "):
        cores = re.search(r"^Core\(s\) per socket:\s+(\d+)", out, re.M)
        socks = re.search(r"^Socket\(s\):\s+(\d+)", out, re.M)
        if cores and socks:
            return to_int(cores.group(1)) * to_int(socks.group(1))
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.lower().startswith("cpu cores"):
                    return to_int(line.split(":")[1])
    except Exception:
        pass
    return 0


def linux_cpu_model():
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or platform.machine()


def ram_gb():
    if IS_LINUX:
        try:
            with open("/proc/meminfo", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if line.startswith("MemTotal:"):
                        return round(int(line.split()[1]) * 1024 / 2**30, 1)
        except Exception:
            pass
    if IS_WIN:
        try:
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
        except Exception:
            pass
    out = first_line(run(["sysctl", "-n", "hw.memsize"], 10))
    return round(to_int(out) / 2**30, 1) if out.isdigit() else 0


def disk_gb():
    p = "C:\\" if IS_WIN else "/"
    try:
        u = shutil.disk_usage(p)
        return round(u.total / 2**30), round(u.free / 2**30)
    except Exception:
        return 0, 0


def virtualization(probe_extra):
    if IS_LINUX:
        out = first_line(run(["systemd-detect-virt"], 10))
        return "" if out.startswith("ERR") else out
    if IS_MAC:
        return "hv_vmm_present=%s" % first_line(run(["sysctl", "-n", "kern.hv_vmm_present"], 10))
    if IS_WIN:
        return "hypervisor=%s" % probe_extra.get("hyperv", "") if "hyperv" in probe_extra else ""
    return ""


def hardware(probe_extra):
    if IS_LINUX:
        cpu = linux_cpu_model()
        phys = linux_physical_cores()
    elif IS_MAC:
        cpu = clean(first_line(run(["sysctl", "-n", "machdep.cpu.brand_string"], 10))) \
            or clean(first_line(run(["sysctl", "-n", "hw.model"], 10)))
        phys = to_int(first_line(run(["sysctl", "-n", "hw.physicalcpu"], 10)))
    elif IS_WIN:
        cpu = probe_extra.get("cpu", "")
        phys = to_int(probe_extra.get("cpu_cores", 0))
    else:
        cpu, phys = platform.processor(), 0
    total, free = disk_gb()
    return {
        "cpu": cpu or platform.machine(),
        "ncpu": os.cpu_count() or 0,
        "ncpu_physical": phys,
        "ram_gb": ram_gb(),
        "disk_total_gb": total,
        "disk_free_gb": free,
        "virt": virtualization(probe_extra),
    }


# ---------------------------------------------------------------- Linux: apps

def apps_linux():
    apps, extras, counts = [], {}, {}

    out = run(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Architecture}\n"], 180)
    n = 0
    if out.startswith("ERR "):
        err("dpkg-query: %s" % out)
    else:
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 2 or not parts[0]:
                continue
            apps.append({"name": parts[0], "version": parts[1], "source": "dpkg",
                         "path": "", "publisher": parts[2] if len(parts) > 2 else ""})
            n += 1
    counts["dpkg"] = n

    manual = run(["apt-mark", "showmanual"], 60)
    if not manual.startswith("ERR "):
        extras["apt_manual"] = sorted({x.strip() for x in manual.splitlines() if x.strip()})
        counts["apt_manual"] = len(extras["apt_manual"])

    snap = run(["snap", "list"], 60)
    n = 0
    if not snap.startswith("ERR "):
        for line in snap.splitlines():
            if not line.strip() or line.lower().startswith("name "):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            apps.append({"name": parts[0], "version": parts[1], "source": "snap",
                         "path": "", "publisher": parts[4] if len(parts) > 4 else ""})
            n += 1
    counts["snap"] = n

    flatpak = run(["flatpak", "list", "--app", "--columns=application,version"], 60)
    n = 0
    if not flatpak.startswith("ERR "):
        for line in flatpak.splitlines():
            parts = line.split("\t")
            if len(parts) < 2 or not parts[0]:
                continue
            apps.append({"name": parts[0], "version": parts[1], "source": "flatpak",
                         "path": "", "publisher": ""})
            n += 1
    counts["flatpak"] = n

    n = 0
    for d in ("/usr/share/applications", "/usr/local/share/applications",
              os.path.expanduser("~/.local/share/applications"),
              "/var/lib/snapd/desktop/applications"):
        for f in sorted(glob.glob(os.path.join(d, "*.desktop"))):
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except Exception:
                continue
            sec, name, exe, ver = "", "", "", ""
            for line in text.splitlines():
                s = line.strip()
                if s.startswith("["):
                    sec = s
                elif sec == "[Desktop Entry]" and "=" in s:
                    k, _, v = s.partition("=")
                    if k == "Name" and not name:
                        name = v.strip()
                    elif k == "Exec" and not exe:
                        exe = v.strip()
                    elif k == "Version" and not ver:
                        ver = v.strip()
            if name:
                apps.append({"name": name, "version": ver, "source": "desktop",
                             "path": exe, "publisher": os.path.basename(d)})
                n += 1
    counts["desktop"] = n
    return apps, counts, extras


# --------------------------------------------------------------- Windows: apps

def ps_json(script, timeout=180):
    """PowerShell -Command с выводом JSON; None при сбое (причина — в errors)."""
    out = run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
               "-Command", script], timeout)
    if out.startswith("ERR "):
        return None
    s = out.strip()
    idx = [i for i in (s.find("{"), s.find("[")) if i >= 0]
    if not idx:
        return None
    try:
        return json.loads(s[min(idx):])
    except Exception:
        return None


PS_PROBE = r"""
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$o = [ordered]@{}
$o.cpu = [string](Get-CimInstance Win32_Processor | Select-Object -First 1).Name
$o.cpu_cores = [int]((Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfCores -Sum).Sum)
$o.cpu_threads = [int]((Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum)
$o.hyperv = [bool](Get-CimInstance Win32_ComputerSystem).HypervisorPresent
$ts = Get-ItemProperty 'HKLM:\System\CurrentControlSet\Control\Terminal Server'
$o.rdp_deny = [int]$ts.fDenyTSConnections
$o.termservice = [string](Get-Service TermService).Status
$o.rdp_port = [bool](Get-NetTCPConnection -LocalPort 3389 -State Listen)
$o.ssh_port = [bool](Get-NetTCPConnection -LocalPort 22 -State Listen)
$o.running = @(Get-Process explorer,dwm | ForEach-Object { $_.ProcessName } | Sort-Object -Unique)
$o.session_id = [int](Get-Process -Id $PID).SessionId
$o.audio = [string](Get-Service Audiosrv).Status
$o.admin = [bool]([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
$o.uac = [int](Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System').EnableLUA
foreach ($c in 'mstsc','sshd','ssh','tailscale','cloudflared','ngrok','winget','choco','scoop','docker','wsl') {
  $o["cmd_$c"] = [bool](Get-Command $c)
}
Add-Type -AssemblyName System.Windows.Forms
$s = [System.Windows.Forms.Screen]::PrimaryScreen
$o.screen_w = [int]$s.Bounds.Width
$o.screen_h = [int]$s.Bounds.Height
$o.screen_depth = [int]$s.BitsPerPixel
$o | ConvertTo-Json -Depth 4 -Compress
"""

PS_APPX = r"""
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
@(Get-AppxPackage | Select-Object Name,Version,Publisher,InstallLocation) | ConvertTo-Json -Depth 3 -Compress
"""


def win_registry_apps():
    try:
        import winreg
    except Exception as ex:
        err("winreg: %s" % ex)
        return []
    rows = []
    sub = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    branches = [
        (winreg.HKEY_LOCAL_MACHINE, sub, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, sub, winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER, sub, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_CURRENT_USER, sub, winreg.KEY_WOW64_32KEY),
    ]
    for root, path, flag in branches:
        try:
            key = winreg.OpenKey(root, path, 0, winreg.KEY_READ | flag)
        except OSError:
            continue
        i = 0
        while True:
            try:
                name = winreg.EnumKey(key, i)
            except OSError:
                break
            i += 1
            try:
                sk = winreg.OpenKey(key, name, 0, winreg.KEY_READ | flag)

                def g(field):
                    try:
                        return str(winreg.QueryValueEx(sk, field)[0]).strip()
                    except OSError:
                        return ""

                disp = g("DisplayName")
                if not disp:
                    continue
                rows.append({"name": disp, "version": g("DisplayVersion"), "source": "registry",
                             "path": g("InstallLocation"), "publisher": g("Publisher")})
            except OSError:
                continue
    return rows


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def apps_windows():
    apps, extras, counts = [], {}, {}

    reg = win_registry_apps()
    apps.extend(reg)
    counts["registry"] = len(reg)

    appx = ps_json(PS_APPX, 180)
    n = 0
    for a in _as_list(appx):
        if not isinstance(a, dict) or not a.get("Name"):
            continue
        apps.append({"name": a["Name"], "version": str(a.get("Version") or ""),
                     "source": "appx", "path": str(a.get("InstallLocation") or ""),
                     "publisher": str(a.get("Publisher") or "")})
        n += 1
    if appx is None:
        err("Get-AppxPackage: пустой ответ")
    counts["appx"] = n

    choco = run(["choco", "list", "--local-only", "--limit-output"], 120)
    n = 0
    if choco.startswith("ERR "):
        if shutil.which("choco"):
            err("choco list: %s" % choco)
    else:
        for line in choco.splitlines():
            parts = line.strip().split("|")
            if len(parts) >= 2 and " " not in parts[0]:
                apps.append({"name": parts[0], "version": parts[1], "source": "choco",
                             "path": "", "publisher": ""})
                n += 1
    counts["choco"] = n

    scoop = run(["scoop", "list"], 120)
    n = 0
    if scoop.startswith("ERR "):
        if shutil.which("scoop"):
            err("scoop list: %s" % scoop)
    else:
        for line in scoop.splitlines():
            m = re.match(r"^([A-Za-z0-9@._+-]+)\s+([0-9][^\s]*)", line)
            if m and m.group(1).lower() not in ("name", "installed"):
                apps.append({"name": m.group(1), "version": m.group(2), "source": "scoop",
                             "path": "", "publisher": ""})
                n += 1
    counts["scoop"] = n

    n = 0
    if shutil.which("winget"):
        tmp = os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()
        p = os.path.join(tmp, "winget-export.json")
        out = run(["winget", "export", "-o", p, "--include-versions",
                   "--accept-source-agreements", "--disable-interactivity"], 180)
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                wg = json.load(fh)
            for src in _as_list(wg.get("Sources")):
                for pkg in _as_list((src or {}).get("Packages")):
                    pid = (pkg or {}).get("PackageIdentifier")
                    if not pid:
                        continue
                    apps.append({"name": pid, "version": str(pkg.get("Version") or ""),
                                 "source": "winget", "path": "", "publisher": ""})
                    n += 1
        except Exception as ex:
            err("winget export: %s" % (out.splitlines()[-1] if out else ex))
    counts["winget"] = n

    # Visual Studio / SDK / .NET / WSL — только если есть
    vswhere = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                           "Microsoft Visual Studio", "Installer", "vswhere.exe")
    if os.path.isfile(vswhere):
        vs = run([vswhere, "-all", "-prerelease", "-products", "*", "-format", "json"], 60)
        try:
            items = json.loads(vs.lstrip("\ufeff"))
            extras["visual_studio"] = [{
                "name": i.get("displayName", ""),
                "version": i.get("installationVersion", ""),
                "path": i.get("installationPath", ""),
            } for i in _as_list(items)]
        except Exception:
            err("vswhere: не удалось разобрать JSON")

    sdk_roots = r"SOFTWARE\Microsoft\Windows Kits\Installed Roots"
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sdk_roots, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        root = str(winreg.QueryValueEx(k, "KitsRoot10")[0]).strip()
        lib = os.path.join(root, "Lib")
        if os.path.isdir(lib):
            extras["windows_sdk"] = sorted(x for x in os.listdir(lib) if x[:1].isdigit())
    except Exception:
        pass

    sdks = run(["dotnet", "--list-sdks"], 60)
    if not sdks.startswith("ERR "):
        extras["dotnet_sdks"] = [x.strip() for x in sdks.splitlines() if x.strip()]
    rts = run(["dotnet", "--list-runtimes"], 60)
    if not rts.startswith("ERR "):
        extras["dotnet_runtimes"] = [x.strip() for x in rts.splitlines() if x.strip()]

    wsl = run_bytes(["wsl", "-l", "-v"], 60)
    if wsl and not wsl.startswith("ERR ") and "Windows Subsystem" not in wsl.splitlines()[0]:
        extras["wsl"] = [x.strip() for x in wsl.replace("\x00", "").splitlines() if x.strip()]

    return apps, counts, extras


def probe_windows():
    o = ps_json(PS_PROBE, 180) or {}
    if not o:
        err("PowerShell probe: пустой ответ")
    extra = {
        "cpu": o.get("cpu", ""),
        "cpu_cores": o.get("cpu_cores", 0),
        "cpu_threads": o.get("cpu_threads", 0),
        "hyperv": o.get("hyperv", ""),
        "termservice": o.get("termservice", ""),
        "rdp_deny": o.get("rdp_deny", ""),
        "session_id": o.get("session_id", ""),
        "audio_service": o.get("audio", ""),
        "admin": o.get("admin", ""),
        "uac": o.get("uac", ""),
        "running": o.get("running", []),
    }
    display = {}
    w, h = to_int(o.get("screen_w", 0)), to_int(o.get("screen_h", 0))
    if w and h:
        display = {"width": w, "height": h, "depth": to_int(o.get("screen_depth", 0)) or 32,
                   "kind": "virtual"}

    cmds = {k[4:]: bool(v) for k, v in o.items() if k.startswith("cmd_")}
    user = os.environ.get("USERNAME") or "runner"
    connect = {}
    caps = []

    if "explorer" in (o.get("running") or []) or "dwm" in (o.get("running") or []):
        caps.append("gui")

    rdp_live = (to_int(o.get("rdp_deny", 1)) == 0 and o.get("termservice") == "Running"
                and bool(o.get("rdp_port")))
    connect["rdp"] = method(
        "available" if rdp_live else "needs-setup",
        port=3389, user="rdp", secrets=["RDP_PASSWORD"], max_minutes=350,
        setup=None if rdp_live else "workflow_dispatch windows-rdp.yml (включает RDP, SSH, туннель)")

    if cmds.get("sshd"):
        connect["ssh"] = method("available" if o.get("ssh_port") else "needs-setup",
                                port=22, user="rdp", secrets=[],
                                setup=None if o.get("ssh_port") else "Start-Service sshd")
    else:
        connect["ssh"] = method("needs-setup", port=22, user="rdp", secrets=[],
                                setup="Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0")

    if cmds.get("tailscale"):
        connect["tailscale"] = method("available", secrets=["TS_AUTHKEY"])
    else:
        connect["tailscale"] = method("needs-setup", secrets=["TS_AUTHKEY"],
                                      setup="windows-rdp.yml (ставит Tailscale)")

    if cmds.get("ssh"):
        connect["serveo"] = method("needs-setup",
                                   setup="ssh -R 0:localhost:3389 serveo.net")
    if cmds.get("ngrok"):
        connect["ngrok"] = method("needs-setup", setup="ngrok tcp 3389")
    if cmds.get("cloudflared"):
        connect["cloudflared"] = method("needs-setup", setup="cloudflared tunnel --url tcp://localhost:3389")

    caps += [k for k in ("rdp", "ssh", "tailscale", "serveo", "ngrok", "cloudflared") if k in connect]
    if o.get("audio") == "Running":
        caps.append("audio")
    if caps and "gui" in caps:
        caps.append("clipboard")
    return {"capabilities": caps, "connect": connect, "display": display, "extra": extra}


# ---------------------------------------------------------------- macOS: apps

def apps_macos():
    apps, extras, counts = [], {}, {}

    prof = run(["system_profiler", "SPApplicationsDataType", "-json"], 240)
    n = 0
    ok = False
    try:
        data = json.loads(prof)
        ok = True
    except Exception:
        data = {}
        err("system_profiler SPApplicationsDataType: не удалось разобрать JSON")

    for a in _as_list(data.get("SPApplicationsDataType") if isinstance(data, dict) else None):
        if not isinstance(a, dict) or not a.get("_name"):
            continue
        apps.append({
            "name": a.get("_name", ""),
            "version": str(a.get("version") or a.get("info") or ""),
            "source": "system_profiler",
            "path": a.get("path", ""),
            "publisher": str(a.get("obtained_from") or ""),
        })
        n += 1
    counts["system_profiler"] = n

    if not ok:  # запасной путь: только бандлы /Applications
        n = 0
        for app in sorted(glob.glob("/Applications/*.app")):
            ver = first_line(run(["plutil", "-extract", "CFBundleShortVersionString", "raw",
                                  os.path.join(app, "Contents", "Info.plist")], 20))
            if ver.startswith("ERR"):
                ver = ""
            apps.append({"name": os.path.basename(app)[:-4], "version": ver, "source": "bundle",
                         "path": app, "publisher": ""})
            n += 1
        counts["bundle"] = n

    brew = shutil.which("brew")
    if brew:
        out = run([brew, "list", "--versions"], 180)
        n = 0
        if not out.startswith("ERR "):
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    apps.append({"name": parts[0], "version": " ".join(parts[1:]), "source": "brew",
                                 "path": "", "publisher": ""})
                    n += 1
        counts["brew"] = n

        out = run([brew, "list", "--cask", "--versions"], 180)
        n = 0
        if not out.startswith("ERR "):
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    apps.append({"name": parts[0], "version": " ".join(parts[1:]), "source": "brew-cask",
                                 "path": "", "publisher": ""})
                    n += 1
        counts["brew-cask"] = n

    mas = shutil.which("mas")
    if mas:
        out = run([mas, "list"], 120)
        n = 0
        if not out.startswith("ERR "):
            for line in out.splitlines():
                m = re.match(r"^\s*(\d+)\s+(.*?)\s+([0-9][^\s]*)\s*$", line)
                if m:
                    apps.append({"name": m.group(2), "version": m.group(3), "source": "mas",
                                 "path": m.group(1), "publisher": "App Store"})
                    n += 1
        counts["mas"] = n

    return apps, counts, extras


# ---------------------------------------------------------------- macOS: probe

ARD_KICKSTART = ("/System/Library/CoreServices/RemoteManagement/"
                 "ARDAgent.app/Contents/Resources/kickstart")


def mac_display():
    raw = run(["system_profiler", "SPDisplaysDataType", "-json"], 90)
    try:
        j = json.loads(raw)
    except Exception:
        return {}
    for item in _as_list(j.get("SPDisplaysDataType")):
        if not isinstance(item, dict):
            continue
        texts = [str(item.get("spdisplays_resolution") or "")]
        for d in _as_list(item.get("spdisplays_ndrvs")):
            if isinstance(d, dict):
                texts.append(str(d.get("_spdisplays_pixels") or ""))
                texts.append(str(d.get("spdisplays_resolution") or ""))
        for t in texts:
            m = re.search(r"(\d{3,5})\s*x\s*(\d{3,5})", t)
            if m:
                return {"width": int(m.group(1)), "height": int(m.group(2)),
                        "depth": 32, "kind": "virtual"}
    return {}


def mac_audio():
    raw = run(["system_profiler", "SPAudioDataType", "-json"], 60)
    try:
        j = json.loads(raw)
    except Exception:
        return False
    return bool(re.search(r'coreaudio_device_(output|transport)', json.dumps(j)))


def probe_macos():
    procs = {}
    for p in ("WindowServer", "loginwindow", "Dock", "Finder", "SystemUIServer"):
        out = run(["pgrep", "-x", p], 10)
        procs[p] = bool(out.strip()) and not out.startswith("ERR ")

    display = mac_display()
    bins = {n: shutil.which(n) for n in
            ("sshd", "ssh", "tailscale", "cloudflared", "ngrok", "screencapture",
             "osascript", "sqlite3", "launchctl", "brew", "pbcopy", "pbpaste")}
    kick = os.path.exists(ARD_KICKSTART)
    ssh_listen = "LISTEN" in run(["lsof", "-nP", "-iTCP:22", "-sTCP:LISTEN"], 15)
    sharing = run(["launchctl", "print", "system/com.apple.screensharing"], 20)
    sharing_on = "state = running" in sharing

    user = os.environ.get("USER") or "runner"
    connect = {}
    if bins.get("sshd"):
        connect["ssh"] = method("available" if ssh_listen else "needs-setup",
                                port=22, user=user, secrets=[],
                                setup=None if ssh_listen else "sudo systemsetup -setremotelogin on")
    if kick:
        connect["vnc-ard"] = method("available" if sharing_on else "needs-setup",
                                    port=5900, secrets=[],
                                    setup=None if sharing_on else
                                    "sudo %s -activate -configure -access -on -restart -agent -privs -all"
                                    % ARD_KICKSTART)
    if bins.get("tailscale"):
        connect["tailscale"] = method("available", secrets=["TS_AUTHKEY"])
    elif bins.get("brew"):
        connect["tailscale"] = method("needs-setup", secrets=["TS_AUTHKEY"],
                                      setup="brew install tailscale; sudo tailscaled & tailscale up --authkey <TS_AUTHKEY>")
    if bins.get("cloudflared"):
        connect["cloudflared"] = method("needs-setup", setup="cloudflared tunnel --url tcp://localhost:5900")
    if bins.get("ngrok"):
        connect["ngrok"] = method("needs-setup", setup="ngrok tcp 5900")
    if bins.get("ssh"):
        connect["serveo"] = method("needs-setup", setup="ssh -R 0:localhost:5900 serveo.net")

    caps = []
    if procs.get("WindowServer"):
        caps.append("gui")
    caps += [k for k in ("ssh", "vnc-ard", "tailscale", "cloudflared", "ngrok", "serveo") if k in connect]
    if mac_audio():
        caps.append("audio")
    if bins.get("pbcopy") and bins.get("pbpaste"):
        caps.append("clipboard")
    if bins.get("screencapture"):
        caps.append("screenshot")

    extra = {
        "processes": {k: v for k, v in procs.items() if v},
        "screensharing": "running" if sharing_on else "",
        "sip": first_line(run(["csrutil", "status"], 15)),
        "gatekeeper": first_line(run(["spctl", "--status"], 15)),
        "filevault": first_line(run(["fdesetup", "status"], 20)),
        "ard_kickstart": ARD_KICKSTART if kick else "",
    }
    tcc = run(["sqlite3", os.path.expanduser("~/Library/Application Support/com.apple.TCC/TCC.db"),
               "select service,client,auth_value from access "
               "where service in ('kTCCServiceScreenCapture','kTCCServiceAccessibility');"], 30)
    if tcc and not tcc.startswith("ERR ") and "Error" not in tcc:
        extra["tcc"] = [x.strip() for x in tcc.splitlines() if x.strip()]

    return {"capabilities": caps, "connect": connect, "display": display, "extra": extra}


# ---------------------------------------------------------------- Linux: probe

def linux_display():
    d = os.environ.get("DISPLAY", "")
    if not d:
        return {}
    out = run(["xdpyinfo", "-display", d], 20)
    m = re.search(r"dimensions:\s+(\d+)x(\d+) pixels", out)
    depth = re.search(r"depth of root window:\s+(\d+)", out)
    if m:
        return {"width": int(m.group(1)), "height": int(m.group(2)),
                "depth": to_int(depth.group(1)) if depth else 24, "kind": "virtual"}
    return {}


def probe_linux():
    names = ("Xvfb", "x11vnc", "tigervncserver", "vncserver", "xrdp", "novnc_proxy",
             "websockify", "openbox", "startxfce4", "xfce4-session", "gnome-shell",
             "startlxqt", "lxqt-session", "xterm", "xdotool", "scrot", "import",
             "ffmpeg", "pulseaudio", "pipewire", "sshd", "tailscale", "cloudflared",
             "ngrok", "xclip", "xsel", "xdpyinfo", "docker")
    bins = {n: shutil.which(n) for n in names}
    display = linux_display()
    listen = sorted({int(m.group(1)) for m in re.finditer(r":(\d{1,5})\s", run(["ss", "-ltn"], 15))})

    user = os.environ.get("USER") or os.environ.get("USERNAME") or "runner"
    connect = {}
    if bins["sshd"]:
        running = 22 in listen
        connect["ssh"] = method("available" if running else "needs-setup", port=22,
                                user=user, secrets=[],
                                setup=None if running else "sudo systemctl start ssh")
    if bins["x11vnc"]:
        connect["vnc"] = method("needs-setup", port=5900, user=user, secrets=[],
                                setup="Xvfb :99 & DISPLAY=:99 x11vnc -forever -nopw -listen 0.0.0.0")
    elif bins["tigervncserver"] or bins["vncserver"]:
        connect["vnc"] = method("needs-setup", port=5900, user=user, secrets=[],
                                setup="vncserver :99")
    elif shutil.which("apt-get"):
        connect["vnc"] = method("needs-setup", port=5900, user=user, secrets=[],
                                setup="sudo apt-get install -y x11vnc")
    if bins["novnc_proxy"] or bins["websockify"]:
        connect["novnc"] = method("needs-setup", port=6080,
                                  setup="websockify --web /usr/share/novnc 6080 localhost:5900")
    elif shutil.which("apt-get"):
        connect["novnc"] = method("needs-setup", port=6080,
                                  setup="sudo apt-get install -y novnc websockify")
    if bins["xrdp"]:
        connect["rdp"] = method("needs-setup", port=3389, user=user, secrets=[],
                                setup="sudo systemctl enable --now xrdp")
    if bins["tailscale"]:
        connect["tailscale"] = method("available", secrets=["TS_AUTHKEY"])
    else:
        connect["tailscale"] = method("needs-setup", secrets=["TS_AUTHKEY"],
                                      setup="curl -fsSL https://tailscale.com/install.sh | sh")
    if shutil.which("ssh"):
        connect["serveo"] = method("needs-setup", setup="ssh -R 0:localhost:5900 serveo.net")
    if bins["cloudflared"]:
        connect["cloudflared"] = method("needs-setup", setup="cloudflared tunnel --url tcp://localhost:5900")
    if bins["ngrok"]:
        connect["ngrok"] = method("needs-setup", setup="ngrok tcp 5900")

    caps = []
    if display:
        caps.append("gui")
    elif bins["Xvfb"]:
        caps.append("gui-xvfb")
    for key, de in (("startxfce4", "xfce"), ("xfce4-session", "xfce"),
                    ("gnome-shell", "gnome"), ("lxqt-session", "lxqt"),
                    ("openbox", "openbox")):
        if bins[key]:
            caps.append("desktop-" + de)
            break
    caps += [k for k in ("ssh", "vnc", "rdp", "novnc", "tailscale", "serveo", "ngrok", "cloudflared")
             if k in connect]
    if bins["pulseaudio"] or bins["pipewire"]:
        caps.append("audio")
    if bins["xclip"] or bins["xsel"]:
        caps.append("clipboard")
    if bins["scrot"] or bins["import"]:
        caps.append("screenshot")
    if os.path.exists("/dev/kvm"):
        caps.append("kvm")

    extra = {"listen": listen}
    if display:
        extra["display_env"] = os.environ.get("DISPLAY", "")
    if os.path.isdir("/tmp/.X11-unix"):
        extra["x11_sockets"] = sorted(os.listdir("/tmp/.X11-unix"))
    if os.path.isdir("/dev/dri"):
        extra["dri"] = sorted(os.listdir("/dev/dri"))
    sd = first_line(run(["systemd-detect-virt"], 10))
    if sd and not sd.startswith("ERR"):
        extra["virt"] = sd
    if bins["docker"]:
        v = first_line(run(["docker", "info", "--format", "{{.ServerVersion}}"], 30))
        if v and not v.startswith("ERR") and not v.startswith("{"):
            extra["docker_server"] = v
    return {"capabilities": caps, "connect": connect, "display": display, "extra": extra}


def probe():
    if IS_LINUX:
        return probe_linux()
    if IS_WIN:
        return probe_windows()
    if IS_MAC:
        return probe_macos()
    return {"capabilities": [], "connect": {}, "display": {}, "extra": {}}


# ------------------------------------------------------------------- Xcode

def xcode_block(base):
    if not IS_MAC:
        return None
    xcodes = base.get("xcodes") or []
    if not xcodes:
        # минимальный запасной сбор: версии из бандлов, без SDK
        seen = set()
        for app in sorted(glob.glob("/Applications/Xcode*.app")):
            real = os.path.realpath(app)
            if real in seen:
                continue
            seen.add(real)
            ver = first_line(run(["plutil", "-extract", "CFBundleShortVersionString", "raw",
                                  os.path.join(app, "Contents", "version.plist")], 20))
            build = first_line(run(["plutil", "-extract", "ProductBuildVersion", "raw",
                                    os.path.join(app, "Contents", "version.plist")], 20))
            xcodes.append({"app": os.path.basename(app), "real": os.path.basename(real),
                           "version": ("Xcode " + ver).strip() if ver and not ver.startswith("ERR") else "",
                           "build": build if not build.startswith("ERR") else "",
                           "sdks": [], "swift": "", "clang": ""})
        if xcodes:
            err("mac-inventory.py: Xcode собран запасным способом")

    default = base.get("xcode_default_version", "")
    default_build = ""
    default_real = base.get("xcode_default", "")
    for c in xcodes:
        if (default and c.get("version") == default) or (default_real and c.get("real") == default_real):
            default_build = c.get("build", "")
            break
    return {
        "select": base.get("xcode_select", ""),
        "default": default,
        "default_build": re.sub(r"^Build version\s*", "", default_build),
        "clt": base.get("clt_version", ""),
        "all": [{"app": c.get("app", ""), "version": c.get("version", ""),
                 "build": re.sub(r"^Build version\s*", "", c.get("build", "")),
                 "sdks": c.get("sdks", []),
                 "swift": c.get("swift", ""), "clang": c.get("clang", "")} for c in xcodes],
        "simulators": base.get("simulators", []),
        "macos_sdk": first_line(run(["xcodebuild", "-version", "-sdk", "macosx"], 60)),
    }


# ------------------------------------------------------------------- вывод

def tsv_field(v):
    if v is None:
        return ""
    return " ".join(str(v).replace("\t", " ").splitlines()).strip()


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text if text.endswith("\n") else text + "\n")


def os_txt(osd):
    lines = ["# %s" % pick(osd.get("name"), platform.platform()),
             "platform: %s" % platform.platform(),
             "machine: %s" % platform.machine(),
             "python: %s" % sys.version.replace("\n", " ")]
    if IS_LINUX:
        for p in ("/etc/os-release", "/proc/version"):
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    lines.append("## %s\n%s" % (p, fh.read().strip()))
            except Exception:
                pass
        lines.append("## uname -a\n%s" % run(["uname", "-a"], 10))
        lines.append("## virt\n%s" % run(["systemd-detect-virt"], 10))
    elif IS_MAC:
        lines.append("## sw_vers\n%s" % run(["sw_vers"], 10))
        lines.append("## uname -a\n%s" % run(["uname", "-a"], 10))
        lines.append("## hardware\n%s" % run(["system_profiler", "SPHardwareDataType"], 120))
    elif IS_WIN:
        lines.append("## systeminfo\n%s" % run_bytes(["systeminfo"], 180))
        lines.append("## ver\n%s" % run(["cmd", "/c", "ver"], 10))
    return "\n\n".join(lines)


def build_summary(data):
    label = data.get("label") or "runner"
    osd, hw, img = data.get("os") or {}, data.get("hardware") or {}, data.get("image") or {}
    counts = data.get("counts") or {}
    caps = data.get("capabilities") or []
    conn = data.get("connect") or {}
    disp = data.get("display") or {}
    xc = data.get("xcode")
    tools = data.get("tools") or {}

    out = ["### %s" % label]
    head = "**%s**" % pick(osd.get("name"), "unknown")
    if osd.get("build"):
        head += " (build %s)" % osd["build"]
    if osd.get("kernel"):
        head += ", ядро %s" % osd["kernel"]
    arch = (data.get("runner") or {}).get("arch", "")
    if arch:
        head += ", %s" % arch
    if img.get("os") or img.get("version"):
        head += " · образ `%s` %s" % (img.get("os", ""), img.get("version", ""))
    out.append(head)
    out.append("")

    parts = []
    if hw.get("cpu"):
        parts.append(hw["cpu"])
    if hw.get("ncpu"):
        c = "%d vCPU" % hw["ncpu"]
        if hw.get("ncpu_physical"):
            c += " (%d cores)" % hw["ncpu_physical"]
        parts.append(c)
    if hw.get("ram_gb"):
        parts.append("%s GB RAM" % hw["ram_gb"])
    if hw.get("disk_total_gb"):
        parts.append("диск %s/%s GB" % (hw.get("disk_total_gb"), hw.get("disk_free_gb", "")))
    if hw.get("virt"):
        parts.append("virt %s" % hw["virt"])
    if parts:
        out.append("- Железо: " + " · ".join(parts))

    if counts.get("apps"):
        by = ", ".join("%s %s" % (k, v) for k, v in sorted(counts.items())
                       if k != "apps" and isinstance(v, int) and v)
        out.append("- Приложения: %d%s" % (counts["apps"], " (%s)" % by if by else ""))

    if tools:
        keys = ("python3", "node", "go", "rustc", "java", "dotnet", "docker", "swift", "xcodebuild")
        t = ["%s %s" % (k, tools[k]) for k in keys if tools.get(k)]
        if t:
            out.append("- Инструменты: " + "; ".join(t))
        out.append("- Всего инструментов: %d" % len(tools))

    if caps:
        out.append("- Возможности: " + ", ".join(caps))
    if conn:
        c = []
        for k in sorted(conn):
            st = (conn[k] or {}).get("status", "")
            c.append(k + ("*" if st == "needs-setup" else ""))
        out.append("- Подключение: " + ", ".join(c) + "  (* — включается штатной командой)")
    if disp:
        out.append("- Экран: %sx%sx%s (%s)" % (disp.get("width"), disp.get("height"),
                                               disp.get("depth"), disp.get("kind", "")))

    if xc:
        if xc.get("default"):
            out.append("- Xcode по умолчанию: %s%s" % (
                xc["default"], " (%s)" % xc["default_build"] if xc.get("default_build") else ""))
        if xc.get("all"):
            out.append("- Xcode в образе: " + ", ".join(
                x.get("version", "") for x in xc["all"] if x.get("version")))
        if xc.get("clt"):
            out.append("- CLT: %s" % xc["clt"])
        if xc.get("simulators"):
            out.append("- Симуляторы: " + ", ".join(xc["simulators"]))

    errs = data.get("errors") or []
    if errs:
        out.append("- Ошибки сбора: %d (см. errors.txt)" % len(errs))
    out.append("")
    out.append("Собрано за %s с." % data.get("collect_seconds", ""))
    return "\n".join(out) + "\n"


def write_outputs(out_dir, data, apps, tools, tool_cmds):
    os.makedirs(out_dir, exist_ok=True)

    write_text(os.path.join(out_dir, "inventory.json"),
               json.dumps(data, ensure_ascii=False, indent=1))

    lines = ["name\tversion\tsource\tpath\tpublisher"]
    for a in apps:
        lines.append("\t".join(tsv_field(a.get(k, "")) for k in
                               ("name", "version", "source", "path", "publisher")))
    write_text(os.path.join(out_dir, "apps.tsv"), "\n".join(lines))

    lines = ["tool\tversion\tcommand"]
    for k in sorted(tools):
        lines.append("\t".join([tsv_field(k), tsv_field(tools[k]), tsv_field(tool_cmds.get(k, ""))]))
    write_text(os.path.join(out_dir, "tools.tsv"), "\n".join(lines))

    write_text(os.path.join(out_dir, "os.txt"), os_txt(data.get("os") or {}))
    with open(os.path.join(out_dir, "errors.txt"), "w", encoding="utf-8", newline="\n") as fh:
        errs = data.get("errors") or []
        if errs:
            fh.write("\n".join(errs) + "\n")
    write_text(os.path.join(out_dir, "summary.md"), build_summary(data))


# ------------------------------------------------------------------- main

def load_base():
    name = "mac-inventory.py" if IS_MAC else "env-inventory.py"
    script = os.path.join(HERE, name)
    if not os.path.isfile(script):
        err("базовый скрипт не найден: %s" % name)
        return {}
    try:
        r = subprocess.run([sys.executable, script], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300,
                           cwd=os.path.dirname(HERE), creationflags=NO_WINDOW)
        return json.loads(r.stdout.lstrip("\ufeff"))
    except Exception as ex:
        err("базовый скрипт %s: %s" % (name, ex))
        return {}


def collect_apps():
    if IS_LINUX:
        return apps_linux()
    if IS_WIN:
        return apps_windows()
    if IS_MAC:
        return apps_macos()
    return [], {}, {}


def dedup(apps):
    seen, out = set(), []
    for a in apps:
        name = (a.get("name") or "").strip()
        if not name:
            continue
        a["name"] = name
        key = (name.lower(), a.get("version", ""), a.get("source", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    out.sort(key=lambda x: (x.get("source", ""), x["name"].lower()))
    return out


def main():
    ap = argparse.ArgumentParser(description="Полная инвентаризация GitHub-раннера")
    ap.add_argument("--out", default="out")
    ap.add_argument("--no-apps", action="store_true")
    ap.add_argument("--label", default=os.environ.get("INV_LABEL", ""))
    args = ap.parse_args()

    base = load_base()
    probe_data = probe()
    osd = os_info()
    hw = hardware(probe_data.get("extra") or {})

    if base:
        hw["ram_gb"] = pick(hw.get("ram_gb"), base.get("ram_gb"))
        hw["disk_total_gb"] = pick(hw.get("disk_total_gb"), base.get("disk_total_gb"))
        hw["disk_free_gb"] = pick(hw.get("disk_free_gb"), base.get("disk_free_gb"))
        hw["ncpu"] = pick(hw.get("ncpu"), base.get("ncpu"))
        hw["cpu"] = pick(hw.get("cpu"), base.get("cpu"))
        if IS_MAC and base.get("macos"):
            osd["name"] = "macOS " + base["macos"]
            osd["version"] = base["macos"]
            osd["build"] = base.get("macos_build", osd.get("build", ""))

    tools, tool_cmds = collect_tools()
    if base.get("tools"):
        for k, v in base["tools"].items():
            if v and k not in tools:
                tools[k] = v
                tool_cmds[k] = "%s --version" % k
    if base.get("brew_formulae"):
        probe_data.setdefault("extra", {})["brew_formulae"] = base["brew_formulae"]

    if args.no_apps:
        apps, counts, app_extra = [], {}, {}
        if IS_LINUX:
            manual = run(["apt-mark", "showmanual"], 60)
            if not manual.startswith("ERR "):
                app_extra["apt_manual"] = sorted({x.strip() for x in manual.splitlines() if x.strip()})
    else:
        apps, counts, app_extra = collect_apps()
        apps = dedup(apps)
        counts["apps"] = len(apps)

    extra = dict(probe_data.get("extra") or {})
    extra.update(app_extra)
    xcode = xcode_block(base)

    label = args.label or platform.node()
    data = {
        "schema": 1,
        "label": label,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runner": {
            "os": os.environ.get("RUNNER_OS", platform.system()),
            "arch": os.environ.get("RUNNER_ARCH", platform.machine()),
            "name": os.environ.get("RUNNER_NAME", ""),
        },
        "image": {
            "os": os.environ.get("ImageOS", base.get("image_os", "")),
            "version": os.environ.get("ImageVersion", base.get("image_version", "")),
        },
        "os": osd,
        "hardware": hw,
        "tools": tools,
        "capabilities": probe_data.get("capabilities") or [],
        "connect": probe_data.get("connect") or {},
        "display": probe_data.get("display") or {},
        "limits": {"job_minutes": 15 if label == "ubuntu-slim" else 360},
        "xcode": xcode,
        "apps": apps[:5000],
        "truncated": len(apps) > 5000,
        "counts": counts,
        "extra": extra,
        "errors": ERRORS,
        "collect_seconds": round(time.time() - STARTED, 1),
    }
    write_outputs(args.out, data, apps, tools, tool_cmds)
    print("full-inventory: %s apps=%d tools=%d errors=%d %ss" % (
        label, len(apps), len(tools), len(ERRORS), data["collect_seconds"]))


if __name__ == "__main__":
    main()
