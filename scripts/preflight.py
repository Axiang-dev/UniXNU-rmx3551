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
    if "PONG_SHENG_ROOT" not in wf:
        fail(3, "kernel.yml", "no sheng source checkout for QcomRpmh.h")
    else:
        print("  sheng sources fetched for QcomRpmh.h")
    for bad_flag in ("XNU_SOURCE_CORECRYPTO14: '1'", "XNU_PONG_WIFI: '1'", "XNU_PONG_BACKLIGHT: '1'"):
        if bad_flag in wf:
            fail(3, "kernel.yml", f"switch that needs an archive this runner cannot build: {bad_flag}")


def main():
    pass_patches()
    pass_syntax()
    pass_decisions()
    print()
    if failures:
        print(f"{len(failures)} problem(s) would reach the build:")
        for p, where, why in failures:
            print(f"  [pass {p}] {where}: {why}")
        return 1
    print("all three passes clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
