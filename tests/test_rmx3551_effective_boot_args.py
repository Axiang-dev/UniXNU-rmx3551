#!/usr/bin/env python3
"""Prevent metadata-only CPU/USB edits from passing as effective boot args."""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_finalizer():
    path = ROOT / "scripts/finalize-pong-adt.py"
    spec = importlib.util.spec_from_file_location("finalize_pong_adt", path)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load finalize-pong-adt.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def menu(args: str) -> bytes:
    return f'''version = 1
[boot]
timeout = 3
default = "xnu"
[[entry]]
id = "xnu"
title = "RMX3551 iPadOS 18.7.10"
type = "xnu"
path = "Payloads/kernel.macho"
args = "{args}"
'''.encode()


def main() -> None:
    module = load_finalizer()
    board = tomllib.loads((ROOT / "board.toml").read_text(encoding="utf-8"))
    payload = board["payload"]
    values = payload["kernel_args"]
    selector = next(item for item in values
                    if item.split("=", 1)[0] in ("cpus", "cpumask"))
    if selector.startswith("cpus="):
        cpu_count = int(selector.split("=", 1)[1])
    else:
        cpu_count = int(selector.split("=", 1)[1], 0).bit_count()
    expected = module.derive_xnu_args(payload, cpu_count)

    extra = [item for item in values
             if item.split("=", 1)[0] not in ("keepsyms", "cpus", "cpumask")]
    unordered = " ".join(["keepsyms=1", *reversed(extra), selector])
    module.read_member = lambda volume, member: menu(unordered)
    module.validate_xnu_args("effective.img", expected)

    if selector.startswith("cpus="):
        stale_selector = "cpus=4" if selector != "cpus=4" else "cpus=5"
    else:
        stale_selector = "cpumask=0x1e"
    stale = expected.replace(selector, stale_selector, 1)
    module.read_member = lambda volume, member: menu(stale)
    try:
        module.validate_xnu_args("stale.img", expected)
    except SystemExit as error:
        message = str(error)
        if "effective xnu args disagree" not in message:
            raise SystemExit(f"unexpected stale-image failure: {message}") from error
    else:
        raise SystemExit("finalizer accepted an xnu entry that disagrees with board.toml")

    print("rmx3551 effective boot-argument test passed")


if __name__ == "__main__":
    main()
