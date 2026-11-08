#!/usr/bin/env python3
"""Resolve PongBoot thread PCs and frame return addresses in a matching dyld cache.

The shared-cache slide comes from snapshot cache=, not image_slide= (which
belongs to the main executable). Local symbols must match the cache's UUID.
Format reference: Apple's include/mach-o/dyld_cache_format.h.
"""
import argparse
import bisect
import importlib.util
import json
import mmap
from pathlib import Path
import re
import struct


class Symbols:
    def __init__(self, cache, symbols, systemos=None):
        self.cache = cache.read_bytes()
        if self.cache[:16].rstrip(b'\0') != b'dyld_v1   arm64':
            raise ValueError('Expected arm64 dyld cache')
        self.file = symbols.open('rb')
        self.data = mmap.mmap(self.file.fileno(), 0, access=mmap.ACCESS_READ)
        if self.data[88:104] != self.cache[400:416]:
            raise ValueError('Local symbol UUID does not match cache')
        self.region, self.region_size, self.max_slide = struct.unpack_from('<3Q', self.cache, 224)
        offset, count = struct.unpack_from('<2Q', self.cache, 136)
        self.images = []
        for i in range(count):
            uuid, address, size, path = struct.unpack_from('<16sQII', self.cache, offset + i * 32)
            end = self.cache.index(b'\0', path)
            self.images.append((address, size, self.cache[path:end].decode(), uuid.hex()))
        self.images.sort()
        self.starts = [i[0] for i in self.images]
        self.local, size = struct.unpack_from('<2Q', self.data, 72)
        if self.local + size > len(self.data):
            raise ValueError('Local symbols extend beyond file')
        self.no, self.nc, self.so, self.ss, eo, ec = struct.unpack_from('<6I', self.data, self.local)
        self.entries = {}
        for i in range(ec):
            address, start, count = struct.unpack_from('<QII', self.data, self.local + eo + i * 16)
            if start + count > self.nc:
                raise ValueError('Local symbol entry outside table')
            self.entries[address] = (start, count)
        self.tables = {}
        self.reader = None
        if systemos:
            spec = importlib.util.spec_from_file_location('apfs_dyld', Path(__file__).with_name('apfs-dyld.py'))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.reader = module.CacheReader(systemos, self.cache[88:104])

    def resolve(self, address, slide, return_address=False):
        # Saved frame LRs point to the instruction after the call.
        pc = address - (4 if return_address and address else 0)
        va = pc - slide
        result = {'address': hex(address), 'unslid': hex(va)}
        i = bisect.bisect_right(self.starts, va) - 1
        if i < 0 or va >= self.images[i][0] + self.images[i][1]:
            result['unresolved'] = 'outside cache text; executable or other mapping'
            return result
        base, size, name, uuid = self.images[i]
        result.update(image=name, uuid=uuid)
        if base not in self.tables:
            table = []
            start, count = self.entries.get(base - self.region, (0, 0))
            for j in range(start, start + count):
                string, kind, section, _, value = struct.unpack_from('<IBBHQ', self.data, self.local + self.no + j * 16)
                if not kind & 0xe0 and kind & 0xe == 0xe and section and base <= value < base + size:
                    if string >= self.ss:
                        raise ValueError('Symbol string outside string table')
                    pos = self.local + self.so + string
                    end = self.data.find(b'\0', pos, self.local + self.so + self.ss)
                    if end < 0:
                        raise ValueError('Unterminated symbol name')
                    table.append((value, self.data[pos:end].decode(errors='replace')))
            if self.reader:
                table.extend((value, name) for value, name in self.reader.exports(base)
                             if base <= value < base + size)
            table = sorted(set(table))
            self.tables[base] = ([row[0] for row in table], table)
        values, table = self.tables[base]
        j = bisect.bisect_right(values, va) - 1
        if j >= 0:
            value, symbol = table[j]
            result.update(nearest_symbol=symbol, offset=va - value)
        return result

    def snapshots(self, path):
        result = []
        current = None
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            if line.startswith('Pong boot snapshot:') and 'cache=' in line:
                fields = dict(re.findall(r'(\w+)=([^ ]+)', line))
                cache = int(fields['cache'], 16)
                slide = cache - self.region
                if not 0 <= slide <= self.max_slide or slide % 4096:
                    raise ValueError('Invalid cache base/slide in ' + str(path))
                current = {'header': line, 'cache_slide': hex(slide), 'threads': []}
                result.append(current)
            elif line.startswith('thread=') and current is not None:
                fields = dict(re.findall(r'(\w+)=([^ ]+)', line.split('frames:')[0]))
                thread = {'state': fields, 'stack': []}
                if fields['state_result'] == '0':
                    pcs = [('pc', fields['pc']), ('lr', fields['lr'])]
                    pcs += [('frame', value) for value in line.split('frames:', 1)[1].split()]
                    for kind, value in pcs:
                        if int(value, 16) == 0:
                            continue
                        thread['stack'].append({'kind': kind, **self.resolve(int(value, 16), slide, kind != 'pc')})
                current['threads'].append(thread)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--symbols', type=Path, required=True)
    parser.add_argument('--systemos', type=Path, help='raw matching APFS image, to include exported symbols')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('snapshots', nargs='+', type=Path)
    args = parser.parse_args()
    symbols = Symbols(args.cache, args.symbols, args.systemos)
    result = {str(path): symbols.snapshots(path) for path in args.snapshots}
    with args.out.open('x', encoding='utf-8') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    print(f'Resolved {sum(len(v) for v in result.values())} snapshots -> {args.out}')


if __name__ == '__main__':
    main()
