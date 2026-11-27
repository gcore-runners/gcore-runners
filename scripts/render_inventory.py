#!/usr/bin/env python3
"""Сводка по артефактам full-inventory: Markdown в stdout и машинный каталог.

    python3 scripts/render_inventory.py artifacts [--out report] [--baseline old]

Читает artifacts/*/inventory.json (или inventory.json прямо в каталоге).
В --out пишет inventory.md, inventory-all.json, catalog.json, apps-all.tsv,
tools-matrix.tsv. В отчёт попадают только те метки, чьи данные реально собраны.
"""
import argparse
import glob
import json
import os
import sys
import time

FAMILIES = ("ubuntu", "windows", "macos", "xcode")


def family(inv):
    label = inv.get("label", "") if isinstance(inv, dict) else str(inv)
    if label.startswith("xcode"):
        return "macos"
    for f in FAMILIES:
        if label.startswith(f):
            return f
    if isinstance(inv, dict):
        osname = ((inv.get("os") or {}).get("name") or "").lower()
        if "windows" in osname:
            return "windows"
        if "macos" in osname or inv.get("xcode"):
            return "macos"
        if "ubuntu" in osname or "linux" in osname:
            return "ubuntu"
    return "other"


def sort_key(inv):
    fam = family(inv)
    return (FAMILIES.index(fam) if fam in FAMILIES else 9, inv.get("label", ""))


def load_inventories(src):
    paths = []
    if os.path.isfile(src):
        paths = [src]
    elif os.path.isdir(src):
        paths = [os.path.join(src, "inventory.json")]
        paths += glob.glob(os.path.join(src, "*", "inventory.json"))
        paths += glob.glob(os.path.join(src, "*", "*", "inventory.json"))
    seen, invs = set(), []
    for p in paths:
        if not os.path.isfile(p):
            continue
        rp = os.path.realpath(p)
        if rp in seen:
            continue
        seen.add(rp)
        try:
            with open(p, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as ex:
            print("render: пропуск %s (%s)" % (p, ex), file=sys.stderr)
            continue
        if isinstance(data, dict) and data.get("label"):
            invs.append(data)
    # один label — одна запись; при повторах (report + label-папка) берём первую
    seen_labels, unique = set(), []
    for inv in invs:
        if inv["label"] in seen_labels:
            continue
        seen_labels.add(inv["label"])
        unique.append(inv)
    invs = unique
    invs.sort(key=sort_key)
    return invs


def cell(v):
    return str(v if v is not None else "").replace("|", "\\|").replace("\n", " ")


def vcpu_ram(inv):
    hw = inv.get("hardware") or {}
    a = "%s vCPU" % hw["ncpu"] if hw.get("ncpu") else ""
    b = "%s GB" % hw["ram_gb"] if hw.get("ram_gb") else ""
    return " / ".join(x for x in (a, b) if x)


def gui_cell(inv):
    caps = inv.get("capabilities") or []
    for k in ("gui", "gui-xvfb"):
        if k in caps:
            return k
    for k in caps:
        if k.startswith("desktop-"):
            return k
    return ""


def connect_cell(inv):
    conn = inv.get("connect") or {}
    items = []
    for k in sorted(conn):
        st = (conn[k] or {}).get("status", "")
        items.append(k + ("*" if st == "needs-setup" else ""))
    return ", ".join(items)


def xcode_default(inv):
    xc = inv.get("xcode")
    return (xc or {}).get("default", "") if xc else ""


def image_cell(inv):
    img = inv.get("image") or {}
    s = " ".join(x for x in (img.get("os", ""), img.get("version", "")) if x)
    return s


def os_line(inv):
    o = inv.get("os") or {}
    r = inv.get("runner") or {}
    parts = [o.get("name") or "unknown"]
    if o.get("version") and o.get("version") not in (o.get("name") or ""):
        parts.append(o["version"])
    if o.get("build"):
        parts.append("build %s" % o["build"])
    if o.get("kernel"):
        parts.append("ядро %s" % o["kernel"])
    if r.get("arch"):
        parts.append(r["arch"])
    return ", ".join(parts)


def hardware_line(inv):
    hw = inv.get("hardware") or {}
    parts = []
    if hw.get("cpu"):
        parts.append(hw["cpu"])
    c = "%s vCPU" % hw["ncpu"] if hw.get("ncpu") else ""
    if c and hw.get("ncpu_physical"):
        c += " (%s cores)" % hw["ncpu_physical"]
    if c:
        parts.append(c)
    if hw.get("ram_gb"):
        parts.append("%s GB RAM" % hw["ram_gb"])
    if hw.get("disk_total_gb"):
        parts.append("диск %s/%s GB" % (hw.get("disk_total_gb"), hw.get("disk_free_gb", "")))
    if hw.get("virt"):
        parts.append("virt %s" % hw["virt"])
    return " · ".join(parts)


def counts_line(inv):
    c = inv.get("counts") or {}
    if not c.get("apps"):
        return ""
    by = ", ".join("%s %s" % (k, v) for k, v in sorted(c.items())
                   if k != "apps" and isinstance(v, int) and v)
    return "%d%s" % (c["apps"], " (%s)" % by if by else "")


def tools_line(inv):
    t = inv.get("tools") or {}
    keys = ("python3", "node", "go", "rustc", "java", "dotnet", "docker",
            "swift", "xcodebuild", "java", "brew")
    seen, parts = set(), []
    for k in keys:
        if k in seen:
            continue
        seen.add(k)
        if t.get(k):
            parts.append("%s %s" % (k, t[k]))
    return "; ".join(parts) + ("; всего %d" % len(t) if t else "")


def display_line(inv):
    d = inv.get("display") or {}
    return "%sx%sx%s (%s)" % (d.get("width"), d.get("height"), d.get("depth"), d.get("kind", "")) if d else ""


def connect_line(inv):
    conn = inv.get("connect") or {}
    if not conn:
        return ""
    parts = []
    for k in sorted(conn):
        c = conn[k] or {}
        s = "%s: %s" % (k, c.get("status", ""))
        extra = []
        if c.get("port"):
            extra.append("порт %s" % c["port"])
        if c.get("user"):
            extra.append("польз. %s" % c["user"])
        if c.get("max_minutes"):
            extra.append("до %s мин" % c["max_minutes"])
        if c.get("secrets"):
            extra.append("секреты %s" % ", ".join(c["secrets"]))
        if extra:
            s += " (%s)" % ", ".join(extra)
        parts.append(s)
    return "; ".join(parts)


def xcode_lines(inv):
    xc = inv.get("xcode")
    if not xc:
        return []
    lines = []
    if xc.get("default"):
        s = "- Xcode по умолчанию: **%s**" % xc["default"]
        if xc.get("default_build"):
            s += " (build %s)" % xc["default_build"]
        if xc.get("select"):
            s += ", `%s`" % xc["select"]
        lines.append(s)
    for x in xc.get("all") or []:
        s = "- Xcode: %s" % x.get("version", "")
        if x.get("build"):
            s += " (build %s)" % x["build"]
        if x.get("sdks"):
            s += " · SDK: %s" % ", ".join(x["sdks"])
        if x.get("swift"):
            s += " · %s" % x["swift"]
        if x.get("clang"):
            s += " · %s" % x["clang"]
        lines.append(s)
    if xc.get("clt"):
        lines.append("- CLT: %s" % xc["clt"])
    if xc.get("macos_sdk"):
        lines.append("- macOS SDK: %s" % xc["macos_sdk"])
    if xc.get("simulators"):
        lines.append("- Симуляторы: %s" % ", ".join(xc["simulators"]))
    return lines


def extra_lines(inv):
    ex = inv.get("extra") or {}
    out = []
    vs = ex.get("visual_studio") or []
    if vs:
        out.append("- Visual Studio: " + ", ".join(
            "%s %s" % (v.get("name", ""), v.get("version", "")) for v in vs))
    if ex.get("windows_sdk"):
        out.append("- Windows SDK: " + ", ".join(ex["windows_sdk"]))
    if ex.get("dotnet_sdks"):
        out.append("- .NET SDK: " + ", ".join(ex["dotnet_sdks"]))
    if ex.get("wsl"):
        out.append("- WSL: " + " / ".join(ex["wsl"]))
    if ex.get("apt_manual"):
        out.append("- apt-mark showmanual: %d пакетов" % len(ex["apt_manual"]))
    if ex.get("listen"):
        out.append("- Слушающие порты: " + ", ".join(str(p) for p in ex["listen"]))
    if ex.get("display_env"):
        out.append("- DISPLAY: %s" % ex["display_env"])
    if ex.get("x11_sockets"):
        out.append("- /tmp/.X11-unix: " + ", ".join(ex["x11_sockets"]))
    if ex.get("dri"):
        out.append("- /dev/dri: " + ", ".join(ex["dri"]))
    if ex.get("docker_server"):
        out.append("- Docker daemon: %s" % ex["docker_server"])
    if ex.get("brew_formulae"):
        out.append("- Homebrew formula: %s" % ex["brew_formulae"])
    if ex.get("screensharing"):
        out.append("- Screen Sharing: %s" % ex["screensharing"])
    for key, name in (("sip", "SIP"), ("gatekeeper", "Gatekeeper"),
                      ("filevault", "FileVault"), ("ard_kickstart", "ARDAgent")):
        if ex.get(key):
            out.append("- %s: %s" % (name, ex[key]))
    if ex.get("tcc"):
        out.append("- TCC: " + "; ".join(ex["tcc"]))
    if ex.get("session_id"):
        out.append("- Сессия: %s" % ex["session_id"])
    if ex.get("admin") not in (None, ""):
        out.append("- Администратор: %s" % ("да" if str(ex["admin"]).lower() == "true" else "нет"))
    return out


def section(inv):
    lines = ["### %s" % inv["label"], ""]
    o = os_line(inv)
    if o:
        lines.append("- ОС: %s" % o)
    img = image_cell(inv)
    if img:
        lines.append("- Образ: `%s`" % img)
    h = hardware_line(inv)
    if h:
        lines.append("- Железо: %s" % h)
    c = counts_line(inv)
    if c:
        lines.append("- Приложения: %s" % c)
    t = tools_line(inv)
    if t:
        lines.append("- Инструменты: %s" % t)
    d = display_line(inv)
    caps = inv.get("capabilities") or []
    if d or caps:
        s = "- Возможности: %s" % ", ".join(caps) if caps else ""
        if d:
            s += ("; " if s else "- ") + "экран %s" % d
        lines.append(s)
    cl = connect_line(inv)
    if cl:
        lines.append("- Подключение: %s" % cl)
    lines.extend(xcode_lines(inv))
    lines.extend(extra_lines(inv))
    errs = inv.get("errors") or []
    if errs:
        lines.append("- Ошибки сбора: %d (errors.txt в артефакте)" % len(errs))
    lines.append("")
    return lines


def play_for(inv):
    label = inv.get("label", "")
    conn = inv.get("connect") or {}
    limits = inv.get("limits") or {}
    max_min = limits.get("job_minutes", 360)

    if family(inv) == "windows":
        return {
            "workflow": "windows-rdp.yml",
            "inputs": {"os": label, "minutes": "60", "tunnel": "tailscale"},
            "secrets": ["RDP_PASSWORD", "TS_AUTHKEY"],
            "connect": "mstsc → tailscale-ip:3389, пользователь rdp",
            "max_minutes": min(max_min, 350),
        }

    if family(inv) == "macos":
        if "vnc-ard" in conn:
            method, note = "vnc-ard", "VNC-клиент → tailscale-ip:5900 (Screen Sharing)"
        elif "ssh" in conn:
            method, note = "ssh", "ssh → tailscale-ip:22"
        else:
            return None
        return {
            "workflow": "play.yml",
            "inputs": {"label": label, "minutes": "60", "method": method},
            "secrets": ["TS_AUTHKEY"],
            "connect": note,
            "max_minutes": max_min,
            "note": "play.yml — отдельный план: поднимает ARD/SSH и отдаёт connect.json",
        }

    if family(inv) == "ubuntu":
        for method, note in (
            ("novnc", "браузер → tailscale-ip:6080/vnc.html"),
            ("vnc", "VNC-клиент → tailscale-ip:5900"),
            ("rdp", "mstsc → tailscale-ip:3389"),
            ("ssh", "ssh → tailscale-ip:22"),
        ):
            if method in conn:
                return {
                    "workflow": "play.yml",
                    "inputs": {"label": label, "minutes": "60", "method": method},
                    "secrets": ["TS_AUTHKEY"],
                    "connect": note,
                    "max_minutes": max_min,
                    "note": "play.yml — отдельный план: Xvfb + VNC/DE, отдаёт connect.json",
                }
    return None


def catalog_entry(inv):
    hw = inv.get("hardware") or {}
    xc = inv.get("xcode")
    e = {
        "label": inv["label"],
        "os": (inv.get("os") or {}).get("name", ""),
        "os_version": (inv.get("os") or {}).get("version", ""),
        "os_build": (inv.get("os") or {}).get("build", ""),
        "arch": (inv.get("runner") or {}).get("arch", ""),
        "cpu": "%s vCPU" % hw["ncpu"] if hw.get("ncpu") else "",
        "cpu_model": hw.get("cpu", ""),
        "ram_gb": hw.get("ram_gb"),
        "disk_gb": {"total": hw.get("disk_total_gb"), "free": hw.get("disk_free_gb")},
        "image": inv.get("image") or {},
        "capabilities": inv.get("capabilities") or [],
        "connect": inv.get("connect") or {},
        "display": inv.get("display") or {},
        "limits": inv.get("limits") or {},
        "apps": (inv.get("counts") or {}).get("apps", 0),
        "xcode": (xc or {}).get("default", "") if xc else "",
        "tools": {k: (inv.get("tools") or {}).get(k, "") for k in
                  ("python3", "node", "go", "rustc", "java", "dotnet", "docker", "swift")},
    }
    play = play_for(inv)
    if play:
        e["play"] = play
    return e


def diff_lines(invs, baseline):
    out = []
    for inv in invs:
        b = baseline.get(inv.get("label"))
        if not b:
            continue
        ch = []
        bi = (b.get("image") or {}).get("version", "")
        ci = (inv.get("image") or {}).get("version", "")
        if bi and ci and bi != ci:
            ch.append("образ %s → %s" % (bi, ci))
        bx = xcode_default(b)
        cx = xcode_default(inv)
        if bx != cx:
            ch.append("Xcode %s → %s" % (bx or "—", cx or "—"))
        for key, name in (("ncpu", "vCPU"), ("ram_gb", "RAM GB")):
            bv = (b.get("hardware") or {}).get(key)
            cv = (inv.get("hardware") or {}).get(key)
            if bv and cv and bv != cv:
                ch.append("%s %s → %s" % (name, bv, cv))
        ba = (b.get("counts") or {}).get("apps") or 0
        ca = (inv.get("counts") or {}).get("apps") or 0
        if ba and ca and abs(ca - ba) > 5:
            ch.append("приложений %d → %d" % (ba, ca))
        if ch:
            out.append("- **%s**: %s" % (inv["label"], "; ".join(ch)))
    return out


def markdown(invs, baseline):
    lines = ["# Инвентаризация GitHub-раннеров", ""]
    if invs:
        lines.append("Собрано: %s · меток: %d" % (time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
                                                  len(invs)))
        lines.append("")
        lines.append("| label | OS | arch | CPU/RAM | apps | GUI | connect | Xcode | image |")
        lines.append("|---|---|---|---|---:|---|---|---|---|")
        for inv in invs:
            lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                cell(inv["label"]),
                cell((inv.get("os") or {}).get("name", "")),
                cell((inv.get("runner") or {}).get("arch", "")),
                cell(vcpu_ram(inv)),
                cell((inv.get("counts") or {}).get("apps", "")),
                cell(gui_cell(inv)),
                cell(connect_cell(inv)),
                cell(xcode_default(inv)),
                cell(image_cell(inv)),
            ))
        lines.append("")
        lines.append("`*` в колонке connect — метод включается штатной командой образа "
                     "(setup в `catalog.json`).")
        lines.append("")

        titles = {"ubuntu": "Ubuntu", "windows": "Windows", "macos": "macOS"}
        for fam in ("ubuntu", "windows", "macos"):
            group = [i for i in invs if family(i) == fam]
            if not group:
                continue
            lines.append("## %s" % titles[fam])
            lines.append("")
            for inv in group:
                lines.extend(section(inv))
        other = [i for i in invs if family(i) not in titles]
        if other:
            lines.append("## Прочее")
            lines.append("")
            for inv in other:
                lines.extend(section(inv))

        lines.append("## Как запустить и подключиться")
        lines.append("")
        lines.append("| label | workflow | входные | секреты | подключение | до, мин |")
        lines.append("|---|---|---|---|---|---:|")
        for inv in invs:
            play = play_for(inv)
            if not play:
                continue
            lines.append("| %s | `%s` | %s | %s | %s | %s |" % (
                cell(inv["label"]), cell(play["workflow"]),
                cell(", ".join("%s=%s" % (k, v) for k, v in play["inputs"].items())),
                cell(", ".join(play["secrets"])),
                cell(play["connect"]), cell(play["max_minutes"])))
        lines.append("")

        if baseline:
            diff = diff_lines(invs, baseline)
            if diff:
                lines.append("## Изменения с прошлым прогоном")
                lines.append("")
                lines.extend(diff)
                lines.append("")
    else:
        lines.append("Данных инвентаризации в артефактах нет.")
        lines.append("")
    lines.append("Полные списки: `apps-all.tsv`, `tools-matrix.tsv`, "
                 "`inventory-all.json`; каталог для страницы — `catalog.json`.")
    return "\n".join(lines) + "\n"


def write_files(out_dir, invs, baseline):
    os.makedirs(out_dir, exist_ok=True)
    md = markdown(invs, baseline)
    with open(os.path.join(out_dir, "inventory.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(md)

    allj = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "count": len(invs), "labels": invs}
    with open(os.path.join(out_dir, "inventory-all.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(allj, fh, ensure_ascii=False, indent=1)

    cat = {"generated_at": allj["generated_at"],
           "entries": [catalog_entry(i) for i in invs]}
    with open(os.path.join(out_dir, "catalog.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(cat, fh, ensure_ascii=False, indent=1)

    def esc(v):
        return " ".join(str(v if v is not None else "").split())

    with open(os.path.join(out_dir, "apps-all.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("label\tsource\tname\tversion\tpath\tpublisher\n")
        for inv in invs:
            for a in inv.get("apps") or []:
                fh.write("\t".join([esc(inv["label"])] + [esc(a.get(k, "")) for k in
                                                          ("source", "name", "version", "path", "publisher")]) + "\n")

    labels = [i["label"] for i in invs]
    tools = sorted({k for i in invs for k in (i.get("tools") or {})})
    with open(os.path.join(out_dir, "tools-matrix.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("tool\t%s\n" % "\t".join(esc(x) for x in labels))
        for t in tools:
            row = [(i.get("tools") or {}).get(t, "") for i in invs]
            fh.write("\t".join([esc(t)] + [esc(x) for x in row]) + "\n")
    return md


def load_baseline(path):
    if not path:
        return {}
    if os.path.isdir(path):
        invs = load_inventories(path)
    else:
        with open(path, encoding="utf-8") as fh:
            j = json.load(fh)
        invs = j.get("labels") if isinstance(j, dict) else j
        invs = invs or []
    return {i["label"]: i for i in invs if isinstance(i, dict) and i.get("label")}


def main():
    ap = argparse.ArgumentParser(description="Сводка инвентаризации раннеров")
    ap.add_argument("src", nargs="?", default="artifacts",
                    help="каталог с артефактами (по умолчанию artifacts)")
    ap.add_argument("--out", default="", help="куда писать файлы отчёта")
    ap.add_argument("--baseline", default="", help="каталог/JSON прошлого прогона")
    args = ap.parse_args()

    invs = load_inventories(args.src)
    baseline = load_baseline(args.baseline)
    md = write_files(args.out, invs, baseline) if args.out else markdown(invs, baseline)
    sys.stdout.write(md)
    print("render: %d меток%s" % (len(invs), ", report → %s" % args.out if args.out else ""),
          file=sys.stderr)


if __name__ == "__main__":
    main()
