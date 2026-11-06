#!/usr/bin/env python3
"""Give the root volume the dyld shared cache launchd looks for.

The kernel mounts the OS window as the read-only root.  That volume carries no
dyld cache at all (verified: not one `dyld_v1` in the whole image), while the
caches live in the SystemOS cryptex.  launchd resolves the cache through the
root's default path -- /System/Library/Caches/com.apple.dyld/ -- and strips the
DYLD_* environment the kernel hands it, so the cryptex copy is unreachable and
launchd_cache_loader aborts with -67062 (errSecCSUnsigned) before init runs.

This step rebuilds the OS window:

  1. the cryptex is scanned first, so the new volume is sized from the real
     cache size instead of a guess (a short volume fails 30 minutes into the
     copy with ENOSPC),
  2. hdiutil creates an APFS volume of exactly that size and ditto copies the
     original root into it (signatures, xattrs and ACLs preserved),
  3. the cryptex's dyld_shared_cache* files are copied to
     /System/Library/Caches/com.apple.dyld/ on the new root,
  4. the result is converted to the raw image the layout consumes and its
     volume superblock is retagged with the original UUID *and* name -- the
     kernel's root_match_volume_uuid is a compile-time constant and XNU selects
     the root IOMedia by that UUID, so the copy has to answer to it.

Every step fails loudly rather than producing an image that would not boot.
"""
import argparse
import hashlib
import json
import os
import plistlib
import struct
import subprocess
import sys
import uuid
from pathlib import Path

MIB = 1 << 20

# dyld opens the caches themselves and their numbered subcaches.  The
# companion files are for symbolication tools; they are gigabytes, they are
# never read at boot, and every one of them makes the flashed image bigger.
SKIP_SUFFIXES = ('.symbols', '.map', '.json', '.list', '.txt')

# Name the rebuilt volume wears while it is being filled; retag_volume() writes
# the original name into the superblock once the original is detached.
STAGING_NAME = 'RMXRootRebuild'


def run(argv, **kwargs):
    print('+', ' '.join(str(a) for a in argv), file=sys.stderr)
    result = subprocess.run([str(a) for a in argv], capture_output=True, **kwargs)
    if result.returncode:
        # ditto over a system volume can run for half an hour before it hits a
        # single directory it may not read; without its stderr the failure looks
        # like a timeout.
        for stream in (result.stdout, result.stderr):
            text = stream.decode('utf-8', 'replace').strip()
            if text:
                print(text[-4000:], file=sys.stderr)
        raise SystemExit(f'{argv[0]} failed with exit status {result.returncode}')
    return result


def attach(image, readwrite=False):
    argv = ['hdiutil', 'attach', '-noverify', '-nobrowse', '-plist']
    if readwrite:
        argv.insert(2, '-readwrite')
    doc = plistlib.loads(run(argv + [str(image)]).stdout)
    for entity in doc.get('system-entities', []):
        if entity.get('mount-point'):
            return entity['dev-entry'], entity['mount-point']
    raise SystemExit(f'{image}: attached without a mount point')


def detach(device):
    subprocess.run(['hdiutil', 'detach', str(device)], capture_output=True)
    subprocess.run(['hdiutil', 'detach', '-force', str(device)], capture_output=True)


def free_mib(mount_point):
    stats = os.statvfs(mount_point)
    return stats.f_bavail * stats.f_frsize // MIB


def cache_files(cryptex_mount):
    """The caches dyld needs, as (path, bytes) pairs, largest first.

    Returns the skipped names too, so the report can say what stayed out.
    """
    found = []
    skipped = []
    for path in sorted(Path(cryptex_mount).rglob('dyld_shared_cache*')):
        if not path.is_file():
            continue
        if path.name.endswith(SKIP_SUFFIXES):
            skipped.append(path.name)
            continue
        found.append((path, path.stat().st_size))
    found.sort(key=lambda item: item[1], reverse=True)
    return found, skipped


# ---------------------------------------------------------------- fletcher

def fletcher64(buf):
    mod = 0xFFFFFFFF
    words = struct.unpack('<%dI' % (len(buf) // 4), buf)
    sum1 = sum2 = 0
    for word in words:
        sum1 += word
        sum2 += sum1
    sum1 %= mod
    sum2 %= mod
    c1 = mod - ((sum1 + sum2) % mod)
    c2 = mod - ((sum1 + c1) % mod)
    return (c2 << 32) | c1


def retag_volume(image, wanted_uuid, wanted_name):
    """Rewrite the APFS volume UUID and name, in place, streaming.

    The volume superblock is an `APSB` object: obj_phys_t header (32 bytes),
    then uuid at 0xF0 and apfs_volname at 0x2C0 -- the offsets tools/apfs/apfs.py
    reads.  Its Fletcher-64 covers the block from offset 8 on, so both edits are
    followed by a checksum refresh.  The image is 10 GiB; it is walked 8 MiB at
    a time (a multiple of the block size, so the magic never straddles a chunk)
    instead of being read into memory.
    """
    wanted_bytes = uuid.UUID(wanted_uuid).bytes
    name_bytes = wanted_name.encode('utf-8')[:255]
    patched = 0
    with open(image, 'r+b') as handle:
        handle.seek(0, os.SEEK_END)
        end = handle.tell()
        position = 0
        while position < end:
            handle.seek(position)
            chunk = handle.read(8 * MIB)
            if not chunk:
                break
            search = 0
            while True:
                at = chunk.find(b'APSB', search)
                if at < 0:
                    break
                search = at + 4
                block_start = position + at - 32       # obj_phys_t precedes the magic
                if block_start < 0 or block_start % 4096:
                    continue
                handle.seek(block_start)
                block = bytearray(handle.read(4096))
                if len(block) < 4096:
                    continue
                if fletcher64(bytes(block[8:])) != int.from_bytes(block[:8], 'little'):
                    continue                            # not a live metadata block
                name = block[0x2C0:0x3C0].split(b'\0', 1)[0].decode('utf-8', 'replace')
                if name not in (wanted_name, STAGING_NAME):
                    continue
                block[0xF0:0x100] = wanted_bytes
                block[0x2C0:0x2C0 + 256] = name_bytes.ljust(256, b'\0')
                block[0:8] = fletcher64(bytes(block[8:])).to_bytes(8, 'little')
                handle.seek(block_start)
                handle.write(bytes(block))
                patched += 1
                print(f'retag: block {block_start:#x} {name!r} -> '
                      f'{wanted_name!r} {wanted_uuid}', file=sys.stderr)
            position += len(chunk)
    if not patched:
        raise SystemExit(f'{image}: no APFS volume superblock to retag (looked for '
                         f'{wanted_name!r} / {STAGING_NAME!r})')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True,
                        help='the OS window image the layout step consumes (replaced)')
    parser.add_argument('--cryptex', type=Path, required=True,
                        help='SystemOS image that carries the dyld cache')
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--slack-mib', type=int, default=1024,
                        help='room left over for APFS metadata once the cache is in; '
                             '512 was 50 MiB short on the 22H374 root, whose copy takes '
                             '330 MiB more than its source container')
    parser.add_argument('--keep-original', action='store_true',
                        help='keep a .orig.cdr copy next to the root (6.4 GiB)')
    parser.add_argument('--report', type=Path, default=None)
    args = parser.parse_args()

    original_bytes = args.root.stat().st_size
    args.work.mkdir(parents=True, exist_ok=True)
    scratch = args.work / 'root-rebuild.sparseimage'
    staging = args.work / 'root-rebuild.cdr'
    for stale in (scratch, staging):
        if stale.exists():
            stale.unlink()

    # The caches are measured before anything is created: sizing the volume from
    # a guess is what turns a 40 minute copy into a 40 minute failure.
    cryptex_device, cryptex_mount = attach(args.cryptex)
    try:
        caches, skipped = cache_files(cryptex_mount)
        if not caches:
            raise SystemExit(f'{args.cryptex}: no dyld_shared_cache* anywhere in the cryptex')
        cache_bytes = sum(size for _, size in caches)
        for path, size in caches:
            print(f'cache: {path.name} {size} bytes ({size / MIB:.0f} MiB)', file=sys.stderr)
        size_mib = -(-(original_bytes + cache_bytes) // MIB) + args.slack_mib
        print(f'cache total {cache_bytes / MIB:.0f} MiB in {len(caches)} files; '
              f'new volume {size_mib} MiB', file=sys.stderr)

        root_device, root_mount = attach(args.root)
        info = plistlib.loads(run(['diskutil', 'info', '-plist', root_mount]).stdout)
        wanted_uuid = info['VolumeUUID']
        wanted_name = info['VolumeName']
        print(f'root: {original_bytes} bytes, uuid {wanted_uuid}, '
              f'name {wanted_name!r}', file=sys.stderr)

        # A distinct volume name while the copy runs: the rebuilt volume must not
        # answer to the original name until the original is detached.  The real
        # name is written into the superblock by retag_volume() afterwards.
        run(['hdiutil', 'create', '-size', f'{size_mib}m', '-fs', 'APFS',
             '-volname', STAGING_NAME, '-type', 'SPARSE', '-quiet', scratch])
        new_device, new_mount = attach(scratch, readwrite=True)
        try:
            before = free_mib(new_mount)
            print(f'new volume free: {before} MiB, cache needs {cache_bytes / MIB:.0f} MiB',
                  file=sys.stderr)
            if before < cache_bytes // MIB + 128:
                raise SystemExit(f'{scratch}: only {before} MiB free for '
                                 f'{cache_bytes / MIB:.0f} MiB of cache')
            # ditto keeps signatures, xattrs and ACLs; the root is a sealed
            # system volume whose files must stay byte identical.  The root
            # carries root-only directories (700) and the runner is not root.
            run(['sudo', 'ditto', '--rsrc', '--extattr', '--acl', root_mount, new_mount])
            after_root = free_mib(new_mount)
            print(f'root copied: {before - after_root} MiB used, {after_root} MiB left; '
                  f'cache needs {cache_bytes / MIB:.0f} MiB', file=sys.stderr)
            if after_root < cache_bytes // MIB + 256:
                raise SystemExit(
                    f'{scratch}: the copy leaves {after_root} MiB, the cache needs '
                    f'{cache_bytes / MIB:.0f} MiB + 256 MiB; rerun with --slack-mib '
                    f'{args.slack_mib + cache_bytes // MIB + 512 - after_root}')
            target = Path(new_mount) / 'System/Library/Caches/com.apple.dyld'
            # The stock root points this directory at the cryptex it cannot see;
            # the rebuilt volume carries the real files here instead.
            run(['sudo', 'sh', '-c', f'rm -rf {target} && mkdir -p {target}'])
            copied = []
            for source, size in caches:
                destination = target / source.name
                run(['sudo', 'ditto', '--rsrc', '--extattr', '--acl',
                     str(source), str(destination)])
                landed = Path(destination).stat().st_size
                if landed != size:
                    raise SystemExit(f'{destination}: {landed} bytes landed, {size} expected')
                copied.append({'name': source.name, 'bytes': landed})
            print(f'copied {len(copied)} cache files, '
                  f'{sum(item["bytes"] for item in copied)} bytes, '
                  f'{free_mib(new_mount)} MiB left', file=sys.stderr)
            # Proves the volume really carries a cache, not an empty directory.
            probe = run(['sudo', 'sh', '-c',
                         f'head -c 16 {target}/dyld_shared_cache_* | od -An -c'])
            print(f'cache header: {probe.stdout.decode("utf-8", "replace").strip()}',
                  file=sys.stderr)
        finally:
            detach(new_device)
        detach(root_device)
    finally:
        detach(cryptex_device)

    run(['hdiutil', 'convert', '-quiet', '-format', 'UDTO',
         '-o', str(staging.with_suffix('')), str(scratch)])
    product = staging if staging.is_file() else staging.with_name(staging.name + '.cdr')
    if not product.is_file():
        raise SystemExit(f'convert produced no image next to {staging}')

    retag_volume(product, wanted_uuid, wanted_name)

    rebuilt_bytes = product.stat().st_size
    if rebuilt_bytes < original_bytes:
        raise SystemExit(f'rebuilt root shrank: {original_bytes} -> {rebuilt_bytes} bytes')
    digest = hashlib.sha256()
    with open(product, 'rb') as handle:
        for chunk in iter(lambda: handle.read(16 * MIB), b''):
            digest.update(chunk)
    root_sha256 = digest.hexdigest()

    if args.keep_original:
        backup = args.root.with_suffix('.orig.cdr')
        if not backup.exists():
            print(f'+ keeping a copy of the original at {backup}', file=sys.stderr)
            with open(args.root, 'rb') as src, open(backup, 'wb') as dst:
                for chunk in iter(lambda: src.read(16 * MIB), b''):
                    dst.write(chunk)
    # The rebuilt image lives on the same filesystem as the root, so this is a
    # rename instead of a 10 GiB copy.
    try:
        os.replace(product, args.root)
    except OSError as error:
        print(f'rename failed ({error}); copying instead', file=sys.stderr)
        with open(product, 'rb') as src, open(args.root, 'wb') as dst:
            for chunk in iter(lambda: src.read(16 * MIB), b''):
                dst.write(chunk)
        product.unlink()

    report = {'os_uuid': wanted_uuid, 'volume_name': wanted_name,
              'original_bytes': original_bytes, 'rebuilt_bytes': rebuilt_bytes,
              'cache': copied, 'skipped': skipped,
              'root_sha256': root_sha256}
    text = json.dumps(report, indent=2) + '\n'
    (args.report or (args.work / 'root-rebuild.json')).write_text(text)
    print(f'rebuilt root: {rebuilt_bytes} bytes, uuid kept {wanted_uuid}', file=sys.stderr)


if __name__ == '__main__':
    main()
