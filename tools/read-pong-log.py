#!/usr/bin/env python3
"""Read the boot log PongBootLog keeps in the userdata tail.

The kernel copies its 4 MiB ramoops mirror (12-byte persistent_ram header +
2 MiB console ring + 2 MiB diagnostic zone) to the first 1 MiB boundary past the
flashed image, every ten seconds, with a 4 KiB header written last. This pulls
that region out of a recovery with root adb and prints the text.

Two steps, because adb wants small numbers:

    python read-pong-log.py plan --serial <device>  # prints the dd command
    adb -s <device> shell <that command> > ponglog-region.bin
    python read-pong-log.py decode ponglog-region.bin [--out log.txt]

`plan` reads the live SHNGROOT header through adb, so the offset always matches
what is flashed; `decode` never touches the device.
"""
import argparse
import hashlib
import struct
import subprocess
import sys
import zlib

MIB = 1 << 20
HEADER_BYTES = 4096
MIRROR_BYTES = 4 * MIB
CONSOLE_BYTES = 2 * MIB
CONSOLE_HEADER = 12
RING_MAGIC = 0x43474244  # "DBGC"


def adb(serial, *args):
    return subprocess.run(['adb', '-s', serial] + list(args), capture_output=True)


def shngroot_header(serial):
    out = adb(serial, 'shell', 'dd if=/dev/block/by-name/userdata bs=4096 count=1 2>/dev/null').stdout
    if len(out) < 4096 or out[:8] != b'SHNGROOT':
        raise SystemExit('userdata does not start with a SHNGROOT directory; '
                         'is the device booted into recovery with adb?')
    version, count = struct.unpack_from('<II', out, 8)
    image_bytes, = struct.unpack_from('<Q', out, 16)
    windows = []
    for index in range(count):
        entry = out[24 + 128 * index: 24 + 128 * (index + 1)]
        name = entry[:32].split(b'\0')[0].decode('ascii', 'replace')
        offset, size = struct.unpack_from('<QQ', entry, 32)
        windows.append((name, offset, size))
    digest_ok = hashlib.sha256(out[:4064]).digest() == out[4064:4096]
    return version, image_bytes, windows, digest_ok


def plan(serial):
    version, image_bytes, windows, digest_ok = shngroot_header(serial)
    region = (image_bytes + MIB - 1) // MIB * MIB
    blocks = (HEADER_BYTES + MIRROR_BYTES) // 4096
    print(f'SHNGROOT v{version}, image {image_bytes} bytes, digest {"ok" if digest_ok else "BAD"}')
    for name, offset, size in windows:
        print(f'  {name:9} offset {offset:>13} size {size:>13}')
    print(f'log region at {region} bytes = block {region // 4096}, {blocks} blocks')
    print('\nrun this, then decode the file it writes:')
    print(f'  adb -s {serial} shell "dd if=/dev/block/by-name/userdata bs=4096 skip={region // 4096} '
          f'count={blocks} 2>/dev/null" > ponglog-region.bin')
    print(f'  python {sys.argv[0]} decode ponglog-region.bin')


def ring_text(zone, label, out):
    if len(zone) < CONSOLE_HEADER:
        out.append(f'--- {label}: short zone ---')
        return
    sig, start, size = struct.unpack_from('<III', zone, 0)
    body = zone[CONSOLE_HEADER:]
    if sig != RING_MAGIC:
        out.append(f'--- {label}: no ring header (sig {sig:#x}) ---')
        return
    capacity = len(body)
    size = min(size, capacity)
    start %= capacity
    if start + size <= capacity:
        segments = [(start, start + size)]
    else:
        segments = [(start, capacity), (0, size - (capacity - start))]
    out.append(f'--- {label}: {size} bytes, ring start {start}, '
               f'{"wrapped" if len(segments) > 1 else "linear"} ---')
    for begin, end in segments:
        out.append(body[begin:end].decode('utf-8', 'replace'))


def decode(path, output):
    blob = path.read_bytes()
    if len(blob) < HEADER_BYTES + CONSOLE_BYTES:
        raise SystemExit(f'{path}: {len(blob)} bytes; expected at least '
                         f'{HEADER_BYTES + CONSOLE_BYTES}')
    magic = blob[:8]
    lines = []
    if magic == b'PBLOG001':
        mirror_bytes, sequence, status, crc = struct.unpack_from('<IIII', blob, 8)
        physical, = struct.unpack_from('<Q', blob, 24)
        tick, ring_start, ring_size = struct.unpack_from('<III', blob, 32)
        body = blob[HEADER_BYTES:HEADER_BYTES + mirror_bytes]
        if crc:
            ok = (zlib.crc32(body) & 0xFFFFFFFF) == crc
            verdict = 'ok' if ok else 'MISMATCH'
        else:
            verdict = 'not recorded'
        lines.append(f'header: sequence {sequence} (status {status}), tick {tick}, '
                     f'ring {ring_start}+{ring_size}, crc {verdict}')
        lines.append(f'        mirror at {physical:#x}, {mirror_bytes} bytes')
        if status != 1:
            lines.append('warning: status is not "complete"; this snapshot may be torn')
    else:
        lines.append(f'header: no PBLOG001 magic ({magic!r}); treating the file as a raw mirror')
        body = blob
    lines.append('')
    ring_text(body[:CONSOLE_BYTES], 'console', lines)
    if len(body) >= 2 * CONSOLE_BYTES:
        ring_text(body[CONSOLE_BYTES:2 * CONSOLE_BYTES], 'diagnostic', lines)
    text = '\n'.join(lines) + '\n'
    if output:
        output.write_text(text, encoding='utf-8')
        print(f'{len(text)} bytes of text written to {output}')
    else:
        sys.stdout.write(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    plan_parser = sub.add_parser('plan', help='print the dd command for the region the kernel uses')
    plan_parser.add_argument('--serial', required=True,
                             help='adb serial; every device operation must target it explicitly')
    dec = sub.add_parser('decode', help='decode a pulled region')
    dec.add_argument('region')
    dec.add_argument('--out')
    args = parser.parse_args()
    if args.command == 'plan':
        plan(args.serial)
    else:
        from pathlib import Path
        decode(Path(args.region), Path(args.out) if args.out else None)


if __name__ == '__main__':
    main()
