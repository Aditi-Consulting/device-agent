"""Node: uses LLM to extract IMEI from alert name."""

from __future__ import annotations

import logging
import re

from src.device_agent.state import DeviceAgentState as AgentState
from src.device_agent.utility.llm import get_llm
from src.device_agent.utility.prompt import IMEI_EXTRACTION_PROMPT
from src.device_agent.utility.summary_tracker import capture_node_execution

logger = logging.getLogger(__name__)

_IMEI_PATTERN = re.compile(r"^\d{16}$")
_NODE_NAME = "parse_alert_for_IMEI"


def parse_alert_node(state: AgentState) -> AgentState:
    """Extract IMEI from alert_name using LLM and populate state['imei']."""
    alert_name = state.get("alert_name", "").strip()

    print("=" * 60)
    print("🔍 NODE: parse_alert_for_imei — STARTING")
    print(f"   alert_name: {alert_name[:120] if alert_name else 'EMPTY'}")
    print("=" * 60)

    logger.info("Extracting IMEI from alert: %s", alert_name)

    if not alert_name:
        logger.warning("alert_name is empty — cannot extract IMEI.")
        state = {**state, "imei": "", "error": "Alert message is empty."}
        state = capture_node_execution(state, _NODE_NAME, error="Alert message is empty.")
        return state

    try:
        llm = get_llm(temperature=0.0)
        response = llm.invoke(IMEI_EXTRACTION_PROMPT.format(alert_name=alert_name))
        extracted = response.content.strip()
        logger.debug("LLM extracted: '%s'", extracted)

        if not _IMEI_PATTERN.match(extracted):
            logger.warning(
                "No valid 16-digit IMEI in alert: %s — LLM returned: %s",
                alert_name, extracted,
            )
            state = {
                **state,
                "imei": "",
                "error": f"Could not extract a valid IMEI from alert: '{alert_name}'",
            }
            state = capture_node_execution(state, _NODE_NAME, error=state["error"])
            return state

        logger.info("IMEI extracted successfully: %s", extracted)
        state = {**state, "imei": extracted, "error": ""}
        state = capture_node_execution(
            state, _NODE_NAME,
            result=f"Successfully extracted IMEI: {extracted} from alert text",
        )
        print(f"🔍 NODE: parse_alert_for_imei — COMPLETED | imei={extracted}")
        return state

    except Exception as exc:
        logger.exception("LLM extraction failed for alert: %s", alert_name)
        state = {**state, "imei": "", "error": f"LLM extraction error: {exc}"}
        state = capture_node_execution(state, _NODE_NAME, error=str(exc))
        return state
