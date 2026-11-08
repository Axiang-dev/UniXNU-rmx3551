# 内核 USB 调试口（liuqin）

从 vermeer 实验室仓库（github.com/xyyyds0106/ios-vermeer-lab 的 USB-DEBUG.md 与
xnu/vermeer/vermeer_usb_debug.c）移植到 Xiaomi Pad 6 Pro / liuqin / SM8475。

## 是什么

内核里一个 opt-in 的 USB CDC-ACM 串口，把内核 console 输出（1 MiB 环形缓冲）流给主机，
并提供四条只读命令。没有 shell、没有任意内存读、没有存储/重启操作。

    VID:PID      1209:0002   （实验室 ID；vermeer 用 1209:0001，用 PID 区分两台机器）
    伪序列号      LIQDBG001   （Windows 靠它认出正确的 COM，不会误选别的串口）
    波特率        115200 8N1  （对 USB 只是名义值）
    端点          EP0 控制 / EP1 IN 应答 / EP2 OUT 命令 / EP3 IN 日志流 / EP5 IN CDC notify

命令（每条一行）：`help` `status` `ping` `replay`

## 开关

board.toml 的 `[payload] kernel_args` 里加 `liuqin_usb=1`（默认已加）。
一次性覆盖：

    ./unixnu build payload --kernel-arg liuqin_usb=1

打开 COM 口必须置 DTR，否则内核一个字节都不会发（transmit() 里的 u.dtr 检查）。

## 移植时换掉的常量（都是 SM8475 的实测/文档值）

| 项 | vermeer (SM8550) | liuqin (SM8475) | 依据 |
| --- | --- | --- | --- |
| DWC3 基址 | 0xa600000 | 0xa600000（wrapper 窗口 0xfc100） | linux sm8450.dtsi usb@a600000 |
| QSCRATCH | base+0xf8800 | base+0xf8800 = 0xa6f8800 | 落在同一 wrapper 窗口内 |
| GCC 块 | 0x139000 (gcc+0x39000) | 0x149000 (gcc+0x49000) | linux sm8450.dtsi clock-controller@100000 |
| USB30_PRIM GDSC | +0x04 | +0x04 → 0x149004 | gcc-sm8450.c usb30_prim_gdsc |
| master halt | +0x18 | +0x18 → 0x149018 | gcc-sm8450.c gcc_usb30_prim_master_clk |
| cfg_noc halt | +0x88 | **+0x84** → 0x149084 | gcc-sm8450.c gcc_cfg_noc_usb3_prim_axi_clk |
| aggre halt | +0x8c | **+0x88** → 0x149088 | gcc-sm8450.c gcc_aggre_usb3_prim_axi_clk |
| APPS SMMU | 0x15000000 | 0x15000000（窗口 0x100000） | linux sm8450.dtsi iommu@15000000 |
| USB stream ID | 0x40 | **0x00** | linux sm8450.dtsi usb_1 的 iommus |
| DMA 窗口 | 0x8c0000000..0x940000000 | 0x80000000..0x100000000（可覆盖） | liuqin DDR 底 0x80000000 |

注意 cfg/aggre 的偏移和 SM8550 差 4 字节：照抄 vermeer 会读到错的寄存器。

## 四道自检门（任一不过就完全不碰控制器，系统照常启动）

1. **GCC**：GDSC bit31 必须为 1（power domain 已开），master/cfg/aggre 三个 halt 寄存器 bit31 必须为 0。
   本驱动从不写 GCC。
2. **控制器身份**：GSNPSID 高位必须是 0x5533/0x3331，GCTL 的 mode 必须是 2（device）。
3. **SMMU**：要求恰好有一条 SMR 匹配 USB stream ID，且路由是 identity/bypass
   （S2CR type=1，或 type=0 + CBAR type=1 + SCTLR 未使能）。绝不新建映射、绝不放宽隔离。
   bring-up 阶段如果板上 SID 与预期不同，日志会打印 `SIDx matches N`，
   可临时用 `liuqin_usb_sid=0xNN` 改 SID、`liuqin_usb_smmu=0` 跳过这道门（仅诊断用）。
4. **DMA**：16 KiB 永久连续块，必须整个落在窗口内、16 KiB 对齐、不超过控制器地址宽度。
   窗口可用 `liuqin_usb_dma=0x80000000,0x100000000` 覆盖；被拒时日志打印实际 PA。

通过后：停 RUN → 等 HALTED → 软复位 → 装 4 KiB event ring → DCFG 只跑 high speed →
epcmd(START_CONFIG/SET_CONFIG/SET_RESOURCE) → 写 QSCRATCH 的 VBUS-valid 覆盖位 → RUN → 1 ms 轮询线程。

## 代码落点

    补丁  patches/xnu/zzz-liuqin-usb-debug.patch   （必须排在内核补丁最后：zzz-boot-progress 之后）
    新增  bsd/dev/liuqin_usb_debug.c    传输层（DWC3 寄存器直操）
          bsd/dev/liuqin_debug.c        RAM 环形缓冲
          bsd/dev/liuqin_log_ring.h     1 MiB 环形缓冲
          bsd/dev/liuqin_usb_protocol.h 描述符 + 控制请求白名单
    挂点  osfmk/console/serial_console.c  _cnputc() 里做镜像（在 boot_progress 抢走之前）
          pexpert/arm/pe_kprintf.c       serial_putc_crlf() 里镜像早期 PE 输出
          bsd/kern/bsd_init.c            bsd_init() 里启动（load_init_program 之前）
          bsd/conf/files.arm64           注册两个目标文件

`patches/xnu/` 在设备仓库里是完整的一份（49 个 UniXNU 基础补丁 + 本补丁），
因为模块是按目录覆盖的：设备仓库一旦提供 patches/xnu，就会替换基础仓库的同名模块。
升级 UniXNU 基础补丁后要重新同步（见下）。

## 主机侧抓取（Windows）

    powershell -File tools/capture-liuqin-debug.ps1 -Seconds 600

脚本按 VID_1209&PID_0002 + 序列号 LIQDBG001 精确定位 COM，置 DTR/RTS，115200 8N1，
滚动写 32 MiB 一个文件；`-ObserveFrames` 这类 GUI 计数在 liuqin 上不适用（没有 GUI 采样器）。

## 已验证 / 未验证

已验证：补丁在 xnu-10063.141.1 + 49 个 UniXNU 补丁的树上 `git apply` 干净通过；
`tests/liuqin_usb_host_test.c` 覆盖环形缓冲、控制请求白名单、DMA 窗口判定、SMMU 流匹配，
gcc 全绿；两个新增 C 文件用 XNU 桩头文件 `gcc -fsyntax-only` 干净通过。

未验证（需要真机）：控制器是否真的停在 ABL 留下的 device mode、SMMU 是否给 USB SID 建了
identity 路由、DMA 落在哪个 PA。第一轮上机的判读方法：屏幕（boot-progress）或串口会打印
`LIUQIN USB: GCC .../ id=.../ SIDx matches .../ DMA ...`，其中任何一行被拒就说明卡在哪道门。

## 已知限制（沿用 vermeer 的设计）

- 拔线、主机发总线复位、event ring 溢出 → 端口停下并保留 DMA，必须重启内核才能重连；没有 panic 时轮询。
- 只有日志和四条只读命令，不是交互式调试器。
- `boot-progress=2` 时屏幕仍归 boot_progress 所有，USB 镜像的是同一份字节流，两边不冲突。

## 在 GitHub Actions 的 macOS runner 上编内核（不用租 Mac）

UniXNU 自带 `.github/workflows/macos.yml`（runs-on: macos-latest），输入里可以指定
设备仓库、分支、defconfig 和步骤。这台机器直连不了 github.com 但 api.github.com 通，
所以建仓/上传/dispatch/取产物全部走 REST API：

    GITHUB_TOKEN=<PAT> python3 tools/gh-build-liuqin.py --dry-run   # 先看要做什么
    GITHUB_TOKEN=<PAT> python3 tools/gh-build-liuqin.py --steps kernel

它做四件事：
1. 建 `<账号>/UniXNU-liuqin` 仓库，用 Git Data API 上传本仓库 68 个文件（不需要 git push）；
2. fork UniXNU，把分支 `liuqin-build` 钉在 `7b52e7968c76453cdc18b5aa174fc368d5293b91`
   —— 补丁就是对着这个提交验证的，避免 main 漂移；
3. 用输入 `device_repository / device_ref / defconfig=liuqin_defconfig / steps=kernel` dispatch；
4. 等跑完，把 `unixnu-liuqin_defconfig.zip` 下到 `~/liuqin-gh/`。

跑完的内核在本机打包（payload 要 unique-chip-id，留在这边做）：

    mkdir -p ~/port/UniXNU/out/liuqin/kernel && unzip -j ~/liuqin-gh/unixnu-liuqin_defconfig.zip '*/kernel.macho' -d ~/port/UniXNU/out/liuqin/kernel/
    scripts/pack-bootimg-liuqin.sh
    fastboot boot ~/port/UniXNU/out/liuqin/boot/boot.img

设备仓库默认建成 **public**：workflow 用 `github.token` 去 checkout 设备仓库，
默认 token 只能读 workflow 所在仓库，public 才免配置。要 private 就得在 fork 里加
`UNIXNU_DEVICE_TOKEN` secret（脚本没有替你设，需要的话手动加或告诉我）。
fork 的 Actions 默认是关闭的，脚本会尝试用 API 打开；如果 dispatch 报
"workflows are disabled"，在 fork 的 Actions 页面点一次 Enable 即可。
