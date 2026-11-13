# CivSwitch SD FTP bridge

PC 侧 FTP 服务器：把标准 FTP 协议映射到引擎（console 侧引擎）的
`root-native-sd-*` 命令，从而用 FileZilla / Windows 资源管理器 / 任何 FTP 客户端浏览和读写
主机内存卡。

```
FTP 客户端  ──(FTP, TCP)──►  sd-ftp.cjs  ──(JSON 行, TCP)──►  引擎 memoryControl
FileZilla                    PC 侧桥接                        switch2\ro\files.cjs
```

本目录四个文件（纯 Node，无第三方依赖，Node ≥ 18；本机实测 v22.14.0）：

| 文件 | 作用 |
| --- | --- |
| `sd-ftp.cjs` | FTP 服务器 + memoryControl 客户端（约 810 行） |
| `mock-engine.cjs` | 本地假引擎（内存文件树），用于**无 console 联调** |
| `selftest.cjs` | 起 mock engine + sd-ftp 的端到端自测（37 项） |
| `README.md` | 本文档 |

对应引擎补丁：CHANGES.md「补丁 19」——`files.cjs` 新增 `sd-create / sd-mkdir / sd-delete /
sd-delete-dir / sd-rename / sd-write / sd-commit`，全部受 `NS2_ALLOW_WRITES=1` 门控。

---

## 1. 快速开始（离线，不需要 console）

```powershell
cd <KIT>\tools\sd-ftp

# 终端 A：假引擎（打印实际端口）
node mock-engine.cjs
# [mock-engine] listening on 127.0.0.1:52134 handle=77398408 allowWrites=true

# 终端 B：FTP 桥接（端口用终端 A 打印的）
node sd-ftp.cjs --socket 127.0.0.1:52134 --handle 77398408 --port 2121 --allow-write
# [sd-ftp] listening on ftp://127.0.0.1:2121
# [sd-ftp] engine=127.0.0.1:52134 handle=77398408 root=/ mode=read-write
```

然后 `ftp://127.0.0.1:2121`（Windows 资源管理器）或 FileZilla（主机 `127.0.0.1`、端口
`2121`、用户 `anonymous`、密码任意）即可浏览假文件树：`/hello.txt`、`/switch/save/data.bin` 等。

一键自测：

```powershell
node selftest.cjs
# ... 37 项 PASS ...
# selftest summary: 37 passed, 0 failed   (exit code 0)
```

---

## 2. 真实环境使用

前置条件：

1. **引擎会话正在运行**（内存卡文件系统句柄在 app 句柄表里活着；换 RUN 或引擎重启后句柄会失效）。
2. 引擎进程带 `NS2_ALLOW_WRITES=1` 环境变量启动（否则写/删/建/改名/commit 全部返回
   `result: 0xE401`）。**这是服务端闸门**；`--allow-write` 只是 FTP 端的第二道闸。
3. 知道两样东西：
   - memoryControl 的 `host:port`：从当前 RUN 的
     `<RUN-DIR>\switch2\current-acquisition.json`（即 engine 的 runs\switch2-XXXXXX 目录）出发，
     读其中 `report` 指向的 JSON，取 `memoryControl.socketPath`（形如 `127.0.0.1:4062`）；
     也可用探针结果 JSON 顶层的 `socketPath`。
   - SD IFileSystem **handle**：从探针结果 JSON 取
     `sd.handle`（cmd18 直接打开的 IFileSystem，推荐）或
     `sd.openers.<key>.handle`，或 v8 探针里的 `sd.mountProbes["<opener> <path>"].handle`。

启动示例（handle 与 socket 均从探针 JSON 自动取）：

```powershell
cd <KIT>\tools\sd-ftp

node sd-ftp.cjs ^
  --acquisition "<RUN-DIR>\switch2\current-acquisition.json" ^
  --probe "<SD-PROBE-JSON>" ^
  --mount cmd18 ^
  --port 2121 --root / --allow-write
```

也可直接指定：`--socket 127.0.0.1:4062 --handle 77398408`。只读模式去掉 `--allow-write` 即可
（默认就是只读）。`--root /switch` 可把 FTP 根映射到 SD 的 `/switch`。

> 安全提示：默认监听 `127.0.0.1`、默认只读、默认匿名登录。不要 `--host 0.0.0.0` 裸奔到公网；
> 需要时用 `--user/--pass`。

### 参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--socket host:port` | 无（除非 `--probe` 带 `socketPath` / `--acquisition`） | 引擎 memoryControl 端点 |
| `--acquisition <json>` | 无 | 读 `current-acquisition.json`，从 `report` JSON 自动取 socket |
| `--handle N` | 无 | SD IFileSystem 句柄（与 `--probe` 二选一，`--handle` 优先） |
| `--probe <json>` | 无 | 探针结果 JSON，自动解析 handle（及 `socketPath` 兜底） |
| `--mount <key>` | `cmd18` | `openers` / `mountProbes` 里的 key；`cmd18`/`sd` 表示 `sd.handle` |
| `--port N` | `2121` | FTP 控制端口 |
| `--host` | `127.0.0.1` | FTP 控制监听地址 |
| `--root /` | `/` | FTP 虚拟根对应的 SD 路径 |
| `--user/--pass` | 匿名（任意密码） | 指定后必须匹配 |
| `--allow-write` | 关 | 转发 STOR/DELE/MKD/RMD/RNFR/RNTO（引擎仍需 `NS2_ALLOW_WRITES=1`） |

---

## 3. FTP ↔ 引擎映射表

| FTP 命令 | 引擎命令 | 说明 |
| --- | --- | --- |
| `USER` / `PASS` | — | 本地认证；默认 anonymous 任意密码；`--user/--pass` 指定后校验 |
| `PWD` / `CWD` / `CDUP` | `root-native-sd-list` | 纯虚拟路径；CWD 用 sd-list 验证目标存在且是目录 |
| `LIST` / `NLST` | `root-native-sd-list` | Unix 风格 `ls -l` 行；支持 `LIST -la` |
| `SIZE` | `root-native-sd-list` | 列父目录按文件名匹配（引擎没有 fstat 命令） |
| `RETR` | `root-native-sd-read` | 按 0x4000 字节分块循环读，hex→bytes |
| `STOR` | `root-native-sd-write` + `sd-commit` | 每 0x4000 一块；**首块 `truncate:true`**；结束 commit；空文件走 delete+create |
| `DELE` | `root-native-sd-delete` | 仅文件 |
| `MKD` | `root-native-sd-mkdir` | |
| `RMD` | `root-native-sd-delete-dir` | `recursive:false`，只删空目录；拒绝删虚拟根 |
| `RNFR` | `root-native-sd-list` | 记录源路径与类型 |
| `RNTO` | `root-native-sd-rename` | best-effort；失败时**文件**走 read→write→delete 兜底，目录直接 550 |
| `PASV` / `EPSV` | — | 被动模式；数据连接独立 TCP socket，每个传输一个监听 | 
| `PORT` | — | 不支持，返回 502（请用 PASV/EPSV） |
| `SYST` / `FEAT` / `OPTS` / `TYPE` / `NOOP` / `QUIT` | — | 基础命令；FEAT 声明 SIZE/UTF8/EPSV/PASV/TVFS |

路径校验：所有路径 UTF-8，必须 `/` 开头，禁止 `..` 逃出虚拟根，长度 < 0x301（引擎侧同样的
校验在 `files.cjs` 里再做一遍）。

---

## 4. 已知限制

1. **rename 是 best-effort**：两个路径需要两个 HIPC X 描述符，`files.cjs` 用新的
   `pathRequest2()` 组包（cmd 5/6）；如果引擎端返回失败，FTP 层对**文件**退化为
   「读→建→写→删」，对**目录**直接 550。`sd-rename` 的失败结果带 `result: 0xE402`。
2. **没有 mtime**：引擎命令不带时间戳，LIST 的时间是 PC 当前时间；不支持 `MLSD` / `MDTM`。
3. **不能断点续传**：没有 `REST` / `APPE`；每次 STOR 从 offset 0 覆盖写。
4. **不能递归删目录**：`RMD` 只删空目录（引擎同一个命令支持 `recursive:true`，如需可扩展）。
5. **大文件慢**：每 16 KiB 一次 memoryControl 请求（一次 TCP 连接）；引擎忙时桥接会以 50 ms
   退避重试，单请求 120 s deadline。没有批量/流式管道。
6. 不支持 `PORT`/`EPRT`、不支持 `AUTH TLS`；只适合本机/受信局域网。
7. 句柄时效：`--handle` 来自探针时的 app 句柄表；引擎重启/换 RUN 后旧 handle 无效，需要重跑
   探针（`_work\sd-probe\sd-probe-sd.cjs`）并重新启动本服务器。
8. 写操作需要**两道闸都开**：FTP 端 `--allow-write` **且** 引擎进程 `NS2_ALLOW_WRITES=1`。

---

## 5. 退出码 / 错误对照

| 现象 | 原因 / 处理 |
| --- | --- |
| FTP `550 read-only bridge: ...` | 启动时没加 `--allow-write` |
| FTP `451 ... engine writes disabled (set NS2_ALLOW_WRITES=1 ...)` | 引擎进程没开 `NS2_ALLOW_WRITES=1` |
| 引擎回 `Another memory request is active` | 同一时刻只有一条 memory 请求；桥接自动 50 ms 退避重试（≤120 s） |
| `engine error 0x2xx` | FsResult 错误（路径不存在等），见引擎 `sd-*` 返回的 `canonicalResult` |
| `--handle must be a positive integer` / `invalid SD handle` | handle 取错或过期 |
| `memory socket stayed busy for 120 s` | 引擎端长时间被占用（另一个 RUN 请求没结束） |

自测（`node selftest.cjs`）覆盖：登录、SYST/TYPE/FEAT、PWD、LIST（含 `-la`）、NLST、SIZE、
RETR（文本与 256 字节二进制）、CWD/CDUP、MKD/CWD/RMD、40000 字节分块 STOR、RNFR/RNTO、
DELE、空文件 STOR、非空目录 RMD 拒绝、EPSV、只读桥拒绝、引擎写门控 451、busy 重试、
rename copy-fallback、`--root` 映射、`--user/--pass` 校验。全部离线，退出码 0 表示全过。

---

## 6. 开发接口

`sd-ftp.cjs` 导出：

```js
const {EngineClient, SdPaths, resolveVirtual, normalizeVirtual, listEntry,
       createFtpServer, resolveProbeHandle, readAcquisitionSocket, parseArgs} = require('./sd-ftp.cjs');
```

- `new EngineClient('127.0.0.1:4062', handle)`：`list/read/write/create/mkdir/delete/
  deleteDir/rename/commit`，内部处理 busy 重试与单请求连接。
- `createFtpServer({socket, handle, root, user, pass, allowWrite, log})` →
  `{server, engine, paths, context, listen(port=0, host='127.0.0.1'), close()}`。
- `resolveProbeHandle(probeJsonPath, mountKey)` / `readAcquisitionSocket(acquisitionPath)`
  供其它脚本复用。

`mock-engine.cjs` 导出 `{MockFs, seedFs, createEngine, createMockEngine, ...}`，
`createMockEngine({allowWrites, busyReplies, failRename, handle})` 返回
`{server, fs, state, dispatch, listen, close}`；也可直接 `node mock-engine.cjs` 充当假引擎。
