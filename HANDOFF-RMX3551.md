# RMX3551 · UniXNU / iPadOS 18 移植交接文档

> 用户最终目标保持不变：**参考 UniXNU 官方仓库和文档，成功启动 iOS 并进入桌面**。
> 2026-11-10 已确认 iPadOS 18.7.10（22H374）进入 SpringBoard 桌面；当前主任务是修复 S3910 触摸。

初次写作：2026-11-08 15:30（GMT+8）。最近更新：2026-11-10 18:15（GMT+8）。
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

## 最新接手快照（2026-11-10 18:15，GMT+8；本段优先）

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
