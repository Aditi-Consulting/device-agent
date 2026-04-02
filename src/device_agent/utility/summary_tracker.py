"""
Utility module for tracking and managing node execution summaries.
Device Agent workflow — stores progress to DB and finalizes with email.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from src.device_agent.store.db import (
    finalize_task_agent_execution,
    get_task_agent_execution_for_email,
    initialize_task_agent_execution,
    store_node_execution_summary,
    update_task_agent_execution,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────

def initialize_execution_tracking(
    state: Dict[str, Any],
    alert_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Initialize execution tracking at the start of a workflow.

    Creates the row in task_agent_execution_summary and seeds state fields.
    """
    if alert_id is None:
        alerts = state.get("alerts", [])
        alert_id = alerts[0].get("id", 1) if alerts else 1

    execution_id = initialize_task_agent_execution(alert_id)

    return {
        **state,
        "execution_summary": [],
        "current_step": 0,
        "task_agent_execution_id": execution_id,
        "task_agent_alert_id": alert_id,
        "task_agent_start_time": datetime.now().isoformat(),
    }


def capture_node_execution(
    state: Dict[str, Any],
    node_name: str,
    result: Any = None,
    error: str = None,
    status: str = None,
) -> Dict[str, Any]:
    """Capture execution summary for a node.

    Stores the record in both the in-memory state list and the database.

    Args:
        state:     Current workflow state.
        node_name: Name of the executed node.
        result:    Result from node execution (optional).
        error:     Error message if node failed (optional).
        status:    Explicit status override ('success', 'warning', 'error').

    Returns:
        Updated state with execution summary appended.
    """
    try:
        current_step = state.get("current_step", 0)

        if "execution_summary" not in state or state["execution_summary"] is None:
            state["execution_summary"] = []

        # ── Derive status and summary ──
        if error:
            derived_status = "error"
            result_summary = f"Error in {node_name}: {error}"
            error_message = error
            serialized = f"Error: {error}"
        elif result is not None:
            derived_status = status or "success"
            result_summary = _generate_result_summary(node_name, result)
            error_message = None
            serialized = _serialize_result(result)
        else:
            derived_status = status or "warning"
            result_summary = f"{node_name} executed but no result available"
            error_message = None
            serialized = f"{node_name} completed successfully"

        execution_record = {
            "node_name": node_name,
            "execution_order": current_step,
            "status": derived_status,
            "result_summary": result_summary,
            "error_message": error_message,
            "full_result": serialized,
        }

        state["execution_summary"].append(execution_record)
        state["current_step"] = current_step + 1

        # ── Persist to DB ──
        alert_id = _get_alert_id_from_state(state)
        if alert_id:
            store_node_execution_summary(
                alert_id=alert_id,
                node_name=node_name,
                execution_order=current_step,
                status=derived_status,
                result_summary=result_summary,
                full_result=serialized,
                error_message=error_message,
            )
            logger.debug(
                "Captured '%s' — status=%s alert_id=%s", node_name, derived_status, alert_id
            )

        return state

    except Exception as exc:
        logger.error("capture_node_execution failed for '%s': %s", node_name, exc)
        return state


def get_execution_summary_text(state: Dict[str, Any]) -> str:
    """Return a formatted plain-text summary of all captured node executions."""
    execution_summary = state.get("execution_summary") or []
    if not execution_summary:
        return "No execution summary available."

    lines = ["=== Execution Summary ==="]
    for node in execution_summary:
        icon = "✓" if node.get("status") == "success" else "✗"
        lines.append(f"{node.get('execution_order')}. {icon} {node.get('node_name')}")
        lines.append(f"   Status : {node.get('status', 'unknown').upper()}")
        lines.append(f"   Result : {node.get('result_summary', 'No summary')}")
        if node.get("error_message"):
            lines.append(f"   Error  : {node['error_message']}")
        lines.append("")
    return "\n".join(lines)


def finalize_workflow_and_send_email(state: Dict[str, Any]) -> Dict[str, Any]:
    """Finalize the workflow: persist full summary to DB and send email.

    Steps:
      1. Build full_result JSON
      2. Persist to task_agent_execution_summary
      3. Store resolution if first time (needs_generation)
      4. Send notification email
    """
    execution_id = state.get("task_agent_execution_id")
    alert_id = state.get("task_agent_alert_id")
    execution_summary = state.get("execution_summary") or []
    workflow_type = state.get("workflow_type", "infrastructure")

    logger.info(
        "Finalizing workflow — execution_id=%s alert_id=%s", execution_id, alert_id
    )

    # ── Recover missing IDs ──
    if not alert_id:
        alerts = state.get("alerts") or []
        if alerts:
            alert_id = alerts[0].get("id")
            state["task_agent_alert_id"] = alert_id

    if not execution_id and alert_id:
        execution_id = initialize_task_agent_execution(alert_id)
        state["task_agent_execution_id"] = execution_id

    if not execution_id or not alert_id:
        logger.error("Cannot finalize — missing execution_id or alert_id")
        return {**state, "error": "Cannot finalize: missing execution tracking IDs"}

    # ── Gather context ──
    alerts = state.get("alerts") or []
    alert = alerts[0] if alerts else {}

    root_cause = state.get("root_cause") or "No root cause identified"
    evidence = state.get("evidence") or ""
    verification_status = state.get("verification_status") or "unknown"
    verification_message = state.get("verification_message") or ""

    # ── Confidence score ──
    confidence_score = state.get("confidence_score")
    if confidence_score is None:
        if "unlock" in str(state.get("result", "")).lower():
            confidence_score = 85.0
        elif state.get("eligible"):
            confidence_score = 70.0
        elif state.get("imei"):
            confidence_score = 50.0
        else:
            confidence_score = 15.0
    try:
        confidence_score = float(confidence_score)
    except Exception:
        confidence_score = 15.0
    confidence_score = max(15.0, min(confidence_score, 100.0))

    # ── Final workflow status ──
    failed_nodes = [n for n in execution_summary if n.get("status") == "error"]
    final_status = "failed" if (failed_nodes or state.get("error")) else "completed"

    # ── Build full_result ──
    issue_type = alert.get("issue_type") or alert.get("classification") or "device_unlock"
    severity = alert.get("severity") or "unknown"

    full_result = {
        "task_agent_summary": {
            "total_steps": len(execution_summary),
            "completed_steps": len([n for n in execution_summary if n.get("status") == "success"]),
            "failed_steps": len(failed_nodes),
            "workflow_status": final_status,
            "workflow_type": workflow_type,
            "issue_type": issue_type,
            "severity": severity,
            "final_result": state.get("result", f"{workflow_type.title()} workflow completed"),
            "start_time": state.get("task_agent_start_time"),
            "end_time": datetime.now().isoformat(),
            "root_cause": root_cause,
            "evidence": evidence,
            "verification_status": verification_status,
            "confidence_score": confidence_score,
        },
        "execution_details": {
            "imei": state.get("imei", ""),
            "eligible": state.get("eligible", False),
            "device_result": state.get("result", ""),
            "verification_status": verification_status,
            "verification_message": verification_message,
            "root_cause": root_cause,
            "evidence": evidence,
            "source": alert.get("source", "ServiceNow"),
        },
        "llm_analysis": {
            "issue_type": issue_type,
            "severity": severity,
            "verification_status": verification_status,
            "root_cause": root_cause,
            "evidence": evidence,
        },
    }

    try:
        update_task_agent_execution(
            execution_id, execution_summary, full_result, final_status, confidence_score
        )
        finalize_task_agent_execution(execution_id, final_status)
        logger.info(
            "Execution id=%s finalized as '%s'", execution_id, final_status
        )

        # ── Store resolution if this was the first time (needs_generation) ──
        if final_status == "completed" and state.get("resolution_source") == "needs_generation":
            _store_auto_resolution(state, alert)

        # ── Get formatted execution summary from DB for email ──
        # This reads the fully persisted node records from DB and formats
        # them into a human-readable string for inclusion in the email body.
        execution_summary_text = get_task_agent_execution_for_email(alert_id, workflow_type)

        # ── Send email ──
        # Lazy import to avoid circular dependency at module load time
        import importlib
        send_email_module = importlib.import_module(
            "src.device_agent.nodes.send_email_node"
        )
        send_email_run = send_email_module.run

        email_state = {
            **state,
            "mail_sent": True,
            "email_content": execution_summary_text,
            "execution_summary_text": execution_summary_text,
            "verification_status": "completed",
            "verification_message": (
                f"{workflow_type.title()} workflow {final_status}: "
                f"{len(execution_summary)} steps executed"
            ),
        }
        final_state = send_email_run(email_state)
        logger.info("Email sent for alert_id=%s", alert_id)

        return {
            **final_state,
            "task_agent_finalized": True,
            "task_agent_execution_status": final_status,
        }

    except Exception as exc:
        logger.exception("finalize_workflow_and_send_email failed")
        return {**state, "error": f"Failed to finalize workflow: {exc}"}


# ─────────────────────────────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────────────────────────────

def _store_auto_resolution(state: Dict[str, Any], alert: dict) -> None:
    """Auto-store a resolution record for future alerts with the same issue_type."""
    from src.device_agent.store.db import fetch_resolution, save_resolution

    issue_type = alert.get("issue_type")
    if not issue_type:
        logger.warning("No issue_type on alert — skipping auto resolution storage")
        return

    # Race condition safety: re-check before inserting
    existing = fetch_resolution(issue_type)
    if existing:
        logger.info(
            "Resolution already exists for issue_type='%s' (id=%s) — skipping",
            issue_type, existing.get("id"),
        )
        state["db_resolution_id"] = existing.get("id")
        return

    action_steps = {
        "steps": [
            "1. Extract the IMEI from ticket.",
         "2. Verify whether the extracted IMEI is eligible for device unlock.",
         "3. If the device is eligible to unlock, proceed with the device unlock operation",
        ],
        "agent": "device_agent",
        "source": alert.get("source", "ServiceNow"),
        "auto_generated": True,
    }

    resolution_id = save_resolution(
        issue_type=issue_type,
        description=(
            f"Auto-generated resolution for '{issue_type}' "
            "from Device Agent workflow"
        ),
        action_type="device_unlock",
        action_steps=action_steps,
    )
    state["db_resolution_id"] = resolution_id
    logger.info(
        "Stored new auto-resolution id=%s for issue_type='%s'", resolution_id, issue_type
    )


def _generate_result_summary(node_name: str, result: Any) -> str:
    try:
        if isinstance(result, str):
            truncated = result[:200] + "..." if len(result) > 200 else result
            return f"{node_name} completed: {truncated}"
        elif isinstance(result, dict):
            if "status" in result:
                return f"{node_name} completed with status: {result['status']}"
            if "message" in result:
                return f"{node_name} completed: {result['message']}"
            return f"{node_name} completed successfully"
        elif isinstance(result, list):
            return f"{node_name} completed: Found {len(result)} items"
        return f"{node_name} completed successfully"
    except Exception as exc:
        return f"{node_name} completed (summary error: {exc})"


def _serialize_result(result: Any) -> Any:
    try:
        if isinstance(result, (str, int, float, bool, type(None))):
            return result
        if isinstance(result, (dict, list)):
            return result
        return str(result)
    except Exception:
        return str(result)


def _get_alert_id_from_state(state: Dict[str, Any]) -> Optional[int]:
    try:
        # Prefer alerts[0].id
        alerts = state.get("alerts") or []
        if alerts and isinstance(alerts[0], dict):
            aid = alerts[0].get("id")
            if aid:
                return int(aid)
        # Fall back to task_agent_alert_id
        ta_id = state.get("task_agent_alert_id")
        if ta_id:
            return int(ta_id)
        return None
    except Exception as exc:
        logger.error("_get_alert_id_from_state error: %s", exc)
        return None

