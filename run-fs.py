#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lobby -> Remote JS Loader -> CivSwitch Stage 2 FS with a held RPC session.

This is the Linux-native counterpart of civswitch-kit's run-p4-once.ps1 for the
"load from Lobby" path:

  1. optionally injects the stock CivSwitch loader (payloads/core.js) into the
     Civ7 Host Lobby through the existing CivSwitchLDN panel (no Switch 1 NRO);
  2. waits for the console's Remote JS Loader on :9026;
  3. starts `port/engine/run.cjs --rpc <PC_IP>` and waits until it listens;
  4. sends port/civ_bridge.js with PC_IP patched to this computer;
  5. keeps the engine process in the foreground, so the Stage 2 FS endpoint and
     the RPC bridge stay alive until Ctrl-C.

The console must be in:
  Civilization VII -> MULTIPLAYER -> WIRELESS -> CREATE GAME -> HOST LOBBY

Use --no-lobby when the loader is already armed (for example from the XSTRIG
save row or from the launcher's double-R3 gesture).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_KIT = HERE / "kit"
DEFAULT_PANEL = HERE / "panel"
LOADER_PORT = 9026
ENGINE_PORT = 39380


def die(message: str) -> "NoReturn":
    print("\nFAILED: " + message, file=sys.stderr)
    raise SystemExit(1)


def local_ip_towards(host: str) -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect((host, LOADER_PORT))
            return sock.getsockname()[0]
    except OSError:
        return None


def has_local_address(address: str) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((address, 0))
            return True
    except OSError:
        return False


def wait_local_address(address: str, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if has_local_address(address):
            return
        time.sleep(1)
    die("computer address %s is not up; reconnect the wired LAN and retry" % address)


def send_script(host: str, port: int, code: str, timeout: float) -> str:
    with socket.create_connection((host, port), timeout=8) as sock:
        sock.sendall(code.encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)
        sock.settimeout(timeout)
        data = b""
        try:
            while True:
                block = sock.recv(65536)
                if not block:
                    break
                data += block
        except socket.timeout:
            pass
    return data.decode("utf-8", "replace")


def loader_ready(host: str, port: int) -> bool:
    nonce = "RUNFS_" + uuid.uuid4().hex
    try:
        out = send_script(host, port, "log('%s')" % nonce, timeout=10)
    except OSError:
        return False
    return nonce in out


def neighbor_ipv4() -> list[str]:
    """Best-effort candidates from the ARP table (DHCP moves the console)."""
    try:
        out = subprocess.run(["ip", "-4", "neigh", "show"], text=True, capture_output=True).stdout
    except OSError:
        return []
    found = []
    for line in out.splitlines():
        parts = line.split()
        if parts and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", parts[0]):
            found.append(parts[0])
    return found


def wait_loader(hosts: list[str], port: int, seconds: float) -> str:
    print("Waiting for the Remote JS Loader on %s:%d ..." % (hosts[0], port), flush=True)
    if len(hosts) > 1:
        print("  candidates: %s" % ", ".join(hosts), flush=True)
    deadline = time.time() + seconds
    while time.time() < deadline:
        for host in hosts:
            if loader_ready(host, port):
                print("[ok] loader online at %s:%d" % (host, port), flush=True)
                return host
        print("  ... no loader yet", flush=True)
        time.sleep(3)
    die(
        "loader did not answer on port %d.\n"
        "On S2 select the XSTRIG save in Load Game (or start the loader from the menu), "
        "wait for 'Awaiting payload at <IP>:9026', then pass --console-ip <that IP>."
        % port
    )


def read_state(panel: Path) -> dict:
    path = panel / "data" / "state" / "civswitchldn.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def inspect_ldn(panel: Path) -> dict:
    integration = panel / "engines" / "CivSwitchLDN" / "integration.cjs"
    if not integration.is_file():
        die("CivSwitchLDN panel not found at %s\n"
            "Pass --panel /path/to/iz2s-panel/iz2s-platform-run22, "
            "or use the Switch 1 NRO from the original kit." % panel)
    node = shutil.which("node")
    if not node:
        die("node was not found in PATH")
    code = (
        "require(%s).inspect(%s).then(x=>{console.log(JSON.stringify(x));"
        "process.exit(0)}).catch(e=>{console.error(e.message);process.exit(1)})"
        % (json.dumps(str(panel / "engines" / "CivSwitchLDN" / "integration.cjs")), json.dumps(str(panel)))
    )
    result = subprocess.run([node, "-e", code], text=True, capture_output=True)
    if result.returncode != 0:
        die("LDN inspection failed: " + result.stderr.strip())
    return json.loads(result.stdout.strip().splitlines()[-1])


def inject_lobby(args: argparse.Namespace, panel: Path) -> None:
    node = shutil.which("node")
    runner = panel / "engines" / "CivSwitchLDN" / "panel-runner.cjs"
    if not runner.is_file():
        die("CivSwitchLDN panel runner not found: %s" % runner)
    state = read_state(panel)
    info = inspect_ldn(panel)
    if not info.get("supported"):
        die("LDN injection is only supported on Linux")
    for key, label in (("dependenciesReady", "LDN dependencies"), ("capabilitiesReady", "raw-socket capabilities"), ("keysReady", "prod.keys")):
        if not info.get(key):
            die("%s are not ready.\n%s" % (label, info.get("capabilityCommand", "")))
    phy = args.phy or state.get("phy")
    radios = info.get("radios") or []
    if args.phy:
        if args.phy not in radios:
            die("radio %s is absent; available: %s" % (args.phy, ", ".join(radios) or "none"))
    elif phy not in radios:
        # USB Wi-Fi adapters re-enumerate as phyN after every LDN cycle. The
        # panel state keeps the old name, so follow the single available radio.
        if len(radios) == 1:
            print("[ldn] stored radio %s is gone; using %s" % (phy, radios[0]))
            phy = radios[0]
        else:
            die("stored radio %s is absent; pass --phy (available: %s)"
                % (phy, ", ".join(radios) or "none"))
    if not phy:
        die("no Wi-Fi radio configured; pass --phy (available: %s)" % ", ".join(radios))
    if not args.yes:
        print("On S2: Civ7 -> MULTIPLAYER > WIRELESS > CREATE GAME > HOST LOBBY.")
        print("Keep the lobby open. The PC Wi-Fi (%s) will be used for LDN." % phy)
        try:
            input("Press Enter to inject the loader, or Ctrl-C to stop: ")
        except EOFError:
            pass
    host_mac = args.host_mac if args.host_mac is not None else state.get("hostMac", "")
    delay = args.chat_delay if args.chat_delay is not None else state.get("chatDelay", 10)
    scale = args.handshake_scale if args.handshake_scale is not None else state.get("handshakeScale", 1)
    cmd = [node, str(runner), str(phy), str(host_mac or ""), str(delay), str(scale)]
    print("Injecting CivSwitch core.js through the Lobby (phy=%s) ..." % phy, flush=True)
    result = subprocess.run(cmd, cwd=str(panel))
    if result.returncode != 0:
        die("LDN delivery failed with exit code %d" % result.returncode)
    print("[ok] lobby delivery complete", flush=True)


def patch_bridge(kit: Path, pc_ip: str) -> tuple[str, Path]:
    source = kit / "port" / "civ_bridge.js"
    if not source.is_file():
        die("bridge not found: %s" % source)
    text = source.read_text(encoding="utf-8")
    if "PC_IP:" not in text:
        die("civ_bridge.js has no PC_IP field")
    patched, count = re.subn(r"PC_IP:\s*'[^']*'", "PC_IP: '%s'" % pc_ip, text, count=1)
    if count != 1:
        die("could not patch PC_IP in civ_bridge.js")
    handle, name = tempfile.mkstemp(prefix="civ_bridge-", suffix=".js")
    os.close(handle)
    path = Path(name)
    path.write_text(patched, encoding="utf-8")
    return patched, path


class Engine:
    def __init__(self, kit: Path, pc_ip: str, dump_firmware: bool) -> None:
        node = shutil.which("node")
        if not node:
            die("node was not found in PATH")
        run = kit / "port" / "engine" / "run.cjs"
        if not run.is_file():
            die("engine not found: %s" % run)
        self.kit = kit
        args = [node, str(run), "--rpc"]
        if dump_firmware:
            args.append("--dump-firmware")
        args.append(pc_ip)
        self.process = subprocess.Popen(
            args,
            cwd=str(kit),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.lines: list[str] = []
        self.run_folder: str | None = None
        self.listening = threading.Event()
        self.ready = threading.Event()
        self.exited = threading.Event()
        self.stalled = False
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            line = line.rstrip("\n")
            self.lines.append(line)
            print("[engine] " + line, flush=True)
            if line.startswith("Run folder: "):
                self.run_folder = line.split("Run folder: ", 1)[1].strip()
                print("[run] folder: %s" % self.run_folder, flush=True)
                print("[run] status: node %s %s status"
                      % (self.kit / "port" / "engine" / "rpc.cjs", self.run_folder), flush=True)
                print("[run] live log: tail -f %s/run.log"
                      % self.run_folder, flush=True)
                print("[run] FS log:   latest attempt listed in %s/switch2/acquisition-supervisor.json"
                      % self.run_folder, flush=True)
            if line.startswith("Waiting for "):
                self.listening.set()
            if "4/4 verified" in line:
                self.ready.set()
            if self.process.poll() is not None:
                break
        self.exited.set()

    def wait_listening(self, seconds: float) -> None:
        if not self.listening.wait(seconds):
            self.stop()
            die("engine did not start listening within %d s" % seconds)

    def wait_ready(self, seconds: float) -> bool:
        deadline = time.time() + seconds if seconds > 0 else None
        while True:
            if self.ready.wait(0.5):
                return True
            if self.stalled or self.exited.is_set() or self.process.poll() is not None:
                return False
            if deadline is not None and time.time() >= deadline:
                return False

    def stop(self) -> None:
        if self.process.poll() is None:
            try:
                self.process.send_signal(signal.SIGINT)
            except OSError:
                pass


def print_status(engine: Engine, kit: Path, console_ip: str) -> None:
    if not engine.run_folder:
        return
    run = Path(engine.run_folder)
    print()
    print("=" * 72)
    print("FS ENDPOINT IS LIVE")
    print("  run folder : %s" % run)
    print("  bridge     : %s:%d" % (console_ip, LOADER_PORT))
    print("  RPC        : node %s %s status" % (kit / "port" / "engine" / "rpc.cjs", run))
    print("  keep this process running; Ctrl-C requests release and cleanup (check the run summary)")
    print("=" * 72)
    print()
    status = run / "switch2" / "fs-execution-current.json"
    if status.is_file():
        try:
            data = json.loads(status.read_text(encoding="utf-8"))
            summary = {
                "verified": data.get("verified"),
                "restored": data.get("restored"),
                "retainedEndpoint": data.get("retainedEndpoint"),
                "cleanup": data.get("cleanup"),
            }
            print("[fs] " + json.dumps(summary, ensure_ascii=False))
        except json.JSONDecodeError:
            pass


def rpc_status(run_dir: Path) -> dict:
    connection = run_dir / "connection.json"
    try:
        port = json.loads(connection.read_text(encoding="utf-8"))["port"]
        request = urllib.request.Request(
            "http://127.0.0.1:%d/" % port,
            data=b'{"command":"status"}',
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=4) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, KeyError, ValueError, urllib.error.URLError) as exc:
        return {"error": str(exc)}


def acquisition_log(run_dir: Path) -> Path | None:
    folder = run_dir / "switch2"
    supervisor = folder / "acquisition-supervisor.json"
    if not supervisor.exists():
        return folder / "acquisition.log"  # pre-v1.0.3 kit compatibility
    if supervisor.is_symlink() or not supervisor.is_file():
        return None
    try:
        attempts = json.loads(supervisor.read_text(encoding="utf-8")).get("attempts", [])
        name = Path(attempts[-1]["log"])
        if (name.parent.resolve() == folder.resolve() and not name.is_symlink()
                and re.fullmatch(r"acquisition-\d+-\d+-[1-3]\.log", name.name)):
            return name
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        pass
    return None


class Monitor:
    """Tail the kit's run.log and live versioned acquisition attempt log."""

    def __init__(self, engine: Engine, stall_seconds: float, stall_exit: float,
                 max_runtime: float) -> None:
        self.engine = engine
        self.stall_seconds = stall_seconds
        self.stall_exit = stall_exit
        self.max_runtime = max_runtime
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.run_dir: Path | None = None
        self.profile: str | None = None
        self.profiles = 0
        self.attempt = 0
        self.acq_inode: int | None = None
        self.acq_path: Path | None = None
        self.started = time.time()
        self.last_progress = time.time()
        self.last_heartbeat = 0.0
        self.warned = False

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def _run(self) -> None:
        run_log = None
        acq_log = None
        try:
            while not self.stop_event.is_set():
                if self.run_dir is None:
                    if not self.engine.run_folder:
                        time.sleep(0.5)
                        continue
                    self.run_dir = Path(self.engine.run_folder)
                    print("[monitor] watching %s" % self.run_dir, flush=True)
                    self.last_progress = time.time()
                if run_log is None:
                    path = self.run_dir / "run.log"
                    if path.is_file():
                        run_log = path.open("r", encoding="utf-8", errors="replace")
                # v1.0.3 writes one live log per attempt; acquisition.log is
                # only a copy made AFTER an attempt fails. Follow the pinned
                # supervisor's newest log, not that stale compatibility copy.
                acq_path = acquisition_log(self.run_dir)
                try:
                    acq_stat = acq_path.stat() if acq_path is not None else None
                except OSError:
                    acq_stat = None
                if acq_stat is not None and (acq_stat.st_ino != self.acq_inode or
                                             acq_path != self.acq_path):
                    if acq_log is not None:
                        acq_log.close()
                    acq_log = acq_path.open("r", encoding="utf-8", errors="replace")
                    self.acq_inode = acq_stat.st_ino
                    self.acq_path = acq_path
                    self.attempt += 1
                    self.last_progress = time.time()
                    if self.attempt > 1:
                        print("[fs] acquisition attempt %d/3 (new source-owned log)" % self.attempt,
                              flush=True)
                moved = False
                for stream, prefix in ((run_log, "[run] "), (acq_log, "[fs] ")):
                    if stream is None:
                        continue
                    while True:
                        line = stream.readline()
                        if not line:
                            break
                        moved = True
                        text = line.rstrip("\n")
                        if not text:
                            continue
                        if prefix == "[run] ":
                            print(prefix + text, flush=True)
                        else:
                            self._acquisition_line(text)
                if moved:
                    self.last_progress = time.time()
                    self.warned = False
                now = time.time()
                if now - self.last_heartbeat >= 15:
                    self.last_heartbeat = now
                    self._heartbeat()
                quiet = now - self.last_progress
                # Acquisition deadlines must not retire a successfully held FS
                # endpoint. After 4/4, only operator release, console disconnect
                # or an actual engine exit ends the session.
                acquiring = not self.engine.ready.is_set()
                if acquiring and self.stall_seconds > 0 and quiet >= self.stall_seconds and not self.warned:
                    self.warned = True
                    print(
                        "[fs] WARNING: no acquisition progress for %d s. The kit treats a wedged "
                        "console (>3 min without progress) as a hard reset: hold power for 12 s."
                        % quiet,
                        flush=True,
                    )
                if acquiring and self.stall_exit > 0 and quiet >= self.stall_exit and not self.engine.stalled:
                    self.engine.stalled = True
                    print("[fs] stall limit reached; stopping the engine", flush=True)
                    self.engine.stop()
                if (acquiring and self.max_runtime > 0 and not self.engine.stalled
                        and now - self.started >= self.max_runtime):
                    self.engine.stalled = True
                    print("[fs] global runtime limit (%d s) reached; stopping the engine"
                          % self.max_runtime, flush=True)
                    self.engine.stop()
                time.sleep(0.4)
        finally:
            for stream in (run_log, acq_log):
                if stream is not None:
                    stream.close()

    def _acquisition_line(self, text: str) -> None:
        if not text.startswith("{"):
            return
        try:
            item = json.loads(text)
        except json.JSONDecodeError:
            return
        stage = item.get("stage")
        if stage == "prepared":
            profile = item.get("profile")
            if profile and profile != self.profile:
                self.profile = profile
                self.profiles += 1
                print("[fs] profile %s" % profile, flush=True)
        elif stage == "field-copy-retry":
            print(
                "[fs] retry %s batch=%s confirmed=%s/%s attempts=%s"
                % (item.get("name"), item.get("batch"), item.get("confirmed"),
                   item.get("required"), item.get("attempts")),
                flush=True,
            )
        elif stage == "error" or item.get("error"):
            print("[fs] ERROR " + json.dumps(item, ensure_ascii=False)[:600], flush=True)

    def _heartbeat(self) -> None:
        if self.run_dir is None:
            return
        stage = "?"
        pipeline = self.run_dir / "switch2" / "pipeline.json"
        try:
            data = json.loads(pipeline.read_text(encoding="utf-8"))
            running = [s for s in data.get("stages", []) if s.get("status") != "complete"]
            stage = running[-1]["name"] if running else "complete"
        except (OSError, ValueError, KeyError):
            pass
        status = rpc_status(self.run_dir)
        elapsed = int(time.time() - self.started)
        quiet = int(time.time() - self.last_progress)
        print(
            "[fs] heartbeat stage=%s attempt=%d elapsed=%ds profiles=%d rpc_calls=%s idle=%ds"
            % (stage, max(self.attempt, 1), elapsed, self.profiles,
               status.get("calls", "?"), quiet),
            flush=True,
        )


def print_summary(run_folder: str | None) -> None:
    if not run_folder:
        return
    run = Path(run_folder)
    print()
    print("=" * 72)
    print("RUN SUMMARY: %s" % run)
    print("=" * 72)
    result_path = run / "result.json"
    if result_path.is_file():
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
            print("verified: %s" % result.get("verified"))
            if result.get("error"):
                print("error   : %s" % result["error"])
            if result.get("rpc"):
                print("rpc     : %s" % json.dumps(result["rpc"], ensure_ascii=False))
        except ValueError:
            print("result.json is not valid JSON")
    else:
        print("result.json: missing (the run is still active or was interrupted)")
    pipeline = run / "switch2" / "pipeline.json"
    if pipeline.is_file():
        try:
            data = json.loads(pipeline.read_text(encoding="utf-8"))
            for stage in data.get("stages", []):
                print("  %-8s %s" % (stage.get("status", "?"), stage.get("name", "?")))
                detail = stage.get("result")
                if isinstance(detail, dict) and detail.get("error"):
                    print("           error: %s" % str(detail["error"]).splitlines()[0])
        except ValueError:
            print("pipeline.json is not valid JSON")
    fs_path = run / "switch2" / "fs-execution-current.json"
    if fs_path.is_file():
        try:
            data = json.loads(fs_path.read_text(encoding="utf-8"))
            print("fs      : verified=%s retained=%s cleanup=%s"
                  % (data.get("verified"),
                     (data.get("retainedEndpoint") or {}).get("ready"),
                     (data.get("cleanup") or {}).get("deferred")))
        except ValueError:
            pass
    acquisition = acquisition_log(run)
    if acquisition is not None and acquisition.is_file():
        errors = []
        retries = []
        with acquisition.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if '"stage":"field-copy-retry"' in line:
                    retries.append(line.strip())
                if '"stage":"error"' in line or '"error":' in line:
                    errors.append(line.strip())
        if retries:
            print("last retries:")
            for line in retries[-3:]:
                print("  " + line[:400])
        if errors:
            print("errors:")
            for line in errors[-5:]:
                print("  " + line[:600])
        print("full FS log: %s" % acquisition)
    print("=" * 72)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="IZCIVSwitch.py",
        description="Load the CivSwitch bridge from the Civ7 Lobby and hold the Stage 2 FS RPC session.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python3 IZCIVSwitch.py --lobby --yes\n"
            "  python3 IZCIVSwitch.py --no-lobby --console-ip <S2-IP>\n"
            "  python3 IZCIVSwitch.py --lobby --dump-firmware --yes\n"
        ),
    )
    parser.add_argument("--lobby", dest="lobby", action="store_true", default=True,
                        help="inject the loader through the Civ7 Host Lobby (default)")
    parser.add_argument("--no-lobby", dest="lobby", action="store_false",
                        help="loader is already armed; skip LDN injection")
    parser.add_argument("--console-ip", default=None, help="Switch 2 LAN address")
    parser.add_argument("--pc-ip", default=None, help="this computer's address reachable by the console")
    parser.add_argument("--phy", default=None, help="Wi-Fi phy for LDN (default: panel state)")
    parser.add_argument("--host-mac", default=None, help="LDN host MAC (default: panel state)")
    parser.add_argument("--chat-delay", type=int, default=None, help="LDN chat delay (default: panel state)")
    parser.add_argument("--handshake-scale", type=float, default=None, help="LDN handshake scale (default: panel state)")
    parser.add_argument("--dump-firmware", action="store_true", help="also dump system CodeFS")
    parser.add_argument("--inject-only", action="store_true",
                        help="inject through the Lobby and stop once the loader answers (for install.py)")
    parser.add_argument("--inspect", metavar="RUN", help="print a summary of an existing run folder and exit")
    parser.add_argument("--stall-seconds", type=float, default=180.0,
                        help="warn when the current acquisition attempt log stops growing (0 disables)")
    parser.add_argument("--stall-exit", type=float, default=0.0,
                        help="stop the engine after this much silence (0 keeps it running)")
    parser.add_argument("--max-runtime", type=float, default=720.0,
                        help="acquisition limit in seconds; default 720; disabled after FS 4/4; 0 disables")
    parser.add_argument("--wait", type=float, default=240.0, help="seconds to wait for the loader")
    parser.add_argument("--ready-timeout", type=float, default=0.0, help="seconds to wait for 4/4 verified (0 = only --max-runtime)")
    parser.add_argument("--kit", type=Path, default=DEFAULT_KIT)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--yes", action="store_true", help="do not ask before LDN injection")
    args = parser.parse_args(argv)

    if args.inspect:
        print_summary(args.inspect)
        return 0

    kit = args.kit.expanduser().resolve()
    panel = args.panel.expanduser().resolve()
    state = read_state(panel)
    if args.console_ip:
        hosts = [args.console_ip]
    else:
        primary = state.get("host") or "10.42.0.20"
        hosts = [primary] + [address for address in neighbor_ipv4() if address != primary]
    console_ip = hosts[0]
    if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", console_ip):
        die("invalid --console-ip: %s" % console_ip)
    pc_ip = args.pc_ip or local_ip_towards(console_ip)
    if not pc_ip:
        die("cannot determine the PC address towards %s; pass --pc-ip" % console_ip)
    print("console: %s   PC: %s" % (console_ip, pc_ip))

    if not (kit / "port" / "engine" / "run.cjs").is_file():
        die("civswitch-kit not found at %s (pass --kit)" % kit)

    if args.lobby:
        inject_lobby(args, panel)
        wait_local_address(pc_ip, 90)
    else:
        print("Skipping Lobby injection (--no-lobby).")

    console_ip = wait_loader(hosts, LOADER_PORT, args.wait)
    if console_ip != hosts[0]:
        print("[net] console answered at %s (not %s)" % (console_ip, hosts[0]), flush=True)
    if args.inject_only:
        print("[ok] loader is armed at %s:%d" % (console_ip, LOADER_PORT))
        print("One-time trigger install:")
        print("  python3 kit/save-tools/restore_save.py kit/save-tools/trigger-recreate %s" % console_ip)
        print("Then hard-power-cycle S2 and use: Load Game -> XSTRIG -> "
              "python3 IZCIVSwitch.py --no-lobby")
        print("Optional launcher install: python3 izlauncher/install.py --ip %s" % console_ip)
        return 0

    bridge_code, bridge_path = patch_bridge(kit, pc_ip)
    try:
        print("Starting engine (held RPC mode) ...", flush=True)
        engine = Engine(kit, pc_ip, args.dump_firmware)
        monitor = Monitor(engine, args.stall_seconds, args.stall_exit, args.max_runtime)
        monitor.start()
        try:
            engine.wait_listening(60)
            print("[ok] engine is listening on %s:%d" % (pc_ip, ENGINE_PORT), flush=True)
            print("Sending civ_bridge.js to the console ...", flush=True)

            bridge_output: list[str] = []
            bridge_error: list[BaseException] = []

            def bridge_worker() -> None:
                try:
                    out = send_script(console_ip, LOADER_PORT, bridge_code, timeout=86400)
                    bridge_output.append(out)
                    for line in out.splitlines():
                        if line.strip():
                            print("[console] " + line, flush=True)
                except BaseException as exc:  # noqa: BLE001 - reported below
                    bridge_error.append(exc)

            thread = threading.Thread(target=bridge_worker, daemon=True)
            thread.start()

            ready = engine.wait_ready(args.ready_timeout)
            if ready:
                print_status(engine, kit, console_ip)
                print("[ok] held RPC session is live; watching the engine. Ctrl-C to stop.", flush=True)
                while engine.process.poll() is None and not engine.stalled:
                    time.sleep(0.5)
                if engine.stalled:
                    print("[fs] stopped on stall limit", flush=True)
                    engine.process.wait(timeout=60)
            else:
                print("[engine] the held session was not reached", flush=True)
                engine.stop()
                engine.process.wait(timeout=60)
            if engine.stalled:
                return 2
            return engine.process.returncode or 0
        finally:
            monitor.stop()
            engine.stop()
            try:
                engine.process.wait(timeout=90)
            except subprocess.TimeoutExpired:
                engine.process.kill()
            bridge_path.unlink(missing_ok=True)
            print_summary(engine.run_folder)
    except KeyboardInterrupt:
        print("\ninterrupted; releasing the console ...", file=sys.stderr)
        return 130


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
