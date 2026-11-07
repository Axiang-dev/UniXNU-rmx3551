#!/usr/bin/env python3
"""Emit the flashable prefix of the userdata image.

The image is a SHNGROOT directory followed by three windows.  Only the OS window
changes between bring-up builds, and it comes first: flashing the 24 GiB image to
change 6 GiB of it costs the phone host far more than the change is worth.

This writes `header + zero pad + OS window` -- byte for byte the prefix a full
flash would write -- split into parts, plus a report the join script verifies.
Everything after the OS window is left alone, which is safe because the OS window
keeps its size: SystemOS and Data stay exactly where the previous flash put them,
and the header records the same offsets either way.
"""
import argparse
import json
from pathlib import Path

MIB = 1 << 20


class SplitWriter:
    def __init__(self, stem, part_bytes):
        self.stem = stem
        self.part_bytes = part_bytes
        self.parts = []
        self.handle = None

    def _open(self):
        self.handle = open(f'{self.stem}.part{len(self.parts):02d}', 'wb')

    def write(self, data):
        view = memoryview(data)
        while view:
            if self.handle is None:
                self._open()
            room = self.part_bytes - self.handle.tell()
            take = min(room, len(view))
            self.handle.write(view[:take])
            view = view[take:]
            if self.handle.tell() >= self.part_bytes:
                self.close_part()

    def close_part(self):
        if self.handle is None:
            return
        size = self.handle.tell()
        self.handle.close()
        self.parts.append({'path': str(self.handle.name), 'bytes': size})
        self.handle = None

    def close(self):
        self.close_part()
        return self.parts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--header', type=Path, required=True)
    parser.add_argument('--layout', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--part-mib', type=int, default=1900)
    parser.add_argument('--json-out', type=Path, required=True)
    args = parser.parse_args()

    header = args.header.read_bytes()
    if len(header) != 4096 or header[:8] != b'SHNGROOT':
        raise SystemExit(f'{args.header}: not a 4096-byte SHNGROOT directory')
    layout = json.loads(args.layout.read_text())
    names = [window['name'] for window in layout['windows']]
    if names != ['OS', 'SystemOS', 'Data']:
        raise SystemExit('layout windows are %s, not OS/SystemOS/Data' % ', '.join(names))
    window = layout['windows'][0]
    offset, size = int(window['offset']), int(window['size'])
    if offset < len(header) or offset % MIB:
        raise SystemExit(f'OS window offset {offset} is not a MiB boundary past the header')
    source = Path(window['image'])
    if not source.is_file():
        raise SystemExit(f'{source} is missing; the OS window parts need it before it is consumed')
    if source.stat().st_size != size:
        raise SystemExit(f'{source}: {source.stat().st_size} bytes, the layout says {size}')

    args.output_dir.mkdir(parents=True, exist_ok=True)
    writer = SplitWriter(args.output_dir / 'pong-ipados18-oswindow.img', args.part_mib * MIB)
    writer.write(header)
    writer.write(b'\0' * (offset - len(header)))
    with open(source, 'rb') as image:
        while True:
            chunk = image.read(8 * MIB)
            if not chunk:
                break
            writer.write(chunk)
    parts = writer.close()
    total = sum(part['bytes'] for part in parts)
    if total != offset + size:
        raise SystemExit(f'the parts hold {total} bytes, the prefix is {offset + size}')

    report = {
        'note': 'SHNGROOT header + pad + the OS window only; concatenate in part '
                'order and flash it over userdata to replace the root without '
                'touching SystemOS or Data',
        'image_bytes': total,
        'os_window_bytes': size,
        'source_sha256': window['sha256'],
        'parts': parts,
    }
    args.json_out.write_text(json.dumps(report, indent=2) + '\n')
    print(f'os window prefix {total} bytes in {len(parts)} part(s)')
    for part in parts:
        print(' ', Path(part['path']).name, part['bytes'])


if __name__ == '__main__':
    main()
