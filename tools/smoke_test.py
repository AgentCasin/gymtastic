from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from urllib import request

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import simulate_device


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_server(base_url: str, timeout_seconds: float = 10.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with request.urlopen(f"{base_url}/", timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("Server did not become ready in time")


def get_json(url: str) -> dict:
    with request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    port = free_port()
    token = "smoke-token"
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "smoke_gymtastic.db")
        env = os.environ.copy()
        env["GYMTASTIC_HOST"] = "127.0.0.1"
        env["GYMTASTIC_PORT"] = str(port)
        env["GYMTASTIC_DEVICE_TOKEN"] = token
        env["GYMTASTIC_DB_PATH"] = db_path

        server = subprocess.Popen(
            ["python", "main.py"],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            base_url = f"http://127.0.0.1:{port}"
            wait_for_server(base_url)

            args = SimpleNamespace(
                base_url=base_url,
                device_token=token,
                device_id="ESP32-GATE-01",
                device_name="Smoke Reader",
                location="Smoke Bench",
                reader_mode="entry",
                relay_seconds=4,
            )

            heartbeat = simulate_device.send_heartbeat(args)
            assert heartbeat.get("ok") is True, heartbeat

            scan = simulate_device.send_scan(args, "RFID-DEMO-001", "auto")
            assert scan.get("authorized") is True, scan
            queued = scan.get("device_command")
            assert queued and queued.get("command_type") == "pulse_relay", scan

            poll = simulate_device.poll_command(args)
            assert poll.get("command", {}).get("id") is not None, poll

            ack = simulate_device.ack_command(args, int(poll["command"]["id"]))
            assert ack.get("command", {}).get("status") == "acknowledged", ack

            event = simulate_device.report_event(args, "smoke_test", "info", "Smoke test device event")
            assert event.get("ok") is True, event

            sessions = get_json(f"{base_url}/api/sessions")
            assert sessions.get("occupancy") == 1, sessions

            commands = get_json(f"{base_url}/api/commands")
            assert commands["commands"][0]["status"] == "acknowledged", commands

            device_events = get_json(f"{base_url}/api/device-events")
            assert device_events["device_events"][0]["event_type"] == "smoke_test", device_events

            print("Smoke test passed")
            return 0
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
