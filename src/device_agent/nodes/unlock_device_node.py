"""Node — unlocks the device via the Device API."""

from __future__ import annotations

import logging

from src.device_agent.state import DeviceAgentState as AgentState
from src.device_agent.tools.device_api_client import DeviceAPIError, unlock_device
from src.device_agent.utility.summary_tracker import capture_node_execution

logger = logging.getLogger(__name__)


def unlock_device_node(state: AgentState) -> AgentState:
    """Call the unlock API and capture the result."""
    imei = state["imei"]

    print("=" * 60)
    print("🔍 NODE: unlock_device — STARTING")
    print(f"   imei: {imei}")
    print(f"   eligible: {state.get('eligible')}")
    print("=" * 60)

    logger.info("Unlocking device for IMEI: %s", imei)

    try:
        status = unlock_device(imei)
        logger.info("Unlock result for IMEI %s: %s", imei, status)
        state = {**state, "result": status, "error": ""}

        if "unlock" in str(status).lower():
            result_msg = f"Device {imei} unlocked successfully: {status}"
            state = capture_node_execution(state, "unlock_device", result=result_msg)
        else:
            result_msg = f"Device unlock result for {imei}: {status}"
            state = capture_node_execution(state, "unlock_device", result=result_msg)
        print(f"🔍 NODE: unlock_device — COMPLETED | result={status}")
        return state

    except DeviceAPIError as exc:
        logger.error("Unlock failed: %s", exc)
        state = {**state, "result": "failed", "error": str(exc)}
        state = capture_node_execution(state, "unlock_device", error=str(exc))
        print(f"🔍 NODE: unlock_device — ERROR | {exc}")
        return state
