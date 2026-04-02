"""Node — checks device unlock eligibility via the Device API."""

from __future__ import annotations

import logging

from src.device_agent.state import AgentState
from src.device_agent.tools.device_api_client import DeviceAPIError, check_eligibility
from src.device_agent.utility.summary_tracker import capture_node_execution

logger = logging.getLogger(__name__)


def check_unlock_eligibility_node(state: AgentState) -> AgentState:
    """Query the eligibility API and update state."""
    imei = state["imei"]

    print("=" * 60)
    print("🔍 NODE: check_unlock_eligibility — STARTING")
    print(f"   imei: {imei}")
    print("=" * 60)

    logger.info("Checking eligibility for IMEI: %s", imei)

    try:
        eligible = check_eligibility(imei)
        logger.info("IMEI %s eligible=%s", imei, eligible)
        state = {**state, "eligible": eligible, "error": ""}

        if eligible:
            result_msg = f"Device with IMEI {imei} is eligible for unlock"
            state = capture_node_execution(
                state, "check_unlock_eligibility", result=result_msg
            )
        else:
            result_msg = f"Device with IMEI {imei} is NOT eligible for unlock"
            state = capture_node_execution(
                state,
                "check_unlock_eligibility",
                result=result_msg,
                status="warning",
            )
        print(
            f"🔍 NODE: check_unlock_eligibility — COMPLETED | eligible={eligible}"
        )
        return state

    except DeviceAPIError as exc:
        logger.error("Eligibility check failed: %s", exc)
        state = {**state, "eligible": False, "error": str(exc)}
        state = capture_node_execution(
            state, "check_unlock_eligibility", error=str(exc)
        )
        print(f"🔍 NODE: check_unlock_eligibility — ERROR | {exc}")
        return state
