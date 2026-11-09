# RMX3551 / UniXNU bring-up progress

Updated: 2026-11-09 (Asia/Shanghai)

The final goal is to keep iPadOS 18 bootable through the UniXNU reference stack and reach SpringBoard, then repair touch, hardware keys and USB. This file records only behavior confirmed by source, generated device trees, build artifacts or hardware logs.

## Current milestone

| Area | Status | Evidence |
|---|---|---|
| iPadOS userland | Verified | iPadOS 18.7.10 (22H374) reaches SpringBoard with display and software UI usable |
| Display | Verified | `1080x2412 BGRA` framebuffer surface and native home request accepted |
| Keyboard / TextInput | Verified | Native TextInput modes and on-screen keyboard are available |
| S3910 touch | Patch repaired; compile and hardware retest pending | Real path is `/soc/pong-touch`; commit `932884e` fixes the stale `/arm-io` lookup |
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

The next build is the first clean compile check for the corrected DT lookup. GitHub Actions run [`42581880203`](https://github.com/Axiang-dev/UniXNU-rmx3551/actions/runs/42581880203) was `in_progress` when this record was updated. Hardware status is not claimed until a new stage-3 image is booted on serial `9ea882b4` and its PongBootLog is decoded.

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

1. Wait for the CI run started by this commit and inspect its build result.
2. Download `rmx3551-kernel` only if the kernel job succeeds.
3. Verify `payload/payload.json`, the embedded kernel hash and `kernel_args`.
4. Build a new stage-3 payload with `pong_s3910=3` and verify the embedded TOML and PONGFAT1 CRC before booting.
5. Run on `9ea882b4` for at least two minutes, return to TWRP and decode PongBootLog.
6. Continue from the first real S3910 error; move to stage 4 only after stage 3 passes.
