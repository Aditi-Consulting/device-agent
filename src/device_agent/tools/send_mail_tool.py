"""SMTP email sender tool for the Device Agent."""

from __future__ import annotations

import json
import logging
import os
import smtplib
from email.mime.text import MIMEText

from dotenv import load_dotenv

from src.device_agent.utility.config import utility_config

load_dotenv()

logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
EMAIL_USER = os.getenv("EMAIL_USER", "")
EMAIL_PASS = os.getenv("EMAIL_PASS", "")
STATIC_FROM_ADDRESS = EMAIL_USER


def send_email(action_input) -> dict:
    """Send an email notification.

    Accepts:
      - dict: {"subject": "...", "body": "...", "to": "a@b.com,c@d.com"}
      - str : JSON string of the above dict

    'to' is optional — defaults to STATIC_TO_ADDRESSES.
    """
    logger.debug("send_email called with type=%s", type(action_input).__name__)

    # ── Normalise input to dict ──
    if isinstance(action_input, str):
        try:
            action_input = json.loads(action_input)
        except Exception:
            try:
                import ast
                action_input = ast.literal_eval(action_input)
            except Exception:
                pass

    subject = body = ""
    to_addresses = None

    if isinstance(action_input, dict):
        normalised = {k.lower(): v for k, v in action_input.items()}
        subject = str(normalised.get("subject", ""))
        body = str(normalised.get("body", ""))
        to_addresses = normalised.get("to")
    else:
        for pair in str(action_input).split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                k = k.strip().lower()
                v = v.strip().strip("'\"")
                if k == "subject":
                    subject = v
                elif k == "body":
                    body = v
                elif k == "to":
                    to_addresses = v

    if not subject or not body:
        logger.warning("send_email: missing subject or body")
        return {"status": "error", "error": "Missing required fields: subject, body"}

    # ── Resolve recipient list ──
    if to_addresses:
        if isinstance(to_addresses, list):
            to_list = [e.strip() for e in to_addresses if e.strip()]
        else:
            to_list = [e.strip() for e in str(to_addresses).split(",") if e.strip()]
    else:
        to_list = utility_config.email_recipients

    logger.info("Sending email to: %s", to_list)

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = STATIC_FROM_ADDRESS
    msg["To"] = ", ".join(to_list)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(STATIC_FROM_ADDRESS, to_list, msg.as_string())
        logger.info("Email sent successfully to %s", to_list)
        return {"status": "success", "recipients": to_list}
    except Exception as exc:
        logger.exception("Failed to send email")
        return {"status": "error", "error": str(exc)}

