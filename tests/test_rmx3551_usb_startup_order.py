#!/usr/bin/env python3
"""Guard the RMX3551 USB debug port against an early-boot regression."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "patches/xnu-ipados18/zzzzzzzzzz-rmx3551-usb-debug.patch"
BSD_INIT = "bsd/kern/bsd_init.c"
USB_SOURCE = "bsd/dev/liuqin_usb_debug.c"


def fail(message: str) -> None:
    raise SystemExit(message)


def patch_hunks(target: str) -> list[tuple[str, str]]:
    """Return (header, post-image text) for every hunk touching target."""
    lines = PATCH.read_text(encoding="utf-8").splitlines()
    marker = f"diff --git a/{target} b/{target}"
    try:
        start = lines.index(marker)
    except ValueError:
        fail(f"USB patch does not touch {target}")

    hunks: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    for line in lines[start + 1 :]:
        if line.startswith("diff --git "):
            break
        if line.startswith("@@"):
            current = []
            hunks.append((line, current))
            continue
        if current is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            current.append(line[1:])
        elif line.startswith(" "):
            current.append(line[1:])
        elif line.startswith("\\ No newline"):
            continue
    return [(header, "\n".join(body)) for header, body in hunks]


def source_for_new_file(target: str) -> str:
    hunks = patch_hunks(target)
    if len(hunks) != 1 or "-0,0 +1," not in hunks[0][0]:
        fail(f"{target} is not represented as one new-file hunk")
    return hunks[0][1] + "\n"


def function_body(source: str, name: str) -> str:
    match = re.search(
        rf"(?m)^(?:static\s+)?void\s*\n{re.escape(name)}\s*\([^)]*\)\s*\n?\s*\{{",
        source,
    )
    if not match:
        fail(f"function {name} not found")
    opening = source.find("{", match.start())
    depth = 0
    for index in range(opening, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[opening + 1 : index]
    fail(f"unterminated function {name}")


def main() -> None:
    bsd_hunks = patch_hunks(BSD_INIT)
    call_hunks = [h for h in bsd_hunks if "liuqin_usb_debug_start" in h[1]]
    if len(call_hunks) != 1:
        fail(f"expected one USB start hook in {BSD_INIT}, found {len(call_hunks)}")
    header, body = call_hunks[0]
    if "bsd_autoconf(void)" not in header:
        fail("USB start hook is not anchored to bsd_autoconf")
    if "bsdinit_task" in header or "vm_init_before_launchd" in body:
        fail("USB start hook regressed into bsdinit_task")
    if "#if defined(ARM64_BOARD_CONFIG_PONG)" not in body:
        fail("USB start hook is not board guarded")
    if "if (result == KERN_SUCCESS)" not in body:
        fail("USB start hook does not require successful IOKit initialization")

    source = source_for_new_file(USB_SOURCE)
    init = function_body(source, "liuqin_usb_debug_init")
    worker = function_body(source, "liuqin_usb_debug_worker")
    start = function_body(source, "liuqin_usb_debug_start")

    if "liuqin_io_map(" not in init or "kmem_alloc_contig(" not in init:
        fail("MMIO mapping or DMA allocation left the post-IOKit worker path")
    if not re.search(r"kernel_thread_start\s*\(\s*liuqin_usb_debug_worker\b", start):
        fail("start routine does not create the USB worker thread")
    if "thread_deallocate(thread)" not in start:
        fail("start routine leaks the created kernel thread")
    if "liuqin_io_map(" in start or "kmem_alloc" in start:
        fail("start routine performs MMIO mapping or DMA allocation on the boot thread")
    if "liuqin_usb_debug_init();" not in worker:
        fail("worker does not enter the USB initialization routine")
    if "thread_terminate(current_thread())" not in worker:
        fail("worker does not terminate itself after initialization")

    print("rmx3551 USB startup ordering test passed")


if __name__ == "__main__":
    main()