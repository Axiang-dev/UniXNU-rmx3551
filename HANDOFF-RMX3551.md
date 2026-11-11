# RMX3551 · UniXNU / iPadOS 18 移植交接文档

> 用户最终目标保持不变：**参考 UniXNU 官方仓库和文档，成功启动 iOS 并进入桌面**。
> 2026-11-11：`ff3d025` 的 TrustCache handoff 已通过实机验证，系统越过 DarwinBoot 并进入内核、SpringBoard，S3910 stage-4 也持续产生真实 HID 触点。当前需要区分“设备实际没有启动”和“系统已运行但画面/帧更新不可见”，不得继续按启动封装错误排查。
> 17:03：USB 调试口在 `ff3d025` CI 镜像上又暴露了启动顺序 panic；`29d45d9` 已把 worker 创建移到 IOKit 初始化成功后，CI `42989774583` 全绿。
> 2026-11-12 00:37：五核启动、APFS、SpringBoard 和触摸通过。六核和七核都完成 CPU first boot，但都停在同一个 APFS UUID 等待，因此继续加核的路线关闭。当前转向五核稳定基线排除诊断日志回写和连续 applog 对 UI/UFS 的干扰。


初次写作：2026-11-08 15:30（GMT+8）。最近更新：2026-11-12 00:37 (Asia/Shanghai)。
接手者先读本页新的「最新接手快照」。其后的历史段落只用于追溯，其中可能仍写着 stage 3 待测、HID 未验证或旧的五核失败结论。

接手核验（2026-11-08，GMT+8）：已只读提取设备日志与用户态库，证据在
`D:\unixnu\ud\diagnostics-20261108-154736`。旧运行未启用快照，但设备上的
`libpong-ui18.dylib` 已包含探针；准备好的 boot 镜像与产物元数据哈希一致。
已完成一次临时启动，取得 7 个进程的 35s/90s 共 14 份快照，证据在
`D:\unixnu\ud\diagnostics-snapshot-20261108-1555`，内核日志 CRC 正确。
SpringBoard 两次采样均阻塞于 LaunchServices 数据库请求；backboardd 的 90s 样本也在
同一等待链。lsd 的服务线程明确等待数据库 seeding，注册线程则仍在执行应用注册。
目前仅能确定首帧之前的实际等待链，尚不能判断 seeding 慢或永久停滞。
16:01 已再次临时启动同一镜像，进行约 20 分钟观察。以下日志路径、符号化和 Wi-Fi
说明已根据实际源码、APFS 目录及匹配 UUID 的符号文件纠正。

---

## 最新接手快照（2026-11-12 00:37 (Asia/Shanghai)；本段优先）

### 一句话状态

系统桌面、S3910 stage 4 触摸和真实 HID 触点均已通过实机验证，用户确认点击位置没有错位。当前瓶颈仍是 `pong_software_ui=1` 下的软件 UI 性能。五核是唯一完成“CPU 注册、APFS Data mount、SpringBoard、触摸”全链路验收的版本。六核和七核都完成了 CPU 注册与 first boot，随后停在同一个 APFS UUID 等待，不能算启动成功。继续增加 A710 的路线因此关闭。

### 五核稳定基线

五核镜像已经通过完整启动验收：

```text
D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-cpumask-1f-usboff-adt5-de4d4e1-20261111-235152.img
102699008 bytes
sha256 d41715fc16763835066185b1b5fc04292d3790545579507e784f2e0219c69441
```

实机日志确认 CPU0–3 的四个 A510 和 CPU4 的首个 A710 注册并完成 first boot，随后继续通过 `Data mount PASS` 并进入 SpringBoard。触摸可用且无坐标错位。

```text
D:\unixnu\ud\diagnostics-cpumask-1f-20261111-235658
ponglog-region.bin 4198400 bytes
sha256 17a71915bf0f43db41711739d66fe6f22f049993e290f0142aa31283f6bca8ee

ponglog.txt 191969 bytes
sha256 f5eef262350cdf3dd9cb8195a2a1408967be9923f435926d05cc6e7e42bba1c1
```

这是后续性能实验必须回归的启动基线，不得覆盖或删除。

### 七核隔离结果

七核镜像来自提交 `932c4c9`，对应 CI run `43054006667`：

```text
D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-cpumask-7f-usboff-adt7-932c4c9-20261112-000205.img
102699008 bytes
sha256 c106d7b8508584a66d0f991348943891d94c7fee7b968953460c18b5b37b8b99
```

封装回读确认：

```text
ADT 16236 bytes
ADT cpus=7
ADT trust-cache=1
touch axes=8640x19296
boot args cpumask=0x7f, liuqin_usb=0, pong_s3910=4
PONGFAT1 CRC 0xc58cc023
```

实机日志确认：

```text
ArmCpu: CPU 4 MPIDR=0x400 registered
ArmCpu: CPU 5 MPIDR=0x500 registered
ArmCpu: CPU 6 MPIDR=0x600 registered
ArmCpu: CPU 4 first boot completed
ArmCpu: CPU 5 first boot completed
ArmCpu: CPU 6 first boot completed
ArmDTPlatform: registered platform cpus=7
```

UFS 发布三张磁盘，APFS 找到稳定 checkpoint，但没有出现 `Data mount PASS` 或 SpringBoard。启动停在：

```text
IOPropertyMatch UUID B07DF049-7AD9-47B5-9F8F-9EE728056398
```

七核结论是“CPU 注册成功，系统启动验收失败”。不能把 CPU first boot 当成整体成功。

```text
D:\unixnu\ud\diagnostics-cpumask-7f-20261112-000850
ponglog-region.bin 4198486 bytes
sha256 52bc94e498902c8d2c5b8a89c2580c7c87a74b93ee47c895f3b45a5c2afc54e4

ponglog.txt 12566 bytes
sha256 0e6b0aab0e451a3bc7b44b1a2e3b6cbc59de2e018c862683029970e968c20ae1
```

### 六核隔离结果

六核镜像只引入 CPU5，即第二颗 A710，同时排除 CPU6：

```text
D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-cpumask-3f-usboff-adt6-932c4c9-20261112-000940.img
102699008 bytes
sha256 99d449891f9ab7d37e23ab3f0f35d13f77706fed3488414272639b32d2fe56f3
```

实机串号确认为 `9ea882b4`，ADB 状态为 `recovery`，设备为 `ovaltine`，TWRP 为 `3.7.0_12-Alpha`。日志确认：

```text
ArmCpu: CPU 4 MPIDR=0x400 registered
ArmCpu: CPU 5 MPIDR=0x500 registered
ArmCpu: CPU 4 first boot completed
ArmCpu: CPU 5 first boot completed
ArmDTPlatform: registered platform cpus=6 arm-io=1 devices=4 nvram-proxy=1
```

系统随后再次停在：

```text
IOPropertyMatch UUID B07DF049-7AD9-47B5-9F8F-9EE728056398
```

日志没有 `PONG APFS: Data mount PASS`，没有 SpringBoard surface，也没有 `first visible frame`。五六核的共同分界因此是 CPU5 是否加入。六核和七核都在 CPU5 加入后失败，CPU6 不是必要条件。继续增加 A710 核数的实验终止。

```text
D:\unixnu\ud\diagnostics-cpumask-3f-20261112-003100
ponglog-region.bin 4198486 bytes
sha256 b535648c567c71c5fd55ad0445645d84e05f59d74be8d51e7c99a1f7c5fa0578

ponglog.txt 12376 bytes
sha256 26b35939fc0a67b62b353498fb4244a5ec38212976ad7ce5f420bc16246612ca
```

### 性能诊断开销 A/B

五核日志显示帧驱动本身每帧约 2 ms，但窗口总吞吐只有约 8.46 FPS，且出现 23.2 秒仅有 11 帧的停顿。GPU 等待记录约 1 us，当前证据更支持 CPU/软件合成、UFS 争用和诊断路径，而不是 GPU fence 阻塞。

现有诊断镜像同时开启 `pong_bootlog=1`、`applog=1`、`fbtrace=8`、`surftrace=24` 和 `pong_boot_snapshot=1`。`PongBootLog` 会在内容变化时把最多 4 MiB 内核镜像同步写回 userdata，循环周期为 2 秒。为隔离这一项，已从五核成功镜像制作严格单变量性能候选，只把 TOML 与 manifest 中的 `pong_bootlog` 从 `1` 改为 `0`：

```text
D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-cpumask-1f-usboff-adt5-de4d4e1-20261111-235152-bootlogoff.img
102699008 bytes
sha256 786e9a84091ffc15c491f0b6b0593a8f58a8344b25822f4ccaccde1bb27ac931
```

回读保留 `cpumask=0x1f`、`liuqin_usb=0`、`pong_s3910=4` 和 `pong_software_ui=1`。fastboot 已明确返回 `serialno: 9ea882b4`，并且只执行临时启动。实机卡顿对比尚待用户反馈。由于该镜像关闭 PongBootLog，失败时不能从 userdata 取本轮日志。

### 音量键 HID 修复

实机日志已经证明物理按键扫描正常：

```text
Pong keys: arbiter v7 channels=768 PON=407 GPIO6=434
power=1 up=1 down=1
Pong keys HID: key=1 down=1 sent=1
Pong keys HID: key=2 down=1 sent=1
Pong keys HID: physical side consumer opened
volume report device=unavailable
```

电源键走虚拟服务事件，因此可用。音量键依赖 `IOHIDUserDeviceCreate()`，而当时内核没有预链接 `IOHIDFamily` 和 `IOHIDEventDriver`，所以报告设备为空。

提交 `94f0aaf007d4d33e6d4eb909431f7f740f5c8cdc` 已推送到 `exp/strict-cpus5-usboff`：

- `kernel.yml` 增加 `IOHIDFamily` 与 `IOHIDEventDriver` 两个预链接根。
- 合并 `configs/pong-hid-match.json`，让 PMIC Consumer 使用非延迟 `IOHIDEventDriver`。
- `emit_prelink.py` 增加显式、可审计的 `--personality-json BUNDLE=PATH`。
- 新增 `tests/test_rmx3551_hid_prelink.py`，阻止 workflow 再次漏掉 HID 栈。

本地 `python -B scripts\preflight.py` 六项通过。Porting CI run `43055703760` 成功。Kernel CI run `43055703607` 也已成功，artifact `13871639513` 已下载核验：

```text
artifact zip sha256 ed0c3a761c03a2fd6a779816d8701dfd9ddd3233fb005826bb14cb3d64f7594a
kernel.json       sha256 13e8cd42fce9429a46e23ee420d433590bedd6c021e2804f82a59d3500877e06
kernel.macho      sha256 8de80c7d69499468074623c9d31301f680bca821b67684f4dba8607d0edc2a8b
payload.img       sha256 8e3cb79eeb036e6bcf9f173a7c23da3a993cbdfd2d3fd3bbf8c27dfd887af9ce
```

`kernel.json` 同时列出 `com.apple.iokit.IOHIDFamily` 与 `com.apple.iokit.IOHIDEventDriver`，`personality_overrides` 含 `Pong PMIC volume keys`。已把该 payload 封装进五核稳定基线，生成音量键测试镜像：

```text
D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-cpumask-1f-hidprelink-94f0aaf-43055703607.img
102699008 bytes
sha256 aac9c1e0d2d89a8d0d06f5825b77f66e40b2690944380b9b855dd1e21f1aea61
PONGFAT1 CRC 0x4ec4c25d
```

ADT 回读为 `cpus=5`、`trust-cache=1`、触摸轴 `8640x19296`。该镜像尚未实机启动。音量键仍必须看到 `volume report device=native` 并实际改变系统音量才算完成。

该修复不修改 S3910 触点投递、坐标转换、`pong_s3910=4` 或屏幕分辨率。

### 当前阻塞与方法优化

- 六核与七核都停在同一个 APFS UUID，继续加核不再有诊断价值。当前先排除性能镜像中的日志/UFS 争用。
- 每次实验先记录四个结论：ADT 核数、boot 参数核数、CPU first boot、APFS/SpringBoard。缺一项就只记录部分结论。
- 五核已经成为稳定基线。后续单变量实验都以它回归，不能把 CPU、USB、HID 和触摸混在一次镜像里。
- CPU 核数成功不等于系统启动成功。六核和七核已经证明两者必须分开验收。
- CI 构建完成不等于功能验证完成。音量键必须看到原生 HID 设备和真实音量变化。

### 方法层面的破局点

1. 一次只改变一个变量。USB 固定 `liuqin_usb=0`，触摸固定 `pong_s3910=4`。
2. 先验证“拓扑声明一致”，再看启动结果。启动参数核数与 ADT CPU 节点数必须一致。
3. CPU 与 GPU 分开处理。当前 `pong_software_ui=1`，Adreno 730 另立实验。
4. 每次实机验收同时记录 CPU 与系统终点，避免把 CPU 注册误报为可启动。
5. 每次性能实验先测诊断开销，再考虑增加硬件复杂度。
6. 任何性能实验都不得改动已通过的触摸代码。触摸只作为回归检查，不作为试验变量。

### 安全硬约束

- 唯一允许操作的串号：`9ea882b4`。
- 绝对禁止操作 `42d72758 / OPD2515`。
- ADB 和 fastboot 必须显式带 `-s 9ea882b4`。
- 只允许 `fastboot -s 9ea882b4 boot <镜像>`，禁止刷 `boot`、`userdata` 和 `fastboot -w`。
- 禁止 `git reset`、`git clean`、`git add .`。
- 不覆盖桌面基线和 `rmx3551-uefi-baseline.img`。

---

## 历史快照（2026-11-11 17:03，Asia/Shanghai）

### 一句话状态

iPadOS 18.7.10（22H374）的系统启动链路已经验证。`ff3d025` 的本地修复镜像在实机越过 DarwinBoot，日志包含内核启动、launchd、SpringBoard、1080x2412 BGRA surface、`first visible frame`，S3910 HID 还记录了真实触点。用户本次观察到的现象仍是“没开机成功”，但日志排除了 DarwinBoot 拒绝和内核未启动。当前主问题收窄为用户可见画面或稳定 scanout 不一致，不能继续沿 TrustCache、ADT 或缺槽位方向排查。

### 2026-11-11 17:03 USB worker 启动顺序修复（CI 已过，实机验证中）

`ff3d025` 的 CI 镜像在实机上进入内核后 panic，照片与符号化材料保存在：

```text
D:\unixnu\ud\panic-ff3d025-ci-42981426332-20261111
```

可见调用链为：

```text
kmem_alloc_guard_internal
io_map
liuqin_usb_debug_start
bsdinit_task
```

不是镜像拼接、PONGFAT1 CRC 或触摸回归。旧代码在 `bsdinit_task()` 中同步启动 USB 调试口，此时 VM 页结构和 IOKit 初始化尚未完成，`ml_io_map()` 返回 `KERN_NO_SPACE` 并触发 panic。

提交 `29d45d9`（`fix(usb): start debug worker after IOKit initialization`）采用上游 K60 的启动顺序：

- 删除 `bsdinit_task()` 中的同步 USB 启动。
- 在 `bsd_autoconf()` 中确认 `IOKitBSDInit()` 返回 `KERN_SUCCESS` 后才调用 `liuqin_usb_debug_start()`。
- `start` 只创建 worker 并立即返回；所有 `liuqin_io_map()`、DMA 分配和控制器寄存器访问都在 worker 内执行。
- worker 完成初始化后调用 `thread_terminate(current_thread())`。
- 新增 `tests/test_rmx3551_usb_startup_order.py`，阻止 USB 调用重新挂回 `bsdinit_task`，也阻止 MMIO/DMA 从 worker 漏回 boot thread。
- `kernel.yml` 在下载大型 Apple 组件前运行 preflight；Windows 本地 preflight 改为把规范化脚本写入临时文件后用 `wsl.exe --exec /bin/bash -n` 检查，消除了 stdin/WSL 的五条假语法错误。

GitHub Actions run `42989774583` 完整成功，artifact id `13842295410`：

```text
artifact zip    23348678 bytes  sha256 031bf7ecf32841b350d54ebd796f550451137b81beffdc1a73fe86fe325e388c
extracted root  D:\unixnu\UniXNU-rmx3551\out\ci-29d45d9-42989774583
ADT             15444 bytes      sha256 1de68c1b46b922c43c302d526215a0ef403c4b529942bbe78890e2efe126b7bb
payload.img     100663296 bytes  sha256 22fdd119555c35324c1d898393cf82e49482c28eb2dadda3e5eac4ea0e052f4c
kernel.macho    51949568 bytes   sha256 a4236c2e57c27e0939ec6258729338c40dd7b6bdd8d6e7fc6dfc6dccba2f83fb
```

独立 ADT 验证通过：`cpus=4`、`trust-cache=1`、触摸 axes `8640x19296`、UFS SMMU stream `0xe0`。payload 的 `kernel_args` 同时保留 `pong_s3910=4`、`liuqin_usb=1` 和 `liuqin_usb_smmu=2`。用未覆盖的 baseline `rmx3551-uefi-baseline.img` 组装的新临时启动镜像是：

```text
D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-usbworker-stage4-29d45d9-42989774583.img
bytes   102699008
sha256  ea041eb3e104829adf5ae4eb689b82f6a9bddda842c8483d7ab609be5fcb1ba4
```

独立 boot 解包核验确认 baseline 的 UEFI/kernel 字节除 header 的 ramdisk-size 字段外不变，PONGFAT1 version、FAT 长度和 CRC32 `0xcf27f9e9` 均匹配，嵌入 payload 与 artifact 逐字节一致。

启动前在 recovery 核验 `9ea882b4 / ovaltine / twrp_ovaltine`，进入 fastboot 后核验 `serialno=9ea882b4 / product=taro`，随后只执行：

```text
fastboot -s 9ea882b4 boot D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-usbworker-stage4-29d45d9-42989774583.img
```

`Sending` 与 `Booting` 都为 `OKAY`。截至本段更新，实机日志尚未回收，因此只能确认 CI、artifact、封装与临时启动命令成功，不能把硬件修复判为最终通过。下一份日志必须确认 `io_map`/`KERN_NO_SPACE` panic 消失，并继续看到 S3910 stage 4 打开 HID，不要修改触摸解析、坐标转换或 `pong_s3910=4`。

### 2026-11-11 TrustCache 启动拒绝与修复

`311b89e` 的 stage-4 镜像进入 UniXNU 菜单后显示：

```text
DARWINBOOT: boot refused: Compromised Data; firmware retained
```

没有进入内核，因此这次失败与触摸 HID、坐标转换、触点解析、CPU 调度或 PONGFAT1 CRC 无关。payload 中真实存在
`EFI/UniXNU/Payloads/kernel.macho.trustcache`（70,116 bytes，SHA-256
`cc4f5079fafbb81cf32f54718666461630381972867428e13c6e8a906b58d7cd`），但当时生成的真实 ADT
`/chosen/memory-map` 只有 `name`。DarwinBoot 读到 trustcache 文件后要求同一 ADT 中存在 16 字节全零的
`TrustCache` 属性；缺失时按设计返回 `EFI_COMPROMISED_DATA`。已知可启动的旧 ADT 正好有这个槽位。

提交 `ff3d025`（`fix: restore TrustCache ADT handoff`）完成以下修复：

- `make-pong-adt-ipados18.py --trust-cache` 生成 `/chosen/memory-map/TrustCache = bytes(16)`。
- `finalize-pong-adt.py` 在 payload 内查找真实 `kernel.macho.trustcache`，缺失或为空时直接失败，并只在文件存在时传入槽位标记。
- `verify-pong-adt.py` 现在必须显式选择 `--trust-cache` 或 `--no-trust-cache`，并验证 16 字节槽位与该选择一致。
- `kernel.yml` 用 `--trust-cache` 验证最终 artifact；`preflight.py` 阻止遗漏四核、UFS 或 TrustCache 检查的流水线。
- `tools/read-pong-log.py plan` 改为强制 `--serial`，内部每次同步都执行 `adb -s <device>`，满足唯一目标设备的操作边界。

隔离工作目录中的真实验证从 `311b89e` 的 100 MiB payload 和同一份 `hardware.dtb` 重新运行 finalizer：

```text
ADT bytes               15444
ADT sha256              99fdf666600b7a4723eb00f7b0db45c40ebbec6559294bba7f7f5f77193d4e63
TrustCache bytes        70116
TrustCache sha256       cc4f5079fafbb81cf32f54718666461630381972867428e13c6e8a906b58d7cd
embedded TOML           cpus=4 + pong_s3910=4
verifier                PASS; trust-cache=1; touch axes=8640x19296
```

为尽快取得硬件证据，已把该新 payload 放入已知 stage-4 启动容器的同一 UEFI kernel slot，生成一张不覆盖任何基线的本地临时镜像：

```text
D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-stage4-trustcache-ff3d025-local.img
size    102699008 bytes
sha256  f0079848126af0f2550f14ce7ca6e5f4c40b6cacc956ca43346317a7731baa07
```

启动前已在 TWRP 核验 `ro.serialno=9ea882b4`、`ro.product.device=ovaltine`、
`ro.product.name=twrp_ovaltine`；进入 bootloader 后又核验 `fastboot -s 9ea882b4 getvar serialno`
返回 `9ea882b4`、`getvar product` 返回 `taro`。只执行了临时 `fastboot -s 9ea882b4 boot`，没有刷写任何分区。

### 2026-11-11 15:54 `ff3d025` 实机启动结果

这张镜像已经不是“尚未实机启动”。回 TWRP 后只读提取并解码的 PongBootLog 显示系统运行了十几分钟，证据目录：

```text
D:\unixnu\ud\diagnostics-s3910-stage4-trustcache-ff3d025-20261111-155103
```

文件与哈希：

```text
ponglog-region.bin       4198486 bytes  ac8316d1fdd9827ef94e6dbc10f388d515a57cba5559a59998c7cffcf977084b
ponglog.txt               186535 bytes  ebd3297f224a9b39682aba4709cd71581ae02fb676cc11892f0e5f0de743c72f
ponglog-region-clean.bin 4198400 bytes  de22a3b2947bee734d6f16b198af4f9a557672433c345204c3a820c89a7b60bb
ponglog-clean.txt        184804 bytes  ebd3297f224a9b39682aba4709cd71581ae02fb676cc11892f0e5f0de743c72f
```

第一次 region 多出的 86 字节是设备端 `dd` 统计文字。随后用 `exec-out` 和 `2>/dev/null` 重新抽取标准 4,198,400 字节，解码后的文本哈希与第一次完全相同，因此当前结论不是抓取时混入文字造成的。日志快照头仍显示 `status 2` 和可能被撕裂的警告，但内容连续并被重复抽取一致确认；不能把该警告解释成内核未启动。

关键行：

```text
7:     Darwin Kernel Version 24.6.0: Tue Nov 10 14:00:36 UTC 2026
210:   Pong touch: S3910 diagnostic stage 4
288:   Pong touch: S3910 identified v1 ... axes=8640x19296 ...
1046:  Pong touch HID: display-integrated digitizer opened
1364:  Pong UI18: screen native=1080x2412 logical=360.00x804.00 scale=3.00
1371:  Pong UI18: main queue wake completed backlight=1 lockscreen=1
1395:  MiniIOMobileFramebuffer: first visible frame; releasing boot console
1446:  MiniIOSurface: SpringBoard[27] created surface 7: 1080x2412 'BGRA'
2118:  Pong touch HID: type=1 finger=0 xy=22664,30661
2656:  MiniIOMobileFramebuffer: 7 frames in 182690 ms (0 a second)
```

用户点击以前，framebuffer 曾连续报告约 9–18 FPS。真实触点之后从约 10 FPS 掉到 1 FPS、0 FPS，之后偶尔恢复再出现长时间停顿。日志中没有 DarwinBoot `boot refused`，也没有内核 panic。当前现象因此是系统已运行但显示或帧更新不稳定，下一步应先确认现场究竟是黑屏、锁屏、UniXNU 菜单残留还是画面冻结，再针对 display/scanout 取证。

`ff3d025` 只修改 TrustCache 的 ADT handoff、生成器、验证器、CI 和 preflight；没有修改 framebuffer、HID、触摸坐标、触点解析、CPU 数量或内核代码。该提交完成的启动修复应视为通过，当前失败继续查显示路径。

本次日志也可归因于新一轮启动，不是上一轮残留：快照头为 `sequence 255`、`tick 2181`，而上一份 cpus4 快照为 `sequence 27`、`tick 45`；本次 `pmap_startup` 为 749,405 微秒，旧快照为 770,232 微秒。

现场画面还有一个必须排除的混淆项。当前 22H374 兼容层在 `userland/ui_compat18.c` 的 `wake_home()` 中只调用
`preventIdleSleepForNumberOfSeconds: 300`，即大约 300 秒后允许系统再次空闲休眠。本次指令原本要求等待
4–5 分钟再回 TWRP，正好接近该窗口。日志后半段系统服务仍持续运行，但显示帧更新变得稀疏；这符合
“SpringBoard 已运行、屏幕随后休眠或进入静止状态”，也符合显示异常，当前日志本身不能区分二者。

因此下一次现场判断必须分时记录：

1. fastboot 后 30–60 秒先确认屏幕状态，不能等满 5 分钟才第一次观察。
2. 若此时有桌面或锁屏，说明启动和首帧已成功；记录是否可触摸以及卡顿程度。
3. 若随后屏幕变黑或冻结，轻触屏幕并等待至少 30 秒，再记录是否恢复。
4. 只有“从未出现桌面/锁屏，轻触后也不恢复”才按纯显示提交失败继续查。

### `ff3d025` CI 产物

GitHub Actions run `42981426332`（<https://github.com/Axiang-dev/UniXNU-rmx3551/actions/runs/42981426332>）已于 2026-11-11 15:57:01 完成，结论为 `success`。关键步骤 19「Finalize the board ADT from the compiled hardware tree」和步骤 20「Verify the finalized ADT before it can be uploaded」均成功。

```text
artifact id     13838875421
artifact        rmx3551-kernel
zip bytes       23346876
zip SHA-256     15bbb48041a9d0bd0afdd707061fba417fb207b9a4420414682dd6bf10f387bb
extracted root  D:\unixnu\UniXNU-rmx3551\out\ci-ff3d025-42981426332
```

从官方 artifact 独立复核：

```text
kernel.macho.adt.pong  15444 bytes     2586053ae57f16aae65b29a0860d5e83062cf33ef9377ef9226ee5b81b255634
payload.img            100663296 bytes d095ee3e17a65bd9092e1a8cbd66a4cd7c8fab667f0270622ba788849f52a965
kernel.macho           51949568 bytes  8e9569c2045e29bad99b384717bfecc5a0758e01c04acbad6d94ca692832d591
verifier               PASS: cpus=4, trust-cache=1, touch axes=8640x19296
```

用该 artifact 的 `payload.img` 和不变更的 UEFI baseline 已生成另一张官方命名候选：

```text
D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-stage4-trustcache-ff3d025-42981426332.img
bytes   102699008
sha256  bdbc301db56c8a0988103382c03a350bab1a920bb36f00d09b3d3cbc3777398a
```

这张候选尚未实机启动。已实机越过 DarwinBoot 的是本地 `f0079848...baa07` 镜像；不要覆盖或删除该已验证镜像，下一次测试如需换图应使用上述新文件名。

不要把 stage-3 的 HID-off 行为套到这张镜像上。它仍使用 `pong_s3910=4`；stage-4 成功时必须看到
`S3910 ready`、真实触点事件，并且现场触屏可操作。

### 触摸结论

- stage 3 的四项关键条件已经全部通过：应用信息返回 `axes=8640x19296`，report format 成功应用，控制器重新识别为 `8640x19296`，HID 保持关闭。
- stage 4 已实机运行。日志显示 `S3910 ready`、`8640x19296`、`60 Hz`，并打开 display-integrated digitizer。
- 三核和四核测试日志都各记录了 4 个真实 `Pong touch HID: type=1/2` 触点事件。用户现场确认点击正常且没有坐标错位。
- 触控原生坐标 `8640x19296` 不是屏幕分辨率。显示仍是 `1080x2412 BGRA`，两个轴按 8 倍归一化。
- 已验收的是基本点击和移动。多指、压力、休眠唤醒、长按及复杂手势尚未系统验收。
- 在新的实机证据表明必须修改前，不要改 touch HID、坐标转换或触点解析代码。

### CPU 增量验证

| 配置 | 实机结果 | PongBootLog 中的可见帧率 | 镜像 SHA-256 |
|---|---|---:|---|
| `cpus=1` | 进入 SpringBoard，CPU0 first boot | 约 2.736 FPS | `96b93111553aafb8dd514f106583c5f8357c62b282223cfd2b5e68c7952bb819` |
| `cpus=2` | 进入 SpringBoard，CPU0–1 first boot | 约 6.124 FPS | `5d8000662ac4b9b54c833a2a59c27ae24c1c2796d4f59622e0661f37900b04e9` |
| `cpus=3` | 进入 SpringBoard，CPU0–2 first boot，无内核 panic | 约 4.887 FPS，短窗口 | `0d3f86889c5c1c4b42282aa43337f661efc90f0729a5f62e4581fa5c0f89578f` |
| `cpus=4` | 进入 SpringBoard，CPU0–3 first boot，无内核 panic | 可见窗口约 9.409 FPS，末尾连续窗口约 10.2 FPS | `190ced0decb0bb78e0939ae442483432c642af2a25c50fd6987f256a4dae6efe` |
| `cpus=5` | 实机启动失败；回 TWRP 后 userdata 日志区仍与 cpus4 完全同哈希，未写出 CPU4 first boot | 无有效新日志 | `57f2118bf3fc44160aa3a9d0d4ce505096221e233d3f128d33f1b0bd463c996b` |

`cpus=1` 至 `cpus=4` 的日志都保留 `ArmCpu: all registered CPUs available; idle preference X2, A710, A510 (no affinity binding)`。四核日志仍有既有用户态错误，包括 Biomed/线程数 watermark、AccessibilityUIS `EXC_RESOURCE` 和 `BlastDoor cannot run unsandboxed`，这些不是 CPU first-boot 或触摸初始化失败。

### 五核失败的边界

- `cpus=4` 与 `cpus=5` 镜像同为 102,699,008 字节，逐字节只差 5 个字节：`0x34504e6` 的 ASCII `4`→`5`，以及 PONGFAT1 头 `0x1f0018`–`0x1f001b` 的 CRC32。两份 FAT 的实算 CRC 都与头内 CRC 相同，因此目前没有镜像封装损坏证据。
- `cpus=5` 是普通内核命令行参数，DarwinBoot24 源码没有针对该值的特殊分支。实机停在带选单残留的画面不能证明尚未进入内核。
- 启动画面已打印 `DARWINBOOT: hand-off to the kernel` 与 `inputs validated; exiting boot services`，而 DarwinBoot 不会清除这层选单画面，因此它可能一直残留到内核早期。没有新的 PongBootLog 只能证明本次没有成功落盘，不能单独证明失败发生在 UniXNU 菜单。
- 下一次判断必须使用更早的可观测点，例如 LIUQIN USB CDC 的早期 console、启动画面阶段标记，或其他可证明 `Enter()` 是否被执行的证据。

`cpus=3` 的可见帧窗口合计约 82.254 秒、402 帧。`cpus=4` 的日志因控制台环形缓冲区截断，只保留了 5 个 cadence 记录，合计 26.889 秒、253 帧，不能把它解释成整次运行只有 27 秒。两者仍应作为趋势数据，而不是精确基准测试。

### 当前镜像与来源

- 仓库 HEAD 为 `81e7063`（`fix: normalize S3910 touch axes`）。
- 对应成功 CI run 为 `42827300826`。
- `cpus=3` 镜像路径为 `D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-stage4-cpus3-81e7063-42827300826.img`。
- `cpus=4` 镜像路径为 `D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-stage4-cpus4-81e7063-42827300826.img`。
- `cpus=5` 镜像路径为 `D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-stage4-cpus5-81e7063-42827300826.img`。
- 三个 CPU 数变体都从同一 CI 产物派生。相对前一档只改变 `cpus=N` 的 1 个 ASCII 字节和 PONGFAT1 CRC32 的 4 个字节，没有重新编译内核，也没有新的 CI run ID。
- 历次都只执行 `fastboot -s 9ea882b4 boot`，没有刷 `boot`、没有刷 `userdata`、没有执行 `fastboot -w`。

### 本轮日志证据

`cpus=3`：

```text
D:\unixnu\ud\diagnostics-s3910-stage4-cpus3-20261110-232912
region SHA-256 d608f5735a8766f7f3c3a8fa2803ee7a051fce9eb95e7f166b9a7386c9002913
log SHA-256    e1155db66374e57b41789c1745f44789fd4bbb91fe63d23066708c8778607785
```

`cpus=4`：

```text
D:\unixnu\ud\diagnostics-s3910-stage4-cpus4-20261110-233348
region SHA-256 5320ebb913955f694267ae72cbce2376fa6c7926ba05d2749c1b8a154e25cb7c
log SHA-256    5a86620c7b327c74a8dbe3d62bc34a358a2b628947cbe81e9b82c95ca6884dfe
```

`cpus=5` 失败尝试（2026-11-10 23:50 左右回收）：

```text
D:\unixnu\ud\diagnostics-cpus5-failed-20261110-235025
region SHA-256 5320ebb913955f694267ae72cbce2376fa6c7926ba05d2749c1b8a154e25cb7c
log SHA-256    5a86620c7b327c74a8dbe3d62bc34a358a2b628947cbe81e9b82c95ca6884dfe
```

这次读回的 region 和 log 与 cpus4 证据逐字节同哈希，只能证明失败尝试没有覆盖上一份 PongBootLog，不能把其中的 CPU0–3 first boot 或 SpringBoard 记录当作五核运行证据。

四核 PongBootLog 的 CPU 证据：

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

### 为什么四核仍然不是最终调度方案

本地 SM8475 DTS 的顺序是：

```text
CPU0–3 = A510 E 簇
CPU4–6 = A710 P 簇
CPU7    = X2 P 簇
```

所以四核只启用了 A510，尚未启用任何 A710/X2。五核才会首次把 CPU4 加入调度。四核的明显提速证明增加可用核心有效，但不证明 UI 已被放到高性能 P 核。

源码瓶颈也已确认。日志仍打印“no affinity binding”，本地补丁仍是：

```c
#define MAX_CPU_CLUSTERS 1
```

因此当前只是多个核都能运行，还没有完整的双簇 E/P 调度和 UI 亲和策略。

### 下一阶段

1. 暂停测试 `cpus=6` 和 AMP/Edge 调度。五核失败尚未形成新的 PongBootLog，需先定位它停在 DarwinBoot、内核早期、CPU4 first boot 还是更晚阶段。
2. 优先启用现有 LIUQIN USB CDC 调试口作为早期启动实时日志通道：它镜像内核 console 到 1 MiB 环形缓冲，并提供 `help/status/ping/replay`。当前已知 blocker 是 `LIUQIN USB: SMMU route refused; controller untouched`，尚未验证控制器和 DMA。
3. P 簇至少稳定后，把官方 `zzyf-sheng-amp.patch` 适配到当前 Darwin 24 内核，设置 `MAX_CPU_CLUSTERS=2`，定义 `__ARM_AMP__`，保留 DTS 的 E/P `cluster-type`，让固定优先级、UI 和 user-initiated 工作优先留在 P 簇。
4. 同时审计长期占用 CPU 的服务，例如 `coreduetd`。不要把服务错误和 CPU 调度故障混在同一次实验。
5. Adreno 730 GPU 在 CPU/Edge 调度稳定后再做。当前仍启用 `pong_software_ui=1`，官方完整参考是 A740/SM8550，不能照搬其固件、寄存器或 stream ID。
6. 多 bank 12 GB RAM 最后单独立项。当前日志仍是 1 owned bank、4096 MiB。设置中约 7 GB 是 APFS Data 分区，不是物理内存。

### 文档与工具状态

2026-11-10 23:40 因 WorkBuddy headless CLI 缺少 `cli/dist/codebuddy` 和 `cli/dist/codebuddy-headless`，自动委派无法执行。用户明确授权后，本次由 Codex 直接更新本文档。WorkBuddy GUI 是否可用不影响上述硬件结论。

### 安全硬约束

- 唯一目标串号是 `9ea882b4`。最近一次 TWRP 属性为 `ovaltine / PGP110 / twrp_ovaltine`。
- 绝不要操作历史出现的 `42d72758 / OPD2515`。
- 所有 ADB 和 fastboot 命令都显式带 `-s 9ea882b4`。
- 只允许 `fastboot -s 9ea882b4 boot <新诊断镜像>`。
- 禁止刷 `boot`、禁止刷 `userdata`、禁止 `fastboot -w`、禁止 `git reset`、禁止 `git clean`。
- 不得覆盖桌面基线 `D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-usbdebug-22e7b2c-42510630419.img`，其 SHA-256 为 `9574063d753bda2b190693aa720cd6d08c5dcfa7bc79ae03f17fff40a9c7cb63`。

---

## 历史快照（2026-11-10 18:15，GMT+8；保留原记录）

### 18:57 实机试验进行中（本条覆盖下文启动前的状态）

- 已确认 `9ea882b4` 位于 TWRP（`ovaltine / PGP110 / twrp_ovaltine`），进 bootloader 后再次查询到 `serialno: 9ea882b4`。`fastboot boot` 回报 `Sending ... OKAY`、`Booting ... OKAY`，现场确认 iPadOS 正在运行。等待返回 TWRP 收取本轮日志，stage 3 结果仍待判定。
- 实机镜像使用 `5820fa6`、CI `42794829937`，路径为 `D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-appinfo-clean-5820fa6-42794829937.img`，启动前复算 SHA-256 为 `fcb3d801fe02a87093114f5b2c4fe102c182528a633b22b24f648b82b9e04875`。
- 证据目录 `D:\unixnu\ud\diagnostics-s3910-stage3-5820fa6-20261110-185714`。启动前的 `before-region-clean.bin` 为 4,198,400 字节，SHA-256 `6b3a779953fbdd7044f9364898dbf8b69f1bd6cc7bef12e1a46cc74d4b9c2079`。其解码日志 `before-ponglog.txt` 显示旧内核构建时间 `09:40:14 UTC`，仍在 `0x24` 失败。新内核的构建时间为 `10:13:33 UTC`，用于核对回收日志归属。每次启动的 `sequence` 从头计数，需比较镜像内容和内核构建标识。
- 首次基线读取因 `dd` 的统计信息混入字节流，多出 86 字节。后续把 `dd` 的 `2>/dev/null` 放进设备端命令，通过二进制方式保存，并核对文件恰为 4,198,400 字节后解码。只运行 `read-pong-log.py decode`，其 `plan` 子命令会自行发起未指定串号的 ADB 请求。

### 目标与当前结论

用户最终目标保持不变：参考 UniXNU 官方仓库和文档，成功启动 iPadOS 并进入桌面。这个总目标已经完成：iPadOS 18.7.10（22H374）已进入 SpringBoard，显示发布为 `1080x2412 BGRA`，当前只继续修 Synaptics S3910 触摸，之后再处理音量键和 USB。

触摸整体完成度约为 **65%–70%**。与 17:43 的旧快照相比，提升来自实机已经成功返回 `GET_APPLICATION_INFO (0x20)`；但新的 report-config 初始化序列尚未实机跑完，HID 仍故意关闭，因此现在不能说“触摸已修好”。

| 环节 | 当前把握 | 证据 / 缺口 |
|---|---:|---|
| 供电、RESET、1.8 V、GPIO | 约 95% | 实机资源打开，S3910 有响应 |
| QUP0/SE4、SPI/GENI/GPIO 位流 | 约 90% | 已完整读出识别包；GENI 不可用时 GPIO SPI 生效 |
| TouchComm v1 识别与分帧 | 约 90% | 已取得 28 字节 identify payload |
| `GET_APPLICATION_INFO (0x20)` | 已验证 | 实机返回 `code=0x1 length=46`，之前的 `STATUS_BUSY` 已消失 |
| 应用模式初始化 / report config | 约 65% | 已删除错误的 dynamic-config 探测；`0x06 -> 0x26 -> 0x25 -> 0x05` 尚待新镜像实机验证 |
| 触点解析和坐标归一化 | 约 55% | 主机测试覆盖格式与边界；尚无真实触摸帧 |
| iPadOS 触控 HID | 约 65% | `userland/touch.c` 与 `/dev/pong-touch` 通路存在；桌面尚未验收 |
| 真机端到端验收 | 未验证 | 必须看到 down/move/up 并驱动 SpringBoard |

### 本次交接时的设备状态

最近一次看到目标设备是在 TWRP，但整理交接时电脑再次完全检测不到 ADB/fastboot 设备，重启 ADB 服务后仍为空。因此**不要假设设备还连着**，新接手者第一步必须重新确认。

目标机唯一合法串号是：

```text
9ea882b4
```

最近确认的属性为：

```text
recovery product:twrp_ovaltine model:PGP110 device:ovaltine
```

历史现场曾同时出现另一台绝对不能操作的真实设备：

```text
42d72758 device product:OPD2515 model:OPD2515 device:OP6548L1
```

所有 ADB/fastboot 命令都必须显式带目标：

```powershell
adb -s 9ea882b4 ...
fastboot -s 9ea882b4 ...
```

绝对边界：

- 只允许 `fastboot -s 9ea882b4 boot <诊断镜像>` 临时启动。
- 不刷 `boot`、`userdata` 或其他分区；不执行 `fastboot -w`。
- 不执行 `git reset`、`git clean`；工作树内有大量不能删除的历史构建输入和日志。
- 新镜像必须使用新文件名，文件名带提交短哈希和 CI run ID。
- 不能覆盖已验证的桌面基线：
  `D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-usbdebug-22e7b2c-42510630419.img`
  SHA-256：
  `9574063d753bda2b190693aa720cd6d08c5dcfa7bc79ae03f17fff40a9c7cb63`

### 最新实机日志与根因

上一张 app-info 诊断镜像的日志目录：

```text
C:\Users\27699\Documents\Codex\2026-11-08\new-chat-2\pong-debug-20261110-175049-appinfo
```

关键日志：

```text
Pong touch: S3910 command 0x20 tx: 20 00 00
Pong touch: S3910 command 0x20 reply[0] code=0x1 length=46

Pong touch: S3910 command 0x6 tx: 06 01 00 11
Pong touch: S3910 command 0x6 reply[0] code=0x1 length=0

Pong touch: S3910 command 0x24 tx: 24 03 00 11 02 00
Pong touch: S3910 command 0x24 reply[0] code=0xf length=0 detail=0xfa5
Pong touch: S3910 identify failed rc=-5 stage=reply detail=15 version=1 command=0x24
```

结论：

- `0x20 GET_APPLICATION_INFO` 已经成功，`STATUS_BUSY` 问题已经解决。
- 失败发生在驱动错误地把 report ID `0x11` 当成 dynamic-config ID 发给 `0x24 SET_DYNAMIC_CONFIG`。
- 芯片正确返回 `STATUS_ERROR (0x0f)`，`detail=0xfa5` 中的 `15` 就是该状态。
- `0x23` 是 `GET_DYNAMIC_CONFIG`；`0x05` 才是 `ENABLE_REPORT`，`0x06` 才是 `DISABLE_REPORT`。不要再把 `0x23` 当 report ID 或 `DISABLE_REPORT` 使用。
- 驱动里仍保留一个针对“初始化前排队的 HBP 帧”的保护判断，其中看到 report code `0x23` 只是分帧保护；该路径不会再发送 `0x23` 命令。

官方初始化顺序现在应严格保持为：

```text
IDENTIFY (0x02)
GET_APPLICATION_INFO (0x20)
DISABLE_REPORT (0x06, report 0x11)
SET_TOUCH_REPORT_CONFIG (0x26)
GET_TOUCH_REPORT_CONFIG (0x25)
ENABLE_REPORT (0x05, report 0x11)
```

### 已提交的源码修复

设备仓库 HEAD：

```text
5820fa67162fc7ac476a16956ed8a926d8dfa8b3
fix: remove S3910 dynamic-config probe
```

修改文件：

```text
D:\unixnu\UniXNU-rmx3551-device\patches\xnu-ipados18\0001-pong-darwin24.patch
```

本轮修改：

- 删除错误的 `0x24 SET_DYNAMIC_CONFIG {0x11, 0x02, 0x00}`。
- 删除错误的 `0x23 GET_DYNAMIC_CONFIG {0x11}`。
- 删除后续错误的 LBP 响应检查。
- 增加应用信息日志，打印 length、version、static/dynamic size、report config、payload limit、原生坐标和对象数。
- 修正注释，明确 `0x06` 是 `DISABLE_REPORT`，`0x23` 是 `GET_DYNAMIC_CONFIG`。
- 新文件 hunk 行数更新为实际的 `1367`。

主机测试已执行并通过：

```powershell
& 'C:\Users\27699\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B `
  'D:\unixnu\UniXNU-rmx3551-device\tests\test_rmx3551_s3910_protocol.py'
```

输出：

```text
rmx3551_s3910_protocol_host_test.c
S3910 protocol host tests passed
```

`git diff --check` 也已通过。

### 已成功构建并准备好的新镜像

最新 CI：

```text
workflow: RMX3551 kernel build
run:      42794829937
commit:   5820fa67162fc7ac476a16956ed8a926d8dfa8b3
status:   success
artifact: rmx3551-kernel
id:       13754321750
zip:      23,334,193 bytes
zip SHA:  809f1987bded56751a9229e03a8d1a6e73afaf1b2b24d960882531b83bbf1dad
```

下载解压目录：

```text
D:\unixnu\UniXNU-rmx3551\out\ci-5820fa6-42794829937
```

新 `kernel.macho`：

```text
路径: D:\unixnu\UniXNU-rmx3551\out\ci-5820fa6-42794829937\build\rmx3551\ipados-18.7.10-22H374\pong_ipados18_ci\kernel\kernel.macho
大小: 51,933,184 bytes
SHA-256: 3b92f02ee7b4d36e4bb71d206d8a079fb8f1ca2c245e3702cbb8fe6417ca6a97
```

新 stage-3 payload：

```text
路径: D:\unixnu\UniXNU-rmx3551\out\payload-s3910-appinfo-clean-5820fa6-42794829937.img
大小: 100,663,296 bytes
SHA-256: 9e0d7c430cde3ac0ba719c6a86a6e8eae00db26ce1e2b6b01a09a2efdb8656db
```

下一张唯一应启动的诊断 boot：

```text
路径: D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-appinfo-clean-5820fa6-42794829937.img
大小: 102,699,008 bytes
SHA-256: fcb3d801fe02a87093114f5b2c4fe102c182528a633b22b24f648b82b9e04875
```

打包时已验证：

- 旧内核 SHA-256：`0e08505d980fe2ba74978a6af59f63aeed4a6efcd10dda7d8777f9bb2014e0c5`
- 新内核 SHA-256：`3b92f02ee7b4d36e4bb71d206d8a079fb8f1ca2c245e3702cbb8fe6417ca6a97`
- ADT 保持 14,268 bytes，SHA-256 `8db7ed1256bba8f310e8d673a4d16300ce968c4cc745e0d02ac425dbf9d8ada9`
- `unixnu.toml` 保持 1,215 bytes，SHA-256 `262cd540ccf61bb5fe74245cb9da807b83d62b92ab971369ed25b79ac89a1a68`
- TOML 仍明确包含 `pong_s3910=3`
- 新 boot 内 payload 与输出的 payload 文件逐字节一致

这张新镜像**尚未实机启动**。当前没有证据把它标成成功或失败。

### 下一步必须按顺序执行

1. 确认 RMX3551 已连接并停留在 TWRP：

```powershell
adb devices -l
```

只接受目标行：

```text
9ea882b4 recovery product:twrp_ovaltine model:PGP110 device:ovaltine
```

2. 临时启动新 stage-3 镜像：

```powershell
adb -s 9ea882b4 reboot bootloader
fastboot devices
fastboot -s 9ea882b4 boot 'D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-appinfo-clean-5820fa6-42794829937.img'
```

`fastboot devices` 中如果不是 `9ea882b4`，立即停止，不要操作任何其他串号。

3. 进入 UniXNU 菜单后选择 iPadOS。**这一版不会产生可用触摸**，因为 `pong_s3910=3` 在初始化完成后会故意关闭 HID。它的目的只是验证应用信息、report config 和控制器初始化链路。

4. 让系统继续到用户态并运行约 4–5 分钟；随后按现场既有方式回到 TWRP。若画面进入桌面，stage 3 本身仍不会让桌面响应触摸。

5. 在 TWRP 中读取 PongBootLog。Windows `cmd.exe` 的二进制重定向可避免 PowerShell 文本编码污染：

```powershell
cmd /c "adb -s 9ea882b4 exec-out dd if=/dev/block/by-name/userdata bs=4096 skip=5083392 count=1025 > region.bin"
& 'C:\Users\27699\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B `
  'D:\unixnu\UniXNU-rmx3551-device\tools\read-pong-log.py' decode region.bin --out ponglog.txt
```

6. stage 3 成功的必要条件：

```text
Pong touch: S3910 app info ... axes=8640x19296 ...
Pong touch: S3910 touch report disabled; applying format
Pong touch: S3910 identified ... axes=8640x19296 ...
Pong touch: S3910 stage 3 complete; HID publication disabled
```

`8640x19296` 是控制器原生坐标；显示屏是 `1080x2412`，两轴相差 8 倍。不要认为 `8640x19296` 写错了。

如果以上全部出现，触摸完成度可上调到约 **75%–80%**，随后才允许进入 stage 4。

7. stage 4 才负责真正投递触点：

- 把 payload 内 TOML 的 `pong_s3910=3` 改为 `pong_s3910=4`。
- 保持同一个已通过 stage-3 的内核，不重新改协议代码。
- 生成新的 stage-4 文件名，仍不得覆盖任何旧镜像。
- 真机验收必须看到 `S3910 ready`、`pong-touch` 设备打开以及真实 down/move/up 被 SpringBoard 接收。
- 第一次出现触点但方向或位置不对时，再校准 `touch_flip` 和坐标归一化；每次同时验证四角、边缘和抬手。

### 新 stage-3 若失败，按日志位置处理

- 停在 `stage=app info`：保留完整 TX/reply 和 46 字节 app-info payload，不再猜字段。
- 停在 `command=0x6`：确认 DISABLE_REPORT 的 payload 只有 `0x11`。
- 停在 `command=0x26`：确认 `config_size`、payload 长度和 report format 是否与官方 `syna_set_report_config()` 一致。
- 停在 `command=0x25`：记录返回长度，并确认它是否允许后跟一个连续读状态前缀。
- 在 `0x05` 后失败：先修初始化收尾，不要开启 HID。
- 如果新版仍出现 `0x24` 或把 `0x23` 当命令发送，说明启动的不是这张新镜像，立即停止。

### 关键源码与参考

- 设备仓库：
  `D:\unixnu\UniXNU-rmx3551-device`
- 驱动补丁：
  `D:\unixnu\UniXNU-rmx3551-device\patches\xnu-ipados18\0001-pong-darwin24.patch`
- 主机测试：
  `D:\unixnu\UniXNU-rmx3551-device\tests\test_rmx3551_s3910_protocol.py`
  `D:\unixnu\UniXNU-rmx3551-device\tests\rmx3551_s3910_protocol_host_test.c`
- iPadOS HID 桥：
  `D:\unixnu\UniXNU-rmx3551-device\userland\touch.c`
  `D:\unixnu\UniXNU-rmx3551-device\userland\touch.h`
- 官方 S3910 参考：
  `D:\unixnu\reference\oneplus-synaptics_tcm_S3910.c`
  `D:\unixnu\reference\oneplus-synaptics_tcm_S3910.h`
- 另一套 UniXNU S3910 实机实现：
  `D:\unixnu\UniXNU-OnePlus-Ace5\ios16\giulia_touch.c`
  `D:\unixnu\UniXNU-OnePlus-Ace5\ios16\giulia_touch_wire.h`
- 最新硬件日志：
  `C:\Users\27699\Documents\Codex\2026-11-08\new-chat-2\pong-debug-20261110-175049-appinfo`
- 上一轮预测读日志：
  `C:\Users\27699\Documents\Codex\2026-11-08\new-chat-2\pong-debug-20261110-v1predictive-165507`

### 给下一个 AI 的直接接手话术

> 继续接手 RMX3551 的 UniXNU iPadOS 18 触控修复。先完整阅读 `D:\unixnu\UniXNU-rmx3551-device\HANDOFF-RMX3551.md` 顶部“最新接手快照”，并确认设备仓库 HEAD 至少包含 `5820fa6`。iPadOS 桌面已经能进，当前只处理 Synaptics S3910。实机已证明 `GET_APPLICATION_INFO (0x20)` 成功；旧代码随后错误发送 `0x24` 并收到 `STATUS_ERROR`，该事务已在 `5820fa6` 删除。GitHub Actions run `42794829937` 已成功，下一张尚未实机启动的 stage-3 镜像是 `D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-appinfo-clean-5820fa6-42794829937.img`，SHA-256 为 `fcb3d801fe02a87093114f5b2c4fe102c182528a633b22b24f648b82b9e04875`。先确认 TWRP 中唯一目标串号是 `9ea882b4`，绝不要操作 `42d72758 / OPD2515`；只执行临时 `fastboot boot`，进入菜单选 iPadOS。stage 3 会故意关闭 HID，所以即使系统进入桌面也不会响应触摸，不要因此误判驱动失败。运行 4–5 分钟后回 TWRP 解码 PongBootLog，要求看到 `app info ... axes=8640x19296`、report-config 成功、最终 `stage 3 complete; HID publication disabled`。只有这些成立后才把 TOML 改为 `pong_s3910=4` 并制作 stage 4；任何分区刷写、清数据、覆盖桌面基线或触碰第二台设备都不允许。完成后把实际日志、新提交、run ID、镜像路径和 SHA-256 继续写回本交接文档。

---

## 一、当前进度（一句话）

内核能起、Data 能挂、launchd 能跑、用户会话能建、**显示驱动全部就绪**——
但**合成器一次 swap 都没提交**，所以屏幕始终是黑的。

```
内核启动        ✅
OS/SystemOS 挂载 ✅  union PASS device=d000002
Data 挂载        ✅  Data mount PASS rw=1
launchd          ✅  跑到 UserEventAgent / wifid / tccd ...
用户会话         ✅  USERMANAGERD SESSION SETUP DONE
显示发布         ✅  default surface 1080x2412 BGRA ready
VSync            ✅  refresh notification 1/2 result=0，心跳连续（908 次 / 146 秒）
IOSurface 客户端  ✅  root user client opened
第一次 swap      ❌  0 次
```

参考实现（sheng / 小米平板 6S Pro）在同样的阶段是「3 次 swap + 苹果 logo」，
官方明确说 **Home Screen 它也没验证过**。所以我们离「出图」只差「第一次提交」。

---

## 二、硬件与仓库

| 项 | 值 |
|---|---|
| 机型 | RMX3551（realme，SM8475）|
| 屏幕 | 1080×2412，120 Hz，NT37705 |
| 存储 | UFS，GPT 窗口：OS 1 MiB / SystemOS / Data 由 payload 声明 |
| OS | iPadOS 18.7.10 **22H374**（`ipados-18.7.10-22H374`）|
| 设备仓库 | `github.com/Axiang-dev/UniXNU-rmx3551` |
| 本地目录 | `D:\unixnu\UniXNU-rmx3551-device`（device）、`D:\unixnu\UniXNU-rmx3551`（build/tools）|
| 镜像目录 | `D:\unixnu\ud` |

关键 UUID（写死在各处，改一处就要改全部）：

| 卷 | UUID |
|---|---|
| OS | `B07DF049-…`（payload ADT 的 `root_match_volume_uuid`）|
| SystemOS | `B57C18AA-9E49-44A4-B94A-ED191CFB4B0F` |
| Data | `47C0F5C3-B8C7-47AC-B9D9-F230BAED1576` |

---

## 三、构建与刷机（照抄即可）

### 3.1 构建内核

改 `patches/xnu-ipados18/*.patch` 或 `board.toml` → 提交 → 推到 `main`，
会自动触发 `RMX3551 kernel build`（约 12–15 分钟）。

也可以手动触发：

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -d '{"ref":"main"}' \
  https://api.github.com/repos/Axiang-dev/UniXNU-rmx3551/actions/workflows/kernel.yml/dispatches
```

拉产物 → 取出 `payload.img` → 打 boot：

```bash
python tools/pack-payload-bootimg.py \
  --boot out/rmx3551-uefi-baseline.img \
  --payload out/payload.img \
  -o out/rmx3551-boot-payload.img
```

> 产物 zip 里 `payload/payload.json` 有 `kernel_args`，**打包前先核对**，别打出旧内核。

### 3.2 刷机

```bash
# userdata（只有换镜像时才需要，约 5 分钟）
fastboot flash userdata D:\unixnu\ud\pong-ipados18-fixed.img

# boot（日常只需要这一条）
fastboot boot D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-payload.img
```

**绝对不要加 `-w`**（会擦 userdata，本项目已经踩过一次）。

### 3.3 读日志（每次验证的核心动作）

内核日志在 userdata 尾部，偏移固定：

```
offset = 5083392 × 4096 字节, length = 1025 × 4096
```

TWRP 里：

```bash
adb exec-out "dd if=/dev/block/by-name/userdata bs=4096 skip=5083392 count=1025" > region.bin
python tools/read-pong-log.py decode region.bin --out ponglog.txt
```

`seq` 会递增；同一分区里只有最后写入的那一份是本次启动的。

---

## 四、镜像拼装（最容易出错的地方）

CI 构建出的 `pong-ipados18-userdata.img` **不能直接刷**：

- 它重新生成了 SystemOS 和 Data 两个 APFS 容器，**Data 的卷 UUID 变成 `58536139-…`**
- 内核按 `47C0F5C3-…` 找盘，找不到 → `writable UFS Data UUID unavailable` → `Data mount SKIP error=6` → `/private/var` 只读 → launchd 写不了 → panic

正确做法是**拼装**：

```bash
cp userdata-root.img pong-ipados18-fixed.img          # 旧镜像（Data/SystemOS 都是对的）
dd if=<CI镜像> of=pong-ipados18-fixed.img \
   bs=4096 skip=256 count=1671168 seek=256 conv=notrunc   # 只覆盖 OS 窗口（1 MiB 起 6.38 GiB）
```

拼完自检：

```python
# 期望：Data-47C0F5C3 = 3, SystemOS-B57C18AA = 6
```

---

## 五、必须知道的坑（每条都踩过）

1. **`fastboot -w` 会擦 userdata。** 没有任何理由用它。
2. **`native-ufs-root=1` 不能加。** payload 步骤会拒绝：`native UFS root boot needs exactly one sheng-pmgr=2`。
   那是 ShengUfs 的运行时参数，本板走 Pong 的电源路径。
3. **`offline-owner-root-check=1` 对 Data 挂载没有帮助。** Data gate 从来不是问题所在
   （`Data prepare enter` 打印了，失败是 UUID 找不到）。
4. **iOS 没有 frontboardd。** 那是 macOS 组件，不要在日志里找它，也不要去补它。
5. **applog 里没有输出 ≠ 进程没跑。** 只有 `applog_name` 名单里的进程才会输出。
   `wifi-bootstrap`、`PosterBoard` 之前就是这样被误判为「没启动」。
6. **`pong_boot_snapshot=1` 不是画图开关。** 它是线程转储探针（见下）。
7. **不要照抄官方文档的参数名。** 文档写的是 ShengUfs 实现，本板是 Pong 实现，
   例如 `sheng-data-persist=2`、`sheng-data-*` 在本板根本不存在。
8. **`lsd` 的 `denied attempt to escape CPU monitor` 会刷 200+ 次**，纯噪音，别当故障。

---

## 六、显示链路：已确认的部分

backboardd 的 selector 调用序列（完整、按时间）：

```
88 → 57 → 15 → 22 → 8 → 29 → 33 → 74 → 12 → 79 → 6 → 27 → 84 → 50 → 72
```

- 其中 `15 / 27 / 50 / 84 / 88` **未实现**（驱动打 `not implemented`），目前不影响启动流程
- `72` 注册 VSync 回调（`kFBNotifyVSync = 5`），**成功**
- **没有 3**（`GetLayerDefaultSurface`），**没有 4/5**（`SwapBegin/SwapEnd`）

驱动侧在 `IOMobileFramebuffer::start()` 里已**主动创建** BGRA 默认画布
（参考实现的做法，见官方 display 页），日志 `default surface WxH BGRA ready`。

**改造点提示**：`userland/ui_compat18.c` 会按 UUID（`faf7d7ea-18f0-3c2d-816c-ac56d16c40a3`）
校验 **QuartzCore** 后改两处；这两个地址并非 SpringBoard 可执行文件地址。
`software_composition` 和 `scanout_format` 在 backboardd 分支启用，旧日志也确认补丁成功：

```c
0x184393468 → 改成 return nullptr      // "stock CPU compositor"：让 GPU 渲染器工厂返回空
0x184396060 → 改成返回 BGRA 常量        // "software scanout BGRA"
```

匹配 SystemOS 的本地符号确认：前者是 `CA::WindowServer::AccelServer::renderer()`，
后者是 `CA::WindowServer::IOMFBDisplay::framebuffer_pixel_format()`，均命中函数入口。
源码注释记录 `renderer()` 返回空后经 `Server::render_update` / `sw_renderer()` 进入
原生 SWContext；因此不能仅凭返回空就推断「没有渲染器」，仍须等待栈或反汇编证据。

---

## 七、下一步（按优先级，全是可执行动作）

### P0 · 收集等待链（这一版镜像已经准备好）

镜像：`out/rmx3551-boot-payload.img`（kernel `777b1531`，已含 `pong_boot_snapshot=1`）

```bash
fastboot boot out/rmx3551-boot-payload.img
# 进入内核后至少等 4 分钟；35s/90s 是进程启动后的计时，不是按 fastboot 命令计时。
# 进 TWRP 后，在 device 仓库运行（输出目录必须尚不存在）：
python tools/read-recovery-apfs.py --serial 9ea882b4 collect Data --out D:/unixnu/ud/NEW-DIAGNOSTICS
```

实测 TWRP 未挂载嵌在 SHNGROOT 中的 APFS Data，直接 `adb pull /data/logs` 不可用。
上面的工具校验 SHNGROOT 目录并通过 adb 只读解析 APFS，自动收集内核日志、
`/logs/PongBoot-*`、`/mobile/Library/Logs/PongBoot-*` 和 Wi-Fi helper 日志。
探针按 euid 选择路径：root 写 `/private/var/logs`，非 root 写
`/private/var/mobile/Library/Logs`；不能只查前一个目录。

期望拿到：`PongBoot-SpringBoard.txt`、`PongBoot-backboardd.txt`、
`PongBoot-PosterBoard.txt`、`PongBoot-wifid.txt` …

文件里有每个线程的 `pc / lr / fp / sp` 和 16 层栈回溯。

**符号化方法**：
`image_slide=` 仅适用于主可执行文件。共享缓存中的框架/系统库地址必须使用
`cache=` 减去 dyld cache 的 `sharedRegionStart` 所得的 cache slide；不能混用。
`tools/symbolicate-pong-snapshot.py` 可读取匹配 UUID 的主 cache 与 `.symbols` 文件，
解析快照中的 PC/LR/帧地址，明确保留未解析的主程序地址。两份符号输入已只读提取到
`D:\unixnu\ud\diagnostics-20261108-154736`。重点查看启动线程及两次采样的变化；
仅凭线程数组索引不能确定某线程就是主线程。

### P1 · 判定 wifi 端口阻塞是否仍在

策略代码注释记录过：`services105 proves SpringBoard blocked in wifi_manager_open … preventing its first frame`。

实测 `wifid` 在 `WiFiManagerCreate` 里卡了 **36 秒**（16:02:07 → 16:02:43）。
`wifi-bootstrap` **不占有这个 MIG 端口**。实际策略在 `board_services18.py` 中把
wifid 的 `com.apple.wifi.manager` 设为 `HideUntilCheckIn=True`，直到真实服务 check-in
才可被发现。helper 只在真实 WLAN 注册后请求本机 Wi-Fi 电源和配置。

这一版已把 `wifi-bootstrap` 加进 `applog_name`，日志里应该能看到它到底跑没跑。

- 本次只读取得 `/logs/pong-wifi-bootstrap.log`：三条 `real WLAN not registered; no power request`。
  这证明 helper 曾运行，但当时未发现 WLAN；不能据此判断 SpringBoard 当前等待位置。
- 看 P0 的快照，判断 SpringBoard 是否仍在 `wifi_manager_open`；必要时核验设备实际 launchd 缓存中的端口策略。

### P2 · 如果 P0 指向渲染器

两条路，二选一，不要混：

**A. 恢复 GPU 路径**（参考实现走的是这条）

```
pong_adreno_start=1
offline-iogpu-load=1
pong_metal=1
pong_gpu_scanout=1
pong_gpu_pool_mib=256
pong_metal_global=1
```
并把 `pong_ui_software` / `pong_software_ui` 改成 0（模板里 GPU 模式会先删掉这两条）。

**B. 修 CPU 路径**：把 `0x184393468` 的补丁从「返回 nullptr」改成「返回一个可用的软件渲染器」。
需要先确认 22H374 的 SpringBoard 里那个函数原本返回什么、CA 在没有 renderer 时的回退条件。

### P3 · 补齐参数（已在 `fe39c45` 完成，供核对）

```
pong_ram_banks=1
pong_wifi=1
pong_poster_snapshot=1
fb_threads=4
```

并把空转的 GPU 参数删掉（`pong_gpu_scanout` / `pong_gpu_pool_mib` / `pong_metal_global` / `pong_gpu_lock_max`）。

---

## 八、参考文档（读这几页就够）

| 页面 | 为什么读 |
|---|---|
| https://unixnu.com/porting/display | **首帧验收标准**：3 次 swap + logo；「先抓等待链再下结论」 |
| https://unixnu.com/devices/sheng | 同代平台（SM8550）的完整移植记录，含 IOSurface / direct scanout 细节 |
| https://unixnu.com/xnu/boot-arguments | 参数表（注意：平台参数名分 sheng / pong 两套）|
| https://unixnu.com/porting/ufs | Data 窗口与 seed 的要求 |

---

## 九、关键文件清单

| 路径 | 说明 |
|---|---|
| `board.toml` | 启动参数、窗口、ADT；**改动最频繁的文件** |
| `patches/xnu-ipados18/0001-pong-darwin24.patch` | 内核主体补丁（含 MiniIOMobileFramebuffer / MiniIOSurface）|
| `userland/ui_compat18.c` | 用户态适配层（SpringBoard / backboardd 的二进制改写都在这里）|
| `userland/boot_snapshot18.c` | **等待链探针**（35s/90s 转储线程状态）|
| `userland/board_services18.py` | launchd 作业策略（wifi.manager 端口、隐藏/禁用规则）|
| `scripts/prepare-os-root.py` | OS 窗口组装 + `wifi-bootstrap` 编译与植入 |
| `tools/pack-payload-bootimg.py` | payload → boot 镜像 |
| `tools/read-pong-log.py` | 日志区解码 |

镜像：

| 文件 | 用途 |
|---|---|
| `D:\unixnu\ud\pong-ipados18-fixed.img` | **可用镜像**（旧 Data/SystemOS + 新 OS 窗口）|
| `D:\unixnu\ud\userdata-root.img` | 旧镜像原件（Data/SystemOS 的真源，**别删**）|
| `D:\unixnu\ud\pong-ipados18-userdata.img` | CI 直出镜像（Data UUID 不对，**不能直接刷**）|
| `D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-payload.img` | 当前 boot（kernel `777b1531`）|

---

## 十、给接手者的一句话

**不要再从「参数猜测」入手。** 这一晚证明了：日志能回答的问题，不要靠推理。
先把 `/data/logs/PongBoot-SpringBoard.txt` 取回来，它会告诉你 SpringBoard
停在哪个函数的哪一行——那才是这条链真正的入口。

---

## 十一、两线同步记录（2026-11-08 17:25）

这份文档由两条线共同维护，合并时以此节为准。

### 已完成（Codex 线，实测）

- 系统**已进入桌面**：图标、Dock、壁纸、状态栏全部正常，显示链路彻底打通
- 快照探针实测：SpringBoard 阻塞在 **LaunchServices 数据库请求**，backboardd 的 90s 样本在同一等待链，`lsd` 服务线程等数据库 seeding、注册线程仍在执行应用注册
- 纠正了三处早期判断：
  1. 两个改写地址在 **QuartzCore**（`AccelServer::renderer()` / `IOMFBDisplay::framebuffer_pixel_format()`），不是 SpringBoard
  2. `renderer()` 返回空会进入 `sw_renderer()` 原生软件路径，不能推断「没有渲染器」
  3. `wifi-bootstrap` 不占 MIG 端口；端口由 `HideUntilCheckIn` 策略控制，helper 只在真实 WLAN 注册后请求电源
- 工具：`tools/read-recovery-apfs.py`（TWRP 里直接解 APFS 读日志）、`tools/symbolicate-pong-snapshot.py`（按 UUID 匹配符号）

### 已完成（内核线，本轮）

- 触摸与按键**同时**失效的根因：内核按绝对路径 `/arm-io/pong-touch`、`/arm-io/pong-buttons` 查找，DTS 却把节点声明在根上，生成器据此产出 `/rmx3551-touch`、`/pong-buttons` → 两个驱动都 `SKIP`
- 修复：节点移入 `apss: soc` 总线，并由 `unixnu,adt-name` 命名（与 `ufs → /arm-io/ufshc` 同一机制）
- 证据（本次启动日志）：
  ```
  Pong touch: missing/incompatible Pong DT; SKIP
  Pong keys: missing/incompatible DT; SKIP
  Pong touch HID: real touch device unavailable (Operation timed out); SKIP
  Pong keys HID: verified PMIC input unavailable; SKIP
  ```

### 下一步（按顺序）

1. 构建 `a6e0273` 的产物 → 打包 boot → `fastboot boot`
2. 验证三行是否出现：
   ```
   Pong touch: Berlin-D ready, SPI 0x990000 ..., axes 1080x2412
   Pong keys: ... ready
   Pong touch HID: display-integrated digitizer opened
   ```
3. 若触摸仍不通：用 `tools/read-recovery-apfs.py` 收集日志，重点看 `Pong touch HID: type=… finger=… xy=…`（有这行说明内核出点、用户态在投递）
4. 若出点但 UI 无响应：问题在 HID 事件投递/坐标映射，改 `userland/touch.c`，不再是 DT

### 协作约定

- 两线共用一个工作区。**提交前先 `git status`**，别把对方的未提交改动覆盖掉
- 构建只认 `main` 上的提交；工作区改动不会被 CI 采纳
- 日志/镜像统一放 `D:/unixnu/ud`，诊断目录带时间戳

---

## 十二、USB 专项（2026-11-08 19:45）

### 已确认的因果链

```
PongUsb 是纯头文件实现（drivers/PongUsb/*.h）
        └─ 只被 drivers/PongPower/PongPower.cpp 包含
              └─ 编译入口 scripts/build-pong-power-native.py → libPongPower.a
                    └─ 由 build-xnu-ipados18.sh 在 XNU_PONG_POWER=1 时 force_load 进内核
```

**实测**：内核 `kernel.macho`（51777536 字节）里
`ArmDTPlatform` 39 处、`Pong touch` 6 处，但
`pong_power_start_optional` **0** 处、`audio classes ready` **0** 处 → **电源归档从未进内核**。

所以 `pong_usb=1`、`pong_usb_mux=1`、`pong_usb_iphone=1` 全部落空，日志里一条 USB 记录都没有。

### 尝试与结果

| 尝试 | 结果 |
|---|---|
| 修 defconfig 的 CRLF + 解析器 `strip()` | 正确但有副作用：**所有**开关同时生效 |
| 工作流显式 `env: XNU_PONG_POWER=1` | 构建停在 `test -f "$CRYPTO_ARCHIVE"` |
| 只导出 POWER、并让环境变量优先于 .config | 仍停在同一行 |

失败行在**构建树里的脚本第 953 行**，而设备仓库同一测试在第 771 行——**两者不是同一份文件**，
说明构建树里的脚本是拼接过的。要继续必须先把这一点搞清楚（已在工作流加诊断步骤，失败时会打印该区域）。

### 下一步（任选其一）

1. **关掉会牵连的开关**：`CONFIG_XNU_SOURCE_CORECRYPTO14` 及其依赖链，只让 POWER 生效
2. **单独构建归档**：先用 `scripts/build-pong-power-native.py` 生成 `libPongPower.a`，
   再通过 `XNU_EXTRA_LD_ARCHIVES`（build-xnu-ipados18.sh 会读取）注入
3. **修上游**：定位构建树脚本的来源（kit merged-scripts / 工具链 pin），从源头修正

### 顺带结论

触摸/按键驱动**在内核里**（字符串已确认），它们的失效纯粹是 DTS 路径问题，与 USB 这条链无关。
