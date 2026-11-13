## v1.0.2「眼前一亮-GUI界面」— 2026-11-13

- **`run-p4-once.ps1` 输出体验修复**：引擎运行期间每 30s 打印 `[engine running Ns] <最新日志行>`（此前窗口在 `=== engine waiting ===` 后静默 3-10 分钟，被误认为卡死）；结束打印 `logs: <临时日志路径>` 并在交互窗口下 `按回车关闭窗口`（避免打完 summary 窗口秒关被误认为闪退）；新增 `-NoPause` 开关（子代理/后台调用用）。依据：朋友反馈「=== engine waiting === 停很久，然后闪退」——实为静默等待 + 窗口自动关闭的观感问题，run 目录内结果完整。

- **图形控制面板并入（BILIBILI@果冻扭扭扭 制作，2026-11-12）**：新增 `kit-gui.py`（纯标准库 tkinter）+ `GUI_startup.cmd`。功能：一键跑一轮（可选先恢复触发存档、固件 dump；引擎就绪自动发桥接，30s 兜底）、单独恢复触发存档/全量备份/探测 loader、实时彩色日志、PC IP 一键写入 `civ_bridge.js`、运行记录 `kit-gui-history.json`（不入库）、打开 runs/dumps 目录、按 `result.json`/`pipeline.json`/`failureSummary` 判读成败。与 `run-p4-once.ps1` 命令逐条对应（`node engine/run.cjs <PcIp>`、`save-tools/send_js.py`、`restore_save.py` 等），不改引擎/命令行行为。README §3/§7.1 已同步；`.gitignore` 加 `kit-gui-config.json`/`kit-gui-history.json`。

- **GUI 增强（BILIBILI@果冻扭扭扭，2026-11-12）**：新增第 5 个「关于」标签页（原作者与上游、特别鸣谢、许可/免责声明，中英双语）；顶部新增「语言/Language」下拉框（中文 / ENGLISH），切换即时生效并记忆到 `kit-gui-config.json`（不入库）。所有界面文案、运行记录列、失败诊断名均随语言切换；主机 IP 输入框默认显示灰色示例占位（不再预填他人机器 IP），左上角标题显示当前版本号（读 `VERSION`）。

## v1.0.1「电源键拯救计划」— 2026-11-11 深夜

**主题**：把流程里的一次硬重启省掉（alive-protocol），并让 SD 探针不再误伤 acquisition。

- **alive-protocol（流程优化）**：console 存活轮（Awaiting payload）→ 在存活 loader 上直接恢复重建存档 → 只硬重启一次 → 下一轮；console wedge 轮仍双重启。实测存档对照干净（trigger 逐字节一致、无 NS2_GAP_* 残留、UserOptions 差异为游戏自身重写）。**每次存活轮少按一次电源键**。
- **-SdProbe 门控修复**（`run-p4-once.ps1`）：探针只在 `ro/install-retained` 在 pipeline.json 里 `complete` 后才触发（+2s 静默）。依据 RUN 62：root clone handle 在 install-retained 后才存在（此前探针必得 no-handle）；RUN 67：旧「find-metadata 或 install-retained」门控在 find-metadata 先完成时提前放行，探针撞上 install-retained 的内存请求（busy 3s 用尽、比 install-retained 结束早 0.126s）。配套探针脚本（`-SdProbe` 参数指定，不在本包内）建议 busy 重试窗口 ≥120s，以骑过 4/4 FS demo 的残余争用。
- **数据记录**：基地址×命中率不耦合（54 boot 统计：四等分命中率 53.8%/61.5%/61.5%/60.0%，sdk 低 20 位恒 0xa4000；竞态在 fs 进程 save 服务堆内，游戏 ASLR 不决定 fs 几何；数据 `work/BASES-ANALYSIS.json`）。
# CHANGES —— 我们对 slapah 移植层的补丁清单

> **v1.0.3「妙手空空」= 预览版**：命令行/PowerShell 路径已真机实测（RUN 104 读、RUN 109 写+FTP）；GUI 的 SD 卡 FTP 卡片未实机验证。

基线：slapah/CivSwitch @ `7d422e52`（2026-11-04），`ns2jb-port/` 移植层。
以下补丁全部为**修 bug / 适配 Civ7 / 适配 Windows 沙箱**，不改变攻击语义。

| # | 文件 | 补丁 | 原因 |
|---|---|---|---|
| 1 | `port/civ7-app/thread-code.json` | `waitTimeoutResult: 59649 → 59905`（0xE901→0xEA01） | 硬件实测 svcWaitSynchronization 超时返回 0xEA01；作者常量写错导致 join 轮询永远把超时当异常（RUN 1-7 卡死根因） |
| 2 | `port/engine/switch2/memory/run-control.cjs`、`ro/runtime.cjs`、`firmware-dump.cjs` | 原子保存 `fs.rename` 加 EPERM/EBUSY/EACCES 重试（12 次，50+25n ms 退避） | Windows 上瞬时文件锁（Defender/索引）导致 `EPERM rename *.tmp -> .json`，运行中随机报废 |
| 3 | `port/engine/switch2/memory/probe-reserved-gap.cjs` | `metadataAttempts: 4 → 12` | alias 重试预算按 SmileBASIC 调校；Civ7 上 alias 频繁被打回（RUN 9/11/23/24） |
| 4 | 同上 | 新增 `retireParkedWorkers()`，serve 入口前主动回收 parked worker 线程，置 `report.servePrepared` | serve 入口 app 自崩排查（背景线程持有腐蚀状态嫌疑）；对成功率无害 |
| 5 | 同上 | drift 容忍：`retryable = earlyHole \|\| |diff| ≤ 0x800`；记 `retryableReason`；不满足才按作者原逻辑 fatal | Civ7 fs 后台活动猛，小 drift（-704/-28336）频繁；纯按 SB 的 ±192 容差会误杀深跑（RUN 15/30/29） |
| 6 | 同上 | bucket period 资格改重试循环（上限 metadataAttempts，记 `periodAttempts`） | 单发 period 资格在 Civ7 上极难（RUN 24 卡死点）；RUN 28 重试后首次通过 |
| 7 | 同上 | `NS2_SERVE_DELAY_MS` 环境变量（serve 前 PC 侧空等，默认 10000ms）与 `NS2_SKIP_SERVE` 旁路 | 诊断 serve 死点用；证明 app 死于 serve 调用窗口 |
| 8 | `port/engine/switch2/memory/fs-memory-control.cjs` + `port/engine/switch2/tools/endpoint.cjs` | memory socket 从 named pipe 路径改为 **TCP loopback**（`127.0.0.1:<随机端口>`，state.socketPath='host:port'，listening='tcp-loopback'）；endpoint.cjs 新增 `connectTarget()`：`/^([^:]+):(\d+)$/` 走 `{host,port}`，否则原路径 | 本机 Windows 沙箱（job object）禁 named pipe → `listen()` 抛 EACCES → serve 死点（RUN 14-34 全部 serve 入口死亡的真正原因）。RUN 34 起 2/4 首次 complete |

另有两处吸收自 x43x61x69/ns2jb（2026-11-10 上游提交）的改进，已并入本包：

| 来源提交 | 内容 |
|---|---|
| `e3309c35` "Track acquisition batch outcomes..." | `wave-history.cjs` 模块化：`hasWindow/markerHit/failureSummary/retryBatches` 批次账本；positive 校验失败立即抛（修掉全 aborted 静默完成的引擎结构 bug）；`workerCaptureSkipped`（native batch 不终止时不读被 IPC 保留的 buffer） |

未包含（备胎/实验）：x43x61x69 `f47ddb6f` 实验性 SD acquisition profile
（`--experimental-sd`，无硬件验证）；x43 的 cleanup-gated 同 session 重试只回植了一半。

补丁前的原文件备份：`port-patches/`（未包含在本包内；需要时向打包者索取）。

验证记录：补丁后 **RUN 34 = 2/4 首通、RUN 35 = 全链 verified 首通、
RUN 38 = 固件 dump 90/90（222 MB）**，均为本包内这份代码。

| 9 | `port/engine/switch2/memory/probe-reserved-gap.cjs` | drift 容忍放宽：`retryable = earlyHole \|\| |Δ| ≤ 0x8000`，reason=early-hole/small-drift(≤0x800)/known-magnitude(≤0x8000)；>0x8000 仍 fatal | -28336=7×4048、-32736=8×4092 是 wave 自身 gap 簿记量，跨机跨阶段反复出现；≤0x800 太紧（RUN 48 误杀深轮） |
| 10 | `port/engine/switch2/acquire.cjs` | 替换为 x43x61x69/ns2jb `e3309c35` 全量版（cleanup-gated 重试：hasProvenCleanup/canRetry、每 attempt 独立 log、acquisition-supervisor.json 记 retryAllowed/failureSummary） | 脏 attempt 不再同 boot 连败 3 次（省约 8 分钟/轮、少 wedge）；RUN 53 实测按预期 1 次即退 |
| 12 | `port/engine/switch2/retained/find-metadata.cjs` | pool 捕获 0 links 时的邻桶扫掠（8 环×2 向×0x40000，首桶 ≥2 links 即采用，记 `evidence.poolCaptureSweep`，上限 16 次只读） | RUN 56/65：三次 5MiB 捕获全 0 links（池漂出固定窗口）；只读、有界、可回退 |
| 11 | port/engine/switch2/retained/find-metadata.cjs | 传输级错误一次性重放（
eplay()：read timeout / was not replayed / ECONNRESET / ECONNREFUSED / EPIPE → 1s 后重试一次，记 evidence.replays）；初始 pool 捕获 0 native links 时重抓最多 3 次（1s 间隔） | RUN 44：bootstrap-move 超时拖死唯一候选 → No candidate reproduced...；RUN 50：第 4 次 bucket 读 60s 超时 abort；RUN 49：首次 5MB 捕获 0 links。全部只读/幂等，happy path 行为不变 |

验证记录：补丁后 **RUN 34 = 2/4 首通、RUN 35 = 全链 verified 首通、
RUN 38 = 固件 dump 90/90（222 MB）**，均为本包内这份代码。
2026-11-11 双机验证与 dump 交叉验证见 [`docs/RESULTS-2026-11-11.md`](docs/RESULTS-2026-11-11.md)。


## v1.0.0（2026-11-11）
- 双机全链验证（RUN 35/38/41/52）+ 双机固件 dump 90/90 逐字节一致（sha256 0 mismatch）。
- 补丁 1–12 全部入库；README 增加「重要注意事项」章节与版本号；新增 docs/RESULTS-2026-11-11.md。

## v1.1.0 进行中（2026-11-11 晚起）
- 0② find-metadata 加固：补丁 11 表内第 11 行（传输重放 + 池捕获重试），待下一轮主机实跑验证。

## v1.1.0 同步段（2026-11-13，SD 相册读写 + FTP；补丁 15–22，lab 为源）

- **补丁 15**：`switch2/ro/files.cjs` + `switch2/ro/control.cjs` — `file-sd-list` / `file-sd-read`（pathRequest 9/8 + IDirectory/IFile 读），`sd-` 路由进 files.cjs。
- **补丁 16**：`switch2/tools/endpoint.cjs`（busy 3000→120000ms）+ `switch2/ro/control.cjs`（`root-native-ipc` 支持 `any:true`）+ `switch2/app/sd-probe.cjs`（env `NS2_APP_SD_PROBE=1` 的诊断探针，1/4 与 4/4 各跑一次）+ `switch2/pipeline.cjs`（两处钩子，try/catch 不 abort 主链）。
- **补丁 17/18**：`run-p4-once.ps1`（探针 socket 第三来源 `current-acquisition.json`；持久 `run-logs/`；send bridge 崩溃防护 + `PYTHONIOENCODING`）。
- **补丁 19**：`switch2/ro/files.cjs` — `sd-create` / `sd-mkdir` / `sd-delete` / `sd-delete-dir` / `sd-rename` / `sd-write` / `sd-commit`（`NS2_ALLOW_WRITES=1` 门控）；`pathRequest2()` 双 X 指针。
- **补丁 20**：`switch2/hold.cjs`（sentinel 文件 `hold-release`）+ `engine/rpc.cjs`（`stop` 子命令）。
- **补丁 21/22**：`switch2/ro/files.cjs` — `sd-write` 先 `SetSize` 到写入终点再写；打开 mode 3→7（appendable）；SetSize 后复读大小；写失败也记录 entry。

- **发布工具（随 v1.0.3 入包）**：`kit-gui.py` 新增「SD 卡 FTP（held 会话）」卡片与 SD FTP 日志页（held 引擎启动/句柄解析/FTP 起停/sentinel 释放）；`tools/sd-ftp/` 收录 `sd-ftp.cjs`、`resolve-sd-handle.cjs`（从 run 目录 socket 解析 promoted root clone + `cmd 100 arg1` 句柄）、`mock-engine.cjs`、`selftest.cjs`、`ftp-smoke.cjs`、`ftp-write-test.cjs`、README。纯 Node 无依赖；GUI 与命令行共用同一批脚本。
