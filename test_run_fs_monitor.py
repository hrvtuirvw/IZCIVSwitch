"""Host-only lifetime checks for CivSwitch's PC monitor (no console/radio)."""
# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2026 hrvtuirvw.
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("izciv_run_fs", Path(__file__).with_name("run-fs.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
INSTALLER_SPEC = importlib.util.spec_from_file_location("izciv_installer", Path(__file__).with_name("pc-install-trigger.py"))
INSTALLER = importlib.util.module_from_spec(INSTALLER_SPEC)
INSTALLER_SPEC.loader.exec_module(INSTALLER)


class FakeEngine:
    def __init__(self, run_folder):
        self.run_folder = run_folder
        self.ready = threading.Event()
        self.stalled = False
        self.stops = 0

    def stop(self):
        self.stops += 1


class MonitorLifetimeTests(unittest.TestCase):
    def test_public_help_names_the_public_entrypoint(self):
        help_text = subprocess.check_output([sys.executable, str(Path(__file__).with_name("IZCIVSwitch.py")), "--help"], text=True)
        self.assertIn("python3 IZCIVSwitch.py --lobby --yes", help_text)
        self.assertNotIn("python3 run-fs.py", help_text)

    def test_installer_success_shows_supported_no_lobby_entrypoint(self):
        output = io.StringIO()
        with redirect_stdout(output):
            INSTALLER.show_installed_next_steps("10.42.0.20")
        text = output.getvalue()
        self.assertIn("python3 IZCIVSwitch.py --no-lobby --console-ip 10.42.0.20", text)
        self.assertIn("Ctrl-C releases it", text)
        self.assertNotIn("sed -i", text)
        self.assertNotIn("save-tools/send_js.py", text)

    def test_supervisor_log_path_must_be_inside_run_and_not_a_symlink(self):
        with tempfile.TemporaryDirectory(prefix="civswitch-monitor-") as folder:
            root = Path(folder) / "switch2"
            root.mkdir()
            log = root / "acquisition-123-456-1.log"
            log.write_text("ok")
            supervisor = root / "acquisition-supervisor.json"
            supervisor.write_text(json.dumps({"attempts": [{"log": str(log)}]}))
            self.assertEqual(MODULE.acquisition_log(Path(folder)), log)
            supervisor.write_text(json.dumps({"attempts": [{"log": "/tmp/acquisition-123-456-1.log"}]}))
            self.assertIsNone(MODULE.acquisition_log(Path(folder)))
            log.unlink()
            log.symlink_to("/etc/passwd")
            supervisor.write_text(json.dumps({"attempts": [{"log": str(log)}]}))
            self.assertIsNone(MODULE.acquisition_log(Path(folder)))

    def test_follows_live_v103_logs_not_stale_compatibility_copy(self):
        with tempfile.TemporaryDirectory(prefix="civswitch-monitor-") as folder:
            root = Path(folder) / "switch2"
            root.mkdir()
            engine = FakeEngine(folder)
            monitor = MODULE.Monitor(engine, stall_seconds=0, stall_exit=0, max_runtime=0)
            old = root / "acquisition.log"
            old.write_text('{"stage":"prepared","profile":"stale"}\n')
            first = root / "acquisition-123-456-1.log"
            first.write_text('{"stage":"prepared","profile":"current-one"}\n')
            supervisor = root / "acquisition-supervisor.json"
            supervisor.write_text(json.dumps({"attempts": [{"log": str(first)}]}))
            with patch.object(monitor, "_heartbeat"):
                monitor.start()
                try:
                    time.sleep(0.7)
                    self.assertEqual(monitor.profile, "current-one")
                    self.assertEqual(monitor.attempt, 1)
                    second = root / "acquisition-123-456-2.log"
                    second.write_text('{"stage":"prepared","profile":"current-two"}\n')
                    supervisor.write_text(json.dumps({"attempts": [{"log": str(first)}, {"log": str(second)}]}))
                    time.sleep(0.7)
                    self.assertEqual(monitor.profile, "current-two")
                    self.assertEqual(monitor.attempt, 2)
                    self.assertNotEqual(monitor.profile, "stale")
                finally:
                    monitor.stop()
                    monitor.thread.join(timeout=3)
            self.assertFalse(monitor.thread.is_alive())

    def exercise(self, *, ready, max_runtime, stall_exit):
        with tempfile.TemporaryDirectory(prefix="civswitch-monitor-") as folder:
            engine = FakeEngine(folder)
            if ready:
                engine.ready.set()
            monitor = MODULE.Monitor(engine, stall_seconds=0.1, stall_exit=stall_exit,
                                     max_runtime=max_runtime)
            monitor.started = time.time() - 20
            monitor.last_progress = time.time() - 20
            with patch.object(monitor, "_heartbeat"):
                monitor.start()
                try:
                    time.sleep(0.6)
                finally:
                    monitor.stop()
                    monitor.thread.join(timeout=3)
            self.assertFalse(monitor.thread.is_alive())
            return engine

    def test_verified_held_fs_ignores_expired_acquisition_timer_and_stall(self):
        engine = self.exercise(ready=True, max_runtime=1, stall_exit=1)
        self.assertEqual(engine.stops, 0)
        self.assertFalse(engine.stalled)

    def test_unverified_acquisition_still_stops_at_runtime_limit(self):
        engine = self.exercise(ready=False, max_runtime=1, stall_exit=0)
        self.assertEqual(engine.stops, 1)
        self.assertTrue(engine.stalled)

    def test_unverified_acquisition_still_stops_at_stall_limit(self):
        engine = self.exercise(ready=False, max_runtime=0, stall_exit=0.1)
        self.assertEqual(engine.stops, 1)
        self.assertTrue(engine.stalled)


if __name__ == "__main__":
    unittest.main()
