#!/usr/bin/env python3
"""Bundle the original Apple trust-cache modules for the boot payload.

The payload carries the trust caches the original Apple security components
verify code against (docs/concepts/security.md): DarwinBoot copies the bundle
into the kernel window and hands its address to the kernel through
/chosen/memory-map/TrustCache.  This build takes the IPSW's own trust-cache
IM4P files unmodified -- StaticTrustCache and Cryptex1,SystemTrustCache -- and
writes them in the bundle format DarwinBoot's ValidTrustCaches accepts:

    <u32 module count> <u32 start> ...   header
    <u32 version=2> <16s uuid> <u32 entries> <entries * (20s cdhash + 4B flags)>

An optional --owner module (a version-2 module of our own CDHashes) may be
appended; it is signed by nothing, the loader only checks the structure.
"""
import argparse
import hashlib
import struct
import sys
from pathlib import Path


def der(data, at):
    if at + 2 > len(data):
        raise SystemExit('truncated DER')
    tag, size = data[at], data[at + 1]
    at += 2
    if size & 0x80:
        count = size & 0x7F
        if not 0 < count <= 4 or at + count > len(data):
            raise SystemExit('invalid DER length')
        size = int.from_bytes(data[at:at + count], 'big')
        at += count
    if at + size > len(data):
        raise SystemExit('DER element exceeds the input')
    return tag, data[at:at + size], at + size


def im4p_payload(path):
    """The data field of one IM4P: tag 0x30, fields IM4P/type/description/data."""
    raw = path.read_bytes()
    tag, sequence, end = der(raw, 0)
    if tag != 0x30 or end != len(raw):
        raise SystemExit(f'{path}: not a single DER sequence')
    fields, cursor = [], 0
    while cursor < len(sequence):
        kind, payload, cursor = der(sequence, cursor)
        fields.append((kind, payload))
    if (len(fields) != 4 or fields[0][1] != b'IM4P' or
            any(kind != 0x16 for kind, _ in fields[:3]) or fields[3][0] != 0x04):
        raise SystemExit(f'{path}: not the IM4P shape of a trust cache')
    return fields[3][1]


def check_module(name, module):
    if len(module) < 24 or struct.unpack_from('<I', module)[0] != 2:
        raise SystemExit(f'{name}: not a version-2 trust module')
    entries = struct.unpack_from('<I', module, 20)[0]
    if len(module) != 24 + entries * 24:
        raise SystemExit(f'{name}: {len(module)} bytes do not hold {entries} entries')
    for entry in range(entries):
        at = 24 + entry * 24
        if not 1 <= module[at + 20] <= 4:
            raise SystemExit(f'{name}: entry {entry} has no valid flag')
        if entry and module[at - 24:at - 4] >= module[at:at + 20]:
            raise SystemExit(f'{name}: entries are not in strictly ascending order')
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='bundle to write')
    parser.add_argument('modules', nargs='+', type=Path,
                        help='IM4P trust-cache components, in bundle order')
    args = parser.parse_args()
    modules = []
    for path in args.modules:
        module = check_module(path.name, im4p_payload(path))
        modules.append(module)
        print(f'{path.name}: module {len(module)} bytes, '
              f'{struct.unpack_from("<I", module, 20)[0]} entries', file=sys.stderr)
    # Bundle order must not depend on how the shell expanded a glob: the payload
    # step records the bundle digest in board.toml.  Smallest module first is
    # also the order the reference bundle uses (static trust cache, then system).
    modules.sort(key=len)
    cursor, starts = 4 + 4 * len(modules), []
    for module in modules:
        starts.append(cursor)
        cursor += len(module)
    bundle = struct.pack(f'<{1 + len(modules)}I', len(modules), *starts) + b''.join(modules)
    # The same structural checks DarwinBoot applies before it hands the bundle over.
    count = struct.unpack_from('<I', bundle)[0]
    assert 0 < count <= 128
    for index in range(count):
        start = struct.unpack_from('<I', bundle, 4 + 4 * index)[0]
        end = struct.unpack_from('<I', bundle, 8 + 4 * index)[0] if index + 1 < count else len(bundle)
        assert start >= 4 + 4 * count and not start & 3 and end <= len(bundle) and end - start >= 24
        assert struct.unpack_from('<I', bundle, start)[0] == 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(bundle)
    print(f'{args.output}: {len(bundle)} bytes, sha256 {hashlib.sha256(bundle).hexdigest()}')


if __name__ == '__main__':
    main()
