from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("GYMTASTIC_DB_PATH", str(BASE_DIR / "gymtastic.db")))
DEVICE_OFFLINE_AFTER_SECONDS = int(os.getenv("GYMTASTIC_DEVICE_OFFLINE_AFTER_SECONDS", "90"))
DEVICE_COMMAND_ACK_TIMEOUT_SECONDS = int(os.getenv("GYMTASTIC_DEVICE_COMMAND_ACK_TIMEOUT_SECONDS", "15"))
RFID_DUPLICATE_WINDOW_SECONDS = int(os.getenv("GYMTASTIC_RFID_DUPLICATE_WINDOW_SECONDS", "3"))


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = db_connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT,
                rfid_uid TEXT NOT NULL UNIQUE,
                membership_status TEXT NOT NULL DEFAULT 'active',
                membership_start_date TEXT,
                membership_end_date TEXT,
                created_at TEXT NOT NULL,
                last_checkin_at TEXT
            );

            CREATE TABLE IF NOT EXISTS equipment (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                esp32_id TEXT NOT NULL UNIQUE,
                location TEXT,
                reader_mode TEXT NOT NULL DEFAULT 'entry',
                relay_seconds INTEGER NOT NULL DEFAULT 5,
                status TEXT NOT NULL DEFAULT 'offline',
                last_seen_at TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS access_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id INTEGER,
                equipment_id INTEGER,
                rfid_uid TEXT NOT NULL,
                esp32_id TEXT,
                event_type TEXT NOT NULL,
                decision TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(member_id) REFERENCES members(id),
                FOREIGN KEY(equipment_id) REFERENCES equipment(id)
            );

            CREATE TABLE IF NOT EXISTS gym_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id INTEGER NOT NULL,
                rfid_uid TEXT NOT NULL,
                entry_equipment_id INTEGER,
                exit_equipment_id INTEGER,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                FOREIGN KEY(member_id) REFERENCES members(id),
                FOREIGN KEY(entry_equipment_id) REFERENCES equipment(id),
                FOREIGN KEY(exit_equipment_id) REFERENCES equipment(id)
            );

            CREATE TABLE IF NOT EXISTS device_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipment_id INTEGER NOT NULL,
                esp32_id TEXT NOT NULL,
                command_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                retry_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                delivered_at TEXT,
                acknowledged_at TEXT,
                FOREIGN KEY(equipment_id) REFERENCES equipment(id)
            );

            CREATE TABLE IF NOT EXISTS pending_rfid_scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rfid_uid TEXT NOT NULL UNIQUE,
                esp32_id TEXT,
                equipment_id INTEGER,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                scan_count INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'pending',
                FOREIGN KEY(equipment_id) REFERENCES equipment(id)
            );

            CREATE TABLE IF NOT EXISTS device_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipment_id INTEGER,
                esp32_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(equipment_id) REFERENCES equipment(id)
            );
            """
        )
        member_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(members)").fetchall()
        }
        equipment_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(equipment)").fetchall()
        }
        if "membership_start_date" not in member_columns:
            conn.execute("ALTER TABLE members ADD COLUMN membership_start_date TEXT")
        if "membership_end_date" not in member_columns:
            conn.execute("ALTER TABLE members ADD COLUMN membership_end_date TEXT")
        if "reader_mode" not in equipment_columns:
            conn.execute("ALTER TABLE equipment ADD COLUMN reader_mode TEXT NOT NULL DEFAULT 'entry'")
        if "relay_seconds" not in equipment_columns:
            conn.execute("ALTER TABLE equipment ADD COLUMN relay_seconds INTEGER NOT NULL DEFAULT 5")
        command_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(device_commands)").fetchall()
        }
        if "retry_count" not in command_columns:
            conn.execute("ALTER TABLE device_commands ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    finally:
        conn.close()


def seed_defaults() -> None:
    conn = db_connection()
    try:
        member_count = conn.execute("SELECT COUNT(*) FROM members").fetchone()[0]
        equipment_count = conn.execute("SELECT COUNT(*) FROM equipment").fetchone()[0]
        default_start = utc_today()
        default_end = (datetime.now(timezone.utc).date() + timedelta(days=30)).isoformat()
        if member_count == 0:
            conn.execute(
                """
                INSERT INTO members (
                    name, email, rfid_uid, membership_status, membership_start_date, membership_end_date, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Demo Member",
                    "demo@gym.local",
                    "RFID-DEMO-001",
                    "active",
                    default_start,
                    default_end,
                    utc_now(),
                ),
            )
        if equipment_count == 0:
            conn.execute(
                """
                INSERT INTO equipment (
                    name, esp32_id, location, reader_mode, relay_seconds, status, last_seen_at, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("Front Gate Reader", "ESP32-GATE-01", "Entrance", "entry", 5, "online", utc_now(), utc_now()),
            )
        conn.commit()
    finally:
        conn.close()


def fetch_all(query: str, params: Iterable[object] = ()) -> list[sqlite3.Row]:
    conn = db_connection()
    try:
        return conn.execute(query, tuple(params)).fetchall()
    finally:
        conn.close()


def fetch_one(query: str, params: Iterable[object] = ()) -> sqlite3.Row | None:
    conn = db_connection()
    try:
        return conn.execute(query, tuple(params)).fetchone()
    finally:
        conn.close()


def execute(query: str, params: Iterable[object] = ()) -> None:
    conn = db_connection()
    try:
        conn.execute(query, tuple(params))
        conn.commit()
    finally:
        conn.close()


def add_member(
    name: str,
    email: str,
    rfid_uid: str,
    membership_status: str,
    membership_start_date: str,
    membership_end_date: str,
) -> None:
    execute(
        """
        INSERT INTO members (
            name, email, rfid_uid, membership_status, membership_start_date, membership_end_date, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            email,
            rfid_uid,
            membership_status,
            membership_start_date or None,
            membership_end_date or None,
            utc_now(),
        ),
    )


def add_member_from_pending_scan(
    pending_scan_id: int,
    name: str,
    email: str,
    membership_status: str,
    membership_start_date: str,
    membership_end_date: str,
) -> None:
    pending_scan = fetch_one(
        "SELECT * FROM pending_rfid_scans WHERE id = ? AND status = 'pending'",
        (pending_scan_id,),
    )
    if pending_scan is None:
        raise ValueError("pending RFID scan not found")

    add_member(
        name,
        email,
        pending_scan["rfid_uid"],
        membership_status,
        membership_start_date,
        membership_end_date,
    )
    execute(
        "UPDATE pending_rfid_scans SET status = 'enrolled', last_seen_at = ? WHERE id = ?",
        (utc_now(), pending_scan_id),
    )


def add_equipment(
    name: str,
    esp32_id: str,
    location: str,
    reader_mode: str,
    relay_seconds: int,
    status: str,
) -> None:
    execute(
        """
        INSERT INTO equipment (
            name, esp32_id, location, reader_mode, relay_seconds, status, last_seen_at, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (name, esp32_id, location, reader_mode, relay_seconds, status, utc_now(), utc_now()),
    )


@dataclass
class ApiResponse:
    status: str
    body: bytes
    content_type: str = "application/json; charset=utf-8"


def parse_json(environ: dict) -> dict:
    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError:
        length = 0
    raw = environ["wsgi.input"].read(length) if length else b"{}"
    return json.loads(raw or b"{}")


def configured_device_token() -> str:
    return os.getenv("GYMTASTIC_DEVICE_TOKEN", "").strip()


def get_header(environ: dict, header_name: str) -> str:
    key = "HTTP_" + header_name.upper().replace("-", "_")
    return str(environ.get(key, "")).strip()


def verify_device_request(environ: dict) -> ApiResponse | None:
    expected_token = configured_device_token()
    if not expected_token:
        return None

    provided_token = get_header(environ, "X-Device-Token")
    if provided_token == expected_token:
        return None

    return json_response(401, {"ok": False, "error": "invalid device token"})


def parse_form(environ: dict) -> dict[str, str]:
    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError:
        length = 0
    raw = environ["wsgi.input"].read(length).decode("utf-8") if length else ""
    parsed = parse_qs(raw)
    return {key: values[0].strip() for key, values in parsed.items()}


def redirect(start_response, location: str) -> list[bytes]:
    start_response("303 See Other", [("Location", location)])
    return [b""]


def json_response(status_code: int, payload: dict) -> ApiResponse:
    phrase = {
        200: "OK",
        201: "Created",
        400: "Bad Request",
        401: "Unauthorized",
        404: "Not Found",
        409: "Conflict",
    }.get(status_code, "OK")
    return ApiResponse(f"{status_code} {phrase}", json.dumps(payload).encode("utf-8"))


def record_access_log(
    member_id: int | None,
    equipment_id: int | None,
    rfid_uid: str,
    esp32_id: str | None,
    event_type: str,
    decision: str,
    message: str,
) -> None:
    execute(
        """
        INSERT INTO access_logs (
            member_id, equipment_id, rfid_uid, esp32_id, event_type, decision, message, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (member_id, equipment_id, rfid_uid, esp32_id, event_type, decision, message, utc_now()),
    )


def record_pending_rfid_scan(
    rfid_uid: str,
    esp32_id: str | None,
    equipment_id: int | None,
) -> None:
    existing = fetch_one("SELECT * FROM pending_rfid_scans WHERE rfid_uid = ?", (rfid_uid,))
    if existing is None:
        execute(
            """
            INSERT INTO pending_rfid_scans (
                rfid_uid, esp32_id, equipment_id, first_seen_at, last_seen_at, scan_count, status
            ) VALUES (?, ?, ?, ?, ?, 1, 'pending')
            """,
            (rfid_uid, esp32_id, equipment_id, utc_now(), utc_now()),
        )
        return

    if existing["status"] == "enrolled":
        return

    execute(
        """
        UPDATE pending_rfid_scans
        SET esp32_id = ?, equipment_id = ?, last_seen_at = ?, scan_count = scan_count + 1, status = 'pending'
        WHERE id = ?
        """,
        (esp32_id, equipment_id, utc_now(), existing["id"]),
    )


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def membership_state(row: sqlite3.Row | None) -> str:
    if row is None:
        return "unknown"
    if row["membership_status"] != "active":
        return row["membership_status"]

    today = datetime.now(timezone.utc).date()
    start_date = parse_iso_date(row["membership_start_date"])
    end_date = parse_iso_date(row["membership_end_date"])

    if start_date and today < start_date:
        return "upcoming"
    if end_date and today > end_date:
        return "expired"
    return "active"


def equipment_health_state(row: sqlite3.Row | None) -> str:
    if row is None:
        return "unknown"

    configured_status = row["status"]
    if configured_status == "maintenance":
        return "maintenance"

    last_seen_at = parse_iso_datetime(row["last_seen_at"])
    if last_seen_at is None:
        return "offline"

    age_seconds = (datetime.now(timezone.utc) - last_seen_at).total_seconds()
    if age_seconds > DEVICE_OFFLINE_AFTER_SECONDS:
        return "offline"
    return "online"


def active_session_for_member(member_id: int) -> sqlite3.Row | None:
    return fetch_one(
        """
        SELECT *
        FROM gym_sessions
        WHERE member_id = ? AND status = 'active'
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (member_id,),
    )


def occupancy_count() -> int:
    row = fetch_one("SELECT COUNT(*) AS count FROM gym_sessions WHERE status = 'active'")
    return int(row["count"]) if row else 0


def create_session(member_id: int, rfid_uid: str, equipment_id: int | None) -> None:
    execute(
        """
        INSERT INTO gym_sessions (member_id, rfid_uid, entry_equipment_id, started_at, status)
        VALUES (?, ?, ?, ?, 'active')
        """,
        (member_id, rfid_uid, equipment_id, utc_now()),
    )


def end_session(session_id: int, equipment_id: int | None) -> None:
    execute(
        """
        UPDATE gym_sessions
        SET ended_at = ?, exit_equipment_id = ?, status = 'completed'
        WHERE id = ?
        """,
        (utc_now(), equipment_id, session_id),
    )


def row_to_session(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "member_id": row["member_id"],
        "rfid_uid": row["rfid_uid"],
        "entry_equipment_id": row["entry_equipment_id"],
        "exit_equipment_id": row["exit_equipment_id"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "status": row["status"],
    }


def row_to_command(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "equipment_id": row["equipment_id"],
        "esp32_id": row["esp32_id"],
        "command_type": row["command_type"],
        "payload": json.loads(row["payload_json"]),
        "status": row["status"],
        "retry_count": row["retry_count"],
        "created_at": row["created_at"],
        "delivered_at": row["delivered_at"],
        "acknowledged_at": row["acknowledged_at"],
    }


def queue_device_command(
    equipment_id: int,
    esp32_id: str,
    command_type: str,
    payload: dict,
) -> None:
    execute(
        """
        INSERT INTO device_commands (
            equipment_id, esp32_id, command_type, payload_json, status, retry_count, created_at
        ) VALUES (?, ?, ?, ?, 'pending', 0, ?)
        """,
        (equipment_id, esp32_id, command_type, json.dumps(payload), utc_now()),
    )


def queue_manual_relay_test(equipment_id: int) -> sqlite3.Row | None:
    equipment = fetch_one("SELECT * FROM equipment WHERE id = ?", (equipment_id,))
    if equipment is None:
        raise ValueError("equipment not found")

    queue_device_command(
        equipment["id"],
        equipment["esp32_id"],
        "pulse_relay",
        {
            "seconds": int(equipment["relay_seconds"] or 5),
            "reason": "manual_test",
            "member_name": "operator",
        },
    )
    return pending_command_for_device(equipment["esp32_id"])


def record_device_event(
    esp32_id: str,
    event_type: str,
    level: str,
    message: str,
) -> None:
    equipment = fetch_one("SELECT * FROM equipment WHERE esp32_id = ?", (esp32_id,))
    execute(
        """
        INSERT INTO device_events (
            equipment_id, esp32_id, event_type, level, message, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            equipment["id"] if equipment else None,
            esp32_id,
            event_type,
            level,
            message,
            utc_now(),
        ),
    )


def reclaim_stale_delivered_commands(esp32_id: str) -> None:
    delivered_commands = fetch_all(
        """
        SELECT *
        FROM device_commands
        WHERE esp32_id = ? AND status = 'delivered'
        ORDER BY delivered_at ASC
        """,
        (esp32_id,),
    )
    now = datetime.now(timezone.utc)
    for command in delivered_commands:
        delivered_at = parse_iso_datetime(command["delivered_at"])
        if delivered_at is None:
            continue
        age_seconds = (now - delivered_at).total_seconds()
        if age_seconds <= DEVICE_COMMAND_ACK_TIMEOUT_SECONDS:
            continue
        execute(
            """
            UPDATE device_commands
            SET status = 'pending', delivered_at = NULL, retry_count = retry_count + 1
            WHERE id = ?
            """,
            (command["id"],),
        )


def pending_command_for_device(esp32_id: str) -> sqlite3.Row | None:
    reclaim_stale_delivered_commands(esp32_id)
    return fetch_one(
        """
        SELECT *
        FROM device_commands
        WHERE esp32_id = ? AND status = 'pending'
        ORDER BY created_at ASC
        LIMIT 1
        """,
        (esp32_id,),
    )


def mark_command_delivered(command_id: int) -> sqlite3.Row | None:
    execute(
        """
        UPDATE device_commands
        SET status = 'delivered', delivered_at = ?
        WHERE id = ?
        """,
        (utc_now(), command_id),
    )
    return fetch_one("SELECT * FROM device_commands WHERE id = ?", (command_id,))


def acknowledge_command(command_id: int) -> sqlite3.Row | None:
    execute(
        """
        UPDATE device_commands
        SET status = 'acknowledged', acknowledged_at = ?
        WHERE id = ?
        """,
        (utc_now(), command_id),
    )
    return fetch_one("SELECT * FROM device_commands WHERE id = ?", (command_id,))


def latest_commands(limit: int = 50) -> list[sqlite3.Row]:
    return fetch_all("SELECT * FROM device_commands ORDER BY created_at DESC LIMIT ?", (limit,))


def resolve_event_type(requested_event_type: str, equipment: sqlite3.Row | None) -> str:
    normalized = requested_event_type.strip().lower()
    if normalized and normalized not in {"auto", "reader"}:
        return normalized

    reader_mode = str(equipment["reader_mode"]).strip().lower() if equipment is not None else "entry"
    if reader_mode in {"entry", "exit"}:
        return reader_mode
    return "entry"


def is_duplicate_scan(rfid_uid: str, esp32_id: str | None, event_type: str) -> bool:
    if not esp32_id:
        return False

    log = fetch_one(
        """
        SELECT *
        FROM access_logs
        WHERE rfid_uid = ? AND esp32_id = ? AND event_type = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (rfid_uid, esp32_id, event_type),
    )
    if log is None:
        return False

    created_at = parse_iso_datetime(log["created_at"])
    if created_at is None:
        return False

    age_seconds = (datetime.now(timezone.utc) - created_at).total_seconds()
    return age_seconds <= RFID_DUPLICATE_WINDOW_SECONDS


def handle_rfid_scan(payload: dict) -> ApiResponse:
    rfid_uid = str(payload.get("rfid_uid", "")).strip()
    esp32_id = str(payload.get("esp32_id", "")).strip() or None
    requested_event_type = str(payload.get("event_type", "auto")).strip() or "auto"

    if not rfid_uid:
        return json_response(400, {"ok": False, "error": "rfid_uid is required"})

    member = fetch_one("SELECT * FROM members WHERE rfid_uid = ?", (rfid_uid,))
    equipment = (
        fetch_one("SELECT * FROM equipment WHERE esp32_id = ?", (esp32_id,)) if esp32_id else None
    )
    event_type = resolve_event_type(requested_event_type, equipment)

    if is_duplicate_scan(rfid_uid, esp32_id, event_type):
        return json_response(
            200,
            {
                "ok": True,
                "authorized": False,
                "duplicate_ignored": True,
                "message": "Duplicate scan ignored",
                "rfid_uid": rfid_uid,
                "event_type": event_type,
            },
        )

    if member is None:
        record_pending_rfid_scan(rfid_uid, esp32_id, equipment["id"] if equipment else None)
        record_access_log(None, equipment["id"] if equipment else None, rfid_uid, esp32_id, event_type, "denied", "Unknown RFID card")
        return json_response(
            404,
            {"ok": False, "authorized": False, "message": "Unknown RFID card", "rfid_uid": rfid_uid},
        )

    current_membership_state = membership_state(member)
    if current_membership_state != "active":
        denial_message = {
            "inactive": "Membership inactive",
            "expired": "Membership expired",
            "upcoming": "Membership not active yet",
        }.get(current_membership_state, "Membership inactive")
        record_access_log(
            member["id"],
            equipment["id"] if equipment else None,
            rfid_uid,
            esp32_id,
            event_type,
            "denied",
            denial_message,
        )
        return json_response(
            200,
            {
                "ok": True,
                "authorized": False,
                "member": row_to_member(member),
                "message": denial_message,
            },
        )

    current_session = active_session_for_member(member["id"])
    equipment_id = equipment["id"] if equipment else None

    if event_type == "entry":
        if current_session is not None:
            record_access_log(
                member["id"],
                equipment_id,
                rfid_uid,
                esp32_id,
                event_type,
                "denied",
                "Member already checked in",
            )
            return json_response(
                200,
                {
                    "ok": True,
                    "authorized": False,
                    "member": row_to_member(member),
                    "session": row_to_session(current_session),
                    "message": "Member already checked in",
                },
            )

        execute("UPDATE members SET last_checkin_at = ? WHERE id = ?", (utc_now(), member["id"]))
        create_session(member["id"], rfid_uid, equipment_id)
        current_session = active_session_for_member(member["id"])
        message = f"Entry granted for {member['name']}"
    elif event_type == "exit":
        if current_session is None:
            record_access_log(
                member["id"],
                equipment_id,
                rfid_uid,
                esp32_id,
                event_type,
                "denied",
                "No active session to close",
            )
            return json_response(
                200,
                {
                    "ok": True,
                    "authorized": False,
                    "member": row_to_member(member),
                    "message": "No active session to close",
                },
            )

        end_session(current_session["id"], equipment_id)
        current_session = fetch_one("SELECT * FROM gym_sessions WHERE id = ?", (current_session["id"],))
        message = f"Exit recorded for {member['name']}"
    else:
        message = f"Access granted for {member['name']}"

    command = None
    if equipment is not None:
        relay_seconds = int(equipment["relay_seconds"] or 5)
        queue_device_command(
            equipment["id"],
            equipment["esp32_id"],
            "pulse_relay",
            {
                "seconds": relay_seconds,
                "reason": event_type,
                "member_name": member["name"],
            },
        )
        command = row_to_command(pending_command_for_device(equipment["esp32_id"]))

    record_access_log(member["id"], equipment_id, rfid_uid, esp32_id, event_type, "granted", message)
    return json_response(
        200,
        {
            "ok": True,
            "authorized": True,
            "member": row_to_member(member),
            "equipment": row_to_equipment(equipment) if equipment else None,
            "session": row_to_session(current_session),
            "occupancy": occupancy_count(),
            "device_command": command,
            "message": message,
        },
    )


def handle_heartbeat(payload: dict) -> ApiResponse:
    esp32_id = str(payload.get("esp32_id", "")).strip()
    if not esp32_id:
        return json_response(400, {"ok": False, "error": "esp32_id is required"})

    name = str(payload.get("name", esp32_id)).strip() or esp32_id
    location = str(payload.get("location", "")).strip()
    reader_mode = str(payload.get("reader_mode", "entry")).strip() or "entry"
    relay_seconds = int(payload.get("relay_seconds", 5) or 5)
    status = str(payload.get("status", "online")).strip() or "online"
    existing = fetch_one("SELECT * FROM equipment WHERE esp32_id = ?", (esp32_id,))

    if existing:
        execute(
            """
            UPDATE equipment
            SET name = ?, location = ?, reader_mode = ?, relay_seconds = ?, status = ?, last_seen_at = ?
            WHERE esp32_id = ?
            """,
            (name, location or existing["location"], reader_mode, relay_seconds, status, utc_now(), esp32_id),
        )
    else:
        add_equipment(name, esp32_id, location, reader_mode, relay_seconds, status)

    equipment = fetch_one("SELECT * FROM equipment WHERE esp32_id = ?", (esp32_id,))
    return json_response(200, {"ok": True, "equipment": row_to_equipment(equipment)})


def handle_device_poll(payload: dict) -> ApiResponse:
    esp32_id = str(payload.get("esp32_id", "")).strip()
    if not esp32_id:
        return json_response(400, {"ok": False, "error": "esp32_id is required"})

    command = pending_command_for_device(esp32_id)
    if command is None:
        return json_response(200, {"ok": True, "command": None})

    delivered = mark_command_delivered(command["id"])
    return json_response(200, {"ok": True, "command": row_to_command(delivered)})


def handle_command_ack(payload: dict) -> ApiResponse:
    try:
        command_id = int(payload.get("command_id"))
    except (TypeError, ValueError):
        return json_response(400, {"ok": False, "error": "command_id is required"})

    command = fetch_one("SELECT * FROM device_commands WHERE id = ?", (command_id,))
    if command is None:
        return json_response(404, {"ok": False, "error": "command not found"})

    acknowledged = acknowledge_command(command_id)
    return json_response(200, {"ok": True, "command": row_to_command(acknowledged)})


def handle_device_event(payload: dict) -> ApiResponse:
    esp32_id = str(payload.get("esp32_id", "")).strip()
    event_type = str(payload.get("event_type", "device_event")).strip() or "device_event"
    level = str(payload.get("level", "info")).strip() or "info"
    message = str(payload.get("message", "")).strip()

    if not esp32_id:
        return json_response(400, {"ok": False, "error": "esp32_id is required"})
    if not message:
        return json_response(400, {"ok": False, "error": "message is required"})

    record_device_event(esp32_id, event_type, level, message)
    return json_response(200, {"ok": True})


def row_to_member(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "rfid_uid": row["rfid_uid"],
        "membership_status": row["membership_status"],
        "membership_state": membership_state(row),
        "membership_start_date": row["membership_start_date"],
        "membership_end_date": row["membership_end_date"],
        "created_at": row["created_at"],
        "last_checkin_at": row["last_checkin_at"],
    }


def row_to_equipment(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    effective_status = equipment_health_state(row)
    return {
        "id": row["id"],
        "name": row["name"],
        "esp32_id": row["esp32_id"],
        "location": row["location"],
        "reader_mode": row["reader_mode"],
        "relay_seconds": row["relay_seconds"],
        "status": row["status"],
        "effective_status": effective_status,
        "is_stale": effective_status == "offline",
        "last_seen_at": row["last_seen_at"],
        "created_at": row["created_at"],
    }


def render_page(title: str, body: str) -> bytes:
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4f1ea;
      --panel: #fffdf8;
      --ink: #1f2a2d;
      --accent: #b24c2c;
      --accent-soft: #f1d5c7;
      --border: #dccfbe;
      --ok: #2d6a4f;
      --warn: #9c6644;
    }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      background: linear-gradient(180deg, #efe8da 0%, var(--bg) 50%, #ebe5d9 100%);
      color: var(--ink);
    }}
    .shell {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 24px;
    }}
    .hero, .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 20px;
      box-shadow: 0 10px 30px rgba(31, 42, 45, 0.08);
      margin-bottom: 20px;
    }}
    .hero {{
      background: radial-gradient(circle at top right, #f3d8c9, var(--panel) 45%);
    }}
    h1, h2 {{ margin-top: 0; }}
    nav a {{
      color: var(--accent);
      margin-right: 14px;
      text-decoration: none;
      font-weight: bold;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
    }}
    .stat {{
      background: #f8f3ea;
      border-radius: 14px;
      padding: 16px;
      border: 1px solid var(--border);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    th, td {{
      text-align: left;
      padding: 10px 8px;
      border-bottom: 1px solid var(--border);
      vertical-align: top;
    }}
    form {{
      display: grid;
      gap: 10px;
      margin-top: 12px;
    }}
    input, select, button {{
      padding: 10px 12px;
      border-radius: 10px;
      border: 1px solid var(--border);
      font: inherit;
    }}
    button {{
      background: var(--accent);
      color: white;
      cursor: pointer;
      border: none;
    }}
    .tag {{
      display: inline-block;
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 0.85rem;
      background: var(--accent-soft);
    }}
    .ok {{ color: var(--ok); }}
    .warn {{ color: var(--warn); }}
    code {{
      background: #f0e6da;
      padding: 2px 6px;
      border-radius: 6px;
    }}
  </style>
</head>
<body>
  <div class="shell">
    <div class="hero">
      <h1>Gymtastic MVP</h1>
      <p>Local gym operations dashboard with RFID access control and ESP32 device heartbeat tracking.</p>
      <nav>
        <a href="/">Dashboard</a>
        <a href="/members">Members</a>
        <a href="/equipment">Equipment</a>
        <a href="/sessions">Sessions</a>
        <a href="/commands">Commands</a>
        <a href="/device-events">Device Events</a>
        <a href="/logs">Access Logs</a>
      </nav>
    </div>
    {body}
  </div>
</body>
</html>"""
    return html.encode("utf-8")


def dashboard_view() -> bytes:
    members = fetch_one("SELECT COUNT(*) AS count FROM members")
    today = utc_today()
    active_members = fetch_one(
        """
        SELECT COUNT(*) AS count
        FROM members
        WHERE membership_status = 'active'
          AND (membership_start_date IS NULL OR membership_start_date <= ?)
          AND (membership_end_date IS NULL OR membership_end_date >= ?)
        """,
        (today, today),
    )
    expiring_members = fetch_one(
        """
        SELECT COUNT(*) AS count
        FROM members
        WHERE membership_status = 'active'
          AND membership_end_date IS NOT NULL
          AND membership_end_date >= ?
          AND membership_end_date <= ?
        """,
        (today, (datetime.now(timezone.utc).date() + timedelta(days=7)).isoformat()),
    )
    equipment = fetch_one("SELECT COUNT(*) AS count FROM equipment")
    equipment_rows = fetch_all("SELECT * FROM equipment ORDER BY created_at DESC")
    online_equipment_count = sum(1 for row in equipment_rows if equipment_health_state(row) == "online")
    offline_equipment_count = sum(1 for row in equipment_rows if equipment_health_state(row) == "offline")
    active_sessions = fetch_one("SELECT COUNT(*) AS count FROM gym_sessions WHERE status = 'active'")
    pending_commands = fetch_one("SELECT COUNT(*) AS count FROM device_commands WHERE status = 'pending'")
    delivered_commands = fetch_one("SELECT COUNT(*) AS count FROM device_commands WHERE status = 'delivered'")
    device_event_errors = fetch_one(
        "SELECT COUNT(*) AS count FROM device_events WHERE level IN ('error', 'warn')"
    )
    recent_logs = fetch_all("SELECT * FROM access_logs ORDER BY created_at DESC LIMIT 8")
    recent_device_events = fetch_all(
        "SELECT * FROM device_events ORDER BY created_at DESC LIMIT 6"
    )
    live_sessions = fetch_all(
        """
        SELECT gym_sessions.*, members.name AS member_name, equipment.name AS entry_reader
        FROM gym_sessions
        JOIN members ON members.id = gym_sessions.member_id
        LEFT JOIN equipment ON equipment.id = gym_sessions.entry_equipment_id
        WHERE gym_sessions.status = 'active'
        ORDER BY gym_sessions.started_at DESC
        LIMIT 8
        """
    )

    rows = "".join(
        f"<tr><td>{escape(log['created_at'])}</td><td>{escape(log['rfid_uid'])}</td><td>{escape(log['event_type'])}</td><td>{escape(log['decision'])}</td><td>{escape(log['message'])}</td></tr>"
        for log in recent_logs
    ) or "<tr><td colspan='5'>No scans recorded yet.</td></tr>"

    session_rows = "".join(
        f"<tr><td>{escape(session['member_name'])}</td><td>{escape(session['started_at'])}</td><td>{escape(session['entry_reader'] or '-')}</td><td><span class='tag'>active</span></td></tr>"
        for session in live_sessions
    ) or "<tr><td colspan='4'>Gym is currently empty.</td></tr>"

    body = f"""
    <div class="grid">
      <div class="stat"><strong>{members['count']}</strong><br>members</div>
      <div class="stat"><strong>{active_members['count']}</strong><br>active memberships</div>
      <div class="stat"><strong>{expiring_members['count']}</strong><br>expiring in 7 days</div>
      <div class="stat"><strong>{equipment['count']}</strong><br>ESP32 devices</div>
      <div class="stat"><strong>{online_equipment_count}</strong><br>online devices</div>
      <div class="stat"><strong>{offline_equipment_count}</strong><br>offline devices</div>
      <div class="stat"><strong>{active_sessions['count']}</strong><br>members in gym</div>
      <div class="stat"><strong>{pending_commands['count']}</strong><br>pending relay commands</div>
      <div class="stat"><strong>{delivered_commands['count']}</strong><br>awaiting command ack</div>
      <div class="stat"><strong>{device_event_errors['count']}</strong><br>device warnings/errors</div>
    </div>
    <div class="panel">
      <h2>Device integration</h2>
      <p>RFID scan endpoint: <code>POST /api/rfid/scan</code></p>
      <p>ESP32 heartbeat endpoint: <code>POST /api/esp32/heartbeat</code></p>
      <p>ESP32 command poll endpoint: <code>POST /api/device/poll</code></p>
      <p>ESP32 command ack endpoint: <code>POST /api/device/ack</code></p>
      <p>Readers can be configured as <code>entry</code> or <code>exit</code>; scans with <code>event_type=auto</code> follow the reader role.</p>
    </div>
    <div class="panel">
      <h2>Live occupancy</h2>
      <table>
        <thead><tr><th>Member</th><th>Started at</th><th>Entry reader</th><th>Status</th></tr></thead>
        <tbody>{session_rows}</tbody>
      </table>
    </div>
    <div class="panel">
      <h2>Recent access events</h2>
      <table>
        <thead><tr><th>Time</th><th>RFID</th><th>Event</th><th>Decision</th><th>Message</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    <div class="panel">
      <h2>Recent device events</h2>
      <table>
        <thead><tr><th>Time</th><th>ESP32</th><th>Type</th><th>Level</th><th>Message</th></tr></thead>
        <tbody>{
            "".join(
                f"<tr><td>{escape(event['created_at'])}</td><td><code>{escape(event['esp32_id'])}</code></td><td>{escape(event['event_type'])}</td><td>{escape(event['level'])}</td><td>{escape(event['message'])}</td></tr>"
                for event in recent_device_events
            ) or "<tr><td colspan='5'>No device events yet.</td></tr>"
        }</tbody>
      </table>
    </div>
    """
    return render_page("Dashboard", body)


def members_view() -> bytes:
    members = fetch_all("SELECT * FROM members ORDER BY created_at DESC")
    pending_scans = fetch_all(
        """
        SELECT pending_rfid_scans.*, equipment.name AS equipment_name
        FROM pending_rfid_scans
        LEFT JOIN equipment ON equipment.id = pending_rfid_scans.equipment_id
        WHERE pending_rfid_scans.status = 'pending'
        ORDER BY pending_rfid_scans.last_seen_at DESC
        LIMIT 20
        """
    )
    rows = "".join(
        f"<tr><td>{escape(member['name'])}</td><td>{escape(member['email'] or '')}</td><td><code>{escape(member['rfid_uid'])}</code></td><td><span class='tag'>{escape(membership_state(member))}</span></td><td>{escape(member['membership_start_date'] or '-')}</td><td>{escape(member['membership_end_date'] or '-')}</td><td>{escape(member['last_checkin_at'] or '-')}</td></tr>"
        for member in members
    )
    pending_rows = "".join(
        f"<tr><td><code>{escape(scan['rfid_uid'])}</code></td><td>{escape(scan['equipment_name'] or (scan['esp32_id'] or '-'))}</td><td>{escape(scan['last_seen_at'])}</td><td>{scan['scan_count']}</td><td>"
        f"<form method='post' action='/members/enroll'>"
        f"<input type='hidden' name='pending_scan_id' value='{scan['id']}'>"
        f"<input name='name' placeholder='Full name' required>"
        f"<input name='email' placeholder='Email address'>"
        f"<input type='date' name='membership_start_date' value='{escape(utc_today())}'>"
        f"<input type='date' name='membership_end_date' value='{escape((datetime.now(timezone.utc).date() + timedelta(days=30)).isoformat())}'>"
        f"<select name='membership_status'><option value='active'>active</option><option value='inactive'>inactive</option></select>"
        f"<button type='submit'>Enroll card</button>"
        f"</form></td></tr>"
        for scan in pending_scans
    ) or "<tr><td colspan='5'>No pending RFID enrollments.</td></tr>"
    default_start = utc_today()
    default_end = (datetime.now(timezone.utc).date() + timedelta(days=30)).isoformat()
    body = f"""
    <div class="panel">
      <h2>Members</h2>
      <table>
        <thead><tr><th>Name</th><th>Email</th><th>RFID UID</th><th>Status</th><th>Start</th><th>End</th><th>Last check-in</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    <div class="panel">
      <h2>Add member</h2>
      <form method="post" action="/members">
        <input name="name" placeholder="Full name" required>
        <input name="email" placeholder="Email address">
        <input name="rfid_uid" placeholder="RFID UID" required>
        <select name="membership_status">
          <option value="active">active</option>
          <option value="inactive">inactive</option>
        </select>
        <input type="date" name="membership_start_date" value="{escape(default_start)}">
        <input type="date" name="membership_end_date" value="{escape(default_end)}">
        <button type="submit">Create member</button>
      </form>
    </div>
    <div class="panel">
      <h2>Pending RFID enrollments</h2>
      <table>
        <thead><tr><th>RFID UID</th><th>Reader</th><th>Last seen</th><th>Scans</th><th>Enroll</th></tr></thead>
        <tbody>{pending_rows}</tbody>
      </table>
    </div>
    """
    return render_page("Members", body)


def equipment_view() -> bytes:
    devices = fetch_all("SELECT * FROM equipment ORDER BY created_at DESC")
    rows = "".join(
        f"<tr><td>{escape(device['name'])}</td><td><code>{escape(device['esp32_id'])}</code></td><td>{escape(device['location'] or '-')}</td><td>{escape(device['reader_mode'])}</td><td>{device['relay_seconds']}s</td><td><span class='tag'>{escape(equipment_health_state(device))}</span></td><td>{escape(device['status'])}</td><td>{escape(device['last_seen_at'] or '-')}</td><td>"
        f"<form method='post' action='/equipment/trigger'>"
        f"<input type='hidden' name='equipment_id' value='{device['id']}'>"
        f"<button type='submit'>Test relay</button>"
        f"</form></td></tr>"
        for device in devices
    )
    body = f"""
    <div class="panel">
      <h2>ESP32 readers</h2>
      <table>
        <thead><tr><th>Name</th><th>ESP32 ID</th><th>Location</th><th>Reader mode</th><th>Relay pulse</th><th>Health</th><th>Configured status</th><th>Last seen</th><th>Control</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    <div class="panel">
      <h2>Add device</h2>
      <form method="post" action="/equipment">
        <input name="name" placeholder="Reader name" required>
        <input name="esp32_id" placeholder="ESP32 device ID" required>
        <input name="location" placeholder="Location">
        <select name="reader_mode">
          <option value="entry">entry</option>
          <option value="exit">exit</option>
          <option value="both">both</option>
        </select>
        <input type="number" min="1" max="30" name="relay_seconds" value="5" required>
        <select name="status">
          <option value="online">online</option>
          <option value="offline">offline</option>
          <option value="maintenance">maintenance</option>
        </select>
        <button type="submit">Register device</button>
      </form>
    </div>
    """
    return render_page("Equipment", body)


def logs_view() -> bytes:
    logs = fetch_all(
        """
        SELECT access_logs.*, members.name AS member_name, equipment.name AS equipment_name
        FROM access_logs
        LEFT JOIN members ON members.id = access_logs.member_id
        LEFT JOIN equipment ON equipment.id = access_logs.equipment_id
        ORDER BY access_logs.created_at DESC
        LIMIT 50
        """
    )
    rows = "".join(
        f"<tr><td>{escape(log['created_at'])}</td><td>{escape(log['member_name'] or 'Unknown')}</td><td><code>{escape(log['rfid_uid'])}</code></td><td>{escape(log['equipment_name'] or (log['esp32_id'] or '-'))}</td><td>{escape(log['event_type'])}</td><td>{escape(log['decision'])}</td><td>{escape(log['message'])}</td></tr>"
        for log in logs
    ) or "<tr><td colspan='7'>No log entries yet.</td></tr>"
    body = f"""
    <div class="panel">
      <h2>Access log</h2>
      <table>
        <thead><tr><th>Time</th><th>Member</th><th>RFID</th><th>Reader</th><th>Event</th><th>Decision</th><th>Message</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    """
    return render_page("Access Logs", body)


def sessions_view() -> bytes:
    sessions = fetch_all(
        """
        SELECT
            gym_sessions.*,
            members.name AS member_name,
            entry.name AS entry_reader_name,
            exit.name AS exit_reader_name
        FROM gym_sessions
        JOIN members ON members.id = gym_sessions.member_id
        LEFT JOIN equipment AS entry ON entry.id = gym_sessions.entry_equipment_id
        LEFT JOIN equipment AS exit ON exit.id = gym_sessions.exit_equipment_id
        ORDER BY gym_sessions.started_at DESC
        LIMIT 100
        """
    )
    rows = "".join(
        f"<tr><td>{escape(session['member_name'])}</td><td>{escape(session['started_at'])}</td><td>{escape(session['ended_at'] or '-')}</td><td>{escape(session['entry_reader_name'] or '-')}</td><td>{escape(session['exit_reader_name'] or '-')}</td><td><span class='tag'>{escape(session['status'])}</span></td></tr>"
        for session in sessions
    ) or "<tr><td colspan='6'>No gym sessions yet.</td></tr>"
    body = f"""
    <div class="panel">
      <h2>Gym sessions</h2>
      <table>
        <thead><tr><th>Member</th><th>Started at</th><th>Ended at</th><th>Entry reader</th><th>Exit reader</th><th>Status</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    """
    return render_page("Sessions", body)


def commands_view() -> bytes:
    commands = latest_commands()
    rows = "".join(
        f"<tr><td>{escape(command['created_at'])}</td><td><code>{escape(command['esp32_id'])}</code></td><td>{escape(command['command_type'])}</td><td>{escape(command['status'])}</td><td>{command['retry_count']}</td><td><code>{escape(command['payload_json'])}</code></td></tr>"
        for command in commands
    ) or "<tr><td colspan='5'>No device commands yet.</td></tr>"
    body = f"""
    <div class="panel">
      <h2>Device commands</h2>
      <table>
        <thead><tr><th>Created</th><th>ESP32</th><th>Command</th><th>Status</th><th>Retries</th><th>Payload</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    """
    return render_page("Commands", body)


def device_events_view() -> bytes:
    events = fetch_all(
        """
        SELECT device_events.*, equipment.name AS equipment_name
        FROM device_events
        LEFT JOIN equipment ON equipment.id = device_events.equipment_id
        ORDER BY device_events.created_at DESC
        LIMIT 100
        """
    )
    rows = "".join(
        f"<tr><td>{escape(event['created_at'])}</td><td>{escape(event['equipment_name'] or '-')}</td><td><code>{escape(event['esp32_id'])}</code></td><td>{escape(event['event_type'])}</td><td>{escape(event['level'])}</td><td>{escape(event['message'])}</td></tr>"
        for event in events
    ) or "<tr><td colspan='6'>No device events yet.</td></tr>"
    body = f"""
    <div class="panel">
      <h2>Device events</h2>
      <table>
        <thead><tr><th>Time</th><th>Reader</th><th>ESP32</th><th>Type</th><th>Level</th><th>Message</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    """
    return render_page("Device Events", body)


def serve_html(start_response, body: bytes) -> list[bytes]:
    start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
    return [body]


def serve_api(start_response, response: ApiResponse) -> list[bytes]:
    start_response(response.status, [("Content-Type", response.content_type)])
    return [response.body]


def app(environ, start_response):
    method = environ["REQUEST_METHOD"]
    path = environ.get("PATH_INFO", "/")

    if method == "GET" and path == "/":
        return serve_html(start_response, dashboard_view())
    if method == "GET" and path == "/members":
        return serve_html(start_response, members_view())
    if method == "POST" and path == "/members":
        form = parse_form(environ)
        add_member(
            form.get("name", ""),
            form.get("email", ""),
            form.get("rfid_uid", ""),
            form.get("membership_status", "active"),
            form.get("membership_start_date", ""),
            form.get("membership_end_date", ""),
        )
        return redirect(start_response, "/members")
    if method == "POST" and path == "/members/enroll":
        form = parse_form(environ)
        add_member_from_pending_scan(
            int(form.get("pending_scan_id", "0")),
            form.get("name", ""),
            form.get("email", ""),
            form.get("membership_status", "active"),
            form.get("membership_start_date", ""),
            form.get("membership_end_date", ""),
        )
        return redirect(start_response, "/members")
    if method == "GET" and path == "/equipment":
        return serve_html(start_response, equipment_view())
    if method == "POST" and path == "/equipment":
        form = parse_form(environ)
        add_equipment(
            form.get("name", ""),
            form.get("esp32_id", ""),
            form.get("location", ""),
            form.get("reader_mode", "entry"),
            int(form.get("relay_seconds", "5") or "5"),
            form.get("status", "online"),
        )
        return redirect(start_response, "/equipment")
    if method == "POST" and path == "/equipment/trigger":
        form = parse_form(environ)
        queue_manual_relay_test(int(form.get("equipment_id", "0")))
        return redirect(start_response, "/equipment")
    if method == "GET" and path == "/logs":
        return serve_html(start_response, logs_view())
    if method == "GET" and path == "/sessions":
        return serve_html(start_response, sessions_view())
    if method == "GET" and path == "/commands":
        return serve_html(start_response, commands_view())
    if method == "GET" and path == "/device-events":
        return serve_html(start_response, device_events_view())
    if method == "GET" and path == "/api/members":
        members = [row_to_member(row) for row in fetch_all("SELECT * FROM members ORDER BY created_at DESC")]
        return serve_api(start_response, json_response(200, {"ok": True, "members": members}))
    if method == "GET" and path == "/api/pending-rfid":
        pending = [
            dict(row)
            for row in fetch_all(
                "SELECT * FROM pending_rfid_scans WHERE status = 'pending' ORDER BY last_seen_at DESC LIMIT 100"
            )
        ]
        return serve_api(start_response, json_response(200, {"ok": True, "pending_rfid": pending}))
    if method == "GET" and path == "/api/equipment":
        devices = [row_to_equipment(row) for row in fetch_all("SELECT * FROM equipment ORDER BY created_at DESC")]
        return serve_api(start_response, json_response(200, {"ok": True, "equipment": devices}))
    if method == "GET" and path == "/api/logs":
        logs = [dict(row) for row in fetch_all("SELECT * FROM access_logs ORDER BY created_at DESC LIMIT 100")]
        return serve_api(start_response, json_response(200, {"ok": True, "logs": logs}))
    if method == "GET" and path == "/api/sessions":
        sessions = [
            row_to_session(row)
            for row in fetch_all("SELECT * FROM gym_sessions ORDER BY started_at DESC LIMIT 100")
        ]
        return serve_api(
            start_response,
            json_response(
                200,
                {
                    "ok": True,
                    "occupancy": occupancy_count(),
                    "sessions": sessions,
                },
            ),
        )
    if method == "GET" and path == "/api/commands":
        commands = [row_to_command(row) for row in latest_commands(100)]
        return serve_api(start_response, json_response(200, {"ok": True, "commands": commands}))
    if method == "GET" and path == "/api/device-events":
        events = [dict(row) for row in fetch_all("SELECT * FROM device_events ORDER BY created_at DESC LIMIT 100")]
        return serve_api(start_response, json_response(200, {"ok": True, "device_events": events}))
    if method == "POST" and path == "/api/equipment/trigger":
        payload = parse_json(environ)
        try:
            equipment_id = int(payload.get("equipment_id"))
        except (TypeError, ValueError):
            return serve_api(start_response, json_response(400, {"ok": False, "error": "equipment_id is required"}))
        command = row_to_command(queue_manual_relay_test(equipment_id))
        return serve_api(start_response, json_response(200, {"ok": True, "command": command}))
    if method == "POST" and path == "/api/rfid/scan":
        auth_error = verify_device_request(environ)
        if auth_error is not None:
            return serve_api(start_response, auth_error)
        return serve_api(start_response, handle_rfid_scan(parse_json(environ)))
    if method == "POST" and path == "/api/esp32/heartbeat":
        auth_error = verify_device_request(environ)
        if auth_error is not None:
            return serve_api(start_response, auth_error)
        return serve_api(start_response, handle_heartbeat(parse_json(environ)))
    if method == "POST" and path == "/api/device/poll":
        auth_error = verify_device_request(environ)
        if auth_error is not None:
            return serve_api(start_response, auth_error)
        return serve_api(start_response, handle_device_poll(parse_json(environ)))
    if method == "POST" and path == "/api/device/ack":
        auth_error = verify_device_request(environ)
        if auth_error is not None:
            return serve_api(start_response, auth_error)
        return serve_api(start_response, handle_command_ack(parse_json(environ)))
    if method == "POST" and path == "/api/device/event":
        auth_error = verify_device_request(environ)
        if auth_error is not None:
            return serve_api(start_response, auth_error)
        return serve_api(start_response, handle_device_event(parse_json(environ)))

    return serve_api(start_response, json_response(404, {"ok": False, "error": f"Route not found: {path}"}))


def main() -> None:
    init_db()
    seed_defaults()
    host = os.getenv("GYMTASTIC_HOST", "127.0.0.1")
    port = int(os.getenv("GYMTASTIC_PORT", "8000"))
    print(f"Gymtastic running on http://{host}:{port}")
    with make_server(host, port, app) as server:
        server.serve_forever()
