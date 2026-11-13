# P4（slapah ns2jb-port 完整 acquisition）运行手册

> 适用：CivSwitch 已固化（触发存档 `XSTRIG.Civ7Save` 已装），PC 与 S2 同网段
> （下文以 `<PC_IP>` / `<S2_IP>` 代指两端的局域网地址）。
> 引擎目录：本包 `port\`；对引擎的改动见 `CHANGES.md`（当前 v1.0.1）。

## 1. 控制台侧（Switch 2）


1. 强制关机再开机：**长按电源 12 秒强制断电**，等 5 秒再按电源开机。
2. 正常启动《文明 7》（实体卡）。
3. 标题画面 → **Load Game** → 选 `XSTRIG.Civ7Save` → 读取。
4. 等屏幕出现 `Awaiting payload at <S2_IP>:9026`。
5. 读到 loader 后**别动主机**。P4 期间主机画面别切换；跑完看屏幕：
   - 仍停在 `Awaiting payload`（或显示 bridge 会话 `exiting after N RPC exchanges`）→ **console 存活**，走 §2 的优化循环；
   - 卡死（画面无响应）>3 分钟 → **console wedge**，走 §2 的标准循环。

## 2. 每轮之后（恢复重建存档，约 13 秒）

**标准循环（console wedge）**：硬重启 → Load Game → 恢复存档 → 再硬重启 → 跑下一轮。

**优化循环（console 存活；2026-11-11 起默认，v1.0.1「电源键拯救计划」）**：
跑完一轮后，若屏幕仍停在 `Awaiting payload`（游戏进程活着，runner 报 handles
未清只是保守推断），**不必先重启**——直接在存活 loader 上恢复存档，然后
**只硬重启一次**再跑下一轮（每轮少按一次电源键）。
2026-11-11 dump 对照验证：单重启后 trigger 与写入版逐字节一致、无 `/NS2_GAP_*`
残留、6/7 选项文件与干净基线一致（UserOptions.txt 差异为游戏自身设置变化）。

在包根目录执行（`<backup-dir>` 为 `save-tools\trigger-recreate` 或 dump 备份目录）：

```powershell
python -u .\save-tools\restore_save.py <backup-dir> <S2_IP> 9026
```

- 期望：`RESTORE DONE X written Y skipped`（trigger-recreate 时 = `1 written 0 skipped`；
  恢复全量备份时 = `6 written 1 skipped`，`HallofFame.sqlite` 报 `E: open … 0x0e02`
  是被游戏占用，属正常）。
- 残留 `/NS2_GAP_*` 不用手动清：引擎 `Remove exploit scratch from prior launches` 阶段会删。
- 存档健康度决定命中率：**每轮都要恢复重建存档**，连续重跑不重建 = 脏存档 0 胜率。

## 3. PC 侧跑 P4（一键脚本，推荐）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run-p4-once.ps1 -ConsoleIp <S2_IP> -PcIp <PC_IP> [-SkipRestore] [-FirmwareDump] [-SdProbe <sd-probe.cjs>]
```

- 脚本自动：set-pc-ip 检查 → （默认）恢复重建存档 → 起引擎 → 发 bridge → 等结束 → 打印
  verified/stages/summary。环境变量经 Start-Process 继承（`NS2_SERVE_DELAY_MS` 等可用）。
- `-SkipRestore`：已按 §2 手动恢复过存档时使用（标准用法）。
- `-FirmwareDump`：4/4 之后追加 `Enumerate and capture installed system code`，产物在
  `port\engine\dumps\`（firmware-dump.json + 每 title 的 main.npdm/main，约 222 MB / 90 titles）。
- `-SdProbe`：`ro/install-retained` complete 后（RUN 67 起只认它，root clone handle 此时才存在）对 retained
  内存 socket 发一次 SD 只读探针（OpenSdCardFileSystem 容量读取），结果落 kit 根 `sd-probe-results\`。
- 首次使用前先跑 `set-pc-ip.ps1 -PcIp <PC_IP>`（写入 `port\civ_bridge.js` 的占位符）。

## 4. PC 侧跑 P4（手动，备用）

```powershell
node .\port\engine\run.cjs <PC_IP>
```

等它打印 `Run folder: …` 后（另开一个终端）：

```powershell
python -u .\save-tools\send_js.py <S2_IP> .\port\civ_bridge.js
```

> 注意：在受限沙箱环境里引擎会因管道式 child_process 被禁而报 `spawn EPERM`——普通
> 用户机器没有此限制，直接跑即可。

## 5. 判读

- **成功**：exit 0，stdout `4/4` + `FS execution verified. Original instructions restored and
  scratch cleaned up.`；`runs\<session>\result.json` 的 `verified: true`、pipeline 26 个 stage
  全 complete。主机回到 `Awaiting payload`（可正常重启）。
- **失败**：exit 1，`The run stopped. …` → 读 `runs\<session>\switch2\acquisition.log`（或
  `acquisition-supervisor.json` 的 failureSummary）与 `switch2\memory\reserved-gap-*.json`。
- **命中率**：每合格波（margin≥300 且未 aborted）翻中 canary 约 22.6%（作者 SmileBASIC
  ~20%）；每 boot 摸到 3/4 的概率约三成，失败按 §2 恢复重建后再抽即可，不要同 boot 连抽。
- 已知失败模式速查：

  | 现象 | 含义 | 处置 |
  |---|---|---|
  | `Overwrite missed the qualified canary` / positive 0/30 | 本轮没翻中（抽签） | 恢复存档+重启重抽 |
  | `Native batch did not terminate` | 13 线程 join 超时（上游未解） | 同上 |
  | `General-heap allocation changed …`（无 retryable） | 大 drift 且非 earlyHole | 同上 |
  | `Field copy did not qualify … earlyHole N` | 洞竞态压过了拷贝窗口 | 同上 |
  | `No candidate reproduced the external allocator link` | find-metadata 候选全败（含 pool 0 links） | 同上；补丁 13 已对 transport 错重放 |
  | `cleanup is unproven or placement is uncertain` | 补丁 12 门控：脏退出禁止同 boot 重试 | 按提示重启 |
  | `Console response timed out; restart the application` | app 已死 | 硬重启 |

- 每次 run 的 run 目录都在 `port\engine\runs\switch2-XXXXXX\`（不删，留证据）。

## 6. 证据/留档

- 抓屏：`ffmpeg -f dshow -i "video=OBS Virtual Camera" -frames:v 1 <png>`（采集卡走 OBS 虚拟摄像头）。
- 每次 run 记一行到自己的 `NOTES.md`：session、时间、失败阶段、error 首行。
- 无 OBS 环境可改用 Windows OCR：抓帧后 `Windows.Media.Ocr`（WinRT）读屏幕文本核对横幅。
