#!/usr/bin/env python3
"""Fast passes over everything a push can break, before the push.

The last two failed builds were both self-inflicted and both visible without a
compiler: a substitution left "bool ok = return property(...)" in a C file, and the
same block called IOLog from a translation unit that prints with printf.  A build
costs fifteen minutes; these checks cost two seconds.

    python scripts/preflight.py

Exit code 0 means every pass is clean.  Any failure prints the file and the line so
it can be fixed before the build, not after it.
"""
import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
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


def run_shell_syntax(source):
    """Check normalized shell text without relying on WSL stdin interop."""
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", suffix=".sh", delete=False
    ) as tree:
        tree.write(source)
        temp_path = Path(tree.name)
    try:
        if os.name == "nt" and (wsl := shutil.which("wsl.exe")):
            translated = subprocess.run(
                [wsl, "--exec", "/usr/bin/wslpath", "-a", "-u", str(temp_path)],
                capture_output=True,
                text=True,
            )
            if translated.returncode or not translated.stdout.strip():
                raise RuntimeError(
                    (translated.stderr or "wslpath did not return a Linux path").strip()
                )
            command = [wsl, "--exec", "/bin/bash", "-n", translated.stdout.strip()]
        else:
            bash = shutil.which("bash")
            if not bash:
                raise FileNotFoundError("bash was not found for shell syntax checking")
            command = [bash, "-n", str(temp_path)]
        return subprocess.run(command, capture_output=True, text=True)
    finally:
        temp_path.unlink(missing_ok=True)


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
        source = sh.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
        try:
            r = run_shell_syntax(source)
        except FileNotFoundError as exc:
            fail(2, sh.name, str(exc))
            continue
        except RuntimeError as exc:
            fail(2, sh.name, str(exc))
            continue
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
    # board.toml is the source of truth for stable runtime arguments. Read the
    # structured values instead of blessing one historical CPU count or USB
    # state: the previous five-core attempt shipped cpus=5 with a four-node ADT
    # because these checks were hard-coded.
    board = (ROOT / "board.toml").read_text(encoding="utf-8")
    try:
        board_data = tomllib.loads(board)
    except tomllib.TOMLDecodeError as error:
        fail(3, "board.toml", f"TOML does not parse: {error}")
        board_data = {}
    kernel_args = board_data.get("payload", {}).get("kernel_args", [])
    if not isinstance(kernel_args, list) or not all(isinstance(arg, str) for arg in kernel_args):
        fail(3, "board.toml", "payload.kernel_args must be a string list")
        kernel_args = []
    arg_values = {}
    for arg in kernel_args:
        if "=" in arg:
            key, value = arg.split("=", 1)
            arg_values[key] = value
    for needed in (
        "pong_touch=1",
        "pong_s3910=4",
        "liuqin_usb_smmu=2",
        "liuqin_usb_dma=0x80000000,0x10000000000",
    ):
        if f'"{needed}"' not in board:
            fail(3, "board.toml", f"{needed} is not in kernel_args; the driver will not start")
        else:
            print(f"  board.toml carries {needed}")
    cpu_selectors = {name: value for name, value in arg_values.items()
                     if name in ("cpus", "cpumask")}
    if len(cpu_selectors) != 1:
        fail(3, "board.toml", "payload.kernel_args must carry exactly one of cpus= or cpumask=")
        cpu_count = 5
    elif "cpus" in cpu_selectors:
        cpu_text = cpu_selectors["cpus"]
        if not cpu_text.isdigit() or not 1 <= int(cpu_text) <= 8:
            fail(3, "board.toml", f"cpus={cpu_text!r} is not an integer from 1 through 8")
            cpu_count = 5
        else:
            cpu_count = int(cpu_text)
            print(f"  board.toml carries cpus={cpu_count}")
    else:
        cpu_mask_text = cpu_selectors["cpumask"]
        try:
            cpu_mask = int(cpu_mask_text, 0)
        except ValueError:
            fail(3, "board.toml", f"cpumask={cpu_mask_text!r} is not an integer")
            cpu_mask = 0
        if cpu_mask <= 0 or cpu_mask > 0xff or cpu_mask & (cpu_mask + 1):
            fail(3, "board.toml", f"cpumask={cpu_mask_text!r} must select a contiguous set of 1 through 8 CPUs")
            cpu_count = 5
        else:
            cpu_count = cpu_mask.bit_count()
            print(f"  board.toml carries cpumask={cpu_mask_text} ({cpu_count} CPUs)")
    usb_state = arg_values.get("liuqin_usb")
    if usb_state not in ("0", "1"):
        fail(3, "board.toml", f"liuqin_usb={usb_state!r}; expected 0 or 1")
    else:
        print(f"  board.toml carries liuqin_usb={usb_state}")
    patch = ROOT / "patches/xnu-ipados18/zzzzzzzzzz-rmx3551-usb-debug.patch"
    if not patch.is_file():
        fail(3, "patches", "the USB debug port patch is missing")
    else:
        print(f"  USB debug port patch present ({patch.stat().st_size} bytes)")
    if "PONG_SHENG_ROOT" not in wf:
        fail(3, "kernel.yml", "no sheng source checkout for QcomRpmh.h")
    else:
        print("  sheng sources fetched for QcomRpmh.h")
    build_step = wf.find("- name: Build the boot payload volume")
    finalize_step = wf.find("- name: Finalize the board ADT from the compiled hardware tree")
    verify_step = wf.find("- name: Verify the finalized ADT before it can be uploaded")
    if min(build_step, finalize_step, verify_step) < 0 or not (build_step < finalize_step < verify_step):
        fail(3, "kernel.yml", "payload -> finalize ADT -> verify ADT is not the step order")
    else:
        print("  payload is finalized from hardware.dtb and verified before upload")
    finalize_invocation = wf[finalize_step:verify_step] if min(finalize_step, verify_step) >= 0 else ""
    verify_invocation = wf[verify_step:] if verify_step >= 0 else ""
    expected_cpus_flag = f"--cpus {cpu_count}"
    if "--ufs-probe" not in finalize_invocation:
        fail(3, "kernel.yml", "the finalized ADT does not publish the UFS probe nub")
    elif expected_cpus_flag not in finalize_invocation:
        fail(3, "kernel.yml", f"the finalized ADT does not use board.toml's {expected_cpus_flag}")
    elif ("scripts/verify-pong-adt.py" not in verify_invocation
            or expected_cpus_flag not in verify_invocation
            or "--trust-cache" not in verify_invocation):
        fail(3, "kernel.yml", f"the finalized ADT is not verified as {expected_cpus_flag} with trust-cache")
    elif not (ROOT / "scripts/verify-pong-adt.py").is_file():
        fail(3, "scripts", "verify-pong-adt.py is missing")
    else:
        print(f"  ADT finalize and verify both use board.toml's {expected_cpus_flag}")
        print("  touch resources and trust-cache handoff are checked at ADT property level")
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


# --------------------------------------- pass 5: hardware-facing host regressions
def pass_host_tests():
    pass_header(5, "hardware-facing host regressions")
    tests = (
        ROOT / "tests/test_rmx3551_usb_startup_order.py",
        ROOT / "tests/test_rmx3551_effective_boot_args.py",
    )
    for test in tests:
        if not test.is_file():
            fail(5, test.name, "hardware-facing regression test is missing")
            continue
        r = subprocess.run([sys.executable, "-B", str(test)], capture_output=True, text=True)
        if r.returncode:
            detail = (r.stderr or r.stdout or "test failed").strip().splitlines()[-1]
            fail(5, test.name, detail)
        else:
            print(f"  {(r.stdout or 'passed').strip()}")


# ------------------------------------- pass 6: the source list actually resolves
def pass_sources():
    pass_header(6, "source list, late init and generated units")
    script = (ROOT / "scripts/build-pong-power-native.py").read_text(encoding="utf-8")
    at = script.find("sources=('QcomRpmh.c'")
    if at < 0:
        fail(6, "build-pong-power-native.py", "no-container source tuple not found")
        return
    tail = script[at:at + 500]
    names = re.findall(r"'([\w.]+)'", tail)
    print(f"  {len(names)} sources: {', '.join(names[:6])}{' ...' if len(names) > 6 else ''}")
    for unit in ("str(mux)", "str(stub)"):
        if unit not in tail:
            fail(6, "build-pong-power-native.py", f"{unit} is not in the source tuple")
        else:
            print(f"  {unit} in the tuple")
    if "IOPlatformExpert.h" not in script:
        fail(6, "build-pong-power-native.py", "mux unit does not include IOPlatformExpert.h; the attach/start upcast will not compile")
    else:
        print("  mux unit includes IOPlatformExpert.h")
    if "mux.write_text" not in script:
        fail(6, "build-pong-power-native.py", "the mux translation unit is never written")
    else:
        print("  mux translation unit generated")
    if "'-I'+str(ROOT/'drivers/PongUsb')" not in script:
        fail(6, "build-pong-power-native.py", "PongUsb headers are not on the include path")
    else:
        print("  PongUsb headers on the include path")
    for name, sym in (("PongBattery.cpp", "PongBatteryStaticInit"), ("PongBacklight.cpp", "PongBacklightStaticInit")):
        if f"name=='{name}'" not in script or sym not in script:
            fail(6, "build-pong-power-native.py", f"{name} needs the {sym} late-init rename")
        else:
            print(f"  {name}: late init via {sym}")
    for banned in ("PongAudio.cpp", "PongAudioService.cpp"):
        if f"'{banned}'" in tail:
            fail(6, "build-pong-power-native.py", f"{banned} needs the amplifier profile")

def main():
    pass_patches()
    pass_syntax()
    pass_decisions()
    pass_symbols()
    pass_host_tests()
    pass_sources()
    print()
    if failures:
        print(f"{len(failures)} problem(s) would reach the build:")
        for p, where, why in failures:
            print(f"  [pass {p}] {where}: {why}")
        return 1
    print("all six passes clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
