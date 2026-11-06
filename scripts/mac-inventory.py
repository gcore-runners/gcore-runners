#!/usr/bin/env python3
"""Опись macOS-раннера GitHub: образ, железо, Xcode (SDK, Swift, Clang), симуляторы и версии инструментов.

Печатает JSON в stdout (его и сохраняем в inv.json). Всё, что не удалось узнать, — пустая строка,
чтобы опись оставалась валидной и сравнимой между прогонами.
"""
import glob, json, os, platform, re, shlex, subprocess, sys, time

started = time.time()

def sh(cmd, env=None, timeout=120):
    """stdout+stderr команды; при сбое/таймауте — строка ERR ..."""
    try:
        e = dict(os.environ)
        if env:
            e.update(env)
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, env=e)
        return (r.stdout + r.stderr).strip()
    except Exception as ex:
        return "ERR %s" % ex

def first(cmd, env=None, timeout=60):
    """Первая непустая строка вывода или пустая строка."""
    out = sh(cmd, env, timeout)
    if not out or out.startswith("ERR "):
        return ""
    for line in out.splitlines():
        line = line.strip()
        if line:
            return line
    return ""

# Ответы-заглушки (заглушка java, xcodebuild без Xcode) версией не считаем.
BAD = ("error", "unable", "not found", "no such file", "cannot find", "couldn\u2019t", "couldn't")

def clean(v):
    if not v or any(b in v.lower() for b in BAD):
        return ""
    return v

def ver_line(out):
    """Строка с версией: пропускаем заголовки вида '... at path:' и пути."""
    for line in out.splitlines():
        line = line.strip()
        if not line or line.endswith(":") or line.startswith(("/", "-")):
            continue
        if any(ch.isdigit() for ch in line):
            return clean(line)
    return ""

def tool(name, cmd=None, check=None):
    """Версия инструмента; если его нет в PATH, пробуем типовые каталоги (go лежит в /usr/local/go/bin)."""
    cmd = cmd or "%s --version" % name
    binname = check or name
    if first("command -v %s" % shlex.quote(binname), timeout=10):
        return ver_line(sh(cmd, timeout=30))
    for d in ("/usr/local/go/bin", "/opt/homebrew/bin", "/usr/local/bin"):
        if os.path.exists(os.path.join(d, binname)):
            return ver_line(sh(cmd, env={"PATH": d + ":" + os.environ.get("PATH", "")}, timeout=30))
    return ""

def num(cmd, cast=int, default=0):
    """Число из команды; мусор и сбой — default (скрипт не должен падать из-за описи)."""
    try:
        return cast(sh(cmd).strip())
    except Exception:
        return default

def xcode(app):
    """Один Xcode: версия, сборка, SDK, Swift, Clang. Симуляторы общие для образа — см. ниже."""
    dev = app + "/Contents/Developer"
    env = {"DEVELOPER_DIR": dev}
    lines = [l.strip() for l in sh("xcodebuild -version", env).splitlines() if l.strip()]
    ver = next((l for l in lines if l.startswith("Xcode")), "")
    build = next((l for l in lines if l.startswith("Build version")), "")
    if not ver:  # лицензия не принята или xcodebuild недоступен — читаем версию из бандла
        pl = shlex.quote(app + "/Contents/version.plist")
        v = first("plutil -extract CFBundleShortVersionString raw %s" % pl, timeout=30)
        ver = ("Xcode " + v).strip() if v else ""
    sdks = sorted(set(re.findall(r"-sdk (\S+)", sh("xcodebuild -showsdks", env, 120))))
    return {
        "app": os.path.basename(app),
        "real": os.path.basename(os.path.realpath(app)),
        "version": ver,
        "build": build,
        "sdks": sdks,
        "swift": first("xcrun swift --version", env, 120),
        "clang": first("xcrun clang --version", env, 120),
    }

def sims():
    """Установленные рантаймы симуляторов (одинаковы для всех Xcode образа)."""
    out = sh("xcrun simctl list runtimes", timeout=180)
    return sorted(set(re.findall(r"^(\S+ \S+) \(", out, re.M)))

# Инструменты, которые реально нужны для задач на macOS-раннере: сборка, языки, мобильные и контейнеры.
TOOLS = [
    ("python3", "python3 --version"),
    ("pip3", "python3 -m pip --version"),
    ("node", "node --version"),
    ("npm", "npm --version"),
    ("yarn", "yarn --version"),
    ("pnpm", "pnpm --version"),
    ("bun", "bun --version"),
    ("ruby", "ruby --version"),
    ("gem", "gem --version"),
    ("bundler", "bundle --version", "bundle"),
    ("cocoapods", "pod --version", "pod"),
    ("fastlane", "fastlane --version"),
    ("go", "go version"),
    ("java", "java -version"),
    ("javac", "javac -version"),
    ("dotnet", "dotnet --version"),
    ("rustc", "rustc --version"),
    ("cargo", "cargo --version"),
    ("cmake", "cmake --version"),
    ("ninja", "ninja --version"),
    ("make", "make --version"),
    ("git", "git --version"),
    ("brew", "brew --version"),
    ("xcodegen", "xcodegen --version"),
    ("xcbeautify", "xcbeautify --version"),
    ("swiftlint", "swiftlint version"),
    ("swiftformat", "swiftformat --version"),
    ("carthage", "carthage version"),
    ("docker", "docker --version"),
    ("qemu-system-x86_64", "qemu-system-x86_64 --version"),
]

tools = {}
for item in TOOLS:
    tools[item[0]] = tool(*item)

brew_formulae = ""
if tools.get("brew"):
    n = first("brew list --formula 2>/dev/null | wc -l", timeout=60).strip()
    brew_formulae = int(n) if n.isdigit() else 0

# Все Xcode: симлинки Xcode.app -> Xcode_N.app не дублируем (сравниваем realpath).
seen, xcodes = set(), []
for app in sorted(glob.glob("/Applications/Xcode*.app")):
    real = os.path.realpath(app)
    if real in seen:
        continue
    seen.add(real)
    xcodes.append(xcode(app))

default_dir = sh("xcode-select -p")
default_real = ""
if default_dir.startswith("/"):
    default_real = os.path.basename(os.path.realpath(default_dir.split("/Contents")[0]))
default_ver = ""
for c in xcodes:
    if c["real"] == default_real:
        default_ver = c["version"]
        break
if not default_ver:
    default_ver = next((l for l in sh("xcodebuild -version").splitlines() if l.strip().startswith("Xcode")), "").strip()

st = os.statvfs("/")
out = {
    "label": os.environ.get("INV_LABEL", ""),
    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "image_os": os.environ.get("ImageOS", ""),
    "image_version": os.environ.get("ImageVersion", ""),
    "macos": sh("sw_vers -productVersion"),
    "macos_build": sh("sw_vers -buildVersion"),
    "arch": platform.machine(),
    "cpu": clean(first("sysctl -n machdep.cpu.brand_string")) or clean(first("sysctl -n hw.model")),
    "ncpu": num("sysctl -n hw.ncpu"),
    "ram_gb": round(num("sysctl -n hw.memsize") / 2**30, 1),
    "disk_total_gb": round(st.f_blocks * st.f_frsize / 2**30),
    "disk_free_gb": round(st.f_bavail * st.f_frsize / 2**30),
    "xcode_select": default_dir,
    "xcode_default": default_real,
    "xcode_default_version": default_ver,
    "clt_version": first("pkgutil --pkg-info=com.apple.pkg.CLTools_Executables 2>/dev/null | sed -n 's/^version: //p'", timeout=30),
    "xcodes": xcodes,
    "simulators": sims(),
    "tools": tools,
    "brew_formulae": brew_formulae,
    "collect_seconds": round(time.time() - started, 1),
}
json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
