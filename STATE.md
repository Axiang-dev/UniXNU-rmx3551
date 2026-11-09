> Historical notes. For the current, evidence-based status and next actions, see [`PROGRESS.md`](PROGRESS.md).

# rmx3551 移植进度（截至 2026-11-05 00:30）

realme GT2 大师探索版 / RMX3551 / SM8475(cape) / 项目号 21605
两条线：**UEFI（已完成）**、**UniXNU 内核（在建）**。

## 一、UEFI：已完成，可进 UniXNU 菜单

产物：`D:\uefi`（Mu-Silicium）+ `D:\unixnu\UniXNU-rmx3551`（打包）
刷写方式：`fastboot boot out/rmx3551-uefi.img`（临时启动，不写分区）

已验证可用：
- 帧缓冲 0xB8000000 直写日志上屏（`FrameBufferSerialPortLib`，DEBUG 构建）
- 内存表由设备 `uefi` 分区里的 `uefiplat.cfg` 直译（44 区域）
- MMU 必须打开（`ArmConfigureMmu`），否则非对齐访问触发 Data Abort
- DxeCore 需要七个架构协议驱动（Watchdog/Capsule/Variable/MonotonicCounter/Reset/RTC/Metronome）
- 驱动顺序：SimpleFbDxe 必须在 ConPlatform/ConSplitter/GraphicsConsole 之前
- **音量键/电源键已端到端可用**（UniXNU 菜单可上下选择、电源确认）

按键地址（实测确认，与 pong 的 dts 完全一致）：

| 键 | 芯片 | 地址 | 位 |
|---|---|---|---|
| 音量下 | PM8350 (SID1) GPIO6 | 0x8D10 | bit0，低有效 |
| 音量上 | PMK8350 (SID0) PON | 0x1310 | bit6（GEN3 RESIN） |
| 电源 | PMK8350 (SID0) PON | 0x1310 | bit7（GEN3 KPDPWR） |

关键实现（`Platforms/Realme/rmx3551Pkg`）：
- `Library/RmxSpmiLib` — SPMI PMIC Arbiter v7 读，命令字 `(opc<<27)|(sid<<20)|(addr<<4)|(bc)`
- `Library/KeypadDeviceLib` — 三键 → 上下/回车，100ms 去抖
- `KeypadDeviceDxe` 自己装 `gEfiConsoleInDeviceGuid`（ConSplitter 只认这个）
- `KeypadDxe` 只发布 `SimpleTextIn`，不发布 `SimpleTextInEx`（否则 ConInEx 偏移 -0x28 崩溃）

## 二、启动链：Stage 1-4 通过，Stage 5 内核裸跑（2026-11-06 03:15）

仓库：https://github.com/Axiang-dev/UniXNU-rmx3551 （本地 `D://unixnu//UniXNU-rmx3551-device`）
做法：按 pong（Nothing Phone 2，同为 SM8475）的 format2 四层结构复用，只改设备层。
两条线并行：**固件（D://uefi，Mu-Silicium）** 和 **内核/payload（CI）**。

### 现在的位置（官方 docs/porting/bring-up.md 的七阶段）
| 阶段 | 状态 | 证据 |
|---|---|---|
| 1 UEFI | ✅ | `fastboot boot` 起 Mu-Silicium，帧缓冲日志上屏，音量/电源键可用 |
| 2 UniXNU | ✅ | 菜单出现，配置解析，按键选择 |
| 3 Payload | ✅ | 屏幕 `config: \EFI\UniXNU\unixnu.toml`，菜单列出 `RMX3551 iPadOS 18.7.10` |
| 4 DarwinBoot | ✅ | `DARWINBOOT: hand-off to the kernel`、`Exiting boot services` |
| 5 Kernel entry | ✅ | ArmCpu 接管 GIC、8 核注册、apfs 加载；停在等根设备（无 panic） |
| 6 Storage/root | ⛔ | 未开始：payload 无 scratch-data.img，设备无 pong userdata |
| 7 Userland | ⛔ | 未开始 |

### 内核侧已修（CI，每一轮都是真 bug）
1. 缺 `fetch-pong-native-sources.py`（Apple 6 源 + 板级 4 源）
2. `/Volumes/PongDev` 硬编码 → `PONG_WORK_ROOT` / `PONG_INPUT_ROOT`
3. 缺 `volume-layout.json` → uuid5 占位（`configs/ci-volume-layout.placeholder.json`）
4. defconfig 用错 → 必须 `pong_ipados18_ci_defconfig`
5. 缺 kernelcache → `prepare-ipados18-components.py --remote` 提三件套
6. 缺解压 → `decompress-ipados18-kernelcache.py`（要 `lzfse` CLI）
7. **`libPongPower.a` 开关错位**：`scripts/build-xnu-ipados18.sh` 里构建与
   `-force_load` 写成 `WIFI || BACKLIGHT` 而非 `POWER`，NativeUfs 的
   `pong_smmu_lease_lock/unlock` 永远缺定义（静态链接不认 weak_import）
8. `scripts/build-pong-power-native.py` 漏编 `PongPlatformResources.cpp`；
   并加「无 `tfa98xx.cnt` 时只编平台资源」分支

### 固件侧已修（D://uefi，都是“开关没连上”类问题）
1. `rmx3551.dsc` 从未定义 `PONG_INITRD_DISK_ENABLED` → `!if` 恒假，
   `Rmx3551BootMemoryDxe` 根本没进固件（这是 `no boot entry found` 的根因）
2. `Include/DXE.inc` 缺 FAT 栈 → 补 `DiskIoDxe`、`PartitionDxe`、`EnglishDxe`、
   `FatPkg/EnhancedFatDxe`（四个 .efi 早就编出来了，只是没进 FV）
3. `Library/MemoryMapLib/MemoryMapLib.c` 只转录了低 4 GiB（唯一大块 Conventional
   247 MB），DarwinBoot 要 4 GiB 窗口 → `Out of Resources`。从设备 DT 的 `/memory`
   取真实布局（5 段 12 GiB），补 `DDR High 0x0900000000 + 0x0180000000`

### Stage 5 当前 panic
```
_xnu Version 24.6.0 ... DEVELOPMENT_ARM64_PONG
_startup(1) init/thread time: 78911616 microseconds
VM bootstrap done: 3 maps, 115 entries and 117 holes left
panic(cpu 0): kalloc.c:1798 Assertion failed: n_zone_sig + n_zone_type * 1 < 32
```
对应 `kalloc_type_create_zones_fixed()` 的 `assert(n_zones_sig + n_zones_type + 1 <= 32)`，
只有 `kt_fixed_zones`（`ZSECURITY_CONFIG_KT_BUDGET`）> 0 时才跑。待查它从哪个
boot-arg / 配置来，以及为何我们的签名数超过 31（pong 同补丁集、同参数）。

### 启动参数现状（board.toml [payload] kernel_args）
与 pong 逐字节相同的部分之外，本轮新增两个诊断参数：
`-v`（文本控制台）和 `boot-progress=1`（官方屏幕诊断页）。补丁集
`patches/xnu-ipados18/*` 与 pong **逐字节相同**。

## 三、工具与坑（下次接手先看这段）

### 本机构建（Windows）
- 一键：`D://unixnu//UniXNU-rmx3551//build-with-payload.cmd`
  编译固件 → 校验 5 个驱动入卷 → 打 bootimg → 套 PONGFAT1 → 拼 ramdisk
- 单独打包：`tools\pack-bootimg.py`、`tools\pack-payload-bootimg.py`
- `build_uefi.py` 会以非 0 退出但无编译错误（EDK2 假失败），看 FD 是否存在；
  后台跑必须用工具的后台模式，`&` 会被杀
- `unixnu build firmware` 是 POSIX 驱动，Windows 上跑不了，所以有 build.cmd 这套

### 网络
- hosts 把 `api.github.com` 指到 127.0.0.1（Watt）：curl 加
  `--resolve api.github.com:443:20.205.243.168`；git push 要
  `env -u https_proxy -u http_proxy GIT_SSL_NO_VERIFY=1`

### 无 PAT 读 CI
- 失败日志：workflow 推到 `ci-logs` 分支，
  `git show origin/ci-logs:runs/<run_id>-attempt1.log`
- 产物：受控浏览器 CDP `Page.setDownloadBehavior` 打开
  `https://github.com/<owner>/<repo>/actions/runs/<run>/artifacts/<id>`

### 判读要点
- `PONG INITRD: source …/Success` = 块设备发布成功
- 绿条是 **shim** 启动时画的，不能当作内核已执行
- 内核 Debug 版在 panic 后会停屏，适合拍照

## 四、下一步（按 bring-up.md）

1. **拍全 panic 行**（右侧被截断）→ 定位是哪个 `kalloc_type` 调用点
2. 查 `ZSECURITY_CONFIG_KT_BUDGET` / `kt_fixed_zones` 的来源
   （boot-arg `zsecurity=` 一类），对比 pong 是否未启用
3. 对照实验：去掉 `-v` + `boot-progress=1` 跑一次；必要时在 CI 配置里
   临时关掉 `PONG_POWER`（它是链接需要才打开的，可能是多出来的 zone 来源）
4. Stage 5 通过后才是 Stage 6：19 GB userdata（含 `tfa98xx.cnt`、`adsp.mbn`）

## 五、收尾待办
- 删 GitHub token（用后即删，本地不留明文）
- `ci-logs` 分支会累积日志，需要时清一次

## 六、板级事实（rmx3551）
- 屏：NT37701B，1080×2412；触摸：Synaptics S3910（SPI@990000，IRQ TLMM21 / reset TLMM20）
- 内存：12 GiB（0x80000000 + 0x3_00000000，与 pong 相同）
- 另有 Pixelworks 显示芯片（i2c@880000），pong 没有
- 无厂商 DXE 固件可用（uefi/xbl/abl 的 PE 签名全为 0），这也是按键必须自己写 SPMI 驱动的原因
