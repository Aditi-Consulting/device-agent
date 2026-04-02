"""LangGraph state definition for the Device Agent workflow."""

from __future__ import annotations

from typing import Any, TypedDict


class DeviceAgentState(TypedDict):
    # ── Existing core fields ──
    alert_id: int
    alert_name: str           # Raw alert text from ticket column
    imei: str                 # 16-digit IMEI extracted by LLM
    eligible: bool            # Whether device is eligible for unlock
    result: str               # Final unlock status message
    error: str                # Error message if anything fails

    # ── Alert data from DB ──
    alerts: list              # Full alert row(s) from DB as list of dicts
    source: str               # Alert source: 'ServiceNow', 'Splunk', etc.

    # ── Resolution tracking ──
    resolutions: list         # Matched resolutions from DB
    resolution_source: str    # 'database' | 'needs_generation'
    db_resolution_id: int     # ID of resolution from DB (if found)
    processed: list           # Processed alert-resolution pairs

    # ── Task agent execution tracking ──
    execution_summary: list          # In-memory list of node execution records
    current_step: int                # Auto-incremented by capture_node_execution
    task_agent_execution_id: int     # ID from task_agent_execution_summary table
    task_agent_alert_id: int         # Alert ID being processed
    task_agent_start_time: str       # ISO timestamp of workflow start
    workflow_type: str               # Always "infrastructure" for device agent

    # ── Verification & root cause ──
    root_cause: str
    evidence: str
    verification_status: str
    verification_message: str
    confidence_score: float

    # ── Email ──
    mail_sent: bool
    email_status: str
    email_content: str
    email_details: dict

    # ── Internal flags ──
    task_agent_finalized: bool
    task_agent_execution_status: str
    alert_update_status: str


# Backwards-compatible alias
AgentState = DeviceAgentState
