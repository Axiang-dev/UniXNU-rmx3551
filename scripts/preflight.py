#!/usr/bin/env python3
"""Three passes over everything a push can break, before the push.

The last two failed builds were both self-inflicted and both visible without a
compiler: a substitution left "bool ok = return property(...)" in a C file, and the
same block called IOLog from a translation unit that prints with printf.  A build
costs fifteen minutes; these checks cost two seconds.

    python scripts/preflight.py

Exit code 0 means every pass is clean.  Any failure prints the file and the line so
it can be fixed before the build, not after it.
"""
import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
failures = []


def fail(pass_name, where, why):
    failures.append((pass_name, where, why))


def pass_header(n, title):
    print(f"\n=== pass {n}: {title} ===")


# ---------------------------------------------------------------- pass 1: patches
def pass_patches():
    pass_header(1, "patch structure and stray tokens")
    for patch in sorted(ROOT.glob("patches/**/*.patch")):
        lines = patch.read_text(encoding="utf-8", errors="replace").splitlines()
        files = hunks = bad = 0
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                files += 1
                i += 2
                continue
            if line.startswith("@@"):
                m = re.match(r"@@ -(\d+),(\d+) \+(\d+),(\d+) @@", line)
                if not m:
                    fail(1, f"{patch.name}:{i+1}", "unparsable hunk header")
                    i += 1
                    continue
                oc, nc = int(m.group(2)), int(m.group(4))
                i += 1
                o = n = 0
                while i < len(lines) and not lines[i].startswith("@@") and not (
                    lines[i].startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ ")
                ):
                    b = lines[i]
                    if b[:1] in (" ", "-"):
                        o += 1
                    if b[:1] in (" ", "+"):
                        n += 1
                    i += 1
                hunks += 1
                if (o, n) != (oc, nc):
                    bad += 1
                    fail(1, f"{patch.name}:{i}", f"hunk counts say {oc}/{nc}, body is {o}/{n}")
                continue
            i += 1
        print(f"  {patch.name}: {files} files, {hunks} hunks, {bad} bad")
        # tokens that only appear when a substitution went wrong, scoped to the file
        current = ""
        for lineno, text in enumerate(patch.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if text.startswith("+++ "):
                current = text[4:].split("\t")[0].strip()
                continue
            if not text.startswith("+"):
                continue
            if "= return " in text:
                fail(1, f"{patch.name}:{lineno}", "assignment kept the original return: '= return'")
            # pong_goodix.c is C: it prints with printf and has no IOLog declaration.
            if "IOLog(" in text and current.endswith("pong_goodix.c"):
                fail(1, f"{patch.name}:{lineno}", "IOLog in the C touch driver, which uses printf")


# ------------------------------------------------------- pass 2: scripts and yaml
def pass_syntax():
    pass_header(2, "python, shell and workflow syntax")
    for py in sorted(ROOT.glob("scripts/*.py")):
        try:
            ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError as e:
            fail(2, f"{py.name}:{e.lineno}", e.msg or "syntax error")
    print(f"  {len(list(ROOT.glob('scripts/*.py')))} python files parsed")
    for sh in sorted(ROOT.glob("scripts/*.sh")):
        r = subprocess.run(["bash", "-n", str(sh)], capture_output=True, text=True)
        if r.returncode:
            fail(2, sh.name, (r.stderr or "bash -n failed").strip().splitlines()[0])
    print(f"  {len(list(ROOT.glob('scripts/*.sh')))} shell files checked")
    try:
        import yaml
    except ImportError:
        print("  yaml module absent; workflow check skipped")
        return
    for wf in sorted((ROOT / ".github/workflows").glob("*.yml")):
        try:
            yaml.safe_load(wf.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001 - any parse error is a failure
            fail(2, wf.name, str(e).splitlines()[0])
    print(f"  {len(list((ROOT / '.github/workflows').glob('*.yml')))} workflow files parsed")


# ---------------------------------------------------- pass 3: the four decisions
def pass_decisions():
    pass_header(3, "the build decisions that cost us a night")
    power = (ROOT / "scripts/build-pong-power-native.py").read_text(encoding="utf-8")
    if "PongPower.cpp" not in power.split("if container.is_file():")[-1]:
        fail(3, "build-pong-power-native.py", "the no-container branch does not compile PongPower.cpp")
    else:
        print("  power unit builds PongPower.cpp without the audio container")
    # only the tuple the no-container branch actually compiles
    at = power.find("sources=('QcomRpmh.c'")
    branch = power[at:at + 400] if at >= 0 else ""
    for banned in ("PongAudio.cpp", "PongAudioService.cpp"):
        if f"'{banned}'" in branch:
            fail(3, "build-pong-power-native.py", f"{banned} needs the amplifier profile and cannot join the no-container list")
    print("  amp-profile sources stay out of the no-container list")
    if "shared=pong_paths.sheng_root()" not in power:
        fail(3, "build-pong-power-native.py", "shared sheng package is not bound before the compile loop")
    else:
        print("  shared sheng package bound")
    if "source=shared/name" not in power:
        fail(3, "build-pong-power-native.py", "QcomRpmh.c resolves under drivers/PongPower instead of the sheng package")
    else:
        print("  QcomRpmh.c resolves from the sheng package")
    if "'PongBattery.cpp'" not in power:
        fail(3, "build-pong-power-native.py", "PongBattery.cpp missing: pong_battery_usb_online would not link")
    else:
        print("  PongBattery.cpp present for the cable question")
    if "'GeniI2c.c'" not in power:
        fail(3, "build-pong-power-native.py", "GeniI2c.c missing: the USB repeater path links against it")
    else:
        print("  GeniI2c.c present for the repeater transfers")
    if "pong-usb-stubs" not in power:
        fail(3, "build-pong-power-native.py", "no weak stubs for the audio entry points")
    else:
        print("  weak audio stubs present")
    wrapper = (ROOT / "scripts/build-ipados18-pong-macos.py").read_text(encoding="utf-8")
    if "not k.startswith(('XNU_','UNIXNU_'))" in wrapper:
        fail(3, "build-ipados18-pong-macos.py", "the wrapper still discards inherited XNU_ switches")
    else:
        print("  wrapper keeps exported XNU_ switches")
    wf = (ROOT / ".github/workflows/kernel.yml").read_text(encoding="utf-8")
    need = {"XNU_PONG_POWER": "1", "XNU_SOURCE_CORECRYPTO14": "0",
            "XNU_SOURCE_PTHREAD": "0", "XNU_NATIVE_AES": "0"}
    for key, want in need.items():
        m = re.search(rf"{key}: '([^']*)'", wf)
        if not m:
            fail(3, "kernel.yml", f"{key} is not exported")
        elif m.group(1) != want:
            fail(3, "kernel.yml", f"{key}={m.group(1)}, expected {want}")
        else:
            print(f"  {key}={want}")
    # board.toml is where the boot arguments live: finalize-pong-adt.py writes them
    # into the ADT, and the packaging script's own list is legacy duplication.
    board = (ROOT / "board.toml").read_text(encoding="utf-8")
    for needed in ("liuqin_usb=1", "liuqin_usb_smmu=2"):
        if f'"{needed}"' not in board:
            fail(3, "board.toml", f"{needed} is not in kernel_args; the driver will not start")
        else:
            print(f"  board.toml carries {needed}")
    patch = ROOT / "patches/xnu-ipados18/zzzzzzzzzz-rmx3551-usb-debug.patch"
    if not patch.is_file():
        fail(3, "patches", "the USB debug port patch is missing")
    else:
        print(f"  USB debug port patch present ({patch.stat().st_size} bytes)")
    board_toml = (ROOT / "board.toml").read_text(encoding="utf-8")
    if '"liuqin_usb=1"' not in board_toml:
        fail(3, "board.toml", "liuqin_usb=1 is not in kernel_args; the debug port stays off")
    elif '"liuqin_usb_smmu=2"' not in board_toml:
        fail(3, "board.toml", "liuqin_usb_smmu=2 is missing; SID0 bypass remains refused")
    else:
        print("  board.toml starts the USB debug port and SID0 bypass planner")
    if "PONG_SHENG_ROOT" not in wf:
        fail(3, "kernel.yml", "no sheng source checkout for QcomRpmh.h")
    else:
        print("  sheng sources fetched for QcomRpmh.h")
    for bad_flag in ("XNU_SOURCE_CORECRYPTO14: '1'", "XNU_PONG_WIFI: '1'", "XNU_PONG_BACKLIGHT: '1'"):
        if bad_flag in wf:
            fail(3, "kernel.yml", f"switch that needs an archive this runner cannot build: {bad_flag}")
# ------------------------------------------------- pass 4: every symbol has an owner
def pass_symbols():
    pass_header(4, "symbol coverage for the USB entry")
    dev = ROOT / "drivers/PongUsb/PongUsbDevice.h"
    mux = ROOT / "drivers/PongUsb/PongUsbMux.h"
    if not dev.exists():
        print("  driver files not checked out; skipped")
        return
    script = (ROOT / "scripts/build-pong-power-native.py").read_text(encoding="utf-8")
    decls = re.findall(r'extern "C"\s+\w[\w \*]*?\b(pong_\w+)\(', dev.read_text(encoding="utf-8"))
    mux_defs = set()
    if mux.exists():
        mux_defs = set(re.findall(r'extern "C"\s+\w[\w \*]*?\b(pong_usb_mux_\w+)\(', mux.read_text(encoding="utf-8")))
    stubs = set(re.findall(r'weak\)\) \w+ (pong_\w+)\(', script))
    # owners outside this archive, named so the reason is on record
    provided = {"pong_ufs_ready": "NativeUfs archive"}
    if "'PongBattery.cpp'" in script:
        provided["pong_battery_usb_online"] = "PongBattery.cpp"
    mux_tu = "pong-usb-mux.cpp" in script
    for name in sorted(set(decls)):
        if name in provided:
            print(f"  {name}: {provided[name]}")
        elif name in stubs:
            print(f"  {name}: weak stub")
        elif name in mux_defs and mux_tu:
            print(f"  {name}: PongUsbMux.h via its own translation unit")
        elif name in mux_defs:
            fail(4, "PongUsbDevice.h", f"{name} is defined in PongUsbMux.h but nothing compiles that header")
        else:
            fail(4, "PongUsbDevice.h", f"{name} is declared and has no owner in this archive")


# ------------------------------------- pass 5: the source list actually resolves
def pass_sources():
    pass_header(5, "source list, late init and generated units")
    script = (ROOT / "scripts/build-pong-power-native.py").read_text(encoding="utf-8")
    at = script.find("sources=('QcomRpmh.c'")
    if at < 0:
        fail(5, "build-pong-power-native.py", "no-container source tuple not found")
        return
    tail = script[at:at + 500]
    names = re.findall(r"'([\w.]+)'", tail)
    print(f"  {len(names)} sources: {', '.join(names[:6])}{' ...' if len(names) > 6 else ''}")
    for unit in ("str(mux)", "str(stub)"):
        if unit not in tail:
            fail(5, "build-pong-power-native.py", f"{unit} is not in the source tuple")
        else:
            print(f"  {unit} in the tuple")
    if "IOPlatformExpert.h" not in script:
        fail(5, "build-pong-power-native.py", "mux unit does not include IOPlatformExpert.h; the attach/start upcast will not compile")
    else:
        print("  mux unit includes IOPlatformExpert.h")
    if "mux.write_text" not in script:
        fail(5, "build-pong-power-native.py", "the mux translation unit is never written")
    else:
        print("  mux translation unit generated")
    if "'-I'+str(ROOT/'drivers/PongUsb')" not in script:
        fail(5, "build-pong-power-native.py", "PongUsb headers are not on the include path")
    else:
        print("  PongUsb headers on the include path")
    for name, sym in (("PongBattery.cpp", "PongBatteryStaticInit"), ("PongBacklight.cpp", "PongBacklightStaticInit")):
        if f"name=='{name}'" not in script or sym not in script:
            fail(5, "build-pong-power-native.py", f"{name} needs the {sym} late-init rename")
        else:
            print(f"  {name}: late init via {sym}")
    for banned in ("PongAudio.cpp", "PongAudioService.cpp"):
        if f"'{banned}'" in tail:
            fail(5, "build-pong-power-native.py", f"{banned} needs the amplifier profile")
def main():
    pass_patches()
    pass_syntax()
    pass_decisions()
    pass_symbols()
    pass_sources()
    print()
    if failures:
        print(f"{len(failures)} problem(s) would reach the build:")
        for p, where, why in failures:
            print(f"  [pass {p}] {where}: {why}")
        return 1
    print("all five passes clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
