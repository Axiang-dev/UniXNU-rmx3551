# RMX3551 userdata 重建事故复盘（旧新拼接才启动）

- 设备：Realme RMX3551（SM8475 / pong 平台），iPadOS 18.7.10（22H374）
- 时间：2026-11-07 深夜 → 2026-11-08 03:00 查清
- 一句话结论：**CI 重建 userdata 时，把 SystemOS 与 Data 两个 APFS 窗口重新造了一遍，卷 UUID 全变；而内核和 ADT 里钉的是旧 UUID。**
  最终用「旧镜像为底 + 只覆盖新的 OS 窗口」的拼装镜像启动成功。

---

## 1. 起因：为什么非要重建 userdata

当时缺的是 **wifi-bootstrap 与 job 策略**——它们必须进系统卷才生效。

CI 有一条 `workflow_dispatch` 的 userdata 构建流程：

- 耗时约 1 小时
- 产出约 **19 GiB** 的完整镜像
- 因为 GitHub 单资产上限 2 GiB，切成 **20 个分片**发布（tag `userdata-22H374`），配 `userdata-image.json` 记录每片大小与整体 sha256

本地用 `join-userdata.py` / `join-userdata.cmd` 拼回来：逐片核对大小、按序拼接、校验总大小和 sha256。**这一步是可靠的**，问题不在拼接。

磨好的镜像结构：

```
SHNGROOT 头（1 MiB 内）
    → 1 MiB pad
    → OS 窗口（6.375 GiB）
    → SystemOS 窗口
    → Data 窗口
总长 20,821,573,632 字节（19.39 GiB）
```

---

## 2. 现象：刷进去就是起不来

`fastboot flash userdata` 之后启动，卡在：

```
panic: init died
launchd 在 /private/preboot/<uuid>/usr/libexec/launchd 加载
  /usr/lib/libSystem.B.dylib 失败
```

一开始的排查方向全在「文件缺失」上：

- 怀疑 `/usr/lib` 与 `/private/preboot/usr/lib` 都不存在
- 怀疑 dyld 缓存没注入到根卷 `System/Library/Caches/com.apple.dyld`
- 甚至为此写了一整条「把 3.7 GiB 缓存复制进根卷」的流水线，跑了 **3 轮、烧掉 2 小时**，最后证明方向错了

**误导点在于**：panic 说的是「加载 dylib 失败」，看起来像文件问题，实际是**卷根本没挂上**——路径自然就不存在。

---

## 3. 根因：两个窗口被重新造了

2026-11-08 00:30 查清。做法是把新旧镜像里所有 APFS 卷 UUID 扫出来，跟内核/ADT 里钉死的期望值对比：

| 卷 | 内核期望的 UUID | 旧镜像命中 | 新镜像命中 |
| --- | --- | --- | --- |
| SystemOS | `B57C18AA-9E49-44A4-B94A-ED191CFB4B0F` | 6 次 | **0 次** |
| Data | `47C0F5C3-B8C7-47AC-B9D9-F230BAED1576` | 3 次 | **0 次** |
| OS | `B07DF049-…` | 有 | 有（窗口是对的） |

**CI 的 userdata 构建会重新生成 SystemOS / Data 两个 APFS 容器**，UUID 全新；而内核与 ADT 里是钉死的旧 UUID，等不到就不挂载。

更隐蔽的一点：**数据门禁从未拦截**。

```
Data prepare enter          ← 打印了
cache_authorized            ← 通过
root_recheck                ← 通过
writable UFS Data Volume UUID unavailable   ← 死在这里
```

失败发生在「按 UUID 找卷」这一步，前面的检查全绿，所以日志看起来像是「都正常然后突然死」。

---

## 4. 第二个坑：以为刷了 A，其实刷的是 B

排查到一半时出现过极诡异的现象：明明做了 `fixed.img`，启动日志里却是另一套 UUID。

证据是日志里的 `window media uuid=58536139-…` —— 那是 **CI 新造的 Data 容器**，而内核等的是 `47C0F5C3-…`。

结论：**之前几次 panic 的镜像根本不是拼装出来的 `fixed.img`，而是 release 里那份原始的 `pong-ipados18-userdata.img`。**

也就是说，有一段时间我们在「分析一个新镜像的症状，却以为那是拼装镜像的」——白绕了一圈。

**教训**：每次刷机前把镜像的 sha256 与 UUID 指纹打出来，和日志里的对照，别靠文件名认人。

---

## 5. 应急手段（**不是通用解法**）

> 这一节是当晚救活机器的操作，**只对"手上已经有一个能启动的旧镜像"的人有效**。
> 别人从零构建时没有"旧镜像"可拆，所以真正的解法在第 6 节。

既然 SystemOS / Data 必须保持旧 UUID，而需要更新的只有 **OS 窗口**（wifi-bootstrap + job 策略都在里面），那就只覆盖那一段。

OS 窗口在镜像中的位置：

```
起始 = 1 MiB（SHNGROOT 头之后的 pad）
长度 = 6.375 GiB
```

以 4096 字节为一个扇区换算：

```
skip  = 256       扇区 = 1 MiB
count = 1671168   扇区 = 6,845,102,080 字节 = 6.375 GiB
```

拼装命令（旧镜像为底，把新 OS 窗口原地覆盖）：

```bash
dd if=pong-ipados18-userdata.img \
   of=pong-ipados18-fixed.img \
   bs=4096 skip=256 count=1671168 seek=256 conv=notrunc
```

关键参数：

| 参数 | 含义 |
| --- | --- |
| `bs=4096` | 与设备扇区一致（这块板是 4 KiB 扇区，不是 512 B） |
| `skip=256` | 从新镜像的第 1 MiB 开始读 |
| `seek=256` | 写到输出镜像的第 1 MiB |
| `conv=notrunc` | **不加这个，dd 会在写完处把文件截断** |

产出：`D:\unixnu\ud\pong-ipados18-fixed.img`，19.39 GiB。

**校验**：三组 UUID 的命中数 `6 / 3 / 10` 全部通过——SystemOS 与 Data 是旧的，OS 是新的。

---

## 6. 真正的解法：让两半对齐同一份布局

### 6.1 问题出在哪一行

```
kernel.yml:52   PONG_VOLUME_LAYOUT = configs/ci-volume-layout.placeholder.json   ← 占位 UUID
userdata.yml    prepare-pong-userland-from-ipsw.py → ci-volume-layout.json       ← 本次构建的真实 UUID
```

内核把三个 UUID **当常量编进去**，而它读的是仓库里那份**占位文件**。
占位文件里的值恰好等于原始 22H374 restore 的 UUID——所以第一次能启动；一旦 userdata 重建、窗口重造，这个"恰好"就没了。

`kernel.yml` 里那段注释其实已经写明：占位 UUID「enough to compile and link, **mounts nothing**」。

### 6.2 改成消费真实布局

userdata 构建本来就把 `ci-volume-layout.json` **作为 release 资产发布**（和分片放在一起），只是内核侧从来没去取。

现在 `kernel.yml` 增加一个输入：

```yaml
volume_layout_release:   # 默认 userdata-22H374；填 none 表示只编译不挂载
```

构建开始时会：

1. `gh release download <tag> --pattern ci-volume-layout.json`
2. 校验这份布局不是占位（`ci_placeholder` 必须为假）、三个 UUID 都齐
3. 写入 `PONG_VOLUME_LAYOUT`，覆盖仓库里的占位路径

并且新增一步**构建期断言**：把布局里的三个 UUID 和内核构建报告 `settings` 里的
`XNU_OWNER_ROOT/CACHE/DATA_VOLUME_UUID` 逐项比对，不一致就直接失败，避免"编出来了但挂不上"这种一小时后才发现的错。

### 6.3 第三方怎么复现（完整流程）

```text
① 跑 userdata.yml（workflow_dispatch，约 1 小时）
   → release `userdata-22H374`：20 个分片 + userdata-image.json + ci-volume-layout.json

② 跑 kernel.yml（workflow_dispatch）
   → volume_layout_release = userdata-22H374
   → 构建期断言通过，说明内核里的 UUID 与镜像一致

③ 本地拼镜像
   python join-userdata.py userdata-image.json --output userdata-root.img

④ 刷机
   fastboot flash userdata userdata-root.img
   fastboot boot boot.img        ← boot.img 内的 payload 来自第 ② 步
```

关键点：**②必须在①之后**，因为内核要读①产出的布局。这两步的先后关系以前没有写下来，所以任何人按"先编内核、再建镜像"的顺序做，都会得到一台起不来的机器。

### 6.4 为什么不用"固定 UUID"的方案

也评估过：在创建 SystemOS / Data 容器后，直接把 APFS 卷超级块里的 UUID 改成常量，再重算 Fletcher64 校验和，让每次构建都产出同一组 UUID。

好处是不用管构建顺序；坏处是要动 APFS 元数据（`hdiutil create` 出来的卷随机 UUID，改它属于改文件系统内部结构），一旦校验和算错，镜像会变成"看起来正常、挂载时报损坏"，比现在的 UUID 不匹配更难查。

在"布局传递"已经能干净解决问题、且只需要几行 CI 配置的前提下，**不动二进制是更好的选择**。


---

## 7. 验证：用隔离实验证明因果

为了确认「只换 OS 窗口」不会破坏挂载，做了单变量实验——**同一个内核，只换镜像**：

| 镜像 | 结果 |
| --- | --- |
| 旧 `userdata-root.img` | `Data mount PASS rw=1` ✅ |
| `fixed.img`（旧 SystemOS/Data + 新 OS 窗口） | 也能挂上，系统一路跑到 `UserEventAgent` ✅ |
| release 的原始 `pong-ipados18-userdata.img` | Data 挂不上，`init died` ❌ |

三条对照把结论钉死了：**问题在窗口 UUID，不在内核、不在策略、不在 dyld 缓存。**

---

## 8. 遗留问题

1. **窗口仍会被重造，但两半已经对齐。** CI 依旧会给 SystemOS / Data 生成新 UUID，
   区别是内核现在按 userdata 构建发布的那份布局来编，所以**新的镜像配新的内核**能对上。
   旧的「任何镜像配同一颗内核」不再成立——刷机时镜像与内核必须成对。
2. **wifi-bootstrap 仍未确认启动。** `fixed.img` 能开机，但日志里没有它的启动记录，`fbtrace` 0 次调用、`surftrace` 0 个 surface——说明那个二进制可能压根没被 launchd 加载，需要给它加一行自证日志。
3. **原镜像别删。** `userdata-root.img` 已由用户恢复，它是唯一的「旧窗口」来源。

---

## 9. 这次的纪律（下次照做）

1. **重建 userdata 之前，先把三个 UUID 记下来**：SystemOS、Data、OS。刷完立刻在日志里对。
2. **刷之前打印镜像指纹**（sha256 + 关键 UUID 命中数），别靠文件名区分镜像。
3. **dd 拼装必须带 `conv=notrunc`，扇区大小按设备来**（这块板 4 KiB）。
4. **单变量验证**：同一内核只换镜像，才能证明是镜像的问题。
5. **看到「加载 dylib 失败」先怀疑挂载**，而不是先怀疑文件缺失——这次为此烧掉两小时。
6. **镜像与内核必须成对。** 重建过 userdata，就必须用那份布局重编内核；反之亦然。
   构建期断言会在 UUID 不一致时直接把 CI 打红，不用等到刷机。

---

## 10. 附录：本次涉及的关键数值

| 项 | 值 |
| --- | --- |
| 镜像总长 | 20,821,573,632 字节（19.39 GiB） |
| SHNGROOT 头 + pad | 1 MiB |
| OS 窗口 | 6.375 GiB（1,671,168 × 4096 字节） |
| 设备扇区 | 4 KiB |
| SystemOS 期望 UUID | `B57C18AA-9E49-44A4-B94A-ED191CFB4B0F` |
| Data 期望 UUID | `47C0F5C3-B8C7-47AC-B9D9-F230BAED1576` |
| OS 期望 UUID | `B07DF049-…` |
| 可用镜像 | `D:\unixnu\ud\pong-ipados18-fixed.img` |
| 备份目录 | `D:\unixnu\backup-rmx3551\2026-11-07\` |
