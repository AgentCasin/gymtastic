#include <HTTPClient.h>
#include <MFRC522.h>
#include <SPI.h>
#include <WiFi.h>

// Replace with your Wi-Fi and server settings.
constexpr char WIFI_SSID[] = "YOUR_WIFI_SSID";
constexpr char WIFI_PASSWORD[] = "YOUR_WIFI_PASSWORD";
constexpr char API_BASE[] = "http://192.168.1.10:8000";
constexpr char DEVICE_TOKEN[] = "CHANGE_ME_DEVICE_TOKEN";
constexpr char DEVICE_ID[] = "ESP32-GATE-01";
constexpr char DEVICE_NAME[] = "Front Gate Reader";
constexpr char DEVICE_LOCATION[] = "Entrance";
constexpr char READER_MODE[] = "entry";
constexpr unsigned long RELAY_SECONDS = 5;

// MFRC522 wiring for ESP32.
constexpr uint8_t SS_PIN = 5;
constexpr uint8_t RST_PIN = 22;

MFRC522 rfid(SS_PIN, RST_PIN);
unsigned long lastHeartbeatAt = 0;
constexpr unsigned long HEARTBEAT_INTERVAL_MS = 30000;
constexpr uint8_t RELAY_PIN = 4;

String uidToString(MFRC522::Uid *uid) {
  String value = "";
  for (byte i = 0; i < uid->size; i++) {
    if (uid->uidByte[i] < 0x10) {
      value += "0";
    }
    value += String(uid->uidByte[i], HEX);
  }
  value.toUpperCase();
  return value;
}

void ensureWifi() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.println("Connecting to Wi-Fi...");
  }
  Serial.println("Wi-Fi connected");
}

String postJson(const String &url, const String &payload) {
  ensureWifi();
  HTTPClient http;
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Token", DEVICE_TOKEN);
  int statusCode = http.POST(payload);
  String response = http.getString();

  Serial.print("POST ");
  Serial.print(url);
  Serial.print(" -> ");
  Serial.println(statusCode);
  Serial.println(response);

  http.end();
  return response;
}

void reportEvent(const String &eventType, const String &level, const String &message) {
  String payload = "{";
  payload += "\"esp32_id\":\"" + String(DEVICE_ID) + "\",";
  payload += "\"event_type\":\"" + eventType + "\",";
  payload += "\"level\":\"" + level + "\",";
  payload += "\"message\":\"" + message + "\"";
  payload += "}";
  postJson(String(API_BASE) + "/api/device/event", payload);
}

void sendHeartbeat() {
  String payload = "{";
  payload += "\"esp32_id\":\"" + String(DEVICE_ID) + "\",";
  payload += "\"name\":\"" + String(DEVICE_NAME) + "\",";
  payload += "\"location\":\"" + String(DEVICE_LOCATION) + "\",";
  payload += "\"reader_mode\":\"" + String(READER_MODE) + "\",";
  payload += "\"relay_seconds\":";
  payload += String(RELAY_SECONDS);
  payload += ",";
  payload += "\"status\":\"online\"";
  payload += "}";

  postJson(String(API_BASE) + "/api/esp32/heartbeat", payload);
}

void sendScan(const String &uid) {
  String payload = "{";
  payload += "\"rfid_uid\":\"" + uid + "\",";
  payload += "\"esp32_id\":\"" + String(DEVICE_ID) + "\",";
  payload += "\"event_type\":\"auto\"";
  payload += "}";

  postJson(String(API_BASE) + "/api/rfid/scan", payload);
}

void pulseRelay(unsigned long seconds) {
  Serial.println("Pulsing relay");
  digitalWrite(RELAY_PIN, HIGH);
  delay(seconds * 1000);
  digitalWrite(RELAY_PIN, LOW);
}

void pollCommands() {
  String payload = "{";
  payload += "\"esp32_id\":\"" + String(DEVICE_ID) + "\"";
  payload += "}";

  String response = postJson(String(API_BASE) + "/api/device/poll", payload);
  if (response.indexOf("\"command\": null") >= 0 || response.indexOf("\"command\":null") >= 0) {
    return;
  }

  int idIndex = response.indexOf("\"id\":");
  int secondsIndex = response.indexOf("\"seconds\":");
  if (idIndex < 0 || secondsIndex < 0) {
    return;
  }

  int commandId = response.substring(idIndex + 5).toInt();
  int seconds = response.substring(secondsIndex + 10).toInt();
  if (seconds <= 0) {
    reportEvent("command_parse", "warn", "Invalid relay duration in command payload");
    seconds = 1;
  }

  pulseRelay(seconds);

  String ackPayload = "{";
  ackPayload += "\"command_id\":";
  ackPayload += String(commandId);
  ackPayload += "}";
  postJson(String(API_BASE) + "/api/device/ack", ackPayload);
}

void setup() {
  Serial.begin(115200);
  SPI.begin();
  rfid.PCD_Init();
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW);
  ensureWifi();
  sendHeartbeat();
}

void loop() {
  ensureWifi();

  if (millis() - lastHeartbeatAt >= HEARTBEAT_INTERVAL_MS) {
    sendHeartbeat();
    lastHeartbeatAt = millis();
  }

  pollCommands();

  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) {
    delay(100);
    return;
  }

  String uid = uidToString(&rfid.uid);
  Serial.print("Card scanned: ");
  Serial.println(uid);
  sendScan(uid);

  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
  delay(1200);
}
