# rmx3551 复用清单（对照 UniXNU-pong）

来源：`D:\unixnu\UniXNU-pong`（Nothing Phone (2)，同为 SM8475）
官方依据：`migration/format2/README.zh.md` 的「配置归属」四层表

## 四层归属

| 层 | 来源 | 本仓库处理 |
|---|---|---|
| ARM64 | UniXNU 上游 | 不复制，构建时引用 |
| SM8475 | pong 的 `migration/format2/soc-seed/` | 原样复制，未改 |
| OS | pong 的 `os-profiles/ipados-18.7.10-22H374/` | 原样复制，未改 |
| 设备 | 需为 rmx3551 新建 | 已改名生成骨架 |

## 直接复用（一行未改）

- `migration/format2/soc-seed/` — SM8475 的 dtsi / configs / kits / patches
- `os-profiles/ipados-18.7.10-22H374/` — Darwin 24 / XNU 11417.140.69 / iPad7,11
- `patches/xnu-ipados18/` — 设备层 XNU 补丁（含 `MASTER.arm64.pong`）
- `configs/` — 含 `pong_ipados18_defconfig`
- `board.toml [ipsw]` — 同一份 iPad 母本，与手机型号无关
- `board.toml [kernel]` 的 `config_fragments` 与 `patch_series` 前三项（arch / soc / os 层）

## 已改（仅板级标识）

- `board.toml`：`name`、`description`、`kit`、`device_tree.source`、`components.include`、
  `[firmware].config/dsc/fd/packages`、`[payload].title`
- `dts`：文件名 `pong.dts → rmx3551.dts`、`model`、顶层 `compatible`

## 故意没改（驱动靠它匹配）

- `compatible = "pong,pm8350-keys"` — XNU 侧 pm8350 按键驱动按此匹配
- `pon-ppid = <0x13>` = SID0 page 0x13 → **0x1300**（与 UEFI 实测一致）
- `volume-up-ppid = <0x18d>` = SID1 page 0x8D → **0x8D00**（同上）
- `kernel_args` 里全部 `pong_*` 参数（`pong_wifi` / `pong_audio` / `pong_disable_swap` …）

> 这三条是本次最有价值的对齐：pong 的按键 ppid 与我们在 rmx3551 UEFI 里逐位验证的
> 结果完全相同（PON 在 SID0 0x1300、音量下在 SID1 0x8D00、GEN3 位 6/7）。

## 必须为 rmx3551 重写（pong 专属硬编码）

- `drivers/` 下 12 个 submodule：屏幕 NT37705、触摸 goodix-berlin、WiFi QCA6490、
  UFS 参数（`smmu-stream-id 0xe0` / `ufs-spi 265` / `gcc page 0x187000`）都写着 pong 的值
- `dts` 的 `pong-touch` / `pong-buttons` 节点：结构可抄，值需按 rmx3551 实测
- `[firmware]` 的 `preflight = scripts/build-pong-hardware-dtb.py` 仍是 pong 的脚本

## 待确认的两个硬数字

1. **内存容量**：pong 写 12 GiB（`0x3_00000000`）。rmx3551 的 Android dts 给出多段
   不连续区间，需按实际容量填；填错会让 XNU 拿到错误的 `dram-size`。
2. **触摸 IC**：rmx3551 不是 goodix-berlin-d，需从 Android dts 确认后改 `pong-touch`。
