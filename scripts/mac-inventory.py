#!/usr/bin/env python3
"""Опись macOS-раннера: образ, железо, все Xcode (SDK, Swift, Clang, симуляторы). JSON в stdout."""
import glob, json, os, platform, re, subprocess, sys

def sh(cmd, env=None, timeout=120):
    try:
        e = dict(os.environ, **(env or {}))
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, env=e)
        return (r.stdout + r.stderr).strip()
    except Exception as ex:
        return f"ERR {ex}"

def xcode(app):
    dev = app + "/Contents/Developer"
    env = {"DEVELOPER_DIR": dev}
    v = sh("xcodebuild -version", env).splitlines()
    sdks = re.findall(r"-sdk (\S+)", sh("xcodebuild -showsdks", env))
    swift = (sh("xcrun swift --version", env).splitlines() or [""])[0]
    clang = (sh("xcrun clang --version", env).splitlines() or [""])[0]
    sims = sorted(set(re.findall(r"^(\S+ \S+) \(", sh("xcrun simctl list runtimes", env, 180), re.M)))
    return {"app": os.path.basename(app), "real": os.path.basename(os.path.realpath(app)),
            "version": v[0] if v else "", "build": v[1] if len(v) > 1 else "",
            "sdks": sdks, "swift": swift, "clang": clang, "simulators": sims}

seen, xs = set(), []
for a in sorted(glob.glob("/Applications/Xcode*.app")):  # симлинки Xcode.app -> Xcode_N.app не дублируем
    r = os.path.realpath(a)
    if r in seen:
        continue
    seen.add(r)
    xs.append(xcode(a))
default_dir = sh("xcode-select -p")
default_real = os.path.basename(os.path.realpath(default_dir.split("/Contents")[0])) if default_dir.startswith("/") else ""
st = os.statvfs("/")
out = {
    "label": os.environ.get("INV_LABEL", ""),
    "image_os": os.environ.get("ImageOS", ""),
    "image_version": os.environ.get("ImageVersion", ""),
    "macos": sh("sw_vers -productVersion"), "macos_build": sh("sw_vers -buildVersion"),
    "arch": platform.machine(),
    "cpu": sh("sysctl -n machdep.cpu.brand_string") or sh("sysctl -n hw.model"),
    "ncpu": int(sh("sysctl -n hw.ncpu") or 0),
    "ram_gb": round(int(sh("sysctl -n hw.memsize") or 0) / 2**30, 1),
    "disk_total_gb": round(st.f_blocks * st.f_frsize / 2**30),
    "disk_free_gb": round(st.f_bavail * st.f_frsize / 2**30),
    "xcode_select": default_dir, "xcode_default": default_real,
    "xcode_default_version": (sh("xcodebuild -version").splitlines() or [""])[0],
    "xcodes": xs,
}
json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
