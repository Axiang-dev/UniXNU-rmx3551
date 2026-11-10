#!/usr/bin/env python3
"""Extract the S3910 protocol header from the XNU patch and exercise it."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "patches/xnu-ipados18/0001-pong-darwin24.patch"
TARGET = "bsd/dev/pong_s3910_protocol.h"
TEST = ROOT / "tests/rmx3551_s3910_protocol_host_test.c"


def validate_new_file_hunk_counts(patch: Path) -> None:
    lines = patch.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        match = re.fullmatch(r"@@ -0,0 \+1,(\d+) @@", line)
        if not match:
            continue
        expected = int(match.group(1))
        actual = 0
        for added in lines[index + 1 :]:
            if added.startswith("diff --git "):
                break
            if added.startswith("+") and not added.startswith("+++"):
                actual += 1
        if actual != expected:
            target = next((value[6:] for value in reversed(lines[max(0, index - 5) : index]) if value.startswith("+++ b/")), "unknown")
            raise SystemExit(f"{target}: new-file hunk declares {expected} lines but contains {actual}")


def extract_new_file(patch: Path, target: str) -> str:
    lines = patch.read_text(encoding="utf-8").splitlines()
    marker = f"diff --git a/{target} b/{target}"
    try:
        start = lines.index(marker)
    except ValueError as error:
        raise SystemExit(f"patch does not create {target}") from error
    added: list[str] = []
    in_body = False
    for line in lines[start + 1 :]:
        if line.startswith("diff --git "):
            break
        if line == f"+++ b/{target}":
            in_body = True
            continue
        if in_body:
            if line.startswith("+"):
                added.append(line[1:])
            elif line.startswith("\\ No newline"):
                continue
            elif line.startswith("@@") or line.startswith("new file mode") or line.startswith("index "):
                continue
            elif line:
                raise SystemExit(f"unexpected patch line for {target}: {line!r}")
    if not added:
        raise SystemExit(f"patch has no content for {target}")
    return "\n".join(added) + "\n"


def find_windows_vcvars() -> Path:
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
    if not vswhere.is_file():
        raise SystemExit("Visual Studio vswhere.exe was not found")
    install = subprocess.check_output(
        [str(vswhere), "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
        text=True,
    ).strip()
    vcvars = Path(install) / "VC/Auxiliary/Build/vcvars64.bat"
    if not vcvars.is_file():
        raise SystemExit("Visual Studio C++ build tools were not found")
    return vcvars


def compile_and_run(source: Path, include: Path, output: Path, temp: Path) -> None:
    if os.name == "nt":
        vcvars = find_windows_vcvars()
        command = subprocess.list2cmdline([
            "cl", "/nologo", "/std:c11", "/W4", "/WX", f"/I{include}", str(source),
            f"/Fe:{output}",
        ])
        batch = temp / "build-test.cmd"
        batch.write_text(f'@call "{vcvars}" >nul\r\n@{command}\r\n', encoding="utf-8")
        subprocess.run([str(batch)], cwd=temp, check=True)
        subprocess.run([str(output)], check=True)
        return
    compiler = shutil.which("clang") or shutil.which("cc") or shutil.which("gcc")
    if not compiler:
        raise SystemExit("no C compiler found")
    subprocess.run([
        compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", f"-I{include}", str(source), "-o", str(output)
    ], check=True)
    subprocess.run([str(output)], check=True)


def main() -> None:
    validate_new_file_hunk_counts(PATCH)
    header = extract_new_file(PATCH, TARGET)
    with tempfile.TemporaryDirectory(prefix="rmx3551-s3910-", ignore_cleanup_errors=True) as directory:
        temp = Path(directory)
        (temp / "pong_s3910_protocol.h").write_text(header, encoding="utf-8", newline="\n")
        exe = temp / ("test.exe" if os.name == "nt" else "test")
        compile_and_run(TEST.resolve(), temp, exe.resolve(), temp)


if __name__ == "__main__":
    main()
