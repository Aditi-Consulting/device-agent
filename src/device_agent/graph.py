"""LangGraph workflow definition for the Device Agent."""

from __future__ import annotations

import logging

from langgraph.graph import END, StateGraph

from src.device_agent.nodes.check_eligibility_node import (
    check_unlock_eligibility_node,
)
from src.device_agent.nodes.parse_alert_node import parse_alert_node
from src.device_agent.nodes.unlock_device_node import unlock_device_node
from src.device_agent.state import DeviceAgentState
from src.device_agent.store.db import fetch_alert_by_id, fetch_resolution
from src.device_agent.utility.summary_tracker import (
    capture_node_execution,
    finalize_workflow_and_send_email,
    initialize_execution_tracking,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Node: read_from_db
# ─────────────────────────────────────────────────────────────────

def read_from_db_node(state: dict) -> dict:
    """Node 1 — Fetch alert from DB, check source, initialize tracking.

    - Fetches alert by alert_id (agent_name + status filters applied in DB layer)
    - Checks source == 'ServiceNow' → graceful warning exit if not
    - Loads matching resolution by issue_type (optional)
    - Initializes task_agent_execution_summary record
    """
    logger.info("read_from_db_node — alert_id=%s", state.get("alert_id"))
    alert_id = state.get("alert_id")

    try:
        alert = fetch_alert_by_id(alert_id)

        if not alert:
            msg = (
                f"No active Device Agent alert found for alert_id={alert_id}. "
                "Alert must have agent_name='Device Agent' and "
                "status IN ('failed','in_progress')."
            )
            logger.warning(msg)
            state["alerts"] = []
            state["error"] = msg
            state = initialize_execution_tracking(state, alert_id)
            state = capture_node_execution(state, "read_from_db", error=msg)
            return state

        # ── Source check — graceful warning, NOT an error ──
        source = alert.get("source", "")
        if source.replace(" ", "").strip().lower() != "servicenow":
            msg = (
                f"Alert source is '{source}', not 'ServiceNow'. "
                "Skipping Device Agent workflow — alert will be handled by the correct agent."
            )
            logger.warning(msg)
            state["alerts"] = [alert]
            state["source"] = source
            state["alert_name"] = alert.get("ticket", "")
            state["result"] = msg
            state = initialize_execution_tracking(state, alert.get("id", alert_id))
            state = capture_node_execution(
                state, "read_from_db", result=msg, status="warning"
            )
            return state

        # ── Populate state from alert row ──
        state["alerts"] = [alert]
        state["alert_name"] = alert.get("ticket", "")
        state["source"] = source
        state["workflow_type"] = "Service Now"

        # ── Resolution lookup (optional) ──
        issue_type = alert.get("issue_type")
        resolution_note = ""

        if issue_type:
            resolution = fetch_resolution(issue_type)
            if resolution:
                state["resolutions"] = [resolution]
                state["resolution_source"] = "database"
                state["db_resolution_id"] = resolution.get("id")
                resolution_note = f" | Found resolution in DB (ID: {resolution['id']})"
                logger.info(
                    "Resolution found — id=%s issue_type=%s",
                    resolution["id"], issue_type,
                )
            else:
                state["resolutions"] = []
                state["resolution_source"] = "needs_generation"
                resolution_note = " | No existing resolution found — will store after success"
                logger.info("No resolution for issue_type='%s' — will generate after completion", issue_type)
        else:
            state["resolutions"] = []
            state["resolution_source"] = "needs_generation"

        # ── Initialize execution tracking ──
        state = initialize_execution_tracking(state, alert.get("id", alert_id))
        logger.info(
            "Tracking initialized — execution_id=%s alert_id=%s",
            state.get("task_agent_execution_id"),
            state.get("task_agent_alert_id"),
        )

        result_msg = f"Retrieved alert {alert_id} from DB (source=ServiceNow){resolution_note}"
        state = capture_node_execution(state, "read_from_db", result=result_msg)
        return state

    except Exception as exc:
        logger.exception("read_from_db_node failed")
        state["error"] = str(exc)
        try:
            state = capture_node_execution(state, "read_from_db", error=str(exc))
        except Exception:
            pass
        return state


# ─────────────────────────────────────────────────────────────────
# Node: fetch_resolution
# ─────────────────────────────────────────────────────────────────

def fetch_resolution_node(state: dict) -> dict:
    """Node 2 — Report resolution status to UI.

    Resolution was already looked up in read_from_db_node.
    This node makes it visible as a dedicated step in the UI.
    """
    logger.info("fetch_resolution_node — resolution_source=%s", state.get("resolution_source"))

    try:
        alerts = state.get("alerts") or []
        if not alerts:
            state = capture_node_execution(
                state, "fetch_resolution", error="No alerts in state"
            )
            return state

        alert = alerts[0]
        issue_type = alert.get("issue_type", "device_unlock")
        resolution_source = state.get("resolution_source", "needs_generation")

        if resolution_source == "database":
            resolutions = state.get("resolutions") or []
            resolution = resolutions[0] if resolutions else {}
            resolution_id = resolution.get("id")
            action_steps = resolution.get("action_steps", {})

            steps = []
            if isinstance(action_steps, dict) and "steps" in action_steps:
                steps_data = action_steps["steps"]
                if isinstance(steps_data, list):
                    steps = steps_data
            elif isinstance(action_steps, list):
                steps = action_steps

            result = {
                "summary": f"Found existing resolution for '{issue_type}' (ID: {resolution_id})",
                "resolution_steps": [{
                    "issue_type": issue_type,
                    "action_type": resolution.get("action_type"),
                    "resolution_id": resolution_id,
                    "steps": steps,
                }],
                "resolutions_found": 1,
                "needs_generation": 0,
            }
            logger.info("Resolution confirmed from DB — id=%s", resolution_id)
            state = capture_node_execution(state, "fetch_resolution", result=result)

        else:
            result = {
                "summary": f"No resolution found for '{issue_type}'. Proceeding with default workflow.",
                "resolution_steps": None,
                "resolutions_found": 0,
                "needs_generation": 1,
            }
            logger.info("No resolution for '%s' — will store after successful completion", issue_type)
            state = capture_node_execution(
                state, "fetch_resolution", result=result, status="warning"
            )

        return state

    except Exception as exc:
        logger.exception("fetch_resolution_node failed")
        state = capture_node_execution(state, "fetch_resolution", error=str(exc))
        return state


# ─────────────────────────────────────────────────────────────────
# Node: finalize_workflow
# ─────────────────────────────────────────────────────────────────

def finalize_workflow_node(state: dict) -> dict:
    """Final node — capture execution, persist summary, store resolution, send email."""
    logger.info("finalize_workflow_node starting")

    # ── Set verification fields ──
    result_str = str(state.get("result", ""))
    if "unlock" in result_str.lower() and not state.get("error"):
        state["verification_status"] = "completed"
        state["root_cause"] = (
            f"Device IMEI {state.get('imei', 'unknown')} required unlock "
            "via ServiceNow alert"
        )
        state["evidence"] = "Device eligibility confirmed; unlock executed successfully"
    elif state.get("error"):
        state["verification_status"] = "failed"
        state["root_cause"] = state.get("error", "Unknown error during workflow")
        state["evidence"] = ""
    else:
        state["verification_status"] = "completed"
        state["root_cause"] = "Device workflow completed — device not eligible or no action taken"
        state["evidence"] = ""

    state["workflow_type"] = "infrastructure"

    # ── Capture this node ──
    if state.get("error"):
        node_result = f"Workflow completed with error: {state['error']}"
    else:
        node_result = (
            f"Device workflow completed — IMEI={state.get('imei', 'N/A')}, "
            f"Eligible={state.get('eligible', False)}, "
            f"Result={state.get('result', 'N/A')}"
        )
    state = capture_node_execution(state, "finalize_workflow", result=node_result)

    # ── Persist + email ──
    final_state = finalize_workflow_and_send_email(state)
    logger.info("finalize_workflow_node done")
    return final_state


# ─────────────────────────────────────────────────────────────────
# Conditional routing
# ─────────────────────────────────────────────────────────────────

def _after_read_from_db(state: dict) -> str:
    """Route after read_from_db.

    Goes to finalize_workflow if:
      - No alert found (alerts list empty)
      - Alert source is not ServiceNow (graceful skip — result set, not error)
      - Any error occurred during DB fetch
    Otherwise proceeds to fetch_resolution.
    """
    # No alert found at all
    alerts = state.get("alerts") or []
    if not alerts:
        return "finalize_workflow"

    # Source is not ServiceNow — graceful skip (result is set, not error)
    source = state.get("source", "")
    if source.replace(" ", "").strip().lower() != "servicenow":
        return "finalize_workflow"

    # DB fetch or initialization error
    if state.get("error"):
        return "finalize_workflow"

    return "fetch_resolution"


def _after_fetch_resolution(state: dict) -> str:
    return "finalize_workflow" if state.get("error") else "parse_alert_for_imei"


def _after_parse(state: dict) -> str:
    if state.get("error") or not state.get("imei"):
        return "finalize_workflow"
    return "check_unlock_eligibility"


def _after_eligibility(state: dict) -> str:
    if state.get("error") or not state.get("eligible"):
        return "finalize_workflow"
    return "unlock_device"


# ─────────────────────────────────────────────────────────────────
# Graph builder
# ─────────────────────────────────────────────────────────────────

def build_graph():
    """Build and return the compiled Device Agent LangGraph workflow.

    Graph topology::

        [START]
            → read_from_db             (fetch alert + source check + resolution lookup)
            → fetch_resolution         (UI visibility node for resolution status)
            → parse_alert_for_imei     (LLM extracts 16-digit IMEI)
            → check_unlock_eligibility (Device API unlock eligibility check)
            → unlock_device            (Device API unlock call)
            → finalize_workflow        (persist summary + store resolution if new + send email)
            → [END]

    Any node failure routes directly to finalize_workflow.
    """
    graph = StateGraph(DeviceAgentState)

    graph.add_node("read_from_db", read_from_db_node)
    graph.add_node("fetch_resolution", fetch_resolution_node)
    graph.add_node("parse_alert_for_imei", parse_alert_node)
    graph.add_node("check_unlock_eligibility", check_unlock_eligibility_node)
    graph.add_node("unlock_device", unlock_device_node)
    graph.add_node("finalize_workflow", finalize_workflow_node)

    graph.set_entry_point("read_from_db")

    graph.add_conditional_edges("read_from_db", _after_read_from_db)
    graph.add_conditional_edges("fetch_resolution", _after_fetch_resolution)
    graph.add_conditional_edges("parse_alert_for_imei", _after_parse)
    graph.add_conditional_edges("check_unlock_eligibility", _after_eligibility)

    graph.add_edge("unlock_device", "finalize_workflow")
    graph.add_edge("finalize_workflow", END)

    logger.debug("LangGraph workflow compiled")
    return graph.compile()
