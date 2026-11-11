#!/usr/bin/env python3
"""Finish the packaged payload the way a local run packs it, and write the boot image.

`unixnu release` follows docs/porting/packaging.md: it writes kernel.macho.adt
with the shared converter and puts payload.img in the boot image's ramdisk slot
unchanged. A local run does two things that document does not describe, and this
step repeats them with the local parameters so the artifacts agree:

* The ADT comes from scripts/make-pong-adt-ipados18.py, the generator the local
  chain uses. The shared converter expresses root, chosen, defaults, options,
  product and buttons, but not the properties this board's kernel reads from
  /arm-io (the pong,ufs-* windows NativeUfs validates, the touch and button
  resources, the PMIC metadata). The parameters are the ones a local run passes:
  12 GiB of physical DRAM, a 4 GiB DarwinBoot window, one CPU, the J171 chip ID,
  the development policy and the boot manifest hash.
* The boot image is the container a local run writes: Android boot v4 with an
  empty kernel slot (this device boots the firmware from its own partition),
  the payload wrapped in the PONGFAT1 envelope PongBootMemoryDxe publishes, and
  an empty signature area. The firmware refuses an initrd above 128 MiB, which
  is why board.toml [payload] size_mib is 96.

boot/boot.img itself stays exactly what `release` wrote: it is the document's
artifact, with the raw payload as its ramdisk.
"""
import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import tomllib
import zlib
from collections import Counter
from pathlib import Path

HEADER_BYTES = 4096          # PONGFAT1 header, and the boot image's first page
SIGNATURE_BYTES = 4096       # boot v4 signature area, left empty
BOOT_HEADER_V4_SIZE = 1584   # boot image header v4, as mkbootimg writes it
BOOT_ARGS_BYTES = 1536       # BOOT_ARGS_SIZE 512 + BOOT_EXTRA_ARGS_SIZE 1024
MAGIC = b'PONGFAT1'

MANIFEST_FORMAT = 'pong-development-boot-manifest-v1'
BOARD = 'Nothing Phone (2) / Pong / SM8475'


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def envelope(fat):
    """PONGFAT1 header followed by the FAT volume, as PongBootMemoryDxe validates it.

    The firmware scans a bounded initrd for this header, then checks the version,
    the header length, a 512-byte multiple length, the FAT signature, the sector
    count and the CRC32 of the volume.
    """
    if len(fat) % 512 or fat[510:512] != b'\x55\xaa' or struct.unpack_from('<H', fat, 11)[0] != 512:
        raise SystemExit('the payload volume is not a FAT volume with 512-byte sectors')
    sectors16 = struct.unpack_from('<H', fat, 19)[0]
    sectors = sectors16 or struct.unpack_from('<I', fat, 32)[0]
    if sectors != len(fat) // 512:
        raise SystemExit(f'the payload volume declares {sectors} sectors, it holds {len(fat) // 512}')
    header = bytearray(HEADER_BYTES)
    struct.pack_into('<8sIIQII', header, 0, MAGIC, 1, HEADER_BYTES, len(fat), zlib.crc32(fat) & 0xffffffff, 0)
    return bytes(header) + fat


def boot_image(ramdisk):
    """Android boot v4: 4096-byte header page, the ramdisk, an empty signature area.

    The kernel slot stays empty because this device boots the UEFI firmware from
    its own partition; the ramdisk is the whole payload. That is the container
    scripts/build-ipados18-bootimg-local.py builds from its v4 template.
    """
    header = bytearray(HEADER_BYTES)
    header[0:8] = b'ANDROID!'
    struct.pack_into('<4I', header, 8, 0, len(ramdisk), 0, BOOT_HEADER_V4_SIZE)
    struct.pack_into('<I', header, 40, 4)
    struct.pack_into('<I', header, 40 + 4 + BOOT_ARGS_BYTES, 0)  # signature_size
    return bytes(header) + ramdisk + bytes(SIGNATURE_BYTES)


def read_member(volume, member):
    env = dict(os.environ, MTOOLS_SKIP_CHECK='1', TZ='UTC')
    probe = subprocess.run(['mtype', '-i', str(volume), f'::{member}'], env=env, capture_output=True)
    return probe.stdout if probe.returncode == 0 else None


def validate_xnu_args(volume, expected):
    """Reject a payload whose actual boot menu disagrees with board.toml.

    kernel_args is also copied into pong-adt.json, but DarwinBoot reads the
    xnu entry from EFI/UniXNU/unixnu.toml. Updating metadata alone used to make
    an image say cpus=5/usboff while the firmware still booted cpus=4 with USB
    enabled. Compare the effective menu entry before wrapping the FAT volume.
    """
    member = 'EFI/UniXNU/unixnu.toml'
    content = read_member(volume, member)
    if content is None:
        raise SystemExit(f'{volume}: {member} is missing; DarwinBoot has no xnu entry')
    try:
        document = tomllib.loads(content.decode('utf-8'))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise SystemExit(f'{volume}: {member} does not parse: {error}') from error
    entries = [entry for entry in document.get('entry', [])
               if entry.get('type') == 'xnu' and entry.get('path') == 'Payloads/kernel.macho']
    if len(entries) != 1:
        raise SystemExit(f'{volume}: expected one kernel.macho xnu entry, found {len(entries)}')
    actual = entries[0].get('args')
    if not isinstance(actual, str):
        raise SystemExit(f'{volume}: the xnu entry has no string args value')
    expected_args = Counter(expected.split())
    actual_args = Counter(actual.split())
    if actual_args == expected_args:
        return
    missing = sorted((expected_args - actual_args).elements())
    unexpected = sorted((actual_args - expected_args).elements())
    raise SystemExit(f'{volume}: effective xnu args disagree with board.toml; '
                     f'missing={missing} unexpected={unexpected}')


def derive_xnu_args(spec, cpu_count):
    """Build the exact kernel command line from board.toml.

    Darwin 24 cannot use cpus= and cpumask= together.  XNU's cpus= path also
    failed to admit the fifth node on RMX3551 even though the ADT carried it,
    while the equivalent cpumask reached CPU4.  Keep one explicit selector in
    board.toml and reject a count or mask that disagrees with the ADT builder.
    """
    values = spec.get("kernel_args", [])
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise SystemExit("board.toml payload.kernel_args must be a string list")
    by_name = {}
    for item in values:
        name, separator, value = item.partition("=")
        if separator:
            by_name[name] = value
    selectors = [item for item in values
                 if item.split("=", 1)[0] in ("cpus", "cpumask")]
    if len(selectors) != 1:
        raise SystemExit("board.toml must carry exactly one of cpus= or cpumask=")
    selector = selectors[0]
    if selector.startswith("cpus="):
        try:
            selected = int(by_name["cpus"], 10)
        except ValueError as error:
            raise SystemExit(f"invalid CPU selector {selector!r}") from error
        if selected != cpu_count:
            raise SystemExit(f"{selector} disagrees with ADT cpu_count={cpu_count}")
    else:
        try:
            mask = int(by_name["cpumask"], 0)
        except ValueError as error:
            raise SystemExit(f"invalid CPU selector {selector!r}") from error
        expected = (1 << cpu_count) - 1
        if mask != expected:
            raise SystemExit(f"{selector} disagrees with ADT cpu_count={cpu_count}; "
                             f"expected {hex(expected)}")
    extra = [item for item in values
             if item.split("=", 1)[0] not in ("keepsyms", "cpus", "cpumask")]
    return " ".join(["keepsyms=1", selector, *extra])


def write_member(volume, member, content):
    """Overwrite or add one file inside the FAT image with mtools, without mounting it."""
    env = dict(os.environ, MTOOLS_SKIP_CHECK='1', TZ='UTC')
    with tempfile.NamedTemporaryFile(suffix='-' + Path(member).name, delete=False) as handle:
        handle.write(content)
        scratch = Path(handle.name)
    try:
        subprocess.run(['mcopy', '-o', '-i', str(volume), str(scratch), f'::{member}'],
                       check=True, env=env, capture_output=True)
    finally:
        scratch.unlink(missing_ok=True)
    if read_member(volume, member) != content:
        raise SystemExit(f'{volume}: {member} did not read back as written')


def main():
    device = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', required=True, type=Path,
                        help='the release configuration directory (out/<device>/<os>/<config>)')
    parser.add_argument('--uefi', type=Path, help='Mu-Silicium checkout, exported to the generator as UNIXNU_UEFI')
    parser.add_argument('--unique-chip-id', required=True, help='platform seed, the value the release used')
    parser.add_argument('--volume-layout', type=Path, help='layout JSON the kernel was configured with')
    parser.add_argument('--hardware-dtb', type=Path,
                        help='compiled board DTS (default: board.toml [bootimg] dtb under the work tree)')
    parser.add_argument('--dram-size', type=lambda value: int(value, 0), default=0x300000000,
                        help='physical DRAM the boot chain reports; a local run passes 12 GiB')
    parser.add_argument('--window-size', type=lambda value: int(value, 0), default=0x100000000,
                        help="DarwinBoot's allocation window; a local run passes 4 GiB")
    parser.add_argument('--cpus', type=int, choices=range(1, 9), default=1,
                        help='CPU nodes in the ADT; a local bring-up run passes 1')
    parser.add_argument('--chip-id', default=None, help='BuildIdentity chip ID (default: board.toml [payload.adt])')
    parser.add_argument('--ufs-probe', action='store_true',
                        help='publish the UFS nub; a local bring-up image leaves it out')
    parser.add_argument('--no-development-debug', dest='development_debug', action='store_false',
                        help='leave the DT debugger gate off; a local run turns it on')
    args = parser.parse_args()

    work = args.work_dir.resolve()
    board = tomllib.loads((device / 'board.toml').read_text())
    payload = work / 'payload/payload.img'
    if not payload.is_file():
        raise SystemExit(f'{payload} missing: run scripts/package.sh first')
    trust_cache = read_member(payload, 'EFI/UniXNU/Payloads/kernel.macho.trustcache')
    if trust_cache is None:
        raise SystemExit(f'{payload}: kernel.macho.trustcache is missing; DarwinBoot consistency requires its ADT slot')
    if not trust_cache:
        raise SystemExit(f'{payload}: kernel.macho.trustcache is empty')
    dtb = (args.hardware_dtb or work / 'tree' / str(board.get('bootimg', {}).get('dtb', ''))).resolve()
    if not dtb.is_file():
        raise SystemExit(f'{dtb} missing: the firmware preflight step compiles the board DTS')

    layout = json.loads(args.volume_layout.read_text()) if args.volume_layout else {}
    root_uuid = (layout.get('os') or {}).get('uuid')
    chip_id = args.chip_id or str(board.get('payload', {}).get('adt', {}).get('chip_id', '0x8010'))

    spec = board.get('payload', {})
    boot_args = derive_xnu_args(spec, args.cpus)
    validate_xnu_args(payload, boot_args)
    # The manifest a local run stages: scripts/build-ipados18-bootimg-local.py
    # writes exactly these keys, and with --skip-image-verification the digests
    # of the kernel and the loader stay null.
    manifest = json.dumps({
        'format': MANIFEST_FORMAT,
        'apple_personalization': False,
        'development_debug': bool(args.development_debug),
        'amfi_only_platform_code': False,
        'system_volume_auth_blob_sha256': None,
        'kernel_sha384': None,
        'loader_sha384': None,
        'board': BOARD,
        'boot_args': boot_args,
        'root_volume_uuid': root_uuid,
        'requested_memory_window_bytes': args.window_size,
    }, sort_keys=True, separators=(',', ':')).encode() + b'\n'
    manifest_file = work / 'payload/pong-boot-manifest.json'
    manifest_file.write_bytes(manifest)

    generated = work / 'payload/kernel.macho.adt.pong'
    command = [sys.executable, str(device / 'scripts/make-pong-adt-ipados18.py'),
               '--cpus', str(args.cpus),
               '--dram-size', hex(args.dram_size),
               '--window-size', hex(args.window_size),
               '--output', str(generated),
               '--unique-chip-id', args.unique_chip_id,
               '--chip-id', chip_id,
               '--boot-manifest', str(manifest_file),
               '--trust-cache',
               # The local chain records no image audit for this development image.
               '--skip-image-verification']
    if args.development_debug:
        command.append('--development-debug')
    if args.ufs_probe:
        command.append('--ufs-probe')
    if root_uuid:
        command += ['--root-match-volume-uuid', root_uuid]
    environment = dict(os.environ, PONG_HARDWARE_DTB=str(dtb))
    if args.uefi:
        environment['UNIXNU_UEFI'] = str(args.uefi.resolve())
    subprocess.run(command, cwd=device, check=True, env=environment)
    adt = generated.read_bytes()

    # kernel.macho.adt is what the firmware loads; pong-boot-manifest.json is the
    # unsigned description a local image carries beside it.
    write_member(payload, 'EFI/UniXNU/Payloads/kernel.macho.adt', adt)
    write_member(payload, 'EFI/UniXNU/Payloads/pong-boot-manifest.json', manifest)

    ramdisk = envelope(payload.read_bytes())
    image = boot_image(ramdisk)
    target = work / 'boot/pong-xnu-initial.img'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(image)
    if image[:8] != b'ANDROID!' or struct.unpack_from('<I', image, 40)[0] != 4:
        raise SystemExit('the boot image is not an Android v4 container')
    if image[HEADER_BYTES:HEADER_BYTES + 8] != MAGIC:
        raise SystemExit('the ramdisk does not begin with the PONGFAT1 envelope')

    record = {'generator': 'scripts/make-pong-adt-ipados18.py',
              'container': {'format': 'android-boot-v4', 'header_bytes': BOOT_HEADER_V4_SIZE,
                            'kernel_bytes': 0, 'signature_bytes': 0,
                            'ramdisk_bytes': len(ramdisk), 'image_bytes': len(image),
                            'note': ('the device boots the UEFI firmware from its own partition; '
                                     'the ramdisk carries the whole payload')},
              'parameters': {'dram_size': hex(args.dram_size), 'window_size': hex(args.window_size),
                             'cpus': args.cpus, 'unique_chip_id': args.unique_chip_id, 'chip_id': chip_id,
                             'ufs_probe': bool(args.ufs_probe),
                             'development_debug': bool(args.development_debug),
                             'skip_image_verification': True,
                             'root_match_volume_uuid': root_uuid},
              'hardware_dtb': {'path': str(dtb), 'bytes': dtb.stat().st_size, 'sha256': sha256(dtb)},
              'adt_bytes': len(adt), 'adt_sha256': sha256(generated),
              'trust_cache_bytes': len(trust_cache),
              'trust_cache_sha256': hashlib.sha256(trust_cache).hexdigest(),
              'boot_manifest_bytes': len(manifest), 'boot_manifest_sha256': hashlib.sha256(manifest).hexdigest(),
              'boot_args': boot_args,
              'payload_bytes': payload.stat().st_size, 'payload_sha256': sha256(payload),
              'image_sha256': sha256(target), 'hardware_tested': False}
    (work / 'boot/pong-boot.json').write_text(json.dumps(record, indent=2) + '\n')
    (work / 'payload/pong-adt.json').write_text(json.dumps(record, indent=2) + '\n')
    manifest_path = work / 'package.manifest.json'
    if manifest_path.is_file():
        package = json.loads(manifest_path.read_text())
        outputs = package.setdefault('outputs', {})
        for key, path in (('boot.img', work / 'boot/boot.img'), ('payload.img', payload),
                          ('pong-xnu-initial.img', target)):
            if path.is_file():
                outputs[key] = {'bytes': path.stat().st_size, 'sha256': sha256(path)}
        manifest_path.write_text(json.dumps(package, indent=2, sort_keys=True) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
