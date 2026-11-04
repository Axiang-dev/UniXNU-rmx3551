# 推到 GitHub 之前的全部操作

目录：`D:\unixnu\UniXNU-rmx3551-device`（已 `git init` + 一次 commit，分支 `master`，333 个文件，约 2.2 MB）

## 1. 在 GitHub 建一个空仓库

名字随意，建议 `UniXNU-rmx3551`。**不要**勾选 README / .gitignore / license，要空仓库。

## 2. 推上去

```sh
cd D:\unixnu\UniXNU-rmx3551-device
git remote add origin https://github.com/<你的用户名>/UniXNU-rmx3551.git
git push -u origin master
```

## 3. 加仓库 secret

Settings → Secrets and variables → Actions → New repository secret

- Name: `UNIXNU_UNIQUE_CHIP_ID`
- Value: `21605000`

这个值是自己定的 8 位十六进制"平台种子"（不是从硬件读的），编进镜像里标识这台设备。`21605` 是项目号，后面补 `000`。

## 4. 跑 workflow

Actions → **RMX3551 porting record** → Run workflow。

这个 workflow 做三件事：
1. checkout 本仓库
2. checkout `UniXNU/UniXNU` 工具仓库（指定 commit，**CI 自己拉，你不用下载**）
3. 跑 `scripts/install-unixnu-inputs.py` 装 22H374 profile，然后 `porting-record.py check`

## 预期结果

**第一次大概率会失败**，而且是好事——它会准确告诉我们缺什么。最可能在：

- `install-unixnu-inputs.py` 里还在找 `PongPlatform24`，而我们的 kit 已改名 `Rmx3551Platform24`
- `porting.toml` 的 `[[area]]` 里有 `paths` 指向 `drivers/PongPower/...` 这类不存在的路径
- `board.toml` 引用的 `scripts/build-pong-hardware-dtb.py` 仍是 pong 的

失败日志直接发给我，我按报错逐条修。**这一步通过之后**，才轮到真正的内核编译（那需要再写一份 `package.yml`，把 `uefi-pong` 换成我们自己的固件源）。

## 没有推上去的东西（故意）

- `drivers/` —— pong 的 12 个 submodule，是板级硬编码（goodix 触摸 / NT37705 屏 / QCA6490），rmx3551 用不了，先不引
- `.github/workflows/package.yml` —— 547 行，深度绑定 `uefi-pong` 仓库和 20 多个 pong 脚本，改名成 `.pong-reference` 留作参考，暂不触发
- `.gitmodules` —— 已删除，避免 checkout 去拉不存在的 submodule

## 板级事实（已确认，供改代码时对照）

| 项 | rmx3551 | pong |
|---|---|---|
| SoC | SM8475 | SM8475 ✔ |
| 内存 | 12 GiB @ 0x80000000 | 12 GiB ✔ |
| 分辨率 | 1080×2412 | 1080×2412 ✔ |
| 按键 | PON ppid 0x13 / GPIO ppid 0x18d | 完全相同 ✔ |
| 触摸 | Synaptics S3910, SPI@990000, IRQ TLMM21, RST TLMM20 | goodix-berlin ✘ |
| 屏幕 | NT37701B | NT37705 ✘ |
| 额外 | Pixelworks 显示芯片 (i2c@880000) | 无 ✘ |
