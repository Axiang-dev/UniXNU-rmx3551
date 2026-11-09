# UniXNU-rmx3551

realme GT2 大师探索版（RMX3551 / SM8475 / cape）的 UniXNU 格式 2 设备仓库。

## 来源

骨架复制自 [UniXNU-pong](https://github.com/Chengdong-Yu/UniXNU-pong)（Nothing Phone (2)，同为 SM8475），
按 `migration/format2/README.zh.md` 的四层归属改造：

| 层 | 处理 |
|---|---|
| ARM64 / SM8475 / OS | 原样复用（soc-seed、os-profiles、第一至三层补丁） |
| 设备 | 本仓库，按 rmx3551 实测改写 |

## 已确认的板级事实

| 项 | 值 | 确认方式 |
|---|---|---|
| SoC | SM8475 (cape) | 平台信息 |
| 内存 | 12 GiB @ 0x80000000 | Android `/memory` 多段合计 11.8 GB |
| 屏幕 | NT37701B，1080×2412 | `platform_support_project_commandline` |
| 触摸 | Synaptics S3910，SPI@990000，IRQ TLMM21，RST TLMM20 | Android dts，focaltech 为 disabled |
| 音量下 | PM8350 (SID1) GPIO6 RT_STS，ppid 0x18d | UEFI 逐位实测 |
| 音量上 / 电源 | PMK8350 (SID0) PON 0x1300，ppid 0x13，GEN3 bit6 / bit7 | UEFI 逐位实测 |

按键三项与 pong 的 `pong-buttons` 节点**完全一致**，因此该节点连同
`compatible = "pong,pm8350-keys"` 保持原样未改。

## 当前状态

完整、按证据分级的进度和下一步见 [`PROGRESS.md`](PROGRESS.md)。

- [x] UEFI 点亮、显示和 ConIn 可用
- [x] iPadOS 18.7.10（22H374）进入 SpringBoard 桌面
- [x] 1080×2412 显示表面、软件 UI、TextInput 和屏幕键盘可用
- [x] 确认 S3910 与实体键的真实 ADT 节点位于 `/soc`，并提交路径修复
- [ ] S3910 新内核编译与 stage-3 真机复测
- [ ] 触摸 HID、实体音量键
- [ ] USB；当前停在 SMMU 路由拒绝

已经验证可进入桌面的 `22e7b2c` 镜像和 SHA-256 记录在 `PROGRESS.md`，不得覆盖。

## 构建

见 `PUSH.md`。
