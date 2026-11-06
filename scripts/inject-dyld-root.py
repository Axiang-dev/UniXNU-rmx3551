#!/usr/bin/env python3
"""Give the root volume the dyld shared cache launchd looks for.

The kernel mounts the OS window as the read-only root.  That volume carries no
dyld cache at all (verified: not one `dyld_v1` in the whole image), while the
caches live in the SystemOS cryptex.  launchd resolves the cache through the
root's default path -- /System/Library/Caches/com.apple.dyld/ -- and strips the
DYLD_* environment the kernel hands it, so the cryptex copy is unreachable and
launchd_cache_loader aborts with -67062 (errSecCSUnsigned) before init runs.

This step rebuilds the OS window:

  1. hdiutil creates a larger APFS volume and ditto copies the original root
     into it (signatures, xattrs and ACLs preserved),
  2. the cryptex's dyld_shared_cache* files are copied to
     /System/Library/Caches/com.apple.dyld/ on the new root,
  3. the new volume's UUID is rewritten to the original one -- the kernel's
     root_match_volume_uuid is a compile-time constant and XNU selects the root
     IOMedia by that UUID -- and the volume superblock checksum is recomputed,
  4. the result is converted to the raw image the userdata layout consumes.

Every step fails loudly rather than producing an image that would not boot.
"""
import argparse
import hashlib
import json
import plistlib
import shutil
import struct
import subprocess
import sys
import uuid
from pathlib import Path


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


def hdiutil_info(image):
    out = run(['hdiutil', 'imageinfo', '-plist', image]).stdout
    return plistlib.loads(out)


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


def volume_uuid(mount_point):
    doc = plistlib.loads(run(['diskutil', 'info', '-plist', mount_point]).stdout)
    return doc['VolumeUUID']


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


def retag_volume(image, wanted, volume_name):
    """Rewrite the APFS volume UUID and refresh its Fletcher-64, in place.

    The volume superblock is an `APSB` object; its uuid sits 0xF0 bytes into
    the block and apfs_volname at 0x2C0 (the offsets tools/apfs/apfs.py reads),
    which is why the copy keeps the whole block and only touches sixteen bytes."""
    blob = bytearray(Path(image).read_bytes())
    wanted_bytes = uuid.UUID(wanted).bytes
    patched = []
    offset = 0
    while True:
        at = blob.find(b'APSB', offset)
        if at < 0:
            break
        offset = at + 4
        block_start = at - 32                     # obj_phys_t header precedes the magic
        if block_start < 0:
            continue
        block = bytes(blob[block_start:block_start + 4096])
        if len(block) < 4096 or fletcher64(block[8:]) != int.from_bytes(block[:8], 'little'):
            continue                              # not a live metadata block
        name = block[0x2C0:0x3C0].split(b'\0', 1)[0].decode('utf-8', 'replace')
        if volume_name and name != volume_name:
            continue
        if block[0xF0:0x100] == wanted_bytes:
            patched.append(('already', block_start))
            break
        blob[block_start + 0xF0:block_start + 0x100] = wanted_bytes
        block = bytearray(blob[block_start:block_start + 4096])
        block[0:8] = fletcher64(bytes(block[8:])).to_bytes(8, 'little')
        blob[block_start:block_start + 4096] = block
        patched.append((name, block_start))
        break
    if not patched:
        raise SystemExit(f'{image}: no APFS volume superblock named {volume_name!r} to retag')
    Path(image).write_bytes(blob)
    print(f'retag: {patched[0]}', file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True,
                        help='the OS window image the layout step consumes (replaced)')
    parser.add_argument('--cryptex', type=Path, required=True,
                        help='SystemOS image that carries the dyld cache')
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--extra-mib', type=int, default=3072,
                        help='headroom over the original root for the caches')
    parser.add_argument('--report', type=Path, default=None)
    args = parser.parse_args()

    original_bytes = args.root.stat().st_size
    args.work.mkdir(parents=True, exist_ok=True)
    scratch = args.work / 'root-rebuild.sparseimage'

    # The original stays mounted until ditto has copied it; only then is its
    # name handed to the rebuilt volume.
    root_device, root_mount = attach(args.root)
    info = plistlib.loads(run(['diskutil', 'info', '-plist', root_mount]).stdout)
    wanted_uuid = info['VolumeUUID']
    name = info['VolumeName']
    size_mib = (original_bytes >> 20) + args.extra_mib
    print(f'root: {original_bytes} bytes, uuid {wanted_uuid}, name {name!r}; '
          f'new volume {size_mib} MiB', file=sys.stderr)

    # A distinct volume name: two volumes with the same name land on the same
    # /Volumes path and ditto would copy the root onto itself.  The real name is
    # restored after the original is detached.
    staging_name = 'RMXRootRebuild'
    run(['hdiutil', 'create', '-size', f'{size_mib}m', '-fs', 'APFS',
         '-volname', staging_name, '-type', 'SPARSE', '-quiet', scratch])
    new_device, new_mount = attach(scratch, readwrite=True)
    try:
        # ditto keeps signatures, xattrs and ACLs; the root is a sealed system
        # volume whose files must stay byte identical.
        # The root carries root-only directories (700); the runner is not root.
        run(['sudo', 'ditto', '--rsrc', '--extattr', '--acl', root_mount, new_mount])
        target = str(Path(new_mount) / 'System/Library/Caches/com.apple.dyld')
        # A sealed root points this directory at preboot; the rebuilt volume
        # carries the real files here instead, so the link has to go.
        run(['sudo', 'sh', '-c', f'rm -rf {target} && mkdir -p {target}'])
        cryptex_device, cryptex_mount = attach(args.cryptex)
        try:
            found = sorted(Path(cryptex_mount).rglob('dyld_shared_cache*'))
            if not found:
                raise SystemExit(f'{args.cryptex}: no dyld_shared_cache* anywhere in the cryptex')
            copied = []
            for source in found:
                if not source.is_file():
                    continue
                destination = Path(target) / source.name
                run(['sudo', 'ditto', '--rsrc', '--extattr', '--acl', source, destination])
                # Size only: the layout step hashes the whole window afterwards,
                # and hashing 1.6 GiB here would double the step's runtime.
                copied.append({'name': source.name, 'bytes': Path(destination).stat().st_size})
            print(f'cache: {len(copied)} files, '
                  f'{sum(item["bytes"] for item in copied)} bytes', file=sys.stderr)
        finally:
            detach(cryptex_device)
        # The original root is no longer needed: free its name, give it back to
        # the rebuilt volume so the superblock lookup and the system volume name
        # stay identical to a stock install.
        detach(root_device)
        run(['diskutil', 'rename', new_mount, name])
    finally:
        detach(new_device)

    raw = args.work / 'root-rebuild.cdr'
    run(['hdiutil', 'convert', '-quiet', '-format', 'UDTO', '-o', raw.with_suffix(''), scratch])
    product = raw if raw.is_file() else raw.with_name(raw.name + '.cdr')
    if not product.is_file():
        raise SystemExit(f'convert produced no image next to {raw}')

    retag_volume(product, wanted_uuid, name)

    rebuilt_bytes = product.stat().st_size
    backup = args.root.with_suffix('.orig.cdr')
    if not backup.exists():
        shutil.copyfile(args.root, backup)
    shutil.copyfile(product, args.root)
    report = {'os_uuid': wanted_uuid, 'volume_name': name,
              'original_bytes': original_bytes, 'rebuilt_bytes': rebuilt_bytes,
              'cache': copied,
              'root_sha256': hashlib.sha256(Path(args.root).read_bytes()).hexdigest()}
    text = json.dumps(report, indent=2) + '\n'
    (args.report or (args.work / 'root-rebuild.json')).write_text(text)
    print(f'rebuilt root: {rebuilt_bytes} bytes, uuid kept {wanted_uuid}', file=sys.stderr)


if __name__ == '__main__':
    main()
