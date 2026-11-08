#!/usr/bin/env python3
"""Read a SHNGROOT APFS window through recovery adb without mounting or writing it.

Examples:
  python tools/read-recovery-apfs.py --serial SERIAL info Data
  python tools/read-recovery-apfs.py --serial SERIAL ls Data /mobile/Library/Logs
  python tools/read-recovery-apfs.py --serial SERIAL cat OS /pong/libpong-ui18.dylib --out ui.dylib
"""
import argparse
import hashlib
import json
import pathlib
import struct
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / 'apfs'))
import apfs


class RecoveryImage:
    def __init__(self, serial, window):
        self.adb = ['adb', '-s', serial, 'exec-out']
        header = self.pull(0, 4096)
        if header[:8] != b'SHNGROOT' or hashlib.sha256(header[:4064]).digest() != header[4064:]:
            raise ValueError('Invalid SHNGROOT header or checksum')
        version, count = struct.unpack_from('<II', header, 8)
        if version != 1 or not 1 <= count <= 31:
            raise ValueError('Unsupported SHNGROOT directory')
        self.offset = self.size = None
        for i in range(count):
            entry = header[24 + 128*i:24 + 128*(i+1)]
            if entry[:32].split(b'\0')[0].decode('ascii') == window:
                self.offset, self.size = struct.unpack_from('<QQ', entry, 32)
        if self.offset is None:
            raise ValueError('No window named ' + window)
        self.header = header
        self.image_bytes = struct.unpack_from('<Q', header, 16)[0]
        if (self.offset % 4096 or self.size % 4096 or self.size == 0 or
                self.offset < 4096 or self.offset + self.size > self.image_bytes):
            raise ValueError('Invalid APFS window bounds')
        self.cache = {}

    def pull(self, offset, size):
        if offset % 4096 or size % 4096:
            raise ValueError('Unaligned device read')
        command = ('dd if=/dev/block/by-name/userdata bs=4096 '
                   f'skip={offset // 4096} count={size // 4096} 2>/dev/null')
        result = subprocess.run(self.adb + [command], capture_output=True, check=True, timeout=60)
        if len(result.stdout) != size:
            raise IOError(f'Short device read: {len(result.stdout)} != {size}')
        return result.stdout

    def read(self, offset, length):
        if offset < 0 or length < 0 or offset + length > self.size:
            raise ValueError('Read outside selected APFS window')
        chunks = []
        step = 65536
        while length:
            base = offset // step * step
            if base not in self.cache:
                self.cache[base] = self.pull(self.offset + base, min(step, self.size - base))
            n = min(length, len(self.cache[base]) - (offset - base))
            chunks.append(self.cache[base][offset - base:offset - base + n])
            offset += n
            length -= n
        return b''.join(chunks)

    def close(self):
        self.cache.clear()


def collect(image, destination, serial):
    """Capture the boot ring and selected diagnostic files from the live Data window."""
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {'serial': serial, 'window': 'Data', 'files': [], 'missing': []}

    def save(name, data, source):
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest['files'].append({'path': name, 'source': source, 'bytes': len(data),
                                  'sha256': hashlib.sha256(data).hexdigest()})
        print(f'{name}: {len(data)} bytes', flush=True)

    save('userdata-header.bin', image.header, 'userdata:0')
    offset = (image.image_bytes + (1 << 20) - 1) // (1 << 20) * (1 << 20)
    save('bootlog-region.bin', image.pull(offset, 4096 + 4 * (1 << 20)), f'userdata:{offset}')
    container = apfs.Container('Data')
    volume = apfs.pick_volume(container, None)
    manifest.update(volume_uuid=apfs._uuid(volume.vol_uuid), checkpoint=container.xid)
    try:
        for directory in ('/logs', '/mobile/Library/Logs'):
            hit = volume.lookup(directory)
            if hit is None:
                manifest['missing'].append(directory)
                continue
            for name, fid, dtype in volume.dir_entries(hit[0]):
                if dtype != 8 or not (name.startswith('PongBoot-') or
                        name in ('pong-wifi-bootstrap.log', 'PongService-runningboardd.log')):
                    continue
                if '/' in name or '\\' in name or name in ('.', '..'):
                    raise ValueError('Unsafe diagnostic filename')
                inode = volume.inode(fid)
                if inode.size > 16 * (1 << 20):
                    raise ValueError('Diagnostic file exceeds 16 MiB: ' + name)
                save(directory.strip('/') + '/' + name, inode.contents(), directory + '/' + name)
    finally:
        (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        container.close()
    subprocess.run([sys.executable, str(pathlib.Path(__file__).with_name('read-pong-log.py')),
                    'decode', str(destination / 'bootlog-region.bin'),
                    '--out', str(destination / 'bootlog.txt')], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('command', choices=['info', 'ls', 'stat', 'cat', 'collect'])
    parser.add_argument('window', choices=['OS', 'SystemOS', 'Data'])
    parser.add_argument('path', nargs='?', default='/')
    parser.add_argument('--out', type=pathlib.Path)
    args = parser.parse_args()
    if args.command == 'collect' and (args.window != 'Data' or args.out is None):
        parser.error('collect requires Data and --out NEW_DIRECTORY')
    image = RecoveryImage(args.serial, args.window)
    apfs.open_image = lambda _: image
    if args.command == 'collect':
        collect(image, args.out, args.serial)
        return 0
    if args.command == 'cat' and args.out:
        container = apfs.Container(args.window)
        volume = apfs.pick_volume(container, None)
        hit = volume.lookup(args.path)
        if hit is None:
            raise FileNotFoundError(args.path)
        inode = volume.inode(hit[0])
        data = inode.contents()
        with args.out.open('xb') as target:
            target.write(data)
        print(f'{len(data)} bytes, sha256={hashlib.sha256(data).hexdigest()} -> {args.out}')
        container.close()
        return 0
    return apfs.main(['apfs.py', args.command, args.window, args.path])


if __name__ == '__main__':
    raise SystemExit(main())
