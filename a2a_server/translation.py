"""
SALUTE / PACE → A2A Translation
================================
Maps internal Organization Kernel state to A2A protocol constructs.
- SALUTE reports → A2A task status updates
- PACE levels → A2A task states
- Graph traversal events → human-readable status messages
- Files modified → A2A artifacts
"""

import json
import mimetypes
import os
from datetime import datetime, timezone
from typing import Any

from . import task_registry as tr

# PACE → A2A state mapping
PACE_STATE_MAP = {
    "primary": tr.STATE_WORKING,
    "alternate": tr.STATE_WORKING,
    "contingent": tr.STATE_INPUT_REQUIRED,
    "emergency": tr.STATE_FAILED,
}


def salute_to_a2a_state(salute: dict) -> str:
    """Map a SALUTE report to an A2A task state."""
    status = salute.get("status", {})
    pace_level = status.get("pace_level", "primary")
    state = status.get("state", "active")

    # Emergency / abort
    if pace_level == "emergency" or state == "aborted":
        return tr.STATE_FAILED

    # Contingent / escalating
    if pace_level == "contingent" or state == "escalating":
        return tr.STATE_INPUT_REQUIRED

    # Active states
    if state in ("active", "error_recovery"):
        return tr.STATE_WORKING

    # Idle (task not yet started processing internally)
    if state == "idle":
        return tr.STATE_WORKING

    return tr.STATE_WORKING


def salute_to_status_message(salute: dict) -> dict:
    """Convert a SALUTE report to an A2A status message."""
    activity = salute.get("activity", {})
    status = salute.get("status", {})
    unit = salute.get("unit", {})

    plan = activity.get("htn_plan", "")
    step = activity.get("htn_step", 0)
    total = activity.get("htn_total_steps", 0)
    progress = status.get("progress", 0)
    pace_level = status.get("pace_level", "primary")
    role_name = unit.get("role_name", "")
    tool = activity.get("current_tool", "")

    # Build human-readable status text
    parts = []

    if plan:
        plan_name = plan.replace("_", " ").title()
        if step and total:
            parts.append(f"{plan_name}: step {step}/{total}")
        else:
            parts.append(plan_name)

    if progress and progress > 0:
        parts.append(f"{int(progress * 100)}% complete")

    if role_name:
        parts.append(f"role: {role_name}")

    if tool:
        parts.append(f"tool: {tool}")

    if pace_level == "alternate":
        parts.append("retrying with alternative approach")
    elif pace_level == "contingent":
        parts.append("needs guidance")
    elif pace_level == "emergency":
        parts.append("critical failure")

    text = ", ".join(parts) if parts else "Working..."

    return {
        "role": "agent",
        "parts": [{"type": "text", "text": text}],
    }


def salute_to_sse_event(task_id: str, context_id: str, salute: dict) -> dict:
    """Build an SSE event payload from a SALUTE report."""
    return {
        "status_update": {
            "taskId": task_id,
            "contextId": context_id,
            "status": {
                "state": salute_to_a2a_state(salute),
                "message": salute_to_status_message(salute),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }
    }


def build_contingent_message(salute: dict, graph_events: list | None = None) -> str:
    """Build a detailed input-required message for PACE contingent.

    Explains what was tried, what failed, and what guidance would help.
    """
    activity = salute.get("activity", {})
    status = salute.get("status", {})

    parts = []

    # What was being attempted
    task = activity.get("current_task", "")
    if task:
        parts.append(f"Task: {task}")

    plan = activity.get("htn_plan", "")
    step = activity.get("htn_step", 0)
    total = activity.get("htn_total_steps", 0)
    if plan:
        parts.append(f"Workflow: {plan.replace('_', ' ').title()}, step {step}/{total}")

    # What failed (from graph events if available)
    if graph_events:
        failures = [
            e for e in graph_events
            if e.get("type") in ("node_verified", "retry_triggered")
            and e.get("outcome") == "fail"
        ]
        if failures:
            fail_nodes = [e.get("node", "") for e in failures[-3:]]
            parts.append(f"Failed steps: {', '.join(fail_nodes)}")

    # Tool failure info
    env = salute.get("environment", {})
    consecutive_failures = env.get("tool_failures_consecutive", 0)
    total_failures = env.get("tool_failures_total", 0)
    if consecutive_failures > 0:
        parts.append(f"Tool failures: {consecutive_failures} consecutive, {total_failures} total")

    # What would help
    parts.append(
        "The agent has exhausted automatic recovery options. "
        "Please provide additional guidance, clarify requirements, "
        "or suggest an alternative approach."
    )

    return "\n".join(parts)


def build_failure_report(salute: dict, result_text: str | None = None) -> str:
    """Build a structured failure report for PACE emergency."""
    activity = salute.get("activity", {})
    status = salute.get("status", {})
    env = salute.get("environment", {})
    time_data = salute.get("time", {})

    parts = ["=== Task Failure Report ===", ""]

    # What was being done
    task = activity.get("current_task", "")
    plan = activity.get("htn_plan", "")
    if task:
        parts.append(f"Task: {task}")
    if plan:
        step = activity.get("htn_step", 0)
        total = activity.get("htn_total_steps", 0)
        progress = status.get("progress", 0)
        parts.append(f"Workflow: {plan.replace('_', ' ').title()}")
        parts.append(f"Progress: step {step}/{total} ({int(progress * 100)}%)")

    # Resources used
    turns = time_data.get("turns_elapsed", 0)
    ctx_fill = env.get("context_fill_pct", 0)
    if turns:
        parts.append(f"Turns elapsed: {turns}")
    if ctx_fill:
        parts.append(f"Context utilization: {int(ctx_fill * 100)}%")

    # Failure details
    failures = env.get("tool_failures_total", 0)
    if failures:
        parts.append(f"Total tool failures: {failures}")

    # Partial results
    if result_text:
        parts.append("")
        parts.append("Partial output:")
        parts.append(result_text[:2000])

    return "\n".join(parts)


def collect_artifacts(salute: dict) -> list[dict]:
    """Collect artifacts from a completed task based on SALUTE report."""
    artifacts = []
    location = salute.get("location", {})
    files_modified = location.get("files_modified", [])

    for filepath in files_modified:
        artifact = _file_to_artifact(filepath)
        if artifact:
            artifacts.append(artifact)

    return artifacts


def _file_to_artifact(filepath: str) -> dict | None:
    """Convert a file path to an A2A artifact."""
    try:
        if not os.path.isfile(filepath):
            return None

        size = os.path.getsize(filepath)
        if size > 1_000_000:  # 1MB limit for inline content
            return {
                "name": os.path.basename(filepath),
                "parts": [{"type": "text", "text": f"[File too large: {filepath} ({size} bytes)]"}],
                "metadata": {
                    "mimeType": _guess_mime(filepath),
                    "path": filepath,
                    "size": size,
                },
            }

        mime = _guess_mime(filepath)
        if mime and mime.startswith("text/") or filepath.endswith((".py", ".js", ".ts", ".json", ".md", ".sh", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".xml", ".html", ".css")):
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return {
                "name": os.path.basename(filepath),
                "parts": [{"type": "text", "text": content}],
                "metadata": {"mimeType": mime, "path": filepath},
            }
        else:
            import base64
            with open(filepath, "rb") as f:
                data = base64.b64encode(f.read()).decode("ascii")
            return {
                "name": os.path.basename(filepath),
                "parts": [{"type": "data", "data": data}],
                "metadata": {"mimeType": mime, "path": filepath, "encoding": "base64"},
            }

    except Exception:
        return None


def _guess_mime(filepath: str) -> str:
    """Guess MIME type from file extension."""
    mime, _ = mimetypes.guess_type(filepath)
    return mime or "application/octet-stream"
