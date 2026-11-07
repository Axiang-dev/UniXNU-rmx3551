# iPadOS 18 首帧前的三处阻塞与诊断设施

目标版本 22H374 / Darwin 24，板级 SM8475（rmx3551）。本轮之前的状态是：内核能起、
三个 APFS 卷能挂、launchd 能跑 boot task，但屏幕永远停在日志，从未出现过一帧。

本文只记录有设备侧证据的部分；没有证据的项目留在「未验证」一节。

## 1. launchd.plist 验签失败被当成致命错误

现象是一块 panic 屏，最后一行是 `panic.apple.com`：

```
panic(cpu 0 caller 0xfffffff007af6abc): launchd_cache_loader[22] exited --
exit reason namespace 7 subcode 0x1 description: Failed to verify codedirectory
[-67062|errSecCSUnsigned]
```

`launchd` 把这个 boot task 标为 `RequireSuccess`，于是它的退出被内核转成 panic，
`init-with-data-volume` 之后的任何任务都不会执行。日志里的表现是控制台停在 `fips`。

修法是 loader 自己支持的开发开关，写进 `board.toml` 的 `kernel_args`：

```
launchd_unsecure_cache=1
```

它让原版 loader 装载本地适配缓存，不再把修改过的 plist 与原厂签名配对。

**证据**：修复后 `mount-phase-2` → `init-with-data-volume` → `keybag` → `usermanagerd`
→ `dirs_cleaner` → `init_featureflags` 全部出现，panic 屏消失。

## 2. ADT 缺少 display-scale，SpringBoard 主动 trap

现象是每轮稳定崩在同一地址：

```
Pong UI crash: SpringBoard[26] exception=6 code=0x1/0x19f5833e4
Pong UI crash: x0 text=FBSDisplayMode cannot be configured as requested :
               <FBSDisplayMode: ... infxinf@0x (1080x2412/0) 120Hz sRGB SDR>
```

尺寸 1080x2412 与 120 Hz 都对，唯独 scale 为 0，逻辑尺寸因此是 `inf × inf`，
FrontBoard 拒绝该模式，SpringBoard 在建主显示前 trap。连续十次之后 launchd 记
`Too many crashes`，不再重启它。

`board.toml` 的 `[payload.adt]` 注明 schema 2 由工具链按 os-profile 生成 ADT。
把 CI 产出的 payload 拆开、抽出 `kernel.macho.adt` 解析 `/chosen` 后确认：
`artwork-scale-factor` 在，`display-scale` 不在——pong 版生成器写的那条属性在切到
schema 2 时没有带过来。

修法是在 `os-profiles/ipados18-22H374/profile.toml` 里声明：

```toml
[adt.chosen.u32]
display-scale = 3
display-rotation = 0
```

**证据**：同一轮日志 `Pong UI crash` 计数归零；SpringBoard 在 adapter 装配后继续
映射 dyld 段，不再退出。

## 3. 服务策略层从未被调用

`userland/board_services18.py` 随 22H374 移植一起进入仓库，包含按设备证据调整的
job 策略（`wifip2pd` / `bluetoothd` 的节流、`softwareupdated` 禁用、
`com.apple.wifi.manager` 的 `HideUntilCheckIn`、`audiomxd` 的 `StandardErrorPath`
等），但**全仓库没有调用点**，镜像一直用原厂 job 缓存。

pong 的 `services105` 记录写明：`com.apple.wifi.manager` 在 `wifid` check-in 之前
就把发送权交给客户端，**SpringBoard 卡在 `wifi_manager_open`，第一帧进不来**。

修法是在已经挂载 OS 根目录的 `scripts/prepare-os-root.py` 里以 root 调用它：

```
sudo python3 userland/board_services18.py --stage-root <mount>
```

`board_services18.py` 为此新增 `--stage-root`，供已有挂载的调用方使用。

**证据**：本项截至本文写入时仍在验证——镜像重建在跑，尚未在设备上确认。

## 4. 日志设施（本轮新增）

`drivers/NativeUfs/PongBootLog.h`：把 `0x85200000` 的 4 MiB ramoops 镜像（12 字节
persistent_ram 头 + 2 MiB console 环 + 2 MiB diagnostic）写到 userdata 里镜像之后的
空洞（offset 20,821,573,632，即分区内 LBA 5,083,392）。头部最后落盘，掉电时保留上一份
完整快照。

- 每 2 秒读一次环的 `(start,size)`，**变化才写**，安静时零写入。
- 头部带 `tick` 心跳，每 2 秒 +1：控制台停住时用它区分「内核已死」与「内核活着、
  用户态卡住」。实测有一轮 tick 走到 295（590 秒）而控制台无新行。
- 读取必须用 `adb exec-out`；`adb shell` 会做 CRLF 转换，一次实测多出 1836 字节、
  二进制全毁。
- 解码：`python tools/read-pong-log.py decode region.bin`。

## 5. 帧路径追踪（本轮新增的启动参数）

```
fbtrace=8
surftrace=24
applog=1
applog_name=launchd,backboardd,SpringBoard,containermanagerd,lsd,runningboardd,logd_helper,powerd
```

`fbtrace` 记录每个 IOMFB selector 的前若干次调用；`surftrace` 记录前若干 surface 的
创建与去向；`applog` 把那批进程的 os_log 镜像到内核控制台。

**当前读数**：`backboardd` 调用了 selector 6/8/12/15/22/27/29/33/50/57/72/74/79/84/88，
其中 15/27/50/84/88 未实现；`surftrace` **一条 surface 都没有**——合成器尚未开始建面。
`SpringBoard[26]` 在 adapter 之后仍在映射 dyld 段，不崩溃、不退出、也不输出。

## 未验证 / 未完成

- 首帧：尚无 surface，配置 120 Hz 不等于已达到 120 fps。
- 触摸：`Pong touch HID: real touch device unavailable (Operation timed out); SKIP`，
  文档第 6 步（input）整块未做。
- 背光：官方 schema 2 的 ADT 不含 `pong-dsi-backlight`（64 字节结构），亮度控制不会工作。
- Data 卷：`mount_phase_two: Overprovision setup failed - error 13 (EACCES)`；
  seed 固定 8 GiB，未按 `seed-data-grow.py` 扩容。
- panic 落盘：panic 发生时写日志线程已停，文本只留在 RAM，仍需在内核 panic 路径补一次 flush。

## 主机记录

内核构建经 `kernel.yml` 的 `workflow_dispatch`，产物 `rmx3551-kernel`；boot 镜像用
`tools/pack-bootimg.py` / `pack-payload-bootimg.py` 以基线固件段重打，逐字节比对确认
固件段与回退镜像一致。设备侧临时启动使用 `fastboot boot`，未写 boot 分区。
