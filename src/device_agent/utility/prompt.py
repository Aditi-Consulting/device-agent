"""Prompts for the Device Agent."""

from __future__ import annotations

IMEI_EXTRACTION_PROMPT = """
Extract the IMEI number from the following alert message.

Rules:
- An IMEI is strictly a 16-digit numeric string.
- Return ONLY the 16 digits — no letters, no spaces, no special characters.
- If no valid 16-digit IMEI is found, respond with exactly: IMEI_NOT_FOUND

Examples:
  Alert: "Unlock the Device: IMEI9988463534567893"
  IMEI: 9988463534567893

  Alert: "Device unlock requested for unit IMEI1234567890123456 in region US"
  IMEI: 1234567890123456

Alert: {alert_name}
IMEI:
""".strip()

