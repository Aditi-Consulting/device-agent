"""Node: sends workflow completion email and updates alert status."""

from __future__ import annotations

import json
import logging
import re

from src.device_agent.store.db import update_alert_status
from src.device_agent.tools.send_mail_tool import send_email as send_mail_tool
from src.device_agent.utility.summary_tracker import get_execution_summary_text

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Email content preparation
# ─────────────────────────────────────────────────────────────────

def _call_llm_for_email(prompt: str) -> dict:
    """Use the LLM to generate email JSON {subject, body}."""
    try:
        from src.device_agent.utility.llm import get_llm
        llm = get_llm(temperature=0.1)
        response = llm.invoke(prompt)
        text = response.content if hasattr(response, "content") else str(response)
        try:
            return json.loads(text)
        except Exception:
            m = re.search(r"(\{(?:.|\n)*})", text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(1))
                except Exception:
                    pass
        return {"__error__": "JSON parse failed", "raw_text": text}
    except Exception as exc:
        logger.exception("LLM email generation failed")
        return {"__error__": str(exc)}


def _prepare_email_content(state: dict) -> dict:
    """Build subject + body for the workflow completion email."""
    alerts = state.get("alerts") or []
    alert = alerts[0] if alerts else {}

    ticket_id = alert.get("ticket_id", "unknown")
    source = alert.get("source", "ServiceNow")
    severity = alert.get("severity", "unknown")
    issue_type = alert.get("issue_type", "unknown")
    ticket = alert.get("ticket", "No description")

    imei = state.get("imei", "Not extracted")
    eligible = state.get("eligible", False)
    device_result = state.get("result", "No result")
    error = state.get("error", "None")

    # Prefer DB-formatted execution summary (set by summary_tracker after DB persist)
    # Fall back to in-memory summary if not yet available
    execution_summary = (
        state.get("execution_summary_text")
        or get_execution_summary_text(state)
    )

    # ── Build resolution steps block ──
    resolutions = state.get("resolutions") or []
    resolution_steps = ""
    if resolutions:
        action_steps = resolutions[0].get("action_steps", {})
        steps = (
            action_steps.get("steps", [])
            if isinstance(action_steps, dict)
            else []
        )
        if steps:
            resolution_steps = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(steps))

    # ── Resolution note ──
    resolution_source = state.get("resolution_source", "")
    db_resolution_id = state.get("db_resolution_id")
    if resolution_source == "database" and db_resolution_id:
        resolution_note = f"Used existing resolution from DB (ID: {db_resolution_id})"
    elif db_resolution_id:
        resolution_note = f"New resolution stored to DB (ID: {db_resolution_id}) for future use"
    else:
        resolution_note = "No resolution found or stored"

    prompt = f"""
Create a professional email notification for a device unlock workflow.

ALERT DETAILS:
- Ticket ID   : {ticket_id}
- Source      : {source}
- Severity    : {severity}
- Issue Type  : {issue_type}
- Description : {ticket}

DEVICE WORKFLOW RESULTS:
- IMEI Extracted : {imei}
- Device Eligible: {eligible}
- Unlock Result  : {device_result}
- Error          : {error}
- Resolution     : {resolution_note}

RESOLUTION STEPS EXECUTED:
{resolution_steps if resolution_steps else "  (See execution summary below)"}

WORKFLOW EXECUTION SUMMARY:
{execution_summary}

Write a clear, professional email that includes:
1. Subject: concise summary of the outcome
2. Body:
   - Brief intro (what was processed and from which source)
   - Device details table (IMEI, eligibility, unlock outcome)
   - Numbered list of steps executed
   - Resolution info (from DB or newly stored)
   - Any errors encountered
   - Professional closing

Respond ONLY with valid JSON:
{{
    "subject": "...",
    "body": "..."
}}
""".strip()

    email_content = _call_llm_for_email(prompt)

    if "__error__" in email_content:
        # ── Static fallback ──
        status_word = "SUCCEEDED" if "unlock" in str(device_result).lower() else "FAILED"
        subject = f"[Device Agent] Alert {ticket_id} — Unlock {status_word} [{severity.upper()}]"
        body = f"""Device Agent Workflow Notification
{'=' * 50}

Ticket ID  : {ticket_id}
Source     : {source}
Severity   : {severity}
Issue Type : {issue_type}

Device Details
--------------
IMEI       : {imei}
Eligible   : {eligible}
Result     : {device_result}
Error      : {error}
Resolution : {resolution_note}

Execution Summary
-----------------
{execution_summary}

Original Alert
--------------
{ticket}
"""
        return {"subject": subject, "body": body}

    return email_content


# ─────────────────────────────────────────────────────────────────
# Node entry point
# ─────────────────────────────────────────────────────────────────

def send_email_node(state: dict) -> dict:
    """LangGraph node: send workflow completion email + update alert status."""
    logger.info("send_email_node — preparing notification email")

    try:
        email_content = _prepare_email_content(state)
        subject = email_content.get("subject", "Device Agent Workflow Notification")
        body = email_content.get("body", "Please review the device agent workflow results.")

        result = send_mail_tool({"subject": subject, "body": body})
        logger.info("send_mail_tool result: %s", result)

        email_status = "sent" if result.get("status") == "success" else "failed"
        state["email_status"] = email_status
        state["email_details"] = result

        # ── Mark alert as resolved based on workflow outcome only ──
        # Alert status update is independent of email delivery success.
        # If workflow completed (verified/completed), alert is resolved
        # regardless of whether the notification email was sent.
        verification_status = state.get("verification_status", "")
        alerts = state.get("alerts") or []

        if alerts and verification_status in ("verified", "completed"):
            alert_id = alerts[0].get("id")
            if alert_id:
                update_alert_status(alert_id, "resolved")
                state["alert_update_status"] = "resolved"
                logger.info("Alert %s marked as resolved (email_status=%s)", alert_id, email_status)

        return state

    except Exception as exc:
        logger.exception("send_email_node failed")
        state["email_status"] = "error"
        state["email_details"] = {"error": str(exc)}
        return state


def run(state: dict) -> dict:
    """Entry point called by summary_tracker.finalize_workflow_and_send_email."""
    return send_email_node(state)

