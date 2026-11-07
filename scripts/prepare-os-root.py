#!/usr/bin/env python3
"""Give the OS root what launchd needs before it will read a single job.

Two unrelated things stop launchd on a copy of the 22H374 root that is not the
sealed system volume:

* launchd verifies /System/Library/xpc/launchd.plist against the detached
  signature in /System/Library/xpc/launchd.plist.sig.  A volume that is not the
  sealed system volume can never satisfy that check, and launchd aborts with
  -67062 errSecCSUnsigned *after* it has already mapped the dyld shared cache
  (the panic log reads "mapping 112 segments" immediately before the abort).
  The reference recipe moves the plist and its signature out of the image and
  installs its own launchd.plist with no signature beside it.
* the split userland keeps part of usr/lib, usr/libexec, usr/bin and usr/sbin in
  the SystemOS cryptex, so launchd's execvp of /usr/libexec/xpcproxy fails with
  ENOENT.  The reference recipe bridges those files with symlinks into
  /private/preboot.

Both edits are metadata only, so the APFS container keeps its exact size: the
SystemOS and Data windows after it stay where the flashed image put them, which
is what lets a rebuilt root be flashed on its own.

The dyld cache itself is *not* copied.  The kernel already hands launchd
DYLD_SHARED_CACHE_DIR=/private/preboot/System/Library/Caches/com.apple.dyld/ and
the cache maps straight out of the cryptex; the alias below only makes the
default path resolve for anything that still looks there.
"""
import argparse
import json
import os
import plistlib
import shlex
import subprocess
import sys
from pathlib import Path

MIB = 1 << 20
TREES = ('usr/lib', 'usr/libexec', 'usr/bin', 'usr/sbin')
ALIASES = {
    'var': 'private/var',
    'System/Cryptexes/OS': '/private/preboot',
    'System/Library/Caches/com.apple.dyld':
        '/private/preboot/System/Library/Caches/com.apple.dyld',
}
# launchd reads the plist; the detached signature is what cannot be satisfied
# here.  Only the signature leaves the image: the stock job list stays exactly as
# Apple shipped it, and a plist with no .sig beside it is what the reference
# recipe boots with (it installs its own unsigned plist the same way).
MOVED = ('System/Library/xpc/launchd.plist.sig',)


def run(argv, **kwargs):
    print('+', ' '.join(str(a) for a in argv), file=sys.stderr)
    result = subprocess.run([str(a) for a in argv], capture_output=True, **kwargs)
    if result.returncode:
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


def cryptex_links(root, cryptex):
    """Files the cryptex has and the root lacks, as (relative path, target)."""
    links = []
    for tree in TREES:
        source = Path(cryptex) / tree
        if not source.is_dir():
            continue
        for directory, dirs, files in os.walk(source, followlinks=False):
            directory = Path(directory)
            rel_dir = directory.relative_to(cryptex)
            # A supplied alias already owns this subtree; never walk through an
            # iOS absolute symlink while building.
            if any((Path(root) / p).is_symlink() for p in (rel_dir, *rel_dir.parents)
                   if str(p) != '.'):
                dirs[:] = []
                continue
            symbolic = [name for name in dirs if (directory / name).is_symlink()]
            dirs[:] = [name for name in dirs if name not in symbolic]
            for name in files + symbolic:
                rel = (directory / name).relative_to(cryptex).as_posix()
                if os.path.lexists(Path(root) / rel):
                    continue
                links.append((rel, '/private/preboot/' + rel))
    return links


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True,
                        help='the OS window image the layout step consumes (rewritten in place)')
    parser.add_argument('--cryptex', type=Path, required=True,
                        help='SystemOS image the userland is split across')
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--report', type=Path, default=None)
    args = parser.parse_args()

    original_bytes = args.root.stat().st_size
    args.work.mkdir(parents=True, exist_ok=True)
    # hdiutil names the UDRW product after -o with a .dmg suffix, so the stem and
    # the file it produces are two different names.
    stem = args.work / 'os-root-writable'
    product = stem.with_suffix('.dmg')
    for stale in (product, stem, stem.with_suffix('.cdr')):
        if stale.is_file():
            stale.unlink()

    # The layout consumes a UDTO image, which hdiutil writes read-only; the
    # edits go through a UDRW copy and come back as UDTO with the same container
    # size, so every window after the OS keeps its offset.
    run(['hdiutil', 'convert', '-quiet', '-format', 'UDRW',
         '-o', str(stem), str(args.root)])
    if not product.is_file():
        raise SystemExit(f'convert produced no {product}')

    moved = []
    links = []
    aliases = []
    device, mount = attach(product, readwrite=True)
    try:
        mount = Path(mount)
        stock = mount / 'pong/stock-config'
        run(['sudo', 'mkdir', '-p', str(stock)])
        for rel in MOVED:
            source = mount / rel
            if not os.path.lexists(source):
                continue
            run(['sudo', 'mv', str(source), str(stock / Path(rel).name)])
            moved.append(rel)
        print(f'moved out of the image: {", ".join(moved) or "nothing"}', file=sys.stderr)
        # What matters is not that a file was moved, but that launchd cannot find
        # a stock detached signature next to the cache.  A prepared userland that
        # never carried one satisfies that just as well, so record the end state
        # and let the caller assert on it instead of on `moved`.
        still_present = [rel for rel in MOVED if os.path.lexists(mount / rel)]

        cryptex_device, cryptex_mount = attach(args.cryptex)
        try:
            links = cryptex_links(mount, cryptex_mount)
        finally:
            detach(cryptex_device)
        print(f'cryptex links to install: {len(links)}', file=sys.stderr)

        script = args.work / 'os-root-links.sh'
        lines = ['set -e']
        quote = shlex.quote
        parents = sorted({str(Path(rel).parent) for rel, _ in links if str(Path(rel).parent) != '.'})
        for parent in parents:
            lines.append(f'mkdir -p {quote(f"{mount}/{parent}")}')
        for rel, target in links:
            lines.append(f'ln -s {quote(target)} {quote(f"{mount}/{rel}")}')
        # Aliases: only ever into a path that is absent or an empty directory.
        for rel, target in ALIASES.items():
            existing = mount / rel
            if os.path.lexists(existing):
                empty = False
                try:
                    empty = existing.is_dir() and not existing.is_symlink() and not any(
                        existing.iterdir())
                except OSError as error:
                    print(f'alias {rel}: cannot inspect ({error}); leaving it alone',
                          file=sys.stderr)
                if empty:
                    lines.append(f'rmdir {quote(str(existing))}')
                else:
                    continue
            lines.append(f'ln -s {quote(target)} {quote(str(existing))}')
            aliases.append(rel)
        script.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        run(['sudo', 'sh', str(script)])
        print(f'aliases created: {", ".join(aliases) or "none"}', file=sys.stderr)

        # Per-service launchd policy.  userland/board_services18.py has carried
        # the reference port's evidence-driven job adjustments since the 22H374
        # import, but nothing ever called it, so every boot paid for the same
        # failures again: bluetoothd and wifip2pd restarting on hardware this
        # board does not have, softwareupdated crashing at startup, and the
        # com.apple.wifi.manager port reserved before wifid checks in -- the
        # wait the reference port recorded as blocking SpringBoard's first
        # frame.  Run it as root so the job plists stay owned by root.
        services = Path(__file__).resolve().parents[1] / 'userland' / 'board_services18.py'
        if services.is_file():
            run(['sudo', sys.executable, str(services), '--stage-root', str(mount)])
            print('launchd job policy staged', file=sys.stderr)
        else:
            print(f'no {services}; job policy left at stock', file=sys.stderr)
    finally:
        detach(device)

    final = args.work / 'os-root-final'
    rebuilt = final.with_suffix('.cdr')
    for stale in (rebuilt, final, final.with_suffix('.dmg')):
        if stale.is_file():
            stale.unlink()
    run(['hdiutil', 'convert', '-quiet', '-format', 'UDTO',
         '-o', str(final), str(product)])
    if not rebuilt.is_file():
        raise SystemExit(f'convert produced no {rebuilt}')
    rebuilt_bytes = rebuilt.stat().st_size
    if rebuilt_bytes != original_bytes:
        raise SystemExit(f'{rebuilt}: {rebuilt_bytes} bytes, the source container was '
                         f'{original_bytes}; the windows after it would move')
    product.unlink()
    os.replace(rebuilt, args.root)

    report = {'original_bytes': original_bytes, 'rebuilt_bytes': rebuilt_bytes,
              'moved': moved, 'still_present': still_present,
              'links': len(links), 'aliases': aliases}
    text = json.dumps(report, indent=2) + '\n'
    (args.report or (args.work / 'os-root.json')).write_text(text)
    print(f'root kept its size: {rebuilt_bytes} bytes, {len(links)} links, '
          f'{len(moved)} files moved', file=sys.stderr)


if __name__ == '__main__':
    main()
