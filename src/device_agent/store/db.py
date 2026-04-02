"""Database access layer for Device Agent alerts."""

from __future__ import annotations

import json
import logging
from datetime import datetime

import mysql.connector

from src.device_agent.utility.config import utility_config

logger = logging.getLogger(__name__)

logger.info("DB config: host=%s port=%s", utility_config.db_host, utility_config.db_port)
def get_db_conn():
    """Return a new MySQL connection."""
    return mysql.connector.connect(
        host=utility_config.db_host,
        user=utility_config.db_user,
        password=utility_config.db_password,
        database=utility_config.db_name,
        port=utility_config.db_port,
    )


def ensure_tables() -> None:
    """Ensure all required tables exist in the shared database.

    Called once at application startup from main.py.
    Does NOT create alerts, resolutions, or task_agent_execution_summary
    as those are owned by the shared schema — only creates tables
    specific to per-node execution tracking.
    """
    conn = get_db_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_execution_summary (
                id               INT AUTO_INCREMENT PRIMARY KEY,
                alert_id         INT NOT NULL,
                node_name        VARCHAR(128) NOT NULL,
                execution_order  INT NOT NULL,
                status           ENUM('success', 'error', 'warning') NOT NULL,
                result_summary   TEXT,
                execution_time   DATETIME DEFAULT CURRENT_TIMESTAMP,
                full_result      JSON,
                error_message    TEXT,
                INDEX idx_alert_id       (alert_id),
                INDEX idx_execution_order (execution_order)
            ) ENGINE=InnoDB;
            """
        )
        conn.commit()
        logger.info("ensure_tables: alert_execution_summary ready")
    except Exception:
        logger.exception("ensure_tables failed")
        raise
    finally:
        cursor.close()
        conn.close()


def fetch_alert_by_id(alert_id: int) -> dict | None:
    """Fetch a single alert by ID only.

    No agent_name or status filter — the routing service already sent this
    alert to the correct agent. Source filtering (ServiceNow) is handled
    in read_from_db_node for a graceful warning response.
    """
    conn = get_db_conn()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT * FROM alerts WHERE id = %s",
            (alert_id,),
        )
        return cursor.fetchone()
    except Exception:
        logger.exception("Failed to fetch alert id=%s from DB", alert_id)
        raise
    finally:
        cursor.close()
        conn.close()


def fetch_device_alerts_from_db(alert_id: int = None, limit: int = 1) -> list:
    """Fetch alerts for the Device Agent.

    No agent_name or status filter — trusts the routing layer.
    """
    conn = get_db_conn()
    cursor = conn.cursor(dictionary=True)
    try:
        if alert_id:
            cursor.execute(
                "SELECT * FROM alerts WHERE id = %s",
                (alert_id,),
            )
        else:
            cursor.execute(
                "SELECT * FROM alerts LIMIT %s",
                (limit,),
            )
        return cursor.fetchall()
    except Exception:
        logger.exception("fetch_device_alerts_from_db failed for alert_id=%s", alert_id)
        raise
    finally:
        cursor.close()
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# Resolution functions
# ═══════════════════════════════════════════════════════════════════

def fetch_resolution(issue_type: str) -> dict | None:
    """Fetch a resolution from the resolutions table by issue_type.

    Returns the resolution row as a dict with action_steps parsed from JSON,
    or None if not found.
    """
    conn = get_db_conn()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT id, issue_type, description, action_type, action_steps
            FROM resolutions
            WHERE issue_type = %s
            LIMIT 1
            """,
            (issue_type,),
        )
        resolution = cursor.fetchone()
        if resolution and resolution.get("action_steps"):
            if isinstance(resolution["action_steps"], str):
                try:
                    resolution["action_steps"] = json.loads(resolution["action_steps"])
                except json.JSONDecodeError:
                    logger.warning("Could not parse action_steps JSON for issue_type=%s", issue_type)
                    resolution["action_steps"] = {}
        return resolution
    except Exception:
        logger.exception("Failed to fetch resolution for issue_type=%s", issue_type)
        raise
    finally:
        cursor.close()
        conn.close()


def save_resolution(
    issue_type: str,
    description: str,
    action_type: str,
    action_steps: dict,
) -> int:
    """Insert a new resolution into the resolutions table.

    Returns the ID of the newly created resolution record.
    """
    conn = get_db_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO resolutions
                (issue_type, description, action_type, action_steps, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, 'ACTIVE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (issue_type, description, action_type, json.dumps(action_steps)),
        )
        resolution_id = cursor.lastrowid
        conn.commit()
        logger.info("Saved new resolution id=%s for issue_type=%s", resolution_id, issue_type)
        return resolution_id
    except Exception:
        logger.exception("Failed to save resolution for issue_type=%s", issue_type)
        raise
    finally:
        cursor.close()
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# Alert status
# ═══════════════════════════════════════════════════════════════════

def update_alert_status(alert_id: int, status: str) -> None:
    """Update the status of an alert and set processed_at timestamp."""
    conn = get_db_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE alerts
            SET status = %s, processed_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (status, alert_id),
        )
        conn.commit()
        logger.info("Alert id=%s status updated to '%s'", alert_id, status)
    except Exception:
        logger.exception("Failed to update alert id=%s status", alert_id)
        raise
    finally:
        cursor.close()
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# Task agent execution summary
# ═══════════════════════════════════════════════════════════════════

def initialize_task_agent_execution(alert_id: int) -> int:
    """Create a new task_agent_execution_summary row for this alert.

    Returns existing execution_id if one already exists in_progress/completed.
    """
    conn = get_db_conn()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT id FROM task_agent_execution_summary
            WHERE task_agent_alert_id = %s
              AND task_agent_status IN ('in_progress', 'completed')
            """,
            (alert_id,),
        )
        existing = cursor.fetchone()
        if existing:
            return existing["id"]

        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO task_agent_execution_summary
                (task_agent_alert_id, task_agent_execution_nodes, task_agent_full_result, task_agent_status)
            VALUES (%s, %s, %s, 'in_progress')
            """,
            (alert_id, "[]", '{"task_agent_summary":{}}'),
        )
        execution_id = cursor.lastrowid
        conn.commit()
        logger.info("Initialized task_agent execution id=%s for alert_id=%s", execution_id, alert_id)
        return execution_id
    except Exception:
        logger.exception("Failed to initialize task_agent execution for alert_id=%s", alert_id)
        raise
    finally:
        cursor.close()
        conn.close()


def store_node_execution_summary(
    alert_id: int,
    node_name: str,
    execution_order: int,
    status: str,
    result_summary: str,
    full_result=None,
    error_message: str = None,
) -> None:
    """Append a node execution record to task_agent_execution_nodes JSON array."""
    conn = get_db_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id, task_agent_execution_nodes
            FROM task_agent_execution_summary
            WHERE task_agent_alert_id = %s
            ORDER BY id DESC LIMIT 1
            """,
            (alert_id,),
        )
        existing = cursor.fetchone()

        def _normalize(fr):
            if fr is None:
                return None
            if isinstance(fr, (dict, list)):
                return fr
            if isinstance(fr, str):
                return {"result": fr}
            return {"result": str(fr)}

        node_data = {
            "node_name": node_name,
            "execution_order": execution_order,
            "status": status,
            "result_summary": result_summary,
            "execution_time": datetime.now().isoformat(),
            "error_message": error_message,
        }
        normalized = _normalize(full_result)
        if normalized is not None:
            node_data["full_result"] = normalized

        if existing:
            execution_id, nodes_json = existing
            nodes = json.loads(nodes_json) if nodes_json else []
            nodes.append(node_data)
            total = len(nodes)
            successful = len([n for n in nodes if n.get("status") == "success"])
            failed = len([n for n in nodes if n.get("status") == "error"])
            cursor.execute(
                """
                UPDATE task_agent_execution_summary
                SET task_agent_execution_nodes = %s,
                    task_agent_total_nodes = %s,
                    task_agent_successful_nodes = %s,
                    task_agent_failed_nodes = %s
                WHERE id = %s
                """,
                (json.dumps(nodes), total, successful, failed, execution_id),
            )
        else:
            execution_id = initialize_task_agent_execution(alert_id)
            successful = 1 if status == "success" else 0
            failed = 1 if status == "error" else 0
            cursor.execute(
                """
                UPDATE task_agent_execution_summary
                SET task_agent_execution_nodes = %s,
                    task_agent_total_nodes = 1,
                    task_agent_successful_nodes = %s,
                    task_agent_failed_nodes = %s
                WHERE id = %s
                """,
                (json.dumps([node_data]), successful, failed, execution_id),
            )
        conn.commit()
    except Exception:
        logger.exception("Failed to store node execution summary for alert_id=%s node=%s", alert_id, node_name)
        raise
    finally:
        cursor.close()
        conn.close()


def update_task_agent_execution(
    execution_id: int,
    nodes_data: list,
    full_result_data: dict,
    status: str = "in_progress",
    confidence_score: float = None,
) -> None:
    """Update the full execution record with all node data, result summary, and confidence."""
    conn = get_db_conn()
    cursor = conn.cursor()
    try:
        # Backfill root_cause into summary if missing
        summary_rc = full_result_data.get("task_agent_summary", {}).get("root_cause")
        if not summary_rc:
            for node in reversed(nodes_data):
                rc = node.get("root_cause")
                if rc:
                    full_result_data.setdefault("task_agent_summary", {})["root_cause"] = rc
                    break

        total = len(nodes_data)
        successful = len([n for n in nodes_data if n.get("status") == "success"])
        failed = len([n for n in nodes_data if n.get("status") == "error"])

        cursor.execute(
            """
            UPDATE task_agent_execution_summary
            SET task_agent_execution_nodes = %s,
                task_agent_full_result = %s,
                task_agent_status = %s,
                confidence_score = %s,
                task_agent_total_nodes = %s,
                task_agent_successful_nodes = %s,
                task_agent_failed_nodes = %s
            WHERE id = %s
            """,
            (
                json.dumps(nodes_data),
                json.dumps(full_result_data),
                status,
                confidence_score,
                total,
                successful,
                failed,
                execution_id,
            ),
        )
        conn.commit()
    except Exception:
        logger.exception("Failed to update task_agent execution id=%s", execution_id)
        raise
    finally:
        cursor.close()
        conn.close()


def finalize_task_agent_execution(execution_id: int, final_status: str = "completed") -> None:
    """Set end time and final status on a task_agent_execution_summary record."""
    conn = get_db_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE task_agent_execution_summary
            SET task_agent_end_time = CURRENT_TIMESTAMP,
                task_agent_status = %s
            WHERE id = %s
            """,
            (final_status, execution_id),
        )
        conn.commit()
    except Exception:
        logger.exception("Failed to finalize task_agent execution id=%s", execution_id)
        raise
    finally:
        cursor.close()
        conn.close()


def get_task_agent_execution_summary(alert_id: int) -> dict | None:
    """Get the most recent task_agent execution summary for an alert."""
    conn = get_db_conn()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT * FROM task_agent_execution_summary
            WHERE task_agent_alert_id = %s
            ORDER BY id DESC LIMIT 1
            """,
            (alert_id,),
        )
        result = cursor.fetchone()
        if result:
            if result.get("task_agent_execution_nodes"):
                result["task_agent_execution_nodes"] = json.loads(result["task_agent_execution_nodes"])
            if result.get("task_agent_full_result"):
                result["task_agent_full_result"] = json.loads(result["task_agent_full_result"])
        return result
    except Exception:
        logger.exception("Failed to get task_agent summary for alert_id=%s", alert_id)
        raise
    finally:
        cursor.close()
        conn.close()


def get_task_agent_execution_for_email(alert_id: int, workflow_type: str = "infrastructure") -> str:
    """Build a formatted plain-text summary of the workflow execution for email."""
    execution_data = get_task_agent_execution_summary(alert_id)
    if not execution_data:
        return "No task agent execution history available."

    nodes = execution_data.get("task_agent_execution_nodes", [])
    full_result = execution_data.get("task_agent_full_result", {})
    summary = full_result.get("task_agent_summary", {})

    header = "=== Task Agent — Infrastructure (Device) Workflow Summary ==="
    lines = [header, "=" * len(header), ""]
    lines.append(f"🏗️  Workflow Type  : {workflow_type.title()}")
    lines.append(f"📊  Total Steps    : {summary.get('total_steps', len(nodes))}")
    lines.append(f"✅  Completed      : {summary.get('completed_steps', len([n for n in nodes if n.get('status') == 'success']))}")
    lines.append(f"🎯  Final Status   : {summary.get('workflow_status', 'unknown').upper()}")
    lines.append(f"🔒  Confidence     : {summary.get('confidence_score', 0)}%")
    lines.append("")
    lines.append("📋 Node Execution Details:")
    lines.append("-" * 40)

    for i, node in enumerate(nodes, 1):
        if not isinstance(node, dict):
            continue
        s = node.get("status", "unknown")
        icon = "✅" if s == "success" else "❌" if s == "error" else "⚠️"
        lines.append(f"{i}. {icon} {node.get('node_name', 'Unknown Node')}")
        lines.append(f"   Status : {s.upper()}")
        lines.append(f"   Result : {node.get('result_summary', 'No summary')}")
        if node.get("error_message"):
            lines.append(f"   ❗ Error: {node['error_message']}")
        if node.get("execution_time"):
            lines.append(f"   🕒 Time : {node['execution_time']}")
        lines.append("")

    lines.append("-" * 50)
    lines.append(f"Completed at: {execution_data.get('task_agent_end_time', 'In Progress')}")
    return "\n".join(lines)
