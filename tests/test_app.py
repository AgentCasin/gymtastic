from io import BytesIO
import json
from datetime import datetime, timedelta, timezone
import os
import unittest

from gymtastic import app as gym_app
from tools import simulate_device


class GymtasticAppTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ.pop("GYMTASTIC_DEVICE_TOKEN", None)
        gym_app.DB_PATH = gym_app.BASE_DIR / "test_gymtastic.db"
        if gym_app.DB_PATH.exists():
            gym_app.DB_PATH.unlink()
        gym_app.init_db()
        gym_app.seed_defaults()

    def tearDown(self) -> None:
        os.environ.pop("GYMTASTIC_DEVICE_TOKEN", None)
        if gym_app.DB_PATH.exists():
            gym_app.DB_PATH.unlink()

    def request(
        self,
        method: str,
        path: str,
        body: bytes = b"",
        content_type: str = "application/json",
        headers: dict[str, str] | None = None,
    ):
        captured: dict[str, object] = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = headers

        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "CONTENT_LENGTH": str(len(body)),
            "CONTENT_TYPE": content_type,
            "wsgi.input": BytesIO(body),
        }
        for key, value in (headers or {}).items():
            environ[f"HTTP_{key.upper().replace('-', '_')}"] = value
        response = b"".join(gym_app.app(environ, start_response))
        captured["body"] = response
        return captured

    def test_dashboard_renders(self) -> None:
        response = self.request("GET", "/")
        self.assertEqual(response["status"], "200 OK")
        self.assertIn(b"Gymtastic MVP", response["body"])

    def test_known_member_scan_is_authorized(self) -> None:
        gym_app.execute(
            "UPDATE equipment SET relay_seconds = ? WHERE esp32_id = ?",
            (7, "ESP32-GATE-01"),
        )
        payload = json.dumps(
            {"rfid_uid": "RFID-DEMO-001", "esp32_id": "ESP32-GATE-01", "event_type": "entry"}
        ).encode("utf-8")
        response = self.request("POST", "/api/rfid/scan", payload)
        data = json.loads(response["body"])
        self.assertEqual(response["status"], "200 OK")
        self.assertTrue(data["authorized"])
        self.assertEqual(data["member"]["name"], "Demo Member")
        self.assertEqual(data["session"]["status"], "active")
        self.assertEqual(data["occupancy"], 1)
        self.assertEqual(data["device_command"]["command_type"], "pulse_relay")
        self.assertEqual(data["device_command"]["payload"]["seconds"], 7)

    def test_double_entry_is_denied_while_session_active(self) -> None:
        payload = json.dumps(
            {"rfid_uid": "RFID-DEMO-001", "esp32_id": "ESP32-GATE-01", "event_type": "entry"}
        ).encode("utf-8")
        self.request("POST", "/api/rfid/scan", payload)
        response = self.request("POST", "/api/rfid/scan", payload)
        data = json.loads(response["body"])
        self.assertEqual(response["status"], "200 OK")
        self.assertFalse(data["authorized"])
        self.assertTrue(data["duplicate_ignored"])
        self.assertEqual(data["message"], "Duplicate scan ignored")

    def test_exit_closes_active_session(self) -> None:
        entry_payload = json.dumps(
            {"rfid_uid": "RFID-DEMO-001", "esp32_id": "ESP32-GATE-01", "event_type": "entry"}
        ).encode("utf-8")
        exit_payload = json.dumps(
            {"rfid_uid": "RFID-DEMO-001", "esp32_id": "ESP32-GATE-01", "event_type": "exit"}
        ).encode("utf-8")

        self.request("POST", "/api/rfid/scan", entry_payload)
        response = self.request("POST", "/api/rfid/scan", exit_payload)
        data = json.loads(response["body"])

        self.assertEqual(response["status"], "200 OK")
        self.assertTrue(data["authorized"])
        self.assertEqual(data["session"]["status"], "completed")
        self.assertEqual(data["occupancy"], 0)

    def test_exit_reader_can_infer_exit_without_explicit_event_type(self) -> None:
        gym_app.execute(
            "UPDATE equipment SET reader_mode = ? WHERE esp32_id = ?",
            ("exit", "ESP32-GATE-01"),
        )
        entry_payload = json.dumps(
            {"rfid_uid": "RFID-DEMO-001", "event_type": "entry"}
        ).encode("utf-8")
        auto_payload = json.dumps({"rfid_uid": "RFID-DEMO-001", "esp32_id": "ESP32-GATE-01"}).encode("utf-8")

        self.request("POST", "/api/rfid/scan", entry_payload)
        response = self.request("POST", "/api/rfid/scan", auto_payload)
        data = json.loads(response["body"])

        self.assertEqual(response["status"], "200 OK")
        self.assertTrue(data["authorized"])
        self.assertEqual(data["session"]["status"], "completed")
        self.assertEqual(data["message"], "Exit recorded for Demo Member")

    def test_sessions_api_reports_occupancy(self) -> None:
        payload = json.dumps(
            {"rfid_uid": "RFID-DEMO-001", "esp32_id": "ESP32-GATE-01", "event_type": "entry"}
        ).encode("utf-8")
        self.request("POST", "/api/rfid/scan", payload)
        response = self.request("GET", "/api/sessions")
        data = json.loads(response["body"])
        self.assertEqual(response["status"], "200 OK")
        self.assertEqual(data["occupancy"], 1)
        self.assertEqual(len(data["sessions"]), 1)

    def test_authorized_scan_queues_device_command(self) -> None:
        payload = json.dumps(
            {"rfid_uid": "RFID-DEMO-001", "esp32_id": "ESP32-GATE-01", "event_type": "entry"}
        ).encode("utf-8")
        self.request("POST", "/api/rfid/scan", payload)
        response = self.request("GET", "/api/commands")
        data = json.loads(response["body"])
        self.assertEqual(response["status"], "200 OK")
        self.assertEqual(len(data["commands"]), 1)
        self.assertEqual(data["commands"][0]["status"], "pending")

    def test_manual_relay_trigger_queues_command(self) -> None:
        equipment = gym_app.fetch_one("SELECT * FROM equipment WHERE esp32_id = ?", ("ESP32-GATE-01",))
        payload = json.dumps({"equipment_id": equipment["id"]}).encode("utf-8")
        response = self.request("POST", "/api/equipment/trigger", payload)
        data = json.loads(response["body"])
        self.assertEqual(response["status"], "200 OK")
        self.assertEqual(data["command"]["command_type"], "pulse_relay")
        self.assertEqual(data["command"]["payload"]["reason"], "manual_test")

    def test_device_event_is_recorded(self) -> None:
        payload = json.dumps(
            {
                "esp32_id": "ESP32-GATE-01",
                "event_type": "wifi_warning",
                "level": "warn",
                "message": "Signal strength is low",
            }
        ).encode("utf-8")
        response = self.request("POST", "/api/device/event", payload)
        data = json.loads(response["body"])
        events_response = self.request("GET", "/api/device-events")
        events_data = json.loads(events_response["body"])
        self.assertEqual(response["status"], "200 OK")
        self.assertTrue(data["ok"])
        self.assertEqual(events_response["status"], "200 OK")
        self.assertEqual(events_data["device_events"][0]["event_type"], "wifi_warning")

    def test_simulator_can_build_device_event_payload(self) -> None:
        class Args:
            base_url = "http://127.0.0.1:8000"
            device_token = ""
            device_id = "ESP32-GATE-01"

        original = simulate_device.post_json
        captured = {}

        def fake_post_json(base_url, path, payload, device_token):
            captured["base_url"] = base_url
            captured["path"] = path
            captured["payload"] = payload
            captured["device_token"] = device_token
            return {"ok": True}

        simulate_device.post_json = fake_post_json
        try:
            simulate_device.report_event(Args(), "wifi_warning", "warn", "Signal low")
        finally:
            simulate_device.post_json = original

        self.assertEqual(captured["path"], "/api/device/event")
        self.assertEqual(captured["payload"]["event_type"], "wifi_warning")
        self.assertEqual(captured["payload"]["level"], "warn")

    def test_db_path_can_be_overridden_for_runtime(self) -> None:
        self.assertTrue(str(gym_app.DB_PATH).endswith(".db"))

    def test_device_can_poll_and_ack_command(self) -> None:
        scan_payload = json.dumps(
            {"rfid_uid": "RFID-DEMO-001", "esp32_id": "ESP32-GATE-01", "event_type": "entry"}
        ).encode("utf-8")
        poll_payload = json.dumps({"esp32_id": "ESP32-GATE-01"}).encode("utf-8")

        self.request("POST", "/api/rfid/scan", scan_payload)
        poll_response = self.request("POST", "/api/device/poll", poll_payload)
        poll_data = json.loads(poll_response["body"])

        self.assertEqual(poll_response["status"], "200 OK")
        self.assertEqual(poll_data["command"]["status"], "delivered")

        ack_payload = json.dumps({"command_id": poll_data["command"]["id"]}).encode("utf-8")
        ack_response = self.request("POST", "/api/device/ack", ack_payload)
        ack_data = json.loads(ack_response["body"])

        self.assertEqual(ack_response["status"], "200 OK")
        self.assertEqual(ack_data["command"]["status"], "acknowledged")

    def test_device_poll_returns_none_when_no_commands_waiting(self) -> None:
        poll_payload = json.dumps({"esp32_id": "ESP32-GATE-01"}).encode("utf-8")
        response = self.request("POST", "/api/device/poll", poll_payload)
        data = json.loads(response["body"])
        self.assertEqual(response["status"], "200 OK")
        self.assertIsNone(data["command"])

    def test_stale_delivered_command_is_requeued_on_next_poll(self) -> None:
        scan_payload = json.dumps(
            {"rfid_uid": "RFID-DEMO-001", "esp32_id": "ESP32-GATE-01", "event_type": "entry"}
        ).encode("utf-8")
        poll_payload = json.dumps({"esp32_id": "ESP32-GATE-01"}).encode("utf-8")

        self.request("POST", "/api/rfid/scan", scan_payload)
        first_poll = self.request("POST", "/api/device/poll", poll_payload)
        first_data = json.loads(first_poll["body"])
        stale_time = (datetime.now(timezone.utc) - timedelta(seconds=60)).replace(microsecond=0).isoformat()
        gym_app.execute(
            "UPDATE device_commands SET delivered_at = ? WHERE id = ?",
            (stale_time, first_data["command"]["id"]),
        )

        second_poll = self.request("POST", "/api/device/poll", poll_payload)
        second_data = json.loads(second_poll["body"])

        self.assertEqual(second_poll["status"], "200 OK")
        self.assertEqual(second_data["command"]["id"], first_data["command"]["id"])
        self.assertEqual(second_data["command"]["status"], "delivered")
        self.assertEqual(second_data["command"]["retry_count"], 1)

    def test_device_endpoints_require_token_when_configured(self) -> None:
        os.environ["GYMTASTIC_DEVICE_TOKEN"] = "secret-token"
        payload = json.dumps({"esp32_id": "ESP32-GATE-01"}).encode("utf-8")
        response = self.request("POST", "/api/device/poll", payload)
        data = json.loads(response["body"])
        self.assertEqual(response["status"], "401 Unauthorized")
        self.assertEqual(data["error"], "invalid device token")

    def test_device_endpoints_accept_valid_token(self) -> None:
        os.environ["GYMTASTIC_DEVICE_TOKEN"] = "secret-token"
        payload = json.dumps({"esp32_id": "ESP32-GATE-01"}).encode("utf-8")
        response = self.request(
            "POST",
            "/api/device/poll",
            payload,
            headers={"X-Device-Token": "secret-token"},
        )
        data = json.loads(response["body"])
        self.assertEqual(response["status"], "200 OK")
        self.assertIsNone(data["command"])

    def test_simulator_builds_device_token_header(self) -> None:
        headers = simulate_device.build_headers("secret-token")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["X-Device-Token"], "secret-token")

    def test_unknown_member_scan_is_denied(self) -> None:
        payload = json.dumps({"rfid_uid": "UNKNOWN"}).encode("utf-8")
        response = self.request("POST", "/api/rfid/scan", payload)
        data = json.loads(response["body"])
        self.assertEqual(response["status"], "404 Not Found")
        self.assertFalse(data["authorized"])

    def test_unknown_scan_is_captured_for_enrollment(self) -> None:
        payload = json.dumps({"rfid_uid": "RFID-NEW-001", "esp32_id": "ESP32-GATE-01"}).encode("utf-8")
        self.request("POST", "/api/rfid/scan", payload)
        response = self.request("GET", "/api/pending-rfid")
        data = json.loads(response["body"])
        self.assertEqual(response["status"], "200 OK")
        self.assertEqual(len(data["pending_rfid"]), 1)
        self.assertEqual(data["pending_rfid"][0]["rfid_uid"], "RFID-NEW-001")

    def test_duplicate_unknown_scan_is_ignored_without_incrementing_pending_count(self) -> None:
        payload = json.dumps({"rfid_uid": "RFID-NEW-003", "esp32_id": "ESP32-GATE-01"}).encode("utf-8")
        self.request("POST", "/api/rfid/scan", payload)
        response = self.request("POST", "/api/rfid/scan", payload)
        data = json.loads(response["body"])
        pending = gym_app.fetch_one(
            "SELECT * FROM pending_rfid_scans WHERE rfid_uid = ?",
            ("RFID-NEW-003",),
        )
        self.assertEqual(response["status"], "200 OK")
        self.assertTrue(data["duplicate_ignored"])
        self.assertEqual(pending["scan_count"], 1)

    def test_pending_scan_can_be_enrolled_into_member(self) -> None:
        payload = json.dumps({"rfid_uid": "RFID-NEW-002", "esp32_id": "ESP32-GATE-01"}).encode("utf-8")
        self.request("POST", "/api/rfid/scan", payload)
        pending = gym_app.fetch_one(
            "SELECT * FROM pending_rfid_scans WHERE rfid_uid = ?",
            ("RFID-NEW-002",),
        )
        gym_app.add_member_from_pending_scan(
            pending["id"],
            "New Member",
            "new@gym.local",
            "active",
            datetime.now(timezone.utc).date().isoformat(),
            (datetime.now(timezone.utc).date() + timedelta(days=30)).isoformat(),
        )
        member = gym_app.fetch_one("SELECT * FROM members WHERE rfid_uid = ?", ("RFID-NEW-002",))
        updated_pending = gym_app.fetch_one(
            "SELECT * FROM pending_rfid_scans WHERE rfid_uid = ?",
            ("RFID-NEW-002",),
        )
        self.assertEqual(member["name"], "New Member")
        self.assertEqual(updated_pending["status"], "enrolled")

    def test_expired_membership_is_denied(self) -> None:
        expired_end = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
        gym_app.add_member(
            "Expired Member",
            "expired@gym.local",
            "RFID-EXPIRED-001",
            "active",
            (datetime.now(timezone.utc).date() - timedelta(days=30)).isoformat(),
            expired_end,
        )
        payload = json.dumps(
            {"rfid_uid": "RFID-EXPIRED-001", "esp32_id": "ESP32-GATE-01", "event_type": "entry"}
        ).encode("utf-8")
        response = self.request("POST", "/api/rfid/scan", payload)
        data = json.loads(response["body"])
        self.assertEqual(response["status"], "200 OK")
        self.assertFalse(data["authorized"])
        self.assertEqual(data["message"], "Membership expired")

    def test_members_api_includes_membership_state(self) -> None:
        response = self.request("GET", "/api/members")
        data = json.loads(response["body"])
        self.assertEqual(response["status"], "200 OK")
        self.assertIn("membership_state", data["members"][0])

    def test_heartbeat_creates_new_equipment(self) -> None:
        payload = json.dumps(
            {
                "esp32_id": "ESP32-RACK-02",
                "name": "Rack Reader",
                "location": "Rack Zone",
                "reader_mode": "exit",
                "relay_seconds": 9,
            }
        ).encode("utf-8")
        response = self.request("POST", "/api/esp32/heartbeat", payload)
        data = json.loads(response["body"])
        self.assertEqual(response["status"], "200 OK")
        self.assertEqual(data["equipment"]["esp32_id"], "ESP32-RACK-02")
        self.assertEqual(data["equipment"]["effective_status"], "online")
        self.assertEqual(data["equipment"]["reader_mode"], "exit")
        self.assertEqual(data["equipment"]["relay_seconds"], 9)

    def test_stale_equipment_is_reported_offline(self) -> None:
        stale_seen = (datetime.now(timezone.utc) - timedelta(seconds=400)).replace(microsecond=0).isoformat()
        gym_app.execute(
            "UPDATE equipment SET status = ?, last_seen_at = ? WHERE esp32_id = ?",
            ("online", stale_seen, "ESP32-GATE-01"),
        )
        response = self.request("GET", "/api/equipment")
        data = json.loads(response["body"])
        self.assertEqual(response["status"], "200 OK")
        self.assertEqual(data["equipment"][0]["effective_status"], "offline")
        self.assertTrue(data["equipment"][0]["is_stale"])

    def test_maintenance_equipment_stays_in_maintenance(self) -> None:
        stale_seen = (datetime.now(timezone.utc) - timedelta(seconds=400)).replace(microsecond=0).isoformat()
        gym_app.execute(
            "UPDATE equipment SET status = ?, last_seen_at = ? WHERE esp32_id = ?",
            ("maintenance", stale_seen, "ESP32-GATE-01"),
        )
        response = self.request("GET", "/api/equipment")
        data = json.loads(response["body"])
        self.assertEqual(response["status"], "200 OK")
        self.assertEqual(data["equipment"][0]["effective_status"], "maintenance")
        self.assertFalse(data["equipment"][0]["is_stale"])


if __name__ == "__main__":
    unittest.main()
