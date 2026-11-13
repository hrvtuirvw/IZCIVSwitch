# 更新日志（CHANGELOG）

面向使用者的发布级更新日志。每次 **push 到 gitee 前**在此追加对应版本段（分类：新增 / 修复 / 改进 / 移除），版本号与 `VERSION` 文件、git tag 保持一致。
与 [CHANGES.md](CHANGES.md)（移植补丁技术清单）分工：本文件回答「这个版本对使用者改了什么」，CHANGES.md 回答「引擎内部打了哪些补丁、为什么」。

格式：`## [vX.Y.Z]「主题名」— YYYY-MM-DD（状态）`，条目按「新增 / 修复 / 改进 / 移除」分组，末尾括号为 git commit 简号。


---

## [v1.0.3]「妙手空空」— 2026-11-13（**预览版**；命令行已实测，GUI SD FTP 未实测）
主题：把 SD 卡上真正可写的那条路打通——经 `cmd 100 arg1`（ImageDirectoryId=SdCard）挂载的**相册 image 文件系统**，实现列目录、读文件、建目录/写文件/读回/删除的完整闭环，并附 PC 侧 FTP 桥。整卡根文件系统（cmd 18）仍是「会话已关闭」，本版不涉及。

> **测试状态（重要）**
> ✅ **命令行 / PowerShell 路径已通过真机测试**：held 模式主链（RUN 101/104/105/109）、SD 相册读（RUN 104：`/2026/11/11` 5 文件 + 4 条文件 sha256）、SD 相册写 + FTP 写测试 8/8 PASS（RUN 109：MKD→STOR 65536B→SIZE→RETR sha256→LIST→DELE→RMD）、held sentinel 释放（`cleanup.cleanedUp=true`）。
> ⚠ **图形面板的「SD 卡 FTP」流程尚未实机验证**：只做了 `py_compile` 与无头 smoke（控件/标签页/尺寸）；`resolve-sd-handle.cjs` 只验证过参数与错误路径。首次使用请先用命令行等价物（`node tools/sd-ftp/resolve-sd-handle.cjs --run <run>` → `node tools/sd-ftp/sd-ftp.cjs --socket <host:port> --handle <N>`），或把 GUI 卡片当预览功能。
> 未测试的部分不改变引擎行为：GUI 只是把 `engine/run.cjs --rpc`、`resolve-sd-handle.cjs`、`sd-ftp.cjs`、`engine/rpc.cjs stop` 串起来。

### 新增
- **SD IFileSystem 只读扩面（补丁 15）**：引擎新增 `file-sd-list`（OpenDirectory cmd 9 + IDirectory cmd 0 ReadDirectory）与 `file-sd-read`（OpenFile cmd 8 + IFile cmd 4/0），路径包经 `rawPathIpc` 直发（句柄是普通 session，不走 domain）。
- **SD 写命令七条（补丁 19）**：`sd-create`/`sd-mkdir`/`sd-delete`/`sd-delete-dir`/`sd-rename`/`sd-write`/`sd-commit`，默认关闭（`NS2_ALLOW_WRITES=1` 才生效，否则回合成 `0xE401` 并记审计）；`sd-rename` 用 `pathRequest2()` 双 X 指针。
- **FTP 桥（`tools/sd-ftp/`，随包发布；lab 开发目录 `_work/sd-ftp/`）**：纯 Node 无依赖 FTP 服务器（PASV/EPSV；LIST/NLST/RETR/STOR/DELE/MKD/RMD/RNFR+RNTO/SIZE），把 FTP 操作映射到引擎命令；默认只读，写需 `--allow-write` 与引擎 `NS2_ALLOW_WRITES=1` 双开关。实机 8/8 PASS：MKD→STOR 65536B→SIZE→RETR sha256 一致→LIST→DELE→RMD→目录消失。
- **held 模式收尾（补丁 20）**：`switch2/hold.cjs` 增加文件 sentinel（`<run>/switch2/hold-release`，500ms 轮询）+ `engine/rpc.cjs stop` 子命令，解决 runner 被强杀时 release 消息发不出、FS 资源泄漏（端点残留）。
- **图形面板 SD FTP（`kit-gui.py` + `tools/sd-ftp/`）**：面板新增「SD 卡 FTP（held 会话）」卡片——①【启动 held 会话】以 `engine/run.cjs --rpc <PC_IP>` 跑主链（自动桥接），成功后解析 `held endpoint ready`；②自动调用 `tools/sd-ftp/resolve-sd-handle.cjs` 从 run 目录解析 SD 相册句柄（promoted root clone + `cmd 100 arg1`）；③【启动 FTP】拉起 `sd-ftp.cjs`（默认只读；勾选写入需二次确认，且引擎侧同步开 `NS2_ALLOW_WRITES=1` 双闸）；④【停止 held】先 `engine/rpc.cjs <run> stop` 走 sentinel 让引擎释放 FS，25 秒未退才强杀。窗口默认按屏幕给出大尺寸（本机 1280×1040，日志区约 16 行；最大化可到 33 行），退出时记住窗口几何（`kit-gui-config.json`）。附 `resolve-sd-handle.cjs` / `mock-engine.cjs` / `selftest.cjs` / `ftp-smoke.cjs` / `ftp-write-test.cjs` 与 README（纯 Node，无依赖）。

### 修复
- **SD 写入 EOF 扩展（补丁 21/22）**：`IFile::Write` 越过 EOF 返回 `Fs/6201 ResultFileExtensionWithoutOpenModeAllowAppend`（`0x307202`）→ `sd-write` 打开 mode 改为 **7（read+write+append）**，并在写入前 `SetSize` 到写入终点、写后 `GetSize` 复核（与 save 文件系统上 donor-prepare「先给最终大小再写」顺序一致）。
- **引擎端点 busy 窗口（补丁 16）**：`tools/endpoint.cjs` 的 busy 重试 3000→120000ms，避免并发探针把主链 stage 撞死（RUN 89 教训）。
- **ps1 健壮性（补丁 17/18）**：`run-p4-once.ps1` 探针 socket 新增 `switch2/current-acquisition.json` TCP 来源；新增持久 `run-logs/`；`send bridge` 步骤用 `PYTHONIOENCODING=utf-8` + `ErrorActionPreference=Continue` 包裹，避免 `send_js.py` 打印非 ANSI 字符时把脚本杀崩（RUN 92 教训）。

### 说明
- 引擎补丁 15–22 从 lab 同步（lab 为源）：`files.cjs`（15/19/21/22）、`control.cjs`（15 路由）、`endpoint.cjs`（16）、`app/sd-probe.cjs`（16，env 开关的诊断探针）、`hold.cjs`+`rpc.cjs`（20）、`pipeline.cjs`（16 探针钩子）、`run-p4-once.ps1`（17/18）；kit 引擎树与 lab 逐文件 sha256 一致、`node --check` 全绿。
- 实机验证：RUN 104/109（held 模式）。SD 相册路径实测为 `/2026/<月>/<日>/<文件>`；整卡根（cmd 18）仍为 `0x320002`/死会话，留作后续。
- 发布包含 `tools/sd-ftp/`（PC 侧 FTP 桥）：可独立命令行使用（`node tools/sd-ftp/sd-ftp.cjs --probe <run>/switch2/.../sd-probe-*.json --mount image-dir-sd-100-1`），也可直接用图形面板的「SD 卡 FTP」卡片。
- **版本代号**：v1.0.3「妙手空空」；本版为**预览版**，GUI 的 SD FTP 卡片未实机验证（命令行路径已实测，见上方「测试状态」）。
- **实测成功率**：RUN 80–109 共 30 轮、11 次全链成功（36.7%）；对照 RUN 80–91 为 41.7%、最近 RUN 100–109 为 40.0%，差异全部来自 boot 级抽签（2/4 抽签 8 次、find-metadata 6 次），主链无回归。
---

## [v1.0.2]「眼前一亮-GUI界面」— 2026-11-13（已发布 gitee）

### 新增
- **图形控制面板**（BILIBILI@果冻扭扭扭 制作）：`kit-gui.py`（纯标准库 tkinter）+ `GUI_startup.cmd`。一键跑一轮（可先恢复触发存档、固件 dump；引擎就绪自动发桥接，30s 兜底）、单独恢复触发存档 / 全量备份 / 探测 loader、实时彩色日志、PC IP 一键写入 `civ_bridge.js`、按 result/pipeline/failureSummary 判读成败、打开 runs/dumps 目录。与 `run-p4-once.ps1` 命令逐条对应，不改引擎行为；运行记录 `kit-gui-history.json` 不入库。
- **GUI 增强**（BILIBILI@果冻扭扭扭）：「关于」标签页（原作者与上游、特别鸣谢、许可/免责声明，中英双语）；「语言/Language」下拉框（中文 / ENGLISH，即时切换并记忆）；主机 IP 输入框灰色示例占位（不再预填他人 IP）；标题显示当前 `VERSION`。

### 改进
- `run-p4-once.ps1` 输出体验：引擎运行期间每 30s 打印心跳（此前 `=== engine waiting ===` 后静默 3-10 分钟被误认为卡死）；结束打印 `logs: <路径>`，交互窗口下按回车关闭；新增 `-NoPause` 开关（后台/子代理调用用）（`88cc3e0`）。

### 修复
- **补丁 14（find-metadata 邻桶扫掠）**：pool capture 0 native links 时，在相邻 bucket 扫掠（8 环×2 向×0x40000，首桶 ≥2 links 即采用，记 `evidence.poolCaptureSweep`，上限 16 次只读）。依据 RUN 56/65：三次 5 MiB 捕获全 0 links（池漂出固定窗口）；只读、有界、可回退（`e674085`、`0b3baa6`）。

---

## [v1.0.1]「电源键拯救计划」— 2026-11-12（已发布 gitee）

主题：把流程里的一次硬重启省掉（alive-protocol），并让 SD 探针不再误伤 acquisition。

### 新增
- **alive-protocol**：console 存活轮在存活 loader 上直接重建存档 → 只硬重启一次；wedge 轮才双重启。每轮少按一次电源键，存档对照干净（`5526301`、`010f566`）。
- **补丁 13（0② find-metadata 加固）**：传输级错误一次性重放（read timeout / ECONNRESET / EPIPE 等 1s 后重试一次）；初始 pool 捕获 0 native links 时重抓最多 3 次（`4eac83f`）。

### 修复
- **-SdProbe 门控三连修**：`find-metadata complete`（`8db7065`）→ `stage status/verified`（`c668b09`）→ **只认 `ro/install-retained` complete + 2s 静默**（`5d27386`）。依据 RUN 62（root clone 句柄只在 install-retained 后存在）与 RUN 67（旧门控被 find-metadata 提前放行，探针撞上 install-retained 内存请求）。配套探针 busy 重试窗口建议 ≥120s。
- `set-pc-ip.ps1` 读取 `civ_bridge.js` 显式 UTF-8（修复中文注释乱码）（`709d5c7`）。

### 改进
- **基地址 × 命中率不耦合记录**：54 boot 统计（四等分命中率 53.8%/61.5%/61.5%/60.0%，sdk 低 20 位恒 0xa4000；游戏 ASLR 不决定 fs 几何），数据 `work/BASES-ANALYSIS.json`（`010f566`）。
- README「重要注意事项」、RUNBOOK-P4 v1.0.1 刷新（`b235084`）。

### 移除
- 开发机路径脱敏（`C:\Users\...` → 占位符）；`.gitignore` 补 `port/engine/runs/`、`sd-probe-results/`（`709d5c7`）。
- 删除过时的 `docs/PORT-HANDOFF.md`（移植完成前的交接稿，与已验证发布相矛盾）及其 README/FINDINGS 引用（`c097a82`）。

---

## [v1.0.0] — 2026-11-11（已发布 gitee）

### 新增
- **完整移植层**：slapah/CivSwitch（`7d422e52`）ns2jb-port 移植层 + 补丁 1–12（waitTimeoutResult 常量、Windows 原子保存重试、metadata 重试预算、drift 容忍、**TCP loopback 内存 socket**、cleanup-gated 重试等——详见 [CHANGES.md](CHANGES.md)）。
- **双机全链验证**：RUN 35/38/41/52 全链 verified；**双机固件 dump 90/90 逐字节一致**（sha256 0 mismatch），见 `docs/RESULTS-2026-11-11.md`（`66c51d1`、`d2a8499`）。
- README「重要注意事项」章节与版本号；`docs/` 全套（RESULTS、RUNBOOK、BRIDGE-CONTRACT、FINDINGS 等）。

---

## [开发线] v1.1.0 进行中（lab / 本地 main，未入发布分支）

引擎侧持续加固，实机验证后并入发布。关键项：

- **patch 14 邻桶扫掠**：pool 捕获 0 native links 时扫掠邻居桶（`e674085`/`0b3baa6`，kit main；实机验证中）。
- **BigInt 序列化修复**（lab `63da003`）：patch 14 首触暴露 `BigInt → JSON.stringify` 崩溃。
- **canary 判读加固**（lab `9b78b85`）：restorationFailures 只算非 aborted 行；同 boot 重试加 cleanedUp 安全门。
- **cache-alias 容差**（lab `ee2a74b`）：`allocationBytes` 与期望差 ≤ heapJitterBytes 视为正常（±192 抖动），RUN 75 实机验证。
- **进程逃逸方案 A 实验参数**（lab `41439f4`，opt-in 默认关）：`-LaunchExperiment/-LaunchTitle/-LaunchStart`（计划书 `PROCESS-ESCAPE-PLAN-2026-11-12.md`）。
- **SD 探针 v2**（`_work/sd-probe/`，未入库）：cmd18 权限墙只读侦察。
- 注：以上 lab 侧提交尚未同步入 kit；入 kit 时逐项写入本文件。
