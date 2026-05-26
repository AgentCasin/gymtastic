from __future__ import annotations

import argparse
import json
import time
from typing import Any
from urllib import error, request


def build_headers(device_token: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if device_token:
        headers["X-Device-Token"] = device_token
    return headers


def post_json(base_url: str, path: str, payload: dict[str, Any], device_token: str) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers=build_headers(device_token),
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"ok": False, "error": raw or f"HTTP {exc.code}"}
        payload["http_status"] = exc.code
        return payload


def send_heartbeat(args: argparse.Namespace) -> dict[str, Any]:
    payload = {
        "esp32_id": args.device_id,
        "name": args.device_name,
        "location": args.location,
        "reader_mode": args.reader_mode,
        "relay_seconds": args.relay_seconds,
        "status": "online",
    }
    return post_json(args.base_url, "/api/esp32/heartbeat", payload, args.device_token)


def send_scan(args: argparse.Namespace, rfid_uid: str, event_type: str) -> dict[str, Any]:
    payload = {
        "rfid_uid": rfid_uid,
        "esp32_id": args.device_id,
        "event_type": event_type,
    }
    return post_json(args.base_url, "/api/rfid/scan", payload, args.device_token)


def poll_command(args: argparse.Namespace) -> dict[str, Any]:
    payload = {"esp32_id": args.device_id}
    return post_json(args.base_url, "/api/device/poll", payload, args.device_token)


def ack_command(args: argparse.Namespace, command_id: int) -> dict[str, Any]:
    payload = {"command_id": command_id}
    return post_json(args.base_url, "/api/device/ack", payload, args.device_token)


def report_event(args: argparse.Namespace, event_type: str, level: str, message: str) -> dict[str, Any]:
    payload = {
        "esp32_id": args.device_id,
        "event_type": event_type,
        "level": level,
        "message": message,
    }
    return post_json(args.base_url, "/api/device/event", payload, args.device_token)


def print_json(label: str, payload: dict[str, Any]) -> None:
    print(f"{label}:")
    print(json.dumps(payload, indent=2, sort_keys=True))


def command_demo(args: argparse.Namespace) -> int:
    heartbeat = send_heartbeat(args)
    print_json("heartbeat", heartbeat)
    if not heartbeat.get("ok"):
        return 1

    scan = send_scan(args, args.rfid_uid, args.event_type)
    print_json("scan", scan)

    command = poll_command(args)
    print_json("poll", command)

    queued = command.get("command")
    if queued and isinstance(queued, dict) and queued.get("id") is not None and args.auto_ack:
        ack = ack_command(args, int(queued["id"]))
        print_json("ack", ack)

    return 0


def command_poll_loop(args: argparse.Namespace) -> int:
    heartbeat = send_heartbeat(args)
    print_json("heartbeat", heartbeat)
    if not heartbeat.get("ok"):
        return 1

    for _ in range(args.poll_count):
        command = poll_command(args)
        print_json("poll", command)
        queued = command.get("command")
        if queued and isinstance(queued, dict) and queued.get("id") is not None and args.auto_ack:
            ack = ack_command(args, int(queued["id"]))
            print_json("ack", ack)
        time.sleep(args.poll_interval)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simulate an ESP32 RFID reader against Gymtastic.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--device-token", default="")
    parser.add_argument("--device-id", default="ESP32-GATE-01")
    parser.add_argument("--device-name", default="Simulated Reader")
    parser.add_argument("--location", default="Local Test Bench")
    parser.add_argument("--reader-mode", default="entry", choices=["entry", "exit", "both"])
    parser.add_argument("--relay-seconds", type=int, default=5)

    subparsers = parser.add_subparsers(dest="command", required=True)

    heartbeat = subparsers.add_parser("heartbeat")
    heartbeat.set_defaults(handler=lambda args: print_json("heartbeat", send_heartbeat(args)) or 0)

    scan = subparsers.add_parser("scan")
    scan.add_argument("--rfid-uid", required=True)
    scan.add_argument("--event-type", default="auto")
    scan.set_defaults(
        handler=lambda args: print_json("scan", send_scan(args, args.rfid_uid, args.event_type)) or 0
    )

    poll = subparsers.add_parser("poll")
    poll.add_argument("--auto-ack", action="store_true")
    poll.set_defaults(
        handler=lambda args: print_json("poll", poll_command(args)) or 0
    )

    ack = subparsers.add_parser("ack")
    ack.add_argument("--command-id", type=int, required=True)
    ack.set_defaults(
        handler=lambda args: print_json("ack", ack_command(args, args.command_id)) or 0
    )

    event = subparsers.add_parser("event")
    event.add_argument("--event-type", default="device_event")
    event.add_argument("--level", default="info")
    event.add_argument("--message", required=True)
    event.set_defaults(
        handler=lambda args: print_json(
            "event",
            report_event(args, args.event_type, args.level, args.message),
        ) or 0
    )

    demo = subparsers.add_parser("demo")
    demo.add_argument("--rfid-uid", default="RFID-DEMO-001")
    demo.add_argument("--event-type", default="auto")
    demo.add_argument("--auto-ack", action="store_true")
    demo.set_defaults(handler=command_demo)

    loop = subparsers.add_parser("poll-loop")
    loop.add_argument("--poll-count", type=int, default=5)
    loop.add_argument("--poll-interval", type=float, default=2.0)
    loop.add_argument("--auto-ack", action="store_true")
    loop.set_defaults(handler=command_poll_loop)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.handler(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
