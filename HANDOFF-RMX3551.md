# RMX3551 · UniXNU / iPadOS 18 移植交接文档

> 用户最终目标保持不变：**参考 UniXNU 官方仓库和文档，成功启动 iOS 并进入桌面**。
> 2026-11-10 已确认 iPadOS 18.7.10（22H374）进入 SpringBoard 桌面；当前主任务是修复 S3910 触摸。

初次写作：2026-11-08 15:30（GMT+8）。最近更新：2026-11-10 17:43（GMT+8）。
接手者先读本页顶部的「最新接手快照」。后面的“黑屏、0 次 swap、尚未进桌面”等段落是历史排查记录，已被 2026-11-10 的桌面实测结果取代。

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

## 最新接手快照（2026-11-10 17:43，GMT+8；本段优先）

### 结论

iPadOS 18.7.10（22H374）已经进入桌面：显示发布为 `1080x2412 BGRA`，SpringBoard 可用，VSync 持续运行。最终目标中的“成功启动 iOS 并进入桌面”已经完成，当前瓶颈是把 Synaptics S3910 触摸真正接到 iPadOS。

触摸整体完成度约为 **60%–65%**，距离“桌面触摸可用”还差约 **35%–40%**。这个数字按当前证据估算，不是按代码行数估算：

| 环节 | 当前把握 | 证据 / 缺口 |
|---|---:|---|
| 供电、RESET、1.8 V、GPIO | 约 95% | 实机日志显示资源已打开，S3910 有响应 |
| QUP0/SE4、SPI/GENI/GPIO 位流 | 约 90% | 实机已经完整读出识别包，GENI 不可用时 GPIO SPI 生效 |
| TouchComm v1 识别与分帧 | 约 90% | 已取得 28 字节识别 payload；进入下一步初始化 |
| `GET_APPLICATION_INFO (0x20)` 与初始化 | 约 35% | 上一轮卡在 `STATUS_BUSY`；修正错误时序后的版本尚待实机复测 |
| 触点解析和坐标归一化 | 约 55% | 主机测试覆盖格式与边界；尚无真实触摸帧 |
| iPadOS 虚拟触控 HID 投递 | 约 65% | `userland/touch.c` 与 `/dev/pong-touch` 通路已存在；桌面尚未验收 |
| 真机端到端验收、方向和边缘手势 | 未验证 | 必须看到真实 down/move/up 事件并由桌面响应 |

### 当前设备与绝对安全边界

2026-11-10 17:40 的设备状态：

```text
9ea882b4 recovery product:twrp_ovaltine model:PGP110 device:ovaltine
```

目标机仍在本轮 TWRP 中，只检测到这一台。历史现场曾同时出现另一台：

```text
42d72758 device product:OPD2515 model:OPD2515 device:OP6548L1
```

**每一次 fastboot 命令都必须显式指定 `-s 9ea882b4`，绝不能操作 OPD2515。**

必须遵守：

- 只允许临时启动：`fastboot -s 9ea882b4 boot <诊断镜像>`。
- 不刷 `boot`、`userdata` 或其他分区；不执行 `fastboot -w`。
- 不执行 `git reset`、`git clean`；仓库里有大量不能删除的历史构建输入和日志。
- 新镜像必须使用新文件名，文件名带提交短哈希和 CI run ID。
- 不能覆盖已验证的桌面基线：
  `D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-usbdebug-22e7b2c-42510630419.img`
  SHA-256：
  `9574063d753bda2b190693aa720cd6d08c5dcfa7bc79ae03f17fff40a9c7cb63`

### 已经确认的触摸事实

2026-11-10 的预测读版本已经取得完整的 S3910 识别包：

```text
a5 10 1c 00 01 01 53 33 39 ...
payload 28 bytes
```

硬件日志还确认：

```text
Pong touch: S3910 QUP0/SE4 source=19200000 Hz FW=0x102 IF_DISABLE=0x1 FIFO=16
Pong touch: S3910 GENI unavailable ... SPI by GPIO
```

因此供电、GPIO、SPI 位流、TouchComm v1 预测读和分帧已经打通。原生触点坐标来自控制器应用信息，预计为 `8640x19296`；显示是 `1080x2412`，两轴正好相差 8 倍。不要把 `19296` 错写成 `19296` 之外的值，也不要拿显示分辨率替换控制器原生坐标。

上一个实机镜像的热点不是识别，而是识别后：

```text
Pong touch: S3910 identify failed rc=-110 stage=header detail=165 version=1 command=0x20
```

`detail=165` 即 `0xa5`，随后持续看到类似 `a5 02 00 00` 的 `STATUS_BUSY`。当时在 `0x20` 前错误发送了 `0x23`。官方 OnePlus S3910 的 `syna_tcm_identify()` 在应用模式识别后直接调用 `syna_tcm_get_app_info()`；`0x23` 是 `CMD_GET_DYNAMIC_CONFIG`，不是 report ID。

### 刚刚修好的 CI 错误

上一轮构建是：

```text
run 42788028166
commit 41909f1
```

编译器报：

```text
pong_goodix.c:6:2: error: unterminated conditional directive
pong_goodix.c:1359:3: error: expected '}'
```

根因不是触摸协议，而是 `patches/xnu-ipados18/0001-pong-darwin24.patch` 里的新文件 hunk 仍声明 1359 行，实际已有 1375 行。补丁应用时最后 16 行被截掉，包括文件末尾 `#endif /* PONG */`。

已做修复并推送：

```text
326d5ff fix: keep S3910 driver patch complete
```

修改内容：

- 把 `pong_goodix.c` 的 hunk 从 `@@ -0,0 +1,1359 @@` 修正为 `@@ -0,0 +1,1375 @@`。
- 在 `tests/test_rmx3551_s3910_protocol.py` 增加所有新文件 hunk 行数校验。
- S3910 主机协议测试已经通过：

```text
rmx3551_s3910_protocol_host_test.c
S3910 protocol host tests passed
```

当前新构建：

```text
run 42790314382
commit 326d5ff
workflow: RMX3551 kernel build
状态: success
artifact: rmx3551-kernel（artifact id 13751831596）
```

当前内核与 payload 已经下载、解压并验证完成。新 kernel 的 SHA-256 是 `0e08505d980fe2ba74978a6af59f63aeed4a6efcd10dda7d8777f9bb2014e0c5`。

### 下一步必须按顺序执行

1. **已完成**：CI run `42790314382` 状态为 `success`。
2. **已完成**：artifact `rmx3551-kernel` 下载到 `D:\unixnu\UniXNU-rmx3551\out\ci-326d5ff-42790314382`，没有覆盖旧目录。
3. **已完成**：新内核已经替换进已验证的 stage-3 payload，原 ADT/TOML 保持不变，`pong_s3910=3`。
   - payload：`D:\unixnu\UniXNU-rmx3551\out\payload-s3910-appinfo-326d5ff-42790314382.img`，SHA-256 `fe03c9a6bfa86cd171bbf0d4fc8bc2be2516281aad922ed22ad8dc6709a971ad`
   - boot：`D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-appinfo-326d5ff-42790314382.img`，SHA-256 `e1d25a7fa0b7ef4caff754127b34126549d4813f02a12bb6fedc65ca41013bca`
4. 用下面脚本把新内核替换进旧的 stage-3 payload，保留原 ADT 和 TOML：

```powershell
& 'C:\Users\27699\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B `
  'C:\Users\27699\Documents\Codex\2026-11-08\new-chat-2\tools\repack-stage3-kernel.py' `
  --source-payload 'D:\unixnu\UniXNU-rmx3551\out\payload-s3910-stage3-v1predictive-18eb972-42782839034.img' `
  --template-boot 'D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-stage3-v1predictive-18eb972-42782839034.img' `
  --kernel '<artifact>\build\...\kernel\kernel.macho' `
  --payload-output 'D:\unixnu\UniXNU-rmx3551\out\payload-s3910-appinfo-326d5ff-42790314382.img' `
  --boot-output 'D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-appinfo-326d5ff-42790314382.img'
```

脚本会验证：

- 源 payload 的 `unixnu.toml` 仍包含 `pong_s3910=3`。
- 新内核是 Mach-O。
- 替换内核后 ADT 和 TOML 未被意外改变。
- 新 boot 内的 `PONGFAT1` payload 与输出 payload 完全一致。

5. 先确认目标机仍为 `9ea882b4`，再临时启动：

```powershell
adb -s 9ea882b4 reboot bootloader
fastboot devices
fastboot -s 9ea882b4 boot 'D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-appinfo-326d5ff-42790314382.img'
```

6. 进入 UniXNU 菜单后选 iPadOS。stage 3 只验证控制器，不要期待触摸生效；它完成后会打印：

```text
Pong touch: S3910 stage 3 complete; HID publication disabled
```

7. 让系统运行到用户态并产生日志，然后回 TWRP 读取日志。成功条件：

```text
Pong touch: S3910 command 0x20 tx: 20 00 00
Pong touch: S3910 command 0x20 reply[...] code=0x1
Pong touch: S3910 identified ... axes=8640x19296
Pong touch: S3910 stage 3 complete; HID publication disabled
```

如果看到 `identified ... axes=8640x19296`，说明应用信息查询和初始化已成功，触摸完成度可上调到约 **75%**。

8. 只有 stage 3 成功后，才制作 `pong_s3910=4` 镜像。stage 4 才会创建设备节点并持续轮询触点；第一次真机验收要看到：

```text
Pong touch HID: display-integrated digitizer opened
Pong touch HID: type=1 finger=0 xy=...
s3910: finger 0 down at ...
```

9. 桌面触摸出现后，再校准方向、边缘手势和抬手。内核目前有 `touch_flip` 变换变量，但尚未根据 RMX3551 实测初始化；若方向相反，在这一层修，必须每次同时验证四角。

### 如果 `0x20` 仍然 BUSY

不要同时改 HID。按以下顺序缩小问题：

1. 先确认 TX 真的是 `20 00 00`，不是旧内核或 `0x23`。
2. 记录每次 `reply` 的 code、length 和 detail，确认是否仍全部为 `a5 02 00 00`。
3. 对照官方 `syna_tcm_identify()`、`syna_tcm_get_app_info()` 和 `syna_tcm_reset()` 的复位时序。
4. 对照 `D:\unixnu\UniXNU-OnePlus-Ace5\ios16\giulia_touch.c`；其中明确处理了冷启动 MISO 低电平重试，并在 app info 成功后才发送 disable raw report、LBP 和 report format。
5. 在 app info 成功前不要再修改触点解析器或 iPadOS HID；否则会把初始化故障与用户态故障混在一起。

### 关键源码与参考

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
- 历史实机日志：
  `C:\Users\27699\Documents\Codex\2026-11-08\new-chat-2\pong-debug-20261110-v1predictive-165507`

### 给下一个 AI 的直接接手话术

> 继续接手 RMX3551 的 UniXNU iPadOS 18 触控修复。先完整阅读 `D:\unixnu\UniXNU-rmx3551-device\HANDOFF-RMX3551.md` 顶部“最新接手快照”，并核对设备仓库 HEAD 是否至少包含 `326d5ff`。iPadOS 桌面已经可进，当前只处理 Synaptics S3910。CI run `42790314382` 已成功，stage-3 镜像已生成：`D:\unixnu\UniXNU-rmx3551\out\rmx3551-boot-s3910-appinfo-326d5ff-42790314382.img`。确认目标机是 `9ea882b4` 后，只对它执行临时 `fastboot boot`，进入菜单选 iPadOS；不要刷分区、不要碰第二台设备、不要改 HID，直到 `0x20` 成功并打印 `axes=8640x19296`。随后回 TWRP 读取 PongBootLog，并把结果完整写回本交接文档再继续。

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
