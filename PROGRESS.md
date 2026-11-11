# RMX3551 / UniXNU bring-up progress

Updated: 2026-11-11 15:52 (Asia/Shanghai)

The final goal is to keep iPadOS 18 bootable through the UniXNU reference stack and reach SpringBoard, then repair touch, hardware keys and USB. This file records only behavior confirmed by source, generated device trees, build artifacts or hardware logs.

## Latest handoff snapshot (2026-11-11 15:52 Asia/Shanghai)

This new snapshot is authoritative. The historical sections below are retained, but statements that stage 3 was pending or HID was unverified are superseded.

| Area | Current status | Evidence |
|---|---|---|
| iPadOS userland | Verified | iPadOS 18.7.10 (22H374) reaches SpringBoard |
| Touch | Basic end-to-end pass | stage 3 app-info/report-format/identify checks passed; stage 4 opens HID at `8640x19296` and `60 Hz`; CPU3 and CPU4 logs each contain four real touch events with no coordinate offset |
| CPU | cpus4 verified, cpus5 failed without a new log | CPU0–3 complete first boot on cpus4. The first cpus5 attempt failed on hardware, and the post-failure userdata log region is byte-identical to the cpus4 evidence, so it contains no CPU4 first-boot proof |
| Current best measured UI | cpus4 | retained cadence windows total about 9.409 FPS, with the last two around 10.2 FPS |
| Boot packaging | Source fix complete, hardware retest pending | The `311b89e` ADT omitted `/chosen/memory-map/TrustCache` while its payload carried `kernel.macho.trustcache`, so DarwinBoot returned `EFI_COMPROMISED_DATA`. Commit `ff3d025` emits, preserves and verifies the 16-byte slot |
| Next engineering step | Confirm the repaired boot on the target | Boot the `ff3d025` repair image, recover a new PongBootLog and confirm stage-4 touch. Do not return to cpus5 or USB work until this regression is closed |
| RAM | 4 GiB managed | `Pong RAM: 1 owned banks, 4096 MiB managed`; the roughly 7 GB APFS Data volume is not physical RAM |
| GPU | Deferred | `pong_software_ui=1` remains in use; Adreno 730 needs a separate platform bring-up |

### 2026-11-11 TrustCache handoff repair

The `311b89e` stage-4 image stopped at the UniXNU menu with:

```text
DARWINBOOT: boot refused: Compromised Data; firmware retained
```

The payload contained a real 70,116-byte `kernel.macho.trustcache` with SHA-256
`cc4f5079fafbb81cf32f54718666461630381972867428e13c6e8a906b58d7cd`, but the finalized ADT had no
`/chosen/memory-map/TrustCache` property. DarwinBoot reads the file first and rejects the ADT when the matching
16-byte zero slot is absent. The old bootable ADT had that slot, so this is a packaging contract bug rather than a
touch, CPU, CRC or memory-map hardware failure.

Commit `ff3d025` (`fix: restore TrustCache ADT handoff`) adds the slot generator, makes the finalizer require and
record the payload's trust cache, makes the ADT verifier require the slot explicitly, and places that verification in
CI and preflight. The PongBootLog reader now requires `--serial` and always invokes `adb -s <device>` so recovery
commands cannot silently target the other attached phone.

A finalizer run against a copied `311b89e` payload and hardware DTB produced:

```text
ADT bytes          15444
ADT sha256         99fdf666600b7a4723eb00f7b0db45c40ebbec6559294bba7f7f5f77193d4e63
TrustCache bytes   70116
TrustCache sha256  cc4f5079fafbb81cf32f54718666461630381972867428e13c6e8a906b58d7cd
embedded TOML      cpus=4 + pong_s3910=4
verifier           PASS (trust-cache=1, touch axes=8640x19296)
```

The local temporary boot image, built by replacing only the payload slot in the known stage-4 UEFI container, is:

```text
D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-stage4-trustcache-ff3d025-local.img
bytes   102699008
sha256  f0079848126af0f2550f14ce7ca6e5f4c40b6cacc956ca43346317a7731baa07
```

Target identity was verified as `9ea882b4 / ovaltine / twrp_ovaltine` in recovery and `serialno=9ea882b4`,
`product=taro` in fastboot. The temporary `fastboot -s 9ea882b4 boot` completed with Sending and Booting `OKAY`.
No new PongBootLog or stage-4 touch observation is claimed yet. CI run `42981426332` was triggered from `ff3d025`
and must finish before its artifact can replace this local boot check.

### CPU progression

| CPUs | Result | Visible cadence | Image SHA-256 |
|---:|---|---|---:|
| 1 | CPU0 boots, SpringBoard reached | about 2.736 FPS | `96b93111553aafb8dd514f106583c5f8357c62b282223cfd2b5e68c7952bb819` |
| 2 | CPU0–1 boot, SpringBoard reached | about 6.124 FPS | `5d8000662ac4b9b54c833a2a59c27ae24c1c2796d4f59622e0661f37900b04e9` |
| 3 | CPU0–2 boot, no kernel panic | about 4.887 FPS across an 82.254 s short window | `0d3f86889c5c1c4b42282aa43337f661efc90f0729a5f62e4581fa5c0f89578f` |
| 4 | CPU0–3 boot, no kernel panic | about 9.409 FPS across retained windows | `190ced0decb0bb78e0939ae442483432c642af2a25c50fd6987f256a4dae6efe` |
| 5 | boot failed; no new PongBootLog, so CPU4 first boot is not proven | no valid new log | `57f2118bf3fc44160aa3a9d0d4ce505096221e233d3f128d33f1b0bd463c996b` |

The CPU4 log contains:

```text
ArmCpu: CPU 1 MPIDR=0x100 registered
ArmCpu: CPU 2 MPIDR=0x200 registered
ArmCpu: CPU 3 MPIDR=0x300 registered
ArmCpu: CPU 0 first boot completed
ArmCpu: CPU 1 first boot completed
ArmCpu: CPU 2 first boot completed
ArmCpu: CPU 3 first boot completed
ArmCpu: all registered CPUs available; idle preference X2, A710, A510 (no affinity binding)
```

The DTS labels CPU0–3 as the A510 E cluster and CPU4–7 as the A710/X2 P cluster. cpus4 therefore improves throughput by enabling four E cores, but it does not yet activate any P core. cpus5 is the first configuration that introduces an A710 into the running set, and that configuration failed on hardware before writing a new PongBootLog.

Existing userland errors remain in the logs, including Biomed and thread-count watermarks, AccessibilityUIS `EXC_RESOURCE`, and `BlastDoor cannot run unsandboxed`. They are not evidence that CPU first-boot or touch initialization failed.

The cpus4 and cpus5 images are both 102,699,008 bytes and differ in exactly five bytes: the ASCII `cpus=4` to `cpus=5` byte at `0x34504e6` and four PONGFAT1 CRC bytes at `0x1f0018` through `0x1f001b`. Both stored PONGFAT CRCs match the calculated FAT CRC, so image packaging corruption is unsupported by the artifact evidence. The visible menu does not prove that the kernel was never entered: the boot screen already contains `DARWINBOOT: hand-off to the kernel`, and the loader does not clear that menu overlay. Use an earlier runtime observation point instead of treating the missing PongBootLog as proof of a menu-stage failure.

### Evidence

```text
cpus3 directory D:\unixnu\ud\diagnostics-s3910-stage4-cpus3-20261110-232912
region SHA-256 d608f5735a8766f7f3c3a8fa2803ee7a051fce9eb95e7f166b9a7386c9002913
log SHA-256    e1155db66374e57b41789c1745f44789fd4bbb91fe63d23066708c8778607785

cpus4 directory D:\unixnu\ud\diagnostics-s3910-stage4-cpus4-20261110-233348
region SHA-256 5320ebb913955f694267ae72cbce2376fa6c7926ba05d2749c1b8a154e25cb7c
log SHA-256    5a86620c7b327c74a8dbe3d62bc34a358a2b628947cbe81e9b82c95ca6884dfe

cpus5 failed-attempt readback D:\unixnu\ud\diagnostics-cpus5-failed-20261110-235025
region SHA-256 5320ebb913955f694267ae72cbce2376fa6c7926ba05d2749c1b8a154e25cb7c
log SHA-256    5a86620c7b327c74a8dbe3d62bc34a358a2b628947cbe81e9b82c95ca6884dfe
both files are identical to the cpus4 evidence and are not cpus5 runtime evidence
```

Repository HEAD is `81e7063` and the successful CI run is `42827300826`. CPU-count variants were derived locally from the same CI image by changing only the `cpus=N` byte and the PONGFAT1 CRC32, so there is no separate CI run for each variant.

### Next actions

1. Locate the cpus5 failure stage before testing another CPU topology or changing scheduler code.
2. Treat LIUQIN USB CDC as the preferred early-boot observability project because it streams the kernel console and exposes `status/replay`. Its documented blocker is the SMMU route, so controller and DMA operation remain unverified. Do not start cpus6 or cpus8 until cpus5 runs far enough to produce evidence.
3. Adapt the official `zzyf-sheng-amp.patch` to Darwin 24 after at least one P core is stable. Set `MAX_CPU_CLUSTERS=2`, define `__ARM_AMP__`, preserve the DTS E/P annotations, and prefer X2/A710 for UI and user-initiated work.
4. Audit background CPU consumers such as `coreduetd` only after the cluster scheduler baseline is understood.
5. Defer Adreno 730 and multi-bank 12 GB RAM work until CPU/Edge scheduling is stable.

### Safety boundary

- The only valid target is `9ea882b4` with TWRP identity `ovaltine / PGP110 / twrp_ovaltine`.
- Never operate on `42d72758 / OPD2515`.
- Every ADB or fastboot command must include `-s 9ea882b4`.
- Use temporary `fastboot boot` only.
- Do not flash `boot` or `userdata`, do not run `fastboot -w`, `git reset`, or `git clean`.
- Do not overwrite the verified desktop baseline `D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-usbdebug-22e7b2c-42510630419.img` with SHA-256 `9574063d753bda2b190693aa720cd6d08c5dcfa7bc79ae03f17fff40a9c7cb63`.

## Historical milestone (before 2026-11-10 23:40)

| Area | Status | Evidence |
|---|---|---|
| iPadOS userland | Verified | iPadOS 18.7.10 (22H374) reaches SpringBoard with display and software UI usable |
| Display | Verified | `1080x2412 BGRA` framebuffer surface and native home request accepted |
| Keyboard / TextInput | Verified | Native TextInput modes and on-screen keyboard are available |
| S3910 touch | `0x20` verified; post-app-info stage-3 retest ready | Stage 3 returned the complete 28-byte identify payload and `GET_APPLICATION_INFO(0x20)` returned 46 bytes with success. Commit `5820fa6` removes an invalid `0x24` dynamic-config transaction; CI run `42794829937` succeeded. The corrected stage-3 image has not yet been booted, and HID remains disabled |
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

That image produced the application-info evidence below and exposed one invalid post-app-info transaction, which the later sections record.

## 2026-11-10 17:50 S3910 application-info hardware retest

The `326d5ff` stage-3 image reached the real S3910 and produced the following
sequence:

```text
Pong touch: S3910 command 0x20 tx: 20 00 00
Pong touch: S3910 command 0x20 reply[0] code=0x1 length=46

Pong touch: S3910 command 0x6 tx: 06 01 00 11
Pong touch: S3910 command 0x6 reply[0] code=0x1 length=0

Pong touch: S3910 command 0x24 tx: 24 03 00 11 02 00
Pong touch: S3910 command 0x24 reply[0] code=0xf length=0 detail=0xfa5
Pong touch: S3910 identify failed rc=-5 stage=reply detail=15 version=1 command=0x24
```

This proves `CMD_GET_APPLICATION_INFO (0x20)` now succeeds. The previous
`STATUS_BUSY` failure is gone. The remaining failure was local protocol misuse:
the driver treated touch report ID `0x11` as a dynamic-config ID and sent
`SET_DYNAMIC_CONFIG (0x24)`, so the controller correctly returned
`STATUS_ERROR (0x0f)`. Command `0x23` is `GET_DYNAMIC_CONFIG`; it is not
`DISABLE_REPORT`, which is command `0x06`.

Commit `5820fa6` removes the two invalid dynamic-config transactions and keeps
the official initialization order:

```text
IDENTIFY (0x02)
GET_APPLICATION_INFO (0x20)
DISABLE_REPORT (0x06, report 0x11)
SET_TOUCH_REPORT_CONFIG (0x26)
GET_TOUCH_REPORT_CONFIG (0x25)
ENABLE_REPORT (0x05, report 0x11)
```

The host protocol test and `git diff --check` pass. GitHub Actions run
`42794829937` completed successfully. Artifact `13754321750` is 23,334,193 bytes
with ZIP SHA-256
`809f1987bded56751a9229e03a8d1a6e73afaf1b2b24d960882531b83bbf1dad`.
The extracted `kernel.macho` is 51,933,184 bytes with SHA-256
`3b92f02ee7b4d36e4bb71d206d8a079fb8f1ca2c245e3702cbb8fe6417ca6a97`.

That kernel was inserted into the verified stage-3 payload without changing the
ADT or TOML. The new diagnostic images are:

```text
payload:
D:\unixnu\UniXNU-rmx3551\out\payload-s3910-appinfo-clean-5820fa6-42794829937.img
SHA-256 9e0d7c430cde3ac0ba719c6a86a6e8eae00db26ce1e2b6b01a09a2efdb8656db

boot:
D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-appinfo-clean-5820fa6-42794829937.img
SHA-256 fcb3d801fe02a87093114f5b2c4fe102c182528a633b22b24f648b82b9e04875
```

The boot image preserves `pong_s3910=3`, so HID is intentionally disabled even
if the controller initialization finishes. This image has not yet been booted.
The next run must stop only the target serial `9ea882b4` and pass this exact
failure point before the TOML moves to `pong_s3910=4`. A stage-3 pass requires:

```text
Pong touch: S3910 app info ... axes=8640x19296 ...
Pong touch: S3910 touch report disabled; applying format
Pong touch: S3910 identified ... axes=8640x19296 ...
Pong touch: S3910 stage 3 complete; HID publication disabled
```

At handoff time no ADB or fastboot device was detected, so the image is ready but
the hardware result is still unknown.

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

## Historical next actions (superseded by the latest snapshot)

1. Compile and verify the QUP0 clock fix, explicit SPI transport assignment and GPIO fallback.
2. Download `rmx3551-kernel` only after the kernel job succeeds.
3. Rebuild a stage-3 image by applying only the `pong-touch` property patch to the original payload ADT, preserving all other nodes.
4. Verify the embedded TOML still contains `pong_s3910=3`, then boot temporarily with `fastboot -s 9ea882b4 boot`.
5. Decode PongBootLog and require `S3910 QUP0/SE4 source=...`, either GENI `SPI 4 MHz` or `SPI by GPIO`, and a first S3910 response before moving to stage 4.
6. Move to `pong_s3910=4` and HID only after stage 3 identifies the controller with plausible `8640x19296` axes.
