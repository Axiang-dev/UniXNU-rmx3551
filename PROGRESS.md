# RMX3551 / UniXNU bring-up progress

Updated: 2026-11-10 (Asia/Shanghai)

The final goal is to keep iPadOS 18 bootable through the UniXNU reference stack and reach SpringBoard, then repair touch, hardware keys and USB. This file records only behavior confirmed by source, generated device trees, build artifacts or hardware logs.

## Current milestone

| Area | Status | Evidence |
|---|---|---|
| iPadOS userland | Verified | iPadOS 18.7.10 (22H374) reaches SpringBoard with display and software UI usable |
| Display | Verified | `1080x2412 BGRA` framebuffer surface and native home request accepted |
| Keyboard / TextInput | Verified | Native TextInput modes and on-screen keyboard are available |
| S3910 touch | Transport verified; app-info hardware test ready | Stage 3 returned the complete 28-byte identify payload. Commit `326d5ff` fixed a truncated new-file hunk, CI run `42790314382` succeeded, and a new stage-3 image now queries `GET_APPLICATION_INFO(0x20)` immediately after identify |
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

The first real post-ADT blocker is the QUP0 S-AHB branch. `0x80000002` means hardware clock gating is enabled and the branch is idle; it is not a clock failure. The USB driver already treats this exact state as valid. The touch patch now applies the same `clock_state()` rule. It also assigns the GENI transfer function explicitly on success and uses the existing GPIO bit-bang transport when the SM8475 SE4 image exposes only GSI/DMA mode. This mirrors the board-level fallback confirmed on the SM8475 `zizhan` reference while retaining the S3910 TouchComm protocol.

Evidence for this run:

```text
region SHA-256 7c6bd416a74687b5ba24de16584de5a9171c8e68d9a10cffad3843c0c2d13062
log SHA-256    d9f746f129c67ce1fe83ed7924e5be2eaa79c1747d83d72dedf1bf5dc2042992
```


The later stage-3 run reached the chip and returned a valid TouchComm v1
`REPORT_IDENTIFY` header (`a5 10 1c 00`), proving the board pins, power and GPIO
SPI path are live. Its continuation read returned `ff ff ff ff` because the
port read a four-byte header and then requested `payload + 7` bytes immediately.
The vendor S3910 driver instead uses a nine-byte predictive first read, waits
30 microseconds before a continued transfer, and requests only the remaining
message bytes plus the `a5 03` status prefix. The driver now follows that
framing; a host test pins the 28-byte identify packet to a 9-byte first read and
a 26-byte continuation with the padding at byte 25.

The predictive-read hardware run identified the chip and then timed out on
`CMD_GET_APPLICATION_INFO (0x20)`, repeatedly observing `STATUS_BUSY`. The
local driver had inserted `CMD_DISABLE_REPORT (0x06)` with payload `0x23`
before app info. OnePlus' S3910 driver instead calls app info immediately after
identify, and `0x23` is `CMD_GET_DYNAMIC_CONFIG`, not a report ID. The next
stage-3 image removes that extra transaction and records the actual command TX
bytes plus each changed response status for a hardware retest.

The later S3910 driver edits reintroduced the same new-file hunk failure: the
header still declared 1359 lines while `pong_goodix.c` contained 1375, so the
last 16 patch additions, including `#endif /* PONG */`, were omitted. Commit
`326d5ff` corrects the header and adds a host-test check that every new-file hunk
declares its exact added-line count.

The resulting GitHub Actions run `42790314382` completed successfully. The
artifact kernel is 51,933,184 bytes with SHA-256
`0e08505d980fe2ba74978a6af59f63aeed4a6efcd10dda7d8777f9bb2014e0c5`.
It was replaced into the verified stage-3 payload while preserving the ADT and
`unixnu.toml` (`pong_s3910=3`). The boot image for the next hardware check is:

```text
D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-appinfo-326d5ff-42790314382.img
SHA-256 e1d25a7fa0b7ef4caff754127b34126549d4813f02a12bb6fedc65ca41013bca
```

This hardware retest is the only remaining evidence needed before moving from stage 3 to the HID-enabled stage 4.

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

1. Compile and verify the QUP0 clock fix, explicit SPI transport assignment and GPIO fallback.
2. Download `rmx3551-kernel` only after the kernel job succeeds.
3. Rebuild a stage-3 image by applying only the `pong-touch` property patch to the original payload ADT, preserving all other nodes.
4. Verify the embedded TOML still contains `pong_s3910=3`, then boot temporarily with `fastboot -s 9ea882b4 boot`.
5. Decode PongBootLog and require `S3910 QUP0/SE4 source=...`, either GENI `SPI 4 MHz` or `SPI by GPIO`, and a first S3910 response before moving to stage 4.
6. Move to `pong_s3910=4` and HID only after stage 3 identifies the controller with plausible `8640x19296` axes.
