"""FastAPI route definitions for the Device Agent."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.device_agent.graph import build_graph

logger = logging.getLogger(__name__)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────
# Response schema
# ─────────────────────────────────────────────────────────────────

class UnlockResponse(BaseModel):
    success: bool
    alert_id: int
    alert_name: str
    imei: str
    eligible: bool
    result: str
    error: str
    workflow_type: str
    workflow_status: str
    email_sent: bool
    confidence_score: float


# ─────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────

@router.post(
    "/unlock",
    response_model=UnlockResponse,
    summary="Trigger device unlock workflow from alert ID",
    description=(
        "Accepts an alert_id as a query parameter. "
        "Fetches the alert from DB, validates source=ServiceNow, "
        "extracts IMEI via LLM, checks eligibility, unlocks if eligible, "
        "persists execution summary and sends email. "
        "Always returns the same response shape."
    ),
)
async def unlock_device(
    alertId: int = Query(..., description="ID of the alert record in the database"),
) -> JSONResponse:
    logger.info("Unlock request received — alertId=%s", alertId)

    alert_id = alertId

    try:
        graph = build_graph()

        initial_state = {
            # Core
            "alert_id": alert_id,
            "alert_name": "",
            "imei": "",
            "eligible": False,
            "result": "",
            "error": "",
            # Alert / resolution
            "alerts": [],
            "source": "",
            "resolutions": [],
            "resolution_source": "",
            "db_resolution_id": 0,
            "processed": [],
            # Execution tracking
            "execution_summary": [],
            "current_step": 0,
            "task_agent_execution_id": 0,
            "task_agent_alert_id": 0,
            "task_agent_start_time": "",
            "workflow_type": "infrastructure",
            # Verification
            "root_cause": "",
            "evidence": "",
            "verification_status": "",
            "verification_message": "",
            "confidence_score": 0.0,
            # Email
            "mail_sent": False,
            "email_status": "",
            "email_content": "",
            "email_details": {},
            # Flags
            "task_agent_finalized": False,
            "task_agent_execution_status": "",
            "alert_update_status": "",
        }

        final_state = graph.invoke(initial_state)

        success = (
            bool(final_state.get("result"))
            and not final_state.get("error")
            and final_state.get("task_agent_execution_status") != "failed"
        )

        return JSONResponse(
            status_code=200,
            content=UnlockResponse(
                success=success,
                alert_id=alert_id,
                alert_name=final_state.get("alert_name", ""),
                imei=final_state.get("imei", ""),
                eligible=final_state.get("eligible", False),
                result=final_state.get("result", ""),
                error=final_state.get("error", ""),
                workflow_type=final_state.get("workflow_type", "infrastructure"),
                workflow_status=final_state.get("task_agent_execution_status", "unknown"),
                email_sent=final_state.get("email_status") == "sent",
                confidence_score=float(final_state.get("confidence_score") or 0.0),
            ).model_dump(),
        )

    except Exception as exc:
        logger.exception("Workflow execution failed for alert_id=%s", alert_id)
        return JSONResponse(
            status_code=500,
            content=UnlockResponse(
                success=False,
                alert_id=alert_id,
                alert_name="",
                imei="",
                eligible=False,
                result="",
                error=f"Workflow execution failed: {exc}",
                workflow_type="infrastructure",
                workflow_status="failed",
                email_sent=False,
                confidence_score=0.0,
            ).model_dump(),
        )
