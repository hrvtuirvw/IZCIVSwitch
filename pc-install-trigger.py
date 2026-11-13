#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PC-side replacement for Switch 1 + civswitch-ldn-nx.nro.

Uses the already-installed CivSwitchLDN panel implementation on this PC
(`iz2s-panel/iz2s-platform-run22/engines/CivSwitchLDN`) to inject the stock
`payloads/core.js` into a Civ7 Host Lobby, then runs the original kit's
`save-tools/restore_save.py` to write `XSTRIG.Civ7Save`.

No Switch 1 is needed. The kit itself is not modified.

Typical use:
  1. S2: Civ7 -> MULTIPLAYER > WIRELESS > CREATE GAME > HOST LOBBY
  2. PC: python3 pc-install-trigger.py --yes
  3. Hard power-cycle S2 (12 s)
  4. Civ7 -> Load Game -> XSTRIG.Civ7Save -> Awaiting payload
  5. PC: python3 IZCIVSwitch.py --no-lobby
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_PANEL = HERE / "panel"
DEFAULT_KIT = HERE / "kit"
LOADER_PORT = 9026


def die(message: str) -> "NoReturn":
    print("\nFAILED: " + message, file=sys.stderr)
    raise SystemExit(1)


def read_state(panel: Path) -> dict:
    try:
        return json.loads((panel / "data" / "state" / "civswitchldn.json").read_text(encoding="utf-8"))
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
        die("node not found in PATH")
    code = (
        "require(%s).inspect(%s).then(x=>{console.log(JSON.stringify(x));"
        "process.exit(0)}).catch(e=>{console.error(e.message);process.exit(1)})"
        % (json.dumps(str(panel / "engines" / "CivSwitchLDN" / "integration.cjs")),
           json.dumps(str(panel)))
    )
    result = subprocess.run([node, "-e", code], text=True, capture_output=True)
    if result.returncode != 0:
        die("LDN inspection failed: " + result.stderr.strip())
    return json.loads(result.stdout.strip().splitlines()[-1])


def neighbor_ipv4() -> list[str]:
    try:
        out = subprocess.run(["ip", "-4", "neigh", "show"], text=True, capture_output=True).stdout
    except OSError:
        return []
    return [line.split()[0] for line in out.splitlines()
            if line.split() and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", line.split()[0])]


def loader_ready(host: str) -> bool:
    nonce = "PCLDN_" + uuid.uuid4().hex
    try:
        with socket.create_connection((host, LOADER_PORT), timeout=3) as sock:
            sock.sendall(("log('%s')" % nonce).encode())
            sock.shutdown(socket.SHUT_WR)
            sock.settimeout(8)
            data = b""
            try:
                while True:
                    block = sock.recv(4096)
                    if not block:
                        break
                    data += block
            except socket.timeout:
                pass
        return nonce in data.decode("utf-8", "replace")
    except OSError:
        return False


def wait_loader(hosts: list[str], seconds: float) -> str:
    print("Waiting for the Remote JS Loader on port %d ..." % LOADER_PORT, flush=True)
    deadline = time.time() + seconds
    while time.time() < deadline:
        for host in hosts:
            if loader_ready(host):
                print("[ok] loader online at %s:%d" % (host, LOADER_PORT), flush=True)
                return host
        print("  ... no loader yet", flush=True)
        time.sleep(3)
    die("loader did not answer. Check that S2 is in Civ7 Host Lobby and keep it open.")


def show_installed_next_steps(console_ip: str) -> None:
    """Point a successful install at the supported wrapper, not manual kit commands."""
    print()
    print("=" * 72)
    print("XSTRIG TRIGGER INSTALLED")
    print("=" * 72)
    print("1. Hard power-cycle S2: hold power for 12 seconds, wait 5 s, boot.")
    print("2. Civ7 -> Load Game -> XSTRIG.Civ7Save.")
    print("3. Wait for: Awaiting payload at %s:%d" % (console_ip, LOADER_PORT))
    print("4. From this extracted IZCIVSwitch folder, run:")
    print("     python3 IZCIVSwitch.py --no-lobby --console-ip %s" % console_ip)
    print("Keep the launcher open to hold FS; Ctrl-C releases it.")
    print("Switch 1 and the Lobby are no longer needed after this.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install XSTRIG.Civ7Save through the PC's LDN adapter (no Switch 1).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python3 pc-install-trigger.py --check\n"
            "  python3 pc-install-trigger.py --yes\n"
            "  python3 pc-install-trigger.py --yes --inject-only\n"
        ),
    )
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--kit", type=Path, default=DEFAULT_KIT)
    parser.add_argument("--console-ip", default=None)
    parser.add_argument("--phy", default=None)
    parser.add_argument("--host-mac", default=None)
    parser.add_argument("--chat-delay", type=int, default=None)
    parser.add_argument("--handshake-scale", type=float, default=None)
    parser.add_argument("--wait", type=float, default=240.0)
    parser.add_argument("--check", action="store_true", help="validate the LDN environment and exit")
    parser.add_argument("--inject-only", action="store_true", help="stop after the loader answers")
    parser.add_argument("--yes", action="store_true", help="do not ask before LDN injection")
    args = parser.parse_args(argv)

    panel = args.panel.expanduser().resolve()
    kit = args.kit.expanduser().resolve()
    restore = kit / "save-tools" / "restore_save.py"
    trigger = kit / "save-tools" / "trigger-recreate"
    if not restore.is_file() or not trigger.is_dir():
        die("original kit not found at %s (pass --kit)" % kit)

    state = read_state(panel)
    info = inspect_ldn(panel)
    radios = info.get("radios") or []
    phy = args.phy or state.get("phy")
    if args.phy:
        if args.phy not in radios:
            die("radio %s is absent; available: %s" % (args.phy, ", ".join(radios) or "none"))
    elif phy not in radios:
        if len(radios) == 1:
            print("[ldn] stored radio %s is gone; using %s" % (phy, radios[0]))
            phy = radios[0]
        else:
            die("stored radio %s is absent; pass --phy (available: %s)"
                % (phy, ", ".join(radios) or "none"))

    primary = args.console_ip or state.get("host") or "10.42.0.20"
    hosts = [primary] + [address for address in neighbor_ipv4() if address != primary]

    print("panel : %s" % panel)
    print("kit   : %s" % kit)
    print("radio : %s   console candidates: %s" % (phy, ", ".join(hosts)))
    for key, label in (("supported", "platform"), ("dependenciesReady", "LDN dependencies"),
                       ("capabilitiesReady", "raw-socket capabilities"), ("keysReady", "prod.keys")):
        if not info.get(key):
            die("%s not ready.\n%s" % (label, info.get("capabilityCommand", "")))
    print("[ok] LDN environment is ready")

    if args.check:
        return 0

    if not args.yes:
        print("On S2: Civ7 -> MULTIPLAYER > WIRELESS > CREATE GAME > HOST LOBBY.")
        print("Keep the lobby open. The PC Wi-Fi (%s) will be used for LDN." % phy)
        try:
            input("Press Enter to inject core.js, or Ctrl-C to stop: ")
        except EOFError:
            pass

    host_mac = args.host_mac if args.host_mac is not None else state.get("hostMac", "")
    delay = args.chat_delay if args.chat_delay is not None else state.get("chatDelay", 10)
    scale = args.handshake_scale if args.handshake_scale is not None else state.get("handshakeScale", 1)
    runner = panel / "engines" / "CivSwitchLDN" / "panel-runner.cjs"
    cmd = [shutil.which("node") or "node", str(runner), str(phy),
           str(host_mac or ""), str(delay), str(scale)]
    print("Injecting the original CivSwitch core.js through the Lobby ...", flush=True)
    result = subprocess.run(cmd, cwd=str(panel))
    if result.returncode != 0:
        die("LDN delivery failed with exit code %d" % result.returncode)
    print("[ok] lobby delivery complete", flush=True)

    console_ip = wait_loader(hosts, args.wait)
    if args.inject_only:
        print()
        print("Loader is armed at %s:%d" % (console_ip, LOADER_PORT))
        print("Original kit restore command:")
        print("  cd %s" % kit)
        print("  python3 save-tools/restore_save.py save-tools/trigger-recreate %s" % console_ip)
        return 0

    print()
    print("Writing XSTRIG.Civ7Save with the original kit tool ...")
    result = subprocess.run(
        [sys.executable, "-u", str(restore), str(trigger), console_ip],
        cwd=str(kit),
    )
    if result.returncode != 0:
        die("restore_save.py failed with exit code %d" % result.returncode)
    show_installed_next_steps(console_ip)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(130)
