# RMX3551 / UniXNU bring-up progress

Updated: 2026-11-10 (Asia/Shanghai)

The final goal is to keep iPadOS 18 bootable through the UniXNU reference stack and reach SpringBoard, then repair touch, hardware keys and USB. This file records only behavior confirmed by source, generated device trees, build artifacts or hardware logs.

## Current milestone

| Area | Status | Evidence |
|---|---|---|
| iPadOS userland | Verified | iPadOS 18.7.10 (22H374) reaches SpringBoard with display and software UI usable |
| Display | Verified | `1080x2412 BGRA` framebuffer surface and native home request accepted |
| Keyboard / TextInput | Verified | Native TextInput modes and on-screen keyboard are available |
| S3910 touch | Board resources verified; clock-gate fix awaiting CI and hardware retest | Stage-3 now reads real GPIO/SPI/RPMh properties and reaches QUP0 clock setup |
| Hardware keys | Same DT fix, hardware retest pending | Button node real path is `/soc/pong-buttons` |
| USB | Blocked | LIUQIN USB reaches the controller gate, then reports `SMMU route refused; controller untouched` |

The known-good desktop baseline must not be overwritten:

```text
D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-usbdebug-22e7b2c-42510630419.img
SHA-256 9574063d753bda2b190693aa720cd6d08c5dcfa7bc79ae03f17fff40a9c7cb63
```

## Touch and keys

The earlier stage-3 image used the correct boot argument, but the driver queried the wrong ADT path. The resulting log showed every board resource as zero:

```text
Pong touch: DT spi=0 tlmm=0 gcc=0 rsc=0 cmd=0 off=0 pins=0,0,0,0,0,0,0 max=0x0
Pong touch: S3910 board configuration rejected; SKIP
Pong keys: missing/incompatible DT; SKIP
```

Generated `hardware.dtb` proves the real nodes are `/soc/pong-touch` and `/soc/pong-buttons`. Commit `932884e` adds those paths while retaining compatibility fallbacks.

GitHub Actions run `42573247020` failed before reaching the driver because the `bsd/dev/pong_goodix.c` new-file hunk header still declared 1307 lines after the DT fix made it 1308. The trailing `#endif` was therefore not applied, producing `unterminated conditional directive`. This repository now declares 1308 lines and includes this progress record.

A full replacement of the packaged ADT froze UniXNU at the boot menu because it also removed the original SM8475 eight-CPU, UFS and PSCI nodes. The successful stage-3 diagnostic instead changed only `/arm-io/pong-touch`, leaving every other ADT node in place.

The 2026-11-10 hardware run on serial `9ea882b4` reached the real S3910 board path:

```text
Pong touch: S3910 diagnostic stage 3
Pong touch: S3910 rails on; ATTN=1 RESET=1 EN1V8=1
goodix: clocks stay off: 0 0x80000002 0x4220
```

The first real post-ADT blocker is the QUP0 S-AHB branch. `0x80000002` means hardware clock gating is enabled and the branch is idle; it is not a clock failure. The USB driver already treats this exact state as valid. The touch patch now applies the same `clock_state()` rule, so CI must compile and retest next.

Evidence for this run:

```text
region SHA-256 7c6bd416a74687b5ba24de16584de5a9171c8e68d9a10cffad3843c0c2d13062
log SHA-256    d9f746f129c67ce1fe83ed7924e5be2eaa79c1747d83d72dedf1bf5dc2042992
```

## Diagnostic order

Touch must progress one stage at a time:

| Argument | Purpose |
|---|---|
| `pong_s3910=1` | Power, GPIO and DT |
| `pong_s3910=2` | Add QUP0/SE4 clocks and pins |
| `pong_s3910=3` | Add GENI, SPI, identification and protocol; HID disabled |
| `pong_s3910=4` | Publish complete touch HID |

The current next hardware test is stage 3. A pass should identify the S3910 and print its axes as `8640x19296`; that is the native touch coordinate space. The display remains `1080x2412`, so both axes normalize by a factor of eight.

## USB

The current USB path is independent of the touch SPI work. The last desktop run reached:

```text
LIUQIN USB: SID0 matches 0
LIUQIN USB: SMMU route refused; controller untouched
```

Do not change touch resources while diagnosing this USB SMMU route. Finish the S3910 stage-3 check first, then trace the USB IOMMU stream ID and SMMU geometry against the SM8475 and upstream device implementations.

## Safety boundary

- Use `fastboot -s 9ea882b4` whenever more than one device may be attached.
- Use temporary `fastboot boot` for diagnostics.
- Do not flash `boot` or `userdata`, and do not add `-w`.
- Never overwrite the verified `22e7b2c` desktop baseline.
- Do not run `git reset` or `git clean`; this worktree contains historical untracked build inputs and logs.
- New diagnostic images must use a new filename and carry the exact source commit in that filename.

## Next actions

1. Push the QUP0 hardware-gated clock fix and wait for the kernel CI compile.
2. Download `rmx3551-kernel` only after the kernel job succeeds.
3. Rebuild a stage-3 image by applying only the `pong-touch` property patch to the original payload ADT, preserving all other nodes.
4. Verify the embedded TOML still contains `pong_s3910=3`, then boot temporarily with `fastboot -s 9ea882b4 boot`.
5. Decode PongBootLog and require `S3910 QUP0/SE4 source=...`, GENI SPI initialization and a first S3910 response before moving to stage 4.
6. Move to `pong_s3910=4` and HID only after stage 3 identifies the controller.
