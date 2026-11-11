# RMX3551 / UniXNU bring-up progress

Updated: 2026-11-11 23:20 (Asia/Shanghai)

The final goal is to keep iPadOS 18 bootable through the UniXNU reference stack and reach SpringBoard, then repair touch, hardware keys and USB. This file records only behavior confirmed by source, generated device trees, build artifacts or hardware logs.

## Latest handoff snapshot (2026-11-11 23:20 (Asia/Shanghai))

This snapshot is authoritative. It supersedes earlier text that treated the first cpus=5 attempt as proof that CPU4 could not boot and text that still marked USB hardware verification as pending.

| Area | Current status | Evidence |
|---|---|---|
| iPadOS userland | Verified | iPadOS 18.7.10 (22H374) reaches SpringBoard |
| Touch | Verified usable | The user confirmed clicks work and their positions are not offset. S3910 stage 4 opens HID at `8640x19296`; lag is a performance symptom, not a touch-parse failure |
| USB debug worker | Startup blocker isolated | `liuqin_usb=1` stopped at `PONG APFS: init owner mount hook entered`; the otherwise identical USB-off A/B image completed owner mount, Data mount, launchd, SpringBoard and first frame |
| CPU baseline | Four E cores | The prior `cpus=5` test was invalid because the ADT still contained four CPU nodes |
| CPU experiment | Built, CI in progress | Branch commit `4b4a85e` produces a five-node ADT and matching `cpus=5`, with USB held at zero |
| Software UI | Known bottleneck | `pong_software_ui=1`; CPU topology and Adreno 730 remain separate experiments |
| Touch policy | Frozen during performance work | Do not modify HID, coordinate conversion or touch parsing without a new touch-specific regression |

### USB A/B result

The original `de4d4e1` CI image retained `liuqin_usb=1` and stopped at the APFS owner-mount hook. The A/B image changed only that worker and reached the desktop:

```text
PONG APFS: init owner mount hook returned error=0 stage=6
PONG APFS: Data mount PASS ... rw=1
MiniIOMobileFramebuffer: first visible frame
MiniIOSurface: SpringBoard[27] created surface 7: 1080x2412 'BGRA'
S3910 identified ... axes=8640x19296
s3901: finger 0 down ...
Pong touch HID: type=1/2/3 ...
```

Evidence:

```text
D:\unixnu\ud\diagnostics-usboff-ab-de4d4e1-20261111-230948
ponglog-region.bin  4198400 bytes  sha256 9fd2f1444469930d4cf7753f5d7b3ec76015e3efbc389a72e703d34f1368e465
ponglog.txt          119989 bytes  sha256 50fa7cdaaa63eb0d3a202156358c5eabe1f84315e3c3dba35e4f100519689fa1
```

The USB-off A/B image is:

```text
D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-usb-launchd-stage4-de4d4e1-43039154889-usboff-ab.img
102699008 bytes
sha256 be391852b0ff9bedaa8681bea3a3c7494e2f0102f2d69cd445fdd49532332214
```

Use `liuqin_usb=0` as the stable base for every performance experiment until the worker gets dedicated instrumentation.

### Strict five-core experiment

The earlier `cpus=5` result did not test CPU4 because the log still reported four registered CPUs. Independent branch `exp/strict-cpus5-usboff` commit `4b4a85e` now changes the ADT count, the boot argument and the verification count to five while keeping `liuqin_usb=0`. It leaves the S3910 code untouched.

Local verification produced:

```text
ADT     15708 bytes  sha256 9b85cb8c59b7ab67ae774ca77e084c809e5dd96057c4429ca095242fdcb986a2
payload             sha256 ec6957a25ef61d7b76c6cf5d01c38bbe828fd086b159eb09648c3e9bbd0e267e
boot args           cpus=5, liuqin_usb=0
ADT checks          cpu_count=5, trust-cache=1, touch axes=8640x19296
```

Candidate image:

```text
D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-cpus5-adtsync-usboff-de4d4e1-20261111.img
102699008 bytes
sha256 a458b470978ea70f074a945b5f145e36e57665ad17470737a6fbb045c0fecf21
```

GitHub Actions run `43047204050` was triggered by this exact commit and was queued when this snapshot was written.

Acceptance requires all of:

```text
ArmDTPlatform: registered platform cpus=5
ArmCpu: CPU 4 MPIDR=0x400 registered
ArmCpu: CPU 4 first boot completed
```

Only then should the project proceed to an A510/A710-X2 two-cluster topology test. A failure must be retained as new PongBootLog/panic evidence, not merged with the old four-node experiment.

### Method rules

1. One experimental variable per boot.
2. The boot argument CPU count and ADT CPU-node count must agree before the image is useful.
3. USB remains off while measuring CPU/UI performance.
4. GPU bring-up and CPU topology are separate projects.
5. The verified touch path stays frozen during performance work.

### Safety boundary

- Target serial is `9ea882b4` only.
- Never operate `42d72758 / OPD2515`.
- Every ADB/fastboot command must include `-s 9ea882b4`.
- Only temporary `fastboot -s 9ea882b4 boot <image>` is allowed.
- Never flash `boot` or `userdata`; never run `fastboot -w`.
- Never run `git reset`, `git clean` or `git add .`.
- Never overwrite the desktop baseline or `rmx3551-uefi-baseline.img`.

---

## Historical snapshot (2026-11-11 17:03 Asia/Shanghai)

This new snapshot is authoritative. The historical sections below are retained, but statements that stage 3 was pending or HID was unverified are superseded.

| Area | Current status | Evidence |
|---|---|---|
| iPadOS userland | Verified | iPadOS 18.7.10 (22H374) reaches SpringBoard |
| Touch | Basic end-to-end pass | stage 3 app-info/report-format/identify checks passed; stage 4 opens HID at `8640x19296` and `60 Hz`; CPU3 and CPU4 logs each contain four real touch events with no coordinate offset |
| CPU | cpus4 verified, cpus5 failed without a new log | CPU0–3 complete first boot on cpus4. The first cpus5 attempt failed on hardware, and the post-failure userdata log region is byte-identical to the cpus4 evidence, so it contains no CPU4 first-boot proof |
| Current best measured UI | cpus4 | retained cadence windows total about 9.409 FPS, with the last two around 10.2 FPS |
| Boot packaging | Hardware pass | The `ff3d025` image crossed DarwinBoot and reached the kernel, launchd and SpringBoard. The payload/ADT TrustCache handoff defect is closed |
| Next engineering step | Correlate the reported blank or stalled display with framebuffer/scanout state | The device ran for many minutes, created a 1080x2412 SpringBoard surface and emitted real S3910 HID events. Frame cadence later collapsed for long periods. Do not reopen TrustCache or touch parsing from this evidence |
| RAM | 4 GiB managed | `Pong RAM: 1 owned banks, 4096 MiB managed`; the roughly 7 GB APFS Data volume is not physical RAM |
| GPU | Deferred | `pong_software_ui=1` remains in use; Adreno 730 needs a separate platform bring-up |
| USB debug startup | CI pass, hardware verification pending | The `ff3d025` CI image panicked at `io_map` inside `liuqin_usb_debug_start`. Commit `29d45d9` moved the real MMIO/DMA work to a worker created only after successful `IOKitBSDInit()`. CI `42989774583` passed |

### 2026-11-11 USB debug startup-order repair

The `ff3d025` CI image reached the kernel but panicked with this visible call chain:

```text
kmem_alloc_guard_internal
io_map
liuqin_usb_debug_start
bsdinit_task
```

The screenshot and symbol/source evidence are in
`D:\unixnu\ud\panic-ff3d025-ci-42981426332-20261111`. The packaging was not at fault:
the old driver performed `ml_io_map()` synchronously from `bsdinit_task()` before the VM page
structures and IOKit initialization were ready, so the mapping returned `KERN_NO_SPACE`.

Commit `29d45d9` removes that call from `bsdinit_task()`. It calls
`liuqin_usb_debug_start()` from `bsd_autoconf()` only after `IOKitBSDInit()` returns
`KERN_SUCCESS`. The start routine now creates one kernel worker and leaves immediately. The
worker owns every `liuqin_io_map()`, DMA allocation and controller register access, then
terminates itself. A host regression test checks this split, and the CI workflow now runs
preflight before downloading the multi-gigabyte Apple components.

The Windows-local preflight false failures were also fixed. It now writes normalized shell text
to a temporary file and invokes `wsl.exe --exec /bin/bash -n <path>` instead of feeding a Bash
program through WSL stdin. All six preflight passes, the USB startup-order test and the S3910
protocol host test pass locally.

GitHub Actions run `42989774583` completed successfully. Artifact id `13842295410`:

```text
zip          23348678 bytes  sha256 031bf7ecf32841b350d54ebd796f550451137b81beffdc1a73fe86fe325e388c
ADT             15444 bytes  sha256 1de68c1b46b922c43c302d526215a0ef403c4b529942bbe78890e2efe126b7bb
payload.img 100663296 bytes  sha256 22fdd119555c35324c1d898393cf82e49482c28eb2dadda3e5eac4ea0e052f4c
kernel.macho 51949568 bytes  sha256 a4236c2e57c27e0939ec6258729338c40dd7b6bdd8d6e7fc6dfc6dccba2f83fb
```

Independent verification passed with `--cpus 4 --trust-cache`: touch axes remain
`8640x19296`, `TrustCache` is present, and the UFS SMMU stream remains `0xe0`. The payload
kernel arguments still contain `pong_s3910=4`, `liuqin_usb=1` and
`liuqin_usb_smmu=2`.

The new temporary boot image was assembled on top of the unchanged
`rmx3551-uefi-baseline.img`:

```text
D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-usbworker-stage4-29d45d9-42989774583.img
bytes   102699008
sha256  ea041eb3e104829adf5ae4eb689b82f6a9bddda842c8483d7ab609be5fcb1ba4
```

Independent parsing confirmed that only the boot header ramdisk-size field and payload region
changed. The embedded FAT matches the artifact byte-for-byte, and its PONGFAT1 CRC32 is
`0xcf27f9e9`.

Target identity was checked as `9ea882b4 / ovaltine / twrp_ovaltine` in recovery and
`serialno=9ea882b4 / product=taro` in fastboot. Only the following temporary boot command was
used:

```text
fastboot -s 9ea882b4 boot D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-usbworker-stage4-29d45d9-42989774583.img
```

Both `Sending` and `Booting` returned `OKAY`. Hardware logs are still pending, so this section
records a successful build and boot handoff, not a completed USB or touch hardware verdict.

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
`product=taro` in fastboot. Only temporary `fastboot -s 9ea882b4 boot` was used.

### 2026-11-11 15:54 `ff3d025` hardware result

The decoded PongBootLog is at:

```text
D:\unixnu\ud\diagnostics-s3910-stage4-trustcache-ff3d025-20261111-155103
region    4198486 bytes  ac8316d1fdd9827ef94e6dbc10f388d515a57cba5559a59998c7cffcf977084b
log        186535 bytes  ebd3297f224a9b39682aba4709cd71581ae02fb676cc11892f0e5f0de743c72f
clean bin 4198400 bytes  de22a3b2947bee734d6f16b198af4f9a557672433c345204c3a820c89a7b60bb
clean log  184804 bytes  ebd3297f224a9b39682aba4709cd71581ae02fb676cc11892f0e5f0de743c72f
```

The first archive contained 86 bytes of device-side `dd` stderr/statistics. A second `exec-out` pull discarded stderr and produced exactly 4,198,400 bytes. It decoded to the same text hash, so the conclusion is independent of that extraction artifact. The snapshot header still says `status 2` and warns that it may be torn, but the complete boot chain is present and repeated consistently.

Observed evidence:

```text
Darwin Kernel Version 24.6.0
S3910 identified ... axes=8640x19296
Pong touch HID: display-integrated digitizer opened
Pong UI18: screen native=1080x2412 logical=360.00x804.00 scale=3.00
MiniIOMobileFramebuffer: first visible frame; releasing boot console
MiniIOSurface: SpringBoard[27] created surface 7: 1080x2412 'BGRA'
Pong touch HID: type=1 finger=0 xy=22664,30661
```

Before the touch event the framebuffer reported roughly 9–18 FPS. After it, cadence fell to 1 FPS and 0 FPS for long windows and later recovered sporadically. There is no DarwinBoot refusal or kernel panic. The user reported that the device did not appear to boot, so the unresolved symptom is now visual presentation or scanout stability, not the TrustCache packaging regression.

Commit `ff3d025` changed only the TrustCache ADT handoff, generator, finalizer, verifier, CI and preflight. It did not change framebuffer, touch HID, coordinate conversion, contact parsing, CPU count or kernel code.

The log is from a fresh run rather than the previous cpus4 snapshot: the new header is `sequence 255`, `tick 2181`, with `pmap_startup` at 749,405 microseconds. The previous ring was `sequence 27`, `tick 45`, with `pmap_startup` at 770,232 microseconds.

One observation confounder remains. The current 22H374 compatibility layer calls
`preventIdleSleepForNumberOfSeconds: 300` from `userland/ui_compat18.c`, so it keeps idle sleep away for only about
five minutes. The old instruction to wait four to five minutes before returning to TWRP lands at the edge of that
window. The later log still shows live system services while frame updates become sparse. That is consistent with
either a sleeping/static SpringBoard or a display fault, and this log alone cannot distinguish them.

The next visual test must observe at 30–60 seconds, record whether the lock screen or desktop appeared, then wait for
the display to change. If it goes dark, touch it and allow at least 30 seconds for wake. A pure display failure is
only established when the UI never appears and touch wake does not restore it.

### `ff3d025` CI artifact

GitHub Actions run `42981426332` completed successfully at 15:57:01 Asia/Shanghai. The ADT finalization and upload verification steps both passed.

```text
artifact id     13838875421
artifact        rmx3551-kernel
zip bytes       23346876
zip SHA-256     15bbb48041a9d0bd0afdd707061fba417fb207b9a4420414682dd6bf10f387bb
extracted root  D:\unixnu\UniXNU-rmx3551\out\ci-ff3d025-42981426332
ADT             15444 bytes     2586053ae57f16aae65b29a0860d5e83062cf33ef9377ef9226ee5b81b255634
payload.img     100663296 bytes d095ee3e17a65bd9092e1a8cbd66a4cd7c8fab667f0270622ba788849f52a965
kernel.macho    51949568 bytes  8e9569c2045e29bad99b384717bfecc5a0758e01c04acbad6d94ca692832d591
```

Independent verification passed with `--cpus 4 --trust-cache`: `trust-cache=1`, touch axes `8640x19296`, UFS stream `0xe0`. A new official-named candidate was packed without replacing any baseline:

```text
D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-stage4-trustcache-ff3d025-42981426332.img
bytes   102699008
sha256  bdbc301db56c8a0988103382c03a350bab1a920bb36f00d09b3d3cbc3777398a
```

This CI-derived candidate has not yet been booted. The local `f0079848...baa07` image remains the hardware-validated artifact for the current boot-chain result.

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
