> 此项目通过Deepseek-V4-Pro协助完成

# CivSwitch × ns2jb 移植 —— 体验包

> 版本：**v1.0.3「妙手空空」**（2026-11-13，**预览版**）

> ⚠ **预览版说明**：命令行 / PowerShell 路径**已通过真机测试**（SD 相册读 = RUN 104；SD 相册写 + FTP 写测试 8/8 PASS = RUN 109；
> held sentinel 释放 verified）。**图形面板的「SD 卡 FTP」流程尚未实机验证**——首次使用请先走命令行等价物，见 §7.2 与 CHANGELOG 的「测试状态」。

> 打包日期：2026-11-13（结果文档更新至 2026-11-12）。用途：在**自己的** Switch 2 上，从《文明 7》实体卡带入口走通
> ns2jb Stage 2 移植（slapah/CivSwitch fork，经我方补丁，见 [CHANGES.md](CHANGES.md)），获取 FS 任意读写，
> 并导出 90 个系统程序的固件 CodeFS（main.npdm + main）。
>
> 本包已经在**两台独立主机**上全链验证（RUN 35/38/41/52），两台主机的固件 dump 90/90 逐字节一致
> （sha256 全同，222 MB）。详见 [`docs/RESULTS-2026-11-11.md`](docs/RESULTS-2026-11-11.md)。
> 你只需要一台满足前提的机器 + 照着下面的循环做。

## English Summary

**What this is** — a hands-on kit for a known Nintendo Switch 2 research chain. A
JavaScript-XSS in the *Civilization VII* (Switch 1 physical cart, v1.0.0) in-game
browser starts a Remote JS Loader on TCP `:9026`. The ns2jb Stage 2 engine then runs
inside the Civ7 process, races the `fs` sysmodule with 13 native threads and forges
cache entries to obtain arbitrary filesystem read/write; from there a retained payload
and an RO payload are installed and 90 system programs (222 MB of CodeFS) can be
dumped.

**Status** — fully validated on two independent consoles (both firmware 23.0.1): RUN
35/38/41/52 end-to-end, firmware dump 90/90 on each, byte-identical across the two
consoles. See [`docs/RESULTS-2026-11-11.md`](docs/RESULTS-2026-11-11.md).

**Requirements** — Switch 2 firmware 23.0.1; Civ7 Switch 1 physical cart v1.0.0; a
Switch 1 able to run homebrew (one-time install only); a Windows PC with Node.js ≥ 20
and Python 3.10+; both consoles wired to the same LAN.

**Per-boot success rate** — the runtime canary hits roughly 30% of boots; just reload
and retry (3–4 attempts typically enough).

**License** — GPL-2.0 for the package as a whole; upstream components, the bundled
`.nro` and the Gezine MIT portions are documented in [`NOTICE.md`](NOTICE.md) and
[`LICENSE-MIT-Gezine.txt`](LICENSE-MIT-Gezine.txt).

**Note** — research only, on hardware you own. Step-by-step instructions below are in
Chinese; the flowchart in §0 shows the chain at a glance.

> This project was built with assistance from **Deepseek-V4-Pro**.

---

## 0. 一句话原理

Civ7（Switch 1 版实体卡 1.0.0）聊天框存在 XSS：把一段 JS 打进游戏内嵌浏览器执行，
起一个 TCP `:9026` 的 Remote JS Loader。Loader 之上跑 ns2jb 的 Stage 2 引擎：
在 Civ7 进程里造 13 条原生线程对 `fs` sysmodule 打 reserved-gap 竞态，
伪造缓存条目拿到 FS 任意读写，再一路走到 retained 常驻端点 → RO payload →
固件 dump。**固化方式**：把触发代码写进 `XSTRIG.Civ7Save` 存档，每次开机 Load Game 即重新武装。

### 0.1 链路流程图

![链路流程图：XSTRIG.Civ7Save 固化触发存档 → Civ7 聊天框 XSS → Remote JS Loader :9026 → ns2jb Stage 2 → fs 竞态 → FS 任意读写 → retained → RO payload → 固件 dump 90/90（222 MB）](docs/flowchart.png)

> 上图的可编辑源文件是 [`docs/flowchart.mmd`](docs/flowchart.mmd)（Mermaid 源码）。
> 该源码在其它 Mermaid 渲染器下正常，但 GitHub 页面实测报 `Unable to render rich display`，
> 因此 README 改用预渲染 PNG，保证在 GitHub 网页、手机端和任何 Markdown 查看器里都能显示。

## 1. 硬件 / 软件前提（缺一不可）

| 项 | 要求 |
|---|---|
| Switch 2 | 系统固件 **23.0.1**，⚠️ **不要再升级** |
| Civ7 卡带 | **Switch 1 实体版《文明 7》1.0.0**（带盒版初版，无更新） |
| Switch 1 | 可跑 homebrew `.nro`（用于**一次性**固化安装；装完可不用） |
| PC | Windows，**有线网线**直连 Switch 2 同一局域网（两端有线） |
| Node.js | ≥ 20（建议 22+） |
| Python | 3.10+（仅 save-tools 用，标准库即可） |
| 存档 | Civ7 的**单机存档可牺牲**（固化时会被清空；见 §5 警告） |

## 2. ⚠️ 重要注意事项（每轮操作前必读）

1. **Civ7 游戏内设置**：自动存档调到 **数量=1、回合间隔=25**。游戏无法完全关闭自动存档，
   只能拉大间隔、减少后台对竞态窗口的干扰。
2. **必须双端有线**：PC 与 Switch 2 都要用**网线**接同一局域网。ns2jb 链对时序敏感，
   无线会显著降低命中率甚至无法跑通。
3. **P3 跑通后立刻备份健康存档**：第一轮 P4 之前，用 `dump_save_tree.py` 做一次全量只读备份
   （干净基线，之后出事可整体恢复）。
4. **每一轮 P4 前：恢复健康存档 + 重启主机**（顺序见 §7 标准循环）：
   恢复触发存档 → 长按电源 12 秒硬关机 → 开机 Load Game → 再开跑。
   不要在同一 boot 里连续重跑——脏存档的命中率会归零。
5. **每轮跑完看 acquisition.log 的错误报告**，按类型处理：

| 错误报告关键字 | 含义 | 处理 |
|---|---|---|
| `canary 0/30`（或 `Positive canary verification failed`） | 纯抽签没中 | 重建存档 + 重启 + 重抽 |
| `Native batch did not terminate` | 竞态时序没卡好 | 同上，重抽 |
| `General-heap allocation changed`（drift） | 后台干扰，少见 | 同上，重抽（补丁 11 已自动容忍已知量级） |

6. **不要往屏幕上加进度打印**：实测判断——2/4 采集竞态期间，控制台侧每一条 `log()`
   都是 DOM 级开销，会落在 µs 级竞态余量窗口里，增加抖动、压低命中率、放大 drift；
   引擎在竞态期刻意保持控制台零输出。要看进度只看 PC 端（引擎 stdout / run 目录报告）。

> 成功与否只看 PC 端（§8）；屏幕上的 `Executed successfully` 不代表成功。

## 3. 目录结构

```
civswitch-kit/
├── README.md            本文件
├── CHANGELOG.md         发布级更新日志（每次 push 前更新）
├── CHANGES.md           我们对引擎的补丁清单（12 项）
├── LICENSE              GPL-2.0 全文
├── LICENSE-MIT-Gezine.txt  原 MIT 文本（来自 Gezine 的部分）
├── NOTICE.md            来源、第三方二进制与再分发说明
├── run-p4-once.ps1      一键跑一轮 P4（恢复存档→起引擎→发 bridge→汇总）
├── set-pc-ip.ps1        一键把 PC 的 IP 写进 civ_bridge.js（首次必做）
├── kit-gui.py           图形控制面板（§7.1，GUI_startup.cmd 启动）
├── GUI_startup.cmd       启动图形面板
├── port/                slapah 移植层（引擎 + 探针 + civ_bridge.js，已打补丁）
├── save-tools/
│   ├── restore_save.py      重写触发存档（每轮前用）
│   ├── dump_save_tree.py    全量备份 save:/saves（防身用）
│   ├── probe_9026.py        探测 loader 是否在线（慎用，见 §8）
│   ├── send_js.py           发任意 JS payload
│   ├── payloads/            示例 payload（helloworld.js 等）
│   └── trigger-recreate/    重建好的触发存档（XSTRIG.Civ7Save + manifest）
├── switch1/
│   └── civswitch-ldn-nx.nro  Switch 1 固化安装器（v0.9，我们实测验证版）
└── docs/
    ├── RUNBOOK-P4.md        标准循环 + 失败判读速查
    ├── SAVE-BACKUP.md       存档备份/恢复说明
    ├── FINDINGS.md          上游实测记录（SmileBASIC）
    ├── UPSTREAM-SYNC-2026-11-10.md  我们吸收的上游提交消化
    ├── flowchart.png        链路流程图（§0.1 引用的图片）
    └── flowchart.mmd        同一张图的 Mermaid 源码（可重新渲染）
```

## 4. Switch 1 侧安装（只做一次）

1. 把 `switch1/civswitch-ldn-nx.nro` 放到 Switch 1 的 SD 卡 `switch/` 目录，
   用任意 nro loader（hbmenu 等）启动。
2. Switch 1 与 Switch 2 **连同一 Wi-Fi**（此时 S1 用无线，后续 S2 用有线也行——
   LDN 阶段只发生在这一步）。

## 5. 固化安装（只做一次，⚠️ 会删存档）

1. S2：Civ7 → `MULTIPLAYER > WIRELESS > CREATE GAME > HOST LOBBY`（大厅保持开着）。
2. S1：运行 NRO → 按 **X** 扫描 → 方向键选到 S2 → 按 **A** 加入 →
   等屏幕出现 `Game lobby: JOINED`（S2 大厅里出现玩家 `CivSwitch-LDN-NX`）。
3. S1：按 **ZR**（一键固化）。S1 会自动：发 loader → 恢复 Wi-Fi → 扫局域网 →
   写触发存档 `XSTRIG.Civ7Save`。
4. 等 S1 显示 `Persistent trigger save installed` + `DONE`（以 **S2 屏幕打出
   `INSTALL DONE`** 为最终成功）。
5. ⚠️ **ZR 会删除 Civ7 全部单机存档**。成功后在 S2 重启游戏 → `Load Game` →
   触发存档 → 屏幕出现 `Awaiting payload at <IP>:9026` 即固化成功。
   之后每次开机 Load Game 都能重新武装，无需 Switch 1。

> 也可以不用 S1：用上游 Gezine 的 PicoSwitch 键盘宏方案（见上游仓库 README），
> 同样能达到固化效果。本包不含 Pico 固件。

## 6. PC 侧首次配置

```powershell
cd civswitch-kit
powershell -NoProfile -ExecutionPolicy Bypass -File .\set-pc-ip.ps1 -PcIp 你的PC局域网IP
```

（IP 查看：`ipconfig`，找以太网适配器 IPv4。此步把 IP 写进 `port\civ_bridge.js`，
是 console 端 bridge 出站连接的目标。）

## 7. 标准运行循环（每轮）

```
① S2 开机 → Civ7 → Load Game → XSTRIG.Civ7Save → 屏幕出现
   Awaiting payload at <S2-IP>:9026
② PC 执行（首次不跳过恢复，之后每轮都建议先恢复一次）：
   powershell -NoProfile -ExecutionPolicy Bypass -File .\run-p4-once.ps1 `
       -ConsoleIp <S2-IP> -PcIp <PC-IP>
③ 脚本顺序：重写触发存档（恢复原始字节）→ 起引擎 → 发 bridge → 等结束 → 打印汇总。
```

**重要（实测协议）**：存档恢复后要**再硬重启一次**才开跑——按这个顺序：

1. loader 在线时先跑一次 `restore_save.py`（run-p4-once 里第 1 步会自动做，
   或手动：`python save-tools\restore_save.py save-tools\trigger-recreate <S2-IP>`）；
2. **长按电源 12 秒硬关机 → 开机 → Load Game → Awaiting payload**；
3. 再跑 `run-p4-once.ps1 -ConsoleIp <S2-IP> -PcIp <PC-IP> -SkipRestore`。
4. 跑完一轮后 console 大概率卡死 → 回到第 2 步硬重启，循环。

**固件 dump**：加 `-FirmwareDump` 参数。dump 落盘 `port\engine\dumps\`
（`firmware-dump.json` 日志 + `ncm-system-programs.bin` + 每个 title 一个目录）。
注意：引擎每次启动会**清掉上一次的 dump 目录**，跑通后先拷贝走再跑下一轮。

### 7.1 图形面板（免 PowerShell，推荐）

双击 **`GUI_startup.cmd`** 打开 `kit-gui.py` 控制面板（纯标准库 tkinter，无需装包；图形界面由 **BILIBILI@果冻扭扭扭** 制作）：

- **一键跑一轮** = `run-p4-once.ps1` 的图形版：可选「先恢复触发存档」（默认勾 = 不带
  `-SkipRestore`）和「固件 dump」（= `-FirmwareDump`）；引擎打印 Waiting/Run folder 后
  **自动发送桥接**（30 秒兜底），结束后自动按 `result.json` / `pipeline.json` /
  `failureSummary` 判读成败、给出下一轮循环提示。
- **PC IP** 填一次点【写入桥接】= `set-pc-ip.ps1`（写入 `port\civ_bridge.js`，之后自动记住）。
- 恢复触发存档、全量备份存档（`dump_save_tree.py`）、探测 loader（带空连接警告）可单独点。
- 顶部可打开 `runs` 记录与 `dumps` 目录；运行记录存 `kit-gui-history.json`（不入库）。
- **「关于」标签页**：原作者/上游、特别鸣谢、许可与免责声明都在这里（中英双语）。
- **语言切换**：右上角「语言 / Language」下拉框可切 **中文 / ENGLISH**，即时生效并记住（`kit-gui-config.json`，不入库）。
- **主机 IP**：未填写时输入框显示灰色示例（`192.168.1.100`），点进去即清空等输入，不会被当成真实地址；左上角标题显示当前 `VERSION` 版本号。

> `-SdProbe` 高级探针未纳入面板，仍走命令行。

### 7.2 SD 卡 FTP（held 模式，可选）

> ⚠ **本节（GUI 的 SD 卡 FTP）尚未在真机验证**：只做了 `py_compile` 与无头窗口 smoke；
> `resolve-sd-handle.cjs` 仅验证过参数/错误路径。它的命令行等价物已在 RUN 104/109 实测通过，
> 所以优先用「命令行等价物」小节里的命令；GUI 卡片当作预览功能。
>
> 前提：这一轮主链能成功跑到 4/4（held 模式会保留 FS 端点）。FTP 只映射 **SD 相册 image 文件系统**（根 `/`，实测 `/2026/<月>/<日>/<文件>`）；**整卡根仍不可用**。

1. 面板底部「SD 卡 FTP（held 会话）」卡片 → 点**【① 启动 held 会话】**。它等价于 `engine/run.cjs --rpc <PC_IP>`：Load Game 后等 `Awaiting payload`，引擎自动桥接；主链成功后打印 `held endpoint ready: 127.0.0.1:<port>`。
2. 面板随后自动调用 `tools/sd-ftp/resolve-sd-handle.cjs`，从 run 目录里解析 SD 相册句柄（promoted root clone + `cmd 100 arg1`）；状态栏显示「held 就绪，句柄 <N>」即可进行下一步。
3. 点**【② 启动 FTP】**：默认**只读**；勾选「允许写入 SD」会弹确认，并同时在引擎侧打开 `NS2_ALLOW_WRITES=1`（双闸）。
4. 用任意 FTP 客户端连 `ftp://127.0.0.1:2121`（地址栏在卡片右侧）：`/` 下就是相册树；只读模式可浏览/下载，写入模式可上传/新建文件夹/重命名/删除（写入 65536B 以上文件时先 SetSize 再写，属已知正确路径）。
5. **用完必须点【停止 held】**：它先发 `engine/rpc.cjs <run> stop`（文件 sentinel）让引擎自己释放 FS，25 秒未退才强杀。不点会一直占着主机侧 FS 会话，下一轮可能不正常。

> 命令行等价物：`node tools/sd-ftp/resolve-sd-handle.cjs --run <run 目录>`、`node tools/sd-ftp/sd-ftp.cjs --socket <v4 的 127.0.0.1:port> --handle <N>`。自测：`node tools/sd-ftp/selftest.cjs`（不需要主机）。

## 8. 成功判据（只看 PC 端）

- `run-p4-once.ps1` 汇总：`verified=True`、`error=`（空）、engine exit=0；
- 引擎 stdout 出现：
  `FS execution verified. Original instructions restored and scratch cleaned up.`
  `Restart the console when finished.`
- 带 `-FirmwareDump` 时出现 `Firmware: dump complete: {"listed":90,...}`。

⚠️ **屏幕上的 `Executed successfully` / `Awaiting payload` 不代表成功**——
那是 bridge 会话正常收尾，成功失败都会显示。也**不要给屏幕加进度打印**：
竞态期控制台输出会直接压低命中率、放大 drift（见 §2 第 6 条），进度一律看 PC 端。

## 9. 概率预期（重要）

- 每 boot 的 canary 命中约 **30%**；没命中就按 §7 循环再来（3-4 次必中一次）。
- 已知失败都在重试清单内（alias requalify / period copyField / 0-30 canary /
  native batch 不终止），都不是死结。
- `probe_9026.py` **少用**：空连接会被 loader 记 bad connection，3 次触发
  listener rebuild。
- 全程别动 S2 画面；卡死 >3 分钟视为 wedge → 长按电源 12 秒硬重启。
- Civ7 游戏内设置：自动存档**数量=1、回合间隔=25**（无法完全关闭，只能拉大）。

## 10. 安全与合规

- 仅供研究本人持有的设备；写入发生在 `save:/` 分区（触发存档、scratch 目录）。
- 跑之前用 `dump_save_tree.py` 备份一次存档（见 docs/SAVE-BACKUP.md）。
- 不要把本包用于他人设备或线上对战。

## 11. 来源与版本

- 上游：kurumuz/ns2jb（GitLab，GPL-2.0）→ slapah/CivSwitch（GitHub fork，
  `7d422e52`，ns2jb-port 移植层）→ 我们的 **22 项补丁**（补丁 1–14 见历史，补丁 15–22 为 v1.0.3 同步段，见 CHANGES.md）。
- Switch 1 安装器：xiaolizi23/civswitch-ldn-nx **v0.9**（我们全程实测版本；
  上游已出新版 v1.x，本包未包含）。SHA-256（同 `switch1/SHA256.txt`）：
  `4E8DDFA4982A8130470D0FCBD236F2954C5EE911F79FF581F4F1ECC01690A2D9`；
  该二进制按原样附带，上游未明确再分发许可，详见 `NOTICE.md`。
- 许可：本包整体 GPL-2.0；Gezine 的 MIT 片段原文本保留在 `LICENSE-MIT-Gezine.txt`。
- 我们的验证环境：S2 fw 23.0.1、Civ7 1.0.0 实体卡、PC Windows + Node 24、
  双端有线以太网。RUN 1→38 全过程见 NOTES（未包含在包内）。

- **版本历史**：v1.0.0（首版移植）→ v1.0.1「电源键拯救计划」→ v1.0.2「眼前一亮-GUI界面」→
  **v1.0.3「妙手空空」（预览版：SD 相册读写 + FTP；GUI 的 SD FTP 卡片未实测，命令行路径已实测）**。
