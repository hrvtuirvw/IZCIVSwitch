# -*- coding: utf-8 -*-
"""
civswitch-kit 控制面板（run-p4-once.ps1 的图形版）
- 一键跑一轮 P4：可选先恢复触发存档 / 固件 dump；引擎就绪后自动发送桥接，
  结束后按 result.json / pipeline.json / failureSummary 判读并提示下一步
- 恢复存档 / 全量备份存档 / 探测 loader 可单独启动、单独停止
- 实时彩色日志、运行记录存档（kit-gui-history.json）、PC IP 一键写入桥接
- 中英文界面切换（语言下拉框，即时切换）、"关于"页（原作者 / 特别鸣谢 / 许可）
"""

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

BASE = os.path.dirname(os.path.abspath(__file__))
PORT_DIR = os.path.join(BASE, "port")
RUNS_DIR = os.path.join(PORT_DIR, "engine", "runs")
DUMPS_DIR = os.path.join(PORT_DIR, "engine", "dumps")
BRIDGE_JS = os.path.join(PORT_DIR, "civ_bridge.js")
CONFIG_PATH = os.path.join(BASE, "kit-gui-config.json")
HISTORY_PATH = os.path.join(BASE, "kit-gui-history.json")

CONSOLE_IP_EXAMPLE = "192.168.1.100"   # 主机 IP 输入框的灰色示例占位（不是默认值）

# 与 run-p4-once.ps1 逐条对应的命令（cwd 见各常量）
ENGINE_CMD = lambda pcip, dump: (["node", "engine/run.cjs", "--dump-firmware", pcip]
                                 if dump else ["node", "engine/run.cjs", pcip])
ENGINE_CWD = PORT_DIR
BRIDGE_CMD = lambda cip: [sys.executable, "-u", "save-tools/send_js.py", cip, "port/civ_bridge.js"]
RESTORE_CMD = lambda cip: [sys.executable, "-u", "save-tools/restore_save.py",
                           "save-tools/trigger-recreate", cip, "9026"]
BACKUP_CMD = lambda cip: [sys.executable, "-u", "save-tools/dump_save_tree.py", cip]
PROBE_CMD = lambda cip: [sys.executable, "-u", "save-tools/probe_9026.py", cip]
COMMON_CWD = BASE

# SD 卡 FTP（held 模式）：引擎加 --rpc 常驻保留端点 → resolver 取 SD 相册句柄 →
# sd-ftp 把该句柄暴露成 FTP。只读默认；写入要勾选开关（引擎侧还需 NS2_ALLOW_WRITES=1）。
SD_FTP_DIR = os.path.join(BASE, "tools", "sd-ftp")
ENGINE_HELD_CMD = lambda pcip: ["node", "engine/run.cjs", "--rpc", pcip]
RESOLVE_SD_CMD = lambda run_dir: ["node", os.path.join(SD_FTP_DIR, "resolve-sd-handle.cjs"),
                                  "--run", run_dir]
SD_FTP_CMD = lambda sock, handle, port, root, allow_write, host: (
    ["node", os.path.join(SD_FTP_DIR, "sd-ftp.cjs"), "--socket", sock, "--handle", str(handle),
     "--port", str(port), "--root", root, "--host", host]
    + (["--allow-write"] if allow_write else []))

BRIDGE_SEND_DELAY = 30      # 引擎启动后仍未打印就绪标记时的兜底发桥接时限（同 ps1）

NO_WINDOW = 0x08000000      # CREATE_NO_WINDOW

ERR_WORDS = ("timed out", "not ready", "fatal", "traceback", "refused",
             "the run stopped", "error", "failed")
OK_WORDS = ("fs execution verified", "restore done", "firmware: dump complete")

# ---------- 界面语言 ----------
_LANG = "zh"                            # zh / en（全局，切换时重建界面）
LANG_DISPLAY = {"zh": "中文", "en": "ENGLISH"}
LANG_INTERNAL = {"中文": "zh", "ENGLISH": "en"}


def L(zh, en, *args):
    """按当前语言取文案；给了 args 时做 % 格式化"""
    s = zh if _LANG == "zh" else en
    return s % args if args else s


def read_version():
    """读 kit 根目录 VERSION 文件（拿不到时返回 ?）"""
    try:
        with open(os.path.join(BASE, "VERSION"), encoding="utf-8") as f:
            return f.read().strip() or "?"
    except OSError:
        return "?"


def read_version_name():
    """读可选的 VERSION-NAME.txt（版本代号，如「眼前一亮」；没有则返回空串）"""
    try:
        with open(os.path.join(BASE, "VERSION-NAME.txt"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def version_display():
    """版本号 + 可选代号，例如 1.0.2「眼前一亮」"""
    ver = read_version()
    name = read_version_name()
    return "%s「%s」" % (ver, name) if name else ver


def about_text():
    """'关于'页正文（按语言生成，版本号读 VERSION 文件）"""
    ver = version_display()
    if _LANG == "zh":
        return """civswitch-kit 控制面板

版本：v%s
本面板是 civswitch-kit 命令行流程 run-p4-once.ps1 的图形化版本，
不修改引擎行为，命令与参数逐条对应。

【原作者与上游】
· Gezine —— CivSwitch 原始漏洞利用链与代码执行框架（MIT）
· pepsipu —— ns2jb 越狱思路（SmileBASIC 4 → FS 系统模块）
· kurumuz —— ns2jb 引擎实现（GPL-2.0）
· slapah —— CivSwitch 的 ns2jb 移植层（port/，GPL-2.0）
· mza1010 —— civswitch-kit 项目：引擎补丁、上游同步、alive-protocol、
  SD 探针门控、文档与发布（Gitee @mza1010/civswitch-kit）

【图形界面】
· 作者：BILIBILI@果冻扭扭扭
· 实现：Python 标准库 tkinter，无需额外依赖（Python 3.10+ / Node 20+）

【特别鸣谢】
· x43x61x69（ns2jb 维护者；acquire.cjs 全量版与清理门控）
· ItsNerisma（CivSwitchLDN 与 LDN 适配参考）
· ravensclawx（HBLauncher 思路与桥接约束参考）
· byizmysh（IZ2S 生态；Super File Bros 的 SD 写协议参考）
· dougchansan（ns2-savekit 的存档工具设计参考）
· xiaolizi23（switch1/civswitch-ldn-nx.nro，v0.9）
· 以及所有在 GBAtemp / Reddit / Discord 上公开踩坑记录的玩家

【许可与免责】
· 本 kit 整体 GPL-2.0；port/ 继承 slapah 的 GPL-2.0；Gezine 原文件为 MIT
  （见 LICENSE-MIT-Gezine.txt）；switch1 的 NRO 来自 xiaolizi23 的 v0.9。
· 仅供研究与学习。使用前请自行备份存档；修改固件/存档有损坏风险，后果自负。
· 本项目与任天堂、2K/Firaxis、Gezine 等均无隶属关系。
""" % ver
    return """civswitch-kit Control Panel

Version: v%s
A graphical front-end for the civswitch-kit CLI flow run-p4-once.ps1.
It does not change engine behavior; every command and argument maps 1:1.

[Original authors & upstream]
· Gezine - original CivSwitch exploit chain and code-execution framework (MIT)
· pepsipu - ns2jb jailbreak approach (SmileBASIC 4 -> FS system module)
· kurumuz - ns2jb engine implementation (GPL-2.0)
· slapah - CivSwitch's ns2jb port layer (port/, GPL-2.0)
· mza1010 - civswitch-kit project: engine patches, upstream sync, alive-protocol,
  SD-probe gating, docs and releases (Gitee @mza1010/civswitch-kit)

[Graphical interface]
· Author: BILIBILI@果冻扭扭扭
· Built with the Python standard library tkinter, no extra dependencies
  (Python 3.10+ / Node 20+)

[Special thanks]
· x43x61x69 (ns2jb maintainer; acquire.cjs wave and cleanup gating)
· ItsNerisma (CivSwitchLDN and LDN adaptation reference)
· ravensclawx (HBLauncher ideas and bridge constraints)
· byizmysh (IZ2S ecosystem; Super File Bros SD write protocol)
· dougchansan (ns2-savekit save-tool design)
· xiaolizi23 (switch1/civswitch-ldn-nx.nro, v0.9)
· and every player who shared hard-won findings on GBAtemp / Reddit / Discord

[License & disclaimer]
· The kit is GPL-2.0 overall; port/ inherits slapah's GPL-2.0; Gezine's original
  files are MIT (see LICENSE-MIT-Gezine.txt); the switch1 NRO comes from
  xiaolizi23's v0.9.
· For research and learning only. Back up your saves first; modifying firmware
  or saves carries a risk of damage - use at your own risk.
· No affiliation with Nintendo, 2K/Firaxis, Gezine, or any other party.
""" % ver


def default_hint():
    return L(
        "流程提示：主机 Load Game 出现 Awaiting payload 后点【一键跑一轮】。\n"
        "勾选「先恢复存档」= run-p4-once.ps1 默认模式；已手动恢复过就取消勾选（= -SkipRestore）。",
        "Flow tip: when the console shows Awaiting payload in Load Game, click [Run a round].\n"
        "With 'Restore trigger save first' checked = run-p4-once.ps1 default; uncheck if you already "
        "restored manually (= -SkipRestore).")


# 引擎失败类型判读表：failureSummary.kind -> (中文名, 英文名, 判定)
# 判定: True=已知可循环的正常竞争失败 / None=可先继续循环但留意 / False=建议发日志分析
FAIL_KINDS = {
    "canary-placement-miss":     ("金丝雀未翻中（竞争没赌中，非崩溃）",
                                  "Canary placement miss (race not won, not a crash)", True),
    "positive-window-exhausted": ("positive 窗口耗尽（未翻中）",
                                  "Positive window exhausted (not hit)", True),
    "console-or-native-timeout": ("主机中途挂死或 13 线程 join 超时",
                                  "Console wedged / 13-thread join timeout", True),
    "native-worker-timeout":     ("工作线程超时", "Worker thread timeout", True),
    "allocation-profile-mismatch": ("内存布局漂移超限", "Memory layout drift over limit", None),
    "acquisition-error":         ("获取阶段通用错误", "Generic acquisition error", None),
}

# 运行记录里的动作/结果（数据里存中文，显示时翻译）
HIST_ACT = {"恢复存档": "Restore save", "备份存档": "Backup saves", "一轮P4": "P4 round"}
HIST_RES = {"成功": "Success", "失败": "Failed", "被终止": "Stopped", "完成": "Done"}


def hist_text(s, table):
    return s if _LANG == "zh" else table.get(s, s)


def read_bridge_pc_ip():
    """读 civ_bridge.js 里当前 PC_IP；未设置返回 None"""
    try:
        with open(BRIDGE_JS, encoding="utf-8") as f:
            m = re.search(r"PC_IP:\s*'([^']*)'", f.read())
        if m and m.group(1) and "<" not in m.group(1):
            return m.group(1)
    except OSError:
        pass
    return None


def write_bridge_pc_ip(pc_ip):
    """set-pc-ip.ps1 的等价实现：替换占位符或旧值，UTF-8 无 BOM 写回"""
    with open(BRIDGE_JS, encoding="utf-8") as f:
        text = f.read()
    if "'<PC_IP>'" in text:
        text = text.replace("'<PC_IP>'", "'%s'" % pc_ip)
    else:
        text = re.sub(r"PC_IP:\s*'[^']*'", "PC_IP: '%s'" % pc_ip, text)
    with open(BRIDGE_JS, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def latest_engine_run_dir():
    """返回 runs 下最新一次引擎运行的目录（switch2-*），无则 None"""
    try:
        dirs = [os.path.join(RUNS_DIR, d) for d in os.listdir(RUNS_DIR)
                if d.startswith("switch2-") and os.path.isdir(os.path.join(RUNS_DIR, d))]
        return max(dirs, key=os.path.getmtime) if dirs else None
    except OSError:
        return None


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def analyze_engine_failure(run_dir):
    """从运行目录提取 failureSummary，返回 (kind, message, 统计) 或 None"""
    if not run_dir:
        return None
    best = None
    mem = os.path.join(run_dir, "switch2", "memory")
    try:
        for name in os.listdir(mem):
            if not (name.startswith("reserved-gap-") and name.endswith(".json")):
                continue
            path = os.path.join(mem, name)
            fs = (load_json(path) or {}).get("failureSummary")
            if not fs:
                continue
            # 优先取带 positive 波统计的；同级取最新修改的
            score = (1 if fs.get("positive") else 0, os.path.getmtime(path))
            if best is None or score > best[0]:
                best = (score, fs)
    except OSError:
        pass
    if not best:
        supervisor = load_json(os.path.join(run_dir, "switch2", "acquisition-supervisor.json"))
        fs = (supervisor or {}).get("failureSummary")
        if fs:
            best = ((0, 0), fs)
    if not best:
        return None
    fs = best[1]
    pos = fs.get("positive") or {}
    stats = ""
    if pos:
        stats = L("（positive 波 %s/%s，合格窗口 %s，marker 命中 %s）",
                  " (positive waves %s/%s, qualified windows %s, marker hits %s)") % (
            pos.get("measuredWaves", "?"), pos.get("limit", "?"),
            pos.get("qualifiedWindows", "?"), pos.get("markerHits", "?"))
    return fs.get("kind", "?"), fs.get("message", ""), stats

# 与 CivSwitchFS 面板同一套视觉（Refactoring UI §1.5/§2.1/§2.8/§3.6）
UI = {
    "bg": "#f6fbfd", "surface": "#ffffff", "border": "#d3dee4",
    "text": "#222435", "muted": "#5c6479", "disabled": "#707a8f",
    "primary": "#2563c9", "primary_hover": "#1a4cb3",
    "tint": "#ebf9ff", "tint_text": "#0f369d",
    "danger": "#c62828", "success": "#0a7d32",
}
FONT = {
    "small": ("Microsoft YaHei UI", 9),
    "body": ("Microsoft YaHei UI", 11),
    "strong": ("Microsoft YaHei UI", 11, "bold"),
    "section": ("Microsoft YaHei UI", 14, "bold"),
    "title": ("Microsoft YaHei UI", 20, "bold"),
    "tab_sel": ("Microsoft YaHei UI", 12, "bold"),
    "mono": ("Consolas", 11),
    "mono_bold": ("Consolas", 11, "bold"),
}


def fmt_dur(sec):
    m, s = divmod(int(sec), 60)
    return "%d:%02d" % (m, s)


def fmt_ip_ok(ip):
    return bool(ip) and ip.count(".") == 3 and all(
        p.isdigit() and 0 <= int(p) <= 255 for p in ip.split("."))


class Job:
    def __init__(self, key, title, title_en):
        self.key = key
        self.title = title          # 中文标题（数据/内部用）
        self.title_en = title_en
        self.proc = None            # 当前主进程（round=引擎；restore 阶段=恢复脚本）
        self.engine_proc = None     # round 专用：引擎进程
        self.bridge_proc = None     # round 专用：桥接进程
        self.bridge_sent = False
        self.phase = None           # round: None -> "restore" -> "engine"
        self.t0 = None
        self.engine_t0 = None
        self.killed = False
        self.saw_2_4 = False
        self.saw_ok = False
        self.saw_dump = False
        self.restore_ok = False
        self.run_dir = None
        self.dump_mode = False
        self.notes = []
        self.last_code = None

    def title_text(self):
        return L(self.title, self.title_en)


class App:
    def __init__(self, root):
        global _LANG
        self.root = root
        self.cfg = self.load_config()
        if self.cfg.get("lang") in ("zh", "en"):
            _LANG = self.cfg["lang"]
        self.version = read_version()
        self.lang_var = tk.StringVar(value=LANG_DISPLAY[_LANG])
        self.q = queue.Queue()
        self.jobs = {k: Job(k, zh, en) for k, zh, en in
                     [("round", "一键跑一轮 P4", "Run a P4 round"),
                      ("restore", "恢复触发存档", "Restore trigger save"),
                      ("backup", "全量备份存档", "Full save backup"),
                      ("sdftp", "SD 卡 FTP", "SD card FTP")]}
        # SD FTP（held 模式）状态
        self.ftp_socket = None
        self.ftp_handle = None
        self.ftp_url = None
        self.ftp_proc = None
        self.ftp_run_dir = None
        self.ftp_bridge_sent = False
        self.ftp_port_var = tk.StringVar(value=str(self.cfg.get("ftp_port", 2121)))
        self.ftp_write_var = tk.BooleanVar(value=bool(self.cfg.get("ftp_write", False)))
        self.ftp_status_lbl = None
        self.ftp_url_lbl = None
        self.history = self.load_history()

        root.title(L("civswitch-kit 控制面板 · v%s", "civswitch-kit Control Panel · v%s",
                     self.version))
        root.geometry(self._initial_geometry())
        root.minsize(980, 800)

        self.build_ui()
        self.refresh_history()
        self.refresh_bridge_ip()
        self.set_hint(default_hint())
        root.after(100, self.poll)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _initial_geometry(self):
        """窗口尺寸：优先用上次记住的几何（保证日志区可被用户拉大且下次保留），
        否则按屏幕大小给一个大窗口——日志区在纵向有 weight，窗口越高日志越大。"""
        saved = str(self.cfg.get("geometry", "") or "").strip()
        if re.match(r"^\d+x\d+([+-]-?\d+[+-]-?\d+)?$", saved):
            return saved
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        width = min(1280, max(1000, sw - 80))
        height = min(1040, max(820, sh - 100))
        return "%dx%d" % (width, height)

    # ---------- UI ----------
    def configure_styles(self):
        self.root.configure(bg=UI["bg"])
        self.root.option_add("*Font", FONT["body"])
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Panel.TButton", font=FONT["body"], padding=(16, 8),
                        background=UI["surface"], foreground=UI["text"],
                        bordercolor=UI["border"], lightcolor=UI["surface"],
                        darkcolor=UI["surface"], relief="flat", borderwidth=1)
        style.map("Panel.TButton",
                  background=[("disabled", UI["bg"]), ("active", UI["bg"])],
                  foreground=[("disabled", UI["disabled"])],
                  bordercolor=[("focus", UI["primary"])])
        style.configure("Primary.Panel.TButton", font=FONT["strong"],
                        background=UI["primary"], foreground=UI["surface"],
                        bordercolor=UI["primary"], lightcolor=UI["primary"],
                        darkcolor=UI["primary"])
        style.map("Primary.Panel.TButton",
                  background=[("disabled", UI["border"]),
                              ("pressed", UI["primary_hover"]),
                              ("active", UI["primary_hover"])],
                  foreground=[("disabled", UI["muted"]), ("!disabled", UI["surface"])])
        style.configure("Danger.Panel.TButton", foreground=UI["danger"])
        style.map("Danger.Panel.TButton", foreground=[("disabled", UI["disabled"]),
                                                      ("!disabled", UI["danger"])])
        style.configure("Quiet.Panel.TButton", borderwidth=0, foreground=UI["muted"])
        style.configure("Start.Panel.TButton", font=FONT["strong"],
                        background=UI["tint"], foreground=UI["tint_text"],
                        bordercolor=UI["primary"], lightcolor=UI["tint"],
                        darkcolor=UI["tint"])
        style.map("Start.Panel.TButton",
                  background=[("disabled", UI["bg"]), ("active", UI["tint"])],
                  foreground=[("disabled", UI["disabled"]), ("!disabled", UI["tint_text"])],
                  bordercolor=[("disabled", UI["border"]), ("!disabled", UI["primary"])])
        style.configure("Panel.TEntry", padding=8, fieldbackground=UI["surface"],
                        foreground=UI["text"], bordercolor=UI["border"],
                        lightcolor=UI["surface"], darkcolor=UI["surface"])
        style.map("Panel.TEntry", bordercolor=[("focus", UI["primary"])])
        # 灰色示例占位样式（主机 IP 输入框未填写时使用）
        style.configure("Placeholder.Panel.TEntry", padding=8, fieldbackground=UI["surface"],
                        foreground=UI["muted"], bordercolor=UI["border"],
                        lightcolor=UI["surface"], darkcolor=UI["surface"])
        style.map("Placeholder.Panel.TEntry", bordercolor=[("focus", UI["primary"])])
        style.configure("Panel.TCheckbutton", background=UI["surface"],
                        foreground=UI["text"], focuscolor=UI["surface"])
        style.map("Panel.TCheckbutton", background=[("active", UI["surface"])])
        style.configure("Panel.TNotebook", background=UI["surface"], borderwidth=0,
                        tabmargins=(0, 0, 0, 0))
        style.configure("Panel.TNotebook.Tab", padding=(24, 12),
                        font=FONT["body"], background=UI["bg"],
                        foreground=UI["muted"], borderwidth=0)
        # 选中的标签页放大（更大内边距 + 加粗大一号字体），未选中保持原样
        style.map("Panel.TNotebook.Tab",
                  background=[("selected", UI["surface"])],
                  foreground=[("selected", UI["primary"]), ("active", UI["text"])],
                  lightcolor=[("selected", UI["surface"])],
                  padding=[("selected", (32, 16)), ("active", (27, 13))],
                  font=[("selected", FONT["tab_sel"])])
        row_height = int(self.root.winfo_fpixels("30p"))
        style.configure("Panel.Treeview", background=UI["surface"],
                        fieldbackground=UI["surface"], foreground=UI["text"],
                        font=FONT["small"], rowheight=row_height, borderwidth=0)
        style.configure("Panel.Treeview.Heading", background=UI["bg"],
                        foreground=UI["muted"], font=FONT["strong"],
                        padding=(12, 8), relief="flat")
        style.map("Panel.Treeview", background=[("selected", UI["primary"])],
                  foreground=[("selected", UI["surface"])])
        for orient in ("Vertical", "Horizontal"):
            style.configure("Panel.%s.TScrollbar" % orient,
                            background=UI["border"], troughcolor=UI["surface"],
                            bordercolor=UI["surface"], arrowcolor=UI["muted"],
                            lightcolor=UI["border"], darkcolor=UI["border"],
                            relief="flat", borderwidth=0, arrowsize=12)

    def ui_label(self, parent, text, font="body", color="text", **kwargs):
        return tk.Label(parent, text=text, font=FONT[font], fg=UI[color],
                        bg=parent.cget("bg"), anchor="w", **kwargs)

    def build_ui(self):
        self.configure_styles()
        header = tk.Frame(self.root, bg=UI["surface"], padx=24, pady=12)
        header.pack(fill="x")
        brand = tk.Frame(header, bg=UI["surface"])
        brand.pack(side="left")
        self.ui_label(brand, "civswitch-kit  v%s" % self.version, font="title").pack(anchor="w")
        self.ui_label(brand, L("控制面板  /  任务与运行记录", "Control panel  /  Tasks & run history"),
                      font="small", color="muted").pack(anchor="w", pady=(4, 0))
        actions = tk.Frame(header, bg=UI["surface"])
        actions.pack(side="right")
        self.ui_label(actions, L("语言", "Language"), font="small", color="muted").pack(side="left", padx=(0, 6))
        self.lang_box = ttk.Combobox(actions, textvariable=self.lang_var,
                                     values=("中文", "ENGLISH"), state="readonly", width=9)
        self.lang_box.pack(side="left", padx=(0, 16))
        self.lang_box.bind("<<ComboboxSelected>>", self.on_lang_change)
        self.btn_auto = ttk.Button(actions, text=L("一键跑一轮", "Run a round"), style="Primary.Panel.TButton",
                                   command=self.run_round_click)
        self.btn_auto.pack(side="left", padx=(0, 8))
        ttk.Button(actions, text=L("全部停止", "Stop all"), style="Danger.Panel.TButton",
                   command=self.stop_all).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text=L("打开 runs 记录", "Open runs"), style="Quiet.Panel.TButton",
                   command=self.open_runs).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text=L("打开 dumps", "Open dumps"), style="Quiet.Panel.TButton",
                   command=self.open_dumps).pack(side="left")

        body = tk.Frame(self.root, bg=UI["bg"], padx=24, pady=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(4, weight=1)

        connection = tk.Frame(body, bg=UI["surface"], padx=16, pady=10)
        connection.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.ui_label(connection, L("连接设置", "Connection"), font="strong").pack(side="left", padx=(0, 24))
        self.ui_label(connection, L("主机 IP", "Console IP"), font="small", color="muted").pack(side="left", padx=(0, 8))
        saved_ip = str(self.cfg.get("console_ip", "") or "").strip()
        self.ip_var = tk.StringVar(value=saved_ip or CONSOLE_IP_EXAMPLE)
        self.ip_entry = ttk.Entry(connection, textvariable=self.ip_var, width=15,
                                  font=FONT["mono"], style="Panel.TEntry")
        self.ip_entry.pack(side="left")
        self.ip_placeholder_on = not saved_ip
        if self.ip_placeholder_on:
            self.ip_entry.configure(style="Placeholder.Panel.TEntry")
        self.ip_entry.bind("<FocusIn>", self.on_ip_focus_in)
        self.ip_entry.bind("<FocusOut>", self.on_ip_focus_out)
        self.ui_label(connection, L("PC  IP", "PC  IP"), font="small", color="muted").pack(side="left", padx=(20, 8))
        self.pc_var = tk.StringVar(value=self.cfg.get("pc_ip", read_bridge_pc_ip() or ""))
        ttk.Entry(connection, textvariable=self.pc_var, width=15,
                  font=FONT["mono"], style="Panel.TEntry").pack(side="left")
        ttk.Button(connection, text=L("写入桥接", "Write bridge"), style="Panel.TButton",
                   command=self.apply_pc_ip).pack(side="left", padx=(8, 0))
        self.bridge_ip_lbl = self.ui_label(connection, "", font="small")
        self.bridge_ip_lbl.pack(side="left", padx=(16, 0))
        ttk.Button(connection, text=L("探测 loader", "Probe loader"), style="Quiet.Panel.TButton",
                   command=self.probe_loader).pack(side="right")

        rows = tk.Frame(body, bg=UI["bg"])
        rows.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self.job_btns = {}
        self.job_status = {}
        for i, key in enumerate(("round", "restore", "backup")):
            rows.columnconfigure(i, weight=1, uniform="jobs")
            card = tk.Frame(rows, bg=UI["surface"], padx=16, pady=10)
            card.grid(row=0, column=i, sticky="nsew", padx=(0, 16 if i < 2 else 0))
            self.ui_label(card, self.jobs[key].title_text(), font="strong").pack(anchor="w")
            st = self.ui_label(card, L("空闲", "Idle"), font="small", color="muted")
            st.pack(anchor="w", pady=(2, 8))
            if key == "round":
                self.restore_var = tk.BooleanVar(value=self.cfg.get("restore_first", True))
                self.dump_var = tk.BooleanVar(value=False)
                opts = tk.Frame(card, bg=UI["surface"])
                opts.pack(fill="x", pady=(0, 8))
                ttk.Checkbutton(opts, text=L("先恢复触发存档", "Restore trigger save first"),
                                variable=self.restore_var,
                                style="Panel.TCheckbutton").pack(side="left")
                ttk.Checkbutton(opts, text=L("固件 dump", "Firmware dump"), variable=self.dump_var,
                                style="Panel.TCheckbutton").pack(side="left", padx=(12, 0))
            controls = tk.Frame(card, bg=UI["surface"])
            controls.pack(fill="x")
            controls.columnconfigure((0, 1), weight=1, uniform="actions")
            b_start = ttk.Button(controls, text=L("开始", "Start"), width=6, style="Start.Panel.TButton",
                                 command=lambda k=key: self.start_job(k))
            b_stop = ttk.Button(controls, text=L("停止", "Stop"), width=6, state="disabled",
                                style="Panel.TButton", command=lambda k=key: self.stop_job(k))
            b_start.grid(row=0, column=0, sticky="ew", padx=(0, 4))
            b_stop.grid(row=0, column=1, sticky="ew", padx=(4, 0))
            self.job_btns[key] = (b_start, b_stop)
            self.job_status[key] = st

        # ---- SD 卡 FTP 卡片（held 模式：主链跑完后 FS 端点常驻，FTP 直连 SD 相册） ----
        ftp_card = tk.Frame(body, bg=UI["surface"], padx=16, pady=10)
        ftp_card.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        ftp_head = tk.Frame(ftp_card, bg=UI["surface"])
        ftp_head.pack(fill="x")
        self.ui_label(ftp_head, L("SD 卡 FTP（held 会话）", "SD card FTP (held session)"),
                      font="strong").pack(side="left")
        self.ftp_status_lbl = self.ui_label(ftp_head, L("未启动", "Not started"),
                                            font="small", color="muted")
        self.ftp_status_lbl.pack(side="left", padx=(16, 0))
        self.ftp_url_lbl = self.ui_label(ftp_head, L("FTP 地址：-", "FTP URL: -"),
                                         font="small", color="muted")
        self.ftp_url_lbl.pack(side="right")

        ftp_row1 = tk.Frame(ftp_card, bg=UI["surface"])
        ftp_row1.pack(fill="x", pady=(8, 0))
        self.btn_ftp_held = ttk.Button(ftp_row1, text=L("① 启动 held 会话", "1) Start held session"),
                                       style="Start.Panel.TButton", command=self.ftp_start_held)
        self.btn_ftp_held.pack(side="left", padx=(0, 8))
        self.btn_ftp_held_stop = ttk.Button(ftp_row1, text=L("停止 held", "Stop held"),
                                            style="Panel.TButton", state="disabled",
                                            command=self.ftp_stop_held)
        self.btn_ftp_held_stop.pack(side="left", padx=(0, 16))
        self.ui_label(ftp_row1, L("FTP 端口", "FTP port"), font="small",
                      color="muted").pack(side="left", padx=(0, 6))
        ttk.Entry(ftp_row1, textvariable=self.ftp_port_var, width=7,
                  font=FONT["mono"], style="Panel.TEntry").pack(side="left", padx=(0, 12))
        ttk.Checkbutton(ftp_row1, text=L("允许写入 SD（默认只读）", "Allow SD writes (read-only by default)"),
                        variable=self.ftp_write_var,
                        style="Panel.TCheckbutton").pack(side="left", padx=(0, 16))
        self.btn_ftp_start = ttk.Button(ftp_row1, text=L("② 启动 FTP", "2) Start FTP"),
                                        style="Start.Panel.TButton", state="disabled",
                                        command=self.ftp_start_server)
        self.btn_ftp_start.pack(side="left", padx=(0, 8))
        self.btn_ftp_stop = ttk.Button(ftp_row1, text=L("停止 FTP", "Stop FTP"),
                                       style="Panel.TButton", state="disabled",
                                       command=self.ftp_stop_server)
        self.btn_ftp_stop.pack(side="left")
        self.ui_label(ftp_card, L(
            "FTP 只映射 SD 相册（image 文件系统，根路径 /），整卡根仍不可用；"
            "会话随 held 引擎存活，用完点「停止 held」释放。",
            "FTP maps only the SD album (image filesystem, root /); the card root is still "
            "unavailable. The session lives with the held engine - use [Stop held] when done."),
            font="small", color="muted").pack(anchor="w", pady=(8, 0))

        log_heading = tk.Frame(body, bg=UI["bg"])
        log_heading.grid(row=3, column=0, sticky="ew", pady=(0, 6))
        self.ui_label(log_heading, L("运行日志", "Run log"), font="strong").pack(side="left")
        self.ui_label(log_heading, L("按任务查看输出与历史记录", "Output & history per task"),
                      font="small", color="muted").pack(side="right")
        nb = ttk.Notebook(body, style="Panel.TNotebook")
        nb.grid(row=4, column=0, sticky="nsew")
        self.tabs = {}
        self.log_empty = {}
        tab_titles = {
            "round": L("P4 输出", "P4 output"),
            "restore": L("恢复存档输出", "Restore output"),
            "backup": L("备份/探测输出", "Backup / probe output"),
            "sdftp": L("SD FTP 输出", "SD FTP output"),
        }
        for key in ("round", "restore", "backup", "sdftp"):
            frame = tk.Frame(nb, bg=UI["surface"], padx=8, pady=8)
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(0, weight=1)
            txt = tk.Text(frame, wrap="none", height=10, width=1, font=FONT["mono"],
                          bg=UI["surface"], fg=UI["text"], relief="flat", borderwidth=0,
                          padx=12, pady=12, spacing1=2, spacing3=2,
                          insertbackground=UI["text"], selectbackground=UI["primary"],
                          selectforeground=UI["surface"], highlightthickness=1,
                          highlightbackground=UI["surface"], highlightcolor=UI["primary"])
            ysb = ttk.Scrollbar(frame, command=txt.yview, style="Panel.Vertical.TScrollbar")
            xsb = ttk.Scrollbar(frame, command=txt.xview, orient="horizontal",
                                style="Panel.Horizontal.TScrollbar")
            txt.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
            txt.tag_configure("ok", foreground=UI["success"])
            txt.tag_configure("err", foreground=UI["danger"], font=FONT["mono_bold"])
            txt.tag_configure("stage", foreground=UI["primary"])
            txt.grid(row=0, column=0, sticky="nsew")
            ysb.grid(row=0, column=1, sticky="ns")
            xsb.grid(row=1, column=0, sticky="ew")
            empty = self.ui_label(frame, L("暂无输出\n运行时，日志会显示在这里",
                                           "No output yet\nLogs will appear here"),
                                  color="muted", justify="center")
            empty.place(relx=0.5, rely=0.5, anchor="center")
            self.log_empty[key] = empty
            nb.add(frame, text=tab_titles[key])
            self.tabs[key] = txt

        hist_frame = tk.Frame(nb, bg=UI["surface"], padx=16, pady=12)
        hist_frame.columnconfigure(0, weight=1)
        hist_frame.rowconfigure(1, weight=1)
        hist_bar = tk.Frame(hist_frame, bg=UI["surface"])
        hist_bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.history_count = self.ui_label(hist_bar, L("运行记录", "Run history"),
                                           font="small", color="muted")
        self.history_count.pack(side="left")
        ttk.Button(hist_bar, text=L("清空记录", "Clear history"), style="Quiet.Panel.TButton",
                   command=self.clear_history).pack(side="right")
        cols_ = ("time", "action", "result", "detail", "dur")
        self.hist_tree = ttk.Treeview(hist_frame, columns=cols_, show="headings", height=5,
                                      style="Panel.Treeview")
        for cid, text, w in zip(cols_, (L("时间", "Time"), L("动作", "Action"), L("结果", "Result"),
                                        L("说明", "Detail"), L("时长", "Duration")),
                                (180, 110, 140, 320, 80)):
            anchor = "e" if cid == "dur" else "w"
            self.hist_tree.heading(cid, text=text, anchor=anchor)
            self.hist_tree.column(cid, width=w, minwidth=w, stretch=cid == "detail", anchor=anchor)
        hsb = ttk.Scrollbar(hist_frame, command=self.hist_tree.yview, style="Panel.Vertical.TScrollbar")
        hxs = ttk.Scrollbar(hist_frame, command=self.hist_tree.xview, orient="horizontal",
                            style="Panel.Horizontal.TScrollbar")
        self.hist_tree.configure(yscrollcommand=hsb.set, xscrollcommand=hxs.set)
        self.hist_tree.grid(row=1, column=0, sticky="nsew")
        hsb.grid(row=1, column=1, sticky="ns")
        hxs.grid(row=2, column=0, sticky="ew")
        self.history_empty = self.ui_label(hist_frame, L("暂无运行记录", "No run records yet"),
                                           color="muted")
        nb.add(hist_frame, text=L("运行记录", "Run history"))

        # 「关于」页：原作者 / 特别鸣谢 / 许可
        about_frame = tk.Frame(nb, bg=UI["surface"], padx=16, pady=12)
        about_frame.columnconfigure(0, weight=1)
        about_frame.rowconfigure(0, weight=1)
        self.about_txt = tk.Text(about_frame, wrap="word", font=FONT["small"],
                                 bg=UI["surface"], fg=UI["text"], relief="flat",
                                 borderwidth=0, padx=12, pady=12, spacing1=2, spacing3=2,
                                 highlightthickness=0)
        asb = ttk.Scrollbar(about_frame, command=self.about_txt.yview,
                            style="Panel.Vertical.TScrollbar")
        self.about_txt.configure(yscrollcommand=asb.set)
        self.about_txt.grid(row=0, column=0, sticky="nsew")
        asb.grid(row=0, column=1, sticky="ns")
        self.set_about_text()
        nb.add(about_frame, text=L("关于", "About"))

        self.nb = nb
        nb.enable_traversal()

        notice = tk.Frame(body, bg=UI["tint"], padx=16, pady=10)
        notice.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        self.ui_label(notice, L("运行提示", "Notice"), font="strong", color="tint_text").pack(anchor="w", pady=(0, 4))
        self.hint = self.ui_label(notice, "", font="small", color="tint_text", justify="left", wraplength=800)
        self.hint.pack(fill="x")
        self.hint.bind("<Configure>", lambda e: self.hint.configure(wraplength=max(1, e.width)))

    # ---------- 语言 ----------
    def on_lang_change(self, _evt=None):
        global _LANG
        new = LANG_INTERNAL.get(self.lang_var.get(), "zh")
        if new == _LANG:
            return
        _LANG = new
        self.root.after_idle(self.rebuild_ui)

    def rebuild_ui(self):
        """按新语言重建整个界面（保留日志文本、运行记录与任务状态）"""
        self.save_config()
        logs = {k: self.tabs[k].get("1.0", "end-1c") for k in self.tabs}
        try:
            sel = self.nb.index(self.nb.select())
        except Exception:
            sel = 0
        for w in list(self.root.winfo_children()):
            w.destroy()
        self.build_ui()
        self.refresh_bridge_ip()
        self.refresh_history()
        for k, txt in logs.items():
            if txt and txt.strip():
                self.tabs[k].insert("1.0", txt)
                self.log_empty[k].place_forget()
        self.set_hint(default_hint())
        self.update_buttons()
        self.root.title(L("civswitch-kit 控制面板 · v%s", "civswitch-kit Control Panel · v%s",
                          self.version))
        try:
            self.nb.select(min(sel, len(self.nb.tabs()) - 1))
        except Exception:
            pass

    def set_about_text(self):
        self.about_txt.configure(state="normal")
        self.about_txt.delete("1.0", "end")
        self.about_txt.insert("1.0", about_text())
        self.about_txt.configure(state="disabled")

    # ---------- 配置/记录 ----------
    def load_config(self):
        try:
            return json.load(open(CONFIG_PATH, encoding="utf-8"))
        except Exception:
            return {}

    def save_config(self):
        try:
            json.dump({"console_ip": self.console_ip(),
                       "pc_ip": self.pc_var.get().strip(),
                       "restore_first": bool(self.restore_var.get()),
                       "ftp_port": str(self.ftp_port_var.get()).strip(),
                       "ftp_write": bool(self.ftp_write_var.get()),
                       "geometry": self.root.geometry(),
                       "lang": _LANG},
                      open(CONFIG_PATH, "w", encoding="utf-8"))
        except Exception:
            pass

    def load_history(self):
        try:
            data = json.load(open(HISTORY_PATH, encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def add_history(self, rec):
        self.history.insert(0, rec)
        self.history = self.history[:200]
        try:
            json.dump(self.history, open(HISTORY_PATH, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        except Exception:
            pass
        self.refresh_history()

    def refresh_history(self):
        self.hist_tree.delete(*self.hist_tree.get_children())
        for r in self.history:
            res = r.get("result", "")
            tag = "okrow" if "成功" in res or "完成" in res else "errrow"
            self.hist_tree.insert("", "end", values=(
                r.get("time", ""), hist_text(r.get("action", ""), HIST_ACT),
                hist_text(res, HIST_RES), r.get("detail", ""), r.get("dur", "")), tags=(tag,))
        self.hist_tree.tag_configure("okrow", foreground=UI["success"])
        self.hist_tree.tag_configure("errrow", foreground=UI["danger"])
        self.history_count.configure(text=L("共 %d 条记录", "%d records", len(self.history)))
        if self.history:
            self.history_empty.place_forget()
        else:
            self.history_empty.place(relx=0.5, rely=0.6, anchor="center")

    def clear_history(self):
        if messagebox.askyesno(L("清空", "Clear"),
                               L("确定清空全部运行记录？", "Clear all run records?")):
            self.history = []
            try:
                json.dump([], open(HISTORY_PATH, "w", encoding="utf-8"))
            except Exception:
                pass
            self.refresh_history()

    # ---------- PC IP / 桥接 ----------
    def refresh_bridge_ip(self):
        cur = read_bridge_pc_ip()
        if cur:
            self.bridge_ip_lbl.configure(
                text=L("桥接 PC_IP = %s", "Bridge PC_IP = %s", cur), fg=UI["muted"])
        else:
            self.bridge_ip_lbl.configure(
                text=L("桥接 PC_IP 未设置！填 PC IP 后点【写入桥接】",
                       "Bridge PC_IP is not set! Fill in the PC IP and click [Write bridge]"),
                fg=UI["danger"])

    def apply_pc_ip(self):
        pc = self.pc_var.get().strip()
        if not fmt_ip_ok(pc):
            messagebox.showwarning(L("IP 不对", "Invalid IP"),
                                   L("请先填写正确的 PC 局域网 IPv4",
                                     "Please enter a valid PC LAN IPv4 address"))
            return
        try:
            write_bridge_pc_ip(pc)
        except Exception as e:
            messagebox.showerror(L("写入失败", "Write failed"), str(e))
            return
        self.append_log("round", L("===== civ_bridge.js -> PC_IP = %s =====",
                                   "===== civ_bridge.js -> PC_IP = %s =====", pc), "stage")
        self.refresh_bridge_ip()
        self.set_hint(L("PC IP 已写入 port\\civ_bridge.js（等价 set-pc-ip.ps1）。",
                        "PC IP written to port\\civ_bridge.js (same as set-pc-ip.ps1)."))

    # ---------- 进程控制 ----------
    # ---------- 主机 IP 输入框（灰色示例占位） ----------
    def set_ip_placeholder(self):
        self.ip_placeholder_on = True
        self.ip_var.set(CONSOLE_IP_EXAMPLE)
        try:
            self.ip_entry.configure(style="Placeholder.Panel.TEntry")
        except Exception:
            pass

    def on_ip_focus_in(self, _event=None):
        if self.ip_placeholder_on:
            self.ip_placeholder_on = False
            self.ip_var.set("")
            try:
                self.ip_entry.configure(style="Panel.TEntry")
            except Exception:
                pass

    def on_ip_focus_out(self, _event=None):
        if not self.ip_var.get().strip():
            self.set_ip_placeholder()

    def console_ip(self):
        """真实的主机 IP；灰色占位/空值时返回空串"""
        if self.ip_placeholder_on:
            return ""
        return self.ip_var.get().strip()

    def validate_console_ip(self):
        cip = self.console_ip()
        if not fmt_ip_ok(cip):
            messagebox.showwarning(L("IP 不对", "Invalid IP"),
                                   L("请先填写正确的主机 IP", "Please enter a valid console IP"))
            return None
        return cip

    def ensure_bridge_ready(self):
        """round 前置检查：civ_bridge.js 的 PC_IP 已设置，必要时现场写入"""
        if read_bridge_pc_ip():
            return True
        pc = self.pc_var.get().strip()
        if fmt_ip_ok(pc) and messagebox.askyesno(
                L("PC_IP 未设置", "PC_IP not set"),
                L("civ_bridge.js 的 PC_IP 还是占位符。\n用当前 PC IP（%s）写入并继续？",
                  "civ_bridge.js still has the PC_IP placeholder.\nWrite the current PC IP (%s) and continue?") % pc):
            try:
                write_bridge_pc_ip(pc)
                self.refresh_bridge_ip()
                return True
            except Exception as e:
                messagebox.showerror(L("写入失败", "Write failed"), str(e))
        return False

    def run_round_click(self):
        job = self.jobs["round"]
        if job.proc and job.proc.poll() is None:
            messagebox.showinfo(L("提示", "Notice"),
                                L("一轮 P4 已在运行中", "A P4 round is already running"))
            return
        self.save_config()
        self.start_job("round")

    def start_job(self, key):
        job = self.jobs[key]
        if job.proc and job.proc.poll() is None:
            messagebox.showinfo(L("提示", "Notice") + ": " + job.title_text(),
                                L("%s 已在运行中", "%s is already running", job.title_text()))
            return
        cip = self.validate_console_ip()
        if not cip:
            return
        if key == "round" and not self.ensure_bridge_ready():
            return

        if key == "round":
            job.phase = "restore" if self.restore_var.get() else "engine"
            job.dump_mode = bool(self.dump_var.get())
        else:
            job.phase = None
        job.killed = False
        job.saw_2_4 = job.saw_ok = job.saw_dump = job.restore_ok = False
        job.bridge_sent = False
        job.run_dir = None
        job.engine_proc = job.bridge_proc = None
        job.notes = []
        job.last_code = None
        job.t0 = time.time()

        if key == "round" and job.phase == "restore":
            self.spawn(job, RESTORE_CMD(cip), COMMON_CWD, tag=L("[存档] ", "[save] "))
            self.set_hint(L(
                "第 1 步：正在重写触发存档（约 13 秒，RESTORE DONE 后自动起引擎）。\n"
                "完成后主机会重新武装；跑动期间别碰主机。",
                "Step 1: rewriting the trigger save (~13 s; the engine starts automatically after "
                "RESTORE DONE).\nThe console re-arms after it finishes; don't touch the console while "
                "it runs."))
        elif key == "round":
            self.start_engine(job, cip)
        elif key == "restore":
            self.spawn(job, RESTORE_CMD(cip), COMMON_CWD)
            self.set_hint(L("正在重写触发存档（约 13 秒）……成功标志：RESTORE DONE。",
                            "Rewriting the trigger save (~13 s)... success marker: RESTORE DONE."))
        elif key == "backup":
            self.spawn(job, BACKUP_CMD(cip), COMMON_CWD)
            self.set_hint(L("正在全量备份 save:/saves（1.3MB 左右，SNAP 流式传输）……",
                            "Backing up save:/saves (~1.3 MB, SNAP streaming)..."))
        self.update_buttons()

    def start_engine(self, job, cip=None):
        cip = cip or self.validate_console_ip()
        if not cip:
            return
        pc = read_bridge_pc_ip()
        if not pc:
            messagebox.showerror(L("PC_IP 未设置", "PC_IP not set"),
                                 L("引擎需要 PC IP；请先写入桥接。",
                                   "The engine needs a PC IP; write the bridge first."))
            return
        env = dict(os.environ)
        if job.dump_mode:
            env["NS2_FIRMWARE_DUMP_DIR"] = DUMPS_DIR
        job.phase = "engine"
        job.engine_t0 = time.time()
        proc = self.spawn(job, ENGINE_CMD(pc, job.dump_mode), ENGINE_CWD, env=env)
        if proc:
            job.engine_proc = proc
        self.set_hint(L(
            "引擎已启动：等它打印 Waiting/Run folder 后自动发桥接。\n"
            "2/4 采集竞态期间主机卡顿属正常；进度只看 PC 端，别碰主机。",
            "Engine started: the bridge is sent automatically after it prints Waiting/Run folder.\n"
            "Console stutter during the 2/4 acquisition race is normal; watch the PC side only and "
            "don't touch the console."))

    def spawn(self, job, cmd, cwd, env=None, tag=""):
        """起一个子进程挂到 job.proc 并开始读输出；tag 用于同页多进程前缀"""
        try:
            proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL,
                                    creationflags=NO_WINDOW, env=env)
        except Exception as e:
            messagebox.showerror(L("启动失败", "Start failed"),
                                 "%s\n%s" % (" ".join(cmd), e))
            return None
        job.proc = proc
        self.append_log(job.key, L("===== 启动: %s (PID %d) =====",
                                   "===== Started: %s (PID %d) =====",
                                   " ".join(cmd), proc.pid), "stage")
        threading.Thread(target=self.reader, args=(job, proc, tag), daemon=True).start()
        return proc

    def send_bridge(self):
        job = self.jobs["round"]
        if job.bridge_sent or not (job.engine_proc and job.engine_proc.poll() is None):
            return
        cip = self.console_ip()
        if not cip:
            self.append_log("round", L("!! 主机 IP 未填写，跳过自动桥接。请填写主机 IP 后重新跑。",
                                       "!! Console IP is empty; skipping automatic bridge. "
                                       "Fill it in and rerun."), "err")
            return
        job.bridge_sent = True
        proc = subprocess.Popen(BRIDGE_CMD(cip), cwd=COMMON_CWD, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                creationflags=NO_WINDOW)
        job.bridge_proc = proc
        self.append_log("round", L("===== 自动发送桥接 (PID %d) =====",
                                   "===== Sending bridge automatically (PID %d) =====", proc.pid), "stage")
        threading.Thread(target=self.reader, args=(job, proc, L("[桥接] ", "[bridge] ")), daemon=True).start()

    def reader(self, job, proc, tag=""):
        for raw in iter(proc.stdout.readline, b""):
            try:
                line = raw.decode("utf-8")
            except UnicodeDecodeError:
                line = raw.decode("gbk", "replace")
            self.q.put(("line", job.key, tag + line.rstrip("\r\n")))
        code = proc.wait()
        if proc is job.proc:
            self.q.put(("exit", job.key, code))

    def stop_job(self, key):
        job = self.jobs[key]
        procs = [p for p in (job.proc, job.engine_proc, job.bridge_proc)
                 if p and p.poll() is None]
        if not procs:
            return
        job.killed = True
        for p in procs:
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                               capture_output=True, creationflags=NO_WINDOW)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        self.append_log(key, L("===== 已手动停止 =====", "===== Stopped manually ====="), "err")

    def stop_all(self):
        for key in ("round", "restore", "backup"):
            self.stop_job(key)
        try:
            self.ftp_stop_held()
        except Exception:
            pass
        self.set_hint(L("已停止全部任务。", "All tasks stopped."))

    # ---------- SD 卡 FTP（held 模式） ----------
    def ftp_set_status(self, text):
        if self.ftp_status_lbl is not None:
            self.ftp_status_lbl.configure(text=text)

    def ftp_refresh_buttons(self):
        if self.ftp_status_lbl is None:
            return
        job = self.jobs["sdftp"]
        held_running = bool(job.engine_proc and job.engine_proc.poll() is None)
        ftp_running = bool(self.ftp_proc and self.ftp_proc.poll() is None)
        ready = bool(self.ftp_socket and self.ftp_handle)
        self.btn_ftp_held.configure(state="disabled" if held_running else "normal")
        self.btn_ftp_held_stop.configure(state="normal" if held_running else "disabled")
        self.btn_ftp_start.configure(state="normal" if (ready and not ftp_running) else "disabled")
        self.btn_ftp_stop.configure(state="normal" if ftp_running else "disabled")
        if self.ftp_url_lbl is not None:
            self.ftp_url_lbl.configure(
                text=L("FTP 地址：%s", "FTP URL: %s", self.ftp_url) if self.ftp_url
                else L("FTP 地址：-", "FTP URL: -"))

    def ftp_send_bridge(self):
        if self.ftp_bridge_sent:
            return
        cip = self.console_ip()
        if not cip:
            self.append_log("sdftp", L("!! 主机 IP 未填写，无法发送桥接。", "!! Console IP is empty; cannot "
                                       "send the bridge."), "err")
            return
        self.ftp_bridge_sent = True
        job = self.jobs["sdftp"]
        proc = subprocess.Popen(BRIDGE_CMD(cip), cwd=COMMON_CWD, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                creationflags=NO_WINDOW)
        job.bridge_proc = proc
        self.append_log("sdftp", L("===== 自动发送桥接 (PID %d) =====",
                                   "===== Sending bridge automatically (PID %d) =====", proc.pid), "stage")
        threading.Thread(target=self.reader, args=(job, proc, L("[桥接] ", "[bridge] ")), daemon=True).start()

    def ftp_start_held(self):
        cip = self.validate_console_ip()
        if not cip:
            return
        pc = read_bridge_pc_ip()
        if not pc:
            messagebox.showerror(L("PC_IP 未设置", "PC_IP not set"),
                                 L("引擎需要 PC IP；请先写入桥接。",
                                   "The engine needs a PC IP; write the bridge first."))
            return
        job = self.jobs["sdftp"]
        if job.engine_proc and job.engine_proc.poll() is None:
            return
        job.phase = "engine"
        job.t0 = time.time()
        job.engine_t0 = time.time()
        job.killed = False
        job.notes = []
        job.run_dir = None
        job.last_code = None
        job.bridge_sent = False
        self.ftp_socket = None
        self.ftp_handle = None
        self.ftp_url = None
        self.ftp_run_dir = None
        self.ftp_bridge_sent = False
        self.ftp_set_status(L("启动中……", "starting..."))
        proc = self.spawn(job, ENGINE_HELD_CMD(pc), ENGINE_CWD)
        if not proc:
            self.ftp_set_status(L("启动失败", "start failed"))
            return
        job.engine_proc = proc
        self.append_log("sdftp", L("===== held 引擎启动: %s =====",
                                   "===== held engine started: %s =====", " ".join(ENGINE_HELD_CMD(pc))),
                        "stage")
        self.set_hint(L(
            "已启动 held 模式引擎：等它打印 held endpoint ready 后会自动解析 SD 相册句柄，"
            "然后点【启动 FTP】。\n"
            "注意：held 会话不会自己释放，FTP 用完务必点【停止 held】（会发送 sentinel 释放 FS）。",
            "Held-mode engine started: once it prints 'held endpoint ready' the SD album handle is "
            "resolved automatically; then click [Start FTP].\n"
            "The held session never releases itself - after using FTP always click [Stop held] "
            "(it sends the sentinel that releases FS)."))
        self.ftp_refresh_buttons()

    def ftp_resolve_handle(self):
        run_dir = self.ftp_run_dir
        if not run_dir:
            return
        self.ftp_set_status(L("解析 SD 句柄……", "resolving SD handle..."))

        def work():
            result = {}
            try:
                proc = subprocess.run(RESOLVE_SD_CMD(run_dir), cwd=BASE, capture_output=True,
                                      timeout=180, creationflags=NO_WINDOW)
                text = proc.stdout.decode("utf-8", "replace").strip()
                line = text.splitlines()[-1] if text else ""
                result = json.loads(line) if line else {}
                if not result.get("ok"):
                    result.setdefault("error", (proc.stderr or b"").decode("utf-8", "replace")[-400:]
                                      or "resolver failed")
            except Exception as e:
                result = {"ok": False, "error": str(e)}
            marker = "OK " if result.get("ok") else "ERR "
            self.q.put(("line", "sdftp", marker + L("===== resolver: %s =====",
                                                    "===== resolver: %s =====",
                                                    json.dumps(result, ensure_ascii=False)[:600])))
            if result.get("ok") and result.get("handle"):
                self.ftp_socket = result.get("socket")
                self.ftp_handle = result.get("handle")
                entries = result.get("listing", {}).get("entries") or []
                self.q.put(("line", "sdftp", L("SD 句柄 = %s；根目录条目 %d 个（%s）",
                                               "SD handle = %s; %d entries at root (%s)",
                                               self.ftp_handle, len(entries),
                                               ", ".join(str(e.get("name")) for e in entries[:6])), "ok"))
            self.root.after(0, self.ftp_after_resolve)

        threading.Thread(target=work, daemon=True).start()

    def ftp_after_resolve(self):
        if self.ftp_socket and self.ftp_handle:
            self.ftp_set_status(L("held 就绪，句柄 %s", "held ready, handle %s", self.ftp_handle))
        else:
            self.ftp_set_status(L("句柄解析失败（看 SD FTP 输出页）", "handle resolve failed (see SD FTP log)"))
        self.ftp_refresh_buttons()

    def ftp_start_server(self):
        if not (self.ftp_socket and self.ftp_handle):
            messagebox.showerror(L("还没就绪", "Not ready"),
                                 L("请先点【① 启动 held 会话】并等句柄解析成功。",
                                   "Click [1) Start held session] first and wait for the handle."))
            return
        try:
            port = int(str(self.ftp_port_var.get()).strip() or "2121")
            if not 1 <= port <= 65535:
                raise ValueError("port")
        except Exception:
            messagebox.showerror(L("端口无效", "Invalid port"), L("FTP 端口必须是 1..65535。",
                                                                 "FTP port must be 1..65535."))
            return
        allow_write = bool(self.ftp_write_var.get())
        if allow_write:
            if not messagebox.askyesno(
                    L("允许写入 SD 卡？", "Allow SD writes?"),
                    L("将允许 FTP 客户端在 SD 相册里新建/覆盖/删除文件。\n"
                      "建议先只读验证，确认无误后再开写。继续？",
                      "FTP clients will be able to create/overwrite/delete files in the SD album.\n"
                      "Verify read-only first, then enable writes. Continue?")):
                return
        if self.ftp_proc and self.ftp_proc.poll() is None:
            return
        cmd = SD_FTP_CMD(self.ftp_socket, self.ftp_handle, port, "/", allow_write, "127.0.0.1")
        job = self.jobs["sdftp"]
        try:
            proc = subprocess.Popen(cmd, cwd=BASE, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    creationflags=NO_WINDOW)
        except Exception as e:
            messagebox.showerror(L("启动失败", "Start failed"), "%s\n%s" % (" ".join(cmd), e))
            return
        self.ftp_proc = proc
        self.append_log("sdftp", L("===== 启动 FTP: %s =====", "===== Starting FTP: %s =====",
                                   " ".join(cmd)), "stage")
        threading.Thread(target=self.reader, args=(job, proc, L("[FTP] ", "[FTP] ")), daemon=True).start()
        self.ftp_set_status(L("FTP 启动中（端口 %d）", "FTP starting (port %d)", port))
        self.ftp_refresh_buttons()

    def ftp_stop_server(self):
        if self.ftp_proc and self.ftp_proc.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.ftp_proc.pid)],
                           capture_output=True, creationflags=NO_WINDOW)
            self.append_log("sdftp", L("===== 已停止 FTP =====", "===== FTP stopped ====="), "err")
        self.ftp_url = None
        self.ftp_refresh_buttons()

    def ftp_stop_held(self):
        self.ftp_stop_server()
        job = self.jobs["sdftp"]
        proc = job.engine_proc
        if not (proc and proc.poll() is None):
            self.ftp_refresh_buttons()
            return
        run_dir = self.ftp_run_dir or job.run_dir
        if run_dir:
            try:
                subprocess.run(["node", "engine/rpc.cjs", run_dir, "stop"], cwd=PORT_DIR,
                               capture_output=True, timeout=60, creationflags=NO_WINDOW)
                self.append_log("sdftp", L("===== 已发送 held 释放（rpc.cjs stop，sentinel）=====",
                                           "===== held release sent (rpc.cjs stop, sentinel) ====="), "stage")
            except Exception as e:
                self.append_log("sdftp", "rpc.cjs stop failed: %s" % e, "err")
        deadline = time.time() + 25
        while time.time() < deadline and proc.poll() is None:
            time.sleep(0.5)
        if proc.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, creationflags=NO_WINDOW)
            self.append_log("sdftp", L("===== held 引擎未自行退出，已强制结束 =====",
                                       "===== held engine did not exit; killed ====="), "err")
        self.ftp_socket = None
        self.ftp_handle = None
        self.ftp_set_status(L("未启动", "Not started"))
        self.ftp_refresh_buttons()

    def on_ftp_exit(self, job, code, dur):
        self.append_log("sdftp", L("===== held 会话结束（退出码 %d，用时 %s）=====",
                                   "===== held session ended (exit code %d, elapsed %s) =====",
                                   code, dur), "stage")
        self.ftp_socket = None
        self.ftp_handle = None
        self.ftp_url = None
        self.ftp_proc = None
        self.ftp_set_status(L("未启动", "Not started"))
        self.add_history({"time": time.strftime("%Y-%m-%d %H:%M:%S"),
                          "action": "SD FTP held",
                          "result": "成功" if code == 0 else "失败",
                          "detail": "held endpoint released" if code == 0 else "退出码 %d" % code,
                          "dur": dur})
        self.ftp_refresh_buttons()

    # ---------- 文件夹 ----------
    def open_runs(self):
        try:
            os.startfile(RUNS_DIR)
        except Exception as e:
            messagebox.showerror(L("打不开", "Cannot open"),
                                 L("runs 目录还没生成（跑过一轮后才有）。\n%s",
                                   "The runs folder does not exist yet (it appears after one round).\n%s") % e)

    def open_dumps(self):
        try:
            os.startfile(DUMPS_DIR)
        except Exception as e:
            messagebox.showerror(L("打不开", "Cannot open"),
                                 L("dumps 目录还没生成（勾选固件 dump 跑一轮后才有）。\n%s",
                                   "The dumps folder does not exist yet (check Firmware dump and run "
                                   "one round).\n%s") % e)

    # ---------- 探测 ----------
    def probe_loader(self):
        cip = self.validate_console_ip()
        if not cip:
            return
        if not messagebox.askyesno(
                L("探测", "Probe"),
                L("probe 会产生一次空连接：累积 3 次会触发 loader 重建。\n"
                  "只在本轮开跑前确认 loader 是否在线时使用。继续？",
                  "probe opens one empty connection: 3 accumulate and the loader is rebuilt.\n"
                  "Use it only to check whether the loader is alive before starting a round. "
                  "Continue?")):
            return
        self.append_log("backup", L("===== 探测 %s:9026 =====", "===== Probing %s:9026 =====", cip), "stage")
        try:
            proc = subprocess.Popen(PROBE_CMD(cip), cwd=COMMON_CWD, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    creationflags=NO_WINDOW)
        except Exception as e:
            messagebox.showerror(L("启动失败", "Start failed"), str(e))
            return

        def drain():
            for raw in iter(proc.stdout.readline, b""):
                self.q.put(("line", "backup", raw.decode("utf-8", "replace").rstrip("\r\n")))
            proc.wait()

        threading.Thread(target=drain, daemon=True).start()

    # ---------- 日志/状态 ----------
    def append_log(self, key, line, tag=None):
        self.log_empty[key].place_forget()
        txt = self.tabs[key]
        txt.insert("end", line + "\n", tag or ())
        txt.see("end")
        lines = int(txt.index("end-1c").split(".")[0])
        if lines > 4000:
            txt.delete("1.0", "2000.0")

    def on_line(self, key, line):
        if not line:
            return
        low = line.lower()
        job = self.jobs[key]
        if "restore done" in low:      # round 内嵌恢复与恢复卡片共用
            job.restore_ok = True
            self.append_log(key, line, "ok")
            return
        if key == "round":
            m = re.search(r"Run folder: (\S+)", line)
            if m:
                job.run_dir = m.group(1)
                self.append_log(key, line, "stage")
                self.send_bridge()
                return
            if "waiting for" in low:
                job.notes.append(L("引擎已就绪等待", "engine ready and waiting"))
                self.append_log(key, line, "stage")
                self.send_bridge()
                return
            if re.search(r"[1234]/4", line):
                if "2/4" in line and not job.saw_2_4:
                    job.saw_2_4 = True
                    job.notes.append(L("进过 2/4（存档已动过）", "reached 2/4 (save already touched)"))
                    self.set_hint(L("已进入 2/4 采集竞态：主机卡顿/掉帧属正常，别碰主机，耐心等。",
                                    "Entered the 2/4 acquisition race: console stutter/dropped frames "
                                    "are normal. Don't touch the console; just wait."))
                self.append_log(key, line, "stage")
                return
            if "fs execution verified" in low:
                job.saw_ok = True
                job.notes.append("4/4 verified")
                self.append_log(key, line, "ok")
                return
            if "firmware: dump complete" in low:
                job.saw_dump = True
                job.notes.append(L("固件 dump 完成", "firmware dump complete"))
                self.append_log(key, line, "ok")
                return
            if "system-code dump" in low or "dump folder" in low:
                self.append_log(key, line, "stage")
                return
            if "restore done" in low:
                job.restore_ok = True
                self.append_log(key, line, "ok")
                return
            if "connected." in low or "checking the application" in low:
                self.append_log(key, line, "stage")
                return
        if key == "sdftp":
            m = re.search(r"Run folder: (\S+)", line)
            if m:
                job.run_dir = m.group(1)
                self.ftp_run_dir = m.group(1)
                self.append_log(key, line, "stage")
                self.ftp_send_bridge()
                return
            if "waiting for" in low:
                self.append_log(key, line, "stage")
                self.ftp_send_bridge()
                return
            m = re.search(r"held endpoint ready: (\S+)", line)
            if m:
                self.ftp_socket = m.group(1)
                self.append_log(key, line, "ok")
                self.ftp_set_status(L("held 端点 %s，正在解析 SD 句柄……",
                                      "held endpoint %s; resolving SD handle...", self.ftp_socket))
                self.ftp_resolve_handle()
                return
            m = re.search(r"\[sd-ftp\] listening on (ftp://\S+)", line)
            if m:
                self.ftp_url = m.group(1)
                self.ftp_set_status(L("FTP 运行中", "FTP running"))
                self.ftp_refresh_buttons()
                self.append_log(key, line, "ok")
                return
            if "fs execution verified" in low:
                self.append_log(key, line, "ok")
                return
        if any(w in low for w in ERR_WORDS):
            if "timed out" in low and job.engine_proc and job.proc is job.engine_proc:
                job.notes.append(L("主机响应超时（多半已卡死）", "console response timed out (most likely wedged)"))
            self.append_log(key, line, "err")
            return
        if any(w in low for w in OK_WORDS):
            self.append_log(key, line, "ok")
            return
        self.append_log(key, line)

    def on_exit(self, key, code):
        job = self.jobs[key]
        job.last_code = code
        dur = fmt_dur(time.time() - job.t0) if job.t0 else "-"
        self.append_log(key, L("===== 结束: 退出码 %d，用时 %s =====",
                               "===== Finished: exit code %d, elapsed %s =====", code, dur), "stage")
        if key == "round":
            self.on_round_exit(job, code, dur)
        elif key == "sdftp":
            self.on_ftp_exit(job, code, dur)
        elif key == "restore":
            result = L("成功", "Success") if (not job.killed and code == 0 and job.restore_ok) else (
                L("被终止", "Stopped") if job.killed else L("失败", "Failed"))
            self.add_history({"time": time.strftime("%Y-%m-%d %H:%M:%S"),
                              "action": "恢复存档",
                              "result": {"Success": "成功", "Stopped": "被终止",
                                         "Failed": "失败"}.get(result, "失败"),
                              "detail": "RESTORE DONE" if job.restore_ok else "退出码 %d" % code,
                              "dur": dur})
            if result == L("成功", "Success"):
                self.set_hint(L(
                    "✅ 存档已恢复（RESTORE DONE）。\n"
                    "接下来：长按电源 12 秒硬重启 → 开机 → Load Game → Awaiting payload →"
                    "【一键跑一轮】（记得取消勾选「先恢复存档」）。",
                    "✅ Save restored (RESTORE DONE).\n"
                    "Next: hold the power button for 12 s to hard reboot -> boot -> Load Game -> "
                    "Awaiting payload -> [Run a round] (remember to uncheck 'Restore trigger save first')."))
        elif key == "backup":
            result = L("完成", "Done") if (not job.killed and code == 0) else (
                L("被终止", "Stopped") if job.killed else L("失败", "Failed"))
            self.add_history({"time": time.strftime("%Y-%m-%d %H:%M:%S"),
                              "action": "备份存档",
                              "result": {"Done": "完成", "Stopped": "被终止",
                                         "Failed": "失败"}.get(result, "失败"),
                              "detail": L("产物在 save-tools\\backups\\（见日志末尾 manifest 路径）",
                                          "Output under save-tools\\backups\\ (see the manifest path "
                                          "at the end of the log)")
                                        if code == 0 else "退出码 %d" % code,
                              "dur": dur})
        self.update_buttons()

    def on_round_exit(self, job, code, dur):
        # round 可能停在 restore 阶段（失败）或 engine 阶段
        if job.phase == "restore":
            # 恢复脚本退出：失败则终止本轮，成功则接着起引擎
            if job.killed:
                self.add_history({"time": time.strftime("%Y-%m-%d %H:%M:%S"),
                                  "action": "一轮P4", "result": "被终止",
                                  "detail": "恢复阶段被终止", "dur": dur})
                self.set_hint(L("已终止。", "Stopped."))
                return
            if not (code == 0 and job.restore_ok):
                self.add_history({"time": time.strftime("%Y-%m-%d %H:%M:%S"),
                                  "action": "一轮P4", "result": "失败",
                                  "detail": "恢复存档失败（loader 在线吗？）退出码 %d" % code,
                                  "dur": dur})
                self.set_hint(L(
                    "❌ 恢复存档失败，本轮中止。\n"
                    "确认主机停在 Load Game（屏幕有 Awaiting payload）后重试。",
                    "❌ Restoring the save failed; this round is aborted.\n"
                    "Make sure the console is at Load Game (Awaiting payload on screen) and retry."))
                return
            self.append_log("round", L("===== 恢复完成，接着起引擎 =====",
                                       "===== Restore done; starting the engine ====="), "stage")
            self.start_engine(job)
            return

        # 引擎阶段退出：杀掉可能残留的桥接，然后汇总
        if job.bridge_proc and job.bridge_proc.poll() is None:
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(job.bridge_proc.pid)],
                               capture_output=True, creationflags=NO_WINDOW)
            except Exception:
                pass
        self.summarize_round(job, code, dur)

    def summarize_round(self, job, code, dur):
        run_dir = job.run_dir or latest_engine_run_dir()
        verified = error = None
        stages = []
        if run_dir:
            self.append_log("round", L("run=%s", "run=%s", run_dir), "stage")
            res = load_json(os.path.join(run_dir, "result.json"))
            if res is not None:
                verified, error = res.get("verified"), res.get("error")
                self.append_log("round", L("verified=%s error=%s", "verified=%s error=%s",
                                           verified, error or ""), "stage")
            pipe = load_json(os.path.join(run_dir, "switch2", "pipeline.json"))
            for st in (pipe or {}).get("stages", []):
                stages.append("%s : %s" % (st.get("name"), st.get("status")))
                self.append_log("round", L("stage %s", "stage %s", stages[-1]), "stage")
        ok = (code == 0 and (job.saw_ok or verified is True))

        if job.killed:
            result = L("被终止", "Stopped")
            hint = L("已停止本轮。", "This round was stopped.")
            result_data = "被终止"
        elif ok:
            result = L("成功", "Success")
            result_data = "成功"
            notes = "；".join(job.notes) or "verified"
            hint = L(
                "✅ 成功！FS 已验证（verified=true）。\n"
                "主机可正常重启。跑下一轮前：主机活着→点【恢复存档】后硬重启一次；"
                "已卡死→硬重启后 Load Game 再【恢复存档】。",
                "✅ Success! FS verified (verified=true).\n"
                "The console can reboot normally. Before the next round: console alive -> click "
                "[Restore save] then hard reboot once; console wedged -> hard reboot, Load Game, "
                "then [Restore save].")
            if job.dump_mode:
                hint += L(
                    "\n\n📦 固件 dump 已落在 port\\engine\\dumps\\（约 222MB / 90 titles）。"
                    "引擎下次启动会清空该目录——现在就拷走！",
                    "\n\n📦 The firmware dump is in port\\engine\\dumps\\ (~222 MB / 90 titles). "
                    "The next engine start clears that folder - copy it out now!")
        else:
            result = L("失败", "Failed")
            result_data = "失败"
            notes = "；".join(job.notes) or ("退出码 %d" % code)
            hint = L(
                "❌ 本轮失败（%s）。下一轮按实测协议：\n"
                "· 主机活着（仍停在 Awaiting payload）→ 点【恢复存档】→ 长按电源 12 秒硬重启 → "
                "Load Game → 【一键跑一轮】（不勾恢复）。\n"
                "· 主机已卡死 → 硬重启 → Load Game →【恢复存档】→ 再硬重启 → Load Game → "
                "【一键跑一轮】（不勾恢复）。",
                "❌ This round failed (%s). Next round follows the measured protocol:\n"
                "· Console alive (still at Awaiting payload) -> click [Restore save] -> hold power "
                "12 s for a hard reboot -> Load Game -> [Run a round] (restore unchecked).\n"
                "· Console wedged -> hard reboot -> Load Game -> [Restore save] -> hard reboot again "
                "-> Load Game -> [Run a round] (restore unchecked).") % notes
            info = analyze_engine_failure(run_dir)
            if info:
                kind, message, stats = info
                name, verdict = FAIL_KINDS.get(kind, ("未知类型", "Unknown type", False))[:2], \
                    FAIL_KINDS.get(kind, (None, None, False))[2]
                diag = "%s [%s] %s %s" % (L(name[0], name[1]), kind, message, stats)
                self.append_log("round", L("【失败诊断】%s", "[Failure diagnosis] %s", diag), "stage")
                job.notes.append(L("诊断:", "diag:") + L(name[0], name[1]))
                notes = "；".join(job.notes)
                if verdict is True:
                    hint += L(
                        "\n\n📋 失败诊断：%s\n→ 已知可循环类型（每 boot 命中约 30%%），"
                        "按上面的循环继续重抽即可。",
                        "\n\n📋 Failure diagnosis: %s\n-> Known retryable type (~30%% per boot); "
                        "just keep redrawing via the loop above.") % diag
                elif verdict is None:
                    hint += L(
                        "\n\n📋 失败诊断：%s\n→ 可先继续循环；若连续多轮都是此类型，"
                        "把 runs 目录下该次运行日志发去分析。",
                        "\n\n📋 Failure diagnosis: %s\n-> You can keep looping for now; if several "
                        "rounds in a row end the same way, send the run log from the runs folder for "
                        "analysis.") % diag
                else:
                    hint += L(
                        "\n\n📋 失败诊断：%s\n→ 不在已知可循环名单里，建议把该次运行目录"
                        "发去分析。",
                        "\n\n📋 Failure diagnosis: %s\n-> Not in the known-retryable list; send that "
                        "run folder for analysis.") % diag
        self.add_history({"time": time.strftime("%Y-%m-%d %H:%M:%S"),
                          "action": "一轮P4", "result": result_data,
                          "detail": notes[:300], "dur": dur})
        self.set_hint(hint)

    def update_buttons(self):
        for key, (bs, bp) in self.job_btns.items():
            running = self.jobs[key].proc and self.jobs[key].proc.poll() is None
            bs.configure(state="disabled" if running else "normal")
            bp.configure(state="normal" if running else "disabled")
        try:
            self.ftp_refresh_buttons()
        except Exception:
            pass

    def set_hint(self, text):
        self.hint.configure(text=text)

    def poll(self):
        try:
            while True:
                kind, key, payload = self.q.get_nowait()
                if kind == "line":
                    self.on_line(key, payload)
                else:
                    self.on_exit(key, payload)
        except queue.Empty:
            pass
        # 兜底：引擎启动 30 秒仍未打印就绪标记也发桥接（同 run-p4-once.ps1）
        job = self.jobs["round"]
        if (job.phase == "engine" and not job.bridge_sent and job.engine_t0
                and job.engine_proc and job.engine_proc.poll() is None
                and time.time() - job.engine_t0 > BRIDGE_SEND_DELAY):
            self.append_log("round", L("===== 30 秒未见就绪标记，兜底发送桥接 =====",
                                       "===== No ready marker after 30 s; sending bridge as fallback ====="),
                            "stage")
            self.send_bridge()
        # 兜底：held 引擎启动 30 秒仍未打印就绪标记也发桥接
        jf = self.jobs["sdftp"]
        if (jf.phase == "engine" and not self.ftp_bridge_sent and jf.engine_t0
                and jf.engine_proc and jf.engine_proc.poll() is None
                and time.time() - jf.engine_t0 > BRIDGE_SEND_DELAY):
            self.append_log("sdftp", L("===== held：30 秒未见就绪标记，兜底发送桥接 =====",
                                       "===== held: no ready marker after 30 s; sending bridge as fallback ====="),
                            "stage")
            self.ftp_send_bridge()
        for key, st in self.job_status.items():
            jb = self.jobs[key]
            if jb.proc and jb.proc.poll() is None:
                phase = {"restore": L("恢复中", "restoring"),
                         "engine": L("引擎运行", "engine running")}.get(jb.phase, "")
                st.configure(text=L("运行中 %s(%s)", "Running %s(%s)", phase, fmt_dur(time.time() - jb.t0)),
                             fg=UI["primary"])
            else:
                code = jb.last_code
                st.configure(text=L("空闲", "Idle") if code is None
                             else L("退出码 %s", "Exit code %s", code), fg=UI["muted"])
        self.root.after(200, self.poll)

    def on_close(self):
        running = [j.title_text() for j in self.jobs.values() if j.proc and j.proc.poll() is None]
        if running:
            if not messagebox.askyesno(L("退出", "Exit"),
                                       L("还有任务在运行：%s\n终止并退出？",
                                         "Tasks are still running: %s\nTerminate and exit?") % "、".join(running)):
                return
            self.stop_all()
        self.save_config()
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
