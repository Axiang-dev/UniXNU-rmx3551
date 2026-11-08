# RMX3551 · UniXNU / iPadOS 18 移植交接文档

> 目标只有一个：**让屏幕出图**（参考实现的里程碑是「3 次 swap + 苹果 logo」）。
> Home Screen 之后的事情一律不管。

写作时间：2026-11-08 15:30（GMT+8）
接手者请先读完「五、必须知道的坑」，那里每一条都是花掉整晚换来的。

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
校验 SpringBoard 后改两处：

```c
0x184393468 → 改成 return nullptr      // "stock CPU compositor"：让 GPU 渲染器工厂返回空
0x184396060 → 改成返回 BGRA 常量        // "software scanout BGRA"
```

**这两处是当前最可疑的地方**：如果系统里没有软件渲染器接上，「返回空」就等于
「没有渲染器」→ CA 永不提交 swap。这也是下面第一优先级的验证目标。

---

## 七、下一步（按优先级，全是可执行动作）

### P0 · 收集等待链（这一版镜像已经准备好）

镜像：`out/rmx3551-boot-payload.img`（kernel `777b1531`，已含 `pong_boot_snapshot=1`）

```bash
fastboot boot out/rmx3551-boot-payload.img
# 等 2 分钟（探针在 35s 和 90s 各写一次）
# 进 TWRP 后：
adb pull /data/logs/            # /private/var/logs 在 TWRP 里就是 /data/logs
```

期望拿到：`PongBoot-SpringBoard.txt`、`PongBoot-backboardd.txt`、
`PongBoot-PosterBoard.txt`、`PongBoot-wifid.txt` …

文件里有每个线程的 `pc / lr / fp / sp` 和 16 层栈回溯。

**符号化方法**：
`PC - slide` 后对 `SpringBoard` 二进制查（`slide` 在文件头 `image_slide=` 里），
或用 `atos -o SpringBoard -l <load addr>`。重点看 **主线程**卡在哪个符号。

### P1 · 判定 wifi 端口阻塞是否仍在

策略代码注释记录过：`services105 proves SpringBoard blocked in wifi_manager_open … preventing its first frame`。

实测 `wifid` 在 `WiFiManagerCreate` 里卡了 **36 秒**（16:02:07 → 16:02:43）。
`wifi-bootstrap` 的作用就是提前抢占这个 MIG 端口。

这一版已把 `wifi-bootstrap` 加进 `applog_name`，日志里应该能看到它到底跑没跑。

- 跑了且抢到 → 看 P0 的快照，SpringBoard 应该不在 wifi 上
- 没跑 → 查它的 plist 为什么没被 launchd 加载（缓存里已确认有作业，二进制也在 `/pong/wifi-bootstrap`）

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
