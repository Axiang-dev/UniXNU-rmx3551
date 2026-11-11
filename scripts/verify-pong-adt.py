#!/usr/bin/env python3
"""Verify that a Pong ADT contains the board resources the kernel consumes.

The UniXNU shared converter emits a generic tree.  It can therefore look valid
and still leave /arm-io/pong-touch with only its name and compatible value,
which makes the S3910 driver skip itself with every address reported as zero.
Parse the actual binary property tree here so CI fails before uploading that
payload.
"""
import argparse
import struct
import sys
from pathlib import Path

MAX_PROPERTIES = 4096
MAX_CHILDREN = 4096
TOUCH_PINS = (16, 17, 18, 19, 21, 20, 97)
TOUCH_U64_PROPERTIES = {
    "spi-base": 0x00990000,
    "tlmm-base": 0x0F000000,
    "gcc-base": 0x00100000,
    "rsc-base": 0x17A20000,
    "cmd-db-base": 0x80860000,
}
TOUCH_U32_PROPERTIES = {
    "gpio-offset": 0x00100000,
    "max-x": 8640,
    "max-y": 19296,
}
UFS_U64_PROPERTIES = {
    "pong,ufs-hc-base": 0x01D84000,
    "pong,ufs-hc-size": 0x00003000,
    "pong,gcc-ufs-page": 0x00187000,
    "pong,smmu-base": 0x15000000,
    "pong,smmu-size": 0x00100000,
}
UFS_U32_PROPERTIES = {
    "pong,smmu-stream-id": 0xE0,
    "pong,smmu-context-banks": 78,
    "pong,smmu-match-groups": 120,
    "pong,ufs-spi": 0x109,
}

class TreeError(ValueError):
    pass


def take(data, offset, size):
    end = offset + size
    if offset < 0 or size < 0 or end > len(data):
        raise TreeError(f"property tree ends at 0x{offset:x}, need 0x{size:x} more bytes")
    return data[offset:end], end


def parse_node(data, offset):
    header, offset = take(data, offset, 8)
    property_count, child_count = struct.unpack("<II", header)
    if property_count > MAX_PROPERTIES:
        raise TreeError(f"implausible property count {property_count} at 0x{offset - 8:x}")
    if child_count > MAX_CHILDREN:
        raise TreeError(f"implausible child count {child_count} at 0x{offset - 8:x}")

    properties = {}
    for _ in range(property_count):
        key_and_size, offset = take(data, offset, 36)
        raw_key, size = struct.unpack("<32sI", key_and_size)
        key = raw_key.split(b"\0", 1)[0].decode("ascii")
        if not key:
            raise TreeError(f"empty property name at 0x{offset - 36:x}")
        if key in properties:
            raise TreeError(f"duplicate property {key!r} at 0x{offset - 36:x}")
        value, offset = take(data, offset, size)
        padding_size = (-size) % 4
        padding, offset = take(data, offset, padding_size)
        if any(padding):
            raise TreeError(f"nonzero alignment padding after {key!r}")
        properties[key] = value

    children = []
    for _ in range(child_count):
        child, offset = parse_node(data, offset)
        children.append(child)

    raw_name = properties.get("name")
    if raw_name is None:
        raise TreeError(f"node at 0x{offset:x} has no name property")
    name = raw_name.rstrip(b"\0").decode("ascii")
    return {"name": name, "properties": properties, "children": children}, offset


def child(node, name):
    for candidate in node["children"]:
        if candidate["name"] == name:
            return candidate
    raise TreeError(f"{node['name']} has no {name!r} child")


def property_bytes(node, name):
    try:
        return node["properties"][name]
    except KeyError as error:
        raise TreeError(f"{node['name']} is missing property {name!r}") from error


def property_u32(node, name, expected=None):
    raw = property_bytes(node, name)
    if len(raw) != 4:
        raise TreeError(f"{node['name']}/{name} is {len(raw)} bytes, expected 4")
    value = struct.unpack("<I", raw)[0]
    if expected is not None and value != expected:
        raise TreeError(f"{node['name']}/{name} is {value:#x}, expected {expected:#x}")
    return value


def property_u64(node, name, expected=None):
    raw = property_bytes(node, name)
    if len(raw) != 8:
        raise TreeError(f"{node['name']}/{name} is {len(raw)} bytes, expected 8")
    value = struct.unpack("<Q", raw)[0]
    if expected is not None and value != expected:
        raise TreeError(f"{node['name']}/{name} is {value:#x}, expected {expected:#x}")
    return value


def verify(path, expected_cpus):
    data = path.read_bytes()
    tree, consumed = parse_node(data, 0)
    if consumed != len(data):
        raise TreeError(f"parsed {consumed} of {len(data)} bytes")
    if tree["name"] != "device-tree":
        raise TreeError(f"root is {tree['name']!r}, expected 'device-tree'")

    chosen = child(tree, "chosen")
    cpus = child(tree, "cpus")
    arm_io = child(tree, "arm-io")
    touch = child(arm_io, "pong-touch")
    ufs = child(arm_io, "ufshc")

    if len(cpus["children"]) != expected_cpus:
        raise TreeError(f"/cpus has {len(cpus['children'])} nodes, expected {expected_cpus}")
    property_u64(chosen, "dram-size", 0x300000000)
    property_u64(chosen, "darwinboot-memory-size", 0x100000000)
    property_u32(chosen, "debug-enabled", 1)

    compatible = property_bytes(touch, "compatible")
    if b"pong,synaptics-s3910\0" not in compatible:
        raise TreeError("/arm-io/pong-touch does not identify pong,synaptics-s3910")

    for name, expected in TOUCH_U64_PROPERTIES.items():
        property_u64(touch, name, expected)
    for name, expected in TOUCH_U32_PROPERTIES.items():
        property_u32(touch, name, expected)

    if b"qcom,sm8475-ufshc\0" not in property_bytes(ufs, "compatible"):
        raise TreeError("/arm-io/ufshc does not identify qcom,sm8475-ufshc")
    for name, expected in UFS_U64_PROPERTIES.items():
        property_u64(ufs, name, expected)
    for name, expected in UFS_U32_PROPERTIES.items():
        property_u32(ufs, name, expected)
    raw_pins = property_bytes(touch, "pins")
    if len(raw_pins) != len(TOUCH_PINS) * 4:
        raise TreeError(
            f"/arm-io/pong-touch/pins is {len(raw_pins)} bytes, "
            f"expected {len(TOUCH_PINS) * 4}"
        )
    pins = struct.unpack(f"<{len(TOUCH_PINS)}I", raw_pins)
    if pins != TOUCH_PINS:
        raise TreeError(f"/arm-io/pong-touch/pins is {pins}, expected {TOUCH_PINS}")

    print(
        f"Pong ADT verified: {len(data)} bytes, cpus={expected_cpus}, "
        f"touch axes={TOUCH_U32_PROPERTIES['max-x']}x"
        f"{TOUCH_U32_PROPERTIES['max-y']}"
    )
    print(
        "  touch resources: "
        f"spi={TOUCH_U64_PROPERTIES['spi-base']:#x} "
        f"tlmm={TOUCH_U64_PROPERTIES['tlmm-base']:#x} "
        f"gcc={TOUCH_U64_PROPERTIES['gcc-base']:#x} "
        f"rsc={TOUCH_U64_PROPERTIES['rsc-base']:#x} "
        f"cmd-db={TOUCH_U64_PROPERTIES['cmd-db-base']:#x} "
        f"pins={','.join(map(str, TOUCH_PINS))}"
    )
    print(
        "  UFS resources: "
        f"hc={UFS_U64_PROPERTIES['pong,ufs-hc-base']:#x} "
        f"size={UFS_U64_PROPERTIES['pong,ufs-hc-size']:#x} "
        f"smmu-stream={UFS_U32_PROPERTIES['pong,smmu-stream-id']:#x}"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("adt", type=Path, help="kernel.macho.adt to inspect")
    parser.add_argument("--cpus", type=int, default=4, help="expected /cpus child count")
    args = parser.parse_args()
    try:
        verify(args.adt, args.cpus)
    except (OSError, TreeError, UnicodeError, struct.error) as error:
        print(f"Pong ADT verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
