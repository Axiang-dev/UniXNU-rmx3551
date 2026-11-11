#!/usr/bin/env python3
"""Keep the PMIC Consumer HID personality in the boot prelink."""

from __future__ import annotations

import copy
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kits" / "NativePrelink"))

from emit_prelink import apply_personality_overrides  # noqa: E402


def main() -> None:
    bundle = "com.apple.iokit.IOHIDFamily"
    personalities = json.loads((ROOT / "configs" / "pong-hid-match.json").read_text())
    overrides = {bundle: personalities}
    if not isinstance(personalities, dict) or "Pong PMIC volume keys" not in personalities:
        raise SystemExit("Pong PMIC volume personality is missing")

    personality = personalities["Pong PMIC volume keys"]
    expected = {
        "CFBundleIdentifier": bundle,
        "IOClass": "IOHIDEventDriver",
        "Transport": "SPMI",
        "Product": "Pong PMIC volume keys",
        "IOMatchDefer": False,
    }
    for key, value in expected.items():
        if personality.get(key) != value:
            raise SystemExit(f"Pong PMIC volume personality has wrong {key}: {personality.get(key)!r}")

    metadata = {"_PrelinkInfoDictionary": [{
        "CFBundleIdentifier": bundle,
        "IOKitPersonalities": {"Stock": {"IOClass": "StockDriver"}},
    }]}
    before = copy.deepcopy(metadata)
    applied = apply_personality_overrides(metadata, overrides)
    if applied != {bundle: ["Pong PMIC volume keys"]}:
        raise SystemExit(f"unexpected override report: {applied!r}")
    merged = metadata["_PrelinkInfoDictionary"][0]["IOKitPersonalities"]
    if set(merged) != {"Stock", "Pong PMIC volume keys"}:
        raise SystemExit("personality merge replaced stock metadata")
    if metadata == before:
        raise SystemExit("personality merge made no change")

    try:
        apply_personality_overrides({"_PrelinkInfoDictionary": []}, overrides)
    except ValueError as error:
        if "unselected kext" not in str(error):
            raise
    else:
        raise SystemExit("personality override for an absent kext was accepted")

    workflow = (ROOT / ".github" / "workflows" / "kernel.yml").read_text()
    for required in (
        "--root com.apple.iokit.IOHIDFamily",
        "--root com.apple.iokit.IOHIDEventDriver",
        "--personality-json com.apple.iokit.IOHIDFamily=configs/pong-hid-match.json",
    ):
        if required not in workflow:
            raise SystemExit(f"kernel workflow is missing {required}")

    board = tomllib.loads((ROOT / "board.toml").read_text())
    if "pong_buttons=1" not in board["payload"]["kernel_args"]:
        raise SystemExit("pong_buttons=1 is absent from the effective board arguments")

    print("rmx3551 PMIC Consumer HID prelink test passed")


if __name__ == "__main__":
    main()