#!/usr/bin/env python3
"""Keep Apple's CPU driver out of the boot path of a prelinked kernel.

`emit_prelink.py` pulls `com.apple.driver.AppleARMPlatform` in because apfs
depends on `com.apple.driver.AppleARMWatchdogTimer`, which depends on it.  That
kext also carries the `AppleARMCPU` personality:

    IOClass         AppleARMCPU
    IOProviderClass IOPlatformDevice
    IONameMatch     cpu

`IODTPlatformExpert` publishes one IOPlatformDevice nub per `/cpus` child, so
that personality attaches to cpu0..cpuN and runs Apple's own
`_validateConfiguration()`.  It expects Apple's ADT dialect (`cpu-id`,
`interrupts`, `/cpus/max_cpus`) and panics with "CPU configuration in device
tree is invalid" on a board whose CPU nodes come from a Qualcomm DTS.

On this platform the CPU driver is UniXNU's `ArmCpu`, linked into the kernel and
started from `ArmDTPlatform::configure` against `IOCPU` nubs.  Apple's driver is
not wanted, but the kext itself must stay: apfs binds against symbols that live
in it.  Renaming the match string disables the personality without touching
anything else.  The replacement is the same length, so the XML blob and every
offset in `__PRELINK_INFO` stay put.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

PERSONALITY = b'<key>AppleARMCPU</key>'
MATCH = b'IONameMatch</key><string>cpu</string>'
DISABLED = b'IONameMatch</key><string>xpu</string>'


def segment(blob: bytes, name: bytes):
    if struct.unpack_from('<I', blob, 0)[0] != 0xFEEDFACF:
        raise SystemExit('not a thin little-endian arm64 Mach-O')
    count = struct.unpack_from('<I', blob, 16)[0]
    at = 32
    for _ in range(count):
        cmd, size = struct.unpack_from('<II', blob, at)
        if cmd == 0x19:
            raw = blob[at + 8:at + 24].rstrip(b'\0')
            va, vsize, offset, fsize = struct.unpack_from('<QQQQ', blob, at + 24)
            if raw == name:
                return offset, fsize
        at += size
    raise SystemExit(f'no {name.decode()} segment')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kernel', type=Path, help='prelinked kernel.macho')
    parser.add_argument('--check', action='store_true', help='report without writing')
    args = parser.parse_args()

    blob = bytearray(args.kernel.read_bytes())
    original_size = len(blob)
    offset, size = segment(blob, b'__PRELINK_INFO')
    info = bytes(blob[offset:offset + size])

    at = info.find(PERSONALITY)
    if at < 0:
        print('AppleARMCPU personality absent; nothing to do')
        return 0
    match = info.find(MATCH, at, at + 512)
    if match < 0:
        if info.find(DISABLED, at, at + 512) >= 0:
            print('AppleARMCPU personality already disabled')
            return 0
        raise SystemExit('AppleARMCPU personality found but its IONameMatch is not "cpu"')

    blob[offset + match:offset + match + len(MATCH)] = DISABLED
    if len(blob) != original_size:
        raise SystemExit('edit changed the file size')

    if args.check:
        print(f'would disable AppleARMCPU at __PRELINK_INFO+{match:#x}')
        return 0
    args.kernel.write_bytes(blob)
    print(f'AppleARMCPU personality disabled in {args.kernel} (__PRELINK_INFO+{match:#x})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
